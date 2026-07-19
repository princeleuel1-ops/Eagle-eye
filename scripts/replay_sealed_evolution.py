"""FULL decision-state replay from the sealed replay bundle (V4 blocker 3).

In a clean process, from REPLAY_BUNDLE.json alone, this script independently
rebuilds and compares EVERY binding of the benchmark run:

  1.  bundle schema version
  2.  evaluator commit-reveal (secret + provenance -> published commitment)
      and lifecycle (reveal only after FINALIZED; FINALIZED row in-chain)
  3.  run context (code revision recomputed over THIS tree, dependency lock
      digest recomputed from the lock file, single evaluator version)
  4.  all three signed chains in Python AND Node (signatures, anchors)
  5.  evaluator ledger structure: charge-before-execution pairing, terminal
      statuses, sequential look indices, unique nonces, lifecycle ordering
  6.  sealed suite rebuild from the revealed secret: case counts, content
      hashes, truth hashes, world seeds vs the PRE-RUN commitments
  7.  base registry manifest; grown-task sequence recomputed through the
      shared pure `build_grown_task`; per-growth and final registry manifests
  8.  full cycle path: live-world targets, champion prediction blocks
      (bit-for-bit vs committed blocks), prediction ids and distribution
      commitments, acting-policy draws and propensities, outcome values from
      the regenerated truth, resolution rows re-executed through a fresh
      PredictionLedger (hash chain equality), registry growth decisions
  9.  lineage replay: deterministic candidate regeneration, snapshot ids,
      dev pre-screen NLLs (challenger AND champion), sealed-look recompute of
      champion/challenger aggregates + paired statistics + alpha accounting,
      and the promotion gate chain via the SAME pure `apply_promotion_gates`
      -> recorded state and reasons must match exactly
  10. final-audit aggregates recomputed on the rebuilt final suite
  11. mapping completeness: charge<->result rows 1:1, SUCCEEDED results <->
      lineage rows 1:1, FAILED/TIMED_OUT/REJECTED results <-> abstention
      lineage rows, outcome chain rows <-> resolutions 1:1; missing,
      duplicate, extra, or unmapped rows FAIL replay

If zero sealed looks were spent the result is reported as
REPLAY_RESULT=VACUOUS_INTEGRITY_ONLY and is NOT called full-decision replay.

Exit code: 0 only if every binding check passed. Any mutated binding field
exits nonzero (see V4_REPLAY_SCHEMA.json and the mutation battery).

usage: PYTHONPATH=src python scripts/replay_sealed_evolution.py <bundle.json> [--fail-fast] [--skip-node]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from eagle_eye.evolution import (
    DEVELOPMENT_SEED,
    apply_promotion_gates,
    build_development_suite,
    generate_candidates,
    predictor_from_config,
    snapshot_identity,
)
from eagle_eye.feedback import (
    state_sha256 as feedback_state_sha256,
    validate_state as validate_feedback_state,
    weighted_generate_candidates,
)
from eagle_eye.flywheel import commit_cycle_prediction
from eagle_eye.outcome_resolution import PredictionLedger, build_grown_task
from eagle_eye.posterior_engine import quantize_micro
from eagle_eye.prediction_court import build_holdout_suite, evaluate_candidate_on_suite, suite_manifest
from eagle_eye.prior_registry import build_registry, canonical_bytes, sha256_hex
from eagle_eye.provenance import dependency_lock_digest
from eagle_eye.regimes import generate_target_case, generate_world
from eagle_eye.sealed_evaluator import EVALUATOR_VERSION, commitment_for, paired_comparison
from eagle_eye.signed_chain import verify_chain
from eagle_eye.stats import DeterministicRng, stable_seed

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SPEC = "sealed-evolution-replay-bundle/4.0"

FAIL_FAST = "--fail-fast" in sys.argv
SKIP_NODE = "--skip-node" in sys.argv

_failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    print(f"{name}={'PASS' if condition else 'FAIL'}" + (f" ({detail})" if detail and not condition else ""))
    if not condition:
        _failures.append(name)
        if FAIL_FAST:
            print("REPLAY_RESULT=FAIL_FAST")
            print("REPLAY_FAIL")
            raise SystemExit(1)
    return condition


def canon(value) -> str:
    return sha256_hex(canonical_bytes(value))


def main() -> int:
    bundle_path = Path(sys.argv[1])
    bundle = json.loads(bundle_path.read_text())

    # ---- 1. schema ----------------------------------------------------------
    check("BUNDLE_SPEC", bundle.get("spec") == EXPECTED_SPEC, str(bundle.get("spec")))

    # ---- 2. commit-reveal + lifecycle --------------------------------------
    reveal = bundle["evaluator_reveal"]
    secret = reveal["evaluator_secret"]
    check("COMMIT_REVEAL", commitment_for(secret, reveal["secret_provenance"])
          == reveal["seed_commitment"])
    check("LIFECYCLE_AT_REVEAL", reveal.get("lifecycle_at_reveal") == "REVEALABLE")
    ev_rows = bundle["chains"]["evaluator"]["rows"]
    finalized_rows = [i for i, r in enumerate(ev_rows) if r["body"]["kind"] == "lifecycle"
                      and r["body"].get("event") == "FINALIZED"]
    charge_indices = [i for i, r in enumerate(ev_rows)
                      if r["body"]["kind"].endswith("_charge")]
    check("LIFECYCLE_FINALIZED_ONCE", len(finalized_rows) == 1)
    check("LIFECYCLE_NO_LOOKS_AFTER_FINALIZE",
          not charge_indices or not finalized_rows or max(charge_indices) < finalized_rows[0])

    # ---- 3. run context binding ---------------------------------------------
    ctx = bundle["run_context"]
    src_rows = []
    for base in ("src", "scripts", "verifier"):
        for r, dirs, files in os.walk(ROOT / base):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in sorted(files):
                p = Path(r) / f
                src_rows.append({"p": str(p.relative_to(ROOT)), "h": sha256_hex(p.read_bytes())})
    src_rows.sort(key=lambda x: x["p"])
    check("RUN_CONTEXT_CODE_REVISION", ctx["code_revision"] == sha256_hex(canonical_bytes(src_rows))[:16],
          "bundle was produced by a different tree than the one replaying it")
    check("RUN_CONTEXT_DEPENDENCY_LOCK", ctx["dependency_lock_sha256"] == dependency_lock_digest(ROOT))
    check("EVALUATOR_VERSION_SINGLE_CONSTANT",
          ctx["evaluator_version"] == EVALUATOR_VERSION
          == bundle["evaluator_config"]["evaluator_version"]
          == reveal["evaluator_version"])

    # ---- 4. signed chains (Python + Node) -----------------------------------
    for name in ("outcomes", "lineage", "evaluator"):
        result = verify_chain(bundle["chains"][name]["rows"], bundle["chains"][name]["anchor"],
                              bundle["signer_registry"], expected_tenant="tenant-demo")
        check(f"CHAIN_{name.upper()}_PY", result["verified"], result.get("reason", ""))
        if not SKIP_NODE:
            node = subprocess.run(["node", "verifier/verify_chain.mjs", str(bundle_path), name, "tenant-demo"],
                                  capture_output=True, text=True, cwd=ROOT)
            check(f"CHAIN_{name.upper()}_NODE", node.returncode == 0
                  and json.loads(node.stdout or "{}").get("verified", False))

    # ---- 5. evaluator ledger structure --------------------------------------
    charges = [r for r in ev_rows if r["body"]["kind"] == "promotion_look_charge"]
    results = [r for r in ev_rows if r["body"]["kind"] == "promotion_look_result"]
    fa_charges = [r for r in ev_rows if r["body"]["kind"] == "final_audit_charge"]
    fa_results = [r for r in ev_rows if r["body"]["kind"] == "final_audit_result"]
    check("LOOKS_DERIVED_FROM_LEDGER", len(fa_charges) == 1 and len(fa_results) == 1)
    result_by_charge = {}
    dup_result = False
    for r in results + fa_results:
        key = r["body"]["charge_row_hash"]
        dup_result = dup_result or key in result_by_charge
        result_by_charge[key] = r
    check("CHARGE_RESULT_PAIRING_1TO1",
          not dup_result
          and all(c["row_hash"] in result_by_charge for c in charges + fa_charges)
          and len(result_by_charge) == len(charges) + len(fa_charges),
          "dangling charge, duplicate, or orphaned result row")
    check("TERMINAL_STATUSES_VALID",
          all(r["body"]["terminal_status"] in ("SUCCEEDED", "FAILED", "TIMED_OUT", "REJECTED")
              for r in results + fa_results)
          and all(c["body"]["terminal_status"] == "CHARGED_PENDING" for c in charges + fa_charges))
    check("LOOK_INDICES_SEQUENTIAL",
          [c["body"]["look_index"] for c in charges] == list(range(1, len(charges) + 1)))
    nonces = [c["body"]["nonce"] for c in charges + fa_charges]
    check("NONCES_UNIQUE", len(nonces) == len(set(nonces)))
    alpha_total = bundle["evaluator_config"]["alpha_total"]
    max_looks = bundle["evaluator_config"]["max_looks"]
    alpha_per_look = alpha_total / max_looks
    check("ALPHA_BUDGET_RESPECTED", len(charges) <= max_looks)

    # ---- 6. sealed suites rebuilt from the revealed secret ------------------
    scale = bundle["evaluator_config"]["suite_scale"]
    check("SUITE_SCALE_CONSISTENT", scale == bundle.get("suite_scale") == reveal["suite_scale"])
    promotion = build_holdout_suite(stable_seed("promotion-holdout", secret) % (1 << 31), scale=scale)
    final_suite = build_holdout_suite(stable_seed("final-audit-holdout", secret) % (1 << 31), scale=scale)
    commitments = reveal["suite_commitments"]
    check("SEALED_PROMOTION_SUITE_REBUILT", suite_manifest(promotion) == commitments["promotion"],
          "promotion suite does not match pre-run commitment")
    check("SEALED_FINAL_SUITE_REBUILT", suite_manifest(final_suite) == commitments["final"],
          "final-audit suite does not match pre-run commitment")
    check("SUITES_DISTINCT", promotion["world_seed"] != final_suite["world_seed"])

    # ---- 7+8. full cycle path: registry, predictions, resolutions, growth ---
    base_world = generate_world(bundle["registry_base"]["world_seed"],
                                tasks_per_regime=bundle["registry_base"]["tasks_per_regime"])
    tasks = list(base_world["tasks"])
    registry = build_registry(tasks)
    check("REGISTRY_BASE_REBUILT", registry["manifest_sha256"] == bundle["base_registry_manifest_sha256"])
    live_world = generate_world(bundle["live_world"]["world_seed"],
                                tasks_per_regime=bundle["live_world"]["tasks_per_regime"])
    policy_rng = DeterministicRng(stable_seed("acting-policy", bundle["live_world"]["world_seed"]))
    follow_prob = bundle["follow_prob"]
    replay_ledger = PredictionLedger("tenant-demo", policy_registry=bundle["policy_registry"])
    grown_by_cycle = {g["cycle"]: g for g in bundle["grown_tasks"]}
    lineage_rows = bundle["chains"]["lineage"]["rows"]
    rows_by_cycle: dict[int, list] = {}
    for row in lineage_rows:
        rows_by_cycle.setdefault(row["body"]["candidate"]["created_at_cycle"], []).append(row)
    resolutions = bundle["resolutions"]
    check("RESOLUTION_COUNT_MATCHES_CYCLES", len(resolutions) == len(bundle["cycle_cutoffs"]))
    outcome_rows = bundle["chains"]["outcomes"]["rows"]
    check("OUTCOME_CHAIN_MAPS_RESOLUTIONS_1TO1",
          [r["body"]["resolution_hash"] for r in outcome_rows]
          == [r["current_audit_hash"] for r in resolutions])

    champion_id = "champ-genesis-governed-set-mt"
    champion_config = dict(bundle["genesis_config"])
    run_seed = bundle["controller_run_seed"]
    run_ctx = bundle["run_context"]
    # V7 (optional feedback-harness bundles): validate the recorded state and
    # bind it — weighted generation is then recomputed from THIS state, and
    # every candidate id must embed its sha256. Legacy bundles (no block)
    # take the identical pre-V7 path with zero additional checks.
    feedback_block = bundle.get("feedback")
    if feedback_block is not None:
        validate_feedback_state(feedback_block["state"])
        expected_fb_sha = feedback_state_sha256(feedback_block["state"])
        check("FEEDBACK_STATE_BOUND",
              all(row["body"]["candidate"].get("feedback_state_sha256") == expected_fb_sha
                  for row in bundle["chains"]["lineage"]["rows"]),
              "lineage candidate ids must bind the recorded feedback state hash")
    dev_suite = build_development_suite(DEVELOPMENT_SEED)
    dev_cache: dict[str, int] = {}

    def dev_nll_micro(config, reg) -> int | None:
        key = canon({"c": config, "r": reg["manifest_sha256"]})
        if key not in dev_cache:
            ev = evaluate_candidate_on_suite(
                "dev", dev_suite, reg, fn=predictor_from_config(config),
                k_max_override=config["selector.k_max"],
                min_score_override=config["selector.min_score_milli"] / 1000.0)
            nll = ev["metrics"]["nll"]
            dev_cache[key] = None if nll is None else int(round(nll * 1e6))
        return dev_cache[key]

    def sealed_eval(config, reg):
        return evaluate_candidate_on_suite(
            "sealed", promotion, reg, fn=predictor_from_config(config),
            k_max_override=config["selector.k_max"],
            min_score_override=config["selector.min_score_milli"] / 1000.0)

    result_rows_by_hash = {r["row_hash"]: r for r in results}
    consumed_result_hashes: set[str] = set()
    consumed_charge_hashes: set[str] = set()
    decisions_recomputed = 0
    decisions_mismatched = 0
    cycle_ok = True
    lineage_ok = True

    for index, cutoff in enumerate(bundle["cycle_cutoffs"], start=1):
        case = generate_target_case(live_world, case_index=9000 + index, tenant_id="tenant-demo",
                                    disruption_class="port_congestion", cutoff=cutoff, n_target_obs=2)
        block = commit_cycle_prediction(registry, case["target"], champion_config, champion_id)
        committed = replay_ledger.commit_prediction(
            block, champion_id=champion_id,
            policy_release_hash=bundle["policy_release_hash"],
            resource_scope="scope:live-disruptions")
        recorded_resolution = resolutions[index - 1]
        cycle_ok &= committed["prediction_id"] == recorded_resolution["prediction_id"]
        cycle_ok &= (committed["prediction_distribution_hash"]
                     == recorded_resolution["prediction_distribution_hash"])
        bundle_block = bundle["predictions"].get(committed["prediction_id"])
        cycle_ok &= bundle_block is not None and canon(bundle_block) == canon(block)
        recommended = block["recommendation"]["recommended_intervention"]
        follow = policy_rng.uniform() < follow_prob
        taken = recommended if follow else "wait_incumbent"
        propensity = follow_prob if follow else round(1.0 - follow_prob, 6)
        truth_outcome = case["truth"]["outcomes"][taken]
        observed_at = (date.fromisoformat(cutoff)
                       + timedelta(days=int(truth_outcome["final_delay_days"]) + 4)).isoformat()
        source_payload = {"channel": "authorized_synthetic_truth", "case_id": case["target"]["case_id"],
                          "taken": taken, "log_final_delay": round(truth_outcome["log_final_delay"], 6)}
        replayed = replay_ledger.resolve({
            "prediction_id": committed["prediction_id"],
            "prediction_distribution_hash": committed["prediction_distribution_hash"],
            "policy_release_hash": bundle["policy_release_hash"],
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
            "intervention_taken": taken, "acting_policy": next(iter(bundle["policy_registry"])),
            "recommendation_propensity": propensity,
            "authorization_receipt": "approval-shadow-fixture",
        })
        strip = lambda r: {k: v for k, v in r.items() if k != "signed_row_hash"}
        cycle_ok &= canon(strip(replayed)) == canon(strip(recorded_resolution))
        if replayed["eligibility_for_registry"]:
            grown_entry = grown_by_cycle.get(index)
            cycle_ok &= grown_entry is not None
            if grown_entry is not None:
                recomputed_task = build_grown_task(block, replayed)
                cycle_ok &= canon(recomputed_task) == canon(grown_entry["task"])
                tasks.append(recomputed_task)
                registry = build_registry(tasks, release=grown_entry["release"])
                cycle_ok &= registry["manifest_sha256"] == grown_entry["registry_manifest_after"]
        else:
            cycle_ok &= index not in grown_by_cycle

        # ---- 9. lineage replay for this cycle ------------------------------
        snapshot = snapshot_identity(registry_manifest_sha256=registry["manifest_sha256"],
                                     evaluator_seed_commitment=reveal["seed_commitment"],
                                     run_seed=run_seed, run_context=run_ctx)
        if feedback_block is not None:
            expected_candidates = weighted_generate_candidates(
                run_seed=run_seed, champion_id=champion_id,
                champion_config=champion_config, snapshot_id=snapshot,
                registry_manifest_sha256=registry["manifest_sha256"],
                evaluator_seed_commitment=reveal["seed_commitment"],
                cycle=index, feedback_state=feedback_block["state"])
        else:
            expected_candidates = generate_candidates(run_seed=run_seed, champion_id=champion_id,
                                                      champion_config=champion_config,
                                                      snapshot_id=snapshot,
                                                      registry_manifest_sha256=registry["manifest_sha256"],
                                                      evaluator_seed_commitment=reveal["seed_commitment"],
                                                      cycle=index)
        recorded_rows = rows_by_cycle.get(index, [])
        lineage_ok &= len(recorded_rows) == len(expected_candidates)
        for expected, row in zip(expected_candidates, recorded_rows):
            body = row["body"]
            lineage_ok &= body["candidate"]["candidate_id"] == expected["candidate_id"]
            lineage_ok &= body["candidate"]["diff"] == expected["diff"]
            lineage_ok &= body["candidate_config"] == expected["config"]
            lineage_ok &= body["dataset_snapshot_id"] == snapshot
            lineage_ok &= body["registry_manifest_sha256"] == registry["manifest_sha256"]
            lineage_ok &= body["evaluator_version"] == EVALUATOR_VERSION
            chall_dev = dev_nll_micro(expected["config"], registry)
            champ_dev = dev_nll_micro(champion_config, registry)
            lineage_ok &= body["dev_nll_challenger_micro"] == chall_dev
            lineage_ok &= body["dev_nll_champion_micro"] == champ_dev
            if chall_dev is None or chall_dev >= champ_dev:
                lineage_ok &= (body["state"] == "REJECTED"
                               and body["reasons"] == ["development_no_improvement (no sealed look spent)"]
                               and body["evaluator_response_hash"] is None
                               and body["evaluator_charge_hash"] is None)
                continue
            # a sealed look was spent: recompute the full decision
            resp_hash = body["evaluator_response_hash"]
            resp_row = result_rows_by_hash.get(resp_hash)
            if resp_row is None or resp_hash in consumed_result_hashes:
                lineage_ok = False
                decisions_mismatched += 1
                continue
            consumed_result_hashes.add(resp_hash)
            consumed_charge_hashes.add(resp_row["body"]["charge_row_hash"])
            rbody = resp_row["body"]
            lineage_ok &= rbody["terminal_status"] == "SUCCEEDED"
            lineage_ok &= rbody["candidate_id"] == expected["candidate_id"]
            lineage_ok &= rbody["snapshot_id"] == snapshot
            lineage_ok &= rbody["nonce"] == f"{expected['candidate_id']}:{snapshot}"
            lineage_ok &= body["evaluator_charge_hash"] == rbody["charge_row_hash"]
            champ_eval = sealed_eval(champion_config, registry)
            chall_eval = sealed_eval(expected["config"], registry)
            stats = paired_comparison(champ_eval, chall_eval, alpha_per_look)
            stats["alpha_spent_after_micro"] = int(round(rbody["look_index"] * alpha_per_look * 1e6))
            stats["alpha_total_micro"] = int(round(alpha_total * 1e6))
            recomputed_fragment = quantize_micro({
                "statistics": stats,
                "challenger_aggregates": {
                    "metrics": chall_eval["metrics"], "scored_count": chall_eval["scored_count"],
                    "abstentions_standard": chall_eval["abstentions_standard"],
                    "abstentions_probe": chall_eval["abstentions_probe"],
                    "probe_count": chall_eval["probe_count"]},
                "champion_aggregates": {
                    "metrics": champ_eval["metrics"], "scored_count": champ_eval["scored_count"]},
            })
            recorded_fragment = {"statistics": rbody["statistics"],
                                 "challenger_aggregates": rbody["challenger_aggregates"],
                                 "champion_aggregates": rbody["champion_aggregates"]}
            state, reasons = apply_promotion_gates(recomputed_fragment)
            full_match = (canon(recomputed_fragment) == canon(recorded_fragment)
                          and state == body["state"] and reasons == body["reasons"]
                          # lineage row must carry the SAME statistics the
                          # evaluator chain recorded (cross-chain consistency)
                          and body["statistics"] == rbody["statistics"])
            if full_match:
                decisions_recomputed += 1
            else:
                decisions_mismatched += 1
                lineage_ok = False
            if body["state"] == "PROMOTED":
                champion_id = body["candidate"]["candidate_id"]
                champion_config = dict(body["candidate_config"])
                # champion change invalidates nothing here: snapshot/dev are
                # recomputed per cycle from the trajectory we are tracking

    check("CYCLE_PATH_REPLAYED", bool(cycle_ok),
          "prediction/resolution/growth path diverged from bundle")
    check("FINAL_REGISTRY_MANIFEST", registry["manifest_sha256"] == bundle["final_registry_manifest_sha256"])
    check("FINAL_CHAMPION_MATCHES", champion_id == bundle["final_champion"]
          and champion_config == bundle["final_champion_config"])
    check("LINEAGE_REPLAYED", bool(lineage_ok), "candidate/dev/gate/statistics divergence")

    # ---- 10. final audit recompute ------------------------------------------
    fa_body = fa_results[0]["body"]
    fa_ok = fa_body["terminal_status"] == "SUCCEEDED" and fa_body["champion_id"] == champion_id
    fa_eval = evaluate_candidate_on_suite(
        "sealed", final_suite, registry, fn=predictor_from_config(champion_config),
        k_max_override=champion_config["selector.k_max"],
        min_score_override=champion_config["selector.min_score_milli"] / 1000.0)
    recomputed_fa = quantize_micro({
        "metrics": fa_eval["metrics"], "scored_count": fa_eval["scored_count"],
        "abstentions_standard": fa_eval["abstentions_standard"],
        "probes_refused": fa_eval["abstentions_probe"] == fa_eval["probe_count"]})
    check("FINAL_AUDIT_RECOMPUTED", fa_ok and recomputed_fa == fa_body["aggregates"])

    # ---- 11. mapping completeness -------------------------------------------
    succeeded_hashes = {r["row_hash"] for r in results if r["body"]["terminal_status"] == "SUCCEEDED"}
    failed_charge_hashes = {r["body"]["charge_row_hash"] for r in results
                            if r["body"]["terminal_status"] != "SUCCEEDED"}
    lineage_charge_refs = [b["body"]["evaluator_charge_hash"] for b in lineage_rows
                           if b["body"]["evaluator_charge_hash"] is not None]
    check("EVALUATOR_LINEAGE_MAPPING_1TO1",
          consumed_result_hashes == succeeded_hashes
          and len(lineage_charge_refs) == len(set(lineage_charge_refs))
          and set(lineage_charge_refs) == consumed_charge_hashes | failed_charge_hashes,
          "unmapped, duplicate, or extra promotion-look rows")

    vacuous = len(charges) == 0
    ok = not _failures
    print(f"DECISIONS_RECOMPUTED={decisions_recomputed} MISMATCHED={decisions_mismatched}")
    if vacuous:
        print("REPLAY_RESULT=VACUOUS_INTEGRITY_ONLY (zero sealed looks spent; this is NOT full-decision replay)")
    else:
        print(f"REPLAY_RESULT={'PASS_FULL_DECISION' if ok else 'FAIL'}")
    print(f"REPLAY_{'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
