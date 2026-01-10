#!/usr/bin/env python
"""
add_user.py - Simple CLI helper to create users in Supabase.

Usage examples:

  python add_user.py --username admin --password yourpass --role admin --expiry-days 365

If any arguments are missing, you will be prompted interactively.
"""

import argparse
import getpass
import sys

from werkzeug.security import generate_password_hash

import neon_client as supabase_client


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Create a user in Supabase users table")
  parser.add_argument("--username", "-u", help="Username for the new user")
  parser.add_argument(
    "--password", "-p", help="Password for the new user (omit to be prompted securely)"
  )
  parser.add_argument(
    "--role",
    "-r",
    default="user",
    choices=["user", "admin"],
    help="Role for the new user (default: user)",
  )
  parser.add_argument(
    "--expiry-days",
    "-e",
    type=int,
    default=None,
    help="Number of days until expiry (optional)",
  )
  return parser.parse_args()


def main() -> None:
  if not supabase_client.is_enabled():
    print(
      "Supabase is not configured. Make sure SUPABASE_URL and SUPABASE_ANON_KEY are set "
      "or that supabase_client.py has the correct defaults."
    )
    sys.exit(1)

  args = parse_args()

  username = args.username or input("Username: ").strip()
  if not username:
    print("Username is required.")
    sys.exit(1)

  password = args.password or getpass.getpass("Password: ")
  if not password:
    print("Password is required.")
    sys.exit(1)

  role = args.role or "user"
  expiry_days = args.expiry_days

  password_hash = generate_password_hash(password)

  try:
    user_id = supabase_client.create_user(username, password_hash, role, expiry_days)
  except Exception as exc:
    print(f"Failed to create user in Supabase: {exc}")
    sys.exit(1)

  if not user_id:
    print("User creation returned no id; check Supabase logs or schema.")
    sys.exit(1)

  print(
    f"User created successfully in Supabase.\n"
    f"  id      : {user_id}\n"
    f"  username: {username}\n"
    f"  role    : {role}\n"
    f"  expiry  : {expiry_days} day(s) from today" if expiry_days else ""
  )


if __name__ == "__main__":
  main()

