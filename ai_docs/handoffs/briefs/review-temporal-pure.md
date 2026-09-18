# Brief: independent SPEC/QUALITY review of the Task 5A pure temporal/conflict increment

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`), not a worktree, because the files under review are uncommitted there.

GOAL: Produce an independent review verdict on the uncommitted pure Task 5A modules against their contract, and run the pure gates. You read and run; you do not edit source or tests.

CONTEXT:
- Contract: `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md`. Sections 1–3 bind this increment; section 7 steps 1–3 describe what was supposed to be built; sections 4–6 are LATER work (shared-file integration) and are out of scope for this review except to confirm nothing from them was attempted.
- Gate ledger: `ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/GATES.md`. T5A5 has evidence; T5A1, T5A2, T5A6 are runnable now; T5A3/T5A4 need integration that has not started and will be skipped by `-k` when their tests do not exist. Pre-flight report: `ai_docs/reports/2026-09-11-task-5a-temporal-conflicts-pre-flight.md`.
- Files under review: `src/hippo/knowledge/temporal.py` (270 lines), `src/hippo/knowledge/conflicts.py` (214 lines), `tests/unit/test_temporal_evidence.py`, `tests/unit/test_temporal_conflicts.py`, `tests/fixtures/rag_all/temporal_events.jsonl` (12 lines).
- The orchestrator has confirmed on Fake: both test files pass with `-W error`, Ruff clean. The implementer no longer exists.
- Existing typed contracts the modules must build on: `src/hippo/knowledge/model.py` (`TemporalRecord`, `Assertion`, `AssertionVersion`, `ConflictSet`, `HistoryManifest`, selector types). Read those definitions.

FILES:
  - own: `ai_docs/reports/2026-09-11-temporal-pure-review.md` (your report); EVIDENCE lines under T5A1, T5A2, T5A6 in the ledger.
  - do NOT touch: anything else.

STEPS:
1. Run the T5A1, T5A2, T5A5, T5A6 commands exactly as in the ledger, each captured to `/tmp/hippo-temporal-review-<gate>.log` with `echo EXIT $?`. Record EVIDENCE lines for T5A1, T5A2, T5A6 (leave checkboxes unticked).
2. SPEC review against plan §1–§3. For each item, classify PROVEN (test name) / UNTESTED / VIOLATED (file:line):
   a. Naive datetimes rejected everywhere an instant enters; original text/timezone/precision preserved; precision never upgraded to an exact instant (§1, §2).
   b. Half-open `[start, end)`; missing upper = open-ended; missing lower = unknown, never negative infinity; empty/reversed intervals reject (§1).
   c. Effective and recorded time independent; `observed_at`, `source_updated_at`, `published_at` distinct (§1, §2).
   d. `TemporalDisposition`, `TemporalReason` closed literals with at least the nine named reasons (§2).
   e. `resolve_selector`: explicit `known_at` wins; otherwise injected latest cutoff; compare returns ordered pair; contradictory snapshot IDs/cutoffs raise (§2).
   f. Predicates: recorded eligibility `recorded_from <= known_at < recorded_to`; `as_of` proven only inside sufficiently bounded interval; unknown/observed_snapshot contextual after recorded eligibility; `atemporal` rules; `during/overlaps` vs `during/throughout`; unknown lower cannot prove either; `current` uses injected cutoff; `changes` clock selection rules (`published`, `source_modified`, `effective`); imprecise change clocks contextual (§2).
   g. `match_temporal` deterministic and side-effect free; compare evaluates each side independently (§2).
   h. `serialize_temporal_evidence` emits original text/tz/precision plus UTC fields; unknowns null plus kind/precision; no natural-language date resolution (§2).
   i. `SourceOrder`/`OrderingKind`/`OrderingRelation` as specified; generic code never lexically or numerically sorts provider tokens (§3).
   j. `ConflictCandidate` validation: one workspace, matching assertion/version IDs, nonempty unique support (§3).
   k. `select_same_source` grouping key exactly `(source_id, adapter, series key, workspace, subject, predicate, scope)`; unique greatest monotonic ordinal wins; equal ordinals / equality-only / unknown remain alternatives; `recorded_from`, `observed_at`, list order NEVER tie-break; duplicate IDs collapse (§3).
   l. `build_conflict_sets`: cardinality supplied by caller; groups never cross scope; `multiple` compatible; `single` conflict when overlap proven (`unresolved`) or unprovable (`possible`); explicit non-overlap no set; interval = exact intersection or null/null; IDs sorted unique; never emits `resolved`/`dismissed` (§3).
   m. No store reads, model calls, or ambient clock calls in either module: `rg -n "datetime.now|utc_now|time\(\)|store\.|ollama|httpx" src/hippo/knowledge/temporal.py src/hippo/knowledge/conflicts.py` must be empty or justified.
   n. Fixture `temporal_events.jsonl` covers all nine scenarios in §7 step 3 (May ownership correction, imported-old-last, equal timestamp/different bytes, unknown date, environment collision, independent-source alternatives, ordinary tombstone, all-history purge, explicit restoration barrier). List which are present and which are missing.
3. QUALITY review: mutable fields inside frozen dataclasses; validation that happens in `__post_init__` vs silently skipped for alternate constructors; duplicated interval math; tests that only exercise happy paths for items b, f, k, l; any ordering that depends on dict/set iteration.
4. Note anything in the modules that already reaches into §4–§6 territory (history service, publication plan, store changes). It should not exist yet.

DONE WHEN:
- `ai_docs/reports/2026-09-11-temporal-pure-review.md` exists with: `SPEC: PASS|FAIL`, `QUALITY: PASS|FAIL`; the a–n table; numbered findings with severity (blocker / major / minor), file:line, why, proposed fix; gate results with log paths; the fixture coverage list from item n.
- EVIDENCE lines recorded for T5A1, T5A2, T5A6.
- `horch done` summary states both verdicts, finding counts by severity, missing fixture scenarios, and the report path.

CONSTRAINTS: no source/test/fixture edits; no Neo4j; no Ladybug runs needed (the pure tests are backend-independent; run them with `HIPPO_TEST_STORE=fake`).

REPORT: `horch note` after gates run, after the SPEC table, after the report. `horch tell orchestrator "[<role>] BLOCKED: ..."` only if a command cannot run.
