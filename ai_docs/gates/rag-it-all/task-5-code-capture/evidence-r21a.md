# R21a evidence: authority reads, discriminating tests and three ledger corrections

Slice `r21a` on `wp/r21a`, based on `rag-it-all-tibs` at `e026640` and merged with `rag-it-all-tibs` at
`f62c4d2` (r21w, r21i and r21c) in `66400d4` before the final runs, as the orchestrator authorized. Brief:
`ai_docs/handoffs/briefs/fix-r21-authority-tests.md`. Findings: R21-M1, M2, M3, M4, M5, M6 and M12 of
`ai_docs/reports/2026-09-13-code-capture-review.md`, and R21-m24, m26 and m35.

## Outcome by finding

| Finding | Outcome | Where |
| --- | --- | --- |
| R21-M2 | Fixed | `knowledge/access.py` (`_KEYED_KINDS`, `EvidenceAccess._groups`), `knowledge/build_authority.py` (`_Overlay._knowledge_rows` takes the scoped read contract) |
| R21-M1 | Authority half fixed and measured; CD1 wording corrected below | `BuildAuthority.check_local` proves the accepted inputs once per authority; the counter test counts rows returned per write batch at 10 and 40 files |
| R21-M4 | Fixed in `test_build_authority.py`; the `test_code_generation.py` twin is proposed to r21w below, verified in a scratch copy | mutation proof below |
| R21-M6 | Fixed, tests only | two tests in `test_code_projection.py`; `projection.py` unchanged; mutation proof below |
| R21-M12 | Fixed | `code_binding._held` (overlap rule), counts pinned in `test_code_binding.py`; `CODE_BINDING_RULE_VERSION` bumped to `code-binding-v2` on the orchestrator's ruling, with `code_history.EXPECTED_CODE_BINDING_RULE_VERSION` (one line, granted) |
| R21-M3 | CD9 wording and assertion shape proposed | "Ledger lines for the orchestrator" |
| R21-M5 | CD8 CHECK line proposed and run green | "Ledger lines for the orchestrator" |
| R21-m35 | `rebaseline` docstring fixed; plan and CD8 wording proposed | "Plan sentence for the orchestrator" |
| R21-m24 | Closed with tests | `test_a_bundle_whose_references_leave_the_bundle_refuses`, `test_a_native_id_outside_the_generation_namespace_refuses` |
| R21-m26 | Closed | `code_binding._reuse` compares the whole record except `observed_at` |
| R21-m4 | Left named; the query counters pin it by caller | `context.py:243`, below |
| R21-m5, m30, m38 | Left named, untouched | |
| Acceptance oracle after the merge | Fixed, granted | `test_code_capture_acceptance.py::assert_arrows_are_the_sealed_relations`, other finding 4 |

## Commits

- `27a3ddc` Look a proof's groups up by ID and prove a build's accepted inputs once per authority
- `9b4025d` Bind an overload only from the passages holding its lines and reuse a stored revision only whole
- `fdb740b` Bump the code binding rule version to code-binding-v2 for the overload binding change
- `66400d4` Merge rag-it-all-tibs into wp/r21a before the final green run
- `f0f4f39` Serve a DEFINED_IN arrow in the acceptance oracle only where the object's binding span is in the passage
- this evidence file is committed on its own after the final runs, in the commit that adds it

## Runs

Every run sets `HIPPO_TEST_STORE` and `-o addopts=''` and writes to the log named.

