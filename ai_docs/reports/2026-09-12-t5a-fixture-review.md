# Independent SPEC/QUALITY review: the Task 5A chronological fixture loader

Reviewer `architect-reviewer-15`, root tree `/Users/mascott/projects/hippo`, HEAD `88a3a4c`
(the loader merged as `8a272ad`, evidence `7b60888`, gates extended `88a3a4c`). Read and run
only; the single file this review wrote is itself.

Contract: `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` sections 1, 3, 5, 6 (last
bullet) and 7 step 3. Under review: `src/hippo/evals/rag_all_temporal.py`,
`tests/unit/test_temporal_fixture_loader.py`, `tests/fixtures/rag_all/temporal_events.jsonl`
and its README section, and the ten conventions declared in
`ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/evidence-fixture.md`.

**SPEC: FAIL** — one live violation of section 1 in the shipped fixture (F1) and one latent
one (F2). Both fixes are local to the loader and need no shared file.

**QUALITY: FAIL** — two of the brief's three quality questions came back negative with
repros (F3, F4). The third passes: the loader cannot be reached as a production ingestion
path.

Conventions: **7 ACCEPT, 3 REDIRECT** (items 1, 5, 9).

Every gate command reproduces. Nothing here disputes a test result; the findings are about
behavior no test asks for.

## Runs

All four exit 0. Every command carried `HIPPO_TEST_STORE` explicitly, `-q -o addopts=''
-W error`, and no Neo4j.

| # | Command | Result | Log |
|---|---|---|---|
| 1 | T5A3 verbatim from the ledger (fake) | exit=0; 77 passed, 53 deselected in 12.51s | `/tmp/hippo-t5afix-review-1.log` |
| 2 | T5A4 verbatim from the ledger (ladybug) | exit=0; 77 passed, 53 deselected in 234.11s | `/tmp/hippo-t5afix-review-2.log` |
| 3 | fake: `test_temporal_fixture_loader.py test_rag_eval.py test_rag_eval_session.py test_managed_eval_activation.py` | exit=0; 96 passed in 20.83s | `/tmp/hippo-t5afix-review-3.log` |
| 4 | ladybug: `test_temporal_fixture_loader.py` alone | exit=0; 20 passed in 155.56s | `/tmp/hippo-t5afix-review-4.log` |

Run 3 passed under plain `-W error` and needed **no** sanctioned-warning filter: none of the
three eval modules raises the `anyio.abc.BlockingPortal` `DeprecationWarning` at collection
in this combination, so neither form (a) nor form (b) of the fleet rule was used.

Root advanced to `b5a5086` (merge `wp/pa4f`, Task 5 production activation) during this review.
It touches none of the files under review — `git diff --name-only 88a3a4c..b5a5086` is empty for
the loader, its tests, the fixture, the fixture README, `knowledge/conflicts.py`,
`knowledge/temporal.py` and the Task 5A gate ledger — so runs 1, 2 and 4 stand. It does change
`evals/runner.py` and `test_managed_eval_activation.py`, which run 3 covers, so run 3 was
repeated at `b5a5086`: exit=0; 97 passed in 19.10s, still under plain `-W error`
(`/tmp/hippo-t5afix-review-3b.log`). Every finding below was measured at `88a3a4c` and
re-confirmed against an unchanged loader.

The ledger's T5A3/T5A4 counts (77 passed, 53 deselected) supersede the evidence file's
proposed 68 passed. The difference is the tree, not the loader: the two pure test files select
57 cases at root against 48 at the worktree base `79e379a`. Eight of the nine are the new
`recorded_correction` tests `wp/t5a2fix` added to `test_temporal_evidence.py` between those two
commits (six functions, eight cases with parameterization); the ninth is a case an existing
test in that file gained. The loader contributes 20 either way, and the deselected count (53)
and the exit code match in both.

Findings were reproduced with five read-only probe scripts under `/tmp/t5arev/`
(`probe1.py`–`probe5.py`); each finding below names the probe that produced it.

## SPEC review

