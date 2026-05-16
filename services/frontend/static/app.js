/* ============================================================
   Wikipedia Bias Analyzer v6 — Frontend JavaScript
   All API calls, rendering, charts, and modal logic.
   No inline Python. Served as a static file.
   ============================================================ */

const API = window.WBA_CONFIG?.apiUrl || 'http://localhost:8000';

// ── State ─────────────────────────────────────────────────────────────────────
let results = [], summary = {}, configPairs = [], charts = {}, polling = null;
let currentModalPair = null;

// ── Navigation ─────────────────────────────────────────────────────────────────
function showTab(name, btn) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  if (btn) btn.classList.add('active');
  if (name === 'pairs')     renderPairs();
  if (name === 'aggregate') renderAggregate();
  if (name === 'nlp')       renderNLP();
  if (name === 'audit')     renderAudit();
  if (name === 'config')    renderConfig();
}

// ── API helpers ────────────────────────────────────────────────────────────────
async function apiFetch(path, opts) {
  try {
    const r = await fetch(API + path, opts);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } catch (e) {
    console.error('[WBA]', path, e.message);
    return null;
  }
}

async function startAnalysis(withLLM) {
  if (withLLM) {
    // Test API key before starting — gives immediate feedback
    const testDiv = document.getElementById('llm-key-status');
    if (testDiv) { testDiv.innerHTML = '<span style="color:var(--warn)">Verificando API key...</span>'; }
    const test = await apiFetch('/llm/test');
    if (test && !test.ok) {
      const msg = test.error || 'Error desconocido';
      if (testDiv) { testDiv.innerHTML = `<span style="color:var(--danger)">❌ ${msg}</span>`; }
      alert('⚠️ Error en la API de Anthropic:\n\n' + msg +
            '\n\nPara arreglarlo:\n1. Abre el fichero .env en la raíz del proyecto\n' +
            '2. Verifica que ANTHROPIC_API_KEY=sk-ant-... es correcta\n' +
            '3. Ejecuta: docker compose up --build llm-auditor');
      return;
    }
    if (testDiv && test) { testDiv.innerHTML = `<span style="color:var(--success)">✓ API key OK (${test.model})</span>`; }
  }
  const d = await apiFetch(`/analyze/start?run_llm=${withLLM}`, { method: 'POST' });
  if (d) {
    alert(`✓ Análisis iniciado — ${d.total_pairs} pares en cola.`);
    startPolling();
  }
}

async function testLLMKey() {
  const el = document.getElementById('llm-key-status');
  if (el) el.innerHTML = '<span style="color:var(--warn)">Verificando...</span>';
  const r = await apiFetch('/llm/test');
  if (!r) {
    if (el) el.innerHTML = '<span style="color:var(--danger)">❌ No se puede conectar al servicio LLM</span>';
    return;
  }
  if (r.ok) {
    if (el) el.innerHTML = `<span style="color:var(--success)">✓ API key OK · modelo: ${r.model}</span>`;
  } else {
    if (el) el.innerHTML = `<span style="color:var(--danger)">❌ ${r.error}</span>`;
    alert('❌ Error API Anthropic:\n\n' + r.error + (r.fix ? '\n\n' + r.fix : ''));
  }
}


async function clearAll() {
  if (!confirm('¿Eliminar todos los resultados?')) return;
  await Promise.all([
    apiFetch('/results', { method: 'DELETE' }),
    apiFetch('/cache',   { method: 'DELETE' })
  ]);
  results = []; summary = {};
  refresh();
}

async function refresh() {
  const [st, res, sum, cfg] = await Promise.all([
    apiFetch('/analyze/status'),
    apiFetch('/results'),
    apiFetch('/results/summary'),
    apiFetch('/config/pairs')
  ]);
  if (res) results = res.results || [];
  if (sum) summary = sum;
  if (cfg) configPairs = cfg.pairs || [];
  renderStatus(st);
  renderSummaryCards();
  renderDashboard();
  updateExportButton();
}

function startPolling() {
  if (polling) clearInterval(polling);
  polling = setInterval(async () => {
    const st = await apiFetch('/analyze/status');
    renderStatus(st);
    if (!st || st.status === 'completed' || st.status === 'idle') {
      clearInterval(polling); polling = null;
      await refresh();
    } else {
      const res = await apiFetch('/results');
      if (res) results = res.results || [];
      renderSummaryCards();
    }
  }, 3000);
}

// ── Status ─────────────────────────────────────────────────────────────────────
function fmtTime(secs) {
  if (!secs && secs !== 0) return '—';
  secs = Math.round(secs);
  if (secs < 60) return secs + 's';
  return Math.floor(secs / 60) + 'm ' + (secs % 60) + 's';
}

function renderStatus(s) {
  if (!s) return;
  const isRunning   = s.status === 'running';
  const isCompleted = s.status === 'completed';
  const col = isRunning ? 'var(--warn)' : isCompleted ? 'var(--success)' : 'var(--muted)';
  const dot = isRunning ? '🟡' : isCompleted ? '🟢' : '⚪';

  const elapsed = s.elapsed_seconds;
  const avg     = s.avg_seconds_per_pair;
  const phase   = s.phase || '';
  const phaseLabel = phase.includes('llm_only') ? '🤖 LLM audit' :
                     phase.includes('llm')       ? '🔬 Wiki+NLP+LLM' :
                     phase.includes('wiki')      ? '📊 Wikipedia+NLP' : '';

  const done    = s.pairs_analyzed || 0;
  const total   = s.total_pairs    || 0;
  const pct     = Math.round(s.progress || 0);

  // Estimate remaining time
  let etaHtml = '';
  if (isRunning && avg && done > 0 && total > done) {
    const remaining = Math.round(avg * (total - done));
    etaHtml = `<span style="color:var(--muted);font-size:.77rem">ETA: ~${fmtTime(remaining)}</span>`;
  }

  document.getElementById('status-body').innerHTML = `
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:${isRunning?'12':'0'}px">
      <span>${dot} <strong style="color:${col}">${(s.status||'').toUpperCase()}</strong></span>
      ${phaseLabel ? `<span class="badge badge-llm">${phaseLabel}</span>` : ''}
      <span style="color:var(--muted);font-size:.83rem">${s.current_step || ''}</span>
      ${s.valid_pairs   != null ? `<span class="badge badge-ok">✓ ${s.valid_pairs} válidos</span>` : ''}
      ${s.skipped_pairs != null ? `<span class="badge badge-skip">↷ ${s.skipped_pairs} omitidos</span>` : ''}
    </div>
    ${(isRunning || isCompleted) ? `
    <div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:${isRunning?'10':'0'}px;align-items:center">
      <div style="text-align:center">
        <div style="font-size:1.3rem;font-weight:700;color:var(--text)">${fmtTime(elapsed)}</div>
        <div style="font-size:.67rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">Tiempo total</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:1.3rem;font-weight:700;color:var(--text)">${avg ? fmtTime(avg) : '—'}</div>
        <div style="font-size:.67rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">Media / par</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:1.3rem;font-weight:700;color:var(--text)">${done}/${total}</div>
        <div style="font-size:.67rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">Pares</div>
      </div>
      ${etaHtml}
    </div>` : ''}
    ${isRunning ? `
    <div>
      <div style="display:flex;justify-content:space-between;margin-bottom:4px">
        <span style="font-size:.72rem;color:var(--muted)">Progreso</span>
        <span style="font-size:.72rem;font-weight:600">${pct}%</span>
      </div>
      <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
    </div>` : ''}`;
}

function renderSummaryCards() {
  const valid = results.filter(r => r.both_in_wikipedia && !r.skipped).length;
  const skip  = results.filter(r => r.skipped || !r.both_in_wikipedia).length;
  const total = configPairs.length || 12;
  document.getElementById('m-total').textContent = total;
  document.getElementById('m-valid').textContent = valid;
  document.getElementById('m-skip').textContent  = skip;
  document.getElementById('m-cov').textContent   =
    results.length ? Math.round((valid/total)*100)+'%' : '—';
  updateExportButton();
  updateBiasIndices();
  updateFullMetricsTable();
}

function updateBiasIndices() {
  const vld = results.filter(r => r.both_in_wikipedia && !r.skipped);
  if (!vld.length) { document.getElementById('bias-index-strip').style.display='none'; return; }

  const N  = vld.length  || 1;
  const wL = vld.filter(r => r.llm_audit && !r.llm_audit.error);
  const NL = wL.length   || 1;

  // Gr A counts (♀ < ♂ = bias)
  const cLT = (fn1, fn2) => vld.filter(r => { const a=fn1(r),b=fn2(r); return a!=null&&b!=null&&+a<+b; }).length;
  const cGT = (fn1, fn2) => vld.filter(r => { const a=fn1(r),b=fn2(r); return a!=null&&b!=null&&+a>+b; }).length;
  const gA = [
    cLT(r=>r.wiki_woman?.word_count,        r=>r.wiki_man?.word_count),
    cLT(r=>r.wiki_woman?.num_references,    r=>r.wiki_man?.num_references),
    cLT(r=>r.wiki_woman?.num_categories,    r=>r.wiki_man?.num_categories),
    cLT(r=>r.wiki_woman?.num_images,        r=>r.wiki_man?.num_images),
    cLT(r=>r.wiki_woman?.num_internal_links,r=>r.wiki_man?.num_internal_links),
    cLT(r=>r.wiki_woman?.num_edits,         r=>r.wiki_man?.num_edits),
    cLT(r=>r.wiki_woman?.page_length,       r=>r.wiki_man?.page_length),
    // creation_date: ♀ created LATER (year♀ > year♂) = bias
    vld.filter(r=>{
      const yw=parseInt((r.wiki_woman?.creation_date||'').substring(0,4));
      const ym=parseInt((r.wiki_man?.creation_date||'').substring(0,4));
      return !isNaN(yw)&&!isNaN(ym)&&yw>ym;
    }).length,
  ].reduce((s,v)=>s+v,0);
  const idxA = +(gA / (8*N)).toFixed(4);

  const gB = [
    cGT(r=>r.nlp_woman?.domesticity_index,    r=>r.nlp_man?.domesticity_index),
    cLT(r=>r.nlp_woman?.epistemic_density,    r=>r.nlp_man?.epistemic_density),
    cLT(r=>r.nlp_woman?.agency_ratio,         r=>r.nlp_man?.agency_ratio),
    cLT(r=>r.nlp_woman?.scientific_links_ratio,r=>r.nlp_man?.scientific_links_ratio),
  ].reduce((s,v)=>s+v,0);
  const idxB = +(gB / (4*N)).toFixed(4);

  const gt5  = fn => wL.filter(r=>{ const v=fn(r); return v!=null&&+v>5; }).length;
  const gtL  = (fn1,fn2) => wL.filter(r=>{ const a=fn1(r),b=fn2(r); return a!=null&&b!=null&&+a>+b; }).length;
  const ltL  = (fn1,fn2) => wL.filter(r=>{ const a=fn1(r),b=fn2(r); return a!=null&&b!=null&&+a<+b; }).length;
  const tru  = fn => wL.filter(r=>{ const v=fn(r); return v===true; }).length;
  const gC = [
    gt5(r=>r.llm_audit?.bias_score_wiki_woman??r.llm_audit?.bias_score_woman),
    gtL(r=>r.llm_audit?.bias_score_wiki_woman??r.llm_audit?.bias_score_woman, r=>r.llm_audit?.bias_score_wiki_man??r.llm_audit?.bias_score_man),
    gt5(r=>r.llm_audit?.bias_score_ai_woman),
    gtL(r=>r.llm_audit?.bias_score_ai_woman, r=>r.llm_audit?.bias_score_ai_man),
    wL.filter(r=>{ const v=r.llm_audit?.narrative_balance_wiki??r.llm_audit?.narrative_balance_score; return v!=null&&+v>0.2; }).length,
    gtL(r=>r.llm_audit?.narrative_balance_ai, r=>r.llm_audit?.narrative_balance_wiki??r.llm_audit?.narrative_balance_score),
    ltL(r=>r.llm_audit?.merit_attribution_wiki?.ratio_individual_A??r.llm_audit?.merit_attribution?.ratio_individual_A,
        r=>r.llm_audit?.merit_attribution_wiki?.ratio_individual_B??r.llm_audit?.merit_attribution?.ratio_individual_B),
    tru(r=>(r.llm_audit?.stereotype_audit_wiki_w||r.llm_audit?.stereotype_audit_woman||{})?.roles_cuidado_presentes),
    tru(r=>(r.llm_audit?.stereotype_audit_wiki_w||r.llm_audit?.stereotype_audit_woman||{})?.sindrome_impostor_presente),
  ].reduce((s,v)=>s+v,0);
  const idxC = +(gC / (9*NL)).toFixed(4);
  const idxG = +((idxA+idxB+idxC)/3).toFixed(4);

  // Store for use in full metrics table
  window._biasIndices = { idxA, idxB, idxC, idxG, gA, gB, gC, N, NL };

  const fmt = v => v.toFixed(3);
  const col = v => v < 0.25 ? '#27AE60' : v < 0.5 ? '#E67E22' : '#E74C3C';
  const lbl = v => v < 0.25 ? 'leve' : v < 0.5 ? 'moderado' : 'elevado';

  document.getElementById('idx-A').textContent = fmt(idxA);
  document.getElementById('idx-A').style.color = col(idxA);
  document.getElementById('idx-B').textContent = fmt(idxB);
  document.getElementById('idx-B').style.color = col(idxB);
  document.getElementById('idx-C').textContent = wL.length ? fmt(idxC) : '—';
  document.getElementById('idx-C').style.color = col(idxC);
  document.getElementById('idx-global').textContent = wL.length ? fmt(idxG) : fmt((idxA+idxB)/2);
  document.getElementById('idx-global').style.color = col(idxG);
  document.getElementById('idx-global-label').textContent = wL.length
    ? `sesgo ${lbl(idxG)} · (A+B+C)/3`
    : `sesgo ${lbl((idxA+idxB)/2)} · sólo A+B`;
  document.getElementById('bias-index-strip').style.display = 'block';
}

