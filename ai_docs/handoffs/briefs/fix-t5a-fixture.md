# Brief: fix the Task 5A fixture loader after independent review (F1–F6)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`) at HEAD `b5a5086` or later. Do NOT commit; the orchestrator commits. Another worker (sonnet-4) is editing `evals/rag_all.py`, `evals/runner.py`, `evals/question_maker.py`, `web/routes/evals.py` and two partial templates in this tree; do not touch those.

GOAL: The chronological loader never invents an instant, preserves a declared offset, wraps every malformed row in `TemporalFixtureError`, closes superseded segments by adapter ordinal only, and the purge scenario reaches purge markers. Then the review's ten conventions are ratified or redirected as decided below.

CONTEXT: review `ai_docs/reports/2026-09-12-t5a-fixture-review.md` (read F1–F10 and the convention table); evidence `ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/evidence-fixture.md`; loader `src/hippo/evals/rag_all_temporal.py`; tests `tests/unit/test_temporal_fixture_loader.py`; fixture `tests/fixtures/rag_all/temporal_events.jsonl` and `tests/fixtures/rag_all/README.md`; plan sections 1–3 of `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md`.

DECISIONS (final):
- F1: an undated claim keeps `source_timestamp_original=None`; the loader never stamps Hippo's recorded instant into a source field (`rag_all_temporal.py:~184`). Test: the unknown-date row serializes with null original text and precision `unknown`.
- F2: a declared non-UTC offset is preserved as the original text/timezone while the computed instant is UTC (`:~137-138`); add a fixture row or a parsing test with `+02:00` proving both.
- F3: every malformed row (bad suppression reason, bad view_applicability, missing key, pydantic validation failure) raises `TemporalFixtureError` naming the row index; tests per shape.
- F4: two rows with equal `recorded_from` in one monotonic series must not drop a closure; order ties by adapter ordinal, and if two rows tie on both, raise `TemporalFixtureError` (the fixture must be unambiguous). Test the tie.
- F5 (modeling, decided): closure follows the adapter ordinal ONLY. Publishing a claim with ordinal N closes every same-series open segment with a LOWER ordinal; a claim arriving with a lower ordinal than an existing open segment closes nothing and stays recorded-open as retained history (its currentness is decided by `select_same_source`, not by recorded intervals). Consequence to prove: after 2026-05-01 the imported-old-last row is NOT the catalog's proven current claim; the newer-ordinal claim is, and both remain queryable in history.
- F6 (modeling, decided): the all-history purge scenario purges a PROVEN (dated) claim so its revision can enter a `HistoryManifest`; adjust the fixture (change the purge row's target, or add a dated claim row for it) and assert that an authorized reader's `purged_history_evidence` yields `evidence_purged` markers for it, that a reader who cannot prove the manifest gets `SnapshotUnavailable`, and that the unknown-date row stays contextual (keep the existing scenario 8 assertion on the broad proof as well).
- Conventions: ACCEPT items 2, 3, 4, 6, 7, 8, 10 as the review did; REDIRECT items 1, 5, 9 exactly as the review proposes (derived closure replaced by the ordinal rule above; pre-resolved barriers replaced by the per-row behavior the review describes; the third as written). If a redirect conflicts with F5/F6 above, F5/F6 win; say so.
- F7–F10: apply the documentation fixes.

FILES:
  - own: `src/hippo/evals/rag_all_temporal.py`, `tests/unit/test_temporal_fixture_loader.py`, `tests/fixtures/rag_all/temporal_events.jsonl` (rows for F2 and F6 only; keep the existing nine scenarios and labels), `tests/fixtures/rag_all/README.md`, `ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/evidence-fixture.md` (append "Fixes after review" and the convention outcomes), EVIDENCE lines for T5A3/T5A4.
  - do NOT touch: `src/hippo/knowledge/*`, `src/hippo/store/*`, `tests/unit/test_temporal_evidence.py`, `test_temporal_conflicts.py`, anything sonnet-4 owns (listed above), `docs/`, the checkpoint, checkboxes.

STEPS:
1. Baseline: T5A3 and T5A4 ledger commands green; `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_temporal_fixture_loader.py tests/unit/test_temporal_conflicts.py -q -o addopts='' -W error` green.
2. RED for F1–F6, save `/tmp/hippo-t5afixfix-red.log`.
3. Implement; GREEN: T5A3, T5A5, T5A6 on Fake and T5A4 on Ladybug (`/tmp/hippo-t5afixfix-{fake,ladybug}-green.log`), plus `tests/unit/test_rag_eval.py tests/unit/test_rag_eval_session.py` on Fake.
4. Ruff; evidence; EVIDENCE lines.

DONE WHEN: green on both backends; evidence appended; `horch done` lists per finding the change (file:line) and test, the convention outcomes, counts and logs. No commits.

REPORT: `horch note` after RED and after GREEN. `horch tell orchestrator "[<role>] BLOCKED: ..."` for any conflict with these decisions.
