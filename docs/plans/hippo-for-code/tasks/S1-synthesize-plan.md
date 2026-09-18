# S1 — Write the unified implementation plan (worker: fresh Opus)

You are a herdr WORKER. Read `00-shared-context.md` first (ignore its research-output format; your output
contract is below). Your deliverable is ONE file: `docs/plans/hippo-for-code/PLAN.md`.

## Inputs, in reading order

1. `docs/plans/hippo-for-code/research/R5-reconciliation.md` — the A-vs-B conflict matrix and open questions.
2. The verdict tables (top of each file) of `research/R1-store-graph.md`, `R2-ingest-evals-tests.md`,
   `R3-retrieval-analysis.md`, `R4-spike-results.md`, `R6-web-mcp-cli-docs.md`. Read the bodies only for the
   claims you need to settle a decision or to name a file/function precisely.
3. `inputs/A-existing-plan-phase1.md` in full. Your plan REPLACES it, so it must be at least as concrete.
4. `inputs/B-design-against-built.md` in full.

Do not read source code except to resolve a contradiction between two research files, and then only with a
targeted `grep -n` / `sed -n`. The research files are your evidence; cite them (`R1.3`, `R4 T1`).

## Conflict rule (binding)

- A's "User decisions (2026-09-07)" block and its "Deferred with reasons" list are the DEFAULT. They were
  decided by the user.
- B overrides A only where (a) B argues the point explicitly (its §13 "Cut, and why", its D1–D5 rationale),
  or (b) the research shows A's choice does not fit the built system (e.g. R4 proves a DDL path impossible,
  R1/R3 show a fidelity break).
- Everything B adds that A deferred (CCG slices, incremental `changed_only` re-index, `Override`/`Unresolved`/
  `BindingRule` tables, `replay_set` + regression gate, optional LSP resolvers) gets an explicit
  **phase 1 / phase 2** call with a one-line cost estimate (files touched, new deps, LLM cost, test burden).
- Where you reverse an A user decision, you MUST list it under "Confirm with user" with the reason.
- The architectural tiebreaker is R4: if node-table `ALTER TABLE ADD` with defaults is not reliable on a
  closed-and-reopened LadybugDB file, B's D1 (symbol as `Entity` column) is out and the plan uses A's tables.
  If it IS reliable, weigh D1's "keeps the diff small" claim against R1's findings on `remove_orphans`,
  `scoped()`, id collisions and the Graph page, and decide. Either way, write the reasoning down.

## Output contract for `PLAN.md`

Same shape as A so it can replace it, in this order:

1. `# <title>` and a **Context** section: what hippo is today in three sentences (from R1–R3, not from B's
   table), the problem statement (B §2 is good; keep it to one paragraph), and a **User decisions carried
   forward** block that reproduces A's decisions verbatim with a status per line: `kept` / `kept, moved to phase 2` /
   `reversed (see Confirm with user #n)`.
2. **Decision Log**: one entry per row of R5's conflict matrix. Format:
   `D<n> <topic>` — Options: A / B / other — Evidence: research ids — Decision — Why (≤3 sentences).
   No decision without a cited research id.
3. **Design summary**: the graph model (tables, columns, rels, properties, FROM/TO) as a code block in A's style;
   the ω table (one merged table; where A and B disagree numerically, pick and footnote); the retrieval rule
   (edge weight formula, specificity, seeding, `link_top_k` treatment) with the exact FIDELITY.md consequence
   sentence that must be added; the id scheme; the package layout (final module paths).
4. **Work packages** WP1…WPn in dependency order. For each: goal, files to create (marked `new`) and files to
   modify (each verified against a research file: write `(R1.5)` after the path), exact function signatures,
   store method names identical across LadybugDB / Neo4j / FakeStore, settings added with defaults and
   `SETTING_RULES` bounds, the tests for that WP (file names, what each asserts, which store matrix it runs on),
   and a "Done when" line. Include the exact DDL that PASSED in R4 for any schema change (paste the fenced block).
5. **Test fixture plan**: the checked-in fixture tree (verbatim files, as A §2.7 does), and how tests build a
   real git repository from it in `tmp_path` with N commits (a nested `.git` under `tests/fixtures/` cannot be
   committed). Name the helper and where it lives (`tests/conftest.py` fixture?) per R2's conventions.
6. **Verification (end to end)**: the manual walk-through on this machine (`just` recipes from R2, the pages
   from R6, the MCP tools), and the two CI gates (deterministic re-index; if incremental is in phase 1, full == changed-only).
7. **What changed vs A / vs B**: a two-column table, one row per material difference.
8. **Confirm with user**: numbered list of reversed or newly-made decisions the user should ratify, each with
   the alternative and what it would cost to flip later.
9. **Known limitations to state in the docs** and **Out of scope (recorded so nobody looks for it)**.
10. **Docs to update**: `docs/CONTRACTS.md` rows in its exact format (R6.8), the `docs/FIDELITY.md` "Code sources"
    section text, `docs/MCP.md` additions, README paragraphs with the target section names.

## Quality bar

- Every existing path, function, class, setting, template and route you name must appear in a research file
  (cite it) or be marked `new`. No invented names. If a research file says something is `Missing`, you may only
  reference it as `new`.
- Every store method appears three times in your plan (LadybugDB, Neo4j, FakeStore) or once with "identical on
  all three" and a test that runs on all three.
- Plan length: about the size of A (~300 lines is fine, 500 is the ceiling). Tables over prose. No filler.
- Write the file incrementally (sections 1–3 first, save; then WPs; then the rest) so a crash loses little.
- When the file is complete, run a self-check: `grep -o 'src/hippo/[a-zA-Z0-9_/]*\.py' PLAN.md | sort -u` and,
  for each path not marked `new`, confirm it exists with `ls`. Fix misses before reporting.

