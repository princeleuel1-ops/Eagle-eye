# FAILURE-RECOVERY RUNBOOK — Eagle Eye Zenith V6

Every failure mode below is EXERCISED by `scripts/failure_court.py` (39 cases)
and/or the pilot test suites. This runbook maps the symptom an operator sees
to the system's fail-closed behavior and the recovery step. The guiding rule:
the system fails CLOSED and stays auditable; it never fails silently.

| Failure injected | System behavior (fail-closed) | Operator recovery |
|---|---|---|
| Evaluator process crash (SIGKILL) mid-look | cockpit `/api/pilot/evaluator/status` → 503 EVALUATOR_UNAVAILABLE; health `degraded` | restart evaluator (`pilot-up` re-launches it); the in-flight look is swept to terminal FAILED, never refunded; commitment unchanged |
| Evaluator restart | dangling reservations swept to FAILED on start (`swept_on_start`); looks_spent monotone; finalize/reveal state persists | none — durable state is authoritative; re-issue a fresh look if needed |
| Reservation deadline passes | submission settles TIMED_OUT; look consumed | request a new look with a fresh nonce |
| Malformed evaluator submission | look settled REJECTED; consumed | fix the candidate; new nonce |
| Database connection lost / process restart | new connection reopens WAL DB; idempotency + audit intact | none — reopen is transparent; re-run `pilot-check` |
| Corrupted backup | `restore-check` raises `corrupted` and exits nonzero | discard the corrupt backup; restore from an earlier good backup |
| Restore mismatch | `all_heads_reproduced=false` | investigate source integrity before trusting the restore; do not proceed |
| Object missing/corrupted | `ObjectMissing`/`ObjectCorrupted` on read (verify-on-read) | re-export the evidence room; corruption never silently served |
| Audit row rewrite/delete | DB trigger `RAISE(ABORT, 'append-only')` | mutation impossible; investigate the actor that attempted it |
| Audit tail truncation / reorder | `verify_chain` fails vs the separately-persisted head commitment | restore from backup; the head commitment outlives the rows |
| Unsigned / forged-source ingestion | quarantined with reasons; never enters the graph | inspect `GET /api/pilot/ingest/quarantine`; fix the source signing |
| Oversized / malformed payload | refused before parse (size guard) / quarantined | reject at the source; raise the cap only deliberately |
| Duplicate idempotency key | transactional rejection (ingest/approval/dispatch) | expected under retries; the first result stands |
| Expired identity assertion | 401 IDENTITY_EXPIRED | re-mint a session (dev issuer) or refresh the real IdP token |
| Wrong tenant / issuer / audience | 401 with the specific reason | use the correct tenant-bound, pinned-issuer assertion |
| Self-approval attempt | 403 (role) or 409 (dual-control) | a different approver identity must approve |
| Post-approval evidence substitution | dispatch fails EVIDENCE_VERIFICATION_FAILED; action frozen EVIDENCE_FAILED | the action can never dispatch; open a fresh request against current evidence |
| Approval expired before dispatch | action moves to EXPIRED; dispatch refused | request + approve again |
| Missing required dependency at startup | cockpit serves 503 DEPENDENCY_DEGRADED (not a crash, not a lie) | fix the pilot home / dependency; `pilot-up` again |
| Secrets in logs | redaction scrubs by value + key name; failure-court asserts absence | none — verified clean; report any leak as a P0 |

## General recovery sequence
1. `make pilot-check` — identify which dependency is degraded.
2. Read `artifacts/pilot/home/logs/*.log` (structured JSON, secrets redacted).
3. If storage/audit integrity is in doubt: `make pilot-restore-check` against
   the latest backup before trusting any state.
4. `make pilot-down && make pilot-up` for a clean restart (stale-listener
   guard prevents double-starts).
5. Escalate only a reproduced integrity failure — the system is designed so
   that a single transient fault fails closed and recovers on restart.
