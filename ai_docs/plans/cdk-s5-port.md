# CDK slice S5: the local prose path and the git code path as connectors on the runtime

**Status:** proposed implementation contract for root review. Nothing here is implemented. Written
at HEAD `f7b14ee`, which carries the design amendments of `d1b7bb2` and `f7b14ee` and the orchestrator's
answer to decision 8. Design of record: `docs/spec/connector-developer-kit.md` ("design"). Gate: CK5
of `ai_docs/gates/rag-it-all/cdk/GATES.md`. Form follows
`ai_docs/plans/rag-it-all-task-5-managed-code-capture.md`.

## 1. Goal and scope

**Goal.** Every managed build that `add_text`, `add_upload` (including ZIP) or `add_repo` starts is
dispatched through the kit: a `local` or `git` connector and a runtime lane. The published
generation is byte-identical to what the pre-kit path publishes today, with one exception:
`Generation.registry_fingerprint` is set on the runtime path and is `None` on the pre-kit path.

**In scope.**

- `src/hippo/connectors/local/` and `src/hippo/connectors/git/`.
- `src/hippo/connectors/lanes.py`, the runtime's coordinator lane.
- One keyword argument on each reviewed coordinator.
- The switch inside `managed_activation.run_managed_build`.
- The byte-identity proof on Fake, and the LadybugDB evidence.

**Out of scope.**

- Re-expressing prose or code emission as `EmissionBatch`. That is Task 6's prose connector and a
  later code connector (design §11).
- `Unit` rows for prose and code.
- The legacy lane.
- `plan_dispatch`, `managed_eligibility` and the CD2 serving rule.
- Retrieval, S4's commands and S6's surfaces.

**Split (decision 12).** S5 is two workers, `s5a` then `s5b`.

- **S5a** is the lane module, the local connector's prose half, the prose seam and the prose switch,
  with its parity proof.
- **S5b** is the code seam, the code switch, the local connector's archive and code-file half, the
  git connector, its parity proof, and the LadybugDB acceptance run.

S5b alone carries a scenario that took 1,615 s and 25.6 GiB on LadybugDB at N=8
(`ai_docs/gates/rag-it-all/task-5-code-capture/evidence-cc11b.md`). One worker cannot also carry
the prose half inside the fleet budget (`ai_docs/handoffs/fleet-worker-rules.md:58`).

## 2. Existing seams

| Seam | Use or required boundary |
| --- | --- |
| `src/hippo/ingest/pipeline.py:98-123` `add_text`, `:126-157` `add_upload`, `:160-188` `add_repo` | Create the Source row, save the bytes, call `start_indexing`. **Unchanged.** |
| `pipeline.py:191-199` `add_sample` | Passes no `build_actor`. `managed_eligibility` returns `unsupported` for kind `sample` (`managed_activation.py:137-153`). The sample has no managed path to be byte-identical with, so it stays legacy. |
| `pipeline.py:238-265` `start_indexing`, `:272-321` `run_indexing`, `:352-382` `_run_managed_indexing` | The lane is decided by `plan_dispatch` (`:257`, `:295`). A managed plan calls `managed_activation.run_managed_build` (`:361-367`). The legacy body (`:302-321`) is untouched. **No change to `pipeline.py`.** |
| `src/hippo/ingest/managed_activation.py:125-154` `managed_eligibility`, `:157-160` `is_code_source`, `:202-217` `plan_dispatch` | Closed dispatch on the Source row. **Unchanged.** CD2's converting-source rule lives below it and in `context.py`/`status.py`, which S5 does not touch. |
| `managed_activation.py:624-674` `run_managed_build` | **The single switch point.** Its refusals (`:634-648`) stay first. Its prose branch (`:655-674`) and code branch (`:650-653` → `:677-746`) build their arguments exactly as today and hand a lane to the runtime. |
| `managed_activation.py:677-713` `_run_code_build`, `:716-746` `_build_code` | Checkout lifecycle: discard before, clone, discard in `finally` (`:700-713`). The lifecycle is kept, and the clone moves into `GitConnector.list_changes` with identical arguments. |
| `managed_activation.py:163-168` `new_operation_id` | `index.<uuid4 hex>`. The parity test pins it. |
| `src/hippo/ingest/prose_generation.py:482-625` `build_plain_source` | The prose coordinator: capture `:532-540`, accepted pairs `:543`, generation `:545`, prior receipt `:546-549`, materialize `:550-552`, staged writes `:579-602`, publish `:603`. |
| `prose_generation.py:141-191` `_accepted_pairs` | Artifacts carry **no `connector_id`** (`:155-162`). Policy scope `source:{id}:plain-prose-v1` (`:146`). |
| `prose_generation.py:194-212` `_configuration`, `:215-228` `_generation` | Configuration enters the manifest. `_generation` adopts a stored generation's `created_at` (`:227-228`), which is the pattern the fingerprint seam copies. |
| `prose_generation.py:292-329` `_materialize` | `read_plain_provenance` (readers), `prepare_prose_chunks` (chunker), `materialize_chunk_evidence`: the prose emission, unchanged. |
| `src/hippo/ingest/code_generation.py:874-1020` `build_code_source` | The code coordinator: capture `:948-955`, generation `:969-973`, prior receipt `:974-977`, prepare `:979`, install `:989-991`, embed `:996-999`, write `:1000-1001`, publish `:1005-1015`. |
| `code_generation.py:389-414` `_history`, `:466-542` `_prepare` | `read_history` runs `git` as a subprocess (`codegraph/git_history.py:64`, `:326`, `:363`, `:582-623`) between extraction (`:471-476`) and binding (`:495`, `:516`), and needs the extracted symbols. |
| `code_generation.py:588-598` `_policy`, `:601-613` `_instant` | Policy scope `source:{id}:managed-code-v1`. `_instant` adopts a reclaimable generation's `created_at`. |
| `src/hippo/ingest/chunker.py:70-89` `chunk_documents` | Ordinals run continuously across a source's documents, with commits last (`:83-88`). |
| `src/hippo/knowledge/lifecycle.py:15-66` `generation_for_inputs`, `:73-95` `generation_passage_id` | The manifest hashes `configuration` (`:47-56`). A passage id hashes its ordinal (`:94-95`). |
| `src/hippo/knowledge/model.py:312` `Artifact.identity_fields` | `("workspace_id", "connector_id", "kind", "external_id")`. A `connector_id` would change every artifact id and every id derived from it. |
| `model.py:278-286` `Connector`, `:670-678` `SyncState` | `SyncState.connector_id` must reference an existing `Connector` (`store/knowledge.py:82`). |
| `src/hippo/store/authorization.py:113-114`, `:183-193` `record_mutation` | Writing a `Connector` row bumps the authorization epoch. |
| `store/authorization.py:44-47` `configured_provider`; `store/knowledge.py:672-677` | A non-`local` connector row that is enabled or configured is refused in open mode. |
| `src/hippo/knowledge/identity.py:75-97` `normalize_provider_url` | `Connector.instance_url` must be an HTTP(S) URL with a host. A local source has none. |
| `src/hippo/store/knowledge.py:760-779` `put_knowledge` | "Immutable record already exists with different contents" (`:771-772`). Two paths on one store would collide on the generation id. |
| `src/hippo/store/generations.py:63-64` `_now` | `_generation_clock` pins the store clock. |
| `generations.py:893-964` `_native_relationships`, `:966-1080` `generation_checksums` | `generation_checksums` skips the `Generation` row (`:982`), so `registry_fingerprint` is unhashed. |
| `generations.py:1419-1427` `IndexEvent(...)` | `payload_json` carries job credentials, including the `uuid4` lease owner (`ingest/build_run.py:90`). Identity is `("workspace_id", "aggregate_id", "sequence", "dedupe_key")` (`model.py:982`), so the receipt's `event_id` is deterministic. |
| `src/hippo/ingest/build_run.py:45-56` `BuildReceipt` | Seven fields, compared whole. |
| `src/hippo/knowledge/inputs.py:43-67` `ByteInput`/`FileInput`, `:182-205` `_manifest_bytes` | The manifest records no input type. Only `FileInput` capture detects a file changed during capture, and `tests/unit/test_managed_pipeline_activation.py:545` pins that refusal, so the lane keeps `FileInput`. |
| `tests/unit/test_code_capture_acceptance.py:242` | The CD9 scenario calls `build_code_source` directly, not through `run_managed_build`. |
| `ai_docs/gates/rag-it-all/task-5-code-capture/GATES.md:18`, `:24`, `:60`, `:66` | The CD1, CD2, CD8 and CD9 CHECK lines. CK5 requires CD1 and CD2 verbatim, CD8 is the dispatch regression, and CD9 is the LadybugDB acceptance. |
| `tests/unit/test_import_order.py:14-28` `MODULES`; `tests/unit/test_layering.py:125-131` | `pipeline` imports `managed_activation` eagerly. A new module on that import path is proven acyclic in a fresh interpreter. |

