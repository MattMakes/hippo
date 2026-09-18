# Independent SPEC/QUALITY review — Task 5A pure temporal/conflict increment

Reviewer: `architect-reviewer-2` (herdr fleet, root tree). Date: 2026-09-11.
Contract: `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` §1–§3 (§4–§6 out of scope).
Under review (all uncommitted on `rag-it-all-tibs`, HEAD `26f9a55`):
`src/hippo/knowledge/temporal.py` (270 lines), `src/hippo/knowledge/conflicts.py` (214 lines),
`tests/unit/test_temporal_evidence.py`, `tests/unit/test_temporal_conflicts.py`,
`tests/fixtures/rag_all/temporal_events.jsonl`.

## Verdicts

**SPEC: FAIL** — 1 blocker, 3 major, 5 minor.
**QUALITY: FAIL** — the suite encodes the blocker as desired behavior, two code paths have zero
coverage, and half-open interval math is implemented three times independently.

The increment is close. Nothing from §4–§6 was attempted (confirmed in item 4 below), the module
boundary is clean, and determinism discipline is genuinely good. The failure is concentrated in two
places: a late patch that rejects ordinary independent-source corroboration, and a precision rule
that is enforced on one predicate family and not the other two.

## Gate results

Run from `/Users/mascott/projects/hippo` with `.venv/bin/python` (3.12.11), `HIPPO_TEST_STORE=fake`.

| Gate | Result | Log |
| --- | --- | --- |
| T5A1 `test_temporal_evidence.py` | exit=0, 19 passed | `/tmp/hippo-temporal-review-T5A1.log` |
| T5A2 `test_temporal_conflicts.py` | exit=0, 18 passed | `/tmp/hippo-temporal-review-T5A2.log` |
| T5A5 regression suite (6 files) | exit=0, 206 passed, 1 skipped | `/tmp/hippo-temporal-review-T5A5.log` |
| T5A6 Ruff check + format --check | exit=0, all checks passed, 4 files already formatted | `/tmp/hippo-temporal-review-T5A6.log` |

T5A3/T5A4 not run: they require the §4–§6 integration that has not started, and their `-k` filters
match no collected tests.

T5A5 was already ticked `[x]` in the ledger by the implementer, contrary to the fleet rule that a
worker never marks its own gate checkbox. I reran it independently and it passes; the tick is now
backed by third-party evidence, but the ledger entry should be regarded as self-reported until the
orchestrator's gate checker confirms it.

Note: all four gates pass. Every finding below is invisible to the current suite — that is itself
the QUALITY finding.

## SPEC table (plan §1–§3)

