// PIN live runner v2 — the sweep-frontier policy driving REAL orders on Shannon testnet.
// Windows: any live DreamDEX EC market with >=25 min headroom (4h/24h windows qualify;
// their mid is far from settlement so the kill rarely fires — good for v0 receipts).
// Flow: rest BUY YES @ mid-d + BUY NO @ (1-mid)-d (zero inventory, mint-a-pair maker)
//       requote when mid moves >1.5 tick; KILL (pull all) inside pin band;
//       before close: flatten; after settle: redeem winner(s); ledger per event.
// SAFETY: DRY default; TOTAL_CAP/WINDOW_CAP tUSDC; orders expire at window close; never
//         logs the key; redeems to same wallet. Uses PIN_MARKETS_SDK testnet conventions.
import { SomniaMarkets, isBinaryMarket, SOMNIA_TESTNET_PRICE_FEED } from "@somnia-chain/markets-sdk";
import { somniaShannon } from "@somnia-chain/markets-sdk/chains";
import { readFileSync, appendFileSync, mkdirSync } from "node:fs";
import { sortedOpen } from "./pxrail.ts";

const DRY = process.env.LIVE_DRY !== "0";
const KEY = (() => {
  const f = process.env.PIN_KEY_FILE ?? "data/pin_key.txt";
  const m = readFileSync(f, "utf8").match(/(0x)?([0-9a-fA-F]{64})/);
  if (!m) throw new Error("no key in " + f);
  return `0x${m[2]}` as `0x${string}`;
})();

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

// frozen operating point (sweep frontier, balanced insurance setting)
const SIGMA = 0.01, D = 0.005, KILL_K = 0.35, TICK_REQUOTE = 0.0015;  // kill = P(pin<=10bp) > 0.35 (hazard-calibrated)
const QUOTE_Q = 5;                    // contracts/side/cycle (~5 tUSDC/cycle)
const TOTAL_CAP = 200, WINDOW_CAP = 60;
const REQUOTE_MS = 12_000, FLATTEN_S = 240;

