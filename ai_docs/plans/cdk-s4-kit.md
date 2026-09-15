# CDK slice S4: the contract test kit, the scaffold, the `hippo connector` commands and the registry loader

> **For Claude:** execute with `dev:execute-plan`, one task per worker (S4c, S4a, S4b). Every task is
> test-first: write the RED tests, save the RED log, implement, save the GREEN log.

**Status:** proposed implementation contract for root review. Nothing here is implemented. First written
at HEAD `f7b14ee`. Re-planned at `e9becec` on `rag-it-all-tibs`, after the plan review
`ai_docs/reports/2026-09-15-cdk-plan-review.md` rejected S4 and rulings R39–R56 of
`ai_docs/plans/cdk-rulings.md` were recorded. The re-plan rewrites §3.1, adds slice S4c (§3.5), adjusts
§3.2 and §3.3, and updates §4–§11. §3.4 is unchanged. Design of record:
`docs/spec/connector-developer-kit.md` ("design"), as amended at `a9cbfcb`. Gate: CK4 of
`ai_docs/gates/rag-it-all/cdk/GATES.md`. The form follows
`ai_docs/plans/rag-it-all-task-5-managed-code-capture.md`. No `ddd/` workspace is written, as in the S3
plan's §0.

**Anchors.** "S1 §5.2", "S2 §4.1" and "S3 §4.7" name sections of `cdk-s1-registry.md`,
`cdk-s2-contract.md` and `cdk-s3-runtime.md` as committed at `e9becec`. Some rulings amend a contract
whose plan text has not been updated yet. There the ruling is the anchor and is cited beside the
section, for example "S3 §4.7 + R49".

## Re-plan changelog (2026-09-15)

| Finding | Ruling | Applied | Where |
| --- | --- | --- | --- |
| B3: the purity guard patches the whole process | R49 | `testing.purity_guard` is `guard.forbid_effects`, S3's per-thread guard. There are no process-wide patches, no lock, no `*modules` argument and no `PurityViolation`. `assert_emit_pure` runs its two `emit` calls inside the guard on the calling thread. | §3.1 "Purity"; §5 S4a; §8 D1; §9 R-S3-4 |
| B4: `run_case` calls a runtime entry S3 does not provide | R49 | `run_case` calls `ensure_connector(..., enabled=True)`, the replay connector's `probe`, `store_classification` and `connector_source`. It then calls `sync_connector` with S3's full signature plus `connector_id`, and reads `receipt.generation_id`. `RUNTIME_FAILPOINTS` is now `RUNTIME_SCENARIOS`: S3 §9's five boundaries, run on `_ReplayConnector` with S3's labels. `testing` re-exports S3's `record_transport` and `replay_transport`, and `ContractViolation("provider_recording")` is gone. One deliberate deviation from R49's listed order: `connector_source` runs after `store_classification`, so a dry run can take its partitions from the probe. Neither call reads the other's row. | §3.1 "The replay connector", "Scratch runs", "`run_case`", "Runtime assertions", "Provider recording"; §9 R-S3-1 to R-S3-3 |
| M2: the loader is in no plan | R50 | New slice S4c: `connectors/loader.py` with `load_registry(*, enabled_kinds, allowlist) -> LoadResult`, the `hippo serve` lifespan call, and the three tests M2 names. S4c merges before every caller. | §3.5; §4 S4c; §5; §6; §7 |
| M5: connectors run that no operator enabled | R51 | Every scratch instance is created with an explicit `enabled=True`, because R51 flips `ensure_connector`'s default. A non-dry-run `sync` of a disabled instance exits 2 through S3's refusal. `list` shows kind enablement and instance enablement. | §3.1 "Scratch runs"; §3.3; §5 S4b |
| M12: the capture-side assertions are defined nowhere | R55 | `check_capture(connector, config, *, sample)` with five named rules, each with a negative fixture | §3.1 "Capture assertions"; §5 S4a; §9 "Provides" |
| M13: nothing tests that `probe` is pure | R55 | `probe_deterministic` runs `probe` twice with two clock instants and requires equal `Classification`s. It has a negative fixture. | §3.1 "Capture assertions" |
| M15: the replay cannot confirm a deletion | R55 | `_ReplayConnector.fetch` raises `ProviderNotFoundError` for an id with no `inputs/` file. `load_case` refuses a missing input only for an `upsert`. | §3.1 "Fixture layout", "The replay connector" |
| M16: the scaffold emits an instance key part | R56 | `connector.py.tmpl` emits `NodeRef(kind="$primary_kind", key={"id": record["id"]})`, and the kit fills `instance`. The pinned scaffold output is regenerated. B4 and R46 have three consequences in the same templates: the descriptor carries `extension`, the extension registers the connector kind, and `probe` samples through the replayable methods. | §3.2 |
| m6: `TOKEN_BOUND = 1500` | R42 | `TOKEN_BOUND = base.PASSAGE_CHAR_BOUND`: 6,000 characters by R24, which approximates the specification's 1,500 tokens | §3.1 |
| m17: the offline model copies the fake's algorithm | R55 | `hashed_embedding` moves into `testing.py`. `embed_text` in `tests/fakes/fake_ollama.py` imports it function-locally. This re-plan grants that edit to S4a. | §3.1 "Offline model"; §4 S4a step 3; §7 |
| m18: the kit and the binder disagree on edge sources | R55 | `edges_fully_attributed` reads design §4's table through `emit.evidence_class(...)` | §3.1 contract table |
| m19: the non-dry-run `sync` is under-specified | R55 | In order: `_require(principal, "manage_sources")`, then `BuildActor.trusted_local()`, then exit 2 when there is no stored classification. Tests cover each step. | §3.3; §5 S4b |
| m20: guard coverage and pool context | R49, R55 | Inherited. The kit uses S3's forbidden set, which gains m20's names. S3's emit workers run in `copy_context()`, and `run_case`'s `use_registry` relies on that. | §9 R-S3-4 |
| Cross-plan R-S1-1: `Registry.load()` | R15, R50 | S4c answers it, built on S1's primitives | §3.5; §9 |
| Cross-plan R-S3-1, R-S3-2, R-S3-5 (entry, labels, one guard) and R-S3-7 (naming the row) | R49 | As for B3 and B4 | §9 |
| Context from R39 | R39 | The kit reads published records back with no registry check on read, so goldens and scenario checks can read any stored code. | §3.1 "`run_case`" step 8 |
| Context from R46 | R46 | `run_case` and `load_connector_package` take the extension from `connector.descriptor.extension`. The `extension=` arguments are gone. | §3.1 |
| Clarification, no finding | — | `changes.json` gains an optional `fetches` map. `ChangePage` JSON carries no `RawFetch` metadata, and the old layout named no place for it. | §3.1 "Fixture layout" |

These stand in substance:

- §3.4, the guide;
- the golden-file table and the registry lock;
- the commands table, except the `probe`, `sync --dry-run` and `sync` rows;
- design deviations 1–4, ratified by R7.

## 1. Goal and scope

**Goal.** A developer who has never seen hippo runs `hippo connector new`, fills in the generated
package, and runs `hippo connector validate`. The command either names the contract rule the connector
breaks or passes. A seeded violation proves that every rule in design §8 fires. An installed connector
package reaches the process registry only through the loader, and only when an operator has enabled
its kind.

**In scope.**

- `hippo.connectors.testing`, which holds:
  - the fixture layout, the replay connector, scratch runs and `run_case`;
  - the named contract, purity, capture, runtime and registry assertions;
  - the re-exported guard and transports, the offline model and `validate_package`.
- `hippo.connectors.loader`, and its call in the `hippo serve` lifespan (S4c).
- The scaffold templates behind `hippo connector new`.
- The `hippo connector new|list|validate|probe|sync` commands and their forwarding in `remote.py`.
- The developer guide `docs/spec/cdk-guide.md`.

**Out of scope.** These belong to other slices:

- S1: the registry;
- S2: the contract records, keys, render and emit binder;
- S3: the runtime, the guard, the HTTP client and credentials;
- S5: the ported connectors;
- S6: the exemplar, the HTTP routes and the MCP tool.

This plan programs against design §1–§3 and §7–§9. §9 lists what it needs from S1, S2 and S3, with
their signatures.

**Split (decision 8).** S4 is three workers:

- **S4c: the loader.** It is small and needs only S1a and S2a, so it may run beside S3.
- **S4a: the kit.** Each of these has a negative fixture: twelve contract assertions, two purity
  assertions, five capture assertions, five runtime scenarios and the registry lock. S4a also carries
  the replay, the scratch runs, the offline model and `validate_package`. That is the size of CC6 in the
  code-capture work, with a named fallback split (§4).
- **S4b: the scaffold,** the five commands, the forwarding client and the guide, the size of CC10.

S4a and S4c share only one appended line each in `tests/unit/test_import_order.py`. S4b edits no S4a or
S4c file.

## 2. Existing seams

| Seam | Use or required boundary |
| --- | --- |
| `src/hippo/cli.py:90-148` `build_parser`; `:132-148` the `user` group | The one nested subcommand group today. `connector` copies its shape: `add_subparsers(dest="connector_command", required=True)`. |
| `cli.py:150-192` `main` | Handlers return ints. `StoreLockedError`, `RemoteError` and `Denied` print `error: ...` and return 2 (`:180-185`). A refusal mapped by `_refusal` returns 2 (`:186-192`). Commands return 1 for their own recoverable failures. |
| `cli.py:236-254` `_principal`, `:257-267` `_build_actor`, `:270-272` `_require` | Identity and the capability check for commands that touch the configured store |
| `cli.py:597-612` `_context_or_running_server` | Forwarding is triggered only by `StoreLockedError`. There is no `--server` flag and no JSON output mode. |
| `tests/unit/test_import_order.py:14-28` `MODULES`; `:52-81` `HELP_MUST_NOT_IMPORT` | `hippo --help` must not load `hippo.ingest.pipeline`, `managed_activation`, `public_errors`, `fastapi` or `starlette`. Every `hippo.connectors` import in `cli.py` is therefore function-local, as `cmd_index` does. S4a and S4c each append their module to `MODULES`. |
| `src/hippo/remote.py:78-129` `RemoteHippo`, `_json`; `:156-163` | One method per endpoint, `self._json(self._client.get(...))`. A 401 maps to `RemoteError` with the token sentence, and a coded refusal maps to `code: message` (`:131-154`). |
| `tests/unit/test_cli.py:22-26` `cli_ctx`; `:278-301` `behind_server`; `:310` | Test patterns. `behind_server` imports `starlette.testclient` inside the function and needs the per-test marker (form (a) of the fleet rules). S4b's forwarding test uses `httpx.MockTransport` instead, so it needs no marker and no S6 route. |
| `tests/unit/test_prose_generation.py:32-79` `Runtime`; `:115-122` | The model protocol a managed build calls: `/api/tags` with a `digest` per model, `/api/show`, `/api/embed` and `/api/chat`. It also shows `Ollama(..., client=httpx.Client(transport=...))` and `RawArtifactStore(tmp_path / "raw", max_object_bytes=...)`. |
| `tests/fakes/fake_ollama.py:23` `DIM`; `:146-160` `embed_text` | Deterministic hashed vectors over words and trigrams. The algorithm moves verbatim into `testing.hashed_embedding` (m17). The fake keeps both names and imports the function inside `embed_text`, so conftest loads no kit module at collection. |
| `src/hippo/ollama.py:46` `Ollama` | `offline_ollama()` builds one over `httpx.MockTransport`. S3's guard refuses its client methods inside `emit` (S3 §10.1). |
| `tests/conftest.py:179-226` `store`; `:229` `LADYBUG_TEST_BUFFER_POOL_BYTES`; `:257-260` `ctx` | `HIPPO_TEST_STORE` selects fake, ladybug or neo4j. `tests/fakes/fake_store.py:66` `FakeStore` is test-only. `ctx` is `AppContext(config=Config(data_dir=...), store=store, ollama=ollama)`, the shape the scratch workspace copies. |
| `src/hippo/store/memory.py:43` `MemoryQueries(Neo4jBase)` | The Neo4j query mixin, **not** an in-memory store. Outside tests, the only store that needs no server is a temporary LadybugDB file (`store/ladybug.py:333`). See deviation 1. |
| `src/hippo/store/generations.py:63-64` `_now` | `_generation_clock` is the store clock seam and the one clock of R27. Scratch runs pin it. |
| `src/hippo/store/generations.py:966` `generation_checksums`; `store/knowledge.py:417` `_knowledge_rows`, `:519` `_knowledge_get` | The reads that bring one generation back, for goldens and for "G1 intact" |
| `src/hippo/store/migrations.py:72` `DEFAULT_WORKSPACE_ID` | The scratch instance's workspace |
| `src/hippo/knowledge/raw_artifacts.py:74-85` `RawArtifactStore(root, *, max_object_bytes)` | The scratch raw store |
| `src/hippo/ingest/managed_activation.py:163-168` `new_operation_id`; `:228` `raw_root`; `:238-241` `embedding_spec(ollama)`; `:658` the production raw store | Scratch syncs pass `embedding_spec`. The non-dry-run `sync` takes its raw store and operation id the way `run_managed_build` does. `hippo.connectors` may import `hippo.ingest`: R54 restricts only `connectors.{lanes,local,git}`. Every such import in `testing.py` and `cli.py` is function-local. |
| `src/hippo/knowledge/source_lifecycle.py:21` `OPERATION_ID` | The pattern is `^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$`. `run_case`'s `validate.<case>` ids must match it, so case names are bounded (§3.1). |
| `src/hippo/knowledge/build_authority.py:60-61` `BuildActor.trusted_local()` | The actor of every kit sync (S3 §5 entry, §5.5) |
| `src/hippo/access.py:120` `EVERYTHING`; `knowledge/query_access.py:82-91` `validate`, `:126-164` `query_session`; `knowledge/access.py:32` `AuthorizationChanged` | The scenario checks: a new internal session opens, and an old session refuses after an epoch change. |
| `src/hippo/knowledge/model.py:278-286` `Connector` (`enabled: bool = False`); `:294-307` `Artifact.kind` (includes `document`) | Enablement per instance; the scaffold's artifact kind |
| `src/hippo/access.py:41-48` `CAPABILITIES` | `manage_sources` gates commands that read or sync connector instance state. |
| `src/hippo/config.py:1-20`, `:126-152` `load_config` | Settings come from `HIPPO_*` environment variables. S4c reads its one variable, `HIPPO_CONNECTOR_ALLOWLIST`, in `loader.py`, because `config.py` is not granted (open question 2). |
| `src/hippo/web/app.py:63-68` `lifespan`; `:163-180` `startup` ("Never raises") | S4c's one call, placed before `startup(ctx)` |
| `pyproject.toml:46-47` `[project.scripts]`; `:53-54` wheel `packages = ["src/hippo"]`; `:62` `norecursedirs`; `:69` Ruff `extend-exclude` | Non-Python files under `src/hippo` ship in the wheel, so the scaffold templates are package data. Connector `fixtures` trees are never collected by pytest. Ruff excludes `docs/plans` but not `docs/spec` or `ai_docs`, so fenced Python in the guide and in this plan must be formatted. |
| `.github/workflows/ci.yml:27-28,45` | `ruff check .`, `ruff format --check .`, `pytest tests/unit` |
| R9 | `docs/spec/cdk-guide.md` is granted to S4b by name. |

