import asyncio
from playwright.async_api import async_playwright, TimeoutError
import time
import os
from pathlib import Path

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
    return os.environ.get("USER_ID") or "0"


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
        cancel_after = max(acquired_at + 120.0, time.time())
        with open(NUMBER_QUEUE_FILE, "a", encoding="utf-8") as f:
            f.write(f"{request_id},{cancel_after}\n")
        print(f"[NUMBER_QUEUE] Enqueued {request_id} for cancellation at {cancel_after}")
    except Exception as e:
        print(f"[NUMBER_QUEUE] Failed to enqueue {request_id}: {e}")


def configure_caller_from_env() -> None:
    """
    Configure caller.py API settings from environment variables passed
    by the backend (per-user API key, base URL, service, operator, country).
    """
    api_key = (os.environ.get("API_KEY") or os.environ.get("SMS_API_KEY") or "").strip()
    base_url = os.environ.get("API_BASE_URL") or ""
    service = os.environ.get("API_SERVICE") or ""
    operator = os.environ.get("API_OPERATOR") or ""
    country = os.environ.get("API_COUNTRY") or ""

    if api_key:
        caller.API_KEY = api_key
    if base_url:
        caller.BASE_URL = base_url
    if service:
        caller.SERVICE = service
    if operator:
        caller.OPERATOR = operator
    if country:
        caller.COUNTRY = country


