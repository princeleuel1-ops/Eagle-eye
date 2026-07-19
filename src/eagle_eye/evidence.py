from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import zipfile
from typing import Any

from .audit import AuditError, verify_chain
from .identity import IdentityError, verify_assertion
from .policy import verify_policy_decision
from .signing import key_id, sign, verify


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


SUPPORT_STATES = {"strong", "moderate", "weak", "unsupported"}


def _posterior_manifest_commitments(pi: dict[str, Any]) -> dict[str, Any]:
    governed = pi["governed"]
    shift = governed.get("shift_score")
    return {
        "predictive_distribution_commitment": pi["predictive_distribution_commitment"],
        "intervention_set_commitment": pi["intervention_set_commitment"],
        "prior_manifest_sha256": pi["prior_manifest_sha256"],
        "prior_registry_manifest_sha256": pi["prior_registry"]["manifest_sha256"],
        "calibration_receipt_sha256": pi["calibration_receipt_sha256"],
        "court_receipt_id": pi["benchmark_court"]["court_receipt_id"],
        "K": pi["K"],
        "context_length": pi["context_length"],
        "support_state": governed["support_state"],
        "shift_score_micro": None if shift is None else int(shift * 1_000_000 + 0.5),
        "abstained": pi["abstained"],
        "model_release": pi["model_release"],
    }


def _verify_posterior_intelligence(run: dict[str, Any], manifest: dict[str, Any]) -> tuple[bool, str | None]:
    """Recompute every posterior commitment from run.json content. Fail closed."""
    from .posterior_engine import commitment_hash  # local import: avoids cycle at module load

    pi = run["posterior_intelligence"]
    sel = pi["selection_receipt"]
    sel_body = {key: value for key, value in sel.items() if key != "receipt_sha256"}
    if _sha256(_canonical(sel_body)) != sel["receipt_sha256"]:
        return False, "selection receipt hash mismatch"
    if sel["registry_manifest_sha256"] != pi["prior_registry"]["manifest_sha256"]:
        return False, "selection receipt bound to a different registry"
    if pi["K"] != len(sel["included_prior_task_ids"]):
        return False, "K does not match included prior task count"
    abstained = pi["abstained"]
    interventions = pi["interventions"]
    if abstained != (interventions is None):
        return False, "abstention flag inconsistent with interventions payload"
    basis = {
        "candidate": pi["candidate"],
        "model_release": pi["model_release"],
        "prior_manifest_sha256": pi["prior_manifest_sha256"],
        "as_of_cutoff": pi["as_of_cutoff"],
        "abstained": abstained,
        "interventions": interventions,
    }
    if commitment_hash(basis) != pi["predictive_distribution_commitment"]:
        return False, "predictive distribution commitment mismatch"
    expected_set = sorted(interventions.keys()) if interventions else []
    if _sha256(_canonical(expected_set)) != pi["intervention_set_commitment"]:
        return False, "intervention set commitment mismatch"
    if _sha256(_canonical(pi["calibration_receipt"])) != pi["calibration_receipt_sha256"]:
        return False, "calibration receipt hash mismatch"
    if pi["calibration_receipt"]["court_receipt_id"] != pi["benchmark_court"]["court_receipt_id"]:
        return False, "calibration receipt bound to a different court"
    if pi["governed"]["support_state"] not in SUPPORT_STATES:
        return False, "unknown support state"
    expected_manifest = _posterior_manifest_commitments(pi)
    if manifest.get("posterior_commitments") != expected_manifest:
        return False, "manifest posterior commitments do not match run content"
    return True, None


