#!/usr/bin/env python3
"""
imap.py — Safe Flipkart OTP Extractor (Zoho Mail, single-use)
Now loads IMAP credentials dynamically from imap_config.json
"""

import imaplib
import email
import re
import json
import os
import time
from email.header import decode_header
from datetime import datetime, timedelta, timezone


# ==========================================================
# JSON CONFIG PATH (Works for Python + Nuitka EXE)
# ==========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.abspath(os.path.join(BASE_DIR, "imap_config.json"))


# ==========================================================
# Default IMAP Config
# ==========================================================
DEFAULT_CONFIG = {
    "host": "imappro.zoho.in",
    "port": 993,
    "email": "work@clyro.sbs",
    "password": "7Kak6MZyimzB",
    "mailbox": "Notification",
}


# ==========================================================
# Load Configuration
# ==========================================================
def load_imap_config():
    """
    Loads IMAP config from JSON.
    Auto-creates file if missing.
    """

    # Create file if missing
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)

    try:
        with open(CONFIG_PATH, "r") as f:
            data = json.load(f)

            # Ensure all keys exist (auto-repair)
            updated = False
            for key in DEFAULT_CONFIG:
                if key not in data:
                    data[key] = DEFAULT_CONFIG[key]
                    updated = True

            if updated:
                with open(CONFIG_PATH, "w") as f:
                    json.dump(data, f, indent=4)

            return data
    except:
        # Reset corrupted config
        with open(CONFIG_PATH, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG.copy()


# ==========================================================
# Other Constants
# ==========================================================
SUBJECT_TOKEN = "Flipkart Account -"
EXPECTED_SENDER = "noreply@rmo.flipkart.com"
OTP_RE = re.compile(r"\b(\d{4,8})\b")
SEARCH_SINCE_MINUTES = 20


# ==========================================================
# Generate tagged email
# ==========================================================
def generate_flipkart_email() -> str:
    """
    Create a unique plus-tagged email using the configured base address.
    Example: name+fk1700000000000@example.com
    """
    cfg = load_imap_config()
    base_email = cfg.get("email", "")
    if "@" not in base_email:
        raise ValueError("Configured email is invalid or missing '@'")
    local, domain = base_email.split("@", 1)
    tag = int(time.time() * 1000)
    return f"{local}+fk{tag}@{domain}"


# ==========================================================
# Helper: Decode Header
# ==========================================================
def decode_hdr(hdr):
    """Decode MIME header safely."""
    if not hdr:
        return ""
    parts = decode_header(hdr)
    return "".join(
        p.decode(enc or "utf-8", errors="ignore") if isinstance(p, bytes) else p
        for p, enc in parts
    )


# ==========================================================
# Fetch OTP
# ==========================================================
def otp(target_email, timeout_seconds: float = 180.0, poll_interval: float = 5.0):
    """
    Poll for the latest Flipkart OTP for the given Delivered-To email.
    Ensures each OTP mail is used once.
    """

    cfg = load_imap_config()

    IMAP_HOST = cfg["host"]
    IMAP_PORT = cfg["port"]
    LOGIN_EMAIL = cfg["email"]
    PASSWORD = cfg["password"]
    MAILBOX = cfg["mailbox"]

    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        since_dt = datetime.now(timezone.utc) - timedelta(minutes=SEARCH_SINCE_MINUTES)
        since_str = since_dt.strftime("%d-%b-%Y")

        print(f"[IMAP] Connecting to IMAP server {IMAP_HOST} for {target_email}...")

        try:
            mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
            mail.login(LOGIN_EMAIL, PASSWORD)
            mail.select(f'"{MAILBOX}"')
        except Exception as e:
            print(f"[IMAP] Login/select failed: {e}")
            return None

        # Only search unseen messages first (do not quote the date)
        typ, data = mail.search(None, "UNSEEN", "SINCE", since_str)

        if typ != "OK" or not data or not data[0]:
            print(f"[IMAP] No unseen mails, checking all recent mails...")
            typ, data = mail.search(None, "SINCE", since_str)

        mail_ids = data[0].split() if data and data[0] else []
        if not mail_ids:
            mail.logout()
            time.sleep(poll_interval)
            continue

        for msg_id in reversed(mail_ids[-10:]):  # last 10 mails
            typ, msg_data = mail.fetch(msg_id, "(RFC822)")
            if typ != "OK" or not msg_data:
                continue

            msg = email.message_from_bytes(msg_data[0][1])
            subj = decode_hdr(msg.get("Subject", ""))
            from_email = msg.get("From", "").lower()
            to_email = (
                msg.get("Delivered-To") or msg.get("To") or msg.get("X-Envelope-To") or ""
            ).lower()

            # Strong filtering
            if SUBJECT_TOKEN.lower() not in subj.lower():
                continue
            if EXPECTED_SENDER not in from_email:
                continue
            if target_email.lower() not in to_email:
                continue

            # Try to extract OTP
            otp_match = OTP_RE.search(subj)
            if not otp_match:
                # fallback: body scan
                body = None
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            try:
                                body = part.get_payload(decode=True).decode(errors="ignore")
                                break
                            except:
                                pass
                else:
                    try:
                        body = msg.get_payload(decode=True).decode(errors="ignore")
                    except:
                        pass

                if body:
                    otp_match = OTP_RE.search(body)

            if otp_match:
                otp_val = otp_match.group(1)

                # Mark as used
                mail.store(msg_id, "+FLAGS", "\\Seen")
                mail.store(msg_id, "+FLAGS", "\\Deleted")
                mail.expunge()

                print(f"[IMAP] OTP for {target_email}: {otp_val}")
                mail.logout()
                return otp_val

        mail.logout()
        time.sleep(poll_interval)

    print("[IMAP] OTP not found within timeout.")
    return None

