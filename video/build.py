"""Builds the HyperFrames project (index.html + compositions/*.html) from assets/vo/timing.json.

Run: python build.py   then   npx hyperframes@0.9.20 check / render
"""
import json, os

T = json.load(open("assets/vo/timing.json"))
ORDER = ["market", "proof", "hook", "idea", "design", "ai", "case", "missing", "twist", "sweep",
         "forged", "human", "results", "failures", "limits", "end"]
LEAD, TAIL = 0.25, 0.4          # silence before / after each line
os.makedirs("compositions", exist_ok=True)

BASE_CSS = """
#root{position:absolute;inset:0;background:var(--ground);color:var(--ink);font-family:'Inter';overflow:hidden}
.mono{font-family:'JetBrains Mono'}
.serif{font-family:'Playfair Display'}
.kicker{font-family:'JetBrains Mono';font-size:28px;letter-spacing:.22em;text-transform:uppercase;color:var(--muted)}
.grad{background:linear-gradient(90deg,var(--amber),var(--pink));-webkit-background-clip:text;background-clip:text;color:transparent}
.pill{display:inline-block;font-family:'JetBrains Mono';font-size:28px;padding:10px 22px;border-radius:999px;border:2px solid currentColor}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:22px}
.glow{position:absolute;inset:0;background:radial-gradient(1200px 600px at 70% -10%,rgba(245,197,107,.14),transparent 60%),radial-gradient(900px 500px at 0% 110%,rgba(240,106,166,.10),transparent 60%)}
"""


import re as _re


def captions(sid, text, start, vdur):
    """Sentence chunks timed by length across the voice line; shown in a bar at the bottom."""
    parts = [p.strip() for p in _re.split(r"(?<=[.:?!])\s+", text) if p.strip()]
    chunks = []
    for p in parts:  # split long sentences at commas
        while len(p) > 90 and "," in p[:90]:
            i = p[:90].rfind(",") + 1
            chunks.append(p[:i].strip()); p = p[i:].strip()
        chunks.append(p)
    total = sum(len(c) for c in chunks)
    html, js, t = [], "", start
    for i, c in enumerate(chunks):
        d = vdur * len(c) / total
        html.append(f'    <div id="cap-{sid}-{i}" class="cap">{c}</div>')
        js += f'    tl.fromTo("#cap-{sid}-{i}", {{opacity:0}}, {{opacity:1, duration:0.15}}, {t:.2f});\n'
        js += f'    tl.to("#cap-{sid}-{i}", {{opacity:0, duration:0.15}}, {t + d - 0.12:.2f});\n'
        t += d
    return "\n".join(html), js


CAP_CSS = ".cap{position:absolute;left:0;right:0;margin:0 auto;width:fit-content;bottom:34px;max-width:1500px;text-align:center;font-family:'Inter';font-size:34px;line-height:1.3;color:#fff;background:rgba(0,0,0,.72);padding:12px 26px;border-radius:12px;opacity:0;z-index:50}"


def scene(sid, body, css, js, dur):
    return f"""<template>
  <style>{BASE_CSS}{css}</style>
  <div id="root" data-composition-id="{sid}" data-width="1920" data-height="1080">
    <div class="glow" data-layout-allow-overflow data-layout-ignore></div>
{body}
  </div>
  <script>
    const tl = gsap.timeline({{ paused: true }});
{js}
    tl.fromTo("#root .glow", {{scale:1, x:0}}, {{scale:1.25, x:-120, duration:{dur:.2f}, ease:"none"}}, 0);
    window.__timelines["{sid}"] = tl;
  </script>
</template>
"""


def fade(sel, at, dy=24, d=0.5):
    return f'    tl.fromTo("{sel}", {{opacity:0, y:{dy}}}, {{opacity:1, y:0, duration:{d}, ease:"power3.out"}}, {at:.2f});\n'


def cam(sel, at, x, y, s, d=1.4):
    return f'    tl.to("{sel}", {{x:{x}, y:{y}, scale:{s}, duration:{d}, ease:"power2.inOut"}}, {at:.2f});\n'


def focus(cx, cy, s):
    """x,y that put image point (cx,cy) at frame centre at scale s (origin 0 0)."""
    return round(960 - cx * s), round(540 - cy * s), s


S = {}

