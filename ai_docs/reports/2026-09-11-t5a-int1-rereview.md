# Independent re-review — Task 5A integration part 1 fixes

Reviewer `architect-reviewer-7`, root tree, read-only except this file.
Under review: `043ca51..957fc35` restricted to the `wp/t5a1fix` commits (`babe0b7`, `5fc3b8c`,
`f077b9c`, `6a11ea3`, `f340a05`, `18cc610`, merged as `957fc35`).
Re-run at `ffd2265` (`da51784` + its incident note), which is `957fc35` plus the import-order fix
described in §1.1.
Against: `ai_docs/reports/2026-09-11-t5a-int1-review.md` (F1–F10) and the orchestrator's decisions
in `ai_docs/handoffs/briefs/fix-t5a-int1.md`. Fixer evidence:
`ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/evidence-int1.md` §"Fixes after review".

**RE-REVIEW: FAIL — F9 INCOMPLETE (N2, major, latent). F1–F8, F10 and the carve-out CORRECT.**

The verdict word is the brief's test, not a publication recommendation: the brief asks whether
every finding is resolved *exactly per the orchestrator's decisions*, and F9's decision —
"unauthorized callers get the same empty answer as a nonexistent manifest" — is not delivered. The
audience gate fails *fully open* when every revision a manifest names has been purged, and not
merely "vacuous for a caller who already holds the ID", which is what the fixer declared: an
anonymous principal with no workspace membership row at all receives the complete marker list
(**N2**, major, reproduced in §3f). Nothing reaches it from a request path today, so it is latent
in exactly the way F1 was. Whether that blocks publication is the orchestrator's call; my own
engineering recommendation is in §5.

The identity carve-out is CORRECT and its blast radius is exactly one record class.

The two blockers of the first review are genuinely closed. The engineering is careful and the
disclosure discipline is good: the fixer's own evidence file states the carve-out's four-mode side
effect precisely, and it is the *plan* amendment that overstates it (**N3**, minor).

New findings: **1 major, 1 minor, 1 informational.** One blocker (**N1**) was found at the
re-review HEAD, did not belong to this slice, and was fixed by the orchestrator mid-review.

---

## 1. Run results

### 1.1 N1 — blocker (not this slice; FIXED at `da51784` during this re-review)

At `957fc35` every gate command that touches the store failed. Cause: a circular import,

```
hippo.knowledge.generation_profiles:14
  -> hippo.ingest/__init__:15
  -> hippo/ingest/pipeline.py:47  "from . import managed_activation"
  -> hippo/ingest/managed_activation.py:35
  -> hippo/ingest/prose_generation.py:25
  -> hippo.knowledge.generation_profiles   (partially initialised)
=> ImportError: cannot import name 'MANIFEST_EXTERNAL_ID'
```

Introduced by `efc1075` (merge `c668688`, `wp/pa3a`), which added `managed_activation` to
`pipeline.py`'s module-level imports; `043ca51` is clean. Any process that touched
`hippo.knowledge.*` before `hippo.ingest` died — including `from hippo import ask` and
`import hippo.mcp_server`. Numbers at `957fc35`: T5A1 23F/23P, T5A3 23F, T5A4 23F, T5A5 47F/164P,
and the extra command could not collect `test_query_session.py` or
`test_managed_route_activation.py` (exit 2). T5A2 and T5A6 were unaffected.

Reported to the orchestrator, who fixed it at `da51784` (lazy accessor in `pipeline.py`). All
numbers below are from `ffd2265`, post-fix, with the gate commands **verbatim** and no workaround.
`.venv/bin/python -c "from hippo import ask, mcp_server; import hippo.knowledge.generation_profiles"`
now succeeds.

### 1.2 Verbatim runs at `ffd2265`

All seven exit 0. `HIPPO_TEST_STORE` explicit on every one. No Neo4j.

