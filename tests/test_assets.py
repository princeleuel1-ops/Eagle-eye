import hashlib
import json
from pathlib import Path


def test_asset_registry_preserves_source_ids_and_matches_app_owned_files():
    root = Path(__file__).resolve().parents[1]
    registry = json.loads((root / "web/assets/node-registry.json").read_text())
    entries = registry["entries"]
    files = sorted((root / "web/assets/nodes").glob("*.png"))
    assert registry["historical_receipt_count"] == 116
    assert registry["main_curated_count"] == 109
    assert registry["replacement_count"] == 4
    assert registry["renderable_count"] == len(files) == 113
    assert registry["registry_entry_count"] == len(entries) == 116
    assert [item["asset_id"] for item in entries] == [f"{i:03d}" for i in range(1, 117)]
    for item in entries:
        if not item["renderable"]:
            continue
        path = root / "web" / item["app_path"].removeprefix("/")
        assert path.exists(), item["asset_id"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]


def test_replacements_duplicate_and_unexplained_removals_are_explicit():
    root = Path(__file__).resolve().parents[1]
    registry = json.loads((root / "web/assets/node-registry.json").read_text())
    by_id = {item["asset_id"]: item for item in registry["entries"]}
    for asset_id in {"012", "033", "100", "101"}:
        assert by_id[asset_id]["disposition"] == "replacement"
        assert by_id[asset_id]["reviewed"] is True
    assert by_id["092"]["disposition"] == "duplicate"
    assert by_id["092"]["canonical_id"] == "091"
    for asset_id in {"018", "085"}:
        assert by_id[asset_id]["disposition"] == "review"
        assert by_id[asset_id]["renderable"] is False
        assert by_id[asset_id]["exclusion_reason"]
