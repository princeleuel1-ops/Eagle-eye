# V10 REPAIR MAP — mission item → change → enforcing evidence

| # | Mission item | Change | Enforcing evidence |
|---|---|---|---|
| 1 | A live-tenant path must exist behind the authorized-ingest seam | `LiveShadowConduit` drives the UNCHANGED `IngestBoundary` (signatures/contract/quarantine/provenance) via a connector seam + scope filter | `test_conduit_drives_unchanged_boundary_and_labels_fixture`, `..._filters_out_of_scope_sources`; gate ingest stage |
| 2 | LIVE must be unreachable without signed data authority | `DataAuthorityConfig` + `verify_authority_config`: production class, pinned-key signature, dual authorizers, non-fixture LIVE tenant, legal basis, validity window — else DISARMED | config tests; gate stages unsigned/single/fixture/expired/tampered |
| 3 | The LIVE label must never be forged or leaked in either direction | `data_class_for` requires all three live signals; any partial claim is a hard refusal | `test_live_requires_all_three_signals`, `test_partial_live_claim_is_hard_refused` (5); gate `partial_live_claim_refused` |
| 4 | Live connectors must default to fail-closed | `NullLiveFeedConnector` refuses (production default); `ReplayFileFeedConnector` for rehearsal only, attests replay_fixture | `test_null_connector_is_fail_closed`; gate `null_connector_fail_closed` |
| 5 | LIVE data admits shadow actions only | `require_shadow_only` interlock on top of globally disabled execution | `test_shadow_only_interlock`; gate `shadow_only_interlock_under_live` |
| 6 | A full synthetic dress rehearsal must prove READY | `scripts/run_live_shadow_rehearsal.py`, 14 stages, `LIVE_REACHABLE=false` | `live-shadow-rehearsal` gate (31st) |
| 7 | The operator must have an exact activation ceremony | `receipts_v10/LIVE_ACTIVATION_RUNBOOK.md` (preconditions, ceremony, abort switch, honest non-grants) | runbook shipped |
| 8 | Honesty structural | walls gain a READY spine but W2 explicitly stands; EXTERNALLY VALIDATED stays nothing; external_action false | `V10_HONEST_REMAINING_WALLS.md`; receipt fields |

Files added: `src/eagle_eye/live_shadow.py`,
`scripts/run_live_shadow_rehearsal.py`, `tests/test_live_shadow.py`,
`receipts_v10/` (5 docs incl. runbook).
Files changed (additive): `Makefile`, `scripts/run_all_gates.py` (gate 31),
`LOCAL_REPRODUCTION.md`, `DOWNLOAD_MANIFEST_SHA256.txt` (regenerated).
