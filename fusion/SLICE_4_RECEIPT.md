# FUSION FORGE — SLICE 4 RECEIPT (honest) : Verifiable Agent-Verdict E-Process
2026-07-21 · Replaceable Fabric (kernel untouched) · clean-room, stdlib only

## ADOPT (frontier, 2024-26)
Anytime-valid sequential verification of a black-box verifier-score stream via
a mixture betting test-supermartingale (e-values). Same family as E-valuator
(agent verifiers via sequential testing), CITE (anytime-valid self-consistency),
and chance-constrained hallucination control. Certifies RELIABLE / UNRELIABLE
at level alpha, valid at ANY stopping time (peeking-immune).

## SURPASS (only Eagle Eye)
The verdict + exact score stream + thresholds + alpha are bound into a signed
record that (a) a stranger recomputes from the scores, (b) is appended to the
Merkle transparency ledger (Slice 1) with inclusion/consistency proofs. The
papers produce a guarantee; we produce a checkable, tamper-evident receipt.

## Measured (honest)
- False-accept under repeated peeking (unreliable agent, mean 0.5, theta 0.6):
  e-process = 0.002 (<= alpha) vs naive confidence-threshold = 0.555.
  -> the anytime-valid guarantee is real; the naive baseline is catastrophic.
- Power (reliable agent, mean 0.9): 300/300 certified.
- Stranger recompute confirms verdict; tampered verdict rejected; Merkle-bound
  with verified inclusion proof.

## Novelty Court (honest)
- ADOPT half: KNOWN METHOD (anytime-valid / e-value verification is published,
  active frontier). NOT novel.
- SURPASS half: NEW COMPOSITION — binding an anytime-valid agent verdict into a
  stranger-recomputable, Merkle-logged cryptographic receipt. Not found in the
  cited papers; classified "new cross-domain composition," NOT an externally
  validated breakthrough.

## Not established (walls)
Synthetic Bernoulli scores, NOT real LLM-judge outputs. Not wired into the
sealed kernel or the stranger's-verifier gate set. Not externally validated.
CANDIDATE, not kernel. Guarantee is conditional on scores being independent
given the trajectory (documented assumption; real judges may correlate).
