from __future__ import annotations

import copy

import pytest

from eagle_eye.regimes_adversarial import family_panel
from eagle_eye.transfer import (
    BASELINE_RELEASE,
    WTransferCourt,
    build_preregistered_protocol,
    cluster_sign,
    cluster_sum_micro,
    stream_id,
    validate_case_rows,
    validate_protocol,
)


def _dummy_case(case_id: str, *, nll_diff: int, crps_diff: int) -> dict:
    champion_nll = 1_000_000
    baseline_nll = champion_nll - nll_diff
    champion_crps = 2_000_000
    baseline_crps = champion_crps - crps_diff
    return {
        "case_index": int(case_id.rsplit("-", 1)[1]),
        "target_spec": {"disruption_class": "port_congestion", "cutoff": "2025-04-14", "n_target_obs": 2},
        "target": {"case_id": case_id, "observations": [{"t": "2025-04-10", "log_delay_days": 1.2}]},
        "truth": {"case_id": case_id, "outcomes": {"wait_incumbent": {"log_final_delay": 1.4}}},
        "selection": {"prior_manifest_sha256": "p" * 64, "K": 3},
        "champion_prediction": {"candidate": "champion", "model_release": "champion/1.0"},
        "baseline_prediction": {"candidate": "no_prefix", "model_release": BASELINE_RELEASE},
        "champion_score": {"abstained": False, "nll_micro": champion_nll, "crps_micro": champion_crps, "covered80": True},
        "baseline_score": {"abstained": False, "nll_micro": baseline_nll, "crps_micro": baseline_crps, "covered80": True},
        "diff_micro": {"nll": nll_diff, "crps": crps_diff},
    }


def _protocol() -> dict:
    return build_preregistered_protocol(
        champion_config_hash="c" * 64,
        family_manifests=family_panel()[:2],
        seeds=[701, 702],
        target_plan=[{"disruption_class": "port_congestion", "cutoff": "2025-04-14", "n_target_obs": 2}],
        baseline_release=BASELINE_RELEASE,
    )


def test_protocol_hash_refuses_alpha_and_metric_substitution():
    protocol = _protocol()
    validate_protocol(protocol)

    forged_alpha = copy.deepcopy(protocol)
    forged_alpha["alpha_total_micro"] += 1
    with pytest.raises(ValueError, match="protocol_hash"):
        validate_protocol(forged_alpha)

    forged_metric = copy.deepcopy(protocol)
    forged_metric["metrics"] = ["nll"]
    with pytest.raises(ValueError, match="protocol_hash"):
        validate_protocol(forged_metric)


def test_cluster_accounting_is_seed_level_and_order_invariant():
    protocol = _protocol()
    family = protocol["family_manifests"][0]
    rows = [
        _dummy_case("case-1", nll_diff=-7, crps_diff=9),
        _dummy_case("case-2", nll_diff=3, crps_diff=-11),
        _dummy_case("case-3", nll_diff=-8, crps_diff=4),
    ]
    assert cluster_sum_micro(rows, "nll") == -12
    assert cluster_sum_micro(list(reversed(rows)), "nll") == -12
    assert cluster_sign(cluster_sum_micro(rows, "nll")) == "win"

    court = WTransferCourt(protocol, champion_bundle_sha256="b" * 64)
    court.admit_seed_evidence(
        family_manifest=family,
        world_seed=701,
        registry_release="registry/family-701",
        case_rows=list(reversed(rows)),
    )
    nll_stream = next(
        row for row in court.standing()
        if row["family_id"] == family["family_id"] and row["metric"] == "nll"
    )
    assert nll_stream["wins"] == 1
    assert nll_stream["losses"] == 0
    assert nll_stream["ties"] == 0
    assert len(nll_stream["history"]) == 1


def test_duplicate_seed_admission_is_refused():
    protocol = _protocol()
    family = protocol["family_manifests"][0]
    court = WTransferCourt(protocol, champion_bundle_sha256="b" * 64)
    rows = [_dummy_case("case-1", nll_diff=-5, crps_diff=-4)]
    court.admit_seed_evidence(
        family_manifest=family,
        world_seed=701,
        registry_release="registry/family-701",
        case_rows=rows,
    )
    with pytest.raises(ValueError, match="duplicate"):
        court.admit_seed_evidence(
            family_manifest=family,
            world_seed=701,
            registry_release="registry/family-701",
            case_rows=rows,
        )


def test_stream_ids_bind_family_metric_and_baseline_release():
    protocol_hash = "p" * 64
    champion_config_hash = "c" * 64
    families = family_panel()[:2]
    ids = {
        stream_id(protocol_hash, families[0]["family_id"], families[0]["family_release"], "nll",
                  champion_config_hash, BASELINE_RELEASE),
        stream_id(protocol_hash, families[0]["family_id"], families[0]["family_release"], "crps",
                  champion_config_hash, BASELINE_RELEASE),
        stream_id(protocol_hash, families[1]["family_id"], families[1]["family_release"], "nll",
                  champion_config_hash, BASELINE_RELEASE),
        stream_id(protocol_hash, families[0]["family_id"], families[0]["family_release"], "nll",
                  champion_config_hash, "forged-baseline/9.9"),
    }
    assert len(ids) == 4


def test_nonfinite_scores_are_refused():
    rows = [_dummy_case("case-1", nll_diff=-5, crps_diff=-4)]
    validate_case_rows(rows)
    forged = copy.deepcopy(rows)
    forged[0]["champion_score"]["nll_micro"] = float("inf")
    with pytest.raises(ValueError, match="nonfinite"):
        validate_case_rows(forged)


def test_invalid_first_admission_does_not_poison_unit_retry():
    protocol = _protocol()
    family = protocol["family_manifests"][0]
    court = WTransferCourt(protocol, champion_bundle_sha256="b" * 64)
    rows = [_dummy_case("case-1", nll_diff=-5, crps_diff=-4)]
    forged = copy.deepcopy(rows)
    forged[0]["champion_score"]["nll_micro"] = float("inf")
    with pytest.raises(ValueError, match="nonfinite"):
        court.admit_seed_evidence(
            family_manifest=family,
            world_seed=701,
            registry_release="registry/family-701",
            case_rows=forged,
        )
    court.admit_seed_evidence(
        family_manifest=family,
        world_seed=701,
        registry_release="registry/family-701",
        case_rows=rows,
    )
