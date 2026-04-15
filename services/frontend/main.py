"""
Frontend Service
Serves the interactive dashboard for the Wikipedia Bias Analyzer.
"""
import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

app = FastAPI(title="Wikipedia Bias Analyzer - Dashboard", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

API_GATEWAY_URL = os.getenv("API_GATEWAY_URL", "http://localhost:8000")

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Wikipedia Bias Analyzer — Sesgos de Género en Ciencia</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {
    --primary: #6c3fc5;
    --secondary: #e84393;
    --woman: #e84393;
    --man: #3b82f6;
    --bg: #0f0f1a;
    --surface: #1a1a2e;
    --surface2: #242444;
    --border: #333366;
    --text: #e8e8ff;
    --text-muted: #9999bb;
    --success: #22c55e;
    --warning: #f59e0b;
    --danger: #ef4444;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }
  
  header {
    background: linear-gradient(135deg, var(--primary), var(--secondary));
    padding: 24px 32px; display: flex; align-items: center; gap: 16px;
    box-shadow: 0 4px 20px rgba(108,63,197,0.4);
  }
  header h1 { font-size: 1.6rem; font-weight: 700; }
  header p { font-size: 0.9rem; opacity: 0.85; margin-top: 4px; }
  .emoji-big { font-size: 2.5rem; }

  nav {
    background: var(--surface); border-bottom: 1px solid var(--border);
    display: flex; gap: 4px; padding: 0 24px; overflow-x: auto;
  }
  nav button {
    background: none; border: none; color: var(--text-muted); padding: 14px 20px;
    cursor: pointer; font-size: 0.9rem; border-bottom: 2px solid transparent;
    transition: all 0.2s; white-space: nowrap;
  }
  nav button.active, nav button:hover { color: var(--text); border-bottom-color: var(--primary); }

  .container { max-width: 1400px; margin: 0 auto; padding: 24px; }
  
  .tab-content { display: none; }
  .tab-content.active { display: block; }

  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
  .grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }

  .card {
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    padding: 20px;
  }
  .card h3 { font-size: 1rem; font-weight: 600; margin-bottom: 16px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; font-size: 0.8rem; }
  .card h2 { font-size: 1.1rem; font-weight: 600; margin-bottom: 12px; }
  
  .metric-card {
    background: var(--surface2); border: 1px solid var(--border); border-radius: 10px;
    padding: 16px; text-align: center;
  }
  .metric-value { font-size: 2rem; font-weight: 700; }
  .metric-label { font-size: 0.8rem; color: var(--text-muted); margin-top: 4px; }
  .metric-delta { font-size: 0.8rem; margin-top: 6px; }
  .delta-pos { color: var(--woman); }
  .delta-neg { color: var(--man); }

  .btn {
    padding: 10px 20px; border-radius: 8px; border: none; cursor: pointer;
    font-size: 0.9rem; font-weight: 600; transition: all 0.2s;
  }
  .btn-primary { background: var(--primary); color: white; }
  .btn-primary:hover { background: #7c4fd5; }
  .btn-secondary { background: var(--secondary); color: white; }
  .btn-outline { background: transparent; border: 1px solid var(--border); color: var(--text); }
  .btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-sm { padding: 6px 12px; font-size: 0.8rem; }

  .badge {
    display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 600;
  }
  .badge-woman { background: rgba(232,67,147,0.2); color: var(--woman); }
  .badge-man { background: rgba(59,130,246,0.2); color: var(--man); }
  .badge-success { background: rgba(34,197,94,0.2); color: var(--success); }
  .badge-warning { background: rgba(245,158,11,0.2); color: var(--warning); }
  .badge-danger { background: rgba(239,68,68,0.2); color: var(--danger); }
  .badge-skip { background: rgba(153,153,187,0.2); color: var(--text-muted); }

  .progress-bar {
    background: var(--surface2); border-radius: 8px; height: 8px; overflow: hidden;
  }
  .progress-fill {
    height: 100%; background: linear-gradient(90deg, var(--primary), var(--secondary));
    transition: width 0.5s ease; border-radius: 8px;
  }

  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th { padding: 10px 12px; text-align: left; background: var(--surface2); color: var(--text-muted); font-weight: 600; text-transform: uppercase; font-size: 0.75rem; letter-spacing: 0.05em; }
  td { padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }
  tr:hover td { background: rgba(255,255,255,0.03); }

  .status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
  .dot-ok { background: var(--success); box-shadow: 0 0 6px var(--success); }
  .dot-warn { background: var(--warning); }
  .dot-err { background: var(--danger); }

  .chart-container { position: relative; height: 280px; }
  .chart-container-lg { position: relative; height: 360px; }

  .bar-compare { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .bar-compare .label { width: 140px; font-size: 0.8rem; text-align: right; color: var(--text-muted); flex-shrink: 0; }
  .bar-compare .bars { flex: 1; display: flex; flex-direction: column; gap: 3px; }
  .bar-fill { height: 14px; border-radius: 4px; transition: width 0.6s; min-width: 2px; display: flex; align-items: center; padding-left: 6px; font-size: 0.7rem; color: white; font-weight: 600; }
  .bar-woman { background: linear-gradient(90deg, var(--woman), #f472b6); }
  .bar-man { background: linear-gradient(90deg, var(--man), #60a5fa); }

  .pair-card {
    background: var(--surface2); border: 1px solid var(--border); border-radius: 10px;
    padding: 16px; margin-bottom: 12px;
  }
  .pair-header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; cursor: pointer; }
  .pair-details { display: none; }
  .pair-details.open { display: block; }
  .pair-names { flex: 1; }
  .pair-woman { color: var(--woman); font-weight: 600; }
  .pair-man { color: var(--man); font-weight: 600; }
  .pair-area { color: var(--text-muted); font-size: 0.8rem; }

  .metric-row { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }
  .metric-row:last-child { border-bottom: none; }

  .alert { padding: 12px 16px; border-radius: 8px; margin-bottom: 16px; font-size: 0.9rem; }
  .alert-info { background: rgba(59,130,246,0.15); border: 1px solid rgba(59,130,246,0.3); }
  .alert-warning { background: rgba(245,158,11,0.15); border: 1px solid rgba(245,158,11,0.3); }
  .alert-success { background: rgba(34,197,94,0.15); border: 1px solid rgba(34,197,94,0.3); }

  .loading { text-align: center; padding: 40px; color: var(--text-muted); }
  .spinner { width: 32px; height: 32px; border: 3px solid var(--border); border-top-color: var(--primary); border-radius: 50%; animation: spin 0.8s linear infinite; margin: 0 auto 12px; }
  @keyframes spin { to { transform: rotate(360deg); } }

  .legend { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 8px; }
  .legend-item { display: flex; align-items: center; gap: 6px; font-size: 0.8rem; }
  .legend-dot { width: 10px; height: 10px; border-radius: 2px; }
  .legend-woman { background: var(--woman); }
  .legend-man { background: var(--man); }

  .section-title { font-size: 1.3rem; font-weight: 700; margin-bottom: 20px; display: flex; align-items: center; gap: 10px; }

  @media (max-width: 768px) {
    .grid-2, .grid-3, .grid-4 { grid-template-columns: 1fr; }
    header h1 { font-size: 1.2rem; }
  }
</style>
</head>
<body>

<header>
  <div class="emoji-big">🔬</div>
  <div>
    <h1>Wikipedia Bias Analyzer</h1>
    <p>Análisis comparativo de sesgos de género en biografías de científicas y científicos</p>
  </div>
</header>

<nav>
  <button class="active" onclick="showTab('dashboard')">📊 Dashboard</button>
  <button onclick="showTab('pairs')">👥 Pares Biográficos</button>
  <button onclick="showTab('metrics')">📈 Métricas Comparativas</button>
  <button onclick="showTab('nlp')">🔤 Análisis NLP</button>
  <button onclick="showTab('audit')">🤖 Auditoría LLM</button>
  <button onclick="showTab('methodology')">📖 Metodología</button>
</nav>

<!-- ── DASHBOARD ── -->
<div id="tab-dashboard" class="tab-content active">
<div class="container">
  <div class="section-title">📊 Panel de Control</div>

  <div id="status-panel" class="card" style="margin-bottom:20px">
    <h3>Estado del Análisis</h3>
    <div id="status-content">
      <div class="loading"><div class="spinner"></div>Cargando estado...</div>
    </div>
  </div>

  <div style="display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap">
    <button class="btn btn-primary" onclick="startAnalysis(false)">▶ Iniciar Análisis Wikipedia + NLP</button>
    <button class="btn btn-secondary" onclick="startAnalysis(true)">🤖 Análisis Completo (incl. LLM)</button>
    <button class="btn btn-outline" onclick="refreshData()">🔄 Actualizar</button>
    <button class="btn btn-outline" id="btn-clear" onclick="clearResults()">🗑 Limpiar resultados</button>
    <label style="display:flex;align-items:center;gap:8px;font-size:0.85rem;color:var(--text-muted)">
      API Key:
      <input type="password" id="api-key-input" placeholder="sk-ant-..." style="background:var(--surface2);border:1px solid var(--border);color:var(--text);padding:6px 10px;border-radius:6px;font-size:0.85rem;width:200px">
    </label>
  </div>

  <div class="grid-4" id="summary-cards">
    <div class="metric-card"><div class="metric-value" id="m-total">—</div><div class="metric-label">Total Pares</div></div>
    <div class="metric-card"><div class="metric-value" style="color:var(--success)" id="m-valid">—</div><div class="metric-label">Pares Válidos (ambos en Wikipedia)</div></div>
    <div class="metric-card"><div class="metric-value" style="color:var(--warning)" id="m-skipped">—</div><div class="metric-label">Pares Omitidos</div></div>
    <div class="metric-card"><div class="metric-value" style="color:var(--primary)" id="m-coverage">—%</div><div class="metric-label">Cobertura Wikipedia ES</div></div>
  </div>

  <div class="grid-2" style="margin-top:20px">
    <div class="card">
      <h3>Longitud media artículo (palabras)</h3>
      <div class="legend"><span class="legend-item"><span class="legend-dot legend-woman"></span>Mujeres</span><span class="legend-item"><span class="legend-dot legend-man"></span>Hombres</span></div>
      <div class="chart-container"><canvas id="chart-wordcount"></canvas></div>
    </div>
    <div class="card">
      <h3>Métricas Wikipedia comparativas</h3>
      <div id="bar-wiki-metrics"></div>
    </div>
  </div>
</div>
</div>

<!-- ── PAIRS ── -->
<div id="tab-pairs" class="tab-content">
<div class="container">
  <div class="section-title">👥 Pares Biográficos</div>
  <div class="alert alert-info">Los pares donde algún miembro no tiene entrada en Wikipedia en castellano son excluidos del análisis comparativo.</div>
  <div id="pairs-list"><div class="loading"><div class="spinner"></div>Cargando pares...</div></div>
</div>
</div>

<!-- ── METRICS ── -->
<div id="tab-metrics" class="tab-content">
<div class="container">
  <div class="section-title">📈 Métricas Cuantitativas Wikipedia</div>
  <div class="grid-2" id="wiki-charts">
    <div class="card"><h3>Nº Referencias</h3><div class="chart-container"><canvas id="chart-refs"></canvas></div></div>
    <div class="card"><h3>Nº Enlances Internos</h3><div class="chart-container"><canvas id="chart-links"></canvas></div></div>
    <div class="card"><h3>Nº Categorías</h3><div class="chart-container"><canvas id="chart-cats"></canvas></div></div>
    <div class="card"><h3>Nº Imágenes</h3><div class="chart-container"><canvas id="chart-imgs"></canvas></div></div>
  </div>
  <div class="card" style="margin-top:20px">
    <h3>Tabla comparativa por par</h3>
    <div style="overflow-x:auto"><table id="metrics-table">
      <thead><tr><th>#</th><th>Mujer</th><th>Hombre</th><th>Área</th><th>Palabras ♀</th><th>Palabras ♂</th><th>Refs ♀</th><th>Refs ♂</th><th>Links ♀</th><th>Links ♂</th><th>Estado</th></tr></thead>
      <tbody id="metrics-tbody"></tbody>
    </table></div>
  </div>
</div>
</div>

<!-- ── NLP ── -->
<div id="tab-nlp" class="tab-content">
<div class="container">
  <div class="section-title">🔤 Análisis de Lenguaje Natural</div>
  <div class="grid-2">
    <div class="card">
      <h3>Índice de "Domesticidad" (Id)</h3>
      <p style="font-size:0.8rem;color:var(--text-muted);margin-bottom:12px">Frecuencia de términos familiares por 1000 palabras</p>
      <div class="chart-container"><canvas id="chart-domesticity"></canvas></div>
    </div>
    <div class="card">
      <h3>Densidad Adjetivos Epistémicos</h3>
      <p style="font-size:0.8rem;color:var(--text-muted);margin-bottom:12px">Ratio adjetivos de intelecto vs. personalidad</p>
      <div class="chart-container"><canvas id="chart-epistemic"></canvas></div>
    </div>
    <div class="card">
      <h3>Ratio de Agencia (Voz Activa/Pasiva)</h3>
      <p style="font-size:0.8rem;color:var(--text-muted);margin-bottom:12px">Mayor valor = más voz activa (más agencia)</p>
      <div class="chart-container"><canvas id="chart-agency"></canvas></div>
    </div>
    <div class="card">
      <h3>Centralidad de Enlaces Científicos</h3>
      <p style="font-size:0.8rem;color:var(--text-muted);margin-bottom:12px">Proporción de enlaces a conceptos científicos</p>
      <div class="chart-container"><canvas id="chart-scilinks"></canvas></div>
    </div>
  </div>
  <div class="card" style="margin-top:20px">
    <h3>Palabras domésticas detectadas por biografía</h3>
    <div id="domestic-words-list"><p style="color:var(--text-muted)">Ejecuta el análisis para ver resultados.</p></div>
  </div>
</div>
</div>

<!-- ── AUDIT ── -->
<div id="tab-audit" class="tab-content">
<div class="container">
  <div class="section-title">🤖 Auditoría LLM (LLM-as-a-Judge)</div>
  <div class="alert alert-warning">⚠️ Esta función requiere una API key de Anthropic configurada. El análisis LLM se ejecuta en el modo "Análisis Completo".</div>
  <div id="audit-results">
    <div class="loading"><div class="spinner"></div>Sin resultados de auditoría LLM todavía.</div>
  </div>
</div>
</div>

<!-- ── METHODOLOGY ── -->
<div id="tab-methodology" class="tab-content">
<div class="container">
  <div class="section-title">📖 Metodología</div>
  <div class="grid-2">
    <div class="card">
      <h2>Métricas Cuantitativas (Wikipedia)</h2>
      <div style="margin-top:12px;font-size:0.9rem;line-height:1.7;color:var(--text-muted)">
        <p><strong style="color:var(--text)">Longitud del artículo</strong> — Número total de palabras</p>
        <p><strong style="color:var(--text)">Número de referencias</strong> — Total de citas bibliográficas</p>
        <p><strong style="color:var(--text)">Diversidad de referencias</strong> — Científicas, periodísticas, institucionales</p>
        <p><strong style="color:var(--text)">Imágenes</strong> — Presencia y calidad visual</p>
        <p><strong style="color:var(--text)">Categorías</strong> — Número y tipología de categorías asignadas</p>
        <p><strong style="color:var(--text)">Fecha de creación</strong> — Antigüedad del artículo</p>
        <p><strong style="color:var(--text)">Número de ediciones</strong> — Actividad editorial acumulada</p>
      </div>
    </div>
    <div class="card">
      <h2>Métricas NLP</h2>
      <div style="margin-top:12px;font-size:0.9rem;line-height:1.7;color:var(--text-muted)">
        <p><strong style="color:var(--text)">Índice de Domesticidad (Id)</strong> — <code>Σ(keywords_domésticos) / N × 1000</code></p>
        <p><strong style="color:var(--text)">Densidad Epistémica</strong> — Ratio adjetivos de intelecto vs. personalidad (spaCy)</p>
        <p><strong style="color:var(--text)">Ratio de Agencia</strong> — <code>R = verbos_activos / verbos_pasivos</code></p>
        <p><strong style="color:var(--text)">Centralidad de enlaces</strong> — Proporción enlaces a conceptos científicos</p>
      </div>
    </div>
    <div class="card">
      <h2>Auditoría LLM (3 prompts)</h2>
      <div style="margin-top:12px;font-size:0.9rem;line-height:1.7;color:var(--text-muted)">
        <p><strong style="color:var(--text)">Prompt 1 — Blind Test</strong> — Detección de foco narrativo (personal vs. profesional) sin nombres propios</p>
        <p><strong style="color:var(--text)">Prompt 2 — Atribución de Mérito</strong> — Logros individuales vs. colaborativos</p>
        <p><strong style="color:var(--text)">Prompt 3 — Auditoría de Estereotipos</strong> — Role Congruity Theory, puntuación 0-10</p>
      </div>
    </div>
    <div class="card">
      <h2>Corpus</h2>
      <div style="margin-top:12px;font-size:0.9rem;line-height:1.7;color:var(--text-muted)">
        <p><strong style="color:var(--text)">Muestra femenina</strong> — Premiadas Ada Byron (España + Latinoamérica)</p>
        <p><strong style="color:var(--text)">Muestra masculina</strong> — Homólogos comparables por área y trayectoria</p>
        <p><strong style="color:var(--text)">Total teórico</strong> — 20 pares (n=40)</p>
        <p><strong style="color:var(--text)">Filtro</strong> — Solo pares donde AMBOS tienen artículo en Wikipedia ES</p>
        <p><strong style="color:var(--text)">Modelo NLP</strong> — spaCy es_core_news_lg</p>
        <p><strong style="color:var(--text)">Modelo LLM</strong> — Claude Sonnet 4</p>
      </div>
    </div>
  </div>
</div>
</div>

<script>
const API = 'API_GATEWAY_PLACEHOLDER';
let allResults = [];
let summary = {};
let charts = {};
let pollingInterval = null;

// ── Navigation ────────────────────────────────────────────────────────────────
function showTab(name) {
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  event.target.classList.add('active');
  if (name === 'pairs') renderPairs();
  if (name === 'metrics') renderMetricsTable();
  if (name === 'nlp') renderNLPCharts();
  if (name === 'audit') renderAuditResults();
}

// ── API calls ─────────────────────────────────────────────────────────────────
async function fetchJSON(url, opts) {
  try {
    const r = await fetch(url, opts);
    return await r.json();
  } catch(e) {
    console.error(url, e);
    return null;
  }
}

async function startAnalysis(withLLM) {
  const key = document.getElementById('api-key-input').value.trim();
  if (withLLM && !key) {
    alert('Para el análisis LLM necesitas introducir tu API key de Anthropic.');
    return;
  }
  
  const data = await fetchJSON(`${API}/analyze/start?run_llm=${withLLM}`, {method:'POST'});
  if (data) {
    alert(`Análisis iniciado. ${data.total_pairs} pares en cola.`);
    startPolling();
  }
}

async function clearResults() {
  if (!confirm('¿Eliminar todos los resultados?')) return;
  await fetchJSON(`${API}/results`, {method:'DELETE'});
  allResults = [];
  summary = {};
  refreshData();
}

async function refreshData() {
  const [statusData, resultsData, sumData] = await Promise.all([
    fetchJSON(`${API}/analyze/status`),
    fetchJSON(`${API}/results`),
    fetchJSON(`${API}/results/summary`)
  ]);
  
  if (resultsData) allResults = resultsData.results || [];
  if (sumData) summary = sumData;
  
  renderStatus(statusData);
  renderSummaryCards();
  renderDashboardCharts();
}

function startPolling() {
  if (pollingInterval) clearInterval(pollingInterval);
  pollingInterval = setInterval(async () => {
    const status = await fetchJSON(`${API}/analyze/status`);
    renderStatus(status);
    if (status && (status.status === 'completed' || status.status === 'idle')) {
      clearInterval(pollingInterval);
      pollingInterval = null;
      await refreshData();
    } else {
      const r = await fetchJSON(`${API}/results`);
      if (r) allResults = r.results || [];
      renderSummaryCards();
    }
  }, 3000);
}

// ── Render Status ─────────────────────────────────────────────────────────────
function renderStatus(s) {
  if (!s) { document.getElementById('status-content').innerHTML = '<p style="color:var(--text-muted)">Sin datos</p>'; return; }
  const color = s.status === 'running' ? 'var(--warning)' : s.status === 'completed' ? 'var(--success)' : 'var(--text-muted)';
  const dotClass = s.status === 'running' ? 'dot-warn' : s.status === 'completed' ? 'dot-ok' : 'dot-err';
  document.getElementById('status-content').innerHTML = `
    <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
      <span><span class="status-dot ${dotClass}"></span><strong style="color:${color}">${s.status.toUpperCase()}</strong></span>
      <span style="color:var(--text-muted)">${s.current_step || ''}</span>
      <span style="color:var(--text-muted)">Par ${s.current_pair || 0} / ${s.total_pairs || 20}</span>
    </div>
    <div style="margin-top:12px">
      <div style="display:flex;justify-content:space-between;margin-bottom:6px"><span style="font-size:0.8rem;color:var(--text-muted)">Progreso</span><span style="font-size:0.8rem">${Math.round(s.progress || 0)}%</span></div>
      <div class="progress-bar"><div class="progress-fill" style="width:${s.progress || 0}%"></div></div>
    </div>
  `;
}

// ── Summary Cards ─────────────────────────────────────────────────────────────
function renderSummaryCards() {
  const valid = allResults.filter(r => r.both_in_wikipedia && !r.skipped).length;
  const skipped = allResults.filter(r => !r.both_in_wikipedia || r.skipped).length;
  const total = 20;
  document.getElementById('m-total').textContent = total;
  document.getElementById('m-valid').textContent = valid;
  document.getElementById('m-skipped').textContent = skipped;
  document.getElementById('m-coverage').textContent = allResults.length ? Math.round((valid/total)*100) + '%' : '—%';
}

// ── Dashboard Charts ──────────────────────────────────────────────────────────
function renderDashboardCharts() {
  const valid = allResults.filter(r => r.both_in_wikipedia && !r.skipped);
  if (!valid.length) return;

  const labels = valid.map(r => `Par ${r.pair_id}`);
  const womenWC = valid.map(r => r.wiki_woman?.word_count || 0);
  const menWC = valid.map(r => r.wiki_man?.word_count || 0);

  destroyChart('chart-wordcount');
  charts['chart-wordcount'] = new Chart(document.getElementById('chart-wordcount'), {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'Mujeres', data: womenWC, backgroundColor: 'rgba(232,67,147,0.7)', borderColor: '#e84393', borderWidth: 1 },
        { label: 'Hombres', data: menWC, backgroundColor: 'rgba(59,130,246,0.7)', borderColor: '#3b82f6', borderWidth: 1 }
      ]
    },
    options: { ...chartDefaults(), plugins: { legend: { labels: { color: '#e8e8ff' } } } }
  });

  // Bar metrics
  const sumWiki = summary.wikipedia_metrics || {};
  const metrics = [
    { name: 'Palabras', woman: sumWiki.avg_word_count_women, man: sumWiki.avg_word_count_men, max: Math.max(sumWiki.avg_word_count_women, sumWiki.avg_word_count_men) },
    { name: 'Referencias', woman: sumWiki.avg_references_women, man: sumWiki.avg_references_men, max: Math.max(sumWiki.avg_references_women, sumWiki.avg_references_men) },
    { name: 'Categorías', woman: sumWiki.avg_categories_women, man: sumWiki.avg_categories_men, max: Math.max(sumWiki.avg_categories_women, sumWiki.avg_categories_men) },
    { name: 'Imágenes', woman: sumWiki.avg_images_women||0, man: sumWiki.avg_images_men||0, max: 10 },
  ];

  document.getElementById('bar-wiki-metrics').innerHTML = metrics.map(m => {
    const wPct = m.max > 0 ? Math.round((m.woman/m.max)*100) : 0;
    const mPct = m.max > 0 ? Math.round((m.man/m.max)*100) : 0;
    return `<div class="bar-compare">
      <div class="label">${m.name}</div>
      <div class="bars">
        <div class="bar-fill bar-woman" style="width:${wPct}%">${m.woman?.toFixed(1)||'—'}</div>
        <div class="bar-fill bar-man" style="width:${mPct}%">${m.man?.toFixed(1)||'—'}</div>
      </div>
    </div>`;
  }).join('');
}

// ── Pairs List ────────────────────────────────────────────────────────────────
function renderPairs() {
  const container = document.getElementById('pairs-list');
  const pairs = allResults.length ? allResults : STATIC_PAIRS;
  
  container.innerHTML = pairs.map(r => {
    const isStatic = !r.wiki_woman;
    const hasWiki = r.both_in_wikipedia;
    const skipped = r.skipped || !hasWiki;
    const womanOk = r.wiki_woman?.exists_in_wikipedia;
    const manOk = r.wiki_man?.exists_in_wikipedia;
    
    const statusBadge = isStatic ? `<span class="badge badge-skip">Pendiente</span>` :
      skipped ? `<span class="badge badge-warning">Omitido</span>` :
      `<span class="badge badge-success">✓ Válido</span>`;

    const womanBadge = isStatic ? '' : (womanOk ? '✅' : '❌');
    const manBadge = isStatic ? '' : (manOk ? '✅' : '❌');

    let details = '';
    if (!isStatic && !skipped && r.wiki_woman) {
      details = `<div class="pair-details" id="detail-${r.pair_id}">
        <div class="grid-2" style="margin-top:12px;gap:12px">
          <div>
            <div style="color:var(--woman);font-weight:600;margin-bottom:8px">${r.woman_name}</div>
            <div class="metric-row"><span>Palabras</span><strong>${r.wiki_woman.word_count}</strong></div>
            <div class="metric-row"><span>Referencias</span><strong>${r.wiki_woman.num_references}</strong></div>
            <div class="metric-row"><span>Categorías</span><strong>${r.wiki_woman.num_categories}</strong></div>
            <div class="metric-row"><span>Domest. Index</span><strong>${r.nlp_woman?.domesticity_index?.toFixed(3)||'—'}</strong></div>
            <div class="metric-row"><span>Densidad Epist.</span><strong>${r.nlp_woman?.epistemic_density?.toFixed(3)||'—'}</strong></div>
            <div class="metric-row"><span>Ratio Agencia</span><strong>${r.nlp_woman?.agency_ratio?.toFixed(2)||'—'}</strong></div>
          </div>
          <div>
            <div style="color:var(--man);font-weight:600;margin-bottom:8px">${r.man_name}</div>
            <div class="metric-row"><span>Palabras</span><strong>${r.wiki_man.word_count}</strong></div>
            <div class="metric-row"><span>Referencias</span><strong>${r.wiki_man.num_references}</strong></div>
            <div class="metric-row"><span>Categorías</span><strong>${r.wiki_man.num_categories}</strong></div>
            <div class="metric-row"><span>Domest. Index</span><strong>${r.nlp_man?.domesticity_index?.toFixed(3)||'—'}</strong></div>
            <div class="metric-row"><span>Densidad Epist.</span><strong>${r.nlp_man?.epistemic_density?.toFixed(3)||'—'}</strong></div>
            <div class="metric-row"><span>Ratio Agencia</span><strong>${r.nlp_man?.agency_ratio?.toFixed(2)||'—'}</strong></div>
          </div>
        </div>
        ${r.wiki_woman?.wikipedia_url ? `<div style="margin-top:8px;font-size:0.8rem"><a href="${r.wiki_woman.wikipedia_url}" target="_blank" style="color:var(--woman)">→ Wikipedia ${r.woman_name}</a></div>` : ''}
        ${r.wiki_man?.wikipedia_url ? `<div style="font-size:0.8rem"><a href="${r.wiki_man.wikipedia_url}" target="_blank" style="color:var(--man)">→ Wikipedia ${r.man_name}</a></div>` : ''}
        ${skipped && r.skip_reason ? `<div class="alert alert-warning" style="margin-top:8px">${r.skip_reason}</div>` : ''}
      </div>`;
    } else if (!isStatic && skipped) {
      details = `<div class="pair-details" id="detail-${r.pair_id}">
        <div class="alert alert-warning" style="margin-top:12px">
          <strong>Par omitido:</strong> ${r.skip_reason || 'Uno o ambos miembros sin entrada en Wikipedia ES'}
          ${!womanOk ? `<div>❌ ${r.woman_name}: no encontrada</div>` : ''}
          ${!manOk ? `<div>❌ ${r.man_name}: no encontrado</div>` : ''}
        </div>
      </div>`;
    }

    const src = isStatic ? STATIC_PAIRS.find(p=>p.pair_id==r.pair_id) : r;

    return `<div class="pair-card">
      <div class="pair-header" onclick="toggleDetail(${r.pair_id || src.pair_id})">
        <div style="min-width:32px;text-align:center;color:var(--text-muted);font-size:0.85rem">#${r.pair_id||src.pair_id}</div>
        <div class="pair-names">
          <div class="pair-woman">${womanBadge} ${r.woman_name||src.woman}</div>
          <div class="pair-man">${manBadge} ${r.man_name||src.man}</div>
          <div class="pair-area">${r.area||src.area}</div>
        </div>
        ${statusBadge}
        <span style="color:var(--text-muted)">▼</span>
      </div>
      ${details}
    </div>`;
  }).join('');
}

function toggleDetail(id) {
  const el = document.getElementById('detail-' + id);
  if (el) el.classList.toggle('open');
}

// ── Metrics Table ─────────────────────────────────────────────────────────────
function renderMetricsTable() {
  const valid = allResults.filter(r => r.both_in_wikipedia && !r.skipped);
  const tbody = document.getElementById('metrics-tbody');
  if (!valid.length) { tbody.innerHTML = '<tr><td colspan="11" style="text-align:center;color:var(--text-muted)">Sin datos. Ejecuta el análisis primero.</td></tr>'; return; }
  
  tbody.innerHTML = valid.map(r => `<tr>
    <td>${r.pair_id}</td>
    <td class="pair-woman" style="color:var(--woman)">${r.woman_name}</td>
    <td class="pair-man" style="color:var(--man)">${r.man_name}</td>
    <td style="color:var(--text-muted);font-size:0.8rem">${r.area}</td>
    <td>${r.wiki_woman?.word_count||'—'}</td>
    <td>${r.wiki_man?.word_count||'—'}</td>
    <td>${r.wiki_woman?.num_references||'—'}</td>
    <td>${r.wiki_man?.num_references||'—'}</td>
    <td>${r.wiki_woman?.num_internal_links||'—'}</td>
    <td>${r.wiki_man?.num_internal_links||'—'}</td>
    <td><span class="badge badge-success">✓</span></td>
  </tr>`).join('');
  
  // Also render Wikipedia comparison charts
  const labels = valid.map(r => `#${r.pair_id}`);
  [
    {id:'chart-refs', field:'num_references', label:'Referencias'},
    {id:'chart-links', field:'num_internal_links', label:'Enlances'},
    {id:'chart-cats', field:'num_categories', label:'Categorías'},
    {id:'chart-imgs', field:'num_images', label:'Imágenes'},
  ].forEach(({id, field, label}) => {
    destroyChart(id);
    charts[id] = new Chart(document.getElementById(id), {
      type: 'bar',
      data: {
        labels,
        datasets: [
          {label:'Mujeres', data: valid.map(r=>r.wiki_woman?.[field]||0), backgroundColor:'rgba(232,67,147,0.7)', borderColor:'#e84393', borderWidth:1},
          {label:'Hombres', data: valid.map(r=>r.wiki_man?.[field]||0), backgroundColor:'rgba(59,130,246,0.7)', borderColor:'#3b82f6', borderWidth:1}
        ]
      },
      options: {...chartDefaults(), plugins:{legend:{labels:{color:'#e8e8ff'}}}}
    });
  });
}

// ── NLP Charts ────────────────────────────────────────────────────────────────
function renderNLPCharts() {
  const valid = allResults.filter(r => r.both_in_wikipedia && !r.skipped && r.nlp_woman);
  if (!valid.length) return;

  const labels = valid.map(r => `#${r.pair_id}`);
  
  const nlpMetrics = [
    {id:'chart-domesticity', field:'domesticity_index', label:'Índice Domesticidad'},
    {id:'chart-epistemic', field:'epistemic_density', label:'Densidad Epistémica'},
    {id:'chart-agency', field:'agency_ratio', label:'Ratio Agencia'},
    {id:'chart-scilinks', field:'scientific_links_ratio', label:'Links Científicos'},
  ];

  nlpMetrics.forEach(({id, field, label}) => {
    destroyChart(id);
    charts[id] = new Chart(document.getElementById(id), {
      type: 'bar',
      data: {
        labels,
        datasets: [
          {label:'Mujeres', data:valid.map(r=>r.nlp_woman?.[field]||0), backgroundColor:'rgba(232,67,147,0.7)', borderColor:'#e84393', borderWidth:1},
          {label:'Hombres', data:valid.map(r=>r.nlp_man?.[field]||0), backgroundColor:'rgba(59,130,246,0.7)', borderColor:'#3b82f6', borderWidth:1}
        ]
      },
      options:{...chartDefaults(), plugins:{legend:{labels:{color:'#e8e8ff'}}}}
    });
  });

  // Domestic keywords
  const domesticEl = document.getElementById('domestic-words-list');
  domesticEl.innerHTML = valid.map(r => {
    const wKws = r.nlp_woman?.domestic_keywords_found || [];
    const mKws = r.nlp_man?.domestic_keywords_found || [];
    if (!wKws.length && !mKws.length) return '';
    return `<div style="margin-bottom:12px">
      <strong>#${r.pair_id}</strong>
      ${wKws.length ? `<div style="color:var(--woman);font-size:0.85rem">♀ ${r.woman_name}: <em>${wKws.join(', ')}</em></div>` : ''}
      ${mKws.length ? `<div style="color:var(--man);font-size:0.85rem">♂ ${r.man_name}: <em>${mKws.join(', ')}</em></div>` : ''}
    </div>`;
  }).join('') || '<p style="color:var(--text-muted)">No se detectaron palabras domésticas en los textos analizados.</p>';
}

// ── Audit Results ─────────────────────────────────────────────────────────────
function renderAuditResults() {
  const withAudit = allResults.filter(r => r.llm_audit && !r.llm_audit.error);
  const container = document.getElementById('audit-results');
  
  if (!withAudit.length) {
    container.innerHTML = `<div class="loading" style="color:var(--text-muted)">
      Sin resultados de auditoría LLM. Ejecuta el análisis con la opción "Análisis Completo (incl. LLM)".
    </div>`;
    return;
  }

  container.innerHTML = withAudit.map(r => {
    const a = r.llm_audit;
    const biasW = (a.bias_score_woman||0).toFixed(1);
    const biasM = (a.bias_score_man||0).toFixed(1);
    const biasColor = w => w > 6 ? 'var(--danger)' : w > 3 ? 'var(--warning)' : 'var(--success)';
    
    return `<div class="card" style="margin-bottom:16px">
      <h2>Par #${r.pair_id}: <span style="color:var(--woman)">${r.woman_name}</span> / <span style="color:var(--man)">${r.man_name}</span></h2>
      <div class="grid-2" style="margin-top:12px">
        <div>
          <div class="metric-row"><span>Puntuación sesgo ♀</span><strong style="color:${biasColor(a.bias_score_woman)}">${biasW}/10</strong></div>
          <div class="metric-row"><span>Puntuación sesgo ♂</span><strong style="color:${biasColor(a.bias_score_man)}">${biasM}/10</strong></div>
          <div class="metric-row"><span>Δ Balance narrativo</span><strong>${(a.narrative_balance_score||0).toFixed(3)}</strong></div>
        </div>
        <div>
          ${a.focus_analysis?.observaciones ? `<p style="font-size:0.85rem;color:var(--text-muted)">${a.focus_analysis.observaciones}</p>` : ''}
          ${a.stereotype_audit_woman?.recomendaciones ? `
            <div style="margin-top:8px">
              <strong style="font-size:0.8rem;color:var(--woman)">Recomendaciones ♀:</strong>
              <ul style="font-size:0.8rem;color:var(--text-muted);margin-left:16px">
                ${(a.stereotype_audit_woman.recomendaciones||[]).map(r=>`<li>${r}</li>`).join('')}
              </ul>
            </div>` : ''}
        </div>
      </div>
    </div>`;
  }).join('');
}

// ── Chart helpers ─────────────────────────────────────────────────────────────
function chartDefaults() {
  return {
    responsive: true, maintainAspectRatio: false,
    scales: {
      x: { ticks: { color: '#9999bb' }, grid: { color: 'rgba(255,255,255,0.05)' } },
      y: { ticks: { color: '#9999bb' }, grid: { color: 'rgba(255,255,255,0.05)' }, beginAtZero: true }
    }
  };
}
function destroyChart(id) {
  if (charts[id]) { charts[id].destroy(); delete charts[id]; }
}

// Static pairs list for before analysis
const STATIC_PAIRS = [
  {pair_id:1,woman:'Montserrat Meya',man:'Ramón López de Mántaras',area:'Lingüística computacional / IA'},
  {pair_id:2,woman:'Asunción Gómez-Pérez',man:'Carles Sierra',area:'Web semántica / Ontologías'},
  {pair_id:3,woman:'Nuria Oliver',man:'Mateo Valero',area:'IA / Big Data / Supercomputación'},
  {pair_id:4,woman:'Regina Llopis Rivas',man:'Andrés Pedreño',area:'IA aplicada / Economía digital'},
  {pair_id:5,woman:'María Ángeles Martín Prats',man:'Pedro Duque',area:'Ingeniería aeroespacial'},
  {pair_id:6,woman:'Concha Monje',man:'José Luis Pons',area:'Robótica'},
  {pair_id:7,woman:'Laura Lechuga',man:'Luis Liz-Marzán',area:'Nanociencia / Biosensores'},
  {pair_id:8,woman:'Elena García Armada',man:'José Luis López Gómez',area:'Exoesqueletos / Ingeniería'},
  {pair_id:9,woman:'Lourdes Verdes-Montenegro',man:'José Cernicharo',area:'Radioastronomía / Astrofísica'},
  {pair_id:10,woman:'María José Escalona',man:'Manuel Hermenegildo',area:'Ingeniería del software'},
  {pair_id:11,woman:'Julia G. Niso',man:'Gustavo Deco',area:'Neuroingeniería / Neurociencia'},
  {pair_id:12,woman:'Sara García Alonso',man:'Pedro Duque',area:'Biología / Astronáutica'},
  {pair_id:13,woman:'Silvia Nair Goyanes',man:'Juan Martín Maldacena',area:'Física'},
  {pair_id:14,woman:'Noemí Zaritzky',man:'Lino Barañao',area:'Ingeniería química / Bioquímica'},
  {pair_id:15,woman:'Raquel Lía Chan',man:'Esteban Hopp',area:'Biotecnología vegetal'},
  {pair_id:16,woman:'Barbarita Lara',man:'Claudio Gutiérrez',area:'Informática'},
  {pair_id:17,woman:'Loreto Valenzuela',man:'Pablo Valenzuela',area:'Biotecnología'},
  {pair_id:18,woman:'Lucía Spangenberg',man:'Rafael Radi',area:'Bioinformática / Bioquímica'},
  {pair_id:19,woman:'Fiorella Haim',man:'Miguel Brechner',area:'Innovación educativa digital'},
  {pair_id:20,woman:'María Clara Betancourt',man:'Manuel Elkin Patarroyo',area:'Ing. ambiental / Inmunología'},
];

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  await refreshData();
  renderPairs(); // Initial render with static data
  // Auto-start polling if analysis is running
  const status = await fetchJSON(`${API}/analyze/status`);
  if (status?.status === 'running') startPolling();
}

init();
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard():
    api_url = os.getenv("API_GATEWAY_URL", "http://localhost:8000")
    html = DASHBOARD_HTML.replace("API_GATEWAY_PLACEHOLDER", api_url)
    return HTMLResponse(content=html)


@app.get("/health")
def health():
    return {"status": "ok", "service": "frontend"}