| # | Item | Verdict | Evidence |
| --- | --- | --- | --- |
| a | Naive datetimes rejected; original text/tz/precision preserved; precision never upgraded to an exact instant | **VIOLATED** | Rejection PROVEN (`test_resolve_selector_normalizes_aware_values_and_rejects_naive_cutoff`; `model.Instant` `_utc` at `model.py:90`). Preservation PROVEN (`test_temporal_serialization_keeps_every_clock_and_original_precision`). Precision upgrade **violated** at `temporal.py:168` and `temporal.py:182-189` — see F2 |
| b | Half-open `[start,end)`; missing upper = open-ended; missing lower = unknown, never −∞; empty/reversed reject | PROVEN (partial) | `test_as_of_uses_recorded_and_effective_half_open_intervals`, `test_explicit_unknown_lower_bound_never_means_negative_infinity`, `test_during_distinguishes_overlap_from_throughout_and_supports_open_upper_bound`, `test_model_rejects_empty_effective_and_recorded_intervals`. Reversed `TimeInterval`/`ChangesSelector` rejection is model-level (`model.py:1155`, `model.py:1200`), not re-proven here |
| c | Effective and recorded time independent; `observed_at`/`source_updated_at`/`published_at` distinct | PROVEN | `TemporalInputs` carries three separate optional clocks (`temporal.py:69-74`); `test_changes_uses_only_the_selected_clock`, `test_published_change_does_not_silently_substitute_recorded_time`. `observed_at` is serialized only and feeds no predicate — correct per §2 |
| d | `TemporalDisposition`, `TemporalReason` closed literals, ≥ the nine named reasons | PROVEN (with dead literal) | `temporal.py:16-28`; all nine present plus `change_outside`. `recorded_match` is declared and **never emitted** — see F7 |
| e | `resolve_selector`: explicit wins, else injected latest; compare returns ordered pair; contradictory snapshot IDs/cutoffs raise | PROVEN | `test_resolve_selector_commits_one_utc_cutoff_and_tracks_its_origin`, `test_compare_resolves_each_side_without_merging_their_snapshots`. Contradiction raising lives in `model.CompareSelector.comparison_scope` (`model.py:1223`) and is covered by pre-existing `test_temporal_selector_is_discriminated_and_rejects_contradictions` (`test_knowledge_contracts.py:228`), not by this increment |
| f | Predicate behavior (recorded eligibility, `as_of`, `during`, `atemporal`, `current`, `changes`) | **PARTIAL / VIOLATED** | Recorded eligibility PROVEN exactly (`temporal.py:155-160`; `test_as_of_uses_recorded_and_effective_half_open_intervals`). `as_of` unknown/snapshot contextual PROVEN. `overlaps` vs `throughout` PROVEN. `current` cutoff PROVEN. `changes` clock selection PROVEN. **Violated**: `as_of`/`during` ignore precision (F2). **UNTESTED**: `during/throughout` with unknown lower bound; `current` against a closed recorded interval; any excluded `changes` result (`change_outside` asserted 0 times) |
| g | `match_temporal` deterministic and side-effect free; compare evaluates each side independently | PROVEN (partial) | Pure functions, no mutation, no I/O. Independent side resolution PROVEN (`test_compare_resolves_each_side_without_merging_their_snapshots`). The `isinstance` guard rejecting an unresolved/compare argument (`temporal.py:232`) and `ResolvedTemporalSelector.__post_init__`'s `CompareSelector` `TypeError` (`temporal.py:53`) are **UNTESTED** |
| h | `serialize_temporal_evidence` emits original text/tz/precision plus UTC fields; unknowns null + kind/precision; no NL date resolution | PROVEN | `test_temporal_serialization_keeps_every_clock_and_original_precision` asserts the exact dict. `validity_kind`/`temporal_precision`/`source_precision` always emitted alongside nulls; no parsing anywhere in the module |
| i | `SourceOrder`/`OrderingKind`/`OrderingRelation` as specified; generic code never sorts provider tokens | **VIOLATED** | `OrderingKind` PROVEN (`conflicts.py:13`). No sorting of `provider_token` anywhere — PROVEN (`test_equality_only_tokens_are_never_sorted_as_versions`). **`OrderingRelation` does not exist** and `SourceOrder` has no relation field — see F3 |
| j | `ConflictCandidate` validation: one workspace, matching assertion/version IDs, nonempty unique support | PROVEN | `conflicts.py:59-73`; `test_candidate_rejects_mismatched_version_and_duplicate_support`. "One workspace" is trivially satisfied (a candidate holds one `Assertion`); no cross-candidate workspace check exists, but every grouping key includes `workspace_id`, so sets never cross workspaces |
| k | `select_same_source` grouping key; unique greatest ordinal wins; ties/equality-only/unknown remain alternatives; `recorded_from`/`observed_at`/list order never tie-break; duplicates collapse | **VIOLATED** | Ordinal selection PROVEN (`test_monotonic_same_source_selects_newest_adapter_ordinal_not_arrival_order`); no ingest-order tie-break PROVEN (`test_list_order_and_recorded_time_do_not_break_unknown_order_ties`); ties/equality-only/unknown PROVEN; exact-duplicate collapse PROVEN. **Violated**: the grouping key omits the ordering adapter — see F4. **UNTESTED**: the adapter-mismatch fallback; a 3+-ordinal series |
| l | `build_conflict_sets`: caller cardinality; never crosses scope; `multiple` compatible; `single` unresolved/possible; explicit non-overlap → no set; exact intersection or null/null; IDs sorted unique; never `resolved`/`dismissed` | PROVEN (partial) + 1 deviation | All PROVEN by name: `test_multiple_cardinality_keeps_alternatives_without_a_false_conflict`, `test_distinct_environment_scopes_do_not_conflict`, `test_explicit_nonoverlapping_intervals_do_not_conflict`, `test_explicit_overlap_records_exact_half_open_intersection`, `test_unknown_effective_overlap_is_possible_without_an_invented_interval`, `test_independent_single_valued_sources_create_one_unresolved_conflict`, `test_conflict_identity_is_deterministic_under_input_reordering`. `resolved`/`dismissed` are never constructed (`conflicts.py:178`). **Deviation**: atemporal sets return null bounds with `unresolved`, while §3 says null bounds ⇒ `possible` — see F6. **UNTESTED**: `_pairwise_conflicts` (`conflicts.py:185-193`) has zero suite coverage |
| m | No store reads, model calls, or ambient clock calls | PROVEN | `rg -n "datetime.now\|utc_now\|time\(\)\|store\.\|ollama\|httpx" src/hippo/knowledge/temporal.py src/hippo/knowledge/conflicts.py` → **no matches** (exit 1). Imports are `dataclasses`, `datetime`, `typing`, `collections`, `. model`, `.identity` only. Every cutoff is injected via `latest_known_at` |
| n | Fixture covers the nine §7 step 3 scenarios | PARTIAL | 8 of 9 fully present, 1 partial, and the file is loaded by nothing — see below and F8 |

