<?php
// This file is part of Moodle - http://moodle.org/
//
// Moodle is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

/**
 * Annotation viewer: every video-elicitation annotation, with filters and export.
 *
 * Moved here from the public /annotation_viewer.html (2026-09-11), which read
 * annotators' names and transcripts from an unauthenticated backend route.
 * Site administrators only; data comes from annotations_dashboard.php.
 *
 * @package   local_craftpilot
 * @copyright 2026
 * @license   http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

require('../../config.php');

require_login();
require_capability('moodle/site:config', context_system::instance());

header('Cache-Control: no-store');
?>
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Annotation Viewer — CraftPilot</title>
<style>
  /* Default (dark) ─ used when no data-theme is set */
  :root,
  :root[data-theme="dark"] {
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #22263a;
    --border: #2e3352;
    --accent: #6c8ef7;
    --accent2: #a78bfa;
    --text: #e2e8f0;
    --muted: #7b88a8;
    --ok: #34d399;
    --warn: #fbbf24;
    --err: #f87171;
    --transcription-color: #c4cde0;
  }

  /* Light theme — Studio palette aligned */
  :root[data-theme="light"] {
    --bg: #F8FBFE;
    --surface: #FFFFFF;
    --surface2: #F2FAFF;
    --border: #E6EEF6;
    --accent: #0066CC;
    --accent2: #1D7FD9;
    --text: #1F2A37;
    --muted: #64748B;
    --ok: #1F9D6B;
    --warn: #D78A2A;
    --err: #E03A5C;
    --transcription-color: #334155;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }
  html { color-scheme: dark; }
  html[data-theme="light"] { color-scheme: light; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', system-ui, sans-serif;
    min-height: 100vh;
    transition: background-color 240ms ease, color 240ms ease;
  }

  /* Theme toggle */
  .theme-toggle {
    margin-left: auto;
    width: 38px; height: 38px;
    border-radius: 50%;
    background: var(--surface);
    border: 1px solid var(--border);
    color: var(--text);
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 16px;
    transition: background-color 200ms ease, border-color 200ms ease, color 200ms ease, transform 140ms ease;
  }
  .theme-toggle:hover { border-color: var(--accent); color: var(--accent); transform: translateY(-1px); }
  .theme-toggle .icon-light { display: none; }
  html[data-theme="light"] .theme-toggle .icon-light { display: inline; }
  html[data-theme="light"] .theme-toggle .icon-dark  { display: none; }

  header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 16px 32px; display: flex; align-items: center; gap: 16px; }
  header h1 { font-size: 1.2rem; font-weight: 600; color: var(--accent); }
  header .subtitle { color: var(--muted); font-size: 0.85rem; }

  .stats-bar { display: flex; gap: 12px; padding: 16px 32px; flex-wrap: wrap; }
  .stat { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px 18px; min-width: 120px; }
  .stat .val { font-size: 1.5rem; font-weight: 700; color: var(--accent); }
  .stat .lbl { font-size: 0.75rem; color: var(--muted); margin-top: 2px; }

  .controls { padding: 0 32px 16px; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
  .controls input, .controls select {
    background: var(--surface); border: 1px solid var(--border); color: var(--text);
    border-radius: 6px; padding: 8px 12px; font-size: 0.85rem; outline: none;
  }
  .controls input:focus, .controls select:focus { border-color: var(--accent); }
  #search { width: 260px; }
  .filter-label { color: var(--muted); font-size: 0.8rem; }
  .export-btn {
    margin-left: auto; padding: 8px 14px; border-radius: 6px; font-size: 0.82rem;
    font-weight: 600; cursor: pointer; border: 1px solid var(--border);
    background: var(--surface2); color: var(--text); transition: background 0.15s, border-color 0.15s;
  }
  .export-btn:hover { background: var(--accent); border-color: var(--accent); color: #fff; }

  .results-info { padding: 0 32px 8px; color: var(--muted); font-size: 0.82rem; }

  .cards { padding: 0 32px 32px; display: grid; gap: 14px; }

  .card {
    background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    overflow: hidden; transition: border-color 0.15s;
  }
  .card:hover { border-color: var(--accent); }

  .card-header {
    display: flex; justify-content: space-between; align-items: flex-start;
    padding: 14px 18px 10px; gap: 12px; flex-wrap: wrap;
  }
  .card-header-left { display: flex; flex-direction: column; gap: 4px; }
  .card-id { font-size: 0.75rem; color: var(--muted); }
  .card-title { font-weight: 600; font-size: 0.95rem; color: var(--text); }
  .card-meta { font-size: 0.78rem; color: var(--muted); }

  .badges { display: flex; gap: 6px; flex-wrap: wrap; }
  .badge {
    font-size: 0.7rem; padding: 3px 8px; border-radius: 20px; font-weight: 600; text-transform: uppercase;
    border: 1px solid;
  }
  .badge-completed { color: var(--ok); border-color: var(--ok); background: rgba(52,211,153,.08); }
  .badge-pending   { color: var(--warn); border-color: var(--warn); background: rgba(251,191,36,.08); }
  .badge-craft     { color: var(--accent2); border-color: var(--accent2); background: rgba(167,139,250,.08); }

  .card-body { padding: 0 18px 14px; }

  .transcription {
    font-size: 0.83rem; color: var(--transcription-color); line-height: 1.6;
    max-height: 80px; overflow: hidden; position: relative; cursor: pointer;
    transition: max-height 0.3s ease;
  }
  .transcription.expanded { max-height: 600px; }
  .transcription::after {
    content: ''; position: absolute; bottom: 0; left: 0; right: 0; height: 30px;
    background: linear-gradient(transparent, var(--surface));
    pointer-events: none;
  }
  .transcription.expanded::after { display: none; }

  .tags-row { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; }
  .tag {
    font-size: 0.7rem; padding: 2px 8px; border-radius: 4px; background: var(--surface2);
    border: 1px solid var(--border); color: var(--muted);
  }
  .tag .cat { color: var(--accent); font-weight: 600; }

  .timing { font-size: 0.75rem; color: var(--muted); margin-top: 8px; }

  .empty { text-align: center; color: var(--muted); padding: 60px; font-size: 0.9rem; }
  .loading { text-align: center; padding: 60px; color: var(--muted); }

  .status-row { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
  .status-item { font-size: 0.72rem; color: var(--muted); }
  .status-item span { font-weight: 600; }
  .s-completed { color: var(--ok); }
  .s-pending   { color: var(--warn); }
</style>
</head>
<body>

<header>
  <div>
    <h1>Annotation Viewer</h1>
    <div class="subtitle">CraftPilot · Video Elicitation Database</div>
  </div>
  <button id="themeToggle" class="theme-toggle" type="button" title="Toggle light / dark" aria-label="Toggle theme">
    <span class="icon-dark">&#9789;</span>
    <span class="icon-light">&#9728;</span>
  </button>
</header>

<script>
  (function () {
    const stored = localStorage.getItem('viewer-theme');
    const sysLight = window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches;
    const theme = stored || (sysLight ? 'light' : 'dark');
    document.documentElement.setAttribute('data-theme', theme);
  })();
  document.addEventListener('DOMContentLoaded', function () {
    const btn = document.getElementById('themeToggle');
    if (!btn) return;
    btn.addEventListener('click', function () {
      const cur = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
      const next = cur === 'light' ? 'dark' : 'light';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('viewer-theme', next);
    });
  });
</script>

<div class="stats-bar" id="statsBar">
  <div class="loading">Chargement…</div>
</div>

<div class="controls">
  <span class="filter-label">Filtres :</span>
  <input type="text" id="search" placeholder="Rechercher dans la transcription…">
  <select id="filterCraft"><option value="">Tous les métiers</option></select>
  <select id="filterStatus">
    <option value="">Tous les statuts</option>
    <option value="completed">Tout complété</option>
    <option value="pending">En attente</option>
  </select>
  <select id="filterAnnotator"><option value="">Tous les annotateurs</option></select>
  <button class="export-btn" onclick="exportJSON()">&#11123; JSON</button>
  <button class="export-btn" onclick="exportCSV()">&#11123; CSV / Excel</button>
</div>

<div class="results-info" id="resultsInfo"></div>

<div class="cards" id="cardsContainer">
  <div class="loading">Chargement des annotations…</div>
</div>

<script>
const DATA_URL = 'annotations_dashboard.php';

// Transcripts, names and tags come from annotators: never inject them as HTML.
function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);
}

let allAnnotations = [];

// ── Data loading ──────────────────────────────────────────────────────────────
async function loadData() {
  const res = await fetch(DATA_URL, { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  allAnnotations = data.annotations;
  return data;
}

// ── Stats bar ─────────────────────────────────────────────────────────────────
function renderStats(annotations) {
  const total      = annotations.length;
  const crafts     = [...new Set(annotations.map(a => a.craft).filter(Boolean))];
  const transcribed = annotations.filter(a => a.transcriptionstatus === 'completed').length;
  const reviewed   = annotations.filter(a => a.reviewstatus === 'completed').length;
  const tagged     = annotations.filter(a => a.taggingstatus === 'completed').length;
  const annotators = [...new Set(annotations.map(a => a.username).filter(Boolean))];

  document.getElementById('statsBar').innerHTML = [
    { val: total,            lbl: 'Annotations' },
    { val: crafts.join(', ') || '—', lbl: 'Métiers' },
    { val: transcribed,      lbl: 'Transcrites' },
    { val: reviewed,         lbl: 'Relues' },
    { val: tagged,           lbl: 'Taguées' },
    { val: annotators.length, lbl: 'Annotateurs' },
  ].map(s => `
    <div class="stat">
      <div class="val">${esc(s.val)}</div>
      <div class="lbl">${s.lbl}</div>
    </div>`).join('');
}

// ── Populate filter dropdowns ─────────────────────────────────────────────────
function populateFilters(annotations) {
  const crafts = [...new Set(annotations.map(a => a.craft).filter(Boolean))];
  const filterCraft = document.getElementById('filterCraft');
  crafts.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c; opt.textContent = c;
    filterCraft.appendChild(opt);
  });

  const annotators = [...new Set(annotations.map(a => a.username).filter(Boolean))];
  const filterAnnotator = document.getElementById('filterAnnotator');
  annotators.forEach(u => {
    const opt = document.createElement('option');
    opt.value = u; opt.textContent = u;
    filterAnnotator.appendChild(opt);
  });
}

// ── Card rendering ────────────────────────────────────────────────────────────
function formatTime(seconds) {
  const m = Math.floor(seconds / 60).toString().padStart(2, '0');
  const s = Math.floor(seconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

function statusBadge(val) {
  const cls = val === 'completed' ? 'badge-completed' : 'badge-pending';
  return `<span class="badge ${cls}">${esc(val)}</span>`;
}

function renderCard(a) {
  const tags = (a.tags || []).map(t =>
    `<span class="tag"><span class="cat">${esc(t.category)}</span> · ${esc(t.name)}</span>`
  ).join('');

  const statuses = [
    { lbl: 'Transcription', val: a.transcriptionstatus },
    { lbl: 'Relecture',     val: a.reviewstatus },
    { lbl: 'Jugement',      val: a.judgestatus },
    { lbl: 'Taguage',       val: a.taggingstatus },
  ].map(s => `
    <span class="status-item">
      ${s.lbl}: <span class="${s.val === 'completed' ? 's-completed' : 's-pending'}">${esc(s.val)}</span>
    </span>`).join('');

  const name = [a.firstname, a.lastname].filter(Boolean).join(' ') || a.username || '—';
  const duration = `${formatTime(a.starttime)} → ${formatTime(a.endtime)}`;

  return `
    <div class="card">
      <div class="card-header">
        <div class="card-header-left">
          <div class="card-id">#${esc(a.id)} · ${esc(a.video_filename || '—')} · ${duration}</div>
          <div class="card-meta">Annotateur : ${esc(name)} · ${esc(a.timecreated ? a.timecreated.slice(0,10) : '—')}</div>
        </div>
        <div class="badges">
          ${a.craft ? `<span class="badge badge-craft">${esc(a.craft)}</span>` : ''}
          ${a.task  ? `<span class="badge badge-craft">${esc(a.task)}</span>` : ''}
        </div>
      </div>
      <div class="card-body">
        <div class="transcription" onclick="this.classList.toggle('expanded')">
          ${a.transcription ? esc(a.transcription).replace(/\n/g,'<br>') : '<em style="color:var(--muted)">Pas de transcription</em>'}
        </div>
        ${tags ? `<div class="tags-row">${tags}</div>` : ''}
        <div class="status-row">${statuses}</div>
      </div>
    </div>`;
}

function renderCards(annotations) {
  const container = document.getElementById('cardsContainer');
  document.getElementById('resultsInfo').textContent =
    `${annotations.length} annotation${annotations.length !== 1 ? 's' : ''} affichée${annotations.length !== 1 ? 's' : ''}`;

  if (!annotations.length) {
    container.innerHTML = '<div class="empty">Aucune annotation ne correspond aux filtres.</div>';
    return;
  }
  container.innerHTML = annotations.map(renderCard).join('');
}

// ── Filtering ─────────────────────────────────────────────────────────────────
function applyFilters() {
  const search     = document.getElementById('search').value.trim().toLowerCase();
  const craft      = document.getElementById('filterCraft').value;
  const status     = document.getElementById('filterStatus').value;
  const annotator  = document.getElementById('filterAnnotator').value;

  const STATUSES = ['transcriptionstatus', 'reviewstatus', 'judgestatus', 'taggingstatus'];

  return allAnnotations.filter(a => {
    if (search && !(a.transcription || '').toLowerCase().includes(search)) return false;
    if (craft && a.craft !== craft) return false;
    if (annotator && a.username !== annotator) return false;
    if (status === 'completed' && !STATUSES.every(s => a[s] === 'completed')) return false;
    if (status === 'pending'   &&  STATUSES.every(s => a[s] === 'completed')) return false;
    return true;
  });
}

// ── Wiring ────────────────────────────────────────────────────────────────────
function onFilterChange() {
  renderCards(applyFilters());
}

['search','filterCraft','filterStatus','filterAnnotator'].forEach(id => {
  document.getElementById(id).addEventListener('input', onFilterChange);
});

// ── Init ──────────────────────────────────────────────────────────────────────
(async () => {
  try {
    const data = await loadData();
    renderStats(data.annotations);
    populateFilters(data.annotations);
    renderCards(data.annotations);
  } catch (e) {
    document.getElementById('statsBar').innerHTML = '';
    document.getElementById('cardsContainer').innerHTML =
      `<div class="empty">Erreur de chargement : ${esc(e.message)}<br><br>
       Le backend CraftPilot est-il démarré ?</div>`;
  }
})();

// ── Client-side exports ───────────────────────────────────────────────────────
function downloadFile(filename, bytes, mime) {
  const blob = new Blob([bytes], { type: mime });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

function exportJSON() {
  const data = applyFilters();
  const payload = { exported_at: new Date().toISOString(), total: data.length, annotations: data };
  downloadFile('annotations_export.json', JSON.stringify(payload, null, 2), 'application/json');
}

function exportCSV() {
  const data = applyFilters();
  if (!data.length) return;
  const cols = ['id','craft','task','video_filename','starttime','endtime',
                 'username','firstname','lastname','transcription','tags',
                 'transcriptionstatus','reviewstatus','judgestatus','taggingstatus',
                 'issalient','timecreated'];
  const escape = v => {
    if (v === null || v === undefined) return '';
    if (Array.isArray(v)) v = v.map(t => `${t.category}:${t.name}`).join('; ');
    v = String(v).replace(/"/g, '""');
    return `"${v}"`;
  };
  const lines = [cols.join(',')];
  data.forEach(a => lines.push(cols.map(c => escape(a[c])).join(',')));
  downloadFile('annotations_export.csv', lines.join('\n'), 'text/csv;charset=utf-8');
}

</script>
</body>
</html>
