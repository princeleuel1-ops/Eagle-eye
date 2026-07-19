# VERIFY THIS MACHINE YOURSELF — no trust required

You do not need to trust the authors, this repository's history, or any AI.
You need Python 3.9+ and ten minutes.

## 1. Audit the verifier (one file, stdlib only)
    less verifier_standalone/strangers_verifier.py
No imports beyond the standard library. No network. Read every line.

## 2. Verify the published recursive-evolution receipt
    python3 -I verifier_standalone/strangers_verifier.py verify-recursive transparency/RECURSIVE_EVOLUTION_RECEIPT.json
Expect: per-round replay verdicts, exact e-process wealth arithmetic
recomputed, honesty block enforced -> STRANGERS_VERIFIER_PASS.

## 3. Verify the transparency heads log
    python3 -I verifier_standalone/strangers_verifier.py heads-verify transparency/HEADS.jsonl
Hash-chained, append-only chain heads from the sealed run.

## 4. Full bundle verification (signatures, chains, commit-reveal, decisions)
The complete replay bundles (with every signed chain row) are large binary-
adjacent artifacts distributed in the release archives rather than git; ask
the maintainer for EAGLE_EYE bundle archives, then:
    python3 -I verifier_standalone/strangers_verifier.py verify-evolution REPLAY_BUNDLE.json --expect-signer ed25519:<pinned>

## What a PASS means — and does not
It proves these receipts are internally exact, correctly accounted, and
that the promotion/evidence arithmetic reproduces bit-for-bit. It does NOT
prove anything about live data, production custody, or the real world —
those remain fail-closed behind operator key ceremonies, and this project's
own walls say so in receipts_v12/V12_HONEST_REMAINING_WALLS.md.

If you ran step 2 and 3 and saw PASS: you just externally verified this
machine. You were the point of the whole design.
