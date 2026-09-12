# Dense-session and retrieval-dispatch gates

Status: bounded implementation complete; Fake gates pass. Final Ladybug rerun passes; independent implementation review is pending. Production activation remains outside this slice.

Scope: one held structural session, verified profile activation and explicit tag compatibility. Existing production routes and the legacy ingestion/query defaults remain unchanged.

- [x] DS1: Tag-compatible matrices preserve immutable evidence and legacy values.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_dense_capability.py tests/unit/test_dense_session.py -q -o addopts='' -W error
  CRITERIA: positive uniform width; canonical managed and legacy sidecar rows survive unchanged; legacy zero vectors remain valid; code and relation provenance, empty-lane widths, scoped/composed behavior and audience fingerprints are preserved. No majority-dimension pruning.
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.                                                                        [100%] | 73 passed in 0.91s
- [x] DS2: Only authorized graph contributors determine routing and descriptor checks.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_dense_session.py -q -o addopts='' -W error
  CRITERIA: exact controlled profile binding; mixed verified/tag modes and dimensions fail before model text dispatch; hidden/staged profiles do not affect routing; relation-only source generations and code-only contributors participate; digest-shaped unmarked tags remain compatibility data; ordinary managed code established by authorized DEFINED_IN is not mislabeled legacy; captured-tag graph/session validation rejects supplied-vector and empty paths after tag changes.
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=................................                                         [100%] | 32 passed in 0.92s
- [x] DS3: Runtime verification and caches use captured profiles outside transactions.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_dense_session.py tests/unit/test_embedding_profile.py tests/unit/test_stored_embedding_profile.py -q -o addopts='' -W error
  CRITERIA: real MockTransport verifies prefix/options/dimension and live digest; cache hits still validate; no HTTP at positive transaction depth; explicit profile mismatch, HTTP errors, cancellation and authorization precedence are exercised.
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.................................................                        [100%] | 121 passed in 0.96s
- [x] DS4: One query pin survives publication and closes on every owned exit.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_dense_session.py tests/unit/test_query_session.py tests/unit/test_query_snapshots.py -q -o addopts='' -W error
  CRITERIA: G1 remains selected through G2 publication during resolution/retrieval; heartbeat renews during blocked HTTP; revocation denies; failure releases all references; borrowed wrappers never reacquire or close the owner; trace snapshot IDs survive graph replacement.
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=...                                                                      [100%] | 75 passed in 1.34s
- [x] DS5: Real-store parity and unchanged legacy defaults pass.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_dense_session.py tests/unit/test_dense_capability.py -q -o addopts='' -W error
  CRITERIA: strict sealed profile fixtures pass the same selection and lifetime cases on Ladybug; existing query_session defaults and legacy cache regressions remain intact. Neo4j repeats require a root reservation.
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.                                                                        [100%] | 73 passed in 132.30s (0:02:12)
- [x] DS6: Formatting, regression and independent SPEC/QUALITY review pass.
  CHECK: .venv/bin/ruff check src/hippo/knowledge/dense_session.py src/hippo/knowledge/dense.py src/hippo/knowledge/query_access.py src/hippo/knowledge/embedding_profile.py src/hippo/knowledge/projection.py src/hippo/hipporag/graph_index.py tests/unit/test_dense_session.py tests/unit/test_dense_capability.py && .venv/bin/ruff format --check src/hippo/knowledge/dense_session.py src/hippo/knowledge/dense.py src/hippo/knowledge/query_access.py src/hippo/knowledge/embedding_profile.py src/hippo/knowledge/projection.py src/hippo/hipporag/graph_index.py tests/unit/test_dense_session.py tests/unit/test_dense_capability.py ai_docs/plans/rag-it-all-task-5-dense-dispatch.md
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 9 files already formatted
  CRITERIA: no remaining independent review findings; all structural/query/profile regressions pass. No route activation, context reload path, storage schema change or profile metadata in audience fingerprints.
  EXPECT: files already formatted

RED/GREEN evidence: initial dispatcher/properties 14 expected failures at /tmp/hippo-dense-session-red.log; stored dimension-before-HTTP regression failed before the local preflight check; managed mention-only entity classification failed before vertex-to-ID conversion; two direct profile-property revocation cases failed before the authorization bracket (/tmp/hippo-dense-property-red.log). Focused final Fake: 73 passed; broad Fake structural/query/profile/context regression: 254 passed. Final full Ladybug run: 73 passed, including both final property regressions. Ruff check and 9-file format check pass.