## 3. Public API

### 3.1 `src/hippo/connectors/testing.py` (S4a)

```python
from .guard import forbid_effects as purity_guard  # B3, R49: the runtime's guard
from .http import ERROR_CLASSES, record_transport, replay_transport  # B4, R49: the runtime's recorder

FIXED_INSTANT: Final = datetime(2026, 1, 1, tzinfo=UTC)
SECOND_INSTANT: Final = datetime(2026, 1, 2, tzinfo=UTC)
TOKEN_BOUND: Final = base.PASSAGE_CHAR_BOUND  # m6, R42
KIT_INSTANCE_URL: Final = "https://connector-kit.invalid"
EMBEDDING_DIM: Final = 128
CASE_NAME: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
CASE_FILES: Final = ("config.json", "changes.json", "policies.json")
CASE_DIRS: Final = ("inputs", "http", "expected")
GOLDEN_FILES: Final = (
    "nodes.json",
    "edges.json",
    "passages.json",
    "units.json",
    "aliases.json",
    "failures.json",
    "coverage.json",
)
CONTRACT_ASSERTIONS: Final = (
    "registered_vocabulary",
    "nodes_have_locator_and_policy",
    "unknown_policy_is_deny",
    "edges_fully_attributed",
    "aliases_name_a_rule",
    "no_ingestion_time",
    "one_fact_per_unit",
    "spans_match_bytes",
    "passages_within_token_bound",
    "identities_from_builders",
    "direction_and_ownership",
    "parse_failures_counted",
)
PURITY_ASSERTIONS: Final = ("emit_deterministic", "emit_pure")
CAPTURE_ASSERTIONS: Final = (
    "change_page_single_partition",
    "fetch_matches_ref",
    "canonical_uri_without_credentials",
    "unknown_policy_carries_no_principals",
    "probe_deterministic",
)
RUNTIME_SCENARIOS: Final = (
    "crash_after_fetch",
    "replayed_page",
    "failed_inventory",
    "policy_change_mid_page",
    "delete_with_live_session",
)
REGISTRY_ASSERTIONS: Final = ("registry_version_bump",)
ASSERTIONS: Final[tuple[str, ...]] = (
    CONTRACT_ASSERTIONS + PURITY_ASSERTIONS + CAPTURE_ASSERTIONS + RUNTIME_SCENARIOS + REGISTRY_ASSERTIONS
)


class ContractViolation(AssertionError):
    def __init__(self, assertion: str, message: str, *, record: str | None = None) -> None: ...


@dataclass(frozen=True)
class AssertionContext:
    registry: Registry
    descriptor: ConnectorDescriptor
    connector: k.Connector
    revision: RevisionInput
    policy: PolicyObservation
    clock_instant: datetime
    run_window: tuple[datetime, datetime]
    token_bound: int = TOKEN_BOUND


@dataclass(frozen=True)
class FixtureCase:
    name: str
    root: Path
    partition: str
    config: dict
    pages: tuple[ChangePage, ...]
    fetches: Mapping[str, dict]
    inputs: Mapping[str, bytes]
    policies: Mapping[str, PolicyObservation]


@dataclass(frozen=True)
class ScratchWorkspace:
    root: Path
    ctx: AppContext
    raw_store: RawArtifactStore


@dataclass(frozen=True)
class ScratchInstance:
    row: k.Connector
    classification: Classification
    sources: Mapping[str, str]  # partition -> Source id


@dataclass(frozen=True)
class CaseResult:
    case: str
    generation_id: str | None
    records: Mapping[str, list]
    violations: tuple[ContractViolation, ...]
    diff: str
    error: str | None = None

    @property
    def passed(self) -> bool: ...


@dataclass(frozen=True)
class ValidationReport:
    connector: str
    version: str
    scope: Literal["capture", "contract", "full"]
    registry_diff: tuple[str, ...]
    cases: tuple[CaseResult, ...]
    violations: tuple[ContractViolation, ...]
    error: str | None = None

    @property
    def passed(self) -> bool: ...

    def to_json(self) -> dict: ...


def assert_registered_vocabulary(batch: EmissionBatch, context: AssertionContext) -> None: ...
def assert_nodes_have_locator_and_policy(batch: EmissionBatch, context: AssertionContext) -> None: ...
def assert_unknown_policy_is_deny(batch: EmissionBatch, context: AssertionContext) -> None: ...
def assert_edges_fully_attributed(batch: EmissionBatch, context: AssertionContext) -> None: ...
def assert_aliases_name_a_rule(batch: EmissionBatch, context: AssertionContext) -> None: ...
def assert_no_ingestion_time(batch: EmissionBatch, context: AssertionContext) -> None: ...
def assert_one_fact_per_unit(batch: EmissionBatch, context: AssertionContext) -> None: ...
def assert_spans_match_bytes(batch: EmissionBatch, context: AssertionContext) -> None: ...
def assert_passages_within_token_bound(batch: EmissionBatch, context: AssertionContext) -> None: ...
def assert_identities_from_builders(batch: EmissionBatch, context: AssertionContext) -> None: ...
def assert_direction_and_ownership(batch: EmissionBatch, context: AssertionContext) -> None: ...
def assert_parse_failures_counted(batch: EmissionBatch, context: AssertionContext) -> None: ...
def check_contract(batch: EmissionBatch, context: AssertionContext) -> tuple[ContractViolation, ...]: ...
def assert_contract(batch: EmissionBatch, registry: Registry, context: AssertionContext) -> None: ...


def assert_emit_pure(
    connector: Connector, revision: RevisionInput, mapping: TypeMapping
) -> EmissionBatch: ...


def check_capture(
    connector: SyncConnector, config: BaseModel, *, sample: int
) -> tuple[ContractViolation, ...]: ...


def load_case(case_dir: Path) -> FixtureCase: ...
def discover_cases(package_dir: Path) -> tuple[Path, ...]: ...


def hashed_embedding(text: str) -> np.ndarray: ...
def offline_ollama() -> Ollama: ...


def scratch_store(path: Path): ...


@contextmanager
def scratch_workspace(*, clock: Clock | None = None) -> Iterator[ScratchWorkspace]: ...


def prepare_instance(
    workspace: ScratchWorkspace,
    connector: Connector,
    config: BaseModel,
    *,
    clock: Clock,
    partitions: tuple[str, ...] | None = None,
) -> ScratchInstance: ...


def scratch_sync(
    workspace: ScratchWorkspace,
    connector: Connector,
    *,
    instance: ScratchInstance,
    config: BaseModel,
    partition: str,
    operation_id: str,
    options: SyncOptions | None = None,
    on_batch: Callable[[RevisionInput, EmissionBatch], None] | None = None,
    fault_hook: Callable[[str], None] | None = None,
) -> SyncReceipt: ...


def run_case(
    connector: Connector, case: FixtureCase | Path, *, update_golden: bool = False
) -> CaseResult: ...
def assert_runtime_resilience(
    connector: Connector, case: FixtureCase | Path, *, scenarios: tuple[str, ...] = RUNTIME_SCENARIOS
) -> None: ...
def dry_run_sync(
    connector: Connector, config: BaseModel, *, partition: str | None = None
) -> tuple[SyncReceipt, ...]: ...


def extension_lock(extension: TypeExtension, *, version: str) -> dict[str, str]: ...
def assert_registry_lock(extension: TypeExtension, *, version: str, lock_path: Path) -> None: ...
def error_transport(error_class: str) -> httpx.MockTransport: ...


def load_connector_package(
    target: str | Path, *, allowlist: frozenset[str] = frozenset()
) -> tuple[Connector, Path]: ...
def validate_package(
    target: str | Path,
    *,
    update_golden: bool = False,
    runtime: bool = True,
    allowlist: frozenset[str] = frozenset(),
) -> ValidationReport: ...
```

**Module rules.** `testing.py` starts with `from __future__ import annotations`. Its module-level
imports are limited to:

- the standard library, `numpy`, `httpx` and `pydantic`;
- `hippo.connectors.{base,guard,http,credentials,keys,render,emit}`.

Everything else is imported inside the function that uses it, with annotation-only names under
`TYPE_CHECKING`:

- `hippo.connectors.sync` and `hippo.connectors.loader`;
- `hippo.store`, `hippo.context` and `hippo.config`;
- `hippo.ingest.managed_activation` and `hippo.knowledge.query_access`.

**Fixture layout** (decision 1a):

```text
<package>/fixtures/registry.lock.json          template, kind and predicate body hashes, keyed name@version
<package>/fixtures/<case>/config.json          instance config, validated by descriptor.config_model
<package>/fixtures/<case>/changes.json         {"pages": [ChangePage JSON, ...], "fetches": {...}}
<package>/fixtures/<case>/policies.json        {"<external id>": PolicyObservation JSON}
<package>/fixtures/<case>/inputs/<quoted id>   raw bytes; quoted = urllib.parse.quote(external_id, safe="")
<package>/fixtures/<case>/http/NNNN.json       optional provider recording in S3 §10.2's format, for the connector's own tests
<package>/fixtures/<case>/expected/*.json      the seven GOLDEN_FILES
```

`changes.json` has two keys:

- **`pages`** holds the pages, replayed in order.
- **`fetches`** is optional. It maps an external id to the `RawFetch` fields other than `ref` and `data`
  (S2 §4.1): `content_type`, `canonical_uri`, `provider_revision`, `source_updated_at`,
  `source_timestamp_original`, `source_timezone`, `source_precision` and `parser`.

An id without a `fetches` entry replays with these values:

- `content_type="application/octet-stream"`;
- `canonical_uri=f"{KIT_INSTANCE_URL}/{quoted id}"`;
- `provider_revision=ref.provider_revision`;
- no source timestamp.

`load_case` refuses each of the following, with a message that names the file:

- a case directory name that does not match `CASE_NAME`, which keeps `validate.<case>` inside
  `OPERATION_ID`;
- a top-level entry outside `CASE_FILES` and `CASE_DIRS`;
- a missing `config.json` or `changes.json`;
- no pages, or pages that name more than one partition;
- an `inputs/` name that does not round-trip through `quote`;
- an `upsert` change whose external id has no input file (M15);
- a `fetches` entry with a field outside the list above.

A `delete` or `policy_change` needs no input file: `fetch` of an id without one raises
`ProviderNotFoundError` (below). A missing `policies.json` entry replays as
`PolicyObservation(state="unknown")`, which the runtime stores as deny. `FixtureCase.partition` is the
one partition the pages name. `load_case` reads every byte into the `FixtureCase`, so the replay does no
file I/O.

**Golden files** (decision 1g). Each golden file is canonical JSON
(`knowledge.identity.canonical_json`): a list sorted by the record `id`, with fields from the published
knowledge records.

| File | One entry per | Fields |
| --- | --- | --- |
| `nodes.json` | `KnowledgeObject` in the generation | `id`, `kind`, `canonical_key`, `observations` (each `ObjectObservation` dump without `recorded_to`) |
| `edges.json` | `Assertion` whose version is a member | `id`, `subject_id`, `predicate`, `object_id`, `scope_key`, `versions`, `support` |
| `passages.json` | `Passage` native row | `id`, `title`, `text`, `span_id`, `retrieval_view_id`, `ordinal` |
| `units.json` | `Unit` | every field except vectors |
| `aliases.json` | `SAME_OBJECT_AS` assertion | as `edges.json` |
| `failures.json` | `ParseFailure` counted in `coverage_json` | `family`, `parser`, `count` |
| `coverage.json` | the generation | `json.loads(Generation.coverage_json)` |

`MaintenanceJob` rows and `IndexEvent.payload_json` are never written to a golden file, because both
carry the `uuid4` lease owner (`ingest/build_run.py:90`, `store/generations.py:1419-1427`).
`validate_package(..., update_golden=True)` writes the seven files and the new lock keys and returns the
unified diff. `hippo connector validate --update-golden` prints that diff and exits 0. Without the flag,
a non-empty diff is a failed case and exit 1.

**The replay connector** (decision 1b, B4, M15). `_replay_connector(connector, case, *, pages=None,
policies=None, fail_on_page=None)` builds the replay in three steps:

1. It creates a subclass of the connector's class for this call:
   `type(f"_Replay{cls.__name__}", (cls,), {"__slots__": (), ...})`.
2. It copies the connector with `copy.copy`.
3. It sets the copy's `__class__` to the subclass and returns the copy.

The subclass overrides exactly three methods and inherits `descriptor`, `probe` and `emit`. When the
real `probe` calls `self.list_changes` and `self.fetch`, it therefore reads the case, which is what R49's
"the replay connector's `probe`" requires. `pages` and `policies` default to the case's own, and the
runtime scenarios pass variants. A `policies` value may be one `PolicyObservation` or a sequence, which
the replay consumes in call order and whose last item repeats. `policy_change_mid_page` needs the
sequence, because it reads A's policy twice in one page and each read must answer differently.

- **`list_changes(config, cursor)`.** The page index is `0` when `cursor is None`, and
  `json.loads(cursor.value)["page"]` otherwise.
  - An index equal to `fail_on_page` raises
    `ProviderTransientError(url=f"{KIT_INSTANCE_URL}/changes", status=503, attempts=1)`.
  - An index past the last page returns
    `ChangePage(partition=case.partition, changes=(), next_cursor=None, complete=True)`.
  - Otherwise it returns `pages[index]`. Its `next_cursor` becomes
    `SyncCursor(partition=case.partition, value=canonical_json({"page": index + 1}), scan=<scan>)`,
    or `None` on the last page. A later run therefore starts from page 0, which is a replay.
  - `<scan>` is the incoming cursor's `scan`, so the replay never overwrites the runtime's scan mode in
    the middle of a scan. On the first page, where there is no incoming cursor, it is the recorded
    `next_cursor.scan`, or `"changes"`.
  - A connector declaring `capabilities.inventory=True` has no `last_reconciled_at` in a fresh
    workspace, so its baseline run may already be an inventory scan (S3 §6.4, `reconcile_due`). The
    scaffold and the fixture connector both declare it, and no expectation below depends on it.
