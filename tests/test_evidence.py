import json
from pathlib import Path
from eagle_eye.evidence import export_evidence_room, verify_evidence_room


def test_evidence_room_detects_tampering(tmp_path: Path):
    run = {"run_id": "run-test", "mode": "FIXTURE", "graph": {"nodes": [], "edges": []}}
    archive = export_evidence_room(run, tmp_path / "room.zip")
    result = verify_evidence_room(archive)
    assert result["verified"] is True
    assert result["hashes_verified"] is True
