# DisputeGraph: progress report for outside review

**Purpose:** give this file to another AI (ChatGPT, Gemini, DeepSeek, Qwen, Kimi…) and ask it to rate the project as a hackathon judge would.
**Snapshot:** 2026-11-08 (updated after the forged-evidence feature). **Deadline:** PayPal AI Hackathon (Devpost), Thu 2026-11-12, 12:00 pm PT.
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

### New: forged-evidence check
A merchant could upload an AI-made or edited "proof of delivery", so every uploaded image or PDF is scanned for signals:

| Signal | How |
|---|---|
| C2PA Content Credentials | The signed "made with AI" label from OpenAI, Adobe, Google and Microsoft, read with `c2pa-python` |
| Metadata | AI-tool or editor names in EXIF/XMP or the PDF producer |
| PDF history | Saved more than once, or modified long after it was created |
| Photo noise (ELA) | A patch much cleaner or noisier than the rest of the photo |
| Sightengine `genai` (optional, off by default) | A pixel-based AI-image model that still works when metadata was stripped |

A flag means **human review**, never automatic rejection. AI-made evidence sends the case to a person.

**Tested:**
- 9 files with known answers, including images **signed with real C2PA manifests** (AI-made, edited, camera): all correct.
- 18 real app screenshots: no false alarms from our own signals.
- **Live Sightengine:** a real photo scored 0%. Two dark-UI app screenshots scored **52% and 75%**, so the threshold was set at 90%; below that the score is shown but doesn't flag the file.
- **Real AI image:** a ChatGPT-generated "parcel on a doorstep" photo whose metadata had been removed (re-saved as WebP, no C2PA, no EXIF) scored **99% AI** on Sightengine, so it was flagged **likely_ai**.
- **Not yet tested:** real fraud cases at scale.

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
| DisputeGraph, no AI | 86.2% | — | 0.1% |
| DisputeGraph + Nemotron (shipped model) | **96.2%** | 91.1% | 0.3% |
| + verified extraction fallback | **98.7%** (95% CI 98.2–99.0) | 97.1% | 0.3% |

**Caveat:** the 2,452 fallback answers in the 98.7% row came from a **Claude Haiku stand-in**, because NVIDIA's free tier rate-limited us (HTTP 429). Code still checks every value the fallback proposes. **A Nemotron re-run of that row has not been done.** The README and Devpost text both say this.

**Refund fix (Nov 8):** we studied the benchmark's missed refund cases and added one general rule for money returned without the word "refund" ("sent the payment back", "money is on its way back"). Refund recall went from 85% to 98% with 0 new false positives, and the blind tests stayed at 157/159. Because that rule came from looking at benchmark misses, the held-out split is no longer fully unseen for refunds. Before the fix: 94.6% (Nemotron), 97.0% (with fallback), 91.4% held-out. The demo video still shows the older 94.6%.

### Blind tests (new formats, scored on the first try)

| Round | Score |
|---|---|
| Batch 1, first try | 48 / 75 (64%) |
| Final batch, first try | 35 / 50 (70%) |
| All 159 blind cases, after fixing each failure **type** as a general rule | **157 / 159** |

**Manually collected test set (159 cases):** none of these came from our own generator. They were written outside the codebase, by other AI models and by 3 reviewers, then collected and scored by hand. First try: 64%, then 70%. After fixing each failure *type* as a general rule: **157 / 159**.

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
2. **98.7% depends partly on a stand-in model** (see the caveat above). 96.2% is the number for the shipped model.
3. **`false_refund_claim` recall is now 98%** (was 85%), but the fix came from benchmark misses, so a fresh blind set is the real test.
4. **Only Item Not Received disputes** are handled.
5. **The hosted demo replays cached AI answers.** Live Nemotron calls take 30–140 s on the free tier.
6. **OCR, translation and the forged-evidence check have been tested on only a few files**, all generated by us. Sightengine has been tested on one real AI-generated image (99%, caught).
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
| Meaningful, safe use of AI | 9 | The LLM reads; code checks; summaries must cite; translations are number-checked; AI-made evidence is flagged for a human |
| Technical depth | 9 | Cited fact model, verified extraction, graph retrieval, OCR, C2PA and forgery signals, confidence intervals |
| Evaluation honesty | 8.5 | Failures and the stand-in are disclosed, but all the data is synthetic |
| Demo and presentation | 8.5 | Live site, captioned video, polished README |
| **Overall** | **9** | The engine is strong and honest; untested on real data |

## 7. Questions for the reviewing AI

1. Rate the project out of 10, overall and for each area in section 6, as a hackathon judge would.
2. Is the AI use meaningful, or could a judge call it decoration? Is the forged-evidence check convincing, or does it feel bolted on?
3. Are the results reported honestly? What would you change?
4. What is the single most valuable thing to do in the 4 days left?
5. Write 3 blind test cases in the JSONL format of `bench/blind/*.jsonl` that you expect this system to get wrong.
