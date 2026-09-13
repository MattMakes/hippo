# qscope evidence: query-time knowledge reads scoped to the selected generations

Branch `wp/qscope`, worktree `.worktrees/qscope`. Brief `ai_docs/handoffs/briefs/fix-query-reads-scope.md`.
Base `2577add`, reset to `c4ba26e` (LBPOOL merged, no commits yet) and fast-forwarded to `4795c0e`
(CC11 merged) under the orchestrator's two authorizations; the uncommitted work was set aside as a
patch and reapplied cleanly both times.

Commits, on `4795c0e`:

1. `9094c52` Read knowledge records by a list of primary keys in one keyed query (the reader and its
   tests).
2. `a816767` Scope the knowledge reads a query makes to the generations it selects (the consumers,
   the granted test double, the query-life tests, and the guard for a lookup of no IDs; `a68ff39`
   amended).
3. The commit that carries this file.

## The defect

CC11 measured it (`evidence-cc11.md`): 30+ whole-table reads of generation-sized kinds during one
lease renewal, and on LadybugDB at about 50 files a 427 s projection and a dense dispatch of more
than seven minutes. KSCOPE (`evidence-kscope.md`) had scoped the knowledge reads a managed *build*
makes; a *query* still read the kinds whole.

A caller-attributed run on the pre-fix tree (`4795c0e`) over the new test's query life -- a
structural `query_session` opened, its lease renewed on the heartbeat thread and once in place,
then an owned `retrieval_session` and an owned `dense_session` -- names every site. The code world
(G1 retired by a refresh, G2 selected) and the prose world (`last-good` retired, the prose
generation selected) give the same counts (`/tmp/hippo-qscope-sites-before.json`):

| Whole-table reads | Kind | Site (pre-fix line) |
| --- | --- | --- |
| 198 each | `IndexManifest`, `GenerationEvidenceMember`, `GenerationMember`, `EvidenceSpan`, `ObjectObservation`, `DerivedRecord`, `DerivedDependency`, `RetrievalView`, `NativeBinding` | `knowledge/access.py:319` `EvidenceAccess.build`'s `rows(kind)` |
| 6, 6, 3 | `NativeBinding`, `ObjectObservation`, `EvidenceSpan` | `knowledge/projection.py:417` `project_managed_graph`'s `allowed()` |
| 3 | `GenerationMember` | `knowledge/projection.py:426` `project_managed_graph` |
| 3 | `IndexManifest` | `context.py:402` `_build_structural_graph` (and `:282` `_build_managed_graph`) |
| 3 | `IndexEvent` | `store/snapshots.py:47` `_check_snapshot_inputs` |

The multiplier is the proof: one query life built 198 of them. A session builds one proof per
workspace at open and one for its snapshot bundle, and every `validate()` -- each renewal, and each
guarded model call and output check -- rebuilds both. Each build read nine generation-sized kinds
whole. Not on that path but in the brief's list: `store/snapshots.py:248` and `:297`/`:305`
(collection) and `knowledge/temporal.py:495` (history).

## What each read is now

| Site | Before | After |
| --- | --- | --- |
| `EvidenceAccess.build`, a proof over explicit generations | every kind whole, once per proof | `_ProofReads(bounded=True)`: `IndexManifest`, `GenerationMember` and `NativeBinding` per selected generation, `GenerationEvidenceMember` per exact generation (`generation_id=`); the exact members' `EvidenceSpan`, `ObjectObservation`, `AssertionVersion`, `AssertionSupport`, `DerivedRecord`, `DerivedDependency`, `RetrievalView`, `ProseExtraction` in one read per kind (`ids=`); a compatibility generation's spans and observations per revision (`where={"revision_id": ...}`); `ArtifactRevision`, `Artifact`, `KnowledgeObject`, `Assertion` and `Generation` by ID |
| `EvidenceAccess.build`, no generation selection | whole | unchanged: `_ProofReads(bounded=False)` answers every narrowed question by filtering the whole kind, with the same queries as before, and a lookup of no IDs reads nothing, as the per-row lookup never ran (see "Reads left whole") |
| `_authorized_derivations` | `validate_view` per selected view: a fresh `_Inventory`, two member reads per view | one `derivations.GenerationViews` per generation per proof |
| `project_managed_graph` `allowed()` | each kind walked whole for the proof's IDs, `ObjectObservation` and `NativeBinding` twice | `_knowledge_rows(kind, ids=...)`, once per kind and ID set |
| `project_managed_graph` members | `GenerationMember` whole | per selected generation |
| `_safe_vectors` | `RetrievalView` by key and `validate_view` per rendered passage | one `ids=` read for every authorized rendered view; one `GenerationViews` per generation |
| `_project_prose` | `ProseExtraction` whole | `ids=` the proof's extraction IDs |
| `context._build_managed_graph`, `_build_structural_graph` | `IndexManifest` whole | `_strict_generations`: per active generation the sources select |
| `store/snapshots._check_snapshot_inputs` | `IndexEvent` whole | `generation_id=` |
| `store/snapshots._collection_block` | `GenerationMember` whole | `generation_id=` |
| `store/snapshots._collect_generation` | `IndexEvent` and four kinds whole | `generation_id=` |
| `knowledge/temporal._retention_gaps` | `GenerationMember` whole plus a `Generation` lookup per member | `Generation` rows (one per generation), then members per retained generation; nothing when no revision is asked |

