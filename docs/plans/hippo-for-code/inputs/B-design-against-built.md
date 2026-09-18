# hippo for code: the design, against what is already built

Written 2026-09-07 against the repository as packed (148 files; `src/hippo/…`, `docs/CONTRACTS.md`, `docs/FIDELITY.md`). This replaces the earlier abstract designs with one that fits hippo's modules, contracts and house rules. Everything the earlier documents argued from the research (symbol-level graph, confidence-weighted edges, PPR as the expansion operator, LLM as filter not query author, overrides as data, evals from git) is kept; the shape now comes from the code.

---

## 1. What hippo already is, measured against the research design

Read as a checklist. "Built" means it exists in the repo and the same tests run on LadybugDB, Neo4j and the fake.

| Research requirement | hippo today | Status |
|---|---|---|
| PPR over a phrase/passage graph, in-process, seeded from LLM-filtered facts, node specificity, damping 0.5 | `hipporag/graph_index.py` (igraph prpack) + `hipporag/retriever.py`, exact to the reference (`docs/FIDELITY.md`) | **Built** |
| One graph, two backends, PageRank outside the DB | `store/ladybug.py` and `store/base.py`+`memory.py`; `GraphIndex.load()` rebuilds on `graph_version` | **Built** |
| Synonym edges (τ=0.8, ≤100/entity), incremental over new entities only | `indexer.find_synonyms` | **Built** |
| Overrides as data: settings, node boosts, edge weights, synonyms, saved then applied, graph version bumped | `analysis/changesets.py` (`set_setting`, `set_edge_weight`, `add_synonym`, `set_node_boost`), `TUNED` rel, `Entity.boost` | **Built** |
| What-if replay before committing | `analysis/simulate.py` (replays the filter, diffs ranks) | **Built** (per question; no golden-set replay yet) |
| Question trace: seeds with weights and origin, top PPR nodes, ranked passages with score decomposition, filter verdicts, timings | `Trace` dataclass; Analyze page; `analysis/explain.py` (linked seeds, shortest path ≤3 hops, "why" sentence, subgraph) | **Built** |
| Golden sets + deterministic metrics (recall@k, gold rank), runs as immutable history | `evals/` (`question_maker`, `runner`, `metrics`, LLM judge) | **Built** for prose; nothing derived from git |
| Access-scoped graph so PPR never crosses a hidden node | `access.py`, `GraphIndex.scoped()` | **Built** |
| Agent surface | `mcp_server.py`: search / ask / remember / sources / whoami | **Built** |
| Git repos as a source | `ingest/repos.py`: shallow clone, `walk_repo`; `chunker._chunk_code`: 1500-char line windows; then **OpenIE runs on code chunks** | Built, but code is treated as prose |
| Symbol nodes (module/class/function), structural edges (contains/imports/invokes/inherits), provenance confidence | none | **Missing** |
| Lexical anchors from identifiers / stack traces in the question | none (question → fact embeddings only) | **Missing** |
| Deterministic path queries (call path, blast radius, exception path) | none (`explain.py` does a generic shortest path for display only) | **Missing** |
| Overrides that survive re-indexing | `TUNED` edges hang off entity nodes; `remove_orphans` (`memory.py:175`, `ladybug.py:525`) `DETACH DELETE`s an entity that loses its last mention, taking its tuned edges with it | **Gap** |
| Incremental re-index by file; git history | `pipeline.reindex` clears a whole source; clone is `--depth 1` | **Missing** |
| Binding rules for calls static analysis cannot see; unresolved-reference leaderboard | none | **Missing** |

Two consequences of the current code path drive the design. First, cost: a 1500-character code chunk costs two LLM calls in `openie.extract` and yields facts like `["def retrieve", "takes", "question"]` — noisy nodes that then get synonym-linked to everything. Second, the graph has no idea that `retrieve` calls `llm_fact_filter`; the only way two code passages connect is through a shared OpenIE phrase. Both are fixed by making the code extractor deterministic and letting it write the same three things the LLM writes today: passages, entities, facts.

---

## 2. The one problem v1.0 solves

