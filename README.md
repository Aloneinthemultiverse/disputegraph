# DisputeGraph

**Two systems. Two truths. One investigation.**

A small PayPal seller loses disputes they should win because the proof is scattered across their order sheet, emails and the courier site. DisputeGraph reconciles what **PayPal recorded** with what the **merchant can prove**. It cites every fact back to the exact API field or document line and asks for the evidence that's missing. When the sources disagree, it shows both sides instead of guessing. Nothing goes to PayPal until a human approves it.

Built for the PayPal AI Hackathon. **PayPal sandbox only. All merchant documents are SYNTHETIC.**

## What it does

1. **PayPal graph.** Starting from a dispute ID, it follows the IDs: dispute → capture → order → refunds, with invoice number and custom ID as the bridge to merchant records. The dispute is fetched through the **official PayPal MCP server** (`@paypal/mcp`, Agent Toolkit, `get_dispute` tool). Captures and orders come from the Payments v2 and Orders v2 REST APIs, and REST is the fallback if MCP is unavailable.
2. **Merchant evidence.** It reads invoices, order sheets, courier tracking and emails. Rules extract IDs, amounts, dates and tracking numbers with doc/page/line citations. **An LLM reads fuzzy wording** the rules miss, such as "our driver left it on your porch".
3. **Reconciliation.** Six deterministic checks (IDs, amount, ship-to, timeline, delivery, refunds) produce six verdicts: Match, Value mismatch, Time mismatch, Missing, Unsupported claim, Contradiction. *Missing is not a contradiction*, and a courier record outranks a merchant's own claim.
4. **Assessment gate**, ported from the author's TruthGuard project. Every question ends in one of four outputs:
   - cited answer
   - dual answer (both sides shown, never arbitrated)
   - clarifying question
   - refusal that lists what's missing

   It uses confidence bands (high / hedge / refuse) and up to two query rewrites.
5. **Investigator loop.** It turns gaps into evidence requests. The merchant adds evidence and the case re-runs, up to 3 rounds, then escalates to a human. Every step is in the audit log.
6. **TurboVec-HippoRAG evidence retrieval.** This is a Python port of the author's turbograph-research method (`Methods.pushPpr`, fused 2-bit + push-PPR with SCAN seeds).
   - Every evidence line is a **2-bit TurboQuant code** (`turbovec`), 16× smaller than float32.
   - Entity edges are stored **exactly**: tracking numbers, invoice and order IDs, amounts, dates, carriers and delivery states, plus each line's neighbour in the same document.
   - Personalized PageRank (local push, α=0.15, ε=1e-4) starts from the best 2-bit hits and any entities named in the question. Ranking = 2-bit score + λ·PPR, with λ=0.1.
   - Lines linked through a shared entity rise even when the wording differs, e.g. the courier scan for the same tracking number. The UI shows the entity path for each hit.
   - Embeddings are NVIDIA NIM `nemotron-3.5-embed-1b` (2048-d), cached for the demo.
7. **AI summary.** An LLM writes a plain-English summary **only from the verdicts**. Every sentence must carry a `[F<n>]` tag pointing to a finding. Untagged sentences are dropped, so the model can't add claims.
8. **Human approval → PayPal.** Only verified facts go into the evidence package. Unresolved mismatches are left out, and a contradicted delivery blocks sending. A person ticks *reviewed* and enters their name, then DisputeGraph calls `provide-evidence`.
9. **Extras:**
   - deadline countdown from `seller_response_due_date`
   - evidence-strength checklist for Item Not Received
   - refund-mismatch sweep
   - webhook listener (`CUSTOMER.DISPUTE.*`, signature verified)
   - timing for each investigation, plus a **manual-vs-DisputeGraph stopwatch**: time yourself checking a case by hand, then compare

## What's real and what's synthetic

| | |
|---|---|
| **Real (PayPal sandbox)** | Dispute `PP-R-QYH-10196792`: a real sandbox order, capture and Item Not Received dispute. A real `provide-evidence` call returned HTTP 200, and the dispute moved to UNDER_REVIEW. |
| **Synthetic** | All merchant documents. Demo disputes `PP-D-DEMO-0002…0005` are synthetic replays shaped like the real responses, made with `scripts/seed_demo.py` to cover every verdict type. |

## Run it (free, about 2 minutes)

You need Python 3.11+.

```bash
git clone <this repo> && cd disputegraph
pip install -r requirements.txt
```

**Demo mode** needs no keys. It replays the cached sandbox responses:

```bash
# Windows
run.bat
# macOS / Linux
./run.sh
```

