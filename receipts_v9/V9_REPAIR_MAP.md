# V9 REPAIR MAP — mission item → change → enforcing evidence

| # | Mission item | Change | Enforcing evidence |
|---|---|---|---|
| 1 | Break verification circularity (third parties had to trust the repo to check the repo) | `verifier_standalone/strangers_verifier.py` — single file, stdlib-only, `python3 -I`-runnable; from-scratch RFC 8032 Ed25519; chain/anchor/commit-reveal/accounting checks | isolation + RFC-vector + parity tests; every court execution is `-I` in a child process |
| 2 | Semantic forgery must fail even when cryptography is internally consistent | candidate-id, snapshot-id, and promotion-gate recomputation from signed micro fields | court `resign_attack` (unpinned) and `pinned_resign` cases |
| 3 | Evidence arithmetic must be independently checkable | cluster sums re-added from per-case scores; ported incomplete-beta e-values with integer parity; wealth/crossing/headline recomputation | `test_log_e_micro_matches_repository_exactly`; court `wealth_inflated`, `claim_flipped` |
| 4 | Published heads need an append-only home | offline hash-chained heads log (`heads-append`/`heads-verify`, bundle membership) | court `heads_roundtrip`, `heads_tampered`; heads pytest |
| 5 | The whole thing must be a canonical gate | `scripts/run_strangers_court.py` + Makefile target + REQUIRED_GATES entry (**gate 30**) | `make strangers-verifier`; `make check` |
| 6 | The artifact itself must be pinnable | `verifier_standalone/MANIFEST_SHA256.txt`; court receipt embeds the verifier SHA-256 | manifest file; `STRANGERS_COURT_RECEIPT.json` |
| 7 | Honesty must be structural | README states the code-bound semantic boundary and the heads-tail caveat; walls upgraded not deleted; EXTERNALLY VALIDATED stays "nothing" until a stranger runs it | `verifier_standalone/README.md`; `receipts_v9/V9_HONEST_REMAINING_WALLS.md` |

Files added: `verifier_standalone/` (verifier, README, manifest),
`scripts/run_strangers_court.py`, `tests/test_strangers_verifier.py`,
`receipts_v9/` (4 documents).
Files changed (additive): `Makefile`, `scripts/run_all_gates.py` (gate 30),
`LOCAL_REPRODUCTION.md` (30 gates / 395 tests), `DOWNLOAD_MANIFEST_SHA256.txt`
(regenerated).
