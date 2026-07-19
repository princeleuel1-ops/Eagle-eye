"""Anytime-valid cross-run promotion evidence — the V7 e-process ledger.

THE GAP THIS CLOSES (V6 wall `W-promotion`): sealed promotion evidence was
PER-RUN only; cross-run alpha was NOT pooled; the rerun-lottery guard was
procedural (auditable via the ledger) rather than statistical. A genuinely
better challenger accumulated no standing evidence across runs, and repeated
reruns could not be statistically distinguished from luck.

THE INSTRUMENT: one e-process (test supermartingale) per evidence stream,
where a stream is an exact (champion_config, challenger_config) pair.

  H0 (per stream): on a fresh sealed case, P(challenger strictly beats
      champion in per-case NLL) <= 1/2   — the paired sign null.

  Per admitted run r: from the REVEALED bundle (admission REQUIRES a passed
  independent full-decision replay), this module RE-DERIVES per-case paired
  NLL differences itself — suites rebuilt from the revealed secret and
  verified against the pre-run commitments, registries rebuilt through the
  recorded growth trajectory — and counts wins/losses/ties in integer micro
  space. Nothing is trusted from the run's own aggregates; consistency with
  the recorded `n_paired` is enforced.

  Per-run e-value: the one-sided binomial mixture e-value with uniform
  prior over theta in (1/2, 1]:

      e(k, m) = 2^(m+1) * B(k+1, m-k+1) * (1 - I_{1/2}(k+1, m-k+1))

  with k = wins, m = wins + losses (ties dropped, pre-registered), B the
  beta function and I the regularized incomplete beta. At the null boundary
  theta = 1/2 this has expectation exactly 1, and E[e] <= 1 for every
  theta <= 1/2 (monotone likelihood ratio), so it is a valid e-value for the
  composite one-sided null.

  Cross-run wealth: W_R = prod_r e_r over admitted runs. Fresh CSPRNG
  evaluator secrets make per-run suites independent, so W is a test
  supermartingale under H0 and Ville's inequality gives

      P_H0( exists R : W_R >= 1/alpha ) <= alpha

  — time-uniform Type-I control that is valid under optional stopping AND
  optional continuation. Rerunning until something crosses cannot inflate
  error: the rerun lottery is closed BY CONSTRUCTION, not by procedure.

WITHIN-RUN DEPENDENCE GUARD: a run's promotion suite is FIXED once its
secret is drawn, so two sealed looks at the same config pair inside one run
are perfectly dependent. Only the FIRST sealed look per stream per run
contributes; later same-pair looks in that run are recorded as
non-contributing duplicates.

WHAT THIS DOES NOT DO: it never overrides the per-run promotion gate chain
(trust, calibration, shift, scored-count all still binding); it adds no new
mutation surface; it makes no claim about structurally independent
generators (`W-transfer` stands). A crossing is a STATISTICAL EVIDENCE
claim about the sealed synthetic suite distribution — labeled
THEOREM-CONDITIONAL on independent case sampling, which the CSPRNG suite
generator provides synthetically. EXTERNALLY VALIDATED: nothing.
"""

from __future__ import annotations

import math
from typing import Any

from .prediction_court import evaluate_candidate_on_suite, build_holdout_suite, suite_manifest
from .prior_registry import build_registry, canonical_bytes, sha256_hex
from .regimes import generate_world
from .sealed_evaluator import commitment_for
from .signed_chain import SignedChain
from .signing import generate_demo_keypair
from .stats import _betainc_regularized, _log_beta, stable_seed

EPROCESS_SPEC = "eagle-eye-eprocess/1.0"
# Pre-registered promotion evidence level for the cross-run ledger.
EPROCESS_ALPHA_MICRO = 50_000  # alpha = 0.05
# ln(1/alpha) in integer micro-nats: promotion evidence when cumulative
# log wealth reaches this. round(ln(20) * 1e6) = 2_995_732.
EPROCESS_LOG_THRESHOLD_MICRO = 2_995_732
_LN2 = math.log(2.0)
_LOG_FLOOR = -80.0  # floor for log(1 - I) underflow; e-values may be tiny, never negative wealth


def stream_id(champion_config: dict[str, Any], challenger_config: dict[str, Any]) -> str:
    """Canonical identity of an evidence stream: the exact config pair."""
    return "strm-" + sha256_hex(canonical_bytes({
        "champion_config": champion_config,
        "challenger_config": challenger_config,
    }))[:16]