| Run | Result | Log |
| --- | --- | --- |
| Baseline at `e026640`, Fake: the brief's seven files | 234 passed | `/tmp/hippo-r21a-baseline.log` |
| RED M2, authority | 1 failed: `[{}, {}]`, two whole `KnowledgeObject` reads per check | `/tmp/hippo-r21a-red-m2-authority.log` |
| RED M1 and M2, counters | 4 failed (group-member build, rows per batch, reader proof setup, authority) | `/tmp/hippo-r21a-red-m1m2.log` |
| RED M2, reader proof | 1 failed: the one `KnowledgeObject` read was whole | `/tmp/hippo-r21a-red-m2-reader.log` |
| RED M1, authority (overlay contract, proven once) | 4 failed | `/tmp/hippo-r21a-red-m1-authority.log` |
| RED M4, mutation | new test failed, `e026640` test passed | `/tmp/hippo-r21a-red-m4.log` |
| RED M6, mutation | both new tests failed | `/tmp/hippo-r21a-red-m6.log` |
| RED M12, m24, m26 | 5 failed, 6 passed (the m24 cases and guards pass: they cover existing refusals) | `/tmp/hippo-r21a-red-m12.log` |
| RED rule-version bump | 1 failed: `'code-binding-v1' == 'code-binding-v2'`, 2 passed | `/tmp/hippo-r21a-red-bump.log` |
| GREEN Fake before commit `27a3ddc` | 188 passed | `/tmp/hippo-r21a-green-commit1.log` |
| GREEN Fake, `test_code_binding.py` | 64 passed | `/tmp/hippo-r21a-green-m12.log` |
| Regression, the 13 other suites that capture a build authority (form (b)) | 552 passed, 5 skipped | `/tmp/hippo-r21a-regression.log` |
| GREEN Fake, broad set (form (b)), before the merge | 927 passed, 1 skipped | `/tmp/hippo-r21a-green-fake.log` |
| Proposed CD8 CHECK, verbatim, before the merge | 380 passed, 3 skipped | `/tmp/hippo-r21a-cd8-proposed.log` |
| GREEN LadybugDB, the brief's four files, before the merge | 110 passed, 2 skipped in 662.87s | `/tmp/hippo-r21a-ladybug.log` |
| GREEN Fake, `test_code_binding.py` and `test_code_history.py` after the bump | 121 passed | `/tmp/hippo-r21a-green-bump.log` |
| M4 twin on the merged tree, unmutated and mutated | unmutated: the twin and r21w's current test pass; with `child.check_local()` deleted: the twin and `test_build_authority.py`'s test fail, r21w's current test passes | `/tmp/hippo-r21a-twin.log`, `/tmp/hippo-r21a-twin-mutation.log` |
| Overload tree built on the merged tree | published: 18 bindings over 17 bound native rows, 2 on the shared `Move` row | `/tmp/hippo-r21a-overload-publish.log` |
| M1 counter peaks on the merged tree | authority 42 / 42 rows; writer 35.43 / 36.46 rows per record; membership 642 / 2,142 rows | `/tmp/hippo-r21a-m1-merged.log` |
| Fake, broad set (form (b)), merged tree, first run | 1 failed (the acceptance oracle, other finding 4), 945 passed, 1 skipped | `/tmp/hippo-r21a-final-fake.log` |
| Acceptance scenario with the pre-M12 binder patched in, and with the exact `DEFINED_IN` oracle | both passed | `/tmp/hippo-r21a-acceptance-oracle.log`, `/tmp/hippo-r21a-exact-oracle.log` |
| GREEN Fake, `test_code_capture_acceptance.py`, after the oracle fix | 2 passed | `/tmp/hippo-r21a-green-acceptance.log` |
| GREEN Fake, broad set (form (b)), merged tree, after the oracle fix | 946 passed, 1 skipped | `/tmp/hippo-r21a-final-fake-2.log` |
| Proposed CD8 CHECK, verbatim, merged tree | 390 passed, 3 skipped | `/tmp/hippo-r21a-final-cd8.log` |
| CD1 and CD5 CHECK lines, verbatim, merged tree | CD1: 123 passed; CD5: 98 passed | `/tmp/hippo-r21a-final-cd1-cd5.log` |
| GREEN LadybugDB, the brief's four files, merged tree | 110 passed, 2 skipped in 645.38s | `/tmp/hippo-r21a-final-ladybug.log` |
| LadybugDB, `test_code_capture_acceptance.py` at 8 files per language, merged tree, after the oracle fix | running when this file was first committed; result in the follow-up commit | `/tmp/hippo-r21a-ladybug-acceptance.log` |
| M1 with and without the change | see R21-M1 | `/tmp/hippo-r21a-m1-without.log`, `/tmp/hippo-r21a-m1-with.log`, `/tmp/hippo-r21a-cpu-without.log`, `/tmp/hippo-r21a-cpu-with.log` |
| M12 identity, before and after | see R21-M12 | `/tmp/hippo-r21a-m12-identity-base.log`, `/tmp/hippo-r21a-m12-identity-head.log` |
| Ruff check and format check: the ten changed Python files and this file | All checks passed; 10 files already formatted; this file already formatted | `/tmp/hippo-r21a-ruff-final.log` |

Warning handling: every run above uses bare `-W error` except the three regression runs, which use form
(b) of the fleet rules (`-W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`)
because their module lists include module-level `fastapi.testclient` importers. No marker was added.

The broad Fake set is `test_code_binding`, `test_managed_input_binding`, `test_code_history`,
`test_staged_code_writer`, `test_code_generation`, `test_code_capture_acceptance`,
`test_managed_code_activation`, `test_code_projection`, `test_status_code_edges`, `test_build_authority`,
`test_evidence_access`, `test_knowledge_scoped_reads`, `test_query_scoped_reads`,
`test_generation_profiles`, CD1's `test_generation_scoped_reads`, `test_generation_store`,
`test_generation_counts` and `test_staged_prose_writer`, and QSCOPE's reviewed query set
(`test_structural_loading`, `test_derived_projection`, `test_temporal_conflicts`,
`test_temporal_evidence`, `test_temporal_fixture_loader`, `test_query_session`, `test_dense_session`,
`test_snapshot_store`, `test_query_snapshots`, `test_status_access`, `test_managed_source_inventory`),
because the `KnowledgeObject` change reaches every unbounded proof.

## R21-M2: a group member's proof read the whole `KnowledgeObject` table

`_ProofReads.by_id` answered an unbounded proof from `whole(kind)`, and the build authority's proof is
unbounded (it selects `revision_ids`, not generations). `EvidenceAccess.build` looks a reader's groups up
with `by_id("KnowledgeObject", ...)`, so a builder with any enabled `GroupMembership` read the whole table
twice per `check_local` (once in `build`, once in `validate_current`), and `check_local` runs six times per
write batch. `_Overlay._knowledge_rows(kind)` also accepted no key, so no keyed read could reach the store.

The fix:

- `_KEYED_KINDS = {"KnowledgeObject"}` is looked up by ID in every proof. No proof reads that kind whole,
  so there is never a whole read to share, and the records returned are the same. Other kinds keep the
  unbounded behaviour, because an unbounded proof also reads `Artifact` and `ArtifactRevision` whole and
  keyed plus whole would be two reads.