The reader: `_knowledge_rows(kind, ids=...)` is new. One read for the whole list, driven by the
primary key through `store.base.by_ids` (`UNWIND ... MATCH (n:Kind {id: wanted_id})`, never `IN`,
`evidence-lbfix.md`), each record once, in the order asked, an unknown ID skipped. It is its own
selection: combining it with `where=` or `generation_id=` raises `ValueError("<Kind> is scoped by
ids alone")`, and a bare string raises `TypeError`. On the Fake store it is a dict lookup per key,
so it never walks a live dict another thread is writing. `ids=` needs no index beyond the
uniqueness constraint, so there is no schema v8.

### Reads left whole, by name

* **Authorization tables inside `build`:** `AccessPolicy`, `Connector`, `Workspace`,
  `GroupMembership`, plus `WorkspaceMembership` (`_identity`) and `Suppression` (`_suppressed`).
  They grow with principals and policies, not evidence (`evidence-kscope.md` finding 1).
* **A proof with no generation selection:** a legacy reader's `list_knowledge`/`get_knowledge`, and
  the history lane's broad proof (`select_history` -> `build_history()`), which proves every
  retained row before time narrows it. Its answer is the whole retained inventory.
* **The compatibility lane's `AssertionSupport`:** read whole only when a selected generation has no
  exact manifest and its revisions carry supports; `AssertionSupport.span_id` has no index.
* **`context.legacy_lane` / `_graph_for`:** `Generation` and `Artifact` whole to choose the loader
  and the lane. `Generation` is one row per build; `Artifact` grows with files (finding 6).
* **`knowledge/temporal._retention_gaps`:** `Generation` whole, one row per generation.
* **`store/generations.py:1765` `native_mutation`:** `IndexManifest` whole when a mutation touches a
  legacy `Entity` or `Fact`. Verified not on the query path; the question it asks is "every sealed
  generation", one row each, so no generation key narrows it.

## Results unchanged

Each narrowed read returns a superset of the rows the unchanged filters after it keep: spans and
observations are only ever kept inside the selected revisions, member tests only ever ask about a
selected generation, and the proof's records are fetched by the IDs the proof already holds. What
changes is dict iteration order, and every consumer is order-insensitive: the proof fingerprint
sorts, the proof's ID sets are frozensets, `policy -> deadline` is a function of the policy, the
projection sorts spans, entries and objects, and `_attributes` keeps only values every observation
agrees on. Every refusal is raised at the same point with the same message: `GenerationViews`
builds its inventory exactly where `validate_view` built one.

Reviewed suites, Fake, `-W error` with form (b) of the warning rule (the command line filter, because
some of these modules import `fastapi.testclient` at module level):

| Run | Result | Log |
| --- | --- | --- |
| Baseline at `2577add`: the brief's ten reviewed modules (`test_temporal_*` = conflicts, evidence, fixture loader) plus `test_knowledge_scoped_reads.py`, `test_generation_scoped_reads.py` | 400 passed, 1 skipped | `/tmp/hippo-qscope-base.log` |
| The same modules plus `test_query_scoped_reads.py`, after the fix | 409 passed, 1 skipped; with the guard and its test, 410 passed, 1 skipped | `/tmp/hippo-qscope-green-reviewed-2.log`, `-3.log` |
| Every unit module that touches a proof, a session, a projection, a snapshot, history or a knowledge read (73 modules, `/tmp/hippo-qscope-broad-files.txt`) | 2,080 passed, 6 skipped; with the guard and its test, 2,081 passed, 6 skipped | `/tmp/hippo-qscope-fake-broad-1.log`, `-3.log` |
| The build-path modules that list missed (`test_build_run`, `test_generation_profiles`, `test_import_order`, `test_ingest_concurrency`, `test_layering`, `test_managed_input_binding`, `test_store_knowledge`, `test_temporal_conflicts`, `test_transaction_ownership`) | 201 passed, 2 skipped, before the guard and with it | `/tmp/hippo-qscope-fake-broad-2.log`, `-4.log` |

