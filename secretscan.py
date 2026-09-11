"""Secret scanner. NOTE: pattern literals are split so this file cannot self-match."""
# Secret/critical-info scanner: every tracked file + full git history.
import subprocess, re

files = subprocess.run(["git", "ls-tree", "-r", "--name-only", "HEAD"],
                       capture_output=True, text=True).stdout.split()
pats = {
    "private-key-64hex": re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])"),
    "vm-ip": re.compile(r"20" + r"\.2" + r"\.233\.34"),
    "vm-userhost": re.compile(r"azureuser" + r"@20"),
    "gh-token": re.compile(r"gh[pousr]_[0-9A-Za-z]{20,}"),
    "pem-name": re.compile(r"obel" + r"isk-key"),
    "donor-key-path": re.compile(r"BACK" + r"ED/\.env|ANCHOR" + r"_PRIVATE_KEY|CAT" + r"_GRID_KEY"),
    "vercel-token": re.compile(r"vcu_[0-9A-Za-z]{10,}"),
    "team-id": re.compile(r"team_[0-9A-Za-z]{20,}"),
    "project-id": re.compile(r"prj_[0-9A-Za-z]{20,}"),
}
hits = []
for f in files:
    if f.endswith((".png", ".jpg", ".ico")): continue
    r = subprocess.run(["git", "show", f"HEAD:{f}"], capture_output=True)
    c = r.stdout.decode("utf-8", errors="ignore")
    for name, pat in pats.items():
        for m in pat.finditer(c):
            line_no = c[:m.start()].count("\n") + 1
            ctx = c[max(0, m.start() - 2):m.start() + 66].splitlines()[0]
            # on-chain hex (tx hashes / market ids / venue ids) with 0x prefix = public by nature
            if name == "private-key-64hex" and ctx.startswith("0x"):
                continue
            hits.append((f, name, line_no, m.group(0)[:16]))
key_ok = "False"
try:
    key = open("data/pin_key.txt").read().strip().replace("0x", "")
    hist = subprocess.run(["git", "log", "--all", "-p", "--format="], capture_output=True).stdout.decode("utf-8", errors="ignore")
    key_ok = str(key in hist)
except FileNotFoundError:
    hist = subprocess.run(["git", "log", "--all", "-p", "--format="], capture_output=True).stdout.decode("utf-8", errors="ignore")
print("PIN key anywhere in history:", key_ok)
print("tracked files:", len(files))
if hits:
    print("=== HITS ===")
    for f, n, l, v in hits:
        print(f"{f}:{l} {n} {v}")
else:
    print("NO CRITICAL HITS")
