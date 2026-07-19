import json
import hashlib
from pathlib import Path

from eagle_eye.audit import AuditLedger
from eagle_eye.evidence import export_evidence_room
from eagle_eye.governance import approve_action, request_action
from eagle_eye.identity import issue_assertion, verify_assertion
from eagle_eye.ingestion import ingest_directory
from eagle_eye.kernel import build_run
from eagle_eye.policy import load_policy_bundle
from eagle_eye.posterior_engine import (
    attach_posterior_intelligence,
    build_demo_registry,
    build_demo_target,
    load_court_receipt,
)
from eagle_eye.signing import generate_demo_keypair, key_id

root = Path(__file__).resolve().parents[1]
policy_bundle = load_policy_bundle(
    root / "policies/action-governance-v1.json",
    expected_sha256="1a47ce736ef27e60fa3aea3d2abcb96aa4e1eb8b22f492c335502d0dc9f75f1f",
)
fixture = ingest_directory(root / "fixtures" / "po17")
run = build_run(fixture)
tenant_id = "tenant-demo"
identity_private_key, identity_public_key = generate_demo_keypair()
identity_issuer = "https://identity.fixture.invalid"
identity_key_id = key_id(identity_public_key)
identity_registry = {
    "trusted_issuers": [{
        "issuer": identity_issuer,
        "key_id": identity_key_id,
        "public_key_pem": identity_public_key.decode(),
        "audiences": ["eagle-eye-zenith"],
        "allowed_tenants": [tenant_id],
        "max_ttl_seconds": 900,
    }],
}

def verified_fixture_principal(subject: str, role: str, session_id: str) -> tuple[dict, dict]:
    claims = {
        "iss": identity_issuer,
        "aud": "eagle-eye-zenith",
        "sub": subject,
        "tenant_id": tenant_id,
        "roles": [role],
        "iat": 1_700_000_000,
        "exp": 1_700_000_300,
        "jti": session_id,
    }
    assertion = issue_assertion(claims, private_key=identity_private_key, public_key=identity_public_key)
    principal = verify_assertion(
        assertion,
        registry=identity_registry,
        expected_audience="eagle-eye-zenith",
        expected_tenant=tenant_id,
        now=1_700_000_010,
        revoked_jtis=set(),
    )
    receipt = {
        "verified": True,
        "subject": subject,
        "session_id": session_id,
        "issuer": identity_issuer,
        "issuer_key_id": identity_key_id,
        "assertion_sha256": hashlib.sha256(assertion.encode()).hexdigest(),
        "signed_assertion_evidence": assertion,
    }
    return principal, receipt

analyst_principal, analyst_identity = verified_fixture_principal("fixture-analyst", "analyst", "session-analyst")
approver_principal, approver_identity = verified_fixture_principal("fixture-approver", "approver", "session-approver")
governed_action = {
    **run["actions"][0],
    "tenant_id": tenant_id,
    "mode": "FIXTURE",
    "evidence_ids": run["risks"][0]["evidence_ids"],
}
request = request_action(
    governed_action,
    principal=analyst_principal,
    policy_bundle=policy_bundle,
)
approval = approve_action(
    request,
    principal=approver_principal,
    policy_bundle=policy_bundle,
)
ledger = AuditLedger(tenant_id)
ledger.append(
    "action_requested",
    actor_id=request["requester_id"],
    payload={
        "action_id": request["action_id"],
        "request_id": request["request_id"],
        "session_id": analyst_principal["session_id"],
        "policy_receipt_id": request["policy_decision"]["receipt_id"],
    },
    idempotency_key=request["request_id"],
)
ledger.append(
    "action_approved_shadow",
    actor_id=approval["approver_id"],
    payload={
        "action_id": approval["action_id"],
        "receipt_id": approval["receipt_id"],
        "external_execution": approval["external_execution"],
        "session_id": approver_principal["session_id"],
        "policy_receipt_id": approval["policy_decision"]["receipt_id"],
    },
    idempotency_key=approval["receipt_id"],
)
run["governance_harness"] = {"request": request, "approval": approval}
run["policy_bundle"] = policy_bundle
run["identity_harness"] = {
    "authority": "ephemeral_fixture_identity_not_production_idp",
    "registry": identity_registry,
    "verification_time": 1_700_000_010,
    "issuer": identity_issuer,
    "issuer_key_id": identity_key_id,
    "principals_verified": 2,
    "receipts": [analyst_identity, approver_identity],
}
run["audit_ledger"] = {
    "events": ledger.events,
    "commitment": {"tenant_id": tenant_id, "length": len(ledger.events), "head": ledger.head},
}
prior_registry = build_demo_registry()
court_receipt = load_court_receipt(
    root / "artifacts" / "prediction-court" / "latest" / "prediction-court-receipt.json")
