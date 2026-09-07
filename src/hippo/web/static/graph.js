// The Graph page: the memory in 3D (3d-force-graph on three.js), with search, filters and
// "light up": run the retriever for a question and watch activation spread from the seed
// entities along the graph to the passages it ranks.
//
// Data comes from three endpoints (see routes/graph.py), all scoped to what the viewer may see:
//   GET  /api/graph/full       nodes + edges after the filters, capped by degree
//   POST /api/graph/light-up   seeds, activated nodes with scores, ranked passages, paths
//   GET  /api/graph/node/{id}  the side panel for one node
//
// Colours: nodes are coloured by tier (who may see them), kind, or source. After a light-up,
// seeds turn gold, activated nodes take a heat colour by score, the ranked passages turn green,
// everything else is dimmed, and particles run along the seed -> passage paths.

(() => {
  const dataEl = document.getElementById('graph-data');
  if (!dataEl || typeof ForceGraph3D === 'undefined') return;
  const page = JSON.parse(dataEl.textContent);
  const $ = (id) => document.getElementById(id);

  const COLORS = {
    entity: '#8d95d9', passage: '#e2b25a', dim: '#dedbd3', dimLink: '#ebe9e3', link: '#c9c6bd',
    seed: '#ffb300', passage_hit: '#1f9d55', path: '#4f5bd5', synonym: '#8fcab0', tuned: '#e0a83a',
  };
  // One colour per tier, top of the ladder first (dark) to everyone (light).
  const TIER_COLORS = ['#2f2580', '#4f43c4', '#7a6fe6', '#a49bef', '#c9c3f3'];
  const HEAT = ['#f6d5a4', '#f4a55c', '#ef7b3a', '#e6522c', '#c9302c'];

  // ------------------------------------------------------------- state
  let data = { nodes: [], links: [] };
  let nodeById = new Map();
  let tiers = []; // [{id, name, rank}] top first
  let sourceColor = new Map();
  let lit = null; // the last light-up result, or null
  let litNodes = new Map(); // id -> {score, stage, seed, rank}
  let litLinks = new Set(); // "a|b" keys of path edges
  let stage = Infinity; // animation frontier: nodes with stage <= this are shown lit
  let timer = null;
  let selected = null;

  const canvasHost = $('graph3d');
  const graph = ForceGraph3D()(canvasHost)
    .width(canvasHost.clientWidth)
    .height(canvasHost.clientHeight)
    .backgroundColor('#fcfbf8')
    .showNavInfo(false)
    .nodeId('id')
    .nodeLabel((n) => tooltip(n))
    .nodeVal((n) => nodeSize(n))
    .nodeColor((n) => nodeColor(n))
    .nodeOpacity(0.95)
    .nodeResolution(12)
    .linkWidth((l) => (isLitLink(l) ? 2.2 : Math.min(1.6, 0.4 + (l.weight || 1) * 0.35)))
    .linkOpacity(0.55)
    .linkColor((l) => linkColor(l))
    .linkDirectionalParticles((l) => (isLitLink(l) ? 4 : 0))
    .linkDirectionalParticleWidth(2.4)
    .linkDirectionalParticleSpeed(0.007)
    .linkDirectionalParticleColor(() => COLORS.path)
    .onNodeClick((n) => { focusNode(n); showNode(n.id); })
    .onBackgroundClick(() => { selected = null; refresh(); });
  graph.d3Force('charge').strength(-45);

  function resize() {
    const el = $('graph3d');
    graph.width(el.clientWidth).height(el.clientHeight);
  }
  window.addEventListener('resize', resize);

  // ---------------------------------------------------------- colours
  function tierIndex(n) {
    const i = tiers.findIndex((t) => t.rank === n.tier_rank);
    return i < 0 ? tiers.length - 1 : i;
  }
  function tierColor(n) {
    const steps = Math.max(1, tiers.length - 1);
    const pos = Math.round((tierIndex(n) / steps) * (TIER_COLORS.length - 1));
    return TIER_COLORS[pos];
  }
  function baseColor(n) {
    const mode = $('g-color').value;
    if (mode === 'kind') return n.kind === 'passage' ? COLORS.passage : COLORS.entity;
    if (mode === 'source') {
      if (n.kind === 'passage') return sourceColor.get(n.source_id) || COLORS.passage;
      return COLORS.entity;
    }
    return tierColor(n);
  }
  function heat(score) {
    const i = Math.min(HEAT.length - 1, Math.max(0, Math.floor(score * HEAT.length)));
    return HEAT[i];
  }
  function nodeColor(n) {
    if (selected && selected === n.id) return '#1e2430';
    if (!lit) return baseColor(n);
    const hit = litNodes.get(n.id);
    if (!hit || hit.stage > stage) return $('g-dim').checked ? COLORS.dim : baseColor(n);
    if (hit.seed) return COLORS.seed;
    if (hit.rank) return COLORS.passage_hit;
    return heat(hit.score);
  }
  function nodeSize(n) {
    const base = n.kind === 'passage' ? 5 : 1.5 + Math.min(6, Math.sqrt(n.degree || 1));
    const hit = lit && litNodes.get(n.id);
    if (!hit || hit.stage > stage) return base;
    if (hit.seed) return base * 3;
    if (hit.rank) return base * (hit.rank <= 3 ? 2.2 : 1.6);
    return base * (1 + hit.score * 1.5);
  }
  function linkKey(a, b) { return a < b ? `${a}|${b}` : `${b}|${a}`; }
  function endId(x) { return typeof x === 'object' ? x.id : x; }
  function isLitLink(l) {
    if (!lit) return false;
    const key = linkKey(endId(l.source), endId(l.target));
    if (!litLinks.has(key)) return false;
    const a = litNodes.get(endId(l.source)), b = litNodes.get(endId(l.target));
    return !!(a && b && a.stage <= stage && b.stage <= stage);
  }
  function linkColor(l) {
    if (isLitLink(l)) return COLORS.path;
    if (lit && $('g-dim').checked) return COLORS.dimLink;
    const kinds = l.kinds || [];
    if (kinds.includes('tuned')) return COLORS.tuned;
    if (kinds.includes('synonym')) return COLORS.synonym;
    return COLORS.link;
  }
  function refresh() {
    // Re-setting the accessors makes 3d-force-graph re-evaluate colours and sizes.
    graph.nodeColor(graph.nodeColor()).nodeVal(graph.nodeVal()).linkColor(graph.linkColor())
      .linkWidth(graph.linkWidth()).linkDirectionalParticles(graph.linkDirectionalParticles());
  }

  function tooltip(n) {
    const hit = lit && litNodes.get(n.id);
    const bits = [`<b>${esc(n.label)}</b>`, n.kind === 'passage' ? `passage · ${esc(n.source_name || '')}` : `entity · in ${n.passage_count || 0} passages`, `visible to ${esc(n.tier)} +`];
    if (hit) {
      if (hit.seed) bits.push(`seed · weight ${hit.seedWeight.toFixed(3)}`);
      if (hit.rank) bits.push(`ranked #${hit.rank}`);
      if (hit.score) bits.push(`activation ${hit.score.toFixed(3)}`);
    }
    return `<div class="g-tip">${bits.join('<br>')}</div>`;
  }

  // ------------------------------------------------------------ loading
  function params(extra = {}) {
    const p = new URLSearchParams();
    if (page.asRole) p.set('as_role', page.asRole);
    for (const [k, v] of Object.entries(extra)) if (v !== '' && v !== null && v !== undefined) p.set(k, v);
    return p.toString();
  }
  async function load() {
    $('g-status').textContent = 'loading…';
    const query = params({
      q: $('g-search').value.trim(), source: $('g-source').value, kind: $('g-kind').value,
      min_weight: Number($('g-minw').value) || 0, limit: Number($('g-limit').value) || 2500,
    });
    let out;
    try { out = await hippo.api('GET', `/api/graph/full?${query}`); }
    catch (_) { $('g-status').textContent = 'could not load the graph'; return; }
    tiers = out.tiers || [];
    const sources = [...new Set(out.nodes.filter((n) => n.source_id).map((n) => n.source_id))];
    sourceColor = new Map(sources.map((sid, i) => [sid, `hsl(${(i * 67) % 360} 55% 60%)`]));
    data = { nodes: out.nodes, links: out.edges.map((e) => ({ ...e })) };
    nodeById = new Map(data.nodes.map((n) => [n.id, n]));
    graph.graphData(data);
    resize();
    const viewer = out.viewer && out.viewer.preview ? ` · viewed as ${esc(out.viewer.role)}` : '';
    $('g-status').innerHTML = `${out.shown_nodes} of ${out.matched_nodes} matching nodes shown` +
      `${out.truncated ? ' (raise "max nodes" or narrow the filters to see more)' : ''} · ${data.links.length} edges · ` +
      `${out.entities} entities, ${out.passages} passages, ${out.facts} facts visible${viewer}`;
    legend();
    if (lit) applyLit(lit, false);
  }

  function legend() {
    const mode = $('g-color').value;
    let rows = [];
    if (mode === 'tier') rows = tiers.map((t) => [tierColor({ tier_rank: t.rank }), `${t.name} +`]);
    else if (mode === 'kind') rows = [[COLORS.entity, 'entity'], [COLORS.passage, 'passage']];
    else rows = [...sourceColor.entries()].map(([sid, c]) => [c, ($('g-source').querySelector(`option[value="${sid}"]`) || {}).textContent || sid]).slice(0, 12);
    const litRows = lit ? [[COLORS.seed, 'seed entity'], [HEAT[3], 'activated (hotter = more)'], [COLORS.passage_hit, 'ranked passage'], [COLORS.path, 'path seed → passage']] : [];
    $('g-legend').innerHTML = [...rows, ...litRows].map(([c, t]) => `<span><i style="background:${c}"></i>${esc(t)}</span>`).join('');
  }

  // ------------------------------------------------------------ light up
  async function lightUp() {
    const question = $('g-question').value.trim();
    if (!question) { hippo.toast('Type a question first', 'bad'); return; }
    $('g-light').disabled = true;
    $('g-status').textContent = 'running the search…';
    const settings = {
      damping: Number($('g-damping').value), linking_top_k: Number($('g-topk').value),
      passage_node_weight: Number($('g-pnw').value),
    };
    try {
      const out = await hippo.api('POST', '/api/graph/light-up', {
        question, settings, as_role: page.asRole || null, top_passages: Number($('g-top-passages').value) || 10,
      });
      applyLit(out, true);
    } catch (_) { $('g-status').textContent = 'the search failed'; }
    finally { $('g-light').disabled = false; }
  }

  function applyLit(out, animate) {
    lit = out;
    litNodes = new Map();
    litLinks = new Set();
    // Merge nodes the cap left out so every lit node is drawable.
    let added = 0;
    for (const n of out.subgraph.nodes) {
      if (!nodeById.has(n.id)) {
        const node = { id: n.id, label: n.label, kind: n.kind, degree: 1, tier: n.tier, tier_rank: n.tier_rank, source_name: '' };
        data.nodes.push(node); nodeById.set(n.id, node); added += 1;
      }
    }
    const have = new Set(data.links.map((l) => linkKey(endId(l.source), endId(l.target))));
    for (const e of out.subgraph.edges) {
      const key = linkKey(e.source, e.target);
      if (!have.has(key) && nodeById.has(e.source) && nodeById.has(e.target)) {
        data.links.push({ source: e.source, target: e.target, weight: e.weight, kinds: e.kinds }); have.add(key);
      }
    }
    const maxScore = Math.max(0.000001, ...out.top_nodes.map((n) => n.score || 0));
    for (const n of out.top_nodes) litNodes.set(n.id, { score: (n.score || 0) / maxScore, stage: 2, seed: false, rank: 0, seedWeight: 0 });
    for (const s of out.seeds) litNodes.set(s.id, { ...(litNodes.get(s.id) || { score: 1 }), seed: true, stage: 0, seedWeight: s.weight });
    for (const p of out.passages) {
      const hit = litNodes.get(p.id) || { score: 0, seed: false, seedWeight: 0 };
      litNodes.set(p.id, { ...hit, rank: p.rank, stage: Math.max(hit.stage || 0, 1) });
    }
    // Paths give the animation its order: a node lights when the wave reaches its position on a path.
    let longest = 1;
    for (const path of out.paths) {
      path.nodes.forEach((id, i) => {
        const hit = litNodes.get(id) || { score: 0.2, seed: false, rank: 0, seedWeight: 0, stage: i };
        hit.stage = Math.min(hit.stage ?? i, i);
        litNodes.set(id, hit);
        if (i > 0) litLinks.add(linkKey(path.nodes[i - 1], id));
        longest = Math.max(longest, i);
      });
    }
    for (const [id, hit] of litNodes) if (hit.rank && !hit.seed) hit.stage = Math.max(hit.stage, 1);
    for (const hit of litNodes.values()) if (!hit.seed && !hit.rank && hit.stage === 2) hit.stage = longest + 1;
    if (added) graph.graphData(data);
    $('g-replay').disabled = false;
    $('g-clear').disabled = false;
    $('g-status').textContent = `${out.seeds.length} seeds · ${out.top_nodes.length} activated nodes · ${out.passages.length} passages ranked · ${Math.round(out.timing_ms.total || 0)} ms`;
    renderLit(out);
    legend();
    if (animate) play(longest + 1); else { stage = Infinity; refresh(); }
  }

  function play(last) {
    clearInterval(timer);
    stage = -1;
    refresh();
    timer = setInterval(() => {
      stage += 1;
      refresh();
      if (stage >= last) { clearInterval(timer); stage = Infinity; refresh(); }
    }, 550);
    // Bring the seeds into view.
    const seeds = (lit.seeds || []).map((s) => nodeById.get(s.id)).filter(Boolean);
    if (seeds.length) focusNode(seeds[0], 420);
  }

  function clearLit() {
    clearInterval(timer);
    lit = null; litNodes = new Map(); litLinks = new Set(); stage = Infinity;
    $('g-replay').disabled = true; $('g-clear').disabled = true;
    $('g-side').innerHTML = '<div class="muted small">Click a node to see what it is, or ask a question above to see which paths light up.</div>';
    legend();
    refresh();
  }

  function renderLit(out) {
    const side = $('g-side');
    const kept = out.kept_facts.map((f) => `<li class="triple"><b>${esc(f.triple[0])}</b> <i>${esc(f.triple[1])}</i> <b>${esc(f.triple[2])}</b> <span class="muted">${f.score.toFixed(2)}</span></li>`).join('');
    const seeds = out.seeds.map((s) => `<li><a href="#" data-focus="${esc(s.id)}">${esc(s.name)}</a> <span class="muted">weight ${s.weight.toFixed(3)} · in ${s.passage_count} passages</span></li>`).join('');
    const passages = out.passages.map((p) => `<li><a href="#" data-focus="${esc(p.id)}"><b>#${p.rank}</b> ${esc(p.title)}</a><div class="muted small">${esc(p.why)}</div></li>`).join('');
    side.innerHTML = `
      <h4>${esc(out.question)}</h4>
      ${out.used_dpr_fallback ? `<div class="callout warn small">No graph search: ${esc(out.fallback_reason)}. Passages were ranked by similarity alone.</div>` : ''}
      <p class="small muted">${out.kept_facts.length} facts kept · ${out.seeds.length} seeds · damping ${out.settings.damping} · ${Math.round(out.timing_ms.total || 0)} ms</p>
      <details open><summary class="small">Facts the filter kept</summary><ul class="facts small">${kept || '<li class="muted">none</li>'}</ul></details>
      <details open><summary class="small">Seed entities (gold)</summary><ul class="small g-list">${seeds || '<li class="muted">none</li>'}</ul></details>
      <details open><summary class="small">Ranked passages (green)</summary><ol class="small g-list">${passages}</ol></details>
      <p class="small"><a href="/ask?q=${encodeURIComponent(out.question)}">Ask this on the Ask page for an answer →</a></p>`;
  }

  // ---------------------------------------------------------- one node
  async function showNode(id) {
    selected = id;
    refresh();
    const side = $('g-side');
    side.innerHTML = '<div class="muted small">loading…</div>';
    let n;
    try { n = await hippo.api('GET', `/api/graph/node/${encodeURIComponent(id)}?${params()}`); }
    catch (_) { side.innerHTML = '<div class="muted small">could not load that node</div>'; return; }
    const facts = (n.facts || []).map((t) => `<li class="triple"><b>${esc(t[0])}</b> <i>${esc(t[1])}</i> <b>${esc(t[2])}</b></li>`).join('');
    const neighbours = n.neighbours.map((o) => `<li><a href="#" data-focus="${esc(o.id)}">${esc(o.label)}</a> <span class="muted">· ${o.kind} · ${o.weight} · ${(o.kinds || []).join('+')}</span></li>`).join('');
    const hit = lit && litNodes.get(id);
    side.innerHTML = `
      <h4>${esc(n.label)}</h4>
      <p class="small muted">${n.kind === 'passage' ? `passage from <b>${esc(n.source_name)}</b>` : `entity · mentioned in ${n.passage_count} passages · boost ${n.boost}`} · visible to <b>${esc(n.tier)} +</b> · ${n.degree} neighbours</p>
      ${hit ? `<p class="small">${hit.seed ? `<span class="pill warn">seed · ${hit.seedWeight.toFixed(3)}</span> ` : ''}${hit.rank ? `<span class="pill ok">ranked #${hit.rank}</span> ` : ''}${hit.score ? `<span class="pill">activation ${hit.score.toFixed(3)}</span>` : ''}</p>` : ''}
      ${n.kind === 'passage' ? `<details open><summary class="small">Text</summary><p class="pre small">${esc(n.text)}</p></details>` : ''}
      <details ${n.kind === 'entity' ? 'open' : ''}><summary class="small">Facts (${n.fact_count ?? (n.facts || []).length})</summary><ul class="facts small">${facts || '<li class="muted">none</li>'}</ul></details>
      ${n.kind === 'entity' && n.passages ? `<details><summary class="small">Passages (${n.passages.length})</summary><ul class="small g-list">${n.passages.map((p) => `<li><a href="#" data-focus="${esc(p.id)}">${esc(p.title)}</a></li>`).join('')}</ul></details>` : ''}
      <details><summary class="small">Neighbours (weight · kind)</summary><ul class="small g-list">${neighbours}</ul></details>
      ${lit ? '<p class="small"><a href="#" id="g-back">← back to the question</a></p>' : ''}`;
    const back = $('g-back');
    if (back) back.addEventListener('click', (e) => { e.preventDefault(); selected = null; renderLit(lit); refresh(); });
  }

  function focusNode(n, distance = 260) {
    if (!n || n.x === undefined) return;
    const len = Math.hypot(n.x, n.y, n.z) || 1;
    const ratio = 1 + distance / len;
    graph.cameraPosition({ x: n.x * ratio, y: n.y * ratio, z: n.z * ratio }, n, 900);
  }

  document.addEventListener('click', (e) => {
    const a = e.target.closest('[data-focus]');
    if (!a) return;
    e.preventDefault();
    const n = nodeById.get(a.dataset.focus);
    if (n) { focusNode(n); showNode(n.id); } else hippo.toast('That node is not in the picture (raise "max nodes")', 'bad');
  });

  // ---------------------------------------------------------- wiring
  $('g-light').addEventListener('click', lightUp);
  $('g-question').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); lightUp(); } });
  $('g-replay').addEventListener('click', () => { if (lit) play(Math.max(...[...litNodes.values()].map((h) => h.stage)) ); });
  $('g-clear').addEventListener('click', clearLit);
  $('g-reload').addEventListener('click', load);
  $('g-search').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); load(); } });
  $('g-color').addEventListener('change', () => { legend(); refresh(); });
  $('g-dim').addEventListener('change', refresh);
  for (const id of ['g-source', 'g-kind']) $(id).addEventListener('change', load);

  function esc(text) {
    return String(text ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  load();
})();
