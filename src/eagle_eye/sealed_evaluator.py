"""Sealed evaluator boundary v4 (post V3 adversarial audit).

V4 rebuilds the evaluator lifecycle and access accounting:

SECRET CUSTODY (V4 blocker 1)
  The evaluator secret MUST be cryptographically random and supplied through
  the explicit trusted boundary `provision_evaluator_secret()` (CSPRNG,
  `secrets.token_hex`). It must NEVER be derived from public seeds, code
  revisions, timestamps, or run ids — the V3 pattern
  `evaluator-secret-{live_seed}-{code_revision}` allowed anyone holding public
  metadata to rebuild the sealed suites before the run; it is abolished and a
  regression test greps for it. The published commitment binds BOTH the secret
  and its declared provenance: sha256(canonical({"evaluator_secret",
  "secret_provenance"})).

LIFECYCLE (V4 blocker 1)
  INITIALIZED -> EVALUATING -> FINALIZED -> REVEALABLE, strictly monotone:
    - first charged access moves INITIALIZED -> EVALUATING
    - finalize() moves to FINALIZED (appends a signed lifecycle ledger row);
      after FINALIZED no further compare()/final_audit() is possible
    - reveal_for_replay() HARD-FAILS unless state is FINALIZED/REVEALABLE and
      moves to REVEALABLE. There is no transition backwards.

CHARGE-BEFORE-EXECUTION (V4 blocker 2)
  Every holdout access appends a signed CHARGE row to the append-only ledger
  BEFORE any candidate/scoring code runs. The outcome is then recorded in a
  linked RESULT row with a terminal status: SUCCEEDED, FAILED, TIMED_OUT, or
  REJECTED. Success, rejection, exception, timeout, and malformed responses
  ALL consume the look; a fresh nonce cannot buy a free failed query. Look
  counts and alpha spend are derived from CHARGE rows, never stored.
  Candidate functions receive a deep copy of each compiled context, so they
  can capture features (at the cost of a charged look) but can never mutate
  the copy used for scoring and never see truth labels.

STATISTICAL RULE (unchanged from V3, precommitted)
  Paired per-case log-score differences d_i = NLL_challenger - NLL_champion.
  H0: E[d] >= 0. Bonferroni allocation alpha_look = alpha_total / max_looks
  charged per look. Decision support requires the one-sided (1 - alpha_look)
  upper confidence bound of mean(d) < 0 and n >= MIN_PAIRED_N.

HONESTY NOTE (unchanged, load-bearing)
  This is a software boundary inside one process. It is NOT organizational
  isolation, NOT production key custody, and in-process Python cannot prevent
  a determined candidate from capturing its own inputs — it can only make
  every capture cost a charged, signed, terminal-status ledger row and keep
  truth labels on the other side of the boundary. Labeled accordingly:
  MECHANICALLY VERIFIED at the API level; organizational isolation
  NOT ESTABLISHED.
"""

from __future__ import annotations

import copy
import math
import secrets
import signal
import threading
from typing import Any

from .prediction_court import build_holdout_suite, evaluate_candidate_on_suite, suite_manifest
from .prior_registry import canonical_bytes, sha256_hex
from .signed_chain import SignedChain
from .signing import generate_demo_keypair
from .stats import norm_ppf, stable_seed

EVALUATOR_VERSION = "sealed-evaluator/4.0"
MIN_PAIRED_N = 30
LIFECYCLE_STATES = ("INITIALIZED", "EVALUATING", "FINALIZED", "REVEALABLE")
TERMINAL_STATUSES = ("SUCCEEDED", "FAILED", "TIMED_OUT", "REJECTED")
SECRET_PROVENANCES = ("csprng_operator_boundary", "test_fixture")


def provision_evaluator_secret() -> dict[str, str]:
    """Trusted operator boundary: mint a cryptographically random evaluator
    secret (256 bits via the OS CSPRNG). This is the ONLY sanctioned source of
    live evaluator secrets. In this sandbox the 'operator' is the run script
    itself — an in-process, non-production custody model, labeled as such."""
    return {"secret": secrets.token_hex(32), "provenance": "csprng_operator_boundary"}