## 3. The shape: coordinator lanes

### 3.1 Why emission stays with the reviewed coordinators

Design §7 steps 5–8 describe a per-revision pure `emit`, a generic bind and `staged_records`. For
these two paths that shape cannot produce byte-identical output, for five reasons:

1. **Passage ids depend on the whole source.** Chunk ordinals run across all of a source's documents
   (`chunker.py:83-88`), and the passage id hashes the ordinal (`lifecycle.py:94-95`). A per-revision
   emit numbers each file from zero.
2. **Code resolution is whole-source.** `extract_code` runs over every document of the source
   (`code_generation.py:471-476`), and cross-file resolution needs all of them.
3. **Git history is a subprocess that needs the extracted symbols.** `read_history` runs between
   extraction and binding (`code_generation.py:401-410`). Design §8 forbids a subprocess inside
   `emit`.
4. **The coordinators call models after binding.** OpenIE runs at `prose_generation.py:567-575` and
   embeddings at `code_generation.py:996-999`. Design §0 puts extraction downstream of emission, so
   the connector cannot do it.
5. **`EmissionBatch` has no slot for records both lanes write:** `RetrievalView`, `DerivedRecord`
   and `DerivedDependency` for rendered chunks (`knowledge/input_binding.py:294-346`),
   `ProseExtraction`, and native `Symbol`, `DataObject` and `Commit` rows with `NativeBinding`.

Design §11 already disposes of these two paths: "Kept unchanged as the code and prose connectors'
emit and native rows; the port (gate CK5) wraps them without changing their output". The port
therefore runs the runtime's sync half through the connector and gives the derivation half to the
reviewed coordinator, which is the **coordinator lane**. The runtime's nine steps map onto reviewed
code:

| Design §7 step | Coordinator lane | Anchor |
| --- | --- | --- |
| 1 Lease | the fenced build claim inside `_install` | `prose_generation.py:332-349`; `code_generation.py:720-729` |
| 2 Cursor and page | `connector.list_changes(config, None)`: a complete local inventory, no provider cursor | §4 below |
| 3 Capture | `capture_raw_inputs` / `capture_repository_inputs` | `prose_generation.py:532-540`; `code_generation.py:324-338` |
| 4 Checkpoint | the accepted manifest's identity: a replay of unchanged inputs returns the prior receipt with no write | `prose_generation.py:546-549`; `code_generation.py:974-977` |
| 5 Emit | `_materialize` / `_prepare` | `prose_generation.py:292-329`; `code_generation.py:466-542` |
| 6 Bind | `materialize_chunk_evidence` / `materialize_code_evidence` + `bind_history` | `prose_generation.py:314-316`; `code_generation.py:495`, `:516` |
| 7 Stage | `staged_prose` batches / `staged_code` | `prose_generation.py:579-602`; `code_generation.py:1000-1001` |
| 8 Publish | `_publish` through `BuildAuthority` | `prose_generation.py:603`; `code_generation.py:1005-1015` |
| 9 Reconcile | none: a local source has no provider deletions, and delete is the unchanged tombstone path | — |

### 3.2 Contract

```python
# src/hippo/connectors/lanes.py
@dataclass(frozen=True)
class CoordinatorLane:
    family: Literal["prose", "code"]
    build: Callable[[ChangePage, str], BuildReceipt]


def run_coordinator_lane(
    connector: Connector,
    config: BaseModel,
    lane: CoordinatorLane,
    *,
    registry: Registry,
) -> BuildReceipt: ...
```

