# PA2 evidence: exact selected-generation projection and generation-aware source inventory

**Worker:** backend-developer-2 (brief `ai_docs/handoffs/briefs/pa2-empty-generation-inventory.md`)
**Branch:** `wp/pa2`, base `26f9a55`. Worktree `/Users/mascott/projects/hippo/.worktrees/pa2`.
**Shell:** zsh on macOS (Darwin 25.5.0). **Interpreter:** `.venv/bin/python` 3.12.11, pytest 9.1.1, Ruff 0.16.6.
**Working directory for every command below:** `/Users/mascott/projects/hippo/.worktrees/pa2`.

The orchestrator's gate checkbox is not touched here; this file records commands, results and
decisions only.

## What was implemented

`GraphIndex.selected_managed_generations: tuple[tuple[str, str], ...] = ()` — the sorted, unique
`(source_id, active_generation_id)` pairs one audience proved for one view. It is
evidence-selection metadata, not a dense contributor list, and it is the only thing that can
represent an authorized generation which produced no evidence at all.

`project_managed_graph` gains keyword-only `selected_generations: Mapping[str, str] | None = None`.
A pair is added only when all of:

1. the caller's explicit mapping matches the authorized selection exactly
   (`{generation.source_id: generation.id}` for every generation `_current_generations` accepted,
   which already enforces the Source current pointer, `status="active"`, workspace and profile);
2. that generation has a raw manifest `GenerationMember` revision; and
3. that revision is in the audience's `AuthorizedEvidence.revision_ids` **and** its `Artifact` is
   authorized and owned by the same source.

Omitting `selected_generations` yields `()`, so every existing direct caller keeps working and no
caller can acquire a pair by accident.

## Deviation from the brief's wording (resolved with the orchestrator)

The brief (line 21) required the manifest `ArtifactRevision` to be "an exact
`GenerationEvidenceMember`". That is impossible: `knowledge/model.py`
`GenerationEvidenceMember.record_kind` is a closed `Literal` of `EvidenceSpan`,
`ObjectObservation`, `AssertionVersion`, `AssertionSupport`, `Section`, `SectionMember`,
`RetrievalView`, `ProseExtraction`, `DerivedRecord`, `DerivedDependency`, `ConflictSet`, `Alias` —
there is no `ArtifactRevision` member, and a genuinely empty prose generation has zero
`EvidenceSpan` rows, so that rule would make every empty source permanently invisible and defeat
the task. `ai_docs/plans/rag-it-all-task-5-production-activation.md` line 149 says "exact
GenerationMember", which does bind revisions and is already the `members` set inside
`project_managed_graph`. **Asked and confirmed by the orchestrator:** implement the plan's
`GenerationMember` rule exactly as stated above.

## Decisions recorded at the orchestrator's direction

- **Source-control presentation applies to every managed row whose pair is proven**, not only empty
  ones. With a proven pair `_managed_source` renders the Source's own `name`, `owner_name`,
  `created_at`, `status`, `stage`, `progress_done` and `progress_total`. Without a proven pair the
  row exists only because some evidence happened to be visible, and today's withheld presentation
  is kept (`"Managed source"` fallback name, `status="ready"`, zero progress, empty stage/owner/
  created). `meta` code metadata stays withheld in both cases.
- **`error` stays withheld (`""`) for managed rows in this task.** Task 3's closed
  exception-to-status mapper owns the managed failure message; rendering the stored Source `error`
  before that mapper exists would surface whatever the legacy pipeline left behind.
- **`status._audience_inventory` now opens its owned session with `structural=True`**, so
  `system_status` / `visible_source_count` count the same sources `source_view` renders. This is an
  explicit opt-in at one status owner, not the `query_access`/`query_session` default flip, which
  remains Task 4 / PA6.
- **`source_view` keeps today's `session=None` mechanism**, switching only to
  `ctx.graph_for(access, structural=True)`. It deliberately does not acquire an owned
  `query_session` context manager, because `src/hippo/web/routes/sources.py` `reindex_all` (Task 4's
  file, not mine) calls `source_view(ctx, access)` and then `view.validate()` *after*
  `pipeline.reindex_all` returns; closing an owned session would release the snapshot bundle and
  make that later `validate()` raise. **Task 4 / PA5 obligation:** give `reindex_all` a held owner
  whose lifetime spans its post-operation `validate()`.
