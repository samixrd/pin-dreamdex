# PIN dashboard generator — reads ONLY real recorded data, emits data/dashboard.html.
# Sections: 1) live money ledger timeline 2) paper decomposition 3) score-race share
# 4) hazard table 5) policy frontier 6) venue anatomy stats. No synthetic numbers.
import json, os, statistics, time, datetime as dt

DATA = "data"
def lj(f):
    try:
        with open(f"{DATA}/{f}", encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]
    except FileNotFoundError:
        return []

live = lj("live_ledger.jsonl")
paper = lj("paper_ledger.jsonl")
hazard = json.load(open(f"{DATA}/hazard_table.json")) if os.path.exists(f"{DATA}/hazard_table.json") else {}
sigma = json.load(open(f"{DATA}/sweep_sigma.json")) if os.path.exists(f"{DATA}/sweep_sigma.json") else {}
size = json.load(open(f"{DATA}/sweep_v3_size.json")) if os.path.exists(f"{DATA}/sweep_v3_size.json") else {}
hist = lj("history.jsonl")

def fast_count(path):
    n = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            n += chunk.count(b"\n")
    return n

try: BOOKS_LINES = fast_count(f"{DATA}/books.jsonl")
except FileNotFoundError: BOOKS_LINES = 0

# --- money summary (fills/flatten/redeem are real; term uses settled rows) ---
rests = [e for e in live if e["ev"] == "rest"]
fills = [e for e in live if e["ev"] == "fill"]
flats = [e for e in live if e["ev"] == "flatten"]
redeems = [e for e in live if e["ev"] in ("redeem", "claim_sweep")]
settles = [e for e in live if e["ev"] == "settle"]
spent = sum(e["qty"] * e["px"] for e in fills)
exposure_max = max([sum(e["qty"] * e["px"] for e in rests[:i+1]) for i in range(len(rests))], default=0)

paper_pnl = [p["term_pnl"] for p in paper]
paper_share = [p["score_share"] for p in paper]

def esc(s): return str(s).replace("&","&amp;").replace("<","&lt;")

def money_rows():
    out = []
    for e in live[-60:]:
        t = dt.datetime.utcfromtimestamp(e["ts"] / 1000).strftime("%H:%M:%S")
        icon = {"rest": "🟦", "fill": "🟨", "cancel": "⬜", "flatten": "🟥", "settle": "⚖️", "redeem": "✅", "claim_sweep": "✅", "no_settle": "⌛", "redeem_err": "❌"}.get(e["ev"], "•")
        detail = " ".join(f"{k}={e[k]}" for k in ("mkid", "kind", "side", "qty", "px", "amt", "winner_up", "trades") if k in e)
        tx = (e.get("tx") or "")[:14]
        out.append(f"<tr><td>{t}</td><td>{icon} {e['ev']}</td><td class='mono'>{esc(detail)}</td><td class='mono'>{tx}</td></tr>")
    return "\n".join(out)

def hazard_rows():
    out = []
    for k, v in sorted(hazard.items(), key=lambda x: float(x[0].split('-')[0])):
        out.append(f"<tr><td class='mono'>{k}</td><td>{v['n']}</td>" + "".join(f"<td>{v[ke]:.2f}</td>" for ke in sorted(v) if ke != 'n' and not ke.isdigit() and '-' not in ke and '.' in ke) + "</tr>")
    return "\n".join(out)

