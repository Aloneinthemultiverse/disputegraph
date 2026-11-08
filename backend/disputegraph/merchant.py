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

from . import freeform, intake
from .llm import classify_claim, extract_fields, map_label
from .model import Fact, Source

ROOT = Path(__file__).resolve().parents[2]
MERCHANT = ROOT / "data" / "merchant"

# "Label: value" lines -> canonical field
LABELS = {
    r"invoice no|invoice number|invoice id|doc ref": "invoice_id",
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
    (re.compile(r"^(?!.*\?)(?!.*\b(not|never|no)\b[^.]{0,20}deliver).*(\b(was|were|has been|have been|marked( as)?|"
                r"it is|is|successfully|status:?|shows?( it was)?|says?) delivered\b|\bdelivered (successfully|to "
                r"(you|customer|your))|\bdelivered:\s*yes|\b(item|package|parcel|order|everything)( was)? delivered\b|"
                r"\bdelivered (already|in good order|to (the )?(buyer|customer|client|recipient))|\b(completed|directly)"
                r" and delivered\b|^\s*delivered\b)", re.I), "delivery_status", "Delivered"),
    (re.compile(r"\bshipped (today|on)\b", re.I), "shipped_claim", "Shipped"),
    (re.compile(r"^(?!.*\?)(?!.*\b(no|never|not|want|nothing)\b[^.]{0,25}refund).*(\b(have|has|was|were|already|we)"
                r"( already)? (been )?refunded\b|\bissued (a|the|your)( full| partial)? refund\b|\brefund"
                r"( of \$?[\d.,]+)? (issued|processed|sent|already sent)|\bprocessed a( full)? refund|\brefunded "
                r"(in full|you|the buyer)|\brefund status: refunded|\brefunded \$|\bcredited\b.{0,40}\bback\b|\bfully refunded|\b(issued|sent|processed)\b[^.]{0,30}\brefund\b|"
                r"\brefund (already )?(sent|completed)\b)", re.I),
     "refund_claim", "Refunded"),
]
LLM_FIELD = {"DELIVERED": ("delivery_status", "Delivered"), "SHIPPED": ("shipped_claim", "Shipped"),
             "REFUNDED": ("refund_claim", "Refunded")}
INJECTION = re.compile(r"\b(ignore|disregard) (all |any )?(previous|prior|above) (rules|instructions)|"
                       r"^\s*(system|assistant)\s*:|\bmark (this|it) as\b", re.I)
OTHER_ORDER = re.compile(r"^\s*(fwd?|fw|forwarded)\b|\b(different|another|other|unrelated) (order|purchase|merchant)\b",
                         re.I)
ID_RUN = re.compile(r"[A-Z0-9][A-Z0-9/_-]*\d[A-Z0-9/_-]*(?: [A-Z0-9-]*\d[A-Z0-9-]*)*")
AMOUNT = re.compile(r"([\d,]+\.\d{2})")


def load_pages(invoice_id: str) -> list[dict]:
    """Text docs as is; PDFs and images through OCR; non-English pages through a checked translation."""
    pages = []
    for f in sorted((MERCHANT / invoice_id).glob("*")):
        text, how = intake.read_file(f)
        if text is None:
            if how == "unread" and f.suffix.lower() in intake.IMAGE | {".pdf"}:
                pages.append({"doc": f.stem, "page": 1, "text": "", "intake": "unread"})
            continue
        if "--- page" not in text:
            text = "--- page 1 ---\n" + text
        parts = re.split(r"^--- page (\d+) ---$", text, flags=re.M)
        for num, body in zip(parts[1::2], parts[2::2]):
            body, tr = intake.translate(body.strip())
            pages.append({"doc": f.stem, "page": int(num), "text": body,
                          "intake": how if tr == "original" else f"{how}+translated"})
    return pages


MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def to_iso(value: str) -> str:
    """2026-10-14 | 10/14/2026 | Oct 14, 2026 | 14 Oct 2026 -> 2026-10-14 (else unchanged)."""
    v = value.strip()
    if m := re.match(r"(\d{4})-(\d{2})-(\d{2})", v):
        return m.group(0)
    if m := re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", v):  # US month/day/year
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    if m := re.match(r"([A-Za-z]{3})[a-z]*\.? (\d{1,2}),? (\d{4})", v):
        if mo := MONTHS.get(m.group(1).lower()):
            return f"{m.group(3)}-{mo:02d}-{int(m.group(2)):02d}"
    if m := re.match(r"(\d{1,2}) ([A-Za-z]{3})[a-z]*\.? (\d{4})", v):
        if mo := MONTHS.get(m.group(2).lower()):
            return f"{m.group(3)}-{mo:02d}-{int(m.group(1)):02d}"
    return v


def _norm(field: str, value: str):
    if field == "amount":
        m = AMOUNT.search(value)
        return m.group(1).replace(",", "") if m else value
    if field == "shipped_at":
        return to_iso(value)
    if field in ("tracking", "invoice_id"):  # "INV-023. Amount payable: ..." -> "INV-023"
        m = ID_RUN.search(value)
        return m.group(0).rstrip(".") if m else value
    return value


_NUM = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen".split())}
_NUM.update(twenty=20, thirty=30, forty=40, fifty=50, sixty=60, seventy=70, eighty=80, ninety=90)
_W = "|".join(sorted(_NUM, key=len, reverse=True)) + "|hundred|thousand|a|and"
# "one hundred twenty-nine dollars (and fifty cents)"
_RUN = rf"(?:\b(?:{_W})\b[ -]+)*\b(?:{_W})\b"
WORD_MONEY = re.compile(rf"({_RUN})\s+dollars?(?:\s+and\s+({_RUN})\s+cents?)?", re.I)


def _words(s: str) -> float:
    """'one hundred twenty-nine' -> 129; 'two thousand and five' -> 2005."""
    total = cur = 0
    for w in re.split(r"[ -]+", s.lower().strip()):
        if w in ("and", ""):
            continue
        if w == "a":
            cur = cur or 1
        elif w == "hundred":
            cur = (cur or 1) * 100
        elif w == "thousand":
            total += (cur or 1) * 1000; cur = 0
        else:
            cur += _NUM[w]
    return float(total + cur)


def _refund_value(line: str) -> str:
    """'Refunded' plus what the line says about size: 'Refunded full' or 'Refunded 50.00'."""
    word = re.search(r"refund", line, re.I)
    nums = [(abs(m.start() - word.start()) if word else 0, m[1] or m[2])
            for m in re.finditer(r"\$\s?([\d,]+(?:\.\d{1,2})?)|\b([\d,]+\.\d{2})\b", line)]
    if nums:  # a stated amount (the one nearest "refund") is the claim; compared with PayPal's refunds
        return f"Refunded {min(nums)[1].replace(',', '')}"
    if (w := WORD_MONEY.search(line)) and _words(w[1]) > 0:
        return f"Refunded {_words(w[1]) + (_words(w[2]) / 100 if w[2] else 0):.2f}"
    if re.search(r"\b(fully|in full|full refund|entire (order|amount)|100%|complete refund)\b", line, re.I):
        return "Refunded full"
    return "Refunded"


