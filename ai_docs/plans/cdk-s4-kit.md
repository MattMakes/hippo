# CDK slice S4: the contract test kit, the scaffold and the `hippo connector` commands

**Status:** proposed implementation contract for root review. Nothing here is implemented. Written
at HEAD `f7b14ee`, which carries the design amendments of `d1b7bb2` and `f7b14ee`. Design of record:
`docs/spec/connector-developer-kit.md` (cited as "design"). Gate: CK4 of
`ai_docs/gates/rag-it-all/cdk/GATES.md`. Form follows
`ai_docs/plans/rag-it-all-task-5-managed-code-capture.md`.

## 1. Goal and scope

**Goal.** A developer who has never seen hippo can run `hippo connector new`, fill in the generated
package, and run `hippo connector validate`. The command either names the contract rule the
connector breaks or passes. Every rule in design §8 is proven to fire by a seeded violation.

**In scope.**

- `hippo.connectors.testing`: fixture layout, `run_case`, the named contract assertions, the purity
  guard, provider recording and replay, runtime and registry assertions, golden files.
- The scaffold templates behind `hippo connector new`.
- The `hippo connector new|list|validate|probe|sync` commands and their forwarding in `remote.py`.
- The developer guide `docs/spec/cdk-guide.md`.

**Out of scope.** The registry (S1), the contract records, keys, render and emit binder (S2), the
runtime, HTTP client and credentials (S3), the ported connectors (S5), the exemplar, the HTTP
routes and the MCP tool (S6). This plan programs against design §1 and §3 and lists what it needs
from S1, S2 and S3 in §9 instead of inventing it.

**Split (decision 12).** S4 is two workers, `s4a` then `s4b`. S4a is the kit alone:
`testing.py` holds about fourteen assertions, each with its negative fixture, plus the guard, the
replay and recording transports, `run_case` and the registry lock. That is the size of CC6 in the
code-capture work. S4b is the scaffold, five commands, the forwarding client and the guide, the size
of CC10. They share no file.

## 2. Existing seams

| Seam | Use or required boundary |
| --- | --- |
| `src/hippo/cli.py:90-147` `build_parser`; `:132-146` the `user` group | The one nested subcommand group today. `connector` copies its shape: `add_subparsers(dest="connector_command", required=True)`. |
| `cli.py:150-192` `main` | Handlers return ints. `StoreLockedError`, `RemoteError` and `Denied` print `error: ...` and return 2 (`:179-184`). A refusal mapped by `_refusal` returns 2 (`:185-192`). Commands return 1 for their own recoverable failures (`:625`, `:638`). |
| `cli.py:236-254` `_principal`, `:257-267` `_build_actor` | Identity for commands that touch the configured store. |
| `cli.py:597-612` `_context_or_running_server` | Forwarding is triggered only by `StoreLockedError`. There is no `--server` flag and no JSON output mode. |
| `tests/unit/test_import_order.py:52-81` `HELP_MUST_NOT_IMPORT` | `hippo --help` must not load `hippo.ingest.pipeline`, `managed_activation`, `public_errors`, `fastapi` or `starlette`. Every `hippo.connectors` import in `cli.py` is therefore function-local, as `cmd_index` does at `cli.py:313-314`. |
| `src/hippo/remote.py:78-129` `RemoteHippo`, `_json`; `:156-163` | One method per endpoint, `self._json(self._client.get(...))`. A 401 maps to `RemoteError` with the token sentence. A coded refusal maps to `code: message` (`:131-154`). |
| `tests/unit/test_cli.py:22-26` `cli_ctx`; `:278-301` `behind_server`; `:310` | Test patterns. `behind_server` imports `starlette.testclient` inside the function and needs the per-test marker (form (a) of the fleet rules). S4b's forwarding test uses `httpx.MockTransport` instead, so it needs no marker and no S6 route. |
| `tests/unit/test_prose_generation.py:32-79` `Runtime` | The model protocol a managed build calls: `/api/tags`, `/api/show`, `/api/embed`, `/api/chat`. The kit's offline model answers the first three. |
| `tests/fakes/fake_ollama.py:146` `embed_text` | Deterministic word and trigram hashed vectors. The offline model uses the same algorithm, re-implemented in `src/` because `tests/` does not ship. |
| `src/hippo/ollama.py:46` `Ollama`; `:126` `chat_text`, `:139` `chat_json`, `:192` `embed_explicit`, `:231` `embed`, `:256` `embed_one` | The client methods the purity guard refuses inside `emit`. |
| `tests/conftest.py:179-226` `store` | `HIPPO_TEST_STORE` selects fake, ladybug or neo4j. `tests/fakes/fake_store.py:66` `FakeStore` is test-only. |
| `src/hippo/store/memory.py:43` `MemoryQueries(Neo4jBase)` | The Neo4j query mixin, **not** an in-memory store. Outside tests, the only store that needs no server is a temporary LadybugDB file (`store/ladybug.py`). See deviation 1. |
| `src/hippo/store/generations.py:63-64` `_now` | `_generation_clock` is the store clock seam. `run_case` pins it. |
| `src/hippo/store/generations.py:966-1004` `generation_checksums`; `prose_generation.py:227,233` | `_knowledge_get` and `_knowledge_rows(kind, generation_id=...)` are the reads the coordinators already use to read one generation back. `run_case` reads the published records the same way. |
| `generations.py:1417-1418` `fault_hook(...)` | The existing failpoint convention. Runtime assertions inject S3's failpoints through it. |
| `src/hippo/access.py:41-48` `CAPABILITIES` | `manage_sources` gates commands that read connector instance state. |
| `pyproject.toml` `[project.scripts]`, `[tool.hatch.build.targets.wheel] packages = ["src/hippo"]` | Non-Python files under `src/hippo` ship in the wheel, so scaffold templates are package data. pytest's `norecursedirs` includes `fixtures`, so connector fixture trees are never collected. Ruff's `extend-exclude` covers `docs/plans`, not `docs/spec`, so the guide's fenced Python must be formatted. |
| `.github/workflows/ci.yml:27-28,45` | `ruff check .`, `ruff format --check .`, `pytest tests/unit`. |
| `ai_docs/handoffs/fleet-worker-rules.md:17` | Workers may not edit `docs/spec/*.md`. Design §13 gives S4 `docs/spec/cdk-guide.md`, so S4b's brief must grant that file explicitly (open question 1). |

