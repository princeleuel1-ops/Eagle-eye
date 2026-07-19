# V9 CLAIM LEDGER — Stranger's Verifier (delta over V8)

V8's ledger remains canonical for the W-transfer court; V7's for the
recursive flywheel. Evidence-class vocabulary unchanged.

| Area | Claim | Class | Evidence |
|---|---|---|---|
| Standalone independence | the verifier imports only the Python standard library and runs under `python3 -I` with no repository on any path | MECHANICALLY VERIFIED | `tests/test_strangers_verifier.py::test_verifier_imports_nothing_beyond_stdlib`, `::test_verifier_runs_isolated_without_repo`; every court case executes it `-I` in a child process |
| Ed25519 correctness | from-scratch RFC 8032 verification passes the RFC known-answer vectors, rejects bit-flips/malformed inputs, and agrees with the repository's `cryptography`-based signing | MECHANICALLY VERIFIED | RFC vector tests; `::test_signature_verification_matches_repository_signing` |
| Key identity parity | PEM/SPKI parsing and `ed25519:sha256(DER)` key ids reproduce the repository's derivation | MECHANICALLY VERIFIED | `::test_pem_parse_and_key_id_match_repository` |
| E-value parity | standalone binomial-mixture `log_e_micro` equals the repository implementation integer-for-integer across the tested grid | MECHANICALLY VERIFIED | `::test_log_e_micro_matches_repository_exactly` |
| Promotion-gate parity | the ported pure gate chain reproduces the repository's states and reasons on gate-relevant fragments | MECHANICALLY VERIFIED | `::test_promotion_gate_port_matches_repository` |
| Chain verification | repository-signed chains verify; interior mutation and truncation fail | MECHANICALLY VERIFIED | `::test_repository_signed_chain_verifies_and_tamper_fails` |
| Real-bundle acceptance | the real evolution bundle (16 checks), transfer bundle + receipt (10 checks), and recursive receipt (6 checks) all PASS in isolation | MECHANICALLY VERIFIED | `strangers-verifier` gate positive controls |
| Doctored refusal | forged signature, splice, reorder, truncation, full re-sign attack (unpinned AND pinned), tampered reveal, inflated wealth, flipped claim, tampered heads log — all fail closed with the named check | MECHANICALLY VERIFIED | `strangers-verifier` gate, 15/15 court cases; `artifacts/strangers/STRANGERS_COURT_RECEIPT.json` |
| Transparency heads log | hash-chained offline append/verify with bundle membership; interior tamper detected; tail immutability requires external pinning of the newest hash (stated, not hidden) | MECHANICALLY VERIFIED | court `heads_roundtrip`/`heads_tampered`; `::test_heads_log_roundtrip_and_tamper` |
| Artifact pinning | the verifier directory ships its own SHA-256 manifest | MECHANICALLY VERIFIED | `verifier_standalone/MANIFEST_SHA256.txt`; court receipt records the verifier's SHA |

## Boundary (unchanged truths)

Semantic replay remains code-bound to the hash-pinned tree. An externally
operated transparency service is NOT ESTABLISHED. **EXTERNALLY VALIDATED:
nothing** — this rung builds the instrument a stranger would use; it cannot
substitute for the stranger. `external_action=false`.
