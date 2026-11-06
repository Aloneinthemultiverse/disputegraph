"""Reconciliation engine: compare PayPal facts with merchant facts.

Deterministic checks only (IDs, amounts, dates, tracking/delivery, ship-to,
refunds). Each check returns Findings with one of six verdicts and the exact
facts (with citations) on both sides. Missing != Contradiction: absence of
evidence is reported as a gap, never as proof the other side is wrong.
"""
from __future__ import annotations

import difflib
import re
from typing import Literal

from pydantic import BaseModel

from .model import Fact

Verdict = Literal["MATCH", "VALUE_MISMATCH", "TIME_MISMATCH", "MISSING",
                  "UNSUPPORTED_CLAIM", "CONTRADICTION"]

# Merchant docs that are third-party records vs the merchant's own claims.
RECORD_DOCS = {"merchant:courier_tracking", "merchant:uploaded_courier_tracking_update"}
CLAIM_DOCS = {"merchant:order_sheet", "merchant:emails"}


class Finding(BaseModel):
    check: str
    verdict: Verdict
    note: str
    paypal: list[Fact] = []
    merchant: list[Fact] = []


def _pick(facts, field, side=None, entity_prefix=""):
    return [f for f in facts if f.field == field
            and (side is None or f.source.side == side)
            and f.entity.startswith(entity_prefix)]


def check_ids(pp, mc) -> list[Finding]:
    out = []
    for field in ("invoice_id", "custom_id"):
        p = _pick(pp, field, entity_prefix="capture:") or _pick(pp, field)
        m = _pick(mc, field)
        if not p or not m:
            out.append(Finding(check=f"id:{field}", verdict="MISSING", paypal=p, merchant=m,
                               note=f"{field} absent on {'PayPal' if not p else 'merchant'} side"))
            continue
        bad = [f for f in m if f.value != p[0].value]
        out.append(Finding(
            check=f"id:{field}", verdict="VALUE_MISMATCH" if bad else "MATCH",
            paypal=p[:1], merchant=bad or m,
            note=(f"{len(bad)} merchant doc(s) disagree with PayPal {p[0].value}" if bad
                  else f"{p[0].value} matches across {len(m)} merchant doc(s)")))
    return out


def _money(v) -> float | None:
    try:
        x = float(str(v).replace(",", "").strip())
    except ValueError:
        return None
    return x if x == x and abs(x) < 1e12 else None  # no NaN / inf / absurd values


def check_amount(pp, mc) -> list[Finding]:
    p = _pick(pp, "amount", entity_prefix="capture:")
    m = _pick(mc, "amount")
    if not p or not m:
        return [Finding(check="amount", verdict="MISSING", paypal=p, merchant=m,
                        note="amount missing on one side")]
    pv = _money(p[0].value)
    if pv is None:
        return [Finding(check="amount", verdict="MISSING", paypal=p[:1], merchant=m,
                        note=f"PayPal amount '{p[0].value}' is unreadable")]
    out = []
    for f in m:
        mv = _money(f.value)
        if mv is None:  # damaged / hostile number: report, never crash or guess
            out.append(Finding(check="amount", verdict="MISSING", paypal=p[:1], merchant=[f],
                               note=f"merchant {f.entity.split(':')[1]} amount '{str(f.value)[:30]}' is unreadable"))
            continue
        ok = abs(mv - pv) < 0.005
        out.append(Finding(
            check="amount", verdict="MATCH" if ok else "VALUE_MISMATCH",
            paypal=p[:1], merchant=[f],
            note=(f"{f.value} matches PayPal capture" if ok else
                  f"merchant {f.entity.split(':')[1]} says {f.value}, PayPal captured {p[0].value}"
                  f" (diff {mv - pv:+.2f})")))
    return out


