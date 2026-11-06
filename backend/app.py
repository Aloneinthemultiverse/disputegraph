"""DisputeGraph API + static UI.

Run:  uvicorn backend.app:app --port 8000
Demo (no credentials): DEMO_MODE=1 uvicorn backend.app:app --port 8000
"""
from __future__ import annotations

import json
import os

import requests
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .disputegraph import investigator as inv
from .disputegraph import package
from .disputegraph.gate import ask
from .disputegraph.merchant import MERCHANT
from .disputegraph.paypal import CACHE, PayPal
from .disputegraph.reconcile import Finding

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "frontend"
app = FastAPI(title="DisputeGraph")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class Question(BaseModel):
    question: str


class Evidence(BaseModel):
    name: str
    text: str


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/disputes")
def disputes():
    out = []
    for p in sorted(CACHE.glob("v1_customer_disputes_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        out.append({"dispute_id": d["dispute_id"], "reason": d.get("reason"),
                    "status": d.get("status"), "amount": d["dispute_amount"]["value"],
                    "currency": d["dispute_amount"]["currency_code"],
                    "deadline": d.get("seller_response_due_date"),
                    "synthetic": bool(d.get("_synthetic"))})
    return sorted(out, key=lambda d: (d["synthetic"], d["dispute_id"]))  # real sandbox case first


@app.get("/api/disputes/{dispute_id}")
def investigate(dispute_id: str):
    try:
        return inv.investigate(dispute_id)
    except Exception as e:  # surface PayPal/cache errors to the UI
        raise HTTPException(404, f"cannot load {dispute_id}: {e}")


@app.post("/api/disputes/{dispute_id}/ask")
def ask_question(dispute_id: str, q: Question):
    result = inv.investigate(dispute_id)
    findings = [Finding(**f) for f in result["findings"]]
    inv.log(dispute_id, "User", "ask", q.question)
    return ask(q.question, findings)


@app.post("/api/disputes/{dispute_id}/evidence")
def add_evidence(dispute_id: str, ev: Evidence):
    invoice = inv.investigate(dispute_id)["invoice_id"]
    name = inv.add_evidence(dispute_id, invoice, ev.name, ev.text)
    return {"saved": name, "investigation": inv.investigate(dispute_id)}


@app.post("/api/disputes/{dispute_id}/reset")
def reset(dispute_id: str):
    inv.reset(dispute_id, inv.investigate(dispute_id)["invoice_id"])
    return {"ok": True}


class Approval(BaseModel):
    approved_by: str
    confirm: bool


@app.get("/api/disputes/{dispute_id}/package")
def package_preview(dispute_id: str):
    return package.build(inv.investigate(dispute_id))


@app.post("/api/disputes/{dispute_id}/submit")
def submit(dispute_id: str, a: Approval):
    if not a.confirm or not a.approved_by.strip():
        raise HTTPException(400, "human approval required")
    pkg = package.build(inv.investigate(dispute_id))
    res = package.submit(pkg, a.approved_by.strip())
    inv.log(dispute_id, a.approved_by.strip(), "approve+submit",
            "sent" if res.get("submitted") else res.get("reason", f"HTTP {res.get('status')}"))
    return res


@app.get("/api/sweep")
def refund_sweep():
    """Refund-mismatch sweep: catch 'merchant says refunded' vs PayPal (and the
    reverse) across every known case, before it turns into a lost dispute."""
    out = []
    for d in disputes():
        r = inv.investigate(d["dispute_id"])
        for f in r["findings"]:
            if f["check"] == "refund" and f["verdict"] != "MATCH":
                out.append({"dispute_id": d["dispute_id"], "invoice_id": r["invoice_id"],
                            "verdict": f["verdict"], "note": f["note"]})
    return out


@app.post("/api/webhooks/paypal")
async def paypal_webhook(req: Request):
    """CUSTOMER.DISPUTE.CREATED / UPDATED -> fetch + cache the dispute so the
    investigation starts on its own. Signature is verified with PayPal when
    PAYPAL_WEBHOOK_ID is set."""
    event = await req.json()
    wid = os.environ.get("PAYPAL_WEBHOOK_ID")
    if wid and os.environ.get("DEMO_MODE") != "1":
        h = req.headers
        pp = PayPal()
        v = requests.post(f"{pp.base}/v1/notifications/verify-webhook-signature", timeout=30,
                          headers={"Authorization": f"Bearer {pp._auth()}"},
                          json={"auth_algo": h.get("paypal-auth-algo"), "cert_url": h.get("paypal-cert-url"),
                                "transmission_id": h.get("paypal-transmission-id"),
                                "transmission_sig": h.get("paypal-transmission-sig"),
                                "transmission_time": h.get("paypal-transmission-time"),
                                "webhook_id": wid, "webhook_event": event}).json()
        if v.get("verification_status") != "SUCCESS":
            raise HTTPException(400, "webhook signature not verified")
    etype = event.get("event_type", "")
    did = (event.get("resource") or {}).get("dispute_id")
    if not etype.startswith("CUSTOMER.DISPUTE") or not did:
        return {"ignored": etype}
    if os.environ.get("DEMO_MODE") != "1":
        PayPal().get(f"/v1/customer/disputes/{did}")
    inv.log(did, "Webhook", etype, "investigation started")
    return {"accepted": did, "investigation": inv.investigate(did)["status"]}


@app.get("/api/source")
def source(ref: str, pointer: str = ""):
    """Click-through: show the exact API field or document page behind a fact."""
    if ref.startswith("/"):  # PayPal API path -> cached JSON, resolve pointer
        body = json.loads(PayPal._key(ref).read_text(encoding="utf-8"))
        node = body
        for part in [p for p in pointer.split("/") if p]:
            node = node[int(part)] if isinstance(node, list) else node.get(part)
        return {"side": "paypal", "ref": ref, "pointer": pointer, "value": node}
    path = (MERCHANT / ref).resolve()
    if MERCHANT.resolve() not in path.parents or not path.exists():
        raise HTTPException(404, "unknown document")
    return {"side": "merchant", "ref": ref, "pointer": pointer,
            "text": path.read_text(encoding="utf-8")}
