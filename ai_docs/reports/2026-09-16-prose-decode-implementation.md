# Exact-content prose decode implementation evidence

Date: 2026-09-16

Scope: Task 1 from `ai_docs/plans/2026-09-16-prose-decode-plan.md`. This report proves G1 and G2 only. G3 remains an orchestrator-owned model benchmark and is not claimed here.

## Requirements checklist

1. Preserve every storage read and authorization boundary.
   - `_knowledge_rows` and `_knowledge_by_ids` still execute their existing backend reads before calling `_knowledge_records`.
   - `_knowledge_get`, `get_knowledge`, and `list_knowledge` retain their existing storage and authorization flow. The cache is private to record decoding and introduces no caller-visible bypass.
2. Reuse only identical `ProseExtraction` decodes.
   - Cache eligibility is restricted by exact model identity (`model is k.ProseExtraction`).
   - The key is canonical serialization of the complete freshly fetched raw row, including every column name and value, before temporal or JSON normalization.
   - Other record kinds always use the uncached decode path.
3. Preserve malformed-row distinctions and validation.
   - Only exact `str`, `int`, `None`, and lists containing exact strings are cacheable. Booleans, tuples, custom objects, and other unsupported raw values bypass the cache rather than being normalized into a key.
   - Changed IDs, payload hashes, identity fields, payload text, passage IDs, malformed JSON, and strict-type violations all miss and retain their existing validation failures.
   - Decode failures are never inserted because cache assignment occurs only after `_decode_knowledge_record` returns successfully.
4. Preserve row ownership.
   - `_decode_knowledge_record` copies each incoming mapping before temporal/JSON conversion, so backend dictionaries are not mutated.
5. Reuse only deeply immutable values.
   - `ProseExtraction`, `ProseExtractionPayload`, `ProseEntity`, and `ProseTriple` inherit the frozen `Contract` configuration.
   - Collections and normalized embedding vectors are tuples. Tests reject mutation of the record, nested entity, and vector.
6. Keep cache state isolated and concurrent access safe.
   - Cache state is created lazily on the store instance, never globally.
   - Ladybug, Fake, and Neo4j stores each initialize an `RLock`; the existing store lock serializes cache creation, misses, insertions, eviction, and hits.
   - Concurrent tests prove one immutable instance is shared for identical content within one store, while separate stores do not share instances.
7. Enforce all memory bounds.
   - Maximum entries: 32, with least-recently-used eviction.
   - Maximum eligible serialized row key: 1 MiB, measured as UTF-8 bytes after complete serialization.
   - Maximum aggregate serialized keys: 8 MiB, with eviction until both entry and byte bounds hold.
   - Oversized and unsupported rows keep the existing validation path without entering the cache. The aggregate bound covers serialized keys, not decoded-model or Python object memory.
8. Preserve freshness under changed and absent storage.
   - Repeated physical reads still execute, identical fresh rows reuse decoding, a corrupt row under the same ID fails, and deletion returns absent rather than resurrecting a cached value.
9. Keep the change narrow.
   - No dependency, model, schema, configuration, service, or application-data changes were made. No Neo4j, full-suite, or model benchmark run was performed.

## Wiring and lock inspection

- Production callers of `_knowledge_records`: `_knowledge_rows` and `_knowledge_by_ids`, both in `src/hippo/store/knowledge.py`.
- Direct test callers: `tests/unit/test_prose_decode_cache.py` only.
- The signature change from static helper to instance method is wired at both production call sites.
- Store lock owners inspected:
  - Ladybug: `LadybugStore.__init__` creates `threading.RLock()`.
  - Fake: `FakeStore.__init__` creates `threading.RLock()`.
  - Neo4j: `Neo4jBase.__init__` creates `threading.RLock()`.

## Test and quality evidence

All pytest commands used `.venv/bin/python`, explicit stores, `-q -o addopts='' -W error`, and exited 0. Every quality command also exited 0.

| Check | Backend/result | Log |
|---|---|---|
| G1: `tests/unit/test_prose_decode_cache.py` | Ladybug: 19 passed in 3.23s | `/tmp/hippo-perf-decode-g1-ladybug.log` |
| G1: `tests/unit/test_prose_decode_cache.py` | Fake: 18 passed, 1 skipped in 0.28s; the skip is the explicitly physical-backend-only read/deletion test | `/tmp/hippo-perf-decode-g1-fake.log` |
| G2: `test_derivation_read_reuse.py`, `test_derived_evidence_access.py`, `test_derived_generation_store.py`, `test_query_snapshots.py`, `test_evidence_access.py` | Ladybug: 101 passed in 53.52s | `/tmp/hippo-perf-decode-g2-ladybug.log` |
| Same G2 files | Fake: 101 passed in 4.13s | `/tmp/hippo-perf-decode-g2-fake.log` |
| Ruff check on owned Python files | Passed | `/tmp/hippo-perf-decode-ruff-check.log` |
| Ruff format check on owned Python files | 2 files already formatted | `/tmp/hippo-perf-decode-ruff-format.log` |
| `compileall -q` on owned Python files | Passed | `/tmp/hippo-perf-decode-compileall.log` |
| `git diff --check` on owned Python files | Passed | `/tmp/hippo-perf-decode-diff-check.log` |

The recovered test file contains 19 collected cases after parametrization. It covers decode reuse, no input-row mutation, seven changed/malformed row variants, deep immutability, 32-entry eviction, the 1 MiB row limit, UTF-8 byte sizing, aggregate byte eviction, unsupported raw tuples, exclusion of other record kinds, store isolation, concurrent reads, repeated physical reads, corrupt persisted content, and deletion freshness.

No new test was added during this finishing pass because inspection and both explicit backend runs uncovered no missing behavior. The tests predated this session, so this report makes no RED claim for them.

## Files in the task scope

- `src/hippo/store/knowledge.py`: recovered exact-content decoder cache implementation; reviewed and verified without further correction in this session.
- `tests/unit/test_prose_decode_cache.py`: recovered focused regression suite; reviewed and verified without further correction in this session.
- `ai_docs/reports/2026-09-16-prose-decode-implementation.md`: this evidence report, added in this session.

## Remaining gap

G3 is intentionally pending: the orchestrator must run the fresh-copy Q3 replay and compare complete answer/evidence equivalence plus latency. Task 1 must not be marked globally complete until that independent benchmark is accepted.
