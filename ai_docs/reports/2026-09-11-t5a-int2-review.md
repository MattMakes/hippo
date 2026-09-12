# Independent SPEC/QUALITY review — Task 5A integration part 2 (append-only correction publication)

Reviewer: `architect-reviewer-11`, root tree `/Users/mascott/projects/hippo`, branch `rag-it-all-tibs`,
HEAD `79e379a`. Read-only: this report is the only file written.

Range under review: `git diff 9980961..7d5984f -- src/ tests/` (merge `758e679`; branch commits
`5cd0834`, `880deb7`, `4565ad3`, `7d5984f`). 7 files, +841/-17.

Contract: `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` sections 1, 3, 5, 6 with every
"Amended" note. Implementer evidence: `ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/evidence-int2.md`.

## Verdicts

**SPEC: PASS.** Every behavior plan section 5 and re-review N2 require is present and, with the four
exceptions listed in the a–h table, proven by a test. Nothing is VIOLATED that is attributable to
part 2.

**QUALITY: PASS, conditional on F1 and F2 landing before Task 5A closes.** Criterion used: a QUALITY
FAIL is reserved for a defect that makes the merged code behave wrongly or that would require
reverting work. Neither F1 nor F2 changes the runtime behavior of the merged tree — F1 is a false
invariant claim recorded in a docstring and in the evidence file, F2 is a missing regression test for
the only enforcement of a spec clause. Both are cheap to fix and both are load-bearing for the
completion boundary in plan section 8, so they are required, not optional. A reviewer who treats a
false invariant claim in the evidence record as disqualifying on its own could defensibly write FAIL;
I do not, because the claim is about a private method with no caller.

Findings: 2 major, 4 minor, 4 informational. No blocker.

## 1. Run results

All commands from the repo root at HEAD `79e379a`, `HIPPO_TEST_STORE` explicit on every one,
`-q -o addopts='' -W error`. No warning filter of either sanctioned form was needed: none of these
modules imports `fastapi.testclient`. No Neo4j. No application data, port 8011 or Ollama touched.

| Gate | Store | Result | Log |
|---|---|---|---|
| T5A1 `test_temporal_evidence.py` | fake | exit=0; 69 passed in 0.74s | `/tmp/hippo-t5a2-review-T5A1.log` |
| T5A2 `test_temporal_conflicts.py` | fake | exit=0; 32 passed in 0.08s | `/tmp/hippo-t5a2-review-T5A2.log` |
| T5A3 `-k 'history_manifest or recorded_correction or suppression_history or purge_history'` | fake | exit=0; 48 passed, 53 deselected in 0.76s | `/tmp/hippo-t5a2-review-T5A3.log` |
| T5A4 same `-k` | ladybug | exit=0; 48 passed, 53 deselected in 88.83s | `/tmp/hippo-t5a2-review-T5A4.log` |
| T5A5 contracts/store/access/generation/snapshot/loader | fake | exit=0; 213 passed, 1 skipped in 6.23s | `/tmp/hippo-t5a2-review-T5A5.log` |
| T5A6 Ruff check + format --check | — | exit=0; All checks passed! / 11 files already formatted | `/tmp/hippo-t5a2-review-T5A6.log` |
| Brief step 1 extra (generation, prose, activation, snapshot, query-snapshot, source-lifecycle) | fake | exit=0; 219 passed, 1 skipped in 25.93s | `/tmp/hippo-t5a2-review-EXTRA.log` |

Every gate reproduces green. The recorded_correction half is identical to the evidence file on both
backends (48 passed, 53 deselected). Where totals differ: T5A5's 213 vs the ledger's 206 and the
evidence's 212 is drift from later merges (`test_snapshot_store.py` gained ~50 lines between
`7d5984f` and HEAD — see F10); the extra run's 219 vs the evidence's 188 is additionally because the
brief's step-1 command runs a sixth file, `test_managed_source_lifecycle.py`, that the evidence's
five-file command omitted.

