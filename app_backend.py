from flask import Flask, request, jsonify, session, send_from_directory, send_file
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
import supabase_client
import payment

app = Flask(__name__, static_folder='dist', static_url_path='')
app.secret_key = os.environ.get("SECRET_KEY", "your-secret-key-change-this-in-production")
CORS(app, supports_credentials=True, origins=['http://localhost:3000', 'http://127.0.0.1:3000'])
socketio = SocketIO(app, cors_allowed_origins=['http://localhost:3000', 'http://127.0.0.1:3000'], async_mode='threading')

# Simple file-based storage
USERS_FILE = Path("users.json")
API_SETTINGS_FILE = Path("api_settings.json")
IMAP_CONFIG_FILE = Path("imap_config.json")
MARGIN_FEES_FILE = Path("margin_fees.json")
NUMBER_QUEUE_FILE = Path("number_queue.txt")

if not USERS_FILE.exists():
    with open(USERS_FILE, 'w') as f:
        json.dump({"users": []}, f)

def load_users():
    # Prefer Supabase users table if configured, otherwise fall back to local file.
    if supabase_client.is_enabled():
        try:
            return supabase_client.get_all_users()
        except Exception as e:
            print(f"[WARN] Supabase load_users failed, falling back to file: {e}")
    try:
        with open(USERS_FILE, 'r') as f:
            data = json.load(f)
            return data.get("users", [])
    except Exception:
        return []

def save_users(users):
    # Only used in file-based mode; Supabase paths call supabase_client helpers directly.
    with open(USERS_FILE, 'w') as f:
        json.dump({"users": users}, f, indent=2)


def _find_user_by_id(user_id):
    """Helper to get a single user dict from load_users()."""
    users = load_users()
    for u in users:
        if u.get("id") == user_id:
            return u
    return None


