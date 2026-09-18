# Brief: fix the Task 5A pure temporal/conflict increment after independent review

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`); the files are uncommitted there. Do NOT commit; the orchestrator runs the gate checker and commits.

GOAL: Resolve every finding in `ai_docs/reports/2026-09-11-temporal-pure-review.md` (F1–F9 plus the fixture gap) according to the decisions below, RED-first, so that T5A1/T5A2/T5A5/T5A6 pass with `-W error` and the plan's section 3 matches the code.

CONTEXT:
- Contract: `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` sections 1–3 and 7. Review: the report above (354 lines; read all of it, it has file:line and a proposed fix per finding). Gate ledger: `ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/GATES.md`.
- The reviewer left reproduction scripts you should turn into RED tests: `/tmp/probe_corroborate.py` (F1), `/tmp/probe_temporal.py` (F2, F5), `/tmp/probe_conflicts.py` (F4 and the untested pairwise path). Read them before writing tests.
- Typed contracts you build on: `src/hippo/knowledge/model.py` (`AssertionVersion.identity_fields`, `TimeInterval`, `ConflictSet`, `TemporalRecord`, selector types). `AssertionVersion.identity_fields` deliberately excludes `source_id` and `support_span_ids`: one version ID is legitimately corroborated by several sources.
- Nothing here touches store, access, snapshots, lifecycle, or publication; sections 4–6 remain later work.

DECISIONS (these are final; do not re-litigate them in the report):

F1 BLOCKER, option (b) refined. `_deduplicate` in `conflicts.py` must: (i) collapse exact duplicate candidates (same version, same source, same spans) idempotently; (ii) raise `ValueError` ONLY when two candidates share a version ID but differ in identity-relevant metadata (workspace, assertion ID, subject, predicate, object, scope, validity kind, effective/recorded bounds: everything in `identity_fields` plus the assertion identity); (iii) KEEP candidates that differ only in `source_id`, `support_span_ids`, or `SourceOrder` as separate per-source candidates, because `select_same_source` groups per source. In `build_conflict_sets`, candidates that share a version (same target object) from different sources are ONE alternative with the sorted unique union of their support span IDs and every contributing source represented; they never form a conflict with each other. Rewrite `test_same_target_from_independent_sources_is_support_not_conflict` so both sources produce the SAME version ID (drop the differing `recorded_from`) and it still yields support, not conflict, and add the rival case (alice from two sources plus bob from a third yields exactly one conflict set with alice's merged support). Rewrite `test_one_version_id_cannot_be_rebound_to_another_source` as `test_one_version_id_cannot_carry_divergent_identity_metadata` (different object or predicate or scope under one version ID raises) and add the positive corroboration case beside it. Amend plan section 3 with two sentences stating this representation.

F2 MAJOR, fix code. `_point` and `_during` must apply the same `temporal_precision` guard `_changes` applies at `temporal.py:212`: a record whose precision is coarser than the requested point/interval requires cannot be PROVEN, it is contextual with a precision reason. RED: year-precision `valid_from=2026-01-01`, `as_of 2026-03-01` and `during/throughout` must not return `effective_match`. Implement the half-open math once (F9): one private helper used by `_point`, `_during`, `_explicit_intersection`, reusing `model.TimeInterval` where it already exists.

F3 MAJOR, amend plan AND add code. `OrderingRelation` becomes the return type of a new pure `compare_orders(a: SourceOrder, b: SourceOrder) -> OrderingRelation` in `conflicts.py`: same adapter identity + same series + both `monotonic` with ordinals gives `older`/`same`/`newer`; anything else (different adapter, `equality_only`, `unknown`, missing ordinal) gives `ambiguous`. `select_same_source` must use `compare_orders` for its decisions so the rule lives once. Amend plan section 3: `SourceOrder` keeps `monotonic_ordinal` as the only adapter-supplied ordering datum in this increment; pairwise-only adapters (for example Git ancestry without a total order) are explicitly deferred to the connector tasks (Tasks 9–10) and must declare `unknown` until then. Add tests for every branch of `compare_orders`.

F4 MAJOR, fix code. `_series_key` includes the ordering adapter identity (adapter ID and adapter version) exactly as section 3 states. Two adapters on one series form separate same-source groups; each group's current candidate then participates independently in conflict construction. RED: the reviewer's `probe_conflicts.py` case where an adapter version bump previously collapsed to ambiguous must now keep deterministic supersession within each adapter group.

F5 minor, fix code. `ResolvedTemporalSelector.__post_init__` derives `selector_json` itself instead of accepting it; `known_at_source='explicit'` is rejected for selector kinds without a `known_at` field; the `known_at <= latest_known_at` bound is enforced at construction, not only in `_resolve_single`. RED: direct construction with a year-2099 cutoff must raise.

F6 minor, amend plan. Keep the code: atemporal-versus-atemporal overlap is proven, so null bounds with `unresolved` is correct. Change the plan sentence to: "Conflict interval is the exact half-open intersection when provable; otherwise both bounds are null. Status is `unresolved` when overlap is proven (including atemporal claims) and `possible` when it cannot be proven."

F7 minor, defer with a note. Leave `recorded_match` in the literal; add one line to plan section 4 saying the history-selection service (sections 4–6) emits it for recorded-eligibility decisions. Do not emit it now.

F8 minor, fix. Add a test that loads `tests/fixtures/rag_all/temporal_events.jsonl`, validates every row against a small explicit schema (required keys, ISO instants parse as aware UTC or are null, precision in the closed set, ordering metadata present where the scenario needs it), and asserts all nine section 7 step 3 scenario labels are present.

Fixture gap, fix. Add a row pair for "equal `source_updated_at`, different bytes" (both rows carry the same `source_updated_at`, different content hashes, equality-only ordering) so the named scenario is represented; keep the existing ETag pair.

F9 minor: covered by F2's single helper.

FILES:
  - own: `src/hippo/knowledge/temporal.py`, `src/hippo/knowledge/conflicts.py`, `tests/unit/test_temporal_evidence.py`, `tests/unit/test_temporal_conflicts.py`, `tests/fixtures/rag_all/temporal_events.jsonl`, `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` (sections 3 and 4 amendments only, marked "Amended 2026-09-11 after review"), and EVIDENCE lines under T5A1/T5A2/T5A5/T5A6 in the ledger (leave checkboxes as they are; T5A5 is currently ticked by the implementer, leave it).
  - do NOT touch: `src/hippo/knowledge/model.py` or any other source file, any other test, the coordinator files (`src/hippo/ingest/prose_generation.py`, `tests/unit/test_prose_generation.py`, under separate review in this tree), store/access/snapshots/lifecycle, `docs/`, the checkpoint. If a fix seems to need `model.py`, stop and ask.

STEPS:
1. Read the review report and the three probe scripts. Confirm baseline: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_temporal_evidence.py tests/unit/test_temporal_conflicts.py -q -o addopts='' -W error` is green (37 passed) before you change anything.
2. RED for F1, F2, F3, F4, F5, F8 and the fixture pair: write the tests, run, save `/tmp/hippo-temporal-fix-red.log`. The F1 rewrites must fail against the current `_deduplicate`.
3. Implement F1, then F2/F9, then F4, then F3, then F5, then F8/fixture. Keep both modules free of store, model-call and clock imports (the reviewer's `rg` for `datetime.now|utc_now|time\(\)|store\.|ollama|httpx` must stay empty).
4. Amend the plan for F1, F3, F6, F7.
5. GREEN: T5A1, T5A2, T5A5, T5A6 commands exactly as in the ledger, logs `/tmp/hippo-temporal-fix-<gate>.log`. Record EVIDENCE lines (result line + log path).
6. Ruff check + format on the four Python files.
7. Re-run the three probe scripts; each must now either pass or fail in the newly intended way. Note the outcome per script in your done summary.

DONE WHEN: all four gate commands green with `-W error`; RED log saved; plan amended; EVIDENCE lines recorded; `horch done` lists per finding F1–F9 what changed (file:line), the test names added or rewritten, the test counts and log paths, and the probe outcomes. No commits.

OUT OF SCOPE: sections 4–6 integration (history service, publication plan, store changes), Neo4j, Ladybug (pure tests are backend-independent).

REPORT: `horch note` after baseline, after RED, after each major finding lands, after GREEN. `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a genuine contract conflict with these decisions; otherwise proceed.
