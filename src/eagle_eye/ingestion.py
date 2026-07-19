from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

SCHEMAS = {
    "suppliers.csv": {"id", "name", "country"},
    "products.csv": {"id", "name", "revenue_at_risk"},
    "components.csv": {"id", "name", "supplier_id", "product_id"},
    "purchase_orders.csv": {"id", "product_id", "supplier_id", "value"},
}


def _read_csv(path: Path, required: set[str]) -> list[dict[str, Any]]:
    if not path.exists():
        raise ValueError(f"{path.name} is required")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = sorted(required - columns)
        if missing:
            raise ValueError(f"{path.name} missing required columns: {', '.join(missing)}")
        rows = []
        for number, row in enumerate(reader, start=2):
            if not row.get("id", "").strip():
                raise ValueError(f"{path.name} row {number} has empty id")
            cleaned = {key: (value.strip() if isinstance(value, str) else value) for key, value in row.items()}
            for numeric in {"value", "revenue_at_risk", "lat", "lon"}:
                if cleaned.get(numeric) not in (None, ""):
                    cleaned[numeric] = float(cleaned[numeric])
            rows.append(cleaned)
        return rows


def ingest_directory(directory: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"mode": "FIXTURE"}
    for filename, required in SCHEMAS.items():
        result[filename.removesuffix(".csv")] = _read_csv(directory / filename, required)
    event_path = directory / "events.json"
    source_path = directory / "sources.json"
    if not event_path.exists() or not source_path.exists():
        missing = event_path.name if not event_path.exists() else source_path.name
        raise ValueError(f"{missing} is required")
    result["events"] = json.loads(event_path.read_text())
    result["sources"] = json.loads(source_path.read_text())
    result["ingestion"] = {
        "source_directory": str(directory),
        "record_counts": {key: len(value) for key, value in result.items() if isinstance(value, list)},
        "rejected_rows": 0,
        "mode": "FIXTURE",
    }
    return result
