"""V9 stranger's verifier: RFC 8032 known-answer vectors, e-value math parity
with the repository implementation, PEM/key-id parity, signed-chain
verification of repository-signed chains in a REPO-ISOLATED child process,
and transparency heads-log integrity. Self-contained: no gate artifacts."""

import base64
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "verifier_standalone" / "strangers_verifier.py"

spec = importlib.util.spec_from_file_location("strangers_verifier", VERIFIER)
sv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sv)


# ---------- the standalone file is genuinely standalone -----------------------

def test_verifier_imports_nothing_beyond_stdlib():
    source = VERIFIER.read_text()
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            root = stripped.split()[1].split(".")[0]
            assert root in {"annotations", "base64", "hashlib", "json", "math", "sys",
                            "__future__"}, f"non-stdlib import: {stripped}"


def test_verifier_runs_isolated_without_repo():
    proc = subprocess.run([sys.executable, "-I", str(VERIFIER)],
                          capture_output=True, text=True)
    assert proc.returncode == 2  # usage banner, no import errors
    assert "STRANGER" in proc.stdout


# ---------- Ed25519 known-answer vectors (RFC 8032 §7.1) ----------------------

def test_ed25519_rfc8032_vector_1_empty_message():
    pk = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a"
                       "0ee172f3daa62325af021a68f707511a")
    sig = bytes.fromhex("e5564300c360ac729086e2cc806e828a"
                        "84877f1eb8e5d974d873e06522490155"
                        "5fb8821590a33bacc61e39701cf9b46b"
                        "d25bf5f0595bbe24655141438e7a100b")
    assert sv.ed25519_verify(pk, b"", sig) is True


def test_ed25519_rfc8032_vector_2_one_byte():
    pk = bytes.fromhex("3d4017c3e843895a92b70aa74d1b7ebc"
                       "9c982ccf2ec4968cc0cd55f12af4660c")
    sig = bytes.fromhex("92a009a9f0d4cab8720e820b5f642540"
                        "a2b27b5416503f8fb3762223ebdb69da"
                        "085ac1e43e15996e458f3613d0f11d8c"
                        "387b2eaeb4302aeeb00d291612bb0c00")
    assert sv.ed25519_verify(pk, b"\x72", sig) is True


