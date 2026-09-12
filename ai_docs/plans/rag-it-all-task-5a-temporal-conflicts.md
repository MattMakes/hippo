# Task 5A: bitemporal evidence and deterministic conflicts

Status: preflighted contract. The pure temporal/conflict increment owns only new files and may proceed. Store, model, access, snapshot, lifecycle, migration, fixture-loader, and generation-publication changes remain reserved until root releases their current owners.

Governing design: `docs/rag_it_all.md` sections 5.5, 7.5–7.9, 12.3, Task 5A, and gate G18.

Gate ledger: `ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/GATES.md`.

## 1. Non-negotiable semantics

- Normalize every computed instant to UTC and reject naive datetimes. Preserve the provider's original timestamp text, declared timezone, and precision. Parsing or serialization may never turn day/month/year/unknown precision into an exact-instant claim.
- Use half-open intervals `[start, end)`. A missing upper bound is open-ended. A missing lower bound is unknown and never means negative infinity. Empty and reversed effective, recorded, selector, or conflict intervals fail before persistence.
- Effective time and recorded time are independent. `valid_from/to` describe when a source supports a claim; `recorded_from/to` describe when Hippo exposed that interpretation. `observed_at`, `source_updated_at`, and `Generation.published_at` remain distinct.
- Current authorization and suppression are evaluated independently of temporal selection and are rechecked before result release. Historical mode changes only `current_only` tombstone behavior; `all_history` access-loss/purge suppression still denies. A snapshot or history manifest is reachability, not an access grant.
- Arrival or ingestion order never proves source order. Only an adapter-declared monotonic ordering result can deterministically replace an earlier claim from the same source and logical series. ETags, Git SHAs, equality-only tokens, equal source timestamps with different bytes, and unknown ordering preserve ambiguity and request canonical refetch.
- Claims from independent sources never supersede one another merely because one was ingested or modified later. Cardinality and question scope decide whether alternatives conflict. Multiple values for a declared multi-valued predicate are compatible; differing values for a single-valued declaration in the same workspace/subject/predicate/scope and overlapping effective context form a conflict.
- Environment, database instance, repository/ref, and other adapter scope are part of `Assertion.scope_key`. Distinct scopes do not conflict and cannot form a same-time path.
- Recorded corrections are append-only. Publication may mutate only a previously open version's `recorded_to`, exactly once and monotonically, while appending corrected historical segment(s), the new state, generation membership, publication event, and source pointer in the same transaction. Original bytes and prior closed segments are immutable.
- Optional model conflict suggestions are read-only candidates. They do not close versions, choose winners, change cardinality, merge identities, grant access, or become authoritative without a configured deterministic rule and supported evidence.

## 2. Pure temporal API (`knowledge/temporal.py`)

The first increment is backend-independent and contains no store reads, model calls, or ambient clock calls.

### Public immutable contracts

- `TemporalDisposition = Literal["proven", "contextual", "excluded"]`.
- `TemporalReason` is a closed literal set covering at least `effective_match`, `recorded_match`, `effective_unknown`, `recorded_after_cutoff`, `recorded_closed`, `effective_outside`, `change_match`, `change_clock_unknown`, and `atemporal_match`. Amended 2026-09-11 after review: the set also contains `effective_imprecise`, the contextual reason returned when a record's effective bound is coarser than an exact instant, so `as_of`, `during`, and `current` refuse to prove such a bound exactly as `changes` already refuses.
- `ResolvedTemporalSelector` contains one non-compare selector, its resolved `known_at`, and the exact selector JSON used for identity/audit. `resolve_selector(selector, *, latest_known_at)` returns one item, or an ordered `(left, right)` pair for compare. Explicit `known_at` wins; otherwise the injected latest cutoff is used. Contradictory global/side snapshot IDs or cutoffs raise rather than override. Amended 2026-09-11 after review: it also carries the `latest_known_at` it was resolved against and rejects a later `known_at` at construction, derives `selector_json` itself instead of accepting it as an argument, and labels its origin `explicit` (the selector's own cutoff), `inherited` (a `CompareSelector` parent's cutoff), or `latest`, with `explicit` rejected unless the selector itself carries that cutoff.
- `TemporalInputs` binds one `TemporalRecord` to optional `source_updated_at`, `observed_at`, and `published_at`. It preserves the typed record; missing clocks remain `None`.
- `TemporalMatch` contains disposition, reason, resolved known/effective/change interval, and the record ID. It never contains inferred dates.

