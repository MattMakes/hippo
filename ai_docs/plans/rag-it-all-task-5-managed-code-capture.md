# RAG-it-all Task 5: managed capture of code repositories

**Status:** proposed implementation contract for root review. Nothing here is implemented and no
production route is activated by this document. The plain-prose coordinator
(`ai_docs/plans/rag-it-all-task-5-prose-coordinator.md`), the production activation plan and the
storage contract are prerequisites and are not reopened by this plan.

## 1. Outcome and scope

One authenticated, explicitly invoked operation converts a repository, an archive or a single code
file from the legacy pipeline to managed generations, with every guarantee the plain-prose lane now
has: immutable accepted inputs, detached preparation, legacy evidence serving until the first
publication, fenced refresh with G1 serving, non-collecting failure, exact
`GenerationEvidenceMember` closure, original spans with real locators, no source-wide cleanup,
tombstone rather than deletion, one structural owner per query, and verified or tag-compatible
dense dispatch.

**In scope.** Sources of kind `repo` (a cloned checkout), `archive` (a ZIP of a tree) and `file`
whose stored name is a code name (`readers.is_code_name`), together with the plain-prose and
unparsed text files those trees contain; the code graph (symbols, data objects, edges,
`DEFINED_IN`); and git history (commits, `MODIFIES`, `PRECEDES`) with the Task 5A temporal fields.

**Out of scope.** Rich documents (PDF/DOCX/EPUB/HTML) and their block model, a separate plan; Task 6
blocks and the local import adapter; connectors and provider identity (Tasks 9–11); cross-source
bindings and the typed assertion vocabulary (Task 12); purge, retention and restore (Task 9A);
endpoint extractors (master plan §6.2); retrieval fusion (Task 13). No new predicate is written
into `knowledge/predicates.py`.

## 2. Existing seams

| Seam | Use or required boundary |
| --- | --- |
| `codegraph/extract.py:51` `extract_code` | Already takes `node_namespace` and `syntax_cache`. Use unchanged; managed callers pass the generation namespace. |
| `codegraph/syntax_cache.py:73` `cache_key`, `:154` `SyntaxCache` | Rematerialises objects and native IDs for the requested namespace and reruns source-wide resolution. Cached IDs are never trusted. A cache hit is coverage, never generation identity. |
| `codegraph/resolve.py:152` `build_index` | Whole-source resolution. Recomputed for every generation; per §7.3 partial reuse is not safe. |
| `codegraph/model.py:110,:122,:130` `symbol_id`/`data_id`/`commit_id`; `:39-41` the three `CODE_MAX_*` rails | Namespaced native IDs — `store/generations.py:1182` already re-derives and rejects a mismatch — and the existing safety rails, reused as the managed ceilings. |
| `codegraph/git_history.py:192` `read_history`, `:124` `History` | Commits/`MODIFIES`/`PRECEDES` in store-row shape, plus `skipped` and `truncated`. Consume its output; do not reimplement diffing. |
| `ingest/repos.py:59` `clone_repo`, `:115` `walk_repo` | Clone and tree walk. `walk_repo` produces `Document`s only; managed capture needs paths and bytes, so it is a reference, not the capture path. |
| `ingest/readers.py:58,:63,:145,:189,:215,:262` | `PROSE_EXTENSIONS`, `CODE_EXTENSIONS`, `is_code_name`, `is_plain_prose_name`, `read_file`, `read_zip`. Eligibility reuses these predicates; capture reuses byte reading and budgets. |
| `ingest/chunker.py:70` `chunk_documents`, `:92` `_chunk_commits` | Symbol-aware chunking and one synthesized passage per commit. Legacy behaviour is the parity target; its generated text is not an original span. |
| `ingest/pipeline.py:158` `add_repo`, `:370` `_read_chunk_index`, `:449` `_read_history`, `:504` `read_source`, `:74` `MAX_CHUNKS` | The legacy lane. `add_repo` accepts no `build_actor` today. `_read_history` is the legacy history pass to replace for managed sources. |
| `hipporag/indexer.py:151` `index_source`, `:279-281`, `:434` `_write_code_graph`; `hipporag/preparation.py:69` `prepare_code_rows` | Legacy code writes plus the global side effects (`set_meta("embed_model")`, `set_meta("embedding_dim")`, `bump_graph_version`) that staged writes must not perform; `prepare_code_rows` is the store-free row/vector/name preparation already extracted for reuse. |
| `store/code.py:362,:406,:424,:453,:468,:482,:687` | `add_symbols`, `add_commits`, `add_code_edges`, `link_definitions`, `add_modifies`, `add_precedes`; `delete_code_nodes_for_source` is source-wide and must never run for a managed attempt. |
| `store/generations.py:1274` `native_write`, `:1363` `native_mutation` | Enforce generation ownership, payload immutability and the cross-generation relationship rule. **Both scan whole native tables per call**; see §8. |
| `store/generations.py:590` `_native_relationships`, `:673` `generation_checksums` | Already seal `CODE_EDGE`, `DEFINED_IN`, `MODIFIES`, `PRECEDES`, `REFERS_TO` and the native Symbol/DataObject/Commit rows, and require every native row to have a `NativeBinding` and every binding a selected `ObjectObservation`. Both are whole-database scans today. |
| `store/generations.py:190` `claim_generation_build`, `:298` `fail_generation_build`, `store/snapshots.py:346` `recover_generation_builds` | Fenced claim, non-collecting failure and expired-lease recovery. **Recovery marks an abandoned staging generation `failed`, and reclaiming a `failed` generation collects its rows** (`generations.py:241-247`); see §8. |
| `knowledge/lifecycle.py:15,:68,:73`; `knowledge/identity.py:157,:264,:276` | `generation_for_inputs`, `generation_namespace`, `generation_passage_id`, `repository_identity`, `symbol_key`, `symbol_identity` — the canonical managed identities. Use unchanged. |
| `knowledge/model.py:289,:341,:448,:490,:608` | `Artifact` (already has `repository` and `history_event` kinds), `ArtifactRevision` (`provider_revision`, `source_updated_at`, `source_precision`, `observed_at`), `KnowledgeObject` (already has `repository`, `file`, `symbol`, `commit`), `ObjectObservation` (`TemporalRecord`), `NativeBinding`. No schema change is required. |
| `knowledge/projection.py:600-623`; `knowledge/dense.py:156,:171` | Projection derives `DEFINED_IN` from an observation's span matching a passage entry and emits `StructuralCodeEvidence` per contributing source generation; the writer's job is to make those bindings exist. See §4 for why `StructuralRelationEvidence` stays empty here. |
| `knowledge/staged_prose.py:69,:129,:190,:211` | The writer template. `_inventory` at `:187` explicitly requires the native code/relationship inventory to be **empty**, so the code lane needs its own writer, not a flag on this one. |
| `knowledge/input_binding.py:294` `_view`, `:348` `materialize_chunk_evidence` | The rendered-view pattern (`RetrievalView` + `DerivedRecord` + `DerivedDependency` over original spans) that generated code/commit text must reuse. |
| `ingest/prepared_chunks.py:371`, `ingest/provenance.py:322` | `prepare_prose_chunks` and `read_plain_provenance` both **reject code**; new sibling seams are required. |
| `ingest/accepted_inputs.py:170` `capture_raw_inputs`, `knowledge/inputs.py:43,:56` | Bounded canonical capture over `ByteInput`/`FileInput`. Reused unchanged for a tree. |
| `ingest/prose_generation.py:621` `build_plain_source`, `knowledge/build_authority.py:340` `capture_build_authority`, `knowledge/lease_heartbeat.py` | The coordinator template, the authority primitive and the renewal worker. |
| `ingest/managed_activation.py:111` `managed_eligibility`, `:166` `plan_dispatch`, `:219` `build_options`, `:465` `run_managed_build` | The activation adapter to extend. Eligibility is closed and decided on the Source row alone. |
| `context.py:171-173`, `status.py:58-59` | **A source leaves the legacy lane as soon as any `Artifact` or `Generation` row names it**, while the managed lane contributes nothing until `active_generation_id` is set (`context.py:215-219`); see §7. |