`run_coordinator_lane` does the following, in order:

1. Refuse, with `ManagedDispatchError` (`managed_activation.py`), any `connector.descriptor` whose
   `families` do not include `lane.family`, whose `kinds`, `artifact_kinds` or `locator_kinds` are not
   registered in `registry`, or whose `predicates` or `parsers` are non-empty.
2. Take `page = connector.list_changes(config, None)`. Refuse a page whose completed-scan marker is
   false.
3. Return `lane.build(page, registry.fingerprint())`, letting any exception propagate with its type
   unchanged, so `managed_activation.map_build_failure` (`:574-590`) maps the same failures to the
   same public codes.

It imports nothing from `hippo.ingest.managed_activation` or `hippo.ingest.pipeline`. The build
callable is a closure that `run_managed_build` makes, so no import cycle can form.

**The coordinator seam** (S5a adds it to prose, S5b to code):

```python
def build_plain_source(
    ctx,
    *,
    source_id,
    actor,
    inputs,
    options,
    raw_store,
    embedding_spec,
    operation_id,
    should_stop,
    on_progress=None,
    embedding_cache: EmbeddingCache | None = None,
    registry_fingerprint: str | None = None,
): ...


def build_code_source(
    ctx,
    *,
    source_id,
    actor,
    tree: CodeTreeInput,
    options: CodeBuildOptions,
    raw_store,
    embedding_spec,
    operation_id,
    should_stop,
    on_progress=None,
    embedding_cache: EmbeddingCache | None = None,
    registry_fingerprint: str | None = None,
) -> BuildReceipt: ...
```

- **Prose.** `_generation` (`prose_generation.py:215-228`) sets the fingerprint on a new generation
  and adopts the stored value for an existing one, exactly as it adopts `created_at`.
- **Code.** After `_instant` (`code_generation.py:970-973`), the coordinator sets the fingerprint on a
  generation it creates and adopts the stored value on a reclaim.

In both, the fingerprint is outside `Generation.identity_fields` (R-S1-1), so no generation id moves.
Neither `lifecycle.py` nor `code_binding.py` changes. With the default `None`, every existing
coordinator test is unchanged.

**No `Connector` or `SyncState` rows on these lanes** (decision 5 note). Each would harm the port:

- a `Connector` row bumps the authorization epoch (`store/authorization.py:113-114,188-193`) and
  would be refused in open mode for kind `git` (`store/knowledge.py:672-677`);
- `Artifact.connector_id` is in identity (`model.py:312`);
- `ProviderURL` has no honest value for a local source (`identity.py:86-92`).

The lease and the checkpoint are the coordinator's claim and manifest (§3.1 table). No
`Artifact.connector_id` is ever set.

## 4. The two connectors

### 4.1 `connectors/local/` (decision 5)

```python
class LocalSourceConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_id: str
    kind: Literal["text", "file", "archive"]
    root: str
    exclusions: tuple[str, ...] = ()
    max_files: int = CODE_MAX_FILES
    max_file_bytes: int = MAX_FILE_BYTES


class LocalConnector:
    descriptor: ConnectorDescriptor

    def probe(self, config: LocalSourceConfig, clock: Clock) -> Classification: ...
    def list_changes(self, config: LocalSourceConfig, cursor: SyncCursor | None) -> ChangePage: ...
    def fetch(self, config: LocalSourceConfig, ref: ExternalRef) -> RawFetch: ...
    def fetch_policy(self, config: LocalSourceConfig, ref: ExternalRef) -> PolicyObservation: ...
```

**Descriptor.** `name="local"`, `version="local-v1"`, `families=("prose", "code")`, `predicates=()`,
`credentials=()`, `parsers=()`. Capabilities are all false: no changes feed, no deletion feed, no
ACLs, no history, no attachments, no webhooks. `kinds`, `artifact_kinds` and `locator_kinds` are the
exact sets the two lanes write for text, file and archive sources. The worker enumerates them from
`code_binding.py` and `input_binding.py`, and `test_local_descriptor_covers_every_record_the_lanes_write`
pins them against the published rows. `types.py` holds an empty `TypeExtension()`. There is no
`templates.py` and no `emit`.

**`config` is built by `run_managed_build` from the Source row and the existing helpers.** `root` is
`ingress_file(...)` (`managed_activation.py:348-382`). The walk limits are `code_build_options(ctx)`
(`:311-336`) for archive and code-file sources.

- **`list_changes`.**
  - For `text` and a prose `file`: one `upsert` change whose external id is the saved name
    (`saved.name`), with `provider_revision=None`, completed scan true and no cursor.
  - For `archive` and a code `file`: `repo_capture.walk_tree(root, exclusions=..., max_files=...,
    max_file_bytes=...)`, the call `code_generation._capture` makes at `:314-319`. It gives one
    `upsert` per inventory input in walk order, one coverage warning per exclusion reason with its
    count, and completed scan true.
- **`fetch`** returns the saved bytes, or the walked member's bytes, with
  `canonical_uri=f"source:{source_id}/{path}"`. That is the form `_accepted_pairs` writes
  (`prose_generation.py:160`).
- **`fetch_policy`** returns the `local_curated` workspace observation, equal to what the lanes mint
  (`prose_generation.py:143-149`, `code_generation.py:590-596`).
- **`probe`** returns one partition, `source:{source_id}`. Its family is `code` exactly when
  `managed_activation.is_code_source` says so (`:157-160`), otherwise `prose`. The name rules are
  `readers.is_code_name` and `is_plain_prose_name`, reached through S2's name-level classifier
  (R-S2-3).

