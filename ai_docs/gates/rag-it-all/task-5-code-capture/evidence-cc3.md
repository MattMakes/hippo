# CC3 evidence — resumable staging reclaim (gates CD1, CD7)

Branch `wp/cc3`, worktree `.worktrees/cc3`, base `c461c9c` (CC1, CC6 and CC2 merged).

Plan section 8.2 ("Resume") as amended by the design review
`ai_docs/reports/2026-09-12-code-capture-plan-review.md` **B5** (the four missing preconditions)
and **M1** (manifest equality is a tautology, not the guard).

## The signature, verbatim

```python
def reclaim_generation_build(
    self, generation_id, *, job_key, lease_owner, lease_expires_at, expected_manifest_hash
): ...
```

Returns the `MaintenanceJob` holder, exactly as `claim_generation_build` does. Both live in
`src/hippo/store/generations.py`.

## One preamble, so the guarantees cannot drift

`_admit_build(generation_id, *, job_key, lease_owner, lease_expires_at, expected_manifest_hash=None)`
is the fenced admission both entry points call. It runs inside the caller's transaction and
performs, in this order:

1. read the generation, take `_lock_source`, **re-read** the generation under the lock, read the
   source;
2. the tombstone barrier (`_tombstoned`) — before the fence advances, before a holder is
   installed, before anything is collected;
3. `status in ("staging", "failed")` and `lease_expires_at > now`;
4. the never-published triple (below);
5. the `expected_manifest_hash` assertion, when one is given;
6. live-holder exclusion, with the idempotent same-holder return;
7. `fence = build_fencing_token + 1`;
8. build the `MaintenanceJob`, carry `attempt_count` over from any prior job of the same identity,
   write it, and set `active_build_id` + `build_fencing_token` on the source.

It returns `BuildAdmission(job, generation, reused)`. `reused=True` is the idempotent same-holder
return: nothing was written and the caller must not go on to collect or restage.

The **only** difference between the two entry points is what happens after the preamble:

| | `claim_generation_build` | `reclaim_generation_build` |
| --- | --- | --- |
| `staging` generation | returns the holder | returns the holder |
| `failed` generation | `_collect_generation`, refuse if `blocked_reason`, then → `staging` | → `staging`, **no collection** |

So the reviewed prose retry contract is untouched: a `failed` generation a prose retry claims still
loses its rows before it restages, and
`test_claim_still_collects_the_failed_generation_that_reclaim_would_have_resumed` asserts that
against the same fixture the reclaim tests resume.

## `claim_generation_build` was tightened, in two ways — both named here

The brief permits tightening only if every existing test stays green and the change is named. Both
conditions hold; here is what changed.

Before, at `generations.py:246-253`:

```python
if gen.status == "failed" and (
    gen.published_at is not None
    or any(
        event.generation_id == gen.id and event.kind == "published"
        for event in self._knowledge_rows("IndexEvent")
    )
):
    raise ValueError("Published generations cannot reopen for retry")
```

Now, in `_admit_build`, for both entry points (the `any(...)` below is one line here and wrapped in
the source: these fences are Ruff-formatted at module level, where they are eight columns further
left than the method body they are quoted from):

```python
if (
    gen.published_at is not None
    or source.get("active_generation_id") == gen.id
    or any(event.kind == "published" for event in self._knowledge_rows("IndexEvent", generation_id=gen.id))
):
    raise ValueError("Published generations cannot reopen for retry")
```

1. **The third proof was added.** `source.active_generation_id == gen.id` is the proof
   `fail_generation_build` (`generations.py:456`, `"Published generations cannot fail as builds"`)
   and `_publish_generation` (`:1363`) both treat as independently sufficient — B5 cites them at
   `:311-318` and `:1098-1106`, which were their line numbers in the reviewed file; the claim path
   checked only the other two. B5 point 4.