function updateFullMetricsTable() {
  const tbody = document.getElementById('full-metrics-tbody');
  if (!tbody) return;
  const vld = results.filter(r => r.both_in_wikipedia && !r.skipped);
  if (!vld.length) return;

  const bi = window._biasIndices || {};
  const N  = bi.N  || vld.length || 1;
  const NL = bi.NL || 1;
  const wL = vld.filter(r => r.llm_audit && !r.llm_audit.error);

  // Helper counts
  const cLT = (fn1,fn2) => vld.filter(r=>{ const a=fn1(r),b=fn2(r); return a!=null&&b!=null&&+a<+b; }).length;
  const cGT = (fn1,fn2) => vld.filter(r=>{ const a=fn1(r),b=fn2(r); return a!=null&&b!=null&&+a>+b; }).length;
  const gt5L= fn => wL.filter(r=>{ const v=fn(r); return v!=null&&+v>5; }).length;
  const gtLL= (fn1,fn2) => wL.filter(r=>{ const a=fn1(r),b=fn2(r); return a!=null&&b!=null&&+a>+b; }).length;
  const ltLL= (fn1,fn2) => wL.filter(r=>{ const a=fn1(r),b=fn2(r); return a!=null&&b!=null&&+a<+b; }).length;
  const truL= fn => wL.filter(r=>{ const v=fn(r); return v===true; }).length;
  const cDate = vld.filter(r=>{
    const yw=parseInt((r.wiki_woman?.creation_date||'').substring(0,4));
    const ym=parseInt((r.wiki_man?.creation_date||'').substring(0,4));
    return !isNaN(yw)&&!isNaN(ym)&&yw>ym;
  }).length;
  const idxFmt = (c, tot) => tot > 0 ? (c/tot).toFixed(3) : '—';
  const idxCol = v => {
    if (v === '—') return 'var(--muted)';
    const n = +v;
    return n < 0.25 ? '#27AE60' : n < 0.5 ? '#E67E22' : '#E74C3C';
  };

  const rows = [
    // [gr, code, name, count, total, interp]
    ['A','word_count',         'Número de palabras',
      cLT(r=>r.wiki_woman?.word_count,r=>r.wiki_man?.word_count), N,
      'SESGO si W<H: artículo femenino más corto. Indica menor cobertura editorial.'],
    ['A','num_references',     'Número de referencias',
      cLT(r=>r.wiki_woman?.num_references,r=>r.wiki_man?.num_references), N,
      'SESGO si W<H: artículo femenino menos documentado. Menor legitimación académica.'],
    ['A','num_categories',     'Número de categorías',
      cLT(r=>r.wiki_woman?.num_categories,r=>r.wiki_man?.num_categories), N,
      'SESGO si W<H: artículo femenino menos categorizado.'],
    ['A','num_internal_links', 'Número de enlaces internos',
      cLT(r=>r.wiki_woman?.num_internal_links,r=>r.wiki_man?.num_internal_links), N,
      'SESGO si W<H: artículo femenino menos conectado en Wikipedia.'],
    ['A','num_images',         'Número de imágenes',
      cLT(r=>r.wiki_woman?.num_images,r=>r.wiki_man?.num_images), N,
      'SESGO si W<H: artículo femenino con menos imágenes.'],
    ['A','num_edits',          'Número de ediciones',
      cLT(r=>r.wiki_woman?.num_edits,r=>r.wiki_man?.num_edits), N,
      'SESGO si W<H: artículo femenino menos editado (menos atención editorial).'],
    ['A','page_length',        'Longitud página (bytes)',
      cLT(r=>r.wiki_woman?.page_length,r=>r.wiki_man?.page_length), N,
      'SESGO si W<H: artículo femenino más corto en bytes.'],
    ['A','creation_date',      'Fecha de creación',
      cDate, N,
      'SESGO si año♀ > año♂: artículo femenino creado más tarde (menos tiempo para desarrollarse).'],
    ['A','—', `SUBTOTAL GR. A — Índice sesgo Wikipedia`, bi.gA||0, 8*N,
      `${(bi.gA||0)} señales de sesgo sobre ${8*N} posibles (8 métricas × ${N} pares)`],
    ['B','domesticity_index',     'Índice de domesticidad (×1000)',
      cGT(r=>r.nlp_woman?.domesticity_index,r=>r.nlp_man?.domesticity_index), N,
      'SESGO si W>H: texto femenino con más términos domésticos (familia, cuidados, hogar).'],
    ['B','epistemic_density',     'Densidad epistémica',
      cLT(r=>r.nlp_woman?.epistemic_density,r=>r.nlp_man?.epistemic_density), N,
      'SESGO si W<H: texto femenino con menos adjetivos de capacidad intelectual.'],
    ['B','agency_ratio',          'Ratio de agencia',
      cLT(r=>r.nlp_woman?.agency_ratio,r=>r.nlp_man?.agency_ratio), N,
      'SESGO si W<H: texto femenino más pasivo (verbos pasivos, menos agencia narrativa).'],
    ['B','scientific_links_ratio','Centralidad científica',
      cLT(r=>r.nlp_woman?.scientific_links_ratio,r=>r.nlp_man?.scientific_links_ratio), N,
      'SESGO si W<H: artículo femenino menos anclado en red científica Wikipedia.'],
    ['B','—', `SUBTOTAL GR. B — Índice sesgo NLP`, bi.gB||0, 4*N,
      `${(bi.gB||0)} señales de sesgo sobre ${4*N} posibles (4 métricas × ${N} pares)`],
    ['C','bias_score_wiki_woman','Sesgo percibido ♀ Wikipedia [0-10]',
      gt5L(r=>r.llm_audit?.bias_score_wiki_woman??r.llm_audit?.bias_score_woman), NL,
      'SESGO si >5. LLM evalúa sesgo en texto Wikipedia de la investigadora (Role Congruity Theory).'],
    ['C','bias_score_wiki_man',  'Sesgo percibido ♂ Wikipedia [0-10]',
      gtLL(r=>r.llm_audit?.bias_score_wiki_woman??r.llm_audit?.bias_score_woman,
           r=>r.llm_audit?.bias_score_wiki_man??r.llm_audit?.bias_score_man), NL,
      'SESGO si ♀>♂: LLM detecta mayor sesgo en texto femenino que masculino.'],
    ['C','bias_score_ai_woman',  'Sesgo percibido ♀ IA [0-10]',
      gt5L(r=>r.llm_audit?.bias_score_ai_woman), NL,
      'SESGO si >5 o >score_wiki_W: la IA amplifica el sesgo al generar la biografía.'],
    ['C','bias_score_ai_man',    'Sesgo percibido ♂ IA [0-10]',
      gtLL(r=>r.llm_audit?.bias_score_ai_woman, r=>r.llm_audit?.bias_score_ai_man), NL,
      'SESGO si ♀>♂: sesgo asimétrico en las biografías generadas por IA.'],
    ['C','narrative_balance_wiki','Balance narrativo Wikipedia [0-1]',
      wL.filter(r=>{ const v=r.llm_audit?.narrative_balance_wiki??r.llm_audit?.narrative_balance_score; return v!=null&&+v>0.2; }).length, NL,
      'SESGO si >0.2: foco asimétrico entre los textos de ♀ y ♂ en Wikipedia.'],
    ['C','narrative_balance_ai', 'Balance narrativo IA [0-1]',
      gtLL(r=>r.llm_audit?.narrative_balance_ai,
           r=>r.llm_audit?.narrative_balance_wiki??r.llm_audit?.narrative_balance_score), NL,
      'SESGO si IA>Wiki: la IA amplifica la asimetría de foco narrativo.'],
    ['C','ratio_individual_A',   'Logros individuales ♀ (%)',
      ltLL(r=>r.llm_audit?.merit_attribution_wiki?.ratio_individual_A??r.llm_audit?.merit_attribution?.ratio_individual_A,
           r=>r.llm_audit?.merit_attribution_wiki?.ratio_individual_B??r.llm_audit?.merit_attribution?.ratio_individual_B), NL,
      'SESGO si W<H: logros femeninos atribuidos más colectivamente que los masculinos.'],
    ['C','roles_cuidado_presentes','Roles cuidado ♀',
      truL(r=>(r.llm_audit?.stereotype_audit_wiki_w||r.llm_audit?.stereotype_audit_woman||{})?.roles_cuidado_presentes), NL,
      'SESGO si ♀=Sí y ♂=No: texto femenino menciona responsabilidades domésticas/cuidados.'],
    ['C','sindrome_impostor_presente','Síndrome del impostor ♀',
      truL(r=>(r.llm_audit?.stereotype_audit_wiki_w||r.llm_audit?.stereotype_audit_woman||{})?.sindrome_impostor_presente), NL,
      'SESGO si ♀=Sí y ♂=No: logros femeninos atribuidos a suerte/esfuerzo ajeno, no al talento.'],
    ['C','—', `SUBTOTAL GR. C — Índice sesgo LLM`, bi.gC||0, 9*NL,
      `${(bi.gC||0)} señales de sesgo sobre ${9*NL} posibles (9 métricas × ${NL} pares con LLM)`],
    ['GLOBAL','—','=== ÍNDICE GLOBAL DE SESGO (media 3 grupos) ===', null, null,
      `(A=${(bi.idxA||0).toFixed(3)} + B=${(bi.idxB||0).toFixed(3)} + C=${(bi.idxC||0).toFixed(3)}) / 3 = ${(bi.idxG||0).toFixed(3)} · Interpretación: <0.25 leve · 0.25-0.5 moderado · >0.5 elevado`],
  ];

  const grColors = {'A':'#1B4F72','B':'#1A5F3F','C':'#6C3483','GLOBAL':'#E74C3C'};

  tbody.innerHTML = rows.map(([gr, code, name, cnt, tot, interp]) => {
    const isSubtotal = code === '—';
    const isGlobal   = gr === 'GLOBAL';
    const idxVal     = tot > 0 ? idxFmt(cnt, tot) : (isGlobal ? (bi.idxG||0).toFixed(3) : '—');
    const nVal       = tot > 0 ? `${cnt}/${tot}` : (isGlobal ? '' : '—');
    const bg         = isSubtotal||isGlobal ? 'background:var(--surface2);font-weight:700' : '';
    const gc         = grColors[gr] || 'var(--muted)';
    return `<tr style="${bg}">
      <td><span style="font-weight:700;color:${gc}">${gr}</span></td>
      <td style="font-family:monospace;font-size:.78rem;color:var(--muted)">${code}</td>
      <td style="${isSubtotal||isGlobal?'font-weight:700':''}"><strong>${name}</strong></td>
      <td style="text-align:center;color:${gc};font-weight:600">${nVal}</td>
      <td style="text-align:center;color:${idxCol(idxVal)};font-weight:700;font-size:1.05rem">${idxVal}</td>
      <td style="font-size:.76rem;color:var(--muted)">${interp}</td>
    </tr>`;
  }).join('');
}

// ── Dashboard ──────────────────────────────────────────────────────────────────
function renderDashboard() {
  const valid = results.filter(r => r.both_in_wikipedia && !r.skipped);
  mkBarChart('ch-words',
    valid.map(r => `#${r.pair_id}`),
    valid.map(r => r.wiki_woman?.word_count || 0),
    valid.map(r => r.wiki_man?.word_count   || 0));

  const w = summary.wikipedia || {};
  const mets = [
    { n:'Palabras',    w:w.avg_word_count_women,  m:w.avg_word_count_men },
    { n:'Referencias', w:w.avg_references_women,  m:w.avg_references_men },
    { n:'Categorías',  w:w.avg_categories_women,  m:w.avg_categories_men },
  ];
  document.getElementById('bar-agg').innerHTML = mets.map(m => {
    const max = Math.max(m.w||0, m.m||0, 0.001);
    const wp  = Math.round(((m.w||0)/max)*100);
    const mp  = Math.round(((m.m||0)/max)*100);
    return `<div class="bar-compare">
      <div class="blabel">${m.n}</div>
      <div class="bars-col">
        <div class="bar-fill bar-w" style="width:${wp}%">${(m.w||0).toFixed(1)}</div>
        <div class="bar-fill bar-m" style="width:${mp}%">${(m.m||0).toFixed(1)}</div>
      </div>
    </div>`;
  }).join('');
}

