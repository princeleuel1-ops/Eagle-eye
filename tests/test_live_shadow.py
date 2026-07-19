"""V10 live-shadow spine: authority-config verification, the LIVE-labeling
guard (the load-bearing safety property), connector fail-closed posture, and
the conduit through the unchanged ingest boundary."""

import json
import time

import pytest

from eagle_eye.live_shadow import (
    ARM_DISARMED, ARM_LIVE, ARM_TEST_FIXTURE, AUTHORITY_CONFIG_SPEC,
    ConnectorDisabled, DataAuthorityError, LiveShadowConduit,
    NullLiveFeedConnector, ReplayFileFeedConnector, data_class_for,
    require_shadow_only, sign_authority_config, verify_authority_config,
)
from eagle_eye.pilot.ingest import IngestBoundary, SyntheticConnector
from eagle_eye.pilot.kms import EphemeralKeyProvider
from eagle_eye.pilot.storage import PilotStorage
from eagle_eye.signing import generate_demo_keypair, key_id

FIX = "tenant-fixture-x"


def _pinned():
    priv, pub = generate_demo_keypair()
    return priv, pub, {key_id(pub): pub}


def _cfg(cls="production", **over):
    base = {"spec": AUTHORITY_CONFIG_SPEC, "authority_class": cls,
            "tenant_id": "tenant-real", "source_ids": ["s1"],
            "event_kinds": ["disruption_signal"], "rate_cap_per_hour": 500,
            "retention_days": 30, "legal_basis": "DPA §4",
            "authorized_by": [{"sub": "ciso"}, {"sub": "dpo"}],
            "valid_from_epoch": time.time() - 60,
            "valid_until_epoch": time.time() + 3600}
    base.update(over)
    return base


# ---------- the LIVE-labeling guard (the safety core) -------------------------

def test_live_requires_all_three_signals():
    assert data_class_for(arm_state=ARM_LIVE, attestation={"origin": "live"},
                          tenant_data_class="LIVE") == "LIVE"


def test_fixture_when_no_live_signals():
    assert data_class_for(arm_state=ARM_TEST_FIXTURE,
                          attestation={"origin": "replay_fixture"},
                          tenant_data_class="FIXTURE") == "FIXTURE"


@pytest.mark.parametrize("arm,origin,tenant", [
    (ARM_LIVE, "replay_fixture", "FIXTURE"),
    (ARM_TEST_FIXTURE, "live", "FIXTURE"),
    (ARM_TEST_FIXTURE, "replay_fixture", "LIVE"),
    (ARM_LIVE, "live", "FIXTURE"),
    (ARM_LIVE, "replay_fixture", "LIVE"),
])
def test_partial_live_claim_is_hard_refused(arm, origin, tenant):
    with pytest.raises(DataAuthorityError):
        data_class_for(arm_state=arm, attestation={"origin": origin},
                       tenant_data_class=tenant)


def test_shadow_only_interlock():
    require_shadow_only("LIVE", "shadow")   # no raise
    require_shadow_only("FIXTURE", "external")  # interlock is live-only
    with pytest.raises(DataAuthorityError):
        require_shadow_only("LIVE", "external")


# ---------- authority config verification ------------------------------------

def test_none_and_missing_fields_disarm():
    _, _, pinned = _pinned()
    assert verify_authority_config(None, trusted_authority_keys=pinned)["arm_state"] == ARM_DISARMED
    assert verify_authority_config({"spec": AUTHORITY_CONFIG_SPEC},
                                   trusted_authority_keys=pinned)["arm_state"] == ARM_DISARMED


def test_valid_production_arms_live_and_fixture_arms_fixture():
    priv, pub, pinned = _pinned()
    live = verify_authority_config(sign_authority_config(_cfg(), priv, pub),
                                   trusted_authority_keys=pinned, fixture_tenants=(FIX,))
    assert live["arm_state"] == ARM_LIVE and live["config_sha256"]
    fix = verify_authority_config(
        sign_authority_config(_cfg("test_fixture", tenant_id=FIX), priv, pub),
        trusted_authority_keys=pinned, fixture_tenants=(FIX,))
    assert fix["arm_state"] == ARM_TEST_FIXTURE


def test_untrusted_signer_disarms():
    priv, pub, _ = _pinned()
    _, _, other_pinned = _pinned()  # different pinned set
    r = verify_authority_config(sign_authority_config(_cfg(), priv, pub),
                                trusted_authority_keys=other_pinned, fixture_tenants=(FIX,))
    assert r["arm_state"] == ARM_DISARMED
    assert any("pinned authority" in x for x in r["reasons"])