LadybugDB (`HIPPO_TEST_STORE=ladybug`, under the 256 MiB pytest pool cap):

| Run | Before the guard | With the guard |
| --- | --- | --- |
| `test_query_scoped_reads.py`, `test_generation_scoped_reads.py`, bare `-W error` | 37 passed, 2 skipped (`/tmp/hippo-qscope-ladybug-new.log`) | 38 passed, 2 skipped (`/tmp/hippo-qscope-ladybug-new-2.log`) |
| The brief's selection: `test_query_session.py test_structural_loading.py test_code_projection.py test_temporal_conflicts.py -k "publish or select or reopen"`, form (b) | 8 passed, 114 deselected (`/tmp/hippo-qscope-ladybug-required.log`) | 8 passed, 114 deselected (`/tmp/hippo-qscope-ladybug-required-2.log`) |
| CC11's scenario at N=8, 4 GiB pool (the scenario's setting) | 2 passed, both trees (see "LadybugDB phase timings") | not rerun |

The pinned `graph.version` and `view_fingerprint` of `test_derived_projection.py::
test_original_only_graph_ids_and_fingerprints_are_unchanged` pass unchanged. The build path keeps
its old reads: `build_authority` proves by `revision_ids` alone, an unbounded proof. It keeps them
since the guard below.

**A regression found by the timings, and its guard.** In the N=8 LadybugDB runs below, CC11's
per-kind counts of reads made while building agree kind for kind except one. The after run adds
`KnowledgeObject:whole`, 6,602 reads, and the totals (737,385 before, 743,987 after) differ by exactly
that. The unbounded `_ProofReads.by_id` read the whole kind even when asked for no ID. Before the fix,
`rows("KnowledgeObject").get(...)` was only evaluated per group membership or per observation, and
`rows("Assertion").get(...)` only per version, so with none of them the kind was never read. The
guard makes a lookup with nothing to look up read nothing, bounded or not. Its test,
`test_a_whole_inventory_proof_reads_no_kind_it_has_nothing_to_look_up_in`, failed on the unguarded
tree with both kinds read (`/tmp/hippo-qscope-lookup-red.log`), passes on a `4795c0e` copy
(`/tmp/hippo-qscope-lookup-prefix.log`) and passes with the guard (`/tmp/hippo-qscope-green2.log`: 10
passed). The guard is in the consumers commit. The N=8 after run was taken one guard earlier, on the
unbounded path, which no query phase takes, so its projection and dense-dispatch numbers stand.

**Test double, granted by the orchestrator.** `EvidenceStore._knowledge_rows` in
`tests/unit/test_evidence_access.py` took `(kind)` only; it now accepts `generation_id=`, `where=`
and `ids=` and filters in Python as the Fake store does. No assertion changed. Before the grant, 34
tests in the five modules that import it failed with `TypeError` and nothing else
(`/tmp/hippo-qscope-double-breakage.log`, `-2.log`); after it, those modules and
`test_derived_evidence_access.py` pass: 114 passed (`/tmp/hippo-qscope-double-green.log`); with the guard, 114 passed
(`/tmp/hippo-qscope-double-green-2.log`).

## The bound

New `tests/unit/test_query_scoped_reads.py`:

| Test | Asserts |
| --- | --- |
| `test_records_read_by_id_are_the_unscoped_records_with_those_ids` | `ids=` equals the unscoped rows for those IDs, in the asked order, duplicates and unknown IDs collapsed |
| `test_records_read_by_id_after_a_delete_in_the_open_transaction_are_the_asked_rows` | the LadybugDB `IN` defect's exact state: a delete and a write in the open transaction, then an `ids=` read |
| `test_an_id_read_is_not_combined_with_another_scope` | the refusal |
| `test_retention_gaps_answer_as_the_whole_membership_walk_did` | the reviewed body, verbatim, as the oracle; no whole generation-sized read |
| `test_a_code_query_reads_no_generation_sized_table_whole` | the query life over a published code generation with its retired G1 present: `knowledge_whole_table(GENERATION_SIZED) == []` on every thread |
| `test_a_prose_query_reads_no_generation_sized_table_whole` | the same over a published prose generation with its retired `last-good` present |
| `test_a_proof_reads_membership_a_constant_number_of_times_whatever_its_views` | member reads per proof: 10 for 4 views and 34 for 16 before, equal after; the rebuilt proof equals the first |
| `test_a_projection_reads_membership_a_constant_number_of_times_whatever_its_passages` | the same for `project_managed_graph`, and no whole generation-sized read |
| `test_a_whole_inventory_proof_reads_no_kind_it_has_nothing_to_look_up_in` | a proof with no generation selection, over a store with no group membership, observation or support, reads neither `KnowledgeObject` nor `Assertion` (added for the regression under "Results unchanged") |
| `test_collecting_a_retired_generation_reads_no_generation_sized_table_whole` | collection |

**The second published generation.** The brief asks that a second, unrelated published generation be
present. In each world that generation is the selected source's own predecessor, retired by the
refresh: code G1, prose `last-good`. It is published, not selected, and has rows in every
generation-sized kind, so any whole read would return them and the recorder would count it. It is
not a different source, though. A published generation from a second source would not work: a
structural session selects every active source's generation, so it would be selected too.
`test_structural_loading.published()` tags its generation with profile `"p"`, and `dense_session`
refuses `mixed_modes` when verified and tag-compatible generations are selected together
(`knowledge/dense_session.py:129`), so the dense leg would never run. If the stricter reading is
wanted, a published generation whose source is tombstoned (`tombstone` in
`test_managed_source_inventory.py`) keeps its rows and changes neither the selection nor the dense
route.

The query life's renewal is forced twice: the held session's heartbeat interval is set to 0.01 s and
the test waits for a renewal on the `hippo-lease-renewal` thread, then calls `session.validate()`.
The recorder counts every thread. RED: 9 failed for the expected reasons
(`/tmp/hippo-qscope-red.log`). GREEN Fake: 9 passed (`/tmp/hippo-qscope-green1.log`); with the guard's test added, 10 passed
(`/tmp/hippo-qscope-green2.log`). After the
fix the caller-attributed run finds no whole-table generation-sized read in either world
(`/tmp/hippo-qscope-sites-after.json`: `{"code": {}, "prose": {}}`).

**CC11's recorder without its thread filter.** A scratch copy of `test_code_capture_acceptance.py`
(never committed) replaces the thread-local `w.building` test with a process-wide flag, so a held
query's heartbeat reads during a build count as build reads, and quickens every heartbeat to 0.2 s
so the refresh build really runs under renewals. Fake, `HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE=2`:

| Tree | Result | Heartbeat renewals | Log |
| --- | --- | --- | --- |
| `4795c0e` (before) | `1 failed`: `assert_cd1_bound`, "whole-table generation-sized knowledge reads during a managed build", 54 of them (`IndexManifest`, `GenerationEvidenceMember`, `GenerationMember`, `EvidenceSpan`, `ObjectObservation`, ...) | 12 | `/tmp/hippo-qscope-nofilter-before-fake-2.log` |
| `wp/qscope` (after) | `1 passed` | 11 | `/tmp/hippo-qscope-nofilter-after-fake-2.log` |

The scratch copy is written by `/tmp/hippo-qscope-make-nofilter.py <acceptance test> <scratch
path>`, which asserts each of its four textual swaps applies exactly once. The unmodified acceptance
test at N=2 on Fake: 2 passed (`/tmp/hippo-qscope-cc11-fake-2.log`); with the guard, 2 passed
(`/tmp/hippo-qscope-cc11-fake-2b.log`).

## LadybugDB phase timings

CC11's scenario, unmodified, on LadybugDB with bare `-W error`,
`HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE=8` and `HIPPO_CODE_ACCEPTANCE_TIMINGS=<json>`. Before: a
copy of `4795c0e` (`/tmp/hippo-qscope-base2`, its own venv). After: this worktree at `a68ff39`, the consumers commit before the guard was added to it (`a816767`). The
numbers are wall-clock seconds from CC11's recorder. They make no claim about production time.