Then open http://localhost:8000. Try these:
- **Pick a case.** `PP-R-QYH-10196792` is the real sandbox dispute.
- **Load sample carrier update → Add evidence.** Delivery flips from Contradiction to Match.
- **Ask questions:**
  - "Was the laptop delivered?" gives a dual answer.
  - "Is everything ok?" gives a clarifying question.
  - "Did the buyer sign for it?" gives a refusal.
- **Click any citation** to see the exact API field or document line.
- **Run the refund sweep.**
- **Use Reset demo** to start again.

**Live mode** uses your own sandbox:
1. Copy `.env.example` to `.env`.
2. Add a **US** sandbox app's Client ID and Secret, with *Customer disputes* and *Transaction search* ticked.
3. Optionally add an LLM endpoint. NVIDIA NIM (`https://integrate.api.nvidia.com/v1`) is free and also provides embeddings; any OpenAI-compatible endpoint works for the LLM. Set `PAYPAL_USE_MCP=1` (needs Node.js) to read disputes through the PayPal MCP server.
4. Run `python -m uvicorn backend.app:app --port 8000`.

To make a fresh sandbox dispute:
1. Run `python scripts/sandbox_spike.py order`.
2. Approve the payment as the sandbox **Personal** buyer.
3. Run `capture <ORDER_ID>`.
4. Open the dispute from the buyer's sandbox Resolution Center.

Sandbox test logins (sandbox only, not real accounts) are in the Devpost submission.

## Evaluation

`python eval/run_eval.py` generates 20 synthetic cases with 24 planted issues and known answers. It scores DisputeGraph, and a single LLM reading the raw records when an LLM key is set.

| | Precision | Recall | Missed issues | Exact cases | Avg time per case |
|---|---|---|---|---|---|
| **DisputeGraph** (deterministic checks + gate) | 1.00 | **1.00** | 0 / 24 | **20/20** | < 1 ms |
| Single LLM reading the raw records (Nemotron 3.5 Lightning via NVIDIA NIM) | 1.00 | 0.63 | 9 / 24 | 14/20 | ~51 s |

The single LLM never raised a false alarm, but it **missed 9 of the 24 planted issues**: amount mismatches, unsupported delivery claims, and in one case everything. It does worst on cases with several problems at once, which matches the FinBalance finding that LLMs struggle to tie entries across documents.

These cases use the document formats the rules were written for, so DisputeGraph's 100% is an **upper bound**, not a real-world claim. The point is that IDs, amounts and dates are checked by code, and the LLM is kept to wording. Raw results are in `eval/results.json`.

## Architecture

```
dispute webhook / picker
      │
PayPal Analyst ── PayPal MCP get_dispute + REST ─▶ PayPal graph (NetworkX) ─┐
Merchant Analyst ── docs ─▶ rules + LLM (fuzzy) ─▶ facts w/ citations ─────┤
                   docs ─▶ TurboVec 2-bit codes + exact entity graph + push-PPR ─▶ supporting passages
                                                                           ▼
                         Reconciliation (6 checks, 6 verdicts)
                                     │
             TruthGuard gate (answer / dual / clarify / refuse) + LLM summary
                                     │
           Investigator loop ─▶ AG Grid UI ─▶ human approval ─▶ provide-evidence
```

More detail is in `arch.md` and `plan.md`.

## Tools used

- **PayPal:** official PayPal MCP server / Agent Toolkit (`@paypal/mcp`), plus REST APIs (Orders v2, Payments v2, Disputes v1 incl. `provide-evidence`, webhook verification) on the sandbox.
- **AI:** NVIDIA NIM (`nvidia/nemotron-3.5-lightning-30b-a3b`), or any OpenAI-compatible LLM, used for fuzzy-claim reading and the citation-locked summary. Responses are cached in `data/llm_cache/` for the hosted demo.
- **Stack:** Python, FastAPI, Pydantic, NetworkX; AG Grid Community for the investigation grid.
- **Retrieval:** `turbovec` 2-bit TurboQuant index + push-PPR graph, ported from the author's turbograph-research (TurboVec-HippoRAG) project. NIM embeddings are cached in `data/embed_cache/`.
- **Assessment gate:** ported from the author's TruthGuard project.

## Limits

- Only Item Not Received disputes are supported.
- Merchant evidence is synthetic text, not real Shopify or Gmail integrations.
- MCP is used to read disputes; captures, orders and `provide-evidence` still go through REST, because the MCP toolset doesn't expose them.
- With no NIM key, questions that aren't cached are embedded with a hashed bag-of-words fallback. The UI labels this.
- The LLM (a reasoning model) is slow live, about 30–140 s per call; the demo replays cached answers.

## License

MIT. See `LICENSE`.
