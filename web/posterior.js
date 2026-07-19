// POSTERIOR INTELLIGENCE panel: calibrated distributions, prior provenance,
// shift/support governance, and in-browser commitment verification.
const $$=s=>document.querySelector(s);
const esc=v=>String(v).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const svgNS2='http://www.w3.org/2000/svg';
const elP=(name,attrs={})=>{const n=document.createElementNS(svgNS2,name);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));return n};
const usd=v=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(v);
const pct=v=>`${(v*100).toFixed(1)}%`;

// Mirror of verifier/verify.mjs canonicalize + quantizeMicro (commitment parity).
const canonicalizeP=v=>Array.isArray(v)?v.map(canonicalizeP):(v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,canonicalizeP(v[k])])):v);
const quantizeMicroP=v=>{
  if(v===null||typeof v==='string'||typeof v==='boolean')return v;
  if(typeof v==='number')return Number.isInteger(v)?v:Math.floor(v*1e6+0.5);
  if(Array.isArray(v))return v.map(quantizeMicroP);
  return Object.fromEntries(Object.entries(v).map(([k,x])=>[k,quantizeMicroP(x)]));
};
async function sha256Hex(text){
  const data=new TextEncoder().encode(text);
  const digest=await crypto.subtle.digest('SHA-256',data);
  return [...new Uint8Array(digest)].map(b=>b.toString(16).padStart(2,'0')).join('');
}
async function recomputeCommitment(pi){
  const basis={candidate:pi.candidate,model_release:pi.model_release,
    prior_manifest_sha256:pi.prior_manifest_sha256,as_of_cutoff:pi.as_of_cutoff,
    abstained:pi.abstained,interventions:pi.interventions};
  return sha256Hex(JSON.stringify(canonicalizeP(quantizeMicroP(basis))));
}

const LABELS={wait_incumbent:'Wait for incumbent',expedite_shipment:'Expedite shipment',
  activate_alternate:'Activate alternate supplier',split_order:'Split order'};

function renderBands(pi){
  const svg=$$('#posterior-bands');
  const ranking=pi.recommendation.ranking;
  const maxDay=Math.max(...ranking.map(n=>pi.interventions[n].delay.interval.high_days))*1.12;
  const width=940,rowH=64,left=250,right=60,plot=width-left-right;
  svg.setAttribute('viewBox',`0 0 ${width} ${ranking.length*rowH+40}`);
  const x=d=>left+plot*(d/maxDay);
  [7,14,21,28,42].filter(d=>d<maxDay).forEach(d=>{
    svg.appendChild(elP('line',{x1:x(d),y1:8,x2:x(d),y2:ranking.length*rowH+8,class:'band-grid'}));
    const t=elP('text',{x:x(d),y:ranking.length*rowH+26,class:'band-axis'});t.textContent=`${d}d`;svg.appendChild(t);
  });
  ranking.forEach((name,i)=>{
    const p=pi.interventions[name],d=p.delay,y=26+i*rowH;
    const label=elP('text',{x:8,y:y+4,class:'band-label'+(i===0?' best':'')});
    label.textContent=(i===0?'★ ':'')+(LABELS[name]||name);svg.appendChild(label);
    const sub=elP('text',{x:8,y:y+20,class:'band-sub'});
    sub.textContent=`P(>14d) ${pct(d.p_exceeds_days['14'])} · stockout ${pct(p.stockout.p)} · exposure p50 ${usd(p.exposure_usd.quantiles_usd.p50)}`;
    svg.appendChild(sub);
    // interval-band: 80% predictive interval
    svg.appendChild(elP('rect',{x:x(d.interval.low_days),y:y-12,width:Math.max(2,x(d.interval.high_days)-x(d.interval.low_days)),height:20,rx:4,class:'interval-band'+(i===0?' best':'')}));
    // p10 / p90 whisker dots and median tick
    svg.appendChild(elP('circle',{cx:x(d.quantiles_days.p10),cy:y-2,r:3,class:'band-dot'}));
    svg.appendChild(elP('circle',{cx:x(d.quantiles_days.p90),cy:y-2,r:3,class:'band-dot'}));
    svg.appendChild(elP('line',{x1:x(d.quantiles_days.p50),y1:y-16,x2:x(d.quantiles_days.p50),y2:y+12,class:'band-median'}));
    const med=elP('text',{x:x(d.quantiles_days.p50)+6,y:y-18,class:'band-med-label'});
    med.textContent=`${d.quantiles_days.p50.toFixed(1)}d`;svg.appendChild(med);
    if(!p.effect_supported){
      const tag=elP('text',{x:width-right+4,y:y+2,class:'band-assumed'});tag.textContent='ASSUMED';svg.appendChild(tag);
    }
  });
}

function supportClass(state){return {strong:'ok',moderate:'ok',weak:'warn',unsupported:'bad'}[state]||'warn'}

