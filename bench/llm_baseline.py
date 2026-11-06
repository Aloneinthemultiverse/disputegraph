"""Single-LLM baseline vs DisputeGraph on the same stratified sample.
Run: python bench/llm_baseline.py [n]   -> bench/results_llm.json"""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bench.bench as bb
n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
cases = bb.load(bb.HERE / "cases.jsonl")
sample = bb.stratified(cases, n)
llm = bb.run_llm(sample, workers=4)
bb.USE_LLM_CLAIMS = True
dg_ai = bb.run_disputegraph(sample)
bb.USE_LLM_CLAIMS = False
dg_rx = bb.run_disputegraph(sample)
kw = bb.run_keyword(sample)
out = {"n": len(sample), "model": os.environ.get("LLM_MODEL"),
       "single_llm": bb.summary("llm", sample, llm), "disputegraph_ai": bb.summary("dg", sample, dg_ai),
       "disputegraph_regex": bb.summary("dgr", sample, dg_rx), "keyword": bb.summary("kw", sample, kw),
       "llm_errors": {k: v["error"] for k, v in llm.items() if v["error"]}}
(bb.HERE / "results_llm.json").write_text(json.dumps(out, indent=1, default=list), encoding="utf-8")
for k in ("single_llm", "disputegraph_ai", "disputegraph_regex", "keyword"):
    s = out[k]; print(f"{k:20} exact {s['exact_accuracy']} {s['exact_accuracy_95ci']} micro {s['micro']} fa {s['false_alarm_rate_on_clean']} p50 {s['latency_ms']['p50']}ms")