# 1 hook ---------------------------------------------------------------------
docs = ["invoice.pdf", "order sheet", "emails", "carrier page", "dispatch note"]
pos = [(250, 230), (1380, 210), (190, 760), (1420, 770), (820, 880)]
chips = "\n".join(
    f'    <div id="hook-d{i}" class="panel mono" style="position:absolute;left:{x}px;top:{y}px;padding:20px 30px;font-size:28px;color:var(--muted)">{n}</div>'
    for i, (n, (x, y)) in enumerate(zip(docs, pos)))
S["hook"] = (f"""
    <div id="hook-card" class="panel" style="position:absolute;left:560px;top:330px;width:800px;padding:44px 52px">
      <div class="kicker">PayPal dispute · PP-D-DEMO-0002</div>
      <div class="serif" style="font-size:72px;margin-top:18px;line-height:1.05">Item not received</div>
      <div style="display:flex;gap:18px;margin-top:30px;align-items:center">
        <span class="mono" style="font-size:44px;color:var(--amber)">$129.99</span>
        <span id="hook-clock" class="pill" style="color:var(--red);margin-left:auto">respond within 3 days</span>
      </div>
    </div>
{chips}
""", """""",
    fade("#hook-clock", 2.0, 0)
    + "".join(fade(f"#hook-d{i}", 4.6 + i * 0.45, 30) for i in range(5)))


# 1b market size (sourced) -----------------------------------------------------
def mstat(id_, val, label, src, color):
    return (f'<div id="{id_}" style="flex:1"><div class="serif" style="font-size:150px;line-height:1;color:{color}">{val}</div>'
            f'<div style="font-size:34px;margin-top:22px;line-height:1.3">{label}</div>'
            f'<div class="mono" style="font-size:28px;color:var(--muted);margin-top:16px">{src}</div></div>')
S["market"] = (f"""
    <div class="kicker" style="position:absolute;left:150px;top:150px">How big is the problem</div>
    <div style="position:absolute;left:150px;right:150px;top:250px;display:flex;gap:70px">
      {mstat("mk-a", "$487B", "moves through PayPal<br>every quarter", "PayPal Q3 2026 earnings", "var(--ink)")}
      {mstat("mk-b", "$34B", "chargebacks a year,<br>rising to <b style='color:var(--amber)'>$42B</b> by 2028", "Mastercard · Datos Insights", "var(--amber)")}
      {mstat("mk-c", "40%+", "of chargebacks left<br>undisputed by most retailers", "Riskified survey", "var(--pink)")}
    </div>
    <div id="mk-d" class="serif" style="position:absolute;left:150px;right:150px;top:800px;font-size:54px;font-style:italic">
      Not because they were wrong.<br><span class="grad">Because the proof was too hard to gather.</span></div>
""", "", fade("#mk-a", 0.4, 30) + fade("#mk-b", 4.9, 30) + fade("#mk-c", 9.2, 30) + fade("#mk-d", 13.4, 20))

# 2 idea ---------------------------------------------------------------------
S["idea"] = ("""
    <div style="position:absolute;left:160px;top:250px;right:160px">
      <div class="serif" style="font-size:118px;line-height:1.02;letter-spacing:-.02em">
        <span id="idea-a">Two systems.</span> <span id="idea-b">Two truths.</span><br>
        <span id="idea-c" class="grad" style="font-style:italic">One investigation.</span></div>
      <div style="display:flex;gap:40px;margin-top:70px">
        <div id="idea-l" class="panel" style="flex:1;padding:34px 40px"><div class="kicker">PayPal recorded</div><div class="mono" style="font-size:30px;margin-top:14px;color:var(--amber)">capture · invoice_id · ship-to · tracking</div></div>
        <div id="idea-r" class="panel" style="flex:1;padding:34px 40px"><div class="kicker">Merchant can prove</div><div class="mono" style="font-size:30px;margin-top:14px;color:var(--pink)">invoices · emails · carrier scans</div></div>
      </div>
    </div>
""", "", fade("#idea-a", 0.3) + fade("#idea-b", 1.0) + fade("#idea-c", 1.7)
    + fade("#idea-l", 3.2) + fade("#idea-r", 4.6))

# 3 design: one diagram that grows -------------------------------------------
checks = ["amount", "IDs", "ship-to", "timeline", "tracking", "delivery"]
verd = [("MATCH", "var(--green)"), ("VALUE_MISMATCH", "var(--amber)"), ("CONTRADICTION", "var(--red)"),
        ("TIME_MISMATCH", "var(--amber)"), ("UNSUPPORTED_CLAIM", "var(--pink)"), ("MISSING", "var(--muted)")]
