# Independent design review: managed code capture (Task 5)

**Reviewer:** architect-reviewer-17 (herdr fleet, root tree, read-only).
**Subject:** `ai_docs/plans/rag-it-all-task-5-managed-code-capture.md` at HEAD `e456e05`, with its
"Orchestrator rulings (2026-09-12)" section and the proposed ledger
`ai_docs/gates/rag-it-all/task-5-code-capture/GATES.md`.
**Method:** contract read against the cited seams; no code, no tests, no Neo4j. Every claim below
carries `file:line` evidence read at `e456e05`.

## DESIGN: APPROVED WITH CHANGES

The architecture is right. A separate `build_code_source` coordinator (§3), native code relations
rather than typed assertions (§4), reuse of the existing `CODE_MAX_*` rails as managed ceilings
(§8.3), the store's own rows as the resume checkpoint (§8.2) and the commit-derived temporal fields
(§9) all hold up against the code. The three prerequisites the plan names — legacy serving, scoped
reads, resumable reclaim — are real and correctly identified.

What it gets wrong is the blast radius of two of them. §7 changes what the `managed` flag means, and
the flag is load-bearing in five places the plan does not name; and §8.2's resume is defeated by an
identity field the plan does not account for. Both are correctable inside the existing split.

**Counts:** 6 blockers, 11 majors, 7 minors — 24 findings. Tasks needing an amendment before
spawn: CC1, CC2, CC3, CC4, CC5, CC8, CC9, CC10, CC11 (CC6 and CC7 unchanged).

**One decision is handed back.** B2 has two shapes, and the choice changes CC1's file list and
whether B3's second half and B6 exist at all. I recommend shape (b), which reverses ruling 6 and
therefore needs a fresh ruling. The orchestrator should settle it before CC1 goes further.

---

## Blockers

### B1 — A converting source's staged rows are served by the legacy graph loader

**Binds:** §7 (plan lines 212-227), CC1. **Severity: blocker.**

`_graph_for` (`src/hippo/context.py:171-178`) computes `managed_sources`, and then:
`if managed_sources:` routes to `_build_managed_graph`; otherwise it falls through to
`full = self.graph()`. `self.graph()` is `GraphIndex.load` (`src/hippo/hipporag/graph_index.py:411-432`),
which loads **every** Passage, Symbol, DataObject and Commit in the database with no
`generation_id` filter at all.

Today that is safe only because `record_mutation` (`src/hippo/store/authorization.py:186-187`) flips
`managed=True` on the first Artifact or Generation write, so the source is always in
`managed_sources` and the generation-aware loader runs. Ruling 6 removes that automatic flip and §7
deliberately keeps the converting source out of `managed_sources`. On the ordinary first conversion
— one repository, no other managed source on the instance — `managed_sources` becomes **empty**,
`_graph_for` takes the `self.graph()` branch, and every staged Symbol, Commit, DataObject and
Passage of the in-flight generation is loaded into the live graph beside that source's legacy rows.
Unpublished, duplicated content is served to every query for the whole bootstrap: precisely what §7
exists to prevent.

The managed and structural branches are fine: `load_generation_graph.selected`
(`src/hippo/knowledge/graph_loader.py:46-51`) requires `generation_id is None` for a source in
`legacy_source_ids`, so a converting source placed there serves exactly its legacy rows. The defect
is only the fall-through.

**Amendment.** Split the two decisions §7 conflates. Keep `managed_sources` at
`context.py:171-173` as the *loader-selection* set (unchanged: any source with an Artifact or
Generation row, or the `managed` flag) so the generation-aware loader always runs once managed rows
exist; add the serving-lane decision one level down, so a source for which
`source_serves_legacy` is true is added to `legacy_ids` at `context.py:214` and at
`context.py:339` and excluded from `selected` at `context.py:215-219` and `context.py:346-347`.
§7's sentence "Use it in `context._build_managed_graph` and `status.system_status` in place of the
current Artifact/Generation presence test" must be rewritten to say this; as written it names the
wrong function (`_graph_for` owns the presence test, and it feeds `_build_structural_graph` too)
and prescribes the replacement that causes the defect.

**CD2 criteria amendment.** Add: "with the converting source as the *only* managed source on the
instance, no staged passage, symbol, data object or commit appears in any query result." A CD2 test
that only asserts the legacy rows are present will pass while this defect is live.

### B2 — Deferring the `managed` flag disarms every legacy-cleanup guard

**Binds:** §7 (plan lines 228-232), ruling 6, CC1/CC9/CC10. **Severity: blocker.**

`source_is_managed` (`src/hippo/store/generations.py:58-60`) is the sole gate on five destructive
or dispatch paths:

- `legacy_source_cleanup` (`generations.py:1450-1459`) is the only thing stopping `delete_source`
  (`store/memory.py:130`, `store/ladybug.py:677`), `delete_passages_for_source`
  (`memory.py:148`, `ladybug.py:684`) and `delete_code_nodes_for_source` (`store/code.py:686`)
  from running on the source. With `managed` false during a multi-commit bootstrap, an
  actorless `delete_source` physically destroys the converting source's legacy evidence
  *and* orphans its staged generation, and `shutil.rmtree` runs at `ingest/pipeline.py:573`.
- `managed_eligibility` (`ingest/managed_activation.py:117`) dispatches on the same flag, so
  `plan_dispatch` (`managed_activation.py:168-180`) returns `legacy` and
  `pipeline.delete_source` (`pipeline.py:557-561`) never reaches `_tombstone`.
- `tombstone_managed_source` raises `UnmanagedSource` (`knowledge/source_lifecycle.py:77-78`,
  `:86-87`) and `apply_source_tombstone` raises `ValueError("Managed source required for
  suppression")` (`generations.py:126`). There is therefore **no way to withdraw a converting
  source** while it converts.
