"""Evidence package: turn a finished investigation into a PayPal
provide-evidence request. Only verified (MATCH) facts go in; anything still
contradicted or missing blocks submission. A human must approve; nothing is
sent automatically.
"""
from __future__ import annotations

import json
import os

import requests

from .paypal import PayPal


def build(inv: dict) -> dict:
    by = lambda check: [x for x in inv["findings"] if x["check"] == check]
    blockers = [x["note"] for x in inv["findings"]
                if x["check"] == "delivery" and x["verdict"] != "MATCH"]
    warnings = [x["note"] for x in inv["findings"]
                if x["verdict"] in ("VALUE_MISMATCH", "TIME_MISMATCH", "CONTRADICTION")
                and x["check"] != "delivery"]

    facts = [m for x in by("delivery") for m in x["merchant"]]
    tracking = inv.get("tracking")
    carrier = inv.get("carrier") or "OTHER"
    delivered = next((m for m in facts if str(m["value"]).lower().startswith("delivered")
                      and "courier" in m["entity"]), None)

    lines = [f"Invoice {inv['invoice_id']}, {inv['amount']} {inv['currency']}."]
    for x in inv["findings"]:
        if x["verdict"] == "MATCH" and x["check"] in ("delivery", "ship_to", "id:invoice_id", "timeline"):
            cite = (x["merchant"] or x["paypal"])[0]["source"]
            lines.append(f"- {x['note']} [{cite['ref']} {cite['pointer']}]")
    if delivered:
        lines.append(f"- Carrier delivery scan: {delivered['value']} at {delivered.get('observed_at')}.")

    evidence = {"evidence_type": "PROOF_OF_FULFILLMENT",
                "evidence_info": {"tracking_info": [{"carrier_name": carrier.upper(),
                                                     "tracking_number": tracking}]},
                "notes": "\n".join(lines)[:2000]}
    return {"dispute_id": inv["dispute_id"], "ready": not blockers and bool(tracking),
            "blockers": blockers + ([] if tracking else ["no tracking number"]),
            "warnings": warnings, "request": {"evidences": [evidence]}}


def submit(pkg: dict, approved_by: str) -> dict:
    if not pkg["ready"]:
        return {"submitted": False, "reason": "blocked", "blockers": pkg["blockers"]}
    path = f"/v1/customer/disputes/{pkg['dispute_id']}/provide-evidence"
    if os.environ.get("DEMO_MODE") == "1":
        return {"submitted": False, "dry_run": True, "path": path,
                "reason": "DEMO_MODE: request shown, not sent", "approved_by": approved_by}
    pp = PayPal()
    r = requests.post(f"{pp.base}{path}", timeout=30,
                      headers={"Authorization": f"Bearer {pp._auth()}"},
                      files={"input": (None, json.dumps(pkg["request"]), "application/json")})
    try:
        body = r.json()
    except ValueError:
        body = {"_text": r.text}
    return {"submitted": r.ok, "status": r.status_code, "path": path,
            "approved_by": approved_by, "response": body}
