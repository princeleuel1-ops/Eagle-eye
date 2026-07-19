"""Outcome resolution: bind realized outcomes to committed predictions,
score immutably, and gate registry growth. Append-only, hash-chained.

Off-policy honesty: recording a propensity does NOT make an outcome unbiased
causal evidence. Identifiability is tested explicitly; failures are labeled
OFF_POLICY_EFFECT_NOT_IDENTIFIABLE and the outcome is retained for predictive
monitoring only.
"""

from __future__ import annotations

import math
from typing import Any

from .predictors import LogScaleDist
from .prior_registry import SCHEMA_VERSION, canonical_bytes, sha256_hex

RESOLUTION_SPEC = "eagle-eye-outcome-resolution/1.0"
GENESIS = "0" * 64
PROPENSITY_FLOOR = 0.05
MIN_ESS = 5.0


class ResolutionError(ValueError):
    """Fail-closed rejection of an invalid resolution."""


def _hash(value: Any) -> str:
    return sha256_hex(canonical_bytes(value))


class PredictionLedger:
    """Append-only store of committed predictions and resolved outcomes."""

    def __init__(self, tenant_id: str, *, policy_registry: dict[str, Any] | None = None,
                 signer_keys: tuple[bytes, bytes] | None = None, run_id: str = "run-ledger"):
        self.tenant_id = tenant_id
        self.predictions: dict[str, dict[str, Any]] = {}
        self.resolutions: list[dict[str, Any]] = []
        self.head = GENESIS
        # Authenticated logged-policy records (audit blocker 6): propensities
        # are RECOMPUTED from these records, never trusted from the caller.
        self.policy_registry = policy_registry or {}
        self.signed = None
        if signer_keys is not None:
            from .signed_chain import SignedChain
            private_key, public_key = signer_keys
            self.signed = SignedChain(tenant_id=tenant_id, run_id=run_id,
                                      chain_id="outcome-resolutions",
                                      private_key=private_key, public_key=public_key)

    # -- commitment ---------------------------------------------------------

    def commit_prediction(self, pi_block: dict[str, Any], *, champion_id: str,
                          policy_release_hash: str, resource_scope: str) -> dict[str, Any]:
        if pi_block["tenant_id"] != self.tenant_id:
            raise ResolutionError("tenant boundary: prediction belongs to another tenant")
        if pi_block["abstained"]:
            raise ResolutionError("abstained predictions carry no distribution to resolve against")
        receipt_hash = _hash(pi_block)
        prediction_id = f"pred-{receipt_hash[:12]}"
        if prediction_id in self.predictions:
            raise ResolutionError(f"duplicate prediction commitment {prediction_id}")
        record = {
            "prediction_id": prediction_id,
            "prediction_receipt_hash": receipt_hash,
            "prediction_distribution_hash": pi_block["predictive_distribution_commitment"],
            "policy_release_hash": policy_release_hash,
            "model_or_champion_id": champion_id,
            "task_id": pi_block["case_id"],
            "tenant_id": pi_block["tenant_id"],
            "resource_scope": resource_scope,
            "prediction_as_of": pi_block["as_of_cutoff"],
            "block": pi_block,
        }
        self.predictions[prediction_id] = record
        return {key: value for key, value in record.items() if key != "block"}

    # -- scoring helpers ----------------------------------------------------

    @staticmethod
    def _dist_for(block: dict[str, Any], intervention: str) -> LogScaleDist:
        payload = block["interventions"][intervention]["delay"]
        return LogScaleDist(payload["loc"], payload["scale"], payload["df"])

    # -- resolution ---------------------------------------------------------

    def resolve(self, resolution: dict[str, Any]) -> dict[str, Any]:
        """Validate, score against the committed distribution, chain, append."""
        pred = self.predictions.get(resolution.get("prediction_id", ""))
        if pred is None:
            raise ResolutionError("outcome references no committed prediction")
        if resolution.get("tenant_id") != pred["tenant_id"] or resolution.get("tenant_id") != self.tenant_id:
            raise ResolutionError("tenant boundary: cross-tenant resolution refused")
        if resolution.get("resource_scope") != pred["resource_scope"]:
            raise ResolutionError("resource scope mismatch")
        if resolution.get("policy_release_hash") != pred["policy_release_hash"]:
            raise ResolutionError("policy release mismatch")
        # Immutability: the referenced prediction must hash to its commitment.
        if _hash(pred["block"]) != pred["prediction_receipt_hash"]:
            raise ResolutionError("prediction content changed after commitment")
        if resolution.get("prediction_distribution_hash") != pred["prediction_distribution_hash"]:
            raise ResolutionError("tampered distribution hash")
        observed_at = resolution.get("outcome_observed_at", "")
        if observed_at <= pred["prediction_as_of"]:
            raise ResolutionError("outcome timestamp predates or equals prediction as-of")
        forbidden = set(resolution.get("features_used", [])) & {"post_outcome", "future"}
        if forbidden:
            raise ResolutionError("leakage: post-outcome features in resolution context")
        prior = [r for r in self.resolutions if r["prediction_id"] == pred["prediction_id"]
                 and r["resolution_status"] in ("RESOLVED", "REVISED")]
        status = resolution.get("resolution_status", "RESOLVED")
        if prior and status == "RESOLVED":
            raise ResolutionError("duplicate outcome: prediction already resolved (submit REVISED)")
        if status == "REVISED" and not prior:
            raise ResolutionError("revision without an original resolution")

        intervention_taken = resolution.get("intervention_taken")  # str | None(unknown)
        recommended = pred["block"]["recommendation"]["recommended_intervention"]
        if intervention_taken is None:
            intervention_status = "unknown_intervention"
            score_channel = "wait_incumbent"
        elif intervention_taken == "wait_incumbent":
            intervention_status = "intervention_free"
            score_channel = "wait_incumbent"
        else:
            intervention_status = "intervention_affected"
            score_channel = intervention_taken

        outcome_value = resolution.get("outcome_value")  # log_final_delay (float) or None
        if outcome_value is None and status not in ("MISSING", "DISPUTED"):
            raise ResolutionError("missing outcome_value requires MISSING or DISPUTED status")

        score = None
        if outcome_value is not None:
            dist = self._dist_for(pred["block"], score_channel)
            lo, hi = dist.ppf(0.10), dist.ppf(0.90)
            score = {
                "scoring_rule": "log_score+crps+cover80(log-delay)",
                "channel": score_channel,
                "nll": round(-dist.logpdf(outcome_value), 6),
                "crps": round(dist.crps(outcome_value), 6),
                "covered80": bool(lo <= outcome_value <= hi),
                "pit": round(dist.cdf(outcome_value), 6),
            }

        source_payload = resolution.get("outcome_source_payload")
        claimed_source_hash = resolution.get("outcome_source_hash")
        if source_payload is not None:
            recomputed_source = _hash(source_payload)
            if claimed_source_hash is not None and claimed_source_hash != recomputed_source:
                raise ResolutionError("outcome source hash mismatch (source payload does not hash to claim)")
            claimed_source_hash = recomputed_source
        off_policy = self._off_policy_identifiability(resolution, intervention_status, recommended)
        eligible, reason = self._registry_eligibility(status, intervention_status, off_policy, outcome_value)

        row = {
            "spec": RESOLUTION_SPEC,
            "prediction_id": pred["prediction_id"],
            "prediction_receipt_hash": pred["prediction_receipt_hash"],
            "prediction_distribution_hash": pred["prediction_distribution_hash"],
            "policy_release_hash": pred["policy_release_hash"],
            "model_or_champion_id": pred["model_or_champion_id"],
            "task_id": pred["task_id"],
            "tenant_id": pred["tenant_id"],
            "resource_scope": pred["resource_scope"],
            "prediction_as_of": pred["prediction_as_of"],
            "outcome_observed_at": observed_at,
            "outcome_value_micro": None if outcome_value is None else math.floor(outcome_value * 1_000_000 + 0.5),
            "outcome_source": resolution.get("outcome_source", "unspecified"),
            "outcome_source_hash": claimed_source_hash or _hash(resolution.get("outcome_source", "")),
            "observed": {
                # observed outcome fields; ABSENT fields stay None, never defaulted
                "final_delay_days": (resolution.get("observed") or {}).get("final_delay_days"),
                "stockout": (resolution.get("observed") or {}).get("stockout"),
                "recovery_days": (resolution.get("observed") or {}).get("recovery_days"),
                "exposure_usd": (resolution.get("observed") or {}).get("exposure_usd"),
                "intervention_result": (resolution.get("observed") or {}).get("intervention_result"),
            },
            "entity_refs": resolution.get("entity_refs") or {},
            "confounders": {"schema_version": (resolution.get("confounders") or {}).get("schema_version"),
                             "vector": (resolution.get("confounders") or {}).get("vector")},
            "missingness_state": resolution.get("missingness_state", "complete"),
            "censoring_state": resolution.get("censoring_state", "uncensored"),
            "authorization_receipt": resolution.get("authorization_receipt"),
            "intervention_recommended": recommended,
            "intervention_taken": intervention_taken,
            "intervention_status": intervention_status,
            "acting_policy": resolution.get("acting_policy", "unspecified"),
            "recommendation_propensity_micro": (
                None if resolution.get("recommendation_propensity") is None
                else math.floor(resolution["recommendation_propensity"] * 1_000_000 + 0.5)),
            "propensity_provenance": resolution.get("propensity_provenance", "absent"),
            "resolution_status": status,
            "revision_of": prior[-1]["current_audit_hash"] if status == "REVISED" and prior else None,
            "score": score,
            "off_policy": off_policy,
            "eligibility_for_registry": eligible,
            "eligibility_reason": reason,
            "previous_audit_hash": self.head,
        }
        row["current_audit_hash"] = _hash(row)
        self.resolutions.append(row)
        self.head = row["current_audit_hash"]
        if self.signed is not None:
            signed_row = self.signed.append({"kind": "outcome_resolution",
                                             "resolution_hash": row["current_audit_hash"],
                                             "prediction_id": row["prediction_id"]})
            row["signed_row_hash"] = signed_row["row_hash"]
        return row

    # -- honesty gates ------------------------------------------------------

    def _off_policy_identifiability(self, resolution: dict[str, Any], intervention_status: str,
                                    recommended: str) -> dict[str, Any]:
        """Measured identifiability (audit blocker 6): propensity is RECOMPUTED
        from the authenticated logged-policy record; overlap, effective sample
        size, and weight concentration come from the ACCUMULATED ledger, not
        from caller-supplied booleans. States: LOGGED -> CHECKED ->
        IDENTIFIABLE_UNDER_STATED_ASSUMPTIONS | NOT_IDENTIFIABLE."""
        policy = self.policy_registry.get(resolution.get("acting_policy", ""))
        taken = resolution.get("intervention_taken")
        logged = policy is not None and policy.get("authenticated") is True
        recomputed = None
        if logged and taken is not None:
            follow = policy["follow_prob"]
            recomputed = follow if taken == recommended else (1.0 - follow)
        claimed = resolution.get("recommendation_propensity")
        checked = (logged and recomputed is not None and claimed is not None
                   and abs(claimed - recomputed) < 1e-9)
        forged = (claimed is not None and recomputed is not None
                  and abs(claimed - recomputed) >= 1e-9)
        # Accumulated-ledger diagnostics from ACTUAL inverse-propensity weights
        prior_props = [r["recommendation_propensity_micro"] / 1e6
                       for r in self.resolutions
                       if r.get("recommendation_propensity_micro")
                       and r["off_policy"].get("state") != "NOT_IDENTIFIABLE"]
        props = prior_props + ([recomputed] if recomputed else [])
        weights = [1.0 / p for p in props if p and p > 0]
        ess = (sum(weights) ** 2 / sum(w * w for w in weights)) if weights else 0.0
        concentration = (max(weights) / sum(weights)) if weights else 1.0
        overlap = bool(recomputed is not None
                       and PROPENSITY_FLOOR <= recomputed <= 1.0 - PROPENSITY_FLOOR)
        confounders = resolution.get("confounders", {})
        confounders_ok = bool(confounders.get("vector")) and bool(confounders.get("schema_version"))
        checks = {
            "policy_record_logged": logged,
            "propensity_recomputed_matches_claim": checked,
            "caller_propensity_forged": forged,
            "positivity_overlap": overlap,
            "action_not_deterministic": bool(recomputed is not None and 0.0 < recomputed < 1.0),
            "confounder_vector_present": confounders_ok,
            "effective_sample_size": round(ess, 3),
            "effective_sample_size_sufficient": ess >= MIN_ESS,
            "weight_concentration": round(concentration, 6),
            "support_violation": recomputed is None,
        }
        if not logged:
            state = "NOT_IDENTIFIABLE"
        elif forged:
            state = "NOT_IDENTIFIABLE"
        elif not checked:
            state = "LOGGED"
        elif (overlap and checks["action_not_deterministic"] and confounders_ok
              and ess >= MIN_ESS and intervention_status != "unknown_intervention"):
            state = "IDENTIFIABLE_UNDER_STATED_ASSUMPTIONS"
        else:
            state = "CHECKED"
        usable = ("causal_effect_estimation_under_stated_assumptions"
                  if state == "IDENTIFIABLE_UNDER_STATED_ASSUMPTIONS"
                  else "predictive_monitoring_only")
        return {
            "checks": checks,
            "recomputed_propensity_micro": None if recomputed is None else int(round(recomputed * 1e6)),
            "state": state,
            "usable_for": usable,
            "sensitivity_to_unobserved_confounding": "NOT_ESTABLISHED (no sensitivity model implemented; do not treat effects as robust to unobserved confounders)",
        }

    @staticmethod
    def _registry_eligibility(status: str, intervention_status: str,
                              off_policy: dict[str, Any], outcome_value: float | None) -> tuple[bool, str]:
        if status in ("MISSING", "DISPUTED"):
            return False, f"visible_but_ineligible:{status.lower()}_outcome"
        if status == "LATE":
            return False, "visible_but_ineligible:late_outcome_pending_review"
        if outcome_value is None:
            return False, "visible_but_ineligible:no_outcome_value"
        if intervention_status == "unknown_intervention":
            return False, "visible_but_ineligible:unknown_intervention_status"
        if intervention_status == "intervention_affected" and \
                off_policy["state"] != "IDENTIFIABLE_UNDER_STATED_ASSUMPTIONS":
            return False, "visible_but_ineligible:intervention_affected_and_not_identifiable"
        return True, "eligible:" + intervention_status

    # -- chain verification & registry growth --------------------------------

    def verify_chain(self) -> bool:
        head = GENESIS
        for row in self.resolutions:
            body = {key: value for key, value in row.items()
                    if key not in ("current_audit_hash", "signed_row_hash")}
            if row["previous_audit_hash"] != head or _hash(body) != row["current_audit_hash"]:
                return False
            head = row["current_audit_hash"]
        return head == self.head

    def grow_registry_task(self, row: dict[str, Any]) -> dict[str, Any]:
        """Convert an eligible resolution into a prior task — STRICT (audit A).

        Fails closed unless the row is present in this ledger's verified chain.
        Every field comes from the recorded resolution; unknown observed fields
        remain None and are NEVER replaced by defaults. Downstream estimators
        exclude None fields (see predictors._stockout_rates)."""
        if not row["eligibility_for_registry"]:
            raise ResolutionError(f"resolution not eligible for registry: {row['eligibility_reason']}")
        if not any(r is row or r["current_audit_hash"] == row["current_audit_hash"]
                   for r in self.resolutions):
            raise ResolutionError("registry growth refused: resolution not present in this ledger")
        if not self.verify_chain():
            raise ResolutionError("registry growth refused: resolution chain does not verify")
        pred = self.predictions[row["prediction_id"]]
        return build_grown_task(pred["block"], row)


