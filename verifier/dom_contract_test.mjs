// V4 blocker 8: JS-runtime frontend/state contract test (Node + DOM shim).
//
// Executes the REAL web/evolution.js against the REAL generated state.json in
// a Node vm with a minimal DOM shim, and asserts:
//   1. no uncaught JS errors
//   2. the panel renders (no "unavailable" fallback state)
//   3. required contract fields are surfaced (contract chip, budget, lineage)
//   4. REGRESSION (the V3 crash): a state whose last_rejection is missing
//      lineage_hash — and whose last_promotion is null — renders safe
//      fallbacks instead of crashing the panel
//
// HONEST LABEL: this is a real JS runtime executing the real panel code, but
// it is NOT a full browser. The full-browser workflow is
// scripts/browser_verification.py (Playwright/Chromium), gated separately.
//
// usage: node verifier/dom_contract_test.mjs <state.json>

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const statePath = process.argv[2] ?? join(root, "artifacts/evolution/latest/state.json");
const source = readFileSync(join(root, "web/evolution.js"), "utf8");
const realState = JSON.parse(readFileSync(statePath, "utf8"));

async function renderWith(state) {
  const elements = {};
  const element = (id) => (elements[id] ??= { innerHTML: "" });
  const errors = [];
  const context = vm.createContext({
    document: { querySelector: (sel) => element(sel) },
    fetch: async () => ({ ok: true, json: async () => state }),
    console,
    setTimeout,
  });
  try {
    vm.runInContext(source, context, { filename: "evolution.js" });
  } catch (e) {
    errors.push(`sync: ${e.message}`);
  }
  // allow the async loadEvolution() promise chain to settle
  for (let i = 0; i < 20 && !elements["#evolution-content"]?.innerHTML; i++) {
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  return { elements, errors };
}

const failures = [];
const expect = (name, cond) => {
  console.log(`${name}=${cond ? "PASS" : "FAIL"}`);
  if (!cond) failures.push(name);
};

// ---- 1+2+3: real generated state renders fully ---------------------------
{
  const { elements, errors } = await renderWith(realState);
  const head = elements["#evolution-head"]?.innerHTML ?? "";
  const content = elements["#evolution-content"]?.innerHTML ?? "";
  expect("NO_JS_ERRORS", errors.length === 0);
  expect("PANEL_RENDERED", content.includes("CHALLENGER BUDGET") && content.includes("FLYWHEEL STATE"));
  expect("NO_UNAVAILABLE_STATE", !content.includes("unavailable:") && !content.includes("Evolution panel unavailable"));
  expect("CONTRACT_CHIP", head.includes("CONTRACT · evolution-state/4"));
  expect("CLAIM_CHIP_HONEST", head.includes("GOVERNED CANDIDATE EVOLUTION") || head.includes("SELF-IMPROVING"));
  expect("LINEAGE_CHIP", head.includes("LINEAGE ·"));
  expect("EXTERNAL_ACTION_CHIP", head.includes("EXTERNAL_ACTION · FALSE"));
  expect("REJECTION_DETAILS", content.includes("LAST REJECTION"));
  expect("TERMINAL_STATUS_SURFACED", content.includes("terminal:") || !realState.budget?.holdout_look_terminal_statuses);
}

// ---- 4: V3 crash regression — optional fields missing ---------------------
{
  const degraded = JSON.parse(JSON.stringify(realState));
  degraded.last_promotion = null;
  degraded.last_rejection = { state: "REJECTED", candidate: {} };  // NO lineage_hash, NO diff, NO reasons
  delete degraded.voi_latest;
  const { elements, errors } = await renderWith(degraded);
  const content = elements["#evolution-content"]?.innerHTML ?? "";
  expect("DEGRADED_NO_JS_ERRORS", errors.length === 0);
  expect("DEGRADED_RENDERS_FALLBACKS", content.includes("none yet") && content.includes("n/a"));
  expect("DEGRADED_NOT_UNAVAILABLE", !content.includes("Evolution panel unavailable"));
}

console.log(`DOM_CONTRACT_${failures.length === 0 ? "PASS" : "FAIL"}`);
process.exit(failures.length === 0 ? 0 : 1);
