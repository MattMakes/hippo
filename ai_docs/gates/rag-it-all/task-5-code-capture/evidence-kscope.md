# kscope evidence: knowledge-table reads scoped on the managed write path (gate CD1)

Branch `wp/kscope`, worktree `.worktrees/kscope`, base `492cb4c`. Brief
`ai_docs/handoffs/briefs/fix-knowledge-reads-scope.md`. This is the second half of CD1: CC2
(`evidence-cc2.md`) scoped the native reads; this slice scopes the knowledge reads a managed build
makes per record written.

Commits: `5194214` (readers: the per-kind allow-list, the v6 freeze and v7 index step, the Fake
single-key read, journal pins) and the commit carrying this file (consumers: the member tests and
sealed guard in `_check_knowledge_write`, the generation-scoped publish and seal reads, the
`GenerationViews` hoist, the Fake transaction snapshot, `test_knowledge_scoped_reads.py`).

## The defect

CC11 measured it on Fake with a scratch probe (`.worktrees/cc11/tests/unit/test_zz_cc11_scale_scratch.py`):
10 files 1.1 s, 40 files 8.4 s, 160 files 109.5 s wall clock, with roughly three unscoped reads per
evidence member. A caller-attributed diagnostic run in this worktree
(`/tmp/hippo-kscope-diag10.log`, `/tmp/hippo-kscope-diag40.log`) named every site. At 40 files:

| Unscoped reads | Kind | Site |
| --- | --- | --- |
| 4,341 + 214 + 153 + 2 | `GenerationEvidenceMember` | `generations.py:675` `_check_knowledge_write` sealed-interpretation guard, on every put |
| 2,040 | `GenerationMember` | `generations.py:641`, on every `GenerationEvidenceMember` put |
| 214 + 214 | `GenerationMember`, `GenerationEvidenceMember` | `generations.py:658/663`, on every `NativeBinding` put |
| 1,080 + 1,080 | `GenerationEvidenceMember`, `GenerationMember` | `derivations.py:115/120` `_Inventory.__init__`, one inventory per rendered passage via `_validate_managed_native -> validate_view` |
| 1,080 + 864 + 864 | `DerivedDependency` | `derivations.py:148` `_Inventory.derivation`, per passage and twice per derivation at seal |
| 1 each | `IndexManifest`, `IndexEvent`, `GenerationMember`, `GenerationEvidenceMember` | `bind_generation_embedding_profile`, `seal_generation`, `validate_generation_seal`, `publish_staged_generation`, `_publish_generation` |

## What each read is now

