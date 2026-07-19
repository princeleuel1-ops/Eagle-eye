"""V7 feedback harness: state validity, pure floor-bounded updates, and
deterministic, state-bound, whitelist-confined weighted generation."""

import copy
import json

import pytest

from eagle_eye.evolution import MUTATION_WHITELIST, default_config, generate_candidates
from eagle_eye.feedback import (
    FLOOR_WEIGHT,
    genesis_state,
    lineage_outcomes_from_bundle,
    state_sha256,
    update_state,
    validate_state,
    weighted_generate_candidates,
)

KW = dict(run_seed=424, champion_id="champ-genesis-governed-set-mt",
          champion_config=default_config(), snapshot_id="snap-test01",
          registry_manifest_sha256="a" * 64, evaluator_seed_commitment="b" * 64,
          cycle=2)


# ---------- state shape --------------------------------------------------------

def test_genesis_covers_exactly_the_whitelist():
    st = genesis_state()
    validate_state(st)
    assert set(st["weights"]) == set(MUTATION_WHITELIST)
    for key, spec in MUTATION_WHITELIST.items():
        assert set(st["weights"][key]) == {json.dumps(v, sort_keys=True) for v in spec["grid"]}
        assert all(w == FLOOR_WEIGHT for w in st["weights"][key].values())


def test_validate_rejects_tampering():
    st = genesis_state()
    missing = copy.deepcopy(st); missing["weights"].pop("selector.k_max")
    with pytest.raises(ValueError):
        validate_state(missing)
    zero = copy.deepcopy(st); zero["weights"]["selector.k_max"]["8"] = 0
    with pytest.raises(ValueError):
        validate_state(zero)
    foreign = copy.deepcopy(st); foreign["weights"]["selector.k_max"]["99"] = 1
    with pytest.raises(ValueError):
        validate_state(foreign)
    floaty = copy.deepcopy(st); floaty["weights"]["selector.k_max"]["8"] = 1.5
    with pytest.raises(ValueError):
        validate_state(floaty)


# ---------- pure update --------------------------------------------------------

def test_update_rewards_and_penalties_with_floor():
    st = genesis_state()
    st2 = update_state(st, lineage_outcomes=[
        {"diff": {"selector.k_max": 8}, "state": "PROMOTED", "mean_diff_micro": -10},
        {"diff": {"governor.widen_weak_milli": 1150}, "state": "REJECTED", "mean_diff_micro": -4},
        {"diff": {"governor.widen_weak_milli": 1600}, "state": "REJECTED", "mean_diff_micro": 7},
        {"diff": {"base.candidate": "seq_prefix"}, "state": "BLOCKED_CALIBRATION_REGRESSION",
         "mean_diff_micro": None},
    ])
    w = st2["weights"]
    assert w["selector.k_max"]["8"] == FLOOR_WEIGHT + 5           # promoted
    assert w["governor.widen_weak_milli"]["1150"] == FLOOR_WEIGHT + 2  # near miss
    assert w["governor.widen_weak_milli"]["1600"] == FLOOR_WEIGHT      # worse: unchanged
    assert w["base.candidate"]["\"seq_prefix\""] == FLOOR_WEIGHT       # blocked: floored, never < FLOOR
    assert st2["updates_applied"] == 1


def test_update_is_pure_and_ignores_foreign_diffs():
    st = genesis_state()
    before = copy.deepcopy(st)
    st2 = update_state(st, lineage_outcomes=[
        {"diff": {"not.a.key": 1}, "state": "PROMOTED", "mean_diff_micro": -1}])
    assert st == before                       # input untouched
    assert st2["weights"] == st["weights"]    # foreign diff ignored, space not widened


