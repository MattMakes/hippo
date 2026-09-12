# Task 5A — chronological JSONL fixture loading

Worker `opus-10`, branch `wp/t5afix`, base `79e379a` (`rag-it-all-tibs`). Contract:
`ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` section 6 (last bullet) and
section 7 step 3, driven through the part 1 and part 2 APIs recorded in
`evidence-int1.md` and `evidence-int2.md`.

Scope delivered: the loader, the nine end-to-end scenario tests, retry idempotence and a
real Ladybug close/reopen. NOT delivered: the disposable-Neo4j repeat (root), the
independent SPEC/QUALITY review of this increment, and any change to `GATES.md`
(see "Decisions and deviations", item 8).

## Files

| File | Change |
|---|---|
| `src/hippo/evals/rag_all_temporal.py` | NEW. The loader, kept apart from `rag_all.py`. |
| `tests/unit/test_temporal_fixture_loader.py` | NEW. 20 tests; `-k fixture_loader` selects all of them by filename. |
| `tests/fixtures/rag_all/README.md` | New "Temporal event log" section: the JSONL contract, what the loader does with each row shape, and the conventions the rows do not carry. |
| `tests/fixtures/rag_all/temporal_events.jsonl` | **Unchanged** in this increment; see "Fixes after review" for the two rows the review's F5 and F6 added. |
| `src/hippo/evals/rag_all.py` | **Unchanged.** Task 4d's `retrieval_session` work was not touched. |

The loader is a new module rather than an addition to `evals/rag_all.py`: that module
validates a corpus allow-list and runs legacy retrieval scoring, and shares no code path
with replaying recorded knowledge events. Keeping them apart also keeps this increment
clear of the session/dispatch code Task 4d changed.

## Signatures

```python
# src/hippo/evals/rag_all_temporal.py
class TemporalFixtureError(ValueError)            # a row cannot be read as a recorded event

@dataclass(frozen=True) TemporalEvent(
    index, case, kind,                            # kind: "claim" | "suppression" | "barrier"
    source_name, recorded_from,
    scope_key=DEFAULT_SCOPE_KEY, order: SourceOrder | None = None,
    predicate=None, object_name=None, valid_from=None, valid_to=None,
    precision="unknown", source_updated_at=None, source_precision="unknown",
    content_hash=None, source_timestamp_original=None, source_timezone=None,
    view_applicability=None, reason=None, epoch=None, restoration_barrier=None)
    .validity_kind -> "explicit_interval" | "unknown"
    .temporal_basis -> "source_explicit" | "unknown"

@dataclass(frozen=True) LoadedClaim(event, generation_id, revision_id, span_id,
    assertion: k.Assertion, version: k.AssertionVersion,
    candidate: ConflictCandidate, closed_version_ids: tuple[str, ...])

@dataclass(frozen=True) TemporalLoad(workspace_id, applied, deferred, claims,
    source_ids, suppressions, barriers, events)
    .claim(case) / .claims_for(case) / .barrier(case)
    .candidates          -> tuple[ConflictCandidate, ...]
    .current_candidates  -> select_same_source(self.candidates).current

read_temporal_events(path: str | Path) -> tuple[TemporalEvent, ...]
load_temporal_events(store, path: str | Path, *, clock: Callable[[], datetime]) -> TemporalLoad
```

Module constants a reviewer should see: `SUBJECT_KIND="service"`,
`SUBJECT_NAME="service-a"`, `OBJECT_KIND="owner"`,
`DEFAULT_SCOPE_KEY="service-a:production"`, `RULE_VERSION="rag-all-temporal-v1"`,
`DEFAULT_BARRIERS={"tombstone":"refetch","access_loss":"reverify","purge":"destroy"}`.

## Behavior to test map (brief's REQUIRED BEHAVIOR order)

Every test lives in `tests/unit/test_temporal_fixture_loader.py`; the filename carries
`fixture_loader`, so one `-k fixture_loader` term selects the whole file.