Probe scripts written for this review (read-only, own throwaway `FakeStore`, no fixtures touched):
`/tmp/t5a2_probe.py`, `/tmp/t5a2_probe2.py`, `/tmp/t5a2_probe3.py`, `/tmp/t5a2_probe4.py`,
`/tmp/t5a2_probe5.py`.

## 2. SPEC table

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| a | Closure target exists, same workspace, source lineage through complete support, open, `recorded_from < published_at`, not already closed differently | **PROVEN, one branch UNTESTED** | `generations.py:874-888`. `test_recorded_correction_refuses_a_closure_target_it_cannot_prove` parametrizes `missing`/`unsupported`/`foreign`/`closed`/`not_before` (the last at the `==` boundary). The workspace branch `generations.py:880` has no test and I could not construct a case for it: `_validate_knowledge` already refuses "Knowledge references cross workspace boundaries" (`/tmp/t5a2_probe3.py` P6), so it is defensive-only. "Not already closed differently" is implemented as the stricter "not closed at all", which is a superset and correct. |
| b | Append is an exact member, `recorded_from == published_at`, preserves identity/scope/dependencies; observation corrections obey the equivalent closure | **PROVEN, two branches UNTESTED** | `generations.py:890-915`. `test_recorded_correction_refuses_an_append_outside_the_staged_correction` covers `outside`/`recorded`/`series`. `test_recorded_correction_closes_the_prior_segment_and_appends_the_corrected_one` closes and appends one `AssertionVersion` **and** one `ObjectObservation`. UNTESTED: the `row.recorded_to is not None` half of `generations.py:904`, and the whole of `generations.py:914` (`dependencies <= revisions`, `supports <= staged`) — see F2. |
| c | One transaction closes, appends, publishes/retires, advances state, writes the event; six failpoints roll back byte-identically | **PROVEN** | `generations.py:996-1014`; `_publish_generation` unchanged. `test_recorded_correction_rolls_back_every_write_when_a_failpoint_fires` parametrizes `closure`, `pointer`, `version`, `retirement`, `event`, `lease` and asserts both closed rows open again, gen one `active`, gen two `ready`, source pointer, job `running` and `content_epoch` unmoved. "Appends" is correctly a validation, not a write: the corrected rows were already persisted as staged members, and publication is what exposes them. Byte-identity after rollback is asserted only on the happy path — see F5. |
| d | Exact retry returns the receipt and observes applied closures; different plan, stale parent or fence, later suppression epoch, or conflicting close fails without writes | **PROVEN, fence UNTESTED on the plan path** | `generations.py:947-961`, `_observe_recorded_closures` at `generations.py:917-922`. Retry, narrower plan and `plan=None` retry are covered; stale parent and later suppression epoch are covered; the conflicting close is the `closed` case. The stale fence is enforced by the unchanged `_check_build` (`generations.py:223-224` compares both `source["build_fencing_token"]` and `job.fencing_token`) but no correction test drives it — see F6. |
| e | No model, filesystem, callback or unguarded clock in the transaction | **PROVEN** | The plan carries IDs and one instant, never a record or a callable (`temporal.py:629-654`, docstring `:630-634`). `publish_staged_generation` refuses a plan whose `published_at` differs from the argument (`generations.py:940`) — `test_recorded_correction_requires_the_plan_clock_to_be_the_publication_clock`. The only clock reached inside the transaction is `GenerationQueries._now()` at `generations.py:227`, the pre-existing injectable lease-expiry check in `_check_build`; it never determines a `recorded_to`. |
| f | The compatibility publish path rejects a plan | **PROVEN** | `generations.py:1026-1027`; `test_recorded_correction_is_refused_by_the_generic_fixture_publication_path`. `test_recorded_correction_never_reaches_a_published_row_through_update_knowledge` additionally proves the direct `update_knowledge` route stays closed before the plan and monotonic after it. |
| g | `select_history` returns the original segment before the cutoff and the corrected one after; `recorded_to` serializes; the May example passes | **PROVEN** | `test_recorded_correction_is_visible_to_history_selection_at_each_cutoff`: `MAY_5` yields `version_one`, `MAY_12` yields `version_two`, and `serialize_temporal_evidence` emits `"2026-05-12T00:00:00Z"` for the closed row and `null` for the open one. `correction_world` is literally the plan's `checkout OWNED_BY ada` → `bo` example. |
| h | N2: `superseded_version_ids` sorted and unique, keyed per series; `fully_superseded_version_ids` is the only closable set | **PROVEN as a pure contract; "only closable set" is advisory, not enforced** | `conflicts.py:83, 98-106, 168-189`. Two tests cover dedupe-across-support-groups and the superseded-here/current-there case. But the store never consults `conflicts.py`: what actually prevents closing a still-claimed version is `_plan_lineage`'s `sources != {gen.source_id}` refusal. Those two rules agree for the cross-source case and diverge for one source running two adapters/series keys over the same version — see F7. |

