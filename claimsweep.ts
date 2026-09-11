// Claim sweep: merge complete sets (YES+NO -> collateral, refund both), redeem every
// finalized holding. Run standalone or from live.ts end-of-run. Real transactions.
import { SomniaMarkets } from "@somnia-chain/markets-sdk";
import { somniaShannon } from "@somnia-chain/markets-sdk/chains";
import { readFileSync, appendFileSync } from "node:fs";
import { privateKeyToAccount } from "viem/accounts";

const pk = `0x${readFileSync("data/pin_key.txt", "utf8").trim().replace(/^0x/, "")}` as `0x${string}`;
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
  chain: somniaShannon, wsRpcUrl: "wss://api.infra.testnet.somnia.network/ws",
  addresses: CORE as any, privateKey: pk,
});
const write = (o: any) => appendFileSync("data/live_ledger.jsonl", JSON.stringify({ ts: Date.now(), ...o }) + "\n");
const log = (s: string) => console.log(`[${new Date().toISOString()}] ${s}`);
const bal: any = await ex.fetchBalance();
log("balance keys: " + Object.entries<any>(bal).filter(([k, v]) => (v?.total ?? 0) > 0).map(([k, v]) => `${k.slice(0, 28)}=${v.total}`).join(", ").slice(0, 900));

// 1) merge complete sets where both legs held per market base
const byBase: Record<string, { y: number; n: number }> = {};
for (const [k, v] of Object.entries<any>(bal ?? {})) {
  const amt = v?.total ?? 0; if (!amt) continue;
  const mm = k.match(/^(.*)#(YES|NO)$/); if (!mm) continue;
  const b = mm[1]; byBase[b] ??= { y: 0, n: 0 };
  if (mm[2] === "YES") byBase[b].y += amt; else byBase[b].n += amt;
}
for (const [base, { y, n }] of Object.entries(byBase)) {
  const pairs = Math.min(y, n);
  if (pairs >= 1) {
    try {
      const r: any = await ex.burnSet?.(base, Math.floor(pairs));
      const h = r?.hash ?? r?.info?.receipt?.transactionHash;
      write({ ev: "merge", base: base.slice(-24), pairs, tx: h }); log(`merged ${pairs} pairs ${base.slice(0, 30)} -> ${h}`);
    } catch (e: any) { log(`merge err ${base.slice(0, 30)}: ${String(e?.message ?? e).slice(0, 120)}`); }
  }
}
// 2) redeem winners on finalized markets
const cl = ex.client as any;
const fin: any[] = await cl.listBinaryMarkets({ venueId: "0x679795a0195a1b76cdebb7c51d74e058aee92919b8c3389af86ef24535e8a28c", status: "Finalized", limit: 100 });
const finIds = new Set(fin.map((r) => r.marketId));
const bal2: any = await ex.fetchBalance();
for (const [k, v] of Object.entries<any>(bal2 ?? {})) {
  const amt = v?.total ?? 0; if (!amt) continue;
  const mm = k.match(/^(.*)#(YES|NO)$/); if (!mm) continue;
  try {
    const r: any = await ex.redeem(mm[1], amt);
    const h = r?.hash ?? r?.info?.receipt?.transactionHash;
    write({ ev: "redeem", sym: k.slice(0, 40), amt, tx: h }); log(`redeemed ${k.slice(0, 36)} amt=${amt} -> ${h}`);
  } catch (e: any) {
    log(`skip ${k.slice(0, 36)}: ${String(e?.message ?? e).slice(0, 90)}`);
  }
}
const balF: any = await ex.fetchBalance();
const coll = balF?.tUSDC?.total ?? balF?.["0x70a86d8842fb63c4ad2b7cdddf530ebf1bb25d8e"]?.total;
log(`final tUSDC: ${coll ?? "?"}`);
await ex.close(); process.exit(0);
