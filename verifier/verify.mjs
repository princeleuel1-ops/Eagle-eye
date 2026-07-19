import crypto from "node:crypto";
import fs from "node:fs";
import { execFileSync } from "node:child_process";

const args = process.argv.slice(2);
const archive = args[0];
const option = name => {
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : undefined;
};
const trustRegistryPath = option("--trust-registry");
const expectedTenant = option("--expected-tenant");
if (!archive) throw new Error("usage: node verifier/verify.mjs <archive.zip> [--trust-registry path] [--expected-tenant id]");
const readEntry = name => execFileSync("unzip", ["-p", archive, name]);
const canonicalize = value => {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonicalize(value[key])]));
  return value;
};
const canonical = value => Buffer.from(JSON.stringify(canonicalize(value)));
const sha256 = data => crypto.createHash("sha256").update(data).digest("hex");
// Cross-runtime numeric commitment discipline (mirrors posterior_engine.quantize_micro):
// integers pass through; non-integer numbers map to floor(x*1e6 + 0.5).
const quantizeMicro = value => {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") return Number.isInteger(value) ? value : Math.floor(value * 1e6 + 0.5);
  if (Array.isArray(value)) return value.map(quantizeMicro);
  if (typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, quantizeMicro(v)]));
  throw new Error(`unsupported type for quantization: ${typeof value}`);
};
const SUPPORT_STATES = new Set(["strong", "moderate", "weak", "unsupported"]);
const keyId = pem => {
  const der = crypto.createPublicKey(pem).export({type: "spki", format: "der"});
  return `ed25519:${sha256(der)}`;
};