USE_USED_ACCOUNT = (os.environ.get("USE_USED_ACCOUNT") or "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


async def main():
    # Ensure SMS API calls inside this worker use the same credentials/settings
    # as the backend used to compute balance/capacity.
    configure_caller_from_env()
    while True:
        browser = None
        browser_closed = False
        request_id = None
        phone_number = None
        first_otp = None
        flipkart_email = None
        number_acquired_at = None

        try:
            async with async_playwright() as p:
                try:
                    print("[DEBUG] Launching browser...")
                    browser = await p.chromium.launch(headless=False)
                    context = await browser.new_context()
                    page = await context.new_page()
                    # ---- GENERATE EMAIL ----
                    flipkart_email = await asyncio.to_thread(imap.generate_flipkart_email)
                    print(f"[DEBUG] Generated Flipkart email: {flipkart_email}")

                    # ---- GET NUMBER FROM API ----
                    print("[DEBUG] Fetching number from API...")
                    try:
                        number_info = await asyncio.to_thread(get_number)
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
                    print("[DEBUG] [OK] Page loaded")

                    # Fill phone number
                    print("[DEBUG] Waiting for phone input field...")
                    await page.wait_for_selector("input[type='text'][maxlength='10']")
                    print("[DEBUG] [OK] Phone input field found")
                    
                    phone_input = page.locator("input[type='text'][maxlength='10']")
                    print(f"[DEBUG] Filling phone number: {phone_number}")
                    await phone_input.fill(phone_number)
                    print("[DEBUG] [OK] Phone number filled")
                    
                    print("[DEBUG] Pressing Enter...")
                    await page.keyboard.press("Enter")
                    print("[DEBUG] [OK] Enter pressed")

                    # ---- CHECK IF ALREADY REGISTERED MESSAGE APPEARS ----
                    print("[DEBUG] Checking for 'already registered' message (3s timeout)...")
                    try:
                        await page.wait_for_selector("div.LERBMj", timeout=3000)
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
                    print(f"[DEBUG] Fetching OTP for request_id={request_id}...")
                    otp = await asyncio.to_thread(get_otp, request_id)
                    if not otp:
                        print("[DEBUG] [WARN] First OTP fetch failed, requesting new OTP...")
                        otp = await asyncio.to_thread(
                            request_new_otp_until_new, request_id, None, 120.0, 1.0
                        )
                    if not otp:
                        raise Exception("[X] Failed to retrieve OTP from API")
                    first_otp = otp  # Store the first OTP
                    print(f"[DEBUG] [OK] Got OTP: {otp}")

                    # Fill OTP
                    print("[DEBUG] Waiting for OTP input field...")
                    await page.wait_for_selector("input[type='text'][maxlength='6']")
                    print("[DEBUG] [OK] OTP input field found")
                    
                    otp_box = page.locator("input[type='text'][maxlength='6']")
                    print(f"[DEBUG] Clicking OTP input field...")
                    await otp_box.click()
                    print(f"[DEBUG] Typing OTP digit by digit: {otp}")
                    for digit in otp:
                        await page.keyboard.type(digit)
                        await asyncio.sleep(0.1)  # Small delay between digits
                    print("[DEBUG] [OK] OTP typed digit by digit")
                    
                    print("[DEBUG] Pressing Enter after OTP...")
                    await page.keyboard.press("Enter")
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

                    # ---- GO TO ACCOUNT EDIT PAGE ----
                    print("[DEBUG] Navigating to account page...")
                    await page.goto("https://www.flipkart.com/account/?rd=0&link=home_account")
                    print("[DEBUG] [OK] Account page loaded")

                    # Click Email Address Edit
                    print("[DEBUG] Waiting for Email Address section...")
                    await page.wait_for_selector("div.Rxk9lv:has(span.SLEz3j:text('Email Address'))")
                    print("[DEBUG] [OK] Email Address section found")
                    
                    email_edit_btn = page.locator("div.Rxk9lv", has_text="Email Address").locator("a.GyKGMu")
                    print("[DEBUG] Clicking Email Address Edit...")
                    await email_edit_btn.click()
                    print("[OK] Clicked Email Address Edit")

                    # ---- ENTER NEW EMAIL ----
                    print("[DEBUG] Waiting for email input...")
                    await page.wait_for_selector("input[name='email']")
                    print("[DEBUG] [OK] Email input found")
                    
                    email_input = page.locator("input[name='email']")
                    print(f"[DEBUG] Filling email: {flipkart_email}")
                    await email_input.fill(flipkart_email)
                    print("[DEBUG] [OK] Email filled")
                    
                    print("[DEBUG] Pressing Enter after email...")
                    await page.keyboard.press("Enter")
                    print("[OK] Email filled")

                    # ---- ENTER EMAIL OTP ----
                    print("[DEBUG] Waiting for OTP input fields...")
                    await page.wait_for_selector("input[maxlength='6']")
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
                    print(f"[DEBUG] Typing email OTP digit by digit: {email_otp}")
                    for digit in email_otp:
                        await page.keyboard.type(digit)
                        await asyncio.sleep(0.1)  # Small delay between digits
                    print("[DEBUG] [OK] Email OTP typed digit by digit")

                    # Press TAB to move to phone OTP
                    print("[DEBUG] Pressing Tab to move to phone OTP field...")
                    await page.keyboard.press("Tab")
                    print("[DEBUG] [OK] Tab pressed")

                    # ---- ENTER PHONE OTP ----
                    print(f"[DEBUG] Fetching phone OTP for request_id={request_id} (must be different from first OTP: {first_otp})...")
                    phone_otp = await asyncio.to_thread(request_new_otp_until_new, request_id, first_otp, 300.0, 1.0)
                    if not phone_otp:
                        raise Exception("[X] Failed to retrieve phone OTP from API")
                    if phone_otp == first_otp:
                        raise Exception(f"[X] Phone OTP is same as first OTP ({first_otp}), this should not happen")
                    print(f"[DEBUG] [OK] Got phone OTP: {phone_otp} (different from first: {first_otp})")
                    
                    print(f"[DEBUG] Clicking phone OTP input...")
                    otp_inputs = page.locator("input[maxlength='6']")
                    phone_otp_input = otp_inputs.nth(1)
                    await phone_otp_input.click()
                    print(f"[DEBUG] Typing phone OTP digit by digit: {phone_otp}")
                    for digit in phone_otp:
                        await page.keyboard.type(digit)
                        await asyncio.sleep(0.1)  # Small delay between digits
                    print("[DEBUG] [OK] Phone OTP typed digit by digit")

                    print("[OK] Both OTPs entered")

                    # ---- CLICK SUBMIT ----
                    print("[DEBUG] Waiting for Submit button...")
                    await page.wait_for_selector("button.dSM5Ub.xSzOV7")
                    print("[DEBUG] [OK] Submit button found")
                    
                    print("[DEBUG] Clicking Submit button...")
                    await page.locator("button.dSM5Ub.xSzOV7").click()
                    print("[OK] Submit button clicked!")

                    print("\n[OK] Account creation successful! Closing browser...")
                    # Record successful email in local report file
                    if flipkart_email:
                        await asyncio.to_thread(append_used_email, flipkart_email)
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
                                print(f"[RECOVERY] [OK] Field clicked")
                                
                                print(f"[RECOVERY] Filling phone number: {phone_number}")
                                await phone_field.fill(phone_number)
                                print(f"[RECOVERY] [OK] Phone filled")
                                
                                print(f"[RECOVERY] Pressing Enter...")
                                await page.keyboard.press("Enter")
                                print(f"[RECOVERY] [OK] Enter pressed")

                                # Re-fetch OTP
                                print(f"[RECOVERY] Fetching OTP for request_id={request_id}...")
                                otp = await asyncio.to_thread(get_otp, request_id)
                                if not otp:
                                    raise Exception("[X] Failed to retrieve OTP during recovery")
                                recovery_first_otp = otp
                                print(f"[RECOVERY] [OK] Got OTP: {otp}")

                                # Directly type OTP digit by digit
                                print(f"[RECOVERY] Typing OTP digit by digit: {otp}")
                                for digit in otp:
                                    await page.keyboard.type(digit)
                                    await asyncio.sleep(0.1)
                                print(f"[RECOVERY] [OK] OTP typed digit by digit")
                                time.sleep(1)
                                print(f"[RECOVERY] Pressing Enter...")
                                await page.keyboard.press("Enter")
                                print(f"[RECOVERY] [OK] Enter pressed")
                                time.sleep(2)

                        # Continue from edit page
                        print("[RECOVERY] Navigating to account page...")
                        await page.goto("https://www.flipkart.com/account/?rd=0&link=home_account")
                        print("[RECOVERY] [OK] Account page loaded")
                        
                        print("[RECOVERY] Waiting for Email Address section...")
                        await page.wait_for_selector("div.Rxk9lv:has(span.SLEz3j:text('Email Address'))")
                        print("[RECOVERY] [OK] Email section found")
                        
                        email_edit_btn = page.locator("div.Rxk9lv", has_text="Email Address").locator("a.GyKGMu")
                        print("[RECOVERY] Clicking Email Address Edit...")
                        await email_edit_btn.click()
                        print("[RECOVERY] [OK] Clicked Email Address Edit")

                        print("[RECOVERY] Waiting for email input...")
                        await page.wait_for_selector("input[name='email']")
                        print("[RECOVERY] [OK] Email input found")
                        
                        email_input = page.locator("input[name='email']")
                        print(f"[RECOVERY] Filling email: {flipkart_email}")
                        await email_input.fill(flipkart_email)
                        print("[RECOVERY] [OK] Email filled")
                        
                        print("[RECOVERY] Pressing Enter...")
                        await page.keyboard.press("Enter")
                        print("[RECOVERY] [OK] Enter pressed")

                        print("[RECOVERY] Waiting for OTP fields...")
                        await page.wait_for_selector("input[maxlength='6']")
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
                        print(f"[RECOVERY] Typing email OTP digit by digit: {email_otp}")
                        for digit in email_otp:
                            await page.keyboard.type(digit)
                            await asyncio.sleep(0.1)
                        print("[RECOVERY] [OK] Email OTP typed digit by digit")

                        print("[RECOVERY] Pressing Tab...")
                        await page.keyboard.press("Tab")
                        print("[RECOVERY] [OK] Tab pressed")

                        # Fetch phone OTP using request_new_otp_until_new (must be different from first OTP)
                        print(f"[RECOVERY] Fetching phone OTP for request_id={request_id} (must be different from first OTP: {recovery_first_otp})...")
                        # Use defaults from caller.request_new_otp_until_new
                        phone_otp = await asyncio.to_thread(request_new_otp_until_new, request_id, recovery_first_otp)
                        if not phone_otp:
                            raise Exception("[X] Failed to retrieve phone OTP from API during recovery")
                        if phone_otp == recovery_first_otp:
                            raise Exception(f"[X] Phone OTP is same as first OTP ({recovery_first_otp}), this should not happen")
                        print(f"[RECOVERY] [OK] Got phone OTP: {phone_otp} (different from first: {recovery_first_otp})")
                        
                        print(f"[RECOVERY] Clicking phone OTP input...")
                        otp_inputs = page.locator("input[maxlength='6']")
                        phone_otp_input = otp_inputs.nth(1)
                        await phone_otp_input.click()
                        print(f"[RECOVERY] Typing phone OTP digit by digit: {phone_otp}")
                        for digit in phone_otp:
                            await page.keyboard.type(digit)
                            await asyncio.sleep(0.1)
                        print("[RECOVERY] [OK] Phone OTP typed digit by digit")

                        print("[RECOVERY] Waiting for Submit button...")
                        await page.wait_for_selector("button.dSM5Ub.xSzOV7")
                        print("[RECOVERY] [OK] Submit button found")
                        
                        print("[RECOVERY] Clicking Submit...")
                        await page.locator("button.dSM5Ub.xSzOV7").click()
                        print("[RECOVERY] [OK] Recovery submit clicked!")

                        print("\n[OK] Recovery completed! Closing browser...")

                        # Record successful email in local report file
                        if flipkart_email:
                            await asyncio.to_thread(append_used_email, flipkart_email)

                        await asyncio.sleep(3)

                        return  # Success: exit worker loop
                    except Exception as recovery_exc:
                        print(f"[RECOVERY] [X] Recovery failed: {recovery_exc}")
                        raise  # Re-raise to trigger outer exception handler

        except NoNumbersAvailableError:
            print("[ERROR] [X] NO_NUMBERS: No numbers available right now")
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

            continue  # Retry loop

        except Exception as exc:
            # All other exceptions - cancel number, cleanup, and retry
            exc_msg = str(exc)
            print(f"\n[ERROR] [X] Exception occurred: {exc_msg}")

            # Record failed phone number if we had one
            if phone_number:
                await asyncio.to_thread(append_failed_number, phone_number)

            print("[CLEANUP] Closing browser in 3 seconds...")
            await asyncio.sleep(3)
            continue  # Retry loop

        finally:
            if not browser_closed and browser:
                try:
                    await browser.close()
                    browser_closed = True
                except Exception:
                    pass


asyncio.run(main())