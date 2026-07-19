"use strict";
// Eagle Eye Zenith — pilot operator cockpit.
// Talks ONLY to /api/pilot/*. No secrets ever reach this page: dev-issuer
// tokens are minted server-side and held in-memory here for the session.
// All user-derived text is escaped; the server also normalizes evidence, so
// hostile payloads (e.g. <script> in a signal description) render inert.

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const esc = (v) => String(v).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const S = {
  tokens: {},            // role -> bearer assertion (in-memory only)
  identities: {},        // slot -> {subject, roles, token}
  evidence: [],          // ingested normalized events
  selected: new Set(),   // chosen evidence digests
  requestId: null,
  state: null,           // current action state
};

function setStage(id, state, tone) {
  const chip = $(`#stage-${id} .state-chip`);
  if (chip) { chip.textContent = state; chip.dataset.tone = tone || ""; }
}
function banner(message, tone) {
  const b = $("#banner");
  if (!message) { b.hidden = true; return; }
  b.hidden = false; b.dataset.tone = tone || "warn"; b.textContent = message;
}
function result(sel, obj, tone) {
  const box = $(sel);
  box.dataset.tone = tone || "";
  if (typeof obj === "string") { box.innerHTML = `<p>${esc(obj)}</p>`; return; }
  box.innerHTML = obj;
}