def sign_counts_from_diffs_micro(diffs_micro: list[int]) -> dict[str, int]:
    """diff_micro = micro(NLL_challenger - NLL_champion); win means diff < 0
    (challenger strictly better on the case). Ties dropped, pre-registered."""
    wins = sum(1 for d in diffs_micro if d < 0)
    losses = sum(1 for d in diffs_micro if d > 0)
    ties = len(diffs_micro) - wins - losses
    return {"wins": wins, "losses": losses, "ties": ties, "n_cases": len(diffs_micro)}


def binomial_mixture_log_e(wins: int, losses: int) -> float:
    """Natural log of the one-sided binomial mixture e-value (uniform prior on
    theta in (1/2, 1]) for k=wins successes in m=wins+losses trials against
    H0: theta <= 1/2. Exact closed form via the regularized incomplete beta.
    m = 0 returns log e = 0 (e = 1: no evidence either way)."""
    if wins < 0 or losses < 0:
        raise ValueError("negative counts")
    m = wins + losses
    if m == 0:
        return 0.0
    upper_mass = 1.0 - _betainc_regularized(wins + 1, m - wins + 1, 0.5)
    log_tail = math.log(upper_mass) if upper_mass > 0.0 else _LOG_FLOOR
    return (m + 1) * _LN2 + _log_beta(wins + 1, m - wins + 1) + log_tail


def log_e_micro(wins: int, losses: int) -> int:
    """Ledger-facing integer form: micro-nats, deterministic given counts."""
    return int(round(binomial_mixture_log_e(wins, losses) * 1e6))


