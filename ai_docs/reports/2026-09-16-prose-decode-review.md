# Independent review: exact-content prose decoding

Date: 2026-09-16
Reviewer: `codex-sol-3`
Scope: uncommitted Task 1 changes at base `1ff6a37`
Verdict: **PASS for specification and code quality; G3 remains pending and is not part of this verdict.**

I reviewed the plan before the implementation and did not read the implementer's report. I also did not run tests, benchmarks, or model calls while the concurrent timing experiment was running. The G1 and G2 results below are the independently supplied gate evidence, not results produced by this review.

## Requirement-by-requirement verdict

| # | Task 1 requirement | File:line evidence | Extras / observations | Verdict |
|---:|---|---|---|---|
| 1 | Keep every database read intact. | `src/hippo/store/knowledge.py:453-513`, `515-536`, `583-602` | Both whole/scoped reads and ID reads execute `run(...)` before decoding. `_knowledge_get` still delegates to `_knowledge_rows`; the cache is below the storage read. The persisted-row regression counts two physical reads and then verifies corruption and deletion (`tests/unit/test_prose_decode_cache.py:165-185`). | PASS |
| 2 | Cache only `ProseExtraction`. | `src/hippo/store/knowledge.py:542-545` | The exact-type guard is `model is k.ProseExtraction`; all other models take the original validation path. Explicitly covered at `tests/unit/test_prose_decode_cache.py:135-142`. | PASS |
| 3 | Key reuse on the complete freshly fetched raw row, with no ID-, hash-, or epoch-only reuse. | `src/hippo/store/knowledge.py:34-58`, `542-555` | `canonical_json(row)` includes every raw mapping entry and value. No identity, payload-hash, or authorization-epoch shortcut exists. Changed ID, payload hash, identity input, payload bytes, support list, and raw type all miss/reject (`tests/unit/test_prose_decode_cache.py:62-79`). | PASS |
| 4 | Do not normalize malformed distinctions before validation. | `src/hippo/store/knowledge.py:34-58` | Only exact `str`, `int`, `None`, and `list[str]` raw values are keyable. Unsupported tuples, booleans, custom/native objects, timestamps, and other types bypass caching rather than being coerced. Payload strings remain strings in the outer key, so distinct raw JSON spellings remain distinct. The tuple and boolean paths are covered at `tests/unit/test_prose_decode_cache.py:62-79`, `127-132`. | PASS |
| 5 | Changed rows miss; corrupt rows still reject; exceptions are not cached. | `src/hippo/store/knowledge.py:554-566`, `569-581` | Decode completes before assignment to the cache. Any JSON/model/hash/identity failure leaves no entry. Same-ID corruption is covered both directly and through a physical read (`tests/unit/test_prose_decode_cache.py:62-79`, `181-183`). | PASS |
| 6 | Missing rows cannot be resurrected. | `src/hippo/store/knowledge.py:508-513`, `531-536`, `583-602` | No decoder/cache lookup occurs when the database returns no row. Physical deletion followed by `_knowledge_get(...) is None` is covered at `tests/unit/test_prose_decode_cache.py:184-185`. | PASS |
| 7 | Scope retention to one store instance. | `src/hippo/store/knowledge.py:549-553` | Cache and byte counter are instance attributes, lazily created under the store lock. Cross-store object non-sharing is covered at `tests/unit/test_prose_decode_cache.py:145-155`. | PASS |
| 8 | Cap the cache at 32 entries. | `src/hippo/store/knowledge.py:29`, `559-564` | LRU eviction is exercised by 33 distinct rows at `tests/unit/test_prose_decode_cache.py:93-97`. | PASS |
| 9 | Cache only rows whose complete serialized key is at most 1 MiB. | `src/hippo/store/knowledge.py:30`, `42-58` | The final bound uses UTF-8 bytes of the complete canonical raw row. Oversize ASCII and multibyte inputs are covered at `tests/unit/test_prose_decode_cache.py:100-109`. | PASS |
| 10 | Cap aggregate serialized keys at 8 MiB, without claiming that as total RAM. | `src/hippo/store/knowledge.py:31`, `556-564` | Accounting adds/removes exact UTF-8 key bytes; the comment correctly limits the claim to serialized keys. Budget-driven eviction before the entry cap is covered at `tests/unit/test_prose_decode_cache.py:112-124`. | PASS |
| 11 | Oversized or unsupported rows use the existing validation/conversion path. | `src/hippo/store/knowledge.py:542-545`, `569-581` | Both cases call `_decode_knowledge_record`; valid oversized rows remain valid but uncached, and a raw tuple is validated without reuse (`tests/unit/test_prose_decode_cache.py:100-109`, `127-132`). | PASS |
| 12 | Preserve temporal and JSON conversion semantics. | `src/hippo/store/knowledge.py:569-581` | The original conversion order and rules remain: timestamps become ISO text, native temporal values use `to_native().isoformat()`, declared JSON columns use `json.loads`, then the full model validates from canonical JSON. The only intended change is conversion into a shallow copy instead of mutating the caller's row. | PASS |
| 13 | Do not mutate incoming row dictionaries. | `src/hippo/store/knowledge.py:571-580` | Conversion writes only to `decoded = dict(row)`. Covered at `tests/unit/test_prose_decode_cache.py:55-59`. | PASS |
| 14 | Reuse only a deeply immutable model graph. | `src/hippo/knowledge/contract.py:45-48`, `src/hippo/knowledge/model.py:1066-1085`, `1115-1125` | `Contract` is frozen and strict; entity/triple collections and vectors are tuples of frozen contracts. Top-level, nested-model, and vector mutations are rejected at `tests/unit/test_prose_decode_cache.py:82-90`. | PASS |
| 15 | Make lazy initialization and concurrent access safe on all backends. | `src/hippo/store/knowledge.py:549-566`, `src/hippo/store/base.py:188-210`, `src/hippo/store/ladybug.py:333-385`, `tests/fakes/fake_store.py:66-71` | Neo4j, Ladybug, and Fake stores all provide an `RLock`. Creation, miss decoding, insertion, eviction, and hits occur under it. Concurrent callers share one result (`tests/unit/test_prose_decode_cache.py:158-162`). Reentrancy also preserves calls made inside store transactions. | PASS |
| 16 | Preserve current authorization decisions and expose no new untrusted bypass. | `src/hippo/store/knowledge.py:1027-1057`, `src/hippo/knowledge/access.py:95-130`, `299-356`, `409-448` | Public reads still build and revalidate authorization proofs. Membership, policy, suppression, and epoch records are not cache-eligible. Proof-local read reuse still invokes store reads for its inventory; only immutable parsing of an identical current prose row is reused. `ProseExtraction` is not added to the public `_record_visible` allow-list. Existing lifetime tests explicitly cover membership removal/disablement, revocation during inventory, expiry, and final-boundary revalidation (`tests/unit/test_evidence_access.py:203-220`, `544-568`, `624-681`). | PASS |
| 17 | No dependency, model, schema, service, authorization, or configuration changes. | `git diff` scope: `src/hippo/store/knowledge.py`; new `tests/unit/test_prose_decode_cache.py` | Production changes are confined to the decoder/cache in the owned source file. | PASS |
| 18 | G1 and G2 semantic regression gates pass. | `ai_docs/gates/prose-decode/GATES.md:5-14` | Supplied evidence records G1: 19 passed and G2: 101 passed. This reviewer did not rerun them during timing. | PASS |
| 19 | G3 fresh-copy Q3 improves time with identical answer/evidence. | `ai_docs/gates/prose-decode/GATES.md:16-18` | Separately owned measured gate. It remains pending and therefore is not converted into a Task 1 spec failure by this review. Overall integration/performance acceptance must wait for the orchestrator's result. | PENDING |

