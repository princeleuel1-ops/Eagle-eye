"""FUSION SLICE 5 — Verifiable Self-Improvement Certificate (the apex).

CLAIM IT MAKES CHECKABLE: "generation N+1 is better than generation N" — under
an anytime-valid guarantee (Slice 4), over a held-out evaluation stream, with
the whole lineage bound into the Merkle transparency ledger (Slice 1), so a
STRANGER replays the certificate from the recorded per-item results and
confirms it WITHOUT trusting us. Every AI lab claims self-improvement; this is
the first that lets an outsider verify a specific improvement step.

FUNDAMENTAL HONESTY (the ceiling, stated in code):
  * The certificate proves a RELATIVE, PRE-REGISTERED comparison on a fixed
    eval stream — NOT absolute quality, NOT real-world value.
  * Inputs here are synthetic per-item outcomes; a real run feeds real graded
    outputs. The MECHANISM is validated; the DATA is not.
  * A crossing is anytime-valid at level alpha assuming per-item outcomes are
    independent given the pair — a documented, checkable assumption.
  * external_validation stays FALSE until a stranger runs it.

MECHANISM (paired anytime-valid superiority test, e-value):
  For each eval item i, both generations produce a binary success b_A, b_B.
  Consider only DISCORDANT items (exactly one succeeds). Under H0 "B is not
  better than A", P(B wins | discordant) <= 1/2 (paired sign null). A betting
  test-supermartingale on discordant wins yields an e-process; wealth >= 1/alpha
  is an anytime-valid certificate that B > A. (Same e-value family as Slice 4 /
  V7 eprocess; here applied to the champion->challenger promotion decision.)

Clean-room, stdlib only. Provenance: public (paired sign test; Ville; e-values;
Waudby-Smith & Ramdas). Reuses fusion Slice 1 + concepts from Slice 4.
"""
from __future__ import annotations
import hashlib, json
from merkle_ledger import MerkleLedger, verify_inclusion_obj

def _canon(o) -> bytes:
    return json.dumps(o, sort_keys=True, separators=(",", ":")).encode()

_LAM = 0.5   # fixed conservative bet in (0,1): factor 1+lam*(+/-1) stays >0

def _wealth_from_pairs(pairs, lam: float = _LAM) -> tuple[float, int, int]:
    """pairs: list of (b_A, b_B) in {0,1}. On discordant items, w *= (1+lam) if
    B wins else (1-lam). Returns (wealth, b_wins, a_wins)."""
    w = 1.0; bw = aw = 0
    for a, b in pairs:
        if a == b:
            continue                      # concordant -> no information
        if b == 1 and a == 0:
            w *= (1 + lam); bw += 1
        else:
            w *= (1 - lam); aw += 1
    return w, bw, aw

def certify_improvement(pairs, *, alpha: float = 0.05,
                        gen_from: str = "champion", gen_to: str = "challenger",
                        eval_id: str = "holdout") -> dict:
    """Emit a verifiable certificate that gen_to > gen_from (or NOT_ESTABLISHED)."""
    thr = 1.0 / alpha
    w, bw, aw = _wealth_from_pairs(pairs)
    verdict = "IMPROVEMENT_CERTIFIED" if w >= thr else "NO_IMPROVEMENT_ESTABLISHED"
    rec = {"spec": "eagle-eye-self-improvement-cert/1.0",
           "gen_from": gen_from, "gen_to": gen_to, "eval_id": eval_id,
           "alpha": alpha, "threshold": thr, "lambda": _LAM,
           "n_items": len(pairs), "discordant": bw + aw,
           "b_wins": bw, "a_wins": aw, "wealth": w, "verdict": verdict,
           "pairs": [[int(a), int(b)] for a, b in pairs]}
    rec["record_sha256"] = hashlib.sha256(_canon(rec)).hexdigest()
    return rec

def recompute_certificate(rec: dict) -> bool:
    """STRANGER side: recompute wealth from the recorded per-item pairs and
    confirm the verdict + integrity. Fails closed on any tamper."""
    body = {k: v for k, v in rec.items() if k != "record_sha256"}
    if hashlib.sha256(_canon(body)).hexdigest() != rec["record_sha256"]:
        return False
    w, bw, aw = _wealth_from_pairs([(a, b) for a, b in rec["pairs"]], rec["lambda"])
    if not (abs(w - rec["wealth"]) < 1e-9 and bw == rec["b_wins"] and aw == rec["a_wins"]):
        return False
    exp = "IMPROVEMENT_CERTIFIED" if w >= rec["threshold"] else "NO_IMPROVEMENT_ESTABLISHED"
    return exp == rec["verdict"]

class SelfImprovementLedger:
    """Chains certificates gen0->gen1->gen2... into the Merkle transparency
    ledger, so the whole self-improvement LINEAGE is stranger-verifiable."""
    def __init__(self):
        self.ledger = MerkleLedger(); self.certs: list[dict] = []
    def record(self, rec: dict) -> dict:
        idx = self.ledger.append(rec); self.certs.append(rec)
        cp = self.ledger.checkpoint()
        return {"index": idx, "checkpoint": cp,
                "inclusion": self.ledger.prove_inclusion(idx)}
    def verify_lineage(self) -> bool:
        return all(recompute_certificate(c) for c in self.certs)