## Protocol

Progress notes in the ledger at each section boundary. If R4 or R5 is missing or contradicts R1, ask the
orchestrator with `horch tell orchestrator "[<role>] ..."` and wait. When complete:
`horch tell orchestrator "[<role>] DONE: PLAN.md written, <n> WPs, <m> confirm-with-user items"`. Do NOT close
your pane after DONE: you will receive review findings to apply. Wait for the orchestrator's next message.

## Orchestrator notes: cross-cutting findings you must not miss

These came out of the six research files; each is expanded in the file cited. Address every one in the plan.

1. **Feasibility is not the tiebreaker (R4).** B's D1 columns work (T1, T2, T4, T6 all PASS on reopen) AND A's
   multi-pair `CODE_EDGE` works (T7 PARTIAL: reads across pairs fine; writes must bind concrete label pairs).
   Decide D1-vs-tables on fit: R1 gotcha 2 (two hard-coded `Entity|Passage` label lists in two dialects),
   R1.8 (entity/fact ids are NOT source-namespaced, passage ids ARE), R1 gotcha 6 + R6 C2–C4 + R6 gotcha 3
   (new node kinds touch 5 Python + 2 JS files with literal `==` checks; `GraphIndex.node_kind` is a two-value
   enum independent of any stored column), R3 gotchas 6–7 (`scoped()` drops entities with no mention edge to a
   visible passage and drops facts whose endpoints vanish).
2. **FTS is unproven (R4 T3 PARTIAL).** `CONTAINS`/regex scan 100k rows fast. B's `search_symbols` via FTS is
   not a safe assumption; A's in-memory `name_index` or a `CONTAINS` query are the proven options.
3. **Scale (R4 T8).** 50k nodes + 200k rels took 537 s to insert. The plan must state batch sizes for
   `UNWIND $rows` writes and record this as a known limitation or a perf target with a measurement gate.
4. **B's ω weighting is inert as written (R3.3-omega).** If every structural relation is also a Fact (count 1),
   `max(1, ω × structural_scale)` never lets ω < 1 matter unless `structural_scale > 1`. Resolve explicitly:
   either structural relations are NOT double-written as facts, or the pair weight for structural-only pairs is
   ω-only, or state that ω is for display/paths and the scale is the only PPR lever.
5. **B's anchor placement is contradicted (R3.1-B); A's fits (R3.1-A)** but requires moving the DPR-fallback
   decision (`retriever.py:261`), which A already states. Also `phrase_weights` is a per-vertex array, so any
   vertex kind can carry reset mass (R3 gotcha 5).
6. **B's synthetic `Paths` passage breaks pinned tests (R3.8-prompt; `test_ask.py:55/:60`)** because it puts a
   fake id in `Answer.passage_ids`; A's separate `context_block` kwarg does not. Prompt itself needs no change (R2-21).
7. **Golden-set replay (R2 gotcha 3, R3.7-set).** `trace_from_dict`, `replay_filter`, stored `Trace` per eval
   result all exist; but `runner.run_question` cannot be reused (no `fact_filter` param; it also calls the
   answerer and judge). `replay_set` is a new loop over stored results calling `Retriever.retrieve` directly.
8. **`scoped()` rebuilds `Edge` field-by-field (`graph_index.py:371-373`)**, so any new `Edge` field must be added
   there or restricted users silently lose it.
9. **`trace_from_dict` is strict (`Cls(**row)`, R3 gotcha 8)**: new `Trace`/`TopNode`/`SeedEntity` fields need
   defaults and no field may ever be removed, because evals store traces permanently.
10. **Settings page `max="1"` (R1.7, R6 C5, R3 gotcha 9)**: template must read `SETTING_RULES` bounds; this also
    fixes a latent bug for `passage_node_weight`. New settings need `SETTING_HELP` lines (R3 gotcha 10).
11. **Pinned tests the plan must list as "update in this WP"**: `test_indexer.py` counts dict ×6 (R1 gotcha 4,
    lines 55, 98, 212-222, 238, 317) + `test_store.py:107` stats keys; `test_ingest_pipeline.py:138,205` chunk
    titles; `test_retriever.py:135` node kinds, `:136` timing keys; `test_analysis_changesets.py:47` VALID_OPS;
    `test_analysis_explain.py:114` edge kinds; `test_mcp_server.py:17` TOOL_NAMES (R6 gotcha 2, README says "four").
12. **Greenfield items neither plan can lean on (R2)**: no `readers.lang_of`; `clone_repo` hardcodes `--depth 1`;
    no per-passage `path`/`kind` column (path lives only in the title string); no per-file bookkeeping; no
    OpenIE skip flag; `FakeOllama` cannot reproduce real-model noise on code (R2 gotcha 4); real-git tests exist
    only in `test_ingest_repos.py` (`make_checkout` pattern, R2 gotcha 8). Default pytest store is LadybugDB,
    not fake (R2-16); `HIPPO_TEST_STORE=fake|neo4j` selects.
13. **`store/base.py` is the Neo4j backend's base class (R1.1)**, not a shared interface; parity is by convention
    and tests only. Name the three files explicitly for every store method.
14. **Toolchain (R4 T9–T11)**: tree-sitter 0.26 requires `QueryCursor`; fragments parse tolerantly; TSX parses
    plain JS; igraph has `community_leiden` and directed shortest paths; `tsserver`/`node` are on PATH, `pyright`
    is not. Neo4j tests: `just test-neo4j` (port 17687, password `hippo-password`), not the figures in A.
