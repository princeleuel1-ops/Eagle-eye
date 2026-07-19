import copy

import pytest

from eagle_eye.audit import AuditError, AuditLedger, verify_chain


def _ledger():
    ledger = AuditLedger("tenant-a")
    ledger.append(
        "action_requested",
        actor_id="analyst-1",
        payload={"action_id": "action-1", "request_id": "request-1"},
        idempotency_key="request-1",
    )
    ledger.append(
        "action_approved_shadow",
        actor_id="approver-1",
        payload={"action_id": "action-1", "receipt_id": "approval-1", "external_execution": False},
        idempotency_key="approval-1",
    )
    return ledger


def test_valid_chain_has_external_head_commitment():
    ledger = _ledger()
    result = verify_chain(
        ledger.events,
        expected_tenant="tenant-a",
        expected_head=ledger.head,
        expected_length=2,
    )
    assert result == {"verified": True, "length": 2, "head": ledger.head, "tenant_id": "tenant-a"}


def test_duplicate_idempotency_key_is_rejected():
    ledger = _ledger()
    with pytest.raises(AuditError, match="replay"):
        ledger.append(
            "action_approved_shadow",
            actor_id="approver-1",
            payload={"receipt_id": "approval-1"},
            idempotency_key="approval-1",
        )


def test_payload_tampering_breaks_chain():
    ledger = _ledger()
    events = copy.deepcopy(ledger.events)
    events[1]["payload"]["external_execution"] = True
    with pytest.raises(AuditError, match="hash"):
        verify_chain(events, expected_tenant="tenant-a", expected_head=ledger.head, expected_length=2)


def test_reordering_breaks_sequence():
    ledger = _ledger()
    events = list(reversed(copy.deepcopy(ledger.events)))
    with pytest.raises(AuditError, match="sequence"):
        verify_chain(events, expected_tenant="tenant-a", expected_head=ledger.head, expected_length=2)


def test_truncation_breaks_external_commitment():
    ledger = _ledger()
    with pytest.raises(AuditError, match="length"):
        verify_chain(
            copy.deepcopy(ledger.events[:-1]),
            expected_tenant="tenant-a",
            expected_head=ledger.head,
            expected_length=2,
        )


def test_cross_tenant_event_is_rejected():
    ledger = _ledger()
    events = copy.deepcopy(ledger.events)
    events[1]["tenant_id"] = "tenant-b"
    with pytest.raises(AuditError, match="tenant"):
        verify_chain(events, expected_tenant="tenant-a", expected_head=ledger.head, expected_length=2)