- `_Overlay._knowledge_rows(kind, *, generation_id=None, where=None, ids=None)` forwards the key it was
  given for a live kind and filters an accepted-input kind in place; `_knowledge_get` reads by `ids=`.
  This also closes `evidence-qscope.md` item 11.
- The group resolution moved verbatim into `EvidenceAccess._groups(reads)`, so the build authority can use
  the same code (R21-M1).

| Path | Before (`e026640`) | After |
| --- | --- | --- |
| `check_local` of a group-member builder | 2 whole `KnowledgeObject` reads | every read `ids=[group]`; a proven authority reads none |
| 10-file code build by a group member, an unrelated generation published first | 880 whole-table reads of a generation-sized kind (the same build without the membership makes none) | 0 |
| whole-inventory reader proof with a group membership | 1 whole read | 1 keyed read |

`GENERATION_SIZED` now names `KnowledgeObject`, `Artifact` and `ArtifactRevision`. The build counters
stayed green with the wider list. The query counters did not: `AppContext._graph_for` reads `Artifact`
whole on every graph it builds (`context.py:243`, review R21-m4). That file belongs to no fix slice, so
`test_query_scoped_reads.py` records each read's caller and pins exactly `("Artifact",
"context.py:_graph_for")` as the one known exception; any other whole read of the three kinds, a proof's
included, still fails, and `test_a_code_query_reads_no_generation_sized_table_whole` asserts the pinned
read still happens, so fixing it forces the pin out. Fix shape, as the orchestrator ruled: put
`Artifact.source_id` on the scoped allow-list with a v8 index step, freezing the v7 descriptor first. It
goes to the cleanup slice after this round.

Tests added: `test_a_group_member_builder_looks_its_groups_up_by_id_on_every_check`,
`test_the_overlay_answers_the_scoped_read_contract` (`test_build_authority.py`),
`test_a_group_member_code_build_reads_no_generation_sized_table_whole` (`test_knowledge_scoped_reads.py`),
`test_a_group_member_reader_proof_looks_its_groups_up_by_id` and
`test_a_group_member_readers_code_query_reads_no_generation_sized_table_whole`
(`test_query_scoped_reads.py`). The last was green before the fix: a query's proofs select generations, so
they were already keyed. It is kept as the group-member coverage the brief asks for.

## R21-M1: the build authority's share of a write batch

### What changed

Every `check_local` re-read each accepted pair and span (`_inventory`'s stored-identity read per record)
and re-proved them (`build`, then `validate_current`, each reading the Source row once per artifact). The
code coordinator hands every tree span to the authority, so that work was proportional to the corpus and
repeated six times per batch.

`check_local` now runs the live checks on every call (both captured epochs, `_source_control`, the actor's
standing, the reviewed mappings and `require_source`) and keeps the proof of the accepted inputs per
authority as `(audience, valid_until)`, with `audience = (access, reviewed mappings)`. A cached call only
rechecks the epoch and the earliest policy deadline. A child authority, from `rebaseline` or
`bind_inputs`, proves afresh, and so does the `fresh` authority `_install` captures.

Why keeping the proof is sound: everything else the proof reads is fenced by an epoch this authority
never adopts.

- A policy, workspace or group membership, connector, reviewed-mapping or permission write moves the
  authorization epoch (`RECORD_EPOCHS`, `permission_mutation`, `metadata_mutation`), and so does an
  accepted `Artifact`'s `policy_id` or `deleted_at`.
- A suppression moves the suppression epoch.
- `ArtifactRevision` and `EvidenceSpan` have no mutable fields (`MUTABLE_FIELDS`).
- A reader's groups change only through a membership: a `GroupMembership` must name an existing
  `KnowledgeObject` (`REFERENCES`), and collection never deletes one.
  `test_a_builders_groups_change_only_with_a_membership_which_moves_the_epoch` pins that premise. (A
  test in which a group object appears without an epoch change could not be built: the store refuses
  the membership first.)
- The clock is covered by `valid_until`: `test_policy_expiry_rechecked_without_epoch_mutation` is
  unchanged and green.

Not re-read, and stated in the docstring: an accepted `Artifact`'s `canonical_uri`, the one mutable
field that moves no epoch and grants nothing; and a record another writer first stores with different
contents after the proof, which the store refuses when this build writes its own.

### Measurement

Counted by `rows_by_batch` in `test_knowledge_scoped_reads.py`: rows returned by `_knowledge_rows` (which
`_knowledge_get` reads through) plus Source rows, split into reads inside `BuildAuthority.check_local` and
all others, per write batch, on fresh Fake stores, `batch_size=16`. "Without" is `access.py` and
`build_authority.py` restored from `e026640` in the worktree, measured, then restored to `27a3ddc` with
`git checkout` and checked clean.

| Measure | 10 files, without | 40 files, without | 10 files, with | 40 files, with |
| --- | --- | --- | --- | --- |
| authority rows, heaviest write batch | 1,392 | 4,092 | 42 | 42 |
| writer rows per record written, heaviest batch | 35.43 | 36.46 | within 1.25x | within 1.25x |
| writer membership rows by `generation_id`, heaviest batch | 642 | 2,142 | 642 | 2,142 |
| write batches | 37 | 125 | 37 | 125 |
| process CPU per evidence member | 0.731 ms | 0.761 ms | 0.615 ms | 0.575 ms |

At 160 files, CPU per member was 1.412 ms without and 0.744 ms with, so the 160-file build's cost per
member against the 10-file build went from 1.93x to 1.21x, and the build from 11.01 s to 5.80 s. A
separate whole-build probe (it counted each `_knowledge_get` and the read inside it, so its absolute
numbers are higher) found 121,668 authority rows at 10 files and 1,051,728 at 40 without, and 5,046 and
13,926 with; the checks before the first write batch (395 and 947 of them) are what remains, each
constant.

### The counter test

`test_a_code_build_is_linear_in_its_evidence_members` (CPU, `LINEAR_FACTOR = 3.0` over a measured 1.9x)
is replaced by `test_a_write_batch_proves_its_authority_in_rows_the_corpus_does_not_change`. Over every
write batch of a 10-file and a 40-file build it asserts:

1. the authority's peak rows per batch are equal at both sizes;
2. the writer's peak rows per record written, minus the membership reads, stay within `BATCH_FACTOR =
   1.25`; batches are compared per record because one dependency group (a commit touching every file)
   holds as many records as the corpus has files;
3. pinned, not endorsed: the writer's `GenerationEvidenceMember` and `GenerationMember` reads by
   `generation_id` (`GENERATION_MEMBERSHIP_READS`) grow at least 3x from 10 to 40 files.

Item 3 is the generation-sized per-batch read that remains: `native_write` builds one `GenerationViews`
per call (`store/generations.py:1612`), whose inventory reads both member tables by `generation_id`
(`knowledge/derivations.py:115-122`) whenever the batch writes a rendered view. Carrying one inventory
across a build's batches is r21w's territory and not taken this round. When it lands, item 3 fails and the
set and the CD1 sentence below change with it.

On the merged tree, with r21w's writer, the peaks are unchanged: 42 authority rows at both sizes, 35.43 and
36.46 writer rows per record, 642 and 2,142 membership rows (`/tmp/hippo-r21a-m1-merged.log`).

Also added: `test_the_accepted_inputs_are_proven_once_per_authority_and_afresh_after_a_rebaseline`.

## R21-M4: the capability-loss rebaseline test

The old test changed the role's capabilities and set `owner_id=None`, so `rebaseline` refused at its
`SourceControl` comparison before the child's proof ran. The new
`test_rebaseline_refuses_after_a_capability_loss_and_latches` makes the builder a non-owner who manages the
source through its role (`manage_sources` granted, owner cleared, both before capture), then removes only
that capability. It asserts `_source_control` still equals the captured control and the suppression epoch
is unchanged, then that `rebaseline()` refuses with `cannot manage source`, twice (latched). The `owner_id`
case stays covered by the parametrized `test_rebaseline_refuses_a_changed_source_control_even_with_every_capability`.

Discrimination, after commit `27a3ddc` so the diff held only the mutation:

```text
--- a/src/hippo/knowledge/build_authority.py
+++ b/src/hippo/knowledge/build_authority.py
@@ -441,7 +441,7 @@ class BuildAuthority:
                 try:
