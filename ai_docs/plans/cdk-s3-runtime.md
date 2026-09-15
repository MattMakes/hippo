# CDK S3: the sync runtime, the generic staged writer, bounded HTTP and credentials

> **For Claude:** execute with `dev:execute-plan`, one task per worker (S3a, S3b, S3c). Every task is
> test-first: write the RED tests, save the RED log, implement, save the GREEN log.

**Status:** proposed implementation contract for gate CK3 of `ai_docs/gates/rag-it-all/cdk/GATES.md`.
Nothing here is implemented. Design of record: `docs/spec/connector-developer-kit.md` at `ef143b1`
(sections 7, 8, 9, 10, 12, 13). Every `src/` and `tests/` anchor was read at `ef143b1`; `git diff --stat
0434aa1 ef143b1 -- src tests` is empty, so they equal the brief's `0434aa1`. S2's names come from
`ai_docs/plans/cdk-s2-contract.md`, S1's from `ai_docs/plans/cdk-s1-registry.md`, S4's expectations
from `ai_docs/plans/cdk-s4-kit.md` (section 9), as those plans stood during this planning session.

**Goal:** one runtime, `hippo.connectors.sync.sync_connector`, that drives any connector through the
nine steps of the design's section 7 (lease, page, capture, checkpoint, emit, bind, stage, publish,
reconcile) with failure injection at every durable boundary; a generic staged writer
(`knowledge/staged_records.py`) under the fencing the prose and code writers use; a bounded HTTP client
with the six error classes and recording/replay; credential references; the per-thread emit guard; and a
fixture connector that proves it on Fake and LadybugDB.

**Architecture:** the runtime is a third coordinator beside `build_plain_source` and `build_code_source`.
It reuses their machinery rather than copying it: `BuildRun` for the failure latch, heartbeat and
cancellation (`ingest/build_run.py:70-201`); `capture_build_authority`, `bind_inputs` and `rebaseline`
(`knowledge/build_authority.py:378-465`); `generation_for_inputs` (`knowledge/lifecycle.py:15`); the
store's claim, reclaim, write, seal and publication compare (`store/generations.py:320-480`,
`:1134-1151`, `:1269-1432`). What is new is the part before a generation exists: a sync lease on a
`SyncRun` row, per-page durable capture of artifacts, revisions and policies, a cursor checkpoint in
`SyncState`, and deletion inferred only from a completed inventory. `knowledge` never imports
`connectors`: the writer takes knowledge records only, and `sync.py` converts S2's `BoundBatch`.

**Tech stack:** Python 3.12 (`requires-python >= 3.11`), httpx 0.28.1 (`pyproject.toml:14`) with
`MockTransport`, Pydantic 2.13.5, the existing store backends (Fake, LadybugDB 0.15.3, Neo4j).

**Wiring manifest:** `sync_connector` → called by S4's `run_case` and `hippo connector sync`, and later by
S5's dispatch and Task 9A's scheduler; never by a production route in this slice. `guard.forbid_effects`
→ used by `sync._emit` and re-exported by S4's `testing.purity_guard`. `http.ProviderClient` → used by
connectors (the fixture connector first). `credentials.resolve` / `redact_url` → used by
`ProviderClient` and S4's recorder. `staged_records.write_staged_records` and its cores → used by
`sync._stage`. The `connector` generation profile → selected by `validate_generation_profile` from the
manifest's metadata key.

**Regression hotspots:** the prose and code coordinators' behaviour and their suites
(`tests/unit/test_prose_generation.py`, `test_code_generation.py`) must not change when S3b moves five
lane-neutral helpers into `build_run.py`; the two existing generation profiles validate byte for byte as
before (`knowledge/generation_profiles.py:202-277`); `BuildAuthority` for `text`, `file`, `repo` and
`archive` sources is unchanged (`build_authority.py:77-105`, `:248-293`); the active generation is never
deleted, and `_clear_passages`, `delete_passages_for_source` and `delete_code_nodes_for_source` are never
called (code-capture plan section 10).

---

## 0. How to read this plan

- The form is the code-capture plan's: scope, seams, public API, the design decisions this slice makes,
  the task split, the gate, ownership, decisions, deviations and questions.
- DDD vocabulary, no DDD workspace: the runtime is an application service of the `hippo.connectors`
  bounded context; `SyncRun`/`SyncState` are its aggregate state; the store is the repository; the
  connector and `ProviderClient` are adapters. No `ddd/` folder is written.
- "Decided by S3" marks a choice the design leaves open; section 15 lists every one.
- Signatures and messages are exact; bodies are described with the anchor they mirror.

## 1. Outcome and scope

**In scope.**

- `src/hippo/connectors/guard.py`: the per-thread effects guard and `EmitSideEffect` (S3a).
- `src/hippo/connectors/http.py`: `ProviderClient`, `HttpLimits`, the six error classes,
  `record_transport`, `replay_transport` (S3a).
- `src/hippo/connectors/credentials.py`: `CredentialRef`, `ResolvedCredential`, `resolve`,
  `redact_url`, `refuse_inline_secrets` (S3a).
- `src/hippo/knowledge/staged_records.py`: the generic staged writer (S3b).
- `src/hippo/knowledge/generation_profiles.py`: the `connector` generation profile (S3b).
- `src/hippo/knowledge/build_authority.py`: admission of `connector` sources (S3b).
- `src/hippo/ingest/build_run.py` and `src/hippo/ingest/code_generation.py`: five lane-neutral helpers
  move from the code coordinator into `build_run.py`, re-bound under their old names (S3b).
- `src/hippo/connectors/sync.py`: the runtime (S3c).
- `tests/fakes/fixture_connector/`: the fixture connector package in the design's section 9 layout, with
  its in-memory HTTP provider (S3c, ruling R10).

**Out of scope.** Scheduling (Task 9A's maintenance worker decides when to call `sync_connector`; S3
provides `reconcile_due`); the `hippo connector` commands and the test kit (S4); pipeline dispatch for
`add_text`, `add_upload`, `add_repo` (S5); connector routes and MCP tools (S6, Task 15); webhooks;
out-of-process connector isolation (design section 14, decision 2); unit embeddings (section 8.7).

## 2. Existing seams

| Seam | Use or required boundary |
| --- | --- |
| `ingest/build_run.py:70-201` `BuildRun` (`check` `:108-135`, `renew` `:137-163`, `start`/`pause` `:165-177`, `adopt` `:190-193`) | The runtime's run state. `renew` renews only the generation job, so `sync.ConnectorRun(BuildRun)` extends it to renew the sync lease too (section 5.1). |
| `build_run.py:45-56` `BuildReceipt`; `:59-67` `credentials`, `authority_fields` | Reused unchanged. |
| `ingest/code_generation.py:602-614` `_instant`, `:617-634` `_operation_generation`, `:637-651` `_receipt`, `:654-679` `_prior_receipt`, `:759-771` `_rebaseline` | Lane-neutral except `_receipt`'s `captured.accepted.manifest.sha256`. S3b moves them to `build_run.py` (section 8). Tests patch only `code_generation._publish` (`test_code_generation.py:830`), so re-binding the old names keeps every seam. |
| `code_generation.py:685-756` `_install`, `:778-809` `_write`, `:820-856` `_publish`, `:1021-1035` failure path | The order of store calls the runtime's install, write, publish and failure steps follow line for line (sections 5.6-5.8). |
| `code_generation.py:545-551` `_vectors`; `prose_generation.py:564-566`, `:587` | Passage vectors through `ProfiledEmbeddings` (`knowledge/embedding_profile.py:369`, `embed` `:423`, `validate` `:416`) and the disposable `EmbeddingCache`. |
| `knowledge/build_authority.py:19` `BUILD_SOURCE_KINDS`, `:23` `ACCEPTED_ARTIFACT_KINDS`, `:27-29` `PLANNED_POLICY_SCOPES`, `:77-105` `_source_control`, `:248-293` `_inventory` (`:268-277` refuses `connector_id`, `:287` refuses non-`local_curated`) | Closed to connector sources today; S3b opens them for `kind="connector"` only (section 7). |
| `build_authority.py:295-358` `check_local`, `:378-394` `bind_inputs`, `:396-451` `rebaseline`, `:458-465` `capture_build_authority` | Reused unchanged. |
| `knowledge/access.py:458-459` | An internal (trusted-local) audience is granted every workspace policy, including `mode="unknown"`; a reader is not (`:460`). This is why connector syncs run as `BuildActor.trusted_local()` (section 5.5). |
| `access.py:476-480` | A provider policy with no deadline is unreadable, so captured policies carry `expires_at` (S2 `policy_record`). |
| `access.py:514`, `:529` | Both the artifact's and the span's policy are checked: narrowing an `Artifact.policy_id` takes effect at once (section 6.3). |
| `knowledge/generation_profiles.py:36-39` profiles; `:202-277` `validate_generation_profile` (`:232-233` refuses remote artifacts, `:241-249` the accepted-inputs manifest convention, `:253-255` closed profile set, `:259` dispatch) | S3b adds the `connector` profile without changing the other two paths (section 7.2). |
| `knowledge/staged_code.py:29` `PAYLOAD_CEILING_BYTES`, `:45` `CLEANUP`, `:281-291` `_epochs`, `:294-315` `_local` (reads only `prepared.generation`), `:338-344` `_Group`, `:485-496` `_immutable_native`, `:557-573` `ResumePlan`, `:600-665` `probe_staged_rows`, `:671-715` `_inventory`, `:718-736` `_seal`, `:739` `write_staged_code` | The writer template. `staged_records.py` imports `_epochs`, `_local`, `_Group`, `_immutable_native`, `ResumePlan`, `CLEANUP` and `PAYLOAD_CEILING_BYTES` instead of copying them (section 7.1). |
| `knowledge/staged_prose.py:69-126`, `:185-203` | The prose writer, unchanged; its `_local` reads `prepared.inputs.generation` and so does not fit a record bundle. |
| `store/generations.py:128-136` `_lock_source`; `:138-143` `begin_managed_source`; `:166-224` `apply_source_tombstone`; `:232-246` `_tombstoned` | Serialization, the managed flip and the tombstone barrier. |
| `generations.py:320-342` `claim_generation_build`; `:344-380` `reclaim_generation_build`; `:382-404` `_check_build`; `:406-422` `renew_generation_build`; `:430-466` `fail_generation_build` (codes `build_failed`, `build_cancelled` only, `:438`) | The generation build lease, reused unchanged. |
| `generations.py:469-478` `generation_write`; `:480-521` `bind_generation_embedding_profile`; `:1134-1151` `seal_generation`; `:1153-1159` `validate_generation_seal` | Reused unchanged. |
| `generations.py:1269-1364` `publish_staged_generation` (`:1315` suppression, `:1322` tombstoned artifact); `:1385-1432` `_publish_generation` with the one `IndexEvent(kind="published")` at `:1419-1427` | The publication compare and the append-lane event. No other `IndexEvent` writer exists in `src/`. |
| `generations.py:594-706` `_check_knowledge_write`, content writes at `:620-637` | An `Artifact` or `ArtifactRevision` write needs build authority only while the source has a *running* rebuild job. Capture therefore runs before the runtime claims its build (section 6.2). |
| `store/authorization.py:113-114` `RECORD_EPOCHS` (`Connector`, `AccessPolicy` are authorization records; `SyncState`, `SyncRun` bookkeeping); `:183-193` `record_mutation` (`:187` an `Artifact` or `Generation` put flips `managed`; `:188-193` a policy or an `Artifact.policy_id`/`deleted_at` change bumps the authorization epoch) | The policy epoch the runtime moves on purpose, and the epoch arithmetic of section 6.3. |
| `store/knowledge.py:151-158` `MUTABLE_FIELDS` (`Artifact` `:155`, `SyncState` `:158`, `SyncRun` `:159-169`); `:225-246` `SCOPED_FIELDS` (no `source_id`); `:760-779` `put_knowledge` (`:772` immutable refusal); `:781-822` `update_knowledge` (`:811-813` counters never decrease) | The sync lease and checkpoint are `update_knowledge` calls on one row each, looked up by id (section 5.1). |
| `store/snapshots.py:223-253` `_collection_block` (`"snapshot_reference"` at `:242`); `:329-342` `collect_generation`; `:344-379` `recover_generation_builds` | Recovery of a crashed attempt, and the live-session proof of section 11. |
| `knowledge/model.py:670-678` `SyncState`; `:681-713` `LeasedWork` (`lease_pair` `:707-713`); `:716-719` `SyncRun`; `:972-982` `IndexEvent` | The sync lease and cursor records, used as they are. |
| `knowledge/query_access.py:82-91` `validate` ("Permissions changed; repeat the query"); `:126-164` `query_session` | A session opened before an epoch change refuses to validate; a new session sees the last published generation. |
| `knowledge/source_lifecycle.py:48` `tombstone_managed_source` | Retiring a whole partition source, reused unchanged (section 6.5). |
| `knowledge/raw_artifacts.py:198-203` `put_bytes`, `:260-264` `read_bytes` | Durable, content-addressed capture outside transactions. |
| `knowledge/identity.py:75-111` `normalize_provider_url`; `:136-139` `artifact_identity` | Instance URLs, and artifact ids for a delete change without a fetch. |
| `knowledge/public_errors.py:24-28`, `:118-140` | A managed caller maps an unknown exception to `operation_failed`. `knowledge` may not import `connectors`, so runtime errors subclass rows already in the table (`BuildBusy`, `BuildCancelled`) or fall through (section 5.9). |
| `ingest/managed_activation.py:125-155` `managed_eligibility` | A `connector` source is `managed` once its first artifact is captured and `unsupported` before; S3 adds no dispatch (S5). |
| `store/memory.py:47-87` `create_source`; `:113` `list_sources` (Ladybug `:725`, `:825`) | How `connector_source` creates or finds a partition's Source. |
| `store/generations.py:481-518`, `:1135-1148`, `:1280`/`:1351`; `store/snapshots.py:65-98`; `store/migrations.py:625-656` | The existing production failpoint convention: a keyword `fault_hook=None` called with a label. The runtime uses the same convention (section 9). |
| `tests/unit/test_temporal_evidence.py:1338` `_bytes`, `:1454-1475` | The byte-identity assertion after an injected failure, reused as the pattern for CK3's checks. |
| `tests/unit/test_code_generation.py:668`, `:700` | Test-side crashes by patching `staged_code._write_batch`; the runtime's tests do the same for `staged_records._write_batch`. |
| `tests/unit/test_staged_code_writer.py:1128-1136` | The LadybugDB close-and-reopen proof. |
| `tests/unit/test_prose_generation.py:86-131` `setup`; `tests/conftest.py:187-260` `store`, `ollama`, `ctx` | Test harness: a real `Ollama` over `httpx.MockTransport`, a disposable raw store, a membership, a builder. |
| `docs/rag_it_all.md:554-568` (backoff `:566`), `:623` (defaults), `:627-645` (out-of-order and deletion rules; `:637` delete barrier, `:638` failed page, `:639` 403, `:640` complete inventory), `:552` (six error classes), `:885-891` (credentials and redirects) | The earlier plan's runtime rules the design absorbs. |