| # | Command | Log | Result |
|---|---|---|---|
| T5A1 | ledger CHECK, Fake | `/tmp/hippo-t5a1-rereview-T5A1.log` | exit 0, **46 passed** |
| T5A2 | ledger CHECK, Fake | `/tmp/hippo-t5a1-rereview-T5A2.log` | exit 0, **30 passed** |
| T5A3 | ledger CHECK, Fake | `/tmp/hippo-t5a1-rereview-T5A3.log` | exit 0, **23 passed, 53 deselected** |
| T5A4 | ledger CHECK, **Ladybug** | `/tmp/hippo-t5a1-rereview-T5A4.log` | exit 0, **23 passed, 53 deselected** in 30.59s |
| T5A5 | ledger CHECK, Fake | `/tmp/hippo-t5a1-rereview-T5A5.log` | exit 0, **211 passed, 1 skipped** |
| T5A6 | ledger CHECK, Ruff | `/tmp/hippo-t5a1-rereview-T5A6.log` | exit 0, `All checks passed!`, **11 files already formatted** |
| (extra) | brief step 1's six-module Fake command with the sanctioned `BlockingPortal` filter | `/tmp/hippo-t5a1-rereview-extra.log` | exit 0, **113 passed, 1 skipped** |

Notes:

- **Warning handling.** The six ledger commands ran under bare `-W error`, exactly as their CHECK
  lines are written. The extra command carries form (b), the sanctioned command-line
  `-W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`, because
  `test_query_session.py` and `test_managed_route_activation.py` import `fastapi.testclient` at
  module level. No `filterwarnings` was added anywhere.
- **Count deltas versus the first review.** T5A1 35 → 46 (+11 post-review cases). T5A3/T5A4 12 →
  23 (the same +11). T5A5 209 → 211 (+2 carve-out cases in `test_knowledge_contracts.py`). T5A6 10
  → 11 files (the CHECK line gained `store/authorization.py` at `e8ca7cc`). `recorded_correction`
  still matches no test; the T5A3/T5A4 "partial" annotation remains accurate and neither gate can
  be closed on it.
