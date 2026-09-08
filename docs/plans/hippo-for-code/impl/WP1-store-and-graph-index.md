# WP1 — Store (LadybugDB, Neo4j, FakeStore) and `GraphIndex`

Read `impl/00-impl-context.md` first. Worktree `.worktrees/wp1`, branch `wp/wp1`.
Neo4j test container: name `hippo-neo4j-wp1`, port **17691**.

Your spec is PLAN.md **WP1 (lines 170-261)** plus the shared contract: Design summary lines 59-164
(graph model, ω table, retrieval rule, settings table, package layout) and the Decision Log rows
D1-D5, D14, D18, D22. Evidence behind it: `research/R1-store-graph.md` (store layer, every line cited)
and `research/R4-spike-results.md` T1/T4/T5/T6/T7/T8 (the exact DDL that was proven on LadybugDB).
Read all of that before writing code. WP2's `codegraph/` is being built in parallel by another worker;
**you import nothing from it** (gotcha 6) — the row dicts in the WP1.3 table are the whole interface.

## Scope (everything in PLAN.md WP1, with these clarifications)

1. **`hipporag/text.py` already has `label_of` and `split_identifier`** (WP0, on `code-graph`). Use them;
   do not redefine. Add nothing else there unless the plan names it.
2. **Settings are declared here, not in WP3.** WP1.4 makes `analysis/simulate.py:110` pass
   `settings["code_structural_scale"]`, so the key must exist. Declare all **eleven** `code_*` keys from the
   §Settings table (line 129-141) in `store/base.py` `DEFAULT_SETTINGS` and `SETTING_RULES` with exactly
   the bounds shown, add a `SETTING_HELP` line for each in `web/routes/pages.py` (use the Meaning column
   verbatim), and add the explicit `SIMULATABLE_SETTINGS` allow-list in `analysis/simulate.py` (§2.2c,
   line 336) that excludes `code_history_depth`, `code_git_timeout_s`, `code_history_total_s` from the
   Analyze knob list. The `settings.html` `min/max/step` fix stays WP3's. Check `tests/unit/
   test_settings_and_safety.py` and the web tests for anything that pins the settings key set.
3. **How the normal retrieval path gets a scaled igraph is unspecified in the plan** (it only specifies
   `build_igraph(..., scale)` and `graph_with_edits(edits, scale)`). Provide
   `GraphIndex.graph_for_scale(scale: float) -> ig.Graph`: returns `self.graph` when `scale == 1.0`,
   otherwise builds with `build_igraph(..., scale)` and memoises per scale on the index (a dict; it dies
   with the index, which `graph_version` already invalidates). `scoped()` indexes get their own memo.
   WP3's retriever will call it. Document it in the class docstring.
4. **Test 1.5a first** (line 251): the populated-table `ALTER TABLE ... ADD IF NOT EXISTS FROM X TO Y`
   on `SYNONYM`/`TUNED` across a close/reopen. If it passes, the rebuild fallback is never written. If it
   fails, do NOT write the `RENAME TO`/`DROP` fallback from the plan's paragraph — it is unverified.
   Spike it in `/tmp` first, record what LadybugDB actually accepts in your ledger notes, then
   `horch tell orchestrator` with the finding before building the fallback.
5. **`GraphIndex.load` signature.** Look at how `AppContext` builds and caches the index (`core/context.py`
   or wherever `graph_for(access)` and `invalidate_graph()` live) so `load()` picks up the new loaders
   without changing its call sites. Loading code nodes must be a no-op cost on a store with no code.
6. The vertex-order arithmetic fix (`num_entities`, `first_passage_vertex`, `passage_position`) and its
   nine call sites (line 246) are yours, including the ones in `web/routes/graph.py`. The rest of
   `graph.py` (per-kind `node_details`, `full_graph` node builder, `tiers_of`) is WP4's — leave it, but
   make sure nothing in it crashes when the index contains code vertices (a symbol id passed to
   `node_details` today returns a wrong-shaped 200; that is acceptable until WP4, a 500 is not).
7. `FakeStore` must implement every new method with identical row shapes; the parity guard test
   (line 259) is what proves it. Write LadybugDB first, then port to FakeStore, then Neo4j — the tests are
   the same file run three times via the `store` fixture.

## Order of work (each step green on fake + LadybugDB before the next; Neo4j at the end of steps 2, 4, 6)

1. `store/code.py` constants + row shapers + `test_store_row_shapes.py` growth. Test 1.5a.
2. Schema (`REL_TABLES` shape change, `ensure_schema` with `ALTER TABLE ... ADD IF NOT EXISTS`,
   `CONSTRAINTS`, `INT_FIELDS`/`FLOAT_FIELDS`) and the write methods on all three stores; `test_store_code.py`.
3. Loaders, `get_*` with access, `stats()` (+ `test_store.py:107`), the three-per-label delete sweep
   in `delete_source`/`delete_passages_for_source`, SYNONYM/TUNED widening via `label_of`
   (delete `_node_label` at `ladybug.py:1141` and the `:Entity|Passage` list at `changesets.py:71`);
   `test_store.py`, `test_store_graph.py` growth.
4. Settings declaration (item 2 above).
5. `GraphIndex`: `NodeKind` enum, `CodeNode`, `DirectedEdge`, vertex blocks, specificity array,
   `name_index`, `Edge.omega`/`code_kinds`, `build_igraph(scale)`, `graph_with_edits(edits, scale)`,
   `graph_for_scale`, `scoped()` per-kind visibility (S2.5) copying `omega`/`code_kinds`, `entity_boost`
   from code `boost`; `simulate.py:110`; `test_graph_index.py` (grow `Tiny`), `test_access.py`.
6. Parity guard, `label_of` tests are WP0's (already there), full three-store matrix, lint.

## Pinned tests you own

`test_store.py:107` (stats keys). Anything else that breaks is either yours to update (say so in the
ledger) or a sign you changed a contract you should not have — check the plan before editing it.

## Done when (PLAN.md line 261)

All three store matrices green, lint green, and — extra, cheap — a script-free check that a copy of a
pre-change LadybugDB file opens with the widened schema: create one with the OLD code (check out
`code-graph`'s parent commit `main` in a second scratch worktree under `/tmp`, index `samples/
acme_robotics.md` through the pipeline with `FakeOllama` into `/tmp/hippo-wp1-old.lbug`), then open
that file with YOUR `LadybugStore`, and assert `CALL show_connection('SYNONYM')` lists the widened pairs
and the old synonym rows still load. Record the outcome in the ledger. Then commit, ledger summary
(every file touched, every pinned test changed, the exact new store method names and row shapes so the
WP2 worker can be briefed from it), `horch tell orchestrator "[<role>] DONE: wp/wp1 ..."`, close pane.
