"""LLM layer: used only where wording is fuzzy. Never decides amounts, IDs or dates.

1. summarize(): plain-English case summary written ONLY from verdicts. Every
   sentence must end with [F<n>] pointing at a finding; sentences without a
   valid tag are dropped, so the model cannot add unsupported claims.
2. classify_claim(): reads a free-text line the regex rules missed and says
   whether it claims delivery / shipping / refund.

Provider: any OpenAI-compatible chat endpoint (Groq, Gemini, OpenRouter, a
local Ollama...). Set LLM_BASE_URL, LLM_API_KEY, LLM_MODEL in .env.
Responses are cached in data/llm_cache/ so the hosted demo replays them with
no key. Without a key and without a cache hit, a deterministic fallback runs.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "llm_cache"
CACHE.mkdir(parents=True, exist_ok=True)


def _chat(system: str, user: str) -> tuple[str | None, str]:
    """Returns (text, source) where source is cache | live | none."""
    model = os.environ.get("LLM_MODEL", "")
    key = hashlib.sha256(f"{model}\n{system}\n{user}".encode()).hexdigest()[:24]
    path = CACHE / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["text"], "cache"
    base, api_key = os.environ.get("LLM_BASE_URL"), os.environ.get("LLM_API_KEY")
    if not (base and api_key and model) or os.environ.get("DEMO_MODE") == "1":
        return None, "none"
    try:
        r = requests.post(f"{base.rstrip('/')}/chat/completions", timeout=60,
                          headers={"Authorization": f"Bearer {api_key}"},
                          json={"model": model, "temperature": 0,
                                "messages": [{"role": "system", "content": system},
                                             {"role": "user", "content": user}]})
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None, "none"
    path.write_text(json.dumps({"model": model, "text": text}, indent=1), encoding="utf-8")
    return text, "live"


SUMMARY_SYS = (
    "You write dispute case summaries for a small online seller. Use ONLY the numbered "
    "findings given. Do not add facts, guesses, advice about who is right, or numbers not in "
    "the findings. Write 3-5 short plain-English sentences. End EVERY sentence with the tag of "
    "the finding it comes from, like [F2]. Say clearly when sources disagree or evidence is missing.")


def summarize(findings: list[dict]) -> dict:
    lines = [f"F{i}: {f['verdict']} | {f['check']} | {f['note']}" for i, f in enumerate(findings)]
    text, src = _chat(SUMMARY_SYS, "\n".join(lines))
    if text is None:
        return {"source": "template", "sentences": _template(findings)}
    kept, dropped = [], 0
    for sent in re.split(r"(?<=[.!?\]])\s+", text):
        tags = [int(t) for t in re.findall(r"\[F(\d+)\]", sent)]
        if tags and all(0 <= t < len(findings) for t in tags):
            kept.append({"text": re.sub(r"\s*\[F\d+\]", "", sent).strip(), "findings": tags})
        elif sent.strip():
            dropped += 1  # untagged or bad tag -> not shown
    return {"source": f"llm:{src}", "sentences": kept or _template(findings), "dropped": dropped}


def _template(findings: list[dict]) -> list[dict]:
    order = ["CONTRADICTION", "UNSUPPORTED_CLAIM", "VALUE_MISMATCH", "TIME_MISMATCH", "MISSING", "MATCH"]
    ranked = sorted(range(len(findings)), key=lambda i: order.index(findings[i]["verdict"]))
    return [{"text": findings[i]["note"][0].upper() + findings[i]["note"][1:] + ".", "findings": [i]}
            for i in ranked[:4]]


CLAIM_SYS = (
    "Classify one line from a seller's email or notes. Reply with exactly one word: "
    "DELIVERED (it claims the item was delivered/received), SHIPPED (claims it was sent), "
    "REFUNDED (claims money was returned), or NONE.")
HINT = re.compile(r"deliver|receiv|arriv|drop(ped)? off|left (it|the)|porch|doorstep|sent|dispatch|refund|money back", re.I)


def classify_claim(line: str) -> str | None:
    """Only called for lines that look relevant but the regex rules missed."""
    if not HINT.search(line):
        return None
    text, _ = _chat(CLAIM_SYS, line)
    if text is None:
        return None
    word = text.strip().split()[0].upper().strip(".")
    return word if word in ("DELIVERED", "SHIPPED", "REFUNDED") else None