## 3. Findings

### F1 — MAJOR — `_close_recorded_intervals` does not have the boundary its docstring and the evidence claim

`src/hippo/store/knowledge.py:714-715` states: "The publication primitive is the sole coordinator:
without its transaction this refuses to run, so no caller acquires the relaxation on its own."
`evidence-int2.md` decision 2 states: "Being private is not by itself a boundary; this is."

Both are false. `transaction()` is public (`store/base.py:233`), so the ambient-transaction check is
satisfied by any caller. Measured (`/tmp/t5a2_probe.py` P1): after `correction_world(store)`, plain

```python
with store.transaction():
    store._close_recorded_intervals((("AssertionVersion", version_one.id),), recorded_to=MAY_12)
```

closes the published interpretation, with no plan, no lease, no fence, no CAS, no
`_validate_publication_plan`. The check does prevent a real thing — a single closure auto-committing
outside a batch (P1b: `RuntimeError: Recorded closure requires the publication transaction`) — it
just is not an authority boundary.

Why it matters: plan section 5 says "the publication primitive is the sole batch coordinator", and
this is the record the next worker and the Neo4j repeat will trust. The actual trust level here is
the same convention the rest of the store already uses for `_generation_authority` and
`_publish_generation` — private instance state, settable by anyone holding the store — so part 2
lowers nothing. The defect is the claim, not the code.

Proposed fix (either is sufficient): (a) reword `knowledge.py:714-715` and evidence decision 2 to the
honest statement — the ambient-transaction check prevents a partial batch from auto-committing, and
the authority boundary is the same private-method convention as `_generation_authority`; or (b) make
the claim true by minting a capability token inside `publish_staged_generation` (after
`_validate_publication_plan`) that `_close_recorded_intervals` requires as a keyword argument.

### F2 — MAJOR — the only enforcement of "preserved evidence dependencies" for an appended version has no test

`generations.py:914` is the `not dependencies <= revisions or not supports <= staged` check. For an
appended `AssertionVersion` it is the *sole* enforcement, because the generic guard that would
otherwise cover it passes vacuously: `_check_knowledge_write` requires
`_record_revisions(target) <= selected` when a `GenerationEvidenceMember` is written
(`generations.py:476`), and an `AssertionVersion` reaches no revision through its reference graph.
Measured (`/tmp/t5a2_probe3.py` P7): `_record_revisions(version_two) == []` while
`_plan_lineage(version_two)[1]` is the one revision of generation two. So the version's real evidence
dependency is visible only through `AssertionSupport`, only in `_plan_lineage`, only at `generations.py:914` — and
no test drives that line. `supports <= staged` is the operative half (see below).

Failure this admits: a staged `AssertionVersion` whose support span belongs to a revision of an
*earlier* generation can be added as an evidence member without complaint, and if it ever
regresses, a correction would append a segment whose proof is outside the generation that publishes
it. The plan's "preserve … evidence dependencies" clause would be silently unenforced.

Which half is live: `supports <= staged` is the untested one that actually guards something.
`dependencies <= revisions` is defensive on both kinds, because `_record_revisions` *does* reach the
revision for an `AssertionSupport` and for an `ObjectObservation` (`/tmp/t5a2_probe5.py` and
`/tmp/t5a2_probe3.py` P7), so the `GenerationEvidenceMember` guard already covers those two once they
are staged. It is only the `AssertionVersion` itself that slips through, and only
`supports <= staged` catches it.

