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

// ── Audit ──────────────────────────────────────────────────────────────────────
function renderAudit() {
  const withAudit = results.filter(r => r.llm_audit && !r.llm_audit.error && r.both_in_wikipedia);
  const el = document.getElementById('audit-list');
  if (!withAudit.length) {
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
