#!/usr/bin/env python3
"""Create database schema in Neon PostgreSQL"""

from dotenv import load_dotenv
load_dotenv()

import os
import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    print("ERROR: DATABASE_URL not found in environment!")
    exit(1)

print("=== CREATING NEON DATABASE SCHEMA ===\n")

# Read SQL schema file
with open("neon_schema.sql", "r") as f:
    schema_sql = f.read()

print("1. Connecting to Neon database...")
try:
    conn = psycopg2.connect(DATABASE_URL)
    print("   ✓ Connected successfully!")
except Exception as e:
    print(f"   ✗ Connection failed: {e}")
    exit(1)

print("\n2. Creating tables...")
try:
    with conn.cursor() as cursor:
        cursor.execute(schema_sql)
        conn.commit()
    print("   ✓ All tables created successfully!")
except Exception as e:
    print(f"   ✗ Failed to create tables: {e}")
    conn.rollback()
    import traceback
    traceback.print_exc()
    exit(1)
finally:
    conn.close()

print("\n3. Verifying tables...")
conn = psycopg2.connect(DATABASE_URL)
try:
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        tables = cursor.fetchall()
        print(f"   ✓ Found {len(tables)} tables:")
        for table in tables:
            print(f"     - {table[0]}")
except Exception as e:
    print(f"   ✗ Failed to verify: {e}")
finally:
    conn.close()

print("\n=== SCHEMA CREATION COMPLETE ===")