def check_delivery(pp, mc) -> list[Finding]:
    claims = [f for f in mc if f.field == "delivery_status" and f.entity in CLAIM_DOCS
              and "deliver" in str(f.value).lower()]
    records = [f for f in mc if f.entity in RECORD_DOCS
               and f.field in ("delivery_status", "delivery_scan", "scan")]
    tracking = _pick(mc, "tracking")
    if not tracking:
        return [Finding(check="delivery", verdict="MISSING", merchant=claims,
                        note="no tracking number in merchant evidence")]
    if not records:
        return [Finding(check="delivery", verdict="UNSUPPORTED_CLAIM" if claims else "MISSING",
                        merchant=claims + tracking,
                        note="no carrier record found for tracking "
                             f"{tracking[0].value}; delivery cannot be verified")]
    delivered = [r for r in records if r.field in ("delivery_status", "scan")
                 and str(r.value).lower().startswith("delivered")]
    status = [r for r in records if r.field in ("delivery_status", "delivery_scan")]
    if delivered:
        return [Finding(check="delivery", verdict="MATCH", merchant=claims + delivered,
                        note="carrier record confirms delivery")]
    if claims:
        return [Finding(check="delivery", verdict="CONTRADICTION", merchant=claims + status,
                        note="merchant says Delivered, but the carrier record shows "
                             f"'{status[0].value if status else 'no delivery scan'}'")]
    return [Finding(check="delivery", verdict="MISSING", merchant=status,
                    note="carrier record has no delivery scan")]


def check_timeline(pp, mc) -> list[Finding]:
    cap = _pick(pp, "captured_at")
    shipped = [s for s in _pick(mc, "shipped_at")
               if len(str(s.value)) == 10 and str(s.value)[4] == "-"]  # dates only ("Shipped: no" is not one)
    if not cap or not shipped:
        return [Finding(check="timeline", verdict="MISSING", paypal=cap, merchant=shipped,
                        note="capture time or ship date missing")]
    early = [s for s in shipped if s.value < cap[0].value[:10]]
    return [Finding(check="timeline", verdict="TIME_MISMATCH" if early else "MATCH",
                    paypal=cap[:1], merchant=early or shipped,
                    note=("shipped before PayPal captured payment" if early
                          else f"shipped {shipped[0].value}, on/after capture {cap[0].value[:10]}"))]


def check_ship_to(pp, mc) -> list[Finding]:
    p = _pick(pp, "ship_to")
    m = _pick(mc, "ship_to")
    if not p or not m:
        return [Finding(check="ship_to", verdict="MISSING", paypal=p, merchant=m,
                        note="shipping address missing on one side")]
    addr = p[0].value if isinstance(p[0].value, dict) else {}
    zip_, city = addr.get("postal_code", ""), addr.get("admin_area_2", "").lower()
    out = []
    for f in m:
        v = str(f.value).lower()
        # ZIP is the strong signal; the city may carry OCR damage ("Denvcr")
        words = re.findall(r"[a-z]+", v)
        n = max(len(city.split()), 1)
        city_ok = bool(city) and (city in v or any(
            difflib.SequenceMatcher(None, city, " ".join(words[i:i + n])).ratio() > .8
            for i in range(len(words))))
        has_zip = bool(re.search(r"\b\d{5}\b", v))
        ok = (zip_ in v) if (zip_ and has_zip) else city_ok
        out.append(Finding(check="ship_to", verdict="MATCH" if ok else "VALUE_MISMATCH",
                           paypal=p[:1], merchant=[f],
                           note=(f"{f.entity.split(':')[1]} ships to {city.title()} {zip_}" if ok
                                 else f"{f.entity.split(':')[1]} address differs from PayPal")))
    return out


