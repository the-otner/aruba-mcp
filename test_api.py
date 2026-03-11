import httpx
import os
from dotenv import load_dotenv

load_dotenv()

base_url = os.getenv("ARUBA_CENTRAL_BASE_URL")
token = os.getenv("ARUBA_CENTRAL_TOKEN")
client_id = os.getenv("ARUBA_CENTRAL_CLIENT_ID")
client_secret = os.getenv("ARUBA_CENTRAL_CLIENT_SECRET")
refresh_token = os.getenv("ARUBA_CENTRAL_REFRESH_TOKEN")

print(f"BASE_URL: {base_url}")
print(f"Token: {token[:20]}...")
print()

# Test 1: Try refreshing token first
print("=" * 60)
print("TEST 1: Refreshing access token...")
print("=" * 60)
try:
    r = httpx.post(
        base_url + "/oauth2/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15
    )
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text[:300]}")

    if r.status_code == 200:
        new_token = r.json().get("access_token", "")
        print(f"\nNEW TOKEN: {new_token[:20]}...")
        token = new_token
    print()
except Exception as e:
    print(f"Error: {e}\n")

# Test 2: Try multiple endpoints with the token
print("=" * 60)
print("TEST 2: Testing API endpoints...")
print("=" * 60)
endpoints = [
    ("Device Inventory", "/platform/device_inventory/v1/devices"),
    ("Groups", "/configuration/v2/groups"),
    ("Sites", "/central/v2/sites"),
    ("Subscription Keys", "/platform/licensing/v1/subscriptions"),
    ("Audit Logs", "/auditlogs/v1/logs"),
]

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

for name, path in endpoints:
    try:
        r = httpx.get(
            base_url + path,
            headers=headers,
            params={"limit": 1},
            timeout=15
        )
        status = r.status_code
        body = r.text[:200]
        marker = " <<<< WORKING!" if status == 200 else ""
        print(f"\n  {name}:")
        print(f"    URL: {base_url}{path}")
        print(f"    Status: {status}{marker}")
        print(f"    Response: {body}")
    except Exception as e:
        print(f"\n  {name}: Error - {str(e)[:80]}")

print("\n" + "=" * 60)
print("DONE")
print("=" * 60)