**Conditions.** The machine has 18 cores and 128 GB, with a load average of 8 to 10 from other fleet
work, and the recorder captures wall clock only, so the absolute seconds are inflated. The runs
started at 15:08:09 (before) and 15:08:12 (after), and the contention did not fall evenly
(`.json.progress` timestamps):

* Both runs' builds, reopens and seal phases ran side by side, with the probe below also running.
* The after run's projection (15:17:07 to 15:18:17) and its dense dispatch (15:18:17 to 15:22:21)
  both ran during the before run's projection (15:16:57 to 15:22:31). The probe's dense dispatch ran
  alongside until 15:20:08.
* The before run's dense dispatch (15:22:31 to 15:44:21) overlapped the after run's refresh and
  final reopen until about 15:30. For its last 14 minutes no other LadybugDB run was going. Its
  refresh and final reopen also ran with no other LadybugDB run.

The two phases the brief names therefore ran under more contention in the after run. The before
figures, the dense dispatch's especially, understate the difference if anything. The refresh build's
313.3 s against 347.6 s is the same effect: the after run's refresh ran during the before run's
dense dispatch, and the before run's ran with no other LadybugDB run.

Both runs: 50 accepted files, 173 symbols, 179 passages, a 4 GiB buffer pool (the scenario's
explicit setting).

| Phase or build | Before (`4795c0e`), s | After (`a68ff39`), s |
| --- | --- | --- |
| bootstrap build (staging) | 159.3 | 159.9 |
| reopen during staging | 2.6 | 2.7 |
| bootstrap build (published) | 336.6 | 342.6 |
| reopen after publication | 6.7 | 6.9 |
| seal validation and checksums | 22.5 | 22.5 |
| **projection, arrows and source row** | **333.9** | **69.6** (4.8x less) |
| **verified dense dispatch** | **1,309.7** | **244.0** (5.4x less) |
| refresh build | 313.3 | 347.6 |
| reopen after refresh | 17.9 | 13.9 |
| pytest wall clock | 2,941.27 (2 passed) | 1,322.46 (2 passed) |

Logs and JSON: `/tmp/hippo-qscope-cc11-ladybug-8-before.log`, `.json`, `.json.progress`;
`/tmp/hippo-qscope-cc11-ladybug-8-after.log`, `.json`, `.json.progress`. The recorder counts reads
made on a building thread and keeps the 25 most frequent kinds (`most_common(25)`). Among those 25, the
whole-table reads in both runs are the authorization tables (`Suppression`, `WorkspaceMembership`,
`Workspace`, `AccessPolicy`, `GroupMembership`). The after run also has 6,602 whole `KnowledgeObject`
reads, the regression the guard under "Results unchanged" removes. None is a `GENERATION_SIZED` kind.
CC11's own `assert_cd1_bound`, which checks every recorded read, passed in both runs.

**A second before datum.** The scratch probe of finding 1 ran on a copy of `c4ba26e` at N=8 on
LadybugDB with a 1 GiB pool, starting at 14:44:51, before either CC11 run began
(`/tmp/hippo-qscope-phases-before-ladybug-8.json.progress`): build 235.5 s, a structural
`query_session` opened and closed 195.29 s, one `session.validate()` on a held session 19.12 s, the
dense dispatch (`retrieval_session` then `dense_session`) 1,474.6 s, 1 passed
(`/tmp/hippo-qscope-before-ladybug-8.log`). From 15:08, about 13 minutes into the dense dispatch, both CC11
runs were also running on the machine. The same phases made 110,331, 8,875 and 602,515 knowledge reads, of which 260, 27
and 1,681 were whole-table generation-sized, over 175 code nodes, 179 passages, 517 arrows and 179
dense vectors (`/tmp/hippo-qscope-phases-before-ladybug-8.json`). `c4ba26e..4795c0e`
changes no LadybugDB read path: it changes `src/hippo/status.py` (a docstring) and the Fake branch of
`store/knowledge.py` (the lock).

## Neo4j query shapes for the root parity run

Neo4j is root-owned and was not run here. New shape, for every kind a proof or projection fetches
by ID (`Artifact`, `ArtifactRevision`, `EvidenceSpan`, `ObjectObservation`, `KnowledgeObject`,
`NativeBinding`, `AssertionVersion`, `AssertionSupport`, `Assertion`, `DerivedRecord`,
`DerivedDependency`, `RetrievalView`, `ProseExtraction`, `Generation`):

