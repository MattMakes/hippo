# Brief: knowledge must not import ingest (layering follow-up)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `layering` (branch `wp/layering`, base = the `rag-it-all-tibs` HEAD named in the spawn message).

GOAL: `hippo.knowledge` no longer imports anything from `hippo.ingest`, `hippo/ingest/__init__.py` no longer imports `pipeline` eagerly, and the lazy accessor added at `da51784` becomes unnecessary (keep the import-order test; it must still pass with the accessor removed). Committed on `wp/layering`.

CONTEXT:
- The incident: `ai_docs/checkpoints/2026-09-11-execution-state.md` ("Import-order incident") and `ai_docs/handoffs/briefs/task4-notes.md` ("Layering follow-up"). `hippo.knowledge.generation_profiles` and `hippo.knowledge.input_binding` import `hippo.ingest.accepted_inputs` (`AcceptedInputs`, `CaptureLimits`, `InputDisposition`) and `hippo.ingest.provenance` (`RawInput`); `hippo.ingest.prose_generation` imports `hippo.knowledge.generation_profiles` (`MANIFEST_EXTERNAL_ID`, `embedding_mode`, `validate_generation_profile`); `hippo/ingest/__init__.py:15` imports `pipeline`, which now reaches `managed_activation` lazily through `pipeline._managed()`.
- Rule: `hippo.ingest` may import `hippo.knowledge`; never the reverse. `tests/unit/test_import_order.py` guards fresh-interpreter imports of the entry modules; extend it rather than weakening it.

DECISIONS:
1. Move the shared input contracts that knowledge needs into a leaf module under `hippo.knowledge` (for example `hippo/knowledge/inputs.py`): `ByteInput`, `FileInput`, `ExcludedInput`, `CaptureLimits`, `AcceptedInputs`, `InputDisposition`, `RawInput`, `MANIFEST_EXTERNAL_ID` and any pure helpers they need. `hippo.ingest.accepted_inputs` and `hippo.ingest.provenance` re-export them (so every existing import path keeps working and no test changes its imports for that reason) and keep the capture/read logic that does I/O.
2. `hippo/ingest/__init__.py` stops importing `pipeline` eagerly: keep the public names via a module-level `__getattr__` that imports on first access (PEP 562), so `from hippo.ingest import add_text` still works and `import hippo.ingest` no longer pulls the whole pipeline.
3. Remove `pipeline._managed()` and restore a plain module-level `from . import managed_activation` once the cycle is gone; the import-order test must pass in every order, and add cases for `hippo.knowledge.input_binding`, `hippo.knowledge.generation_profiles` imported FIRST and for `hippo.ingest` imported first.
4. Add a static guard test: no module under `src/hippo/knowledge` contains `from ..ingest` / `from hippo.ingest` / `import hippo.ingest` (grep-based, fails on any occurrence).

FILES:
  - own: NEW `src/hippo/knowledge/inputs.py`, `src/hippo/knowledge/generation_profiles.py`, `src/hippo/knowledge/input_binding.py` (imports only), `src/hippo/ingest/__init__.py`, `src/hippo/ingest/accepted_inputs.py`, `src/hippo/ingest/provenance.py` (moves and re-exports only), `src/hippo/ingest/pipeline.py` (the accessor removal only), `src/hippo/ingest/prose_generation.py` (import lines only), `tests/unit/test_import_order.py`, NEW `tests/unit/test_layering.py`, NEW `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-layering.md`.
  - do NOT touch: any behavior, any other file, `docs/`, the checkpoint, `GATES.md`.

STEPS: baseline `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_import_order.py tests/unit/test_accepted_inputs.py tests/unit/test_input_binding.py tests/unit/test_generation_profiles.py tests/unit/test_prose_generation.py tests/unit/test_managed_pipeline_activation.py tests/unit/test_ingest_pipeline.py -q -o addopts='' -W error` (correct names with `ls`); RED (the new layering test and the new import-order cases fail before the move); implement; GREEN the same set plus `tests/unit/test_managed_prose_preparation.py tests/unit/test_staged_prose_writer.py` on Fake, and `test_prose_generation.py` on Ladybug is NOT required (no behavior change; say so); Ruff; a fresh-interpreter check of `hippo --help`'s import footprint still excluding `hippo.ingest.pipeline`; evidence; commit in one or two commits.

DONE WHEN: green; the accessor is gone; the layering guard passes; evidence written; commits; `horch done` lists the moved names, files, counts and logs.

REPORT: `horch note` per step; `horch tell orchestrator "[<role>] BLOCKED: ..."` for any behavior change that seems required.
