# Brief: PA2 finding 4, attribute code edges by generation membership in status

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `pa2f4` (branch `wp/pa2f4`, base = the `rag-it-all-tibs` HEAD named in the spawn message).

GOAL: `status.source_view` attributes `CODE_EDGE` arrows (and every other code relation it counts) by the selected generation's exact membership rather than by node membership, so a source's counts never include an edge that belongs to another generation, a staged generation, or a tombstoned one. The finding is PA2-4 in `ai_docs/reports/2026-09-11-pa2-review.md`, restated in `ai_docs/reports/2026-09-13-pa8-resign.md`; it became REACHABLE when CC10 (`evidence-cc10.md`, merged) started dispatching managed code generations that write native `CODE_EDGE` rows. Committed on `wp/pa2f4`.

CONTEXT: `src/hippo/status.py` (`source_view`, the `_managed_source` / `_legacy_source` renderers CC1fix introduced, `edges_by_kind`), `src/hippo/context.py::legacy_lane` (ruling 14: only untagged rows serve the legacy lane), CC2's scoped reads (`_native_relationships(*, generation_id=...)`, `_edges_touching`, `evidence-cc2.md`), `GraphIndex.selected_managed_generations`, and the multi-generation invariant pinned by `tests/unit/test_multi_generation_support.py` (every projected relation carries exactly one contributing pair). The plan's counter is written in the activation plan's rollout section (`:~279`, PA2-4 sentence).

REQUIRED BEHAVIOR:
1. For a managed source, `source_view`'s `edges_by_kind` for native code relations counts only rows whose `generation_id` is the selected (active) generation, read through a scoped `_native_relationships(generation_id=...)` call, never by walking node membership; a staged, failed, retired or tombstoned generation contributes zero; the legacy lane's counts are unchanged (untagged rows only, as today).
2. Tests in a NEW `tests/unit/test_status_code_edges.py` on Fake and Ladybug: a published code generation counts exactly its CODE_EDGE rows; a second staged generation of the same source adds nothing until it publishes and then replaces the count atomically; a tombstoned source shows no code edges; an edge whose endpoints straddle a generation boundary is refused by the store (CC2's cross-generation check) and never counted; a legacy repo source keeps today's count.
3. No change to `context.py`, `store/*`, `knowledge/*`, or the ingest lane; if the scoped read you need does not exist, stop and name it.

FILES:
  - own: `src/hippo/status.py`, NEW `tests/unit/test_status_code_edges.py`, NEW `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa2f4.md`.
  - do NOT touch: anything else (CC11 is live on tests/fixtures/evidence and the plan; never edit `GATES.md`).

STEPS: worktree + venv (`mcp==2.1.1` pin); baseline the PA2 CHECK line and `tests/unit/test_status_access.py tests/unit/test_managed_code_activation.py` on Fake; RED (a staged second generation inflates the count today); fix; GREEN on the same plus the new file, Fake and Ladybug (`test_status_code_edges.py` and `test_status_access.py`); Ruff; evidence; one or two commits.

DONE WHEN: green both backends; PA2 line green; evidence written; `horch done` lists the commits, counts and logs and names the scoped read used.

REPORT: `horch note` per step; `horch tell orchestrator "[<role>] BLOCKED: ..."` if a store read is missing.
