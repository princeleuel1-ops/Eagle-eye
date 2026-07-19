# RECEIPT STATUS INDEX — V5 canonical

The CURRENT, authoritative receipt set is `receipts_v5/`. Everything else is
historical and superseded; historical files are preserved BYTE-IDENTICAL
(supersession is expressed by location + this index, never by editing a
generated receipt).

| Location | Status | Notes |
|---|---|---|
| `receipts_v5/` | CURRENT | V5 canonical claim ledger, walls, repair map, pilot checklist, this index |
| `receipts_superseded/v4/` | SUPERSEDED_V4 | V4 final receipts (byte-identical); the independently hash-verified kernel V5 integrates |
| `receipts_superseded/` (V1–V3 set) | SUPERSEDED_V1/V2/V3 | earlier receipts + their own RECEIPT_STATUS_INDEX describing the V1–V3-era layout |

Corrections carried into V5 (full detail in V5_CLAIM_LEDGER.md §A and the V4
ledger under receipts_superseded/v4/):
- test count is **227 tests / 33 files** in V5 (V4 shipped 214/31; earlier
  128/167/184 counts apply only to their own superseded sets)
- per-run replay decision counts are bound to a specific run's artifacts, not
  presented as invariants
- any historical `receipts_v4/` path reference belongs to the V4-era layout;
  the current location is `receipts_superseded/v4/`
