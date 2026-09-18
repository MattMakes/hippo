# Task 5A integration part 2 — append-only correction publication and per-series supersession

Worker `opus-8`, branch `wp/t5a2`, base `9980961`. Contract:
`ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` sections 1, 5 and 6 including the
`Amended 2026-09-12 in integration part 2` notes this worker added to section 5.

Scope delivered: plan section 5 in full, the section 6 changes it needs in
`store/generations.py` and `store/knowledge.py`, and the pure re-review minor N2 in
`knowledge/conflicts.py`. NOT delivered (deferred by the brief): chronological JSONL fixture
loading (its loader is owned by Task 4d) and the disposable-Neo4j repeat (root).

## Signatures

```python
# src/hippo/knowledge/temporal.py
@dataclass(frozen=True) RecordedSegment(record_kind: TemporalRecordKind, record_id: str)
    # record_kind is "ObjectObservation" | "AssertionVersion"; anything else raises

@dataclass(frozen=True) TemporalPublicationPlan(
    published_at: datetime,
    closures: tuple[RecordedSegment, ...],
    appends: tuple[RecordedSegment, ...] = (),
)
    .fingerprint -> str    # text_hash over published_at + both ID lists

# src/hippo/knowledge/conflicts.py
@dataclass(frozen=True) SameSourceSelection(current, superseded_version_ids, ambiguous_series,
                                            superseded_by_series=())     # last field is new (N2)
fully_superseded_version_ids(selection: SameSourceSelection) -> tuple[str, ...]      # new (N2)

# src/hippo/store/knowledge.py
CLOSABLE_RECORD_KINDS = ("AssertionVersion", "ObjectObservation")
KnowledgeQueries._close_recorded_intervals(segments, *, recorded_to: datetime) -> tuple[str, ...]
KnowledgeQueries._authorized_recorded_closure(record, existing) -> bool

# src/hippo/store/generations.py
GenerationQueries.publish_staged_generation(generation_id, *, expected_parent_id, job_id,
    lease_owner, fencing_token, expected_suppression_epoch, published_at,
    plan=None, fault_hook=None)                                   # `plan` is new
GenerationQueries.publish_generation(generation_id, *, expected_parent_id, published_at,
    plan=None, fault_hook=None)                                   # `plan` is new and always rejected
GenerationQueries._validate_publication_plan(gen, plan)           # read-only, before any write
GenerationQueries._observe_recorded_closures(plan)                # read-only, retry path
GenerationQueries._plan_row / _plan_lineage / _plan_series        # validation helpers
```

## Behavior to test map (brief's REQUIRED BEHAVIOR order)

All new tests carry `recorded_correction` in the name, so the T5A3/T5A4 `-k` selects every one
that lives in the two temporal test files.

| # | Behavior | Test |
|---|---|---|
| 1 | Frozen, canonical, sorted, unique, disjoint plan with no callbacks | `test_recorded_correction_plan_is_frozen_canonical_and_disjoint` |
| 2 | Closure target exists / workspace / source lineage through complete support / open / `recorded_from < published_at` / not already closed | `test_recorded_correction_refuses_a_closure_target_it_cannot_prove` (5 cases: `closed`, `foreign`, `unsupported`, `not_before`, `missing`) |
| 2 | Appended segment is an exact member, `recorded_from == published_at`, preserves series and evidence dependencies; observation corrections obey the equivalent object closure | `test_recorded_correction_refuses_an_append_outside_the_staged_correction` (3 cases), `test_recorded_correction_closes_the_prior_segment_and_appends_the_corrected_one` (closes and appends one assertion version **and** one object observation) |
| 3 | One transaction closes, appends, publishes/retires, advances state, writes the event; a failpoint rolls everything back | `test_recorded_correction_rolls_back_every_write_when_a_failpoint_fires` (6 positions), `test_recorded_correction_closes_the_prior_segment_and_appends_the_corrected_one` |
| 4 | Exact retry returns the receipt and observes the closures; a different plan, stale parent, later suppression epoch fail without writes | `test_recorded_correction_retry_returns_the_original_receipt_and_observes_the_closures`, `test_recorded_correction_retry_with_a_different_plan_fails_without_writing`, `test_recorded_correction_fails_without_writes_on_a_stale_parent_or_a_later_suppression` |
| 5 | No unguarded clock: `published_at` comes from the plan | `test_recorded_correction_requires_the_plan_clock_to_be_the_publication_clock` |
| 6 | The fixture compatibility path is not a bypass | `test_recorded_correction_is_refused_by_the_generic_fixture_publication_path`, `test_recorded_correction_never_reaches_a_published_row_through_update_knowledge` |
| 7 | `select_history` returns the original segment before the correction and the corrected one after; `recorded_to` serializes | `test_recorded_correction_is_visible_to_history_selection_at_each_cutoff` |
| N2 | `superseded_version_ids` names a version once; supersession is keyed per series | `test_recorded_correction_supersession_names_each_version_once_per_series`, `test_recorded_correction_supersession_is_keyed_by_series_not_globally` |
| — | Real close/reopen after a correction publication | `test_recorded_correction_survives_a_ladybug_close_and_reopen` (`tests/unit/test_generation_store.py`, builds its own `LadybugStore` under `tmp_path`) |