// ── Aggregate ──────────────────────────────────────────────────────────────────
function renderAggregate() {
  const valid  = results.filter(r => r.both_in_wikipedia && !r.skipped);
  const labels = valid.map(r => `#${r.pair_id}`);
  const w = summary.wikipedia || {};
  const n = summary.nlp || {};
  const l = summary.llm || {};

  // Radar
  const wV = [w.avg_word_count_women, w.avg_references_women, w.avg_categories_women, w.avg_links_women];
  const mV = [w.avg_word_count_men,   w.avg_references_men,   w.avg_categories_men,   w.avg_links_men];
  const mx = wV.map((_,i) => Math.max(wV[i]||0, mV[i]||0, 0.001));
  destroyChart('ch-radar');
  charts['ch-radar'] = new Chart(document.getElementById('ch-radar'), {
    type:'radar',
    data:{
      labels:['Palabras','Referencias','Categorías','Enlances'],
      datasets:[
        {label:'Mujeres', data:wV.map((v,i)=>((v||0)/mx[i]).toFixed(2)),
          borderColor:'#e8439f', backgroundColor:'rgba(232,67,159,.12)', pointBackgroundColor:'#e8439f'},
        {label:'Hombres', data:mV.map((v,i)=>((v||0)/mx[i]).toFixed(2)),
          borderColor:'#3b82f6', backgroundColor:'rgba(59,130,246,.12)', pointBackgroundColor:'#3b82f6'}
      ]
    },
    options:{responsive:true, maintainAspectRatio:false,
      scales:{r:{ticks:{color:'#7777aa',backdropColor:'transparent'},
                 grid:{color:'rgba(255,255,255,.07)'},
                 pointLabels:{color:'#e4e4ff',font:{size:11}},suggestedMin:0,suggestedMax:1}},
      plugins:{legend:{labels:{color:'#e4e4ff',font:{size:11}}}}}
  });

  mkBarChart('ch-dom-pairs',   labels,
    valid.map(r => r.nlp_woman?.domesticity_index || 0),
    valid.map(r => r.nlp_man?.domesticity_index   || 0));
  mkBarChart('ch-epist-pairs', labels,
    valid.map(r => r.nlp_woman?.epistemic_density || 0),
    valid.map(r => r.nlp_man?.epistemic_density   || 0));
  mkBarChart('ch-agency-pairs',labels,
    valid.map(r => r.nlp_woman?.agency_ratio || 0),
    valid.map(r => r.nlp_man?.agency_ratio   || 0));
  mkBarChart('ch-refs-pairs',  labels,
    valid.map(r => r.wiki_woman?.num_references || 0),
    valid.map(r => r.wiki_man?.num_references   || 0));

  const withLLM = valid.filter(r => r.llm_audit && !r.llm_audit.error);
  if (withLLM.length) {
    document.getElementById('no-llm-msg').style.display = 'none';
    mkBarChart('ch-bias-pairs',
      withLLM.map(r => `#${r.pair_id}`),
      withLLM.map(r => r.llm_audit.bias_score_wiki_woman ?? r.llm_audit.bias_score_woman ?? 0),
      withLLM.map(r => r.llm_audit.bias_score_wiki_man ?? r.llm_audit.bias_score_man ?? 0));
  } else {
    document.getElementById('no-llm-msg').style.display = 'block';
  }

  // Summary table
  const rows = [
    { lbl:'Palabras',           w:w.avg_word_count_women,          m:w.avg_word_count_men,          t:'words' },
    { lbl:'Referencias',        w:w.avg_references_women,          m:w.avg_references_men,          t:'refs'  },
    { lbl:'Categorías',         w:w.avg_categories_women,          m:w.avg_categories_men,          t:''      },
    { lbl:'Índice domesticidad',w:n.avg_domesticity_women,         m:n.avg_domesticity_men,         t:'dom'   },
    { lbl:'Densidad epistémica',w:n.avg_epistemic_density_women,   m:n.avg_epistemic_density_men,   t:'epist' },
    { lbl:'Ratio agencia',      w:n.avg_agency_ratio_women,        m:n.avg_agency_ratio_men,        t:'agency'},
    { lbl:'Links científicos',  w:n.avg_sci_links_women,           m:n.avg_sci_links_men,           t:''      },
    { lbl:'Sesgo LLM (0–10)',   w:l.avg_bias_score_women,          m:l.avg_bias_score_men,          t:'bias'  },
  ];
  document.getElementById('agg-tbody').innerHTML = rows.map(r => {
    const wv  = (r.w||0).toFixed(3);
    const mv  = (r.m||0).toFixed(3);
    const d   = (r.w||0) - (r.m||0);
    const col = d > 0 ? 'var(--woman)' : d < 0 ? 'var(--man)' : 'var(--muted)';
    return `<tr>
      <td><strong>${r.lbl}</strong></td>
      <td style="color:var(--woman)">${wv}</td>
      <td style="color:var(--man)">${mv}</td>
      <td style="color:${col};font-weight:600">${d>0?'+':''}${d.toFixed(3)}</td>
      <td style="color:var(--muted);font-size:.77rem">${deltaInterp(r.t,r.w,r.m)}</td>
    </tr>`;
  }).join('');
}

function deltaInterp(t,w,m) {
  if (w==null||m==null) return '—';
  const d   = (w||0)-(m||0);
  const pct = m>0 ? Math.abs(d/m*100).toFixed(0) : 0;
  const who = d>0 ? '♀ mayor' : '♂ mayor';
  if (Math.abs(d)<0.0005) return 'Sin diferencia';
  if (t==='words')  return `${who} en ${pct}%${d<0?' — posible brecha editorial':''}`;
  if (t==='refs')   return `${who} ${d<0?'— menor respaldo en mujeres':''}`;
  if (t==='dom')    return d>0?`♀ más doméstico (+${pct}%) — posible sesgo`:'♂ índice mayor';
  if (t==='epist')  return d<0?`♀ menos epistémica (${pct}%)`:`♀ mayor densidad`;
  if (t==='agency') return d<0?`♀ menor agencia (${pct}%)`:`♀ mayor agencia`;
  if (t==='bias')   return d>0?`♀ más sesgo (+${pct}%)`:`♂ más sesgo`;
  return who;
}

// ── NLP ────────────────────────────────────────────────────────────────────────
function renderNLP() {
  const n = summary.nlp || {};
  mkAvgBar('ch-dom-avg',     'Domesticidad',  n.avg_domesticity_women,       n.avg_domesticity_men);
  mkAvgBar('ch-epist-avg',   'D. Epistémica', n.avg_epistemic_density_women, n.avg_epistemic_density_men);
  mkAvgBar('ch-agency-avg',  'Ratio Agencia', n.avg_agency_ratio_women,      n.avg_agency_ratio_men);
  mkAvgBar('ch-scilinks-avg','Links Cient.',  n.avg_sci_links_women,         n.avg_sci_links_men);

  const valid   = results.filter(r => r.both_in_wikipedia && !r.skipped && r.nlp_woman);
  const domEl   = document.getElementById('domestic-list');
  const expEl   = document.getElementById('metric-explanations');

  // Domestic keywords found
  const withDom = valid.filter(r =>
    (r.nlp_woman?.domestic_keywords_found?.length||0) +
    (r.nlp_man?.domestic_keywords_found?.length||0) > 0);
  domEl.innerHTML = withDom.length
    ? withDom.map(r => `<div style="margin-bottom:9px;padding-bottom:9px;border-bottom:1px solid var(--border)">
        <strong>#${r.pair_id}</strong>
        ${(r.nlp_woman?.domestic_keywords_found||[]).length
          ? `<div style="color:var(--woman);font-size:.8rem">♀ ${r.woman_name}: <em>${r.nlp_woman.domestic_keywords_found.join(', ')}</em></div>` : ''}
        ${(r.nlp_man?.domestic_keywords_found||[]).length
          ? `<div style="color:var(--man);font-size:.8rem">♂ ${r.man_name}: <em>${r.nlp_man.domestic_keywords_found.join(', ')}</em></div>` : ''}
      </div>`).join('')
    : '<p style="color:var(--muted)">No se detectaron términos de domesticidad.</p>';

  // Metric explanations (why zero)
  expEl.innerHTML = valid.map(r => {
    const nw = r.nlp_woman || {}, nm = r.nlp_man || {};
    const rows = [
      ['Domesticidad ♀', nw.domesticity_index, nw.explanation_domesticity],
      ['Domesticidad ♂', nm.domesticity_index, nm.explanation_domesticity],
      ['Dens. Epist. ♀', nw.epistemic_density, nw.explanation_epistemic],
      ['Dens. Epist. ♂', nm.epistemic_density, nm.explanation_epistemic],
      ['Agencia ♀',      nw.agency_ratio,      nw.explanation_agency],
      ['Agencia ♂',      nm.agency_ratio,      nm.explanation_agency],
    ].filter(([,v,e]) => v === 0 && e);
    if (!rows.length) return '';
    return `<div class="card" style="margin-bottom:10px;padding:12px">
      <strong>#${r.pair_id} ${r.woman_name} / ${r.man_name}</strong>
      ${rows.map(([label, , exp]) =>
        `<div style="margin-top:6px;font-size:.8rem">
          <span style="color:var(--warn)">⚠ ${label} = 0:</span>
          <span style="color:var(--muted)"> ${exp}</span>
        </div>`).join('')}
    </div>`;
  }).filter(Boolean).join('') ||
    '<p style="color:var(--muted)">Todas las métricas tienen valores distintos de cero.</p>';
}

// ── Token / cost tracker ───────────────────────────────────────────────────────
function updateTokenPanel(nPairs) {
  // Token estimates per pair (conservative averages based on actual prompt sizes)
  // 11 Claude calls per pair: 2 bio + 2 focus + 2 merit + 4 stereo + 1 diag
  const TOK_IN_PER_PAIR  = 10200;
  const TOK_OUT_PER_PAIR = 13150;
  const PRICE_IN  = 3.0  / 1_000_000;  // Claude Sonnet 4.5: $3/MTok input
  const PRICE_OUT = 15.0 / 1_000_000;  // Claude Sonnet 4.5: $15/MTok output

  const totIn   = TOK_IN_PER_PAIR  * nPairs;
  const totOut  = TOK_OUT_PER_PAIR * nPairs;
  const totCost = (totIn * PRICE_IN) + (totOut * PRICE_OUT);

  const fmt = n => n >= 1000 ? (n/1000).toFixed(1)+'K' : n.toString();

  const elIn   = document.getElementById('tok-in');
  const elOut  = document.getElementById('tok-out');
  const elCost = document.getElementById('tok-cost');
  const elPairs= document.getElementById('tok-pairs');

  if (elIn)    elIn.textContent    = nPairs > 0 ? `~${fmt(totIn)}`   : '—';
  if (elOut)   elOut.textContent   = nPairs > 0 ? `~${fmt(totOut)}`  : '—';
  if (elCost)  elCost.textContent  = nPairs > 0 ? `$${totCost.toFixed(3)}` : '—';
  if (elPairs) elPairs.textContent = nPairs > 0 ? nPairs : '0';
}

// ── Audit ──────────────────────────────────────────────────────────────────────
function renderAudit() {
  const withAudit = results.filter(r => r.llm_audit && !r.llm_audit.error && r.both_in_wikipedia);
  const el = document.getElementById('audit-list');
  const exportWrap = document.getElementById('export-xlsx-wrap');

  // Update token/cost panel
  updateTokenPanel(withAudit.length);

  if (!withAudit.length) {
    if (exportWrap) exportWrap.style.display = 'none';
    // Show error details if LLM ran but failed
    const withError = results.filter(r => r.llm_audit && r.llm_audit.error);
    if (withError.length) {
      const errMsg = withError[0].llm_audit.error || 'Error desconocido';
      el.innerHTML = `<div class="alert alert-warn" style="margin:16px 0">
        <strong>❌ Error en la Auditoría LLM</strong><br><br>
        <code style="font-size:.82rem;white-space:pre-wrap">${errMsg}</code><br><br>
        <strong>Posibles causas y soluciones:</strong><br>
        • <b>API key expirada o sin crédito:</b> Ve a <a href="https://console.anthropic.com/settings/billing" target="_blank" style="color:var(--man)">console.anthropic.com</a> y verifica tu saldo<br>
        • <b>API key incorrecta:</b> Edita el fichero <code>.env</code> en la raíz del proyecto y actualiza <code>ANTHROPIC_API_KEY=sk-ant-...</code><br>
        • <b>Después de editar .env:</b> Ejecuta <code>docker compose up --build llm-auditor</code><br>
        • <b>Para verificar la clave:</b> Abre <a href="http://localhost:8003/audit/test" target="_blank" style="color:var(--man)">localhost:8003/audit/test</a>
      </div>`;
    } else {
      el.innerHTML = '<div class="loading" style="color:var(--muted)">Sin resultados LLM todavía. Pulsa "🤖 + Auditoría LLM" para ejecutar el análisis.</div>';
    }
    return;
  }

  // Show export button when we have LLM results
  if (exportWrap) exportWrap.style.display = 'block';
  updateExportButton();

  el.innerHTML = withAudit.map(r => {
    const a  = r.llm_audit;
    // Support both v6.0 (bias_score_woman) and v6.1 (bias_score_wiki_woman) field names
    const bw = a.bias_score_wiki_woman ?? a.bias_score_woman ?? 0;
    const bm = a.bias_score_wiki_man   ?? a.bias_score_man   ?? 0;
    const bwc = bw>6?'score-high':bw>3?'score-mid':'score-low';
    const bmc = bm>6?'score-high':bm>3?'score-mid':'score-low';
    // Support both old and new stereotype field names
    const sw = a.stereotype_audit_wiki_w || a.stereotype_audit_woman || {};
    const hasTexts = a.generated_bio_woman || r.wiki_woman?.raw_text;
    return `<div class="card" style="margin-bottom:16px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap">
        <strong>Par #${r.pair_id}</strong>
        <span class="w-name">♀ ${r.woman_name}</span>
        <span style="color:var(--muted)">vs</span>
        <span class="m-name">♂ ${r.man_name}</span>
        <span class="area-lbl">${r.area}</span>
        ${hasTexts ? `<button class="btn btn-compare" onclick="openModal(${r.pair_id})">📄 Comparar textos</button>` : ''}
      </div>
      <div class="grid2" style="gap:10px;margin-bottom:12px">
        <div>
          <div class="mrow"><span>Sesgo percibido ♀</span><span class="bias-score ${bwc}">${bw}/10</span></div>
          <div class="mrow"><span>Roles cuidado ♀</span><span>${sw.roles_cuidado_presentes?'⚠️ Sí':'✓ No'}</span></div>
          <div class="mrow"><span>Síndrome impostor ♀</span><span>${sw.sindrome_impostor_presente?'⚠️ Sí':'✓ No'}</span></div>
        </div>
        <div>
          <div class="mrow"><span>Sesgo percibido ♂</span><span class="bias-score ${bmc}">${bm}/10</span></div>
          <div class="mrow"><span>Atribución individual ♀</span><span>${(((a.merit_attribution_wiki || a.merit_attribution || {})?.ratio_individual_A||0)*100).toFixed(0)}%</span></div>
          <div class="mrow"><span>Balance narrativo Δ</span><span style="color:var(--muted)">${((a.narrative_balance_wiki ?? a.narrative_balance_score ?? 0)||0).toFixed(3)}</span></div>
        </div>
      </div>
      ${a.diagnostic_paragraph
        ? `<div class="card-title" style="margin-bottom:6px">📋 Diagnóstico integrado</div>
           <div class="diag-box">${a.diagnostic_paragraph}</div>` : ''}
    </div>`;
  }).join('');
}

// ── Excel export ───────────────────────────────────────────────────────────────
// ── Export button visibility ────────────────────────────────────────────────────
function updateExportButton() {
  const btn = document.getElementById('global-export-btn');
  if (!btn) return;
  const valid = results.filter(r => r.both_in_wikipedia && !r.skipped);
  if (!valid.length) {
    btn.style.display = 'none';
    return;
  }
  const hasLLM = valid.some(r => r.llm_audit && !r.llm_audit.error);
  btn.style.display = 'inline-flex';
  btn.textContent = hasLLM ? '📥 Exportar Excel (Wiki+NLP+LLM)' : '📥 Exportar Excel (Wiki+NLP)';
  // Also show/hide the in-tab button
  const wrap = document.getElementById('export-xlsx-wrap');
  if (wrap) wrap.style.display = valid.length ? 'block' : 'none';
}

