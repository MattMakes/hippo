# R5 — Reconciliation matrix: Plan A vs Design B (worker: codex-terra-1)

Read `00-shared-context.md` first. Output file: `docs/plans/hippo-for-code/research/R5-reconciliation.md`.

Document-only task. Do not read source code. Read the two inputs closely and produce the matrix the
synthesizer will decide from. Neutral tone: you report positions, you do not pick winners.

## Part 1 — Conflict matrix

One row per conflict, columns: `# | Topic | A says (§ref, ≤2-line quote) | B says (§ref, ≤2-line quote) |
What is at stake | Which research file informs the tiebreaker (R1 store/graph, R2 ingest/evals, R3 retrieval,
R4 LadybugDB spike, R6 web/MCP/CLI)`.

Cover at least these (add any you find):
1. Symbol as `Entity` row with `kind` (B D1) vs separate `Symbol` / `DataObject` / `Commit` node tables (A).
2. Structure written as `Fact` rows + `STRUCT` rel (B D2/D3) vs `CODE_EDGE` only, no facts (A).
3. Rel naming and shape: `STRUCT {kind, omega, provenance, line, in_branch, arg_binding}` vs
   `CODE_EDGE {kind, omega, provenance, extra JSON}`; one edge per (a,b,kind) rule.
4. Id scheme: A `make_id("symbol-", f"{source_id}:{path}:{qualname}")` vs B `symbol-` + md5(`repo_source_id:qualname`).
5. Node specificity for code nodes: A `1/(incoming INVOKES/READS/WRITES + 1)` vs B passage count via `MENTIONS`/`DEFINES`.
6. Symbol name lookup: B `store.search_symbols` with FTS vs A in-memory `name_index` on `GraphIndex`, no store search.
7. Symbol embedding: A name-text only (split tokens + spelling), dense seeding via defining passage; B
   `signature + first docstring sentence`, synonym search on `name_tokens`.
8. Git history: A `Commit` nodes + `MODIFIES` from diff hunks ∩ symbol ranges + `PRECEDES`, default 200
   first-parent commits; B `commit` passages + `modified_by` from `git blame`, `HISTORY_COMMITS` 500.
9. Data-access edges READS/WRITES via sqlglot / Mongo / Cypher literals: A keeps ("asked for explicitly"); B silent.
10. LLM "select" pass (DyRetriever keep/drop/expand-once), on by default: A yes; B absent.
11. Leiden communities: A yes (+10% rerank prior); B cut with reason (§13).
12. CCG per-function slices: A deferred; B in (`ccg.py`, `Passage.ccg_json`, `ccg.slice` in the answer).
13. Incremental re-index by changed files: A deferred ("sources re-indexed wholesale"); B in (`reindex(changed_only=True)`).
14. Overrides persistence: B new `Override` table re-applied at link time + `stale` flag; A: how does A persist
    tuned edges across re-index, if at all? Quote.
15. `Unresolved` leaderboard + `BindingRule` (tree-sitter query rules): B in; A?
16. Golden-set replay `replay_set` + `regression_tolerance` 409 gate on `changesets.apply`: B in; A?
17. Evals from commits: both — compare `generate_code_questions` (B §8) vs A §4.5 in detail.
18. Anchors: compare A's seeding paragraph (identifiers, stack frames 0.8 decay, fenced code, diff hunks,
    dense hits on code passages; bypass fact filter AND `linking_top_k`) vs B §6 (same shapes; NOT exempt
    from `link_top_k`).
19. Answer block: A `Title: Code graph` pseudo-passage vs B `Paths` passage + `ccg.slice` substitution for long functions.
20. Package layout: A `src/hippo/codegraph/` (pure, no `ingest` import) + `hipporag/anchors.py` + `hipporag/paths.py`
    + `web/routes/code.py`; B `src/hippo/ingest/code/` + `hipporag/anchors.py` + `analysis/paths.py` +
    `analysis/unresolved.py` + additions to `web/routes/analyze.py` and `sources.py`.
21. MCP tools: A's four tools (`explain_path`, `blast_radius`, `exception_path`, `history`) vs B's
    (`hippo_path`, `hippo_impact`, `hippo_explain`, `hippo_ask(code=)`).
22. Settings: A `code_seed_weight` (and others in §3.1) vs B `structural_scale`, `omega_threshold`,
    `history_commits`, `regression_tolerance`. List every setting each proposes with defaults.
23. Resolvers: A in-house only, LSP deferred; B in-house + optional pyright/tsserver when installed.
24. Languages and ω table: line up A's ω table against B §4.3 and flag every numeric difference.
25. Test fixture: A `tests/fixtures/code_sample/` verbatim files (§2.7); B `tests/fixtures/code_repo/` with
    "three commits". Note that a nested `.git` cannot be checked in; report what each says about that.

## Part 2 — Lists

- **A's explicit user decisions**, verbatim, from A's "Context" section (the bulleted "User decisions" block
  and the "Deferred with reasons" list).
- **A's "Verified on this machine" facts**, verbatim.
- **B's cuts** (§13) verbatim.
- **Only in A**: features/sections with no B counterpart.
- **Only in B**: features/sections with no A counterpart.
- **Shared and agreed**: what both say the same way (so the synthesizer can take those as settled).

## Part 3 — Questions the synthesizer must answer

A numbered list of the decisions that cannot be settled from the documents alone, each phrased as a
yes/no or A/B question, with the research file that should settle it.

Keep it under ~350 lines. Section references must be exact (`A §2.2`, `B §7`).