- **The non-structural managed path also passes `selected_generations`** (`_build_managed_graph`),
  so PA2 counts and visibility agree whichever path a reader holds. `_build_managed_graph`'s
  `proofs` list is now `(engine, proof, local_selected)` per workspace.

## Existing tests modified

| File | Change |
|---|---|
| `tests/unit/test_status_access.py` | `status_context()` mock graph gained `id` on its passage, `passage_ids` on its fact, and `structural_code_evidence` / `structural_object_evidence` / `structural_relations` / `selected_managed_generations`, because managed counts now come from those sidecars. Two `graph_for.assert_called_with(access, settings=ANY)` became `..., structural=True` (the status-owned session). `test_status_route_and_page_header_pass_the_request_audience` kept `settings=ANY` **without** `structural=True` and gained a comment: those routes own their own non-structural session until Task 4. `@pytest.mark.filterwarnings` added to the 7 TestClient tests (see below). New `test_proven_selected_pair_renders_the_source_control_presentation`. |
| `tests/unit/test_structural_loading.py` | New `test_structural_selection_records_its_authorized_pairs_without_model_access`. `test_structural_shared_canonical_code_object_does_not_collide_across_sources` gained one assertion that the non-structural managed lane proves the same pairs. |

`test_managed_source_surfaces_render_only_projected_evidence` is **unchanged and still passing**:
its fixture monkeypatches `ctx.graph_for` to return a projection with no
`selected_managed_generations`, so it now exercises the no-proven-pair branch, which is exactly the
withheld case the orchestrator asked to keep. The proven-pair counterpart is the new test beside
it. Both cases are therefore covered without weakening the original leak assertions.

## Pre-existing environment failures (not caused by this work)

On clean `26f9a55` with anyio 4.15.1 + starlette 1.6.0, any pytest run with `-W error` that imports
`fastapi.testclient` fails:

```
DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
```

That was 11 failures in `tests/unit/test_status_access.py` and a hard collection error for
`tests/unit/test_web_base.py` before any change of mine. Fixed here the way the repo already does
it (`tests/unit/test_eval_access.py:251`): a per-test
`@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")`
on the 7 TestClient tests in `test_status_access.py`. No ini/`pyproject.toml` change; `test_web_base.py`
and the other TestClient modules still need the same and belong to Task 4.

`tests/unit/test_cli.py` has a second, separate pre-existing `-W error` failure —
`StarletteDeprecationWarning: You should not use the 'timeout' argument with the TestClient` — 14
tests. Verified pre-existing by running the identical command in a throwaway worktree at clean
`26f9a55`:

```
git worktree add .worktrees/pa2-base --detach 26f9a55
HIPPO_TEST_STORE=fake pytest tests/unit/test_cli.py -q -o addopts='' -W error \
  -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"
=> 14 failed, 41 passed          # same 14 as with this branch's changes
```

`test_cli.py` is Task 4's file, so it is untouched here. With
`-W "ignore:You should not use the 'timeout' argument with the TestClient"` added it is 55 passed.

## Commands and results

### Baseline before any change (step 1)

```
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_structural_loading.py \
  tests/unit/test_status_access.py tests/unit/test_evidence_projection.py \
  tests/unit/test_dense_session.py tests/unit/test_graph_index.py -q -o addopts='' -W error
=> 11 failed, 164 passed        # all 11 the pre-existing anyio import failure above
                                # log /tmp/hippo-pa2-baseline.log

# same command plus the one third-party message filter
=> 175 passed                   # log /tmp/hippo-pa2-baseline4.log
```

### RED (step 2)

```
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_source_inventory.py \
  -q -o addopts='' -W error
=> 21 failed, 1 passed          # log /tmp/hippo-pa2-red.log
```