def export_evidence_room(
    run: dict[str, Any],
    destination: Path,
    *,
    private_key: bytes | None = None,
    public_key: bytes | None = None,
    tenant_id: str = "fixture-default",
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    run_bytes = json.dumps(run, indent=2, sort_keys=True).encode()
    manifest: dict[str, Any] = {
        "spec": "eagle-eye-evidence-room/0.2-fixture",
        "run_id": run["run_id"],
        "mode": run["mode"],
        "tenant_id": tenant_id,
        "files": {"run.json": {"sha256": _sha256(run_bytes), "bytes": len(run_bytes)}},
        "integrity_scope": "Archive integrity and signer possession; factual authority is reported separately",
        "source_authority": "synthetic_fixture",
        "signature_state": "UNSIGNED" if private_key is None else "DEMO_ED25519",
    }
    if "posterior_intelligence" in run:
        # Posterior commitments ride inside the signed manifest body so the
        # probabilistic output is bound to signer, tenant, and audit scope.
        manifest["posterior_commitments"] = _posterior_manifest_commitments(run["posterior_intelligence"])
    if (private_key is None) != (public_key is None):
        raise ValueError("private_key and public_key must be supplied together")
    if private_key is not None and public_key is not None:
        manifest["signer_key_id"] = key_id(public_key)
        signature = sign(_canonical(manifest), private_key)
        manifest["signature"] = {
            "algorithm": "Ed25519",
            "public_key_pem": public_key.decode(),
            "value_base64": base64.b64encode(signature).decode(),
            "key_authority": "ephemeral_demo_key_not_production_kms",
        }
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode()
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("run.json", run_bytes)
        zf.writestr("manifest.json", manifest_bytes)
    return destination


def verify_evidence_room(
    archive: Path,
    *,
    trust_registry: Path | None = None,
    expected_tenant: str | None = None,
) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(archive, "r") as zf:
            names = set(zf.namelist())
            if names != {"run.json", "manifest.json"}:
                return {"verified": False, "hashes_verified": False, "reason": "unexpected archive entries"}
            manifest = json.loads(zf.read("manifest.json"))
            run_bytes = zf.read("run.json")
            expected = manifest["files"]["run.json"]["sha256"]
            hashes = _sha256(run_bytes) == expected
            run = json.loads(run_bytes)
            coherent = run.get("run_id") == manifest.get("run_id") and run.get("mode") == manifest.get("mode")
            signature_block = manifest.get("signature")
            signature_verified = False
            if signature_block:
                body = dict(manifest)
                body.pop("signature")
                signature_verified = verify(
                    _canonical(body),
                    base64.b64decode(signature_block["value_base64"]),
                    signature_block["public_key_pem"].encode(),
                )
            required_signature = manifest.get("signature_state") != "UNSIGNED"
            signer_trusted: bool | None = None
            tenant_verified: bool | None = None
            if trust_registry is not None:
                registry = json.loads(trust_registry.read_text())
                embedded_key = signature_block["public_key_pem"].encode() if signature_block else b""
                computed_key_id = key_id(embedded_key) if embedded_key else None
                declared_key_id = manifest.get("signer_key_id")
                signer = next(
                    (
                        item
                        for item in registry.get("trusted_signers", [])
                        if item.get("key_id") == declared_key_id == computed_key_id
                        and item.get("public_key_pem", "").encode() == embedded_key
                    ),
                    None,
                )
                signer_trusted = signer is not None
                tenant_verified = bool(
                    signer
                    and manifest.get("tenant_id") in signer.get("allowed_tenants", [])
                    and (expected_tenant is None or manifest.get("tenant_id") == expected_tenant)
                )
            elif expected_tenant is not None:
                tenant_verified = manifest.get("tenant_id") == expected_tenant
            audit_verified: bool | None = None
            audit_error: str | None = None
            if "audit_ledger" in run:
                audit = run["audit_ledger"]
                commitment = audit["commitment"]
                try:
                    verify_chain(
                        audit["events"],
                        expected_tenant=manifest.get("tenant_id"),
                        expected_head=commitment["head"],
                        expected_length=commitment["length"],
                    )
                    audit_verified = commitment.get("tenant_id") == manifest.get("tenant_id")
                    if not audit_verified:
                        audit_error = "audit commitment tenant does not match manifest tenant"
                except AuditError as exc:
                    audit_verified = False
                    audit_error = str(exc)
            identity_verified: bool | None = None
            identity_error: str | None = None
            if "identity_harness" in run:
                identity = run["identity_harness"]
                try:
                    for receipt in identity["receipts"]:
                        assertion = receipt["signed_assertion_evidence"]
                        if _sha256(assertion.encode()) != receipt["assertion_sha256"]:
                            raise IdentityError("identity assertion digest is invalid")
                        principal = verify_assertion(
                            assertion,
                            registry=identity["registry"],
                            expected_audience="eagle-eye-zenith",
                            expected_tenant=manifest.get("tenant_id"),
                            now=identity["verification_time"],
                            revoked_jtis=set(),
                        )
                        if principal["id"] != receipt["subject"] or principal["session_id"] != receipt["session_id"]:
                            raise IdentityError("identity receipt does not match signed assertion")
                    identity_verified = len(identity["receipts"]) == identity["principals_verified"]
                except (IdentityError, KeyError, TypeError) as exc:
                    identity_verified = False
                    identity_error = str(exc)
            policy_verified: bool | None = None
            policy_bundle_verified: bool | None = None
            if "governance_harness" in run and "identity_harness" in run and "policy_bundle" in run:
                bundle = run["policy_bundle"]
                bundle_body = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
                policy_bundle_verified = _sha256(_canonical(bundle_body)) == bundle.get("bundle_sha256")
                governance = run["governance_harness"]
                request = governance["request"]
                approval = governance["approval"]
                identities = {item["subject"]: item for item in run["identity_harness"]["receipts"]}
                request_resource = {
                    "action_id": request["action_id"],
                    "tenant_id": request["tenant_id"],
                    "mode": request["mode"],
                    "status": "pending_approval",
                    "requester_id": None,
                    "evidence_ids": request["evidence_ids"],
                }
                approval_resource = {
                    "action_id": request["action_id"],
                    "tenant_id": request["tenant_id"],
                    "mode": request["mode"],
                    "status": request["status"],
                    "requester_id": request["requester_id"],
                    "evidence_ids": request["evidence_ids"],
                }
                request_identity = identities.get(request["requester_id"], {})
                approval_identity = identities.get(approval["approver_id"], {})
                events = run["audit_ledger"]["events"]
                policy_verified = bool(
                    policy_bundle_verified
                    and verify_policy_decision(
                        request["policy_decision"],
                        operation="request_action",
                        principal_id=request["requester_id"],
                        session_id=request_identity.get("session_id"),
                        tenant_id=request["tenant_id"],
                        resource=request_resource,
                        bundle=bundle,
                    )
                    and verify_policy_decision(
                        approval["policy_decision"],
                        operation="approve_action",
                        principal_id=approval["approver_id"],
                        session_id=approval_identity.get("session_id"),
                        tenant_id=approval["tenant_id"],
                        resource=approval_resource,
                        bundle=bundle,
                    )
                    and events[0]["payload"].get("policy_receipt_id") == request["policy_decision"]["receipt_id"]
                    and events[1]["payload"].get("policy_receipt_id") == approval["policy_decision"]["receipt_id"]
                )
            posterior_verified: bool | None = None
            posterior_error: str | None = None
            if "posterior_intelligence" in run:
                try:
                    posterior_verified, posterior_error = _verify_posterior_intelligence(run, manifest)
                except (KeyError, TypeError, ValueError) as exc:
                    posterior_verified = False
                    posterior_error = f"posterior block malformed: {exc}"
            elif manifest.get("posterior_commitments") is not None:
                posterior_verified = False
                posterior_error = "manifest commits to a posterior block absent from run.json"
            trust_ok = signer_trusted is not False and tenant_verified is not False
            audit_ok = audit_verified is not False
            identity_ok = identity_verified is not False
            policy_ok = policy_verified is not False
            posterior_ok = posterior_verified is not False
            verified = hashes and coherent and (signature_verified if required_signature else True) and trust_ok and audit_ok and identity_ok and policy_ok and posterior_ok
            return {
                "verified": verified,
                "hashes_verified": hashes,
                "manifest_coherent": coherent,
                "signature_verified": signature_verified,
                "signer_trusted": signer_trusted,
                "tenant_verified": tenant_verified,
                "audit_verified": audit_verified,
                "audit_error": audit_error,
                "identity_verified": identity_verified,
                "identity_error": identity_error,
                "policy_verified": policy_verified,
                "policy_bundle_verified": policy_bundle_verified,
                "posterior_verified": posterior_verified,
                "posterior_error": posterior_error,
                "tenant_id": manifest.get("tenant_id"),
                "signer_key_id": manifest.get("signer_key_id"),
                "signature_state": manifest.get("signature_state"),
                "source_authority": manifest.get("source_authority"),
                "run_id": run.get("run_id"),
            }
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError, ValueError) as exc:
        return {"verified": False, "hashes_verified": False, "signature_verified": False, "reason": str(exc)}
