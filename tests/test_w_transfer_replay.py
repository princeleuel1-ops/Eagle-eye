from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _pythonpath_env() -> dict[str, str]:
    return {**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")}


@pytest.fixture(scope="module")
def transfer_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("w-transfer")
    champion_dir = root / "champion"
    transfer_dir = root / "transfer"

    spec = importlib.util.spec_from_file_location("rse_transfer", ROOT / "scripts" / "run_sealed_evolution.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    code = module.main(live_seed=550, evaluator_secret="fx2", out_dir=champion_dir, suite_scale=1)
    assert code == 0

    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_w_transfer.py"),
            "--champion-bundle",
            str(champion_dir / "REPLAY_BUNDLE.json"),
            "--out",
            str(transfer_dir),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=900,
        env=_pythonpath_env(),
    )
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-4000:]
    bundle_path = transfer_dir / "W_TRANSFER_BUNDLE.json"
    receipt_path = transfer_dir / "W_TRANSFER_RECEIPT.json"
    return {
        "stdout": proc.stdout,
        "bundle_path": bundle_path,
        "receipt_path": receipt_path,
        "bundle": json.loads(bundle_path.read_text()),
        "receipt": json.loads(receipt_path.read_text()),
    }


def _replay(bundle_path: Path, receipt_path: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "replay_w_transfer.py"),
            str(bundle_path),
            str(receipt_path),
            *flags,
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=900,
        env=_pythonpath_env(),
    )


def _write_mutated_pair(
    source: dict[str, object],
    tmp_path: Path,
    *,
    mutate_bundle=None,
    mutate_receipt=None,
) -> tuple[Path, Path]:
    bundle = copy.deepcopy(source["bundle"])
    receipt = copy.deepcopy(source["receipt"])
    if mutate_bundle is not None:
        mutate_bundle(bundle, receipt)
    if mutate_receipt is not None:
        mutate_receipt(bundle, receipt)
    bundle_path = tmp_path / "W_TRANSFER_BUNDLE.json"
    receipt_path = tmp_path / "W_TRANSFER_RECEIPT.json"
    bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True))
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True))
    return bundle_path, receipt_path


def _mutate_family_release(bundle, receipt):
    bundle["protocol"]["family_manifests"][1]["family_release"] = "forged-family/9.9"


def _mutate_family_id(bundle, receipt):
    bundle["evaluations"][0]["family_id"] = "forged-family"


def _mutate_source_commitment(bundle, receipt):
    bundle["protocol"]["family_manifests"][1]["source_commitment"] = "f" * 64


def _mutate_duplicate_seed(bundle, receipt):
    bundle["evaluations"][1]["world_seed"] = bundle["evaluations"][0]["world_seed"]


def _mutate_missing_seed(bundle, receipt):
    bundle["evaluations"].pop(0)


def _mutate_reordered_seed_rows(bundle, receipt):
    bundle["evaluations"][0], bundle["evaluations"][1] = bundle["evaluations"][1], bundle["evaluations"][0]


def _mutate_registry_release(bundle, receipt):
    bundle["evaluations"][0]["registry_release"] = "forged-registry/9.9"


def _mutate_deleted_case(bundle, receipt):
    bundle["evaluations"][0]["case_rows"].pop()


def _mutate_duplicate_case(bundle, receipt):
    bundle["evaluations"][0]["case_rows"][1] = copy.deepcopy(bundle["evaluations"][0]["case_rows"][0])


def _mutate_case_index(bundle, receipt):
    bundle["evaluations"][0]["case_rows"][0]["case_index"] += 1


def _mutate_champion_substitution(bundle, receipt):
    bundle["champion_config"]["selector.k_max"] = 12


def _mutate_baseline_substitution(bundle, receipt):
    bundle["baseline_release"] = "forged-baseline/9.9"