### Predicate behavior

- Recorded eligibility is `recorded_from <= known_at < recorded_to`, with a missing `recorded_to` open-ended.
- `as_of` proves explicit validity only when the point is inside a sufficiently bounded interval. `unknown` and `observed_snapshot` may be returned as labeled contextual evidence after recorded eligibility; they are excluded from time-proven claims. `atemporal` is proven only for `validity_kind="atemporal"` and contextual for unknown/snapshot evidence.
- `during/overlaps` proves an explicit interval intersects the requested interval. `during/throughout` proves the evidence covers the entire requested interval. An unknown lower bound cannot prove either predicate; missing upper is valid open-ended coverage.
- `current` uses the injected request cutoff for both recorded visibility and explicit effective applicability. The latest open recorded interpretation of `unknown` or `observed_snapshot` is contextual, not falsely dated. Current generation/snapshot selection remains a separate prerequisite.
- `changes` uses `[changes_since, changes_until)`. `published` uses the version publication clock (`published_at`, or `recorded_from` only where the caller explicitly binds them as the same publication event); `source_modified` requires `source_updated_at`; `effective` requires a source-supported explicit effective boundary. Missing or imprecise change clocks are contextual and receive no recency claim.
- `match_temporal(inputs, resolved)` is deterministic and side-effect free. Compare calls it independently for each side; it does not union the sides or infer a transition.
- `serialize_temporal_evidence(inputs)` emits original timestamp text/timezone/precision plus UTC effective, recorded, observed, source-modified, and published fields. Unknowns serialize as null plus their explicit kind/precision. It performs no natural-language date resolution.

## 3. Pure ordering and conflict API (`knowledge/conflicts.py`)

### Adapter ordering

- `OrderingKind = Literal["monotonic", "equality_only", "unknown"]`; `OrderingRelation = Literal["older", "same", "newer", "ambiguous"]`.
- `SourceOrder` carries adapter identity, series key, kind, opaque provider token, and an adapter-produced relation/ordinal only for a documented monotonic order. Generic code never lexically or numerically sorts provider tokens. Amended 2026-09-11 after review: `SourceOrder` keeps `monotonic_ordinal` as the only adapter-supplied ordering datum in this increment, and `OrderingRelation` is the return type of the pure `compare_orders(a, b)` in `conflicts.py` rather than a stored field: the same adapter identity and series with both sides `monotonic` and carrying ordinals yields `older`/`same`/`newer`, and a different adapter, a different series, `equality_only`, `unknown`, or a missing ordinal yields `ambiguous`. `select_same_source` makes every supersession decision through `compare_orders` so the rule lives once. Pairwise-only adapters (for example Git ancestry without a total order) are explicitly deferred to the connector tasks (Tasks 9–10) and must declare `unknown` until then.
- `ConflictCandidate` binds an authorized, temporally selected `Assertion`, `AssertionVersion`, exact complete support span IDs, source ID, and `SourceOrder`. Constructor validation requires one workspace, matching assertion/version IDs, nonempty unique support, and source/scope identity supplied by trusted storage closure. Amended 2026-09-11 after review: because `AssertionVersion.identity_fields` excludes `source_id` and support spans, several independent sources legitimately corroborate one version ID, so a candidate set holds one candidate per (version, source, support, ordering) tuple; exact duplicates collapse idempotently, candidates differing only in `source_id`, support spans, or `SourceOrder` are retained as separate per-source candidates, and only two candidates that share a version ID while carrying different typed assertion/version records raise. In `build_conflict_sets` those corroborating candidates are one alternative carrying the sorted unique union of their support span IDs with every contributing source represented, and they never form a conflict with each other.
- `select_same_source(candidates)` groups by `(source_id, ordering adapter, series key, workspace, subject, predicate, scope)`. A uniquely greatest adapter-normalized monotonic ordinal is the current same-source candidate; older candidates remain retained history. Equal ordinals with different versions, equality-only unequal tokens, and unknown/ambiguous ordering remain alternatives and request canonical refetch. `recorded_from`, `observed_at`, and list order are never tie-breakers. Exact duplicate IDs collapse idempotently.

