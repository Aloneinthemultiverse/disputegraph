"""Forged-evidence signals for merchant uploads (images and PDFs).

A merchant could submit an AI-generated or edited "proof of delivery". No single
test proves that, so this module only collects SIGNALS and never rejects a file:
a flagged file is marked "needs human review" and its facts stay usable.

Signals, strongest first:
1. C2PA Content Credentials: a signed manifest that tools such as OpenAI,
   Adobe Firefly, Google and Microsoft attach. It can state "created with
   generative AI" (IPTC digitalSourceType trainedAlgorithmicMedia) or list edits.
2. Metadata: EXIF/XMP software tags of AI or editing tools.
3. PDF history: incremental saves after creation, an editor as producer, or a
   modify date long after the creation date.
4. Error Level Analysis (JPEG): a region that recompresses very differently
   from the rest of the image, typical of pasted-in text or numbers.

Not covered (said plainly): watermark-only detectors such as Google SynthID
have no public image API, and a clean screenshot of a fake carries no metadata.
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

AI_TOOLS = re.compile(r"dall.?e|midjourney|stable diffusion|firefly|generative fill|openai|chatgpt|"
                      r"imagen|gemini|adobe express|canva|leonardo|ideogram|flux|sdxl|bing image", re.I)
EDITORS = re.compile(r"photoshop|gimp|pixelmator|affinity|lightroom|snapseed|picsart|paint\.net|"
                     r"acrobat(?! distiller)|foxit phantom|pdfescape|sejda|smallpdf|ilovepdf|pdf-xchange editor|"
                     r"inkscape|word|libreoffice", re.I)
AI_SOURCE = re.compile(r"trainedAlgorithmicMedia|compositeWithTrainedAlgorithmicMedia|algorithmicMedia", re.I)


def _c2pa(path: Path) -> list[dict]:
    try:
        import c2pa
    except ImportError:
        return []
    try:
        with c2pa.Reader(str(path)) as r:
            store = json.loads(r.json())
    except Exception:
        return []  # no manifest (the usual case)
    raw = json.dumps(store)
    active = store.get("manifests", {}).get(store.get("active_manifest", ""), {})
    gen = active.get("claim_generator") or (active.get("claim_generator_info") or [{}])[0].get("name", "")
    out = [{"signal": "c2pa_manifest", "severity": "info",
            "detail": f"Content Credentials present (made by: {gen or 'unknown tool'})"}]
    if AI_SOURCE.search(raw):
        out.append({"signal": "c2pa_ai_generated", "severity": "high",
                    "detail": "Content Credentials say this image was created or altered by generative AI"})
    elif re.search(r"c2pa\.(edited|placed|composited)", raw):
        out.append({"signal": "c2pa_edited", "severity": "medium",
                    "detail": "Content Credentials record edits to this image"})
    return out


def _image_meta(path: Path) -> list[dict]:
    from PIL import Image
    out = []
    with Image.open(path) as im:
        exif = im.getexif()
        text = " ".join(str(v) for v in exif.values() if isinstance(v, (str, bytes)))
        text += " " + " ".join(str(v) for v in im.info.values() if isinstance(v, (str, bytes)))
    if m := AI_TOOLS.search(text):
        out.append({"signal": "ai_tool_metadata", "severity": "high",
                    "detail": f"metadata names an AI image tool: '{m.group(0)}'"})
    elif m := EDITORS.search(text):
        out.append({"signal": "editor_metadata", "severity": "medium",
                    "detail": f"metadata says the image was saved by an editor: '{m.group(0)}'"})
    return out


def _ela(path: Path) -> list[dict]:
    """Error Level Analysis: resave at a known quality and compare blocks.
    A few blocks with a far higher error than the rest suggests pasted content."""
    from PIL import Image, ImageChops
    with Image.open(path) as im:
        if im.format != "JPEG":
            return []
        rgb = im.convert("RGB")
    buf = io.BytesIO()
    rgb.save(buf, "JPEG", quality=90)
    diff = ImageChops.difference(rgb, Image.open(buf)).convert("L")
    w, h = diff.size
    bs = 32
    px = diff.load()
    scores = []
    for by in range(0, h - bs + 1, bs):
        for bx in range(0, w - bs + 1, bs):
            s = sum(px[x, y] for y in range(by, by + bs, 4) for x in range(bx, bx + bs, 4))
            scores.append(s / ((bs // 4) ** 2))
    if len(scores) < 16:
        return []
    srt = sorted(scores)
    median = srt[len(srt) // 2] or 0.5
    small = lambda n: 2 <= n <= len(scores) * 0.08  # a small patch stands out; not the whole image
    hot = sum(1 for s in scores if s > 6 * median and s > 4)
    # noise inconsistency: a too-clean patch inside a photo that is noisy everywhere else
    # (skipped for screenshots and scans with flat backgrounds, where median noise is near 0)
    quiet = sum(1 for s in scores if s < 0.35 * median) if median >= 1.0 else 0
    if small(hot) or small(quiet):
        kind = "much noisier" if small(hot) else "much cleaner"
        return [{"signal": "ela_inconsistency", "severity": "medium",
                 "detail": f"{max(hot, quiet) if small(hot) and small(quiet) else (hot if small(hot) else quiet)} "
                           f"region(s) are {kind} than the rest of the photo (possible pasted or erased content)"}]
    return []


def _pdf(path: Path) -> list[dict]:
    out = []
    data = path.read_bytes()
    saves = data.count(b"%%EOF")
    if saves > 1:
        out.append({"signal": "pdf_incremental_save", "severity": "medium",
                    "detail": f"PDF was saved {saves} times; content may have been changed after it was issued"})
    try:
        from pypdf import PdfReader
        meta = PdfReader(io.BytesIO(data)).metadata or {}
    except Exception:
        return out
    tools = f"{meta.get('/Producer', '')} {meta.get('/Creator', '')}"
    if m := AI_TOOLS.search(tools):
        out.append({"signal": "ai_tool_metadata", "severity": "high", "detail": f"PDF made with '{m.group(0)}'"})
    elif m := EDITORS.search(tools):
        out.append({"signal": "editor_metadata", "severity": "low",
                    "detail": f"PDF produced by an editor ('{m.group(0)}'), not the issuing system"})
    c, mo = str(meta.get("/CreationDate", ""))[2:10], str(meta.get("/ModDate", ""))[2:10]
    if c.isdigit() and mo.isdigit() and mo > c:
        out.append({"signal": "pdf_modified_later", "severity": "medium",
                    "detail": f"PDF modified on {mo[:4]}-{mo[4:6]}-{mo[6:]} after it was created on {c[:4]}-{c[4:6]}-{c[6:]}"})
    return out


IMAGE = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}


def scan(path: Path) -> dict:
    """{'file', 'signals': [...], 'verdict': clean | review | likely_ai}. Never raises."""
    path = Path(path)
    signals: list[dict] = []
    try:
        ext = path.suffix.lower()
        if ext in IMAGE:
            signals = _c2pa(path) + _image_meta(path) + _ela(path)
        elif ext == ".pdf":
            signals = _c2pa(path) + _pdf(path)
    except Exception as e:  # a damaged file is itself worth a look
        signals.append({"signal": "unreadable", "severity": "medium", "detail": f"could not inspect file ({e.__class__.__name__})"})
    sev = {s["severity"] for s in signals}
    verdict = "likely_ai" if "high" in sev else "review" if sev & {"medium"} else "clean"
    return {"file": path.name, "signals": signals, "verdict": verdict}


def scan_folder(folder: Path) -> list[dict]:
    return [scan(p) for p in sorted(Path(folder).glob("*"))
            if p.suffix.lower() in IMAGE | {".pdf"}]