def test_update_applies_evidence_standing_bonus():
    st = genesis_state()
    st2 = update_state(st, lineage_outcomes=[],
                       evidence_standing=[{"diff": {"selector.min_score_milli": 6000},
                                           "cumulative_log_e_micro": 1200}])
    assert st2["weights"]["selector.min_score_milli"]["6000"] == FLOOR_WEIGHT + 1
    st3 = update_state(st, lineage_outcomes=[],
                       evidence_standing=[{"diff": {"selector.min_score_milli": 6000},
                                           "cumulative_log_e_micro": -50}])
    assert st3["weights"]["selector.min_score_milli"]["6000"] == FLOOR_WEIGHT


# ---------- weighted generation -------------------------------------------------

def test_weighted_generation_is_deterministic_and_bound_to_state():
    st = genesis_state()
    a = weighted_generate_candidates(**KW, feedback_state=st)
    b = weighted_generate_candidates(**KW, feedback_state=st)
    assert a == b and len(a) == 3
    sha = state_sha256(st)
    assert all(c["feedback_state_sha256"] == sha for c in a)
    st2 = update_state(st, lineage_outcomes=[
        {"diff": {"selector.k_max": 8}, "state": "PROMOTED", "mean_diff_micro": -1}])
    c = weighted_generate_candidates(**KW, feedback_state=st2)
    assert [x["candidate_id"] for x in c] != [x["candidate_id"] for x in a]


def test_weighted_generation_respects_whitelist_rules():
    st = genesis_state()
    champion = default_config()
    for cyc in range(1, 30):
        for cand in weighted_generate_candidates(**{**KW, "cycle": cyc}, feedback_state=st):
            (key, value), = cand["diff"].items()
            assert key in MUTATION_WHITELIST
            assert value in MUTATION_WHITELIST[key]["grid"]
            assert value != champion[key]
            assert not (key.startswith("seq.") and champion["base.candidate"] == "set_mt")
            assert cand["config"] == {**champion, key: value}


def test_weighted_generation_steers_toward_heavy_weights():
    st = genesis_state()
    st["weights"]["governor.shift_suspect_milli"]["900"] = 5000  # dominate
    validate_state(st)
    hits = 0
    for cyc in range(1, 21):
        for cand in weighted_generate_candidates(**{**KW, "cycle": cyc}, feedback_state=st):
            if cand["diff"] == {"governor.shift_suspect_milli": 900}:
                hits += 1
    assert hits >= 15  # deterministic; heavy weight dominates but floor keeps others alive


def test_floor_prevents_starvation():
    st = genesis_state()
    st["weights"]["governor.shift_suspect_milli"]["900"] = 5000
    validate_state(st)
    seen_other = set()
    for cyc in range(1, 61):
        for cand in weighted_generate_candidates(**{**KW, "cycle": cyc}, feedback_state=st):
            if cand["diff"] != {"governor.shift_suspect_milli": 900}:
                seen_other.add(json.dumps(cand["diff"], sort_keys=True))
    assert len(seen_other) >= 3  # exploration survives extreme reweighting


def test_weighted_ids_differ_from_legacy_ids():
    """Feedback-path candidates are a DIFFERENT committed family than legacy
    ones for the same core — no id collision between the two specs."""
    legacy = generate_candidates(**KW)
    weighted = weighted_generate_candidates(**KW, feedback_state=genesis_state())
    assert {c["candidate_id"] for c in legacy}.isdisjoint(
        {c["candidate_id"] for c in weighted})


def test_lineage_outcomes_extractor_shape():
    bundle = {"chains": {"lineage": {"rows": [
        {"body": {"candidate": {"diff": {"selector.k_max": 8}}, "state": "REJECTED",
                  "statistics": {"mean_diff_micro": -3}}},
        {"body": {"candidate": {"diff": {"seq.decay_milli": 600}}, "state": "REJECTED",
                  "statistics": None}},
    ]}}}
    out = lineage_outcomes_from_bundle(bundle)
    assert out == [
        {"diff": {"selector.k_max": 8}, "state": "REJECTED", "mean_diff_micro": -3},
        {"diff": {"seq.decay_milli": 600}, "state": "REJECTED", "mean_diff_micro": None},
    ]