Two seams named in the brief do not exist as described. `write_commit_history` is
`tests/fakes/code_fixture.py`, a test fixture, not a production writer: production history writes
are `store.add_commits` / `add_modifies` / `add_precedes` through `indexer.py:448-450`. There is no
`git_history` module under `hipporag`; it is `codegraph/git_history.py`.

## 3. Public API

Create `src/hippo/ingest/code_generation.py` with a coordinator separate from
`build_plain_source`:

```python
def build_code_source(
    ctx,
    *,
    source_id: str,
    actor: BuildActor,
    tree: CodeTreeInput,
    options: CodeBuildOptions,
    raw_store: RawArtifactStore,
    embedding_spec: EmbeddingSpec,
    operation_id: str,
    should_stop: Callable[[], bool],
    on_progress: Callable[[BuildProgress], None] | None = None,
) -> BuildReceipt: ...
```

Reasons for a separate entry point rather than widening `build_plain_source`: prose bootstrap is a
single detached commit with no durable reservation, while a repository bootstrap is durable staging
over many commits with resume (§6); prose rejects code by contract at three reviewed seams
(`prepare_prose_chunks`, `read_plain_provenance`, `staged_prose._inventory`); and the reviewed
prose gates PC1–PC8 would all have to be reopened. The two coordinators share `BuildActor`,
`BuildAuthority`, `LeaseHeartbeat`, `RawArtifactStore`, `BuildProgress` and `BuildReceipt`, and the
shared `_Run` failure latch is factored into `src/hippo/ingest/build_run.py` so neither owns it.

`CodeTreeInput` is frozen and carries: the absolute checkout/extraction root; the ordered tuple of
normalized relative paths to capture; the source kind (`repo`, `archive`, `file`); the repository
descriptor (§5); and the resolved head commit SHA or `None`. `CodeBuildOptions` is frozen and
carries the input-affecting configuration (chunk size/overlap, synonymy threshold, history depth,
walker/grammar profile, exclusion and empty policy) separately from the operational scheduling
limits (batch size, checkpoint interval, lease duration and renewal interval, worker count,
ceilings from §8). Only the first group enters generation identity. `BuildReceipt` gains
`resumed_from_batches: int` and is otherwise unchanged; it still names no path, no text and no
exception body.

New modules, all with focused tests and one owner each: `ingest/repo_capture.py`,
`ingest/code_provenance.py`, `ingest/prepared_code_chunks.py`, `knowledge/code_binding.py`,
`knowledge/code_history.py`, `knowledge/staged_code.py`, `ingest/code_generation.py`,
`ingest/build_run.py`.

## 4. What a code generation contains

`generation_checksums` already accepts every record below; no schema change is proposed.

- **Accepted inputs.** One `Artifact(kind="repository")` (or `kind="file"` for a single code file)
  for the tree, one `Artifact(kind="file")` per captured file, one
  `Artifact(kind="manifest", external_id="accepted-inputs-v1")`, and one
  `Artifact(kind="history_event")` per commit. Each with one immutable `ArtifactRevision`.
- **Originals.** One `EvidenceSpan` per contributing original region, `locator_kind="file_lines"`,
  with real start/end lines from `code_provenance` — never a synthetic whole-file span.
- **Rendered views.** Every passage whose text is not byte-identical to one original region is a
  `RetrievalView` + `DerivedRecord` + `DerivedDependency` over its originals, exactly as
  `input_binding._view` does for prose. This covers the chunker's generated context header, the
  data-object mention passages and every commit passage (`chunker.py:92`), whose text is a
  synthesized message-plus-symbol-names rendering.
- **Objects.** `KnowledgeObject` of kind `repository`, `file`, `symbol`, `commit` and the schema
  kinds for SQL data objects, keyed with `identity.repository_identity` and `identity.symbol_key`.
  One `ObjectObservation` per object per span, carrying the attributes the projection renders
  (`name`, `path`, `kind`, `doc`, `signature`, `lang`, `is_test`, community label).
- **Native rows and bindings.** `Symbol` / `DataObject` / `Commit` rows carrying `generation_id`
  and the namespaced ID, each with a `NativeBinding` to its `KnowledgeObject` and span. The store
  re-derives every native ID from the generation namespace and rejects a mismatch
  (`generations.py:1238-1257`). The obligation runs one way only: `generation_checksums:789-792`
  requires a binding for every native row, and `:751-767` requires a selected observation for every
  binding, but a `KnowledgeObject` may have observations and no native row at all. `repository` and
  `file` objects are exactly that case and seal correctly without one.
- **Native relations.** `CODE_EDGE`, `DEFINED_IN`, `MODIFIES`, `PRECEDES` and `REFERS_TO` written
  through the existing writers under the generation fence. `_native_relationships` already seals
  them into the `native` representation and `native_mutation` already refuses a relationship whose
  endpoints belong to different generations.
- **Dense.** One `Passage` per chunk with `generation_id`, `span_id`, `artifact_revision_id`,
  `retrieval_view_id` where rendered, and a vector from the verified profile.

**Code relations stay native; this lane writes no `Assertion`.** `knowledge/predicates.py:66`
registers no `CONTAINS`/`IMPORTS`/`INHERITS`/`OVERRIDES`/`INVOKES`/`RAISES`/`CATCHES`/`TESTED_BY`/
`READS`/`WRITES` predicate, and master plan §5.3 states that existing code relations remain in
`CODE_EDGE`. Consequently this lane populates `StructuralCodeEvidence` (from the object/span/
generation bindings, via `projection.py:611`) and `StructuralObjectEvidence` for SQL data objects,
and populates **no** `StructuralRelationEvidence`: that channel is `AssertionSupport`-backed and
belongs to Task 12's typed bindings. The brief's phrasing implies otherwise; see §11.

**No `SYNONYM` writes and no post-seal `set_symbol_communities`.** §7.3 forbids staged or retired
code entering a published synonym projection, and the managed projection already computes cosine
synonyms at read time. The community label is computed during preparation
(`indexer.module_communities`) and written in the `Symbol` row before the seal.

**OpenIE is not applied to code.** Plain-prose files inside a captured tree go through the shared
prose path and do receive extraction; every code, config and unparsed file records
`openie: "skipped"` in `coverage_json` and produces no `ProseExtraction`. The seal is valid without
one: `generation_checksums:719-724` requires dense coverage only for nonempty exact text.

## 5. Identity

- **Repository.** `repository_identity(workspace, provider_instance, provider_repository_id)`.
  Until a connector supplies provider IDs (Task 10), use the normalized clone URL's host as the
  provider instance and its normalized `owner/name` path as the repository ID; master plan §5.2
  already treats URLs as aliases of the true identity, so a later connector adds an alias rather
  than renaming evidence. An archive or single file has no repository: it uses the source-scoped
  local identity `local_artifact_identity` and a repository key of `source:<source-id>`.
