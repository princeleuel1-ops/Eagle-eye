import random
# ---- Slice 1 integration ----
from merkle_ledger import MerkleLedger, verify_inclusion_obj, verify_transition
def test_slice1_ledger():
    L = MerkleLedger()
    for i in range(50): L.append({"decision": i, "verdict": "PROMOTED" if i%7==0 else "REJECTED"})
    cp1 = L.checkpoint()
    for i in range(50, 130): L.append({"decision": i, "verdict": "REJECTED"})
    cp2 = L.checkpoint()
    assert verify_inclusion_obj(L.prove_inclusion(123))
    assert verify_transition(cp1["root"], cp1["size"], L.prove_consistency(cp1["size"]))
    # tamper an OLD entry, rebuild -> transition from honest cp1 must FAIL
    L.leaves[10] = b'{"decision":10,"verdict":"ATTACKER"}'
    assert not verify_transition(cp1["root"], cp1["size"], L.prove_consistency(cp1["size"]))
    print("SLICE1_LEDGER_OK inclusion+consistency+tamper-detect")

# ---- Slice 2 percolation ----
from cascading_risk import Graph, add_edge, analyze, systemic_importance
def test_slice2_percolation_threshold():
    # Erdos-Renyi-ish: build random graph with mean degree ~ around threshold,
    # verify giant-cascade fraction rises with failure probability (monotone).
    rng = random.Random(1); g: Graph = {}
    nodes = [f"n{i}" for i in range(60)]
    for i in nodes: g.setdefault(i, set())
    for i in range(len(nodes)):
        for j in range(i+1, len(nodes)):
            if rng.random() < 0.06: add_edge(g, nodes[i], nodes[j])
    lo = analyze(g, {n:0.05 for n in g}, trials=400)["expected_cascade_frac"]
    hi = analyze(g, {n:0.60 for n in g}, trials=400)["expected_cascade_frac"]
    assert hi > lo, (lo, hi)
    imp = systemic_importance(g, {n:0.3 for n in g}, trials=200)
    assert imp and imp[0][1] >= imp[-1][1]     # ranking is ordered
    print(f"SLICE2_PERColation_OK cascade rises {lo:.3f}->{hi:.3f}; top node={imp[0][0]}")

# ---- Slice 3 security game ----
from adversary_game import Target, optimal_defense, undefended_baseline, attacker_best_response
def test_slice3_security_game():
    targets = [Target("port", 100, 0.9), Target("rail", 70, 0.9),
               Target("grid", 120, 0.9), Target("water", 90, 0.9)]
    base_t, base_ev = undefended_baseline(targets)      # attacks highest value = grid(120)
    assert base_t == "grid" and abs(base_ev-120) < 1e-9
    res = optimal_defense(targets, budget=2.0)
    # optimal randomized defense must LOWER attacker's expected value
    assert res["attacker_ev"] < base_ev, res
    print(f"SLICE3_GAME_OK undef EV={base_ev:.0f} -> defended EV={res['attacker_ev']:.1f} "
          f"(attacker now prefers {res['attacker_target']})")

if __name__ == "__main__":
    test_slice1_ledger(); test_slice2_percolation_threshold(); test_slice3_security_game()
    print("ALL_THREE_SLICES_PASS")
