# Brief: independent SPEC/QUALITY review of the Task 5A chronological fixture loader

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`); the work is merged at the HEAD named in the spawn message (branch `wp/t5afix`, commits `031597a`, `7b60888` on top of `79e379a`). You read and run; you do not edit source or tests.

GOAL: Verdict on the loader and, explicitly, on the ten unratified conventions its evidence declares, since a wrong convention would misrepresent the fixture rather than the code.

CONTEXT: plan `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` sections 1, 6 (last bullet) and 7 step 3; brief `ai_docs/handoffs/briefs/t5a-fixture-loader.md`; evidence `ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/evidence-fixture.md` (items 1–10 are the conventions to ratify or redirect); fixture `tests/fixtures/rag_all/temporal_events.jsonl` and its README section; loader `src/hippo/evals/rag_all_temporal.py`; tests `tests/unit/test_temporal_fixture_loader.py`. Part 1 and 2 reviews under `ai_docs/reports/2026-09-11-t5a-int*.md` for the APIs the loader drives.

FILES:
  - own: `ai_docs/reports/2026-09-12-t5a-fixture-review.md`.
  - do NOT touch: anything else.

STEPS:
1. Run, each to `/tmp/hippo-t5afix-review-<n>.log` with `echo EXIT $?`: T5A3 and T5A4 verbatim from the ledger (they now include the loader file and the `fixture_loader` keyword), `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_temporal_fixture_loader.py tests/unit/test_rag_eval.py tests/unit/test_rag_eval_session.py tests/unit/test_managed_eval_activation.py -q -o addopts='' -W error`, and the loader file alone on Ladybug.
2. SPEC review; PROVEN (test) / UNTESTED / VIOLATED (file:line): every instant parsed as aware UTC with naive or missing required instants rejected; original text/timezone/precision preserved; rows applied in chronological `recorded_from` order bounded by the caller's clock; no wall clock anywhere in the loader (`rg -n "datetime.now|utc_now|time\(\)" src/hippo/evals/rag_all_temporal.py` empty); each of the nine scenarios proven end to end through the part 1/2 APIs with the assertion the plan names; idempotent reload writes nothing; Ladybug close/reopen preserves the loaded history.
3. CONVENTIONS: for each of evidence items 1–10 (derived closure via `fully_superseded_version_ids` limited to the same source's earlier open segments; `series_key` = source name; default subject/object kinds and scope key; per-source `rule_version`; pre-resolved barriers; lending the store its private generation clock and reading `_knowledge_get`; revision reuse on re-import; scenario 8 proved on the broad history proof rather than purge markers; and the two remaining), state ACCEPT or REDIRECT with the reason, judged against plan sections 1 and 3: in particular whether derived closure (item a) makes the May example prove what the plan describes or something weaker, and whether reaching store privates (item f) is acceptable for a fixture loader or should become a public test seam.
4. QUALITY: whether the loader could silently apply rows out of order under equal `recorded_from`; whether `TemporalFixtureError` covers every malformed shape; whether the loader can be misused as a production ingestion path (it must not be importable by production routes; check nothing under `src/hippo/web`, `mcp_server.py`, `cli.py` imports it).

DONE WHEN: `ai_docs/reports/2026-09-12-t5a-fixture-review.md` exists with `SPEC: PASS|FAIL`, `QUALITY: PASS|FAIL`, the scenario table, the ten-convention table with ACCEPT/REDIRECT, numbered findings with severity, file:line, why, proposed fix, run results with log paths. `horch done` states the verdicts, the number of REDIRECTed conventions, and the report path.

CONSTRAINTS: no edits outside your report; no Neo4j; `HIPPO_TEST_STORE` explicit on every command.

REPORT: `horch note` after the runs, after the tables, after the report.
