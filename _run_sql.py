"""Load .env and execute SQL via Supabase pg-meta"""
import os
import sys
import httpx
import json
from dotenv import load_dotenv

# Find .env relative to this script's location
script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, '..', '.env')
load_dotenv(dotenv_path=dotenv_path)

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Missing Supabase env vars")
    sys.exit(1)

ref = SUPABASE_URL.split('https://')[1].split('.supabase.co')[0]

headers = {
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json',
    'Accept': 'application/json',
}

# Read SQL file path from args
sql_file = sys.argv[1] if len(sys.argv) > 1 else None
if sql_file:
    with open(sql_file) as f:
        sql = f.read()
else:
    sql = "SELECT 1 AS test"

# Try pg-meta endpoint
pg_meta_url = f'{SUPABASE_URL.rstrip("/")}/pg-meta/default/query'

print(f"Ref: {ref}")
print(f"Executing SQL from: {sql_file or 'inline query'}")
print(f"SQL length: {len(sql)} chars")

try:
    r = httpx.post(pg_meta_url, headers=headers, json={"query": sql}, timeout=30)
    print(f"Status: {r.status_code}")
    if r.status_code < 300:
        print("SUCCESS:", r.text[:500])
    else:
        print("FAIL:", r.text[:500])
except Exception as e:
    print(f"ERROR: {e}")
