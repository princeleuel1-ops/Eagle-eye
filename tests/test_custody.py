"""V11 custody & identity: state ladder, round-trip protocol, and the
production signing interlock (refusal BY CLASS for local providers)."""

import time

import pytest

from eagle_eye.custody import (
    CONFIGURED_UNVERIFIED, DISABLED_NO_CREDENTIALS, VERIFICATION_FAILED,
    VERIFIED, CustodyError, custody_state, oidc_state,
    require_production_custody, run_roundtrip_verification,
)
from eagle_eye.pilot.kms import EphemeralKeyProvider


def _verified_local():
    proof = run_roundtrip_verification(EphemeralKeyProvider(),
                                       provider_class="local-ephemeral", operator="t")
    return {"provider_class": "local-ephemeral", "credentials_ref": "local",
            "verification_proof": proof}


def test_state_ladder_defaults():
    assert custody_state(None)[0] == DISABLED_NO_CREDENTIALS
    assert custody_state({"provider_class": "nonsense"})[0] == DISABLED_NO_CREDENTIALS
    assert custody_state({"provider_class": "gcp-kms"})[0] == DISABLED_NO_CREDENTIALS
    assert custody_state({"provider_class": "gcp-kms",
                          "credentials_ref": "proj/key"})[0] == CONFIGURED_UNVERIFIED


def test_roundtrip_reaches_verified_and_proof_is_content_hashed():
    desc = _verified_local()
    state, reasons = custody_state(desc)
    assert state == VERIFIED and reasons == []
    proof = desc["verification_proof"]
    assert proof["verdict"] is True and proof["proof_sha256"]
    assert proof["nonce"] and proof["signature_b64"]


def test_failed_roundtrip_is_worse_than_unconfigured():
    class Broken:
        def sign(self, payload):
            raise RuntimeError("unreachable")
    proof = run_roundtrip_verification(Broken(), provider_class="aws-kms", operator="t")
    assert proof["verdict"] is False and "error" in proof
    state, _ = custody_state({"provider_class": "aws-kms", "credentials_ref": "arn:x",
                              "verification_proof": proof})
    assert state == VERIFICATION_FAILED


def test_proofs_expire():
    desc = _verified_local()
    desc["verification_proof"] = dict(desc["verification_proof"],
                                      verified_at_epoch=time.time() - 7200)
    state, reasons = custody_state(desc)
    assert state == CONFIGURED_UNVERIFIED and any("expired" in r for r in reasons)


def test_production_interlock_refuses_everything_but_verified_production():
    with pytest.raises(CustodyError):
        require_production_custody(None)
    with pytest.raises(CustodyError):
        require_production_custody({"provider_class": "aws-kms",
                                    "credentials_ref": "arn:x"})
    # fully VERIFIED local provider: refused BY CLASS, not by state
    with pytest.raises(CustodyError, match="non-production by label"):
        require_production_custody(_verified_local())


def test_oidc_ladder_mirrors_custody():
    assert oidc_state(None)[0] == DISABLED_NO_CREDENTIALS
    rp = {"issuer_url": "x", "audience": "y", "jwks_source": "z"}
    assert oidc_state(rp)[0] == CONFIGURED_UNVERIFIED
    assert oidc_state({**rp, "verification_proof": {"verdict": False}})[0] \
        == VERIFICATION_FAILED
    assert oidc_state({**rp, "verification_proof": {
        "verdict": True, "verified_at_epoch": time.time()}})[0] == VERIFIED
    assert oidc_state({**rp, "verification_proof": {
        "verdict": True, "verified_at_epoch": time.time() - 7200}})[0] \
        == CONFIGURED_UNVERIFIED
