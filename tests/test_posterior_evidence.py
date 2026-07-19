import copy
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from eagle_eye.evidence import export_evidence_room, verify_evidence_room
from eagle_eye.posterior_engine import (
    attach_posterior_intelligence,
    build_demo_registry,
    build_demo_target,
    commitment_hash,
    quantize_micro,
)
from eagle_eye.signing import generate_demo_keypair


@pytest.fixture(scope="module")
def registry():
    return build_demo_registry()


@pytest.fixture(scope="module")
def court_receipt_stub(registry):
    """Minimal court receipt carrying exactly the fields the engine binds.

    The court's real behavior is proven in test_prediction_court; this stub
    keeps the evidence-layer tests fast while preserving the binding contract.
    """
    return {
        "court_receipt_id": "pcourt-stub00000000",
        "development_sha256": "d" * 64,
        "holdout_sha256": "h" * 64,
        "registry_manifest_sha256": registry["manifest_sha256"],
        "decisions": [{"candidate": "governed_set_mt", "status": "promote", "reasons": []}],
        "evaluations": {
            "governed_set_mt": {
                "holdout": {
                    "metrics": {
                        "nll": 0.770731, "crps": 0.332435, "coverage80": 0.904762,
                        "nll_temporal_ood": 0.441657, "permutation_spread_max": 0.0,
                    }
                }
            }
        },
    }


@pytest.fixture(scope="module")
def fixture_payload():
    return {
        "events": [{"id": "evt-1", "supplier_id": "sup-1", "severity": 0.7, "source_id": "src-1"}],
        "purchase_orders": [{"id": "PO-17", "supplier_id": "sup-1", "product_id": "prod-1", "value": 250000}],
        "components": [{"id": "cmp-1", "supplier_id": "sup-1", "product_id": "prod-1"}],
    }


@pytest.fixture(scope="module")
def posterior_run(registry, court_receipt_stub, fixture_payload):
    run = {"run_id": "run-posterior-test", "mode": "FIXTURE", "graph": {"nodes": [], "edges": []}}
    target = build_demo_target(fixture_payload)
    attach_posterior_intelligence(
        run, registry=registry, target=target, court_receipt=court_receipt_stub)
    return run


def _write_room(run, path, *, signed=True):
    if signed:
        private_key, public_key = generate_demo_keypair()
        return export_evidence_room(run, path, private_key=private_key, public_key=public_key,
                                    tenant_id="tenant-demo")
    return export_evidence_room(run, path, tenant_id="tenant-demo")


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _tamper(archive: Path, destination: Path, mutate) -> Path:
    """Adversary model: rewrite run.json via `mutate`, fix the manifest file
    hash, and RE-SIGN the manifest with the attacker's own (untrusted) key.
    The Ed25519 signature then verifies — only the posterior commitment
    checks stand between the verifier and the forged distribution."""
    import base64

    from eagle_eye.signing import key_id, sign

    with zipfile.ZipFile(archive) as source:
        run = json.loads(source.read("run.json"))
        manifest = json.loads(source.read("manifest.json"))
    mutate(run, manifest)
    run_bytes = json.dumps(run, indent=2, sort_keys=True).encode()
    manifest["files"]["run.json"] = {
        "sha256": hashlib.sha256(run_bytes).hexdigest(), "bytes": len(run_bytes)}
    attacker_private, attacker_public = generate_demo_keypair()
    manifest.pop("signature", None)
    manifest["signature_state"] = "DEMO_ED25519"
    manifest["signer_key_id"] = key_id(attacker_public)
    signature = sign(_canonical(manifest), attacker_private)
    manifest["signature"] = {
        "algorithm": "Ed25519",
        "public_key_pem": attacker_public.decode(),
        "value_base64": base64.b64encode(signature).decode(),
        "key_authority": "attacker_self_signed",
    }
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as target:
        target.writestr("run.json", run_bytes)
        target.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True).encode())
    return destination


def _node_verify(archive: Path) -> dict:
    completed = subprocess.run(["node", "verifier/verify.mjs", str(archive)],
                               check=False, capture_output=True, text=True)
    return json.loads(completed.stdout.splitlines()[0])


def test_quantize_micro_cross_runtime_semantics():
    assert quantize_micro(2.0) == 2               # integer-valued float -> int (Node parity)
    assert quantize_micro(0.5) == 500000
    assert quantize_micro(-1.25) == -1250000
    assert quantize_micro({"a": [1.5, True, None, "x", 3]}) == {"a": [1500000, True, None, "x", 3]}
    assert quantize_micro(0.4123456789) == 412346  # half-up at the 7th decimal


