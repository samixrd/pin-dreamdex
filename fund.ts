// Fund the PIN burner wallet on Shannon TESTNET.
// Inputs via env only (see .env.example):
//   PIN_KEY_FILE  — file containing the burner key (64-hex, 0x optional)
//   DONOR_PK      — optional 64-hex key that already holds testnet STT to transfer from.
// Nothing is funded? tUSDC is self-serve below; STT comes from the SomniaHacks Telegram faucet
// (https://t.me/+XHq0F0JXMyhmMzM0) if no donor is provided.
import { createWalletClient, createPublicClient, http, parseEther } from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { somniaShannon } from "@somnia-chain/markets-sdk/chains";
import { readFileSync } from "node:fs";

const keyFile = process.env.PIN_KEY_FILE ?? "data/pin_key.txt";
const hex = readFileSync(keyFile, "utf8").match(/[0-9a-fA-F]{64}/)?.[0];
if (!hex) throw new Error(`no 64-hex key in ${keyFile}`);
const pin = privateKeyToAccount(`0x${hex}` as `0x${string}`);
console.log("PIN address:", pin.address);

const pub = createPublicClient({ chain: somniaShannon, transport: http("https://api.infra.testnet.somnia.network") });
const STT = await pub.getBalance({ address: pin.address });
console.log("STT:", Number(STT) / 1e18);

// optional donor STT transfer (testnet-only funds)
const donorHex = process.env.DONOR_PK?.match(/[0-9a-fA-F]{64}/)?.[0];
if (donorHex && Number(STT) / 1e18 < 1) {
  const donor = privateKeyToAccount(`0x${donorHex}` as `0x${string}`);
  const w = createWalletClient({ account: donor, chain: somniaShannon, transport: http("https://api.infra.testnet.somnia.network") });
  const h = await w.sendTransaction({ to: pin.address, value: parseEther("20") });
  await pub.waitForTransactionReceipt({ hash: h });
  console.log("STT 20 tx:", h);
} else if (Number(STT) / 1e18 < 1) {
  console.log("STT low and no DONOR_PK — request STT from the SomniaHacks Telegram faucet.");
}

const ercAbi = [
  { type: "function", name: "balanceOf", stateMutability: "view", inputs: [{ name: "a", type: "address" }], outputs: [{ type: "uint256" }] },
  { type: "function", name: "faucet", stateMutability: "nonpayable", inputs: [{ name: "amount", type: "uint256" }], outputs: [] },
] as const;
const TUSDC = "0x70a86D8842FB63C4Ad2b7cdddF530eBf1BB25d8E";
let bal = await pub.readContract({ address: TUSDC, abi: ercAbi, functionName: "balanceOf", args: [pin.address] }) as bigint;
console.log("tUSDC:", Number(bal) / 1e6);
if (Number(bal) < 5000) {
  const w = createWalletClient({ account: pin, chain: somniaShannon, transport: http("https://api.infra.testnet.somnia.network") });
  const h = await w.writeContract({ address: TUSDC, abi: ercAbi, functionName: "faucet", args: [10_000n * 10n ** 6n] });
  const rc = await pub.waitForTransactionReceipt({ hash: h });
  console.log("faucet tx:", h, "status:", rc.status);
  bal = await pub.readContract({ address: TUSDC, abi: ercAbi, functionName: "balanceOf", args: [pin.address] }) as bigint;
  console.log("tUSDC after:", Number(bal) / 1e6);
}
