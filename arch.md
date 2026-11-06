# DisputeGraph — Architecture

> "Two systems. Two versions of the truth. One investigation engine."

DisputeGraph compares **what PayPal's records show** with **what the merchant's own evidence claims**. It finds matches, mismatches, gaps and unsupported claims, chases missing evidence, and prepares a human-approved dispute response.

---

## 1. Mind map

```
                                   🧠 DISPUTEGRAPH
                                          │
   ┌──────────────┬───────────────┬───────┴───────┬────────────────┬────────────────┐
   ▼              ▼               ▼               ▼                ▼                ▼
1. TRIGGERS   2. PAYPAL SIDE  3. MERCHANT SIDE 4. RECONCILE    5. AGENTS        6. OUTPUT / UI
```

```
TRIGGERS
├── A. Dispute opened (main flow)      → webhook CUSTOMER.DISPUTE.CREATED / list_disputes
├── B. Scheduled sweep (pre-dispute)   → merchant says "refunded" but PayPal shows no refund
└── C. Agent-purchase dispute (stretch)→ order placed by an AI shopping agent

PAYPAL SIDE (structured data, no RAG)
├── Orders API         → order, items, invoice_id / custom_id
├── Payments API       → captures, refunds
├── Transaction Search → transaction history
├── Disputes API       → reason, status, seller_response_due_date, disputed txn IDs
├── Tracking API       → carrier + tracking (if used)
├── ⭐ PayPal Graph Builder → links records by ID
└── PayPal Analyst (agent) → facts + source (API, field, fetched_at)

MERCHANT SIDE (unstructured documents, RAG)
├── invoices · dispatch receipts · courier tracking · proof of delivery
├── customer emails · refund records · product pages · return policy
├── TurboVec + HippoRAG → retrieval with citations
└── Merchant Evidence Analyst (agent) → claims + doc/page citations

RECONCILIATION ENGINE (core)
├── Common model: Transaction · Order · Payment · Shipment · Refund · Dispute · Evidence · Event
├── Bridge key: invoice_id / custom_id
├── Deterministic checks (code) + LLM checks (fuzzy wording only)
└── Verdicts: ✅ Match · ❌ Value · 🕒 Time · ⬜ Missing · ⚠️ Unsupported · 🛑 Contradiction

AGENTS
├── PayPal Analyst
├── Merchant Evidence Analyst
└── Reconciliation Investigator (gap → request → re-run → update)

OUTPUT / UI
├── AG Grid investigation screen + source click-through
├── Deadline countdown · Evidence strength bar · Plain-English summary · Audit log
├── Evidence package → 👤 human approval
└── Disputes API provide-evidence (sandbox)
```

---

## 2. System diagram

```
              ┌───────────────────────── TRIGGERS ─────────────────────────┐
              │  PayPal webhook   │  Scheduled sweep   │  Manual "Investigate" │
              └─────────┬─────────┴─────────┬──────────┴──────────┬───────────┘
                        ▼                   ▼                     ▼
                  ┌──────────────────── ORCHESTRATOR (FastAPI) ────────────────────┐
                  │                                                               │
      ┌───────────▼───────────┐                                   ┌───────────────▼──────────┐
      │   PAYPAL ANALYST      │                                   │ MERCHANT EVIDENCE ANALYST │
      │ REST API / PayPal MCP │                                   │  TurboVec + HippoRAG      │
      │        │              │                                   │        │                 │
      │ PayPal Graph Builder  │                                   │ LLM fact extraction      │
      │   (NetworkX)          │                                   │ + citations              │
      └───────────┬───────────┘                                   └───────────────┬──────────┘
                  │  PayPal facts (with provenance)        Merchant claims (with citations) │
                  └──────────────────────┐                  ┌────────────────────────────────┘
                                         ▼                  ▼
                              ┌────────────────────────────────────┐
                              │      RECONCILIATION ENGINE         │
                              │  normalise → align by bridge key → │
                              │  deterministic checks → LLM fuzzy  │
                              │  → verdict per field               │
                              └─────────────────┬──────────────────┘
                                                ▼
                              ┌────────────────────────────────────┐
                              │   RECONCILIATION INVESTIGATOR      │◀── merchant uploads
                              │  gaps → evidence requests → re-run │    new evidence
                              └─────────────────┬──────────────────┘
                                                ▼
                 ┌──────────────────────── UI (React + AG Grid) ───────────────────────┐
                 │ Summary · Deadline · Evidence strength · Verdict grid · Audit log   │
                 └─────────────────────────────────┬───────────────────────────────────┘
                                                   ▼
                                     👤 Merchant approves package
                                                   ▼
                              PayPal Disputes API: provide-evidence (sandbox)
```