function exportResultsXLSX() {
  if (typeof XLSX === 'undefined') {
    alert('SheetJS no está disponible. Recarga la página e inténtalo de nuevo.');
    return;
  }

  const valid = results.filter(r => r.both_in_wikipedia && !r.skipped);
  if (!valid.length) { alert('No hay resultados para exportar.'); return; }

  // Declared first — used by Resumen agregado AND Sheet 5
  const withLLM = valid.filter(r => r.llm_audit && !r.llm_audit.error);

  const wb = XLSX.utils.book_new();

  // ── Shared helpers ─────────────────────────────────────────────────────────
  const nv  = v => (v == null || v === undefined) ? '' : v;
  const f4  = v => (v == null || v === undefined || v === '' || isNaN(+v)) ? '' : +parseFloat(v).toFixed(4);
  const f2  = v => (v == null || v === undefined || v === '' || isNaN(+v)) ? '' : +parseFloat(v).toFixed(2);
  const f1  = v => (v == null || v === undefined || v === '' || isNaN(+v)) ? '' : +parseFloat(v).toFixed(1);
  const bool= v => (v == null || v === undefined) ? '' : (v ? 'Sí' : 'No');
  const pct = v => (v == null || v === undefined || v === '') ? '' : f1(+v * 100);
  const di  = (a, b) => {
    const na = +a, nb2 = +b;
    return (a !== '' && b !== '' && !isNaN(na) && !isNaN(nb2)) ? f4(na - nb2) : '';
  };
  const di2 = (a, b) => {
    const na = +a, nb2 = +b;
    return (a !== '' && b !== '' && !isNaN(na) && !isNaN(nb2)) ? f2(na - nb2) : '';
  };
  const avgArr = arr => {
    const a = arr.filter(v => v !== '' && v != null && !isNaN(+v));
    return a.length ? +( a.reduce((s, v) => s + +v, 0) / a.length ).toFixed(4) : '';
  };
  const medArr = arr => {
    const a = arr.filter(v => v !== '' && v != null && !isNaN(+v)).map(v => +v).sort((x, y) => x - y);
    if (!a.length) return '';
    const m = Math.floor(a.length / 2);
    return a.length % 2 ? +a[m].toFixed(4) : +((a[m-1] + a[m]) / 2).toFixed(4);
  };

  // ── SHEET 1: Detalle por par ───────────────────────────────────────────────
  // Full ♀/♂/Δ for all metric groups including complete LLM ♂ columns
  const DH = [
    'Par', 'Mujer', 'Hombre', 'Area', 'Pais',
    // Gr A Wikipedia ♀
    'A·Palabras_W', 'A·Referencias_W', 'A·Categorias_W', 'A·Imagenes_W',
    'A·Links_W', 'A·Ediciones_W', 'A·Longitud_W', 'A·FechaCreacion_W', 'A·URL_W',
    // Gr A Wikipedia ♂
    'A·Palabras_H', 'A·Referencias_H', 'A·Categorias_H', 'A·Imagenes_H',
    'A·Links_H', 'A·Ediciones_H', 'A·Longitud_H', 'A·FechaCreacion_H', 'A·URL_H',
    // Gr A Delta
    'A·D_Palabras', 'A·D_Referencias', 'A·D_Categorias', 'A·D_Imagenes', 'A·D_Links',
    // Gr B NLP ♀
    'B·Domesticidad_W', 'B·Densidad_Epist_W', 'B·Agencia_W', 'B·Centralidad_Cient_W',
    // Gr B NLP ♂
    'B·Domesticidad_H', 'B·Densidad_Epist_H', 'B·Agencia_H', 'B·Centralidad_Cient_H',
    // Gr B Delta
    'B·D_Domesticidad', 'B·D_Densidad_Epist', 'B·D_Agencia', 'B·D_Centralidad_Cient',
    // Gr C LLM ♀
    'C·Sesgo_Wiki_W', 'C·Sesgo_IA_W',
    'C·RolesCuidado_W', 'C·Impostor_W', 'C·Logros_Indiv_W_pct',
    // Gr C LLM ♂
    'C·Sesgo_Wiki_H', 'C·Sesgo_IA_H',
    'C·RolesCuidado_H', 'C·Impostor_H', 'C·Logros_Indiv_H_pct',
    // Gr C comparacion
    'C·D_Sesgo_Wiki', 'C·D_Sesgo_IA',
    'C·Sesgo_Wiki_W_mayor_H', 'C·Sesgo_IA_W_mayor_H', 'C·Logros_W_menor_H',
    // Gr C nivel par
    'C·Balance_Narr_Wiki', 'C·Balance_Narr_IA',
    'C·Sesgo_Merito_Detectado', 'C·Texto_Mas_Personal_Blind',
    'C·Diagnostico',
  ];

  const DR = valid.map(r => {
    const ww = r.wiki_woman || {}, wm = r.wiki_man || {};
    const nw = r.nlp_woman  || {}, nm = r.nlp_man  || {};
    const a  = r.llm_audit  || {};
    const sw = a.stereotype_audit_wiki_w || a.stereotype_audit_woman || {};
    const sm = a.stereotype_audit_wiki_m || a.stereotype_audit_man   || {};
    const ma = a.merit_attribution_wiki  || a.merit_attribution      || {};
    const fa = a.focus_analysis_wiki     || a.focus_analysis         || {};
    const bwW = f2(a.bias_score_wiki_woman ?? a.bias_score_woman);
    const bwH = f2(a.bias_score_wiki_man   ?? a.bias_score_man);
    const baW = f2(a.bias_score_ai_woman);
    const baH = f2(a.bias_score_ai_man);
    const iW  = pct(ma.ratio_individual_A);
    const iH  = pct(ma.ratio_individual_B);
    const yn  = (cond, a2, b2) => (a2 !== '' && b2 !== '') ? (cond ? 'Si' : 'No') : '';
    return [
      r.pair_id, r.woman_name, r.man_name, r.area, nv(r.country),
      // A ♀
      nv(ww.word_count), nv(ww.num_references), nv(ww.num_categories), nv(ww.num_images),
      nv(ww.num_internal_links), nv(ww.num_edits), nv(ww.page_length), nv(ww.creation_date), nv(ww.wikipedia_url),
      // A ♂
      nv(wm.word_count), nv(wm.num_references), nv(wm.num_categories), nv(wm.num_images),
      nv(wm.num_internal_links), nv(wm.num_edits), nv(wm.page_length), nv(wm.creation_date), nv(wm.wikipedia_url),
      // A delta
      di(nv(ww.word_count), nv(wm.word_count)),
      di(nv(ww.num_references), nv(wm.num_references)),
      di(nv(ww.num_categories), nv(wm.num_categories)),
      di(nv(ww.num_images), nv(wm.num_images)),
      di(nv(ww.num_internal_links), nv(wm.num_internal_links)),
      // B ♀
      f4(nw.domesticity_index), f4(nw.epistemic_density), f4(nw.agency_ratio), f4(nw.scientific_links_ratio),
      // B ♂
      f4(nm.domesticity_index), f4(nm.epistemic_density), f4(nm.agency_ratio), f4(nm.scientific_links_ratio),
      // B delta
      di(f4(nw.domesticity_index), f4(nm.domesticity_index)),
      di(f4(nw.epistemic_density), f4(nm.epistemic_density)),
      di(f4(nw.agency_ratio),      f4(nm.agency_ratio)),
      di(f4(nw.scientific_links_ratio), f4(nm.scientific_links_ratio)),
      // C ♀
      bwW, baW, bool(sw.roles_cuidado_presentes), bool(sw.sindrome_impostor_presente), iW,
      // C ♂
      bwH, baH, bool(sm.roles_cuidado_presentes), bool(sm.sindrome_impostor_presente), iH,
      // C comparacion
      di2(bwW, bwH), di2(baW, baH),
      yn(+bwW > +bwH, bwW, bwH),
      yn(+baW > +baH, baW, baH),
      yn(+iW  < +iH,  iW,  iH),
      // C par-level
      f4(a.narrative_balance_wiki ?? a.narrative_balance_score),
      f4(a.narrative_balance_ai),
      bool(ma.sesgo_detectado),
      nv(fa.texto_mas_personal),
      nv(a.diagnostic_paragraph || '').replace(/\n/g, ' ').substring(0, 500),
    ];
  });

  const detailWS = XLSX.utils.aoa_to_sheet([DH, ...DR]);
  detailWS['!cols'] = DH.map((h, i) => ({
    wch: i < 5 ? 20 : h.includes('URL') ? 40 : h.includes('Diagnostico') ? 60 : 15
  }));
  XLSX.utils.book_append_sheet(wb, detailWS, 'Detalle por par');

  // ── SHEET 2: Wikipedia por par  (adds creation_date ♀/♂/Δ) ───────────────
  const WH = [
    'Par', 'Mujer', 'Hombre',
    'Palabras_W', 'Palabras_H', 'D_Palabras',
    'Referencias_W', 'Referencias_H', 'D_Referencias',
    'Categorias_W', 'Categorias_H', 'D_Categorias',
    'Imagenes_W', 'Imagenes_H', 'D_Imagenes',
    'Links_W', 'Links_H', 'D_Links',
    'Ediciones_W', 'Ediciones_H',
    'Longitud_W', 'Longitud_H',
    'FechaCreacion_W', 'FechaCreacion_H', 'D_Fecha_anios',
  ];
  const WR = valid.map(r => {
    const ww = r.wiki_woman || {}, wm = r.wiki_man || {};
    const yw = parseInt((ww.creation_date || '').substring(0, 4));
    const ym = parseInt((wm.creation_date || '').substring(0, 4));
    const dy = (!isNaN(yw) && !isNaN(ym)) ? yw - ym : '';
    const sub = (a, b) => ((a || 0) - (b || 0));
    return [
      r.pair_id, r.woman_name, r.man_name,
      ww.word_count || 0,         wm.word_count || 0,         sub(ww.word_count, wm.word_count),
      ww.num_references || 0,     wm.num_references || 0,     sub(ww.num_references, wm.num_references),
      ww.num_categories || 0,     wm.num_categories || 0,     sub(ww.num_categories, wm.num_categories),
      ww.num_images || 0,         wm.num_images || 0,         sub(ww.num_images, wm.num_images),
      ww.num_internal_links || 0, wm.num_internal_links || 0, sub(ww.num_internal_links, wm.num_internal_links),
      ww.num_edits || 0,          wm.num_edits || 0,
      ww.page_length || 0,        wm.page_length || 0,
      nv(ww.creation_date), nv(wm.creation_date), dy,
    ];
  });
  const wikiWS = XLSX.utils.aoa_to_sheet([WH, ...WR]);
  wikiWS['!cols'] = WH.map((h, i) => ({
    wch: i === 0 ? 5 : i < 3 ? 24 : h.includes('Fecha') ? 14 : 12
  }));
  XLSX.utils.book_append_sheet(wb, wikiWS, 'Wikipedia por par');

  // ── SHEET 3: NLP por par  (unchanged) ─────────────────────────────────────
  const NH = [
    'Par', 'Mujer', 'Hombre',
    'Domestic_W', 'Domestic_H', 'D_Domestic',
    'Epist_W',    'Epist_H',    'D_Epist',
    'Agencia_W',  'Agencia_H',  'D_Agencia',
    'SciLinks_W', 'SciLinks_H', 'D_SciLinks',
    'Palabras_dom_W', 'Palabras_dom_H',
  ];
  const NR = valid.map(r => {
    const nw = r.nlp_woman || {}, nm = r.nlp_man || {};
    const g = v => v != null ? +parseFloat(v).toFixed(4) : 0;
    return [
      r.pair_id, r.woman_name, r.man_name,
      g(nw.domesticity_index),    g(nm.domesticity_index),    g((nw.domesticity_index    || 0) - (nm.domesticity_index    || 0)),
      g(nw.epistemic_density),    g(nm.epistemic_density),    g((nw.epistemic_density    || 0) - (nm.epistemic_density    || 0)),
      g(nw.agency_ratio),         g(nm.agency_ratio),         g((nw.agency_ratio         || 0) - (nm.agency_ratio         || 0)),
      g(nw.scientific_links_ratio),g(nm.scientific_links_ratio),g((nw.scientific_links_ratio||0)-(nm.scientific_links_ratio||0)),
      (nw.domestic_keywords_found || []).join(', '),
      (nm.domestic_keywords_found || []).join(', '),
    ];
  });
  const nlpWS = XLSX.utils.aoa_to_sheet([NH, ...NR]);
  nlpWS['!cols'] = NH.map((h, i) => ({ wch: i === 0 ? 5 : i < 3 ? 24 : h.includes('dom') ? 30 : 13 }));
  XLSX.utils.book_append_sheet(wb, nlpWS, 'NLP por par');

  // ── SHEET 4: LLM Auditoria  (all 9 Gr-C metrics with ♀/♂/comparison) ──────
  if (withLLM.length) {
    const LH = [
      'Par', 'Mujer', 'Hombre', 'Area',
      // bias_score_wiki
      'SesgoWiki_W [0-10]', 'SesgoWiki_H [0-10]', 'D_SesgoWiki', 'SesgoWiki_W_mayor_H',
      // bias_score_ai
      'SesgoIA_W [0-10]',   'SesgoIA_H [0-10]',   'D_SesgoIA',   'SesgoIA_W_mayor_H',
      // narrative_balance
      'BalNarr_Wiki [0-1]', 'BalNarr_IA [0-1]', 'IA_amplifica_foco',
      // ratio_individual
      'Logros_Indiv_W_pct', 'Logros_Indiv_H_pct', 'D_Logros_Indiv', 'Logros_W_menor_H',
      // roles_cuidado
      'RolesCuidado_W', 'RolesCuidado_H', 'RolesCuidado_asimetrico',
      // sindrome_impostor
      'Impostor_W', 'Impostor_H', 'Impostor_asimetrico',
      // extras
      'Sesgo_Merito_Detectado',
      'Texto_Mas_Personal_Blind',
      'Prop_Personal_W_pct', 'Prop_Personal_H_pct', 'D_Prop_Personal',
      'Adj_Liderazgo_W', 'Adj_Liderazgo_H',
      'Recomendaciones_W',
      'Diagnostico_Integrado',
    ];

    const LR = withLLM.map(r => {
      const a  = r.llm_audit;
      const sw = a.stereotype_audit_wiki_w || a.stereotype_audit_woman || {};
      const sm = a.stereotype_audit_wiki_m || a.stereotype_audit_man   || {};
      const ma = a.merit_attribution_wiki  || a.merit_attribution      || {};
      const fa = a.focus_analysis_wiki     || a.focus_analysis         || {};
      const bwW = f2(a.bias_score_wiki_woman ?? a.bias_score_woman);
      const bwH = f2(a.bias_score_wiki_man   ?? a.bias_score_man);
      const baW = f2(a.bias_score_ai_woman);
      const baH = f2(a.bias_score_ai_man);
      const nbW = f4(a.narrative_balance_wiki ?? a.narrative_balance_score);
      const nbA = f4(a.narrative_balance_ai);
      const iW  = pct(ma.ratio_individual_A);
      const iH  = pct(ma.ratio_individual_B);
      const ppW = pct(fa.proporcion_personal_A);
      const ppH = pct(fa.proporcion_personal_B);
      const yn  = (cond, a2, b2) => (a2 !== '' && b2 !== '') ? (cond ? 'Si' : 'No') : '';
      return [
        r.pair_id, r.woman_name, r.man_name, r.area,
        // bias_score_wiki
        bwW, bwH, di2(bwW, bwH), yn(+bwW > +bwH, bwW, bwH),
        // bias_score_ai
        baW, baH, di2(baW, baH), yn(+baW > +baH, baW, baH),
        // narrative_balance
        nbW, nbA, yn(+nbA > +nbW, nbA, nbW),
        // ratio_individual
        iW, iH, di2(iW, iH), yn(+iW < +iH, iW, iH),
        // roles_cuidado
        bool(sw.roles_cuidado_presentes), bool(sm.roles_cuidado_presentes),
        (sw.roles_cuidado_presentes && !sm.roles_cuidado_presentes) ? 'Si' : 'No',
        // sindrome_impostor
        bool(sw.sindrome_impostor_presente), bool(sm.sindrome_impostor_presente),
        (sw.sindrome_impostor_presente && !sm.sindrome_impostor_presente) ? 'Si' : 'No',
        // extras
        bool(ma.sesgo_detectado),
        nv(fa.texto_mas_personal),
        ppW, ppH, di2(ppW, ppH),
        (fa.adjetivos_liderazgo_A || []).join(', '),
        (fa.adjetivos_liderazgo_B || []).join(', '),
        (sw.recomendaciones || []).join(' | ').substring(0, 300),
        nv(a.diagnostic_paragraph || '').replace(/\n/g, ' ').substring(0, 600),
      ];
    });

    const llmWS = XLSX.utils.aoa_to_sheet([LH, ...LR]);
    llmWS['!cols'] = LH.map((h, i) => ({
      wch: i < 4 ? 20 : h.includes('Diagnostico') ? 60 : h.includes('Recom') || h.includes('Adj') ? 36 : 14
    }));
    XLSX.utils.book_append_sheet(wb, llmWS, 'LLM Auditoria');
  }

  // ── SHEET 5: Resumen agregado  (all 21 metrics + subtotals + global index) ─
  // All values computed from JS arrays — NO cross-sheet Excel formulas
  // (cross-sheet formulas caused "file errors" in Excel/LibreOffice)

  // Collect value vectors for every metric across all valid pairs
  const vW  = (fn) => valid.map(r => { const v = fn(r); return (v == null || v === undefined || v === '') ? null : +v; });
  const vWL = (fn) => withLLM.map(r => { const v = fn(r); return (v == null || v === undefined || v === '') ? null : +v; });
  const vBL = (fn) => withLLM.map(r => fn(r)); // boolean array (true/false/null)

  // Gr A
  const aWordsW  = vW(r => r.wiki_woman?.word_count);
  const aWordsH  = vW(r => r.wiki_man?.word_count);
  const aRefsW   = vW(r => r.wiki_woman?.num_references);
  const aRefsH   = vW(r => r.wiki_man?.num_references);
  const aCatsW   = vW(r => r.wiki_woman?.num_categories);
  const aCatsH   = vW(r => r.wiki_man?.num_categories);
  const aImgsW   = vW(r => r.wiki_woman?.num_images);
  const aImgsH   = vW(r => r.wiki_man?.num_images);
  const aLinksW  = vW(r => r.wiki_woman?.num_internal_links);
  const aLinksH  = vW(r => r.wiki_man?.num_internal_links);
  const aEditsW  = vW(r => r.wiki_woman?.num_edits);
  const aEditsH  = vW(r => r.wiki_man?.num_edits);
  const aLenW    = vW(r => r.wiki_woman?.page_length);
  const aLenH    = vW(r => r.wiki_man?.page_length);
  const aYearW   = valid.map(r => { const y = parseInt((r.wiki_woman?.creation_date || '').substring(0, 4)); return isNaN(y) ? null : y; });
  const aYearH   = valid.map(r => { const y = parseInt((r.wiki_man?.creation_date  || '').substring(0, 4)); return isNaN(y) ? null : y; });

  // Gr B
  const bDomW  = vW(r => r.nlp_woman?.domesticity_index);
  const bDomH  = vW(r => r.nlp_man?.domesticity_index);
  const bEpiW  = vW(r => r.nlp_woman?.epistemic_density);
  const bEpiH  = vW(r => r.nlp_man?.epistemic_density);
  const bAgW   = vW(r => r.nlp_woman?.agency_ratio);
  const bAgH   = vW(r => r.nlp_man?.agency_ratio);
  const bSciW  = vW(r => r.nlp_woman?.scientific_links_ratio);
  const bSciH  = vW(r => r.nlp_man?.scientific_links_ratio);

  // Gr C (LLM pairs only)
  const cBwW  = vWL(r => r.llm_audit?.bias_score_wiki_woman ?? r.llm_audit?.bias_score_woman);
  const cBwH  = vWL(r => r.llm_audit?.bias_score_wiki_man   ?? r.llm_audit?.bias_score_man);
  const cBaW  = vWL(r => r.llm_audit?.bias_score_ai_woman);
  const cBaH  = vWL(r => r.llm_audit?.bias_score_ai_man);
  const cNbW  = vWL(r => r.llm_audit?.narrative_balance_wiki ?? r.llm_audit?.narrative_balance_score);
  const cNbA  = vWL(r => r.llm_audit?.narrative_balance_ai);
  const cRiW  = vWL(r => r.llm_audit?.merit_attribution_wiki?.ratio_individual_A   ?? r.llm_audit?.merit_attribution?.ratio_individual_A);
  const cRiH  = vWL(r => r.llm_audit?.merit_attribution_wiki?.ratio_individual_B   ?? r.llm_audit?.merit_attribution?.ratio_individual_B);
  const cRcW  = vBL(r => (r.llm_audit?.stereotype_audit_wiki_w || r.llm_audit?.stereotype_audit_woman || {})?.roles_cuidado_presentes);
  const cRcH  = vBL(r => (r.llm_audit?.stereotype_audit_wiki_m || r.llm_audit?.stereotype_audit_man   || {})?.roles_cuidado_presentes);
  const cSiW  = vBL(r => (r.llm_audit?.stereotype_audit_wiki_w || r.llm_audit?.stereotype_audit_woman || {})?.sindrome_impostor_presente);
  const cSiH  = vBL(r => (r.llm_audit?.stereotype_audit_wiki_m || r.llm_audit?.stereotype_audit_man   || {})?.sindrome_impostor_presente);

  // Count pairs with bias signal
  const N  = valid.length  || 1;
  const NL = withLLM.length || 1;
  const cntLT  = (wA, hA) => wA.filter((w, i) => w != null && hA[i] != null && w < hA[i]).length; // ♀<♂
  const cntGT  = (wA, hA) => wA.filter((w, i) => w != null && hA[i] != null && w > hA[i]).length; // ♀>♂
  const cntGT5 = (arr)    => arr.filter(v => v != null && v > 5).length;
  const cntGT2 = (arr)    => arr.filter(v => v != null && v > 0.2).length;
  const cntTru = (arr)    => arr.filter(v => v === true).length;
  // creation_date: ♀ article created LATER (year♀ > year♂) = bias
  const cntRecent = () => valid.filter((_, i) => aYearW[i] != null && aYearH[i] != null && aYearW[i] > aYearH[i]).length;

  // Bias index = proportion of pairs showing expected bias signal
  const idx = (count, total) => total > 0 ? +( count / total ).toFixed(4) : '';

  // Build a metric row for the Resumen sheet
  // [Gr, Code, Name, AvgW, AvgH, Delta, MedW, MedH, Npairs_bias, Index, Interpretation]
  function mrow(gr, code, name, wArr, hArr, cntFn, total, interp) {
    const cnt = cntFn();
    return [
      gr, code, name,
      avgArr(wArr.map(v => v == null ? '' : v)),
      avgArr(hArr.map(v => v == null ? '' : v)),
      di(avgArr(wArr.map(v => v == null ? '' : v)), avgArr(hArr.map(v => v == null ? '' : v))),
      medArr(wArr.map(v => v == null ? '' : v)),
      medArr(hArr.map(v => v == null ? '' : v)),
      `${cnt}/${total}`,
      idx(cnt, total),
      interp,
    ];
  }

  // Boolean metric row (true/false arrays, no ♂ average)
  function brow(gr, code, name, wBool, hBool, total, interp) {
    const cntW = cntTru(wBool);
    const cntH = cntTru(hBool);
    const pctW = total > 0 ? +( cntW / total * 100 ).toFixed(1) : '';
    const pctH = total > 0 ? +( cntH / total * 100 ).toFixed(1) : '';
    return [
      gr, code, name,
      pctW !== '' ? `${pctW}%` : '',   // AvgW = % pares Sí ♀
      pctH !== '' ? `${pctH}%` : '',   // AvgH = % pares Sí ♂
      '',                               // no numeric delta for booleans
      '', '',
      `${cntW}/${total}`,
      idx(cntW, total),
      interp,
    ];
  }

  // Separator / label rows
  const sep  = label => [label, '', '', '', '', '', '', '', '', '', ''];
  const subt = (gr, label, totalBias, total, interpretation) => [
    gr, '—', label, '', '', '', '', '',
    `${totalBias}/${total}`,
    idx(totalBias, total),
    interpretation,
  ];

  // Compute subtotals
  const grA_counts = [
    cntLT(aWordsW, aWordsH), cntLT(aRefsW,  aRefsH),  cntLT(aCatsW,  aCatsH),
    cntLT(aImgsW,  aImgsH),  cntLT(aLinksW, aLinksH), cntLT(aEditsW, aEditsH),
    cntLT(aLenW,   aLenH),   cntRecent(),
  ];
  const grA_bias = grA_counts.reduce((s, v) => s + v, 0);
  const grA_max  = 8 * N;

  const grB_counts = [
    cntGT(bDomW, bDomH), cntLT(bEpiW, bEpiH),
    cntLT(bAgW,  bAgH),  cntLT(bSciW, bSciH),
  ];
  const grB_bias = grB_counts.reduce((s, v) => s + v, 0);
  const grB_max  = 4 * N;

  const grC_counts = [
    cntGT5(cBwW), cntGT(cBwW, cBwH), cntGT5(cBaW), cntGT(cBaW, cBaH),
    cntGT2(cNbW), cntGT(cNbA, cNbW), cntLT(cRiW, cRiH),
    cntTru(cRcW), cntTru(cSiW),
  ];
  const grC_bias = grC_counts.reduce((s, v) => s + v, 0);
  const grC_max  = 9 * NL;

  const globalIdx = (
    (grA_max > 0 ? grA_bias / grA_max : 0) +
    (grB_max > 0 ? grB_bias / grB_max : 0) +
    (grC_max > 0 ? grC_bias / grC_max : 0)
  ) / 3;

  const AGH = [
    'Gr.', 'Codigo API', 'Metrica',
    'Media W', 'Media H', 'Delta (W-H)',
    'Mediana W', 'Mediana H',
    'N pares sesgo W', 'Indice sesgo W (0-1)',
    'Interpretacion — sesgo detectado?',
  ];

  const aggData = [
    AGH,
    sep('=== GRUPO A — METRICAS WIKIPEDIA ==='),
    mrow('A','word_count',         'Num. palabras',
      aWordsW, aWordsH, ()=>cntLT(aWordsW,aWordsH), N,
      'SESGO si W<H: articulo femenino mas corto. Indica menor cobertura editorial de la investigadora.'),
    mrow('A','num_references',     'Num. referencias',
      aRefsW,  aRefsH,  ()=>cntLT(aRefsW,aRefsH),  N,
      'SESGO si W<H: articulo femenino menos documentado. Menos fuentes = menor legitimacion academica.'),
    mrow('A','num_categories',     'Num. categorias',
      aCatsW,  aCatsH,  ()=>cntLT(aCatsW,aCatsH),  N,
      'SESGO si W<H: articulo femenino menos categorizado. Menor integracion en red tematica Wikipedia.'),
    mrow('A','num_images',         'Num. imagenes',
      aImgsW,  aImgsH,  ()=>cntLT(aImgsW,aImgsH),  N,
      'SESGO si W<H: articulo femenino con menos imagenes. Menor cobertura visual.'),
    mrow('A','num_internal_links', 'Num. enlaces internos',
      aLinksW, aLinksH, ()=>cntLT(aLinksW,aLinksH), N,
      'SESGO si W<H: articulo femenino menos conectado dentro de Wikipedia.'),
    mrow('A','num_edits',          'Num. ediciones',
      aEditsW, aEditsH, ()=>cntLT(aEditsW,aEditsH), N,
      'SESGO si W<H: articulo femenino menos editado (menos atencion editorial acumulada).'),
    mrow('A','page_length',        'Longitud pagina (bytes)',
      aLenW,   aLenH,   ()=>cntLT(aLenW,aLenH),   N,
      'SESGO si W<H: articulo femenino mas corto en bytes (incluye codigo wiki, plantillas, refs).'),
    [
      'A','creation_date','Fecha creacion (ano)',
      avgArr(aYearW.map(v=>v==null?'':v)), avgArr(aYearH.map(v=>v==null?'':v)),
      di(avgArr(aYearW.map(v=>v==null?'':v)), avgArr(aYearH.map(v=>v==null?'':v))),
      medArr(aYearW.map(v=>v==null?'':v)), medArr(aYearH.map(v=>v==null?'':v)),
      `${cntRecent()}/${N}`, idx(cntRecent(), N),
      'SESGO si ano_W > ano_H: articulo femenino creado mas tarde. Menos tiempo para desarrollarse.',
    ],
    subt('A','SUBTOTAL GR. A — Indice sesgo Wikipedia', grA_bias, grA_max,
      `${grA_bias} senales de sesgo sobre ${grA_max} posibles (8 metricas x ${N} pares). Indice=[0,1]. >0.5 = sesgo generalizado.`),

    sep('=== GRUPO B — METRICAS NLP ==='),
    mrow('B','domesticity_index',     'Indice domesticidad (x1000)',
      bDomW, bDomH, ()=>cntGT(bDomW,bDomH), N,
      'SESGO si W>H: texto femenino contiene mas terminos domesticos (familia, cuidados, hogar).'),
    mrow('B','epistemic_density',     'Densidad epistemica',
      bEpiW, bEpiH, ()=>cntLT(bEpiW,bEpiH), N,
      'SESGO si W<H: texto femenino con menos adjetivos de capacidad intelectual vs personalidad.'),
    mrow('B','agency_ratio',          'Ratio de agencia',
      bAgW,  bAgH,  ()=>cntLT(bAgW,bAgH),   N,
      'SESGO si W<H: texto femenino mas pasivo (verbos pasivos, menos agencia narrativa).'),
    mrow('B','scientific_links_ratio','Centralidad cientifica',
      bSciW, bSciH, ()=>cntLT(bSciW,bSciH), N,
      'SESGO si W<H: articulo femenino menos anclado en red cientifica de Wikipedia.'),
    subt('B','SUBTOTAL GR. B — Indice sesgo NLP', grB_bias, grB_max,
      `${grB_bias} senales de sesgo sobre ${grB_max} posibles (4 metricas x ${N} pares). Indice=[0,1]. >0.5 = sesgo sistematico en texto.`),

    sep('=== GRUPO C — LLM-AS-A-JUDGE ==='),
    mrow('C','bias_score_wiki_woman','Sesgo percibido W Wikipedia [0-10]',
      cBwW, cBwH, ()=>cntGT5(cBwW), NL,
      `SESGO si >5 (${cntGT5(cBwW)}/${NL} pares). LLM evalua sesgo en texto Wikipedia de la investigadora.`),
    mrow('C','bias_score_wiki_man',  'Sesgo percibido H Wikipedia [0-10]',
      cBwH, cBwW, ()=>cntGT(cBwW,cBwH), NL,
      `SESGO si W>H (${cntGT(cBwW,cBwH)}/${NL} pares): LLM detecta mayor sesgo en texto femenino que masculino.`),
    mrow('C','bias_score_ai_woman',  'Sesgo percibido W IA [0-10]',
      cBaW, cBaH, ()=>cntGT5(cBaW), NL,
      `SESGO si >5 o >score_wiki_W (${cntGT5(cBaW)}/${NL} pares). Si Media_W > Media W Wikipedia: IA amplifica sesgo.`),
    mrow('C','bias_score_ai_man',    'Sesgo percibido H IA [0-10]',
      cBaH, cBaW, ()=>cntGT(cBaW,cBaH), NL,
      `SESGO si W>H (${cntGT(cBaW,cBaH)}/${NL} pares): sesgo asimetrico en biografias IA.`),
    mrow('C','narrative_balance_wiki','Balance narrativo Wikipedia [0-1]',
      cNbW, cNbW, ()=>cntGT2(cNbW), NL,
      `SESGO si >0.2 (${cntGT2(cNbW)}/${NL} pares): foco asimetrico entre texto W y H en Wikipedia.`),
    mrow('C','narrative_balance_ai', 'Balance narrativo IA [0-1]',
      cNbA, cNbW, ()=>cntGT(cNbA,cNbW), NL,
      `SESGO si IA>Wiki (${cntGT(cNbA,cNbW)}/${NL} pares): IA amplifica asimetria de foco narrativo.`),
    mrow('C','ratio_individual_A',   'Logros individuales W (%)',
      cRiW.map(v=>v==null?null:v*100), cRiH.map(v=>v==null?null:v*100),
      ()=>cntLT(cRiW,cRiH), NL,
      `SESGO si W<H (${cntLT(cRiW,cRiH)}/${NL} pares): logros femeninos atribuidos mas colectivamente.`),
    brow('C','roles_cuidado_presentes',      'Roles cuidado W',     cRcW, cRcH, NL,
      `SESGO si W=Si y H=No (${cntTru(cRcW)}/${NL} pares). Mencion a responsabilidades domesticas/cuidados en texto femenino.`),
    brow('C','sindrome_impostor_presente',   'Sindrome impostor W', cSiW, cSiH, NL,
      `SESGO si W=Si y H=No (${cntTru(cSiW)}/${NL} pares). Logros femeninos atribuidos a suerte o esfuerzo ajeno, no al talento.`),
    subt('C','SUBTOTAL GR. C — Indice sesgo LLM', grC_bias, grC_max,
      `${grC_bias} senales de sesgo sobre ${grC_max} posibles (9 metricas x ${NL} pares con LLM). Indice=[0,1]. >0.5 = LLM confirma sesgo sistematico.`),

    sep('=== CORRELACION GLOBAL DE SESGO ==='),
    ['GLOBAL','—','Indice sesgo Gr. A (Wikipedia estructural)',
      '','','','','','', idx(grA_bias, grA_max),
      'Sesgos en metadatos y estructura de articulos Wikipedia (longitud, refs, categorias, imagenes, links, ediciones, fecha creacion).'],
    ['GLOBAL','—','Indice sesgo Gr. B (NLP textual)',
      '','','','','','', idx(grB_bias, grB_max),
      'Sesgos en el contenido textual del articulo (domesticidad, densidad epistemica, agencia, centralidad cientifica).'],
    ['GLOBAL','—','Indice sesgo Gr. C (LLM juez externo)',
      '','','','','','', idx(grC_bias, grC_max),
      'Sesgos detectados por LLM sobre textos Wikipedia y biografias generadas por IA (9 dimensiones).'],
    ['GLOBAL','—','=== INDICE GLOBAL DE SESGO (media 3 grupos) ===',
      '','','','','','',
      +globalIdx.toFixed(4),
      `(A=${idx(grA_bias,grA_max)} + B=${idx(grB_bias,grB_max)} + C=${idx(grC_bias,grC_max)}) / 3. Interpretacion: <0.25 sesgo leve | 0.25-0.5 moderado | >0.5 elevado.`],
  ];

  const aggWS = XLSX.utils.aoa_to_sheet(aggData);
  aggWS['!cols'] = [5,26,34,12,12,12,12,12,14,14,80].map(wch => ({ wch }));
  XLSX.utils.book_append_sheet(wb, aggWS, 'Resumen agregado');

  // ── Download ───────────────────────────────────────────────────────────────
  const now = new Date();
  const ts  = `${now.getFullYear()}${String(now.getMonth()+1).padStart(2,'0')}${String(now.getDate()).padStart(2,'0')}`;
  XLSX.writeFile(wb, `gender_bias_analyzer_${ts}.xlsx`);
}

