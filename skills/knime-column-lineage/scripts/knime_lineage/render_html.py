"""Renders a lineage subgraph as a self-contained interactive HTML page.

Nodes are HTML divs laid out in dataflow columns; edges are SVG paths
overlaid on the same container. Clicking any node opens a detail panel
showing its full action text, evidence, code/SQL, and settings.
No external dependencies — works offline.
"""

from __future__ import annotations

import json
from xml.sax.saxutils import escape

from .models import LineageSubgraph, to_serializable

# ---------------------------------------------------------------------------
# CSS + JS template (injected inline so the file is fully self-contained)
# ---------------------------------------------------------------------------

_CSS = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#f1f5f9;--surface:#ffffff;--surface2:#f8fafc;
  --border:#e2e8f0;--border2:#cbd5e1;
  --text:#0f172a;--muted:#64748b;--faint:#94a3b8;
  --accent:#3b82f6;--accent-bg:#eff6ff;
  --traced:#10b981;--traced-bg:#ecfdf5;
  --inferred:#f59e0b;--inferred-bg:#fffbeb;
  --fv:#b45309;--fv-bg:#fef3c7;
  --edge:#94a3b8;--edge-inferred:#f59e0b;
  --node-w:220px;--node-h:84px;--col-gap:96px;--row-gap:20px;
  --radius:8px;--shadow:0 1px 3px rgba(0,0,0,.08),0 1px 2px rgba(0,0,0,.06);
}
@media(prefers-color-scheme:dark){
  :root{
    --bg:#0f172a;--surface:#1e293b;--surface2:#1e293b;
    --border:#334155;--border2:#475569;
    --text:#f1f5f9;--muted:#94a3b8;--faint:#64748b;
    --accent:#60a5fa;--accent-bg:#1e3a5f;
    --traced:#34d399;--traced-bg:#052e16;
    --inferred:#fbbf24;--inferred-bg:#451a03;
    --fv:#fcd34d;--fv-bg:#292524;
    --edge:#475569;--edge-inferred:#d97706;
  }
}
body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;font-size:14px;line-height:1.5}
a{color:var(--accent)}

/* ---- layout ---- */
#app{display:flex;flex-direction:column;height:100vh;overflow:hidden}
#header{padding:14px 20px 12px;background:var(--surface);border-bottom:1px solid var(--border);flex-shrink:0}
#header h1{font-size:16px;font-weight:700;color:var(--text)}
#header .sub{font-size:12px;color:var(--muted);margin-top:2px}
#legend{display:flex;gap:18px;margin-top:10px;flex-wrap:wrap}
.leg{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--muted)}
.leg-line{width:22px;height:2px;background:var(--edge)}
.leg-line.dash{background:repeating-linear-gradient(90deg,var(--edge-inferred) 0 6px,transparent 6px 10px)}
.leg-dot{width:10px;height:10px;border-radius:2px}
.leg-dot.traced{background:var(--traced-bg);border:1.5px solid var(--traced)}
.leg-dot.inferred{background:var(--inferred-bg);border:1.5px dashed var(--inferred)}
.leg-dot.fv{background:var(--fv-bg);border:1.5px solid var(--fv)}

#body{display:flex;flex:1;overflow:hidden}
#graph-wrap{flex:1;overflow:auto;padding:24px;position:relative}
#graph-container{position:relative;/* sized by JS */}
#edge-svg{position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;overflow:visible}

