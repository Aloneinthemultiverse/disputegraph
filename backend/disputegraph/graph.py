"""PayPal Graph: start from a dispute and follow IDs to captures, orders, refunds.

Nodes: dispute / capture / order / refund / invoice (bridge to merchant data).
Every node also yields Facts with provenance for the reconciliation engine.
"""
from __future__ import annotations

import networkx as nx

from .model import Fact, Source
from .paypal import PayPal


def _fact(entity, field, value, ref, pointer, at=None) -> Fact:
    return Fact(entity=entity, field=field, value=value, observed_at=at,
                source=Source(side="paypal", ref=ref, pointer=pointer))


def _link(body: dict, rel: str) -> str | None:
    return next((l["href"] for l in body.get("links", []) if l["rel"] == rel), None)


class PayPalGraph:
    def __init__(self, client: PayPal | None = None):
        self.pp = client or PayPal()
        self.g = nx.MultiDiGraph()
        self.facts: list[Fact] = []

    def _add(self, node: str, kind: str, **attrs):
        self.g.add_node(node, kind=kind, **attrs)

    # -- builders ---------------------------------------------------------
    def from_dispute(self, dispute_id: str) -> "PayPalGraph":
        ref = f"/v1/customer/disputes/{dispute_id}"
        d = self.pp.get(ref)
        dn = f"dispute:{dispute_id}"
        self._add(dn, "dispute", reason=d.get("reason"), status=d.get("status"),
                  stage=d.get("dispute_life_cycle_stage"))
        at = d.get("create_time")
        for f, v, p in [("reason", d.get("reason"), "/reason"),
                        ("status", d.get("status"), "/status"),
                        ("stage", d.get("dispute_life_cycle_stage"), "/dispute_life_cycle_stage"),
                        ("amount", d["dispute_amount"]["value"], "/dispute_amount/value"),
                        ("currency", d["dispute_amount"]["currency_code"], "/dispute_amount/currency_code"),
                        ("created", at, "/create_time"),
                        # null during INQUIRY stage; UI must handle "no deadline yet"
                        ("seller_response_due", d.get("seller_response_due_date"), "/seller_response_due_date")]:
            self.facts.append(_fact(dn, f, v, ref, p, at))
        for i, m in enumerate(d.get("messages", [])):
            self.facts.append(_fact(dn, "buyer_message", m.get("content"), ref,
                                    f"/messages/{i}/content", m.get("time_posted")))

        for i, t in enumerate(d.get("disputed_transactions", [])):
            p = f"/disputed_transactions/{i}"
            for f, k in [("invoice_id", "invoice_number"), ("custom_id", "custom"),
                         ("buyer_transaction_id", "buyer_transaction_id")]:
                if t.get(k):
                    self.facts.append(_fact(dn, f, t[k], ref, f"{p}/{k}", at))
            if t.get("invoice_number"):
                inv = f"invoice:{t['invoice_number']}"
                self._add(inv, "invoice")
                self.g.add_edge(dn, inv, rel="references_invoice")
            if t.get("seller_transaction_id"):
                cap = self.add_capture(t["seller_transaction_id"])
                self.g.add_edge(dn, cap, rel="disputes")
        return self

    def add_capture(self, capture_id: str) -> str:
        cn = f"capture:{capture_id}"
        if cn in self.g:
            return cn
        ref = f"/v2/payments/captures/{capture_id}"
        c = self.pp.get(ref)
        at = c.get("create_time")
        self._add(cn, "capture", status=c.get("status"), amount=c["amount"]["value"])
        for f, v, p in [("amount", c["amount"]["value"], "/amount/value"),
                        ("currency", c["amount"]["currency_code"], "/amount/currency_code"),
                        ("status", c.get("status"), "/status"),
                        ("captured_at", at, "/create_time"),
                        ("invoice_id", c.get("invoice_id"), "/invoice_id"),
                        ("custom_id", c.get("custom_id"), "/custom_id")]:
            if v is not None:
                self.facts.append(_fact(cn, f, v, ref, p, at))
        if c.get("invoice_id"):
            inv = f"invoice:{c['invoice_id']}"
            self._add(inv, "invoice")
            self.g.add_edge(cn, inv, rel="has_invoice")
        if up := _link(c, "up"):
            on = self.add_order(up.rsplit("/", 1)[-1])
            self.g.add_edge(cn, on, rel="part_of")
        return cn

    def add_order(self, order_id: str) -> str:
        on = f"order:{order_id}"
        if on in self.g:
            return on
        ref = f"/v2/checkout/orders/{order_id}"
        o = self.pp.get(ref)
        at = o.get("create_time")
        self._add(on, "order", status=o.get("status"))
        self.facts.append(_fact(on, "status", o.get("status"), ref, "/status", at))
        self.facts.append(_fact(on, "created", at, ref, "/create_time", at))
        for i, pu in enumerate(o.get("purchase_units", [])):
            p = f"/purchase_units/{i}"
            for f, k in [("description", "description"), ("invoice_id", "invoice_id"),
                         ("custom_id", "custom_id")]:
                if pu.get(k):
                    self.facts.append(_fact(on, f, pu[k], ref, f"{p}/{k}", at))
            if ship := pu.get("shipping", {}).get("address"):
                self.facts.append(_fact(on, "ship_to", ship, ref, f"{p}/shipping/address", at))
            for j, r in enumerate(pu.get("payments", {}).get("refunds", [])):
                rn = f"refund:{r['id']}"
                self._add(rn, "refund", status=r.get("status"))
                self.g.add_edge(rn, on, rel="refunds")
                rp = f"{p}/payments/refunds/{j}"
                self.facts.append(_fact(rn, "amount", r["amount"]["value"], ref, f"{rp}/amount/value",
                                        r.get("create_time")))
                self.facts.append(_fact(rn, "status", r.get("status"), ref, f"{rp}/status",
                                        r.get("create_time")))
        if o.get("payer", {}).get("payer_id"):
            self.facts.append(_fact(on, "payer_id", o["payer"]["payer_id"], ref, "/payer/payer_id", at))
        return on

    # -- views ------------------------------------------------------------
    def summary(self) -> str:
        lines = [f"{u} --{d['rel']}--> {v}" for u, v, d in self.g.edges(data=True)]
        lines.append(f"{len(self.facts)} facts")
        return "\n".join(lines)


if __name__ == "__main__":
    import sys
    pg = PayPalGraph().from_dispute(sys.argv[1])
    print(pg.summary())
    for f in pg.facts:
        print(f"  {f.entity:32} {f.field:20} {str(f.value)[:40]:40} {f.cite()}")
