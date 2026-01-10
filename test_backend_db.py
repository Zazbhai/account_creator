#!/usr/bin/env python3
"""Test if the backend can connect to Neon database with current environment"""

# Load .env file first
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✓ Loaded .env file")
except ImportError:
    print("✗ python-dotenv not installed")

import os
import neon_client as supabase_client

print("\n=== ENVIRONMENT CHECK ===")
db_url = os.environ.get("DATABASE_URL", "")
if db_url:
    # Show masked version
    masked = db_url[:30] + "..." + db_url[-20:] if len(db_url) > 50 else db_url
    print(f"DATABASE_URL: {masked}")
else:
    print("DATABASE_URL: Not set!")

print("\n=== NEON CLIENT CHECK ===")
print(f"Database enabled: {supabase_client.is_enabled()}")

if supabase_client.is_enabled():
    try:
        users = supabase_client.get_all_users()
        print(f"✓ Successfully connected to Neon!")
        print(f"✓ Found {len(users)} users in database")
        for u in users:
            print(f"  - {u.get('username')} (ID: {u.get('id')}, Role: {u.get('role')})")
    except Exception as e:
        print(f"✗ Failed to fetch users: {e}")
        import traceback
        traceback.print_exc()
else:
    print("✗ Database not enabled - check DATABASE_URL in .env")

print("\n=== END ===")