```cypher
UNWIND $ids AS wanted_id MATCH (n:EvidenceSpan {id: wanted_id}) RETURN n.<field> AS <field>, ...
```

Existing shapes with new callers: `MATCH (n:<Kind>) WHERE n.generation_id = $generation_id` on
`IndexManifest`, `IndexEvent`, `GenerationMember`, `GenerationEvidenceMember` and `NativeBinding`;
`MATCH (n:EvidenceSpan) WHERE n.revision_id = $revision_id` and the same on `ObjectObservation`
(the compatibility lane only). Worth targeting: the managed and structural session suites, the
temporal suites (history proofs are unchanged in shape), and `test_query_scoped_reads.py`.

## Findings outside this slice

1. **Per-view lineage reads now dominate a query, and they are keyed, not whole.** A scratch probe
   (never committed) builds CC11's repository fixture at `files_per_language=2` through the coordinator,
   then times and counts three phases: a structural `query_session` opened and closed, one
   `session.validate()` on a held session, and an owned `retrieval_session` then `dense_session`.
   Fake, the same tree before (`4795c0e` copy) and after (`/tmp/hippo-qscope-phases-before-fake-2.json`,
   `-after-fake-2.json`), with identical result sizes (49 code nodes, 53 passages, 134 arrows, 88
   original citations, 53 dense vectors):

   | Phase | Knowledge reads before | Whole-table generation-sized before | Knowledge reads after | Whole-table generation-sized after |
   | --- | --- | --- | --- | --- |
   | projection | 31,449 | 260 | 26,787 | 0 |
   | one renewal | 2,539 | 27 | 2,062 | 0 |
   | dense dispatch | 154,410 | 1,492 | 127,914 | 0 |

   After the fix the dense dispatch's largest counts are all keyed reads: `EvidenceSpan` by key
   42,076, `DerivedDependency` by `derived_record_id` 25,132, `ArtifactRevision` by key 18,116,
   `Artifact` by key 15,860, `DerivedRecord` by key 9,904, `RetrievalView` by key 9,434. They come
   from `derivations._Inventory` (`record`, `span`, `derivation`): several keyed reads per rendered
   view, for every view every proof validates. `derivations.py` is outside this slice's files.
   Fetching an inventory's records in one `ids=` read per kind would make them a handful of queries
   per proof; on LadybugDB each keyed read is one query (`evidence-cc11.md` finding 22).
2. **Proof builds per query.** The test's query life built 198 proofs. A `validate()` rebuilds the
   workspace proof and the snapshot bundle's proof, and a guarded model call validates before and
   after. Rebuilding from storage is the authorization contract (`validate_current`), so caching a
   proof across calls is an authorization decision, not a read-scoping one.
3. **Native lookups per binding in `build`.** `EvidenceAccess.build` still calls
   `store._knowledge_get(binding.native_kind, binding.native_id)` once per bound native row per
   proof, one query each on the Cypher backends; `_native_rows(kind, ids=...)` could batch them.
4. **`validate_prose` builds its own inventory per extraction** in `_authorized_derivations` and
   `_project_prose`. Its reads are generation-scoped already; hoisting it needs a seam on
   `derivations.validate_prose` (`evidence-kscope.md` finding 5).
5. **`store/snapshots._collect_generation` walks the four native kinds whole** and filters by
   generation in Python (collection only; `_native_rows(kind, generation_id=...)` exists).
6. **`context._graph_for` reads `Artifact` and `Generation` whole on every `graph_for`** to choose the
   loader. `Artifact` grows with files; narrowing it needs an `Artifact.source_id` key, which is a
   journaled index.
7. **`store/snapshots.recover_generation_builds` reads `MaintenanceJob` whole once per `Generation`**;
   CC2's v6 `input_fingerprint` key would answer it.
8. **`projection._selected_pairs`** is still O(selected generations x authorized revisions) in CPU;
   the activation plan gives its `by_generation` shape to Task 16.
9. **Test harness.** `test_query_scoped_reads.knowledge_reads` deletes its instance attribute on
   exit rather than restoring the bound method, the gotcha in `evidence-cc11.md` finding 20.
