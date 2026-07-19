"""V6 identity seam + KMS seam — positive paths AND the rejection court."""

import time

import pytest

from eagle_eye.identity import IdentityError
from eagle_eye.pilot.identity_service import (
    AuthorizationError, IdentityVerifier, LocalDevIssuer, OidcProviderConfig,
    PILOT_AUDIENCE, identity_status, require_permission)
from eagle_eye.pilot.kms import (
    AwsKmsConfig, EphemeralKeyProvider, GcpKmsConfig, KeyProviderError,
    PersistedKeyProvider, kms_status)

TENANT = "tenant-fixture-a"
OTHER = "tenant-fixture-b"


@pytest.fixture()
def issuer():
    return LocalDevIssuer(tenants=[TENANT, OTHER])


@pytest.fixture()
def verifier(issuer):
    return IdentityVerifier(registry_entries=issuer.registry_entries())


def test_valid_assertion_authenticates_with_subject_and_tenant(issuer, verifier):
    token = issuer.mint(subject="user-req-1", tenant_id=TENANT, roles=["analyst"])
    principal = verifier.verify(token, expected_tenant=TENANT)
    assert principal["id"] == "user-req-1"
    assert principal["tenant_id"] == TENANT
    assert principal["issuer"] == "local-dev-issuer:NOT-PRODUCTION"


def test_expired_assertion_rejected(issuer, verifier):
    token = issuer.mint(subject="u", tenant_id=TENANT, roles=["analyst"],
                        ttl_seconds=10, now=int(time.time()) - 3600)
    with pytest.raises(IdentityError, match="expired"):
        verifier.verify(token, expected_tenant=TENANT)


def test_not_before_enforced(issuer, verifier):
    token = issuer.mint(subject="u", tenant_id=TENANT, roles=["analyst"],
                        nbf_offset_seconds=3600)
    with pytest.raises(IdentityError, match="not yet valid"):
        verifier.verify(token, expected_tenant=TENANT)


def test_cross_tenant_token_rejected(issuer, verifier):
    token = issuer.mint(subject="u", tenant_id=OTHER, roles=["analyst"])
    with pytest.raises(IdentityError, match="tenant"):
        verifier.verify(token, expected_tenant=TENANT)


def test_wrong_audience_rejected(issuer):
    strict = IdentityVerifier(registry_entries=issuer.registry_entries(),
                              expected_audience="some-other-app")
    token = issuer.mint(subject="u", tenant_id=TENANT, roles=["analyst"])
    with pytest.raises(IdentityError, match="audience"):
        strict.verify(token, expected_tenant=TENANT)


def test_unknown_issuer_rejected(issuer):
    foreign = LocalDevIssuer(tenants=[TENANT])
    verifier = IdentityVerifier(registry_entries=issuer.registry_entries())
    token = foreign.mint(subject="u", tenant_id=TENANT, roles=["analyst"])
    # foreign issuer shares the NAME but not the pinned key ⇒ untrusted
    with pytest.raises(IdentityError, match="issuer"):
        verifier.verify(token, expected_tenant=TENANT)


def test_revoked_issuer_rejected(issuer, verifier):
    token = issuer.mint(subject="u", tenant_id=TENANT, roles=["analyst"])
    verifier.revoke_issuer(issuer.issuer)
    with pytest.raises(IdentityError, match="issuer"):
        verifier.verify(token, expected_tenant=TENANT)


def test_revoked_session_rejected(issuer, verifier):
    token = issuer.mint(subject="u", tenant_id=TENANT, roles=["analyst"])
    principal = verifier.verify(token, expected_tenant=TENANT)
    verifier.revoke_jti(principal["session_id"])
    with pytest.raises(IdentityError, match="revoked"):
        verifier.verify(token, expected_tenant=TENANT)


def test_missing_or_garbage_authentication_rejected(verifier):
    for bad in ("", "not-a-token", "a.b", "a.b.c.d"):
        with pytest.raises(IdentityError):
            verifier.verify(bad, expected_tenant=TENANT)


def test_key_rotation_old_tokens_verify_new_tokens_sign(issuer):
    old_token = issuer.mint(subject="u", tenant_id=TENANT, roles=["analyst"])
    old_kid = issuer.active_kid()
    new_kid = issuer.rotate()
    assert new_kid != old_kid
    verifier = IdentityVerifier(registry_entries=issuer.registry_entries())
    # historical assertion still verifies (its kid stays in the registry) …
    assert verifier.verify(old_token, expected_tenant=TENANT)["id"] == "u"
    # … and fresh assertions sign with the NEW key
    fresh = issuer.mint(subject="u2", tenant_id=TENANT, roles=["approver"])
    assert verifier.verify(fresh, expected_tenant=TENANT)["id"] == "u2"