- **Generation.** `generation_for_inputs` over every accepted artifact/revision pair plus the
  manifest pair, the captured configuration and the expected parent. The head commit SHA enters
  identity as the repository revision's `provider_revision`; the per-file content hashes enter as
  their own revisions. The captured configuration records `parser_version` and `linker_version` on
  the `Generation`, and inside `configuration_json`: `syntax_cache.WALKER_RULES_VERSION`, the
  `syntax_cache.parser_profile(grammar)` tuple for every grammar used, `syntax_cache.SCHEMA_VERSION`,
  the effective chunk size/overlap after the chunker's clamp, the history depth, the synonymy
  threshold and the exclusion/empty policy. Operational limits, worker count, progress, clone depth
  and observation timestamps do not enter identity.
- **Symbols.** `symbol_key(repository, language, path, qualified_name, signature, kind=...)`. The
  signature discriminator is supplied where the walker produced one, so overloads do not merge
  (§5.2). Native IDs remain `codegraph.model.symbol_id(..., node_namespace=generation_namespace)`.
- **Commits.** `KnowledgeObject(kind="commit")` keyed by repository plus SHA; native
  `commit_id(source_id, sha, node_namespace=...)`.

## 6. Deterministic preparation

All of it runs outside every write transaction, with the build guard checked before and after each
step and before any text reaches a model.

1. Resolve `ResolvedEmbeddingProfile` (and `ResolvedOpenIEProfile` only if prose files were
   captured) with live guards; keep safe descriptors only.
2. Enumerate. `repo_capture.walk_tree(root)` returns the ordered, normalized relative paths under
   `readers.IGNORED_DIRS`, applies `CODE_MAX_FILES` and the per-file byte cap, and classifies each
   path as `code`, `prose`, `excluded` (with an explicit reason) or `unsupported`. Symlinks,
   non-regular files and paths escaping the root are refused, not skipped.
3. Capture. Pass the complete inventory to `capture_raw_inputs` unchanged; the manifest excludes
   itself. Every subsequent read is from the captured raw object, never the live checkout, through
   `code_provenance.read_code_source(...)` — the code-accepting sibling of `read_plain_provenance`
   with the same decode, trim and complete-line locator behaviour, where rich and binary outcomes
   still refuse.
4. Extract. `extract_code(docs, source_id, node_namespace=generation_namespace(gen), syntax_cache=...)`
   then whole-source resolution. Cache hits rematerialise; cached IDs are never trusted.
5. History. `read_history(checkout, code.symbols, source_id, depth=..., ...)` against the captured
   checkout, then `code_history.bind_history(...)` (§9).
6. Chunk. `prepared_code_chunks.prepare_code_chunks(...)` wraps `chunk_documents(..., code=code)`
   and maps every emitted chunk to its exact original line ranges plus its generated segments, the
   contract `PreparedChunk` already expresses for prose. Seeded parity against the committed legacy
   chunker is required, as the prose slice did with 2,000 cases: managed chunk text must equal
   legacy chunk text for the same inputs.
7. Bind and embed. `code_binding.materialize_code_evidence(...)` turns prepared chunks plus the
   resolved `CodeGraph` into the §4 inventory — pure, with no store handle, no model and no clock
   beyond the one injected capture instant — then one vector per chunk and per code node is
   produced through the verified profile and the disposable `EmbeddingCache`, batched, outside
   transactions.

## 7. Legacy serving during a multi-commit bootstrap

`context.py:171-173` and `status.py:58-59` classify a source as managed on the presence of any
`Artifact` or `Generation` row, while `context.py:215-219` selects managed evidence only when the
Source has an `active_generation_id`. A repository bootstrap that stages over many transactions
therefore makes the legacy repository **disappear from every query** the moment its first staging
record commits. The prose lane never hits this because it installs and publishes in one
transaction; a 1,000-file repository cannot.

The fix is one narrow, testable predicate rather than a shadow source: a source keeps serving its
legacy evidence while it has no published generation. Add
`store.source_serves_legacy(source_row) -> bool`, true when the Source has `managed` false, no
`active_generation_id`, and no `IndexEvent(kind="published")` for any of its generations. Use it in
`context._build_managed_graph` and `status.system_status` in place of the current
Artifact/Generation presence test. Staging records are already invisible to selection, so a
converting source serves exactly its old legacy graph and nothing else.

`begin_managed_source` (which sets `managed=True` and bumps the authorization epoch) is therefore
**not** called at staging start. It runs inside the publication transaction, together with the
active pointer, the source presentation and the counts — the same atomic swap the prose bootstrap
performs, only reached after the staged content already exists.

**Refresh differs from bootstrap in exactly three places.** It claims a fenced build before any
inference, as prose does, because the source is already managed and a concurrent builder must be
excluded. Its serving guarantee comes from G1 remaining the active pointer, not from §7. And it
publishes with `expected_parent_id=G1` rather than `None`. Everything else — capture, extraction,
chunking, binding, batching, resume, seal — is the same code path, which is why the coordinator has
one preparation phase and two admission phases rather than two pipelines.

## 8. Staged writing at scale

### 8.1 The scale defect that blocks this task

Three reviewed store helpers are whole-table or whole-database scans:

- `native_write` (`generations.py:1283`) materialises **every** row of the kind on every call.
- `native_mutation` (`:1384`) materialises every row of all six native kinds on every call.
- `_native_relationships` (`:590`) enumerates every relationship of eleven kinds in the database,
  and `generation_checksums` (`:673`) canonically hashes the result.

