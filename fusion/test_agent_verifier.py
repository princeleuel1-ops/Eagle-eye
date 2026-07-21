import random
from agent_verifier import AgentVerdictProcess, certify, recompute_verdict
from merkle_ledger import MerkleLedger, verify_inclusion_obj

def _stream(rng, p, n):  # Bernoulli(p) judge scores
    return [1.0 if rng.random() < p else 0.0 for _ in range(n)]

def test_false_accept_is_alpha_controlled():
    """The money guarantee: on UNRELIABLE agents (true score mean 0.5, at/below
    theta_reliable=0.6), the fraction ever certified RELIABLE <= ~alpha, even
    though we peek after every score (anytime-valid). Baseline naive threshold
    (accept if running mean>0.6 at ANY look) inflates far past alpha."""
    rng = random.Random(11); trials = 3000; alpha = 0.05
    ev_false, base_false = 0, 0
    for _ in range(trials):
        s = _stream(rng, 0.5, 40)                 # truly unreliable-ish
        # e-process
        p = AgentVerdictProcess(theta_reliable=0.6, theta_unreliable=0.4, alpha=alpha)
        certified = any(p.update(x) == "RELIABLE" for x in s)
        ev_false += certified
        # baseline: peek — accept if running mean ever exceeds 0.6
        tot = 0; base = False
        for i, x in enumerate(s):
            tot += x
            if (tot/(i+1)) > 0.6 and i >= 4: base = True; break
        base_false += base
    ev_rate, base_rate = ev_false/trials, base_false/trials
    assert ev_rate <= 2*alpha, ev_rate            # anytime-valid holds
    assert base_rate > ev_rate                    # naive peeking inflates
    print(f"FALSE_ACCEPT e-process={ev_rate:.3f} (<= {2*alpha}) vs naive-peek={base_rate:.3f}")

def test_power_on_reliable():
    rng = random.Random(3); hit = 0
    for _ in range(300):
        s = _stream(rng, 0.9, 60)                 # genuinely reliable
        p = AgentVerdictProcess(alpha=0.05)
        if any(p.update(x) == "RELIABLE" for x in s): hit += 1
    assert hit/300 > 0.9, hit/300
    print(f"POWER reliable certified {hit}/300")

def test_stranger_recompute_and_merkle_bind():
    rng = random.Random(7)
    rec = certify(_stream(rng, 0.92, 80), agent_id="a1", task_id="t1")
    assert rec["verdict"] == "RELIABLE" and recompute_verdict(rec)   # stranger confirms
    tampered = dict(rec); tampered["verdict"] = "UNRELIABLE"
    assert not recompute_verdict(tampered)                            # tamper caught
    # SURPASS: bind verdict into Merkle transparency ledger + inclusion proof
    L = MerkleLedger(); idx = L.append(rec); L.checkpoint()
    assert verify_inclusion_obj(L.prove_inclusion(idx))
    print(f"STRANGER_VERIFY ok; verdict={rec['verdict']} stopped_at={rec['stopped_at']}; merkle-bound")

if __name__ == "__main__":
    test_false_accept_is_alpha_controlled()
    test_power_on_reliable()
    test_stranger_recompute_and_merkle_bind()
    print("SLICE4_ALL_PASS")
