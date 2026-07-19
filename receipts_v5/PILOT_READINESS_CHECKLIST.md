# PILOT READINESS CHECKLIST — Eagle Eye Zenith V5

V5 ships fail-closed adapter SEAMS (`src/eagle_eye/adapters.py`), not
infrastructure. Every capability below is **NOT ESTABLISHED** until a pilot
wires a real backend to its named adapter and INDEPENDENTLY verifies it.
`pilot_status()` returns this state machine-readably; by default
`all_fail_closed: true`, `external_action: false`.

| # | Capability | Adapter (fail-closed default) | What the pilot must provide | Verify by |
|---|---|---|---|---|
| 1 | Authorized live data | `NullDataSource` | tenant-scoped disruption/registry feed with provenance + as-of windows | independent reconciliation vs source-of-record; tenant-isolation test |
| 2 | Production key custody | `NullKeyCustody` | KMS/HSM signing (replace fixture Ed25519) | signer trust rooted in KMS; key-rotation + revocation drill |
| 3 | Production identity | `NullIdentity` | SSO/OIDC principals for requester/approver | dual-control rejects self-approval + cross-tenant with REAL principals |
| 4 | Durable transparency store | `NullAuditSink` | append-only external log (e.g. transparency log / WORM) | third party reproduces audit head from the external store |
| 5 | External execution | `NullActionExecutor` | authorized procurement/notification integration | starts DISABLED; enable only after legal/ops sign-off; every action dual-control + audited |

## Onboarding sequence (fail-closed at every step)
1. `make setup && make check` on the pilot host → full green from a clean
   extraction (proves the mechanics before any real wiring).
2. Wire capability 1 (data) only; keep 2–5 Null. Re-run `make check`; confirm
   `pilot_status().external_action == false`.
3. Wire capability 2 (KMS) and 3 (identity); re-run the trust suite against
   real principals/keys; confirm dual-control rejections hold.
4. Wire capability 4 (durable audit); confirm an external party can reproduce
   the audit head from the durable store, not just the in-run chain.
5. Leave capability 5 (external execution) OFF. Turning it on is a separate,
   explicitly authorized decision with its own review — it is NOT part of
   making the cockpit "work."

## Non-negotiable during a pilot
- No live claim without independent verification of the specific capability.
- `external_action` stays false until step 5 is explicitly authorized.
- The fixture keys in this repo are labeled and MUST NOT be used in a pilot.
- Synthetic evaluation findings (transfer, promotion) do not transfer to live
  data — re-measure on the pilot's own authorized data before relying on them.
