# V12 REPAIR MAP
| # | Item | Change | Evidence |
|---|---|---|---|
| 1 | Execution unarmed by default | verify_arming(None)=UNARMED; unarmed executor refuses | gate 1,10-11 |
| 2 | Arming is a signed dual-control decision | ExecutionArmingConfig + pinned-key verification | gate 3-4; tests |
| 3 | Production arming chains to custody | require_production_custody inside verify_arming | gate 2; test |
| 4 | Every action individually licensed | single-use expiring bound tokens + spent ledger | gate 6-8; tests |
| 5 | The action carries its proof | receipt binds the full chain, hashed + signed | gate 5; tests |
| 6 | Reversibility | LocalOutboxAdapter.reverse bound to receipt hash | gate 9 |
| 7 | Canonical gate | execution-rehearsal = required gate 33 | make check |
| 8 | Ceremony | FIRST_ACTION_RUNBOOK (needs V10+V11 first) | runbook |
Files added: src/eagle_eye/licensed_execution.py,
scripts/run_execution_rehearsal.py, tests/test_licensed_execution.py,
receipts_v12/ (5 docs). Changed: Makefile, run_all_gates.py (gate 33),
LOCAL_REPRODUCTION.md, manifest.