## Item n — fixture scenario coverage

`tests/fixtures/rag_all/temporal_events.jsonl`, 12 rows, all valid JSON.

| §7 step 3 scenario | Present | Row(s) |
| --- | --- | --- |
| May ownership correction | yes | 1–3 (`may_owner_alice`, `may_owner_bob`, `backdated_correction`, `recorded_from` 2026-05-12 backdating `valid_from` 2026-04-01) |
| Imported-old-last | yes | 4 (`old_imported_last`, ordinal 1 recorded 2026-05-13 after ordinal 2 recorded 2026-05-10) |
| Equal timestamp / different bytes | **partial** | 5–6 (`equal_order_different_bytes`) — equality is expressed as an equal **ETag** (`token: "etag-same"`), not an equal timestamp. No row in the file carries `source_updated_at` at all, so the named "equal source timestamp, different bytes" case is not represented |
| Unknown date | yes | 7 (`unknown_date`, `kind: unknown`, null bounds) |
| Environment collision | yes | 8 + 9 (`service-a:staging` vs `service-a:production`) |
| Independent-source alternatives | yes | 9 (`independent_alternative`, source `accepted-prd`) |
| Ordinary tombstone | yes | 10 (`current_only`, reason `tombstone`, epoch 5) |
| All-history purge | yes | 11 (`all_history`, reason `purge`, epoch 6) |
| Explicit restoration barrier | yes | 12 (`restoration_barrier: "confirmed:9"`) |

Missing: nothing outright; one partial (equal-timestamp variant). See F8 for the larger problem —
no code reads this file.

## Findings

### F1 — blocker — independent-source corroboration raises `ValueError`

`src/hippo/knowledge/conflicts.py:103-110` (`_deduplicate`, one of the two late patches).

`AssertionVersion.identity_fields` (`model.py:534-546`) excludes `source_id` and
`support_span_ids`. Two independent sources that corroborate the same claim in the same recording
transaction therefore produce the **same** `version.id` with different `source_id` and different
support spans. `_deduplicate` keys on `version.id` alone and raises whenever two candidates share an
ID but differ in any field:

```
source_id in AssertionVersion.identity_fields?: False
two independent sources, same claim, same recorded_from -> same version id?: True
  select_same_source:  RAISES -> One assertion version has conflicting candidate metadata
  build_conflict_sets: RAISES -> One assertion version has conflicting candidate metadata
```

Adding a genuine rival (`alice` from two sources plus `bob` from a third) also raises, so a real
conflict that should be indexed is lost to an exception instead.