---

## 3. Components

### 3.1 Triggers
| Trigger | Input | Notes |
|---|---|---|
| Dispute webhook | `CUSTOMER.DISPUTE.CREATED` event | Needs a public URL (Render). Fallback: a "Check disputes" button that calls `list_disputes` |
| Refund sweep | Recent merchant orders marked refunded | Runs on a schedule or on a button press |
| Manual | A dispute ID | Used in the demo |

### 3.2 PayPal side
- **Access:** PayPal REST APIs (OAuth client credentials, Sandbox). The PayPal MCP server / Agent Toolkit (`npx -y @paypal/mcp --tools=...`) is used where its tools fit, such as `list_disputes` and `get_dispute`.
- **Not RAG.** API responses are the source of truth. Store the raw JSON plus normalised records.
- **PayPal Graph:** nodes are records; edges are ID links.

```
Dispute ──disputes──▶ Capture/Transaction ──part_of──▶ Order ──invoice_id──▶ (bridge to merchant)
                             │
                        refunded_by
                             ▼
                          Refund
```

> All field names must be verified against real Sandbox responses on day 1.

### 3.3 Merchant side
- **Inputs:** uploaded or synthetic documents (PDF, text, email), every one labelled **SYNTHETIC** in the demo.
- **Retrieval:** TurboVec + hybrid search, ported from the private `Aloneinthemultiverse/auralis` repo:
  ```
  query ─┬─▶ dense:   TurboVec (2-bit TurboQuant, IdMapIndex, dim 768) → top k×10 candidates
         │            → exact cosine re-score on full embeddings → top k
         ├─▶ lexical: BM25-style full-text search (IDF-weighted terms)
         └─▶ fuse with Reciprocal Rank Fusion → rerank the head with an LLM ("does this passage help?")
  ```
  - TurboVec runs as a small FastAPI service (`vendor/turbovec-service/app.py`: `/add`, `/search` with an `allowlist`, `/calibrate`). The **allowlist scopes a search to one dispute's documents**, so evidence from another order can't leak in.
  - Calibrate the index on a sample of embeddings first. Keep the full embeddings for exact re-scoring.
  - Fallback: plain vector search (pgvector or in-memory).

- **TurboVec-HippoRAG (third retriever in the fusion step):** from [`turbograph-research`](https://github.com/Aloneinthemultiverse/turbograph-research) (Java: `TurboHippo.java`, `TwoBitCodec.java`, `Methods.java`). Also in Auralis under `knowledge/hippo/` (`FactExtractor`, `HippoGraph`, `HippoIndex`) and `knowledge/graphvec/`.
  - A single knowledge graph: every node (passage, entity, fact) is stored as a **2-bit TurboQuant code**, and the edges are stored **exactly**.
  - Facts come from OpenIE extraction. Retrieval runs a **local-push Personalized PageRank** from the query's seed nodes, fused with dense scores (λ = 0.1).
  - **Measured results** (1,000 questions per dataset):

    | Dataset | Method | Index | R@5 | ms/query |
    |---|---|---|---|---|
    | HotpotQA | HippoRAG 2 (float, global PPR) | 641.8 MB | 0.870 | 598 |
    | HotpotQA | **TurboVec-HippoRAG fused** | **64.7 MB** | **0.871** | **151** |
    | HotpotQA | Dense 2-bit flat (no graph) | 2.6 MB | 0.858 | 12 |
    | MuSiQue | HippoRAG 2 (float, global PPR) | 693.3 MB | 0.600 | 685 |
    | MuSiQue | **TurboVec-HippoRAG fused** | **70.2 MB** | 0.555 | **162** |

  - **What it buys:** it keeps HippoRAG's **entity relationships** (which flat vector search doesn't have) at **9.9× less storage and ~4× lower latency** than HippoRAG 2.
  - **Complete evidence chains (All@5 = all supporting passages retrieved):**

    | Dataset | Dense 2-bit flat | TurboVec-HippoRAG fused |
    |---|---|---|
    | HotpotQA | 0.737 | **0.761** |
    | MuSiQue | 0.177 | **0.201** (~14% more complete chains) |

  - **Trade-off to state honestly:** single-hit recall (R@5) is about the same as flat search, and latency is higher than flat search (151 vs 12 ms). Quote the gains **vs HippoRAG 2**, plus All@5 vs flat search.
  - **Why it fits disputes:** a dispute is a chain (email → order → tracking → courier → proof of delivery). The graph links these as the **same entities**, which flat similarity can't do.
  - **For DisputeGraph:** dense 2-bit + BM25 for quick single-fact lookups; **TurboVec-HippoRAG for evidence chains** and cross-document questions (e.g. "which courier handled the replacement for the order this customer emailed about?").
  - Its entity/fact graph **is the merchant-side graph** that the reconciliation engine aligns with the PayPal graph.
  - Dispute eval should add a **chain-completeness metric** (were all the evidence docs for a claim retrieved?), not just recall.
