# sigma_est_v2: ML fit of the yield band sigma from the incumbent's resting geometry.
# Model: a rational maker under band sigma with requote interval T rests no further than
# d_max(sigma) where W(d)/d^2 is maximized... simpler & defensible: the venue's SNAP rule
# (bot-kit yield.ts: snapPriceToMinWeight with min-weight floor w0) means makers keep W>=w0.
# Observed ladder distance d_obs and level spacing => for candidate (sigma,w0),
# P(d_obs | sigma,w0) = density of distances a w0-floor policy produces = [d <= sigma*sqrt(-2ln w0)]
# => support radius R(sigma,w0)= sigma*sqrt(-2ln w0). Max-likelihood over grid: all mass within R,
# prefer the SMALLEST R consistent (tightest band), i.e. sigma_hat = max_obs_d / sqrt(-2 ln w0).
# Cross-check against the markout-curve optimum (GPSS): where does observed profit per fill peak?
import json, math, statistics
from collections import defaultdict

# observed: first-level resting distances from mid (bids and asks), and full ladder levels
dists1, dists3 = [], []
seen_markets = 0
snaps_seen = 0
with open("data/books.jsonl", encoding="utf-8") as f:
    for l in f:
        r = json.loads(l)
        b, a = r.get("bids") or [], r.get("asks") or []
        if not b or not a: continue
        mid = (b[0][0] + a[0][0]) / 2
        snaps_seen += 1
        d = abs(b[0][0] - mid)
        dists1.append(d)
        for lv, q in (b[:3] + a[:3]):
            dists3.append(abs(lv - mid))
        if snaps_seen > 2_000_000: break
print(f"snaps used: {snaps_seen:,} | first-level median d: {statistics.median(dists1):.4f} p95: {sorted(dists1)[int(.95*len(dists1))]:.4f}")

# The first level of a 3-level ladder sits ~d/2 from mid (levels above/below mid each offset by half-spread):
# our books show ladders like bid 0.552 / ask 0.582 with mid .567 => first-level d = spread/2
q95 = sorted(dists1)[int(.95*len(dists1))]
med3 = statistics.median(dists3)
print(f"any-level median d: {med3:.4f} | first-level p95: {q95:.4f}")

# sigma_hat for floors w0 = 0.3, 0.5 (e^-0.5~0.607 ops default), 0.607:
rows = []
for w0 in (0.10, 0.30, 0.50, 0.607):
    for d_ref, lbl in ((med3, "median"), (q95, "p95")):
        sig = d_ref / math.sqrt(-2 * math.log(w0))
        rows.append((w0, lbl, round(sig, 4)))
        print(f"floor w0={w0:<5} via {lbl:<6} => sigma ≈ {sig:.4f}")

# GPSS cross-check: adverse markout curve says d in [0.01,0.02] is FAVORABLE flow, >=0.03 toxic.
# A maker optimizing yield+spread would rest near the top of the favorable band => the observed
# 1-2.25c ladders are jointly consistent with sigma in [0.005, 0.0225] but the WEIGHT shifts:
# if sigma were 0.005, a w0=0.607 floor forces d<=0.0062 — but ladders sit at 0.010-0.025 half
# of observed snaps (p95 above) => floor-implied sigma from p95 is the binding estimate.
print("\nBinding estimate: sigma ~ [%.4f, %.4f]  (floor w0=0.607: median vs p95 spread)" % (
    statistics.median(dists1)/math.sqrt(-2*math.log(0.607)),
    q95/math.sqrt(-2*math.log(0.607))))
json.dump({"snaps": snaps_seen, "median_d": statistics.median(dists1), "p95_d": q95,
           "any_level_median": med3, "grid": rows},
          open("data/published/sigma_est_v2.json", "w"), indent=1)
print("written data/published/sigma_est_v2.json")