def get_wallet_balance_for_user(user_id: int) -> float:
    """Return the stored internal wallet balance for a user (not the SMS provider balance)."""
    user = _find_user_by_id(user_id)
    if not user:
        return 0.0
    try:
        return float(user.get("wallet_balance") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def add_funds_to_user(user_id: int, amount: float) -> float:
    """
    Add amount to the user's internal wallet balance and return the new balance.
    - When Supabase is enabled, we PATCH the users table (wallet_balance column).
    - In file-based mode, we update users.json.
    """
    if amount <= 0:
        return get_wallet_balance_for_user(user_id)

    users = load_users()
    current_balance = 0.0
    found = False

    for u in users:
        if u.get("id") == user_id:
            try:
                current_balance = float(u.get("wallet_balance") or 0.0)
            except (TypeError, ValueError):
                current_balance = 0.0
            new_balance = current_balance + amount
            u["wallet_balance"] = new_balance
            found = True
            break

    if not found:
        # No user record found in local list; just treat previous as zero.
        new_balance = amount

    # Persist depending on storage backend
    if supabase_client.is_enabled():
        try:
            supabase_client.update_user_wallet(user_id, new_balance)
        except Exception as e:
            print(f"[WARN] Supabase update_user_wallet failed: {e}")
    else:
        save_users(users)

    return new_balance


def load_imap_config() -> dict:
    """Legacy global IMAP config from local json file (used as fallback)."""
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

# Default extra safety buffer per account (margin fees) in rupees.
DEFAULT_MARGIN_PER_ACCOUNT = 2.5


def load_api_settings() -> dict:
    """
    Load API settings for Temporasms (URL, service, operator, country, default price).
    Prefer Supabase api_settings table; fall back to local JSON file.
    """
    if supabase_client.is_enabled():
        try:
            row = supabase_client.get_api_settings()
            if row:
                # Merge with defaults to ensure all keys exist
                merged = {**DEFAULT_API_SETTINGS, **row}
                return merged
        except Exception as e:
            print(f"[WARN] Supabase get_api_settings failed, falling back to file: {e}")

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


def get_margin_per_account(user_id: int) -> float:
    """
    Resolve the margin fee per account for a specific user, in rupees.
    Preference order:
      1) Supabase margin_fees table (per_account_fee for user_id)
      2) Local margin_fees.json file (legacy fallback)
      3) DEFAULT_MARGIN_PER_ACCOUNT constant
    """
    fee = DEFAULT_MARGIN_PER_ACCOUNT

    # Supabase source - per-user margin fees
    if supabase_client.is_enabled():
        try:
            row = supabase_client.get_margin_fee_by_user(user_id)
            if row and row.get("per_account_fee") is not None:
                fee = float(row["per_account_fee"])
        except Exception as e:
            print(f"[WARN] Supabase get_margin_fee_by_user failed for user {user_id}, using fallback: {e}")

    # Local file fallback if Supabase not configured or returned nothing
    if (not supabase_client.is_enabled()) or (fee == DEFAULT_MARGIN_PER_ACCOUNT):
        if MARGIN_FEES_FILE.exists():
            try:
                with open(MARGIN_FEES_FILE, "r") as f:
                    data = json.load(f) or {}
                local_fee = float(data.get("per_account_fee") or fee)
                if local_fee > 0:
                    fee = local_fee
            except Exception:
                pass

    # Ensure a sane positive value
    try:
        if fee <= 0:
            fee = DEFAULT_MARGIN_PER_ACCOUNT
    except Exception:
        fee = DEFAULT_MARGIN_PER_ACCOUNT

    return fee


def get_user_margin_balance(user_id: int) -> float:
    """
    Get the margin_balance for a specific user from margin_fees table.
    Falls back to wallet_balance from users table if margin_fees row doesn't exist.
    """
    if supabase_client.is_enabled():
        try:
            row = supabase_client.get_margin_fee_by_user(user_id)
            if row and row.get("margin_balance") is not None:
                return float(row["margin_balance"])
        except Exception as e:
            print(f"[WARN] Supabase get_margin_fee_by_user failed for user {user_id}: {e}")
    
    # Fallback to wallet_balance from users table
    return get_wallet_balance_for_user(user_id)


def get_total_margin_balance() -> float:
    """
    Compute the total margin-fees balance across all users
    by summing their wallet_balance field.
    """
    users = load_users()
    total = 0.0
    for u in users:
        try:
            total += float(u.get("wallet_balance") or 0.0)
        except (TypeError, ValueError):
            continue
    return total


def process_number_cancel_queue_once() -> None:
    """
    Read queued request_ids from NUMBER_QUEUE_FILE and cancel any whose
    scheduled cancel_after time has passed. Rewrites the file with remaining.
    """
    if not NUMBER_QUEUE_FILE.exists():
        return
    try:
        with open(NUMBER_QUEUE_FILE, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
    except Exception as e:
        print(f"[NUMBER_QUEUE] Failed to read queue file: {e}")
        return

    if not lines:
        return

    now = time.time()
    remaining: list[str] = []

    for line in lines:
        try:
            req_id, ts_str = line.split(",", 1)
            cancel_after = float(ts_str)
        except Exception:
            continue

        if now >= cancel_after:
            try:
                print(f"[NUMBER_QUEUE] Cancelling {req_id} (due at {cancel_after}, now={now})")
                caller.cancel_number(req_id)
            except Exception as e:
                print(f"[NUMBER_QUEUE] Failed to cancel {req_id}: {e}")
                # Keep it in the queue to retry later
                remaining.append(line)
        else:
            remaining.append(line)

    try:
        with open(NUMBER_QUEUE_FILE, "w", encoding="utf-8") as f:
            for line in remaining:
                f.write(line + "\n")
    except Exception as e:
        print(f"[NUMBER_QUEUE] Failed to rewrite queue file: {e}")


_number_queue_worker_started = False


def ensure_number_queue_worker_started() -> None:
    """
    Start a background daemon thread that continuously processes the
    number cancel queue every few seconds, even when no workers are running.
    """
    global _number_queue_worker_started
    if _number_queue_worker_started:
        return
    _number_queue_worker_started = True

    def _worker():
        while True:
            try:
                process_number_cancel_queue_once()
            except Exception as e:
                print(f"[NUMBER_QUEUE] Worker error: {e}")
            time.sleep(10)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

def get_user_by_username(username):
    if supabase_client.is_enabled():
        try:
            return supabase_client.get_user_by_username(username)
        except Exception as e:
            print(f"[WARN] Supabase get_user_by_username failed, falling back to file: {e}")
    users = load_users()
    for user in users:
        if user.get("username") == username:
            return user
    return None

def create_user(username, password_hash, role="user", expiry_days=None):
    user_id = None
    if supabase_client.is_enabled():
        try:
            user_id = supabase_client.create_user(username, password_hash, role, expiry_days)
            # Create default margin_fees row for the new user
            if user_id:
                try:
                    supabase_client.upsert_margin_fee_for_user(
                        user_id=user_id,
                        per_account_fee=DEFAULT_MARGIN_PER_ACCOUNT,
                        margin_balance=0.0,
                    )
                except Exception as e:
                    print(f"[WARN] Failed to create default margin_fees for user {user_id}: {e}")
            return user_id
        except Exception as e:
            print(f"[WARN] Supabase create_user failed, falling back to file: {e}")
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

# Start background worker that cancels queued numbers after 2 minutes
ensure_number_queue_worker_started()

# In-memory log buffer for REAL-TIME log updates
log_buffer = {}
log_lock = threading.Lock()
MAX_LOG_BUFFER_SIZE = 10000

# Worker process tracking
user_processes = {}
user_processes_lock = threading.Lock()
# Stop flags for each user
user_stop_flags = {}
user_stop_flags_lock = threading.Lock()

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
    """Compute current API balance and how many accounts can be created based on real API price."""
    try:
        # Load per-user API key from IMAP config (Supabase first, then legacy file)
        imap_cfg = {}
        if supabase_client.is_enabled():
            try:
                imap_cfg = supabase_client.get_imap_config(user_id)
            except Exception as e:
                print(f"[WARN] Supabase get_imap_config failed, falling back to file: {e}")
        if not imap_cfg:
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
                price = float(api_settings.get('default_price', 6.99))

        # Capacity is based on the real provider price.
        capacity = int(balance / price) if price > 0 else 0

        # Best-effort: store last known balance/capacity/price in Supabase users table.
        if supabase_client.is_enabled():
            try:
                supabase_client.update_user_balance(user_id, balance, capacity, price)
            except Exception as e:
                print(f"[WARN] Supabase update_user_balance failed: {e}")

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


@app.route('/api/funds', methods=['GET'])
@login_required
def api_funds():
    """Get the internal wallet balance for the current user."""
    user_id = session.get('user_id')
    wallet_balance = get_wallet_balance_for_user(user_id)
    return jsonify({"balance": round(wallet_balance, 2)})


@app.route('/api/margin-fees', methods=['GET'])
@login_required
def api_margin_fees():
    """Get the current margin per-account fee and margin balance for the current user."""
    user_id = session.get('user_id')
    fee = get_margin_per_account(user_id)
    margin_balance = get_user_margin_balance(user_id)
    return jsonify({
        "per_account_fee": round(fee, 4),
        "margin_balance": round(margin_balance, 2),
    })

@app.route('/api/logs', methods=['GET'])
@login_required
def api_logs():
    """Get logs for user."""
    user_id = session.get('user_id')
    logs = get_user_logs(user_id, limit=5000)
    return jsonify({"logs": logs})


@app.route('/api/reports/used-emails', methods=['GET'])
@login_required
def api_used_emails():
    """
    Return or download used emails for the current user.

    Prefer per-user file used_emails_user{user_id}.txt, but fall back to a
    legacy global used_emails.txt if present.
    """
    user_id = session.get('user_id')
    per_user = Path(f"used_emails_user{user_id}.txt")
    legacy = Path("used_emails.txt")

    # If download=1, respond with a text file, preferring the global file
    if request.args.get('download') == '1':
        try:
            target = legacy if legacy.exists() else per_user
            if not target.exists():
                # Create an empty global file if absolutely nothing exists yet
                legacy.touch()
                target = legacy
            return send_file(str(target), mimetype='text/plain', as_attachment=True)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # View mode: prefer the global file, then per-user as fallback
    path = legacy if legacy.exists() else per_user if per_user.exists() else None
    if not path:
        return jsonify({"items": [], "source": "local"})

    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f if line.strip()]
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"items": lines, "source": "local"})


