import os
import datetime
from typing import Any, Dict, List, Optional
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

# PostgreSQL client for Neon database
# Replaces supabase_client.py with direct PostgreSQL connection

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://neondb_owner:npg_2OJ0rvhmnCVE@ep-lingering-glade-ahxz3ciz-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require")

# Connection pool for better performance
_connection_pool: Optional[pool.SimpleConnectionPool] = None


def _init_pool():
    """Initialize the connection pool."""
    global _connection_pool
    if _connection_pool is None and DATABASE_URL:
        try:
            _connection_pool = pool.SimpleConnectionPool(
                1, 10,  # min and max connections
                DATABASE_URL
            )
        except Exception as e:
            print(f"[NEON] Failed to initialize connection pool: {e}")
            _connection_pool = None


def is_enabled() -> bool:
    """Return True if Neon database is configured."""
    return bool(DATABASE_URL)


def _get_connection():
    """Get a connection from the pool."""
    if not is_enabled():
        raise RuntimeError("Neon database is not configured")
    
    _init_pool()
    if _connection_pool is None:
        raise RuntimeError("Failed to initialize database connection pool")
    
    return _connection_pool.getconn()


def _release_connection(conn):
    """Release a connection back to the pool."""
    if _connection_pool and conn:
        _connection_pool.putconn(conn)


def _execute_query(query: str, params: tuple = None, fetch: str = "all") -> Any:
    """
    Execute a query and return results.
    
    Args:
        query: SQL query string
        params: Query parameters
        fetch: "all", "one", or "none"
    
    Returns:
        Query results as list of dicts, single dict, or None
    """
    if not is_enabled():
        return [] if fetch == "all" else None
    
    conn = None
    try:
        conn = _get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, params)
            
            if fetch == "all":
                result = cursor.fetchall()
                return [dict(row) for row in result] if result else []
            elif fetch == "one":
                result = cursor.fetchone()
                return dict(result) if result else None
            else:  # none
                conn.commit()
                return None
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"[NEON] Query error: {e}")
        print(f"[NEON] Query: {query}")
        print(f"[NEON] Params: {params}")
        raise
    finally:
        if conn:
            _release_connection(conn)


# ===== Users =====


def get_all_users() -> List[Dict[str, Any]]:
    """Fetch all users from users table."""
    if not is_enabled():
        return []
    query = "SELECT * FROM users ORDER BY id"
    return _execute_query(query, fetch="all")


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """Fetch a single user by username."""
    if not is_enabled():
        return None
    query = "SELECT * FROM users WHERE username = %s LIMIT 1"
    return _execute_query(query, (username,), fetch="one")


def create_user(
    username: str,
    password_hash: str,
    role: str = "user",
    expiry_days: Optional[int] = None,
) -> Optional[int]:
    """Create a new user row and return its id."""
    if not is_enabled():
        return None

    expiry_date = None
    if expiry_days:
        from datetime import date, timedelta
        expiry_date = (date.today() + timedelta(days=expiry_days)).isoformat()

    now_iso = datetime.datetime.utcnow().isoformat()
    query = """
        INSERT INTO users (username, password_hash, role, expiry_date, created_at)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    """
    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            cursor.execute(query, (username, password_hash, role, expiry_date, now_iso))
            user_id = cursor.fetchone()[0]
            conn.commit()
            return user_id
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"[NEON] Failed to create user: {e}")
        raise
    finally:
        if conn:
            _release_connection(conn)


def delete_user(user_id: int) -> None:
    """Delete a user by id."""
    if not is_enabled():
        return
    query = "DELETE FROM users WHERE id = %s"
    try:
        _execute_query(query, (user_id,), fetch="none")
    except Exception as e:
        print(f"[NEON] Failed to delete user {user_id}: {e}")


# ===== API Settings (admin) =====


def get_api_settings() -> Optional[Dict[str, Any]]:
    """Fetch the single row from api_settings table, if any."""
    if not is_enabled():
        return None
    query = "SELECT * FROM api_settings LIMIT 1"
    try:
        return _execute_query(query, fetch="one")
    except Exception as e:
        print(f"[NEON] Failed to get api_settings: {e}")
        return None


