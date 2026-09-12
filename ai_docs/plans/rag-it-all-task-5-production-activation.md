# RAG-it-all Task 5 production activation plan

**Status:** proposed implementation contract. The plain-prose coordinator and dense-session dispatcher are prerequisites; this document does not claim that production routes are activated.

**Goal:** activate the reviewed managed path for authenticated local pasted text and plain-prose files, make every production reader see the same generation-scoped corpus, and dispatch delete/reindex/bulk operations without allowing a managed source through legacy destructive cleanup. LadybugDB is the required primary implementation and acceptance backend. Neo4j must preserve the same contract for scale.

This is a bounded Task 5 integration. It does not add repository/code generations, rich-document managed extraction, connectors, temporal reconstruction, restore, physical purge, retention collection, or autonomous maintenance. Those remain in their assigned tasks. In particular, a managed delete in this increment is an immediate current-view tombstone and builder fence. It is not byte erasure.

## Prerequisites and current seams

The implementation must build on these reviewed primitives rather than reproduce them:

- `src/hippo/ingest/prose_generation.py`: `build_plain_source`, `PlainBuildOptions`, immutable raw capture, verified embedding/OpenIE profiles, atomic bootstrap/refresh publication, and non-collecting failure.
- `src/hippo/knowledge/dense_session.py`: `retrieval_session`/`dense_session`, contributor-based verified versus tag-compatible routing, one structural owner, and profile validation outside transactions.
- `src/hippo/knowledge/build_authority.py`: explicit `BuildActor.reader(principal)` and `BuildActor.trusted_local()`; open and preview audiences cannot build managed evidence.
- `src/hippo/knowledge/query_access.py` and `src/hippo/context.py`: one held authorization/generation snapshot and opt-in structural loading.
- `src/hippo/store/generations.py`: source fencing, staged generations, exact membership, atomic publication, recovery, references, and conservative collection.
- `src/hippo/knowledge/raw_artifacts.py` and `embedding_cache.py`: bounded content-addressed raw storage and disposable profile-keyed vector cache.

The legacy pipeline remains the compatibility implementation for repositories, archives, samples, rich files, code files, open-mode ingestion, and existing direct callers that do not provide a build actor. Its public return shapes remain stable.

## Required public behavior

### Managed eligibility and dispatch

Use the presence of an explicit `BuildActor` as the opt-in at the existing pipeline boundary. Extend these signatures with keyword-only `build_actor: BuildActor | None = None`:

```python
add_text(..., build_actor=None) -> str
add_upload(..., build_actor=None) -> str
start_indexing(ctx, source_id, *, build_actor=None, operation_id=None) -> bool
run_indexing(ctx, source_id, *, build_actor=None, operation_id=None) -> None
reindex(ctx, source_id, *, build_actor=None) -> bool
reindex_all(ctx, *, build_actor=None) -> int
delete_source(ctx, source_id, *, build_actor=None, operation_id=None) -> None
```

An omitted actor preserves the existing legacy behavior for an unmanaged source. An actor never converts an unsupported source family.

| Source/input | Explicit reader or trusted-local actor | No actor / open audience |
|---|---|---|
| New pasted `text` | Managed plain-prose bootstrap | Legacy |
| New uploaded `file` with `.txt`, `.md`, `.markdown`, `.rst`, or `.text` | Managed plain-prose bootstrap | Legacy |
| Existing eligible legacy `text`/plain file reindex | Atomic managed bootstrap; legacy evidence serves until publish | Existing destructive legacy reindex |
| Existing managed text/plain file | Managed refresh only | Refuse before mutation; never fall back to legacy |
| Archive, repo, sample, PDF/DOCX/EPUB/HTML, code/config file, extensionless or binary input | Legacy | Legacy |
| Current-tombstoned source | Refuse/skip; never resurrect | Refuse/skip |

Eligibility is a closed predicate in the activation module and reuses `readers.PROSE_EXTENSIONS`. It must check the saved Source kind and sanitized stored filename, not an HTTP content-type claim. A managed Source is recognized with `store.source_is_managed`; artifacts/generations are a migration consistency check, never a reason to send it to legacy cleanup.

