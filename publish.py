# Publish headline artifacts from raw ledgers into data/published/*.json for the repo.
import json, os, statistics

os.makedirs("data/published", exist_ok=True)
def lj(f):
    try: return [json.loads(l) for l in open(f"data/{f}", encoding="utf-8") if l.strip()]
    except FileNotFoundError: return []
def fast_count(p):
    n = 0
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""): n += c.count(b"\n")
    return n

# venue anatomy
hist = lj("history.jsonl") + lj("settled.jsonl")
mk = {}
for r in hist: mk.setdefault(r["marketId"], r)
rows = list(mk.values())
dead = sum(1 for r in rows if (r.get("tradeCount") or 0) == 0)
i5 = [r for r in rows if (r.get("intervalSec") or 9999) <= 600]
mkconc, mint = [], []
for r in rows:
    fs = r.get("fills") or []
    if not fs: continue
    from collections import Counter
    top = Counter(f.get("mk") for f in fs).most_common(1)
    if top: mkconc.append(top[0][1] / len(fs))
    mint.append(sum(1 for f in fs if "PAIR" in (f.get("kind") or "")) / len(fs))
anatomy = {
    "markets_recorded": len(rows),
    "dead_markets_pct": round(100*dead/max(1,len(rows)), 1),
    "five_min_markets": len(i5),
    "five_min_dead_pct": round(100*sum(1 for r in i5 if (r.get("tradeCount") or 0)==0)/max(1,len(i5)), 1),
    "median_top_maker_share": round(statistics.median(mkconc), 3) if mkconc else None,
    "median_mint_pair_share": round(statistics.median(mint), 3) if mint else None,
    "book_snapshots": fast_count("data/books.jsonl"),
    "rail_candles_52d": fast_count("data/px_deep.jsonl"),
}
json.dump(anatomy, open("data/published/venue_anatomy.json", "w"), indent=1)
print(json.dumps(anatomy, indent=1))

# frontier tables (already compact)
for src in ("sweep_v2.json", "sweep_v3_size.json", "sweep_sigma02.json", "hazard_table.json"):
    if os.path.exists(f"data/{src}"):
        data = json.load(open(f"data/{src}"))
        json.dump(data, open(f"data/published/{src}", "w"), indent=1)

# live money ledger (small) with tx hashes — the receipts artifact
live = lj("live_ledger.jsonl")
json.dump(live, open("data/published/live_ledger.json", "w"), indent=1)
print("live ledger events published:", len(live))

# paper ledger
paper = lj("paper_ledger.jsonl")
json.dump(paper, open("data/published/paper_ledger.json", "w"), indent=1)
print("paper windows published:", len(paper))

# settlement validation (oracle precision curve) — recompute compactly
from bisect import bisect_right
rail = {"BTC": {}, "ETH": {}}
for l in open("data/px_deep.jsonl", encoding="utf-8"):
    r = json.loads(l)
    if r["asset"] in rail: rail[r["asset"]][r["t"]] = int(r["c"])/1e18
sr = {a: sorted(rail[a]) for a in rail}
def at(a, ms):
    ks = sr[a]
    if not ks or ms < ks[0] or ms > ks[-1]+90000: return None
    return rail[a][ks[bisect_right(ks, ms)-1]]
buckets = {"<2bp": [0,0], "2-5bp": [0,0], "5-10bp": [0,0], "10-25bp": [0,0], ">=25bp": [0,0]}
z_dist = []
for m in rows:
    if m.get("voided") or m.get("winningOutcome") is None: continue
    o = at(m["asset"], m["start"]*1000); s = at(m["asset"], m["expiry"]*1000)
    if not o or not s: continue
    d = abs(s/o-1)*1e4
    b = "<2bp" if d<2 else "2-5bp" if d<5 else "5-10bp" if d<10 else "10-25bp" if d<25 else ">=25bp"
    buckets[b][0]+=1
    if (s>=o)==(m["winningOutcome"]==0):
        buckets[b][1]+=1
        z_dist.append(d)
json.dump({"rail_vs_chain_winner": buckets, "n": sum(v[0] for v in buckets.values())},
          open("data/published/oracle_precision.json","w"), indent=1)
zs = sorted(z_dist)
if zs:
    dist = {p: round(zs[int(p/100*len(zs))], 1) for p in (10,25,50,75,90)}
    json.dump({"settle_dist_bps_percentiles": dist,
               "pct_lt_25bps": round(100*sum(1 for z in z_dist if z<25)/len(z_dist),1),
               "pct_lt_50bps": round(100*sum(1 for z in z_dist if z<50)/len(z_dist),1)},
              open("data/published/settle_distances.json","w"), indent=1)
    print("oracle curve:", json.dumps(buckets))
    print("settle pctiles:", dist)
print("published OK")
