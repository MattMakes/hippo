# Brief: chronological JSONL fixture loading for the Task 5A temporal scenarios

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `t5afix` (branch `wp/t5afix`, base = the `rag-it-all-tibs` HEAD named in the spawn message).

GOAL: The RAG-all fixture loader can load `tests/fixtures/rag_all/temporal_events.jsonl` chronologically, using explicit parsed instants and the adapter ordering metadata each row carries (never wall-clock defaults), so the nine section 7 step 3 scenarios can be exercised end to end through the loader rather than only through hand-built worlds. Committed on `wp/t5afix`.

CONTEXT:
- Plan: `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` section 6 (last bullet: "Fixture loading gains chronological JSONL support ... explicit parsed instants and adapter ordering metadata, never wall-clock defaults") and section 7 step 3 (the nine scenarios). The fixture exists (14 rows; every claim row carries `precision`, ordering metadata is required on claim/barrier rows and forbidden on suppression rows; `tests/unit/test_temporal_conflicts.py` already validates its shape, read those tests first).
- Loader: find it with `rg -n "rag_all" src/hippo/evals/rag_all.py src/hippo/evals tests/fixtures/rag_all` (the Task 1 cross-source fixture loader and its README under `tests/fixtures/rag_all/`). Task 4d just converted `evals/rag_all.py` to `retrieval_session`; do not change that.
- Part 1 and part 2 signatures you drive: `select_history(store, *, workspace_id, access, selector, request_cutoff, clock)`, `TemporalPublicationPlan(published_at, closures, appends)`, `publish_staged_generation(..., plan=...)`, `SourceOrder`, `select_same_source`, `build_conflict_sets` (`ai_docs/reports/2026-09-11-t5a-int1-review.md` section 5 and `evidence-int2.md`).

REQUIRED BEHAVIOR:
1. A loader function (name yours; record it) reads the JSONL in row order, parses every instant as an aware UTC datetime (rejecting naive or missing required instants), preserves the row's original timestamp text/timezone/precision, and applies rows as recorded events in chronological `recorded_from` order: claims become staged generations published with the row's `published_at` (a correction row produces a `TemporalPublicationPlan` closing the segment it names), suppression rows apply the named suppression, barrier rows apply the restoration barrier. No `datetime.now`/`utc_now` anywhere in the loader; the caller supplies the clock.
2. Each of the nine scenarios has one end-to-end test through the loader plus the part 1/part 2 APIs: May ownership correction (original before, corrected after the cutoff), imported-old-last (no supersession), equal ETag / equal timestamp with different bytes (ambiguous, refetch requested), unknown date (contextual), environment collision (distinct scopes, no conflict), independent-source alternatives (support, not conflict), ordinary tombstone (history visible), all-history purge (denied), explicit restoration barrier.
3. Loading the same fixture twice into the same store is idempotent (exact retry semantics); loading into Ladybug and reopening preserves the loaded history.

FILES:
  - own: `src/hippo/evals/rag_all.py` (loader additions only; do not touch the session/dispatch code Task 4d changed) or a NEW `src/hippo/evals/rag_all_temporal.py` if the loader is cleaner apart (say which), NEW `tests/unit/test_temporal_fixture_loader.py`, `tests/fixtures/rag_all/README.md` (document the JSONL contract), `tests/fixtures/rag_all/temporal_events.jsonl` ONLY if a row is missing a field the loader needs (name it), EVIDENCE line for T5A3/T5A4 if you extend them (append `fixture_loader` keyword tests and note it), NEW `ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/evidence-fixture.md`.
  - do NOT touch: `src/hippo/knowledge/*`, `src/hippo/store/*`, `tests/unit/test_temporal_*.py` (add your tests in the new file), `docs/`, the checkpoint, checkboxes.

STEPS:
1. Worktree + venv (with the `mcp==2.1.1` pin). Baseline: T5A1–T5A6 ledger commands green; `tests/unit/test_rag_eval.py tests/unit/test_rag_eval_session.py` green.
2. RED: the nine scenario tests plus idempotence and reopen; save `/tmp/hippo-t5afix-red.log`.
3. Implement; GREEN Fake: the new file plus the ledger commands plus `test_rag_eval.py test_rag_eval_session.py test_managed_eval_activation.py`; log `/tmp/hippo-t5afix-fake-green.log`. GREEN Ladybug: the new file; log `/tmp/hippo-t5afix-ladybug-green.log`.
4. Ruff; evidence; commit on `wp/t5afix` in one or two commits.

DONE WHEN: steps 3–4 green with `-W error`; evidence written; commits; `horch done` lists the loader signature, files, the nine scenario test names, counts per backend and logs.

REPORT: `horch note` per step. `horch tell orchestrator "[<role>] BLOCKED: ..."` for contract or ownership questions; wait.
