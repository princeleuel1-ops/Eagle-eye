"""V4 blocker 6: suite scaling must be honest sample-size scaling — the exact
stratum and observation-count distribution is preserved and every replica is
an INDEPENDENT case resample. The V3 behavior (n_target_obs incremented per
replica) changed stratum composition and is withdrawn."""
from collections import Counter

from eagle_eye.prediction_court import build_holdout_suite, suite_manifest


def _stratum(row):
    return (row["subset"], row["target"]["disruption_class"],
            row["target"]["as_of_cutoff"], len(row["target"]["observations"]),
            row["k_max"])


def test_scale_preserves_stratum_distribution_exactly():
    base = build_holdout_suite(4242, scale=1)
    scaled = build_holdout_suite(4242, scale=3)
    assert len(scaled["cases"]) == 3 * len(base["cases"])
    base_strata = Counter(_stratum(r) for r in base["cases"])
    scaled_strata = Counter(_stratum(r) for r in scaled["cases"])
    assert scaled_strata == Counter({k: 3 * v for k, v in base_strata.items()}), \
        "scaling changed the stratum/observation-count distribution"


def test_scale_replicas_are_independent_resamples():
    scaled = build_holdout_suite(4242, scale=2)
    n = len(scaled["cases"]) // 2
    first, second = scaled["cases"][:n], scaled["cases"][n:]
    assert {r["target"]["case_id"] for r in first}.isdisjoint(
        {r["target"]["case_id"] for r in second})
    # independent draws: every replica pair with observations differs in its
    # observed values; zero-obs pairs (scarcity/OoD strata) differ in latent truth
    for a, b in zip(first, second):
        if a["target"]["observations"]:
            assert a["target"]["observations"] != b["target"]["observations"]
        else:
            assert a["truth"]["theta"] != b["truth"]["theta"]


def test_suite_manifest_is_deterministic_and_content_bound():
    a = suite_manifest(build_holdout_suite(777, scale=2))
    b = suite_manifest(build_holdout_suite(777, scale=2))
    c = suite_manifest(build_holdout_suite(778, scale=2))
    assert a == b
    assert a["cases_sha256"] != c["cases_sha256"]
    assert a["truth_sha256"] != c["truth_sha256"]
    assert a["case_count"] == 2 * suite_manifest(build_holdout_suite(777, scale=1))["case_count"]
