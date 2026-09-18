# PA2 finding 5: a relation supported by two generations is unreachable by design

Owner: opus-20. Branch `wp/pa2f5` from `rag-it-all-tibs` `38ffa70`. Tests only, one new file:
`tests/unit/test_multi_generation_support.py`. No production change.

## The answer

The fixture the finding asks for cannot be built. A proof group belongs to exactly one
generation, so `StructuralRelationEvidence.source_generations` always holds exactly one
`(source_id, generation_id)` pair for any sealed exact generation, and
`status.py:142`'s `pair in row.source_generations` has no second element to find.

opus-17 established that the **sequential** shape is refused
(`Sealed assertion proof group cannot gain support`, `src/hippo/store/generations.py:690`) and
proposed the **interleaved** shape instead: both generations in staging, the second joining the
first's `(assertion_version_id, "declared")` group before either seals. That shape is refused
too, one step later, at seal time. Sealing a generation that carries an `AssertionVersion`
requires **every** `AssertionSupport` row in the store for that version to be in that same
generation's exact interpretation (`generations.py:994-1001`), and the second source's support
can never be in the first's exact set. Whichever side seals first, one clause fires; and the
gap cannot be closed by borrowing the other generation's support, nor by putting both sources'
evidence in one generation.

Each door is now pinned by a test, so the shape is not re-attempted a third time.

| Test | Refusal | Line |
|---|---|---|
| `test_a_second_source_cannot_join_a_published_proof_group` | `Sealed assertion proof group cannot gain support` | `store/generations.py:690` |
| `test_the_interleaved_group_cannot_seal_the_versions_own_generation` | `Incomplete assertion proof group` | `store/generations.py:1001` |
| `test_the_interleaved_group_cannot_seal_the_joining_generation` | `Incomplete assertion proof group` | `store/generations.py:1001` |
| `test_a_join_that_leaves_out_the_version_has_an_incomplete_closure` | `Incomplete exact interpretation closure` | `store/generations.py:993` |
| `test_the_other_generations_support_cannot_be_borrowed_while_its_build_runs` | `Managed evidence write requires build authority` | `store/generations.py:601` |
| `test_the_other_generations_support_cannot_be_borrowed_after_it_publishes` | `Evidence member is outside generation revisions` | `store/generations.py:646` |
| `test_no_generation_can_hold_a_second_sources_revision` | `Generation member belongs to another source` | `store/knowledge.py:690` |
| `test_every_projected_relation_carries_exactly_one_contributing_pair` | the invariant that follows: one relation, one pair, one counted lane | `status.py:142` |

The two borrow tests are the same door from both sides: while the donor's build is running the
write needs *that* lease (a single `_generation_authority` is held at a time, so two sources'
running builds cannot be satisfied at once), and once the donor has published the same write is
simply outside the borrower's own manifest revisions.

The only interpretation path that does not filter `AssertionSupport` by generation membership
is the compatibility branch (`knowledge/access.py:117-124` and `:132-163`), which admits only
generations whose `IndexManifest` is not ready with all three checksums
(`knowledge/access.py:89-99`); `context.py:416` requires exact membership for every strict one.
A generation the managed pipeline sealed is always strict, so that path is closed for
`source_view` and cannot be used to assemble a two-source group either.

## Discrimination proof

A coverage test has no RED, so the discriminating experiment is the inverse: relax the rule and
watch the pins fail. In the `pa2f5` worktree only, the all-members clause of
`generations.py:1001` was reduced to `if not supports:` and the suite re-run:

```
2 failed, 7 passed
FAILED test_the_interleaved_group_cannot_seal_the_versions_own_generation - DID NOT RAISE
FAILED test_the_interleaved_group_cannot_seal_the_joining_generation - DID NOT RAISE
```