| # | Behavior | Test |
|---|---|---|
| 1 | Rows read in row order, sorted to chronological `recorded_from` order, every instant aware UTC, original text/zone/precision preserved | `test_every_row_instant_is_parsed_as_an_aware_utc_value_in_recorded_order` |
| 1 | A naive, missing or unparseable required instant is refused, never defaulted | `test_a_naive_or_missing_instant_is_refused_instead_of_defaulted` (4 cases) |
| 1 | No `datetime.now` / `utc_now` anywhere in the loader | `test_the_loader_reads_no_wall_clock_anywhere` |
| 1 | The caller's clock is the only time input and bounds which events have happened | `test_the_caller_clock_bounds_which_recorded_events_are_applied` |
| 2.1 | May ownership correction: original before the cutoff, corrected after; the prior segment is closed by a `TemporalPublicationPlan`, never rewritten | `test_may_ownership_correction_shows_the_original_before_and_the_correction_after`, `test_the_corrected_segment_keeps_its_bounded_effective_interval` |
| 2.2 | Imported-old-last supersedes nothing | `test_an_old_import_arriving_last_supersedes_nothing` |
| 2.3 | Equal ETag / equal source timestamp with different bytes stay ambiguous and request refetch | `test_an_equal_ordering_datum_with_different_bytes_stays_ambiguous` (2 cases) |
| 2.4 | Unknown date is contextual, never time-proven | `test_an_unknown_date_is_contextual_and_never_time_proven` |
| 2.5 | Environment collision: distinct scopes, no conflict | `test_distinct_environment_scopes_never_form_one_conflict` |
| 2.6 | Independent-source alternatives are support, not conflict | `test_independent_source_alternatives_support_each_other` |
| 2.7 | Ordinary tombstone hides the current view and keeps history | `test_an_ordinary_tombstone_hides_the_current_view_and_keeps_history` |
| 2.8 | All-history purge denies the retained history a tombstone would keep | `test_an_all_history_purge_denies_the_retained_history_a_tombstone_would_keep` |
| 2.9 | Explicit restoration barrier | `test_the_explicit_restoration_barrier_is_what_a_restoration_must_satisfy` |
| 3 | Loading the same fixture twice into one store is an exact retry | `test_loading_the_same_fixture_twice_writes_nothing_new` |
| 3 | Loading into Ladybug and reopening preserves the loaded history | `test_loaded_history_survives_a_ladybug_close_and_reopen` |

## Commands and results

Baseline, `/tmp/hippo-t5afix-baseline.log` (worktree `t5afix`, base `79e379a`, both new
files moved out of the tree first so the ledger commands ran against the unchanged base):
T5A1 69 passed, T5A2 32 passed, T5A3 48 passed/53 deselected, T5A5 213 passed/1 skipped,
`test_rag_eval.py test_rag_eval_session.py` 59 passed, T5A6 clean (11 files already
formatted), T5A4 (Ladybug) 48 passed/53 deselected in 71.69s; every command exit 0.

RED log `/tmp/hippo-t5afix-red.log`, written before the module existed: collection fails
with `ModuleNotFoundError: No module named 'hippo.evals.rag_all_temporal'`, exit 2.

GREEN Fake, `/tmp/hippo-t5afix-fake-green.log`, every command with `-o addopts='' -W error`:

| Command | Result |
|---|---|
| `HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_temporal_evidence.py` (T5A1) | exit=0; 69 passed in 0.68s |
| `HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_temporal_conflicts.py` (T5A2) | exit=0; 32 passed in 0.04s |
| `HIPPO_TEST_STORE=fake ... test_temporal_evidence.py test_temporal_conflicts.py test_temporal_fixture_loader.py -k 'history_manifest or recorded_correction or suppression_history or purge_history or fixture_loader'` (T5A3 extended) | exit=0; 68 passed, 53 deselected in 16.18s |
| `HIPPO_TEST_STORE=fake ... test_knowledge_contracts.py test_store_knowledge.py test_evidence_access.py test_generation_store.py test_snapshot_store.py test_generation_graph_loader.py` (T5A5) | exit=0; 213 passed, 1 skipped in 5.66s |
| `HIPPO_TEST_STORE=fake ... test_rag_eval.py test_rag_eval_session.py test_managed_eval_activation.py` | exit=0; 76 passed in 5.18s |
| `HIPPO_TEST_STORE=fake ... test_temporal_fixture_loader.py` | exit=0; 20 passed in 15.69s |
| T5A6 command (unchanged file list) | exit=0; All checks passed! / 11 files already formatted |

