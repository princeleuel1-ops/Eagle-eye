# V6 REPAIR MAP — mission item → change → enforcing evidence

Traces each V6 mission item to its implementation and the test/gate that
enforces it. "Carried" = inherited unchanged from the merged V5 kernel and
re-verified by the V6 canonical gate.

## Baseline provenance
- Base = authoritative merged V5 source, archive SHA-256
  `cee96b4fbff020955a93aab6743b49d26c1acfc5d5468480a160335f3bd7944b`.
- `FABLE_V5_LOCAL_CORRECTIONS.patch` applied (adapted to V6): `.gitignore`
  now ignores `artifacts/prediction-court/*` (and the V6 artifact dirs); the
  aggregate gate writes `artifacts/check/V6_GATE_RESULTS.json` with spec
  `v6-canonical-gate/6.0`; `LOCAL_REPRODUCTION.md` updated to V6 counts.
- Files intentionally changed from the V5 archive tree (all others
  byte-identical, diff-verified): `.gitignore`, `DOWNLOAD_MANIFEST_SHA256.txt`,
  `Makefile`, `pyproject.toml`, `scripts/build_package.py`,
  `scripts/run_all_gates.py`, `scripts/verify_package.py`,
  `scripts/browser_verification.py` (additive Chromium-args hook, below),
  `src/eagle_eye/identity.py` (additive nbf),
  `src/eagle_eye/server.py` (pilot API), `web/index.html` (pilot link, styled
  in `web/styles.css` to honor the cockpit CSP).

## Portability hardening (setup + browser, honest — not hiding the environment)
- **Evaluator socket length.** AF_UNIX paths are capped (~104 macOS / ~108
  Linux). A pilot home nested under a long/deep path made the home-relative
  socket exceed the limit and the evaluator `bind()` failed in clean
  extraction. Fix: `evaluator_socket_path(home)` derives a short deterministic
  socket under the system temp dir (shared by launcher + client), with an
  `EAGLE_EYE_PILOT_SOCKET` override. Regression: `tests/test_evaluator_
  isolation.py::test_evaluator_socket_path_stays_under_af_unix_limit`.
- **Headless Chromium on a shm-starved container.** A tiny `/dev/shm` crashes
  Chromium's multiprocess renderer ("Page crashed"). Both browser harnesses
  read `EAGLE_EYE_CHROMIUM_ARGS` (space-separated, default EMPTY) so a
  constrained host can pass `--single-process --disable-dev-shm-usage` etc.
  Default is unchanged real multiprocess Chromium — exactly the verified Mac
  run. This is a launcher flag, not an assertion change.

## V6 mission items

| # | Mission item | Change | Enforced by |
|---|---|---|---|
| 1 | Durable storage | `src/eagle_eye/pilot/storage.py` + `objectstore.py`: migrations, idempotency, append-only audit + head commitments, backup/restore; Postgres/S3 fail-closed shapes | `tests/test_pilot_storage.py`, `test_pilot_objectstore_observability.py`; `pilot-smoke`, `failure-court` |
| 2 | Identity | `src/eagle_eye/pilot/identity_service.py`: dev issuer, verifier, nbf (additive in `identity.py`), role map, rotation, revocation; OIDC fail-closed shape | `tests/test_pilot_identity_kms.py`; failure-court identity cases |
| 3 | Evaluator isolation | `src/eagle_eye/pilot/evaluator_service.py`: unix-socket service + client, durable looks, crash/restart no-refund, irreversible lifecycle | `tests/test_evaluator_isolation.py` (real subprocess); failure-court SIGKILL case |
| 4 | KMS seam | `src/eagle_eye/pilot/kms.py`: provider interface, ephemeral + persisted providers, AWS/GCP fail-closed | `tests/test_pilot_identity_kms.py` KMS block |
| 5 | Authorized ingestion | `src/eagle_eye/pilot/ingest.py`: signed contract, quarantine, replay/idempotency, corrections, provenance, connectors | `tests/test_pilot_ingest.py`; failure-court ingest cases |
| 6 | Shadow lifecycle | `src/eagle_eye/pilot/shadow.py`: 7-state machine, dual control, expiry, evidence freezing, idempotent dispatch, outcome, replay, export | `tests/test_pilot_shadow.py`; failure-court approval/substitution cases |
| 7 | Observability | `src/eagle_eye/pilot/observability.py`: JSON logs, correlation, redaction, metrics, health | `tests/test_pilot_objectstore_observability.py`; failure-court secrets-in-logs |
| 8 | Operator cockpit | `web/pilot.html` + `pilot.js` + `pilot.css`; `src/eagle_eye/pilot/service.py` API; `server.py` routing | `scripts/pilot_browser_verification.py` (desktop+mobile) |
| 9 | Failure court | `scripts/failure_court.py` (39 executed cases) | `failure-court` gate |
| 10 | Operations | `src/eagle_eye/pilot/ops.py` + Makefile `pilot-*` targets; `scripts/pilot_smoke.py`; `scripts/pilot_performance.py` | `pilot-smoke`, `pilot-performance` gates |

## Canonical gate wiring
`scripts/run_all_gates.py` appends four V6 gates before `package-verify`:
`pilot-smoke`, `failure-court`, `pilot-browser`, `pilot-performance`. Pilot
unit + evaluator-process tests run inside the existing `tests` gate (not
double-run). The completeness guard still refuses PASS if any gate is missing
or non-zero. Total: 25 gates.

## No-weakening statement
All V6 changes are additive. No inherited gate was removed or loosened; no
hard test was deleted or weakened. The pilot browser gate classifies the
deliberately-exercised self-approval refusal (401/403/409) as an EXPECTED
refusal, separate from unexpected failures (5xx, asset 404, network, JS
exceptions) which still fail the gate — this is a precise honest split,
recorded transparently in the browser result JSON, not a relaxed threshold.
