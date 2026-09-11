# PIN sweep v2 — corrected fill model (pin_core). Grid: d x kill_k x skew_gamma at sigma bands.
import json, statistics, sys
from pin_core import load_all, simulate

books, markets, series = load_all()
stamps = {a: [t for t, _ in s] for a, s in series.items()}

rows = [mk for mk, sn in books.items() if mk in markets]
sys.stderr.write(f"{len(rows)} dense-replay markets; rail pts: " + ", ".join(f"{a} {len(series[a])}" for a in series) + "\n")

def run(**kw):
    out = []
    for mk in rows:
        r = simulate(mk, books[mk], markets[mk], series, stamps, **kw)
        if r: out.append(r)
    return out

def agg(rs):
    if not rs: return None
    pnls = [x["pnl"] for x in rs]
    return {"n": len(rs),
            "pnl_med": round(statistics.median(pnls), 2),
            "pnl_mean": round(statistics.fmean(pnls), 2),
            "win_pct": round(100 * sum(1 for p in pnls if p > 0) / len(pnls)),
            "adv_mean": round(statistics.fmean(x["adverse"] for x in rs), 2),
            "fills_ks": round(statistics.fmean((x["fills_y"] + x["fills_n"]) / x["span_s"] * 1000 for x in rs), 1),
            "score_share_med": round(statistics.median(x["score_share"] for x in rs), 4),
            "killed": round(statistics.fmean(x["killed_frac"] for x in rs), 2)}

results = {}
configs = [
    ("naive-2c-nokill", dict(d=0.02, kill_k=0.0)),
    ("naive-2c-kill07", dict(d=0.02, kill_k=0.7)),
    ("touch-1t-kill07", dict(d=0.001, kill_k=0.7)),
    ("touch-1t-kill0", dict(d=0.001, kill_k=0.0)),
    ("5t-kill07", dict(d=0.005, kill_k=0.7)),
    ("5t-kill03", dict(d=0.005, kill_k=0.3)),
    ("10t-kill07", dict(d=0.01, kill_k=0.7)),
    ("5t-kill07-skew", dict(d=0.005, kill_k=0.7, skew_gamma=1.0)),
    ("1t-kill07-skew", dict(d=0.001, kill_k=0.7, skew_gamma=1.0)),
    ("5t-kill10-skew", dict(d=0.005, kill_k=1.0, skew_gamma=2.0)),
]
for name, kw in configs:
    for sigma in (0.005, 0.01):
        a = agg(run(sigma=sigma, **kw))
        results[f"{name}@{sigma}"] = a
        print(f"{name:>18}@{sigma:<5}", json.dumps(a))

json.dump(results, open("data/sweep_v2.json", "w"), indent=1)
