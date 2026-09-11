// PIN collector — read-only recorder for DreamDEX EC markets on Shannon testnet (chain 50312).
// Append-only JSONL under ./data:
//   books.jsonl   — order-book snapshots per live market (live-store watch, zero RTT per tick)
//   fills.jsonl   — trade tape rows per live market
//   settled.jsonl — one record per newly-Finalized market: full row + scoped fills for THAT marketId
//   px.jsonl      — underlying BTC/ETH oracle mark ticks (the pin-distance ground truth)
// All state keyed by marketId (pools recycle). No signer, no chain writes.
import { SomniaMarkets, SOMNIA_TESTNET_PRICE_FEED } from "@somnia-chain/markets-sdk";
import { somniaShannon } from "@somnia-chain/markets-sdk/chains";
import { createWriteStream, mkdirSync, existsSync, readFileSync, writeFileSync, appendFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const DATA = join(__dirname, "data");
mkdirSync(DATA, { recursive: true });

const VENUE_ID = "0x679795a0195a1b76cdebb7c51d74e058aee92919b8c3389af86ef24535e8a28c";
const CORE = {
  binaryModule: "0x3ecC694Cef705358864a646142ac17A90E29e388",
  marketsCore: "0x2802504314685D89bF6C992CA5a8e7cC78bc0294",
  clobFactory: "0xb2BE8EE02F96379DB75f01802384593EBa9bfF04",
  binaryPoolImpl: "0x82A1FcdaA2daC2fC7D5f9909D43E68021eE966FD",
  binarySettlement: "0xbF4a49e0Dfd092e5FBE8E5761064C49533e6Ed23",
  collateralRouter: "0xbC0C9834B15ACE38bB50dDaa7d7f7C7CC4DC183C",
  marketCreatorFactory: "0xE6bEE93cE87c9E6e62aCb621caa7832EE47b4F6B",
  oracleHub: "0xe40db387cC98601Dd11bd634fF2f3AD5686dE32b",
  collateral: "0x70a86D8842FB63C4Ad2b7cdddF530eBf1BB25d8E",
} as const;

const ex = new SomniaMarkets({
  indexerUrl: "https://dev.smk.somnia.host/v1/graphql",
  chain: somniaShannon,
  wsRpcUrl: "wss://api.infra.testnet.somnia.network/ws",
  addresses: CORE as any,
  priceFeed: SOMNIA_TESTNET_PRICE_FEED,
});
const cl = ex.client as any;

const W = {
  books: createWriteStream(join(DATA, "books.jsonl"), { flags: "a" }),
  fills: createWriteStream(join(DATA, "fills.jsonl"), { flags: "a" }),
  settled: createWriteStream(join(DATA, "settled.jsonl"), { flags: "a" }),
  px: createWriteStream(join(DATA, "px.jsonl"), { flags: "a" }),
};
const log = (s: string) => {
  const l = `[${new Date().toISOString()}] ${s}`;
  appendFileSync(join(DATA, "collector.log"), l + "\n");
  console.log(l);
};

// persisted: markets we've already recorded as settled
const stateFile = join(DATA, "state.json");
const settledSeen: Set<string> = new Set(
  existsSync(stateFile) ? (JSON.parse(readFileSync(stateFile, "utf8")).settled ?? []) : [],
);
const persist = () => writeFileSync(stateFile, JSON.stringify({ settled: [...settledSeen] }));

// ---- market registry: symbol -> marketId/asset/expiry, refreshed from live rows ----
type Live = { marketId: string; symbol: string; asset: string; expiry: number; intervalSec: number; pool: string };
const live = new Map<string, Live>(); // key: symbol

async function discover() {
  const rows = await cl.listLiveBinaryMarkets({ venueId: VENUE_ID, phase: "live" });
  const todo = rows.filter((m: any) => !live.has(`${m.asset}-0-peek`) && ![...live.values()].some((v) => v.marketId === m.marketId));
  if (!todo.length) return;
  const all: any = Object.values(await ex.loadMarkets(true));
  let added = 0;
  for (const m of todo) {
    const row: any = all.find((x: any) => x.info?.marketId === m.marketId);
    const sym = row?.outcomes?.[0]?.symbol;
    if (!sym || live.has(sym)) continue;
    live.set(sym, {
      marketId: m.marketId, symbol: sym, asset: m.asset,
      expiry: Number(m.expiry), intervalSec: Number(m.intervalSec ?? row.info.intervalSec), pool: m.poolAddress,
    });
    loopBook(sym, live.get(sym)!);
    loopTape(sym, live.get(sym)!);
    added++;
  }
  if (added) { log(`discovered ${added} new live markets (total watched ${live.size})`); }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ---- per-market book loop: watchOrderBook returns from the live store ----
function loopBook(sym: string, w: Live) {
  (async () => {
    const cutoff = (w.expiry + 120) * 1000;
    while (Date.now() < cutoff) {
      try {
        const b: any = await Promise.race([
          ex.watchOrderBook(sym, 10),
          sleep(5000).then(() => null),
        ]);
        if (!b) continue;
        W.books.write(JSON.stringify({
          t: Date.now(), marketId: w.marketId, asset: w.asset,
          start: w.expiry - w.intervalSec, expiry: w.expiry,
          bids: b.bids ?? [], asks: b.asks ?? [],
        }) + "\n");
      } catch (e: any) {
        const msg = String(e?.message ?? e);
        if (msg.includes("unknown symbol")) { log(`book loop ended (market off registry) ${sym.slice(0, 34)}`); break; }
        log(`book ${sym.slice(0, 30)} err ${msg.slice(0, 120)}`);
        await sleep(3000);
      }
    }
    log(`book loop done ${sym.slice(0, 34)}`);
  })();
}

// ---- per-market tape loop: dedupe by fill id ----
function loopTape(sym: string, w: Live) {
  (async () => {
    const seen = new Set<string>();
    const cutoff = (w.expiry + 120) * 1000;
    while (Date.now() < cutoff) {
      try {
        const trades: any = await Promise.race([
          ex.watchTrades(sym, 50),
          sleep(5000).then(() => null),
        ]);
        if (!trades?.length) continue;
        for (const tr of trades) {
          const id = `${tr.info?.id ?? tr.id ?? ""}:${tr.timestamp}:${tr.price}:${tr.amount}`;
          if (seen.has(id)) continue;
          seen.add(id);
          W.fills.write(JSON.stringify({ t: Date.now(), marketId: w.marketId, asset: w.asset, sym, tr }) + "\n");
        }
      } catch (e: any) {
        const msg = String(e?.message ?? e);
        if (msg.includes("unknown symbol")) break;
        log(`tape ${sym.slice(0, 30)} err ${msg.slice(0, 120)}`);
        await sleep(3000);
      }
    }
  })();
}

// ---- settlement sweep: newly-Finalized rows + per-marketId scoped fills ----
async function sweepSettled() {
  const rows = await cl.listBinaryMarkets({ venueId: VENUE_ID, status: "Finalized", limit: 60 });
  for (const m of rows) {
    if (settledSeen.has(m.marketId)) continue;
    settledSeen.add(m.marketId);
    const rec: any = {
      marketId: m.marketId, pool: m.poolAddress, asset: m.asset,
      start: Number(m.tradingStart), expiry: Number(m.expiry), resolvedAt: Number(m.resolvedAtTimestamp),
      tradeCount: Number(m.tradeCount), quoteVol: Number(m.cumulativeQuoteVolume),
      winningOutcome: m.winningOutcome, voided: m.voided, intervalSec: Number(m.intervalSec),
      lastPrice: m.lastPrice, strike: m.strike, oq: m.oracleQuestionId,
    };
    try {
      // scoped pull (pool + window in UNIX SECONDS), filter to THIS marketId — pools recycle
      const fr = await cl.getFills(m.poolAddress, {
        since: rec.start - 60, until: rec.resolvedAt + 120, limit: 1000,
      });
      rec.fills = fr.filter((f: any) => f.market === m.marketId).map((f: any) => ({
        p: f.fillPrice, q: f.quantity, side: f.makerSide, kind: f.kind,
        t: Number(f.timestamp), mk: f.maker?.slice(0, 10), tk: f.taker?.slice(0, 10),
      }));
    } catch (e: any) { rec.fillsErr = String(e?.message ?? e).slice(0, 140); }
    try {
      const on: any = await cl.getMarketOnchain(m.marketId as `0x${string}`);
      rec.onchain = { status: on?.status, openingPrice: on?.openingPrice ?? null, settlePrice: on?.settlePrice ?? null };
    } catch (e: any) { rec.onchainErr = String(e?.message ?? e).slice(0, 140); }
    W.settled.write(JSON.stringify(rec) + "\n");
    log(`settled ${m.asset} …${m.marketId.slice(-6)} trades=${rec.tradeCount} fillsSaved=${rec.fills?.length ?? "ERR"}`);
  }
  persist();
}

// ---- underlying price: 1m OHLCV backfill + ~2s poll of live marks ----
async function pxBackfill() {
  for (const asset of ["BTC", "ETH"]) {
    try {
      const rows: any = await withDeadline(ex.fetchPriceOHLCV(asset, "1m", undefined, 500), 30000, "ohlcv");
      if (typeof rows === "string") { log(`px backfill ${asset} ${rows}`); continue; }
      let n = 0;
      for (const [bucket, o, h, l, c, cnt] of rows) {
        W.px.write(JSON.stringify({ t: bucket, src: "1m", asset, o, h, l, c, n: cnt }) + "\n"); n++;
      }
      log(`px backfill ${asset}: ${n} x 1m candles`);
    } catch (e: any) { log(`px backfill ${asset} err ${String(e?.message ?? e).slice(0, 120)}`); }
  }
}
function priceLoop() {
  (async () => {
    await pxBackfill();
    let lastBucket = 0, loopN = 0;
    while (true) {
      for (const asset of ["BTC", "ETH"]) {
        try {
          const p: any = await Promise.race([ex.fetchPrice(asset), sleep(5000).then(() => null)]);
          if (p?.price) W.px.write(JSON.stringify({ t: Date.now(), src: "tick", asset, price: p.price, ema: p.ema ?? null }) + "\n");
        } catch (e: any) { log(`px ${asset} err ${String(e?.message ?? e).slice(0, 100)}`); await sleep(5000); }
      }
      // hourly OHLCV top-up so any missed candles land (dedupe by bucket client-side later)
      const hr = Math.floor(Date.now() / 3_600_000);
      if (hr !== lastBucket) { lastBucket = hr; await pxBackfill(); }
      if (process.env.PX_HB && loopN++ % 60 === 0) log(`px heartbeat ${new Date().toISOString()}`);
      await sleep(2000);
    }
  })();
}

await discover();
await sweepSettled();
priceLoop();
setInterval(() => discover().catch((e) => log(`discover err ${String(e?.message ?? e).slice(0, 140)}`)), 120_000);
setInterval(() => sweepSettled().catch((e) => log(`sweep err ${String(e?.message ?? e).slice(0, 140)}`)), 180_000);
log("collector up");
