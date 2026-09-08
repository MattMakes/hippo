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

<!-- ORCHESTRATOR FILLS FROM THE WP3 LEDGER SUMMARY: paths.py function signatures, Trace field names -->

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
