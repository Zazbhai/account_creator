import os
import datetime
from typing import Any, Dict, List, Optional

import requests

# Basic Supabase REST client for server-side use in app_backend.
#
# IMPORTANT:
# - This uses the Supabase REST endpoint (/rest/v1) with the anon key.
# - In production you would normally use a service role key and proper RLS.

SUPABASE_URL = os.environ.get(
    "SUPABASE_URL",
    "https://ijtewopznpstxfvxobgk.supabase.co",
)
SUPABASE_ANON_KEY = os.environ.get(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlqdGV3b3B6bnBzdHhmdnhvYmdrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjYwNTAxNTAsImV4cCI6MjA4MTYyNjE1MH0.0W4rRT4QlJYNWiju1W6Br-fZotgjHJRwCcEkfN7LSkQ",
)
# Service role key for admin operations (bypasses RLS)
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

_BASE_REST_URL = (
    SUPABASE_URL.rstrip("/") + "/rest/v1" if SUPABASE_URL and SUPABASE_ANON_KEY else None
)

_COMMON_HEADERS = (
    {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if _BASE_REST_URL
    else {}
)

# Admin headers using service role key (bypasses RLS)
_ADMIN_HEADERS = (
    {
        "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if _BASE_REST_URL and (SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY)
    else {}
)


def is_enabled() -> bool:
    """Return True if Supabase integration is configured."""
    return bool(_BASE_REST_URL and SUPABASE_ANON_KEY)


def _request(method: str, path: str, use_admin_key: bool = False, **kwargs) -> requests.Response:
    """
    Make a request to Supabase REST API.
    
    Args:
        method: HTTP method (GET, POST, PATCH, etc.)
        path: API path (e.g., "/users", "/api_settings")
        use_admin_key: If True, use service role key (bypasses RLS). Default False.
        **kwargs: Additional arguments passed to requests.request()
    
    Returns:
        requests.Response object
    """
    if not is_enabled():
        raise RuntimeError("Supabase is not configured")
    url = _BASE_REST_URL + path
    headers = kwargs.pop("headers", {})
    # Use admin headers (service role key) for admin operations to bypass RLS
    base_headers = _ADMIN_HEADERS if use_admin_key else _COMMON_HEADERS
    merged_headers = {**base_headers, **headers}
    resp = requests.request(method, url, headers=merged_headers, timeout=10, **kwargs)
    # Let caller handle non-2xx where necessary
    return resp


# ===== Users =====


def get_all_users() -> List[Dict[str, Any]]:
    """Fetch all users from Supabase users table."""
    if not is_enabled():
        return []
    resp = _request("GET", "/users", params={"select": "*"})
    resp.raise_for_status()
    return resp.json() or []


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """Fetch a single user by username."""
    if not is_enabled():
        return None
    params = {"select": "*", "username": f"eq.{username}"}
    resp = _request("GET", "/users", params=params)
    resp.raise_for_status()
    rows = resp.json() or []
    return rows[0] if rows else None


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
    payload = {
        "username": username,
        "password_hash": password_hash,
        "role": role,
        "expiry_date": expiry_date,
        "created_at": now_iso,
    }
    resp = _request(
        "POST",
        "/users",
        json=payload,
        headers={"Prefer": "return=representation"},
        use_admin_key=True,  # Admin operation - create user
    )
    resp.raise_for_status()
    rows = resp.json() or []
    return rows[0].get("id") if rows else None


def delete_user(user_id: int) -> None:
    """Delete a user by id."""
    if not is_enabled():
        return
    params = {"id": f"eq.{user_id}"}
    resp = _request("DELETE", "/users", params=params, use_admin_key=True)  # Admin operation
    # 204 is expected; ignore errors for now
    if resp.status_code >= 400:
        # Best-effort; don't crash app
        print(f"[SUPABASE] Failed to delete user {user_id}: {resp.status_code} {resp.text}")


# ===== API Settings (admin) =====


def get_api_settings() -> Optional[Dict[str, Any]]:
    """Fetch the single row from api_settings table, if any."""
    if not is_enabled():
        return None
    resp = _request("GET", "/api_settings", params={"select": "*"})
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    rows = resp.json() or []
    return rows[0] if rows else None


def upsert_api_settings(settings: Dict[str, Any]) -> None:
    """
    Upsert admin API settings into api_settings table.
    Expects columns matching keys of settings (base_url, service, operator, country, default_price).
    Uses service role key (if available) to bypass RLS for admin operations.
    Filters out unknown columns to avoid schema errors.
    """
    if not is_enabled():
        print("[SUPABASE] upsert_api_settings: Supabase not enabled, skipping")
        return
    
    # Known columns in api_settings table (filter out unknown columns like wait_for_otp if not in DB)
    # This allows the code to work even if the database schema hasn't been updated yet
    known_columns = ["base_url", "service", "operator", "country", "default_price", "wait_for_otp", "wait_for_second_otp"]
    
    # Filter settings to only include known columns (or all if we want to be permissive)
    # For now, we'll try to send all, but catch schema errors gracefully
    filtered_settings = {k: v for k, v in settings.items() if k in known_columns}
    
    # If filtered_settings is empty or different, log a warning
    if len(filtered_settings) < len(settings):
        skipped = set(settings.keys()) - set(filtered_settings.keys())
        if skipped:
            print(f"[WARN] [upsert_api_settings] Skipping unknown columns: {skipped}")
    
    print(f"[DEBUG] [upsert_api_settings] Attempting to save settings: {filtered_settings}")
    print(f"[DEBUG] [upsert_api_settings] Using service role key: {bool(SUPABASE_SERVICE_ROLE_KEY)}")
    
    try:
        existing = get_api_settings()
        print(f"[DEBUG] [upsert_api_settings] Existing settings: {existing}")
        
        if existing and "id" in existing:
            # Update existing row by id
            row_id = existing["id"]
            params = {"id": f"eq.{row_id}"}
            print(f"[DEBUG] [upsert_api_settings] Updating existing row with id: {row_id}")
            # Use admin key for write operations
            resp = _request("PATCH", "/api_settings", params=params, json=filtered_settings, use_admin_key=True)
        else:
            # Insert new row
            print(f"[DEBUG] [upsert_api_settings] Inserting new row")
            # Use admin key for write operations
            resp = _request(
                "POST",
                "/api_settings",
                json=filtered_settings,
                headers={"Prefer": "return=representation"},
                use_admin_key=True,
            )
        
        # Check response status
        if resp.status_code >= 400:
            error_text = resp.text
            # Check if it's a schema error (column doesn't exist)
            if "PGRST204" in error_text or "Could not find" in error_text and "column" in error_text:
                # Try again without wait_for_otp or wait_for_second_otp if those are the issue
                columns_to_remove = []
                if "wait_for_otp" in filtered_settings and "wait_for_otp" in error_text:
                    columns_to_remove.append("wait_for_otp")
                if "wait_for_second_otp" in filtered_settings and "wait_for_second_otp" in error_text:
                    columns_to_remove.append("wait_for_second_otp")
                
                if columns_to_remove:
                    print(f"[WARN] [upsert_api_settings] Column(s) not found in database: {columns_to_remove}, retrying without them")
                    filtered_settings_retry = {k: v for k, v in filtered_settings.items() if k not in columns_to_remove}
                    if existing and "id" in existing:
                        resp = _request("PATCH", "/api_settings", params=params, json=filtered_settings_retry, use_admin_key=True)
                    else:
                        resp = _request("POST", "/api_settings", json=filtered_settings_retry, headers={"Prefer": "return=representation"}, use_admin_key=True)
                    
                    if resp.status_code >= 400:
                        error_msg = f"[SUPABASE] Failed to upsert api_settings: {resp.status_code} {resp.text}"
                        print(error_msg)
                        if resp.status_code == 401:
                            print("[SUPABASE] RLS Policy Error: If you see this, you need to either:")
                            print("  1. Set SUPABASE_SERVICE_ROLE_KEY environment variable (recommended)")
                            print("  2. Or update RLS policy in Supabase to allow anon key to insert/update api_settings")
                        raise Exception(error_msg)
                else:
                    error_msg = f"[SUPABASE] Failed to upsert api_settings: {resp.status_code} {resp.text}"
                    print(error_msg)
                    if resp.status_code == 401:
                        print("[SUPABASE] RLS Policy Error: If you see this, you need to either:")
                        print("  1. Set SUPABASE_SERVICE_ROLE_KEY environment variable (recommended)")
                        print("  2. Or update RLS policy in Supabase to allow anon key to insert/update api_settings")
                    raise Exception(error_msg)
            else:
                error_msg = f"[SUPABASE] Failed to upsert api_settings: {resp.status_code} {resp.text}"
                print(error_msg)
                if resp.status_code == 401:
                    print("[SUPABASE] RLS Policy Error: If you see this, you need to either:")
                    print("  1. Set SUPABASE_SERVICE_ROLE_KEY environment variable (recommended)")
                    print("  2. Or update RLS policy in Supabase to allow anon key to insert/update api_settings")
                raise Exception(error_msg)
        
        print(f"[DEBUG] [upsert_api_settings] Successfully saved to Supabase (status: {resp.status_code})")
        if resp.status_code in (200, 201, 204):
            result = resp.json() if resp.content else None
            print(f"[DEBUG] [upsert_api_settings] Response: {result}")
    except Exception as e:
        error_msg = f"[SUPABASE] Error in upsert_api_settings: {e}"
        print(error_msg)
        raise Exception(error_msg) from e


# ===== IMAP config per user =====


def get_imap_config(user_id: int) -> Dict[str, Any]:
    """Fetch IMAP/API config for a given user_id from imap_config table."""
    if not is_enabled():
        return {}
    params = {"select": "*", "user_id": f"eq.{user_id}"}
    resp = _request("GET", "/imap_config", params=params)
    if resp.status_code == 404:
        return {}
    resp.raise_for_status()
    rows = resp.json() or []
    return rows[0] if rows else {}


def upsert_imap_config(user_id: int, config: Dict[str, Any]) -> None:
    """
    Upsert IMAP/API key config for a user into imap_config table.
    Expected columns: user_id, host, port, email, password, mailbox, api_key.
    """
    if not is_enabled():
        return
    existing = get_imap_config(user_id)
    payload = {
        "user_id": user_id,
        "host": config.get("host"),
        "port": config.get("port"),
        "email": config.get("email"),
        "password": config.get("password"),
        "mailbox": config.get("mailbox"),
        "api_key": config.get("api_key"),
    }
    if existing and "id" in existing:
        params = {"id": f"eq.{existing['id']}"}
        resp = _request("PATCH", "/imap_config", params=params, json=payload, use_admin_key=True)  # Admin operation
    else:
        resp = _request(
            "POST",
            "/imap_config",
            json=payload,
            headers={"Prefer": "return=representation"},
            use_admin_key=True,  # Admin operation
        )
    if resp.status_code >= 400:
        print(f"[SUPABASE] Failed to upsert imap_config: {resp.status_code} {resp.text}")


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
    If the columns are missing, errors are logged but not raised.
    """
    if not is_enabled():
        return
    payload = {
        "last_balance": balance,
        "last_capacity": capacity,
        "last_price": price,
    }
    params = {"id": f"eq.{user_id}"}
    resp = _request("PATCH", "/users", params=params, json=payload, use_admin_key=True)  # Admin operation
    if resp.status_code >= 400:
        print(f"[SUPABASE] Failed to update user balance: {resp.status_code} {resp.text}")


def update_user_expiry(user_id: int, expiry_date: str) -> None:
    """
    Best-effort update of a user's expiry_date column.
    """
    if not is_enabled():
        return
    payload = {"expiry_date": expiry_date}
    params = {"id": f"eq.{user_id}"}
    resp = _request("PATCH", "/users", params=params, json=payload, use_admin_key=True)  # Admin operation
    if resp.status_code >= 400:
        print(f"[SUPABASE] Failed to update user expiry: {resp.status_code} {resp.text}")


def update_user_wallet(user_id: int, wallet_balance: float) -> None:
    """
    Best-effort update of a user's wallet_balance column.
    Requires a numeric wallet_balance column on the users table.
    """
    if not is_enabled():
        return
    payload = {"wallet_balance": wallet_balance}
    params = {"id": f"eq.{user_id}"}
    resp = _request("PATCH", "/users", params=params, json=payload, use_admin_key=True)  # Admin operation
    if resp.status_code >= 400:
        print(f"[SUPABASE] Failed to update user wallet: {resp.status_code} {resp.text}")


# ===== Margin fees (per-user config) =====


def get_margin_fee_by_user(user_id: int) -> Optional[Dict[str, Any]]:
    """Fetch the margin_fees row for a given user_id."""
    if not is_enabled():
        return None
    params = {"select": "*", "user_id": f"eq.{user_id}"}
    resp = _request("GET", "/margin_fees", params=params)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    rows = resp.json() or []
    return rows[0] if rows else None


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
    payload: Dict[str, Any] = {
        "user_id": user_id,
        "per_account_fee": per_account_fee,
        "updated_at": now_iso,
    }
    if margin_balance is not None:
        payload["margin_balance"] = margin_balance
    if existing and "id" in existing:
        params = {"id": f"eq.{existing['id']}"}
        resp = _request("PATCH", "/margin_fees", params=params, json=payload, use_admin_key=True)  # Admin operation
    else:
        resp = _request(
            "POST",
            "/margin_fees",
            json=payload,
            headers={"Prefer": "return=representation"},
            use_admin_key=True,  # Admin operation
        )
    if resp.status_code >= 400:
        print(f"[SUPABASE] Failed to upsert margin_fees for user {user_id}: {resp.status_code} {resp.text}")


# Legacy function for backward compatibility (deprecated)
def get_margin_fee() -> Optional[Dict[str, Any]]:
    """Legacy: Fetch the single row from margin_fees table, if any. DEPRECATED: Use get_margin_fee_by_user instead."""
    if not is_enabled():
        return None
    resp = _request("GET", "/margin_fees", params={"select": "*"})
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    rows = resp.json() or []
    return rows[0] if rows else None



# Legacy function for backward compatibility (deprecated)
def upsert_margin_fee(per_account_fee: float, margin_balance: Optional[float] = None) -> None:
    """Legacy: Upsert global margin per-account fee. DEPRECATED: Use upsert_margin_fee_for_user instead."""
    if not is_enabled():
        return
    existing = get_margin_fee()
    payload: Dict[str, Any] = {"per_account_fee": per_account_fee}
    if margin_balance is not None:
        payload["margin_balance"] = margin_balance
    if existing and "id" in existing:
        params = {"id": f"eq.{existing['id']}"}
        resp = _request("PATCH", "/margin_fees", params=params, json=payload, use_admin_key=True)  # Admin operation
    else:
        resp = _request(
            "POST",
            "/margin_fees",
            json=payload,
            headers={"Prefer": "return=representation"},
            use_admin_key=True,  # Admin operation
        )
    if resp.status_code >= 400:
        print(f"[SUPABASE] Failed to upsert margin_fees: {resp.status_code} {resp.text}")


# ===== Used UTRs (payment tracking) =====


def get_used_utr(utr: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a used UTR row.
    When Supabase is disabled, falls back to used_utrs.txt.
    """
    if not is_enabled():
        return _get_utr_file(utr)

    params = {"select": "utr,user_id,amount,created_at", "utr": f"eq.{utr}"}
    resp = _request("GET", "/used_utrs", params=params)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    rows = resp.json() or []
    return rows[0] if rows else None


def insert_used_utr(utr: str, user_id: int, amount: float) -> None:
    """
    Insert a successful UTR into the used_utrs table.
    Table structure: utr (primary key), user_id, amount, created_at
    """
    if not is_enabled():
        _save_utr_file(utr, user_id, amount)
        return

    now_iso = datetime.datetime.utcnow().isoformat()
    payload = {
        "utr": utr,
        "user_id": user_id,
        "amount": amount,
        "created_at": now_iso,
    }
    resp = _request(
        "POST",
        "/used_utrs",
        json=payload,
        headers={"Prefer": "return=representation"},
    )
    if resp.status_code >= 400:
        print(f"[SUPABASE] Failed to insert used_utr {utr}: {resp.status_code} {resp.text}")


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
        print(f"[SUPABASE] Error reading used_utrs.txt: {e}")
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
      print(f"[SUPABASE] Error writing to used_utrs.txt: {e}")