| Required behavior (brief step 2) | Verdict |
|---|---|
| Every instant parsed as aware UTC | **PROVEN** — `test_every_row_instant_is_parsed_as_an_aware_utc_value_in_recorded_order`; `_instant` refuses a naive value at `rag_all_temporal.py:132` and normalizes with `astimezone(UTC)` at `:134`. |
| Naive or missing required instants rejected, never defaulted | **PROVEN** — `test_a_naive_or_missing_instant_is_refused_instead_of_defaulted`, 4 cases (naive `recorded_from`, null `recorded_from`, naive `valid_from`, unparseable text). |
| Original text preserved | **PROVEN** for a dated row — `source_timestamp_original == "2026-04-01T00:00:00Z"`. |
| Original timezone preserved | **VIOLATED** — `rag_all_temporal.py:137-138`. See F2. |
| Original precision preserved | **PROVEN** — `_precision` at `:164-167`, asserted in the parsing test. |
| Nothing defaulted to a wall clock | **PROVEN** — `rg -n "datetime.now\|utc_now\|time\(\)" src/hippo/evals/rag_all_temporal.py` is empty (exit 1), and `test_the_loader_reads_no_wall_clock_anywhere` pins it from inside the suite. The one ambient clock a publication reads is lent the row's own instant (`_generation_window`, `:324-341`). |
| Rows applied in chronological `recorded_from` order | **PROVEN** — `read_temporal_events` sorts by `(recorded_from, file index)` at `:269`; the test asserts the emitted order is sorted. |
| Bounded by the caller's clock | **PROVEN** for claims and suppressions — `test_the_caller_clock_bounds_which_recorded_events_are_applied`. **Not applied to barrier rows** — `:657` reads the whole file regardless of the clock, so a barrier is in force before its row is. That is a declared convention rather than a SPEC break, so it does not block `SPEC`; it is why convention 5 is REDIRECT. See F7. |
| Nine scenarios proven end to end through the part 1/2 APIs | **PROVEN** for 7; **weaker than the plan describes** for scenarios 1, 2 and 8. See the scenario table. |
| Idempotent reload writes nothing | **PROVEN**, and more strongly than the suite claims. Probe `probe4.py` (P11b) diffed *all 17* stored record kinds before and after a second replay: nothing changed. The suite's own `_knowledge_snapshot` covers 12 kinds and omits `AccessPolicy`, `Artifact`, `IndexManifest`, `MaintenanceJob` and `Workspace`; those five are clean too. |
| Ladybug close/reopen preserves the loaded history | **PROVEN** — `test_loaded_history_survives_a_ladybug_close_and_reopen` builds its own `LadybugStore` under `tmp_path`, and runs 2 and 4 exercise it on real Ladybug (234s / 156s). |

## Scenarios (plan section 7 step 3)