- **Extraction:** an LLM pulls structured claims (`order_id`, `amount`, `dispatch_date`, `delivered`, `tracking_no`, `refund_amount`, …), each with a doc ID, page and quote.

### 3.4 Common data model
```
Entity types: Transaction, Order, Payment, Shipment, Refund, Dispute, EvidenceDoc, Event

Fact {
  entity:        "Order"
  field:         "amount"
  value:         75000
  currency:      "INR"
  source_side:   "paypal" | "merchant"
  source_ref:    "orders/v2/5O190127TN364715T#purchase_units[0].amount" | "invoice_123.pdf#p1"
  quote:         "Total: ₹75,000"           (merchant docs only)
  fetched_at:    ISO timestamp
  doc_hash:      sha256 (merchant docs)
  confidence:    0–1 (LLM extractions) | 1.0 (API)
  provenance:    "paypal_verified" | "merchant_provided" | "synthetic_demo"
}
```

### 3.5 Reconciliation engine
**Alignment:** match PayPal and merchant entities using `invoice_id` / `custom_id` → merchant order number, then transaction ID and tracking number.

**Deterministic checks (code only):**
| Check | Rule |
|---|---|
| Transaction ID | exact match |
| Amount + currency | exact (allow a defined tolerance for fees) |
| Order ID | exact via bridge key |
| Tracking number | normalised exact match |
| Refund status/amount | arithmetic + status mapping |
| Timeline | payment ≤ dispatch ≤ delivery ≤ dispute |

**LLM checks (fuzzy only):** event wording ("out for delivery" vs "delivered"), whether two phrases describe the same event, semantic conflicts in emails.

**Verdicts:**
| Verdict | Meaning |
|---|---|
| ✅ Match | Both sides agree |
| ❌ Value mismatch | Values differ |
| 🕒 Time mismatch | Dates or event order differ |
| ⬜ Missing | One side has no data. **Not a contradiction.** |
| ⚠️ Unsupported claim | A claim with no supporting evidence |
| 🛑 Contradiction | Evidence directly conflicts |

### 3.6 Agents
| Agent | Tools | Output |
|---|---|---|
| PayPal Analyst | PayPal REST / MCP, graph builder | PayPal facts + provenance |
| Merchant Evidence Analyst | RAG search, LLM extraction | Merchant claims + citations |
| Reconciliation Investigator | Verdict table, evidence checklist, both analysts | Evidence requests, updated status: resolved / unresolved / unverified |

Agents don't debate or vote. Each one produces grounded facts, and the decisions come from deterministic code.

**Investigator loop:**
```
verdicts → find ⚠️/⬜ items that matter for this dispute reason
        → generate a targeted request ("upload carrier tracking for order #A123")
        → merchant uploads / analysts search again
        → re-run reconciliation → update status
        → stop when resolved or max 3 rounds
```

### 3.7 Output / UI
| Element | Source |
|---|---|
| Plain-English summary | LLM, written **only** from verdicts; every sentence links to a finding |
| Deadline countdown | Dispute `seller_response_due_date` |
| Evidence strength bar | Checklist per dispute reason from PayPal's evidence docs (INR: tracking/carrier, or proof of delivery/docs) |
| Verdict grid (AG Grid) | Rows = fields; columns = PayPal · Merchant · Verdict · Source |
| Source click-through | Raw API field or document page + quote |
| Audit log | Each agent step: tool, input, output, timestamp |
| Evidence package | Maps to Disputes API `provide-evidence`: `tracking_info`, `notes`, `documents` |
| Human approval | Required before any submission |

