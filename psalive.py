# Print one line per PIN service: <name> <0|1>. For bash watchdog; immune to its own process.
import subprocess
out = subprocess.run(["powershell", "-NoProfile", "-Command",
    "Get-CimInstance Win32_Process | Where-Object { ($_.Name -match 'node.exe|python.exe' -and $_.CommandLine -match 'live\\.ts|collector\\.ts|paper\\.py|backfill\\.ts|dashboard\\.py') -or ($_.Name -match 'bash.exe' -and $_.CommandLine -match 'watchdog\\.sh' -and $_.CommandLine -notmatch 'psalive') } | ForEach-Object { $_.CommandLine }"],
    capture_output=True, text=True).stdout
names = {"collector": 0, "paper": 0, "live": 0, "backfill": 0, "watchdog": 0}
for l in out.splitlines():
    for k, pat in (("collector", "collector.ts"), ("paper", "paper.py"), ("live", "live.ts"),
                   ("backfill", "backfill.ts"), ("watchdog", "watchdog.sh")):
        if pat in l: names[k] += 1
for k, v in names.items():
    print(k, v)