2. **It now applies to a `staging` generation too, not only a `failed` one.** Gating the triple on
   `failed` for claim and not for reclaim would be exactly the drift the shared preamble exists to
   prevent, and no legitimate flow puts a `staging` generation behind any of the three proofs:
   `_publish_generation` sets `status="active"`, `published_at`, the active pointer and the
   `IndexEvent` in one transaction. A `staging` row any proof names is a corrupted or
   partially-rolled-back state, and refusing it is the honest answer.

The error message and type are unchanged, so no caller's handling changes. Nothing else about
`claim_generation_build` moved: same order, same messages, same fence arithmetic, same
`attempt_count` carry-over, same collection, same return value.

## `expected_manifest_hash` is an assertion, not the safety property (M1)

The docstring says so. `manifest_hash` is in `Generation.identity_fields`
(`knowledge/model.py:368-375`) and `Record` validates `id == make_identity(prefix,
identity_parts())`, so a stored generation with ID *G* necessarily carries the hash that was hashed
into *G*. Passing `generation_id` already pins it; equality proves nothing the ID did not. The
parameter stays because a cheap assertion against a corrupted row costs nothing, and it is checked
**before** the live-holder branch so a same-holder caller with a wrong hash refuses rather than
returning idempotently.

The properties that actually do the work are named in the docstring and claimed nowhere wider:

* the B5 admission preconditions above;
* ruling 10's derivation versions in generation identity (CC6/CC9, not this slice);
* CC8's absence-asserting probe, which is what catches M2's orphan row from a changed derivation.

A `None` or empty hash is refused outright (`"Reclaim requires the stored generation's manifest
hash"`) rather than silently disabling the assertion, because `_admit_build` treats `None` as "no
assertion" for the claim path and an unset caller field must not inherit that meaning.
`test_reclaim_refuses_an_absent_manifest_hash_instead_of_skipping_the_assertion` pins both values;
with the guard removed it fails for the two distinct right reasons, `None` with
`DID NOT RAISE ValueError` — the build was admitted and a holder installed — and `""` with the
mismatch message instead of the required-argument one.

## The refusals, and that they cost nothing

`test_reclaim_refuses_without_advancing_the_fence_or_installing_a_holder` is parametrised over all
six of B5's cases and asserts, for each, that the source row, the generation row and every
`MaintenanceJob` naming this generation are byte-identical afterwards — and, separately, that the
full staged inventory is unchanged:

| case | how it is built | refusal |
| --- | --- | --- |
| `tombstoned` | `begin_managed_source` + `apply_source_tombstone` | `Stale build lease, fence, or generation state` |
| `live_holder` | a live claim by `other-worker` | `Source already has a live build holder` |
| `expired_lease` | `lease_expires_at == now` | `Build requires staging or unpublished failed generation and future lease` |
| `published_at` | `_write_knowledge(gen.replace(published_at=NOW))` | `Published generations cannot reopen for retry` |
| `active_pointer` | `_source_fields(source, active_generation_id=gen.id)` | same |
| `event` | a raw `IndexEvent(kind="published", generation_id=gen.id)` | same |

Each publication proof is exercised **individually**, which is why the last three are built by hand:
a genuinely published generation carries all three at once and is already refused on status.

The refusal snapshot excludes one field, `generation_lock`, and only that one. On the real backends
`_lock_source` runs `SET s.generation_lock=coalesce(s.generation_lock,0)+1`, so an admission that
returns the live holder idempotently *commits* that increment — it records that the lock was taken,
which is the guarantee rather than a mutation of build state. A refusal rolls it back with its
transaction. This was found by the Ladybug run, not assumed; the Fake store has no such counter and
would never have shown it.

## What "resumable" is asserted to mean

`tests/unit/test_generation_resume.py`, 19 tests, both backends:

* an expired holder on a `staging` generation is replaced and **every** staged row survives —
  `GenerationMember`, `GenerationEvidenceMember`, `NativeBinding`, `IndexManifest`, the four native
  kinds, `_native_relationships(generation_id=...)` and all three representation checksums;