- `_prepare_reindex` on the legacy lane (`pipeline.py:620-622`) clears the source's passages
  mid-build for the same reason.
- `native_write`'s untagged-row barrier (`generations.py:1290-1293`) only refuses an untagged
  managed write when `source_is_managed`, so a concurrently dispatched legacy indexer can write
  untagged native rows into the source while the managed build stages.

§10's promise — "Never any collection, `_clear_passages`, `delete_code_nodes_for_source`, `rmtree`
or raw deletion" — is unenforceable for the code lane as §7 is written.

**Amendment.** The plan must state that the `managed` flag carries two meanings today — "the
managed lane owns cleanup and dispatch" (safety) and "serve managed evidence" (selection) — and
that only the second is being deferred. Two shapes:

- **(a) Consistent with ruling 6.** Keep the deferred flip, and re-point each of the five guards
  above at a new store predicate `source_has_managed_rows(source_id)` (true when any Artifact or
  Generation row names the source). This is CC1's work for `generations.py`, but
  `managed_activation.py`, `pipeline.py`, `source_lifecycle.py` and `store/code.py` are **not** in
  CC1's exclusive list (M10), and it breaks `managed_eligibility`'s reviewed contract — "Closed,
  and decided on the row alone" (`managed_activation.py:111-112`) — because the predicate needs a
  store handle that function does not take.
- **(b) Recommended.** Flip `managed=True` at staging start as today and make
  `source_serves_legacy` drop the `managed` term entirely: true iff the source has no
  `active_generation_id` and no published `IndexEvent`. Every existing guard then fires unchanged,
  `managed_eligibility` stays row-only, **B6 disappears** (publication no longer bumps the
  authorization epoch, because the flip already happened), and **B3's second half becomes
  redundant** (`_source_control.managed` is simply true). Only the two selection sites move. The
  cost: the code coordinator must decide `bootstrap` from `active_generation_id is None` rather
  than from `source_control.managed` as `prose_generation.py:655` does.

**Shape (b) collapses three blockers into one predicate change and is my recommendation.** It
reverses ruling 6, so it needs a fresh ruling rather than a silent amendment.

Either way, §7's claim that this is "one narrow, testable predicate" is false as stated, and CD2
must gain: "an actorless delete, reindex or bulk reindex of a converting source refuses rather than
clearing it; `delete_source`, `delete_passages_for_source`, `delete_code_nodes_for_source`,
`_prepare_reindex` and `shutil.rmtree` are never reached; the source can still be tombstoned."

### B3 — `build_authority._source_control` refuses every repository source outright

**Binds:** §3, §6, §12 (CC8/CC9/CC10). **Severity: blocker.**

`_source_control` (`src/hippo/knowledge/build_authority.py:61-67`) raises
`AuthorizationChanged("Build actor cannot manage source")` when
`source.get("kind") not in {"text", "file"}`. `capture_build_authority`
(`build_authority.py:340-345`) calls it first. So `BuildActor`-based authority cannot be captured
for a `repo` or `archive` source at all, and `build_code_source` cannot take its first step. The
plan never mentions this seam.

Worse, the same function computes `managed` at `build_authority.py:68-77` from *exactly the
Artifact/Generation presence test §7 is removing* — a **third** copy, alongside `context.py:171-173`
and `status.py:58-65`, which §7 does not name. Two consequences: `build_plain_source`'s
`bootstrap = not run.guard.source_control.managed` (`ingest/prose_generation.py:655`) would compute
`bootstrap=False` for a *resumed* code bootstrap whose staged rows already exist, and the next line
(`prose_generation.py:656-657`) then raises `ValueError("Managed source needs explicit recovery
before initial publication")`. A resumed bootstrap is rejected by construction if CC9 copies the
prose shape.

**Amendment.** Add `build_authority._source_control` to §2's seam table and to §12. It must
(i) accept `repo` and `archive` in the kind allow-list, keeping the identical denial text so the
refusal stays a non-oracle, and (ii) drop the Artifact/Generation presence term from its `managed`
computation in favour of the same predicate B2 settles on. Assign both to **CC1** (it is the
blocker-A slice and nothing else in CC1 conflicts), not to CC8, and add
`src/hippo/knowledge/build_authority.py` + `tests/unit/test_build_authority.py` to CC1's exclusive
list with a handoff to CC8 — see M9.

### B4 — The one capture instant is in `ObjectObservation` identity, so resume cannot reproduce it

**Binds:** §8.2 (plan lines 283-315), §9 (plan lines 339-340), CC7/CC8/CC9. **Severity: blocker.**

`ObjectObservation.identity_fields` (`src/hippo/knowledge/model.py:496-508`) includes
`recorded_from`, and record IDs are derived from `identity_fields` and validated against the row
(`model.py:143-153`, `knowledge/identity.py:make_identity`). §9 sets every observation's
`recorded_from` to "one capture instant … taken from the store clock at the start of the
operation".