GREEN Ladybug, `/tmp/hippo-t5afix-ladybug-green.log`:

| Command | Result |
|---|---|
| `HIPPO_TEST_STORE=ladybug ... test_temporal_evidence.py test_temporal_conflicts.py test_temporal_fixture_loader.py -k 'history_manifest or recorded_correction or suppression_history or purge_history or fixture_loader'` (T5A4 extended) | exit=0; 68 passed, 53 deselected in 237.47s |
| `HIPPO_TEST_STORE=ladybug ... test_temporal_fixture_loader.py` | exit=0; 20 passed in 189.43s |

Ruff, on both files this worker created:

```
.venv/bin/ruff check  src/hippo/evals/rag_all_temporal.py tests/unit/test_temporal_fixture_loader.py
.venv/bin/ruff format --check src/hippo/evals/rag_all_temporal.py tests/unit/test_temporal_fixture_loader.py
-> All checks passed! | 2 files already formatted   (exit 0)
```

No test touched application data, port 8011, `.rag-dev-data/` or Ollama. No
`filterwarnings` was added and no sanctioned-warning exception was needed: neither new
file imports `fastapi.testclient`, and the Ladybug reopen test builds its own
`LadybugStore` under `tmp_path`, as `test_generation_store.py` already does.

## Decisions and deviations worth a reviewer's attention

1. **Closure comes from the ordering metadata, not from a row naming a target.** No row
   names the segment it corrects, so the loader derives it: for each claim publication it
   runs `select_same_source` over every loaded candidate, takes
   `fully_superseded_version_ids`, and keeps only this source's own still-open segments
   recorded strictly before this instant. Mechanically that means `may_owner_bob`
   (ordinal 2) closes `may_owner_alice` (1), `backdated_correction` (3) closes
   `may_owner_bob`, and `old_imported_last` (1, arriving last) closes nothing.
   Supersession in section 3 is ordinal-only, so closing Bob is what the adapter's
   declared order says; both closed segments remain queryable at a cutoff before their
   closure, which is the "original before, corrected after" the scenario asks for. This
   lives in one function (`_closures`) so a redirect is local.
2. **`SourceOrder.series_key` is the fixture source name.** The fixture's
   `provider_order` carries no series, and the object must *not* enter it: `_series_key`
   already adds workspace/subject/predicate/scope, and putting the claimed object in the
   series would split the equal-token pairs into two one-member series and lose the
   ambiguity the scenario exists to prove.
3. **A row without `scope_key` claims `service-a:production`.** The rows name no subject
   and mostly no scope; the loader supplies subject `service-a` and this default. It is
   what makes `environment_collision`'s declared `service-a:staging` a genuinely distinct
   scope and `independent_alternative` a genuine same-scope alternative rather than an
   unrelated claim.
4. **`rule_version` is per source (`rag-all-temporal-v1:<source>`).** Two sources stating
   an identical undated claim at the same instant otherwise produce one
   `AssertionVersion` id — which section 3 explicitly allows — but the store refuses
   `Sealed assertion proof group cannot gain support` once the first publication sealed
   it. Cross-source corroboration is therefore expressed as separate candidates over the
   same `Assertion`, which is what scenario 6 asserts.
5. **A barrier row writes nothing of its own.** `Suppression` is immutable and
   `restoration_barrier` is not in `MUTABLE_FIELDS`, so a later row cannot stamp a barrier
   onto a committed suppression. Barrier rows are resolved from the whole file *before*
   any suppression is written; a source with no barrier row gets a per-reason default.
   This is also what keeps an incremental replay idempotent: the tombstone written at the
   May 15 clock is byte-identical to the one a May 18 clock would write. There is no
   un-suppress path in the store, so "applying" the barrier means recording the token a
   confirmed restoration would have to satisfy; the test additionally proves an ordinary
   later arrival (`old_imported_last`, ordinal 1) is `older` than the confirmed
   restoration (ordinal 9) and so can never stand in for it.
