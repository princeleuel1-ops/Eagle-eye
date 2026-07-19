# PILOT OPERATOR RUNBOOK — Eagle Eye Zenith V6

A local pilot reference deployment on ONE host. Fixture tenant, labeled
NON-PRODUCTION dev issuer, external execution fail-closed. Nothing here is
production infrastructure; see V6_HONEST_REMAINING_WALLS.md.

## 1. Prerequisites
- `make setup` completed (venv, locked deps, Playwright Chromium shell).
- Ports: cockpit on `EAGLE_EYE_PORT` (default 8765). The evaluator uses a
  unix socket under the pilot home (no TCP port).

## 2. Bring up / tear down
```bash
make pilot-setup           # idempotent: home dirs, migrations from empty,
                           # fixture tenant, 0600 evaluator client token
make pilot-up              # starts evaluator + cockpit; waits for readiness
make pilot-check           # health + readiness + migration status (exit 0/1)
open http://127.0.0.1:8765/pilot.html
make pilot-down            # graceful SIGTERM, then cleanup pidfiles + socket
```
Home directory: `EAGLE_EYE_PILOT_HOME` (default `artifacts/pilot/home`).
`PILOT_CONFIG.json` records the resolved config.

Stale-listener guard: `pilot-up` refuses to start if a live pidfile or the
cockpit port is already in use — run `pilot-down` first.

## 3. Operating the loop (cockpit or API)
1. **Ingest** a signed synthetic batch (operator role).
2. **Inspect provenance** of a signal (raw→normalized, recomputed digest).
3. **Assess** bound evidence (labeled fixture decision support).
4. **Request** a bounded action (analyst); evidence digest is frozen.
5. **Approve** with a DIFFERENT identity (approver); self-approval is refused.
6. **Dispatch** (shadow only; idempotent; external execution false).
7. **Record outcome** (resolver identity + decision-quality).
8. **Replay** (independent recomputation; decomposed proof chips).
9. **Export** the evidence room (content-addressed zip).

All state-changing API routes require `Authorization: Bearer <EE-SESSION>`
minted by the dev issuer (`POST /api/pilot/dev-issuer/mint`). There is no
bypass. Health/status/metrics are open reads.

## 4. Backup & restore
```bash
make pilot-backup          # consistent online backup + BACKUP_MANIFEST.json
                           # (db hash, per-tenant audit heads, migrations)
make pilot-restore-check   # restore latest backup into scratch and PROVE
                           # every tenant audit head is reproduced; exit 0/1
```
Restore verification recomputes each tenant's audit chain with the same
verifier the gate uses; a corrupted backup fails closed with `corrupted`.

## 5. Health, metrics, logs
- `GET /api/pilot/health` — dependency probes (storage, object store,
  evaluator); `ready` is true only if every REQUIRED probe is ok.
- `GET /api/pilot/metrics` — labeled local telemetry (counters + timings).
- Logs are structured JSON with correlation ids (run/tenant/request/trace).
  Secrets are redacted by value AND by key name; a failure-court case proves
  the evaluator secret and client token never appear in any log.

## 6. Onboarding a REAL pilot (fail-closed at every step)
1. `make setup && make check` on the pilot host → full green from a clean
   extraction (proves the mechanics before any real wiring).
2. Wire **authorized data** to the ingestion source registry (register the
   source identity + public key); keep everything else on the local
   reference backends. Re-run `pilot-check`.
3. Wire **PostgreSQL** behind the storage interface (set the DSN env var);
   re-run migrations + `pilot-restore-check`.
4. Wire **KMS** (KeyProvider) and **OIDC** (IdentityProvider); re-run the
   identity + failure-court suites against real keys/principals; confirm
   dual-control rejections hold with REAL identities.
5. Wire a **durable external transparency store** to the AuditSink; confirm a
   third party can reproduce the audit head from the external store.
6. Leave **external execution** OFF. Turning it on is a separate, explicitly
   authorized decision with its own legal/ops review — it is NOT part of
   making the cockpit work.

## 7. Non-negotiable during a pilot
- No live claim without independent verification of the specific capability.
- `external_execution` stays false until step 6 is explicitly authorized.
- Fixture keys and the dev issuer are labeled and MUST NOT be used in a pilot.
- Synthetic evaluation findings do not transfer to live data — re-measure on
  the pilot's own authorized data before relying on them.
