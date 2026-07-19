"""V6 pilot storage — durable, tenant-bound, append-only-where-it-matters."""

import sqlite3

import pytest

from eagle_eye.audit import verify_chain
from eagle_eye.pilot.storage import (
    DuplicateIdempotencyKey, MIGRATIONS, PilotStorage, PostgresConfig,
    StorageError, TenantRequired, BackendUnavailable, migration_plan)


@pytest.fixture()
def store(tmp_path):
    s = PilotStorage(tmp_path / "pilot.sqlite3")
    s.migrate()
    s.ensure_tenant("tenant-fixture-a", display_name="Fixture A", data_class="FIXTURE")
    s.ensure_tenant("tenant-fixture-b", display_name="Fixture B", data_class="FIXTURE")
    yield s
    s.close()


def test_migrations_apply_from_empty_state(tmp_path):
    s = PilotStorage(tmp_path / "fresh.sqlite3")
    result = s.migrate()
    assert result["schema_version"] == MIGRATIONS[-1][0]
    assert len(result["applied_now"]) == len(MIGRATIONS)
    # idempotent: a second run applies nothing and fails nothing
    again = s.migrate()
    assert again["applied_now"] == []
    status = s.migration_status()
    assert [row["version"] for row in status] == [v for v, _, _ in MIGRATIONS]
    s.close()


def test_migration_checksum_drift_is_refused(tmp_path):
    s = PilotStorage(tmp_path / "drift.sqlite3")
    s.migrate()
    # simulate an edited historical migration by corrupting its recorded checksum
    with s.transaction() as conn:
        conn.execute("UPDATE schema_migrations SET checksum='deadbeef' WHERE version=1")
    with pytest.raises(StorageError, match="drifted"):
        s.migrate()
    s.close()


def test_migration_plan_is_machine_readable():
    plan = migration_plan()
    assert len(plan) == len(MIGRATIONS)
    assert all(set(p) == {"version", "name", "checksum"} for p in plan)


def test_tenant_data_class_is_labeled_and_constrained(store):
    row = store.tenant("tenant-fixture-a")
    assert row["data_class"] == "FIXTURE"
    with pytest.raises(StorageError, match="data_class"):
        store.ensure_tenant("tenant-x", display_name="X", data_class="CUSTOMER")


def test_duplicate_idempotency_key_rejected_transactionally(store):
    store.claim_idempotency("tenant-fixture-a", scope="ingest", key="k1")
    with pytest.raises(DuplicateIdempotencyKey):
        store.claim_idempotency("tenant-fixture-a", scope="ingest", key="k1")
    # same key in a DIFFERENT tenant or scope is a different claim
    store.claim_idempotency("tenant-fixture-b", scope="ingest", key="k1")
    store.claim_idempotency("tenant-fixture-a", scope="approval", key="k1")


def test_tenant_binding_is_mandatory_everywhere(store):
    with pytest.raises(TenantRequired):
        store.claim_idempotency("", scope="s", key="k")
    with pytest.raises(TenantRequired):
        store.audit_append("", event_type="t", actor_id="a",
                           payload={}, idempotency_key="k")
    with pytest.raises(TenantRequired):
        store.execute("tenant-fixture-a", "SELECT * FROM tenants")  # no tenant bind in SQL
    with pytest.raises(TenantRequired):
        store.execute("tenant-fixture-a",
                      "SELECT * FROM tenants WHERE tenant_id=?", ("other",))


def test_audit_rows_hash_link_and_verify_with_v5_verifier(store):
    for i in range(4):
        store.audit_append("tenant-fixture-a", event_type=f"e{i}",
                           actor_id="actor-1", payload={"i": i},
                           idempotency_key=f"key-{i}")
    events = store.audit_events("tenant-fixture-a")
    length, head = store.audit_head("tenant-fixture-a")
    verdict = verify_chain(events, expected_tenant="tenant-fixture-a",
                           expected_head=head, expected_length=length)
    assert verdict["verified"] and verdict["length"] == 4


def test_audit_rows_cannot_be_updated_or_deleted(store):
    store.audit_append("tenant-fixture-a", event_type="e", actor_id="a",
                       payload={}, idempotency_key="k")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        with store.transaction() as conn:
            conn.execute("UPDATE audit_events SET actor_id='evil' WHERE tenant_id=?",
                         ("tenant-fixture-a",))
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        with store.transaction() as conn:
            conn.execute("DELETE FROM audit_events WHERE tenant_id=?",
                         ("tenant-fixture-a",))


