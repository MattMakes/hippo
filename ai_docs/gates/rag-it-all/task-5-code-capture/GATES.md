# Task 5 managed code capture gates

**Status:** proposed; no implementation evidence has been recorded.

**Scope:** managed generations for repositories, archives and single code files, including the code
graph, git history and the plain-prose files inside a captured tree. Contract:
`ai_docs/plans/rag-it-all-task-5-managed-code-capture.md`. LadybugDB is the acceptance backend;
Fake is the first backend for every gate. Neo4j parity is root-owned evidence recorded under CD9,
not a separately runnable line, because the disposable container admits one pytest process at a
time (the `task-5-prose-coordinator` PC-N4 convention). Rich documents, connectors, Task 6 blocks,
Task 12 typed bindings and Task 9A purge are outside this ledger. Nothing here activates a
production route on its own; CD8 activates the managed dispatch lane.

Every CHECK line runs from `/Users/mascott/projects/hippo`. Test files named below do not exist
yet. Runnable checkboxes are set by the orchestrator's gate checker, never by an implementer.

- [ ] CD1: Generation-scoped store reads keep every existing result byte-identical and bound the work per write.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_generation_scoped_reads.py tests/unit/test_generation_store.py tests/unit/test_generation_counts.py tests/unit/test_staged_prose_writer.py -q -o addopts='' -W error
  CRITERIA: parameterised `_native_rows`, `_native_relationships` and `_knowledge_rows` return exactly what the unscoped forms returned for the same selection; `native_write`, `native_mutation` and `generation_checksums` use them; a recorded query counter proves per-batch work is bounded by the batch rather than by corpus size; every existing representation checksum, seal and publication result is unchanged; the reviewed prose writer and counts suites stay green. (Amended 2026-09-12 by the design review: native_write and native_mutation scope by ids and native_mutation still raises 'Native relationship crosses generations' for an edge across two generations and still admits an edge to an untagged legacy row; the scoped read is index-backed on the backends that support one, evidenced by the schema statement and not only by the query counter; sealing a generation at the symbol ceiling is linear in the generation in CPU as well as in queries; the scoped edge enumeration still returns every edge with exactly one endpoint in the selection so the 'Native relationship crosses generations' and 'Missing shared graph endpoint' refusals survive, and the two-hop MENTIONS/STATES -> SUBJECT/OBJECT closure is computed by a second scoped pass, never a whole-table read.)
  EXPECT: passed

- [ ] CD2: A converting source serves its legacy graph until its first publication.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_converting_source_serving.py tests/unit/test_managed_source_inventory.py tests/unit/test_status_access.py tests/unit/test_structural_loading.py -q -o addopts='' -W error
  CRITERIA: `source_serves_legacy` is true for a source holding only staging Artifact/Generation rows and false once a generation is published or an all-principals suppression targets the source, independent of the managed flag, which flips at staging start (ruling 9); such a source keeps its complete legacy passages, code nodes and edges in every query and appears exactly once in source inventory with its legacy counts; with the converting source as the only managed source on the instance, no staged passage, symbol, data object or commit appears in any query result; publication flips lane, active pointer, counts and presentation in one transaction; an authorized empty published generation still appears with zero counts; a denied or tombstoned source appears in neither lane; only UNTAGGED rows ever serve the legacy lane, and a source holding a Generation row is presented in the legacy lane only while it owns at least one untagged passage, symbol, data object or commit, so a bootstrap-only managed source is absent from every graph surface, dropdown, eval label and count until publication (ruling 14, `evidence-cc1fix.md`); the store-level `delete_source`, `delete_passages_for_source` and `delete_code_nodes_for_source` refuse mid-conversion and the source can still be tombstoned (the pipeline-level `_prepare_reindex` and `shutil.rmtree` refusals are added to this line when CC10 lands).
  EXPECT: passed

- [ ] CD3: Repository, archive and single-file capture is bounded, canonical and order-independent.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_repo_capture.py tests/unit/test_code_provenance.py tests/unit/test_accepted_inputs.py -q -o addopts='' -W error
  CRITERIA: the tree inventory is normalized, sorted and identical under a reordered walk; ignored directories, oversized files, unsupported names and explicit exclusions each carry a distinct recorded reason; symlinks, non-regular files, escaping paths and files changed during capture are refused rather than skipped; code and config decode with exact complete-line locators, Unicode byte mappings and the legacy trim behaviour; rich, archive-inside-archive and binary outcomes refuse in this seam; the accepted manifest excludes itself and contains no absolute path; every later read is from the captured raw object.
  EXPECT: passed

- [ ] CD4: Mapped code chunks reproduce the legacy chunker exactly and carry exact original closures.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_prepared_code_chunks.py tests/unit/test_ingest_chunker.py -q -o addopts='' -W error
  CRITERIA: for seeded trees the prepared chunk text, order and `defines` equal the committed `chunk_documents(..., code=code)` output; every chunk maps to exact original line ranges plus explicitly marked generated segments for the context header, data-object mention passages and commit passages; oversized bodies split at statement boundaries as today; a chunk whose text is byte-identical to one original region carries no generated segment; remapped, rich and already-derived inputs reject.
  EXPECT: passed

- [ ] CD5: Code evidence binding is pure and its exact membership closes.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_code_binding.py tests/unit/test_managed_input_binding.py -q -o addopts='' -W error
  CRITERIA: spans, rendered views, derived records and dependencies, knowledge objects, observations, native rows, bindings, revision members and evidence members form one closed inventory with no duplicate and no orphan *binding* — a `repository` or `file` knowledge object legitimately has observations and no native row, and must not be treated as an orphan; native IDs equal `symbol_id`/`data_id`/`commit_id` under the generation namespace; `symbol_key` carries the signature discriminator so overloads do not merge; a shared canonical symbol observed by two sources keeps distinct per-source observations; no `Assertion`, `AssertionVersion`, `AssertionSupport` or `SYNONYM` row is produced; the materialiser holds no store handle, model client or clock.
  EXPECT: passed

