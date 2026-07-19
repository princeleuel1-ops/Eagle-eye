#!/usr/bin/env python3
"""EAGLE EYE — THE STRANGER'S VERIFIER (V9).

A single-file, standard-library-only verifier for published Eagle Eye
bundles. It imports NOTHING from the Eagle Eye repository and depends on
NOTHING outside CPython >= 3.9. You can audit this one file in one sitting,
then run it against any published bundle.

WHAT IT PROVES WITHOUT TRUSTING THE REPOSITORY
  - AUTHENTICITY: every chain row and every anchor carries an Ed25519
    signature verified here by a from-scratch RFC 8032 implementation,
    against the signer registry pinned in the bundle and/or key ids you
    pin yourself with --expect-signer.
  - INTEGRITY: row hashes, hash linkage, sequence numbering, anchored
    length/head — recomputed from bytes; splices, reorders, truncations,
    and rewrites are detected.
  - COMMIT-REVEAL: the revealed evaluator secret reproduces the published
    pre-run commitment.
  - ACCOUNTING: charge-before-result pairing, one-result-per-charge,
    monotone look indexes, alpha arithmetic, and the paired-test decision
    flag's internal consistency.
  - DECISION RULE: candidate ids, snapshot ids, and the full promotion
    gate chain are recomputed from signed micro-integer fields; every
    recorded lineage STATE and reason list must reproduce exactly.
  - EVIDENCE ARITHMETIC: W-transfer cluster sums are re-added from
    recorded per-case scores; seed signs, e-process wealth (exact
    binomial-mixture e-values), thresholds, crossings, and the headline
    claim are recomputed. Inflated wealth or a flipped claim fails.
  - TRANSPARENCY: an offline, hash-chained heads log (append/verify) so
    published chain heads commit into an append-only record.

WHAT IT DOES NOT PROVE (honest boundary)
  - It does not re-run the models. Rebuilding sealed suites from the
    revealed secret and re-scoring predictions is SEMANTIC replay and
    requires the hash-pinned source tree (run its `make check` /
    `make replay` for that, as a second step). This file proves the
    receipts are authentic, intact, internally consistent, and correctly
    accounted — not that the model math inside the sealed evaluator is
    what the source claims. Pin the tree hash; audit or execute the tree.
  - Verifying against the registry embedded in a bundle proves internal
    consistency only. For real third-party assurance, pin the expected
    signer key ids out-of-band via --expect-signer.

USAGE
  python3 strangers_verifier.py verify-evolution REPLAY_BUNDLE.json
      [--expect-signer ed25519:HEX]...
  python3 strangers_verifier.py verify-transfer W_TRANSFER_BUNDLE.json
      W_TRANSFER_RECEIPT.json [--champion-bundle REPLAY_BUNDLE.json]
      [--expect-signer ed25519:HEX]...
  python3 strangers_verifier.py verify-recursive RECURSIVE_EVOLUTION_RECEIPT.json
  python3 strangers_verifier.py heads-append HEADS.jsonl BUNDLE.json
  python3 strangers_verifier.py heads-verify HEADS.jsonl [--bundle BUNDLE.json]

Exit code 0 with STRANGERS_VERIFIER_PASS only if every check passes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import sys

VERIFIER_SPEC = "eagle-eye-strangers-verifier/1.0"
GENESIS = "0" * 64

# --- constants ported from the pinned tree (pure data; audit against source) --
EVOLUTION_SPEC = "eagle-eye-sealed-evolution/4.0"
COURT_RELEASE = "eagle-eye-prediction-court/1.0"
DEVELOPMENT_SEED = 11
EVALUATOR_VERSION = "sealed-evaluator/4.0"
MIN_SCORED_CASES = 30
MIN_PAIRED_N = 30
COVERAGE_BAND_MICRO = (700_000, 920_000)
PERMUTATION_TOLERANCE_MICRO = 50_000
W_TRANSFER_RECEIPT_SPEC = "w-transfer-receipt/1.0"

# ============================ minimal helpers ================================

def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_failures: list[str] = []
_passed = 0


def check(name: str, condition: bool, detail: str = "") -> bool:
    global _passed
    if condition:
        _passed += 1
        print(f"OK   {name}")
    else:
        _failures.append(name)
        print(f"FAIL {name}{(': ' + detail) if detail else ''}")
    return bool(condition)


# ===================== Ed25519 (RFC 8032, verify only) =======================
# From-scratch implementation over the twisted Edwards curve using extended
# homogeneous coordinates. Standard-library only. Verification only.

_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _I % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_By = 4 * _inv(5) % _P
_Bx = _recover_x(_By, 0)
_B = (_Bx, _By, 1, _Bx * _By % _P)  # base point, extended coords
_IDENT = (0, 1, 1, 0)


def _pt_add(p, q):
    x1, y1, z1, t1 = p
    x2, y2, z2, t2 = q
    a = (y1 - x1) * (y2 - x2) % _P
    b = (y1 + x1) * (y2 + x2) % _P
    c = 2 * t1 * t2 * _D % _P
    dd = 2 * z1 * z2 % _P
    e, f, g, h = b - a, dd - c, dd + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _pt_mul(s: int, p):
    q = _IDENT
    while s > 0:
        if s & 1:
            q = _pt_add(q, p)
        p = _pt_add(p, p)
        s >>= 1
    return q


def _pt_equal(p, q) -> bool:
    x1, y1, z1, _ = p
    x2, y2, z2, _ = q
    return (x1 * z2 - x2 * z1) % _P == 0 and (y1 * z2 - y2 * z1) % _P == 0


def _pt_decompress(raw: bytes):
    if len(raw) != 32:
        return None
    y = int.from_bytes(raw, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def ed25519_verify(public_raw: bytes, message: bytes, signature: bytes) -> bool:
    if len(public_raw) != 32 or len(signature) != 64:
        return False
    a_pt = _pt_decompress(public_raw)
    r_pt = _pt_decompress(signature[:32])
    if a_pt is None or r_pt is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    h = int.from_bytes(
        hashlib.sha512(signature[:32] + public_raw + message).digest(), "little") % _L
    # [8][S]B == [8]R + [8][h]A  (cofactored check per RFC 8032)
    lhs = _pt_mul(8 * s, _B)
    rhs = _pt_add(_pt_mul(8, r_pt), _pt_mul(8 * h, a_pt))
    return _pt_equal(lhs, rhs)


# Ed25519 SubjectPublicKeyInfo DER prefix (RFC 8410): fixed 12 bytes + 32 raw.
_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


def parse_ed25519_pem(pem: str) -> tuple[bytes, str] | None:
    """Return (raw_32_byte_key, key_id) or None. key_id = ed25519:sha256(DER)."""
    body = "".join(line.strip() for line in pem.strip().splitlines()
                   if "-----" not in line)
    try:
        der = base64.b64decode(body, validate=True)
    except Exception:
        return None
    if len(der) != 44 or not der.startswith(_SPKI_PREFIX):
        return None
    return der[12:], "ed25519:" + sha256_hex(der)


# ========================= signed chain verification =========================

def load_registry(bundle: dict, expected_ids: list[str]) -> dict[str, bytes] | None:
    reg = {}
    for signer in bundle.get("signer_registry", {}).get("trusted_signers", []):
        parsed = parse_ed25519_pem(signer.get("public_key_pem", ""))
        if parsed is None:
            check("REGISTRY_KEY_PARSES", False, f"unparseable key for {signer.get('key_id')}")
            return None
        raw, kid = parsed
        check(f"REGISTRY_KEY_ID_MATCHES:{kid[:24]}", kid == signer.get("key_id"),
              "registry key_id does not match sha256 of the DER key")
        reg[kid] = raw
    for expected in expected_ids:
        check(f"EXPECTED_SIGNER_PRESENT:{expected[:24]}", expected in reg,
              "pinned signer not found in bundle registry")
    return reg


def verify_signed_chain(name: str, chain: dict, registry: dict[str, bytes],
                        *, expected_tenant: str | None = None) -> bool:
    rows, anchor = chain.get("rows", []), chain.get("anchor", {})
    ok = True
    prev = GENESIS
    chain_id = anchor.get("chain_id")
    run_id = anchor.get("run_id")
    tenant = anchor.get("tenant_id")
    if expected_tenant is not None:
        ok &= check(f"{name}:TENANT", tenant == expected_tenant)
    for i, row in enumerate(rows):
        core = {"chain_id": row.get("chain_id"), "tenant_id": row.get("tenant_id"),
                "run_id": row.get("run_id"), "sequence": row.get("sequence"),
                "previous_hash": row.get("previous_hash"), "body": row.get("body")}
        recomputed = sha256_hex(canonical_bytes(core))
        if not (row.get("row_hash") == recomputed
                and row.get("sequence") == i + 1
                and row.get("previous_hash") == prev
                and row.get("chain_id") == chain_id
                and row.get("run_id") == run_id
                and row.get("tenant_id") == tenant):
            ok &= check(f"{name}:ROW_{i + 1}_INTEGRITY", False,
                        "hash/linkage/sequence/binding mismatch")
            return False
        kid = row.get("signer_key_id")
        raw = registry.get(kid)
        sig_ok = False
        if raw is not None:
            try:
                sig = base64.b64decode(row.get("signature_b64", ""), validate=True)
                sig_ok = ed25519_verify(raw, row["row_hash"].encode(), sig)
            except Exception:
                sig_ok = False
        if not sig_ok:
            ok &= check(f"{name}:ROW_{i + 1}_SIGNATURE", False,
                        f"signature invalid or signer {str(kid)[:24]} untrusted")
            return False
        prev = row["row_hash"]
    ok &= check(f"{name}:ROWS_VERIFIED", ok, "")
    anchor_body = {"chain_id": chain_id, "tenant_id": tenant, "run_id": run_id,
                   "length": anchor.get("length"), "head": anchor.get("head"),
                   "signer_key_id": anchor.get("signer_key_id")}
    a_ok = anchor.get("length") == len(rows) and anchor.get("head") == prev
    raw = registry.get(anchor.get("signer_key_id"))
    if a_ok and raw is not None:
        try:
            asig = base64.b64decode(anchor.get("anchor_signature_b64", ""), validate=True)
            a_ok = ed25519_verify(raw, canonical_bytes(anchor_body), asig)
        except Exception:
            a_ok = False
    else:
        a_ok = False
    ok &= check(f"{name}:ANCHOR", a_ok,
                "anchor length/head/signature mismatch (truncation or rewrite)")
    return bool(ok)


# ==================== evolution-bundle specific checks =======================

def snapshot_id_for(registry_manifest: str, seed_commitment: str,
                    run_seed: int, run_context: dict) -> str:
    return "snap-" + sha256_hex(canonical_bytes({
        "registry_manifest_sha256": registry_manifest,
        "development_partition": {"builder": "development", "seed": DEVELOPMENT_SEED},
        "evaluator_seed_commitment": seed_commitment,
        "evaluator_version": EVALUATOR_VERSION,
        "court_release": COURT_RELEASE,
        "run_seed": run_seed,
        "run_context": run_context,
    }))[:16]


def candidate_id_for(cand: dict) -> str:
    core = {"p": cand["parent_champion_id"], "d": cand["diff"],
            "c": cand["created_at_cycle"], "snap": cand["dataset_snapshot_id"]}
    if cand.get("feedback_state_sha256"):
        core["fb"] = cand["feedback_state_sha256"]
    return "cand-" + sha256_hex(canonical_bytes(core))[:12]


def apply_promotion_gates(body: dict, *, min_scored: int = MIN_SCORED_CASES):
    """Exact port of the pinned tree's pure promotion gate chain (micro ints)."""
    stats = body["statistics"]
    agg = body["challenger_aggregates"]
    champ_agg = body["champion_aggregates"]
    hold_m = agg["metrics"]
    if agg["scored_count"] < min_scored:
        return ("ABSTAINED_INSUFFICIENT_EVIDENCE",
                [f"scored_count {agg['scored_count']} < {min_scored}"])
    reasons = []
    if agg["abstentions_standard"] > 0:
        reasons.append("trust:standard_abstention")
    if agg["probe_count"] and agg["abstentions_probe"] != agg["probe_count"]:
        reasons.append("trust:out_of_support_not_refused")
    if hold_m["permutation_spread_max"] > PERMUTATION_TOLERANCE_MICRO:
        reasons.append("trust:permutation_instability")
    if reasons:
        return ("BLOCKED_TRUST_REGRESSION", reasons)
    cov = hold_m["coverage80"] or 0
    champ_cov = champ_agg["metrics"]["coverage80"] or 0
    if not (COVERAGE_BAND_MICRO[0] <= cov <= COVERAGE_BAND_MICRO[1]):
        return ("BLOCKED_CALIBRATION_REGRESSION", [f"coverage_micro {cov} outside band"])
    if abs(cov - 800000) > abs(champ_cov - 800000) + 20000:
        return ("BLOCKED_CALIBRATION_REGRESSION",
                ["coverage distance to nominal worsened beyond 0.02"])
    if (hold_m["nll_temporal_ood"] is not None
            and champ_agg["metrics"]["nll_temporal_ood"] is not None
            and hold_m["nll_temporal_ood"] > champ_agg["metrics"]["nll_temporal_ood"]):
        return ("BLOCKED_SHIFT", ["temporal_ood_regression_vs_champion"])
    if stats["significant_improvement"]:
        return ("PROMOTED", [])
    return ("REJECTED", ["sealed_paired_test_not_significant",
                         f"ci_upper_micro={stats['ci_upper_micro']}"])


