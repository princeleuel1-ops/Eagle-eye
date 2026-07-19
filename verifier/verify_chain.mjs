// Node parity verifier for Ed25519-signed anchored chains (audit blocker G).
// usage: node verifier/verify_chain.mjs <replay_bundle.json> <chain_name> <expected_tenant>
import crypto from "node:crypto";
import fs from "node:fs";
const canonicalize = v => Array.isArray(v) ? v.map(canonicalize)
  : (v && typeof v === "object"
     ? Object.fromEntries(Object.keys(v).sort().map(k => [k, canonicalize(v[k])])) : v);
const canonical = v => Buffer.from(JSON.stringify(canonicalize(v)));
const sha256 = d => crypto.createHash("sha256").update(d).digest("hex");
const keyId = pem => `ed25519:${sha256(crypto.createPublicKey(pem).export({type: "spki", format: "der"}))}`;
const [bundlePath, chainName, expectedTenant] = process.argv.slice(2);
const bundle = JSON.parse(fs.readFileSync(bundlePath, "utf8"));
const {rows, anchor} = bundle.chains[chainName];
const registry = bundle.signer_registry;
const fail = reason => { console.log(JSON.stringify({verified: false, reason})); process.exit(1); };
const signer = registry.trusted_signers.find(s => s.key_id === anchor.signer_key_id);
if (!signer) fail("unknown signer");
if (keyId(signer.public_key_pem) !== anchor.signer_key_id) fail("signer registry fingerprint mismatch");
const anchorBody = {...anchor}; delete anchorBody.anchor_signature_b64;
if (!crypto.verify(null, canonical(anchorBody), signer.public_key_pem,
                   Buffer.from(anchor.anchor_signature_b64, "base64"))) fail("forged anchor signature");
if (anchor.tenant_id !== expectedTenant) fail("wrong tenant");
// V5 parity: bind the anchor's signed chain_id/run_id (cross-chain confusion).
const anchorChainId = anchor.chain_id, anchorRunId = anchor.run_id;
if (rows.length !== anchor.length) fail("chain length does not match external anchor");
let head = "0".repeat(64);
for (let i = 0; i < rows.length; i += 1) {
  const row = rows[i];
  const body = {...row}; delete body.row_hash; delete body.signature_b64; delete body.signer_key_id;
  if (row.sequence !== i + 1) fail(`sequence break at ${i + 1}`);
  if (row.previous_hash !== head) fail(`linkage break at ${row.sequence}`);
  if (sha256(canonical(body)) !== row.row_hash) fail(`row hash mismatch at ${row.sequence}`);
  if (row.signer_key_id !== anchor.signer_key_id) fail(`signer substitution at ${row.sequence}`);
  if (row.chain_id !== anchorChainId) fail(`chain_id confusion at ${row.sequence}`);
  if (row.run_id !== anchorRunId) fail(`run_id confusion at ${row.sequence}`);
  if (!crypto.verify(null, Buffer.from(row.row_hash), signer.public_key_pem,
                     Buffer.from(row.signature_b64, "base64"))) fail(`forged signature at ${row.sequence}`);
  if (row.tenant_id !== expectedTenant) fail(`tenant mismatch at ${row.sequence}`);
  head = row.row_hash;
}
if (head !== anchor.head) fail("terminal head does not match external anchor");
console.log(JSON.stringify({verified: true, chain: chainName, length: rows.length, head,
                            chain_id: anchorChainId, run_id: anchorRunId}));