def upsert_api_settings(settings: Dict[str, Any]) -> None:
    """
    Upsert admin API settings into api_settings table.
    Expects columns matching keys of settings (base_url, service, operator, country, default_price).
    """
    if not is_enabled():
        print("[NEON] upsert_api_settings: Database not enabled, skipping")
        return
    
    # Known columns in api_settings table
    known_columns = ["base_url", "service", "server", "default_price", "wait_for_otp", "wait_for_second_otp"]
    
    # Filter settings to only include known columns
    filtered_settings = {k: v for k, v in settings.items() if k in known_columns}
    
    if len(filtered_settings) < len(settings):
        skipped = set(settings.keys()) - set(filtered_settings.keys())
        if skipped:
            print(f"[WARN] [upsert_api_settings] Skipping unknown columns: {skipped}")
    
    print(f"[DEBUG] [upsert_api_settings] Attempting to save settings: {filtered_settings}")
    
    try:
        existing = get_api_settings()
        print(f"[DEBUG] [upsert_api_settings] Existing settings: {existing}")
        
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor() as cursor:
                if existing and "id" in existing:
                    # Update existing row
                    row_id = existing["id"]
                    print(f"[DEBUG] [upsert_api_settings] Updating existing row with id: {row_id}")
                    
                    set_clause = ", ".join([f"{k} = %s" for k in filtered_settings.keys()])
                    query = f"UPDATE api_settings SET {set_clause} WHERE id = %s"
                    params = tuple(filtered_settings.values()) + (row_id,)
                    cursor.execute(query, params)
                else:
                    # Insert new row
                    print(f"[DEBUG] [upsert_api_settings] Inserting new row")
                    
                    columns = ", ".join(filtered_settings.keys())
                    placeholders = ", ".join(["%s"] * len(filtered_settings))
                    query = f"INSERT INTO api_settings ({columns}) VALUES ({placeholders})"
                    cursor.execute(query, tuple(filtered_settings.values()))
                
                conn.commit()
                print(f"[DEBUG] [upsert_api_settings] Successfully saved to database")
        except Exception as e:
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                _release_connection(conn)
    except Exception as e:
        error_msg = f"[NEON] Error in upsert_api_settings: {e}"
        print(error_msg)
        raise Exception(error_msg) from e


# ===== IMAP config per user =====


def get_imap_config(user_id: int) -> Dict[str, Any]:
    """Fetch IMAP/API config for a given user_id from imap_config table."""
    if not is_enabled():
        return {}
    query = "SELECT * FROM imap_config WHERE user_id = %s LIMIT 1"
    try:
        result = _execute_query(query, (user_id,), fetch="one")
        return result if result else {}
    except Exception as e:
        print(f"[NEON] Failed to get imap_config: {e}")
        return {}


def upsert_imap_config(user_id: int, config: Dict[str, Any]) -> None:
    """
    Upsert IMAP/API key config for a user into imap_config table.
    Expected columns: user_id, host, port, email, password, mailbox, api_key.
    """
    if not is_enabled():
        return
    
    existing = get_imap_config(user_id)
    
    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            if existing and "id" in existing:
                # Update existing row
                query = """
                    UPDATE imap_config 
                    SET host = %s, port = %s, email = %s, password = %s, mailbox = %s, api_key = %s
                    WHERE id = %s
                """
                params = (
                    config.get("host"),
                    config.get("port"),
                    config.get("email"),
                    config.get("password"),
                    config.get("mailbox"),
                    config.get("api_key"),
                    existing["id"]
                )
                cursor.execute(query, params)
            else:
                # Insert new row
                query = """
                    INSERT INTO imap_config (user_id, host, port, email, password, mailbox, api_key)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """
                params = (
                    user_id,
                    config.get("host"),
                    config.get("port"),
                    config.get("email"),
                    config.get("password"),
                    config.get("mailbox"),
                    config.get("api_key")
                )
                cursor.execute(query, params)
            
            conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"[NEON] Failed to upsert imap_config: {e}")
    finally:
        if conn:
            _release_connection(conn)


# ===== Optional: store last known balance/capacity per user =====


def update_user_balance(
    user_id: int,
    balance: float,
    capacity: int,
    price: float,
) -> None:
    """
    Best-effort update of user's last known balance/capacity/price.
    Expects columns last_balance, last_capacity, last_price to exist on users table.
    """
    if not is_enabled():
        return
    
    query = """
        UPDATE users 
        SET last_balance = %s, last_capacity = %s, last_price = %s
        WHERE id = %s
    """
    try:
        _execute_query(query, (balance, capacity, price, user_id), fetch="none")
    except Exception as e:
        print(f"[NEON] Failed to update user balance: {e}")


