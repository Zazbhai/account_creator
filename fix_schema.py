#!/usr/bin/env python3
"""Check and fix database schema"""

from dotenv import load_dotenv
load_dotenv()

import os
import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")

print("=== CHECKING DATABASE SCHEMA ===\n")

conn = psycopg2.connect(DATABASE_URL)

# Check current api_settings columns
print("1. Current api_settings columns:")
try:
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'api_settings'
            ORDER BY ordinal_position
        """)
        columns = cursor.fetchall()
        for col in columns:
            print(f"   - {col[0]} ({col[1]})")
except Exception as e:
    print(f"   ✗ Failed: {e}")

# Add missing columns if needed
print("\n2. Adding missing columns...")
try:
    with conn.cursor() as cursor:
        # Try to add each column (will fail silently if already exists)
        alterations = [
            "ALTER TABLE api_settings ADD COLUMN IF NOT EXISTS default_price NUMERIC(10, 2)",
            "ALTER TABLE api_settings ADD COLUMN IF NOT EXISTS wait_for_otp INTEGER",
            "ALTER TABLE api_settings ADD COLUMN IF NOT EXISTS wait_for_second_otp INTEGER"
        ]
        for sql in alterations:
            try:
                cursor.execute(sql)
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"   Note: {e}")
        print("   ✓ Schema updated")
except Exception as e:
    conn.rollback()
    print(f"   ✗ Failed: {e}")

# Check users table columns
print("\n3. Current users table columns:")
try:
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'users'
            ORDER BY ordinal_position
        """)
        columns = cursor.fetchall()
        for col in columns:
            print(f"   - {col[0]} ({col[1]})")
except Exception as e:
    print(f"   ✗ Failed: {e}")

# Add missing columns to users table
print("\n4. Adding missing columns to users table...")
try:
    with conn.cursor() as cursor:
        alterations = [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_balance NUMERIC(10, 2)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_capacity INTEGER",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_price NUMERIC(10, 2)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_balance NUMERIC(10, 2) DEFAULT 0.0"
        ]
        for sql in alterations:
            try:
                cursor.execute(sql)
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"   Note: {e}")
        print("   ✓ Users table updated")
except Exception as e:
    conn.rollback()
    print(f"   ✗ Failed: {e}")

conn.close()
print("\n=== SCHEMA CHECK COMPLETE ===")