@app.route('/api/reports/failed-numbers', methods=['GET'])
@login_required
def api_failed_numbers():
    """
    Return or download failed numbers for the current user.

    Prefer per-user file failed_numbers_user{user_id}.txt, but fall back to a
    legacy global failed_numbers.txt if present.
    """
    user_id = session.get('user_id')
    per_user = Path(f"failed_numbers_user{user_id}.txt")
    # Support both correct and legacy misspelled filenames
    legacy_main = Path("failed_numbers.txt")
    legacy_alt = Path("failed_numers.txt")

    # If download=1, respond with a text file, preferring the global files
    if request.args.get('download') == '1':
        try:
            # Priority: legacy_alt, legacy_main, per_user
            if legacy_alt.exists():
                target = legacy_alt
            elif legacy_main.exists():
                target = legacy_main
            elif per_user.exists():
                target = per_user
            else:
                # Create empty main global file if nothing exists
                legacy_main.touch()
                target = legacy_main
            return send_file(str(target), mimetype='text/plain', as_attachment=True)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # View mode: prefer global files, then per-user
    if legacy_alt.exists():
        path = legacy_alt
    elif legacy_main.exists():
        path = legacy_main
    elif per_user.exists():
        path = per_user
    else:
        path = None
    if not path:
        return jsonify({"items": [], "source": "local"})

    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f if line.strip()]
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"items": lines, "source": "local"})