6. **`old_imported_last` reuses the `ArtifactRevision` it re-imports.** Its
   `provider_order.token` is `rev-a`, the same bytes as `may_owner_alice`, and a revision
   is identified by artifact + provider revision + content hash. A re-import is the same
   revision observed once, not a second copy observed later, so the loader reuses the
   stored row; it gets its own span, observations and version, and its own
   `GenerationMember` in its own generation.
7. **The loader lends the store the row's own instant.** `GenerationQueries._now()` is the
   one ambient clock a publication reads (build-lease validity). `_generation_window`
   sets `store._generation_clock` to the instant of the row being applied and restores the
   previous value afterwards — the same injection `tests/unit/test_temporal_evidence.py`
   uses. Without it a 2026-05 lease would be judged against whenever the replay runs. This
   is the only private store attribute the loader writes; it reads `_knowledge_get` to
   detect an already-published generation and an existing revision.
8. **`GATES.md` was not edited.** The brief allows an EVIDENCE line on T5A3/T5A4, but
   commit `7d5984f` established one EVIDENCE line per Task 5A gate, and extending those
   gates also requires their CHECK lines to gain the new file and `-k` term, which the
   orchestrator maintains. The verified replacements are below, ready to apply.
9. **A purged source contributes no manifest revisions, so scenario 8 is proved on the
   proof, not on markers.** `_revision_closure` reaches revisions from *proven* rows only,
   and `unknown_date` is contextual by construction, so its revision never enters a
   `HistoryManifest` and `purged_history_evidence` can never name it. The test instead
   proves the contrast the plan states: before the purge the version is in the contextual
   inventory and its revision is in `HistorySelection.broad`; after it, neither — while
   the `current_only` tombstone in scenario 7 left catalog's history fully selectable.
10. **The clock is a bound, not a stamp.** `load_temporal_events` applies events recorded
    at or before `clock()` and returns the rest in `deferred`. That is what makes the
    incremental replay in scenario 8 possible (load to the tombstone, pin a selection,
    load on to the purge) and it is the only thing the caller's clock decides.

## Proposed `GATES.md` update (verified, not applied)

T5A3:

```
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_temporal_evidence.py tests/unit/test_temporal_conflicts.py tests/unit/test_temporal_fixture_loader.py -k 'history_manifest or recorded_correction or suppression_history or purge_history or fixture_loader' -q -o addopts='' -W error
  EVIDENCE: complete (fixture_loader half added by the chronological JSONL loader); exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo/.worktrees/t5afix; branch=wp/t5afix; output=68 passed, 53 deselected in 16.18s; supersedes the integration part 2 line (48 passed, its detail is preserved in evidence-int2.md); the 20 new cases load tests/fixtures/rag_all/temporal_events.jsonl chronologically from explicit parsed instants and adapter ordering metadata and exercise all nine section 7 step 3 scenarios end to end plus retry idempotence and a Ladybug reopen; detail=ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/evidence-fixture.md
```

T5A4:

```
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_temporal_evidence.py tests/unit/test_temporal_conflicts.py tests/unit/test_temporal_fixture_loader.py -k 'history_manifest or recorded_correction or suppression_history or purge_history or fixture_loader' -q -o addopts='' -W error
  EVIDENCE: complete (fixture_loader half added by the chronological JSONL loader); exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo/.worktrees/t5afix; branch=wp/t5afix; output=68 passed, 53 deselected in 237.47s; supersedes the integration part 2 line (48 passed, its detail is preserved in evidence-int2.md); real close/reopen of a fixture-loaded history covered by tests/unit/test_temporal_fixture_loader.py::test_loaded_history_survives_a_ladybug_close_and_reopen, which builds its own LadybugStore under tmp_path; detail=ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/evidence-fixture.md
```

## Remaining for Task 5A

- The disposable-Neo4j repeat of the T5A3 publication/CAS/conflict cases, run by root.
- The independent SPEC/QUALITY review of integration part 2 and of this increment.
- Applying the `GATES.md` lines above.

## Fixes after review (worker `opus-14`, root tree at `2ac0794`, 2026-09-12)