`add_text` and eligible `add_upload` still create the Source and save ingress bytes under `data_dir/sources/<source_id>/...` before the background job starts. Generate a bounded unique operation ID before submitting the job, capture the immutable actor and operation ID in the closure, and pass both through every managed retry/failure decision. Never capture a bearer token, Request, session cookie, or ambient principal in a worker.

### Build actors at every boundary

The app has one default local workspace in this increment. Its local User records are the authoritative identity mapping for that workspace.

- Web page forms and JSON routes call `require(..., "add_sources")`, obtain the current `Principal`, construct `BuildActor.reader(principal)`, and pass it for pasted text and eligible plain uploads. Delete/reindex use the already authorized `manageable_source` principal. Bulk reindex retains `edit_graph` and passes that principal's reader actor.
- HTTP MCP uses only the principal resolved by `AuthGate`; it must not inspect the process `HIPPO_TOKEN`. Stdio MCP continues resolving `HIPPO_TOKEN` through its existing principal provider. `hippo_remember` passes a reader actor only for a real reader; open MCP remains legacy.
- Remote CLI continues through HTTP and inherits server authorization.
- Direct local `hippo index` resolves `HIPPO_TOKEN` with `principal_from_bearer` when users exist. It requires `add_sources` and passes a reader actor. A missing/invalid token in gated mode fails before source creation. In never-gated open mode it preserves legacy indexing.
- `BuildActor.trusted_local()` is accepted only from an explicit internal/library/maintenance call. Web, MCP, and CLI code must never manufacture it as an authentication fallback.
- Existing library callers that omit `build_actor` retain legacy behavior. Once a Source is managed, an omitted/invalid actor fails closed before clear, file deletion, generation mutation, or model I/O.

Because `EvidenceAccess` requires a reviewed `WorkspaceMembership`, activate a controlled local mapping at the store boundary:

1. Add `ensure_local_workspace_memberships(principal_ids: Iterable[str] | None = None) -> int` plus a transaction-internal `_ensure_local_workspace_memberships_locked(...) -> int` to `KnowledgeQueries`, usable by both `Store` and inherited `LadybugStore`.
2. Under one store transaction and authorization lock, ensure `"local"` is present in the sorted, unique `reviewed_mapping_authorities` metadata and ensure every selected live User has one enabled default-workspace `WorkspaceMembership(mapping_authority="local")`. Repair an older disabled/different mapping by increasing `policy_epoch`. The locked helper reports the number of changes but does not bump epochs. The public wrapper does not bump the authorization epoch either (Amended 2026-09-11 after the Task 2 review): the mapping bootstrap is additive, so it can only leave stale denials, which are fail-safe, whereas bumping on the first lazy `ping()` invalidates a query session already open across that ping. Access reductions happen only inside `permission_mutation`, which owns its single bump.
3. Call the public all-user form during `Store.on_first_connection` and `LadybugStore.on_first_connection`, after schema and roles. Call the locked one-user form inside each backend's existing `create_user` permission-mutation transaction so that transaction's existing epoch bump covers both records. Disable that user's membership with the same locked helper before `delete_user` removes the User; retain the disabled record as audit state. Do not nest a second epoch-owning wrapper inside either user mutation.
4. Do not infer provider/group memberships, add open identities, or grant a role beyond the current User/Role and Source ACL checks. Idempotent startup performs no epoch bump when nothing changed.

This is an explicit product policy for the single local workspace. Tests must prove that a disabled user, changed role, Source ACL change, deleted user, missing membership, or removal of the reviewed authority invalidates a running build.

### Managed build resources and coordinator adapter

Add `src/hippo/ingest/managed_activation.py` as the sole adapter from a saved Source to `build_plain_source`. It owns no storage records itself.

For one eligible Source it must:

1. Re-read the Source, verify it is not current-tombstoned, and locate exactly one saved ingress file under `source_dir(ctx, source_id)`. Refuse missing, symlinked, non-regular, changed-during-capture, oversized, or filename-escaping inputs.
2. Construct one immutable `FileInput` with the saved file's absolute path, sanitized logical filename (`text.md` for pasted text), and `text/plain`. The saved source directory remains reindex authority; the managed raw object is immutable historical evidence.
3. Lazily construct `RawArtifactStore` at `(Path(config.data_dir).resolve() / "knowledge" / "raw-v1")` with `max_object_bytes=config.max_upload_bytes`, and `EmbeddingCache` at the sibling `cache/embeddings-v1`. No query, status, startup, legacy ingestion, or unsupported route creates these directories.
4. Capture `PlainBuildOptions` from the effective immutable configuration: current chunk size/overlap, current synonym threshold, `openie_workers`, one input/file, `max_upload_bytes`, `max_text_chars`, and the coordinator's reviewed bootstrap/batch/lease caps. Reject values outside the coordinator contract. Do not truncate or silently lower coverage.
5. Construct the `EmbeddingSpec` using the same current Ollama base-model prefix mapping used by dense-session compatibility resolution. Factor one pure helper if needed so ingestion and explicit empty-corpus resolution cannot drift. Persisted generation descriptors remain authoritative after publication.
6. Map coordinator `BuildProgress` to Source `status`, `stage`, `progress_done`, and `progress_total` only. Do not put progress/status/error into `meta_json`, which participates in `SourceControl.input_config_json`.
7. Call `build_plain_source` outside every ambient store transaction. Forward `Jobs.is_cancelled(job_key)` and never invoke model/file callbacks under store locks.

The first managed publication atomically replaces legacy evidence as already guaranteed by the coordinator. Refresh keeps G1 serving until G2 publishes. The adapter must never call `_clear_passages`, `delete_passages_for_source`, `delete_code_for_source`, `remove_orphans`, `store.delete_source`, `shutil.rmtree`, generation collection, raw deletion, or any source-wide cleanup for a managed attempt.

### Failure and progress presentation

Add a closed exception-to-status mapper in `managed_activation.py`. It emits a stable internal code and a generic bounded Source message; it never stores or returns `str(exc)` for an unknown/model/profile/raw/filesystem exception.

Required state transitions:

- Initial bootstrap success: coordinator publication owns `ready/ready`, progress, and generation-aware counts.
- Refresh start/progress: keep `status="ready"` while setting a safe `stage` such as `refreshing: capture|extract|write|publish`; current G1 remains available.
- Refresh failure/cancellation with an active generation: keep `status="ready"`; set `stage="refresh_failed"` or `"refresh_cancelled"` and a generic error code/message. Do not change active pointer or public G1 counts.
- Initial bootstrap failure/cancellation with no active generation: set `status="failed"`, safe stage, and generic error. The coordinator's unpublished generation failure remains retained for recovery/collection.
- Tombstone observed at any point: do not overwrite `status="deleted", stage="tombstoned"` or clear the suppression. A late worker is harmless because the source fence and authorization/suppression epochs reject writes/publication.

Logs may include source ID, operation ID, safe phase, and stable exception class/code. They must not include source text, raw bytes, absolute paths, tokens, prompts, provider response bodies, model output, or unknown exception strings. HTTP/MCP/CLI responses use the same safe error mapper described below.

### Managed delete: suppression now, physical purge elsewhere

Add `src/hippo/knowledge/source_lifecycle.py` and a transactional store primitive in `src/hippo/store/generations.py` for managed tombstoning. The public service takes `ctx`, `source_id`, explicit `BuildActor`, and bounded `operation_id`, and returns an immutable receipt.

The service first captures empty-input `BuildAuthority`. It requests cooperative cancellation of `index:<source_id>`, then enters one callback-free transaction, locks authorization and the Source, calls `guard.check_local()`, and performs this exact transition:

- Recheck the Source is managed and the captured actor may still manage it.
- Increment `build_fencing_token` and clear `active_build_id`.
- If that exact active build names an unpublished staging/ready generation, mark only that generation failed and its exact running `MaintenanceJob` cancelled with the closed code `source_tombstoned`. Never modify the published active generation or another job/generation.
- Insert an all-principals `Suppression` for `target_kind="source"`, `target_id=source_id`, `reason="tombstone"`, `view_applicability="current_only"`, `scope_key=f"source:{source_id}:delete"`, the next suppression epoch, and `restoration_barrier=operation_id`.
- Set the retained Source presentation to `status="deleted"`, `stage="tombstoned"`, zero progress, and no detailed error. Keep `active_generation_id` unchanged for authorized historical reconstruction.
- Commit suppression/content/authorization epoch changes with the transition. In-flight current sessions must fail validation; every new current session excludes the source immediately.