Failure reasons in that log, all the absence of the feature: `AttributeError: 'GraphIndex' object
has no attribute 'selected_managed_generations'` (13), `TypeError: _assemble() got an unexpected
keyword argument 'selected_managed_generations'` (2), `TypeError: project_managed_graph() got an
unexpected keyword argument 'selected_generations'` (1), `KeyError: 'code'` for a shared node the
non-owning source could not count (2), `assert 0 == 1` for the hardcoded `fact_links` (1),
`AssertionError: an empty G1 to empty G2 publication must change the view fingerprint` (1),
`Failed: DID NOT RAISE AuthorizationChanged` because the empty source never reached DTO
construction (1). The one passing test is the staging-inflation regression guard, which already
held.

### GREEN on Fake — the PA2 gate command exactly as `GATES.md` writes it (step 4)

```
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_source_inventory.py \
  tests/unit/test_status_access.py tests/unit/test_structural_loading.py -q -o addopts='' -W error
=> 93 passed, 1 skipped in 1.59s   # exit 0, no warning filter needed
                                   # log /tmp/hippo-pa2-pa2gate.log
```

The skip is the LadybugDB close/reopen assertion, which runs only under
`HIPPO_TEST_STORE=ladybug`.

### GREEN on Fake — regressions

```
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_source_inventory.py \
  tests/unit/test_status_access.py tests/unit/test_structural_loading.py \
  tests/unit/test_evidence_projection.py tests/unit/test_dense_session.py \
  tests/unit/test_dense_capability.py tests/unit/test_graph_index.py \
  tests/unit/test_query_session.py tests/unit/test_query_snapshots.py \
  tests/unit/test_query_snapshot_service.py tests/unit/test_query_authorization_boundary.py \
  tests/unit/test_core_context.py tests/unit/test_evidence_context.py \
  tests/unit/test_derived_projection.py tests/unit/test_rag_replay_access.py \
  tests/unit/test_mcp_server.py tests/unit/test_mcp_http.py tests/unit/test_web_base.py \
  tests/unit/test_web_auth.py tests/unit/test_web_security.py tests/unit/test_cli.py \
  tests/unit/test_eval_access.py tests/unit/test_evals_runner.py tests/unit/test_web_code.py \
  tests/unit/test_web_analyze.py -q -o addopts='' -W error \
  -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"
=> 14 failed, 566 passed        # the 14 are test_cli.py's pre-existing starlette timeout warning
                                # log /tmp/hippo-pa2-reg2.log

HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_web_busy_pages.py \
  tests/unit/test_web_library_evals.py tests/unit/test_graph_surface_access.py \
  tests/unit/test_source_snapshot_lifetime.py tests/unit/test_inventory_snapshot_lifetime.py \
  tests/unit/test_render_snapshot_lifetime.py tests/unit/test_account_snapshot_lifetime.py \
  tests/unit/test_lookup_snapshot_lifetime.py tests/unit/test_graph_snapshot_lifetime.py \
  tests/unit/test_changeset_snapshot_lifetime.py tests/unit/test_eval_snapshot_lifetime.py \
  tests/unit/test_analysis_snapshot_lifetime.py tests/unit/test_saved_snapshot_retention.py \
  tests/unit/test_snapshot_store.py tests/unit/test_generation_store.py \
  tests/unit/test_generation_failure.py tests/unit/test_evidence_access.py \
  tests/unit/test_derived_generation_store.py tests/unit/test_staged_prose_writer.py \
  tests/unit/test_browse_original_citations.py tests/unit/test_changeset_access.py \
  tests/unit/test_settings_and_safety.py -q -o addopts='' -W error \
  -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"
=> 328 passed in 12.03s         # log /tmp/hippo-pa2-reg3.log
```

The whole `tests/unit` Fake suite was run with both third-party filters:

```
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit -q -o addopts='' -W error \
  -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning" \
  -W "ignore:You should not use the 'timeout' argument with the TestClient"
=> 3036 passed, 24 skipped in 181.81s     # exit 0, log /tmp/hippo-pa2-fake-green.log
```

### Each commit green at its own point

`e9e2afe` does not change `status.py`, so the inventory presentation tests are still the base
version there:

