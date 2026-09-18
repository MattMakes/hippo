# Gates: Task 5 plain prose chunk provenance

OWNS: src/hippo/ingest/chunker.py, src/hippo/ingest/prepared_chunks.py, tests/unit/test_managed_chunk_provenance.py

Scope: share the existing prose boundary decisions with an immutable mapped-text adapter. Plain reader inputs only; code, history, rich extraction and pre-generated input mappings remain unsupported. No persistence or production dispatch.

- [x] PC1: Legacy chunk text, titles, ordinals, extraction gating and code behavior remain identical; the real Acme sample retains eight chunks.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_managed_chunk_provenance.py tests/unit/test_ingest_chunker.py tests/unit/test_managed_reader_provenance.py tests/unit/test_ingest_readers.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=...........................................                              [100%] | 187 passed in 0.43s
- [x] PC2: Repeated equal text, overlap, hard cuts, Unicode/CRLF and headings retain exact ordered ranges; generated separators and title dependencies close over honest complete original lines.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_managed_chunk_provenance.py tests/unit/test_ingest_chunker.py tests/unit/test_managed_reader_provenance.py tests/unit/test_ingest_readers.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=...........................................                              [100%] | 187 passed in 0.42s
- [x] PC3: Prepared values have immutable nested types, deterministic rendition/range identity and fresh legacy adapters; unsupported input mappings reject explicitly.
  CHECK: .venv/bin/ruff check src/hippo/ingest/chunker.py src/hippo/ingest/prepared_chunks.py tests/unit/test_managed_chunk_provenance.py
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed!

RED: `/tmp/hippo-prose-chunk-red.log` (missing API), `/tmp/hippo-prose-chunk-mapping-red.log` (6 failures: equal titles at distinct ranges and irrelevant blank-line anchors), `/tmp/hippo-prose-chunk-contract-red.log` (3 failures: stale rendition identity, omitted evidence closure and non-plain original remapping). Implementations followed each failing check. Independent review requested.

API: `prepare_prose_chunks(documents, *, size_chars, overlap_chars) -> tuple[PreparedChunk, ...]`. PreparedChunk retains frozen legacy values, ordered retrieval/extraction segments, exact per-segment and title input ranges, their ordered deduplicated union, and a validated complete-line closure. Plain prose has `defines=()`, `extract_text=None`, extraction segments equal retrieval segments and self support. `chunk_key` is computed from the rendition, effective chunker profile, ordinal and exact per-segment/title references; changing a value reconstructs its identity. `to_chunk()` returns a fresh legacy adapter.

Materialization consumes `PreparedChunk.originals`: each `PreparedOriginal(unit_key, lines)` carries the exact OriginalLines text/locator and internal character bounds. The full `original_units` remain mapping context and must not be substituted for this minimal closure. `requires_view` is true for generated separators, changed text or multiple original dependencies. Code, history, rich readers and existing transformed input mappings fail explicitly in this new API. Existing legacy callers retain their current dispatch.

No complete Task 5 chunk/parser or storage-binding parity is claimed by this bounded prose slice.

Independent adaptive review: SPEC PASS / QUALITY PASS. The reviewer ran all 187 focused cases with warnings treated as errors, Ruff and formatting, plus 2,000 seeded comparisons against the committed legacy chunker covering headings, repeated text, Unicode, Python splitlines whitespace, sizes and overlap. No findings.
