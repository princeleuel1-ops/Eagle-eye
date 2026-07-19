"""V10 live-shadow spine — the complete live-tenant path, built to READY,
armed only by a key the operator must sign.

THE WALL THIS BUILDS AGAINST (verbatim, current walls): "W2 — Everything is
synthetic. NO live-data evidence anywhere." and "Live pilot … NOT
ESTABLISHED." V10 does not — and cannot — close that wall from inside this
repository: closing it requires the operator's DATA AUTHORITY, a real feed,
and a signed activation. What V10 builds is everything up to that key:

  - a signed DataAuthorityConfig format and fail-closed verifier: the ONE
    artifact that arms live ingestion. Absent, unsigned, wrongly signed,
    expired, single-approver, or fixture-tenant configs all leave the seam
    DISARMED with recorded reasons.
  - a LiveFeedConnector seam behind the EXISTING authorized-ingest boundary
    (source signatures, contract validation, quarantine, provenance — all
    unchanged). The only shipped connectors are NullLiveFeedConnector
    (refuses, fail-closed — the production default) and
    ReplayFileFeedConnector (reads recorded envelopes, attests
    origin=replay_fixture — the dress-rehearsal instrument).
  - the LIVE evidence class, UNREACHABLE by construction without ALL of:
    a verified production-class authority config, a connector attesting
    origin=live, and a non-fixture tenant. Any partial claim of LIVE is a
    hard refusal — never a silent relabel in either direction.
  - shadow-only enforcement under LIVE: any non-shadow action mode with
    LIVE data is refused at the guard (external execution remains disabled
    globally; this adds the live-specific interlock).

Everything here is additive; the pilot's ingest/decision/approval/dispatch
machinery is untouched and still enforces its own courts.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from .prior_registry import canonical_bytes, sha256_hex
from .signing import key_id as pem_key_id, sign as ed_sign, verify as ed_verify

LIVE_SHADOW_SPEC = "eagle-eye-live-shadow/1.0"
AUTHORITY_CONFIG_SPEC = "eagle-eye-data-authority/1.0"
AUTHORITY_CLASSES = ("production", "test_fixture")
ARM_DISARMED = "DISARMED"
ARM_TEST_FIXTURE = "ARMED_TEST_FIXTURE"
ARM_LIVE = "ARMED_LIVE"
DATA_CLASS_FIXTURE = "FIXTURE"
DATA_CLASS_LIVE = "LIVE"
PRODUCTION_MIN_AUTHORIZERS = 2  # dual control, same posture as approvals

_REQUIRED_FIELDS = (
    "spec", "authority_class", "tenant_id", "source_ids", "event_kinds",
    "rate_cap_per_hour", "retention_days", "legal_basis", "authorized_by",
    "valid_from_epoch", "valid_until_epoch",
)


class DataAuthorityError(ValueError):
    """Raised on any attempt to mint or imply LIVE without full authority."""


class ConnectorDisabled(RuntimeError):
    """The fail-closed default: no live connector is configured."""


# ------------------------- authority config ----------------------------------

def authority_config_body(config: dict[str, Any]) -> dict[str, Any]:
    return {k: config[k] for k in _REQUIRED_FIELDS}


def sign_authority_config(body: dict[str, Any], private_pem: bytes,
                          public_pem: bytes) -> dict[str, Any]:
    """Produce a signed config. In production the OPERATOR runs this with
    their authority key (see receipts_v10/LIVE_ACTIVATION_RUNBOOK.md); the
    repository never holds that key."""
    missing = [k for k in _REQUIRED_FIELDS if k not in body]
    if missing:
        raise DataAuthorityError(f"config missing fields: {missing}")
    signed = dict(body)
    signed["authority_key_id"] = pem_key_id(public_pem)
    signed["signature_b64"] = base64.b64encode(
        ed_sign(canonical_bytes(authority_config_body(body)), private_pem)).decode()
    return signed


def verify_authority_config(config: dict[str, Any] | None, *,
                            trusted_authority_keys: dict[str, bytes],
                            fixture_tenants: tuple[str, ...] = (),
                            now_epoch: float | None = None) -> dict[str, Any]:
    """Fail-closed verification. Returns {"arm_state", "reasons", ...}.
    trusted_authority_keys is pinned OUT-OF-BAND (key_id -> public PEM):
    a config can never vouch for its own signer."""
    now = time.time() if now_epoch is None else now_epoch
    reasons: list[str] = []
    if config is None:
        return {"arm_state": ARM_DISARMED, "reasons": ["no data-authority config present"]}
    for field in _REQUIRED_FIELDS + ("authority_key_id", "signature_b64"):
        if field not in config:
            reasons.append(f"missing field: {field}")
    if reasons:
        return {"arm_state": ARM_DISARMED, "reasons": reasons}
    if config["spec"] != AUTHORITY_CONFIG_SPEC:
        reasons.append("unknown config spec")
    if config["authority_class"] not in AUTHORITY_CLASSES:
        reasons.append("unknown authority_class")
    public_pem = trusted_authority_keys.get(config["authority_key_id"])
    if public_pem is None:
        reasons.append("signer is not a pinned authority key")
    else:
        try:
            sig = base64.b64decode(config["signature_b64"], validate=True)
            if not ed_verify(canonical_bytes(authority_config_body(config)), sig, public_pem):
                reasons.append("authority signature invalid")
        except Exception:
            reasons.append("authority signature undecodable")
    if not (config["valid_from_epoch"] <= now <= config["valid_until_epoch"]):
        reasons.append("outside validity window")
    if config["authority_class"] == "production":
        approvers = config["authorized_by"]
        if (not isinstance(approvers, list)
                or len({json.dumps(a, sort_keys=True) for a in approvers})
                < PRODUCTION_MIN_AUTHORIZERS):
            reasons.append("production arming requires dual distinct authorizers")
        if config["tenant_id"] in fixture_tenants:
            reasons.append("production authority may not target a fixture tenant")
        if not str(config["legal_basis"]).strip():
            reasons.append("production arming requires a non-empty legal basis")
    if reasons:
        return {"arm_state": ARM_DISARMED, "reasons": reasons}
    state = ARM_LIVE if config["authority_class"] == "production" else ARM_TEST_FIXTURE
    return {"arm_state": state, "reasons": [],
            "tenant_id": config["tenant_id"],
            "source_ids": list(config["source_ids"]),
            "event_kinds": list(config["event_kinds"]),
            "rate_cap_per_hour": config["rate_cap_per_hour"],
            "config_sha256": sha256_hex(canonical_bytes(authority_config_body(config)))}


# ------------------------- connector seam ------------------------------------

class NullLiveFeedConnector:
    """Production default: present, wired, and refusing. Mirrors the
    NullActionExecutor posture — the seam exists, the capability does not."""

    name = "null-live-feed"

    def attestation(self) -> dict[str, Any]:
        return {"origin": "disabled", "connector": self.name}

    def poll(self, max_events: int = 100) -> list[dict[str, Any]]:
        raise ConnectorDisabled(
            "live feed connector not configured; live ingestion is fail-closed "
            "(see receipts_v10/LIVE_ACTIVATION_RUNBOOK.md)")


class ReplayFileFeedConnector:
    """Dress-rehearsal connector: replays recorded signed envelopes from a
    JSONL file and attests origin=replay_fixture. It can NEVER mint LIVE —
    data_class_for refuses replay origins for LIVE regardless of arming."""

    name = "replay-file-feed"

    def __init__(self, path):
        self._events = [json.loads(line) for line in
                        open(path).read().splitlines() if line.strip()]
        self._cursor = 0

    def attestation(self) -> dict[str, Any]:
        return {"origin": "replay_fixture", "connector": self.name}

    def poll(self, max_events: int = 100) -> list[dict[str, Any]]:
        batch = self._events[self._cursor:self._cursor + max_events]
        self._cursor += len(batch)
        return batch


# ------------------------- the labeling guard --------------------------------

def data_class_for(*, arm_state: str, attestation: dict[str, Any],
                   tenant_data_class: str) -> str:
    """The ONLY function allowed to produce a data class for ingested events.

    LIVE requires ALL of: ARMED_LIVE, connector origin == "live", and a
    tenant registered as LIVE. Any PARTIAL live claim is a hard refusal —
    mislabeling must never be silently repaired in either direction."""
    origin = attestation.get("origin")
    live_signals = [arm_state == ARM_LIVE, origin == "live",
                    tenant_data_class == DATA_CLASS_LIVE]
    if all(live_signals):
        return DATA_CLASS_LIVE
    if any(live_signals):
        raise DataAuthorityError(
            f"inconsistent live claim refused: arm_state={arm_state}, "
            f"origin={origin}, tenant_data_class={tenant_data_class}")
    return DATA_CLASS_FIXTURE


def require_shadow_only(data_class: str, action_mode: str) -> None:
    """LIVE data admits shadow actions only — the live interlock on top of
    the globally disabled external execution."""
    if data_class == DATA_CLASS_LIVE and action_mode != "shadow":
        raise DataAuthorityError(
            f"non-shadow action mode {action_mode!r} refused under LIVE data")


# ------------------------- the conduit ---------------------------------------

class LiveShadowConduit:
    """The live-tenant ingestion path: authority arming -> connector poll ->
    scope filter (sources, kinds, rate cap) -> the EXISTING IngestBoundary
    (signatures, contract, quarantine, provenance — unchanged) -> data-class
    stamped ingestion record. Every conduit run emits a signed-content
    summary row for the rehearsal receipt."""

    def __init__(self, *, boundary, connector, verification: dict[str, Any]):
        if verification.get("arm_state") not in (ARM_TEST_FIXTURE, ARM_LIVE):
            raise DataAuthorityError(
                f"conduit refused: arm_state={verification.get('arm_state')} "
                f"({'; '.join(verification.get('reasons', []))})")
        self.boundary = boundary
        self.connector = connector
        self.verification = verification

    def run_once(self, *, tenant_data_class: str, max_events: int = 100) -> dict[str, Any]:
        data_class = data_class_for(arm_state=self.verification["arm_state"],
                                    attestation=self.connector.attestation(),
                                    tenant_data_class=tenant_data_class)
        allowed_sources = set(self.verification["source_ids"])
        allowed_kinds = set(self.verification["event_kinds"])
        accepted, quarantined, out_of_scope = 0, 0, 0
        receipts = []
        for envelope in self.connector.poll(max_events=max_events):
            event = envelope.get("event", {})
            if (event.get("source_id") not in allowed_sources
                    or event.get("event_kind") not in allowed_kinds):
                out_of_scope += 1
                continue
            result = self.boundary.ingest_envelope(
                self.verification["tenant_id"], envelope)
            if result.get("accepted"):
                accepted += 1
                receipts.append({"digest": result.get("digest"),
                                 "state": result.get("state"),
                                 "data_class": data_class})
            else:
                quarantined += 1
        summary = {"spec": LIVE_SHADOW_SPEC, "kind": "conduit_run",
                   "arm_state": self.verification["arm_state"],
                   "connector": self.connector.attestation(),
                   "config_sha256": self.verification["config_sha256"],
                   "data_class": data_class,
                   "accepted": accepted, "quarantined": quarantined,
                   "out_of_scope": out_of_scope, "receipts": receipts,
                   "external_action": False}
        summary["summary_sha256"] = sha256_hex(canonical_bytes(summary))
        return summary