ck = "\n".join(f'      <div id="des-c{i}" class="panel mono" style="padding:14px 22px;font-size:28px;text-align:center">{c}</div>' for i, c in enumerate(checks))
vd = "\n".join(f'      <div id="des-v{i}" class="pill" style="color:{c};font-size:28px;text-align:center">{v}</div>' for i, (v, c) in enumerate(verd))
S["design"] = (f"""
    <div class="kicker" style="position:absolute;left:120px;top:90px">How it works</div>
    <div id="des-pp" class="panel" style="position:absolute;left:120px;top:250px;width:330px;padding:30px"><div class="kicker">PayPal sandbox API</div><div class="mono" style="font-size:28px;margin-top:10px;color:var(--amber)">dispute · capture · order</div></div>
    <div id="des-md" class="panel" style="position:absolute;left:120px;top:620px;width:330px;padding:30px"><div class="kicker">Merchant documents</div><div class="mono" style="font-size:28px;margin-top:10px;color:var(--pink)">invoice · emails · carrier</div></div>
    <svg id="des-ln1" style="position:absolute;left:450px;top:300px" width="140" height="460"><path d="M0 40 C 80 40, 60 230, 140 230 M0 410 C 80 410, 60 230, 140 230" stroke="#4a443c" stroke-width="3" fill="none"/></svg>
    <div id="des-f" class="panel" style="position:absolute;left:590px;top:455px;width:230px;padding:28px;text-align:center"><div class="serif" style="font-size:52px">Facts</div><div class="mono" style="font-size:28px;color:var(--muted);margin-top:6px">value + source line</div></div>
    <div style="position:absolute;left:890px;top:250px;width:300px;display:flex;flex-direction:column;gap:18px">
{ck}
    </div>
    <div class="kicker" id="des-ck" style="position:absolute;left:890px;top:200px">deterministic checks</div>
    <div style="position:absolute;left:1270px;top:250px;width:520px;display:flex;flex-direction:column;gap:22px;align-items:flex-start">
{vd}
    </div>
    <div id="des-cite" class="mono" style="position:absolute;left:1270px;top:860px;font-size:28px;color:var(--ink)">↳ every verdict cites its API field or document line</div>
""", "", fade("#des-pp", 0.4, 0) + fade("#des-md", 1.6, 0) + fade("#des-ln1", 3.6, 0)
    + fade("#des-f", 4.4, 0) + fade("#des-ck", 6.2, 0)
    + "".join(fade(f"#des-c{i}", 6.6 + i * 0.55, 0, 0.35) for i in range(6))
    + "".join(fade(f"#des-v{i}", 11.0 + i * 0.3, 0, 0.3) for i in range(6))
    + fade("#des-cite", 13.6, 10))

# 4 ai -------------------------------------------------------------------------
S["ai"] = ("""
    <div class="kicker" style="position:absolute;left:160px;top:120px">Where AI helps</div>
    <div id="ai-box" class="panel" style="position:absolute;left:160px;top:200px;width:620px;padding:40px">
      <div class="serif" style="font-size:58px">NVIDIA Nemotron</div>
      <div id="ai-j0" class="mono" style="font-size:30px;margin-top:26px">→ maps messy labels</div>
      <div id="ai-j1" class="mono" style="font-size:30px;margin-top:14px">→ classifies claims</div>
      <div id="ai-j2" class="mono" style="font-size:30px;margin-top:14px">→ writes the summary</div>
    </div>
    <div style="position:absolute;left:880px;top:200px;width:900px">
      <div class="kicker">AI summary · every sentence linked</div>
      <div id="ai-s0" class="mono" style="font-size:28px;margin-top:30px">The amount 129.99 matches the PayPal capture. <span class="pill" style="color:var(--green);font-size:28px;padding:4px 12px">F2</span></div>
      <div id="ai-s1" class="mono" style="font-size:28px;margin-top:26px">The invoice ships to Austin 78701. <span class="pill" style="color:var(--green);font-size:28px;padding:4px 12px">F4</span></div>
      <div id="ai-s2" class="mono" style="font-size:28px;margin-top:26px;position:relative">The buyer was clearly lying. <span class="pill" style="color:var(--red);font-size:28px;padding:4px 12px">no finding</span>
        <div id="ai-strike" style="position:absolute;left:0;top:50%;height:3px;width:470px;background:var(--red);transform-origin:0 50%"></div></div>
      <div id="ai-rm" class="mono" style="font-size:28px;margin-top:22px;color:var(--red)">removed: 1 unsupported sentence</div>
    </div>
""", "", fade("#ai-box", 0.2, 0) + fade("#ai-j0", 1.9, 10) + fade("#ai-j1", 3.2, 10) + fade("#ai-j2", 4.4, 10)
    + fade("#ai-s0", 5.6, 10) + fade("#ai-s1", 6.4, 10) + fade("#ai-s2", 7.3, 10)
    + '    tl.fromTo("#ai-strike", {scaleX:0}, {scaleX:1, duration:0.5, ease:"power2.out"}, 9.3);\n'
    + fade("#ai-rm", 9.7, 10))