Cooperative cancellation is not the safety mechanism and delete must not wait for a blocked model call before suppressing. For a managed source, do not call `Store.delete_source`, delete native passages/code, sweep orphans, remove `data_dir/sources/<id>`, remove content-addressed raw blobs/cache entries, discard/collect generations, rewrite saved snapshots, or erase retained history. Physical enumeration/removal, restoration, backup handling, retention, and purge verification belong to Task 9A.

The existing HTTP response remains `{"deleted": source_id}` after a committed transition. Subsequent current lookup returns the same 404 as any unavailable source. A retry must not disclose whether an inaccessible/tombstoned source exists. Internal operation-id replay may return its prior receipt only after the same trusted authority is established; it must not add another suppression epoch.

Legacy delete remains unchanged and physically deletes legacy evidence/files. The existing `legacy_source_cleanup` refusal stays as a final invariant: no dispatcher branch may weaken or bypass it.

### Reindex and mixed bulk behavior

`reindex` dispatches after current actor/source/suppression checks:

- Managed: start a managed refresh from saved bytes. Never prepare/clear legacy rows.
- Eligible legacy plus actor: start an atomic managed bootstrap. Legacy evidence remains readable until publication.
- Unsupported legacy, or eligible legacy without actor: existing `_prepare_reindex` and legacy job.
- Tombstoned: return false/not found without mutation.

`reindex_all` retains the existing global `edit_graph` requirement and conservative no-index-job precondition. Before any destructive legacy preparation it snapshots the current Source rows, skips current tombstones, classifies every source, and validates BuildAuthority for every managed refresh or eligible conversion. If any managed preflight fails, it clears nothing and starts nothing.

After successful preflight, run `_prepare_reindex` only for the legacy lane, completing all legacy clears before starting any job so the current orphan-sweep invariant remains true. Then submit each captured lane with its immutable actor and operation ID. One source's asynchronous failure must not clear another source, change another active pointer, or make another G1 unavailable. Keep the public API's `{"accepted": true}` response and do not expose hidden per-source outcomes. The internal integer remains number of jobs accepted by `Jobs`, not evidence counts.

Every worker rechecks its classification and authority. A race that converts, suppresses, changes ACLs, or changes the actor before execution fails safely; it cannot fall back to legacy.

### Structural source inventory, including empty generations

Extend `GraphIndex` with a canonical immutable field:

```python
selected_managed_generations: tuple[tuple[str, str], ...] = ()
# sorted unique (source_id, active_generation_id) pairs proven for this view
```

This field is evidence-selection metadata, not a dense contributor list. `project_managed_graph` may add a pair only when:

- the Source/current pointer and Generation match the caller's exact selected generation;
- its sealed manifest ArtifactRevision is an exact GenerationMember; and
- that manifest revision is in the audience's `AuthorizedEvidence.revision_ids`.

Pass the selected source/generation mapping explicitly from `AppContext` into projection. Do not infer an empty source from unrestricted Source rows or manifest counts. A source-level ACL alone is insufficient if its artifact policy denied the generation. Suppression removes the pair through the normal current proof.

Preserve/filter/compose this field in `GraphIndex.scoped`, projection `_assemble`, `compose_graphs`, structural/dense `dataclasses.replace`, and `view_fingerprint`. An empty G1 to empty G2 publication must change the view fingerprint. Dense-session contributor classification must continue inspecting retained evidence sidecars/provenance only; an empty selected pair must not trigger profile resolution or model I/O.

`status.source_view` must obtain a structural session when it owns one and treat `selected_managed_generations` as representation. This keeps an authorized, valid, empty active generation visible with zero counts while omitting a policy-denied or tombstoned empty source. Render the Source control name, owner/access labels, status/stage/error/progress, and created timestamp. Do not synthesize `"Managed source"` or force `status="ready"`.

All public counts come from the held graph and its exact provenance:

- passages: current graph passages owned by the source;
- fact links: each retained Fact-to-passage support belonging to the source;
- symbol/data/commit counts: unique code nodes contributed by that source's `StructuralCodeEvidence` or `StructuralObjectEvidence`, including shared nodes;
- relation counts: each structural relation whose `source_generations` contains the selected pair, including relation-only support;
- languages and edge-kind breakdown: from those contributed code records/relations.

