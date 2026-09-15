# Brief: fix the plain-prose coordinator after independent review, then Neo4j parity

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`); the files are uncommitted there. Do NOT commit; the orchestrator runs the gate checker and commits.

GOAL: Resolve the review findings in `ai_docs/reports/2026-09-11-prose-coordinator-review.md` that belong to this slice (findings 1, 2, 4, 5 and the minors), leave finding 3 explicitly deferred, get PC1–PC4 green including the full Ladybug run, then run the same tests once on the disposable Neo4j container, which you hold exclusively for that one run.

CONTEXT:
- Contract: `ai_docs/plans/rag-it-all-task-5-prose-coordinator.md` (sections 4–9 bind). Ledger: `ai_docs/gates/rag-it-all/task-5-prose-coordinator/GATES.md`. Review report above: read all of it; each finding has file:line and a proposed fix.
- Verified state: PC1 Fake 59 passed / 1 skipped; PC3 136 passed; PC4 Ruff clean; PC2 Ladybug 2 failed / 58 passed in ~16 minutes (`/tmp/hippo-prose-review-pc2.log`). One Ladybug bootstrap measured at 18.59 s (`/tmp/hippo-prose-review-timing.log`).
- Files under your ownership: `src/hippo/ingest/prose_generation.py`, `tests/unit/test_prose_generation.py`, the ledger above (EVIDENCE lines and its "Status:" line only), and `ai_docs/plans/rag-it-all-task-5-prose-coordinator.md` (only to add the deferral note described below).

DECISIONS (final):

- Finding 1 and 2 (blockers, test-only): fix the harness as the report proposes. `thread.join` budgets must be derived from the measured per-bootstrap cost with headroom (two serialized Ladybug bootstraps plus margin), or better, the test must wait on the rendezvous event rather than a fixed budget. The unblock helper's `checking.wait(...)` window must open at the rendezvous, not before the build starts. No production code changes for these two. Both tests must pass on Fake and on Ladybug.
- Finding 3 (major, store-layer ambient-transaction probe reading the process-global depth): DEFERRED, not yours. Do not touch any file under `src/hippo/store/` or `tests/fakes/`. Add a short "Known limitation (deferred 2026-09-11)" paragraph at the end of the plan's "Coordinator implementation notes": concurrent `build_plain_source` calls in one process can be spuriously rejected by the ambient-transaction probe until the store exposes per-thread transaction ownership; the orchestrator schedules that store increment before production dispatch (activation Task 3). Add one skipped test that documents the intended behavior (`pytest.mark.skip(reason="store per-thread transaction ownership pending")`) so the follow-up has a RED to turn on.
- Finding 4 (major, `_Run._check` re-reads `self.heartbeat` after the None test while `pause()` nulls it): fix with a single local read of the attribute, and add an event-controlled RED test that reproduces the bogus `AuthorizationChanged` before the fix.
- Finding 5 (major, after-publication epoch recheck at ~:588 untested): add a RED test that changes the authorization epoch between the publish call and the post-publish recheck inside the same transaction path (use the same fault-injection style the existing publication tests use) and proves the transaction rolls back with G1 unchanged.
- Minors 6–11: apply each as the report proposes when the change is local to your two files; if a minor needs another file, list it as deferred in your done summary instead. Minor 11 is documentation only: the next brief will import `ByteInput`/`FileInput`/`ExcludedInput` from `hippo.ingest.accepted_inputs`; you do not need to re-export them.

FILES:
  - own: the four listed above.
  - do NOT touch: `src/hippo/store/*`, `tests/fakes/*`, `src/hippo/knowledge/*`, `src/hippo/ingest/*` other than `prose_generation.py`, the temporal files (`src/hippo/knowledge/temporal.py`, `conflicts.py`, their tests; another worker owns them in this tree), `docs/`, the checkpoint, any other ledger.

STEPS:
1. Baseline: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_prose_generation.py -o addopts='' -q -W error` must be 59 passed / 1 skipped before you change anything.
2. RED for findings 4 and 5: write the tests, run on Fake, save `/tmp/hippo-prose-fix-red.log` showing them failing.
3. Fix finding 4; make finding 5's test pass (if it already passes because the code is right, say so and keep the test). Apply the minors. Fix the two harness tests (findings 1, 2).
4. GREEN Fake: PC1 and PC3 commands, logs `/tmp/hippo-prose-fix-pc1.log`, `/tmp/hippo-prose-fix-pc3.log`.
5. GREEN Ladybug: PC2 command, log `/tmp/hippo-prose-fix-pc2.log`. Start it in the background and keep working on the ledger while it runs (about 16 minutes). It must be 0 failed.
6. PC4 Ruff check + format on both files.
7. Neo4j parity, ONE run, you hold the container until it finishes: `HIPPO_TEST_STORE=neo4j NEO4J_URI=bolt://127.0.0.1:32774 NEO4J_USER=neo4j NEO4J_PASSWORD=hippo-disposable-test .venv/bin/pytest tests/unit/test_prose_generation.py -o addopts='' -q -W error > /tmp/hippo-prose-fix-neo4j.log 2>&1; echo EXIT $?`. Never run two Neo4j pytest processes. Never target port 7687. When it finishes, `horch note "neo4j released"`.
8. Record EVIDENCE lines under PC1–PC4 (result line + log path) and add a `PC-N4` evidence line for the Neo4j run under PC2. Update the ledger "Status:" line to describe the actual state. Leave checkboxes unticked.

DONE WHEN: PC1–PC4 green (PC2 with 0 failed on Ladybug); Neo4j run recorded; RED log saved; plan deferral note added; `horch done` lists per finding what changed (file:line), test names added, counts per backend with log paths, and any minor you deferred with the reason. No commits.

OUT OF SCOPE: store changes (finding 3), production route activation, pipeline dispatch, raw GC.

REPORT: `horch note` after baseline, RED, Fake green, Ladybug started, Ladybug green, Neo4j released. `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a genuine conflict with these decisions.
