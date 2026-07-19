import json
from pathlib import Path
import subprocess
import zipfile

from eagle_eye.evidence import export_evidence_room, verify_evidence_room
from eagle_eye.signing import generate_demo_keypair


def test_python_and_node_verify_same_ed25519_archive(tmp_path: Path):
    private_key, public_key = generate_demo_keypair()
    run = {"run_id": "run-signed", "mode": "FIXTURE", "graph": {"nodes": [], "edges": []}}
    archive = export_evidence_room(run, tmp_path / "signed.zip", private_key=private_key, public_key=public_key)

    python_result = verify_evidence_room(archive)
    assert python_result["verified"] is True
    assert python_result["signature_verified"] is True

    completed = subprocess.run(
        ["node", "verifier/verify.mjs", str(archive)],
        check=True, capture_output=True, text=True,
    )
    node_result = json.loads(completed.stdout.splitlines()[0])
    assert node_result["verified"] is True
    assert node_result["signature_verified"] is True
    assert node_result["run_id"] == python_result["run_id"]


def test_python_and_node_reject_tampered_signed_archive(tmp_path: Path):
    private_key, public_key = generate_demo_keypair()
    archive = export_evidence_room(
        {"run_id": "run-original", "mode": "FIXTURE", "graph": {"nodes": [], "edges": []}},
        tmp_path / "original.zip",
        private_key=private_key,
        public_key=public_key,
    )
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "run.json":
                data = data.replace(b"run-original", b"run-tampered")
            target.writestr(name, data)

    python_result = verify_evidence_room(tampered)
    assert python_result["verified"] is False
    assert python_result["hashes_verified"] is False

    completed = subprocess.run(
        ["node", "verifier/verify.mjs", str(tampered)],
        check=False, capture_output=True, text=True,
    )
    assert completed.returncode != 0
    node_result = json.loads(completed.stdout.splitlines()[0])
    assert node_result["verified"] is False
    assert node_result["hashes_verified"] is False
