# WP4c — Evals: code questions, commit questions, the new recall metrics

Read `impl/00-impl-context.md` first. Worktree `.worktrees/wp4c`, branch `wp/wp4c`.
Neo4j test container: name `hippo-neo4j-wp4c`, port **17698**.

`code-graph` now contains WP1-WP3 (graph, indexing, git history, retrieval). You make the eval harness
generate code and commit questions and measure whether code seeding helped. Three other WP4 workers run
in parallel (API/MCP/CLI, web pages, docs); you own only `src/hippo/evals/*` and their tests
(`tests/unit/test_evals_*.py`, `test_web_library_evals.py` only if a response shape you add reaches it).

Your spec is PLAN.md **WP4 section 4.5 (line 404)**, Decision Log D17, and the retrieval rule's
baseline settings (line 123: `code_seed_weight=0 code_dense_seeds=0 code_select=False
code_structural_scale=0`). Evidence: `research/R2-ingest-evals-tests.md` R2-12 (`origin`/`kind` are free
strings; `origin` is QuestionSet-level, `kind` per question), R2-14 (`recall[...]` keys and `summarize`'s
`DEFAULT_KS` loop), R2-15 (**never assert the fake judge's verdict on code questions**), R2 gotcha 3
(a `Trace` is stored per `EvalResult`).

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

## Scope

1. **`evals/question_maker.py`** — `generate_questions(..., max_code=5, max_commits=5)` plus two pure
   generators over a `GraphIndex`: `code_questions` (functions with ≥ 1 INVOKES out-edge at ω ≥ 0.5 and a
   doc ≥ 80 chars → a question naming the function's display qualname, gold = its defining passage plus
   the callee's; `kind="code"`) and `commit_questions` (commits touching ≥ 2 symbols, newest first → "what
   changed in <subject>", gold = the commit passage plus the modified symbols' passages; `kind="commit"`).
   Fix the kind comparison the plan's WP1.4 checklist names for this file (a non-passage vertex must not
   be treated as an entity). Expected answers are short deterministic strings built from the graph, never
   from an LLM.
2. **`evals/runner.py`** — `run_question` adds `recall["code_seeded"]` (1.0 if `trace.used_code_seeds`
   else 0.0) and, for `kind="commit"`, `recall["path_fidelity"]` (fraction of the gold MODIFIES symbols
   whose passages are in the retrieved top-k); `summarize` means them like the existing keys.
   Baseline comparison is a settings-override run with the four baseline values — add a helper that
   takes a `QuestionSet` and returns `(with_code, baseline)` summaries so the README/docs can describe it.
3. **Tests** — over `code_index` and `git_index` on all three stores: the generators' exact question
   sets for the fixture (`place` qualifies; nothing without a doc does; commit 2 and 3 qualify if they
   touch ≥ 2 symbols — check `make_code_checkout`), the new recall keys present with sensible values,
   `summarize` including them, and the baseline helper producing two summaries with **no assertion on
   the judge's verdict** for code/commit questions.

## Done when

Three stores + lint green. Commit, ledger summary (files; the new metric key names; the generator
question templates verbatim — the docs worker will quote them),
`horch tell orchestrator "[<role>] DONE: wp/wp4c ..."`, close pane.
