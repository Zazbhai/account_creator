from flask import Flask, request, jsonify, session, send_from_directory, send_file
from datetime import timedelta
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
import neon_client as supabase_client
import payment
import imap

# Load environment variables from .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, use system environment variables

app = Flask(__name__, static_folder='dist', static_url_path='')
app.secret_key = os.environ.get("SECRET_KEY", "your-secret-key-change-this-in-production")
# Make sessions persistent (30 days)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# CORS configuration from environment variables
# For tunneling (ngrok, etc.), set FRONTEND_URL to your tunneled frontend URL
# Example: FRONTEND_URL=https://abc123.ngrok-free.app
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:7333")
CORS_ORIGINS_STR = os.environ.get("CORS_ORIGINS", "")
if CORS_ORIGINS_STR:
    # If CORS_ORIGINS is explicitly set, use it
    CORS_ORIGINS = [origin.strip() for origin in CORS_ORIGINS_STR.split(",")]
else:
    # Otherwise, use FRONTEND_URL and add localhost fallbacks
    CORS_ORIGINS = [FRONTEND_URL]
    if "localhost" in FRONTEND_URL or "127.0.0.1" in FRONTEND_URL:
        # Only add localhost variants if FRONTEND_URL is localhost
        CORS_ORIGINS.extend(["http://localhost:7333", "http://127.0.0.1:7333"])

CORS(app, supports_credentials=True, origins=CORS_ORIGINS)
# Optimize for 4 vCPU, 16GB RAM: Use threading mode with max_http_buffer_size limit
socketio = SocketIO(
    app, 
    cors_allowed_origins=CORS_ORIGINS, 
    async_mode='threading',
    max_http_buffer_size=1e6,  # 1MB limit to prevent memory issues
    ping_timeout=60,
    ping_interval=25
)

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
    """Load users from Neon database only (no file fallback)."""
    if not supabase_client.is_enabled():
        raise RuntimeError("Database not configured - cannot load users")
    try:
        return supabase_client.get_all_users()
    except Exception as e:
        print(f"[ERROR] Failed to load users from database: {e}")
        raise