def test_tamper_after_signing_disarms():
    priv, pub, pinned = _pinned()
    signed = sign_authority_config(_cfg(), priv, pub)
    signed["rate_cap_per_hour"] = 10 ** 9
    r = verify_authority_config(signed, trusted_authority_keys=pinned, fixture_tenants=(FIX,))
    assert r["arm_state"] == ARM_DISARMED and any("signature" in x for x in r["reasons"])


def test_single_approver_and_fixture_tenant_and_expiry_disarm():
    priv, pub, pinned = _pinned()
    single = verify_authority_config(
        sign_authority_config(_cfg(authorized_by=[{"sub": "solo"}]), priv, pub),
        trusted_authority_keys=pinned, fixture_tenants=(FIX,))
    assert single["arm_state"] == ARM_DISARMED
    fixture_target = verify_authority_config(
        sign_authority_config(_cfg(tenant_id=FIX), priv, pub),
        trusted_authority_keys=pinned, fixture_tenants=(FIX,))
    assert fixture_target["arm_state"] == ARM_DISARMED
    expired = verify_authority_config(
        sign_authority_config(_cfg(valid_until_epoch=time.time() - 1), priv, pub),
        trusted_authority_keys=pinned, fixture_tenants=(FIX,))
    assert expired["arm_state"] == ARM_DISARMED


def test_production_requires_nonempty_legal_basis():
    priv, pub, pinned = _pinned()
    r = verify_authority_config(sign_authority_config(_cfg(legal_basis="  "), priv, pub),
                                trusted_authority_keys=pinned, fixture_tenants=(FIX,))
    assert r["arm_state"] == ARM_DISARMED and any("legal basis" in x for x in r["reasons"])


# ---------- connectors + conduit ---------------------------------------------

def test_null_connector_is_fail_closed():
    with pytest.raises(ConnectorDisabled):
        NullLiveFeedConnector().poll()
    assert NullLiveFeedConnector().attestation()["origin"] == "disabled"


def test_conduit_refuses_to_construct_while_disarmed():
    _, _, pinned = _pinned()
    with pytest.raises(DataAuthorityError):
        LiveShadowConduit(boundary=None, connector=NullLiveFeedConnector(),
                          verification=verify_authority_config(None, trusted_authority_keys=pinned))


def test_conduit_drives_unchanged_boundary_and_labels_fixture(tmp_path):
    priv, pub, pinned = _pinned()
    store = PilotStorage(tmp_path / "p.sqlite3")
    store.migrate()
    store.ensure_tenant(FIX, display_name="Fix", data_class="FIXTURE")
    feed = SyntheticConnector(source_id="s1", tenant_id=FIX, seed=5)
    boundary = IngestBoundary(store, signer=EphemeralKeyProvider(),
                              sources={"s1": feed.source_registration()})
    path = tmp_path / "feed.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in feed.events(6)) + "\n")
    cfg = sign_authority_config(_cfg("test_fixture", tenant_id=FIX, source_ids=["s1"]),
                                priv, pub)
    v = verify_authority_config(cfg, trusted_authority_keys=pinned, fixture_tenants=(FIX,))
    conduit = LiveShadowConduit(boundary=boundary,
                                connector=ReplayFileFeedConnector(path), verification=v)
    summary = conduit.run_once(tenant_data_class="FIXTURE")
    assert summary["accepted"] == 6 and summary["data_class"] == "FIXTURE"
    assert summary["quarantined"] == 0 and summary["external_action"] is False
    assert summary["summary_sha256"]
    store.close()


def test_conduit_filters_out_of_scope_sources(tmp_path):
    priv, pub, pinned = _pinned()
    store = PilotStorage(tmp_path / "p.sqlite3")
    store.migrate()
    store.ensure_tenant(FIX, display_name="Fix", data_class="FIXTURE")
    feed = SyntheticConnector(source_id="s1", tenant_id=FIX, seed=5)
    other = SyntheticConnector(source_id="rogue", tenant_id=FIX, seed=9)
    boundary = IngestBoundary(store, signer=EphemeralKeyProvider(),
                              sources={"s1": feed.source_registration(),
                                       "rogue": other.source_registration()})
    path = tmp_path / "feed.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in
                              feed.events(3) + other.events(3)) + "\n")
    cfg = sign_authority_config(_cfg("test_fixture", tenant_id=FIX, source_ids=["s1"]),
                                priv, pub)
    v = verify_authority_config(cfg, trusted_authority_keys=pinned, fixture_tenants=(FIX,))
    summary = LiveShadowConduit(boundary=boundary,
                                connector=ReplayFileFeedConnector(path),
                                verification=v).run_once(tenant_data_class="FIXTURE")
    assert summary["accepted"] == 3 and summary["out_of_scope"] == 3
    store.close()
