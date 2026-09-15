# Brief: production activation Task 2 — exact selected-generation projection and generation-aware source inventory

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `pa2` (branch `wp/pa2`, base `26f9a55`).

GOAL: Implement Task 2 of `ai_docs/plans/rag-it-all-task-5-production-activation.md`: `GraphIndex.selected_managed_generations` populated only from exact authorized selected generation pairs, preserved through scoping/composition/replacement/fingerprinting, and a `status.source_view` that makes an authorized EMPTY active generation visible with zero counts while hiding denied, suppressed, staging and retired ones, with all public counts derived from held-graph provenance. Committed on `wp/pa2`.

CONTEXT:
- Plan sections that bind you, read them completely: "Structural source inventory, including empty generations", invariants 5, 6, the Task 2 row of the ownership table, and the adversarial cases about the exact empty generation and the shared code object / relation support from multiple generations.
- Gates you are proving (ledger `ai_docs/gates/rag-it-all/task-5-production-activation/GATES.md`): PA2 entirely; the inventory half of PA7. PA6 belongs to a later worker.
- Existing code you extend: `src/hippo/hipporag/graph_index.py` (`GraphIndex`, `scoped`, `compose_graphs`, `view_fingerprint`, `StructuralCodeEvidence`, `StructuralObjectEvidence`, relation `source_generations`), `src/hippo/knowledge/projection.py` (`project_managed_graph`, `_assemble`), `src/hippo/context.py` (`AppContext.graph_for`, structural loading, selected generation mapping), `src/hippo/status.py` (`source_view`, `system_status`), `src/hippo/knowledge/replay.py` only if reconstruction must carry the new field. Read `tests/unit/test_structural_loading.py`, `tests/unit/test_status_access.py`, `tests/unit/test_evidence_projection.py`, `tests/unit/test_dense_session.py` for how structural sessions, audiences and managed fixtures are built in tests.
- Reviewed facts from the prior session: structural loading is opt-in (`structural=True`) and performs no model access; `dense_session` classifies contributors ONLY from retained evidence sidecars/provenance; `view_fingerprint` uses canonical retained vectors; source scoping removes unsupported relations and rebuilds weights; `status.source_view` currently borrows the selected graph. The new field is evidence-selection metadata, NOT a dense contributor list.

FROZEN CONTRACT:

```python
# GraphIndex
selected_managed_generations: tuple[tuple[str, str], ...] = ()
# sorted, unique (source_id, active_generation_id) pairs proven for this view
```

A pair may be added by `project_managed_graph` only when ALL hold: the Source current pointer and Generation match the caller's exact selected generation; `(generation_id, manifest revision_id)` is an exact `GenerationMember` (NOT `GenerationEvidenceMember`, whose record kinds exclude revisions); that manifest revision is in the audience's `AuthorizedEvidence.revision_ids`; and its Artifact is authorized and owned by that source. (Corrected 2026-09-11 after worker question Q1.) `AppContext` passes the selected source-to-generation mapping explicitly into projection. Never infer an empty source from unrestricted Source rows or manifest counts. Preserve/filter/compose the field in `GraphIndex.scoped`, `_assemble`, `compose_graphs`, every structural/dense `dataclasses.replace`, and `view_fingerprint`. Empty G1 to empty G2 publication changes the fingerprint. An empty selected pair triggers no profile resolution and no model I/O.

`status.source_view` obtains a structural session when it owns one, treats the field as representation, renders the Source control name, owner/access labels, status/stage/error/progress and created timestamp for an empty authorized generation with zero counts, and omits policy-denied or tombstoned empty sources. Do not synthesize `"Managed source"` or force `status="ready"`. Counts for a managed row come only from the held graph and its exact provenance (passages owned by the source; each retained Fact-to-passage support of the source; unique code nodes contributed via `StructuralCodeEvidence`/`StructuralObjectEvidence` including shared nodes; relations whose `source_generations` contains the pair including relation-only support; languages/edge kinds from those records). Never raw Store Source counts. Validate the held session after DTO construction.