Proposed fix — one test, shaped to fail if `generations.py:914` is removed. Inside
`with store.generation_write(second.id, ...)` in a `correction_world` variant, before `_seal`:
create `version_x` on a new assertion with `_support(store, version_x, span_two)`;
`_member(store, second, version_x)` succeeds (nothing binds it, `_record_revisions` is empty), but
deliberately do **not** `_member` the support row. A plan whose `appends` names `version_x` must then
raise "depends on evidence outside its generation". Optionally assert the companion fact in the same
test: `_member(store, second, support_on_span_one)` is refused with "Evidence member is outside
generation revisions", which is what makes `dependencies <= revisions` redundant rather than live.

### F3 — MINOR — a plan may close a row the same generation is publishing, minting a recorded window that was never exposed

`_validate_publication_plan` checks a closure target is open and `recorded_from < published_at`, but
not that it is outside the staged generation. Measured (`/tmp/t5a2_probe4.py` F): `correction_world`'s
own `mistimed` observation (a staged member of generation two, `recorded_from = MAY_10`) is accepted
as a closure target, and generation two publishes it born-closed over `[MAY_10, MAY_12)`. Plan
section 1 defines `recorded_from/to` as "when Hippo exposed that interpretation", and Hippo exposed
nothing during that window — the generation was not active.

Not attributable to part 2 alone: the fixture's `mistimed` row shows the staging path already accepts
an arbitrary `recorded_from` on a bitemporal row, so an unclosed version of this anomaly predates the
plan. Part 2's marginal contribution is the ability to close it in the same transaction.

Proposed fix: in `_validate_publication_plan`'s closure loop, after the `recorded_from` check, add
`if (segment.record_kind, segment.record_id) in staged: raise ValueError(...)` (hoist the `staged`
set above the loop). Separately worth raising with the orchestrator as a Task 5A follow-up: nothing
binds a staged bitemporal row's `recorded_from` to the publication instant of the generation that
first exposes it.

### F4 — MINOR — decision 3, the case the amendment exists for, is proven only by this review's probe