def check_refunds(pp, mc) -> list[Finding]:
    refunds = [f for f in pp if f.entity.startswith("refund:") and f.field == "amount"]
    claims = _pick(mc, "refund_claim")
    if not refunds:
        if claims:  # merchant says refunded, PayPal has no refund on this order
            return [Finding(check="refund", verdict="UNSUPPORTED_CLAIM", merchant=claims,
                            note="merchant says the buyer was refunded, but PayPal shows no refund "
                                 "on this order")]
        return []
    m = [f for f in mc if "refund" in f.field or "refund" in str(f.value).lower()]
    return [Finding(check="refund", verdict="MATCH" if m else "MISSING", paypal=refunds, merchant=m,
                    note=(f"PayPal shows refund/reversal {refunds[0].value}"
                          + ("; merchant records it" if m else
                             "; merchant has no record of it (likely dispute hold, verify)")))]


def _tnorm(v) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(v)).upper()


def check_tracking(pp, mc) -> list[Finding]:
    """The carrier record must be for the parcel the merchant says it sent."""
    claimed = [f for f in mc if f.field == "tracking" and f.entity not in RECORD_DOCS]
    records = [f for f in mc if f.field == "tracking" and f.entity in RECORD_DOCS]
    if not claimed or not records:
        return []
    ids = {_tnorm(f.value) for f in claimed}
    bad = [r for r in records if _tnorm(r.value) not in ids]
    return [Finding(check="tracking", verdict="VALUE_MISMATCH" if bad else "MATCH",
                    merchant=(bad + claimed[:1]) if bad else records[:1] + claimed[:1],
                    note=(f"carrier record is for tracking {bad[0].value}, but the merchant shipped "
                          f"{claimed[0].value} (proof may be for a different parcel)" if bad
                          else "carrier record is for the same tracking number"))]


def check_delivery_time(pp, mc) -> list[Finding]:
    """A delivery scan cannot come before the item shipped or was paid for."""
    cap = _pick(pp, "captured_at")
    shipped = [str(s.value) for s in _pick(mc, "shipped_at") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(s.value))]
    scans = [f for f in mc if f.entity in RECORD_DOCS and f.field == "scan"
             and str(f.value).lower().startswith("delivered") and f.observed_at]
    floor = min([*shipped, *(c.value[:10] for c in cap)], default=None)
    if not scans or not floor:
        return []
    bad = [f for f in scans if f.observed_at[:10] < floor]
    return [Finding(check="delivery_time", verdict="TIME_MISMATCH" if bad else "MATCH",
                    paypal=cap[:1], merchant=bad or scans[:1],
                    note=(f"carrier shows delivery on {bad[0].observed_at[:10]}, before the item "
                          f"shipped / was paid ({floor}); the scan may be fabricated" if bad
                          else "delivery scan is after shipping and payment"))]


def tracking_reuse(cases: dict[str, list[Fact]]) -> dict[str, list[str]]:
    """Cross-case: one tracking number offered as proof for different orders.
    cases: {case_id: merchant facts} -> {tracking: [case_ids]} for reused ones."""
    seen: dict[str, set[str]] = {}
    for cid, facts in cases.items():
        for f in facts:
            if f.field == "tracking":
                seen.setdefault(_tnorm(f.value), set()).add(cid)
    return {t: sorted(ids) for t, ids in seen.items() if len(ids) > 1}


CHECKS = [check_ids, check_amount, check_ship_to, check_timeline, check_delivery, check_refunds,
          check_tracking, check_delivery_time]


def reconcile(paypal_facts: list[Fact], merchant_facts: list[Fact]) -> list[Finding]:
    return [f for c in CHECKS for f in c(paypal_facts, merchant_facts)]


if __name__ == "__main__":
    import sys

    from .graph import PayPalGraph
    from .merchant import extract

    pg = PayPalGraph().from_dispute(sys.argv[1])
    inv = next(f.value for f in pg.facts if f.field == "invoice_id")
    for fd in reconcile(pg.facts, extract(inv)):
        print(f"{fd.verdict:18} {fd.check:14} {fd.note}")
        for f in fd.paypal + fd.merchant:
            print(f"{'':34}- {f.cite()}")
