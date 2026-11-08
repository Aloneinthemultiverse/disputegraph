# DisputeGraph: Devpost submission text

## Tagline
Merchants lose disputes they should win. DisputeGraph finds the proof, flags the gaps, and never makes a number up.

## Tested, not just demoed
**Most AI demos show it works once. We tested ours on 3,000 cases, and we publish where it fails.**

| | Exact verdicts | False alarms |
|---|---:|---:|
| Keyword script | 55.8% | 17.7% |
| **DisputeGraph + NVIDIA Nemotron** | **94.6%** | **0.3%** |
| Blind cases we had never seen (after fixing each failure *type*) | **157 / 159** | |

Live demo: https://disputegraph.onrender.com

## The problem
- Chargebacks cost merchants **$34B a year**, rising to **$42B by 2028** (Mastercard / Datos Insights).
- Most online retailers leave **over 40% of chargebacks undisputed** (Riskified).
- They usually weren't wrong. The proof was spread across invoices, emails and carrier pages, and the deadline came first.
- PayPal handles **$487B a quarter** (Q3 2026 earnings), so even a small win rate on that scale is real money for merchants.

## What it does
DisputeGraph puts two truths side by side: what PayPal recorded, and what the merchant can prove.

1. **Pulls the dispute** from PayPal: sandbox REST API plus PayPal's MCP server.
2. **Reads the merchant's evidence:** text, PDFs, scanned receipts (OCR) and non-English documents (translated, with every number checked).
3. **Checks six things in code:** amount, IDs, address, timeline, tracking and delivery. Each check gets a verdict that cites the exact API field or document line.
4. **Says exactly what's missing,** for example "no carrier record for tracking 1Z…, so delivery can't be verified". That turns a vague case into a to-do list.
5. **Checks PayPal's own tracking record** with the PayPal Shipment Tracking API: is the merchant's tracking number actually on the PayPal transaction? Seller Protection relies on this. In the sandbox it confirms tracking 1Z999AA10123456784 with status SHIPPED.
6. **Flags forged or AI-made evidence.** It reads C2PA Content Credentials (the signed "made with AI" label from OpenAI, Adobe, Google and Microsoft), AI-tool and editor metadata, PDF edit history, and noise inconsistencies in photos. A flag means a person checks the file before anything is sent. It never rejects a file automatically.
7. **Sweeps across all cases,** catching things like the same tracking number offered in two disputes, or a refund the merchant claims that PayPal never recorded.
8. **A human approves** before anything is sent to PayPal.

## Why judges can trust it
- **AI never decides a number.** NVIDIA Nemotron only reads messy wording and writes the summary.
- **Every AI sentence must cite a finding,** or it is removed automatically.
- **Code checks AI-extracted values** against the source line. Translations are kept only if every number survives unchanged.

## Results (honest)
| Test | Score |
|---|---|
| 3,000-case adversarial benchmark, Nemotron only | **94.6%** exact, **0.3%** false alarms (a keyword baseline gets 55.8% with 17.7% false alarms) |
| Same, plus the verified field-extraction fallback | **97.0%**. The fallback's answers came from a Claude Haiku stand-in because NVIDIA's free tier rate-limited us; a Nemotron re-run is pending |
| Blind cases, first try | 64%, then 70% |
| Blind cases, after fixing each failure *type* as a general rule | **157 / 159** |

**Manually collected test set (159 cases):** none of these came from our own generator. They were written outside the codebase, by other AI models and by 3 reviewers, then collected and scored by hand. First try: 64%, then 70%. After fixing each failure *type* as a general rule: **157 / 159**.

Almost every first-try failure came from reading messy input, not from the reasoning. When the facts were extracted correctly, the checks gave the right verdict.

**Limit:** real dispute data is private, so all testing used synthetic and sandbox cases.

## How we built it
Python, FastAPI, NetworkX, a TurboVec 2-bit vector index with personalized PageRank retrieval, NVIDIA NIM (Nemotron), and the PayPal REST APIs (Disputes, Payments, Orders, Shipment Tracking, provide-evidence, webhooks) and the PayPal MCP server. It's deployed on Render, and the demo video was made with HyperFrames.

## What's next
- A pilot on real merchant disputes, with consent.
- More dispute types beyond Item Not Received.
- Shopify and Gmail connectors, so evidence is collected automatically.

## Links
- Live demo: https://disputegraph.onrender.com (the first load can take about a minute)
- Code: https://github.com/Aloneinthemultiverse/disputegraph

## Built with
python, fastapi, paypal-api, paypal-mcp, nvidia-nim, nemotron, networkx, render, hyperframes