`evidence-int2.md` decision 3 and plan section 5 line 116 say a version corroborated by a second
source cannot be closed by one source's publication (re-review F1). The five closure cases test a
*fully* foreign version, never a *shared*-support one. I verified the mechanism directly
(`/tmp/t5a2_probe3.py` P3'): a version supported by spans from two sources yields
`_plan_lineage → sources == {alpha, beta}`, so `sources != {gen.source_id}` refuses it. Separately
(`/tmp/t5a2_probe.py` P3) a *published* version can no longer gain corroboration at all — 
`_check_knowledge_write` raises "Sealed assertion proof group cannot gain support" — so the case only
arises for support added before sealing.

Proposed fix: add a sixth parametrization `corroborated` to
`test_recorded_correction_refuses_a_closure_target_it_cannot_prove`, building the version with two
`_support` rows from two sources, expecting the `lineage` message.

### F5 — MINOR — the rollback test asserts openness, not byte-identity

Plan section 5 and the brief both say a failpoint leaves "the prior publication and every open
version byte-identical". `test_recorded_correction_rolls_back_every_write_when_a_failpoint_fires`
asserts `.recorded_to is None` on the two closure targets. The happy-path test already has the
stronger form (`_row(...) == world.version_one.replace(recorded_to=MAY_12)`).

Proposed fix: in the rollback test, replace the two `.recorded_to is None` asserts with
`_row(store, "AssertionVersion", world.version_one.id) == world.version_one` and the equivalent for
`observation_one`.

### F6 — MINOR — the stale fence is the one (d) precondition with no correction-path test

`_check_build` compares `source["build_fencing_token"]`, `job.fencing_token`, `job.lease_owner`,
`job.lease_expires_at` and `gen.status` (`generations.py:215-231`) and is reached before any plan
work, so the behavior is structurally sound; the brief nonetheless names "stale parent **or fence**".

Proposed fix: add `dict(fencing_token=world.job_two.fencing_token + 1)` to the loop in
`test_recorded_correction_fails_without_writes_on_a_stale_parent_or_a_later_suppression`.

### F7 — INFO — `fully_superseded_version_ids` is advisory; the store enforces a different, mostly equivalent rule

Nothing in `src/hippo/` imports `knowledge/conflicts.py` at all (verified by grep at HEAD); it is a
pure module with test consumers only. What actually stops a publication from closing
a version another series still claims is `_plan_lineage`'s single-source requirement. The two rules
agree for the cross-source case the N2 test models (`catalog-a` / `catalog-b`), and diverge for one
source whose adapter emits two series keys over the same version: `fully_superseded_version_ids`
would exclude it, `_plan_lineage` would allow the close. No caller constructs plans from selections
yet, so this is a note for whoever wires the conflict output to the plan builder, not a defect.

### F8 — INFO — the closure relaxation is exactly two guards, and both are load-bearing

Verified rather than taken on trust (`/tmp/t5a2_probe.py` P2). Forcing
`_authorized_recorded_closure → False`: an `AssertionVersion`-only plan fails with "Published
interpretation is immutable"; an `ObjectObservation`-only plan fails with "Managed evidence write
requires build authority". Decision 1 is accurate, and the asymmetry has a reason — an
`AssertionVersion` reaches no revision (F2), so the content-epoch authority branch is a no-op for it.
The predicate itself is tight: `knowledge.py:697-702` requires an authorized `(kind, id)`, an open
existing row, and `record == existing.replace(recorded_to=instant)`, so no other field can move.

### F9 — INFO — the receipt fingerprint carries no private text and is stable across equal plans

`payload_json` after a correction is
`{"fencing_token":2,"job_id":"maintenancejob-…","lease_owner":"worker","temporal_plan":"<sha256>"}`
(`/tmp/t5a2_probe3.py` P5) — record IDs are already content-addressed hashes and the plan itself is
reduced to one sha256. Idempotence across a byte-different but semantically equal plan holds:
`__post_init__` sorts and dedupes both tuples and `_utc` normalizes to UTC, so a plan spelled
`2026-05-12T02:00+02:00` fingerprints identically to `2026-05-12T00:00Z` (P4), and the unit test
already covers the reordered-tuple case. Two nits, neither worth a fix: `_recorded_closures` is a
plain instance attribute with the same implicit single-threaded-store assumption as
`_generation_authority`; and the reverse retry (original had no plan, retry supplies one) is untested
though symmetric under the same dict equality.

### F10 — INFO — the heavier `correction_world` fixture hides nothing; one ledger line is stale

`correction_world` is heavier than part 1's `history_world` in the direction of *more* rigor: every
corrected row is a real `GenerationEvidenceMember`, which is what makes the published-interpretation
guard fire at all (F8 confirms it does). `history_world` was left byte-for-byte alone, so part 1's
cases keep their meaning. The `retracted` row is deliberately *not* a member, which is what makes the
`closed` case a genuine already-closed target. No assertion the lighter fixture would have caught is
lost. No Ladybug-only or Fake-only path: the correction tests run on both through T5A3/T5A4, and
`test_recorded_correction_survives_a_ladybug_close_and_reopen` builds its own `LadybugStore` under
`tmp_path`, so it exercises a real file in both sessions. Neo4j remains the one untested backend, as
the ledger already records. Separately, the T5A5 EVIDENCE line still reads 206 passed while the gate
now yields 213 — the drift is from later merges (`test_snapshot_store.py` gained ~50 lines between
`7d5984f` and HEAD), not from part 2, but the line no longer matches a re-run.

## 4. Verbatim public signatures (step 4)

Read from source at HEAD `79e379a`, not from the evidence file.

```python
# src/hippo/knowledge/temporal.py:629
@dataclass(frozen=True)
class RecordedSegment:
    record_kind: TemporalRecordKind          # "ObjectObservation" | "AssertionVersion"; anything else raises
    record_id: str                           # nonempty after strip, else raises

# src/hippo/knowledge/temporal.py:658
@dataclass(frozen=True)
class TemporalPublicationPlan:
    published_at: datetime                   # normalized through _utc(); naive raises "timezone aware"
    closures: tuple[RecordedSegment, ...]    # sorted, unique, nonempty
    appends: tuple[RecordedSegment, ...] = ()  # sorted, unique, disjoint from closures; may be empty

    @property
    def fingerprint(self) -> str             # text_hash(canonical_json({published_at, closures, appends}))

# src/hippo/knowledge/conflicts.py:78
@dataclass(frozen=True)
class SameSourceSelection:
    current: tuple[ConflictCandidate, ...]
    superseded_version_ids: tuple[str, ...]
    ambiguous_series: tuple[str, ...]
    superseded_by_series: tuple[tuple[str, tuple[str, ...]], ...] = ()   # new (N2)

    @property
    def requires_refetch(self) -> bool

# src/hippo/knowledge/conflicts.py:98
def fully_superseded_version_ids(selection: SameSourceSelection) -> tuple[str, ...]   # new (N2)

# src/hippo/store/knowledge.py:22
CLOSABLE_RECORD_KINDS = ("AssertionVersion", "ObjectObservation")

# src/hippo/store/knowledge.py:687
class KnowledgeQueries:
    def _authorized_recorded_closure(self, record, existing) -> bool
    def _close_recorded_intervals(self, segments, *, recorded_to: datetime) -> tuple[str, ...]
        # segments is an iterable of (kind, record_id); raises RuntimeError outside an ambient transaction

# src/hippo/store/generations.py:822
class GenerationQueries:
    def _plan_row(self, kind, record_id)
    def _plan_lineage(self, kind, row)            # -> (sources: set[str], revisions: set[str])
    def _plan_series(self, kind, row)             # -> ("ObjectObservation", object_id)
                                                  #  | ("AssertionVersion", workspace, subject, predicate, scope_key)
    def _validate_publication_plan(self, gen, plan)   # read-only, before any write
    def _observe_recorded_closures(self, plan)        # read-only, retry path

    def publish_staged_generation(self, generation_id, *, expected_parent_id, job_id, lease_owner,
                                  fencing_token, expected_suppression_epoch, published_at,
                                  plan=None, fault_hook=None)
    def publish_generation(self, generation_id, *, expected_parent_id, published_at,
                           plan=None, fault_hook=None)    # a plan is always rejected here
```

Failpoint positions accepted by `fault_hook` on the strict path, in firing order:
`closure` (new, after every closure and before `_publish_generation`), `pointer`, `retirement`,
`version`, `event`, `lease`.

For the two follow-ups this unblocks:

- **Fixture loader (Task 4d's file).** The loader needs no new store surface. It builds
  `RecordedSegment(record_kind, record_id)` values and one `TemporalPublicationPlan(published_at=…,
  closures=…, appends=…)` per correction event, then calls `publish_staged_generation(..., plan=plan)`
  with `published_at` equal to `plan.published_at`. Every appended row must already be a
  `GenerationEvidenceMember` of the staged generation with `recorded_from == published_at`, and every
  closure target's complete support must resolve to the publishing source alone.
- **Neo4j repeat (root).** Run the T5A3 `-k` selection against the disposable container. The
  backend-sensitive surface is `_close_recorded_intervals` → `update_knowledge`, which on `neo4j`
  takes the extra `_knowledge_lock` write before reading lifecycle state (`knowledge.py:653-659`);
  that path is exercised on neither Fake nor Ladybug, so the repeat is the first test of it. Assert
  one winning closure/publication transaction under concurrency and that the six failpoints roll back
  there too.

## 5. What the next worker should do

Required before Task 5A closes: **F1** (correct the claim, or mint the capability) and **F2** (the
dependency/support regression test). Recommended in the same pass, all small: **F3** (one-line
`staged` guard on closures), **F4** (`corroborated` parametrization), **F5** (byte-identity assert),
**F6** (`fencing_token + 1` case). F7–F10 need no code change; F10's ledger drift is the
orchestrator's line to refresh if it wants the recorded counts to match a re-run.
