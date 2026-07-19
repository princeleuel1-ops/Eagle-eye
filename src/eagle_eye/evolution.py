"""Champion-challenger evolution controller v4 (post V3 adversarial audit).

Changes vs v2/v3:
  - the promotion gate chain is a PURE module-level function
    (`apply_promotion_gates`) shared verbatim by the live controller and the
    independent full-decision replay, so recorded decision states and reasons
    are bit-for-bit recomputable from the replay bundle
  - candidate generation is a PURE module-level function
    (`generate_candidates`) for the same reason
  - lineage rows bind BOTH sides of the development pre-screen
    (dev_nll_challenger_micro AND dev_nll_champion_micro), the consumed
    evaluator charge row (even when the look FAILED), and the single imported
    evaluator version constant (no more 2.0/2.1 mismatch)
  - the controller still owns no holdout rows, labels, or secrets; every
    sealed access flows through SealedEvaluator's charge-before-execution
    ledger
"""

from __future__ import annotations

import json
from typing import Any

from .governor import govern
from .predictors import predict_seq_prefix, predict_set_mt
from .prediction_court import (
    COVERAGE_BAND,
    PERMUTATION_TOLERANCE,
    build_development_suite,
    evaluate_candidate_on_suite,
    leakage_attack_battery,
)
from .prior_registry import canonical_bytes, sha256_hex
from .sealed_evaluator import EVALUATOR_VERSION, MIN_PAIRED_N, EvaluatorError, SealedEvaluator
from .signed_chain import SignedChain
from .signing import generate_demo_keypair
from .stats import DeterministicRng, stable_seed

EVOLUTION_SPEC = "eagle-eye-sealed-evolution/4.0"
COURT_RELEASE = "eagle-eye-prediction-court/1.0"
DEVELOPMENT_SEED = 11

MUTATION_WHITELIST: dict[str, dict[str, Any]] = {
    "selector.k_max": {"type": "int", "grid": [8, 10, 12], "default": 10},
    "selector.min_score_milli": {"type": "int", "grid": [3500, 4000, 4500, 5000, 6000], "default": 4000},
    "governor.widen_weak_milli": {"type": "int", "grid": [1150, 1350, 1600], "default": 1350},
    "governor.widen_shift_milli": {"type": "int", "grid": [1250, 1500, 1800], "default": 1500},
    "governor.shift_suspect_milli": {"type": "int", "grid": [700, 800, 900, 990], "default": 800},
    "base.candidate": {"type": "enum", "grid": ["set_mt", "seq_prefix"], "default": "set_mt"},
    "seq.decay_milli": {"type": "int", "grid": [600, 800, 950], "default": 800},
}
CHALLENGER_BUDGET_PER_CYCLE = 3
MIN_SCORED_CASES = 30
PROMOTION_STATES = (
    "PROMOTED", "REJECTED", "ABSTAINED_INSUFFICIENT_EVIDENCE",
    "BLOCKED_TRUST_REGRESSION", "BLOCKED_CALIBRATION_REGRESSION",
    "BLOCKED_SHIFT", "BLOCKED_CONTAMINATION",
)


def default_config() -> dict[str, Any]:
    return {name: spec["default"] for name, spec in MUTATION_WHITELIST.items()}


def validate_mutation(diff: dict[str, Any]) -> None:
    for key, value in diff.items():
        spec = MUTATION_WHITELIST.get(key)
        if spec is None:
            raise ValueError(f"mutation outside whitelist: {key}")
        if value not in spec["grid"]:
            raise ValueError(f"mutation value {value!r} outside allowed grid for {key}")


def predictor_from_config(config: dict[str, Any]):
    def fn(compiled: dict[str, Any]) -> dict[str, Any]:
        if config["base.candidate"] == "seq_prefix":
            raw = predict_seq_prefix(compiled, decay=config["seq.decay_milli"] / 1000.0)
        else:
            raw = predict_set_mt(compiled)
        return govern(raw, compiled,
                      widen_weak=config["governor.widen_weak_milli"] / 1000.0,
                      widen_shift=config["governor.widen_shift_milli"] / 1000.0,
                      shift_suspect=config["governor.shift_suspect_milli"] / 1000.0)
    return fn


def snapshot_identity(*, registry_manifest_sha256: str, evaluator_seed_commitment: str,
                      run_seed: int, run_context: dict[str, Any]) -> str:
    """Pure snapshot identity — recomputable by the independent replay."""
    return "snap-" + sha256_hex(canonical_bytes({
        "registry_manifest_sha256": registry_manifest_sha256,
        "development_partition": {"builder": "development", "seed": DEVELOPMENT_SEED},
        "evaluator_seed_commitment": evaluator_seed_commitment,
        "evaluator_version": EVALUATOR_VERSION,
        "court_release": COURT_RELEASE,
        "run_seed": run_seed,
        "run_context": run_context,
    }))[:16]


