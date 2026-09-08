# WP2b — Git history: `Commit` nodes, `MODIFIES`, `PRECEDES`, commit passages

Read `impl/00-impl-context.md` first. Worktree `.worktrees/wp2b`, branch `wp/wp2b`.
Neo4j test container: name `hippo-neo4j-wp2b`, port **17694**.

`code-graph` now contains WP1 (store: `add_commits`, `add_modifies`, `add_precedes`, `load_*`, the three
history settings in `DEFAULT_SETTINGS`/`SETTING_RULES`) and WP2 (`codegraph/` extractors, the fixture
tree). WP2i (chunker/indexer/pipeline integration, the `code_index` fixture, the golden test) and WP3
(retrieval) are being built in parallel and will merge while you work. You do not touch `retriever.py`,
`anchors.py`, `paths.py`, `ask.py`, `answerer.py`, `prompts.py`, `store/base.py` (the settings exist).

## Two phases — read this first

**Phase 1 (now):** the backend-free half — `codegraph/git_history.py`, `test_git_history.py`,
`make_code_checkout` in `tests/conftest.py`, `repos.clone_repo(..., depth=1)` and its test. All of it
runs against a real git repo in `tmp_path` and needs no store, no pipeline. Commit green on all three
stores (nothing you touch should change any store test), write the ledger note, then
`horch tell orchestrator "[<role>] PHASE 1 DONE: wp/wp2b ..."` and **keep your pane open**.

**Phase 2 (when the orchestrator tells you WP2i has merged):** `git merge code-graph` into `wp/wp2b`
(the one time you may merge; resolve `tests/conftest.py` if both sides added to it), then the pipeline
and indexer integration, the `git_index` fixture, the `expected.json` `commits`/`modifies` sections and
the pipeline history tests on all three stores. Then the normal DONE.

Your spec is PLAN.md **WP2b (lines 354-366)**, S2.9 (MODIFIES intersects hunks with symbol ranges AT THAT
COMMIT), S2.11 (budgets: `code_history_depth`, `code_git_timeout_s`, `code_history_total_s`), the
**Test fixture plan's git parts (lines 475-482)**: `make_code_checkout(tmp_path)` with the pinned
`GIT_AUTHOR_*`/`GIT_COMMITTER_*` identity and dates, the `git_index` fixture, and S2.17's rule that
`expected.json` keys commits by `(ordinal, subject)` and MODIFIES rows by `(ordinal, path, qualname)`,
never by SHA. Decision Log D8, D17 (the eval that will consume these edges as gold — which is why S2.9
is not optional). Evidence: `research/R4-spike-results.md` T11 (git command timings and the `-U0` hunk
format), `research/R2-ingest-evals-tests.md` R2-7 (`clone_repo` hardcodes `--depth 1`), R2 gotcha 8
(`make_checkout` in `tests/unit/test_ingest_repos.py` is the only real-git pattern in the suite).

## What the previous workers built (read their code, not just this summary)

**WP1 (store), merged as 240d348.** `src/hippo/store/code.py` has the row shapers `commit_write_row`
and `modifies_write_rows`; every store has `add_commits(rows)` (`{id, source_id, sha, author, date,
message, ordinal}` + `embedding` when the passage path supplies one — check), `add_modifies(rows)`
(`{commit_id, symbol_id, omega, hunk}`, `hunk` JSON text), `add_precedes(pairs)`, `get_commits`,
`load_commits`/`load_modifies`/`load_precedes`; `delete_code_nodes_for_source` sweeps commits with the
source. `GraphIndex` loads commits as vertices (order entities → symbols → data → commits → passages),
MODIFIES/PRECEDES as `DirectedEdge`s, PRECEDES excluded from igraph. Ids: `commit_id(source_id, sha)`
in `codegraph/model.py`. Full handoff in the `backend-developer-1` ledger entry.

