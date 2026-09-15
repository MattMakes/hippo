# Brief: re-review the Task 5A pure fixes and close the precision-overlap question

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`). The fixes are committed at HEAD (commit subject "Add pure bitemporal selectors and deterministic conflict sets"); see `git show --stat HEAD`. Do NOT commit; the orchestrator commits after your run.

GOAL: (1) Make one small, specified fix (open finding 4 below) with RED/GREEN. (2) Independently re-review the fixes another worker made for findings F1–F5 of `ai_docs/reports/2026-09-11-temporal-pure-review.md` and confirm each is correct, tested and matches the orchestrator's decisions. You edit only for (1); for (2) you report.

CONTEXT:
- Plan: `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` sections 1–3 (now carrying "Amended 2026-09-11 after review" notes). Original review: the report above. Decisions the fixer followed: `ai_docs/handoffs/briefs/fix-temporal-pure.md` (read its DECISIONS block; they are final).
- Files: `src/hippo/knowledge/temporal.py`, `src/hippo/knowledge/conflicts.py`, `tests/unit/test_temporal_evidence.py`, `tests/unit/test_temporal_conflicts.py`, `tests/fixtures/rag_all/temporal_events.jsonl`.
- Gate ledger: `ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/GATES.md` (T5A1/T5A2/T5A5/T5A6 currently MET by the orchestrator's checker; T5A3/T5A4 are unstarted integration gates).
- The fixer's done summary reported two items it deliberately left: (4) `conflicts._explicit_intersection` still intersects a coarse-precision effective bound as if exact, so a year-precision claim versus an instant-precision claim yields `unresolved` with a computed interval, inconsistent with the F2 rule that coarse precision is never proven; (5) pre-existing: `superseded_version_ids` can repeat a version ID that is older in one series and current in another.

DECISIONS (final):
- Open finding 4: when EITHER candidate's effective bounds carry a `temporal_precision` other than `"instant"`, overlap cannot be proven: the conflict set gets `status="possible"` and null bounds, exactly like an unknown-overlap case. Do not attempt window-widening arithmetic. Amend plan section 3 with one sentence stating this, marked "Amended 2026-09-11 after re-review". RED: year-precision alice versus instant bob must produce `possible` with null bounds; instant versus instant with a provable intersection stays `unresolved` with the exact interval.
- Item 5: no code change. Add one sentence to plan section 3 recording that `superseded_version_ids` is per-series and may list a version that remains current in another series, and that the integration slice (sections 4–6) must key supersession by series when persisting.

FILES:
  - own (for the fix and plan note only): `src/hippo/knowledge/conflicts.py`, `tests/unit/test_temporal_conflicts.py`, `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` (section 3 only), EVIDENCE lines in the ledger for T5A2 and T5A6, and your report `ai_docs/reports/2026-09-11-temporal-pure-rereview.md`.
  - do NOT touch: `temporal.py`, `test_temporal_evidence.py`, the fixture, any coordinator or store file, `docs/`, the checkpoint, checkboxes in the ledger.

STEPS:
1. Baseline: run the T5A1, T5A2, T5A5, T5A6 commands from the ledger (each to `/tmp/hippo-temporal-rereview-<gate>-before.log` with `echo EXIT $?`); all must be green.
2. RED for finding 4, save `/tmp/hippo-temporal-rereview-red.log`; implement; GREEN T5A2 and T5A6 (`/tmp/hippo-temporal-rereview-<gate>.log`). Add the two plan sentences. Record EVIDENCE lines.
3. Re-review F1–F5 against the decisions, reading the code and the tests the fixer named (F1: `_deduplicate`, `_version_buckets`, `_pairwise_conflicts`, and the four rewritten/added tests; F2: `_point`/`_during` precision guard and `effective_imprecise`; F3: `compare_orders` and `select_same_source`; F4: `_series_key`; F5: `ResolvedTemporalSelector.__post_init__`, `latest_known_at`, origin labels). For each: CORRECT / INCOMPLETE / WRONG with file:line and the reason. Specifically check: (a) F1's raise condition compares whole typed (assertion, version) records, so two sources with identical records never raise and any recorded_to divergence does; (b) merged support in a bucketed alternative is sorted and unique and every contributing source ID is represented in the `ConflictSet`; (c) `compare_orders` never compares ordinals across adapter versions; (d) the F5 constructor rejects a cutoff after `latest_known_at` and derives `selector_json` from the selector alone; (e) the purity grep `rg -n "datetime.now|utc_now|time\(\)|store\.|ollama|httpx" src/hippo/knowledge/temporal.py src/hippo/knowledge/conflicts.py` is empty.
4. Write the report: verdict `RE-REVIEW: PASS|FAIL`, the F1–F5 table, any new findings with severity and proposed fix, the finding-4 fix summary, and gate results with log paths.

DONE WHEN: T5A1/T5A2/T5A5/T5A6 green after your change; RED log saved; plan amended; report written; `horch done` states the verdict, any new findings by severity, and the report path. No commits.

CONSTRAINTS: `HIPPO_TEST_STORE=fake` explicit; no Ladybug or Neo4j needed; no edits outside the listed files.

REPORT: `horch note` after baseline, after GREEN, after the report.
