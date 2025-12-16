import asyncio
from playwright.async_api import async_playwright, TimeoutError
import time

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


async def main():
    while True:
        browser = None
        browser_closed = False
        request_id = None
        phone_number = None
        first_otp = None
        flipkart_email = None

        try:
            async with async_playwright() as p:
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
                        raise Exception("❌ Failed to get number from API")
                    request_id, phone_number = number_info
                    print(f"[DEBUG] ✅ Got number: request_id={request_id}, phone={phone_number}")
                except Exception as e:
                    error_msg = str(e)
                    if "NO_NUMBERS" in error_msg or "No numbers available" in error_msg:
                        raise NoNumbersAvailableError("No numbers available right now")
                    raise

                # ---- OPEN SIGNUP ----
                print("[DEBUG] Navigating to Flipkart signup page...")
                await page.goto("https://www.flipkart.com/account/login?signup=true")
                print("[DEBUG] ✅ Page loaded")

                # Fill phone number
                print("[DEBUG] Waiting for phone input field...")
                await page.wait_for_selector("input[type='text'][maxlength='10']")
                print("[DEBUG] ✅ Phone input field found")
                
                phone_input = page.locator("input[type='text'][maxlength='10']")
                print(f"[DEBUG] Filling phone number: {phone_number}")
                await phone_input.fill(phone_number)
                print("[DEBUG] ✅ Phone number filled")
                
                print("[DEBUG] Pressing Enter...")
                await page.keyboard.press("Enter")
                print("[DEBUG] ✅ Enter pressed")

                # ---- CHECK IF ALREADY REGISTERED MESSAGE APPEARS ----
                print("[DEBUG] Checking for 'already registered' message (3s timeout)...")
                try:
                    await page.wait_for_selector("div.LERBMj", timeout=3000)
                    error_text = await page.locator("div.LERBMj").inner_text()
                    print(f"[DEBUG] ⚠️ Error message found: '{error_text}'")

                    if "already registered" in error_text.lower():
                        print("[DEBUG] 🔴 User is ALREADY REGISTERED - triggering recovery flow")
                        raise AlreadyRegisteredError("USER ALREADY REGISTERED")
                    else:
                        print(f"[DEBUG] Error message present but not 'already registered': {error_text}")

                except TimeoutError:
                    print("[DEBUG] ✅ No error message - continuing with signup")
                    pass

                # ---- FETCH SIGNUP OTP ----
                print(f"[DEBUG] Fetching OTP for request_id={request_id}...")
                otp = await asyncio.to_thread(get_otp, request_id)
                if not otp:
                    print("[DEBUG] ⚠️ First OTP fetch failed, requesting new OTP...")
                    otp = await asyncio.to_thread(
                        request_new_otp_until_new, request_id, None, 300.0, 1.0
                    )
                if not otp:
                    raise Exception("❌ Failed to retrieve OTP from API")
                first_otp = otp  # Store the first OTP
                print(f"[DEBUG] ✅ Got OTP: {otp}")

                # Fill OTP
                print("[DEBUG] Waiting for OTP input field...")
                await page.wait_for_selector("input[type='text'][maxlength='6']")
                print("[DEBUG] ✅ OTP input field found")
                
                otp_box = page.locator("input[type='text'][maxlength='6']")
                print(f"[DEBUG] Clicking OTP input field...")
                await otp_box.click()
                print(f"[DEBUG] Typing OTP digit by digit: {otp}")
                for digit in otp:
                    await page.keyboard.type(digit)
                    await asyncio.sleep(0.1)  # Small delay between digits
                print("[DEBUG] ✅ OTP typed digit by digit")
                
                print("[DEBUG] Pressing Enter after OTP...")
                await page.keyboard.press("Enter")
                print("[DEBUG] ✅ Enter pressed after OTP")

                # Check for incorrect OTP message
                print("[DEBUG] Checking for 'OTP is incorrect' message (3s timeout)...")
                try:
                    await page.wait_for_selector("div.LERBMj", timeout=3000)
                    error_text = await page.locator("div.LERBMj").inner_text()
                    if "otp is incorrect" in error_text.lower():
                        print(f"[DEBUG] 🔴 OTP INCORRECT: {error_text}")
                        raise Exception(f"❌ OTP is incorrect: {error_text}")
                    print(f"[DEBUG] ⚠️ Some error after OTP: {error_text}")
                except TimeoutError:
                    print("[DEBUG] ✅ No OTP error - continuing")
                    pass

                print("✅ OTP submitted successfully!")

                # Click Signup button
                print("[DEBUG] Waiting for Signup button...")
                await page.wait_for_selector("button.dSM5Ub.Kv3ekh.KcXDCU")
                print("[DEBUG] ✅ Signup button found")
                
                print("[DEBUG] Clicking Signup button...")
                await page.locator("button.dSM5Ub.Kv3ekh.KcXDCU").click()
                print("✅ Signup button clicked!")

                # ---- GO TO ACCOUNT EDIT PAGE ----
                print("[DEBUG] Navigating to account page...")
                await page.goto("https://www.flipkart.com/account/?rd=0&link=home_account")
                print("[DEBUG] ✅ Account page loaded")

                # Click Email Address Edit
                print("[DEBUG] Waiting for Email Address section...")
                await page.wait_for_selector("div.Rxk9lv:has(span.SLEz3j:text('Email Address'))")
                print("[DEBUG] ✅ Email Address section found")
                
                email_edit_btn = page.locator("div.Rxk9lv", has_text="Email Address").locator("a.GyKGMu")
                print("[DEBUG] Clicking Email Address Edit...")
                await email_edit_btn.click()
                print("✅ Clicked Email Address Edit")

                # ---- ENTER NEW EMAIL ----
                print("[DEBUG] Waiting for email input...")
                await page.wait_for_selector("input[name='email']")
                print("[DEBUG] ✅ Email input found")
                
                email_input = page.locator("input[name='email']")
                print(f"[DEBUG] Filling email: {flipkart_email}")
                await email_input.fill(flipkart_email)
                print("[DEBUG] ✅ Email filled")
                
                print("[DEBUG] Pressing Enter after email...")
                await page.keyboard.press("Enter")
                print("✅ Email filled")

                # ---- ENTER EMAIL OTP ----
                print("[DEBUG] Waiting for OTP input fields...")
                await page.wait_for_selector("input[maxlength='6']")
                print("[DEBUG] ✅ OTP fields found")
                
                email_otp_input = page.locator(f"input[name='{flipkart_email}']")

                # Fetch email OTP from IMAP
                print(f"[DEBUG] Fetching email OTP from IMAP for {flipkart_email}...")
                email_otp = await asyncio.to_thread(imap.otp, flipkart_email)
                if not email_otp:
                    raise Exception("❌ Failed to retrieve email OTP from IMAP")
                print(f"[DEBUG] ✅ Got email OTP: {email_otp}")
                
                print(f"[DEBUG] Clicking email OTP input...")
                await email_otp_input.click()
                print(f"[DEBUG] Typing email OTP digit by digit: {email_otp}")
                for digit in email_otp:
                    await page.keyboard.type(digit)
                    await asyncio.sleep(0.1)  # Small delay between digits
                print("[DEBUG] ✅ Email OTP typed digit by digit")

                # Press TAB to move to phone OTP
                print("[DEBUG] Pressing Tab to move to phone OTP field...")
                await page.keyboard.press("Tab")
                print("[DEBUG] ✅ Tab pressed")

                # ---- ENTER PHONE OTP ----
                print(f"[DEBUG] Fetching phone OTP for request_id={request_id} (must be different from first OTP: {first_otp})...")
                phone_otp = await asyncio.to_thread(request_new_otp_until_new, request_id, first_otp, 300.0, 1.0)
                if not phone_otp:
                    raise Exception("❌ Failed to retrieve phone OTP from API")
                if phone_otp == first_otp:
                    raise Exception(f"❌ Phone OTP is same as first OTP ({first_otp}), this should not happen")
                print(f"[DEBUG] ✅ Got phone OTP: {phone_otp} (different from first: {first_otp})")
                
                print(f"[DEBUG] Clicking phone OTP input...")
                otp_inputs = page.locator("input[maxlength='6']")
                phone_otp_input = otp_inputs.nth(1)
                await phone_otp_input.click()
                print(f"[DEBUG] Typing phone OTP digit by digit: {phone_otp}")
                for digit in phone_otp:
                    await page.keyboard.type(digit)
                    await asyncio.sleep(0.1)  # Small delay between digits
                print("[DEBUG] ✅ Phone OTP typed digit by digit")

                print("✅ Both OTPs entered")

                # ---- CLICK SUBMIT ----
                print("[DEBUG] Waiting for Submit button...")
                await page.wait_for_selector("button.dSM5Ub.xSzOV7")
                print("[DEBUG] ✅ Submit button found")
                
                print("[DEBUG] Clicking Submit button...")
                await page.locator("button.dSM5Ub.xSzOV7").click()
                print("✅ Submit button clicked!")

                print("\n✅ Account creation successful! Closing browser...")
                await asyncio.sleep(3)
                
                # Cancel number after successful completion
                if request_id:
                    try:
                        await asyncio.to_thread(cancel_number, request_id)
                        print("[CLEANUP] ✅ Number cancelled")
                    except Exception as e:
                        print(f"[CLEANUP] ⚠️ Failed to cancel number: {e}")
                
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
                            print(f"[RECOVERY] ✅ Field clicked")
                            
                            print(f"[RECOVERY] Filling phone number: {phone_number}")
                            await phone_field.fill(phone_number)
                            print(f"[RECOVERY] ✅ Phone filled")
                            
                            print(f"[RECOVERY] Pressing Enter...")
                            await page.keyboard.press("Enter")
                            print(f"[RECOVERY] ✅ Enter pressed")

                            # Re-fetch OTP
                            print(f"[RECOVERY] Fetching OTP for request_id={request_id}...")
                            otp = await asyncio.to_thread(get_otp, request_id)
                            if not otp:
                                print("[RECOVERY] ⚠️ First OTP fetch failed, requesting new OTP...")
                                # Use defaults from caller.request_new_otp_until_new
                                otp = await asyncio.to_thread(
                                    request_new_otp_until_new, request_id, None
                                )
                            if not otp:
                                raise Exception("❌ Failed to retrieve OTP during recovery")
                            recovery_first_otp = otp
                            print(f"[RECOVERY] ✅ Got OTP: {otp}")

                            # Directly type OTP digit by digit
                            print(f"[RECOVERY] Typing OTP digit by digit: {otp}")
                            for digit in otp:
                                await page.keyboard.type(digit)
                                await asyncio.sleep(0.1)
                            print(f"[RECOVERY] ✅ OTP typed digit by digit")
                            
                            print(f"[RECOVERY] Pressing Enter...")
                            await page.keyboard.press("Enter")
                            print(f"[RECOVERY] ✅ Enter pressed")
                            time.sleep(4)

                    # Continue from edit page
                    print("[RECOVERY] Navigating to account page...")
                    await page.goto("https://www.flipkart.com/account/?rd=0&link=home_account")
                    print("[RECOVERY] ✅ Account page loaded")
                    
                    print("[RECOVERY] Waiting for Email Address section...")
                    await page.wait_for_selector("div.Rxk9lv:has(span.SLEz3j:text('Email Address'))")
                    print("[RECOVERY] ✅ Email section found")
                    
                    email_edit_btn = page.locator("div.Rxk9lv", has_text="Email Address").locator("a.GyKGMu")
                    print("[RECOVERY] Clicking Email Address Edit...")
                    await email_edit_btn.click()
                    print("[RECOVERY] ✅ Clicked Email Address Edit")

                    print("[RECOVERY] Waiting for email input...")
                    await page.wait_for_selector("input[name='email']")
                    print("[RECOVERY] ✅ Email input found")
                    
                    email_input = page.locator("input[name='email']")
                    print(f"[RECOVERY] Filling email: {flipkart_email}")
                    await email_input.fill(flipkart_email)
                    print("[RECOVERY] ✅ Email filled")
                    
                    print("[RECOVERY] Pressing Enter...")
                    await page.keyboard.press("Enter")
                    print("[RECOVERY] ✅ Enter pressed")

                    print("[RECOVERY] Waiting for OTP fields...")
                    await page.wait_for_selector("input[maxlength='6']")
                    print("[RECOVERY] ✅ OTP fields found")
                    
                    email_otp_input = page.locator(f"input[name='{flipkart_email}']")
                    
                    # Fetch email OTP from IMAP
                    print(f"[RECOVERY] Fetching email OTP from IMAP for {flipkart_email}...")
                    email_otp = await asyncio.to_thread(imap.otp, flipkart_email)
                    if not email_otp:
                        raise Exception("❌ Failed to retrieve email OTP from IMAP during recovery")
                    print(f"[RECOVERY] ✅ Got email OTP: {email_otp}")
                    
                    print(f"[RECOVERY] Clicking email OTP input...")
                    await email_otp_input.click()
                    print(f"[RECOVERY] Typing email OTP digit by digit: {email_otp}")
                    for digit in email_otp:
                        await page.keyboard.type(digit)
                        await asyncio.sleep(0.1)
                    print("[RECOVERY] ✅ Email OTP typed digit by digit")

                    print("[RECOVERY] Pressing Tab...")
                    await page.keyboard.press("Tab")
                    print("[RECOVERY] ✅ Tab pressed")

                    # Fetch phone OTP using request_new_otp_until_new (must be different from first OTP)
                    print(f"[RECOVERY] Fetching phone OTP for request_id={request_id} (must be different from first OTP: {recovery_first_otp})...")
                    # Use defaults from caller.request_new_otp_until_new
                    phone_otp = await asyncio.to_thread(request_new_otp_until_new, request_id, recovery_first_otp)
                    if not phone_otp:
                        raise Exception("❌ Failed to retrieve phone OTP from API during recovery")
                    if phone_otp == recovery_first_otp:
                        raise Exception(f"❌ Phone OTP is same as first OTP ({recovery_first_otp}), this should not happen")
                    print(f"[RECOVERY] ✅ Got phone OTP: {phone_otp} (different from first: {recovery_first_otp})")
                    
                    print(f"[RECOVERY] Clicking phone OTP input...")
                    otp_inputs = page.locator("input[maxlength='6']")
                    phone_otp_input = otp_inputs.nth(1)
                    await phone_otp_input.click()
                    print(f"[RECOVERY] Typing phone OTP digit by digit: {phone_otp}")
                    for digit in phone_otp:
                        await page.keyboard.type(digit)
                        await asyncio.sleep(0.1)
                    print("[RECOVERY] ✅ Phone OTP typed digit by digit")

                    print("[RECOVERY] Waiting for Submit button...")
                    await page.wait_for_selector("button.dSM5Ub.xSzOV7")
                    print("[RECOVERY] ✅ Submit button found")
                    
                    print("[RECOVERY] Clicking Submit...")
                    await page.locator("button.dSM5Ub.xSzOV7").click()
                    print("[RECOVERY] ✅ Recovery submit clicked!")

                    print("\n✅ Recovery completed! Closing browser...")
                    await asyncio.sleep(3)
                    
                    # Cancel number after recovery
                    if request_id:
                        try:
                            await asyncio.to_thread(cancel_number, request_id)
                            print("[CLEANUP] ✅ Number cancelled")
                        except Exception as e:
                            print(f"[CLEANUP] ⚠️ Failed to cancel number: {e}")
                    
                    return  # Success: exit worker loop
                except Exception as recovery_exc:
                    print(f"[RECOVERY] ❌ Recovery failed: {recovery_exc}")
                    raise  # Re-raise to trigger outer exception handler

        except NoNumbersAvailableError:
            print("[ERROR] ❌ NO_NUMBERS: No numbers available right now")
            print("[CLEANUP] Closing browser in 3 seconds...")
            await asyncio.sleep(3)
            return  # Exit worker gracefully

        except AlreadyRegisteredError:
            # This should not happen here - it's handled inside the async with block
            # But if it does, just cancel and retry
            print("[ERROR] AlreadyRegisteredError caught outside async block")
            if request_id:
                try:
                    await asyncio.to_thread(cancel_number, request_id)
                    print("[CLEANUP] ✅ Number cancelled")
                except Exception as e:
                    print(f"[CLEANUP] ⚠️ Failed to cancel number: {e}")
            continue  # Retry loop

        except Exception as exc:
            # All other exceptions - cancel number, cleanup, and retry
            exc_msg = str(exc)
            print(f"\n[ERROR] ❌ Exception occurred: {exc_msg}")

            if request_id:
                try:
                    await asyncio.to_thread(cancel_number, request_id)
                    print("[CLEANUP] ✅ Number cancelled")
                except Exception as e:
                    print(f"[CLEANUP] ⚠️ Failed to cancel number: {e}")

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
