// One-time historical backfill: all Finalized markets on the DreamDEX EC venue
// for the last N days, with per-market scoped fills. Resumable via state file.
import { SomniaMarkets } from "@somnia-chain/markets-sdk";
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
});
const cl = ex.client as any;
const log = (s: string) => { console.log(`[${new Date().toISOString()}] ${s}`); appendFileSync(join(DATA, "backfill.log"), `[${new Date().toISOString()}] ${s}\n`); };

const DONE_FILE = join(DATA, "backfill_done.txt");
const done: Set<string> = new Set(existsSync(DONE_FILE) ? readFileSync(DONE_FILE, "utf8").split("\n").filter(Boolean) : []);
const out = createWriteStream(join(DATA, "history.jsonl"), { flags: "a" });

/** retry with backoff — the testnet indexer throws HTTP 503/aborted timeouts under load */
async function retry<T>(fn: () => Promise<T>, tries = 10, baseMs = 8000): Promise<T> {
  for (let i = 0; ; i++) {
    try { return await fn(); }
    catch (e: any) {
      if (i >= tries - 1) throw e;
      const wait = baseMs * (i + 1);
      log(`retry ${i + 1}/${tries} in ${wait / 1000}s: ${String(e?.message ?? e).slice(0, 100)}`);
      await new Promise((r) => setTimeout(r, wait));
    }
  }
}

const WINDOW_DAYS = Number(process.argv[2] ?? 5);
const cutoff = Math.floor(Date.now() / 1000) - WINDOW_DAYS * 86400;

// statuses the indexer uses; sweep each
for (const status of ["Finalized", "Voided"]) {
  let offset = 0, total = 0;
  while (true) {
    const rows = await retry(() => cl.listBinaryMarkets({ venueId: VENUE_ID, status, limit: 100, offset }));
    if (!rows.length) break;
    for (const m of rows) {
      if (Number(m.resolvedAtTimestamp ?? m.expiry) < cutoff) { log(`${status}: older than window at offset ${offset}, stopping`); offset = -1; break; }
      if (done.has(m.marketId)) continue;
      const rec: any = {
        marketId: m.marketId, pool: m.poolAddress, asset: m.asset,
        start: Number(m.tradingStart), expiry: Number(m.expiry), resolvedAt: Number(m.resolvedAtTimestamp),
        tradeCount: Number(m.tradeCount), quoteVol: Number(m.cumulativeQuoteVolume),
        winningOutcome: m.winningOutcome, voided: m.voided, intervalSec: Number(m.intervalSec),
        lastPrice: m.lastPrice, strike: m.strike, oq: m.oracleQuestionId, status: m.status,
      };
      if (rec.tradeCount > 0) {
        try {
          const fr = await retry(() => cl.getFills(m.poolAddress, { since: rec.start - 60, until: rec.resolvedAt + 120, limit: 2000 }));
          rec.fills = fr.filter((f: any) => f.market === m.marketId).map((f: any) => ({
            p: f.fillPrice, q: f.quantity, side: f.makerSide, kind: f.kind,
            t: Number(f.timestamp), mk: f.maker?.slice(0, 10),
          }));
          if (rec.fills.length !== rec.tradeCount) rec.fillsMismatch = `${rec.fills.length}/${rec.tradeCount}`;
        } catch (e: any) { rec.fillsErr = String(e?.message ?? e).slice(0, 140); }
      } else rec.fills = [];
      out.write(JSON.stringify(rec) + "\n");
      done.add(m.marketId); writeFileSync(DONE_FILE, [...done].join("\n") + "\n");
      total++;
    }
    if (offset === -1) break;
    offset += rows.length;
    if (rows.length < 100) break;
    await new Promise((r) => setTimeout(r, 250));
  }
  log(`${status}: recorded ${total} markets`);
}
log("backfill complete");
process.exit(0);
