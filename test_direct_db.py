#!/usr/bin/env python3
"""Direct test of database save without connection pool"""

from dotenv import load_dotenv
load_dotenv()

import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL")

print("=== DIRECT DATABASE TEST ===\n")

# Test 1: Insert API settings
print("1. Inserting API settings...")
conn = psycopg2.connect(DATABASE_URL)
try:
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("""
            INSERT INTO api_settings (base_url, service, operator, country, default_price, wait_for_otp, wait_for_second_otp)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """, ("https://api.temporasms.com", "temporasms", "any", "91", 6.99, 5, 5))
        result = cursor.fetchone()
        conn.commit()
        print(f"   ✓ Saved successfully! ID: {result['id']}")
except Exception as e:
    conn.rollback()
    print(f"   ✗ Failed: {e}")
    import traceback
    traceback.print_exc()
finally:
    conn.close()

# Test 2: Retrieve API settings
print("\n2. Retrieving API settings...")
conn = psycopg2.connect(DATABASE_URL)
try:
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT * FROM api_settings LIMIT 1")
        result = cursor.fetchone()
        if result:
            print("   ✓ Retrieved successfully:")
            print(f"     - Base URL: {result['base_url']}")
            print(f"     - Service: {result['service']}")
            print(f"     - Country: {result['country']}")
        else:
            print("   ✗ No data found")
except Exception as e:
    print(f"   ✗ Failed: {e}")
finally:
    conn.close()

print("\n=== TEST COMPLETE ===")
