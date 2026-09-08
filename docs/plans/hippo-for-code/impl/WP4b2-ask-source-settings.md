# WP4b2 — Web pages, second slice: Ask card, Source page, Settings verification

Read `impl/00-impl-context.md` first, then `impl/WP4b-web-pages.md` for the shared context (the
"What the previous workers built" block, the browser instructions, the evidence list) — **but your scope
is only the slice below**. Worktree `.worktrees/wp4b2`, branch `wp/wp4b2`. Neo4j test container: name
`hippo-neo4j-wp4b2`, port **17699**. Scratch server: `HIPPO_DATA_DIR=/tmp/hippo-wp4b2 HIPPO_STORE=ladybug
.venv/bin/hippo serve --port 8011` (never 8000, never `data/`). Screenshots under `/tmp/hippo-wp4b2/shots/`.

Another worker (WP4b) owns the Graph and Analyze pages and `analysis/*`; WP4a owns the API/MCP/CLI/status;
WP4c owns evals; WP4d owns docs. **You own only:** `src/hippo/web/templates/partials/answer.html`,
`src/hippo/web/routes/sources.py`, `src/hippo/web/templates/source.html`, `src/hippo/web/templates/
settings.html` (verification only; WP3 already made it read `SETTING_RULES`), `src/hippo/web/routes/
pages.py` (help text only if a line reads badly), and tests for those (`test_web_base.py`,
`test_web_busy_pages.py`, or a new `test_web_source_code.py`). Spec: PLAN.md 4.4 (line 402), the Ask,
Source and Settings sentences; §Verification step 4 (line 489) for the Ask / Source / Settings checks.
WP2b (git history) may merge while you work; use `tests/fakes/code_fixture.py::write_commit_history` for
commit rendering until then.

## Scope

1. **Ask page** — a "Code graph" card in `partials/answer.html` rendered when `answer.context_block` is
   non-empty (preformatted, the S2.15 grammar as-is, collapsible), and seed chips for
   `trace.seed_symbols` (token, how, weight) next to the existing entity seed chips. Test: an answer with a
   block renders the card; one without does not; a stored pre-WP3 answer dict still renders.
2. **Source page** — under each symbol passage a `<details>` "Code graph" with the defining symbol(s)
   (display name, kind, lines, signature), out-edges grouped by kind with ω, tests (TESTED_BY targets),
   commits (MODIFIES, newest first); and on the source header a `meta["code"]` summary (files parsed /
   skipped by reason, symbols, data objects, edges, unresolved calls, `history_skipped`, `truncated`,
   `languages` once WP4a adds it). Read the data through the store's `get_symbols`/`get_commits` and the
   scoped `GraphIndex` (`symbols_defined_in`, `out_edges`) — sort every list, never rely on load order.
   Test over `code_index`: the details render for `pyapp/orders.py :: pyapp.orders.OrderService.place`
   and not for a prose passage; a restricted principal sees no symbol details for a hidden source.
3. **Settings page** — verify in the browser that every `code_*` key renders with its help text and the
   `SETTING_RULES` bounds, save `code_seed_weight = 2`, toggle `code_select`, reload and confirm both
   stuck. Fix only what is broken; WP3 owns the mechanism.

## Done when

Unit tests green on all three stores, lint green, the Ask / Source / Settings manual checks pass in your
browser with screenshots in the ledger. Commit, ledger summary (files; screenshot paths),
`horch tell orchestrator "[<role>] DONE: wp/wp4b2 ..."`, close pane. Stop the scratch server and delete
`/tmp/hippo-wp4b2` data before you go.
