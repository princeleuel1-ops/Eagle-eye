"""V4 blocker 8: REAL browser verification of the live cockpit.

Starts the actual server (unused localhost port), drives headless Chromium via
Playwright through the full workflow the audit requires:

  supplier selection, evidence trace, posterior commitment (in-browser
  WebCrypto recomputation), evolution lineage, rejection details, budget,
  final audit surfacing, and fixture/external-action labeling

and REQUIRES zero browser JavaScript errors, zero failed requests, and no
"panel unavailable" state. Writes a receipt + screenshot.

usage: PYTHONPATH=src python scripts/browser_verification.py [out.json]
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT / "artifacts" / "browser" / "latest" / "BROWSER_VERIFICATION.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("BROWSER_VERIFICATION_FAIL=playwright not installed (pip install playwright; playwright install chromium)")
        return 1
    port = free_port()
    server = subprocess.Popen(
        [sys.executable, "-m", "eagle_eye.server"],
        cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "src"),
                       "EAGLE_EYE_PORT": str(port)},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    checks: dict[str, bool] = {}
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[str] = []

    def expect(name: str, condition: bool) -> None:
        checks[name] = bool(condition)
        print(f"{name}={'PASS' if condition else 'FAIL'}")

    try:
        time.sleep(1.0)
        with sync_playwright() as p:
            # V6 portability: optional renderer-stability flags for constrained
            # CI/container hosts via EAGLE_EYE_CHROMIUM_ARGS (space-separated).
            # Default EMPTY → real multiprocess Chromium, unchanged from V5.
            _extra = os.environ.get("EAGLE_EYE_CHROMIUM_ARGS", "").split()
            browser = p.chromium.launch(headless=True, args=_extra)
            page = browser.new_page()
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: page_errors.append(str(e)))
            page.on("requestfailed", lambda r: failed_requests.append(f"{r.url} ({r.failure})"))
            page.on("response", lambda r: failed_requests.append(f"{r.url} (HTTP {r.status})")
                    if r.status >= 400 else None)
            page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(1200)

            # proof state + fixture / external-action labeling
            proof = page.text_content("#proof-state") or ""
            # V5 Lane 3: decomposed, honest proof chips (no single misleading badge)
            expect("PROOF_STATE_DECOMPOSED",
                   "DATA SIGNATURES" in proof and "SHADOW-ONLY" in proof
                   and "NOT EXECUTED" in proof and "READY" not in proof)
            expect("FIXTURE_LABELED", "FIXTURE" in (page.text_content("header") or ""))

            # supplier selection: click the first affected (alert) node
            page.locator("#network-layer g.node").first.wait_for(state="visible", timeout=10000)
            alert_node = page.locator("#network-layer g.node:has(circle.alert)").first
            (alert_node if alert_node.count() else page.locator("#network-layer g.node").first).click()
            page.wait_for_timeout(400)
            inspector = page.inner_html("#inspector")
            expect("SUPPLIER_SELECTION", "<h2>" in inspector and "ID ·" in inspector)
            # V5 Lane 3: inspector is READABLE key/value, not a raw JSON dump
            expect("INSPECTOR_NO_RAW_JSON",
                   'class="json"' not in inspector and "kv-list" in inspector)
            # V5 Lane 3: action lifecycle strip explains PENDING->SHADOW sequence
            action_html = page.inner_html("#action")
            expect("ACTION_LIFECYCLE_STRIP",
                   "lifecycle" in action_html
                   and "EXTERNALLY_EXECUTED · OFF" in page.text_content("#action"))
            # V5 Lane 3: the previously-dead "Fit network" control is wired —
            # clicking it resets the inspector to the default prompt
            page.click("#fit")
            page.wait_for_timeout(200)
            expect("FIT_CONTROL_LIVE", "Select a node" in page.inner_html("#inspector"))
            # V5 Lane 3: layer toggle is wired — unchecking Network hides the layer
            net_box = page.locator(".rail label", has_text="Network").locator("input")
            net_box.uncheck()
            page.wait_for_timeout(150)
            hidden = page.eval_on_selector("#network-layer", "el => el.style.display")
            expect("LAYER_TOGGLE_LIVE", hidden == "none")
            net_box.check()
            # re-select a node for the remaining evidence/commitment checks
            (alert_node if alert_node.count() else page.locator("#network-layer g.node").first).click()
            page.wait_for_timeout(300)

            # evidence trace
            page.click("#trace")
            page.wait_for_timeout(300)
            evidence = page.inner_html("#evidence-content")
            expect("EVIDENCE_TRACE", len(evidence) > 40 and "unavailable" not in evidence.lower())

            # posterior commitment recomputed IN the browser (WebCrypto)
            page.wait_for_selector("#commitment-badge", timeout=10000)
            expect("POSTERIOR_COMMITMENT_RECOMPUTED",
                   "RECOMPUTED ✓" in (page.text_content("#commitment-badge") or ""))

            # evolution lineage / budget / rejection details / final audit / contract
            head = page.inner_html("#evolution-head")
            content = page.inner_html("#evolution-content")
            expect("EVOLUTION_LINEAGE_CHIP", "LINEAGE ·" in head)
            expect("EVOLUTION_CONTRACT_CHIP", "CONTRACT · evolution-state/4" in head)
            expect("EXTERNAL_ACTION_FALSE_CHIP", "EXTERNAL_ACTION · FALSE" in head)
            expect("REJECTION_DETAILS_RENDERED", "LAST REJECTION" in content)
            expect("BUDGET_RENDERED", "CHALLENGER BUDGET" in content and "alpha" in content)
            expect("FINAL_AUDIT_SURFACED", "final-audit looks" in content)
            expect("NO_PANEL_UNAVAILABLE", "unavailable" not in content.lower())

            # governance / dual control panel
            expect("GOVERNANCE_DUAL_CONTROL", "DUAL CONTROL" in (page.inner_html("#governance") or ""))

            page.screenshot(path=str(out_path.parent / "cockpit.png"), full_page=True)

            # V5 Lane 3: no horizontal overflow at a 390px phone viewport
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(400)
            overflow = page.evaluate(
                "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
            expect("NO_MOBILE_HORIZONTAL_OVERFLOW", overflow <= 2)
            page.screenshot(path=str(out_path.parent / "cockpit-mobile.png"), full_page=True)
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)

    expect("ZERO_JS_ERRORS", not console_errors and not page_errors)
    expect("ZERO_FAILED_REQUESTS", not failed_requests)
    ok = all(checks.values())
    receipt = {
        "spec": "browser-verification/5.0",
        "browser": "playwright-chromium (headless)",
        "port": port,
        "checks": checks,
        "console_errors": console_errors,
        "page_errors": page_errors,
        "failed_requests": failed_requests,
        "screenshot": str(out_path.parent / "cockpit.png"),
        "pass": ok,
    }
    out_path.write_text(json.dumps(receipt, indent=2, sort_keys=True))
    print(f"BROWSER_VERIFICATION_{'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