# app-screen scenes: one camera over a real screenshot ------------------------
def shot(sid, img, w, h, moves, extra="", extra_js=""):
    fit = min(1920 / w, 1080 / h) * 0.94
    x0, y0 = round((1920 - w * fit) / 2), round((1080 - h * fit) / 2)
    body = f"""
    <div id="{sid}-cam" style="position:absolute;left:0;top:0;width:{w}px;height:{h}px;transform-origin:0 0">
      <img id="{sid}-img" src="assets/shots/{img}" style="position:absolute;left:0;top:0;width:{w}px;height:{h}px;border-radius:18px;box-shadow:0 30px 120px rgba(0,0,0,.6)">
{extra}
    </div>"""
    js = f'    tl.fromTo("#{sid}-cam", {{x:{x0}, y:{y0 + 30}, scale:{fit:.4f}, opacity:0}}, {{x:{x0}, y:{y0}, scale:{fit:.4f}, opacity:1, duration:0.7, ease:"power3.out"}}, 0);\n'
    for at, (cx, cy, s) in moves:
        js += cam(f"#{sid}-cam", at, *focus(cx, cy, s))
    return body, "", js + extra_js


def box(id_, x, y, w, h, color="var(--amber)"):
    return f'      <div id="{id_}" style="position:absolute;left:{x}px;top:{y}px;width:{w}px;height:{h}px;border:5px solid {color};border-radius:16px;box-shadow:0 0 40px {color}"></div>'


S["case"] = shot("case", "01-overview.png", 1920, 1200, [(1.6, (1527, 650, 1.55))],
                 box("case-hl", 1300, 545, 450, 100), fade("#case-hl", 2.8, 0, 0.35))
S["missing"] = shot("missing", "01-overview.png", 1920, 1200, [(0.8, (1527, 1060, 1.7))],
                    box("mis-hl", 1305, 985, 440, 140, "var(--pink)"), fade("#mis-hl", 2.2, 0, 0.35))
S["twist"] = shot("twist", "07-after-top.png", 1920, 1200,
                  [(0.9, (1527, 260, 1.55)), (5.2, (700, 700, 1.45))],
                  box("tw-hl1", 1300, 180, 450, 100, "var(--green)") + box("tw-hl2", 170, 670, 1080, 70, "var(--red)"),
                  fade("#tw-hl1", 2.4, 0, 0.35) + fade("#tw-hl2", 6.9, 0, 0.35))
S["sweep"] = shot("sweep", "09-sweep.png", 480, 580, [(1.4, (240, 450, 1.75))],
                  box("sw-hl", 26, 356, 430, 190, "var(--amber)") + box("sw-hl2", 26, 160, 430, 86, "var(--pink)"),
                  fade("#sw-hl", 2.4, 0, 0.35) + fade("#sw-hl2", 6.0, 0, 0.35)
                  + cam("#sweep-cam", 5.4, *focus(240, 260, 1.75)))

# 9 human ---------------------------------------------------------------------
S["human"] = ("""
    <div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:44px">
      <div id="hu-b" class="mono" style="font-size:44px;padding:26px 56px;border-radius:18px;background:linear-gradient(90deg,var(--amber),#f7a35c);color:#1a1206;font-weight:700">Approve &amp; send to PayPal</div>
      <div id="hu-t" class="kicker" style="font-size:28px">nothing is sent without human approval</div>
    </div>
""", "", fade("#hu-b", 0.3, 20) + fade("#hu-t", 1.3, 10))