const ex = new SomniaMarkets({
  indexerUrl: "https://dev.smk.somnia.host/v1/graphql",
  chain: somniaShannon,
  wsRpcUrl: "wss://api.infra.testnet.somnia.network/ws",
  addresses: CORE as any,
  priceFeed: SOMNIA_TESTNET_PRICE_FEED,
  ...(DRY ? {} : { privateKey: KEY }),
});
const cl = ex.client as any;
mkdirSync("data", { recursive: true });
const write = (o: any) => appendFileSync("data/live_ledger.jsonl", JSON.stringify({ ts: Date.now(), ...o }) + "\n");
const log = (s: string) => console.log(`[${new Date().toISOString()}] ${s}`);

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
/** Abramowitz-Stegun erf approximation (|err| < 1.5e-7) */
function erf(x: number): number {
  const s = x < 0 ? -1 : 1; x = Math.abs(x);
  const t = 1 / (1 + 0.3275911 * x);
  const y = 1 - ((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t * Math.exp(-x * x);
  return s * y;
}
const withTimeout = <T,>(p: Promise<T>, ms: number): Promise<T | null> =>
  Promise.race([p, sleep(ms).then(() => null)]);

async function spot(asset: string) {
  const p: any = await withTimeout(ex.fetchPrice(asset), 9000);
  return p?.price ?? null;
}
async function minuteVol(asset: string) {
  const rows: any = await withTimeout(ex.fetchPriceOHLCV(asset, "1m", undefined, 180), 15000);
  if (!rows?.length || rows.length < 30) return null;
  const pts = rows.map((r: any) => r[4]);
  const rets = pts.slice(1).map((c: number, i: number) => Math.log(c / pts[i]));
  const mu = rets.reduce((a, b) => a + b) / rets.length;
  return Math.sqrt(rets.reduce((a, b) => a + (b - mu) ** 2, 0) / (rets.length - 1));
}

async function pickWindow() {
  const markets = await withTimeout(ex.loadMarkets(true), 40000);
  if (!markets) return null;
  const now = Math.floor(Date.now() / 1000);
  const cands: any[] = [];
  for (const m of Object.values<any>(markets)) {
    const i = m.info;
    if (!isBinaryMarket(i) || i.venueId !== VENUE_ID) continue;
    // on-chain status gate (indexer lag gotcha #1)
    const oc: any = await withTimeout(cl.getMarketOnchain(i.marketId as `0x${string}`), 12000).catch(() => null);
    if (oc?.status !== 1) continue;
    const sym = m.outcomes?.[0]?.symbol; if (!sym) continue;
    const left = Number(i.expiry) - now;
    if (left < 360 || left > 1200) continue;      // v1-money: windows with real runway (6-20 min)
    const bk: any = await withTimeout(ex.fetchOrderBook(sym, 5), 12000);
    if (!bk?.bids?.length || !bk?.asks?.length) continue;
    const mid = (bk.bids[0][0] + bk.asks[0][0]) / 2;
    if (mid < 0.05 || mid > 0.95) continue;     // deep-tail books = pin noise
    cands.push({ i, sym, mid, left, m });
  }
  if (!cands.length) return null;
  cands.sort((a, b) => b.left - a.left);
  return cands[0];
}

async function myOpenOrders(symScope: string): Promise<any[]> {
  if (DRY) return [];
  try {
    const os: any = await withTimeout(ex.fetchOrders(symScope, undefined, 100), 15000);
    return (os ?? []).filter((o: any) => o.status === "open");
  } catch { return []; }
}

async function main() {
  const { privateKeyToAccount } = await import("viem/accounts");
  const acct = DRY ? "(dry)" : privateKeyToAccount(KEY).address;
  log(`PIN live runner | account ${acct} | DRY=${DRY} | policy d=${D} kill=${KILL_K} q=${QUOTE_Q}`);
  let grandSpent = 0, windowsDone = 0;
  const MAX_WINDOWS = Number(process.env.LIVE_MAX_WINDOWS ?? 40);
  const BAL_FLOOR = 9_700;   // stop if tUSDC ever drops below this (hard loss rail, 300 max loss)
  while (windowsDone < MAX_WINDOWS) {
    if (!DRY) {
      const b: any = await withTimeout(ex.fetchBalance(), 15000);
      const t = b?.tUSDC?.total ?? b?.["0x70a86d8842fb63c4ad2b7cdddf530ebf1bb25d8e"]?.total ?? 1e9;
      if (Number(t) < BAL_FLOOR) { log(`LOSS RAIL: tUSDC ${t} < ${BAL_FLOOR} — halting`); break; }
    }
    const r = await runOneWindow();
    if (r == null) { log("no eligible window right now; retry in 60s"); await sleep(60_000); continue; }
    grandSpent += r; windowsDone++;
    log(`window ${windowsDone}/${MAX_WINDOWS} done; cumulative turnover ≈ ${grandSpent.toFixed(1)} tUSDC`);
    // periodic claim sweep so settled holdings recycle back to collateral
    try {
      const bal: any = await withTimeout(ex.fetchBalance(), 15000);
      for (const [k, v] of Object.entries<any>(bal ?? {})) {
        const amt = v?.total ?? 0; if (!amt) continue;
        const mm = k.match(/^(.*)#(YES|NO)$/); if (!mm) continue;
        try { const rr: any = await ex.redeem(mm[1], amt); write({ ev: "redeem", sym: k.slice(0, 40), amt, tx: rr?.hash }); log(`claim ${k.slice(0, 32)} ${amt} -> ${rr?.hash}`); } catch {}
      }
    } catch {}
    await sleep(20_000);
  }
  log(`ALL DONE | ${windowsDone} windows, cumulative ≈ ${grandSpent.toFixed(1)}`);
  // claim sweep: any residual outcome-token balances get redeemed if finalized
  if (!DRY) {
    const bal: any = await withTimeout(ex.fetchBalance(), 20000);
    for (const [symK, v] of Object.entries<any>(bal ?? {})) {
      const amt = v?.total ?? 0;
      if (amt > 0 && (symK.includes("#YES") || symK.includes("#NO"))) {
        const baseK = symK.replace(/#(YES|NO)$/, "");
        try {
          const r: any = await ex.redeem(baseK, amt);
          write({ ev: "claim_sweep", sym: symK, amt, tx: r.hash });
          log(`claim sweep ${symK} ${amt} -> ${r.hash}`);
        } catch (e: any) { log(`claim sweep ${symK.slice(0, 30)} err ${String(e?.message ?? e).slice(0, 110)}`); }
      }
    }
  }
  await ex.close(); process.exit(0);
}

async function runOneWindow() {
  const sel = await pickWindow();
  if (!sel) return null;
  const { i, sym, mid } = sel;
  const mkid = i.marketId, asset = i.asset, expiry = Number(i.expiry), start = Number(i.tradingStart);
  const base = sym.replace(/#YES$/, "");
  log(`selected ${asset} …${String(mkid).slice(-6)} mid=${mid.toFixed(3)} left=${((expiry - Date.now() / 1000) / 60) | 0}m expiryNs ok`);

  // window-start collateral snapshot for balance-delta settle PnL (tUSDC raw 6-dp)
  const TUSDC = "0x70a86D8842FB63C4Ad2b7cdddF530eBf1BB25d8E";
  async function tusdc(): Promise<number | null> {
    const bal: any = await withTimeout(ex.fetchBalance(), 15000);
    const v = bal?.tUSDC?.total ?? bal?.["0x70a86d8842fb63c4ad2b7cdddf530ebf1bb25d8e"]?.total;
    return v == null ? null : Number(v);
  }
  const b0 = DRY ? 0 : await tusdc();

  // line-to-beat from the deep rail (window open price). Fallback: window is young
  // (<6min left of a <=5min series, i.e. just opened) -> current spot IS ~the open.
  let line = await sortedOpen(asset, start * 1000);
  if (!line && (expiry - Math.floor(Date.now() / 1000)) > 240 && Number(i.intervalSec) <= 300) {
    line = await spot(asset);
    if (line) log(`line fallback: spot-at-select ${line.toFixed(2)} (window just opened)`);
  }
  log(`line-to-beat ${line ? line.toFixed(2) : "n/a (kill disabled without line)"}`);
  const vol = line ? await minuteVol(asset) : null;
  const expiryNs = BigInt(expiry) * 1_000_000_000n;

  let resting: { id: string; sym: string; kind: "YES" | "NO"; px: number; since: number }[] = [];
  let spent = 0, fills = 0, killOn = false, cycles = 0, lastMid = mid;
  let holdY = 0, holdN = 0, costY = 0, costN = 0;   // per-window position book for settle PnL

  while (Date.now() / 1000 < expiry - FLATTEN_S) {
    cycles++;
    const now = Math.floor(Date.now() / 1000);
    const tauMin = Math.max(0.05, (expiry - now) / 60);
    const px = line ? await spot(asset) : null;
    // pin hazard: P(settles within ±25bps of line) under BM remainder — kill_k is a probability
    let inBand = false;
    if (line && vol && px && KILL_K > 0) {
      const r = Math.log(px / line), s = vol * Math.sqrt(tauMin), e = 0.001;  // 10bp, empirically calibrated
      const Nrm = (x: number) => 0.5 * (1 + erf(x / Math.SQRT2));
      const pPin = Nrm((r + e) / s) - Nrm((r - e) / s);
      inBand = pPin > KILL_K;
    }
    if (inBand && !killOn) { killOn = true; log(`KILL: pin-hazard @ τ=${tauMin.toFixed(1)}min — pulling quotes`); await cancelAll(resting); resting = []; }
    if (!inBand) killOn = false;
    if (inBand) { await sleep(REQUOTE_MS); continue; }

    const bk: any = await withTimeout(ex.fetchOrderBook(sym, 5), 12000);
    if (!bk?.bids?.length || !bk?.asks?.length) { await sleep(4000); continue; }
    const m = (bk.bids[0][0] + bk.asks[0][0]) / 2;
    const nb = Math.floor((m - D) * 1e6) / 1e6;
    const np = Math.floor((1 - m - D) * 1e6) / 1e6;

    if (Math.abs(m - lastMid) > TICK_REQUOTE || !resting.length) {
      await cancelAll(resting); resting = [];
      if (spent + QUOTE_Q * (nb + np) > Math.min(TOTAL_CAP, WINDOW_CAP)) { log("cap reached, riding out window"); break; }
      if (DRY) {
        log(`DRY rest YES ${QUOTE_Q}@${nb.toFixed(3)} / NO ${QUOTE_Q}@${np.toFixed(3)} (spent≈${(spent + QUOTE_Q * (nb + np)).toFixed(1)})`);
        spent += QUOTE_Q * (nb + np); lastMid = m;
        await sleep(REQUOTE_MS); continue;
      }
      try {
        const y: any = await ex.createOrder(sym, "limit", "buy", QUOTE_Q, nb, { expireTimestampNs: expiryNs, postOnly: true } as any).catch((e: any) => { log(`YES err ${String(e?.message ?? e).slice(0, 120)}`); return null; });
        const n: any = await ex.createOrder(sym.replace("#YES", "#NO"), "limit", "buy", QUOTE_Q, np, { expireTimestampNs: expiryNs, postOnly: true } as any).catch((e: any) => { log(`NO err ${String(e?.message ?? e).slice(0, 120)}`); return null; });
        for (const [r, kind, pxv] of [[y, "YES", nb], [n, "NO", np]] as const) {
          if (!r) continue;
          const id = r.id ?? r.info?.id ?? r.info?.orderId;
          const h = r.info?.receipt?.transactionHash ?? null;
          if (DRY) log(`DRY rest ${kind} ${QUOTE_Q}@${pxv.toFixed(3)}`);
          else write({ ev: "rest", mkid: String(mkid).slice(-6), kind, qty: QUOTE_Q, px: pxv, id, tx: h });
          if (id) resting.push({ id: String(id), sym: kind === "YES" ? sym : sym.replace("#YES", "#NO"), kind, px: pxv, since: Date.now() });
        }
        spent += QUOTE_Q * (nb + np);
        lastMid = m;
        if (cycles % 10 === 0) log(`cycle ${cycles}: resting=${resting.length} spent≈${spent.toFixed(1)} mid=${m.toFixed(3)}`);
      } catch (e: any) { log(`place fail ${String(e?.message ?? e).slice(0, 140)}`); }
    }

    // fills? compare resting ids against open orders (grace 25s: indexer lag means a
    // just-placed order can be missing from fetchOrders and read as a false fill)
    if (!DRY && resting.length) {
      const open = await myOpenOrders(base);
      const openIds = new Set(open.map((o: any) => String(o.id ?? o.orderId)));
      for (const r of resting.filter((x) => !openIds.has(x.id) && Date.now() - x.since > 25_000)) {
        fills++; log(`FILL detected: ${r.kind} ${QUOTE_Q}@${r.px.toFixed(3)} (settles at 0/1)`);
        write({ ev: "fill", mkid: String(mkid).slice(-6), kind: r.kind, qty: QUOTE_Q, px: r.px });
        if (r.kind === "YES") { holdY += QUOTE_Q; costY += QUOTE_Q * r.px; } else { holdN += QUOTE_Q; costN += QUOTE_Q * r.px; }
      }
      resting = resting.filter((x) => openIds.has(x.id) || Date.now() - x.since <= 25_000);
    }
    await sleep(REQUOTE_MS);
  }

  // ---- flatten leg: cancel rest, market-out inventory via IOC take ----
  await cancelAll(resting); resting = [];
  if (!DRY) {
    const bal: any = await withTimeout(ex.fetchBalance(), 15000);
    const qy = bal?.[sym]?.total ?? 0, qn = bal?.[sym.replace("#YES", "#NO")]?.total ?? 0;
    log(`inventory YES=${qy} NO=${qn}`);
    if (qy > 0 || qn > 0) {
      const bk: any = await withTimeout(ex.fetchOrderBook(sym, 5), 12000);
      const bb = bk?.bids?.[0]?.[0], ba = bk?.asks?.[0]?.[0];
      if (qy > 0 && bb) try { await ex.createOrder(sym, "limit", "sell", qy, bb * 0.97, { timeInForce: "IOC" } as any); write({ ev: "flatten", side: "YES", q: qy }); } catch (e: any) { log(`flatten YES err ${String(e?.message ?? e).slice(0, 100)}`); }
      if (qn > 0 && ba) try { await ex.createOrder(sym.replace("#YES", "#NO"), "limit", "sell", qn, (1 - ba) * 0.97, { timeInForce: "IOC" } as any); write({ ev: "flatten", side: "NO", q: qn }); } catch (e: any) { log(`flatten NO err ${String(e?.message ?? e).slice(0, 100)}`); }
      // unflattenable inventory is FINE: it rides to settlement and the claim sweep redeems 0/1
    }
  } else log("DRY: would flatten now");

  // ---- settlement + redeem: poll REDEEM itself (removes indexer finalization latency) ----
  log("window closed; redeeming (retry loop ≤10min)…");
  let redeemed = false, lastErr = "";
  for (let t = 0; t < 40 && !redeemed; t++) {
    await sleep(15000);
    if (DRY) break;
    try {
      const bal: any = await withTimeout(ex.fetchBalance(), 15000);
      const winSymA = sym, winSymB = sym.replace("#YES", "#NO");
      const a = bal?.[sym]?.total ?? 0, b = bal?.[winSymB]?.total ?? 0;
      if (!a && !b) { log("nothing to redeem (no inventory)"); redeemed = true; break; }
      const side = a ? sym : winSymB;
      const amt = a || b;
      const r: any = await ex.redeem(base, amt);
      write({ ev: "redeem", amt, side: side.endsWith("NO") ? "NO" : "YES", tx: r.hash, mkid: String(mkid).slice(-6) });
      log(`redeemed ${amt} ${side.endsWith("NO") ? "NO" : "YES"} -> ${r.hash}`);
      redeemed = true;
    } catch (e: any) {
      lastErr = String(e?.message ?? e).slice(0, 120);
      if (lastErr.includes("InsufficientBalance")) { log("redeem: balance not releaseable yet (escrow lag) — deferring to sweep"); write({ ev: "redeem_pending", mkid: String(mkid).slice(-6), err: lastErr }); redeemed = true; break; }
      if (!lastErr.includes("unresolved")) log(`redeem err: ${lastErr}`);
    }
  }
  if (!redeemed && lastErr) write({ ev: "redeem_pending", mkid: String(mkid).slice(-6), err: lastErr });
  const balF: any = DRY ? null : await withTimeout(ex.fetchBalance(), 15000);
  // balance-delta settle PnL: what this window actually cost/earned in collateral
  let pnl: number | null = null;
  if (!DRY && b0 != null) {
    const b1 = await tusdc();
    if (b1 != null) pnl = (b1 - b0) / 1e6;
  }
  write({ ev: "window_settle", mkid: String(mkid).slice(-6), asset, fills, holdY, holdN,
          cost: +(costY + costN).toFixed(3), pnl_balance_delta: pnl,
          note: "pnl = wallet tUSDC delta over window (includes escrow timing; claims land via sweep)" });
  log(`SETTLE …${String(mkid).slice(-6)} fills=${fills} pos Y${holdY}/N${holdN} cost=${(costY + costN).toFixed(2)} Δbalance=${pnl == null ? "n/a" : pnl.toFixed(2)}`);
  log(`DONE | cycles=${cycles} fills=${fills} spent≈${spent.toFixed(2)} final tUSDC=${balF?.tUSDC?.free ?? balF?.["0x70a86d8842fb63c4ad2b7cdddf530ebf1bb25d8e"]?.free ?? "?"}`);
  return spent;
}

async function cancelAll(list: { id: string; sym: string }[]) {
  for (const o of list) {
    try { await ex.cancelOrder(o.id, o.sym); if (!DRY) write({ ev: "cancel", id: o.id }); } catch {}
  }
}

main().catch((e) => { log(`FATAL ${String(e?.stack ?? e).slice(0, 500)}`); process.exit(1); });
