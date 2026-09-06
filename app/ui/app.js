/* Madalena Intelligence — infrastructure graph view.
 *
 * Consumes GET /topology/graph?tenant=... and renders an evidence-backed,
 * navigable graph (Cytoscape.js). Nothing is hardcoded: node/edge kinds come
 * from the API. Filter chips, legend and colors are generated from the payload
 * so newly discovered asset types render without touching this file.
 *
 * Interactions:
 *   - pan (drag background), zoom (wheel / pinch), fit (button)
 *   - tap a node  -> side panel with identity, relations, evidence
 *   - tap an edge -> relation summary in the status bar
 *   - double-tap  -> collapse/expand direct children of a node
 *   - search box  -> find and center a node (reveals it if hidden)
 */
"use strict";

const ASSET_STYLE = {
  site:       { color: "#9aa0ab", size: 20, shape: "round-rectangle", labelFont: 10 },
  router:     { color: "#f06292", size: 28, shape: "ellipse", labelFont: 14 },
  olt:        { color: "#7aa2f7", size: 32, shape: "ellipse", labelFont: 14 },
  switch:     { color: "#3ddc85", size: 28, shape: "ellipse", labelFont: 14 },
  controller: { color: "#e6c74e", size: 28, shape: "ellipse", labelFont: 14 },
  ap:         { color: "#a370f7", size: 26, shape: "ellipse", labelFont: 13 },
  server:     { color: "#00d0b3", size: 30, shape: "square", labelFont: 14 },
  pon:        { color: "#4dd8e6", size: 20, shape: "round-rectangle", labelFont: 11 },
  onu:        { color: "#8a93a8", size: 16, shape: "ellipse", labelFont: 9 },
  device:     { color: "#c792ea", size: 26, shape: "ellipse", labelFont: 13 },
};
const FALLBACK_STYLE = { color: "#c792ea", size: 24, shape: "ellipse", labelFont: 12 };

const EDGE_LABEL = {
  pertence_a: "pertence a",
  contiene: "contém",
  conectado_a: "conectado a",
  uplink_de: "uplink de",
  alcanzable_via: "alcanzable vía",
  anuncia_rede: "anuncia red",
  observado_em: "observado em",
};

const HIDDEN = { type: new Set(), edge: new Set(), node: new Set() };

const state = {
  payload: null,
  cy: null,
  selId: null,
  nextId: 0,
};

// Testability hook (harmless; only used by automated UI validation via CDP).
window.__mni = { get state() { return state; } };