10. **Every session open re-verifies each strict generation's seal.** `acquire_snapshot_reference` ->
    `_check_snapshot_inputs` -> `validate_generation_seal` -> `_verify_manifest`
    (`store/generations.py:1099`) recomputes `generation_checksums(gen.id)` for every selected
    generation on every `query_session` open. For scale, CC11's scenario times a checksum pass as
    its own "seal validation and checksums" phase: 22.5 s at N=8 on LadybugDB in both runs below. Its
    reads are generation-scoped, but inside it
    `AssertionSupport` is still read whole once per `AssertionVersion` member
    (`store/generations.py:1025`, and `:1159`, `:1236` on the publication path), which is
    `evidence-kscope.md` finding 4. `AssertionSupport` is not in `GENERATION_SIZED`, so the counter
    test cannot see it: a prose generation with many assertions pays one whole read per assertion per
    session open. Scoping it needs a journaled index on `AssertionSupport.assertion_version_id`.
11. **`build_authority._Overlay._knowledge_rows(self, kind)`** (`knowledge/build_authority.py:160`)
    accepts only a kind. That is safe today: the build authority proves by `revision_ids`, an
    unbounded proof, so `_ProofReads` only ever calls it with a kind. A generation-bounded proof
    through the overlay would raise `TypeError`; the overlay needs the scoped signature first.

## Commands

Every run sets `HIPPO_TEST_STORE` and `-o addopts=''`, writes to the log named and appends `EXIT $?`.
The warning rule: bare `-W error` for `test_query_scoped_reads.py`, the test double's modules and
CC11's scenario; form (b) for the reviewed set, both broad sweeps and the LadybugDB `-k` run, whose
modules import `fastapi.testclient` at module level.

```bash
# Baseline (2577add) and the reviewed set after the fix (the second adds test_query_scoped_reads.py)
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_structural_loading.py tests/unit/test_derived_projection.py tests/unit/test_code_projection.py tests/unit/test_temporal_conflicts.py tests/unit/test_temporal_evidence.py tests/unit/test_temporal_fixture_loader.py tests/unit/test_query_session.py tests/unit/test_dense_session.py tests/unit/test_snapshot_store.py tests/unit/test_query_snapshots.py tests/unit/test_status_access.py tests/unit/test_managed_source_inventory.py tests/unit/test_knowledge_scoped_reads.py tests/unit/test_generation_scoped_reads.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning" > /tmp/hippo-qscope-base.log 2>&1; echo EXIT $? >> /tmp/hippo-qscope-base.log
HIPPO_TEST_STORE=fake .venv/bin/pytest <the same fourteen> tests/unit/test_query_scoped_reads.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning" > /tmp/hippo-qscope-green-reviewed-2.log 2>&1; echo EXIT $? >> /tmp/hippo-qscope-green-reviewed-2.log

# RED, then GREEN (Fake)
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_query_scoped_reads.py -q -o addopts='' -W error > /tmp/hippo-qscope-red.log 2>&1; echo EXIT $?
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_query_scoped_reads.py -q -o addopts='' -W error > /tmp/hippo-qscope-green1.log 2>&1; echo EXIT $?

# The guard: RED on the unguarded tree; the same test in a copy of the module on the 4795c0e copy (copy removed after); GREEN
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_query_scoped_reads.py -k nothing_to_look_up -q -o addopts='' -W error > /tmp/hippo-qscope-lookup-red.log 2>&1; echo EXIT $? >> /tmp/hippo-qscope-lookup-red.log
(cd /tmp/hippo-qscope-base2 && HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_zz_qscope_lookup_scratch.py -k nothing_to_look_up -q -o addopts='' -W error > /tmp/hippo-qscope-lookup-prefix.log 2>&1; echo EXIT $? >> /tmp/hippo-qscope-lookup-prefix.log)
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_query_scoped_reads.py -q -o addopts='' -W error > /tmp/hippo-qscope-green2.log 2>&1; echo EXIT $? >> /tmp/hippo-qscope-green2.log

# Broad sweeps (Fake)
HIPPO_TEST_STORE=fake .venv/bin/pytest $(cat /tmp/hippo-qscope-broad-files.txt) -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning" -p no:randomly > /tmp/hippo-qscope-fake-broad-1.log 2>&1; echo EXIT $? >> /tmp/hippo-qscope-fake-broad-1.log
HIPPO_TEST_STORE=fake .venv/bin/pytest $(cat /tmp/hippo-qscope-broad-files-2.txt) -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning" > /tmp/hippo-qscope-fake-broad-2.log 2>&1; echo EXIT $? >> /tmp/hippo-qscope-fake-broad-2.log

# The test double (Fake)
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_evidence_access.py tests/unit/test_evidence_projection.py tests/unit/test_derived_projection.py tests/unit/test_generation_evidence_selection.py tests/unit/test_query_snapshot_service.py tests/unit/test_derived_evidence_access.py -q -o addopts='' -W error > /tmp/hippo-qscope-double-green.log 2>&1; echo EXIT $?

# LadybugDB: the new modules, then the brief's required selection
HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_query_scoped_reads.py tests/unit/test_generation_scoped_reads.py -q -o addopts='' -W error > /tmp/hippo-qscope-ladybug-new.log 2>&1; echo EXIT $? >> /tmp/hippo-qscope-ladybug-new.log
HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_query_session.py tests/unit/test_structural_loading.py tests/unit/test_code_projection.py tests/unit/test_temporal_conflicts.py -k "publish or select or reopen" -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning" > /tmp/hippo-qscope-ladybug-required.log 2>&1; echo EXIT $? >> /tmp/hippo-qscope-ladybug-required.log

# CC11's scenario: N=2 Fake, unmodified; N=8 LadybugDB with timings, before (4795c0e copy) and after (this worktree)
HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE=2 HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_code_capture_acceptance.py -q -o addopts='' -W error > /tmp/hippo-qscope-cc11-fake-2.log 2>&1; echo EXIT $?
HIPPO_CODE_ACCEPTANCE_TIMINGS=/tmp/hippo-qscope-cc11-ladybug-8-before.json HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE=8 HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_code_capture_acceptance.py -q -o addopts='' -W error > /tmp/hippo-qscope-cc11-ladybug-8-before.log 2>&1; echo EXIT $? >> /tmp/hippo-qscope-cc11-ladybug-8-before.log
HIPPO_CODE_ACCEPTANCE_TIMINGS=/tmp/hippo-qscope-cc11-ladybug-8-after.json HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE=8 HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_code_capture_acceptance.py -q -o addopts='' -W error > /tmp/hippo-qscope-cc11-ladybug-8-after.log 2>&1; echo EXIT $? >> /tmp/hippo-qscope-cc11-ladybug-8-after.log

# CC11's recorder without its thread filter (scratch copy written by /tmp/hippo-qscope-make-nofilter.py), Fake N=2
HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE=2 HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_zz_qscope_cc11_nofilter_scratch.py -q -o addopts='' -W error -k cd9_guarantee > /tmp/hippo-qscope-nofilter-after-fake-2.log 2>&1; echo EXIT $? >> /tmp/hippo-qscope-nofilter-after-fake-2.log

# Ruff, every changed file
.venv/bin/ruff check <the eight files> ai_docs/gates/rag-it-all/task-5-code-capture/evidence-qscope.md
.venv/bin/ruff format --check <the eight files> ai_docs/gates/rag-it-all/task-5-code-capture/evidence-qscope.md
```

