# V6 CLAIM LEDGER — Eagle Eye Zenith Pilot Forge (canonical, supersedes V1–V5)

This is the ONE current claim ledger. Prior ledgers are historical under
`receipts_v5/` and `receipts_superseded/`. Supersession is by location + this
document, never by editing a generated receipt after the fact.

Evidence classes (the only permitted vocabulary):
**MECHANICALLY VERIFIED** · **SYNTHETICALLY VERIFIED** · **THEOREM-CONDITIONAL** ·
**MODEL-CONDITIONAL ESTIMATE** · **EXTERNALLY VALIDATED** (currently NOTHING) ·
**NOT ESTABLISHED**.

Baseline: the authoritative merged V5 source (archive SHA-256
`cee96b4fbff020955a93aab6743b49d26c1acfc5d5468480a160335f3bd7944b`), plus the
four `FABLE_V5_LOCAL_CORRECTIONS.patch` coherence fixes, then the V6 pilot
spine. The V6 base tree was diffed against that archive: the only differences
are files intentionally changed for V6 (recorded in V6_REPAIR_MAP.md).

## A. New in V6 — the operational pilot spine

| Area | Change | Class | Evidence |
|---|---|---|---|
| Durable storage | tenant-bound SQLite reference backend: checksummed ordered migrations (apply from empty; drift refused), transactional idempotency (UNIQUE + txn), trigger-enforced append-only audit rows AND head-commitment table, backup + restore-check that recomputes every tenant audit head | MECHANICALLY VERIFIED | `tests/test_pilot_storage.py` (15); `failure-court` audit-mutation/truncation/restart cases |
| No cross-tenant path | every storage method requires tenant_id and binds it in SQL; the raw-SQL escape hatch refuses any query/params without the tenant binding | MECHANICALLY VERIFIED | `tests/test_pilot_storage.py::test_tenant_binding_is_mandatory_everywhere` |
| Object storage | content-addressed, verify-on-read, immutable local store; missing/corrupted objects fail closed | MECHANICALLY VERIFIED | `tests/test_pilot_objectstore_observability.py`; failure-court corrupt/missing cases |
| Identity/authorization | Ed25519 EE-SESSION assertions: issuer+key pinning, audience/tenant binding, exp + **nbf** + TTL policy, jti + issuer revocation; deny-by-default role→permission map; requester/approver separation | MECHANICALLY VERIFIED | `tests/test_pilot_identity_kms.py` (14); failure-court identity cases |
| Local dev issuer | labeled NON-PRODUCTION; key rotation (old tokens verify, new tokens sign); no default bypass | MECHANICALLY VERIFIED | `tests/test_pilot_identity_kms.py::test_key_rotation_*` |
| KMS seam | sign/verify/key-id/public-key/rotate/health interface; ephemeral + encrypted-persisted local providers; AWS/GCP shapes fail closed (`DISABLED_NO_CREDENTIALS`) and refuse to sign without real remote verification | MECHANICALLY VERIFIED | `tests/test_pilot_identity_kms.py` KMS block |
| Evaluator PROCESS isolation | separately launched unix-socket service owns the CSPRNG secret + truth; authenticated (constant-time token), strict schema, frame cap, RLIMIT_AS; **charge-before-context** durable looks; crash/timeout/malformed/disconnect all consume the look; restart sweeps dangling looks to terminal FAILED with **no refund**; finalize/reveal irreversible across restart; secret never crosses the wire pre-reveal, never in logs | MECHANICALLY VERIFIED (process isolation on one host) | `tests/test_evaluator_isolation.py` (real subprocess kill/restart); failure-court live SIGKILL case |
| Authorized ingestion | versioned signed event contract; source authority + signature verification; schema + size validation; canonical normalization + content digest; ingestion receipt; replay + idempotency rejection; quarantine with reasons; corrections/late handling; raw→normalized provenance | MECHANICALLY VERIFIED | `tests/test_pilot_ingest.py` (16); failure-court unsigned/forged/oversized cases |
| Shadow lifecycle | REQUESTED→AWAITING_INDEPENDENT_APPROVAL→APPROVED_SHADOW→SHADOW_DISPATCHED→OUTCOME_PENDING→OUTCOME_RECORDED→REPLAY_VERIFIED; no-skip compare-and-set; dual-control approval; approval expiry; evidence digest frozen at request and re-verified at approval+dispatch; idempotent dispatch; outcome + decision-quality; full-trail replay; content-addressed evidence-room export | MECHANICALLY VERIFIED | `tests/test_pilot_shadow.py` (12); failure-court self-approval/duplicate/substitution cases |
| External execution | only the fail-closed NullActionExecutor is wired; dispatch records a fail-closed proof; every receipt carries `external_execution: false` | MECHANICALLY VERIFIED | `tests/test_pilot_shadow.py::test_external_execution_is_provably_false_everywhere` |
| Observability | structured JSON logs with correlation ids; secret-value + secret-key redaction (nested); metrics; health/readiness aggregation | MECHANICALLY VERIFIED | `tests/test_pilot_objectstore_observability.py`; failure-court secrets-in-logs case |
| Operator cockpit | full ingest→provenance→decision→request→approve→dispatch→outcome→replay→export loop; required UI states; decomposed replay proof chips (no single READY badge); hostile-HTML evidence proven inert; desktop + 390px mobile; zero JS errors; zero unexpected failed requests | MECHANICALLY VERIFIED | `scripts/pilot_browser_verification.py` (24 checks) |
| End-to-end loop | the whole product loop over REAL HTTP with separate evaluator+cockpit processes and three dev identities | MECHANICALLY VERIFIED | `scripts/pilot_smoke.py` (22 steps); `pilot-smoke` gate |
| Failure court | 39 executed cases (25 live injections against real processes + 14 pytest rejection suites) all fail closed and recover | MECHANICALLY VERIFIED | `scripts/failure_court.py` |
| Performance | labeled local synthetic latencies/throughput with generous regression guards | MODEL-CONDITIONAL ESTIMATE (local host only) | `scripts/pilot_performance.py` |

