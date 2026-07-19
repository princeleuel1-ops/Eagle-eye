# LIVE ACTIVATION RUNBOOK — the key ceremony for V10

The V10 spine is READY and DISARMED. This runbook is the ONLY path to LIVE
data. Nothing in the repository can perform it; it requires YOUR data
authority. Read every step — arming this seam means real data enters the
system for the first time.

## What you are signing (and why the machine cannot)
LIVE ingestion arms only on a `eagle-eye-data-authority/1.0` config that is:
1. `authority_class: "production"`,
2. signed by an Ed25519 key whose id you have pinned OUT-OF-BAND into the
   deployment (never carried in the repo),
3. dual-authorized — `authorized_by` lists ≥ 2 distinct approvers,
4. targeted at a NON-fixture tenant registered with `data_class: "LIVE"`,
5. carrying a non-empty `legal_basis`, and
6. inside its `valid_from_epoch`..`valid_until_epoch` window.
Fail any one → the seam stays DISARMED with the reason recorded. The verifier
is `eagle_eye.live_shadow.verify_authority_config`; read it before you trust it.

## Preconditions (you provide)
- [ ] A lawful basis to ingest the tenant's data (DPA / contract reference).
- [ ] An Ed25519 authority keypair generated on hardware you control. Pin the
      PUBLIC key id in the deployment's trusted-authority set. The PRIVATE key
      never touches this repo or any Eagle Eye process.
- [ ] A second approver (dual control) with their own recorded identity.
- [ ] A live feed connector implementing the `poll()`/`attestation()` seam and
      attesting `origin: "live"`. (The repo ships only NullLiveFeedConnector
      (fail-closed) and ReplayFileFeedConnector (fixtures) — a real connector
      is deployment-specific and lands outside this handoff.)
- [ ] The target tenant created with `data_class="LIVE"` (not FIXTURE).

## The ceremony
1. Rehearse first, unchanged: `make live-shadow-rehearsal` → expect
   `LIVE_SHADOW_REHEARSAL_PASS=true`, `LIVE_REACHABLE=false`. This proves the
   pipe on synthetic data with zero live exposure.
2. Author the production config (all fields in `_REQUIRED_FIELDS`), then have
   BOTH approvers sign off; record both in `authorized_by`.
3. Sign the config with your pinned authority key
   (`sign_authority_config` run on YOUR machine, YOUR key).
4. Deploy the signed config + the pinned public key id + the live connector.
5. Verify arming: `verify_authority_config(cfg, trusted_authority_keys=…,
   fixture_tenants=…)` must return `arm_state="ARMED_LIVE"` with empty reasons.
6. First hour, shadow-only: run the conduit; confirm receipts carry
   `data_class="LIVE"`, `require_shadow_only` is enforced, and NO action ever
   leaves shadow (external execution remains globally disabled — V12 territory,
   not this rung).

## Abort switch
Remove/expire the config, or unpin the authority key → the seam returns to
DISARMED on the next verification, immediately and fail-closed. Revoking the
pinned key id disarms every config it signed at once.

## What this does NOT grant
- Not external execution (still disabled; shadow-only interlock added here).
- Not a production KMS/OIDC posture (that is V11's ceremony).
- Not external validation. Even live-armed, a run is only "externally
  validated" once a stranger verifies its published bundle with the V9
  verifier. LIVE data ≠ external proof.

## The honest line
Until this ceremony is performed on real authority, W2 stands: everything is
synthetic, and the LIVE class is unreachable by construction. The machine is
ready; the authority is yours.
