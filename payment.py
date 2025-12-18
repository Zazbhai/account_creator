import requests
import json

def payment_checker(utr):

    # ---- CONFIG (YOUR VALUES ARE CORRECT) ----
    MERCHANT_ID = 60987133
    ACCESS_TOKEN = "a2581a8d9e8c4bfa8580204e872c1119"

    # If you get 401/403, try adding session cookies (copy from browser after login to dashboard)
    # Otherwise, leave empty or remove the Cookie line
    SESSION_COOKIE = "eyJpdiI6IlNSYTFQZENDMEhqV0pnOUxGRjMwb3c9PSIsInZhbHVlIjoiRTJPSWNoaGhJeGxuXC8xK3ZJZEhPZlJ1MTNpZU8xUjc0TEtOV1lkR3NTVWFMMzVzSEhycVo3Vm04eFp2c05IeDZnTHZvclEwNTEzbmQzd29uOVIzcjFQQzNJOFBOUlYxUjQwMTRIYllFZHZud05NRXoxaitIUldERGZNWjRpbGJwIiwibWFjIjoiOGRhYzNjNjhmYjg0NTQyMTJiZDNkNzkyZTY1ZWY4MzdkZDUwODlkMTEyNDljODNlYzQ3ZjYyY2I1ZDBjNWFjMiJ9"  # e.g., "JSESSIONID=xxx; bp_session=yyy"

    UTR_TO_CHECK = str(utr)  # Replace with the actual UTR you want to verify

    # ---- FIXED: Correct URL and authentication ----
    URL = "https://payments-tesseract.bharatpe.in/api/v1/merchant/transactions"

    params = {
        "module": "PAYMENT_QR",
        "merchantId": MERCHANT_ID
    }

    headers = {
        "token": ACCESS_TOKEN,          # ← This is the correct header (not "accessToken")
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://dashboard.bharatpe.in/"
    }

    # Only add Cookie if you have valid session cookies
    if SESSION_COOKIE:
        headers["Cookie"] = SESSION_COOKIE

    # ---- Make request ----
    try:
        resp = requests.get(URL, params=params, headers=headers, timeout=15)
        resp.raise_for_status()  # Raises error if 4xx/5xx
    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP Error: {resp.status_code} - {resp.text}")
        return False, 0
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        return False, 0

    # ---- Parse response ----
    try:
        data = resp.json()
    except json.JSONDecodeError:
        print("❌ Invalid JSON response")
        print(resp.text)
        return False, 0

    transactions = data.get("data", {}).get("transactions", [])

    found_txn = None
    for txn in transactions:
        # bankReferenceNo is usually a string, so compare as string
        if str(txn.get("bankReferenceNo")) == UTR_TO_CHECK:
            found_txn = txn
            break

    if found_txn:
        
        amount = found_txn.get("amount", "N/A")
        status = found_txn.get("status", "N/A")
        payer_name = found_txn.get("payerName", "N/A")
        payer_handle = found_txn.get("payerHandle", "N/A")
        txn_time = found_txn.get("transactionTime", "N/A")

        print("✅ Payment FOUND and CONFIRMED!")
        print(f"Amount       : ₹{amount}")
        print(f"Status       : {status}")
        print(f"Payer Name   : {payer_name}")
        print(f"Payer UPI    : {payer_handle}")
        print(f"Time         : {txn_time}")
        print(f"UTR / RRN    : {UTR_TO_CHECK}")
        return True, amount
    else:
        print("❌ Payment NOT FOUND with this UTR")
        print(f"(Checked {len(transactions)} recent transactions)")
        return False, 0

if __name__ == "__main__":
    bools, amount = payment_checker(3939473167972)
    print(bools, amount)