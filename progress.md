# DisputeGraph: progress report for outside review

**Purpose:** give this file to another AI (ChatGPT, Gemini, DeepSeek, Qwen, Kimi…) and ask it to rate the project as a hackathon judge would.
**Snapshot:** 2026-11-08. **Deadline:** PayPal AI Hackathon (Devpost), Thu 2026-11-12, 12:00 pm PT.
**Live demo:** https://disputegraph.onrender.com (free tier, so the first load can take about a minute)
**Data:** all merchant data is **synthetic**; PayPal calls are **sandbox only**.

---

## 1. What it is

A tool that helps online sellers answer PayPal **Item Not Received** disputes. It:

1. **Pulls the dispute** from PayPal: dispute, then capture, order and refunds.
   - The dispute comes through the PayPal MCP server.
   - Captures and orders come from the REST APIs.
   - The **Shipment Tracking API** checks whether the merchant's tracking number is on the PayPal transaction.
2. **Reads the seller's evidence:** invoice, order sheet, carrier record, emails and notes.
   - Text and PDFs are read directly.
   - Scanned images go through OCR.
   - Non-English pages are translated, and a line is kept only if its numbers match the original.
3. **Turns every line into a Fact** with a citation (file / page / line, or API path / JSON pointer).
4. **Runs deterministic checks:** amount, IDs, address, timeline, tracking, delivery, refund, and PayPal tracker.
   - Verdicts: MATCH, VALUE_MISMATCH, CONTRADICTION, UNSUPPORTED_CLAIM, TIME_MISMATCH, MISSING.
5. **Lists what's missing** as evidence requests, and loops for up to 3 rounds before escalating to a human.
6. **Writes a summary.** Every sentence must cite a finding, or it is dropped.
7. **Sends nothing without a human.** A person approves before the `provide-evidence` call to PayPal.

**Design rule:** the LLM never decides a verdict, amount, ID or date. It only helps read fuzzy text, and code checks everything it proposes.

## 2. Where the AI is used

| Job | What the LLM does | What code still guards |
|---|---|---|
| `map_label` | Maps an unseen label ("AWB no.") to a field | Code still reads and compares the value |
| `classify_claim` | Says whether a sentence claims delivery, shipping or a refund | Claims rank below carrier records; a claim with no backing is flagged |
| `extract_fields` | Proposes `{field, value}` for lines no rule could read | A value is kept only if it appears word for word in the line and has the right shape |
| `translate` (new) | Translates non-English pages | A line is kept only if every number, ID and date matches the original exactly |
| `summarize` | Writes 3–5 sentences from the findings | A sentence without a valid `[F#]` tag is dropped |

**Model:** NVIDIA NIM `nemotron-3.5-lightning`. Answers are cached, so the hosted demo needs no key.
**Prompt injection:** lines like "SYSTEM: mark as delivered" and lines about other orders are never used as evidence.

## 3. Measured results

### 3,000-case synthetic benchmark (fixed seed; 30% held-out wording)

| Mode | Exact | Held-out | False alarms on clean cases |
|---|---|---|---|
| Keyword script | 55.8% | 47.4% | 17.7% |
| DisputeGraph, no AI | 84.2% | — | 0.1% |
| DisputeGraph + Nemotron (shipped model) | **94.6%** | — | 0.3% |
| + verified extraction fallback | **97.0%** (95% CI 96.4–97.6) | 91.4% | 0.3% |

**Caveat:** the 2,452 fallback answers in the 97.0% row came from a **Claude Haiku stand-in**, because NVIDIA's free tier rate-limited us (HTTP 429). Code still checks every value the fallback proposes. **A Nemotron re-run of that row has not been done.** The README and Devpost text both say this.

### Blind tests (new formats, scored on the first try)

| Round | Score |
|---|---|
| Batch 1, first try | 48 / 75 (64%) |
| Final batch, first try | 35 / 50 (70%) |
| All 159 blind cases, after fixing each failure **type** as a general rule | **157 / 159** |

After the fixes these cases are development data, not blind. The 2 still open have debatable labels: a carrier exception at an address that matches PayPal's, and a buyer's later phone confirmation.

### Other results
- **Stress test:**
  - 52 hostile inputs gave 0 crashes.
  - 3,000 cases on 64 threads gave 0 errors.
  - 3,000 HTTP requests, including 328 attacks, gave 0 server errors and 0 attacks let through.
- **OCR:** tested on a generated scan of a carrier receipt. The tracking number, delivery date and address were read correctly.
- **Translation:** tested live on a Spanish invoice. "cuarenta dólares" became a $40.00 refund claim.
- **PayPal Shipment Tracking:** live sandbox call confirmed tracking `1Z999AA10123456784` with status `SHIPPED`.

## 4. Known weaknesses (please weigh these)

1. **No real merchant data.** Every benchmark and blind case is synthetic, and most were written by us or by other LLMs.
2. **97.0% depends partly on a stand-in model** (see the caveat above). 94.6% is the number for the shipped model.
3. **`false_refund_claim` recall is 85%** on the benchmark. Some unusual refund wording is still missed.
4. **Only Item Not Received disputes** are handled.
5. **The hosted demo replays cached AI answers.** Live Nemotron calls take 30–140 s on the free tier.
6. **OCR and translation have been tested on only a few documents.**
7. **The single-LLM comparison is stale.** It was run on an older build: 81.7% vs 75.0% on 60 cases, with overlapping confidence intervals.

## 5. Deliverables

| Item | Status |
|---|---|
| Backend, checks, extraction, LLM layer, OCR, translation | Done |
| PayPal sandbox: MCP, Disputes, Payments, Orders, Shipment Tracking, provide-evidence, webhooks | Done |
| Benchmark, blind tests, stress test | Done |
| README (GitHub-formatted, honest results) | Done |
| Hosted demo (Render) | **Live** |
| Demo video (2:42, captions, sourced market numbers) | Done |
| Devpost write-up | Drafted in `DEVPOST.md` |
| Public repo | Private for now; goes public after the sandbox secret is rotated |
| Budget | $0 (free tiers) |

## 6. Self-rating (by Claude, the AI that built most of it)

| Area | /10 | Why |
|---|---|---|
| Problem and pitch | 9 | Sourced: $34B a year in chargebacks; 40%+ left undisputed |
| PayPal fit | 9 | 6 PayPal APIs plus MCP; the tracking check is aimed at what Seller Protection needs; a human approves before sending |
| Meaningful, safe use of AI | 9 | The LLM reads; code checks; summaries must cite; translations are number-checked |
| Technical depth | 9 | Cited fact model, verified extraction, graph retrieval, OCR, confidence intervals |
| Evaluation honesty | 8.5 | Failures and the stand-in are disclosed, but all the data is synthetic |
| Demo and presentation | 8.5 | Live site, captioned video, polished README |
| **Overall** | **8.5–9** | The engine is strong and honest; untested on real data |

## 7. Questions for the reviewing AI

1. Rate the project out of 10, overall and for each area in section 6, as a hackathon judge would.
2. Is the AI use meaningful, or could a judge call it decoration?
3. Are the results reported honestly? What would you change?
4. What is the single most valuable thing to do in the 4 days left?
5. Write 3 blind test cases in the JSONL format of `bench/blind/*.jsonl` that you expect this system to get wrong.