Never use raw Store Source counts for a managed public row because they span legacy, staged, active, and retained generations. Validate the held session after DTO construction.

### Production query-session activation

Make structural generation selection the internal default by changing `query_access(..., structural=True)` and `query_session(..., structural=True)`. Keep `AppContext.graph_for(..., structural=False)` unchanged as the explicit low-level legacy default. Existing named callers may still pass `structural=False` only in a documented compatibility/test path; production route ownership must not.

After this switch, audit every `query_session`, `query_access`, `ctx.graph_for`, and `ctx.graph` call. Classify it as follows:

- Model/dense retrieval owner: use `retrieval_session` or wrap its one borrowed structural `QuerySession` with `retrieval_session(..., session=session)`. This includes `ask.py`, HTTP `/api/ask` and `/api/search`, MCP ask/search, local CLI ask, analysis simulation, graph light-up, evaluation runner, and the static RAG-all evaluator. The lower layer must never reacquire a graph when a session was supplied.
- Graph/source/citation/status/code-only owner: hold structural `query_session` through DTO/render/save. This includes pages, sources, status, account/user source views, code routes/tools, graph browse, changeset/eval access, question-maker passage reads, render helpers, and MCP sources/code tools.
- Local CLI code and source listing: replace unrestricted `ctx.graph()`/raw `list_sources()` presentation with one structural session and the same shared payload/source-view functions. Administrative commands may retain explicit unrestricted store operations, but must not use them as query evidence.

Every response is produced and validated within the same owner lifetime. Do not perform a graph/profile preflight, close it, then reacquire for retrieval. Graph-only/status operation remains functional when Ollama metadata and model endpoints are unavailable. Model-based routes resolve only the profiles of authorized contributing evidence.

### Safe transport failures

Add `src/hippo/knowledge/public_errors.py` with a closed pure mapping from known activation exceptions to `PublicFailure(code, message, http_status)`. It must not serialize arbitrary exception text.

Required mappings:

| Condition | Code | HTTP | Public message class |
|---|---|---:|---|
| mixed/unverified/invalid dense evidence; stored profile mismatch/change | `retrieval_rebuild_required` | 409 | Rebuild compatible sources before retrieval |
| model metadata/embed/chat unavailable or timeout | `retrieval_unavailable` | 503 | Retrieval service is unavailable |
| build actor/authorization/suppression changed | existing authorization response | 409/403 | Current generic permission response |
| invalid client input/unsupported type/size | `invalid_source` | 400/413 | Existing bounded validation text from closed input validators only |
| unknown managed build/query exception | `operation_failed` | 500 | Operation failed; inspect local logs by operation ID |

FastAPI, MCP `ToolError`, remote client, and CLI stderr must use the same stable code/message. Preserve existing response shapes where clients already depend on them; add `code` without returning private details. Background managed build failures use the same code in Source state. Legacy validation routes retain their current messages. Tests must inject exception strings containing secrets, absolute paths, source text, and model bodies and assert none reaches logs captured at public level, Source rows, JSON, MCP, or CLI.

## Invariants that block the activation

The implementation is incomplete if any of these is false:

1. A managed source never enters `_clear_passages`, `Store.delete_source`, legacy source cleanup, orphan sweeping, or source-directory removal.
2. Current suppression commits before delete returns and invalidates in-flight current sessions. Published/retired history and raw bytes remain untouched.
3. G1 serves during G2 refresh and after G2 failure. Only atomic publish changes the active pointer/counts.
4. Every production query uses structural generation selection; every dense/model query uses the dense dispatcher from that same held owner.
5. Hidden, suppressed, staging, failed, or policy-denied evidence cannot affect routing, model resolution, source visibility, counts, scores, traces, or errors.
6. Empty authorized active generations appear in source inventory with zero counts and no Ollama call.
7. Real readers are backed by current local WorkspaceMembership and Source authority. Open/preview identities cannot create, refresh, or delete managed evidence.
8. Raw roots are configured below the absolute data directory, created only for managed ingest, and retained by delete/reindex.
9. Bulk mode preflights all managed authority before any legacy clear and never resurrects tombstones.
10. Ladybug reopen preserves source pointers, tombstones, fences, memberships, manifests, counts, and query behavior. Neo4j implements the same transitions without weakening lock/epoch checks.

