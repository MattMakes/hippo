# R5 — Reconciliation matrix: Plan A vs Design B

## Conflict matrix

| # | Topic | A says (§ref, ≤2-line quote) | B says (§ref, ≤2-line quote) | What is at stake | Tiebreaker |
|---|---|---|---|---|---|
| 1 | Symbol nodes | A Context: “`Symbol` … `DataObject` … `Commit`” are added node types. | B §3 D1: “A symbol is an `Entity`.” | Schema, index vertex model, compatibility. | R1 |
| 2 | Structure storage | A Context: “`CODE_EDGE {kind, omega, provenance, extra}`”. | B §3 D2: “Structure is written as facts.” | Whether code relations enter fact filtering/embedding. | R1, R3 |
| 3 | Relation shape | A Context: one CODE_EDGE per `(a, b, kind)` with JSON `extra`. | B §4.2: `STRUCT` has typed columns including `line`, `in_branch`, `arg_binding`. | Schema and duplicate/relation semantics. | R1, R4 |
| 4 | Symbol IDs | A Context: `make_id("symbol-", f"{source_id}:{path}:{qualname}")`. | B §3 D1: “`symbol-` + md5(`repo_source_id:qualname`)”. | ID stability and same-qualname-in-two-files behavior. | R2 |
| 5 | Specificity | A Context: `1 / (incoming INVOKES/READS/WRITES + 1)`. | B §4.2: symbol specificity is passages that “touch it”. | PPR seed damping and hub behavior. | R3 |
| 6 | Name lookup | A Context: “no `search_symbols`”; scoped `name_index`. | B §11: `search_symbols(q, access)` using FTS. | Store API, picker and anchor lookup. | R1, R3 |
| 7 | Symbol embedding | A Context: “one vector … *name text*”; passage embedding seeds dense retrieval. | B §4.1: embedding is “`signature + first docstring sentence`”. | Synonym quality versus vector/storage design. | R2, R3 |
| 8 | Git history | A Context: Commit nodes; hunk∩range `MODIFIES`; default 200 first-parent. | B §5: commit passages + `git blame`; `HISTORY_COMMITS` 500. | History fidelity, cost, and graph shape. | R2 |
| 9 | Data access | A Context: READS/WRITES from SQL, MongoDB, Cypher literals are kept. | B §§3–5 does not specify SQL/Mongo/Cypher data objects. | Scope of source-only graph and data nodes. | R2 |
| 10 | LLM select | A Context: “LLM helpfulness pass on by default”. | B is silent on a select/keep/drop/expand pass. | Latency, determinism, trace/replay design. | R3 |
| 11 | Leiden | A Context: “Leiden … +10% rerank prior.” | B §13 cuts “Leiden communities”. | Community storage and ranking behavior. | R3 |
| 12 | CCG slices | A Context defers “CCG slice artifacts”. | B §5 adds `ccg.py`; §6 uses `ccg.slice()`. | Extraction/prompt complexity. | R2, R3 |
| 13 | Incremental reindex | A Context: sources “re-indexed wholesale”. | B §5 adds `reindex(changed_only=True)`. | Deletion/relinking contracts and test scope. | R2, R1 |
| 14 | Override persistence | A has TUNED/boost persistence but no reapply/stale proposal; it says boosts survive changesets. | B §3 D4: `Override` is re-applied; unresolved targets are “stale”. | Tuned-edge survival after source rebuild. | R1, R2 |
| 15 | Unresolved/rules | A has no Unresolved leaderboard or BindingRule proposal. | B §3 D5: unresolved calls become `Unresolved`; rules are written against it. | Explicit extraction-gap feedback loop. | R2 |
| 16 | Replay gate | A has eval baselines but no `replay_set`/409 gate. | B §7: `replay_set`; reject apply on regression beyond tolerance. | Changeset safety and eval plumbing. | R2, R3 |
| 17 | Commit evals | A §4.5 has `code_questions` and `commit_questions`, with expected answers and extra metrics. | B §8 has `generate_code_questions`, newest commit passages, unchanged metrics. | Eval population, gold labels, and metrics. | R2 |
| 18 | Anchor cap | A §3.4: symbol seeds “bypass … `linking_top_k`”. | B §6: anchors “are not exempt from `link_top_k`”. | Whether exact stack frames can all seed PPR. | R3 |
| 19 | Answer block | A §3.5 prepends `Title: Code graph` pseudo-passage. | B §6 prepends synthetic `Paths`; long functions use `ccg.slice()`. | Prompt evidence format and long-function handling. | R3 |
| 20 | Package layout | A: `codegraph/`, `hipporag/paths.py`, `web/routes/code.py`. | B: `ingest/code/`, `analysis/paths.py`, edits analyze/sources. | Module boundaries and dependency direction. | R2, R6 |
| 21 | MCP | A §4.2: `hippo_explain_path`, blast, exception, history. | B §10: `hippo_ask(code=)`, `hippo_path`, impact, explain. | Public tool names and operation set. | R6 |
| 22 | Settings | A §3.1: seven `code_*` settings, defaults listed below. | B §§6–7: `structural_scale`, `omega_threshold`, `history_commits`, `regression_tolerance`. | Configuration/API surface. | R3, R6 |
| 23 | Resolvers | A Context defers “pyright/tsserver LSP resolvers”. | B §5: optional pyright/tsserver “when installed”. | Dependency policy and resolution provenance. | R2 |
| 24 | ω values | A Context table has import-through-index .90, wildcard .60, READS/WRITES .85/.60. | B §4.3 adds import-scoped .80 and dynamic/reflection .30; uses git-blame modified_by. | Confidence policy and emitted provenance taxonomy. | R2 |
| 25 | Fixture | A §2.7: `tests/fixtures/code_sample/`, verbatim files; git is initialized in a copied fixture. | B §12: `tests/fixtures/code_repo/`, “three commits”. | Fixture path/content; nested `.git` cannot be checked in, so history setup must be created during tests. | R2 |

