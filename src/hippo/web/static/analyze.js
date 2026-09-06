// The Analyze page: draws the graph picture and runs the "tweak & simulate" panel.
//
// Everything the page needs is in the <script id="analyze-data"> JSON block:
//   question, resultId | traceKey, goldIds, subgraph {nodes, edges}, settings, baselinePassages.
// Simulate collects the panel into an "overrides" object, POSTs /api/simulate, and renders the diff.

(() => {
  const dataEl = document.getElementById('analyze-data');
  if (!dataEl) return;
  const data = JSON.parse(dataEl.textContent);
  const $ = (id) => document.getElementById(id);

  // ------------------------------------------------------------ graph picture
  let cy = null;
  function drawGraph(subgraph) {
    const container = $('graph');
    if (!container || typeof cytoscape === 'undefined') return;
    const maxScore = Math.max(0.0001, ...subgraph.nodes.map((n) => n.score || 0));
    const elements = [
      ...subgraph.nodes.map((n) => ({
        data: { ...n, size: 18 + 42 * Math.sqrt((n.score || 0) / maxScore), gold: data.goldIds.includes(n.id) },
      })),
      ...subgraph.edges.map((e, i) => ({ data: { id: `e${i}`, ...e, label: (e.kinds || []).join('+') } })),
    ];
    if (cy) cy.destroy();
    cy = cytoscape({
      container,
      elements,
      style: [
        { selector: 'node', style: { label: 'data(label)', 'font-size': 9, 'text-wrap': 'ellipsis', 'text-max-width': 90,
            'text-valign': 'bottom', 'text-margin-y': 3, width: 'data(size)', height: 'data(size)',
            'background-color': '#c7cbe8', 'border-width': 1, 'border-color': '#9aa0c9', color: '#1e2430' } },
        { selector: 'node[kind = "passage"]', style: { shape: 'round-rectangle', 'background-color': '#f3d9a4', 'border-color': '#d9b25f' } },
        { selector: 'node[?is_seed]', style: { 'border-width': 4, 'border-color': '#4f5bd5' } },
        { selector: 'node[?gold]', style: { 'border-width': 4, 'border-color': '#1f9d55' } },
        { selector: 'node[?is_seed][?gold]', style: { 'border-style': 'double', 'border-width': 6 } },
        { selector: 'edge', style: { width: 'mapData(weight, 0, 3, 1, 5)', 'line-color': '#d4d2cb', 'curve-style': 'haystack', opacity: 0.9 } },
        { selector: 'edge[kinds *= "synonym"]', style: { 'line-color': '#9ad0b5', 'line-style': 'dashed' } },
        { selector: 'edge[kinds *= "tuned"]', style: { 'line-color': '#e0a83a' } },
        { selector: 'node:selected', style: { 'background-color': '#4f5bd5', color: '#1e2430' } },
      ],
      layout: { name: 'cose', animate: false, nodeRepulsion: 9000, idealEdgeLength: 70, padding: 20 },
      wheelSensitivity: 0.2,
    });
    cy.on('tap', 'node', async (evt) => showNode(evt.target.data()));
    fillNodeSelects(subgraph.nodes);
  }

  async function showNode(node) {
    const side = $('graph-side');
    side.innerHTML = `<h4>${escapeHtml(node.label)}</h4><p class="small">${node.kind}${node.is_seed ? ' · seed' : ''}${node.score ? ` · activation ${Number(node.score).toFixed(4)}` : ''}${node.seed_weight ? ` · seed weight ${Number(node.seed_weight).toFixed(3)}` : ''}</p><p class="small">loading neighbours…</p>`;
    try {
      const hood = await hippo.api('GET', `/api/graph/neighborhood?node_id=${encodeURIComponent(node.id)}&depth=1&limit=40`);
      const others = hood.edges
        .map((e) => ({ other: e.source === node.id ? e.target : e.source, weight: e.weight, kinds: e.kinds }))
        .sort((a, b) => b.weight - a.weight);
      const names = Object.fromEntries(hood.nodes.map((n) => [n.id, n]));
      side.innerHTML = `<h4>${escapeHtml(node.label)}</h4><p class="small">${node.kind}${node.is_seed ? ' · seed' : ''}</p>
        <p class="small"><b>${others.length} neighbours</b> (edge weight · kind)</p>
        <ul class="small">${others.slice(0, 40).map((o) => `<li>${escapeHtml(names[o.other]?.label || o.other)} <span class="muted">· ${Number(o.weight).toFixed(2)} · ${(o.kinds || []).join('+') || '?'}</span></li>`).join('')}</ul>`;
    } catch (_) { side.innerHTML += '<p class="small">could not load neighbours</p>'; }
  }

  // ---------------------------------------------------------- node pickers
  const knownNodes = new Map(); // id -> {label, kind}
  function fillNodeSelects(nodes) {
    nodes.forEach((n) => knownNodes.set(n.id, { label: n.label, kind: n.kind }));
    for (const id of ['edge-a', 'edge-b']) {
      const select = $(id);
      const current = select.value;
      select.innerHTML = [...knownNodes.entries()]
        .sort((a, b) => a[1].label.localeCompare(b[1].label))
        .map(([nid, n]) => `<option value="${nid}">${escapeHtml(n.label)} (${n.kind === 'passage' ? 'passage' : 'entity'})</option>`).join('');
      if (current) select.value = current;
    }
  }

  const entityLookup = new Map(); // label -> id, filled by the datalist search
  let searchTimer = null;
  async function searchEntities(text) {
    if (!text || text.length < 2) return;
    const found = await hippo.api('GET', `/api/entities?q=${encodeURIComponent(text)}&limit=15`);
    const list = $('entity-options');
    list.innerHTML = found.map((e) => `<option value="${escapeHtml(e.name)}">${e.passage_count} passages</option>`).join('');
    found.forEach((e) => entityLookup.set(e.name, e.id));
  }
  for (const id of ['boost-search', 'edge-search']) {
    $(id).addEventListener('input', (e) => { clearTimeout(searchTimer); searchTimer = setTimeout(() => searchEntities(e.target.value.trim()), 200); });
  }

  // ------------------------------------------------------------- edit lists
  const extraBoosts = new Map(); // entity id -> {name, boost}
  const edgeEdits = []; // {a, b, weight, aLabel, bLabel}

  $('boost-add').addEventListener('click', () => {
    const name = $('boost-search').value.trim();
    const id = entityLookup.get(name);
    if (!id) { hippo.toast('Pick an entity from the suggestions first', 'bad'); return; }
    extraBoosts.set(id, { name, boost: Number($('boost-value').value) });
    renderEdits();
  });
  $('edge-search-add').addEventListener('click', () => {
    const name = $('edge-search').value.trim();
    const id = entityLookup.get(name);
    if (!id) { hippo.toast('Pick an entity from the suggestions first', 'bad'); return; }
    fillNodeSelects([{ id, label: name, kind: 'entity' }]);
    $('edge-b').value = id;
    hippo.toast(`Added "${name}" to the edge lists`, 'ok');
  });
  $('edge-add').addEventListener('click', () => {
    const a = $('edge-a').value, b = $('edge-b').value;
    if (!a || !b || a === b) { hippo.toast('Pick two different nodes', 'bad'); return; }
    edgeEdits.push({ a, b, weight: Number($('edge-weight').value), aLabel: knownNodes.get(a)?.label || a, bLabel: knownNodes.get(b)?.label || b });
    renderEdits();
  });
  function renderEdits() {
    $('extra-boosts').innerHTML = [...extraBoosts.entries()].map(([id, b]) => `<li>boost <b>${escapeHtml(b.name)}</b> × ${b.boost} <span class="x" data-remove-boost="${id}">✕</span></li>`).join('');
    $('edge-edits').innerHTML = edgeEdits.map((e, i) => `<li><b>${escapeHtml(e.aLabel)}</b> — <b>${escapeHtml(e.bLabel)}</b> weight ${e.weight} <span class="x" data-remove-edge="${i}">✕</span></li>`).join('');
  }
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-remove-boost]');
    if (b) { extraBoosts.delete(b.dataset.removeBoost); renderEdits(); }
    const ed = e.target.closest('[data-remove-edge]');
    if (ed) { edgeEdits.splice(Number(ed.dataset.removeEdge), 1); renderEdits(); }
  });

  // --------------------------------------------------------- collect & run
  function collectOverrides() {
    const settings = {};
    for (const key of ['linking_top_k', 'passage_node_weight', 'damping']) {
      const el = $(`ov-${key}`);
      if (Number(el.value) !== Number(el.dataset.original)) settings[key] = Number(el.value);
    }
    const spec = $('ov-node_specificity');
    if ((spec.checked ? '1' : '0') !== spec.dataset.original) settings.node_specificity = spec.checked;

    const force_include = [], force_exclude = [];
    document.querySelectorAll('.fact-mode').forEach((sel) => {
      if (sel.value === 'in') force_include.push(sel.dataset.factId);
      if (sel.value === 'out') force_exclude.push(sel.dataset.factId);
    });
    const node_boosts = {};
    document.querySelectorAll('.boost-input').forEach((inp) => {
      if (Number(inp.value) !== Number(inp.dataset.original)) node_boosts[inp.dataset.entityId] = Number(inp.value);
    });
    extraBoosts.forEach((b, id) => { node_boosts[id] = b.boost; });
    return {
      settings, force_include, force_exclude, node_boosts,
      edge_edits: edgeEdits.map((e) => ({ a: e.a, b: e.b, weight: e.weight })),
      rerun_filter: $('ov-rerun-filter').checked,
      reanswer: $('ov-reanswer').checked,
    };
  }

  let lastOps = null;
  $('simulate-btn').addEventListener('click', async () => {
    const overrides = collectOverrides();
    const status = $('simulate-status');
    status.textContent = overrides.rerun_filter || overrides.reanswer ? 'asking the model…' : 'running the graph search…';
    $('simulate-btn').disabled = true;
    try {
      const body = { question: data.question, result_id: data.resultId, trace_key: data.traceKey || null, overrides };
      const out = await hippo.api('POST', '/api/simulate', body);
      renderSimulation(out);
      lastOps = out.ops;
      $('save-changeset').disabled = !(out.ops && out.ops.length);
      status.textContent = `done in ${Math.round(out.trace.timing_ms?.total || 0)} ms`;
    } catch (err) { status.textContent = ''; }
    finally { $('simulate-btn').disabled = false; }
  });
  $('reset-btn').addEventListener('click', () => window.location.reload());

  function renderSimulation(out) {
    $('sim-results').hidden = false;
    const t = out.trace, d = out.diff;
    const kept = t.fact_candidates.filter((c) => c.kept).length;
    $('sim-summary').innerHTML = [
      `<span class="badge">${t.used_dpr_fallback ? 'embedding search only: ' + escapeHtml(t.fallback_reason) : `graph search · ${kept} facts kept`}</span>`,
      d.fallback_before !== d.fallback_after ? `<span class="badge">fallback: ${d.fallback_before} → ${d.fallback_after}</span>` : '',
    ].join(' ');
    const goldSet = new Set(data.goldIds);
    $('sim-diff').innerHTML = (d.passages || []).map((p) => {
      const before = p.before_rank ?? '–', after = p.after_rank ?? '–';
      let change = '=';
      if (p.before_rank == null && p.after_rank != null) change = '<span class="up">new</span>';
      else if (p.before_rank != null && p.after_rank == null) change = '<span class="down">gone</span>';
      else if (p.before_rank > p.after_rank) change = `<span class="up">▲ ${p.before_rank - p.after_rank}</span>`;
      else if (p.before_rank < p.after_rank) change = `<span class="down">▼ ${p.after_rank - p.before_rank}</span>`;
      return `<tr><td>${escapeHtml(p.title)}${goldSet.has(p.passage_id) ? ' <span class="pill ok">gold</span>' : ''}</td><td class="num">${before}</td><td class="num">${after}</td><td>${change}</td></tr>`;
    }).join('');
    const seeds = t.seed_entities.filter((s) => s.kept).map((s) => `${escapeHtml(s.name)} (${Number(s.weight).toFixed(3)})`);
    $('sim-seeds').textContent = seeds.length ? `Seeds now: ${seeds.join(', ')}` : 'No seeds (embedding fallback).';
    const ans = $('sim-answer');
    if (out.answer) { ans.hidden = false; ans.innerHTML = `<p class="answer">${escapeHtml(out.answer.answer)}</p>${out.answer.thought ? `<details><summary>How the model reasoned</summary><p class="pre muted">${escapeHtml(out.answer.thought)}</p></details>` : ''}`; }
    else { ans.hidden = true; }
    if (out.explanation && out.explanation.subgraph) drawGraph(out.explanation.subgraph);
  }

  $('save-changeset').addEventListener('click', async () => {
    if (!lastOps || !lastOps.length) return;
    const name = $('cs-name').value.trim() || `Changeset from "${data.question.slice(0, 40)}"`;
    const out = await hippo.api('POST', '/api/changesets', { name, ops: lastOps, from_result_id: data.resultId, note: $('cs-note').value.trim() });
    hippo.toast('Saved. Apply it from the Changesets page.', 'ok');
    setTimeout(() => (window.location = `/changesets?open=${out.changeset_id}`), 600);
  });

  function escapeHtml(text) {
    return String(text ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  drawGraph(data.subgraph);
})();
