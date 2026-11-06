"""Mini evaluation: DisputeGraph vs a single LLM reading the raw records.

20 SYNTHETIC cases are generated with a fixed seed. Each one plants zero or
more known problems, so the correct answer is known:

  amount_mismatch        merchant doc total differs from PayPal capture
  delivery_contradiction merchant claims delivered, carrier shows in transit
  delivery_unsupported   merchant claims delivered, no carrier record at all
  early_ship             merchant ship date is before PayPal captured payment
  false_refund_claim     merchant says refunded, PayPal shows no refund

DisputeGraph runs its normal extraction + reconciliation. The baseline gets
the PayPal JSON and the merchant documents as plain text and must return the
issue labels. The baseline needs LLM_BASE_URL / LLM_API_KEY / LLM_MODEL; if
they are not set it is skipped and only DisputeGraph is scored.

Run:  python eval/run_eval.py      -> prints a table, writes eval/results.json
"""
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")
from backend.disputegraph.llm import _chat  # noqa: E402
from backend.disputegraph.merchant import extract  # noqa: E402
from backend.disputegraph.model import Fact, Source  # noqa: E402
from backend.disputegraph.reconcile import reconcile  # noqa: E402

LABELS = ["amount_mismatch", "delivery_contradiction", "delivery_unsupported",
          "early_ship", "false_refund_claim"]
ITEMS = ["Laptop", "Headphones", "Camera", "Shoes", "Lamp", "Watch", "Backpack", "Monitor"]
CITIES = [("Austin", "TX", "78701"), ("Seattle", "WA", "98101"), ("Denver", "CO", "80202"),
          ("Portland", "OR", "97205"), ("San Jose", "CA", "95131")]


def make_case(i: int, rng: random.Random) -> dict:
    planted = set()
    if rng.random() < .3: planted.add("amount_mismatch")
    r = rng.random()
    if r < .25: planted.add("delivery_contradiction")
    elif r < .45: planted.add("delivery_unsupported")
    if rng.random() < .25: planted.add("early_ship")
    if rng.random() < .2: planted.add("false_refund_claim")
    amt = f"{rng.randint(20, 900)}.{rng.randint(0, 99):02d}"
    city, st, zp = rng.choice(CITIES)
    inv, day, cap_day = f"INV-EVAL{i:03d}", 10 + i % 15, f"2026-10-{10 + i % 15:02d}"
    ship_day = f"2026-10-{day - 2 if 'early_ship' in planted else day:02d}"
    sheet_amt = f"{float(amt) + rng.choice([5, 10, 25]):.2f}" if "amount_mismatch" in planted else amt
    trk = f"1Z{rng.randint(10**9, 10**10 - 1)}"
    item = rng.choice(ITEMS)
    docs = {
        "invoice": f"Invoice No: {inv}\nOrder Ref: ORD-{i:03d}\nBill To / Ship To: Buyer {i}, 1 Main St, "
                   f"{city}, {st} {zp}\nItem: {item}\nTotal Due: USD {amt}",
        "order_sheet": f"Order Ref: ORD-{i:03d}\nInvoice No: {inv}\nOrder Total: USD {sheet_amt}\n"
                       f"Status: {'Delivered' if planted & {'delivery_contradiction', 'delivery_unsupported'} else 'Shipped'}\n"
                       f"Carrier: UPS\nTracking: {trk}\nShipped: {ship_day}",
        "emails": f"Date: 2026-10-{day + 3:02d}\nSubject: Re: order\n\n"
                  + ("Hi, our records show your order was delivered.\n"
                     if planted & {"delivery_contradiction", "delivery_unsupported"} else "Hi, your order is on its way.\n")
                  + ("You have been refunded in full.\n" if "false_refund_claim" in planted else ""),
    }
    if "delivery_unsupported" not in planted:
        status = "In Transit" if "delivery_contradiction" in planted else "Delivered"
        scans = f"{ship_day} 18:00  Origin Scan\n" + (
            f"2026-10-{day + 2:02d} 14:00  Delivered - Front Door\n" if status == "Delivered" else "")
        docs["courier_tracking"] = (f"Tracking: {trk}\nShip To: {city.upper()}, {st} {zp}\n\nScan history:\n"
                                    f"{scans}Current Status: {status}")
    paypal = {"capture": {"id": f"CAP{i:03d}", "status": "COMPLETED", "invoice_id": inv,
                          "custom_id": f"ORD-{i:03d}", "amount": {"currency_code": "USD", "value": amt},
                          "create_time": f"{cap_day}T09:00:00Z"},
              "order": {"shipping": {"address": {"admin_area_2": city, "postal_code": zp}}, "refunds": []}}
    return {"id": i, "invoice": inv, "planted": sorted(planted), "docs": docs, "paypal": paypal}