## Required lists

### A's explicit user decisions (verbatim)

- Corpus: **source code repositories and nothing else**: source files, tests, in-repo docs (README, docstrings, comments) and **git history**. PRDs, tickets, external DDL and monitors are out.
- Code graph: tree-sitter Python + TypeScript/JavaScript symbols with CONTAINS / IMPORTS / INVOKES / INHERITS / OVERRIDES / RAISES / CATCHES / TESTED_BY, each with a provenance ω. INVOKES carries `call_line`, `in_branch`, `arg_binding`.
- **Data-access edges are kept** (asked for explicitly): READS/WRITES from SQL, MongoDB and Cypher literals *inside the repo's own files* and from in-repo `.sql` files. That is still "source code only"; only external DDL ingestion is out.
- **Git history in phase 1, bounded**: `Commit` nodes, `MODIFIES` (diff hunks ∩ symbol ranges), `PRECEDES`, commit-message passages, a configurable history depth (default 200 first-parent commits), and a commit-based localization eval.
- **LLM helpfulness pass on by default** (DyRetriever "select": keep / drop / expand-once), behind a setting so evals can compare.
- Communities: Leiden on the file-level projection, stored on symbols, shown as the subsystem label, +10% rerank prior.
- OpenIE: prose only (design doc §4.4 step 5; the survey and LARGER run no LLM extraction over code): a symbol's docstring/doc-comment when ≥ 80 chars, README/markdown, commit messages. Never function bodies or DDL.
- Passage granularity: one passage per symbol (module header, class header, each function/method), titled `path :: qualname (lines a-b)`; long bodies split at top-level statements of the body.

**A deferred with reasons (verbatim):** CCG slice artifacts (the statement-split passages bound prompt cost for now); pyright/tsserver LSP resolvers (heavy deps; the in-house resolver gives the 0.90 tier, LSP is a later drop-in adapter); intent classification with typed restart; `Field` nodes and READS/WRITES_FIELD; `Repo`/`Directory` nodes; commit-aware incremental re-indexing (sources are still re-indexed wholesale, so "incremental" means the extractor is per-file and cached, not that the graph is patched).

### A's “Verified on this machine” facts (verbatim)

`tree-sitter` 0.26, `tree-sitter-python` 0.25 (ABI 15), `tree-sitter-typescript` 0.23.2 (exposes `language_typescript()` and `language_tsx()`; the tsx grammar parses plain JS/JSX cleanly), `sqlglot` 30 (`parse_one(..., error_level=IGNORE)`; `find_all(exp.Table)` gives read/written tables). tree-sitter parses all of hippo's Python in 55 ms. On LadybugDB 0.15.3: `ALTER TABLE <rel> ADD IF NOT EXISTS FROM A TO B` works and is idempotent (in memory; must be re-verified on a closed-and-reopened file, first test in WP1); `CREATE` of a rel bound by a multi-label node pattern is refused (writes go one statement per concrete label pair); `NOT EXISTS {}` under `UNWIND` does not see rows created in the same statement (dedupe in Python); `SET a = CASE.., b = CASE..` is sequential (compute a `better` flag in a `WITH` first); a `None` in a bytes column under `UNWIND` breaks `decode()` (always `text(x or "")`).

