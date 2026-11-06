"""Common data model shared by the PayPal side and the merchant side.

Every fact carries provenance, so any verdict can be traced back to the exact
API field (PayPal side) or document/page (merchant side) it came from.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

Side = Literal["paypal", "merchant"]


class Source(BaseModel):
    side: Side
    ref: str            # API path (e.g. /v2/payments/captures/X) or doc id
    pointer: str = ""   # JSON pointer into the response, or "page 2"


class Fact(BaseModel):
    entity: str         # e.g. "capture:0FW80593L7360991P"
    field: str          # canonical field: amount, currency, status, invoice_id, ...
    value: Any
    source: Source
    observed_at: str | None = None   # timestamp the source attaches to the value

    def cite(self) -> str:
        return f"{self.source.side}:{self.source.ref}#{self.source.pointer}"
