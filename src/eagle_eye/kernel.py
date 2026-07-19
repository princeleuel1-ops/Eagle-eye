from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any


def _stable_id(prefix: str, value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:12]}"


def build_run(data: dict[str, Any]) -> dict[str, Any]:
    mode = data.get("mode")
    if mode is None:
        raise ValueError("mode is required and must identify FIXTURE, REPLAY, or LIVE")
    if mode != "FIXTURE":
        raise ValueError("Slice 1 accepts FIXTURE mode only; LIVE requires authorized connectors")

    suppliers = data.get("suppliers", [])
    products = data.get("products", [])
    components = data.get("components", [])
    purchase_orders = data.get("purchase_orders", [])
    events = data.get("events", [])
    sources = {item["id"]: item for item in data.get("sources", [])}

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for kind, records in (
        ("supplier", suppliers), ("product", products), ("component", components),
        ("purchase_order", purchase_orders), ("event", events),
    ):
        for record in records:
            nodes.append({"id": record["id"], "type": kind, "label": record.get("name", record["id"]), "data": record})

    for component in components:
        edges.append({"id": f"edge-{component['id']}-supplier", "source": component["supplier_id"], "target": component["id"], "type": "supplies"})
        edges.append({"id": f"edge-{component['id']}-product", "source": component["id"], "target": component["product_id"], "type": "part_of"})
    for po in purchase_orders:
        edges.append({"id": f"edge-{po['id']}-supplier", "source": po["supplier_id"], "target": po["id"], "type": "fulfills"})
        edges.append({"id": f"edge-{po['id']}-product", "source": po["id"], "target": po["product_id"], "type": "orders"})

    risks: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    product_by_id = {p["id"]: p for p in products}

    for event in events:
        if event.get("source_id") not in sources:
            raise ValueError(f"event {event['id']} has no valid evidence source")
        supplier_id = event["supplier_id"]
        affected_pos = [po for po in purchase_orders if po["supplier_id"] == supplier_id]
        affected_products = sorted({po["product_id"] for po in affected_pos})
        revenue = sum(float(product_by_id[p].get("revenue_at_risk", 0)) for p in affected_products if p in product_by_id)
        po_value = sum(float(po.get("value", 0)) for po in affected_pos)
        severity = max(0.0, min(1.0, float(event.get("severity", 0))))
        exposure_low = round((revenue + po_value) * severity * 0.15, 2)
        exposure_high = round((revenue + po_value) * severity * 0.45, 2)
        risk = {
            "id": _stable_id("risk", event),
            "title": f"{event.get('kind', 'event').replace('_', ' ').title()} affects {len(affected_pos)} purchase order(s)",
            "event_id": event["id"],
            "supplier_id": supplier_id,
            "severity": severity,
            "confidence": "bounded_fixture",
            "evidence_ids": [event["source_id"]],
            "affected_purchase_orders": [po["id"] for po in affected_pos],
            "affected_products": affected_products,
            "exposure_range": {"low": exposure_low, "high": exposure_high, "currency": "USD"},
            "unknowns": ["actual disruption duration", "alternate supplier qualification time"],
        }
        action = {
            "id": _stable_id("action", {"risk": risk["id"], "kind": "review_alternates"}),
            "risk_id": risk["id"],
            "title": "Review alternate supply and inventory coverage",
            "owner_role": "procurement_lead",
            "reason": "Supplier disruption intersects open purchase orders",
            "evidence_ids": risk["evidence_ids"],
            "status": "pending_approval",
            "external_execution_allowed": False,
            "rollback": "No external change occurs before approval",
        }
        risks.append(risk)
        actions.append(action)
        for po in affected_pos:
            traces.append({"id": _stable_id("trace", [event["source_id"], event["id"], supplier_id, po["id"], action["id"]]), "path": [event["source_id"], event["id"], supplier_id, po["id"], action["id"]]})

    scenarios: list[dict[str, Any]] = []
    if risks:
        primary = risks[0]
        scenarios = [
            {
                "id": "scenario-baseline",
                "name": "baseline",
                "description": "Release proceeds under expected fixture conditions",
                "delay_days": {"low": 0, "high": 3},
                "exposure_range": {"low": 0, "high": round(primary["exposure_range"]["low"] * 0.25, 2), "currency": "USD"},
                "assumptions": ["No material extension of the disruption"],
            },
            {
                "id": "scenario-disruption",
                "name": "disruption",
                "description": "Current fixture disruption persists through the modeled window",
                "delay_days": {"low": 7, "high": 21},
                "exposure_range": primary["exposure_range"],
                "assumptions": ["Fixture severity remains constant", "No qualified alternate is yet confirmed"],
            },
        ]

    payload = {
        "mode": mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "graph": {"nodes": nodes, "edges": edges},
        "risks": risks,
        "scenarios": scenarios,
        "actions": actions,
        "approval_receipts": [],
        "trace": traces,
        "sources": list(sources.values()),
        "limitations": [
            "All current records are authorized synthetic fixtures.",
            "Exposure is a bounded deterministic demonstration, not a calibrated forecast.",
            "No external action is executed.",
        ],
    }
    payload["run_id"] = _stable_id("run", {k: v for k, v in payload.items() if k not in {"generated_at"}})
    return payload