def build_grown_task(target: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """Pure grown-task construction from (committed prediction block,
    resolution row) — shared verbatim by the ledger (after its fail-closed
    chain checks) and by the independent full-decision replay, so a recorded
    grown task is bit-for-bit recomputable from the replay bundle."""
    y = row["outcome_value_micro"] / 1_000_000
    observed = row["observed"]
    entity = dict(row["entity_refs"]) if row["entity_refs"] else {}
    entity.setdefault("supplier_id", None)
    entity.setdefault("component_id", None)
    entity.setdefault("lane", None)
    entity.setdefault("region", None)
    # exposure_rate only if actually recorded; None otherwise (no 9000 default)
    entity.setdefault("exposure_rate_per_day_usd", None)
    sel = target["selection_receipt"]
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": f"pt-resolved-{row['current_audit_hash'][:12]}",
        "tenant_id": row["tenant_id"],
        "disruption_class": target["disruption_class"],
        "as_of_start": row["prediction_as_of"],
        "as_of_end": row["outcome_observed_at"],
        "entity_refs": entity,
        "observations": [],
        "intervention": {"id": row["intervention_taken"], "applied": True,
                          "recommended": row["intervention_recommended"],
                          "logged_propensity_micro": row["recommendation_propensity_micro"]},
        "realized": {
            "final_delay_days": observed["final_delay_days"],
            "log_final_delay": round(y, 6),
            "stockout": observed["stockout"],
            "exposure_usd": observed["exposure_usd"],
            "recovery_days": observed["recovery_days"],
            "intervention_success": observed["intervention_result"],
        },
        "missingness_state": row["missingness_state"],
        "censoring_state": row["censoring_state"],
        "sources": [{"id": f"src-resolution-{row['current_audit_hash'][:12]}",
                      "kind": "resolved_outcome",
                      "resolution_hash": row["current_audit_hash"],
                      "prediction_id": row["prediction_id"],
                      "prediction_receipt_hash": row["prediction_receipt_hash"],
                      "outcome_source_hash": row["outcome_source_hash"],
                      "acting_policy": row["acting_policy"],
                      "confounder_schema_version": row["confounders"]["schema_version"],
                      "authorization_receipt": row["authorization_receipt"],
                      "selection_receipt_sha256": sel["receipt_sha256"]}],
        "eligibility": {"status": "closed", "quality": "resolved_outcome",
                         "off_policy_state": row["off_policy"]["state"]},
    }
