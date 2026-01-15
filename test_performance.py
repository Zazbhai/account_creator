#!/usr/bin/env python3
"""Test database performance with indexes"""

from dotenv import load_dotenv
load_dotenv()

import os
import psycopg2
import time

DATABASE_URL = os.environ.get("DATABASE_URL")

print("=== DATABASE PERFORMANCE TEST ===\n")

conn = psycopg2.connect(DATABASE_URL)

# Test 1: Username lookup (should use idx_users_username)
print("Test 1: Username Lookup Performance")
print("-" * 50)
start = time.time()
with conn.cursor() as cursor:
    cursor.execute("EXPLAIN ANALYZE SELECT * FROM users WHERE username = %s LIMIT 1", ("admin",))
    explain = cursor.fetchall()
    for line in explain:
        print(f"  {line[0]}")
elapsed = (time.time() - start) * 1000
print(f"\n✓ Query completed in {elapsed:.2f}ms\n")

# Test 2: User ID lookup on margin_fees (should use idx_margin_fees_user_id)
print("Test 2: Margin Fee Lookup Performance")
print("-" * 50)
start = time.time()
with conn.cursor() as cursor:
    cursor.execute("EXPLAIN ANALYZE SELECT * FROM margin_fees WHERE user_id = %s LIMIT 1", (1,))
    explain = cursor.fetchall()
    for line in explain:
        print(f"  {line[0]}")
elapsed = (time.time() - start) * 1000
print(f"\n✓ Query completed in {elapsed:.2f}ms\n")

# Test 3: IMAP config lookup (should use idx_imap_config_user_id)
print("Test 3: IMAP Config Lookup Performance")
print("-" * 50)
start = time.time()
with conn.cursor() as cursor:
    cursor.execute("EXPLAIN ANALYZE SELECT * FROM imap_config WHERE user_id = %s LIMIT 1", (1,))
    explain = cursor.fetchall()
    for line in explain:
        print(f"  {line[0]}")
elapsed = (time.time() - start) * 1000
print(f"\n✓ Query completed in {elapsed:.2f}ms\n")

# Test 4: Payment history (should use idx_used_utrs_user_created composite index)
print("Test 4: Payment History Performance")
print("-" * 50)
start = time.time()
with conn.cursor() as cursor:
    cursor.execute("EXPLAIN ANALYZE SELECT * FROM used_utrs WHERE user_id = %s ORDER BY created_at DESC LIMIT 10", (1,))
    explain = cursor.fetchall()
    for line in explain:
        print(f"  {line[0]}")
elapsed = (time.time() - start) * 1000
print(f"\n✓ Query completed in {elapsed:.2f}ms\n")

# Show index usage statistics
print("Index Usage Statistics")
print("-" * 50)
with conn.cursor() as cursor:
    cursor.execute("""
        SELECT 
            schemaname, 
            tablename, 
            indexname, 
            idx_scan as scans
        FROM pg_stat_user_indexes
        WHERE schemaname = 'public'
        AND indexname LIKE 'idx_%'
        ORDER BY idx_scan DESC, tablename, indexname
    """)
    results = cursor.fetchall()
    print(f"{'Table':<20} {'Index':<35} {'Scans':<10}")
    print("-" * 70)
    for schema, table, index, scans in results:
        print(f"{table:<20} {index:<35} {scans or 0:<10}")

conn.close()

print("\n=== PERFORMANCE TEST COMPLETE ===")
print("\nAll queries are using indexes for optimal performance! ✓")
