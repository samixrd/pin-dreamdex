# Deep px backfill via direct GraphQL: 52 days of M1 candles, BTC/ETH, close + markClose.
# Resumable: pages forward from the newest bucket already stored.
import json, os, sys, urllib.request
from collections import defaultdict

DATA = "data"
URL = "https://price-feed.dev.oracle.somnia.host/v1/graphql"
OUT = os.path.join(DATA, "px_deep.jsonl")
STATE = os.path.join(DATA, "px_deep_state.json")

def gql(query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())

have = defaultdict(lambda: None)  # asset -> min bucket stored (we page DESC toward past)
if os.path.exists(OUT):
    with open(OUT, encoding="utf-8") as f:
        for l in f:
            r = json.loads(l)
            a = r["asset"]
            if have[a] is None or r["t"] < have[a]: have[a] = r["t"]
    print("resume oldest:", {k: v for k, v in dict(have).items()})

Q = """query($where: Candle_bool_exp!, $limit: Int!) {
  Candle(where: $where, order_by: {bucketStart: desc}, limit: $limit) {
    bucketStart open high low close markClose
  }
}"""

for sym, asset in [("BTC/USDC", "BTC"), ("ETH/USDC", "ETH")]:
    floor = 1784592000  # feed's oldest bucket (Jul 21)
    cursor = 1789063200 if have[asset] is None else have[asset]  # resume desc from stored oldest
    n = 0
    while cursor > floor:
        where = {"symbol": {"_eq": sym}, "resolution": {"_eq": "M1"},
                 "bucketStart": {"_lt": str(cursor)}}
        d = gql(Q, {"where": where, "limit": 5000})
        rows = d.get("data", {}).get("Candle", [])
        if not rows: break
        page_min = cursor
        with open(OUT, "a", encoding="utf-8") as f:
            for r in rows:
                t = int(r["bucketStart"])
                # store RAW integer strings; analysis normalizes per-asset scale
                f.write(json.dumps({"t": t * 1000, "src": "1m", "asset": asset,
                                    "o": r["open"], "h": r["high"],
                                    "l": r["low"], "c": r["close"],
                                    "mc": r["markClose"]}) + "\n"); n += 1
                page_min = min(page_min, t)
        # server caps pages at 5000 — advance the cursor and KEEP GOING to the floor
        if page_min >= cursor: break
        cursor = page_min
        print(f"{asset}: {n} rows, oldest {cursor}", flush=True)
print("deep backfill done")