Failpoint positions exercised: `closure` (new, fired after every closure and before
`_publish_generation`), `pointer`, `version`, `retirement`, `event`, `lease`. After each one the
closed rows are open again, generation one is `active`, generation two is `ready`, the source
pointer and the build job are unchanged, and `content_epoch` is where it started.

## Commands and results

Baseline before any change (worktree `t5a2`, base `9980961`):
`/tmp/hippo-t5a2-baseline-fake.log` (T5A1 46, T5A2 30, T5A3 23, T5A5 211 passed 1 skipped, all
exit 0) and `/tmp/hippo-t5a2-baseline-ladybug.log` (T5A4 23 passed, T5A6 clean).

RED log `/tmp/hippo-t5a2-red.log`, written before any implementation: the new tests fail at
collection with `ImportError: cannot import name 'RecordedSegment' from 'hippo.knowledge.temporal'`
and `test_recorded_correction_survives_a_ladybug_close_and_reopen` fails on the same import,
`1 failed, 34 deselected`.

GREEN Fake, `/tmp/hippo-t5a2-fake-green.log`, every command with `-o addopts='' -W error`:

| Command | Result |
|---|---|
| `HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_temporal_evidence.py` (T5A1) | exit=0; 69 passed in 0.79s |
| `HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_temporal_conflicts.py` (T5A2) | exit=0; 32 passed in 0.04s |
| `HIPPO_TEST_STORE=fake ... test_temporal_evidence.py test_temporal_conflicts.py -k 'history_manifest or recorded_correction or suppression_history or purge_history'` (T5A3) | exit=0; 48 passed, 53 deselected in 0.81s |
| `HIPPO_TEST_STORE=fake ... test_knowledge_contracts.py test_store_knowledge.py test_evidence_access.py test_generation_store.py test_snapshot_store.py test_generation_graph_loader.py` (T5A5) | exit=0; 212 passed, 1 skipped in 7.82s |
| `HIPPO_TEST_STORE=fake ... test_generation_store.py test_prose_generation.py test_managed_pipeline_activation.py test_snapshot_store.py test_query_snapshots.py` | exit=0; 188 passed, 1 skipped in 27.57s |

GREEN Ladybug, `/tmp/hippo-t5a2-ladybug-green.log`:

| Command | Result |
|---|---|
| `HIPPO_TEST_STORE=ladybug ... test_temporal_evidence.py test_temporal_conflicts.py -k 'history_manifest or recorded_correction or suppression_history or purge_history'` (T5A4) | exit=0; 48 passed, 53 deselected in 117.60s |
| `HIPPO_TEST_STORE=ladybug ... test_generation_store.py` | exit=0; 35 passed in 26.13s |

Ruff, on every file this worker changed and on the T5A6 file list:

```
.venv/bin/ruff check  src/hippo/knowledge/temporal.py src/hippo/knowledge/conflicts.py \
  src/hippo/store/generations.py src/hippo/store/knowledge.py \
  tests/unit/test_temporal_evidence.py tests/unit/test_temporal_conflicts.py \
  tests/unit/test_generation_store.py
.venv/bin/ruff format --check <same list>
-> All checks passed! | 7 files already formatted   (exit 0)
T5A6 command -> All checks passed! | 11 files already formatted   (exit 0)
```

No test touched application data, port 8011, `.rag-dev-data/` or Ollama. No `filterwarnings`
was added; no sanctioned-warning exception was needed, because none of these test modules
imports `fastapi.testclient`.