**WP2 (extractors), merged as 9ba5e39.** `codegraph/python.py` / `typescript.py` expose the walkers
(`walk(...) -> FileFacts`) and `codegraph/treesitter.py` the parser factory — reuse them to parse a
file's content at a commit; `Symbol` has `path`, `qualname`, `display`, `line_start`, `line_end`;
`readers.lang_of(name)` says which language a path is. The three budget constants are UPPER_CASE.
`tests/conftest.py` already has `CODE_SAMPLE_PATH` and `code_sample_docs()`. The fixture tree is
`tests/fixtures/code_sample/` (11 files, exact line numbers per PLAN 420-469); `expected.json` there
has empty `commits`/`modifies` lists for you to fill through `scripts/update_expected.py` (extend it;
`--check` must pass). Full handoff in the `opus-1` ledger entry.

<!-- ORCHESTRATOR FILLS FROM THE WP2i LEDGER SUMMARY AT PHASE 2 -->

## Scope

1. **`codegraph/git_history.py`** — `read_history(checkout, symbols, *, depth, timeout_s, total_s) ->
   History(commits, modifies, precedes, skipped)`: `git log --first-parent -n {depth}` (newest first,
   `ordinal` 0 = HEAD), `git show -U0 <sha>` per commit for hunks, and per touched file in a supported
   language `git show <sha>:<path>` → tree-sitter parse (reuse `codegraph`'s walkers; one `Parser` per call)
   → intersect the hunk's new-side ranges with THAT parse's symbol ranges → map to the HEAD symbol by
   `(path, qualname)`; absent at HEAD → no edge. `PRECEDES` chains consecutive first-parent commits.
   `-M` off. Per-commit timeout skips the commit; the whole-pass budget stops the loop and keeps what was
   read; both counted into `skipped` → `Source.meta.history_skipped`. The cooperative `should_stop` runs
   between commits. Binary and unsupported files are ignored. Commit rows are exactly WP1's `add_commits`
   shape; `hunk` is the JSON `{file, old_range, new_range, churn}`.
2. **`ingest/repos.py`** — `clone_repo(url, dest, timeout=300, depth=1)`; `pipeline.read_source`'s
   `kind == "repo"` branch threads `code_history_depth` from settings (0 → `--depth 1` and no history).
3. **`ingest/pipeline.py` / `hipporag/indexer.py`** — for repo sources, stage `"reading history"` with the
   single `on_progress` pair; commit passages (`text = message + "\n\nTouched: " + qualnames`, title
   `commit {sha[:10]}: {subject}`, `defines=[commit_id]`, `extract_text=message`) go through the normal
   chunk/index path so they get embeddings and `MENTIONS` like any passage; then `add_commits`,
   `add_modifies`, `add_precedes`, `link_definitions` for the commit passage, and REFERS_TO from commit
   passages via WP2i's `"linking mentions"` stage. `meta["code"]` gains the commit counts and
   `history_skipped`.
4. **`tests/conftest.py`** — `make_code_checkout(tmp_path)` (copy the fixture tree, `git init`, pinned
   identity and dates, three commits exactly as line 478 lists them) and the `git_index` fixture (a repo
   source over the local path; note `repos.is_git_url` rejects plain paths while `git clone` accepts them,
   so create the source directly and call `pipeline.run_indexing`).
5. **`expected.json`** — fill the `commits` and `modifies` sections with the ordinal-keyed rows; extend
   `scripts/update_expected.py`; the golden test in `test_indexer.py` now compares them too (mapping run-time
   SHAs through the ordinal).
6. **Tests** — `test_git_history.py` (backend-free, real git in `tmp_path`): three commits newest-first,
   the PRECEDES chain, MODIFIES from commit 2 to `place` only, hunk JSON shape, `depth=1` → one commit, a
   binary file ignored, determinism, and the three S2.9 cases (HEAD range of `place` differs from its
   range at commit 2 and the edge is still `place`; a symbol deleted after the commit that touched it
   yields no edge; a forced `git show` timeout skips its commit and bumps `skipped`).
   `test_ingest_pipeline.py`: the repo-history case on all three stores via `git_index` — commit passages,
   `stats()["commits"] == 3`, REFERS_TO from the README passage at 0.85 and 0.60, `code_history_depth=0` →
   no commits.

## Done when (PLAN.md line 366)

A repo source indexes with history on all three stores, `git_index` is available, lint green. Commit,
ledger summary (files, the `History` shape, the `git_index` fixture's yield, the `meta["code"]` keys you
added, any WP3-relevant fact about `Commit` rows), `horch tell orchestrator "[<role>] DONE: wp/wp2b ..."`,
close pane.
