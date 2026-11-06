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
                    if not any(re.fullmatch(p_, lab) for p_ in merchant.LABELS): labels.add(lab)
                elif not any(p_.search(line) for p_, _, _ in merchant.CLAIMS) and llm.HINT.search(line):
                    lines.add(line)
print(len(labels), "labels,", len(lines), "claim lines")
if "--count" in sys.argv: sys.exit()
with ThreadPoolExecutor(8) as ex:
    list(ex.map(llm.map_label, sorted(labels)))
    list(ex.map(llm.classify_claim, sorted(lines)))
print({l: llm._LABEL_MEMO.get(l) for l in sorted(labels)[:40]})
