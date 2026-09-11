# PIN — 2:30 demo video script

Format: screen recording, no voice needed (captions + terminal typing ASMR). 1080p, dark theme, zoom 1.25x.

## 0:00–0:15 Cold open — the venue's dirty secret
Terminal, run:
```
python -c "import json; print(json.dumps(json.load(open('data/published/venue_anatomy.json')), indent=1))"
```
Caption: "364 markets recorded on DreamDEX Event Contracts. One maker takes 100% of the volume on a median market. Half of all fills create the pair themselves — there are no sellers."

## 0:15–0:40 The mechanic nobody models
Show docs.dreamdex.io/trading/common/yield-algorithm (scroll to the Gaussian), then
`strategies/yield-optimizer/README.md` from dreamdex-bot-kit.
Caption: "dreamDEX pays makers per second: score = qty × exp(−d²/2σ²) × time. No early-cancel penalty. σ is set on-chain and published nowhere — the official kit makes you GUESS it (YO_SIGMA_RAW). 80 hackathon projects: zero mention."

## 0:40–1:10 Our data rack
`ls -la data/` then one-liner counters from venue_anatomy (5.4M book snapshots, 156k candles 52d).
Open `data/dashboard.html` → "Empirical pin hazard" section.
Caption: "We recorded the venue for 18 hours: 5.4M order-book snapshots, every settled window's fills with maker addresses, 52 days of oracle price rail. 67% of windows finish within 1σ of their opening line. Pin risk is the modal outcome."

## 1:10–1:35 σ from public data
Run `python sigma_est.py` (fast section: the spacing histogram + markout curve).
Caption: "The incumbent ladder rests 1–2.25¢ off mid. Under the venue's own e^-½ convention that brackets σ ∈ [0.005, 0.0225]. 2,170 reconstructed maker fills show three regimes: touch pays adverse, 1–2¢ earns it, 3¢+ turns toxic. We know the band the incumbents are optimizing against — they don't publish it."

## 1:35–2:00 The frontier + live money
`cat data/sweep_final.json | python -m json.tool | head` → point at top line vs naive line.
Caption: "Same venue, same size, same risk posture: touch+kill = +81 mean / −10.5 worst per window. Naive 2¢ maker = +20 / −56. And the kill rule: it fires on empirical P(pin), not textbook math."
Then `tail -f data/live_runner.out` (live, mid-run): "KILL: pin-hazard — pulling quotes" / "FILL detected: NO 5@0.012" / "redeemed → 0x…".
Caption: "This is running with real orders on Shannon testnet. Every claim in this video has a tx hash."
Show `data/published/live_ledger.json` grep a few tx fields + one explorer link on screen.

## 2:00–2:25 The dashboard, honestly
Scroll dashboard.html money ledger section — including the negative rows.
Caption: "Window #1 lost 208 paper tUSDC — stale price rail disarmed the kill. Root-caused, fixed, on the ledger. We publish the decomposition, not the highlight reel: spread + yield share − adverse selection − pin."

## 2:25–2:30 Close
Black screen, one line:
"PIN — quote geometry from the venue's own formula. Kill rule from the venue's own settle history. Claims from the chain. github.com/samixrd/pin-dreamdex"

---
### Recording checklist (morning)
- [ ] sweep_final done → README numbers refreshed & pushed
- [ ] live_ledger has ≥5 windows settled (claims + redeems) — if <5, record anyway with what's there
- [ ] dashboard.html regenerated <5 min before recording
- [ ] terminal font ≥16pt; explorer tab pre-opened for one tx hash
- [ ] record sections 1:10+1:35 with the ACTUAL running processes (authenticity)