* the same after `recover_generation_builds` has marked it `failed`;
* a `ready` generation recovery turned `failed` (crash after the seal, before publication) reclaims
  to `staging`, and `seal_generation` with the recomputed manifest returns the **same manifest ID**
  against the byte-identical existing row, then publishes;
* a `ready` generation still holding a live job is refused, as today;
* the reclaimed job is a build credential exactly as a claimed one: `generation_write` accepts it,
  `seal_generation` accepts it, and the crashed holder's credentials are refused;
* replay is idempotent on this side of the seam — re-running the whole write batch over the
  reclaimed generation leaves the inventory and the checksums unchanged, and the build still seals
  and publishes;
* `attempt_count` carries over: 1 → 2 → 3 across two crash/reclaim cycles with the same `job_key`
  (`MaintenanceJob.identity_fields` excludes `fencing_token`, so the same key is the same row);
* `Generation.created_at` — the capture instant the review's M1 neighbour asks the coordinator to
  adopt rather than re-take — is unchanged by a reclaim taken under a different clock;
* the whole thing across a LadybugDB close and reopen, which is what a crash actually is.

## Reads under the source lock, for the Neo4j parity run

Neo4j is root-owned and was not run here. `_admit_build` issues exactly these reads, all scoped,
none of them a whole-table read:

| kind | key | shape |
| --- | --- | --- |
| `Generation` ×2 | `id` | `MATCH (n:Generation) WHERE n.id = $id RETURN ...` |
| `Source` | `id` | `get_source`, plus `_lock_source`'s `SET s.generation_lock=...` |
| `Suppression` | `target_kind` + `target_id` | `MATCH (n:Suppression) WHERE n.target_kind = $target_kind AND n.target_id = $target_id RETURN ...` |
| `IndexEvent` | `generation_id` | `MATCH (n:IndexEvent) WHERE n.generation_id = $generation_id RETURN ...` |
| `MaintenanceJob` ×2 | `id` | `MATCH (n:MaintenanceJob) WHERE n.id = $id RETURN ...` |

Two of these are newly scoped and are the only read-shape change in this slice:

* **`_tombstoned`** read `_knowledge_rows("Suppression")` whole — every suppression on the
  instance, on the admission path of every build of every size. It now passes CC2's
  `where={"target_kind": "source", "target_id": source_id}`, the two fields its predicate already
  required. `KIND_SCOPED_FIELDS["Suppression"]` allows exactly those two and CC2's v6 step indexes
  both.
* **the publication proof** read `_knowledge_rows("IndexEvent")` whole and compared
  `event.generation_id` in Python. It now passes `generation_id=`, and
  `knowledge_indexevent_generation_id` is emitted by `schema_steps(neo4j, version=5)`, so the
  index predates this slice.

Both are the same predicate expressed to the database instead of to Python, so the result sets are
identical by construction; rows with a null `generation_id` drop out of the scoped form exactly as
`== gen.id` dropped them before.

One caveat for whoever runs parity: **`_tombstoned`'s Suppression read is not reachable through
`apply_source_tombstone`**, which sets `status="deleted"` on the source first, and that is the
branch the barrier short-circuits on. The scoped query shape is therefore proven here by
construction rather than by a test that forces it, and by `source_serves_legacy` (CC1), which
issues the identical `where=` shape on the same kind. A parity run should target the shape through
that caller.

`fail_generation_build`, `_collect_generation` and `apply_source_tombstone` keep their whole-table
`IndexEvent`/`Suppression` reads. They are outside this slice and are named here so the next owner
sees them.

## Commands

CD1:

```
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_generation_scoped_reads.py \
  tests/unit/test_generation_store.py tests/unit/test_generation_counts.py \
  tests/unit/test_staged_prose_writer.py -q -o addopts='' -W error
```

**90 passed** (`/tmp/hippo-cc3-cd1.log`), exit 0.

