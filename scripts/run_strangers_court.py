"""V9 strangers court — the standalone verifier must accept every real bundle
and refuse every doctored one, in a child process, with ZERO repository trust
(`python3 -I`, no PYTHONPATH, system interpreter, stdlib only).

Positive controls: the real evolution bundle, transfer bundle + receipt, and
recursive receipt from THIS run's earlier gates must PASS.

Doctored battery (each case must FAIL with the named check):
  sig_forged           one flipped byte in one row signature
  body_spliced         lineage diff mutated without rehash
  row_reordered        two chain rows swapped
  tail_truncated       last row dropped, anchor kept
  resign_attack        diff mutated, every row/anchor re-hashed, re-linked and
                       re-signed by an ATTACKER key, registry swapped — pure
                       cryptographic consistency holds, so only semantic
                       recomputation (candidate ids) can catch it
  pinned_resign        same attack, verifier run with --expect-signer pinning
  reveal_tampered      evaluator secret altered
  wealth_inflated      transfer standing wealth bumped above threshold
  claim_flipped        headline claim swapped to EARNED
  heads_tampered       transparency log entry mutated after append

Writes artifacts/strangers/STRANGERS_COURT_RECEIPT.json; exit 0 only if every
control passes and every doctored case fails closed with the expected check.
"""

from __future__ import annotations

import base64
import copy
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eagle_eye.prior_registry import canonical_bytes, sha256_hex  # noqa: E402
from eagle_eye.signing import generate_demo_keypair, key_id, sign  # noqa: E402

VERIFIER = ROOT / "verifier_standalone" / "strangers_verifier.py"
OUT = ROOT / "artifacts" / "strangers"
STRANGER_PY = shutil.which("python3") or sys.executable  # system interpreter, not venv


