# WP3 — Retrieval, paths, answer serialization

Read `impl/00-impl-context.md` first. Worktree `.worktrees/wp3`, branch `wp/wp3`.
Neo4j test container: name `hippo-neo4j-wp3`, port **17695**.

This is the WP with the most judgment in it: it is where the plan's fidelity guarantees are either kept
or silently broken, and gotchas 3 and 4 in the rulebook both live here.

## Two phases — read this first

You start EARLY, to shorten the critical path. `code-graph` contains WP1 (store + `GraphIndex` with code
vertices, `graph_for_scale(scale)`, all eleven `code_*` settings declared) but NOT yet WP2 (extractors,
the fixture tree) or WP2i (indexing writes the graph; the `code_index` fixture). Those are being built in
parallel and will merge while you work.

**Phase 1 (now):** everything in Scope below that does not need an indexed fixture — `anchors.py`,
`paths.py`, the retriever, answer serialisation, `simulate.py`, the settings template — tested against
indexes you build in the tests through the store's own methods (`add_symbols`, `add_code_edges`,
`link_definitions`, `add_commits`, ... — the row shapes are in the WP1 handoff below) plus the existing
prose `indexed` fixture. Write those store-built tests so they mirror the fixture the plan draws
(`pyapp.orders.OrderService.place`, `pyapp.billing.total`, `table orders`, ...), using the qualnames from
PLAN §2.2a and the ids from `hipporag.text.make_id` conventions (`symbol-`, `data-`, `commit-` prefixes via
the `codegraph.model` id functions once they exist; until then compute them with `make_id` the same way:
`make_id("symbol-", f"{source_id}:{path}:{qualname}")`). Do NOT add tree-sitter or sqlglot as a dependency
yourself and do not import `codegraph` (it may not exist on your branch yet): `split_question`'s
"lines that parse as code" is a regex heuristic (indent + brackets/operators/`def`/`return`/`;`/`=>` etc.),
which is also the cheaper choice per question. Commit phase 1 green on all three stores, write the ledger
note, then `horch tell orchestrator "[<role>] PHASE 1 DONE: wp/wp3 ..."` and **keep your pane open**.

**Phase 2 (when the orchestrator tells you WP2i has merged):** `git merge code-graph` into `wp/wp3`
(the one time you may merge), resolve `tests/conftest.py` if both sides added fixtures, then add the
`mixed_index` fixture and every fixture-based test in 3.5 (the mixed-memory test FIRST, `place` in the
top 3, `test_ask.py`'s exact block string, `test_paths.py` over `code_index`, S2.12/S2.13/S2.14 over the
real fixture). Replace any store-built test that the fixture now covers better; keep the ones that
construct a case the fixture cannot (the synonym-guard style). Then the normal DONE.

WP2b (git history) may also merge during phase 2 — see "History" below.

Your spec is PLAN.md **WP3 (lines 368-388)** in full, the **Retrieval rule (lines 100-125)**, the
Settings paragraph (line 143: the `settings.html` `min/max/step` fix), and Decision Log D5, D10, D18,
D19, D20, D21. Evidence: `research/R3-retrieval-analysis.md` — read all of it; it is the line-by-line map
of `retriever.py`, `ask.py`, `answerer.py`, `prompts.py`, `analysis/simulate.py` and the tests that pin
them — and `research/R6-web-mcp-cli-docs.md` C5/C6 for the settings template.

## What the spikes found — binding for this WP (`research/S0-spikes.md`, spike 1, read it)

