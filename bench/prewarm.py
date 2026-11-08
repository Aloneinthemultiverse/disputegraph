"""Fill the LLM cache for every unseen label / fuzzy claim line in the bench, in parallel."""
import json, re, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv; load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from backend.disputegraph import merchant, llm

labels, lines = set(), set()
for p in [Path(__file__).parent / "cases.jsonl", *sorted((Path(__file__).parent / "external").glob("*.jsonl"))]:
    for row in p.read_text(encoding="utf-8").splitlines():
        if not row.strip(): continue
        for text in json.loads(row)["docs"].values():
            for line in text.splitlines():
                if merchant.SCAN.match(line.strip()): continue
                if m := merchant.LINE.match(line):
                    lab = m.group(1).strip().lower()
                    if any(re.fullmatch(p_, lab) for p_ in merchant.LABELS): continue
                    labels.add(lab)  # unknown label; if it maps to nothing the line is read as a sentence
                if merchant.INJECTION.search(line): continue
                if not any(p_.search(line) for p_, _, _ in merchant.CLAIMS) and llm.HINT.search(line):
                    lines.add(line)
ext = set()
import bench.bench as bb
for p in [Path(__file__).parent / "cases.jsonl", *sorted((Path(__file__).parent / "external").glob("*.jsonl"))]:
    for row in p.read_text(encoding="utf-8").splitlines():
        if not row.strip(): continue
        c = json.loads(row)
        orig = merchant.extract_fields
        merchant.extract_fields = lambda line: (ext.add(line), [])[1]  # record, don't call
        merchant.classify_claim, merchant.map_label = (lambda l: None), (lambda l: None)
        try: merchant.extract(c["paypal"]["invoice_id"], bb.pages(c))
        finally: merchant.extract_fields = orig
merchant.classify_claim, merchant.map_label = llm.classify_claim, llm.map_label
print(len(labels), "labels,", len(lines), "claim lines,", len(ext), "extract lines")
if "--count" in sys.argv: sys.exit()
with ThreadPoolExecutor(4) as ex:
    list(ex.map(llm.map_label, sorted(labels)))
    list(ex.map(llm.classify_claim, sorted(lines)))
    list(ex.map(llm.extract_fields, sorted(ext)))
print({l: llm._LABEL_MEMO.get(l) for l in sorted(labels)[:40]})