@app.route('/api/reports/log-files', methods=['GET'])
@login_required
def api_log_files():
    """List available log files in the logs directory."""
    log_dir = Path("logs")
    if not log_dir.exists():
        return jsonify({"files": []})

    files = []
    for p in sorted(log_dir.glob("*.txt")):
        try:
            stat = p.stat()
            files.append(
                {
                    "name": p.name,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                }
            )
        except OSError:
            continue

    return jsonify({"files": files})


@app.route('/api/reports/log-file', methods=['GET'])
@login_required
def api_log_file():
    """Return the content of a specific log file, or download it."""
    name = (request.args.get('name') or '').strip()
    if not name:
        return jsonify({"error": "Missing log file name"}), 400

    # Prevent path traversal; only allow plain filenames inside logs/
    safe_name = os.path.basename(name)
    log_dir = Path("logs")
    file_path = log_dir / safe_name

    if not file_path.exists() or not file_path.is_file():
        return jsonify({"error": "Log file not found"}), 404

    if request.args.get('download') == '1':
        try:
            return send_file(str(file_path), mimetype='text/plain', as_attachment=True)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        stat = file_path.stat()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify(
        {
            "name": safe_name,
            "content": content,
            "size": stat.st_size,
            "modified": stat.st_mtime,
        }
    )

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
    use_used_account_raw = (request.form.get("use_used_account", "1") or "").strip().lower()
    use_used_account = use_used_account_raw in ("1", "true", "on", "yes")

    if total_accounts < 1 or max_parallel < 1:
        return jsonify({"error": "Invalid input values"}), 400

    balance, capacity, price, error_msg = compute_balance_and_capacity(user_id, include_price=True)
    if error_msg:
        return jsonify({"error": error_msg}), 400

    # First, enforce limit based on real provider price/capacity
    if capacity is not None and total_accounts > capacity:
        if balance is not None and price:
            required_balance = total_accounts * price
            amount_needed = max(0.0, round(required_balance - balance, 2))
        else:
            required_balance = None
            amount_needed = None

        return (
            jsonify(
                {
                    "error": f"Insufficient balance. You can only create {capacity} account(s).",
                    "amount_needed": amount_needed,
                    "required_balance": required_balance,
                    "balance": balance,
                }
            ),
            400,
        )

    # Second, enforce margin-fees buffer: check that user has enough margin_balance
    # in margin_fees table (separate from SMS provider balance).
    margin_per_account = get_margin_per_account(user_id)
    required_margin = total_accounts * margin_per_account
    
    # Get margin_balance from margin_fees table
    margin_balance = get_user_margin_balance(user_id)
    
    if margin_balance < required_margin:
        # How much extra margin balance is needed
        extra_needed = max(0.0, round(required_margin - margin_balance, 2))

        return (
            jsonify(
                {
                    "error": (
                        f"Insufficient margin fees. For {total_accounts} account(s) you need at least "
                        f"₹{required_margin:.2f} as margin buffer "
                        f"(₹{margin_per_account:.2f} per account). "
                        f"Your current margin balance is ₹{margin_balance:.2f}."
                    ),
                    "amount_needed": extra_needed,
                    "required_margin": round(required_margin, 2),
                    "margin_balance": round(margin_balance, 2),
                    "margin_per_account": round(margin_per_account, 4),
                }
            ),
            400,
        )

    # Get retry_failed flag from form data
    retry_failed_raw = request.form.get("retry_failed", "1").strip().lower()
    retry_failed = retry_failed_raw in ("1", "true", "on", "yes")
    
    thread = threading.Thread(
        target=run_parallel_sessions,
        args=(total_accounts, max_parallel, user_id, use_used_account, retry_failed),
        daemon=True
    )
    thread.start()

    return jsonify({"success": True})