def test_engine_refuses_unpromoted_or_mismatched_court(registry, court_receipt_stub, fixture_payload):
    run = {"run_id": "r", "mode": "FIXTURE"}
    target = build_demo_target(fixture_payload)
    demoted = copy.deepcopy(court_receipt_stub)
    demoted["decisions"][0]["status"] = "reject"
    with pytest.raises(ValueError, match="no promotion"):
        attach_posterior_intelligence(run, registry=registry, target=target, court_receipt=demoted)
    foreign = copy.deepcopy(court_receipt_stub)
    foreign["registry_manifest_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="different prior registry"):
        attach_posterior_intelligence(run, registry=registry, target=target, court_receipt=foreign)


def test_signed_posterior_room_verifies_in_both_runtimes(posterior_run, tmp_path):
    archive = _write_room(posterior_run, tmp_path / "room.zip", signed=True)
    py = verify_evidence_room(archive)
    assert py["posterior_verified"] is True, py.get("posterior_error")
    assert py["verified"] is True
    node = _node_verify(archive)
    assert node["posterior_verified"] is True, node.get("posterior_error")
    assert node["verified"] is True


def test_tampered_probability_is_caught_by_both_runtimes(posterior_run, tmp_path):
    archive = _write_room(posterior_run, tmp_path / "room.zip")

    def mutate(run, manifest):
        wait = run["posterior_intelligence"]["interventions"]["wait_incumbent"]
        wait["delay"]["p_exceeds_days"]["14"] = 0.010101  # forged optimism

    tampered = _tamper(archive, tmp_path / "tampered.zip", mutate)
    py = verify_evidence_room(tampered)
    assert py["posterior_verified"] is False
    assert "commitment mismatch" in py["posterior_error"]
    assert py["verified"] is False
    node = _node_verify(tampered)
    assert node["posterior_verified"] is False
    assert node["verified"] is False


def test_tampered_selection_receipt_is_caught(posterior_run, tmp_path):
    archive = _write_room(posterior_run, tmp_path / "room.zip")

    def mutate(run, manifest):
        receipt = run["posterior_intelligence"]["selection_receipt"]
        receipt["included_prior_task_ids"] = receipt["included_prior_task_ids"][:-1]
        run["posterior_intelligence"]["K"] = len(receipt["included_prior_task_ids"])

    tampered = _tamper(archive, tmp_path / "tampered.zip", mutate)
    py = verify_evidence_room(tampered)
    assert py["posterior_verified"] is False
    assert "selection receipt" in py["posterior_error"]
    node = _node_verify(tampered)
    assert node["posterior_verified"] is False


def test_tampered_calibration_receipt_is_caught(posterior_run, tmp_path):
    archive = _write_room(posterior_run, tmp_path / "room.zip")

    def mutate(run, manifest):
        run["posterior_intelligence"]["calibration_receipt"]["coverage80_micro"] = 990000

    tampered = _tamper(archive, tmp_path / "tampered.zip", mutate)
    assert verify_evidence_room(tampered)["posterior_verified"] is False
    assert _node_verify(tampered)["posterior_verified"] is False


def test_manifest_support_state_mismatch_is_caught(posterior_run, tmp_path):
    archive = _write_room(posterior_run, tmp_path / "room.zip")

    def mutate(run, manifest):
        manifest["posterior_commitments"]["support_state"] = "strong-forged"

    tampered = _tamper(archive, tmp_path / "tampered.zip", mutate)
    py = verify_evidence_room(tampered)
    assert py["posterior_verified"] is False
    assert "manifest" in py["posterior_error"]
    assert _node_verify(tampered)["posterior_verified"] is False


def test_dropping_posterior_block_but_keeping_manifest_commitments_is_caught(posterior_run, tmp_path):
    archive = _write_room(posterior_run, tmp_path / "room.zip")

    def mutate(run, manifest):
        del run["posterior_intelligence"]

    tampered = _tamper(archive, tmp_path / "tampered.zip", mutate)
    py = verify_evidence_room(tampered)
    assert py["posterior_verified"] is False
    assert "absent" in py["posterior_error"]
    node = _node_verify(tampered)
    assert node["posterior_verified"] is False


def test_rooms_without_posterior_block_remain_backward_compatible(tmp_path):
    run = {"run_id": "run-legacy", "mode": "FIXTURE", "graph": {"nodes": [], "edges": []}}
    archive = _write_room(run, tmp_path / "legacy.zip", signed=True)
    py = verify_evidence_room(archive)
    assert py["verified"] is True
    assert py["posterior_verified"] is None
    node = _node_verify(archive)
    assert node["verified"] is True
    assert node["posterior_verified"] is None


def test_commitment_hash_matches_engine_block(posterior_run):
    pi = posterior_run["posterior_intelligence"]
    basis = {
        "candidate": pi["candidate"],
        "model_release": pi["model_release"],
        "prior_manifest_sha256": pi["prior_manifest_sha256"],
        "as_of_cutoff": pi["as_of_cutoff"],
        "abstained": pi["abstained"],
        "interventions": pi["interventions"],
    }
    assert commitment_hash(basis) == pi["predictive_distribution_commitment"]