On resume, a fresh operation takes a *fresh* capture instant. Every `ObjectObservation` ID then
changes. The §8.2 resume probe ("probes each batch group's records with one scoped read and skips a
group whose inventory already matches") matches nothing, so the writer emits a full duplicate set
of observations beside the persisted ones. `_inventory`'s exactness and
`generation_checksums` (`store/generations.py:751-767`) then refuse the seal permanently: the
generation is unresumable *and* unsealable, and the only exit is the failed-generation cleanup path
§8.2 reserves for conflicting payloads. `BuildReceipt.resumed_from_batches` would always read 0.

A fresh instant breaks resume through a **second** path as well. `ArtifactRevision.observed_at`
(`model.py:350`) is deliberately *not* in its identity (`model.py:353-354`, and
`knowledge/lifecycle.py:28-31` explains why), so a re-taken instant produces the **same** revision
ID with a **different payload**, which `put_knowledge` refuses outright:
`ValueError("Immutable record already exists with different contents")`
(`store/knowledge.py:654-656`). The observations fork silently; the revisions fail loudly. Both
close with the same amendment.

**Amendment.** §9 must say the capture instant is **persisted with the generation and re-read on
resume, never re-taken**. `Generation.created_at` is the natural carrier: it is already written at
install and is *not* in `Generation.identity_fields` (`model.py:368-375`), so adopting it changes no
generation ID. Add to §8.2: "on a successful `reclaim_generation_build`, the coordinator adopts the
stored generation's recorded capture instant; it takes a new instant only for a generation it is
creating." Add to CD7: "a resumed build reproduces every `ObjectObservation` ID byte-identically
and reports a nonzero `resumed_from_batches`."

### B5 — `reclaim_generation_build` as specified drops four of `claim_generation_build`'s guarantees

**Binds:** §8.2 (plan lines 288-307), CC3. **Severity: blocker.**

The plan specifies reclaim as "admits only a never-published `staging` or `failed` generation whose
`manifest_hash` equals `expected_manifest_hash`, takes the source lock, advances the fence, installs
a fresh holder and returns the generation to `staging` without collecting". Compared with
`claim_generation_build` (`store/generations.py:190-247`), four preconditions are missing:

1. **The tombstone barrier.** `claim_generation_build:195-200` calls `self._tombstoned(...)` and
   refuses "before the fence advances, before a holder is installed, and before the retained
   attempt could be collected". The plan omits it. Answering the brief's question directly: as
   specified, **a reclaim can resurrect a tombstoned source** — it advances the fence past the one
   `apply_source_tombstone` installed (`generations.py:129`) and installs a live holder on a
   suppressed source.
2. **Live-holder exclusion.** `claim_generation_build:212-220` refuses
   `"Source already has a live build holder"` unless the caller *is* that holder
   (same `input_fingerprint`, `job_key` and `lease_owner`, in which case it returns the existing
   job idempotently). Without it two builders can hold the same generation.
3. **The future-lease check** (`:202-203`, `lease_expires_at <= now`).
4. **The full never-published triple.** `fail_generation_build:311-318` and
   `_publish_generation:1098-1106` treat `published_at is not None`, `source.active_generation_id ==
   gen.id` and any `IndexEvent(kind="published")` as three independent proofs;
   `claim_generation_build:204-211` checks two of them. "Never-published" must be all three.
   `attempt_count` bookkeeping (`:236-238`) should also carry over.

**Amendment.** Replace §8.2's prose specification with an explicit list: reclaim performs every
step of `claim_generation_build` *except* `_collect_generation`, and additionally requires
`expected_manifest_hash`. Add to CD7: "a reclaim on a tombstoned source, on a source with a live
holder, with an expired lease, or on a generation with any publication proof, refuses without
advancing the fence."

### B6 — Publishing bumps the authorization epoch the coordinator asserts unchanged

**Binds:** ruling 6, §7, CC1/CC9. **Severity: blocker.**

`begin_managed_source` (`store/generations.py:82-87`) calls `_bump_authorization_epoch()`.
`prose_generation._publish` (`ingest/prose_generation.py:589-598`) asserts, immediately after
`publish_staged_generation` returns, that `store.authorization_epoch()` still equals
`guard.expected_authorization_epoch`, and then re-captures authority and compares both epochs and
the whole `SourceControl` again at `prose_generation.py:605-618`.

The prose lane survives because it already flipped the flag at `_install`
(`prose_generation.py:491`), before `_publish`, with the `+ int(not source_is_managed)` arithmetic
at `prose_generation.py:484` accounting for the bump inside the install window. Under ruling 6 the
code lane flips at publication instead, so a code coordinator that copies `_publish` verbatim will
raise `AuthorizationChanged("Authority changed during publication")` on **every** bootstrap, and
the `fresh.source_control != replace(guard.source_control, active_generation_id=gen.id)` comparison
at `prose_generation.py:612` will also fail, because `SourceControl.managed`
(`build_authority.py:56`) flips from false to true in the same transaction.

**Amendment.** §7 must state the publication-window epoch arithmetic explicitly: the code lane's
publish expects `guard.expected_authorization_epoch + int(not store.source_is_managed(source_id))`
and expects `source_control` to differ in **both** `active_generation_id` and `managed`. Add to
CD8: "a bootstrap publication succeeds with the managed flip inside its transaction, and a genuine
unrelated authorization change in the same window still refuses."

Ruling 6 is otherwise sound for the prose lane: removing the automatic flip leaves
`prose_generation.py:484`'s `+1` to be produced by the explicit `begin_managed_source` at `:491`
instead of by `put_knowledge(gen)` at `:488`, so the net epoch delta across `_install` is unchanged
in both the first-attempt and the retry case. **No reviewed prose invariant breaks.**

---

## Majors

### M1 — `manifest_hash` equality is a tautology, not a guard

**Binds:** §8.2 (plan lines 289-307), CC3. **Severity: major.**

`Generation.identity_fields` (`model.py:368-375`) includes `manifest_hash`, and `Record` validates
that `id` equals `make_identity(prefix, identity_parts())` (`model.py:143-153`). A stored
generation with ID *G* therefore necessarily has the `manifest_hash` that was hashed into *G*.
Passing `generation_id` already pins it. The plan's own sentence at line 306 — "identical accepted
inputs produce the identical generation ID, so a retry either matches exactly or is a different
generation" — is the proof that the parameter adds nothing.

Keep the parameter (a cheap assertion against a corrupted row costs nothing) but **stop presenting
it as the safety property**: the real preconditions are B5's list, and the real staleness risk is
M2's.

### M2 — Resume has no guard against staged rows written by a different code version

**Binds:** §8.2 (plan lines 308-315), CC8/CC9. **Severity: major.**

The plan's failure mode for a stale row is "same ID, different payload", which
`put_knowledge` refuses correctly (`store/knowledge.py:654-656`). But most knowledge IDs are
content-derived (`EvidenceSpan.identity_fields = ("revision_id", "locator_json", "text_hash")`,
`model.py:419-420`), so a changed derivation produces a **different ID** — an extra orphan row, not
a conflict. Those are invisible to a probe that looks for what it expects and finds it absent; the
build writes its own set beside them and the seal then refuses forever on inventory exactness.
Nothing in generation identity pins the chunker, `input_binding` or writer versions: §5 puts the
walker/grammar versions in `configuration_json`, but not the derivation rule versions.

**Amendment.** Either add the derivation rule/view versions to the `configuration` that enters
`generation_for_inputs` (so a changed derivation is a different generation and resume is
impossible by construction), or make §8.2's resume probe assert the *absence* of unexpected
generation-scoped rows as well as the presence of expected ones, and fail closed with a named
remediation. State which. Add to CD7: "a staged generation holding a record the current
derivation would not produce fails the resume rather than sealing."

### M3 — `native_write` and `native_mutation` cannot be scoped by generation

**Binds:** §8.1 (plan lines 258-263), CC2. **Severity: major.**

§8.1 asks for "generation-scoped, parameterised reads" and then says to make all three helpers use
them. Two of the three cannot be scoped by generation:

- `native_write` (`generations.py:1276`) reads `existing` to find a *prior* row before the
  generation is known — `generation_id = row.get("generation_id") or (prior or {}).get("generation_id")`
  (`generations.py:1284`) is the fallback that keeps untagged legacy writes working. Scoping by
  generation would break that path. It must scope by `ids=[row["id"] for row in rows]`.
- `native_mutation` (`generations.py:1379-1384`) discovers which argument strings are native IDs by
  membership in the whole table, and its cross-generation check
  (`generations.py:1412-1424`) is *only* meaningful when rows of other generations are visible.
  Scoping by generation would silently delete that check. It must collect every string in
  `args`/`kwargs` and do one `_native_rows(kind, ids=candidates)` lookup per kind; membership is
  then preserved exactly, and the work is bounded by the argument size rather than the corpus.

**Amendment.** §8.1 must say which helper scopes by which key: `ids=` for `native_write` and
`native_mutation`, `generation_id=` for `_inventory` and `generation_checksums`. Add to CD1:
"`native_mutation` still raises `Native relationship crosses generations` for an edge whose
endpoints belong to two generations, and still admits an edge to an untagged legacy row exactly as
before."

### M4 — Native tables have no `generation_id` index, so a scoped read is still a full scan

**Binds:** §8.1, CD1, CC2. **Severity: major.**

`store/base.py:95-118` creates `symbol_source`, `data_object_source` and `commit_source` indexes on
`n.source_id` only. There is no index on `generation_id` for `Symbol`, `DataObject`, `Commit` or
`Passage`. The knowledge tables do get one — `migrations.py:428` emits
`CREATE INDEX knowledge_<name>_<field>` for `generation_id` among others — but the native tables are
not in that list; `migrations.py:421-424` only `ALTER TABLE … ADD generation_id STRING`.

So on Neo4j `MATCH (n:Symbol {generation_id:$g})` is a label scan: linear in the whole table, not
in the generation. CD1's stated criterion — "a recorded query counter proves per-batch work is
bounded by the batch rather than by corpus size" — would pass while the database work stays exactly
as quadratic as today, which is the defect §8.1 exists to fix.

**On Ladybug it is worse: there is no secondary index at all.** Ladybug overrides
`_ensure_legacy_schema` (`store/ladybug.py:422-447`) and creates node tables, relationship tables
and the Settings row only — it never runs `base.py`'s `CONSTRAINTS` list, so not even the existing
`symbol_source` index exists there. `schema_steps`' Ladybug branch (`store/migrations.py:398-424`)
creates tables and `ALTER TABLE … ADD` columns; the `CREATE INDEX knowledge_<name>_<field>`
statements at `migrations.py:427-440` are in the **else** branch, Cypher-only. Ladybug is the CD9
**acceptance** backend.

**Amendment.** Add the four `CREATE INDEX … ON (n.generation_id)` statements for `Symbol`,
`DataObject`, `Commit` and `Passage` to CC2's scope, and add `src/hippo/store/base.py` (plus
`src/hippo/store/migrations.py` if a schema-version bump is needed) to CC2's exclusive files. CC2
must also decide the Ladybug story explicitly — either add index support there or state that it has
none. CD1's CRITERIA must add: "the scoped read is index-backed on the backends that support one,
evidenced by the schema statement and not only by the query counter", and CD9 must record which
backend the bound is actually proven on rather than implying it holds on the acceptance backend.

