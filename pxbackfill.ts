// Deep OHLCV backfill: BTC/ETH 1m candles as far back as the feed goes.
import { SomniaMarkets, SOMNIA_TESTNET_PRICE_FEED } from "@somnia-chain/markets-sdk";
import { somniaShannon } from "@somnia-chain/markets-sdk/chains";
import { createWriteStream, existsSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const __dirname = dirname(fileURLToPath(import.meta.url));
const DATA = join(__dirname, "data"); mkdirSync(DATA, { recursive: true });

const ex = new SomniaMarkets({
  indexerUrl: "https://dev.smk.somnia.host/v1/graphql",
  chain: somniaShannon,
  wsRpcUrl: "wss://api.infra.testnet.somnia.network/ws",
  addresses: { binaryModule: "0x3ecC694Cef705358864a646142ac17A90E29e388" } as any,
  priceFeed: SOMNIA_TESTNET_PRICE_FEED,
});
const out = createWriteStream(join(DATA, "px_history.jsonl"), { flags: "a" });

// resume: last bucket per asset
const last = { BTC: 0, ETH: 0 };
if (existsSync(join(DATA, "px_history.jsonl")))
  for (const l of readFileSync(join(DATA, "px_history.jsonl"), "utf8").split("\n").filter(Boolean)) {
    const r = JSON.parse(l); if (r.t > last[r.asset]) last[r.asset] = r.t;
  }
console.log("resume from:", new Date(last.BTC).toISOString(), new Date(last.ETH).toISOString());

for (const asset of ["BTC", "ETH"]) {
  let cursor = last[asset] || (Math.floor(Date.now() / 1000) - 7 * 86400) * 1000;
  const endTs = Math.floor(Date.now() / 1000) * 1000;
  while (cursor < endTs) {
    let rows: any;
    try { rows = await ex.fetchPriceOHLCV(asset, "1m", cursor, 500); }
    catch (e) { console.log("err", String(e).slice(0, 120)); break; }
    if (!rows?.length) break;
    let maxT = cursor;
    for (const [t, o, h, l, c, n] of rows) {
      if (t > maxT) maxT = t;
      out.write(JSON.stringify({ t, src: "1m", asset, o, h, l, c, n }) + "\n");
    }
    if (maxT <= cursor) break;
    cursor = maxT;
    process.stdout.write(`\r${asset} up to ${new Date(cursor).toISOString()}   `);
    if (rows.length < 500) break;
    await new Promise((r) => setTimeout(r, 150));
  }
  console.log(`\n${asset}: done at ${new Date(cursor).toISOString()}`);
}
process.exit(0);
