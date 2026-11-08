# DisputeGraph: demo video script (~2:30)

Voice: en-US-AndrewNeural (edge-tts, free). Visuals: real app screenshots + HTML diagrams.

| # | Scene | Narration | On screen |
|---|---|---|---|
| 1 | hook | A merchant gets a PayPal dispute. Item not received, one hundred twenty-nine dollars. The proof is scattered across invoices, emails and carrier pages. | Dispute card, deadline ticking, scattered doc chips |
| 2 | idea | DisputeGraph puts two truths side by side: what PayPal recorded, and what the merchant can prove. | Hero headline from the app |
| 3 | design | It pulls the dispute from the PayPal sandbox, reads the merchant's documents, and turns both into facts. Then deterministic checks compare amount, IDs, address, timeline, tracking and delivery. Every check gets a verdict, with a citation. | Diagram grows: PayPal + Merchant → Facts → 6 checks → verdicts |
| 4 | ai | AI, NVIDIA Nemotron, maps messy labels, classifies claims and writes the summary. Every AI sentence must link to a finding, or it is removed. | AI box; summary lines with F-tags |
| 5 | case | Here's the case. Four of the six items PayPal looks for are already in place. | App overview, strength 4/6 |
| 6 | missing | And when something is missing, it says exactly what: no carrier record for this tracking number, so delivery can't be verified. | "What we still need" panel |
| 7 | twist | The merchant uploads a carrier update. Strength rises to five of six. But DisputeGraph notices the tracking number is different. The proof may be for another parcel. | After-evidence screen, F9 highlighted |
| 8 | sweep | Across all cases, a sweep finds the same tracking offered in two disputes, and a refund the merchant claims that PayPal never recorded. | Sweep card |
| 9 | human | And nothing is sent to PayPal without a human approving it. | Approval line |
| 10 | results | We tested on blind cases we had never seen. First try: sixty-four percent, then seventy. After fixing each failure type as a general rule: one fifty-five of one fifty-nine. False alarms: zero point three percent. | Numbers land |
| 11 | failures | Here's where it failed: carrier prefixes, mistyped IDs, foreign postcodes, refunds written in words, dates read as tracking numbers. Four ambiguous cases are still open. | Failure list, struck through when fixed |
| 12 | limits | Our honest limit: real dispute data is private, so we tested on synthetic and sandbox cases only. Next: OCR and translation for scanned and foreign documents. | Limitation + next |
| 13 | end | DisputeGraph. It doesn't guess. It asks. | Logo line |