### M5 — §8.1 misses the quadratic Python loops inside `generation_checksums`

**Binds:** §8.1 (plan lines 245-256), CD1/CD9, CC2. **Severity: major.**

Three costs inside `generation_checksums` are per-row, not per-call, and survive any query scoping:

- `generations.py:751-767`: for **every** binding it rebuilds the full `observations` list from
  `exact` and scans it — O(bindings x exact).
- `generations.py:789-791`: for **every** native row it scans **every** binding — O(natives x
  bindings). At the plan's own `CODE_MAX_SYMBOLS_PER_SOURCE` ceiling (50,000, `codegraph/model.py:41`)
  that is 2.5e9 comparisons per seal.
- `generations.py:1189-1193` and `:1231`: `_validate_managed_native` reads every
  `GenerationMember` and, for a parented passage, every `Passage` row — **once per row** inside
  `native_write`'s loop.

**Amendment.** Add these three to §8.1's list of what CC2 fixes (index the inner loops with dicts
and sets keyed by `object_id` and `(native_kind, native_id)`, and hoist the per-row reads out of the
loop). Add to CD1: "sealing a generation at the §8.3 symbol ceiling is linear in the generation in
CPU as well as in queries." CD9's "multi-hundred-file fixture" is not large enough to catch this;
say so, or raise it.

