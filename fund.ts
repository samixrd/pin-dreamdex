// 1) generate dedicated PIN key; 2) mainnet balance check of donor candidates (never spend
// mainnet funds); 3) donor -> PIN STT transfer on TESTNET ONLY (chainId 50312); 4) public
// tUSDC faucet call by PIN key (docs: faucet(uint256) credits msg.sender, cap 10k); 5) verify.
import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";
import { createPublicClient, createWalletClient, http, parseEther } from "viem";
import { somniaShannon } from "@somnia-chain/markets-sdk/chains";
import { somniaMainnet } from "@somnia-chain/markets-sdk/chains";
import { readFileSync, writeFileSync, existsSync } from "node:fs";

const KEYF = "data/pin_key.txt";
let pk: string;
if (existsSync(KEYF)) pk = readFileSync(KEYF, "utf8").trim();
else { pk = generatePrivateKey(); writeFileSync(KEYF, pk, { mode: 0o600 }); console.log("generated new PIN key"); }
const pin = privateKeyToAccount(pk as `0x${string}`);
console.log("PIN address:", pin.address);

const rpc = "https://api.infra.testnet.somnia.network";
const pub = createPublicClient({ chain: somniaShannon, transport: http(rpc) });
const pubMain = createPublicClient({ chain: somniaMainnet, transport: http("https://api.infra.mainnet.somnia.network") });

// donor = BACKED anchor, ONLY if its MAINNET balance is zero
const anchorPk = readFileSync("D:/BACKED/.env", "utf8").match(/ANCHOR_PRIVATE_KEY="?([0x0-9a-fA-F]{64})"?/)?.[1];
const anchor = privateKeyToAccount(`0x${anchorPk}` as `0x${string}`);
const mBal = await pubMain.getBalance({ address: anchor.address });
console.log("anchor MAINNET bal:", Number(mBal) / 1e18, "SOMI");
if (mBal > 0n) { console.log("REFUSING: donor holds mainnet funds"); process.exit(2); }

const tBalPin = await pub.getBalance({ address: pin.address });
console.log("PIN testnet STT:", Number(tBalPin) / 1e18);
if (Number(tBalPin) / 1e18 < 1) {
  const w = createWalletClient({ account: anchor, chain: somniaShannon, transport: http(rpc) });
  const h = await w.sendTransaction({ to: pin.address, value: parseEther("20"), chain: somniaShannon });
  console.log("STT 20 tx:", h);
  await pub.waitForTransactionReceipt({ hash: h });
}
// faucet tUSDC directly by PIN key (public faucet, per docs/contracts-and-addresses)
const ercAbi = [
  { type: "function", name: "balanceOf", stateMutability: "view", inputs: [{ name: "a", type: "address" }], outputs: [{ type: "uint256" }] },
  { type: "function", name: "faucet", stateMutability: "nonpayable", inputs: [{ name: "amount", type: "uint256" }], outputs: [] },
] as const;
const TUSDC = "0x70a86D8842FB63C4Ad2b7cdddF530eBf1BB25d8E";
let bal = await pub.readContract({ address: TUSDC, abi: ercAbi, functionName: "balanceOf", args: [pin.address] }) as bigint;
console.log("PIN tUSDC:", Number(bal) / 1e6);
if (Number(bal) < 5000) {
  const w = createWalletClient({ account: pin, chain: somniaShannon, transport: http(rpc) });
  try {
    const h = await w.writeContract({ address: TUSDC, abi: ercAbi, functionName: "faucet", args: [10_000n * 10n ** 6n], chain: somniaShannon });
    const rc = await pub.waitForTransactionReceipt({ hash: h });
    console.log("faucet tx:", h, "status:", rc.status);
  } catch (e: any) { console.log("faucet err:", String(e?.message ?? e).slice(0, 200)); }
  bal = await pub.readContract({ address: TUSDC, abi: ercAbi, functionName: "balanceOf", args: [pin.address] }) as bigint;
  console.log("PIN tUSDC after:", Number(bal) / 1e6);
}
console.log("STT now:", Number(await pub.getBalance({ address: pin.address })) / 1e18);
