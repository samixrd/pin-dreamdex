# FINAL DASHBOARD AUDIT — cross-checks every rendered figure against raw files & chain.
import json, re, subprocess, statistics, datetime as dt, os

H = open("data/dashboard.html", encoding="utf-8").read()
def lj(f):
    return [json.loads(l) for l in open(f"data/{f}", encoding="utf-8") if l.strip()]

led = lj("live_ledger.jsonl")
paper = lj("paper_ledger.jsonl")
anatomy = json.load(open("data/published/venue_anatomy.json"))
hazard = json.load(open("data/published/hazard_table.json"))
final = json.load(open("data/published/sweep_final.json"))
settle = json.load(open("data/published/settle_distances.json"))
fails = []

def chk(name, ok, detail=""):
    print(("PASS " if ok else "FAIL "), name, detail)
    if not ok: fails.append(name)

fills = [e for e in led if e["ev"] == "fill"]
rests = [e for e in led if e["ev"] == "rest"]
notional = sum(e["qty"] * e["px"] for e in fills)

# 1. stat cards match raw ledger
chk("fills count", str(len(fills)) in H, f"{len(fills)}")
chk("notional", f"{notional:.1f}" in H, f"{notional:.1f}")
chk("rests count", str(len(rests)) in H, f"{len(rests)}")
chk("paper windows", str(len(paper)) in H, f"{len(paper)}")
chk("snapshots live count", anatomy["book_snapshots"] >= 6_000_000, str(anatomy["book_snapshots"]))
chk("anatomy numbers on page", str(anatomy["markets_recorded"]) in H or f"{anatomy['dead_markets_pct']}" in H)

# 2. every tx link is a plausible hash AND appears in the ledger
links = re.findall(r"href='https://shannon-explorer\.somnia\.network/tx/(0x[0-9a-f]{10,})'", H)
ledger_txs = {e.get("tx") for e in led}
chk("tx links count", len(links) >= 15, f"{len(links)} links")
chk("tx links all from ledger", all(any(t.startswith(l[:10]) for t in ledger_txs if t) for l in links))

# 3. SPOT-CHECK one tx on public RPC (not our files): does it exist, from our wallet?
RPC = "https://api.infra.testnet.somnia.network"
probe = max(links, key=len)
full = next(t for t in ledger_txs if t and t.startswith(probe))
r = subprocess.run(["curl","-s","-m","20",RPC,"-H","Content-Type: application/json",
    "-d", json.dumps({"jsonrpc":"2.0","id":1,"method":"eth_getTransactionByHash","params":[full]})],
    capture_output=True, text=True)
try:
    tx = json.loads(r.stdout)["result"]
    chk("RPC: tx exists on chain", tx is not None, probe[:14])
    chk("RPC: sender is PIN wallet", tx and tx["from"].lower() == "0x27633fec5eda3f0298bff a24018daf54dd18197a".replace(" ",""), tx["from"] if tx else "")
except Exception as e:
    chk("RPC probe", False, str(e)[:80])

# 4. frontier values == published sweep file
for sg in ("0.005","0.01","0.0225"):
    p = final[f"s{sg}-q200-1t-pk0.6"]; n = final[f"s{sg}-q200-2c-pk0.6"]
    chk(f"frontier row σ={sg}", f"{p['pnl_mean']:+.0f}".replace("+","+") in H and f"{p['pnl_mean']:+.0f}" in H,
        f"pin {p['pnl_mean']:+.0f} naive {n['pnl_mean']:+.0f}")

# 5. hazard cells match published table
haz_ok = True
for k, v in hazard.items():
    for e in [x for x in v if x != "n"]:
        if f"{v[e]:.2f}" not in H: haz_ok = False
chk("hazard table cells", haz_ok, f"{sum(len([x for x in v if x!='n']) for v in hazard.values())} cells")

# 6. yield race values match sweep file at sigma .01
race_vals = [final[f"s0.01-q200-{d}-pk{k}"]["score_share_med"] for d, k in
             (("1t","0.0"),("5t","0.0"),("1t","0.6"),("5t","0.6"),("2c","0.0"),("2c","0.6"),("1t","0.35"),("5t","0.35"))]
chk("yield race figures", all(f"{100*v:.1f}%" in H for v in race_vals), ", ".join(f"{100*v:.1f}" for v in race_vals))

# 7. paper rows trace to paper_ledger
pmis = 0
for p in paper[-24:]:
    if p["fills"] and f"{p['term_pnl']:+.2f}" not in H: pmis += 1
chk("paper PnL cells", pmis == 0, f"{pmis} mismatches")

# 8. killed_frac >100 bug stays fixed
chk("no 101% killed", "101%" not in H)

# 9. no gradient/tick artifacts user removed
chk("card tick removed", "card::after" not in H)
chk("bg gradient removed", "radial-gradient" not in H)

# 10. fonts
chk("Inter loaded", "family=Inter" in H)
chk("no slashed-zero fonts", "Source Code Pro" not in H and "Plex" not in H)

# 11. sigma honesty labels
chk("replayed-not-paid label", "replayed, not paid" in H)
chk("sigma-invariant note", "σ-invariant by design" in H)

# 12. stack still running right now (fresh ledger events in last 10 min)
newest = max(e["ts"] for e in led)
age_min = (dt.datetime.now(dt.timezone.utc).timestamp()*1000 - newest)/60000
chk("ledger is live", age_min < 10, f"newest event {age_min:.1f} min ago")

print("\n=== RESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILS: {fails}")
