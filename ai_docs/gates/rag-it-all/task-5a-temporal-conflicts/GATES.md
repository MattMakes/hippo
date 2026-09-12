# Task 5A bitemporal evidence and deterministic conflict gates

Governing contract: `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md`.

Scope: G18. Pure modules may proceed now. Shared storage/access/snapshot/publication integration remains pending root ownership release.

OWNS: src/hippo/knowledge/{temporal,conflicts}.py, tests/unit/test_temporal_evidence.py, tests/unit/test_temporal_conflicts.py, tests/fixtures/rag_all/temporal_events.jsonl, ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md, ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/GATES.md, ai_docs/reports/2026-09-11-task-5a-temporal-conflicts-pre-flight.md

Status (2026-09-12): T5A1/T5A2/T5A5/T5A6 complete. T5A3/T5A4 are ticked by the gate checker for the history_manifest, suppression_history and purge_history halves only; their recorded_correction half (plan section 5, append-only correction publication) is integration part 2 and is not yet implemented, so Task 5A remains OPEN. Root-only Neo4j repeat still owed.

- [x] T5A1: Pure temporal selectors preserve both clocks and unknown/open semantics.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_temporal_evidence.py -q -o addopts='' -W error
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=b6bf9549d64b/37 entries; output=..............................................                           [100%] | 46 passed in 0.54s
  CRITERIA: UTC-aware half-open current/as-of/during/changes/atemporal/compare behavior; overlaps versus throughout; explicit open upper bound; unknown lower/time stays contextual; fixed known-at reconstruction; malformed intervals and contradictory snapshot/cutoff inputs reject; serialization preserves original/effective/observed/published fields without inferred dates.
  EXPECT: passed

- [x] T5A2: Deterministic replacement and conflict sets never use ingestion order.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_temporal_conflicts.py -q -o addopts='' -W error
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=b6bf9549d64b/37 entries; output=..............................                                           [100%] | 30 passed in 0.04s
  CRITERIA: only adapter-declared monotonic order supersedes same-source current candidates; old-imported-last/equality-only/equal-token-different-bytes remain ambiguous; independent sources remain alternatives; single versus multiple cardinality, effective overlap, unknown overlap and environment/scope isolation produce deterministic sorted ConflictSets with exact support.
  EXPECT: passed

- [x] T5A3: G18 history/access and append-only correction integration passes on Fake.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_temporal_evidence.py tests/unit/test_temporal_conflicts.py -k 'history_manifest or recorded_correction or suppression_history or purge_history' -q -o addopts='' -W error
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=b6bf9549d64b/37 entries; output=.......................                                                  [100%] | 23 passed, 53 deselected in 0.63s
  CRITERIA: authorized HistoryManifest closure includes retired-only evidence at fixed cutoff; current policy remains mandatory; ordinary current-only deletion leaves permitted history; all-history access-loss/purge denies old snapshots; May backdated correction preserves each recorded segment; atomic failure leaves prior publication unchanged; exact retry is idempotent.
  EXPECT: passed

- [x] T5A4: G18 storage behavior survives a real Ladybug close/reopen.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_temporal_evidence.py tests/unit/test_temporal_conflicts.py -k 'history_manifest or recorded_correction or suppression_history or purge_history' -q -o addopts='' -W error
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=b6bf9549d64b/37 entries; output=.......................                                                  [100%] | 23 passed, 53 deselected in 41.31s
  CRITERIA: parameterized recorded/effective selection, manifest persistence, interval closure/publication rollback and retained-history reachability match Fake after reopen; no test touches application data.
  EXPECT: passed

- [x] T5A5: Existing evidence, generation, snapshot, migration and projection contracts remain compatible.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_knowledge_contracts.py tests/unit/test_store_knowledge.py tests/unit/test_evidence_access.py tests/unit/test_generation_store.py tests/unit/test_snapshot_store.py tests/unit/test_generation_graph_loader.py -q -o addopts='' -W error
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=b6bf9549d64b/37 entries; output=.....................................................................    [100%] | 212 passed, 1 skipped in 4.54s
  CRITERIA: existing current selectors and query snapshots keep their behavior; history never widens access; recorded_to is the only mutable historical field; generation sealing/publication/collection and structural projections remain valid.
  EXPECT: passed

- [x] T5A6: Formatting passes for the pure and integrated modules.
  CHECK: .venv/bin/ruff check src/hippo/knowledge/temporal.py src/hippo/knowledge/conflicts.py src/hippo/knowledge/access.py src/hippo/knowledge/model.py src/hippo/knowledge/snapshots.py src/hippo/store/snapshots.py src/hippo/store/authorization.py tests/unit/test_temporal_evidence.py tests/unit/test_temporal_conflicts.py tests/unit/test_knowledge_contracts.py tests/unit/test_snapshot_store.py && .venv/bin/ruff format --check src/hippo/knowledge/temporal.py src/hippo/knowledge/conflicts.py src/hippo/knowledge/access.py src/hippo/knowledge/model.py src/hippo/knowledge/snapshots.py src/hippo/store/snapshots.py src/hippo/store/authorization.py tests/unit/test_temporal_evidence.py tests/unit/test_temporal_conflicts.py tests/unit/test_knowledge_contracts.py tests/unit/test_snapshot_store.py
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=b6bf9549d64b/37 entries; output=All checks passed! | 11 files already formatted
  CRITERIA: modified temporal implementation and tests pass Ruff check and format verification. Task completion separately requires independent SPEC/QUALITY review confirming no unchecked temporal ambiguity, authorization fork, non-atomic closure, mutable evidence, wall-clock dependency, or ingest-order tie-breaker.
  EXPECT: files already formatted

Root-only evidence: disposable Neo4j repeats T5A3 publication/CAS/conflict cases under a reserved database and confirms one winning closure/publication transaction. This evidence is required before Task 5A completion but is not run by this worker.
