# Neo4j parity evidence (root-owned, disposable container)

Container `hippo-rag-test-b780ab5` (Neo4j 5.26.30, bolt `127.0.0.1:32774`, no host bind mounts), one pytest process at a time, `-W error`, `-o addopts=''`.

## Run 1 — activation store, ordering and pipeline slices (2026-09-12)

Tree: `812c60e` (Tasks 1, 2, 3a, 3b, per-thread transaction ownership, fact and arrow ordering, import-order guard).

Files: `test_import_order.py`, `test_transaction_ownership.py`, `test_local_workspace_membership.py`, `test_managed_source_lifecycle.py`, `test_managed_source_inventory.py`, `test_fact_order_determinism.py`, `test_structural_loading.py`, `test_generation_store.py`, `test_managed_pipeline_activation.py`.

Result: `313 passed, 4 skipped in 1906.36s`, exit 0. Log `/tmp/hippo-orch-neo4j-parity-1.log`. The four skips are Ladybug-only close/reopen contracts and the driver auto-abort case.

This covers the Neo4j halves of PA1, PA3, PA4, PA5 and PA7 for the store, inventory, membership, tombstone, restart-sweep and managed dispatch behavior. Route-level tests (PA6) run on Fake and Ladybug only; they exercise no Neo4j-specific code.

## Run 2 — temporal, snapshot and generation slices (2026-09-12)

Tree: `a9512a2` or later (Task 5A parts 1 and 2 with both review fix rounds).

Files: `test_temporal_evidence.py`, `test_temporal_conflicts.py`, `test_snapshot_store.py`, `test_query_snapshots.py`, `test_generation_store.py`.

Result: `160 passed in 320.68s`, exit 0. Log `/tmp/hippo-orch-neo4j-parity-2.log`. This is the root-only disposable-Neo4j repeat the Task 5A ledger required for the publication/CAS/conflict cases (T5A3) and the snapshot/generation contracts.