CD7, limited to the files that exist. `tests/unit/test_staged_code_writer.py` is **CC8's and does
not exist yet**, so the gate's third file is absent from this run and CD7 cannot be closed on this
slice alone:

```
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_generation_resume.py \
  tests/unit/test_generation_failure.py -q -o addopts='' -W error
```

**36 passed** (`/tmp/hippo-cc3-cd7.log`), exit 0.

Ladybug, the brief's selection:

```
HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_generation_resume.py \
  tests/unit/test_generation_store.py -k "claim or reclaim or recover or retry" \
  -q -o addopts='' -W error
```

**23 passed, 31 deselected** (`/tmp/hippo-cc3-ladybug.log`), exit 0. The whole new file on Ladybug,
unfiltered, is **19 passed** (`/tmp/hippo-cc3-ladybug-full.log`), which is the CD9 shape.

Baseline set plus the new file on Fake: **185 passed, 1 skipped**
(`/tmp/hippo-cc3-green-baseline.log`); the same set before any change was **166 passed, 1 skipped**
(`/tmp/hippo-cc3-baseline.log`), so the 19 new tests are the whole delta and nothing existing
changed.

Because `claim_generation_build` was tightened, every suite that claims a build was run too:

```
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_source_lifecycle.py \
  tests/unit/test_managed_pipeline_activation.py tests/unit/test_converting_source_serving.py \
  tests/unit/test_generation_counts.py tests/unit/test_derived_generation_store.py \
  tests/unit/test_temporal_evidence.py -q -o addopts='' -W error
```

**267 passed, 3 skipped** (`/tmp/hippo-cc3-claimcallers.log`), exit 0.

Whole Fake unit suite:

```
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit -q -o addopts='' -W error \
  -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"
```

**10 failed, 4141 passed, 29 skipped** (`/tmp/hippo-cc3-full.log`), exit 1. The ten are **exactly**
the ten CC2 recorded as pre-existing on `7a0c719` (`evidence-cc2.md`, "Pre-existing failures"):
`comm -13` of CC2's list against this run's `FAILED` lines is **empty**, so this slice introduces no
new failure. They are the `test_evidence_context.py` / `test_graph_surface_access.py` /
`test_eval_access.py` legacy-graph fall-through group, which is CD2's subject, not CD1's or CD7's.

RED: `/tmp/hippo-cc3-red.log` — **16 failed, 1 passed**. The 16 fail on
`AssertionError: Resumable staging reclaim is missing`; the one that passes is the contrast test,
which asserts today's collecting `claim_generation_build` and must pass before and after. The
required-hash guard's two tests were driven separately, `/tmp/hippo-cc3-red2.log` — **2 failed**
with the guard removed from the source, restored immediately after.

**Warning filter (fleet rule).** Every other command passes under a bare `-W error` and needed no
filter. Only the whole-suite sweep used **form (b)**, the command-line filter shown above, because
it collects modules that import `fastapi.testclient` at module level. No ini-wide `filterwarnings`
was added and no test gained a marker.

Ruff: `check` and `format --check` clean on `src/hippo/store/generations.py`,
`tests/unit/test_generation_resume.py` and this document.

## Deviations from the brief

1. **`src/hippo/store/snapshots.py` and `src/hippo/store/knowledge.py` were not touched.** Both
   were available. `recover_generation_builds` already leaves exactly the reclaimable state this
   slice needs — a `failed` generation, no holder, an advanced fence — so no recovery change was
   justified, and CC2's `_knowledge_rows(name, *, generation_id=None, where=None)` already answered
   every read the admission path needed. The store files are released unchanged apart from
   `generations.py`.
2. **`tests/unit/test_generation_store.py` was not touched.** The brief allows a contrast assertion
   there; the contrast is a named test in the new file instead, next to the reclaim tests it
   contrasts with, so the retry contract file stays byte-identical.
3. **`claim_generation_build` was tightened**, in the two ways named above. This is the brief's
   explicit option, taken because the alternative is a conditional inside the shared preamble.