def commitment_for(secret: str, provenance: str) -> str:
    return sha256_hex(canonical_bytes({"evaluator_secret": secret,
                                       "secret_provenance": provenance}))


def paired_test_from_diffs(diffs: list[float], alpha_per_look: float) -> dict[str, Any]:
    """The precommitted decision-rule core over paired per-case differences.
    Single source of truth: used by `paired_comparison` (live evaluator AND
    full-decision replay) and by the power analysis (operating
    characteristics of THIS exact rule, not a reimplementation)."""
    n = len(diffs)
    if n >= 2:
        mean = sum(diffs) / n
        sd = math.sqrt(sum((d - mean) ** 2 for d in diffs) / (n - 1))
        se = sd / math.sqrt(n) if sd > 0 else 1e-12
        t_stat = mean / se
        z = norm_ppf(1.0 - alpha_per_look)
        ci_upper, ci_lower = mean + z * se, mean - z * se
    else:
        mean = sd = t_stat = ci_upper = ci_lower = None
    return {"n": n, "mean": mean, "sd": sd, "t_stat": t_stat,
            "ci_lower": ci_lower, "ci_upper": ci_upper,
            "significant_improvement": bool(n >= MIN_PAIRED_N and ci_upper is not None
                                            and ci_upper < 0.0)}


def paired_comparison(champ_eval, chall_eval, alpha_per_look):
    """Pure precommitted paired test - shared by the evaluator and the
    independent full-decision replay (identical inputs -> identical stats)."""
    champ_cases = {r["case_id"]: r for r in champ_eval["per_case"] if not r["abstained"]}
    diffs = [r["nll"] - champ_cases[r["case_id"]]["nll"]
             for r in chall_eval["per_case"]
             if not r["abstained"] and r["case_id"] in champ_cases]
    core = paired_test_from_diffs(diffs, alpha_per_look)
    n, mean, sd = core["n"], core["mean"], core["sd"]
    t_stat, ci_upper, ci_lower = core["t_stat"], core["ci_upper"], core["ci_lower"]
    micro = lambda v: None if v is None else int(round(v * 1e6))
    return {
        "hypothesis": "H0: E[NLL_challenger - NLL_champion] >= 0 on the sealed suite",
        "test": "paired mean difference, one-sided normal (CLT), Bonferroni-allocated",
        "n_paired": n, "mean_diff_micro": micro(mean), "sd_micro": micro(sd),
        "t_statistic_micro": micro(t_stat), "ci_lower_micro": micro(ci_lower),
        "ci_upper_micro": micro(ci_upper),
        "alpha_per_look_micro": int(round(alpha_per_look * 1e6)),
        "stopping_rule": "fixed per-look level; run stops when budget exhausted",
        "decision_threshold": "one-sided upper confidence bound of mean diff < 0 AND n >= 30",
        "significant_improvement": core["significant_improvement"],
        "assumptions": "approx normality of mean via CLT; independence across cases",
        "failure_conditions": "heavy-tailed diffs at small n; cross-case dependence",
    }


class EvaluatorError(ValueError):
    """Raised on refused or failed evaluator requests. When a look was already
    charged before the failure, `charge_row_hash` carries the signed charge row
    so lineage can bind the consumed look."""

    def __init__(self, message: str, *, charge_row_hash: str | None = None,
                 terminal_status: str | None = None):
        super().__init__(message)
        self.charge_row_hash = charge_row_hash
        self.terminal_status = terminal_status


class _Timeout(Exception):
    pass