### M6 — `rebaseline()` cannot "re-run `check_local()` in full", and §8.2 contradicts ruling 2

**Binds:** §8.2 (plan lines 318-324), ruling 2, CC8. **Severity: major.**

Two defects.

*(a) It cannot work as written.* `check_local` refuses on an epoch mismatch as its **first** act
(`knowledge/build_authority.py:263-265`), so a rebaseline that calls it will always fail — that is
the very condition it exists to clear. The workable shape is `bind_inputs`'s
(`build_authority.py:317-334`): under the source and authorization locks, construct a child
`BuildAuthority` with the *current* epochs and the *original* actor, accepted inputs and
`source_control`, call `child.check_local()`, and only on success adopt the new epochs.

*(b) §8.2 says "adopts the current epochs", plural.* Ruling 2 says "may adopt a new
*authorization* epoch only". The suppression epoch must stay frozen at capture, because
`publish_staged_generation(expected_suppression_epoch=...)` (`generations.py:1020-1021`) is what
makes a suppression landing mid-build refuse at publication. Adopting it would discard that.

**Amendment.** Rewrite §8.2's rebaseline paragraph as: authorization epoch only; suppression epoch
frozen; `source_control` **frozen at capture, never adopted** — `SourceControl`
(`build_authority.py:49-58`) carries `access_role_id`, `min_rank` and `owner_id`, so adopting a
changed one would let an operator re-target the finished generation's audience mid-build; and the
child-authority construction above. Add to CD8: "a rebaseline refuses when the Source row's
`access_role_id` or `min_rank` changed, even though the actor kept every capability."

### M7 — "a suppression that applies to this source" is under-specified

**Binds:** §8.2 (plan line 323), ruling 2, CC8. **Severity: major.**

`publish_staged_generation:1022-1045` defines the set that matters as the generation's *reachable
closure* — the source, plus every accepted revision, artifact and policy, plus every `EvidenceSpan`,
`AssertionVersion` and `DerivedRecord` in exact membership. A rebaseline that only checks
`("source", source_id)` would continue a build over an input that has just been suppressed, and
publication would then refuse at the end after the whole corpus had been staged.

**Amendment.** Define "applies to this source" in §8.2 as exactly the closure
`publish_staged_generation` computes, and reuse that computation rather than restating it.

### M8 — `repo_name`'s two-segment truncation collides distinct repositories

**Binds:** §5 (plan lines 160-165), CC4/CC9. **Severity: major.**

`ingest/repos.py:49-56` returns `"/".join(parts[-2:])` — the last two path segments. For a GitLab
subgroup layout, `https://host/alpha/team/api` and `https://host/beta/team/api` both normalize to
`team/api`. §5 makes that string the `provider_repository_id` inside
`repository_identity(workspace, provider_instance, provider_repository_id)`
(`knowledge/identity.py:157`), and `symbol_key` (`identity.py:264-273`) takes the repository as its
first term. Two unrelated repositories would share one `repository` KnowledgeObject and merge their
symbol identities.

**Amendment.** §5 must specify the full normalized path minus a trailing `.git`, not
`repo_name`'s last two segments, and must define the normalization (lowercase host; path case
preserved or folded — say which, because `host/Acme/Robots` and `host/acme/robots` are the same
GitHub repository and would otherwise mint two identities). Name `repos.repo_name` in §2 as a
reference that is *not* reused, the way §2 already does for `walk_repo`.

---

## Minors

### m1 — CD5's CHECK names a test file that does not exist and no task creates

`tests/unit/test_input_binding.py` is absent; the reviewed suite is
`tests/unit/test_managed_input_binding.py`. CD5 (`GATES.md:38`) would abort with a collection error.
**Amendment:** rename it in the CHECK line. *(Binds CD5/CC11.)*

### m2 — CD10's EXPECT diverges from the ledger's own lint convention

The reviewed prose ledger records its lint gate as `EXPECT: 4 files already formatted`
(`ai_docs/gates/rag-it-all/task-5-prose-coordinator/GATES.md:25`) — the final line of
`ruff format --check`. CD10 (`GATES.md:65`) says `EXPECT: passed` over 8 Python files and 2
Markdown files. This is **not** a failure: the checker matches as a substring (PC1's
`EXPECT: passed` is satisfied by output `66 passed, 1 skipped in 6.75s`,
`task-5-prose-coordinator/GATES.md:8-10`), and `passed` is a substring of `ruff check`'s
`All checks passed!`. It is a weakness — `passed` is satisfied by the *first* half of a compound
`&&` line, so a formatter regression could hide behind `ruff check`'s success text.
**Amendment:** `EXPECT: 10 files already formatted`, matching PC4. *(Binds CD10/CC11.)*

I verified both documents format clean today: `.venv/bin/ruff format --check` on the plan and the
ledger prints `2 files already formatted`, exit 0.

### m3 — The remaining nine CHECK lines are runnable as written

Every other existing file a CHECK names is present, and none of them imports `fastapi.testclient`
at module level: `tests/unit/test_status_access.py` uses the sanctioned per-test form (a) marker at
`:238`, `:305`, `:322`, `:368`, `:421`, `:446`, `:470` with function-level imports at `:240`,
`:307`, `:332` and so on. No CHECK line needs the command-line form (b) filter. *No change.*

### m4 — `git log --first-parent` is an uncounted history gap

`codegraph/git_history.py:319` walks with `--first-parent`, so commits on merged side branches are
never seen. §9's coverage list records `skipped`, `truncated` and the shallow boundary but not
this. **Amendment:** add the first-parent restriction to the §9 coverage list and to CD6, so a
first-parent walk is never presented as the repository's complete history.

