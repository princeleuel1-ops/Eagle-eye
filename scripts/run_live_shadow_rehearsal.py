"""V10 live-shadow DRESS REHEARSAL — the full live path exercised end to end
on a TEST-FIXTURE authority, proving the machine is READY while LIVE stays
unreachable.

It demonstrates, in one deterministic run:
  1. DISARMED by default: with no authority config, the conduit refuses.
  2. Fixture arming works: a test_fixture authority config, signed by a
     pinned key, arms the seam to ARMED_TEST_FIXTURE and drives real
     envelopes through the UNCHANGED IngestBoundary via the replay connector.
  3. LIVE stays unreachable: even fully armed at test-fixture, and even if a
     connector lied about origin=live, data_class_for refuses to mint LIVE
     without a production authority + live origin + live tenant.
  4. Production arming is gated: an unsigned / single-approver / fixture-
     tenant / expired production config all leave the seam DISARMED with
     recorded reasons.
  5. Shadow-only interlock holds under (hypothetical) LIVE.

Writes artifacts/live_shadow/LIVE_SHADOW_REHEARSAL_RECEIPT.json. Exit 0 only
if every stage behaves exactly as the READY-but-unarmed contract requires.
No network, no real feed, external_action=false throughout.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eagle_eye.live_shadow import (  # noqa: E402
    ARM_DISARMED, ARM_LIVE, ARM_TEST_FIXTURE, DataAuthorityError,
    LiveShadowConduit, NullLiveFeedConnector, ReplayFileFeedConnector,
    data_class_for, require_shadow_only, sign_authority_config,
    verify_authority_config,
)
from eagle_eye.pilot.ingest import IngestBoundary, SyntheticConnector  # noqa: E402
from eagle_eye.pilot.kms import EphemeralKeyProvider  # noqa: E402
from eagle_eye.pilot.storage import PilotStorage  # noqa: E402
from eagle_eye.prior_registry import canonical_bytes, sha256_hex  # noqa: E402
from eagle_eye.signing import generate_demo_keypair, key_id  # noqa: E402

OUT = ROOT / "artifacts" / "live_shadow"
TENANT = "tenant-fixture-live-rehearsal"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.time()
    stages: list[dict] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        stages.append({"stage": name, "ok": bool(ok), "detail": detail})
        print(f"{'OK  ' if ok else 'FAIL'} {name}{': ' + detail if detail and not ok else ''}")

    # operator authority key (pinned out-of-band); repo never holds it in prod
    auth_priv, auth_pub = generate_demo_keypair()
    auth_kid = key_id(auth_pub)
    pinned = {auth_kid: auth_pub}
    fixture_tenants = (TENANT,)

    # ---- stage 1: disarmed by default --------------------------------------
    v_none = verify_authority_config(None, trusted_authority_keys=pinned)
    record("disarmed_without_config", v_none["arm_state"] == ARM_DISARMED)
    try:
        LiveShadowConduit(boundary=None, connector=NullLiveFeedConnector(), verification=v_none)
        record("conduit_refuses_when_disarmed", False, "conduit constructed while disarmed")
    except DataAuthorityError:
        record("conduit_refuses_when_disarmed", True)
    try:
        NullLiveFeedConnector().poll()
        record("null_connector_fail_closed", False)
    except Exception:
        record("null_connector_fail_closed", True)

    # ---- stage 2: fixture arming + real ingest through the unchanged seam ---
    store = PilotStorage(OUT / "rehearsal.sqlite3")
    store.migrate()
    store.ensure_tenant(TENANT, display_name="Live Rehearsal Fixture",
                        data_class="FIXTURE")
    signer = EphemeralKeyProvider()
    feed = SyntheticConnector(source_id="live-syn-1", tenant_id=TENANT, seed=707)
    boundary = IngestBoundary(store, signer=signer,
                              sources={"live-syn-1": feed.source_registration()})
    envelopes = feed.events(8)
    replay_path = OUT / "recorded_feed.jsonl"
    replay_path.write_text("\n".join(json.dumps(e) for e in envelopes) + "\n")

    fixture_cfg = sign_authority_config({
        "spec": "eagle-eye-data-authority/1.0", "authority_class": "test_fixture",
        "tenant_id": TENANT, "source_ids": ["live-syn-1"],
        "event_kinds": ["disruption_signal"], "rate_cap_per_hour": 10000,
        "retention_days": 1, "legal_basis": "synthetic rehearsal — no real data",
        "authorized_by": [{"sub": "rehearsal-operator"}],
        "valid_from_epoch": time.time() - 60, "valid_until_epoch": time.time() + 3600,
    }, auth_priv, auth_pub)
    v_fix = verify_authority_config(fixture_cfg, trusted_authority_keys=pinned,
                                    fixture_tenants=fixture_tenants)
    record("fixture_config_arms_test_fixture", v_fix["arm_state"] == ARM_TEST_FIXTURE,
           json.dumps(v_fix.get("reasons")))
    conduit = LiveShadowConduit(boundary=boundary,
                                connector=ReplayFileFeedConnector(replay_path),
                                verification=v_fix)
    summary = conduit.run_once(tenant_data_class="FIXTURE")
    record("rehearsal_ingests_through_unchanged_boundary",
           summary["accepted"] == 8 and summary["data_class"] == "FIXTURE"
           and summary["quarantined"] == 0, json.dumps({k: summary[k] for k in
           ("accepted", "quarantined", "out_of_scope", "data_class")}))

    # ---- stage 3: LIVE unreachable -----------------------------------------
    # armed at fixture + replay origin: must be FIXTURE, never LIVE
    dc = data_class_for(arm_state=ARM_TEST_FIXTURE,
                        attestation={"origin": "replay_fixture"},
                        tenant_data_class="FIXTURE")
    record("live_unreachable_at_fixture_arm", dc == "FIXTURE")
    # a lying connector (origin=live) without production arm/tenant: hard refuse
    try:
        data_class_for(arm_state=ARM_TEST_FIXTURE, attestation={"origin": "live"},
                       tenant_data_class="FIXTURE")
        record("partial_live_claim_refused", False, "mislabel not refused")
    except DataAuthorityError:
        record("partial_live_claim_refused", True)

    # ---- stage 4: production arming gated ----------------------------------
    def prod_cfg(**over):
        base = {"spec": "eagle-eye-data-authority/1.0", "authority_class": "production",
                "tenant_id": "tenant-real-acme", "source_ids": ["acme-edi"],
                "event_kinds": ["disruption_signal"], "rate_cap_per_hour": 500,
                "retention_days": 30, "legal_basis": "DPA-2026-ACME §4",
                "authorized_by": [{"sub": "ciso"}, {"sub": "dpo"}],
                "valid_from_epoch": time.time() - 60,
                "valid_until_epoch": time.time() + 3600}
        base.update(over)
        return base

    signed_prod = sign_authority_config(prod_cfg(), auth_priv, auth_pub)
    v_prod = verify_authority_config(signed_prod, trusted_authority_keys=pinned,
                                     fixture_tenants=fixture_tenants)
    record("valid_production_config_arms_live", v_prod["arm_state"] == ARM_LIVE,
           json.dumps(v_prod.get("reasons")))

    # unsigned
    unsigned = prod_cfg(); unsigned.update({"authority_key_id": "ed25519:deadbeef",
                                            "signature_b64": "AAAA"})
    r1 = verify_authority_config(unsigned, trusted_authority_keys=pinned,
                                 fixture_tenants=fixture_tenants)
    record("unpinned_signer_disarmed", r1["arm_state"] == ARM_DISARMED)
    # single approver
    single = sign_authority_config(prod_cfg(authorized_by=[{"sub": "ciso"}]),
                                   auth_priv, auth_pub)
    r2 = verify_authority_config(single, trusted_authority_keys=pinned,
                                 fixture_tenants=fixture_tenants)
    record("single_approver_disarmed",
           r2["arm_state"] == ARM_DISARMED
           and any("dual" in x for x in r2["reasons"]))
    # fixture tenant under production class
    fixture_target = sign_authority_config(prod_cfg(tenant_id=TENANT), auth_priv, auth_pub)
    r3 = verify_authority_config(fixture_target, trusted_authority_keys=pinned,
                                 fixture_tenants=fixture_tenants)
    record("production_on_fixture_tenant_disarmed",
           r3["arm_state"] == ARM_DISARMED
           and any("fixture" in x for x in r3["reasons"]))
    # expired
    expired = sign_authority_config(
        prod_cfg(valid_from_epoch=time.time() - 7200,
                 valid_until_epoch=time.time() - 3600), auth_priv, auth_pub)
    r4 = verify_authority_config(expired, trusted_authority_keys=pinned,
                                 fixture_tenants=fixture_tenants)
    record("expired_config_disarmed",
           r4["arm_state"] == ARM_DISARMED
           and any("validity" in x for x in r4["reasons"]))
    # tampered field after signing
    tampered = dict(signed_prod); tampered["rate_cap_per_hour"] = 999999
    r5 = verify_authority_config(tampered, trusted_authority_keys=pinned,
                                 fixture_tenants=fixture_tenants)
    record("tampered_config_disarmed",
           r5["arm_state"] == ARM_DISARMED
           and any("signature" in x for x in r5["reasons"]))

    # ---- stage 5: shadow-only interlock under LIVE -------------------------
    require_shadow_only("LIVE", "shadow")  # ok
    try:
        require_shadow_only("LIVE", "external")
        record("shadow_only_interlock_under_live", False)
    except DataAuthorityError:
        record("shadow_only_interlock_under_live", True)

    all_ok = all(s["ok"] for s in stages)
    receipt = {
        "spec": "eagle-eye-live-shadow-rehearsal/1.0",
        "tenant": TENANT, "stages": stages,
        "passed": sum(1 for s in stages if s["ok"]), "total": len(stages),
        "conduit_summary": summary,
        "live_reachable_in_this_run": False,
        "external_action": False,
        "elapsed_s": round(time.time() - started, 2),
    }
    receipt["receipt_id"] = "live-" + sha256_hex(canonical_bytes(receipt))[:12]
    (OUT / "LIVE_SHADOW_REHEARSAL_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True))
    store.close()
    print(f"REHEARSAL_STAGES={receipt['passed']}/{receipt['total']}")
    print(f"LIVE_REACHABLE={str(receipt['live_reachable_in_this_run']).lower()}")
    print(f"RECEIPT_ID={receipt['receipt_id']}")
    print(f"LIVE_SHADOW_REHEARSAL_PASS={'true' if all_ok else 'false'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