def update_user_expiry(user_id: int, expiry_date: str) -> None:
    """
    Best-effort update of a user's expiry_date column.
    """
    if not is_enabled():
        return
    
    query = "UPDATE users SET expiry_date = %s WHERE id = %s"
    try:
        _execute_query(query, (expiry_date, user_id), fetch="none")
    except Exception as e:
        print(f"[NEON] Failed to update user expiry: {e}")


def update_user_wallet(user_id: int, wallet_balance: float) -> None:
    """
    Best-effort update of a user's wallet_balance column.
    Requires a numeric wallet_balance column on the users table.
    """
    if not is_enabled():
        return
    
    query = "UPDATE users SET wallet_balance = %s WHERE id = %s"
    try:
        _execute_query(query, (wallet_balance, user_id), fetch="none")
    except Exception as e:
        print(f"[NEON] Failed to update user wallet: {e}")


# ===== Margin fees (per-user config) =====


def atomic_margin_update(
    user_id: int, 
    amount_delta: float, 
    fallback_start_balance: float = 0.0,
    default_per_account_fee: float = 2.5
) -> Optional[float]:
    """
    Atomically update user's margin_balance.
    - Locks the row if it exists.
    - If row exists: margin_balance += amount_delta.
    - If row missing: inserts new row with margin_balance = fallback_start_balance + amount_delta.
    Returns the new balance.
    """
    if not is_enabled():
        return None
    
    conn = None
    try:
        conn = _get_connection()
        # Start transaction
        with conn.cursor() as cursor:
            # Try to select for update to lock the row
            cursor.execute("SELECT id, margin_balance FROM margin_fees WHERE user_id = %s FOR UPDATE", (user_id,))
            row = cursor.fetchone()
            
            now_iso = datetime.datetime.utcnow().isoformat()
            new_balance = 0.0
            
            if row:
                row_id, current_bal = row
                current_bal = float(current_bal) if current_bal is not None else 0.0
                new_balance = current_bal + amount_delta
                
                cursor.execute(
                    "UPDATE margin_fees SET margin_balance = %s, updated_at = %s WHERE id = %s",
                    (new_balance, now_iso, row_id)
                )
            else:
                # Row doesn't exist, create it
                new_balance = fallback_start_balance + amount_delta
                cursor.execute(
                    """
                    INSERT INTO margin_fees (user_id, per_account_fee, margin_balance, updated_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (user_id, default_per_account_fee, new_balance, now_iso)
                )
            
            conn.commit()
            return new_balance
            
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"[NEON] atomic_margin_update failed: {e}")
        raise
    finally:
        if conn:
            _release_connection(conn)


def get_margin_fee_by_user(user_id: int) -> Optional[Dict[str, Any]]:
    """Fetch the margin_fees row for a given user_id."""
    if not is_enabled():
        return None
    
    query = "SELECT * FROM margin_fees WHERE user_id = %s LIMIT 1"
    try:
        return _execute_query(query, (user_id,), fetch="one")
    except Exception as e:
        print(f"[NEON] Failed to get margin_fee: {e}")
        return None


def upsert_margin_fee_for_user(
    user_id: int,
    per_account_fee: float,
    margin_balance: Optional[float] = None,
) -> None:
    """
    Upsert margin fee config for a specific user into margin_fees table.
    Table structure: user_id, id, per_account_fee, margin_balance, updated_at
    """
    if not is_enabled():
        return
    
    existing = get_margin_fee_by_user(user_id)
    now_iso = datetime.datetime.utcnow().isoformat()
    
    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            if existing and "id" in existing:
                # Update existing row
                if margin_balance is not None:
                    query = """
                        UPDATE margin_fees 
                        SET per_account_fee = %s, margin_balance = %s, updated_at = %s
                        WHERE id = %s
                    """
                    params = (per_account_fee, margin_balance, now_iso, existing["id"])
                else:
                    query = """
                        UPDATE margin_fees 
                        SET per_account_fee = %s, updated_at = %s
                        WHERE id = %s
                    """
                    params = (per_account_fee, now_iso, existing["id"])
                cursor.execute(query, params)
            else:
                # Insert new row
                if margin_balance is not None:
                    query = """
                        INSERT INTO margin_fees (user_id, per_account_fee, margin_balance, updated_at)
                        VALUES (%s, %s, %s, %s)
                    """
                    params = (user_id, per_account_fee, margin_balance, now_iso)
                else:
                    query = """
                        INSERT INTO margin_fees (user_id, per_account_fee, updated_at)
                        VALUES (%s, %s, %s)
                    """
                    params = (user_id, per_account_fee, now_iso)
                cursor.execute(query, params)
            
            conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"[NEON] Failed to upsert margin_fees for user {user_id}: {e}")
    finally:
        if conn:
            _release_connection(conn)


# Legacy function for backward compatibility (deprecated)
def get_margin_fee() -> Optional[Dict[str, Any]]:
    """Legacy: Fetch the single row from margin_fees table, if any. DEPRECATED: Use get_margin_fee_by_user instead."""
    if not is_enabled():
        return None
    
    query = "SELECT * FROM margin_fees LIMIT 1"
    try:
        return _execute_query(query, fetch="one")
    except Exception as e:
        print(f"[NEON] Failed to get margin_fee: {e}")
        return None


# Legacy function for backward compatibility (deprecated)
def upsert_margin_fee(per_account_fee: float, margin_balance: Optional[float] = None) -> None:
    """Legacy: Upsert global margin per-account fee. DEPRECATED: Use upsert_margin_fee_for_user instead."""
    if not is_enabled():
        return
    
    existing = get_margin_fee()
    
    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            if existing and "id" in existing:
                # Update existing row
                if margin_balance is not None:
                    query = "UPDATE margin_fees SET per_account_fee = %s, margin_balance = %s WHERE id = %s"
                    params = (per_account_fee, margin_balance, existing["id"])
                else:
                    query = "UPDATE margin_fees SET per_account_fee = %s WHERE id = %s"
                    params = (per_account_fee, existing["id"])
                cursor.execute(query, params)
            else:
                # Insert new row
                if margin_balance is not None:
                    query = "INSERT INTO margin_fees (per_account_fee, margin_balance) VALUES (%s, %s)"
                    params = (per_account_fee, margin_balance)
                else:
                    query = "INSERT INTO margin_fees (per_account_fee) VALUES (%s)"
                    params = (per_account_fee,)
                cursor.execute(query, params)
            
            conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"[NEON] Failed to upsert margin_fees: {e}")
    finally:
        if conn:
            _release_connection(conn)


# ===== Used UTRs (payment tracking) =====


def get_used_utr(utr: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a used UTR row.
    When database is disabled, falls back to used_utrs.txt.
    """
    if not is_enabled():
        return _get_utr_file(utr)

    query = "SELECT utr, user_id, amount, created_at FROM used_utrs WHERE utr = %s LIMIT 1"
    try:
        return _execute_query(query, (utr,), fetch="one")
    except Exception as e:
        print(f"[NEON] Failed to get used_utr: {e}")
        return None


def insert_used_utr(utr: str, user_id: int, amount: float) -> None:
    """
    Insert a successful UTR into the used_utrs table.
    Table structure: utr (primary key), user_id, amount, created_at
    """
    if not is_enabled():
        _save_utr_file(utr, user_id, amount)
        return

    now_iso = datetime.datetime.utcnow().isoformat()
    query = """
        INSERT INTO used_utrs (utr, user_id, amount, created_at)
        VALUES (%s, %s, %s, %s)
    """
    try:
        _execute_query(query, (utr, user_id, amount, now_iso), fetch="none")
    except Exception as e:
        print(f"[NEON] Failed to insert used_utr {utr}: {e}")


def _get_utr_file(utr: str) -> Optional[Dict[str, Any]]:
    """File-based fallback: return row for given UTR from used_utrs.txt."""
    import os

    utr_file = "used_utrs.txt"
    if not os.path.exists(utr_file):
        return None
    try:
        with open(utr_file, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("|")
                if not parts or parts[0] != utr:
                    continue
                # utr|user_id|amount|created_at
                row: Dict[str, Any] = {"utr": parts[0]}
                if len(parts) > 1:
                    try:
                        row["user_id"] = int(parts[1])
                    except Exception:
                        row["user_id"] = None
                if len(parts) > 2:
                    try:
                        row["amount"] = float(parts[2])
                    except Exception:
                        row["amount"] = None
                if len(parts) > 3:
                    row["created_at"] = parts[3]
                return row
    except Exception as e:
        print(f"[NEON] Error reading used_utrs.txt: {e}")
    return None


def _save_utr_file(utr: str, user_id: int, amount: float) -> None:
    """File-based fallback: Append UTR to used_utrs.txt."""
    import os

    utr_file = "used_utrs.txt"
    now_iso = datetime.datetime.utcnow().isoformat()
    try:
        with open(utr_file, "a", encoding="utf-8") as f:
            f.write(f"{utr}|{user_id}|{amount}|{now_iso}\n")
    except Exception as e:
        print(f"[NEON] Error writing to used_utrs.txt: {e}")