def verify_evolution(bundle: dict, expected_signers: list[str]) -> bool:
    registry = load_registry(bundle, expected_signers)
    if registry is None:
        return False
    ok = True
    for cname, chain in sorted(bundle.get("chains", {}).items()):
        ok &= verify_signed_chain(f"CHAIN[{cname}]", chain, registry)
    reveal = bundle["evaluator_reveal"]
    ok &= check("COMMIT_REVEAL",
                sha256_hex(canonical_bytes({
                    "evaluator_secret": reveal["evaluator_secret"],
                    "secret_provenance": reveal["secret_provenance"],
                })) == reveal["seed_commitment"],
                "revealed secret does not reproduce the published commitment")
    ok &= check("LIFECYCLE_AT_REVEAL", reveal.get("lifecycle_at_reveal") == "REVEALABLE")

    ev_rows = [r["body"] for r in bundle["chains"]["evaluator"]["rows"]]
    ev_hash = {r["row_hash"]: r["body"] for r in bundle["chains"]["evaluator"]["rows"]}
    charges = {r["row_hash"]: r["body"] for r in bundle["chains"]["evaluator"]["rows"]
               if r["body"].get("kind") in ("promotion_look_charge", "final_audit_charge")}
    results = [(r["row_hash"], r["body"]) for r in bundle["chains"]["evaluator"]["rows"]
               if r["body"].get("kind") in ("promotion_look_result", "final_audit_result")]
    used = set()
    pair_ok, alpha_ok = True, True
    alpha_per_look = None
    for rh, body in results:
        ch = charges.get(body.get("charge_row_hash"))
        if ch is None or body["charge_row_hash"] in used:
            pair_ok = False
            continue
        used.add(body["charge_row_hash"])
        pair_ok &= (ch.get("look_index") == body.get("look_index"))
        if body.get("kind") == "promotion_look_result":
            pair_ok &= (ch.get("candidate_id") == body.get("candidate_id")
                        and ch.get("nonce") == body.get("nonce"))
            stats = body.get("statistics") or {}
            apl = stats.get("alpha_per_look_micro")
            alpha_per_look = apl if alpha_per_look is None else alpha_per_look
            alpha_ok &= (apl == alpha_per_look)
            alpha_ok &= (stats.get("alpha_spent_after_micro")
                         == int(round(body["look_index"] * apl)))
            sig = bool(stats.get("n_paired", 0) >= MIN_PAIRED_N
                       and stats.get("ci_upper_micro") is not None
                       and stats["ci_upper_micro"] < 0)
            alpha_ok &= (bool(stats.get("significant_improvement")) == sig)
    ok &= check("CHARGE_RESULT_PAIRING", pair_ok,
                "result without matching charge, reuse, or index/nonce mismatch")
    ok &= check("ALPHA_AND_DECISION_ARITHMETIC", alpha_ok)
    lifecycle = [b for b in ev_rows if b.get("kind") == "lifecycle"]
    ok &= check("LIFECYCLE_FINALIZED_IN_CHAIN",
                any(b.get("event") == "FINALIZED" for b in lifecycle),
                "no signed FINALIZED lifecycle row (reveal-before-finalize?)")

    run_seed = bundle["controller_run_seed"]
    fb = bundle.get("feedback")
    lin_ok, states = True, {"PROMOTED": 0, "REJECTED": 0, "BLOCKED": 0, "ABSTAINED": 0}
    for row in bundle["chains"]["lineage"]["rows"]:
        body = row["body"]
        cand = body["candidate"]
        lin_ok &= (body.get("spec") == EVOLUTION_SPEC)
        lin_ok &= (candidate_id_for({**cand, "dataset_snapshot_id": body["dataset_snapshot_id"]})
                   == cand["candidate_id"])
        lin_ok &= (snapshot_id_for(body["registry_manifest_sha256"],
                                   reveal["seed_commitment"], run_seed,
                                   body["run_context"]) == body["dataset_snapshot_id"])
        if fb is not None:
            lin_ok &= (cand.get("feedback_state_sha256") is not None)
        st = body["state"]
        states["BLOCKED" if st.startswith("BLOCKED") else
               "ABSTAINED" if st.startswith("ABSTAINED") else st] = \
            states.get("BLOCKED" if st.startswith("BLOCKED") else
                       "ABSTAINED" if st.startswith("ABSTAINED") else st, 0) + 1
        resp_hash = body.get("evaluator_response_hash")
        if resp_hash is not None:
            resp = ev_hash.get(resp_hash)
            if resp is None or resp.get("terminal_status") != "SUCCEEDED":
                lin_ok = False
                continue
            fragment = {"statistics": resp["statistics"],
                        "challenger_aggregates": resp["challenger_aggregates"],
                        "champion_aggregates": resp["champion_aggregates"]}
            state, reasons = apply_promotion_gates(fragment)
            lin_ok &= (state == body["state"] and reasons == body["reasons"])
            lin_ok &= (resp["candidate_id"] == cand["candidate_id"])
            lin_ok &= (body.get("statistics") == resp["statistics"])
        else:
            lin_ok &= (body["state"] != "PROMOTED")
    ok &= check("LINEAGE_IDS_AND_DECISIONS_RECOMPUTED", lin_ok,
                "candidate/snapshot id or promotion-gate state mismatch")
    print(f"INFO lineage_states={json.dumps(states, sort_keys=True)}")
    return bool(ok)


