import pytest

from eagle_eye.identity import IdentityError, issue_assertion, verify_assertion
from eagle_eye.signing import generate_demo_keypair, key_id

NOW = 1_700_000_000


def _identity():
    private_key, public_key = generate_demo_keypair()
    issuer = "https://identity.fixture.invalid"
    registry = {
        "trusted_issuers": [
            {
                "issuer": issuer,
                "key_id": key_id(public_key),
                "public_key_pem": public_key.decode(),
                "audiences": ["eagle-eye-zenith"],
                "allowed_tenants": ["tenant-a"],
                "max_ttl_seconds": 900,
            }
        ]
    }
    claims = {
        "iss": issuer,
        "aud": "eagle-eye-zenith",
        "sub": "analyst-1",
        "tenant_id": "tenant-a",
        "roles": ["analyst"],
        "iat": NOW,
        "exp": NOW + 300,
        "jti": "session-1",
    }
    return private_key, public_key, registry, claims


def test_valid_assertion_becomes_governance_principal():
    private_key, public_key, registry, claims = _identity()
    token = issue_assertion(claims, private_key=private_key, public_key=public_key)
    principal = verify_assertion(
        token,
        registry=registry,
        expected_audience="eagle-eye-zenith",
        expected_tenant="tenant-a",
        now=NOW + 10,
        revoked_jtis=set(),
    )
    assert principal == {
        "id": "analyst-1",
        "tenant_id": "tenant-a",
        "roles": ["analyst"],
        "session_id": "session-1",
        "issuer": "https://identity.fixture.invalid",
    }


def test_forged_assertion_is_rejected():
    private_key, public_key, registry, claims = _identity()
    token = issue_assertion(claims, private_key=private_key, public_key=public_key)
    forged = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(IdentityError, match="signature"):
        verify_assertion(forged, registry=registry, expected_audience="eagle-eye-zenith", expected_tenant="tenant-a", now=NOW + 10, revoked_jtis=set())


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"exp": NOW - 1}, "expired"),
        ({"exp": NOW + 901}, "lifetime"),
        ({"aud": "other-service"}, "audience"),
        ({"tenant_id": "tenant-b"}, "tenant"),
    ],
)
def test_invalid_claims_are_rejected(change, message):
    private_key, public_key, registry, claims = _identity()
    claims.update(change)
    token = issue_assertion(claims, private_key=private_key, public_key=public_key)
    with pytest.raises(IdentityError, match=message):
        verify_assertion(token, registry=registry, expected_audience="eagle-eye-zenith", expected_tenant="tenant-a", now=NOW, revoked_jtis=set())


def test_revoked_session_is_rejected():
    private_key, public_key, registry, claims = _identity()
    token = issue_assertion(claims, private_key=private_key, public_key=public_key)
    with pytest.raises(IdentityError, match="revoked"):
        verify_assertion(token, registry=registry, expected_audience="eagle-eye-zenith", expected_tenant="tenant-a", now=NOW, revoked_jtis={"session-1"})


def test_untrusted_issuer_key_is_rejected():
    private_key, public_key, registry, claims = _identity()
    other_private, other_public = generate_demo_keypair()
    token = issue_assertion(claims, private_key=other_private, public_key=other_public)
    with pytest.raises(IdentityError, match="trusted issuer"):
        verify_assertion(token, registry=registry, expected_audience="eagle-eye-zenith", expected_tenant="tenant-a", now=NOW, revoked_jtis=set())
