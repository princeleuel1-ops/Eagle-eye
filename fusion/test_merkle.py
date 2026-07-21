import os, random
from transparency_merkle import (merkle_root, inclusion_proof, verify_inclusion,
                                  consistency_proof, verify_consistency)

def test_inclusion_all_sizes():
    for n in range(1, 130):
        entries = [f"entry-{i}".encode() for i in range(n)]
        root = merkle_root(entries)
        for m in range(n):
            p = inclusion_proof(entries, m)
            assert verify_inclusion(entries[m], m, n, p, root), (n, m)
            # tamper: wrong leaf must fail
            assert not verify_inclusion(b"WRONG", m, n, p, root), (n, m, "tamper")
    print("INCLUSION_OK all sizes 1..129")

def test_consistency_all_sizes():
    for n in range(1, 90):
        entries = [f"e-{i}".encode() for i in range(n)]
        new_root = merkle_root(entries)
        for m in range(1, n + 1):
            old_root = merkle_root(entries[:m])
            proof = consistency_proof(entries, m, n)
            assert verify_consistency(m, n, proof, old_root, new_root), (m, n)
    print("CONSISTENCY_OK all sizes 1..89")

def test_consistency_detects_tampering():
    # A retroactively EDITED history must fail the consistency proof.
    n = 40
    entries = [f"e-{i}".encode() for i in range(n)]
    m = 25
    old_root = merkle_root(entries[:m])              # what an auditor saw at size 25
    # attacker edits an OLD entry (index 10) and presents a new size-40 log
    tampered = list(entries); tampered[10] = b"ATTACKER-REWROTE-HISTORY"
    new_root_bad = merkle_root(tampered)
    proof = consistency_proof(tampered, m, n)
    # consistency vs the HONEST old_root the auditor holds must FAIL
    assert not verify_consistency(m, n, proof, old_root, new_root_bad)
    print("TAMPER_DETECTED consistency proof rejects retroactive edit")

def test_random_fuzz():
    rng = random.Random(7)
    for _ in range(300):
        n = rng.randint(1, 200)
        entries = [os.urandom(8) for _ in range(n)]
        root = merkle_root(entries)
        m = rng.randrange(n)
        assert verify_inclusion(entries[m], m, n, inclusion_proof(entries, m), root)
        k = rng.randint(1, n)
        assert verify_consistency(k, n, consistency_proof(entries, k, n),
                                  merkle_root(entries[:k]), root)
    print("FUZZ_OK 300 random trees")

if __name__ == "__main__":
    test_inclusion_all_sizes()
    test_consistency_all_sizes()
    test_consistency_detects_tampering()
    test_random_fuzz()
    print("ALL_MERKLE_TESTS_PASS")
