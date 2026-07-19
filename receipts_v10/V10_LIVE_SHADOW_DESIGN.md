# V10 — THE LIVE-SHADOW SPINE
## Built to READY; armed only by the operator's key

Base: the V9 tree `56e1110581f09ad95f675ad1057764d182d590e1` (30 gates,
395 tests, stranger's verifier). V10 is additive.

## 1. The wall, verbatim

"W2 — Everything is synthetic. NO live-data evidence anywhere." and
"Live pilot … NOT ESTABLISHED." This rung does NOT close W2 — closing it
needs real data under real authority, which lives outside this repository.
V10 builds everything up to that key and refuses to fake the rest.

## 2. The instrument (`src/eagle_eye/live_shadow.py`)

- **DataAuthorityConfig** (`eagle-eye-data-authority/1.0`) — the single
  artifact that arms live ingestion, and its fail-closed verifier. LIVE
  arming requires ALL of: production class, signature by an out-of-band
  pinned authority key, dual distinct authorizers, a non-fixture LIVE
  tenant, a non-empty legal basis, and a valid time window. Any failure →
  DISARMED with recorded reasons. A config can never vouch for its own
  signer (keys pinned externally).
- **Connector seam** — `NullLiveFeedConnector` (fail-closed production
  default, mirrors NullActionExecutor) and `ReplayFileFeedConnector` (dress
  rehearsal; attests `origin=replay_fixture`, can never mint LIVE).
- **The labeling guard** `data_class_for` — the load-bearing safety
  property: LIVE demands armed-live AND connector origin=live AND a LIVE
  tenant; ANY partial live signal is a HARD REFUSAL, never a silent relabel
  in either direction. This is the one function that can emit "LIVE", and it
  is exhaustively tested (5 partial-claim refusals).
- **`require_shadow_only`** — the live interlock: under LIVE data, only
  shadow actions; external stays globally disabled.
- **LiveShadowConduit** — arming → connector poll → scope filter (sources,
  kinds) → the UNCHANGED `IngestBoundary` (signatures, contract, quarantine,
  provenance) → data-class-stamped records + a signed-content run summary.

## 3. The gate (required gate 31: `live-shadow-rehearsal`)

`scripts/run_live_shadow_rehearsal.py` — 14 stages, all green in the sealing
run: disarmed-by-default; null connector fail-closed; fixture arming drives
8 real envelopes through the unchanged boundary (0 quarantined); LIVE
unreachable at fixture arm; partial-live claim refused; valid production
config arms LIVE; unsigned / single-approver / fixture-tenant / expired /
tampered production configs all DISARMED with the right reasons; shadow-only
interlock holds. `LIVE_REACHABLE=false` by construction.

## 4. Evidence classes

- Authority verification, the labeling guard, connector posture, conduit
  scope filtering, and the shadow-only interlock: MECHANICALLY VERIFIED
  (`tests/test_live_shadow.py`, 18 tests; the gate, 14 stages).
- The rehearsal's ingested data: SYNTHETIC, labeled FIXTURE end to end.
- LIVE data evidence: NOT ESTABLISHED — unreachable without the operator's
  signed production authority (LIVE_ACTIVATION_RUNBOOK.md).
- EXTERNALLY VALIDATED: nothing. Live data is not external proof; only a
  stranger running the V9 verifier on a published bundle is.

## 5. Honest boundary

READY ≠ live. The spine is complete, fail-closed, and rehearsed; W2 stands
until the key ceremony runs on real authority. No live connector to a real
feed ships here (deployment-specific). External execution remains disabled;
V10 only adds the live-specific shadow interlock on top of it.

## 6. Standing prohibitions honored

Additive only; the pilot ingest/decision/approval/dispatch machinery is
untouched (its own gates still pass); no gate lowered; `external_action=false`
throughout; no key simulated (the rehearsal mints a clearly-labeled
test_fixture authority and a synthetic operator key that exists only for the
rehearsal).
