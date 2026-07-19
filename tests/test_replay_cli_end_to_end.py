"""V4 blocker 3: the ACTUAL replay CLI, exercised end to end on a non-vacuous
fixture run (real sealed looks spent), plus a fast subset of the mutation
battery. The complete 17-mutation battery runs in `make check`
(scripts/replay_mutation_battery.py) against the canonical benchmark bundle.
"""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def fixture_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("evo-e2e")
    import importlib.util
    spec = importlib.util.spec_from_file_location("rse_e2e", ROOT / "scripts" / "run_sealed_evolution.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # secret "fx2" is a PRECOMMITTED test fixture chosen because it provably
    # spends a sealed look (non-vacuous replay, 1 SUCCEEDED look at seed 550
    # under the stable generation seeding)
    code = module.main(live_seed=550, evaluator_secret="fx2",
                       out_dir=out, suite_scale=1)
    assert code == 0
    return out


def _replay(bundle_path: Path, *flags: str) -> subprocess.CompletedProcess:
    import os
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "replay_sealed_evolution.py"),
         str(bundle_path), *flags],
        capture_output=True, text=True, cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")})


def test_replay_cli_passes_non_vacuously_on_real_bundle(fixture_run):
    result = _replay(fixture_run / "REPLAY_BUNDLE.json")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REPLAY_RESULT=PASS_FULL_DECISION" in result.stdout
    assert "VACUOUS" not in result.stdout
    line = next(l for l in result.stdout.splitlines() if l.startswith("DECISIONS_RECOMPUTED="))
    recomputed = int(line.split("=")[1].split()[0])
    mismatched = int(line.split("MISMATCHED=")[1])
    assert recomputed > 0 and mismatched == 0


@pytest.mark.parametrize("name,mutate", [
    ("bundle_spec", lambda b: b.__setitem__("spec", "sealed-evolution-replay-bundle/3.0")),
    ("base_registry_manifest", lambda b: b.__setitem__(
        "base_registry_manifest_sha256", "0" * 64)),
    ("code_revision", lambda b: b["run_context"].__setitem__("code_revision", "deadbeefdeadbeef")),
    ("evaluator_secret", lambda b: b["evaluator_reveal"].__setitem__(
        "evaluator_secret", "not-the-real-secret")),
    ("cycle_cutoffs", lambda b: b.__setitem__("cycle_cutoffs", b["cycle_cutoffs"][:-1])),
])
def test_mutated_binding_fields_fail_replay(fixture_run, tmp_path, name, mutate):
    bundle = json.loads((fixture_run / "REPLAY_BUNDLE.json").read_text())
    mutated = copy.deepcopy(bundle)
    mutate(mutated)
    path = tmp_path / f"mutated-{name}.json"
    path.write_text(json.dumps(mutated, sort_keys=True))
    result = _replay(path, "--fail-fast", "--skip-node")
    assert result.returncode != 0, f"mutation {name} was NOT detected:\n{result.stdout}"


def test_unmutated_bundle_still_passes_with_fail_fast(fixture_run):
    result = _replay(fixture_run / "REPLAY_BUNDLE.json", "--fail-fast", "--skip-node")
    assert result.returncode == 0, result.stdout + result.stderr
