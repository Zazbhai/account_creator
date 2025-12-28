import json
import re
import time
from typing import Any, Dict, Optional, Tuple
from urllib import error, parse, request

# API credentials and defaults
API_KEY = "2ce12168a4f72374207d61fc634ba23c79cf"
OPERATOR = "1"
COUNTRY = "22"
SERVICE = "pfk"

BASE_URL = "https://api.temporasms.com/stubs/handler_api.php"

def _http_get(params: Dict[str, Any]) -> str:
    """
    Perform a GET request with shared base URL and API key.
    Returns raw text from the API or raises ValueError on network/HTTP issues.
    """
    import datetime
    import json as json_module
    import time
    
    # #region agent log
    try:
        with open(r"c:\Users\zgarm\OneDrive\Desktop\Account creator\.cursor\debug.log", "a", encoding='utf-8') as log_file:
            log_file.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"E","location":"caller.py:15","message":"_http_get entry","data":{"BASE_URL":BASE_URL,"SERVICE":SERVICE,"OPERATOR":OPERATOR,"COUNTRY":COUNTRY,"API_KEY_set":bool(API_KEY),"API_KEY_length":len(API_KEY)},"timestamp":int(time.time()*1000)}) + "\n")
    except: pass
    # #endregion
    
    merged = {"api_key": API_KEY, **params}
    url = f"{BASE_URL}?{parse.urlencode(merged)}"
    
    # Create a safe version of params for logging (redact API key but show first 4 chars for verification)
    api_key_display = f"{API_KEY[:4]}...{API_KEY[-4:]}" if len(API_KEY) > 8 else "***REDACTED***"
    safe_params = {k: (api_key_display if k == 'api_key' else v) for k, v in merged.items()}
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    
    # Log the API call (using plain text to avoid Windows encoding issues)
    print("=" * 80)
    print(f"[CALLER API REQUEST] {timestamp}")
    print("-" * 80)
    print(f"URL: {BASE_URL}")
    print(f"Action: {params.get('action', 'unknown')}")
    print(f"[CONFIG] Service: {SERVICE} | Operator: {OPERATOR} | Country: {COUNTRY}")
    print(f"[CONFIG] API Key: {api_key_display} (length: {len(API_KEY)})")
    print(f"Params (for request): service={params.get('service', SERVICE)}, operator={params.get('operator', OPERATOR)}, country={params.get('country', COUNTRY)}")
    print(f"Full URL (redacted): {BASE_URL}?{parse.urlencode(safe_params)}")
    start_time = time.time()

    try:
        with request.urlopen(url, timeout=15) as resp:
            duration = (time.time() - start_time) * 1000  # Convert to milliseconds
            response_text = resp.read().decode("utf-8").strip()
            
            # Log successful response
            print(f"[OK] Status: {resp.status} {resp.reason}")
            print(f"Duration: {duration:.2f}ms")
            print(f"Response: {response_text[:200]}{'...' if len(response_text) > 200 else ''}")
            print(f"Response Length: {len(response_text)} bytes")
            print("=" * 80)
            print()
            
            # API returns plain text like: ACCESS_BALANCE:123.45
            return response_text
    except error.HTTPError as exc:
        duration = (time.time() - start_time) * 1000
        print(f"[ERROR] HTTP Error: {exc.code} {exc.reason}")
        print(f"Duration: {duration:.2f}ms")
        if hasattr(exc, 'read'):
            try:
                error_body = exc.read().decode("utf-8")[:200]
                print(f"Error Response: {error_body}")
            except:
                pass
        print("=" * 80)
        print()
        raise ValueError(f"API HTTP {exc.code}: {exc.reason}") from exc
    except error.URLError as exc:
        duration = (time.time() - start_time) * 1000
        print(f"[ERROR] Network Error: {exc.reason}")
        print(f"Duration: {duration:.2f}ms")
        print("=" * 80)
        print()
        raise ValueError(f"Network error: {exc.reason}") from exc
    except Exception as exc:
        duration = (time.time() - start_time) * 1000
        print(f"[ERROR] Unexpected Error: {type(exc).__name__}: {exc}")
        print(f"Duration: {duration:.2f}ms")
        print("=" * 80)
        print()
        raise