@app.route('/api/funds/add', methods=['POST'])
@login_required
def api_add_funds():
    """
    Verify payment via payment.py and credit the confirmed amount
    to the user's internal wallet balance.
    """
    user_id = session.get('user_id')
    data = request.json or {}

    raw_amount = data.get("amount")
    utr = str(data.get("utr", "")).strip()

    if not utr:
        return jsonify({"error": "UTR / RRN number is required"}), 400

    try:
        requested_amount = float(raw_amount)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid amount"}), 400

    if requested_amount <= 0:
        return jsonify({"error": "Amount must be greater than zero"}), 400

    # Ask BharatPe API (via payment.py) to verify the payment
    try:
        ok, paid_amount = payment.payment_checker(utr)
    except Exception as e:
        return jsonify({"error": f"Payment verification failed: {e}"}), 400

    if not ok:
        return jsonify({"error": "Payment not found or not confirmed for this UTR"}), 400

    try:
        paid_amount = float(paid_amount)
    except (TypeError, ValueError):
        paid_amount = 0.0

    if paid_amount <= 0:
        return jsonify({"error": "Verified payment amount is zero or invalid"}), 400

    # Credit exactly the paid amount, regardless of the requested_amount
    new_balance = add_funds_to_user(user_id, paid_amount)

    # Update margin_balance in margin_fees table by adding the paid amount to existing balance
    if supabase_client.is_enabled():
        try:
            # Get current margin_balance and per_account_fee to preserve them
            current_fee = get_margin_per_account(user_id)
            
            # Get current margin_balance from margin_fees table (not wallet_balance)
            current_margin_balance = 0.0
            try:
                row = supabase_client.get_margin_fee_by_user(user_id)
                if row and row.get("margin_balance") is not None:
                    current_margin_balance = float(row["margin_balance"])
            except Exception:
                # If row doesn't exist, start with 0.0
                current_margin_balance = 0.0
            
            # Add the paid amount to existing margin_balance
            new_margin_balance = current_margin_balance + paid_amount
            
            # Upsert will create the row if it doesn't exist, or update if it does
            supabase_client.upsert_margin_fee_for_user(
                user_id=user_id,
                per_account_fee=current_fee,
                margin_balance=new_margin_balance,
            )
        except Exception as e:
            print(f"[WARN] Failed to update margin_fees for user {user_id}: {e}")

    return jsonify(
        {
            "success": True,
            "credited": round(paid_amount, 2),
            "requested_amount": round(requested_amount, 2),
            "wallet_balance": round(new_balance, 2),
        }
    )

