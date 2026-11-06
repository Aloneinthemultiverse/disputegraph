"""Day-1 Sandbox spike: order -> buyer approval -> capture -> INR dispute.

Every raw API response is saved to data/raw/ so we can see the real ID links.

Usage:
  python scripts/sandbox_spike.py order            # create order, prints approve link
  python scripts/sandbox_spike.py capture ORDER_ID # after approving as sandbox buyer
  python scripts/sandbox_spike.py dispute CAPTURE_ID BUYER_PAYER_ID
  python scripts/sandbox_spike.py list             # list merchant disputes
  python scripts/sandbox_spike.py show DISPUTE_ID
"""
import base64
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)
load_dotenv(ROOT / ".env")

BASE = os.environ.get("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")
CLIENT_ID = os.environ["PAYPAL_CLIENT_ID"]
SECRET = os.environ["PAYPAL_CLIENT_SECRET"]


def token() -> str:
    r = requests.post(f"{BASE}/v1/oauth2/token", auth=(CLIENT_ID, SECRET),
                      data={"grant_type": "client_credentials"}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def save(name: str, resp: requests.Response) -> dict:
    try:
        body = resp.json()
    except ValueError:
        body = {"_text": resp.text}
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = RAW / f"{stamp}_{name}.json"
    path.write_text(json.dumps({"status": resp.status_code, "url": resp.url, "body": body},
                               indent=2), encoding="utf-8")
    print(f"[{resp.status_code}] saved {path.relative_to(ROOT)}")
    if resp.status_code >= 400:
        print(json.dumps(body, indent=2))
    return body


def headers(extra: dict = None) -> dict:
    h = {"Authorization": f"Bearer {token()}", "Content-Type": "application/json",
         "PayPal-Request-Id": str(uuid.uuid4())}
    h.update(extra or {})
    return h


def create_order():
    invoice = f"INV-{uuid.uuid4().hex[:8].upper()}"
    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": "A123",
            "invoice_id": invoice,      # bridge key to merchant records
            "custom_id": "ORDER-A123",
            "description": "Laptop (SYNTHETIC demo order)",
            "amount": {"currency_code": "USD", "value": "750.00"},
        }],
        "payment_source": {"paypal": {"experience_context": {
            "return_url": "https://example.com/return",
            "cancel_url": "https://example.com/cancel"}}},
    }
    data = save("order_create", requests.post(f"{BASE}/v2/checkout/orders", headers=headers(),
                                              json=body, timeout=30))
    for link in data.get("links", []):
        if link["rel"] in ("payer-action", "approve"):
            print(f"\nOrder {data['id']} (invoice {invoice})")
            print(f"Log in as the SANDBOX BUYER and approve:\n  {link['href']}")
            print(f"Then run: python scripts/sandbox_spike.py capture {data['id']}")


def capture(order_id: str):
    data = save("order_capture", requests.post(
        f"{BASE}/v2/checkout/orders/{order_id}/capture", headers=headers(), timeout=30))
    save("order_get", requests.get(f"{BASE}/v2/checkout/orders/{order_id}",
                                   headers=headers(), timeout=30))
    try:
        cap = data["purchase_units"][0]["payments"]["captures"][0]
        payer = data["payer"]["payer_id"]
        print(f"\nCapture {cap['id']} status {cap['status']}  buyer payer_id {payer}")
        save("capture_get", requests.get(f"{BASE}/v2/payments/captures/{cap['id']}",
                                         headers=headers(), timeout=30))
        print(f"Then run: python scripts/sandbox_spike.py dispute {cap['id']} {payer}")
    except (KeyError, IndexError):
        print("Could not find capture in response (see saved JSON).")


def buyer_assertion(payer_id: str) -> str:
    """Unsigned JWT acting on behalf of the buyer (sandbox dispute creation)."""
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'none'})}.{enc({'iss': CLIENT_ID, 'payer_id': payer_id})}."


def create_dispute(capture_id: str, payer_id: str):
    body = {
        "disputed_transactions": [{"buyer_transaction_id": capture_id}],
        "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
        "dispute_amount": {"currency_code": "USD", "value": "750.00"},
        "extensions": {"buyer_contacted_time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")},
        "messages": [{"content": "I never received the laptop. (SYNTHETIC)"}],
    }
    save("dispute_create", requests.post(
        f"{BASE}/v1/customer/disputes", json=body, timeout=30,
        headers=headers({"PayPal-Auth-Assertion": buyer_assertion(payer_id)})))


def list_disputes():
    data = save("dispute_list", requests.get(f"{BASE}/v1/customer/disputes",
                                             headers=headers(), timeout=30))
    for d in data.get("items", []):
        print(d.get("dispute_id"), d.get("reason"), d.get("status"), d.get("dispute_amount"))


def show_dispute(dispute_id: str):
    save("dispute_get", requests.get(f"{BASE}/v1/customer/disputes/{dispute_id}",
                                     headers=headers(), timeout=30))


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["help"]
    {"order": create_order, "capture": capture, "dispute": create_dispute,
     "list": list_disputes, "show": show_dispute}.get(cmd, lambda *a: print(__doc__))(*args)