/* ---------- http ---------- */
async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.url}`);
  return r.json();
}

async function loadTenants() {
  const sel = document.getElementById("tenant");
  try {
    const tenants = await fetchJSON("/tenants");
    tenants.sort((a, b) => a.slug.localeCompare(b.slug));
    for (const t of tenants) {
      const o = document.createElement("option");
      o.value = t.slug; o.textContent = `${t.slug} (${t.name})`;
      sel.appendChild(o);
    }
  } catch (e) {
    sel.appendChild(Object.assign(document.createElement("option"), { value: "", text: "(sin tenants)" }));
  }
}

/* ---------- filters ---------- */
function toggleChip(chip) {
  chip.classList.toggle("on");
  const key = chip.dataset.pool === "type" ? "type" : "edge";
  const v = chip.dataset.v;
  if (chip.classList.contains("on")) HIDDEN[key].delete(v);
  else HIDDEN[key].add(v);
  refresh();
}

function buildChips(containerId, values, pool, labelFn) {
  const box = document.getElementById(containerId);
  box.innerHTML = "";
  for (const v of values || []) {
    const c = document.createElement("span");
    c.className = "chip on";
    c.dataset.v = v;
    c.dataset.pool = pool;
    c.textContent = labelFn ? labelFn(v) : v;
    c.onclick = () => toggleChip(c);
    box.appendChild(c);
  }
}

/* ---------- graph ---------- */
function styleByAsset(t) {
  return ASSET_STYLE[t] || FALLBACK_STYLE;
}

function cyStyle() {
  const s = [
    { selector: "node", style: { "background-color": "#5b6270", color: "#e4e8ef", "text-outline-width": 2, "text-outline-color": "#1b1d23" } },
    { selector: "edge", style: { "line-color": "#565d6d", width: 1.6, "curve-style": "bezier", "target-arrow-shape": "triangle", "arrow-scale": 0.7 } },
    { selector: "edge:selected", style: { "line-color": "#ffd740", width: 2.6 } },
    { selector: "node:selected", style: { "background-color": "#ffd740", "border-color": "#ffd740", "border-width": 2 } },
  ];
  for (const n of state.payload.nodes) {
    const t = n.asset_type;
    const st = styleByAsset(t);
    s.push({
      selector: `node[^asset_type = "${t}"]`,
      style: {
        "background-color": st.color,
        shape: st.shape,
        width: st.size, height: st.size,
        "font-size": st.labelFont,
      },
    });
  }
  // dashed edges for non-physical relations
  for (const k of new Set(state.payload.edges.map(e => e.kind))) {
    if (k === "conectado_a") continue;
    s.push({ selector: `edge[^kind = "${k}"]`, style: { "line-style": "dashed", "target-arrow-shape": "triangle" } });
  }
  return s;
}

function visibleNode(id) {
  return !HIDDEN.type.has(state.payload.nodes.find(n => n.id === id)?.asset_type)
    && !HIDDEN.node.has(id);
}

function buildCy() {
  const elements = [];
  for (const n of state.payload.nodes) {
    const el = { data: { id: n.id, label: n.label, asset_type: n.asset_type, node_type: n.node_type, parent_id: n.parent_id } };
    for (const [k, v] of Object.entries(n.meta || {})) el.data[k] = v;
    el.data.__first_seen = edgeTs(n.id, "first_seen");
    el.data.__last_seen = edgeTs(n.id, "last_seen");
    el.data.__child_count = state.payload.nodes.filter(x => x.parent_id === n.id).length;
    elements.push(el);
  }
  for (const e of state.payload.edges) {
    elements.push({ data: {
      id: e.id, source: e.source, target: e.target, kind: e.kind, status: e.status,
      label: EDGE_LABEL[e.kind] || e.kind,
      first_seen: e.first_seen, last_seen: e.last_seen, evidence: e.evidence,
      ...e.meta,
    }});
  }

  const container = document.getElementById("cy");
  container.innerHTML = "";
  // Root the radial layout on the OLT (or first device) when present.
  const roots = state.payload.nodes.filter(n => n.asset_type === "olt").map(n => n.id);
  state.cy = cytoscape({
    container, elements, style: cyStyle(),
    layout: {
      name: "concentric",
      minNodeSpacing: 22,
      levelWidth: () => 1.6,
      padding: 40,
      animate: false,
      radiusIncrement: 55,
      ...(roots.length ? { roots } : {}),
    },
    minZoom: 0.02, maxZoom: 8,
  });
  try { state.cy.layout({ name: "concentric", minNodeSpacing: 22, radiusIncrement: 55, padding: 40, animate: false, ...(roots.length ? { roots } : {}) }).run(); } catch (_) {}
  state.cy.fit();
  const cy = state.cy;
  cy.on("tap", "node", evt => selectNode(evt.target));
  cy.on("tap", "edge", evt => selectEdge(evt.target));
  cy.on("tap", evt => { if (evt.target === "background") clearSelection(); });
  cy.on("dbltap", "node", evt => toggleChildren(evt.target));
  refresh();
  status(
    `Grafo «${state.payload.tenant}»: ${state.payload.nodes.length} nodo(s) · ` +
    `${state.payload.edges.length} relação(es) · evidência persistida (sem hardcode). ` +
    `Duplo toque num nó com filhos colapsa/expande.`
  );
}

function edgeTs(nodeId, field) {
  let best = null;
  for (const e of state.payload.edges) {
    if (e.source === nodeId || e.target === nodeId) {
      const v = e[field];
      if (v && (!best || (field === "first_seen" ? v < best : v > best))) best = v;
    }
  }
  return best;
}

/* ---------- visibility / collapse ---------- */
function refresh() {
  const cy = state.cy;
  if (!cy) return;
  // apply style-level type visibility
  const byId = new Map(state.payload.nodes.map(n => [n.id, n]));
  cy.elements().style("display", "element");
  for (const n of state.payload.nodes) {
    if (HIDDEN.type.has(n.asset_type) || HIDDEN.node.has(n.id)) {
      const el = cy.getElementById(n.id);
      if (el) el.style("display", "none");
    }
  }
  for (const e of state.payload.edges) {
    const src = byId.get(e.source), tgt = byId.get(e.target);
    const typeOn = !HIDDEN.type.has(src?.asset_type) && !HIDDEN.type.has(tgt?.asset_type);
    const nodeOn = !HIDDEN.node.has(e.source) && !HIDDEN.node.has(e.target);
    const edgeOn = !HIDDEN.edge.has(e.kind);
    if (!(typeOn && nodeOn && edgeOn)) {
      const el = cy.getElementById(e.id);
      if (el) el.style("display", "none");
    }
  }
}

function toggleChildren(nodeEl) {
  const id = nodeEl.data("id");
  const children = state.payload.nodes.filter(n => n.parent_id === id);
  if (children.length === 0) return;
  const allHide = children.every(c => HIDDEN.node.has(c.id));
  for (const c of children) {
    if (allHide) HIDDEN.node.delete(c.id);
    else HIDDEN.node.add(c.id);
  }
  refresh();
  status(allHide
    ? `Expandido ${children.length} descendente(s) de «${nodeEl.data('label')}».`
    : `Colapsado ${children.length} descendente(s) de «${nodeEl.data('label')}».`);
}

/* ---------- selection ---------- */
function clearSelection() {
  state.selId = null;
  document.getElementById("side").classList.add("hidden");
}

function selectNode(el) {
  const data = el.data();
  state.selId = data.id;
  const n = state.payload.nodes.find(x => x.id === data.id);
  renderSide(n);
  status(`${n.label} · tipo ${n.asset_type} · últ. obs. ${shortTs(data.__last_seen)}`);
}

function selectEdge(el) {
  const d = el.data();
  const byId = new Map(state.payload.nodes.map(n => [n.id, n]));
  const src = byId.get(d.source), tgt = byId.get(d.target);
  status(
    `Relação «${EDGE_LABEL[d.kind] || d.kind}» · ${src ? src.label : d.source} → ${tgt ? tgt.label : d.target} · ` +
    `estado ${d.status} · evidênça: ${(d.evidence || []).join(", ")} · depuis ${shortTs(d.last_seen)}`
  );
}

/* ---------- side panel ---------- */
function renderSide(n) {
  const side = document.getElementById("side");
  side.classList.remove("hidden");
  document.getElementById("side-kind").textContent = `${n.node_type} · ${n.asset_type}`;
  document.getElementById("side-title").textContent = n.label;

  const dl = document.getElementById("side-dl");
  dl.innerHTML = "";
  const m = n.meta || {};
  const rows = [
    ["ID", n.id],
    ["Tipo", n.asset_type],
    ["Fabricante", m.vendor || "—"],
    ["Modelo", m.model || "—"],
  ];
  if (m.serial) rows.push(["Serial", m.serial]);
  if (m.status) rows.push(["Status", m.status]);
  if (m.profile_name) rows.push(["Perfil", m.profile_name]);
  if (m.pon) rows.push(["PON", m.pon]);
  if (m.ont_id) rows.push(["ONT", m.ont_id]);
  if (m.enabled !== undefined) rows.push(["Habilitado", m.enabled ? "sí" : "no"]);
  if (m.last_identity) rows.push(["Identidad", m.last_identity]);
  if (m.last_version) rows.push(["Versión", m.last_version]);
  rows.push(["Primera obs.", shortTs(edgeTs(n.id, "first_seen"))]);
  rows.push(["Última obs.", shortTs(edgeTs(n.id, "last_seen"))]);
  for (const [k, v] of rows) {
    const dt = document.createElement("dt"); dt.textContent = k;
    const dd = document.createElement("dd"); dd.textContent = String(v || "—");
    dl.appendChild(dt); dl.appendChild(dd);
  }

  const relList = document.getElementById("side-rels");
  relList.innerHTML = "";
  const byId = new Map(state.payload.nodes.map(x => [x.id, x]));
  const rels = state.payload.edges
    .filter(e => e.source === n.id || e.target === n.id)
    .sort((a, b) => (b.last_seen || "").localeCompare(a.last_seen || ""));
  if (rels.length === 0) {
    relList.innerHTML = "<li>Sin relações com evidência.</li>";
  } else {
    for (const e of rels) {
      const isOut = e.source === n.id;
      const other = byId.get(isOut ? e.target : e.source);
      const li = document.createElement("li");
      const s1 = document.createElement("span"); s1.className = "rel-kind";
      s1.textContent = EDGE_LABEL[e.kind] || e.kind;
      const s2 = document.createElement("span"); s2.className = "rel-target";
      s2.textContent = ` ${isOut ? "→" : "←"} ${other ? other.label : (isOut ? e.target : e.source)}`;
      const s3 = document.createElement("span"); s3.className = "rel-ts";
      s3.textContent = ` · ${shortTs(e.last_seen)}`;
      li.append(s1, s2, s3);
      relList.appendChild(li);
    }
  }

  const ev = document.getElementById("side-evid");
  ev.innerHTML = "";
  for (const e of rels) {
    const li = document.createElement("li");
    li.textContent = `${e.id} → ${(e.evidence || []).join(", ") || "evidência não registrada"}`;
    ev.appendChild(li);
  }
  if (rels.length === 0) ev.innerHTML = "<li>—</li>";

  document.getElementById("side-counts").textContent =
    `${rels.length} relação(es) · ${state.payload.nodes.filter(x => x.parent_id === n.id).length} hijo(s)`;
}

/* ---------- legend ---------- */
function buildLegend() {
  const list = document.getElementById("legend-list");
  list.innerHTML = "";
  for (const t of (state.payload.asset_types || [])) {
    const st = styleByAsset(t);
    const li = document.createElement("li");
    const sw = document.createElement("span");
    sw.className = "sw"; sw.style.background = st.color;
    li.append(sw, document.createTextNode(` ${t}`));
    list.appendChild(li);
  }
  if ((state.payload.asset_types || []).length === 0) list.innerHTML = "<li>sem nós</li>";
}

/* ---------- utils ---------- */
function shortTs(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }); }
  catch (_) { return iso; }
}
function status(msg) { document.getElementById("statusbar").textContent = msg; }
function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/* ---------- search ---------- */
function reveal(id) {
  // Unhide the target and every ancestor along its parent chain.
  const byId = new Map(state.payload.nodes.map(n => [n.id, n]));
  let cur = id;
  while (cur) {
    HIDDEN.node.delete(cur);
    const n = byId.get(cur);
    cur = n && n.parent_id ? n.parent_id : null;
  }
}
function doSearch(q) {
  const needle = (q || "").trim().toLowerCase();
  const cy = state.cy;
  if (!cy || !needle) return;
  let hit = null;
  for (const n of state.payload.nodes) {
    if ((n.label || "").toLowerCase().includes(needle)) { hit = n; break; }
    if (n.meta && n.meta.serial && String(n.meta.serial).toLowerCase().includes(needle)) { hit = n; break; }
  }
  if (!hit) { status(`Sem resultados para «${q}»`); return; }
  reveal(hit.id);
  refresh();
  const el = cy.getElementById(hit.id);
  selectNode(el);
  try { cy.fit([el], 60); } catch (_) {}
  if (el.style("display") === "none") el.style("display", "element"); // force show the target
  status(`Equipamento encontrado: ${hit.label}`);
}

/* ---------- bootstrap ---------- */
function init() {
  document.getElementById("tenant").onchange = loadGraph;
  document.getElementById("search").oninput = debounce(ev => doSearch(ev.target.value), 180);
  document.getElementById("fit").onclick = () => state.cy && state.cy.fit();
  document.getElementById("side-close").onclick = clearSelection;
  document.addEventListener("keydown", ev => { if (ev.key === "Escape") clearSelection(); });
  loadTenants().then(() => {
    if (document.getElementById("tenant").options.length > 0) loadGraph();
    else status("Sem tenants disponíveis.");
  });
}

async function loadGraph() {
  const tenant = document.getElementById("tenant").value;
  if (!tenant) return;
  status(`Carregando grafo de «${tenant}»…`);
  document.getElementById("side").classList.add("hidden");
  HIDDEN.type.clear(); HIDDEN.edge.clear(); HIDDEN.node.clear();
  state.payload = null; state.selId = null;
  try {
    const data = await fetchJSON(`/topology/graph?tenant=${encodeURIComponent(tenant)}`);
    state.payload = data;
    buildChips("type-filters", data.asset_types || [], "type");
    buildChips("edge-filters", data.relation_kinds || [], "edge", k => EDGE_LABEL[k] || k);
    buildLegend();
    buildCy();
  } catch (e) {
    status(`Erro carregando grafo: ${e.message}`);
  }
}

document.addEventListener("DOMContentLoaded", init);