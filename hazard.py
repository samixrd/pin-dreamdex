# Empirical pin-hazard table (multi-eps): P(settle within eps of line | state u).
import json, math, statistics
from bisect import bisect_right
from pin_core import load_all

books, markets, series = load_all(books_too=False)
stamps = {a: [t for t, _ in s] for a, s in series.items()}
EPS_LIST = [0.0002, 0.0005, 0.001, 0.0025, 0.005]

def rail_at(a, ms):
    s = series.get(a)
    if not s: return None
    if ms < s[0][0] or ms > s[-1][0] + 90_000: return None
    i = bisect_right(stamps[a], ms) - 1
    return s[i][1] if i >= 0 else None

obs = []   # (u, final_move_frac_abs)
for mk, m in markets.items():
    if m.get("voided") or m.get("winningOutcome") is None: continue
    o = rail_at(m["asset"], m["start"] * 1000); sl = rail_at(m["asset"], m["expiry"] * 1000)
    if not o or not sl or o == 0: continue
    if (sl >= o) != (m["winningOutcome"] == 0): continue
    final_d = abs(sl / o - 1)
    span = m["expiry"] - m["start"]
    for frac in (0.1, 0.25, 0.5, 0.75, 0.9):
        t = m["start"] + span * frac
        px = rail_at(m["asset"], t * 1000)
        if not px: continue
        rem_min = max(0.2, (m["expiry"] - t) / 60.0)
        u = abs(math.log(px / o)) / math.sqrt(rem_min)
        obs.append((u, final_d))
print(f"state obs: {len(obs)} from {len(set(int(i/5) for i in range(0,len(obs))))} ...", end=" ")
n_win = len(obs) // 5
print(f"~{n_win} windows")

UB = [0, 0.0002, 0.0005, 0.001, 0.002, 0.004, 0.008, 0.015, 0.03, 1e9]
header = "u bucket            n  " + "  ".join(f"P<={int(e*1e4)}bp" for e in EPS_LIST)
print(header)
table = {}
for lo, hi in zip(UB, UB[1:]):
    sel = [(u, d) for u, d in obs if lo <= u < hi]
    if len(sel) < 5: continue
    row = f"[{lo:>6},{hi if hi<1e9 else 'inf':>4}) {len(sel):>5}  "
    cells = {}
    for e in EPS_LIST:
        h = statistics.fmean(1 if d < e else 0 for _, d in sel)
        cells[e] = round(h, 3)
        row += f"{h:>8.3f}  "
    table[f"{lo}-{hi}"] = {"n": len(sel), **{str(e): cells[e] for e in EPS_LIST}}
    print(row)
json.dump(table, open("data/hazard_table.json", "w"), indent=1)

# demo the lookup: 4h ETH state r=10.2bps tau=282min; and a 5m parked state
for name, r_bps, tau in [("4h ETH @10%", 2.5, 254), ("5m BTC parked at line", 0.3, 2.5), ("15m moved 20bps w/ 5 left", 20, 5)]:
    u = (r_bps / 1e4) / math.sqrt(tau)
    for k, v in table.items():
        lo, hi = map(float, k.split("-"))
        if lo <= u < hi:
            print(f"{name}: u={u:.4f} -> " + " ".join(f"P<={int(e*1e4)}bp={v[str(e)]}" for e in EPS_LIST))
            break