- **Ledger EVIDENCE drift (N4, informational, orchestrator's lines).** T5A1 records `22 passed`
  (now 46); T5A5 records `206 passed, 1 skipped` (now 211, 1); T5A6 records `4 files already
  formatted` (now 11). T5A3/T5A4 were refreshed by the fixer and match.
- **Footnote on the workaround.** Before `da51784` I re-ran the same seven commands with
  `PYTHONPATH=/tmp/t5a1rr` and `-p ingest_first`, a two-line pytest plugin in `/tmp` whose only
  body is `import hippo.ingest`, to get signal past N1 without touching a repository file. Those
  runs produced the identical counts (T5A1 46, T5A2 30, T5A3 23/53, T5A5 211/1, extra 113/1). They
  are **not gate-valid evidence** and no EVIDENCE line should be recorded from them; the verbatim
  numbers in the table above supersede them entirely.

## 2. Finding-by-finding verdict

| # | Decision | Verdict | Where, and what proves it |
|---|---|---|---|
| F1 | `acquire_history_snapshot` rebuilds the proof for the caller; keeps the epoch check; requires every manifest ID inside that proof; bundle proof, fingerprint, validation and expiry clock all belong to the caller | **CORRECT** | `knowledge/snapshots.py:236-241` rebuilds via `history_access(store, manifest.workspace_id, access, clock=clock)`; `:238` epoch check; `:240` `proof_covers_manifest`; `:252` `policy_fingerprint=proof.policy_fingerprint`; `:264` stores `((resolver, proof),)` and the caller's `clock` in the bundle, so `_validate_authorization` (`:75-76`) and `_check_current_boundary`'s `_now()` are the caller's. `test_history_manifest_pin_proves_the_calling_audience_not_the_selecting_one` (`test_temporal_evidence.py:955`) asserts `resolver.access == caller`, `secret_span ∈ internal.proof.span_ids` but `∉ proof.span_ids`, and both fingerprints equal the caller's own. See §3(a). |
| F2 | one `store.transaction()`, no callbacks/model/uncontrolled clock inside; containment becomes manifest ⊆ proof and runs before the put; broad/proof epoch cross-check | **CORRECT** | `temporal.py:556-625`: `with store.transaction():` opens at `:556`, `epoch` captured at `:557`, `put_knowledge` at `:615`, return inside. Epoch cross-check `:604-605`, `proof_covers_manifest` `:608-609`, the old `proof ⊆ broad` kept at `:610-614`, all three before the write. Proven by `test_history_manifest_is_written_inside_the_transaction_that_read_it` (`:899`), `..._is_never_persisted_outside_its_final_proof` (`:917`) and `..._refuses_an_authorization_epoch_that_moved_mid_read` (`:936`); the last two assert `store._knowledge_rows("HistoryManifest") == []`. See §3(b). |
| F3 | `known_at` on `CurrentSelector`/`AtemporalSelector`; `pinned_selector` binds for every mode; `validate_knowledge_cutoff` covers them; a pinned selector re-resolves to the pinned instant | **CORRECT** | `model.py:1226,1258` add the field; `temporal.py:409-421` drops the conditional and always `replace(known_at=...)`; `model.py:1291-1304` unchanged in logic but now non-vacuous. `test_history_manifest_pins_an_implicit_cutoff_for_current_and_atemporal_modes` (`:989`) and `test_every_pinned_selector_mode_carries_the_knowledge_cutoff_it_was_resolved_at` (`test_knowledge_contracts.py:925`). Independently re-derived for all six modes: §3(c). |
| F4 | `HistoryManifest` and `ConflictSet` become `bookkeeping`; no build-lease fence, no `content_epoch` bump; confirm no other read-path record shares it | **CORRECT** | `store/authorization.py:150-161`. `test_history_manifest_reads_through_a_running_rebuild_of_its_source` (`:1013`), `test_history_manifest_conflict_set_persists_through_a_running_rebuild` (`:1045`), `test_history_manifest_read_leaves_the_content_epoch_where_it_found_it` (`:1025`). Independent re-walk of `REFERENCES`/`LIST_REFERENCES` over all 38 record classes reproduces the audit exactly: §3(e). |
| F5 | compare stays unimplemented; test name and docstring say "rejected in part 1" | **CORRECT** | `test_temporal_evidence.py:676-690`: renamed `..._rejects_a_compare_selector_and_asks_for_one_manifest_per_side`, docstring "Compare is rejected in part 1, even with two independently pinned sides", and the assertion now matches the remedy text `"one independently pinned manifest per side"` (`temporal.py:555`). No behavior change. |
| F6 | purged set resolved once per collection pass | **CORRECT** | `store/snapshots.py:230` memoises `members` (the `GenerationMember` scan) once and `purged` per workspace, both lazily and only when a durable history pin asks; `_snapshot_reaches` became `_history_reaches(snapshot, *, revision_ids, purged)` (`:207`). The `sources` fast path moved into the loop (`:239-240`), so a pass with no history pin now does *fewer* scans than before. No stale caller of `_snapshot_reaches` anywhere in `src/` or `tests/`; `SnapshotQueries` is a shared mixin (`FakeStore`, `LadybugStore`, `Store` all inherit it), so no Fake mirror was needed. |
| F7 | `history_access` reuses `_reader_proof`'s helper instead of duplicating it | **CORRECT (declared deviation, accepted)** | `temporal.py:424-436` now calls `store._reviewed_mapping_authorities()` (`store/knowledge.py:325-331`), which raises the identical `RuntimeError("Invalid reviewed membership authority configuration")`. The decision said "factor a private function"; the fixer used the accessor that already existed because `store/knowledge.py` is on the brief's do-NOT-touch list, and says so in the evidence. Copies went 3 → 2; the survivor is `_reader_proof`'s own inline block (`store/knowledge.py:687-692`). Correct within ownership; the residual should be closed when `store/knowledge.py` is next owned. |
| F8 | empty authorized set gets an empty manifest with no code; `history_unavailable` reserved for a cutoff before the earliest retained interval | **CORRECT** | `temporal.py:566`, `unavailable = earliest is not None and resolved.known_at < earliest`. `test_history_manifest_is_empty_rather_than_unavailable_without_authorized_rows` (`:1063`) asserts `codes == ()` and proven/contextual all zero; the pre-existing `..._reports_history_unavailable_before_the_earliest_interval` still guards the positive case. |
| F9 | `purged_history_evidence(manifest_id, *, workspace_id, access)` scoped to workspace and audience; unauthorized callers get the same answer as a nonexistent manifest | **INCOMPLETE** | The signature, the workspace check and the partial-purge gate are right (`store/snapshots.py:174-205`) and `test_purge_history_evidence_answers_only_an_audience_that_proves_the_manifest` (`:1077`) proves foreign-workspace, revoked-member and unknown-manifest all raise `SnapshotUnavailable`. But the gate is `retained <= proof.revision_ids` where `retained = manifest.revision_ids - purged`; when every named revision is purged, `retained` is empty, the subset holds for *anyone*, and `validate_current` proves stability rather than entitlement. See **N2**. |
| F10 | fix the doc drift the report lists | **CORRECT** | Plan §4 gained an "Amended 2026-09-11 after the independent SPEC/QUALITY review" block (nine bullets, one per decision); `evidence-int1.md` Decision 1 is corrected in place and the open-findings count reconciled to three. One overstated sentence in the plan block: **N3**. The three stale ledger EVIDENCE lines are correctly left to the orchestrator: **N4**. |
| carve-out | `Record.identity_parts` omits a null `known_at` at any depth so pre-change identities survive | **CORRECT** | `model.py:115-143`. Scope verified independently across all 38 record classes: §3(d). The fixer's own scope paragraph in `evidence-int1.md` is accurate, including the four-mode side effect. |

## 3. The specific verifications the brief asked for

### (a) The bystander scenario, and whose proof governs expiry and fingerprint

The first review's repro handed `acquire_history_snapshot` a `HistorySelection` selected by the
internal (3-span) audience together with `Access(user_id=<bystander>)`, and got a bundle whose
pinned proof, `policy_fingerprint` and every later revalidation belonged to the internal audience.
That is now structurally impossible: `history.resolver` is no longer read at all
(`knowledge/snapshots.py:236`), and the proof is built from the caller's `access` and the caller's
`clock`.

The shipped test is `test_history_manifest_pin_proves_the_calling_audience_not_the_selecting_one`
(`test_temporal_evidence.py:955`). It is genuinely RED at `043ca51`: with `resolver =
history.resolver` both `assert resolver.access == caller` and `assert world.secret_span.id not in
proof.span_ids` fail, because the selecting resolver is `EVERYTHING`'s.

Two consequences worth stating precisely, because the test's shape differs from the report's:

- The bystander is **not denied**; they receive a bundle built on their own narrower proof. That is
  the correct outcome, because `proof_covers_manifest` only requires the manifest's `revision_ids`
  and `assertion_version_ids`, and this bystander can prove both. A caller who *cannot* re-prove
  the manifest is denied at acquisition, not at first use —
  `test_history_manifest_pin_denies_a_caller_who_cannot_reprove_it` (`:977`).
- Expiry and fingerprint: `policy_fingerprint` on both the proof pair and the persisted
  `QuerySnapshot` come from the rebuilt proof (`snapshots.py:252`), the bundle carries the caller's
  `clock` (`:264`), and `proof.valid_until` is the caller's, so `_check_current_boundary` now
  genuinely honours the `clock=` a caller passes. The first review's "the uncontrollable one" is
  closed.

`proof_covers_manifest` does not check `link_generation_ids` or `retention_gaps`. That is not a
gap: `AuthorizedEvidence` has no `link_generation_ids` field to check against (its fields are
`artifact_ids, assertion_ids, assertion_version_ids, authorization_epoch, derived_dependency_ids,
derived_record_ids, native_binding_ids, object_ids, observation_ids, policy_fingerprint,
prose_extraction_ids, retrieval_view_ids, revision_ids, selection, span_ids, support_groups,
support_ids, valid_until, workspace_id`), and the decision named exactly the two tuples that are
checked.

### (b) Inside `select_history`: no callback, no model call, no uncontrolled clock; a narrowed proof raises without a row

Source inspection of `temporal.py:556-625`. The block contains: `store.authorization_epoch()`,
`history_access(...)`, `EvidenceAccess.build_history()`, `_authorized_temporal_rows`, `_decide`
(pure; wraps an unchanged `match_temporal`), `min(...)`, `_revision_closure`, `_link_generations`,
`_retention_gaps`, `_counts`, `pinned_selector`, two record constructions, `EvidenceAccess.build`,
three guard clauses and one `put_knowledge`. No helper takes a callable; none opens a file, calls a
model or reaches a network. `grep -n "utc_now|datetime.now|_now|time()" src/hippo/knowledge/temporal.py`
returns only the import (`:20`), `history_access`'s keyword default (`:424`) and `select_history`'s
keyword default (`:537`) — no clock is *read* in the module. The only clock read inside the
transaction is `EvidenceAccess._now()` (`knowledge/access.py:244-247`, used at `:312` and `:559`),
which calls `self.clock`, i.e. the clock the caller injected via `history_access(..., clock=clock)`.
`resolve_selector` runs *before* the transaction and touches no store.

A proof narrowed between the two builds: `test_history_manifest_is_never_persisted_outside_its_final_proof`
(`:917`) monkeypatches `EvidenceAccess.build` to return `revision_ids=frozenset()` for the
selection build only, asserts `AuthorizationChanged`, **and** asserts
`store._knowledge_rows("HistoryManifest") == []`. Both halves of the old defect — the inverted
direction and the position after the write — are covered. The epoch variant is the sibling test at
`:936`. The concurrency claim itself remains structural, as the fixer declared: Fake and Ladybug
are single-threaded, so no test observes a real interleaving.

### (c) All six selector modes pin and replay to the same instant

Re-derived independently (`/tmp/t5a1rr/probe_f3.py`, Fake):

```
mode       select_history   pinned known_at              replay@2026-06-01            origin
current    ok               2026-05-12 00:00:00+00:00    2026-05-12 00:00:00+00:00    explicit
atemporal  ok               2026-05-12 00:00:00+00:00    2026-05-12 00:00:00+00:00    explicit
as_of      ok               2026-05-12 00:00:00+00:00    2026-05-12 00:00:00+00:00    explicit
during     ok               2026-05-12 00:00:00+00:00    2026-05-12 00:00:00+00:00    explicit
changes    ok               2026-05-12 00:00:00+00:00    2026-05-12 00:00:00+00:00    explicit
compare    REJECTED by select_history; pinned_selector binds each side to its own
           cutoff (2026-05-05T12:00Z / 2026-05-12T00:00Z), each replaying "explicit"
```

`manifest.knowledge_cutoff == pinned.known_at == re-resolved known_at` for all five reachable
modes. Compare reaches `pinned_selector` only through a caller that loops the sides itself, which
is the F5 decision; `validate_knowledge_cutoff` recurses into both sides (`model.py:1302-1304`), so
a `CompareSelector` that *is* persisted is still proved.

### (d) The carve-out's blast radius

**Which record classes it can reach.** Walking `identity_fields` for all 38 registered record
classes and asking, per field, whether a `known_at` key can appear anywhere in its JSON dump:
exactly one hit — `QuerySnapshot.temporal`. Every other identity field is a scalar, a tuple of
strings, a `Json` *text* column, or a nested model with no `known_at` (`SnapshotSource`,
`RepresentationChecksum`, `TimeInterval`). `HistoryManifest.temporal_selector_json` is text, so the
carve-out never touches it. No model class outside the six selectors declares `known_at`.

**Does a set `known_at` still change the identity?** Yes, for every mode, including a nested
comparison side:

```
current/atemporal/as_of/compare: pinned id != unset id, '"known_at"' present in identity_key
CompareSelector(left pinned, right unset): id differs; only the right side's null is stripped
```

**Does it preserve pre-change identities?** I loaded the real `model.py` from `043ca51` alongside
the current one and compared `QuerySnapshot.id` mode by mode with `known_at` unset:

| mode | `known_at` existed at 043ca51 | identity preserved at HEAD |
|---|---|---|
| current | no | **yes** |
| atemporal | no | **yes** |
| as_of | yes | **no** |
| during | yes | **no** |
| changes | yes | **no** |
| compare | yes | **no** |

So the carve-out preserves identity for precisely the two modes that gained the field, and changes
it for the four that already carried an explicit null. **This is harmless and the fixer knew it**:
`evidence-int1.md` §"Scope of the carve-out" states the four-mode effect verbatim and gives the
right reason — the only two `src/` writers of `QuerySnapshot.temporal` are
`acquire_query_snapshots` (bare `CurrentSelector()`, `snapshots.py:173`) and
`acquire_history_snapshot` (a pinned selector, `:247`), confirmed by grep; no production path can
have persisted an unpinned `as_of`/`during`/`changes`/`compare` snapshot. No collision is
introduced either, because `known_at` is now a declared field on all six modes, so "absent" never
occurs in a fresh dump and `mode` discriminates regardless. The claim that is wrong is the *plan
amendment's* — see **N3**.

### (e) The F4 audit, re-walked independently

I re-implemented the `_record_revisions` walk from `REFERENCES` + `LIST_REFERENCES`
(`store/knowledge.py:44-97`) and ran it over every registered record class. The 13 `content`
records whose write is fenced by a running rebuild are exactly the fixer's list: `Alias`,
`AssertionSupport`, `DerivedDependency`, `DerivedRecord`, `EvidenceSpan`, `GenerationMember`,
`NativeBinding`, `ObjectObservation`, `ProseExtraction`, `RetrievalView`, `Section`,
`SectionMember` — plus `Artifact`, which reaches the fence not through a reference but through
`_check_knowledge_write`'s explicit `source_ids = {record.source_id}` seed
(`store/generations.py:412`); the fixer's "does not reach one" is right about the walk and the
difference does not change the conclusion. Their correction of the first review's `LinkGeneration`
claim is right: it reaches `AssertionVersion` only, never a revision.

The four records that *name* evidence without being it — `HistoryManifest`, `ConflictSet`,
`QuerySnapshot`, `SnapshotReference` — are now exactly the `bookkeeping` members that reach a
revision. Two of the four were already bookkeeping; the other two moved. No other record shares the
pattern, and none of the 13 is written from a read path: the only `put_knowledge` on a read path
anywhere in `src/` is `temporal.py:615` (a `HistoryManifest`), and `conflicts.py:206` *builds* a
`ConflictSet` that nothing persists yet.

`RECORD_EPOCHS` has exactly two consumers — the build-lease fence (`store/generations.py:410`) and
`record_mutation`'s epoch bumps (`store/authorization.py:185-197`) — so the reclassification can
change nothing else. `content_epoch` is unchanged by a history read *and* by a `ConflictSet` write:
`test_history_manifest_read_leaves_the_content_epoch_where_it_found_it` (`:1025`) asserts
`store.content_epoch() == before` across both.

### (f) F9's residual: what the all-purged case actually leaks

The fixer declared: "when every manifest revision is purged the F9 audience gate is vacuous (a
caller holding the manifest ID learns which revisions it named)". That understates it in two ways.

