# PIN core — order lifecycle + fill + adverse-selection model for EC books. Shared by sim/sweep.
# Fill rules (single YES-quoted book, mint-a-pair semantics):
#   our BUY YES @ pb is lifted when a YES ask rests at a <= pb  (pay a)
#   our BUY NO  @ pn (YES-equiv xe = 1-pn) is lifted when a YES bid arrives at b >= xe
#     but b < best ask (else it would have crossed the ask instead)
#   consumed-on-fill; re-placed next requote cycle.
# Adverse selection per fill = max(0, paid - mark_30s_later_of_what_we_bought).
import json, math, statistics
from collections import defaultdict
from bisect import bisect_right

TICK = 0.001
QUOTE_Q = 10.0

def load_all(DATA="data", books_too=True):
    def lj(f):
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
    if books_too:
        for r in lj("books.jsonl"):
            books[r["marketId"]].append(r)
        for m in books: books[m].sort(key=lambda r: r["t"])
    markets = {}
    for r in lj("history.jsonl") + lj("settled.jsonl"):
        markets.setdefault(r["marketId"], r)
    rail = {"BTC": {}, "ETH": {}}
    for f in ("px.jsonl", "px_history.jsonl", "px_deep.jsonl"):
        for p in lj(f):
            if p.get("src") == "1m":
                a = p["asset"]
                if a in rail:
                    c = p["c"]
                    if isinstance(c, str): c = int(c) / 1e18   # raw feed units
                    rail[a][p["t"]] = c
    series = {a: sorted(d.items()) for a, d in rail.items()}
    return books, markets, series

def rail_at(series, stamps, a, ms):
    s = series.get(a)
    if not s: return None
    if ms < s[0][0] or ms > s[-1][0] + 90_000: return None
    i = bisect_right(stamps[a], ms) - 1
    return s[i][1] if i >= 0 else None

def vol_per_sqrt_min(series, asset):
    pts = [c for _, c in series.get(asset, [])][-240:]
    if len(pts) < 30: return None
    rets = [math.log(pts[i + 1] / pts[i]) for i in range(len(pts) - 1)]
    mu = statistics.fmean(rets)
    return math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1))

def W(d, sigma): return math.exp(-(d * d) / (2 * sigma * sigma))

def pin_info(m, series, stamps):
    o = rail_at(series, stamps, m["asset"], m["start"] * 1000)
    sl = rail_at(series, stamps, m["asset"], m["expiry"] * 1000)
    if o is None or sl is None or o == 0: return None
    pn = m.get("payoutNumerators")
    chain_up = (pn[0] >= pn[1]) if pn and len(pn) == 2 else m.get("winningOutcome") == 0
    up = sl >= o
    if up != chain_up: return None
    v = vol_per_sqrt_min(series, m["asset"])
    if not v: return None
    tau_min = max(1.0, (m["expiry"] - m["start"]) / 60.0)
    return {"winner_up": up, "z": abs(math.log(sl / o)) / (v * math.sqrt(tau_min)), "open": o, "settle": sl}

