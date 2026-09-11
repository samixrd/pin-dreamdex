# SDK & Docs Feedback — PIN (Somnia × DreamDEX Event Contracts hackathon)

Every item below was hit in real testing on Shannon testnet (chain 50312), markets-sdk 0.28–0.30.
Ordered by how much time each cost us.

## 1. `getFills` `since`/`until` unit is undocumented and silently wrong
`FillsOptions.since/until` accept **unix seconds**. Passing milliseconds (the natural choice,
since every SDK row timestamps in seconds *or* ms depending on the table — `Fill.timestamp` is
seconds, `UnifiedTrade.timestamp` is ms) yields an empty result set with **no error**. Our
settlement recorder silently saved `fills: []` for ~40 markets before we caught it in a
row-count cross-check against `tradeCount`.
**Suggest:** seconds documented explicitly in the `getFills` JSDoc + reject/normalize ms-scale
values (> 1e11) with a warning.

## 2. Testnet indexer availability under load
`dev.smk.somnia.host/v1/graphql` intermittently returns HTTP 503, non-JSON bodies, or aborts
long queries (`listBinaryMarkets` limit≥100 with offsets, `listLiveBinaryMarkets`) under
sustained polling — three of our five services died on this in one evening. The gotchas page
covers indexer *lag* but not *failure modes*; retry/backoff is on the builder.
**Suggest:** a short "indexer reliability & recommended polling budget" section; the SDK could
retry idempotent GraphQL reads internally (they're safe).

## 3. Price feed candle endpoint caps pages at 5000 — silently
`fetchPriceOHLCV(limit: 10000)` returns 5000 rows and `len(rows) < limit` looks like "history
end". Our first deep-rail backfill stopped 48 days short because of this and we nearly shipped
a "venue only has 3 days of history" claim. GraphQL `Candle` caps identically.
**Suggest:** document the cap; have the unified verb page internally or throw when
`len == cap`.

## 4. `UnifiedOrderBook` bids/asks: prices already human-units, but binary venue decimals differ
spot 6/8/18-dp vs binary 6-dp collateral — the docs' "derive decimals from `collateral`" advice
is right, but binary market rows carry no `tickSize`/`lotSize` (gotchas #6 mentions lot only).
We hard-scoped a 1e-6 price grid from observation. **Suggest:** expose binary pool tick/lot in
`getBinaryPoolParams` consumers or the unified market row.

## 5. `watchOrderBook` on a market that just rolled off `loadMarkets` throws
`unknown symbol … call loadMarkets() first` — technically correct, but the *action* is to stop
watching, and nothing in the error says the market finalized. Our book loops hot-looped this
error until we string-matched it. **Suggest:** a dedicated error class or a `marketGone` flag.

## 6. Docs quality (positive, for the record)
The Event Contracts docs pages (market-structure, gotchas, yield-algorithm) are the best part of
the stack — "pools are recycled, key by marketId" and "no early-cancel penalty on yield score"
both changed our design before they cost us. The `?ask=` GitBook endpoint answered σ-visibility
accurately (it admitted σ is not queryable, which *is* our project's premise).