### Conflict construction

- `Cardinality = Literal["single", "multiple"]` is supplied by the typed schema/catalog adapter or configured predicate policy; the generic predicate registry does not invent it.
- `build_conflict_sets(candidates, *, cardinality)` consumes only already-authorized and temporally applicable candidates after same-source selection. It groups by workspace/subject/predicate/scope and never across environments/scopes.
- `multiple` retains distinct objects as compatible alternatives. `single` creates a deterministic `ConflictSet` for distinct target objects when their effective contexts overlap or cannot be proven disjoint. Proven overlap is `unresolved`; unknown overlap is `possible`. Explicit non-overlap creates no set.
- Conflict interval is the exact half-open intersection when provable; otherwise both bounds are null (amended 2026-09-11 after review). Status is `unresolved` when overlap is proven (including atemporal claims, which are timeless and therefore genuinely coexist) and `possible` when it cannot be proven. Assertion-version IDs and support-span IDs are sorted and unique before constructing the record.
- Independent sources remain represented in the set. A same-source ambiguous set can be `possible`; a same-source deterministically older version has already been removed from the current candidate set but remains queryable in history.
- An authoritative resolution is a separate, configured operation. The pure builder never emits `resolved` or `dismissed`, and model suggestions never change its output.

## 4. Historical selection and authorization integration (after shared-file release)

Add a history-selection service in `knowledge/temporal.py` that operates in this order:

1. Resolve the selector using an injected UTC request cutoff. Reject compare unless the caller requests two independently pinned sides.
2. Build the broad retained evidence proof with `EvidenceAccess` in `query_mode="history"`; this applies live identity, workspace membership, artifact policy, complete AND support groups, and `all_history` suppression before time filtering.
3. Apply recorded/effective predicates only to authorized `ObjectObservation` and `AssertionVersion` rows. Preserve unknown-time rows in a separate contextual inventory. Never add an ID that was absent from the authorization proof.
4. Compute the exact revision closure from selected observations and surviving complete assertion support groups, then include only compatible retained link generations. Record retention gaps without fabricating missing revisions or dates.
5. Persist a canonical `HistoryManifest` with sorted unique IDs, exact resolved selector JSON and knowledge cutoff. `coverage_json` records separate proven/contextual counts and stable codes such as `history_unavailable`, `retention_gap`, or `link_coverage_incomplete`; it contains no private source text.
6. Build the final `EvidenceSelection(revision_ids=..., assertion_version_ids=..., query_mode="history")`, acquire a `QuerySnapshot` that pins the manifest, and revalidate current authorization/suppression before each dispatch and release. A requested cutoff before the earliest retained recorded interval returns `history_unavailable` rather than current evidence.

Amended 2026-09-11 after review: this history-selection service is what emits `recorded_match`; the pure predicates in section 2 report recorded eligibility only through its failure reasons (`recorded_after_cutoff`, `recorded_closed`), and a positive recorded-eligibility decision becomes a reported reason here, where recorded-only proofs are selected.

`current_only` tombstones can leave authorized retained history visible. Artifact/source/policy suppressions with `all_history`, current permission loss, or a purge barrier remove it even from an old snapshot. Collection treats live/durable history snapshots as roots; purge overrides those roots and yields `evidence_purged` markers without retained text.

## 5. Atomic correction/publication integration (after shared-file release)

Introduce a frozen `TemporalPublicationPlan` in `knowledge/temporal.py` containing exact closure operations and new-version IDs. It is prepared outside the write transaction and contains no callbacks.

Within `publish_staged_generation`, under the existing source lock, build fence, parent CAS, suppression check and seal validation:

- Validate every closure target exists, belongs to the same workspace/source lineage through complete support, is currently open, has `recorded_from < published_at`, and is not already closed differently.
- Require each appended replacement/corrected segment to be an exact member of the staged generation, to have `recorded_from == published_at`, and to preserve assertion identity/scope/evidence dependencies. Object-observation corrections obey the equivalent object/revision/span closure.
- Close old rows with `recorded_to=published_at`, append already-staged immutable corrected/new rows, publish/retire generations, advance graph/content state, and write the publication event in one transaction. A failpoint after any closure, pointer, event, or retirement rolls everything back.
- Exact publication retry returns the original receipt and observes already-applied closures. A different closure plan, stale parent/fence, later suppression epoch, or conflicting close fails without writes.

No model, filesystem, remote callback, or unguarded clock runs in this transaction. `update_knowledge` retains its only-once monotonic `recorded_to` rule; the publication primitive is the sole batch coordinator.

## 6. Required shared-file changes and ownership boundary

These changes require root release before modification:

- `knowledge/model.py`: canonical sorted/unique validation for `HistoryManifest` and `ConflictSet`; reject invalid conflict support/interval shapes while keeping unknown/open semantics. Do not add opaque provider ordering or authority fields to JSON.
- `knowledge/access.py`: expose a narrow history proof path that reuses existing source/policy/suppression and complete-support logic; never fork authorization policy. Preserve `query_mode` distinction exactly.
- `knowledge/snapshots.py` and `store/snapshots.py`: acquire/validate history manifests and references atomically; recheck current authorization and include history reachability in collection roots.
- `knowledge/lifecycle.py` and `store/generations.py`: validate and apply `TemporalPublicationPlan` inside strict fenced publication. Generic fixture publication must not become a production bypass.
- `store/knowledge.py`: add exact batch closure validation using the current source/authorization lock. Keep all other historical fields immutable.
- `store/ladybug.py`, `store/migrations.py`, and FakeStore only if the final storage contract adds physical fields or optimized parameterized predicates. Schema 5 already contains the documented temporal columns, so prefer mixin logic and parameterized existing columns over an unnecessary schema bump.
- Fixture loading gains chronological JSONL support only after its owner is free. It must use explicit parsed instants and adapter ordering metadata, never wall-clock defaults.

Dense graph, projection, query-dispatch, and prose coordinator files are outside Task 5A ownership. Temporal selection feeds their future provider inputs through held authorized snapshots; it does not patch those active files in this increment.

## 7. TDD sequence and acceptance evidence

1. RED/GREEN pure UTC, interval, selector, unknown/open and serialization behavior in `tests/unit/test_temporal_evidence.py` and `knowledge/temporal.py`.
2. RED/GREEN adapter ordering, same-source selection, scope isolation, cardinality, overlap and deterministic conflict identities in `tests/unit/test_temporal_conflicts.py` and `knowledge/conflicts.py`.
3. Add `tests/fixtures/rag_all/temporal_events.jsonl` with the May ownership correction, imported-old-last, equal timestamp/different bytes, unknown date, environment collision, independent source alternatives, ordinary tombstone, all-history purge, and explicit restoration barrier.
4. After shared-file release, RED/GREEN authorized history manifests, current/history suppression split, retained-generation reachability and evidence serialization.
5. RED/GREEN atomic correction publication and failpoint rollback on Fake, real Ladybug reopen, then root-reserved Neo4j parity.
6. Run G18 plus existing knowledge-contract, evidence-access, generation, snapshot, migration and projection regressions. Ruff/format and independent SPEC/QUALITY review must pass before the task is complete.

## 8. Completion boundary

Task 5A is complete only when G18 proves effective/recorded reconstruction, retained-only history, fixed knowledge cutoffs, no ingestion-order supersession, honest unknown time, cardinality/scope-aware conflicts, ordinary-delete history, and purge/access denial on Fake and Ladybug, with Neo4j transaction parity separately verified by root. Passing the pure increment alone does not complete Task 5A or activate temporal production routes.
