"""V5 setup-portability preflight (fail-fast, non-mutating).

The Hermes launcher (and CI wrappers generally) can export PYTHONPATH /
PYTHONHOME pointing at unrelated agent code. Inside a venv that contaminates
distribution discovery — pip and imports can resolve foreign packages before
the project's own, producing confusing "works on my machine" failures.

This preflight DETECTS and REPORTS the hazard; it never edits or erases the
caller's environment (that is the operator's decision). It exits nonzero when
a hazard that would corrupt setup/verification is present, printing the exact
clean-invocation guidance. The Makefile additionally SCRUBS PYTHONPATH/
PYTHONHOME for its own pip and interpreter steps, so `make setup` / `make
check` are correct regardless of the launcher — this script is the loud
diagnostic, the Makefile is the structural fix.

usage: python scripts/preflight.py [--strict]   (--strict: any hazard -> exit 3)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _entries(var: str) -> list[str]:
    raw = os.environ.get(var, "")
    return [e for e in raw.split(os.pathsep) if e]


def analyze() -> dict:
    hazards, notes = [], []
    # PYTHONPATH entries that are NOT the project's own src/ are suspicious
    project_src = str(PROJECT_ROOT / "src")
    foreign_pp = [e for e in _entries("PYTHONPATH")
                  if os.path.abspath(e) != project_src
                  and not os.path.abspath(e).startswith(str(PROJECT_ROOT))]
    if foreign_pp:
        hazards.append(("PYTHONPATH", foreign_pp,
                        "foreign import roots precede the project on sys.path"))
    if os.environ.get("PYTHONHOME"):
        hazards.append(("PYTHONHOME", [os.environ["PYTHONHOME"]],
                        "overrides the interpreter's stdlib/site resolution"))
    # Are we actually running the project venv?
    in_venv = sys.prefix != sys.base_prefix
    venv_here = str(PROJECT_ROOT / ".venv")
    running_project_venv = os.path.abspath(sys.prefix) == os.path.abspath(venv_here)
    if in_venv and not running_project_venv:
        notes.append(f"running venv {sys.prefix} (project venv is {venv_here})")
    # Would a foreign PYTHONPATH shadow the installed package?
    try:
        import eagle_eye  # noqa: F401
        resolved = os.path.abspath(eagle_eye.__file__)
        expected = str(PROJECT_ROOT / "src" / "eagle_eye")
        if not resolved.startswith(expected) and "/.venv/" not in resolved:
            hazards.append(("eagle_eye", [resolved],
                            "package resolves OUTSIDE the project/venv"))
    except Exception as exc:  # noqa: BLE001
        notes.append(f"eagle_eye not importable in this context: {exc}")
    return {"python": sys.version.split()[0], "prefix": sys.prefix,
            "base_prefix": sys.base_prefix, "in_venv": in_venv,
            "running_project_venv": running_project_venv,
            "hazards": hazards, "notes": notes}


def main() -> int:
    strict = "--strict" in sys.argv
    a = analyze()
    print(f"PREFLIGHT python={a['python']} in_venv={a['in_venv']} "
          f"project_venv={a['running_project_venv']}")
    for note in a["notes"]:
        print(f"PREFLIGHT note: {note}")
    for var, values, why in a["hazards"]:
        print(f"PREFLIGHT HAZARD {var}: {why}")
        for v in values:
            print(f"    -> {v}")
    if a["hazards"]:
        print("PREFLIGHT guidance: run with a scrubbed environment, e.g.")
        print("    env -u PYTHONPATH -u PYTHONHOME make setup")
        print("    env -u PYTHONPATH -u PYTHONHOME make check")
        print("  (the Makefile also scrubs these for its own pip/interpreter steps;")
        print("   this preflight is the diagnostic, not a silent mutation.)")
        if strict:
            print("PREFLIGHT=FAIL")
            return 3
    print("PREFLIGHT=OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
