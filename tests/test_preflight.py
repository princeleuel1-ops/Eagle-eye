"""V5 setup-portability: the preflight detector must SURFACE launcher
contamination (never silently erase it) and pass on a clean environment."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "scripts" / "preflight.py"


def _run(env_overrides, strict=False):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    env.update(env_overrides)
    cmd = [sys.executable, str(PREFLIGHT)] + (["--strict"] if strict else [])
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env)


def test_clean_environment_passes():
    r = _run({"PYTHONPATH": "src"})  # the project's own root is not foreign
    assert "PREFLIGHT=OK" in r.stdout
    assert r.returncode == 0


def test_foreign_pythonpath_is_surfaced():
    r = _run({"PYTHONPATH": "/Users/Apple/.hermes/hermes-agent"})
    assert "HAZARD PYTHONPATH" in r.stdout
    assert "/Users/Apple/.hermes/hermes-agent" in r.stdout
    assert "env -u PYTHONPATH" in r.stdout  # guidance, not mutation


def test_pythonhome_is_surfaced(monkeypatch):
    # PYTHONHOME set to a foreign path breaks the interpreter before it can
    # print, so the detector is exercised in-process (not via subprocess).
    import importlib.util
    spec = importlib.util.spec_from_file_location("preflight_mod", PREFLIGHT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setenv("PYTHONHOME", "/some/foreign/home")
    monkeypatch.delenv("PYTHONPATH", raising=False)
    a = mod.analyze()
    assert any(var == "PYTHONHOME" for var, _, _ in a["hazards"])


def test_strict_mode_fails_closed_on_hazard():
    r = _run({"PYTHONPATH": "/opt/foreign/agent"}, strict=True)
    assert r.returncode == 3
    assert "PREFLIGHT=FAIL" in r.stdout


def test_preflight_does_not_mutate_caller_env():
    # the caller's PYTHONPATH must be unchanged after preflight runs
    r = _run({"PYTHONPATH": "/opt/foreign/agent",
              "ECHO_BACK": "1"})
    # preflight prints hazards but cannot reach back into the parent shell;
    # we assert it reports rather than clears (no "cleared"/"unset" language)
    assert "cleared" not in r.stdout.lower()
    assert "unset PYTHONPATH" not in r.stdout  # it SShows env -u guidance instead
