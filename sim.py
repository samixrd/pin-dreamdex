# PIN simulator — event-replay of quoting policies on recorded books.
#
# Policies (both rest zero-inventory two-sided bids, mint-a-pair style:
# BUY YES @ p_bid and BUY NO @ p_no; escrowed cost p_bid + (1-p_ask_mirror)...):
#   naive : rest YES at mid-2c and NO mirror at mid-2c (ec-maker style)
#   pin   : yield-aware distance d* = argmax_d [ W(d)*yield_rate - adverse_rate(d) ]
#           + pin-kill: pull quotes when spot within K*sigma_window of the line-to-beat
#
# Fill model (conservative, level-based):
#   our bid at p is lifted fully at next-snap ask a if a < p (pay a);
#   partial queue share if a == p.
# Adverse selection: markout = our_pay - mid_30s_later (positive = we lost), per fill.
# Yield: score = sum over resting qty of W(|p-mid|)*dt; rivals accrue on their visible
#   ladders from the same recorded books; our share = self/(self+rival) of pool.
# Terminal: hold YES/NO to settlement (validated winner from px rail), redeem 0/1.
#
import json, math, statistics, sys
from collections import defaultdict
from bisect import bisect_right

DATA = "data"

def load_jsonl(f):
    out = []
    try:
        with open(f"{DATA}/{f}", encoding="utf-8") as fh:
            for l in fh:
                l = l.strip()
                if l: out.append(json.loads(l))
    except FileNotFoundError:
        pass
    return out

books = defaultdict(list)
for r in load_jsonl("books.jsonl"):
    books[r["marketId"]].append(r)
for m in books: books[m].sort(key=lambda r: r["t"])

markets = {}
for r in load_jsonl("history.jsonl") + load_jsonl("settled.jsonl"):
    markets.setdefault(r["marketId"], r)

rail = {"BTC": {}, "ETH": {}}
for f in ("px.jsonl", "px_history.jsonl"):
    for p in load_jsonl(f):
        if p.get("src") == "1m": rail[p["asset"]][p["t"]] = p["c"]
series = {a: sorted(d.items()) for a, d in rail.items()}
stamps = {a: [t for t, _ in s] for a, s in series.items()}

def rail_at(a, ms):
    s = series.get(a)
    if not s: return None
    if ms < s[0][0] or ms > s[-1][0] + 90_000: return None
    i = bisect_right(stamps[a], ms) - 1
    return s[i][1] if i >= 0 else None

TICK = 0.001
QUOTE_Q = 10.0     # contracts per side per quote

def W(d, sigma): return math.exp(-(d * d) / (2 * sigma * sigma))

vol_cache = {}
def vol_per_sqrt_min(asset):
    if asset in vol_cache: return vol_cache[asset]
    pts = [c for _, c in series.get(asset, [])][-240:]
    if len(pts) < 30: return None
    rets = [math.log(pts[i+1] / pts[i]) for i in range(len(pts) - 1)]
    mu = statistics.fmean(rets)
    v = math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1))
    vol_cache[asset] = v
    return v

def pin_info(m):
    """validated winner + z-distance at settle (rail vs on-chain payout must agree)"""
    o = rail_at(m["asset"], m["start"] * 1000)
    sl = rail_at(m["asset"], m["expiry"] * 1000)
    if o is None or sl is None or o == 0: return None
    pn = m.get("payoutNumerators")
    chain_up = (pn[0] >= pn[1]) if pn and len(pn) == 2 else m.get("winningOutcome") == 0
    up = sl >= o
    if up != chain_up: return None
    v = vol_per_sqrt_min(m["asset"])
    if not v: return None
    tau_min = max(1.0, (m["expiry"] - m["start"]) / 60.0)
    z = abs(math.log(sl / o)) / (v * math.sqrt(tau_min))
    return {"winner_up": up, "z": z}