def save_users(users):
    """Deprecated - users are saved directly via supabase_client methods."""
    print("[WARN] save_users() called but users should be saved via database methods directly")
    pass


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
    Saves directly to database only.
    """
    if amount <= 0:
        return get_wallet_balance_for_user(user_id)

    if not supabase_client.is_enabled():
        raise RuntimeError("Database not configured - cannot add funds")

    current_balance = get_wallet_balance_for_user(user_id)
    new_balance = current_balance + amount

    try:
        supabase_client.update_user_wallet(user_id, new_balance)
        print(f"[DEBUG] Added ₹{amount:.2f} to user {user_id}, new balance: ₹{new_balance:.2f}")
    except Exception as e:
        print(f"[ERROR] Failed to update wallet balance in database: {e}")
        raise

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
    "wait_for_otp": 5,  # Default: 5 minutes (for first OTP)
    "wait_for_second_otp": 5,  # Default: 5 minutes (for second/phone OTP)
}

# Default extra safety buffer per account (margin fees) in rupees.
DEFAULT_MARGIN_PER_ACCOUNT = 2.5


def load_api_settings() -> dict:
    """
    Load API settings from Neon database only.
    Returns database values merged with defaults, or just defaults if database has no settings yet.
    """
    # Load from database (single source of truth)
    if supabase_client.is_enabled():
        try:
            row = supabase_client.get_api_settings()
            if row:
                # Merge with defaults to ensure all keys exist
                merged = {**DEFAULT_API_SETTINGS, **row}
                print(f"[DEBUG] [load_api_settings] Loaded from database: {merged}")
                return merged
            else:
                print(f"[DEBUG] [load_api_settings] No settings in database yet, using defaults")
        except Exception as e:
            print(f"[ERROR] [load_api_settings] Database query failed: {e}")
            raise RuntimeError(f"Failed to load API settings from database: {e}")
    else:
        raise RuntimeError("Database not configured - cannot load API settings")
    
    # No settings in database yet, return defaults
    return DEFAULT_API_SETTINGS.copy()


def get_margin_per_account(user_id: int) -> float:
    """
    Get the margin fee per account for a specific user from database only.
    Returns user's margin fee from database, or default if not set.
    """
    if not supabase_client.is_enabled():
        return DEFAULT_MARGIN_PER_ACCOUNT

    try:
        row = supabase_client.get_margin_fee_by_user(user_id)
        if row and row.get("per_account_fee") is not None:
            fee = float(row["per_account_fee"])
            if fee > 0:
                return fee
    except Exception as e:
        print(f"[ERROR] Failed to get margin fee from database for user {user_id}: {e}")

    return DEFAULT_MARGIN_PER_ACCOUNT


def get_user_margin_balance(user_id: int) -> float:
    """
    Get the margin_balance for a specific user from margin_fees table (database only).
    Falls back to wallet_balance from users table if margin_fees row doesn't exist.
    """
    if not supabase_client.is_enabled():
        return 0.0

    try:
        row = supabase_client.get_margin_fee_by_user(user_id)
        if row and row.get("margin_balance") is not None:
            return float(row["margin_balance"])
    except Exception as e:
        print(f"[ERROR] Failed to get margin balance from database for user {user_id}: {e}")
    
    # Fallback to wallet_balance from users table
    return get_wallet_balance_for_user(user_id)


def update_margin_balance(user_id: int, amount: float, reason: str = "", fallback_balance: float = None) -> bool:
    """
    Update margin_balance for a user by adding/subtracting the given amount.
    Positive amount adds to balance, negative amount subtracts from balance.
    Returns True if successful, False otherwise.
    Uses atomic database updates to prevent race conditions.
    """
    try:
        # Validate amount is a number
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            print(f"[ERROR] [update_margin_balance] Invalid amount: {amount}")
            return False
            
        operation = "ADDED" if amount >= 0 else "DEDUCTED"
        print(f"[DEBUG] [update_margin_balance] ========== MARGIN BALANCE UPDATE ==========")
        print(f"[DEBUG] [update_margin_balance] User ID: {user_id}")
        print(f"[DEBUG] [update_margin_balance] Amount: ₹{abs(amount):.2f} ({operation})")
        print(f"[DEBUG] [update_margin_balance] Reason: {reason}")
        
        # Determine fallback balance (wallet balance) in case margin row doesn't exist yet
        # If fallback_balance is provided, use it (useful for deposits where wallet is already updated)
        if fallback_balance is not None:
            fallback_bal = fallback_balance
        else:
            fallback_bal = get_wallet_balance_for_user(user_id)
            
        current_fee = get_margin_per_account(user_id)
        
        # Perform atomic update via Neon client
        if supabase_client.is_enabled():
            try:
                new_balance = supabase_client.atomic_margin_update(
                    user_id=user_id,
                    amount_delta=amount,
                    fallback_start_balance=fallback_bal,
                    default_per_account_fee=current_fee
                )
                
                if new_balance is not None:
                    print(f"[DEBUG] [update_margin_balance] Successfully updated margin_balance. New balance: ₹{new_balance:.2f}")
                    print(f"[DEBUG] [update_margin_balance] ============================================")
                    return True
                else:
                    print(f"[ERROR] [update_margin_balance] Atomic update returned None")
                    return False
            except Exception as e:
                print(f"[ERROR] [update_margin_balance] Failed to update margin_balance in DB: {e}")
                import traceback
                traceback.print_exc()
                return False
        else:
            print(f"[WARN] [update_margin_balance] Database not enabled, cannot update margin_balance")
            return False

    except Exception as e:
        print(f"[ERROR] [update_margin_balance] Exception: {e}")
        import traceback
        traceback.print_exc()
        return False


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
        import traceback
        traceback.print_exc()
        return

    if not lines:
        return

    now = time.time()
    remaining: list[str] = []
    cancelled_count = 0

    for line in lines:
        try:
            parts = line.split(",")
            if len(parts) >= 3:
                # New format: request_id, cancel_after, user_id
                req_id, ts_str, user_id_str = parts[0], parts[1], parts[2]
                user_id = int(user_id_str) if user_id_str.strip() else None
            elif len(parts) == 2:
                # Old format: request_id, cancel_after (backward compatibility)
                req_id, ts_str = parts[0], parts[1]
                user_id = None
            else:
                print(f"[NUMBER_QUEUE] Invalid line format: '{line}'")
                continue
            cancel_after = float(ts_str)
        except Exception as e:
            print(f"[NUMBER_QUEUE] Failed to parse line '{line}': {e}")
            continue

        time_until_cancel = cancel_after - now
        if now >= cancel_after:
            try:
                # Ensure caller is configured before canceling
                # This runs in a background thread, so we need to load settings each time
                api_settings = load_api_settings()
                
                # Load per-user API key if user_id is available
                user_api_key = None
                if user_id:
                    try:
                        if supabase_client.is_enabled():
                            imap_cfg = supabase_client.get_imap_config(user_id)
                            user_api_key = (imap_cfg.get("api_key") or "").strip()
                            if user_api_key:
                                print(f"[NUMBER_QUEUE] Loaded API key for user {user_id} from Supabase (length: {len(user_api_key)})")
                    except Exception as e:
                        print(f"[NUMBER_QUEUE] Failed to load per-user config for user {user_id}: {e}")
                
                # Fallback to global IMAP config if no per-user key found
                if not user_api_key:
                    imap_cfg = load_imap_config()
                    user_api_key = (imap_cfg.get("api_key") or "").strip()
                    if user_api_key:
                        print(f"[NUMBER_QUEUE] Using API key from global IMAP config (length: {len(user_api_key)})")
                
                if user_api_key:
                    caller.API_KEY = user_api_key
                else:
                    print(f"[NUMBER_QUEUE] WARNING: No API key found, using default caller API key")
                
                caller.BASE_URL = api_settings.get("base_url", caller.BASE_URL)
                caller.SERVICE = api_settings.get("service", caller.SERVICE)
                caller.OPERATOR = api_settings.get("operator", caller.OPERATOR)
                caller.COUNTRY = api_settings.get("country", caller.COUNTRY)
                
                print(f"[NUMBER_QUEUE] Cancelling {req_id} (user_id: {user_id}, scheduled at {cancel_after}, now={now}, delay={now - cancel_after:.1f}s)")
                result = caller.cancel_number(req_id)
                print(f"[NUMBER_QUEUE] Cancel result for {req_id}: {result}")
                cancelled_count += 1
            except Exception as e:
                print(f"[NUMBER_QUEUE] Failed to cancel {req_id}: {e}")
                import traceback
                traceback.print_exc()
                # Keep it in the queue to retry later
                remaining.append(line)
        else:
            # Not yet time to cancel
            remaining.append(line)
    
    if cancelled_count > 0:
        print(f"[NUMBER_QUEUE] Processed queue: cancelled {cancelled_count} number(s), {len(remaining)} remaining")

    # Only rewrite if we actually cancelled something or if there are remaining items
    if len(remaining) != len(lines):
        try:
            with open(NUMBER_QUEUE_FILE, "w", encoding="utf-8") as f:
                for line in remaining:
                    f.write(line + "\n")
            if cancelled_count > 0:
                print(f"[NUMBER_QUEUE] Updated queue file: {len(remaining)} items remaining")
        except Exception as e:
            print(f"[NUMBER_QUEUE] Failed to rewrite queue file: {e}")
            import traceback
            traceback.print_exc()


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
        print("[NUMBER_QUEUE] Worker thread started - will process queue every 15 seconds")
        while True:
            try:
                process_number_cancel_queue_once()
            except Exception as e:
                print(f"[NUMBER_QUEUE] Worker error: {e}")
                import traceback
                traceback.print_exc()
            # Optimize for 4 vCPU: Increase interval to reduce CPU usage
            time.sleep(15)  # Increased from 10 to 15 seconds

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    print("[NUMBER_QUEUE] Background worker thread started successfully")

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
    """Create user in database only (no file fallback)."""
    if not supabase_client.is_enabled():
        raise RuntimeError("Database not configured - cannot create user")
    
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
        print(f"[ERROR] Failed to create user in database: {e}")
        raise

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

        print(f"[DEBUG] [compute_balance_and_capacity] Calling get_balance()...")
        balance = None
        try:
            balance_text = caller.get_balance()
            print(f"[DEBUG] [compute_balance_and_capacity] get_balance() returned: {balance_text[:100] if balance_text else 'None'}")
            balance = caller.parse_balance(balance_text)
            if balance is None:
                print(f"[WARN] [compute_balance_and_capacity] Failed to parse balance from: {balance_text}")
        except Exception as e:
            print(f"[ERROR] [compute_balance_and_capacity] Exception in get_balance(): {e}")
            import traceback
            traceback.print_exc()
            # Don't return error yet, try to get price so we can at least show that
            balance = None
        
        print(f"[DEBUG] [compute_balance_and_capacity] Calling get_price_for_service()...")
        try:
            price_text = caller.get_price_for_service()
            print(f"[DEBUG] [compute_balance_and_capacity] get_price_for_service() returned: {price_text}")
        except Exception as e:
            print(f"[ERROR] [compute_balance_and_capacity] Exception in get_price_for_service(): {e}")
            import traceback
            traceback.print_exc()
            # Use default price if API call fails
            price_text = None
        if not price_text:
            price = float(api_settings.get('default_price', 6.99))
        else:
            try:
                price = float(price_text)
            except ValueError:
                price = float(api_settings.get('default_price', 6.99))

        # Capacity is based on the real provider price.
        # If balance is None (API failure), treat as 0 for capacity calc
        safe_balance = balance if balance is not None else 0.0
        capacity = int(safe_balance / price) if price > 0 else 0

        # Best-effort: store last known balance/capacity/price in Supabase users table.
        if supabase_client.is_enabled():
            try:
                supabase_client.update_user_balance(user_id, safe_balance, capacity, price)
            except Exception as e:
                print(f"[WARN] Supabase update_user_balance failed: {e}")

        if include_price:
            # Return discovered price even if balance is None (so UI shows price instead of N/A)
            return balance, capacity, price, None
        return balance, capacity, None
    except Exception as e:
        # If we have a critical error but can still determine the default price, return that
        try:
             api_settings = load_api_settings()
             default_price = float(api_settings.get('default_price', 6.99))
             if include_price:
                 return None, 0, default_price, str(e)
        except:
            pass
        return None, None, None if include_price else None, str(e)

# API Routes
@app.route('/api/auth/check', methods=['GET'])
def check_auth():
    if 'user_id' not in session:
        response = jsonify({"authenticated": False})
    else:
        user = get_user_by_username(session.get('username'))
        response = jsonify({
            "authenticated": True,
            "user": {
                "id": user.get('id'),
                "username": user.get('username'),
                "role": user.get('role')
            }
        })
    
    # Prevent caching of auth status
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route('/api/auth/login', methods=['POST'])
def login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    if not username or not password:
        return jsonify({"success": False, "error": "Please enter both username and password"}), 400
    user = get_user_by_username(username)
    if user and check_password_hash(user.get("password_hash"), password):
        session.permanent = True  # Make session persistent
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
    response = jsonify({"success": True})
    # Explicitly clear the session cookie
    response.set_cookie('session', '', expires=0, secure=False, httponly=True)
    # Nuke everything: cookies, storage, cache
    response.headers["Clear-Site-Data"] = '"cookies", "storage", "executionContexts"'
    return response

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
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401
        
        try:
            fee = get_margin_per_account(user_id)
            margin_balance = get_user_margin_balance(user_id)
        except Exception as e:
            print(f"[WARN] [api_margin_fees] Error getting margin data: {e}")
            fee = 2.5
            margin_balance = 0.0
        
        # Ensure values are numbers
        try:
            fee = float(fee) if fee is not None else 2.5
            margin_balance = float(margin_balance) if margin_balance is not None else 0.0
        except (ValueError, TypeError) as e:
            print(f"[WARN] [api_margin_fees] Invalid fee/balance values, using defaults: {e}")
            fee = 2.5
            margin_balance = 0.0
        
        response_data = {
            "per_account_fee": round(fee, 4),
            "margin_balance": round(margin_balance, 2),
        }
        return jsonify(response_data)
    except Exception as e:
        print(f"[ERROR] [api_margin_fees] Unexpected exception: {e}")
        import traceback
        traceback.print_exc()
        # Return default values on error instead of crashing
        try:
            return jsonify({
                "per_account_fee": 2.5,
                "margin_balance": 0.0,
                "error": "Failed to load margin fees"
            }), 200  # Return 200 instead of 500 to avoid breaking frontend
        except Exception as e2:
            print(f"[ERROR] [api_margin_fees] Failed to create error response: {e2}")
            # Last resort: return minimal response
            from flask import Response
            return Response('{"per_account_fee":2.5,"margin_balance":0.0}', mimetype='application/json'), 200

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


@app.route('/api/no-numbers-notify', methods=['POST'])
def api_no_numbers_notify():
    """
    Endpoint to emit NO_NUMBERS event to frontend via Socket.IO.
    Called by workers when they encounter NO_NUMBERS error.
    """
    try:
        data = request.get_json() or {}
        user_id = data.get('user_id')
        
        if not user_id:
            return jsonify({"error": "user_id required"}), 400
        
        # Emit Socket.IO event to show popup
        socketio.emit('no_numbers', {
            'message': 'No numbers available right now. Please try again after some time.'
        }, room=f'user_{user_id}')
        
        print(f"[NO_NUMBERS] Emitted no_numbers event to user_{user_id}")
        return jsonify({"status": "notified"}), 200
    except Exception as e:
        print(f"[ERROR] [no_numbers_notify] Failed: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


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


@app.route('/api/reports/failed-emails', methods=['GET'])
@login_required
def api_failed_emails():
    """
    Return or download failed emails (use_first_mails.txt) for the current user.
    """
    failed_emails_file = Path("use_first_mails.txt")
    
    # If download=1, respond with a text file
    if request.args.get('download') == '1':
        try:
            if not failed_emails_file.exists():
                # Create an empty file if it doesn't exist
                failed_emails_file.touch()
            return send_file(str(failed_emails_file), mimetype='text/plain', as_attachment=True)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    # View mode: return file contents
    if not failed_emails_file.exists():
        return jsonify({"items": [], "content": ""})
    
    try:
        with open(failed_emails_file, 'r', encoding='utf-8-sig', errors='replace') as f:
            content = f.read()
            lines = [line.strip() for line in content.splitlines() if line.strip()]
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
    return jsonify({"items": lines, "content": content})


@app.route('/api/reports/failed-emails', methods=['POST'])
@login_required
def api_update_failed_emails():
    """
    Update the use_first_mails.txt file with new content.
    """
    try:
        data = request.get_json() or {}
        content = data.get('content', '')
        
        failed_emails_file = Path("use_first_mails.txt")
        
        # Write the content to the file
        with open(failed_emails_file, 'w', encoding='utf-8', newline='\n') as f:
            f.write(content)
        
        print(f"[REPORTS] Updated use_first_mails.txt (length: {len(content)} chars)")
        return jsonify({"success": True, "message": "Failed emails file updated successfully"})
    except Exception as e:
        print(f"[ERROR] [api_update_failed_emails] Failed: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


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
    print(f"[DEBUG] [run] Starting /api/run endpoint")
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Login required"}), 401
    
    # Standardize user_id as int immediately to prevent key mismatches in tracking
    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid User ID in session"}), 400
        
    print(f"[DEBUG] [run] User ID: {user_id}")
    
    total_accounts = int(request.form.get("total_accounts", 10))
    max_parallel = int(request.form.get("max_parallel", 4))
    use_used_account_raw = (request.form.get("use_used_account", "1") or "").strip().lower()
    use_used_account = use_used_account_raw in ("1", "true", "on", "yes")
    
    print(f"[DEBUG] [run] Parameters: total_accounts={total_accounts}, max_parallel={max_parallel}, use_used_account={use_used_account}")

    if total_accounts < 1 or max_parallel < 1:
        return jsonify({"error": "Invalid input values"}), 400
    
    # Optimize for 4 vCPU, 16GB RAM: Limit max_parallel to prevent resource exhaustion
    # Allow up to 8 parallel workers (2 per CPU core) to leave resources for system
    MAX_ALLOWED_PARALLEL = min(max_parallel, 8)
    if max_parallel > MAX_ALLOWED_PARALLEL:
        max_parallel = MAX_ALLOWED_PARALLEL
        print(f"[WARN] [run] max_parallel capped at {MAX_ALLOWED_PARALLEL} for resource optimization")

    print(f"[DEBUG] [run] Computing balance and capacity...")
    try:
        balance, capacity, price, error_msg = compute_balance_and_capacity(user_id, include_price=True)
        print(f"[DEBUG] [run] Balance computation complete: balance={balance}, capacity={capacity}, price={price}, error={error_msg}")
    except Exception as e:
        print(f"[ERROR] [run] Exception in compute_balance_and_capacity: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Failed to compute balance: {str(e)}"}), 500
    
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
    print(f"[DEBUG] [run] Getting margin per account...")
    try:
        margin_per_account = get_margin_per_account(user_id)
        print(f"[DEBUG] [run] Margin per account: {margin_per_account}")
    except Exception as e:
        print(f"[ERROR] [run] Exception in get_margin_per_account: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Failed to get margin fee: {str(e)}"}), 500
    
    required_margin = total_accounts * margin_per_account
    
    # Get margin_balance from margin_fees table
    print(f"[DEBUG] [run] Getting user margin balance...")
    try:
        margin_balance = get_user_margin_balance(user_id)
        print(f"[DEBUG] [run] Margin balance: {margin_balance}, Required: {required_margin}")
    except Exception as e:
        print(f"[ERROR] [run] Exception in get_user_margin_balance: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Failed to get margin balance: {str(e)}"}), 500
    
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
    
    # Deduct margin_balance upfront for all accounts to be created
    print(f"[DEBUG] [run] ========== MARGIN BALANCE DEDUCTION ==========")
    print(f"[DEBUG] [run] User ID: {user_id}")
    print(f"[DEBUG] [run] Total accounts requested: {total_accounts}")
    print(f"[DEBUG] [run] Per account fee: ₹{margin_per_account:.2f}")
    
    # Get current balance before deduction
    try:
        current_balance = get_user_margin_balance(user_id)
        print(f"[DEBUG] [run] Current margin balance: ₹{current_balance:.2f}")
    except Exception as e:
        print(f"[WARN] [run] Could not get current balance: {e}")
        current_balance = 0.0
    
    total_margin_deduction = total_accounts * margin_per_account
    expected_new_balance = current_balance - total_margin_deduction
    print(f"[DEBUG] [run] Total deduction: ₹{total_margin_deduction:.2f}")
    print(f"[DEBUG] [run] Expected new balance: ₹{expected_new_balance:.2f}")
    
    print(f"[DEBUG] [run] Calling update_margin_balance...")
    try:
        if not update_margin_balance(user_id, -total_margin_deduction, f"Deducting upfront for {total_accounts} account(s)"):
            print(f"[ERROR] [run] update_margin_balance returned False")
            return jsonify({"error": "Failed to deduct margin balance. Please try again."}), 500
        print(f"[DEBUG] [run] Margin balance deduction successful")
    except Exception as e:
        print(f"[ERROR] [run] Exception in update_margin_balance: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Failed to deduct margin balance: {str(e)}"}), 500
    
    # Get updated margin_balance for confirmation
    print(f"[DEBUG] [run] Verifying margin balance after deduction...")
    try:
        updated_margin = get_user_margin_balance(user_id)
        print(f"[DEBUG] [run] Margin balance after deduction: ₹{updated_margin:.2f}")
        if abs(updated_margin - expected_new_balance) > 0.01:  # Allow small floating point differences
            print(f"[WARN] [run] Balance mismatch! Expected ₹{expected_new_balance:.2f}, got ₹{updated_margin:.2f}")
        else:
            print(f"[DEBUG] [run] Balance verification successful")
    except Exception as e:
        print(f"[WARN] [run] Failed to get updated margin balance: {e}")
        # Don't fail the request if we can't confirm, deduction already happened
    print(f"[DEBUG] [run] ============================================")
    
    # Initialize account status tracking for this batch
    print(f"[DEBUG] [run] Initializing account status tracking...")
    with account_status_lock:
        # Initialize or reset tracking for this user
        user_account_status[user_id] = {
            "success": 0, 
            "failed": 0, 
            "total_requested": total_accounts,
            "margin_per_account": margin_per_account, # Pin the fee for consistent refunds
            "reported_emails": set(),
            "active_emails": set()
        }
        user_account_status[user_id]["total_requested"] = total_accounts
        print(f"[DEBUG] [run] Initialized account tracking: total_requested={total_accounts}")
    
    print(f"[DEBUG] [run] Starting worker thread for user {user_id}...")
    user_id_int = user_id # Already converted to int at start of function
        
    thread = threading.Thread(
        target=run_parallel_sessions,
        args=(total_accounts, max_parallel, user_id_int, use_used_account, retry_failed, margin_per_account),
        daemon=True
    )
    thread.start()
    print(f"[DEBUG] [run] Worker thread started, returning success response")

    return jsonify({"success": True})


# Track account creation success/failure for margin_balance refunds
user_account_status = {}  # {user_id: {"success": count, "failed": count, "total_requested": count, "reported_emails": set}}
account_status_lock = threading.Lock()

@app.route('/api/account-status', methods=['POST'])
def api_account_status():
    """
    Endpoint for account_creator.py to report account creation success or failure.
    Used to track margin_balance refunds for failed accounts.
    Prevents double-counting by tracking which emails have already been reported.
    """
    try:
        data = request.get_json() or {}
        user_id = data.get('user_id')
        status = data.get('status')  # 'success' or 'failed'
        email = data.get('email')  # Optional: email to prevent double-counting
        
        if not user_id or status not in ('success', 'failed', 'started'):
            return jsonify({"error": "Invalid request. user_id and status (success/failed/started) required"}), 400
        
        user_id = int(user_id)
        
        with account_status_lock:
            # Get current run status OR initialize if worker reports before run thread (rare)
            if user_id not in user_account_status:
                margin_per_account = get_margin_per_account(user_id)
                user_account_status[user_id] = {
                    "success": 0, 
                    "failed": 0, 
                    "total_requested": 0,
                    "margin_per_account": margin_per_account,
                    "reported_emails": set(),
                    "active_emails": set()
                }
            else:
                # Use the fee that was pinned when the run started
                margin_per_account = user_account_status[user_id].get("margin_per_account")
                if margin_per_account is None:
                    margin_per_account = get_margin_per_account(user_id)
                    user_account_status[user_id]["margin_per_account"] = margin_per_account
            
            if status == 'started':
                if email:
                    user_account_status[user_id].setdefault("active_emails", set()).add(email)
                    print(f"[DEBUG] [api_account_status] User {user_id}: Email {email} started")
                return jsonify({"success": True})

            # For success/fail, remove from active_emails if present
            if email:
                user_account_status[user_id].setdefault("active_emails", set()).discard(email)
            
            # Check if this email was already reported (prevent double-counting)
            email_key = email or f"account_{user_account_status[user_id]['success'] + user_account_status[user_id]['failed']}"
            if email_key in user_account_status[user_id].get("reported_emails", set()):
                print(f"[WARN] [api_account_status] User {user_id}: Email {email_key} already reported, skipping duplicate report")
                return jsonify({"success": True, "message": "Already reported"})
            
            if status == 'success':
                user_account_status[user_id]["success"] += 1
                user_account_status[user_id]["reported_emails"].add(email_key)
                print(f"[DEBUG] [api_account_status] User {user_id}: Account SUCCESS (Total success: {user_account_status[user_id]['success']}, Total attempted: {user_account_status[user_id]['success'] + user_account_status[user_id]['failed']})")
            else:
                # status == 'failed' - ALWAYS refund margin_balance
                # This includes NO_NUMBERS errors and all other failure cases
                user_account_status[user_id]["failed"] += 1
                user_account_status[user_id]["reported_emails"].add(email_key)
                
                print(f"[DEBUG] [api_account_status] Processing refund for failed account (email: {email or 'N/A'}, margin_per_account: ₹{margin_per_account:.2f})")
                
                # Get current balance before refund for verification
                try:
                    balance_before = get_user_margin_balance(user_id)
                    print(f"[DEBUG] [api_account_status] Balance before refund: ₹{balance_before:.2f}")
                except Exception as e:
                    balance_before = None
                    print(f"[WARN] [api_account_status] Could not get balance before refund: {e}")
                
                # Refund margin_balance for failed account (trigger automatic refund)
                # This refunds the per_account_fee that was deducted upfront
                refund_reason = f"Refunding for failed account (email: {email or 'N/A'})"
                if not email or email == 'N/A':
                    refund_reason = f"Refunding for failed account (NO_NUMBERS or no email generated)"
                
                if update_margin_balance(user_id, margin_per_account, refund_reason):
                    try:
                        balance_after = get_user_margin_balance(user_id)
                        if balance_before is not None:
                            expected_balance = balance_before + margin_per_account
                            if abs(balance_after - expected_balance) > 0.01:
                                print(f"[WARN] [api_account_status] Balance mismatch! Expected ₹{expected_balance:.2f}, got ₹{balance_after:.2f}")
                            else:
                                print(f"[DEBUG] [api_account_status] Balance verification: ₹{balance_before:.2f} + ₹{margin_per_account:.2f} = ₹{balance_after:.2f} ✓")
                    except Exception:
                        pass  # Verification failed, but refund succeeded
                    
                    print(f"[DEBUG] [api_account_status] User {user_id}: Account FAILED - Refunded ₹{margin_per_account:.2f} (Total failed: {user_account_status[user_id]['failed']}, Total attempted: {user_account_status[user_id]['success'] + user_account_status[user_id]['failed']})")
                else:
                    print(f"[ERROR] [api_account_status] User {user_id}: Failed to refund margin_balance for failed account")
        
        return jsonify({"success": True})
    except Exception as e:
        print(f"[ERROR] [api_account_status] Exception: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

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

    # Check if this UTR was already used before verifying again
    try:
        existing = supabase_client.get_used_utr(utr)
    except Exception as e:
        print(f"[WARN] Error checking used UTR {utr}: {e}")
        existing = None

    if existing is not None:
        used_amount = existing.get("amount")
        try:
            used_amount_val = float(used_amount) if used_amount is not None else None
        except (TypeError, ValueError):
            used_amount_val = None

        msg = "This UTR has already been applied"
        if used_amount_val is not None:
            msg += f" for ₹{used_amount_val:.2f}."
        else:
            msg += "."

        return jsonify(
            {
                "error": msg + " Please use a different UTR.",
                "used_amount": round(used_amount_val, 2) if used_amount_val is not None else None,
            }
        ), 400

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

    # Get current wallet balance BEFORE adding funds, to use as margin fallback start
    # if margin row is missing. This prevents double-counting the initial deposit.
    pre_update_wallet_balance = get_wallet_balance_for_user(user_id)

    # Credit exactly the paid amount, regardless of the requested_amount
    new_balance = add_funds_to_user(user_id, paid_amount)

    # Update margin_balance in margin_fees table by adding the paid amount to existing balance
    # Use atomic update helper
    if supabase_client.is_enabled():
        update_margin_balance(
            user_id, 
            paid_amount, 
            f"Payment verified via UTR {utr}",
            fallback_balance=pre_update_wallet_balance
        )

    # Record this UTR as used so it cannot be applied again
    try:
        supabase_client.insert_used_utr(utr, user_id, paid_amount)
    except Exception as e:
        # Do not fail the whole request if tracking insert fails; just log it.
        print(f"[WARN] Failed to insert used UTR {utr} for user {user_id}: {e}")

    return jsonify(
        {
            "success": True,
            "credited": round(paid_amount, 2),
            "requested_amount": round(requested_amount, 2),
            "wallet_balance": round(new_balance, 2),
        }
    )



@app.route('/api/stop', methods=['POST'])
def api_stop():
    """Stop all workers for current user. Can be called from session or from worker process."""
    # Try to get user_id from session first (normal user request)
    user_id = session.get('user_id')
    # If no session, try to get from request data (worker timeout request)
    if not user_id:
        try:
            data = request.get_json() or {}
            user_id = data.get('user_id')
            if not user_id:
                # Try to get from USER_ID environment variable if available
                user_id = os.environ.get('USER_ID')
        except:
            pass
    
    if not user_id:
        return jsonify({"error": "User ID required"}), 400
    
    # Convert to int if it's a string
    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid user ID"}), 400
    
    # Set stop flag
    with user_stop_flags_lock:
        user_stop_flags[user_id] = True
    
    # Note: Workers will report their own status when they exit (success or failed)
    # We don't need to count or refund here - the final check in run_parallel_sessions will handle
    # any accounts that didn't report (truly didn't start or were interrupted before reporting)
    with account_status_lock:
        status = user_account_status.get(user_id, {"success": 0, "failed": 0, "total_requested": 0})
        total_requested = status.get("total_requested", 0)
        success_count = status.get("success", 0)
        failed_count = status.get("failed", 0)
        completed_count = success_count + failed_count
        remaining_count = max(0, total_requested - completed_count)
        
        print(f"[DEBUG] [api_stop] Stop button pressed - current status:")
        print(f"  User ID: {user_id}")
        print(f"  Total requested: {total_requested}")
        print(f"  Success (reported): {success_count}")
        print(f"  Failed (reported): {failed_count}")
        print(f"  Completed (reported): {completed_count}")
        print(f"  Remaining (not yet reported): {remaining_count}")
        print(f"[DEBUG] [api_stop] Cleaning up active emails from reserved list...")
        
        # PROACTIVE CLEANUP: Unreserve AND RECYCLE active emails immediately before killing processes
        # This ensures that even if process termination is abrupt, the reservation is cleared
        # and the email is added back to the pool for reuse.
        active_emails_val = status.get("active_emails", set())
        # Handle both set and list types safely
        active_emails_list = list(active_emails_val) if active_emails_val else []
        
        if active_emails_list:
            print(f"[DEBUG] [api_stop] Found {len(active_emails_list)} active emails to unreserve and recycle: {active_emails_list}")
            for orphaned_email in active_emails_list:
                try:
                    # 1. Add back to recycle pool (use_first_mails.txt)
                    imap.add_failed_email(orphaned_email)
                    # 2. Remove from reserved list (reserved_emails.txt)
                    imap.unreserve_email(orphaned_email)
                    print(f"[DEBUG] [api_stop] Proactive recycle successful for: {orphaned_email}")
                except Exception as clean_err:
                    print(f"[ERROR] [api_stop] Failed to proactively recycle {orphaned_email}: {clean_err}")
        
        # Clear the active list now that we've recycled them
        status["active_emails"] = set()
        
        print(f"[DEBUG] [api_stop] Workers will report their own status. Final refund will be calculated when all workers complete.")
    
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
    wait_for_otp = data.get("wait_for_otp", settings.get("wait_for_otp", 5))
    wait_for_second_otp = data.get("wait_for_second_otp", settings.get("wait_for_second_otp", 5))

    try:
        default_price = float(default_price)
    except (TypeError, ValueError):
        return jsonify({"error": "default_price must be a number"}), 400

    try:
        wait_for_otp = float(wait_for_otp)
        if wait_for_otp <= 0:
            return jsonify({"error": "wait_for_otp must be greater than 0"}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "wait_for_otp must be a number"}), 400

    try:
        wait_for_second_otp = float(wait_for_second_otp)
        if wait_for_second_otp <= 0:
            return jsonify({"error": "wait_for_second_otp must be greater than 0"}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "wait_for_second_otp must be a number"}), 400

    new_settings = {
        "base_url": base_url,
        "service": service,
        "operator": operator,
        "country": country,
        "default_price": default_price,
        "wait_for_otp": wait_for_otp,
        "wait_for_second_otp": wait_for_second_otp,
    }

    # Save to database only (single source of truth)
    if not supabase_client.is_enabled():
        return jsonify({"error": "Database not configured"}), 500

    try:
        supabase_client.upsert_api_settings(new_settings)
        print(f"[DEBUG] [admin_api_settings] Successfully saved to database: {new_settings}")
        return jsonify({"success": True, "settings": new_settings})
    except Exception as e:
        error_msg = f"Failed to save API settings to database: {str(e)}"
        print(f"[ERROR] [admin_api_settings] {error_msg}")
        return jsonify({"error": error_msg}), 500


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
        # Force role to 'user' - admin role cannot be created through this endpoint
        role = 'user'
        expiry_days_str = request.json.get('expiry_days', '').strip()

        if not username or not password:
            return jsonify({"error": "Username and password required"}), 400

        if not expiry_days_str:
            return jsonify({"error": "Expiry days is required"}), 400

        try:
            expiry_days = int(expiry_days_str)
            if expiry_days <= 0:
                raise ValueError()
        except ValueError:
            return jsonify({"error": "Invalid expiry days"}), 400

        try:
            password_hash = generate_password_hash(password)
            create_user(username, password_hash, role, expiry_days)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

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

def run_account_creator(session_num, total_sessions, user_id, use_used_account, retry_failed=True):
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
        
        # #region agent log
        import json as json_module
        try:
            with open(r"c:\Users\zgarm\OneDrive\Desktop\Account creator\.cursor\debug.log", "a", encoding='utf-8') as log_file:
                log_file.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"app_backend.py:1330","message":"run_account_creator entry","data":{"user_id":user_id,"session_num":session_num},"timestamp":int(time.time()*1000)}) + "\n")
        except: pass
        # #endregion
        
        # Load per-user API key from IMAP config (Supabase first, then legacy file)
        imap_cfg = {}
        if supabase_client.is_enabled():
            try:
                imap_cfg = supabase_client.get_imap_config(user_id)
                # #region agent log
                try:
                    with open(r"c:\Users\zgarm\OneDrive\Desktop\Account creator\.cursor\debug.log", "a", encoding='utf-8') as log_file:
                        log_file.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"app_backend.py:1336","message":"Loaded IMAP config from Supabase","data":{"user_id":user_id,"has_api_key":bool(imap_cfg.get("api_key")),"api_key_length":len(imap_cfg.get("api_key",""))},"timestamp":int(time.time()*1000)}) + "\n")
                except: pass
                # #endregion
            except Exception as e:
                print(f"[WARN] Supabase get_imap_config failed, falling back to file: {e}")
                # #region agent log
                try:
                    with open(r"c:\Users\zgarm\OneDrive\Desktop\Account creator\.cursor\debug.log", "a", encoding='utf-8') as log_file:
                        log_file.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"app_backend.py:1340","message":"Supabase get_imap_config failed","data":{"error":str(e)},"timestamp":int(time.time()*1000)}) + "\n")
                except: pass
                # #endregion
        if not imap_cfg:
            imap_cfg = load_imap_config()
            # #region agent log
            try:
                with open(r"c:\Users\zgarm\OneDrive\Desktop\Account creator\.cursor\debug.log", "a", encoding='utf-8') as log_file:
                    log_file.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"app_backend.py:1344","message":"Loaded IMAP config from file","data":{"has_api_key":bool(imap_cfg.get("api_key")),"api_key_length":len(imap_cfg.get("api_key",""))},"timestamp":int(time.time()*1000)}) + "\n")
            except: pass
            # #endregion
        
        api_settings = load_api_settings()
        user_api_key = (imap_cfg.get("api_key") or "").strip()

        # #region agent log
        try:
            with open(r"c:\Users\zgarm\OneDrive\Desktop\Account creator\.cursor\debug.log", "a", encoding='utf-8') as log_file:
                log_file.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"app_backend.py:1350","message":"API settings loaded","data":{"base_url":api_settings.get("base_url"),"service":api_settings.get("service"),"operator":api_settings.get("operator"),"country":api_settings.get("country")},"timestamp":int(time.time()*1000)}) + "\n")
        except: pass
        # #endregion
        
        # Debug: Print what API settings were loaded
        print(f"[DEBUG] [run_account_creator] Loaded API settings: {api_settings}")
        print(f"[DEBUG] [run_account_creator] base_url: {api_settings.get('base_url')}")
        print(f"[DEBUG] [run_account_creator] service: {api_settings.get('service')}")
        print(f"[DEBUG] [run_account_creator] operator: {api_settings.get('operator')}")
        print(f"[DEBUG] [run_account_creator] country: {api_settings.get('country')}")
        print(f"[DEBUG] [run_account_creator] user_api_key: {'SET (' + str(len(user_api_key)) + ' chars)' if user_api_key else 'NOT SET'}")

        env = os.environ.copy()
        env['USER_ID'] = str(user_id)
        env['SESSION_ID'] = session_id
        env['WORKER_NUM'] = str(worker_num)
        env['PYTHONUNBUFFERED'] = '1'
        env['USE_USED_ACCOUNT'] = '1' if use_used_account else '0'
        env['RETRY_FAILED'] = '1' if retry_failed else '0'

        if user_api_key:
            env['API_KEY'] = user_api_key
        
        # Always use values from api_settings (JSON file or Supabase)
        # Don't fall back to caller defaults - use what's in the settings
        env['API_BASE_URL'] = str(api_settings.get("base_url", caller.BASE_URL))
        env['API_SERVICE'] = str(api_settings.get("service", caller.SERVICE))
        env['API_OPERATOR'] = str(api_settings.get("operator", caller.OPERATOR))
        env['API_COUNTRY'] = str(api_settings.get("country", caller.COUNTRY))
        env['WAIT_FOR_OTP'] = str(api_settings.get("wait_for_otp", 5))  # In minutes (for first OTP)
        env['WAIT_FOR_SECOND_OTP'] = str(api_settings.get("wait_for_second_otp", 5))  # In minutes (for second/phone OTP)
        # Pass backend URL so workers can signal backend to stop all workers on timeout or report status
        backend_port = os.environ.get("PORT", "6333")
        env['BACKEND_URL'] = f"http://localhost:{backend_port}"
        
        # #region agent log
        try:
            with open(r"c:\Users\zgarm\OneDrive\Desktop\Account creator\.cursor\debug.log", "a", encoding='utf-8') as log_file:
                log_file.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"app_backend.py:1370","message":"Environment variables set","data":{"API_KEY_set":bool(env.get("API_KEY")),"API_KEY_length":len(env.get("API_KEY","")),"API_BASE_URL":env.get("API_BASE_URL"),"API_SERVICE":env.get("API_SERVICE"),"API_OPERATOR":env.get("API_OPERATOR"),"API_COUNTRY":env.get("API_COUNTRY")},"timestamp":int(time.time()*1000)}) + "\n")
        except: pass
        # #endregion
        
        # Debug: Print what environment variables are being set
        print(f"[DEBUG] [run_account_creator] Setting environment variables:")
        print(f"  API_BASE_URL: {env.get('API_BASE_URL')}")
        print(f"  API_SERVICE: {env.get('API_SERVICE')}")
        print(f"  API_OPERATOR: {env.get('API_OPERATOR')}")
        print(f"  API_COUNTRY: {env.get('API_COUNTRY')}")
        print(f"  WAIT_FOR_OTP: {env.get('WAIT_FOR_OTP')} minutes (first OTP)")
        print(f"  WAIT_FOR_SECOND_OTP: {env.get('WAIT_FOR_SECOND_OTP')} minutes (second OTP)")
        print(f"  API_KEY: {'SET (' + str(len(env.get('API_KEY', ''))) + ' chars)' if env.get('API_KEY') else 'NOT SET'}")
        
        # Optimize for 4 vCPU, 16GB RAM: Limit subprocess resources
        # Use line buffering and limit memory/CPU usage
        process = subprocess.Popen(
            ["python", "-u", "account_creator.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # Line buffered
            env=env,
            # Limit process group to prevent resource exhaustion
            preexec_fn=None if os.name == 'nt' else lambda: os.setpgrp()  # Unix only
        )
        
        with user_processes_lock:
            if user_id not in user_processes:
                user_processes[user_id] = []
            user_processes[user_id].append(process)
        
        def read_output():
            """Stream worker stdout into in-memory + file-based logs.
            Optimized for 4 vCPU, 16GB RAM: Batch writes to reduce I/O overhead."""
            worker_log = LOG_DIR / f"worker{worker_num}.txt"
            log_buffer = []
            buffer_size = 5  # Buffer 5 lines before flushing to disk
            last_flush = time.time()
            flush_interval = 0.5  # Flush every 0.5 seconds even if buffer not full
            
            try:
                with open(worker_log, 'a', encoding='utf-8', buffering=8192) as wf, open(
                    latest_log, 'a', encoding='utf-8', buffering=8192
                ) as lf:
                    for line in iter(process.stdout.readline, ''):
                        if not line:
                            break
                        line = line.rstrip('\n\r')
                        if not line:
                            continue

                        # In-memory + websocket log (immediate for real-time updates)
                        add_log(user_id, line)

                        # Buffer file writes for better I/O performance
                        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        tagged = f"[{ts}] [W{worker_num}] {line}\n"
                        log_buffer.append(tagged)
                        
                        # Flush buffer when it reaches size or after interval
                        current_time = time.time()
                        if len(log_buffer) >= buffer_size or (current_time - last_flush) >= flush_interval:
                            try:
                                for tag in log_buffer:
                                    wf.write(tag)
                                    lf.write(tag)
                                wf.flush()
                                lf.flush()
                                log_buffer = []
                                last_flush = current_time
                            except Exception as e:
                                print(f"[WARN] Failed to write log buffer: {e}")
                    
                    # Flush remaining logs
                    if log_buffer:
                        try:
                            for tag in log_buffer:
                                wf.write(tag)
                                lf.write(tag)
                            wf.flush()
                            lf.flush()
                        except Exception as e:
                            print(f"[WARN] Failed to flush remaining logs: {e}")
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

def run_parallel_sessions(total_accounts, max_parallel, user_id, use_used_account, retry_failed=True, margin_per_account=None):
    """Run sessions in batches."""
    print(f"[DEBUG] [run_parallel_sessions] Starting run for user {user_id}. Cleaning up stale email reservations...")
    try:
        cleaned = imap.cleanup_stale_reservations(timeout_minutes=10)
        if cleaned > 0:
            print(f"[DEBUG] [run_parallel_sessions] Cleaned up {cleaned} stale email reservation(s)")
    except Exception as e:
        print(f"[WARN] [run_parallel_sessions] Failed to clean stale reservations: {e}")
        
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
                            run_account_creator, current_session, total_accounts, user_id, use_used_account, retry_failed
                        )
                        futures.append(future)
                        session_map[future] = current_session
                    else:
                        # Optimize for 4 vCPU: Stagger worker starts to reduce CPU spikes
                        # Reduce delay slightly but still stagger to prevent resource contention
                        time.sleep(1.5)  # Reduced from 2s to 1.5s for faster startup
                        future = executor.submit(
                            run_account_creator, current_session, total_accounts, user_id, use_used_account, retry_failed
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
                        run_account_creator(failed_session, total_accounts, user_id, use_used_account, retry_failed)
                        add_log(user_id, f"[INFO] Retry session {failed_session} completed successfully")
                    except Exception as e:
                        error_msg = f"[ERROR] Retry session {failed_session} failed again: {e}"
                        add_log(user_id, error_msg)
                # Clear failed sessions after retry attempt
                failed_sessions = []
        
        # Track account success/failure by parsing logs or using API calls
        # For now, we'll track via API endpoint calls from account_creator.py
        # If margin_per_account is provided, we'll refund for any failures at the end
        if margin_per_account:
            print(f"[DEBUG] [run_parallel_sessions] Margin tracking enabled: ₹{margin_per_account:.2f} per account")
        
        # Get final account status summary and emit to frontend
        # Wait a moment for any pending status reports from workers
        time.sleep(3)
        
        with account_status_lock:
            if user_id not in user_account_status:
                user_account_status[user_id] = {
                    "success": 0, "failed": 0, "total_requested": total_accounts,
                    "active_emails": set(), "reported_emails": set()
                }
            status = user_account_status[user_id]
            success_count = status.get("success", 0)
            failed_count = status.get("failed", 0)
            total_requested = status.get("total_requested", 0)
            total_attempted = success_count + failed_count
            
            # Calculate remaining accounts that were not reported (workers that didn't report status)
            remaining_count = max(0, total_requested - total_attempted)
            
            print(f"[DEBUG] [run_parallel_sessions] Final account status (before handling remaining):")
            print(f"  Total requested: {total_requested}")
            print(f"  Success (reported): {success_count}")
            print(f"  Failed (reported): {failed_count}")
            print(f"  Total attempted (reported): {total_attempted}")
            print(f"  Remaining (not reported): {remaining_count}")
            print(f"[DEBUG] [run_parallel_sessions] Margin balance calculation:")
            print(f"  Per account fee: ₹{margin_per_account:.2f}")
            print(f"  Upfront deduction: ₹{total_requested * margin_per_account:.2f} (for {total_requested} accounts)")
            print(f"  Refunded so far: ₹{failed_count * margin_per_account:.2f} (for {failed_count} failed accounts)")
            print(f"  Expected remaining refund: ₹{remaining_count * margin_per_account:.2f} (for {remaining_count} unaccounted accounts)")
            
            # If there are remaining accounts that didn't report (stopped before completion)
            # Refund for them and mark as failed for summary
            final_failed_count = failed_count
            if remaining_count > 0 and margin_per_account:
                total_refund = remaining_count * margin_per_account
                print(f"[DEBUG] [run_parallel_sessions] Found {remaining_count} accounts that didn't report status (stopped/interrupted)")
                print(f"[DEBUG] [run_parallel_sessions] Refunding ₹{total_refund:.2f} for these accounts")
                if update_margin_balance(user_id, total_refund, f"Refunding for {remaining_count} account(s) that didn't complete"):
                    # Add to failed count for accurate summary (these accounts didn't succeed)
                    final_failed_count = failed_count + remaining_count
                    user_account_status[user_id]["failed"] = final_failed_count
                    print(f"[DEBUG] [run_parallel_sessions] Updated failed count to {final_failed_count} (includes {remaining_count} stopped accounts)")
                    print(f"[DEBUG] [run_parallel_sessions] Total refunded: ₹{final_failed_count * margin_per_account:.2f} (for {final_failed_count} failed accounts)")
                else:
                    print(f"[ERROR] [run_parallel_sessions] Failed to refund for {remaining_count} unaccounted accounts")
            
            # --- CRITICAL CLEANUP: Unreserve and Recycle Active Emails that didn't finish ---
            active_emails = user_account_status[user_id].get("active_emails", set())
            if active_emails:
                print(f"[DEBUG] [run_parallel_sessions] Cleaning up {len(active_emails)} orphaned active emails: {active_emails}")
                for orphaned_email in list(active_emails):
                    try:
                        # 1. Add back to recycle pool so it's prioritized next time
                        imap.add_failed_email(orphaned_email)
                        # 2. Remove from reserved list so other workers can see it
                        imap.unreserve_email(orphaned_email)
                        print(f"[DEBUG] [run_parallel_sessions] Recycled orphaned email: {orphaned_email}")
                    except Exception as clean_err:
                        print(f"[ERROR] [run_parallel_sessions] Failed to clean up orphaned email {orphaned_email}: {clean_err}")
                # Clear the set
                user_account_status[user_id]["active_emails"] = set()
            
            # Calculate final total (should match total_requested)
            final_total = success_count + final_failed_count
            
            # Validate: total should not exceed total_requested
            if final_total > total_requested:
                print(f"[WARN] [run_parallel_sessions] Total ({final_total}) exceeds requested ({total_requested})! Adjusting...")
                # Cap failed count to ensure total doesn't exceed requested
                final_failed_count = max(0, total_requested - success_count)
                user_account_status[user_id]["failed"] = final_failed_count
                final_total = success_count + final_failed_count
                print(f"[DEBUG] [run_parallel_sessions] Adjusted: Success={success_count}, Failed={final_failed_count}, Total={final_total}")
            
            # Always emit account summary when workers complete
            print(f"[DEBUG] [run_parallel_sessions] Account Summary - Success: {success_count}, Failed: {final_failed_count}, Total: {final_total}")
            socketio.emit('account_summary', {
                'success': success_count,
                'failed': final_failed_count,
                'total': final_total,
                'message': f"Total Success: {success_count} | Total Failed: {final_failed_count}"
            }, room=f'user_{user_id_int}')
            
            print(f"[DEBUG] [run_parallel_sessions] Emitted account_summary event to user_{user_id_int}: success={success_count}, failed={final_failed_count}, total={final_total}")
            
            # Clear status for this user after emitting (optional, or keep for history)
            # user_account_status[user_id] = {"success": 0, "failed": 0}
        
        completion_msg = "[INFO] All workers completed!"
        add_log(user_id, completion_msg)
        latest_log = LOG_DIR / "latest_logs.txt"
        try:
            with open(latest_log, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {completion_msg}\n")
        except Exception:
            pass
        try:
            if completion_file.exists():
                completion_file.unlink()
        except Exception:
            pass

    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = f"[CRITICAL] Batch processing failed hard: {e}"
        print(f"[ERROR] {error_msg}")
        add_log(user_id, error_msg)

# Reports API endpoints
REPORTS_DIR = Path("reports")
REPORTS_DIR.mkdir(exist_ok=True)

@app.route('/api/reports/used-emails', methods=['GET'])
@login_required
def api_reports_used_emails():
    """Get list of used emails with total count."""
    user_id = session.get('user_id')
    download = request.args.get('download') == '1'
    
    # Check both global and per-user files
    global_file = REPORTS_DIR / "used_emails.txt"
    per_user_file = REPORTS_DIR / f"used_emails_user{user_id}.txt"
    
    emails = []
    
    # Read from per-user file first
    if per_user_file.exists():
        try:
            with open(per_user_file, 'r', encoding='utf-8-sig') as f:
                for line in f:
                    email = line.strip()
                    if email and email not in emails:
                        emails.append(email)
        except Exception as e:
            print(f"[WARN] Failed to read per-user emails file: {e}")
    
    # Read from global file
    if global_file.exists():
        try:
            with open(global_file, 'r', encoding='utf-8-sig') as f:
                for line in f:
                    email = line.strip()
                    if email and email not in emails:
                        emails.append(email)
        except Exception as e:
            print(f"[WARN] Failed to read global emails file: {e}")
    
    if download:
        # Return as downloadable file
        content = "\n".join(emails)
        from io import BytesIO
        buffer = BytesIO(content.encode('utf-8'))
        buffer.seek(0)
        return send_file(buffer, as_attachment=True, download_name='used_emails.txt', mimetype='text/plain')
    else:
        # Return JSON with count
        return jsonify({"items": emails, "count": len(emails)})

@app.route('/api/reports/failed-numbers', methods=['GET'])
@login_required
def api_reports_failed_numbers():
    """Get list of failed numbers with total count."""
    download = request.args.get('download') == '1'
    
    failed_file = REPORTS_DIR / "failed_numbers.txt"
    numbers = []
    
    if failed_file.exists():
        try:
            with open(failed_file, 'r', encoding='utf-8-sig') as f:
                for line in f:
                    number = line.strip()
                    if number:
                        numbers.append(number)
        except Exception as e:
            print(f"[WARN] Failed to read failed numbers file: {e}")
    
    if download:
        content = "\n".join(numbers)
        from io import BytesIO
        buffer = BytesIO(content.encode('utf-8'))
        buffer.seek(0)
        return send_file(buffer, as_attachment=True, download_name='failed_numbers.txt', mimetype='text/plain')
    else:
        return jsonify({"items": numbers, "count": len(numbers)})

@app.route('/api/reports/failed-emails', methods=['GET', 'POST'])
@login_required
def api_reports_failed_emails():
    """Get or update list of failed emails (use_first_mails.txt) with total count."""
    failed_file = REPORTS_DIR / "use_first_mails.txt"
    
    if request.method == 'POST':
        # Update failed emails file
        data = request.json or {}
        content = data.get('content', '')
        
        try:
            with open(failed_file, 'w', encoding='utf-8') as f:
                f.write(content)
            return jsonify({"success": True, "message": "Failed emails updated successfully"})
        except Exception as e:
            return jsonify({"error": f"Failed to update file: {str(e)}"}), 500
    
    else:
        # GET request
        download = request.args.get('download') == '1'
        emails = []
        content = ""
        
        if failed_file.exists():
            try:
                with open(failed_file, 'r', encoding='utf-8-sig') as f:
                    content = f.read()
                    for line in content.splitlines():
                        email = line.strip()
                        if email:
                            emails.append(email)
            except Exception as e:
                print(f"[WARN] Failed to read failed emails file: {e}")
        
        if download:
            from io import BytesIO
            buffer = BytesIO(content.encode('utf-8'))
            buffer.seek(0)
            return send_file(buffer, as_attachment=True, download_name='use_first_mails.txt', mimetype='text/plain')
        else:
            return jsonify({"items": emails, "count": len(emails), "content": content})


# Serve React app
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_react(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')

if __name__ == "__main__":
    BACKEND_HOST = os.environ.get("BACKEND_HOST", "0.0.0.0")
    BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "6333"))
    DEBUG_MODE = os.environ.get("FLASK_DEBUG", "True").lower() == "true"
    
    print("=" * 60)
    print("🚀 Starting Flask Backend Server")
    print("=" * 60)
    print(f"   Host: {BACKEND_HOST}")
    print(f"   Port: {BACKEND_PORT}")
    print(f"   Debug: {DEBUG_MODE}")
    print(f"   Frontend URL: {FRONTEND_URL}")
    print(f"   CORS Origins: {', '.join(CORS_ORIGINS)}")
    print("=" * 60)
    print(f"   Server URL: http://{BACKEND_HOST}:{BACKEND_PORT}")
    print("=" * 60)
    print()
    
    socketio.run(app, debug=DEBUG_MODE, host=BACKEND_HOST, port=BACKEND_PORT, allow_unsafe_werkzeug=True)
