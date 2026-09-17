# Exact-content prose decoding experiment

> **For Codex:** Use `/dev-execute` to implement this plan task-by-task. The user forbids Claude Code workers.

**Goal:** Reduce repeated vector/payload deserialization without skipping current database reads or authorization validation.
**Architecture:** Bounded per-store cache of deeply immutable ProseExtraction records, keyed by complete freshly fetched raw storage row contents. Changed rows always miss; absent rows cannot be resurrected; malformed rows still reject. Other record kinds/native dictionaries are not cached. No epoch-only or ID-only caching.
**Gates:** ai_docs/gates/prose-decode/GATES.md
**Tech Stack:** Python, pytest, Ladybug, existing Ollama replay.
**Wiring Manifest:** KnowledgeStoreMixin._knowledge_records → exact-content prose decoder; existing _knowledge_rows/_knowledge_get still perform every database read.
**Regression Hotspots:** Same ID with corrupt changed payload/hash/identity; missing row; immutable nested vectors; concurrent reads; cache memory bounds; fresh authorization decisions.

## Evidence/design

After 6a5e1e6, Q3 still takes298.611s with304proof builds. One proof profile attributes1.174/1.476profiled seconds to _knowledge_records,0.866 to model_validate_json,0.593 to ProseExtraction.bind_payload (nested). Record payload/vector parsing repeats although storage bytes are unchanged. A per-store exact-content decoder cache targets this cost without weakening fresh evidence reads. Alternative: share _ProofReads records within one proof (safer smaller win), or deduplicate validation boundaries (larger lifetime risk). Try decoding first, measure and rollback if not useful.

## Task 0: Environment

Previously verified same local copied evaluation database, qwen3:8b,nomic-embed-text,512MiBbuffer. Benchmark script /private/tmp/hippo-speed-round1-FfTJFE/replay.py --output NEW_DIRECTORY --ids Q3. No service/auth changes. Full fake suite14400 is still testing prior loaded code; do not claim it covers this new slice.

## Task 1: Bounded exact-content prose decoding

- [x] complete
Gates: G1, G2, G3
OWNS: src/hippo/store/knowledge.py, tests/unit/test_prose_decode_cache.py

Spec: Keep database reads intact. Only cache ProseExtraction, whose contract and all nested payload objects/vectors are frozen. Cache key must cover ALL raw column values, not identity/hash alone, and avoid normalizing away malformed distinctions before validation. Scope cache to store instance (not global private-data retention), cap entries at32, eligible serialized row size at1MiB, and aggregate serialized keys at8MiB; oversized/unsupported rows use existing validation path. Parsed models consume additional bounded memory;8MiB is not a total RAM claim. Corpus measurements show12payloads totaling4,689,077bytes, largest993,810bytes;256KiB would bypass8/12 and miss the dominant work. Do not cache exceptions. Do not mutate incoming row dictionaries. No dependency/model/config changes. Cache may be lazily initialized; make concurrent access safe with existing lock or equivalent. Never expose a new bypass for untrusted callers.

Files: modify knowledge.py; new test_prose_decode_cache.py. Any needed scope expansion must be discussed first.

Steps:
1. Read implementation and immutable contracts. Write real backend regressions that observe expensive decode called once for identical fresh rows, verify DB reads still occur, changes under same ID fail validation, deletions remain absent, nested data cannot mutate, stores don't share cache, oversized input bypasses cache and cache evicts boundedly. Tests may call private decoder with real persisted row shapes where full stores would obscure decoder-specific behavior.
2. Run new tests and capture semantic RED failures before production changes.
3. Implement minimal bounded exact-content cache. Prefer explicit readable helper over generic caching framework. Existing backend temporal/JSON conversion semantics must remain.
4. Run G1/G2, Ruff, compileall. Parent independently reviews and replays Q3 after concurrent tests finish; do not run model benchmarks or commit before parent approval.

## Preservation analysis / pre-flight

| Category | Existing behavior | Preservation / Task |
|---|---|---|
| Behavioral | DB reads and validation at every proof boundary | Task1 leaves reads/checks; only identical immutable parsed content reused |
| Contract | _knowledge_records yields typed immutable records | Task1 same values/errors; private helper signature may change to instance method |
| Domain | Canonical identity and payload/vector validation | Task1 invalid changed content always misses/rejects |
| Wiring | _knowledge_rows/_knowledge_get call self._knowledge_records | Task1 retains call sites; inspect all callers |
| Credentials | None changed | Task0 same local DB/model |
| Failure | Stale ID-only cache hides corruption; oversized cache retains too much | Task1 content key, bound, corruption/eviction tests |

Pre-flight: source/model contracts inspected; no external API, schema, credentials or package changes. Tests own new decoder oracle. Existing snapshot/auth tests retain corruption guards. Same-source source data never modified. Read/approve ledger commands before execution. Do not mark overall goal complete on this slice alone.
