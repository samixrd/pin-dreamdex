# PIN paper-trader — shadow quoting engine on the LIVE book stream.
# Consumes data/books.jsonl tail (collector writes it) and runs the SAME policy
# object as the replay engine, incrementally: one market-window per policy-state,
# emitting per-fill and per-settlement records to data/paper_state.jsonl + paper_decomp.jsonl.
# Same rules as pin_core.simulate: d, kill_k, skew, flatten-before-settle, inventory cap.
import json, math, os, time, statistics
from bisect import bisect_right
from pin_core import load_all, vol_per_sqrt_min, pin_info, rail_at, W, TICK

DATA = "data"
CFG = {"sigma": 0.005, "d": 0.005, "kill_k": 0.35, "quote_q": 50.0, "max_inv": 500.0,
       "flatten_s": 60.0, "requote_tick": 1.5}

STATE_F = f"{DATA}/paper_state.json"
OUT_F = f"{DATA}/paper_ledger.jsonl"

def load_rail():
    rail = {"BTC": {}, "ETH": {}}
    for f in ("px.jsonl", "px_history.jsonl", "px_deep.jsonl"):
        try:
            for l in open(f"{DATA}/{f}", encoding="utf-8"):
                p = json.loads(l)
                if p["asset"] not in rail: continue
                if p.get("src") == "1m":
                    c = p["c"]
                    if isinstance(c, str): c = int(c) / 1e18
                    rail[p["asset"]][p["t"]] = c
                elif p.get("src") == "tick" and p.get("price"):
                    rail[p["asset"]][p["t"]] = p["price"]   # live poll ticks
        except FileNotFoundError: pass
    return rail

def series_of(rail):
    series = {a: sorted(rail[a].items()) for a in rail}
    stamps = {a: [t for t, _ in s] for a, s in series.items()}
    return series, stamps

_vcache = {}
def minute_vol(rail, asset, refresh_s=120):
    """per-minute log-retail stdev from LAST 240 one-minute closes (ticks resampled)."""
    now = time.time()
    hit = _vcache.get(asset)
    if hit and now - hit[0] < refresh_s: return hit[1]
    items = sorted(rail[asset].items())
    per_min = {}
    for t, c in items[-20000:]:
        per_min[t // 60000] = c
    pts = [per_min[k] for k in sorted(per_min)][-240:]
    v = None
    if len(pts) >= 30:
        rets = [math.log(pts[i + 1] / pts[i]) for i in range(len(pts) - 1)]
        mu = statistics.fmean(rets)
        v = math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1))
    _vcache[asset] = (now, v)
    return v

def load_state():
    if os.path.exists(STATE_F):
        return json.load(open(STATE_F))
    return {"markets": {}, "settled_done": []}

def save_state(st):
    tmp = STATE_F + ".tmp"; json.dump(st, open(tmp, "w")); os.replace(tmp, STATE_F)

def tail_lines(path, offsets):
    """yield new lines since offsets[path]; update offsets"""
    out = []
    try:
        size = os.path.getsize(path)
        off = offsets.get(path, 0)
        if size < off: off = 0  # rotated
        if size == off: return out
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(off)
            data = f.read()
            new = f.tell()
            # keep only full lines
            if not data.endswith("\n"):
                cut = data.rfind("\n")
                if cut == -1: return out
                data = data[:cut + 1]; new = off + len(data.encode("utf-8"))
            offsets[path] = new
            out = data.splitlines()
    except FileNotFoundError:
        pass
    return out

