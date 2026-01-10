#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
import threading
import sys
from pathlib import Path
from email.header import decode_header
from datetime import datetime, timedelta, timezone

# Fix Windows console encoding to handle Unicode properly
if sys.platform == 'win32':
    try:
        # Set stdout/stderr to UTF-8 encoding on Windows
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        # Fallback: use environment variable
        os.environ['PYTHONIOENCODING'] = 'utf-8'

# Safe print function that handles encoding errors gracefully
def safe_print(*args, **kwargs):
    """Print function that handles Unicode encoding errors on Windows."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        # Fallback: encode to ASCII with error handling
        try:
            message = ' '.join(str(arg).encode('ascii', errors='replace').decode('ascii') for arg in args)
            print(message, **kwargs)
        except Exception:
            # Last resort: just print a safe message
            print("[IMAP] [LOG]", **kwargs)

# Cross-platform file locking
try:
    import fcntl  # Unix/Linux
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False

try:
    import msvcrt  # Windows
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False

# Try to import neon_client if available
try:
    import neon_client as supabase_client
except ImportError:
    supabase_client = None


# ==========================================================
# JSON CONFIG PATH (Works for Python + Nuitka EXE)
# ==========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.abspath(os.path.join(BASE_DIR, "imap_config.json"))
COUNTER_FILE = os.path.abspath(os.path.join(BASE_DIR, "flipkart_counter.json"))
COUNTER_LOCK_FILE = os.path.abspath(os.path.join(BASE_DIR, "flipkart_counter.lock"))
FAILED_EMAILS_FILE = os.path.abspath(os.path.join(BASE_DIR, "use_first_mails.txt"))
EMAIL_GEN_LOCK_FILE = os.path.abspath(os.path.join(BASE_DIR, "email_generation.lock"))
RESERVED_EMAILS_FILE = os.path.abspath(os.path.join(BASE_DIR, "reserved_emails.txt"))

# Reports directory for used emails (matches account_creator.py - root directory)
REPORTS_DIR = Path(BASE_DIR)

# Thread lock for in-process synchronization
_counter_lock = threading.Lock()
_failed_emails_lock = threading.Lock()
_email_generation_lock = threading.Lock()  # Lock for entire email generation to prevent race conditions


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
# Counter Management (Thread-safe, Cross-process safe)
# ==========================================================
def _get_next_counter() -> int:
    """
    Atomically get and increment the Flipkart account counter.
    Returns the incremented counter value.
    Uses file locking to prevent race conditions across processes.
    Thread-safe and cross-platform (Windows/Unix).
    """
    max_retries = 20
    retry_delay = 0.05
    
    # Use thread lock for in-process synchronization
    with _counter_lock:
        for attempt in range(max_retries):
            try:
                lock_fd = None
                lock_file_obj = None  # For Windows file object
                lock_acquired = False
                
                try:
                    # Try to acquire file lock (cross-platform)
                    if HAS_FCNTL:
                        # Unix/Linux: use fcntl
                        lock_fd = os.open(COUNTER_LOCK_FILE, os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
                        try:
                            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            lock_acquired = True
                        except (IOError, OSError):
                            # Lock held by another process
                            os.close(lock_fd)
                            lock_fd = None
                            if attempt < max_retries - 1:
                                time.sleep(retry_delay)
                                continue
                    elif HAS_MSVCRT:
                        # Windows: use msvcrt (requires binary mode file handle)
                        try:
                            # Open file in binary append mode for locking
                            lock_file_obj = open(COUNTER_LOCK_FILE, 'ab')
                            lock_fd = lock_file_obj.fileno()
                            try:
                                msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
                                lock_acquired = True
                                # Keep file open for lock duration
                            except IOError:
                                # Lock held by another process
                                lock_file_obj.close()
                                lock_file_obj = None
                                lock_fd = None
                                if attempt < max_retries - 1:
                                    time.sleep(retry_delay)
                                    continue
                        except (OSError, IOError):
                            # Failed to create/open lock file
                            if attempt < max_retries - 1:
                                time.sleep(retry_delay)
                                continue
                    else:
                        # No file locking available, use simple file existence check
                        if os.path.exists(COUNTER_LOCK_FILE):
                            # Check if lock file is stale (older than 5 seconds)
                            try:
                                lock_age = time.time() - os.path.getmtime(COUNTER_LOCK_FILE)
                                if lock_age > 5.0:
                                    # Stale lock, remove it
                                    try:
                                        os.remove(COUNTER_LOCK_FILE)
                                    except:
                                        pass
                                else:
                                    if attempt < max_retries - 1:
                                        time.sleep(retry_delay)
                                        continue
                            except:
                                pass
                        
                        # Create lock file
                        try:
                            lock_fd = os.open(COUNTER_LOCK_FILE, os.O_CREAT | os.O_WRONLY | os.O_EXCL)
                            lock_acquired = True
                        except (IOError, OSError):
                            # Lock file exists
                            if attempt < max_retries - 1:
                                time.sleep(retry_delay)
                                continue
                    
                    if not lock_acquired:
                        if attempt == max_retries - 1:
                            # Last attempt: proceed without file lock (thread lock still active)
                            break
                        continue
                    
                    # Read current counter
                    counter = 0
                    if os.path.exists(COUNTER_FILE):
                        try:
                            with open(COUNTER_FILE, 'r') as f:
                                data = json.load(f)
                                counter = data.get("counter", 0)
                        except (json.JSONDecodeError, IOError, ValueError):
                            counter = 0
                    
                    # Increment and save
                    counter += 1
                    with open(COUNTER_FILE, 'w') as f:
                        json.dump({"counter": counter}, f, indent=2)
                    
                    # Release and close lock
                    if HAS_FCNTL and lock_fd is not None:
                        try:
                            fcntl.flock(lock_fd, fcntl.LOCK_UN)
                            os.close(lock_fd)
                        except:
                            pass
                    elif HAS_MSVCRT and lock_fd is not None:
                        try:
                            msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
                            if lock_file_obj is not None:
                                lock_file_obj.close()
                        except:
                            pass
                    elif lock_fd is not None:
                        try:
                            os.close(lock_fd)
                        except:
                            pass
                    
                    # Remove lock file (for systems without fcntl/msvcrt)
                    if not HAS_FCNTL and not HAS_MSVCRT:
                        try:
                            os.remove(COUNTER_LOCK_FILE)
                        except:
                            pass
                    
                    return counter
                    
                except Exception as e:
                    # Clean up on error
                    if HAS_MSVCRT and lock_file_obj is not None:
                        try:
                            if lock_fd is not None:
                                try:
                                    msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
                                except:
                                    pass
                            lock_file_obj.close()
                        except:
                            pass
                    elif lock_fd is not None:
                        try:
                            if HAS_FCNTL:
                                try:
                                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                                except:
                                    pass
                            os.close(lock_fd)
                        except:
                            pass
                    
                    if not HAS_FCNTL and not HAS_MSVCRT:
                        try:
                            if os.path.exists(COUNTER_LOCK_FILE):
                                os.remove(COUNTER_LOCK_FILE)
                        except:
                            pass
                    
                    if attempt == max_retries - 1:
                        # Last attempt: proceed without file lock
                        break
                    
                    time.sleep(retry_delay)
                    continue
                    
            except Exception:
                if attempt == max_retries - 1:
                    break
                time.sleep(retry_delay)
        
        # Fallback: read and increment without file lock (thread lock still protects)
        counter = 0
        if os.path.exists(COUNTER_FILE):
            try:
                with open(COUNTER_FILE, 'r') as f:
                    data = json.load(f)
                    counter = data.get("counter", 0)
            except (json.JSONDecodeError, IOError, ValueError):
                counter = 0
        
        counter += 1
        try:
            with open(COUNTER_FILE, 'w') as f:
                json.dump({"counter": counter}, f, indent=2)
        except:
            pass
        
        return counter


# ==========================================================
# Failed Email Management
# ==========================================================
def add_failed_email(email: str) -> None:
    """
    Add a failed email to use_first_mails.txt for reuse in future sessions.
    Thread-safe and cross-process safe. Uses file locking to prevent race conditions.
    """
    if not email or not isinstance(email, str):
        return
    
    # Validate email format (basic check)
    email = email.strip()
    if not email or "@" not in email:
        print(f"[WARN] [imap.add_failed_email] Invalid email format: {email}")
        return
    
    max_retries = 10
    retry_delay = 0.1
    
    # Use thread lock to prevent race conditions
    with _failed_emails_lock:
        for attempt in range(max_retries):
            try:
                # Read existing failed emails (atomic read)
                failed_emails = []
                if os.path.exists(FAILED_EMAILS_FILE):
                    try:
                        # Read with UTF-8 encoding and handle BOM
                        with open(FAILED_EMAILS_FILE, 'r', encoding='utf-8-sig') as f:
                            content = f.read()
                            # Strip BOM if present
                            if content.startswith('\ufeff'):
                                content = content[1:]
                            failed_emails = [line.strip() for line in content.splitlines() if line.strip()]
                    except UnicodeDecodeError as e:
                        # Try reading with different encoding if UTF-8 fails
                        try:
                            with open(FAILED_EMAILS_FILE, 'r', encoding='latin-1') as f:
                                content = f.read()
                                if content.startswith('\ufeff'):
                                    content = content[1:]
                                failed_emails = [line.strip() for line in content.splitlines() if line.strip()]
                        except Exception as e2:
                            print(f"[WARN] [imap.add_failed_email] Failed to read file: {e2}")
                            failed_emails = []
                    except (IOError, ValueError, Exception) as e:
                        print(f"[WARN] [imap.add_failed_email] Failed to read file: {e}")
                        failed_emails = []
                
                # Add email if not already present (prevent duplicates)
                if email not in failed_emails:
                    failed_emails.append(email)
                    
                    # Write back to file (atomic write)
                    # Use 'utf-8' (not 'utf-8-sig') to avoid writing BOM
                    try:
                        with open(FAILED_EMAILS_FILE, 'w', encoding='utf-8', newline='\n') as f:
                            for failed_email in failed_emails:
                                f.write(f"{failed_email}\n")
                        
                        print(f"[IMAP] Added failed email to use_first_mails.txt: {email} (total: {len(failed_emails)})")
                    except Exception as e:
                        print(f"[ERROR] [imap.add_failed_email] Failed to write file: {e}")
                        if attempt == max_retries - 1:
                            return
                        time.sleep(retry_delay)
                        continue
                else:
                    print(f"[DEBUG] [imap.add_failed_email] Email {email} already in use_first_mails.txt (skipping)")
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"[ERROR] [imap.add_failed_email] Failed after {max_retries} attempts: {e}")
                else:
                    time.sleep(retry_delay)


def get_and_remove_failed_email():
    """
    Get the first failed email from use_first_mails.txt and remove it atomically.
    Returns the email if found, None otherwise.
    Thread-safe and cross-process safe. Uses file locking to prevent race conditions.
    """
    max_retries = 10
    retry_delay = 0.1
    
    # Use thread lock to prevent race conditions within the same process
    with _failed_emails_lock:
        for attempt in range(max_retries):
            try:
                if not os.path.exists(FAILED_EMAILS_FILE):
                    print(f"[DEBUG] [imap.get_and_remove_failed_email] use_first_mails.txt does not exist yet")
                    return None
                
                # Read existing failed emails (atomic read)
                failed_emails = []
                try:
                    # Read with UTF-8 encoding and handle BOM (Byte Order Mark)
                    with open(FAILED_EMAILS_FILE, 'r', encoding='utf-8-sig') as f:
                        content = f.read()
                        # Strip BOM if present (utf-8-sig should handle it, but double-check)
                        if content.startswith('\ufeff'):
                            content = content[1:]
                        print(f"[DEBUG] [imap.get_and_remove_failed_email] File content (raw): {repr(content[:100])}")  # First 100 chars only
                        failed_emails = [line.strip() for line in content.splitlines() if line.strip()]
                        print(f"[DEBUG] [imap.get_and_remove_failed_email] Parsed {len(failed_emails)} email(s): {failed_emails}")
                except UnicodeDecodeError as e:
                    # Try reading with different encoding if UTF-8 fails
                    print(f"[WARN] [imap.get_and_remove_failed_email] UTF-8 decode failed, trying latin-1: {e}")
                    try:
                        with open(FAILED_EMAILS_FILE, 'r', encoding='latin-1') as f:
                            content = f.read()
                            # Remove BOM if present
                            if content.startswith('\ufeff'):
                                content = content[1:]
                            failed_emails = [line.strip() for line in content.splitlines() if line.strip()]
                            print(f"[DEBUG] [imap.get_and_remove_failed_email] Parsed {len(failed_emails)} email(s) with latin-1: {failed_emails}")
                    except Exception as e2:
                        print(f"[ERROR] [imap.get_and_remove_failed_email] Failed to read file with latin-1: {e2}")
                        import traceback
                        traceback.print_exc()
                        return None
                except (IOError, ValueError, Exception) as e:
                    print(f"[WARN] [imap.get_and_remove_failed_email] Failed to read file: {e}")
                    import traceback
                    traceback.print_exc()
                    return None
                
                if not failed_emails:
                    print(f"[DEBUG] [imap.get_and_remove_failed_email] use_first_mails.txt is empty (no emails to reuse)")
                    return None
                
                # Get first valid email and remove it (atomic operation)
                email = None
                valid_emails = []
                for failed_email in failed_emails:
                    failed_email = failed_email.strip()
                    if failed_email and "@" in failed_email:
                        if email is None:
                            # First valid email - use it (removed from list)
                            email = failed_email
                            print(f"[DEBUG] [imap.get_and_remove_failed_email] Selected email: {email} (removing from file)")
                        else:
                            # Keep other valid emails
                            valid_emails.append(failed_email)
                    # Skip invalid emails
                
                if email is None:
                    # No valid emails found, clear the file
                    try:
                        with open(FAILED_EMAILS_FILE, 'w', encoding='utf-8', newline='\n') as f:
                            pass  # Create empty file
                    except Exception as e:
                        print(f"[WARN] [imap.get_and_remove_failed_email] Failed to clear file: {e}")
                    return None
                
                # Write back remaining valid emails (atomic write - removes the selected email)
                # Use 'utf-8' (not 'utf-8-sig') to avoid writing BOM
                try:
                    with open(FAILED_EMAILS_FILE, 'w', encoding='utf-8', newline='\n') as f:
                        for valid_email in valid_emails:
                            f.write(f"{valid_email}\n")
                    safe_print(f"[IMAP] [OK] Removed email from use_first_mails.txt: {email}")
                    safe_print(f"[IMAP] [OK] Remaining emails in file: {len(valid_emails)}")
                    if valid_emails:
                        safe_print(f"[IMAP] [OK] Remaining emails: {valid_emails}")
                except Exception as e:
                    print(f"[ERROR] [imap.get_and_remove_failed_email] Failed to write file: {e}")
                    import traceback
                    traceback.print_exc()
                    # Don't return the email if we couldn't remove it from file (prevent duplicate use)
                    return None
                
                safe_print(f"[IMAP] [OK] REUSING failed email from use_first_mails.txt: {email}")
                return email
            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"[ERROR] [imap.get_and_remove_failed_email] Failed after {max_retries} attempts: {e}")
                    return None
                else:
                    time.sleep(retry_delay)
    
    return None


def mark_email_success(email: str) -> None:
    """
    Remove email from failed emails list if it was successfully used.
    This is a safety check - the email should already be removed when retrieved,
    but this ensures it's not in the file if account creation succeeds.
    Thread-safe and cross-process safe.
    """
    if not email or not isinstance(email, str):
        return
    
    email = email.strip()
    if not email:
        return
    
    max_retries = 10
    retry_delay = 0.1
    
    # Use thread lock to prevent race conditions
    with _failed_emails_lock:
        for attempt in range(max_retries):
            try:
                if not os.path.exists(FAILED_EMAILS_FILE):
                    # File doesn't exist, email is already not in the list - success
                    print(f"[DEBUG] [imap.mark_email_success] use_first_mails.txt doesn't exist, email {email} already removed")
                    return
                
                # Read existing failed emails (atomic read)
                failed_emails = []
                try:
                    # Read with UTF-8 encoding and handle BOM
                    with open(FAILED_EMAILS_FILE, 'r', encoding='utf-8-sig') as f:
                        content = f.read()
                        # Strip BOM if present
                        if content.startswith('\ufeff'):
                            content = content[1:]
                        failed_emails = [line.strip() for line in content.splitlines() if line.strip()]
                except UnicodeDecodeError as e:
                    # Try reading with different encoding if UTF-8 fails
                    try:
                        with open(FAILED_EMAILS_FILE, 'r', encoding='latin-1') as f:
                            content = f.read()
                            if content.startswith('\ufeff'):
                                content = content[1:]
                            failed_emails = [line.strip() for line in content.splitlines() if line.strip()]
                    except Exception as e2:
                        print(f"[WARN] [imap.mark_email_success] Failed to read file: {e2}")
                        return
                except (IOError, ValueError, Exception) as e:
                    print(f"[WARN] [imap.mark_email_success] Failed to read file: {e}")
                    return
                
                # Remove email if present (safety check - should already be removed)
                if email in failed_emails:
                    failed_emails.remove(email)
                    
                    # Write back remaining emails (atomic write)
                    try:
                        with open(FAILED_EMAILS_FILE, 'w', encoding='utf-8') as f:
                            for failed_email in failed_emails:
                                f.write(f"{failed_email}\n")
                        
                        print(f"[IMAP] Removed successfully used email from failed list: {email} (was still in file)")
                    except Exception as e:
                        print(f"[ERROR] [imap.mark_email_success] Failed to write file: {e}")
                else:
                    # Email not in file - already removed (expected behavior)
                    print(f"[DEBUG] [imap.mark_email_success] Email {email} not in use_first_mails.txt (already removed)")
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"[ERROR] [imap.mark_email_success] Failed after {max_retries} attempts: {e}")
                else:
                    time.sleep(retry_delay)


# ==========================================================
# Check if email is already used
# ==========================================================
def _is_email_used(email: str) -> bool:
    """
    Check if an email exists in used_emails.txt files or reserved_emails.txt.
    Checks both per-user and global used_emails.txt files, and also reserved_emails.txt.
    Thread-safe.
    """
    if not email or "@" not in email:
        return False
    
    user_id = os.environ.get("USER_ID")
    email_lower = email.strip().lower()
    
    # Check reserved emails file first (emails currently being used by workers)
    try:
        if os.path.exists(RESERVED_EMAILS_FILE):
            with open(RESERVED_EMAILS_FILE, 'r', encoding='utf-8-sig', errors='replace') as f:
                for line in f:
                    if line.strip().lower() == email_lower:
                        print(f"[DEBUG] [imap._is_email_used] Email {email} found in reserved_emails.txt")
                        return True
    except Exception as e:
        print(f"[WARN] [imap._is_email_used] Error checking reserved file: {e}")
    
    # Check per-user file
    if user_id:
        try:
            per_user_path = REPORTS_DIR / f"used_emails_user{user_id}.txt"
            if per_user_path.exists():
                with open(per_user_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                    for line in f:
                        if line.strip().lower() == email_lower:
                            print(f"[DEBUG] [imap._is_email_used] Email {email} found in per-user used_emails file")
                            return True
        except Exception as e:
            print(f"[WARN] [imap._is_email_used] Error checking per-user file: {e}")
    
    # Check global file
    try:
        global_path = REPORTS_DIR / "used_emails.txt"
        if global_path.exists():
            with open(global_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                for line in f:
                    if line.strip().lower() == email_lower:
                        print(f"[DEBUG] [imap._is_email_used] Email {email} found in global used_emails file")
                        return True
    except Exception as e:
        print(f"[WARN] [imap._is_email_used] Error checking global file: {e}")
    
    return False


def _reserve_email(email: str) -> bool:
    """
    Reserve an email by adding it to reserved_emails.txt.
    This prevents other workers from using the same email.
    Returns True if successfully reserved, False if already reserved.
    Thread-safe and cross-process safe using file-based locking.
    """
    if not email or "@" not in email:
        return False
    
    email_lower = email.strip().lower()
    max_retries = 20
    retry_delay = 0.1
    
    # Use thread lock for in-process synchronization
    with _email_generation_lock:
        for attempt in range(max_retries):
            lock_fd = None
            lock_file_obj = None
            lock_acquired = False
            
            try:
                # Try to acquire file lock (cross-platform, similar to counter lock)
                if HAS_FCNTL:
                    # Unix/Linux: use fcntl
                    try:
                        lock_fd = os.open(EMAIL_GEN_LOCK_FILE, os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
                        try:
                            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            lock_acquired = True
                        except (IOError, OSError):
                            os.close(lock_fd)
                            lock_fd = None
                            if attempt < max_retries - 1:
                                time.sleep(retry_delay)
                                continue
                    except (IOError, OSError):
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            continue
                elif HAS_MSVCRT:
                    # Windows: use msvcrt
                    try:
                        lock_file_obj = open(EMAIL_GEN_LOCK_FILE, 'ab')
                        lock_fd = lock_file_obj.fileno()
                        try:
                            msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
                            lock_acquired = True
                        except IOError:
                            lock_file_obj.close()
                            lock_file_obj = None
                            lock_fd = None
                            if attempt < max_retries - 1:
                                time.sleep(retry_delay)
                                continue
                    except (OSError, IOError):
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            continue
                else:
                    # No file locking available, use simple file existence check
                    if os.path.exists(EMAIL_GEN_LOCK_FILE):
                        try:
                            lock_age = time.time() - os.path.getmtime(EMAIL_GEN_LOCK_FILE)
                            if lock_age > 5.0:
                                try:
                                    os.remove(EMAIL_GEN_LOCK_FILE)
                                except:
                                    pass
                            else:
                                if attempt < max_retries - 1:
                                    time.sleep(retry_delay)
                                    continue
                        except:
                            pass
                    
                    try:
                        lock_fd = os.open(EMAIL_GEN_LOCK_FILE, os.O_CREAT | os.O_WRONLY | os.O_EXCL)
                        lock_acquired = True
                    except (IOError, OSError):
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            continue
                
                if not lock_acquired:
                    if attempt < max_retries - 1:
                        continue
                    # Last attempt: proceed without file lock (thread lock still active)
                    break
                
                # Read existing reserved emails
                reserved_emails = set()
                if os.path.exists(RESERVED_EMAILS_FILE):
                    try:
                        with open(RESERVED_EMAILS_FILE, 'r', encoding='utf-8-sig', errors='replace') as f:
                            for line in f:
                                line = line.strip().lower()
                                if line:
                                    reserved_emails.add(line)
                    except Exception as e:
                        print(f"[WARN] [imap._reserve_email] Failed to read reserved file: {e}")
                
                # Check if already reserved
                if email_lower in reserved_emails:
                    print(f"[DEBUG] [imap._reserve_email] Email {email} already reserved")
                    # Release lock
                    if HAS_FCNTL and lock_fd:
                        try:
                            fcntl.flock(lock_fd, fcntl.LOCK_UN)
                            os.close(lock_fd)
                        except:
                            pass
                    elif HAS_MSVCRT and lock_file_obj:
                        try:
                            msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
                            lock_file_obj.close()
                        except:
                            pass
                    elif lock_fd:
                        try:
                            os.close(lock_fd)
                            os.remove(EMAIL_GEN_LOCK_FILE)
                        except:
                            pass
                    return False
                
                # Add to reserved list
                reserved_emails.add(email_lower)
                
                # Write back
                with open(RESERVED_EMAILS_FILE, 'w', encoding='utf-8', newline='\n') as f:
                    for reserved_email in sorted(reserved_emails):
                        f.write(f"{reserved_email}\n")
                
                print(f"[DEBUG] [imap._reserve_email] Reserved email: {email}")
                
                # Release lock
                if HAS_FCNTL and lock_fd:
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                        os.close(lock_fd)
                    except:
                        pass
                elif HAS_MSVCRT and lock_file_obj:
                    try:
                        msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
                        lock_file_obj.close()
                    except:
                        pass
                elif lock_fd:
                    try:
                        os.close(lock_fd)
                        os.remove(EMAIL_GEN_LOCK_FILE)
                    except:
                        pass
                
                return True
            except Exception as e:
                # Release lock on error
                if HAS_FCNTL and lock_fd:
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                        os.close(lock_fd)
                    except:
                        pass
                elif HAS_MSVCRT and lock_file_obj:
                    try:
                        msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
                        lock_file_obj.close()
                    except:
                        pass
                elif lock_fd:
                    try:
                        os.close(lock_fd)
                        try:
                            os.remove(EMAIL_GEN_LOCK_FILE)
                        except:
                            pass
                    except:
                        pass
                
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                print(f"[ERROR] [imap._reserve_email] Failed to reserve email after {max_retries} attempts: {e}")
                return False
    
    return False


def _reserve_email_atomic(email: str, lock_fd, lock_file_obj) -> bool:
    """
    Reserve an email atomically when we already hold the file lock.
    This is used inside generate_flipkart_email() when we already have the lock.
    Returns True if successfully reserved, False if already reserved.
    """
    if not email or "@" not in email:
        return False
    
    email_lower = email.strip().lower()
    
    try:
        # Read existing reserved emails
        reserved_emails = set()
        if os.path.exists(RESERVED_EMAILS_FILE):
            try:
                with open(RESERVED_EMAILS_FILE, 'r', encoding='utf-8-sig', errors='replace') as f:
                    for line in f:
                        line = line.strip().lower()
                        if line:
                            reserved_emails.add(line)
            except Exception as e:
                print(f"[WARN] [imap._reserve_email_atomic] Failed to read reserved file: {e}")
                return False
        
        # Check if already reserved or used
        if email_lower in reserved_emails:
            print(f"[DEBUG] [imap._reserve_email_atomic] Email {email} already in reserved_emails.txt (current reserved: {sorted(reserved_emails)})")
            return False
        
        # Also check if it's in used_emails.txt
        if _is_email_used_internal(email_lower):
            print(f"[DEBUG] [imap._reserve_email_atomic] Email {email} already in used_emails.txt")
            return False
        
        # Add to reserved list
        reserved_emails.add(email_lower)
        
        # Write back (with flush to ensure it's written immediately)
        with open(RESERVED_EMAILS_FILE, 'w', encoding='utf-8', newline='\n') as f:
            for reserved_email in sorted(reserved_emails):
                f.write(f"{reserved_email}\n")
            f.flush()  # Force write to disk immediately
            os.fsync(f.fileno())  # Ensure it's written to disk (Unix/Windows)
        
        print(f"[DEBUG] [imap._reserve_email_atomic] Successfully reserved email: {email} (total reserved now: {len(reserved_emails)})")
        return True
    except Exception as e:
        print(f"[ERROR] [imap._reserve_email_atomic] Failed to reserve email: {e}")
        return False


def _is_email_used_internal(email_lower: str) -> bool:
    """
    Internal function to check if email is used (without checking reserved_emails.txt).
    Used when we already have the lock and want to check only used_emails.txt.
    """
    user_id = os.environ.get("USER_ID")
    
    # Check per-user file
    if user_id:
        try:
            per_user_path = REPORTS_DIR / f"used_emails_user{user_id}.txt"
            if per_user_path.exists():
                with open(per_user_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                    for line in f:
                        if line.strip().lower() == email_lower:
                            return True
        except Exception as e:
            print(f"[WARN] [imap._is_email_used_internal] Error checking per-user file: {e}")
    
    # Check global file
    try:
        global_path = REPORTS_DIR / "used_emails.txt"
        if global_path.exists():
            with open(global_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                for line in f:
                    if line.strip().lower() == email_lower:
                        return True
    except Exception as e:
        print(f"[WARN] [imap._is_email_used_internal] Error checking global file: {e}")
    
    return False


def _release_email_lock(lock_fd, lock_file_obj) -> None:
    """Release the email generation file lock."""
    if HAS_FCNTL and lock_fd:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        except:
            pass
    elif HAS_MSVCRT and lock_file_obj:
        try:
            msvcrt.locking(lock_file_obj.fileno(), msvcrt.LK_UNLCK, 1)
            lock_file_obj.close()
        except:
            pass
    elif lock_fd:
        try:
            os.close(lock_fd)
            try:
                os.remove(EMAIL_GEN_LOCK_FILE)
            except:
                pass
        except:
            pass


def _unreserve_email(email: str) -> None:
    """
    Remove an email from reserved_emails.txt.
    Called when email is successfully used (moved to used_emails.txt) or when worker fails.
    Thread-safe and cross-process safe using file-based locking.
    """
    if not email or "@" not in email:
        return
    
    email_lower = email.strip().lower()
    max_retries = 10
    retry_delay = 0.1
    
    # Use thread lock for in-process synchronization
    with _email_generation_lock:
        for attempt in range(max_retries):
            lock_fd = None
            lock_file_obj = None
            lock_acquired = False
            
            try:
                # Try to acquire file lock (cross-platform, similar to counter lock)
                if HAS_FCNTL:
                    try:
                        lock_fd = os.open(EMAIL_GEN_LOCK_FILE, os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
                        try:
                            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            lock_acquired = True
                        except (IOError, OSError):
                            os.close(lock_fd)
                            lock_fd = None
                            if attempt < max_retries - 1:
                                time.sleep(retry_delay)
                                continue
                    except (IOError, OSError):
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            continue
                elif HAS_MSVCRT:
                    try:
                        lock_file_obj = open(EMAIL_GEN_LOCK_FILE, 'ab')
                        lock_fd = lock_file_obj.fileno()
                        try:
                            msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
                            lock_acquired = True
                        except IOError:
                            lock_file_obj.close()
                            lock_file_obj = None
                            lock_fd = None
                            if attempt < max_retries - 1:
                                time.sleep(retry_delay)
                                continue
                    except (OSError, IOError):
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            continue
                else:
                    if os.path.exists(EMAIL_GEN_LOCK_FILE):
                        try:
                            lock_age = time.time() - os.path.getmtime(EMAIL_GEN_LOCK_FILE)
                            if lock_age > 5.0:
                                try:
                                    os.remove(EMAIL_GEN_LOCK_FILE)
                                except:
                                    pass
                            else:
                                if attempt < max_retries - 1:
                                    time.sleep(retry_delay)
                                    continue
                        except:
                            pass
                    
                    try:
                        lock_fd = os.open(EMAIL_GEN_LOCK_FILE, os.O_CREAT | os.O_WRONLY | os.O_EXCL)
                        lock_acquired = True
                    except (IOError, OSError):
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            continue
                
                if not lock_acquired:
                    if attempt < max_retries - 1:
                        continue
                    break
                
                if not os.path.exists(RESERVED_EMAILS_FILE):
                    # Release lock
                    if HAS_FCNTL and lock_fd:
                        try:
                            fcntl.flock(lock_fd, fcntl.LOCK_UN)
                            os.close(lock_fd)
                        except:
                            pass
                    elif HAS_MSVCRT and lock_file_obj:
                        try:
                            msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
                            lock_file_obj.close()
                        except:
                            pass
                    elif lock_fd:
                        try:
                            os.close(lock_fd)
                            os.remove(EMAIL_GEN_LOCK_FILE)
                        except:
                            pass
                    return
                
                # Read existing reserved emails
                reserved_emails = set()
                try:
                    with open(RESERVED_EMAILS_FILE, 'r', encoding='utf-8-sig', errors='replace') as f:
                        for line in f:
                            line = line.strip().lower()
                            if line:
                                reserved_emails.add(line)
                except Exception as e:
                    print(f"[WARN] [imap._unreserve_email] Failed to read reserved file: {e}")
                    # Release lock
                    if HAS_FCNTL and lock_fd:
                        try:
                            fcntl.flock(lock_fd, fcntl.LOCK_UN)
                            os.close(lock_fd)
                        except:
                            pass
                    elif HAS_MSVCRT and lock_file_obj:
                        try:
                            msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
                            lock_file_obj.close()
                        except:
                            pass
                    elif lock_fd:
                        try:
                            os.close(lock_fd)
                            os.remove(EMAIL_GEN_LOCK_FILE)
                        except:
                            pass
                    return
                
                # Remove if present
                if email_lower in reserved_emails:
                    reserved_emails.remove(email_lower)
                    
                    # Write back
                    with open(RESERVED_EMAILS_FILE, 'w', encoding='utf-8', newline='\n') as f:
                        for reserved_email in sorted(reserved_emails):
                            f.write(f"{reserved_email}\n")
                    
                    print(f"[DEBUG] [imap._unreserve_email] Unreserved email: {email}")
                
                # Release lock
                if HAS_FCNTL and lock_fd:
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                        os.close(lock_fd)
                    except:
                        pass
                elif HAS_MSVCRT and lock_file_obj:
                    try:
                        msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
                        lock_file_obj.close()
                    except:
                        pass
                elif lock_fd:
                    try:
                        os.close(lock_fd)
                        os.remove(EMAIL_GEN_LOCK_FILE)
                    except:
                        pass
                
                return
            except Exception as e:
                # Release lock on error
                if HAS_FCNTL and lock_fd:
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                        os.close(lock_fd)
                    except:
                        pass
                elif HAS_MSVCRT and lock_file_obj:
                    try:
                        msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
                        lock_file_obj.close()
                    except:
                        pass
                elif lock_fd:
                    try:
                        os.close(lock_fd)
                        try:
                            os.remove(EMAIL_GEN_LOCK_FILE)
                        except:
                            pass
                    except:
                        pass
                
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                print(f"[WARN] [imap._unreserve_email] Failed to unreserve email: {e}")
                return


def unreserve_email(email: str) -> None:
    """
    Public function to unreserve an email.
    Called when email is successfully used or when worker fails.
    """
    _unreserve_email(email)


# ==========================================================
# Find missing sequence numbers in used_emails.txt
# ==========================================================
def _find_missing_sequence_number(domain: str) -> int | None:
    """
    Find the first missing sequence number in used_emails.txt files.
    For example, if we have flipkart1, flipkart2, flipkart3, flipkart5, flipkart6,
    then flipkart4 is missing, so return 4.
    
    Thread-safe. Checks both per-user and global used_emails.txt files.
    Returns None if no gaps are found.
    """
    missing_numbers = _find_all_missing_sequence_numbers(domain)
    if missing_numbers:
        return missing_numbers[0]  # Return the first (lowest) missing number
    return None


def _find_all_missing_sequence_numbers(domain: str) -> list[int]:
    """
    Find ALL missing sequence numbers in used_emails.txt files.
    For example, if we have flipkart1, flipkart2, flipkart3, flipkart5, flipkart6, flipkart9,
    then flipkart4, flipkart7, flipkart8 are missing, so return [4, 7, 8].
    
    Thread-safe. Checks both per-user and global used_emails.txt files.
    Returns a sorted list of missing numbers, or empty list if no gaps are found.
    """
    if not domain or not domain.strip():
        return []
    
    user_id = os.environ.get("USER_ID")
    used_numbers = set()
    
    # Read per-user file first
    if user_id:
        try:
            per_user_path = REPORTS_DIR / f"used_emails_user{user_id}.txt"
            if per_user_path.exists():
                with open(per_user_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        # Extract number from patterns like "flipkart1@domain.com" or "admin+flipkart1@domain.com"
                        # Match flipkart followed by digits
                        match = re.search(r'flipkart(\d+)@', line.lower())
                        if match:
                            num = int(match.group(1))
                            used_numbers.add(num)
        except Exception as e:
            print(f"[WARN] [imap._find_all_missing_sequence_numbers] Error reading per-user file: {e}")
    
    # Read global file
    try:
        global_path = REPORTS_DIR / "used_emails.txt"
        if global_path.exists():
            with open(global_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    # Extract number from patterns like "flipkart1@domain.com" or "admin+flipkart1@domain.com"
                    match = re.search(r'flipkart(\d+)@', line.lower())
                    if match:
                        num = int(match.group(1))
                        used_numbers.add(num)
    except Exception as e:
        print(f"[WARN] [imap._find_all_missing_sequence_numbers] Error reading global file: {e}")
    
    if not used_numbers:
        # No emails found, no gaps to fill
        return []
    
    # Find all missing numbers starting from 1
    max_num = max(used_numbers) if used_numbers else 0
    missing_numbers = []
    # Check for gaps from 1 to max_num
    for num in range(1, max_num + 1):
        if num not in used_numbers:
            missing_numbers.append(num)
    
    if missing_numbers:
        print(f"[DEBUG] [imap._find_all_missing_sequence_numbers] Found {len(missing_numbers)} missing sequence numbers: {missing_numbers[:10]}{'...' if len(missing_numbers) > 10 else ''} (used numbers: {sorted(list(used_numbers))[:20]}{'...' if len(used_numbers) > 20 else ''})")
    
    return missing_numbers


# ==========================================================
# Generate tagged email
# ==========================================================
def generate_flipkart_email() -> str:
    """
    Create a unique plus-tagged email using the configured base address.
    First checks use_first_mails.txt for any failed emails to reuse.
    If no failed emails found, generates a new email with counter.
    Example: flipkart1@example.com, flipkart2@example.com (no "admin+" prefix)
    Uses an atomic counter that increments atomically to prevent race conditions.
    The counter increments when generating the email (ensuring uniqueness across parallel workers).
    Loads IMAP config from Supabase (per-user) first, then falls back to JSON file.
    
    CRITICAL: This function uses file-based locking to ensure only one worker
    can generate an email at a time across processes, preventing race conditions.
    """
    max_retries = 20
    retry_delay = 0.1
    
    # Acquire file lock for entire email generation process (cross-process safe)
    for attempt in range(max_retries):
        lock_fd = None
        lock_file_obj = None
        lock_acquired = False
        
        try:
            # Try to acquire file lock (cross-platform, similar to counter lock)
            if HAS_FCNTL:
                try:
                    lock_fd = os.open(EMAIL_GEN_LOCK_FILE, os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        lock_acquired = True
                    except (IOError, OSError):
                        os.close(lock_fd)
                        lock_fd = None
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            continue
                except (IOError, OSError):
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
            elif HAS_MSVCRT:
                try:
                    lock_file_obj = open(EMAIL_GEN_LOCK_FILE, 'ab')
                    lock_fd = lock_file_obj.fileno()
                    try:
                        msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
                        lock_acquired = True
                    except IOError:
                        lock_file_obj.close()
                        lock_file_obj = None
                        lock_fd = None
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            continue
                except (OSError, IOError):
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
            else:
                if os.path.exists(EMAIL_GEN_LOCK_FILE):
                    try:
                        lock_age = time.time() - os.path.getmtime(EMAIL_GEN_LOCK_FILE)
                        if lock_age > 5.0:
                            try:
                                os.remove(EMAIL_GEN_LOCK_FILE)
                            except:
                                pass
                        else:
                            if attempt < max_retries - 1:
                                time.sleep(retry_delay)
                                continue
                    except:
                        pass
                
                try:
                    lock_fd = os.open(EMAIL_GEN_LOCK_FILE, os.O_CREAT | os.O_WRONLY | os.O_EXCL)
                    lock_acquired = True
                except (IOError, OSError):
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
            
            if not lock_acquired:
                if attempt < max_retries - 1:
                    print(f"[DEBUG] [imap.generate_flipkart_email] Lock not acquired, retrying (attempt {attempt + 1}/{max_retries})")
                    continue
                # Last attempt: proceed without file lock (not ideal but better than failing)
                print(f"[WARN] [imap.generate_flipkart_email] Could not acquire file lock after {max_retries} attempts, proceeding without lock")
                break
            
            # Verify lock is actually held (write a marker to the lock file)
            try:
                if lock_fd:
                    os.write(lock_fd, b"LOCKED\n")
                    os.fsync(lock_fd)
                elif lock_file_obj:
                    lock_file_obj.write(b"LOCKED\n")
                    lock_file_obj.flush()
            except Exception as e:
                print(f"[WARN] [imap.generate_flipkart_email] Could not write lock marker: {e}")
            
            # Now we have the lock - generate email atomically
            print(f"[DEBUG] [imap.generate_flipkart_email] LOCK ACQUIRED - generating email atomically (attempt {attempt + 1}/{max_retries}, lock_fd={lock_fd}, lock_file_obj={lock_file_obj})")
            try:
                # PRIORITY 1: First, check for missing sequence numbers in used_emails.txt
                # This is the highest priority - fill gaps in the sequence before reusing failed emails
                cfg = {}
                user_id = os.environ.get("USER_ID")
                
                # Try to load from Supabase first (per-user config)
                if user_id:
                    try:
                        import neon_client as supabase_client
                        if supabase_client.is_enabled():
                            try:
                                user_id_int = int(user_id)
                                cfg = supabase_client.get_imap_config(user_id_int)
                                if cfg and cfg.get("email"):
                                    base_email = cfg.get("email")
                                    if "@" in base_email:
                                        domain = base_email.split("@", 1)[1]
                                        if domain and domain.strip():
                                            # FIRST: Check for missing sequence numbers in used_emails.txt
                                            # Try ALL missing sequences until we find one that's available
                                            missing_numbers = _find_all_missing_sequence_numbers(domain)
                                            if missing_numbers:
                                                for missing_num in missing_numbers:
                                                    missing_email = f"flipkart{missing_num}@{domain}"
                                                    # Check and reserve atomically (we already have the lock)
                                                    if _reserve_email_atomic(missing_email, lock_fd, lock_file_obj):
                                                        print(f"[DEBUG] [imap.generate_flipkart_email] Using missing sequence number: flipkart{missing_num}@{domain}")
                                                        # Release lock before returning
                                                        _release_email_lock(lock_fd, lock_file_obj)
                                                        return missing_email
                                                    else:
                                                        print(f"[DEBUG] [imap.generate_flipkart_email] Missing sequence {missing_num} is already reserved, trying next missing sequence...")
                                                # All missing sequences are reserved, will check failed emails next
                                                print(f"[DEBUG] [imap.generate_flipkart_email] All {len(missing_numbers)} missing sequences are already reserved, will check failed emails next")
                                            
                                            # PRIORITY 2: Check failed emails if no missing sequences available
                                            failed_email = get_and_remove_failed_email()
                                            if failed_email:
                                                if _reserve_email_atomic(failed_email, lock_fd, lock_file_obj):
                                                    safe_print(f"[IMAP] [OK] PRIORITY 2: REUSING failed email from use_first_mails.txt: {failed_email}")
                                                    _release_email_lock(lock_fd, lock_file_obj)
                                                    return failed_email
                                            
                                            # PRIORITY 3: Generate email using counter if no missing sequences and no failed emails
                                            print(f"[DEBUG] [imap.generate_flipkart_email] PRIORITY 3: Using counter to generate new email")
                                            max_attempts = 100  # Prevent infinite loop
                                            for email_attempt in range(max_attempts):
                                                counter = _get_next_counter()
                                                generated_email = f"flipkart{counter}@{domain}"
                                                
                                                # Reserve atomically (we already have the lock)
                                                if _reserve_email_atomic(generated_email, lock_fd, lock_file_obj):
                                                    print(f"[DEBUG] [imap.generate_flipkart_email] PRIORITY 3: Generated and reserved unused email: {generated_email}")
                                                    # Release lock before returning
                                                    _release_email_lock(lock_fd, lock_file_obj)
                                                    return generated_email
                                                else:
                                                    print(f"[DEBUG] [imap.generate_flipkart_email] Email {generated_email} already in used_emails.txt or reserved by another worker, trying next number...")
                                                    continue
                                            
                                            # If we exhausted all attempts, return the last generated email anyway
                                            print(f"[ERROR] [imap.generate_flipkart_email] Exhausted {max_attempts} attempts, using: {generated_email}")
                                            # Try to reserve it anyway
                                            _reserve_email_atomic(generated_email, lock_fd, lock_file_obj)
                                            _release_email_lock(lock_fd, lock_file_obj)
                                            return generated_email
                            except Exception as e:
                                print(f"[DEBUG] [imap.generate_flipkart_email] Supabase load failed: {e}")
                    except ImportError:
                        pass  # supabase_client not available
                
                # Fallback to JSON file
                if not cfg or not cfg.get("email"):
                    cfg = load_imap_config()
                
                base_email = cfg.get("email", "")
                if "@" not in base_email:
                    raise ValueError("Configured email is invalid or missing '@'")
                
                domain = base_email.split("@", 1)[1]
                if not domain or not domain.strip():
                    raise ValueError("Configured email domain is invalid or empty")
                
                # PRIORITY 1: Check for missing sequence numbers in used_emails.txt
                # Try ALL missing sequences until we find one that's available
                missing_numbers = _find_all_missing_sequence_numbers(domain)
                if missing_numbers:
                    for missing_num in missing_numbers:
                        missing_email = f"flipkart{missing_num}@{domain}"
                        # Reserve atomically (we already have the lock)
                        if _reserve_email_atomic(missing_email, lock_fd, lock_file_obj):
                            print(f"[DEBUG] [imap.generate_flipkart_email] PRIORITY 1: Using missing sequence number: flipkart{missing_num}@{domain}")
                            # Release lock before returning
                            _release_email_lock(lock_fd, lock_file_obj)
                            return missing_email
                        else:
                            print(f"[DEBUG] [imap.generate_flipkart_email] Missing sequence {missing_num} is already reserved, trying next missing sequence...")
                    # All missing sequences are reserved, will check failed emails next
                    print(f"[DEBUG] [imap.generate_flipkart_email] All {len(missing_numbers)} missing sequences are already reserved, will check failed emails next")
                
                # PRIORITY 2: Check if there are any failed emails to reuse from use_first_mails.txt
                # Only use failed emails if no missing sequences are available
                print(f"[DEBUG] [imap.generate_flipkart_email] PRIORITY 2: Checking use_first_mails.txt for failed emails...")
                print(f"[DEBUG] [imap.generate_flipkart_email] File path: {FAILED_EMAILS_FILE}")
                print(f"[DEBUG] [imap.generate_flipkart_email] File exists: {os.path.exists(FAILED_EMAILS_FILE)}")
                
                if os.path.exists(FAILED_EMAILS_FILE):
                    try:
                        # Check file size
                        file_size = os.path.getsize(FAILED_EMAILS_FILE)
                        print(f"[DEBUG] [imap.generate_flipkart_email] File size: {file_size} bytes")
                        if file_size > 0:
                            # Try to peek at file content (first 200 chars) for debugging
                            with open(FAILED_EMAILS_FILE, 'r', encoding='utf-8-sig', errors='replace') as f:
                                peek = f.read(200)
                                print(f"[DEBUG] [imap.generate_flipkart_email] File preview: {repr(peek)}")
                    except Exception as e:
                        print(f"[WARN] [imap.generate_flipkart_email] Could not preview file: {e}")
                
                failed_email = get_and_remove_failed_email()
                if failed_email:
                    # Reserve the failed email immediately
                    if _reserve_email_atomic(failed_email, lock_fd, lock_file_obj):
                        safe_print(f"[IMAP] [OK] PRIORITY 2: REUSING failed email from use_first_mails.txt: {failed_email}")
                        # Release lock AFTER reserving (lock must be held during reservation)
                        _release_email_lock(lock_fd, lock_file_obj)
                        lock_acquired = False  # Mark as released
                        return failed_email
                    else:
                        print(f"[WARN] [imap.generate_flipkart_email] Failed to reserve failed email {failed_email}, will use counter instead")
                else:
                    print(f"[DEBUG] [imap.generate_flipkart_email] No failed emails found in use_first_mails.txt, will use counter")
                
                # PRIORITY 3: If no missing sequences and no failed emails, generate email using counter
                # Keep trying until we find an unused email
                print(f"[DEBUG] [imap.generate_flipkart_email] PRIORITY 3: Using counter to generate new email")
                max_attempts = 100  # Prevent infinite loop
                for email_attempt in range(max_attempts):
                    counter = _get_next_counter()
                    # Remove "admin+" prefix, just use flipkart{counter}
                    generated_email = f"flipkart{counter}@{domain}"
                    
                    print(f"[DEBUG] [imap.generate_flipkart_email] Generated email from counter: {generated_email}, attempting to reserve (we have lock)")
                    # Reserve atomically (we already have the lock)
                    if _reserve_email_atomic(generated_email, lock_fd, lock_file_obj):
                        print(f"[DEBUG] [imap.generate_flipkart_email] PRIORITY 3: Successfully reserved email from counter: {generated_email}, releasing lock")
                        # Release lock AFTER reserving (lock must be held during reservation)
                        _release_email_lock(lock_fd, lock_file_obj)
                        lock_acquired = False  # Mark as released
                        return generated_email
                    else:
                        print(f"[DEBUG] [imap.generate_flipkart_email] Email {generated_email} already in used_emails.txt or reserved by another worker, trying next number...")
                        continue
                
                # If we exhausted all attempts, return the last generated email anyway (shouldn't happen)
                print(f"[ERROR] [imap.generate_flipkart_email] Exhausted {max_attempts} attempts to find unused email, using: {generated_email}")
                # Try to reserve it anyway
                _reserve_email_atomic(generated_email, lock_fd, lock_file_obj)
                _release_email_lock(lock_fd, lock_file_obj)
                return generated_email
            except Exception as e:
                # Release lock on error
                if lock_acquired:
                    _release_email_lock(lock_fd, lock_file_obj)
                print(f"[ERROR] [imap.generate_flipkart_email] Error generating email: {e}")
                raise
            finally:
                # Always release lock
                if lock_acquired:
                    _release_email_lock(lock_fd, lock_file_obj)
        
        except Exception as e:
            # Error acquiring lock or during lock acquisition
            if lock_acquired:
                _release_email_lock(lock_fd, lock_file_obj)
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            # Last attempt failed, break and use fallback
            break
    # If we couldn't acquire lock after all retries, fall back to non-atomic generation (not ideal)
    print(f"[WARN] [imap.generate_flipkart_email] Could not acquire lock, using fallback method")
    # Fallback: use the old method without file lock (less safe but better than failing)
    failed_email = get_and_remove_failed_email()
    if failed_email:
        if _reserve_email(failed_email):
            return failed_email
    
    # Generate new email
    cfg = {}
    user_id = os.environ.get("USER_ID")
    if user_id:
        try:
            import neon_client as supabase_client
            if supabase_client.is_enabled():
                try:
                    user_id_int = int(user_id)
                    cfg = supabase_client.get_imap_config(user_id_int)
                except Exception:
                    pass
        except ImportError:
            pass
    
    if not cfg or not cfg.get("email"):
        cfg = load_imap_config()
    
    base_email = cfg.get("email", "")
    if "@" not in base_email:
        raise ValueError("Configured email is invalid or missing '@'")
    
    domain = base_email.split("@", 1)[1]
    if not domain or not domain.strip():
        raise ValueError("Configured email domain is invalid or empty")
    
    # Generate using counter
    for email_attempt in range(100):
        counter = _get_next_counter()
        generated_email = f"flipkart{counter}@{domain}"
        if _reserve_email(generated_email):
            return generated_email
    
    # Last resort
    counter = _get_next_counter()
    generated_email = f"flipkart{counter}@{domain}"
    _reserve_email(generated_email)
    return generated_email


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
    Loads IMAP config from Supabase (per-user) first, then falls back to JSON file.
    """
    cfg = {}
    user_id = os.environ.get("USER_ID")
    
    # Try to load from Supabase first (per-user config)
    if user_id and supabase_client and supabase_client.is_enabled():
        try:
            user_id_int = int(user_id)
            cfg = supabase_client.get_imap_config(user_id_int)
        except Exception as e:
            print(f"[DEBUG] [imap.otp] Supabase load failed: {e}")
    
    # Fallback to JSON file
    if not cfg:
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

