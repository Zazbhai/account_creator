#!/usr/bin/env python3
"""Test saving API settings to Neon database"""

from dotenv import load_dotenv
load_dotenv()

import neon_client as supabase_client

print("=== TESTING API SETTINGS SAVE ===\n")

# Test data
test_settings = {
    "base_url": "https://api.temporasms.com",
    "service": "temporasms",
    "operator": "any",
    "country": "91",
    "default_price": 6.99,
    "wait_for_otp": 5,
    "wait_for_second_otp": 5
}

print("1. Current API settings in database:")
current = supabase_client.get_api_settings()
if current:
    print(f"   Found: {current}")
else:
    print("   None found")

print("\n2. Saving test API settings to database...")
try:
    supabase_client.upsert_api_settings(test_settings)
    print("   ✓ Save successful!")
except Exception as e:
    print(f"   ✗ Save failed: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

print("\n3. Verifying saved data...")
saved = supabase_client.get_api_settings()
if saved:
    print(f"   ✓ Data retrieved from database:")
    print(f"     - Base URL: {saved.get('base_url')}")
    print(f"     - Service: {saved.get('service')}")
    print(f"     - Operator: {saved.get('operator')}")
    print(f"     - Country: {saved.get('country')}")
    print(f"     - Default Price: {saved.get('default_price')}")
else:
    print("   ✗ Failed to retrieve saved data!")

print("\n=== DATABASE SAVE TEST COMPLETE ===")
