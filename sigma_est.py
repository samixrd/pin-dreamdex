# PIN — sigma estimator v1: infer the venue's undisclosed yield band sigma from public data.
#
# Idea: the venue's payout rule is score = q * exp(-d^2/2sigma^2) * seconds, but sigma is
# never published (kit: YO_SIGMA_RAW manual). Two public observables constrain it:
#  (1) BEHAVIOR: incumbent makers choose resting distances. If ladders cluster at distance
#      d_ladder, their config implies a W-floor: sigma >= d / sqrt(-2 ln W_min) for any
#      sensible W_min they'd accept (ops hint: default min-weight ~= e^-0.5 -> d=sigma).
#  (2) OUTCOME: we can MEASURE realized yield share of a replay policy at assumed sigma
#      and compare against reality — the venue's actual score distribution — only if we
#      could see payouts; we can't yet. So instead use (1) + (3):
#  (3) ADVERSE curve: E[markout30 | fill at distance d] grows ~linearly in d (you get
#      picked off when mid moved d toward you). The OPTIMAL quote distance d* is where
#      marginal yield loss == marginal adverse gain:
#        d* = argmax_d [ W(d;sigma) * S - A(d) ]   with A(d) = a*d
#      => sigma is identifiable from the pair (d*, a) IF the incumbent is optimizing:
#      assuming the observed ladder distance IS their d*, invert for sigma.
#
# Output: per-market ladder distances (from books), adverse slope a (from fills x rail),
# implied sigma band. This is a genuine measurement of an unpublished venue parameter.

import json, math, statistics
from collections import defaultdict
from bisect import bisect_right
from pin_core import load_all

books, markets, series = load_all()
stamps = {a: [t for t, _ in s] for a, s in series.items()}

# ---- 1. ladder geometry from recorded books: distance of rival resting levels from mid ----
ladder = defaultdict(list)   # marketId -> list of (dist_from_mid, qty) for the nearest 3 levels/side
for mk, snaps in books.items():
    for s in snaps:
        if not s["bids"] or not s["asks"]: continue
        mid = (s["bids"][0][0] + s["asks"][0][0]) / 2
        for side in ("bids", "asks"):
            for lv, qty in s[side][:3]:
                d = abs(lv - mid) / 2 if False else abs(lv - mid)
                ladder[mk].append((d, qty))
    # keep memory sane: subsample
# summarize: modal distances of the 3-level ladders (levels 2/3 reveal the spacing rule)
spacing = defaultdict(lambda: defaultdict(int))
for mk, rows in ladder.items():
    # bucket distance to 0.5c
    for d, q in rows:
        b = round(d / 0.005) * 0.005
        spacing[mk][b] += 1
print("=== ladder spacing (distance-from-mid histogram, top per market) ===")
sigmas_from_ladder = []
for mk in list(spacing)[:12]:
    top = sorted(spacing[mk].items(), key=lambda x: -x[1])[:4]
    tot = sum(v for _, v in spacing[mk].items())
    print(mk[-6:], [(d, round(100*c/tot, 1)) for d, c in top])

# ---- 2. adverse-selection slope from fills x rail ----
# per fill (from history/settled), reconstruct mid at fill time from books, markout30 from rail mid
def mid_series(mk):
    out = []
    for s in books.get(mk, []):
        if s["bids"] and s["asks"]:
            out.append((s["t"], (s["bids"][0][0] + s["asks"][0][0]) / 2))
    return out

fill_rows = []
for mk, m in markets.items():
    if m.get("voided") or not m.get("fills") or m.get("tradeCount", 0) < 10: continue
    ms = mid_series(mk)
    if len(ms) < 30: continue
    ts = [t for t, _ in ms]
    for f in m["fills"]:
        if not f.get("t"): continue
        t_ms = f["t"] * 1000
        i = bisect_right(ts, t_ms) - 1
        if i < 0: continue
        mid_fill = ms[i][1]
        # markout 30s
        j = bisect_right(ts, t_ms + 30_000) - 1
        if j >= len(ms): continue
        mid_after = ms[j][1]
        p = float(f["p"]) / 1e6
        side = f["side"]
        # maker's effective PRICE PAID (prob units) and direction of beneficial mid move:
        #  BUY_YES @p: pays p, wants mid UP          -> mark = (mid2 - p)
        #  SELL_YES @p: receives p, wants mid DOWN   -> mark = (p - mid2)
        #  BUY_NO: buy No at (1-p) => pays 1-p YES-equiv, wants mid DOWN -> mark = ((1-p) - (1-mid2)) = mid2 - p? no:
        #    maker bought NO paying (1-p); NO redeems at 1-mid later => mark = ((1-mid2) - (1-p)) = (p - mid2)
        #  SELL_NO: receives (1-p); short NO => mark = ((1-p) - (1-mid2))*-1... long YES view => (mid2 - p)
        if side == "BUY_YES":   mark = mid_after - p
        elif side == "SELL_YES": mark = p - mid_after
        elif side == "BUY_NO":  mark = p - mid_after
        else:                    mark = mid_after - p   # SELL_NO
        fill_rows.append((abs(mid_fill - p), mark, mk[-6:]))

by_dist = defaultdict(list)
for d, adv, mk in fill_rows:
    b = min(int(d / 0.01), 10)
    by_dist[b * 0.01].append(adv)
print(f"\n=== adverse selection vs |fill-mid| ({len(fill_rows)} reconstructed maker fills) ===")
print(f"{'dist':>6} {'n':>6} {'E[markout]':>10} {'P(loss>2c)':>10}")
pts = []
for b in sorted(by_dist):
    v = by_dist[b]
    if len(v) < 15: continue
    e = statistics.fmean(v)
    tail = sum(1 for x in v if x < -0.02) / len(v)
    print(f"{b:>6.2f} {len(v):>6} {e:>10.4f} {100*tail:>9.1f}%")
    pts.append((b, e))
if len(pts) >= 4:
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    slope = sum((x-mx)*(y-my) for x, y in pts) / sum((x-mx)**2 for x in xs)
    print(f"\nadverse slope a ~= {slope:.3f} (markout lost per unit quote distance)")
    # implied sigma if incumbent d* chosen optimally for W-floor e^-0.5:
    d_ladder = statistics.median([d for d, q in [x for mk in list(ladder) [:6] for x in ladder[mk][:300]]]) if ladder else None
    print(f"median ladder distance from mid: {d_ladder:.4f}" if d_ladder else "no ladder data")
    # if ops min-weight is ~e^-0.5, sigma ~= d_ladder
    print(f"implied sigma band ~= {d_ladder:.4f} (ops floor e^-0.5 convention)" if d_ladder else "")