@app.route('/api/stop', methods=['POST'])
@login_required
def api_stop():
    """Stop all workers for current user."""
    user_id = session.get('user_id')
    
    # Set stop flag
    with user_stop_flags_lock:
        user_stop_flags[user_id] = True
    
    # Kill all processes
    with user_processes_lock:
        processes = user_processes.get(user_id, [])
        for process in processes:
            try:
                if process.poll() is None:  # Process is still running
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()  # Force kill if terminate didn't work
            except Exception as e:
                print(f"[WARN] Error stopping process: {e}")
        user_processes[user_id] = []
    
    # Remove completion flag file
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
    user_id = session.get('user_id')
    if request.method == 'GET':
        # Prefer per-user config in Supabase, fall back to legacy local file.
        if supabase_client.is_enabled():
            try:
                cfg = supabase_client.get_imap_config(user_id)
                return jsonify({"config": cfg or {}})
            except Exception as e:
                print(f"[WARN] Supabase get_imap_config failed, falling back to file: {e}")
        try:
            config = load_imap_config()
            return jsonify({"config": config})
        except Exception:
            return jsonify({"config": {}})
    else:
        config = request.json or {}
        # Save to Supabase if available
        if supabase_client.is_enabled():
            try:
                supabase_client.upsert_imap_config(user_id, config)
            except Exception as e:
                print(f"[WARN] Supabase upsert_imap_config failed: {e}")
        # Also persist to local file as a simple backup
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

    # Persist to Supabase if available
    if supabase_client.is_enabled():
        try:
            supabase_client.upsert_api_settings(new_settings)
        except Exception as e:
            print(f"[WARN] Supabase upsert_api_settings failed: {e}")

    # Also keep local JSON as a simple backup
    try:
        with open(API_SETTINGS_FILE, "w") as f:
            json.dump(new_settings, f, indent=2)
        return jsonify({"success": True, "settings": new_settings})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/admin/margin-fees', methods=['GET', 'POST'])
@admin_required
def admin_margin_fees():
    """
    Admin margin fees config: returns admin's per-account fee and total margin balance.
    Note: This endpoint is for admin's own margin fee. For managing other users' fees, use /api/admin/users.
    """
    if request.method == 'GET':
        # Get admin's own margin fee
        admin_user_id = session.get('user_id')
        fee = get_margin_per_account(admin_user_id) if admin_user_id else DEFAULT_MARGIN_PER_ACCOUNT
        total_margin = get_total_margin_balance()
        return jsonify(
            {
                "per_account_fee": round(fee, 4),
                "margin_balance": round(total_margin, 2),
            }
        )

    data = request.json or {}
    raw_fee = data.get("per_account_fee")
    try:
        fee = float(raw_fee)
    except (TypeError, ValueError):
        return jsonify({"error": "per_account_fee must be a number"}), 400

    if fee <= 0:
        return jsonify({"error": "per_account_fee must be greater than zero"}), 400

    # Persist to Supabase if available
    if supabase_client.is_enabled():
        try:
            total_margin = get_total_margin_balance()
            supabase_client.upsert_margin_fee(fee, margin_balance=total_margin)
        except Exception as e:
            print(f"[WARN] Supabase upsert_margin_fee failed: {e}")

    # Also keep local JSON as a simple backup
    try:
        with open(MARGIN_FEES_FILE, "w") as f:
            json.dump({"per_account_fee": fee}, f, indent=2)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"success": True, "per_account_fee": round(fee, 4)})

@app.route('/api/admin/users', methods=['GET', 'POST'])
@admin_required
def admin_users():
    if request.method == 'GET':
        users = load_users()
        # Enrich each user with margin fee data
        for user in users:
            user_id = user.get('id')
            if user_id:
                try:
                    fee = get_margin_per_account(user_id)
                    margin_balance = get_user_margin_balance(user_id)
                    user['per_account_fee'] = round(fee, 4)
                    user['margin_balance'] = round(margin_balance, 2)
                except Exception as e:
                    print(f"[WARN] Failed to load margin fees for user {user_id}: {e}")
                    user['per_account_fee'] = DEFAULT_MARGIN_PER_ACCOUNT
                    user['margin_balance'] = 0.0
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
    # Prefer Supabase delete if configured
    if supabase_client.is_enabled():
        try:
            supabase_client.delete_user(user_id)
            return jsonify({"success": True})
        except Exception as e:
            print(f"[WARN] Supabase delete_user failed, falling back to file: {e}")

    users = load_users()
    users = [u for u in users if u.get('id') != user_id]
    save_users(users)
    return jsonify({"success": True})


