# Proof inventory read reuse implementation

Base revision: `4c2232266b378c1f9def55bc16c1fdd8aa218ea3`.

## Requirement checklist

- [x] `EvidenceAccess.build` supplies its one raw `_ProofReads` instance to every per-generation derivation inventory created during that proof.
- [x] The injected reader is private plumbing and is rejected unless its `store` is the identical store object.
- [x] Injected generation evidence membership and generation revision membership use `_ProofReads.scoped` for the exact generation.
- [x] `record(kind, identity)` still checks exact membership on every exact call, including after a cached non-exact read, and then uses raw `_ProofReads.by_id` on a cache miss.
- [x] Dependencies are enumerated from all persisted `DerivedDependency` rows for the derived parent via `_ProofReads.scoped`, not from the audience/manifest-filtered interpretation subset. A persisted nonmember dependency still refuses the proof.
- [x] Generation capability, source availability, failed-generation, version, fingerprint, lineage, and audience checks remain in place.
- [x] Original constructor refusal order is preserved: resolve generation, validate capability, resolve/check source and failed status, then read membership. The injected missing-generation path preserves `Unknown generation`.
- [x] Native `Passage` and native-binding target reads remain direct store reads.
- [x] No raw reader is retained beyond one `EvidenceAccess.build`; each subsequent build creates a fresh reader and observes intervening corruption.
- [x] Standalone `validate_view` and `validate_prose` retain fresh store-backed inventories.
- [x] No public response fields, store decoder, native validation, cache lifetime, schema, configuration, or credentials changed.

## Semantic RED

The test-only patch was run before implementation on both backends:

```text
HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_proof_inventory_reuse.py tests/unit/test_derivation_read_reuse.py -q -o addopts=''
HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_proof_inventory_reuse.py tests/unit/test_derivation_read_reuse.py -q -o addopts=''
```

Both runs produced `4 failed, 9 passed`. The decisive failures were:

- duplicate `EvidenceSpan` `_knowledge_get`: expected `0`, observed `1`;
- shared derived-parent dependency enumeration: expected `1`, observed `3`;
- `GenerationViews(..., _proof_reads=...)`: keyword did not exist;
- the updated existing proof reuse assertion likewise observed `1` rather than `0`.

Logs:

- `/tmp/hippo-proof-inventory-red-fake.log`
- `/tmp/hippo-proof-inventory-red-ladybug.log`

## Final-source verification

The final source state is base `4c22322` plus the uncommitted owned-file patch, identified by these SHA-256 values:

```text
edd59c68f6362ef6e3c5509fca1499e27a9b78c445465f1bfe1de91999f1e08c  src/hippo/knowledge/access.py
97624c10b58840f04ca3dca09cc28094db00fe423d5041853d588d6a23203ad4  src/hippo/knowledge/derivations.py
edab2f07f2f384b779ecee71496b415b7aa38dd888f0c083f8ae064ac2c46c95  tests/unit/test_proof_inventory_reuse.py
e34b6b1678beb8e01cf678084a3567ac4f1c3d4ceb60490a5ee8af51576411df  tests/unit/test_derivation_read_reuse.py
```

### G1 and review correction, final source

```text
HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_proof_inventory_reuse.py tests/unit/test_derivation_read_reuse.py -q -o addopts=''
15 passed in 0.47s

HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_proof_inventory_reuse.py tests/unit/test_derivation_read_reuse.py -q -o addopts=''
15 passed in 18.30s
```

Logs:

- `/tmp/hippo-proof-inventory-final2-g1-fake.log`
- `/tmp/hippo-proof-inventory-final2-g1-ladybug.log`

The added review regression proves an incapable standalone generation refuses before either membership table is read. The final focused set also proves the injected missing-generation error text.

### G2

Final-source fake command:

```text
HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_derived_evidence_access.py tests/unit/test_derived_generation_store.py tests/unit/test_query_snapshots.py tests/unit/test_evidence_access.py tests/unit/test_generation_scoped_reads.py tests/unit/test_knowledge_scoped_reads.py -q -o addopts=''
142 passed in 17.15s
```

Log: `/tmp/hippo-proof-inventory-final2-g2-fake.log`.

A separate complete Ladybug run on the initial GREEN source, before the constructor-order correction, produced `138 passed, 4 skipped in 219.35s`; log: `/tmp/hippo-proof-inventory-g2-ladybug.log`. The later correction only moved the same membership reads after the existing early validation refusals. Its affected regression passed on fake and Ladybug, and the entire final G1 passed on both as shown above. The orchestrator owns the final-source Ladybug G2 rerun with an adequate timeout.

The parent checker handle `39667` is not counted as a G2 pass: its built-in 120-second limit killed G2 before a verdict. A subsequently started redundant local Ladybug rerun was intentionally interrupted on orchestrator instruction and is also not counted.

### Static and diff checks, final source

```text
.venv/bin/python -m ruff check src/hippo/knowledge/access.py src/hippo/knowledge/derivations.py tests/unit/test_proof_inventory_reuse.py tests/unit/test_derivation_read_reuse.py
All checks passed!

.venv/bin/python -m compileall -q src/hippo/knowledge/access.py src/hippo/knowledge/derivations.py tests/unit/test_proof_inventory_reuse.py tests/unit/test_derivation_read_reuse.py
exit 0

git diff --check -- src/hippo/knowledge/access.py src/hippo/knowledge/derivations.py tests/unit/test_derivation_read_reuse.py
exit 0
```

Logs:

- `/tmp/hippo-proof-inventory-final-ruff.log`
- `/tmp/hippo-proof-inventory-final-compileall.log`
- `/tmp/hippo-proof-inventory-final-diff-check.log`

## Scope and exclusions

Only the four Task 1 code/test files and this report were changed by this worker. Other concurrent worktree changes were preserved. Neo4j, the full suite, model requests, private-corpus benchmarks, G3 timing/evidence comparison, commits, staging, and pushes were intentionally not performed. G3 remains orchestrator-owned and pending measurement.