// ── Pairs ──────────────────────────────────────────────────────────────────────
function renderPairs() {


  // ── Sheet 1: Detalle por par (todas las métricas) ──────────────────────────
  const detailHeaders = [
    'Par ID', 'Mujer', 'Hombre', 'Área', 'País',
    // Wikipedia ♀
    'W_Palabras', 'W_Referencias', 'W_CategorÍas', 'W_ImÁgenes',
    'W_Links_Int', 'W_EdicionEs', 'W_Longitud', 'W_FechaCreacion', 'W_URL',
    // Wikipedia ♂
    'H_Palabras', 'H_Referencias', 'H_CategorÍas', 'H_ImÁgenes',
    'H_Links_Int', 'H_EdicionEs', 'H_Longitud', 'H_FechaCreacion', 'H_URL',
    // Delta Wikipedia
    'Δ_Palabras', 'Δ_Referencias', 'Δ_CategorÍas', 'Δ_ImÁgenes', 'Δ_Links_Int',
    // NLP ♀
    'W_Domesticidad', 'W_D_Epistémica', 'W_Agencia', 'W_Links_Cient',
    // NLP ♂
    'H_Domesticidad', 'H_D_Epistémica', 'H_Agencia', 'H_Links_Cient',
    // Delta NLP
    'Δ_Domesticidad', 'Δ_D_Epistémica', 'Δ_Agencia', 'Δ_Links_Cient',
    // LLM
    'LLM_Sesgo_W', 'LLM_Sesgo_H', 'Δ_Sesgo_LLM',
    'LLM_RolesCuidado_W', 'LLM_Impostor_W', 'LLM_Atrib_Indiv_W',
    'LLM_Balance_Narrativo', 'LLM_Sesgo_Detectado',
    'LLM_Diagnostico'
  ];

  const detailRows = valid.map(r => {
    const ww = r.wiki_woman || {}, wm = r.wiki_man || {};
    const nw = r.nlp_woman  || {}, nm = r.nlp_man  || {};
    const a  = r.llm_audit  || {};
    const sw = a.stereotype_audit_wiki_w || a.stereotype_audit_woman || {};
    const ma = a.merit_attribution_wiki  || a.merit_attribution      || {};
    const bw = a.bias_score_wiki_woman   ?? a.bias_score_woman       ?? null;
    const bm = a.bias_score_wiki_man     ?? a.bias_score_man         ?? null;
    const nb = a.narrative_balance_wiki  ?? a.narrative_balance_score ?? null;

    const n = v => (v == null ? '' : v);
    const f = (v, d=4) => (v == null ? '' : parseFloat((+v).toFixed(d)));
    const b = v => (v == null ? '' : v ? 'Sí' : 'No');

    return [
      r.pair_id, r.woman_name, r.man_name, r.area, r.country || '',
      // Wikipedia ♀
      n(ww.word_count), n(ww.num_references), n(ww.num_categories), n(ww.num_images),
      n(ww.num_internal_links), n(ww.num_edits), n(ww.page_length),
      n(ww.creation_date), n(ww.wikipedia_url),
      // Wikipedia ♂
      n(wm.word_count), n(wm.num_references), n(wm.num_categories), n(wm.num_images),
      n(wm.num_internal_links), n(wm.num_edits), n(wm.page_length),
      n(wm.creation_date), n(wm.wikipedia_url),
      // Delta Wikipedia
      n(ww.word_count) - n(wm.word_count),
      n(ww.num_references) - n(wm.num_references),
      n(ww.num_categories) - n(wm.num_categories),
      n(ww.num_images)     - n(wm.num_images),
      n(ww.num_internal_links) - n(wm.num_internal_links),
      // NLP ♀
      f(nw.domesticity_index), f(nw.epistemic_density), f(nw.agency_ratio), f(nw.scientific_links_ratio),
      // NLP ♂
      f(nm.domesticity_index), f(nm.epistemic_density), f(nm.agency_ratio), f(nm.scientific_links_ratio),
      // Delta NLP
      f((nw.domesticity_index||0) - (nm.domesticity_index||0)),
      f((nw.epistemic_density||0) - (nm.epistemic_density||0)),
      f((nw.agency_ratio||0) - (nm.agency_ratio||0)),
      f((nw.scientific_links_ratio||0) - (nm.scientific_links_ratio||0)),
      // LLM
      bw, bm, (bw != null && bm != null) ? f(bw - bm) : '',
      b(sw.roles_cuidado_presentes), b(sw.sindrome_impostor_presente),
      f((ma.ratio_individual_A||0) * 100, 1),
      nb != null ? f(nb) : '',
      b(ma.sesgo_detectado),
      n(a.diagnostic_paragraph || '').replace(/\n/g, ' ').substring(0, 500),
    ];
  });

  const detailWS = XLSX.utils.aoa_to_sheet([detailHeaders, ...detailRows]);
  // Column widths
  detailWS['!cols'] = detailHeaders.map((h, i) => ({
    wch: i === detailHeaders.length - 1 ? 60 : i < 5 ? 22 : 14
  }));
  XLSX.utils.book_append_sheet(wb, detailWS, 'Detalle por par');

  // ── Sheet 2: Resumen agregado ──────────────────────────────────────────────
  const w  = summary.wikipedia || {};
  const sn = summary.nlp       || {};
  const sl = summary.llm       || {};
  const aggHeaders = ['Métrica', 'Mujeres (avg)', 'Hombres (avg)', 'Delta (♀−♂)', 'Interpretación'];
  const aggRows = [
    ['Palabras Wikipedia',    w.avg_word_count_women,         w.avg_word_count_men,          null, ''],
    ['Referencias Wikipedia', w.avg_references_women,         w.avg_references_men,          null, ''],
    ['Categorías Wikipedia',  w.avg_categories_women,         w.avg_categories_men,          null, ''],
    ['Links internos',        w.avg_links_women,              w.avg_links_men,               null, ''],
    ['Índice domesticidad',   sn.avg_domesticity_women,       sn.avg_domesticity_men,        null, 'Mayor = más términos domésticos'],
    ['Densidad epistémica',   sn.avg_epistemic_density_women, sn.avg_epistemic_density_men,  null, 'Mayor = más adjetivos epistémicos'],
    ['Ratio agencia',         sn.avg_agency_ratio_women,      sn.avg_agency_ratio_men,       null, 'Mayor = más voz activa'],
    ['Links científicos',     sn.avg_sci_links_women,         sn.avg_sci_links_men,          null, ''],
    ['Sesgo LLM (0–10)',      sl.avg_bias_score_women,        sl.avg_bias_score_men,         null, '0=sin sesgo, 10=sesgo extremo'],
  ].map(([m, wv, mv, , interp]) => {
    const wf = wv != null ? +parseFloat(wv).toFixed(4) : '';
    const mf = mv != null ? +parseFloat(mv).toFixed(4) : '';
    const d  = (wf !== '' && mf !== '') ? +(wf - mf).toFixed(4) : '';
    return [m, wf, mf, d, interp];
  });
  const aggWS = XLSX.utils.aoa_to_sheet([aggHeaders, ...aggRows]);
  aggWS['!cols'] = [{ wch: 28 }, { wch: 16 }, { wch: 16 }, { wch: 14 }, { wch: 35 }];
  XLSX.utils.book_append_sheet(wb, aggWS, 'Resumen agregado');

  // ── Sheet 3: Métricas Wikipedia por par ────────────────────────────────────
  const wikiHeaders = [
    'Par', 'Mujer', 'Hombre',
    'Palabras ♀', 'Palabras ♂', 'Δ Palabras',
    'Refs ♀', 'Refs ♂', 'Δ Refs',
    'Categ ♀', 'Categ ♂', 'Δ Categ',
    'Imgs ♀', 'Imgs ♂',
    'Links ♀', 'Links ♂',
    'Ediciones ♀', 'Ediciones ♂',
    'Longitud ♀', 'Longitud ♂',
  ];
  const wikiRows = valid.map(r => {
    const ww = r.wiki_woman || {}, wm = r.wiki_man || {};
    return [
      r.pair_id, r.woman_name, r.man_name,
      ww.word_count||0, wm.word_count||0, (ww.word_count||0)-(wm.word_count||0),
      ww.num_references||0, wm.num_references||0, (ww.num_references||0)-(wm.num_references||0),
      ww.num_categories||0, wm.num_categories||0, (ww.num_categories||0)-(wm.num_categories||0),
      ww.num_images||0, wm.num_images||0,
      ww.num_internal_links||0, wm.num_internal_links||0,
      ww.num_edits||0, wm.num_edits||0,
      ww.page_length||0, wm.page_length||0,
    ];
  });
  const wikiWS = XLSX.utils.aoa_to_sheet([wikiHeaders, ...wikiRows]);
  wikiWS['!cols'] = wikiHeaders.map(() => ({ wch: 13 }));
  wikiWS['!cols'][1] = { wch: 24 }; wikiWS['!cols'][2] = { wch: 24 };
  XLSX.utils.book_append_sheet(wb, wikiWS, 'Wikipedia por par');

  // ── Sheet 4: Métricas NLP por par ─────────────────────────────────────────
  const nlpHeaders = [
    'Par', 'Mujer', 'Hombre',
    'Domestic ♀', 'Domestic ♂', 'Δ Domestic',
    'Epist ♀', 'Epist ♂', 'Δ Epist',
    'Agencia ♀', 'Agencia ♂', 'Δ Agencia',
    'Sci-Links ♀', 'Sci-Links ♂', 'Δ Sci-Links',
    'Palabras dom ♀', 'Palabras dom ♂',
  ];
  const nlpRows = valid.map(r => {
    const nw = r.nlp_woman || {}, nm = r.nlp_man || {};
    const f4 = v => v != null ? +parseFloat(v).toFixed(4) : 0;
    return [
      r.pair_id, r.woman_name, r.man_name,
      f4(nw.domesticity_index), f4(nm.domesticity_index), f4((nw.domesticity_index||0)-(nm.domesticity_index||0)),
      f4(nw.epistemic_density), f4(nm.epistemic_density), f4((nw.epistemic_density||0)-(nm.epistemic_density||0)),
      f4(nw.agency_ratio),      f4(nm.agency_ratio),      f4((nw.agency_ratio||0)-(nm.agency_ratio||0)),
      f4(nw.scientific_links_ratio), f4(nm.scientific_links_ratio), f4((nw.scientific_links_ratio||0)-(nm.scientific_links_ratio||0)),
      (nw.domestic_keywords_found||[]).join(', '),
      (nm.domestic_keywords_found||[]).join(', '),
    ];
  });
  const nlpWS = XLSX.utils.aoa_to_sheet([nlpHeaders, ...nlpRows]);
  nlpWS['!cols'] = nlpHeaders.map(() => ({ wch: 13 }));
  nlpWS['!cols'][1] = { wch: 24 }; nlpWS['!cols'][2] = { wch: 24 };
  nlpWS['!cols'][15] = { wch: 30 }; nlpWS['!cols'][16] = { wch: 30 };
  XLSX.utils.book_append_sheet(wb, nlpWS, 'NLP por par');

  // ── Sheet 5: Auditoría LLM por par ────────────────────────────────────────
  const withLLM = valid.filter(r => r.llm_audit && !r.llm_audit.error);
  if (withLLM.length) {
    const llmHeaders = [
      'Par', 'Mujer', 'Hombre', 'Área',
      'Sesgo ♀ (0-10)', 'Sesgo ♂ (0-10)', 'Δ Sesgo',
      'Roles cuidado ♀', 'Impostor ♀', 'Roles cuidado ♂', 'Impostor ♂',
      'Atrib. indiv. ♀ (%)', 'Atrib. indiv. ♂ (%)',
      'Sesgo mérito detectado',
      'Texto más personal (blind test)',
      'Prop. personal ♀ (%)', 'Prop. personal ♂ (%)',
      'Balance narrativo',
      'Recomendaciones ♀',
      'Diagnóstico integrado',
    ];
    const llmRows = withLLM.map(r => {
      const a  = r.llm_audit;
      const sw = a.stereotype_audit_wiki_w || a.stereotype_audit_woman || {};
      const sm = a.stereotype_audit_wiki_m || a.stereotype_audit_man   || {};
      const ma = a.merit_attribution_wiki  || a.merit_attribution      || {};
      const fa = a.focus_analysis_wiki     || a.focus_analysis         || {};
      const bw = a.bias_score_wiki_woman   ?? a.bias_score_woman       ?? '';
      const bm = a.bias_score_wiki_man     ?? a.bias_score_man         ?? '';
      const nb = a.narrative_balance_wiki  ?? a.narrative_balance_score ?? '';
      const b  = v => v == null ? '' : (v ? 'Sí' : 'No');
      const pct = v => v != null ? +(parseFloat(v)*100).toFixed(1) : '';
      return [
        r.pair_id, r.woman_name, r.man_name, r.area,
        bw, bm, (bw !== '' && bm !== '') ? +(bw - bm).toFixed(2) : '',
        b(sw.roles_cuidado_presentes), b(sw.sindrome_impostor_presente),
        b(sm.roles_cuidado_presentes), b(sm.sindrome_impostor_presente),
        pct(ma.ratio_individual_A), pct(ma.ratio_individual_B),
        b(ma.sesgo_detectado),
        fa.texto_mas_personal || '',
        pct(fa.proporcion_personal_A), pct(fa.proporcion_personal_B),
        nb !== '' ? +parseFloat(nb).toFixed(4) : '',
        (sw.recomendaciones || []).join(' | ').substring(0, 300),
        (a.diagnostic_paragraph || '').replace(/\n/g, ' ').substring(0, 600),
      ];
    });
    const llmWS = XLSX.utils.aoa_to_sheet([llmHeaders, ...llmRows]);
    llmWS['!cols'] = llmHeaders.map((h, i) =>
      ({ wch: [4,22,22,20,10,10,8,14,10,14,10,14,14,16,20,14,14,14,40,60][i] || 14 })
    );
    XLSX.utils.book_append_sheet(wb, llmWS, 'LLM Auditoría');
  }

  // ── Download ───────────────────────────────────────────────────────────────
  const now = new Date();
  const ts  = `${now.getFullYear()}${String(now.getMonth()+1).padStart(2,'0')}${String(now.getDate()).padStart(2,'0')}`;
  XLSX.writeFile(wb, `gender_bias_analyzer_${ts}.xlsx`);
}

