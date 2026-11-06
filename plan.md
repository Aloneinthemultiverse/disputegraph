# DisputeGraph — Build Plan (PayPal AI Hackathon)

**Deadline:** Thu Nov 12, 2026, **12:00 pm Pacific Time** (= Fri Nov 13, 12:30 am IST), from the official rules. The rules require the **PayPal sandbox environment**, so no live PayPal data.
**Pitch:** "Two systems. Two versions of the truth. One investigation engine."
**Target user:** A small PayPal seller (50–500 orders/month) who loses disputes they should win, because the proof is scattered across email, the courier site and their order sheet.
**Target prizes:** Top 3, Most Impactful, Best Use of PayPal + AI, Best Use of AG Grid (+ Render hosting).

---

## 1. Architecture (summary)

```
TRIGGERS ─▶ PAYPAL SIDE ─┐
                         ├─▶ RECONCILIATION ENGINE ─▶ INVESTIGATOR LOOP ─▶ UI ─▶ HUMAN APPROVAL ─▶ SUBMIT EVIDENCE
TRIGGERS ─▶ MERCHANT SIDE┘
```

| Layer | What it does |
|---|---|
| **Triggers** | Dispute webhook (`CUSTOMER.DISPUTE.CREATED`), scheduled refund-mismatch sweep |
| **PayPal side** | Orders / Payments / Disputes / Transaction Search via REST + PayPal MCP server → **PayPal Graph** (links records by ID) |
| **Merchant side** | Synthetic invoices, receipts, courier docs, emails → TurboVec + HippoRAG → facts with citations |
| **Bridge key** | `invoice_id` / `custom_id` = the merchant's order number ↔ the PayPal order |
| **Reconciliation** | Common model; deterministic checks (IDs, amounts, dates, tracking, refunds); LLM only for fuzzy wording |
| **Verdicts** | Match · Value mismatch · Time mismatch · Missing · Unsupported claim · Contradiction (Missing ≠ Contradiction) |
| **Agents** | PayPal Analyst · Merchant Evidence Analyst · Reconciliation Investigator (requests missing evidence, re-runs) |
| **Output** | AG Grid investigation screen, summary, evidence strength, deadline, audit log, evidence package → human approves → `provide-evidence` |

**Stack:** Python + FastAPI · NetworkX · React + AG Grid · one LLM API · TurboVec + HippoRAG · Render

---

## 2. Feature list

### Must ship (core)
- [ ] Real Sandbox flow: order → capture → INR dispute (created via API)
- [ ] PayPal Graph builder (dispute → capture → order → refund, linked by IDs)
- [ ] Common data model with provenance on every fact
- [ ] Merchant evidence RAG with doc/page citations
- [ ] Reconciliation engine: 5 deterministic checks + 6 verdict types
- [ ] Reconciliation Investigator loop (request evidence → re-run → update status)
- [ ] AG Grid investigation screen with click-through to the source
- [ ] Evidence package → **human approval** → Disputes API `provide-evidence` (sandbox)
- [ ] **Assessment gate with four outputs (ported from TruthGuard)** (see arch.md §3.8):
  - [ ] Cited answer (SUFFICIENT): every claim linked to an API field or doc/page
  - [ ] Dual answer (contradictions): both claims shown with sources, never arbitrated
  - [ ] Clarification (AMBIGUOUS): multiple-choice `clarify_options`, re-run once
  - [ ] Refusal + gap analysis (INSUFFICIENT): states what's missing → feeds evidence requests
  - [ ] False-contradiction guards: value-only, cross-source, scope, superseded, bi-temporal, OCR outlier, relevance
  - [ ] Confidence bands (high / hedge / refuse)
  - [ ] Test case per output (4 cases minimum in the eval set)