*It is not limited to a caller who holds a legitimate selection.* Reproduced on Fake
(`/tmp/t5a1rr/probe_f9.py`): with a 2-revision manifest and both revisions purged,

```
plain bystander (workspace member)  -> both markers
DISABLED workspace member (revoked) -> both markers   <- denied in the partial-purge case
stranger, no membership row at all  -> both markers
Access(audience_kind="open")        -> both markers
Access(audience_kind="preview")     -> both markers
```

while the *same* bystander gets `None` from `get_knowledge("HistoryManifest", …)` and `[]` from
`list_knowledge`, because `_record_visible` (`store/knowledge.py:699-716`) deliberately refuses to
render control records to a non-internal audience.

*It does leak beyond what the ID's holder already knew.* The manifest is not readable through the
public store API by any non-internal audience, so the markers are the only way to learn the
manifest's cardinality and its revision IDs. The IDs are hash-derived and carry no text, locator or
`content_hash` — the first review established that and it still holds — but they are correlatable
against any revision the caller can see elsewhere.

Mechanism, for the fix: `validate_current` (`knowledge/access.py:562-573`) proves *stability* (the
rebuilt proof equals the given one), not *entitlement*; for a principal with no grants both builds
are empty and equal, so it passes. The entire entitlement check is therefore the subset test, and
an empty `retained` makes it vacuous. Recorded as **N2**.

