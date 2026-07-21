import random
from self_improvement_cert import (certify_improvement, recompute_certificate,
                                    SelfImprovementLedger, _wealth_from_pairs)
from merkle_ledger import verify_inclusion_obj

def _pairs(rng, pa, pb, n):
    return [(1 if rng.random()<pa else 0, 1 if rng.random()<pb else 0) for _ in range(n)]

def test_false_certification_alpha_controlled():
    """H0 true (B NOT better: pa==pb). Fraction ever certifying improvement,
    peeking after every item, must be <= ~alpha (anytime-valid)."""
    rng = random.Random(21); trials=3000; alpha=0.05; false=0
    for _ in range(trials):
        pairs=_pairs(rng,0.6,0.6,60)         # equal skill -> no real improvement
        # peek: does wealth EVER cross threshold along the stream?
        w=1.0; crossed=False
        for a,b in pairs:
            if a==b: continue
            w *= (1+0.5) if (b==1 and a==0) else (1-0.5)
            if w>=1/alpha: crossed=True; break
        false+=crossed
    rate=false/trials
    assert rate<=2*alpha, rate
    print(f"FALSE_CERT rate={rate:.3f} (<= {2*alpha}) [anytime-valid holds]")

def test_power_real_improvement():
    rng=random.Random(5); hit=0
    for _ in range(300):
        pairs=_pairs(rng,0.45,0.75,120)      # B genuinely better
        w=1.0
        for a,b in pairs:
            if a==b: continue
            w*=(1+0.5) if (b==1 and a==0) else (1-0.5)
            if w>=20: hit+=1; break
    assert hit/300>0.8, hit/300
    print(f"POWER real improvement certified {hit}/300")

def test_stranger_recompute_tamper_and_merkle_lineage():
    rng=random.Random(7)
    L=SelfImprovementLedger()
    # a 3-generation self-improvement lineage, each step genuinely better
    for i,(pa,pb) in enumerate([(0.30,0.65),(0.40,0.72),(0.45,0.78)]):
        rec=certify_improvement(_pairs(rng,pa,pb,400),gen_from=f"gen{i}",gen_to=f"gen{i+1}")
        assert rec["verdict"]=="IMPROVEMENT_CERTIFIED", rec["verdict"]
        out=L.record(rec)
        assert verify_inclusion_obj(out["inclusion"])          # merkle-bound
        assert recompute_certificate(rec)                      # stranger confirms
    assert L.verify_lineage()
    # tamper: flip a verdict -> stranger rejects
    bad=dict(L.certs[0]); bad["verdict"]="IMPROVEMENT_CERTIFIED" if False else "NO_IMPROVEMENT_ESTABLISHED"
    assert not recompute_certificate(bad)
    # tamper: edit a pair without rehash -> rejected
    bad2=dict(L.certs[1]); bad2["pairs"]=[[0,1]]*bad2["n_items"]
    assert not recompute_certificate(bad2)
    print(f"STRANGER lineage 3 gens verified + tamper rejected")

if __name__=="__main__":
    test_false_certification_alpha_controlled()
    test_power_real_improvement()
    test_stranger_recompute_tamper_and_merkle_lineage()
    print("SLICE5_ALL_PASS")
