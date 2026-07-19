# Frontend/State Contract — evolution-state/4.0 (V4 blocker 8)

The Sealed Evolution panel (`web/evolution.js`) and the benchmark's
`state.json` (written by `scripts/run_sealed_evolution.py`) share this
versioned contract. The panel checks `state_schema_version` and renders a
warning chip on major-version mismatch; it must NEVER crash on missing
optional fields (the V3 crash — `last_rejection.lineage_hash` undefined —
is a regression test in `verifier/dom_contract_test.mjs`).

## REQUIRED fields (producer MUST emit; panel may rely on presence)

| field | type | notes |
|---|---|---|
| `state_schema_version` | string | `evolution-state/4.x` |
| `champion` | string | current champion id |
| `champion_config` | object | whitelist config |
| `lineage_length` | int | signed lineage row count |
| `lineage_head` | string | terminal row hash |
| `budget` | object | see budget subfields below |
| `conformal_state_latest` | string | guarantee state enum |
| `drift_state` | string | |
| `n_cycles` | int | |
| `events` | object | counters |
| `evaluator_lifecycle` | string | INITIALIZED/EVALUATING/FINALIZED/REVEALABLE |
| `external_action` | bool | always false in fixture mode |
| `claim_supported` | bool | gates the "SELF-IMPROVING" label |

Budget REQUIRED subfields: `candidates_proposed`, `candidates_evaluated`,
`holdout_looks`, `final_audit_holdout_looks`, `alpha_spent_micro`,
`alpha_total_micro`.

## OPTIONAL fields (panel MUST render safe fallbacks when absent/null)

| field | fallback |
|---|---|
| `last_promotion` (whole object or any subfield) | "none yet" card |
| `last_promotion.lineage_hash` | "n/a" |
| `last_promotion.statistics.*` | "n/a" |
| `last_rejection` (whole object or any subfield) | "none" card |
| `last_rejection.lineage_hash` | "n/a" |
| `last_rejection.candidate.diff` | "diff unavailable" |
| `last_rejection.reasons` | "sealed gates" |
| `voi_latest.*` | "n/a" |
| `off_policy_latest` | "n/a" |
| `registry_growth_count` | 0 |
| `resolution_backlog` | "n/a" |
| `budget.holdout_look_terminal_statuses` | row hidden |

## Producer-side guarantees (V4)

`state.json`'s `last_promotion` / `last_rejection` entries are built as
`{**lineage_row.body, "lineage_hash": lineage_row.row_hash}` so the hash the
panel links is always present when the entry itself exists. The panel still
treats it as optional (defense in depth).

## Verification

- `verifier/dom_contract_test.mjs` — Node JS-runtime execution of the real
  panel code against the real generated state, plus the degraded-state
  regression (missing lineage_hash, null promotion, missing voi_latest).
- `scripts/browser_verification.py` — real headless Chromium workflow:
  supplier selection, evidence trace, posterior commitment recomputation,
  evolution lineage/budget/rejection/final-audit chips, fixture and
  external-action labeling; zero JS errors, zero failed requests, no
  "panel unavailable" state.
