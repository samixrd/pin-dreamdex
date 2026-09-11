// Rail access: open price at window start from recorded px files (deep rail first).
// Auto-refreshes when any source file grows (collector keeps writing px.jsonl).
import { readFileSync, statSync } from "node:fs";
let cache: Record<string, [number, number][]> | null = null;
let cacheSig = "";
function filesSig(): string {
  return ["data/px_deep.jsonl", "data/px_history.jsonl", "data/px.jsonl"]
    .map((f) => { try { return String(statSync(f).size); } catch { return "0"; } }).join("|");
}
function load(): Record<string, [number, number][]> {
  const sig = filesSig();
  if (cache && sig === cacheSig) return cache;
  cacheSig = sig;
  const m: Record<string, Map<number, number>> = { BTC: new Map(), ETH: new Map() };
  for (const f of ["data/px_deep.jsonl", "data/px_history.jsonl", "data/px.jsonl"]) {
    try {
      for (const l of readFileSync(f, "utf8").split("\n")) {
        if (!l.trim()) continue;
        const p = JSON.parse(l);
        if (!(p.asset in m)) continue;
        if (p.src === "1m") {
          const c = typeof p.c === "string" ? Number(BigInt(p.c)) / 1e18 : p.c;
          m[p.asset].set(p.t, c);
        } else if (p.src === "tick" && p.price) {
          m[p.asset].set(Math.floor(p.t / 60000) * 60000, p.price);
        }
      }
    } catch {}
  }
  cache = Object.fromEntries(Object.entries(m).map(([a, d]) => [a, [...d.entries()].sort((x, y) => x[0] - y[0])]));
  return cache!;
}
/** close of the last 1m bucket at/just-before ms (null if outside rail) */
export async function sortedOpen(asset: string, ms: number): Promise<number | null> {
  const s = load()[asset]; if (!s?.length) return null;
  let lo = 0, hi = s.length - 1;
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (s[mid][0] <= ms) lo = mid; else hi = mid - 1; }
  return s[lo][0] <= ms && ms - s[lo][0] <= 120_000 ? s[lo][1] : null;
}
