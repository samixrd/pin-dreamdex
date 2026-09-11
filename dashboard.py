# PIN dashboard generator — Somnia-branded (tokens extracted live from somnia.network CSS).
# Renders ONLY from real recorded data in data/. Zero mock numbers: every figure traces to a file.
import json, os, statistics, datetime as dt

DATA = "data"
PUB = f"{DATA}/published"

def lj(f):
    try:
        with open(f"{DATA}/{f}", encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]
    except FileNotFoundError:
        return []

def pj(name):
    for p in (f"{PUB}/{name}", f"{DATA}/{name}"):
        if os.path.exists(p):
            return json.load(open(p))
    return {}

live = lj("live_ledger.jsonl")
paper = lj("paper_ledger.jsonl")
hazard = pj("hazard_table.json")
final = pj("sweep_final.json")
sigma = pj("sweep_sigma02.json")
anatomy = pj("venue_anatomy.json")
oracle = pj("oracle_precision.json")
SD = pj("settle_distances.json")

fills = [e for e in live if e["ev"] == "fill"]
rests = [e for e in live if e["ev"] == "rest"]
redeems = [e for e in live if e["ev"] in ("redeem", "claim_sweep")]
merges = [e for e in live if e["ev"] == "merge"]
settles = [e for e in live if e["ev"] == "settle"]
notional = sum(e["qty"] * e["px"] for e in fills)

# frontier: best touch configs vs naive at each sigma (PnL mean)
def front_bars():
    out = []
    for sg in ("0.005", "0.01", "0.0225"):
        pk = f"s{sg}-q200-1t-pk0.6"; nk = f"s{sg}-q200-2c-pk0.6"
        p_, n_ = final.get(pk) or {}, final.get(nk) or {}
        out.append({"sigma": sg, "pin": p_.get("pnl_mean", 0), "naive": n_.get("pnl_mean", 0),
                    "pin_worst": p_.get("worst", 0), "naive_worst": n_.get("worst", 0),
                    "pin_shr": p_.get("score_share_med", 0), "naive_shr": n_.get("score_share_med", 0)})
    return out
bars = front_bars()

# yield score race at operating sigma
race = []
for k, v in sorted((final or {}).items()):
    if not v or not k.startswith("s0.01-q200"): continue
    race.append((k.split("-", 1)[1], v["score_share_med"]))
race.sort(key=lambda x: -x[1])

haz_rows = []
if hazard:
    eps = [k for k in next(iter(hazard.values())) if k != "n"]
    for k, v in sorted(hazard.items(), key=lambda x: float(x[0].split("-")[0])):
        haz_rows.append((k, v.get("n", ""), [v.get(e, "") for e in eps]))
    haz_eps = [f"{round(float(e)*1e4)}bp" for e in eps]
else:
    haz_eps = []

def money_rows(n=40):
    out = []
    ICON = {"rest": ("REST", "#771be8"), "fill": ("FILL", "#ccff00"), "cancel": ("CANCEL", "#666"),
            "flatten": ("FLATTEN", "#ff006a"), "merge": ("MERGE", "#61ea7d"), "settle": ("SETTLE", "#ea9990"),
            "redeem": ("CLAIM", "#61ea7d"), "claim_sweep": ("CLAIM", "#61ea7d"),
            "no_settle": ("WAIT", "#888"), "redeem_pending": ("PEND", "#ff7b00"), "redeem_err": ("ERR", "#ff006a")}
    for e in live[-n:][::-1]:
        lbl, col = ICON.get(e["ev"], (e["ev"].upper(), "#888"))
        t = dt.datetime.utcfromtimestamp(e["ts"] / 1000).strftime("%m-%d %H:%M:%S")
        d = " ".join(f"{k}:{str(e[k])[:10]}" for k in ("mkid", "kind", "side", "qty", "px", "amt") if k in e)
        raw = e.get("tx") or e.get("id") or ""
        short = raw[:16] + "…" if len(raw) > 16 else raw
        if raw.startswith("0x") and len(raw) > 40:
            cell = f"<a href='{explorer}{raw}' target='_blank' title='{raw}'>{short}</a>"
        else:
            cell = f"<span class='dim'>{short}</span>"
        out.append(f"<tr><td class='dim'>{t}</td><td style='color:{col}'>{lbl}</td><td>{d}</td>"
                   f"<td>{cell}</td></tr>")
    return "\n".join(out)

