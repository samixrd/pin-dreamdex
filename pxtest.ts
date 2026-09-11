import { SomniaMarkets, SOMNIA_TESTNET_PRICE_FEED } from "@somnia-chain/markets-sdk";
import { somniaShannon } from "@somnia-chain/markets-sdk/chains";
const ex = new SomniaMarkets({
  indexerUrl: "https://dev.smk.somnia.host/v1/graphql",
  chain: somniaShannon,
  wsRpcUrl: "wss://api.infra.testnet.somnia.network/ws",
  addresses: { binaryModule: "0x3ecC694Cef705358864a646142ac17A90E29e388" } as any,
  priceFeed: SOMNIA_TESTNET_PRICE_FEED,
});
try {
  const p: any = await Promise.race([
    ex.fetchPrice("BTC"),
    new Promise((_, rj) => setTimeout(() => rj(new Error("timeout")), 15000)),
  ]);
  console.log("fetchPrice:", JSON.stringify(p));
} catch (e) { console.log("fetchPrice ERR:", String(e).slice(0, 300)); }
try {
  const o: any = await Promise.race([
    ex.fetchPriceOHLCV("BTC", "1m", undefined, 3),
    new Promise((_, rj) => setTimeout(() => rj(new Error("timeout")), 15000)),
  ]);
  console.log("ohlcv:", JSON.stringify(o));
} catch (e) { console.log("ohlcv ERR:", String(e).slice(0, 300)); }
process.exit(0);