-                    child.check_local()
+                    pass
                 except BaseException:
```

Under it, the new test failed and the `e026640` version of the test (copied to a temporary module) passed,
which is the review's finding reproduced. `build_authority.py` was restored with `git checkout`; its
`shasum` matched the pre-mutation value and `git status` showed it clean.

Proposed for r21w's `tests/unit/test_code_generation.py` (verified in an untracked scratch module against
the merged tree `66400d4`: it passes unmutated, and with `child.check_local()` deleted from `rebaseline` it
fails while the current `test_a_capability_loss_mid_build_aborts_and_never_rebaselines` still passes,
`/tmp/hippo-r21a-twin-mutation.log`):

```text
def test_a_capability_loss_mid_build_aborts_and_never_rebaselines(world, monkeypatch):
    w = world
    legacy_row(w)
    # A non-owner who manages the source through its role, set before the build captures its
    # authority, so losing the capability leaves the Source row and `SourceControl` as captured
    # and only the rebaseline child's own proof can refuse.
    w.store.update_role("individual", capabilities=["add_sources", "manage_sources"])
    w.store.set_source_access(w.source, None, owner_id=None)
    calls = spies(w, monkeypatch)
    adopted = []
    rebaseline = BuildAuthority.rebaseline

    def counted(authority):
        child = rebaseline(authority)
        adopted.append(child)
        return child

    monkeypatch.setattr(BuildAuthority, "rebaseline", counted)
    original = staged_code._write_batch
    state = {"written": 0}

    def revoke_after_the_first_batch(store, prepared, batch, **authority):
        result = original(store, prepared, batch, **authority)
        state["written"] += 1
        if state["written"] == 1:
            # The role change alone: it moves the authorization epoch, which takes the
            # coordinator into `rebaseline()`, and it touches no Source field.
            store.update_role("individual", capabilities=["add_sources"])
        return result

    monkeypatch.setattr(staged_code, "_write_batch", revoke_after_the_first_batch)
    with pytest.raises(AuthorizationChanged, match="cannot manage source"):
        build(w, options=options(w, batch_size=1))

    assert adopted == [], "no rebaseline was adopted"
    staged = next(g for g in w.store._knowledge_rows("Generation"))
    assert staged.status == "failed" and w.store.get_source(w.source)["active_generation_id"] is None
    assert calls == []