Review: `ai_docs/reports/2026-09-12-t5a-fixture-review.md` (F1-F10 and the convention
table). Decisions: `ai_docs/handoffs/briefs/fix-t5a-fixture.md`, with three refinements
the orchestrator gave in session - F5 takes the review's *preferred* option (one added
catalog row, no post-replay closure machinery), F6 *adds* a purge row rather than
retargeting the existing one, and convention 5 takes F7's minimal fix rather than
resolving barriers from applied events only. F8-F10 were declared optional: their code
is unchanged and each is recorded below as a known gap, with F10's one-sentence README
clarification taken because it costs nothing and makes scenario 9's intent explicit.
The loader suite grew from 20 cases to 37. No commits: the orchestrator commits.

Two signature changes since the block above: `TemporalLoad` gains
`declarations: tuple[TemporalEvent, ...]` (barrier rows, see convention 5), and
`_timezone_label(text)` no longer takes the parsed instant. `temporal_events.jsonl` is
no longer unchanged: it gains exactly two rows, `restated_new_state` and
`purged_proven_history`. The nine scenarios and every existing case label are intact.

### Per finding

| # | Change | Test |
|---|---|---|
| F1 | `rag_all_temporal.py:205,223`: a row with no `valid_from` declares no source timestamp, so `source_timestamp_original`/`source_timezone` stay `None` instead of taking the recorded instant. | `test_an_unknown_date_serializes_as_null_rather_than_hippos_own_clock` - the serialized evidence carries null text, null zone, null `valid_from` and precision `unknown`, the stored `ObjectObservation` rows carry the same nulls, and a dated row still reports `2026-04-01T00:00:00Z` / `UTC`. |
| F2 | `rag_all_temporal.py:144-155`: `_timezone_label` reads the offset from the provider's own text instead of from the already-normalized instant, and renders it canonically, so the dead `text[-6:]` branch is gone and `+0200` and `+02:00` label alike. | `test_a_declared_offset_survives_while_the_computed_instant_is_utc`, 4 cases (`+02:00`, `+0200`, `-05:00`, `Z`): the instant is the UTC one, the text and the label are the declared ones. |
| F3 | `rag_all_temporal.py:66,239-244` validate both closed sets at parse time; `:271-284` (`_event`) names the row index on every parse refusal; `:784-789` turns a `ValidationError` from the knowledge model into a `TemporalFixtureError` naming the row it came from. | `test_every_malformed_row_is_a_fixture_error_naming_its_row_index`, 5 cases (bad reason, bad view applicability, missing `epoch`, missing `precision`, malformed `claim`), each also asserting `row 0` in the message; `test_a_row_the_knowledge_model_refuses_is_reported_as_a_fixture_error` for the model's own refusal at load time. |
| F4 | `rag_all_temporal.py:287-317` (`_ordered`) resolves a tie inside one series by the adapter's ordinal and refuses a tie on both instant and ordinal; `:616-620` raises instead of dropping a closure the ordering proves but section 5 cannot express. The tiebreak is deliberately **per series**, not global: `compare_orders` is `ambiguous` across adapters and series, so sorting two sources' ordinals against each other would be an order no adapter declared. A cross-source tie therefore keeps file order: no shipped row's position in the replay changed, because no two monotonic rows of one source share an instant in this fixture. | `test_one_instant_twice_in_a_series_is_ordered_by_ordinal_and_never_drops_a_closure` (both file orders, so the tiebreak itself is what is proved), `test_two_rows_tying_on_both_instant_and_ordinal_are_refused_as_ambiguous`. |
| F5 | Fixture row `restated_new_state` (catalog, ordinal 4, `rev-d`, effective `[2026-05-01, open)`, recorded `2026-05-13T06:00Z`). No loader change: the ordinal rule was already the mechanism. | `test_the_replay_ends_with_the_highest_ordinal_as_the_catalogs_only_proven_claim` pins the post-replay end state; `test_an_old_import_arriving_last_supersedes_nothing` keeps the conflict-API half. The end-state pin is taken at `as_of 2026-05-20 / known_at 2026-05-13T12:00Z` rather than the review's `known_at 2026-05-18`, because the catalog series records nothing after `2026-05-13T06:00Z` and the earlier cutoff keeps the test's own load clock; the May 18 end of the same story is covered by the scenario 8 test at `as_of 2026-05-20 / known_at 2026-05-16T12:00Z` and by the Ladybug reopen. |
| F6 | Fixture row `purged_proven_history` (`accepted-prd`, `all_history`, `purge`, epoch 7, recorded `2026-05-16T18:00Z`), added beside the contextual purge rather than replacing it. | `test_an_all_history_purge_of_a_proven_source_answers_with_purge_markers`: the revision is in the pinned manifest, `EVERYTHING` and an enabled workspace reader both get exactly one `("revision", ..., "evidence_purged")` marker with no text attribute, a revoked reader gets `SnapshotUnavailable`, and the claim is gone from both proof inventories afterwards. |
| F7 | `rag_all_temporal.py:359-366` (`TemporalLoad.declarations`), `:755-761` and the `load_temporal_events` docstring: the carve-out is stated where a reader meets it, and a barrier row is no longer reported as `deferred` while its content is in force. | `test_a_barrier_row_is_a_declaration_the_clock_does_not_bound` at a May 15 clock; `test_the_caller_clock_bounds_which_recorded_events_are_applied` asserts the barrier is in neither list. |

