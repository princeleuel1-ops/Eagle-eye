"""FUSION SLICE 2 — Percolation theory (physics) -> cascading-risk scoring.

COLLISION:
  Gene A (statistical physics): bond/site percolation — as nodes/edges fail
    with probability, connected clusters form; above a critical threshold a
    giant component emerges (systemic collapse). p_c ~= 1/<k> for ER graphs.
  Gene B (Eagle Eye's original domain): supply-chain / dependency disruption
    intelligence — "if this supplier fails, what cascades?"

FUSION: a Monte-Carlo percolation engine over a dependency graph that scores
  (1) probability a TARGET is reached by a cascade,
  (2) expected cascade size,
  (3) systemic-importance ranking (whose failure most grows the giant comp),
  (4) proximity to the percolation threshold (early-warning of systemic risk).
Clean-room, stdlib only. Provenance: percolation theory is public science
(Broadbent-Hammersley 1957; Erdos-Renyi). No code reused.
"""
from __future__ import annotations
import random
from typing import Iterable

Graph = dict[str, set[str]]

def add_edge(g: Graph, a: str, b: str) -> None:
    g.setdefault(a, set()).add(b); g.setdefault(b, set()).add(a)

def _component_size(g: Graph, alive: set[str], start: str) -> set[str]:
    seen, stack = {start}, [start]
    while stack:
        u = stack.pop()
        for v in g.get(u, ()):
            if v in alive and v not in seen:
                seen.add(v); stack.append(v)
    return seen

def cascade_trial(g: Graph, fail_p: dict[str, float], rng: random.Random) -> set[str]:
    """One percolation trial: each node independently fails w.p. fail_p[n].
    Returns the set of FAILED nodes reachable-connected into the failure set
    (a node cascades if it fails OR is only supported through failed nodes).
    Simplified contagion: a node is 'down' if it fails, then failure spreads to
    neighbors that lose all alive support."""
    down = {n for n in g if rng.random() < fail_p.get(n, 0.0)}
    changed = True
    while changed:
        changed = False
        for n in g:
            if n in down:
                continue
            nb = g[n]
            if nb and all(m in down for m in nb):   # lost all support
                down.add(n); changed = True
    return down

def analyze(g: Graph, fail_p: dict[str, float], *, target: str | None = None,
            trials: int = 2000, seed: int = 7) -> dict:
    rng = random.Random(seed)
    n = len(g)
    hit = 0; sizes = []; giant = []
    for _ in range(trials):
        down = cascade_trial(g, fail_p, rng)
        sizes.append(len(down))
        if target is not None and target in down:
            hit += 1
        # giant component among DOWN nodes
        if down:
            big = max((len(_component_size(g, down, s)) for s in down), default=0)
        else:
            big = 0
        giant.append(big)
    return {
        "nodes": n, "trials": trials,
        "target_hit_prob": (hit / trials) if target else None,
        "expected_cascade_frac": sum(sizes) / trials / n,
        "expected_giant_frac": sum(giant) / trials / n,
        "systemic": sum(giant) / trials / n > 0.5,   # giant comp => systemic regime
    }

def systemic_importance(g: Graph, fail_p: dict[str, float], **kw) -> list[tuple[str, float]]:
    """Rank nodes by how much REMOVING them (hardening to fail_p=0) reduces the
    expected giant cascade — the ones worth defending first."""
    base = analyze(g, fail_p, **kw)["expected_giant_frac"]
    out = []
    for n in g:
        fp = dict(fail_p); fp[n] = 0.0
        lift = base - analyze(g, fp, **kw)["expected_giant_frac"]
        out.append((n, lift))
    return sorted(out, key=lambda x: -x[1])
