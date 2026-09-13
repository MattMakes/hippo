# Neo4j parity for the managed code-capture slices (orchestrator-run)

Container `hippo-rag-test-b780ab5` (Neo4j 5.26.30, bolt `127.0.0.1:32774`, no host bind mounts),
one pytest process at a time, `-W error`, `-o addopts=''`. Ladybug is the primary backend; these runs
verify the Neo4j lane of the same suites after each store-touching slice merges.

## Run 1: CC1 legacy serving (merged at `7a0c719`)

Command (credentials via the test-only environment, never printed):

```
HIPPO_TEST_STORE=neo4j NEO4J_URI=bolt://127.0.0.1:32774 .venv/bin/pytest \
  tests/unit/test_converting_source_serving.py tests/unit/test_managed_source_inventory.py \
  tests/unit/test_status_access.py -q -o addopts='' -W error
```

Result: `62 passed, 2 skipped in 305.74s` (log `/tmp/hippo-orch-neo4j-parity-cc1.log`). Covers
`source_serves_legacy`'s IndexEvent and Suppression reads, the reopen-mid-staging and tombstone
cases, and the status lanes on the Neo4j backend.

## Run 2: CC2 generation-scoped reads and schema v6 (merged at `c461c9c`, run on `c461c9c`)

```
HIPPO_TEST_STORE=neo4j NEO4J_URI=bolt://127.0.0.1:32774 .venv/bin/pytest \
  tests/unit/test_generation_scoped_reads.py tests/unit/test_generation_store.py \
  tests/unit/test_store_migrations.py tests/unit/test_policy_migration.py \
  tests/unit/test_generation_counts.py tests/unit/test_staged_prose_writer.py \
  tests/unit/test_converting_source_serving.py -q -o addopts='' -W error
```

Result: `150 passed, 5 skipped in 874.26s` (log `/tmp/hippo-orch-neo4j-parity-cc2.log`). This is the
only backend that executes the eight v6 `CREATE INDEX` statements and `validate_physical_schema`'s
version >= 6 RANGE assertions (Ladybug has no secondary-index DDL), so CD1's index-backed half is
proven here. Also covers the `n.id IN $ids` / `n.generation_id = $g` native reads, the Passage owner
join, the three `_edges_touching` passes and the scoped `_knowledge_rows` reads.

## Run 3: CC3 reclaim and the cc1fix legacy lane (merged at `8f32ec4`, run on `8f32ec4`)

```
HIPPO_TEST_STORE=neo4j NEO4J_URI=bolt://127.0.0.1:32774 .venv/bin/pytest \
  tests/unit/test_generation_resume.py tests/unit/test_generation_failure.py \
  tests/unit/test_managed_source_lifecycle.py tests/unit/test_converting_source_serving.py \
  tests/unit/test_managed_source_inventory.py tests/unit/test_status_access.py \
  -q -o addopts='' -W error
```

Result: `134 passed, 2 skipped in 528.85s` (log `/tmp/hippo-orch-neo4j-parity-cc3.log`). Covers
`_admit_build`'s scoped Suppression and IndexEvent reads, the tightened never-published triple, the
`generation_lock` increment on an idempotent admission, `context.legacy_lane()`'s untagged reads
(`generation_id IS NULL AND source_id = $source_id`) and the status lanes. Note: the same
`test_managed_source_lifecycle.py` was red on Ladybug at `013317f` (five managed builds failing to
publish), so that defect is Ladybug-specific; its fix is recorded in `evidence-lbfix.md`.

## Run 4: CC8 staged code writer, code profile, rebaseline and the PA2 f5 pins (run on `d1910c8`)

```
HIPPO_TEST_STORE=neo4j NEO4J_URI=bolt://127.0.0.1:32774 .venv/bin/pytest \
  tests/unit/test_staged_code_writer.py tests/unit/test_generation_profiles.py \
  tests/unit/test_build_authority.py tests/unit/test_multi_generation_support.py \
  -q -o addopts='' -W error
```

Result: `161 passed in 682.95s` (log `/tmp/hippo-orch-neo4j-parity-cc8.log`). Covers the fenced
dependency-group writes, the resume probe's canonical-payload and absence checks, the seal under the
`code` generation profile, `BuildAuthority.rebaseline` and the widened source-control admission, and
the two-source proof-group refusals.

## Run 5: the primary-key read helper from the Ladybug fix (merged at `9770c00`, run on `9770c00`)

```
HIPPO_TEST_STORE=neo4j NEO4J_URI=bolt://127.0.0.1:32774 .venv/bin/pytest \
  tests/unit/test_generation_scoped_reads.py tests/unit/test_generation_store.py \
  tests/unit/test_derived_projection.py tests/unit/test_managed_source_lifecycle.py \
  -q -o addopts='' -W error
```

Result: `111 passed, 2 skipped in 573.98s` (log `/tmp/hippo-orch-neo4j-parity-lbfix.log`). Covers the
`UNWIND $ids AS rid MATCH (n:Kind {id: rid})` form that replaced every `IN $list` node-property
predicate in `store/*` and `knowledge/projection.py` (an index seek per id on Neo4j), the scoped
reads and the managed lifecycle on the Neo4j backend.
