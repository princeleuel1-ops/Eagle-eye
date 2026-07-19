// GOVERNED CANDIDATE EVOLUTION panel: champion lineage, budgets, guarantee
// states, off-policy identifiability, and value-of-information — every claim
// linked to a receipt. The stronger label "self-improving" renders ONLY when
// at least one promotion AND one rejection are verifiable in the lineage.
//
// V4 frontend/state contract (docs/frontend-state-contract-4.0.md):
//   REQUIRED: state_schema_version, champion, lineage_length, lineage_head,
//             budget{...}, conformal_state_latest, drift_state, n_cycles,
//             events, external_action, claim_supported
//   OPTIONAL (render safe fallbacks, never crash): last_promotion,
//             last_rejection (and every field inside them), voi_latest,
//             off_policy_latest, registry_growth_count, resolution_backlog
const $e=s=>document.querySelector(s);
const escE=v=>String(v).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const CONTRACT_MAJOR='evolution-state/4';
const opt=(o,path,fallback)=>{ // null-safe deep access for OPTIONAL fields
  let node=o;
  for(const key of path.split('.')){ if(node==null||typeof node!=='object'||!(key in node)) return fallback; node=node[key]; }
  return node==null?fallback:node;
};
const shortHash=(h,n)=>h?escE(String(h).slice(0,n))+'…':'n/a';
function promoCard(promo){
  if(!promo) return '<p>none yet</p>';
  const diff=opt(promo,'candidate.diff',null);
  const ci=opt(promo,'statistics.ci_upper_micro',null);
  const n=opt(promo,'statistics.n_paired',null);
  return `<p class="mono-sm">${diff?escE(JSON.stringify(diff)):'diff unavailable'}</p>`+
    `<p>sealed paired test · ci_upper ${ci===null?'n/a':(ci/1e6).toFixed(4)} · n ${n===null?'n/a':escE(n)}</p>`+
    `<small>${shortHash(opt(promo,'lineage_hash',null),20)}</small>`;
}
function rejCard(rej){
  if(!rej) return '<p>none</p>';
  const diff=opt(rej,'candidate.diff',null);
  const reasons=(opt(rej,'reasons',[])||[]).join('; ')||'sealed gates';
  return `<p class="mono-sm">${diff?escE(JSON.stringify(diff)):'diff unavailable'}</p>`+
    `<p>${escE(opt(rej,'state','UNKNOWN'))} · ${escE(reasons)}</p>`+
    `<small>${shortHash(opt(rej,'lineage_hash',null),20)}</small>`;
}
async function loadEvolution(){
  let state=null;
  try{const r=await fetch('/api/evolution');if(r.ok)state=await r.json();}catch(e){/* absent */}
  if(!state){$e('#evolution-content').innerHTML='<p>No evolution state. Run scripts/run_sealed_evolution.py.</p>';return;}
  const version=String(state.state_schema_version||'');
  const contractOk=version.startsWith(CONTRACT_MAJOR);
  const b=state.budget||{}, promo=state.last_promotion, rej=state.last_rejection;
  const claim=state.claim_supported
    ?'SELF-IMPROVING · PROMOTION + REJECTION VERIFIED IN LINEAGE'
    :'GOVERNED CANDIDATE EVOLUTION · promotion not yet proven';
  const statuses=opt(b,'holdout_look_terminal_statuses',null);
  $e('#evolution-head').innerHTML=
    `<span class="chip ${state.claim_supported?'ok':'warn'}">${escE(claim)}</span>`+
    `<span class="chip ${contractOk?'ok':'warn'}">CONTRACT · ${escE(version||'MISSING')}</span>`+
    `<span class="chip">CHAMPION · ${escE(state.champion||'n/a')}</span>`+
    `<span class="chip">LINEAGE · ${escE(state.lineage_length??'n/a')} RECEIPTS · HEAD ${shortHash(state.lineage_head,12)}</span>`+
    `<span class="chip ${state.conformal_state_latest==='GUARANTEE_ACTIVE'?'ok':'warn'}">CONFORMAL · ${escE(state.conformal_state_latest||'n/a')}</span>`+
    `<span class="chip ${state.drift_state==='stable'?'ok':'warn'}">DRIFT · ${escE(String(state.drift_state||'n/a').toUpperCase())}</span>`+
    `<span class="chip ok">EXTERNAL_ACTION · FALSE</span>`;
  $e('#evolution-content').innerHTML=
    `<div class="evo-grid">`+
    `<div><h4>LAST PROMOTION</h4>${promoCard(promo)}</div>`+
    `<div><h4>LAST REJECTION</h4>${rejCard(rej)}</div>`+
    `<div><h4>CHALLENGER BUDGET</h4><p>${escE(opt(b,'candidates_proposed','n/a'))} proposed · ${escE(opt(b,'candidates_evaluated','n/a'))} evaluated · ${escE(opt(b,'holdout_looks','n/a'))} holdout looks</p>`+
    `<p>alpha ${(opt(b,'alpha_spent_micro',0)/1e4).toFixed(2)}% spent / ${(opt(b,'alpha_total_micro',0)/1e4).toFixed(2)}% · final-audit looks ${escE(opt(b,'final_audit_holdout_looks','n/a'))}</p>`+
    (statuses?`<p class="mono-sm">terminal: ${escE(JSON.stringify(statuses))}</p>`:'')+`</div>`+
    `<div><h4>FLYWHEEL STATE</h4><p>registry growth +${escE(opt(state,'registry_growth_count',0))} tasks · backlog ${escE(opt(state,'resolution_backlog','n/a'))}</p>`+
    `<p>off-policy · ${escE(opt(state,'off_policy_latest','n/a'))}</p>`+
    `<p>VOI · ${escE(opt(state,'voi_latest.recommended_wait_or_act','n/a'))} (EVOI $${escE(opt(state,'voi_latest.evoi_usd','n/a'))}, ${escE(opt(state,'voi_latest.label','n/a'))})</p>`+
    `<small>N=${escE(state.n_cycles??'n/a')} sealed cycles · every row receipt-linked in EVOLUTION_LINEAGE.json</small></div>`+
    `</div>`;
}
loadEvolution().catch(e=>{$e('#evolution-content').innerHTML=`<p>Evolution panel unavailable: ${escE(e.message)}</p>`});
