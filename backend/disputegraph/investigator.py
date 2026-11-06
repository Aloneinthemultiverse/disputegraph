"""Reconciliation Investigator: run the pipeline, turn gaps into evidence
requests, accept new evidence, re-run (max MAX_ROUNDS), and log every step.

Pipeline per round:
  PayPal Analyst   -> PayPalGraph.from_dispute (API facts)
  Merchant Analyst -> merchant.extract (doc facts)
  Investigator     -> reconcile -> evidence requests + strength + status
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from .graph import PayPalGraph
from .llm import summarize
from .merchant import MERCHANT, extract
from .model import Fact
from .reconcile import Finding, reconcile

MAX_ROUNDS = 3
_AUDIT: dict[str, list[dict]] = {}
_ROUNDS: dict[str, int] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(dispute_id: str, agent: str, action: str, detail: str = ""):
    _AUDIT.setdefault(dispute_id, []).append(
        {"time": _now(), "agent": agent, "action": action, "detail": detail})


def _requests(findings: list[Finding], facts: list[Fact]) -> list[dict]:
    tracking = next((f.value for f in facts if f.field == "tracking"), None)
    out = []
    for fd in findings:
        if fd.check == "delivery" and fd.verdict != "MATCH":
            out.append({"check": "delivery", "priority": "high",
                        "ask": "Upload the carrier's proof of delivery (delivery scan)"
                               + (f" for tracking {tracking}" if tracking else "") + ".",
                        "why": fd.note})
        elif fd.check == "amount" and fd.verdict == "VALUE_MISMATCH":
            out.append({"check": "amount", "priority": "medium",
                        "ask": "Correct or explain the amount in "
                               f"{fd.merchant[0].entity.split(':')[1]} (e.g. shipping not charged).",
                        "why": fd.note})
        elif fd.check == "timeline" and fd.verdict == "TIME_MISMATCH":
            out.append({"check": "timeline", "priority": "medium",
                        "ask": "Explain why the ship date is before PayPal captured payment "
                               "(e.g. order sheet date typo, or pre-shipped on authorization).",
                        "why": fd.note})
        elif fd.check == "refund" and fd.verdict != "MATCH":
            out.append({"check": "refund", "priority": "low",
                        "ask": "Confirm whether you issued a refund, or if this is PayPal's dispute hold.",
                        "why": fd.note})
        elif fd.verdict in ("MISSING", "VALUE_MISMATCH") and fd.check.startswith(("ship_to", "id:")):
            out.append({"check": fd.check, "priority": "medium",
                        "ask": f"Provide a document that confirms {fd.check.replace('id:', '')}.",
                        "why": fd.note})
    return out


def _strength(findings: list[Finding], facts: list[Fact]) -> list[dict]:
    """INR evidence checklist (PayPal: proof of delivery with tracking, shipped
    to the address on the transaction)."""
    ok = lambda check: any(f.check == check and f.verdict == "MATCH" for f in findings)
    has = lambda field: any(f.field == field and f.source.side == "merchant" for f in facts)
    return [
        {"item": "Tracking number provided", "met": has("tracking")},
        {"item": "Carrier named", "met": has("carrier")},
        {"item": "Carrier confirms delivery", "met": ok("delivery")},
        {"item": "Shipped to PayPal address", "met": ok("ship_to")},
        {"item": "Amounts consistent with PayPal",
         "met": not any(f.check == "amount" and f.verdict != "MATCH" for f in findings)},
        {"item": "Buyer communication on file", "met": has("shipped_claim")},
    ]


def investigate(dispute_id: str) -> dict:
    t0 = time.perf_counter()
    log(dispute_id, "PayPal Analyst", "fetch", f"/v1/customer/disputes/{dispute_id} + linked capture/order")
    pg = PayPalGraph().from_dispute(dispute_id)
    inv = next(f.value for f in pg.facts if f.field == "invoice_id")
    m_facts = extract(inv)
    docs = sorted({f.source.ref for f in m_facts})
    log(dispute_id, "Merchant Evidence Analyst", "extract", f"{len(m_facts)} facts from {len(docs)} docs")
    findings = reconcile(pg.facts, m_facts)
    reqs = _requests(findings, pg.facts + m_facts)
    log(dispute_id, "Reconciliation Investigator", "reconcile",
        f"{len(findings)} findings, {len(reqs)} evidence requests")

    strength = _strength(findings, m_facts)
    rounds = _ROUNDS.get(dispute_id, 0)
    blocking = [f for f in findings if f.check == "delivery" and f.verdict != "MATCH"]
    status = ("READY_FOR_REVIEW" if not blocking else
              "ESCALATE_TO_HUMAN" if rounds >= MAX_ROUNDS else "NEEDS_EVIDENCE")
    get = lambda field: next((f.value for f in pg.facts if f.field == field), None)
    fds = [f.model_dump() for f in findings]
    summary = summarize(fds)
    log(dispute_id, "Summary Writer", "summarize", summary["source"])
    return {
        "elapsed_ms": round((time.perf_counter() - t0) * 1000),
        "summary": summary,
        "llm_facts": sum(1 for f in m_facts if f.method == "llm"),
        "dispute_id": dispute_id, "invoice_id": inv,
        "reason": get("reason"), "status_paypal": get("status"), "stage": get("stage"),
        "amount": get("amount"), "currency": get("currency"),
        "deadline": get("seller_response_due"),
        "tracking": next((f.value for f in m_facts if f.field == "tracking"), None),
        "carrier": next((f.value for f in m_facts if f.field == "carrier"), None),
        "status": status, "round": rounds, "max_rounds": MAX_ROUNDS,
        "findings": fds,
        "requests": reqs, "strength": strength,
        "graph": [{"from": u, "to": v, "rel": d["rel"]} for u, v, d in pg.g.edges(data=True)],
        "audit": _AUDIT.get(dispute_id, []),
    }


def add_evidence(dispute_id: str, invoice_id: str, name: str, text: str) -> str:
    """Save merchant-supplied evidence as a new doc and count a round."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "evidence"
    if "courier" in slug or "tracking" in slug or "carrier" in slug:
        slug = "courier_tracking_update"   # treated as a carrier record
    path = MERCHANT / invoice_id / f"uploaded_{slug}.md"
    if not text.lstrip().startswith("---"):
        text = "--- page 1 ---\n" + text
    path.write_text(text, encoding="utf-8")
    _ROUNDS[dispute_id] = _ROUNDS.get(dispute_id, 0) + 1
    log(dispute_id, "Merchant", "upload", path.name)
    return path.name


def reset(dispute_id: str, invoice_id: str):
    for p in (MERCHANT / invoice_id).glob("uploaded_*.md"):
        p.unlink()
    _ROUNDS.pop(dispute_id, None)
    _AUDIT.pop(dispute_id, None)
