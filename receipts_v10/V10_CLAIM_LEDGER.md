# V10 CLAIM LEDGER — Live-Shadow Spine (delta over V9)

| Area | Claim | Class | Evidence |
|---|---|---|---|
| Authority arming | LIVE arms only on production class + pinned-key signature + dual authorizers + non-fixture LIVE tenant + legal basis + valid window; any failure DISARMS with reasons | MECHANICALLY VERIFIED | `tests/test_live_shadow.py` (config block); gate stages unsigned/single/fixture/expired/tampered |
| No self-vouching | a config cannot authorize its own signer; authority keys are pinned out-of-band | MECHANICALLY VERIFIED | `test_untrusted_signer_disarms` |
| Tamper evidence | any field mutated after signing DISARMS on signature failure | MECHANICALLY VERIFIED | `test_tamper_after_signing_disarms`; gate `tampered_config_disarmed` |
| LIVE labeling guard | LIVE requires armed-live AND origin=live AND LIVE tenant; every partial live claim is HARD REFUSED (never silently relabeled) | MECHANICALLY VERIFIED | `test_partial_live_claim_is_hard_refused` (5 cases); gate `partial_live_claim_refused` |
| Connector posture | null connector fail-closed (production default); replay connector attests origin=replay_fixture and can never mint LIVE | MECHANICALLY VERIFIED | `test_null_connector_is_fail_closed`; guard tests |
| Unchanged ingest path | the conduit drives the EXISTING IngestBoundary (signatures/contract/quarantine/provenance) untouched; scope filter enforces sources/kinds | MECHANICALLY VERIFIED | `test_conduit_drives_unchanged_boundary_and_labels_fixture`, `test_conduit_filters_out_of_scope_sources`; gate ingest stage (8 accepted, 0 quarantined) |
| Shadow-only interlock | under LIVE data, only shadow action mode is admitted | MECHANICALLY VERIFIED | `test_shadow_only_interlock`; gate `shadow_only_interlock_under_live` |
| Dress rehearsal | full live path exercised on a test-fixture authority; LIVE unreachable in-run | MECHANICALLY VERIFIED; SYNTHETIC data | `live-shadow-rehearsal` gate, 14/14, `LIVE_REACHABLE=false` |

## Boundary (unchanged truths)

- **W2 stands.** LIVE data evidence NOT ESTABLISHED — unreachable without the
  operator's signed production authority (LIVE_ACTIVATION_RUNBOOK.md).
- Live pilot, revenue, customer value: NOT ESTABLISHED.
- External execution: disabled; V10 adds only the live shadow interlock.
- **EXTERNALLY VALIDATED: nothing.** `external_action=false` throughout.
