# r21w evidence: the CD10 review's writer blockers (R21-B1, B2, B3, B5)

Worker `backend-developer-30`, 2026-09-13. Branch `wp/r21w`, worktree `.worktrees/r21w`, base
`e026640`, with `rag-it-all-tibs` at `a01f9c3` (r21i and r21c merged) merged in once as `3e92dba`
before the final green run, as the orchestrator authorized. Brief
`ai_docs/handoffs/briefs/fix-r21-writer.md`; findings from
`ai_docs/reports/2026-09-13-code-capture-review.md`; rulings 10, 12 and 13 of
`ai_docs/handoffs/briefs/code-capture-notes.md`. No gate checkbox is set here.

## Commits

| Hash | Subject |
| --- | --- |
| `3e92dba` | Merge rag-it-all-tibs into wp/r21w for r21i and r21c before the final green run |
| `d36da2f` | Seal every binding of a native row, resume every CODE_EDGE kind and relation payload, and rebind a sealed profile idempotently (writer and store: `staged_code.py`, `generations.py`, the writer and scoped-read tests, and the fixture's shape constants they import) |
| the commit adding this file | Prove the writer blockers through the coordinator and carry their shapes in the CD9 fixture (`test_code_generation.py`, the fixture's repository files, `test_code_capture_acceptance.py`, this evidence) |

## Files

| File | Change |
| --- | --- |
| `src/hippo/knowledge/staged_code.py` | B1: every binding of a native row in its group and probed. B3: relations keyed `(rel, a, b, code-edge kind or None)` in `relations`, `_groups`, `_persisted` and `_inventory`; each relation probe carries its row; payloads compared in the probe and at the seal |
| `src/hippo/store/generations.py` | B5: `_edges_touching` drops the `(a, b)` seen set. B2: `bind_generation_embedding_profile` returns for a verified generation before the manifest refusal. m6: the Fake branch reads under `_lock` |
| `src/hippo/ingest/code_generation.py` | **not touched**: the B2 fix is entirely in the store function `_install` calls |
| `tests/fakes/fake_store.py` | **not touched**: the Fake already keeps one `CODE_EDGE` per `(a, b, kind)` |
| `tests/fakes/code_capture_repo.py` | additions only: the five shape texts and four files carrying them (item 4) |
| `tests/unit/test_staged_code_writer.py` | 6 test functions (10 cases) added; `test_the_sealed_generation_holds_every_native_row_binding_and_relation` compares through `_relation_key` |
| `tests/unit/test_code_generation.py` | 4 test functions (7 cases) added |
| `tests/unit/test_generation_scoped_reads.py` | B5 oracle case and m10 predicate test added; m3 tripwire regex |
| `tests/unit/test_code_capture_acceptance.py` | `assert_native_defined_in_support` (granted) and one documented count (see "Acceptance file") |
| NEW `ai_docs/gates/rag-it-all/task-5-code-capture/evidence-r21w.md` | this file |

## Per finding

### R21-B1: one `NativeBinding` per native row refused ordinary trees

`_groups` built `bindings` as a dict keyed by `(native_kind, native_id)`, so it kept the last
binding of a row and wrote only that one. The bundle carries one binding per observing
`(object, span)`, and `_inventory` compares the whole set, so the seal refused. The fix groups
every binding of a row with the row, probes each one, and leaves `_inventory` unchanged, because it
already compared the full set.

| Shape (coordinator, Fake) | Before | After |
| --- | --- | --- |
| `big_function` (400 padded lines) | `Exact NativeBinding inventory differs from prepared coverage` | published; 24 bindings over 13 native rows sealed |
| `cs_overloads` | same refusal | published; 18 bindings over 15 native rows sealed |
| `sql_rw` (table in `db/schema.sql`, read and written from `app/touch.py`) | same refusal | published; 17 bindings over 16 native rows sealed |

Each shape binds exactly one native row more than once. The counts come from a throwaway counting
module run on Fake (`/tmp/hippo-r21w-counts-fake.log`; the module was deleted and never staged).
The tests pin the relation (more bindings than bound native rows) and never a literal count, so
r21a's M12 change, which reduces the overload shape's bindings, moves the numbers above and none of
the assertions. `test_a_native_row_missing_one_of_its_bindings_fails_the_resume` stages a row with
every binding but its first. Before the fix the probe skipped that group, because it knew only the
last binding. Now the probe refuses: `incomplete; explicit failed-generation cleanup required`.

### R21-B3: the resume probe dropped a second `CODE_EDGE` kind and never compared relation payloads

| Case | Before | After |
| --- | --- | --- |
| `main_guard` crash between CONTAINS and INVOKES (coordinator, batch size 1) | published without `INVOKES` | published; `CODE_EDGE` prepared 8 = stored 8; `resumed_from_batches` 91 of 128 groups |
| `sql_rw_no_schema` crash between READS and WRITES | published without `WRITES` | published; prepared 8 = stored 8; `resumed_from_batches` 87 of 123 groups |
| the same two crashes at writer level | sealed without the second kind | sealed with both |
| staged `CODE_EDGE` with a higher omega, then reclaim and probe | skipped (DID NOT RAISE) | `A staged CODE_EDGE relation differs from this build; explicit failed-generation cleanup required` |
| staged `MODIFIES` with a higher omega and another hunk | skipped | `A staged MODIFIES relation differs from this build; ...` |
| an extra `CODE_EDGE` kind on a planned pair | not seen (same key) | `holds 1 relation rows this build would not produce; ...` |
| a drifted omega at the seal | sealed | `Native relationship inventory differs from prepared coverage` |

How the payload comparison works (ruling 10: canonical equality, never `native_write`'s tolerance):
`_written_relation` passes the prepared row through the store's own write shaping
(`code_edge_write_rows`, `modifies_write_rows`: float omega, `extra` and `hunk` as sorted JSON
text). `_stored_relation` then projects both sides onto `RELATION_PROPERTIES`: `kind`, `omega`,
`provenance` and `extra` for a `CODE_EDGE`, `omega` and `hunk` for `MODIFIES`, nothing for
`DEFINED_IN` and `PRECEDES`. The projection is needed because a Fake relation payload also carries
its endpoint fields and a Cypher `properties(r)` does not. The absence half is unchanged: every
persisted key outside the plan refuses. `staged_code` now imports the two write-shaping functions
from `hippo.store.code`. `knowledge/projection.py` and `knowledge/graph_loader.py` already import
from that module, and `test_layering.py` forbids only knowledge-to-ingest imports.

### R21-B5: the non-Fake `_edges_touching` de-duplicated on the endpoint pair

The seen set collapsed rows with the same `(a, b)` inside each `(rel, a_kind, b_kind)` pass, so
LadybugDB and Neo4j returned one `CODE_EDGE` per pair. The fix removes it. The right-hand
(`b`-driven) pass now skips exactly the rows whose `a` is in `ids`, which the left-hand pass already
returned. `test_two_code_edge_kinds_between_one_pair_are_both_enumerated` writes CONTAINS and
INVOKES between two symbols of one generation and asserts both kinds come back, that the scoped read
equals `reference_relationships` (plain `MATCH (a)-[r]->(b)`), and that the `generation_id` form
equals the `ids` form.

| Backend | Before | After |
| --- | --- | --- |
| Fake | 1 passed (`/tmp/hippo-r21w-red-b5-fake.log`) | green in every Fake run below |
| LadybugDB | `assert {'CONTAINS'} == {'CONTAINS', 'INVOKES'}`, 1 failed (`/tmp/hippo-r21w-red-b5-ladybug.log`) | 1 passed (`/tmp/hippo-r21w-green-b5-ladybug.log`) and in the final LadybugDB run |

### R21-B2: any failure after the seal stranded the source

`bind_generation_embedding_profile` now calls `validate_generation_profile(gen, pointer)` before the
`IndexManifest` refusal and returns for a `verified_v1` generation. Binding the identical profile
is therefore a no-op, sealed or not. A different pointer still refuses inside
`validate_generation_profile` ("Generation profile binding conflicts"). An unverified generation
holding a manifest still refuses ("A sealed profile cannot be rebound"). By reading, the two
existing profile refusals survive, both before the moved check:
`test_generation_profiles.py:177` (binding after publication) refuses at `_check_build`, and
`:378` (a different pointer) refuses in `validate_generation_profile`.

| Case | Before | After |
| --- | --- | --- |
| `_publish` faulted after `_seal`, then retried (`test_a_failure_after_the_seal_retries_to_publication_of_the_same_generation`) | the failed generation kept its one manifest; retry raised `ValueError: A sealed profile cannot be rebound` | same generation ID published, `outcome == "published"`, `resumed_from_batches` 126 = 138 groups - 1 preflight - 11 revision members, one manifest, `created_at` kept |
| R21-m31: authorization epoch bumped inside `publish_staged_generation` | first attempt refused `Authority changed during publication`; retry raised the same `A sealed profile cannot be rebound` (`/tmp/hippo-r21w-red-m31-fake.log`) | first attempt refuses and leaves no published event and no pointer; retry publishes the same ID |

**Deviation, named:** the brief asks for `status == "resumed"`. `BuildReceipt` has no `status`
field and no outcome `"resumed"` (`_publish` returns `"published"`; the reviewer's scratch module
printed `receipt.status`, which would raise `AttributeError`). `build_run.py` is outside this
slice, so nothing was added. The test asserts the same generation ID, `outcome == "published"` and
the exact skipped-group count.

**Prose lane:** affected in code, unreachable in behaviour, not edited. `prose_generation._install`
calls the same store function, but it admits with `claim_generation_build`, which collects a failed
generation's `IndexManifest` (`store/snapshots.py:299`) before returning it to staging, so a prose
retry never meets a manifest at the bind. `test_staged_prose_writer.py`, `test_prose_generation.py`
and `test_generation_profiles.py` are unchanged and green, and every pinned checksum in the profile
suite holds.

## Neo4j shapes for the parity run (root-owned)

`_edges_touching`: the Cypher text is identical before and after. Only the Python-side
de-duplication changed. For each `(rel, a_kind, b_kind)`, with `properties(r)` on Neo4j:

```text
left : UNWIND $ids AS wanted_id MATCH (a:Symbol {id: wanted_id})-[r:CODE_EDGE]->(b:Symbol) RETURN a.id AS a,b.id AS b,properties(r) AS r
right: UNWIND $ids AS wanted_id MATCH (b:Symbol {id: wanted_id})<-[r:CODE_EDGE]-(a:Symbol) RETURN a.id AS a,b.id AS b,properties(r) AS r
```

Before: rows whose `(a, b)` was already seen in either pass were dropped. After: a right-pass row
whose `a` is in `ids` is dropped, and nothing else is.

Profile bind, one transaction: `_check_build`, then `_generation`, then
`validate_generation_profile(gen, pointer)` (members by generation, revisions and artifacts by ID).
For a `verified_v1` generation it returns here: no `IndexManifest` read, no write, no
`content_epoch` bump. Otherwise it runs the generation-scoped `IndexManifest` read, refuses if a
manifest exists, or writes the binding as before. The relation payload comparison adds no query.

Suggested parity selection: `tests/unit/test_generation_scoped_reads.py`,
`tests/unit/test_generation_profiles.py`,
`tests/unit/test_staged_code_writer.py -k "several_spans or missing_one_of or two_kinds or payload_differs or extra_code_edge_kind or compares_every_relation or reopen"`,
`tests/unit/test_code_generation.py -k "after_the_seal or publication_window or two_kinds or several_spans"`.

## CD9 fixture (item 4)

`build_code_capture_repository` gains four committed files in its first commit, each named in the
docstring. `services/python/shapes/report.py` holds a function longer than 1500 characters.
`services/python/shapes/orders_cli.py` holds a function that selects and updates `orders`, plus a
module-level `main()` under the main guard. `csharp/Orders/Robot.cs` holds two overloads.
`db/schema.sql` defines `orders`, which `orders_cli.py` references from another directory. The
Python paths sort after every `services/python/pkg*` module, so `refresh()` (which takes
`languages["python"][1]`) and the edited-shard commit pick the files they always picked. Every
new file is in `languages`. The docstring now records the accepted-file count,
5N + 2 * max(2, N // 4) + 10: 274 at N = 48 (was 270), 54 at N = 8 (was 50), 24 at N = 2 (was 20).
The determinism test is green.

The ledger still says "270 accepted files at its default size" in CD9's CRITERIA and "50 accepted
files" in its notes. Both are the orchestrator's to update.

### Acceptance file

- `assert_native_defined_in_support`: **granted by the orchestrator** after the N = 2 run failed on
  the new `orders` table (`/tmp/hippo-r21w-green-acceptance-fake.log`). The oracle keyed bindings
  one per native row, the same single-binding assumption as B1, so it kept the reference-site span
  while DEFINED_IN pointed at the schema passage. It now collects every binding span of a row and
  asserts that the DEFINED_IN passage holds one of them. The CD9 wording is applied by the
  orchestrator in `a01f9c3`.
- The size comment r21c wrote, "8 per language (50 accepted files)", now reads 54 accepted files.
- No assertion count moved: `len(first.accepted) >= 250` at N = 48 still holds with 274.

## Minors

| ID | Outcome |
| --- | --- |
| R21-m3 | closed: the tripwire matches `(?i)\b(\w+\.\w+)\s+IN\s+\$` over `rglob("*.py")`; no new offender |
| R21-m6 | closed: the Fake branch of `_edges_touching` reads its tables under `_lock` (an RLock the writers hold for a whole transaction) |
| R21-m10 | closed: `test_only_an_all_principals_suppression_of_the_source_leaves_the_legacy_lane` (a principal-scoped suppression keeps the legacy lane; an all-principals one leaves it) |
| R21-m31 | closed: `test_an_authorization_change_in_the_publication_window_refuses_and_the_retry_publishes` |
| R21-m2 | left: the SUBJECT/OBJECT second hop needs a passage-to-Entity/Fact extraction fixture, and `Missing shared graph endpoint` cannot be produced through a Cypher store's relationship writers (an edge needs both nodes); not a one-liner |
| R21-m14 | left: asserting identical passages after rewriting the checkout needs a second source and checkout built from the same bytes to compare against; test-only but not a one-liner |
| R21-m1, m5, m19, m32, m33, m34, m38, m40, m41 | left, as the brief says. m38: the B2 fix sits in the store function both lanes call, so the prose near-copy needs no twin |

## Tests and runs

RED (before any fix, Fake unless named):

```text
/tmp/hippo-r21w-red-writer-fake.log       10 failed  (3 seal refusals, 5 DID NOT RAISE, 2 missing kinds)
/tmp/hippo-r21w-red-coordinator-fake.log  7 failed   (3 seal refusals, 2 missing kinds, t1 "cannot be rebound", m31 harness error)
/tmp/hippo-r21w-red-m31-fake.log          1 failed   ValueError: A sealed profile cannot be rebound (B2 reverted, rest applied)
/tmp/hippo-r21w-red-b5-fake.log           1 passed   (Fake control)
/tmp/hippo-r21w-red-b5-ladybug.log        1 failed   {'CONTAINS'} == {'CONTAINS', 'INVOKES'}
```

The first m31 RED failed on a harness error: restoring `publish_staged_generation` as a bound
method on the store instance made the Fake transaction snapshot deep-copy the store's `RLock`. The
test now patches the class. The RED in `/tmp/hippo-r21w-red-m31-fake.log` was re-run with only
the `generations.py` change reverted and fails for the finding's reason.

Baseline at `e026640` (Fake): CD7 83 passed, CD8 306 passed and 3 skipped, scoped reads + prose
writer + profiles 87 passed (`/tmp/hippo-r21w-baseline-{cd7,cd8,extra}.log`).

Final, on the merged tree, `-q -o addopts='' -W error`, no warning filter:

```text
Fake  CD1 line                                            120 passed                /tmp/hippo-r21w-final-cd1-fake.log
Fake  CD7 line                                            93 passed                 /tmp/hippo-r21w-final-cd7-fake.log
Fake  CD8 line                                            316 passed, 3 skipped     /tmp/hippo-r21w-final-cd8-fake.log
Fake  scoped reads + prose writer + profiles              89 passed                 /tmp/hippo-r21w-final-extra-fake.log
Fake  acceptance, HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE=2   2 passed             /tmp/hippo-r21w-final-acceptance-n2-fake.log
LadybugDB  test_generation_scoped_reads test_staged_code_writer test_code_generation
           -k "publish or resume or overload or two_kinds or big"   27 passed, 102 deselected in 919.29s   /tmp/hippo-r21w-ladybug-units.log
           max RSS 0.9 GiB, peak footprint 0.6 GiB
LadybugDB  acceptance, HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE=2   2 passed in 351.55s    /tmp/hippo-r21w-ladybug-acceptance-n2.log
           max RSS 1.9 GiB, peak footprint 1.0 GiB
LadybugDB  (pre-merge) the 10 new writer cases                    10 passed in 55.68s     /tmp/hippo-r21w-ladybug-writer-early.log
```

The item-5 selection holds 27 tests: the B5 oracle, the writer's `big_function`, `cs_overloads`,
two-kinds and resume cases, and the coordinator's publish, resume, two-kinds and retry-after-seal
cases. The writer's `sql_rw` seal case and `test_the_seal_compares_every_relation_payload` are
outside the selection; they ran on LadybugDB in the pre-merge run. The LadybugDB runs were one at a
time.

Counts against the baseline: CD7 gains the 10 writer cases. CD8 gains the 7 coordinator cases and
r21c's 3 pipeline tests from the merge. The extra set gains the B5 oracle and m10. CD1 is 118 in
the review, plus the same two.

Ruff: `ruff check` and `ruff format --check` on the seven touched Python files, all checks passed
and 7 files already formatted (`/tmp/hippo-r21w-ruff.log`); `ruff format --check` on this file,
already formatted.

## Notes for the next slice

- From r21i: `native_mutation` on entity or fact IDs checksums every ready generation, so a legacy
  `SYNONYM` between entities that a sealed generation's passages `MENTION` would be refused.
  Unreachable today: the code lane writes no `MENTIONS` and no `Entity` rows (OpenIE is skipped
  for code).
- One bug of my own was caught before commit, only by the real-LadybugDB reopen test inside the
  writer suite: the first B5 edit named the pass index `right`, which shadowed the spec's `right`
  label tuple.
- A monkeypatched bound method on a Fake store instance breaks the next transaction's snapshot
  (`cannot pickle '_thread.RLock'`). Patch the class, as `spies()` does.
- Not taken: r21a's proposed `test_code_generation.py` twin of R21-M4 (outside this brief).
