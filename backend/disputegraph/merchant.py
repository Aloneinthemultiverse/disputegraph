"""Merchant side: load a dispute's evidence folder, extract facts with doc/page
citations, and offer keyword (BM25) search over the pages.

Folder layout: data/merchant/<invoice_id>/<doc>.md, pages split by
"--- page N ---". The doc name sets its type (invoice, order_sheet,
courier_tracking, emails), which the reconciliation engine uses to weigh
records (courier scans) against claims (staff notes, emails).

Extraction is deterministic (regex) for IDs, amounts, dates, tracking. Fuzzy
wording (e.g. "our records show it was delivered") is matched by phrase
rules here; the LLM fallback plugs in later for anything the rules miss.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from .model import Fact, Source

ROOT = Path(__file__).resolve().parents[2]
MERCHANT = ROOT / "data" / "merchant"

# "Label: value" lines -> canonical field
LABELS = {
    r"invoice no": "invoice_id",
    r"order ref": "custom_id",
    r"total due|order total": "amount",
    r"tracking": "tracking",
    r"carrier": "carrier",
    r"shipped": "shipped_at",
    r"ship to|bill to / ship to": "ship_to",
    r"status|current status": "delivery_status",
    r"delivered": "delivery_scan",
}
LINE = re.compile(r"^\s*([A-Za-z /]+?)\s*:\s*(.+?)\s*$")
SCAN = re.compile(r"^(\d{4}-\d{2}-\d{2})(?: (\d{2}:\d{2}))?\s+(.+)$")
DATE = re.compile(r"^Date:\s*(\d{4}-\d{2}-\d{2})", re.M)
CLAIMS = [  # free-text claims in emails / notes
    (re.compile(r"\b(was|were|has been|marked) delivered\b", re.I), "delivery_status", "Delivered"),
    (re.compile(r"\bshipped (today|on)\b", re.I), "shipped_claim", "Shipped"),
]
AMOUNT = re.compile(r"([\d,]+\.\d{2})")


def load_pages(invoice_id: str) -> list[dict]:
    pages = []
    for f in sorted((MERCHANT / invoice_id).glob("*.md")):
        parts = re.split(r"^--- page (\d+) ---$", f.read_text(encoding="utf-8"), flags=re.M)
        for num, text in zip(parts[1::2], parts[2::2]):
            pages.append({"doc": f.stem, "page": int(num), "text": text.strip()})
    return pages


def _norm(field: str, value: str):
    if field == "amount":
        m = AMOUNT.search(value)
        return m.group(1).replace(",", "") if m else value
    if field == "shipped_at":
        return value[:10]
    return value


def extract(invoice_id: str) -> list[Fact]:
    facts: list[Fact] = []
    for p in load_pages(invoice_id):
        ent = f"merchant:{p['doc']}"
        ref = f"{invoice_id}/{p['doc']}.md"
        dated = DATE.search(p["text"])
        at = dated.group(1) if dated else None
        for i, line in enumerate(p["text"].splitlines(), 1):
            ptr = f"page {p['page']}, line {i}"
            src = Source(side="merchant", ref=ref, pointer=ptr)
            if m := SCAN.match(line.strip()):
                facts.append(Fact(entity=ent, field="scan", value=m.group(3).strip(),
                                  observed_at=f"{m.group(1)} {m.group(2) or ''}".strip(), source=src))
                continue
            if m := LINE.match(line):
                label = m.group(1).strip().lower()
                for pat, field in LABELS.items():
                    if re.fullmatch(pat, label):
                        facts.append(Fact(entity=ent, field=field, value=_norm(field, m.group(2)),
                                          observed_at=at, source=src))
                        break
                continue
            for pat, field, val in CLAIMS:
                if pat.search(line):
                    facts.append(Fact(entity=ent, field=field, value=val,
                                      observed_at=at, source=src))
    return facts


class BM25:
    """Tiny BM25 over pages; stands in until TurboVec + BM25 hybrid is wired."""

    def __init__(self, pages: list[dict], k1=1.5, b=0.75):
        self.pages, self.k1, self.b = pages, k1, b
        self.toks = [self._tok(p["text"]) for p in pages]
        self.avg = sum(map(len, self.toks)) / max(len(self.toks), 1)
        df = Counter(t for d in self.toks for t in set(d))
        n = len(pages)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    @staticmethod
    def _tok(s: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", s.lower())

    def search(self, query: str, k=3) -> list[tuple[float, dict]]:
        q = self._tok(query)
        scored = []
        for p, d in zip(self.pages, self.toks):
            tf = Counter(d)
            s = sum(self.idf.get(t, 0) * tf[t] * (self.k1 + 1) /
                    (tf[t] + self.k1 * (1 - self.b + self.b * len(d) / self.avg)) for t in q)
            if s > 0:
                scored.append((round(s, 3), p))
        return sorted(scored, key=lambda x: -x[0])[:k]


if __name__ == "__main__":
    import sys
    inv = sys.argv[1]
    for f in extract(inv):
        print(f"  {f.entity:28} {f.field:16} {str(f.value)[:34]:34} {f.cite()}")
    print("\nsearch: 'was the laptop delivered'")
    for s, p in BM25(load_pages(inv)).search("was the laptop delivered"):
        print(f"  {s:6} {p['doc']} p{p['page']}")