async function loadPosterior(){
  const response=await fetch('/api/run');const run=await response.json();
  const pi=run.posterior_intelligence;
  if(!pi){$$('#posterior-content').innerHTML='<p>No posterior intelligence block in this run. Run `make check`.</p>';return;}
  const g=pi.governed;
  const commitment=await recomputeCommitment(pi).catch(()=>null);
  const commitmentOk=commitment===pi.predictive_distribution_commitment;
  $$('#posterior-head').innerHTML=
    `<span class="chip ${supportClass(g.support_state)}">PRIOR SUPPORT · ${esc(g.support_state.toUpperCase())}</span>`+
    `<span class="chip ${g.shift_score>=0.8?'bad':g.shift_score>=0.5?'warn':'ok'}">SHIFT SCORE · ${g.shift_score===null?'UNKNOWN':esc(g.shift_score.toFixed(3))}</span>`+
    `<span class="chip">K · ${esc(pi.K)} PRIOR TASKS</span>`+
    `<span class="chip">CONTEXT · ${esc(pi.context_length)}</span>`+
    `<span class="chip ${commitmentOk?'ok':'bad'}" id="commitment-badge">COMMITMENT ${commitmentOk?'RECOMPUTED ✓':'MISMATCH ✗'}</span>`+
    `<span class="chip">${esc(pi.candidate)} · ${esc(pi.model_release)}</span>`;
  if(pi.abstained){
    $$('#posterior-content').innerHTML=`<div class="abstain-card"><h3>ENGINE ABSTAINED</h3><p>${esc(pi.recommendation.abstain_reason||'outside validated support')}</p><p>No numbers are published outside validated support. abstained=true is itself a signed, verifiable output.</p></div>`;
    return;
  }
  renderBands(pi);
  const rec=pi.recommendation;
  $$('#posterior-recommendation').innerHTML=
    `<h3>${esc(LABELS[rec.recommended_intervention]||rec.recommended_intervention)}</h3>`+
    `<p>Median exposure ${usd(rec.expected_exposure_p50_usd)} vs incumbent ${usd(rec.incumbent_exposure_p50_usd)} · P(delay&gt;14d) ${pct(rec.p_delay_exceeds_14_recommended)} vs ${pct(rec.p_delay_exceeds_14_incumbent)}</p>`+
    `<p class="basis">${esc(rec.decision_basis)}</p>`+
    `<p class="falsify"><b>WHAT WOULD FALSIFY THIS</b> · ${esc(rec.what_would_falsify)}</p>`+
    (g.adjustments.length?`<p class="basis">GOVERNOR · ${g.adjustments.map(esc).join(' · ')}</p>`:'');
  const cal=pi.calibration_receipt;
  $$('#posterior-calibration').innerHTML=
    `<span class="chip ${cal.coverage80_micro>=cal.coverage_band_micro[0]&&cal.coverage80_micro<=cal.coverage_band_micro[1]?'ok':'bad'}">COVERAGE@80 · ${(cal.coverage80_micro/1e4).toFixed(1)}%</span>`+
    `<span class="chip">HOLDOUT NLL · ${(cal.nll_micro/1e6).toFixed(3)}</span>`+
    `<span class="chip">CRPS · ${(cal.crps_micro/1e6).toFixed(3)}</span>`+
    `<span class="chip ok">COURT · ${esc(pi.benchmark_court.decision.toUpperCase())}D</span>`+
    `<small>calibration_receipt ${esc(pi.calibration_receipt_sha256.slice(0,16))}… · ${esc(pi.benchmark_court.court_receipt_id)}</small>`;
  const sel=pi.selection_receipt;
  const excluded=sel.decisions.filter(d=>d.decision==='excluded').length;
  $$('#posterior-provenance').innerHTML=
    `<p><b>KNOWN</b> · ${esc(pi.K)} eligible prior tasks (tenant + as-of ${esc(pi.as_of_cutoff)} enforced) · ${excluded} excluded with reasons</p>`+
    `<p><b>ASSUMED</b> · class-comparable tasks share the latent regime · fixed recovery multiplier</p>`+
    `<p><b>UNKNOWN</b> · actual disruption duration · unmodeled regime breaks (watch shift score)</p>`+
    `<div class="task-chips">${sel.included_prior_task_ids.map(id=>`<span class="task-chip">${esc(id)}</span>`).join('')}</div>`+
    `<small>registry ${esc(pi.prior_registry.registry_release_id)} · manifest ${esc(pi.prior_manifest_sha256.slice(0,16))}… · selection receipt ${esc(sel.receipt_sha256.slice(0,16))}…</small>`;
}
loadPosterior().catch(e=>{$$('#posterior-content').innerHTML=`<p>Posterior panel unavailable: ${esc(e.message)}</p>`});
