# PIN — Yield-Aware Convergence Market Making on DreamDEX Event Contracts

**The venue pays makers to rest liquidity and never publishes the rulebook's key parameter.**
dreamDEX distributes collateral yield to resting orders by
`score = qty × exp(−(P−mid)²/2σ²) × seconds` (docs: Collateral Yield Algorithm). σ is set
per market on-chain and is **not exposed by any API or SDK** — the official bot-kit requires
operators to hand-set `YO_SIGMA_RAW`. 80 hackathon projects traded this venue; none mentions
this mechanic. PIN is the first market maker whose objective function contains it.

**Live monitor:** https://samixrd.github.io/pin-dreamdex/ (auto-regenerates from the running
stack every 90 s — tx hashes link straight to the Shannon explorer)

```
fund → mint-a-pair two-sided bids at d from mid → accrue yield score per second (W-banded)
     → pin-hazard kill (empirically calibrated) → flatten before settle → redeem → decompose
```

## What PIN is

A zero-inventory, two-sided maker for DreamDEX Event Contracts (binary Up/Down price windows
on Somnia) that:

1. **Quotes geometry from the venue's own yield formula.** Resting distance is chosen against
   the Gaussian weight band, not a fixed spread. Measured on recorded books: at the incumbent
   ladder's quote size, touch-adjacent quoting captures **22–88% of the book's total yield
   score** (band-dependent) vs **0.1–19%** for the standard ±2¢ maker — a 300× gap at narrow σ,
   still 1.5×+ and $-positive at the band the incumbents' own geometry implies.
2. **Carries a kill rule calibrated on the venue's settle distribution, not textbook BM.**
   From 52 days / 146k-candle rail over 100+ validated windows: **67% of windows finish
   within 1σ of their opening line** — pin risk is the modal outcome. The guard fires on
   P(settle within 10bp of line) > 0.35, computed from an empirical hazard table learned
   from the venue's own settlements (`data/hazard_table.json`).
3. **Publishes the decomposition, not a PnL number.** Every window settles into
   spread captured + yield score share − adverse selection (30s markout per fill) − pin
   losses, live on the dashboard. Losses included. Window #1 lost −208.5 paper tUSDC and the
   post-mortem (stale price rail disarming the kill) is in the ledger.

## Evidence, all measured on Shannon testnet (chain 50312)

| Claim | Source |
|---|---|
| 20.3% of 364 recorded markets never traded; of 261 five-minute windows, 23% died | `data/published/venue_anatomy.json` |
| Median traded market has **one maker taking 100% of maker volume**; 49% of fills are mint-a-pair (no sellers exist) | per-market fill ladders w/ maker addresses |
| Oracle resolves outcomes that public 1-min feeds **cannot reproduce**: 100% agreement ≥25bp from the line, 64% at 5–10bp, 36% <2bp | `analyze3.py`, 136-window test |
| Adverse selection has **3 regimes**: touch pays −1.5¢ markout, 1–2¢ band *earns* +1.8¢ (trend flow), ≥3¢ turns toxic (33–47% loss tails) | 2,170 reconstructed maker fills |
| σ bracketed from public data: incumbent ladder at 1–2.25¢ ⇒ σ ∈ [0.005, 0.0225] under the ops e^−½ convention — the estimator is our own | `sigma_est.py` |
| Policy frontier (q200): **touch + hazard-kill(0.6) = +136.7 mean, worst window 0.0, 81.5% yield share** (σ=0.005) vs naive-2¢ **+46.8, worst −56.4, 0.2%** | `sweep_final.py`, `data/published/sweep_final.json` |
| Empirical pin hazard: P(settle ≤10bp from line) = 47–59% right after open, dropping to 3% once 2bp√min of escape — the kill rule is *calibrated on this table*, not on textbook BM | `data/published/hazard_table.json` |
| Live money: 339 ledger events — orders placed, filled (incl. NO at 0.012 during a crash-through), flattened, merged, redeemed, all with tx hashes on Shannon | `data/published/live_ledger.json` |

## Layout

```
collector.ts    read-only recorder: books (5-level, ~2s), fills, settlements, px marks
backfill.ts     historical market+fill sweep (resumable, indexer-503-hardened)
pxdeep.py       52-day oracle price feed dump (1m candles, close + EMA mark, raw precision)
pin_core.py     replay engine: order lifecycle, mint-a-pair fills, yield-score race, markout
sweep2/3/sigma  policy grids: distance × kill × σ band × quote size
hazard.py       empirical P(pin | normalized state) table from venue settlements
sigma_est.py    band inference from ladder geometry + adverse curve
paper.py        live shadow trader on the collector's stream (same policy objects)
live.ts         real-money runner: on-chain status gate, post-only bids, expire-ts dead-man,
                hazard kill, pre-settle flatten, redeem + claim sweep; caps: 60/window, 200 total
dashboard.py    regenerates data/dashboard.html from the ledgers (zero synthetic data)
```

## Run

```bash
npm i                                            # markets-sdk ^0.30, viem
cp .env.example .env                             # PIN_KEY_FILE=wallet-with-shannon-stt
npx tsx collector.ts                             # record books/fills/settlements
python pxdeep.py                                 # 52-day price rail
npx tsx backfill.ts 30                           # settled markets + maker fills
python pin_core.py && python sweep2.py           # replay frontier
python hazard.py                                 # calibrate the kill
LIVE_DRY=1 npx tsx live.ts                       # policy dry run
LIVE_DRY=0 npx tsx live.ts                       # real windows, hard caps
python dashboard.py                              # publish the decomposition
```

Testnet tUSDC is self-serve: public `faucet(uint256)` on the token, 10k/call (no Telegram needed).

## Feedback report

See `FEEDBACK.md` — five verified SDK/docs traps we hit building this (all reproducible).

MIT. Data and receipts are the product; fork the engine, not the claims.
