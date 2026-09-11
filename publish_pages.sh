#!/usr/bin/env bash
# Publish the live dashboard to GitHub Pages (runs from VM crontab, every 15 min).
cd "$(dirname "$0")"
git pull --rebase -q origin main >/dev/null 2>&1 || git rebase --abort 2>/dev/null
python3 dashboard.py >/dev/null 2>&1 || true
cp data/dashboard.html docs/index.html
if ! git diff --quiet docs/index.html; then
  git add docs/index.html && git commit -qm "pages: vm auto $(date -u +%H:%M)" && git push -q origin main
fi
