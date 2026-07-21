# EAGLE EYE — WEAKEST CAPABILITY DIMENSIONS (honest, 2026-07-20)
Ranked by how much they cap the system's value, from the real repo state.

1. **No external validation** — a stranger has not verified (operator did). [social/process, not code]
2. **No live data (W2)** — everything synthetic; live spine READY but key-gated.
3. **No verifiable TIME / anti-split-view on the ledger** — heads log is a hash
   chain: tamper-evident only to a holder of the WHOLE log; NO succinct
   inclusion/consistency proofs; NO equivocation resistance.  <-- THIS SLICE
4. **Transfer not established (W-transfer)** — advantage dies on independent generators.
5. **Single-host trust** — no threshold/distributed authority.
6. **Own supply-chain provenance not attested** — ironic gap (SLSA/in-toto).
7. **No privacy-preserving verification** — can't prove a decision without revealing inputs (ZK).

Slice 1 attacks #3 — the highest-value dimension that is (a) pure code,
(b) clean-provenance, (c) buildable stdlib-only, (d) keeps the kernel untouched.