```

It needs `from hippo.knowledge.build_authority import BuildAuthority`. The build raises, so there is no
receipt; "`rebaselines == 0`" is asserted as no adopted rebaseline.

## R21-M6: the native relation read under suppression and denial

Two tests in `test_code_projection.py`, over the billed tree (`total` in `src/billing.py` is invoked by
`bill`, invokes `helper` and is contained by its module):

- `test_a_suppressed_binding_span_takes_its_symbols_arrows_and_support_with_it`: before, the served
  arrows touching `total` include `INVOKES` and `CONTAINS`; after a `Suppression(target_kind="span")` of
  its binding span, no served arrow and no relation read has `total` as an endpoint or that span in
  `support_span_ids`, and the rest of the generation still serves.
- `test_a_policy_denied_file_takes_its_symbols_arrows_and_support_with_it`: for a reader (`Access(rank=0,
  user_id=builder)`), `src/billing.py`'s `Artifact` moves to a restricted `local_curated` policy (the code
  lane grants a whole source through one planned policy, so this is how a single file is re-scoped; it
  moves the authorization epoch). No served arrow and no relation read touches any object bound on that
  file's spans or cites one of its spans; `INVOKES` from `total` into `helper` was present before.

Finding: `_assemble` drops an arrow whose endpoint is not a projected node, so assertions on served arrows
alone cannot catch a relation read that lets an unauthorized binding in. Both tests therefore also spy on
`projection._native_code_relations` and assert on what it returns.

Discrimination (untracked mutation, never committed):

```text
-    for object_id, rows in bindings.items():
-        if object_id in code_ids:
-            for binding in rows:
-                supports[binding.generation_id][binding.native_id][object_id].add(binding.span_id)
+    for generation_id in generations:
+        for binding in store._knowledge_rows("NativeBinding", generation_id=generation_id):
+            supports[binding.generation_id][binding.native_id][binding.object_id].add(binding.span_id)
```

Both tests failed on the relation-read assertion (the served-arrow assertion still passed, as the finding
above predicts). `projection.py` was restored with `git checkout`, `shasum` matched and `git status` was
clean. Diff: `/tmp/hippo-r21a-m6-mutation.diff`.

## R21-M12: overload observations were cross-attributed

### Decision: fixed

`materialize_code_evidence` bound every node behind a chunk's `symbol_id`. Two overloads share one
codegraph native ID, so the passage for `Move(int)` observed and bound `Move(string)` too, and the reverse.
`code_binding._held(nodes, chunk)` now returns the nodes a passage observed:

- one node behind the ID: that node, whatever its lines (unchanged behaviour);
- several nodes: those whose `[line_start, line_end]` overlaps one of the passage's original line ranges
  in the same file;
- several nodes and no overlap: `ValueError("A prepared passage names a shared code ID but holds none of
  the lines of its nodes")`.

The review suggested "whose original lines contain the node's lines". Containment fails a long overload
split into windows: no window holds the whole method, so the node would bind from none. Overlap binds each
window to the overload it belongs to. Data objects are unchanged: the review's finding is the symbol loop.

Probe (`/tmp/hippo-r21a-probe-overlap.log`, untracked `/tmp/hippo-r21a-probe/probe_overlap.py`): in every
shape tried, each named symbol passage overlaps exactly one node of its native-ID group. Shapes: two
one-line C# overloads, two C# overloads split into eight windows, TypeScript function and method overload
signatures, a Python function split into windows, the binding fixture tree, and the CD9 fixture's Python,
TypeScript, Go, C#, Rust and SQL templates at three files each.

### Identity and the rule version: bumped to `code-binding-v2`

`/tmp/hippo-r21a-probe/probe_identity.py` binds six shapes and prints each generation ID and a digest of
the sorted native rows and the IDs of every binding, observation, object, span, view, derived record and
evidence member. The table compares the binder before and after the M12 change, both still at
`code-binding-v1`, to show where the derivation changed.

| Shape | Generation ID | Digest before | Digest after | Bindings / observations before | After |
| --- | --- | --- | --- | --- | --- |
| binding fixture tree | unchanged | `f2d07a04f73aaf0c` | same | 7 / 20 | 7 / 20 |
| CD9 templates, 3 files each | unchanged | `ccfa6ac4f2f6a7e9` | same | 74 / 198 | 74 / 198 |
| TypeScript overload signatures | unchanged | `c83e983d26f7409c` | same | 4 / 11 | 4 / 11 |
| long Python function | unchanged | `d543f05ce25db9de` | same | 4 / 9 | 4 / 9 |
| two C# overloads | unchanged | `5b28c8788cf79d72` | `c48fa5f5d8dd9978` | 6 / 14 | 4 / 12 |
| two long C# overloads | unchanged | `46f1e0b78850e584` | `9771aceb51a7363e` | 18 / 33 | 10 / 25 |

The derivation changed only where a native ID names several nodes: every generation ID and four of the
six bundles were unchanged. The first case for keeping `code-binding-v1` was that no generation holding a
shared-ID group could have sealed. At `e026640` with this change, an overload tree refuses at the seal with
`Exact NativeBinding inventory differs from prepared coverage`, because the staged writer kept one
`NativeBinding` per native row (R21-B1; untracked scratch build, `/tmp/hippo-r21a-scratch.log`, the
generation left `failed`). r21w then merged first (`1fc6233`) and fixed B1, so on `rag-it-all-tibs` an
overload tree can seal under the old binder.

The orchestrator ruled BUMP, on the strict reading of ruling 10 and of the module's own comment ("Bump
whenever the spans, views, objects, observations, native rows or bindings this module can produce could
change"): the binder's derivation changed, and no sealed generation exists anywhere real yet, so the cost
is zero now and never lower.

- `CODE_BINDING_RULE_VERSION` is `code-binding-v2`. It enters the configuration `generation_for_inputs`
  hashes, so every managed code generation ID moves, and every rendered view and derived record with it:
  in the probe, `tree` `generation-44671add525b...` to `generation-9da3ea9df73c...`; `cd9-templates` `generation-42a5165362e1...` to `generation-7f26abea9d24...`; `ts-overloads` `generation-db051086bdbb...` to `generation-cfcd7eec0a1e...`; `long-python` `generation-d2d779d0531c...` to `generation-79e5e66a6339...`; `overloads` `generation-2f39f235c3fc...` to `generation-e0b15be3c859...`; `long-cs-overloads` `generation-4acb3b340f31...` to `generation-f147bc607361...`, each with the same native rows, bindings and observations as after the M12 change (`/tmp/hippo-r21a-m12-identity-bump.log`).
- `code_history.EXPECTED_CODE_BINDING_RULE_VERSION` moves to `code-binding-v2` in the same commit: one
  line outside this brief's files, granted by the orchestrator. `test_code_history.py:720` still asserts
  the pairing.
- No test hardcodes a code generation ID. In `test_code_binding.py` the frozen-version pin now reads
  `code-binding-v2` (RED first), and the two tests that prove a changed version moves identity now patch
  `code-binding-v3`, since patching `code-binding-v2` would no longer change anything.
- A staged generation from before the bump has another generation ID, so a later build of the same tree
  derives a new generation instead of resuming the old one.

### Pins (`test_code_binding.py`)

- `test_each_overload_is_bound_and_observed_only_from_the_passage_holding_its_lines`: bindings and
  observations of the two overloads are exactly `Move(int)` on lines 5-5 and `Move(string)` on 7-7; the
  bundle has 3 native rows, 4 bindings and 12 observations (6 and 14 before).
- `test_a_split_overload_binds_each_window_only_to_the_overload_whose_lines_it_holds`: one binding and one
  syntax observation per window, each overlapping only its own overload.
- `test_a_passage_naming_a_shared_id_that_holds_none_of_its_nodes_lines_refuses`.
- `test_a_symbol_alone_behind_its_native_id_binds_as_before_whatever_its_lines`: only a shared ID is
  narrowed.

On the merged tree, where R21-B1 seals every binding, a tree holding the two overloads builds and
publishes with 18 bindings over 17 bound native rows, the shared `Move` row carrying exactly two, one per
overload (untracked scratch build, `/tmp/hippo-r21a-overload-publish.log`). r21w's overload tests pin
"more bindings than bound native rows", which holds.

Projection consequence: once overload bindings seal, each overload's `DEFINED_IN` arrow is exact, because
`_native_code_relations` intersects a node's binding spans with the passage closure and each overload's
binding span is now its own. A `CODE_EDGE` touching the shared native row still projects to both overloads'
objects (the cross product in the plan).

### R21-m24 and R21-m26

- m24: `test_a_bundle_whose_references_leave_the_bundle_refuses` reaches "lacks a selected observation",
  "cites an object or span outside the bundle", "view cites a span or derivation outside the bundle",
  "differs from its exact original" and an extra evidence member, each with membership kept exact so the
  reference check is the one that refuses; `test_a_native_id_outside_the_generation_namespace_refuses`
  covers a `Symbol` and a `DataObject`. These were green before the change: they cover existing refusals.
- m26: `_reuse` compared `artifact_id`, `content_hash`, `provider_revision` and `raw_uri`. It now compares
  the whole record except `observed_at`. `test_a_stored_revision_differing_in_any_field_but_its_first_observation_refuses`
  (a different `metadata_json`, a different `source_timezone`) was RED. A stored revision in another
  lifecycle was already refused, earlier, by "An accepted captured file must be an active immutable
  revision". `_reuse` is shared with `code_history.py:940`; `test_code_history.py` is in the broad Fake set.

## R21-m35

`BuildAuthority.rebaseline`'s docstring said `source_control` "carries `access_role_id`, `min_rank` and
`owner_id`". It now says the control is compared whole: kind, workspace, `owner_id`, `access_role_id`,
`min_rank`, the managed flag, the active generation and the input configuration. Wording for the plan and
CD8 is below.

## Other findings

1. `_Overlay.__init__` still reads `AccessPolicy` whole on every `check_local`, and `require_source` reads
   `Workspace`, `Suppression` and `WorkspaceMembership` whole. These are authorization tables (they grow
   with principals and policies), as `evidence-kscope.md` recorded; unchanged.
2. The CD1 CHECK does not run `test_build_authority.py`, where the R21-M1/M2 authority tests live; the CD8
   CHECK below adds it.
3. R21-m4 fix shape as ruled: `Artifact.source_id` on the scoped allow-list plus a v8 index step, V7
   frozen first; cleanup slice.
4. After the merge, the acceptance scenario's arrow oracle disagreed with M12. r21w's fixture now holds a
   C# overload pair; with each overload bound only on its own span, the projection serves `DEFINED_IN`
   from each overload to the passages holding its own lines, while
   `test_code_capture_acceptance.py::assert_arrows_are_the_sealed_relations` still served a native
   `DEFINED_IN` row as every object bound to the node, two crossed arrows more
   (`/tmp/hippo-r21a-final-fake.log`). The scenario passes with `code_binding._held` patched back to
   bind every node (`/tmp/hippo-r21a-acceptance-oracle.log`), and passes with the M12 binder when the
   oracle counts a `DEFINED_IN` pair only if one of the object's binding spans on that node lies in the
   passage's `retrieval_evidence` original spans, the projection's own rule
   (`/tmp/hippo-r21a-exact-oracle.log`). The orchestrator granted that one function to r21a (r21w and r21c
   are merged): `assert_arrows_are_the_sealed_relations` now builds each `(native node, object)` pair's
   binding spans and skips a `DEFINED_IN` `(object, passage)` pair whose spans miss the passage's
   original spans; nothing else in the file changed. CD9's LadybugDB CHECK runs this scenario, so its
   next root run includes the change.

## Ledger lines for the orchestrator

### CD1 CRITERIA (R21-M1, R21-M2; replace the whole line)

```text
  CRITERIA: parameterised `_native_rows`, `_native_relationships` and `_knowledge_rows` return exactly what the unscoped forms returned for the same selection; `native_write`, `native_mutation` and `generation_checksums` use them; a recorded counter of rows returned proves, at two corpus sizes, which per-batch work is bounded by the batch and names the per-batch read that is not; every existing representation checksum, seal and publication result is unchanged; the reviewed prose writer and counts suites stay green. (Amended 2026-09-12 by the design review: native_write and native_mutation scope by ids and native_mutation still raises 'Native relationship crosses generations' for an edge across two generations and still admits an edge to an untagged legacy row; the scoped read is index-backed on the backends that support one, evidenced by the schema statement and not only by the query counter; sealing a generation at the symbol ceiling is linear in the generation in CPU as well as in queries; the scoped edge enumeration still returns every edge with exactly one endpoint in the selection so the 'Native relationship crosses generations' and 'Missing shared graph endpoint' refusals survive, and the two-hop MENTIONS/STATES -> SUBJECT/OBJECT closure is computed by a second scoped pass, never a whole-table read.) (Amended 2026-09-13 by CC11, corrected by cc11b on the final tree: the per-batch bound covers the knowledge tables as well as the native ones — `_check_knowledge_write`'s membership and binding checks read by `generation_id`, by primary key or by a v7 key, and `derivations._Inventory` reads the generation's own `GenerationMember` and `GenerationEvidenceMember` rows and its `DerivedDependency` rows by `derived_record_id`, built once per `native_write` call or checksum pass through `GenerationViews` rather than once per rendered passage through `validate_view`, so no generation-sized knowledge table is read whole per record written (KSCOPE, `test_knowledge_scoped_reads.py`, `evidence-kscope.md`, `evidence-cc11.md` finding 1); a query's proof, projection, snapshot, collection and retention reads are scoped to the generations it selects, so a session's open, lease renewal, validation, retrieval and dense dispatch read no generation-sized knowledge kind whole except `AppContext._graph_for`'s whole `Artifact` read (`context.py:243`, R21-m4), which `test_query_scoped_reads.py` pins by caller for the cleanup slice (QSCOPE, `test_query_scoped_reads.py`, `evidence-qscope.md`).) (Amended 2026-09-13 by r21a, R21-M1 and R21-M2: a managed code build is not linear in its corpus. Each `native_write` call that writes a rendered view builds its own `GenerationViews` inventory, which reads the generation's whole `GenerationEvidenceMember` and `GenerationMember` membership by `generation_id` (`store/generations.py:1612`, `knowledge/derivations.py:115-122`), 642 rows in one write batch at 10 files and 2,142 at 40, so those reads grow with members x rendered-view batches until one inventory is carried across a build's batches. The rest of a write batch is bounded: the build authority proves its accepted pairs and spans once per authority, again only in a rebaseline or `bind_inputs` child or once its earliest policy deadline passes, and otherwise re-reads the Source row, the actor, the reviewed mappings and the authorization tables, 42 rows in the heaviest write batch at 10 and at 40 files where it read 1,392 and 4,092; the writer's other reads are point reads per record written, 35.4 and 36.5 rows per record. No proof reads `KnowledgeObject` whole, a group member's included, and the counters' generation-sized list names `KnowledgeObject`, `Artifact` and `ArtifactRevision` (`test_knowledge_scoped_reads.py`, `test_query_scoped_reads.py`, `test_build_authority.py`, `evidence-r21a.md`).)
```

### CD5 CRITERIA (R21-M12, R21-m24, R21-m26; replace the whole line)

```text
  CRITERIA: spans, rendered views, derived records and dependencies, knowledge objects, observations, native rows, bindings, revision members and evidence members form one closed inventory with no duplicate and no orphan *binding* — a `repository` or `file` knowledge object legitimately has observations and no native row, and must not be treated as an orphan; native IDs equal `symbol_id`/`data_id`/`commit_id` under the generation namespace; `symbol_key` carries the signature discriminator so overloads do not merge, and overloads sharing one codegraph native ID are two knowledge objects over one native row, each observed and bound only from the passages whose original lines overlap its own lines (two one-line C# overloads: three native rows, four bindings, twelve observations; an overload split into windows: one binding per window), while a passage naming a shared ID that overlaps none of its nodes refuses; a stored revision is reused only when it equals the captured revision in every field but `observed_at`; the closure refusals (a binding without its observation, an observation or view outside the bundle, a stale dependency, an extra evidence member, a native ID outside the generation namespace) each refuse; a shared canonical symbol observed by two sources keeps distinct per-source observations; no `Assertion`, `AssertionVersion`, `AssertionSupport` or `SYNONYM` row is produced; the materialiser holds no store handle, model client or clock.
```

### CD8 CHECK (R21-M5; replace the whole line)

```text
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_code_generation.py tests/unit/test_managed_code_activation.py tests/unit/test_ingest_pipeline.py tests/unit/test_ingest_concurrency.py tests/unit/test_managed_pipeline_activation.py tests/unit/test_prose_generation.py tests/unit/test_build_authority.py -q -o addopts='' -W error
```

EXPECT stays `passed`. Run verbatim on this tree: 390 passed, 3 skipped.

CD8 CRITERIA, the `rebaseline` clause (R21-m35; replace that clause only):

```text
`BuildAuthority.rebaseline` accepts an unrelated authorization-epoch change and refuses after any capability loss (a role-managed non-owner losing `manage_sources`, which leaves `SourceControl` as captured), after any suppression-epoch change, when the captured `SourceControl` changed in any field (kind, workspace, `owner_id`, `access_role_id`, `min_rank`, the managed flag, the active generation or the input configuration), including a change to `access_role_id`, `min_rank` or `owner_id` alone even though the actor kept every capability, after a sticky failure and inside a transaction, and never adopts a suppression epoch or a changed `SourceControl`;
```

### CD9 CRITERIA (R21-M3; replace one clause)

The clause below is unchanged by `a01f9c3`, which reworded the `DEFINED_IN` clause after it to "one of
the node's binding spans"; the replacement uses the same reading. Replace `a published code generation
projects \`StructuralCodeEvidence\` with exact original spans and original citations with real line
locators` with:

```text
a published code generation gives every code node structural support, either a `DEFINED_IN` arrow whose `support_span_ids` hold one of the node's binding spans or a `StructuralCodeEvidence` row with exact original spans, and projects original citations with real line locators
```

Assertion shape for `tests/unit/test_code_capture_acceptance.py::assert_projection` (not r21a's file),
replacing the loop over `sidecar.items()`:

```text
bound = defaultdict(set)
for row in store._knowledge_rows("NativeBinding", generation_id=generation_id):
    bound[row.object_id].add(row.span_id)
support = defaultdict(set)
for arrow in code_arrows(graph):
    if arrow.kind == "DEFINED_IN":
        support[graph.node_ids[arrow.src]].update(arrow.extra["support_span_ids"])
# Every bound node in the scenario reaches a passage whose originals hold one of its binding spans, so
# the sidecar is empty; a shared-node shape that produces a row would assert its exact spans instead.
assert sidecar == {}, "the scenario projects no StructuralCodeEvidence"
for node_id in nodes:
    assert bound[node_id] & support[node_id], node_id
```

`test_code_projection.py::test_each_bound_node_is_defined_in_the_passage_whose_originals_hold_its_binding_span`
already asserts this shape for the smaller fixture, including `structural_code_evidence == ()`.

## Plan sentence for the orchestrator

`ai_docs/plans/rag-it-all-task-5-managed-code-capture.md`, "§4, data objects, mentions and overloads",
third bullet (R21-M12). Replace:

```text
- `codegraph.model.symbol_id` carries no signature, so two C# overloads in one file share one
  native ID. They become two knowledge objects and two bindings over one native row, and the first
  in canonical order is kept. This is a recorded defect, not repaired (`evidence-cc6.md`). Fixing it
  needs a `codegraph` change and a native-ID migration.
```

with:

```text
- `codegraph.model.symbol_id` carries no signature, so two C# overloads in one file share one
  native ID. They become two knowledge objects over one native row, the first in canonical order
  kept, and each overload is observed and bound only from the passages whose original lines overlap
  its own (`code_binding._held`, `evidence-r21a.md`): two one-line overloads give two bindings, and
  an overload split into windows gives one binding per window. A passage naming a shared ID that
  overlaps none of its nodes refuses. The rule moved `CODE_BINDING_RULE_VERSION` to
  `code-binding-v2`. The shared native row is a recorded defect, not repaired; fixing it needs a
  `codegraph` change and a native-ID migration.
```

Same plan, "§4, the projection", last paragraph. Replace:

```text
Two overloads sharing one native ID project as the cross product of their knowledge objects. A
status card that counts arrows can then exceed the source row's native count
(`evidence-codeproj.md` finding 3).
```

with:

```text
Two overloads sharing one native ID share its native relations: a `CODE_EDGE` touching that row
projects to both overloads' knowledge objects, the cross product, so a status card that counts
arrows can exceed the source row's native count (`evidence-codeproj.md` finding 3). Their
`DEFINED_IN` arrows are exact, because each overload's binding span is its own.
```

Same plan, "§8.2, rebaseline", third bullet (R21-m35). Replace:

```text
- refuses any change to `SourceControl`'s `access_role_id`, `min_rank` or `owner_id`;
```

with:

```text
- refuses any change to `SourceControl`, which it compares whole: the source's kind, workspace,
  `owner_id`, `access_role_id`, `min_rank`, managed flag, active generation and input
  configuration (a change to `access_role_id`, `min_rank` or `owner_id` alone refuses even though
  the actor kept every capability);
```
