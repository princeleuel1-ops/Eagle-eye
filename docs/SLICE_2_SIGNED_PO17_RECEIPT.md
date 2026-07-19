---
type: verification_receipt
title: Eagle Eye Zenith Slice 2 — Signed PO-17 Preflight
timestamp: 2026-07-12
---

# Executable claim

Authorized CSV/JSON fixture files become an evidence-bound PO-17 preflight with deterministic graph construction, baseline-versus-disruption scenarios, a pending human approval, and a portable evidence room independently verified by Python and Node.

# Input contract

`fixtures/po17/` contains:

- `suppliers.csv`
- `products.csv`
- `components.csv`
- `purchase_orders.csv`
- `events.json`
- `sources.json`

Required CSV columns are validated. Missing columns and empty IDs fail closed.

# Decision path

```text
SRC-AUTH-17
→ EVT-PORT-17
→ SUP-TAIWAN
→ MCU-42
→ EDGE-CTRL
→ PO-17
→ action-bce5ceb7b8a2
```

# Scenarios

| Scenario | Delay | Bounded fixture exposure |
|---|---:|---:|
| Baseline | 0–3 days | $0–$18,450 |
| Disruption | 7–21 days | $73,800–$221,400 |

These values are deterministic fixture outputs, not calibrated forecasts.

# Governed action

- Status: `pending_approval`
- Approval receipts: `0`
- External execution: disabled
- Recommendation: review alternate supply and inventory coverage

The absence of an approval receipt is represented explicitly; it is not inferred or fabricated.

# Cryptographic scope

- SHA-256 binds `run.json` into the manifest.
- Ed25519 signs the canonical manifest.
- Python and Node verify the same detached signature and archive hash.
- The signer is an ephemeral demonstration key generated per fixture run.
- This proves key possession and archive integrity, not factual authority.
- Production KMS identity is not claimed.

# Positive verification

```text
RUN_ID=run-fd0b0cfab41b
PURCHASE_ORDER=PO-17
COMPONENT=MCU-42
SCENARIOS=2
ACTIONS_PENDING=1
APPROVAL_RECEIPTS=0
SIGNATURE_VERIFIED=true
EVIDENCE_ROOM_VERIFIED=true
NODE_EVIDENCE_ROOM_VERIFIED=true
```

# Negative verification

A test changes `run-original` to `run-tampered` inside a signed archive without regenerating the manifest or signature.

Expected and observed behavior:

- Python rejects the archive.
- Node exits non-zero.
- Both report `verified=false`.
- Both report `hashes_verified=false`.

# Full gate

```text
10 passed
HAS_SCENARIO_COMPARISON=true
DIGITAL_TWIN_SEMANTIC_PASS
EAGLE_EYE_ZENITH_CHECK_PASS
```

# Browser verification

Verified at `http://127.0.0.1:8765`:

- signed parity proof state;
- five connected graph entities;
- recovered node imagery;
- disrupted supplier highlighting;
- PO-17 blast radius;
- scenario comparison;
- evidence trace and known unknowns;
- disabled fixture approval;
- zero console messages;
- zero JavaScript errors.

# Remaining brittle point

The signature uses an ephemeral demonstration key. An attacker who can replace both archive and embedded public key can create a different self-consistent bundle. The next trust upgrade requires an external trust anchor: production KMS identity, certificate/key registry, or verifier-pinned public key.
