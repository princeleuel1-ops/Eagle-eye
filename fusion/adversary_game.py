"""FUSION SLICE 3 — Auction/game theory (economics) -> adversary decision model.

COLLISION:
  Gene A (economics): Stackelberg security games — a defender COMMITS to a
    (possibly randomized) defense allocation; a rational attacker observes it
    and BEST-RESPONDS to maximize expected payoff. (Basis of real deployed
    systems: ARMOR/IRIS for LAX & US Coast Guard.)
  Gene B (Eagle Eye): the adversarial court / decision review — model how a
    rational adversary picks which decision or asset to attack.

FUSION: given targets with attacker-values and defense effectiveness, compute
  (1) the attacker's best-response to a given defense,
  (2) the defender's optimal randomized coverage that MINIMIZES the attacker's
      max expected value (a minimax/LP-free hill-climb, stdlib only),
  (3) the residual risk and the target the adversary rationally prefers.
Clean-room, stdlib only. Provenance: public game theory (von Stackelberg 1934;
Tambe security games 2011). No code reused.
"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class Target:
    name: str
    value: float          # attacker's reward if it succeeds uncovered
    def_effect: float     # coverage effectiveness in [0,1]: P(attack stopped | covered)

def attacker_best_response(targets: list[Target], coverage: dict[str, float]) -> tuple[str, float]:
    """Attacker picks the target maximizing expected value given coverage c[t]
    in [0,1]. Expected value = value * (1 - c*def_effect)."""
    best, best_ev = None, -1.0
    for t in targets:
        c = coverage.get(t.name, 0.0)
        ev = t.value * (1.0 - c * t.def_effect)
        if ev > best_ev:
            best, best_ev = t.name, ev
    return best, best_ev

def optimal_defense(targets: list[Target], budget: float, *, steps: int = 20000,
                    lr: float = 0.02) -> dict:
    """Find coverage distribution (sum <= budget, each in [0,1]) minimizing the
    attacker's best-response EV. Projected water-filling: repeatedly pour
    coverage onto whichever target the attacker currently prefers."""
    cov = {t.name: 0.0 for t in targets}
    tmap = {t.name: t for t in targets}
    spent = 0.0
    grain = budget / steps
    for _ in range(steps):
        if spent >= budget:
            break
        tgt, _ = attacker_best_response(targets, cov)
        t = tmap[tgt]
        if cov[tgt] >= 1.0 or t.def_effect <= 0:
            # can't help this one; give to next-most-attractive coverable target
            ranked = sorted(targets, key=lambda x: -x.value*(1-cov[x.name]*x.def_effect))
            tgt = next((x.name for x in ranked if cov[x.name] < 1.0 and x.def_effect > 0), None)
            if tgt is None:
                break
        cov[tgt] = min(1.0, cov[tgt] + grain)
        spent += grain
    br, ev = attacker_best_response(targets, cov)
    return {"coverage": cov, "attacker_target": br, "attacker_ev": ev,
            "budget": budget, "spent": round(spent, 6)}

def undefended_baseline(targets: list[Target]) -> tuple[str, float]:
    return attacker_best_response(targets, {})
