"""Simple test to check Confluence connection."""

import requests
import os
from dotenv import load_dotenv

load_dotenv()

base_url = os.getenv("CONFLUENCE_BASE_URL")
username = os.getenv("CONFLUENCE_USERNAME")
password = os.getenv("CONFLUENCE_API_TOKEN")

if not base_url or not username or not password:
    print("[ERROR] Missing credentials in .env file")
    print("Required: CONFLUENCE_BASE_URL, CONFLUENCE_USERNAME, CONFLUENCE_API_TOKEN")
    exit(1)

base_url = base_url.rstrip("/")
print(f"Testing connection to: {base_url}")
print(f"Username: {username}")
print("-" * 40)

# Test 1: Check if server is reachable
try:
    response = requests.get(f"{base_url}/", timeout=5)
    print(f"[OK] Server is reachable (status: {response.status_code})")
except Exception as e:
    print(f"[ERROR] Cannot reach server: {e}")
    exit(1)

# Test 2: Try REST API with Basic Auth
try:
    from requests.auth import HTTPBasicAuth
    response = requests.get(
        f"{base_url}/rest/api/space?limit=5",
        auth=HTTPBasicAuth(username, password),
        timeout=10
    )
    if response.status_code == 200:
        data = response.json()
        print(f"[OK] Authentication successful!")
        print(f"[OK] Found {len(data.get('results', []))} spaces")
        if data.get('results'):
            print(f"  First space: {data['results'][0].get('name', 'N/A')}")
    else:
        print(f"[ERROR] Auth failed (status: {response.status_code})")
        print(f"  Response: {response.text[:200]}")
except Exception as e:
    print(f"[ERROR] API request failed: {e}")

print("-" * 40)
print("If all tests passed, run: docker-compose up")