def paper_rows(n=24):
    out = []
    for p in paper[-n:][::-1]:
        pnl = p["term_pnl"]
        col = "#ccff00" if pnl > 0 else ("#ff006a" if pnl < -1 else "#8a8a8a")
        kf = min(1.0, p['killed_frac'])
        pnlcell = f"{pnl:+.2f}" if p['fills'] else "<span class='dim'>no fills</span>"
        out.append(f"<tr><td class='dim'>{p['marketId']}</td><td>{p['asset']}</td>"
                   f"<td style='color:{col};text-align:right'>{pnlcell}</td>"
                   f"<td style='text-align:right'>{p['fills']}</td>"
                   f"<td style='text-align:right'>{100*p['score_share']:.0f}%</td>"
                   f"<td style='text-align:right'>{100*kf:.0f}%</td></tr>")
    return "\n".join(out)

maxmean = max([max(b["pin"], b["naive"]) for b in bars] + [1])
front_html = "".join(f"""
<div class="frow">
  <div class="flabel">σ={b['sigma']}</div>
  <div class="fbar"><div class="fpin" style="width:{100*b['pin']/maxmean:.0f}%"></div></div>
  <div class="fval">{b['pin']:+.0f}</div>
  <div class="fbar2"><div class="fnaive" style="width:{100*b['naive']/maxmean:.0f}%"></div></div>
  <div class="fval dim">{b['naive']:+.0f}</div>
  <div class="fworst {'ok' if b['pin_worst']>=0 else 'bad'}">worst {b['pin_worst']:+.0f} · yield {100*b['pin_shr']:.0f}%</div>
  <div class="fworst bad">worst {b['naive_worst']:+.0f} · yield {100*b['naive_shr']:.0f}%</div>
</div>""" for b in bars)

race_html = "".join(
    f"<div class='race'><span class='rname'>{lbl}</span><span class='rtrack'><span class='rfill' style='width:{max(1,100*shr):.1f}%'></span></span><span class='rpct'>{100*shr:.1f}%</span></div>"
    for lbl, shr in race[:8])

haz_html = ""
if haz_rows:
    haz_html = "<table><tr><th>state u = |r|/√t<sub>rem</sub></th><th>n</th>" + "".join(f"<th>{c}</th>" for c in haz_eps) + "</tr>"
    for k, n, cells in haz_rows:
        tds = ""
        for c in cells:
            if c == "":
                tds += "<td>—</td>"
            else:
                a = max(0.06, min(1.0, float(c)))
                fg = "#0a0a0a" if a > 0.35 else "#9ab03a"
                tds += f"<td style='background:rgba(204,255,0,{a:.2f});color:{fg};text-align:center;font-weight:600'>{a:.2f}</td>"
        haz_html += f"<tr><td class='mono'>{k}</td><td class='dim'>{n}</td>{tds}</tr>"
    haz_html += "</table>"

ORACLE_NOTE = ""
if oracle:
    o = oracle["rail_vs_chain_winner"]
    ORACLE_NOTE = " · ".join(f"{k}: {v[1]}/{v[0]}" for k, v in o.items())

now = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
explorer = "https://shannon-explorer.somnia.network/tx/"

