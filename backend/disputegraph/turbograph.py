"""TurboVec-HippoRAG over a dispute's merchant evidence.

Python port of the method in the author's turbograph-research repo
(Methods.pushPpr, "Fused 2-bit + Push-PPR, SCAN seeds"):

  * every evidence chunk (one document line) is stored as a 2-bit TurboQuant
    code (turbovec.IdMapIndex, bit_width=2), ~16x smaller than float32;
  * knowledge-graph edges are stored EXACTLY: chunk <-> entity (tracking
    numbers, invoice/order IDs, amounts, dates, carriers, delivery states) and
    chunk <-> next chunk in the same document;
  * a query seeds Personalized PageRank from the best 2-bit chunk scores
    (score >= best - 0.05, weight exp(40 * (s - best))) plus entities named in
    the query, then runs Andersen-Chung-Lang local push (alpha 0.15, eps 1e-4);
  * ranking is fused: 2-bit relevance + lambda (0.1) x normalised PPR mass, so
    evidence linked through a shared entity rises even when its wording differs.

Why it matters for disputes: "was it delivered?" should surface not just the
email that says "delivered" but the courier scan for the SAME tracking number,
reached through the tracking-number entity. Plain vector search can't follow
that link; the graph keeps the relationship while the vectors stay 2-bit.

Embeddings: NVIDIA NIM nemotron-3.5-embed-1b (2048-d), cached on disk so the
demo replays without a key. With no key and no cache, a deterministic hashed
bag-of-words embedding is used and the result is labelled as such.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
import requests
import turbovec

from .merchant import load_pages

ROOT = Path(__file__).resolve().parents[2]
ECACHE = ROOT / "data" / "embed_cache"
ECACHE.mkdir(parents=True, exist_ok=True)
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nvidia/nemotron-3.5-embed-1b")
DIM, BITS = 2048, 2
ALPHA, EPS, LAMBDA, SEED_BAND, SEED_TEMP = 0.15, 1e-4, 0.1, 0.05, 40.0

ENTITY_PATTERNS = [
    ("tracking", r"\b(1Z[0-9A-Z]{10,}|9[0-9]{15,}|[0-9]{12})\b"),
    ("invoice", r"\bINV-[A-Z0-9]+\b"),
    ("order", r"\bORDER?-[A-Z0-9]+\b"),
    ("amount", r"\b\d{1,5}\.\d{2}\b"),
    ("date", r"\b20\d\d-\d\d-\d\d\b"),
    ("carrier", r"\b(UPS|USPS|FedEx|DHL)\b"),
    ("state", r"\b(delivered|in transit|label created|picked up|origin scan|arrival scan|refunded|shipped|cancelled)\b"),
]


def entities(text: str) -> set[str]:
    out = set()
    for kind, pat in ENTITY_PATTERNS:
        for m in re.finditer(pat, text, re.I):
            out.add(f"{kind}:{m.group(0).lower()}")
    return out


# -- embeddings ---------------------------------------------------------------
def _hash_embed(text: str) -> np.ndarray:
    v = np.zeros(DIM, dtype=np.float32)
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        v[h % DIM] += 1.0 if (h >> 20) & 1 else -1.0
    return v


def _nim(texts: list[str], kind: str) -> list[np.ndarray] | None:
    base, key = os.environ.get("LLM_BASE_URL"), os.environ.get("LLM_API_KEY")
    if not (base and key):
        return None
    for _ in range(3):  # NIM occasionally returns 500 on a batch; retry
        try:
            r = requests.post(f"{base.rstrip('/')}/embeddings", timeout=60,
                              headers={"Authorization": f"Bearer {key}"},
                              json={"model": EMBED_MODEL, "input": texts,
                                    "input_type": kind, "encoding_format": "float"})
            r.raise_for_status()
            return [np.asarray(d["embedding"], dtype=np.float32) for d in r.json()["data"]]
        except Exception:
            continue
    return None


def embed(texts: list[str], kind: str, force_hash: bool = False) -> tuple[np.ndarray, str]:
    """kind = passage | query. Returns L2-normalised vectors and their source.
    All vectors in one call come from ONE embedder (never a mix), so the
    passages and the query always live in the same space."""
    if force_hash:
        out = [_hash_embed(t) for t in texts]
        source = "hash-fallback"
    else:
        keys = [hashlib.sha256(f"{EMBED_MODEL}|{kind}|{t}".encode()).hexdigest()[:24] for t in texts]
        out: list = [np.load(ECACHE / f"{k}.npy") if (ECACHE / f"{k}.npy").exists() else None for k in keys]
        todo = [i for i, v in enumerate(out) if v is None]
        source = "nim-cache" if not todo else "nim"
        for start in range(0, len(todo), 16):
            batch = todo[start:start + 16]
            got = _nim([texts[i] for i in batch], kind)
            if got is None:  # try one by one before giving up
                got = [(_nim([texts[i]], kind) or [None])[0] for i in batch]
            for i, v in zip(batch, got):
                if v is not None:
                    np.save(ECACHE / f"{keys[i]}.npy", v)
                    out[i] = v
        if any(v is None for v in out):
            source = "hash-fallback"
            out = [_hash_embed(t) for t in texts]
    m = np.vstack(out).astype(np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
    return m, source


# -- graph --------------------------------------------------------------------
class TurboGraph:
    def __init__(self, invoice_id: str):
        self.chunks: list[dict] = []
        for p in load_pages(invoice_id):
            for i, line in enumerate(p["text"].splitlines(), 1):
                if line.strip() and not line.startswith("SYNTHETIC"):
                    self.chunks.append({"doc": p["doc"], "page": p["page"], "line": i,
                                        "ref": f"{invoice_id}/{p['doc']}.md",
                                        "pointer": f"page {p['page']}, line {i}", "text": line.strip()})
        n = len(self.chunks)
        vecs, self.embed_source = embed([c["text"] for c in self.chunks], "passage")
        self.index = turbovec.IdMapIndex(DIM, BITS)
        self.index.add_with_ids(vecs, np.arange(n, dtype=np.uint64))
        # exact edges: chunk <-> entity, chunk <-> next chunk in the same doc
        self.adj: dict[str, dict[str, float]] = defaultdict(dict)
        self.ent_df: dict[str, int] = defaultdict(int)
        for i, c in enumerate(self.chunks):
            for e in entities(c["text"]):
                self.ent_df[e] += 1
        for i, c in enumerate(self.chunks):
            for e in entities(c["text"]):
                w = 1.0 / self.ent_df[e]  # specific entities (a tracking number) link strongly
                self.adj[f"c{i}"][e] = w
                self.adj[e][f"c{i}"] = w
            if i + 1 < n and self.chunks[i + 1]["doc"] == c["doc"]:
                self.adj[f"c{i}"][f"c{i+1}"] = 0.5
                self.adj[f"c{i+1}"][f"c{i}"] = 0.5
        self.bytes_2bit = n * DIM * BITS // 8
        self.bytes_f32 = n * DIM * 4
        self.edges = sum(len(v) for v in self.adj.values()) // 2

    def _push_ppr(self, seed: dict[str, float]) -> dict[str, float]:
        total = sum(seed.values()) or 1.0
        r = {k: v / total for k, v in seed.items()}
        p: dict[str, float] = defaultdict(float)
        queue, pushes = list(r), 0
        while queue and pushes < 200_000:
            u = queue.pop(0)
            ru, nb = r.get(u, 0.0), self.adj.get(u, {})
            if not nb or ru < EPS * len(nb):
                continue
            pushes += 1
            p[u] += ALPHA * ru
            r[u] = 0.0
            wsum = sum(nb.values())
            for v, w in nb.items():
                r[v] = r.get(v, 0.0) + (1 - ALPHA) * ru * w / wsum
                if r[v] >= EPS * max(1, len(self.adj.get(v, {}))) and v not in queue:
                    queue.append(v)
        return p

    def search(self, query: str, k: int = 5) -> dict:
        n = len(self.chunks)
        q, qsrc = embed([query], "query", force_hash=self.embed_source == "hash-fallback")
        index = self.index
        if qsrc == "hash-fallback" and self.embed_source != "hash-fallback":
            # query couldn't be embedded with NIM (no key / offline, uncached question):
            # score against a hashed 2-bit index so both sides share one space
            if not hasattr(self, "hash_index"):
                hv, _ = embed([c["text"] for c in self.chunks], "passage", force_hash=True)
                self.hash_index = turbovec.IdMapIndex(DIM, BITS)
                self.hash_index.add_with_ids(hv, np.arange(n, dtype=np.uint64))
            index = self.hash_index
        scores, ids = index.search(q, n)
        s = {int(i): float(sc) for sc, i in zip(scores[0], ids[0])}
        best = max(s.values())
        seed = {f"c{i}": math.exp((v - best) * SEED_TEMP) for i, v in s.items() if v >= best - SEED_BAND}
        q_ents = entities(query) | {e for e in self.ent_df if e.split(":", 1)[1] in query.lower()}
        for e in q_ents:
            if e in self.adj:
                seed[e] = seed.get(e, 0.0) + math.log(1 + n / self.ent_df[e])
        p = self._push_ppr(seed)
        max_p = max((v for kk, v in p.items() if kk.startswith("c")), default=0.0) or 1.0
        fused = {i: s[i] + LAMBDA * p.get(f"c{i}", 0.0) / max_p for i in range(n)}
        flat = sorted(range(n), key=lambda i: -s[i])[:k]
        top = sorted(range(n), key=lambda i: -fused[i])[:k]
        hits = []
        for rank, i in enumerate(top):
            c = self.chunks[i]
            # explain the graph path: which entities link this chunk to the seeds
            via = sorted((e for e in self.adj.get(f"c{i}", {}) if not e.startswith("c") and p.get(e, 0) > 0),
                         key=lambda e: -p.get(e, 0))[:3]
            hits.append({**c, "score": round(fused[i], 4), "dense_2bit": round(s[i], 4),
                         "ppr": round(p.get(f"c{i}", 0.0) / max_p, 3), "via": via,
                         "graph_lifted": i not in flat})
        return {"query": query, "hits": hits, "embed_source": qsrc if qsrc != "nim" else self.embed_source,
                "stats": {"chunks": n, "entities": len(self.ent_df), "exact_edges": self.edges,
                          "index_bytes_2bit": self.bytes_2bit, "float32_bytes": self.bytes_f32,
                          "compression": round(self.bytes_f32 / max(self.bytes_2bit, 1), 1),
                          "params": {"alpha": ALPHA, "eps": EPS, "lambda": LAMBDA, "bits": BITS}}}


_GRAPHS: dict[str, tuple[float, TurboGraph]] = {}


def graph_for(invoice_id: str) -> TurboGraph:
    folder = ROOT / "data" / "merchant" / invoice_id
    stamp = max((f.stat().st_mtime for f in folder.glob("*.md")), default=0.0) + len(list(folder.glob("*.md")))
    hit = _GRAPHS.get(invoice_id)
    if not hit or hit[0] != stamp:  # rebuild when evidence is added or removed
        _GRAPHS[invoice_id] = (stamp, TurboGraph(invoice_id))
    return _GRAPHS[invoice_id][1]
