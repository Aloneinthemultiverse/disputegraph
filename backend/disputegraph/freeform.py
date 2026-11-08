"""Free-form evidence reader: facts written as sentences, not "Label: value" lines.

Real merchant paperwork says "Delivered to Austin, TX 78701 on Oct 3, 2026" or
"FedEx 7821 4455 0091 ... Signed: T OKAFOR". These rules pull the same
canonical fields (amount, invoice_id, tracking, shipped_at, ship_to, carrier
scans) out of such text. Everything is deterministic and cited by line; the
reconciliation engine decides what the facts mean.
"""
from __future__ import annotations

import re
from datetime import date

from .model import Fact, Source

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
DATE_RX = re.compile(
    rf"(?P<iso>\b\d{{4}}-\d{{2}}-\d{{2}}\b)"
    rf"|(?P<dmy>\b\d{{1,2}}-(?P<dmy_m>{MON})-\d{{4}}\b)"
    rf"|(?P<mdy>\b(?P<mdy_m>{MON})\.? (?P<mdy_d>\d{{1,2}})(?:st|nd|rd|th)?\b,?(?: (?P<mdy_y>\d{{4}}))?)"
    rf"|(?P<dm>\b(?P<dm_d>\d{{1,2}}) (?P<dm_m>{MON})\.?\b,?(?: (?P<dm_y>\d{{4}}))?)"
    rf"|(?P<num>\b(?P<a>\d{{1,2}})/(?P<b>\d{{1,2}})(?:/(?P<y>\d{{4}}|\d{{2}}))?\b(?!/))",
    re.I)


def _d(y, m, d):
    try:
        return date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        return None


def dates_in(text: str, hint: date | None) -> list[tuple[int, date, bool]]:
    """All dates in text -> [(position, date, unambiguous)]. Missing years and
    day/month order are resolved towards the hint (the case's other dates)."""
    yh = hint.year if hint else date.today().year
    out = []
    for m in DATE_RX.finditer(text):
        g = m.groupdict()
        if g["iso"]:
            dt, sure = _d(*g["iso"].split("-")), True
        elif g["dmy"]:
            dd, _, yy = g["dmy"].split("-")
            dt, sure = _d(yy, MONTHS[g["dmy_m"][:3].lower()], dd), True
        elif g["mdy"]:
            dt, sure = _d(g["mdy_y"] or yh, MONTHS[g["mdy_m"][:3].lower()], g["mdy_d"]), bool(g["mdy_y"])
        elif g["dm"]:
            dt, sure = _d(g["dm_y"] or yh, MONTHS[g["dm_m"][:3].lower()], g["dm_d"]), bool(g["dm_y"])
        else:
            a, b, y = int(g["a"]), int(g["b"]), g["y"]
            y = int(y) + 2000 if y and len(y) == 2 else int(y or yh)
            opts = [x for x in (_d(y, a, b), _d(y, b, a)) if x]  # US first, then day/month
            if not opts:
                continue
            if hint and len(opts) == 2:
                opts.sort(key=lambda x: abs((x - hint).days))
            dt, sure = opts[0], len(opts) == 1 or a == b
        if dt:
            out.append((m.start(), dt, sure))
    return out