| Site | Before | After |
| --- | --- | --- |
| `_check_knowledge_write`, sealed guard (three refusals) | every member of every non-staging generation, on every write | `_sealed_member(kind, record_id)`: only where the answer can refuse (an update, a `DerivedDependency` put, an `AssertionSupport` put), only for a kind in `GenerationEvidenceMember.record_kind`, and by `where={"record_id": ...}` |
| `_check_knowledge_write`, `GenerationEvidenceMember` put | the generation's member revisions, from a whole-table read | `_revision_member(generation_id, revision_id)`: `GenerationMember`'s identity is exactly that pair, so one primary-key lookup per revision the target cites |
| `_check_knowledge_write`, `NativeBinding` put | whole `MaintenanceJob`, `GenerationMember`, `GenerationEvidenceMember` | `where={"input_fingerprint": gen.id}` (CC2's v6 key), `_revision_member`, and `_evidence_member(gen, "EvidenceSpan", span)` -- a primary-key lookup, the member's identity being `(generation_id, record_kind, record_id)` |
| `derivations._Inventory.__init__` | whole `GenerationEvidenceMember`, `GenerationMember` | `generation_id=` |
| `derivations._Inventory.derivation` | whole `DerivedDependency` | `where={"derived_record_id": identity}` |
| `_validate_managed_native` rendered passage | `validate_view` builds a fresh inventory per passage | `views=`: a `derivations.GenerationViews` the caller holds for the batch; its inventory is built at the first view, exactly where `validate_view` built one, and reused. `native_write` holds one per generation per call; `generation_checksums` one per pass; `_Inventory.passage` passes its own inventory |
| `bind_generation_embedding_profile`, `seal_generation`, `validate_generation_seal`, `_publish_generation` | whole `IndexManifest` filtered by generation | `generation_id=` |
| `apply_source_tombstone`, `fail_generation_build`, `publish_staged_generation`, `_publish_generation` | whole `IndexEvent` filtered by generation | `generation_id=` |
| `publish_staged_generation`, `_validate_publication_plan` | whole `GenerationMember` / `GenerationEvidenceMember` filtered by generation | `generation_id=` (`_selected_revisions` for the plan) |

`validate_view`'s signature is unchanged. The hoist is a sibling keyword, `views=`, beside the
existing `selected=` seam on `_validate_managed_native`, and `selected=` keeps its meaning.

Why `derived_record_id` and not the generation: a `DerivedDependency` has no `generation_id`, and a
dependency naming the record but outside the exact membership must still reach
`_Inventory.record` and refuse with "Derived input missing from exact generation membership".
Reading only the members' dependencies would route that case to "Rendered view fingerprint
differs" instead -- a different refusal. The key is therefore the record.

## Refusals and checksums

Every refusal message is byte-identical; no message was added to the write path. The reviewed
suites pass unchanged except for the journal pins below. Two reachability notes, both about states
no validated write can create:

* The old sealed guard called `_generation(m.generation_id)` for every member on every write, so a
  member pointing at a missing `Generation` would have refused every write with "Unknown
  generation". `put_knowledge` validates that reference, and collection removes members with their
  generation, so the state is unreachable; the new guard evaluates only the record's own members.
* `_Inventory.passage` now validates the support passage's view against its own inventory instead
  of a fresh one. The calls are sequential, not nested, so the shared `visiting` set sees no false
  cycle; the membership snapshot is the same one `validate_prose` already holds.

Checksums: `test_generation_checksums_are_unchanged_by_scoping`, `test_sealed_generations_still_verify_their_manifest`
and the seal and publish suites are green; no representation's bytes changed.

## Schema v7

Two keys needed an index Neo4j did not have. Following CC2's v6 precedent exactly:

* `KIND_SCOPED_FIELDS` gains `GenerationEvidenceMember.record_id` and
  `DerivedDependency.derived_record_id`. `SCOPED_FIELDS` is untouched: the pre-v6 generic index list
  keys off it, and growing it would grow v2's journaled step list.
* v6 is frozen. `V6_DESCRIPTOR = [6, *V5_DESCRIPTOR[1:]]` (v6 changed no column) and its checksum
  stays `4b639a6ba1b60516f2cf31d74bd1aeb0e59295d3aaf7e1fd7825e85d5d95137d`, pinned by
  `test_the_v6_descriptor_and_step_list_are_frozen`. `NATIVE_INDEXES` becomes the literal eight-step
  list v6 journaled: it used to be derived from the live allow-list, and adding a field would have
  grown it and refused every v6 store at `check_compatibility`.
* v7 (`CURRENT_SCHEMA_VERSION = 7`, `SUPPORTED_CHECKSUMS[7] = MIGRATION_CHECKSUM`) derives
  `V7_INDEXES` from the allow-list minus v6's, as v6 did while current.
* `validate_physical_schema` checks each version's own indexes, so an existing v6 Neo4j store
  validates against v6's eight before its v7 steps run. A missing v7 index refuses with "Evidence
  schema shape has an absent knowledge scope index"; v6's message is unchanged.
* Ladybug's v7 step list is empty (no secondary-index DDL, probed by CC2); its bound is the
  predicate. `_data_transform` reads and rewrites nothing for v7.

Journal fixtures updated under the orchestrator's grant (pins only): `test_policy_migration.py`
(current version, two history lists, the checksum map now splits `6: V6_CHECKSUM` from
`7: MIGRATION_CHECKSUM`, and both rewind fixtures drop 7 as well), `test_store_migrations.py`
(history set), `test_derived_generation_store.py` and `test_generation_store.py`
(`CURRENT_SCHEMA_VERSION == 7`). In the owned `test_generation_scoped_reads.py`: the history range,
the checksum key list, and the kind-scoped index containment now spans v6 and v7.

## Neo4j query shapes for the root parity run

Neo4j is root-owned and was not run here. New shapes (all through `_knowledge_rows`, which projects
every column):

```cypher
CREATE INDEX knowledge_deriveddependency_derived_record_id IF NOT EXISTS FOR (n:DerivedDependency) ON (n.derived_record_id)
CREATE INDEX knowledge_generationevidencemember_record_id IF NOT EXISTS FOR (n:GenerationEvidenceMember) ON (n.record_id)

MATCH (n:GenerationEvidenceMember) WHERE n.record_id = $record_id RETURN n.<field> AS <field>, ...
MATCH (n:DerivedDependency) WHERE n.derived_record_id = $derived_record_id RETURN n.<field> AS <field>, ...
```

Existing shapes with new callers: `MATCH (n:GenerationMember) WHERE n.id = $id` and
`MATCH (n:GenerationEvidenceMember) WHERE n.id = $id` (the member primary-key lookups, the same
shape `_knowledge_get` already issues); `WHERE n.generation_id = $generation_id` on
`GenerationEvidenceMember`, `GenerationMember`, `IndexManifest` and `IndexEvent`;
`MATCH (n:MaintenanceJob) WHERE n.input_fingerprint = $input_fingerprint`.

Worth targeting in parity: migrating an existing v6 store (the v6 physical check, then the two v7
steps and a `pending` journal row per step), and `SHOW INDEXES` reporting both v7 indexes as `RANGE`.

## The Fake double

Two changes to the test double, both measured before they were made:

* **Single-key scoped reads** (`knowledge.py`, Fake branch). A one-field `where=` compares the field
  directly instead of through `all()` per row. It is still a walk of the kind -- the Fake store has
  no secondary index -- so this is a constant factor only.
* **The transaction snapshot** (`tests/fakes/fake_store.py`, `FakeStore.transaction`, granted by the
  orchestrator). The outer-transaction snapshot deep-copied all of `vars(self)`, and the frozen
  `ingest/build_run.py:125` `_check` opens one outer transaction per check. `_knowledge_data` is now
  copied per kind with its records shared; everything else is still deep-copied.
  `test_the_fake_snapshot_shares_only_records_no_write_can_change` proves the premise: every
  registered record kind is `frozen`, assigning to a stored record raises, and a rolled-back put
  plus replace leaves exactly the prior dicts holding the identical prior records.

## Measurements

All on the Fake store, generated modules on top of the code fixture tree, `batch_size=128`.

**Same harness, before and after** (`fresh_builder`: one empty store per size, as CC11's probe had a
fresh `world` per size; process CPU, wall clock in brackets). "Before" is the pre-fix `src` snapshot
with the `HEAD` test tree, so the original `FakeStore` snapshot too
(`/tmp/hippo-kscope-measure-before.log`); "after" is this branch
(`/tmp/hippo-kscope-measure-after.log`).

| files | members | before CPU | before ms/member | after CPU | after ms/member |
| --- | --- | --- | --- | --- | --- |
| 10 | 600 | 1.62 s (1.91 s) | 2.69 | 0.97 s (1.30 s) | 1.62 |
| 40 | 2,040 | 12.34 s (13.23 s) | 6.05 | 3.47 s (4.19 s) | 1.70 |
| 160 | 7,800 | 158.05 s (164.10 s) | 20.26 | 23.86 s (26.39 s) | 3.06 |

Per member, the 160-file build cost 7.5x the 10-file build before and 1.9x after; `LINEAR_FACTOR`
bounds it at 3x. The 160-file build is 6.6x cheaper in CPU. CC11's own wall-clock numbers for the same
sizes were 1.1 s, 8.4 s and 109.5 s (7.7x per member); the "before" wall times here ran beside a
Ladybug suite, which is why CPU is the column compared.

Whole-table reads of a generation-sized kind, before: 1,809 / 999 / 858 `GenerationEvidenceMember` /
`GenerationMember` / `DerivedDependency` at 10 files, 6,009 / 3,339 / 2,808 at 40, and 22,809 /
12,699 / 10,608 at 160 -- CC11's 160-file counts exactly, which is what shows this harness reproduces
its probe -- plus 5 `IndexManifest` and 1 `IndexEvent` per build. After: none at any size.

**The steps in between**, from the RED and round-one runs of the timed test, which built all three
sizes into one accumulating store (so a later build also carried the earlier generations):

| state | 10 files | 40 files | 160 files | 160 vs 10 per member |
| --- | --- | --- | --- | --- |
| pre-fix (`/tmp/hippo-kscope-red-linear.log`) | 1.61 s, 2.68 ms | 20.17 s, 9.9 ms | 320.42 s, 41.1 ms | 15.3x |
| reads scoped, old Fake snapshot (`/tmp/hippo-kscope-green1.log`) | 1.17 s, 1.95 ms | 10.52 s, 5.2 ms | 136.06 s, 17.4 ms | 9.0x |

Whole-table reads across those three pre-fix builds: `GenerationEvidenceMember` 30,627,
`GenerationMember` 17,037, `DerivedDependency` 14,274, `IndexManifest` 15, `IndexEvent` 3. After
the read fix: none.

Round one still failed the bound with zero whole-table reads, so it was profiled rather than
guessed at (`/tmp/hippo-kscope-profile10.log`, `profile40.log`, `profile160.log`, one fresh
`world` each). The remaining superlinear cost was the test double, not the store:

| files | `FakeStore.transaction` deep copies | deep-copy CPU | of which pydantic `__deepcopy__` | profile total |
| --- | --- | --- | --- | --- |
| 10 | 224 | 1.0 s | -- | 3.7 s |
| 40 | 544 | 6.6 s | 4.9 s | 16.8 s |
| 160 | 1,844 | 83.1 s | 63.5 s | 158.0 s |

The Fake `where=` scan accounted for 63.7M predicate evaluations at 160 files, and the frozen
`knowledge.access.build` for 13.4 s. Sharing the frozen records in the snapshot and the single-key
fast path produced the "after" column above.

**Query counts, unit level** (`test_knowledge_scoped_reads.py`, RED in `/tmp/hippo-kscope-red.log`):

| scenario | before | after |
| --- | --- | --- |
| `native_fixture` (evidence, passage, observation, symbol, binding, edge) | 14 whole-table reads of generation-sized kinds | 0 |
| a 10-file `build_code_source` | 3,672 | 0 |
| member-table reads per `add_passages` call, 4 vs 16 rendered passages | 9 vs 33 | constant |
| seal and publish of a rendered generation | whole `GenerationEvidenceMember`, `GenerationMember`, `DerivedDependency`, `IndexManifest`, `IndexEvent` | 0 |
| a `KnowledgeObject` put during a build | 1 whole `GenerationEvidenceMember` read | no member read at all |
| the sealed guards (derivation, proof, published row) | whole `GenerationEvidenceMember` | `where={"record_id": ...}` |

## Findings outside this slice

1. **Authorization reads on every build check (frozen files).** `knowledge/build_authority.py:155/161/227`,
   through `knowledge/access.py:261/279/305/319`, read `AccessPolicy`, `WorkspaceMembership`,
   `GroupMembership`, `Workspace` and `Suppression` whole on every `BuildRun` check. At 10 files
   (`/tmp/hippo-kscope-diag10.log`): 880 reads of each of the last four through `access.build`, 440 of
   `WorkspaceMembership`, `Suppression` and `Workspace` through `require_source`, and four `AccessPolicy`
   sites at 214 each. At 160 files (`/tmp/hippo-kscope-profile160.log`) `access.build` ran 7,140 times
   for 13.4 s of a 158 s profile. These tables grow with principals and policies, not with evidence,
   which is why `GENERATION_SIZED` excludes them, but the call count grows with the batches; a
   per-build cache would remove most of it. Owner: `build_authority` / `knowledge.access`.
2. **Once-per-build unscoped reads in frozen files:** `ingest/code_generation.py:621` (`MaintenanceJob`,
   from `_prior_receipt` and `_install`) and `store/snapshots.py:353` (`Generation`, from
   `recover_generation_builds`).
3. **One outer transaction per build check.** `ingest/build_run.py:125` `_check` opens a store
   transaction per check: 214 at 10 files, 523 at 40, 1,778 at 160. Harmless on Neo4j and Ladybug; on
   the Fake double it was a whole-store deep copy each time, addressed above.
4. **Unscoped reads left in `generations.py`,** none generation-sized on a code build:
   `Suppression` once per `publish_staged_generation`; `native_write`'s `MaintenanceJob` read for an
   untagged row of a managed source (legacy lane); `native_mutation`'s `IndexManifest` read when a
   mutation touches an `Entity` or `Fact` (grows with sealed generations; prose lane); and
   `AssertionSupport` filtered by `assertion_version_id` in `generation_checksums`, `_plan_lineage`
   and `_validate_publication_plan`, once per `AssertionVersion` member. No code build writes
   assertions, but a generation with many would seal quadratically, and scoping it is another
   journaled index (`AssertionSupport.assertion_version_id` is not indexed).
5. **Prose seal.** `generation_checksums` calls `validate_prose` once per `ProseExtraction` member and
   each builds its own `_Inventory` -- generation-scoped now, still O(generation) per extraction.
   Hoisting it needs a `GenerationViews`-style seam on `validate_prose`, whose signature this slice
   left alone. The same pass also builds two inventories from one snapshot
   (`validate_generation_derivations` and the dense loop's `GenerationViews`).
6. **Binding dependencies.** `_Inventory.derivation`'s binding branch walks every exact
   `ObjectObservation` per binding dependency. Code dependencies are span-only
   (`knowledge/code_binding.py:563`), so a code build never enters it.
7. **Query time.** `knowledge/projection.py:178` and `knowledge/access.py:200` call `validate_view`
   per view, one inventory each: correct and now generation-scoped, but O(generation) per view.
8. **For CD9.** Ladybug has no secondary-index DDL, so both v7 keys are predicate scans inside the
   engine there. Linearity is proven here on the Fake store; the Ladybug ceiling should be measured on
   the acceptance fixture, not inferred from these numbers.
9. CC11's scratch probe is no longer in `.worktrees/cc11` (committed as `ae24a54`, `880aeff`). The
   harness here reproduces its shape: the same generated module per file on top of the fixture tree,
   `batch_size=128`, one build per size.

## Commands

Baseline before any change (Fake, `-W error`): CD1 CHECK 93 passed, CD7 CHECK 83 passed,
`test_prose_generation.py test_code_generation.py` 99 passed and 1 skipped
(`/tmp/hippo-kscope-base-CD1.log`, `-CD7.log`, `-EXTRA.log`).

```
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_generation_scoped_reads.py \
  tests/unit/test_generation_store.py tests/unit/test_generation_counts.py \
  tests/unit/test_staged_prose_writer.py -q -o addopts='' -W error
```

CD1 CHECK: **93 passed** (`/tmp/hippo-kscope-cd1.log`).

```
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_staged_code_writer.py \
  tests/unit/test_generation_resume.py tests/unit/test_generation_failure.py -q -o addopts='' -W error
```

CD7 CHECK: **83 passed** (`/tmp/hippo-kscope-cd7.log`).

Full Fake unit suite, because the `FakeStore.transaction` change reaches every Fake test:
**4,435 passed, 29 skipped, 0 failed** (`/tmp/hippo-kscope-fake-full.log`). It includes
`test_knowledge_scoped_reads.py` (the timed test among them), `test_prose_generation.py`,
`test_code_generation.py` and the four journal-fixture suites.

Ladybug, `-W error`:

* `test_generation_scoped_reads.py test_staged_code_writer.py test_staged_prose_writer.py
  test_knowledge_scoped_reads.py`: **109 passed, 4 skipped** (`/tmp/hippo-kscope-ladybug.log`). The
  skips are the Fake-only fixtures (the symbol ceiling, the two timed tests, the snapshot premise).
* `test_code_generation.py -k "publish or refresh or resume"`: **7 passed, 26 deselected**
  (`/tmp/hippo-kscope-ladybug-codegen.log`).
* `test_store_migrations.py test_policy_migration.py test_derived_generation_store.py
  test_generation_store.py`, because v7's step list is backend-specific: **119 passed**
  (`/tmp/hippo-kscope-ladybug-mig.log`).

Neo4j: not run (root-owned); the shapes to target are listed above.

**Warning filter (fleet rule).** Every targeted command passes under a bare `-W error`. Only the
whole-suite sweep used form (b), the command-line filter
`-W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`, because
it collects modules that import `fastapi.testclient` at module level. No marker or ini filter was
added.

Ruff: `check` and `format --check` clean on every changed file, including this document.

## Deviations from the brief

1. **Four test files outside the FILES list** carry journal pins only, granted by the orchestrator:
   `test_policy_migration.py`, `test_store_migrations.py`, `test_derived_generation_store.py`,
   `test_generation_store.py`.
2. **`FakeStore.transaction`'s snapshot** changed beyond "query methods and counters", granted by the
   orchestrator with the guard test described above.
3. **The counter is asserted over `GENERATION_SIZED`, not every kind**, as the orchestrator ruled:
   `knowledge_whole_table()` with no filter is not empty across a build because the frozen
   `build_authority` / `knowledge.access`, `code_generation` and `snapshots` read authorization and
   control tables whole (findings 1 and 2).
4. **`base.py`, `memory.py` and `ladybug.py` are unchanged.** v6's knowledge indexes were never in
   `base.CONSTRAINTS` either -- `migrate_store` applies every version's steps to a new store -- and
   the Neo4j and Ladybug `_knowledge_rows` path is the shared equality query, which needed no change.