# 10 results ------------------------------------------------------------------
def stat(id_, val, label, color):
    return f'<div id="{id_}" style="flex:1"><div class="serif" style="font-size:190px;line-height:1;color:{color}">{val}</div><div class="mono" style="font-size:28px;color:var(--muted);margin-top:18px">{label}</div></div>'
S["results"] = (f"""
    <div class="kicker" style="position:absolute;left:150px;top:230px">Blind tests · cases we had never seen</div>
    <div style="position:absolute;left:150px;right:150px;top:360px;display:flex;gap:50px">
      {stat("rs-a", "64%", "first try · batch 1 (48/75)", "var(--ink)")}
      {stat("rs-b", "70%", "first try · final batch (35/50)", "var(--ink)")}
      {stat("rs-c", "157/159", "after fixing each failure type", "var(--green)")}
    </div>
    <div id="rs-d" class="mono" style="position:absolute;left:150px;top:820px;font-size:46px">false alarms: <span style="color:var(--amber)">0.3%</span></div>
""", "", fade("#rs-a", 3.3, 30) + fade("#rs-b", 5.0, 30) + fade("#rs-c", 9.0, 30) + fade("#rs-d", 12.6, 20))

# 11 failures -----------------------------------------------------------------
fails = ["carrier prefix on tracking · HERMES/JJD…", "mistyped IDs · INV-1O23 vs INV-1023",
         "foreign postcodes · K1A 0B1", "refund in words · “eighty dollars”", "dates read as tracking numbers"]
fl = "\n".join(
    f'      <div id="fa-{i}" class="mono" style="font-size:42px;display:flex;gap:26px;align-items:center"><span class="pill" style="color:var(--green);font-size:28px;padding:6px 14px">fixed</span>{t}</div>'
    for i, t in enumerate(fails))
S["failures"] = (f"""
    <div class="kicker" style="position:absolute;left:150px;top:190px">Where it failed first</div>
    <div style="position:absolute;left:150px;top:290px;display:flex;flex-direction:column;gap:42px">
{fl}
      <div id="fa-open" class="mono" style="font-size:42px;display:flex;gap:26px;align-items:center;margin-top:20px"><span class="pill" style="color:var(--amber);font-size:28px;padding:6px 14px">open</span>2 debatable cases · e.g. “confirmed by phone”</div>
    </div>
""", "", "".join(fade(f"#fa-{i}", 1.6 + i * 1.3, 0, 0.4) for i in range(5)) + fade("#fa-open", 9.0, 0, 0.4))

# 12 limits -------------------------------------------------------------------
S["limits"] = ("""
    <div style="position:absolute;left:150px;top:300px;right:150px">
      <div id="li-b" class="mono" style="font-size:40px;color:var(--muted)">added → <span style="color:var(--green)">OCR</span> for scanned receipts · <span style="color:var(--green)">translation</span> checked number by number</div>
      <div class="kicker" style="margin-top:90px">Honest limit</div>
      <div id="li-a" class="serif" style="font-size:80px;line-height:1.12;margin-top:24px">Real dispute data is private.<br>We tested on <span class="grad">synthetic + sandbox</span> cases only.</div>
    </div>
""", "", fade("#li-b", 0.4, 20) + fade("#li-a", 6.2, 30))

# 13 end ----------------------------------------------------------------------
S["end"] = ("""
    <div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:30px">
      <div id="en-a" class="mono" style="font-size:96px">~/dispute<span class="grad">graph</span></div>
      <div id="en-b" class="serif" style="font-size:64px;font-style:italic">It doesn't guess. <span class="grad">It asks.</span></div>
      <div id="en-c" class="mono" style="font-size:44px;margin-top:40px;color:var(--amber)">disputegraph.onrender.com</div>
    </div>
""", "", fade("#en-a", 0.2, 20, 0.6) + fade("#en-b", 1.1, 20, 0.6) + fade("#en-c", 3.3, 20, 0.6))


