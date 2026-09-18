# Re-review — Task 5A pure temporal/conflict fixes (F1–F5) plus the coarse-precision overlap fix

Reviewer: `opus-3` (herdr fleet, root tree). Date: 2026-09-11.
Brief: `ai_docs/handoffs/briefs/rereview-temporal-pure.md`. Decisions re-reviewed against:
`ai_docs/handoffs/briefs/fix-temporal-pure.md` DECISIONS block.
Original review: `ai_docs/reports/2026-09-11-temporal-pure-review.md`.
Under review: `src/hippo/knowledge/temporal.py`, `src/hippo/knowledge/conflicts.py`,
`tests/unit/test_temporal_evidence.py`, `tests/unit/test_temporal_conflicts.py`,
`tests/fixtures/rag_all/temporal_events.jsonl`, all committed at `cb92ba7`
("Add pure bitemporal selectors and deterministic conflict sets").

## Verdict

**RE-REVIEW: PASS.** F1–F5 are each fixed correctly, match the orchestrator's decisions, and are
each covered by a test that asserts the exact behavior the original review showed was wrong. (I read
the tests against the pre-fix behavior documented in that review rather than re-running them against
reverted code, since `temporal.py` is outside this worker's ownership.) Open finding 4 is now fixed
(RED-first) and open item 5 is recorded in the plan as decided. Two new **minor** findings and three
observations are listed below; none blocks the pure increment. Both minor findings are reproducible
from pure inputs today, but neither has a production caller until the §4–§6 integration lands.

## 1. Open finding 4 — fixed

Decision: when either candidate's effective bounds carry a `temporal_precision` other than
`"instant"`, overlap cannot be proven, so the set is `possible` with null bounds, with no
window-widening arithmetic.

- Code: `src/hippo/knowledge/conflicts.py:184` — a two-line guard in `_explicit_intersection`,
  placed *after* the all-atemporal return (`conflicts.py:178`) and *after* the
  `validity_kind != "explicit_interval"` check (`conflicts.py:180`), so it returns `None`
  ("unprovable") and never `()` ("provably empty"). `_conflict` then produces
  `resolution_status="possible"` with `valid_from=valid_to=None`, the same path an unknown-validity
  member already takes. The docstring at `conflicts.py:172-176` states the rule.
- Test: `tests/unit/test_temporal_conflicts.py:420`
  `test_coarse_effective_precision_can_never_prove_a_conflict_overlap` — year-precision alice versus
  instant bob yields `possible` with null bounds and is input-order independent; the same test
  re-runs the pair with instant precision on both sides and asserts `unresolved` with the exact
  `(MAY_1, JUNE_1)` intersection, so an over-broad guard fails it too.
- The test helper gained an optional `precision=` argument (`test_temporal_conflicts.py:76,102`);
  its default reproduces the previous derivation exactly, so no existing case changed.
- RED: `/tmp/hippo-temporal-rereview-red.log` — `1 failed, 29 passed`, failing exactly on
  `assert 'unresolved' == 'possible'`.
- Plan: `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` §3, conflict-interval bullet,
  sentence marked "Amended 2026-09-11 after re-review".

**Documented consequence (not a deviation).** Because the guard applies to the whole logical group,
one coarse-precision member makes the group's whole-set intersection unprovable, so
`build_conflict_sets` returns a single `possible` set over all members instead of descending into
`_pairwise_conflicts`. Two members that are provably disjoint on their own (bob `[May 1, May 10)`
versus carol `[May 10, Jun 1)` → no set) are therefore absorbed into that one `possible` set when a
year-precision alice is present. Verified with `/tmp/probe_rereview.py`. This is exactly what an
`unknown`-validity member already does today and is what "exactly like an unknown-overlap case"
prescribes; a per-pair precision rule would be a different decision and is not taken here.

## 2. Open item 5 — recorded, no code change

`select_same_source` reports `superseded_version_ids` per series (`conflicts.py:156`), so one version
ID can be superseded inside one series while remaining current in another. Reproduced directly:
with one version corroborated by `catalog-a` (superseded there by a newer ordinal) and `catalog-b`
(current there), the ID appears in both `superseded_version_ids` and `current`
(`/tmp/probe_rereview.py`, section "item 5"). Recorded in plan §3, independent-sources bullet, as
"Amended 2026-09-11 after re-review", with the requirement that the integration slice (§4–§6) key
supersession by series when persisting.

## 3. F1–F5 verdicts

| # | Original finding | Verdict | Evidence |
| --- | --- | --- | --- |
| F1 | `_deduplicate` raised on ordinary independent-source corroboration | **CORRECT** | `conflicts.py:127-139`. Collapse is keyed on `_candidate_key` (assertion, version, source, support, canonical order JSON) at `conflicts.py:102-109`, so exact duplicates collapse idempotently while per-source candidates survive. The raise (`conflicts.py:133-137`) fires only when two candidates share `version.id` but carry non-equal typed `(assertion, version)` records, and it names the version ID and both source IDs. Tests: `test_one_version_id_from_two_sources_is_corroboration_not_a_rebinding` (`:359`), `test_exact_duplicate_version_is_idempotently_collapsed` (`:318`), `test_one_version_id_cannot_carry_divergent_identity_metadata` (`:326`), `test_same_target_from_independent_sources_is_support_not_conflict` (`:490`, now with an identical `recorded_from` so it exercises the real path), `test_corroborated_alternative_and_a_rival_form_one_conflict_with_merged_support` (`:498`), `test_pairwise_conflicts_keep_corroborating_support_in_one_deterministic_alternative` (`:515`). |
| F2 | `as_of`/`during` upgraded coarse precision to exact instants | **CORRECT** | `temporal.py:219-220` (`_point`) and `temporal.py:236-237` (`_during`, before either interval branch) return `contextual` / `effective_imprecise`, the same guard `_changes` applies at `temporal.py:264`. `effective_imprecise` is a declared reason (`temporal.py:21`) and plan §2 was amended to name it. Test: `test_coarser_than_instant_effective_bounds_are_never_proven_by_point_or_interval_predicates` (`test_temporal_evidence.py:230`) covers `as_of`, `during/throughout`, `during/overlaps` and `current` at year and day precision, and asserts the reason is `effective_imprecise` for all four. |
| F3 | `OrderingRelation` unimplemented | **CORRECT** | `compare_orders` at `conflicts.py:89-99` returns `older`/`same`/`newer` only for the same `(adapter_id, adapter_version, series_key)` with both sides `monotonic` and both ordinals present; everything else is `ambiguous`. `select_same_source` makes its only supersession decision through it (`conflicts.py:152`), so the rule lives once. Tests: `test_compare_orders_relates_ordinals_only_within_one_adapter_contract_and_series` (`:152`) and `test_compare_orders_reports_ambiguous_for_every_order_it_cannot_prove` (`:162`), which covers different adapter, different adapter version, different series, `unknown`, `equality_only`, and an ordinal-less order forced past validation. Plan §3 amended to state ordinal-only in this increment with pairwise-only adapters deferred to Tasks 9–10. |
| F4 | `_series_key` omitted the ordering adapter | **CORRECT** | `_series_key` now includes `order.adapter_id` and `order.adapter_version` (`conflicts.py:117-118`) alongside source, series, workspace, subject, predicate and scope. The previous in-group `contracts` degradation check is gone, which is correct — after the key change it was unreachable, and `compare_orders` supplies the same protection across groups. Tests: `test_each_ordering_adapter_forms_its_own_series_and_supersedes_within_it` (`:191`, the reviewer's adapter-version-bump case: both series now supersede deterministically, `ambiguous_series == ()`), `test_two_adapters_on_one_series_never_request_a_spurious_refetch` (`:221`). |
| F5 | Forgeable origin label; cutoff bound unenforced; `selector_json` accepted as an argument | **CORRECT (with a residual, see N1)** | `selector_json` is `field(init=False)` and derived in `__post_init__` (`temporal.py:89,110`), so it cannot be supplied. `known_at > latest_known_at` raises at construction (`temporal.py:100-101`). `known_at_source="explicit"` is rejected when the selector carries no cutoff (`temporal.py:108-109`) and when it carries a different one (`temporal.py:104-107`). `latest_known_at` is now carried on the record. Tests: `test_resolved_selector_derives_its_canonical_identity_instead_of_accepting_one` (`test_temporal_evidence.py:77`), `test_resolved_selector_rejects_forged_origins_and_cutoffs_beyond_available_knowledge` (`:88`, including the year-2099 direct construction), `test_compare_labels_an_inherited_cutoff_without_claiming_the_side_pinned_it` (`:132`). |

## 4. Brief step 3 specific checks

- **(a) F1 raise condition** — CONFIRMED. `conflicts.py:133` compares whole typed
  `(assertion, version)` records, so two sources with byte-identical records never raise, and any
  `recorded_to` divergence does (verified: a closed mirror segment raises, naming the version ID and
  both sources). Scope note: because `AssertionVersion.identity_fields` (`model.py:534-546`) already
  covers every field except `recorded_to`, `source_timestamp_original` and `source_timezone`, any
  *other* difference produces a different version ID and simply becomes a second version rather than
  a raise — confirmed for `confidence`. The whole-record comparison is therefore stricter than
  "identity-relevant metadata" only for those three fields, which is the safe direction and is what
  decision (a) asks for.
- **(b) Merged support and source representation** — CONFIRMED with one clarification.
  `_conflict` builds `support_span_ids` from a set comprehension and sorts it (`conflicts.py:213-215`),
  so it is sorted and unique in both the whole-group path and the `_version_buckets` /
  `_pairwise_conflicts` path (`:515` asserts the bucketed case). Clarification: `k.ConflictSet`
  (`model.py:1118-1127`) has **no** source field, so "every contributing source ID is represented"
  is satisfied only through each source's support spans appearing in the merged tuple, which they
  do. The plan §3 sentence "with every contributing source represented" should be read that way; it
  currently reads as though sources were a field of the record.
- **(c) `compare_orders` across adapter versions** — CONFIRMED. `conflicts.py:91` compares the
  `(adapter_id, adapter_version, series_key)` triple before any ordinal is read, and
  `test_compare_orders_reports_ambiguous_for_every_order_it_cannot_prove` asserts the
  `adapter_version="v2"` case explicitly (`test_temporal_conflicts.py:176`).
- **(d) F5 constructor** — CONFIRMED for both properties (cutoff after `latest_known_at` raises;
  `selector_json` is derived and not accepted). See N1 for what the constructor still cannot check.
- **(e) Purity grep** — CONFIRMED empty:
  `rg -n "datetime.now|utc_now|time\(\)|store\.|ollama|httpx" src/hippo/knowledge/temporal.py src/hippo/knowledge/conflicts.py`
  → no matches, exit 1. Imports in both modules are stdlib plus `knowledge.model` and
  `knowledge.identity` only (`conflicts.py` additionally imports `_HalfOpen` from `temporal.py`).

## 5. New findings

### N1 — minor — the `known_at_source` origin label is still unverifiable for `latest` and `inherited`

`src/hippo/knowledge/temporal.py:98-109`.

F5 closed the `explicit` hole, but the two remaining labels are still accepted without a check the
constructor could make. Both of these are accepted today (verified, `/tmp/probe_rereview.py`
section "F5"):

```
ResolvedTemporalSelector(CurrentSelector(), MAY_10, "latest",    MAY_12)  -> accepted
ResolvedTemporalSelector(CurrentSelector(), MAY_10, "inherited", MAY_12)  -> accepted
```

The first is self-contradictory on the record's own data: `latest` means "the injected latest cutoff
was used", so `known_at` must equal `latest_known_at`. The second is not checkable from the record
alone (the parent `CompareSelector` is not carried), but it becomes checkable once the first rule
holds, since `inherited` is then the only label left for a non-explicit cutoff that differs from
latest. Audit metadata can currently record a caller-inherited cutoff as `latest`.

Impact: audit/identity metadata only; `selector_json` excludes `known_at_source`, so conflict and
manifest identity are unaffected, and `resolve_selector` itself always labels correctly
(`temporal.py:167-173`). Nothing in the current code path produces a wrong label.

Proposed fix (one line, `temporal.py`, not this worker's file): in `__post_init__`, after the
existing explicit checks, `if self.known_at_source == "latest" and self.known_at != self.latest_known_at: raise ValueError(...)`.
Fold into the §4–§6 integration, where directly constructed resolved selectors first appear.

### N2 — minor — `superseded_version_ids` can repeat one ID within a single series

`src/hippo/knowledge/conflicts.py:156,161`.

Distinct from open item 5 (which is about one ID being superseded in one series and current in
another). Within *one* series, a source that contributes the same version under two different
support groups yields two candidates with the same `version.id` and different `_candidate_key`s;
when a newer ordinal supersedes them, both are appended and the tuple carries the ID twice
(verified, `/tmp/probe_rereview.py` trailing probe):

```
superseded: ('assertionversion-c72c9b...', 'assertionversion-c72c9b...')
```

Plan §3 requires sorted-unique IDs for `ConflictSet` and is silent for `SameSourceSelection`, so
this is a hygiene defect rather than a contract violation, and `ConflictSet` construction is
unaffected (it de-duplicates via a set). It matters for the integration slice, where the list drives
persistence and a repeated ID means a repeated closure attempt.

Proposed fix: `superseded_version_ids=tuple(sorted(set(superseded)))` at `conflicts.py:161`, with a
test that one version superseded under two support groups appears once. Same file and same field as
item 5, so both are best handled in one change when §4–§6 lands.

## 6. Observations (not findings)

- `conflicts.py:12` imports the private `_HalfOpen` from `temporal.py`. F9's "implement the half-open
  math once" decision made it a shared helper, so the leading underscore now understates its scope.
  Renaming it to a public `HalfOpen` (or moving it beside `model.TimeInterval`) would match its use.
- `_changes` (`temporal.py:272`) still inlines `interval.start <= clock < interval.end` rather than
  going through `_HalfOpen`. The F2/F9 decision named `_point`, `_during` and
  `_explicit_intersection` only, and `k.TimeInterval` guarantees a closed non-empty interval here, so
  the inline comparison is correct; noting it so the last duplicate is not forgotten.
- `_deduplicate`'s error message names whichever candidate was seen first, so the two source IDs can
  swap places under input reordering. The raise itself is order-independent; only the message text
  varies.

## 7. Gate results

Run from `/Users/mascott/projects/hippo` with `.venv/bin/python` (3.12.11), `HIPPO_TEST_STORE=fake`,
`-W error`, commands exactly as written in
`ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/GATES.md`. No `filterwarnings` form was needed:
neither test module imports `fastapi.testclient`.

| Gate | Baseline (before) | After the finding-4 fix | Log |
| --- | --- | --- | --- |
| T5A1 `test_temporal_evidence.py` | exit=0, 22 passed | exit=0, 22 passed | `/tmp/hippo-temporal-rereview-T5A1{-before,}.log` |
| T5A2 `test_temporal_conflicts.py` | exit=0, 29 passed | exit=0, **30 passed** | `/tmp/hippo-temporal-rereview-T5A2{-before,}.log` |
| T5A5 regression suite (6 files) | exit=0, 206 passed, 1 skipped | exit=0, 206 passed, 1 skipped | `/tmp/hippo-temporal-rereview-T5A5{-before,}.log` |
| T5A6 Ruff check + `format --check` | exit=0, all checks passed, 4 files already formatted | exit=0, all checks passed, 4 files already formatted | `/tmp/hippo-temporal-rereview-T5A6{-before,}.log` |

RED for finding 4: `/tmp/hippo-temporal-rereview-red.log` (exit=1, `1 failed, 29 passed`).
T5A3/T5A4 not run: they are unstarted §4–§6 integration gates whose `-k` filters match no collected
test.

## 8. Files changed by this re-review

- `src/hippo/knowledge/conflicts.py` — the `_explicit_intersection` precision guard and its docstring.
- `tests/unit/test_temporal_conflicts.py` — `precision=` helper argument, `JAN_1`/`NEXT_JAN_1`
  constants, and `test_coarse_effective_precision_can_never_prove_a_conflict_overlap`.
- `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` — two §3 sentences marked
  "Amended 2026-09-11 after re-review".
- `ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/GATES.md` — one appended `EVIDENCE:` line
  under T5A2 and one under T5A6. Checkboxes untouched; the orchestrator's checker lines are intact.
- This report. No commits; `temporal.py`, `test_temporal_evidence.py` and the fixture were not
  modified.
