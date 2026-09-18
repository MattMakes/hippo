# E1F-a — Git history must degrade, never crash the index job

Read `impl/00-impl-context.md` first (rules, worktree + venv, three-store matrix, exit-code capture).
Worktree `.worktrees/e1fa`, branch `wp/e1fa`, from the CURRENT tip of `code-graph`. Neo4j test
container: name `hippo-neo4j-e1fa`, port **17706**. Small task: two files plus tests, under an hour.

Spec: `docs/plans/hippo-for-code/research/E1-territory-updater.md` **Defect 1** (read it in full — it
has the exact reproduction, the code path and the two suggested fixes). Summary: `_hunks()` in
`src/hippo/codegraph/git_history.py` calls `_git()` with `text=True`, so a diff containing invalid
UTF-8 raises `UnicodeDecodeError` inside `subprocess.run`; nothing catches it (`read_history`'s loop
catches only `TimeoutExpired`, `pipeline._read_history` only `HistoryError`), so `run_indexing`'s
generic handler marks the WHOLE source failed and discards the passages and code graph already
written — contradicting `_read_history`'s own docstring. A ~1 GB diff also spends seconds in Python
parsing that `code_git_timeout_s` does not bound.

## Do this

1. `_hunks()` reads the diff as bytes and decodes with `errors="replace"`, the pattern `_symbols_at()`
   already uses in the same file.
2. A per-commit size guard: if the diff output exceeds `MAX_DIFF_BYTES` (a module constant, 20 MiB,
   documented as "a commit that vendors a binary tree is not history worth parsing"), the commit is
   skipped and counted in `skipped` like a timeout, with a debug log line naming the sha and size.
   Prefer reading stdout with a cap (`git diff --stat` first, or read the pipe up to the cap and kill)
   over reading the whole gigabyte and then discarding it — measure on the fixture that it costs no
   visible time for normal commits.
3. Defence in depth: `read_history`'s per-commit loop catches `(subprocess.TimeoutExpired,
   UnicodeDecodeError, OSError)` → skip + count; `pipeline._read_history` catches any `Exception` from
   `read_history` → warning + the empty/partial `History`, never a failed job. The docstring's promise
   becomes literally true.
4. Tests in `tests/unit/test_git_history.py` (backend-free, real git in `tmp_path`): a commit that adds
   a file containing bytes `\xe4` in a `.h` file → history reads, that commit is skipped or read with
   replacement (state which) and the others are intact; a commit whose diff exceeds a monkeypatched
   `MAX_DIFF_BYTES` → skipped, counted, the rest intact; and in `test_ingest_pipeline.py` one case where
   `read_history` is monkeypatched to raise a bare `RuntimeError` and the source still indexes with
   `status == "ready"`, a code graph, and `history_skipped`/empty commits.

## Done when

Three stores + lint green, no pinned assertion changed, ledger summary (files, constant name and value,
the exact skip semantics), `horch tell orchestrator "[<role>] DONE: wp/e1fa ..."`, close pane.