## 3. Requires from S1 and S2

**From S1** (`cdk-s1-registry.md` sections 5.2, 6.1, 10):

| # | S3 uses | S1 reference |
| --- | --- | --- |
| RS1-1 | `current_registry()`, `use_registry()`, `extension_scope()`, `Registry.freeze()`, `Registry.frozen`, `Registry.fingerprint()`; no loader (S4 owns discovery, ruling R15) | section 5.2, rulings R15, R16 |
| RS1-2 | `Generation.registry_fingerprint` and `generation_for_inputs(..., registry_fingerprint=...)`, which never enters the manifest | D21 |
| RS1-3 | `Connector.classification_json: Json = "{}"`, a JSON object, mutable, outside identity, in schema v8 | D22 |
| RS1-4 | `Unit` on every backend: exact `GenerationEvidenceMember`, read by `generation_id`, the write guard (lease, the generation's own passage, a selected span), hashed into the `evidence` checksum, removed by collection | D16 |
| RS1-5 | `AssertionVersion.unit_id` must name an existing `Unit` (write order: native `Passage`, then `Unit`, then `AssertionVersion`) | D18, section 10 |
| RS1-6 | Units hidden from non-internal readers | D16 |

**From S2** (`cdk-s2-contract.md` section 13): `capture_records`, `policy_record`, `bind_batch`,
`merge_bound`, `BindContext`, `BoundBatch`, `BoundPassageRow`, `CapturedRevision`, `EmissionCoverage`,
`descriptor_configuration`, `BINDER_VERSION`, `RENDER_RULE_VERSION`, `KEY_RULE_VERSION`,
`CLASSIFIER_VERSION`, `ContractError`, and the `base.py` records (`Connector`, `ConnectorDescriptor`,
`ChangePage`, `Change`, `ExternalRef`, `SyncCursor`, `RawFetch`, `PolicyObservation`, `TypeMapping`,
`PartitionClassification`, `Classification`, `RevisionInput`, `EmissionBatch`, `ParseFailure`).
`bind_batch` refuses any registry but the frozen `current_registry()` (S2 decision 32, ruling R16), so
the runtime passes the registry it was given only after checking it is the current one.

**Rulings applied** (`ai_docs/plans/cdk-rulings.md` at `166bf00`): R3 (no lane seam in `sync.py`; S5b
adds its re-export), R5 (no slice writes the local and git `Connector` rows), R6 (rendered facts reach
retrieval as derived passages; identity-only foreign endpoints; deletion only from a completed
inventory), R10 (the fixture connector lives at `tests/fakes/fixture_connector/`), R11 (one token
counter, S2's), R12 (S3 writes `Connector.classification_json`), R15 (no loader in S3), R16
(`current_registry()`), R21 (classification written only on change), R2 (`code_generation.py` handoff). Section 13 answers every R-S3 item of
the S4, S5 and S6 plans by name.

## 4. Public API

### 4.1 `connectors/guard.py` (S3a)

```python
class EmitSideEffect(RuntimeError):
    """emit touched the network, a model, a subprocess, a thread or the clock."""


@contextmanager
def forbid_effects() -> Iterator[None]: ...
```

### 4.2 `connectors/credentials.py` (S3a)

```python
class CredentialError(ValueError):
    """A credential reference cannot be resolved; the message names the reference, never a value."""


@dataclass(frozen=True, slots=True)
class CredentialRef:
    scheme: Literal["env", "file"]
    name: str

    @classmethod
    def parse(cls, value: str) -> "CredentialRef": ...


@dataclass(frozen=True, slots=True)
class ResolvedCredential:
    ref: CredentialRef
    _secret: str = field(repr=False)

    def authorization(self, scheme: Literal["Bearer", "Basic", "Token"] = "Bearer") -> tuple[str, str]: ...


def resolve(
    ref: str, *, environ: Mapping[str, str] | None = None, max_bytes: int = 64_000
) -> ResolvedCredential: ...


def redact_url(url: str) -> str: ...


def refuse_inline_secrets(config: BaseModel) -> None: ...
```

### 4.3 `connectors/http.py` (S3a)

```python
ERROR_CLASSES = ("authentication", "forbidden", "not_found", "throttled", "transient", "malformed")


class ProviderError(Exception):
    error_class: ClassVar[str]

    def __init__(self, *, url: str, status: int | None, attempts: int, retry_after: float | None = None): ...


class ProviderAuthenticationError(ProviderError): ...  # 401


class ProviderForbiddenError(ProviderError): ...  # 403


class ProviderNotFoundError(ProviderError): ...  # 404, 410


class ProviderThrottledError(ProviderError): ...  # 429


class ProviderTransientError(ProviderError): ...  # 408, 5xx, httpx.TransportError


class ProviderMalformedError(ProviderError): ...  # any other status, a redirect, an oversize or invalid body


@dataclass(frozen=True, slots=True)
class HttpLimits:
    connect_timeout: float = 10.0
    read_timeout: float = 30.0
    max_response_bytes: int = 8_000_000
    max_attempts: int = 5
    max_total_seconds: float = 300.0
    backoff_base_seconds: float = 0.5
    backoff_cap_seconds: float = 300.0
    max_retry_after_seconds: float = 300.0


class ProviderClient:
    def __init__(
        self,
        base_url: str,
        *,
        limits: HttpLimits = HttpLimits(),
        transport: httpx.BaseTransport | None = None,
        credential: ResolvedCredential | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = utc_now,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None: ...

    def get_bytes(
        self, path: str, *, params: Mapping[str, str] | None = None
    ) -> tuple[bytes, Mapping[str, str]]: ...

    def get_json(self, path: str, *, params: Mapping[str, str] | None = None) -> JsonValue: ...

    def close(self) -> None: ...


def record_transport(case_dir: Path, inner: httpx.BaseTransport) -> httpx.BaseTransport: ...


def replay_transport(case_dir: Path) -> httpx.MockTransport: ...
```

### 4.4 `knowledge/staged_records.py` (S3b)

```python
@dataclass(frozen=True, slots=True)
class StagedPassage:
    row: Mapping[str, object]  # a BoundPassageRow.native_row() without "embedding"
    embedding: tuple[float, ...]

    @property
    def id(self) -> str: ...

    def native_row(self) -> dict: ...


@dataclass(frozen=True, slots=True)
class RecordBundle:
    generation: k.Generation
    configuration_json: str
    accepted_pairs: tuple[tuple[k.Artifact, k.ArtifactRevision], ...]
    manifest_revision: k.ArtifactRevision
    revision_members: tuple[k.GenerationMember, ...]
    spans: tuple[k.EvidenceSpan, ...]
    objects: tuple[k.KnowledgeObject, ...]
    observations: tuple[k.ObjectObservation, ...]
    views: tuple[k.RetrievalView, ...]
    derived_records: tuple[k.DerivedRecord, ...]
    derived_dependencies: tuple[k.DerivedDependency, ...]
    passages: tuple[StagedPassage, ...]
    units: tuple[k.Unit, ...]
    assertions: tuple[k.Assertion, ...]
    versions: tuple[k.AssertionVersion, ...]
    supports: tuple[k.AssertionSupport, ...]
    evidence_members: tuple[k.GenerationEvidenceMember, ...]


def _write_batches(bundle: RecordBundle, *, batch_size: int, resume: ResumePlan | None = None): ...


def _write_batch(store, bundle: RecordBundle, batch: tuple, **authority) -> None: ...


def probe_staged_records(store, bundle: RecordBundle) -> ResumePlan: ...


def _seal(store, bundle: RecordBundle, **authority) -> k.IndexManifest: ...


def write_staged_records(
    store,
    bundle: RecordBundle,
    *,
    job_id: str,
    lease_owner: str,
    fencing_token: int,
    expected_authorization_epoch: int,
    expected_suppression_epoch: int,
    check: Callable[[], None],
    batch_size: int = 128,
    resume: ResumePlan | None = None,
) -> k.IndexManifest: ...
```

### 4.5 `knowledge/generation_profiles.py` additions (S3b)

```python
CONNECTOR_PROFILE = "connector"
GENERATION_PROFILES = (PLAIN_PROSE_PROFILE, CODE_PROFILE, CONNECTOR_PROFILE)
CONNECTOR_MANIFEST_EXTERNAL_ID = "connector-inventory-v1"
CONNECTOR_MANIFEST_KEY = "connector_inventory_v1"
```

### 4.6 `ingest/build_run.py` additions (S3b)

```python
def adopt_capture_instant(store, gen, candidate): ...  # was code_generation._instant


def operation_generation(store, gen, operation_id): ...  # was code_generation._operation_generation


def published_receipt(store, gen, manifest_sha256, outcome, job=None, *, resumed=0, rebaselines=0): ...


def prior_receipt(run, gen, manifest_sha256, operation_id): ...  # was code_generation._prior_receipt


def rebaseline_between_batches(run): ...  # was code_generation._rebaseline
```

### 4.7 `connectors/sync.py` (S3c)

```python
SYNC_RULE_VERSION = "cdk-sync-v1"
CONNECTOR_SOURCE_KIND = "connector"
CONNECTOR_PARSER_VERSION = "cdk-connector-v1"
FAULT_POINTS = (
    "lease",
    "after_page",
    "after_fetch",
    "before_checkpoint",
    "after_checkpoint",
    "after_emit",
    "after_bind",
    "after_install",
    "before_batch",
    "before_seal",
    "before_publish",
    "after_publish",
)


class ConnectorSyncRefused(ValueError): ...


class ConnectorSyncBusy(BuildBusy): ...


class ConnectorSyncCancelled(BuildCancelled): ...


class ConnectorContractViolation(ValueError): ...


@dataclass(frozen=True)
class SyncOptions:
    max_pages: int = 1000
    max_changes_per_page: int = 1000
    max_fetch_bytes: int = 8_000_000
    max_run_bytes: int = 256_000_000
    max_batch_records: int = 50_000
    emit_workers: int = 2
    emit_timeout_seconds: float = 30.0
    policy_ttl_seconds: float = 600.0
    reconcile: bool = False
    reconcile_interval_seconds: float = 86_400.0
    batch_size: int = 128
    max_batch_payload_bytes: int = 64 * 1024 * 1024
    lease_duration_seconds: float = 300.0
    renewal_interval_seconds: float = 30.0


@dataclass(frozen=True)
class SyncReceipt:
    source_id: str
    partition: str
    outcome: Literal["published", "already_current", "already_published", "no_changes"]
    generation_id: str | None
    build: BuildReceipt | None
    pages: int
    changes: int
    deleted: int
    policy_updates: int
    inventory: Literal["not_scanned", "partial", "complete"]
    coverage: Mapping[str, object]


def ensure_connector(
    store,
    *,
    workspace_id: str,
    kind: str,
    instance_url: str,
    config: BaseModel,
    credential_ref: str | None = None,
    enabled: bool = True,
) -> k.Connector: ...


def connector_source(
    store,
    *,
    connector: k.Connector,
    partition: str,
    name: str,
    owner_id: str | None = None,
    access_role_id: str | None = None,
) -> str: ...


def store_classification(store, *, connector: k.Connector, classification: Classification) -> k.Connector: ...


def load_classification(connector: k.Connector, partition: str) -> PartitionClassification: ...


def reconcile_due(state: k.SyncState | None, *, now: datetime, interval: timedelta) -> bool: ...


def sync_connector(
    ctx,
    connector: Connector,
    *,
    config: BaseModel,
    partition: str,
    actor: BuildActor,
    registry: Registry,
    options: SyncOptions,
    raw_store: RawArtifactStore,
    embedding_spec: EmbeddingSpec,
    operation_id: str,
    should_stop: Callable[[], bool],
    on_progress: Callable[[BuildProgress], None] | None = None,
    on_batch: Callable[[RevisionInput, EmissionBatch], None] | None = None,
    embedding_cache: EmbeddingCache | None = None,
    fault_hook: Callable[[str], None] | None = None,
) -> SyncReceipt: ...
```

## 5. The runtime's nine steps (brief decision 7)

`sync_connector` runs the steps below as named private functions in `sync.py`, in this order. The
shape is `build_code_source` (`code_generation.py:874-1037`): argument checks, `ConnectorRun`
construction, the steps, and one `except BaseException` path that pauses the heartbeat and calls
`fail_generation_build` for an installed, unpublished attempt (`:1021-1035`).

Entry checks, each a `ConnectorSyncRefused` with the exact message:

- `registry is current_registry() and registry.frozen`: `Sync requires the frozen current registry`
  (ruling R16; the caller installs it with `use_registry()` or extends it with `extension_scope()`, and
  S4's loader builds it, ruling R15, so S3 plans no loader);
- `connector.descriptor.capabilities.derivation == "emit"`: `A coordinator-lane connector syncs through
  its lane, not sync_connector` (ruling R1; S5's `run_coordinator_lane` is the other entry);
- `connector.descriptor.validate_against(registry)` passes, and `type(config) is
  connector.descriptor.config_model`;
- `actor.kind == "trusted_local"`: `Connector syncs run as the trusted local maintenance actor`
  (section 5.5 explains why);
- `ctx.store.in_ambient_transaction()` is false: `Sync requires no ambient transaction`;
- `operation_id` and `should_stop` as `build_code_source` checks them (`:902-910`).

`credentials.refuse_inline_secrets(config)` runs before any provider call. The mapping `emit` receives is
the stored probe result, `load_classification(connector_row, partition).mapping`, never a fresh guess
(design section 2); with no stored classification for the partition the sync refuses before capture:
`Probe the connector before syncing partition {partition}`. `mapping.validate_against(registry)` runs
next, so a mapping whose kinds are no longer registered refuses too.

### 5.1 Step 1, lease: `_lease(run, target, options) -> k.SyncRun`

**Records.** One `SyncRun` row per connector partition, reused across runs, so it is found by id and
never by a whole-table scan (`SCOPED_FIELDS` has no `source_id`, `store/knowledge.py:225-238`):
`SyncRun(connector_id=connector_row.id, source_id=source_id, scope_key=f"source:{source_id}:{partition}",
run_key=partition, input_fingerprint=SYNC_RULE_VERSION, ...)` (identity `model.py:716-719`). One
`SyncState(connector_id, partition_key=partition)` row holds the cursor (`model.py:670-678`).

**Claim**, in one `store.transaction()` with `store._lock_source(source_id)` (`generations.py:128-136`):

1. refuse a tombstoned source (`store._tombstoned`, `generations.py:232-246`): `Source is tombstoned`;
2. `store.recover_generation_builds(source_id=source_id)` (`snapshots.py:344-379`), so a crashed run's
   expired build lease is released before capture writes (section 6.2);
3. read the `SyncRun` by id. If it is `status="running"` with `lease_expires_at > store._now()` and another
   owner, raise `ConnectorSyncBusy("Connector partition already has a live sync holder")`;
4. otherwise `put_knowledge` (first run) or `update_knowledge` it with `status="running"`,
   `phase="fetch"`, `lease_owner=run.owner`, `lease_expires_at=now + lease_duration`,
   `fencing_token=previous + 1`, `attempt_count=previous + 1`, `retry_at=None`, `error_code=None`,
   `cursor_json={"operation_id": operation_id}`. `MUTABLE_FIELDS["SyncRun"]` allows every one of these
   (`store/knowledge.py:159-169`), and the counters never decrease (`:811-813`);
5. `put_knowledge` the `SyncState` if absent.

`SyncRun` and `SyncState` are bookkeeping records (`authorization.py:113-140`): no epoch moves.

**Fence check** `_check_sync(store, held)`: the stored row's `lease_owner`, `fencing_token` and
`status="running"` equal the held ones and `lease_expires_at > store._now()`; otherwise
`ConnectorSyncBusy("Sync lease was lost")`. It runs inside every checkpoint and the publication
transaction.

**Renewal.** `ConnectorRun(BuildRun)` overrides `renew` (`build_run.py:137-163`): it renews the sync
lease under the fence check, then calls `super().renew()`, which renews the generation job once one is
installed. A renewal failure is sticky exactly as in `BuildRun`, with the message `Connector sync lease
renewal failed`. `BuildRun`'s constructor takes `cancelled_message="Connector sync cancelled"`.

**Release.** The publication transaction sets `status="completed"`, `phase="complete"` and clears the
lease. A failure path, outside any transaction, sets `status="failed"` with a bounded `error_code`
(`sync_failed`, `sync_cancelled`, `lease_lost`), clears the lease if still the holder, and never raises
over the original exception.

Failpoint: `lease`, after the claim commits.

### 5.2 Step 2, cursor and page: `_next_page(run, target, state, options) -> ChangePage`

- The cursor is `SyncState.cursor_json["cursor"]` parsed as `SyncCursor`, or `None`. An inventory scan
  (section 6.4) starts from `None` with `scan="inventory"`.
- `connector.list_changes(config, cursor)` runs outside every transaction. Its HTTP is bounded by
  `ProviderClient` (section 10); the runtime additionally refuses `len(page.changes) >
  options.max_changes_per_page` (`A change page exceeds max_changes_per_page`) and `page.partition !=
  partition` (`A change page names another partition`).
- `run.check()` before and after the call (`build_run.py:108-135`), so cancellation and lost authority
  stop between pages.
- At most `options.max_pages` pages per run. A run that stops on the page cap has a partial inventory.

Failpoint: `after_page`.

### 5.3 Step 3, capture: `_capture(run, target, page, raw_store, options) -> CapturedPage`

Outside transactions, for each change in page order:

- **`upsert`.** `fetch` → refuse `len(data) > max_fetch_bytes` and a run total above `max_run_bytes`
  → `raw_store.put_bytes(data)` (`raw_artifacts.py:198-203`) → `fetch_policy` →
  `emit.capture_records(fetch, policy, connector=..., workspace_id=..., source_id=..., raw_uri=...,
  observed_at=now, policy_expires_at=now + policy_ttl)` (S2).
- **`policy_change`.** `fetch_policy` only → `emit.policy_record(...)`. An artifact the store does not
  hold yet is treated as an `upsert`.
- **`delete`.** No fetch. The artifact id is `identity.artifact_identity(workspace_id,
  connector_row.instance_url, ref.artifact_kind, ref.external_id)` (`identity.py:136-139`), which equals
  `Artifact.identity_parts` for a remote artifact (`model.py:314-317`).

`now` is `store._now()`, taken once per page. `CapturedPage` holds the ordered records and the page's
next cursor. Raw bytes written here and never checkpointed are orphans, which the prose coordinator's
raw rules allow (`ai_docs/plans/rag-it-all-task-5-prose-coordinator.md` section 9).

Failpoint: `after_fetch`, after the page's raw objects are written and before the checkpoint. This is
CK3's "crash after fetch before checkpoint".

### 5.4 Step 4, checkpoint: `_checkpoint(run, target, captured) -> k.SyncState`

One `store.transaction()` with `_lock_source(source_id)` and `_check_sync`. For each captured record, in
page order:

1. **Revision reuse.** A stored `ArtifactRevision` with the same id is reused whole when
   `(artifact_id, content_hash, provider_revision, raw_uri)` agree, and refuses otherwise with
   `Accepted revision identity conflicts with stored input`: the rule of `prose_generation._pair`
   (`:124-138`). A new one is `put_knowledge`.
2. **Policy.** A new `AccessPolicy` is `put_knowledge`. A stored one with the same id gets
   `update_knowledge(verified_at=now, expires_at=now + ttl)` (`MUTABLE_FIELDS["AccessPolicy"]`,
   `store/knowledge.py:157`).
3. **Artifact.** A new one is `put_knowledge` (its first put flips `managed`, `authorization.py:187`). A
   stored one whose `policy_id` differs gets `update_knowledge(policy_id=...)`; a `delete` gets
   `update_knowledge(deleted_at=now)`; an `upsert` of a deleted artifact whose revision differs from the
   deleted one gets `update_knowledge(deleted_at=None)` (the delete barrier, `docs/rag_it_all.md:637`),
   and an identical replay stays deleted.
4. **Pending log.** `SyncState.cursor_json` becomes
   `{"version": 1, "cursor": <next SyncCursor or null>, "pending": {artifact_id: [operation, revision_id or null, policy_id]}, "scan": {...}}`,
   the last operation per artifact winning in feed order.
5. `update_knowledge(SyncState)` and `update_knowledge(SyncRun)` with `phase="fetch"`.

**Replay is a no-op by identity (I8).** A replayed page re-puts identical bytes (content-addressed),
reuses the stored revision and policy, finds `Artifact.policy_id` unchanged, and computes an equal
`cursor_json`, so `update_knowledge` changes nothing (`store/knowledge.py:814`) and no epoch moves.

Failpoints: `before_checkpoint` inside the transaction, before commit, proving rollback; and
`after_checkpoint`, after commit.

### 5.5 Authority and the generation's inputs: `_inputs(run, target, state) -> SyncInputs`

After the last checkpoint of the run, and before any emit:

1. **Inventory.** The parent is the Source's `active_generation_id`. The member set is the parent's
   `GenerationMember` revisions (`_knowledge_rows("GenerationMember", generation_id=parent)`) minus its
   manifest, overlaid with `SyncState.cursor_json["pending"]`: an `upsert` replaces the artifact's
   revision, a `delete` removes it, a `policy_change` keeps the revision. Section 6.4's inferred deletions
   are applied here. Every artifact with `deleted_at` set is excluded, because publication refuses a
   tombstoned artifact in the closure (`generations.py:1322`).
2. **No changes.** If the member set equals the parent's and no policy changed, the run releases its
   lease, clears `pending`, and returns `outcome="no_changes"` without building.
3. **Manifest.** `connector-inventory-v1` canonical JSON:
   `{"version": 1, "source_id", "workspace_id", "connector_id", "instance", "partition", "configuration", "members": [[artifact_id, revision_id, content_hash, raw_uri, provider_revision], ...]}`,
   members sorted, written with `raw_store.put_bytes`. It is bound as `Artifact(kind="manifest",
   external_id="connector-inventory-v1", canonical_uri=f"source:{source_id}/connector-inventory-v1",
   policy_id=<manifest policy>)` and an `ArtifactRevision(content_hash=<sha256>, raw_uri=...,
   metadata_json={"connector_inventory_v1": <payload>})`, reused when stored. This mirrors the prose
   manifest pair (`prose_generation.py:172-188`). The manifest policy is the local grant
   `AccessPolicy(origin="local_curated", scope_key=f"source:{source_id}:connector-v1", mode="workspace")`,
   planned exactly as `code_generation._policy` plans its own (`:588-599`).
4. **Configuration.** `{"generation_profile": "connector", "embedding_profile": <descriptor>,
   **descriptor_configuration(descriptor, registry), "mapping": <TypeMapping JSON>, "partition": partition,
   "derivation": {"sync": SYNC_RULE_VERSION, "binder": BINDER_VERSION, "render": RENDER_RULE_VERSION,
   "keys": KEY_RULE_VERSION, "classifier": CLASSIFIER_VERSION}}`. The derivation versions make a changed
   derivation a different generation, so a stale staged attempt can never be resumed (code-capture
   ruling 10). `registry.fingerprint()` is never in it (amended design section 3).
5. **Generation.** `generation_for_inputs(pairs + manifest pair, workspace_id, source_id,
   parent_id=parent, parser_version=CONNECTOR_PARSER_VERSION, linker_version=BINDER_VERSION,
   embedding_profile=profile.fingerprint, configuration=..., created_at=now,
   registry_fingerprint=registry.fingerprint())` (`lifecycle.py:15`, RS1-2), then
   `build_run.adopt_capture_instant` (the moved `_instant`, `code_generation.py:602-614`); a reclaimed
   attempt also keeps its stored `registry_fingerprint` (S1 section 10).
6. **Authority.** `run.adopt(run.guard.bind_inputs(AcceptedBuildInputs(pairs=..., planned_policies=...)))`
   (`build_authority.py:378-394`). The guard was captured by `ConnectorRun` at entry, before capture;
   capture's own epoch bumps (new policies, `policy_id` and `deleted_at` updates) happened inside the run,
   so the guard is re-captured with `capture_build_authority` after the last checkpoint and before
   `bind_inputs`, never across a checkpoint.
7. **Receipt shortcut.** `build_run.prior_receipt(run, gen, manifest_sha256, operation_id)` returns
   `already_published` or `already_current` without emit or writes (`code_generation.py:654-679`).

**Why the trusted local actor.** `EvidenceAccess.build` grants an internal audience every workspace
policy, including `mode="unknown"` (`access.py:458-459`), and denies unknown to a reader (`:460`). A
provider partition legitimately holds artifacts nobody may read yet (design section 10: "produces artifacts
nobody can read until an operator assigns a policy"). A reader actor could therefore never prove the
accepted inputs, and readability belongs to provider ACLs, not to whoever pressed "sync". S4's commands
and S6's routes check the operator's source-management capability before calling the runtime.

### 5.6 Step 5, emit: `_emit(run, target, inputs, raw_store, options) -> tuple[EmitResult, ...]`

- Every member revision of the new generation is emitted, not only the changed ones (deviation DV1).
- The main thread reads each revision's bytes (`raw_store.read_bytes`, `raw_artifacts.py:260-264`) and
  builds `RevisionInput(partition, artifact, revision, data, config, mapping, registry)`.
- A `ThreadPoolExecutor(max_workers=options.emit_workers)` runs `connector.emit(revision, mapping)` inside
  `guard.forbid_effects()` in the worker thread (section 10.1). `future.result(timeout=emit_timeout)`
  bounds the wait; a timeout raises `ConnectorContractViolation("emit exceeded its time budget")`, and the
  thread cannot be pre-empted in-process (question Q6).
- A returned batch over `max_batch_records` records refuses: `An emission batch exceeds max_batch_records`.
- `on_batch(revision, batch)` runs in the main thread, outside transactions and outside the guard.
- **Failures.** `EmitSideEffect` and `ContractError` are connector defects: `ConnectorContractViolation`
  fails the sync before install. Any other exception from `emit` is a revision-level parse failure: it is
  counted as `coverage["emit_failed"][family]`, and the artifact keeps its parent revision if it has one,
  or leaves the generation if it does not ("the previous revision's records stay", design section 7).

Failpoint: `after_emit`.

### 5.7 Step 6, bind: `_bind(run, target, inputs, results) -> RecordBundle`

- `emit.bind_batch(BindContext(registry=registry, descriptor, connector=connector_row, generation,
  workspace_id, source_id, partition), revision, batch)` per revision, then `emit.merge_bound(...)` (S2).
- Passage vectors: `ProfiledEmbeddings(ctx.ollama, resolved, cache=embedding_cache,
  authorization_check=run.check)` (`prose_generation.py:564-566`) embeds every `BoundPassageRow.text`
  exactly as `code_generation._vectors` does (`:545-551`), outside transactions; `embeddings.validate()`
  runs before publication (`:1002`). Units are not embedded (section 8.7).
- The `RecordBundle` (section 7.1) is assembled from the merged records, the accepted pairs, the manifest
  revision, one `GenerationMember` per pair and the `StagedPassage`s.
- Coverage for the generation: `{"connector": name, "partition": partition, "emission":
  coverage.to_json(), "pages", "fetched", "deleted", "policy_updates", "emit_failed", "inventory":
  "not_scanned" | "partial" | "complete", "reconcile_unconfirmed", "units_embedded": "downstream"}`.

Failpoint: `after_bind`.

### 5.8 Step 7, stage: `_stage(run, bundle) -> int`

The order and store calls of `code_generation`'s install and write (`:685-756`, `:778-809`):

1. `run.pause()`, `run.check()`; one transaction with `_lock_source`: `_check_sync`; refuse a live other
   holder (`BuildBusy("Source already has a live build holder")`, `:697-700`);
   `recover_generation_builds(source_id=...)`; expected authorization epoch plus one per new planned policy
   (`:704-708`; the managed flip already happened at capture, so no `+ int(not source_is_managed)` term
   remains); `put_knowledge(gen.replace(coverage_json=...))` if new; `claim_generation_build` for a new
   generation, `reclaim_generation_build(..., expected_manifest_hash=gen.manifest_hash)` for a stored one
   (`generations.py:320-380`); under `generation_write`, the accepted pairs and revision members;
   `bind_generation_embedding_profile(gen.id, manifest_revision.id, ...)`; the epoch and
   `SourceControl` comparison of `:740-755`. Failpoint `after_install`.
2. `run.start()`; `resume = staged_records.probe_staged_records(store, bundle)`.
3. For each batch of `staged_records._write_batches(bundle, batch_size=..., resume=resume)`:
   `build_run.rebaseline_between_batches(run)`, `run.check()`, failpoint `before_batch`,
   `staged_records._write_batch(store, bundle, batch, **credentials(job), **authority_fields(guard))`,
   rebaseline, check (`:791-803`).
4. Failpoint `before_seal`; `staged_records._seal(...)` (`:807`).

### 5.9 Step 8, publish: `_publish(run, target, bundle, inputs) -> BuildReceipt`

`run.pause()`, `run.check()`, then one transaction with `_lock_source`, following `code_generation._publish`
(`:820-856`):

1. `_check_sync`; `guard.check_local()`; failpoint `before_publish` (inside, proving rollback);
2. `store.publish_staged_generation(gen.id, expected_parent_id=gen.parent_id, **credentials(job),
   expected_suppression_epoch=guard.expected_suppression_epoch, published_at=store._now())`
   (`generations.py:1269`). It writes the one `IndexEvent(kind="published")` (`:1419-1427`), which is the
   append-lane announcement: a downstream indexer reads the generation's members from its
   `generation_id`;
3. the epoch comparison of `:833-837`, then `update_source` with the ready presentation (`:838-841`);
4. `SyncState.cursor_json` keeps `cursor`, clears `pending`, resets `scan`; `last_success_at=now`, and
   `last_reconciled_at=now` when the scan was complete; `SyncRun` completed and released;
5. the fresh-authority comparison of `:842-854`.

After commit: failpoint `after_publish`; `run.receipt`, `run.job = None`, `run.adopt(final_guard)`,
`run.guard.check()` (`:1016-1019`). A lost compare (`Generation publication compare-and-swap failed`,
`generations.py:1402`) fails the build through the failure path; the next run rebuilds against the new
parent (design section 7 step 8).

### 5.10 Failure

`except BaseException`: `run.pause()`; if installed and unpublished,
`fail_generation_build(gen.id, **credentials(job), error_code="build_cancelled" if isinstance(error,
BuildCancelled) else "build_failed")`, swallowing `ValueError`/`AuthorizationChanged`
(`code_generation.py:1026-1034`); release the sync lease with a bounded `error_code`; re-raise. The runtime
never calls `discard_generation`, `collect_generation`, `_clear_passages`, `delete_passages_for_source` or
`delete_code_nodes_for_source`.

## 6. Deletions, policy changes and inventory (brief decision 9)

### 6.1 The rules

| Input | Action | Anchor |
| --- | --- | --- |
| `Change(operation="delete")` from a deletion feed | `Artifact.deleted_at = now` at checkpoint; excluded from the next manifest | `store/knowledge.py:155`; `generations.py:1322` |
| `Change(operation="policy_change")` | new `AccessPolicy`; `Artifact.policy_id` updated at checkpoint | `authorization.py:188-193` |
| An `upsert` whose policy differs from the stored artifact's | as `policy_change`, in the same checkpoint | same |
| An `upsert` of a deleted artifact, same revision | stays deleted (replay) | `docs/rag_it_all.md:637` |
| An `upsert` of a deleted artifact, different revision | `deleted_at = None` | same |
| A failed page (any exception in `list_changes`, `fetch`, `fetch_policy`) | the run stops before that page's checkpoint; nothing is deleted; no generation is built in that run (deviation DV5); the next run resumes from the last checkpoint | `docs/rag_it_all.md:638` |
| `ProviderForbiddenError` or a permission-masked `ProviderNotFoundError` on `fetch_policy` | stored as `PolicyObservation(state="unknown")`: deny, never a deletion | `docs/rag_it_all.md:639` |
| An artifact missing from a *completed* inventory scan | a deletion candidate (section 6.4) | `docs/rag_it_all.md:640` |
| An artifact missing from an incomplete scan | nothing | design section 7 step 9 |

### 6.2 Why capture precedes the build lease

`_check_knowledge_write` requires build authority for a content write only while the source has a
running rebuild job (`generations.py:620-637`). Capture writes `Artifact` and `ArtifactRevision` rows
with no generation, so it must run while no rebuild job is live for the source. Two facts make that
hold: the runtime claims its own build only in step 7, after the last checkpoint; and step 1 runs
`recover_generation_builds(source_id=...)`, which releases a crashed run's expired job. A live foreign
job (another process mid-build) makes a capture write refuse with `Managed evidence write requires build
authority`, which the checkpoint maps to `ConnectorSyncBusy`; the sync lease already excludes that case
for well-behaved callers.

### 6.3 The policy epoch

A new policy, a changed `Artifact.policy_id` and a changed `Artifact.deleted_at` each bump the
authorization epoch (`authorization.py:188-193`): that bump is the policy epoch of the design's section 7
step 3. Consequences, all intended:

- **Narrowing takes effect at the checkpoint**, before any rebuild, because `EvidenceAccess` checks the
  artifact's policy (`access.py:514`) for every generation that holds the artifact, including the one
  still active.
- **Widening waits for the next revision.** A span is immutable and keeps the policy it was created with,
  and `EvidenceAccess` checks the span's policy too (`access.py:529`). Re-binding an unchanged revision
  mints the same span id, so the stored span is reused with its original `policy_id` (question Q4).
- **An open query session refuses and must repeat** (`query_access.py:89-91`), which is the fail-closed
  behaviour the delete-with-live-session test pins (section 11).
- **A concurrent build elsewhere rebaselines** between batches (`build_authority.py:396-451`), as for any
  permission change.

### 6.4 Inventory completeness and inferred deletion: `_reconcile(run, target, state, inputs)`

An inventory scan runs when `options.reconcile` is true or `reconcile_due(state, now=...,
interval=options.reconcile_interval_seconds)` holds (`last_reconciled_at` is `None` or older than the
interval; default daily, `docs/rag_it_all.md:623`), and only if `descriptor.capabilities.inventory` is
true. `SyncState.cursor_json["scan"]` records `{"mode": "inventory", "started_at", "complete": false,
"config_hash", "credential_ref", "seen": <raw uri of the sorted seen artifact ids, or null>}`, rewritten
at every checkpoint; the seen set lives in the raw store so a large inventory never inflates a row.

Deletions are inferred only when all of these hold (the design's section 7 step 9 and
`docs/rag_it_all.md:640`):

1. the scan started from cursor `None` and a page with `complete=True` was checkpointed;
2. the configuration hash and `credential_ref` are unchanged since `started_at`;
3. the artifact is a member of the parent generation and not in `seen`;
4. a confirming `fetch` raises `ProviderNotFoundError`. A successful fetch whose `source_updated_at` is
   after `started_at` keeps the artifact and records an `upsert`; any other error keeps the artifact and
   counts `coverage["reconcile_unconfirmed"]`.

A confirmed candidate gets `deleted_at` in one more checkpoint transaction, under the same rules as a
feed delete. After publication `scan` resets and `last_reconciled_at` is set.

### 6.5 Retiring a whole partition

When a connector instance is disabled or a partition disappears from its provider, the partition's
Source is withdrawn with `source_lifecycle.tombstone_managed_source(ctx, source_id=..., actor=...,
operation_id=...)` (`knowledge/source_lifecycle.py:48`), unchanged. S3 adds no wrapper; S4's commands or
Task 15 call it. A later sync on that Source refuses at step 1 (`Source is tombstoned`). Per-artifact
deletion never uses the tombstone path: it is `Artifact.deleted_at` plus exclusion (section 6.1).

## 7. The generic staged writer, the connector profile and authority admission (brief decision 8)

### 7.1 `knowledge/staged_records.py`

**Shared, imported from `staged_code.py`:** `_epochs` (`:281-291`), `_local` (`:294-315`; it reads only
`prepared.generation`, which `RecordBundle` has), `_Group` (`:338-344`), `_immutable_native`
(`:485-496`), `ResumePlan` (`:557-573`), `CLEANUP` (`:45`) and `PAYLOAD_CEILING_BYTES` (`:29`).

**New:**

- `RecordBundle.__post_init__` checks closure, with these messages:
  - every generation-scoped record has exactly one member and no member names a missing record:
    `Record bundle membership differs from its generation-scoped records`;
  - every observation's object, every assertion's endpoints, every version's assertion, every support's
    version and span, every unit's passage and span, and every view's span are present:
    `Record bundle references a missing {kind}`;
  - every span's revision is a revision member: `Record bundle span is outside its revision members`;
  - every passage row names this generation: `Record bundle passage belongs to another generation`.
- `_accepted(store, bundle)` mirrors `staged_code._accepted` (`:318-335`): verified profile binding, bound
  configuration fingerprint equal to `text_hash(bundle.configuration_json)`, stored accepted pairs equal.
- `_groups(bundle)`, in dependency order, each group with its probes as in `staged_code._groups`
  (`:347-431`):
  1. the accepted preflight (`None`);
  2. one group per revision member;
  3. one per span, with its member;
  4. one per object, with its observations and their members (an observation cites a span, so objects
     follow spans, `staged_code.py:354-358`);
  5. one per derived record, with its dependencies, views and their members;
  6. one per passage: the native `Passage` row, then its `Unit`s and their members (S1: the passage
     before its units);
  7. one per assertion: the `Assertion`, then its versions, supports and their members (a version names
     its unit, so assertions come last, S1 section 10).
- `_write_batch`: under `_local`, the ceiling check, `put_knowledge` for knowledge records,
  `_immutable_native` then `store.add_passages` for passage rows, in group order.
- `probe_staged_records` mirrors `probe_staged_rows` (`:600-665`) with the flavours `member`, `exact`
  (evidence members, including `Unit`) and `native` (`Passage`): SKIP a group wholly present and equal,
  WRITE a group wholly absent, FAIL CLOSED on a partial group, a differing payload, or any
  generation-scoped row the bundle would not produce.
- `_inventory` requires exact `GenerationMember`, `GenerationEvidenceMember` (with `Unit`), `Unit` rows
  (`_knowledge_rows("Unit", generation_id=...)`, RS1-4), `Passage` rows, equal knowledge payloads, and no
  `NativeBinding`, native `Symbol`/`DataObject`/`Commit`, native relationship or `ProseExtraction`.
- `_seal` writes `IndexManifest(required_representations=("evidence", "dense", "native"),
  checksums=store.generation_checksums(gen.id))` and calls `seal_generation`, as `staged_code._seal` does
  (`:718-736`).
- `write_staged_records` refuses an ambient transaction and brackets every batch with `check()`, as
  `write_staged_code` does (`:739`).

**What CK3's byte checks measure.** After each injected failure the tests compare, for the last published
generation: `store.generation_checksums(gen_id)`; `_bytes(store, kind, id)` (the canonical serialization of
`test_temporal_evidence.py:1338`) of every `GenerationMember`, every evidence member's record, every
`Passage` and every `Unit`; the Source's `active_generation_id` and `status`; and, for a replay, the
authorization, suppression and content epochs.

### 7.2 The `connector` generation profile

`validate_generation_profile` (`generation_profiles.py:202-277`) gains one branch, taken only when the
manifest revision's metadata key is `connector_inventory_v1`; the accepted-inputs path is byte-identical:

- the `connector_id is not None` refusal at `:232-233` applies to the accepted-inputs path only;
- the manifest artifact must be `external_id == "connector-inventory-v1"`, source-scoped, no provider
  revision, `metadata_json` closed to `{"connector_inventory_v1": ...}`;
- the payload is closed to `version` (1), `source_id`, `workspace_id`, `connector_id`, `instance`,
  `partition`, `configuration`, `members`;
- `_connector_members` requires every original to be a remote artifact of that connector and instance,
  and the member set to equal `members` exactly on `(artifact_id, revision_id, content_hash, raw_uri,
  provider_revision)`, refusing with `Connector generation members differ from their inventory manifest`;
- `configuration["generation_profile"] == "connector"`, and the identity re-derivation of `:264-276`
  passes `registry_fingerprint=generation.registry_fingerprint` (S1 section 10).

### 7.3 `BuildAuthority` admission of connector sources

All in `knowledge/build_authority.py`; every other source kind is unchanged:

- `BUILD_SOURCE_KINDS` (`:19`) gains `"connector"`; `PLANNED_POLICY_SCOPES` (`:27-29`) gains
  `CONNECTOR_SCOPE = "connector-v1"`.
- `_inventory` (`:248-293`), when `control.kind == "connector"`: an original artifact must carry
  `connector_id == meta["connector_id"]` and a `provider_instance`; the kind check against
  `ACCEPTED_ARTIFACT_KINDS` (`:272`) is replaced by the registry-validated `Artifact.kind` (S1 D8), and the
  one manifest artifact stays local; a used policy is either the planned local manifest grant or
  `origin="provider"` with `scope_key` starting `connector:{connector_id}:`. `mode="unknown"` is admitted.
  The expiry check of `:288-293` does not apply to provider policies, because the build is not a read
  grant and the internal audience ignores deadlines (`access.py:458-459`); readers still need an
  unexpired policy.
- `_source_control` is unchanged: `meta["connector_id"]` and `meta["partition"]` enter
  `input_config_json` (`:98-104`), so a changed partition or connector mid-build refuses.

## 8. Reuse of the coordinators' helpers (brief decision 7)

S3b moves five lane-neutral functions from `ingest/code_generation.py` into `ingest/build_run.py`, the
module the two coordinators already share (`build_run.py:1-18`), under public names. The bodies are
unchanged except where noted:

| New name in `build_run.py` | Was | Change |
| --- | --- | --- |
| `adopt_capture_instant` | `_instant`, `code_generation.py:602-614` | none |
| `operation_generation` | `_operation_generation`, `:617-634` | none |
| `published_receipt` | `_receipt`, `:637-651` | takes `manifest_sha256` instead of reading `captured.accepted.manifest.sha256` |
| `prior_receipt` | `_prior_receipt`, `:654-679` | takes `manifest_sha256` |
| `rebaseline_between_batches` | `_rebaseline`, `:759-771` | none |

`code_generation.py` keeps every old name bound: `_instant = adopt_capture_instant`,
`_operation_generation = operation_generation`, `_rebaseline = rebaseline_between_batches`, and two
three-line wrappers `_receipt` and `_prior_receipt` that pass `captured.accepted.manifest.sha256`.
This is the precedent of `prose_generation.py:59-70` (`_Run = BuildRun`). Tests patch only
`code_generation._publish` (`test_code_generation.py:830`), which does not move. `prose_generation.py`
keeps its own copies untouched (it is S5a's, ruling R2). Proof: `test_code_generation.py`,
`test_build_run.py`, `test_prose_generation.py` and `test_managed_code_activation.py` pass unchanged.

## 9. Failpoints (brief decisions 7 and 11)

**Mechanism.** `sync_connector(..., fault_hook: Callable[[str], None] | None = None)`, the store's own
convention (`generations.py:481-518`, `:1135-1148`, `:1280`/`:1351`; `snapshots.py:65-98`;
`migrations.py:625-656`): the runtime calls `fault_hook(label)` and ignores its return value; a test's
hook raises. Labels are exactly `FAULT_POINTS`. The hook runs inside a transaction at two points only,
`before_checkpoint` and `before_publish`, and there it can only raise, which is what proves rollback. No
production caller passes a hook: `test_no_production_module_passes_fault_hook_to_sync_connector` greps
`src/hippo` outside `connectors/sync.py`.

Test-side crashes inside the writer patch `staged_records._write_batch`, the pattern of
`test_code_generation.py:668` and `:700`.

**S4's five design section 8 boundaries** (S4 R-S3-2) map onto labels:

| Design section 8 boundary | Label and injection |
| --- | --- |
| crash after fetch before checkpoint | `after_fetch` (and `before_checkpoint`, in the transaction) |
| replayed page | `after_checkpoint` on page N, then a second run whose provider replays page N |
| failed inventory | the provider raises `ProviderTransientError` on page 2 of an inventory scan |
| policy change mid-page | a page `[upsert A, policy_change A, upsert B]` with `after_checkpoint` observed between pages |
| delete of an artifact with a live query session | `after_checkpoint` on a page deleting A, with a `query_session` opened before the run |

**The failure-injection matrix.** Every row runs on Fake and on LadybugDB (section 12). "G1 intact" means
section 7.1's byte checks equal their pre-run values and a new `query_session(ctx, EVERYTHING)` selects
G1 with its passages.

| # | Injection | Expected |
| --- | --- | --- |
| M1 | `after_fetch` raises on page 1 | no `Artifact`, `ArtifactRevision` or `AccessPolicy` row added; `SyncState.cursor_json` unchanged; G1 intact; a rerun reaches the same generation id and checksums as an uninterrupted run |
| M2 | `before_checkpoint` raises | as M1: the transaction rolled back |
| M3 | `after_checkpoint` raises on page 1, rerun replays page 1 | the rerun changes no row, no epoch and no `SyncState` byte for page 1; final generation equals an uninterrupted run's |
| M4 | provider replays one page twice in one run | same as M3 within one run |
| M5 | transient failure on page 2 of an inventory scan | no `deleted_at` set; no generation built; G1 intact; `scan.complete` false; the next run resumes at page 2 and completes |
| M6 | scan stops at `max_pages` before a `complete` page | no deletion; `inventory="partial"` |
| M7 | complete scan omits A (confirmed 404) and B (fetch succeeds) | A excluded with `deleted_at`; B kept |
| M8 | page `[upsert A, policy_change A → another user, upsert B]` | after the checkpoint a reader session loses A (`access.py:514`) while G1 still serves B; G2 publishes A under the new policy |
| M9 | session opened on G1, page deletes A | the old session's `validate()` raises `Permissions changed; repeat the query` (`query_access.py:89-91`); a new session serves G1 without A; after G2 publishes, `collect_generation(G1)` is blocked with `snapshot_reference` while the old session's reference is live (`snapshots.py:223-242`) |
| M10 | emit calls `socket`, `httpx`, `Ollama.embed`, `subprocess`, `threading.Thread.start`, `time.time`, `datetime.now` (one subclass each) | `ConnectorContractViolation`; nothing installed; G1 intact |
| M11 | emit raises `ValueError` for revision X | `coverage["emit_failed"]` counts it; X keeps its parent revision; publication proceeds |
| M12 | `staged_records._write_batch` raises after two batches | generation `failed` with its rows retained; the rerun reclaims (`reclaim_generation_build`) and reports `resumed_from_batches > 0` |
| M13 | `before_seal`; `before_publish` | G1 active; the rerun publishes; after `before_publish` no `IndexEvent(kind="published")` names the new generation |
| M14 | `after_publish` | G2 active; the rerun returns `outcome="already_published"` |
| M15 | parent changed between install and publish | `Generation publication compare-and-swap failed`; the attempt fails; the next run publishes on the new parent |
| M16 | a second `sync_connector` while the first holds the lease | `ConnectorSyncBusy` |
| M17 | the lease expires and another claim advances the fence | the first run's next checkpoint refuses `Sync lease was lost` and writes nothing |
| M18 | `should_stop` turns true between pages | `ConnectorSyncCancelled`; the previous checkpoint kept |
| M19 | the Source is tombstoned during staging | publication refuses; G1 is withdrawn by the tombstone, never deleted |
| M20 | spies on `discard_generation`, `collect_generation`, `_clear_passages`, `delete_passages_for_source`, `delete_code_nodes_for_source` across every row | never called |

## 10. HTTP, credentials and the emit guard (brief decision 10)

### 10.1 `connectors/guard.py`

`forbid_effects()` installs a profile function with `sys.setprofile` for the calling thread only and
removes it in `finally`. The runtime enters it inside each emit worker thread. Per-thread profiling is
used because process-wide patches would break the runtime's own main thread, which uses httpx, the clock
and Ollama concurrently, and because `datetime.datetime.now` is an attribute of an immutable C type that
cannot be patched (checked against the root venv while planning). On a `c_call` or `call` event for a
forbidden callable it raises `EmitSideEffect(f"emit called {qualname}; emit must not touch the network, a
model, a subprocess, a thread or the clock")`; CPython then unsets the profiler for that thread, and the
exception propagates to the `emit` call. The forbidden set:

- C callables: `socket.socket.connect`, `connect_ex`, `socket.getaddrinfo`, `_posixsubprocess.fork_exec`,
  `os.posix_spawn`, `os.posix_spawnp`, `os.system`, `os.fork`, the `os.exec*` family,
  `_thread.start_new_thread`, `time.time`, `time.time_ns`, `time.monotonic`, `time.monotonic_ns`,
  `time.perf_counter`, `time.perf_counter_ns`, `time.localtime`, `time.gmtime`, `time.sleep`, and
  `now`, `utcnow` and `today` bound to any subclass of `datetime.date`;
- Python functions, matched by code object: `httpx.Client.send`, `httpx.AsyncClient.send`, and
  `hippo.ollama.Ollama.chat_text`, `chat_json`, `_chat`, `embed`, `embed_one`, `embed_explicit`, `pull`
  (`ollama.py:91-256`).

Logging inside `emit` reads the clock and is therefore refused; a connector reports through
`ParseFailure`. The check was run on the root venv while planning: `datetime.datetime.now()`, `from time
import time; time()` and `socket.connect` were refused in a worker thread, a pure computation was
allowed, and the main thread's clock was unaffected. S4's `testing.purity_guard` re-exports this module
(S4 R-S3-5).

### 10.2 `connectors/http.py`

- `base_url` goes through `identity.normalize_provider_url` (`identity.py:75-111`), which refuses userinfo.
  A `path` that is absolute or not relative to it refuses: `Provider paths are relative to the
  configured instance`.
- `follow_redirects=False`. A 3xx raises `ProviderMalformedError`, so credentials never cross an origin
  (`docs/rag_it_all.md:891`).
- Timeouts come from `HttpLimits`. The body is streamed and refused as `ProviderMalformedError` once it
  passes `max_response_bytes`, checking `Content-Length` first.
- Classification: 401 authentication, 403 forbidden, 404 and 410 not found, 429 throttled, 408, 5xx and
  `httpx.TransportError` transient, and anything else, including invalid JSON from `get_json`, malformed.
  These match S4's canned `error_transport` responses (S4 plan section 3.1).
- Retries only for throttled and transient. Attempt `n` sleeps `Retry-After` when given (seconds, or an
  HTTP date against `wall_clock`) or `min(backoff_cap, backoff_base * 2 ** (n - 1)) * rng.uniform(0.5,
  1.0)`. It stops at `max_attempts`, when the next sleep would pass `max_total_seconds` on `monotonic`, or
  when `Retry-After` exceeds `max_retry_after_seconds` (`docs/rag_it_all.md:566`, `:623`).
- Error messages and `ProviderError.url` carry `credentials.redact_url(url)` and the status, never a body.
- `record_transport(case_dir, inner)` writes `http/NNNN.json` exactly as S4's plan section 3.1 specifies:
  `request` with `method`, the redacted `url`, the `accept` and `content-type` headers and `body_sha256`;
  `response` with `status`, the `content-type`, `retry-after` and `link` headers and `body_base64`.
  `replay_transport(case_dir)` answers in recorded order and raises `ProviderMalformedError` on an
  unexpected method, URL or body hash. S4 re-exports both.

### 10.3 `connectors/credentials.py`

- `CredentialRef.parse` accepts `env:NAME` (`NAME` matches `^[A-Z_][A-Z0-9_]*$`) and `file:/absolute/path`
  (no `..`); anything else refuses `Credential references are env:NAME or file:/absolute/path`.
- `resolve(ref)`: an environment variable must be present and non-empty. A file is opened with
  `O_NOFOLLOW`, must be a regular file of at most `max_bytes`, must not be readable by group or others
  (`st_mode & 0o077 == 0`), and is decoded as UTF-8 with one trailing newline stripped. Every error names
  the reference, never a value.
- `ResolvedCredential` has `repr=False` on its secret, and its `__repr__` prints `<redacted>`.
- `redact_url(url)` removes userinfo and replaces the value of every query parameter whose name contains
  `token`, `key`, `secret`, `password`, `signature`, `sig` or `code` (case-insensitive) with `REDACTED`.
- `refuse_inline_secrets(config)` refuses a config model field whose name contains `token`, `password`,
  `secret`, `api_key` or `credential`: `Connector configuration names a secret field {field}; store a
  credential_ref instead`. `Connector.credential_ref` (`model.py:283`) stores only the reference.
- Tests never read `.rag-dev-data/smoke-credentials.json` or any real token; they use `monkeypatch.setenv`
  and `tmp_path` files.

## 11. The fixture connector (brief decision 11, ruling R10)

**Location.** `tests/fakes/fixture_connector/` (ruling R10): never shipped, never auto-registered,
importable by tests and by the guide's executed examples, and apart from `connectors/testing.py` (S4a's).
It follows the design's section 9 package shape:

```text
tests/fakes/fixture_connector/__init__.py
tests/fakes/fixture_connector/connector.py      FixtureConnector, FixtureConfig, DESCRIPTOR
tests/fakes/fixture_connector/types.py          FIXTURE_EXTENSION
tests/fakes/fixture_connector/provider.py       FixtureProvider: an in-memory provider behind httpx.MockTransport
tests/fakes/fixture_connector/fixtures/basic/config.json
tests/fakes/fixture_connector/fixtures/basic/changes.json    {"pages": [ChangePage JSON, ...]}
tests/fakes/fixture_connector/fixtures/basic/policies.json   {"<external id>": PolicyObservation JSON}
tests/fakes/fixture_connector/fixtures/basic/inputs/<quoted id>
```

The case files use S4's layout (S4 plan section 3.1); S3 writes no `expected/` directory, because S4a
generates the goldens.

**Vocabulary** (`types.py`): kind `fixture_note`, family `custom`, `key_template=("instance", "note_id")`,
`key_prefix="note"`, `attrs_model=FixtureNoteAttributes` (`title: str`, `updated: str | None`,
`extra="forbid"`), `label_template="{title}"`, one fact template
`FactTemplate(name="note_summary", version="1", consumes=("title", "updated"), text="Note {key} titled {title} was updated {updated}")`;
predicate `FIXTURE_LINKS`, `fixture_note → fixture_note`, `owner_families={"custom"}`,
`sources_allowed={"metadata"}`, `family_default="deterministic"`, `verb_phrase="links to"`.
`connector_kinds=("fixture",)`, so `ensure_connector(kind="fixture")` validates (`Connector.kind` is
registry-backed after S1). `SAME_OBJECT_AS` is built in. Registered by tests through `extension_scope()` with
`declared_families=("custom",)` (S1 D5).

**Descriptor.** `name="fixture"`, `version="1"`, `families=("custom",)`, `kinds=("fixture_note",)`,
`predicates=("FIXTURE_LINKS",)`, `artifact_kinds=("document",)`, `locator_kinds=("field",)`,
`capabilities=ConnectorCapabilities(changes_feed=True, deletion_feed=True, acls=True, inventory=True)`,
`config_model=FixtureConfig` (`instance_url: str`, `partition: str`, `extra="forbid"`),
`credentials=(CredentialRequirement(name="fixture_token"),)`, `parsers=()`.

**Provider protocol**, served by `FixtureProvider` over `httpx.MockTransport` and read through
`ProviderClient`:

- `GET /api/partitions/{partition}/changes?page={n}` returns `changes.json`'s page `n`;
  `SyncCursor.value` is `{"page": n + 1}`.
- `GET /api/notes/{quoted id}` returns the `inputs/` bytes as `application/json`.
- `GET /api/notes/{quoted id}/acl` returns the `policies.json` entry, or `{"state": "unknown"}`.

`FixtureProvider` also offers mutators the tests drive: replace a note, delete one, change an ACL, fail
page `n` with a given status, replay a page, and count requests.

**A note** is `{"id", "title", "body", "updated", "url", "links": [...], "same_as": [...]}`. `emit` is
pure and produces:

- one `NodeEmission` on the `title` field span, with `source="metadata"`, `metadata_origin="catalog"`, and
  `ts` parsed from `updated` with its original spelling;
- one verbatim `PassageEmission` over the `body` field;
- one `UnitEmission(kind="sentence")` per sentence of `body`, with character offsets;
- one `FIXTURE_LINKS` edge per link, supported by `links.{i}`;
- one `AliasEmission(rule="explicit_annotation")` per `same_as` entry, supported by `same_as.{i}`;
- `ParseFailure(family="custom", reason="missing_body")` for a note without `body`.

Rendered facts become derived passages through S2's binder (ruling R6). `probe` samples up to ten notes
and calls `classify.classify` with `KindMapping(provider_type="note", kind="fixture_note")`. Guard-violating
variants for matrix row M10 are subclasses defined in `test_connector_sync.py`, not in the fixture package.

## 12. Task split

Three workers. Each owns its files exclusively.

| # | Task | Depends on | Exclusive files |
| --- | --- | --- | --- |
| S3a | Guard, HTTP, credentials | S2a merged (for the package) | NEW `src/hippo/connectors/guard.py`, `http.py`, `credentials.py`; NEW `tests/unit/test_connector_guard.py`, `test_connector_http.py`, `test_connector_credentials.py` |
| S3b | Staged writer, connector profile, authority admission, helper extraction | S1b merged | NEW `src/hippo/knowledge/staged_records.py`, NEW `tests/unit/test_staged_records.py`; `src/hippo/knowledge/generation_profiles.py`, `src/hippo/knowledge/build_authority.py`, `src/hippo/ingest/build_run.py`, `src/hippo/ingest/code_generation.py` (re-bindings only; ruling R2 gives the file to S5b, which receives it after S3b merges), and appended tests in `tests/unit/test_generation_profiles.py`, `test_build_authority.py`, `test_build_run.py` |
| S3c | The runtime and the fixture connector | S2b, S3a, S3b merged | NEW `src/hippo/connectors/sync.py`, NEW `tests/fakes/fixture_connector/**`, NEW `tests/unit/test_connector_sync.py` |

**Sizing.** S3a is pure and small. S3b is the analogue of CC8 (`staged_code.py`, one worker) plus about
150 lines of admission and profile changes. S3c is the analogue of CC9b (`code_generation.py`, one worker)
plus the fixture. If S3c runs short of budget, split it after section 5.4: S3c-1 is the lease, page,
capture, checkpoint and reconcile steps with matrix rows M1–M9 and M16–M18; S3c-2 is emit, bind, stage and
publish with rows M10–M15, M19 and M20.

### Task S3a: guard, HTTP, credentials

**Spec.** Purpose: the bounded provider boundary and the emit guard. Inputs: URLs, transports, references,
callables. Outputs: bytes and JSON, resolved credentials, a guarded context. Errors: the six
`ProviderError` classes, `CredentialError`, `EmitSideEffect`. Invariants: no store; no secret in any
message, log or repr; the guard affects only the thread that enters it.

**Step 1: RED.** Save `/tmp/hippo-s3a-red.log`.

`tests/unit/test_connector_guard.py`:

- `test_the_guard_refuses[socket_connect|getaddrinfo|httpx_client|httpx_async_client|ollama_chat_json|ollama_embed|subprocess_run|os_system|thread_start|time_time|time_monotonic|perf_counter|from_time_import_time|datetime_now|datetime_utcnow|date_today|time_sleep]`
- `test_the_guard_allows_pure_computation_json_and_hashing`
- `test_the_guard_affects_only_the_entering_thread`
- `test_the_guard_is_removed_after_a_violation_and_after_a_normal_exit`
- `test_the_guard_nests_and_restores_a_previous_profiler`

`tests/unit/test_connector_http.py`:

- `test_each_status_maps_to_its_error_class[401|403|404|410|429|408|500|503|418]`
- `test_transport_errors_are_transient_and_invalid_json_is_malformed`
- `test_throttled_and_transient_retry_with_capped_jittered_backoff`
- `test_retry_after_seconds_and_http_date_are_honoured_and_capped`
- `test_attempts_and_total_duration_are_capped`
- `test_authentication_forbidden_not_found_and_malformed_never_retry`
- `test_a_response_over_the_size_cap_is_malformed_before_it_is_read_whole`
- `test_a_redirect_is_refused_and_credentials_never_cross_it`
- `test_an_absolute_or_escaping_path_is_refused`
- `test_errors_carry_a_redacted_url_and_never_a_body`
- `test_record_then_replay_reproduces_the_exchanges_in_order`
- `test_replay_refuses_an_unexpected_request`
- `test_a_recording_contains_no_authorization_header_or_secret_query_value`

`tests/unit/test_connector_credentials.py`:

- `test_env_and_file_references_parse_and_others_refuse`
- `test_env_reference_resolves_and_a_missing_variable_names_only_the_reference`
- `test_file_reference_refuses_symlinks_oversize_and_group_readable_files`
- `test_resolved_credential_repr_and_str_never_show_the_secret`
- `test_redact_url_removes_userinfo_and_secret_query_values`
- `test_inline_secret_fields_in_a_config_model_are_refused`

Run: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_guard.py tests/unit/test_connector_http.py tests/unit/test_connector_credentials.py -q -o addopts='' -W error > /tmp/hippo-s3a-red.log 2>&1; echo EXIT $?`.
Expected: nonzero, `ModuleNotFoundError`.

**Step 2: GREEN.** Implement sections 4.1–4.3 and 10. The same command to `/tmp/hippo-s3a-green.log`:
`EXIT 0`.

**Step 3: lint.** `.venv/bin/ruff check` and `.venv/bin/ruff format --check` on the six files.

**Step 4: commit** in worktree `s3a`: `Add the connector emit guard, bounded HTTP client and credential
references (CDK S3a)`.

### Task S3b: staged writer, connector profile, authority admission, helper extraction

**Spec.** Purpose: the store-facing half of the runtime. Inputs: a `RecordBundle`, a connector generation
and its manifest, a connector Source. Outputs: fenced staged rows and a sealed manifest; a validated
profile; an admitted build authority. Errors: the messages of sections 7.1–7.3. Invariants: `knowledge`
imports nothing from `connectors`; the prose, code, and `text`/`file`/`repo`/`archive` authority paths
are unchanged.

**Step 1: RED.** Save `/tmp/hippo-s3b-red.log`.

`tests/unit/test_staged_records.py` (new):

- `test_record_bundle_refuses_missing_references_and_inexact_membership`
- `test_groups_write_passages_before_units_and_units_before_versions`
- `test_every_batch_revalidates_the_fence_and_both_epochs`
- `test_an_oversized_batch_is_refused_before_its_transaction`
- `test_a_conflicting_persisted_passage_is_never_overwritten`
- `test_the_inventory_is_exact_including_units`
- `test_the_seal_hashes_units_into_the_evidence_checksum`
- `test_replaying_every_batch_changes_nothing`
- `test_resume_skips_complete_groups_and_writes_absent_ones`
- `test_resume_fails_closed_on_a_partial_group_a_changed_payload_or_an_orphan_row`
- `test_the_public_wrapper_refuses_an_ambient_transaction_and_checks_between_batches`
- `test_staged_records_imports_nothing_from_connectors`
- `test_a_sealed_connector_generation_survives_ladybug_close_and_reopen`: the
  `test_staged_code_writer.py:1128-1136` pattern; skipped unless `HIPPO_TEST_STORE=ladybug`.

Appended to `tests/unit/test_generation_profiles.py`:

- `test_connector_profile_validates_its_inventory_manifest`
- `test_connector_profile_refuses_a_member_outside_the_manifest_or_another_connector`
- `test_connector_profile_rederives_identity_with_the_registry_fingerprint`
- `test_plain_prose_and_code_profiles_are_unchanged` (the existing cases, run again, still pass)

Appended to `tests/unit/test_build_authority.py`:

- `test_a_connector_source_is_captured_for_the_trusted_local_actor`
- `test_connector_authority_admits_provider_and_unknown_policies_of_its_connector_only`
- `test_connector_authority_refuses_an_artifact_of_another_connector`
- `test_connector_authority_ignores_provider_policy_expiry_while_readers_do_not`
- `test_a_changed_connector_or_partition_in_source_meta_refuses`
- `test_text_file_repo_and_archive_authority_is_unchanged`

Appended to `tests/unit/test_build_run.py`:

- `test_the_moved_helpers_are_the_code_coordinators_bound_names`
- `test_published_receipt_and_prior_receipt_take_the_manifest_hash`

Run: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_staged_records.py tests/unit/test_generation_profiles.py tests/unit/test_build_authority.py tests/unit/test_build_run.py -q -o addopts='' -W error > /tmp/hippo-s3b-red.log 2>&1; echo EXIT $?`.

**Step 2: GREEN.** Implement sections 4.4–4.6, 7 and 8. The same command to `/tmp/hippo-s3b-green.log`:
`EXIT 0`. Then with `HIPPO_TEST_STORE=ladybug` to `/tmp/hippo-s3b-ladybug.log`: `EXIT 0`.

**Step 3: regression.** `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_code_generation.py tests/unit/test_prose_generation.py tests/unit/test_managed_code_activation.py tests/unit/test_staged_code_writer.py tests/unit/test_staged_prose_writer.py tests/unit/test_generation_resume.py tests/unit/test_layering.py tests/unit/test_import_order.py -q -o addopts='' -W error > /tmp/hippo-s3b-regress.log 2>&1; echo EXIT $?`.
If a file imports `fastapi.testclient` at module level, append the rulebook's form (b) filter and record it.

**Step 4: lint** on every changed file. **Step 5: commit** in worktree `s3b`: `Add the generic staged
writer, the connector generation profile and connector build authority (CDK S3b)`.

### Task S3c: the runtime and the fixture connector

**Spec.** Purpose: sections 5, 6, 9 and 11. Inputs: a connector, its config and partition, a frozen
current registry, a trusted-local actor, a raw store, an embedding spec. Output: a `SyncReceipt`. Errors:
`ConnectorSyncRefused`, `ConnectorSyncBusy`, `ConnectorSyncCancelled`, `ConnectorContractViolation`, the
store's and authority's own refusals. Invariants: the rows of section 9's matrix.

**Step 1: RED.** Save `/tmp/hippo-s3c-red.log`. `tests/unit/test_connector_sync.py`, with a `setup`
fixture in the shape of `test_prose_generation.py:86-131` (a real `Ollama` over `httpx.MockTransport`, a
builder with a membership, a raw store), plus `ensure_connector`, `connector_source`,
`store_classification`, the fixture extension under `extension_scope()`, and a `FixtureProvider`:

- `test_a_fixture_partition_syncs_through_every_step_and_publishes`
- `test_publication_uses_the_build_authority_and_writes_one_published_index_event`
- `test_the_generation_records_the_registry_fingerprint_outside_its_configuration`
- `test_the_configuration_carries_the_connector_templates_and_derivation_versions`
- `test_passages_are_embedded_through_ctx_ollama_and_units_are_not`
- `test_rendered_facts_are_retrievable_as_derived_passages`
- `test_an_unchanged_partition_returns_no_changes_and_builds_nothing`
- `test_a_second_run_with_one_changed_note_publishes_a_child_generation`
- `test_the_sync_lease_is_one_row_per_partition_with_a_monotonic_fence`
- `test_store_classification_writes_only_when_the_value_changes` (ruling R21)
- `test_a_partition_without_a_stored_classification_is_refused`
- `test_emit_receives_the_stored_mapping`
- `test_a_reader_actor_is_refused_for_a_connector_sync`
- `test_a_coordinator_lane_connector_is_refused_by_sync_connector`
- `test_a_registry_that_is_not_the_frozen_current_registry_is_refused`
- `test_the_failure_matrix[M1|M2|M3|M4|M5|M6|M7|M8|M9|M10|M11|M12|M13|M14|M15|M16|M17|M18|M19|M20]`
- `test_no_production_module_passes_fault_hook_to_sync_connector`
- `test_every_fault_point_label_is_reachable`
- `test_on_batch_sees_each_revision_outside_transactions_and_the_guard`
- `test_the_last_published_generation_survives_ladybug_close_and_reopen_after_a_failed_sync`: skipped
  unless `HIPPO_TEST_STORE=ladybug`.

Run the CK3 CHECK line (section 14) to `/tmp/hippo-s3c-red.log`. Expected: `test_connector_sync.py`
fails on `ModuleNotFoundError`; S3a's and S3b's files pass.

**Step 2: GREEN.** Implement section 4.7 and sections 5, 6, 9 and 11. The CK3 CHECK line to
`/tmp/hippo-s3c-green.log`: `EXIT 0`. The LadybugDB CHECK line to `/tmp/hippo-s3c-ladybug.log`: `EXIT 0`.

**Step 3: regression.** S3b's step 3 command plus `tests/unit/test_managed_source_lifecycle.py` and
`tests/unit/test_query_session.py`.

**Step 4: lint** on the new files. **Step 5: commit** in worktree `s3c`: `Add the connector sync runtime
and its fixture connector (CDK S3c)`.

## 13. Answers to the S4, S5 and S6 requirements

Every R-S3 item of `cdk-s4-kit.md` section 9, `cdk-s5-port.md` section 12 and `cdk-s6-exemplar.md`
section 11, satisfied or refuted by name.

| Item | Answer |
| --- | --- |
| S4 R-S3-1 (one entry; actor, frozen registry, clock, `fault_hook`, `on_batch`; returns the generation id) | Satisfied by `sync_connector(ctx, connector, *, config, partition, actor, registry, ..., on_batch=None, fault_hook=None) -> SyncReceipt`, whose `generation_id` is the published id. **Refuted in one part:** no `clock` argument. The runtime's only clock is the store clock (`generations.py:63-64`), which S4 already pins through `store._generation_clock`; a second clock could disagree with the one publication and recovery read. |
| S4 R-S3-2 (failpoint names for the five boundaries) | Satisfied: `FAULT_POINTS` and the mapping table of section 9. |
| S4 R-S3-3 (transport injection, six classes) | Satisfied: `ProviderClient(transport=...)`, section 10.2. |
| S4 R-S3-4 (`credentials.redact_url`, `credentials.resolve`) | Satisfied with exactly those names, section 4.2. |
| S4 R-S3-5 (the guard in a module both import) | Satisfied: `hippo.connectors.guard.forbid_effects`; S4's `purity_guard` re-exports it. |
| S4 R-S3-6 (fixture module path and case directory) | Satisfied: `tests/fakes/fixture_connector/` and `fixtures/basic/` (ruling R10). |
| S4 R-S3-7 (Connector row, Source row, embedding through `ctx.ollama`) | Satisfied: `ensure_connector`, `connector_source`; passages embed through `ctx.ollama` (section 5.7). |
| S5 R-S3 (nothing functional; `sync.py` re-export) | Satisfied by leaving no seam (ruling R3); S5b adds its re-export after S3c merges. `sync_connector` refuses a coordinator-lane connector by its declared `derivation` (ruling R1). S5's switch must also handle a `kind="connector"` Source (question Q7). |
| S6 R-S3-1 (Source creation, `_source_control` admission, `BuildAuthority`, `ctx.ollama`) | Satisfied: `connector_source` (kind `connector`), section 7.3, section 5.9, section 5.7. |
| S6 R-S3-2 (rendered facts as managed passages over a view) | Satisfied by S2's binder (S2 plan section 8.7, ruling R6) and embedded and staged here like any passage. |
| S6 R-S3-3 (store and read the classification) | Satisfied: `store_classification` writes `Connector.classification_json` only when the value changes (rulings R12, R21); `load_classification` reads one partition's entry. |
| S6 R-S3-4 (instance creation with stored config; credentials for probe) | Satisfied: `ensure_connector(..., config=..., credential_ref=...)` stores `config.model_dump_json()` after `refuse_inline_secrets`; `credentials.resolve`. Local and git rows are not written by any slice (ruling R5). |
| S6 R-S3-5 (deletion only from a completed inventory) | Satisfied: section 6.4, matrix rows M5–M7. |

`ensure_connector` is a `put_knowledge`, or an `update_knowledge` of `config_json`, `credential_ref`,
`enabled` or `capabilities_json` (`MUTABLE_FIELDS["Connector"]`, `store/knowledge.py:154`). A `Connector`
write is an authorization record and bumps the epoch (`authorization.py:113-114`), so it runs before a
sync, never inside one. `store_classification` compares the canonical JSON first and writes nothing when
it is equal (ruling R21).

## 14. Gate CK3

**CHECK line: a replacement is proposed** (for the orchestrator to apply). The ledger's line names four
files; S3 adds the guard's own file and appends admission, profile and helper tests to three existing
files, which the gate must run:

```text
CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_sync.py tests/unit/test_connector_http.py tests/unit/test_staged_records.py tests/unit/test_connector_credentials.py tests/unit/test_connector_guard.py tests/unit/test_generation_profiles.py tests/unit/test_build_authority.py tests/unit/test_build_run.py -q -o addopts='' -W error
```

**LadybugDB CHECK line, added** (persistence is touched; the code-capture ledger's convention):

```text
CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_connector_sync.py tests/unit/test_staged_records.py tests/unit/test_generation_profiles.py -q -o addopts='' -W error
```

**Neo4j parity**, root-owned, recorded in `ai_docs/gates/rag-it-all/cdk/neo4j-parity.md`: the LadybugDB
line with `HIPPO_TEST_STORE=neo4j`, on the disposable container only.

**CK7:** add `src/hippo/connectors/guard.py` (already under `src/hippo/connectors`) and
`tests/unit/test_connector_guard.py` (already matched by `test_connector_*.py`); no change needed.

None of these files imports `fastapi.testclient` at module level, so no form-(b) filter is needed; a
worker that finds otherwise records the form used.

CRITERIA, clause by clause:

| CK3 clause | Tests |
| --- | --- |
| a fixture connector runs every step of section 7 | `test_a_fixture_partition_syncs_through_every_step_and_publishes`, `test_every_fault_point_label_is_reachable` |
| failure injection at each durable boundary | `test_the_failure_matrix[M1..M20]` |
| no deletion follows a failed inventory | M5, M6 |
| a replayed page changes nothing | M3, M4 |
| publication uses the existing `BuildAuthority` compare | `test_publication_uses_the_build_authority_and_writes_one_published_index_event`, M15 |
| the active generation is never deleted | M20, M19, M13 |
| `IndexEvent` rows for the append lane | `test_publication_uses_the_build_authority_and_writes_one_published_index_event` |
| the runtime forbids network, model and clock inside `emit` | `test_the_guard_refuses[...]`, M10 |
| the same suite on LadybugDB with reopen proven | the LadybugDB line; both `*_ladybug_close_and_reopen_*` tests |
| Neo4j parity recorded | `neo4j-parity.md` |

## 15. Worktrees, merge order and what not to touch

- **Worktrees:** `s3a`, `s3b`, `s3c` (branches `wp/s3a`, `wp/s3b`, `wp/s3c`), each from the HEAD the
  orchestrator names after its prerequisites merge, with the rulebook's venv recipe.
- **Merge order:** S1a → S2a → S3a; S1b → S3b (S3b may run beside S2b); S2b + S3a + S3b → S3c. S4a after
  S3c; S5b's `sync.py` re-export after S3c (ruling R3).
- **Do not touch**, in any S3 task: S2's `connectors/{__init__,base,classify,keys,render,emit}.py`;
  `knowledge/registry.py`, `model.py`, `predicates.py`, `identity.py`, `input_binding.py`,
  `code_binding.py`, `staged_prose.py`, `staged_code.py`, `access.py`, `source_lifecycle.py`;
  `store/**`; `ingest/prose_generation.py` (S5a's, ruling R2), `ingest/pipeline.py`,
  `ingest/managed_activation.py`; `connectors/testing.py`, `cli.py`, `remote.py`, `web/**`,
  `mcp_server.py`; `tests/fakes/fake_store.py`; `docs/spec/*`, `docs/rag_it_all*.md`, every gate ledger
  and the checkpoint file. `ingest/code_generation.py` is S3b's for the re-bindings of section 8 only, then S5b's (ruling R2): a
  sequential handoff at S3b's merge.

## 16. Decisions taken

1. One `Source` of kind `connector` per (connector instance, partition), with `meta = {"connector_id",
   "partition"}`; `scope_key = source:{source_id}:{partition}` (amended design section 4).
2. Two leases: a `SyncRun` for the sync (one row per partition, found by id, fenced, renewed by
   `ConnectorRun.renew`) and the existing `MaintenanceJob` generation lease for the build.
3. The sync lease and cursor use `put_knowledge`/`update_knowledge` inside `_lock_source`
   transactions; no new store method.
4. Capture writes `Artifact`, `ArtifactRevision` and `AccessPolicy` durably per page, before the build is
   claimed, so a narrowed policy or a delete takes effect at the checkpoint.
5. The checkpoint stores the provider cursor and a pending change log in `SyncState.cursor_json`; the
   inventory's seen set lives in the raw store.
6. A replayed page is a no-op by identity, proven by unchanged rows, epochs and `SyncState` bytes.
7. A failed page ends the run without building (deviation DV5).
8. Inferred deletion needs a completed scan from cursor `None`, an unchanged configuration and
   credential reference, parent membership, absence from the seen set, and a confirming 404.
9. Per-artifact deletion is `Artifact.deleted_at` plus exclusion; whole-partition retirement is
   `tombstone_managed_source`, unchanged.
10. Connector syncs run as the trusted local actor; readers are refused.
11. The authority guard is re-captured after the last checkpoint, so capture's own epoch bumps never
    cross a guard.
12. Every member revision is emitted each run (deviation DV1).
13. Emit runs in a thread pool under a per-thread `sys.setprofile` guard in `connectors/guard.py`.
14. `EmitSideEffect` and `ContractError` fail the sync; any other emit exception is a revision-level
    failure that keeps the parent revision.
15. The runtime embeds passages through `ctx.ollama` and does not embed units.
16. The connector manifest is `connector-inventory-v1` in the raw store, bound as a local `manifest`
    artifact under a `connector-v1` local grant.
17. The configuration carries `descriptor_configuration`, the mapping, the partition and every
    derivation version; `registry_fingerprint` is recorded on the generation only.
18. A new `connector` generation profile branch, selected by the manifest's metadata key.
19. `BuildAuthority` admits `connector` sources, their provider and unknown policies, and ignores provider
    policy expiry for the build only.
20. `staged_records.py` imports `staged_code`'s fenced core instead of copying it, and orders groups
    passage → unit → assertion.
21. Five lane-neutral helpers move to `build_run.py`, re-bound under their old names in
    `code_generation.py`.
22. Failpoints use the store's `fault_hook` convention with twelve closed labels; production callers never
    pass one.
23. Only the store's `published` `IndexEvent` is written; it is the append-lane announcement.
24. `ProviderClient` follows no redirects, streams with a size cap, retries only throttled and transient
    responses with capped jittered backoff and `Retry-After`, and redacts every URL it reports.
25. Recording and replay use S4's `http/NNNN.json` format and live in `http.py`.
26. Credential references are `env:` and `file:` only; files must be private regular files.
27. The fixture connector is `tests/fakes/fixture_connector/` with S4's case layout (ruling R10).
28. `store_classification` writes only on change (ruling R21).
29. No registry loader in S3; `sync_connector` takes the frozen current registry (rulings R15, R16).
30. No `clock` argument on the sync entry: the store clock is the one clock.
31. S3 is split into S3a, S3b, S3c, with a named fallback split of S3c.
32. `emit` receives the stored classification's mapping; a partition with none refuses.

## 17. Design deviations

- **DV1, every member revision is emitted, not only new ones.** The design's section 7 step 5 says "for
  each new revision call `emit`". Passage and unit ids are generation-scoped (`lifecycle.py:73-89`, S1's
  `Unit` identity), so an unchanged revision's records must be re-minted for the child generation anyway,
  and no stored emission exists to copy. `emit` is pure and passage vectors hit the embedding cache, so
  the cost is CPU. Carrying records forward is an optimisation for after clean-rebuild equivalence
  (`docs/rag_it_all.md:616`).
- **DV2, no new `IndexEvent` kinds.** The design's section 7 step 8 says `IndexEvent` rows announce the
  append lane. The store's single `published` event (`generations.py:1419-1427`) names the generation
  whose members are the append. Policy-change and invalidation events belong to Task 9A's consumers.
- **DV3, the pending change log is in `SyncState`, not `SourceEvent`.** `docs/rag_it_all.md:389-391`
  lists `SourceEvent` for deliveries. `SourceEvent.provider_instance` is required and its reference to
  `Artifact` forces an artifact first; the cursor row already is the durable per-partition progress
  record the design names (`SyncState`, section 7 step 1), and webhooks, which need delivery dedupe, are
  out of scope.
- **DV4, passages are embedded by the runtime.** The design's section 0 keeps the kit index-agnostic, but
  a managed `Passage` row without a vector is refused by the store (`generations.py:1479-1545`), and
  CK6's retrieval runs through today's dense lane. Units stay unembedded.
- **DV5, a failed page builds nothing in that run.** The design is silent; building from a partial run
  would publish a generation whose inventory state is ambiguous, and the next run resumes from the
  checkpoint anyway.

## 18. Open questions

- **Q1.** Rulings R15 and R16 make the registry the caller's. Should `sync_connector` also verify that the
  connector's `TypeExtension` is registered (not only that its descriptor validates), or is
  `validate_against` enough?
- **Q2.** Provider principal mapping (S2 Q5): the fixture uses local principal ids; a real connector needs
  a mapping source.
- **Q3.** The reconcile interval is an option with the earlier plan's daily default; Task 9A decides when
  `sync_connector` is actually called.
- **Q4.** Policy widening waits for a new revision, because spans keep their creation policy
  (`access.py:529`). Is that acceptable, or should a policy-only change re-mint spans under a new
  generation (which needs a span identity that includes the policy)?
- **Q5.** `ensure_connector` bumps the authorization epoch. Operators create connectors outside build
  windows (ruling R5), but a busy instance will rebaseline running code builds when it happens.
- **Q6.** In-process emit cannot be pre-empted: a timeout fails the sync while the worker thread runs to
  completion. Out-of-process isolation is the design's open decision 2.
- **Q7.** Once its first artifact is captured, a `kind="connector"` Source is `managed`, so
  `plan_dispatch` (`pipeline.py:257`, `:295`, `:639`) would route a reindex of it to `run_managed_build`
  (`managed_activation.py:624`), whose non-code branch calls `build_plain_source` (`:662`), which refuses
  the kind. No production route creates
  such a Source in S3, but `run_managed_build` must refuse or route `kind="connector"` (S5's switch)
  before one does.


## Plan verification checklist

### Wiring manifest

| Interface | Implementation | Registration | Plan task |
| --- | --- | --- | --- |
| `sync_connector` | `connectors/sync.py` | called by S4 `run_case` and `hippo connector sync`; later S5, Task 9A | S3c |
| `guard.forbid_effects` | `connectors/guard.py` | `sync._emit`; re-exported by S4 `purity_guard` | S3a |
| `ProviderClient`, `record_transport`, `replay_transport` | `connectors/http.py` | used by connectors; re-exported by S4 | S3a |
| `credentials.resolve`, `redact_url` | `connectors/credentials.py` | `ProviderClient`; S4 recorder and probe | S3a |
| `write_staged_records` and cores | `knowledge/staged_records.py` | `sync._stage` | S3b |
| `connector` generation profile | `knowledge/generation_profiles.py` | `validate_generation_profile` branch | S3b |
| connector source admission | `knowledge/build_authority.py` | `capture_build_authority` | S3b |
| moved helpers | `ingest/build_run.py` | re-bound in `code_generation.py`; used by `sync.py` | S3b |

### Regression hotspots

| # | Behavior | Old location | New location | Plan task | Verified |
| --- | --- | --- | --- | --- | --- |
| 1 | Code coordinator receipts, instant, rebaseline | `code_generation.py:602-679`, `:759-771` | `build_run.py` | S3b | `test_code_generation.py` unchanged |
| 2 | Prose and code generation profiles | `generation_profiles.py:202-277` | same, plus a branch | S3b | `test_generation_profiles.py` existing cases |
| 3 | Authority for `text`/`file`/`repo`/`archive` | `build_authority.py:77-105`, `:248-293` | same | S3b | `test_text_file_repo_and_archive_authority_is_unchanged` |
| 4 | The active generation is never deleted | code-capture plan section 10 | `sync.py` failure path | S3c | matrix M20 |
| 5 | Fenced staged writes and exact seal | `staged_code.py:281-736` | imported by `staged_records.py` | S3b | `test_staged_code_writer.py` unchanged |

### Contract matrix

| Endpoint | Old shape | New shape | Breaking? | Plan task |
| --- | --- | --- | --- | --- |
| none: S3 adds library APIs only; routes and commands are S4 and S6 | | | no | |

### External dependencies (runtime)

| Dependency | Type | Endpoint/connection | Auth method | Integration test script | Verified? |
| --- | --- | --- | --- | --- | --- |
| Provider HTTP APIs | httpx | per connector `instance_url` | `credential_ref` → `Authorization` header | `test_connector_http.py` over `httpx.MockTransport`; the fixture provider in `test_connector_sync.py` | planned |
| Ollama embeddings | httpx via `hippo.ollama.Ollama` | `ctx.ollama` | none | `test_connector_sync.py` with the `test_prose_generation.py:32-121` MockTransport runtime | planned |

### Credential source inventory

| Credential | Runtime source | Path/key | Rotation? | Verified in new code |
| --- | --- | --- | --- | --- |
| Provider token per connector instance | `Connector.credential_ref` → environment variable or private file | `env:NAME` / `file:/abs/path` | re-resolved every sync | `test_connector_credentials.py` |