## 4. New findings

### N1 — blocker — circular import broke `hippo.ask` / `hippo.mcp_server` at `957fc35` (not this slice; FIXED)

See §1.1. Owner was the `wp/pa3a` slice (`efc1075`). Fixed by the orchestrator at `da51784`;
verified here. Recorded so the incident is traceable from this slice's re-review, not because this
slice caused it.

### N2 — major — `purged_history_evidence`'s audience gate fails open when every named revision is purged

`src/hippo/store/snapshots.py:192-201`

**Why.** `retained = frozenset(history.revision_ids) - purged` (`:192`). When a purge covers every
revision the manifest names, `retained` is empty, `engine.validate_current(proof)` passes for any
principal (it proves stability, not entitlement), and `retained <= proof.revision_ids` is
`∅ ⊆ anything` — true for a disabled member, for a principal with no membership row, and for
`open`/`preview` audiences alike. The decision in `fix-t5a-int1.md` F9 was "unauthorized callers get
the same empty answer as a nonexistent manifest"; in this case they get the *complete* answer.

**Reproduction.** `/tmp/t5a1rr/probe_f9.py`, `HIPPO_TEST_STORE=fake`, output quoted in §3(f). The
adjacent partial-purge case is correctly denied — `test_purge_history_evidence_answers_only_an_audience_that_proves_the_manifest`
(`:1077`) proves it — which is what makes this a fail-open rather than a design choice.