try {
  const runBytes = readEntry("run.json");
  const manifest = JSON.parse(readEntry("manifest.json").toString("utf8"));
  const run = JSON.parse(runBytes.toString("utf8"));
  const body = {...manifest}; delete body.signature;
  const embeddedKey = manifest.signature.public_key_pem;
  const signature = Buffer.from(manifest.signature.value_base64, "base64");
  const verifiedSignature = crypto.verify(null, canonical(body), embeddedKey, signature);
  const hashes = sha256(runBytes) === manifest.files["run.json"].sha256;
  const coherent = run.run_id === manifest.run_id && run.mode === manifest.mode;
  let signerTrusted = null;
  let tenantVerified = expectedTenant ? manifest.tenant_id === expectedTenant : null;
  if (trustRegistryPath) {
    const registry = JSON.parse(fs.readFileSync(trustRegistryPath, "utf8"));
    const computedKeyId = keyId(embeddedKey);
    const signer = registry.trusted_signers.find(item =>
      item.key_id === manifest.signer_key_id &&
      item.key_id === computedKeyId &&
      item.public_key_pem === embeddedKey
    );
    signerTrusted = Boolean(signer);
    tenantVerified = Boolean(
      signer && signer.allowed_tenants.includes(manifest.tenant_id) &&
      (!expectedTenant || manifest.tenant_id === expectedTenant)
    );
  }
  let auditVerified = null;
  if (run.audit_ledger) {
    const {events, commitment} = run.audit_ledger;
    let previous = "0".repeat(64);
    const idempotencyKeys = new Set();
    auditVerified = events.length === commitment.length && commitment.tenant_id === manifest.tenant_id;
    for (let index = 0; auditVerified && index < events.length; index += 1) {
      const event = events[index];
      const eventBody = {...event}; delete eventBody.event_hash;
      const computedHash = sha256(canonical(eventBody));
      auditVerified = event.sequence === index + 1 &&
        event.tenant_id === manifest.tenant_id &&
        event.previous_hash === previous &&
        !idempotencyKeys.has(event.idempotency_key) &&
        event.event_hash === computedHash;
      idempotencyKeys.add(event.idempotency_key);
      previous = event.event_hash;
    }
    auditVerified = auditVerified && previous === commitment.head;
  }
  let identityVerified = null;
  if (run.identity_harness) {
    const identity = run.identity_harness;
    identityVerified = identity.receipts.length === identity.principals_verified;
    for (const receipt of identity.receipts) {
      const token = receipt.signed_assertion_evidence;
      const parts = token.split(".");
      if (parts.length !== 3) { identityVerified = false; break; }
      const header = JSON.parse(Buffer.from(parts[0], "base64url").toString("utf8"));
      const claims = JSON.parse(Buffer.from(parts[1], "base64url").toString("utf8"));
      const issuer = identity.registry.trusted_issuers.find(item =>
        item.issuer === claims.iss && item.key_id === header.kid
      );
      const signatureValid = Boolean(issuer) && crypto.verify(
        null,
        Buffer.from(`${parts[0]}.${parts[1]}`),
        issuer.public_key_pem,
        Buffer.from(parts[2], "base64url")
      );
      const digestValid = sha256(Buffer.from(token)) === receipt.assertion_sha256;
      const claimValid = Boolean(issuer) &&
        header.alg === "EdDSA" && header.typ === "EE-SESSION" &&
        keyId(issuer.public_key_pem) === header.kid &&
        issuer.audiences.includes(claims.aud) && claims.aud === "eagle-eye-zenith" &&
        issuer.allowed_tenants.includes(claims.tenant_id) && claims.tenant_id === manifest.tenant_id &&
        claims.exp > identity.verification_time && claims.iat <= identity.verification_time + 60 &&
        claims.exp > claims.iat && claims.exp - claims.iat <= issuer.max_ttl_seconds &&
        claims.sub === receipt.subject && claims.jti === receipt.session_id;
      identityVerified = identityVerified && signatureValid && digestValid && claimValid;
    }
  }
  let policyVerified = null;
  let policyBundleVerified = null;
  if (run.governance_harness && run.identity_harness && run.policy_bundle) {
    const bundle = run.policy_bundle;
    const bundleBody = {...bundle}; delete bundleBody.bundle_sha256;
    policyBundleVerified = sha256(canonical(bundleBody)) === bundle.bundle_sha256;
    const {request, approval} = run.governance_harness;
    const identities = Object.fromEntries(run.identity_harness.receipts.map(item => [item.subject, item]));
    const requestResource = {
      action_id: request.action_id, tenant_id: request.tenant_id, mode: request.mode,
      status: "pending_approval", requester_id: null, evidence_ids: request.evidence_ids,
    };
    const approvalResource = {
      action_id: request.action_id, tenant_id: request.tenant_id, mode: request.mode,
      status: request.status, requester_id: request.requester_id, evidence_ids: request.evidence_ids,
    };
    const verifyPolicy = (decision, operation, principalId, sessionId, tenantId, resource) => {
      const body = {...decision}; delete body.receipt_id;
      const expectedReceipt = `policy-${sha256(canonical(body)).slice(0, 12)}`;
      return decision.policy_id === bundle.policy_id &&
        decision.policy_release === bundle.release &&
        decision.policy_bundle_sha256 === bundle.bundle_sha256 &&
        decision.effect === "ALLOW" && decision.reasons.length === 0 &&
        decision.operation === operation && decision.principal_id === principalId &&
        decision.session_id === sessionId && decision.tenant_id === tenantId &&
        decision.resource_digest === sha256(canonical(resource)) &&
        decision.receipt_id === expectedReceipt;
    };
    policyVerified = policyBundleVerified && verifyPolicy(
      request.policy_decision, "request_action", request.requester_id,
      identities[request.requester_id]?.session_id, request.tenant_id, requestResource
    ) && verifyPolicy(
      approval.policy_decision, "approve_action", approval.approver_id,
      identities[approval.approver_id]?.session_id, approval.tenant_id, approvalResource
    ) && run.audit_ledger.events[0].payload.policy_receipt_id === request.policy_decision.receipt_id
      && run.audit_ledger.events[1].payload.policy_receipt_id === approval.policy_decision.receipt_id;
  }
  let posteriorVerified = null;
  let posteriorError = null;
  if (run.posterior_intelligence) {
    try {
      const pi = run.posterior_intelligence;
      const fail = reason => { posteriorVerified = false; posteriorError = reason; };
      const sel = pi.selection_receipt;
      const selBody = {...sel}; delete selBody.receipt_sha256;
      if (sha256(canonical(selBody)) !== sel.receipt_sha256) fail("selection receipt hash mismatch");
      else if (sel.registry_manifest_sha256 !== pi.prior_registry.manifest_sha256) fail("selection receipt bound to a different registry");
      else if (pi.K !== sel.included_prior_task_ids.length) fail("K does not match included prior task count");
      else if (pi.abstained !== (pi.interventions === null)) fail("abstention flag inconsistent with interventions payload");
      else {
        const basis = {
          candidate: pi.candidate,
          model_release: pi.model_release,
          prior_manifest_sha256: pi.prior_manifest_sha256,
          as_of_cutoff: pi.as_of_cutoff,
          abstained: pi.abstained,
          interventions: pi.interventions,
        };
        const expectedSet = pi.interventions ? Object.keys(pi.interventions).sort() : [];
        const governed = pi.governed;
        const shift = governed.shift_score;
        const expectedManifest = {
          predictive_distribution_commitment: pi.predictive_distribution_commitment,
          intervention_set_commitment: pi.intervention_set_commitment,
          prior_manifest_sha256: pi.prior_manifest_sha256,
          prior_registry_manifest_sha256: pi.prior_registry.manifest_sha256,
          calibration_receipt_sha256: pi.calibration_receipt_sha256,
          court_receipt_id: pi.benchmark_court.court_receipt_id,
          K: pi.K,
          context_length: pi.context_length,
          support_state: governed.support_state,
          shift_score_micro: shift === null || shift === undefined ? null : Math.floor(shift * 1e6 + 0.5),
          abstained: pi.abstained,
          model_release: pi.model_release,
        };
        if (sha256(canonical(quantizeMicro(basis))) !== pi.predictive_distribution_commitment) fail("predictive distribution commitment mismatch");
        else if (sha256(canonical(expectedSet)) !== pi.intervention_set_commitment) fail("intervention set commitment mismatch");
        else if (sha256(canonical(pi.calibration_receipt)) !== pi.calibration_receipt_sha256) fail("calibration receipt hash mismatch");
        else if (pi.calibration_receipt.court_receipt_id !== pi.benchmark_court.court_receipt_id) fail("calibration receipt bound to a different court");
        else if (!SUPPORT_STATES.has(governed.support_state)) fail("unknown support state");
        else if (sha256(canonical(manifest.posterior_commitments ?? null)) !== sha256(canonical(expectedManifest))) fail("manifest posterior commitments do not match run content");
        else posteriorVerified = true;
      }
    } catch (error) {
      posteriorVerified = false;
      posteriorError = `posterior block malformed: ${error.message}`;
    }
  } else if (manifest.posterior_commitments !== undefined && manifest.posterior_commitments !== null) {
    posteriorVerified = false;
    posteriorError = "manifest commits to a posterior block absent from run.json";
  }
  const trustOk = signerTrusted !== false && tenantVerified !== false;
  const result = {
    verified: hashes && coherent && verifiedSignature && trustOk && auditVerified !== false && identityVerified !== false && policyVerified !== false && posteriorVerified !== false,
    hashes_verified: hashes,
    manifest_coherent: coherent,
    signature_verified: verifiedSignature,
    signer_trusted: signerTrusted,
    tenant_verified: tenantVerified,
    audit_verified: auditVerified,
    identity_verified: identityVerified,
    policy_verified: policyVerified,
    policy_bundle_verified: policyBundleVerified,
    posterior_verified: posteriorVerified,
    posterior_error: posteriorError,
    tenant_id: manifest.tenant_id,
    signer_key_id: manifest.signer_key_id,
    run_id: run.run_id,
  };
  console.log(JSON.stringify(result));
  console.log(`NODE_EVIDENCE_ROOM_VERIFIED=${result.verified}`);
  process.exit(result.verified ? 0 : 1);
} catch (error) {
  console.log(JSON.stringify({verified:false, signature_verified:false, signer_trusted:false, tenant_verified:false, reason:String(error.message)}));
  process.exit(1);
}