demo_target = build_demo_target(fixture)
attach_posterior_intelligence(
    run, registry=prior_registry, target=demo_target, court_receipt=court_receipt)
out = root / "artifacts" / "runs" / "latest"
out.mkdir(parents=True, exist_ok=True)
(out / "run.json").write_text(json.dumps(run, indent=2, sort_keys=True))
private_key, public_key = generate_demo_keypair()
trust_registry = {
    "spec": "eagle-eye-trust-registry/0.1-fixture",
    "trusted_signers": [{
        "key_id": key_id(public_key),
        "public_key_pem": public_key.decode(),
        "allowed_tenants": [tenant_id],
        "authority": "ephemeral_fixture_registry_not_production_kms",
    }],
}
(out / "trust-registry.json").write_text(json.dumps(trust_registry, indent=2, sort_keys=True))
archive = export_evidence_room(
    run,
    out / "evidence-room.zip",
    private_key=private_key,
    public_key=public_key,
    tenant_id=tenant_id,
)
(out / "demo-public-key.pem").write_bytes(public_key)
print(f"RUN_ID={run['run_id']}")
print(f"MODE={run['mode']}")
print(f"PURCHASE_ORDER={fixture['purchase_orders'][0]['id']}")
print(f"COMPONENT={fixture['components'][0]['id']}")
print(f"NODES={len(run['graph']['nodes'])}")
print(f"RISKS={len(run['risks'])}")
print(f"SCENARIOS={len(run['scenarios'])}")
print(f"ACTIONS_PENDING={sum(a['status']=='pending_approval' for a in run['actions'])}")
print(f"APPROVAL_RECEIPTS={len(run['approval_receipts'])}")
print(f"POLICY_RELEASE={policy_bundle['release']}")
print(f"POLICY_BUNDLE_SHA256={policy_bundle['bundle_sha256']}")
print("IDENTITY_ASSERTIONS_VERIFIED=2")
print(f"IDENTITY_ISSUER_KEY_ID={identity_key_id}")
print(f"AUDIT_EVENTS={len(ledger.events)}")
print(f"AUDIT_HEAD={ledger.head}")
print(f"TENANT_ID={tenant_id}")
pi = run["posterior_intelligence"]
print(f"POSTERIOR_CANDIDATE={pi['candidate']}")
print(f"POSTERIOR_MODEL_RELEASE={pi['model_release']}")
print(f"PRIOR_REGISTRY_RELEASE={pi['prior_registry']['registry_release_id']}")
print(f"PRIOR_K={pi['K']}")
print(f"PRIOR_MANIFEST_SHA256={pi['prior_manifest_sha256']}")
print(f"SUPPORT_STATE={pi['governed']['support_state']}")
print(f"SHIFT_SCORE={pi['governed']['shift_score']}")
print(f"POSTERIOR_ABSTAINED={str(pi['abstained']).lower()}")
print(f"PREDICTIVE_DISTRIBUTION_COMMITMENT={pi['predictive_distribution_commitment']}")
print(f"CALIBRATION_RECEIPT_SHA256={pi['calibration_receipt_sha256']}")
print(f"COURT_RECEIPT_ID={pi['benchmark_court']['court_receipt_id']}")
print(f"RECOMMENDED_INTERVENTION={pi['recommendation']['recommended_intervention']}")
print(f"SIGNER_KEY_ID={key_id(public_key)}")
print("SIGNER=ephemeral_demo_ed25519_not_production_kms")
print(f"EVIDENCE_ROOM={archive}")