**Impact.** Latent, exactly as F1 was: nothing in `src/` calls `purged_history_evidence` from a
request path, and Task 5 is not activated. It becomes live the moment part 2 wires markers to a
dispatcher, which is precisely what the first review's F9 warned about.

**Proposed fix.** Make the empty case deny rather than allow. In the non-internal branch, after
computing `retained`, add: if `retained` is empty and `history.revision_ids` is not, raise the same
`SnapshotUnavailable("Unknown history manifest")`. That collapses the all-purged case into the
indistinguishable answer the decision asked for, and it is consistent with the rest of the slice —
a bundle pinning a fully purged manifest already raises on `validate()`
(`test_purge_history_overrides_retained_snapshot_roots`, `:846`), so no legitimate caller loses a
working path. If the orchestrator wants the all-purged answer to remain *available* to an entitled
caller, the gate has to prove entitlement some other way than through a proof the purge has already
emptied — e.g. an explicit workspace-membership check — and that is a larger change than this slice
should carry.

**Note on the same shape elsewhere.** `proof_covers_manifest` is also vacuous for an empty
manifest, so any audience can pin one. That one is harmless — the manifest names nothing, so the
pin reaches nothing — but it is the same "empty set makes the gate true" pattern and worth a
comment if part 2 adds a third use.