def run_verifier(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run([STRANGER_PY, "-I", str(VERIFIER), *args],
                          capture_output=True, text=True, cwd=OUT)
    return proc.returncode, proc.stdout


def write(path: Path, obj) -> Path:
    path.write_text(json.dumps(obj, indent=1, sort_keys=True))
    return path


def resign_chain(chain: dict, private_pem: bytes, signer: str) -> None:
    prev = "0" * 64
    for row in chain["rows"]:
        core = {"chain_id": row["chain_id"], "tenant_id": row["tenant_id"],
                "run_id": row["run_id"], "sequence": row["sequence"],
                "previous_hash": prev, "body": row["body"]}
        row["previous_hash"] = prev
        row["row_hash"] = sha256_hex(canonical_bytes(core))
        row["signer_key_id"] = signer
        row["signature_b64"] = base64.b64encode(
            sign(row["row_hash"].encode(), private_pem)).decode()
        prev = row["row_hash"]
    anchor = chain["anchor"]
    anchor["length"] = len(chain["rows"])
    anchor["head"] = prev
    anchor["signer_key_id"] = signer
    body = {k: anchor[k] for k in ("chain_id", "tenant_id", "run_id",
                                   "length", "head", "signer_key_id")}
    anchor["anchor_signature_b64"] = base64.b64encode(
        sign(canonical_bytes(body), private_pem)).decode()


def main() -> int:
    started = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    evo_path = ROOT / "artifacts" / "evolution" / "latest" / "REPLAY_BUNDLE.json"
    wtb_path = ROOT / "artifacts" / "transfer" / "latest" / "W_TRANSFER_BUNDLE.json"
    wtr_path = ROOT / "artifacts" / "transfer" / "latest" / "W_TRANSFER_RECEIPT.json"
    rec_path = ROOT / "artifacts" / "recursive" / "RECURSIVE_EVOLUTION_RECEIPT.json"
    for p in (evo_path, wtb_path, wtr_path, rec_path):
        if not p.exists():
            print(f"STRANGERS_COURT_FAIL=missing prerequisite {p}")
            return 1
    evo = json.loads(evo_path.read_text())
    wtb = json.loads(wtb_path.read_text())
    wtr = json.loads(wtr_path.read_text())
    honest_signers = [s["key_id"] for s in evo["signer_registry"]["trusted_signers"]]

    cases = []

    def case(name: str, args: list[str], *, expect_pass: bool, expect_check: str = "") -> None:
        code, out = run_verifier(args)
        passed_banner = "STRANGERS_VERIFIER_PASS" in out
        if expect_pass:
            ok = code == 0 and passed_banner
        else:
            ok = code == 1 and not passed_banner and (expect_check in out)
        cases.append({"case": name, "expect_pass": expect_pass,
                      "expected_check": expect_check, "exit": code, "ok": ok})
        print(f"{'OK  ' if ok else 'FAIL'} court:{name}")

    # ---- positive controls -------------------------------------------------
    case("pass_evolution", ["verify-evolution", str(evo_path)], expect_pass=True)
    case("pass_evolution_pinned",
         ["verify-evolution", str(evo_path)]
         + [f"--expect-signer={k}" for k in honest_signers], expect_pass=True)
    case("pass_transfer", ["verify-transfer", str(wtb_path), str(wtr_path)],
         expect_pass=True)
    case("pass_recursive", ["verify-recursive", str(rec_path)], expect_pass=True)

    # ---- doctored battery ---------------------------------------------------
    d = copy.deepcopy(evo)
    sig = bytearray(base64.b64decode(d["chains"]["lineage"]["rows"][3]["signature_b64"]))
    sig[7] ^= 0x41
    d["chains"]["lineage"]["rows"][3]["signature_b64"] = base64.b64encode(bytes(sig)).decode()
    case("sig_forged", ["verify-evolution", str(write(OUT / "d1.json", d))],
         expect_pass=False, expect_check="ROW_4_SIGNATURE")

    d = copy.deepcopy(evo)
    row = d["chains"]["lineage"]["rows"][2]
    (key, val), = row["body"]["candidate"]["diff"].items()
    row["body"]["candidate"]["diff"] = {key: val if key != "selector.k_max" else 8}
    row["body"]["candidate"]["diff"][key] = 12 if val != 12 else 8
    case("body_spliced", ["verify-evolution", str(write(OUT / "d2.json", d))],
         expect_pass=False, expect_check="ROW_3_INTEGRITY")

    d = copy.deepcopy(evo)
    rows = d["chains"]["lineage"]["rows"]
    rows[1], rows[2] = rows[2], rows[1]
    case("row_reordered", ["verify-evolution", str(write(OUT / "d3.json", d))],
         expect_pass=False, expect_check="ROW_2_INTEGRITY")

    d = copy.deepcopy(evo)
    d["chains"]["lineage"]["rows"] = d["chains"]["lineage"]["rows"][:-1]
    case("tail_truncated", ["verify-evolution", str(write(OUT / "d4.json", d))],
         expect_pass=False, expect_check="ANCHOR")

    # full re-sign attack: cryptography internally consistent; semantics must catch
    d = copy.deepcopy(evo)
    attacker_priv, attacker_pub = generate_demo_keypair()
    attacker_id = key_id(attacker_pub)
    target = next(r for r in d["chains"]["lineage"]["rows"]
                  if r["body"]["candidate"]["diff"])
    (key, val), = target["body"]["candidate"]["diff"].items()
    grid = {"selector.k_max": [8, 10, 12], "selector.min_score_milli": [3500, 4000, 4500, 5000, 6000]}
    alt = [v for v in grid.get(key, [val, 0]) if v != val]
    target["body"]["candidate"]["diff"] = {key: alt[0] if alt else 0}
    d["signer_registry"]["trusted_signers"] = [
        {"key_id": attacker_id, "public_key_pem": attacker_pub.decode()}]
    for chain in d["chains"].values():
        resign_chain(chain, attacker_priv, attacker_id)
    p5 = write(OUT / "d5.json", d)
    case("resign_attack", ["verify-evolution", str(p5)],
         expect_pass=False, expect_check="LINEAGE_IDS_AND_DECISIONS_RECOMPUTED")
    case("pinned_resign", ["verify-evolution", str(p5),
                           f"--expect-signer={honest_signers[0]}"],
         expect_pass=False, expect_check="EXPECTED_SIGNER_PRESENT")

    d = copy.deepcopy(evo)
    d["evaluator_reveal"]["evaluator_secret"] = "not-the-real-secret"
    case("reveal_tampered", ["verify-evolution", str(write(OUT / "d6.json", d))],
         expect_pass=False, expect_check="COMMIT_REVEAL")

    r = copy.deepcopy(wtr)
    r["standing"][0]["cumulative_log_e_micro"] = 99_000_000
    r["standing"][0]["crossed"] = True
    case("wealth_inflated", ["verify-transfer", str(wtb_path),
                             str(write(OUT / "d7.json", r))],
         expect_pass=False, expect_check="STREAM_WEALTH_RECOMPUTED")

    r = copy.deepcopy(wtr)
    r["headline_claim_status"] = "ALIEN_TRANSFER_EVIDENCE_EARNED"
    r["headline_claim_crossed"] = True
    case("claim_flipped", ["verify-transfer", str(wtb_path),
                           str(write(OUT / "d8.json", r))],
         expect_pass=False, expect_check="HEADLINE_CLAIM_CONSISTENT")

    # ---- transparency heads log ---------------------------------------------
    heads = OUT / "HEADS.jsonl"
    heads.unlink(missing_ok=True)
    code1, _ = run_verifier(["heads-append", str(heads), str(evo_path)])
    code2, _ = run_verifier(["heads-append", str(heads), str(wtb_path)])
    code3, out3 = run_verifier(["heads-verify", str(heads), "--bundle", str(evo_path)])
    heads_ok = code1 == 0 and code2 == 0 and code3 == 0 and "STRANGERS_VERIFIER_PASS" in out3
    cases.append({"case": "heads_roundtrip", "expect_pass": True, "ok": heads_ok})
    print(f"{'OK  ' if heads_ok else 'FAIL'} court:heads_roundtrip")
    lines = heads.read_text().splitlines()
    mutated = lines[:]
    mutated[0] = mutated[0].replace('"length":', '"length_x":', 1) if '"length":' in mutated[0] else mutated[0] + " "
    (OUT / "HEADS_TAMPERED.jsonl").write_text("\n".join(mutated) + "\n")
    code4, out4 = run_verifier(["heads-verify", str(OUT / "HEADS_TAMPERED.jsonl")])
    tamper_ok = code4 == 1 and "HEADS_LOG_HASH_CHAIN" in out4
    cases.append({"case": "heads_tampered", "expect_pass": False,
                  "expected_check": "HEADS_LOG_HASH_CHAIN", "ok": tamper_ok})
    print(f"{'OK  ' if tamper_ok else 'FAIL'} court:heads_tampered")

    all_ok = all(c["ok"] for c in cases)
    receipt = {
        "spec": "eagle-eye-strangers-court/1.0",
        "verifier_sha256": sha256_hex(VERIFIER.read_bytes()),
        "stranger_interpreter": STRANGER_PY,
        "isolation": "python3 -I (no env, no site, no repository imports)",
        "cases": cases,
        "passed": sum(1 for c in cases if c["ok"]),
        "total": len(cases),
        "external_action": False,
        "elapsed_s": round(time.time() - started, 1),
    }
    (OUT / "STRANGERS_COURT_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True))
    print(f"COURT_CASES={receipt['passed']}/{receipt['total']}")
    print(f"VERIFIER_SHA256={receipt['verifier_sha256']}")
    print(f"STRANGERS_COURT_PASS={'true' if all_ok else 'false'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
