import asyncio
from playwright.async_api import async_playwright, TimeoutError
import time
import os
from pathlib import Path
import requests

import caller
from caller import (
    cancel_number,
    get_number,
    get_otp,
    request_new_otp_until_new,
)
import imap


class AlreadyRegisteredError(Exception):
    """Raised when phone number is already registered."""
    pass


class NoNumbersAvailableError(Exception):
    """Raised when NO_NUMBERS response is received from API."""
    pass


class FatalAPIError(Exception):
    """Raised for BAD_ACTION, BAD_KEY, USER_BANNED and similar fatal API errors."""
    pass


# ==========================================================
# Local report helpers (used_emails / failed_numbers)
# And number-cancel queue
# ==========================================================
REPORTS_DIR = Path(".")
NUMBER_QUEUE_FILE = Path("number_queue.txt")


def _get_user_id() -> str:
    """Get user ID from environment variable."""
    return os.environ.get("USER_ID") or "0"

def _report_account_status(status: str, email: str = None) -> None:
    """
    Report account creation status (success/failed) to backend API.
    Used for margin_balance tracking and refunds.
    Prevents double-counting by including email in the report.
    """
    try:
        user_id = _get_user_id()
        backend_url = os.environ.get("BACKEND_URL", "http://localhost:6333")
        api_url = f"{backend_url}/api/account-status"
        
        payload = {"user_id": int(user_id), "status": status}
        if email:
            payload["email"] = email
        
        response = requests.post(
            api_url,
            json=payload,
            timeout=5,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            print(f"[DEBUG] [account_status] Reported account {status} to backend (email: {email or 'N/A'})")
        else:
            print(f"[WARN] [account_status] Failed to report account {status}: {response.status_code} {response.text}")
    except Exception as e:
        print(f"[WARN] [account_status] Exception reporting account {status}: {e}")

def append_used_email(email: str) -> None:
    """Append a successfully used email to per-user and global report files."""
    if not email:
        return
    user_id = _get_user_id()
    per_user_path = REPORTS_DIR / f"used_emails_user{user_id}.txt"
    global_path = REPORTS_DIR / "used_emails.txt"
    try:
        line = str(email).strip() + "\n"
        # Per-user file
        with open(per_user_path, "a", encoding="utf-8") as f:
            f.write(line)
        # Global file
        with open(global_path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        print(f"[REPORTS] Failed to write used email: {e}")


def append_failed_number(number: str) -> None:
    """Append a failed phone number to per-user and global report files."""
    if not number:
        return
    user_id = _get_user_id()
    per_user_path = REPORTS_DIR / f"failed_numbers_user{user_id}.txt"
    global_path_1 = REPORTS_DIR / "failed_numbers.txt"
    # Also support the legacy misspelled name for compatibility
    global_path_2 = REPORTS_DIR / "failed_numers.txt"
    try:
        line = str(number).strip() + "\n"
        # Per-user file
        with open(per_user_path, "a", encoding="utf-8") as f:
            f.write(line)
        # Global files
        with open(global_path_1, "a", encoding="utf-8") as f:
            f.write(line)
        with open(global_path_2, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        print(f"[REPORTS] Failed to write failed number: {e}")


def enqueue_number_for_cancel(request_id: str, acquired_at: float) -> None:
    """
    Add a request_id to the shared cancel queue.
    The backend will cancel it no earlier than 2 minutes after acquisition.
    """
    if not request_id:
        return
    try:
        user_id = _get_user_id()
        cancel_after = max(acquired_at + 120.0, time.time())
        with open(NUMBER_QUEUE_FILE, "a", encoding="utf-8") as f:
            f.write(f"{request_id},{cancel_after},{user_id}\n")
        print(f"[NUMBER_QUEUE] Enqueued {request_id} for cancellation at {cancel_after} (user_id: {user_id})")
    except Exception as e:
        print(f"[NUMBER_QUEUE] Failed to enqueue {request_id}: {e}")


def configure_caller_from_env() -> None:
    """
    Configure caller.py API settings from environment variables passed
    by the backend (per-user API key, base URL, service, server).
    """
    import json as json_module
    import time
    
    # #region agent log
    try:
        with open(r"c:\Users\zgarm\OneDrive\Desktop\Account creator\.cursor\debug.log", "a", encoding='utf-8') as log_file:
            log_file.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"account_creator.py:102","message":"configure_caller_from_env entry","data":{},"timestamp":int(time.time()*1000)}) + "\n")
    except: pass
    # #endregion
    
    api_key = (os.environ.get("API_KEY") or os.environ.get("SMS_API_KEY") or "").strip()
    base_url = os.environ.get("API_BASE_URL") or ""
    service = os.environ.get("API_SERVICE") or ""
    server = os.environ.get("API_SERVER") or ""
    wait_for_otp_minutes = os.environ.get("WAIT_FOR_OTP") or "5"
    wait_for_second_otp_minutes = os.environ.get("WAIT_FOR_SECOND_OTP") or "5"

    # #region agent log
    try:
        with open(r"c:\Users\zgarm\OneDrive\Desktop\Account creator\.cursor\debug.log", "a", encoding='utf-8') as log_file:
            log_file.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"account_creator.py:115","message":"Environment variables read","data":{"API_KEY_set":bool(api_key),"API_KEY_length":len(api_key),"API_BASE_URL":base_url,"API_SERVICE":service,"API_SERVER":server},"timestamp":int(time.time()*1000)}) + "\n")
    except: pass
    # #endregion

    # Parse wait_for_otp (in minutes) and convert to seconds
    global WAIT_FOR_OTP_SECONDS, WAIT_FOR_SECOND_OTP_SECONDS
    try:
        WAIT_FOR_OTP_SECONDS = float(wait_for_otp_minutes) * 60.0
    except (ValueError, TypeError):
        WAIT_FOR_OTP_SECONDS = 300.0  # Default: 5 minutes
        print(f"[DEBUG] [account_creator] Invalid WAIT_FOR_OTP value '{wait_for_otp_minutes}', using default 300 seconds")
    
    try:
        WAIT_FOR_SECOND_OTP_SECONDS = float(wait_for_second_otp_minutes) * 60.0
    except (ValueError, TypeError):
        WAIT_FOR_SECOND_OTP_SECONDS = 300.0  # Default: 5 minutes
        print(f"[DEBUG] [account_creator] Invalid WAIT_FOR_SECOND_OTP value '{wait_for_second_otp_minutes}', using default 300 seconds")

    # Debug: Print what we received from environment
    print(f"[DEBUG] [account_creator] Environment variables:")
    print(f"  API_KEY: {'***SET***' if api_key else 'NOT SET'}")
    print(f"  API_BASE_URL: {base_url if base_url else 'NOT SET (using default: ' + caller.BASE_URL + ')'}")
    print(f"  API_SERVICE: {service if service else 'NOT SET (using default: ' + caller.SERVICE + ')'}")
    print(f"  API_SERVER: {server if server else 'NOT SET (using default: ' + caller.SERVER + ')'}")
    print(f"  WAIT_FOR_OTP: {wait_for_otp_minutes} minutes ({WAIT_FOR_OTP_SECONDS} seconds) - first OTP")
    print(f"  WAIT_FOR_SECOND_OTP: {wait_for_second_otp_minutes} minutes ({WAIT_FOR_SECOND_OTP_SECONDS} seconds) - second OTP")

    if api_key:
        caller.API_KEY = api_key
        print(f"[DEBUG] [account_creator] Updated API_KEY")
    if base_url:
        caller.BASE_URL = base_url
        print(f"[DEBUG] [account_creator] Updated BASE_URL to: {base_url}")
    if service:
        caller.SERVICE = service
        print(f"[DEBUG] [account_creator] Updated SERVICE to: {service}")
    if server:
        caller.SERVER = server
        print(f"[DEBUG] [account_creator] Updated SERVER to: {server}")
    
    # #region agent log
    try:
        with open(r"c:\Users\zgarm\OneDrive\Desktop\Account creator\.cursor\debug.log", "a", encoding='utf-8') as log_file:
            log_file.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"account_creator.py:142","message":"Final caller configuration","data":{"BASE_URL":caller.BASE_URL,"SERVICE":caller.SERVICE,"SERVER":caller.SERVER,"API_KEY_set":bool(caller.API_KEY)},"timestamp":int(time.time()*1000)}) + "\n")
    except: pass
    # #endregion
    
    # Print final configuration
    print(f"[DEBUG] [account_creator] Final caller configuration:")
    print(f"  BASE_URL: {caller.BASE_URL}")
    print(f"  SERVICE: {caller.SERVICE}")
    print(f"  SERVER: {caller.SERVER}")