def test_audit_replay_and_cross_tenant_isolation(store):
    store.audit_append("tenant-fixture-a", event_type="e", actor_id="a",
                       payload={}, idempotency_key="dup")
    with pytest.raises(DuplicateIdempotencyKey):
        store.audit_append("tenant-fixture-a", event_type="e", actor_id="a",
                           payload={}, idempotency_key="dup")
    # tenant B's chain is independent: same key fine, chains do not mix
    store.audit_append("tenant-fixture-b", event_type="e", actor_id="a",
                       payload={}, idempotency_key="dup")
    assert len(store.audit_events("tenant-fixture-a")) == 1
    assert len(store.audit_events("tenant-fixture-b")) == 1


def test_head_commitment_outlives_rows_and_detects_truncation(store, tmp_path):
    for i in range(3):
        store.audit_append("tenant-fixture-a", event_type="e", actor_id="a",
                           payload={"i": i}, idempotency_key=f"k{i}")
    commitment = store.commit_audit_head("tenant-fixture-a")
    assert commitment["length"] == 3
    # commitments are append-only too
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        with store.transaction() as conn:
            conn.execute("UPDATE audit_head_commitments SET head='00' WHERE tenant_id=?",
                         ("tenant-fixture-a",))
    # a truncated events list no longer matches the persisted commitment
    events = store.audit_events("tenant-fixture-a")[:-1]
    with pytest.raises(Exception, match="length"):
        verify_chain(events, expected_tenant="tenant-fixture-a",
                     expected_head=commitment["head"], expected_length=commitment["length"])


def test_backup_and_restore_reproduce_audit_heads(store, tmp_path):
    for i in range(5):
        store.audit_append("tenant-fixture-a", event_type="e", actor_id="a",
                           payload={"i": i}, idempotency_key=f"b{i}")
    store.commit_audit_head("tenant-fixture-a")
    manifest = store.backup(tmp_path / "backup")
    assert manifest["audit_heads"]["tenant-fixture-a"]["length"] == 5
    check = PilotStorage.restore_check(tmp_path / "backup")
    assert check["all_heads_reproduced"] is True
    assert check["tenants"]["tenant-fixture-a"]["length"] == 5


def test_restore_check_fails_closed_on_corrupted_backup(store, tmp_path):
    store.audit_append("tenant-fixture-a", event_type="e", actor_id="a",
                       payload={}, idempotency_key="c1")
    store.backup(tmp_path / "backup")
    db = tmp_path / "backup" / "pilot.sqlite3"
    data = bytearray(db.read_bytes())
    data[len(data) // 2] ^= 0xFF  # flip a bit mid-file (tail may be zero padding)
    db.write_bytes(bytes(data))
    with pytest.raises(StorageError, match="corrupted"):
        PilotStorage.restore_check(tmp_path / "backup")


def test_database_restart_preserves_state(tmp_path):
    path = tmp_path / "restart.sqlite3"
    s1 = PilotStorage(path)
    s1.migrate()
    s1.ensure_tenant("tenant-fixture-a", display_name="A", data_class="FIXTURE")
    s1.audit_append("tenant-fixture-a", event_type="before-restart", actor_id="a",
                    payload={}, idempotency_key="r1")
    length, head = s1.audit_head("tenant-fixture-a")
    s1.close()
    s2 = PilotStorage(path)  # a fresh connection = process restart
    assert s2.audit_head("tenant-fixture-a") == (length, head)
    with pytest.raises(DuplicateIdempotencyKey):
        s2.audit_append("tenant-fixture-a", event_type="e", actor_id="a",
                        payload={}, idempotency_key="r1")
    s2.close()


def test_postgres_config_shape_fails_closed(monkeypatch):
    monkeypatch.delenv("EAGLE_EYE_PILOT_POSTGRES_DSN", raising=False)
    with pytest.raises(BackendUnavailable, match="NOT ESTABLISHED"):
        PostgresConfig().connect()
    # a configured DSN without a driver still fails closed
    monkeypatch.setenv("EAGLE_EYE_PILOT_POSTGRES_DSN", "postgresql://localhost/x")
    with pytest.raises(BackendUnavailable, match="driver|lock"):
        PostgresConfig().connect()
