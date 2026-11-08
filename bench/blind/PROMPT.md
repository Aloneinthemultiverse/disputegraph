# Prompt for a fresh blind batch

Paste everything below the line into another AI (ChatGPT, Gemini, DeepSeek, Qwen, Kimi, Grok...).
Save its answer as `bench/blind/<ai-name>.jsonl`, then run `python bench/blind/score.py --ai -v`
**before changing any code**. That first score is the blind number.

---

You are writing test cases for a tool that checks a small online seller's evidence in a PayPal dispute. You cannot see its code. Try to write cases it gets **wrong**, but every case must have a correct, defensible answer.

Write **25 cases**, one JSON object per line (JSONL), with no other text and no code fences. Each line uses exactly this shape:

{"id": "x-001", "labels": [], "paypal": {"amount": "128.90", "invoice_id": "INV-88412", "custom_id": "PO-7781", "captured_at": "2026-10-14T09:00:00Z", "ship_to": {"admin_area_2": "Springfield", "postal_code": "62704"}, "refunds": []}, "docs": {"invoice": "...", "order_sheet": "...", "courier_tracking": "...", "emails": "...", "notes": "..."}, "why": "one sentence explaining the correct answer"}

**Rules:**

- `paypal` is the truth from PayPal. `refunds` is a list of refunded amounts as strings, e.g. ["58.75"].
- `docs` is the seller's evidence. Use any subset of the keys `invoice`, `order_sheet`, `courier_tracking` (the carrier's own record), `emails` and `notes` (the seller's own statements). Write the text however real paperwork looks: labels, sentences, OCR noise, other date formats, other carriers, forwarded emails and so on. Use `\n` for new lines.
- `labels` lists every problem in the case, using only these names:
  - `amount_mismatch`: the invoice or order total differs from the PayPal amount.
  - `id_mismatch`: the invoice number differs from the PayPal invoice_id.
  - `ship_to_mismatch`: the carrier delivered to a different city or postcode than PayPal's ship_to.
  - `tracking_mismatch`: the tracking number the seller gives differs from the one on the carrier record.
  - `delivery_contradiction`: the seller says delivered, but the carrier record for this order says not delivered (in transit, exception, returned...).
  - `delivery_unsupported`: the seller says delivered, but there is no carrier record at all.
  - `early_ship`: the seller says it shipped before PayPal's captured_at date.
  - `impossible_timeline`: the carrier shows delivery before the item was shipped.
  - `false_refund_claim`: the seller says the buyer was refunded (or refunded more than PayPal shows), but PayPal's refunds do not support it.
- Use `[]` for a clean case with no problems. Make about 30% of the cases clean but tricky (they look suspicious but are fine).
- Use only synthetic, made-up data. Use USD amounts.
