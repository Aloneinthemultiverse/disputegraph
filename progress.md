# DisputeGraph: progress report for outside review

**Purpose:** hand this file to another AI (ChatGPT, DeepSeek, Qwen, Kimi, Gemini...) and ask it to rate the project.
**Snapshot date:** 2026-11-07. **Deadline:** PayPal AI Hackathon (Devpost), Thu 2026-11-12, 12:00 pm PT.
All data is **SYNTHETIC**; PayPal calls are sandbox only.

---

## 1. What it is

A tool that helps small online sellers answer PayPal disputes. It:

1. Pulls the dispute and the transaction from the PayPal sandbox.
2. Reads the seller's evidence folder: invoice, order sheet, courier tracking, emails and notes.
3. Turns every line into a **Fact** with a citation (`file / page / line`).
4. Runs **deterministic reconcile checks** (amount, invoice ID, tracking, ship-to, delivery, refund, timeline), each giving a verdict: MATCH, VALUE_MISMATCH, CONTRADICTION, UNSUPPORTED_CLAIM, TIME_MISMATCH or MISSING.
5. Gives the case a readiness label (READY_FOR_REVIEW or NEEDS_EVIDENCE) and writes a plain-English summary. **Every summary sentence must cite a finding, or it is dropped.**

**Design rule:** the LLM never decides a verdict, an amount, an ID or a date. It only helps *read* fuzzy text. Code checks everything it proposes.

## 2. Where the AI is used

| Job | What the LLM does | What code still guards |
|---|---|---|
| `map_label` | Maps an unseen label ("AWB no.", "Amount payable") to a field name | The value itself is still read and compared by code |
| `classify_claim` | Says whether a free-text line claims delivery, shipping or a refund | Claims are weighed below carrier records; an unbacked claim is flagged |
| `extract_fields` (new) | Proposes `{field, value}` for lines that no rule could read | A value is kept only if it appears **word for word** in the line and has the right shape (ID, money, date) |
| `summarize` | Writes 3–5 sentences from the findings | Any sentence without a valid `[F#]` tag is dropped |

**Blocking rules:** prompt-injection lines ("ignore previous instructions", "mark this as delivered", `system:`) and forwarded or other-order lines are never used as evidence.

- **Model shipped:** NVIDIA NIM `nemotron-3.5-lightning`, through any OpenAI-compatible endpoint.
- **Caching:** answers are cached, so the hosted demo replays with no key.

## 3. Measured results (3,000-case synthetic bench, 29 trap types)

| Version | Exact verdict | Held-out wording | Precision | False alarms on clean cases |
|---|---|---|---|---|
| Start of this session (AI) | 84.7% | 58.2% | — | — |
| + sentence reader, regex only (no LLM) | 82.0% | — | 0.994 | — |
| + sentence reader, with LLM | 92.1% | 80.2% | 0.997 | 0.3% |
| + "AWB no." fix (Nemotron, no fallback) | **94.6%** | 85.9% | — | — |
| + verified LLM fallback (see note) | **97.1%** (95% CI 96.6–97.7) | 91.5% | 0.998 | 0.3% |

**Note on the 97.1% row.** The fallback's answers came from **Claude Haiku** acting as a stand-in, because the NVIDIA free tier rate-limited us (429). The Haiku helpers read the lines and wrote their answers down partly as rules; the answers were spot-checked. The NVIDIA re-run is **not done**. Honest claim: **94.6% measured on the shipped model, 97.1% with the fallback on a stand-in model.**

### Other results

- **External cases.** 100 cases written by four other LLMs (25 each).
  - First **blind** run: 44–52%. This exposed that the system only read `Label: value` lines.
  - After adding the sentence reader (`freeform.py`): ChatGPT 100%, DeepSeek 100%, Qwen 100%, Kimi 88%. **This is no longer blind:** the fixes were made after seeing these cases.
- **Fuzz test:** 52 malformed inputs, 0 crashes; slowest case 3.9 s.
- **Demo cases:** stable across all changes. Two are READY_FOR_REVIEW and three are NEEDS_EVIDENCE.
- **Code graph check (graphify):** confirmed that retrieval (BM25 / HippoRAG-style graph) is used only for Q&A and search, **never on the verdict path**.

## 4. Known weaknesses (please weigh these)

1. **`false_refund_claim` recall is 85%.** Some unusual "we refunded you" wording is still missed.
2. **7 false `delivery_contradiction` flags** on the bench.
3. **Kimi-003 and Kimi-020 may be mislabelled** in the external set. Kimi-023 uses a "Delivered: YES" format the system misses.
4. **The bench is synthetic and written by us.** Even the "held-out" wording comes from our own generator. There is no real merchant data.
5. **The external set is no longer blind** (see above). A fresh blind batch has not been run.
6. **97.1% is not measured on the shipped model** (see above).
7. **The single-LLM baseline comparison is stale** (81.7%, from an older build).
8. **Small code nit:** `merchant.py` imports `freeform` twice. It's harmless but untidy.

## 5. Status of deliverables

| Item | Status |
|---|---|
| Backend (FastAPI), checks, extraction, LLM layer | Done |
| PayPal sandbox integration | Done (the sandbox secret must be **rotated** before the repo goes public) |
| Benchmark + fuzz + external cases | Done |
| README | Mostly done; needs the 94.6% / 97.1% numbers and the stand-in note |
| Git commit of this session's work | **Not done yet** |
| Public repo (MIT) | Pending |
| Hosted demo (Render) | Pending |
| Demo video (< 3 min) | Pending |
| Devpost write-up | Pending |
| Budget | $0 so far |

## 6. Self-rating (by Claude, the AI that built most of it)

| Area | Score /10 | Why |
|---|---|---|
| Idea / problem fit | 9 | A real seller pain point; on-theme for PayPal |
| Meaningful, safe use of AI | 9 | The LLM reads; code verifies; summaries need citations; injection is guarded |
| Technical depth | 8.5 | Cited fact model, verified extraction, ablation, confidence intervals |
| Evaluation honesty | 8.5 | Failures and stand-ins are disclosed, but the bench is synthetic and self-made |
| Robustness | 8 | 0 fuzz crashes; a few weak trap types remain |
| Polish / submission readiness | 6.5 | Video, deploy, Devpost text and the commit are still to do |
| **Overall** | **8.5 / 10** | Strong engine; the score now depends on demo, video and write-up |

**Biggest risks to the score:**

- Missing the deadline on the video or the deploy.
- A judge asking "was 97.1% run on Nemotron?" and getting a vague answer.

## 7. Questions for the reviewing AI

1. Rate the project out of 10 overall and for each area in section 6, as a hackathon judge would.
2. Is the AI use "meaningful", or could a judge call it decoration?
3. Are the results presented honestly? What would you change in how they are reported?
4. What is the single highest-value thing to do in the 5 days left?
5. Write 3 blind test cases (same JSONL format as `bench/external/*.jsonl`) that you expect this system to get wrong.