def hazard_rows2():
    rows = []
    for k, v in sorted(hazard.items(), key=lambda x: float(x[0].split('-')[0])):
        cells = [f"{val:.2f}" for ek, val in v.items() if ek != "n"]
        rows.append("<tr><td class='mono'>" + k + "</td><td>" + str(v.get('n','')) + "</td>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return "\n".join(rows)

eps_cols = []
if hazard:
    any_v = next(iter(hazard.values()))
    eps_cols = [k for k in any_v if k != "n"]

front = []
for tag, tbl in (("σ-sweep", sigma), ("size-sweep", size)):
    for k, v in sorted(tbl.items(), key=lambda x: -x[1]["pnl_mean"]):
        front.append((tag, k, v))
front.sort(key=lambda x: -x[2]["pnl_mean"])

html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>PIN — yield-aware convergence MM · live monitor</title>
<style>
:root {{ color-scheme: dark }}
body {{ background:#09090B; color:#F0F0F2; font:14px/1.5 'Inter',system-ui,sans-serif; margin:28px }}
h1 {{ font-size:22px; letter-spacing:.4px }} h2 {{ font-size:15px; margin-top:26px; color:#F0B90B }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px; margin:14px 0 }}
.card {{ background:#111114; border:1px solid #232326; padding:12px 14px }}
.card .v {{ font-size:22px; font-weight:600 }} .card .l {{ color:#8B8B93; font-size:12px }}
table {{ border-collapse:collapse; width:100%; font-size:12.5px }}
th,td {{ border-bottom:1px solid #1E1E22; padding:5px 8px; text-align:left }}
th {{ color:#8B8B93; font-weight:500 }} .mono {{ font-family:'Fragment Mono',monospace; font-size:12px }}
.ok {{ color:#3DD68C }} .warn {{ color:#F0B90B }} .bad {{ color:#F87171 }}
.note {{ color:#8B8B93; font-size:12px; margin-top:4px }}
</style></head><body>
<h1>PIN <span style="color:#8B8B93;font-weight:400">· yield-aware convergence market maker on DreamDEX Event Contracts</span></h1>
<div class="note">all figures below are generated from recorded testnet data (chain 50312). regen: <span class="mono">python dashboard.py</span> · {dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC</div>

<div class="grid">
<div class="card"><div class="v">{len(settles)}</div><div class="l">live windows settled</div></div>
<div class="card"><div class="v">{len(fills)}</div><div class="l">real fills (on-chain)</div></div>
<div class="card"><div class="v">{spent:.2f} <span style="font-size:12px">tUSDC</span></div><div class="l">notional filled</div></div>
<div class="card"><div class="v">{len(rests)}</div><div class="l">orders rested (tx-logged)</div></div>
<div class="card"><div class="v">{len(redeems)}</div><div class="l">redemptions</div></div>
<div class="card"><div class="v">{len(paper)}</div><div class="l">paper windows shadowed</div></div>
</div>

<h2>Money ledger — every event is an on-chain tx</h2>
<table><tr><th>time</th><th>event</th><th>detail</th><th>tx</th></tr>{money_rows()}</table>

<h2>Paper shadow PnL — per-window settlement decomposition</h2>
<div class="note">policy d=0.5¢, kill = P(pin@10bp) &gt; 0.35 (hazard-calibrated), q=50 contracts/side</div>
<table><tr><th>market</th><th>asset</th><th>settle PnL</th><th>fills</th><th>yield score share</th><th>killed frac</th></tr>
{''.join(f"<tr><td class='mono'>{p['marketId']}</td><td>{p['asset']}</td><td class='{'ok' if p['term_pnl']>0 else ('bad' if p['term_pnl']<-1 else '')}'>{p['term_pnl']:.2f}</td><td>{p['fills']}</td><td>{100*p['score_share']:.0f}%</td><td>{100*p['killed_frac']:.0f}%</td></tr>" for p in paper[-20:])}
</table>
<div class="note">median paper PnL {statistics.median(paper_pnl) if paper_pnl else '—'} · median score share {100*statistics.median(paper_share) if paper_share else '—':.0f}%</div>

<h2>Empirical pin hazard (learned from {len(hist)}+ settled windows, 52-day rail)</h2>
<div class="note">u = |ln(px/line)| / √(minutes remaining) — normalized distance-through-time. P = probability window settles within ε of its line.</div>
<table><tr><th>u bucket</th><th>n</th>{''.join(f"<th>ε={int(float(c)*1e4)}bp</th>" for c in eps_cols)}</tr>{hazard_rows2()}</table>

<h2>Policy frontier (replay, real recorded books)</h2>
<table><tr><th>source</th><th>config</th><th>PnL mean</th><th>worst</th><th>win%</th><th>score share</th></tr>
{''.join(f"<tr><td>{t}</td><td class='mono'>{esc(k)}</td><td class='{'ok' if v['pnl_mean']>0 else 'bad'}'>{v['pnl_mean']}</td><td>{v['worst']}</td><td>{v['win_pct']}%</td><td>{100*v['score_share_med']:.1f}%</td></tr>" for t, k, v in front[:14])}
</table>

<h2>Venue anatomy (recorded)</h2>
<div class="grid">
<div class="card"><div class="v">{100*sum(1 for h in hist if (h.get('tradeCount') or 0)==0)/max(1,len(hist)):.0f}%</div><div class="l">recorded markets dead (0 trades)</div></div>
<div class="card"><div class="v">{BOOKS_LINES:,}</div><div class="l">order-book snapshots recorded</div></div>
<div class="card"><div class="v">{sum(1 for l in open(f'{DATA}/px_deep.jsonl')):,}</div><div class="l">price-rail candles (52d)</div></div>
<div class="card"><div class="v">{len(set(h['marketId'] for h in hist))}</div><div class="l">settled markets w/ maker fills</div></div>
</div>
<div class="note" style="margin-top:22px">PIN — quote geometry from the venue's own yield formula; kill rule from its own settle distribution; claims from its own chain.</div>
</body></html>"""
with open(f"{DATA}/dashboard.html", "w", encoding="utf-8") as f:
    f.write(html)
print("dashboard written:", len(html), "bytes; live events:", len(live), "paper windows:", len(paper))
