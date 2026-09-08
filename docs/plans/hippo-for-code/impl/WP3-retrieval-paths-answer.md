# WP3 — Retrieval, paths, answer serialization

Read `impl/00-impl-context.md` first. Worktree `.worktrees/wp3`, branch `wp/wp3`.
Neo4j test container: name `hippo-neo4j-wp3`, port **17695**.

This is the WP with the most judgment in it: it is where the plan's fidelity guarantees are either kept
or silently broken, and gotchas 3 and 4 in the rulebook both live here. `code-graph` contains WP1
(store + `GraphIndex` with code vertices, `graph_for_scale(scale)`, all eleven `code_*` settings declared),
WP2 (extractors, fixture) and WP2i (indexing writes the graph; the `code_index` fixture yields an indexed
fixture on all three stores). WP2b (git history) is being built in parallel — see "History" below.

Your spec is PLAN.md **WP3 (lines 368-388)** in full, the **Retrieval rule (lines 100-125)**, the
Settings paragraph (line 143: the `settings.html` `min/max/step` fix), and Decision Log D5, D10, D18,
D19, D20, D21. Evidence: `research/R3-retrieval-analysis.md` — read all of it; it is the line-by-line map
of `retriever.py`, `ask.py`, `answerer.py`, `prompts.py`, `analysis/simulate.py` and the tests that pin
them — and `research/R6-web-mcp-cli-docs.md` C5/C6 for the settings template.

## What the previous workers built and what the spikes found (read the code, not just this)

<!-- ORCHESTRATOR FILLS FROM THE WP1 / WP2 / WP2i LEDGER SUMMARIES AND research/S0-spikes.md -->

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
