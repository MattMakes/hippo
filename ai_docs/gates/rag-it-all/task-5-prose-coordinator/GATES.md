# Plain-prose coordinator gates

Scope: explicit API only. No production route, bulk dispatch or source deletion activation.

Status: independent review complete, all findings inside this slice resolved, and every probe now uses per-thread transaction ownership (store increment evidence-txown.md; coordinator and staged-writer probes switched in 158ebf2 with the deferred concurrent-build test enabled). Final PC2 on real Ladybug at 158ebf2: 67 passed, 0 failed. PC-N4 on the disposable Neo4j at 158ebf2: 204 passed across the coordinator, staged writer, transaction ownership, tombstone, membership and inventory files. Minors 7, 9(b) and 11 are recorded in the plan for later slices. Nothing in this slice activates a production route. Runnable checkboxes are set by the orchestrator's gate checker.

- [x] PC1: Fake end-to-end input/authority/bootstrap/refresh/recovery/receipt/cancellation and privacy checks cover plan PC1–PC6.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_prose_generation.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=b6bf9549d64b/37 entries; output=............................................................s......      [100%] | 66 passed, 1 skipped in 6.75s

- [x] PC2: Disposable Ladybug end-to-end rollback, reopening, fencing and raw retention cover plan PC7.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_prose_generation.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=b6bf9549d64b/37 entries; output=...................................................................      [100%] | 67 passed in 1228.04s (0:20:28)
  PC-N4 EVIDENCE (disposable Neo4j parity; not a separate runnable gate — do not re-run it as part of gate checking, the container admits one pytest process at a time): 204 passed, 3 skipped, 0 failed in 1595.14s (0:26:35), EXIT 0, with -W error at HEAD 158ebf2, using HIPPO_TEST_STORE=neo4j NEO4J_URI=bolt://127.0.0.1:32774 NEO4J_USER=neo4j NEO4J_PASSWORD=hippo-disposable-test with -o addopts='' -q over six files: tests/unit/{test_prose_generation,test_staged_prose_writer,test_transaction_ownership,test_managed_source_lifecycle,test_local_workspace_membership,test_managed_source_inventory}.py. Wider than the earlier single-file PC-N4 because the probe switch also changes the staged-prose writer, and the managed-source files exercise the same store transaction paths. Log: /tmp/hippo-probe-neo4j.log. One exclusive run, the container (hippo-rag-test-b780ab5, bolt 127.0.0.1:32774) held for its whole duration and released on completion; no second Neo4j process ran, and the Ladybug PC2 pass above finished before this one started. The three skips are the only conditional skips in those six files and all are Ladybug-only contracts: test_prose_generation.py:1016 (real Ladybug close/reopen), test_transaction_ownership.py:94 (a statement the driver auto-aborted), test_managed_source_inventory.py:528 (LadybugDB reopen persistence); the three `s` marks in the progress output fall inside those three files in run order, the last one on the run's final test. This supersedes the pre-txown single-file run at 82bd317 (65 passed / 2 skipped in 1100.64s, /tmp/hippo-prose-fix-neo4j.log).

- [x] PC3: Reviewed authority, preparation/writer, profile and existing ingestion compatibility remain green.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_build_authority.py tests/unit/test_managed_prose_preparation.py tests/unit/test_staged_prose_writer.py tests/unit/test_generation_profiles.py tests/unit/test_ingest_concurrency.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=b6bf9549d64b/37 entries; output=..................................................................       [100%] | 138 passed in 5.26s

- [x] PC4: Ruff, formatting and independent review (plan PC8).
  CHECK: .venv/bin/ruff check src/hippo/ingest/prose_generation.py src/hippo/knowledge/staged_prose.py tests/unit/test_prose_generation.py tests/unit/test_staged_prose_writer.py && .venv/bin/ruff format --check src/hippo/ingest/prose_generation.py src/hippo/knowledge/staged_prose.py tests/unit/test_prose_generation.py tests/unit/test_staged_prose_writer.py
  EXPECT: 4 files already formatted
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=b6bf9549d64b/37 entries; output=All checks passed! | 4 files already formatted

RED/GREEN history: 23 initial missing-module failures; unauthorized own-setup epoch rebase; immutable retired-operation receipt and operation-key retargeting; shared-depth heartbeat false rejection; sticky cancellation/progress failure; changed-input expired-attempt recovery; original publication-credential mismatch. Each observed failure was followed by the focused fix and green run. Exact logs: /tmp/hippo-prose-coordinator-{red,delta-red,lifecycle-red,latch-red,recovery-red}.log. Additional admission, source-policy, partial-start, concurrent-bootstrap, held-renewal and persistence cases strengthen those boundaries; their passing runs do not claim any production dispatch activation.