**Reuse of readers and chunker (the brief's wording).** The local connector's emission is the prose
lane's `_materialize`: `read_plain_provenance` for readers, `prepare_prose_chunks` for the chunker,
then `materialize_chunk_evidence`, called unchanged by `build_plain_source`. For archives and code
files it is the code lane's `_prepare`.

**The lanes do not call `fetch` or `fetch_policy`.** Capture stays `FileInput` or the coordinator's
tree walk, because only file capture refuses an input changed during capture
(`test_managed_pipeline_activation.py:545`). `fetch` and `fetch_policy` are implemented and pinned
equal to what the lane captures and mints. They serve `probe` sampling and S4's dry run.

### 4.2 `connectors/git/` (decision 6)

```python
class GitSourceConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_id: str
    url: str
    checkout: str
    depth: int
    git_timeout_seconds: float
    exclusions: tuple[str, ...] = ()
    max_files: int = CODE_MAX_FILES
    max_file_bytes: int = MAX_FILE_BYTES


class GitConnector:
    descriptor: ConnectorDescriptor

    def probe(self, config: GitSourceConfig, clock: Clock) -> Classification: ...
    def list_changes(self, config: GitSourceConfig, cursor: SyncCursor | None) -> ChangePage: ...
    def fetch(self, config: GitSourceConfig, ref: ExternalRef) -> RawFetch: ...
    def fetch_policy(self, config: GitSourceConfig, ref: ExternalRef) -> PolicyObservation: ...
```

**Descriptor.** `name="git"`, `version="git-v1"`, `families=("code",)`, `predicates=()`,
`credentials=()`, `parsers=()`. Capabilities: history true, everything else false. `kinds`,
`artifact_kinds` and `locator_kinds` are pinned from the published rows of a repository build, and
include `history_event`, as for local.

**`config`.** `url` is `_clone_url(source)` (`managed_activation.py:423-426`), `checkout` is
`checkout_directory(ctx, source_id, operation_id)` (`:392-400`), `depth` is `clone_depth(options)`
(`:339-345`), and the walk limits come from `code_build_options(ctx)`.

- **`list_changes`** does the following:
  1. Call `repository_descriptor(url)`, the refusal `add_repo` and `_run_code_build` already make
     (`pipeline.py:182`, `managed_activation.py:699`). A credentialed URL refuses before any clone.
  2. `repos.clone_repo(url, Path(checkout), depth=depth)` when the checkout does not exist. It is
     called through the module attribute, so the `clone_locally` monkeypatch in
     `tests/unit/test_managed_code_activation.py:129-140` still applies.
  3. `head = repos.head_revision(Path(checkout), timeout=git_timeout_seconds)`.
  4. `walk_tree(checkout, ...)`, giving one `upsert` per input with `provider_revision=head`,
     exclusion warnings and completed scan true.
- **`fetch`** reads a walked file's bytes from the checkout.
- **`fetch_policy`** returns the local curated observation.
- **`probe`** reports family `code` and the history capability, observed from the checkout.

**Reuse of the code walkers, `code_binding.py`, `code_history.py` and `staged_code.py`.** The git
connector's emission is the code lane: `_prepare` (`code_generation.py:466-542`) runs `extract_code`,
`read_history`, `prepare_code_chunks`, `materialize_code_evidence` and `bind_history`, and `_write`
stages through `staged_code` (`:1000-1001`). All are unchanged, so native rows are unchanged.
**History is read by the coordinator, never inside a connector method.**

The checkout lifecycle stays in `_run_code_build`: discard before, then discard in `finally`
(`managed_activation.py:702`, `:712-713`).

## 5. The switch (decision 7)

**Where.** Only `managed_activation.run_managed_build` (`:624-674`) and `_run_code_build`
(`:677-713`). `pipeline.py` is not modified. `plan_dispatch`, `managed_eligibility`, `ingress_file`,
`record_build_failure`, `record_build_receipt` and the `FAILURES` table are unchanged. The legacy
body `pipeline.py:302-321` never reaches the kit.

**Flag.** None. CK5 requires the production dispatch to go through the kit, and a flag would keep two
production paths. The pre-kit path stays reachable exactly where the coordinator tests reach it
today: `build_plain_source` and `build_code_source` called directly with the default
`registry_fingerprint=None`.

**The prose branch after S5a**, replacing `:655-674`:

```python
saved = ingress_file(ctx, source_id, stored_name=_recorded_name(source))
options = build_options(ctx)
spec = embedding_spec(ctx.ollama)
store = RawArtifactStore(raw_root(ctx), max_object_bytes=int(ctx.config.max_upload_bytes))
cache = EmbeddingCache(cache_root(ctx))


def build(page: ChangePage, registry_fingerprint: str) -> BuildReceipt:
    return build_plain_source(
        ctx,
        source_id=source_id,
        actor=actor,
        inputs=(FileInput(saved.name, saved),),
        options=options,
        raw_store=store,
        embedding_spec=spec,
        operation_id=operation_id,
        should_stop=lambda: ctx.jobs.is_cancelled(job_key),
        on_progress=lambda progress: _present_progress(ctx, source_id, progress, refresh=refresh),
        embedding_cache=cache,
        registry_fingerprint=registry_fingerprint,
    )


present(ctx, source_id, **_starting_fields(refresh))
config = LocalSourceConfig(source_id=source_id, kind=source["kind"], root=str(saved))
return run_coordinator_lane(
    LocalConnector(), config, CoordinatorLane("prose", build), registry=default_registry()
)
```

**The code branch after S5b.** `_run_code_build` keeps its order: `present`, `discard_checkout`,
then `try`/`finally`.

- For `archive` and a code `file`, `_run_code_build` builds a `LocalSourceConfig` and a code lane
  whose build returns `_build_code(..., tree=CodeTreeInput(root=saved, kind=source["kind"]),
  registry_fingerprint=...)`.
- For `repo`, it builds a `GitSourceConfig`. The lane's build computes
  `CodeTreeInput(root=checkout.resolve(), kind="repo", repository=descriptor,
  head_revision=repos.head_revision(checkout, timeout=options.git_timeout_seconds))`, the
  expression at `:705-710`, after `list_changes` has cloned.

`_build_code` gains `registry_fingerprint` and passes it on.

## 6. The byte-identity proof (decision 8)

**Two worlds, one fixture.** The shared helper `tests/fakes/connector_parity.py` (S5a creates it, S5b
extends it) builds each world on a fresh data directory and a fresh store of the selected backend,
mirroring `tests/conftest.py:179-226`. On Neo4j, where one database serves one process, world A is
snapshotted and the database is reset before world B. Both worlds have the following, identically:

- the store clock pinned: `store._generation_clock = lambda: INSTANT` (`generations.py:63-64`);
- `new_id` pinned to a counter in every module that binds it (`store/base.py:147-149`, bound at
  `store/memory.py:60`, `tests/fakes/fake_store.py:241`, `:921`, and any other the worker greps), so
  source and user ids agree;
- `managed_activation.new_operation_id` pinned to one value;
- the same signed-in builder, membership and reviewed mapping authority
  (`test_managed_pipeline_activation.py:93-108`);
- the same mock model `Runtime` (`tests/unit/test_prose_generation.py:32-79`; the code variant used
  by `test_code_generation.py`).

In **world A**, the pre-kit path, the source is created by `pipeline.add_text`, `add_upload` or
`add_repo` with jobs held (`test_managed_pipeline_activation.py:146-155`). The test then calls the
coordinator directly with the arguments `run_managed_build` built at `0434aa1`: `:655-674` for prose
and `:689-746` for code, including the clone. The receipt is the return value.

In **world B**, the runtime path, the same `add_*` call runs with inline jobs
(`test_managed_pipeline_activation.py:129-144`). A refresh or rebuild calls
`managed_activation.run_managed_build(ctx, source_id=..., actor=..., operation_id=..., job_key=pipeline.job_key(source_id))`,
the call at `pipeline.py:361-367`. The receipt is captured by wrapping `record_build_receipt`
(`managed_activation.py:612-618`) with a spy that records and delegates.

**Compared, and required equal** (`published_snapshot(ctx, generation_id, receipt)`):

1. `store.generation_checksums(generation_id)`, element by element (`generations.py:966`).
2. Every `GenerationMember`, `GenerationEvidenceMember` and `NativeBinding` of the generation and
   every record they reference, walked as `generation_checksums` walks them (`:980-993`), as
   `model_dump(mode="json")`. This covers spans, derived views, dependencies, observations and
   prose extractions.
3. Native rows `_native_rows(kind, generation_id=...)` for `Passage`, `Symbol`, `DataObject` and
   `Commit` (the kinds at `:917`), canonical and sorted by id; and
   `_native_relationships(generation_id=...)` (`:893-964`).
4. The `Generation` row's dump without `registry_fingerprint`. It includes `coverage_json`,
   `manifest_hash`, `parser_version`, `linker_version`, `embedding_profile`, `created_at`,
   `published_at` and `status`.
5. The accepted manifest revision's `metadata_json`, which holds the configuration.
6. `IndexManifest` rows for the generation.
7. `IndexEvent` rows for the generation, compared on `id`, `kind`, `generation_id`, `aggregate_id`,
   `sequence`, `dedupe_key` and `created_at`.
8. The `BuildReceipt`, all seven fields.
9. The content-addressed raw object listing (`test_managed_pipeline_activation.py:59-63`).

**The one allowed difference:** `Generation.registry_fingerprint`, which is `None` in world A and
`default_registry().fingerprint()` in world B. `generation_checksums` does not hash it, because it
skips the `Generation` row (`generations.py:982`). Nothing is normalized: no generation id, and no id
namespaced by one.

**Outside the compared set**, because CK5 does not name them and they carry operational randomness
or wall time:

- `MaintenanceJob` rows (lease owner `uuid4`, `build_run.py:90`);
- `IndexEvent.payload_json` (the same credentials, `generations.py:1419-1427`);
- Source-row presentation fields and their `now_iso` timestamps;
- store meta epochs.

The runtime path writes no `Connector` or `SyncState` row. A test asserts that, so the comparison
hides no extra row.

**Fixtures.**

- *Prose (S5a):* `FIRST_TEXT` and `LONG_TEXT` pasted (`test_managed_pipeline_activation.py:35-39`); a
  `notes.md` upload; a refresh to `SECOND_TEXT`; an unchanged rebuild, which returns the pre-kit
  receipt with outcome other than `published`.
- *Code (S5b):* the `make_checkout` repository (`test_code_generation.py:141-156`) and its
  `ORDERS_V2` refresh; `ARCHIVE` and the single code file of `CODE_KINDS`
  (`test_managed_code_activation.py:59-80`); `build_code_capture_repository(files_per_language=2)`
  (`tests/fakes/code_capture_repo.py:248`); and a crash after a batch followed by a resume on both
  paths.

**LadybugDB acceptance (CK5's last clause).** Two runs:

- the CD9 CHECK line verbatim (`task-5-code-capture/GATES.md:66`, at
  `HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE=8`). Its `test_managed_code_activation.py` now
  dispatches through the lane. Its multi-hundred-file scenario calls the coordinator directly
  (`test_code_capture_acceptance.py:242`), which proves that the seam default leaves the reviewed
  path intact at the recorded size.
- `test_connector_local.py` and `test_connector_git.py` on LadybugDB, which prove the runtime path
  equal on the acceptance fixture's shape at N=2.

The runtime path at N=8 is open question 3.

## 7. File-by-file steps

### S5a (worktree `s5a`)

1. **Create** `tests/fakes/connector_parity.py` (§6 helpers) and `tests/unit/test_connector_local.py`
   (§8). Run the tests and save `/tmp/hippo-cdk-s5a-red.log`.
2. **Create** `src/hippo/connectors/lanes.py` (§3.2).
3. **Create** `src/hippo/connectors/local/__init__.py`, `local/connector.py` (§4.1, with the text and
   prose-file branches of `list_changes` and `fetch`) and `local/types.py` (an empty extension).
4. **Modify** `src/hippo/ingest/prose_generation.py`:
   - at `:482-495`, add the `registry_fingerprint` keyword;
   - at `:215-228`, extend `_generation` to set or adopt it;
   - at `:545`, pass the fingerprint.
5. **Modify** `src/hippo/ingest/managed_activation.py:655-674` as in §5, with imports of `lanes`,
   `local.connector` and the registry accessor (R-S1-2).
6. **Modify** `tests/unit/test_import_order.py:14-28`: append `"hippo.connectors.lanes"` and
   `"hippo.connectors.local.connector"`.
7. Run GREEN on Fake and LadybugDB (§9), run Ruff, commit.

### S5b (worktree `s5b`, after S5a merges)

1. **Extend** `tests/fakes/connector_parity.py` with the code worlds, and **create**
   `tests/unit/test_connector_git.py` (§8). Save `/tmp/hippo-cdk-s5b-red.log`.
2. **Modify** `src/hippo/connectors/local/connector.py`: the archive and code-file branches.
3. **Create** `src/hippo/connectors/git/__init__.py`, `git/connector.py` and `git/types.py`.
4. **Modify** `src/hippo/ingest/code_generation.py`:
   - at `:874-887`, add the keyword;
   - after `:970-973`, set or adopt the fingerprint.
5. **Modify** `src/hippo/ingest/managed_activation.py:677-746` as in §5.
6. **Modify** `tests/unit/test_import_order.py`: append `"hippo.connectors.git.connector"`.
7. Run GREEN on Fake, the CD1, CD2 and CD8 lines verbatim, the LadybugDB runs (§9), and Ruff, then
   commit.

## 8. RED tests

### `tests/unit/test_connector_local.py` (S5a)

- `test_local_descriptor_declares_no_templates_parsers_predicates_or_emit`
- `test_local_descriptor_covers_every_record_the_lanes_write`
- `test_local_list_changes_for_pasted_text_and_a_prose_file_is_one_complete_upsert`
- `test_local_fetch_returns_the_saved_bytes`
- `test_local_fetch_policy_equals_the_policy_the_prose_lane_mints`
- `test_local_probe_family_agrees_with_the_dispatch_for_every_eligible_kind`
- `test_the_sample_and_an_actorless_source_never_reach_a_lane`
- `test_add_text_and_a_prose_upload_dispatch_through_the_prose_lane`
- `test_run_coordinator_lane_passes_the_frozen_registry_fingerprint`
- `test_run_coordinator_lane_refuses_an_incomplete_inventory_or_an_unregistered_descriptor`
- `test_a_lane_failure_reaches_map_build_failure_with_its_type_unchanged`
- `test_pasted_text_through_the_runtime_is_byte_identical_to_the_pre_kit_path[first_text|long_text]`
- `test_a_prose_upload_through_the_runtime_is_byte_identical_to_the_pre_kit_path`
- `test_a_text_refresh_through_the_runtime_is_byte_identical_to_the_pre_kit_refresh`
- `test_an_unchanged_rebuild_through_the_runtime_returns_the_pre_kit_receipt`
- `test_registry_fingerprint_is_the_only_generation_field_that_differs`
- `test_a_failed_runtime_build_presents_the_pre_kit_public_failure[capture_too_large|model_unavailable]`
- `test_the_runtime_path_writes_no_connector_or_sync_state_row_and_no_connector_id`
- `test_build_plain_source_defaults_registry_fingerprint_to_none`
- `test_a_retried_prose_generation_keeps_its_stored_registry_fingerprint`

### `tests/unit/test_connector_git.py` (S5b)

- `test_git_descriptor_declares_no_templates_parsers_predicates_or_emit`
- `test_git_descriptor_covers_every_record_the_code_lane_writes`
- `test_git_list_changes_clones_through_repos_clone_repo_with_the_dispatch_depth`
- `test_git_list_changes_refuses_a_credentialed_url_before_cloning`
- `test_git_list_changes_lists_the_walk_with_the_head_revision`
- `test_the_checkout_is_discarded_however_the_build_ends`
- `test_local_list_changes_for_an_archive_and_a_code_file_lists_their_walk`
- `test_add_repo_and_code_uploads_dispatch_through_the_code_lane[repo|archive|file]`
- `test_repository_bootstrap_through_the_runtime_is_byte_identical_to_the_pre_kit_path`
- `test_repository_refresh_through_the_runtime_is_byte_identical_to_the_pre_kit_refresh`
- `test_archive_and_code_file_through_the_runtime_are_byte_identical_to_the_pre_kit_path[archive|file]`
- `test_the_capture_fixture_repository_through_the_runtime_is_byte_identical`
- `test_a_resumed_code_build_through_the_runtime_equals_the_pre_kit_resume`
- `test_build_code_source_defaults_registry_fingerprint_to_none`
- `test_a_reclaimed_code_generation_keeps_its_stored_registry_fingerprint`

Every existing file on the CK5 CHECK line passes **unchanged**. No assertion in
`test_prose_generation.py`, `test_code_generation.py`, `test_managed_pipeline_activation.py`,
`test_managed_code_activation.py` or `test_code_capture_acceptance.py` is edited.

## 9. GREEN commands, the CK5 CHECK line, LadybugDB

```bash
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_local.py tests/unit/test_prose_generation.py tests/unit/test_managed_pipeline_activation.py tests/unit/test_import_order.py tests/unit/test_layering.py -q -o addopts='' -W error > /tmp/hippo-cdk-s5a-green.log 2>&1; echo EXIT $?
HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_connector_local.py -q -o addopts='' -W error > /tmp/hippo-cdk-s5a-ladybug.log 2>&1; echo EXIT $?
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_local.py tests/unit/test_connector_git.py tests/unit/test_prose_generation.py tests/unit/test_code_generation.py tests/unit/test_managed_pipeline_activation.py tests/unit/test_managed_code_activation.py tests/unit/test_code_capture_acceptance.py -q -o addopts='' -W error > /tmp/hippo-cdk-s5b-ck5.log 2>&1; echo EXIT $?
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_code_generation.py tests/unit/test_managed_code_activation.py tests/unit/test_ingest_pipeline.py tests/unit/test_ingest_concurrency.py tests/unit/test_managed_pipeline_activation.py tests/unit/test_prose_generation.py tests/unit/test_build_authority.py -q -o addopts='' -W error > /tmp/hippo-cdk-s5b-cd8.log 2>&1; echo EXIT $?
HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_connector_local.py tests/unit/test_connector_git.py -q -o addopts='' -W error > /tmp/hippo-cdk-s5b-ladybug-parity.log 2>&1; echo EXIT $?
.venv/bin/ruff check src/hippo/connectors/lanes.py src/hippo/connectors/local src/hippo/connectors/git src/hippo/ingest/prose_generation.py src/hippo/ingest/code_generation.py src/hippo/ingest/managed_activation.py tests/fakes/connector_parity.py tests/unit/test_connector_local.py tests/unit/test_connector_git.py && .venv/bin/ruff format --check src/hippo/connectors/lanes.py src/hippo/connectors/local src/hippo/connectors/git src/hippo/ingest/prose_generation.py src/hippo/ingest/code_generation.py src/hippo/ingest/managed_activation.py tests/fakes/connector_parity.py tests/unit/test_connector_local.py tests/unit/test_connector_git.py
```

S5b also runs, verbatim from `ai_docs/gates/rag-it-all/task-5-code-capture/GATES.md`, the CD1 line
(`:18`), the CD2 line (`:24`) and the CD9 line (`:66`). The CD9 run is scheduled by the orchestrator:
at N=8 it recorded 1,615.56 s and 25.6 GiB RSS, and only one LadybugDB acceptance process should run
at a time on the machine.

**CK5 CHECK line: confirmed as written.** No file on it imports a test client at module level. The
ledger's EVIDENCE for CK5 should carry, beside the Fake line:

- the CD1 and CD2 runs;
- the CD9 run;
- the `test_connector_local.py` and `test_connector_git.py` LadybugDB run.

The Neo4j parity of the two connector files is root-owned.

**Ledger lines.** The CHECK line stands. The proposed CRITERIA wording keeps the SPEC review from
reading "through the runtime" as "through `connectors/sync.py`". Replace "dispatch through the runtime
with the local and git connectors" with "dispatch through the kit's connector interface
(`LocalConnector`, `GitConnector`) and the coordinator lane (`connectors/lanes.py`), whose derivation
half is the reviewed coordinator (plan deviation 1)".

## 10. Worktrees, merge order, do-not-touch

- **Worktrees:** `s5a`, `s5b`.
- **Merge order:** S1a → S1b → S2 → S3 → S5a → S5b.
  - S5 needs S1a (registry and fingerprint), S1b (`Generation.registry_fingerprint`) and S2 (the
    contract records). It touches nothing S3 owns. The design's S3 dependency is kept as merge order,
    so `lanes.py` joins an existing runtime package.
  - S5 can run beside S4a and S4b. Both S4a and S5a append to `tests/unit/test_import_order.py`
    `MODULES`, a one-line conflict the merger resolves by keeping both.
- **S5a owns:** `src/hippo/connectors/lanes.py`, `src/hippo/connectors/local/**`,
  `src/hippo/ingest/prose_generation.py`, `src/hippo/ingest/managed_activation.py` (released to S5b
  at merge), `tests/fakes/connector_parity.py`, `tests/unit/test_connector_local.py`, and the appended
  lines in `test_import_order.py`.
- **S5b owns:** `src/hippo/connectors/git/**`, `src/hippo/connectors/local/connector.py` (after S5a),
  `src/hippo/ingest/code_generation.py`, `src/hippo/ingest/managed_activation.py` (after S5a),
  `tests/fakes/connector_parity.py` (after S5a), `tests/unit/test_connector_git.py`, and the appended
  line in `test_import_order.py`.
- **Do not touch:**
  - `src/hippo/ingest/pipeline.py`, `readers.py`, `chunker.py`, `repo_capture.py`,
    `accepted_inputs.py`, `repos.py`;
  - `src/hippo/knowledge/**`, including `lifecycle.py`, `code_binding.py`, `code_history.py`,
    `staged_prose.py`, `staged_code.py`, `input_binding.py`, `build_authority.py`;
  - `src/hippo/store/**`, `src/hippo/context.py`, `src/hippo/status.py`, `src/hippo/codegraph/**`;
  - S2's and S3's `connectors/*` modules, S4's `testing.py` and scaffold;
  - `src/hippo/web/**`, `src/hippo/mcp_server.py`, `src/hippo/cli.py`, `src/hippo/remote.py`;
  - every existing test named on the CK5, CD1, CD2, CD8 or CD9 lines;
  - `docs/spec/*`, the ledgers, the checkpoint.

## 11. Decisions taken

5. **Local connector.**
   - `list_changes` is the saved ingress file for text and prose files, and `walk_tree` for archives
     and code files.
   - `fetch` reads the saved bytes. `fetch_policy` is the local curated grant. `probe` agrees with
     `is_code_source`.
   - The connector has no emit: its emission is the prose lane's `_materialize` (readers, chunker,
     `materialize_chunk_evidence`) or the code lane's `_prepare`, unchanged.
   - Capture stays `FileInput`.
   - The sample stays legacy.
6. **Git connector.**
   - `list_changes` refuses credentialed URLs, clones through `repos.clone_repo` into the operation
     checkout at `clone_depth`, reads the head, and walks.
   - Its emission is the code lane's `_prepare`, `bind_history` and `staged_code`, unchanged, so
     native rows are unchanged.
   - History is read by the coordinator.
   - The checkout lifecycle stays in `_run_code_build`.
7. **Switch.**
   - Inside `run_managed_build` and `_run_code_build` only, with no flag.
   - `pipeline.py`, `plan_dispatch`, `managed_eligibility`, the legacy lane and CD2 are untouched.
   - The coordinators gain `registry_fingerprint: str | None = None`.
8. **Byte identity.**
   - Two worlds with a pinned clock, ids and operation id.
   - The nine comparisons of §6.
   - The single allowed difference is `Generation.registry_fingerprint`.
   - The operational rows are named and excluded, and LadybugDB is proven by CD9 verbatim plus the
     connector parity files at N=2.
9. **No `Connector` or `SyncState` rows on coordinator lanes.** The lease and checkpoint are the
   coordinators' reviewed claim and manifest (§3.1).
10. **Sizing (decision 12).** S5a (prose) and S5b (code, git, LadybugDB).
11. **The `ingest` → `connectors` import edge is new, and confined to `managed_activation.py`.** It
    imports `connectors.lanes`, `connectors.local.connector` and `connectors.git.connector`. Those
    import only leaves: `connectors.local` imports `ingest.repo_capture` and `ingest.readers`, and
    `connectors.git` imports `ingest.repos`, never `managed_activation` or `pipeline`. The appended
    `test_import_order.MODULES` entries prove every order acyclic in a fresh interpreter. Putting
    the lanes under `ingest/` was rejected: the switch has to live where the kit is, so a later
    connector replaces a lane rather than moving it.

## 12. Requires from S1, S2 and S3

- **R-S1-1.** `Generation.registry_fingerprint: Text | None = None`, outside `identity_fields`, and
  persisted and read back identically on Fake, LadybugDB and Neo4j. Call sites:
  `prose_generation._generation`, `build_code_source`.
- **R-S1-2.** A process registry accessor, built-ins plus in-repo packages, frozen, with
  `fingerprint()`. Named `default_registry()` here; S1's name wins. Call site: `run_managed_build`.
- **R-S1-3.** Built-in registrations cover every object kind, artifact kind (`file`, `manifest`,
  `repository`, `history_event`) and locator kind the two lanes write today. That follows from CK1's
  "every value that is a `Literal` today". Call site: `run_coordinator_lane`'s descriptor check.
- **R-S2-1.** `ConnectorDescriptor` accepts empty `predicates`, `parsers` and `credentials`, and a
  connector class may omit `emit`. The protocol's `emit` is optional, or a coordinator-lane
  connector is a declared variant. Call sites: `LocalConnector`, `GitConnector`.
- **R-S2-2.** `ChangePage`, `Change`, `ExternalRef`, `RawFetch`, `PolicyObservation`,
  `Classification`, `ConnectorCapabilities`, `SyncCursor` and `Clock`, importable from
  `hippo.connectors.base`.
- **R-S2-3.** The name-level classifier over `readers.is_code_name` and `is_plain_prose_name`
  (S2 decision 3). Call site: `LocalConnector.probe`.
- **R-S2-4.** `hippo/connectors/__init__.py` imports neither `lanes`, `local` nor `git`, and nothing
  from `hippo.ingest.pipeline` or `managed_activation`. `managed_activation` imports
  `hippo.connectors.lanes` at module level, and `test_import_order.py` proves it acyclic.
- **R-S3.** Nothing functional. Open question 2 asks whether `sync.py` should re-export
  `run_coordinator_lane`.

## 13. Design deviations

1. **Design §7 steps 3 and 5–8, for these two connectors.** They are the reviewed coordinators, not
   a per-revision `emit`, the §6 binder and `staged_records`. §3.1 gives the five reasons, each with
   its anchor. Design §11 already says the port wraps them without changing their output.
2. **Design §7 steps 1, 2 and 4.** They map onto the coordinator's fenced claim, a complete local
   inventory and the manifest's prior receipt. No `Connector` or `SyncState` row is written, because
   of the authorization-epoch bump, the open-mode provider refusal, `connector_id` in artifact
   identity, and the HTTP-only `ProviderURL`.
3. **Design §7's sentence "its `fetch` reads the captured file".** Capture stays inside the coordinator
   through `FileInput`, which keeps the changed-during-capture refusal
   (`test_managed_pipeline_activation.py:545`). `fetch` reads the saved file, is pinned equal, and is
   not called by the lane.
4. **Design §9's in-repo layout.** `connectors/local` and `connectors/git` have no `templates.py`
   and no `fixtures/`: they have no emit and no goldens. Their proof is the parity suite.
5. **Design §13's S5 row.**
   - It names `ingest/pipeline.py`, which does not change.
   - It omits `ingest/prose_generation.py` and `ingest/code_generation.py`, which each gain one
     keyword argument.
   - It omits `tests/unit/test_import_order.py`, which gains appended module names.
6. **The brief lists the sample among the paths to port.** It stays legacy, because it has no
   managed pre-kit path (`pipeline.py:191-199`, `managed_activation.py:137-153`).
7. **Design §3's configuration carve-out is extended to the descriptor's `version` and `parsers`.**
   `run_coordinator_lane` refuses non-empty `parsers`, although the code lane runs tree-sitter. The
   ported descriptors declare `parsers=()` and a version that enters no configuration, for two
   reasons. `f7b14ee` requires their configuration to stay byte for byte what the lanes write today.
   And the code lane already records its grammar profiles and walker rules in its own configuration
   (`code_generation.py:299-301`).

## 14. Open questions

1. **Ownership of `ingest/prose_generation.py` and `ingest/code_generation.py`** for the
   `registry_fingerprint` keyword. S5a takes the first and S5b the second. The orchestrator ratifies,
   and confirms S1 does not also edit them.
2. **Whether `connectors/sync.py` should re-export `run_coordinator_lane`**, so that "the runtime" is
   one module. That would be a one-line edit in an S3 file after S3 merges.
3. **LadybugDB at the recorded size through the runtime.** This plan proves the runtime path equal at
   N=2 on the acceptance fixture's shape and reruns CD9 at N=8, where the scenario calls the
   coordinator directly. A runtime-path N=8 run costs another ~27 minutes and ~26 GiB. Recommendation:
   not required, because the lane adds no store work.
4. **Future `Connector` rows for `local` and `git` instances**, if Task 15's status surfaces list
   them. They should be created once, outside any build window: at schema bootstrap or by an operator
   action. Never inside `run_managed_build`.

## Plan verification checklist

| Interface | Implementation | Registration | Plan step |
| --- | --- | --- | --- |
| `CoordinatorLane`, `run_coordinator_lane` | `connectors/lanes.py` | called from `managed_activation.run_managed_build` | S5a 2, 5 |
| `LocalConnector` | `connectors/local/connector.py` | constructed in `run_managed_build`, `_run_code_build` | S5a 3, S5b 2 |
| `GitConnector` | `connectors/git/connector.py` | constructed in `_run_code_build` | S5b 3, 5 |
| `registry_fingerprint` keyword | `prose_generation.py`, `code_generation.py` | passed by the lanes | S5a 4, S5b 4 |

| Regression hotspot | Old location | Proof |
| --- | --- | --- |
| A file changed during capture refuses | `test_managed_pipeline_activation.py:545` | unchanged file on the CK5 line |
| The clone monkeypatch applies to managed clones | `test_managed_code_activation.py:129-140` | `test_git_list_changes_clones_through_repos_clone_repo_with_the_dispatch_depth` |
| Legacy cleanup never runs for a managed attempt | CD8 line `GATES.md:60` | rerun verbatim |
| A converting source serves legacy until publication | CD2 line `GATES.md:24` | rerun verbatim |
