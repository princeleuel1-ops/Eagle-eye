from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .eprocess import log_e_micro
from .evolution import predictor_from_config
from .prediction_court import COVERAGE_BAND, scored_dist
from .predictors import predict_no_prefix
from .prior_registry import build_registry, canonical_bytes, sha256_hex
from .prior_selector import compile_prior_context, select_prior_tasks
from .regimes_adversarial import (
    FAMILY_ORDER,
    family_manifest as family_manifest_by_id,
    family_panel,
    generate_family_target,
    generate_family_world,
)
from .signed_chain import SignedChain, verify_chain
from .signing import generate_demo_keypair

W_TRANSFER_PROTOCOL_SPEC = "eagle-eye-w-transfer/1.0"
W_TRANSFER_BUNDLE_SPEC = "w-transfer-bundle/1.0"
W_TRANSFER_RECEIPT_SPEC = "w-transfer-receipt/1.0"
W_TRANSFER_ALPHA_TOTAL_MICRO = 50_000
W_TRANSFER_METRICS = ("nll", "crps")
W_TRANSFER_TASKS_PER_CLASS = 12
W_TRANSFER_SEEDS = [98101, 98102, 98103, 98104]
W_TRANSFER_TARGET_PLAN = [
    {"disruption_class": "port_congestion", "cutoff": "2025-04-14", "n_target_obs": 1},
    {"disruption_class": "port_congestion", "cutoff": "2025-06-09", "n_target_obs": 2},
    {"disruption_class": "supplier_quality", "cutoff": "2025-04-21", "n_target_obs": 2},
    {"disruption_class": "supplier_quality", "cutoff": "2025-06-16", "n_target_obs": 4},
    {"disruption_class": "geopolitical", "cutoff": "2025-05-05", "n_target_obs": 1},
    {"disruption_class": "geopolitical", "cutoff": "2025-06-23", "n_target_obs": 4},
]
BASELINE_RELEASE = "no-prefix-conjugate/1.0"
ALIEN_TRANSFER_EVIDENCE_EARNED = "ALIEN_TRANSFER_EVIDENCE_EARNED"
NO_ALIEN_TRANSFER_EVIDENCE_EARNED = "NO_ALIEN_TRANSFER_EVIDENCE_EARNED"


def stream_id(
    protocol_hash: str,
    family_id: str,
    family_release: str,
    metric: str,
    champion_config_hash: str,
    baseline_release: str,
) -> str:
    return "wstrm-" + sha256_hex(canonical_bytes({
        "protocol_hash": protocol_hash,
        "family_id": family_id,
        "family_release": family_release,
        "metric": metric,
        "champion_config_hash": champion_config_hash,
        "baseline_release": baseline_release,
    }))[:16]


def cluster_sign(sum_micro: int) -> str:
    if sum_micro < 0:
        return "win"
    if sum_micro > 0:
        return "loss"
    return "tie"


def validate_family_manifest(manifest: dict[str, Any], expected: dict[str, Any] | None = None) -> dict[str, Any]:
    required = {
        "panel_release",
        "family_id",
        "family_release",
        "generator_release",
        "seed_namespace",
        "schema_release",
        "kernels",
        "dependence",
        "tail",
        "intervention",
        "stockout",
        "structural_parent",
        "source_commitment",
    }
    missing = sorted(required - set(manifest))
    if missing:
        raise ValueError(f"family manifest missing fields: {', '.join(missing)}")
    if manifest["schema_release"] != "prior-task/1.0":
        raise ValueError(f"unsupported schema_release {manifest['schema_release']!r}")
    if expected is not None and canonical_bytes(manifest) != canonical_bytes(expected):
        raise ValueError(f"family manifest mismatch for {expected['family_id']}")
    return manifest


def _protocol_body(protocol: dict[str, Any]) -> dict[str, Any]:
    return {
        "spec": protocol["spec"],
        "alpha_total_micro": protocol["alpha_total_micro"],
        "metrics": protocol["metrics"],
        "seeds": protocol["seeds"],
        "target_plan": protocol["target_plan"],
        "family_manifests": protocol["family_manifests"],
        "baseline_release": protocol["baseline_release"],
        "champion_config_hash": protocol["champion_config_hash"],
        "stream_count": protocol["stream_count"],
        "log_threshold_micro": protocol["log_threshold_micro"],
        "headline_family_ids": protocol["headline_family_ids"],
        "headline_rule": protocol["headline_rule"],
    }