def best_distance(sigma, adv_coef):
    """grid-search d in ticks maximizing W(d) - adv_coef * d (yield vs adverse per sec)"""
    best, bd = None, TICK
    steps = int(0.15 / TICK)
    for i in range(1, steps + 1):
        d = i * TICK
        net = W(d, sigma) - adv_coef * d * 100  # adv_coef scaled to prob units
        if best is None or net > best:
            best, bd = net, d
    return bd

def simulate(mkid, snaps, sigma, policy, adv_coef=0.02, kill_k=0.7):
    m = markets[mkid]
    span = (snaps[-1]["t"] - snaps[0]["t"]) / 1000
    if span < 120 or len(snaps) < 600: return None
    vol = vol_per_sqrt_min(m["asset"])
    if vol is None: return None
    line = rail_at(m["asset"], m["start"] * 1000)
    pi = pin_info(m)
    if not pi or line is None: return None
    end_ms = m["expiry"] * 1000

    ts = [s["t"] for s in snaps]
    bid = None; askd = None            # bid = our BUY YES price; askd = our BUY NO dist (NO @ 1-mid-askd)
    qy = qn = cash = 0.0
    score_self = score_rival = 0.0
    adverse = 0.0; fills = 0; killed = 0.0
    d_star = best_distance(sigma, adv_coef)
    MAX_INV = 200.0        # contracts per side (inventory cap)
    FLATTEN_S = 60.0       # seconds before window end: sell back to the book

    def mid_of(s):
        return (s["bids"][0][0] + s["asks"][0][0]) / 2 if s["bids"] and s["asks"] else None

    def markout(i, pay, sign):
        j = bisect_right(ts, snaps[i]["t"] + 30_000) - 1
        j2 = min(max(j, i), len(snaps) - 1)
        m2 = mid_of(snaps[j2])
        return 0.0 if m2 is None else sign * (m2 - pay)

    for i in range(len(snaps) - 1):
        s = snaps[i]; t = s["t"]; dt = (snaps[i + 1]["t"] - t) / 1000
        mid = mid_of(s)
        if mid is None:
            bid = askd = None
            continue
        px_now = rail_at(m["asset"], t)
        tau_min = max(0.05, (end_ms - t) / 60000.0)
        near = px_now and abs(math.log(px_now / line)) < kill_k * vol * math.sqrt(tau_min)

        # ---- flatten window: sell inventory back to the book near expiry ----
        if (end_ms - t) / 1000 < FLATTEN_S and s["bids"] and s["asks"]:
            if qy > 0:                       # sell YES into best bid
                cash += s["bids"][0][0] * qy; adverse += max(0.0, -markout(i, s["bids"][0][0], +1)) * 0
                qy = 0.0
            if qn > 0:                       # NO bid mirrors YES ask: sell NO at (1 - bestAsk)
                cash += (1 - s["asks"][0][0]) * qn
                qn = 0.0
            bid = askd = None
            # after flatten attempt, only accrue rivals below
            for lv, qty in s["bids"]:
                if qty: score_rival += qty * W(abs(lv - mid), sigma) * dt
            continue

        if policy == "pin" and near:
            bid = askd = None; killed += dt
        elif policy == "naive":
            nb, na = mid - 0.02, 0.02
        else:
            nb, na = mid - d_star, d_star
        if policy != "pin" or not near:
            if bid is None or abs(bid - nb) > 1.5 * TICK:
                bid, askd = nb, na

        # accrue: rivals' visible ladders both sides
        for lv, qty in s["bids"]:
            if qty: score_rival += qty * W(abs(lv - mid), sigma) * dt
        for lv, qty in s["asks"]:
            if qty: score_rival += qty * W(abs(lv - mid), sigma) * dt
        can_y = max(0.0, MAX_INV - qy)
        can_n = max(0.0, MAX_INV - qn)
        if bid is not None:
            if can_y > 0: score_self += min(QUOTE_Q, can_y) * W(abs(bid - mid), sigma) * dt
        if askd is not None and can_n > 0:
            score_self += min(QUOTE_Q, can_n) * W(askd, sigma) * dt

        # ---- fills: orders are CONSUMED on fill and re-placed next cycle ----
        nx = snaps[i + 1]
        if bid is not None and nx["asks"] and can_y > 0:
            nba = nx["asks"][0][0]
            qty_take = min(QUOTE_Q, can_y)
            if nba < bid - 1e-12:
                cash -= nba * qty_take; qy += qty_take; fills += 1
                adverse += max(0.0, markout(i, nba, +1)) * qty_take
                bid = None                   # consumed
            elif abs(nba - bid) <= 1e-12:
                lvl = sum(q2 for p2, q2 in nx["asks"] if abs(p2 - bid) <= 1e-12) or QUOTE_Q
                share = min(lvl, qty_take)
                cash -= bid * share; qy += share; fills += 1
                adverse += max(0.0, markout(i, bid, +1)) * share
                bid = None
        if askd is not None and nx["bids"] and can_n > 0:
            nbb = nx["bids"][0][0]
            want_no = 1 - (mid + askd)
            if nbb > want_no + 1e-12:
                pay_no = 1 - nbb
                qty_take = min(QUOTE_Q, can_n)
                cash -= pay_no * qty_take; qn += qty_take; fills += 1
                adverse += max(0.0, markout(i, nbb, -1)) * qty_take
                askd = None

    win_up = pi["winner_up"]
    term = cash + (qy if win_up else 0.0) + (qn if not win_up else 0.0)
    tot = score_self + score_rival
    return {
        "marketId": mkid[-6:], "asset": m["asset"], "span_s": round(span),
        "policy": policy, "sigma": sigma, "fills": fills,
        "pnl": round(term, 3), "adverse": round(adverse, 4),
        "score_share": round(score_self / tot, 4) if tot else 0,
        "killed_frac": round(killed / span, 3), "z": round(pi["z"], 2),
    }

