# RECEIPT STATUS INDEX — V4 supersession (audit blocker 10)

Every receipt under `receipts_superseded/` is HISTORICAL and SUPERSEDED by
the `receipts_v4/` set. Historical files are preserved BYTE-IDENTICAL (no
content edits — supersession is expressed only here and by directory name).

Status labels: SUPERSEDED_V1 = introduced with the V1 handoff;
SUPERSEDED_V2 = introduced/last-revised with V2; SUPERSEDED_V3 = introduced/
last-revised with V3. Classification is MECHANICAL: each local file's
SHA-256 was matched against the members of the actual delivered archives.

Key corrections that apply to these historical receipts (details in
V4_CLAIM_LEDGER.md §A): test counts 128/167/184; V1 one-promotion claims;
113-PNG claims for archives that omitted the files; V3 'full decision
replay RESOLVED'; V3 'cross-generator' (in-family shift); V3 'power
tripled'.

| file | earliest identical in | status | sha256 (16) |
|---|---|---|---|
| ADVERSARIAL_FINDINGS_AND_REPAIRS.md | V1, V2, V3 | SUPERSEDED_V1 | e05c22d85236f8b9 |
| ARCHITECTURE_AND_IMPLEMENTATION_MAP.md | V1, V2, V3 | SUPERSEDED_V1 | 2691277ca6fa1d10 |
| BENCHMARK_COURT_SPEC.md | V1, V2, V3 | SUPERSEDED_V1 | 099182dfee266a2c |
| BENCHMARK_RESULTS.json | V1, V2, V3 | SUPERSEDED_V1 | fdcacaea35a2ce85 |
| CHAMPION_CHALLENGER_SPEC.md | V1, V2, V3 | SUPERSEDED_V1 | 0b24460b1f69cdf0 |
| CLAIM_LEDGER.md | V2, V3 | SUPERSEDED_V2 | d7c1f1eeaf2cf916 |
| CONFORMAL_EVALUATION_RESULTS.json | V2, V3 | SUPERSEDED_V2 | 997683d295c3ac40 |
| CONFORMAL_GUARANTEE_CONTRACT.md | V1, V2, V3 | SUPERSEDED_V1 | 4527bf68e6b721dd |
| CROSS_GENERATOR_RESULTS.json | V3 | SUPERSEDED_V3 | 09e42c6dd152fb3c |
| EVOLUTION_LINEAGE.json | V3 | SUPERSEDED_V3 | 63a8324898797b9c |
| FINAL_VERIFICATION_RECEIPT.md | V1, V2, V3 | SUPERSEDED_V1 | c88d3ba19fed1468 |
| HOLDOUT_ACCESS_LEDGER.json | V3 | SUPERSEDED_V3 | 7f16ddac4810882a |
| HONEST_REMAINING_WALLS.md | V3 | SUPERSEDED_V3 | 444f38cd4dee8196 |
| MULTIPLE_COMPARISON_POLICY.md | V1, V2, V3 | SUPERSEDED_V1 | 680943c98560f762 |
| MUTATION_WHITELIST.json | V1, V2, V3 | SUPERSEDED_V1 | fb16e8de124ce97d |
| OFF_POLICY_IDENTIFIABILITY_REPORT.json | V2, V3 | SUPERSEDED_V2 | 8474eaddc5de9a98 |
| OUTCOME_RESOLUTION_RECEIPT_EXAMPLE.json | V2, V3 | SUPERSEDED_V2 | 636c07901b21342c |
| OUTCOME_RESOLUTION_SCHEMA.json | V1, V2, V3 | SUPERSEDED_V1 | 3214cb2288593d7d |
| OUTCOME_RESOLUTIONS.json | V3 | SUPERSEDED_V3 | 61806bdfebdf7e11 |
| PRIOR_SELECTION_RECEIPT_EXAMPLE.json | V1, V2, V3 | SUPERSEDED_V1 | 33f7ec6d527a22aa |
| PRIOR_TASK_SCHEMA.json | V1, V2, V3 | SUPERSEDED_V1 | 467a71e540915a16 |
| RECURSIVE_PROMOTION_REJECTION_RECEIPT.json | V1, V2, V3 | SUPERSEDED_V1 | d330c001a7dc5625 |
| REPLAY_BUNDLE.json | V3 | SUPERSEDED_V3 | ef1119ae610d3c58 |
| SEALED_EVOLUTION_ARCHITECTURE.md | V1, V2, V3 | SUPERSEDED_V1 | 42cd0718cfa173cd |
| SEALED_EVOLUTION_BASELINE_RECEIPT.json | V1, V2, V3 | SUPERSEDED_V1 | 4c5dbd41205ef99a |
| SEALED_EVOLUTION_BENCHMARK_RESULTS.json | V3 | SUPERSEDED_V3 | a9d7a57391468da8 |
| SEALED_EVOLUTION_FINAL_RECEIPT.md | V1, V2, V3 | SUPERSEDED_V1 | a02c820b64c379de |
| SOTA_GAP_AND_BRITTLE_POINT_MAP.md | V1, V2, V3 | SUPERSEDED_V1 | 1d7a5a7e0e344bd4 |
| SOURCE_AND_CLAIM_LEDGER.md | V1, V2, V3 | SUPERSEDED_V1 | b7cad095e7891ba7 |
| state.json | V3 | SUPERSEDED_V3 | e60ec3da99308c0a |
| VALUE_OF_INFORMATION_CONTRACT.md | V1, V2, V3 | SUPERSEDED_V1 | 8fa7d225345a49d4 |
| VALUE_OF_INFORMATION_EXAMPLE.json | V1, V2, V3 | SUPERSEDED_V1 | 5167345c0b4ed65c |
| ZENITH_RUN_MANIFEST.json | V1, V2, V3 | SUPERSEDED_V1 | 070ed39f3776879d |

Notes:
- Files 'identical in' multiple versions were shipped unchanged across
  those handoffs; their status reflects first shipment.
- `CROSS_GENERATOR_RESULTS.json` (SUPERSEDED_V3) carries the WITHDRAWN
  'generator swap' claim — see receipts_v4/V4_CLAIM_LEDGER.md.
- `HONEST_REMAINING_WALLS.md` (V3 revision) contains the WITHDRAWN
  'full decision replay RESOLVED' and 'power tripled' entries.
