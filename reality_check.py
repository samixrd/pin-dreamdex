# Reality check: take tx hashes from our ledger, fetch receipts from the PUBLIC Somnia RPC.
# If these transactions exist on-chain with our wallet as sender, the dashboard is real.
import json, subprocess, sys

RPC = "https://api.infra.testnet.somnia.network"
PIN = "0x27633fEC5EdA3F0298BfFa24018dAf54dd18197A"

def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    r = subprocess.run(["curl", "-s", "-m", "25", RPC, "-H", "Content-Type: application/json", "-d", body],
                       capture_output=True, text=True)
    return json.loads(r.stdout).get("result")

led = [json.loads(l) for l in open("data/live_ledger.jsonl", encoding="utf-8") if l.strip()]
txs = [e for e in led if e.get("tx") and str(e["tx"]).startswith("0x") and len(str(e["tx"])) > 40]
print(f"ledger events: {len(led)} | with tx hash: {len(txs)}")

# balance on-chain right now
bal = rpc("eth_getBalance", [PIN, "latest"])
print(f"PIN STT on-chain: {int(bal,16)/1e18:.4f}")
tusdc = rpc("eth_call", [{"to": "0x70a86D8842FB63C4Ad2b7cdddF530eBf1BB25d8E",
    "data": "0x70a08231000000000000000000000000" + PIN[2:].lower()}, "latest"])
print(f"PIN tUSDC on-chain: {int(tusdc,16)/1e6:.2f}")

import datetime as dt
for e in txs[-6:]:
    rc = rpc("eth_getTransactionReceipt", [e["tx"]])
    if not rc:
        print("MISSING:", e["tx"]); continue
    tx = rpc("eth_getTransactionByHash", [e["tx"]])
    t = dt.datetime.utcfromtimestamp(int(tx["blockNumber"], 16) and int(rc.get("blockNumber","0x0"),16) or 0)
    print(f"{e['ev']:8} {e['tx'][:20]}…  block={int(rc['blockNumber'],16):,}  from={tx['from'][:12]}…  status={rc['status']}  gas={int(rc['gasUsed'],16):,}")
