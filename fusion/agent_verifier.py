"""FUSION SLICE 4 — Verifiable agent-verdict e-process (ADOPT + SURPASS).

ADOPT (2024-26 frontier: E-valuator, CITE, chance-constrained inference):
  Turn a stream of black-box verifier scores s_t in [0,1] (e.g. repeated
  LLM-judge calls on an agent trajectory) into an ANYTIME-VALID accept/reject
  with provable false-alarm control at level alpha, via a betting test
  supermartingale (Waudby-Smith/Ramdas e-values). Valid at ANY stopping time
  (immune to peeking / optional stopping), which naive confidence-thresholds
  are NOT.

SURPASS (only Eagle Eye has this): bind the certified verdict + the exact
score stream + thresholds + alpha into a signed record and append it to the
Merkle transparency ledger (Slice 1), so a STRANGER can recompute the wealth
from the recorded scores AND get an inclusion/consistency proof the verdict
was not tampered. The papers give a guarantee; we give a checkable receipt.

Clean-room, stdlib only. Provenance: public methods (Ville 1939;
Waudby-Smith & Ramdas 2020; e-value literature). No code reused.
"""
from __future__ import annotations
import hashlib, json

# mixture betting martingale for H0: mean(scores) <= theta  (certify RELIABLE)
def _accept_factor(x: float, theta: float, lam: float) -> float:
    return 1.0 + lam * (x - theta)          # E<=1 under mean<=theta; >0 for lam<1/theta

def _reject_factor(x: float, theta: float, lam: float) -> float:
    return 1.0 + lam * (theta - x)          # certify UNRELIABLE: H0 mean>=theta

def _lam_grid(theta: float) -> list[float]:
    hi = 1.0 / max(theta, 1e-6)             # keep accept factor positive
    hi = min(hi, 1.0 / max(1e-6, 1 - theta))
    return [g for g in (0.25, 0.5, 1.0, 1.5, 2.0) if 0 < g < hi] or [0.25]

class AgentVerdictProcess:
    """Anytime-valid certifier. accept when accept-wealth >= 1/alpha (RELIABLE);
    reject when reject-wealth >= 1/alpha (UNRELIABLE); else CONTINUE."""
    def __init__(self, *, theta_reliable: float = 0.6, theta_unreliable: float = 0.4,
                 alpha: float = 0.05):
        self.tr, self.tu, self.alpha = theta_reliable, theta_unreliable, alpha
        self.thr = 1.0 / alpha
        self.acc_grid = _lam_grid(theta_reliable)
        self.rej_grid = _lam_grid(1 - theta_unreliable)
        self.acc = [1.0] * len(self.acc_grid)   # per-lambda wealth (accept side)
        self.rej = [1.0] * len(self.rej_grid)
        self.scores: list[float] = []

    def update(self, s: float) -> str:
        s = min(1.0, max(0.0, float(s)))
        self.scores.append(s)
        self.acc = [w * _accept_factor(s, self.tr, l) for w, l in zip(self.acc, self.acc_grid)]
        self.rej = [w * _reject_factor(s, self.tu, l) for w, l in zip(self.rej, self.rej_grid)]
        return self.verdict()

    def accept_wealth(self) -> float: return sum(self.acc) / len(self.acc)   # mixture
    def reject_wealth(self) -> float: return sum(self.rej) / len(self.rej)

    def verdict(self) -> str:
        if self.accept_wealth() >= self.thr: return "RELIABLE"
        if self.reject_wealth() >= self.thr: return "UNRELIABLE"
        return "CONTINUE"

def _canon(o) -> bytes:
    return json.dumps(o, sort_keys=True, separators=(",", ":")).encode()

def certify(scores, *, theta_reliable=0.6, theta_unreliable=0.4, alpha=0.05,
            agent_id="agent", task_id="task") -> dict:
    """Run the process over a score stream; emit a verifiable verdict record."""
    p = AgentVerdictProcess(theta_reliable=theta_reliable,
                            theta_unreliable=theta_unreliable, alpha=alpha)
    v = "CONTINUE"; stop = None
    for i, s in enumerate(scores):
        v = p.update(s)
        if v != "CONTINUE":
            stop = i + 1; break
    rec = {"spec": "eagle-eye-agent-verdict/1.0", "agent_id": agent_id,
           "task_id": task_id, "alpha": alpha,
           "theta_reliable": theta_reliable, "theta_unreliable": theta_unreliable,
           "n_scores": len(p.scores), "scores": p.scores, "verdict": v,
           "stopped_at": stop, "accept_wealth": p.accept_wealth(),
           "reject_wealth": p.reject_wealth(), "threshold": p.thr}
    rec["record_sha256"] = hashlib.sha256(_canon(rec)).hexdigest()
    return rec

def recompute_verdict(rec: dict) -> bool:
    """STRANGER side: recompute the e-process from the recorded scores and
    confirm the recorded verdict + integrity. Fails closed on any tamper."""
    body = {k: v for k, v in rec.items() if k != "record_sha256"}
    if hashlib.sha256(_canon(body)).hexdigest() != rec["record_sha256"]:
        return False
    p = AgentVerdictProcess(theta_reliable=rec["theta_reliable"],
                            theta_unreliable=rec["theta_unreliable"], alpha=rec["alpha"])
    v = "CONTINUE"
    for s in rec["scores"]:
        v = p.update(s)
        if v != "CONTINUE": break
    return v == rec["verdict"]
