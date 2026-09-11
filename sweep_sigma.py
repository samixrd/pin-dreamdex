# Rerun of the decisive configs at sigma = 0.02 (the venue-behavior-implied band)
import json, statistics, sys
from pin_core import load_all, simulate

books, markets, series = load_all()
stamps = {a: [t for t, _ in s] for a, s in series.items()}
rows = [mk for mk, sn in books.items() if mk in markets]

def run(**kw):
    out = []
    for mk in rows:
        r = simulate(mk, books[mk], markets[mk], series, stamps, **kw)
        if r: out.append(r)
    return out

def agg(rs):
    if not rs: return None
    pnls = [x["pnl"] for x in rs]
    return {"n": len(rs), "pnl_med": round(statistics.median(pnls), 2),
            "pnl_mean": round(statistics.fmean(pnls), 2), "worst": round(min(pnls), 2),
            "win_pct": round(100 * sum(1 for p in pnls if p > 0) / len(pnls)),
            "adv_mean": round(statistics.fmean(x["adverse"] for x in rs), 2),
            "fills_ks": round(statistics.fmean((x["fills_y"]+x["fills_n"]) / x["span_s"] * 1000 for x in rs), 1),
            "score_share_med": round(statistics.median(x["score_share"] for x in rs), 4)}

res = {}
for sigma in (0.01, 0.015, 0.02):
    for q, cap in ((200.0, 2000.0), (50.0, 500.0)):
        for d, name in ((0.001, "touch"), (0.005, "5t"), (0.02, "2c")):
            for k in (0.0, 0.3):
                a = agg(run(sigma=sigma, d=d, kill_k=k, quote_q=q, max_inv=cap))
                key = f"s{sigma}-q{int(q)}-{name}-kill{k}"
                res[key] = a
                print(f"{key:>22}", json.dumps(a), flush=True)
json.dump(res, open("data/sweep_sigma02.json", "w"), indent=1)