def extract_stream_evidence(bundle: dict[str, Any]) -> dict[str, Any]:
    """Re-derive per-stream sign evidence from a REVEALED replay bundle.

    Independent recomputation: rebuilds the promotion suite from the revealed
    secret (verified against the pre-run commitment), rebuilds the registry
    trajectory through the recorded grown tasks, re-evaluates champion and
    challenger per-case on the sealed suite for every SUCCEEDED sealed look,
    and counts signs of micro-quantized paired NLL differences.

    Returns {"streams": {stream_id: {...counts, contributing rows...}},
             "looks_seen": int, "looks_contributing": int}.
    Raises ValueError on ANY inconsistency (fail closed): suite commitment
    mismatch, registry manifest mismatch, or recomputed pair count differing
    from the recorded statistics.n_paired.
    """
    reveal = bundle["evaluator_reveal"]
    secret = reveal["evaluator_secret"]
    if commitment_for(secret, reveal["secret_provenance"]) != reveal["seed_commitment"]:
        raise ValueError("revealed secret does not match the published commitment")
    scale = bundle["evaluator_config"]["suite_scale"]
    promotion = build_holdout_suite(stable_seed("promotion-holdout", secret) % (1 << 31), scale=scale)
    if suite_manifest(promotion) != reveal["suite_commitments"]["promotion"]:
        raise ValueError("rebuilt promotion suite does not match pre-run commitment")

    base_world = generate_world(bundle["registry_base"]["world_seed"],
                                tasks_per_regime=bundle["registry_base"]["tasks_per_regime"])
    tasks = list(base_world["tasks"])
    registry = build_registry(tasks)
    if registry["manifest_sha256"] != bundle["base_registry_manifest_sha256"]:
        raise ValueError("base registry manifest mismatch")
    grown_by_cycle = {g["cycle"]: g for g in bundle["grown_tasks"]}

    lineage_rows = bundle["chains"]["lineage"]["rows"]
    rows_by_cycle: dict[int, list] = {}
    for row in lineage_rows:
        rows_by_cycle.setdefault(row["body"]["candidate"]["created_at_cycle"], []).append(row)

    champion_config = dict(bundle["genesis_config"])
    eval_cache: dict[str, Any] = {}

    def sealed_eval(config: dict[str, Any], reg: dict[str, Any]) -> dict[str, Any]:
        key = sha256_hex(canonical_bytes({"c": config, "r": reg["manifest_sha256"]}))
        if key not in eval_cache:
            eval_cache[key] = evaluate_candidate_on_suite(
                "sealed", promotion, reg, fn=_predictor(config),
                k_max_override=config["selector.k_max"],
                min_score_override=config["selector.min_score_milli"] / 1000.0)
        return eval_cache[key]

    streams: dict[str, dict[str, Any]] = {}
    seen_in_run: set[str] = set()
    looks_seen = looks_contributing = 0

    for index in sorted(rows_by_cycle):
        grown_entry = grown_by_cycle.get(index)
        # registry state for this cycle mirrors the recorded (replay-verified)
        # growth trajectory: grown task appended BEFORE this cycle's lineage
        # rows were produced iff recorded so.
        for row in rows_by_cycle[index]:
            body = row["body"]
            if body.get("evaluator_response_hash") is None or body.get("statistics") is None:
                if body["state"] == "PROMOTED":  # defensive: promotion without a look is impossible
                    raise ValueError("PROMOTED lineage row without a sealed look")
                continue
            reg = _registry_at(bundle, index, tasks, grown_by_cycle)
            if reg["manifest_sha256"] != body["registry_manifest_sha256"]:
                raise ValueError(f"registry manifest mismatch at cycle {index}")
            looks_seen += 1
            chall_config = body["candidate_config"]
            sid = stream_id(champion_config, chall_config)
            champ_eval = sealed_eval(champion_config, reg)
            chall_eval = sealed_eval(chall_config, reg)
            champ_cases = {r["case_id"]: r for r in champ_eval["per_case"] if not r["abstained"]}
            diffs_micro = [int(round((r["nll"] - champ_cases[r["case_id"]]["nll"]) * 1e6))
                           for r in chall_eval["per_case"]
                           if not r["abstained"] and r["case_id"] in champ_cases]
            counts = sign_counts_from_diffs_micro(diffs_micro)
            if counts["n_cases"] != body["statistics"]["n_paired"]:
                raise ValueError(
                    f"recomputed pair count {counts['n_cases']} != recorded "
                    f"n_paired {body['statistics']['n_paired']} (cycle {index})")
            contributing = sid not in seen_in_run
            seen_in_run.add(sid)
            if contributing:
                looks_contributing += 1
            entry = streams.setdefault(sid, {
                "stream_id": sid,
                "champion_config": dict(champion_config),
                "challenger_config": dict(chall_config),
                "diff": body["candidate"]["diff"],
                "wins": 0, "losses": 0, "ties": 0,
                "contributing_look": None,
                "duplicate_looks_in_run": 0,
            })
            if contributing:
                entry.update({"wins": counts["wins"], "losses": counts["losses"],
                              "ties": counts["ties"],
                              "contributing_look": {"cycle": index,
                                                     "lineage_row_hash": row["row_hash"],
                                                     "state": body["state"]}})
            else:
                entry["duplicate_looks_in_run"] += 1
            if body["state"] == "PROMOTED":
                champion_config = dict(chall_config)
        _ = grown_entry  # trajectory handled by _registry_at
    return {"streams": streams, "looks_seen": looks_seen,
            "looks_contributing": looks_contributing}


def _registry_at(bundle: dict[str, Any], cycle_index: int, base_tasks: list,
                 grown_by_cycle: dict[int, dict]) -> dict[str, Any]:
    """Registry state during `cycle_index`, mirroring the recorded growth
    trajectory (grown task of cycle c becomes visible to cycle c's lineage,
    matching the recorded registry_manifest_after — verified by the caller
    against each lineage row)."""
    tasks = list(base_tasks)
    release = None
    for c in sorted(grown_by_cycle):
        if c > cycle_index:
            break
        tasks.append(grown_by_cycle[c]["task"])
        release = grown_by_cycle[c]["release"]
    return build_registry(tasks, release=release) if release else build_registry(tasks)


def _predictor(config: dict[str, Any]):
    from .evolution import predictor_from_config
    return predictor_from_config(config)