def extract(invoice_id: str, pages: list[dict] | None = None) -> list[Fact]:
    facts: list[Fact] = []
    pages = pages if pages is not None else load_pages(invoice_id)
    hint = freeform.date_hint([p["text"] for p in pages])
    for p in pages:
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
                field = next((f for pat, f in LABELS.items() if re.fullmatch(pat, label)), None)
                method = "regex"
                if field is None and (field := map_label(label)):  # unseen wording -> LLM maps it
                    method = "llm"
                if field:
                    facts.append(Fact(entity=ent, field=field, value=_norm(field, m.group(2)),
                                      observed_at=at, source=src, method=method))
                    continue
                # "Seller: we refunded you" -- a speaker, not a field: read it as a sentence below
            if INJECTION.search(line) or OTHER_ORDER.search(line):  # not evidence about this order
                continue
            hit = False
            for pat, field, val in CLAIMS:
                if pat.search(line):
                    hit = True
                    facts.append(Fact(entity=ent, field=field, value=_refund_value(line) if
                                      field == "refund_claim" else val, observed_at=at, source=src))
            if not hit and (word := classify_claim(line)):  # fuzzy wording -> LLM
                field, val = LLM_FIELD[word]
                val = _refund_value(line) if field == "refund_claim" else val
                facts.append(Fact(entity=ent, field=field, value=val, observed_at=at,
                                  source=src, method="llm"))
        seen = {(f.entity, f.field, str(f.value)) for f in facts}
        dated_scans = any(f.entity == ent and f.field == "scan" for f in facts)
        for f in freeform.read(p, ent, ref, hint):  # facts written as sentences
            if f.field == "scan" and dated_scans:  # the carrier's own dated scans win
                continue
            if f.field == "scan" or (f.entity, f.field, str(f.value)) not in seen:
                facts.append(f)
        facts += _llm_verified(p, ent, ref, hint, {f.source.pointer for f in facts if f.entity == ent})
    return facts


# only lines holding something a check could use: an ID-like token or a money amount
WORTH_ASKING = re.compile(r"\b(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9-]{6,}\b|\b\d{7,}\b|\d+\.\d{2}\b")


TOTAL_LINE = re.compile(r"\b(grand )?total\b|amount (due|payable|paid|charged)|\bbalance due\b|\bcharged\b|"
                        r"\bpaid\b|\bcollected\b", re.I)
SHIP_LINE = re.compile(r"\b(ship|shipped|shipping|dispatch\w*|sent|went out|left|collected|picked up|handed|posted"
                       r"|mailed|despachado|enviado)\b", re.I)
INVOICE_LINE = re.compile(r"\b(invoice|inv|bill|receipt|factura|doc(ument)? ref)\b", re.I)


def _verify(field: str, value: str, line: str, hint):
    """Keep an LLM-proposed value only if it is really in the line and has the field's shape."""
    squash = lambda s: re.sub(r"\s+", " ", s).strip().lower()
    if not value or squash(value) not in squash(line):
        return None  # invented, not copied
    if field == "invoice_id" and not INVOICE_LINE.search(line):  # manifest / order refs are not invoices
        return None
    if field in ("tracking", "invoice_id"):
        core = re.sub(r"[^A-Za-z0-9]", "", value)
        ok = len(core) >= (6 if field == "tracking" else 3) and re.search(r"\d", core) \
            and not freeform.dates_in(value, hint)
        return value if ok else None
    if field == "amount":
        if not TOTAL_LINE.search(line):  # an item price or shipping fee is not the order total
            return None
        m = re.fullmatch(r"(?:usd|us\$|\$)?\s*([\d,]+(?:\.\d{1,2})?)\s*(?:usd)?", value.strip(), re.I)
        return m.group(1).replace(",", "") if m else None
    if field == "shipped_at":
        if not SHIP_LINE.search(line):  # a printed label or order date is not a shipment
            return None
        ds = freeform.dates_in(value, hint)
        return ds[0][1].isoformat() if ds else None
    if field == "ship_to":
        return line.strip() if re.search(r"[A-Za-z]{3}", value) else None
    return None


def _llm_verified(page, ent, ref, hint, covered) -> list[Fact]:
    """Last resort for lines nothing else could read: the LLM proposes, code verifies."""
    if not any(k in page["doc"] for k in ("invoice", "order_sheet", "courier_tracking")):
        return []
    out = []
    for i, line in enumerate(page["text"].splitlines(), 1):
        ptr = f"page {page['page']}, line {i}"
        if ptr in covered or not WORTH_ASKING.search(line) or SCAN.match(line.strip()) \
                or INJECTION.search(line) or OTHER_ORDER.search(line):
            continue
        for field, value in extract_fields(line):
            if (v := _verify(field, value, line, hint)) is not None:
                out.append(Fact(entity=ent, field=field, value=v, source=Source(
                    side="merchant", ref=ref, pointer=ptr), method="llm-verified"))
    return out


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