def test_ed25519_rejects_flipped_bit_and_malformed():
    pk = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a"
                       "0ee172f3daa62325af021a68f707511a")
    sig = bytearray(bytes.fromhex(
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"))
    sig[10] ^= 1
    assert sv.ed25519_verify(pk, b"", bytes(sig)) is False
    assert sv.ed25519_verify(pk, b"x", b"short") is False
    assert sv.ed25519_verify(b"short", b"", bytes(64)) is False


# ---------- parity with the repository implementations ------------------------

def test_log_e_micro_matches_repository_exactly():
    sys.path.insert(0, str(ROOT / "src"))
    from eagle_eye.eprocess import log_e_micro as repo_log_e
    for wins, losses in [(0, 0), (1, 0), (0, 1), (4, 0), (2, 2), (3, 1), (21, 9),
                         (30, 0), (15, 15), (40, 0), (0, 40), (26, 14)]:
        assert sv.log_e_micro(wins, losses) == repo_log_e(wins, losses), (wins, losses)


def test_pem_parse_and_key_id_match_repository():
    sys.path.insert(0, str(ROOT / "src"))
    from eagle_eye.signing import generate_demo_keypair, key_id
    _, public_pem = generate_demo_keypair()
    parsed = sv.parse_ed25519_pem(public_pem.decode())
    assert parsed is not None
    raw, kid = parsed
    assert len(raw) == 32
    assert kid == key_id(public_pem)


def test_signature_verification_matches_repository_signing():
    sys.path.insert(0, str(ROOT / "src"))
    from eagle_eye.signing import generate_demo_keypair, key_id, sign
    private_pem, public_pem = generate_demo_keypair()
    raw, _ = sv.parse_ed25519_pem(public_pem.decode())
    message = b"the stranger trusts mathematics, not us"
    assert sv.ed25519_verify(raw, message, sign(message, private_pem)) is True
    assert sv.ed25519_verify(raw, message + b"!", sign(message, private_pem)) is False


def test_promotion_gate_port_matches_repository():
    sys.path.insert(0, str(ROOT / "src"))
    from eagle_eye.evolution import apply_promotion_gates as repo_gates
    fragment = {
        "statistics": {"significant_improvement": False, "ci_upper_micro": 1200,
                       "n_paired": 45},
        "challenger_aggregates": {
            "scored_count": 45, "abstentions_standard": 0, "abstentions_probe": 3,
            "probe_count": 3,
            "metrics": {"permutation_spread_max": 10_000, "coverage80": 810_000,
                        "nll_temporal_ood": 900_000}},
        "champion_aggregates": {
            "scored_count": 45,
            "metrics": {"coverage80": 800_000, "nll_temporal_ood": 950_000}},
    }
    assert sv.apply_promotion_gates(fragment) == repo_gates(fragment)
    fragment["challenger_aggregates"]["abstentions_standard"] = 2
    assert sv.apply_promotion_gates(fragment) == repo_gates(fragment)
    fragment["challenger_aggregates"]["abstentions_standard"] = 0
    fragment["challenger_aggregates"]["metrics"]["coverage80"] = 600_000
    assert sv.apply_promotion_gates(fragment) == repo_gates(fragment)


# ---------- chain verification against repository-signed chains ---------------

def _signed_demo_chain(rows: int = 4):
    sys.path.insert(0, str(ROOT / "src"))
    from eagle_eye.signed_chain import SignedChain
    from eagle_eye.signing import generate_demo_keypair
    private_key, public_key = generate_demo_keypair()
    chain = SignedChain(tenant_id="tenant-demo", run_id="run-sv-test",
                        chain_id="sv-test", private_key=private_key,
                        public_key=public_key)
    for i in range(rows):
        chain.append({"kind": "demo", "index": i, "value_micro": 1000 * i})
    registry = {"trusted_signers": [{"key_id": chain.signer_key_id,
                                     "public_key_pem": public_key.decode()}]}
    return chain, registry


def test_repository_signed_chain_verifies_and_tamper_fails(tmp_path):
    chain, registry = _signed_demo_chain()
    good = {"chains": {"demo": {"rows": chain.rows, "anchor": chain.anchor()}},
            "signer_registry": registry}
    reg = sv.load_registry(good, [])
    assert reg is not None
    assert sv.verify_signed_chain("T", good["chains"]["demo"], reg) is True
    bad = json.loads(json.dumps(good))
    bad["chains"]["demo"]["rows"][1]["body"]["value_micro"] = 999_999
    assert sv.verify_signed_chain("T2", bad["chains"]["demo"], reg) is False
    trunc = json.loads(json.dumps(good))
    trunc["chains"]["demo"]["rows"] = trunc["chains"]["demo"]["rows"][:-1]
    assert sv.verify_signed_chain("T3", trunc["chains"]["demo"], reg) is False


# ---------- transparency heads log ---------------------------------------------

def test_heads_log_roundtrip_and_tamper(tmp_path):
    chain, registry = _signed_demo_chain(rows=2)
    bundle = {"spec": "sealed-evolution-replay-bundle/4.0",
              "chains": {"demo": {"rows": chain.rows, "anchor": chain.anchor()}},
              "signer_registry": registry}
    bpath = tmp_path / "bundle.json"
    bpath.write_text(json.dumps(bundle, sort_keys=True))
    heads = tmp_path / "HEADS.jsonl"
    run = lambda *a: subprocess.run([sys.executable, "-I", str(VERIFIER), *a],
                                    capture_output=True, text=True)
    assert run("heads-append", str(heads), str(bpath)).returncode == 0
    assert run("heads-append", str(heads), str(bpath)).returncode == 0  # 2 entries
    ver = run("heads-verify", str(heads), "--bundle", str(bpath))
    assert ver.returncode == 0 and "STRANGERS_VERIFIER_PASS" in ver.stdout
    lines = heads.read_text().splitlines()
    assert len(lines) == 2
    tampered = tmp_path / "H2.jsonl"
    entry = json.loads(lines[0])
    entry["length"] = 99
    tampered.write_text(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n"
                        + "\n".join(lines[1:]) + "\n")
    bad = run("heads-verify", str(tampered))
    assert bad.returncode == 1 and "HEADS_LOG_HASH_CHAIN" in bad.stdout


def test_sign_counts_arithmetic_neutral_and_monotone():
    assert sv.log_e_micro(0, 0) == 0
    values = [sv.log_e_micro(k, 10 - k) for k in range(11)]
    assert values == sorted(values)
    with pytest.raises(ValueError):
        sv.log_e_micro(-1, 2)
