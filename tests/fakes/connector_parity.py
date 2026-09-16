"""Two worlds, one fixture: the pre-kit coordinator path and the kit's runtime path.

`ai_docs/plans/cdk-s5-port.md` section 6. Each world is built on its own data directory and
its own store of the selected backend, one after the other, so the same code shape serves a
backend that keeps two stores open (Fake, LadybugDB) and one that serves a single database
per process (Neo4j, reset between worlds). Every world pins the store clock, `new_id` in each
module that binds it, and the operation identity, so the two worlds agree on every id that is
not content-addressed.

`published_snapshot` returns plain JSON-able data: the nine comparisons of section 6, with
`Generation.registry_fingerprint` removed, because it is the one allowed difference. The
operational rows the plan names - maintenance jobs, `IndexEvent.payload_json`, Source-row
presentation and store meta epochs - are outside the snapshot on purpose.

S5a creates this helper for the prose lane; S5b extends it with the code worlds.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import local

import httpx

from hippo.access import Principal
from hippo.config import Config
from hippo.context import AppContext
from hippo.ingest import managed_activation, pipeline
from hippo.ingest.prose_generation import build_plain_source
from hippo.knowledge.build_authority import BuildActor
from hippo.knowledge.embedding_cache import EmbeddingCache
from hippo.knowledge.identity import canonical_json
from hippo.knowledge.raw_artifacts import RawArtifactStore
from hippo.ollama import Ollama
from hippo.store.migrations import DEFAULT_WORKSPACE_ID

# The instant both worlds read from the store clock. Operation identities are a counter, not one
# value: a refresh is a second build, and the two must not share one operation's identity.
INSTANT = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
# Every module that binds `store.base.new_id` by name; rebinding the definition alone would
# leave these three reading the original.
ID_MODULES = ("hippo.store.base", "hippo.store.memory", "hippo.store.ladybug", "tests.fakes.fake_store")
# The pasted texts and the uploaded prose file the parity fixtures use, from
# `tests/unit/test_managed_pipeline_activation.py:35-39`.
FIRST_TEXT = "ACME builds Robot."
SECOND_TEXT = "ACME now builds Robot."
LONG_TEXT = "ACME builds Robot. " * 200
PROSE_FILENAME = "notes.md"
PROSE_FILE = b"# Notes\n\nACME builds Robot.\n"

# Section 6: the native kinds `generation_checksums` walks (`store/generations.py:917`).
NATIVE_KINDS = ("Passage", "Symbol", "DataObject", "Commit")
# Section 6 comparison 7: an IndexEvent is compared on its identity and its shape, never on
# `payload_json`, which carries the build job's `uuid4` lease owner.
EVENT_FIELDS = ("id", "kind", "generation_id", "aggregate_id", "sequence", "dedupe_key", "created_at")


def backend() -> str:
    """Which store the worlds build. The same rule as `tests/conftest.py:179-185`."""
    chosen = os.environ.get("HIPPO_TEST_STORE", "").strip().lower()
    if chosen:
        return chosen
    return "neo4j" if os.environ.get("NEO4J_URI") else "ladybug"


@contextmanager
def _store(root: Path):
    """A store of the selected backend that starts empty, mirroring `tests/conftest.py:187-226`."""
    chosen = backend()
    if chosen == "fake":
        from tests.fakes.fake_store import FakeStore

        yield FakeStore()
    elif chosen == "ladybug":
        from hippo.store.ladybug import LadybugStore

        embedded = LadybugStore(root / "hippo.lbug", buffer_pool_bytes=256 * 2**20)
        try:
            yield embedded
        finally:
            embedded.close()
    elif chosen == "neo4j":
        # One database serves one process, so world A is snapshotted and the database reset
        # before world B opens. Not exercised by the S5a lines; the Neo4j parity of the
        # connector files is root-owned (plan section 9).
        from hippo.store import Store

        real = Store(
            os.environ["NEO4J_URI"],
            os.environ.get("NEO4J_USER", "neo4j"),
            os.environ.get("NEO4J_PASSWORD", "hippo-password"),
        )
        try:
            real.driver.execute_query("MATCH (n) DETACH DELETE n", database_=real.database)
            for catalog, kind in (("CONSTRAINTS", "CONSTRAINT"), ("INDEXES", "INDEX")):
                result = real.driver.execute_query(
                    f"SHOW {catalog} YIELD name RETURN name", database_=real.database
                )
                for record in result.records:
                    name = record["name"].replace("`", "``")
                    real.driver.execute_query(f"DROP {kind} `{name}` IF EXISTS", database_=real.database)
            real.ensure_schema()
            yield real
        finally:
            real.close()
    else:
        raise ValueError(f"HIPPO_TEST_STORE must be ladybug, fake or neo4j, not {chosen!r}")


class _Counter:
    """`new_id` as a counter, so two worlds mint the same source, user and role ids."""

    def __init__(self) -> None:
        self.n = 0

    def __call__(self) -> str:
        self.n += 1
        return f"{self.n:012x}"


@dataclass
class World:
    """One built world: its context, its builder, and the operation identities it minted."""

    ctx: AppContext
    actor: BuildActor
    user: str
    runtime: object
    # Every operation identity this world's dispatch minted, in order. `add_text` / `add_upload`
    # mint `operations[0]` through `start_indexing`, and world A reuses it for the direct call, so
    # both worlds build under the same identity.
    operations: list[str]


@contextmanager
def world(monkeypatch, tmp_path: Path, name: str, **config_fields):
    """A signed-in builder, a pinned clock, pinned ids and a mock model, on a fresh store.

    The caller runs one world at a time and keeps only its snapshot, because a backend may
    serve a single database per process. `config_fields` overrides `Config` defaults, so a
    scenario can make both worlds refuse for the same configured reason.
    """
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    counter = _Counter()
    for module in ID_MODULES:
        monkeypatch.setattr(f"{module}.new_id", counter, raising=False)
    operations: list[str] = []

    def new_operation_id() -> str:
        operations.append(f"index.{len(operations) + 1:032x}")
        return operations[-1]

    monkeypatch.setattr(managed_activation, "new_operation_id", new_operation_id)
    with _store(root) as store:
        store._generation_clock = lambda: INSTANT
        transaction_state = local()
        original_transaction = store.transaction

        @contextmanager
        def transaction():
            with original_transaction():
                transaction_state.depth = getattr(transaction_state, "depth", 0) + 1
                try:
                    yield
                finally:
                    transaction_state.depth -= 1

        monkeypatch.setattr(store, "transaction", transaction)
        store.ensure_schema()
        store.ensure_roles()
        user = store.create_user("builder", "password", "individual")
        from hippo.knowledge import model as k

        store.put_knowledge(
            k.WorkspaceMembership(
                workspace_id=DEFAULT_WORKSPACE_ID,
                principal_id=user,
                mapping_authority="local",
                enabled=True,
                policy_epoch=1,
            )
        )
        store.set_meta("reviewed_mapping_authorities", ["local"])
        actor = BuildActor.reader(Principal.for_user(store.get_user(user), store.get_role("individual")))
        from tests.unit.test_prose_generation import Runtime

        runtime = Runtime(store, transaction_state)
        ollama = Ollama(
            "http://local-model",
            "chat:latest",
            "embed:latest",
            num_ctx=8192,
            client=httpx.Client(base_url="http://local-model", transport=httpx.MockTransport(runtime.handle)),
        )
        ctx = AppContext(
            config=Config(data_dir=root / "data", openie_workers=2, **config_fields),
            store=store,
            ollama=ollama,
        )
        yield World(ctx=ctx, actor=actor, user=user, runtime=runtime, operations=operations)


def hold_jobs(monkeypatch, ctx) -> list:
    """Capture every submitted job without running it: world A never runs the managed lane."""
    held: list = []

    def start(key, work):
        held.append((key, work))
        return True

    monkeypatch.setattr(ctx.jobs, "start", start)
    return held


def inline_jobs(monkeypatch, ctx) -> list:
    """Run every submitted job in the caller's thread: world B dispatches through the runtime."""
    started: list = []

    def start(key, work):
        started.append(key)
        work()
        return True

    monkeypatch.setattr(ctx.jobs, "start", start)
    return started