def build_preregistered_protocol(
    *,
    champion_config_hash: str,
    family_manifests: list[dict[str, Any]] | None = None,
    seeds: list[int] | None = None,
    target_plan: list[dict[str, Any]] | None = None,
    baseline_release: str = BASELINE_RELEASE,
    alpha_total_micro: int = W_TRANSFER_ALPHA_TOTAL_MICRO,
) -> dict[str, Any]:
    family_manifests = [dict(manifest) for manifest in (family_manifests or family_panel())]
    seeds = list(seeds or W_TRANSFER_SEEDS)
    target_plan = list(target_plan or W_TRANSFER_TARGET_PLAN)
    if [manifest["family_id"] for manifest in family_manifests] != list(FAMILY_ORDER)[:len(family_manifests)]:
        expected = list(FAMILY_ORDER)[:len(family_manifests)]
        raise ValueError(f"family order mismatch: expected prefix {expected}")
    for manifest in family_manifests:
        validate_family_manifest(manifest)
    if len({manifest["family_id"] for manifest in family_manifests}) != len(family_manifests):
        raise ValueError("duplicate family_id in preregistration")
    if len(seeds) != len(set(seeds)):
        raise ValueError("duplicate seed in preregistration")
    stream_count = len(family_manifests) * len(W_TRANSFER_METRICS)
    log_threshold_micro = round(math.log(stream_count * 1e6 / alpha_total_micro) * 1e6)
    protocol = {
        "spec": W_TRANSFER_PROTOCOL_SPEC,
        "alpha_total_micro": alpha_total_micro,
        "metrics": list(W_TRANSFER_METRICS),
        "seeds": seeds,
        "target_plan": target_plan,
        "family_manifests": family_manifests,
        "baseline_release": baseline_release,
        "champion_config_hash": champion_config_hash,
        "stream_count": stream_count,
        "log_threshold_micro": log_threshold_micro,
        "headline_family_ids": [
            manifest["family_id"]
            for manifest in family_manifests
            if manifest["structural_parent"] is None
        ],
        "headline_rule": "all structurally independent family x metric streams must cross",
    }
    protocol["protocol_hash"] = sha256_hex(canonical_bytes(_protocol_body(protocol)))
    protocol["headline_stream_ids"] = [
        stream_id(
            protocol["protocol_hash"],
            manifest["family_id"],
            manifest["family_release"],
            metric,
            champion_config_hash,
            baseline_release,
        )
        for manifest in family_manifests
        if manifest["structural_parent"] is None
        for metric in W_TRANSFER_METRICS
    ]
    return protocol


def validate_protocol(protocol: dict[str, Any]) -> dict[str, Any]:
    expected_hash = sha256_hex(canonical_bytes(_protocol_body(protocol)))
    if protocol.get("protocol_hash") != expected_hash:
        raise ValueError("protocol_hash mismatch")
    if protocol.get("metrics") != list(W_TRANSFER_METRICS):
        raise ValueError("protocol metrics mismatch")
    for manifest in protocol["family_manifests"]:
        validate_family_manifest(manifest, family_manifest_by_id(manifest["family_id"]))
    return protocol