USE_USED_ACCOUNT = (os.environ.get("USE_USED_ACCOUNT") or "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

RETRY_FAILED = (os.environ.get("RETRY_FAILED") or "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# Wait for OTP timeout in seconds (default: 5 minutes = 300 seconds)
# These will be updated by configure_caller_from_env() from environment variables (in minutes)
WAIT_FOR_OTP_SECONDS = 300.0  # For first OTP (signup OTP)
WAIT_FOR_SECOND_OTP_SECONDS = 300.0  # For second OTP (phone OTP)


async def main():
    # Ensure SMS API calls inside this worker use the same credentials/settings
    # as the backend used to compute balance/capacity.
    configure_caller_from_env()
    browser = None
    browser_closed = False
    
    try:
        while True:
            request_id = None
            phone_number = None
            first_otp = None
            flipkart_email = None
            number_acquired_at = None

            try:
                async with async_playwright() as p:
                    try:
                        print("[DEBUG] Launching browser...")
                        browser = await p.chromium.launch(headless=True)
                        context = await browser.new_context()
                        page = await context.new_page()
                        # ---- GENERATE EMAIL ----
                        flipkart_email = await asyncio.to_thread(imap.generate_flipkart_email)
                        print(f"[DEBUG] Generated Flipkart email: {flipkart_email}")
                        
                        # Report to backend that we started with this email (allows cleanup on stop)
                        await asyncio.to_thread(_report_account_status, "started", flipkart_email)

                        # ---- GET NUMBER FROM API ----
                        print("[DEBUG] Fetching number from API...")
                        try:
                            # Call get_number with explicit values from caller module
                            # (can't rely on default params since they're evaluated at import time)
                            number_info = await asyncio.to_thread(
                                lambda: caller.get_number(
                                    service=caller.SERVICE,
                                    server=caller.SERVER
                                )
                            )
                            if not number_info:
                                raise Exception("[X] Failed to get number from API")
                            request_id, phone_number = number_info
                            print(f"[DEBUG] [OK] Got number: request_id={request_id}, phone={phone_number}")
                            number_acquired_at = time.time()
                            # Enqueue this number for cancellation; backend will cancel after 2 minutes
                            enqueue_number_for_cancel(request_id, number_acquired_at)
                        except Exception as e:
                            error_msg = str(e)
                            if "NO_NUMBERS" in error_msg or "No numbers available" in error_msg:
                                raise NoNumbersAvailableError("No numbers available right now")
                            raise

                        # ---- OPEN SIGNUP ----
                        print("[DEBUG] Navigating to Flipkart signup page...")
                        await page.goto("https://www.flipkart.com/account/login?signup=true")
                        await asyncio.sleep(2)  # Wait for page to fully load in headless mode
                        print("[DEBUG] [OK] Page loaded")

                        # Fill phone number
                        print("[DEBUG] Waiting for phone input field...")
                        await page.wait_for_selector("input[type='text'][maxlength='10']")
                        await asyncio.sleep(1)  # Small delay after selector appears
                        print("[DEBUG] [OK] Phone input field found")
                        
                        phone_input = page.locator("input[type='text'][maxlength='10']")
                        print(f"[DEBUG] Filling phone number: {phone_number}")
                        await phone_input.fill(phone_number)
                        await asyncio.sleep(1)  # Wait after filling
                        print("[DEBUG] [OK] Phone number filled")
                        
                        print("[DEBUG] Pressing Enter...")
                        await page.keyboard.press("Enter")
                        await asyncio.sleep(2)  # Wait for response after Enter
                        print("[DEBUG] [OK] Enter pressed")

                        # ---- CHECK IF ALREADY REGISTERED MESSAGE APPEARS ----
                        await asyncio.sleep(1)  # Wait before checking for error message
                        print("[DEBUG] Checking for 'already registered' message (3s timeout)...")
                        try:
                            await page.wait_for_selector("div.LERBMj", timeout=3000)
                            await asyncio.sleep(0.5)  # Small delay after selector appears
                            error_text = await page.locator("div.LERBMj").inner_text()
                            print(f"[DEBUG] [WARN] Error message found: '{error_text}'")

                            if "already registered" in error_text.lower():
                                if USE_USED_ACCOUNT:
                                    print("[DEBUG] [FAIL] Used-account mode ENABLED - triggering recovery flow")
                                    raise AlreadyRegisteredError("USER ALREADY REGISTERED")
                                else:
                                    print("[DEBUG] [FAIL] Used-account mode DISABLED - skipping this number and retrying")
                                    raise Exception("SKIP_USED_ACCOUNT_ALREADY_REGISTERED")
                            else:
                                print(f"[DEBUG] Error message present but not 'already registered': {error_text}")

                        except TimeoutError:
                            print("[DEBUG] [OK] No error message - continuing with signup")
                            pass

                        # ---- FETCH SIGNUP OTP ----
                        print(f"[DEBUG] Fetching OTP for request_id={request_id} (timeout: {WAIT_FOR_OTP_SECONDS}s)...")
                        
                        # Set up timeout task to cancel number and stop ALL workers if OTP timeout is reached
                        async def cancel_on_timeout(req_id: str, timeout_sec: float, user_id: str):
                            await asyncio.sleep(timeout_sec)
                            print(f"[TIMEOUT] First OTP timeout ({timeout_sec}s) reached - canceling number {req_id} and stopping ALL workers")
                            try:
                                await asyncio.to_thread(caller.cancel_number, req_id)
                                print(f"[TIMEOUT] Number {req_id} canceled due to first OTP timeout")
                            except Exception as e:
                                print(f"[TIMEOUT] Failed to cancel number {req_id}: {e}")
                            
                            # Signal backend to stop ALL parallel workers for this user
                            try:
                                backend_url = os.environ.get("BACKEND_URL", "http://localhost:6333")
                                stop_url = f"{backend_url}/api/stop"
                                print(f"[TIMEOUT] Signaling backend to stop all workers: {stop_url}")
                                response = await asyncio.to_thread(
                                    requests.post, stop_url,
                                    json={"user_id": user_id},
                                    timeout=5,
                                    headers={"Content-Type": "application/json"}
                                )
                                print(f"[TIMEOUT] Backend stop response: {response.status_code}")
                            except Exception as e:
                                print(f"[TIMEOUT] Failed to signal backend to stop workers: {e}")
                            
                            raise Exception(f"[X] First OTP timeout ({timeout_sec}s) - number canceled and ALL workers stopped")
                        
                        user_id = _get_user_id()
                        timeout_task = asyncio.create_task(cancel_on_timeout(request_id, WAIT_FOR_OTP_SECONDS, user_id))
                        
                        try:
                            otp = await asyncio.to_thread(get_otp, request_id, WAIT_FOR_OTP_SECONDS, 1.0)
                            timeout_task.cancel()  # Cancel timeout task if OTP received
                            if not otp:
                                print("[DEBUG] [WARN] First OTP fetch failed, requesting new OTP...")
                                # Restart timeout for retry
                                timeout_task = asyncio.create_task(cancel_on_timeout(request_id, WAIT_FOR_OTP_SECONDS, user_id))
                                otp = await asyncio.to_thread(
                                    request_new_otp_until_new, request_id, None, WAIT_FOR_OTP_SECONDS, 1.0
                                )
                                timeout_task.cancel()  # Cancel timeout task if OTP received
                            if not otp:
                                raise Exception("[X] Failed to retrieve OTP from API")
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            timeout_task.cancel()  # Cancel timeout task on any exception
                            if "timeout" in str(e).lower() and "first otp" in str(e).lower():
                                raise  # Re-raise timeout exception
                            raise
                        first_otp = otp  # Store the first OTP
                        print(f"[DEBUG] [OK] Got OTP: {otp}")

                        # Fill OTP
                        print("[DEBUG] Waiting for OTP input field...")
                        await page.wait_for_selector("input[type='text'][maxlength='6']")
                        await asyncio.sleep(1.5)  # Wait for OTP field to be ready in headless mode
                        print("[DEBUG] [OK] OTP input field found")
                        
                        otp_box = page.locator("input[type='text'][maxlength='6']")
                        print(f"[DEBUG] Clicking OTP input field...")
                        await otp_box.click()
                        await asyncio.sleep(0.5)  # Wait after clicking
                        print(f"[DEBUG] Typing OTP digit by digit: {otp}")
                        for digit in otp:
                            await page.keyboard.type(digit)
                            await asyncio.sleep(0.15)  # Slightly longer delay between digits in headless mode
                        await asyncio.sleep(1)  # Wait after typing OTP
                        print("[DEBUG] [OK] OTP typed digit by digit")
                        
                        print("[DEBUG] Pressing Enter after OTP...")
                        await page.keyboard.press("Enter")
                        await asyncio.sleep(2)  # Wait for response after Enter in headless mode
                        print("[DEBUG] [OK] Enter pressed after OTP")

                        # Check for incorrect OTP message
                        print("[DEBUG] Checking for 'OTP is incorrect' message (3s timeout)...")
                        try:
                            await page.wait_for_selector("div.LERBMj", timeout=3000)
                            error_text = await page.locator("div.LERBMj").inner_text()
                            if "otp is incorrect" in error_text.lower():
                                print(f"[DEBUG] [FAIL] OTP INCORRECT: {error_text}")
                                raise Exception(f"[X] OTP is incorrect: {error_text}")
                            print(f"[DEBUG] [WARN] Some error after OTP: {error_text}")
                        except TimeoutError:
                            print("[DEBUG] [OK] No OTP error - continuing")
                            pass

                        print("[OK] OTP submitted successfully!")
                        await asyncio.sleep(2)  # Wait for page to process OTP

                        # ---- GO TO ACCOUNT EDIT PAGE ----
                        print("[DEBUG] Navigating to account page...")
                        await page.goto("https://www.flipkart.com/account/?rd=0&link=home_account")
                        await asyncio.sleep(2)  # Wait for account page to fully load in headless mode
                        print("[DEBUG] [OK] Account page loaded")

                        # Click Email Address Edit
                        print("[DEBUG] Waiting for Email Address section...")
                        await page.wait_for_selector("div.Rxk9lv:has(span.SLEz3j:text('Email Address'))", timeout=30000)
                        await asyncio.sleep(1.5)  # Wait for element to be fully interactive in headless mode
                        print("[DEBUG] [OK] Email Address section found")
                        
                        email_edit_btn = page.locator("div.Rxk9lv", has_text="Email Address").locator("a.GyKGMu")
                        print("[DEBUG] Clicking Email Address Edit...")
                        await email_edit_btn.click()
                        await asyncio.sleep(2)  # Wait for edit form to appear
                        print("[OK] Clicked Email Address Edit")

                        # ---- ENTER NEW EMAIL ----
                        print("[DEBUG] Waiting for email input...")
                        await page.wait_for_selector("input[name='email']", timeout=30000)
                        await asyncio.sleep(1)  # Wait for input field to be ready
                        print("[DEBUG] [OK] Email input found")
                        
                        email_input = page.locator("input[name='email']")
                        print(f"[DEBUG] Filling email: {flipkart_email}")
                        await email_input.fill(flipkart_email)
                        await asyncio.sleep(1)  # Wait after filling email
                        print("[DEBUG] [OK] Email filled")
                        
                        print("[DEBUG] Pressing Enter after email...")
                        await page.keyboard.press("Enter")
                        await asyncio.sleep(2)  # Wait for response after Enter
                        print("[OK] Email filled")

                        # ---- ENTER EMAIL OTP ----
                        print("[DEBUG] Waiting for OTP input fields...")
                        await page.wait_for_selector("input[maxlength='6']", timeout=30000)
                        await asyncio.sleep(1)  # Wait for OTP fields to be ready
                        print("[DEBUG] [OK] OTP fields found")
                        
                        email_otp_input = page.locator(f"input[name='{flipkart_email}']")

                        # Fetch email OTP from IMAP
                        print(f"[DEBUG] Fetching email OTP from IMAP for {flipkart_email}...")
                        email_otp = await asyncio.to_thread(imap.otp, flipkart_email)
                        if not email_otp:
                            raise Exception("[X] Failed to retrieve email OTP from IMAP")
                        print(f"[DEBUG] [OK] Got email OTP: {email_otp}")
                        
                        print(f"[DEBUG] Clicking email OTP input...")
                        await email_otp_input.click()
                        await asyncio.sleep(0.5)  # Wait after clicking
                        print(f"[DEBUG] Typing email OTP digit by digit: {email_otp}")
                        for digit in email_otp:
                            await page.keyboard.type(digit)
                            await asyncio.sleep(0.15)  # Slightly longer delay between digits in headless mode
                        await asyncio.sleep(1)  # Wait after typing email OTP
                        print("[DEBUG] [OK] Email OTP typed digit by digit")

                        # Press TAB to move to phone OTP
                        print("[DEBUG] Pressing Tab to move to phone OTP field...")
                        await page.keyboard.press("Tab")
                        await asyncio.sleep(1)  # Wait after Tab press
                        print("[DEBUG] [OK] Tab pressed")

                        # ---- ENTER PHONE OTP ----
                        print(f"[DEBUG] Fetching phone OTP for request_id={request_id} (must be different from first OTP: {first_otp}, timeout: {WAIT_FOR_SECOND_OTP_SECONDS}s)...")
                        
                        # Set up timeout task to cancel number and stop ALL workers if second OTP timeout is reached
                        async def cancel_on_second_otp_timeout(req_id: str, timeout_sec: float, user_id: str):
                            await asyncio.sleep(timeout_sec)
                            print(f"[TIMEOUT] Second OTP timeout ({timeout_sec}s) reached - canceling number {req_id} and stopping ALL workers")
                            try:
                                await asyncio.to_thread(caller.cancel_number, req_id)
                                print(f"[TIMEOUT] Number {req_id} canceled due to second OTP timeout")
                            except Exception as e:
                                print(f"[TIMEOUT] Failed to cancel number {req_id}: {e}")
                            
                            # Signal backend to stop ALL parallel workers for this user
                            try:
                                backend_url = os.environ.get("BACKEND_URL", "http://localhost:6333")
                                stop_url = f"{backend_url}/api/stop"
                                print(f"[TIMEOUT] Signaling backend to stop all workers: {stop_url}")
                                user_id = _get_user_id()
                                response = await asyncio.to_thread(
                                    requests.post, stop_url,
                                    json={"user_id": user_id},
                                    timeout=5,
                                    headers={"Content-Type": "application/json"}
                                )
                                print(f"[TIMEOUT] Backend stop response: {response.status_code}")
                            except Exception as e:
                                print(f"[TIMEOUT] Failed to signal backend to stop workers: {e}")
                            
                            raise Exception(f"[X] Second OTP timeout ({timeout_sec}s) - number canceled and ALL workers stopped")
                        
                        user_id = _get_user_id()
                        timeout_task = asyncio.create_task(cancel_on_second_otp_timeout(request_id, WAIT_FOR_SECOND_OTP_SECONDS, user_id))
                        
                        try:
                            phone_otp = await asyncio.to_thread(request_new_otp_until_new, request_id, first_otp, WAIT_FOR_SECOND_OTP_SECONDS, 1.0)
                            timeout_task.cancel()  # Cancel timeout task if OTP received
                            if not phone_otp:
                                raise Exception("[X] Failed to retrieve phone OTP from API")
                            if phone_otp == first_otp:
                                raise Exception(f"[X] Phone OTP is same as first OTP ({first_otp}), this should not happen")
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            timeout_task.cancel()  # Cancel timeout task on any exception
                            if "timeout" in str(e).lower() and "second otp" in str(e).lower():
                                raise  # Re-raise timeout exception
                            raise
                        print(f"[DEBUG] [OK] Got phone OTP: {phone_otp} (different from first: {first_otp})")
                        
                        print(f"[DEBUG] Clicking phone OTP input...")
                        otp_inputs = page.locator("input[maxlength='6']")
                        phone_otp_input = otp_inputs.nth(1)
                        await phone_otp_input.click()
                        await asyncio.sleep(0.5)  # Wait after clicking
                        print(f"[DEBUG] Typing phone OTP digit by digit: {phone_otp}")
                        for digit in phone_otp:
                            await page.keyboard.type(digit)
                            await asyncio.sleep(0.15)  # Slightly longer delay between digits in headless mode
                        await asyncio.sleep(1)  # Wait after typing phone OTP
                        print("[DEBUG] [OK] Phone OTP typed digit by digit")

                        print("[OK] Both OTPs entered")
                        await asyncio.sleep(1)  # Wait before clicking submit

                        # ---- CLICK SUBMIT ----
                        print("[DEBUG] Waiting for Submit button...")
                        await page.wait_for_selector("button.dSM5Ub.xSzOV7", timeout=30000)
                        await asyncio.sleep(1)  # Wait for button to be ready
                        print("[DEBUG] [OK] Submit button found")
                        
                        print("[DEBUG] Clicking Submit button...")
                        await page.locator("button.dSM5Ub.xSzOV7").click()
                        await asyncio.sleep(2)  # Wait for submission to process
                        print("[OK] Submit button clicked!")

                        print("\n[OK] Account creation successful! Closing browser...")
                        # Record successful email in local report file
                        if flipkart_email:
                            await asyncio.to_thread(append_used_email, flipkart_email)
                            # Mark email as successfully used (remove from failed list if present)
                            await asyncio.to_thread(imap.mark_email_success, flipkart_email)
                            # Unreserve email (move from reserved to used)
                            await asyncio.to_thread(imap.unreserve_email, flipkart_email)
                        
                        # Report account success to backend for margin_balance tracking
                        await asyncio.to_thread(_report_account_status, "success", flipkart_email)
                        
                        await asyncio.sleep(3)
                        
                        return  # Success: exit worker loop

                    except AlreadyRegisteredError:
                        # Recovery flow - we're still inside async with block so page is available
                        print("\n[RECOVERY] Starting recovery flow for already registered user...")
                        recovery_first_otp = None
                        try:
                            if request_id and phone_number:
                                print(f"[RECOVERY] Looking for login input field...")
                                phone_field = page.locator("input.c3Bd2c.yXUQVt[type='text']")
                                field_count = await phone_field.count()
                                print(f"[RECOVERY] Found {field_count} matching input field(s)")
                                
                                if field_count > 0:
                                    print(f"[RECOVERY] Clicking on input field...")
                                    await phone_field.click()
                                    await asyncio.sleep(1)  # Wait after clicking in recovery
                                    print(f"[RECOVERY] [OK] Field clicked")
                                    
                                    print(f"[RECOVERY] Filling phone number: {phone_number}")
                                    await phone_field.fill(phone_number)
                                    await asyncio.sleep(1)  # Wait after filling in recovery
                                    print(f"[RECOVERY] [OK] Phone filled")
                                    
                                    print(f"[RECOVERY] Pressing Enter...")
                                    await page.keyboard.press("Enter")
                                    await asyncio.sleep(2)  # Wait for response after Enter in recovery
                                    print(f"[RECOVERY] [OK] Enter pressed")

                                    # Re-fetch OTP
                                    print(f"[RECOVERY] Fetching OTP for request_id={request_id} (timeout: {WAIT_FOR_OTP_SECONDS}s)...")
                                    
                                    # Set up timeout task to cancel number and stop ALL workers if first OTP timeout is reached (recovery)
                                    async def cancel_on_recovery_first_otp_timeout(req_id: str, timeout_sec: float, user_id: str):
                                        await asyncio.sleep(timeout_sec)
                                        print(f"[TIMEOUT] [RECOVERY] First OTP timeout ({timeout_sec}s) reached - canceling number {req_id} and stopping ALL workers")
                                        try:
                                            await asyncio.to_thread(caller.cancel_number, req_id)
                                            print(f"[TIMEOUT] [RECOVERY] Number {req_id} canceled due to first OTP timeout")
                                        except Exception as e:
                                            print(f"[TIMEOUT] [RECOVERY] Failed to cancel number {req_id}: {e}")
                                        
                                        # Signal backend to stop ALL parallel workers for this user
                                        try:
                                            backend_url = os.environ.get("BACKEND_URL", "http://localhost:6333")
                                            stop_url = f"{backend_url}/api/stop"
                                            print(f"[TIMEOUT] [RECOVERY] Signaling backend to stop all workers: {stop_url}")
                                            response = await asyncio.to_thread(
                                                requests.post, stop_url,
                                                json={"user_id": user_id},
                                                timeout=5,
                                                headers={"Content-Type": "application/json"}
                                            )
                                            print(f"[TIMEOUT] [RECOVERY] Backend stop response: {response.status_code}")
                                        except Exception as e:
                                            print(f"[TIMEOUT] [RECOVERY] Failed to signal backend to stop workers: {e}")
                                        
                                        raise Exception(f"[X] [RECOVERY] First OTP timeout ({timeout_sec}s) - number canceled and ALL workers stopped")
                                    
                                    user_id = _get_user_id()
                                    timeout_task = asyncio.create_task(cancel_on_recovery_first_otp_timeout(request_id, WAIT_FOR_OTP_SECONDS, user_id))
                                    
                                    try:
                                        otp = await asyncio.to_thread(get_otp, request_id, WAIT_FOR_OTP_SECONDS, 1.0)
                                        timeout_task.cancel()  # Cancel timeout task if OTP received
                                        if not otp:
                                            raise Exception("[X] Failed to retrieve OTP during recovery")
                                    except asyncio.CancelledError:
                                        raise
                                    except Exception as e:
                                        timeout_task.cancel()  # Cancel timeout task on any exception
                                        if "timeout" in str(e).lower() and "first otp" in str(e).lower():
                                            raise  # Re-raise timeout exception
                                        raise
                                    recovery_first_otp = otp
                                    print(f"[RECOVERY] [OK] Got OTP: {otp}")

                                    # Directly type OTP digit by digit
                                    print(f"[RECOVERY] Typing OTP digit by digit: {otp}")
                                    for digit in otp:
                                        await page.keyboard.type(digit)
                                        await asyncio.sleep(0.15)  # Slightly longer delay in headless mode
                                    await asyncio.sleep(1)  # Wait after typing OTP
                                    print(f"[RECOVERY] [OK] OTP typed digit by digit")
                                    print(f"[RECOVERY] Pressing Enter...")
                                    await page.keyboard.press("Enter")
                                    await asyncio.sleep(2)  # Wait for response after Enter
                                    print(f"[RECOVERY] [OK] Enter pressed")

                            # Continue from edit page
                            print("[RECOVERY] Navigating to account page...")
                            await page.goto("https://www.flipkart.com/account/?rd=0&link=home_account")
                            await asyncio.sleep(2)  # Wait for account page to load in headless mode
                            print("[RECOVERY] [OK] Account page loaded")
                            
                            print("[RECOVERY] Waiting for Email Address section...")
                            await page.wait_for_selector("div.Rxk9lv:has(span.SLEz3j:text('Email Address'))", timeout=30000)
                            await asyncio.sleep(1.5)  # Wait for element to be ready
                            print("[RECOVERY] [OK] Email section found")
                            
                            email_edit_btn = page.locator("div.Rxk9lv", has_text="Email Address").locator("a.GyKGMu")
                            print("[RECOVERY] Clicking Email Address Edit...")
                            await email_edit_btn.click()
                            await asyncio.sleep(2)  # Wait for edit form to appear
                            print("[RECOVERY] [OK] Clicked Email Address Edit")

                            print("[RECOVERY] Waiting for email input...")
                            await page.wait_for_selector("input[name='email']", timeout=30000)
                            await asyncio.sleep(1)  # Wait for input field to be ready
                            print("[RECOVERY] [OK] Email input found")
                            
                            email_input = page.locator("input[name='email']")
                            print(f"[RECOVERY] Filling email: {flipkart_email}")
                            await email_input.fill(flipkart_email)
                            await asyncio.sleep(1)  # Wait after filling email
                            print("[RECOVERY] [OK] Email filled")
                            
                            print("[RECOVERY] Pressing Enter...")
                            await page.keyboard.press("Enter")
                            await asyncio.sleep(2)  # Wait for response after Enter
                            print("[RECOVERY] [OK] Enter pressed")

                            print("[RECOVERY] Waiting for OTP fields...")
                            await page.wait_for_selector("input[maxlength='6']", timeout=30000)
                            await asyncio.sleep(1)  # Wait for OTP fields to be ready
                            print("[RECOVERY] [OK] OTP fields found")
                            
                            email_otp_input = page.locator(f"input[name='{flipkart_email}']")
                            
                            # Fetch email OTP from IMAP
                            print(f"[RECOVERY] Fetching email OTP from IMAP for {flipkart_email}...")
                            email_otp = await asyncio.to_thread(imap.otp, flipkart_email)
                            if not email_otp:
                                raise Exception("[X] Failed to retrieve email OTP from IMAP during recovery")
                            print(f"[RECOVERY] [OK] Got email OTP: {email_otp}")
                            
                            print(f"[RECOVERY] Clicking email OTP input...")
                            await email_otp_input.click()
                            await asyncio.sleep(0.5)  # Wait after clicking
                            print(f"[RECOVERY] Typing email OTP digit by digit: {email_otp}")
                            for digit in email_otp:
                                await page.keyboard.type(digit)
                                await asyncio.sleep(0.15)  # Slightly longer delay in headless mode
                            await asyncio.sleep(1)  # Wait after typing email OTP
                            print("[RECOVERY] [OK] Email OTP typed digit by digit")

                            print("[RECOVERY] Pressing Tab...")
                            await page.keyboard.press("Tab")
                            await asyncio.sleep(1)  # Wait after Tab press
                            print("[RECOVERY] [OK] Tab pressed")

                            # Fetch phone OTP using request_new_otp_until_new (must be different from first OTP)
                            print(f"[RECOVERY] Fetching phone OTP for request_id={request_id} (must be different from first OTP: {recovery_first_otp}, timeout: {WAIT_FOR_SECOND_OTP_SECONDS}s)...")
                            
                            # Set up timeout task to cancel number and stop ALL workers if second OTP timeout is reached (recovery)
                            async def cancel_on_recovery_second_otp_timeout(req_id: str, timeout_sec: float, user_id: str):
                                await asyncio.sleep(timeout_sec)
                                print(f"[TIMEOUT] [RECOVERY] Second OTP timeout ({timeout_sec}s) reached - canceling number {req_id} and stopping ALL workers")
                                try:
                                    await asyncio.to_thread(caller.cancel_number, req_id)
                                    print(f"[TIMEOUT] [RECOVERY] Number {req_id} canceled due to second OTP timeout")
                                except Exception as e:
                                    print(f"[TIMEOUT] [RECOVERY] Failed to cancel number {req_id}: {e}")
                                
                                # Signal backend to stop ALL parallel workers for this user
                                try:
                                    backend_url = os.environ.get("BACKEND_URL", "http://localhost:6333")
                                    stop_url = f"{backend_url}/api/stop"
                                    print(f"[TIMEOUT] [RECOVERY] Signaling backend to stop all workers: {stop_url}")
                                    response = await asyncio.to_thread(
                                        requests.post, stop_url,
                                        json={"user_id": user_id},
                                        timeout=5,
                                        headers={"Content-Type": "application/json"}
                                    )
                                    print(f"[TIMEOUT] [RECOVERY] Backend stop response: {response.status_code}")
                                except Exception as e:
                                    print(f"[TIMEOUT] [RECOVERY] Failed to signal backend to stop workers: {e}")
                                
                                raise Exception(f"[X] [RECOVERY] Second OTP timeout ({timeout_sec}s) - number canceled and ALL workers stopped")
                            
                            user_id = _get_user_id()
                            timeout_task = asyncio.create_task(cancel_on_recovery_second_otp_timeout(request_id, WAIT_FOR_SECOND_OTP_SECONDS, user_id))
                            
                            try:
                                phone_otp = await asyncio.to_thread(request_new_otp_until_new, request_id, recovery_first_otp, WAIT_FOR_SECOND_OTP_SECONDS, 1.0)
                                timeout_task.cancel()  # Cancel timeout task if OTP received
                                if not phone_otp:
                                    raise Exception("[X] Failed to retrieve phone OTP from API during recovery")
                                if phone_otp == recovery_first_otp:
                                    raise Exception(f"[X] Phone OTP is same as first OTP ({recovery_first_otp}), this should not happen")
                            except asyncio.CancelledError:
                                raise
                            except Exception as e:
                                timeout_task.cancel()  # Cancel timeout task on any exception
                                if "timeout" in str(e).lower() and "second otp" in str(e).lower():
                                    raise  # Re-raise timeout exception
                                raise
                            print(f"[RECOVERY] [OK] Got phone OTP: {phone_otp} (different from first: {recovery_first_otp})")
                            
                            print(f"[RECOVERY] Clicking phone OTP input...")
                            otp_inputs = page.locator("input[maxlength='6']")
                            phone_otp_input = otp_inputs.nth(1)
                            await phone_otp_input.click()
                            await asyncio.sleep(0.5)  # Wait after clicking
                            print(f"[RECOVERY] Typing phone OTP digit by digit: {phone_otp}")
                            for digit in phone_otp:
                                await page.keyboard.type(digit)
                                await asyncio.sleep(0.15)  # Slightly longer delay in headless mode
                            await asyncio.sleep(1)  # Wait after typing phone OTP
                            print("[RECOVERY] [OK] Phone OTP typed digit by digit")

                            await asyncio.sleep(1)  # Wait before clicking submit
                            print("[RECOVERY] Waiting for Submit button...")
                            await page.wait_for_selector("button.dSM5Ub.xSzOV7", timeout=30000)
                            await asyncio.sleep(1)  # Wait for button to be ready
                            print("[RECOVERY] [OK] Submit button found")
                            
                            print("[RECOVERY] Clicking Submit...")
                            await page.locator("button.dSM5Ub.xSzOV7").click()
                            await asyncio.sleep(2)  # Wait for submission to process
                            print("[RECOVERY] [OK] Recovery submit clicked!")

                            print("\n[OK] Recovery completed! Closing browser...")

                            # Record successful email in local report file
                            if flipkart_email:
                                await asyncio.to_thread(append_used_email, flipkart_email)
                                # Mark email as successfully used (remove from failed list if present)
                                await asyncio.to_thread(imap.mark_email_success, flipkart_email)
                                # Unreserve email (move from reserved to used)
                                await asyncio.to_thread(imap.unreserve_email, flipkart_email)

                            # Report account success to backend for margin_balance tracking
                            await asyncio.to_thread(_report_account_status, "success", flipkart_email if flipkart_email else None)

                            await asyncio.sleep(3)

                            return  # Success: exit worker loop
                        except Exception as recovery_exc:
                            print(f"[RECOVERY] [X] Recovery failed: {recovery_exc}")
                            # Track failed email for reuse
                            if flipkart_email:
                                await asyncio.to_thread(imap.add_failed_email, flipkart_email)
                                # Unreserve email so it can be reused
                                await asyncio.to_thread(imap.unreserve_email, flipkart_email)
                            # Report account failure to backend for margin_balance refund
                            await asyncio.to_thread(_report_account_status, "failed", flipkart_email if flipkart_email else None)
                            raise  # Re-raise to trigger outer exception handler

            except NoNumbersAvailableError:
                print("[ERROR] [X] NO_NUMBERS: No numbers available right now")
                print("[NO_NUMBERS] This account creation failed due to NO_NUMBERS - will refund margin_balance")
                
                # Note: When we get NO_NUMBERS, no number was acquired, so there's nothing to cancel
                # However, if we somehow have a request_id from a previous attempt, handle it
                if request_id and number_acquired_at:
                    time_elapsed = time.time() - number_acquired_at
                    if time_elapsed < 120:  # Less than 2 minutes
                        print(f"[NO_NUMBERS] Found number {request_id} from previous attempt (acquired {time_elapsed:.1f}s ago, < 2 mins), canceling immediately")
                        try:
                            await asyncio.to_thread(caller.cancel_number, request_id)
                            print(f"[NO_NUMBERS] Successfully canceled number {request_id}")
                        except Exception as cancel_err:
                            print(f"[NO_NUMBERS] Failed to cancel number {request_id}: {cancel_err}")
                            # If cancel fails, ensure it's in the queue for later cancellation
                            enqueue_number_for_cancel(request_id, number_acquired_at)
                            print(f"[NO_NUMBERS] Number {request_id} added to cancellation queue")
                    else:
                        # Already >= 2 mins, just ensure it's in queue
                        enqueue_number_for_cancel(request_id, number_acquired_at)
                        print(f"[NO_NUMBERS] Number {request_id} was acquired {time_elapsed:.1f}s ago (>= 2 mins), added to queue")
                
                # Track failed email for reuse
                if flipkart_email:
                    await asyncio.to_thread(imap.add_failed_email, flipkart_email)
                    # Unreserve email so it can be reused
                    await asyncio.to_thread(imap.unreserve_email, flipkart_email)
                    print(f"[NO_NUMBERS] Added failed email to use_first_mails.txt: {flipkart_email}")
                else:
                    print("[NO_NUMBERS] No email generated yet, skipping failed email tracking")
                
                # CRITICAL: ALWAYS report account failure to backend for margin_balance refund
                # This ensures the user gets refunded even when NO_NUMBERS occurs
                print(f"[NO_NUMBERS] Reporting account failure to backend for margin_balance refund (email: {flipkart_email or 'N/A'})")
                try:
                    await asyncio.to_thread(_report_account_status, "failed", flipkart_email if flipkart_email else None)
                    print("[NO_NUMBERS] Successfully reported account failure - margin_balance refund should be processed")
                except Exception as report_err:
                    print(f"[ERROR] [NO_NUMBERS] Failed to report account failure for refund: {report_err}")
                    # Try one more time with a delay
                    try:
                        await asyncio.sleep(1)
                        await asyncio.to_thread(_report_account_status, "failed", flipkart_email if flipkart_email else None)
                        print("[NO_NUMBERS] Retry successful - margin_balance refund reported")
                    except Exception as retry_err:
                        print(f"[ERROR] [NO_NUMBERS] Retry also failed: {retry_err}")
                
                # Emit Socket.IO event to show popup in frontend
                try:
                    backend_url = os.environ.get("BACKEND_URL", "http://localhost:6333")
                    user_id = _get_user_id()
                    if user_id:
                        import requests
                        # Signal backend to emit NO_NUMBERS event
                        requests.post(
                            f"{backend_url}/api/no-numbers-notify",
                            json={"user_id": int(user_id)},
                            timeout=5,
                            headers={"Content-Type": "application/json"}
                        )
                except Exception as notify_err:
                    print(f"[NO_NUMBERS] Failed to notify frontend: {notify_err}")
                
                print("[CLEANUP] Closing browser in 3 seconds...")
                await asyncio.sleep(3)
                return  # Exit worker gracefully

            except AlreadyRegisteredError:
                # This should not happen here - it's handled inside the async with block
                # But if it does, just cancel and retry
                print("[ERROR] AlreadyRegisteredError caught outside async block")

                # Treat this as a failed number for reporting
                if phone_number:
                    await asyncio.to_thread(append_failed_number, phone_number)
                
                # Track failed email for reuse
                if flipkart_email:
                    await asyncio.to_thread(imap.add_failed_email, flipkart_email)
                    # Unreserve email so it can be reused
                    await asyncio.to_thread(imap.unreserve_email, flipkart_email)
                
                # Report account failure to backend for margin_balance refund
                await asyncio.to_thread(_report_account_status, "failed", flipkart_email if flipkart_email else None)

                if RETRY_FAILED:
                    continue  # Retry loop
                else:
                    print("[INFO] Retry disabled - exiting worker")
                    return  # Exit without retrying

            except KeyboardInterrupt:
                # User requested stop - show stopping message
                print("[INFO] Stopping all workers...")
                
                # Track failed email for reuse
                if flipkart_email:
                    await asyncio.to_thread(imap.add_failed_email, flipkart_email)
                    # Unreserve email so it can be reused
                    await asyncio.to_thread(imap.unreserve_email, flipkart_email)
                
                # Report account failure to backend for margin_balance refund (stop button pressed)
                await asyncio.to_thread(_report_account_status, "failed", flipkart_email if flipkart_email else None)
                
                print("[CLEANUP] Closing browser...")
                if browser and not browser_closed:
                    try:
                        await browser.close()
                        browser_closed = True
                    except Exception:
                        pass
                return  # Exit worker gracefully

            except Exception as exc:
                # All other exceptions - cancel number, cleanup, and retry
                exc_msg = str(exc)
                print(f"\n[ERROR] [X] Exception occurred: {exc_msg}")

                # Check if number was canceled or timeout reached - if so, exit immediately without retrying
                if ("canceled" in exc_msg.lower() or "cancel" in exc_msg.lower() or 
                    "timeout" in exc_msg.lower()):
                    if "timeout" in exc_msg.lower():
                        print("[INFO] OTP timeout reached - number canceled and worker stopped")
                    else:
                        print("[INFO] Number was canceled by backend - exiting worker immediately")
                    
                    # Track failed email for reuse
                    if flipkart_email:
                        await asyncio.to_thread(imap.add_failed_email, flipkart_email)
                        # Unreserve email so it can be reused
                        await asyncio.to_thread(imap.unreserve_email, flipkart_email)
                    
                    # Report account failure to backend for margin_balance refund
                    await asyncio.to_thread(_report_account_status, "failed", flipkart_email if flipkart_email else None)
                    
                    print("[CLEANUP] Closing browser...")
                    if browser and not browser_closed:
                        try:
                            await browser.close()
                            browser_closed = True
                        except Exception:
                            pass
                    return  # Exit immediately, don't retry

                # Record failed phone number if we had one
                if phone_number:
                    await asyncio.to_thread(append_failed_number, phone_number)
                
                # Track failed email for reuse
                if flipkart_email:
                    await asyncio.to_thread(imap.add_failed_email, flipkart_email)
                    # Unreserve email so it can be reused
                    await asyncio.to_thread(imap.unreserve_email, flipkart_email)
                
                # Report account failure to backend for margin_balance refund
                await asyncio.to_thread(_report_account_status, "failed", flipkart_email if flipkart_email else None)

                print("[CLEANUP] Closing browser in 3 seconds...")
                await asyncio.sleep(3)
                
                if RETRY_FAILED:
                    continue  # Retry loop
                else:
                    print("[INFO] Retry disabled - exiting worker")
                    return  # Exit without retrying

            finally:
                if not browser_closed and browser:
                    try:
                        await browser.close()
                        browser_closed = True
                    except Exception:
                        pass
    except KeyboardInterrupt:
        # User requested stop - show stopping message
        print("[INFO] Stopping all workers...")
        
        # Track failed email for reuse if we had one
        try:
            if 'flipkart_email' in locals() and flipkart_email:
                await asyncio.to_thread(imap.add_failed_email, flipkart_email)
                # Unreserve email so it can be reused
                await asyncio.to_thread(imap.unreserve_email, flipkart_email)
        except:
            pass
        
        # Report account failure to backend for margin_balance refund (stop button pressed)
        try:
            await asyncio.to_thread(_report_account_status, "failed", flipkart_email if 'flipkart_email' in locals() and flipkart_email else None)
        except:
            pass
        
        if browser and not browser_closed:
            try:
                await browser.close()
                browser_closed = True
            except Exception:
                pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[INFO] Stopping all workers...")
        import sys
        sys.exit(0)