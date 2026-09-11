# Kill every node/python child whose command line contains these script names,
# EXCEPT nothing — PIN stack fully restarts after. Prints what it kills.
import subprocess, sys
NAMES = ["live.ts", "collector.ts", "paper.py", "backfill.ts", "watchdog.sh"]
out = subprocess.run(["powershell", "-NoProfile", "-Command",
    "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'live\\.ts|collector\\.ts|paper\\.py|backfill\\.ts|watchdog\\.sh' -and $_.Name -notin @('powershell.exe','pwsh.exe') -and $_.CommandLine -notmatch 'pinkill' } | ForEach-Object { \"$($_.ProcessId)`t$($_.Name)`t$($_.CommandLine.Substring(0,[Math]::Min(120,$_.CommandLine.Length)))\" }"],
    capture_output=True, text=True)
lines = [l for l in out.stdout.splitlines() if l.strip()]
print("matches:", len(lines))
pids = []
for l in lines:
    print(" ", l[:150])
    try: pids.append(int(l.split("\t")[0]))
    except: pass
if "--dry" in sys.argv: sys.exit(0)
for p in pids:
    subprocess.run(["taskkill", "/PID", str(p), "/F", "/T"], capture_output=True)
print("killed", len(pids))