### m5 — §9 omits `evidence_class` for observations

`ObjectObservation.evidence_class` (`model.py:495`) is required and is in its identity
(`model.py:496-508`), so it is part of every observation ID. §9's table does not set it.
**Amendment:** add the row.

### m6 — Clone failures log the URL and git's raw stderr

`ingest/repos.py:116` logs `"git clone of %s failed: %s"` with the full URL and git's stderr, and
`:136` logs absolute paths. `is_git_url` accepts `https://user:token@host/owner/repo`
(`repos.py:43-46`), so a credentialed URL is logged verbatim, and `_explain_git_failure:110-114`
puts both the URL and git's last stderr line into the user-visible `RepoError`. §10 promises the
opposite for all three. The Source-row half of §10 *does* hold today:
`status._public_error` (`status.py:156-168`) renders from the stable code and never echoes the
stored sentence. **Amendment:** §10 must name the redaction as work, not as an existing property,
and `src/hippo/ingest/repos.py` must be added to CC10's exclusive files (see M10).

### m7 — Symbol identity drifts across walker versions; it does not collide

Answering the brief's question 7 directly: two generations of the same repository at the same
commit with different walker versions **cannot collide or wrongly dedupe**. `WALKER_RULES_VERSION`
(`codegraph/syntax_cache.py:23`) and `parser_profile` (`:46`) enter `configuration`, which enters
`generation_for_inputs`'s manifest (`knowledge/lifecycle.py:47-54`), which determines
`manifest_hash` and hence the generation ID; and native IDs are re-derived from
`generation_namespace` and rejected on mismatch (`generations.py:1238-1257`). What *does* happen is
drift: `symbol_key` (`identity.py:264-273`) is deliberately not generation-scoped, so a walker that
changes a `qualified_name` or a signature mints a **new** `KnowledgeObject` and the old one keeps
its observations. That is the intended shared-canonical-object design, but §5 should say so
explicitly, because it means a walker upgrade silently forks symbol history. *No blocking change.*

---

## Split findings

### M9 — Three files the split needs are owned by nobody

**Severity: major.** **Binds §12.**

- `src/hippo/ingest/prose_generation.py` holds `BuildReceipt` (`:120`) and `_Run` (`:139`). CC9's
  required result is "`_Run` factored out of `prose_generation.py` without changing its contract"
  and §3 adds `resumed_from_batches` to `BuildReceipt` — both edits land in a file in no task's
  exclusive list. **Add it to CC9**, and add `tests/unit/test_prose_generation.py` as a
  regression-only suite CC9 must keep green unchanged.
- `src/hippo/store/base.py` (and possibly `migrations.py`) for M4's indexes. **Add to CC2.**
- `src/hippo/knowledge/build_authority.py` for B3's kind allow-list and presence-test removal.
  It is currently CC8's, but B3 blocks CC9 which depends on CC8 anyway; **move the `_source_control`
  half to CC1** and leave `rebaseline` with CC8, with an explicit file handoff CC1 → CC8.

### M10 — B2's guard re-pointing crosses four task boundaries

**Severity: major.** **Binds §12 CC1/CC10.**

Under shape (a), the five guards in B2 live in `store/generations.py` (CC1),
`store/code.py` (nobody), `ingest/managed_activation.py` (CC10), `ingest/pipeline.py` (CC10) and
`knowledge/source_lifecycle.py` (nobody). CC10 runs *last*, so on the plan's current order the
window B2 describes stays open from CC9 until CC10 lands — and CC9's own CD8 spies
("`delete_code_nodes_for_source` … are never called for a managed attempt") would be asserting a
property the code does not yet have.

**Amendment:** either move the guard re-pointing forward into CC1 (adding `store/code.py`,
`knowledge/source_lifecycle.py`, `ingest/managed_activation.py` and `ingest/pipeline.py` to CC1, at
which point CC1 is no longer "the smallest store slice"), or take B2 shape (b) so the existing
guards keep firing unchanged and CC1 stays small. **This is the one decision I am handing back, and
CC1 is already running.** Add `src/hippo/ingest/repos.py` to CC10 for m6 either way.

### M11 — Two tasks are over the fleet budget

**Severity: major.** **Binds §12 CC2/CC9.**

The fleet rule is that a worker finishes within roughly 400-500k tokens
(`ai_docs/handoffs/fleet-worker-rules.md:58`). Two tasks are not sized for that:

- **CC2** now covers scoped read primitives on four files, the M4 indexes on two more, the M3
  rewiring of two decorators with their cross-generation semantics intact, the M5 inner-loop
  work, and byte-identical-checksum proof on Fake, Ladybug **and** Neo4j.
  **Amendment:** split into CC2a (primitives + indexes + equal-results proof on all backends) and
  CC2b (rewire `native_write`/`native_mutation`/`generation_checksums`, inner loops, query-count and
  complexity proof). CC3 then depends on CC2a only and can run in parallel with CC2b.
- **CC9** builds the analogue of `prose_generation.py` (762 lines, which took a whole worker for the
  prose slice) *plus* resume *plus* the `_Run` extraction *plus* `build_run.py`.
  **Amendment:** split into CC9a (`build_run.py` + the `_Run` extraction, proven by the unchanged
  prose suite) and CC9b (`code_generation.py`: bootstrap, refresh, resume, failure, receipt).

`CC6` (the analogue of `input_binding.py`, 457 lines) is at the edge but acceptable; CC8
(`staged_prose.py` is 242 lines) is comfortable once `rebaseline` is its only extra.

### Other split checks — dependencies are complete and the remaining boundaries are real

