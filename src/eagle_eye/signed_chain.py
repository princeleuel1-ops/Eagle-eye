"""Ed25519-signed, anchored, append-only receipt chains.

Replaces rewriteable unkeyed SHA-256 chains (audit blockers 4/5). Every row is
signed over (tenant, run, sequence, previous_hash, body). The chain publishes
an external anchor {length, head, signer_key_id} signed separately, so
tail truncation and whole-chain rewrites are detectable even by a verifier
that only holds the anchor. Verification requires a trusted signer registry.
"""

from __future__ import annotations

import base64
from typing import Any

from .prior_registry import canonical_bytes, sha256_hex
from .signing import key_id, sign, verify

GENESIS = "0" * 64


class ChainError(ValueError):
    pass


class SignedChain:
    def __init__(self, *, tenant_id: str, run_id: str, chain_id: str,
                 private_key: bytes, public_key: bytes):
        self.tenant_id, self.run_id, self.chain_id = tenant_id, run_id, chain_id
        self._private = private_key
        self.public_key = public_key
        self.signer_key_id = key_id(public_key)
        self.rows: list[dict[str, Any]] = []
        self.head = GENESIS

    def append(self, body: dict[str, Any]) -> dict[str, Any]:
        # Rows must be float-free for cross-runtime signature parity (B6):
        # every number is quantized to micro-integers before hashing/signing.
        from .posterior_engine import quantize_micro
        body = quantize_micro(body)
        row = {
            "chain_id": self.chain_id,
            "tenant_id": self.tenant_id,
            "run_id": self.run_id,
            "sequence": len(self.rows) + 1,
            "previous_hash": self.head,
            "body": body,
        }
        row["row_hash"] = sha256_hex(canonical_bytes(row))
        row["signer_key_id"] = self.signer_key_id
        row["signature_b64"] = base64.b64encode(
            sign(row["row_hash"].encode(), self._private)).decode()
        self.rows.append(row)
        self.head = row["row_hash"]
        return row

    def anchor(self) -> dict[str, Any]:
        """Externally committable anchor: length + terminal head, signed."""
        body = {
            "chain_id": self.chain_id, "tenant_id": self.tenant_id, "run_id": self.run_id,
            "length": len(self.rows), "head": self.head,
            "signer_key_id": self.signer_key_id,
        }
        return {**body, "anchor_signature_b64": base64.b64encode(
            sign(canonical_bytes(body), self._private)).decode()}


def verify_chain(rows: list[dict[str, Any]], anchor: dict[str, Any],
                 registry: dict[str, Any], *, expected_tenant: str,
                 expected_chain_id: str | None = None,
                 expected_run_id: str | None = None) -> dict[str, Any]:
    """Full verification: signer trust, signatures, linkage, anchor. Fail closed.

    V5 hardening (Lane 2 finding): the anchor's signed chain_id/run_id are now
    bound. Every row must carry the SAME chain_id/run_id as the signed anchor,
    and callers may additionally pin the expected values — so a chain signed by
    a reused key cannot be presented in the slot of a DIFFERENT chain
    (cross-chain confusion). Malformed signer PEM fails closed (verified:False)
    instead of raising.
    """
    def fail(reason: str) -> dict[str, Any]:
        return {"verified": False, "reason": reason}
    signer = next((s for s in registry.get("trusted_signers", [])
                   if s.get("key_id") == anchor.get("signer_key_id")), None)
    if signer is None:
        return fail("unknown signer")
    pub = signer["public_key_pem"].encode()
    # fail closed on malformed key material / signatures rather than raising
    try:
        if key_id(pub) != anchor["signer_key_id"]:
            return fail("signer registry fingerprint mismatch")
        anchor_body = {k: v for k, v in anchor.items() if k != "anchor_signature_b64"}
        if not verify(canonical_bytes(anchor_body), base64.b64decode(anchor["anchor_signature_b64"]), pub):
            return fail("forged anchor signature")
    except Exception as exc:  # noqa: BLE001
        return fail(f"malformed signer material or signature: {type(exc).__name__}")
    if anchor["tenant_id"] != expected_tenant:
        return fail("wrong tenant")
    # V5: bind the anchor's own chain identity, and optionally pin it.
    anchor_chain_id = anchor.get("chain_id")
    anchor_run_id = anchor.get("run_id")
    if expected_chain_id is not None and anchor_chain_id != expected_chain_id:
        return fail(f"chain_id mismatch: anchor {anchor_chain_id!r} != expected {expected_chain_id!r}")
    if expected_run_id is not None and anchor_run_id != expected_run_id:
        return fail(f"run_id mismatch: anchor {anchor_run_id!r} != expected {expected_run_id!r}")
    if len(rows) != anchor["length"]:
        return fail("chain length does not match external anchor (truncation or extension)")
    head = GENESIS
    for index, row in enumerate(rows):
        body = {k: v for k, v in row.items()
                if k not in ("row_hash", "signature_b64", "signer_key_id")}
        if row["sequence"] != index + 1:
            return fail(f"sequence break at {index + 1} (reordered or deleted rows)")
        if row["previous_hash"] != head:
            return fail(f"linkage break at sequence {row['sequence']}")
        if sha256_hex(canonical_bytes(body)) != row["row_hash"]:
            return fail(f"row hash mismatch at sequence {row['sequence']} (rewritten row)")
        if row["signer_key_id"] != anchor["signer_key_id"]:
            return fail(f"signer substitution at sequence {row['sequence']}")
        if row.get("chain_id") != anchor_chain_id:
            return fail(f"chain_id confusion at sequence {row['sequence']} "
                        f"(row {row.get('chain_id')!r} != anchor {anchor_chain_id!r})")
        if row.get("run_id") != anchor_run_id:
            return fail(f"run_id confusion at sequence {row['sequence']}")
        try:
            if not verify(row["row_hash"].encode(), base64.b64decode(row["signature_b64"]), pub):
                return fail(f"forged signature at sequence {row['sequence']}")
        except Exception as exc:  # noqa: BLE001
            return fail(f"malformed signature at sequence {row['sequence']}: {type(exc).__name__}")
        if row["tenant_id"] != expected_tenant:
            return fail(f"tenant mismatch at sequence {row['sequence']}")
        head = row["row_hash"]
    if head != anchor["head"]:
        return fail("terminal head does not match external anchor")
    return {"verified": True, "length": len(rows), "head": head,
            "signer_key_id": anchor["signer_key_id"],
            "chain_id": anchor_chain_id, "run_id": anchor_run_id}
