#!/usr/bin/env python3
"""Test script to verify Paperclip connectivity from the dashboard's perspective."""
import os, sys, urllib.request, json

# Simulate exactly what app.py does
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

print(f"ENV_FILE: {ENV_FILE}")
print(f"Exists: {os.path.isfile(ENV_FILE)}")

# Load env file (new behavior: .env always wins)
with open(ENV_FILE, "r", encoding="utf-8-sig") as handle:
    for raw in handle:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            os.environ[key] = value.strip().strip('"').strip("'")

PAPERCLIP_URL = os.getenv("PAPERCLIP_API_URL", "http://localhost:3100")
COMPANY_ID = os.getenv("PAPERCLIP_COMPANY_ID", "856affb4-69f1-44cb-a690-e4c2e6b2769d")

print(f"PAPERCLIP_URL: {PAPERCLIP_URL}")
print(f"COMPANY_ID: {COMPANY_ID}")

# Test
url = f"{PAPERCLIP_URL}/api/companies/{COMPANY_ID}"
print(f"\nTesting: {url}")

try:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=3) as res:
        data = json.loads(res.read().decode("utf-8"))
        print(f"SUCCESS: {res.status} → {data.get('name', 'N/A')}")
except urllib.error.HTTPError as e:
    print(f"HTTP ERROR: {e.code}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")