I grepped for helpers two tasks would both edit and found none beyond M9-M10: CC5, CC6 and CC7
create new modules only; CC4's `repo_capture.py` consumes `readers.IGNORED_DIRS` (`:36`),
`is_code_name` (`:145`) and `PROSE_EXTENSIONS` (`:58`) **read-only**, and `readers.py` is CC10's, so
CC4 is safe as long as it adds no new reader predicate — worth stating in CC4's brief. CC3's
"the CC2 store files, released by CC2" sequencing is correct. Ruling 3 lets CC1 adapt five existing
test files not in its exclusive list; nothing else touches them in this wave, so that is safe, but
the ledger should record it. *No change beyond noting CC4's read-only constraint.*

---

## Answers to the ten questions

**1. Is the legacy-serving predicate sufficient and safe?** No — see B1, B2, B3. The predicate
itself (`managed` false, no active pointer, no published `IndexEvent`) is the right *shape*; three
things are missing. Reachability of a staged-only source through paths the plan does not name:

- **Legacy graph fall-through** — reachable, B1 (`context.py:176-178` →
  `graph_index.py:411-432`).
- **Source page / legacy passage read** — `store.passages_for_source`
  (`store/memory.py:281-294`) has no `generation_id` filter, so the converting source's staged
  passages appear on its own page. It is reached only through the `else` branch at
  `web/routes/sources.py:195-200`, which is taken exactly when the row's `managed` is false —
  which is the whole bootstrap. **Reachable; CD2 must cover it.**
- **MCP source list** — `mcp_server.py:536-540` calls `status.source_view`, so the `status.py`
  half of the fix covers it. *Not separately reachable.*
- **Status inventory** — `status.py:58-65` has its **own** presence test with a third term
  (`meta.managed`) the plan does not mention, and `status.py:74-76` then drops any source that is
  neither in `legacy_ids` nor `represented`, so a converting source vanishes entirely today.
  Covered by the fix once §7 names `status.py:58-65` precisely (it names `:58-59`).
- **Structural / snapshot path** — `_build_structural_graph` (`context.py:339`) and
  `knowledge/snapshots.py:148` select on `active_generation_id`, and
  `graph_loader.selected` (`:46-51`) already excludes tagged rows from a legacy source.
  *Correct under the fix; the plan's claim "staging records are already invisible to selection"
  holds for these.*
- **Eval and changeset access** — `evals/rag_all.py:347` and `evals/rag_all_temporal.py:416` use
  `list_sources()` for presence only and read through `ctx.graph_for`. *Not separately reachable.*

**Does moving `begin_managed_source` into the publication transaction break a reviewed prose
invariant?** No, and I checked the arithmetic both ways — see B6's last paragraph. The prose
coordinator's tests should pass unchanged. But the *code* lane's publish must expect the bump, which
is B6.

**2. Does `reclaim_generation_build` preserve every reviewed guarantee?** No — B5 lists four
missing preconditions. **Can a reclaim resurrect a tombstoned source?** As specified, **yes**
(no `_tombstoned` barrier). **Can it reuse a lease across a suppression?** Only through the same
gap: `_check_build` (`generations.py:248-269`) compares `source.build_fencing_token` against the
job's, and `apply_source_tombstone` advances that fence (`generations.py:129`), so an *existing*
lease dies correctly at the tombstone; the risk is a *new* holder installed by a reclaim that
never checked. Both close with B5's amendment. `fail_generation_build`'s non-collecting contract
(`:293-330`) and `recover_generation_builds`' fence-clearing (`snapshots.py:365-378`) are
unaffected by reclaim. A crash *after* the seal is recoverable: recovery turns `ready` into
`failed` (`snapshots.py:377-379`), reclaim returns it to `staging`, and `seal_generation`
tolerates a byte-identical existing manifest (`generations.py:844-846`) — provided B4 is fixed.

**3. Are the proposed scoped reads sufficient, and can checksums stay byte-identical?**
Sufficient only with M3, M4 and M5. **Byte-identity is achievable**: `_native_relationships`
canonicalizes with `sorted(result, key=canonical_json)` (`generations.py:665`), so enumeration
order does not enter the checksum, and the `reachable` closure
(`generations.py:645-652`) depends only on `ids`, which is already the generation's own row set
(`generations.py:800`). Two constraints CC2 must honour and the plan does not state: the scoped
edge enumeration must still return edges with **exactly one** endpoint in `ids`, or the
`ValueError("Native relationship crosses generations")` at `generations.py:655-657` and the
`ValueError("Missing shared graph endpoint")` at `:660-661` both disappear; and the two-hop
`MENTIONS`/`STATES` → `SUBJECT`/`OBJECT` closure at `generations.py:650-652` needs a second scoped
pass. Add both to CD1.

**4. Can a partially written batch group be mistaken for complete?** Not by partial *persistence* —
each batch is one transaction, so a group is all-or-nothing. Three real ways it can be mistaken:

- **Sampling.** If the probe checks one representative row per group and infers the rest, a group
  whose membership *changed* between attempts (M2) reads as complete. **Amendment for CC8:** probe
  every row of the group, or write an explicit last-record sentinel per group.
- **`native_write`'s tolerant equality.** `generations.py:1303-1315` treats rows differing only in
  `boost`, `community`, `entities_json`, `triples_json` or `extraction_error` as identical and
  skips them. A resume that relies on `native_write`'s skip rather than comparing the canonical
  payload itself would accept a symbol whose community label differs from the one this attempt
  computed. **Amendment for CC8:** the probe compares `_canonical_native` output itself.
- **A relation group whose endpoint group came from a different attempt.** `native_mutation` checks
  only that both endpoints share a generation (`generations.py:1412-1424`) — not which attempt wrote
  them. Under B4/M2 a resumed attempt can produce endpoints with different IDs, and the relation
  group then binds to whichever set it finds. Closed by B4 and M2 together; CD7 should assert it
  directly.