### What the two fixture rows change about the replay

Ordinal-only closure closes *every* lower-ordinal open segment of the series, so the
ordinal-4 restatement closes both `old_imported_last` and `backdated_correction` in one
publication at `2026-05-13T06:00Z`. The corrected April segment is therefore
recorded-closed from that instant and stays proven at any earlier `known_at` - which is
what section 3's "remains queryable in history" means and what
`test_the_replay_ends_with_the_highest_ordinal_as_the_catalogs_only_proven_claim` and
the scenario 7 test both assert. Scenarios 7 and 8 consequently prove retained history
through the catalog's open restated claim (and, for the April segment, through a cutoff
before its closure) instead of through a segment that is now closed. The end state the
review asked for holds: after 2026-05-01 the catalog proves the ordinal-4 claim and
nothing else, and the re-import that arrived last is history.

### F8-F10, declared optional and recorded rather than applied

Left exactly as the review found them, so a later slice knows they are known and not
overlooked:

- **F8**: `(precision == "instant") != (valid_from is not None)` is a biconditional, so
  only `instant` and `unknown` are reachable and no fixture row can carry a coarse
  effective bound. `effective_imprecise` - the contextual reason section 2 was amended
  to add - therefore has no end-to-end proof here. Relaxing the rule to "an explicit
  bound requires a precision, and `unknown` forbids one" plus a `day`-precision row
  would close it; no scenario in step 3 asks for it, and widening the rule that keeps an
  unknown time from becoming a dated claim is not a change to make as a side effect.
- **F9**: `workspace_id` is a loop-level variable rather than `_SourceState` state, so a
  source in a different workspace would have its records written against the previous
  source's workspace. Unobservable today - every fixture source lands in the default
  workspace - and it stays a latent trap until a fixture needs two workspaces.
- **F10**: a barrier row's `SourceOrder` sits in its source's claim series. Nothing
  breaks, because a barrier row never becomes a `ConflictCandidate`; it is what makes
  scenario 9's `compare_orders(imported, barrier)` well defined, and the fixture README
  now says so deliberately rather than leaving it to coincidence.

### The ten conventions, after the redirects

