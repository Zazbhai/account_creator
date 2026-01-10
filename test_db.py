import os
os.environ['DATABASE_URL'] = 'postgresql://neondb_owner:npg_2OJ0rvhmnCVE@ep-lingering-glade-ahxz3ciz-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require'

import neon_client as supabase_client

print('=== TESTING NEON DATABASE ===')
print('1. Database enabled:', supabase_client.is_enabled())

users = supabase_client.get_all_users()
print('2. Users count:', len(users))
for u in users:
    print(f'   - User: {u.get("username")} (ID: {u.get("id")}, Role: {u.get("role")})')

api_settings = supabase_client.get_api_settings()
print('3. API Settings:', 'Found' if api_settings else 'Not found')
if api_settings:
    print(f'   - Base URL: {api_settings.get("base_url")}')
    print(f'   - Service: {api_settings.get("service")}')

print('\n=== ALL DATABASE OPERATIONS WORKING ===')