## B. Carried forward from the merged V5 kernel (re-verified in V6)

CSPRNG evaluator secret + irreversible lifecycle; charge-before-execution;
real full-decision replay + 19/19 mutation battery; stratum-preserving power
measurement; single evaluator-version constant + mandatory dependency lock;
signed dual-runtime chains (Python + Node); complete package with 113 PNGs;
V5 cockpit decomposed honest proof + wired controls. Classes unchanged from
`receipts_v5/V5_CLAIM_LEDGER.md`; all re-verified by the V6 canonical gate.

## C. Synthetic / per-run findings (receipt-bound — NOT invariants)

- Sealed promotion outcomes vary per CSPRNG run. The main run's replay is
  often `VACUOUS_INTEGRITY_ONLY` (0 sealed decisions) — labeled as such,
  never called full replay. The pinned battery fixture is the invariant
  non-vacuous proof (baseline_full_decision=true, 19/19 detections). The exact
  promotions/rejections/replay counts belong to the specific bound run — see
  the delivery folder's `V6_GATE_RESULTS.json` and sealed-run receipt.
- In-family shift: NLL transfer ESTABLISHED; CRPS transfer NOT ESTABLISHED.
- Structurally independent generator: champion advantage NOT ESTABLISHED
  (CI straddles zero); calibration stayed in band (the gated trust property).

## D. NOT ESTABLISHED (see V6_HONEST_REMAINING_WALLS.md)

Live customer data · production KMS/HSM key custody · production OIDC/identity ·
organizational evaluator isolation · durable external transparency storage ·
real external execution · alien-generator advantage · general self-improvement ·
universal transfer advantage · production operational scale.
**EXTERNALLY VALIDATED: nothing.** Every V6 pilot production capability is a
fail-closed adapter SEAM or a labeled local reference backend, not deployed
infrastructure. A local reference implementation is not external validation; a
configured interface is not deployed infrastructure; a mock is not an
integration; a valid signature is not a trusted signer; approval is not
external execution.

## E. Standing prohibitions honored

No gate lowered, no tolerance widened, no hard test deleted/weakened for green
(all changes additive; the only signature change carried from V5 is
`verify_chain`'s optional pinning kwargs). No generated receipt hand-edited
after generation. `external_action`/external execution false throughout. The
canonical Mac repository was NOT accessed or merged from this sandbox; V6 is a
source + patch handoff for independent local verification.
