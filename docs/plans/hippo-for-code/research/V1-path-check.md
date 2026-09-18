# V1 mechanical review: paths, DDL, signatures, and consistency

| id | count checked | defects |
|---|---:|---:|
| V1.1 Paths | 84 | 0 |
| V1.2 Symbols | 31 | 0 |
| V1.3 Store parity | 22 methods/loaders | 0 |
| V1.4 DDL | 12 statement shapes | 3 |
| V1.5 Settings | 9 | 1 |
| V1.6 Tests | 25 files | 1 |
| V1.7 Contracts | 1 proposed block | 0 |
| V1.8 Internal consistency | 4 name families, 8 settings, 10 edge kinds, 10 omega rows | 0 |

## Defects

- **[blocker]** PLAN.md:223 — `MATCH (n:Symbol:DataObject:Commit) WHERE n.source_id = $id DETACH DELETE n` is prescribed for deletion, including the Neo4j batched implementation — in the Neo4j dialect used by this repository, alternatives are written with `|`; chained labels mean that the same node must carry all labels, so this query matches none of the separately labelled code nodes (`src/hippo/store/changesets.py:71`). Use concrete per-label statements or `MATCH (n:Symbol|DataObject|Commit ...)` and retain the stated batching.
- **[fix]** PLAN.md:186-203 — the plan says R4 T7 “proves” the multi-pair relationship-table DDL, while R4's verdict for T7 is `PARTIAL`, not `PASS`; the successful concrete-label writes are accompanied by a failing multi-label-pattern write (`docs/plans/hippo-for-code/research/R4-spike-results.md:9`, `:166-179`). The implementation directions do account for the restriction, but the plan must not present this as a PASS row under V1.4's acceptance rule.
- **[fix]** PLAN.md:203 — the fallback migration uses `RENAME TO`, copy, and `DROP`, but no R4 PASS row tests those DDL statements; R4 covers scalar ALTER, additive tables, relation endpoint ALTER, and multi-pair tables only (`docs/plans/hippo-for-code/research/R4-spike-results.md:3-13`). Either cite a separate checked result or add the missing spike before retaining this executable fallback.
- **[fix]** PLAN.md:189-195 — production changes the tested T7 third endpoint pair from `(DataObject, Symbol)` to `(DataObject, DataObject)` — R4's exact tested DDL contains `(DataObject, Symbol)`, not the production pair (`docs/plans/hippo-for-code/research/R4-spike-results.md:164-169`). This is likely supported by the generic feature, but it is not an exact match to a PASS row as V1.4 requires.
- **[fix]** PLAN.md:134,277-283 — `Config.git_history_depth` / `HIPPO_GIT_HISTORY_DEPTH` has a default and disable value, but is explicitly excluded from graph settings and therefore has no `SETTING_RULES` bounds or Settings-page control — every current Settings-page input is generated from stored settings, and its validation bounds come from `SETTING_RULES` (`src/hippo/store/base.py:13-32`, `src/hippo/web/templates/settings.html:68-80`). If it is intentionally env-only, call it configuration rather than a new setting and exempt it explicitly from V1.5; otherwise specify its upper bound and Settings UI.
- **[fix]** PLAN.md:277-283 — `test_git_history.py` and the added repo-history case in `test_ingest_pipeline.py` are named, but their store matrix is not stated locally; the section only says the feature is done when history works on all three stores. This is less precise than WP1's “Store matrix = all three” and WP2's explicit `test_indexer.py (all three stores)` (`PLAN.md:231`, `:266`). State whether the pure git test is backend-free and whether the pipeline case runs through the parametrized `store` fixture (`tests/conftest.py:32-41`).

## V1.1 path inventory

`exists` means tracked in the current repository. `new` means absent and explicitly marked new in PLAN.md. Brace groups are expanded here.