/* ---- nodes ---- */
.node{
  position:absolute;width:var(--node-w);background:var(--surface);
  border:1.5px solid var(--border2);border-radius:var(--radius);
  box-shadow:var(--shadow);cursor:pointer;transition:box-shadow .15s,border-color .15s;
  overflow:hidden;
}
.node:hover{box-shadow:0 4px 12px rgba(0,0,0,.12);border-color:var(--accent)}
.node.selected{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-bg)}
.node.traced{border-left:3px solid var(--traced)}
.node.inferred{border-left:3px solid var(--inferred);border-style:dashed dashed dashed solid}
.node-head{padding:8px 10px 6px;border-bottom:1px solid var(--border)}
.node-name{font-size:12px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.node-badge{display:inline-block;font-size:9px;font-weight:600;padding:1px 5px;border-radius:99px;margin-top:3px}
.badge-traced{background:var(--traced-bg);color:var(--traced)}
.badge-inferred{background:var(--inferred-bg);color:var(--inferred)}
.node-action{padding:6px 10px;font-size:11px;color:var(--muted);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}

/* ---- passthrough badge ---- */
.pt-badge{
  position:absolute;background:var(--surface);border:1px solid var(--border2);
  border-radius:99px;font-size:10px;color:var(--faint);padding:1px 8px;
  white-space:nowrap;transform:translate(-50%,-50%);pointer-events:none;
}

/* ---- flow-variable chips ---- */
.fv-chip{
  position:absolute;background:var(--fv-bg);border:1px solid var(--fv);
  border-radius:4px;font-size:10px;color:var(--fv);padding:2px 7px;
  white-space:nowrap;max-width:200px;overflow:hidden;text-overflow:ellipsis;
  pointer-events:none;
}

/* ---- detail panel ---- */
#detail{
  width:340px;flex-shrink:0;background:var(--surface);border-left:1px solid var(--border);
  overflow-y:auto;display:flex;flex-direction:column;
}
#detail.hidden{display:none}
#detail-head{padding:14px 16px 10px;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--surface);z-index:1}
#detail-head h2{font-size:14px;font-weight:700}
#detail-close{float:right;cursor:pointer;color:var(--muted);font-size:18px;line-height:1;margin-top:-2px}
#detail-close:hover{color:var(--text)}
#detail-body{padding:14px 16px;display:flex;flex-direction:column;gap:14px}
.detail-section h3{font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
.detail-section .value{font-size:13px;color:var(--text)}
.detail-section .value.code{font-family:'SF Mono','Fira Mono',monospace;font-size:12px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;white-space:pre-wrap;word-break:break-all;max-height:240px;overflow-y:auto}
.evidence-pill{display:inline-block;padding:2px 10px;border-radius:99px;font-size:11px;font-weight:600}
.ep-traced{background:var(--traced-bg);color:var(--traced)}
.ep-inferred{background:var(--inferred-bg);color:var(--inferred)}
.detail-section table{width:100%;border-collapse:collapse;font-size:12px}
.detail-section td{padding:3px 6px;border-bottom:1px solid var(--border);vertical-align:top}
.detail-section td:first-child{color:var(--muted);width:42%;word-break:break-all}
.trunc-note{background:var(--inferred-bg);border:1px solid var(--inferred);border-radius:6px;padding:8px 10px;font-size:12px;color:var(--text);margin:12px 0}
"""

_JS = r"""
const DATA = /*DATA_PLACEHOLDER*/;

const NODE_W = 220, NODE_H = 84, COL_GAP = 96, ROW_GAP = 20, MARGIN = 24;

function orderNodes(nodes, edges) {
  const ids = nodes.map(n => n.node_id);
  const incoming = Object.fromEntries(ids.map(id => [id, []]));
  const outgoing  = Object.fromEntries(ids.map(id => [id, []]));
  for (const e of edges) {
    if (e.source_node in incoming && e.dest_node in incoming) {
      incoming[e.dest_node].push(e.source_node);
      outgoing[e.source_node].push(e.dest_node);
    }
  }
  const depth = Object.fromEntries(ids.map(id => [id, 0]));
  for (let i = 0; i < ids.length; i++) {
    let changed = false;
    for (const id of ids) {
      for (const p of incoming[id]) {
        if (depth[p] + 1 > depth[id]) { depth[id] = depth[p] + 1; changed = true; }
      }
    }
    if (!changed) break;
  }
  const cols = {};
  for (const id of ids) { (cols[depth[id]] = cols[depth[id]] || []).push(id); }
  return Object.keys(cols).sort((a,b)=>+a - +b).map(d => cols[d]);
}

function computePos(columns) {
  const pos = {};
  const tallest = Math.max(...columns.map(c => c.length));
  const bodyH = tallest * NODE_H + (tallest - 1) * ROW_GAP;
  columns.forEach((col, c) => {
    const x = MARGIN + c * (NODE_W + COL_GAP);
    const colH = col.length * NODE_H + (col.length - 1) * ROW_GAP;
    const y0 = MARGIN + (bodyH - colH) / 2;
    col.forEach((id, r) => { pos[id] = { x, y: y0 + r * (NODE_H + ROW_GAP) }; });
  });
  const totalW = MARGIN * 2 + columns.length * NODE_W + Math.max(columns.length - 1, 0) * COL_GAP;
  const totalH = MARGIN * 2 + bodyH;
  return { pos, totalW, totalH };
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function truncate(s, n) {
  s = String(s || '').replace(/\s+/g,' ').trim();
  return s.length <= n ? s : s.slice(0, n-1) + '…';
}

function renderGraph() {
  const { nodes, edges, flow_variable_influences = [], truncated, truncation_note } = DATA;
  const byId = Object.fromEntries(nodes.map(n => [n.node_id, n]));
  const columns = orderNodes(nodes, edges);
  const { pos, totalW, totalH } = computePos(columns);

  const container = document.getElementById('graph-container');
  container.style.width  = totalW + 'px';
  container.style.height = (totalH + 60) + 'px';

  // truncation notice
  if (truncated && truncation_note) {
    const d = document.createElement('div');
    d.className = 'trunc-note';
    d.textContent = '⚠ ' + truncation_note;
    d.style.cssText = `position:absolute;top:${totalH+8}px;left:${MARGIN}px;right:${MARGIN}px`;
    container.appendChild(d);
  }

  // flow variable map
  const fvByNode = {};
  for (const fv of flow_variable_influences) {
    (fvByNode[fv.controlling_node_id] = fvByNode[fv.controlling_node_id] || []).push(fv);
  }

  // SVG edges
  const svg = document.getElementById('edge-svg');
  svg.setAttribute('viewBox', `0 0 ${totalW} ${totalH + 60}`);
  let edgeSvg = `<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10z" fill="var(--edge)"/></marker><marker id="arr-i" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10z" fill="var(--edge-inferred)"/></marker></defs>`;

  // passthrough badge positions (collect to avoid DOM timing issues)
  const ptBadges = [];

  for (const edge of edges) {
    const s = pos[edge.source_node], d = pos[edge.dest_node];
    if (!s || !d) continue;
    const x1 = s.x + NODE_W, y1 = s.y + NODE_H / 2;
    const x2 = d.x,          y2 = d.y + NODE_H / 2;
    const dest = byId[edge.dest_node];
    const inferred = dest && dest.evidence === 'inferred_from_code';
    const color = inferred ? 'var(--edge-inferred)' : 'var(--edge)';
    const dash  = inferred ? 'stroke-dasharray="6 4"' : '';
    const mid   = (x1 + x2) / 2;
    const path  = `M${x1} ${y1} C${mid} ${y1},${mid} ${y2},${x2} ${y2}`;
    const marker = inferred ? 'url(#arr-i)' : 'url(#arr)';
    edgeSvg += `<path d="${path}" fill="none" stroke="${color}" stroke-width="1.6" ${dash} marker-end="${marker}"/>`;

    if (edge.passthrough_count > 0) {
      ptBadges.push({ x: mid, y: (y1 + y2) / 2, label: `+${edge.passthrough_count} unchanged` });
    }
  }

  // flow variable connectors (dotted lines to FV chips above)
  const FV_CHIP_H = 26, FV_CHIP_Y_BASE = 10;
  for (const [nodeId, fvList] of Object.entries(fvByNode)) {
    const p = pos[nodeId];
    if (!p) continue;
    fvList.forEach((_, i) => {
      const cx = p.x + NODE_W / 2, cy = p.y;
      const ty = FV_CHIP_Y_BASE + i * (FV_CHIP_H + 4) + FV_CHIP_H;
      edgeSvg += `<line x1="${cx}" y1="${cy}" x2="${cx}" y2="${ty}" stroke="var(--fv)" stroke-width="1" stroke-dasharray="2 3"/>`;
    });
  }

  svg.innerHTML = edgeSvg;

  // passthrough badges (DOM elements on top of SVG)
  for (const { x, y, label } of ptBadges) {
    const el = document.createElement('div');
    el.className = 'pt-badge';
    el.textContent = label;
    el.style.left = x + 'px';
    el.style.top  = y + 'px';
    container.appendChild(el);
  }

  // flow variable chips (above graph)
  const fvOffset = Object.keys(fvByNode).length > 0 ? 0 : 0;
  for (const [nodeId, fvList] of Object.entries(fvByNode)) {
    const p = pos[nodeId];
    if (!p) continue;
    fvList.forEach((fv, i) => {
      const chip = document.createElement('div');
      chip.className = 'fv-chip';
      chip.textContent = '⚙ ' + fv.variable_name + ' → ' + fv.setting_path;
      chip.title = (fv.defining_node_name ? 'Defined by: ' + fv.defining_node_name : '') +
                   '\nControls: ' + fv.controlling_node_name;
      chip.style.left = p.x + 'px';
      chip.style.top  = (FV_CHIP_Y_BASE + i * (FV_CHIP_H + 4)) + 'px';
      chip.style.width = NODE_W + 'px';
      container.appendChild(chip);
    });
  }

  // node divs
  for (const node of nodes) {
    const p = pos[node.node_id];
    if (!p) continue;
    const inferred = node.evidence === 'inferred_from_code';
    const div = document.createElement('div');
    div.className = 'node ' + (inferred ? 'inferred' : 'traced');
    div.dataset.id = node.node_id;
    div.style.left = p.x + 'px';
    div.style.top  = p.y + 'px';

    const badge = inferred
      ? '<span class="node-badge badge-inferred">inferred</span>'
      : '<span class="node-badge badge-traced">traced</span>';

    div.innerHTML = `
      <div class="node-head">
        <div class="node-name" title="${esc(node.node_name)}">${esc(truncate(node.node_name, 28))}</div>
        ${badge}
      </div>
      <div class="node-action" title="${esc(node.action)}">${esc(node.action)}</div>`;

    div.addEventListener('click', () => showDetail(node, div));
    container.appendChild(div);
  }
}

let selectedDiv = null;

function showDetail(node, div) {
  if (selectedDiv) selectedDiv.classList.remove('selected');
  div.classList.add('selected');
  selectedDiv = div;

  const panel = document.getElementById('detail');
  panel.classList.remove('hidden');

  document.getElementById('detail-head').querySelector('h2').textContent = node.node_name;

  const body = document.getElementById('detail-body');
  body.innerHTML = '';

  // evidence
  addSection(body, 'Evidence', () => {
    const ev = node.evidence;
    const cls = ev === 'inferred_from_code' ? 'ep-inferred' : 'ep-traced';
    const label = ev === 'inferred_from_code' ? 'Inferred from code'
                : ev === 'traced_from_spec'   ? 'Traced from spec'
                :                               'Traced from settings';
    return `<span class="evidence-pill ${cls}">${label}</span>`;
  });

  // action
  addSection(body, 'Action', () => `<div class="value">${esc(node.action)}</div>`);

  // code
  if (node.code) {
    addSection(body, 'Code / Expression', () => `<div class="value code">${esc(node.code)}</div>`);
  }

  // join candidates
  if (node.join_candidates && node.join_candidates.length) {
    addSection(body, 'Join sides', () => {
      const rows = node.join_candidates.map(c =>
        `<tr><td>${esc(c.side)}</td><td>${c.kept ? '✓ kept' : '— dropped'}</td></tr>`
      ).join('');
      return `<table><tr><td><b>Side</b></td><td><b>Status</b></td></tr>${rows}</table>`;
    });
  }

  // settings (flatten top-level keys)
  const settingsKeys = Object.keys(node.settings || {}).filter(k => k !== 'raw_model');
  if (settingsKeys.length) {
    addSection(body, 'Relevant settings', () => {
      const rows = settingsKeys.map(k => {
        const v = node.settings[k];
        const display = typeof v === 'object' ? JSON.stringify(v, null, 2) : String(v);
        return `<tr><td>${esc(k)}</td><td><code style="font-size:11px;word-break:break-all">${esc(display)}</code></td></tr>`;
      }).join('');
      return `<table>${rows}</table>`;
    });
  }

  // node id
  addSection(body, 'Node ID', () => `<div class="value" style="font-family:monospace;font-size:12px">${esc(node.node_id)}</div>`);
}

function addSection(parent, title, renderFn) {
  const sec = document.createElement('div');
  sec.className = 'detail-section';
  sec.innerHTML = `<h3>${title}</h3>`;
  sec.insertAdjacentHTML('beforeend', renderFn());
  parent.appendChild(sec);
}

function init() {
  // header
  document.getElementById('col-name').textContent = DATA.column_name;
  document.getElementById('wf-name').textContent  = DATA.workflow_name;

  if (DATA.truncated && DATA.truncation_note) {
    const note = document.createElement('div');
    note.style.cssText = 'margin-top:6px;font-size:11px;color:var(--inferred)';
    note.textContent = '⚠ ' + DATA.truncation_note;
    document.querySelector('#header .sub').after(note);
  }

  // close panel
  document.getElementById('detail-close').addEventListener('click', () => {
    document.getElementById('detail').classList.add('hidden');
    if (selectedDiv) { selectedDiv.classList.remove('selected'); selectedDiv = null; }
  });

  renderGraph();
}

document.addEventListener('DOMContentLoaded', init);
"""

# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lineage: {col_name}</title>
<style>{css}</style>
</head>
<body>
<div id="app">
  <div id="header">
    <h1>Lineage of &#8220;<span id="col-name"></span>&#8221;</h1>
    <div class="sub" id="wf-name"></div>
    <div id="legend">
      <span class="leg"><span class="leg-dot traced"></span> Traced from settings / spec</span>
      <span class="leg"><span class="leg-dot inferred"></span> Inferred from code</span>
      <span class="leg"><span class="leg-line"></span> Dataflow edge</span>
      <span class="leg"><span class="leg-line dash"></span> Inferred hop</span>
      <span class="leg"><span class="leg-dot fv"></span> Flow variable</span>
    </div>
  </div>
  <div id="body">
    <div id="graph-wrap">
      <div id="graph-container">
        <svg id="edge-svg"></svg>
      </div>
    </div>
    <div id="detail" class="hidden">
      <div id="detail-head">
        <span id="detail-close">&#x2715;</span>
        <h2></h2>
      </div>
      <div id="detail-body"></div>
    </div>
  </div>
</div>
<script>{js}</script>
</body>
</html>
"""


def render_lineage_html(subgraph: LineageSubgraph) -> str:
    """Return a complete self-contained HTML page for this lineage subgraph."""
    try:
        return _render(subgraph)
    except Exception:  # noqa: BLE001 - must never crash a lineage answer
        return _fallback(subgraph)


def _render(subgraph: LineageSubgraph) -> str:
    data_json = json.dumps(to_serializable(subgraph), ensure_ascii=False)
    js = _JS.replace("/*DATA_PLACEHOLDER*/", data_json, 1)
    return _HTML_TEMPLATE.format(
        col_name=escape(subgraph.column_name),
        css=_CSS,
        js=js,
    )


def _fallback(subgraph: LineageSubgraph) -> str:
    col = escape(subgraph.column_name)
    wf  = escape(subgraph.workflow_name)
    return (
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'>"
        f"<title>Lineage: {col}</title></head><body>"
        f"<h2>Lineage of &ldquo;{col}&rdquo; &mdash; {wf}</h2>"
        f"<p>Diagram could not be rendered. "
        f"{len(subgraph.nodes)} nodes in path.</p></body></html>"
    )