| # | Outcome |
|---|---|
| 1 | **REDIRECTED.** The mechanism stands; the claim does not. Closure follows the adapter ordinal alone: a publication closes every same-series open segment with a lower ordinal, and a claim arriving with a lower ordinal than an open segment closes nothing and stays recorded-open as retained history, its currentness decided by `select_same_source` rather than by recorded intervals. The fixture now carries the new state, so the May example appends the corrected historical segment *and* a claim about what holds after it. |
| 2 | ACCEPT, unchanged. `SourceOrder.series_key` is the source name. |
| 3 | ACCEPT, unchanged. Subject `service-a`, object kind `owner`, `DEFAULT_SCOPE_KEY="service-a:production"`. |
| 4 | ACCEPT, unchanged. Per-source `rule_version`. |
| 5 | **REDIRECTED.** Barrier rows stay pre-resolved from the whole file, because `restoration_barrier` is immutable and a later row could not stamp a committed `Suppression` - but the carve-out is now stated rather than implied: it is written into the `load_temporal_events` docstring and the fixture README, a barrier row is reported in `declarations` instead of contradicting itself in `deferred`, and a test at a pre-barrier clock pins that the May 15 tombstone already carries `confirmed:9`. |
| 6 | ACCEPT, unchanged. Revision reuse on re-import. |
| 7 | ACCEPT with the review's correction applied here, superseding the wording of item 7 above (left in place as the record of what was originally decided): the loader is the **first `src/` writer** of `store._generation_clock` - the other 15 writers are all test modules - not "the same injection the tests use". It should become a public clock injection when section 6 releases `store/generations.py`. |
| 8 | ACCEPT (moot), with one deliberate departure: this worker's brief owns the `EVIDENCE:` lines for T5A3/T5A4, so those two lines - and only those two - were edited in `GATES.md`. The CHECK lines and every checkbox are the orchestrator's and were not touched. |
| 9 | **REDIRECTED.** Scenario 8 still proves denial on the broad proof for the contextual `prd` purge, and the added `accepted-prd` purge now proves the marker half of section 4 end to end. |
| 10 | ACCEPT, unchanged, with convention 5's carve-out named as the one exception. |

### Commands and results

Baseline first, at `2ac0794` with nothing changed: T5A3 exit=0, 77 passed / 53
deselected in 12.52s (`/tmp/hippo-t5afixfix-baseline-t5a3.log`); T5A4 exit=0, 77 passed
/ 53 deselected in 179.39s (`/tmp/hippo-t5afixfix-baseline-t5a4.log`).

RED, `/tmp/hippo-t5afixfix-red.log`: exit=1, **15 failed, 22 passed** - F1 (1), F2 (3),
F3 (6), F4 (3), F7 (2). The F5 and F6 tests passed in the RED run, which is honest and
expected: both are fixture-modeling decisions whose mechanism already existed, so their
rows were written before the run and only the loader findings were red.

GREEN, every command with `-q -o addopts='' -W error` and an explicit `HIPPO_TEST_STORE`:

| Command | Result | Log |
|---|---|---|
| fake: `test_temporal_fixture_loader.py` | exit=0; 37 passed in 18.30s (was 20) | `/tmp/hippo-t5afixfix-green1.log` |
| fake: T5A3 verbatim from the ledger | exit=0; 94 passed, 53 deselected in 21.98s | `/tmp/hippo-t5afixfix-fake-green.log` |
| ladybug: T5A4 verbatim from the ledger | exit=0; 94 passed, 53 deselected in 285.13s | `/tmp/hippo-t5afixfix-ladybug-green.log` |
| fake: T5A5 verbatim from the ledger | exit=0; 213 passed, 1 skipped in 6.20s | `/tmp/hippo-t5afixfix-fake-t5a5.log` |
| fake: `test_rag_eval.py test_rag_eval_session.py` | exit=0; 59 passed in 4.59s | `/tmp/hippo-t5afixfix-fake-rageval.log` |
| T5A6 verbatim from the ledger | exit=0; All checks passed! / 11 files already formatted | - |
| `ruff check` + `ruff format --check` on both changed source files | exit=0; All checks passed! / 2 files already formatted | - |

No sanctioned-warning filter was needed: every command ran under plain `-W error`, and
the one module this file now imports from `tests/` (`test_store_knowledge.reader`) is
the same import `test_temporal_evidence.py` already makes. No test touched application
data, port 8011, `.rag-dev-data/` or Ollama, and no Neo4j was used.

One pre-existing finding, not introduced here and not fixed here: `ruff format --check
tests/fixtures/rag_all/README.md` fails on the optional live-model recipe's Python
block, byte-identically at `HEAD` before this change (verified against
`git show HEAD:tests/fixtures/rag_all/README.md`). The prose added by this change
contains no Python fence. Reformatting that block is a one-line-range change the
orchestrator may want, but it is unrelated to any finding here.