def date_hint(texts: list[str]) -> date | None:
    sure = sorted(d for t in texts for _, d, s in dates_in(t, None) if s)
    return sure[len(sure) // 2] if sure else None


AMOUNT_KW = re.compile(r"\b(?:grand total|total(?: due| payable| a pagar)?|amount(?: payable| due(?: after discount)?"
                       r"| received)?|paid(?: via paypal)?)\b", re.I)
MONEY = re.compile(r"^[^\d\n]{0,30}?(?P<cur>usd|us\$|\$)?\s*(?P<n>\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
                   r"(?!\s*(?:x|items?|boxes|pcs|%|/))(?P<cur2>\s*usd)?", re.I)
INVOICE = re.compile(r"(?i:\b(?:invoice|inv|bill|factura|faktura)\b)\.?\s*(?i:#|no\.?|nr\.?|number|n°|id"
                     r"|ref(?:erence)?)?\s*[:#.]?\s*([A-Z0-9][A-Z0-9/_-]*\d[A-Z0-9/_-]*)")
CARRIER = r"(?:usps|ups|fedex|dhl(?: ecommerce)?|ontrac|bluedart)"
TRACKING = re.compile(rf"(?i:\b(?:tracking(?: no\.?| number| #)?|trk|awb(?: no\.?)?|guia|package(?: id)?"
                      rf"|shipment(?: reference)?|{CARRIER}(?: shipment| tracking(?: no\.?| number)?)?)\b)"
                      r"(?:\s*\([^)]*\)|\s+per our records)?[\s:#.]*(?:is\s+)?([A-Z0-9][A-Z0-9-]*\d[A-Z0-9-]*(?: [A-Z0-9-]*\d[A-Z0-9-]*)*)")
ACCEPT = re.compile(r"\b(?:accepted(?: at facility)?|acceptance scan|(?:package )?received by carrier|package received"
                    r"|picked up|pickup(?: event)?|origin scan|shipment accepted)\b\s*:?", re.I)
SHIP_KW = re.compile(r"\b(?:dispatch confirmation|shipped(?: on)?|dispatched|dispatch(?: date)?|ship date|shipment date|date shipped|ship"
                     r"|handed over|handed to carrier(?: on)?|despachado|envio|enviado|shpd)\b\s*:?", re.I)
DELIVERED = re.compile(r"\bdeliv(?:ered)?\b|\bdelivery date\b|\bentregado\b", re.I)
NOT_DELIVERED = re.compile(r"\b(?:not|no|never)\b[^.\n]{0,20}\bdeliver|\?|\b(?:expected|estimated|scheduled)\b", re.I)
STATUS = re.compile(r"exception|returned? to sender|return in progress|in transit|declared lost|\blost\b|held at"
                    r"|attempted|not home|delayed|missing mail", re.I)
STATES = ("Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|"
          "Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|"
          "Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|"
          "North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|"
          "South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming")
STATE_ZIP = re.compile(rf"\b(?:[A-Z]{{2}}|{STATES})\s*[,/]?\s*\d{{5}}\b")
CITY_ST = re.compile(r"\b[A-Z][a-z]+(?: [A-Z][a-z]+)*,? [A-Z]{2}\b")
ISO_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _money(line: str) -> str | None:
    for kw in AMOUNT_KW.finditer(line):
        if m := MONEY.match(line[kw.end():]):
            if "." in m["n"] or m["cur"] or m["cur2"] or "," in m["n"]:
                return m["n"].replace(",", "")
    return None


def read(page: dict, ent: str, ref: str, hint: date | None) -> list[Fact]:
    doc = page["doc"]
    record = "courier_tracking" in doc
    facts: list[Fact] = []
    prev_date = None
    for i, line in enumerate(page["text"].splitlines(), 1):
        src = Source(side="merchant", ref=ref, pointer=f"page {page['page']}, line {i}")
        add = lambda f, v, at=None: facts.append(Fact(entity=ent, field=f, value=v, observed_at=at,
                                                         source=src, method="rule"))
        ds = dates_in(line, hint)
        if doc in ("invoice", "order_sheet") and (amt := _money(line)):
            add("amount", amt)
        if doc in ("invoice", "order_sheet"):
            for m in INVOICE.finditer(line):
                if len(m.group(1)) >= 3 and not ISO_LIKE.match(m.group(1)):
                    add("invoice_id", m.group(1).rstrip("."))
        if record or doc in ("order_sheet", "emails", "notes"):
            for m in TRACKING.finditer(line):
                if len(re.sub(r"[^A-Z0-9]", "", m.group(1))) >= 6 and not dates_in(m.group(1), hint):
                    add("tracking", m.group(1))
        if record or doc == "order_sheet":
            if STATE_ZIP.search(line) or (record and re.search(r"deliver|destination", line, re.I)
                                          and CITY_ST.search(line)) or (record and re.search(
                    r"\b(?:postcode|postal code|zip(?: code)?)\b\W*\d{5}\b|\bdeliver(?:ed|y)(?: to| address)\s*:", line, re.I)):
                add("ship_to", line.strip())
        if not record:
            for kw in SHIP_KW.finditer(line):
                after = [d for p, d, _ in ds if 0 <= p - kw.end() <= 12]
                if after:
                    add("shipped_at", after[0].isoformat())
                    break
        if record:
            for kw in ACCEPT.finditer(line):  # carrier took the parcel: delivery cannot come before this
                after = [d for p, d, _ in ds if 0 <= p - kw.end() <= 20]
                if after:
                    add("carrier_accepted", after[0].isoformat())
                    break
            if (dm := DELIVERED.search(line)) and not NOT_DELIVERED.search(line) and not STATUS.search(line):
                after = [d for p, d, _ in ds if p >= dm.start()]
                when = (after or [d for _, d, _ in ds] or [prev_date])[0]
                add("scan", "Delivered", when.isoformat() if when else None)
            elif STATUS.search(line):
                add("delivery_status", line.strip())
        if ds:
            prev_date = ds[-1][1]
    return facts
