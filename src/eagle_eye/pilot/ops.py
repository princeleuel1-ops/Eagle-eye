"""Operator command surface — one coherent local pilot interface.

    make pilot-setup          initialize home, migrate storage, provision the
                              evaluator client token (idempotent)
    make pilot-up             start evaluator service + cockpit server
                              (pidfiles, stale-listener detection, health wait)
    make pilot-check          health + readiness + migration status (exit 0/1)
    make pilot-smoke          the full product loop end-to-end over HTTP
    make pilot-backup         consistent backup with hash manifest
    make pilot-restore-check  restore into scratch, reproduce audit heads
    make pilot-down           graceful shutdown + socket/pid cleanup

Everything is rooted in EAGLE_EYE_PILOT_HOME (default artifacts/pilot/home).
All of it is a LOCAL PILOT REFERENCE deployment: one host, fixture tenant,
labeled dev issuer, external execution fail-closed.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

import hashlib
import tempfile

from .observability import get_logger, log_event
from .storage import PilotStorage

_LOG = get_logger("pilot.ops")

DEFAULT_HOME = Path("artifacts/pilot/home")
FIXTURE_TENANT = "tenant-fixture-a"
# AF_UNIX socket paths are capped (~104 on macOS, ~108 on Linux). A pilot home
# nested deep under a long project path (or a clean-extraction dir) can push a
# home-relative socket path over that limit and the evaluator bind() fails.
# We therefore place the runtime socket under the system temp dir with a short
# deterministic name derived from the resolved home, and record the real path
# in the home's run/ dir for humans. Both the launcher and the client derive
# the same path from the same home, so there is a single source of truth.
_SOCKET_NAME_LEN = 12


def pilot_home() -> Path:
    return Path(os.environ.get("EAGLE_EYE_PILOT_HOME", str(DEFAULT_HOME)))


def evaluator_socket_path(home: str | Path) -> Path:
    """Short, portable, deterministic evaluator socket path for a given home.
    Honors an explicit EAGLE_EYE_PILOT_SOCKET override (operator control)."""
    override = os.environ.get("EAGLE_EYE_PILOT_SOCKET")
    if override:
        return Path(override)
    digest = hashlib.sha1(str(Path(home).resolve()).encode()).hexdigest()[:_SOCKET_NAME_LEN]
    # Never place the socket directly in the system temp root. On macOS that
    # root is OS-managed and cannot be chmod'ed by the process; on shared /tmp
    # systems a predictable top-level socket also creates an ownership hazard.
    uid = getattr(os, "getuid", lambda: 0)()
    socket_dir = Path(tempfile.gettempdir()) / f"eez-pilot-{uid}"
    return socket_dir / f"{digest}.sock"


def cockpit_port() -> int:
    return int(os.environ.get("EAGLE_EYE_PORT", "8765"))


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _read_pidfile(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _port_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_setup(home: Path) -> int:
    """Idempotent initialization: home dirs, migrations, fixture tenant,
    evaluator client token (0600)."""
    run_dir = home / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(run_dir, 0o700)
    store = PilotStorage(home / "pilot.sqlite3")
    migration = store.migrate()
    store.ensure_tenant(FIXTURE_TENANT, display_name="Pilot Fixture A",
                        data_class="FIXTURE")
    store.close()
    token_file = run_dir / "client.token"
    if not token_file.exists():
        token_file.write_text(secrets.token_hex(24))
        os.chmod(token_file, 0o600)
    config = {
        "spec": "eagle-eye-pilot-config/6.0",
        "home": str(home),
        "tenant": FIXTURE_TENANT,
        "data_class": "FIXTURE",
        "cockpit_port": cockpit_port(),
        "evaluator_socket": str(evaluator_socket_path(home)),
        "external_execution": False,
        "schema_version": migration["schema_version"],
    }
    # record the resolved socket path for humans (the socket lives in the
    # system temp dir to stay under the AF_UNIX length limit)
    (run_dir / "evaluator.socket.path").write_text(str(evaluator_socket_path(home)))
    (home / "PILOT_CONFIG.json").write_text(json.dumps(config, indent=2, sort_keys=True))
    print(json.dumps({"setup": "ok", **config}, sort_keys=True))
    return 0


def cmd_up(home: Path) -> int:
    """Start the evaluator service and the cockpit server as separate
    processes. Stale-listener detection: a live pidfile or an occupied port
    refuses a second start instead of silently doubling up."""
    run_dir = home / "run"
    if not (home / "PILOT_CONFIG.json").exists():
        print("pilot home not initialized — run `make pilot-setup` first",
              file=sys.stderr)
        return 1
    port = cockpit_port()
    for name in ("evaluator", "cockpit"):
        pid = _read_pidfile(run_dir / f"{name}.pid")
        if pid and _pid_alive(pid):
            print(f"stale-listener guard: {name} already running (pid {pid}); "
                  "run `make pilot-down` first", file=sys.stderr)
            return 1
    if _port_listening(port):
        print(f"stale-listener guard: port {port} is already in use", file=sys.stderr)
        return 1

    env = {**os.environ, "PYTHONPATH": "src",
           "EAGLE_EYE_PILOT_HOME": str(home)}
    logs_dir = home / "logs"
    logs_dir.mkdir(exist_ok=True)
    evaluator_log = (logs_dir / "evaluator.log").open("a")
    socket_path = evaluator_socket_path(home)
    socket_path.unlink(missing_ok=True)  # clear any stale socket from a crash
    evaluator = subprocess.Popen(
        [sys.executable, "-m", "eagle_eye.pilot.evaluator_service",
         "--socket", str(socket_path),
         "--state-dir", str(home / "evaluator-state"),
         "--token-file", str(run_dir / "client.token"),
         "--tenant", FIXTURE_TENANT, "--run-id", "run-pilot-service"],
        env=env, stdout=evaluator_log, stderr=subprocess.STDOUT)
    (run_dir / "evaluator.pid").write_text(str(evaluator.pid))
    cockpit_log = (logs_dir / "cockpit.log").open("a")
    cockpit = subprocess.Popen(
        [sys.executable, "-m", "eagle_eye.server"],
        env=env, stdout=cockpit_log, stderr=subprocess.STDOUT)
    (run_dir / "cockpit.pid").write_text(str(cockpit.pid))

    deadline = time.time() + 30
    ready = False
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/pilot/health", timeout=2) as resp:
                report = json.loads(resp.read())
                if report.get("ready"):
                    ready = True
                    break
        except (urllib.error.URLError, ConnectionError, json.JSONDecodeError):
            pass
        if evaluator.poll() is not None or cockpit.poll() is not None:
            print("a pilot process died during startup — see logs/", file=sys.stderr)
            cmd_down(home)
            return 1
        time.sleep(0.4)
    log_event(_LOG, "pilot up", ready=ready, port=port,
              evaluator_pid=evaluator.pid, cockpit_pid=cockpit.pid)
    print(json.dumps({"up": True, "ready": ready, "port": port,
                      "evaluator_pid": evaluator.pid, "cockpit_pid": cockpit.pid}))
    return 0 if ready else 1


def cmd_down(home: Path) -> int:
    """Graceful shutdown + cleanup (pidfiles, socket). Safe when not running."""
    run_dir = home / "run"
    stopped = []
    for name in ("cockpit", "evaluator"):
        pidfile = run_dir / f"{name}.pid"
        pid = _read_pidfile(pidfile)
        if pid and _pid_alive(pid):
            os.kill(pid, signal.SIGTERM)
            deadline = time.time() + 10
            while time.time() < deadline and _pid_alive(pid):
                time.sleep(0.2)
            if _pid_alive(pid):
                os.kill(pid, signal.SIGKILL)
            stopped.append({name: pid})
        pidfile.unlink(missing_ok=True)
    evaluator_socket_path(home).unlink(missing_ok=True)
    (run_dir / "evaluator.sock").unlink(missing_ok=True)  # legacy path cleanup
    print(json.dumps({"down": True, "stopped": stopped}))
    return 0


def cmd_check(home: Path) -> int:
    """Health + readiness + migrations; exit nonzero on any degradation."""
    port = cockpit_port()
    problems: list[str] = []
    report: dict[str, Any] = {}
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/pilot/health", timeout=5) as resp:
            report = json.loads(resp.read())
    except Exception as exc:
        problems.append(f"health endpoint unreachable: {type(exc).__name__}")
    if report and not report.get("ready"):
        for name, dep in report.get("dependencies", {}).items():
            if dep["required"] and not dep["ok"]:
                problems.append(f"dependency {name}: {dep['detail']}")
    store = PilotStorage(home / "pilot.sqlite3")
    migrations = store.migration_status()
    store.close()
    if not migrations:
        problems.append("no migrations applied")
    result = {"pilot_check": "PASS" if not problems else "FAIL",
              "problems": problems,
              "migrations_applied": len(migrations),
              "health": report}
    print(json.dumps(result, sort_keys=True))
    return 0 if not problems else 1


def cmd_backup(home: Path) -> int:
    dest = home / "backups" / time.strftime("%Y%m%dT%H%M%S")
    store = PilotStorage(home / "pilot.sqlite3")
    manifest = store.backup(dest, object_store_dir=home / "objects")
    store.close()
    print(json.dumps({"backup": "ok", "dest": str(dest),
                      "db_sha256": manifest["db_sha256"],
                      "audit_heads": manifest["audit_heads"]}, sort_keys=True))
    return 0


def cmd_restore_check(home: Path) -> int:
    backups = sorted((home / "backups").glob("*")) if (home / "backups").exists() else []
    if not backups:
        print(json.dumps({"restore_check": "FAIL",
                          "error": "no backups exist — run pilot-backup first"}))
        return 1
    latest = backups[-1]
    result = PilotStorage.restore_check(latest)
    ok = result["all_heads_reproduced"]
    print(json.dumps({"restore_check": "PASS" if ok else "FAIL",
                      "backup": str(latest), **result}, sort_keys=True))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Eagle Eye pilot operations")
    parser.add_argument("command", choices=["setup", "up", "down", "check",
                                            "backup", "restore-check"])
    args = parser.parse_args(argv)
    home = pilot_home()
    return {"setup": cmd_setup, "up": cmd_up, "down": cmd_down,
            "check": cmd_check, "backup": cmd_backup,
            "restore-check": cmd_restore_check}[args.command](home)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
