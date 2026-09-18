# Brief: close the fully-purged manifest fail-open (re-review finding N2) and the plan drift (N3)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`) at the current `rag-it-all-tibs` HEAD. Do NOT commit; the orchestrator commits.

GOAL: `purged_history_evidence` never hands purge markers to an audience that cannot prove the manifest, including when every revision the manifest names has been purged; the plan text about the identity carve-out matches what the evidence says.

CONTEXT:
- Finding N2 in `ai_docs/reports/2026-09-11-t5a-int1-rereview.md` (read sections 2 and 5): in `src/hippo/store/snapshots.py:192-201`, `retained = revision_ids - purged` is empty when everything is purged, and `retained <= proof.revision_ids` is vacuously true, so a disabled member, a stranger with no membership, or an open/preview audience receives the complete marker list. The adjacent partial-purge case is correctly denied by the existing test. Reproduction: `HIPPO_TEST_STORE=fake PYTHONPATH=/Users/mascott/projects/hippo .venv/bin/python /tmp/t5a1rr/probe_f9.py` (read it; it builds its own FakeStore).
- Decision: in the non-internal branch, when `retained` is empty and `history.revision_ids` is not, raise the same `SnapshotUnavailable` the unknown-manifest path raises. Internal audience behavior unchanged. An authorized reader whose proof still contains the unpurged remainder is unchanged.
- Finding N3: `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` section 4's carve-out bullet says every pre-change identity stays byte-identical; that is true only for current/atemporal selectors (as_of/during/changes/compare snapshots already carried an explicit null `known_at`, so their IDs change, harmlessly, because no persisted row uses them). Reword the bullet to match `ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/evidence-int1.md`, marked "Amended 2026-09-12 after re-review".

FILES:
  - own: `src/hippo/store/snapshots.py` (that function only), `tests/unit/test_snapshot_store.py`, `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` (section 4 bullet only).
  - do NOT touch: anything else. Five workers own other files in worktrees; nothing else is live in the root tree.

STEPS:
1. Baseline: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_snapshot_store.py tests/unit/test_temporal_evidence.py -q -o addopts='' -W error > /tmp/hippo-n2-baseline.log 2>&1; echo EXIT $?` must be green.
2. RED: add to `tests/unit/test_snapshot_store.py` a test modeled on the probe: publish a manifest, purge every revision it names, then assert that a disabled member, a principal with no membership, and an open audience each raise `SnapshotUnavailable`, while the internal audience still receives the full marker list, and an authorized reader with a partial purge still works as the existing test proves. Run; save `/tmp/hippo-n2-red.log` showing the new test failing.
3. Implement the four-line guard. GREEN: the baseline command plus `tests/unit/test_query_snapshots.py`, log `/tmp/hippo-n2-fake-green.log`; then `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_snapshot_store.py -q -o addopts='' -W error > /tmp/hippo-n2-ladybug-green.log 2>&1; echo EXIT $?`.
4. Ruff check + format on the two Python files. Amend the plan bullet.

DONE WHEN: RED log saved; Fake and Ladybug green; Ruff clean; plan bullet amended; `horch done` lists the exact lines changed (file:line), the test name, counts and log paths. No commits.

REPORT: `horch note` after RED and after GREEN.
