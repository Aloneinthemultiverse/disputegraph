"""Seed SYNTHETIC demo disputes so every verdict type shows up in the demo.

These are NOT real PayPal records. They copy the shape of the real sandbox
responses (see data/cache/ for the one real dispute) and use IDs starting
with PP-D-DEMO / DEMO so they can never be confused with sandbox data.

Run:  python scripts/seed_demo.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.disputegraph.paypal import CACHE, PayPal  # noqa: E402

MERCHANT = ROOT / "data" / "merchant"
TAG = "SYNTHETIC DEMO DOCUMENT - not a real record"

CASES = [
    {   # delivery claimed, but no carrier record at all -> UNSUPPORTED_CLAIM
        "n": "0002", "item": "Wireless headphones", "amount": "129.99", "day": "2026-10-20",
        "due": "2026-11-10T10:00:00Z", "refund": None,
        "docs": {
            "invoice": "Invoice No: INV-DEMO0002\nOrder Ref: ORDER-B0002\nInvoice Date: 2026-10-20\n"
                       "Bill To / Ship To: Ana Ruiz, 18 Pine Ave, Austin, TX 78701\nTotal Due: USD 129.99",
            "order_sheet": "Order Ref: ORDER-B0002\nInvoice No: INV-DEMO0002\nOrder Total: USD 129.99\n"
                           "Status: Delivered\nCarrier: USPS\nTracking: 9400111899223344556677\nShipped: 2026-10-21",
            "emails": "Date: 2026-10-30\nSubject: Re: headphones not here\n\n"
                      "Hi Ana, the package was delivered on Oct 24, please check your mailbox.",
        }},
    {   # shipped before payment captured + fuzzy "left it on your porch" -> TIME_MISMATCH, LLM claim
        "n": "0003", "item": "Running shoes", "amount": "89.00", "day": "2026-10-25",
        "due": "2026-11-15T10:00:00Z", "refund": None,
        "docs": {
            "invoice": "Invoice No: INV-DEMO0003\nOrder Ref: ORDER-C0003\nInvoice Date: 2026-10-25\n"
                       "Bill To / Ship To: Lee Park, 77 Oak St, Portland, OR 97205\nTotal Due: USD 89.00",
            "order_sheet": "Order Ref: ORDER-C0003\nInvoice No: INV-DEMO0003\nOrder Total: USD 89.00\n"
                           "Status: Shipped\nCarrier: FedEx\nTracking: 771234567890\nShipped: 2026-10-23",
            "courier_tracking": "Tracking: 771234567890\nShip To: PORTLAND, OR 97205\n\nScan history:\n"
                                "2026-10-23 16:00  Picked Up\n2026-10-26 11:20  Delivered - Porch\n"
                                "Current Status: Delivered",
            "emails": "Date: 2026-10-27\nSubject: Re: shoes\n\nHi Lee, our driver left them on your porch on Monday.",
        }},
    {   # everything lines up -> ready to send
        "n": "0004", "item": "Mirrorless camera", "amount": "420.00", "day": "2026-10-28",
        "due": "2026-11-18T10:00:00Z", "refund": None,
        "docs": {
            "invoice": "Invoice No: INV-DEMO0004\nOrder Ref: ORDER-D0004\nInvoice Date: 2026-10-28\n"
                       "Bill To / Ship To: Sam Okafor, 5 Bay Rd, Seattle, WA 98101\nTotal Due: USD 420.00",
            "order_sheet": "Order Ref: ORDER-D0004\nInvoice No: INV-DEMO0004\nOrder Total: USD 420.00\n"
                           "Status: Delivered\nCarrier: UPS\nTracking: 1Z888BB20234567890\nShipped: 2026-10-28",
            "courier_tracking": "Tracking: 1Z888BB20234567890\nShip To: SEATTLE, WA 98101\n\nScan history:\n"
                                "2026-10-28 17:30  Origin Scan\n2026-10-30 13:05  Delivered - Signed: OKAFOR\n"
                                "Current Status: Delivered",
            "emails": "Date: 2026-10-28\nSubject: Your order shipped\n\nHi Sam, your camera shipped today with UPS.",
        }},
    {   # merchant says refunded, PayPal shows no refund -> refund sweep catches it
        "n": "0005", "item": "Desk lamp", "amount": "45.50", "day": "2026-10-29",
        "due": "2026-11-19T10:00:00Z", "refund": None,
        "docs": {
            "invoice": "Invoice No: INV-DEMO0005\nOrder Ref: ORDER-E0005\nInvoice Date: 2026-10-29\n"
                       "Bill To / Ship To: Priya Nair, 9 Elm Ct, Denver, CO 80202\nTotal Due: USD 45.50",
            "order_sheet": "Order Ref: ORDER-E0005\nInvoice No: INV-DEMO0005\nOrder Total: USD 45.50\n"
                           "Status: Cancelled\nShipped: no",
            "emails": "Date: 2026-11-01\nSubject: Re: cancel my lamp order\n\n"
                      "Hi Priya, sorry about that. You have been refunded in full.",
        }},
]


def write(path: str, body: dict):
    PayPal._key(path).write_text(json.dumps(body, indent=2), encoding="utf-8")


def seed():
    CACHE.mkdir(parents=True, exist_ok=True)
    for c in CASES:
        n, amt, day = c["n"], c["amount"], c["day"]
        inv, cus = f"INV-DEMO{n}", c["docs"]["invoice"].split("Order Ref: ")[1].split("\n")[0]
        did, cap, order = f"PP-D-DEMO-{n}", f"DEMOCAP{n}", f"DEMOORDER{n}"
        money = {"currency_code": "USD", "value": amt}
        write(f"/v1/customer/disputes/{did}", {
            "dispute_id": did, "create_time": f"{day}T12:00:00Z", "update_time": f"{day}T12:00:00Z",
            "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "status": "WAITING_FOR_SELLER_RESPONSE",
            "dispute_life_cycle_stage": "INQUIRY", "dispute_amount": money,
            "seller_response_due_date": c["due"],
            "messages": [{"posted_by": "BUYER", "time_posted": f"{day}T12:00:00Z",
                          "content": f"I never received the {c['item'].lower()}. (SYNTHETIC)"}],
            "disputed_transactions": [{"seller_transaction_id": cap, "buyer_transaction_id": f"BUY{n}",
                                       "invoice_number": inv, "custom": cus,
                                       "transaction_status": "COMPLETED"}],
            "links": [], "_synthetic": True})
        write(f"/v2/payments/captures/{cap}", {
            "id": cap, "status": "COMPLETED", "amount": money, "invoice_id": inv, "custom_id": cus,
            "create_time": f"{day}T09:00:00Z", "_synthetic": True,
            "links": [{"rel": "up", "href": f"https://api.sandbox.paypal.com/v2/checkout/orders/{order}"}]})
        addr = c["docs"]["invoice"].split("Ship To: ")[1].split("\n")[0].split(", ")
        write(f"/v2/checkout/orders/{order}", {
            "id": order, "status": "COMPLETED", "create_time": f"{day}T09:00:00Z", "_synthetic": True,
            "payer": {"payer_id": f"DEMOPAYER{n}"},
            "purchase_units": [{"invoice_id": inv, "custom_id": cus, "description": f"{c['item']} (SYNTHETIC)",
                                "shipping": {"address": {"address_line_1": addr[1], "admin_area_2": addr[2],
                                                         "admin_area_1": addr[3].split()[0],
                                                         "postal_code": addr[3].split()[1],
                                                         "country_code": "US"}},
                                "payments": {"captures": [{"id": cap}], "refunds": []}}]})
        folder = MERCHANT / inv
        folder.mkdir(parents=True, exist_ok=True)
        for name, text in c["docs"].items():
            (folder / f"{name}.md").write_text(f"{TAG}\n--- page 1 ---\n{text}\n", encoding="utf-8")
        print("seeded", did, inv)


if __name__ == "__main__":
    seed()
