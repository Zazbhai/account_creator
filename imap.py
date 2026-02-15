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
FAILED_EMAILS_LOCK_FILE = os.path.abspath(os.path.join(BASE_DIR, "use_first_mails.lock"))
EMAIL_GEN_LOCK_FILE = os.path.abspath(os.path.join(BASE_DIR, "email_generation.lock"))
RESERVED_EMAILS_FILE = os.path.abspath(os.path.join(BASE_DIR, "reserved_emails.txt"))

# Reports directory for used emails (matches account_creator.py - root directory)
REPORTS_DIR = Path(BASE_DIR)

# Thread lock for in-process synchronization
_counter_lock = threading.Lock()
_failed_emails_lock = threading.Lock()
_email_generation_lock = threading.Lock()  # Lock for entire email generation to prevent race conditions

# ==========================================================
# ROBUST FILE HELPERS
# ==========================================================
def _safe_write_lines(filepath, lines):
    """Write lines to a file atomically using a temporary file and rename."""
    temp_path = str(filepath) + ".tmp"
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        
        with open(temp_path, 'w', encoding='utf-8', newline='\n') as f:
            for line in lines:
                f.write(f"{line.strip()}\n")
            f.flush()
            os.fsync(f.fileno()) # Ensure it's on disk
        
        # Atomic replacement
        if os.path.exists(filepath):
            os.replace(temp_path, filepath)
        else:
            os.rename(temp_path, filepath)
        return True
    except Exception as e:
        print(f"[ERROR] [imap] Robust write failed for {filepath}: {e}")
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass
        return False

def _safe_save_json(filepath, data):
    """Save JSON data atomically."""
    temp_path = str(filepath) + ".tmp"
    try:
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
        
        if os.path.exists(filepath):
            os.replace(temp_path, filepath)
        else:
            os.rename(temp_path, filepath)
        return True
    except Exception as e:
        print(f"[ERROR] [imap] Robust JSON save failed for {filepath}: {e}")
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass
        return False


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
        if _safe_save_json(COUNTER_FILE, {"counter": counter}):
             # Success
             pass
        else:
             print(f"[WARN] [imap._get_next_counter] Failed to save counter robustly")
        
        return counter


# ==========================================================
# Failed Email Management
# ==========================================================
def add_failed_email(email: str) -> None:
    """
    Add a failed email to use_first_mails.txt for reuse in future sessions.
    Thread-safe and cross-process safe using file-based locking.
    """
    if not email or not isinstance(email, str):
        return
    
    email = email.strip()
    if not email or "@" not in email:
        print(f"[WARN] [imap.add_failed_email] Invalid email format: {email}")
        return
    
    max_retries = 20
    retry_delay = 0.1
    
    with _failed_emails_lock:
        for attempt in range(max_retries):
            lock_fd = None
            lock_file_obj = None
            lock_acquired = False
            
            try:
                # Acquire file lock for use_first_mails.txt
                if HAS_FCNTL:
                    lock_fd = os.open(FAILED_EMAILS_LOCK_FILE, os.O_CREAT | os.O_WRONLY)
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    lock_acquired = True
                elif HAS_MSVCRT:
                    lock_file_obj = open(FAILED_EMAILS_LOCK_FILE, 'ab')
                    lock_fd = lock_file_obj.fileno()
                    msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
                    lock_acquired = True
                
                # Now we have the lock, read and update
                failed_emails = []
                if os.path.exists(FAILED_EMAILS_FILE):
                    with open(FAILED_EMAILS_FILE, 'r', encoding='utf-8-sig', errors='replace') as f:
                        failed_emails = [line.strip() for line in f if line.strip()]
                
                if email not in failed_emails:
                    failed_emails.append(email)
                    if _safe_write_lines(FAILED_EMAILS_FILE, failed_emails):
                        print(f"[IMAP] Added email to use_first_mails.txt: {email} (total: {len(failed_emails)})")
                    else:
                        print(f"[ERROR] [imap.add_failed_email] Failed to write failed emails robustly")
                
                break # Success
            except (IOError, OSError):
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
            finally:
                if lock_acquired:
                    if HAS_FCNTL and lock_fd:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                        os.close(lock_fd)
                    elif HAS_MSVCRT and lock_file_obj:
                        msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
                        lock_file_obj.close()