```
git checkout e9e2afe
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_structural_loading.py \
  tests/unit/test_status_access.py tests/unit/test_evidence_projection.py \
  tests/unit/test_dense_session.py tests/unit/test_graph_index.py \
  tests/unit/test_core_context.py -q -o addopts='' -W error \
  -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"
=> 182 passed
```

### GREEN on Ladybug (step 5)

```
HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_managed_source_inventory.py \
  tests/unit/test_structural_loading.py tests/unit/test_status_access.py \
  -q -o addopts='' -W error
=> 94 passed in 84.21s          # exit 0, log /tmp/hippo-pa2-ladybug-green.log
```

This includes PA7's inventory half:
`test_empty_source_visibility_survives_a_ladybug_close_and_reopen` publishes an empty generation,
renders its inventory row, closes the `LadybugStore`, reopens the same database and asserts the same
pair and a byte-identical row. It skips under any other backend.

### Ruff (step 6)

```
.venv/bin/ruff check   src/hippo/hipporag/graph_index.py src/hippo/knowledge/projection.py \
                       src/hippo/knowledge/replay.py src/hippo/context.py src/hippo/status.py \
                       tests/unit/test_managed_source_inventory.py \
                       tests/unit/test_status_access.py tests/unit/test_structural_loading.py
=> All checks passed!

.venv/bin/ruff format --check <same files>
=> 8 files already formatted
```

## Audited `dataclasses.replace` / constructor sites

Source list: `rg -n "replace\(|GraphIndex\(" src/hippo`, plus `rg -n "GraphIndex\(|return cls\("
src/hippo` to catch `GraphIndex.load`'s `cls(...)`, which the first pattern misses. Every site that
constructs or copies a `GraphIndex` is listed; sites operating on other types are named so the
audit is complete rather than filtered silently.

**Constructs a `GraphIndex` (3 sites, all handled):**

| Site | Handling |
|---|---|
| `src/hippo/hipporag/graph_index.py:473` (`GraphIndex.load`, `return cls(...)`) | Left at the `()` default on purpose: a raw store load selects no managed generation and must never claim one. |
| `src/hippo/hipporag/graph_index.py:862` (`GraphIndex.scoped`) | Filters to `pair[0] in visible`; the identity fast-path above it also gained `all(source in visible ...)` so an evidence-less pair cannot ride the shortcut. |
| `src/hippo/knowledge/projection.py:873` (`_assemble`) | New keyword-only `selected_managed_generations=()` forwarded; also appended to the `_assemble` version payload when non-empty. |

**Copies a `GraphIndex` with `dataclasses.replace` (3 sites, all preserved by field default; no
edit needed, each proven by test):**

| Site | Proof |
|---|---|
| `src/hippo/knowledge/dense_session.py:148` (`_activate`, structural → dense) | `test_managed_source_inventory.py::test_structural_to_dense_activation_retains_the_selected_pairs` |
| `src/hippo/knowledge/dense.py:315` (`structural_legacy_graph`) | `test_structural_loading.py::test_structural_selection_records_its_authorized_pairs_without_model_access` asserts the legacy lane claims no pair |
| `src/hippo/context.py:163` (`_authorize_legacy`) | Legacy-only path; `test_status_access.py` and `test_core_context.py` cover it. `replace` keeps the field untouched. |

`dense_session.py` needed **no** change, which the brief predicted. `replay.py` reconstruction
needed no change either; only `view_fingerprint` in that file was extended.

**`replace(...)` calls on other types, inspected and correctly out of scope:**
`src/hippo/hipporag/graph_index.py:814` (`CodeNode`), `:897` (`LegacyDenseVector`),
`src/hippo/knowledge/replay.py:70,88,102,118,131,150` (`Trace` rows), `src/hippo/ask.py:116`
(`Trace`), `src/hippo/access.py:204` (`Principal`), `src/hippo/analysis/simulate.py:167` (`Trace`),
`src/hippo/knowledge/model.py:106,139` and every `src/hippo/store/*` `record.replace(...)`
(immutable knowledge records), `src/hippo/ingest/prepared_chunks.py:142` (`_MappedText.replace`,
string surgery).

