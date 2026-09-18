# AR1F — Apply the architecture review's fixes 1-7 and 9

Read `impl/00-impl-context.md` first. Worktree `.worktrees/ar1f`, branch `wp/ar1f`, from the CURRENT tip
of `code-graph`. Neo4j test container: name `hippo-neo4j-ar1f`, port **17689**.

Your spec is `docs/plans/hippo-for-code/research/AR1-architecture-review.md`, section "Fixes — should
change before release", items **1, 2, 3, 4, 5, 6, 7 and 9** (item 8 is docs and belongs to WP4d). Each
finding cites a `file:line` and a recommendation; read the finding, read the code, apply the smallest
correct change, and add or extend the test the finding says is missing. Do not touch the nits. Do not
refactor around the fix. The files you will touch — `hipporag/retriever.py`, `hipporag/graph_index.py`,
`hipporag/indexer.py`, `hipporag/anchors.py`, `hipporag/paths.py`, `ingest/chunker.py` and their tests
— are not being edited by any live WP4 worker; WP2b (git history) is finishing in `indexer.py` /
`pipeline.py` and will merge first or just after you; keep your `indexer.py` edits to the cited lines.

## Decisions already made for you

- **Fix 1 (select `drop` is inert):** do BOTH halves. The judged window becomes
  `max(qa_top_k * 2, qa_top_k + 5)` ranked passages, and the reassembled order is
  `kept + rest + demoted + expanded` — a passage the LLM judged irrelevant sinks below passages it never
  saw, and a kept passage from the wider window moves into the `qa_top_k` slice when one above it is
  dropped. `replay_select` replays stored decisions unchanged. Extend `test_retriever.py`'s select test
  to assert that the set of passage ids in the qa slice (`[p for p in trace.passages if not
  p.via_expand][:qa_top_k]`) DIFFERS from the no-select baseline when the fake `select_fn` drops one, and
  that a stored pre-fix trace still loads. Make sure `test_ask.py`'s pinned block and the mixed-memory
  tests stay green — the select pass is gated on `used_code_seeds`, so prose is untouched.
- **Fix 2 (per-scale memo):** key by `round(scale, 2)` and keep at most 3 entries (evict oldest).
- **Fix 3 (Leiden RNG):** a module-level `threading.Lock` around seed / run / restore.
- **Fix 4, 7:** hoist the set / build the `(path, line) -> ids` dict once, as recommended.
- **Fix 5:** `path_index` on `GraphIndex` beside `name_index`, shared by `scoped()`, hits filtered
  through `idx_of`; add a `test_graph_index.py` case and keep `test_anchors.py`'s access test green.
- **Fix 6:** cap pairing to the top 5 seeds by weight, memoise `display_at` per index, give `_bfs` a
  visit budget (a constant, e.g. 5,000 vertices, documented); `test_paths.py` gets a case that the cap
  and the budget hold.
- **Fix 9:** `np.argpartition` then sort the partition; same results on the fixture (a test that
  `find_synonyms` output is unchanged before/after is the proof — compare against the golden run).

## Done when

Three stores + lint green, every fix has its test, no pinned assertion weakened, `expected.json`
`--check` still clean. Commit per fix, ledger summary listing which AR1 items you applied and how,
`horch tell orchestrator "[<role>] DONE: wp/ar1f ..."`, close pane.