def get_and_remove_failed_email():
    """
    Get the first failed email from use_first_mails.txt and remove it atomically.
    Thread-safe and cross-process safe using file-based locking.
    """
    max_retries = 20
    retry_delay = 0.1
    
    with _failed_emails_lock:
        for attempt in range(max_retries):
            lock_fd = None
            lock_file_obj = None
            lock_acquired = False
            
            try:
                if not os.path.exists(FAILED_EMAILS_FILE):
                    return None
                
                # Acquire file lock
                if HAS_FCNTL:
                    lock_fd = os.open(FAILED_EMAILS_LOCK_FILE, os.O_CREAT | os.O_WRONLY)
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    lock_acquired = True
                elif HAS_MSVCRT:
                    lock_file_obj = open(FAILED_EMAILS_LOCK_FILE, 'ab')
                    lock_fd = lock_file_obj.fileno()
                    msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
                    lock_acquired = True
                
                # Lock acquired, read
                failed_emails = []
                with open(FAILED_EMAILS_FILE, 'r', encoding='utf-8-sig', errors='replace') as f:
                    failed_emails = [line.strip() for line in f if line.strip()]
                
                if not failed_emails:
                    _release_email_lock(lock_fd, lock_file_obj)
                    return None
                
                # Take the first one and write back remaining
                selected = failed_emails.pop(0)
                if _safe_write_lines(FAILED_EMAILS_FILE, failed_emails):
                    print(f"[IMAP] REUSING email from use_first_mails.txt: {selected}")
                    _release_email_lock(lock_fd, lock_file_obj)
                    return selected
                else:
                    print(f"[ERROR] [imap.get_and_remove_failed_email] Failed to write back robustly")
                    _release_email_lock(lock_fd, lock_file_obj)
                    return None
                
            except (IOError, OSError):
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
            finally:
                if lock_acquired:
                    _release_email_lock(lock_fd, lock_file_obj)
    
    return None


def mark_email_success(email: str) -> None:
    """
    Remove email from failed emails pool.
    Thread-safe and cross-process safe using file-based locking.
    """
    if not email:
        return
    
    email = email.strip().lower()
    max_retries = 20
    retry_delay = 0.1
    
    with _failed_emails_lock:
        for attempt in range(max_retries):
            lock_fd = None
            lock_file_obj = None
            lock_acquired = False
            
            try:
                if not os.path.exists(FAILED_EMAILS_FILE):
                    return
                
                if HAS_FCNTL:
                    lock_fd = os.open(FAILED_EMAILS_LOCK_FILE, os.O_CREAT | os.O_WRONLY)
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    lock_acquired = True
                elif HAS_MSVCRT:
                    lock_file_obj = open(FAILED_EMAILS_LOCK_FILE, 'ab')
                    lock_fd = lock_file_obj.fileno()
                    msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
                    lock_acquired = True
                
                # Now we have the lock, read and update
                failed_emails = []
                with open(FAILED_EMAILS_FILE, 'r', encoding='utf-8-sig', errors='replace') as f:
                    failed_emails = [line.strip() for line in f if line.strip()]
                
                original_len = len(failed_emails)
                failed_emails = [fe for fe in failed_emails if fe.lower() != email]
                
                if len(failed_emails) != original_len:
                    if _safe_write_lines(FAILED_EMAILS_FILE, failed_emails):
                        print(f"[IMAP] mark_email_success: Removed {email} from use_first_mails.txt")
                    else:
                        print(f"[ERROR] [imap.mark_email_success] Failed to remove email robustly")
                
                _release_email_lock(lock_fd, lock_file_obj)
                break
            except (IOError, OSError):
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
            finally:
                if lock_acquired:
                    _release_email_lock(lock_fd, lock_file_obj)


