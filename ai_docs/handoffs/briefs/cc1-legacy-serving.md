# Brief: CC1 — legacy serving until publication (managed code capture, task 1)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `cc1` (branch `wp/cc1`, base = the `rag-it-all-tibs` HEAD named in the spawn message).

GOAL: A source whose managed rows are all unpublished (staging or failed, no active pointer, no published `IndexEvent`) keeps serving its legacy graph through every current read path, appears exactly once in every inventory, and flips to managed atomically at publication. This is blocker A of `ai_docs/plans/rag-it-all-task-5-managed-code-capture.md` (section 7) and gate CD2 of `ai_docs/gates/rag-it-all/task-5-code-capture/GATES.md`. Committed on `wp/cc1`.

CONTEXT: read the plan's sections 1, 2, 7 and the "Orchestrator rulings" (ruling 3 releases `context.py` and `status.py` to you and names the activation regression you must keep green). Today a source leaves the legacy lane as soon as ANY `Artifact` or `Generation` row names it (`src/hippo/context.py:~171-173`, `src/hippo/status.py:~58-59`) while the managed lane contributes nothing until `active_generation_id` is set (`context.py:~215-219`); the prose coordinator never exposed this because it installs and publishes in one transaction. Also `store.source_is_managed` (`src/hippo/store/generations.py:~58`) and `begin_managed_source` (find it with `rg`), and the prose coordinator's use of both (`src/hippo/ingest/prose_generation.py`).

REQUIRED BEHAVIOR:
1. `GenerationQueries.source_serves_legacy(source_row) -> bool` beside `source_is_managed`: true iff the source is not marked managed, has no `active_generation_id`, and has no published `IndexEvent`; false otherwise. Pure store read, no lock, no clock.
2. `context.py` and `status.py` classify a source by `source_serves_legacy` (legacy lane) versus the active pointer (managed lane), never by Artifact/Generation presence. A staged-only source serves its legacy passages, code and facts; a published one serves its generation; no source appears in both lanes or in neither.
3. `begin_managed_source` is invoked inside the publication transaction (with `publish_staged_generation`), not before staging, for the prose coordinator too; the coordinator's own tests (`tests/unit/test_prose_generation.py`, `test_managed_pipeline_activation.py`) pass unchanged, and a Ladybug close/reopen during staging still serves legacy.
4. Tests (`tests/unit/test_converting_source_serving.py`): stage managed rows for a legacy source (use the coordinator's detached preparation or write staging rows directly under a claimed build), assert the legacy graph still answers `ask`/`search`/status/source inventory with one row, publish, assert the managed generation now serves and the legacy rows are unselected; a failed unpublished generation keeps legacy serving; the `source_is_managed` flag flips only at publication; Ladybug reopen mid-staging.

FILES:
  - own: `src/hippo/store/generations.py` (the predicate and the `begin_managed_source` call placement only), `src/hippo/context.py`, `src/hippo/status.py`, `src/hippo/ingest/prose_generation.py` (only the `begin_managed_source` call site, if it lives there), NEW `tests/unit/test_converting_source_serving.py`, NEW `ai_docs/gates/rag-it-all/task-5-code-capture/evidence-cc1.md`. You may adapt an activation test assertion ONLY if it pins the Artifact-presence classification; name each in the evidence.
  - do NOT touch: anything else (CC4 owns new ingest capture files; the design reviewer is read-only).

STEPS: worktree + venv (with the `mcp==2.1.1` pin); baseline the activation regression from ruling 3 plus `test_prose_generation.py test_generation_store.py test_structural_loading.py` green; RED; implement; GREEN Fake on those plus the new file; GREEN Ladybug on the new file plus `test_prose_generation.py -k reopen`; Ruff; evidence (with the CD2 command result); commit in one or two commits.

DONE WHEN: green on both backends with `-W error` (AnyIO form (b) only where a listed file imports `fastapi.testclient` at module level); evidence written; `horch done` lists the predicate signature, the classification sites changed (file:line), any adapted assertion, counts and logs. Then release `store/generations.py` to CC2 by finishing.

REPORT: `horch note` per step; `horch tell orchestrator "[<role>] BLOCKED: ..."` for contract questions.