**5. `rebaseline()` under the orchestrator's conditions.** With M6 and M7 applied, an operator who
changes roles between batches **can**: continue the build across an unrelated role change (the
point of the feature); widen or narrow *other* principals' access to already-published sources; and
cause wasted staged work by revoking and restoring a capability. They **cannot**: continue after
losing any capability (`check_local`'s `core.build` proof and `proof.revision_ids` comparison,
`build_authority.py:282-287`, refuse); continue across a suppression of the source or of any
accepted input (M7); re-target the finished generation's audience by editing the Source row (M6's
frozen `source_control`); or make a denied input readable — publication independently re-checks the
suppression epoch and the reachable closure (`generations.py:1020-1045`), and the manifest is
input-only. The residual is bounded and benign: a capability lost *during* a batch's write
transaction is caught at the next batch, and nothing staged is readable before publication. Without
M6's freezes, the `source_control` adoption is a genuine privilege-widening path — that is why M6 is
major rather than minor.

**6. Do §9's temporal choices agree with Task 5A?** Yes, with two gaps. Every value is in the
implemented vocabulary: `ValidityKind` (`model.py:49`) has `explicit_interval` and
`observed_snapshot`; `TemporalBasis` (`:50-52`) has `commit` and `observed`; `TemporalPrecision`
(`:53`) has `second`. `explicit_interval` with `valid_from` set and `valid_to=None` passes
`TemporalRecord.intervals` (`model.py:477-487`), and `observed_snapshot` with both bounds `None`
passes the same validator. `recorded_from` is set independently of `valid_from`, and no wall-clock
default appears. `%aI` is exactly what `read_history` captures —
`LOG_FORMAT = f"%H{_UNIT}%P{_UNIT}%an{_UNIT}%aI{_UNIT}%B{_RECORD}"` (`codegraph/git_history.py:80`),
author date with offset, parsed at `:335-341` — so §9's `source_timestamp_original` and
`source_timezone` are honest. The two gaps are m5 (`evidence_class` unset) and m4 (`--first-parent`
uncounted). B4 is a *resume* consequence of §9, not a temporal-correctness one.

**7. Identity.** No collision and no wrong dedupe between two walker versions — see m7 for the
proof chain. The real identity defect is M8's `repo_name` truncation. §5's namespace rule
(`generation_namespace`, `knowledge/lifecycle.py:66-68`, re-derived and enforced at
`generations.py:1238-1257`) is sound, and `symbol_key`'s signature discriminator
(`identity.py:264-273`) does keep overloads apart as §5 claims.

**8. Privacy.** §10's Source-row and public-error guarantees hold today (`status.py:156-168`,
`knowledge/public_errors.py`). The model-I/O boundary is right: ruling 5 keeps prose OpenIE to
`readers.PROSE_EXTENSIONS` files and no code text reaches a chat model. The log guarantee does
**not** hold — m6. One more to state in §10: `EvidenceSpan.text` (`model.py:419-420`) stores the
original code text in the database by design, so §10's "source text never reaches logs" must not be
read as "code text is not stored"; the access boundary, not absence, is what protects it.

**9. Split.** Boundaries are real except M9 and M10; two tasks are over budget (M11); dependencies
are otherwise complete.

**10. Ledger.** Nine of ten CHECK lines are runnable as written once the named new test files exist
(m3). CD5 is not (m1). CD10's EXPECT does not match the convention (m2). The CRITERIA amendments
requested above: CD1 (M3, M4, M5, Q3's two constraints), CD2 (B1, B2), CD6 (m4), CD7 (B4, B5, M2,
Q4's three cases), CD8 (B6, M6), CD9 (M5's ceiling note).

---

## Per-task rulings

| Task | Verdict |
| --- | --- |
| CC1 | **Amend before spawn.** B1 (split loader-selection from serving lane in `context.py`), B2 (settle option (a) or (b) — this is the orchestrator's call and it changes CC1's file list), B3's `_source_control` half plus `build_authority.py` ownership, B6's publish-window arithmetic (moot under shape (b)), and CD2's two new criteria. |
| CC2 | **Amend before spawn.** M3 (scope by `ids` not generation for the two decorators), M4 (`base.py` + the four indexes, added to its file list), M5 (the quadratic inner loops), Q3's two enumeration constraints, and M11's CC2a/CC2b split. |
| CC3 | **Amend before spawn.** B5 (the four missing preconditions, written out explicitly) and M1 (stop presenting manifest equality as the safety property). |
| CC4 | **Amend before spawn.** M8 (full normalized repository path, not `repo_name`) and the note that `readers.py` is read-only for this task. |
| CC5 | **Amend before spawn.** M2's derivation-version decision, if it lands as "rule versions enter generation identity", changes what `prepare_code_chunks` must record. Otherwise unchanged. |
| CC6 | **Unchanged.** m5 (`evidence_class`) is a one-line addition to its §9 input, not a contract change. |
| CC7 | **Unchanged.** m4 and m5 are coverage/field additions inside its own new files. |
| CC8 | **Amend before spawn.** B4 (adopt the persisted capture instant on resume), M2 (probe asserts absence as well as presence), M6 and M7 (rebaseline's real shape and freezes), Q4's three probe cases. |
| CC9 | **Amend before spawn.** B3 (it cannot start without the kind allow-list), B4, B6, M9 (`prose_generation.py` ownership), M11's CC9a/CC9b split. |
| CC10 | **Amend before spawn.** B2's guard re-pointing if shape (a) is chosen, and m6 (`repos.py` added for redaction). |
| CC11 | **Amend before spawn.** m1 (CD5's file name), m2 (CD10's EXPECT), and the six CRITERIA amendments listed under question 10. |

---

*No file outside this report was modified. No test was run; the only command executed against the
repository was `ruff format --check` on the plan and the ledger, read-only, recorded in m2.*