A 1,000-file repository is up to `CODE_MAX_SYMBOLS_PER_SOURCE` symbols and several times that many
edges. Writing them in batches of 128 is roughly 400 full scans per representation, which is
quadratic in the corpus and will not hold the contract on Neo4j at scale. The checkpoint already
records the related concern ("typed ID reads currently decode full record tables; optimize
parameterized lookup before scaling", 2026-09-11, Task 3 final).

Task CC2 is therefore a hard prerequisite, not an optimisation: add generation-scoped, parameterised reads
(`_native_rows(kind, *, generation_id=None, ids=None)`,
`_native_relationships(ids, *, generation_id=None)`,
`_knowledge_rows(kind, *, generation_id=None)`) on all three backends and the fake, make
`native_write`, `native_mutation` and `generation_checksums` use them, and prove equal results and
bounded query counts. Public behaviour and every existing checksum stay byte-identical.

### 8.2 Batching, checkpoints and resume

The staged code writer `knowledge/staged_code.py` mirrors `staged_prose.py`: a pure
`_write_batches(prepared, *, batch_size)` generator of complete dependency groups, a callback-free
`_write_batch(store, prepared, batch, **authority)`, an `_inventory` and a `_seal`, plus the public
`write_staged_code(...)` wrapper that refuses an ambient transaction. Differences:

- Batch groups are ordered accepted preflight → revision members → repository/file objects →
  original spans → derived views → dense passages → native code rows and bindings → native
  relations → history. A relation group is emitted only after both endpoints, so a partial run
  never leaves a dangling edge.
- `_inventory` is the inverse of the prose one: it requires the exact `Symbol`/`DataObject`/
  `Commit` rows, `NativeBinding`s, `ObjectObservation`s and native relations for this generation,
  and requires that no other generation's rows are present. It reuses the scoped reads of §8.1.
- Between batches, and never inside `generation_write`, the coordinator renews the lease, invokes
  the external `check` and reports progress. Every batch re-validates the expected authorization
  and suppression epochs inside its own short transaction, exactly as prose does.

**Resume.** `recover_generation_builds` (`snapshots.py:378-380`) marks an abandoned staging
generation `failed`, and `claim_generation_build` (`generations.py:241-247`) then **collects** the
failed generation's rows before returning it to `staging`. Under that behaviour a crashed
repository build always restarts from zero, so "resumable" is not achievable without a store
change. Task CC3 adds one:

```python
def reclaim_generation_build(
    self,
    generation_id,
    *,
    job_key,
    lease_owner,
    lease_expires_at,
    expected_manifest_hash,
): ...
```

It admits only a never-published `staging` or `failed` generation whose `manifest_hash` equals
`expected_manifest_hash`, takes the source lock, advances the fence, installs a fresh holder and
returns the generation to `staging` **without collecting**. Any other caller, and any mismatched
manifest, keeps today's collect-then-stage `claim_generation_build` semantics untouched, so the
reviewed prose retry contract does not change. Because `manifest_hash` is input-only, identical
accepted inputs produce the identical generation ID, so a retry either matches exactly or is a
different generation.

Replay is idempotent by construction: `native_write` already skips a prior identical managed row
(`generations.py:1302-1315`), `put_knowledge` accepts an equal record, and the batch plan is a pure
function of the prepared output. The resume checkpoint is therefore the store's own rows, not a
side file: the coordinator probes each batch group's records with one scoped read and skips a group
whose inventory already matches. `BuildReceipt.resumed_from_batches` reports how many were skipped.
A conflicting persisted row (same ID, different payload) is not overwritten; it fails the build and
requires the explicit failed-generation cleanup path.

**Long-build authority.** A repository build outlives many unrelated permission mutations, and a
frozen epoch equality would abort it whenever any user logs a role change. Between batches, under
the authorization and source locks, the guard may call one new bounded operation
`BuildAuthority.rebaseline()`: it re-runs `check_local()` in full and, only if the actor still has
every capability it started with, adopts the current epochs as the new expected baseline. It is
refused inside `generation_write`, after any sticky failure, and after a suppression that applies
to this source. This is strictly the `check_local()` proof, not a reset; it is listed in §11 as a
decision to rule on.

### 8.3 Ceilings

Managed ceilings reuse the existing safety rails rather than inventing numbers: `CODE_MAX_FILES`
(5,000) captured files, `CODE_MAX_SYMBOLS_PER_SOURCE` (50,000) symbols, `CODE_MAX_FILE_BYTES`
(512 KiB) per parsed file, `MAX_CHUNKS` (20,000) passages, and the existing raw and decoded
budgets — all operational settings outside representation identity. The prose bootstrap's
1,000-chunk / 50,000-record / 64 MiB single-transaction ceiling does not apply because a code
bootstrap is not one transaction; a per-batch canonical payload ceiling (proposed 64 MiB, the same
unit) applies instead. Exceeding a ceiling refuses the build before capture; it never truncates
silently and never installs a partial generation as authoritative.

## 9. Temporal fields for commits and file revisions

One capture instant is taken from the store clock at the start of the operation and threaded
through every record; no record calls `now()` itself and there is no wall-clock default anywhere.

| Field | Value |
| --- | --- |
| `ArtifactRevision.observed_at` (file, repository, manifest) | the one capture instant |
| `ArtifactRevision.source_updated_at` (file) | `None`; a working-tree mtime is not provider truth |
| `ArtifactRevision.provider_revision` (repository) | head commit SHA; (file) `None` for v1 |
| `ArtifactRevision(kind="history_event").source_updated_at` | the commit's git author date |
| `ArtifactRevision.source_timestamp_original` / `source_timezone` | the raw `%aI` string and its offset, unparsed |
| `ArtifactRevision.source_precision` | `"second"` |
| commit `ObjectObservation.valid_from` / `valid_to` | author date / `None`, `validity_kind="explicit_interval"` |
| commit `ObjectObservation.temporal_basis` / `temporal_precision` | `"commit"` / `"second"` |
| commit `ObjectObservation.recorded_from` | the one capture instant; `recorded_to` stays `None` |
| symbol/data `ObjectObservation` | `validity_kind="observed_snapshot"`, `temporal_basis="observed"`, `recorded_from` the capture instant |

The legacy native history writes are replaced rather than wrapped. `pipeline._read_history`
(`:449`) mutates the `CodeGraph` in place and `indexer._write_code_graph` (`:448-450`) then calls
`add_commits`, `add_modifies` and `add_precedes` untagged; the managed lane skips both, calls
`read_history` itself in step 5 of §6, and emits the same three row shapes from
`code_history.bind_history(...)` through the staged writer under the generation fence, so each row
carries `generation_id` and the namespaced `commit_id` and is validated by
`_validate_managed_native`. Legacy behaviour for unmanaged sources is untouched.

`History.skipped`, `History.truncated`, `CodeGraph.truncated`, `files_skipped` by reason and the
shallow-clone boundary are recorded in `coverage_json`, so a partial history is never presented as
complete. A repository with `code_history_depth = 0` records `history: "disabled"` and produces no
`history_event` artifact; that is a configuration value in generation identity, so enabling history
later is a new generation rather than an append.

## 10. Failure, cancellation, idempotence, privacy

- **Failure.** `fail_generation_build` under the held fence; the staged inventory is retained for
  audited recovery. During bootstrap the legacy graph keeps serving because §7 keeps the source in
  the legacy lane until publication; during refresh G1 stays active and the Source keeps
  `status="ready"` with a `refresh_failed` stage, as the activation plan specifies for prose.
  Never any collection, `_clear_passages`, `delete_code_nodes_for_source`, `rmtree` or raw deletion.
- **Cancellation and crash.** Cancellation is cooperative, checked between batches and before each
  model call, and leaves a resumable staging generation. After a crash nothing beyond staged rows
  and orphan raw objects can remain; restart recovery clears the expired holder and §8.2's reclaim
  resumes the same generation. A retry with different inputs supersedes rather than resumes. A
  crash after the publication commit is resolved by the immutable publication receipt.
- **Idempotence.** `operation_id` resolves a prior receipt under the source lock; an accepted
  manifest equal to the active generation's returns `already_current` without inference or writes.
- **Privacy.** Absolute paths, repository URLs with credentials, source text, diff hunks, commit
  messages, model prompts and unknown exception strings never reach logs, Source rows or public
  errors; only relative logical paths enter the accepted manifest, and failures map through the
  existing `managed_activation` closed mapper and `knowledge/public_errors.py`. Model I/O is
  restricted to embedding text for code chunks and prose OpenIE for captured prose files; no code
  text is sent to a chat model by this lane.

## 11. Decisions to rule on before implementation

1. **`StructuralRelationEvidence` is not populated by this lane** (§4). If the orchestrator wants
   code edges to become typed assertions instead, `knowledge/predicates.py` needs ten new
   predicates and the projection's relation channel becomes the code channel, which is a materially
   larger change and contradicts master plan §5.3.
2. **`BuildAuthority.rebaseline()`** (§8.2). The alternative is to fail a long repository build on
   any unrelated authorization-epoch change, which makes large repositories effectively
   unbuildable on a busy instance.
3. **The legacy-serving predicate change** (§7) touches `context.py` and `status.py`, which the
   production-activation plan's Tasks 2 and 4 owned. It needs the orchestrator's confirmation that
   those files are released, and a check that no activation test asserts the current
   Artifact-presence classification.
4. **Provisional repository identity from the clone URL** (§5). Cheap and reversible via an alias,
   but it does mint identities that Task 10 must reconcile.
5. **Prose files inside a repository go through OpenIE** (§4). The alternative — skip extraction
   for everything in a code source in v1 — is cheaper and loses README facts that the legacy lane
   currently extracts, so it would be a retrieval regression.

### Orchestrator rulings (2026-09-12)

1. **Accepted.** Code relations stay native `CODE_EDGE`/`DEFINED_IN`/`MODIFIES`/`PRECEDES` sealed in the native representation; `StructuralRelationEvidence` is Task 12's typed-assertion work. The brief's contrary phrasing is withdrawn.
2. **Accepted with conditions.** `BuildAuthority.rebaseline()` may adopt a new *authorization* epoch only after `check_local()` re-proves the actor and every accepted input's policy in full under the authorization and source locks; a suppression epoch change that applies to this source refuses; it is callable only between batches, never inside `generation_write`, never after a sticky failure; every receipt records the number of rebaselines; the between-batch test proves a removed capability still aborts.
3. **Confirmed.** `context.py` and `status.py` are released (activation Tasks 2 and 4 are merged and reviewed). CC1 runs the activation regression (`test_managed_source_inventory.py`, `test_status_access.py`, `test_managed_route_activation.py`, `test_managed_web_surfaces.py`, `test_managed_web_ingress.py`) and may adapt only assertions that pin the Artifact-presence classification, naming each in its evidence.
4. **Accepted.** Provisional repository identity from the normalized clone URL; Task 10 adds provider aliases rather than renaming evidence.
5. **Accepted, bounded.** Files matching `readers.PROSE_EXTENSIONS` inside a repository go through OpenIE under the same budgets as the plain lane; code comments and docstrings are not prose inputs.

6. **Ruled during CC1 (2026-09-12).** The managed flip stays an authorization-epoch bump (the source's authorization model changes from source ACL to artifact policy plus membership, so a held legacy session must revalidate), performed inside `publish_staged_generation`'s transaction through the single `begin_managed_source` primitive; the automatic call from `store/authorization.py`'s record mutation on every Artifact/Generation put is removed, so staging rows no longer flip a source. The prose coordinator's publication accounts for that bump; code builds rebaseline across it.

7. **Ruled during CC4 (2026-09-12).** Fine-grained exclusion reasons (`ignored_path`, `binary`, `too_large`, `unsupported_language`, `symlink`, `submodule`, `not_regular`, `configured_exclusion`) live on the capture result and in `coverage_json`; the canonical accepted-input manifest keeps `ExcludedInput`'s single `configured_exclusion` disposition, so `knowledge/inputs.py` is unchanged. Symlinks, submodules and non-regular files are recorded exclusions; only a path escaping the root and a file changed during capture refuse. `read_code_provenance` delegates its decode to `read_plain_provenance` (section 2's claim that the plain reader rejects code is wrong: it decodes `CODE_EXTENSIONS` and marks `is_code`), refuses plain-prose names so those files route to the prose lane, and accepts extensionless known-text names such as `go.mod`.

8. **Ruled during CC1 (2026-09-12).** `legacy_source_cleanup` refuses when the source is managed OR any Artifact/Generation row names it: a converting source can never be wiped by legacy cleanup (a destructive-operation guard, not a lane classification). Consequences for CC9/CC10: `apply_source_tombstone` and `managed_activation.managed_eligibility` must treat a source with unpublished managed rows (staging or failed, not yet flipped) as managed for delete, reindex and bulk dispatch, so a delete during conversion tombstones and an actorless reindex during staging is refused rather than classified `eligible_legacy`.

9. **Reversal of ruling 6 and amendment of ruling 8 (design review, 2026-09-12).** The managed flag flips at staging start exactly as today (the record-mutation call stays), so `legacy_source_cleanup`, `managed_eligibility`, `tombstone_managed_source`, `_prepare_reindex` and the untagged-row barrier keep treating a converting source as managed without change. The serving lane is a separate predicate: `source_serves_legacy(source_row)` is true iff the source has no `active_generation_id` and no published `IndexEvent`, independent of the managed flag, and false when an all-principals `Suppression` targets the source (a tombstoned converting source leaves the legacy lane and the managed lane shows nothing for it: no pointer, no pair, no evidence; principal-specific suppressions remain the access layer's job). The lane decision lives one level below the loader-selection set (`context.py:~214` and `~339`, and the status twin): `managed_sources` still selects which generations to load, but an empty set must never fall through to the unfiltered legacy loader, which would serve every staged row live (review blocker B1). The prose coordinator is unchanged. CC8/CC9 must also lift `build_authority._source_control`'s `{text, file}` kind restriction and its own Artifact-presence test (review blocker B4).

10. **Ruled (design review M2, 2026-09-12).** Both halves. The derivation rule versions (code chunker rule version, code binding/view rule version, code writer version, walker and grammar versions) enter the `configuration` that `generation_for_inputs` hashes, so a changed derivation is a different generation and resume is impossible by construction; AND the resume probe asserts the ABSENCE of unexpected generation-scoped rows as well as the presence of expected ones, failing closed with a named remediation (the explicit failed-generation cleanup path). CD7 gains: "a staged generation holding a record the current derivation would not produce fails the resume rather than sealing." Each preparation module exports its rule-version constant; CC6/CC9 fold them into the configuration.
11. **Ruled (CC5 finding 3, 2026-09-12).** `readers.PROSE_EXTENSIONS` is the sole prose test in the managed lane. An extensionless prose-looking file inside a repository (README, LICENSE, CHANGELOG and the like) is an unparsed file: it is chunked as `window` passages, never sent to OpenIE, and recorded in coverage as `openie=skipped` with reason `unparsed`. No basename allow-list is introduced; ruling 5 covers only files that `PROSE_EXTENSIONS` names. The legacy lane's behaviour for such files is untouched. Two consequences ratified with it: CC5's parity latch (the committed chunker runs a second time per build and the result is refused on any byte difference) stays, and the pinned chunk fixture digest is changed only together with `CODE_CHUNK_RULE_VERSION`.

Blockers A (legacy serving until publication) and B (resumable reclaim) and the scale finding (generation-scoped reads) are accepted as prerequisites CC1–CC3. The split CC1–CC11 is adopted; CC1 and CC4 start in parallel, the rest in the stated order. An independent design review runs alongside CC1/CC4; its findings bind the later tasks.

## 12. Task split

Each task starts with failing behavioural tests, owns its files exclusively, and is sized to finish
well inside the fleet budget rule in `ai_docs/handoffs/fleet-worker-rules.md`. Shared files are
owned sequentially; the dependency column is binding.

| # | Task | Depends on | Gates | Exclusive files | Required result |
| --- | --- | --- | --- | --- | --- |
| CC1 | Legacy serving until publication | — | CD2 | `src/hippo/store/generations.py`, `src/hippo/context.py`, `src/hippo/status.py`, NEW `tests/unit/test_converting_source_serving.py` | `source_serves_legacy` beside `source_is_managed` (`generations.py:58`); a source with staging-only managed rows serves its legacy graph, appears once in inventory, and flips atomically at publication. Smallest store slice, so it holds the shared file first. |
| CC2 | Generation-scoped store reads | CC1 (file handoff) | CD1 | `src/hippo/store/generations.py`, `src/hippo/store/snapshots.py`, `src/hippo/store/ladybug.py`, `src/hippo/store/memory.py`, NEW `tests/unit/test_generation_scoped_reads.py` | Parameterised `_native_rows`/`_native_relationships`/`_knowledge_rows`; `native_write`, `native_mutation`, `generation_checksums` use them; identical checksums and bounded query counts on Fake, Ladybug and Neo4j. |
| CC3 | Resumable staging reclaim | CC2 (same files) | CD1, CD7 | the CC2 store files, released by CC2, plus NEW `tests/unit/test_generation_resume.py` | `reclaim_generation_build` with manifest equality and no collection; recovery leaves a reclaimable attempt; existing `claim_generation_build` behaviour and the prose retry gates unchanged. |
| CC4 | Repository capture and code provenance | — | CD3 | NEW `src/hippo/ingest/repo_capture.py`, NEW `src/hippo/ingest/code_provenance.py`, NEW `tests/unit/test_repo_capture.py`, NEW `tests/unit/test_code_provenance.py` | Ordered normalized tree inventory with explicit exclusion reasons and refusals; code/config decode with exact complete-line locators; reordering does not change accepted identity. |
| CC5 | Mapped code chunks | CC4 | CD4 | NEW `src/hippo/ingest/prepared_code_chunks.py`, NEW `tests/unit/test_prepared_code_chunks.py` | `prepare_code_chunks` with exact original ranges and generated segments for symbol, mention and commit passages; seeded parity against the committed legacy chunker. |
| CC6 | Code evidence and object binding | CC5 | CD5 | NEW `src/hippo/knowledge/code_binding.py`, NEW `tests/unit/test_code_binding.py` | Pure materialisation of the §4 inventory with exact membership closure, rendered views for generated text, namespaced native rows and bindings; no store, model or clock. |
| CC7 | Git history binding | CC6 | CD6 | NEW `src/hippo/knowledge/code_history.py`, NEW `tests/unit/test_code_history.py` | `history_event` artifacts/revisions, commit objects/observations with the §9 temporal fields, commit views, `MODIFIES`/`PRECEDES` rows; truncation and shallow boundaries in coverage; no wall-clock default. |
| CC8 | Staged code writer and long-build authority | CC2, CC6, CC7 | CD7 | NEW `src/hippo/knowledge/staged_code.py`, NEW `tests/unit/test_staged_code_writer.py`, `src/hippo/knowledge/build_authority.py`, `tests/unit/test_build_authority.py` | Fenced batches, exact inventory, `IndexManifest` seal through `seal_generation`; idempotent replay; no callback, model or filesystem access inside a transaction. Owns `BuildAuthority.rebaseline` too, because the between-batch contract is what proves it; CC9 only calls it. |
| CC9 | Coordinator | CC1, CC3, CC8 | CD7, CD8 | NEW `src/hippo/ingest/code_generation.py`, NEW `src/hippo/ingest/build_run.py`, NEW `tests/unit/test_code_generation.py` | `build_code_source` bootstrap/refresh/resume/failure/receipt; `_Run` factored out of `prose_generation.py` without changing its contract. |
| CC10 | Activation dispatch | CC9 | CD8 | `src/hippo/ingest/managed_activation.py`, `src/hippo/ingest/pipeline.py`, `src/hippo/ingest/readers.py`, NEW `tests/unit/test_managed_code_activation.py` | Eligibility extended to `repo`, `archive` and code `file` with an actor; `add_repo(..., build_actor=...)`; managed sources bypass `_read_history` and `_prepare_reindex`; unsupported and actorless callers stay legacy; destructive-operation spies stay untouched. |
| CC11 | Acceptance and review | CC1–CC10 | CD9, CD10 | this plan and `ai_docs/gates/rag-it-all/task-5-code-capture/GATES.md` only | Full ledger with Ladybug as primary; root-owned disposable Neo4j parity evidence; independent SPEC and QUALITY review with findings closed and affected gates rerun. |

## 13. Acceptance gates

The proposed ledger is `ai_docs/gates/rag-it-all/task-5-code-capture/GATES.md`, unticked, with
gates CD1–CD10: CD1 scoped store reads, CD2 legacy serving until publication, CD3 capture and
provenance, CD4 mapped chunks, CD5 evidence binding, CD6 history and temporal fields, CD7 staged
writer and resume, CD8 coordinator and activation dispatch, CD9 Ladybug acceptance with recorded
Neo4j parity, CD10 lint and independent review. Fake is the first backend for every gate, LadybugDB
is the acceptance backend, and Neo4j parity is recorded as root-owned evidence under CD9 rather
than as a separately runnable line, following the `task-5-prose-coordinator` PC-N4 convention: the
disposable container admits one pytest process at a time. No gate is satisfied by this document.

## Post-implementation amendments (CC11, 2026-09-13)

What CC1–CC10 shipped (merged at `9a474e4`) where it differs from the sections above, or makes
them precise. Each paragraph names the text it supersedes and its evidence. The sections above are
left as reviewed. Evidence files live in `ai_docs/gates/rag-it-all/task-5-code-capture/`.

**§2 and §3, `read_plain_provenance`** (supersedes the §2 row "`prepare_prose_chunks` and
`read_plain_provenance` both reject code" and §3's "prose rejects code by contract at three
reviewed seams"). `read_plain_provenance` does not reject code. `provenance.py:349` decodes
`CODE_EXTENSIONS`, `:377` marks `is_code`, and only rich names and `.zip` refuse.
`code_provenance.read_code_provenance` delegates its decode to it, refuses plain-prose names, and
accepts extensionless known-text names such as `go.mod` (ruling 7; `evidence-cc4.md` item 1). The
claim about `prepare_prose_chunks` was not re-examined. The separate code seam stands on §3's
other reasons.

**§2, `build_authority._source_control`** (adds the seam §2 omitted; review B3). This function held
a third copy of the Artifact/Generation presence test and refused every kind except `text` and
`file`. CC8 changed four things:

- it admits `repo` and `archive`;
- it computes `managed` from the row's `managed` flag or `active_generation_id`;
- `_inventory` admits `repository` and `history_event` members;
- the planned-policy scope key accepts `source:<id>:managed-code-v1` beside `plain-prose-v1`
  (`evidence-cc8.md`).

**§3, `CodeTreeInput` and `CodeBuildOptions`** (supersedes §3's "the ordered tuple of normalized
relative paths to capture" and the clone depth in §5's operational list). The coordinator is
handed a checkout. `paths` is an exclusion complement over the walk: every walked path not named
is excluded, and a named path the walk did not find refuses. Capture has no only-these-paths mode
(`evidence-cc9b.md` deviation 1). `CodeBuildOptions` has no clone-depth field. The activation
adapter derives the depth as `code_history_depth + 1`, or 1 with history off (`evidence-cc10.md`).

**§4, the community label** (supersedes "community label" in the observation attributes and "The
community label is computed during preparation … and written in the `Symbol` row before the
seal"). This lane cannot write it: `store/code.py::symbol_write_row` builds a closed dict with no
`community` key, and `add_symbols` has no `SET n.community` (`evidence-cc8.md` finding 3,
`evidence-cc6.md` finding 4, `evidence-cc9b.md` finding 5). The claim is withdrawn for this task.
Writing communities for managed code needs its own `store/code.py` slice, which is not scheduled.

**§4, data objects, mentions and overloads.**

- `knowledge.model.ObjectKind` has `table` and `column` but not the codegraph's `collection`,
  `label` or `rel_type`. `code_binding.DATA_OBJECT_KINDS` maps those three to `resource` and keeps
  the dialect and data kind in `canonical_key` and `attributes_json` (`evidence-cc6.md`). Growing
  `ObjectKind` instead is a `model.py` change left to the CD10 review.
- The committed chunker synthesizes no data-object mention text, so §4's "data-object mention
  passages" have no instance (`evidence-cc5.md` finding 1).
- `codegraph.model.symbol_id` carries no signature, so two C# overloads in one file share one
  native ID. They become two knowledge objects and two bindings over one native row, and the first
  in canonical order is kept. This is a recorded defect, not repaired (`evidence-cc6.md`). Fixing it
  needs a `codegraph` change and a native-ID migration.

**§4, the projection** (qualifies "this lane populates `StructuralCodeEvidence`"). As of CC10, a
published code generation projected its code nodes with no arrows. Code derived records carry no
`input_binding_ids` (`knowledge/code_binding.py:459-463`), so the projection drew no `DEFINED_IN`
for a rendered code passage, and it read no native `CODE_EDGE` (`evidence-cc11.md` finding 2).
CODEPROJ, merged at `955cc11`, closed this without changing any evidence writer or generation
identity (`evidence-codeproj.md`):

- `projection._native_code_relations` reads each selected generation's sealed `CODE_EDGE`,
  `DEFINED_IN`, `MODIFIES` and `PRECEDES` rows. It uses one scoped `_edges_touching(...,
  both=True)` read over that generation's bound native ids and projected passages.
- The rows are served as arrows with the legacy loader's kind, weight, provenance and extra, plus
  `generation_id` and `support_span_ids`.
- A `DEFINED_IN` arrow is served only when the node's binding span lies inside the passage's exact
  original closure, so a bound node needs no `StructuralCodeEvidence` row.
- Relations stay native, as ruling 1 says. The projection is the one reader that turns them into
  arrows.

Two parity differences against the legacy lane remain.
`test_code_projection.py::test_one_repository_serves_the_same_code_arrows_through_the_legacy_and_the_managed_lane`
pins both exactly:

1. **No `REFERS_TO`.** `staged_code.RELATION_KINDS` is `CODE_EDGE`, `DEFINED_IN`, `MODIFIES` and
   `PRECEDES`. The managed lane therefore writes none of the prose-to-code `REFERS_TO` relations the
   legacy indexer draws.
2. **Declaration-only modules stay unbound.** A module whose file holds only declarations, such as
   `web/index.ts` in that test, has no passage of its own. It appears only in its first
   declaration's `defines`, while `materialize_code_evidence` binds a chunk's own `symbol_id`
   (`code_binding.py:1077-1085`). So the module gets no native row, `code_relations` drops every
   relation touching it, and coverage counts it in `unbound_nodes`. The legacy lane serves that
   node with its `CONTAINS`, `MODIFIES` and `DEFINED_IN`. The fix belongs to the owner of
   `code_binding.py` and `ingest/code_generation.py`.

Two overloads sharing one native ID project as the cross product of their knowledge objects. A
status card that counts arrows can then exceed the source row's native count
(`evidence-codeproj.md` finding 3).

**§4, §6 and §10, prose inside a tree** (supersedes §4's "Plain-prose files inside a captured tree
… do receive extraction", §6 step 1's OpenIE profile, §10's "prose OpenIE for captured prose files"
and ruling 5). Ruling 5 is deferred, by name, to a follow-up slice. The code bundles and
`staged_code` carry no `ProseExtraction`, and the writer refuses one. A `readers.PROSE_EXTENSIONS`
file inside a tree is therefore captured as ordinary passages through `prepare_code_chunks`' prose
branch. Coverage records `openie: "skipped"` for it, with the reason `prose_extraction_deferred`
per file (`code_generation.OPENIE_PROSE_DEFERRED`, `evidence-cc9b.md`). The follow-up widens CC6,
CC7 and CC8 together. Until it lands, a converted source loses the README facts that the legacy
lane extracts, which is the regression §11 item 5 named. Ruling 11 shipped as written: an
extensionless `README`, `LICENSE`, `NOTES` or `go.mod` becomes `window` passages with the reason
`unparsed`.

**§5, repository identity** (supersedes "its normalized `owner/name` path as the repository ID";
review M8).

- The repository ID is the whole normalized path, not `repos.repo_name`'s last two segments. A
  trailing `.git` and empty segments are dropped, and `.` or `..` refuse.
- Host and path fold to lowercase, and transport folds to `https`. The `http://`, `ssh://git@host/`
  and `git@host:` spellings of a path are one repository.
- An `ssh` port and a scheme's default port are dropped. A non-default `http(s)` port is kept.
- An `http(s)` URL carrying userinfo refuses (`evidence-cc4.md` M8).

The cost falls on a forge with genuinely case-sensitive paths. Task 10's provider IDs resolve it.

**§5, walker drift** (review m7). Two generations at one commit with different walker or grammar
versions cannot collide, because the versions are hashed into the generation ID and native IDs are
re-derived from its namespace. They drift instead. `symbol_key` is deliberately not
generation-scoped, so a walker that changes a qualified name or a signature mints a new symbol
object, and the old object keeps its observations. A walker upgrade silently forks that symbol's
history.

**§5, identity inputs that do not match the text.**

- `chunk_overlap_chars` is hashed but changes no code passage. `chunker.code_windows` takes no
  overlap, so two generations that differ only in overlap have byte-identical code passages
  (`evidence-cc6.md` finding 11).
- Contrary to ruling 10's list, no writer rule version is hashed. Batch grouping changes no record
  identity, and the resume probe's absence assertion closes M2 (`evidence-cc8.md` finding 5).

**§7, the legacy lane** (supersedes the whole section; rulings 9 and 14).

- **The flag.** The `managed` flag still flips at staging start, so every destructive-operation
  guard treats a converting source as managed.
- **The serving predicate.** `GenerationQueries.source_serves_legacy(source_row)` decides the
  serving lane apart from the loader-selection set, independent of the flag, with three terms: no
  `active_generation_id`, no published `IndexEvent`, and no all-principals `Suppression` targeting
  the source (`evidence-cc1.md`).
- **Untagged rows only.** `context.legacy_lane(store, sources, managed_records)` (`context.py:54`,
  shared by `status.py:72`) applies ruling 14: only untagged rows serve the legacy lane. A source
  with no `Generation` row is legacy iff it is in no managed record set. A source with one is legacy
  iff `source_serves_legacy` holds and it still owns an untagged `Passage`, `Symbol`, `DataObject` or
  `Commit`.
- **Consequences.** A bootstrap-only managed source is absent from every surface until publication,
  and an empty selection never falls through to the unfiltered legacy loader
  (`evidence-cc1fix.md`). Refresh differs from bootstrap in the three places §7 names.

**§8.1, the knowledge-table half of the scale defect** (adds to §8.1). CC2's scoped reads bounded
the native tables. At CC10, though, the write path still read whole knowledge tables per record:

- `_check_knowledge_write` (`store/generations.py:641`, `:658`, `:663`, `:675`) reads every
  `GenerationMember` and `GenerationEvidenceMember` row for each membership or binding put.
- `knowledge/derivations.py`'s `_Inventory` and `validate_view` read whole
  `GenerationEvidenceMember`, `GenerationMember` and `DerivedDependency` tables. They are reached
  per rendered passage through `_validate_managed_native` (`generations.py:1477`).

A code build was therefore quadratic in the corpus. On Fake it took 1.1 s, 8.4 s and 109.5 s at
10, 40 and 160 files, and one 10-file build took 444.6 s on LadybugDB (`evidence-cc11.md`).
KSCOPE, merged at `df05bac`, scoped every one of those reads (`evidence-kscope.md`). Each is now
keyed by `generation_id`, by a primary key, or by one of the two schema v7 keys,
`GenerationEvidenceMember.record_id` and `DerivedDependency.derived_record_id`. LadybugDB has no
secondary-index DDL, so there the v7 keys are predicate scans inside the engine.

A build still issues one keyed knowledge read per record it checks. The three builds of CD9's
scenario at 20 files made about 183,000, almost all `where` lookups, so on LadybugDB a build's cost
is set by that query count (`evidence-cc11.md`).

**§8.2, reclaim** (supersedes the "Resume" paragraph's admission rule; review B5).
`reclaim_generation_build` performs every step of `claim_generation_build` except collection, in
this order:

1. read and lock the source;
2. the tombstone barrier;
3. `staging` or `failed` status with a future lease;
4. the never-published triple: `published_at`, `active_generation_id == gen.id`, and any published
   `IndexEvent`. `claim_generation_build` now checks the same triple.
5. `expected_manifest_hash`;
6. live-holder exclusion, where the same holder is idempotent;
7. advance the fence and install a fresh holder.

A refusal advances no fence and installs no holder. Manifest equality is an assertion, not the
safety property (M1, `evidence-cc3.md`).

**§8.2 and §9, the capture instant** (review B4). The instant is persisted as
`Generation.created_at`, which is outside generation identity.

- The coordinator computes the manifest and generation ID first. It then adopts the stored
  `created_at` on a reclaim, or takes one `store._now()` for a generation it creates.
- The instant is threaded through binding and history. `bind_history` refuses any other instant,
  so a resumed build reproduces every `ObjectObservation` ID.
- `ArtifactRevision.observed_at` means first observed. A refresh over an unchanged file or commit
  reuses the stored revision. Minting the same ID with a new instant would make `put_knowledge`
  refuse (`evidence-cc9b.md`).

**§8.2, resume probe and receipt** (supersedes "skips a group whose inventory already matches").

- The probe compares every row of a group against its canonical payload. It also asserts that the
  generation holds no row the current derivation would not produce (ruling 10).
- `BuildReceipt.resumed_from_batches` counts skipped dependency groups, minus the revision-member
  groups the install writes before every attempt. It does not count batch transactions
  (`evidence-cc8.md`, `evidence-cc9b.md`).
- A `ResumePlan` is not bound to the prepared index it was probed against (`evidence-cc8.md` finding
  8).

**§8.2, rebaseline** (supersedes the "Long-build authority" paragraph; review M6 and M7). As CC8
built it, `BuildAuthority.rebaseline()`:

- refuses inside a transaction and after a sticky failure;
- under the authorization and source locks, refuses any suppression-epoch change (frozen at
  capture; publication would refuse such a change anyway, which subsumes M7);
- refuses any change to `SourceControl`'s `access_role_id`, `min_rank` or `owner_id`;
- then builds a child `BuildAuthority` from the current authorization epoch and the original actor,
  inputs and source control, and adopts that epoch only if `child.check_local()` passes. The
  parent's own `check_local()` is never called.

Receipts count rebaselines (`evidence-cc8.md`).

**Still open: the heartbeat race.** `LeaseHeartbeat` renews on its own timer through `check_local()`.
That call can latch an epoch mismatch before the between-batch comparison rebaselines it. A build
that loses the race fails with its inventory retained and resumes on the next attempt. Closing the
race needs a hook in `build_run.py`, which CC10 did not take (`evidence-cc9b.md` item 4,
`evidence-cc10.md` deviation 4).

**§8.3, ceilings** (qualifies "Exceeding a ceiling refuses the build before capture").

- The passage ceiling is checked after chunking (`evidence-cc5.md` finding 8). Every ceiling still
  refuses before a generation is installed
  (`test_code_generation.py::test_every_ceiling_refuses_before_it_installs_anything`).
- `CodeBuildOptions.max_file_bytes` (2,000,000, the value of `readers.MAX_FILE_BYTES`) is the
  capture cap that excludes a file as `too_large`. `CODE_MAX_FILE_BYTES` (512 KiB) only decides
  whether a captured file is parsed or kept as line windows.
- `max_inputs` is `3 * CODE_MAX_FILES`, because excluded entries count against the capture limits.

**§9, `evidence_class` and history coverage** (adds rows to the §9 table; review m4 and m5).

| Observation | `evidence_class` and span |
| --- | --- |
| symbol and data object | `syntax_observed` |
| file object | `catalog_observed`, one observation per span |
| repository object | `declared`, one observation over a `field` locator on the normalized clone path |
| commit | `declared`, a `field` locator `commit.message` on the `history_event` revision |

Coverage records `history_walk: "first_parent"` beside `skipped`, `truncated` and the shallow
boundary. `codegraph.git_history.shallow_boundary` was added by CC9b. Coverage also records
`history_renames: "not_reported"`, because `History` reports no renames. The history rule version
enters identity under the top-level `code_history_derivation` key (ruling 10, option 3).

**§10, privacy** (supersedes "Absolute paths, repository URLs with credentials … never reach logs"
as a present property; review m6 and question 8). The redaction was work, and CC10 did it
(`evidence-cc10.md`):

- a clone failure logs a closed reason and the bare host, never the URL or git's stderr;
- a timeout names no URL and drops its chained cause;
- checkout errors name no absolute path;
- with an actor, `add_repo` refuses a credentialed URL before any Source row exists.

Three limits remain.

- The legacy lane still stores a credentialed `meta.url` (Task 16).
- `EvidenceSpan.text` stores the original code text in the database by design. "Source text never
  reaches logs" must not be read as "code text is not stored": the access boundary protects it.
- On Neo4j the driver logs every Cypher statement with its parameters at DEBUG, so raw URIs and
  captured paths reach a DEBUG log that hippo's own loggers never write. Root's Neo4j parity run 6
  found it through `test_code_generation.py`'s log-leak test, which now checks hippo's loggers only.
  Hippo's logging setup must cap the `neo4j` logger at INFO (Task 16 follow-up).

**§10, failure, crash and costs.**

- **Seal-to-publication crash.** Such a crash leaves the generation `ready`. An immediate retry
  cannot reclaim it, because reclaim admits only `staging` and `failed` (`evidence-cc9b.md` item 5).
  Once lease-expiry recovery marks it `failed`, reclaim returns it to `staging`, and the
  byte-identical seal publishes (`evidence-cc3.md`).
- **Crashed repository build.** It leaves `checkouts/<operation-id>/` behind until the same
  operation retries (`evidence-cc10.md` finding 3).
- **`content_kind`.** It is unset on code passages (`evidence-cc8.md` finding 4).
- **Query-time profile check.** `validate_generation_profile` does a bounded `_knowledge_get` pair
  per member on every query that touches a code generation (`evidence-cc8.md` finding 6).

**§11, rulings 12 and 13** (ruling 14 is under §7 above).

- **Ruling 12.** `knowledge/code_binding.py` and `knowledge/code_history.py` import nothing from
  `hippo.ingest`. They validate the capture and chunk dataclasses structurally and pin
  `EXPECTED_CODE_CHUNK_RULE_VERSION`. Moving the shared dataclasses into `knowledge/inputs.py` is
  deferred.
- **Ruling 13.** `generation_profiles` has a `code` profile, selected by the accepted configuration:
  one manifest, one repository, one file per accepted input and zero or more `history_event`
  members, with the `history_event` pairs excluded from the identity re-derivation. It is validated
  at seal, checksum and query time, and the plain-prose profile is byte-identical.

**LadybugDB engine defect** (applies to every store query builder). real_ladybug 0.15.3 can answer
an `IN <list>` predicate on a string column of a node table from the wrong row. It does so when the
table holds a deleted row and the wanted row was written in the open transaction.

- Every list-membership read in `store/*` and `knowledge/*` goes through `store.base.by_ids`, which
  emits `UNWIND $ids AS wanted_id MATCH (n:Label {id: wanted_id})`.
- `tests/unit/test_generation_scoped_reads.py::test_no_query_builder_selects_node_rows_with_a_list_predicate`
  is the static tripwire.
- The relationship-property `r.kind IN $kinds` at `store/code.py:596` and `store/ladybug.py:1280`
  stays allowlisted and unprobed (`evidence-lbfix.md`).

Future LadybugDB query builders use the `UNWIND` form.

**§13, acceptance** (qualifies CD9).

- The index-backed half of the CD1 bound is proven on Neo4j (root parity run 2), not on LadybugDB,
  which has no secondary-index DDL (`evidence-cc2.md`, `neo4j-parity.md`).
- The linearity proof at the 50,000-symbol ceiling is CC2's synthetic Fake test.
- CD9's fixture, `tests/fakes/code_capture_repo.py`, does not reach that ceiling and is not presented
  as doing so.
