"""Assessment gate, ported from TruthGuard (truthguard/controller.py + assess.py).

A question about a dispute ends in exactly one of four outputs:
  answer       SUFFICIENT: every claim cited (API field or doc/page/line)
  dual_answer  conflicting sources: both sides shown with provenance, never arbitrated
  clarify      AMBIGUOUS_QUESTION: multiple-choice options, caller re-runs once
  refusal      INSUFFICIENT after rewrites: says exactly what evidence is missing

Confidence and bands are TruthGuard's: conf = min(1, sim + 0.25) * verdict
weight (1.0 / 0.7 / 0.4), halved on conflict; >=0.75 high, >=0.40 hedge,
else refuse. Up to MAX_REWRITES query rewrites before refusing.

Answers are written from templates over Findings, so no text is generated
that a Finding doesn't support. An LLM summary layer can sit on top later.
"""
from __future__ import annotations

import re
from typing import Any

from .reconcile import Finding

CONF_ANSWER, CONF_HEDGE, MAX_REWRITES = 0.75, 0.40, 2
VERDICT_WEIGHT = {"SUFFICIENT": 1.0, "PARTIAL": 0.7}

TOPICS = {  # topic -> (reconciliation checks, trigger words)
    "delivery": (["delivery"], r"deliver|receiv|arriv|tracking|courier|ups|scan|transit"),
    "amount":   (["amount"], r"amount|price|total|charg|paid|pay|cost|how much|\$"),
    "ids":      (["id:invoice_id", "id:custom_id"], r"invoice|order (id|ref|number)|reference"),
    "ship_to":  (["ship_to"], r"address|ship(ped)? to|where.*sent|destination"),
    "timeline": (["timeline"], r"when|date|timeline|before|after"),
    "refund":   (["refund"], r"refund|revers|hold|money back"),
}
LABELS = {"delivery": "Was it delivered?", "amount": "Does the amount match?",
          "ids": "Do the invoice / order IDs match?", "ship_to": "Was it shipped to the right address?",
          "timeline": "Is the timeline consistent?", "refund": "Was anything refunded?"}
SYNONYMS = {  # rewrite step: widen vocabulary before giving up
    "get": "receive", "got": "received", "came": "arrived", "sent": "shipped",
    "bill": "invoice", "money": "amount", "package": "delivery", "parcel": "delivery",
}
VAGUE = re.compile(r"^\s*(is|was|are)?\s*(it|this|that|everything|all)\b.*\b(ok|okay|fine|good|right|correct|valid)\b|"
                   r"^\s*(status|summary|what happened|any issues?)\??\s*$", re.I)
CONFLICT = {"VALUE_MISMATCH", "CONTRADICTION", "TIME_MISMATCH"}
GAP = {"MISSING", "UNSUPPORTED_CLAIM"}


def _route(q: str) -> list[str]:
    return [t for t, (_, pat) in TOPICS.items() if re.search(pat, q, re.I)]


def _rewrite(q: str) -> str:
    return " ".join(SYNONYMS.get(w.lower(), w) for w in q.split())


def _cites(fs: list[Finding]) -> list[str]:
    seen = []
    for fd in fs:
        for f in fd.paypal + fd.merchant:
            if f.cite() not in seen:
                seen.append(f.cite())
    return seen


def _cross_source(fd: Finding) -> bool:
    """Clash guard: a conflict needs facts from at least two different sources."""
    return len({f.source.ref for f in fd.paypal + fd.merchant}) >= 2


def assess(findings: list[Finding]) -> tuple[str, list[Finding], list[Finding]]:
    conflicts = [f for f in findings if f.verdict in CONFLICT and _cross_source(f)]
    gaps = [f for f in findings if f.verdict in GAP]
    matches = [f for f in findings if f.verdict == "MATCH"]
    if conflicts:
        return "CONFLICT", conflicts, matches
    if gaps and not matches:
        # one-sided evidence (e.g. PayPal shows a refund, merchant has nothing) is a
        # partial answer; only findings with no facts at all are INSUFFICIENT
        cited = [g for g in gaps if g.paypal or g.merchant]
        return ("PARTIAL", cited, []) if cited else ("INSUFFICIENT", gaps, [])
    if gaps:
        return "PARTIAL", matches, gaps
    return "SUFFICIENT", matches, []


