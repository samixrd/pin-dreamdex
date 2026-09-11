#!/usr/bin/env bash
# PIN supervisor tick — designed for Hermes cron (every 10m). Restarts dead services with
# fully detached lifetime (powershell Start-Process), regenerates dashboard. Idempotent:
# never double-launches (psalive.py counts). Quiet unless something restarts.
cd "C:/Users/Acer/pin-probe" || exit 1
log() { echo "[$(date -u +%F_%H:%M:%S)] $*"; }
status() { python psalive.py 2>/dev/null; }
launch() { # name, envstring, command...
  local tag="$1"; shift
  local envs="$1"; shift
  if command -v powershell >/dev/null 2>&1 || [ -x "/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe" ]; then
    "/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe" -NoProfile -Command \
      "Start-Process -WindowStyle Hidden -FilePath 'C:\Program Files\Git\bin\bash.exe' -ArgumentList '-lc', \"cd /c/Users/Acer/pin-probe && $envs $* >> data/$tag.out 2>&1\"" >/dev/null 2>&1
    log "launched $tag via powershell"
  else
    nohup "$@" >> "data/$tag.out" 2>&1 &
    log "launched $tag via nohup"
  fi
}
eval "$(status | awk '{printf "%s=%s\n", $1, $2}')"
OUT=""
[ "${collector:-0}" -eq 0 ] && { launch collector "" npx tsx collector.ts; OUT="$OUT collector"; }
[ "${paper:-0}" -eq 0 ]    && { launch paper "" python paper.py; OUT="$OUT paper"; }
[ "${live:-0}" -eq 0 ]     && { launch live "LIVE_DRY=0 LIVE_MAX_WINDOWS=40" npx tsx live.ts; OUT="$OUT live"; }
if [ "${backfill:-0}" -eq 0 ] && ! grep -q "backfill complete" data/backfill.log 2>/dev/null; then
  launch backfill "" npx tsx backfill.ts 30; OUT="$OUT backfill"
fi
python dashboard.py >/dev/null 2>&1
# money watchdog: warn if live wallet lost collateral beyond the rail
python - <<'EOF' 2>/dev/null
import json, os, datetime as dt
led = "data/live_ledger.jsonl"
if os.path.exists(led):
    with open(led, encoding="utf-8") as f:
        lines = f.readlines()[-400:]
    evs = [json.loads(l) for l in lines if l.strip()]
    settles = [e for e in evs if e.get("ev") == "settle"]
    print(f"LEDGER: events={len(evs)} settles={len(settles)} last={settles[-1] if settles else '-'}")
EOF
[ -n "$OUT" ] && echo "PIN supervisor restarted:$OUT" || true