@app.route('/api/admin/users/<int:user_id>/expiry', methods=['PATCH'])
@admin_required
def update_user_expiry(user_id):
    """
    Increase or decrease a user's expiry by delta_days.
    If the user has no expiry_date, we start from today.
    """
    data = request.json or {}
    if "delta_days" not in data:
        return jsonify({"error": "delta_days is required"}), 400

    try:
        delta_days = int(data.get("delta_days", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "delta_days must be an integer"}), 400

    users = load_users()
    current = None
    for u in users:
        if u.get("id") == user_id:
            current = u
            break

    if not current:
        return jsonify({"error": "User not found"}), 404

    from datetime import date, timedelta

    today = date.today()
    expiry_str = current.get("expiry_date")
    try:
        base_date = date.fromisoformat(expiry_str) if expiry_str else today
    except Exception:
        base_date = today

    new_date = base_date + timedelta(days=delta_days)
    new_iso = new_date.isoformat()

    # Update via Supabase if available
    if supabase_client.is_enabled():
        try:
            supabase_client.update_user_expiry(user_id, new_iso)
        except Exception as e:
            print(f"[WARN] Supabase update_user_expiry failed: {e}")

    # Also update local cache (file-based fallback)
    for u in users:
        if u.get("id") == user_id:
            u["expiry_date"] = new_iso
    save_users(users)

    return jsonify({"success": True, "expiry_date": new_iso})