def pre_kit_prose_build(ctx, *, source_id: str, actor: BuildActor, operation_id: str, job_key: str):
    """The prose branch `run_managed_build` was at `2a9913a`, before S5a replaced it.

    Copied verbatim from `managed_activation.run_managed_build:655-674` so that world A keeps
    calling the pre-kit arguments after the switch has replaced them.
    """
    source = ctx.store.get_source(source_id)
    refresh = bool(source.get("active_generation_id"))
    saved = managed_activation.ingress_file(
        ctx, source_id, stored_name=managed_activation._recorded_name(source)
    )
    options = managed_activation.build_options(ctx)
    spec = managed_activation.embedding_spec(ctx.ollama)
    raw_store = RawArtifactStore(
        managed_activation.raw_root(ctx), max_object_bytes=int(ctx.config.max_upload_bytes)
    )
    cache = EmbeddingCache(managed_activation.cache_root(ctx))

    managed_activation.present(ctx, source_id, **managed_activation._starting_fields(refresh))
    return build_plain_source(
        ctx,
        source_id=source_id,
        actor=actor,
        inputs=(managed_activation.FileInput(saved.name, saved),),
        options=options,
        raw_store=raw_store,
        embedding_spec=spec,
        operation_id=operation_id,
        should_stop=lambda: ctx.jobs.is_cancelled(job_key),
        on_progress=lambda progress: managed_activation._present_progress(
            ctx, source_id, progress, refresh=refresh
        ),
        embedding_cache=cache,
    )