- **`fetch(config, ref)`.** It returns the `inputs/` bytes with the `fetches` metadata. An id with no
  input file raises `ProviderNotFoundError(url=f"{KIT_INSTANCE_URL}/{quoted id}", status=404, attempts=1)`:
  the confirmation S3 §6.4 needs before it infers a deletion (M15).
- **`fetch_policy(config, ref)`.** It returns the next observation for `external_id` (the single value,
  or the sequence's next item) with `ref` set to the request. An id with no entry gets
  `PolicyObservation(ref=ref, state="unknown")`.

A `probe` that samples through `self.list_changes` and `self.fetch` replays exactly. A `probe` that opens
its own `ProviderClient` reaches the network instead, or a test's transport. The scaffold and the fixture
connector therefore sample through their own methods (§3.2, R-S3-7).

**Scratch runs** (B4, M5). Each run gets its own workspace:

- **`scratch_store(path)`** returns `LadybugStore(path)` (deviation 1). Tests substitute the Fake or a
  capped LadybugDB with `monkeypatch.setattr(testing, "scratch_store", ...)`.
- **`scratch_workspace(clock=None)`** does the following:
  - makes a `tempfile.TemporaryDirectory(prefix="hippo-connector-kit-")` and takes
    `root = Path(tmp.name).resolve()`. `RawArtifactStore` refuses a root with symlinked components
    (`raw_artifacts.py:74-90`), and on macOS the temporary directory sits under `/var`, a symlink to
    `/private/var`. Pytest's `tmp_path` is already resolved, which is why no existing test hits this;
  - opens `store = scratch_store(root / "kit.lbug")` and calls `store.ensure_schema()`;
  - when `clock` is given, sets `store._generation_clock = clock`, the one clock of R27
    (`store/generations.py:63-64`);
  - builds `AppContext(config=Config(data_dir=root / "data"), store=store, ollama=offline_ollama())`, the
    `tests/conftest.py:257-260` shape;
  - creates `RawArtifactStore(root / "raw", max_object_bytes=SyncOptions().max_fetch_bytes)`.

  It yields `ScratchWorkspace(root, ctx, raw_store)`. On every exit it closes the context and removes
  the directory.
- **`_kit_registry(descriptor)`** builds `Registry.with_builtins()`, calls
  `register(descriptor.extension, declared_families=descriptor.families)` (R46, S1 D5), then calls
  `freeze()`. A refusal raises `RegistrationError`. Every kit run registers only the built-ins and the
  connector's own extension, so a golden never depends on which other connectors a process has enabled.
- **`prepare_instance(workspace, connector, config, *, clock, partitions=None)`** runs R49's calls in
  this order:
  1. `sync.ensure_connector(store, workspace_id=DEFAULT_WORKSPACE_ID, kind=descriptor.name, instance_url=KIT_INSTANCE_URL, config=config, enabled=True)`.
     `enabled=True` is explicit because R51 makes `False` the default (M5).
  2. `classification = connector.probe(config, clock)`.
  3. `row = sync.store_classification(store, connector=row, classification=classification)`.
  4. `sync.connector_source(store, connector=row, partition=p, name=f"{descriptor.name} {p}")` for each
     `p` in `partitions`, or in `classification.partitions` when `partitions` is `None`.

  It returns `ScratchInstance(row, classification, {partition: source_id})`. `connector_source` comes
  after `store_classification` so that a dry run can take its partitions from the probe. Neither call
  reads the other's row, so moving it changes no write.
- **`scratch_sync(...)`** makes one call, with S3's full signature (S3 §4.7 + R49):

```python
receipt = sync.sync_connector(
    workspace.ctx,
    connector,
    connector_id=instance.row.id,
    config=config,
    partition=partition,
    actor=BuildActor.trusted_local(),
    registry=current_registry(),
    options=options or SyncOptions(emit_workers=1),
    raw_store=workspace.raw_store,
    embedding_spec=embedding_spec(workspace.ctx.ollama),
    operation_id=operation_id,
    should_stop=lambda: False,
    on_batch=on_batch,
    fault_hook=fault_hook,
)
```

- **`dry_run_sync(connector, config, *, partition=None)`** backs `hippo connector sync --dry-run`. It
  runs under `use_registry(_kit_registry(connector.descriptor))`, in one `scratch_workspace()` that keeps
  the store's own clock:
  1. `prepare_instance(..., clock=workspace.ctx.store._now, partitions=(partition,) if partition else None)`;
  2. one `scratch_sync(..., operation_id=f"dry-run.{index}")` per partition, in partition order.

  It returns the receipts. The connector is the real one, reading its provider read-only.

**`run_case`** (decision 1b, B4):

1. When a path is given, `case = load_case(case)`. Record `started = datetime.now(UTC)`.
2. `registry = _kit_registry(connector.descriptor)`. A `RegistrationError` returns a `CaseResult` with
   `error` set. Everything below runs under `use_registry(registry)` (R16), so S2's binder and S3's entry
   check both find the registry as `current_registry()`.
3. `config = descriptor.config_model.model_validate(case.config)`, then
   `replay = _replay_connector(connector, case)`.
4. Inside `with scratch_workspace(clock=lambda: FIXED_INSTANT) as workspace:`, call
   `instance = prepare_instance(workspace, replay, config, clock=lambda: FIXED_INSTANT, partitions=(case.partition,))`.
5. `receipt = scratch_sync(workspace, replay, instance=instance, config=config, partition=case.partition, operation_id=f"validate.{case.name}", on_batch=record)`,
   where `record(revision, batch)` only appends the pair. S3 §4.7's observer signature is
   `(revision, batch)`, and the mapping travels in `revision.mapping`. The observer does nothing more,
   because a raise inside `on_batch` would fail the sync with an error that names no rule.
6. Some exceptions from steps 4–5 end the case with `generation_id=None` and
   `error=f"{type(exc).__name__}: {exc}"`:
   - `ConnectorSyncRefused`;
   - `ConnectorContractViolation`;
   - `ContractError`, which includes `RegistrationRequired` and `BindRefused`;
   - `pydantic.ValidationError`.

   Every other exception propagates. A `receipt.outcome` other than `"published"` also ends the case,
   with the error `The case published nothing: {outcome}`.
7. After `sync_connector` has returned, each recorded `(revision, batch)` gets two checks:
   - `check_contract(batch, AssertionContext(registry, descriptor, instance.row, revision, policy, FIXED_INSTANT, (started, datetime.now(UTC))))`,
     where `policy` is the case's observation for `revision.artifact.external_id`, or unknown;
   - `assert_emit_pure(replay, revision, revision.mapping)`.

   Both append to `violations`.
8. Read the published generation back by `receipt.generation_id` with `_knowledge_rows(kind,
   generation_id=...)` and `_knowledge_get`, and build the seven golden lists. No read checks
   vocabulary (R39).
9. Diff the lists against `expected/`. With `update_golden=True`, write them and return the diff.

**Contract assertions** (decision 1c). Each is a named function that raises
`ContractViolation(assertion=<name>, message, record=<emission key or ref>)`. Where S2 already has the
check, the kit calls that function and adds nothing. The kit asserts at emission time what S2 enforces at
bind time, and the two cannot disagree because they run one function.

The "Also enforced at" column says where S2 refuses the same condition during a sync. When that happens,
`run_case` records the refusal as its `error` (step 6), and the contract scope of `validate_package` has
already named the rule. S2's construction validators would refuse some of these inputs outright, so the
negative fixtures build those emission records with `model_construct`.

| Assertion | Fires when | Calls | Also enforced at |
| --- | --- | --- | --- |
| `registered_vocabulary` | a node kind, edge predicate, span locator kind or edge source is not in `context.registry` | `Registry.object_kind`, `.predicate`, `.locator`, `.evidence_source` (S1 §5.2) | bind step 2 (S2 §8.1) |
| `nodes_have_locator_and_policy` | a node emission has no span, or `context.revision.artifact.policy_id` is empty | — | kit only |
| `unknown_policy_is_deny` | `context.policy.state == "unknown"`, and `emit.policy_record(context.policy, connector=context.connector, workspace_id=context.connector.workspace_id, observed_at=context.clock_instant, expires_at=context.clock_instant + timedelta(minutes=10))` has `mode != "unknown"` | `emit.policy_record` (S2 §4.5, with R44's principal map) | capture (S3 §5.3) |
| `edges_fully_attributed` | `emit.evidence_class(edge.family, edge.source, edge.metadata_origin)` raises, because the pair has no row in design §4's table (m18; design §8: "a source with a deterministic row in the §4 table"). An edge's statement is the kit's rendering (S2 §7), so no connector can omit one. | `emit.evidence_class` (S2 §4.5, §8.3) | bind (S2 §8.3) |
| `aliases_name_a_rule` | an alias emission's `rule` is empty | — | kit only |
| `no_ingestion_time` | a node `ts`, passage `ts`, edge `valid_from` or edge `valid_to` equals `clock_instant` or falls inside `run_window` | — | kit only |
| `one_fact_per_unit` | a slice unit's span does not verify, or its `start`/`end` fall outside the verified text; or `render.render_facts(...)` yields a `RenderedText` whose `template` is not one of the node kind's fact templates | `emit.verify_span`, `render.render_label`, `render.render_facts`, `render.unit_text` | bind (S2 §8.7) |
| `spans_match_bytes` | `emit.verify_span(revision.data, span, artifact=revision.artifact)` raises, or a given `span.text` differs from its result | `emit.verify_span` | bind (S2 §8.4) |
| `passages_within_token_bound` | `base.token_count(text) > context.token_bound` for a passage's verified text | `base.token_count` (R26) | bind (S2 §8.5) |
| `identities_from_builders` | `keys.check_key_parts(registry.object_kind(ref.kind), ref)` or `keys.canonical_key(registry, ref, instance=context.connector.instance_url)` raises, for any `NodeRef` in the batch | `keys.check_key_parts`, `keys.canonical_key` (S2 §4.2, and R53's declared instance) | bind (S2 §6) |
| `direction_and_ownership` | `emit.check_direction_and_ownership(registry, descriptor, edge.predicate, edge.subject.kind, edge.object.kind)` raises. The message is S2's developer-facing text. | `emit.check_direction_and_ownership` (S2 §8.5) | bind (S2 §8.5) |
| `parse_failures_counted` | non-empty revision bytes yield no node, passage or unit, and no `ParseFailure` | — | kit only |

`check_contract` runs the twelve functions in `CONTRACT_ASSERTIONS` order and collects their violations.
`assert_contract` raises the first one (deviation 2).

**Purity** (decision 1d, B3). `purity_guard` is `hippo.connectors.guard.forbid_effects` itself (S3 §4.1,
§10.1): a `sys.setprofile` hook on the calling thread only. It enforces S3's forbidden set, which R49
widens with m20's `time.clock_gettime`, `time.clock_gettime_ns`, `time.process_time`, `sys.setprofile`
and `threading.setprofile`.

`assert_emit_pure(connector, revision, mapping)` calls `connector.emit(revision, mapping)` twice, each
call inside `forbid_effects()` on the calling thread:

- an `EmitSideEffect` becomes `ContractViolation("emit_pure", str(exc))`, raised from the original;
- two batches whose `canonical_json(batch.model_dump(mode="json"))` differ raise
  `ContractViolation("emit_deterministic", ...)`;
- otherwise it returns the first batch.

No other thread is affected, so S6's validate route and MCP tool can run the check inside `hippo serve`
(B3). The kit and the runtime refuse exactly the same calls, because they run one function.

**Capture assertions** (M12, M13, ruling R1). `check_capture(connector, config, *, sample)` exercises a
connector's sync half and returns the violations it finds. The argument is a `SyncConnector` (S2 §4.1), so
S5's coordinator-lane connectors, which have no `emit`, qualify. The function opens no store and makes no
HTTP call of its own. It calls the connector's four sync methods, which read whatever the connector reads:
a directory, a test's transport, or the case for a replay connector. `sample`, a positive int, bounds the
work to at most `sample` pages listed and at most `sample` changes fetched and policy-read.

S2's construction validators refuse some of these conditions inside the connector's own method. The kit
therefore wraps each call in `try`. A `pydantic.ValidationError` or `ContractError` raised inside
`list_changes`, `fetch` or `fetch_policy` is reported under the rule for the record that call was
building. Everything else is behaviour the kit observes directly.

| Assertion | Fires when | Reuses |
| --- | --- | --- |
| `change_page_single_partition` | `list_changes(config, cursor)` returns a page whose `partition` differs from `cursor.partition` for a follow-up cursor, or a change or `next_cursor` names another partition, or building the page raised S2's `A change page cannot mix partitions` | S2 §4.6, `ChangePage` rule |
| `fetch_matches_ref` | `fetch(config, ref)` returns a `RawFetch` whose `ref` or `external_id` differs from the requested ref, or whose `provider_revision` differs from a revision the change named; or `fetch_policy(config, ref)` returns an observation whose `ref` differs | S2 §4.6, `RawFetch` rule |
| `canonical_uri_without_credentials` | a fetched `canonical_uri` has userinfo, or `credentials.redact_url(uri) != uri` because a query value has a secret name | `credentials.redact_url` (S3 §4.2) |
| `unknown_policy_carries_no_principals` | an observation has `state="unknown"` with a mode or any principal, or building it raised S2's `An unknown policy carries no principals; the runtime stores it as deny` | S2 §4.6, `PolicyObservation` rule |
| `probe_deterministic` | `probe(config, lambda: FIXED_INSTANT)` and `probe(config, lambda: SECOND_INSTANT)` return `Classification`s whose `canonical_json(... .model_dump(mode="json"))` differ | S2 §4.1, `probe(config, clock)` |

The procedure runs in this order:

1. Starting from `cursor = None`, list up to `sample` pages. Check each page and collect its changes.
   Stop at `next_cursor is None`, or once `sample` changes are collected.
2. `fetch` each collected `upsert` and check the result.
3. Call `fetch_policy` for each collected `upsert` and `policy_change` and check the result.
4. Run `probe_deterministic`.

`probe`'s clock (S2 §4.1) is the only clock a connector sees. Inside `run_case`, the store clock is
pinned to the same instant (R27). `probe_deterministic` runs `probe` unguarded, because a lane connector's
`probe` may run `git` or read files, and neither is an `emit` effect. It checks design §2's "pure function
of the descriptor, the config and the sampled bytes" by varying the one input that must not matter.

**Provider recording** (decision 1e, B4). `testing.record_transport` and `testing.replay_transport` are
S3's `http.record_transport` and `http.replay_transport` (S3 §4.3, §10.2). There is one `http/NNNN.json`
format, and an unexpected request raises `ProviderMalformedError`. `testing.ERROR_CLASSES` is
`http.ERROR_CLASSES`. The kit keeps `error_transport(error_class)`, whose canned responses S3 §10.2
already classifies:

| Class | Response |
| --- | --- |
| `authentication` | 401 |
| `forbidden` | 403 |
| `not_found` | 404 |
| `throttled` | 429 with `Retry-After: 1` |
| `transient` | 503 |
| `malformed` | 200 with an invalid JSON body |

**Offline model** (decision 6, m17). `hashed_embedding(text)` is `embed_text` from
`tests/fakes/fake_ollama.py:146-160`, moved verbatim with `EMBEDDING_DIM = 128`:

- strip a `search_query: ` or `search_document: ` prefix and lowercase the text;
- take word features and padded-trigram features;
- pick the bucket and sign from `md5`;
- weight words 2.0;
- L2-normalize.

The fake keeps its names. `embed_text(text)` becomes a function-local
`from hippo.connectors.testing import hashed_embedding` followed by the call, and `DIM` stays. No test
changes an import, and conftest loads no kit module at collection.

`offline_ollama()` returns
`Ollama("http://connector-kit-model", "kit-chat:latest", "kit-embed:latest", num_ctx=8192, client=httpx.Client(base_url="http://connector-kit-model", transport=httpx.MockTransport(_offline_handle)))`.
The handler answers:

- `/api/tags` with both models and a `digest` each, in the `tests/unit/test_prose_generation.py:47-56`
  shape;
- `/api/show` with `["embedding"]` for the embed model and `["completion"]` for the chat model;
- `/api/embed` with `hashed_embedding` vectors;
- `/api/chat` with a 500.

**Negative-fixture convention** (decision 1f). `tests/unit/test_connector_testing_kit.py` holds a table
`VIOLATIONS: dict[str, Callable[[], Violation]]` with exactly one entry per name in `testing.ASSERTIONS`.
A completeness test fails when a name has no entry. Each entry builds the smallest input that breaks its
one rule:

- **A contract assertion:** an `EmissionBatch` and an `AssertionContext`, with `model_construct` where S2
  would refuse construction.
- **`emit_deterministic` and `emit_pure`:** a connector whose `emit` returns a different batch on its
  second call, and one whose `emit` calls `time.time()`.
- **A capture assertion:** a small `SyncConnector` with one misbehaving method: a second page for
  another partition, a fetch that answers another ref, a `canonical_uri` carrying `?token=`, an unknown
  observation built with principals through `model_construct`, or a `probe` that stamps `clock()` into a
  warning.
- **A runtime scenario:** a double of `testing.scratch_sync`, installed with `monkeypatch`, that breaks
  that scenario's invariant once (the last column of the scenario table below).
- **`registry_version_bump`:** an extension whose template text changed under an unchanged version.

The positive fixture is S3's fixture connector with its `fixtures/basic` case (R10, R-S3-7). It passes
every assertion.

**Runtime assertions** (design §8, B4). `assert_runtime_resilience(connector, case, *, scenarios=RUNTIME_SCENARIOS)`
runs each scenario in its own `scratch_workspace(clock=lambda: FIXED_INSTANT)`, under
`use_registry(_kit_registry(descriptor))`, on `_replay_connector` variants of the case, and with S3 §9's
labels.

The case needs at least two `upsert` changes: A is the first upserted external id in page order and B the
second. A case with fewer raises
`ContractViolation("<scenario>", "runtime scenarios need a case with two upserted records")`.

Every scenario starts the same way:

1. `prepare_instance`.
2. A baseline `scratch_sync` of the case, which publishes G1.
3. Record `generation_checksums(G1)`, the Source's `active_generation_id`, `SyncState.cursor_json` and
   `authorization_epoch()`.

"G1 intact" means three things hold: the Source's `active_generation_id` is G1,
`generation_checksums(G1)` equals its baseline, and `query_session(ctx, EVERYTHING)` opens and closes
without raising. A failed check raises `ContractViolation(<scenario>, "<scenario>: <the failed check>")`.

| Scenario | S3 §9 boundary and label | Replay and options | Expected, else the scenario fires | Negative double of `scratch_sync` |
| --- | --- | --- | --- | --- |
| `crash_after_fetch` | crash after fetch, before checkpoint; `after_fetch` | Run 2 lists `[delete A]`, and `fault_hook` raises at `after_fetch`. | The injected fault propagates. G1 is intact. A's `deleted_at` is unset. `SyncState.cursor_json` equals its baseline. Run 3, without the hook, publishes G2, whose members exclude A. | moves the raise from `after_fetch` to `after_checkpoint`, so the checkpoint commits |
| `replayed_page` | replayed page; `after_checkpoint` | Run 2 lists `[delete A]` and raises at `after_checkpoint`. Run 3 replays the same page, because the stored cursor restarts at page 0, and raises at `after_checkpoint` again. | After run 3, `authorization_epoch()`, `SyncState.cursor_json` and A's `Artifact` row equal their values after run 2: a replay is a no-op by identity (S3 §5.4, with R52's refresh rule). G1 is intact. Run 4 publishes G2. | refreshes `verified_at` on every stored `AccessPolicy` before delegating, which moves the epoch (the review's M3 defect) |
| `failed_inventory` | failed inventory; the provider raises on page 2 | Run 2 lists `[upsert A]` with `complete=False` and a `scan="inventory"` cursor, with `fail_on_page=1` and `SyncOptions(emit_workers=1, reconcile=True)`. Skipped by declaration when `descriptor.capabilities.inventory` is false. | Run 2 ends without publishing, and the `ProviderTransientError` propagates (S3 §6.1, DV5). No G1 member artifact has `deleted_at`. G1 is intact, and the Source has no generation beyond G1. | sets `deleted_at` on B after the failure, then re-raises |
| `policy_change_mid_page` | policy change mid-page; `after_checkpoint` | Run 2 lists `[upsert A, policy_change A, upsert B]`. The replay's observation for A flips between unknown and `known`/`workspace`. Run 2 raises at `after_checkpoint`, and run 3 publishes. | After run 2, A's `Artifact.policy_id` names the new policy and `authorization_epoch()` has moved: narrowing takes effect at the checkpoint (S3 §6.3). G1 is intact. After run 3, every `EvidenceSpan` of G1 is still stored with its baseline `policy_id` (R48). | restores A's previous `policy_id` after the crash |
| `delete_with_live_session` | delete of an artifact with a live query session; `after_checkpoint` | A `query_session(ctx, EVERYTHING)` is entered before run 2. Run 2 lists `[delete A]` and raises at `after_checkpoint`. | The old session's `validate()` raises `AuthorizationChanged("Permissions changed; repeat the query")` (`query_access.py:89-91`). Its exit raises the same error, which the kit catches. A new session opens. A's `deleted_at` is set, and G1 is still the active generation. Run 3 publishes G2 without A. | clears A's `deleted_at` after the crash |

The kit's scenarios check what any connector's case can show without users or principals. The
reader-specific halves of these boundaries stay in S3's matrix rows M8, M8b and M9, which run on the
fixture connector with real users:

- a narrowed reader loses A;
- widening waits for a new revision;
- `collect_generation` is blocked by a live snapshot.

**Registry assertion.** `extension_lock` hashes the canonical JSON body of every fact template, object kind
and predicate. The keys are `template:<kind>/<name>@<template version>`, `kind:<name>@<descriptor
version>` and `predicate:<name>@<descriptor version>`. Keying kinds and predicates by the descriptor version
covers R20's `label_template` and `verb_phrase`. `assert_registry_lock` raises
`ContractViolation("registry_version_bump", "<key> changed without a version bump")` when a key present in
both the lock and the extension has a different hash. `--update-golden` writes a new key. It never
rewrites a changed body under an unchanged key.

**`load_connector_package(target, *, allowlist=frozenset())`** returns `(connector, package_dir)`.

- **A path.** It must be a directory holding `__init__.py`.
  - Under `src/hippo/connectors/`, it is imported by its dotted name.
  - Anywhere else, it is imported by file location under the module name
    `hippo_connector_under_test_<directory name>`.

  The package must export `Connector`, as the scaffold's `__init__.py` does and as design §9's
  entry-point form names.
- **A name.** It is resolved by `loader.discover_connectors(allowlist=allowlist)` (§3.5). An in-repo
  package always resolves; an entry point resolves only when allowlisted. An unknown or untrusted name
  raises `loader.ConnectorLoadError`.

The connector is `Connector()`, constructed with no arguments. `package_dir` is the directory of the
class's module.

**`validate_package(target, *, update_golden=False, runtime=True, allowlist=frozenset())`** (decision 1g)
works in six steps:

1. `load_connector_package(target, allowlist=allowlist)`. A failure returns a report whose `error` is set,
   which the CLI exits 2 on.
2. `registry = _kit_registry(descriptor)`. A `RegistrationError` sets `error` (exit 2). The remaining
   steps run under `use_registry(registry)`.
3. **A coordinator-lane connector** (`descriptor.capabilities.derivation == "coordinator_lane"`, R1)
   gets scope `capture`. For each case, the kit runs `check_capture(connector, <case config>, sample=10)`
   on the real connector. The emit, runtime and registry assertions are skipped by declaration, never by
   exception, and `VIOLATIONS` still covers every name. A package with no case sets
   `error="No fixture cases under <dir>/fixtures"`.
4. **Any other connector:**
   - `assert_registry_lock(descriptor.extension, version=descriptor.version, lock_path=package_dir / "fixtures" / "registry.lock.json")`;
   - `registry_diff` lists what the extension adds over `Registry.with_builtins()`, sorted: `+ kind <name>`,
     `+ predicate <name>`, `+ locator <name>`, `+ artifact kind <name>`, `+ connector kind <name>` and
     `+ template <kind>/<name>@<version>`. The diff is independent of the lock, so it stays the same
     after `--update-golden`. That is what design §9's "prints the registry diff" and S6's
     `test_validate_passes_the_exemplar_and_reports_its_registry_diff` read. The lock's own check is
     `assert_registry_lock`, above.
5. For each case in `discover_cases(package_dir)`:
   1. `replay = _replay_connector(connector, case)`.
   2. `check_capture(replay, config, sample=<the case's change count>)`. This checks the case files
      against the capture rules and runs `probe_deterministic` on the real `probe`.
   3. `classification = replay.probe(config, lambda: FIXED_INSTANT)`. `mapping` is the case partition's
      mapping.
   4. `row = k.Connector(workspace_id=DEFAULT_WORKSPACE_ID, kind=descriptor.name, instance_url=KIT_INSTANCE_URL, config_json=config.model_dump_json(), enabled=True)`.
      It is built in memory and never stored.
   5. For each `upsert`, with a temporary `RawArtifactStore` and no database:
      - `put_bytes`;
      - `captured = emit.capture_records(fetch, policy, connector=row, workspace_id=DEFAULT_WORKSPACE_ID, source_id=f"kit-{case.name}", raw_uri=<the stored uri>, observed_at=FIXED_INSTANT, policy_expires_at=FIXED_INSTANT + timedelta(minutes=10))`;
      - `revision = RevisionInput(partition=case.partition, artifact=captured.artifact, revision=captured.revision, data=fetch.data, config=config, mapping=mapping, registry=registry, span_policy_id=captured.policy.id)`
        (R48);
      - `batch = assert_emit_pure(replay, revision, mapping)`, then `check_contract(batch, <its context>)`.
6. With `runtime=True`, the scope is `full`:
   - `run_case(connector, case, update_golden=update_golden)` runs for each case;
   - then `assert_runtime_resilience(connector, <the first case, in name order, with two upserts>)` runs.

   Otherwise the scope is `contract`. S6's route and MCP tool pass `runtime=False` (R8), because a scratch
   build does not belong inside a server request.

`ValidationReport.passed` holds when `error` is `None`, `violations` is empty and every case passed.

### 3.2 The scaffold (S4b, decision 2)

`src/hippo/connectors/scaffold/__init__.py`:

```python
FAMILIES_REQUIRE_REGISTRY: Final = True
NAME: Final = re.compile(r"^[a-z][a-z0-9_]{1,62}$")


@dataclass(frozen=True)
class ScaffoldRequest:
    name: str
    family: str
    kinds: tuple[str, ...]


def render_package(request: ScaffoldRequest, dest: Path) -> tuple[Path, ...]: ...
```

The templates live at `src/hippo/connectors/scaffold/templates/` as package data and are read through
`importlib.resources.files("hippo.connectors.scaffold") / "templates"`. They are `string.Template` files
with the placeholders `$name`, `$class_name`, `$family`, `$kinds`, `$primary_kind` and `$key_prefix`.
Only rows marked M16, R46 or B4 changed in the re-plan.

| Template | Writes | Content |
| --- | --- | --- |
| `__init__.py.tmpl` | `<name>/__init__.py` | `from .connector import $class_name as Connector`: the export that the loader and `load_connector_package` read (§3.1, §3.5) |
| `connector.py.tmpl` | `<name>/connector.py` | See "The generated connector" below (M16, R46, B4). |
| `types.py.tmpl` | `<name>/types.py` | `EXTENSION = TypeExtension(object_kinds=(...), connector_kinds=("$name",))`. There is one `ObjectKindDefinition` per kind: an attrs model with `extra="forbid"` and `title: str`, `key_template=("instance", "id")` (unchanged, because `instance` is filled by the kit and never emitted), `key_prefix="$key_prefix"`, `label_template="{title}"`, and one `FactTemplate(name="summary", version="1", consumes=("title",), text="Record {key} is titled {title}")`. `connector_kinds` registers the kind that `ensure_connector(kind=descriptor.name)` stores (B4). |
| `templates.py.tmpl` | `<name>/templates.py` | The `FactTemplate` objects that `types.py` imports. Every generated module imports only from `hippo.connectors`, `hippo.connectors.base`, `hippo.connectors.classify`, `hippo.connectors.keys`, `hippo.connectors.render`, `hippo.knowledge.model`, `pydantic` and the standard library (R-S2-8, R-S2-10). |
| `fixtures/basic/...` | `<name>/fixtures/basic/` | `config.json` (`{"export_dir": ".", "partition": "export"}`); `changes.json` with one complete page of two upserts, `record-1` and `record-2`, the second malformed, which meets the runtime scenarios' two-upsert rule; `policies.json` (`{}`); `inputs/record-1`; `inputs/record-2` |
| `test_connector.py.tmpl` | `<name>/tests/test_connector.py` | `assert validate_package(Path(__file__).parents[1]).passed` |

**The generated connector.** `connector.py.tmpl` writes `$class_name` and `ExportConfig`. `ExportConfig`
has `export_dir: str` and `partition: str = "export"`, with `extra="forbid"`. The descriptor (R46) is:

```python
descriptor = ConnectorDescriptor(
    name="$name",
    version="1",
    families=("$family",),
    kinds=$kinds,
    predicates=(),
    artifact_kinds=("document",),
    locator_kinds=("field",),
    capabilities=ConnectorCapabilities(inventory=True),
    config_model=ExportConfig,
    credentials=(),
    parsers=(),
    extension=EXTENSION,
)
```

The methods:

- `list_changes` lists the `*.json` files under `config.export_dir` as one complete page of `upsert`
  changes.
- `fetch` reads the bytes.
- `fetch_policy` returns unknown, with a comment saying unknown is deny.
- `probe` samples up to ten records through `self.list_changes(config, None)` and
  `self.fetch(config, ref)`, so the kit's replay is exact (§3.1). It then calls
  `classify.classify(self.descriptor, config, items, current_registry(), spec=classify.classifier_spec(), capabilities=self.descriptor.capabilities, kinds=(KindMapping(provider_type="record", kind="$primary_kind"),))`.
- `emit` parses one JSON object and emits one node:
  `NodeEmission(ref=NodeRef(kind="$primary_kind", key={"id": record["id"]}), attrs={"title": record["title"]}, span=SpanRef(locator_kind="field", locator={"field_path": "title"}), source="metadata", metadata_origin="catalog")`.
  - The kit fills the `instance` key part from the connector row (S2 §6 step 2, M16).
  - A record that does not parse, or lacks `id` or `title`, becomes
    `ParseFailure(family="$family", reason="invalid_record")`.

After writing the files, `render_package` calls `validate_package(dest / request.name,
update_golden=True)` once, which computes the goldens and the registry lock. A freshly scaffolded package
therefore passes `validate`.

The generated test's goldens are pinned in `tests/unit/test_connector_scaffold.py`, so a kit change that
alters scaffold output fails there, not silently in a developer's package. The pinned output is
regenerated from the corrected templates (M16).

### 3.3 The commands (S4b, decision 3)

Parser additions, placed after the `user` group at `cli.py:132-148`:

```text
hippo connector new <name> --family <family> [--kinds <kind> ...] [--dest <dir>]
hippo connector list
hippo connector validate <package-or-path> [--update-golden]
hippo connector probe <name> --config <file>
hippo connector sync <instance> [--config <file>] [--partition <p>] [--dry-run]
```

`main`'s handler table (`cli.py:155-169`) gains `"connector": cmd_connector`. `cmd_connector` dispatches on
`args.connector_command` and imports `hippo.connectors.*` inside each branch.

**Resolving a connector.** Most commands resolve a connector through the loader (§3.5):

- `probe <name>`, `sync <name> --dry-run` and `validate <name>` resolve it with
  `loader.discover_connectors(allowlist=loader.configured_allowlist())`: an in-repo package, or an
  allowlisted entry point.
- `validate <path>` imports the directory (§3.1).

These commands use a scratch registry holding the built-ins and that connector's extension, so a kind
needs no enablement to be validated, probed or dry-run. Enablement gates only a sync into the configured
workspace (M5, R51).

| Command | Store | Provider | Forwards when the store is locked | Exit codes |
| --- | --- | --- | --- | --- |
| `new` | none (writes only under `--dest`) | none | never | 0 written; 2 for an invalid name, an unknown family, a name that is already a registered connector kind, or an existing target |
| `list` | reads `Connector` rows (requires `manage_sources` when users exist) and calls `loader.load_connectors(ctx)` | none | yes: `RemoteHippo.connectors()` | 0; 2 when denied or on a remote refusal |
| `validate` | scratch only | none (replay) | never | 0 passed; 1 for a violation or golden diff; 2 when the package cannot load, is untrusted, or its registration is refused |
| `probe` | none | read-only, through the connector | never (the config file and credential references stay on the caller's machine) | 0 classified; 1 when the classification is a registration request (prints the `TypeExtension` needed); 2 for an unknown or untrusted connector or an invalid config |
| `sync --dry-run` | scratch only (`testing.dry_run_sync`) | read-only | never | 0 printed coverage; 1 sync failed; 2 for an unknown or untrusted connector or an invalid config |
| `sync` | configured store (requires `manage_sources`) | read-only | never; prints `error: the database is open in hippo serve; stop it to sync, or use --dry-run` and returns 2 | 0; 1 sync failed; 2 when denied, locked, the kind is not enabled, the instance is disabled, there is no stored classification, or the input is invalid |

`<instance>` is a connector name when `--config` is given (dry run), and a stored `Connector.id`
otherwise. Output is human text through `print` and `print_table` (`cli.py:815-825`).

- **`list`** prints the name, version, families, origin (`built-in`, `in-repo` or `entry point`),
  enabled, instances and classified partitions.
  - The kind's `enabled` is its `ConnectorEntry.enabled` from the load, and each instance shows its own
    `Connector.enabled`.
  - An entry point that fails to import or register is a row with `error: <exception class name>`
    (design §9).
  - An entry point missing from the allowlist is a row with `error: not allowlisted`.
- **`probe`** prints, per partition, the family, the mapping from provider type to kind, the observed
  capabilities, the sample count, the warnings and the registry fingerprint.
- **`validate`** prints one line per violation (`<assertion>: <message> [<record>]`), the case diffs, and
  the registry diff (`+ kind incident`, `+ predicate AFFECTS`).
- **`sync <instance>` without `--dry-run`** (m19, M5) runs these steps in order:
  1. Open the configured context. `StoreLockedError` prints the locked message above and exits 2.
  2. `_require(_principal(ctx), "manage_sources")` (`cli.py:236-272`). `Denied` exits 2.
  3. `loader.load_connectors(ctx)` installs the frozen process registry (§3.5).
  4. Read the `Connector` row by id; an absent row exits 2. Its `kind` must be registered in that load,
     else `error: connector kind {kind} is not enabled` and exit 2.
  5. `config = descriptor.config_model.model_validate_json(row.config_json)`.
  6. The partitions are `--partition`, or else every partition in `row.classification_json`. With none:
     `error: connector instance {id} has no stored classification; probe it first` and exit 2.
  7. For each partition, call `sync.connector_source(ctx.store, connector=row, partition=p, name=f"{row.kind} {p}")`,
     then:

     ```python
     receipt = sync.sync_connector(
         ctx,
         connector,
         connector_id=row.id,
         config=config,
         partition=p,
         actor=BuildActor.trusted_local(),
         registry=current_registry(),
         options=SyncOptions(),
         raw_store=RawArtifactStore(raw_root(ctx), max_object_bytes=int(ctx.config.max_upload_bytes)),
         embedding_spec=embedding_spec(ctx.ollama),
         operation_id=new_operation_id(),
         should_stop=lambda: False,
     )
     ```

     The raw store and the operation id come from the same sources `run_managed_build` uses
     (`managed_activation.py:163`, `:228`, `:238`, `:658`).

  The actor is the trusted local maintenance actor, because S3 refuses any other (S3 §5.5). Step 2's
  capability check is the operator's authorization. `ConnectorSyncRefused` covers a disabled instance
  (R51) and a partition without a stored classification (S3 §5 entry); it prints `error: <message>` and
  exits 2. Any other sync failure prints `error: <message>` and exits 1.

`remote.py` gains one method, placed after `sources` at `remote.py:159-160`:

```python
def connectors(self) -> list[dict[str, Any]]:
    return self._json(self._client.get("/api/connectors"))
```

**The `GET /api/connectors` response contract** is defined here and implemented by S6, which builds it
from `app.state.connector_load` (§3.5) and the `Connector` rows. It is a list of `ConnectorSummary`
objects:

```json
{
  "name": "incidents_ndjson",
  "version": "1",
  "families": ["incident"],
  "origin": "in-repo",
  "enabled": true,
  "error": null,
  "instances": [{"id": "connector-...", "enabled": true, "partitions": [{"partition": "...", "family": "incident"}]}]
}
```

The only change is the new per-instance `enabled` (M5).

### 3.4 The developer guide (S4b, decision 4)

`docs/spec/cdk-guide.md` outline:

1. What a connector is: the descriptor and methods of design §1, with no store, index, model or clock.
2. `hippo connector new`: the generated files (the §3.2 table).
3. The descriptor (example `descriptor`).
4. Registering types: `TypeExtension`, kinds, predicates with `owner_families`, fact templates (example
   `types`).
5. Talking to the provider: `list_changes`, `fetch`, `fetch_policy`, and the recording helpers (example
   `sync_half`).
6. `emit`: nodes, edges, passages, units, aliases, failures, and rendering (example `emit`).
7. Fixtures and goldens: the §3.1 layout table and `--update-golden`.
8. `hippo connector validate`: one row per name in `testing.ASSERTIONS`, with what trips it and how to fix
   it.
9. `hippo connector probe` and classification.
10. `hippo connector sync --dry-run`.
11. Packaging and the `hippo.connectors` entry point group.
12. The rules the kit enforces: no model call, no clock, unknown policy is deny, no unearned relation
    label.

**Examples are the fixture connector.** Every fenced Python block in the guide is preceded by
`<!-- cdk-guide: example <name> -->`. It must equal, byte for byte, the region between
`# cdk-guide: begin <name>` and `# cdk-guide: end <name>` in S3's fixture connector source (R-S3-7).

- S4b adds those marker comments to S3's file, comments only, after S3 merges.
- The fixture connector's own tests execute that code, so the guide's examples run in CI.
- The guide's fenced Python must pass `ruff format --check`.

### 3.5 `src/hippo/connectors/loader.py` (S4c, M2, R50)

```python
ENTRY_POINT_GROUP: Final = "hippo.connectors"
ALLOWLIST_ENV: Final = "HIPPO_CONNECTOR_ALLOWLIST"
IN_REPO_PACKAGES: Final = ("hippo.connectors", "hippo.connectors.examples")


class ConnectorLoadError(ValueError): ...


@dataclass(frozen=True)
class ConnectorEntry:
    name: str
    origin: Literal["built-in", "in-repo", "entry point"]
    target: str | None  # "package.module:Connector"; None for a built-in connector kind
    trusted: bool
    enabled: bool = False
    registered: bool = False
    connector_class: type | None = None
    error: str | None = None  # an exception class name, "not allowlisted", "NameMismatch" or "DuplicateName"


@dataclass(frozen=True)
class LoadResult:
    registry: Registry
    entries: tuple[ConnectorEntry, ...]

    def connector_class(self, name: str) -> type: ...  # a registered entry's class, else ConnectorLoadError


def discover_connectors(*, allowlist: frozenset[str]) -> tuple[ConnectorEntry, ...]: ...
def load_registry(*, enabled_kinds: frozenset[str], allowlist: frozenset[str]) -> LoadResult: ...
def configured_allowlist(environ: Mapping[str, str] | None = None) -> frozenset[str]: ...
def enabled_connector_kinds(store) -> frozenset[str]: ...
def load_connectors(ctx) -> LoadResult: ...
```

**Discovery.** `discover_connectors(*, allowlist)` finds connectors and registers nothing. It works in
four steps:

1. **In-repo packages.** Each direct subdirectory of `hippo/connectors/` and `hippo/connectors/examples/`
   that holds `__init__.py` and `connector.py` is a candidate, read through `importlib.resources.files`
   and taken in name order.
   - The target is `hippo.connectors[.examples].<name>:Connector`.
   - In-repo packages are trusted.
   - `scaffold/` is never found, because its files are `.tmpl`. Nor is `tests/fakes/fixture_connector/`,
     which sits outside the package (R10).
2. **Entry points.** A module-level `_entry_points()` returns
   `importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)`, and tests replace it with stand-ins that
   carry `name`, `value` and `load()`. Entry points are taken in name order.
   - An entry point is trusted only if its name is in `allowlist`, which is empty by default (design §9).
   - An untrusted entry point is listed with `error="not allowlisted"` and is never imported. This is M2's
     second test.
3. **Import.** A trusted entry is imported: `importlib.import_module` plus `getattr(module, "Connector")`
   for an in-repo package, `entry_point.load()` for an entry point.
   - Any exception is caught. The entry gets `error=type(exc).__name__`, the traceback is logged at
     warning, and discovery continues. This is M2's first test.
   - A class whose `descriptor.name` differs from the discovered name gets `error="NameMismatch"`.
4. **Duplicates.** An entry point whose name equals an in-repo package's name gets
   `error="DuplicateName"`.

**Loading.** `load_registry(*, enabled_kinds, allowlist)` follows design §3's order: built-ins, in-repo
packages, then entry points.

1. `registry = current_registry()`. Its built-ins install on first use (S1 §5.2, "State").
   - A production process loads into `REGISTRY`. A `ContextVar` set inside the lifespan task would not
     reach request tasks, so the registry is changed where every thread reads it.
   - A test installs `Registry.with_builtins()` with `use_registry` first.
2. `discover_connectors(allowlist=allowlist)`: in-repo entries first, then entry points.
3. Each trusted, imported entry whose name is in `enabled_kinds` gets `enabled=True` and
   `registry.register(cls.descriptor.extension, declared_families=cls.descriptor.families)` (R46, S1 D5).
   - A `RegistrationError`, or any other exception, sets `error` to its class name and registers nothing,
     because S1's `register` swaps state only when every check passes. Loading continues.
   - A successful registration sets `registered=True`.
4. Built-in connector kinds (`Registry.with_builtins().connector_kinds()`) with no discovered package are
   listed with `origin="built-in"`, `target=None`, `trusted=True`, `registered=True`, and `enabled` taken
   from `enabled_kinds`.
5. `registry.freeze()`, which is idempotent.

A registry that is already frozen on entry registers nothing. An enabled entry is `registered` only if
every definition in its extension is already present and equal:

- `registry.object_kind(name) == definition`;
- likewise for predicates and locator kinds;
- membership for artifact kinds and connector kinds.

This is the restart rule of R50. The loaded registry is frozen, so enabling a kind takes effect when the
process next starts. It also makes a second lifespan in one process harmless.

**Inputs.**

- **`enabled_connector_kinds(store)`** is
  `frozenset(row.kind for row in store._knowledge_rows("Connector") if row.enabled)`. A kind is enabled
  when an operator has enabled an instance of it, which is what design §9 names Task 15's
  `POST /api/connectors` for. R51 gates each instance again at sync entry.
- **`configured_allowlist(environ=None)`** splits `HIPPO_CONNECTOR_ALLOWLIST` on commas, strips blanks,
  and returns an empty set when the variable is unset (design §9: "the configuration carries an
  allowlist … empty by default").
- **`load_connectors(ctx)`** is
  `load_registry(enabled_kinds=enabled_connector_kinds(ctx.store), allowlist=configured_allowlist())`.
  When reading the rows raises, it logs a warning and loads with `enabled_kinds=frozenset()`. It never
  raises, like `startup` (`web/app.py:163`).

**Wiring (R50).**

- **The `web/app.py` lifespan** (`:63-68`) becomes the block below. The import is function-local, so the
  grant stays inside the lifespan's lines. `app.state.connector_load` is what S6's `GET /api/connectors`
  lists (origin, enabled, error) without importing packages a second time.

  ```python
  @asynccontextmanager
  async def lifespan(app: FastAPI):
      from ..connectors.loader import load_connectors

      app.state.connector_load = load_connectors(ctx)
      startup(ctx)
      yield
      ctx.close()
  ```

- **`cli.cmd_connector`** (S4b) calls `load_connectors(ctx)` for `list` and for a non-dry-run `sync`. It
  calls `discover_connectors(allowlist=configured_allowlist())` for `probe`, `sync --dry-run` and
  `validate <name>`. R50 grants these call lines to S4c, but `cmd_connector` does not exist until S4b,
  which merges after S4c. S4b therefore writes them against S4c's merged API (open question 1).
- **S5's `default_registry()`** (S5 §12 R-S1-2) is `load_connectors(ctx).registry`. **S6's R-S1-3**
  ("discovered but not registered until enabled") is `discover_connectors` plus the enablement rule.
- **Readers need no loader.** R39 makes every read accept any code, so `hippo ask`, `hippo mcp` and
  startup recovery read rows of unloaded extensions (M1).

**The process registry in tests.** `load_registry` freezes `REGISTRY` in `hippo serve` and in each
`hippo connector` process. A pytest process that runs an app lifespan freezes it too. A test that
registers into the process registry must therefore do so under one of two forms:

- `extension_scope()`, which clears and restores the frozen flag (S1 §5.2, R16);
- `use_registry(Registry.with_builtins())`.

S4c's own tests use the second form. Its regression run (§6) puts the web and registry suites in one
process to prove that test order does not matter.

**M2's three tests** are
`test_loader_lists_a_failing_entry_point_and_continues[import_error|registration_refused]`,
`test_loader_skips_an_entry_point_missing_from_the_allowlist` and
`test_serve_startup_installs_a_frozen_registry`. The third runs under
`use_registry(Registry.with_builtins())` in three steps:

1. It imports `hippo.web.app` inside the test and builds `create_app(ctx)`.
2. It runs `asyncio.run(...)` over `app.router.lifespan_context(app)`.
3. Inside the lifespan, it asserts that `current_registry().frozen` holds and that
   `app.state.connector_load` lists the enabled stand-in as registered.

It never imports a test client, so it needs no anyio filter.

## 4. File-by-file steps

### S4c (worktree `s4c`, after S1a and S2a merge; may run beside S1b, S2b and S3)

1. **Create** `tests/unit/test_connector_loader.py` with the §5 S4c tests. Run it, save
   `/tmp/hippo-cdk-s4c-red.log`, and confirm that every test fails on the missing module.
2. **Create** `src/hippo/connectors/loader.py` (§3.5).
3. **Modify** `src/hippo/web/app.py:63-68`, the lifespan only (the R50 grant), as §3.5 shows.
4. **Modify** `tests/unit/test_import_order.py:14-28`: append `"hippo.connectors.loader"` to `MODULES`.
5. Run GREEN and the regression run (§6), and save `/tmp/hippo-cdk-s4c-green.log` and
   `/tmp/hippo-cdk-s4c-regress.log`. Run Ruff, then commit
   `Add the connector registry loader and install it at serve startup (CDK S4c)`.

### S4a (worktree `s4a`, after S3c merges)

1. **Create** `tests/unit/test_connector_testing_kit.py` with the §5 S4a tests.
   - Before any source edit, on the base tree, compute
     `hashlib.sha256(fake_ollama.embed_text("ACME builds Robot.").tobytes()).hexdigest()` and pin it in
     `test_the_fake_ollama_embeds_with_the_kit_algorithm`.
   - Run the file, save `/tmp/hippo-cdk-s4a-red.log`, and confirm that the kit tests fail on the
     missing module.
2. **Create** `src/hippo/connectors/testing.py` in this order:
   1. the constants, the re-exports, `ContractViolation` and the dataclasses;
   2. `load_case`, `discover_cases` and `_replay_connector`;
   3. the twelve contract assertion functions, `check_contract` and `assert_contract`;
   4. `assert_emit_pure` and `check_capture`;
   5. `hashed_embedding` and `offline_ollama`;
   6. `scratch_store`, `scratch_workspace`, `_kit_registry`, `prepare_instance`, `scratch_sync`,
      `run_case` and `dry_run_sync`;
   7. `assert_runtime_resilience`;
   8. `extension_lock`, `assert_registry_lock` and `error_transport`;
   9. `load_connector_package` and `validate_package`.
3. **Modify** `tests/fakes/fake_ollama.py:146-160`. The body of `embed_text` becomes a function-local
   `from hippo.connectors.testing import hashed_embedding` and `return hashed_embedding(text)`. `DIM`
   and every other line stay unchanged. This re-plan grants the edit to S4a (m17).
4. **Modify** `tests/unit/test_import_order.py:14-28`: append `"hippo.connectors.testing"` after S4c's
   line. R9's merge-order rule serializes the two appends.
5. **Measure** `validate_package` on S3's fixture connector with the default `scratch_store`: LadybugDB
   with its buffer pool bounded to `256 * 2**20` bytes, the value at `tests/conftest.py:229`. Record the
   wall time and peak RSS in the evidence, as R7 requires.
6. Run GREEN (Fake, LadybugDB and the fake-Ollama regression, §6) and save the logs. Run Ruff, then
   commit `Add the connector test kit: contract, purity, capture, runtime and registry assertions (CDK S4a)`.

**Fallback split**, if the budget runs out:

- **S4a-1** is steps 2.1–2.5 and 2.8–2.9 with `validate_package(runtime=False)` only, plus steps 3 and 4.
- **S4a-2** is steps 2.6–2.7, the `runtime=True` branch, and step 5.

S4b waits for S4a-2, because `render_package` needs the full `validate_package`.

### S4b (worktree `s4b`, after S4a and S4c merge)

1. **Create** `tests/unit/test_connector_scaffold.py` and `tests/unit/test_cli_connector.py` with the §5
   S4b tests. Save the RED log to `/tmp/hippo-cdk-s4b-red.log`.
2. **Create** `src/hippo/connectors/scaffold/__init__.py` and
   `src/hippo/connectors/scaffold/templates/*.tmpl` (§3.2).
3. **Modify** `src/hippo/cli.py`:
   1. At `:132-148`, add the `connector` subparser group.
   2. At `:155-169`, add `"connector": cmd_connector` to the handler table.
   3. Add `cmd_connector` and its five private helpers beside `cmd_user`, per §3.3. The imports of
      `hippo.connectors.{loader,testing,sync}`, `hippo.knowledge.registry`,
      `hippo.knowledge.build_authority`, `hippo.knowledge.raw_artifacts` and
      `hippo.ingest.managed_activation` are function-local.
   4. `connector` is not an `EVIDENCE_COMMANDS` member (`cli.py:62`). Its store reads are administration,
      gated by `_require(principal, "manage_sources")`.
4. **Modify** `src/hippo/remote.py`: add `connectors()` at `:159-160`.
5. **Create** `docs/spec/cdk-guide.md` (§3.4; granted by R9).
6. **Modify** S3's fixture connector module (R-S3-7): add the `cdk-guide` marker comments, comments only.
7. Run GREEN and save `/tmp/hippo-cdk-s4b-green.log`. Run Ruff on every changed `.py` and on the guide,
   then commit `Add the connector scaffold, the hippo connector commands and the developer guide (CDK S4b)`.

## 5. RED tests

### `tests/unit/test_connector_loader.py` (S4c)

- `test_loader_lists_a_failing_entry_point_and_continues[import_error|registration_refused]` (M2)
- `test_loader_skips_an_entry_point_missing_from_the_allowlist` (M2)
- `test_serve_startup_installs_a_frozen_registry` (M2)
- `test_loader_registers_enabled_in_repo_packages_before_allowlisted_entry_points_then_freezes`
- `test_a_discovered_kind_that_is_not_enabled_is_listed_and_not_registered`
- `test_loading_a_frozen_registry_registers_nothing_until_restart`
- `test_enabled_kinds_come_from_enabled_instances_and_the_allowlist_from_the_environment`
- `test_load_connectors_never_raises_when_connector_rows_cannot_be_read`

### `tests/unit/test_connector_testing_kit.py` (S4a)

- `test_every_assertion_has_exactly_one_negative_fixture`
- `test_a_negative_fixture_fires_its_own_assertion[<each name in ASSERTIONS>]`
- `test_a_negative_fixture_fires_no_other_assertion_of_its_group[<each contract and capture assertion>]`
- `test_the_fixture_connector_passes_every_assertion`
- `test_assert_contract_raises_the_first_violation_in_assertion_order`
- `test_token_bound_is_the_passage_character_bound` (m6)
- `test_the_purity_guard_is_the_runtime_guard` (B3)
- `test_assert_emit_pure_leaves_other_threads_alone`: another thread calls `time.monotonic` and
  `httpx.Client.send` over a `MockTransport` throughout (B3)
- `test_check_capture_bounds_its_reads_by_sample` (M12)
- `test_check_capture_accepts_a_sync_connector_without_emit` (M12, R1)
- `test_load_case_reads_the_documented_layout`
- `test_load_case_refuses_a_bad_case_name_an_unknown_file_a_missing_upsert_input_an_unquoted_name_and_two_partitions`
- `test_a_missing_policy_replays_as_unknown`
- `test_the_replay_raises_provider_not_found_for_an_id_without_input` (M15)
- `test_the_replay_connector_keeps_the_real_probe_and_emit_and_replays_the_sync_half` (B4)
- `test_run_case_creates_an_enabled_instance_stores_the_probe_and_calls_sync_connector_with_its_full_signature`:
  a spy on `sync.sync_connector` checks `connector_id`, a trusted-local `actor`, `registry is
  current_registry()`, `options.emit_workers == 1` and `operation_id == "validate.basic"` (B4, M5)
- `test_run_case_pins_the_store_clock_to_the_fixed_instant`
- `test_run_case_records_a_sync_refusal_as_the_case_error` (B4)
- `test_run_case_diffs_published_records_against_the_goldens`
- `test_update_golden_rewrites_the_seven_files_and_returns_the_diff`
- `test_goldens_are_canonical_json_sorted_by_id_without_job_or_event_payload`
- `test_the_kit_re_exports_the_runtime_transports` (B4)
- `test_each_error_class_has_a_replayable_response[authentication|forbidden|not_found|throttled|transient|malformed]`
- `test_runtime_resilience_holds_for_the_fixture_connector[<each name in RUNTIME_SCENARIOS>]` (B4)
- `test_the_registry_lock_accepts_a_bumped_template_version`
- `test_the_offline_model_embeds_deterministically_and_refuses_chat`
- `test_the_fake_ollama_embeds_with_the_kit_algorithm` (m17)
- `test_validate_package_reports_the_registry_diff`
- `test_validate_package_contract_scope_runs_no_sync`
- `test_validate_package_of_a_coordinator_lane_connector_runs_capture_only` (R1)
- `test_dry_run_sync_publishes_into_a_scratch_workspace_only` (B4)

A module fixture points `testing.scratch_store` at the backend `HIPPO_TEST_STORE` names: `FakeStore()` for
`fake`, and `LadybugStore(path, buffer_pool_bytes=LADYBUG_TEST_BUFFER_POOL_BYTES)` for `ladybug`.

### `tests/unit/test_connector_scaffold.py` (S4b)

- `test_new_writes_the_documented_package_files`
- `test_a_new_package_passes_validate`
- `test_a_new_packages_own_test_passes`
- `test_new_refuses_an_invalid_name_an_unknown_family_a_registered_kind_and_an_existing_directory`
- `test_the_scaffold_templates_ship_as_package_data`
- `test_the_scaffold_emits_node_refs_without_an_instance_key_part` (M16)
- `test_scaffold_output_for_a_fixed_request_is_pinned` (regenerated from the M16 templates)
- `test_a_scaffolded_package_is_ruff_clean`
- `test_the_guide_exists_and_every_python_example_is_the_fixture_connector`
- `test_the_guide_documents_every_assertion`

### `tests/unit/test_cli_connector.py` (S4b)

- `test_connector_arguments_parse[new|new_with_kinds_and_dest|list|validate|validate_update_golden|probe|sync_dry_run|sync_instance]`
- `test_the_connector_group_requires_a_subcommand`
- `test_connector_help_imports_no_serving_machinery`
- `test_list_shows_built_in_in_repo_and_entry_point_connectors`
- `test_list_shows_an_entry_point_that_fails_to_import_with_its_error`
- `test_list_requires_manage_sources_when_users_exist`
- `test_list_forwards_to_the_running_server_when_the_store_is_locked`
- `test_remote_connectors_maps_a_401_and_a_coded_refusal`
- `test_validate_passes_the_fixture_connector`
- `test_validate_prints_each_violation_and_exits_1`
- `test_validate_update_golden_prints_the_diff_and_exits_0`
- `test_probe_prints_family_and_mapping_per_partition`
- `test_probe_with_an_invalid_config_exits_2`
- `test_probe_of_an_unregistered_kind_prints_the_type_extension_and_exits_1`
- `test_probe_and_sync_dry_run_refuse_an_entry_point_missing_from_the_allowlist`
- `test_sync_dry_run_prints_coverage_and_writes_nothing_to_the_configured_store`
- `test_sync_refuses_with_exit_2_when_the_store_is_locked`
- `test_sync_requires_manage_sources_when_users_exist`
- `test_sync_checks_manage_sources_then_runs_as_the_trusted_local_actor` (m19)
- `test_sync_without_a_stored_classification_exits_2` (m19)
- `test_sync_of_a_disabled_instance_exits_2` (M5)
- `test_sync_of_a_kind_that_is_not_enabled_exits_2` (M5)

No new test module imports `fastapi.testclient` or `starlette.testclient`. Forwarding is proven against
`httpx.MockTransport`, and serve startup through `app.router.lifespan_context`. The CLI tests make the
fixture connector discoverable by replacing `loader._entry_points` with a stand-in named `fixture` whose
target is `tests.fakes.fixture_connector:FixtureConnector`, and they set `HIPPO_CONNECTOR_ALLOWLIST=fixture`
with `monkeypatch.setenv`.

## 6. GREEN commands and the CK4 CHECK line

```bash
# S4c
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_loader.py tests/unit/test_import_order.py -q -o addopts='' -W error > /tmp/hippo-cdk-s4c-green.log 2>&1; echo EXIT $?
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_loader.py tests/unit/test_web_base.py tests/unit/test_managed_web_surfaces.py tests/unit/test_registry.py tests/unit/test_registry_model.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning" > /tmp/hippo-cdk-s4c-regress.log 2>&1; echo EXIT $?
# S4a
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_testing_kit.py tests/unit/test_import_order.py -q -o addopts='' -W error > /tmp/hippo-cdk-s4a-green.log 2>&1; echo EXIT $?
HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_connector_testing_kit.py -q -o addopts='' -W error > /tmp/hippo-cdk-s4a-ladybug.log 2>&1; echo EXIT $?
HIPPO_TEST_STORE=fake .venv/bin/pytest $(grep -l 'embed_text\|FakeOllama\|fake_ollama' tests/unit/*.py) -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning" > /tmp/hippo-cdk-s4a-fake-ollama.log 2>&1; echo EXIT $?
# S4b
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_scaffold.py tests/unit/test_cli_connector.py tests/unit/test_cli.py tests/unit/test_import_order.py -q -o addopts='' -W error > /tmp/hippo-cdk-s4b-green.log 2>&1; echo EXIT $?
# Ruff, each worker on its own files
.venv/bin/ruff check src/hippo/connectors/loader.py src/hippo/connectors/testing.py src/hippo/connectors/scaffold src/hippo/cli.py src/hippo/remote.py src/hippo/web/app.py tests/fakes/fake_ollama.py tests/unit/test_connector_*.py && .venv/bin/ruff format --check src/hippo/connectors/loader.py src/hippo/connectors/testing.py src/hippo/connectors/scaffold src/hippo/cli.py src/hippo/remote.py src/hippo/web/app.py tests/fakes/fake_ollama.py tests/unit/test_connector_*.py docs/spec/cdk-guide.md
```

**Warning filters.** The two regression lines use form (b) of the fleet rules, because web test modules
import `fastapi.testclient` at module level. A worker who finds that no listed file does so drops the
filter and records that. `tests/unit/test_cli.py` must pass unchanged, with its existing per-test
markers.

**CK4 CHECK line: a replacement is proposed** (for the orchestrator to apply). The ledger line names three
files, and S4c adds a fourth:

```text
CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_testing_kit.py tests/unit/test_connector_scaffold.py tests/unit/test_cli_connector.py tests/unit/test_connector_loader.py -q -o addopts='' -W error
```

No form (b) filter is needed. None of the four files imports a test client at module level, and the
loader's startup test runs the lifespan without a client. The S4a LadybugDB line is evidence for the
ledger, not a new gate line. CK7's Ruff lines already cover `src/hippo/connectors` and
`tests/unit/test_connector_*.py`.

**Ledger lines.** CK4's CRITERIA already carry S4c, `check_capture`, `probe_deterministic` and the one
guard (`a9cbfcb`). One wording proposal stands from the first plan: replace "`remote.py` forwards the
commands" with "`remote.py` forwards `hippo connector list` to `GET /api/connectors`; `new`, `validate`,
`probe` and `sync --dry-run` run locally by design, and a non-dry-run `sync` refuses while the server holds
the store (deviation 4)".

## 7. Worktrees, merge order, do-not-touch

- **Worktrees:** `s4c`, `s4a` and `s4b` (branches `wp/s4c`, `wp/s4a`, `wp/s4b`). Each is created per
  `ai_docs/handoffs/fleet-worker-rules.md` from the HEAD the orchestrator names after its prerequisites
  merge.
- **Merge order** (R38, extended by R50):
  - S1a → S2a → **S4c**; S4c may run beside S1b, S2b and S3;
  - S3c → **S4a**;
  - S4a + S4c → **S4b**;
  - S5a after S4c, because its `default_registry()` calls the loader;
  - S5b after S4a (R1) and S4c;
  - S6 after S4b and S5b.

  S4c precedes every caller of `load_registry`.
- **S4c owns:** `src/hippo/connectors/loader.py`, `tests/unit/test_connector_loader.py`, the lifespan lines
  `src/hippo/web/app.py:63-68` (R50), and one appended line in `tests/unit/test_import_order.py`.
  `web/app.py` passes to S6 after S4c merges, a sequential handoff.
- **S4a owns:** `src/hippo/connectors/testing.py`, `tests/unit/test_connector_testing_kit.py`, the body of
  `embed_text` in `tests/fakes/fake_ollama.py` (m17, granted here), and one appended line in
  `tests/unit/test_import_order.py`.
- **S4b owns:** `src/hippo/connectors/scaffold/**`, `src/hippo/cli.py`, `src/hippo/remote.py`,
  `docs/spec/cdk-guide.md` (R9), `tests/unit/test_connector_scaffold.py`,
  `tests/unit/test_cli_connector.py`, and marker comments in S3's fixture connector.
- **Do not touch:**
  - `src/hippo/knowledge/**`, `src/hippo/store/**`, `src/hippo/ingest/**`, `src/hippo/config.py`;
  - S2's `connectors/{__init__,base,classify,keys,render,emit}.py`;
  - S3's `connectors/{guard,http,credentials,sync}.py`, `knowledge/staged_records.py` and
    `tests/fakes/fixture_connector/**`, apart from S4b's marker comments;
  - `src/hippo/web/**`, apart from S4c's lifespan lines, and `src/hippo/mcp_server.py`;
  - `tests/fakes/**`, apart from S4a's `embed_text` body and S4b's markers;
  - `docs/spec/connector-developer-kit.md`, `docs/rag_it_all*.md`, every gate ledger and the checkpoint
    file.

## 8. Decisions taken

1. **`testing.py`** (S4a).
   - *Layout:* §3.1, loaded strictly so that a typo fails. `fetches` is optional. Case names are bounded
     so operation ids match `OPERATION_ID`.
   - *Replay:* a per-call subclass of the connector's class that overrides `list_changes`, `fetch` and
     `fetch_policy` and keeps the real `probe` and `emit`. An id without input raises
     `ProviderNotFoundError`.
   - *Scratch runs:* one temporary workspace per run, holding only the built-ins and the connector's own
     extension under `use_registry`. The instance is created with an explicit `enabled=True`. Calls go
     through S3's full `sync_connector` signature, with one emit worker and the trusted local actor. The
     store clock is pinned for goldens and scenarios.
   - *`run_case`:* `on_batch` only records, and the checks run after the sync returns. Sync refusals
     become the case's `error`. Records are read back by generation id.
   - *Contract assertions:* twelve names. Each overlapping check calls S2's function. Edges go through
     `emit.evidence_class`, and the token bound is `base.PASSAGE_CHAR_BOUND`.
   - *Purity:* S3's per-thread `forbid_effects`, on the calling thread, twice per revision.
   - *Capture:* five rules over any `SyncConnector`. No store and no HTTP of its own, bounded by `sample`,
     with `probe` run unguarded under two clock instants.
   - *Runtime:* five scenarios with S3's labels on replay variants. The checks do not depend on a reader.
     The negatives are `scratch_sync` doubles.
   - *Recording:* S3's transports, re-exported. The kit keeps `error_transport`.
   - *Offline model:* owns the hashed-vector algorithm, and the fake imports it.
   - *Goldens:* seven canonical JSON files, and `--update-golden` prints the diff.
2. **Scaffold** (S4b). `string.Template` files, shipped as package data. The generated connector emits
   key parts without the instance (M16), carries `extension` (R46), registers its connector kind, and
   samples in `probe` through its own methods. The generated package computes its goldens and lock at
   creation, and a test pins the output for a fixed request.
3. **Commands** (S4b). Five subcommands in the `user` group's shape, with function-local imports.
   - Only `list` forwards.
   - `new`, `validate`, `probe` and `sync --dry-run` never open the configured store, and they need a
     trusted connector, not an enabled one.
   - The non-dry-run `sync` checks `manage_sources`, loads the registry, requires an enabled kind and a
     stored classification, and syncs as the trusted local actor.
4. **Guide** (S4b). Twelve sections. Every Python example equals a marked region of S3's fixture
   connector, enforced by a test.
5. **The kit's scratch store is a temporary LadybugDB** (R7). Tests substitute the Fake through
   `testing.scratch_store`.
6. **The kit ships its own offline model.** `validate` and `sync --dry-run` must not require a running
   Ollama, and the managed build asks the model for tags, capabilities and embeddings.
7. **The registry lock** versions kinds and predicates by the descriptor's version, and templates by
   `FactTemplate.version`. The descriptor version therefore covers R20's `label_template` and
   `verb_phrase`.
8. **Sizing.** Three workers: S4c, then S4a (with a named fallback split), then S4b.
9. **Loader** (S4c).
   - It loads into `current_registry()`: built-ins, then enabled in-repo packages, then allowlisted and
     enabled entry points, then `freeze()`.
   - A kind is enabled when an enabled `Connector` instance of it exists. The allowlist is
     `HIPPO_CONNECTOR_ALLOWLIST`.
   - Import and registration failures are listed by class name and never stop loading. An
     already-frozen registry registers nothing (restart rule).
   - `load_connectors` never raises. The lifespan stores the result on `app.state.connector_load`.

## 9. Requires from S1, S2 and S3, and provides to S5 and S6

Each item copies the signature from the cited plan section, amended by the cited ruling where the plan
text is not yet updated. When the implemented slice spells a name differently, that slice wins, and the
S4 worker changes the one call site named.

**R-S1-1: the registry** (S1 §5.2). Call sites: `loader.load_registry`, `testing._kit_registry`,
`run_case`, `validate_package`, `extension_lock`.

```python
class RegistrationError(ValueError): ...


class Registry:
    def register(
        self, extension: TypeExtension, *, declared_families: Iterable[str] | None = None
    ) -> None: ...
    def freeze(self) -> None: ...
    def fingerprint(self) -> str: ...
    def object_kind(self, name: str) -> ObjectKindDefinition: ...
    def predicate(self, name: str) -> PredicateDefinition: ...
    def locator(self, kind: str) -> type[LocatorBase]: ...
    def artifact_kind(self, name: str) -> str: ...
    def connector_kind(self, name: str) -> str: ...
    def evidence_source(self, name: str) -> str: ...
    @property
    def frozen(self) -> bool: ...
    def connector_kinds(self) -> frozenset[str]: ...
    @classmethod
    def with_builtins(cls) -> Registry: ...


def current_registry() -> Registry: ...


@contextmanager
def use_registry(registry: Registry) -> Iterator[Registry]: ...


@contextmanager
def extension_scope() -> Iterator[Registry]: ...
```

**R-S1-2: the definitions** (S1 §5.2). `FactTemplate(name, version, consumes, text)`,
`ObjectKindDefinition` (`name`, `family`, `key_template`, `key_prefix`, `attrs_model`, `label_template`,
`fact_templates`, `scope_kind`), `PredicateDefinition` and `TypeExtension` (`families`, `object_kinds`,
`artifact_kinds`, `locator_kinds`, `connector_kinds`, `evidence_sources`, `predicates`), as listed there.
R40 changes only how an extension evidence source is spelled. Call sites: `extension_lock`, the scaffold
templates, the loader's frozen-registry comparison.

**R-S2-1: the contract module** (S2 §4.1, with R24, R46, R48 and R53). Every §4.1 record is importable
from `hippo.connectors.base`. The kit relies on these:

```python
PASSAGE_CHAR_BOUND = 1500  # R24: 6000; R42: S4 reads the constant, never the number


def token_count(text: str) -> int: ...


class ContractError(ValueError): ...


class RegistrationRequired(ContractError): ...


class ConnectorDescriptor(Contract):  # R46 adds `extension: TypeExtension`
    name: Code
    version: Text
    families: tuple[Family, ...]
    kinds: tuple[Code, ...]
    predicates: tuple[Code, ...]
    artifact_kinds: tuple[Code, ...]
    locator_kinds: tuple[Code, ...]
    capabilities: ConnectorCapabilities
    config_model: type[BaseModel]
    credentials: tuple[CredentialRequirement, ...]
    parsers: tuple[ParserVersion, ...]


class RevisionInput(Contract):  # R48 adds `span_policy_id: str`
    partition: Code
    artifact: k.Artifact
    revision: k.ArtifactRevision
    data: bytes
    config: BaseModel
    mapping: TypeMapping
    registry: Registry


class NodeRef(Contract):  # R53 adds `instance: Text = None` for identity-only foreign endpoints
    kind: Code
    key: dict[Code, KeyValue]


@runtime_checkable
class SyncConnector(Protocol):
    descriptor: ConnectorDescriptor

    def probe(self, config: BaseModel, clock: Clock) -> Classification: ...
    def list_changes(self, config: BaseModel, cursor: SyncCursor | None) -> ChangePage: ...
    def fetch(self, config: BaseModel, ref: ExternalRef) -> RawFetch: ...
    def fetch_policy(self, config: BaseModel, ref: ExternalRef) -> PolicyObservation: ...


@runtime_checkable
class Connector(SyncConnector, Protocol):
    def emit(self, revision: RevisionInput, mapping: TypeMapping) -> EmissionBatch: ...
```

The kit also uses these records with their §4.1 fields: `ConnectorCapabilities` (`inventory`,
`derivation`), `ExternalRef`, `SyncCursor`, `Change`, `ChangePage`, `RawFetch`, `PolicyObservation`,
`KindMapping`, `TypeMapping`, `PartitionClassification`, `Classification`, `SpanRef`, the five emission
records, `ParseFailure`, `EmissionBatch`, `Family` and `Clock`. S2 §4.6 supplies the validator messages
that `check_capture` quotes.

**R-S2-2: keys** (S2 §4.2). Call site: `assert_identities_from_builders`.

```python
def check_key_parts(definition: ObjectKindDefinition, ref: NodeRef) -> None: ...


def canonical_key(registry: Registry, ref: NodeRef, *, instance: str) -> CanonicalKey: ...
```

**R-S2-3: render** (S2 §4.4). Call site: `assert_one_fact_per_unit`.

```python
def render_label(definition: ObjectKindDefinition, attrs: BaseModel) -> str: ...


def render_facts(
    definition: ObjectKindDefinition, attrs: BaseModel, *, label: str, key: CanonicalKey
) -> tuple[RenderedText, ...]: ...


def unit_text(text: str, *, prefix: str = "", template: str | None = None) -> RenderedText: ...
```

**R-S2-4 to R-S2-7 (`verify_span`, `check_direction_and_ownership`, `policy_record`,
`capture_records`), and R-S2-9 (`evidence_class`, new for m18): emit** (S2 §4.5, with R44 on
`policy_record`). Call sites:
`assert_spans_match_bytes`, `assert_one_fact_per_unit`, `assert_unknown_policy_is_deny`,
`assert_direction_and_ownership`, `assert_edges_fully_attributed` (m18), and `validate_package` step 5.

```python
def evidence_class(family: str, source: str, metadata_origin: str | None = None) -> str: ...


def verify_span(data: bytes, span: SpanRef, *, artifact: k.Artifact) -> str: ...


def check_direction_and_ownership(
    registry: Registry, descriptor: ConnectorDescriptor, predicate: str, subject_kind: str, object_kind: str
) -> PredicateDefinition: ...


def policy_record(
    policy: PolicyObservation,
    *,
    connector: k.Connector,
    workspace_id: str,
    observed_at: datetime,
    expires_at: datetime,
) -> k.AccessPolicy: ...


def capture_records(
    fetch: RawFetch,
    policy: PolicyObservation,
    *,
    connector: k.Connector,
    workspace_id: str,
    source_id: str,
    raw_uri: str,
    observed_at: datetime,
    policy_expires_at: datetime,
) -> CapturedRevision: ...
```

R40 may give `evidence_class` a registry argument for extension evidence sources. If so, the kit passes
`context.registry`.

**R-S2-8: re-exports** (S2 decision 40). `hippo.connectors.base` re-exports `TypeExtension`,
`ObjectKindDefinition`, `PredicateDefinition` and `FactTemplate`. Call sites: `types.py.tmpl`,
`templates.py.tmpl`.

**R-S2-10: registry access and the classifier for a connector's `probe`** (S2 §4.3; new, open question 4).
The scaffold's `probe` calls the classifier with the current registry:

```python
def classify(
    descriptor: ConnectorDescriptor,
    config: BaseModel,
    items: Iterable[SampledItem],
    registry: Registry,
    *,
    spec: ClassifierSpec,
    capabilities: ConnectorCapabilities,
    kinds: tuple[KindMapping, ...] = (),
    attributes: tuple[AttributeMapping, ...] = (),
) -> Classification: ...


def classifier_spec(
    *, declarations: tuple[PathDeclaration, ...] = (), sql_dialects: tuple[str, ...] = ()
) -> ClassifierSpec: ...
```

The request is that `hippo.connectors.base` also re-exports S1's `current_registry`. Without it, the
template imports `current_registry` from `hippo.knowledge.registry`, and the scaffold's import test adds
that one name.

**R-S3-1: the runtime entry** (S3 §4.7 + R49). Call sites: `testing.scratch_sync`, and `cli.cmd_connector`
for a non-dry-run `sync`.

```python
def sync_connector(
    ctx,
    connector: Connector,
    *,
    connector_id: str,  # R49
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

The kit also uses `SyncOptions` (`emit_workers`, `reconcile`, `max_fetch_bytes`), `SyncReceipt`
(`outcome`, `generation_id`, `coverage`), `ConnectorSyncRefused` and `ConnectorContractViolation`, as
S3 §4.7 lists them. It relies on the entry refusals of S3 §5: no stored classification, and R51's
disabled instance.

**R-S3-2: instances and classification** (S3 §4.7, with R51's default). Call sites:
`testing.prepare_instance`, `cli.cmd_connector`.

```python
def ensure_connector(
    store,
    *,
    workspace_id: str,
    kind: str,
    instance_url: str,
    config: BaseModel,
    credential_ref: str | None = None,
    enabled: bool = True,  # R51: False; the kit always passes True
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
```

**R-S3-3: failpoint labels and behaviours** (S3 §4.7 `FAULT_POINTS`, §9). The scenarios raise at
`after_fetch` and `after_checkpoint`. They rely on these behaviours:

- a replay is a no-op by identity (S3 §5.4 with R52);
- a failed page builds nothing (S3 §6.1, DV5);
- narrowing takes effect at the checkpoint (S3 §6.3);
- spans keep the first capture's policy (R48).

**R-S3-4: the guard** (S3 §4.1, §10.1, with R49's m20 additions). Call sites: `testing.purity_guard`,
`assert_emit_pure`. S3's emit workers run in `contextvars.copy_context()` (m20), so `run_case`'s
`use_registry` reaches them.

```python
class EmitSideEffect(RuntimeError): ...


@contextmanager
def forbid_effects() -> Iterator[None]: ...
```

**R-S3-5: HTTP** (S3 §4.3). Call sites: the re-exports, `_replay_connector`, `error_transport` tests.

```python
ERROR_CLASSES = ("authentication", "forbidden", "not_found", "throttled", "transient", "malformed")


class ProviderError(Exception):
    def __init__(self, *, url: str, status: int | None, attempts: int, retry_after: float | None = None): ...


def record_transport(case_dir: Path, inner: httpx.BaseTransport) -> httpx.BaseTransport: ...


def replay_transport(case_dir: Path) -> httpx.MockTransport: ...
```

It also uses `ProviderNotFoundError`, `ProviderTransientError` and `ProviderMalformedError`, the
`ProviderError` subclasses, and `ProviderClient(base_url, *, transport=...)`.

**R-S3-6: credentials** (S3 §4.2). Call sites: `check_capture`, `cli._connector_probe`.

```python
def resolve(
    ref: str, *, environ: Mapping[str, str] | None = None, max_bytes: int = 64_000
) -> ResolvedCredential: ...


def redact_url(url: str) -> str: ...
```

**R-S3-7: the fixture connector** (S3 §11, R10). It lives at `tests/fakes/fixture_connector/` with the
`fixtures/basic` case in §3.1's layout. The kit needs four things from it, for S3c's brief:

- `FixtureConnector()` constructs with no arguments;
- `fixtures/basic` has at least two `upsert` notes;
- `descriptor.capabilities.inventory` is true (already so in S3 §11);
- `probe` samples through `self.list_changes(config, None)` and `self.fetch(config, ref)`, so the
  replay is exact.

Call sites: the positive fixture, the guide marker test, the `validate` tests.

**Existing code** (anchors in §2):

- `embedding_spec(ollama) -> EmbeddingSpec` (`managed_activation.py:238`)
- `raw_root(ctx) -> Path` (`:228`)
- `new_operation_id() -> str` (`:163`)
- `RawArtifactStore(root, *, max_object_bytes)` (`raw_artifacts.py:85`)
- `BuildActor.trusted_local()` (`build_authority.py:60`)
- `query_session(ctx, access=None, *, settings=None, structural=True)` (`query_access.py:126`)
- `EVERYTHING` (`access.py:120`)
- `DEFAULT_WORKSPACE_ID` (`migrations.py:72`)

**Provides.**

- **To S5.** `testing.check_capture(connector, config, *, sample)` for `LocalConnector` and
  `GitConnector` (M12; S5a and S5b each add a passing test). `loader.load_connectors(ctx)` backs
  `default_registry()`. In-repo connector packages export `Connector` from their `__init__` to be
  discovered.
- **To S6.** `hippo connector new ... --dest`, `testing.validate_package(name, runtime=False,
  allowlist=...)`, `ValidationReport.to_json()`, `testing.offline_ollama()`, `testing.assert_emit_pure`,
  the `ConnectorSummary` JSON of §3.3, `app.state.connector_load` (§3.5), and
  `loader.discover_connectors` for R-S1-3. The review's route test
  `test_post_validate_does_not_disturb_a_concurrent_request` (B3) holds because the guard is per-thread.

## 10. Design deviations

1. **Design §8 says `run_case` runs "on the Fake store".** The Fake store is test code and does not ship,
   so the installed kit uses a temporary LadybugDB store. Tests, and the CK4 CHECK line, substitute the
   Fake. Ratified by R7.
2. **Design §8's `assert_contract(batch, registry)` gains a third argument, `context`.** Several rules need
   the injected clock, the revision bytes, the policy observation and the connector row, and a batch
   carries none of them. Ratified by R7.
3. **Design §9's `sync <instance> [--partition <p>] [--dry-run]` gains `--config <file>`**, because a dry
   run of a connector name has no stored config. `new` gains `--dest <dir>`. Ratified by R7.
4. **Design §9 says the CLI forwards "as the other commands do".** Ratified by R7:
   - Only `list` forwards.
   - `probe` keeps a caller's config file and credential references on the caller's machine.
   - `validate`, `new` and `sync --dry-run` use no configured store.
   - A non-dry-run `sync` refuses while `hippo serve` holds the store, because the server-side sync route
     is Task 15's `POST /api/connectors/{id}/sync`, which S6 does not create.
5. **Design §9's allowlist lives in "the configuration".** S4c reads it from `HIPPO_CONNECTOR_ALLOWLIST`
   inside `loader.py`, not through `Config`, because `config.py` is not granted (open question 2).

## 11. Open questions

1. **R50's `cli.cmd_connector` lines.** R50 grants S4c the lines where `cmd_connector` calls the loader,
   but `cmd_connector` is created by S4b, which must merge after S4c. This plan has S4b write those calls
   against S4c's merged API, and S4c exercises its grant only in the `web/app.py` lifespan. Confirm, or
   move the grant to S4b explicitly.
2. **Where the allowlist lives.** The environment variable parsed in `loader.py` keeps S4c inside its
   grant. The alternatives are a `Config` field, which needs a `config.py` grant, or a store setting that
   Task 15's `POST /api/connectors` writes. Recommendation: keep the variable for v1 and move it when
   Task 15 lands.
3. **Who creates and enables `Connector` rows in v1.** R5 leaves instance creation to Task 15, and no S4
   or S6 path writes rows (S6's probe route only stores a classification on an existing row). Until
   Task 15, `hippo serve` registers no extension kind, and a non-dry-run `sync` has a target only when a
   test or an operator script calls `ensure_connector`. Is that acceptable for v1?
4. **How a connector's `probe` reaches the registry** (R-S2-10). `probe(config, clock)` receives none, and
   S6's import allowlist admits neither `hippo.connectors.classify` nor `hippo.knowledge.registry`.
   Recommendation: S2a re-exports `current_registry` from `hippo.connectors.base`, and S6's list admits
   `hippo.connectors.classify`.
5. **A transport convention for connectors' own tests.** S3 gives `ProviderClient(transport=...)` but no
   rule for how a connector receives a transport. The kit does not need one, because the replay overrides
   the sync half. A connector's own `record_transport`/`replay_transport` tests do need one.
   Recommendation: a keyword-only `transport=None` on connector constructors, adopted by S3c's fixture
   connector and S6's exemplar. Non-blocking.
6. **R-S3-7 goes to S3c's brief.** Its four points (no-argument constructor, two upserts, inventory, and
   `probe` sampling through its own methods) are not in the S3 plan's text.

The first plan's questions 1–4 were resolved by R9 (guide grant), R10 (fixture location), R12
(`classification_json`) and R24/R42 (passage bound).

## Plan verification checklist

### Wiring manifest

| Interface | Implementation | Registration | Plan step |
| --- | --- | --- | --- |
| `hippo connector` group | `cli.cmd_connector` | `cli.py:155-169` handler table | S4b step 3 |
| `RemoteHippo.connectors` | `remote.py` | `GET /api/connectors`, implemented by S6 | S4b step 4 |
| Scaffold templates | `connectors/scaffold/templates/*.tmpl` | wheel package data under `src/hippo` | S4b step 2 |
| Kit module | `connectors/testing.py` | `test_import_order.MODULES` | S4a steps 2 and 4 |
| Offline embedding | `testing.hashed_embedding` | imported by `tests/fakes/fake_ollama.embed_text` | S4a step 3 |
| Registry loader | `connectors/loader.py` | `web/app.py` lifespan; `test_import_order.MODULES` | S4c steps 2–4 |
| Process registry | `load_registry` into `current_registry()` | `app.state.connector_load`; `cmd_connector` | S4c step 3, S4b step 3 |

### Regression hotspots

| # | Behavior | Old location | New location | Plan step | Verified |
| --- | --- | --- | --- | --- | --- |
| 1 | `hippo --help` stays light | `test_import_order.py:52-81` | unchanged | S4b | `test_connector_help_imports_no_serving_machinery`, plus the unchanged file |
| 2 | Existing CLI exit codes and forwarding | `cli.py:150-192`, `:597-612` | unchanged | S4b | `tests/unit/test_cli.py` unchanged in the S4b GREEN run |
| 3 | Fake Ollama vectors are byte-identical | `fake_ollama.py:146-160` | `testing.hashed_embedding` | S4a step 3 | pinned digest test; the fake-Ollama regression run |
| 4 | Serve startup never raises | `web/app.py:163-180` | lifespan plus `load_connectors` | S4c step 3 | `test_load_connectors_never_raises_when_connector_rows_cannot_be_read`; the web regression run |
| 5 | Test order independence of the process registry | S1 §5.2 `extension_scope` | the frozen `REGISTRY` after a lifespan | S4c step 5 | the regression run with the web and registry suites in one process |

### Contract matrix

| Endpoint | Old shape | New shape | Breaking? | Plan task |
| --- | --- | --- | --- | --- |
| `GET /api/connectors` (S6 implements) | none | `ConnectorSummary` list, §3.3 | no (new) | S4b defines, S6 builds |
| `hippo connector *` | none | §3.3 | no (new) | S4b |

### External dependencies (runtime)

| Dependency | Type | Endpoint/connection | Auth method | Integration test script | Verified? |
| --- | --- | --- | --- | --- | --- |
| Python entry points | `importlib.metadata` | group `hippo.connectors` | allowlist | `test_connector_loader.py` with stand-in entry points | planned |
| Ollama (offline stand-in) | `httpx.MockTransport` | `offline_ollama()` | none | `test_the_offline_model_embeds_deterministically_and_refuses_chat` | planned |

### Credential source inventory

| Credential | Runtime source | Path/key | Rotation? | Verified in new code |
| --- | --- | --- | --- | --- |
| none: the kit replays or reads through a connector; `probe` resolves references through S3's `credentials.resolve` | | | | |