def get_balance() -> str:
    """Check account balance."""
    return _http_get({"action": "getBalance"})


def parse_balance(text: str) -> Optional[float]:
    """Extract numeric balance from API response."""
    if not text.startswith("ACCESS_BALANCE:"):
        return None
    try:
        return float(text.split(":", 1)[1])
    except ValueError:
        return None


def get_prices(country: str = COUNTRY, operator: str = OPERATOR) -> str:
    """Get pricing for the given country/operator."""
    return _http_get(
        {
            "action": "getPrices",
            "country": country,
            "operator": operator,
        }
    )


def parse_prices(text: str) -> Dict[str, Any]:
    """Parse JSON-like price response into a dict; returns {} on failure."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def get_price_for_service(
    service: str = SERVICE, country: str = COUNTRY, operator: str = OPERATOR
) -> Optional[str]:
    """
    Fetch price data and return the price string for the given service,
    or None if not found.
    """
    raw = get_prices(country=country, operator=operator)
    data = parse_prices(raw)

    # Expected shape: { "22": { "pbk": { "2.99": "467" } } }
    country_block = data.get(str(country), {})
    service_block = country_block.get(service, {})
    if not isinstance(service_block, dict):
        return None

    price_keys = list(service_block.keys())
    return price_keys[0] if price_keys else None


def get_number(
    service: str = SERVICE,
    country: str = COUNTRY,
    operator: str = OPERATOR,
) -> Optional[Tuple[str, str]]:
    """
    Request a virtual number for a service.
    Returns (request_id, phone_number) or None on parse failure.
    Raises ValueError with "NO_NUMBERS" message if API returns NO_NUMBERS.
    """
    raw = _http_get(
        {
            "action": "getNumber",
            "service": service,
            "country": country,
            "operator": operator,
        }
    )
    # Check for NO_NUMBERS response before parsing
    if "NO_NUMBERS" in raw.upper() or "NO NUMBERS" in raw.upper():
        raise ValueError("NO_NUMBERS: No numbers available right now")
    return parse_number(raw)


def parse_number(text: str) -> Optional[Tuple[str, str]]:
    """
    Extract (request_id, phone_number) from ACCESS_NUMBER response.
    Strips leading '91' from the phone number if present.
    """
    if not text.startswith("ACCESS_NUMBER:"):
        return None
    try:
        _, req_id, raw_number = text.split(":", 2)
    except ValueError:
        return None

    number = raw_number
    if number.startswith("91") and len(number) > 2:
        number = number[2:]

    return req_id, number


def get_otp(
    request_id: str,
    timeout_seconds: float = 300.0,
    poll_interval: float = 1.0,
) -> Optional[str]:
    """
    Poll for OTP/status for up to timeout_seconds.
    Returns the OTP string if found; None if timeout or canceled.
    Raises Exception if number is canceled (status="cancelled" without OTP).
    """
    deadline = time.time() + timeout_seconds

    while True:
        response = _http_get({"action": "getStatus", "id": request_id})
        status, otp = parse_otp_response(response)

        # If number is canceled, raise exception to signal worker to exit
        if status == "cancelled" and not otp:
            raise Exception("[X] Number was canceled by backend")

        if status in ("ok", "cancelled") and otp:
            return otp

        if time.time() >= deadline:
            return otp  # may be None

        time.sleep(poll_interval)


def set_status(status: int, request_id: str) -> str:
    """Generic status update helper (e.g., 3=request new OTP, 8=cancel)."""
    return _http_get({"action": "setStatus", "status": status, "id": request_id})


def request_new_otp(request_id: str) -> str:
    """Shortcut: ask for another OTP (status=3)."""
    return set_status(3, request_id)


def cancel_number(request_id: str) -> str:
    """Shortcut: cancel the number (status=8)."""
    return set_status(8, request_id)


def parse_cancel_status(text: str) -> str:
    """
    Interpret cancel response.
    Returns 'accepted', 'already_cancelled', or raw text if unknown.
    """
    if text.startswith("ACCESS_CANCEL"):
        return "accepted"
    if text.startswith("ACCESS_CANCEL_ALREADY"):
        return "already_cancelled"
    return text


def extract_otp(text: str) -> Optional[str]:
    """
    Extract the first 4-8 digit OTP from the provided text.
    Returns None if no OTP found.
    """
    matches = re.findall(r"\b(\d{4,8})\b", text)
    if not matches:
        return None
    # Prefer the last match (often the actual OTP)
    return matches[-1]


def parse_otp_response(text: str) -> Tuple[str, Optional[str]]:
    """
    Parse getStatus response.
    Returns a tuple of (status, otp_or_none).
    """
    if text.startswith("STATUS_OK:"):
        otp = extract_otp(text)
        return "ok", otp
    if text.startswith("STATUS_CANCEL"):
        return "cancelled", None
    if text.startswith("ACCESS_WAITING"):
        return "waiting", None
    return "unknown", extract_otp(text)


def request_new_otp_until_new(
    request_id: str,
    previous_otp: Optional[str] = None,
    timeout_seconds: float = 300.0,
    poll_interval: float = 1.0,
) -> Optional[str]:
    """
    Ask for a fresh OTP (status=3) and poll until a new OTP different from
    previous_otp is received, or timeout is reached. Returns the new OTP or None.
    Raises Exception if number is canceled.
    """
    deadline = time.time() + timeout_seconds
    last_otp = previous_otp

    while True:
        set_status(3, request_id)
        time.sleep(poll_interval)

        try:
            otp = get_otp(request_id, timeout_seconds=poll_interval, poll_interval=poll_interval)
        except Exception as e:
            # If get_otp raises exception (e.g., number canceled), re-raise it
            if "canceled" in str(e).lower():
                raise
            # Otherwise, continue polling
            otp = None

        if otp and otp != last_otp:
            return otp

        if time.time() >= deadline:
            return None

        last_otp = otp or last_otp


def _print_menu() -> None:
    print(
        """
