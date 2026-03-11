import httpx
import os
from dotenv import load_dotenv

load_dotenv()

base = os.getenv("ARUBA_CENTRAL_BASE_URL")
token = os.getenv("ARUBA_CENTRAL_TOKEN")
client_id = os.getenv("ARUBA_CENTRAL_CLIENT_ID")
client_secret = os.getenv("ARUBA_CENTRAL_CLIENT_SECRET")
refresh_token = os.getenv("ARUBA_CENTRAL_REFRESH_TOKEN")

# Refresh token first
print("Refreshing token...")
r = httpx.post(
    base + "/oauth2/token",
    data={
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    },
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    timeout=15
)
if r.status_code == 200:
    token = r.json()["access_token"]
    print(f"New token: {token[:15]}...")
else:
    print(f"Refresh failed: {r.status_code}")

headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Test endpoints
endpoints = [
    ("Sites (v2)",          "/central/v2/sites",                          {"limit": 5, "offset": 0}),
    ("Monitoring Devices",  "/monitoring/v1/devices",                     {"limit": 5, "offset": 0}),
    ("Monitoring APs (v2)", "/monitoring/v2/aps",                         {"limit": 5, "offset": 0}),
    ("Monitoring APs (v1)", "/monitoring/v1/aps",                         {"limit": 5, "offset": 0}),
    ("Switches",            "/monitoring/v1/switches",                    {"limit": 5, "offset": 0}),
    ("Gateways",            "/monitoring/v1/gateways",                    {"limit": 5, "offset": 0}),
    ("Inventory (v1)",      "/platform/device_inventory/v1/devices",      {"limit": 5}),
    ("Groups",              "/configuration/v2/groups",                   {"limit": 5, "offset": 0}),
    ("Subscriptions",       "/platform/licensing/v1/subscriptions",       {}),
    ("Wireless Clients",    "/monitoring/v1/clients/wireless",            {"limit": 5, "offset": 0}),
]

print("\n" + "=" * 70)
for name, path, params in endpoints:
    try:
        r = httpx.get(base + path, params=params, headers=headers, timeout=15)
        marker = " <<<< WORKS!" if r.status_code == 200 else ""
        print(f"  {name:25} {r.status_code}{marker}")
        if r.status_code == 200:
            print(f"    {r.text[:150]}")
        else:
            print(f"    {r.text[:150]}")
    except Exception as e:
        print(f"  {name:25} ERROR: {str(e)[:60]}")
print("=" * 70)