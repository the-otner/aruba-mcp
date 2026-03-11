import httpx
import os
from dotenv import load_dotenv

load_dotenv()

token = os.getenv("ARUBA_CENTRAL_TOKEN")
current_url = os.getenv("ARUBA_CENTRAL_BASE_URL")

print(f"Current BASE_URL: {current_url}")
print(f"Token starts with: {token[:20]}..." if token else "Token: MISSING!")
print()

urls = [
    ("US-1", "https://app1-apigw.central.arubanetworks.com"),
    ("US-2", "https://apigw-prod2.central.arubanetworks.com"),
    ("US-WEST4", "https://apigw-uswest4.central.arubanetworks.com"),
    ("EU-1", "https://eu-apigw.central.arubanetworks.com"),
    ("EU-3", "https://apigw-eucentral3.central.arubanetworks.com"),
    ("APAC-1", "https://api-ap.central.arubanetworks.com"),
    ("APAC-EAST1", "https://apigw-apnortheast1.central.arubanetworks.com"),
    ("APAC-SOUTH1", "https://internal-apigw-apsouth1.central.arubanetworks.com"),
    ("Canada", "https://apigw-cacent1.central.arubanetworks.com"),
]

print("Testing all Aruba Central regions...")
print("-" * 80)

for name, url in urls:
    try:
        r = httpx.get(
            url + "/platform/device_inventory/v1/devices",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            params={"limit": 1},
            timeout=10
        )
        status = r.status_code
        marker = " <-- THIS ONE WORKS!" if status == 200 else ""
        print(f"  {name:15} Status: {status}{marker}")
    except httpx.ConnectError:
        print(f"  {name:15} DNS/Connection FAILED")
    except httpx.TimeoutException:
        print(f"  {name:15} TIMEOUT")
    except Exception as e:
        print(f"  {name:15} Error: {str(e)[:60]}")

print("-" * 80)
print("Done! Use the URL that shows 'THIS ONE WORKS' in your .env file.")