**The plan's bare-word anchor rule fails as written**: bare word ≥ 3 chars + stoplist + exact `name` hit
fired on 16% of 118 prose questions against Django's symbol set and 4% against hippo's own. **Ship the
plan's fallback (b)**: a bare word anchors only when its *surface form* is code-shaped — qualified
(`a.b`), backticked, PascalCase, snake_case, camelCase or ALL_CAPS. That measured 0/118 false anchors on
all four repos tested, at the cost of 5 of 18 bare-identifier questions (acceptable; dense seeds still
cover them). Two one-line corrections go with it: apply the ≥ 3-char test to the *matched name segment*,
not the raw token (or `S.O.B.` anchors on Django's `DateFormat.b`), and require dot-separated parts to be
≥ 2 chars each. Stack frames, exceptions, fenced code and diffs are unaffected. Write the spike's prose
corpus into `test_anchors.py` as a "prose → []" table (the spike file lists the questions).

## What the previous workers built (read the code, not just this)

**WP1 (store + GraphIndex), merged as 240d348.** `src/hippo/store/code.py` holds the vocabulary
(`CODE_BATCH=5000`, `SYMBOL_KINDS`, `DATA_KINDS`, `CODE_EDGE_KINDS`, `SPECIFICITY_KINDS=(INVOKES,READS,
WRITES)`, `CODE_EDGE_PAIRS`), the row shapers (`symbol_write_row`, `data_object_write_row`,
`commit_write_row`, `code_edge_write_rows`, `modifies_write_rows`, `refers_to_write_rows`) and the Neo4j
`CodeQueries` mixin, twinned in `store/ladybug.py` and `tests/fakes/fake_store.py`. 22 methods on every
store: writers `add_symbols`, `add_data_objects`, `add_commits`, `add_code_edges`, `link_definitions`,
`add_modifies`, `add_precedes`, `add_refers_to`, `set_symbol_communities`; readers `get_symbols`,
`get_data_objects`, `get_commits`; nine `load_*` loaders incl. `load_code_embeddings`; and
`delete_code_nodes_for_source`. Row shapes are the WP1.3 table's — read the shapers. `GraphIndex`:
vertex order entities → symbols → data → commits → passages LAST, `passage_position = v -
first_passage_vertex`; `NodeKind` five-valued with `SYMBOL`/`DATA`/`COMMIT`; `CodeNode`, `DirectedEdge`;
`code_out`/`code_in`, `name_index`, `Edge.omega`/`code_kinds`, `Edge.weight_at(scale)`; `specificity`
holds the DENOMINATOR (entity = mentions, symbol/data = in_degree+1, commit = 1, passage = 0) with
`entity_passage_count` kept as an alias; **`graph_for_scale(scale)`** memoised — your retriever calls it
when no explicit `graph=` is passed; `scoped()` carries omega/code_kinds/boost. All eleven `code_*`
settings are in `DEFAULT_SETTINGS`/`SETTING_RULES` with `SETTING_HELP` text.
**Landmine:** `analysis/simulate.py` has `SIMULATABLE_SETTINGS` and `INGEST_SETTINGS` and
`test_analysis_simulate.py` asserts they partition `SETTING_RULES` exactly. `Tiny` (`test_graph_index.py`)
and `small_graph` (`test_store_graph.py`) fixtures now use `make_id`-shaped ids. Full handoff in the
`backend-developer-1` ledger entry (`horch sessions`).

<!-- ORCHESTRATOR FILLS FROM THE WP2 / WP2i LEDGER SUMMARIES AT PHASE 2 -->

## Scope

1. **`hipporag/anchors.py`** (3.1, S2.12, S2.13) — `find_anchors(question, index)`, `split_question(text)`,
   `MAX_ANCHORS = 20`, `MAX_MATCHES_PER_TOKEN = 8`, the pre-cap `n_matches` → `ambiguous` (> 10) → seed up to
   8 at `code_seed_weight / n_matches` ordering, path-qualified matches never split, stack-frame patterns
   with `0.8 ** k`, the trailing `SomeError:` exception anchor at 0.8, fenced blocks and unified diffs,
   bare words ≥ 3 chars + stoplist + exact `name` hit, everything filtered through the given index's
   `idx_of` and `node_kind ∈ {symbol, data}`. Pure, deterministic, no LLM. **Apply spike 1's
   recommendation for the bare-word rule** (filled in above).
2. **`hipporag/paths.py`** (3.2) — `resolve_symbol` (`AmbiguousSymbol` / `UnknownSymbol`),
   `shortest_code_path`, `direct_edges`, `code_paths_for`, `render_triples`, `render_block`,
   `blast_radius` (grouped by community in its rendering), `exception_path`, `history` over `PRECEDES`.
   Over `GraphIndex.code_out`/`code_in`, never `DEFINED_IN`, ω ≥ θ; simulation edge edits do not affect
   these tools (docstring says so).
3. **`hipporag/retriever.py`** (3.3) — the new `Trace`/`TopNode`/`RankedPassage`/`SeedSymbol` fields, all
   defaulted, none ever removed; anchors + dense seeds after the fact filter and before the DPR-fallback
   decision (`if not kept_fact_indices and not trace.used_code_seeds`); **gate = lexical anchor only;
   dense seed admitted only in the OVERALL top `code_dense_seeds` by `dpr_scores`** (gotcha 3);
   `MAX_CODE_SEEDS = 20` outside the `link_top_k` cut; `reset = phrase_weights + code_weights +
   passage_weights`; `code_community_boost` after PPR; the scaled igraph via
   `index.graph_for_scale(settings["code_structural_scale"])` when no explicit `graph=` is passed;
   `select_fn` injected callable (S2.14) with keep/drop/expand, keep-all on any error, unknown ids ignored,
   `expand` neighbours appended after the kept list at score 0.0 with `via_expand=True` and EXCLUDED from
   the `qa_top_k` slice; `trace.paths/tests/history` + `timing["paths"]` only when `used_code_seeds`;
   `question_prose`/`question_code` from `split_question`, the embedding and fact-filter prompt receiving
   `prose` only (fallback to full text when empty), the QA prompt the full text.
4. **`ask.py` / `answerer.py` / `prompts.py`** (3.4) — `Answer.context_block: str = ""`;
   `answer_question(..., context_block="")` prepends the `Title: Code graph` pseudo-passage inside so it
   never enters `passage_ids`; `answer_from_trace` renders the block gated on `used_code_seeds`;
   `prompts.CODE_GRAPH_HEADER` and `prompts.code_select_messages`; the S2.15 fixed grammar (triples,
   `Tests:`, `Commits:`, `Subsystems:`), cut at `code_triples_chars` on a line boundary with
   `… (+N more)`. `ask.search` supplies the LLM-backed `select_fn` default.
5. **`analysis/simulate.py`** — `replay_select(baseline)` beside `replay_filter`, passed to `retrieve()`
   so a slider move never costs an LLM call; the scale already flows through `graph_with_edits(edits,
   scale)` (WP1) — verify, don't rebuild.
6. **Settings UI** — `web/templates/settings.html:76` reads `SETTING_RULES` for `min`/`max`/`step` instead
   of the hard-coded `max="1"` (this also fixes `passage_node_weight`); review the `SETTING_HELP` lines WP1
   added and sharpen any that read badly. A test saves `code_seed_weight = 2` through the web client.
7. **`tests/conftest.py`** — the `mixed_index` fixture (`samples/acme_robotics.md` AND the code fixture in
   ONE memory, all three stores).
8. **Tests** (3.5) — `test_anchors.py`, `test_paths.py`, and in `test_retriever.py` **the mixed-memory test
   FIRST** (prose question at defaults → `used_code_seeds is False`, zero extra chat calls vs the prose-only
   index, `context_block == ""`, no `paths` key in `timing_ms`, same top-3 passage ids as the prose-only
   `indexed` fixture), then every other bullet in 3.5 including S2.12 (a 40-line traceback + one sentence
   embeds only the sentence — assert the text handed to `embed_one`), S2.13 both branches, S2.14 via an
   injected `select_fn` (no `FakeOllama` dispatch rule — do not write one), S2.16 (a pre-change stored
   trace JSON loads), and `test_ask.py`'s exact block string + the `code_triples_chars=60` cut.
   `tests/unit/test_retriever.py:190` and `test_analysis_simulate.py:54` (zero chat calls on replay) must
   stay green.

## History (WP2b runs in parallel)

`GraphIndex` already loads `Commit` vertices, `MODIFIES` and `PRECEDES` (WP1), so `paths.history()` and the
`Commits:` lines need nothing from WP2b. For the `history(place)` test, build the commits directly through
the store (`add_commits`/`add_modifies`/`add_precedes` with the row shapes in WP1's ledger summary) inside
the test, then load a `GraphIndex` — do not wait for the `git_index` fixture. If `git log code-graph`
shows WP2b merged before you write that test, you may use `git_index` instead; either is acceptable.

## Pinned tests you own (S2.18)

`test_retriever.py:135` (top-node kinds — stays green on prose; the code fixture gets its own `⊆`
assertion), `:136` (timing keys — stays green on prose because `paths` is written only when
`used_code_seeds`), `test_analysis_explain.py:114` (`edge["kinds"]` — both sides move together).
If any OTHER prose assertion moves, you have broken fidelity: stop and find out why.

## Done when (PLAN.md line 388)

A stack trace with no surviving facts still seeds PPR, and the prose suite is byte-identical with
`code_seed_weight=0 code_dense_seeds=0 code_select=False code_structural_scale=0` (write that as a test
over `mixed_index`, not as a claim). Three stores + lint green. Commit, ledger summary (files, pinned tests
changed, the exact `Trace` field names and the `SelectResult`/`select_fn` signature, the `context_block`
grammar as implemented, anything WP4's routes/MCP/CLI/web/evals workers must know),
`horch tell orchestrator "[<role>] DONE: wp/wp3 ..."`, close pane.
