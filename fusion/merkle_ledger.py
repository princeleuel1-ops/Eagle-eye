"""FUSION SLICE 1 (integration) — wire Merkle proofs into a decision ledger +
a standalone verifier, WITHOUT touching the sealed Proof Kernel.

A MerkleLedger appends canonical decision receipts, publishes hash-chained
CHECKPOINTS {size, root, prev}, and serves inclusion + consistency proofs. A
standalone verify_transition() lets an auditor (the stranger's-verifier idea)
confirm append-only growth between two checkpoints with an O(log n) proof —
the capability the plain hash-chain heads log lacked. Stdlib only.
"""
from __future__ import annotations
import hashlib, json
from transparency_merkle import (merkle_root, inclusion_proof, verify_inclusion,
                                  consistency_proof, verify_consistency)

def _canon(o) -> bytes:
    return json.dumps(o, sort_keys=True, separators=(",", ":")).encode()

class MerkleLedger:
    def __init__(self):
        self.leaves: list[bytes] = []
        self.checkpoints: list[dict] = []

    def append(self, receipt: dict) -> int:
        self.leaves.append(_canon(receipt)); return len(self.leaves) - 1

    def checkpoint(self) -> dict:
        root = merkle_root(self.leaves).hex()
        prev = self.checkpoints[-1]["checkpoint_hash"] if self.checkpoints else "0"*64
        body = {"size": len(self.leaves), "root": root, "prev": prev}
        body["checkpoint_hash"] = hashlib.sha256(_canon(body)).hexdigest()
        self.checkpoints.append(body); return body

    def prove_inclusion(self, index: int) -> dict:
        proof = inclusion_proof(self.leaves, index)
        return {"index": index, "size": len(self.leaves),
                "leaf": self.leaves[index].decode(),
                "proof": [h.hex() for h in proof],
                "root": merkle_root(self.leaves).hex()}

    def prove_consistency(self, old_size: int) -> dict:
        proof = consistency_proof(self.leaves, old_size, len(self.leaves))
        return {"old_size": old_size, "new_size": len(self.leaves),
                "proof": [h.hex() for h in proof],
                "new_root": merkle_root(self.leaves).hex()}

# ---- standalone auditor side (no ledger object, just the proof objects) -----
def verify_inclusion_obj(obj: dict) -> bool:
    return verify_inclusion(obj["leaf"].encode(), obj["index"], obj["size"],
                            [bytes.fromhex(h) for h in obj["proof"]],
                            bytes.fromhex(obj["root"]))

def verify_transition(old_root_hex: str, old_size: int, cons: dict) -> bool:
    """Auditor holds an old checkpoint root; verifies the new checkpoint is an
    append-only extension of it. Fails closed on any retroactive edit."""
    return verify_consistency(old_size, cons["new_size"],
                              [bytes.fromhex(h) for h in cons["proof"]],
                              bytes.fromhex(old_root_hex),
                              bytes.fromhex(cons["new_root"]))