| # | Scenario | Assertion the plan names | Verdict |
|---|---|---|---|
| 1 | May ownership correction | §5: close the prior segment and append the corrected one in one transaction; §1: append "corrected historical segment(s), **the new state**" | **PROVEN in part.** The closure travels as a `TemporalPublicationPlan`, the prior segment's `recorded_to` is stamped and never rewritten, and "original before / corrected after" holds at both cutoffs. **Weaker than §1:** the correction appends only the corrected historical segment, so after it the catalog asserts nothing about ownership from 2026-05-01 onward — the "new state" half is never exercised, and `may_owner_bob` is retired though no source retracted it. See F5. |
| 2 | Imported-old-last supersedes nothing | §1: arrival order never proves source order | **PROVEN at the conflict API** (`closed_version_ids == ()`, absent from `select_same_source(...).current`, `compare_orders(...) == "older"`). **UNTESTED in the persisted history**, where it is the one catalog claim still proven after 2026-05-01. See F5. |
| 3 | Equal ETag / equal source timestamp, different bytes | §1, §3: preserve ambiguity and request canonical refetch | **PROVEN**, 2 parameterized cases: `requires_refetch`, `superseded_version_ids == ()`, both versions current, both recorded intervals open, distinct `content_hash`. |
| 4 | Unknown date | §2: contextual, never time-proven | **PROVEN** — `validity_kind="unknown"`, `valid_from is None`, `temporal_precision="unknown"`, in `contextual` with reason `effective_unknown` and absent from `proven`. But the row's own `source_timestamp_original` is a fabricated instant; see F1. |
| 5 | Environment collision | §1, §3: distinct scopes never conflict | **PROVEN** — `service-a:staging` vs `service-a:production`, staging absent from every conflict set, all sets at the production scope. |
| 6 | Independent-source alternatives | §3: corroboration, not conflict | **PROVEN** — two sources, one `Assertion` id, `superseded_version_ids == ()`, `ambiguous_series == ()`, no conflict at either cardinality. |
| 7 | Ordinary tombstone | §1, §4: hides `current_only`, keeps authorized history | **PROVEN** — `current_only`/`tombstone`/epoch 5 asserted, the corrected version still proven in history mode, its span gone from the current proof. |
| 8 | All-history purge | §1, §4: denies even historical mode; `purged_history_evidence` returns markers with no retained text | **PROVEN for denial** (version gone from proven *and* contextual, revision gone from `broad`, and the contrast against scenario 7's tombstone is explicit). **UNTESTED for the markers** — the marker path is unreachable from this fixture. See F6. |
| 9 | Explicit restoration barrier | §4: a purge/restoration barrier is what a restoration must satisfy | **PROVEN** that the declared token is what the source's suppressions carry and that an ordinary later arrival is `older` than the confirmed restoration. But the barrier is in force before the row declaring it has been applied; see F7. |

## The ten conventions

Judged against plan sections 1 and 3. Numbering follows `evidence-fixture.md`
"Decisions and deviations".

| # | Convention | Verdict | Reason |
|---|---|---|---|
| 1 | Derived closure: `fully_superseded_version_ids` limited to the same source's earlier open segments | **REDIRECT** | The *mechanism* is the only §3-consistent one available — supersession is ordinal-only, no row names its target, and `_closures` correctly refuses another source's versions, its own version, and anything not recorded strictly earlier. What needs redirecting is the claim the convention makes about the proof. Because all three catalog claims share one series, the highest ordinal is the only possible current claim, so the correction retires `may_owner_bob` and the fixture ends with no catalog claim about ownership after 2026-05-01: the May example proves "original before, corrected after" but never the "corrected segment(s) **and the new state**" §1 asks for. The same derivation leaves `old_imported_last` recorded-open forever (F5). The mechanism stays; the convention should say what it proves and what it does not, and the fixture should carry the new state. |
| 2 | `SourceOrder.series_key` = source name | **ACCEPT** | The reasoning is right and load-bearing: `_series_key` already contributes workspace/subject/predicate/scope, and putting the claimed object in the series would split the equal-token pairs into two one-member series and destroy the ambiguity scenario 3 exists to prove. Verified by reading `conflicts.py:133-145`. One low note in F10: barrier rows are given an order in the same series, so `compare_orders(claim, barrier)` is well-defined only because the series key coincides. |
| 3 | Default subject `service-a` (kind `service`), object kind `owner`, `DEFAULT_SCOPE_KEY="service-a:production"` | **ACCEPT** | The rows genuinely carry no subject and mostly no scope, so a convention is unavoidable, and this one is what makes `environment_collision` a distinct scope under §1 bullet 7 and `independent_alternative` a same-scope alternative under §3 rather than an unrelated claim. Both are asserted directly in the scenario 5 and 6 tests, and the README documents the default. |
| 4 | Per-source `rule_version` (`rag-all-temporal-v1:<source>`) | **ACCEPT** | §3's amendment explicitly allows several sources to share one version ID, and the store then refuses the second source's support with `Sealed assertion proof group cannot gain support`. Expressing corroboration as separate candidates over the same `Assertion` is exactly what §3 prescribes ("those corroborating candidates are one alternative ... they never form a conflict"), and scenario 6 proves the outcome (`accepted.assertion.id == undated.assertion.id`). The in-code comment at `:461-463` states the reason where a maintainer will read it. |
| 5 | Pre-resolved barriers; a barrier row writes nothing of its own | **REDIRECT** | The immutability argument is correct — `restoration_barrier` is not a mutable field, so a later row cannot stamp a committed `Suppression`. But resolving from the *whole file* means a barrier recorded 2026-05-17 is in force for a tombstone written at a 2026-05-15 clock while the loader simultaneously reports that barrier row in `deferred`. That contradicts convention 10 and the loader's own docstring. See F7 for the minimal fix. |
| 6 | Revision reuse on re-import | **ACCEPT** | A revision is identified by artifact + provider revision + content hash, so `old_imported_last` (token `rev-a`, no `content_hash`) legitimately resolves to the revision `may_owner_alice` created; reusing the stored row is also what keeps `observed_at` honest at 2026-04-02 instead of minting a second copy "observed" in May. It still gets its own span, observations, version and `GenerationMember`. `probe4.py` confirms 10 `ArtifactRevision` rows for 11 claims — exactly one reuse. |
| 7 | Lending the store its private generation clock; reading `_knowledge_get` | **ACCEPT**, with a recommendation | `_knowledge_get`/`_knowledge_rows` are the codebase's de-facto internal record API, used across `src/hippo/knowledge/*`, `src/hippo/ingest/*`, `status.py` and `context.py` — reading them is squarely conventional. `_generation_clock` is read only at `store/generations.py:31` via `getattr(self, "_generation_clock", lambda: datetime.now(UTC))`, so the restore logic at `:339` is correct (the attribute is never a class attribute, so `previous` is `None` unless a caller already set one) and no instance attribute is left shadowing anything. It is also genuinely necessary: `publish_staged_generation` already takes `published_at`, but build-lease validity goes through `_now()`, and a lease expiring 2026-05-10T00:05 would be judged expired against real wall time. There is no public seam, and `store/generations.py` is reserved by §6, so the loader could not create one. The loader is nonetheless the **first `src/` writer** of that private attribute (the other 15 writers are all test modules) — it should become a public clock injection when §6 releases `store/generations.py`, and the evidence file should say "first production writer" rather than "the same injection the tests use". |
| 8 | `GATES.md` not edited by the implementer | **ACCEPT** (moot) | Correct under fleet rule "the orchestrator maintains those lines", and already applied at HEAD `88a3a4c`. Runs 1 and 2 reproduce the applied CHECK lines verbatim at 77 passed / 53 deselected, exit 0. |
| 9 | Scenario 8 proved on the broad history proof rather than purge markers | **REDIRECT** | The explanation is accurate — `probe4.py` (P13) confirms `unknown_date`'s revision is in `broad` but not in the `HistoryManifest` (4 revisions, none of them the contextual row), and `purged_history_evidence(manifest_id, ...)` returns `()`. But that is a property of *which source the fixture purges*, not a limit of the implementation: the purge targets `prd`, whose only claim is contextual by construction, so §4's marker path is unreachable from this fixture and Task 5A's purge story is proved one API short. See F6. |
| 10 | The clock is a bound, not a stamp | **ACCEPT** | This is the right rule and it is what makes the incremental replay in scenario 8 work (load to the tombstone, pin a selection, load on to the purge). It is convention 5 that must conform to it, not the reverse. |

## Findings

### F1 — HIGH — an undated claim is stamped with Hippo's recorded instant as its source timestamp

`src/hippo/evals/rag_all_temporal.py:184`, surfaced at `:202-203`.

`original = row["valid_from"] if valid_from is not None else row["recorded_from"]`. For a row
with no effective bound, the loader writes the *recorded* instant's text into
`source_timestamp_original` and `"UTC"` into `source_timezone`. Measured on the shipped
fixture (`probe1.py` P2, `probe2.py` P6): `unknown_date` carries
`source_timestamp_original="2026-05-14T00:00:00Z"`, and `serialize_temporal_evidence` emits
that instant beside `validity_kind="unknown"`, `temporal_precision="unknown"`,
`valid_from=null`.

Why it matters: section 1 requires that effective and recorded time stay independent and that
"parsing or serialization may never turn day/month/year/unknown precision into an
exact-instant claim"; section 2 requires unknowns to "serialize as null plus their explicit
kind/precision". The typed fields stay honest, but the serialized evidence a consumer reads
now shows an exact source timestamp that no source declared, and its value is Hippo's own
clock for the row. This is the one live section 1 violation in the shipped fixture.

It is not forced by the model. `probe5.py` constructs both `AssertionVersion` and
`ObjectObservation` with `source_timestamp_original=None` and `source_timezone=None`; both are
accepted, and `serialize_temporal_evidence` then emits nulls, which is exactly what section 2
asks for. So the fix is local to the loader and touches no shared file:

```python
original = row["valid_from"] if valid_from is not None else None
```

with `source_timezone=_timezone_label(original, valid_from) if original else None`. Add an
assertion to `test_an_unknown_date_is_contextual_and_never_time_proven` that both fields are
`None`, so the property is pinned rather than incidental.

### F2 — MEDIUM — a declared non-UTC offset is flattened to "UTC"; the branch meant to keep it is dead

`src/hippo/evals/rag_all_temporal.py:137-138`.

`_timezone_label(text, parsed)` returns `"UTC"` when `parsed.utcoffset() == timedelta(0)` and
`text[-6:]` otherwise. Every datetime it is ever given has already been through `_instant`,
which ends in `parsed.astimezone(UTC)` at `:134`, so `utcoffset()` is always zero and the
`text[-6:]` branch is unreachable. Confirmed by `probe1.py` (P1): a row declaring
`valid_from="2026-04-01T02:00:00+02:00"` preserves the text but reports
`source_timezone="UTC"`.

Why it matters: section 1 requires the provider's *declared timezone* to be preserved, and
the loader's own module docstring claims "the provider's own text, declared zone and precision
preserved". The shipped fixture is all-`Z`, so today's stored values are correct — but the
first row added to prove exactly the behavior section 1 demands would be silently mislabeled,
and the dead branch shows the intent was the opposite of the effect.

Fix: derive the label before normalizing. Have `_instant` return the offset it parsed (or
re-parse the text inside `_timezone_label` instead of inspecting the already-converted value),
and label from that offset rather than from a `text[-6:]` slice, which is also wrong for a
`+0200` form written without a colon. Cover it with a `tmp_path` row carrying a non-zero
offset.

### F3 — MEDIUM — `TemporalFixtureError` does not cover every malformed shape

`src/hippo/evals/rag_all_temporal.py:628` and `:617-629`.

The brief asks directly. Two malformed suppression shapes escape as foreign exception types,
both at load time rather than parse time, so `read_temporal_events` reports the file as valid:

- An unsupported `reason` raises `KeyError: 'policy_change'` from
  `DEFAULT_BARRIERS[event.reason]` at `:628` (`probe2.py` P8). `_suppression_event` checks only
  that `reason` is a nonempty string.
- A `view_applicability` outside the literal set raises a pydantic `ValidationError` from
  `k.Suppression` (`probe3.py` P12).

Everything else I probed is covered correctly: unparseable and naive instants, a missing
required instant, an unexpected field set on all three row shapes, a malformed
`provider_order` (the `except ValueError` at `:160` catches the ordering contract's own
refusals, including a non-integer ordinal and a missing equality-only token), a non-positive
epoch, a reversed effective interval, and a row that is none of the three shapes.

Fix: validate both closed sets in `_suppression_event`, beside the epoch check — `reason`
against `set(DEFAULT_BARRIERS)` and `view_applicability` against
`{"current_only", "all_history"}` — so every malformed row fails as a `TemporalFixtureError`
at parse time with a message naming the field. Add the two cases to the existing
parameterized rejection test.

### F4 — MEDIUM — equal `recorded_from` inside one monotonic series silently skips a proven closure

`src/hippo/evals/rag_all_temporal.py:538`.

The brief asks whether rows can be applied out of order under equal `recorded_from`. They
cannot: `:269` sorts by `(recorded_from, file index)`, so ties are deterministic and decided
by the file's own sequence. But the closure is where an equal instant does damage.
`_closures` keeps only targets with `row.recorded_from < published_at`, and it drops the rest
silently. `probe3.py` (P10) gives two catalog rows the same `recorded_from` and ordinals 1
and 2: ordinal 2 closes nothing, and ordinal 1 is left recorded-open even though the
adapter's declared order retires it.

Why it matters: the strict `<` is correct — section 5 requires it and the store refuses
otherwise — but turning the store's refusal into a silent no-op means a future fixture row
can lose a supersession the ordering proves, with no error and no test. For a fixture whose
whole purpose is to make ordering behavior visible, a dropped closure should be loud.

Fix: in `_closures`, when a version is in `fully_superseded_version_ids`, belongs to this
source and is still open, but fails the `recorded_from < published_at` test, raise
`TemporalFixtureError` naming both instants — the fixture is asking for a closure the
publication contract cannot express. Cover it with a `tmp_path` two-row file.

### F5 — MEDIUM — which superseded segment gets recorded-closed depends on arrival order, and the re-import stays open forever

`src/hippo/evals/rag_all_temporal.py:514-540` (derivation) plus the fixture's catalog series.

After a full replay (`probe2.py` P5), three of the four catalog claims are retired by the
adapter's ordinal order, but only two have a closed recorded interval:

```
may_owner_alice      ord=1  recorded=[2026-04-02 -> 2026-05-10)
may_owner_bob        ord=2  recorded=[2026-05-10 -> 2026-05-12)
backdated_correction ord=3  recorded=[2026-05-12 -> open)     <- current
old_imported_last    ord=1  recorded=[2026-05-13 -> open)     <- retired, never closed
```

`old_imported_last` is closed by nothing because no later publication in the series follows
it. Its effective interval is `[2026-04-01, open)`, so `probe3.py` (P9) shows the
consequence through `select_history`:

- `as_of 2026-04-15, known_at 2026-05-18` proves **both** `backdated_correction` and
  `old_imported_last`;
- `as_of 2026-05-20, known_at 2026-05-18` proves `old_imported_last` as the catalog's **only**
  claim — the retired re-import is what the history says the catalog asserts about ownership
  today.

Section 3 does say an older same-source version "remains queryable in history", so
`select_history` returning it is layering, not a bug: history is reachability and
`select_same_source` decides the winner. The finding is narrower and real — whether an equally
retired segment is recorded-open or recorded-closed is decided by arrival order relative to
the next closure-bearing publication, which makes the `_closures` docstring's "Arrival order
never appears here" true of the decision and false of its consequence. Combined with the
missing "new state" (convention 1), the fixture's end state is a catalog that asserts nothing
current except a claim its own adapter retired.

The loader cannot fix this alone: section 5 forbids closing a segment at
`recorded_from == published_at` and part 2 forbids closing a member of the publishing
generation, so there is no instant at which `old_imported_last` could close itself. Two
options, and the choice is the orchestrator's:

- **Fixture** (preferred): add one catalog row at ordinal 4 restating the state after the
  re-import, so the re-import is closed like its siblings and the May correction finally
  appends the "new state" section 1 names. This costs one JSONL line and changes no code.
- **Loader**: after the replay, issue one closure-only publication (part 2 permits empty
  `appends`) at the last applied instant for every still-open member of
  `fully_superseded_version_ids`. More faithful, considerably more machinery.

**Mandatory regardless of the choice:** pin the post-replay end state in
`test_an_old_import_arriving_last_supersedes_nothing` — assert what
`as_of 2026-05-20 / known_at 2026-05-18` proves for the catalog. Today the test asks only the
conflict API, so this behavior is invisible to the suite either way.

### F6 — MEDIUM — the purge scenario cannot reach `purged_history_evidence`

`tests/fixtures/rag_all/temporal_events.jsonl:13` and
`tests/unit/test_temporal_fixture_loader.py:289-308`.

`probe4.py` (P13) pins a `HistoryManifest` before the purge (4 revisions), applies the purge,
then calls `purged_history_evidence(manifest_id, workspace_id=..., access=EVERYTHING)`: it
returns `()`. The reason in convention 9 is correct — the purge targets `prd`, whose only
claim is contextual by construction, so its revision never enters a manifest and no marker can
name it.

Why it matters: section 4 makes `purged_history_evidence` returning `PurgedEvidence(...,
"evidence_purged")` markers with no retained text part of the purge contract, and section 8
requires Task 5A to prove "purge/access denial". The fixture proves denial and leaves the
marker half of the contract unexercised end to end — one API short of the story the gate
claims, and the shortfall is a fixture choice rather than a limitation.

Fix: add a second `all_history` purge row over a source with a *proven* row (`accepted-prd`
or `backstage`) and assert in scenario 8 that `purged_history_evidence` names exactly that
revision's markers and carries no text. Adding rather than retargeting keeps the existing
contextual purge as the contrast it already is.

### F7 — MEDIUM — a barrier declared by a deferred row is already in force

`src/hippo/evals/rag_all_temporal.py:657`.

`barriers = {event.source_name: event.restoration_barrier for event in events if event.kind
== "barrier"}` reads every barrier row in the file with no clock filter, before the replay
loop. `probe2.py` (P7) at `clock = 2026-05-15T12:00Z`: `explicit_restoration` (recorded
2026-05-17) is reported in `deferred`, and the `ordinary_tombstone` `Suppression` written at
that clock nonetheless carries `restoration_barrier="confirmed:9"` — a token declared by an
event the loader says has not happened.

Why it matters: it contradicts convention 10 ("the clock is a bound"), the loader's own
docstring ("a row recorded after it is deferred, not applied"), and section 1's independence
of recorded time. The immutability argument behind the decision is sound and the idempotence
it buys is real, so the cost is honesty rather than correctness — the loader reads the future
to keep an incremental replay byte-identical. The README documents the resolution order,
which is why this is MEDIUM and not higher, but neither the README nor the evidence says the
clock does not bound barrier rows, and no test exercises the pre-barrier clock.

Minimal fix, no fixture change: state the carve-out explicitly where a reader will hit it —
in `load_temporal_events`'s docstring and in convention 5 — as "barrier rows are file-level
declarations about a source, exempt from the clock, because a `Suppression` cannot be
restamped"; stop listing barrier rows in `deferred` when their content is already in force, or
report them in a separate field so the two statements agree; and add a test at a clock before
2026-05-17 asserting the tombstone already carries `confirmed:9`, so the behavior is reviewed
rather than accidental. If the carve-out is unwanted instead, resolve barriers only from
applied events and let the fixture order the barrier row before the suppressions it governs,
with a `TemporalFixtureError` when it does not.

### F8 — LOW — the fixture cannot express a coarse effective bound, so `effective_imprecise` is unreachable

`src/hippo/evals/rag_all_temporal.py:182-183`.

`if (precision == "instant") != (valid_from is not None): raise`. The rule is a good one — it
is what stops a row turning an unknown time into a dated claim — but it is stated as a
biconditional, so `precision` can only ever be `"instant"` or `"unknown"` and the other five
members of `PRECISIONS` are unreachable (`probe1.py` P3 refuses `day`, `month` and `year` with
a `valid_from`).

Consequence: `effective_imprecise`, the contextual reason section 2 was amended to add after
the part 1 review precisely so `as_of`/`during`/`current` refuse a coarser-than-instant bound,
cannot be reached from this fixture. Not a violation — no scenario in step 3 asks for it — but
a gap worth recording, since the fixture is where that behavior would naturally be proved end
to end.

Fix: relax to "an explicit bound requires a precision, and `unknown` precision forbids one"
(`(valid_from is not None) == (precision != "unknown")`), and if the orchestrator wants the
coverage, add a `day`-precision row and assert `effective_imprecise` on it.

### F9 — LOW — `workspace_id` is an ambient variable rather than per-source state

`src/hippo/evals/rag_all_temporal.py:662, 677, 685`.

`workspace_id` is a loop-level variable reassigned each time a new source appears, and
`_apply_suppression` and `_apply_claim` receive whatever it last held rather than the
workspace of the `_SourceState` they are writing for. Every fixture source lands in the same
default workspace, so this is unobservable today and both backends pass. It is still a latent
correctness trap: a source in a different workspace would have its `Suppression` and staged
records written against another source's workspace, and no test could catch it.

Two smaller edges in the same area: `TemporalLoad.workspace_id` is `None` when every event is
deferred or every applied event is a barrier, and callers (including the suite's `history`
helper) pass it straight into `select_history`.

Fix: store `workspace_id` on `_SourceState` at construction and read `state.workspace_id` at
both call sites; keep `TemporalLoad.workspace_id` as the first applied source's workspace and
say so in its docstring.

### F10 — LOW — barrier rows share the claim series' ordinal namespace

`src/hippo/evals/rag_all_temporal.py:238`, asserted at
`tests/unit/test_temporal_fixture_loader.py:325`.

`_barrier_event` builds a `SourceOrder` with `series_key=source`, the same series the source's
claims use, so the barrier's ordinal 9 sits in the catalog claim ordering. Nothing breaks —
barrier rows never become `ConflictCandidate`s, so `select_same_source` never sees ordinal 9 —
but scenario 9's `compare_orders(imported.candidate.order, barrier.order) == "older"` is
well-defined only because a claim and a non-claim happen to share a series key, which is a
comparison section 3 does not contemplate. If a barrier row ever did enter the candidate set
it would supersede every claim from its source.

Fix: give barrier rows their own series (`f"{source}:restoration"`) and have scenario 9 assert
the barrier's ordinal against the source's highest *claim* ordinal directly, or state in the
README that a barrier row's order is deliberately in the claim series so a restoration can be
ranked against arrivals. Either makes the intent explicit.

## Quality answers to the brief's three questions

1. **Can rows be applied out of order under equal `recorded_from`?** No. `:269` sorts by
   `(recorded_from, file index)`, so ties resolve to the file's own sequence and the order is
   deterministic on every run and both backends. The real hazard at an equal instant is a
   silently dropped closure — F4.
2. **Does `TemporalFixtureError` cover every malformed shape?** No — F3, two escapes with
   repros. Everything else I probed is covered.
3. **Can the loader be misused as a production ingestion path?** No. Nothing under
   `src/hippo/web`, `src/hippo/mcp_server.py` or `src/hippo/cli.py` imports it (`rg` exit 1);
   `src/hippo/evals/__init__.py` does not re-export it; the only importer in the repository is
   `tests/unit/test_temporal_fixture_loader.py`; and `load_temporal_events` requires an
   explicit `clock` keyword, so there is no default-argument path into it. It is packaged and
   therefore importable, which is the same posture as `evals/rag_all.py` and consistent with
   this repository's convention of shipping eval code, so no change is warranted — but it is
   worth keeping the "no production importer" check on the gate as the module grows.

## Verdict and what closes it

`SPEC: FAIL` on F1 (live) and F2 (latent). `QUALITY: FAIL` on F3 and F4. All four are local
to `src/hippo/evals/rag_all_temporal.py`, need no shared file and no §6 release, and each
comes with a test that would have caught it.

F5, F6 and F7 are why conventions 1, 9 and 5 are REDIRECT. F5 and F6 are fixture-modeling
decisions for the orchestrator; F7 needs either the carve-out written down and tested or the
resolution order changed. F8–F10 are optional.

Nothing found here weakens the gate evidence: T5A3 and T5A4 reproduce verbatim at 77 passed /
53 deselected on both backends, idempotence holds across all 17 stored record kinds, and the
Ladybug reopen is real. The findings are about behavior the suite does not ask for, which is
the difference between a passing gate and a proved contract.