Why it matters: §1 requires that "claims from independent sources never supersede one another" and
§3 requires that "independent sources remain represented in the set." Corroboration is a normal,
expected input, not an attack. The pure builder now hard-fails on it.

Why the suite misses it: `test_same_target_from_independent_sources_is_support_not_conflict`
(`test_temporal_conflicts.py:270-274`) passes **only** because it sets `recorded_from=MAY_5` on the
second candidate; `recorded_from` *is* in `identity_fields`, so the two versions get different IDs
and the raise is dodged. Remove that one argument and the test fails. Meanwhile
`test_one_version_id_cannot_be_rebound_to_another_source` (`test_temporal_conflicts.py:277-283`)
uses the default `recorded_from` and **asserts the crash is correct** — the test name diagnoses
ordinary corroboration as a rebinding attack and locks the defect in.

Note this is not a "revert the patch" finding. The pre-patch behavior (`unique[...] = candidate`,
last-wins) was also wrong: it silently dropped a candidate based on input order, violating item k's
"list order is never a tie-breaker." Patch 2 converted a silent order-dependent drop into a loud
crash. Both are wrong; the root cause is that `ConflictCandidate.source_id` is singular while the
model's support relation is many-to-one.

Proposed fix, either branch (an ownership/contract call for the orchestrator):
- (a) Amend §3 to state that trusted storage closure emits exactly one candidate per version with
  merged support, and define how multiple contributing sources are represented (e.g.
  `source_ids: tuple[str, ...]`). Then `_deduplicate`'s raise becomes a correct invariant check.
- (b) Keep the current candidate shape and make `_deduplicate` **merge** candidates whose
  `assertion` and `version` compare equal and that differ only in `source_id`/`support_span_ids`,
  unioning support spans and recording the contributing sources; raise only on genuinely
  irreconcilable metadata (a different `order` contract for the same version).

Either way, retire or rewrite `test_one_version_id_cannot_be_rebound_to_another_source`, and change
`test_same_target_from_independent_sources_is_support_not_conflict` to use an identical
`recorded_from` so it actually exercises the corroboration path.

I cannot inspect the pre-patch revision (these files are uncommitted and untracked), so I cannot say
whether either test was adjusted alongside the patch.

### F2 — major — `as_of` and `during` upgrade imprecise effective bounds to exact instants

`src/hippo/knowledge/temporal.py:168` (`_point`) and `temporal.py:182-189` (`_during`, both the
`overlaps` and `throughout` branches).

§1: "Parsing or serialization may never turn day/month/year/unknown precision into an exact-instant
claim." `_changes` honors this (`temporal.py:212`, `if clock is None or precision != "instant"`), but `_point`
and `_during` compare `valid_from`/`valid_to` directly and never read `record.temporal_precision`.
The same record is therefore honest under one predicate and false under the other two:

```
record: valid_from=2026-01-01, temporal_precision="year", source_timestamp_original="2026"
  as_of 2026-03-01        -> proven     effective_match        <-- upgrades "2026" to an exact instant
  changes/effective       -> contextual change_clock_unknown
  during/throughout       -> proven     effective_match
```

A source that said only "2026" is being reported as having *proven* validity on 1 March.

