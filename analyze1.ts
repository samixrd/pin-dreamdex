// PIN analysis #1: pin risk + book anatomy + maker concentration from recorded history.
// Reads data/history.jsonl (marketId-keyed, fills p in raw units: 6-dp venue => /1e6 for prob)
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const __dirname = dirname(fileURLToPath(import.meta.url));
const DATA = join(__dirname, "data");

const recs = readFileSync(join(DATA, "history.jsonl"), "utf8").split("\n").filter(Boolean)
  .map((l) => JSON.parse(l));
const live = readFileSync(join(DATA, "settled.jsonl"), "utf8").split("\n").filter(Boolean)
  .map((l) => JSON.parse(l));
const byId = new Map<string, any>();
for (const r of [...recs, ...live]) if (!byId.has(r.marketId)) byId.set(r.marketId, r);
const rows = [...byId.values()];
console.log("markets analyzed:", rows.length);

const COL = 1e6; // 6-dp testnet: price unit
const stats = { total: 0, dead: 0, died5m: { t: 0, d: 0 }, pins: [] as number[], distNear: 0,
  makerConc: [] as any[], mintShare: [] as number[] };

for (const m of rows) {
  if (m.voided) continue;
  const fills: any[] = m.fills ?? [];
  stats.total++;
  if (!fills.length) { stats.dead++;
    if (Number(m.intervalSec) <= 600) { stats.died5m.t++; stats.died5m.d++; }
    continue; }
  // maker concentration: largest maker's share of fills
  const mk = new Map<string, number>();
  let mint = 0;
  for (const f of fills) {
    mk.set(f.mk ?? "?", (mk.get(f.mk ?? "?") ?? 0) + 1);
    if (f.kind === "MINT_A_PAIR" || f.kind === "BURN_A_PAIR") mint++;
  }
  const top = [...mk.values()].sort((a, b) => b - a)[0];
  stats.makerConc.push(top / fills.length);
  stats.mintShare.push(mint / fills.length);
  // pin proxy: last trade price vs 0/1 extremity in final 20% of window
  const span = m.resolvedAt - m.start;
  const late = fills.filter((f) => f.t > m.resolvedAt - 0.2 * span);
  if (late.length) {
    const last = late[late.length - 1];
    const p = Number(last.p) / COL;
    const pinness = Math.min(p, 1 - p); // distance from settled-at-1 => how close to the line at the end
    stats.pins.push(pinness);
    if (pinness < 0.05) stats.distNear++;
  }
}
const med = (a: number[]) => a.slice().sort((x, y) => x - y)[Math.floor(a.length / 2)] ?? NaN;
console.log(JSON.stringify({
  totalMarkets: stats.total,
  deadMarkets: stats.dead,
  deadPct: +(100 * stats.dead / stats.total).toFixed(1),
  fiveMinWindows: stats.died5m.t, fiveMinDeadPct: +(100 * stats.died5m.d / (stats.died5m.t || 1)).toFixed(1),
  marketsWithLateTrades: stats.pins.length,
  pinnedNearLine_pct_lt5c: +(100 * stats.distNear / (stats.pins.length || 1)).toFixed(1),
  medianLateDistFromEdge: +med(stats.pins).toFixed(3),
  medianTopMakerShare: +med(stats.makerConc).toFixed(2),
  medianMintPairShare: +med(stats.mintShare).toFixed(2),
}, null, 1));
