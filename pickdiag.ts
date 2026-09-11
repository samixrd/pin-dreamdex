// Diagnostic: why pickWindow finds nothing — replicate each gate with counts.
import { SomniaMarkets, isBinaryMarket, SOMNIA_TESTNET_PRICE_FEED } from "@somnia-chain/markets-sdk";
import { somniaShannon } from "@somnia-chain/markets-sdk/chains";
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
const VENUE_ID = "0x679795a0195a1b76cdebb7c51d74e058aee92919b8c3389af86ef24535e8a28c";
const ex = new SomniaMarkets({
  indexerUrl: "https://dev.smk.somnia.host/v1/graphql",
  chain: somniaShannon, wsRpcUrl: "wss://api.infra.testnet.somnia.network/ws",
  addresses: CORE as any, priceFeed: SOMNIA_TESTNET_PRICE_FEED,
});
const cl = ex.client as any;
const markets = await ex.loadMarkets(true);
const now = Math.floor(Date.now() / 1000);
const counts: any = { total: Object.keys(markets).length, binary: 0, venue: 0, trading_idx: 0, onchain_ok: 0, left_ok: 0, book_ok: 0, mid_ok: 0 };
for (const m of Object.values<any>(markets)) {
  const i = m.info;
  if (!isBinaryMarket(i)) continue; counts.binary++;
  if (i.venueId !== VENUE_ID) continue; counts.venue++;
  if (i.status !== "Trading") continue; counts.trading_idx++;
  const oc: any = await cl.getMarketOnchain(i.marketId as `0x${string}`).catch(() => null);
  if (oc?.status !== 1) { console.log("onchain status", oc?.status, String(i.marketId).slice(-6)); continue; }
  counts.onchain_ok++;
  const left = Number(i.expiry) - now;
  if (left < 120 || left > 285) { console.log("left", left, i.asset, String(i.marketId).slice(-6)); continue; }
  counts.left_ok++;
  const sym = m.outcomes?.[0]?.symbol;
  const bk: any = await Promise.race([ex.fetchOrderBook(sym, 5), new Promise((r) => setTimeout(() => r(null), 12000))]);
  if (!bk?.bids?.length || !bk?.asks?.length) { console.log("book empty", sym); continue; }
  counts.book_ok++;
  const mid = (bk.bids[0][0] + bk.asks[0][0]) / 2;
  if (mid < 0.05 || mid > 0.95) { console.log("mid out of range", mid, sym); continue; }
  counts.mid_ok++;
}
console.log(counts);
process.exit(0);