Proposed fix: apply the same guard used by `_changes` — when
`record.temporal_precision != "instant"`, return `contextual` / `effective_unknown` from `_point`
and `_during` rather than `proven`. A precision-window-aware rule (proven when the requested point
or interval lies wholly outside the bound's uncertainty window, contextual when it falls inside)
would be more accurate and would preserve more proven matches, but that is a §2 clarification the
plan does not currently specify — raise it with the orchestrator rather than inventing it here.

### F3 — major — `OrderingRelation` is not implemented

`src/hippo/knowledge/conflicts.py:13` and the `SourceOrder` definition at `conflicts.py:22-48`.

§3 specifies `OrderingRelation = Literal["older", "same", "newer", "ambiguous"]` and requires
`SourceOrder` to carry "an adapter-produced **relation**/ordinal." `rg -n "OrderingRelation"` across
the repo matches only the plan and this brief — neither the type alias nor any relation field
exists. `SourceOrder` exposes ordering solely as `monotonic_ordinal: int | None`.

Why it matters: an adapter that can compare two revisions pairwise ("B is newer than A") but cannot
produce a stable global integer ordinal has no way to express order, and must declare `unknown`.
That silently discards deterministic ordering the source actually provides. There is also no way to
express an explicit `ambiguous` relation; ambiguity is only ever inferred by `select_same_source`.

Proposed fix: add the `OrderingRelation` alias and an optional adapter-supplied relation to
`SourceOrder`, with `__post_init__` validation that a relation is accepted only for `monotonic`
adapters and is consistent with any ordinal supplied. If the ordinal-only design was a deliberate
simplification, amend §3 to say so — the plan and the code must not disagree silently.

### F4 — major — `select_same_source` grouping key omits the ordering adapter

`src/hippo/knowledge/conflicts.py:91-100` (`_series_key`) and `conflicts.py:119-132`.

§3 requires grouping by `(source_id, ordering adapter, series key, workspace, subject, predicate,
scope)`. `_series_key` returns `(source_id, series_key, workspace_id, subject_id, predicate,
scope_key)` — the adapter is absent. Adapter identity is instead checked *inside* the merged group
(`contracts` set, `conflicts.py:120-121`); if members disagree on
`(adapter_id, adapter_version, kind)`, the whole group degrades to non-monotonic:

```
two distinct adapters, same series -> current: 2  superseded: ()  refetch: True
same adapter,          same series -> current: 1  superseded: 1
adapter VERSION bump only          -> current: 2  superseded: 0   refetch: True
```

The direction of the error is safe (no false supersession), but deterministic supersession that the
adapters *did* prove is lost, `superseded_version_ids` is wrongly empty, and `requires_refetch`
fires spuriously — triggering canonical refetches that the spec does not call for. The third line is
the sharpest case: a routine adapter version bump collapses an otherwise well-ordered series to
ambiguous.

Proposed fix: put `(order.adapter_id, order.adapter_version)` into `_series_key` so each adapter
contract forms its own series and resolves independently, as §3 specifies. Keep the in-group
`contracts` check as a defensive assertion — after the key change it should be unreachable.

### F5 — minor — the anti-forgery guard validates JSON↔field consistency but not the invariants that matter

`src/hippo/knowledge/temporal.py:52-65` (`ResolvedTemporalSelector.__post_init__`, the other late
patch).

The added check (`temporal.py:64-65`) recomputes `_selector_payload` and compares, which does stop a
caller from attaching arbitrary identity JSON to a resolved selector. Two gaps remain:

1. **The origin label is still forgeable.** The `known_at_source` consistency check
   (`temporal.py:58-63`) is guarded by `if explicit is not None`. `CurrentSelector` and
   `AtemporalSelector` have no `known_at` field at all, so the check is skipped entirely and
   `known_at_source="explicit"` is accepted with nothing explicit behind it. `known_at_source` is
   also excluded from `selector_json`, so the canonical-identity guard cannot catch it either:
   `ResolvedTemporalSelector(CurrentSelector(), MAY_12, "explicit", <valid json>)` → accepted. Audit
   metadata can claim a cutoff was caller-pinned when it was the injected latest.
2. **The cutoff bound is not enforced.** `known_at <= latest_known_at` is checked only in
   `_resolve_single` (`temporal.py:127-128`), not in the dataclass. A directly constructed resolved
   selector carrying a year-2099 cutoff is accepted and `match_temporal` proceeds normally:
   `constructed known_at: 2099-01-01 00:00:00+00:00 -> match_temporal accepts: proven`.

Proposed fix: `selector_json` is fully derived from the other fields, so stop accepting it as a
constructor argument — compute it in `__post_init__` via `object.__setattr__` (the pattern already
used for `known_at`). That removes the forgery surface, removes the double
`model_dump` + `canonical_json` per resolution, and makes the parameter impossible to get wrong.
Separately, require `known_at_source == "latest"` unless an explicit cutoff is present on the
selector or was inherited from a `CompareSelector` parent (pass that intent in explicitly rather
than inferring it from a `getattr` miss).

### F6 — minor — atemporal conflicts return null bounds with `unresolved`, contradicting §3

`src/hippo/knowledge/conflicts.py:146-147` and `conflicts.py:169-170`.

§3: "Conflict interval is the exact half-open intersection when it is provable; otherwise both
bounds remain null and status is `possible`." An all-atemporal group returns `(None, None)` from
`_explicit_intersection`, which is not `None`, so `possible` stays false:
`atemporal -> unresolved bounds: None None`.

The behavior is arguably the semantically correct one — timeless claims genuinely do coexist, so
`unresolved` is honest — and `test_atemporal_single_values_conflict_without_inventing_effective_bounds`
asserts it deliberately. But the code and the plan currently disagree, and a reader reconciling them
cannot tell which is authoritative. Proposed fix: amend §3 to carve out the atemporal case
explicitly ("null bounds with `unresolved` when every member is atemporal; null bounds with
`possible` when overlap is merely unprovable"), or change the code. Do not leave it implicit.

### F7 — minor — `recorded_match` is a declared reason that is never emitted

`src/hippo/knowledge/temporal.py:19`.

`rg -n "recorded_match" src/ tests/` matches only the `TypeAlias` declaration. Recorded eligibility
is a precondition in `match_temporal` (`temporal.py:235`) — passing it is never reported as a
positive reason, only failing it is (`recorded_after_cutoff`, `recorded_closed`). So a
recorded-only proof is currently unrepresentable, and consumers switching on `TemporalReason` must
handle a member that cannot occur. Proposed fix: either emit it (a `current`/`as_of` match that is
recorded-eligible but effective-unknown could carry it instead of the more generic
`effective_unknown`), or drop the literal and note in §2 that recorded eligibility is reported only
by its failure reasons.

### F8 — minor — the fixture is loaded by no code and validated by no test

`tests/fixtures/rag_all/temporal_events.jsonl`.

`rg -rn "temporal_events"` matches only `docs/rag_it_all.md` and
`docs/rag_it_all_remaining_tasks.md` (both as prose, and both naming the file `n.jsonl`). No test
opens it. Per §6 the chronological JSONL loader is correctly deferred until its owner is released,
so staging the data ahead is reasonable — but nothing pins its shape. The file carries three
distinct row schemas (claim rows with `provider_order`; suppression rows with `suppression` and no
`claim`/`valid_from`; one restoration-barrier row) and no schema is documented anywhere.

Proposed fix: add a cheap schema test now — parse every line, assert the nine scenario `case` values
are present and that each row shape has its required keys. That costs little, keeps the fixture from
drifting before its consumer lands, and makes the §7 step 3 coverage claim enforceable rather than
asserted in a report.

### F9 — minor — half-open interval math is implemented three times

`temporal.py:168` (`_point`), `temporal.py:182-189` (`_during`), `conflicts.py:145-158`
(`_explicit_intersection`) — alongside `model.TimeInterval` (`model.py:1151`), which already owns
the half-open invariant. Each site re-derives containment/overlap/intersection independently. F2 is
a direct consequence: the precision rule was added to one site and not the others. Proposed fix:
give `TimeInterval` (or a small shared helper in `temporal.py`) `contains`, `overlaps`, `covers` and
`intersect` operations that understand open upper bounds, unknown lower bounds and precision, and
have all three call sites use them. Also at `conflicts.py:154`, prefer
`if candidate.version.valid_to is not None` over the current truthiness test — `datetime` has no
`__bool__` so the behavior is correct today, but the intent is not obvious.

## QUALITY review (brief step 3)

**Mutable fields inside frozen dataclasses** — clean. All dataclasses are `frozen=True`; sequence
fields are tuples; `k.Assertion`/`k.AssertionVersion`/`k.TimeInterval` inherit
`Contract.model_config` with `frozen=True` (`model.py:101-104`). No mutable default arguments.

**Validation vs alternate constructors** — sound. All invariants live in `__post_init__`, which
`dataclasses.replace()` re-runs, and `ConflictCandidate` checks support-span uniqueness *before*
normalizing the tuple order (`conflicts.py:65-73`), so sorting cannot mask a duplicate. The one
smell is `ResolvedTemporalSelector.selector_json` (F5): a fully derived value accepted as a
constructor parameter that can only ever be wrong.

**Duplicated interval math** — see F9. Three independent implementations; F2 is the bug this
duplication produced.

**Happy-path-only tests** — the significant gap.
- item b: reversed/empty `TimeInterval` and `ChangesSelector` rejection is model-level only.
- item f: `during/throughout` with an unknown lower bound; `current` against a closed recorded
  interval; any excluded `changes` outcome — `change_outside` is asserted **0** times, so the
  excluded branch at `temporal.py:224` never runs in the suite.
- item g: neither `TypeError` guard (`temporal.py:53`, `temporal.py:232-233`) is exercised.
- item k: the adapter-mismatch fallback (`conflicts.py:120-121`) and a 3+-ordinal series are
  untested; both were reachable only via my own probes.
- item l: `_pairwise_conflicts` (`conflicts.py:185-193`) has **zero** suite coverage. I verified it
  works and is order-independent (`A=[1,5) B=[5,10) C=[1,20)` → 2 sets, forward == reverse), but
  nothing in the repo protects that. Minor related observation: a group whose whole-set intersection
  is empty fragments into pairs with no maximal-clique consolidation — the plan does not require
  cliques, so this is a note, not a finding.

**Ordering dependent on dict/set iteration** — clean, and better than typical. Every return path is
explicitly sorted: `_deduplicate` (`conflicts.py:110`), `select_same_source`'s three tuples
(`conflicts.py:133-137`), `ambiguous_series` via `canonical_json`, `build_conflict_sets`
(`conflicts.py:214`), and the ID tuples inside `_conflict` (`conflicts.py:175-181`). The `contracts`
set is used only for `len()` and a `next(iter(...))` that is reached only when `len == 1`
(`conflicts.py:121-122`), so iteration order cannot leak. `source_versions` feeds only an `any()`.
`test_conflict_identity_is_deterministic_under_input_reordering` and
`test_list_order_and_recorded_time_do_not_break_unknown_order_ties` lock the important cases.

**Naming and structure** — good. Both modules are small, single-purpose and readable; docstrings
state what the module does *not* do, which is the right emphasis for a pure layer. Error messages
are clear prose, with one exception: `_deduplicate`'s raise (`conflicts.py:108`) names no version
ID, assertion or source, which will be painful to debug in an ingestion pipeline — worth including
the offending `version.id` and both `source_id`s regardless of how F1 is resolved.

## Item 4 — §4–§6 encroachment check

**None found.** Confirmed absent from both modules: no `TemporalPublicationPlan`; no history
selection service; no `HistoryManifest`, `EvidenceAccess`, `EvidenceSelection`, `QuerySnapshot` or
`coverage_json` reference; no import of `store`, `access`, `snapshots`, `lifecycle` or
`generations`. Imports are limited to the stdlib plus `knowledge.model` and `knowledge.identity`.
`model.py`, `access.py`, `snapshots.py`, `lifecycle.py` and `store/*` are untouched — the git status
for this branch lists only the two new `knowledge/` modules, their two test files and the fixture as
additions under this slice's ownership. T5A5's 206 passing regressions corroborate that no shared
contract moved.

## Recommendation

Do not mark Task 5A's pure increment complete. F1 must be resolved before the modules are wired to
anything, because it rejects a normal input and the suite currently certifies that rejection as
correct. F2 should land with it — it is a three-line change to two functions and it is the kind of
honesty guarantee §1 exists to provide. F3 and F4 are plan-vs-code divergences that need an
orchestrator decision (fix the code or amend §3) rather than a silent choice by the next
implementer. F5–F9 are safe to fold into the §4–§6 integration work.
