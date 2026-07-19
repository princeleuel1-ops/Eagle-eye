# The Stranger's Verifier

One file. Standard library only. CPython ≥ 3.9. No imports from this
repository, no pip installs, no network. You can read every line before you
trust it — that is the point.

```
python3 -I strangers_verifier.py verify-evolution REPLAY_BUNDLE.json \
    [--expect-signer ed25519:HEX]...
python3 -I strangers_verifier.py verify-transfer W_TRANSFER_BUNDLE.json \
    W_TRANSFER_RECEIPT.json [--champion-bundle REPLAY_BUNDLE.json]
python3 -I strangers_verifier.py verify-recursive RECURSIVE_EVOLUTION_RECEIPT.json
python3 -I strangers_verifier.py heads-append HEADS.jsonl BUNDLE.json
python3 -I strangers_verifier.py heads-verify HEADS.jsonl [--bundle BUNDLE.json]
```

`-I` runs Python in isolated mode: no environment variables, no site
packages, no current-directory imports. Exit 0 with
`STRANGERS_VERIFIER_PASS` only if every check passes.

## What a PASS proves — without trusting the publisher

1. **Authenticity.** Every chain row and anchor signature verifies under a
   from-scratch RFC 8032 Ed25519 implementation (known-answer tested against
   the RFC vectors). Keys come from the bundle's signer registry AND from any
   key ids you pin with `--expect-signer` (pin them — a bundle that ships its
   own registry can only prove internal consistency).
2. **Integrity.** Row hashes, previous-hash linkage, sequence numbers, and
   the signed anchor (length + head) are recomputed from bytes. Splices,
   reorders, rewrites, and truncations fail.
3. **Commit-reveal.** The revealed evaluator secret reproduces the pre-run
   commitment published before any outcome existed.
4. **Accounting.** Charge-before-result pairing (one result per charge),
   monotone look indexes, alpha spend arithmetic, and the significance
   flag's arithmetic consistency.
5. **The decision rule itself.** Candidate ids, snapshot ids, and the entire
   promotion gate chain are recomputed from signed micro-integer fields.
   An attacker who mutates a decision and re-signs EVERYTHING with their own
   key still fails — the recorded semantics no longer reproduce.
6. **Evidence arithmetic.** W-transfer cluster sums re-added from per-case
   scores; seed signs, exact binomial-mixture e-values, wealth accumulation,
   threshold crossings, and the headline claim recomputed. Inflated wealth
   and flipped claims fail.
7. **Transparency.** `heads-append` commits chain heads into a hash-chained,
   append-only offline log; `heads-verify` detects interior mutation and
   checks bundle membership. Pin the latest line's hash somewhere public —
   the tail of any hash chain is only as immutable as its newest commitment.

## What a PASS does NOT prove — the honest boundary

- It does not re-run the models. Rebuilding sealed suites from the revealed
  secret and re-scoring predictions is SEMANTIC replay; it requires executing
  the hash-pinned source tree (`make replay`, `make check` there). This file
  proves the receipts are authentic, intact, and correctly accounted — the
  semantic layer is code-bound to a tree hash you can audit and run yourself.
- It does not prove anything about the real world. Eagle Eye's own walls
  apply: everything is synthetic until its own receipts say otherwise, and
  EXTERNALLY VALIDATED means someone who is not the publisher ran this.

## Verify this verifier

`MANIFEST_SHA256.txt` pins this directory's own hashes. Recompute them:
`sha256sum strangers_verifier.py README.md`.
