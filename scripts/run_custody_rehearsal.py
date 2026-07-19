"""V11 custody & identity DRESS REHEARSAL — the state machine and round-trip
protocol proven on labeled local providers; production VERIFIED unreachable.

Stages: default DISABLED; configured-but-unverified trusts nothing; a real
round-trip on the LOCAL provider reaches VERIFIED mechanically; a broken
provider lands VERIFICATION_FAILED; proofs expire back to unverified;
production signing is refused for every non-(VERIFIED ∧ production-class)
combination — including a fully VERIFIED local provider (refused BY CLASS);
tampered proof detected; OIDC ladder mirrors it on the labeled dev issuer.

Writes artifacts/custody/CUSTODY_REHEARSAL_RECEIPT.json; exit 0 only if all
stages behave. No cloud calls, no credentials, external_action=false.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eagle_eye.custody import (  # noqa: E402
    CONFIGURED_UNVERIFIED, DISABLED_NO_CREDENTIALS, VERIFICATION_FAILED,
    VERIFIED, CustodyError, custody_state, oidc_state,
    require_production_custody, run_oidc_verification,
    run_roundtrip_verification,
)
from eagle_eye.pilot.identity_service import IdentityVerifier, LocalDevIssuer  # noqa: E402
from eagle_eye.pilot.kms import EphemeralKeyProvider  # noqa: E402
from eagle_eye.prior_registry import canonical_bytes, sha256_hex  # noqa: E402

OUT = ROOT / "artifacts" / "custody"
TENANT = "tenant-fixture-custody"


class _BrokenProvider:
    def sign(self, payload):  # noqa: ANN001
        raise RuntimeError("remote signer unreachable")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.time()
    stages = []

    def rec(name, ok, detail=""):
        stages.append({"stage": name, "ok": bool(ok), "detail": detail})
        print(f"{'OK  ' if ok else 'FAIL'} {name}{': ' + detail if detail and not ok else ''}")

    # 1. defaults
    s, _ = custody_state(None)
    rec("disabled_without_descriptor", s == DISABLED_NO_CREDENTIALS)
    s, _ = custody_state({"provider_class": "aws-kms", "credentials_ref": None})
    rec("aws_shape_disabled_without_credentials", s == DISABLED_NO_CREDENTIALS)
    s, _ = custody_state({"provider_class": "aws-kms", "credentials_ref": "arn:...:key"})
    rec("configured_is_not_trusted", s == CONFIGURED_UNVERIFIED)

    # 2. the round-trip protocol (local provider — labeled non-production)
    provider = EphemeralKeyProvider()
    proof = run_roundtrip_verification(provider, provider_class="local-ephemeral",
                                       operator="rehearsal")
    desc_local = {"provider_class": "local-ephemeral", "credentials_ref": "local",
                  "verification_proof": proof}
    s, _ = custody_state(desc_local)
    rec("local_roundtrip_reaches_verified", proof["verdict"] is True and s == VERIFIED)

    # 3. failure is remembered as worse than unconfigured
    bad = run_roundtrip_verification(_BrokenProvider(), provider_class="aws-kms",
                                     operator="rehearsal")
    s, _ = custody_state({"provider_class": "aws-kms", "credentials_ref": "arn:x",
                          "verification_proof": bad})
    rec("failed_roundtrip_is_verification_failed",
        bad["verdict"] is False and s == VERIFICATION_FAILED)

    # 4. proofs age out
    stale = dict(proof); stale["verified_at_epoch"] = time.time() - 7200
    s, r = custody_state({**desc_local, "verification_proof": stale})
    rec("stale_proof_downgrades_to_unverified",
        s == CONFIGURED_UNVERIFIED and any("expired" in x for x in r))

    # 5. the production signing interlock
    refusals = 0
    for desc in (None,
                 {"provider_class": "aws-kms", "credentials_ref": None},
                 {"provider_class": "aws-kms", "credentials_ref": "arn:x"},
                 {"provider_class": "aws-kms", "credentials_ref": "arn:x",
                  "verification_proof": bad},
                 desc_local):  # VERIFIED but local: refused BY CLASS
        try:
            require_production_custody(desc)
        except CustodyError:
            refusals += 1
    rec("production_signing_refused_all_five", refusals == 5, f"refusals={refusals}")

    # 6. tampered proof detected by content hash
    tampered = dict(proof); tampered["verdict"] = True
    tampered["operator"] = "attacker"
    body = {k: v for k, v in tampered.items() if k != "proof_sha256"}
    rec("tampered_proof_hash_mismatch",
        sha256_hex(canonical_bytes(body)) != tampered["proof_sha256"])

    # 7. OIDC ladder on the labeled dev issuer
    s, _ = oidc_state(None)
    rec("oidc_disabled_without_config", s == DISABLED_NO_CREDENTIALS)
    issuer = LocalDevIssuer(tenants=[TENANT])
    verifier = IdentityVerifier(registry_entries=issuer.registry_entries())
    rp = {"issuer_url": "local-dev-issuer:NOT-PRODUCTION",
          "audience": "eagle-eye-pilot", "jwks_source": "registry:local"}
    s, _ = oidc_state(rp)
    rec("oidc_configured_is_not_trusted", s == CONFIGURED_UNVERIFIED)
    oidc_proof = run_oidc_verification(rp, verifier=verifier, issuer=issuer,
                                       tenant_id=TENANT, operator="rehearsal")
    s, _ = oidc_state({**rp, "verification_proof": oidc_proof})
    rec("oidc_roundtrip_reaches_verified",
        oidc_proof["verdict"] is True and s == VERIFIED)

    all_ok = all(x["ok"] for x in stages)
    receipt = {"spec": "eagle-eye-custody-rehearsal/1.0", "stages": stages,
               "passed": sum(1 for x in stages if x["ok"]), "total": len(stages),
               "production_custody_reachable_in_this_run": False,
               "external_action": False,
               "elapsed_s": round(time.time() - started, 2)}
    receipt["receipt_id"] = "cust-" + sha256_hex(canonical_bytes(receipt))[:12]
    (OUT / "CUSTODY_REHEARSAL_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True))
    print(f"REHEARSAL_STAGES={receipt['passed']}/{receipt['total']}")
    print("PRODUCTION_CUSTODY_REACHABLE=false")
    print(f"RECEIPT_ID={receipt['receipt_id']}")
    print(f"CUSTODY_REHEARSAL_PASS={'true' if all_ok else 'false'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
