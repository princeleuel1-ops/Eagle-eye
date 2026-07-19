from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from pathlib import Path
from urllib.parse import urlparse
import uuid

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
RUN = ROOT / "artifacts" / "runs" / "latest" / "run.json"
BENCHMARK = ROOT / "artifacts" / "benchmarks" / "latest" / "court-receipt.json"
GOVERNANCE = ROOT / "artifacts" / "governance" / "latest" / "approval-receipt.json"
EVOLUTION = ROOT / "artifacts" / "evolution" / "latest" / "state.json"

MAX_PILOT_BODY = 512 * 1024  # request-size abuse guard on the pilot API

_pilot_api = None
_pilot_lock = threading.Lock()
_pilot_error: str | None = None


def _get_pilot_api():
    """Lazily build the V6 pilot runtime (thread-safe, once). A broken pilot
    home degrades the pilot API to 503 without touching the V5 cockpit
    routes — the cockpit shows an honest degraded state instead of dying."""
    global _pilot_api, _pilot_error
    with _pilot_lock:
        if _pilot_api is None and _pilot_error is None:
            try:
                from eagle_eye.pilot.ops import pilot_home
                from eagle_eye.pilot.service import PilotApi, PilotRuntime
                _pilot_api = PilotApi(PilotRuntime(pilot_home()))
            except Exception as exc:  # fail closed, loudly, per-request
                _pilot_error = f"{type(exc).__name__}: {exc}"
        return _pilot_api, _pilot_error


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self.request_id = uuid.uuid4().hex
        super().__init__(*args, directory=str(WEB), **kwargs)

    def end_headers(self):
        self.send_header("X-Request-ID", self.request_id)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        )
        super().end_headers()

    def log_message(self, format, *args):
        print(json.dumps({
            "event": "http_request",
            "request_id": self.request_id,
            "client": self.client_address[0],
            "message": format % args,
        }, sort_keys=True))

    # -- V6 pilot API ---------------------------------------------------------
    def _serve_pilot(self, method: str) -> None:
        api, error = _get_pilot_api()
        if api is None:
            self._respond_json(503, {"error": f"pilot runtime unavailable: {error}",
                                     "state": "DEPENDENCY_DEGRADED"})
            return
        body = None
        if method == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_PILOT_BODY:
                self._respond_json(400, {"error": "request body too large",
                                         "state": "REFUSED"})
                return
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._respond_json(400, {"error": "request body is not valid JSON",
                                         "state": "REFUSED"})
                return
        status, payload = api.handle(method, urlparse(self.path).path, body,
                                     {k.lower(): v for k, v in self.headers.items()})
        self._respond_json(status, payload)

    def _respond_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, sort_keys=True, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith("/api/pilot/"):
            self._serve_pilot("POST")
            return
        self.send_error(404, "no POST routes outside the pilot API")

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/pilot/"):
            self._serve_pilot("GET")
            return
        if path in {"/api/run", "/api/benchmark", "/api/governance", "/api/evolution"}:
            sources = {"/api/run": RUN, "/api/benchmark": BENCHMARK, "/api/governance": GOVERNANCE, "/api/evolution": EVOLUTION}
            source = sources[path]
            if not source.exists():
                self.send_error(503, "Required artifact unavailable; run make check")
                return
            payload = source.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        return super().do_GET()


def main():
    import os
    port = int(os.environ.get("EAGLE_EYE_PORT", "8765"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Eagle Eye Zenith FIXTURE cockpit: http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()  # clean shutdown releases the listener


if __name__ == "__main__":
    main()
