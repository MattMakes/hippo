# Finish the recovered prose decoder experiment

You are a fresh Codex Sol worker. Use only `horch` for fleet communication. No Claude workers or nested agents. Work in the root tree `/Users/mascott/projects/hippo`, branch `rag-it-all-tibs`, initial HEAD `1ff6a37`. The user authorized continued measured optimization and commits; the orchestrator owns integration commits after measurement.

Read `ai_docs/plans/2026-09-16-prose-decode-plan.md` completely, then `src/hippo/store/knowledge.py`, relevant immutable ProseExtraction contracts in `src/hippo/knowledge/model.py`, and `tests/unit/test_prose_decode_cache.py`. These already contain an unfinished implementation recovered from session 01a0ac3b-80c5-79f1-97d2-8ff5133bfe55. Preserve useful existing changes.

Goal: finish Task 1 and prove G1/G2 of `ai_docs/gates/prose-decode/GATES.md`, preserving every current storage read and authorization boundary. Done means correct bounded exact-content reuse, passing relevant tests, readable implementation, and an evidence report. G3 benchmark is the orchestrator's responsibility, so do not mark overall task complete.

Own only `src/hippo/store/knowledge.py`, `tests/unit/test_prose_decode_cache.py`, and new `ai_docs/reports/2026-09-16-prose-decode-implementation.md`. Do not edit other source, plans, gates, or reports. No worktree needed; other workers have disjoint ownership. Do not commit, stage, push, start model benchmarks, run the full suite, or use Neo4j. Never touch application data/, original /private/tmp/hippo-real-eval-YCrJeD data, source repos/notes/Mongo, or service configuration.

Steps:
1. Extract the plan's requirements into a checklist. Inspect all `_knowledge_records` callers and store locks across Ladybug, FakeStore and Neo4j classes. Confirm signature change is wired and cached models are deeply immutable.
2. Run existing new tests on Ladybug and fake explicitly, save logs under /tmp/hippo-perf-decode-*. A failing assertion must be diagnosed; preserve current behavior except specified reuse/no-row-mutation. Check malformed changed rows, database deletion, store isolation, entry/byte bounds, Unicode sizing, unsupported raw types and concurrent reads. Add a meaningful regression only for a missing behavior you uncover; obtain RED first for any new fix.
3. Make the smallest needed corrections, if any, within ownership. Avoid unrelated refactoring. If scope must expand, tell orchestrator and wait.
4. Run G1/G2 commands from the ledger with `HIPPO_TEST_STORE=ladybug`, then the same files with fake. `.venv/bin/python -m pytest ... -q -o addopts='' -W error`. Use only the narrowly sanctioned anyio warning filter if it actually arises. Capture full logs and exit codes. Run Ruff check/format on owned files, compileall, git diff --check.
5. Write the report with numbered requirements, exact checks/counts/logs, files changed and any gaps. Do not claim RED for tests written by an earlier session unless its actual assertion failure evidence is recoverable.
6. Send `horch tell orchestrator "[ROLE] DONE: ..."`, record `horch done` summary and close normally. No continued idle worker.

Common environment: `.venv/bin/python`, default pytest store is Ladybug; set HIPPO_TEST_STORE explicitly. No full expensive tests during model timing. Reporting must not reproduce private evaluation source text. Existing fleet rules apply except root-tree ownership above, no Claude trailer, and no commit by this worker.