FILES:
  - own: `src/hippo/hipporag/graph_index.py`, `src/hippo/knowledge/projection.py`, `src/hippo/knowledge/replay.py`, `src/hippo/context.py`, `src/hippo/status.py`, `tests/unit/test_structural_loading.py`, `tests/unit/test_status_access.py`, NEW `tests/unit/test_managed_source_inventory.py`, NEW `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa2.md`.
  - do NOT touch: `src/hippo/store/*`, `src/hippo/ingest/*`, `src/hippo/web/*`, `src/hippo/knowledge/query_access.py`, `dense_session.py`, `dense.py`, `access.py`, `ask.py`, `mcp_server.py`, `cli.py`, the shared `GATES.md`, `docs/`, the checkpoint. If `dense_session.py` appears to need a change for the empty-pair rule, stop and ask; the intended answer is that your tests prove the existing behavior.
- Existing public signatures of `graph_for`, `query_session`, `project_managed_graph`, `compose_graphs`, `scoped` keep working for every current caller; add keyword-only parameters with defaults.

STEPS:
1. Worktree + venv per the rulebook. Confirm green baseline: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_structural_loading.py tests/unit/test_status_access.py tests/unit/test_evidence_projection.py tests/unit/test_dense_session.py tests/unit/test_graph_index.py -q -o addopts='' -W error`.
2. RED: write `tests/unit/test_managed_source_inventory.py` covering: an exact empty published generation is visible to its owner and to an allowed reader with control name and zero counts; a denied reader does not see it; after a current-only source suppression it disappears; staging, retired and failed generations never produce a pair; a generation whose manifest revision is not in the audience's authorized revisions produces no pair even when the Source ACL allows; the pair survives `scoped`, `compose_graphs`, structural-to-dense `replace`; empty G1 to empty G2 changes `view_fingerprint`; an empty selection performs no Ollama call (use the MockTransport pattern from `test_dense_session.py` and assert zero requests); shared code object and one relation support from two generations are counted for each contributing selected source without duplicating global nodes; retired/staging contributions do not inflate current counts; the held session is validated after DTO construction (revoke between projection and DTO return, expect the existing authorization error). Save `/tmp/hippo-pa2-red.log`. Extend `test_structural_loading.py` and `test_status_access.py` where the behavior lives there.
3. Implement in this order: field + preservation in `graph_index.py`; population rule in `projection.py`; explicit mapping from `context.py`; `status.source_view`; `replay.py` only if reconstruction breaks.
4. GREEN on Fake: PA2's three files plus regressions `tests/unit/test_evidence_projection.py tests/unit/test_dense_session.py tests/unit/test_dense_capability.py tests/unit/test_graph_index.py tests/unit/test_query_session.py tests/unit/test_query_snapshots.py tests/unit/test_core_context.py tests/unit/test_replay.py tests/unit/test_web_sources.py tests/unit/test_web_status.py tests/unit/test_mcp_server.py` (use `ls tests/unit | rg 'status|source|graph_index|context|replay|projection'` to catch the real names and add them). Log `/tmp/hippo-pa2-fake-green.log`.
5. GREEN on Ladybug: `test_managed_source_inventory.py test_structural_loading.py test_status_access.py`. Log `/tmp/hippo-pa2-ladybug-green.log`.
6. Ruff check + format on every changed file.
7. Write `evidence-pa2.md`: commands, result lines, log paths, RED log path, the list of every `dataclasses.replace(...)` / constructor site you audited for the new field (with `rg -n "replace\(|GraphIndex\(" src/hippo` as the source of the list), and any deviation with reason.
8. Commit on `wp/pa2` in two or three commits. Stage only owned files.

DONE WHEN: steps 4–6 green with `-W error`; `evidence-pa2.md` written; commits on `wp/pa2`; `horch done` lists commit hashes, files touched, the audited replace/constructor site list count, test counts per backend with log paths, and any existing test you modified.

OUT OF SCOPE: query-session default flip to structural (Task 4), routes, pipeline, store changes, dense routing changes, Neo4j runs.

REPORT: `horch note` at each step. `horch tell orchestrator "[<role>] BLOCKED: ..."` for contract or ownership questions; wait for the answer.