def test_permission_model_denies_by_default(issuer, verifier):
    token = issuer.mint(subject="u", tenant_id=TENANT, roles=["approver"])
    principal = verifier.verify(token, expected_tenant=TENANT)
    require_permission(principal, "action:approve")  # allowed
    with pytest.raises(AuthorizationError):
        require_permission(principal, "action:request")  # approvers do not request
    with pytest.raises(AuthorizationError):
        require_permission({"id": "x", "roles": ["unknown-role"]}, "ingest:read")


def test_oidc_shape_fails_closed(monkeypatch):
    for var in ("EAGLE_EYE_PILOT_OIDC_ISSUER", "EAGLE_EYE_PILOT_OIDC_CLIENT_ID",
                "EAGLE_EYE_PILOT_OIDC_JWKS_URL"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(IdentityError, match="NOT ESTABLISHED"):
        OidcProviderConfig().load()


def test_identity_status_is_honest(issuer):
    status = identity_status(issuer)
    assert status["development_issuer"]["production"] is False
    assert status["oidc_provider"]["evidence_class"] == "NOT ESTABLISHED"
    assert status["no_default_bypass"] is True


# ---------------------------------------------------------------------------
# KMS seam
# ---------------------------------------------------------------------------

def test_ephemeral_provider_signs_verifies_and_rotates():
    kp = EphemeralKeyProvider()
    payload = b"pilot-audit-head"
    sig = kp.sign(payload)
    assert kp.verify(payload, sig)
    old_kid = kp.key_id()
    new_kid = kp.rotate()
    assert new_kid != old_kid
    # rotated-out key still verifies history but never signs again
    assert kp.verify(payload, sig, key_id=old_kid)
    assert kp.verify(b"new-payload", kp.sign(b"new-payload"))
    assert kp.health()["production"] is False


def test_persisted_provider_requires_passphrase_and_detects_tamper(tmp_path, monkeypatch):
    path = tmp_path / "pilot-key.json"
    monkeypatch.setenv("EAGLE_EYE_PILOT_KEY_PASSPHRASE", "correct horse battery")
    kp = PersistedKeyProvider(path)
    kid = kp.initialize()
    sig = kp.sign(b"payload")
    assert kp.verify(b"payload", sig)
    assert kp.key_id() == kid
    # a fresh instance without the passphrase is DISABLED and fails closed
    monkeypatch.delenv("EAGLE_EYE_PILOT_KEY_PASSPHRASE")
    cold = PersistedKeyProvider(path)
    assert cold.state() == "DISABLED"
    with pytest.raises(KeyProviderError, match="fail closed|not set"):
        cold.sign(b"payload")
    # wrong passphrase → integrity tag mismatch, fail closed
    monkeypatch.setenv("EAGLE_EYE_PILOT_KEY_PASSPHRASE", "wrong")
    wrong = PersistedKeyProvider(path)
    with pytest.raises(KeyProviderError, match="integrity|passphrase"):
        wrong.sign(b"payload")


def test_persisted_provider_refuses_overwrite(tmp_path, monkeypatch):
    monkeypatch.setenv("EAGLE_EYE_PILOT_KEY_PASSPHRASE", "p")
    kp = PersistedKeyProvider(tmp_path / "k.json")
    kp.initialize()
    with pytest.raises(KeyProviderError, match="refusing to overwrite"):
        kp.initialize()


def test_cloud_kms_shapes_fail_closed(monkeypatch):
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION",
                "GOOGLE_APPLICATION_CREDENTIALS"):
        monkeypatch.delenv(var, raising=False)
    for cfg in (AwsKmsConfig(), GcpKmsConfig()):
        assert cfg.state() == "DISABLED_NO_CREDENTIALS"
        with pytest.raises(KeyProviderError, match="NOT ESTABLISHED"):
            cfg.sign(b"x")
        assert cfg.verify(b"x", b"sig") is False
        assert cfg.health()["evidence_class"] == "NOT ESTABLISHED"
    # flipping "credentials present" alone STILL cannot claim success:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA-FAKE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    with pytest.raises(KeyProviderError, match="remote signature verification"):
        AwsKmsConfig().sign(b"x")


def test_kms_status_reports_not_established_production():
    status = kms_status()
    assert status["production_kms"] == "NOT ESTABLISHED"
    assert status["providers"]["aws_kms"]["state"] == "DISABLED_NO_CREDENTIALS"
