# WP4a — HTTP API, MCP tools, CLI + remote, status card

Read `impl/00-impl-context.md` first. Worktree `.worktrees/wp4a`, branch `wp/wp4a`.
Neo4j test container: name `hippo-neo4j-wp4a`, port **17696**.

`code-graph` now contains WP1-WP3: the store, `GraphIndex` with code vertices, the extractors, indexing,
git history, `hipporag/anchors.py`, `hipporag/paths.py` and a retriever/answer path that produces
`seed_symbols`, `paths`, `tests`, `history` on the `Trace` and `context_block` on the `Answer`. You expose
the path tools over HTTP, MCP and the CLI. Three other WP4 workers run in parallel: **web pages**
(`web/routes/graph.py`, `web/static/*.js`, templates, `analysis/*`), **evals** (`evals/*`), **docs**
(`docs/*.md`, `README.md`). Do not touch their files; yours are listed below.

Your spec is PLAN.md **WP4 sections 4.1, 4.2, 4.3 (lines 396-400)** and the status card sentence in 4.4
(line 402: "Status: a 'Code' card is purely additive"); Decision Log D21. Evidence:
`research/R6-web-mcp-cli-docs.md` C1 (router include order — only "before `_mount_mcp`" matters), C7/C8
(no CSRF token; access is `principal_of(request).access` → `ctx.graph_for(access)`), C9 (the MCP tool
pattern), C10 (argparse CLI, `_context_or_running_server()`), C11 (`status._compute()`), C19 (test clients
must pass `base_url="http://localhost"`), gotcha 2 (`TOOL_NAMES` in `test_mcp_server.py:17`), and
`research/R2-ingest-evals-tests.md` R2-20 (`RemoteHippo`).

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

**WP3 (retrieval, paths, answer block), c6e186e.** `src/hippo/hipporag/anchors.py`: `find_anchors(question,
index)`, `split_question(text)`; a bare word anchors only when its surface form is code-shaped.
`src/hippo/hipporag/paths.py`: `resolve_symbol` (`UnknownSymbol`, `AmbiguousSymbol.candidates`),
`shortest_code_path`, `direct_edges`, `code_paths_for`, `expand_from`, `blast_radius`/`render_blast`,
`exception_path`, `history`, `tests_for`, the `*_rows` helpers, **`community_labels(index)`** (the
display-name subsystem label — use THIS, never `GraphIndex.community_name`, which labels two different
subsystems "Base" on the real tree), and the block builder `block_lines`/`cut_to`/`render_block`.
`retriever.py`: `SeedSymbol`, `SelectResult`, `SelectFn`; `Trace` += `seed_symbols`, `used_code_seeds`,
`question_prose`, `question_code`, `paths`, `tests`, `history`, `select`, `expansions` (all defaulted);
`RankedPassage` += `community_boosted`, `via_expand`; `retrieve(..., select_fn=None)`. `answerer.py`:
`Answer.context_block`, `answer_question(..., context_block="")`. `prompts.py`: `CODE_GRAPH_HEADER`,
`CODE_SELECT_SYSTEM`/`CODE_SELECT_SCHEMA`, `code_select_messages`. `ask.py` installs `retriever.llm_select`
and `answer_from_trace` filters `via_expand` before `qa_top_k`. `analysis/simulate.py`: `replay_select`.
Settings page reads `min/max/step` from `SETTING_RULES`. `tests/conftest.py`: `index_code_sample`,
`index_prose_sample`, `sample_chunks`, `mixed_index` (prose + code in one memory); `tests/fakes/
code_fixture.py`: `write_commit_history` (a store-built stand-in for git history), `many_symbols`.
`test_ask.py`'s `CODE_BLOCK_BODY` pins the answer block byte-for-byte. Every path walk sorts edges by
(kind, target name, source name). Full handoff: `horch sessions` entry `opus-2` ("WP3 FINAL SUMMARY").

<!-- ORCHESTRATOR FILLS FROM THE WP2b LEDGER SUMMARY -->

## Files you own

Create: `src/hippo/web/routes/code.py`, `tests/unit/test_web_code.py`.
Modify: `src/hippo/web/app.py`, `src/hippo/mcp_server.py`, `src/hippo/cli.py`, `src/hippo/remote.py`,
`src/hippo/status.py`, `tests/unit/test_mcp_server.py`, `tests/unit/test_mcp_http.py`,
`tests/unit/test_cli.py`, and whichever test covers `status.py`.

## Scope

1. **4.1 API** — `api = APIRouter(prefix="/api/code")` with `GET /symbols?q=&limit=` (substring over the
   caller's scoped `name_index`, ≤ 100), `GET /path`, `GET /blast-radius`, `GET /exception-path`,
   `GET /history`; `UnknownSymbol` → 404, `AmbiguousSymbol` → 409 with candidates, `depth` clamped 1-4,
   `ValueError` → 400, matching `analyze.py`'s mapping. Included in `app.py` before `_mount_mcp`.
   `test_web_code.py`: every endpoint over `code_index` (and `git_index` for history), the 404/409/400
   mapping, and the access case — a restricted principal gets 404 for a hidden source's symbol.
2. **4.2 MCP** — `explain_path_tool`, `blast_radius_tool`, `exception_path_tool`, `history_tool` as
   module-level functions plus one-line `@server.tool` closures named `hippo_explain_path`,
   `hippo_blast_radius`, `hippo_exception_path`, `hippo_history` (A's names, Confirm #4 — do not rename);
   ambiguity → `ToolError`; `search_tool`/`ask_tool` responses gain `seed_symbols`, `paths`, `tests`,
   `history`, `code_graph`. `TOOL_NAMES` grows five → nine; add a stdio and an HTTP test for at least one
   new tool following the existing files.
3. **4.3 CLI + remote** — `hippo path A B`, `hippo blast SYMBOL [--depth N]`, `hippo raises SYMBOL
   EXCEPTION`, `hippo history SYMBOL [--limit N]` as `add_parser` blocks + `handlers` entries, each via
   `_context_or_running_server()` branching on `remote is None`; `RemoteHippo` gains four thin methods
   in the style of `ask`; ambiguity → exit 2 with candidates on stderr. Test both the local and the
   remote branch the way `test_cli.py` already does for `ask`.
4. **Status** — a "Code" card in `status._compute()`: symbols, data objects, code edges, commits,
   languages present, unresolved-call count, `history_skipped`, all from `stats()`/`Source.meta`; zero
   values when no code is indexed. Purely additive; existing keys untouched.

## Done when

Nine MCP tools answer over HTTP and stdio, the four CLI commands work locally and behind a running server
(the tests prove both branches), three stores + lint green. Commit, ledger summary (files; the exact
endpoint query parameters and JSON shapes; the MCP response field names — the docs worker will copy them),
`horch tell orchestrator "[<role>] DONE: wp/wp4a ..."`, close pane.