### N3 — minor — the plan's carve-out bullet overstates what stays byte-identical

`ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md`, the carve-out bullet in the new
"Amended 2026-09-11 after the independent SPEC/QUALITY review" block, says "... so **every**
pre-change identity stays byte-identical ... Verified against a `QuerySnapshot` JSON captured at
`043ca51`."

Per §3(d) that is true for `current` and `atemporal` and false for `as_of`, `during`, `changes` and
`compare`, whose dumps already carried `"known_at": null`. The captured JSON pins the `current`
case only, so the cited verification does not reach the claim. `evidence-int1.md` states the same
fact correctly two paragraphs later, so this is drift between two documents rather than a
misunderstanding. The re-review brief's own CONTEXT line ("`Record.identity_parts` omits a null
`known_at` at any depth ... so pre-change `QuerySnapshot` identities stay byte-identical") inherited
the same overstatement and is worth correcting alongside it.

**Fix.** Scope the sentence: "... so every identity a pre-change store could actually have written
stays byte-identical — the only two writers of `QuerySnapshot.temporal` are a bare `CurrentSelector()`
and a pinned selector — while the canonical form of an unset `as_of`/`during`/`changes`/`compare`
cutoff also changes, affecting no persisted row." No code change.

### N4 — informational — three stale EVIDENCE lines in the T5A ledger

`ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/GATES.md`. T5A1 records `22 passed`, now 46.
T5A5 records `206 passed, 1 skipped`, now `211 passed, 1 skipped`. T5A6 records `4 files already
formatted`, now `11 files already formatted` (its CHECK line gained `store/authorization.py` at
`e8ca7cc`). T5A3 and T5A4 were refreshed by the fixer and match my runs. These are the
orchestrator's lines to maintain; the fixer correctly left them alone and said so.

## 5. Recommendation

Publish the slice. F1 and F2 — the two named T5A6 disqualifiers, "authorization fork" and
"non-atomic closure" — are closed by contained, well-tested changes in the two files the slice
already owned, and the F4 reclassification is justified by an audit that reproduces independently.
F3's carve-out is the right call and is documented honestly where it matters most (the evidence
file).

Before part 2 wires anything to a dispatcher, close **N2**; it is a four-line change in the file
this slice already owns. **N3** and **N4** are text. T5A3 and T5A4 still cannot be checked off:
`recorded_correction` matches no test, which is part 2's work and is correctly annotated as partial
in the ledger.

The declared residuals stand as declared: F2's concurrency argument is structural and cannot be
behaviourally proven on a single-threaded backend; `QuerySnapshotBundle.close()` still releases
without rechecking authorization, which this slice inherited and did not change; and `_reader_proof`
keeps its own copy of the authority validation until someone owns `store/knowledge.py`.

## Appendix — re-review scripts

All in `/tmp/t5a1rr/`, run as `HIPPO_TEST_STORE=fake PYTHONPATH=/Users/mascott/projects/hippo
.venv/bin/python <script>`. They build their own `FakeStore`, touch no repository file and write
nothing outside `/tmp`.

- `probe_f3.py` — all six selector modes through `select_history` and `resolve_selector` (§3c).
- `probe_f9.py` — the all-purged marker gate across five audiences (§3f, N2).
- `identity_scan.py` — `known_at` reachability across all 38 record classes' `identity_fields` (§3d).
- `legacy_probe.py` + `oldpkg/__init__.py` — the real `043ca51` `model.py` loaded beside the current
  one for the mode-by-mode identity comparison (§3d).
- `f4_walk.py` — independent `REFERENCES`/`LIST_REFERENCES` walk (§3e).
- `ingest_first.py` — the two-line pytest plugin used only before `da51784`; superseded (§1.2).