async function api(method, path, { role, body } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (role && S.tokens[role]) headers["Authorization"] = `Bearer ${S.tokens[role]}`;
  const resp = await fetch(path, {
    method, headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  let payload = {};
  try { payload = await resp.json(); } catch (_) { /* empty */ }
  if (resp.status === 401) banner(`Identity ${payload.state || "failed"} — re-mint sessions.`, "bad");
  else if (resp.status === 503) banner(`Dependency degraded: ${payload.state || ""}.`, "bad");
  else banner("");
  return { status: resp.status, payload };
}

// -- identities -------------------------------------------------------------
async function mint(subject, roles) {
  const { payload } = await api("POST", "/api/pilot/dev-issuer/mint",
    { body: { subject, roles, ttl_seconds: 1800 } });
  return payload.token;
}
async function provisionIdentities() {
  S.tokens.analyst = await mint("op-analyst", ["analyst"]);
  S.tokens.approver = await mint("op-approver", ["approver"]);
  S.tokens.operator = await mint("op-operator", ["operator"]);
  $("#identity-note").textContent =
    "3 sessions minted (analyst · approver · operator), 30-min TTL, NOT-PRODUCTION.";
  ["as-analyst", "as-approver"].forEach((id) => {
    const sel = $(`#${id}`);
    sel.innerHTML = "";
    Object.keys(S.tokens).forEach((role) => {
      const opt = document.createElement("option");
      opt.value = role; opt.textContent = `${role}`;
      sel.appendChild(opt);
    });
  });
  $("#as-analyst").value = "analyst";
  $("#as-approver").value = "approver";
}
const requesterRole = () => $("#as-analyst").value || "analyst";
const approverRole = () => $("#as-approver").value || "approver";

// -- 1. ingest --------------------------------------------------------------
async function doIngest() {
  setStage("ingest", "loading", "warn");
  const count = Math.max(1, Math.min(50, parseInt($("#ingest-count").value, 10) || 6));
  const { status, payload } = await api("POST", "/api/pilot/ingest/synthetic",
    { role: "operator", body: { count } });
  if (status !== 200) {
    setStage("ingest", "denied", "bad");
    result("#ingest-result", payload.error || "ingest failed", "bad");
    return;
  }
  setStage("ingest", `${payload.accepted} accepted`, "ok");
  result("#ingest-result",
    `<p><strong>${payload.accepted}</strong> signed events accepted · ${payload.rejected} rejected.</p>`,
    "ok");
  await loadEvidence();
}
async function viewQuarantine() {
  const { payload } = await api("GET", "/api/pilot/ingest/quarantine", { role: "operator" });
  const entries = payload.entries || [];
  result("#ingest-result", entries.length
    ? `<p class="warn-text">${entries.length} quarantined:</p><ul>${entries.map((e) =>
        `<li>${esc(e.source_id || "?")}: ${esc((e.reasons || []).join("; "))}</li>`).join("")}</ul>`
    : "<p class='empty'>Quarantine empty.</p>");
}

// -- 2. provenance ----------------------------------------------------------
async function loadEvidence() {
  const { payload } = await api("GET", "/api/pilot/ingest/events", { role: "analyst" });
  S.evidence = payload.events || [];
  const box = $("#evidence-list");
  if (!S.evidence.length) { box.innerHTML = "<p class='empty'>No evidence yet — run ingest.</p>"; setStage("provenance", "empty"); return; }
  setStage("provenance", `${S.evidence.length} signals`, "ok");
  box.innerHTML = S.evidence.slice(0, 12).map((e) => {
    const p = e.event.payload || {};
    const short = e.digest.slice(0, 10);
    const checked = S.selected.has(e.digest) ? "checked" : "";
    return `<label class="evidence-item${e.superseded_by_correction ? " superseded" : ""}">
      <input type="checkbox" data-digest="${esc(e.digest)}" ${checked}>
      <span class="ev-lane">${esc(p.lane || "?")}</span>
      <span class="ev-class">${esc(p.disruption_class || "?")}</span>
      <span class="ev-sev">sev ${esc(p.severity ?? "?")}</span>
      <button class="link prov-btn" data-digest="${esc(e.digest)}">${esc(short)}…</button>
      ${e.superseded_by_correction ? '<span class="tag">superseded</span>' : ""}
    </label>`;
  }).join("");
  $$("#evidence-list input[type=checkbox]").forEach((cb) =>
    cb.addEventListener("change", () => {
      cb.checked ? S.selected.add(cb.dataset.digest) : S.selected.delete(cb.dataset.digest);
      refreshGating();
    }));
  $$("#evidence-list .prov-btn").forEach((btn) =>
    btn.addEventListener("click", (e) => { e.preventDefault(); showProvenance(btn.dataset.digest); }));
  refreshGating();
}
async function showProvenance(digest) {
  const { status, payload } = await api("GET", `/api/pilot/provenance/${digest}`, { role: "analyst" });
  if (status !== 200) { result("#provenance-detail", payload.error || "not found", "bad"); return; }
  const description = (payload.normalized_event && payload.normalized_event.payload
    && payload.normalized_event.payload.description) || "";
  result("#provenance-detail", `<div class="kv-list">
    <div class="kv"><span class="kv-k">digest</span><span class="kv-v wrap">${esc(payload.digest)}</span></div>
    <div class="kv"><span class="kv-k">digest recomputed</span><span class="kv-v">${payload.digest_recomputed_ok ? "✓ matches" : "✗ mismatch"}</span></div>
    <div class="kv"><span class="kv-k">source registered</span><span class="kv-v">${payload.source_registered ? "✓" : "✗"}</span></div>
    <div class="kv"><span class="kv-k">raw event sha256</span><span class="kv-v wrap">${esc(payload.receipt.raw_event_sha256)}</span></div>
    <div class="kv"><span class="kv-k">description</span><span class="kv-v wrap" id="prov-description">${esc(description)}</span></div>
    <div class="kv"><span class="kv-k">late</span><span class="kv-v">${payload.receipt.late}</span></div>
  </div>`, payload.digest_recomputed_ok ? "ok" : "bad");
}

// -- 3. decision ------------------------------------------------------------
async function doDecision() {
  setStage("decision", "loading", "warn");
  const { status, payload } = await api("POST", "/api/pilot/decision",
    { role: requesterRole(), body: { evidence_ids: [...S.selected] } });
  if (status !== 200) { setStage("decision", "refused", "bad"); result("#decision-result", payload.error, "bad"); return; }
  S.decision = payload;
  setStage("decision", "assessed", "ok");
  result("#decision-result", `<div class="kv-list">
    <div class="kv"><span class="kv-k">focus lane</span><span class="kv-v">${esc(payload.focus_lane)}</span></div>
    <div class="kv"><span class="kv-k">mean severity</span><span class="kv-v">${esc(payload.mean_severity)}</span></div>
    <div class="kv"><span class="kv-k">recommended</span><span class="kv-v">${esc(payload.recommended_action.label)}</span></div>
    <div class="kv"><span class="kv-k">signals</span><span class="kv-v">${esc(payload.signals_considered)}</span></div>
  </div><p class="label-chip">${esc(payload.label)}</p>
  <p class="muted">${esc(payload.uncertainty.note)}</p>`, "ok");
  refreshGating();
}

// -- 4. request -------------------------------------------------------------
async function doRequest() {
  setStage("request", "loading", "warn");
  const actionId = (S.decision && S.decision.recommended_action.action_id) || "expedite-alt-supplier";
  const { status, payload } = await api("POST", "/api/pilot/actions/request",
    { role: requesterRole(), body: { action_id: actionId, evidence_ids: [...S.selected], summary: "operator cockpit action" } });
  if (status !== 200) { setStage("request", "refused", "bad"); result("#request-result", payload.error, "bad"); return; }
  S.requestId = payload.request_id; S.state = payload.state;
  setStage("request", "awaiting approval", "warn");
  result("#request-result", `<p>Request <span class="wrap">${esc(payload.request_id)}</span></p>
    <p class="muted">evidence digest frozen: <span class="wrap">${esc(payload.evidence_digest.slice(0, 24))}…</span></p>`, "ok");
  updateLifecycle(payload.state);
  refreshGating();
}

// -- 5. approval ------------------------------------------------------------
async function doApprove() {
  setStage("approval", "loading", "warn");
  const { status, payload } = await api("POST", `/api/pilot/actions/${S.requestId}/approve`,
    { role: approverRole(), body: {} });
  if (status !== 200) { setStage("approval", "refused", "bad"); result("#approval-result", payload.error, "bad"); return; }
  S.state = payload.state;
  setStage("approval", "approved", "ok");
  result("#approval-result", `<p>Approved by <strong>${esc(payload.approval.approver_id)}</strong> (requester was ${esc(payload.approval.requester_id)}).</p>
    <p class="muted">dual control verified · external execution ${payload.approval.external_execution}</p>`, "ok");
  updateLifecycle(payload.state);
  refreshGating();
}
async function doReject() {
  const { payload } = await api("POST", `/api/pilot/actions/${S.requestId}/reject`,
    { role: approverRole(), body: { reason: "operator rejected in cockpit" } });
  setStage("approval", "rejected", "bad");
  result("#approval-result", `<p>Rejected — action frozen in APPROVAL_REJECTED.</p>`, "bad");
  S.state = "APPROVAL_REJECTED"; updateLifecycle(S.state); refreshGating();
}
async function trySelfApprove() {
  // requester tries to approve their own action — MUST be refused.
  const { status, payload } = await api("POST", `/api/pilot/actions/${S.requestId}/approve`,
    { role: requesterRole(), body: {} });
  const refused = status === 403 || status === 409;
  result("#approval-result",
    `<p class="${refused ? "ok-text" : "bad-text"}">Self-approval ${refused ? "correctly refused" : "UNEXPECTEDLY ALLOWED"}: ${esc(payload.error || payload.state)}</p>`,
    refused ? "ok" : "bad");
}

// -- 6. shadow --------------------------------------------------------------
async function doDispatch() {
  setStage("shadow", "loading", "warn");
  const key = `cockpit-${S.requestId}`;
  const { status, payload } = await api("POST", `/api/pilot/actions/${S.requestId}/dispatch`,
    { role: requesterRole(), body: { idempotency_key: key } });
  if (status !== 200) { setStage("shadow", "refused", "bad"); result("#dispatch-result", payload.error, "bad"); return; }
  S.state = payload.state;
  setStage("shadow", "shadow dispatched", "ok");
  const d = payload.dispatch;
  result("#dispatch-result", `<div class="kv-list">
    <div class="kv"><span class="kv-k">mode</span><span class="kv-v">${esc(d.mode)}</span></div>
    <div class="kv"><span class="kv-k">external execution</span><span class="kv-v">${d.external_execution}</span></div>
    <div class="kv"><span class="kv-k">fail-closed proof</span><span class="kv-v wrap">${esc(d.external_executor_state.fail_closed_proof)}</span></div>
  </div>`, "ok");
  updateLifecycle(payload.state);
  refreshGating();
}

// -- 7. outcome -------------------------------------------------------------
async function doOutcome() {
  setStage("outcome", "loading", "warn");
  const { status, payload } = await api("POST", `/api/pilot/actions/${S.requestId}/outcome`,
    { role: requesterRole(), body: { observed: { predicted_delay_days: 12.0, actual_delay_days: 10.5, note: "cockpit fixture outcome" } } });
  if (status !== 200) { setStage("outcome", "refused", "bad"); result("#outcome-result", payload.error, "bad"); return; }
  S.state = payload.state;
  setStage("outcome", "recorded", "ok");
  const q = payload.outcome.decision_quality;
  result("#outcome-result", `<p>Resolver <strong>${esc(payload.outcome.resolver_id)}</strong></p>
    <p class="muted">${esc(q.label)} · abs error ${esc(q.abs_error_days)} days · within 20% ${q.within_20pct}</p>`, "ok");
  updateLifecycle(payload.state);
  refreshGating();
}

// -- 8. replay --------------------------------------------------------------
async function doReplay() {
  setStage("replay", "loading", "warn");
  const { status, payload } = await api("POST", `/api/pilot/actions/${S.requestId}/replay`,
    { role: requesterRole(), body: {} });
  if (status !== 200) { setStage("replay", "refused", "bad"); result("#replay-proof", payload.error, "bad"); return; }
  const checks = payload.checks || {};
  $("#replay-proof").innerHTML = Object.entries(checks).map(([name, ok]) =>
    `<span class="pchip ${ok ? "ok" : "bad"}">${esc(name.replace(/_/g, " "))} ${ok ? "✓" : "✗"}</span>`).join("");
  setStage("replay", payload.verified ? "verified" : "FAILED", payload.verified ? "ok" : "bad");
  if (payload.verified) { S.state = "REPLAY_VERIFIED"; updateLifecycle(S.state); }
  refreshGating();
}

// -- 9. export --------------------------------------------------------------
async function doExport() {
  setStage("export", "loading", "warn");
  const { status, payload } = await api("POST", `/api/pilot/actions/${S.requestId}/export`,
    { role: "operator", body: {} });
  if (status !== 200) { setStage("export", "refused", "bad"); result("#export-result", payload.error, "bad"); return; }
  setStage("export", "exported", "ok");
  result("#export-result", `<p>Evidence room stored content-addressed.</p>
    <div class="kv-list"><div class="kv"><span class="kv-k">object digest</span><span class="kv-v wrap">${esc(payload.object_digest)}</span></div>
    <div class="kv"><span class="kv-k">bytes</span><span class="kv-v">${esc(payload.bytes)}</span></div></div>`, "ok");
}

// -- lifecycle strip --------------------------------------------------------
const LIFECYCLE = ["REQUESTED", "AWAITING_INDEPENDENT_APPROVAL", "APPROVED_SHADOW",
  "SHADOW_DISPATCHED", "OUTCOME_PENDING", "OUTCOME_RECORDED", "REPLAY_VERIFIED"];
function updateLifecycle(state) {
  const idx = LIFECYCLE.indexOf(state);
  $("#shadow-lifecycle").innerHTML = LIFECYCLE.map((s, i) => {
    const cls = state === "EXPIRED" || state === "APPROVAL_REJECTED" || state === "EVIDENCE_FAILED"
      ? (i === 0 ? "done" : "blocked")
      : (i < idx ? "done" : i === idx ? "here" : "");
    return `<span class="ls ${cls}">${esc(s.replace(/_/g, " "))}</span>`;
  }).join("") + `<span class="ls blocked">EXTERNALLY EXECUTED · OFF</span>`;
}

// -- gating (buttons enable only when the stage is reachable) ----------------
function refreshGating() {
  const has = (s) => S.state === s;
  $("#do-decision").disabled = S.selected.size === 0;
  $("#do-request").disabled = S.selected.size === 0 || !S.decision;
  const awaiting = has("AWAITING_INDEPENDENT_APPROVAL");
  $("#do-approve").disabled = !awaiting;
  $("#do-reject").disabled = !awaiting;
  $("#try-self-approve").disabled = !awaiting;
  $("#do-dispatch").disabled = !has("APPROVED_SHADOW");
  $("#do-outcome").disabled = !has("OUTCOME_PENDING");
  $("#do-replay").disabled = !has("OUTCOME_RECORDED") && !has("REPLAY_VERIFIED");
  $("#do-export").disabled = !has("REPLAY_VERIFIED");
}

// -- health -----------------------------------------------------------------
async function loadHealthAndStatus() {
  const { payload: status } = await api("GET", "/api/pilot/status");
  if (status && status.external_execution === false) {
    $("#ext-exec").innerHTML = "EXTERNAL EXECUTION: <strong class='off'>DISABLED · FAIL-CLOSED</strong>";
  }
  if (status && status.health) {
    const deps = status.health.dependencies || {};
    $("#health-grid").innerHTML = Object.entries(deps).map(([name, d]) =>
      `<span class="pchip ${d.ok ? "ok" : (d.required ? "bad" : "warn")}">${esc(name)} ${d.ok ? "✓" : "degraded"}</span>`).join("")
      + `<span class="pchip ${status.health.ready ? "ok" : "warn"}">readiness: ${esc(status.health.status)}</span>`;
  }
  if (status && status.adapters) {
    $("#walls-note").textContent =
      "Pilot adapters fail-closed · production KMS/identity/durable-audit/live-data NOT ESTABLISHED.";
  }
  const { status: evStatus, payload: ev } = await api("GET", "/api/pilot/evaluator/status", { role: "analyst" });
  if (evStatus === 200) {
    result("#evaluator-state", `<div class="kv-list">
      <div class="kv"><span class="kv-k">evaluator lifecycle</span><span class="kv-v">${esc(ev.lifecycle)}</span></div>
      <div class="kv"><span class="kv-k">looks spent / max</span><span class="kv-v">${esc(ev.looks_spent)} / ${esc(ev.max_looks)}</span></div>
      <div class="kv"><span class="kv-k">commitment</span><span class="kv-v wrap">${esc(ev.commitment.slice(0, 24))}…</span></div>
    </div><p class="muted">Separate OS process; this page never holds the evaluator secret.</p>`, "ok");
  } else {
    result("#evaluator-state", `Evaluator ${esc(ev.state || evStatus)} — cockpit degrades honestly.`,
      "warn");
  }
}

// -- wiring -----------------------------------------------------------------
function wire() {
  $("#do-ingest").addEventListener("click", doIngest);
  $("#view-quarantine").addEventListener("click", viewQuarantine);
  $("#do-decision").addEventListener("click", doDecision);
  $("#do-request").addEventListener("click", doRequest);
  $("#do-approve").addEventListener("click", doApprove);
  $("#do-reject").addEventListener("click", doReject);
  $("#try-self-approve").addEventListener("click", trySelfApprove);
  $("#do-dispatch").addEventListener("click", doDispatch);
  $("#do-outcome").addEventListener("click", doOutcome);
  $("#do-replay").addEventListener("click", doReplay);
  $("#do-export").addEventListener("click", doExport);
  $("#reset-identities").addEventListener("click", async () => {
    S.requestId = null; S.state = null; S.selected.clear(); S.decision = null;
    await provisionIdentities(); refreshGating();
  });
}

async function boot() {
  wire();
  try {
    await provisionIdentities();
    await loadHealthAndStatus();
    await loadEvidence();
    refreshGating();
  } catch (e) {
    banner(`Cockpit boot error: ${e.message}`, "bad");
  }
}
boot();