# ==========================================================
# Check if email is already used
# ==========================================================
def _is_email_used(email: str) -> bool:
    """
    Check if an email exists in used_emails.txt files or reserved_emails.txt.
    Checks both per-user and global used_emails.txt files, and also reserved_emails.txt.
    Matches primarily based on sequence number (e.g. flipkart1 == admin+flipkart1).
    Thread-safe.
    """
    if not email or "@" not in email:
        return False
    
    user_id = os.environ.get("USER_ID")
    email_lower = email.strip().lower()
    
    # Extract number from candidate email
    candidate_num = None
    match = re.search(r'flipkart(\d+)@', email_lower)
    if match:
        candidate_num = int(match.group(1))

    # Helper to check number match or string match
    def is_match(line, target_email, target_num):
        line = line.strip().lower()
        if not line: return False
        if line == target_email: return True
        # Check number match
        if target_num is not None:
            m = re.search(r'flipkart(\d+)@', line)
            if m and int(m.group(1)) == target_num:
                return True
        return False
    
    # Check reserved emails file first (emails currently being used by workers)
    try:
        if os.path.exists(RESERVED_EMAILS_FILE):
             with open(RESERVED_EMAILS_FILE, 'r', encoding='utf-8-sig', errors='replace') as f:
                for line in f:
                    # Handle "email|timestamp" format
                    line_email = line.split('|', 1)[0].strip().lower() if '|' in line else line.strip().lower()
                    if is_match(line_email, email_lower, candidate_num):
                        print(f"[DEBUG] [imap._is_email_used] Email {email} (or num {candidate_num}) found in reserved_emails.txt")
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
                        if is_match(line, email_lower, candidate_num):
                            print(f"[DEBUG] [imap._is_email_used] Email {email} (or num {candidate_num}) found in per-user used_emails file")
                            return True
        except Exception as e:
            print(f"[WARN] [imap._is_email_used] Error checking per-user file: {e}")
    
    # Check global file
    try:
        global_path = REPORTS_DIR / "used_emails.txt"
        if global_path.exists():
            with open(global_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                for line in f:
                    if is_match(line, email_lower, candidate_num):
                        print(f"[DEBUG] [imap._is_email_used] Email {email} (or num {candidate_num}) found in global used_emails file")
                        return True
    except Exception as e:
        print(f"[WARN] [imap._is_email_used] Error checking global file: {e}")
    
    return False

def cleanup_stale_reservations(timeout_minutes: int = 10) -> int:
    """
    Remove any reservations older than timeout_minutes from reserved_emails.txt.
    Self-healing mechanism for crashed workers.
    Returns the number of removed entries.
    """
    if not os.path.exists(RESERVED_EMAILS_FILE):
        return 0
    
    max_retries = 20
    retry_delay = 0.1
    removed_count = 0
    
    with _email_generation_lock:
        for attempt in range(max_retries):
            lock_fd = None
            lock_file_obj = None
            lock_acquired = False
            
            try:
                # Acquire lock
                if HAS_FCNTL:
                    lock_fd = os.open(EMAIL_GEN_LOCK_FILE, os.O_CREAT | os.O_WRONLY)
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    lock_acquired = True
                elif HAS_MSVCRT:
                    lock_file_obj = open(EMAIL_GEN_LOCK_FILE, 'ab')
                    lock_fd = lock_file_obj.fileno()
                    msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
                    lock_acquired = True
                
                # Read and filter
                current_time = time.time()
                timeout_seconds = timeout_minutes * 60
                
                kept_entries = []
                if os.path.exists(RESERVED_EMAILS_FILE):
                    with open(RESERVED_EMAILS_FILE, 'r', encoding='utf-8-sig', errors='replace') as f:
                        for line in f:
                            line = line.strip()
                            if not line: continue
                            
                            if '|' in line:
                                email_part, ts_part = line.split('|', 1)
                                try:
                                    ts = float(ts_part)
                                    if current_time - ts < timeout_seconds:
                                        kept_entries.append(line)
                                    else:
                                        removed_count += 1
                                        print(f"[DEBUG] [imap.cleanup] Removing stale reservation: {email_part} (age: {int(current_time - ts)}s)")
                                except (ValueError, TypeError):
                                    # Corrupted line? Remove it
                                    removed_count += 1
                            else:
                                # Old format without timestamp? Keep but it will be purged next time if it doesn't match
                                kept_entries.append(f"{line}|{current_time}")
                
                if removed_count > 0:
                    if _safe_write_lines(RESERVED_EMAILS_FILE, kept_entries):
                        print(f"[IMAP] Cleanup: Removed {removed_count} stale reservations")
                    else:
                        print(f"[ERROR] [imap.cleanup] Failed to write back cleaned file")
                
                _release_email_lock(lock_fd, lock_file_obj)
                return removed_count
            except (IOError, OSError):
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
            finally:
                if lock_acquired:
                    _release_email_lock(lock_fd, lock_file_obj)
    
    return 0


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
                reserved_entries = [] # Full strings
                if os.path.exists(RESERVED_EMAILS_FILE):
                    try:
                        with open(RESERVED_EMAILS_FILE, 'r', encoding='utf-8-sig', errors='replace') as f:
                            for line in f:
                                line = line.strip().lower()
                                if not line: continue
                                reserved_entries.append(line)
                                # Extract email part if timestamp exists
                                email_only = line.split('|', 1)[0] if '|' in line else line
                                reserved_emails.add(email_only)
                    except Exception as e:
                        print(f"[WARN] [imap._reserve_email] Failed to read reserved file: {e}")
                
                # Check if already reserved
                if email_lower in reserved_emails:
                    print(f"[DEBUG] [imap._reserve_email] Email {email} already reserved")
                    _release_email_lock(lock_fd, lock_file_obj)
                    return False
                
                # Add to reserved list with timestamp (use original entries + new one)
                reserved_entries.append(f"{email_lower}|{time.time()}")
                
                # Write back ROBUSTLY
                if _safe_write_lines(RESERVED_EMAILS_FILE, sorted(list(set(reserved_entries)))):
                    print(f"[DEBUG] [imap._reserve_email] Reserved email: {email}")
                    _release_email_lock(lock_fd, lock_file_obj)
                    return True
                else:
                    _release_email_lock(lock_fd, lock_file_obj)
                    return False
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
        reserved_entries = []
        if os.path.exists(RESERVED_EMAILS_FILE):
            try:
                with open(RESERVED_EMAILS_FILE, 'r', encoding='utf-8-sig', errors='replace') as f:
                    for line in f:
                        line = line.strip().lower()
                        if not line: continue
                        reserved_entries.append(line)
                        email_only = line.split('|', 1)[0] if '|' in line else line
                        reserved_emails.add(email_only)
            except Exception as e:
                print(f"[WARN] [imap._reserve_email_atomic] Failed to read reserved file: {e}")
                return False
        
        # Check if already reserved or used
        if email_lower in reserved_emails:
            print(f"[DEBUG] [imap._reserve_email_atomic] Email {email} already in reserved_emails.txt")
            return False
        
        # Also check if it's in used_emails.txt
        if _is_email_used_internal(email_lower):
            print(f"[DEBUG] [imap._reserve_email_atomic] Email {email} already in used_emails.txt")
            return False
        
        # Add to reserved list with timestamp
        reserved_entries.append(f"{email_lower}|{time.time()}")
        
        # Write back ROBUSTLY
        if _safe_write_lines(RESERVED_EMAILS_FILE, sorted(list(set(reserved_entries)))):
            print(f"[DEBUG] [imap._reserve_email_atomic] Successfully reserved email: {email} (total reserved now: {len(reserved_entries)})")
            return True
        else:
            return False
    except Exception as e:
        print(f"[ERROR] [imap._reserve_email_atomic] Failed to reserve email: {e}")
        return False


def _is_email_used_internal(email_lower: str) -> bool:
    """
    Internal function to check if email is used (without checking reserved_emails.txt).
    Used when we already have the lock and want to check only used_emails.txt.
    Matches primarily based on sequence number.
    """
    user_id = os.environ.get("USER_ID")
    
    # Extract number from candidate email
    candidate_num = None
    match = re.search(r'flipkart(\d+)@', email_lower)
    if match:
        candidate_num = int(match.group(1))

    # Helper to check number match or string match
    def is_match(line, target_email, target_num):
        line = line.strip().lower()
        if not line: return False
        if line == target_email: return True
        # Check number match
        if target_num is not None:
            m = re.search(r'flipkart(\d+)@', line)
            if m and int(m.group(1)) == target_num:
                return True
        return False

    # Check per-user file
    if user_id:
        try:
            per_user_path = REPORTS_DIR / f"used_emails_user{user_id}.txt"
            if per_user_path.exists():
                with open(per_user_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                    for line in f:
                        if is_match(line, email_lower, candidate_num):
                            return True
        except Exception as e:
            print(f"[WARN] [imap._is_email_used_internal] Error checking per-user file: {e}")
    
    # Check global file
    try:
        global_path = REPORTS_DIR / "used_emails.txt"
        if global_path.exists():
            with open(global_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                for line in f:
                    if is_match(line, email_lower, candidate_num):
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
                    # Release lock and return
                    _release_email_lock(lock_fd, lock_file_obj)
                    return
                
                # Read existing reserved emails with retry for file access
                reserved_entries = []
                read_success = False
                for read_attempt in range(5):
                    try:
                        with open(RESERVED_EMAILS_FILE, 'r', encoding='utf-8-sig', errors='replace') as f:
                            for line in f:
                                line = line.strip()
                                if line:
                                    reserved_entries.append(line)
                        read_success = True
                        break
                    except (IOError, OSError) as e:
                        print(f"[DEBUG] [imap._unreserve_email] Read attempt {read_attempt+1} failed: {e}")
                        time.sleep(0.05)
                
                if not read_success:
                    print(f"[WARN] [imap._unreserve_email] Could not read {RESERVED_EMAILS_FILE} after retries")
                    _release_email_lock(lock_fd, lock_file_obj)
                    return

                # Remove matching entries (email part)
                original_count = len(reserved_entries)
                # entry is "email|timestamp"
                new_entries = []
                for entry in reserved_entries:
                    if '|' in entry:
                        e_part = entry.split('|', 1)[0].strip().lower()
                    else:
                        e_part = entry.strip().lower()
                    
                    if e_part != email_lower:
                        new_entries.append(entry)
                
                if len(new_entries) < original_count:
                    # Write back ROBUSTLY
                    if _safe_write_lines(RESERVED_EMAILS_FILE, sorted(list(set(new_entries)))):
                         print(f"[DEBUG] [imap._unreserve_email] Successfully unreserved {email}")
                    else:
                        print(f"[WARN] [imap._unreserve_email] Failed to write back {RESERVED_EMAILS_FILE}")
                else:
                    print(f"[DEBUG] [imap._unreserve_email] Email {email} was not in reserved list")
                
                # Release lock
                _release_email_lock(lock_fd, lock_file_obj)
                return
            except Exception as e:
                # Release lock on error
                _release_email_lock(lock_fd, lock_file_obj)
                
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
    
    # helper to extract number
    def extract_number(line):
        # Extract number from patterns like "flipkart1@domain.com" or "admin+flipkart1@domain.com"
        # Match flipkart followed by digits
        match = re.search(r'flipkart(\d+)@', line.lower())
        if match:
            return int(match.group(1))
        return None

    # 1. Check per-user file
    if user_id:
        try:
            per_user_path = REPORTS_DIR / f"used_emails_user{user_id}.txt"
            if per_user_path.exists():
                with open(per_user_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                    for line in f:
                        line = line.strip()
                        if not line: continue
                        num = extract_number(line)
                        if num is not None:
                            used_numbers.add(num)
        except Exception as e:
            print(f"[WARN] [imap._find_all_missing_sequence_numbers] Error reading per-user file: {e}")
    
    # 2. Check global file (ALWAYS check this too, to ensure global uniqueness/sequence refilling)
    try:
        global_path = REPORTS_DIR / "used_emails.txt"
        if global_path.exists():
            with open(global_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    num = extract_number(line)
                    if num is not None:
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
                cfg = {}
                user_id = os.environ.get("USER_ID")
                
                # Priority: Try to load from Supabase first
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
                                            # PRIORITY 1: Check failed/remaining emails in use_first_mails.txt first
                                            failed_email = get_and_remove_failed_email()
                                            if failed_email:
                                                if _reserve_email_atomic(failed_email, lock_fd, lock_file_obj):
                                                    safe_print(f"[IMAP] [OK] PRIORITY 1: REUSING remaining mail from use_first_mails.txt: {failed_email}")
                                                    _release_email_lock(lock_fd, lock_file_obj)
                                                    return failed_email
                                            
                                            # PRIORITY 2: Check for missing sequence numbers in used_emails.txt
                                            missing_numbers = _find_all_missing_sequence_numbers(domain)
                                            if missing_numbers:
                                                for missing_num in missing_numbers:
                                                    missing_email = f"flipkart{missing_num}@{domain}"
                                                    if _reserve_email_atomic(missing_email, lock_fd, lock_file_obj):
                                                        print(f"[DEBUG] [imap.generate_flipkart_email] PRIORITY 2: Using missing sequence number: {missing_email}")
                                                        mark_email_success(missing_email)
                                                        _release_email_lock(lock_fd, lock_file_obj)
                                                        return missing_email
                                            
                                            # PRIORITY 3: Generate email using counter
                                            print(f"[DEBUG] [imap.generate_flipkart_email] PRIORITY 3: Using counter")
                                            for _ in range(100):
                                                counter = _get_next_counter()
                                                generated_email = f"flipkart{counter}@{domain}"
                                                if _reserve_email_atomic(generated_email, lock_fd, lock_file_obj):
                                                    print(f"[DEBUG] [imap.generate_flipkart_email] PRIORITY 3: Generated {generated_email}")
                                                    mark_email_success(generated_email)
                                                    _release_email_lock(lock_fd, lock_file_obj)
                                                    return generated_email
                            except Exception as e:
                                print(f"[DEBUG] [imap.generate_flipkart_email] Supabase load failed: {e}")
                    except ImportError:
                        pass
                
                # Fallback to local JSON config
                if not cfg or not cfg.get("email"):
                    cfg = load_imap_config()
                
                base_email = cfg.get("email", "")
                if "@" in base_email:
                    domain = base_email.split("@", 1)[1]
                    if domain and domain.strip():
                        # PRIORITY 1: Remaining/Failed pool
                        failed_email = get_and_remove_failed_email()
                        if failed_email:
                            if _reserve_email_atomic(failed_email, lock_fd, lock_file_obj):
                                safe_print(f"[IMAP] [OK] PRIORITY 1: REUSING {failed_email}")
                                _release_email_lock(lock_fd, lock_file_obj)
                                return failed_email
                        
                        # PRIORITY 2: Gaps
                        missing_numbers = _find_all_missing_sequence_numbers(domain)
                        if missing_numbers:
                            for missing_num in missing_numbers:
                                missing_email = f"flipkart{missing_num}@{domain}"
                                if _reserve_email_atomic(missing_email, lock_fd, lock_file_obj):
                                    mark_email_success(missing_email)
                                    _release_email_lock(lock_fd, lock_file_obj)
                                    return missing_email
                        
                        # PRIORITY 3: Counter
                        for _ in range(100):
                            counter = _get_next_counter()
                            generated_email = f"flipkart{counter}@{domain}"
                            if _reserve_email_atomic(generated_email, lock_fd, lock_file_obj):
                                mark_email_success(generated_email)
                                _release_email_lock(lock_fd, lock_file_obj)
                                return generated_email

                # If no email could be generated through any method
                _release_email_lock(lock_fd, lock_file_obj)
                raise Exception("Failed to generate unique email after checking all priorities and fallback methods")
                
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