results = []
eligible = [mk for mk, sn in books.items() if mk in markets]
sys.stderr.write(f"replaying {len(eligible)} markets x 2 policies x {3} sigmas\n")
for mk in eligible:
    for sigma in (0.005, 0.01, 0.02):
        for pol in ("naive", "pin"):
            r = simulate(mk, books[mk], sigma, pol)
            if r: results.append(r)

json.dump(results, open(f"{DATA}/sim_results.json", "w"), indent=1)

agg = defaultdict(list)
for r in results: agg[(r["policy"], r["sigma"])].append(r)
hdr = f"{'policy/sigma':>14} {'n':>3} {'PnL med':>8} {'PnL mean':>8} {'win%':>5} {'adv/100u$':>9} {'scoreShr':>8} {'kill%':>6} {'fills/1ks':>9}"
print(hdr)
for (pol, sg), rs in sorted(agg.items()):
    pnls = [x["pnl"] for x in rs]
    adv = [x["adverse"] / max(1, abs(x["pnl"]) if x["pnl"] else 1) for x in rs]
    adv100 = [100 * x["adverse"] / max(1, x["span_s"] / 10) for x in rs]
    print(f"{pol+'/'+str(sg):>14} {len(rs):>3} {statistics.median(pnls):>8.2f} {statistics.fmean(pnls):>8.2f} "
          f"{100*sum(1 for x in pnls if x>0)/len(pnls):>5.0f} {statistics.fmean(adv100):>9.4f} "
          f"{statistics.fmean(x['score_share'] for x in rs):>8.4f} {100*statistics.fmean(x['killed_frac'] for x in rs):>6.1f} "
          f"{statistics.fmean(x['fills']/max(1,x['span_s'])*1000 for x in rs):>9.2f}")

# pin-risk table: how many replayed windows settled within N sigma of the line
zs = sorted(x["z"] for x in results if x["policy"] == "naive")
if zs:
    print("\nsettle z (|move|/sigma_window) across replayed windows:")
    for thr in (0.2, 0.5, 1.0, 2.0):
        c = sum(1 for z in zs if z < thr)
        print(f"  < {thr} sigma: {c}/{len(zs)} = {100*c/len(zs):.0f}%")