| path | in plan as | exists? | verdict |
|---|---|---:|---|
| `src/hippo/codegraph/` | new package | no | new |
| `src/hippo/codegraph/__init__.py` | create/new | no | new |
| `src/hippo/codegraph/model.py` | create/new | no | new |
| `src/hippo/codegraph/treesitter.py` | create/new | no | new |
| `src/hippo/codegraph/python.py` | create/new | no | new |
| `src/hippo/codegraph/typescript.py` | create/new | no | new |
| `src/hippo/codegraph/resolve.py` | create/new | no | new |
| `src/hippo/codegraph/data_access.py` | create/new | no | new |
| `src/hippo/codegraph/extract.py` | create/new | no | new |
| `src/hippo/codegraph/git_history.py` | create/new | no | new |
| `src/hippo/store/code.py` | create/new | no | new |
| `src/hippo/hipporag/anchors.py` | create/new | no | new |
| `src/hippo/hipporag/paths.py` | create/new | no | new |
| `src/hippo/web/routes/code.py` | create/new | no | new |
| `src/hippo/store/ladybug.py` | modify | yes | exists |
| `src/hippo/store/__init__.py` | modify | yes | exists |
| `src/hippo/store/base.py` | modify | yes | exists |
| `src/hippo/store/memory.py` | modify | yes | exists |
| `src/hippo/store/changesets.py` | modify | yes | exists |
| `src/hippo/hipporag/graph_index.py` | modify | yes | exists |
| `src/hippo/hipporag/indexer.py` | modify | yes | exists |
| `src/hippo/hipporag/retriever.py` | modify | yes | exists |
| `src/hippo/hipporag/answerer.py` | modify | yes | exists |
| `src/hippo/hipporag/text.py` | modify | yes | exists |
| `src/hippo/ingest/chunker.py` | modify | yes | exists |
| `src/hippo/ingest/pipeline.py` | modify | yes | exists |
| `src/hippo/ingest/readers.py` | modify | yes | exists |
| `src/hippo/ingest/repos.py` | modify | yes | exists |
| `src/hippo/ask.py` | modify | yes | exists |
| `src/hippo/prompts.py` | modify | yes | exists |
| `src/hippo/config.py` | modify | yes | exists |
| `src/hippo/analysis/explain.py` | modify | yes | exists |
| `src/hippo/analysis/simulate.py` | modify | yes | exists |
| `src/hippo/analysis/changesets.py` | modify | yes | exists |
| `src/hippo/evals/question_maker.py` | modify | yes | exists |
| `src/hippo/evals/runner.py` | modify | yes | exists |
| `src/hippo/mcp_server.py` | modify | yes | exists |
| `src/hippo/cli.py` | modify | yes | exists |
| `src/hippo/remote.py` | modify | yes | exists |
| `src/hippo/status.py` | modify | yes | exists |
| `src/hippo/web/app.py` | modify | yes | exists |
| `src/hippo/web/routes/graph.py` | modify | yes | exists |
| `src/hippo/web/routes/sources.py` | modify | yes | exists |
| `src/hippo/web/routes/analyze.py` | modify | yes | exists |
| `src/hippo/web/routes/pages.py` | modify | yes | exists |
| `src/hippo/web/static/graph.js` | modify | yes | exists |
| `src/hippo/web/static/analyze.js` | modify | yes | exists |
| `src/hippo/web/templates/settings.html` | modify | yes | exists |
| `src/hippo/web/templates/graph.html` | modify | yes | exists |
| `src/hippo/web/templates/source.html` | modify | yes | exists |
| `src/hippo/web/templates/analyze.html` | modify | yes | exists |
| `src/hippo/web/templates/partials/answer.html` | modify | yes | exists |
| `tests/fixtures/code_sample/` | create/new | no | new |
| `tests/unit/test_store_code.py` | create/new | no | new |
| `tests/unit/test_codegraph.py` | create/new | no | new |
| `tests/unit/test_git_history.py` | create/new | no | new |
| `tests/unit/test_anchors.py` | create/new | no | new |
| `tests/unit/test_paths.py` | create/new | no | new |
| `tests/unit/test_web_code.py` | create/new | no | new |
| `tests/fakes/fake_store.py` | modify | yes | exists |
| `tests/fakes/fake_ollama.py` | modify | yes | exists |
| `tests/conftest.py` | modify | yes | exists |
| `tests/unit/test_store_ladybug.py` | modify/grow | yes | exists |
| `tests/unit/test_store_row_shapes.py` | modify/grow | yes | exists |
| `tests/unit/test_store.py` | modify | yes | exists |
| `tests/unit/test_graph_index.py` | modify | yes | exists |
| `tests/unit/test_store_graph.py` | modify | yes | exists |
| `tests/unit/test_access.py` | modify | yes | exists |
| `tests/unit/test_ingest_chunker.py` | modify | yes | exists |
| `tests/unit/test_indexer.py` | modify | yes | exists |
| `tests/unit/test_ingest_pipeline.py` | modify | yes | exists |
| `tests/unit/test_ingest_repos.py` | existing reference | yes | exists |
| `tests/unit/test_retriever.py` | modify | yes | exists |
| `tests/unit/test_ask.py` | modify | yes | exists |
| `tests/unit/test_analysis_simulate.py` | modify | yes | exists |
| `tests/unit/test_fakes.py` | modify | yes | exists |
| `tests/unit/test_mcp_server.py` | modify | yes | exists |
| `tests/unit/test_analysis_explain.py` | modify | yes | exists |
| `tests/unit/test_web_busy_pages.py` | existing coverage reference | yes | exists |
| `docs/CONTRACTS.md` | modify | yes | exists |
| `docs/FIDELITY.md` | modify | yes | exists |
| `docs/MCP.md` | modify | yes | exists |
| `README.md` | modify | yes | exists |
| `pyproject.toml` | modify | yes | exists |