def simulate(mk, snaps, m, series, stamps, *, sigma=0.005, d=None, kill_k=0.7,
             quote_q=QUOTE_Q, max_inv=200.0, flatten_s=60.0, requote_tick=1.5, skew_gamma=0.0):
    """one window replay; d in prob units (None => naive 2c). returns decomposition or None."""
    span = (snaps[-1]["t"] - snaps[0]["t"]) / 1000
    if span < 120 or len(snaps) < 600: return None
    vol = vol_per_sqrt_min(series, m["asset"])
    pi = pin_info(m, series, stamps)
    if vol is None or pi is None: return None
    line = pi["open"]
    end_ms = m["expiry"] * 1000
    ts = [s["t"] for s in snaps]
    d = 0.02 if d is None else d

    bid = pno = None                      # resting: BUY YES @ bid ; BUY NO @ pno
    qy = qn = 0.0; cash = 0.0
    score_self = score_rival = 0.0
    adverse = 0.0; fills = 0; killed = 0.0
    adverse_ok = adverse_no = 0.0         # by leg (diagnostics)
    fy = fn = 0

    def mid_of(s):
        return (s["bids"][0][0] + s["asks"][0][0]) / 2 if s["bids"] and s["asks"] else None

    def mark30(i, asset_mid_fn):
        j = min(max(bisect_right(ts, snaps[i]["t"] + 30_000) - 1, i + 1), len(snaps) - 1)
        return asset_mid_fn(snaps[j])

    for i in range(len(snaps) - 1):
        s = snaps[i]; t = s["t"]; dt = (snaps[i + 1]["t"] - t) / 1000
        mid = mid_of(s)
        if mid is None:
            bid = pno = None
            continue
        inv_imb = qy - qn                 # >0 too much YES -> shade quotes down (sell-side pressure)
        shift = -skew_gamma * inv_imb * TICK if skew_gamma else 0.0
        px_now = rail_at(series, stamps, m["asset"], t)
        tau_min = max(0.05, (end_ms - t) / 60000.0)
        # hazard = P(window settles within +-eps of its line) — a terminal-density
        # statement: p = Phi((r+e)/s) - Phi((r-e)/s), r = ln(px/line), s = vol*sqrt(tau_rem).
        # Wide band early in LONG windows is fine (p is tiny); a 5m window parked at its
        # line is pinned from second one (p ~ 30%). One formula, no per-cadence hacks.
        r_now = math.log(px_now / line) if px_now else None
        s_now = vol * math.sqrt(tau_min)
        EPS_BPS = 0.001
        p_pin = None
        if r_now is not None and s_now > 0:
            N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
            p_pin = N((r_now + EPS_BPS) / s_now) - N((r_now - EPS_BPS) / s_now)
        # kill_k is a pin-PROBABILITY threshold; 0 (or less) disables the kill entirely
        near = p_pin is not None and kill_k > 0 and p_pin > kill_k

        # flatten leg before settle
        if (end_ms - t) / 1000 < flatten_s:
            if qy > 0: cash += s["bids"][0][0] * qy; qy = 0.0
            if qn > 0: cash += (1 - s["asks"][0][0]) * qn; qn = 0.0
            bid = pno = None
            for lv, qty in s["bids"]:
                if qty: score_rival += qty * W(abs(lv - mid), sigma) * dt
            continue

        if kill_k > 0 and near:
            bid = pno = None; killed += dt
        else:
            nb = mid - d + shift
            np_ = (1 - mid) - d - shift          # mirror: NO bid at (1-mid)-d
            if bid is None or abs(bid - nb) > requote_tick * TICK:
                bid, pno = nb, np_

        # accrue scores
        for lv, qty in s["bids"]:
            if qty: score_rival += qty * W(abs(lv - mid), sigma) * dt
        for lv, qty in s["asks"]:
            if qty: score_rival += qty * W(abs(lv - mid), sigma) * dt
        if bid is not None and qy < max_inv:
            score_self += min(quote_q, max_inv - qy) * W(abs(bid - mid), sigma) * dt
        if pno is not None and qn < max_inv:
            score_self += min(quote_q, max_inv - qn) * W(abs(pno - (1 - mid)), sigma) * dt

        # fills on next snap
        nx = snaps[i + 1]
        if bid is not None and nx["asks"] and qy < max_inv:
            nba = nx["asks"][0][0]
            if nba <= bid + 1e-12:
                pay = min(nba, bid); qty_take = min(quote_q, max_inv - qy)
                cash -= pay * qty_take; qy += qty_take; fills += 1; fy += 1
                m2 = mark30(i, mid_of)
                adv = max(0.0, (pay - m2)) * qty_take if m2 is not None else 0.0
                adverse += adv; adverse_ok += adv
                bid = None
        if pno is not None and nx["bids"] and nx["asks"] and qn < max_inv:
            nbb = nx["bids"][0][0]
            xe = 1 - pno                      # YES-equivalent of our NO bid
            if nbb >= xe - 1e-12 and nbb < nx["asks"][0][0]:
                pay = max(pno, 1 - nbb); qty_take = min(quote_q, max_inv - qn)
                cash -= pay * qty_take; qn += qty_take; fills += 1; fn += 1
                m2 = mark30(i, mid_of)
                adv = max(0.0, (pay - (1 - m2))) * qty_take if m2 is not None else 0.0
                adverse += adv; adverse_no += adv
                pno = None

    win_up = pi["winner_up"]
    term = cash + (qy if win_up else 0.0) + (qn if not win_up else 0.0)
    tot = score_self + score_rival
    return {"marketId": mk[-6:], "asset": m["asset"], "span_s": round(span),
            "pnl": round(term, 3), "adverse": round(adverse, 3),
            "adv_y": round(adverse_ok, 3), "adv_n": round(adverse_no, 3),
            "fills_y": fy, "fills_n": fn,
            "score_share": round(score_self / tot, 4) if tot else 0,
            "killed_frac": round(killed / span, 3), "z": round(pi["z"], 2)}