// ── Pairs ──────────────────────────────────────────────────────────────────────
function renderPairs() {
  const el  = document.getElementById('pairs-list');
  const src = results.length ? results : configPairs.map(p => ({
    pair_id: p.pair_id, woman_name: p.woman, man_name: p.man,
    area: p.area, both_in_wikipedia: null, skipped: false
  }));
  el.innerHTML = src.map(r => {
    const isPending = r.both_in_wikipedia === null;
    const wOk = r.wiki_woman?.exists_in_wikipedia;
    const mOk = r.wiki_man?.exists_in_wikipedia;
    const hasLLM = r.llm_audit && !r.llm_audit?.error;
    const badge = isPending
      ? '<span class="badge badge-pending">Pendiente</span>'
      : r.skipped
        ? '<span class="badge badge-skip">Omitido</span>'
        : hasLLM
          ? '<span class="badge badge-llm">LLM+NLP+Wiki</span>'
          : r.nlp_woman
            ? '<span class="badge badge-ok">NLP+Wiki</span>'
            : '<span class="badge badge-ok">Wiki</span>';

    let detail = '';
    if (!isPending && !r.skipped && r.wiki_woman) {
      detail = `<div class="pair-details" id="pd-${r.pair_id}">
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
          <button class="btn btn-compare" onclick="openModal(${r.pair_id})">📄 Comparar 4 textos</button>
        </div>
        <div class="grid2" style="gap:12px">
          <div>
            <div class="w-name" style="margin-bottom:8px">♀ ${r.woman_name}</div>
            <div class="mrow"><span>Palabras</span><strong>${r.wiki_woman?.word_count||'—'}</strong></div>
            <div class="mrow"><span>Referencias</span><strong>${r.wiki_woman?.num_references||'—'}</strong></div>
            <div class="mrow"><span>Categorías</span><strong>${r.wiki_woman?.num_categories||'—'}</strong></div>
            <div class="mrow"><span>Domest. Index</span><strong>${(r.nlp_woman?.domesticity_index||0).toFixed(3)}</strong></div>
            <div class="mrow"><span>D. Epistémica</span><strong>${(r.nlp_woman?.epistemic_density||0).toFixed(3)}</strong></div>
            <div class="mrow"><span>Ratio Agencia</span><strong>${(r.nlp_woman?.agency_ratio||0).toFixed(2)}</strong></div>
            ${r.wiki_woman?.wikipedia_url
              ? `<a href="${r.wiki_woman.wikipedia_url}" target="_blank" style="color:var(--woman);font-size:.77rem;margin-top:6px;display:block">→ Wikipedia (${r.wiki_woman.wikipedia_title||''})</a>` : ''}
            ${(r.nlp_woman?.explanation_domesticity && r.nlp_woman.domesticity_index===0)
              ? `<div style="font-size:.72rem;color:var(--warn);margin-top:4px">ⓘ ${r.nlp_woman.explanation_domesticity}</div>` : ''}
            ${(r.nlp_woman?.explanation_epistemic && r.nlp_woman.epistemic_density===0)
              ? `<div style="font-size:.72rem;color:var(--warn);margin-top:2px">ⓘ ${r.nlp_woman.explanation_epistemic}</div>` : ''}
            ${(r.nlp_woman?.explanation_agency && r.nlp_woman.agency_ratio===0)
              ? `<div style="font-size:.72rem;color:var(--warn);margin-top:2px">ⓘ ${r.nlp_woman.explanation_agency}</div>` : ''}
          </div>
          <div>
            <div class="m-name" style="margin-bottom:8px">♂ ${r.man_name}</div>
            <div class="mrow"><span>Palabras</span><strong>${r.wiki_man?.word_count||'—'}</strong></div>
            <div class="mrow"><span>Referencias</span><strong>${r.wiki_man?.num_references||'—'}</strong></div>
            <div class="mrow"><span>Categorías</span><strong>${r.wiki_man?.num_categories||'—'}</strong></div>
            <div class="mrow"><span>Domest. Index</span><strong>${(r.nlp_man?.domesticity_index||0).toFixed(3)}</strong></div>
            <div class="mrow"><span>D. Epistémica</span><strong>${(r.nlp_man?.epistemic_density||0).toFixed(3)}</strong></div>
            <div class="mrow"><span>Ratio Agencia</span><strong>${(r.nlp_man?.agency_ratio||0).toFixed(2)}</strong></div>
            ${r.wiki_man?.wikipedia_url
              ? `<a href="${r.wiki_man.wikipedia_url}" target="_blank" style="color:var(--man);font-size:.77rem;margin-top:6px;display:block">→ Wikipedia (${r.wiki_man.wikipedia_title||''})</a>` : ''}
          </div>
        </div>
        ${r.wiki_woman?.disambiguation_note
          ? `<div style="font-size:.75rem;color:var(--muted);margin-top:8px">ℹ ♀: ${r.wiki_woman.disambiguation_note}</div>` : ''}
        ${r.wiki_man?.disambiguation_note
          ? `<div style="font-size:.75rem;color:var(--muted)">ℹ ♂: ${r.wiki_man.disambiguation_note}</div>` : ''}
        ${hasLLM && r.llm_audit.diagnostic_paragraph
          ? `<div style="margin-top:12px"><div class="card-title" style="margin-bottom:4px">📋 Diagnóstico</div>
             <div class="diag-box">${r.llm_audit.diagnostic_paragraph}</div></div>` : ''}
      </div>`;
    } else if (!isPending && r.skipped) {
      detail = `<div class="pair-details" id="pd-${r.pair_id}">
        <div class="alert alert-warn" style="margin-top:10px">
          ${r.skip_reason || 'Uno o ambos miembros sin entrada en Wikipedia ES'}
          ${!wOk ? `<div>❌ ${r.woman_name}: ${r.wiki_woman?.error||'no encontrada'}</div>` : ''}
          ${!mOk ? `<div>❌ ${r.man_name}: ${r.wiki_man?.error||'no encontrado'}</div>` : ''}
        </div>
      </div>`;
    }

    return `<div class="pair-card">
      <div class="pair-header" onclick="togglePair(${r.pair_id})">
        <span style="min-width:26px;color:var(--muted);font-size:.8rem">#${r.pair_id}</span>
        <div style="flex:1;min-width:0">
          <div class="w-name">${isPending?'':wOk?'✅':'❌'} ${r.woman_name||r.woman}</div>
          <div class="m-name">${isPending?'':mOk?'✅':'❌'} ${r.man_name||r.man}</div>
          <div class="area-lbl">${r.area}</div>
        </div>
        ${badge}
        ${(!isPending && !r.skipped && r.wiki_woman)
          ? `<button class="btn btn-compare" style="flex-shrink:0"
               onclick="event.stopPropagation();openModal(${r.pair_id})">📄</button>` : ''}
        <span class="chevron" id="chev-${r.pair_id}">▾</span>
      </div>
      ${detail}
    </div>`;
  }).join('');
}

