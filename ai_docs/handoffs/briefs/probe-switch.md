# Brief: switch the two remaining ambient-transaction probes to per-thread ownership

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`) at the HEAD the orchestrator names in the spawn message. Do NOT commit; the orchestrator commits.

GOAL: The plain-prose coordinator and the staged-prose writer wrapper decide "is there an ambient transaction?" with the new per-thread store API, so two builds in different threads no longer reject each other, and the coordinator's deferred concurrency test is turned on and passes.

CONTEXT:
- `store.in_ambient_transaction() -> bool` exists on all three stores since merge `afb8960` (`ai_docs/gates/rag-it-all/task-5-prose-coordinator/evidence-txown.md` describes it: true only when the CALLING thread opened the outermost transaction). `src/hippo/knowledge/build_authority.py::BuildAuthority.check` already uses it.
- Two probes still read the process-global `_transaction_depth` / `_transaction`:
  1. `src/hippo/ingest/prose_generation.py` around line 652 (entry validation of `build_plain_source`: "Coordinator requires no ambient transaction"). This is the false rejection from review finding 3 of `ai_docs/reports/2026-09-11-prose-coordinator-review.md`. The coordinator fixer added a skipped test (`pytest.mark.skip(reason="store per-thread transaction ownership pending")` or similar; find it with `rg -n "ownership pending" tests/unit/test_prose_generation.py`).
  2. `src/hippo/knowledge/staged_prose.py` around line 224 ("Staged refresh wrapper requires no outer transaction"), the same false rejection.
- Pattern for two-thread RED tests: `tests/unit/test_transaction_ownership.py` (bounded waits, `release.set()` in the caller's `finally`, helper threads catch `BaseException` and report on the calling thread).

FILES:
  - own: `src/hippo/ingest/prose_generation.py` (that probe only), `src/hippo/knowledge/staged_prose.py` (that probe only), `tests/unit/test_prose_generation.py` (un-skip plus any needed adjustment of that one test), `tests/unit/test_staged_prose_writer.py` (one new two-thread test).
  - do NOT touch: anything else.

STEPS:
1. Baseline: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_prose_generation.py tests/unit/test_staged_prose_writer.py tests/unit/test_transaction_ownership.py -q -o addopts='' -W error > /tmp/hippo-probe-baseline.log 2>&1; echo EXIT $?` must be green (one skip expected).
2. RED: remove the skip marker on the coordinator test; add to `test_staged_prose_writer.py` a test where a helper thread holds an open store transaction (parked on an event) while the main thread calls the public `write_staged_prose` wrapper and expects it NOT to raise the outer-transaction error, and a sibling test where the SAME thread holds a transaction and it still raises. Run; save `/tmp/hippo-probe-red.log` (both new expectations must fail before the switch).
3. Switch both probes to `store.in_ambient_transaction()` (the store handle each function already has). Keep the error messages unchanged.
4. GREEN: the step-1 command, log `/tmp/hippo-probe-fake-green.log`; then `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_staged_prose_writer.py -q -o addopts='' -W error > /tmp/hippo-probe-ladybug-green.log 2>&1; echo EXIT $?`. Do NOT run the full coordinator file on Ladybug (16 minutes; the orchestrator schedules that).
5. Ruff check + format on the four files.
6. `horch note "probe switch green on Fake; ready for final Ladybug and Neo4j"` and WAIT for the orchestrator's `horch tell` saying the disposable Neo4j container is yours. Then, in this order, one process at a time:
   a. PC2 at final state: `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_prose_generation.py -o addopts='' -q -W error > /tmp/hippo-probe-pc2-ladybug.log 2>&1; echo EXIT $?` (about 18 minutes; must be 0 failed).
   b. Neo4j parity at final state: `HIPPO_TEST_STORE=neo4j NEO4J_URI=bolt://127.0.0.1:32774 NEO4J_USER=neo4j NEO4J_PASSWORD=hippo-disposable-test .venv/bin/pytest tests/unit/test_prose_generation.py tests/unit/test_staged_prose_writer.py tests/unit/test_transaction_ownership.py tests/unit/test_managed_source_lifecycle.py tests/unit/test_local_workspace_membership.py tests/unit/test_managed_source_inventory.py -o addopts='' -q -W error > /tmp/hippo-probe-neo4j.log 2>&1; echo EXIT $?`. Never two Neo4j pytest processes; never port 7687. When it finishes, `horch note "neo4j released"`.
   c. Record EVIDENCE lines for PC2 and a `PC-N4` line in `ai_docs/gates/rag-it-all/task-5-prose-coordinator/GATES.md` (you own those lines for this step; leave checkboxes alone).

DONE WHEN: Fake green with the coordinator test un-skipped and the two writer tests added; Ladybug writer file green; final PC2 Ladybug 0 failed; Neo4j run recorded and released; Ruff clean; `horch done` lists the two probe lines changed (file:line), the test names, counts per backend and log paths. No commits.

REPORT: `horch note` after RED and after GREEN.
