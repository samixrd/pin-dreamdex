// PIN analysis #2: true pin risk from price rail + settlement validation.
// For each traded market: openMark = px close at/just-before tradingStart,
// settleMark = px close at expiry; winner = settleMark >= openMark ? Up : Down.
// We VALIDATE that against the on-chain winningOutcome before trusting the dist stats.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const __dirname = dirname(fileURLToPath(import.meta.url));
const DATA = join(__dirname, "data");

function loadJsonl(f: string): any[] {
  try { return readFileSync(join(DATA, f), "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l)); }
  catch { return []; }
}
const markets = new Map<string, any>();
for (const r of [...loadJsonl("history.jsonl"), ...loadJsonl("settled.jsonl")])
  if (!markets.has(r.marketId)) markets.set(r.marketId, r);

// px rail: per-asset sorted close series from 1m candles (dedupe by bucket)
const rail: Record<string, { t: number; c: number }[]> = { BTC: [], ETH: [] };
const buckets: Record<string, Map<number, number>> = { BTC: new Map(), ETH: new Map() };
for (const f of ["px.jsonl", "px_history.jsonl"]) for (const p of loadJsonl(f)) {
  if (p.src !== "1m" || !rail[p.asset]) continue;
  buckets[p.asset].set(p.t, p.c);
}
for (const a of Object.keys(rail)) rail[a] = [...buckets[a].entries()].map(([t, c]) => ({ t, c })).sort((x, y) => x.t - y.t);
console.log("rail:", rail.BTC.length, "BTC pts,", rail.ETH.length, "ETH pts", rail.BTC.length ? `${new Date(rail.BTC[0].t).toISOString()} -> ${new Date(rail.BTC.at(-1)!.t).toISOString()}` : "");

const at = (a: string, ms: number): number | null => {
  const r = rail[a]; if (!r.length) return null;
  if (ms < r[0].t || ms > r.at(-1)!.t + 90_000) return null;
  let lo = 0, hi = r.length - 1;
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (r[mid].t <= ms) lo = mid; else hi = mid - 1; }
  return r[lo].c;
};

let validated = 0, mismatch = 0, skipped = 0;
const distBps: { d: number; tau: number; asset: string; traded: boolean; i5: boolean }[] = [];
const rv: { volBps: number; distBps: number }[] = [];
for (const m of markets.values()) {
  if (m.voided) continue;
  const open = at(m.asset, m.start * 1000), settle = at(m.asset, m.expiry * 1000);
  if (open == null || settle == null || open === 0) { skipped++; continue; }
  const upWins = settle >= open;
  // outcome order is [Up, Down]: Up won iff payoutNumerators[0] >= [1] (void = both 0.5)
  const chainUp = (m.payoutNumerators?.length === 2)
    ? Number(m.payoutNumerators[0]) >= Number(m.payoutNumerators[1])
    : m.winningOutcome === 0;
  const agree = upWins === chainUp;
  if (agree) validated++; else { mismatch++; continue; }

  const d = Math.abs(settle - open) / open * 1e4; // bps
  distBps.push({ d, tau: m.expiry - m.start, asset: m.asset, traded: (m.fills?.length ?? 0) > 0, i5: Number(m.intervalSec) <= 600 });
  if ((m.fills?.length ?? 0) > 0) {
    // realized vol during window from last trade price ladder? use px rail 1m stdev instead
    const from = m.start * 1000, to = m.expiry * 1000;
    const pts = rail[m.asset].filter((p) => p.t >= from && p.t <= to).map((p) => p.c);
    if (pts.length > 3) {
      const rets = pts.slice(1).map((c, i) => Math.log(c / pts[i]));
      const mu = rets.reduce((a, b) => a + b) / rets.length;
      const sd = Math.sqrt(rets.reduce((a, b) => a + (b - mu) ** 2, 0) / (rets.length - 1)) * 1e4; // bps/min
      rv.push({ volBps: sd, distBps: d });
    }
  }
}
const q = (a: number[], p: number) => { const s = a.slice().sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(p * s.length))]; };
const dd = distBps.map((x) => x.d);
const near = distBps.filter((x) => x.d < 25); // <25 bps from the line = "pinned zone" (order of a 2-3c quote distance)
const near5 = distBps.filter((x) => x.d < 25 && x.i5);
console.log(JSON.stringify({
  marketsInRail: validated + mismatch, settlementAgreement: { validated, mismatch }, skippedOutOfRail: skipped,
  settleDistBps: { median: q(dd, .5), p10: q(dd, .1), p25: q(dd, .25), p75: q(dd, .75), p90: q(dd, .9) },
  pctWithin25bps: +(100 * near.length / distBps.length).toFixed(1),
  pctWithin25bps_5minWindows: +(100 * near5.length / Math.max(1, distBps.filter((x) => x.i5).length)).toFixed(1),
  pinnedAndTraded: near.filter((x) => x.traded).length,
}, null, 1));
// vol-vs-distance regression points for the quote-distance policy
const vv = rv.sort((a, b) => a.volBps - b.volBps);
console.log("rv pairs:", vv.length, "medianVolBpsPerMin:", vv.length ? q(vv.map((x) => x.volBps), .5).toFixed(1) : "n/a",
  "medianDist:", vv.length ? q(vv.map((x) => x.distBps), .5).toFixed(1) : "n/a");
