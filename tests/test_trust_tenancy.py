import json
from pathlib import Path
import subprocess

from eagle_eye.evidence import export_evidence_room, verify_evidence_room
from eagle_eye.signing import generate_demo_keypair, key_id


def _registry(path: Path, public_key: bytes, tenant: str = "tenant-demo") -> Path:
    path.write_text(json.dumps({
        "spec": "eagle-eye-trust-registry/0.1-fixture",
        "trusted_signers": [{
            "key_id": key_id(public_key),
            "public_key_pem": public_key.decode(),
            "allowed_tenants": [tenant],
            "authority": "fixture",
        }],
    }))
    return path


def test_trusted_signer_and_expected_tenant_pass(tmp_path: Path):
    private, public = generate_demo_keypair()
    archive = export_evidence_room(
        {"run_id": "run-tenant-a", "mode": "FIXTURE"},
        tmp_path / "room.zip",
        private_key=private,
        public_key=public,
        tenant_id="tenant-a",
    )
    registry = _registry(tmp_path / "trust.json", public, "tenant-a")
    result = verify_evidence_room(archive, trust_registry=registry, expected_tenant="tenant-a")
    assert result["verified"] is True
    assert result["signer_trusted"] is True
    assert result["tenant_verified"] is True
    node = subprocess.run(
        ["node", "verifier/verify.mjs", str(archive), "--trust-registry", str(registry), "--expected-tenant", "tenant-a"],
        check=False, capture_output=True, text=True,
    )
    assert node.returncode == 0
    node_result = json.loads(node.stdout.splitlines()[0])
    assert node_result["verified"] is True
    assert node_result["signer_trusted"] is True
    assert node_result["tenant_verified"] is True


def test_unknown_signer_fails_closed(tmp_path: Path):
    private, public = generate_demo_keypair()
    _, other_public = generate_demo_keypair()
    archive = export_evidence_room(
        {"run_id": "run-unknown", "mode": "FIXTURE"},
        tmp_path / "room.zip",
        private_key=private,
        public_key=public,
        tenant_id="tenant-a",
    )
    registry = _registry(tmp_path / "trust.json", other_public, "tenant-a")
    result = verify_evidence_room(archive, trust_registry=registry, expected_tenant="tenant-a")
    assert result["verified"] is False
    assert result["signature_verified"] is True
    assert result["signer_trusted"] is False


def test_cross_tenant_replay_fails_closed(tmp_path: Path):
    private, public = generate_demo_keypair()
    archive = export_evidence_room(
        {"run_id": "run-tenant-a", "mode": "FIXTURE"},
        tmp_path / "room.zip",
        private_key=private,
        public_key=public,
        tenant_id="tenant-a",
    )
    registry = _registry(tmp_path / "trust.json", public, "tenant-a")
    result = verify_evidence_room(archive, trust_registry=registry, expected_tenant="tenant-b")
    assert result["verified"] is False
    assert result["signer_trusted"] is True
    assert result["tenant_verified"] is False
    node = subprocess.run(
        ["node", "verifier/verify.mjs", str(archive), "--trust-registry", str(registry), "--expected-tenant", "tenant-b"],
        check=False, capture_output=True, text=True,
    )
    assert node.returncode != 0
    node_result = json.loads(node.stdout.splitlines()[0])
    assert node_result["signature_verified"] is True
    assert node_result["signer_trusted"] is True
    assert node_result["tenant_verified"] is False