function togglePair(id) {
  const el = document.getElementById('pd-'+id);
  const ch = document.getElementById('chev-'+id);
  if (el) el.classList.toggle('open');
  if (ch) ch.classList.toggle('open');
}

// ── Config ─────────────────────────────────────────────────────────────────────
function renderConfig() {
  const el = document.getElementById('config-list');
  if (!configPairs.length) {
    el.innerHTML = '<p style="color:var(--muted)">No se pudo cargar pairs.json</p>';
    return;
  }
  el.innerHTML = `<p style="color:var(--muted);margin-bottom:10px;font-size:.8rem">${configPairs.length} pares · config/pairs.json</p>` +
    configPairs.map(p => `<div style="display:flex;gap:8px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.04);font-size:.8rem;align-items:center">
      <span style="color:var(--muted);min-width:24px">#${p.pair_id}</span>
      <span class="w-name" style="min-width:170px;font-size:.79rem">${p.woman}</span>
      <span class="m-name" style="min-width:170px;font-size:.79rem">${p.man}</span>
      <span style="color:var(--muted);flex:1;font-size:.77rem">${p.area}</span>
      <span class="badge badge-pending">${p.country||''}</span>
    </div>`).join('');
}

// ══════════════════════════════════════════════════════════════════════════════
//  MODAL — Text comparison
// ══════════════════════════════════════════════════════════════════════════════
function openModal(pairId) {
  const r = results.find(x => x.pair_id === pairId);
  if (!r) return;
  currentModalPair = r;
  const a = r.llm_audit || {};

  document.getElementById('m-pair-id').textContent = pairId;
  document.getElementById('m-area').textContent    = r.area || '';
  document.getElementById('m-wname-wiki').textContent = r.woman_name;
  document.getElementById('m-mname-wiki').textContent = r.man_name;
  document.getElementById('m-wname-ai').textContent   = r.woman_name;
  document.getElementById('m-mname-ai').textContent   = r.man_name;
  document.getElementById('m-wmeta').textContent = `${(r.wiki_woman?.word_count||0).toLocaleString('es')} palabras`;
  document.getElementById('m-mmeta').textContent = `${(r.wiki_man?.word_count||0).toLocaleString('es')} palabras`;

  setPanel('m-wtext', r.wiki_woman?.raw_text || r.wiki_woman?.summary || '⚠ Texto no disponible');
  setPanel('m-mtext', r.wiki_man?.raw_text   || r.wiki_man?.summary   || '⚠ Texto no disponible');

  const hasAI = a.generated_bio_woman || a.generated_bio_man;
  document.getElementById('no-ai-notice').style.display = hasAI ? 'none' : 'block';
  setPanel('m-wtext-ai', a.generated_bio_woman || '⚠ Ejecuta el análisis LLM para generar.');
  setPanel('m-mtext-ai', a.generated_bio_man   || '⚠ Ejecuta el análisis LLM para generar.');

  renderModalStats(r);
  renderModalDiag(r);
  switchModalTab('texts', document.querySelector('.modal-tab'));
  document.getElementById('modal-overlay').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function setPanel(id, text) {
  const el = document.getElementById(id);
  el.dataset.rawText = text;
  el.textContent = text;
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
  document.body.style.overflow = '';
  currentModalPair = null;
  document.getElementById('search-term').value = '';
}

function closeModalOnOverlay(e) {
  if (e.target === document.getElementById('modal-overlay')) closeModal();
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

function switchModalTab(name, btn) {
  ['texts','stats','diag'].forEach(t => {
    document.getElementById('mtab-'+t).style.display = t===name ? 'block' : 'none';
  });
  document.querySelectorAll('.modal-tab').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
}

function highlightSearch() {
  const term = document.getElementById('search-term').value.trim().toLowerCase();
  ['m-wtext','m-mtext','m-wtext-ai','m-mtext-ai'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    const raw = el.dataset.rawText || '';
    if (!term) { el.textContent = raw; return; }
    const esc   = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`(${esc})`, 'gi');
    el.innerHTML = raw.replace(regex, '<mark>$1</mark>');
  });
}

