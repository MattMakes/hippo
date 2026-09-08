# WP2b — Git history: `Commit` nodes, `MODIFIES`, `PRECEDES`, commit passages

Read `impl/00-impl-context.md` first. Worktree `.worktrees/wp2b`, branch `wp/wp2b`.
Neo4j test container: name `hippo-neo4j-wp2b`, port **17694**.

`code-graph` now contains WP1 (store: `add_commits`, `add_modifies`, `add_precedes`, `load_*`, the three
history settings in `DEFAULT_SETTINGS`/`SETTING_RULES`), WP2 (`codegraph/` extractors, fixture tree) and
WP2i (chunker/indexer/pipeline integration, `code_index` fixture, golden `expected.json` test).
Another worker is building WP3 (retrieval) in parallel; you share `store/base.py` only if you must
(the settings already exist — you should not need to touch it) and you do not touch `retriever.py`,
`anchors.py`, `paths.py`, `ask.py`, `answerer.py`, `prompts.py`.

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

<!-- ORCHESTRATOR FILLS FROM THE WP1 / WP2 / WP2i LEDGER SUMMARIES -->

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