def paypal_facts(c: dict) -> list[Fact]:
    cap, ref = c["paypal"]["capture"], f"/v2/payments/captures/{c['paypal']['capture']['id']}"
    mk = lambda e, f, v, p: Fact(entity=e, field=f, value=v, source=Source(side="paypal", ref=ref, pointer=p))
    return [mk(f"capture:{cap['id']}", "amount", cap["amount"]["value"], "/amount/value"),
            mk(f"capture:{cap['id']}", "invoice_id", cap["invoice_id"], "/invoice_id"),
            mk(f"capture:{cap['id']}", "custom_id", cap["custom_id"], "/custom_id"),
            mk(f"capture:{cap['id']}", "captured_at", cap["create_time"], "/create_time"),
            mk("order:X", "ship_to", c["paypal"]["order"]["shipping"]["address"], "/shipping/address")]


def disputegraph(c: dict) -> set:
    pages = [{"doc": d, "page": 1, "text": t} for d, t in c["docs"].items()]
    found = set()
    for f in reconcile(paypal_facts(c), extract(c["invoice"], pages)):
        if f.check == "amount" and f.verdict == "VALUE_MISMATCH": found.add("amount_mismatch")
        if f.check == "delivery" and f.verdict == "CONTRADICTION": found.add("delivery_contradiction")
        if f.check == "delivery" and f.verdict == "UNSUPPORTED_CLAIM": found.add("delivery_unsupported")
        if f.check == "timeline" and f.verdict == "TIME_MISMATCH": found.add("early_ship")
        if f.check == "refund" and f.verdict == "UNSUPPORTED_CLAIM": found.add("false_refund_claim")
    return found


BASE_SYS = ("You audit PayPal disputes. Compare the PayPal record with the merchant documents and "
            "return ONLY a JSON array of issue labels that apply, chosen from: " + ", ".join(LABELS) +
            ". Definitions: amount_mismatch = a merchant total differs from the PayPal amount; "
            "delivery_contradiction = merchant claims delivered but carrier record shows not delivered; "
            "delivery_unsupported = merchant claims delivered and there is no carrier record; "
            "early_ship = merchant ship date is before the PayPal capture date; "
            "false_refund_claim = merchant says refunded but PayPal shows no refund. Return [] if none.")


def baseline(c: dict) -> set | None:
    user = "PAYPAL RECORD:\n" + json.dumps(c["paypal"]) + "\n\nMERCHANT DOCUMENTS:\n" + \
           "\n\n".join(f"### {d}\n{t}" for d, t in c["docs"].items())
    text, src = _chat(BASE_SYS, user)
    if text is None:
        return None
    try:
        arr = json.loads(text[text.index("["): text.rindex("]") + 1])
        return {x for x in arr if x in LABELS}
    except ValueError:
        return set()


def score(rows, key):
    tp = fp = fn = exact = 0
    for r in rows:
        p, g = set(r[key]), set(r["planted"])
        tp += len(p & g); fp += len(p - g); fn += len(g - p); exact += p == g
    prec = tp / (tp + fp) if tp + fp else 1.0
    rec = tp / (tp + fn) if tp + fn else 1.0
    return {"precision": round(prec, 3), "recall": round(rec, 3), "false_alarms": fp,
            "missed": fn, "exact_cases": f"{exact}/{len(rows)}",
            "avg_ms": round(sum(r[key + "_ms"] for r in rows) / len(rows), 1)}


def main(n=20, seed=7):
    rng = random.Random(seed)
    rows, have_base = [], True
    for i in range(1, n + 1):
        c = make_case(i, rng)
        t = time.perf_counter(); dg = disputegraph(c); dg_ms = (time.perf_counter() - t) * 1000
        t = time.perf_counter(); b = baseline(c) if have_base else None; b_ms = (time.perf_counter() - t) * 1000
        if b is None: have_base = False
        rows.append({"id": i, "planted": c["planted"], "disputegraph": sorted(dg), "disputegraph_ms": dg_ms,
                     "baseline": sorted(b) if b is not None else None, "baseline_ms": b_ms})
    res = {"cases": n, "seed": seed, "disputegraph": score(rows, "disputegraph"),
           "baseline": score(rows, "baseline") if have_base else "skipped (no LLM key configured)",
           "rows": rows}
    (ROOT / "eval" / "results.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"{n} synthetic cases, {sum(len(r['planted']) for r in rows)} planted issues")
    print("DisputeGraph:", res["disputegraph"])
    print("Single LLM:  ", res["baseline"])


if __name__ == "__main__":
    main()
