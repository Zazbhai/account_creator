from flask import Flask, request, jsonify, session, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
from datetime import datetime
import json
import caller

app = Flask(__name__, static_folder='dist', static_url_path='')
app.secret_key = os.environ.get("SECRET_KEY", "your-secret-key-change-this-in-production")
CORS(app, supports_credentials=True, origins=['http://localhost:3000', 'http://127.0.0.1:3000'])
socketio = SocketIO(app, cors_allowed_origins=['http://localhost:3000', 'http://127.0.0.1:3000'], async_mode='threading')

# Simple file-based storage
USERS_FILE = Path("users.json")
API_SETTINGS_FILE = Path("api_settings.json")
IMAP_CONFIG_FILE = Path("imap_config.json")

if not USERS_FILE.exists():
    with open(USERS_FILE, 'w') as f:
        json.dump({"users": []}, f)

def load_users():
    try:
        with open(USERS_FILE, 'r') as f:
            data = json.load(f)
            return data.get("users", [])
    except:
        return []

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump({"users": users}, f, indent=2)


def load_imap_config() -> dict:
    try:
        with open(IMAP_CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


DEFAULT_API_SETTINGS = {
    "base_url": caller.BASE_URL,
    "service": caller.SERVICE,
    "operator": caller.OPERATOR,
    "country": caller.COUNTRY,
    "default_price": 6.99,
}


def load_api_settings() -> dict:
    """Load API settings for Temporasms (URL, service, operator, country, default price)."""
    if not API_SETTINGS_FILE.exists():
        with open(API_SETTINGS_FILE, "w") as f:
            json.dump(DEFAULT_API_SETTINGS, f, indent=2)
        return DEFAULT_API_SETTINGS.copy()

    try:
        with open(API_SETTINGS_FILE, "r") as f:
            data = json.load(f)
    except Exception:
        data = {}

    # Ensure all keys exist
    updated = False
    for key, value in DEFAULT_API_SETTINGS.items():
        if key not in data:
            data[key] = value
            updated = True

    if updated:
        with open(API_SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=2)

    return data

def get_user_by_username(username):
    users = load_users()
    for user in users:
        if user.get("username") == username:
            return user
    return None

def create_user(username, password_hash, role="user", expiry_days=None):
    users = load_users()
    user_id = len(users) + 1
    expiry_date = None
    if expiry_days:
        from datetime import date, timedelta
        expiry_date = (date.today() + timedelta(days=expiry_days)).isoformat()
    users.append({
        "id": user_id,
        "username": username,
        "password_hash": password_hash,
        "role": role,
        "expiry_date": expiry_date,
        "created_at": datetime.now().isoformat()
    })
    save_users(users)
    return user_id

# Initialize default admin user if no users exist
if not load_users():
    admin_hash = generate_password_hash("admin")
    create_user("admin", admin_hash, role="admin", expiry_days=365)

# In-memory log buffer for REAL-TIME log updates
log_buffer = {}
log_lock = threading.Lock()
MAX_LOG_BUFFER_SIZE = 10000

# Worker process tracking
user_processes = {}
user_processes_lock = threading.Lock()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401
        user = get_user_by_username(session.get('username'))
        if not user or user.get('role') != 'admin':
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated_function

def add_log(user_id, message):
    """Add log message to in-memory buffer (REAL-TIME, thread-safe)."""
    with log_lock:
        if user_id not in log_buffer:
            log_buffer[user_id] = []
        log_buffer[user_id].append(message)
        if len(log_buffer[user_id]) > MAX_LOG_BUFFER_SIZE:
            log_buffer[user_id] = log_buffer[user_id][-MAX_LOG_BUFFER_SIZE:]
        print(f"[User {user_id}] {message}")
    socketio.emit('log', {'line': message}, room=f'user_{user_id}')

def clear_user_logs(user_id):
    """Clear logs for a user."""
    with log_lock:
        log_buffer[user_id] = []

def get_user_logs(user_id, limit=100):
    """Get logs for a user."""
    with log_lock:
        logs = log_buffer.get(user_id, [])
        return logs[-limit:] if limit else logs

def compute_balance_and_capacity(user_id, include_price=False):
    """Compute balance and capacity."""
    try:
        # Load per-user API key from IMAP config
        imap_cfg = load_imap_config()
        user_api_key = (imap_cfg.get("api_key") or "").strip()
        if not user_api_key:
            msg = "API key not configured. Please set it in IMAP settings."
            return None, None, None if include_price else None, msg

        # Load shared API settings (URL, service, operator, country)
        api_settings = load_api_settings()

        # Override caller module globals so we use the admin-configured URL/etc
        caller.API_KEY = user_api_key
        caller.BASE_URL = api_settings.get("base_url", caller.BASE_URL)
        caller.SERVICE = api_settings.get("service", caller.SERVICE)
        caller.OPERATOR = api_settings.get("operator", caller.OPERATOR)
        caller.COUNTRY = api_settings.get("country", caller.COUNTRY)

        balance_text = caller.get_balance()
        balance = caller.parse_balance(balance_text)
        if balance is None:
            return None, None, None if include_price else None, "Failed to parse balance"
        price_text = caller.get_price_for_service()
        if not price_text:
            price = float(api_settings.get('default_price', 6.99))
        else:
            try:
                price = float(price_text)
            except ValueError:
                price = 6.99
        capacity = int(balance / price) if price > 0 else 0
        if include_price:
            return balance, capacity, price, None
        return balance, capacity, None
    except Exception as e:
        return None, None, None if include_price else None, str(e)

# API Routes
@app.route('/api/auth/check', methods=['GET'])
def check_auth():
    if 'user_id' not in session:
        return jsonify({"authenticated": False})
    user = get_user_by_username(session.get('username'))
    return jsonify({
        "authenticated": True,
        "user": {
            "id": user.get('id'),
            "username": user.get('username'),
            "role": user.get('role')
        }
    })

@app.route('/api/auth/login', methods=['POST'])
def login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    if not username or not password:
        return jsonify({"success": False, "error": "Please enter both username and password"}), 400
    user = get_user_by_username(username)
    if user and check_password_hash(user.get("password_hash"), password):
        session['user_id'] = user.get("id")
        session['username'] = username
        return jsonify({
            "success": True,
            "user": {
                "id": user.get('id'),
                "username": user.get('username'),
                "role": user.get('role')
            }
        })
    return jsonify({"success": False, "error": "Invalid username or password"}), 401

@app.route('/api/auth/logout', methods=['POST'])
@login_required
def logout():
    session.clear()
    return jsonify({"success": True})

@app.route('/api/balance', methods=['GET'])
@login_required
def api_balance():
    """Get balance and capacity."""
    user_id = session.get('user_id')
    balance, capacity, price, error_msg = compute_balance_and_capacity(user_id, include_price=True)
    if error_msg:
        return jsonify({"error": error_msg})
    socketio.emit('balance', {"balance": balance, "price": price, "capacity": capacity}, room=f'user_{user_id}')
    return jsonify({"balance": balance, "price": price, "capacity": capacity})

@app.route('/api/logs', methods=['GET'])
@login_required
def api_logs():
    """Get logs for user."""
    user_id = session.get('user_id')
    logs = get_user_logs(user_id, limit=5000)
    return jsonify({"logs": logs})

@app.route('/api/worker-status', methods=['GET'])
@login_required
def api_worker_status():
    """Check if workers are still running."""
    user_id = session.get('user_id')
    LOG_DIR = Path("logs")
    completion_file = LOG_DIR / f"user_{user_id}_running.flag"
    running = False
    try:
        if completion_file.exists():
            file_age = time.time() - completion_file.stat().st_mtime
            if file_age > 900:
                completion_file.unlink()
                running = False
            else:
                latest_log = LOG_DIR / "latest_logs.txt"
                if latest_log.exists():
                    with open(latest_log, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if "[INFO] All workers completed!" in content:
                            completion_file.unlink()
                            running = False
                        else:
                            running = True
                else:
                    running = True
    except Exception:
        pass
    socketio.emit('worker_status', {'running': running}, room=f'user_{user_id}')
    return jsonify({'running': running})

@app.route('/api/run', methods=['POST'])
@login_required
def run():
    user_id = session.get('user_id')
    total_accounts = int(request.form.get("total_accounts", 10))
    max_parallel = int(request.form.get("max_parallel", 4))
    
    balance, capacity, price, error_msg = compute_balance_and_capacity(user_id, include_price=True)
    if error_msg:
        return jsonify({"error": error_msg}), 400
    
    if capacity is not None and total_accounts > capacity:
        return jsonify({"error": f'Insufficient balance. You can only create {capacity} account(s).'}), 400
    
    if total_accounts < 1 or max_parallel < 1:
        return jsonify({"error": 'Invalid input values'}), 400
    
    thread = threading.Thread(
        target=run_parallel_sessions,
        args=(total_accounts, max_parallel, user_id),
        daemon=True
    )
    thread.start()
    
    return jsonify({"success": True})

@app.route('/api/stop', methods=['POST'])
@login_required
def api_stop():
    """Stop all workers for current user."""
    user_id = session.get('user_id')
    with user_processes_lock:
        processes = user_processes.get(user_id, [])
        for process in processes:
            try:
                process.kill()
            except Exception:
                pass
        user_processes[user_id] = []
    
    LOG_DIR = Path("logs")
    completion_file = LOG_DIR / f"user_{user_id}_running.flag"
    try:
        if completion_file.exists():
            completion_file.unlink()
    except Exception:
        pass
    
    add_log(user_id, "[INFO] Stop requested by user. Terminating all workers.")
    return jsonify({"status": "stopped"})

@app.route('/api/imap/config', methods=['GET', 'POST'])
@login_required
def imap_config():
    if request.method == 'GET':
        try:
            config = load_imap_config()
            return jsonify({"config": config})
        except:
            return jsonify({"config": {}})
    else:
        config = request.json
        try:
            with open(IMAP_CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=4)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 400


@app.route('/api/admin/api-settings', methods=['GET', 'POST'])
@admin_required
def admin_api_settings():
    """Admin API settings: base URL, service, operator, country, default price."""
    if request.method == 'GET':
        settings = load_api_settings()
        return jsonify({"settings": settings})

    data = request.json or {}
    settings = load_api_settings()

    base_url = data.get("base_url", "").strip() or settings["base_url"]
    service = data.get("service", "").strip() or settings["service"]
    operator = data.get("operator", "").strip() or settings["operator"]
    country = data.get("country", "").strip() or settings["country"]
    default_price = data.get("default_price", settings["default_price"])

    try:
        default_price = float(default_price)
    except (TypeError, ValueError):
        return jsonify({"error": "default_price must be a number"}), 400

    new_settings = {
        "base_url": base_url,
        "service": service,
        "operator": operator,
        "country": country,
        "default_price": default_price,
    }

    try:
        with open(API_SETTINGS_FILE, "w") as f:
            json.dump(new_settings, f, indent=2)
        return jsonify({"success": True, "settings": new_settings})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/admin/users', methods=['GET', 'POST'])
@admin_required
def admin_users():
    if request.method == 'GET':
        users = load_users()
        return jsonify({"users": users})
    else:
        username = request.json.get('username', '').strip()
        password = request.json.get('password', '').strip()
        role = request.json.get('role', 'user').strip()
        expiry_days_str = request.json.get('expiry_days', '').strip()
        expiry_days = None
        if expiry_days_str:
            try:
                expiry_days = int(expiry_days_str)
            except ValueError:
                return jsonify({"error": "Invalid expiry days"}), 400
        if username and password:
            try:
                password_hash = generate_password_hash(password)
                create_user(username, password_hash, role, expiry_days)
                return jsonify({"success": True})
            except Exception as e:
                return jsonify({"error": str(e)}), 400
        return jsonify({"error": "Username and password required"}), 400

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    users = load_users()
    users = [u for u in users if u.get('id') != user_id]
    save_users(users)
    return jsonify({"success": True})

# WebSocket Events
@socketio.on('connect')
def handle_connect():
    if 'user_id' in session:
        user_id = session.get('user_id')
        join_room(f'user_{user_id}')
        emit('connected', {'status': 'connected'})

@socketio.on('disconnect')
def handle_disconnect():
    if 'user_id' in session:
        user_id = session.get('user_id')
        leave_room(f'user_{user_id}')

@socketio.on('join')
def handle_join(data):
    if 'user_id' in session:
        user_id = session.get('user_id')
        join_room(f'user_{user_id}')

def run_account_creator(session_num, total_sessions, user_id):
    """Run a single account creator session."""
    session_id = f"{session_num}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    worker_num = session_num
    LOG_DIR = Path("logs")
    LOG_DIR.mkdir(exist_ok=True)
    latest_log = LOG_DIR / "latest_logs.txt"
    
    try:
        env = os.environ.copy()
        env['USER_ID'] = str(user_id)
        env['SESSION_ID'] = session_id
        env['WORKER_NUM'] = str(worker_num)
        env['PYTHONUNBUFFERED'] = '1'
        
        process = subprocess.Popen(
            ["python", "-u", "account_creator.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env
        )
        
        with user_processes_lock:
            if user_id not in user_processes:
                user_processes[user_id] = []
            user_processes[user_id].append(process)
        
        def read_output():
            try:
                for line in iter(process.stdout.readline, ''):
                    if not line:
                        break
                    line = line.rstrip('\n\r')
                    if line:
                        add_log(user_id, line)
            except Exception as e:
                error_msg = f"[ERROR] Worker {worker_num} output read error: {e}"
                add_log(user_id, error_msg)
        
        output_thread = threading.Thread(target=read_output, daemon=True)
        output_thread.start()
        
        process.wait()
        output_thread.join(timeout=5)
        
    except Exception as e:
        error_msg = f"[ERROR] Worker {worker_num} Exception: {e}"
        add_log(user_id, error_msg)
    finally:
        with user_processes_lock:
            if user_id in user_processes:
                user_processes[user_id] = [p for p in user_processes[user_id] if p.poll() is None]

def run_parallel_sessions(total_accounts, max_parallel, user_id):
    """Run sessions in batches."""
    LOG_DIR = Path("logs")
    LOG_DIR.mkdir(exist_ok=True)
    clear_user_logs(user_id)
    completion_file = LOG_DIR / f"user_{user_id}_running.flag"
    
    try:
        for log_file in LOG_DIR.glob("*"):
            if log_file.is_file() and log_file.name != completion_file.name:
                try:
                    log_file.unlink()
                except Exception:
                    pass
        latest_log = LOG_DIR / "latest_logs.txt"
        start_msg = "[INFO] Starting new batch..."
        add_log(user_id, start_msg)
        with open(latest_log, 'w', encoding='utf-8') as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {start_msg}\n")
        
        with open(completion_file, 'w', encoding='utf-8') as f:
            f.write(f"running\n")
    except Exception as e:
        print(f"[ERROR] Failed to clear logs: {e}")
    
    remaining = total_accounts
    session_num = 1
    
    try:
        while remaining > 0:
            batch_size = min(max_parallel, remaining)
            futures = []
            with ThreadPoolExecutor(max_workers=max_parallel) as executor:
                for i in range(batch_size):
                    current_session = session_num + i
                    if i == 0:
                        futures.append(executor.submit(run_account_creator, current_session, total_accounts, user_id))
                    else:
                        time.sleep(2)
                        futures.append(executor.submit(run_account_creator, current_session, total_accounts, user_id))
                
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        error_msg = f"[ERROR] Batch session error: {e}"
                        add_log(user_id, error_msg)
            
            session_num += batch_size
            remaining -= batch_size
        
        completion_msg = "[INFO] All workers completed!"
        add_log(user_id, completion_msg)
        latest_log = LOG_DIR / "latest_logs.txt"
        try:
            with open(latest_log, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {completion_msg}\n")
        except Exception:
            pass
    finally:
        try:
            if completion_file.exists():
                completion_file.unlink()
        except Exception:
            pass

# Serve React app
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_react(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')

if __name__ == "__main__":
    print("Starting Flask app with SocketIO on http://127.0.0.1:5000")
    socketio.run(app, debug=True, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)