def _confidence(verdict: str, sim: float, conflict: bool) -> float:
    conf = min(1.0, sim + 0.25) * VERDICT_WEIGHT.get(verdict, 0.4)
    return round(conf * (0.5 if conflict else 1.0), 2)


def _band(c: float) -> str:
    return "high" if c >= CONF_ANSWER else "hedge" if c >= CONF_HEDGE else "refuse"


def _side(fd: Finding) -> str:
    return "; ".join(f"{f.source.side} {f.entity.split(':', 1)[1]} = {f.value}"
                     for f in fd.paypal + fd.merchant)


def ask(question: str, findings: list[Finding]) -> dict[str, Any]:
    trace: list[dict] = []
    if VAGUE.search(question):
        trace.append({"step": "assess", "verdict": "AMBIGUOUS_QUESTION"})
        return {"kind": "clarify", "text": "Which part of the dispute do you mean?",
                "confidence": None, "band": None, "citations": [], "contradictions": [],
                "clarify_options": [LABELS[t] for t in TOPICS],
                "gaps": None, "trace": trace}

    q = question
    for attempt in range(MAX_REWRITES + 1):
        topics = _route(q)
        trace.append({"step": "route", "attempt": attempt, "query": q, "topics": topics})
        if topics:
            break
        if attempt < MAX_REWRITES:
            nq = _rewrite(q)
            if nq == q:  # rewrite can't add anything new; stop early (TruthGuard: rewrite_abandoned)
                trace.append({"step": "rewrite_abandoned"})
                break
            q = nq
    if not topics:
        return {"kind": "refusal", "confidence": 0.0, "band": "refuse",
                "text": "No evidence in the PayPal records or merchant documents addresses this question.",
                "citations": [], "contradictions": [], "clarify_options": None,
                "gaps": ["No PayPal field or merchant document covers this. Add evidence that does "
                         "(e.g. signed delivery confirmation, photos, chat logs)."],
                "trace": trace}

    checks = {c for t in topics for c in TOPICS[t][0]}
    rel = [f for f in findings if f.check in checks]
    verdict, primary, secondary = assess(rel)
    trace.append({"step": "assess", "verdict": verdict, "findings": len(rel)})
    sim = 1.0  # deterministic routing to exact checks

    if verdict == "CONFLICT":
        # evidence is sufficient, it just disagrees: TruthGuard halves confidence on conflict
        conf = _confidence("SUFFICIENT", sim, conflict=True)
        return {"kind": "dual_answer", "confidence": conf, "band": _band(conf),
                "text": "The sources disagree. Both sides are shown; DisputeGraph does not pick one.",
                "contradictions": [{"check": f.check, "verdict": f.verdict, "note": f.note,
                                    "claims": _side(f), "citations": _cites([f])} for f in primary],
                "citations": _cites(primary + secondary), "clarify_options": None,
                "gaps": None, "trace": trace}
    if verdict == "INSUFFICIENT":
        return {"kind": "refusal", "confidence": 0.0, "band": "refuse",
                "text": "Not enough evidence to answer.",
                "gaps": [f.note for f in primary], "citations": _cites(primary),
                "contradictions": [], "clarify_options": None, "trace": trace}
    conf = _confidence(verdict, sim, conflict=False)
    band = _band(conf)
    prefix = "" if band == "high" else "Partly supported: "
    return {"kind": "answer", "confidence": conf, "band": band,
            "text": prefix + " ".join(f.note + "." for f in primary),
            "citations": _cites(primary),
            "gaps": [f.note for f in secondary] or None,
            "contradictions": [], "clarify_options": None, "trace": trace}


if __name__ == "__main__":
    import json
    import sys

    from .graph import PayPalGraph
    from .merchant import extract
    from .reconcile import reconcile

    pg = PayPalGraph().from_dispute(sys.argv[1])
    inv = next(f.value for f in pg.facts if f.field == "invoice_id")
    fds = reconcile(pg.facts, extract(inv))
    for q in sys.argv[2:]:
        r = ask(q, fds)
        r.pop("trace")
        print(f"\nQ: {q}\n" + json.dumps(r, indent=1))
