# Brief: independent SPEC/QUALITY review of activation Task 2 (selected-generation inventory)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`). The work under review is merged at `82bd317` (branch commits `e9e2afe`, `65b13bc`, `0a94c51`, `6d1afb8`). You read and run; you do not edit source or tests.

GOAL: Independent SPEC and QUALITY verdict on Task 2 of `ai_docs/plans/rag-it-all-task-5-production-activation.md` before it is published.

CONTEXT:
- Plan sections that bind: "Structural source inventory, including empty generations", invariants 5 and 6, the Task 2 row of the ownership table, the adversarial cases about the exact empty generation and the shared code object / relation support from multiple generations. Gates PA2 (all) and PA7 (inventory half) in `ai_docs/gates/rag-it-all/task-5-production-activation/GATES.md`.
- Implementer's evidence: `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa2.md`. Verify its claims.
- Diff to review: `git diff 26f9a55..6d1afb8 -- src/ tests/` (8 files). New: `tests/unit/test_managed_source_inventory.py`. Modified: `src/hippo/hipporag/graph_index.py`, `src/hippo/knowledge/projection.py`, `src/hippo/knowledge/replay.py`, `src/hippo/context.py`, `src/hippo/status.py`, `tests/unit/test_structural_loading.py`, `tests/unit/test_status_access.py`.
- Orchestrator decisions the implementer followed (not deviations): the pair rule is the plan's `GenerationMember` rule (pair iff `(generation_id, manifest revision_id)` is a `GenerationMember`, that revision is in `AuthorizedEvidence.revision_ids`, and its Artifact is authorized and owned by that source); Source-control presentation (name, owner/access, created, status, stage, progress) renders for every managed row whose pair is proven and stays withheld when evidence is visible but no pair is proven; managed `error` stays withheld until Task 3's closed mapper; `status._audience_inventory` opens its owned session with `structural=True`; `source_view` keeps `ctx.graph_for(access, structural=True)` for its own acquisition because `web/routes/sources.py::reindex_all` validates the view after the pipeline call (Task 4 obligation); AnyIO `-W error` warning handled with the per-test marker in `test_status_access.py`.

FILES:
  - own: `ai_docs/reports/2026-09-11-pa2-review.md`.
  - do NOT touch: anything else. Other workers own `src/hippo/ingest/prose_generation.py` and its test, and `src/hippo/knowledge/conflicts.py` in this tree.

STEPS:
1. Run, each to `/tmp/hippo-pa2-review-<n>.log` with `echo EXIT $?`:
   a. the PA2 CHECK line verbatim from the ledger (Fake);
   b. `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_managed_source_inventory.py tests/unit/test_structural_loading.py -q -o addopts='' -W error`;
   c. `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_dense_session.py tests/unit/test_dense_capability.py tests/unit/test_evidence_projection.py tests/unit/test_graph_index.py tests/unit/test_query_session.py tests/unit/test_query_snapshots.py tests/unit/test_core_context.py tests/unit/test_replay.py tests/unit/test_local_workspace_membership.py tests/unit/test_managed_source_lifecycle.py -q -o addopts='' -W error` (use `ls tests/unit` to correct any name that does not exist and say so).
2. SPEC review; classify PROVEN (test name) / UNTESTED / VIOLATED (file:line):
   a. `selected_managed_generations` is sorted, unique, one generation per source, validated so `dataclasses.replace` cannot smuggle a bad value.
   b. The pair rule above, including: a manifest revision NOT in the audience's authorized revisions yields no pair even when the Source ACL allows; staging/retired/failed generations never yield a pair; a current-only source suppression removes the pair through the normal proof; no inference from unrestricted Source rows or manifest counts.
   c. Preservation through `scoped` (including the identity fast path the implementer says leaked an evidence-less pair), `_assemble`, `compose_graphs` (union; populated shortcut counts a pair-only lane), every structural/dense `replace`, and `view_fingerprint` (appended only when non-empty so legacy fingerprints are byte-identical; empty G1 to empty G2 changes it).
   d. An empty selected pair triggers no profile resolution and no model I/O (the implementer notes `retrieval_session` makes zero HTTP calls on an empty corpus while `dense_session` makes six; confirm the assertion is on the right layer and that a route reaching `dense_session` with only an empty pair still performs no model I/O, or record it as a Task 4 obligation).
   e. `source_view`: proven pair renders Source control name/owner/created/status/stage/progress with zero counts for an empty generation; denied reader and tombstoned source omitted; no `"Managed source"` synthesis; no forced `status="ready"`; counts (passages, fact links, unique code nodes including shared, relations whose `source_generations` contain the pair including relation-only, languages/edge kinds) from held-graph provenance only; never raw Store Source counts; held session validated after DTO construction.
   f. Shared code object and relation support from two generations counted for each contributing selected source without duplicating global nodes; retired/staging contributions do not inflate current counts.
   g. Ladybug close/reopen preserves the pair and renders a byte-identical row.
3. QUALITY review, with attention to: the `scoped` fast-path guard (does it change any legacy behavior?); `compose_graphs` union semantics when two lanes select different generations for one source (must be impossible or must raise; check); `_build_managed_graph` proofs tuple change `(engine, proof, local_selected)` and every consumer of that tuple; whether `status._managed_source` can still read a raw Source count anywhere; the `test_status_access.py` mock-graph changes (do they weaken what the existing leak tests prove?); the one-time saved-fingerprint invalidation for managed corpora (intended; confirm legacy-only payloads are byte-identical); any Neo4j-specific projection path without a test in this tree.
4. Report the verbatim signature of `project_managed_graph` (with the new keyword) and of `status.source_view` for the Task 4 brief.

DONE WHEN: `ai_docs/reports/2026-09-11-pa2-review.md` exists with `SPEC: PASS|FAIL`, `QUALITY: PASS|FAIL`, the a–g table, numbered findings with severity (blocker / major / minor), file:line, why, proposed fix, run results with log paths, and the signatures. `horch done` states both verdicts, finding counts by severity, and the report path.

CONSTRAINTS: no edits outside your report; no Neo4j; `HIPPO_TEST_STORE` explicit on every command.

REPORT: `horch note` after the runs, after the SPEC table, after the report.