@app.route('/api/admin/users/<int:user_id>/margin-fee', methods=['PATCH'])
@admin_required
def update_user_margin_fee(user_id):
    """
    Update a user's per_account_fee in margin_fees table.
    Only per_account_fee can be edited; margin_balance is read-only (synced from wallet_balance).
    """
    data = request.json or {}
    raw_fee = data.get("per_account_fee")
    
    if raw_fee is None:
        return jsonify({"error": "per_account_fee is required"}), 400
    
    try:
        fee = float(raw_fee)
    except (TypeError, ValueError):
        return jsonify({"error": "per_account_fee must be a number"}), 400
    
    if fee <= 0:
        return jsonify({"error": "per_account_fee must be greater than zero"}), 400
    
    # Verify user exists
    user = _find_user_by_id(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    # Get current margin_balance to preserve it
    margin_balance = get_user_margin_balance(user_id)
    
    # Update in Supabase if available
    if supabase_client.is_enabled():
        try:
            supabase_client.upsert_margin_fee_for_user(
                user_id=user_id,
                per_account_fee=fee,
                margin_balance=margin_balance,
            )
        except Exception as e:
            print(f"[WARN] Supabase upsert_margin_fee_for_user failed for user {user_id}: {e}")
            return jsonify({"error": f"Failed to update margin fee: {e}"}), 500
    
    return jsonify({"success": True, "per_account_fee": round(fee, 4)})

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

def run_account_creator(session_num, total_sessions, user_id, use_used_account):
    """Run a single account creator session."""
    session_id = f"{session_num}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    worker_num = session_num
    LOG_DIR = Path("logs")
    LOG_DIR.mkdir(exist_ok=True)
    latest_log = LOG_DIR / "latest_logs.txt"
    
    try:
        # Build environment for worker process, including per-user API credentials
        # and admin-configured API settings so that all SMS API calls use the
        # correct key/base URL/service/operator/country.
        imap_cfg = load_imap_config()
        api_settings = load_api_settings()
        user_api_key = (imap_cfg.get("api_key") or "").strip()

        env = os.environ.copy()
        env['USER_ID'] = str(user_id)
        env['SESSION_ID'] = session_id
        env['WORKER_NUM'] = str(worker_num)
        env['PYTHONUNBUFFERED'] = '1'
        env['USE_USED_ACCOUNT'] = '1' if use_used_account else '0'

        if user_api_key:
            env['API_KEY'] = user_api_key
        env['API_BASE_URL'] = api_settings.get("base_url", caller.BASE_URL)
        env['API_SERVICE'] = api_settings.get("service", caller.SERVICE)
        env['API_OPERATOR'] = api_settings.get("operator", caller.OPERATOR)
        env['API_COUNTRY'] = api_settings.get("country", caller.COUNTRY)
        
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
            """Stream worker stdout into in-memory + file-based logs."""
            worker_log = LOG_DIR / f"worker{worker_num}.txt"
            try:
                with open(worker_log, 'a', encoding='utf-8') as wf, open(
                    latest_log, 'a', encoding='utf-8'
                ) as lf:
                    for line in iter(process.stdout.readline, ''):
                        if not line:
                            break
                        line = line.rstrip('\n\r')
                        if not line:
                            continue

                        # In-memory + websocket log
                        add_log(user_id, line)

                        # File-based logs with timestamp and worker number
                        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        tagged = f"[{ts}] [W{worker_num}] {line}\n"
                        try:
                            wf.write(tagged)
                            wf.flush()
                        except Exception:
                            # Don't let file I/O break the worker
                            pass
                        try:
                            lf.write(tagged)
                            lf.flush()
                        except Exception:
                            pass
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

def run_parallel_sessions(total_accounts, max_parallel, user_id, use_used_account, retry_failed=True):
    """Run sessions in batches."""
    LOG_DIR = Path("logs")
    LOG_DIR.mkdir(exist_ok=True)
    clear_user_logs(user_id)
    completion_file = LOG_DIR / f"user_{user_id}_running.flag"
    
    # Clear stop flag for this user
    with user_stop_flags_lock:
        user_stop_flags[user_id] = False
    
    try:
        # Delete ALL files in logs folder before starting a new batch
        for log_file in LOG_DIR.glob("*"):
            if log_file.is_file():
                try:
                    log_file.unlink()
                except Exception as e:
                    print(f"[WARN] Failed to delete {log_file.name}: {e}")
        
        # Create fresh latest_logs.txt
        latest_log = LOG_DIR / "latest_logs.txt"
        start_msg = "[INFO] Starting new batch..."
        add_log(user_id, start_msg)
        with open(latest_log, 'w', encoding='utf-8') as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {start_msg}\n")
        
        # Create completion flag file
        with open(completion_file, 'w', encoding='utf-8') as f:
            f.write(f"running\n")
    except Exception as e:
        print(f"[ERROR] Failed to clear logs: {e}")
    
    remaining = total_accounts
    session_num = 1
    failed_sessions = []  # Track failed sessions for retry
    
    try:
        while remaining > 0:
            # Check if stop was requested
            with user_stop_flags_lock:
                if user_stop_flags.get(user_id, False):
                    add_log(user_id, "[INFO] Stop requested. Stopping batch execution.")
                    break
            batch_size = min(max_parallel, remaining)
            futures = []
            session_map = {}  # Map future to session number
            
            with ThreadPoolExecutor(max_workers=max_parallel) as executor:
                for i in range(batch_size):
                    current_session = session_num + i
                    if i == 0:
                        future = executor.submit(
                            run_account_creator, current_session, total_accounts, user_id, use_used_account
                        )
                        futures.append(future)
                        session_map[future] = current_session
                    else:
                        time.sleep(2)
                        future = executor.submit(
                            run_account_creator, current_session, total_accounts, user_id, use_used_account
                        )
                        futures.append(future)
                        session_map[future] = current_session
                
                for future in as_completed(futures):
                    # Check stop flag again
                    with user_stop_flags_lock:
                        if user_stop_flags.get(user_id, False):
                            break
                    
                    session_num_for_future = session_map.get(future, session_num)
                    try:
                        future.result()
                        # Session completed successfully
                    except Exception as e:
                        error_msg = f"[ERROR] Session {session_num_for_future} failed: {e}"
                        add_log(user_id, error_msg)
                        # Track failed session for retry if enabled
                        if retry_failed:
                            failed_sessions.append(session_num_for_future)
            
            # Check stop flag before continuing
            with user_stop_flags_lock:
                if user_stop_flags.get(user_id, False):
                    break
            
            session_num += batch_size
            remaining -= batch_size
            
            # If retry is enabled and we have failed sessions, retry them
            if retry_failed and failed_sessions:
                retry_count = len(failed_sessions)
                add_log(user_id, f"[INFO] Retrying {retry_count} failed session(s)...")
                # Retry failed sessions one by one
                for failed_session in failed_sessions:
                    # Check stop flag before each retry
                    with user_stop_flags_lock:
                        if user_stop_flags.get(user_id, False):
                            break
                    try:
                        run_account_creator(failed_session, total_accounts, user_id, use_used_account)
                        add_log(user_id, f"[INFO] Retry session {failed_session} completed successfully")
                    except Exception as e:
                        error_msg = f"[ERROR] Retry session {failed_session} failed again: {e}"
                        add_log(user_id, error_msg)
                # Clear failed sessions after retry attempt
                failed_sessions = []
        
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
