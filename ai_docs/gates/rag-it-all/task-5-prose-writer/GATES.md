# Managed plain-prose preparation and staged writer gates

Status: implementation and focused verification complete; independent SPEC PASS / QUALITY PASS. Production runtime/coordinator activation remains outside this slice.

Scope: new preparation and writer modules only. Legacy dispatch, model identity resolution, lease coordinator, code/rich/history preparation and publication remain separate.

- [x] PW1: Immutable accepted inputs reconstruct generation identity and bind exact profiles/configuration.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_prose_preparation.py -q -o addopts='' -W error
  CRITERIA: changed configuration/revisions/workspace/profile/dimension, mutable nested DTOs and duplicate/conflicting inventories reject; canonical valid inputs pass.
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=................................                                         [100%] | 32 passed in 0.09s
- [x] PW2: Shared OpenIE behavior and exact mandatory coverage survive preparation.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_prose_preparation.py tests/unit/test_prepared_index.py tests/unit/test_openie.py -q -o addopts='' -W error
  CRITERIA: actual NER/triple prompts, cleanup, entity endpoints and fact embedding text match legacy; short plain prose runs; successful empty output differs from skip/failure; empty predicate fails; omission/duplicates/profile drift/cancellation reject without prepared success.
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.............................................................            [100%] | 61 passed in 0.11s
- [x] PW3: Scoped model calls stay outside transactions and persist no authority.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_prose_preparation.py -q -o addopts='' -W error
  CRITERIA: exact document-kind embedding inputs and dimensions, guarded chat dispatch/results, latched cancellation of subsequent calls and no store/model handles in prepared DTOs; global existing-ID methods are never consulted.
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=................................                                         [100%] | 32 passed in 0.08s
- [x] PW4: Fenced batches and exact pre-seal reconciliation preserve last good generation.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_staged_prose_writer.py tests/unit/test_managed_input_binding.py tests/unit/test_derived_generation_store.py -q -o addopts='' -W error
  CRITERIA: missing/extra/conflicting revisions, members, passages or prose reject; complete child groups, explicit empty code and successful empty inference seal; lost fence/lease/source denial/partial failure prevent sealing; G1 and global legacy state remain unchanged.
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=..............                                                           [100%] | 86 passed in 5.74s
- [x] PW5: Real persistence and authorized retrieval consume the same originals and source-local inferred facts.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_staged_prose_writer.py -q -o addopts='' -W error
  CRITERIA: strict original/view fixtures seal and reopen; explicit test publication projects original citations, inferred fact support and cosine synonyms; staging dimensions and denied secondary originals never leak. Neo4j repeats require a root reservation.
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=...................                                                      [100%] | 19 passed in 23.08s
- [x] PW6: Formatting, regression and independent review pass.
  CHECK: .venv/bin/ruff check src/hippo/knowledge/prose_preparation.py src/hippo/knowledge/staged_prose.py tests/unit/test_managed_prose_preparation.py tests/unit/test_staged_prose_writer.py && .venv/bin/ruff format --check src/hippo/knowledge/prose_preparation.py src/hippo/knowledge/staged_prose.py tests/unit/test_managed_prose_preparation.py tests/unit/test_staged_prose_writer.py ai_docs/plans/rag-it-all-task-5-prose-writer.md
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 5 files already formatted
  CRITERIA: no findings; formatter also checks these files and ai_docs/plans/rag-it-all-task-5-prose-writer.md; independent SPEC/QUALITY review passes.
  EXPECT: 5 files already formatted

Review notes: adaptive identified one concrete guard race; fixed RED→GREEN with two event-controlled tests and narrow independent rereview. Final independent broad review: SPEC PASS / QUALITY PASS, no remaining findings. No Neo4j run, production dispatch, publication or data cleanup was performed by this agent.
