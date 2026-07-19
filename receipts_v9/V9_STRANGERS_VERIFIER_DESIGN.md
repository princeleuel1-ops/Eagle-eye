# V9 — THE STRANGER'S VERIFIER
## External transparency, first rung: verification without trusting us

Baseline: the V8 tree (383 tests / 46 files, 29 gates), itself verified on a
second machine on 2026-07-18 (29/29, `NO_ALIEN_TRANSFER_EVIDENCE_EARNED`
reproduced, V8 ⊇ V7 proven byte-exact). V9 is additive on that tree.

## 1. The wall, verbatim

From the current walls: **"Durable external transparency store → … An
externally durable, third-party-reproducible transparency service NOT
ESTABLISHED."** And from the claim ledger's standing boundary:
**"EXTERNALLY VALIDATED: nothing"** — partly because no third party could
verify our receipts without trusting our repository: every verifier we
shipped imported the code whose claims it was checking. Circular.

## 2. The instrument

`verifier_standalone/strangers_verifier.py` — ONE file, standard library
only, CPython ≥ 3.9, zero imports from this repository, runnable under
`python3 -I` (no env, no site-packages). A stranger can audit every line,
then verify:

- **Ed25519 from scratch** (RFC 8032, extended twisted-Edwards coordinates,
  cofactored verification; known-answer tested against the RFC vectors and
  cross-tested against the repository's `cryptography`-based signing).
- **Chains**: row hashes, linkage, sequences, signed anchors, registry
  pinning (bundle-internal AND out-of-band via `--expect-signer`).
- **Commit-reveal**, **charge/result pairing**, **alpha arithmetic**,
  **significance-flag consistency**.
- **The decision rule recomputed**: candidate ids, snapshot ids, and the
  full promotion-gate chain from signed micro fields — the check that
  defeats the full re-sign attack (see court case below).
- **Transfer evidence arithmetic**: cluster sums re-added from per-case
  scores, per-case diff cross-checks, seed signs, exact binomial-mixture
  e-values (ported continued-fraction incomplete beta, integer-micro parity
  with the repository proven by test), wealth, crossings, headline claim.
- **Recursive-receipt arithmetic**: per-round replay verdicts, e-process
  history sums, crossing flags, honesty block.
- **Offline transparency heads log**: hash-chained JSONL append/verify with
  bundle-membership checks (`heads-append` / `heads-verify`). The log's
  tail is only as immutable as its newest externally pinned hash — stated
  in the README, not hidden.

## 3. The court (required gate 30: `strangers-verifier`)

`scripts/run_strangers_court.py` runs the standalone verifier in a
repo-isolated child interpreter against the REAL bundles produced by the
earlier gates (positive controls, pinned and unpinned), then against a
doctored battery, each required to fail closed with the named check:
forged signature · body splice without rehash · row reorder · tail
truncation · **full re-sign attack** (mutated decision, every row and anchor
re-hashed/re-linked/re-signed by an attacker key, registry swapped —
cryptographically self-consistent, caught ONLY by semantic recomputation of
candidate ids; also caught at the registry layer when pinned) · tampered
reveal secret · inflated e-process wealth · flipped headline claim ·
tampered heads log. 15/15 in the sealing run.

## 4. Honest trust decomposition (what this does and does not close)

- CLOSED (as an instrument): a third party can now verify authenticity,
  integrity, accounting, decision-rule reproduction, and evidence
  arithmetic of any published bundle WITHOUT trusting or executing our
  code, and can maintain an offline append-only heads log.
- NOT CLOSED: semantic replay (rebuilding sealed suites, re-scoring
  predictions) remains code-bound to the hash-pinned tree; a stranger who
  wants that layer must audit/execute the pinned tree (`make replay`).
  Stated in the verifier's own README.
- NOT CLOSED: an externally OPERATED, durable transparency service, and
  external validation itself. The instrument exists; **no third party has
  run it. EXTERNALLY VALIDATED: still nothing.** When someone does, their
  machine — not ours — prints the verdict; that is the design.

## 5. Standing prohibitions honored

Additive only; no gate lowered; legacy paths untouched; the verifier ships
with its own manifest (`verifier_standalone/MANIFEST_SHA256.txt`) so the
artifact itself is pinnable. `external_action=false` throughout.