def generate_candidates(*, run_seed: int, champion_id: str, champion_config: dict[str, Any],
                        snapshot_id: str, registry_manifest_sha256: str,
                        evaluator_seed_commitment: str, cycle: int,
                        budget: int = CHALLENGER_BUDGET_PER_CYCLE) -> list[dict[str, Any]]:
    """Pure deterministic bounded candidate generation — shared verbatim by
    the live controller and the independent full-decision replay.

    The generation seed derives from the STABLE decision core (run seed,
    champion, registry manifest, evaluator commitment, court release, cycle)
    — deliberately NOT from snapshot_id, which also binds run_context: a
    documentation-only code edit must not reshuffle which mutations get
    explored. Contamination defense is unaffected — candidate ids still embed
    the FULL snapshot_id, so stale-snapshot candidates remain blocked."""
    rng = DeterministicRng(stable_seed("evolve", run_seed, champion_id,
                                       registry_manifest_sha256, evaluator_seed_commitment,
                                       COURT_RELEASE, cycle, budget))
    names = sorted(MUTATION_WHITELIST)
    out, seen, attempts = [], set(), 0
    while len(out) < budget and attempts < budget * 12:
        attempts += 1
        name = names[rng.choice_index(len(names))]
        spec = MUTATION_WHITELIST[name]
        value = spec["grid"][rng.choice_index(len(spec["grid"]))]
        if value == champion_config[name]:
            continue
        if name.startswith("seq.") and champion_config["base.candidate"] == "set_mt":
            continue
        diff = {name: value}
        key = json.dumps(diff, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        validate_mutation(diff)
        out.append({
            # snapshot-bound id: identical diffs in different registries differ
            "candidate_id": f"cand-{sha256_hex(canonical_bytes({'p': champion_id, 'd': diff, 'c': cycle, 'snap': snapshot_id}))[:12]}",
            "parent_champion_id": champion_id,
            "mutation_type": "typed_parameter", "diff": diff,
            "config": {**champion_config, **diff},
            "hypothesis": f"adjusting {name} to {value} improves sealed paired log score without regression",
            "expected_benefit": "sharper or better-supported posterior",
            "known_risk": "calibration or OoD regression; support misuse",
            "generation_seed": run_seed,
            "dataset_snapshot_id": snapshot_id,
            "court_release_id": COURT_RELEASE,
            "candidate_budget_position": len(out) + 1,
            "created_at_cycle": cycle,
        })
    return out


def apply_promotion_gates(body: dict[str, Any], *, min_scored: int = MIN_SCORED_CASES) -> tuple[str, list[str]]:
    """Pure promotion gate chain over a SUCCEEDED evaluator response body.

    Returns (state, reasons). Shared verbatim by the live controller and the
    independent full-decision replay, so a recorded lineage decision is
    bit-for-bit recomputable: trust, support, calibration, shift, coverage,
    scored-count, and significance gates all live here. Signed evaluator rows
    are float-free (micro units); every comparison is in micro."""
    stats = body["statistics"]
    agg = body["challenger_aggregates"]
    champ_agg = body["champion_aggregates"]
    hold_m = agg["metrics"]
    if agg["scored_count"] < min_scored:
        return ("ABSTAINED_INSUFFICIENT_EVIDENCE",
                [f"scored_count {agg['scored_count']} < {min_scored}"])
    reasons: list[str] = []
    if agg["abstentions_standard"] > 0:
        reasons.append("trust:standard_abstention")
    if agg["probe_count"] and agg["abstentions_probe"] != agg["probe_count"]:
        reasons.append("trust:out_of_support_not_refused")
    if hold_m["permutation_spread_max"] > int(PERMUTATION_TOLERANCE * 1e6):
        reasons.append("trust:permutation_instability")
    if reasons:
        return ("BLOCKED_TRUST_REGRESSION", reasons)
    cov = hold_m["coverage80"] or 0
    champ_cov = champ_agg["metrics"]["coverage80"] or 0
    band_lo, band_hi = int(COVERAGE_BAND[0] * 1e6), int(COVERAGE_BAND[1] * 1e6)
    if not (band_lo <= cov <= band_hi):
        return ("BLOCKED_CALIBRATION_REGRESSION", [f"coverage_micro {cov} outside band"])
    if abs(cov - 800000) > abs(champ_cov - 800000) + 20000:
        return ("BLOCKED_CALIBRATION_REGRESSION",
                ["coverage distance to nominal worsened beyond 0.02"])
    if (hold_m["nll_temporal_ood"] is not None
            and champ_agg["metrics"]["nll_temporal_ood"] is not None
            and hold_m["nll_temporal_ood"] > champ_agg["metrics"]["nll_temporal_ood"]):
        return ("BLOCKED_SHIFT", ["temporal_ood_regression_vs_champion"])
    if stats["significant_improvement"]:
        return ("PROMOTED", [])
    return ("REJECTED", ["sealed_paired_test_not_significant",
                         f"ci_upper_micro={stats['ci_upper_micro']}"])


class EvolutionController:
    def __init__(self, registry: dict[str, Any], evaluator: SealedEvaluator, *,
                 run_seed: int = 20260713, run_context: dict[str, Any] | None = None,
                 tenant_id: str = "tenant-demo", run_id: str = "run-evolution",
                 feedback_state: dict[str, Any] | None = None):
        self.evaluator = evaluator
        # V7 (additive, default None => bit-identical legacy behavior): a
        # validated feedback-harness state routes generation through
        # feedback.weighted_generate_candidates; its hash is bound into every
        # candidate id, so the replay bundle remains fully recomputable.
        self.feedback_state = feedback_state
        if feedback_state is not None:
            from .feedback import validate_state
            validate_state(feedback_state)
        self.run_seed = run_seed
        self.run_context = run_context or {"code_revision": "unbound", "dependency_lock_sha256": "unbound"}
        self.development = build_development_suite(DEVELOPMENT_SEED)
        self.leakage = leakage_attack_battery(registry, self.development)
        private_key, public_key = generate_demo_keypair()
        self.lineage_chain = SignedChain(tenant_id=tenant_id, run_id=run_id,
                                         chain_id="evolution-lineage",
                                         private_key=private_key, public_key=public_key)
        self.candidates_proposed = 0
        self.candidates_evaluated = 0
        self.candidates_rejected_pre_evaluation = 0
        self.champion = {"champion_id": "champ-genesis-governed-set-mt",
                          "config": default_config(), "receipt_hash": "0" * 64}
        self.registry: dict[str, Any] = {}
        self.snapshot_id = ""
        self.update_registry(registry)

    # -- snapshot identity (recomputed on EVERY mutation) -----------------------
    def update_registry(self, registry: dict[str, Any]) -> None:
        self.registry = registry
        self.snapshot_id = snapshot_identity(
            registry_manifest_sha256=registry["manifest_sha256"],
            evaluator_seed_commitment=self.evaluator.seed_commitment,
            run_seed=self.run_seed, run_context=self.run_context)
        self._champ_dev_cache = None

    # -- deterministic bounded generation --------------------------------------
    def propose_candidates(self, cycle: int, *, budget: int = CHALLENGER_BUDGET_PER_CYCLE) -> list[dict[str, Any]]:
        if self.feedback_state is not None:
            from .feedback import weighted_generate_candidates
            out = weighted_generate_candidates(
                run_seed=self.run_seed,
                champion_id=self.champion["champion_id"],
                champion_config=self.champion["config"],
                snapshot_id=self.snapshot_id,
                registry_manifest_sha256=self.registry["manifest_sha256"],
                evaluator_seed_commitment=self.evaluator.seed_commitment,
                cycle=cycle, feedback_state=self.feedback_state, budget=budget)
        else:
            out = generate_candidates(run_seed=self.run_seed,
                                      champion_id=self.champion["champion_id"],
                                      champion_config=self.champion["config"],
                                      snapshot_id=self.snapshot_id,
                                      registry_manifest_sha256=self.registry["manifest_sha256"],
                                      evaluator_seed_commitment=self.evaluator.seed_commitment,
                                      cycle=cycle, budget=budget)
        self.candidates_proposed += len(out)
        return out

    def _dev_eval(self, config: dict[str, Any]) -> dict[str, Any]:
        return evaluate_candidate_on_suite(
            "dev", self.development, self.registry, fn=predictor_from_config(config),
            k_max_override=config["selector.k_max"],
            min_score_override=config["selector.min_score_milli"] / 1000.0)

    def _champion_dev_nll(self) -> float:
        if self._champ_dev_cache is None:
            self._champ_dev_cache = self._dev_eval(self.champion["config"])["metrics"]["nll"]
        return self._champ_dev_cache

    # -- decision --------------------------------------------------------------
    def decide(self, candidate: dict[str, Any]) -> dict[str, Any]:
        if candidate["dataset_snapshot_id"] != self.snapshot_id:
            return self._record(candidate, "BLOCKED_CONTAMINATION", None, None, None,
                                ["stale_snapshot: candidate bound to a superseded registry state"])
        if not self.leakage["all_defended"]:
            return self._record(candidate, "BLOCKED_TRUST_REGRESSION", None, None, None,
                                ["leakage_not_defended"])
        dev = self._dev_eval(candidate["config"])
        self.candidates_evaluated += 1
        dev_nll = dev["metrics"]["nll"]
        champ_dev_nll = self._champion_dev_nll()
        if dev_nll is None or dev_nll >= champ_dev_nll:
            self.candidates_rejected_pre_evaluation += 1
            return self._record(candidate, "REJECTED", dev_nll, champ_dev_nll, None,
                                ["development_no_improvement (no sealed look spent)"])
        try:
            response = self.evaluator.compare(
                champion_config=self.champion["config"],
                challenger_config=candidate["config"],
                candidate_id=candidate["candidate_id"], snapshot_id=self.snapshot_id,
                registry=self.registry, fn_factory=predictor_from_config,
                nonce=f"{candidate['candidate_id']}:{self.snapshot_id}")
        except EvaluatorError as exc:
            return self._record(candidate, "ABSTAINED_INSUFFICIENT_EVIDENCE",
                                dev_nll, champ_dev_nll, None,
                                [f"evaluator_refused: {exc}"],
                                charge_hash=exc.charge_row_hash,
                                terminal_status=exc.terminal_status)
        except Exception as exc:
            return self._record(candidate, "ABSTAINED_INSUFFICIENT_EVIDENCE",
                                dev_nll, champ_dev_nll, None,
                                [f"evaluator_refused: {exc}"])
        state, reasons = apply_promotion_gates(response["body"])
        return self._record(candidate, state, dev_nll, champ_dev_nll, response, reasons)

    # -- signed lineage ----------------------------------------------------------
    def _record(self, candidate: dict[str, Any], state: str,
                dev_nll: float | None, champ_dev_nll: float | None,
                response: dict[str, Any] | None, reasons: list[str],
                *, charge_hash: str | None = None,
                terminal_status: str | None = None) -> dict[str, Any]:
        assert state in PROMOTION_STATES
        micro = lambda v: None if v is None else int(round(v * 1e6))
        body = {
            "spec": EVOLUTION_SPEC, "state": state, "reasons": reasons,
            "candidate": {k: v for k, v in candidate.items() if k != "config"},
            "candidate_config": candidate["config"],
            "parent_champion_receipt": self.champion["receipt_hash"],
            "dataset_snapshot_id": self.snapshot_id,
            "registry_manifest_sha256": self.registry["manifest_sha256"],
            "court_release_id": COURT_RELEASE,
            "evaluator_version": EVALUATOR_VERSION,
            "policy_release": "policy-v1@1a47ce736ef27e60",
            "run_context": self.run_context,
            "dev_nll_challenger_micro": micro(dev_nll),
            "dev_nll_champion_micro": micro(champ_dev_nll),
            "evaluator_response_hash": None if response is None else response["row_hash"],
            "evaluator_charge_hash": (response["body"]["charge_row_hash"] if response is not None
                                      else charge_hash),
            "evaluator_terminal_status": (response["body"]["terminal_status"] if response is not None
                                          else terminal_status),
            "evaluator_look_index": None if response is None else response["body"]["look_index"],
            "statistics": None if response is None else response["body"]["statistics"],
        }
        row = self.lineage_chain.append(body)
        if state == "PROMOTED":
            self.champion = {"champion_id": candidate["candidate_id"],
                              "config": candidate["config"], "receipt_hash": row["row_hash"]}
            self._champ_dev_cache = None
        return {**body, "lineage_hash": row["row_hash"], "row": row}

    def budget_report(self) -> dict[str, Any]:
        looks = self.evaluator.looks_spent()  # derived from the signed ledger
        results = [r["body"] for r in self.evaluator.ledger.rows
                   if r["body"]["kind"] == "promotion_look_result"]
        by_status = {status: sum(1 for b in results if b["terminal_status"] == status)
                     for status in ("SUCCEEDED", "FAILED", "TIMED_OUT", "REJECTED")}
        return {
            "candidates_proposed": self.candidates_proposed,
            "candidates_evaluated": self.candidates_evaluated,
            "candidates_rejected_before_holdout": self.candidates_rejected_pre_evaluation,
            "holdout_looks": looks,
            "holdout_look_terminal_statuses": by_status,
            "final_audit_holdout_looks": sum(
                1 for r in self.evaluator.ledger.rows if r["body"]["kind"] == "final_audit_charge"),
            "alpha_total_micro": int(self.evaluator.alpha_total * 1e6),
            "alpha_spent_micro": int(round(self.evaluator.alpha_spent() * 1e6)),
            "alpha_remaining_micro": int(round((self.evaluator.alpha_total - self.evaluator.alpha_spent()) * 1e6)),
            "alpha_procedure": "Bonferroni allocation alpha_total/max_looks per charged look; champion charged inside each compare; FAILED/TIMED_OUT/REJECTED looks consume alpha too",
            "effective_hypothesis_family": "single-parameter whitelist mutations of the sitting champion",
        }
