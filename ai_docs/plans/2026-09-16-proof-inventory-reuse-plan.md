# Reuse trusted raw reads inside one evidence proof

Goal: reduce the 726 SQL operations and 1,915 ordinary record decodes in a warm proof, keeping every live proof boundary and every membership, dependency, version and audience check.
Base measured revision: `4c22322`. Q3 takes 120.311612s and builds 304 proofs. A warm proof takes about 0.43s; SQL preparation/execution and ordinary-record decoding dominate after prose caching.
Gates: `ai_docs/gates/proof-inventory-reuse/GATES.md`.

## Design decision

`EvidenceAccess.build` already owns `_ProofReads`, a cache of raw trusted storage rows scoped to that single proof. `_authorized_derivations` then constructs separate per-generation `_Inventory` objects that fetch the same typed records again. Supply the existing raw proof reader to these inventories. The reader must never be an audience-filtered map such as authorized spans, revisions or bindings. Standalone derivation validators retain their existing fresh store path.

Implement private optional `_proof_reads` plumbing through `GenerationViews` and `_Inventory` (or equivalently named private keyword). It must belong to the identical store instance. Within an injected inventory:

- Generation membership and revision membership use `_ProofReads.scoped` for that exact generation; no broadening or removal of exact-member checks.
- `record(kind, identity)` checks exact membership on every call as today, then obtains uncached inventory records through raw `_ProofReads.by_id`, which returns only current-proof typed records or absence. Native/Passage dictionary reads remain direct store reads in this slice.
- Dependency enumeration must still query **all** rows whose `derived_record_id` names the target, including any nonmembers. Use `_ProofReads.scoped` on that field, never the selected `interpretation("DerivedDependency")` subset. Its per-proof scope memoization avoids repeated enumeration. An out-of-membership dependency must still cause refusal.
- Preserve generation/source availability checks and all error/fingerprint/version logic. Do not prefilter lineage by audience. Every later `EvidenceAccess.build` creates a new raw reader and new inventories.
- The inventory's own record memoization remains valid for standalone callers. No cross-proof cache of grants or lineage closures, no epoch-only shortcuts, no broad generic caching framework. Avoid changing `_ProofReads` existing semantics merely to save a few extra reads.

Alternatives considered: caching prepared statements targets about 0.09s/proof but involves connection lifecycle and schema invalidation; collapsing nested model guards primarily helps some legacy paths and is smaller on the current verified dense path. Sharing records already loaded by the same proof directly targets redundant work while preserving boundaries. Further native-read or closure caching is outside this experiment.

## Task 0: environment and preservation

Root environment `.venv/bin/python`, explicit fake and Ladybug tests. No schema/config/credential/model changes. Existing local-model replay uses copied baseline data only. The compact-selector worker owns retriever.py and a different test file; both implementations may run tests now, but all tests finish before timing.

## Task 1: raw proof reader injection

- [x] complete
Gates: G1, G2, G3
OWNS: src/hippo/knowledge/access.py, src/hippo/knowledge/derivations.py, tests/unit/test_proof_inventory_reuse.py, tests/unit/test_derivation_read_reuse.py

1. Inspect the raw-reader lifetime, full dependency enumeration and immutable record contracts. Enumerate all requirements above. Use existing `world()` fixtures from derived-evidence tests.
2. Add meaningful RED tests: a proof no longer separately `_knowledge_get`s a representative record already in its raw `_ProofReads`; repeated shared derived parents do not repeat the same full dependency query; exact membership still rejects after a non-exact read; an extra persisted nonmember dependency is detected; private secondary inputs cannot become authorized; corruption/revocation between separate proofs is observed; a reader belonging to another store is rejected; standalone validators keep their fresh behavior. Prefer extending existing cases to duplication, but do not weaken corruption or authority assertions. Record exact assertion failures before code.
3. Implement only the private plumbing described. Preserve all public signatures, response fields and validators. If an existing one-read test becomes zero-read through raw reuse, update only that count assertion and explain it; new tests must positively establish the intended zero duplicate lookup. Do not relax assertions to a broad range.
4. Run new tests plus the existing derivation/access/scoped/snapshot suites listed in G2 on Ladybug and fake. Ruff, compileall and diff checks must pass. Report exact logs and any exclusions; no Neo4j or full-suite run here.
5. Orchestrator independently reviews and measures a before/after cold+warm proof against copied identical corpus, comparing complete AuthorizedEvidence values. It then measures final end-to-end queries. No worker commit until measured acceptance; rollback this patch if it fails quality or yields no meaningful performance improvement.

## Acceptance boundaries

No storage row is reused across independent proof builds. Complete exact lineage validates before audience filtering, including nonmember dependencies. Each requested record still fails if absent, incompatible, corrupt or outside its required membership. Store identity guards protect injected-reader ownership. Direct native record validation, model-call checks, heartbeat, revocation/expiry and release-time revalidation stay unchanged. The overall goal still requires twelve complete grounded answers and supplemental/regression coverage.
