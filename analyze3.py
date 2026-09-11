# PIN analysis #3: venue-wide settlement anatomy on the FULL 52-day price rail.
# Every Finalized market (backfill history) x deep rail (close + markClose):
#  - winner-agreement curve by distance bucket (oracle precision finding)
#  - |move| distribution in bps AND sigma-units -> the true pin-zone share
#  - per-cadence (5m/15m/1h/4h/24h) breakdown: which windows are coin-flips at settle
import json, math, statistics
from collections import defaultdict
from bisect import bisect_right

DATA = "data"
markets = {}
for f in ("history.jsonl", "settled.jsonl"):
    try:
        for l in open(f"{DATA}/{f}", encoding="utf-8"):
            r = json.loads(l); markets.setdefault(r["marketId"], r)
    except FileNotFoundError: pass

rail = {"BTC": {}, "ETH": {}}
mark = {"BTC": {}, "ETH": {}}
for l in open(f"{DATA}/px_deep.jsonl", encoding="utf-8"):
    r = json.loads(l)
    rail[r["asset"]][r["t"]] = int(r["c"]) / 1e18
    mark[r["asset"]][r["t"]] = int(r["mc"]) / 1e18
for l in open(f"{DATA}/px.jsonl", encoding="utf-8"):  # live ticks too
    r = json.loads(l)
    if r.get("src") == "1m" and r["asset"] in rail:
        rail[r["asset"]][r["t"]] = r["c"]; mark[r["asset"]][r["t"]] = r.get("mc", r["c"])
stamps = {a: sorted(rail[a]) for a in rail}

def at(series, a, ms):
    ks = stamps[a]
    if not ks or ms < ks[0] or ms > ks[-1] + 90_000: return None
    return series[a][ks[bisect_right(ks, ms) - 1]]

# per-asset per-minute log-vol from mark series (24h trailing at settle time would be ideal; use global recent as proxy per cadence)
def vol_window(a, t0, t1):
    ks = [k for k in stamps[a] if t0 <= k <= t1]
    pts = [mark[a][k] for k in ks]
    if len(pts) < 10: return None
    rets = [math.log(pts[i+1]/pts[i]) for i in range(len(pts)-1)]
    mu = statistics.fmean(rets)
    return math.sqrt(sum((r-mu)**2 for r in rets)/max(1,len(rets)-1))

buckets = [(0,2),(2,5),(5,10),(10,25),(25,50),(50,1e9)]
agree = {b:[0,0] for b in buckets}
rows = []
cad = defaultdict(lambda: [0,0,0])  # tested, agree, pin_lt_1sigma
void_ct = 0
for m in markets.values():
    if m.get("voided"): void_ct += 1; continue
    if m.get("winningOutcome") is None: continue
    o = at(rail, m["asset"], m["start"]*1000); s = at(rail, m["asset"], m["expiry"]*1000)
    if o is None or s is None or o == 0: continue
    chain_up = m["winningOutcome"] == 0
    up = s >= o
    d_bps = abs(s/o - 1)*1e4
    ok = up == chain_up
    for b in buckets:
        if b[0] <= d_bps < b[1]:
            agree[b][0] += 1
            if ok: agree[b][1] += 1
            break
    v = vol_window(m["asset"], m["start"]*1000 - 6*3600_000, m["expiry"]*1000)
    if v and ok:
        tau_min = max(1.0, (m["expiry"]-m["start"])/60.0)
        z = abs(math.log(s/o))/(v*math.sqrt(tau_min))
        c = int(m.get("intervalSec") or 300)
        key = 300 if c <= 400 else 900 if c <= 1000 else 3600 if c <= 4000 else 14400 if c <= 16000 else 86400
        cad[key][0] += 1
        if z < 1.0: cad[key][1] += 1
        rows.append({"z": z, "d": d_bps, "cad": key, "traded": (m.get("tradeCount") or 0) > 0})

tested = sum(v[0] for v in agree.values())
print(f"markets w/ rail coverage: {tested} | voided: {void_ct} | rail span: {__import__('datetime').datetime.utcfromtimestamp(stamps['BTC'][0]/1000).date()} -> {__import__('datetime').datetime.utcfromtimestamp(stamps['BTC'][-1]/1000).date()}")
print("\nORACLE-PRECISION CURVE (rail close vs on-chain winner):")
for b in buckets:
    t_, a_ = agree[b]
    print(f"  |move| {b[0]:>3}-{'' if b[1]<1e8 else '+'}{min(b[1],9999):<5} bps: {a_}/{t_} " + (f"= {100*a_/t_:.0f}%" if t_ else ""))
zs = sorted(r["z"] for r in rows)
if zs:
    print("\nsettle distance in SIGMA-of-window units (validated markets only):")
    for thr in (0.1, 0.25, 0.5, 1.0, 2.0):
        print(f"  < {thr:>4} σ: {100*sum(1 for z in zs if z<thr)/len(zs):>4.1f}%")
print("\nper-cadence: tested | %within 1σ (coin-flip-at-settle risk) | %traded")
for c in sorted(cad):
    t_, p_, _ = cad[c]
    tr = sum(1 for r in rows if r["cad"]==c and r["traded"])
    if t_: print(f"  {c//60:>4}m win: {t_:>4} | pin-1σ: {100*p_/t_:>5.1f}% | traded: {100*tr/t_:>5.1f}%")
