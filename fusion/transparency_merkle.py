"""EAGLE EYE FUSION SLICE 1 — Merkle transparency log (clean-room RFC 6962).

CROSS-DOMAIN COLLISION:
  Gene A  (intelligence/security domain, source: IETF RFC 6962 Certificate
           Transparency): Merkle audit tree with INCLUSION proofs and
           CONSISTENCY proofs; split-view/equivocation resistance.
  Gene B  (Eagle Eye core): the append-only signed heads log (a hash chain
           that detects tampering only for a holder of the WHOLE log, and
           cannot prove a specific entry's inclusion succinctly, nor prove
           that version N is a prefix of version N+M).

FUSION: give the Eagle Eye ledger CT-grade proofs —
  * inclusion proof: prove entry e is in the log of root R, in O(log n),
    without shipping the whole log.
  * consistency proof: prove the log of root R_old is a strict prefix of the
    log of root R_new (no retroactive insertion, deletion, or reordering).
  This structurally defeats a split-view / retroactive-edit attack that the
  plain hash-chain heads log cannot catch from a succinct proof alone.

PROVENANCE: clean-room reimplementation from the PUBLIC RFC 6962 algorithm
(IETF, informational/standards-track, no license restriction on the
algorithm). Standard library only (hashlib). No code copied. See
SOURCE_PASSPORTS/rfc6962.json.

SAFETY BOUNDARY: this is Replaceable Intelligence Fabric — it does NOT modify
the sealed Proof Kernel; it is an additive, isolated module a verifier can
check independently.
"""
from __future__ import annotations

import hashlib
from typing import Sequence

# RFC 6962 domain separation: leaf = 0x00, node = 0x01
def _leaf_hash(data: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + data).digest()

def _node_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()

def _largest_power_of_two_less_than(n: int) -> int:
    k = 1
    while k < n:
        k <<= 1
    return k >> 1

def merkle_root(entries: Sequence[bytes]) -> bytes:
    """RFC 6962 Merkle Tree Hash (MTH) over a list of leaf byte-strings."""
    n = len(entries)
    if n == 0:
        return hashlib.sha256(b"").digest()
    if n == 1:
        return _leaf_hash(entries[0])
    k = _largest_power_of_two_less_than(n)
    return _node_hash(merkle_root(entries[:k]), merkle_root(entries[k:]))

def inclusion_proof(entries: Sequence[bytes], m: int) -> list[bytes]:
    """Audit path proving entry index m (0-based) is in the tree."""
    n = len(entries)
    if not (0 <= m < n):
        raise IndexError("leaf index out of range")
    if n == 1:
        return []
    k = _largest_power_of_two_less_than(n)
    if m < k:
        return inclusion_proof(entries[:k], m) + [merkle_root(entries[k:])]
    return inclusion_proof(entries[k:], m - k) + [merkle_root(entries[:k])]

def verify_inclusion(leaf: bytes, m: int, n: int, proof: list[bytes], root: bytes) -> bool:
    """Verify an inclusion proof WITHOUT the full tree (O(log n) hashes)."""
    if not (0 <= m < n):
        return False
    node = _leaf_hash(leaf)
    fn, sn = m, n - 1
    idx = 0
    for sibling in proof:
        if idx >= len(proof) and False:
            break
        if fn == sn or (fn % 2 == 1):
            node = _node_hash(sibling, node)
            while not (fn == 0 or fn % 2 == 1):
                fn >>= 1; sn >>= 1
        else:
            node = _node_hash(node, sibling)
        fn >>= 1; sn >>= 1
        idx += 1
    return fn == 0 and node == root

def consistency_proof(entries: Sequence[bytes], m: int, n: int) -> list[bytes]:
    """Prove the tree of the first m leaves is a prefix of the tree of n leaves."""
    if not (0 < m <= n):
        raise ValueError("require 0 < m <= n")
    if m == n:
        return []
    return _subproof(m, entries[:n], True)

def _subproof(m: int, entries: Sequence[bytes], b: bool) -> list[bytes]:
    n = len(entries)
    if m == n:
        return [] if b else [merkle_root(entries)]
    k = _largest_power_of_two_less_than(n)
    if m <= k:
        return _subproof(m, entries[:k], b) + [merkle_root(entries[k:])]
    return _subproof(m - k, entries[k:], False) + [merkle_root(entries[:k])]

def verify_consistency(m: int, n: int, proof: list[bytes], old_root: bytes, new_root: bytes) -> bool:
    """Verify old_root (size m) is a prefix of new_root (size n) via RFC 6962."""
    if m == 0 or m > n:
        return False
    if m == n:
        return not proof and old_root == new_root
    if not proof:
        return False
    if m & (m - 1) == 0:                 # m is a power of two -> prepend old_root
        proof = [old_root] + proof
    fn, sn = m - 1, n - 1
    while fn % 2 == 1:
        fn >>= 1; sn >>= 1
    fr = sr = proof[0]
    for c in proof[1:]:
        if sn == 0:
            return False
        if fn % 2 == 1 or fn == sn:
            fr = _node_hash(c, fr)
            sr = _node_hash(c, sr)
            while not (fn == 0 or fn % 2 == 1):
                fn >>= 1; sn >>= 1
        else:
            sr = _node_hash(sr, c)
        fn >>= 1; sn >>= 1
    return fn == 0 and fr == old_root and sr == new_root