## Implementation tasks and file ownership

Every task starts with failing behavioral tests. Shared files are owned sequentially; parallel workers must not edit the same files.

| Task | Gates | Exclusive files | Required result |
|---|---|---|---|
| 1. Local identity mapping and managed tombstone primitive | PA1, PA4, PA7 | `src/hippo/store/knowledge.py`, `src/hippo/store/generations.py`, `src/hippo/store/users.py`, `src/hippo/store/ladybug.py`, `src/hippo/store/__init__.py`, NEW `src/hippo/knowledge/source_lifecycle.py`, NEW `tests/unit/test_local_workspace_membership.py`, NEW `tests/unit/test_managed_source_lifecycle.py` | Idempotent reviewed local memberships; atomic current suppression/fence; retained generations/raw paths; no managed legacy cleanup. Test Fake first, then Ladybug reopen. |
| 2. Exact empty-generation projection and source inventory | PA2, PA6, PA7 | `src/hippo/hipporag/graph_index.py`, `src/hippo/knowledge/projection.py`, `src/hippo/knowledge/replay.py`, `src/hippo/context.py`, `src/hippo/status.py`, `tests/unit/test_structural_loading.py`, `tests/unit/test_status_access.py`, NEW `tests/unit/test_managed_source_inventory.py` | Authorized selected generation pairs survive scope/compose/dense replacement/fingerprint; empty sources appear; all counts use current graph provenance; no hidden-policy inventory leak. |
| 3. Managed pipeline adapter and lifecycle dispatch | PA1, PA3–PA5, PA7 | NEW `src/hippo/ingest/managed_activation.py`, `src/hippo/ingest/pipeline.py`, `src/hippo/ingest/readers.py`, `src/hippo/config.py`, `tests/unit/test_ingest_pipeline.py`, `tests/unit/test_ingest_concurrency.py`, NEW `tests/unit/test_managed_pipeline_activation.py` | Authenticated text/plain add and conversion/refresh use coordinator; unsupported/open/direct defaults stay legacy; failures are private; mixed bulk preflights and clears only legacy. |
| 4. Actor propagation and production session/error activation | PA1, PA5–PA7 | NEW `src/hippo/knowledge/public_errors.py`, `src/hippo/knowledge/query_access.py`, `src/hippo/ask.py`, `src/hippo/status.py` after task 2 releases it, `src/hippo/web/app.py`, `src/hippo/web/auth.py`, `src/hippo/web/routes/api.py`, `src/hippo/web/routes/analyze.py`, `src/hippo/web/routes/code.py`, `src/hippo/web/routes/graph.py`, `src/hippo/web/routes/pages.py`, `src/hippo/web/routes/sources.py`, `src/hippo/web/routes/users.py`, `src/hippo/web/render.py`, `src/hippo/mcp_server.py`, `src/hippo/cli.py`, `src/hippo/remote.py`, `src/hippo/analysis/simulate.py`, `src/hippo/evals/runner.py`, `src/hippo/evals/question_maker.py`, `src/hippo/evals/rag_all.py`, `src/hippo/knowledge/eval_access.py`, `src/hippo/knowledge/changeset_access.py`, NEW `tests/unit/test_managed_route_activation.py` plus affected existing route/MCP/CLI/eval tests | All ingress actors come from the current boundary identity; one structural owner per response; all model routes use dense dispatch; graph routes work offline; failures are stable and private. Use an `rg` audit to account for every low-level graph/session call. |
| 5. Integrated persistence, regression, and independent review | PA7, PA8 | This plan and `ai_docs/gates/rag-it-all/task-5-production-activation/GATES.md` only | Run the complete ledger with Ladybug as the primary acceptance backend. Run Neo4j parity only against a reserved isolated database. Record independent SPEC and QUALITY findings and rerun affected gates after fixes. |

## Wiring manifest