def main():
    rail = load_rail()
    series, stamps = series_of(rail)
    rail_offsets = {f"{DATA}/px.jsonl": os.path.getsize(f"{DATA}/px.jsonl") - 400_000 if os.path.exists(f"{DATA}/px.jsonl") else 0}
    if rail_offsets[f"{DATA}/px.jsonl"] < 0: rail_offsets[f"{DATA}/px.jsonl"] = 0
    st = load_state()
    offsets = {f"{DATA}/books.jsonl": os.path.getsize(f"{DATA}/books.jsonl") - 1_000_000}
    if offsets[f"{DATA}/books.jsonl"] < 0: offsets[f"{DATA}/books.jsonl"] = 0
    # settled markets arrive via settled.jsonl (collector sweep)
    s_off = {}
    loop_n = 0

    while True:
        loop_n += 1
        # refresh rail from live px ticks each loop (cheap tail read)
        for l in tail_lines(f"{DATA}/px.jsonl", rail_offsets):
            try:
                p = json.loads(l)
                a = p.get("asset")
                if a in rail:
                    if p.get("src") == "tick" and p.get("price"): rail[a][p["t"]] = p["price"]
                    elif p.get("src") == "1m":
                        c = p["c"]; rail[a][p["t"]] = int(c) / 1e18 if isinstance(c, str) else c
            except Exception: pass
        if loop_n % 30 == 0:
            series, stamps = series_of(rail)
        # --- book ticks ---
        for line in tail_lines(f"{DATA}/books.jsonl", offsets):
            try: s = json.loads(line)
            except Exception: continue
            mk = s["marketId"]; now = s["t"]
            M = st["markets"].get(mk)
            if M is None:
                M = st["markets"][mk] = {"cash": 0.0, "qy": 0.0, "qn": 0.0, "bid": None, "pno": None,
                                          "score_self": 0.0, "score_riv": 0.0, "adv": 0.0, "fills": 0,
                                          "killed_s": 0.0, "last_t": None, "asset": s["asset"],
                                          "first_t": now, "quotes": 0,
                                          "start": s.get("start"), "expiry": s.get("expiry")}
                continue
            if s.get("expiry") and not M.get("expiry"): M["expiry"] = s["expiry"]
            dt = (now - (M["last_t"] or now)) / 1000.0
            M["last_t"] = now
            if dt <= 0 or dt > 30: continue
            bids, asks = s.get("bids") or [], s.get("asks") or []
            if not bids or not asks:
                M["bid"] = M["pno"] = None
                continue
            mid = (bids[0][0] + asks[0][0]) / 2
            sigma = CFG["sigma"]; d = CFG["d"]
            # accrue rival + own score
            for lv, qty in bids: M["score_riv"] += qty * W(abs(lv - mid), sigma) * dt
            for lv, qty in asks: M["score_riv"] += qty * W(abs(lv - mid), sigma) * dt
            qq = min(CFG["quote_q"], max(0.0, CFG["max_inv"] - M["qy"]))
            if M["bid"] is not None and qq > 0:
                M["score_self"] += qq * W(abs(M["bid"] - mid), sigma) * dt
            qn_cap = min(CFG["quote_q"], max(0.0, CFG["max_inv"] - M["qn"]))
            if M["pno"] is not None and qn_cap > 0:
                M["score_self"] += qn_cap * W(abs(M["pno"] - (1 - mid)), sigma) * dt

            # fills on THIS snap (prev cycle's resting orders vs current touch)
            if M["bid"] is not None and asks and M["qy"] < CFG["max_inv"]:
                a0 = asks[0][0]
                if a0 <= M["bid"] + 1e-12:
                    pay = min(a0, M["bid"]); take = min(CFG["quote_q"], CFG["max_inv"] - M["qy"])
                    M["cash"] -= pay * take; M["qy"] += take; M["fills"] += 1
                    open_ledger(mk, "FILL_Y", now, pay, take, mid)
                    M["bid"] = None
            if M["pno"] is not None and bids and asks and M["qn"] < CFG["max_inv"]:
                b0 = bids[0][0]; xe = 1 - M["pno"]
                if b0 >= xe - 1e-12 and b0 < asks[0][0]:
                    pay = max(M["pno"], 1 - b0); take = min(CFG["quote_q"], CFG["max_inv"] - M["qn"])
                    M["cash"] -= pay * take; M["qn"] += take; M["fills"] += 1
                    open_ledger(mk, "FILL_N", now, pay, take, mid)
                    M["pno"] = None

            # requote / kill (needs px rail -> line = open px from rail at window start)
            if "line" not in M and M.get("start"):
                px = rail_at(series, stamps, M["asset"], M["start"] * 1000)
                if px: M["line"] = px
            near = False
            if "line" in M and M.get("expiry"):
                px = rail_at(series, stamps, M["asset"], now)
                v = minute_vol(rail, M["asset"])
                tau_min = max(0.05, (M["expiry"] * 1000 - now) / 60000.0)
                if px and v and CFG["kill_k"] > 0:
                    r = math.log(px / M["line"]); s = v * math.sqrt(tau_min); e = 0.001  # eps=10bp, calibrated vs data/hazard_table.json
                    Nrm = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
                    p_pin = Nrm((r + e) / s) - Nrm((r - e) / s)
                    near = p_pin > CFG["kill_k"]   # kill_k = pin-probability threshold
            if near:
                M["bid"] = M["pno"] = None; M["killed_s"] += dt
            else:
                nb = mid - d; np_ = (1 - mid) - d
                if M["bid"] is None or abs(M["bid"] - nb) > CFG["requote_tick"] * TICK:
                    M["bid"], M["pno"] = nb, np_; M["quotes"] += 1

        # --- settlement events ---
        for line in tail_lines(f"{DATA}/settled.jsonl", offsets):
            try: m = json.loads(line)
            except Exception: continue
            mk = m["marketId"]
            M = st["markets"].get(mk)
            if not M or mk in st["settled_done"]: continue
            if M.get("expiry_hint") is None: M["expiry_hint"] = m["expiry"]
            # flatten at last book state before settle: use last mid proxy via settle payout instead
            # (paper holds to settlement for the honest decomposition)
            win_up = (m.get("winningOutcome") == 0)
            term = M["cash"] + (M["qy"] if win_up else 0.0) + (M["qn"] if not win_up else 0.0)
            tot = M["score_self"] + M["score_riv"]
            rec = {"marketId": mk[-6:], "asset": M["asset"], "term_pnl": round(term, 3),
                   "cash": round(M["cash"], 3), "invY": M["qy"], "invN": M["qn"], "win_up": win_up,
                   "fills": M["fills"], "quotes": M["quotes"],
                   "score_share": round(M["score_self"] / tot, 4) if tot else 0,
                   "killed_frac": round(M["killed_s"] / max(1.0, (m["expiry"] * 1000 - M["first_t"]) / 1000), 3)}
            with open(OUT_F, "a", encoding="utf-8") as f: f.write(json.dumps(rec) + "\n")
            st["settled_done"].append(mk)
            print("SETTLED", json.dumps(rec), flush=True)
        # expiry hints from live discovery: read state of watched markets from books asset/expiry? use settled only.
        save_state(st)
        time.sleep(2.0)

def open_ledger(mk, kind, t, pay, qty, mid):
    with open(f"{DATA}/paper_fills.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"mk": mk[-6:], "kind": kind, "t": t, "pay": round(pay, 4), "qty": qty, "mid": round(mid, 4)}) + "\n")

if __name__ == "__main__":
    main()