### B's cuts (§13, verbatim)

| Cut | Reason |
|---|---|
| Languages beyond Python and TS/JS | No resolver → only ω 0.5 edges → PPR noise; today's line-chunk path remains for them, which is honest. |
| Symbol-level `MODIFIES` from historical diffs | `git blame` gives the last commit per line deterministically with one command per file; full per-commit hunk∩symbol mapping needs checkouts of every parent. History depth is a setting. |
| Global statement-level graph | `ccg_json` per function covers GraphCoder's benefit at prompt time; the survey/RepoGraph/DyCoder cost findings stand. |
| Intent classifier / typed restart | `structural_scale` and `omega_threshold` in simulations give the same lever with no classifier to maintain; revisit only if the code eval set shows a gap. |
| Leiden communities | The Graph page's `path` prefix grouping and `blast_radius` grouping by directory cover the "subsystem" label for v1.0; a real community pass is one function on `GraphIndex` if the evals ask for it. |
| A Cypher console for users | As before. Neo4j Browser exists for admins on that backend. |

### Settings proposed

- A §3.1: `code_seed_weight=1.0`, `code_theta=0.5`, `code_dense_seeds=5`, `code_triples_chars=1500`, `code_community_boost=0.1`, `code_select=True`, `code_expand_max=10`; A Context also gives history depth default 200.
- B §§5–7, 14: `structural_scale=1.0`, `omega_threshold=0.5`, `history_commits=500`, `regression_tolerance=0.0`.

### Only in A

- Separate Symbol/DataObject/Commit tables; source-scoped in-memory name index; data-access objects/READS/WRITES.
- Hunk-intersection history, `PRECEDES`, first-parent default 200, community rerank, select/expand pass.
- Four fixed specialized MCP graph tools, Code graph prompt block, code-specific eval metrics and expected-answer generation.

### Only in B

- Entity/Fact reuse, `Override`, `Unresolved`, BindingRule, replay/regression gate, changed-only reindex.
- CCG slices, optional LSP resolution, `search_symbols` FTS, source/unresolved UI, and B's alternate MCP names.

### Shared and agreed

- Python and TypeScript/JavaScript tree-sitter extraction; deterministic structure; no OpenIE over function bodies.
- Symbol-level passages, top-level statement splitting for long bodies, anchors from identifiers/stack traces/snippets/diffs, provenance-weighted directed paths, and no free-form user graph query.
- Repo git history, commit passages, code-localization evals, tests, path/blast/exception/history capabilities, scoped access, PPR retained as the retrieval spine, and no external PRD/ticket/DDL ingestion.

## Questions the synthesizer must answer

1. A/B: separate code node tables and CODE_EDGE, or Entity/Fact/STRUCT reuse? (R1, R3)
2. A/B: hunk∩symbol commit history at 200 first-parent commits, or git-blame history at 500? (R2)
3. Yes/no: include source-literal SQL/Mongo/Cypher READS/WRITES and DataObject nodes in phase 1? (R2)
4. Yes/no: enable the LLM select/expand pass by default? (R3)
5. A/B: Leiden + rerank prior, or directory grouping only? (R3)
6. A/B: defer CCG and changed-only reindex, or implement both in phase 1? (R2, R1)
7. Yes/no: persist/reapply overrides with staleness and block regressing changesets? (R1, R2, R3)
8. Yes/no: expose unresolved-call leaderboard and tree-sitter BindingRules? (R2)
9. A/B: exact anchors bypass `linking_top_k`, or retain the normal `link_top_k` cap? (R3)
10. A/B: Code graph block, or Paths block plus CCG substitution? (R3)
11. A/B: in-memory scoped name lookup, or store-backed FTS? (R1, R3)
12. A/B: in-house resolver only, or optional installed LSP servers? (R2)
13. A/B: A's four specialized MCP tools/names, or B's path/impact/explain plus `hippo_ask(code=)` surface? (R6)
14. A/B: fixture `code_sample` with test-created git history, or rename/reframe it as B's `code_repo`? (R2)