After the guard, the same commands were rerun for the reviewed set, both broad sweeps, the test
double, CC11 at N=2 and both LadybugDB selections. Each writes to `/tmp/hippo-qscope-<name>.log`,
with names `green-reviewed-3`, `fake-broad-3`, `fake-broad-4`, `double-green-2`, `cc11-fake-2b`,
`ladybug-new-2` and `ladybug-required-2`.

Ruff: `All checks passed!` and `8 files already formatted` on `src/hippo/context.py`,
`src/hippo/knowledge/access.py`, `src/hippo/knowledge/projection.py`, `src/hippo/knowledge/temporal.py`,
`src/hippo/store/knowledge.py`, `src/hippo/store/snapshots.py`, `tests/unit/test_evidence_access.py`,
`tests/unit/test_query_scoped_reads.py`; the evidence file is checked after its last edit.

## Deviations from the brief

1. **`tests/unit/test_evidence_access.py`** (the `EvidenceStore` double), granted by the orchestrator
   as above.
2. **Two branch moves before the first commit**, both authorized: reset to `c4ba26e`, then a
   fast-forward merge of `rag-it-all-tibs` at `4795c0e`.
3. **Three commits, not two.** The readers and the consumers are the brief's two; this evidence is a
   third, because its LadybugDB timings finished after the consumers were committed.
4. **The consumers commit was amended** (`a68ff39` to `a816767`, unpushed) with the guard for a
   lookup of no IDs and its test, so the brief's two code commits stand.
5. **The second published generation is each world's retired predecessor**, not a different source's
   generation; the reason is under "The bound".