def validate_case_rows(case_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    for row in case_rows:
        case_id = row["target"]["case_id"]
        if case_id in seen:
            raise ValueError(f"duplicate case_id {case_id}")
        seen.add(case_id)
        for side in ("champion_score", "baseline_score"):
            score = row[side]
            if score["abstained"]:
                continue
            for field in ("nll_micro", "crps_micro"):
                value = score[field]
                if not isinstance(value, int) or not math.isfinite(value):
                    raise ValueError(f"nonfinite or non-integer {side}.{field}")
        if row["champion_score"]["abstained"] or row["baseline_score"]["abstained"]:
            if any(row["diff_micro"][metric] is not None for metric in W_TRANSFER_METRICS):
                raise ValueError("abstained case may not carry score diffs")
            continue
        for metric in W_TRANSFER_METRICS:
            expected = row["champion_score"][f"{metric}_micro"] - row["baseline_score"][f"{metric}_micro"]
            if row["diff_micro"][metric] != expected:
                raise ValueError(f"diff mismatch for {case_id} metric={metric}")
    return case_rows


def cluster_sum_micro(case_rows: list[dict[str, Any]], metric: str) -> int:
    validate_case_rows(case_rows)
    ordered = sorted(case_rows, key=lambda row: row["target"]["case_id"])
    return sum(row["diff_micro"][metric] for row in ordered if row["diff_micro"][metric] is not None)


def serialize_prediction(prediction: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in prediction.items() if not key.startswith("_")}


def score_prediction(prediction: dict[str, Any], truth: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(prediction, dict) or "interventions" not in prediction:
        raise ValueError("malformed prediction response")
    if prediction.get("interventions") is None:
        return {"abstained": True, "nll_micro": None, "crps_micro": None, "covered80": None}
    dist = scored_dist(prediction, "wait_incumbent")
    y = truth["outcomes"]["wait_incumbent"]["log_final_delay"]
    lo, hi = dist.ppf(0.10), dist.ppf(0.90)
    nll = -dist.logpdf(y)
    crps = dist.crps(y)
    if not (math.isfinite(nll) and math.isfinite(crps)):
        raise ValueError("nonfinite score detected")
    return {
        "abstained": False,
        "nll_micro": int(round(nll * 1e6)),
        "crps_micro": int(round(crps * 1e6)),
        "covered80": bool(lo <= y <= hi),
    }


def evaluate_case_row(
    *,
    family_id: str,
    registry: dict[str, Any],
    target_spec: dict[str, Any],
    target: dict[str, Any],
    truth: dict[str, Any],
    champion_config: dict[str, Any],
) -> dict[str, Any]:
    selection = select_prior_tasks(
        registry,
        target,
        k_max=champion_config["selector.k_max"],
        min_score=champion_config["selector.min_score_milli"] / 1000.0,
    )
    compiled = compile_prior_context(selection["included"], target)
    champion_prediction = predictor_from_config(champion_config)(compiled)
    baseline_prediction = predict_no_prefix(compiled)
    champion_score = score_prediction(champion_prediction, truth)
    baseline_score = score_prediction(baseline_prediction, truth)
    diffs = {
        metric: None
        if champion_score["abstained"] or baseline_score["abstained"]
        else champion_score[f"{metric}_micro"] - baseline_score[f"{metric}_micro"]
        for metric in W_TRANSFER_METRICS
    }
    return {
        "family_id": family_id,
        "target_spec": dict(target_spec),
        "target": target,
        "truth": truth,
        "selection": {
            "receipt": selection["receipt"],
            "prior_manifest_sha256": compiled["prior_manifest_sha256"],
            "K": compiled["K"],
        },
        "champion_prediction": serialize_prediction(champion_prediction),
        "baseline_prediction": serialize_prediction(baseline_prediction),
        "champion_score": champion_score,
        "baseline_score": baseline_score,
        "diff_micro": diffs,
    }


def evaluate_family_seed(
    *,
    family_manifest: dict[str, Any],
    world_seed: int,
    champion_config: dict[str, Any],
    target_plan: list[dict[str, Any]],
    tenant_id: str = "tenant-demo",
) -> dict[str, Any]:
    family_spec = family_manifest
    validate_family_manifest(family_spec, family_manifest_by_id(family_spec["family_id"]))
    world = generate_family_world(
        family_spec["family_id"],
        world_seed,
        tasks_per_class=W_TRANSFER_TASKS_PER_CLASS,
        tenant_id=tenant_id,
    )
    if world["generator_release"] != family_spec["generator_release"]:
        raise ValueError(f"generator release mismatch for family {family_spec['family_id']}")
    registry = build_registry(
        list(world["tasks"]),
        release=f"prior-registry/{family_spec['family_id']}-{world_seed}",
    )
    case_rows = []
    for case_index, target_spec in enumerate(target_plan):
        case = generate_family_target(
            family_spec["family_id"],
            world=world,
            world_seed=world_seed,
            case_index=7000 + case_index,
            disruption_class=target_spec["disruption_class"],
            cutoff=target_spec["cutoff"],
            n_target_obs=target_spec["n_target_obs"],
            tenant_id=tenant_id,
        )
        row = evaluate_case_row(
            family_id=family_spec["family_id"],
            registry=registry,
            target_spec=target_spec,
            target=case["target"],
            truth=case["truth"],
            champion_config=champion_config,
        )
        row["case_index"] = case_index
        case_rows.append(row)
    validate_case_rows(case_rows)
    cluster_sums = {metric: cluster_sum_micro(case_rows, metric) for metric in W_TRANSFER_METRICS}
    cluster_signs = {metric: cluster_sign(cluster_sums[metric]) for metric in W_TRANSFER_METRICS}
    champion_cases = [row["champion_score"] for row in case_rows if not row["champion_score"]["abstained"]]
    baseline_cases = [row["baseline_score"] for row in case_rows if not row["baseline_score"]["abstained"]]
    coverage_hits = [score["covered80"] for score in champion_cases if score["covered80"] is not None]
    return {
        "family_id": family_spec["family_id"],
        "family_release": family_spec["family_release"],
        "generator_release": world["generator_release"],
        "world_seed": world_seed,
        "unit_id": sha256_hex(canonical_bytes({
            "family_id": family_spec["family_id"],
            "world_seed": world_seed,
            "generator_release": world["generator_release"],
        }))[:16],
        "registry_release": registry["release"],
        "registry_manifest_sha256": registry["manifest_sha256"],
        "case_rows": case_rows,
        "cluster_sums_micro": cluster_sums,
        "cluster_signs": cluster_signs,
        "paired_case_count": sum(1 for row in case_rows if row["diff_micro"]["nll"] is not None),
        "champion_abstentions_standard": sum(1 for row in case_rows if row["champion_score"]["abstained"]),
        "baseline_abstentions_standard": sum(1 for row in case_rows if row["baseline_score"]["abstained"]),
        "champion_coverage80_micro": None if not coverage_hits else int(round(sum(coverage_hits) / len(coverage_hits) * 1e6)),
        "all_scores_finite": True,
    }


class WTransferCourt:
    def __init__(
        self,
        protocol: dict[str, Any],
        *,
        champion_bundle_sha256: str,
        run_id: str | None = None,
        tenant_id: str = "tenant-demo",
    ) -> None:
        self.protocol = validate_protocol(dict(protocol))
        self.champion_bundle_sha256 = champion_bundle_sha256
        private_key, public_key = generate_demo_keypair()
        self.chain = SignedChain(
            tenant_id=tenant_id,
            run_id=run_id or f"run-w-transfer-{champion_bundle_sha256[:8]}",
            chain_id="w-transfer-history",
            private_key=private_key,
            public_key=public_key,
        )
        self.signer_registry = {
            "trusted_signers": [{
                "key_id": self.chain.signer_key_id,
                "public_key_pem": self.chain.public_key.decode(),
            }],
        }
        self._seen_units: set[tuple[str, int]] = set()
        self._history: list[dict[str, Any]] = []
        self._streams: dict[str, dict[str, Any]] = {}
        for manifest in self.protocol["family_manifests"]:
            for metric in W_TRANSFER_METRICS:
                sid = stream_id(
                    self.protocol["protocol_hash"],
                    manifest["family_id"],
                    manifest["family_release"],
                    metric,
                    self.protocol["champion_config_hash"],
                    self.protocol["baseline_release"],
                )
                self._streams[sid] = {
                    "stream_id": sid,
                    "family_id": manifest["family_id"],
                    "family_release": manifest["family_release"],
                    "metric": metric,
                    "wins": 0,
                    "losses": 0,
                    "ties": 0,
                    "cumulative_log_e_micro": 0,
                    "crossed": False,
                    "first_crossing_index": None,
                    "history": [],
                }

    def admit_seed_evidence(
        self,
        *,
        family_manifest: dict[str, Any],
        world_seed: int,
        registry_release: str,
        case_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        family_spec = family_manifest
        expected_manifest = family_manifest_by_id(family_spec["family_id"])
        validate_family_manifest(family_spec, expected_manifest)
        if world_seed not in self.protocol["seeds"]:
            raise ValueError(f"unexpected seed {world_seed}")
        unit_key = (family_spec["family_id"], world_seed)
        if unit_key in self._seen_units:
            raise ValueError("duplicate family/seed admission")
        validate_case_rows(case_rows)
        self._seen_units.add(unit_key)
        cluster_sums = {metric: cluster_sum_micro(case_rows, metric) for metric in W_TRANSFER_METRICS}
        cluster_signs = {metric: cluster_sign(cluster_sums[metric]) for metric in W_TRANSFER_METRICS}
        stream_updates = []
        for metric in W_TRANSFER_METRICS:
            sid = stream_id(
                self.protocol["protocol_hash"],
                family_spec["family_id"],
                family_spec["family_release"],
                metric,
                self.protocol["champion_config_hash"],
                self.protocol["baseline_release"],
            )
            stream = self._streams[sid]
            sign = cluster_signs[metric]
            if sign == "win":
                stream["wins"] += 1
            elif sign == "loss":
                stream["losses"] += 1
            else:
                stream["ties"] += 1
            stream["cumulative_log_e_micro"] = log_e_micro(stream["wins"], stream["losses"])
            admission_index = len(stream["history"]) + 1
            crossed_after = stream["cumulative_log_e_micro"] >= self.protocol["log_threshold_micro"]
            if crossed_after and stream["first_crossing_index"] is None:
                stream["first_crossing_index"] = admission_index
            stream["crossed"] = crossed_after
            history_row = {
                "family_id": family_spec["family_id"],
                "family_release": family_spec["family_release"],
                "world_seed": world_seed,
                "registry_release": registry_release,
                "cluster_sum_micro": cluster_sums[metric],
                "sign": sign,
                "admission_index": admission_index,
                "case_count": len(case_rows),
                "paired_case_count": sum(1 for row in case_rows if row["diff_micro"][metric] is not None),
                "cumulative_log_e_micro": stream["cumulative_log_e_micro"],
                "crossed_after": crossed_after,
            }
            stream["history"].append(history_row)
            stream_updates.append({
                "metric": metric,
                "stream_id": sid,
                "sign": sign,
                "cluster_sum_micro": cluster_sums[metric],
                "wins": stream["wins"],
                "losses": stream["losses"],
                "ties": stream["ties"],
                "cumulative_log_e_micro": stream["cumulative_log_e_micro"],
                "crossed": stream["crossed"],
                "first_crossing_index": stream["first_crossing_index"],
            })
        body = {
            "kind": "seed_cluster",
            "protocol_hash": self.protocol["protocol_hash"],
            "family_id": family_spec["family_id"],
            "family_release": family_spec["family_release"],
            "world_seed": world_seed,
            "registry_release": registry_release,
            "case_count": len(case_rows),
            "paired_case_count": sum(1 for row in case_rows if row["diff_micro"]["nll"] is not None),
            "cluster_sums_micro": cluster_sums,
            "cluster_signs": cluster_signs,
            "stream_updates": stream_updates,
        }
        row = self.chain.append(body)
        self._history.append({
            **body,
            "row_hash": row["row_hash"],
            "previous_hash": row["previous_hash"],
            "sequence": row["sequence"],
        })
        return body

    def history(self) -> list[dict[str, Any]]:
        return list(self._history)

    def standing(self) -> list[dict[str, Any]]:
        return [
            json.loads(json.dumps(stream))
            for _, stream in sorted(self._streams.items(), key=lambda item: (item[1]["family_id"], item[1]["metric"]))
        ]

    def expected_unit_order(self) -> list[tuple[str, int]]:
        return [
            (manifest["family_id"], seed)
            for manifest in self.protocol["family_manifests"]
            for seed in self.protocol["seeds"]
        ]

    def verify_chain(self) -> bool:
        report = verify_chain(
            self.chain.rows,
            self.chain.anchor(),
            self.signer_registry,
            expected_tenant=self.chain.tenant_id,
            expected_chain_id=self.chain.chain_id,
            expected_run_id=self.chain.run_id,
        )
        return bool(report.get("verified", False))


def summarize_families(protocol: dict[str, Any], evaluations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = []
    band_lo = int(COVERAGE_BAND[0] * 1e6)
    band_hi = int(COVERAGE_BAND[1] * 1e6)
    for manifest in protocol["family_manifests"]:
        family_rows = [row for row in evaluations if row["family_id"] == manifest["family_id"]]
        coverage_values = [row["champion_coverage80_micro"] for row in family_rows if row["champion_coverage80_micro"] is not None]
        coverage = None if not coverage_values else int(round(sum(coverage_values) / len(coverage_values)))
        summaries.append({
            "family_id": manifest["family_id"],
            "family_release": manifest["family_release"],
            "seeds_evaluated": [row["world_seed"] for row in family_rows],
            "paired_case_count_total": sum(row["paired_case_count"] for row in family_rows),
            "champion_abstentions_standard": sum(row["champion_abstentions_standard"] for row in family_rows),
            "baseline_abstentions_standard": sum(row["baseline_abstentions_standard"] for row in family_rows),
            "champion_coverage80_micro": coverage,
            "champion_coverage_in_band": coverage is not None and band_lo <= coverage <= band_hi,
            "all_scores_finite": all(row["all_scores_finite"] for row in family_rows),
            "protocol_complete": [row["world_seed"] for row in family_rows] == protocol["seeds"],
        })
    return summaries


def headline_claim_status(protocol: dict[str, Any], standing: list[dict[str, Any]]) -> tuple[bool, str]:
    crossed = {row["stream_id"]: row["crossed"] for row in standing}
    earned = all(crossed.get(sid, False) for sid in protocol["headline_stream_ids"])
    return earned, ALIEN_TRANSFER_EVIDENCE_EARNED if earned else NO_ALIEN_TRANSFER_EVIDENCE_EARNED


def build_receipt(
    *,
    protocol: dict[str, Any],
    champion_bundle_sha256: str,
    champion_config_hash: str,
    evaluations: list[dict[str, Any]],
    court: WTransferCourt,
    replay_status: dict[str, Any],
) -> dict[str, Any]:
    family_summaries = summarize_families(protocol, evaluations)
    standing = court.standing()
    headline_crossed, headline_status = headline_claim_status(protocol, standing)
    expected_order = [
        {"family_id": family_id, "world_seed": seed}
        for family_id, seed in court.expected_unit_order()
    ]
    actual_order = [{"family_id": row["family_id"], "world_seed": row["world_seed"]} for row in evaluations]
    target_plan_complete = all(
        [case["target_spec"] for case in evaluation["case_rows"]] == protocol["target_plan"]
        and [case["case_index"] for case in evaluation["case_rows"]]
        == list(range(len(protocol["target_plan"])))
        for evaluation in evaluations
    )
    mechanism_checks = {
        "champion_bundle_replay_passed": replay_status["passed"],
        "protocol_complete": actual_order == expected_order,
        "target_plan_complete": target_plan_complete,
        "family_protocol_complete": all(summary["protocol_complete"] for summary in family_summaries),
        "champion_coverage_in_band_all_families": all(summary["champion_coverage_in_band"] for summary in family_summaries),
        "champion_abstentions_zero": all(summary["champion_abstentions_standard"] == 0 for summary in family_summaries),
        "baseline_abstentions_zero": all(summary["baseline_abstentions_standard"] == 0 for summary in family_summaries),
        "scores_finite": all(summary["all_scores_finite"] for summary in family_summaries),
        "history_rows_match_units": len(court.history()) == len(evaluations),
        "history_chain_verified": court.verify_chain(),
    }
    receipt = {
        "spec": W_TRANSFER_RECEIPT_SPEC,
        "protocol_hash": protocol["protocol_hash"],
        "champion_bundle_sha256": champion_bundle_sha256,
        "champion_config_hash": champion_config_hash,
        "baseline_release": protocol["baseline_release"],
        "alpha_total_micro": protocol["alpha_total_micro"],
        "stream_count": protocol["stream_count"],
        "log_threshold_micro": protocol["log_threshold_micro"],
        "family_summaries": family_summaries,
        "history_row_count": len(court.history()),
        "history_head": court.chain.head,
        "standing": standing,
        "headline_stream_ids": protocol["headline_stream_ids"],
        "headline_claim_crossed": headline_crossed,
        "headline_claim_status": headline_status,
        "mechanism_checks": mechanism_checks,
        "external_action": False,
    }
    receipt["receipt_id"] = "wtr-" + sha256_hex(canonical_bytes({
        key: value for key, value in receipt.items() if key != "receipt_id"
    }))[:12]
    return receipt


def build_bundle(
    *,
    champion_bundle_path: Path,
    champion_bundle_sha256: str,
    champion_config: dict[str, Any],
    protocol: dict[str, Any],
    evaluations: list[dict[str, Any]],
    court: WTransferCourt,
    replay_status: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    return {
        "spec": W_TRANSFER_BUNDLE_SPEC,
        "champion_bundle_path": str(champion_bundle_path),
        "champion_bundle_sha256": champion_bundle_sha256,
        "champion_config": champion_config,
        "champion_config_hash": protocol["champion_config_hash"],
        "baseline_release": protocol["baseline_release"],
        "protocol": protocol,
        "replay_status": replay_status,
        "evaluations": evaluations,
        "chains": {
            "transfer": {"rows": court.chain.rows, "anchor": court.chain.anchor()},
        },
        "signer_registry": court.signer_registry,
        "receipt_id": receipt["receipt_id"],
    }