## 3. Public API

### 3.1 `src/hippo/connectors/testing.py` (S4a)

```python
FIXED_INSTANT: Final = datetime(2026, 1, 1, tzinfo=UTC)
TOKEN_BOUND: Final = 1500
CASE_FILES: Final = ("config.json", "changes.json", "policies.json")
GOLDEN_FILES: Final = (
    "nodes.json",
    "edges.json",
    "passages.json",
    "units.json",
    "aliases.json",
    "failures.json",
    "coverage.json",
)
ASSERTIONS: Final[tuple[str, ...]] = (
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
    "emit_deterministic",
    "emit_pure",
    "runtime_resilience",
    "registry_version_bump",
)
RUNTIME_FAILPOINTS: Final = (
    "after_fetch_before_checkpoint",
    "replayed_page",
    "failed_inventory",
    "policy_change_mid_page",
    "delete_with_live_session",
)
ERROR_CLASSES: Final = ("authentication", "forbidden", "not_found", "throttled", "transient", "malformed")


class ContractViolation(AssertionError):
    def __init__(self, assertion: str, message: str, *, record: str | None = None) -> None: ...


class PurityViolation(ContractViolation): ...


@dataclass(frozen=True)
class AssertionContext:
    registry: Registry
    descriptor: ConnectorDescriptor
    revisions: Mapping[str, RevisionInput]
    clock_instant: datetime
    run_window: tuple[datetime, datetime]
    token_bound: int = TOKEN_BOUND


@dataclass(frozen=True)
class FixtureCase:
    name: str
    root: Path
    config: dict
    pages: tuple[ChangePage, ...]
    inputs: Mapping[str, bytes]
    policies: Mapping[str, PolicyObservation]


@dataclass(frozen=True)
class CaseResult:
    case: str
    generation_id: str
    records: Mapping[str, list]
    violations: tuple[ContractViolation, ...]
    diff: str

    @property
    def passed(self) -> bool: ...


@dataclass(frozen=True)
class ValidationReport:
    connector: str
    version: str
    scope: Literal["contract", "full"]
    registry_diff: tuple[str, ...]
    cases: tuple[CaseResult, ...]
    violations: tuple[ContractViolation, ...]

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
def assert_contract(batch: EmissionBatch, registry: Registry, context: AssertionContext) -> None: ...
def check_contract(batch: EmissionBatch, context: AssertionContext) -> tuple[ContractViolation, ...]: ...


@contextmanager
def purity_guard(*modules: ModuleType) -> Iterator[None]: ...
def assert_emit_pure(
    connector: Connector, revision: RevisionInput, mapping: TypeMapping
) -> EmissionBatch: ...


def load_case(case_dir: Path) -> FixtureCase: ...
def discover_cases(package_dir: Path) -> tuple[Path, ...]: ...
def scratch_store(path: Path): ...
def offline_ollama() -> Ollama: ...
def run_case(
    connector: Connector,
    case: FixtureCase | Path,
    *,
    extension: TypeExtension,
    update_golden: bool = False,
    fault_hook: Callable[[str], None] | None = None,
) -> CaseResult: ...
def assert_runtime_resilience(connector: Connector, case: Path, *, extension: TypeExtension) -> None: ...


def extension_lock(extension: TypeExtension, *, version: str) -> dict[str, str]: ...
def assert_registry_lock(extension: TypeExtension, *, version: str, lock_path: Path) -> None: ...


def record_transport(case_dir: Path, inner: httpx.BaseTransport) -> httpx.BaseTransport: ...
def replay_transport(case_dir: Path) -> httpx.MockTransport: ...
def error_transport(error_class: str) -> httpx.MockTransport: ...


def load_connector_package(target: str | Path) -> tuple[Connector, TypeExtension, Path]: ...
def validate_package(
    target: str | Path, *, update_golden: bool = False, runtime: bool = True
) -> ValidationReport: ...
```

**Fixture layout on disk** (decision 1a). Design §8's layout, made exact:

```text
<package>/fixtures/registry.lock.json          template and kind body hashes, keyed name@version
<package>/fixtures/<case>/config.json          instance config, validated by descriptor.config_model
<package>/fixtures/<case>/changes.json         {"pages": [ChangePage JSON, ...]}, replayed in order
<package>/fixtures/<case>/policies.json        {"<external id>": PolicyObservation JSON}
<package>/fixtures/<case>/inputs/<quoted id>   raw bytes; quoted = urllib.parse.quote(external_id, safe="")
<package>/fixtures/<case>/http/NNNN.json       optional provider recording, one exchange per file
<package>/fixtures/<case>/expected/*.json      the seven GOLDEN_FILES
```

`load_case` refuses an unknown top-level file, a missing `config.json` or `changes.json`, an
`inputs/` name that does not round-trip through `quote`, and a change whose external id has no input
file. A typo in a fixture is therefore an error, never a silently empty case. A missing
`policies.json` entry replays as `PolicyObservation` unknown, which the runtime stores as deny.

**Golden files** (decision 1g). Each golden file is canonical JSON (`knowledge.identity.canonical_json`),
a list sorted by the record `id`, with fields from the published knowledge records:

| File | One entry per | Fields |
| --- | --- | --- |
| `nodes.json` | `KnowledgeObject` in the generation | `id`, `kind`, `canonical_key`, `observations` (each `ObjectObservation` dump without `recorded_to`) |
| `edges.json` | `Assertion` whose version is a member | `id`, `subject_id`, `predicate`, `object_id`, `scope_key`, `versions`, `support` |
| `passages.json` | `Passage` native row | `id`, `title`, `text`, `span_id`, `retrieval_view_id`, `ordinal` |
| `units.json` | `Unit` | every field except vectors |
| `aliases.json` | `SAME_OBJECT_AS` assertion | as `edges.json` |
| `failures.json` | `ParseFailure` counted in `coverage_json` | `family`, `parser`, `count` |
| `coverage.json` | the generation | `json.loads(Generation.coverage_json)` |

`MaintenanceJob` rows and `IndexEvent.payload_json` are never written to a golden file. Both carry
the `uuid4` lease owner (`ingest/build_run.py:90`, `store/generations.py:1419-1427`).

`run_case(..., update_golden=True)` writes the seven files and returns the unified diff against the
previous files. `hippo connector validate --update-golden` prints that diff and exits 0. Without the
flag, a non-empty diff is a failed case and exit 1.

**`run_case`** (decision 1b) does the following, in order:

1. Build a scratch `AppContext` on a temporary data directory. Its store is `scratch_store(tmp)`,
   a temporary `LadybugStore`. Its model is `offline_ollama()`. Its store clock is pinned:
   `store._generation_clock = lambda: FIXED_INSTANT`.
2. Build a fresh registry with the built-ins, `register(extension)`, `freeze()`.
3. Wrap the connector in a private `_ReplayConnector`. It keeps the real `descriptor`, `probe` and
   `emit`. `list_changes` returns the case's pages in order, and the cursor is the page index.
   `fetch` returns `inputs/` bytes with the `RawFetch` metadata carried in `changes.json`.
   `fetch_policy` returns `policies.json` or unknown.
4. Call S3's sync entry (R-S3-1) for one partition with `BuildActor.trusted_local()`, the pinned clock
   and an `on_batch` observer. The observer only **records** each `(revision, mapping, batch)`.
   After the sync has returned, with no build, heartbeat or job thread alive, the kit runs
   `check_contract` on each recorded batch and `assert_emit_pure` on each recorded revision. The
   guard must never be held while `BuildRun`'s `LeaseHeartbeat` thread runs
   (`ingest/build_run.py:166`): its clock reads would raise inside that thread and fail the build
   for the wrong reason.
5. Read the published generation back with `_knowledge_rows(..., generation_id=...)` and build the
   seven golden lists.
6. Diff them against `expected/`.

Tests replace `scratch_store` with `tests.fakes.fake_store.FakeStore` through `monkeypatch`, which is
how the CK4 CHECK line runs on Fake.

**Contract assertions** (decision 1c). Each is a named function. It raises
`ContractViolation(assertion=<name without "assert_">, message, record=<emission id or key>)`.

| Assertion | Fires when | Reuses |
| --- | --- | --- |
| `registered_vocabulary` | a node kind, edge predicate, locator kind or edge source is not in the frozen registry | `Registry.object_kind`, `.predicate`, `.locator`, `.evidence_source` (design §3) |
| `nodes_have_locator_and_policy` | a node emission has no locator, or its revision has no policy observation | — |
| `unknown_policy_is_deny` | an `unknown` observation would be stored as anything but deny | S2's policy binder (R-S2-6) |
| `edges_fully_attributed` | an edge lacks family, source or statement; or a deterministic edge's source is not parser, metadata or rule | — |
| `aliases_name_a_rule` | an alias emission has no rule name | — |
| `no_ingestion_time` | any `ts`, `valid_from` or `valid_to` equals `clock_instant` or falls inside `run_window` | — |
| `one_fact_per_unit` | a rendered unit is not exactly one template output, or a slice unit is not one verified slice | S2's `render` (R-S2-3) |
| `spans_match_bytes` | a span's text hash differs from the hash of the revision bytes at its locator | S2's span verifier (R-S2-4) |
| `passages_within_token_bound` | a passage exceeds `TOKEN_BOUND` tokens | S2's token counter (R-S2-5) |
| `identities_from_builders` | an emission carries a literal id, or a key part list does not match its kind's `key_template` | S2's `keys` builders (R-S2-2) |
| `direction_and_ownership` | an edge's predicate lists none of the connector's families in `owner_families` and is not `identity=True`, or it points against `canonical_direction` | S2's direction check (R-S2-7); the message is S2's developer-facing text |
| `parse_failures_counted` | a revision with non-empty bytes yields no node, passage or unit and no `ParseFailure` | — |

Where S2's binder already refuses a condition, the kit calls S2's check function and adds nothing.
The kit asserts at emission time what S2 enforces at bind time. The two can never disagree because
they are one function.

**Purity guard** (decision 1d). `purity_guard(*modules)` holds a process-wide lock, so two guards
never overlap. While held, it patches:

- `socket.socket.connect`, `socket.create_connection` and `socket.getaddrinfo`;
- `httpx.Client.send` and `httpx.AsyncClient.send`;
- `hippo.ollama.Ollama.chat_text`, `chat_json`, `embed`, `embed_one` and `embed_explicit`;
- `subprocess.Popen.__init__`, which covers `run`, `call` and `check_output`, and `os.system`;
- `time.time`, `time.time_ns`, `time.monotonic` and `time.perf_counter`;
- in each module passed (the connector's own modules), a module-global `datetime` class, replaced
  with a subclass whose `now`, `utcnow` and `today` raise, and a module-global `date` class, whose
  `today` raises.

Each patched callable raises `PurityViolation("emit_pure", "<what> is not allowed inside emit")`.
Every patch is restored in `finally`, even after a violation. The kit runs `emit` in the calling
thread, never in a pool, and only when no build is in flight (`run_case` step 4), so the process-wide
patch is exact and no store thread can trip it. S3's runtime runs `emit` in its worker
pool under its own guard (R-S3-5). `assert_emit_pure` calls `emit` twice under the guard and compares
`canonical_json(batch.model_dump(mode="json"))`. A difference raises
`ContractViolation("emit_deterministic", ...)`.

**Provider recording** (decision 1e). `record_transport` wraps a real transport and writes
`http/NNNN.json` with these fields:

- `request`: `method`; `url`, passed through S3's `credentials.redact_url` (R-S3-4); the
  `accept` and `content-type` headers; `body_sha256`.
- `response`: `status`; the `content-type`, `retry-after` and `link` headers; `body_base64`.

`replay_transport` answers requests in recorded order. An unexpected method, URL or body hash raises
`ContractViolation("provider_recording", ...)`. `error_transport(error_class)` returns a canned
response for each of the six classes:

| Class | Response |
| --- | --- |
| `authentication` | 401 |
| `forbidden` | 403 |
| `not_found` | 404 |
| `throttled` | 429 with `Retry-After: 1` |
| `transient` | 503 |
| `malformed` | 200 with an invalid JSON body |

S3's HTTP client classifies them (R-S3-3).

**Negative-fixture convention** (decision 1f). The convention lives in the kit's own tests,
`tests/unit/test_connector_testing_kit.py`, which holds a table
`VIOLATIONS: dict[str, Callable[[], Violation]]`. It has exactly one entry per name in
`testing.ASSERTIONS`. Each entry builds the smallest input that breaks that one rule: a batch and
context, a connector, a runtime double or an extension. A completeness test fails when an assertion
is added without a negative fixture. The positive fixture is S3's fixture connector (R-S3-6), which
passes every assertion.

**Runtime assertions.** `assert_runtime_resilience` runs `run_case` once per name in
`RUNTIME_FAILPOINTS`, with S3's `fault_hook` raising at that failpoint (R-S3-2). After each fault it
asserts four things:

- the last published generation is still selected by `query_session(ctx, EVERYTHING)`
  (`knowledge/query_access.py:126-164`), with its passages;
- a replayed page leaves `generation_checksums` unchanged;
- a failed inventory deletes nothing;
- no failure advanced the cursor past a page whose raw observations are not durable.

**Registry assertion.** `extension_lock` hashes the canonical JSON body of every fact template,
object kind and predicate. Keys are `template:<kind>/<name>@<template version>`,
`kind:<name>@<descriptor version>` and `predicate:<name>@<descriptor version>`.
`assert_registry_lock` raises `ContractViolation("registry_version_bump", "<key> changed without a
version bump")` when a key present in both the lock and the extension has a different hash. A new key
is written by `--update-golden`. A changed body under an unchanged key is never rewritten.

**`validate_package(target, runtime=False)`** does four things:

1. loads the package;
2. registers its extension, with refusals reported as violations;
3. checks the registry lock;
4. for every fixture case, runs `emit` over the case's inputs with `check_contract` and
   `assert_emit_pure`. The `RevisionInput` is built from the case's `RawFetch` metadata through
   S2's constructor (R-S2-1).

It skips `run_case` and the runtime assertions, and the report's `scope` is `contract`. The default
`runtime=True` gives `scope` `full`, which the CLI runs. S6's HTTP route and MCP tool use
`runtime=False`, because a scratch build does not belong inside a server request.

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

Templates live at `src/hippo/connectors/scaffold/templates/` as package data and are read through
`importlib.resources.files("hippo.connectors.scaffold") / "templates"`. They are `string.Template`
files with placeholders `$name`, `$class_name`, `$family`, `$kinds`, `$primary_kind` and `$key_prefix`:

| Template | Writes | Content |
| --- | --- | --- |
| `__init__.py.tmpl` | `<name>/__init__.py` | `from .connector import Connector` for the entry point |
| `connector.py.tmpl` | `<name>/connector.py` | A descriptor with the family and kinds. `list_changes` lists `*.json` files under `config.export_dir`. `fetch` reads bytes. `fetch_policy` returns unknown, with a comment that unknown is deny. `emit` parses one JSON object and emits one node of `$primary_kind` with key parts `(config.instance, record["id"])`, or a `ParseFailure`. |
| `types.py.tmpl` | `<name>/types.py` | `TypeExtension` with one `ObjectKindDefinition` per kind: an attrs model with `extra="forbid"` and `title: str`, `key_template=("instance", "id")`, `label_template="{title}"`, and one `FactTemplate` named `summary`, version `1` |
| `templates.py.tmpl` | `<name>/templates.py` | The `FactTemplate` objects `types.py` imports. Every generated module imports only from `hippo.connectors`, `hippo.connectors.base`, `hippo.connectors.keys`, `hippo.connectors.render`, `hippo.knowledge.model`, `pydantic` and the standard library (R-S2-8). |
| `fixtures/basic/...` | `<name>/fixtures/basic/` | `config.json`, `changes.json` with one page and two records (one malformed), `policies.json`, `inputs/record-1` and `inputs/record-2` |
| `test_connector.py.tmpl` | `<name>/tests/test_connector.py` | `assert validate_package(Path(__file__).parents[1]).passed` |

After writing the files, `render_package` computes the goldens and the registry lock once by calling
`run_case(..., update_golden=True)`. A freshly scaffolded package therefore passes `validate`. The
generated test's goldens are pinned in `tests/unit/test_connector_scaffold.py`, so a kit change that
alters scaffold output fails there, not silently in a developer's package.

### 3.3 The commands (S4b, decision 3)

Parser additions, placed after the `user` group at `cli.py:132-146`:

```text
hippo connector new <name> --family <family> [--kinds <kind> ...] [--dest <dir>]
hippo connector list
hippo connector validate <package-or-path> [--update-golden]
hippo connector probe <name> --config <file>
hippo connector sync <instance> [--config <file>] [--partition <p>] [--dry-run]
```

`main`'s handler table (`cli.py:155-169`) gains `"connector": cmd_connector`. `cmd_connector`
dispatches on `args.connector_command` and imports `hippo.connectors.*` inside each branch.

| Command | Store | Provider | Forwards when the store is locked | Exit codes |
| --- | --- | --- | --- | --- |
| `new` | none (writes only under `--dest`) | none | never | 0 written; 2 invalid name, unknown family, name already a registered connector kind, or target exists |
| `list` | reads `Connector` rows (requires `manage_sources` when users exist) | none | yes: `RemoteHippo.connectors()` | 0; 2 denied or remote refusal |
| `validate` | scratch only | none (replay) | never | 0 passed; 1 violation or golden diff; 2 package cannot load or registration refused |
| `probe` | none | read-only through the connector | never (the config file and credential references stay on the caller's machine) | 0 classified; 1 classification is a registration request (prints the `TypeExtension` needed); 2 unknown connector or config invalid |
| `sync --dry-run` | scratch only | read-only | never | 0 printed coverage; 1 sync failed; 2 unknown connector or config invalid |
| `sync` | configured store (requires `manage_sources`) | read-only | never; prints `error: the database is open in hippo serve; stop it to sync, or use --dry-run` and returns 2 | 0; 1 sync failed; 2 denied, locked or invalid |

`<instance>` is a connector name when `--config` is given (dry run) or a stored `Connector.id`
otherwise. Output is human text through `print` and `print_table` (`cli.py:815-825`).

- `list` prints name, version, families, origin (`built-in`, `in-repo` or `entry point`), enabled,
  instances and classified partitions. An entry point that fails to import is a row with
  `error: <exception class name>` (design §9).
- `probe` prints, per partition, the family, the provider type to kind mapping, observed
  capabilities, the sample count, warnings and the registry fingerprint.
- `validate` prints one line per assertion violation (`<assertion>: <message> [<record>]`), the case
  diffs and the registry diff (`+ kind incident`, `+ predicate AFFECTS`).

`remote.py` gains one method, placed after `sources` at `remote.py:159-160`:

```python
def connectors(self) -> list[dict[str, Any]]:
    return self._json(self._client.get("/api/connectors"))
```

**The `GET /api/connectors` response contract** is defined here and implemented by S6. It is a list
of `ConnectorSummary` objects:

```json
{
  "name": "incidents_ndjson",
  "version": "1",
  "families": ["incident"],
  "origin": "in-repo",
  "enabled": true,
  "error": null,
  "instances": [{"id": "connector-...", "partitions": [{"partition": "...", "family": "incident"}]}]
}
```

### 3.4 The developer guide (S4b, decision 4)

`docs/spec/cdk-guide.md` outline:

1. What a connector is: the descriptor and methods of design §1, with no store, index, model or
   clock.
2. `hippo connector new`: the generated files (the §3.2 table).
3. The descriptor (example `descriptor`).
4. Registering types: `TypeExtension`, kinds, predicates with `owner_families`, fact templates
   (example `types`).
5. Talking to the provider: `list_changes`, `fetch`, `fetch_policy`, and the recording helpers
   (example `sync_half`).
6. `emit`: nodes, edges, passages, units, aliases, failures, and rendering (example `emit`).
7. Fixtures and goldens: the §3.1 layout table and `--update-golden`.
8. `hippo connector validate`: one row per name in `testing.ASSERTIONS`, what trips it and how to fix
   it.
9. `hippo connector probe` and classification.
10. `hippo connector sync --dry-run`.
11. Packaging and the `hippo.connectors` entry point group.
12. The rules the kit enforces: no model call, no clock, unknown policy is deny, no unearned
    relation label.

**Examples are the fixture connector.** Every fenced Python block in the guide is preceded by
`<!-- cdk-guide: example <name> -->`. It must equal, byte for byte, the region between
`# cdk-guide: begin <name>` and `# cdk-guide: end <name>` in S3's fixture connector source (R-S3-6).
S4b adds those marker comments to S3's file: comments only, after S3 merges. The fixture connector's
own tests execute that code, so the guide's examples run in CI. The guide's fenced Python must pass
`ruff format --check`.

## 4. File-by-file steps

### S4a (worktree `s4a`)

1. **Create** `tests/unit/test_connector_testing_kit.py` with the §5 S4a tests. Run it, save
   `/tmp/hippo-cdk-s4a-red.log`, and confirm every test fails on the missing module.
2. **Create** `src/hippo/connectors/testing.py`:
   1. The constants and exception types.
   2. `load_case` and `discover_cases`.
   3. The twelve contract assertion functions, `check_contract` and `assert_contract`.
   4. `purity_guard` and `assert_emit_pure`.
   5. `scratch_store`, `offline_ollama` (an `httpx.MockTransport` answering `/api/tags`,
      `/api/show` and `/api/embed` with the `fake_ollama.embed_text` algorithm, and `/api/chat` with
      500), `_ReplayConnector` and `run_case`.
   6. `assert_runtime_resilience`.
   7. `extension_lock` and `assert_registry_lock`.
   8. The three transports.
   9. `load_connector_package` and `validate_package`.
3. **Modify** `tests/unit/test_import_order.py:14-28`: append `"hippo.connectors.testing"` to
   `MODULES`.
4. **Measure** `validate_package` on S3's fixture connector with the default `scratch_store`:
   LadybugDB with its buffer pool bounded to `256 * 2**20` bytes, the
   `LADYBUG_TEST_BUFFER_POOL_BYTES` value at `tests/conftest.py:229`. Record wall time and peak RSS
   in the evidence, so the cost of deviation 1 is known when the orchestrator ratifies it.
5. Run GREEN (§6), save `/tmp/hippo-cdk-s4a-green.log`, run Ruff, commit.

### S4b (worktree `s4b`, after S4a merges)

1. **Create** `tests/unit/test_connector_scaffold.py` and `tests/unit/test_cli_connector.py` with
   the §5 S4b tests. Save the RED log to `/tmp/hippo-cdk-s4b-red.log`.
2. **Create** `src/hippo/connectors/scaffold/__init__.py` and
   `src/hippo/connectors/scaffold/templates/*.tmpl` (the §3.2 table).
3. **Modify** `src/hippo/cli.py`:
   1. At `:132-146`, add the `connector` subparser group.
   2. At `:155-169`, add `"connector": cmd_connector` to the handler table.
   3. Add `cmd_connector` and five private helpers beside `cmd_user`, with function-local imports.
   4. Add `"connector"` to nothing else: it is not an `EVIDENCE_COMMANDS` member (`cli.py:62`),
      because its store reads are administration, gated by `_require(principal, "manage_sources")`.
4. **Modify** `src/hippo/remote.py`: at `:159-160`, add `connectors()`.
5. **Create** `docs/spec/cdk-guide.md` (§3.4). This needs the brief grant of open question 1.
6. **Modify** S3's fixture connector module (R-S3-6): the `cdk-guide` marker comments, comments
   only.
7. Run GREEN, save `/tmp/hippo-cdk-s4b-green.log`, run Ruff on every changed `.py` and on the guide,
   commit.

## 5. RED tests

### `tests/unit/test_connector_testing_kit.py` (S4a)

- `test_every_assertion_has_exactly_one_negative_fixture`
- `test_a_negative_fixture_fires_its_own_assertion[<each name in ASSERTIONS>]`
- `test_a_negative_fixture_fires_no_other_contract_assertion[<each contract assertion>]`
- `test_the_fixture_connector_passes_every_assertion`
- `test_assert_contract_raises_the_first_violation_in_assertion_order`
- `test_a_nondeterministic_emit_fails_emit_deterministic`
- `test_the_purity_guard_refuses[socket_connect|create_connection|getaddrinfo|httpx_client|httpx_async_client|ollama_chat_json|ollama_chat_text|ollama_embed|ollama_embed_one|ollama_embed_explicit|subprocess_run|subprocess_popen|os_system|time_time|time_monotonic|perf_counter|datetime_now|datetime_utcnow|date_today]`
- `test_the_purity_guard_restores_every_patch_after_a_violation`
- `test_two_purity_guards_never_overlap`
- `test_load_case_reads_the_documented_layout`
- `test_load_case_refuses_an_unknown_file_a_missing_input_and_an_unquoted_name`
- `test_a_missing_policy_replays_as_unknown`
- `test_run_case_pins_the_store_clock_to_the_fixed_instant`
- `test_run_case_diffs_published_records_against_the_goldens`
- `test_update_golden_rewrites_the_seven_files_and_returns_the_diff`
- `test_goldens_are_canonical_json_sorted_by_id_without_job_or_event_payload`
- `test_record_then_replay_round_trips_a_provider_session`
- `test_replay_refuses_an_unexpected_request`
- `test_a_recording_redacts_credentials_from_every_url`
- `test_each_error_class_has_a_replayable_response[authentication|forbidden|not_found|throttled|transient|malformed]`
- `test_runtime_resilience_holds_for_the_fixture_connector[<each failpoint>]`
- `test_runtime_resilience_fires_when_the_runtime_misbehaves[<each failpoint>]`
- `test_the_registry_lock_fires_when_a_template_changes_without_a_version_bump`
- `test_the_registry_lock_accepts_a_bumped_template_version`
- `test_the_offline_model_embeds_deterministically_and_refuses_chat`
- `test_validate_package_reports_the_registry_diff`

### `tests/unit/test_connector_scaffold.py` (S4b)

- `test_new_writes_the_documented_package_files`
- `test_a_new_package_passes_validate`
- `test_a_new_packages_own_test_passes`
- `test_new_refuses_an_invalid_name_an_unknown_family_a_registered_kind_and_an_existing_directory`
- `test_the_scaffold_templates_ship_as_package_data`
- `test_scaffold_output_for_a_fixed_request_is_pinned`
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
- `test_sync_dry_run_prints_coverage_and_writes_nothing_to_the_configured_store`
- `test_sync_refuses_with_exit_2_when_the_store_is_locked`
- `test_sync_requires_manage_sources_when_users_exist`

No new test module imports `fastapi.testclient` or `starlette.testclient`. Forwarding is proven
against `httpx.MockTransport`.

## 6. GREEN commands and the CK4 CHECK line

```bash
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_testing_kit.py -q -o addopts='' -W error > /tmp/hippo-cdk-s4a-green.log 2>&1; echo EXIT $?
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_scaffold.py tests/unit/test_cli_connector.py tests/unit/test_cli.py tests/unit/test_import_order.py -q -o addopts='' -W error > /tmp/hippo-cdk-s4b-green.log 2>&1; echo EXIT $?
HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_connector_testing_kit.py -q -o addopts='' -W error > /tmp/hippo-cdk-s4a-ladybug.log 2>&1; echo EXIT $?
.venv/bin/ruff check src/hippo/connectors/testing.py src/hippo/connectors/scaffold src/hippo/cli.py src/hippo/remote.py tests/unit/test_connector_*.py && .venv/bin/ruff format --check src/hippo/connectors/testing.py src/hippo/connectors/scaffold src/hippo/cli.py src/hippo/remote.py tests/unit/test_connector_*.py docs/spec/cdk-guide.md
```

`tests/unit/test_cli.py` must pass unchanged, with its existing per-test markers.

**CK4 CHECK line: confirmed as written.** All three files are created by this plan, and none imports
a test client at module level, so no form (b) filter is needed. The Ladybug line above is evidence
for the ledger, not a new gate line.

**Ledger lines.** The CHECK line stands. Proposed CRITERIA wording, replacing "`remote.py` forwards
the commands": "`remote.py` forwards `hippo connector list` to `GET /api/connectors`; `new`,
`validate`, `probe` and `sync --dry-run` run locally by design, and a non-dry-run `sync` refuses while
the server holds the store (plan deviation 4)".

## 7. Worktrees, merge order, do-not-touch

- **Worktrees:** `s4a`, `s4b`, created per `ai_docs/handoffs/fleet-worker-rules.md:32-44` from the
  HEAD the orchestrator names after S3 merges.
- **Merge order:** S1a → S1b → S2 → S3 → S4a → S4b. S4b depends on S4a's `validate_package` and
  `run_case`. S5 may run beside S4 once S3 has merged. S6 merges after S4b.
- **S4a owns:** `src/hippo/connectors/testing.py`, `tests/unit/test_connector_testing_kit.py`, and one
  appended line in `tests/unit/test_import_order.py`.
- **S4b owns:** `src/hippo/connectors/scaffold/**`, `src/hippo/cli.py`, `src/hippo/remote.py`,
  `docs/spec/cdk-guide.md` (grant required), `tests/unit/test_connector_scaffold.py`,
  `tests/unit/test_cli_connector.py`, and marker comments in S3's fixture connector.
- **Do not touch:**
  - `src/hippo/knowledge/**`, `src/hippo/store/**`, `src/hippo/ingest/**`;
  - S2's `connectors/{base,classify,keys,render,emit}.py` and `connectors/__init__.py`;
  - S3's `connectors/{sync,http,credentials}.py`, apart from S4b's marker comments in the fixture
    connector, and `knowledge/staged_records.py`;
  - `src/hippo/web/**`, `src/hippo/mcp_server.py`;
  - `docs/spec/connector-developer-kit.md`, `docs/rag_it_all*.md`, every gate ledger, the checkpoint
    file.

## 8. Decisions taken

1. **`testing.py`.**
   - *Layout:* §3.1, with strict loading, so a typo fails.
   - *`run_case`:* scratch context, pinned clock, replay wrapper, S3's sync entry, published records
     read back by generation.
   - *Assertions:* sixteen names, twelve of them contract rules. Each overlapping check delegates to
     S2's function.
   - *Purity guard:* process-wide patches under a lock, the connector's own module-global `datetime`
     replaced, `emit` in the calling thread.
   - *Recording:* ordered replay with redacted URLs and six canned error classes.
   - *Negatives:* one table entry per assertion, with a completeness test.
   - *Goldens:* seven canonical JSON files and `--update-golden` that prints the diff.
2. **Scaffold.** `string.Template` files shipped as package data under `connectors/scaffold/templates`.
   The generated package computes its own goldens and lock at creation. Scaffold output for a fixed
   request is pinned by a test.
3. **Commands.** Five subcommands on the `user` group's shape, with function-local imports. Only
   `list` forwards. Exit codes are 0, 1 and 2 as tabulated. `new`, `validate`, `probe` and
   `sync --dry-run` never open the configured store.
4. **Guide.** Twelve sections. Every Python example equals a marked region of S3's fixture connector,
   enforced by a test.
5. **The kit's scratch store is a temporary LadybugDB.** The Fake store is test-only
   (`tests/fakes/fake_store.py:66`), and `store/memory.py:43` is not an in-memory store. Tests
   substitute the Fake through `testing.scratch_store`.
6. **The kit ships its own offline model** (§3.1). `validate` and `sync --dry-run` must not require a
   running Ollama, and the managed build asks the model for tags, capabilities and embeddings.
7. **Kinds and predicates are versioned by the descriptor's version** in the registry lock, because
   design §3's `ObjectKindDefinition` and `PredicateDefinition` carry no version of their own.
   Templates are versioned by `FactTemplate.version` (R-S1-2).
8. **Sizing (decision 12).** Two workers, S4a and S4b, split at the kit/command boundary.

## 9. Requires from S1, S2 and S3

Each item names what S4 calls. When the S1, S2 or S3 plan spells a name differently, that plan wins
and the S4 worker changes the one call site named.

- **R-S1-1.** The design §3 `Registry` API verbatim, plus:
  - a constructor of a fresh registry holding only the built-ins;
  - `Registry.load()` returning the entry points that failed to import, with their exception;
  - `ObjectKindDefinition.family`, `.key_template` and `.fact_templates`;
  - `PredicateDefinition.owner_families`, `.identity` and `.canonical_direction`.

  Call sites: `testing.run_case`, `testing.validate_package`, `cli._connector_list`.
- **R-S1-2.** `FactTemplate` carries `name`, `version` and the attribute names it consumes. Call
  site: `testing.extension_lock`.
- **R-S2-1.** Every design §1 record importable from `hippo.connectors.base`: `ConnectorDescriptor`,
  `Connector`, `ChangePage`, `Change`, `RawFetch`, `PolicyObservation` (with an unknown value),
  `ExternalRef`, `SyncCursor`, `RevisionInput`, `TypeMapping`, `Classification`, `EmissionBatch`,
  `NodeEmission`, `EdgeEmission`, `PassageEmission`, `UnitEmission`, `AliasEmission`, `ParseFailure`,
  `Family`, `Clock`, and the registration-request outcome of `probe` (design §2).
- **R-S2-2.** `keys.py` exposes the per-kind builder and a check that a key part list matches a kind's
  `key_template`. Call site: `assert_identities_from_builders`.
- **R-S2-3.** `render.py` exposes template evaluation. Call site: `assert_one_fact_per_unit`.
- **R-S2-4.** The span verifier (bytes, locator → text hash). Call site: `assert_spans_match_bytes`.
- **R-S2-5.** The token counter behind the 1,500-token passage bound. Call site:
  `assert_passages_within_token_bound`.
- **R-S2-6.** The policy binder's unknown-to-deny rule. Call site: `assert_unknown_policy_is_deny`.
- **R-S2-7.** The direction and ownership check with its developer-facing message. Call site:
  `assert_direction_and_ownership`.
- **R-S2-8.** `hippo.connectors.base` re-exports S1's `TypeExtension`, `ObjectKindDefinition`,
  `PredicateDefinition` and `FactTemplate`. The scaffold templates import them from there, so a
  scaffolded package imports only the public kit and `hippo.knowledge.model`: the same rule S6's
  exemplar is held to (`cdk-s6-exemplar.md` §3.3, R-S2-1). Call sites: `types.py.tmpl`,
  `templates.py.tmpl`.
- **R-S3-1.** One entry that syncs one partition of one connector on a given `AppContext`, taking an
  actor, a frozen registry, a clock, a `fault_hook` and an `on_batch(revision, batch)` observer, and
  returning the published generation id. Call site: `testing.run_case`. Proposed:
  `sync_partition(ctx, connector, *, config, partition, actor, registry, clock, fault_hook=None,
  on_batch=None)`.
- **R-S3-2.** The failpoint names for design §8's five runtime boundaries, raised through
  `fault_hook(name)` as `store/generations.py:1417-1418` does. Call site:
  `assert_runtime_resilience`.
- **R-S3-3.** `connectors/http.py` accepts an `httpx` transport and classifies the six error classes.
  Call site: the recording tests.
- **R-S3-4.** `credentials.redact_url` and `credentials.resolve`. Call sites: `record_transport`,
  `cli._connector_probe`.
- **R-S3-5.** The runtime's own purity guard around `emit` in its worker pool. It may reuse
  `testing.purity_guard` only if S3 places the guard in a module both import. Otherwise S4 imports
  S3's guard and `purity_guard` becomes a re-export.
- **R-S3-6.** The fixture connector's module path and fixture case directory (S3's decision 11).
  Call sites: the positive fixture, the guide marker test, `validate` tests.
- **R-S3-7.** How a scratch run gets a `Connector` instance row and a `Source` row for its partition,
  and that the runtime embeds passages through `ctx.ollama`. Call site: `run_case`.

## 10. Design deviations

1. **Design §8 says `run_case` runs "on the Fake store".** The Fake store is test code and does not
   ship, so the installed kit uses a temporary LadybugDB store. Tests, and the CK4 CHECK line,
   substitute the Fake.
2. **Design §8's `assert_contract(batch, registry)` gains a third argument, `context`.** Two rules
   (`no_ingestion_time`, `spans_match_bytes`) need the injected clock and the revision bytes, which a
   batch does not carry.
3. **Design §9's `sync <instance> [--partition <p>] [--dry-run]` gains `--config <file>`**, because a
   dry run of a connector name has no stored config. `new` gains `--dest <dir>`.
4. **Design §9 says the CLI forwards "as the other commands do".**
   - Only `list` forwards.
   - `probe` keeps a caller's config file and credential references on the caller's machine.
   - `validate`, `new` and `sync --dry-run` use no configured store.
   - A non-dry-run `sync` refuses while `hippo serve` holds the store, because the server-side sync
     route is Task 15's `POST /api/connectors/{id}/sync`, which S6 does not create.

## 11. Open questions

1. **`docs/spec/cdk-guide.md` ownership.** `ai_docs/handoffs/fleet-worker-rules.md:17` forbids workers
   editing `docs/spec/*.md`, and design §13 gives the file to S4. S4b's brief must grant it by name.
2. **The fixture connector's location** is S3's decision 11. If it is under `tests/fakes/`, the guide
   cites a test path, which is acceptable but unusual. If it is under `src/hippo/connectors/`, it must
   not collide with `connectors/testing.py`, a module that S4 owns.
3. **`Connector.classification_json`** (design §2) appears in no slice's file list at this HEAD.
   `list` shows stored classification only if S1b adds the column and S3 writes it. Otherwise `list`
   shows `not classified`.
4. **The 1,500-token bound needs one named tokenizer** (R-S2-5). The design does not name one.

## Plan verification checklist

| Interface | Implementation | Registration | Plan step |
| --- | --- | --- | --- |
| `hippo connector` group | `cli.cmd_connector` | `cli.py:155-169` handler table | S4b step 3 |
| `RemoteHippo.connectors` | `remote.py` | `GET /api/connectors`, implemented by S6 | S4b step 4 |
| Scaffold templates | `connectors/scaffold/templates/*.tmpl` | wheel package data under `src/hippo` | S4b step 2 |
| Kit module | `connectors/testing.py` | `test_import_order.MODULES` | S4a steps 2-3 |

| Regression hotspot | Location | Proof |
| --- | --- | --- |
| `hippo --help` stays light | `test_import_order.py:61-81` | `test_connector_help_imports_no_serving_machinery` plus the unchanged file |
| Existing CLI exit codes and forwarding | `cli.py:170-192`, `:597-612` | `tests/unit/test_cli.py` unchanged in the S4b GREEN run |