# ===================== e-process / transfer arithmetic =======================

def _log_beta(a: float, b: float) -> float:
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def _betainc_regularized(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = a * math.log(x) + b * math.log1p(-x) - math.log(a) - _log_beta(a, b)
    if x > (a + 1.0) / (a + b + 2.0):
        return 1.0 - _betainc_regularized(b, a, 1.0 - x)
    tiny = 1e-300
    f, c_term, d_term = 1.0, 1.0, 0.0
    for m in range(0, 400):
        if m == 0:
            numerator = 1.0
        elif m % 2 == 0:
            k = m // 2
            numerator = (k * (b - k) * x) / ((a + 2.0 * k - 1.0) * (a + 2.0 * k))
        else:
            k = (m - 1) // 2
            numerator = -((a + k) * (a + b + k) * x) / ((a + 2.0 * k) * (a + 2.0 * k + 1.0))
        d_term = 1.0 + numerator * d_term
        if abs(d_term) < tiny:
            d_term = tiny
        d_term = 1.0 / d_term
        c_term = 1.0 + numerator / c_term
        if abs(c_term) < tiny:
            c_term = tiny
        f *= c_term * d_term
        if abs(1.0 - c_term * d_term) < 1e-15:
            break
    return math.exp(ln_front) * (f - 1.0)


_LN2 = math.log(2.0)
_LOG_FLOOR = -80.0


def log_e_micro(wins: int, losses: int) -> int:
    if wins < 0 or losses < 0:
        raise ValueError("negative counts")
    m = wins + losses
    if m == 0:
        return 0
    upper = 1.0 - _betainc_regularized(wins + 1, m - wins + 1, 0.5)
    log_tail = math.log(upper) if upper > 0.0 else _LOG_FLOOR
    return int(round(((m + 1) * _LN2 + _log_beta(wins + 1, m - wins + 1) + log_tail) * 1e6))


def transfer_stream_id(protocol_hash: str, family_id: str, family_release: str,
                       metric: str, champion_config_hash: str, baseline_release: str) -> str:
    return "wstrm-" + sha256_hex(canonical_bytes({
        "protocol_hash": protocol_hash, "family_id": family_id,
        "family_release": family_release, "metric": metric,
        "champion_config_hash": champion_config_hash,
        "baseline_release": baseline_release,
    }))[:16]


def verify_transfer(bundle: dict, receipt: dict, expected_signers: list[str],
                    champion_bundle_path: str | None) -> bool:
    registry = load_registry(bundle, expected_signers)
    if registry is None:
        return False
    ok = verify_signed_chain("CHAIN[transfer]", bundle["chains"]["transfer"], registry)
    protocol = bundle["protocol"]
    body = {k: protocol[k] for k in (
        "spec", "alpha_total_micro", "metrics", "seeds", "target_plan",
        "family_manifests", "baseline_release", "champion_config_hash",
        "stream_count", "log_threshold_micro", "headline_family_ids", "headline_rule")}
    ok &= check("PROTOCOL_HASH_RECOMPUTED",
                sha256_hex(canonical_bytes(body)) == protocol["protocol_hash"])
    ok &= check("RECEIPT_BINDS_PROTOCOL",
                receipt.get("protocol_hash") == protocol["protocol_hash"]
                and receipt.get("spec") == W_TRANSFER_RECEIPT_SPEC)
    if champion_bundle_path:
        digest = hashlib.sha256()
        with open(champion_bundle_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        ok &= check("CHAMPION_BUNDLE_SHA_BOUND",
                    digest.hexdigest() == bundle.get("champion_bundle_sha256")
                    == receipt.get("champion_bundle_sha256"))

    fam_release = {m["family_id"]: m["family_release"] for m in protocol["family_manifests"]}
    # rebuild stream trajectories from recorded per-case evidence
    streams: dict[str, dict] = {}
    ev_ok = True
    chain_rows = [r["body"] for r in bundle["chains"]["transfer"]["rows"]]
    chain_by_unit = {(b["family_id"], b["world_seed"]): b for b in chain_rows}
    for ev in bundle["evaluations"]:
        sums = {m: 0 for m in protocol["metrics"]}
        n_pairs = 0
        for case in ev["case_rows"]:
            dm = case.get("diff_micro")
            if dm is None:
                continue
            n_pairs += 1
            for m in protocol["metrics"]:
                sums[m] += dm[m]
                champ, base = case.get("champion_score"), case.get("baseline_score")
                if champ and base and not champ.get("abstained") and not base.get("abstained"):
                    ev_ok &= (dm[m] == champ[f"{m}_micro"] - base[f"{m}_micro"])
        ev_ok &= (n_pairs == ev["paired_case_count"])
        crow = chain_by_unit.get((ev["family_id"], ev["world_seed"]))
        ev_ok &= (crow is not None and crow["protocol_hash"] == protocol["protocol_hash"])
        for m in protocol["metrics"]:
            ev_ok &= (sums[m] == ev["cluster_sums_micro"][m]
                      and (crow or {}).get("cluster_sums_micro", {}).get(m) == sums[m])
            sign = "win" if sums[m] < 0 else ("loss" if sums[m] > 0 else "tie")
            ev_ok &= (ev["cluster_signs"][m] == sign)
            sid = transfer_stream_id(protocol["protocol_hash"], ev["family_id"],
                                     fam_release[ev["family_id"]], m,
                                     protocol["champion_config_hash"],
                                     protocol["baseline_release"])
            st = streams.setdefault(sid, {"wins": 0, "losses": 0, "ties": 0,
                                          "family_id": ev["family_id"], "metric": m,
                                          "first_crossing_index": None, "units": 0})
            st["units"] += 1
            st[sign + ("s" if sign != "loss" else "es")] = st[sign + ("s" if sign != "loss" else "es")] + 1
            wealth = log_e_micro(st["wins"], st["losses"])
            if wealth >= protocol["log_threshold_micro"] and st["first_crossing_index"] is None:
                st["first_crossing_index"] = st["units"]
    ok &= check("CLUSTER_SUMS_AND_SIGNS_RECOMPUTED", ev_ok,
                "per-case sums, chain rows, or signs do not reproduce")

    standing = {row["stream_id"]: row for row in receipt["standing"]}
    st_ok = set(standing) == set(streams)
    for sid, st in streams.items():
        rec = standing.get(sid)
        if rec is None:
            st_ok = False
            continue
        wealth = log_e_micro(st["wins"], st["losses"])
        st_ok &= (rec["cumulative_log_e_micro"] == wealth)
        st_ok &= (bool(rec["crossed"]) == (wealth >= protocol["log_threshold_micro"]))
        st_ok &= (rec.get("wins") == st["wins"] and rec.get("losses") == st["losses"])
        st_ok &= (rec.get("first_crossing_index") == st["first_crossing_index"])
    ok &= check("STREAM_WEALTH_RECOMPUTED", st_ok,
                "e-process wealth, crossing flags, or counts do not reproduce")

    earned = all(standing.get(sid, {}).get("crossed", False)
                 for sid in protocol["headline_stream_ids"])
    claimed = receipt.get("headline_claim_status")
    expected_claim = ("ALIEN_TRANSFER_EVIDENCE_EARNED" if earned
                      else "NO_ALIEN_TRANSFER_EVIDENCE_EARNED")
    ok &= check("HEADLINE_CLAIM_CONSISTENT",
                bool(receipt.get("headline_claim_crossed")) == earned
                and claimed == expected_claim,
                f"claimed '{claimed}' but recomputation says '{expected_claim}'")
    print(f"INFO headline={expected_claim}")
    return bool(ok)


def verify_recursive(receipt: dict) -> bool:
    ok = True
    thr = receipt["log_threshold_micro"]
    for r in receipt.get("rounds", []):
        ok &= check(f"ROUND_{r.get('round')}_REPLAY_PASSED",
                    r.get("status") == "ADMITTED" and r.get("replay_passed") is True
                    and (r.get("replay_report") or {}).get("decisions_mismatched") == 0)
    arith = True
    for sid, s in (receipt.get("ledger_state", {}).get("streams") or {}).items():
        cum = 0
        for h in s.get("history", []):
            arith &= (h["log_e_micro"] == log_e_micro(h["wins"], h["losses"]))
            cum += h["log_e_micro"]
            arith &= (h["cumulative_log_e_micro"] == cum)
        arith &= (s.get("cumulative_log_e_micro") == cum)
    ok &= check("EPROCESS_ARITHMETIC_RECOMPUTED", arith)
    cross_ok = all((s["cumulative_log_e_micro"] >= thr) == bool(c.get("crossed"))
                   for c in receipt.get("standing_top", [])
                   for s in [receipt["ledger_state"]["streams"][c["stream_id"]]])
    ok &= check("CROSSING_FLAGS_CONSISTENT", cross_ok)
    ok &= check("HONESTY_BLOCK_PRESENT",
                receipt.get("honesty", {}).get("crossing_required_for_pass") is False
                and receipt.get("external_action") is False)
    return bool(ok)


# ====================== transparency heads log (offline) =====================

def heads_entries_from_bundle(bundle: dict, bundle_sha256: str) -> list[dict]:
    out = []
    for cname, chain in sorted(bundle.get("chains", {}).items()):
        anchor = chain.get("anchor", {})
        out.append({"chain": cname, "chain_id": anchor.get("chain_id"),
                    "tenant_id": anchor.get("tenant_id"), "run_id": anchor.get("run_id"),
                    "length": anchor.get("length"), "head": anchor.get("head"),
                    "signer_key_id": anchor.get("signer_key_id"),
                    "bundle_sha256": bundle_sha256,
                    "bundle_spec": bundle.get("spec")})
    return out


def heads_append(heads_path: str, bundle_path: str) -> int:
    bundle = json.load(open(bundle_path))
    digest = hashlib.sha256(open(bundle_path, "rb").read()).hexdigest()
    try:
        lines = [ln for ln in open(heads_path).read().splitlines() if ln.strip()]
    except FileNotFoundError:
        lines = []
    prev = sha256_hex(lines[-1].encode()) if lines else GENESIS
    seq = (json.loads(lines[-1])["seq"] + 1) if lines else 1
    added = 0
    with open(heads_path, "a") as fh:
        for entry in heads_entries_from_bundle(bundle, digest):
            record = {"spec": "eagle-eye-heads-log/1.0", "seq": seq,
                      "prev_entry_sha256": prev, **entry}
            line = json.dumps(record, sort_keys=True, separators=(",", ":"))
            fh.write(line + "\n")
            prev = sha256_hex(line.encode())
            seq += 1
            added += 1
    print(f"HEADS_APPENDED={added}")
    return 0


def heads_verify(heads_path: str, bundle_path: str | None) -> int:
    lines = [ln for ln in open(heads_path).read().splitlines() if ln.strip()]
    prev, seq_ok = GENESIS, True
    for i, line in enumerate(lines):
        rec = json.loads(line)
        seq_ok &= (rec.get("seq") == i + 1 and rec.get("prev_entry_sha256") == prev)
        prev = sha256_hex(line.encode())
    check("HEADS_LOG_HASH_CHAIN", seq_ok, "sequence break or entry-chain mismatch")
    if bundle_path:
        bundle = json.load(open(bundle_path))
        digest = hashlib.sha256(open(bundle_path, "rb").read()).hexdigest()
        wanted = heads_entries_from_bundle(bundle, digest)
        have = [{k: json.loads(ln).get(k) for k in wanted[0]} for ln in lines]
        for entry in wanted:
            check(f"HEADS_MEMBERSHIP:{entry['chain']}", entry in have,
                  "bundle head not committed in the heads log")
    return _finish()


# ================================== CLI ======================================

def _finish() -> int:
    total = _passed + len(_failures)
    print(f"CHECKS_PASSED={_passed}/{total}")
    verdict = not _failures
    print(f"STRANGERS_VERIFIER_{'PASS' if verdict else 'FAIL'}")
    return 0 if verdict else 1


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    mode, args = argv[1], argv[2:]
    expected = [a.split("=", 1)[1] if "=" in a else args[i + 1]
                for i, a in enumerate(args) if a.startswith("--expect-signer")]
    pos = [a for i, a in enumerate(args)
           if not a.startswith("--")
           and not (i > 0 and args[i - 1].startswith("--") and "=" not in args[i - 1])]
    print(f"VERIFIER_SPEC={VERIFIER_SPEC}")
    if mode == "verify-evolution":
        bundle = json.load(open(pos[0]))
        check("BUNDLE_SPEC_KNOWN", str(bundle.get("spec", "")).startswith("sealed-evolution-replay-bundle/"))
        verify_evolution(bundle, expected)
        return _finish()
    if mode == "verify-transfer":
        bundle, receipt = json.load(open(pos[0])), json.load(open(pos[1]))
        champ = None
        for i, a in enumerate(args):
            if a == "--champion-bundle":
                champ = args[i + 1]
            elif a.startswith("--champion-bundle="):
                champ = a.split("=", 1)[1]
        check("BUNDLE_SPEC_KNOWN", str(bundle.get("spec", "")).startswith("w-transfer-bundle/"))
        verify_transfer(bundle, receipt, expected, champ)
        return _finish()
    if mode == "verify-recursive":
        verify_recursive(json.load(open(pos[0])))
        return _finish()
    if mode == "heads-append":
        return heads_append(pos[0], pos[1])
    if mode == "heads-verify":
        b = None
        for i, a in enumerate(args):
            if a == "--bundle":
                b = args[i + 1]
            elif a.startswith("--bundle="):
                b = a.split("=", 1)[1]
        return heads_verify(pos[0], b)
    print(f"unknown mode: {mode}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