**Other `return cls(...)` sites confirmed unrelated:** `knowledge/build_authority.py:42,46`
(`BuildActor`), `knowledge/raw_artifacts.py:62`, `context.py:67` (`AppContext`),
`access.py:143,150` (`Principal`), `remote.py:68`, `analysis/simulate.py:94`.

## Files changed

- `src/hippo/hipporag/graph_index.py` — field, `canonical_selected_generations`, `__post_init__`
  canonicalization, `scoped` fast-path guard and filter.
- `src/hippo/knowledge/projection.py` — `_selected_pairs`, `project_managed_graph`
  `selected_generations=`, `_assemble` parameter + version payload, `compose_graphs` union and
  `populated` fix.
- `src/hippo/knowledge/replay.py` — `view_fingerprint` payload extension.
- `src/hippo/context.py` — per-workspace source→generation mapping passed into projection from both
  `_build_managed_graph` and `_build_structural_graph`.
- `src/hippo/status.py` — `source_view` structural acquisition and pair-based representation,
  `_managed_source` provenance counts and control presentation, `_audience_inventory` structural
  owned session.
- `tests/unit/test_managed_source_inventory.py` (new, 24 tests; one is Ladybug-only).

One of those tests, `test_relation_predicates_cannot_be_counted_twice_as_code_edges`, guards a
counting invariant rather than a behaviour: `_managed_source` counts inherited code relations from
`code_out` filtered by `CODE_EDGE_KINDS` and assertion relations from their exact selected pair. The
two vocabularies are disjoint today (verified: `set(CODE_EDGE_KINDS) & set(PREDICATES) == set()`), so
no relation is counted twice; if a later task adds a predicate that is also a code edge kind, that
test fails instead of silently doubling a row's edge count.
- `tests/unit/test_status_access.py`, `tests/unit/test_structural_loading.py` (see table above).

Nothing under `src/hippo/store/`, `src/hippo/ingest/`, `src/hippo/web/`,
`src/hippo/knowledge/query_access.py`, `dense_session.py`, `dense.py`, `access.py`, `ask.py`,
`mcp_server.py` or `cli.py` was touched, nor `GATES.md`, `docs/` or the checkpoint.

## Open findings for the orchestrator

1. **PA6/PA7 gate CHECK lines will still fail as written** until the same
   `@pytest.mark.filterwarnings` marker reaches the other TestClient modules — at minimum
   `tests/unit/test_web_base.py` (collection error), `tests/unit/test_mcp_http.py`,
   `tests/unit/test_web_auth.py`, `tests/unit/test_web_analyze.py`, `tests/unit/test_web_code.py`.
   `tests/unit/test_cli.py` additionally needs the starlette `timeout` filter. All are Task 4 files.
2. **Task 4 / PA5:** `web/routes/sources.py` `reindex_all` validates a `source_view` after the
   operation returns; it needs a held owner spanning that call (see decision above).
3. **A non-structural managed view does carry the pairs** (`_build_managed_graph` passes
   `selected_generations` too), asserted by
   `test_structural_loading.py::test_structural_shared_canonical_code_object_does_not_collide_across_sources`.
   The remaining limitation is not the pair but the profile coupling that lane already had:
   `_current_generations` requires every selected generation's `embedding_profile` to equal
   `ctx.ollama.embed_model`, so a source built under another profile raises `ProjectionError` on that
   path regardless of this change. Task 4's structural flip removes that coupling for production
   readers; nothing here makes it better or worse.

## Known effects

Adding the pairs to the `view_fingerprint` payload invalidates saved fingerprints **once** for a
managed corpus: a trace or evaluation fingerprint recorded before this branch will not match, so
`can_reuse_answer` and saved-snapshot reuse return `False` on the first comparison after upgrade and
the answer is recomputed rather than reused. That is the intended direction of the change (a stale
fingerprint must not look reusable) and it is bounded to one miss per saved output. Legacy-only
graphs are unaffected: their pairs are empty, so the payload and therefore the fingerprint are
byte-identical, which `test_structural_loading.py`'s existing legacy-adapter fingerprint equalities
prove.