- [ ] CD6: Git history becomes artifacts and revisions with honest temporal fields.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_code_history.py tests/unit/test_git_history.py -q -o addopts='' -W error
  CRITERIA: one `history_event` artifact and revision per commit carrying the author date in `source_updated_at`, the raw `%aI` text in `source_timestamp_original`, its offset in `source_timezone` and `source_precision="second"`; commit observations use `valid_from` = author date, `validity_kind="explicit_interval"`, `temporal_basis="commit"`, `recorded_from` = the one injected capture instant, `recorded_to` null; no record calls a wall clock and no default instant appears anywhere; `MODIFIES` hunks and `PRECEDES` pairs bind only to symbols of the same generation; `skipped`, `truncated`, the shallow boundary, renames and disabled history are recorded in coverage and never presented as a complete history.
  EXPECT: passed

- [ ] CD7: The staged code writer is fenced, exact, sealable and resumable.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_staged_code_writer.py tests/unit/test_generation_resume.py tests/unit/test_generation_failure.py -q -o addopts='' -W error
  CRITERIA: batches are complete dependency groups, so no batch leaves a dangling endpoint or an unbound native row; every batch revalidates lease, fence, authorization and suppression inside its own short transaction; no callback, model call or filesystem access occurs inside a transaction; missing, extra or conflicting rows refuse the seal; the seal writes an `IndexManifest` with the evidence, dense and native representations and matching checksums; `reclaim_generation_build` resumes a never-published attempt with an equal `manifest_hash` without collecting, a different manifest still collects, a published generation never reopens, and identical replay is idempotent while a conflicting persisted payload fails closed; a lost fence or expired lease prevents every write and the seal.
  EXPECT: passed

- [ ] CD8: The coordinator and activation dispatch convert and refresh without touching legacy cleanup.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_code_generation.py tests/unit/test_managed_code_activation.py tests/unit/test_ingest_pipeline.py tests/unit/test_ingest_concurrency.py tests/unit/test_managed_pipeline_activation.py tests/unit/test_prose_generation.py -q -o addopts='' -W error
  CRITERIA: an authenticated actor converts an eligible `repo`, `archive` or code `file` and the legacy graph serves unchanged until publication; refresh keeps G1 selected through capture, extraction, every write batch and the seal, and after failure or cancellation; a crashed build resumes the same generation and reports the skipped batch count; `already_current` returns without inference; the head SHA, walker rules version and per-grammar parser profile participate in generation identity while worker count, clone depth and progress do not; `BuildAuthority.rebaseline` accepts an unrelated epoch change and refuses after any capability loss, suppression or sticky failure; open, preview and actorless callers and unsupported source kinds stay legacy; spies on `_clear_passages`, `delete_passages_for_source`, `delete_code_nodes_for_source`, `remove_orphans`, `store.delete_source`, `shutil.rmtree`, generation collection and raw unlink are never called for a managed attempt; the reviewed prose coordinator suite is unchanged by the `_Run` extraction.
  EXPECT: passed

- [ ] CD9: LadybugDB acceptance, reopen and full-corpus behaviour, with recorded Neo4j parity.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_code_generation.py tests/unit/test_staged_code_writer.py tests/unit/test_generation_resume.py tests/unit/test_generation_scoped_reads.py tests/unit/test_converting_source_serving.py tests/unit/test_managed_code_activation.py tests/unit/test_code_history.py tests/unit/test_structural_loading.py tests/unit/test_dense_session.py -q -o addopts='' -W error
  CRITERIA: close and reopen preserves generation pointers, fences, exact membership, native code rows and relations, bindings, manifests, raw references, resumable staging state and coverage; a published code generation projects `StructuralCodeEvidence` with exact `DEFINED_IN` support and original citations with real line locators, and routes through verified dense dispatch; a retired generation stays reconstructable under a live snapshot; a representative multi-hundred-file fixture completes within the ceilings of the plan's §8.3 with the CD1 query bound holding. Root records disposable-Neo4j parity for the same files here as an evidence note, run serially against the reserved container, never as a second concurrent pytest process.
  EXPECT: passed

- [ ] CD10: Lint, formatting and independent review.
  CHECK: .venv/bin/ruff check src/hippo/ingest/repo_capture.py src/hippo/ingest/code_provenance.py src/hippo/ingest/prepared_code_chunks.py src/hippo/ingest/code_generation.py src/hippo/ingest/build_run.py src/hippo/knowledge/code_binding.py src/hippo/knowledge/code_history.py src/hippo/knowledge/staged_code.py && .venv/bin/ruff format --check src/hippo/ingest/repo_capture.py src/hippo/ingest/code_provenance.py src/hippo/ingest/prepared_code_chunks.py src/hippo/ingest/code_generation.py src/hippo/ingest/build_run.py src/hippo/knowledge/code_binding.py src/hippo/knowledge/code_history.py src/hippo/knowledge/staged_code.py ai_docs/plans/rag-it-all-task-5-managed-code-capture.md ai_docs/gates/rag-it-all/task-5-code-capture/GATES.md
  CRITERIA: no lint findings; the formatter also checks the fenced Python in the plan and this ledger, which the CI Ruff job runs; independent SPEC and QUALITY reviews pass with every finding closed and each affected gate rerun afterwards.
  EXPECT: 10 files already formatted