--- Temporasms Helper ---
1) Get balance
2) Get PBK price only
3) Get number
4) Get OTP
5) Request new OTP until different
6) Cancel number
0) Exit
"""
    )


def _menu():
    """Simple CLI to test the helper functions manually."""
    last_request_id: Optional[str] = None
    last_otp: Optional[str] = None

    while True:
        _print_menu()
        choice = input("Select option: ").strip()

        try:
            if choice == "1":
                res = get_balance()
                print("Raw:", res)
                print("Parsed balance:", parse_balance(res))
            elif choice == "2":
                price = get_price_for_service()
                print("PBK price:", price)
            elif choice == "3":
                parsed = get_number()
                print("Parsed:", parsed)
                if parsed:
                    last_request_id, number = parsed
                    print(f"Saved request_id={last_request_id}, number={number}")
            elif choice == "4":
                req_id = last_request_id
                if not req_id:
                    print("No request_id available. Get number first.")
                    continue
                otp = get_otp(req_id)
                last_otp = otp
                print("OTP:", otp)
            elif choice == "5":
                req_id = last_request_id
                if not req_id:
                    print("No request_id available. Get number first.")
                    continue
                otp = request_new_otp_until_new(req_id, previous_otp=last_otp)
                last_otp = otp
                print("New OTP:", otp)
            elif choice == "6":
                req_id = last_request_id
                if not req_id:
                    print("No request_id available. Get number first.")
                    continue
                res = cancel_number(req_id)
                print("Parsed:", parse_cancel_status(res))
            elif choice == "0":
                print("Bye.")
                break
            else:
                print("Invalid choice.")
        except Exception as exc:  # pragma: no cover - interactive helper
            print(f"Error: {exc}")


if __name__ == "__main__":
    _menu()