### Added extras (cheap, high return)
- [ ] **Deadline countdown:** seller response deadline from the Disputes API, colour-coded
- [ ] **Evidence strength bar:** "Covers X of Y items PayPal asks for in INR disputes" (checklist from PayPal's official dispute reasons and evidence docs)
- [ ] **Plain-English summary:** LLM-written from verdicts only, each sentence linked to a finding
- [ ] **Audit log:** what each agent fetched, when, from which API/doc
- [ ] **Webhook listener:** new dispute auto-starts an investigation (verify the event name in Sandbox)
- [ ] **Before/after number:** time one manual investigation vs DisputeGraph

### Small extension
- [ ] Pre-dispute refund-mismatch sweep (merchant says "refunded", PayPal shows no refund)

### Only if ahead of schedule on Nov 10
- [ ] Agent-purchase dispute case (agentic commerce angle)
- [ ] Postman collection of the API calls
- [ ] Drafted buyer message (draft only, merchant approves)

### Do not build
- More dispute types, fraud scoring, Neo4j, real Shopify/Gmail integrations, login/multi-merchant, more agents

---

## 3. Day-by-day plan

| Day | Goal | Done when |
|---|---|---|
| **Nov 5** | Sandbox spike | Sandbox app with **Disputes enabled**; order → capture → INR dispute via API; all raw JSON saved in `data/raw/`. **If disputes fail, switch the main flow to refund mismatch tonight.** |
| **Nov 6** | PayPal graph + common model | Pull Orders/Captures/Refunds/Disputes and link them in NetworkX; schema defined; deadline field extracted |
| **Nov 7** | Merchant side | 5–8 synthetic cases tied to real sandbox IDs via `invoice_id`; RAG returns facts + citations; every doc labelled SYNTHETIC |
| **Nov 8** | Reconciliation engine + assessment gate | 5 checks + 6 verdicts working on all cases; **TruthGuard gate ported (`assess.py`/`controller.py`) with all 4 outputs and clash guards**; at least one synthetic case triggering each output; evidence-strength checklist; audit log records each step |
| **Nov 9** | Investigator loop + UI | Agent requests evidence and re-runs; AG Grid screen; deadline countdown; plain-English summary; source click-through |
| **Nov 10** | Submission + extras + deploy | Human approval → `provide-evidence`; webhook listener; refund-mismatch sweep; Render deploy; mini evaluation (one LLM vs DisputeGraph, ~20 cases); time manual vs tool. **Feature freeze at end of day.** |
| **Nov 11** | Package | Bug fixes only; README, LICENSE, tools section, Devpost text; record demo video under 3 minutes and upload it (public, YouTube) |
| **Nov 12** | Buffer | Submit early. No new features. |

---

## 4. Evaluation (answers "why not ChatGPT?")
- About 20 synthetic cases tied to real Sandbox transactions, with known correct answers
- Compare: **single LLM on raw docs** vs **DisputeGraph**
- Metrics: mismatch precision/recall, unsupported-claim rate, false alarms, time per case
- Supporting research: FinBalance (arXiv, Jun 2026). The best of six LLMs reaches 46% on multi-document reconciliation and struggles to link entries to documents.

---

## 5. Demo video script (under 3 minutes)
1. **Problem (20s):** A small seller loses about $166–190 per dispute, and the evidence is scattered.
2. **A dispute arrives (15s):** The webhook fires and the deadline countdown appears.
3. **Investigation (60s):** PayPal facts vs merchant claims, AG Grid verdicts, click through to the source.
4. **Gap found (30s):** The "delivered" claim is unsupported. The investigator asks for tracking; the merchant uploads it; the result turns verified.
5. **Submit (20s):** Summary + evidence strength → human approves → sent to PayPal.
6. **Bonus (15s):** The refund-mismatch sweep catches a problem before it becomes a dispute.
7. **Proof (20s):** Before/after time and the LLM-vs-DisputeGraph comparison.

---

## 6. Submission checklist
- [ ] Public GitHub repo, **LICENSE** (MIT) visible in the About section
- [ ] README: setup + run steps, architecture, `.env.example`
- [ ] `.env` in `.gitignore`, no secrets committed
- [ ] **Runnable build ($0 budget).** A video alone does NOT count as the functional demo:
  - [ ] README run instructions + one-command start (`docker compose up` or `run.bat`/`run.sh`). This alone meets the rule.
  - [ ] Free hosted demo (Render free tier or Hugging Face Space) with a "first load ~1 min" banner
  - [ ] 3–5 seeded disputes loaded at startup
  - [ ] Demo mode that replays cached LLM responses, so the hosted demo works without API quota
  - [ ] 1–2 min setup video embedded on the hosted page + linked in the README
  - [ ] Sandbox test account logins for judges in the README (test-only, never real `.env` secrets)
- [ ] "Tools used" section: LLM, PayPal APIs, PayPal MCP server, AG Grid, TurboVec + HippoRAG
- [ ] Synthetic data clearly labelled
- [ ] YouTube video (public, under 3 minutes, no copyrighted music)
- [ ] Devpost text: problem, user, how it works, what's real vs synthetic

---

## 7. Claims to avoid
- "Detects fraud" · "Accesses PayPal's global data" · "AI decides who's right" · "No PayPal delivery record = not delivered" · RAG benchmark numbers without a documented baseline

---

## 8. Risks
| Risk | Fallback |
|---|---|
| Sandbox dispute creation fails | Make the refund mismatch the main flow (Orders/Captures/Refunds only) |
| Webhook won't reach localhost | Use the Render URL, or a polling `list_disputes` button |
| `provide-evidence` fails in Sandbox | Show the approved evidence package plus the exact API request; say so honestly |
| TurboVec/HippoRAG integration slips | Ship dense 2-bit TurboVec + BM25 (Auralis); TurboVec-HippoRAG (`turbograph-research`, Java) is optional. Pitch numbers only "vs HippoRAG 2": 9.9× smaller, ~4× faster, same R@5 on HotpotQA |
| Running out of time | Cut in this order: webhook → summary → refund sweep → evaluation |

---

## 9. References
- [PayPal Disputes integration guide](https://developer.paypal.com/docs/disputes/integration-guide/)
- [Integrate Disputes APIs](https://developer.paypal.com/platforms/disputes/integrate-disputes)
- [Dispute reasons and evidence](https://developer.paypal.com/platforms/disputes/reference/dispute-reasons)
- [Dispute API test values](https://developer.paypal.com/platforms/disputes/reference/dispute-api-test-values)
- [PayPal Agent Toolkit / MCP](https://playbooks.com/mcp/paypal-agent-toolkit)
- [FinBalance benchmark](https://papers.cool/arxiv/2606.15949)
- [Chargeback cost stats](https://www.chargeflow.io/blog/chargeback-statistics-trends-costs-solutions)
- [Hackathon page](https://paypalaihackathon.devpost.com/)