```text
web page/API principal ─┐
HTTP/stdio MCP principal ├─> BuildActor.reader ─> pipeline add/reindex/delete
remote CLI HTTP ─────────┤                              │
local CLI HIPPO_TOKEN ───┘                              ├─ eligible text/plain ─> managed_activation ─> build_plain_source
explicit internal caller ──> BuildActor.trusted_local ──┤
                                                        └─ unsupported/actorless unmanaged ─> legacy pipeline

managed delete ─> source_lifecycle ─> one transaction:
  fence active builder + cancel exact unpublished generation + current-only source suppression
  + retained Source status
  (no passage/code/raw/file/generation deletion)

all production readers ─> structural query_session (one owner)
  ├─ graph/source/status/code DTOs directly
  └─ ask/search/analyze/eval ─> retrieval_session over same owner ─> verified/tag-compatible dense execution

selected Source pointer + exact authorized manifest revision
  ─> GraphIndex.selected_managed_generations
  ─> empty-source visibility + generation-aware status/counts + audience fingerprint
```

## Adversarial acceptance cases

- Create users before and after upgrade; repeated startup does not change epochs. Disable/change/delete a user or remove `local` authority during capture, embedding, write, or publish; the attempt cannot publish or return output.
- Authenticated pasted text and `.md` upload publish strict managed G1. Open mode and an old library call remain legacy. Authenticated `.pdf`, `.py`, zip, repo, and sample remain legacy. A managed source with no actor raises before any legacy delete hook.
- Refresh while G1 is queried, fail at every coordinator boundary, cancel during blocked model I/O, and race tombstone against G2 publication. G1 remains stable unless suppression committed; after suppression no current result is dispatchable.
- Monkeypatch `delete_source`, source-wide passage/code cleanup, orphan sweep, `rmtree`, generation collect/discard, and any raw unlink to raise. Managed refresh/delete/bulk still succeed in their intended control transitions without calling them; unrelated sources remain byte-for-byte/evidence-identical.
- Publish a valid exact empty generation. The authorized owner and an allowed reader see the Source with its control name and zero counts; a denied reader and current view after tombstone do not. No profile/model HTTP occurs solely because the generation is empty.
- Give one shared code object and one relation support from multiple generations. Counts attribute the object/relation to every exact contributing selected source without duplicating global graph nodes. Retired/staging contributions do not inflate current counts.
- Mixed bulk contains a managed refresh, eligible legacy conversion, unsupported legacy repo/archive, and tombstone. Failed managed preflight makes zero mutations. Successful preflight clears only legacy lanes, skips tombstone, preserves managed G1, and returns no hidden source breakdown.
- Run ask/search/analyze/light-up/evaluation with verified managed, tag-compatible legacy, mixed-profile, hidden wrong-profile, code-only, relation-only, and empty corpora. Assert one acquisition/heartbeat/finalizer and the dense dispatch expected for actual authorized contributors.
- Block Ollama `/api/show`, embedding, and chat. Source/status/code/graph endpoints and local source/code CLI still work. Dense/model endpoints return stable safe failures and no private exception text.
- Restart Ladybug after managed publication, failed refresh, and tombstone. Verify pointers, membership, suppression epoch, source visibility, raw references, and history. Repeat atomic/parity cases on isolated Neo4j before declaring scale compatibility.

## Rollout and rollback boundary

Activation is one code/config behavior change with no background conversion sweep. Existing unmanaged sources remain legacy until an authorized eligible reindex. New authenticated text/plain ingestion opts in automatically; open mode stays legacy. This avoids rewriting existing evidence without an explicit source operation.

Rollback disables new managed dispatch and dense route activation while preserving schema-5 records and current suppressions. It must never launch an older binary that cannot recognize the current schema, clear managed sources, repoint generations, or remove raw data. A managed Source can continue to serve through the reviewed structural/dense reader even when new managed builds are disabled. Restoration and physical deletion require their separate ledgers.

## Completion checklist

- [ ] PA1–PA8 are implemented and recorded in the gate ledger.
- [ ] The low-level graph/session call-site audit has no unclassified production caller.
- [ ] Managed destructive-operation spies prove zero source-wide cleanup and zero raw/file removal.
- [ ] Empty-generation visibility and multi-source provenance counts pass on Fake and Ladybug.
- [ ] Failure redaction passes across Source rows, logs, HTTP, MCP, remote CLI, and local CLI.
- [ ] Ladybug close/reopen tests pass; Neo4j parity evidence is recorded from an isolated reservation.
- [ ] Independent SPEC and QUALITY review have no unresolved findings.