def _mutate_first_observation(bundle, receipt):
    for evaluation in bundle["evaluations"]:
        for case in evaluation["case_rows"]:
            if case["target"]["observations"]:
                case["target"]["observations"][0]["log_delay_days"] += 0.25
                return
    raise AssertionError("no observed case found")


def _mutate_first_truth(bundle, receipt):
    bundle["evaluations"][0]["case_rows"][0]["truth"]["outcomes"]["wait_incumbent"]["log_final_delay"] += 0.1


def _mutate_first_score(bundle, receipt):
    bundle["evaluations"][0]["case_rows"][0]["champion_score"]["nll_micro"] -= 1


def _mutate_first_cluster_sign(bundle, receipt):
    bundle["evaluations"][0]["cluster_signs"]["nll"] = "loss"


def _mutate_deleted_family(bundle, receipt):
    victim = next(
        family["family_id"]
        for family in reversed(bundle["protocol"]["family_manifests"])
        if family["structural_parent"] is None
    )
    bundle["evaluations"] = [row for row in bundle["evaluations"] if row["family_id"] != victim]


def _mutate_truncated_history(bundle, receipt):
    bundle["chains"]["transfer"]["rows"] = bundle["chains"]["transfer"]["rows"][:-1]


def _mutate_claim(bundle, receipt):
    receipt["headline_claim_crossed"] = not receipt["headline_claim_crossed"]


def _mutate_crossing_index(bundle, receipt):
    receipt["standing"][0]["first_crossing_index"] = (
        1 if receipt["standing"][0]["first_crossing_index"] is None
        else receipt["standing"][0]["first_crossing_index"] + 1
    )


def _mutate_receipt_id(bundle, receipt):
    receipt["receipt_id"] = "wtr-forged000000"


def test_w_transfer_replay_passes_non_vacuously_on_real_bundle(transfer_run):
    result = _replay(transfer_run["bundle_path"], transfer_run["receipt_path"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "W_TRANSFER_REPLAY=PASS_COMPLETE" in result.stdout
    assert "UNITS_REGENERATED=" in result.stdout
    assert transfer_run["receipt"]["history_row_count"] > 0


@pytest.mark.parametrize(
    ("name", "mutate_bundle", "mutate_receipt"),
    [
        ("family_release", _mutate_family_release, None),
        ("family_id", _mutate_family_id, None),
        ("source_commitment", _mutate_source_commitment, None),
        ("duplicate_seed", _mutate_duplicate_seed, None),
        ("missing_seed", _mutate_missing_seed, None),
        ("reordered_seed_rows", _mutate_reordered_seed_rows, None),
        ("registry_release", _mutate_registry_release, None),
        ("deleted_case", _mutate_deleted_case, None),
        ("duplicate_case", _mutate_duplicate_case, None),
        ("case_index", _mutate_case_index, None),
        ("champion_substitution", _mutate_champion_substitution, None),
        ("baseline_substitution", _mutate_baseline_substitution, None),
        ("observation", _mutate_first_observation, None),
        ("truth", _mutate_first_truth, None),
        ("score", _mutate_first_score, None),
        ("cluster_sign", _mutate_first_cluster_sign, None),
        ("deleted_family", _mutate_deleted_family, None),
        ("truncated_history", _mutate_truncated_history, None),
        ("claim", None, _mutate_claim),
        ("crossing_index", None, _mutate_crossing_index),
        ("receipt_id", None, _mutate_receipt_id),
    ],
)
def test_mutated_w_transfer_bindings_fail_replay(transfer_run, tmp_path, name, mutate_bundle, mutate_receipt):
    bundle_path, receipt_path = _write_mutated_pair(
        transfer_run,
        tmp_path,
        mutate_bundle=mutate_bundle,
        mutate_receipt=mutate_receipt,
    )
    result = _replay(bundle_path, receipt_path, "--fail-fast")
    assert result.returncode != 0, f"mutation {name} was not detected:\n{result.stdout}"
