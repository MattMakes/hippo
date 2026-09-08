# WP4d — Docs: CONTRACTS, FIDELITY adaptation 15, MCP.md, README, docs/design

Read `impl/00-impl-context.md` first. Worktree `.worktrees/wp4d`, branch `wp/wp4d`. No Neo4j leg: you
change no code. `just lint` must still pass (it does not lint markdown outside `docs/plans`, but run it).

`code-graph` now contains WP1-WP3, and WP4a/b/c (API+MCP+CLI, web pages, evals) are being built in
parallel by three other workers. **You edit only `docs/CONTRACTS.md`, `docs/FIDELITY.md`, `docs/MCP.md`,
`README.md` and the new `docs/design/` directory.** Where a name you must document is owned by a parallel
worker (endpoint query parameters, MCP response fields, CLI flags, eval metric names), take it from the
plan; the orchestrator will hand you their ledger summaries when they land so you can correct the few
that differ, before your branch merges.

Your spec is PLAN.md **§Docs to update (lines 528-568)** in full — it prescribes the exact format of each
file — plus the FIDELITY paragraph and the three sentence edits in §Retrieval rule (lines 121-125),
§Known limitations (lines 515-522), §Out of scope (line 526), the Settings table (lines 129-141), and
Confirm #5 (line 513). Evidence: `research/R6-web-mcp-cli-docs.md` C12 (CONTRACTS.md's fenced plain-text
block format, not a table; its "## To write" heading is stale — append there), C13 (FIDELITY.md is a flat
numbered list of 14 adaptations; you write **15, "Code graph"**, not a section), C9/`MCP.md:136-227` (one
request/response JSON pair per tool), gotcha 2 (`README.md:228` says "four MCP tools"; it becomes nine).
Also `research/S0-spikes.md` spike 3 for two limitations to state: a pandas-sized repo (~34k symbols) now
exceeds `MAX_CHUNKS = 20_000` where its line windows fit before, and vector reload cost at the ceiling
(~117 MiB) on every graph-version bump.

## Corrections to the plan's own wording that the implementers found (write the TRUE sentence)

- **Dense-seed consequence (Retrieval rule, line 118).** The plan says a prose question over a mixed
  corpus "behaves exactly as today unless a code passage out-ranks every prose passage on dense
  similarity". That is only true at `code_dense_seeds = 1`. The shipped mechanism is Ruling 1b as written
  (a dense seed is admitted when its passage is in the OVERALL top `code_dense_seeds` by `dpr_scores`),
  so the true sentence is: at defaults a prose question over a mixed corpus is unchanged unless a code
  passage is among the overall top `code_dense_seeds` dense hits; `code_dense_seeds = 1` gives the
  original condition; code passages remain ordinary passages and can rank on DPR merit alone. The real
  fidelity guarantee is the inert-settings one (the four settings at 0/0/False/0 rank a mixed corpus
  identically to the same corpus indexed with no code graph at all — WP3 tests this literally).
- **FIDELITY.md `:120-121`** (the `max(fact count, mention, synonym score)` rule) needs its fourth term
  `ω × code_structural_scale`; WP1 left it for you.

## What the previous workers built (read their code — the code is the truth, the plan is the intent)

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

1. **`docs/CONTRACTS.md`** — a new `### code graph` heading with the block quoted at PLAN lines 532-560,
   corrected to the signatures actually in the code (`grep -n "^def \|^    def \|^class " ` the modules),
   plus rows appended to the existing `src/hippo/web/`, `mcp_server.py` and `cli.py` blocks.
2. **`docs/FIDELITY.md`** — adaptation 15 in the file's exact `N. **Title.** ... Reason: ...` shape,
   covering every item in the list at line 562; the inertness paragraph from line 123 verbatim; and the
   **three** sentence edits at `:67-72`, `:120-121`, `:153-155` as §Retrieval rule specifies (the line
   numbers are from before this work — find the sentences by text). Every claim you write must be
   literally true of the code on `code-graph`: check `build_igraph`'s weight expression, the retriever's
   gate, and `split_question` before you write the sentence that describes them.
3. **`docs/MCP.md`** — "## The five tools" → nine; a `###` per new tool with one request/response JSON
   pair in the existing shape, the `AmbiguousSymbol` → `ToolError` example, and the new fields on
   `hippo_search`/`hippo_ask`. Field names come from WP4a's code; until it lands use the plan's and mark
   each with `<!-- verify against WP4a -->`, then remove the markers when the orchestrator sends the summary.
4. **`README.md`** — the new **"Code"** section after "How it works" (line 568 lists its content); the
   eleven `code_*` rows in the configuration table; "Where the code lives" gains the five new modules;
   `README.md:228` "four MCP tools" → nine. No new env var anywhere.
5. **`docs/design/`** — `README.md` mapping each principle of the code-only design to where it lives in
   hippo and what phase 1 defers (D12 CCG, D13 incremental, D14 overrides, D15 unresolved, D16 replay
   gate, D23 LSP, typed restart, `Field` nodes). The two verbatim documents `code-hipporag-design.md` and
   `code-only-design.md` are the USER's originals and are not in the repo: write `docs/design/README.md`
   so it links to both by those names, and put a one-line placeholder file at each path saying the
   document is supplied by the user (the orchestrator has asked for them). `inputs/B-design-against-built.md`
   is NOT one of them unless the orchestrator tells you so. Do not invent content.
6. **Known limitations** — every bullet of PLAN lines 517-522 plus the two spike-3 facts, in whichever
   file the existing "limitations" content lives (check README and FIDELITY; follow the precedent).

## Done when

Every file reads as if the feature had always been there, every path/function/setting/tool name you
wrote exists on `code-graph` (write a tiny `grep` loop over your own doc and run it — paste it in the
ledger), lint green. Commit, ledger summary (files; the list of names you marked `verify against`),
`horch tell orchestrator "[<role>] DONE: wp/wp4d ..."`, and **keep your pane open**: the orchestrator
will send you the WP4a/b/c summaries for a final correction pass before merge.
