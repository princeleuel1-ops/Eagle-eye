"""V5 pilot adapters must be fail-closed by default and honest about what a
real pilot still needs. No adapter may claim readiness it does not have."""
import pytest

from eagle_eye.adapters import (
    AdapterDisabled,
    NullActionExecutor,
    NullAuditSink,
    NullDataSource,
    NullIdentity,
    NullKeyCustody,
    PilotConfig,
    default_adapters,
    pilot_status,
)


def test_every_default_adapter_is_fail_closed():
    a = default_adapters()
    with pytest.raises(AdapterDisabled, match="fetch_tasks"):
        a["data_source"].fetch_tasks(tenant_id="tenant-demo")
    with pytest.raises(AdapterDisabled, match="sign"):
        a["key_custody"].sign(b"x", key_id="k")
    with pytest.raises(AdapterDisabled, match="authenticate"):
        a["identity"].authenticate("token")
    with pytest.raises(AdapterDisabled, match="append"):
        a["audit_sink"].append({"row": 1})
    with pytest.raises(AdapterDisabled, match="execute"):
        a["action_executor"].execute({"action": "buy"})


def test_capability_reporters_all_false_by_default():
    a = default_adapters()
    assert a["data_source"].is_live() is False
    assert a["key_custody"].is_production() is False
    assert a["identity"].is_production() is False
    assert a["audit_sink"].is_durable() is False
    assert a["action_executor"].is_enabled() is False


def test_pilot_status_is_all_fail_closed_and_not_established():
    status = pilot_status()
    assert status["all_fail_closed"] is True
    assert status["external_action"] is False
    for cap in status["capabilities"].values():
        assert cap["ready"] is False
        assert cap["evidence_class"] == "NOT ESTABLISHED"
        assert cap["pilot_needs"]


def test_flipping_config_without_backend_still_fails_closed():
    # turning the flag on but keeping Null adapters must NOT report ready
    cfg = PilotConfig(external_execution_enabled=True)
    status = pilot_status(config=cfg)
    assert status["external_action"] is False  # Null executor ignores the flag
    with pytest.raises(AdapterDisabled):
        default_adapters()["action_executor"].execute({"a": 1})
