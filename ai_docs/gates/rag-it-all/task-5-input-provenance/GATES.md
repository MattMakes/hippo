# Gates: Task 5 plain input provenance

OWNS: src/hippo/ingest/provenance.py, tests/unit/test_managed_reader_provenance.py

Scope: immutable raw input and reader mapping values; plain UTF-8 text/code only. No capture coordinator, chunking, rich extraction, production dispatch, model calls or persistence changes.

- [x] IP2a: Plain reader output exactly matches legacy reading, including trim, BOM, code classification, budgets, empty/binary outcomes and decoding errors.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_managed_reader_provenance.py tests/unit/test_ingest_readers.py tests/unit/test_ingest_limits.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.........                                                                [100%] | 81 passed in 0.98s
- [x] IP2b: Unicode parser byte ranges map to the right original characters and retained raw bytes; repeated text, CRLF and malformed UTF-8 preserve honest complete-line locators and decoder precision.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_managed_reader_provenance.py tests/unit/test_ingest_readers.py tests/unit/test_ingest_limits.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.........                                                                [100%] | 81 passed in 0.93s
- [x] IP2c: Frozen DTOs reject invalid mapping ranges/dependencies, raw identity mismatch and unsupported rich formats; legacy adapters cannot mutate provenance.
  CHECK: .venv/bin/ruff check src/hippo/ingest/provenance.py tests/unit/test_managed_reader_provenance.py
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed!

RED: `/tmp/hippo-input-provenance-red.log` (missing reader assertion), `/tmp/hippo-input-provenance-validation-red.log` (2 failures: mutable metadata and incorrect raw precision accepted), `/tmp/hippo-input-provenance-slice-red.log` (mutable original-slice text accepted). Each corresponding implementation followed its failing check.

Independent storage-agent review found nested duck-typed mutable values could enter frozen DTOs. RED: `/tmp/hippo-input-provenance-nested-red.log` (5 failed, 2 passed). The boundary now checks exact immutable locator/range/line/unit/document/segment types, including empty outcomes. GREEN: `/tmp/hippo-input-provenance-nested-green.log` (81 passed, including 42 provenance cases). The existing gate evidence above predates these seven review regressions.

Final independent SPEC PASS / QUALITY PASS: both mutable mapping/locator reproducers now reject, containing DTOs checked, 72 provenance and legacy reader tests passed with warnings treated as errors; Ruff and format clean. The reviewer also checked 20,000 random byte tails against the actual UTF-8 decoder without a mapping mismatch. No database was used for these provenance cases.

API: `read_plain_provenance(raw_input, data, *, name=None, path=None, budget=None) -> ProvenanceRead`. The result carries frozen documents, original units and an explicit text/empty/binary outcome. `RawInput.raw_artifact` adapts to the separately owned immutable raw store. `ProvenanceDocument.to_document()` returns a fresh legacy value; `original_segments_for_bytes(start, end)` translates UTF-8 parser boundaries, retaining generated segments as generated. `OriginalUnit.complete_lines(start, end)` expands internal character slices to actual complete original lines.

Physical lines use CRLF/LF/CR terminators and omit a synthetic empty trailing line. UTF-8-sig decoding records a consumed leading BOM separately; replacement characters have explicit non-exact raw ranges. Original-unit identity includes raw identity and decoder profile, never display titles or temporary paths. The legacy budget counts analysis characters; a separate MAX_TEXT_CHARS ceiling bounds untrimmed provenance allocations, including whitespace-only inputs. Raw capture remains responsible for its configured byte cap and accepted-source aggregate budget.

IP2 is only partially implemented by this slice. Rich-format and archive provenance, accepted source capture, chunk/parser preparation and storage binding remain separate gates in the parent plan.