### 3.8 Assessment gate: the four outputs (ported from TruthGuard)

Reused from [`truthguard-rag`](https://github.com/Aloneinthemultiverse/truthguard-rag) (`truthguard/assess.py`, `truthguard/controller.py`). **Core rule:** the LLM never writes a finding, summary or evidence package until the gate has checked the evidence. Hallucination is blocked by structure, not by prompting.

```
Retrieve (PayPal graph + merchant RAG) ──▶ ASSESS ──▶ Respond
                                             │
                    sufficiency · fact extraction (bi-temporal) · clash detection · answerability
```

| Gate verdict | Output | DisputeGraph meaning | Example |
|---|---|---|---|
| **SUFFICIENT** (or PARTIAL with high confidence) | **Cited answer** | The field is verified; every claim links to an API field or doc/page/chunk | "Amount ₹75,000 ✅ (orders/v2/…amount · invoice_A123.pdf p1)" |
| **contradictions non-empty** | **Dual answer with provenance** | Show **both** claims, each tagged with its source. **Never pick one.** Maps to the 🛑 Contradiction / ❌ Value mismatch verdicts | "PayPal refund: none · Merchant ledger: refunded ₹2,000 (refunds.csv row 14)" |
| **AMBIGUOUS** | **Clarification** (`clarify_options`, multiple choice) | Several valid readings, so the merchant picks one and we re-run **once** | "3 shipments for order #A123. Which one does this dispute cover?" · "Two PayPal captures match this invoice. Which one?" |
| **INSUFFICIENT** (after rewrites) | **Refusal + gap analysis** | Can't verify, so say so and list exactly what's missing. Maps to ⬜ Missing / ⚠️ Unsupported | "Delivery cannot be verified. Missing: carrier tracking or proof of delivery." |

#### Controller flow (per dispute question / field)
```
1. Pre-guard: asked about an order/date not in either source  → refusal immediately
2. assess(evidence)
3. AMBIGUOUS and not clarified yet       → clarify (stop; resume with the merchant's choice)
4. real contradictions                   → dual answer (never arbitrate)
5. SUFFICIENT / PARTIAL                  → cited answer, confidence-banded (high / hedge)
                                           band = refuse → treat as INSUFFICIENT
6. INSUFFICIENT                          → rewrite the retrieval query (max 2, drift-checked) → loop
7. Exhausted / LLM call cap              → refusal + gap analysis
```
The Reconciliation Investigator's "request evidence" step is the gap-analysis output: a refusal turns into a targeted evidence request.

#### Guards against false contradictions (reused from `_detect_clashes`)
| Guard | TruthGuard rule | DisputeGraph example |
|---|---|---|
| **Value-type only** | Only numeric/value facts can clash; names and prose can vary | Amounts, dates, quantities, tracking numbers can clash; product descriptions can't |
| **Different sources** | A clash must span different source files or systems | Two amounts in one invoice (subtotal vs total) aren't a conflict |
| **Scope qualifiers** | Different scope keys (e.g. role) aren't a conflict | Item-level partial refund vs order total; shipment 1 vs shipment 2 |
| **Superseded status** | A value marked superseded isn't a live conflict | A cancelled invoice vs the reissued invoice |
| **Bi-temporal windows** | Facts carry `valid_from` / `valid_until`; non-overlapping windows = timeline, not a conflict | Status "shipped" (12 Oct) then "delivered" (15 Oct) is history; "refunded" vs "not refunded" **as of the same time** is a conflict |
| **Evidence voting / OCR** | An OCR-only outlier against ≥2 agreeing sources is `possible_ocr_error`, not a contradiction | A scanned courier slip reads ₹7,500 while PayPal and the invoice both say ₹75,000 |
| **Relevance** | The clash must relate to the question | A mismatch on another order doesn't hijack this dispute |

**Deterministic first:** for PayPal ↔ merchant structured fields (IDs, amounts, currency, dates), clashes are computed in code. The TruthGuard LLM-triple path is used only for facts extracted from merchant documents.

#### Confidence (from `_confidence` / `_band`)
- Base = retrieval similarity × verdict weight (SUFFICIENT 1.0, PARTIAL 0.7, otherwise 0.4)
- × 0.5 if any conflict, and lowered further if the evidence comes from low-confidence OCR
- Bands: **high** → state it · **hedge** → state it with "likely" · **refuse** → refusal + gaps
- PayPal API facts get confidence 1.0; LLM-extracted merchant claims are banded.

#### Response shape
```json
{
  "kind": "answer | dual_answer | clarify | refusal",
  "text": "...",
  "confidence": 0.0,
  "band": "high | hedge | refuse",
  "citations": [{"side": "paypal|merchant", "ref": "...", "page": 1, "quote": "..."}],
  "contradictions": [{"subject": "...", "relation": "...", "kind": "contradiction|possible_ocr_error", "claims": [...]}],
  "clarify_options": ["..."],
  "gaps": ["missing: carrier tracking"],
  "trace": [{"step": "assess", "verdict": "..."}]
}
```
The `trace` feeds the audit log; `gaps` feed the investigator's evidence requests.

#### UI mapping
| Kind | UI |
|---|---|
| answer | Green/amber row + citation chips |
| dual_answer | Split cell: PayPal claim vs merchant claim, both linked; no winner shown |
| clarify | Multiple-choice prompt; the investigation pauses until answered |
| refusal | Grey row "Cannot verify" + list of missing evidence + an "Upload" button |

---

## 4. End-to-end flow (Item Not Received)

```
1. Buyer opens INR dispute (sandbox API)                    → webhook fires
2. PayPal Analyst: dispute → capture → order (graph)       → amount ₹75,000, completed, no delivery info
3. Merchant Analyst: invoice, dispatch receipt, note       → ₹75,000, dispatched 12 Oct, "delivered"
4. Reconcile: amount ✅ · dispatch (merchant only) · delivery ⚠️ · proof of delivery ⬜
5. Investigator: "Upload carrier tracking / proof of delivery for order #A123"
6. Merchant uploads courier PDF → re-run                    → delivery ✅ verified
7. UI: summary + strength 4/4 + deadline 3 days
8. Merchant approves → provide-evidence (carrier + tracking + docs)
```

## 5. Pre-dispute flow (refund mismatch)
```
Sweep → merchant order #B77 status "refunded ₹2,000"
      → PayPal: capture for #B77 has no refund
      → verdict ❌/⬜ → alert: "Refund not found in PayPal. Check before the customer disputes."
```

---

## 6. Tech stack
| Layer | Choice |
|---|---|
| Backend / orchestrator | Python, FastAPI |
| PayPal | REST APIs (Sandbox), PayPal MCP server / Agent Toolkit |
| Graph | NetworkX (in memory), saved as JSON |
| Storage | SQLite (facts, verdicts, audit log) + `data/raw/` JSON |
| Merchant retrieval | TurboVec + HippoRAG (fallback: plain vector search) |
| LLM | One provider API (extraction, fuzzy checks, summary) |
| Frontend | React + AG Grid |
| Hosting | Render (backend + frontend; public webhook URL) |

## 7. Suggested repo layout
```
disputegraph/
├── backend/
│   ├── paypal/        # auth, clients, graph builder
│   ├── merchant/      # ingestion, RAG, extraction
│   ├── reconcile/     # model, checks, verdicts
│   ├── agents/        # analysts + investigator
│   ├── api/           # FastAPI routes, webhook
│   └── eval/          # baseline vs DisputeGraph
├── frontend/          # React + AG Grid
├── data/
│   ├── raw/           # saved PayPal responses
│   └── synthetic/     # merchant docs (labelled)
├── scripts/           # sandbox setup: order → capture → dispute
├── .env.example
├── LICENSE
└── README.md
```

## 8. Security and guardrails
- Sandbox only; credentials in `.env` (git-ignored).
- The LLM never decides amounts, IDs or dates. Code does.
- Missing data is never reported as a contradiction.
- No fraud verdicts, and the system never decides who's right.
- A human approves before any evidence is submitted.
- Synthetic data is labelled throughout.

## 9. Open items to verify on day 1
- [ ] Dispute creation in Sandbox (buyer-side auth header, Disputes enabled on the app)
- [ ] Exact field names linking dispute ↔ transaction ↔ capture ↔ order
- [ ] Whether `invoice_id` / `custom_id` survive into the transaction and dispute records
- [ ] Webhook event name and delivery to Render
- [ ] `provide-evidence` behaviour in Sandbox
- [ ] Which PayPal MCP tools exist in the current package version
