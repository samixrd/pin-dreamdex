#!/bin/bash
# VM entry: ensure px rail fresh + let services run. pm2 restarts crashes; this runs as cron.
cd "$HOME/pin" || exit 1
# refresh the deep rail periodically (appends, resumable); cheap, capped pages
python3 pxdeep.py >> data/pxdeep.out 2>&1
# hourly publish snapshot for the laptop-side Pages fetcher
python3 publish.py >> data/publish.out 2>&1
