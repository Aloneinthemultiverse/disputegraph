# DisputeGraph: Devpost submission text

## Tagline
Puts what PayPal recorded next to what the merchant can prove, and shows exactly what's missing.

## Inspiration
Chargebacks cost merchants about $34B a year, and that figure is forecast to reach $42B by 2028 (Mastercard / Datos Insights). Most online retailers leave over 40% of chargebacks undisputed (Riskified). The merchant usually wasn't wrong. Gathering the proof from invoices, emails and carrier pages before the deadline was just too hard.

## What it does
- Pulls a dispute from the PayPal sandbox through PayPal's MCP server and REST API.
- Reads the merchant's documents and turns both sides into facts.
- Runs deterministic checks on amount, IDs, address, timeline, tracking and delivery. Each check gets a verdict (MATCH, VALUE_MISMATCH, CONTRADICTION, UNSUPPORTED_CLAIM, TIME_MISMATCH or MISSING) and a citation to its source.
- Lists exactly what evidence is still needed, for example: "no carrier record for this tracking number".
- Sweeps across all cases, catching things like the same tracking number offered in two disputes.
- Nothing is sent to PayPal until a human approves it.

## How we built it
- Backend: Python and FastAPI. Graph and vector retrieval: TurboVec 2-bit index plus personalized PageRank.
- AI: NVIDIA NIM Nemotron. It only maps labels, classifies claims, extracts fields and writes the summary. Every AI sentence must cite a finding, or it is removed.

## Results
- 97.0% on a 3,000-case adversarial benchmark, with 0.3% false alarms.
- Blind cases we had never seen: 64%, then 70% on the first try. After fixing each failure type as a general rule: 155 of 159.
- Almost every failure came from reading messy input, such as carrier prefixes, typos, foreign postcodes and refunds written in words. When the facts were extracted correctly, the checks gave the right verdict.

## Challenges
Real dispute data is private, so we tested on synthetic and sandbox data only. Real-world accuracy is not yet measured.

## What's next
- OCR and translation for scanned and foreign-language documents.
- Testing on real merchant data, with consent.
- More dispute types beyond Item Not Received.

## Built with
python, fastapi, paypal-api, paypal-mcp, nvidia-nim, nemotron, networkx, hyperframes
