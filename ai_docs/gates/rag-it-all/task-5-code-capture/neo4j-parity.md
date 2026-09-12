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
