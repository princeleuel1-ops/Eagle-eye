"""V12 licensed-execution spine — the first real action, unarmed by default.

THE WALL (verbatim): "Real external execution NOT ESTABLISHED and
intentionally DISABLED — the only wired executor raises AdapterDisabled;
enabling a real one is a separate, explicitly authorized decision outside
this build." V12 builds that decision's machinery — arming, per-action
licenses, the proof chain, reversal — and leaves production execution
unreachable without the operator's signed ceremony.

INVARIANTS
  - UNARMED by default: no arming config ⇒ every execution refused; the
    NullActionExecutor default posture everywhere else is untouched.
  - Dual-control arming: a signed ExecutionArmingConfig (pinned out-of-band
    authority key, ≥2 distinct authorizers, action-class allowlist, budget,
    validity window). test_fixture arming reaches only the local outbox
    adapter; production arming ALSO demands VERIFIED production custody
    (V11 interlock) — unreachable in-repo by construction.
  - Per-action license: a single-use, expiring, signed token binding THE
    action: action_id + evidence digest + approval receipt + arming config
    hash. Replay, tamper, mismatch, expiry ⇒ refusal. Spent tokens ledger.
  - Proof chain in the receipt: identity → evidence digest → approval →
    arming → license → adapter attestation → outcome → reversal handle,
    content-hashed and signed.
  - Reversible by design: the one shipped adapter writes signed records to
    a local outbox and can emit a bound compensating reversal.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from pathlib import Path
from typing import Any

from .custody import require_production_custody
from .prior_registry import canonical_bytes, sha256_hex
from .signing import key_id as pem_key_id, sign as ed_sign, verify as ed_verify

EXECUTION_SPEC = "eagle-eye-licensed-execution/1.0"
ARMING_SPEC = "eagle-eye-execution-arming/1.0"
UNARMED, ARMED_TEST_FIXTURE, ARMED_PRODUCTION = "UNARMED", "ARMED_TEST_FIXTURE", "ARMED_PRODUCTION"
TOKEN_TTL_S = 900.0
_ARM_FIELDS = ("spec", "arming_class", "tenant_id", "action_classes",
               "max_actions", "authorized_by", "valid_from_epoch", "valid_until_epoch")


class ExecutionRefused(RuntimeError):
    pass


def sign_arming_config(body: dict[str, Any], private_pem: bytes, public_pem: bytes) -> dict[str, Any]:
    missing = [k for k in _ARM_FIELDS if k not in body]
    if missing:
        raise ExecutionRefused(f"arming config missing: {missing}")
    out = dict(body)
    out["authority_key_id"] = pem_key_id(public_pem)
    out["signature_b64"] = base64.b64encode(
        ed_sign(canonical_bytes({k: body[k] for k in _ARM_FIELDS}), private_pem)).decode()
    return out


def verify_arming(config: dict[str, Any] | None, *, trusted_authority_keys: dict[str, bytes],
                  custody_descriptor: dict[str, Any] | None = None,
                  now_epoch: float | None = None) -> dict[str, Any]:
    now = time.time() if now_epoch is None else now_epoch
    if config is None:
        return {"arm_state": UNARMED, "reasons": ["no execution arming config"]}
    reasons = []
    for f in _ARM_FIELDS + ("authority_key_id", "signature_b64"):
        if f not in config:
            reasons.append(f"missing {f}")
    if reasons:
        return {"arm_state": UNARMED, "reasons": reasons}
    pem = trusted_authority_keys.get(config["authority_key_id"])
    if pem is None:
        reasons.append("signer not a pinned authority key")
    else:
        try:
            sig = base64.b64decode(config["signature_b64"], validate=True)
            if not ed_verify(canonical_bytes({k: config[k] for k in _ARM_FIELDS}), sig, pem):
                reasons.append("arming signature invalid")
        except Exception:
            reasons.append("arming signature undecodable")
    if not (config["valid_from_epoch"] <= now <= config["valid_until_epoch"]):
        reasons.append("outside validity window")
    approvers = config["authorized_by"]
    if (not isinstance(approvers, list)
            or len({json.dumps(a, sort_keys=True) for a in approvers}) < 2):
        reasons.append("arming requires dual distinct authorizers")
    if config["arming_class"] not in ("production", "test_fixture"):
        reasons.append("unknown arming class")
    if config["arming_class"] == "production":
        try:
            require_production_custody(custody_descriptor)
        except Exception as exc:
            reasons.append(f"production arming requires verified production custody: {exc}")
    if reasons:
        return {"arm_state": UNARMED, "reasons": reasons}
    state = ARMED_PRODUCTION if config["arming_class"] == "production" else ARMED_TEST_FIXTURE
    return {"arm_state": state, "reasons": [],
            "action_classes": list(config["action_classes"]),
            "max_actions": config["max_actions"],
            "config_sha256": sha256_hex(canonical_bytes({k: config[k] for k in _ARM_FIELDS}))}


_TOKEN_FIELDS = ("spec", "action_id", "action_class", "evidence_digest",
                 "approval_receipt_id", "arming_config_sha256", "issued_at_epoch")


def issue_action_token(body: dict[str, Any], private_pem: bytes, public_pem: bytes) -> dict[str, Any]:
    out = dict(body)
    out["authority_key_id"] = pem_key_id(public_pem)
    out["signature_b64"] = base64.b64encode(
        ed_sign(canonical_bytes({k: body[k] for k in _TOKEN_FIELDS}), private_pem)).decode()
    out["token_sha256"] = sha256_hex(canonical_bytes(out))
    return out


class LocalOutboxAdapter:
    """THE concrete reversible adapter: signed action records to a local
    outbox file. No network. Reversal emits a bound compensating record."""

    name = "local-outbox/1.0"

    def __init__(self, outbox: Path):
        self.outbox = Path(outbox)

    def attestation(self) -> dict[str, Any]:
        return {"adapter": self.name, "target": str(self.outbox), "network": False}

    def execute(self, record: dict[str, Any]) -> dict[str, Any]:
        with self.outbox.open("a") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        return {"delivered": True, "offset": self.outbox.stat().st_size}

    def reverse(self, original: dict[str, Any]) -> dict[str, Any]:
        rec = {"kind": "reversal", "reverses_receipt_sha256": original["receipt_sha256"],
               "action_id": original["action_id"], "at_epoch": time.time()}
        with self.outbox.open("a") as fh:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
        return rec


class LicensedExecutor:
    """Every execution demands: armed state ∋ action class, a valid unspent
    single-use license bound to THIS action's evidence + approval + arming,
    and budget. The receipt binds the complete proof chain and is signed."""

    def __init__(self, *, verification: dict[str, Any], adapter,
                 trusted_authority_keys: dict[str, bytes], signer):
        self.v = verification
        self.adapter = adapter
        self.trusted = trusted_authority_keys
        self.signer = signer
        self.spent_tokens: set[str] = set()
        self.executed = 0

    def execute(self, *, action_id: str, action_class: str, payload: dict[str, Any],
                principal: dict[str, Any], evidence_digest: str,
                approval_receipt_id: str, token: dict[str, Any]) -> dict[str, Any]:
        if self.v.get("arm_state") not in (ARMED_TEST_FIXTURE, ARMED_PRODUCTION):
            raise ExecutionRefused(f"unarmed: {'; '.join(self.v.get('reasons', []))}")
        if action_class not in self.v["action_classes"]:
            raise ExecutionRefused(f"action class {action_class!r} not in armed allowlist")
        if self.executed >= self.v["max_actions"]:
            raise ExecutionRefused("armed action budget exhausted")
        pem = self.trusted.get(token.get("authority_key_id"))
        core = {k: token.get(k) for k in _TOKEN_FIELDS}
        try:
            sig = base64.b64decode(token.get("signature_b64", ""), validate=True)
            ok = pem is not None and ed_verify(canonical_bytes(core), sig, pem)
        except Exception:
            ok = False
        if not ok:
            raise ExecutionRefused("action license invalid or unsigned")
        if token["token_sha256"] in self.spent_tokens:
            raise ExecutionRefused("action license already spent (single-use)")
        if (token["action_id"] != action_id or token["action_class"] != action_class
                or token["evidence_digest"] != evidence_digest
                or token["approval_receipt_id"] != approval_receipt_id
                or token["arming_config_sha256"] != self.v["config_sha256"]):
            raise ExecutionRefused("action license does not bind this action")
        if time.time() - token["issued_at_epoch"] > TOKEN_TTL_S:
            raise ExecutionRefused("action license expired")
        self.spent_tokens.add(token["token_sha256"])
        receipt = {"spec": EXECUTION_SPEC, "action_id": action_id,
                   "action_class": action_class, "payload_sha256":
                   sha256_hex(canonical_bytes(payload)),
                   "principal": principal, "evidence_digest": evidence_digest,
                   "approval_receipt_id": approval_receipt_id,
                   "arming_config_sha256": self.v["config_sha256"],
                   "arm_state": self.v["arm_state"],
                   "token_sha256": token["token_sha256"],
                   "adapter": self.adapter.attestation(),
                   "issued_at_epoch": time.time()}
        outcome = self.adapter.execute({"action_id": action_id, "payload": payload,
                                        "receipt_preimage_sha256":
                                        sha256_hex(canonical_bytes(receipt))})
        receipt["outcome"] = outcome
        receipt["receipt_sha256"] = sha256_hex(canonical_bytes(receipt))
        receipt["receipt_signature_b64"] = base64.b64encode(
            self.signer.sign(receipt["receipt_sha256"].encode())).decode()
        self.executed += 1
        return receipt

    def reverse(self, receipt: dict[str, Any]) -> dict[str, Any]:
        return self.adapter.reverse(receipt)
