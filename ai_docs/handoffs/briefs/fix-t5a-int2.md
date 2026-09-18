# Brief: fix Task 5A integration part 2 after independent review (F1–F6)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `t5a2fix` (branch `wp/t5a2fix`, base = the `rag-it-all-tibs` HEAD named in the spawn message).

GOAL: The recorded-closure helper can only run under the publication primitive's authority (not merely inside any transaction); the "preserved evidence dependencies" enforcement for an appended version is pinned by a test that fails if the check is removed; a plan cannot close a row the same generation is publishing; the rollback test asserts byte-identity; the stale-fence and decision-3 cases are covered. Committed on `wp/t5a2fix`.

CONTEXT:
- Review: `ai_docs/reports/2026-09-11-t5a-int2-review.md` (read F1–F6 fully; F7–F10 are informational; section 5 lists what the next worker should do). Implementer evidence: `ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/evidence-int2.md`. Plan: `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` section 5 with its "Amended 2026-09-12 in integration part 2" block.
- Code: `src/hippo/store/knowledge.py` (`_close_recorded_intervals` ~:714, `_authorized_recorded_closure`), `src/hippo/store/generations.py` (`_validate_publication_plan`, `_observe_recorded_closures`, `_plan_lineage`, the check at ~:914 `not dependencies <= revisions or not supports <= staged`, `publish_staged_generation(..., plan=)`), `src/hippo/knowledge/temporal.py` (`TemporalPublicationPlan`, `RecordedSegment`), tests `tests/unit/test_temporal_evidence.py` (`correction_world`, `recorded_correction` cases), `tests/unit/test_generation_store.py`.

DECISIONS (final):
- F1 (major): make the claim true, option (b). `publish_staged_generation` mints a capability inside the publication transaction after `_validate_publication_plan` succeeds (a frozen object bound to the generation ID, plan fingerprint and the transaction; not persisted, not exported); `_close_recorded_intervals` requires it as a keyword argument and verifies it matches the current transaction and generation before touching any row. A direct call with a transaction but no capability (the review's P1 probe) raises. Reword `knowledge.py:714-715` and evidence decision 2 to describe the real boundary.
- F2 (major): add the test the review specifies, shaped to fail if the `generations.py:~914` check is removed: inside `generation_write` of the second generation in a `correction_world` variant, create a version on a new assertion whose support span belongs to the first generation's revision, add the version as a member but deliberately not its support row, and assert a plan appending it raises "depends on evidence outside its generation"; also assert the companion fact that adding the support row on the foreign span is refused as outside generation revisions.
- F3 (minor): `_validate_publication_plan` rejects a closure target that is itself a member (or appended row) of the generation being published, with a test; a correction must close only rows published by an earlier generation.
- F4 (minor): pin decision 3 (a version corroborated by a second source cannot be closed by one source's publication) with a repo test derived from the review's probe.
- F5 (minor): the rollback tests assert byte-identity of every affected row (serialize before, compare after each failpoint), not merely openness.
- F6 (minor): add the stale-fence correction-path test (precondition (d)).

FILES:
  - own: `src/hippo/store/knowledge.py` (closure helper only), `src/hippo/store/generations.py` (plan validation and publication only), `src/hippo/knowledge/temporal.py` (capability type only, if you place it there), `tests/unit/test_temporal_evidence.py`, `tests/unit/test_generation_store.py`, `ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/evidence-int2.md` (append "Fixes after review"), `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` (section 5 note only), EVIDENCE lines for T5A3/T5A4.
  - do NOT touch: `src/hippo/knowledge/{snapshots,access,model,conflicts}.py`, `store/snapshots.py`, `evals/*` (the fixture-loader worker owns `evals/rag_all.py`), `ingest/*`, `web/*`, `docs/`, the checkpoint, checkboxes.

STEPS:
1. Worktree + venv (with the `mcp==2.1.1` pin). Baseline: T5A1–T5A6 ledger commands green plus `tests/unit/test_generation_store.py tests/unit/test_prose_generation.py`.
2. RED for F1 (direct-call probe must raise after the change; write the test first), F2, F3, F4, F6; save `/tmp/hippo-t5a2fix-red.log`.
3. Implement; strengthen F5; GREEN Fake: the ledger commands plus `tests/unit/test_generation_store.py tests/unit/test_prose_generation.py tests/unit/test_managed_pipeline_activation.py tests/unit/test_snapshot_store.py` (the coordinator must still publish plan-free generations unchanged); log `/tmp/hippo-t5a2fix-fake-green.log`. GREEN Ladybug: T5A4 plus `tests/unit/test_generation_store.py`; log `/tmp/hippo-t5a2fix-ladybug-green.log`.
4. Ruff (T5A6 command); evidence; commit on `wp/t5a2fix` in one or two commits.

DONE WHEN: green on both backends with `-W error`; evidence and plan note written; commits; `horch done` lists per finding the change (file:line) and the test, the capability's shape, counts and logs.

REPORT: `horch note` per step. `horch tell orchestrator "[<role>] BLOCKED: ..."` for any conflict with these decisions.
