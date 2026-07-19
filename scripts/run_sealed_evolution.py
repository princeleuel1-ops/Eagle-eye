"""Sealed Evolution Flywheel benchmark v4 (post V3 adversarial audit).

Evidence-class discipline: everything below is SYNTHETICALLY VERIFIED
(authorized synthetic truth channel); chain/signature/replay properties are
MECHANICALLY VERIFIED; no live/category claims are made.

V4 trust-boundary changes:
  - evaluator secret comes from the CSPRNG operator boundary
    (`provision_evaluator_secret`), NEVER derived from public seeds or code
    revisions; the commitment binds secret + provenance
  - evaluator lifecycle: looks happen in EVALUATING; `finalize()` closes the
    phase irreversibly BEFORE chains are anchored and the secret is revealed
  - every holdout access is charged before execution with a terminal status
  - the replay bundle carries every binding needed for FULL decision replay:
    suite commitments, per-growth registry manifests, committed prediction
    blocks, dev-prescreen values, controller seed, cycle cutoffs, policy
    registry, evaluator configuration, and the dependency lock digest
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from eagle_eye.conformal import calibrate, conformal_interval, evaluate_coverage
from eagle_eye.evolution import (
    DEVELOPMENT_SEED,
    EvolutionController,
    MUTATION_WHITELIST,
    predictor_from_config,
)
from eagle_eye.flywheel import calibration_pairs, commit_cycle_prediction
from eagle_eye.outcome_resolution import PredictionLedger
from eagle_eye.posterior_engine import commitment_hash
from eagle_eye.predictors import LogScaleDist
from eagle_eye.prior_registry import build_registry, canonical_bytes, sha256_hex
from eagle_eye.prior_selector import compile_prior_context, select_prior_tasks
from eagle_eye.provenance import dependency_lock_digest, verify_dependency_lock
from eagle_eye.regimes import generate_target_case, generate_world
from eagle_eye.sealed_evaluator import (
    EVALUATOR_VERSION,
    SealedEvaluator,
    provision_evaluator_secret,
)
from eagle_eye.signed_chain import verify_chain
from eagle_eye.signing import generate_demo_keypair, key_id
from eagle_eye.stats import DeterministicRng, stable_seed
from eagle_eye.voi import sign_loss_function, value_of_information

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "evolution" / "latest"
BENCHMARK_SPEC = "sealed-evolution-benchmark/4.0"
BUNDLE_SPEC = "sealed-evolution-replay-bundle/4.0"
STATE_SCHEMA_VERSION = "evolution-state/4.0"
POLICY_RELEASE_HASH = "1a47ce736ef27e60fa3aea3d2abcb96aa4e1eb8b22f492c335502d0dc9f75f1f"
CYCLE_CUTOFFS = ["2025-05-01", "2025-05-18", "2025-06-04", "2025-08-10", "2025-09-01", "2025-09-22"]
FOLLOW_PROB = 0.7
CONTROLLER_RUN_SEED = 20260713
REGISTRY_BASE = {"world_seed": 20260712, "tasks_per_regime": 16}
LIVE_TASKS_PER_REGIME = 4
CALIBRATION_SUITE_SEED = 31
DEFAULT_SUITE_SCALE = 3


def run_context() -> dict:
    src_rows = []
    for base in ("src", "scripts", "verifier"):
        for r, dirs, files in os.walk(ROOT / base):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in sorted(files):
                p = Path(r) / f
                src_rows.append({"p": str(p.relative_to(ROOT)), "h": sha256_hex(p.read_bytes())})
    src_rows.sort(key=lambda x: x["p"])
    return {"code_revision": sha256_hex(canonical_bytes(src_rows))[:16],
            # fail-closed: raises if the lock is missing (never NOT_AVAILABLE)
            "dependency_lock_sha256": dependency_lock_digest(ROOT),
            "base_commit": "46f6e2f", "evaluator_version": EVALUATOR_VERSION,
            "python": sys.version.split()[0]}


def main(live_seed: int = 550, evaluator_secret: str | None = None, out_dir: Path | None = None,
         cutoffs: list[str] | None = None, suite_scale: int = DEFAULT_SUITE_SCALE,
         feedback_state: dict | None = None):
    out = out_dir or OUT
    out.mkdir(parents=True, exist_ok=True)
    cutoffs = cutoffs or CYCLE_CUTOFFS
    lock_report = verify_dependency_lock(ROOT)
    if not lock_report["all_match"]:
        print("DEPENDENCY_LOCK_MISMATCH=" + json.dumps(
            [r for r in lock_report["packages"] if not r["match"]]))
        return 1
    ctx = run_context()
    base_world = generate_world(REGISTRY_BASE["world_seed"],
                                tasks_per_regime=REGISTRY_BASE["tasks_per_regime"])
    registry_tasks = list(base_world["tasks"])
    registry = build_registry(registry_tasks)
    base_registry_manifest = registry["manifest_sha256"]
    live_world = generate_world(live_seed, tasks_per_regime=LIVE_TASKS_PER_REGIME)
    # V4 blocker 1: cryptographically random secret through the explicit
    # operator boundary. A caller-supplied secret is a TEST fixture and is
    # labeled as such in the commitment.
    if evaluator_secret is None:
        provisioned = provision_evaluator_secret()
        secret, provenance = provisioned["secret"], provisioned["provenance"]
    else:
        secret, provenance = evaluator_secret, "test_fixture"
    evaluator = SealedEvaluator(tenant_id="tenant-demo", run_id=f"run-evo-{live_seed}",
                                secret=secret, secret_provenance=provenance,
                                suite_scale=suite_scale)
    controller = EvolutionController(registry, evaluator, run_seed=CONTROLLER_RUN_SEED,
                                     run_context=ctx, run_id=f"run-evo-{live_seed}",
                                     feedback_state=feedback_state)
    signer_keys = generate_demo_keypair()
    policy_registry = {"policy:follow-recommendation-70/1": {
        "follow_prob": FOLLOW_PROB, "authenticated": True,
        "record_hash": sha256_hex(canonical_bytes({"policy": "follow-recommendation", "p": FOLLOW_PROB}))}}
    ledger = PredictionLedger("tenant-demo", policy_registry=policy_registry,
                              signer_keys=signer_keys, run_id=f"run-evo-{live_seed}")
    # calibration partition (candidate-domain; disjoint from evaluator suites)
    from eagle_eye.evolution import build_development_suite
    calibration_suite = build_development_suite(CALIBRATION_SUITE_SEED)
    policy_rng = DeterministicRng(stable_seed("acting-policy", live_seed))
    loss = sign_loss_function({"spec": "loss/1.0", "exposure_rate_per_day_usd": 9000.0,
        "intervention_cost_usd": {"wait_incumbent": 0.0, "expedite_shipment": 45000.0,
                                   "activate_alternate": 30000.0, "split_order": 20000.0}})
    cal_receipt = None
    cal_state = None
    grown_tasks = []
    cycles = []
    events = {"promotions": 0, "rejections": 0, "abstentions": 0, "trust_blocks": 0,
              "calibration_blocks": 0, "shift_blocks": 0, "contamination_blocks": 0,
              "coverage_failures": 0, "shift_suspensions": 0,
              "off_policy_not_identifiable": 0, "receipt_verification_failures": 0,
              "registry_growth": 0}

    for index, cutoff in enumerate(cutoffs, start=1):
        cycle = {"cycle": index, "cutoff": cutoff}
        # E: recalibrate when champion OR registry (snapshot) changed
        state_now = (controller.champion["champion_id"], controller.snapshot_id)
        if cal_state != state_now:
            pairs = calibration_pairs(registry, controller.champion["config"], calibration_suite)
            cal_half = [(y, d) for i, (y, d, _) in enumerate(pairs) if i % 2 == 0]
            eval_half = [(y, d, g) for i, (y, d, g) in enumerate(pairs) if i % 2 == 1]
            cal_receipt = calibrate(cal_half, target_coverage=0.8)
            coverage_eval = evaluate_coverage(eval_half, cal_receipt)  # DISJOINT from calibration
            cal_state = state_now
            cycle["conformal_recalibrated"] = True
            cycle["conformal_calibration"] = {
                "receipt_sha256": cal_receipt["receipt_sha256"],
                "n_calibration": cal_receipt["calibration_sample_size"],
                "n_evaluation_disjoint": coverage_eval["n"],
                "empirical_coverage_micro_heldout": coverage_eval["empirical_coverage_micro"]}
        case = generate_target_case(live_world, case_index=9000 + index, tenant_id="tenant-demo",
                                    disruption_class="port_congestion", cutoff=cutoff, n_target_obs=2)
        block = commit_cycle_prediction(registry, case["target"], controller.champion["config"],
                                        controller.champion["champion_id"])
        committed = ledger.commit_prediction(block, champion_id=controller.champion["champion_id"],
                                             policy_release_hash=POLICY_RELEASE_HASH,
                                             resource_scope="scope:live-disruptions")
        payload = block["interventions"]["wait_incumbent"]["delay"]
        dist = LogScaleDist(payload["loc"], payload["scale"], payload["df"])
        interval = conformal_interval(dist, cal_receipt, shift_score=block["governed"]["shift_score"])
        if interval["state"] == "GUARANTEE_SUSPENDED_SHIFT":
            events["shift_suspensions"] += 1
        recommended = block["recommendation"]["recommended_intervention"]
        follow = policy_rng.uniform() < FOLLOW_PROB
        taken = recommended if follow else "wait_incumbent"
        propensity = FOLLOW_PROB if follow else round(1.0 - FOLLOW_PROB, 6)
        truth_outcome = case["truth"]["outcomes"][taken]
        observed_at = (date.fromisoformat(cutoff)
                       + timedelta(days=int(truth_outcome["final_delay_days"]) + 4)).isoformat()
        source_payload = {"channel": "authorized_synthetic_truth", "case_id": case["target"]["case_id"],
                          "taken": taken, "log_final_delay": round(truth_outcome["log_final_delay"], 6)}
        resolution = ledger.resolve({
            "prediction_id": committed["prediction_id"],
            "prediction_distribution_hash": committed["prediction_distribution_hash"],
            "policy_release_hash": POLICY_RELEASE_HASH,
            "tenant_id": "tenant-demo", "resource_scope": "scope:live-disruptions",
            "outcome_observed_at": observed_at,
            "outcome_value": round(truth_outcome["log_final_delay"], 6),
            "outcome_source": "authorized_synthetic_truth_channel",
            "outcome_source_payload": source_payload,
            "observed": {"final_delay_days": round(truth_outcome["final_delay_days"], 3),
                          "stockout": bool(truth_outcome["stockout"]),
                          "recovery_days": round(truth_outcome["recovery_days"], 3),
                          "exposure_usd": round(truth_outcome["exposure_usd"], 2),
                          "intervention_result": None},
            "entity_refs": {**case["target"]["entity_refs"]},
            "confounders": {"schema_version": "confounders/1.0",
                             "vector": {"lane": case["target"]["entity_refs"]["lane"],
                                        "n_target_obs": len(case["target"]["observations"]),
                                        "disruption_class": "port_congestion"}},
            "intervention_taken": taken, "acting_policy": "policy:follow-recommendation-70/1",
            "recommendation_propensity": propensity,
            "authorization_receipt": "approval-shadow-fixture",
        })
        if resolution["off_policy"]["state"] in ("NOT_IDENTIFIABLE",):
            events["off_policy_not_identifiable"] += 1
        if resolution["score"] and not resolution["score"]["covered80"]:
            events["coverage_failures"] += 1
        if resolution["eligibility_for_registry"]:
            new_task = ledger.grow_registry_task(resolution)
            registry_tasks.append(new_task)
            registry = build_registry(registry_tasks, release=f"prior-registry/2+growth{index}")
            controller.update_registry(registry)  # snapshot_id recomputed (B3)
            grown_tasks.append({"cycle": index, "release": f"prior-registry/2+growth{index}",
                                "task": new_task,
                                "resolution_hash": resolution["current_audit_hash"],
                                "prediction_id": resolution["prediction_id"],
                                "registry_manifest_after": registry["manifest_sha256"],
                                "snapshot_id_after": controller.snapshot_id})
            events["registry_growth"] += 1
        decisions = []
        for candidate in controller.propose_candidates(index):
            decision = controller.decide(candidate)
            decisions.append({"candidate_id": candidate["candidate_id"], "diff": candidate["diff"],
                              "state": decision["state"], "reasons": decision["reasons"],
                              "lineage_hash": decision["lineage_hash"]})
            events[{"PROMOTED": "promotions", "REJECTED": "rejections",
                    "ABSTAINED_INSUFFICIENT_EVIDENCE": "abstentions",
                    "BLOCKED_TRUST_REGRESSION": "trust_blocks",
                    "BLOCKED_CALIBRATION_REGRESSION": "calibration_blocks",
                    "BLOCKED_SHIFT": "shift_blocks",
                    "BLOCKED_CONTAMINATION": "contamination_blocks"}[decision["state"]]] += 1
        diag = block.get("diagnostics", {})
        sigma2 = diag.get("sigma2", 0.09)
        post_var = max(1e-6, dist.scale ** 2 - sigma2)
        actions = {name: {"delta": 0.0 if name == "wait_incumbent" else
                          (math.log(block["interventions"][name]["delay"]["quantiles_days"]["p50"])
                           - math.log(block["interventions"]["wait_incumbent"]["delay"]["quantiles_days"]["p50"])),
                   "var": 0.01} for name in block["interventions"]}
        voi = value_of_information(posterior_mean=dist.loc, posterior_var=post_var, sigma2=sigma2,
                                   actions=actions, loss=loss, signal_sd=math.sqrt(sigma2),
                                   signal_cost_usd=500.0, waiting_cost_usd=4000.0,
                                   posterior_is_normal=dist.df is None)
        signer_registry = {"trusted_signers": [
            {"key_id": ledger.signed.signer_key_id, "public_key_pem": ledger.signed.public_key.decode()},
            {"key_id": controller.lineage_chain.signer_key_id,
             "public_key_pem": controller.lineage_chain.public_key.decode()},
            {"key_id": evaluator.ledger.signer_key_id,
             "public_key_pem": evaluator.ledger.public_key.decode()}]}
        replay = {
            "ledger_hash_chain": ledger.verify_chain(),
            "outcome_signed_chain": verify_chain(ledger.signed.rows, ledger.signed.anchor(),
                                                 signer_registry, expected_tenant="tenant-demo")["verified"],
            "lineage_signed_chain": verify_chain(controller.lineage_chain.rows,
                                                 controller.lineage_chain.anchor(),
                                                 signer_registry, expected_tenant="tenant-demo")["verified"],
            "evaluator_ledger_chain": verify_chain(evaluator.ledger.rows, evaluator.ledger.anchor(),
                                                   signer_registry, expected_tenant="tenant-demo")["verified"],
            "prediction_commitment": commitment_hash({
                "candidate": block["candidate"], "model_release": block["model_release"],
                "prior_manifest_sha256": block["prior_manifest_sha256"],
                "as_of_cutoff": block["as_of_cutoff"], "abstained": block["abstained"],
                "interventions": block["interventions"]}) == committed["prediction_distribution_hash"],
            "registry_intact": registry["manifest_sha256"] == build_registry(
                registry_tasks, release=registry["release"])["manifest_sha256"],
        }
        if not all(replay.values()):
            events["receipt_verification_failures"] += 1
        cycle.update({
            "champion": controller.champion["champion_id"],
            "snapshot_id": controller.snapshot_id,
            "prediction_id": committed["prediction_id"],
            "distribution_commitment": committed["prediction_distribution_hash"],
            "conformal_state": interval["state"],
            "resolution_hash": resolution["current_audit_hash"],
            "resolution_score": resolution["score"],
            "intervention_recommended": recommended, "intervention_taken": taken,
            "off_policy_state": resolution["off_policy"]["state"],
            "registry_eligible": resolution["eligibility_for_registry"],
            "registry_release": registry["registry_release_id"],
            "challenger_decisions": decisions,
            "voi": {"recommended_wait_or_act": voi["recommended_wait_or_act"],
                     "evoi_usd": voi["expected_value_of_information_usd"],
                     "label": voi["exact_or_approximate"], "receipt_hash": voi["receipt_hash"]},
            "verification_replay": replay,
        })
        cycles.append(cycle)

    audit_row = evaluator.final_audit(config=controller.champion["config"],
                                      champion_id=controller.champion["champion_id"],
                                      registry=registry, fn_factory=predictor_from_config,
                                      nonce=f"final-audit:{controller.snapshot_id}")
    # V4 lifecycle: irreversibly close the evaluation phase BEFORE anchoring
    # chains and revealing the secret. Reveal before this point hard-fails.
    evaluator.finalize()
    signer_registry = {"trusted_signers": [
        {"key_id": ledger.signed.signer_key_id, "public_key_pem": ledger.signed.public_key.decode()},
        {"key_id": controller.lineage_chain.signer_key_id,
         "public_key_pem": controller.lineage_chain.public_key.decode()},
        {"key_id": evaluator.ledger.signer_key_id,
         "public_key_pem": evaluator.ledger.public_key.decode()}]}
    budget = controller.budget_report()
    results = {
        "spec": BENCHMARK_SPEC,
        "evidence_class": "SYNTHETICALLY VERIFIED (chains/signatures/replay: MECHANICALLY VERIFIED)",
        "live_world_seed": live_seed,
        "run_context": ctx,
        "evaluator_seed_commitment": evaluator.seed_commitment,
        "evaluator_suite_commitments": evaluator.suite_commitments,
        "evaluator_lifecycle": evaluator.lifecycle,
        "n_attempted": len(cutoffs), "n_completed": len(cycles),
        "events": events,
        "final_champion": controller.champion["champion_id"],
        "final_champion_config": controller.champion["config"],
        "final_audit_holdout": audit_row["body"]["aggregates"],
        "budget": budget,
        "leakage": controller.leakage,
        "cycles": cycles,
        "external_action": False,
    }
    results["benchmark_receipt_id"] = f"sevo4-{sha256_hex(canonical_bytes(results))[:12]}"
    (out / "SEALED_EVOLUTION_BENCHMARK_RESULTS.json").write_text(json.dumps(results, indent=2, sort_keys=True))
    bundle = {
        "spec": BUNDLE_SPEC,
        "run_context": ctx,
        "registry_base": dict(REGISTRY_BASE),
        "base_registry_manifest_sha256": base_registry_manifest,
        "live_world": {"world_seed": live_seed, "tasks_per_regime": LIVE_TASKS_PER_REGIME},
        "cycle_cutoffs": list(cutoffs),
        "controller_run_seed": CONTROLLER_RUN_SEED,
        "development_seed": DEVELOPMENT_SEED,
        "calibration_suite_seed": CALIBRATION_SUITE_SEED,
        "policy_registry": policy_registry,
        "policy_release_hash": POLICY_RELEASE_HASH,
        "follow_prob": FOLLOW_PROB,
        "evaluator_config": {"alpha_total": evaluator.alpha_total, "max_looks": evaluator.max_looks,
                              "suite_scale": suite_scale, "evaluator_version": EVALUATOR_VERSION},
        "evaluator_reveal": evaluator.reveal_for_replay(),
        "suite_scale": suite_scale,
        # V7 (optional): generation ran through the feedback harness; the
        # recorded state makes weighted generation exactly recomputable and
        # its sha256 is bound inside every candidate id of this run.
        **({} if feedback_state is None else {"feedback": {
            "spec": feedback_state["spec"],
            "state": feedback_state,
        }}),
        "grown_tasks": grown_tasks,
        "predictions": {pid: rec["block"] for pid, rec in ledger.predictions.items()},
        "genesis_config": {name: spec["default"] for name, spec in MUTATION_WHITELIST.items()},
        "final_champion": controller.champion["champion_id"],
        "final_champion_config": controller.champion["config"],
        "signer_registry": signer_registry,
        "chains": {
            "outcomes": {"rows": ledger.signed.rows, "anchor": ledger.signed.anchor()},
            "lineage": {"rows": controller.lineage_chain.rows, "anchor": controller.lineage_chain.anchor()},
            "evaluator": {"rows": evaluator.ledger.rows, "anchor": evaluator.ledger.anchor()},
        },
        "resolutions": ledger.resolutions,
        "final_registry_manifest_sha256": registry["manifest_sha256"],
        "informational": {
            "note": "fields under this key are INFORMATIONAL_NOT_VERIFIED in the replay schema",
            "benchmark_receipt_id": results["benchmark_receipt_id"],
        },
    }
    (out / "REPLAY_BUNDLE.json").write_text(json.dumps(bundle, indent=2, sort_keys=True))
    (out / "EVOLUTION_LINEAGE.json").write_text(json.dumps(
        {"rows": controller.lineage_chain.rows, "anchor": controller.lineage_chain.anchor(),
         "signer_registry": signer_registry}, indent=2, sort_keys=True))
    (out / "HOLDOUT_ACCESS_LEDGER.json").write_text(json.dumps(
        {"rows": [{k: v for k, v in r.items() if k != "body"} | {
            "kind": r["body"]["kind"], "look_index": r["body"].get("look_index"),
            "terminal_status": r["body"].get("terminal_status"),
            "candidate_id": r["body"].get("candidate_id")} for r in evaluator.ledger.rows],
         "anchor": evaluator.ledger.anchor(), "budget": budget},
        indent=2, sort_keys=True))
    (out / "OUTCOME_RESOLUTIONS.json").write_text(json.dumps(
        {"resolutions": ledger.resolutions, "head": ledger.head,
         "hash_chain_verified": ledger.verify_chain(),
         "signed_anchor": ledger.signed.anchor()}, indent=2, sort_keys=True))
    (out / "OFF_POLICY_IDENTIFIABILITY_REPORT.json").write_text(json.dumps({
        "spec": "off-policy-identifiability/2.0",
        "policy_registry": policy_registry,
        "per_resolution": [{"prediction_id": r["prediction_id"], "state": r["off_policy"]["state"],
                             "checks": r["off_policy"]["checks"],
                             "usable_for": r["off_policy"]["usable_for"],
                             "sensitivity": r["off_policy"]["sensitivity_to_unobserved_confounding"]}
                            for r in ledger.resolutions],
        "honesty": "propensities recomputed from authenticated policy records; identifiability requires measured overlap, ESS, confounder schema; sensitivity to unobserved confounding NOT_ESTABLISHED",
    }, indent=2, sort_keys=True))
    (out / "OUTCOME_RESOLUTION_RECEIPT_EXAMPLE.json").write_text(
        json.dumps(ledger.resolutions[0], indent=2, sort_keys=True))
    pairs = calibration_pairs(registry, controller.champion["config"], calibration_suite)
    cal_half = [(y, d) for i, (y, d, _) in enumerate(pairs) if i % 2 == 0]
    eval_half = [(y, d, g) for i, (y, d, g) in enumerate(pairs) if i % 2 == 1]
    final_cal = calibrate(cal_half, target_coverage=0.8)
    (out / "CONFORMAL_EVALUATION_RESULTS.json").write_text(json.dumps({
        "calibration_receipt": final_cal,
        "heldout_coverage_disjoint": evaluate_coverage(eval_half, final_cal),
        "states_observed": sorted({c["conformal_state"] for c in cycles}),
        "note": "coverage evaluated ONLY on pairs disjoint from calibration (audit blocker 8)",
    }, indent=2, sort_keys=True))
    (out / "VALUE_OF_INFORMATION_EXAMPLE.json").write_text(json.dumps(
        {**cycles[0]["voi"], "cycle": 1}, indent=2, sort_keys=True))
    rejections_all = (events["rejections"] + events["trust_blocks"]
                      + events["calibration_blocks"] + events["shift_blocks"]
                      + events["contamination_blocks"])

    def _state_entry(row):
        return None if row is None else {**row["body"], "lineage_hash": row["row_hash"]}

    state = {
        "state_schema_version": STATE_SCHEMA_VERSION,
        "champion": controller.champion["champion_id"],
        "champion_config": controller.champion["config"],
        "lineage_length": len(controller.lineage_chain.rows),
        "lineage_head": controller.lineage_chain.head,
        "last_promotion": _state_entry(next((r for r in reversed(controller.lineage_chain.rows)
                                             if r["body"]["state"] == "PROMOTED"), None)),
        "last_rejection": _state_entry(next((r for r in reversed(controller.lineage_chain.rows)
                                             if r["body"]["state"] != "PROMOTED"), None)),
        "budget": budget,
        "conformal_state_latest": cycles[-1]["conformal_state"],
        "off_policy_latest": cycles[-1]["off_policy_state"],
        "registry_growth_count": events["registry_growth"],
        "resolution_backlog": 0,
        "drift_state": "shift_detected_post_2025-07" if events["shift_suspensions"] else "stable",
        "voi_latest": cycles[-1]["voi"],
        "n_cycles": len(cycles), "events": events,
        "evaluator_lifecycle": evaluator.lifecycle,
        "external_action": False,
        "claim_supported": events["promotions"] >= 1 and rejections_all >= 1,
    }
    (out / "state.json").write_text(json.dumps(state, indent=2, sort_keys=True))
    print(f"N_ATTEMPTED={results['n_attempted']}")
    print(f"N_COMPLETED={results['n_completed']}")
    for key, value in events.items():
        print(f"{key.upper()}={value}")
    print(f"FINAL_CHAMPION={controller.champion['champion_id']}")
    print(f"SNAPSHOT_FINAL={controller.snapshot_id}")
    print(f"ALL_CHAINS_SIGNED_VERIFIED={str(all(all(c['verification_replay'].values()) for c in cycles)).lower()}")
    print(f"FINAL_AUDIT_NLL={results['final_audit_holdout']['metrics']['nll']}")
    print(f"EVALUATOR_LIFECYCLE={evaluator.lifecycle}")
    print(f"LOOK_TERMINAL_STATUSES={json.dumps(budget['holdout_look_terminal_statuses'], sort_keys=True)}")
    print(f"BENCHMARK_RECEIPT_ID={results['benchmark_receipt_id']}")
    if events["promotions"] == 0:
        print("NO_CHALLENGER_EARNED_PROMOTION")
    print(f"RECURSIVE_REJECTION_PROVEN={str(rejections_all >= 1).lower()}")
    print(f"RECURSIVE_PROMOTION_PROVEN={str(events['promotions'] >= 1).lower()}")
    ok = (results["n_completed"] == results["n_attempted"]
          and events["receipt_verification_failures"] == 0 and rejections_all >= 1)
    print(f"SEALED_EVOLUTION_PASS={str(ok).lower()}")
    return 0 if ok else 1


if __name__ == "__main__":
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 550
    raise SystemExit(main(seed))