> An engineer indexes a repository into hippo and asks a question that contains code — a snippet, a stack trace, an identifier — in the Ask page, over MCP from Claude Code, or in an eval. hippo returns the right functions, the call path between them, the tests and the commits that touched them, and shows on the Analyze page exactly why. Prose sources keep behaving exactly as they do today.

Nothing else is promised. In particular: Python and TypeScript/JavaScript only; other languages keep today's line-chunk behaviour, untouched.

---

## 3. The five decisions

**D1. A symbol is an Entity.** `Entity` gains `kind` (`'phrase'` today's rows, `'symbol'` new), `symbol_kind` (module|class|function|method), `path`, `line_start`, `line_end`, `signature`, `qualname`. Its id is `symbol-` + md5(`repo_source_id:qualname`), so `post` in two files are two nodes, distinct from the OpenIE phrase `post`. Everything that already works for entities — `MENTIONS`, node specificity (`entity_passage_count`), `boost`, `TUNED`, synonym edges, `scoped()`, the Analyze subgraph, the Graph page, changeset ops — works for symbols with no change to `GraphIndex`'s vertex model. This is the decision that keeps the diff small.

**D2. Structure is written as facts.** The code extractor emits deterministic triples with the same shape OpenIE does — `["ledger.post", "calls", "validate_amount"]`, `["validate_amount", "raises", "ValueError"]`, `["PaymentValidator", "inherits", "BaseValidator"]`, `["ledger/post.py", "defines", "post"]` — stored as `Fact` nodes with `provenance` and `omega`, embedded with the same model, `STATES`-linked from the passage that holds the call site. The retriever's question → fact-embedding → LLM filter → seed path therefore works on code without modification, the Analyze page shows structural facts as candidates, and the fact filter can be replayed. Code passages never go to `openie.extract`.

**D3. Structural edges are a fourth edge kind.** `graph_index.Edge` gains `structural: float` (the best ω among structural relations between the pair) and `structural_kinds`. `Edge.weight` becomes `max(fact_count, mention, synonym_score, structural × structural_scale)`, tuned still wins. Because D2 already produces a fact edge (count 1) for every call, the structural term matters for two things: relations that are not facts (`MODIFIED_BY`, `TESTED_BY`, `DEFINES`) and the confidence ω that a fact count cannot express. `structural_scale` is a setting (default 1.0) so a hub-heavy repo can turn structure down without touching prose behaviour.

**D4. Overrides live in their own table and are re-applied at link time.** A new `Override` node (`op`, `a`, `b`, `value`, `provenance`, `author`, `note`, `created_at`) replaces the fragile "hang a TUNED edge off an entity" persistence for anything that must outlive a re-index: rejected edges, asserted edges, glossary synonyms, hub marks, binding rules. `changesets.apply` still writes `TUNED`/`SYNONYM`/`boost` for immediate effect, and additionally records the Override row; `indexer.index_source` re-applies matching overrides after linking. A row whose `a`/`b` no longer resolve is reported as stale, not silently dropped.

**D5. Precision over completeness in extraction, and the gap is measured.** tree-sitter plus a per-language resolver emits only edges it can justify, each stamped with the provenance that produced it and the ω that provenance earns. Every call it cannot bind is kept as an `Unresolved` row (name, file, line, syntactic pattern). That table is the leaderboard; binding rules are written against it.

---

## 4. Graph model changes

Additions only; every existing table, column and query is unchanged so prose sources are bit-for-bit as before.

### 4.1 Nodes

| Table | Change |
|---|---|
| `Entity` | + `kind STRING` (`'phrase'`/`'symbol'`), `symbol_kind STRING`, `path STRING`, `line_start INT64`, `line_end INT64`, `signature STRING`, `qualname STRING`, `name_tokens STRING[]` |
| `Fact` | + `provenance STRING` (`'openie'` for today's rows; `'call'`, `'import'`, `'inherit'`, `'override'`, `'raise'`, `'catch'`, `'define'`, `'test'`, `'commit'`, `'human'`), `omega DOUBLE` (1.0 for openie so nothing changes) |
| `Passage` | + `kind STRING` (`'prose'`, `'function'`, `'class_header'`, `'module_header'`, `'doc'`, `'commit'`), `lang STRING`, `path STRING`, `line_start INT64`, `line_end INT64`, `ccg_json STRING` (the per-function CFG/CDG/DDG slice artifact, present only for `'function'`) |
| `Override` | new: `id, op, a, b, value DOUBLE, text_value STRING, provenance STRING, author STRING, note STRING, created_at STRING, stale BOOLEAN` |
| `Unresolved` | new: `id, source_id, path, line, name, pattern, count INT64` |
| `BindingRule` | new: `id, source_id (null = all), lang, pattern STRING (tree-sitter query), edge_kind, omega DOUBLE, author, created_at` |

`Entity.embedding` for a symbol is the embedding of `signature + first docstring sentence`; `name_tokens` is the camel/snake split, and the synonym search (§5.4) runs on the embedding of `" ".join(name_tokens)` so a README phrase "payment validation" reaches `validate_payment_data`.

### 4.2 Relationships

| Rel | From → To | Properties | Purpose |
|---|---|---|---|
| `STRUCT` | Entity → Entity | `kind STRING, omega DOUBLE, provenance STRING, line INT64, in_branch BOOLEAN, arg_binding STRING` | contains / imports / invokes / inherits / overrides / raises / catches / tested_by / modified_by, one rel table with a `kind` column (LadybugDB needs declared tables; one table keeps `ensure_schema` small) |
| `DEFINES` | Passage → Entity | | the passage that holds the symbol's body; also counted as a mention so specificity and access rules hold |

`MENTIONS` (Passage → Entity) is reused for "this passage references this symbol" — a call site, an import, a name in a docstring or commit message — so that node specificity for a symbol is exactly "how many passages touch it", the same definition prose entities have.

### 4.3 Confidence table (ω by provenance)

Same-file definition 1.0 · resolver/LSP 0.90 · explicit import 0.95 · re-export 0.90 · import-scoped name 0.80 · inheritance resolved 0.90 · fuzzy name only 0.50 · dynamic/reflection 0.30 · `tested_by` by import 0.85, by filename 0.75 · `modified_by` (git blame) 1.0 · human-asserted 1.0 · binding rule: as declared. Stored on the `STRUCT` rel and on the `Fact` so the Analyze page can show it.

---

## 5. Ingest: `src/hippo/ingest/code/`

A new package beside `readers.py`, `chunker.py`, `repos.py`. `pipeline.start_indexing` routes a document to it when `readers.lang_of(path)` is a supported language; every other file follows today's path unchanged.

```
ingest/code/
  __init__.py      supported_languages() -> {"python", "typescript", "javascript"}; extract_repo(root, docs, budget) -> CodeExtraction
  parse.py         tree-sitter grammars; per-file Symbols, calls, imports, inheritance, raises/catches, literals, docstrings
  resolve.py       ReferenceResolver per language: Python (module graph from repo root, __init__ re-exports, relative imports,
                   self/cls method binding via class MRO; optional pyright over LSP when installed), TS/JS (tsserver when installed,
                   tree-sitter fallback). Returns (target_qualname | None, provenance, omega)
  ccg.py           statement-level CFG/CDG/DDG per function (GraphCoder Def. 1) -> compact JSON; slice(ccg, line, h=3, l=20)
  facts.py         CodeExtraction -> passages, entities, facts, struct edges, mentions, unresolved   (deterministic; no LLM)
  history.py       git log --first-parent -n HISTORY_COMMITS (500) + git blame --line-porcelain per file -> Commit passages,
                   modified_by edges symbol -> commit
  rules.py         BindingRule matcher: run each rule's tree-sitter query, emit edges with the rule's kind/omega/provenance "rule:<id>"
```

**Passages a repo produces.** `function` (signature + docstring + body; bodies over `chunk_size_chars` are split at top-level statements into `(part N)` passages sharing the symbol), `class_header`, `module_header` (imports + docstring + top-level names), `doc` (README/markdown sections and docstrings of three or more sentences — these go to OpenIE exactly as today), `commit` (message + touched symbols).

**Facts a repo produces** (all `STATES`-linked from the passage of the call site or definition): `defines`, `calls` (with `in_branch`, `arg_binding` on the rel), `imports`, `inherits`, `overrides`, `raises`, `catches`, `tested_by`, `modified_by`. Fact text is `subject predicate object` like today, so `fact_text()` and the embedding path are unchanged.

**Repos.** `repos.clone_repo` gains `depth` (default `HISTORY_COMMITS`; `--depth 1` stays the behaviour for the `hippo index <path>` of a plain folder). `walk_repo` is unchanged; `pipeline` calls `extract_repo` once per source and hands the prose documents to the existing chunker.

**Incremental.** `pipeline.reindex(source_id)` gains `changed_only=True`: for a repo source it runs `git fetch` + `git diff --name-only <indexed_commit>..HEAD`, deletes only the passages of changed files (`store.delete_passages_for_paths`), re-runs extraction for those files, re-links inbound `STRUCT`/`MENTIONS` from the `Unresolved`-style reverse index of other files' references to names in the changed files, re-applies overrides, bumps the version. `Source.meta` gains `{"commit": sha, "languages": {...}, "unresolved": n}`. `reindex_all` and the `Busy` rule are untouched.

**Cost.** For a 50k-line Python repo today's path makes ~1,400 code chunks × 2 LLM calls; the new path makes zero LLM calls for code and OpenIE only for `doc` passages.

---

## 6. Retrieval changes: `hipporag/retriever.py` and `ask.py`

Three additions, each behind a keyword so every existing call and test is unchanged.

**Anchors.** `ask.search(ctx, question, code=None, …)`. `retriever.anchors_from(question, code)` (new module `hipporag/anchors.py`, deterministic) returns `[(entity_id, weight, origin)]`:

| Input shape | Anchor |
|---|---|
| Stack trace lines `File "x.py", line N, in f` | the symbol whose `path`/`line` range contains N; weight 1.0 for the innermost frame, ×0.8 per frame outward; the exception class name |
| Snippet | tree-sitter (error-tolerant) → called names, attribute chains, imported names, string literals; exact `name` match then `name_tokens` match (0.6) |
| Diff | hunk ranges → symbols at those lines (weight 1.0); `+`/`−` identifiers |
| Bare identifiers in the prose (backticks, `a.b.c`, snake_case, CamelCase) | exact match 1.0, split-token 0.6 |

`Retriever.retrieve(..., seed_nodes: dict[str, float] | None)` adds these to `phrase_weights` after node specificity and boosts, and records them in a new `Trace.anchors` list (entity_id, name, weight, origin). Anchors do not go through the fact filter — they are exact — but they are not exempt from `link_top_k`, so a stack trace with twelve frames still seeds the strongest five, like the reference does with fact entities.

**Structural weight in PPR.** `GraphIndex.load` reads `store.load_struct_edges()` into `Edge.structural`; `scoped()` carries it per pair like synonyms; `graph_with_edits` is unchanged. `DEFAULT_SETTINGS` gains `structural_scale: 1.0` and `omega_threshold: 0.5` (edges below it are loaded but get weight 0 — the LARGER θ, tunable on the Settings page and in simulations).

**Answer block.** `answerer.answer_question` already takes `(id, title, text)` passages. `ask.answer_from_trace` prepends one synthetic passage titled `Paths` when `analysis/paths.py` (§7) returns any, and replaces the body of a `function` passage longer than 60 lines with `ccg.slice()` around the matched line when the trace has an anchor inside that function. Prose questions produce no `Paths` passage, so the QA prompt is unchanged for them.

---

## 7. Analysis: paths, explanations, overrides

**`analysis/paths.py` (new, no LLM).** Runs on `GraphIndex` (igraph over `STRUCT` edges only, filtered by `omega_threshold`):

```
call_path(index, a, b, max_hops=6) -> list[Path]           shortestPaths a→b over invokes/overrides; up to 3
blast_radius(index, symbol, depth=3, omega_min=0.75) -> Radius   reverse invokes/overrides/imports closure, grouped by path prefix,
                                                                 plus reachable tested_by; counts + top-20 by PPR mass of the last trace
exception_path(index, symbol, exc) -> list[Path]           raisers reachable from symbol ∩ catchers among its callers
history(index, symbols, n=3) -> list[CommitRef]            last n modified_by commits per symbol
paths_for_trace(index, trace) -> PathBlock                 the automatic choice: call paths among the kept function anchors/seeds,
                                                           exception path when an exception anchor exists, history for the top passages
```

`Path` carries per edge: kind, ω, provenance, `in_branch`, `arg_binding`. `PathBlock.render()` is the typed-triple text that goes into the answer and onto the page.

**`analysis/explain.py`.** `Explanation` gains `anchors` (from the trace), `paths` (from `paths_for_trace`), and `PassageExplanation.why` learns two more sentences: "Anchored by the stack trace at line 27." and "Reached via `apply_refund -[calls 0.9]-> post`." The subgraph edges gain `kinds` values `struct:invokes` etc. (the Analyze picture already draws `kinds`).

**`analysis/simulate.py` / `changesets.py`.** `Overrides` gains `omega_threshold`/`structural_scale` through `settings` (no new field) and `seed_nodes: dict[str, float]` (try an anchor by hand). New changeset ops, validated like the existing four and described in words like them:

| Op | Keys | Effect on apply | Persistence |
|---|---|---|---|
| `reject_edge` | a, b, kind | `TUNED` weight 0 now; `Override(op=reject_edge)` so the linker never re-creates it | survives re-index |
| `assert_edge` | a, b, kind | `STRUCT` edge ω 1.0 provenance `human`, plus the matching fact | survives re-index |
| `mark_hub` | entity_id | `boost` 0 (existing meaning: never a seed) and `Override(op=mark_hub)` | survives re-index |
| `add_synonym` | a, b, score | existing op; now also writes `Override` | survives re-index (today it does not) |
| `add_binding_rule` | lang, pattern, edge_kind, omega, source_id? | `BindingRule` row; re-index of affected sources applies it | rule, not edge |

`describe()` renders each: "Reject `foo → bar` (calls)", "Assert `dispatcher → handle_refund` (calls, 1.0)", "Mark `log` as a hub", "Rule (python): `register_handler(_, fn)` ⇒ dispatcher calls fn (0.9)".

**`analysis/unresolved.py` (new).** `leaderboard(ctx, source_id) -> [{name, count, files, pattern, example_line}]` grouped by name then by syntactic pattern; `suggest_rule(row) -> BindingRule draft` fills the tree-sitter query for the two patterns that cover most cases (registry call with a string key and a callable; decorator with a string argument).

**Golden-set replay.** `simulate.replay_set(ctx, set_id, overrides) -> {before, after, changed_questions}` runs `runner.run_question` with the LLM filter replayed from each stored result's trace (no LLM), so a proposed changeset can be scored against a whole set. `changesets.apply` refuses (409) when a linked `eval_set_id` regresses `recall@5` by more than `regression_tolerance` (setting, default 0.0) unless `force=True`.

---

## 8. Evals from git: `evals/question_maker.py`

New origin `'code'` next to `'generated'`: `generate_code_questions(ctx, source_id, *, max_questions=30, access=None)`. For the newest `commit` passages that touch ≥1 function: question = commit message (+ up to 5 context lines when the diff is available), `gold_passage_ids` = the `function` passages of the symbols the commit `modified_by` links to, `kind='code'`, `notes=sha`. No LLM. `runner` and `metrics` are unchanged (`recall@k`, `gold_rank`, `gold_in_top5` are exactly the LocBench-style numbers). Two more CI gates run in `tests/unit`: indexing a fixed fixture repo twice yields identical node/edge multisets; `reindex(changed_only=True)` after a synthetic commit equals a full re-index.

---

## 9. UI, page by page

Everything reuses the existing FastAPI + Jinja + HTMX + Cytoscape/3d-force-graph stack. No new framework.

| Page | Change |
|---|---|
| **Library** (`/`) | Repo rows show `commit`, languages, symbols/edges counts and an "unresolved: N" badge linking to the source page section. Add-repo form gains "history: N commits". |
| **Source** (`/sources/{id}`) | For repos: three tabs — *Passages* (today's list, now showing kind and line range, structural facts instead of OpenIE triples for code), *Symbols* (searchable table: kind, path, degree by relation, specificity, hub warning when in-degree > 3σ, community placeholder), *Unresolved* (the leaderboard; each row has "Assert edge…" and "Draft rule…" which open the changeset editor pre-filled). "Reindex changed files" button beside "Reindex". |
| **Ask** (`/ask`) | A second textarea "Paste code / stack trace / diff (optional)". The answer partial shows the `Paths` block first, then passages; each path edge shows ω and provenance on hover. |
| **Analyze** | New section 0 "Anchors" (table: name, origin, weight, matched by) above "What the search did". Candidates table gains provenance/ω columns. Section 3's picture draws `STRUCT` edges as dashed lines labelled by kind. New section "Paths" with the typed triples and a "Show blast radius" button (calls `/api/paths/impact`). Tweak panel gains: `structural_scale`, `omega_threshold` sliders; "Add anchor" (entity picker, weight); per structural fact "Reject edge" / per unresolved name "Assert edge"; "Replay against set…" dropdown that runs `replay_set` and shows before/after recall@5 and the questions whose top-5 changed. "Save as changeset" now emits the new ops. |
| **Changesets** | Lists the new ops in words; shows a "stale" badge on overrides whose targets no longer resolve; Apply shows the replay delta when the changeset is linked to a set. |
| **Graph** (`/graph`) | Kind filter gains "symbol"; STRUCT edges drawn dashed; node panel for a symbol shows path/lines, callers/callees with ω, tests, last commits. Light-up animation already works (PPR is the same). |
| **Settings** | `structural_scale`, `omega_threshold`, `history_commits`, `regression_tolerance` with one-line explanations; a "Code" status card: installed grammars, resolver availability (pyright/tsserver found or not), per-language edge-provenance mix (share of invokes that are fuzzy — the graph-health number). |

Two things stay deliberately absent, as before: a Cypher console for users, and per-question sliders for damping — the Tweak panel already scopes those to simulations.

---

## 10. MCP and CLI

`mcp_server.py` adds three tools, all scoped to the caller's slice like the five existing ones:

```
hippo_ask(question, code=None)               # existing tool, new optional argument
hippo_path(from_symbol, to_symbol)           -> paths with omega/provenance per edge
hippo_impact(symbol, depth=3)                -> blast radius (files, functions, tests), counts and the top-20
hippo_explain(symbol)                        -> definition passage, callers/callees, tests, last commits
```

No free-form graph query tool; the research case against it stands (CodexGraph cost and fragility; CodeAnchor's low tool-use pilot; LARGER's graph-tool baselines). `cli.py`: `hippo index <git-url> --history 500`, `hippo reindex <id> --changed`, `hippo unresolved <id>`, `hippo path <a> <b>`.

---

## 11. Store: what each backend adds

`store/memory.py` and `store/ladybug.py` gain, name-for-name, with `tests/fakes/fake_store.py` mirroring them and `test_store*.py` running on all three:

```
add_struct_edges(rows)                 rows: {a, b, kind, omega, provenance, line, in_branch, arg_binding}
load_struct_edges() -> rows            for GraphIndex.load (best omega per (a, b) pair, kinds)
link_passage_defines(pairs)            (passage_id, entity_id)
delete_passages_for_paths(source_id, paths)      the incremental unit (also removes their STATES/MENTIONS/DEFINES; remove_orphans after)
add_overrides(rows) / load_overrides() / mark_override_stale(id)
add_unresolved(rows) / unresolved_for_source(source_id) / clear_unresolved(source_id, paths)
add_binding_rule(row) / list_binding_rules(source_id | None) / delete_binding_rule(id)
search_symbols(q, access) -> rows      name / qualname / path substring, for the anchor and pickers (FTS on both backends)
```

`ensure_schema` adds the three node tables and the two rel tables; existing tables get the new columns with `ALTER TABLE … ADD` guarded by a `schema_version` meta key (LadybugDB has no "add column if not exists"). `load_entities`/`load_facts` return the new columns, defaulting to `'phrase'` / `'openie'` / 1.0, so a memory built before this change loads unchanged. The `_rows_with_good_vectors` guard already tolerates rows without embeddings; symbol rows always have one.

Access: a symbol is visible when a visible passage `DEFINES` or `MENTIONS` it — the existing rule, so `ACCESS_WHERE` needs one extra pattern alternative and `scoped()` needs `DEFINES` treated as a mention.

---

## 12. Tests and gates

`tests/unit/` gains, in the house style (fast, fakes, all three stores):

- `test_ingest_code_parse.py` — a fixture repo (`tests/fixtures/code_repo/`, ~15 files: a registry, a decorator-registered handler, a class hierarchy with an override, a raise/catch pair, a test file, three commits) with the exact expected symbols, facts, edges, ω and unresolved rows.
- `test_ingest_code_incremental.py` — full index == changed-only re-index after each fixture commit; overrides survive.
- `test_anchors.py` — every input shape in §6 against the fixture.
- `test_paths.py` — call path, blast radius, exception path, history on the fixture; no LLM.
- `test_changesets_code_ops.py` — validate/describe/apply/stale for the five new ops; `replay_set` refusal on regression.
- `test_web_source_code.py`, `test_mcp_code_tools.py`.
- `test_indexer.py` gains the assertion that no `openie.extract` call happens for `function`/`class_header`/`module_header`/`commit` passages (the `FakeOllama` counts calls).

`FakeOllama` needs no new rules: structural facts never go through it. CI stays `ruff` + the three store matrices.

---

## 13. Cut, and why

| Cut | Reason |
|---|---|
| Languages beyond Python and TS/JS | No resolver → only ω 0.5 edges → PPR noise; today's line-chunk path remains for them, which is honest. |
| Symbol-level `MODIFIES` from historical diffs | `git blame` gives the last commit per line deterministically with one command per file; full per-commit hunk∩symbol mapping needs checkouts of every parent. History depth is a setting. |
| Global statement-level graph | `ccg_json` per function covers GraphCoder's benefit at prompt time; the survey/RepoGraph/DyCoder cost findings stand. |
| Intent classifier / typed restart | `structural_scale` and `omega_threshold` in simulations give the same lever with no classifier to maintain; revisit only if the code eval set shows a gap. |
| Leiden communities | The Graph page's `path` prefix grouping and `blast_radius` grouping by directory cover the "subsystem" label for v1.0; a real community pass is one function on `GraphIndex` if the evals ask for it. |
| A Cypher console for users | As before. Neo4j Browser exists for admins on that backend. |

---

## 14. Contract additions (in `docs/CONTRACTS.md` style)

```
src/hippo/ingest/code/__init__.py   supported_languages(); extract_repo(root, docs, budget, *, rules, history_commits) -> CodeExtraction
                                    CodeExtraction(passages: list[Chunk+kind/path/lines/ccg], entities: list[SymbolRow], facts: list[FactRow],
                                                   struct_edges: list[StructRow], mentions, defines, unresolved: list[UnresolvedRow], commit_sha)
src/hippo/ingest/code/parse.py      parse_file(path, text, lang) -> FileSyntax(symbols, calls, imports, bases, raises, catches, literals, docstrings)
src/hippo/ingest/code/resolve.py    Resolver.for_repo(root, lang) ; resolve(ref: CallRef | ImportRef | BaseRef) -> Resolution(qualname|None, provenance, omega)
src/hippo/ingest/code/ccg.py        build(function_syntax) -> dict ; slice(ccg: dict, line: int, h=3, l=20) -> str
src/hippo/ingest/code/history.py    commits(root, n) -> list[CommitRow] ; blame(root, path) -> {line: sha}
src/hippo/ingest/code/rules.py      apply_rules(root, rules, files) -> list[StructRow]
src/hippo/hipporag/anchors.py       anchors_from(index, question, code) -> list[Anchor(entity_id, name, weight, origin)]
src/hippo/hipporag/retriever.py     Retriever.retrieve(..., seed_nodes=None) ; Trace.anchors
src/hippo/hipporag/graph_index.py   Edge.structural, Edge.structural_kinds ; GraphIndex.struct_neighbors(vertex, kinds, omega_min)
src/hippo/analysis/paths.py         call_path, blast_radius, exception_path, history, paths_for_trace ; PathBlock.render()
src/hippo/analysis/unresolved.py    leaderboard(ctx, source_id) ; suggest_rule(row)
src/hippo/analysis/simulate.py      Overrides.seed_nodes ; replay_set(ctx, set_id, overrides)
src/hippo/analysis/changesets.py    VALID_OPS += reject_edge, assert_edge, mark_hub, add_binding_rule ; apply(..., force=False)
src/hippo/evals/question_maker.py   generate_code_questions(ctx, source_id, *, max_questions=30, access=None) -> set_id  (origin 'code')
src/hippo/ask.py                    search(ctx, question, settings=None, access=None, code=None) ; answer_from_trace(...) adds the Paths passage
src/hippo/store/*                   the methods in §11 ; DEFAULT_SETTINGS += structural_scale 1.0, omega_threshold 0.5,
                                    history_commits 500, regression_tolerance 0.0
src/hippo/mcp_server.py             hippo_ask(question, code=None) ; hippo_path ; hippo_impact ; hippo_explain
src/hippo/web/routes/analyze.py     POST /api/paths/impact {symbol_id, depth} ; POST /api/simulate/replay-set {set_id, overrides}
src/hippo/web/routes/sources.py     GET /sources/{id}?tab=symbols|unresolved ; POST /api/sources/{id}/reindex {changed_only: true}
```

`docs/FIDELITY.md` gains one section, "Code sources", stating that nothing in the reference algorithm changed: structural facts are extra `Fact` rows, anchors are extra reset mass added after the reference's seed computation, and `structural` is an extra term in the edge-weight `max`; with `structural_scale = 0` and no code sources the system is the reference.

---

## 15. Worked example: hippo indexes itself

`hippo index https://github.com/MattMakes/hippo.git --history 500`. The extractor produces roughly 40 modules, ~600 functions, `calls` facts such as `["Retriever.retrieve", "calls", "match_triples"]` (ω 1.0, same file), `["index_source", "calls", "find_synonyms"]` (ω 1.0), `["Retriever.llm_fact_filter", "calls", "Ollama.chat_json"]` (ω 0.9, resolver), `["Retriever.llm_fact_filter", "catches", "OllamaError"]`, `["index_source", "tested_by", "test_indexer.py"]` (0.85), and `modified_by` facts to the commits that last touched each line. The README's "How it works" section is a `doc` passage and goes through OpenIE as today, yielding phrases like "recognition memory" and "node specificity", which the synonym pass links to `Retriever.llm_fact_filter` (docstring: "the reference's DSPy recognition memory filter") and to the `node_specificity` setting name.

Ask, with the code box holding:
```
File "src/hippo/hipporag/retriever.py", line 170, in retrieve
    kept_triples, raw = filter_fn(question, candidate_triples) if sent else ([], "")
```
and the question *"Why did this fall back to DPR?"*

- Anchors: `Retriever.retrieve` (1.0, stack trace), `llm_fact_filter` (0.6, split-token from `filter_fn`), `candidate_triples` (0.6).
- Fact candidates include `["Retriever.retrieve", "calls", "Retriever.llm_fact_filter"]`, `["Retriever.llm_fact_filter", "catches", "OllamaError"]`, and the OpenIE fact `["fact filter", "keeps no facts on", "error"]` from the README; the filter keeps all three.
- PPR lands on the `function` passage of `llm_fact_filter`, the `retrieve` passage split around line 170, the README section, `test_retriever.py::test_filter_error_falls_back`, and commit `…` "a filter error keeps no facts, like the reference".
- Paths: `retrieve -[calls 1.0 in_branch args:{question, candidate_triples}]-> llm_fact_filter -[catches 1.0]-> OllamaError`.
- The answer block leads with that path, then the `ccg.slice` around line 170 showing `if not kept_fact_indices: trace.used_dpr_fallback = True`, then the filter function, the test, the commit message and the README sentence — every item with ω and a file path.

On the Analyze page the anchor table shows where each seed came from; the Tweak panel can drop the README fact, raise `omega_threshold` to 0.95, and replay against the `code` question set to see recall@5 unchanged before saving that as a changeset.
