"""
Render a session graph JSON into a standalone, dependency-free HTML viewer.

No CDN, no build step, no network: the graph data is inlined and the force
layout is ~120 lines of vanilla JS. This matters for a demo on venue wifi.
"""

from __future__ import annotations

import json
from typing import Any

PALETTE = {
    "PROMPT":      "#4e79a7",
    "DECISION":    "#e15759",
    "TOOL_CALL":   "#9c9c9c",
    "FILE":        "#76b7b2",
    "ARTIFACT":    "#59a14f",
    "COMMIT":      "#f28e2c",
    "BRANCH":      "#edc948",
    "SKILL":       "#af7aa1",
    "AGENT":       "#ff9da7",
    "EXTERNAL":    "#79706e",
    "FINDING":     "#d4af37",
    "REQUIREMENT": "#8cd17d",
    "HYPOTHESIS":  "#b07aa1",
}

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<style>
  :root {
    --bg:#11141a; --panel:#181d26; --line:#272e3a; --fg:#e6e9ef; --muted:#8b95a7;
    --accent:#4e79a7;
  }
  * { box-sizing:border-box; }
  html,body { margin:0; height:100%; background:var(--bg); color:var(--fg);
    font:13px/1.5 ui-sans-serif,-apple-system,Segoe UI,Roboto,sans-serif; }
  #app { display:flex; height:100vh; }
  #side { width:300px; flex:0 0 300px; background:var(--panel);
    border-right:1px solid var(--line); display:flex; flex-direction:column; overflow:hidden; }
  #main { flex:1; position:relative; min-width:0; }
  svg { width:100%; height:100%; display:block; cursor:grab; }
  svg.dragging { cursor:grabbing; }
  h1 { font-size:14px; margin:0 0 2px; letter-spacing:.3px; }
  h2 { font-size:11px; text-transform:uppercase; letter-spacing:.08em;
    color:var(--muted); margin:16px 0 6px; font-weight:600; }
  .pad { padding:14px 14px 0; }
  .sub { color:var(--muted); font-size:11px; word-break:break-all; }
  #stats { display:grid; grid-template-columns:1fr 1fr; gap:4px 10px; margin-top:8px; font-size:11px; }
  #stats b { color:#fff; font-weight:600; }
  .legend { display:flex; flex-direction:column; gap:1px; }
  .lg { display:flex; align-items:center; gap:8px; padding:3px 6px; border-radius:4px;
    cursor:pointer; user-select:none; }
  .lg:hover { background:#1f2531; }
  .lg.off { opacity:.3; }
  .dot { width:10px; height:10px; border-radius:50%; flex:0 0 10px; }
  .lg .n { margin-left:auto; color:var(--muted); font-variant-numeric:tabular-nums; }
  input[type=search], input[type=range] { width:100%; }
  input[type=search] { background:#0d1016; border:1px solid var(--line); color:var(--fg);
    padding:6px 8px; border-radius:5px; font-size:12px; }
  #scroll { overflow-y:auto; padding-bottom:20px; flex:1; }
  #detail { border-top:1px solid var(--line); background:#0d1016; padding:12px 14px;
    max-height:44%; overflow-y:auto; font-size:11.5px; }
  #detail .t { font-size:10px; text-transform:uppercase; letter-spacing:.08em; font-weight:700; }
  #detail .lbl { font-size:13px; margin:4px 0 8px; color:#fff; font-weight:600; }
  #detail dl { margin:0; display:grid; grid-template-columns:auto 1fr; gap:3px 8px; }
  #detail dt { color:var(--muted); white-space:nowrap; }
  #detail dd { margin:0; word-break:break-word; }
  #detail code { background:#1b2230; padding:1px 5px; border-radius:3px;
    font-family:ui-monospace,Consolas,monospace; font-size:11px; display:inline-block; }
  .pill { display:inline-block; padding:1px 7px; border-radius:99px; font-size:10px;
    background:#1f2531; color:var(--muted); margin:0 3px 3px 0; }
  .pill.bad { background:#3a1f24; color:#ff9da7; }
  .pill.good { background:#1f3324; color:#8cd17d; }
  #hint { position:absolute; left:14px; bottom:12px; color:var(--muted); font-size:11px; }
  #tip { position:absolute; pointer-events:none; background:#0b0e13ee; border:1px solid var(--line);
    padding:5px 9px; border-radius:5px; font-size:11.5px; max-width:340px; display:none; z-index:9; }
  #toolbar { position:absolute; right:12px; top:12px; display:flex; gap:6px; flex-wrap:wrap;
    justify-content:flex-end; max-width:60%; }
  button { background:var(--panel); color:var(--fg); border:1px solid var(--line);
    padding:5px 11px; border-radius:5px; cursor:pointer; font-size:11.5px; }
  button:hover { border-color:#3c4659; }
  button.on { background:var(--accent); border-color:var(--accent); color:#fff; }
  .node { cursor:pointer; }
  .node text { pointer-events:none; }
  #time { padding:0 14px 12px; }
  #timelabel { color:var(--muted); font-size:11px; font-variant-numeric:tabular-nums; }
</style>
</head>
<body>
<div id="app">
  <div id="side">
    <div id="scroll">
      <div class="pad">
        <h1>Session Development Graph</h1>
        <div class="sub" id="sessid"></div>
        <div id="stats"></div>
      </div>
      <div class="pad">
        <h2>Search</h2>
        <input type="search" id="q" placeholder="filter nodes&hellip;" autocomplete="off">
      </div>
      <div class="pad">
        <h2>Node types <span class="sub">(click to toggle)</span></h2>
        <div class="legend" id="legend"></div>
      </div>
      <div class="pad">
        <h2>Edge types</h2>
        <div class="legend" id="elegend"></div>
      </div>
    </div>
    <div id="time">
      <h2 style="margin-top:0">Replay</h2>
      <input type="range" id="tslider" min="0" max="100" value="100">
      <div id="timelabel">full session</div>
    </div>
    <div id="detail"><div class="sub">Click a node to inspect its provenance.</div></div>
  </div>
  <div id="main">
    <div id="toolbar">
      <button id="bfuse" title="Show only the edges joining conversation to git">Fuse view</button>
      <button id="binferred" title="Hide LLM-inferred nodes">Observed only</button>
      <button id="brelax">Re-layout</button>
      <button id="bfit">Fit</button>
    </div>
    <svg id="svg"></svg>
    <div id="tip"></div>
    <div id="hint">drag background to pan &middot; scroll to zoom &middot; drag nodes to pin &middot; click for provenance</div>
  </div>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
const DATA    = JSON.parse(document.getElementById('data').textContent);
const PALETTE = __PALETTE__;
const GIT_TYPES = new Set(['COMMIT','BRANCH']);
const CONV_TYPES = new Set(['PROMPT','DECISION','TOOL_CALL','SKILL','AGENT']);

const svg  = document.getElementById('svg');
const tip  = document.getElementById('tip');
const NS   = 'http://www.w3.org/2000/svg';

let nodes = DATA.nodes.map(n => ({...n}));
let edges = DATA.edges.map(e => ({...e}));
const byId = new Map(nodes.map(n => [n.id, n]));
edges = edges.filter(e => byId.has(e.source) && byId.has(e.target));

// ---- degree drives node size: hubs are where the work concentrated
const deg = new Map(nodes.map(n => [n.id, 0]));
edges.forEach(e => { deg.set(e.source, deg.get(e.source)+1); deg.set(e.target, deg.get(e.target)+1); });
nodes.forEach(n => { n.deg = deg.get(n.id) || 0; n.r = 5 + Math.min(14, Math.sqrt(n.deg) * 3.1); });

// ---- ordered timestamps for the replay slider
const stamps = nodes.map(n => n.ts).filter(Boolean).sort();
const tmin = stamps[0], tmax = stamps[stamps.length-1];

// ---- layout state
const W = () => svg.clientWidth, H = () => svg.clientHeight;
nodes.forEach((n,i) => {
  const a = (i / nodes.length) * Math.PI * 2;
  n.x = W()/2 + Math.cos(a) * Math.min(W(),H()) * 0.32 + (Math.random()-.5)*40;
  n.y = H()/2 + Math.sin(a) * Math.min(W(),H()) * 0.32 + (Math.random()-.5)*40;
  n.vx = 0; n.vy = 0;
});

const adj = new Map(nodes.map(n => [n.id, new Set()]));
edges.forEach(e => { adj.get(e.source).add(e.target); adj.get(e.target).add(e.source); });

// ---- state
const hiddenTypes = new Set();
let showInferred = true, fuseOnly = false, query = '', selected = null, tcut = 1;

// ---- view transform
let view = {x:0, y:0, k:1};

const gRoot  = document.createElementNS(NS,'g');
const gEdges = document.createElementNS(NS,'g');
const gNodes = document.createElementNS(NS,'g');
gRoot.append(gEdges, gNodes);
svg.append(gRoot);

const defs = document.createElementNS(NS,'defs');
// built imperatively: innerHTML on SVG defs is unreliable across browsers
const marker = document.createElementNS(NS,'marker');
marker.setAttribute('id','arrow'); marker.setAttribute('viewBox','0 -4 8 8');
marker.setAttribute('refX','8'); marker.setAttribute('refY','0');
marker.setAttribute('markerWidth','5'); marker.setAttribute('markerHeight','5');
marker.setAttribute('orient','auto');
const mpath = document.createElementNS(NS,'path');
mpath.setAttribute('d','M0,-3L8,0L0,3'); mpath.setAttribute('fill','#55617a');
marker.append(mpath); defs.append(marker); svg.append(defs);

// ---- element pools
const edgeEls = edges.map(e => {
  const l = document.createElementNS(NS,'line');
  l.setAttribute('stroke-width','1');
  l.setAttribute('marker-end','url(#arrow)');
  gEdges.append(l);
  return l;
});

const nodeEls = nodes.map(n => {
  const g = document.createElementNS(NS,'g');
  g.setAttribute('class','node');
  const c = document.createElementNS(NS,'circle');
  c.setAttribute('r', n.r);
  c.setAttribute('fill', PALETTE[n.type] || '#888');
  c.setAttribute('stroke','#11141a');
  c.setAttribute('stroke-width','1.5');
  if (n.inferred) { c.setAttribute('stroke', PALETTE[n.type] || '#888');
                    c.setAttribute('stroke-dasharray','3 2'); c.setAttribute('fill-opacity','.25'); }
  const t = document.createElementNS(NS,'text');
  t.setAttribute('font-size','9.5'); t.setAttribute('fill','#c9d1de');
  t.setAttribute('x', n.r + 4); t.setAttribute('y','3.2');
  t.textContent = n.label.length > 34 ? n.label.slice(0,33) + '…' : n.label;
  g.append(c, t);
  gNodes.append(g);
  g.addEventListener('mouseenter', ev => showTip(ev, n));
  g.addEventListener('mousemove',  ev => positionTip(ev));
  g.addEventListener('mouseleave', () => tip.style.display = 'none');
  g.addEventListener('mousedown',  ev => startNodeDrag(ev, n));
  g.addEventListener('click',      ev => { ev.stopPropagation(); select(n); });
  return {g, c, t};
});

// ---- visibility
function tsVisible(n) {
  if (tcut >= 1 || !n.ts || !tmin) return true;
  const span = Date.parse(tmax) - Date.parse(tmin);
  return Date.parse(n.ts) <= Date.parse(tmin) + span * tcut;
}
function nodeVisible(n) {
  if (hiddenTypes.has(n.type)) return false;
  if (!showInferred && n.inferred) return false;
  if (!tsVisible(n)) return false;
  if (query) {
    const hay = (n.label + ' ' + n.detail + ' ' + JSON.stringify(n.provenance)).toLowerCase();
    if (!hay.includes(query)) return false;
  }
  if (fuseOnly) {
    // keep git nodes, and conversation nodes that actually touch git
    if (GIT_TYPES.has(n.type)) return true;
    if (!CONV_TYPES.has(n.type)) return false;
    for (const nb of adj.get(n.id)) if (GIT_TYPES.has(byId.get(nb).type)) return true;
    return false;
  }
  return true;
}
function edgeVisible(e) {
  if (!vis.get(e.source) || !vis.get(e.target)) return false;
  if (fuseOnly) {
    const a = byId.get(e.source).type, b = byId.get(e.target).type;
    return (GIT_TYPES.has(a) !== GIT_TYPES.has(b)) || e.type === 'parent_of' || e.type === 'tip_of';
  }
  return true;
}
let vis = new Map();
function recomputeVisibility() {
  vis = new Map(nodes.map(n => [n.id, nodeVisible(n)]));
  nodeEls.forEach((el,i) => el.g.style.display = vis.get(nodes[i].id) ? '' : 'none');
  edgeEls.forEach((el,i) => el.style.display = edgeVisible(edges[i]) ? '' : 'none');
  paintSelection();
}

// ---- force simulation (velocity damping, repulsion, springs, gravity)
let alpha = 1;
function step() {
  const live = nodes.filter(n => vis.get(n.id));
  const cx = W()/2, cy = H()/2;
  // repulsion - O(n^2) but n is in the hundreds, which is fine
  for (let i=0;i<live.length;i++) {
    const a = live[i];
    for (let j=i+1;j<live.length;j++) {
      const b = live[j];
      let dx = b.x-a.x, dy = b.y-a.y;
      let d2 = dx*dx + dy*dy;
      if (d2 < 1) { d2 = 1; dx = Math.random()-.5; dy = Math.random()-.5; }
      if (d2 > 360000) continue;
      const f = 2400 / d2;
      const d = Math.sqrt(d2);
      const fx = (dx/d)*f, fy = (dy/d)*f;
      a.vx -= fx; a.vy -= fy; b.vx += fx; b.vy += fy;
    }
  }
  // springs
  for (let i=0;i<edges.length;i++) {
    if (edgeEls[i].style.display === 'none') continue;
    const a = byId.get(edges[i].source), b = byId.get(edges[i].target);
    const dx = b.x-a.x, dy = b.y-a.y;
    const d = Math.sqrt(dx*dx+dy*dy) || 1;
    const target = 78 + a.r + b.r;
    const f = (d - target) * 0.0085;
    const fx = (dx/d)*f, fy = (dy/d)*f;
    a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
  }
  // gravity + integrate
  for (const n of live) {
    if (n.fixed) { n.vx = 0; n.vy = 0; continue; }
    n.vx += (cx - n.x) * 0.0022;
    n.vy += (cy - n.y) * 0.0022;
    n.vx *= 0.82; n.vy *= 0.82;
    n.x += n.vx * alpha * 2.2;
    n.y += n.vy * alpha * 2.2;
  }
  alpha = Math.max(0.05, alpha * 0.996);
}

function draw() {
  for (let i=0;i<edges.length;i++) {
    const el = edgeEls[i];
    if (el.style.display === 'none') continue;
    const a = byId.get(edges[i].source), b = byId.get(edges[i].target);
    const dx = b.x-a.x, dy = b.y-a.y, d = Math.sqrt(dx*dx+dy*dy)||1;
    el.setAttribute('x1', a.x); el.setAttribute('y1', a.y);
    el.setAttribute('x2', b.x - (dx/d)*(b.r+3));
    el.setAttribute('y2', b.y - (dy/d)*(b.r+3));
  }
  nodeEls.forEach((el,i) => {
    const n = nodes[i];
    if (el.g.style.display === 'none') return;
    el.g.setAttribute('transform', `translate(${n.x.toFixed(1)},${n.y.toFixed(1)})`);
  });
  gRoot.setAttribute('transform', `translate(${view.x},${view.y}) scale(${view.k})`);
}

function tick() { step(); draw(); requestAnimationFrame(tick); }

// ---- selection highlighting
function paintSelection() {
  const near = selected ? adj.get(selected.id) : null;
  nodeEls.forEach((el,i) => {
    const n = nodes[i];
    const on = !selected || n.id === selected.id || near.has(n.id);
    el.g.setAttribute('opacity', on ? 1 : 0.16);
    el.c.setAttribute('stroke', n.id === selected?.id ? '#fff'
      : (n.inferred ? (PALETTE[n.type]||'#888') : '#11141a'));
    el.c.setAttribute('stroke-width', n.id === selected?.id ? 2.5 : 1.5);
  });
  edgeEls.forEach((el,i) => {
    if (el.style.display === 'none') return;
    const e = edges[i];
    const on = !selected || e.source === selected.id || e.target === selected.id;
    el.setAttribute('stroke', on ? (selected ? '#7f8ca3' : '#39414f') : '#262c37');
    el.setAttribute('opacity', on ? (selected ? .95 : .55) : .12);
    el.setAttribute('stroke-width', on && selected ? 1.6 : 1);
  });
}

// ---- detail panel
const detail = document.getElementById('detail');
function esc(s){ return String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
function select(n) {
  selected = (selected && selected.id === n.id) ? null : n;
  paintSelection();
  if (!selected) { detail.innerHTML = '<div class="sub">Click a node to inspect its provenance.</div>'; return; }
  const p = n.provenance || {};
  let rows = '';
  for (const [k,v] of Object.entries(p)) {
    if (v === null || v === undefined || v === '' || (Array.isArray(v) && !v.length)) continue;
    let val;
    if (k === 'verify')        val = `<code>${esc(v)}</code>`;
    else if (Array.isArray(v)) val = v.map(x => `<span class="pill">${esc(x)}</span>`).join('');
    else if (k === 'status')   val = `<span class="pill ${v==='error'?'bad':'good'}">${esc(v)}</span>`;
    else                       val = esc(v);
    rows += `<dt>${esc(k)}</dt><dd>${val}</dd>`;
  }
  const outs = edges.filter(e => e.source === n.id)
    .map(e => `<span class="pill">${esc(e.type)} &rarr; ${esc((byId.get(e.target)||{}).label||'')}</span>`).join('');
  const ins = edges.filter(e => e.target === n.id)
    .map(e => `<span class="pill">${esc((byId.get(e.source)||{}).label||'')} &rarr; ${esc(e.type)}</span>`).join('');
  detail.innerHTML =
    `<div class="t" style="color:${PALETTE[n.type]||'#888'}">${esc(n.type)}`
    + (n.inferred ? ' <span class="pill">inferred</span>' : ' <span class="pill good">observed</span>') + `</div>`
    + `<div class="lbl">${esc(n.label)}</div>`
    + (n.detail && n.detail !== n.label ? `<div class="sub" style="margin-bottom:8px;color:#aeb8c8">${esc(n.detail)}</div>` : '')
    + (rows ? `<dl>${rows}</dl>` : '')
    + (outs ? `<h2>Outgoing</h2>${outs}` : '')
    + (ins  ? `<h2>Incoming</h2>${ins}`  : '');
}

// ---- tooltip
function showTip(ev, n) {
  tip.innerHTML = `<b>${esc(n.label)}</b><br><span style="color:#8b95a7">${esc(n.type)}`
    + (n.ts ? ' &middot; ' + esc(n.ts.replace('T',' ').slice(0,19)) : '')
    + ` &middot; degree ${n.deg}</span>`;
  tip.style.display = 'block'; positionTip(ev);
}
function positionTip(ev) {
  const r = svg.getBoundingClientRect();
  tip.style.left = Math.min(ev.clientX - r.left + 12, r.width - 350) + 'px';
  tip.style.top  = (ev.clientY - r.top + 12) + 'px';
}

// ---- interaction: pan, zoom, node drag
let panning = null, dragging = null;
svg.addEventListener('mousedown', ev => {
  if (ev.target.closest('.node')) return;
  panning = {x:ev.clientX, y:ev.clientY, vx:view.x, vy:view.y};
  svg.classList.add('dragging');
});
function startNodeDrag(ev, n) {
  ev.stopPropagation();
  dragging = n; n.fixed = true;
}
window.addEventListener('mousemove', ev => {
  if (panning) {
    view.x = panning.vx + (ev.clientX - panning.x);
    view.y = panning.vy + (ev.clientY - panning.y);
  } else if (dragging) {
    const r = svg.getBoundingClientRect();
    dragging.x = (ev.clientX - r.left - view.x) / view.k;
    dragging.y = (ev.clientY - r.top  - view.y) / view.k;
    alpha = Math.max(alpha, .35);
  }
});
window.addEventListener('mouseup', () => {
  panning = null; dragging = null; svg.classList.remove('dragging');
});
svg.addEventListener('dblclick', ev => {
  const g = ev.target.closest('.node');
  if (!g) return;
  const i = nodeEls.findIndex(e => e.g === g);
  if (i >= 0) { nodes[i].fixed = false; alpha = Math.max(alpha,.4); }
});
svg.addEventListener('wheel', ev => {
  ev.preventDefault();
  const r = svg.getBoundingClientRect();
  const mx = ev.clientX - r.left, my = ev.clientY - r.top;
  const f = ev.deltaY < 0 ? 1.12 : 1/1.12;
  const k = Math.max(0.15, Math.min(4.5, view.k * f));
  view.x = mx - (mx - view.x) * (k / view.k);
  view.y = my - (my - view.y) * (k / view.k);
  view.k = k;
}, {passive:false});
svg.addEventListener('click', ev => {
  if (ev.target.closest('.node')) return;
  selected = null;
  paintSelection();
  detail.innerHTML = '<div class="sub">Click a node to inspect its provenance.</div>';
});

function fit() {
  const live = nodes.filter(n => vis.get(n.id));
  if (!live.length) return;
  const xs = live.map(n=>n.x), ys = live.map(n=>n.y);
  const x0=Math.min(...xs)-60, x1=Math.max(...xs)+60;
  const y0=Math.min(...ys)-40, y1=Math.max(...ys)+40;
  const k = Math.min(W()/(x1-x0), H()/(y1-y0), 2.2);
  view.k = k;
  view.x = (W() - (x1+x0)*k)/2;
  view.y = (H() - (y1+y0)*k)/2;
}

// ---- sidebar
document.getElementById('sessid').textContent =
  (DATA.meta.session_id || '') + ' · ' + (DATA.meta.extraction || '');

const m = DATA.meta;
const started = m.started ? m.started.replace('T',' ').slice(0,16) : '?';
document.getElementById('stats').innerHTML = [
  ['nodes', nodes.length], ['edges', edges.length],
  ['records', m.records ?? '?'], ['started', started],
  ['repo', m.repo ? m.repo.split(/[\\/]/).pop() : 'none'],
  ['inferred', m.inferred_nodes ?? 0],
].map(([k,v]) => `<div class="sub">${k}</div><b>${esc(v)}</b>`).join('');

const typeCounts = {};
nodes.forEach(n => typeCounts[n.type] = (typeCounts[n.type]||0)+1);
const legend = document.getElementById('legend');
Object.keys(PALETTE).filter(t => typeCounts[t]).forEach(t => {
  const d = document.createElement('div');
  d.className = 'lg';
  d.innerHTML = `<span class="dot" style="background:${PALETTE[t]}"></span>
    <span>${t}</span><span class="n">${typeCounts[t]}</span>`;
  d.onclick = () => {
    hiddenTypes.has(t) ? hiddenTypes.delete(t) : hiddenTypes.add(t);
    d.classList.toggle('off', hiddenTypes.has(t));
    recomputeVisibility(); alpha = Math.max(alpha,.5);
  };
  legend.append(d);
});

const edgeCounts = {};
edges.forEach(e => edgeCounts[e.type] = (edgeCounts[e.type]||0)+1);
document.getElementById('elegend').innerHTML = Object.entries(edgeCounts)
  .sort((a,b)=>b[1]-a[1])
  .map(([t,c]) => `<div class="lg" style="cursor:default"><span>${t}</span><span class="n">${c}</span></div>`)
  .join('');

document.getElementById('q').addEventListener('input', ev => {
  query = ev.target.value.trim().toLowerCase();
  recomputeVisibility(); alpha = Math.max(alpha,.4);
});

const slider = document.getElementById('tslider');
slider.addEventListener('input', () => {
  tcut = slider.value / 100;
  const lbl = document.getElementById('timelabel');
  if (tcut >= 1) lbl.textContent = 'full session';
  else if (tmin) {
    const t = new Date(Date.parse(tmin) + (Date.parse(tmax)-Date.parse(tmin))*tcut);
    lbl.textContent = 'up to ' + t.toISOString().replace('T',' ').slice(0,19);
  }
  recomputeVisibility();
});

const bfuse = document.getElementById('bfuse');
bfuse.onclick = () => { fuseOnly = !fuseOnly; bfuse.classList.toggle('on', fuseOnly);
  recomputeVisibility(); alpha = 1; setTimeout(fit, 600); };
const binf = document.getElementById('binferred');
binf.onclick = () => { showInferred = !showInferred; binf.classList.toggle('on', !showInferred);
  recomputeVisibility(); alpha = Math.max(alpha,.5); };
document.getElementById('brelax').onclick = () => {
  nodes.forEach(n => n.fixed = false); alpha = 1;
};
document.getElementById('bfit').onclick = fit;

recomputeVisibility();
tick();
setTimeout(fit, 1400);
window.addEventListener('resize', () => { alpha = Math.max(alpha,.3); });
</script>
</body>
</html>
"""


def render(data: dict[str, Any]) -> str:
    meta = data.get("meta", {})
    title = f"Session Graph - {meta.get('session_id', 'unknown')}"
    return (
        TEMPLATE
        .replace("__TITLE__", title)
        .replace("__PALETTE__", json.dumps(PALETTE))
        .replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    )


if __name__ == "__main__":
    import sys
    from pathlib import Path

    src = Path(sys.argv[1] if len(sys.argv) > 1 else "session_graph.json")
    dst = Path(sys.argv[2] if len(sys.argv) > 2 else "session_graph.html")
    dst.write_text(render(json.loads(src.read_text(encoding="utf-8"))), encoding="utf-8")
    print(f"wrote {dst.resolve()}")