def runtime_prose_build(ctx, *, source_id: str, actor: BuildActor, operation_id: str):
    """World B's build: the call `pipeline._run_managed_indexing` makes (`pipeline.py:361-367`)."""
    return managed_activation.run_managed_build(
        ctx,
        source_id=source_id,
        actor=actor,
        operation_id=operation_id,
        job_key=pipeline.job_key(source_id),
    )


def spy_receipts(monkeypatch) -> list:
    """Record every receipt `pipeline` hands to `record_build_receipt`, and delegate.

    World B's receipt is not a return value: the job body presents it and returns None.
    """
    receipts: list = []
    original = managed_activation.record_build_receipt

    def record(ctx, *, source_id, receipt):
        receipts.append(receipt)
        return original(ctx, source_id=source_id, receipt=receipt)

    monkeypatch.setattr(managed_activation, "record_build_receipt", record)
    return receipts


def _jsonable(value):
    """Plain JSON data for a record, a row or a tuple of them, with a stable key order."""
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    if isinstance(value, float):
        return float(value)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def raw_inventory(ctx) -> dict[str, str]:
    """The content-addressed raw objects, as `test_managed_pipeline_activation.py:59-63` reads them."""
    root = Path(ctx.config.data_dir).resolve() / "knowledge" / "raw-v1"
    if not root.is_dir():
        return {}
    return {path.name: path.read_bytes().hex() for path in sorted(root.iterdir()) if path.is_file()}


# The `Generation` row is comparison 4, compared on its own with `registry_fingerprint` removed,
# so walking it here too would report the one allowed difference as a closure difference. `Source`
# and `Workspace` carry presentation and wall time, which section 6 puts outside the comparison.
# `Artifact` and `AccessPolicy` are kept, although `generation_checksums` skips them
# (`store/generations.py:1010-1011`): they are immutable inputs, and they must agree.
CLOSURE_SKIPPED = ("Generation", "Source", "Workspace")


def _closure(store, generation_id: str) -> list:
    """Every member, evidence member and binding, and every record they reference.

    Walked the way `generation_checksums` walks them (`store/generations.py:1017-1027`), so the
    comparison covers spans, derived views, dependencies, observations and prose extractions.
    """
    seen: dict[tuple[str, str], dict] = {}

    def visit(record) -> None:
        key = (type(record).__name__, record.id)
        if key in seen or key[0] in CLOSURE_SKIPPED:
            return
        seen[key] = _jsonable(record)
        for kind, rid in store._references(record):
            from hippo.knowledge import model as k

            if kind in k.RECORD_TYPES:
                target = store._knowledge_get(kind, rid)
                if target is not None:
                    visit(target)

    for kind in ("GenerationMember", "GenerationEvidenceMember", "NativeBinding"):
        for record in store._knowledge_rows(kind, generation_id=generation_id):
            visit(record)
    return sorted(([kind, rid, row] for (kind, rid), row in seen.items()), key=canonical_json)


def published_snapshot(ctx, generation_id: str, receipt) -> dict:
    """The nine comparisons of plan section 6, without the one allowed difference."""
    store = ctx.store
    generation = _jsonable(store._knowledge_get("Generation", generation_id))
    generation.pop("registry_fingerprint", None)
    manifest_revisions = [
        _jsonable(row.metadata_json)
        for row in store._knowledge_rows("ArtifactRevision")
        if row.metadata_json and "accepted_manifest_v1" in row.metadata_json
    ]
    events = [
        {field: _jsonable(getattr(row, field)) for field in EVENT_FIELDS}
        for row in store._knowledge_rows("IndexEvent", generation_id=generation_id)
    ]
    native = {
        kind: sorted(
            (
                store._canonical_native(kind, row)
                for row in store._native_rows(kind, generation_id=generation_id)
            ),
            key=canonical_json,
        )
        for kind in NATIVE_KINDS
    }
    return {
        "checksums": _jsonable(store.generation_checksums(generation_id)),
        "closure": _closure(store, generation_id),
        "native": _jsonable(native),
        "relationships": _jsonable(store._native_relationships(generation_id=generation_id)),
        "generation": generation,
        "accepted_manifest": sorted(manifest_revisions, key=canonical_json),
        "index_manifests": sorted(
            (_jsonable(row) for row in store._knowledge_rows("IndexManifest", generation_id=generation_id)),
            key=canonical_json,
        ),
        "index_events": sorted(events, key=canonical_json),
        "receipt": _jsonable(receipt),
        "raw_objects": raw_inventory(ctx),
    }