# proof: results up front ------------------------------------------------------
S["proof"] = (f"""
    <div class="kicker" style="position:absolute;left:150px;top:170px">Tested, not just demoed</div>
    <div id="pf-q" class="serif" style="position:absolute;left:150px;top:240px;font-size:64px;font-style:italic">Most AI demos show it works <span class="grad">once.</span></div>
    <div style="position:absolute;left:150px;right:150px;top:420px;display:flex;gap:60px">
      {stat("pf-a", "3,000", "test cases, fixed seed", "var(--ink)")}
      {stat("pf-b", "96.2%", "exact verdicts · Nemotron", "var(--green)")}
      {stat("pf-c", "0.3%", "false alarms on clean cases", "var(--amber)")}
    </div>
    <div id="pf-d" class="mono" style="position:absolute;left:150px;top:850px;font-size:40px;color:var(--muted)">keyword script → <span style="color:var(--red)">55.8%</span> exact, 17.7% false alarms</div>
""", "", fade("#pf-q", 0.2, 20) + fade("#pf-a", 2.6, 30) + fade("#pf-b", 5.0, 30) + fade("#pf-c", 8.0, 30) + fade("#pf-d", 10.8, 20))

# forged evidence ---------------------------------------------------------------
S["forged"] = ("""
    <div class="kicker" style="position:absolute;left:120px;top:110px">Forged-evidence check</div>
    <div id="fg-img" style="position:absolute;left:120px;top:190px;width:800px;height:600px">
      <img src="assets/shots/forged.jpg" style="width:800px;height:600px;border-radius:14px;box-shadow:0 30px 120px rgba(0,0,0,.6)">
      <div id="fg-box" style="position:absolute;left:30px;top:228px;width:400px;height:66px;border:5px solid var(--red);border-radius:10px;box-shadow:0 0 40px var(--red)"></div>
    </div>
    <div style="position:absolute;left:1000px;top:230px;width:800px;display:flex;flex-direction:column;gap:30px">
      <div id="fg-p" class="pill" style="color:var(--red);font-size:34px;align-self:flex-start">needs human review</div>
      <div id="fg-1" class="mono" style="font-size:32px;line-height:1.4">a region is much cleaner than<br>the rest of the photo</div>
      <div id="fg-2" class="mono" style="font-size:28px;color:var(--muted);line-height:1.5">also checks: C2PA Content Credentials ·<br>AI-tool metadata · PDF edit history</div>
    </div>
""", "", fade("#fg-img", 0.2, 30) + fade("#fg-box", 2.4, 0, 0.35) + fade("#fg-p", 3.0, 10) + fade("#fg-1", 3.6, 10) + fade("#fg-2", 5.0, 10))

# assemble ---------------------------------------------------------------------
hosts, audios, t = [], [], 0.0
for i, sid in enumerate(ORDER):
    vo = T[sid]
    dur = round(LEAD + vo["dur"] + TAIL + (1.2 if sid == "end" else 0), 2)
    body, css, js = S[sid]
    ch, cj = captions(sid, vo["text"], LEAD, vo["dur"])
    body, css, js = body + "\n" + ch, css + CAP_CSS, js + cj
    open(f"compositions/{sid}.html", "w", encoding="utf-8").write(scene(sid, body, css, js, dur))
    hosts.append(f'      <div id="{sid}" data-composition-id="{sid}" data-composition-src="compositions/{sid}.html" class="clip" '
                 f'data-start="{t:.2f}" data-duration="{dur}" data-track-index="1" data-track-kind="graphics" '
                 f'data-width="1920" data-height="1080" style="z-index:1"></div>')
    audios.append(f'      <audio id="vo-{sid}" class="clip" src="{vo["file"]}" data-start="{t + LEAD:.2f}" '
                  f'data-duration="{vo["dur"]}" data-track-index="2" data-volume="1"></audio>')
    t += dur
total = round(t, 2)
audios.append(f'      <audio id="music" class="clip" src="assets/music.wav" data-start="0" data-duration="{total}" data-track-index="3" data-volume="0.16" data-fade-in="1.5" data-fade-out="3"></audio>')

index = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1920, height=1080" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>
    <style>
      :root {{ --ground:#0b0a09; --ink:#f4efe6; --muted:#8a8378; --amber:#f5c56b; --pink:#f06aa6;
               --green:#5fd18a; --red:#ff6b6b; --panel:#151311; --line:#2a2622; --font-display:'Playfair Display'; }}
      * {{ margin:0; padding:0; box-sizing:border-box; }}
      html, body {{ width:1920px; height:1080px; overflow:hidden; background:var(--ground); }}
      #root {{ position:relative; width:100%; height:100%; background:var(--ground); }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{total}" data-width="1920" data-height="1080">
{chr(10).join(hosts)}
{chr(10).join(audios)}
    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""
open("index.html", "w", encoding="utf-8").write(index)
print("total seconds", total)