class SealedEvaluator:
    def __init__(self, *, tenant_id: str, run_id: str, secret: str,
                 secret_provenance: str = "test_fixture",
                 alpha_total: float = 0.05, max_looks: int = 20, suite_scale: int = 1,
                 timeout_s: float | None = None):
        if secret_provenance not in SECRET_PROVENANCES:
            raise EvaluatorError(f"unknown secret provenance {secret_provenance!r}")
        self.__secret = secret
        self.__secret_provenance = secret_provenance
        self.suite_scale = suite_scale
        self.timeout_s = timeout_s
        self.seed_commitment = commitment_for(secret, secret_provenance)
        self.__promotion = build_holdout_suite(stable_seed("promotion-holdout", secret) % (1 << 31),
                                               scale=suite_scale)
        self.__final = build_holdout_suite(stable_seed("final-audit-holdout", secret) % (1 << 31),
                                           scale=suite_scale)
        # Public commitments to the sealed content (hashes only, no rows):
        # published BEFORE any look so replay can prove the suites never moved.
        self.suite_commitments = {
            "promotion": suite_manifest(self.__promotion),
            "final": suite_manifest(self.__final),
        }
        private_key, public_key = generate_demo_keypair()
        self.__private = private_key
        self.public_key = public_key
        self.ledger = SignedChain(tenant_id=tenant_id, run_id=run_id,
                                  chain_id="evaluator-access", private_key=private_key,
                                  public_key=public_key)
        self.alpha_total = alpha_total
        self.max_looks = max_looks
        self.alpha_per_look = alpha_total / max_looks
        self.lifecycle = "INITIALIZED"
        self.__nonces: set[str] = set()
        self.__final_used = False

    # -- derived, never stored ------------------------------------------------
    def looks_spent(self) -> int:
        """Charged promotion looks — counts CHARGE rows, so failed, timed-out,
        rejected, and crashed-after-charge accesses all consume budget."""
        return sum(1 for r in self.ledger.rows if r["body"]["kind"] == "promotion_look_charge")

    def alpha_spent(self) -> float:
        return self.looks_spent() * self.alpha_per_look

    # -- lifecycle --------------------------------------------------------------
    def _require_active(self) -> None:
        if self.lifecycle in ("FINALIZED", "REVEALABLE"):
            raise EvaluatorError(f"lifecycle {self.lifecycle}: evaluator accepts no further looks")

    def _mark_evaluating(self) -> None:
        if self.lifecycle == "INITIALIZED":
            self.lifecycle = "EVALUATING"

    def finalize(self) -> dict[str, Any]:
        """Irreversibly close the evaluation phase. Appends a signed lifecycle
        row so the transition is part of the tamper-evident ledger."""
        if self.lifecycle in ("FINALIZED", "REVEALABLE"):
            raise EvaluatorError("lifecycle: already finalized (irreversible)")
        self.lifecycle = "FINALIZED"
        return self.ledger.append({
            "kind": "lifecycle",
            "event": "FINALIZED",
            "evaluator_version": EVALUATOR_VERSION,
            "looks_spent_at_finalize": self.looks_spent(),
        })

    # -- private scoring -------------------------------------------------------
    def __guarded_fn(self, fn):
        """Hand the candidate a deep copy of each compiled context: captures
        cost a charged look; mutations cannot poison the scored original."""
        def guarded(compiled: dict[str, Any]) -> dict[str, Any]:
            return fn(copy.deepcopy(compiled))
        return guarded

    def __paired_eval(self, config: dict[str, Any], registry: dict[str, Any],
                      fn_factory, suite) -> dict[str, Any]:
        return evaluate_candidate_on_suite(
            "sealed", suite, registry, fn=self.__guarded_fn(fn_factory(config)),
            k_max_override=config["selector.k_max"],
            min_score_override=config["selector.min_score_milli"] / 1000.0)

    def __run_with_timeout(self, fn):
        """Execute fn(); convert SIGALRM into _Timeout when a budget is set and
        we are on the main thread (signal limitation, documented)."""
        if not self.timeout_s or threading.current_thread() is not threading.main_thread():
            return fn()

        def _alarm(signum, frame):
            raise _Timeout()

        previous = signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, self.timeout_s)
        try:
            return fn()
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0.0)
            signal.signal(signal.SIGALRM, previous)

    def _charge(self, kind: str, binding: dict[str, Any]) -> dict[str, Any]:
        """Atomically reserve the look: the signed CHARGE row is appended to
        the append-only ledger BEFORE any candidate code executes."""
        row = self.ledger.append({
            "kind": kind,
            "evaluator_version": EVALUATOR_VERSION,
            "terminal_status": "CHARGED_PENDING",
            **binding,
        })
        self._mark_evaluating()
        return row

    def _settle(self, kind: str, charge_row: dict[str, Any], terminal_status: str,
                extra: dict[str, Any]) -> dict[str, Any]:
        assert terminal_status in TERMINAL_STATUSES
        return self.ledger.append({
            "kind": kind,
            "evaluator_version": EVALUATOR_VERSION,
            "charge_row_hash": charge_row["row_hash"],
            "look_index": charge_row["body"]["look_index"],
            "terminal_status": terminal_status,
            **extra,
        })

    def compare(self, *, champion_config: dict[str, Any], challenger_config: dict[str, Any],
                candidate_id: str, snapshot_id: str, registry: dict[str, Any],
                fn_factory, nonce: str) -> dict[str, Any]:
        """One charged look: paired sequential comparison on the sealed suite.

        Refusals BEFORE the charge (replayed nonce, exhausted budget, closed
        lifecycle) expose no sealed data and consume no look. Everything after
        the charge row lands — success, candidate exception, timeout, or
        malformed response — terminates in a linked RESULT row and consumes
        the look."""
        self._require_active()
        if nonce in self.__nonces:
            raise EvaluatorError("replayed nonce: one-shot requests only")
        self.__nonces.add(nonce)
        if self.looks_spent() >= self.max_looks:
            raise EvaluatorError("access budget exhausted")
        charge = self._charge("promotion_look_charge", {
            "candidate_id": candidate_id,
            "snapshot_id": snapshot_id,
            "nonce": nonce,
            "look_index": self.looks_spent() + 1,
        })
        try:
            champ = self.__run_with_timeout(
                lambda: self.__paired_eval(champion_config, registry, fn_factory, self.__promotion))
            chall = self.__run_with_timeout(
                lambda: self.__paired_eval(challenger_config, registry, fn_factory, self.__promotion))
        except _Timeout:
            self._settle("promotion_look_result", charge, "TIMED_OUT",
                         {"error_class": "Timeout", "candidate_id": candidate_id})
            raise EvaluatorError(f"candidate execution timed out; look {charge['body']['look_index']} consumed",
                                 charge_row_hash=charge["row_hash"], terminal_status="TIMED_OUT")
        except Exception as exc:
            self._settle("promotion_look_result", charge, "FAILED",
                         {"error_class": type(exc).__name__, "candidate_id": candidate_id})
            raise EvaluatorError(f"candidate execution failed ({type(exc).__name__}); "
                                 f"look {charge['body']['look_index']} consumed",
                                 charge_row_hash=charge["row_hash"], terminal_status="FAILED")
        statistics = paired_comparison(champ, chall, self.alpha_per_look)
        statistics["alpha_spent_after_micro"] = int(round(self.looks_spent() * self.alpha_per_look * 1e6))
        statistics["alpha_total_micro"] = int(round(self.alpha_total * 1e6))
        body_extra = {
            "candidate_id": candidate_id,
            "snapshot_id": snapshot_id,
            "nonce": nonce,
            "statistics": statistics,
            "challenger_aggregates": {
                "metrics": chall["metrics"],
                "scored_count": chall["scored_count"],
                "abstentions_standard": chall["abstentions_standard"],
                "abstentions_probe": chall["abstentions_probe"],
                "probe_count": chall["probe_count"],
            },
            "champion_aggregates": {
                "metrics": champ["metrics"],
                "scored_count": champ["scored_count"],
            },
        }
        try:
            self._validate_response_shape(body_extra)
        except Exception as exc:
            self._settle("promotion_look_result", charge, "REJECTED",
                         {"error_class": type(exc).__name__, "candidate_id": candidate_id})
            raise EvaluatorError(f"malformed evaluator response ({exc}); "
                                 f"look {charge['body']['look_index']} consumed",
                                 charge_row_hash=charge["row_hash"], terminal_status="REJECTED")
        return self._settle("promotion_look_result", charge, "SUCCEEDED", body_extra)

    @staticmethod
    def _validate_response_shape(body: dict[str, Any]) -> None:
        stats = body["statistics"]
        for field in ("hypothesis", "n_paired", "t_statistic_micro", "ci_upper_micro",
                      "alpha_per_look_micro", "alpha_spent_after_micro", "significant_improvement"):
            if field not in stats:
                raise ValueError(f"statistics missing {field}")
        for agg_key in ("challenger_aggregates", "champion_aggregates"):
            if body[agg_key].get("scored_count") is None:
                raise ValueError(f"{agg_key} missing scored_count")

    def final_audit(self, *, config: dict[str, Any], champion_id: str,
                    registry: dict[str, Any], fn_factory, nonce: str) -> dict[str, Any]:
        self._require_active()
        if self.__final_used:
            raise EvaluatorError("final audit holdout is strictly one-shot")
        if nonce in self.__nonces:
            raise EvaluatorError("replayed nonce: one-shot requests only")
        self.__nonces.add(nonce)
        # one-shot is consumed at CHARGE time: a failed final audit is spent.
        self.__final_used = True
        charge = self._charge("final_audit_charge", {
            "champion_id": champion_id, "nonce": nonce, "look_index": 1,
        })
        try:
            evaluation = self.__run_with_timeout(
                lambda: self.__paired_eval(config, registry, fn_factory, self.__final))
        except _Timeout:
            self._settle("final_audit_result", charge, "TIMED_OUT",
                         {"error_class": "Timeout", "champion_id": champion_id})
            raise EvaluatorError("final audit timed out; one-shot consumed",
                                 charge_row_hash=charge["row_hash"], terminal_status="TIMED_OUT")
        except Exception as exc:
            self._settle("final_audit_result", charge, "FAILED",
                         {"error_class": type(exc).__name__, "champion_id": champion_id})
            raise EvaluatorError(f"final audit failed ({type(exc).__name__}); one-shot consumed",
                                 charge_row_hash=charge["row_hash"], terminal_status="FAILED")
        return self._settle("final_audit_result", charge, "SUCCEEDED", {
            "champion_id": champion_id,
            "aggregates": {
                "metrics": evaluation["metrics"],
                "scored_count": evaluation["scored_count"],
                "abstentions_standard": evaluation["abstentions_standard"],
                "probes_refused": evaluation["abstentions_probe"] == evaluation["probe_count"],
            },
        })

    def reveal_for_replay(self) -> dict[str, Any]:
        """Commit-reveal disclosure. HARD-FAILS before FINALIZED: the secret
        (and with it the ability to rebuild the sealed suites) does not exist
        outside this boundary until the evaluation phase is irreversibly
        closed."""
        if self.lifecycle not in ("FINALIZED", "REVEALABLE"):
            raise EvaluatorError(
                f"lifecycle {self.lifecycle}: reveal refused before FINALIZED "
                "(sealed suites must not be reconstructable while looks remain possible)")
        self.lifecycle = "REVEALABLE"
        return {"evaluator_secret": self.__secret,
                "secret_provenance": self.__secret_provenance,
                "seed_commitment": self.seed_commitment,
                "lifecycle_at_reveal": self.lifecycle,
                "suite_scale": self.suite_scale,
                "evaluator_version": EVALUATOR_VERSION,
                "suite_commitments": self.suite_commitments,
                "note": "verify sha256(canonical({'evaluator_secret','secret_provenance'})) == seed_commitment; "
                        "rebuild suites via stable_seed('promotion-holdout'|'final-audit-holdout', secret) % 2^31"}