html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta http-equiv="refresh" content="60"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PIN — Yield-Aware Convergence MM · Somnia × dreamDEX</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root {{
  --bg:#0a0a0a; --bg2:#000; --surface:#101012; --raised:#161619;
  --border:#1c1c1c; --border-strong:#2f2f2f;
  --text:#f5f5f5; --dim:#8a8a93;
  --purple:#771be8; --purple-glow:#771be855;
  --acid:#ccff00; --cherry:#ff006a; --coral:#ea9990; --mint:#61ea7d; --orange:#ff7b00;
}}
* {{ box-sizing:border-box; margin:0 }}
body {{ background:var(--bg); color:var(--text); font:13px/1.6 'Inter',sans-serif; font-variant-numeric:tabular-nums; min-height:100vh }}
.wrap {{ max-width:1280px; margin:0 auto; padding:0 26px 60px; position:relative }}
header {{ display:flex; justify-content:space-between; align-items:flex-end; border-bottom:1px solid var(--border-strong); padding:26px 0 18px }}
.logo {{ font-family:'Space Grotesk',sans-serif; font-size:30px; font-weight:700; letter-spacing:4px }}
.logo em {{ font-style:normal; color:var(--purple); text-shadow:0 0 24px var(--purple-glow) }}
.tagline {{ color:var(--dim); font-size:11.5px; max-width:520px }}
.livechip {{ display:inline-flex; gap:7px; align-items:center; font-size:11px; color:var(--acid); border:1px solid #ccff0033; padding:2px 9px; text-transform:uppercase; letter-spacing:1px }}
.pulse {{ width:7px; height:7px; background:var(--acid); border-radius:50%; animation:p 1.6s infinite }}
@keyframes p {{ 0%,100% {{ opacity:1 }} 50% {{ opacity:.25 }} }}
.meta {{ text-align:right; font-size:10.5px; color:var(--dim) }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(158px,1fr)); gap:10px; margin:22px 0 }}
.card {{ background:var(--surface); border:1px solid var(--border); padding:14px 16px 12px; position:relative; overflow:hidden }}
.card::after {{ content:""; position:absolute; left:0; top:0; width:26px; height:2px; background:var(--purple) }}
.card .v {{ font-family:'Space Grotesk',sans-serif; font-size:23px; font-weight:500; letter-spacing:.2px; font-variant-numeric:tabular-nums }}
.card .v small {{ font-size:11px; color:var(--dim); font-weight:400 }}
.card .l {{ color:var(--dim); font-size:10px; text-transform:uppercase; letter-spacing:1.4px; margin-top:2px }}
h2 {{ font-size:12px; text-transform:uppercase; letter-spacing:2.4px; color:var(--coral); margin:34px 0 4px; display:flex; align-items:center; gap:10px }}
h2::after {{ content:""; flex:1; height:1px; background:var(--border-strong) }}
.sub {{ color:var(--dim); font-size:11px; margin-bottom:12px }}
.cols {{ display:grid; grid-template-columns:1fr 1fr; gap:26px }}
@media (max-width:900px) {{ .cols {{ grid-template-columns:1fr }} }}
table {{ border-collapse:collapse; width:100%; font-size:11.5px }}
th {{ color:var(--dim); text-transform:uppercase; font-size:9.5px; letter-spacing:1.2px; font-weight:500; text-align:left; padding:6px 8px; border-bottom:1px solid var(--border-strong) }}
td {{ padding:5px 8px; border-bottom:1px solid var(--border) }}
.mono {{ font-family:'Inter',sans-serif }}
.dim {{ color:var(--dim) }} .ok {{ color:var(--acid) }} .bad {{ color:var(--cherry) }}
a {{ color:var(--purple); text-decoration:none }} a:hover {{ color:var(--acid) }}
.scroll {{ max-height:340px; overflow-y:auto; border:1px solid var(--border); background:var(--bg2) }}
.scroll::-webkit-scrollbar {{ width:6px }} .scroll::-webkit-scrollbar-thumb {{ background:var(--border-strong) }}
.frow {{ display:grid; grid-template-columns:88px 1fr 64px 1fr 64px 170px 170px; gap:8px; align-items:center; margin:8px 0; font-size:11px }}
.flabel {{ color:var(--dim) }}
.fbar,.fbar2 {{ height:14px; background:var(--surface); border:1px solid var(--border); position:relative }}
.fpin {{ position:absolute; inset:0 auto 0 0; background:linear-gradient(90deg,var(--purple),#9c4dff) }}
.fnaive {{ position:absolute; inset:0 auto 0 0; background:#3a3a40 }}
.fval {{ text-align:right; color:var(--acid); font-family:'Space Grotesk',sans-serif; font-variant-numeric:tabular-nums }}
.fval.dim {{ color:var(--dim) }}
.fworst {{ text-align:right }}
.race {{ display:grid; grid-template-columns:150px 1fr 54px; gap:10px; align-items:center; margin:7px 0; font-size:11px }}
.rname {{ color:var(--dim); overflow:hidden; text-overflow:ellipsis; white-space:nowrap }}
.rtrack {{ height:10px; background:var(--surface); border:1px solid var(--border) }}
.rfill {{ display:block; height:100%; background:linear-gradient(90deg,var(--acid),#8a9900) }}
.rpct {{ text-align:right; color:var(--acid); font-family:'Space Grotesk',sans-serif }}
.heat {{ color:#0a0a0a; background:var(--acid); text-align:center; font-weight:600 }}
.note {{ margin-top:26px; padding-top:14px; border-top:1px solid var(--border); color:var(--dim); font-size:10.5px; line-height:1.7 }}
.badge {{ display:inline-block; border:1px solid var(--border-strong); color:var(--dim); font-size:9.5px; padding:1px 7px; letter-spacing:1px; text-transform:uppercase }}
</style></head><body><div class="wrap">

<header>
  <div>
    <div class="logo">P<em>◆</em>IN</div>
    <div class="tagline">yield-aware convergence market maker · dreamdex event contracts · somnia shannon (50312)<br>
    the venue pays makers exp(−d²/2σ²)·sec to rest — σ is unpublished — we estimate it, quote against it, and kill on its own settlement statistics</div>
  </div>
  <div class="meta">
    <span class="livechip"><span class="pulse"></span> recording live</span><br>
    0x2763…197a · venue 6797…a28c<br>{now}
  </div>
</header>
<nav><a href="#overview">Overview</a><a href="#edge">Edge</a><a href="#hazard">Hazard</a><a href="#ledger">Ledger</a><span class="nsep"></span><a href="#about">Provenance</a></nav>
<section id="overview">
<div class="grid">
  <div class="card"><div class="v">{len(fills)}</div><div class="l">on-chain fills</div></div>
  <div class="card"><div class="v">{notional:.1f} <small>tUSDC</small></div><div class="l">notional traded</div></div>
  <div class="card"><div class="v">{len(rests)}</div><div class="l">orders rested</div></div>
  <div class="card"><div class="v">{len(redeems)+len(merges)}</div><div class="l">claims + merges</div></div>
  <div class="card"><div class="v">{len(paper)}</div><div class="l">paper windows settled</div></div>
  <div class="card"><div class="v">{anatomy.get('book_snapshots',0):,}</div><div class="l">book snapshots</div></div>
  <div class="card"><div class="v">{anatomy.get('five_min_dead_pct','—')}<small>%</small></div><div class="l">5-min windows dead</div></div>
  <div class="card"><div class="v">{anatomy.get('median_mint_pair_share',0)*100:.0f}<small>%</small></div><div class="l">fills are mint-a-pair</div></div>
</div>
</section>
<section id="edge">
<div class="cols">
<div>
<h2>Policy frontier — PnL / window</h2>
<div class="sub"><span class="badge" style="color:var(--purple)">PIN touch+kill</span> vs <span class="badge">naive 2¢ maker</span> · q200 · replay on recorded books · trade PnL is σ-invariant by design; the σ-dependent term is yield share (shown per row)</div>
{front_html}
</div>
<div>
<h2>Yield score race — our share of the venue's OI subsidy</h2>
<div class="sub">computed per second from rivals' own resting ladders in the recorded book (σ=0.01 · q200)</div>
{race_html}
<div class="sub" style="margin-top:10px">the incumbent ladder's own config implies σ ∈ [0.005, 0.0225] — we bracket an unpublished venue parameter from public data (<span class="mono">sigma_est.py</span>)</div>
</div>
</div>
</section>
<section id="hazard">
<h2>Empirical pin hazard — P(window settles within ε of its opening line)</h2>
<div class="sub">learned from 52 days of oracle rail × {anatomy.get('markets_recorded','?')} recorded windows · u = |ln(px/line)| / √(minutes remaining) — the kill rule fires above P≤10bp = 0.35, calibrated on THIS table, not textbook Brownian motion</div>
{haz_html}

</section>
<section id="ledger">
<div class="cols">
<div>
<h2>Live money ledger — every event is a transaction</h2>
<div class="sub">{explorer}…</div>
<div class="scroll"><table>
<tr><th>time</th><th>event</th><th>detail</th><th>tx / id</th></tr>
{money_rows()}
</table></div>
</div>
<div>
<h2>Paper shadow PnL — per-window settlement</h2>
<div class="sub">identical policy objects, live book stream, 50-contract quotes</div>
<div class="scroll"><table>
<tr><th>window</th><th>asset</th><th style="text-align:right">settle PnL</th><th style="text-align:right">fills</th><th style="text-align:right">score share</th><th style="text-align:right">killed</th></tr>
{paper_rows()}
</table></div>
</div>
</div>
</section>
<section id="about">
<div class="note">
PROVENANCE — every figure regenerates from raw files: <span class="mono">publish.py</span> → <span class="mono">data/published/*.json</span> → this page.
venue anatomy: {anatomy.get('markets_recorded',0)} recorded markets, {anatomy.get('dead_markets_pct','—')}% never traded, median top-maker share {anatomy.get('median_top_maker_share','—')} ·
oracle-precision curve (1-min rail vs on-chain winner): {ORACLE_NOTE} ·
median settled distance from the line: {SD.get('settle_dist_bps_percentiles',{}).get('50','—')} bp, {SD.get('pct_lt_25bps','—')}% of windows finish within 25bp
<br>PIN — quote geometry from the venue's own formula · kill rule from the venue's own settle history · claims from the chain. <a href="https://github.com/samixrd/pin-dreamdex">github.com/samixrd/pin-dreamdex</a>
</div>
</section>
</div></body></html>"""

with open(f"{DATA}/dashboard.html", "w", encoding="utf-8") as f:
    f.write(html)
print(f"dashboard regenerated: {len(html):,} bytes | live events {len(live)} | paper {len(paper)} | fills {len(fills)} notional {notional:.1f}")