## V1.2 existing-symbol spot-check

All existing targets named for modification were found. Current signatures that the plan extends are:

- `Retriever.retrieve(self, question, settings, *, fact_filter=None, force_include=frozenset(), force_exclude=frozenset(), node_boosts=None, graph=None, question_embedding=None) -> Trace` (`src/hippo/hipporag/retriever.py:160-172`). The plan does not actually propose `seed_nodes`; it adds code seeding internally.
- `index_source(store, ollama, source_id, chunks, *, synonymy_threshold=0.8, workers=2, on_progress=None, should_stop=None)` (`src/hippo/hipporag/indexer.py:65-75`). The proposed `code=None` is additive.
- `chunk_documents(docs, size_chars, overlap_chars)` (`src/hippo/ingest/chunker.py:39`). The proposed `code=None` is additive.
- `clone_repo(url, dest, timeout=300) -> Path` (`src/hippo/ingest/repos.py:58`). The proposed `depth=1` is additive.
- `answer_question(ollama, question, passages) -> Answer` (`src/hippo/hipporag/answerer.py:25`). The proposed `context_block=""` is additive.
- `search(ctx, question, settings=None, access=None) -> Trace` and `answer_from_trace(ctx, trace, access=None) -> Answer` exist at `src/hippo/ask.py:23` and `:40`.
- `generate_questions`, `run_question`, `summarize`, `explain`, `simulate`, `build_parser`, `_context_or_running_server`, `stats`, `delete_source`, `delete_passages_for_source`, `remove_orphans`, `add_synonyms`, `set_edge_weight`, `clear_edge_weight`, and `set_node_boost` all exist under the modules the plan names.

## V1.3 store parity

The plan assigns every new store operation to all three implementations: LadybugDB in `store/ladybug.py`, Neo4j in the new `store/code.py` mixin, and `FakeStore` in `tests/fakes/fake_store.py` (`PLAN.md:207-219`). Names are identical. Input/output shapes are specified once in the shared method table, so there is no per-backend row-shape divergence in the plan. The parity guard at `PLAN.md:239` mechanically compares method names.

## V1.5 settings cross-check

The eight graph settings at `PLAN.md:125-132` each have a default, a type, min/max bounds, Settings-page help, and an explicit requirement to replace the template's hard-coded bounds. That matches R1.7's finding (`docs/plans/hippo-for-code/research/R1-store-api.md:99-111`). The separate history configuration is the defect listed above.

## V1.6 test collision and matrix check

All seven files marked new are absent; every file marked modify/grow exists. There are no filename collisions. WP1 explicitly says all-three-store matrix (`PLAN.md:231`), WP2 marks pure tests and `test_indexer.py` all-three (`:263-267`), and WP3 says `code_index` exercises all three (`:303`). The WP2b wording gap is listed above.

## V1.7 contract format

The proposed block at `PLAN.md:452-480` matches the existing contract convention: a fenced plain-text block, left-aligned module path, aligned signatures, and indented continuation rows. The current precedent is visible at `docs/CONTRACTS.md:338-343`; the plan correctly does not propose a Markdown table.

## V1.8 consistency check

No internal mismatch found. The plan consistently uses `CODE_EDGE` (not B's `STRUCT`), `src/hippo/hipporag/paths.py` (not `analysis/paths.py`), `Config.git_history_depth` default 200, `code_theta` default 0.5, `code_structural_scale`, `code_community_boost` default 0.0, the same ten code-edge kinds, and A's omega table. References to `STRUCT` and `omega_threshold` occur only while explicitly describing and rejecting B's alternatives.
