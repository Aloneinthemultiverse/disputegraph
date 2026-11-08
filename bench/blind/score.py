"""Score blind test batches: python bench/blind/score.py [--ai] [-v]
Reads every bench/blind/*.jsonl. Run it BEFORE changing any code to get the blind number."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import bench.bench as bb

bb.USE_LLM_CLAIMS = "--ai" in sys.argv
tot = ok = 0
for p in sorted(Path(__file__).parent.glob("*.jsonl")):
    cs = []
    for i, l in enumerate(open(p, encoding="utf-8"), 1):
        if not l.strip():
            continue
        try:
            c = json.loads(l)
        except ValueError as e:
            print(f"  {p.name}:{i} bad JSON ({e})"); continue
        bad = [x for x in c.get("labels", []) if x not in bb.ISSUES]
        if bad:
            print(f"  {p.name}:{i} unknown labels {bad}")
        c["id"] = f"{p.stem}:{c['id']}"
        c["labels"] = [x for x in c["labels"] if x in bb.ISSUES]
        cs.append(c)
    r = bb.run_disputegraph(cs); n = 0
    for c in cs:
        pred, gold = r[c["id"]]["pred"], set(c["labels"])
        n += pred == gold
        if pred != gold and "-v" in sys.argv:
            print(f"  {c['id']:28} gold={sorted(gold)} pred={sorted(pred)}  | {c.get('why', '')[:90]}")
    print(f"{p.stem:12} {n}/{len(cs)}"); tot += len(cs); ok += n
print("ALL", ok, "/", tot)
