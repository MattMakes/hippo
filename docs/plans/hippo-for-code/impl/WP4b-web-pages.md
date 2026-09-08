# WP4b — Web pages: Graph, Analyze, Ask, Source, Settings (the per-kind rendering)

Read `impl/00-impl-context.md` first. Worktree `.worktrees/wp4b`, branch `wp/wp4b`.
Neo4j test container: name `hippo-neo4j-wp4b`, port **17697**.

`code-graph` now contains WP1-WP3. `GraphIndex` has five vertex kinds (`entity`, `passage`, `symbol`,
`data`, `commit`), `Edge` carries `omega`/`code_kinds`, the retriever's `Trace` carries `seed_symbols`,
`paths`, `tests`, `history`, `select`, and the `Answer` carries `context_block`. The web pages still
spell `entity`/`passage` as literal comparisons and assume "not passage" means "entity". You make every
page render the new kinds correctly. Three other WP4 workers run in parallel: **API/MCP/CLI**
(`web/routes/code.py`, `app.py`, `mcp_server.py`, `cli.py`, `remote.py`, `status.py`), **evals**
(`evals/*`), **docs**. Do not touch their files.

Your spec is PLAN.md **WP4 section 4.4 (line 402)** in full, WP1.4's consumer checklist (lines 234-246 —
the seven files that compare kinds; WP1 did `graph_index.py` and the retriever passthrough, you do the
rest), Decision Log D11 (the community label's surfaces) and D19. Evidence:
`research/R6-web-mcp-cli-docs.md` C2/C3/C4 (Graph and Analyze pages, `graph.js`, `analyze.js`), C5/C6
(settings template — WP3 already fixed `min/max/step`; verify), C18 (Source page), C19 (test client
`base_url`), C20 (templates are compile-checked by `test_web_busy_pages.py`), gotcha 3 (`node_details`
else-branch), and `research/R3-retrieval-analysis.md` R3.2/R3.5 (`explain()` reads `trace.seed_entities`
only), R3.6 (`changesets._node_names`), R3.7 (simulate knobs).

You have a real browser: after the unit tests pass, run `just dev` on a scratch data dir
(`HIPPO_DATA_DIR=/tmp/hippo-wp4b HIPPO_STORE=ladybug .venv/bin/hippo serve --port 8010` — NOT 8000, and
never against `data/`), index `tests/fixtures/code_sample` as a zip source through the UI, and walk the
manual checks in PLAN.md §Verification step 4 (line 489) for Graph, Analyze, Ask, Source and Settings.
Ollama is running on the host for the LLM steps; they take tens of seconds. Screenshot each page into
your ledger notes' paths under `/tmp/hippo-wp4b/shots/`.

## What the previous workers built (read their code, not just this)

**WP1 (store + GraphIndex), 240d348.** 22 store methods on all three backends (writers `add_symbols`,
`add_data_objects`, `add_commits`, `add_code_edges`, `link_definitions`, `add_modifies`, `add_precedes`,
`add_refers_to`, `set_symbol_communities`; readers `get_symbols`/`get_data_objects`/`get_commits`
(access-scoped, `source_name` + `passage_ids`); nine `load_*` loaders; `delete_code_nodes_for_source`);
`stats()` has `symbols`, `data_objects`, `code_edges`, `commits`. `GraphIndex`: `NodeKind` five-valued
(`entity`, `passage`, `symbol`, `data`, `commit`), vertex order entities → symbols → data → commits →
passages LAST, `first_passage_vertex`, `CodeNode`, `DirectedEdge(src, dst, kind, omega, provenance,
extra)`, `code_out`/`code_in`, `name_index`, `Edge.omega`/`code_kinds`/`weight_at(scale)`,
`specificity` (denominator; `entity_passage_count` alias), `graph_for_scale(scale)`, `scoped()` per-kind
visibility, `community_of`/`community_name`, `code_node_by_id`, `out_edges`/`in_edges`,
`defining_passages`, `symbols_defined_in`. All eleven `code_*` settings in `DEFAULT_SETTINGS`/
`SETTING_RULES`/`SETTING_HELP`; `analysis/simulate.py` has `SIMULATABLE_SETTINGS` + `INGEST_SETTINGS`
which a test asserts partition `SETTING_RULES`. **`code_out`/`code_in` are in load order and Neo4j
promises none** — anything that renders or walks them must sort (WP3 sorts by (kind, target name,
source name)); never pin an order-dependent string without sorting.

**WP2 (extractors), 9ba5e39.** `src/hippo/codegraph/` (`model`, `treesitter`, `python`, `typescript`,
`resolve`, `data_access`, `extract`); `extract_code(docs, source_id, *, should_stop=None) -> CodeGraph`;
`Symbol.display` is the fully-qualified display name (`pyapp.orders.OrderService.place`); ids via
`symbol_id`/`data_id`/`commit_id` in `codegraph/model.py`; `readers.lang_of(name)`. Fixture:
`tests/fixtures/code_sample/` (30 symbols, 12 data objects, 64 edges; `expected.json` is the spec;
`scripts/update_expected.py --check`). Two pinned rulings: `cli.main -> OrderService.place` INVOKES 0.90
`via_import`; `place -> OrderService.log` INVOKES 1.00 `same_file`, no `place -> Base.log` edge.

**WP2i (indexing), 143480d.** Passage titles `path :: module.qualname (lines a-b)` (`(part N)` when
split); `Chunk.defines`/`extract_text`; `index_source(..., code=)` stages `"writing code graph"`,
`"linking mentions"` (REFERS_TO 0.85/0.60), `"communities"` (seeded Leiden, relabelled); nine-key
counts; `meta["code"]` = `symbols`, `data_objects`, `edges`, `edges_by_kind`, `files_parsed`,
`files_skipped`, `unresolved_calls`, `unresolved_calls_total`, `truncated` (+ WP2b's commit keys and
`history_skipped`). `tests/conftest.py`: `code_index` fixture yields `(ctx, source_id)` (kind
`"archive"`, store-generated id), `code_sample_zip()`, `CODE_SAMPLE_PATH`, `--update-expected`. A symbol
whose name splits into < 2 tokens carries NO embedding by design (`enters_synonym_search`); DataObject
exempt. Full handoffs: `horch sessions` entries `backend-developer-1`, `opus-1`, `backend-developer-2`.

<!-- ORCHESTRATOR FILLS FROM THE WP2b / WP3 LEDGER SUMMARIES -->

## Files you own

`src/hippo/web/routes/graph.py`, `src/hippo/web/routes/sources.py`, `src/hippo/web/routes/analyze.py`,
`src/hippo/web/routes/pages.py` (help text only if needed), `src/hippo/web/static/graph.js`,
`src/hippo/web/static/analyze.js`, `src/hippo/web/templates/{graph,source,analyze,settings}.html`,
`src/hippo/web/templates/partials/answer.html`, `src/hippo/analysis/explain.py`,
`src/hippo/analysis/simulate.py`, `src/hippo/analysis/changesets.py`, and their tests
(`test_web_analyze.py`, `test_web_base.py`, `test_web_busy_pages.py`, `test_analysis_*.py`, plus a new
`test_web_graph_code.py` if none covers `graph.py`'s node endpoints).

## Scope

1. **Graph page** — `node_details` branches per kind: a symbol id returns signature, path, lines, doc,
   callers/callees (with kind + ω), tests, community label; data object: kind, dialect, readers/writers;
   commit: sha, author, date, message, modified symbols. `full_graph`'s node dict builder emits `kind`,
   and **`tiers_of` sets a code node's tier from `source_tier[node.source_id]`** (today a mention-less node
   renders as "Everyone"); test that a hidden-tier symbol shows its real tier. `graph.js`: colour, size,
   tooltip, legend per kind; the `g-kind` filter gains the three kinds; the `g-color` options gain a
   **`community` colour mode** by name (D11's main visible surface). Test: a symbol id through
   `node_details` returns the symbol-shaped payload, not the entity-shaped fallback.
2. **Analyze page** — a seed-symbols table (from `trace.seed_symbols`: token, how, weight, `n_matches`,
   `ambiguous`), symbols joined into the `explain()` subgraph explicitly (it reads `seed_entities` only),
   a Paths section rendering `trace.paths` in the S2.15 grammar, per-kind Cytoscape style selectors in
   `analyze.js` (additive), and simulate knobs for `code_seed_weight` / `code_structural_scale` /
   `code_theta` — they are in `SETTING_RULES`, so verify they appear and that the three ingest settings
   do NOT (`SIMULATABLE_SETTINGS`). Moving the scale slider must not fire an LLM call (WP3's
   `replay_select`) — assert it in `test_analysis_simulate.py` if WP3 did not. `changesets._node_names`
   resolves symbol/data ids.
3. **Ask page** — a "Code graph" card in `partials/answer.html` when `answer.context_block`, and the seed
   chips for `seed_symbols`.
4. **Source page** — the code-graph `<details>` under a symbol passage (its symbol, out-edges, tests,
   commits) and the `meta["code"]` summary on the source header (files parsed/skipped, symbols, edges,
   unresolved, `history_skipped`, `truncated`).
5. **Settings page** — verify WP3's `SETTING_RULES`-driven `min/max/step` renders every `code_*` key with
   its help text; save `code_seed_weight = 2` and toggle `code_select` in the browser.
6. `evals/question_maker.py`'s kind comparison is the **evals worker's**; skip it.

## Done when

Every manual check in §Verification step 4 that touches a page passes in your browser, the unit tests
cover each new branch on all three stores, lint green. Commit, ledger summary (files; the screenshot
paths; anything the docs worker should describe), `horch tell orchestrator "[<role>] DONE: wp/wp4b ..."`,
close pane. Stop the scratch server and delete `/tmp/hippo-wp4b` data before you go.
