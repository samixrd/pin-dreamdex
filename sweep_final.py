# PIN final sweep — hazard-form kill (P(pin@10bp) thresholds), the same code path live.ts uses.
import json, statistics, sys
from pin_core import load_all, simulate

books, markets, series = load_all()
stamps = {a: [t for t, _ in s] for a, s in series.items()}
rows = [mk for mk, sn in books.items() if mk in markets]
sys.stderr.write(f"{len(rows)} dense markets\n")

def run(**kw):
    return [r for r in (simulate(mk, books[mk], markets[mk], series, stamps, **kw) for mk in rows) if r]

def agg(rs):
    if not rs: return None
    pnls = [x["pnl"] for x in rs]
    return {"n": len(rs), "pnl_med": round(statistics.median(pnls), 2),
            "pnl_mean": round(statistics.fmean(pnls), 2), "worst": round(min(pnls), 2),
            "win_pct": round(100*sum(1 for p in pnls if p > 0)/len(pnls)),
            "adv_mean": round(statistics.fmean(x["adverse"] for x in rs), 2),
            "fills_ks": round(statistics.fmean((x["fills_y"]+x["fills_n"])/x["span_s"]*1000 for x in rs), 1),
            "score_share_med": round(statistics.median(x["score_share"] for x in rs), 4),
            "killed": round(statistics.fmean(x["killed_frac"] for x in rs), 2)}

res = {}
for sigma in (0.005, 0.01, 0.0225):
    for q, cap in ((50.0, 500.0), (200.0, 2000.0)):
        for d, dn in ((0.001, "1t"), (0.005, "5t"), (0.02, "2c")):
            for k in (0.0, 0.35, 0.6):
                key = f"s{sigma}-q{int(q)}-{dn}-pk{k}"
                a = agg(run(sigma=sigma, d=d, kill_k=k, quote_q=q, max_inv=cap))
                res[key] = a
                print(f"{key:>24}", json.dumps(a), flush=True)
json.dump(res, open("data/sweep_final.json", "w"), indent=1)