## Decisions and deviations worth a reviewer's attention

1. **Two guards are relaxed for the authorized close, not one.** The obvious one is
   `Published interpretation is immutable`. The second is the live-build authority branch of
   `_check_knowledge_write`: closing an `ObjectObservation` reaches a revision, the source has a
   running build (the publication's own), and the branch's `_check_build` demands a `staging`
   generation, which a generation being published is not. Both are skipped only through
   `_authorized_recorded_closure`, which requires the plan's authority to name that exact row and
   instant, the row to still be open, and every other field to be byte-identical. The alternative
   considered and rejected was moving the closures after `_source_fields(active_build_id=None)`,
   which needs only one relaxation but inverts the order plan section 5 states.
2. **`_close_recorded_intervals` refuses to run outside an ambient transaction**, mirroring
   `apply_source_tombstone`. Being private is not by itself a boundary; this is.
3. **A version corroborated by a second source cannot be closed by one source's publication.**
   `_plan_lineage` requires *every* revision of the complete support to resolve to the
   publishing source, so the re-review F1 corroboration case is refused rather than silently
   retired. This is deliberate and is the conservative direction.
4. **`appends` may be empty; `closures` may not.** A correction that only retracts a segment
   appends nothing, which is honest; a plan with no closure is a plain publication and must not
   travel a path that exists to close intervals.
5. **Series keys include the record kind**, so an object-observation closure and an
   assertion-version append never satisfy each other.
6. **`knowledge/lifecycle.py` is unchanged.** Plan section 6 lists it beside
   `store/generations.py`, but the plan type belongs to `knowledge/temporal.py` per section 5 and
   `generation_for_inputs` has no part in preparing or validating one. Nothing was found that
   lifecycle needed to own.
7. **`superseded_version_ids` stays the flat union** and gains uniqueness; the per-series map is
   the new `superseded_by_series`, and `fully_superseded_version_ids` is the only set a caller
   should turn into closures. No existing assertion about `superseded_version_ids` changed.
8. **T5A3/T5A4 keep one EVIDENCE line each.** Every other ledger in
   `ai_docs/gates/rag-it-all/` has exactly one `EVIDENCE:` line per gate, so part 1's `partial`
   line was replaced rather than stacked under a second one. Its numbers (23 passed on both
   backends) are preserved verbatim in `evidence-int1.md` and cited in the new line.
9. **Test-fixture note for the next worker.** `correction_world` in
   `tests/unit/test_temporal_evidence.py` is deliberately heavier than part 1's `history_world`:
   every corrected row is an exact `GenerationEvidenceMember`, which drags in support members,
   span members and one dense passage per generation, and both endpoints of an assertion need an
   authorized `ObjectObservation` before `EvidenceAccess` carries the assertion at all.
   `history_world` was left byte-for-byte alone so part 1's cases keep their meaning.

## Remaining for Task 5A

- Chronological JSONL fixture loading (`tests/fixtures/rag_all/temporal_events.jsonl` already
  contains the nine scenarios; the loader is owned by Task 4d).
- The disposable-Neo4j repeat of the T5A3 publication/CAS/conflict cases, run by root.
- The independent SPEC/QUALITY review of this part.

## Fixes after review (worker `opus-13`, branch `wp/t5a2fix`, base `ad964da`)

Review: `ai_docs/reports/2026-09-11-t5a-int2-review.md`. F1-F6 are addressed below; F7-F10 needed
no code change and none was made. Nothing outside the brief's owned list was touched.

| # | Change | Test |
|---|---|---|
| F1 | `store/knowledge.py`: `RecordedClosureCapability` (`:28-43`), `_recorded_closure_capability` mint (`:726-748`), `_close_recorded_intervals(..., capability=)` required and verified (`:750-789`); `store/generations.py:1008-1019` mints it after `_validate_publication_plan` | `test_recorded_correction_closure_helper_refuses_a_caller_without_a_capability`, `test_recorded_correction_closure_capability_is_neither_forgeable_nor_reusable` |
| F2 | No code change; see the correction below. `generations.py:914` kept and labelled defense in depth | `test_recorded_correction_cannot_even_seal_an_append_whose_proof_group_is_incomplete` (2 cases), `test_recorded_correction_plan_refuses_an_append_depending_on_outside_evidence` (2 cases), `test_recorded_correction_cannot_stage_a_support_row_from_another_generation` |
| F3 | `generations.py:877-881` hoists `staged`; `:894-899` refuses a closure target the publishing generation carries | `test_recorded_correction_refuses_a_closure_target_the_same_generation_publishes` |
| F4 | No code change; decision 3 pinned | `..._refuses_a_closure_target_it_cannot_prove[corroborated]`, with `correction_world(corroborated=True)` |
| F5 | No code change | the rollback test now compares `model_dump_json()` of both closure targets and both appended rows, captured before the failpoint |
| F6 | No code change | `fencing_token + 1` added to the loop in `..._fails_without_writes_on_a_stale_parent_or_a_later_suppression` |

### F1: what the boundary now actually is

`publish_staged_generation` mints a `RecordedClosureCapability` *after* `_validate_publication_plan`
returns, inside the publication transaction, bound to the generation ID, the plan fingerprint, the
closure instant and the exact segment list. `_close_recorded_intervals` takes it as a required
keyword argument and refuses unless (a) there is an ambient transaction, (b) the object it was
handed **is** the one the store is currently holding - identity, not field equality, which is why
the dataclass is `eq=False` - and (c) the capability's instant and segments equal the ones being
closed. The mint is a context manager, so the capability is dropped when the closure step ends,
whether the publication commits or rolls back.

Measured against the review's probes: the P1 probe (`with store.transaction():
store._close_recorded_intervals(segments, recorded_to=MAY_12)`) no longer type-checks - it raises
`TypeError` for the missing capability before any row is read. A field-identical forgery and a real
capability captured from a completed publication both raise `RuntimeError: Recorded closure
requires the capability its publication minted`. Decision 2 below is corrected accordingly: the
ambient-transaction check prevents a partial batch from auto-committing; the *authority* is the
capability.

Placement note: the capability type lives in `store/knowledge.py` beside the helper that verifies
it, not in `knowledge/temporal.py`. `temporal.py` is the pure module a caller imports to *build* a
plan; a capability no caller may mint does not belong there. It is not persisted, not serialized
into the receipt (`payload_json` still carries only `temporal_plan`, the plan fingerprint) and never
returned.

### F2: the review's premise is wrong, and the record is corrected here

Review F2 says `generations.py:914` is the *sole* enforcement of "preserved evidence dependencies"
for an appended `AssertionVersion`, because `_check_knowledge_write`'s member guard passes
vacuously. The member guard does pass vacuously - but `validate_generation_seal` does not.
`generations.py:703-710` requires every `AssertionSupport` row of a member `AssertionVersion` to be
a member of the same generation, and `publish_staged_generation` calls `validate_generation_seal`
at `:995`, before `_validate_publication_plan` at `:997`.

Measured: staging a member version whose support row is deliberately unstaged cannot be sealed at
all ("Incomplete assertion proof group"), and with `:914` mutated to `if False and (...)` both
shapes the review proposes - support on this generation's span, support on the previous
generation's span - still fail, at `_seal`, with the same message
(`/tmp/hippo-t5a2fix-mutation-914.log`, reproduced in `/tmp/hippo-t5a2fix-red.log` part C). So
`supports <= staged` is implied by seal validation and `dependencies <= revisions` is implied
transitively through `:695` on the staged support members: `:914` is dead defense in depth on the
publication path, not the sole enforcement. It is kept (orchestrator's decision) and commented as
such.

Three tests replace the one the review asked for, agreed with the orchestrator before writing:
the end-to-end refusal at seal and the refusal to publish an unsealed generation; a white-box call
to the read-only `store._validate_publication_plan(gen, plan)` that pins `:914` itself and fails if
the line is removed; and the companion fact that a support row on a foreign revision cannot be
staged at all ("Evidence member is outside generation revisions").

### RED and mutation evidence

`/tmp/hippo-t5a2fix-red.log` has three parts. Part A: the new tests against the unmodified tree at
`ad964da` - 6 failed, 49 passed, three of them failing for the wrong reason (the two proof-group
cases, which is how F2 was found, and the corroborated case, whose fixture row has to be built
before the second build is claimed). Part B: because F2/F3/F4/F6 pin guards that already existed or
that live behind an earlier guard, each is additionally shown to fail when the guard it pins is
mutated away and to pass when it is restored:

| Mutation | Test that fails | Result |
|---|---|---|
| `generations.py:914` dependency check -> `if False and (...)` | `..._plan_refuses_an_append_depending_on_outside_evidence` | exit 1, DID NOT RAISE |
| F3 staged-closure guard -> `if False and (...)` | `..._refuses_a_closure_target_the_same_generation_publishes` | exit 1, DID NOT RAISE |
| `sources != {gen.source_id}` -> `if False and ...` | `..._refuses_a_closure_target_it_cannot_prove[foreign]` and `[corroborated]` | exit 1, DID NOT RAISE |
| `_check_build` fence comparison removed | `..._fails_without_writes_on_a_stale_parent_or_a_later_suppression` | exit 1, DID NOT RAISE |
| `validate_generation_seal` proof-group raise -> `if False and (...)` | `..._cannot_even_seal_an_append_whose_proof_group_is_incomplete` | exit 1, DID NOT RAISE |
| capability identity check removed | `..._closure_capability_is_neither_forgeable_nor_reusable` | exit 1, 1 failed 1 passed (the required-kwarg test still passes: its `TypeError` is independent of the identity check) |

### Commands and results

Baseline at `ad964da` before any change, all `-q -o addopts='' -W error`:
`/tmp/hippo-t5a2fix-baseline-fake.log` (T5A1 69, T5A2 32, T5A3 48, T5A5 213 passed 1 skipped,
generation+prose 101 passed 1 skipped, T5A6 clean) and `/tmp/hippo-t5a2fix-baseline-ladybug.log`
(T5A4 48 passed 53 deselected, `test_generation_store.py` 35 passed).

GREEN Fake, `/tmp/hippo-t5a2fix-fake-green.log`:

| Command | Result |
|---|---|
| T5A1 `test_temporal_evidence.py` | exit=0; 78 passed in 0.89s (was 69) |
| T5A2 `test_temporal_conflicts.py` | exit=0; 32 passed in 0.03s |
| T5A3 `-k 'history_manifest or recorded_correction or suppression_history or purge_history'` | exit=0; 57 passed, 53 deselected in 0.84s (was 48) |
| T5A5 contracts/store/access/generation/snapshot/loader | exit=0; 213 passed, 1 skipped in 6.80s |
| generation + prose + managed activation + snapshot | exit=0; 210 passed, 3 skipped in 35.93s |

GREEN Ladybug, `/tmp/hippo-t5a2fix-ladybug-green.log`:

| Command | Result |
|---|---|
| T5A4 same `-k`, `HIPPO_TEST_STORE=ladybug` | exit=0; 57 passed, 53 deselected in 100.58s |
| `HIPPO_TEST_STORE=ladybug test_generation_store.py` | exit=0; 35 passed in 26.30s |

Ruff: T5A6's command plus every file this worker changed -> `All checks passed!`, all files already
formatted, exit 0. No `filterwarnings` was added and no sanctioned-warning form was needed: none of
these modules imports `fastapi.testclient`. No test touched application data, port 8011,
`.rag-dev-data/` or Ollama; no Neo4j.

### Corrections to the part 2 record above

- Decision 2 ("`_close_recorded_intervals` refuses to run outside an ambient transaction ... Being
  private is not by itself a boundary; this is") was wrong, exactly as review F1 says. The ambient
  transaction check stops a single closure from auto-committing outside the batch; it is not an
  authority boundary, because `transaction()` is public. The boundary is now the capability, and
  the docstring at `store/knowledge.py:751-768` says only what is actually checked.
- The behavior map's row for "preserves ... evidence dependencies" should read
  `validate_generation_seal` (`generations.py:703-710`), not `generations.py:914`.
- `correction_world` gained three keyword arguments, all defaulting to the previous behavior:
  `extra_span` (stage one more version in the corrected series whose support row is unstaged;
  implies no seal, because such a generation cannot be sealed), `corroborated` (an open version
  supported jointly by this source and a second one, built before the second build is claimed
  because a support row reaching a source's revisions needs build authority once its build runs)
  and `seal`.

Every count above was produced from the committed tree (`c5dc345`), after the final Ruff
formatting, by `/tmp/t5a2fix-fake-green.sh` and `/tmp/t5a2fix-ladybug-green.sh`; the mutation table
was produced by `/tmp/t5a2fix-mutate.py`, which restores each file it touches.