function clearSearch() {
  document.getElementById('search-term').value = '';
  highlightSearch();
}

function renderModalStats(r) {
  const ww = r.wiki_woman || {}, wm = r.wiki_man || {};
  const nw = r.nlp_woman  || {}, nm = r.nlp_man  || {};
  const a  = r.llm_audit  || {};
  const rows = [
    { lbl:'Palabras',      w:ww.word_count||0,    m:wm.word_count||0 },
    { lbl:'Referencias',   w:ww.num_references||0, m:wm.num_references||0 },
    { lbl:'Categorías',    w:ww.num_categories||0, m:wm.num_categories||0 },
    { lbl:'Imágenes',      w:ww.num_images||0,     m:wm.num_images||0 },
  ];
  document.getElementById('m-stats-strip').innerHTML = rows.map(s => {
    const d = s.w - s.m;
    const col = d > 0 ? 'var(--woman)' : d < 0 ? 'var(--man)' : 'var(--muted)';
    return `<div class="stat-cell">
      <div class="stat-lbl">${s.lbl}</div>
      <div style="display:flex;justify-content:center;gap:16px;margin-top:4px">
        <div style="text-align:center"><div class="stat-val" style="color:var(--woman)">${s.w}</div><div style="font-size:.65rem;color:var(--woman)">♀</div></div>
        <div style="text-align:center"><div class="stat-val" style="color:var(--man)">${s.m}</div><div style="font-size:.65rem;color:var(--man)">♂</div></div>
      </div>
      <div style="font-size:.7rem;font-weight:600;color:${col};margin-top:4px">${d>0?'+':''}${d}</div>
    </div>`;
  }).join('');

  const nlpRows = [
    { lbl:'Domesticidad',  w:nw.domesticity_index||0,    m:nm.domesticity_index||0 },
    { lbl:'D. Epistémica', w:nw.epistemic_density||0,    m:nm.epistemic_density||0 },
    { lbl:'Ratio Agencia', w:nw.agency_ratio||0,         m:nm.agency_ratio||0 },
    { lbl:'Links Cient.',  w:nw.scientific_links_ratio||0,m:nm.scientific_links_ratio||0 },
    { lbl:'Sesgo LLM',     w:(a.bias_score_wiki_woman??a.bias_score_woman??0), m:(a.bias_score_wiki_man??a.bias_score_man??0) },
  ];
  document.getElementById('m-stats-nlp').innerHTML = nlpRows.map(row => {
    const maxV = Math.max(row.w, row.m, 0.001);
    const wp   = Math.round((row.w/maxV)*100);
    const mp   = Math.round((row.m/maxV)*100);
    const d    = row.w - row.m;
    const col  = d > 0 ? 'var(--woman)' : d < 0 ? 'var(--man)' : 'var(--muted)';
    return `<div class="card" style="padding:12px">
      <strong style="font-size:.82rem">${row.lbl}</strong>
      <div class="bar-compare" style="margin:8px 0 4px">
        <div class="blabel" style="width:60px">♀ ${row.w.toFixed(3)}</div>
        <div class="bars-col"><div class="bar-fill bar-w" style="width:${wp}%"></div></div>
      </div>
      <div class="bar-compare">
        <div class="blabel" style="width:60px">♂ ${row.m.toFixed(3)}</div>
        <div class="bars-col"><div class="bar-fill bar-m" style="width:${mp}%"></div></div>
      </div>
      <div style="font-size:.72rem;color:${col};margin-top:6px">Δ ${d>0?'+':''}${d.toFixed(4)}</div>
    </div>`;
  }).join('');
}

function renderModalDiag(r) {
  const a  = r.llm_audit || {};
  const el = document.getElementById('m-diag-content');
  if (!a.diagnostic_paragraph && !a.focus_analysis) {
    el.innerHTML = '<div class="alert alert-warn">Sin datos LLM. Ejecuta el análisis completo.</div>';
    return;
  }
  const sw = a.stereotype_audit_wiki_w || a.stereotype_audit_woman || {};
  const sm = a.stereotype_audit_wiki_m || a.stereotype_audit_man   || {};
  const fa = a.focus_analysis_wiki || a.focus_analysis || {};
  const ma = a.merit_attribution_wiki || a.merit_attribution || {};
  el.innerHTML = `
    ${a.diagnostic_paragraph ? `
      <div class="card-title" style="margin-bottom:6px">📋 Diagnóstico integrado</div>
      <div class="diag-box" style="margin-bottom:16px">${a.diagnostic_paragraph}</div>` : ''}
    <div class="grid2" style="gap:12px;margin-bottom:14px">
      <div class="card" style="padding:14px">
        <div class="card-title" style="margin-bottom:8px">Blind test de foco</div>
        <div class="mrow"><span>Texto más personal</span><strong>Texto ${fa.texto_mas_personal||'—'}</strong></div>
        <div class="mrow"><span>Proporción personal ♀</span><strong>${((fa.proporcion_personal_A||0)*100).toFixed(0)}%</strong></div>
        <div class="mrow"><span>Proporción personal ♂</span><strong>${((fa.proporcion_personal_B||0)*100).toFixed(0)}%</strong></div>
        ${fa.observaciones ? `<p style="font-size:.78rem;color:var(--muted);margin-top:8px">${fa.observaciones}</p>` : ''}
      </div>
      <div class="card" style="padding:14px">
        <div class="card-title" style="margin-bottom:8px">Atribución de mérito</div>
        <div class="mrow"><span>Ratio individual ♀</span><strong>${((ma.ratio_individual_A||0)*100).toFixed(0)}%</strong></div>
        <div class="mrow"><span>Ratio individual ♂</span><strong>${((ma.ratio_individual_B||0)*100).toFixed(0)}%</strong></div>
        <div class="mrow"><span>Sesgo detectado</span><strong>${ma.sesgo_detectado?'⚠️ Sí':'✓ No'}</strong></div>
      </div>
    </div>
    <div class="grid2" style="gap:12px">
      <div class="card" style="padding:14px">
        <div class="card-title" style="margin-bottom:8px">Estereotipos ♀</div>
        <div class="mrow"><span>Sesgo</span><span class="bias-score ${(sw.puntuacion_sesgo_percibido||0)>6?'score-high':(sw.puntuacion_sesgo_percibido||0)>3?'score-mid':'score-low'}">${sw.puntuacion_sesgo_percibido||0}/10</span></div>
        <div class="mrow"><span>Roles cuidado</span><strong>${sw.roles_cuidado_presentes?'⚠️':'✓'}</strong></div>
        <div class="mrow"><span>Impostor</span><strong>${sw.sindrome_impostor_presente?'⚠️':'✓'}</strong></div>
        ${(sw.recomendaciones||[]).length ? `<div style="margin-top:8px">${sw.recomendaciones.map(rec=>`<div style="font-size:.76rem;color:var(--muted)">→ ${rec}</div>`).join('')}</div>` : ''}
      </div>
      <div class="card" style="padding:14px">
        <div class="card-title" style="margin-bottom:8px">Estereotipos ♂</div>
        <div class="mrow"><span>Sesgo</span><span class="bias-score ${(sm.puntuacion_sesgo_percibido||0)>6?'score-high':(sm.puntuacion_sesgo_percibido||0)>3?'score-mid':'score-low'}">${sm.puntuacion_sesgo_percibido||0}/10</span></div>
        <div class="mrow"><span>Roles cuidado</span><strong>${sm.roles_cuidado_presentes?'⚠️':'✓'}</strong></div>
        <div class="mrow"><span>Impostor</span><strong>${sm.sindrome_impostor_presente?'⚠️':'✓'}</strong></div>
      </div>
    </div>`;
}

// ── Chart helpers ──────────────────────────────────────────────────────────────
function destroyChart(id) {
  if (charts[id]) { charts[id].destroy(); delete charts[id]; }
}
const cOpts = () => ({
  responsive: true, maintainAspectRatio: false,
  scales: {
    x: { ticks:{color:'#7777aa',font:{size:10}}, grid:{color:'rgba(255,255,255,.04)'} },
    y: { ticks:{color:'#7777aa',font:{size:10}}, grid:{color:'rgba(255,255,255,.04)'}, beginAtZero:true }
  },
  plugins: { legend:{labels:{color:'#e4e4ff',font:{size:11}}} }
});
function mkBarChart(id, labels, wData, mData) {
  destroyChart(id);
  const el = document.getElementById(id);
  if (!el) return;
  charts[id] = new Chart(el, {
    type:'bar', data:{labels, datasets:[
      {label:'Mujeres', data:wData, backgroundColor:'rgba(232,67,159,.72)', borderColor:'#e8439f', borderWidth:1},
      {label:'Hombres', data:mData, backgroundColor:'rgba(59,130,246,.72)',  borderColor:'#3b82f6', borderWidth:1}
    ]}, options:cOpts()
  });
}
function mkAvgBar(id, label, wVal, mVal) {
  destroyChart(id);
  const el = document.getElementById(id);
  if (!el) return;
  charts[id] = new Chart(el, {
    type:'bar', data:{
      labels:['Mujeres','Hombres'],
      datasets:[{label, data:[wVal||0,mVal||0],
        backgroundColor:['rgba(232,67,159,.72)','rgba(59,130,246,.72)'],
        borderColor:['#e8439f','#3b82f6'], borderWidth:1}]
    }, options:{...cOpts(), plugins:{legend:{display:false}}}
  });
}

// ── Init ───────────────────────────────────────────────────────────────────────
(async () => {
  await refresh();
  const st = await apiFetch('/analyze/status');
  if (st?.status === 'running') startPolling();
})();
