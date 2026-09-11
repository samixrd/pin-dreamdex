#!/usr/bin/env bash
# PIN watchdog v3 — restarts dead services only (no setsid on git-bash). Self-retires ~9h.
cd "C:/Users/Acer/pin-probe" || exit 1
END=$(( $(date +%s) + 32400 ))
log() { echo "[$(date -u +%H:%M:%S)] $*" >> data/watchdog.log; }
status() { python psalive.py 2>/dev/null; }
log "watchdog v3 up"
while [ "$(date +%s)" -lt "$END" ]; do
  eval "$(status | awk '{printf "%s=%s\n", $1, $2}')"
  [ "${collector:-0}" -eq 0 ] && { log "restart collector"; nohup npx tsx collector.ts >> data/collector.out 2>&1 & sleep 8; }
  [ "${paper:-0}" -eq 0 ]    && { log "restart paper";      nohup python paper.py >> data/paper.out 2>&1 & sleep 8; }
  [ "${live:-0}" -eq 0 ]     && { log "restart live";       LIVE_DRY=0 LIVE_MAX_WINDOWS=40 nohup npx tsx live.ts >> data/live_runner.out 2>&1 & sleep 8; }
  if [ "${backfill:-0}" -eq 0 ] && ! grep -q "backfill complete" data/backfill.log 2>/dev/null; then
    log "restart backfill"; nohup npx tsx backfill.ts 30 >> data/backfill.out 2>&1 & sleep 8
  fi
  python dashboard.py >> data/dashboard.out 2>&1
  sleep 90
done
log "watchdog retiring"