## Collision, lifetime, and boundary analysis

No reachable raw-row key collision was found among eligible values. Canonical object-key ordering only removes dictionary insertion-order differences, which are not column values. String contents, including distinct serialized payload spellings, remain embedded verbatim as outer JSON string values; list order and every column value remain significant. Exact type checks prevent Python equivalences such as `True == 1`, tuple/list coercion, or driver/custom-object serialization from hitting an existing entry. Unsupported shapes bypass the cache and retain validation behavior.

Current-read preservation is structural rather than inferred from an epoch: `_knowledge_rows` and `_knowledge_by_ids` obtain a complete current row first, and only then call `_knowledge_records`. A missing row never presents a key. A changed row presents a different complete key and is decoded again. The authorization proof separately rereads and validates live identities, memberships, policies, suppressions, generation membership, and the authorization boundary; none of those mutable decisions is cached here. Returning the same frozen prose object for identical freshly read bytes grants no new authority.

Memory is bounded by both 32 entries and 8 MiB of serialized keys, with a 1 MiB admission limit per row. Parsed Python objects consume additional memory, as the implementation accurately states; their retained population is nevertheless bounded by the same entry/admission policy. Cache ownership ends with its store instance.

## Independent code-quality assessment

**No findings.**

The implementation is small, explicit, and localized to the existing decode boundary. The helper names and comments explain the security/performance invariants without overstating the memory bound. The copied-row conversion avoids an incidental input mutation while retaining validation order. Locking is conservative but correct for the bounded cache and prevents duplicate concurrent decoding. The focused tests cover the meaningful regression scenarios: complete-key changes and malformed values, exception behavior through repeated validation, deep immutability, per-store scope, concurrency, both memory bounds, UTF-8 sizing, unsupported inputs, current physical reads, corruption, and deletion. I found no concrete correctness, coupling, readability, authorization, or reachable behavioral regression that warrants a change.

## Gate status and final recommendation

- G1: PASS (supplied evidence: 19 tests passed).
- G2: PASS (supplied evidence: 101 tests passed).
- G3: PENDING with the orchestrator/timing worker.
- Static whitespace check: `git diff --check` passed during this review.

Recommendation: accept the Task 1 implementation on specification and code quality, subject to the orchestrator's independent G3 performance and answer/evidence-equivalence decision.