class EProcessLedger:
    """Signed, append-only cross-run evidence ledger.

    Admission is FAIL-CLOSED: a run is admitted only with an explicit passed
    independent-replay verdict; evidence is then re-derived from the bundle
    by `extract_stream_evidence`, never copied from run aggregates. All
    stored evidence is integer micro-nats; cumulative wealth is integer
    addition of per-run log e-values (product of e-values in log space)."""

    def __init__(self, *, tenant_id: str = "tenant-demo", run_id: str = "run-eprocess") -> None:
        private_key, public_key = generate_demo_keypair()
        self.chain = SignedChain(tenant_id=tenant_id, run_id=run_id,
                                 chain_id="eprocess-ledger",
                                 private_key=private_key, public_key=public_key)
        self.state: dict[str, Any] = {
            "spec": EPROCESS_SPEC,
            "alpha_micro": EPROCESS_ALPHA_MICRO,
            "log_threshold_micro": EPROCESS_LOG_THRESHOLD_MICRO,
            "admitted_runs": [],
            "streams": {},
        }

    # -- admission -------------------------------------------------------------
    def admit_run(self, bundle: dict[str, Any], *, bundle_sha256: str,
                  replay_passed: bool, replay_report: dict[str, Any]) -> dict[str, Any]:
        if not replay_passed:
            raise ValueError("ADMISSION_REFUSED: independent replay did not pass; "
                             "unverified evidence cannot enter the e-process ledger")
        run_key = bundle["evaluator_reveal"]["seed_commitment"]
        if any(r["seed_commitment"] == run_key for r in self.state["admitted_runs"]):
            raise ValueError("ADMISSION_REFUSED: run already admitted (double counting)")
        evidence = extract_stream_evidence(bundle)
        contributions = []
        for sid, ev in sorted(evidence["streams"].items()):
            if ev["contributing_look"] is None:
                continue
            delta = log_e_micro(ev["wins"], ev["losses"])
            entry = self.state["streams"].setdefault(sid, {
                "stream_id": sid,
                "champion_config": ev["champion_config"],
                "challenger_config": ev["challenger_config"],
                "diff": ev["diff"],
                "cumulative_log_e_micro": 0,
                "runs_contributing": 0,
                "history": [],
            })
            entry["cumulative_log_e_micro"] += delta
            entry["runs_contributing"] += 1
            entry["history"].append({
                "seed_commitment": run_key,
                "wins": ev["wins"], "losses": ev["losses"], "ties": ev["ties"],
                "log_e_micro": delta,
                "cumulative_log_e_micro": entry["cumulative_log_e_micro"],
                "lineage_row_hash": ev["contributing_look"]["lineage_row_hash"],
                "duplicate_looks_excluded": ev["duplicate_looks_in_run"],
            })
            contributions.append({"stream_id": sid, "wins": ev["wins"],
                                  "losses": ev["losses"], "ties": ev["ties"],
                                  "log_e_micro": delta,
                                  "cumulative_log_e_micro": entry["cumulative_log_e_micro"]})
        admission = {
            "spec": EPROCESS_SPEC,
            "kind": "eprocess_admission",
            "seed_commitment": run_key,
            "bundle_sha256": bundle_sha256,
            "replay_passed": True,
            "replay_report": replay_report,
            "looks_seen": evidence["looks_seen"],
            "looks_contributing": evidence["looks_contributing"],
            "contributions": contributions,
            "state_sha256_after": None,  # filled below, then signed
        }
        self.state["admitted_runs"].append({
            "seed_commitment": run_key, "bundle_sha256": bundle_sha256,
            "contributions": len(contributions),
        })
        admission["state_sha256_after"] = self.state_sha256()
        row = self.chain.append(admission)
        admission["row_hash"] = row["row_hash"]
        return admission

    # -- reporting ---------------------------------------------------------------
    def state_sha256(self) -> str:
        return sha256_hex(canonical_bytes(self.state))

    def standing(self) -> list[dict[str, Any]]:
        rows = [{"stream_id": s["stream_id"], "diff": s["diff"],
                 "cumulative_log_e_micro": s["cumulative_log_e_micro"],
                 "runs_contributing": s["runs_contributing"],
                 "crossed": s["cumulative_log_e_micro"] >= EPROCESS_LOG_THRESHOLD_MICRO}
                for s in self.state["streams"].values()]
        return sorted(rows, key=lambda r: (-r["cumulative_log_e_micro"], r["stream_id"]))

    def crossings(self) -> list[dict[str, Any]]:
        return [r for r in self.standing() if r["crossed"]]

    def verify_chain(self) -> bool:
        from .signed_chain import verify_chain
        registry = {"trusted_signers": [{"key_id": self.chain.signer_key_id,
                                         "public_key_pem": self.chain.public_key.decode()}]}
        report = verify_chain(self.chain.rows, self.chain.anchor(), registry,
                              expected_tenant=self.chain.tenant_id,
                              expected_chain_id=self.chain.chain_id,
                              expected_run_id=self.chain.run_id)
        return bool(report.get("verified", False))