`src/hippo/store/generations.py` was then restored with `git checkout --` and verified byte for
byte: `md5 -q` is `836c27a0040cbb55f7898ac8e107fc0a` before the edit and after the restore, and
`git status --porcelain` reports only the new test file. Log: `/tmp/hippo-pa2f5-discriminate.log`.

**What the relaxed run also showed, and the later slice should know.** With that one clause
relaxed and nothing else changed, the interleaved shape completes end to end and produces
exactly what the finding described: one relation whose `source_generations` carries **both**
pairs, and `edges_by_kind["BOUND_TO"] == 1` on **both** source rows
(`/tmp/hippo-pa2f5-relaxed-shape.log`). So `status.py:142` and the grouping at
`knowledge/access.py:445-447` are not wrong -- they are correct code for a shape the store's
seal rule forbids. Per the orchestrator's ruling, the recommendation of record is that the dead
multi-pair branch at `status.py:142` be simplified in a later slice; that measurement is
recorded here because it argues the alternative (relax the seal clause and keep the branch) is
the same one-line decision, and the design owner should pick knowingly rather than by default.

## Runs

Both commands were run verbatim in `.worktrees/pa2f5`. Neither needs the AnyIO filter: no
module in this file's import graph imports a transport at module level, and a bare `-W error`
is clean (form: none).

| Command | Result | Log |
|---|---|---|
| `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_multi_generation_support.py -q -o addopts='' -W error` | **8 passed — EXIT 0** | `/tmp/hippo-pa2f5-green-fake.log` |
| `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_multi_generation_support.py -q -o addopts='' -W error` | **8 passed — EXIT 0** | `/tmp/hippo-pa2f5-green-ladybug.log` |
| The PA2 gate line plus this file, on Fake | **105 passed, 1 skipped — EXIT 0** | `/tmp/hippo-pa2f5-pa2-with-new.log` |

The third run is the PA2 CHECK line with `tests/unit/test_multi_generation_support.py` appended:
97 + 8 = 105, so the new file adds eight tests and perturbs none of PA2's own. Whether the gate
line grows is the orchestrator's call; no ledger line was edited here.

Ruff: `.venv/bin/ruff check` and `.venv/bin/ruff format --check` both clean on the new test file
and on this document.

## Deviations from the brief

1. **The brief's REQUIRED BEHAVIOR 1 could not be delivered as written**, because its premise is
   false; the orchestrator ruled option (a), close the finding as unreachable-by-design and pin
   the refusals. Items (a) and (b) of that list are covered by the invariant test in their
   reachable, single-contributor form; items (c) revoke-one-audience, (d) tombstone-one-source
   and (e) the unpublished third contributor presuppose the shared group and are subsumed by the
   refusals. Item (e)'s intent -- "retired/staging contributions do not inflate current counts",
   `ai_docs/plans/rag-it-all-task-5-production-activation.md:254` -- is kept: the invariant test
   stages a third contributor that is never published and asserts it wins no pair and no row.
2. **(c) and (d) would not have behaved as the brief describes even if the group existed.**
   `knowledge/access.py:466` drops a whole proof group when any member's span is unauthorized,
   so revoking one contributor's audience would have removed the relation outright, not just its
   pair. The same fail-closed rule holds one layer up: `graph_index.py:878` keeps a relation
   under `scoped()` only if **all** its support spans are visible, so opus-17's drafted
   assertion that the relation survives `scoped({either.source_id})` would have been wrong as
   well. Half a shared proof is not a proof.
3. **Two line references in the brief are stale.** The status branch is `status.py:142`, not
   `:124`, and the sequential refusal is `store/generations.py:690`, not `:601` (`:601` is the
   build-authority guard, which this file also pins).
4. **The temporary edit for the discrimination proof touched `src/hippo/store/generations.py`**,
   which opus-19 owns. It was confined to the `pa2f5` worktree's own copy, was never committed,
   and was restored byte for byte as recorded above. The brief's STEPS sanction exactly this
   ("temporarily breaking the multi-contributor branch locally ... then restore byte for byte
   and say so").
