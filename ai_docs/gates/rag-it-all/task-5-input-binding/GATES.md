# Gates: Task 5 pure plain input binding

OWNS: src/hippo/knowledge/input_binding.py, tests/unit/test_managed_input_binding.py

Scope: pure typed materialization of already verified plain local-file preparation. No raw I/O, vectors, model calls, writes or production dispatch. Raw byte authenticity remains the accepted reader boundary; binding checks verify its immutable metadata and identities.

- [x] IB1: Exact complete-line originals and all-input rendered lineage materialize deterministically with generation/view-aware native identities and extraction bindings.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_managed_input_binding.py tests/unit/test_managed_chunk_provenance.py tests/unit/test_derived_generation_store.py tests/unit/test_derived_projection.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=...................................................................      [100%] | 139 passed in 3.78s
- [x] IB2: Strict storage seals and projects emitted originals/views; hidden secondary originals deny the whole derived output.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_managed_input_binding.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=..................................                                       [100%] | 34 passed in 2.07s
- [x] IB3: Conflicting inventories, foreign scope/path/provider/hash/URI bindings and mutable nested values reject; no prepared revision metadata is changed.
  CHECK: .venv/bin/ruff check src/hippo/knowledge/input_binding.py tests/unit/test_managed_input_binding.py
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed!

RED: `/tmp/hippo-input-binding-red.log` (missing API), `/tmp/hippo-input-binding-closure-red.log` (omitted title proof and incomplete dependency group accepted; a suppression fixture was also corrected), `/tmp/hippo-input-binding-output-red.log` (4 failures from root review: missing/duplicate revision membership, duplicate passage inventory and non-staging binding). Corrections followed the failing checks. Final output validation also checks consistent generation records, one plain unit per passage, and span/view membership through ID maps rather than repeated tuple scans.

API: `local_input_key(*, workspace_id, source_id, logical_path)` supplies the canonical source-scoped key used before plain reading. `AcceptedArtifactBinding(raw_input, artifact, revision)` requires exact frozen types, matching raw hash/URI/provider revision and the canonical local file path/scope. `materialize_chunk_evidence(prepared, generation, *, workspace_id, bindings)` returns PreparedEvidence with typed span/view/derivation/dependency/member tuples plus passage and extraction bindings. No mutable native dictionary is retained. `BoundPassage.native_row()` returns fresh metadata without embedding; `to_chunk()` returns a fresh legacy Chunk.

ExtractionInput carries typed input kind/ID/version/text hash, exact text, the complete original span inventory and explicit support passage IDs. It represents preparation for the existing plain `extract_text=None` gate; it is not a successful inferred model output. The native row and view profile commit the chosen generation, complete source originals and prepared rendition/range/profile identity. Reader profiles remain in view configuration, never newly added to an existing raw revision's metadata. Empty accepted files produce revision membership without fabricated spans or passages.

Remote artifacts, archives, rich formats, code/history, inferred model output and coordinator coverage/publication remain separate tasks.
