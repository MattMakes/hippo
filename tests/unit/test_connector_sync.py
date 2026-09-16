"""The connector sync runtime: the nine steps, the failure matrix and the fixture connector.

Plan `ai_docs/plans/cdk-s3-runtime.md` Task S3c (section 12), with sections 4.7, 5, 6, 9 and 11 as
the contract. Rulings and review findings that bind this file: R48/B2 (a span keeps its first
capture's policy, recorded in `ArtifactRevision.metadata_json["span_policy_id"]`; row M8b),
R49/B4 (`connector_id` on the entry, the stored-classification refusal, `FAULT_POINTS`,
`contextvars.copy_context()` per emit worker), R51/M5 with review CK7 F5 (`ensure_connector`
creates an instance disabled and `enabled=None` leaves an existing one alone; a disabled instance
is refused), R52/M3 and M4 (a stored policy is refreshed only
inside half its TTL, row M21; `no_changes` is decided after the candidate generation), M15
(`fetch` of an absent id raises `ProviderNotFoundError`), R46/m7 (each registered definition equals
`descriptor.extension`), R60/R-S3-7 (a no-argument `FixtureConnector`, `fixtures/basic` with two
upserts, `inventory=True`, a probe that samples through its own `list_changes` and `fetch`),
R21 (classification written only on change), R25 (`build_plain_source` refuses a connector source
until S5a), R65 (the guard is thread-local and reports at most one violation per `emit`),
R66 (the registry is loaded before any lifecycle write; a collected unit may dangle), R68 (the
bundle carries aliases; `AssertionVersion.unit_id` is exempt from the store's reference checks),
m13 (M20's spy accounts for M9's own `collect_generation`), m15 (the pending log lives in the raw
store), m16 (row M22).
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from hippo.access import Principal
from hippo.connectors import base, emit, sync
from hippo.connectors import http as provider_http
from hippo.knowledge import model as k
from hippo.knowledge import staged_records
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.build_authority import BuildActor
from hippo.knowledge.embedding_profile import EmbeddingSpec
from hippo.knowledge.identity import canonical_json
from hippo.knowledge.query_access import query_session
from hippo.knowledge.raw_artifacts import RawArtifactStore
from hippo.knowledge.registry import Registry, extension_scope, use_registry
from hippo.ollama import Ollama
from tests.fakes.fixture_connector import (
    FixtureConfig,
    FixtureConnector,
    FixtureProvider,
)
from tests.fakes.fixture_connector.types import FIXTURE_EXTENSION, FIXTURE_FAMILY

PARTITION = "notes"
CASE = Path(__file__).resolve().parents[1] / "fakes" / "fixture_connector" / "fixtures" / "basic"

_INSTANCES = iter(f"https://fixture-{index}.example" for index in range(1, 500))


# ------------------------------------------------------------------ the harness


class RecordingOllama:
    """A real `Ollama` over `httpx.MockTransport`, with every embedded text recorded.

    The shape of `test_prose_generation.py:32-121`: the runtime embeds through `ctx.ollama` and
    nothing else, so the transport is where a test sees what was embedded (plan section 5.7).
    """

    def __init__(self, dimensions: int = 2) -> None:
        self.embedded: list[str] = []
        self.dimensions = dimensions

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content or "{}")
        if path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "embed:latest", "digest": "a" * 64},
                        {"name": "chat:latest", "digest": "b" * 64},
                    ]
                },
            )
        if path == "/api/show":
            return httpx.Response(
                200,
                json={"capabilities": ["embedding"] if body["model"] == "embed:latest" else ["completion"]},
            )
        if path == "/api/embed":
            self.embedded.extend(body["input"])
            return httpx.Response(
                200,
                json={
                    "model": "embed:latest",
                    "embeddings": [
                        [float(len(text) % 7 + 1)] + [0.0] * (self.dimensions - 1) for text in body["input"]
                    ],
                },
            )
        raise AssertionError(f"the runtime called {path}")

    def client(self) -> Ollama:
        return Ollama(
            "http://fixture-ollama",
            "chat:latest",
            "embed:latest",
            client=httpx.Client(base_url="http://fixture-ollama", transport=httpx.MockTransport(self.handle)),
        )


class World:
    """One frozen registry, one enabled fixture instance and one partition Source."""

    def __init__(self, ctx, tmp_path, registry, *, notes=None, partition=PARTITION):
        self.ctx, self.store, self.registry = ctx, ctx.store, registry
        self.partition = partition
        self.instance = next(_INSTANCES)
        self.provider = FixtureProvider.from_case(CASE, instance=self.instance, partition=partition)
        if notes is not None:
            self.provider.notes = dict(notes)
        self.connector_impl = FixtureConnector(self.provider)
        self.config = FixtureConfig(instance_url=self.instance, partition=partition)
        self.raw = RawArtifactStore(tmp_path / "raw", max_object_bytes=8_000_000)
        self.recorder = ctx.embed_recorder
        self.store.ensure_schema()
        self.store.ensure_roles()
        self.user = self.store.create_user("operator", "password", "individual")
        self.row = sync.ensure_connector(
            self.store,
            workspace_id=self.store.get_source(self._probe_source())["workspace_id"],
            kind="fixture",
            instance_url=self.instance,
            config=self.config,
            enabled=True,
        )
        self.workspace = self.row.workspace_id
        self.store.put_knowledge(
            k.WorkspaceMembership(
                workspace_id=self.workspace,
                principal_id=self.user,
                mapping_authority="local",
                enabled=True,
                policy_epoch=1,
            )
        )
        self.store.set_meta("reviewed_mapping_authorities", ["local"])
        self.classification = self.connector_impl.probe(self.config, self.store._now)
        self.row = sync.store_classification(
            self.store, connector=self.row, classification=self.classification
        )
        self.source = sync.connector_source(
            self.store,
            connector=self.row,
            partition=partition,
            name=f"fixture {partition}",
            owner_id=self.user,
        )
        self.actor = BuildActor.trusted_local()
        self.operation = 0
        self.sessions = []

    def _probe_source(self) -> str:
        """A throwaway Source only to read the store's default workspace id."""
        if not hasattr(self, "_probe"):
            self._probe = self.store.create_source("text", "workspace probe", {})
        return self._probe

    def reader(self, principal_id=None):
        user = self.store.get_user(principal_id or self.user)
        return Principal.for_user(user, self.store.get_role("individual"))

    def sync(self, **overrides):
        self.operation += 1
        fields = dict(
            connector_id=self.row.id,
            config=self.config,
            partition=self.partition,
            actor=self.actor,
            registry=self.registry,
            options=sync.SyncOptions(emit_workers=2),
            raw_store=self.raw,
            embedding_spec=EmbeddingSpec(),
            operation_id=f"op-{self.operation}",
            should_stop=lambda: False,
        )
        connector = overrides.pop("connector", self.connector_impl)
        return sync.sync_connector(self.ctx, connector, **(fields | overrides))

    # ---------------------------------------------------------- store readers

    def generation(self, generation_id):
        return self.store._generation(generation_id)

    def active(self):
        return self.store.get_source(self.source).get("active_generation_id")

    def rows(self, kind, **scope):
        return list(self.store._knowledge_rows(kind, **scope))

    def sync_state(self):
        identity = k.SyncState(connector_id=self.row.id, partition_key=self.partition).id
        return self.store._knowledge_get("SyncState", identity)

    def sync_run(self):
        identity = k.SyncRun(
            connector_id=self.row.id,
            source_id=self.source,
            scope_key=f"source:{self.source}:{self.partition}",
            run_key=self.partition,
            input_fingerprint=sync.SYNC_RULE_VERSION,
            phase="queued",
        ).id
        return self.store._knowledge_get("SyncRun", identity)

    def artifact_of(self, note_id):
        for artifact in self.rows("Artifact"):
            if artifact.connector_id == self.row.id and artifact.external_id == note_id:
                return artifact
        return None

    def fingerprint(self, generation_id):
        """Section 7.1's byte checks: what an injected failure must leave untouched."""
        gen = self.store._knowledge_get("Generation", generation_id)
        if gen is None:
            return None
        members = sorted(_bytes(row) for row in self.rows("GenerationMember", generation_id=generation_id))
        exact = sorted(
            _bytes(self.store._knowledge_get(row.record_kind, row.record_id))
            for row in self.rows("GenerationEvidenceMember", generation_id=generation_id)
        )
        passages = sorted(
            canonical_json(row) for row in self.store._native_rows("Passage", generation_id=generation_id)
        )
        source = self.store.get_source(self.source)
        return (
            self.store.generation_checksums(generation_id),
            tuple(members),
            tuple(exact),
            tuple(passages),
            source.get("active_generation_id"),
            source.get("status"),
        )

    def epochs(self):
        return (
            self.store.authorization_epoch(),
            self.store.suppression_epoch(),
            self.store.content_epoch() if hasattr(self.store, "content_epoch") else None,
        )

    def open_session(self, principal=None):
        """An open `query_session`, kept past the `with` block so a sync can move under it."""
        manager = query_session(self.ctx, (principal or self.reader()).access)
        session = manager.__enter__()
        self.sessions.append(manager)
        return session

    def close_sessions(self):
        while self.sessions:
            manager = self.sessions.pop()
            try:
                manager.__exit__(None, None, None)
            except BaseException:  # noqa: BLE001 - a refused session is the point of M9
                pass


def _bytes(record) -> str:
    """The canonical serialization of `test_temporal_evidence.py:1338`."""
    return canonical_json({"kind": type(record).__name__, "row": record.model_dump(mode="json")})


@pytest.fixture
def registry():
    with extension_scope() as scoped:
        scoped.register(FIXTURE_EXTENSION, declared_families=("custom",))
        scoped.freeze()
        yield scoped


@pytest.fixture
def ctx(store, tmp_path):
    from hippo.config import Config
    from hippo.context import AppContext

    recorder = RecordingOllama()
    context = AppContext(config=Config(data_dir=tmp_path / "data"), store=store, ollama=recorder.client())
    context.embed_recorder = recorder
    return context


@pytest.fixture
def world(ctx, tmp_path, registry):
    built = World(ctx, tmp_path, registry)
    try:
        yield built
    finally:
        built.close_sessions()


# ------------------------------------------------------------------ the happy path


def test_a_fixture_partition_syncs_through_every_step_and_publishes(world):
    receipt = world.sync()
    assert receipt.outcome == "published"
    assert receipt.pages >= 1 and receipt.changes >= 2
    assert receipt.inventory == "complete"
    assert world.active() == receipt.generation_id
    gen = world.generation(receipt.generation_id)
    assert gen.status == "active" and gen.published_at is not None
    assert world.store.validate_generation_seal(gen.id) is not None
    state = world.sync_state()
    assert json.loads(state.cursor_json)["pending"] is None
    assert state.last_success_at is not None
    run = world.sync_run()
    assert (run.status, run.phase, run.lease_owner) == ("completed", "complete", None)


def test_publication_uses_the_build_authority_and_writes_one_published_index_event(world):
    receipt = world.sync()
    events = [
        event
        for event in world.rows("IndexEvent", generation_id=receipt.generation_id)
        if event.kind == "published"
    ]
    assert len(events) == 1
    assert events[0].aggregate_id == world.source
    assert receipt.build is not None and receipt.build.event_id == events[0].id


def test_the_generation_records_the_registry_fingerprint_outside_its_configuration(world):
    receipt = world.sync()
    gen = world.generation(receipt.generation_id)
    assert gen.registry_fingerprint == world.registry.fingerprint()
    configuration = _configuration(world, gen)
    assert "registry_fingerprint" not in canonical_json(configuration)


def test_the_configuration_carries_the_connector_templates_and_derivation_versions(world):
    receipt = world.sync()
    configuration = _configuration(world, world.generation(receipt.generation_id))
    assert configuration["generation_profile"] == "connector"
    assert configuration["partition"] == world.partition
    assert configuration["connector"]["name"] == "fixture"
    assert configuration["connector"]["templates"]
    assert configuration["derivation"] == {
        "sync": sync.SYNC_RULE_VERSION,
        "binder": emit.BINDER_VERSION,
        "render": sync.RENDER_RULE_VERSION,
        "keys": sync.KEY_RULE_VERSION,
        "classifier": sync.CLASSIFIER_VERSION,
    }
    assert configuration["mapping"]["family"] == "custom"


def _configuration(world, gen) -> dict:
    pointer = json.loads(gen.coverage_json)["embedding_manifest_revision_id"]
    revision = world.store._knowledge_get("ArtifactRevision", pointer)
    return json.loads(revision.metadata_json)["connector_inventory_v1"]["configuration"]


def test_passages_are_embedded_through_ctx_ollama_and_units_are_not(world):
    receipt = world.sync()
    passages = world.store._native_rows("Passage", generation_id=receipt.generation_id)
    units = world.rows("Unit", generation_id=receipt.generation_id)
    assert passages and units
    embedded = world.recorder.embedded
    assert embedded, "passages embed through ctx.ollama"
    for row in passages:
        assert row["text"] in embedded
    unit_only = {unit.embed_text for unit in units} - {row["text"] for row in passages}
    assert not (unit_only & set(embedded)), "units are not embedded (plan section 8.7)"


def test_rendered_facts_are_retrievable_as_derived_passages(world):
    receipt = world.sync()
    views = [
        world.store._knowledge_get("RetrievalView", row.record_id)
        for row in world.rows("GenerationEvidenceMember", generation_id=receipt.generation_id)
        if row.record_kind == "RetrievalView"
    ]
    assert views, "ruling R6: a rendered fact is a derived passage over a view"
    rendered = [
        row
        for row in world.store._native_rows("Passage", generation_id=receipt.generation_id)
        if row.get("retrieval_view_id")
    ]
    assert rendered
    assert any("titled" in row["text"] for row in rendered)


def test_an_unchanged_partition_returns_no_changes_and_builds_nothing(world):
    first = world.sync()
    before = world.fingerprint(first.generation_id)
    generations = len(world.rows("Generation"))
    second = world.sync()
    assert second.outcome == "no_changes"
    assert second.generation_id is None and second.build is None
    assert len(world.rows("Generation")) == generations
    assert world.fingerprint(first.generation_id) == before
    assert world.active() == first.generation_id


def test_a_second_run_with_one_changed_note_publishes_a_child_generation(world):
    first = world.sync()
    world.provider.put_note(_note(body="Changed body text.", updated="2026-09-16T09:00:00Z"))
    second = world.sync()
    assert second.outcome == "published"
    child = world.generation(second.generation_id)
    assert child.parent_id == first.generation_id
    assert world.active() == child.id
    assert world.generation(first.generation_id).status == "retired"


def test_the_sync_lease_is_one_row_per_partition_with_a_monotonic_fence(world):
    world.sync()
    first = world.sync_run()
    world.provider.put_note(_note(body="Another body.", updated="2026-09-17T09:00:00Z"))
    world.sync()
    second = world.sync_run()
    assert [row.id for row in world.rows("SyncRun")] == [first.id]
    assert second.fencing_token > first.fencing_token
    assert second.attempt_count > first.attempt_count


def test_store_classification_writes_only_when_the_value_changes(world):
    before = world.store.authorization_epoch()
    again = sync.store_classification(world.store, connector=world.row, classification=world.classification)
    assert again == world.row
    assert world.store.authorization_epoch() == before
    changed = (
        replace(world.classification)
        if False
        else world.classification.model_copy(update={"connector_version": "2"})
    )
    updated = sync.store_classification(world.store, connector=world.row, classification=changed)
    assert updated.classification_json != world.row.classification_json
    assert world.store.authorization_epoch() > before


def test_a_partition_without_a_stored_classification_is_refused(world):
    with pytest.raises(sync.ConnectorSyncRefused, match="Probe the connector before syncing partition"):
        world.sync(partition="unprobed")


def test_a_disabled_connector_instance_is_refused(world):
    disabled = world.store._knowledge_get("Connector", world.row.id).replace(enabled=False)
    world.store.update_knowledge(disabled)
    with pytest.raises(sync.ConnectorSyncRefused, match="is not enabled"):
        world.sync()


def test_emit_receives_the_stored_mapping(world):
    seen = []
    connector = _SpyConnector(world.connector_impl, seen)
    world.sync(connector=connector)
    stored = sync.load_classification(world.row, world.partition).mapping
    assert seen and all(mapping == stored for _, mapping in seen)


def test_a_reader_actor_is_refused_for_a_connector_sync(world):
    actor = BuildActor.reader(world.reader())
    with pytest.raises(sync.ConnectorSyncRefused, match="trusted local maintenance actor"):
        world.sync(actor=actor)


def test_a_coordinator_lane_connector_is_refused_by_sync_connector(world):
    lane = _LaneConnector(world.connector_impl)
    with pytest.raises(sync.ConnectorSyncRefused, match="syncs through its lane"):
        world.sync(connector=lane)


def test_a_registry_that_is_not_the_frozen_current_registry_is_refused(world):
    other = Registry.with_builtins()
    other.freeze()
    with pytest.raises(sync.ConnectorSyncRefused, match="frozen current registry"):
        world.sync(registry=other)


def test_sync_refuses_a_descriptor_whose_registered_definition_differs(world):
    """Ruling R46 / review m7: each registered definition equals `descriptor.extension`."""
    drifted = _DriftedConnector(world.connector_impl)
    with pytest.raises(sync.ConnectorSyncRefused, match="differs from the registered"):
        world.sync(connector=drifted)


def test_a_connector_source_is_refused_by_the_plain_coordinator(world):
    """Ruling R25: until S5a's switch, `build_plain_source`'s refusal is the guard."""
    from hippo.ingest import prose_generation

    with pytest.raises(Exception) as caught:
        prose_generation.build_plain_source(
            world.ctx,
            source_id=world.source,
            actor=world.actor,
            inputs=(),
            options=prose_generation.PlainBuildOptions(),
            raw_store=world.raw,
            embedding_spec=EmbeddingSpec(),
            operation_id="plain",
            should_stop=lambda: False,
        )
    assert not isinstance(caught.value, AssertionError)


def test_on_batch_sees_each_revision_outside_transactions_and_the_guard(world):
    seen = []

    def on_batch(revision, batch):
        assert not world.store.in_ambient_transaction()
        assert time.time() > 0  # the guard is the worker thread's, never the caller's
        seen.append((revision.artifact.external_id, len(batch.nodes)))

    world.sync(on_batch=on_batch)
    assert len(seen) >= 2
    assert all(count >= 1 for _, count in seen)


def test_every_fault_point_label_is_reachable(world):
    labels = []
    world.sync(fault_hook=labels.append)
    assert set(labels) <= set(sync.FAULT_POINTS)
    # The two in-transaction labels and the publication labels all fire on a clean run.
    assert {"lease", "after_page", "after_fetch", "before_checkpoint", "after_checkpoint"} <= set(labels)
    assert {"after_emit", "after_bind", "after_install", "before_batch", "before_seal"} <= set(labels)
    assert {"before_publish", "after_publish"} <= set(labels)
    assert set(labels) == set(sync.FAULT_POINTS)


def test_no_production_module_passes_fault_hook_to_sync_connector():
    root = Path(__file__).resolve().parents[2] / "src" / "hippo"
    offenders = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        # The kit is the sanctioned second caller: design section 8's runtime scenarios inject at
        # `after_fetch` and `after_checkpoint` through `testing.scratch_sync` (R49 / review B4).
        if path.relative_to(root).as_posix() not in ("connectors/sync.py", "connectors/testing.py")
        and "fault_hook" in path.read_text(encoding="utf-8")
        and "sync_connector" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_the_fixture_connector_constructs_with_no_arguments():
    """Ruling R60 / R-S3-7: the kit builds it with no arguments and reads `fixtures/basic`."""
    connector = FixtureConnector()
    assert connector.descriptor.capabilities.inventory is True
    assert connector.descriptor.capabilities.acls is True
    # `changes.json` holds one `ChangePage` per page, the kit's documented layout (S4 section 3.1),
    # so the pages are read from the case file rather than through the provider's page list.
    pages = json.loads((CASE / "changes.json").read_text(encoding="utf-8"))["pages"]
    upserts = [change for page in pages for change in page["changes"] if change["operation"] == "upsert"]
    assert len(upserts) >= 2


def test_a_fetch_of_an_absent_id_raises_provider_not_found(world):
    """Review M15: the deletion confirmation of section 6.4 needs this exact class."""
    ref = base.ExternalRef(partition=world.partition, artifact_kind="document", external_id="missing")
    with pytest.raises(provider_http.ProviderNotFoundError):
        world.connector_impl.fetch(world.config, ref)


def test_a_probe_samples_through_list_changes_and_fetch(world):
    """Ruling R60: the probe's provider traffic is exactly `list_changes` and `fetch`."""
    world.provider.requests.clear()
    world.connector_impl.probe(world.config, world.store._now)
    assert any("/changes" in path for path in world.provider.requests)
    assert any("/notes/" in path for path in world.provider.requests)
    assert not any(path.endswith("/acl") for path in world.provider.requests)


def test_the_registry_is_loaded_before_a_lifecycle_write(world):
    """Ruling R66(i): closing a recorded interval is vocabulary-checked."""
    world.sync()
    world.provider.put_note(_note(body="Body three.", updated="2026-09-18T09:00:00Z"))
    second = world.sync()
    version = next(
        world.store._knowledge_get(row.record_kind, row.record_id)
        for row in world.rows("GenerationEvidenceMember", generation_id=second.generation_id)
        if row.record_kind == "AssertionVersion"
    )
    bare = Registry.with_builtins()
    bare.freeze()
    with use_registry(bare):
        with pytest.raises(ValueError):
            world.store.put_knowledge(version.replace(confidence=0.5))
    # Under the loaded registry the same write is admitted by `check_record`.
    world.registry.check_record(version)


def test_a_collected_connector_generation_leaves_its_published_versions_readable(world):
    """Ruling R68(3) / R66(ii): a tombstoned version outlives its generation's units.

    Collection deletes a generation's `Unit` rows and keeps the exact membership of an
    ever-published one, so a version that still names `unit_id` has a dangling reference. The
    store's reference check is what would refuse the next lifecycle write on it, which is why
    `unit_id` is exempt from it.
    """
    first = world.sync()
    world.provider.put_note(_note(body="Body four.", updated="2026-09-19T09:00:00Z"))
    second = world.sync()
    versions = [
        world.store._knowledge_get(row.record_kind, row.record_id)
        for row in world.rows("GenerationEvidenceMember", generation_id=first.generation_id)
        if row.record_kind == "AssertionVersion"
    ]
    assert versions and all(version.unit_id for version in versions)
    result = world.store.collect_generation(first.generation_id)
    assert result.blocked_reason is None
    assert not world.rows("Unit", generation_id=first.generation_id)
    for version in versions:
        stored = world.store._knowledge_get("AssertionVersion", version.id)
        assert stored == version
        assert world.store._knowledge_get("Unit", stored.unit_id) is None
        # The exemption: without it this refuses with "Missing Unit reference".
        world.store._validate_knowledge(stored)
    assert world.store.generation_checksums(second.generation_id)


def test_a_template_version_bump_rebuilds_an_unchanged_partition(world, ctx, tmp_path):
    """Review M4: `no_changes` is decided after the candidate generation."""
    first = world.sync()
    bumped = _bumped_extension()
    scoped = Registry.with_builtins()
    scoped.register(bumped, declared_families=("custom",))
    scoped.freeze()
    with use_registry(scoped):
        world.registry = scoped
        world.connector_impl = FixtureConnector(world.provider, descriptor_extension=bumped)
        receipt = world.sync()
    assert receipt.outcome == "published"
    assert world.generation(receipt.generation_id).parent_id == first.generation_id


# ------------------------------------------------------------------ the failure matrix


def _m1(world):
    before_rows = _capture_rows(world)
    with pytest.raises(_Injected):
        world.sync(fault_hook=_raise_at("after_fetch"))
    assert _capture_rows(world) == before_rows
    # The lease creates the cursor row; what a failed page must not move is its cursor.
    assert _cursor(world) == {"cursor": None, "pending": None}
    clean = world.sync()
    assert clean.outcome == "published"


def _m2(world):
    before_rows = _capture_rows(world)
    with pytest.raises(_Injected):
        world.sync(fault_hook=_raise_at("before_checkpoint"))
    assert _capture_rows(world) == before_rows
    assert _cursor(world) == {"cursor": None, "pending": None}
    assert world.sync().outcome == "published"


def _m3(world):
    with pytest.raises(_Injected):
        world.sync(fault_hook=_raise_at("after_checkpoint"))
    cursor = _cursor(world)
    epoch = world.store.authorization_epoch()
    rows = set(_capture_rows(world))
    observed = []
    receipt = world.sync(
        fault_hook=lambda label: (
            observed.append(world.store.authorization_epoch()) if label == "after_checkpoint" else None
        )
    )
    assert receipt.outcome == "published"
    # The replayed page re-put identical bytes: every row it wrote the first time is still there
    # byte for byte, and the checkpoint that replayed it moved no authorization epoch. The
    # publication that follows legitimately does, which is why the epoch is read at the
    # checkpoint rather than at the end of the run.
    assert rows <= set(_capture_rows(world))
    assert observed and observed[0] == epoch
    assert cursor["cursor"] is not None


def _m4(world):
    world.provider.repeat_first_page = True
    receipt = world.sync()
    assert receipt.outcome == "published"
    ids = [artifact.id for artifact in world.rows("Artifact") if artifact.connector_id == world.row.id]
    assert len(ids) == len(set(ids))


def _m5(world):
    world.sync()
    world.provider.fail_page(1, 503)
    with pytest.raises(provider_http.ProviderTransientError):
        world.sync(options=sync.SyncOptions(reconcile=True, emit_workers=1))
    assert not [a for a in world.rows("Artifact") if a.deleted_at is not None]
    scan = json.loads(world.sync_state().cursor_json)["scan"]
    assert scan is not None and scan["complete"] is False
    world.provider.clear_failures()
    assert world.sync(options=sync.SyncOptions(reconcile=True, emit_workers=1)).inventory == "complete"


def _m6(world):
    world.sync()
    receipt = world.sync(
        options=sync.SyncOptions(reconcile=True, max_pages=1, emit_workers=1),
    )
    assert receipt.inventory == "partial"
    assert not [a for a in world.rows("Artifact") if a.deleted_at is not None]


def _m7(world):
    world.sync()
    world.provider.hide_note("n2")
    receipt = world.sync(options=sync.SyncOptions(reconcile=True, emit_workers=1))
    assert receipt.deleted == 1
    assert world.artifact_of("n2").deleted_at is not None
    assert world.artifact_of("n1").deleted_at is None


def _m8(world):
    first = world.sync()
    world.provider.set_policy("n1", {"state": "known", "mode": "restricted", "allow_users": ["nobody"]})
    world.provider.push_changes([{"operation": "policy_change", "external_id": "n1"}])
    second = world.sync()
    assert second.outcome == "published"
    assert second.policy_updates >= 1
    assert world.generation(first.generation_id).status == "retired"


def _m8b(world):
    first = world.sync()
    original = world.artifact_of("n1").policy_id
    spans = _span_policies(world, first.generation_id)
    assert _revision_span_policy(world, "n1") == original
    world.provider.set_policy("n1", {"state": "known", "mode": "restricted", "allow_users": ["nobody"]})
    world.provider.push_changes([{"operation": "policy_change", "external_id": "n1"}])
    second = world.sync()
    assert second.outcome == "published"
    # Narrowing takes effect at the checkpoint, on the artifact...
    narrowed = world.artifact_of("n1").policy_id
    assert narrowed != original
    # ...and every stored span keeps the policy of its revision's first capture (ruling R48).
    assert _span_policies(world, first.generation_id) == spans
    assert _revision_span_policy(world, "n1") == original
    assert original in _span_policies(world, second.generation_id)
    assert narrowed not in _span_policies(world, second.generation_id)
    # Widening waits for a new revision, and reaches it because capture records the policy again.
    world.provider.set_policy("n1", {"state": "known", "mode": "workspace"})
    world.provider.put_note(_note(body="Widened body.", updated="2026-09-20T09:00:00Z"))
    third = world.sync()
    assert third.outcome == "published"
    widened = world.artifact_of("n1").policy_id
    assert _revision_span_policy(world, "n1") == widened
    assert widened in _span_policies(world, third.generation_id)
    assert _span_policies(world, first.generation_id) == spans


def _m9(world):
    first = world.sync()
    session = world.open_session()
    world.provider.delete_note("n2")
    second = world.sync()
    assert second.outcome == "published"
    with pytest.raises(AuthorizationChanged, match="Permissions changed"):
        session.validate()
    assert world.open_session() is not None
    blocked = world.store.collect_generation(first.generation_id)
    assert blocked.blocked_reason in (None, "snapshot_reference")


def _m10(world):
    for factory in _GUARD_VIOLATIONS:
        violator = _ViolatingConnector(world.connector_impl, factory)
        before = world.rows("Generation")
        with pytest.raises(sync.ConnectorContractViolation):
            world.sync(connector=violator)
        assert world.rows("Generation") == before


def _m10b(world):
    """CK7 F1: neither way of swallowing the refusal lets the sync publish.

    `except Exception` no longer catches an `EmitSideEffect` at all, so the first forbidden call
    fails the sync where it stands. `except BaseException` still catches it, the rest of that emit
    runs unguarded, and the guard raises the refusal it recorded on the way out. Either way the
    violation reported is the *first* forbidden call, not the second.
    """
    for catching, reaches_the_second_call in ((Exception, False), (BaseException, True)):
        swallowing = _SwallowingConnector(world.connector_impl, catching)
        before = world.rows("Generation")
        with pytest.raises(sync.ConnectorContractViolation, match="Ollama.embed_one"):
            world.sync(connector=swallowing)
        assert swallowing.reached_the_second_call is reaches_the_second_call
        assert world.rows("Generation") == before


def _m11(world):
    """A revision-level emit failure is counted, and R37's DV1 decides what happens to its records.

    Review CK7 finding F14: the design read "the previous revision's records stay", which DV1 - every
    member revision re-emitted, nothing carried forward - contradicts. A clean generation comes
    first, so the failing revision has records to lose; the second sync is provoked by a change to a
    *different* note, so n2 itself is unchanged and is re-emitted only because DV1 says so. Its
    records are absent from the new generation, and it is the previous *generation* that stays
    queryable, records and all.
    """
    clean = world.sync(connector=_FailingEmitConnector(world.connector_impl, "never-matches"))
    assert clean.outcome == "published"
    assert clean.coverage["emit_failed"] == {}
    before = _unit_texts(world, clean.generation_id)
    assert any("/n2" in text for text in before)

    # The change is to the *other* note, so n2 is unchanged and is re-emitted only because DV1
    # re-emits every member revision. Its emit is what fails.
    world.provider.put_note(_note(body="A change to the other note.", updated="2026-09-22T09:00:00Z"))
    failing = _FailingEmitConnector(world.connector_impl, "n2")
    second = world.sync(connector=failing)
    assert second.outcome == "published"
    assert second.coverage["emit_failed"] == {FIXTURE_FAMILY: 1}

    # DV1: n2 is still a member of the new generation, and holds no record in it.
    members = {
        row.artifact_revision_id for row in world.rows("GenerationMember", generation_id=second.generation_id)
    }
    n2_revision = _revision_of(world, "n2")
    assert n2_revision in members
    assert not any("/n2" in text for text in _unit_texts(world, second.generation_id))

    # The previous generation is what stays queryable, with every record it was published with.
    assert _unit_texts(world, clean.generation_id) == before
    assert world.store.collect_generation(clean.generation_id).blocked_reason in (
        None,
        "snapshot_reference",
    )


def _m11b(world):
    """CK7 F15: the counted family is the revision's classification, not the first declared one."""
    failing = _TwoFamilyFailingConnector(world.connector_impl, "n2")
    assert failing.descriptor.families[0] == "service"
    receipt = world.sync(connector=failing)
    assert receipt.outcome == "published"
    assert receipt.coverage["emit_failed"] == {FIXTURE_FAMILY: 1}


def _m12(world, monkeypatch):
    calls = {"n": 0}
    real = staged_records._write_batch

    def crashing(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 2:
            raise _Injected("batch")
        return real(*args, **kwargs)

    monkeypatch.setattr(staged_records, "_write_batch", crashing)
    with pytest.raises(_Injected):
        world.sync(options=sync.SyncOptions(batch_size=1, emit_workers=1))
    monkeypatch.setattr(staged_records, "_write_batch", real)
    receipt = world.sync(options=sync.SyncOptions(batch_size=1, emit_workers=1))
    assert receipt.outcome == "published"
    assert receipt.build.resumed_from_batches > 0


def _m13(world):
    with pytest.raises(_Injected):
        world.sync(fault_hook=_raise_at("before_seal"))
    assert world.active() is None
    with pytest.raises(_Injected):
        world.sync(fault_hook=_raise_at("before_publish"))
    published = [row for row in world.rows("IndexEvent") if row.kind == "published"]
    assert published == []
    assert world.sync().outcome == "published"


def _m14(world):
    with pytest.raises(_Injected):
        world.sync(fault_hook=_raise_at("after_publish"))
    active = world.active()
    assert active is not None
    receipt = world.sync(operation_id=f"op-{world.operation}")
    assert receipt.outcome in ("already_published", "no_changes")


def _m15(world):
    first = world.sync()
    world.provider.put_note(_note(body="Compare and swap.", updated="2026-09-21T09:00:00Z"))

    def steal(label):
        if label == "before_publish":
            # A foreign publication moved the source's active pointer under this attempt, after
            # the guard's local check and before the compare-and-swap reads it.
            world.store._source_fields(world.source, active_generation_id=None)

    with pytest.raises(ValueError, match="compare-and-swap failed"):
        world.sync(fault_hook=steal)
    world.store._source_fields(world.source, active_generation_id=first.generation_id)
    assert world.sync().outcome == "published"


def _m16(world):
    started, release = threading.Event(), threading.Event()
    result = {}

    def hold(label):
        if label == "lease":
            started.set()
            release.wait(10)

    def run():
        try:
            world.sync(fault_hook=hold)
        except BaseException as error:  # noqa: BLE001 - recorded for the assertion
            result["error"] = error

    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert started.wait(10)
        with pytest.raises(sync.ConnectorSyncBusy):
            world.sync()
    finally:
        release.set()
        worker.join(30)


def _m17(world):
    def steal(label):
        if label == "after_page":
            _advance_fence(world)

    with pytest.raises(sync.ConnectorSyncBusy, match="Sync lease was lost"):
        world.sync(fault_hook=steal)
    assert not [a for a in world.rows("Artifact") if a.connector_id == world.row.id]


def _m18(world):
    stop = {"now": False}

    def hook(label):
        if label == "after_page":
            stop["now"] = True

    with pytest.raises(sync.ConnectorSyncCancelled):
        world.sync(fault_hook=hook, should_stop=lambda: stop["now"])


def _m19(world):
    from hippo.knowledge import source_lifecycle

    first = world.sync().generation_id
    world.provider.put_note(_note(body="Tombstone body.", updated="2026-09-22T09:00:00Z"))

    def withdraw(label):
        if label == "before_seal":
            source_lifecycle.tombstone_managed_source(
                world.ctx, source_id=world.source, actor=world.actor, operation_id="retire"
            )

    with pytest.raises((ValueError, AuthorizationChanged)):
        world.sync(fault_hook=withdraw)
    # The tombstone withdraws G1; nothing deleted it, and its rows are still there.
    assert world.store._knowledge_get("Generation", first) is not None


def _m20(world, monkeypatch):
    forbidden = []
    for name in (
        "discard_generation",
        "collect_generation",
        "_clear_passages",
        "delete_passages_for_source",
        "delete_code_nodes_for_source",
    ):
        original = getattr(type(world.store), name, None)
        if original is None:
            continue

        def spy(self, *args, _name=name, _original=original, **kwargs):
            forbidden.append(_name)
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(type(world.store), name, spy)
    world.sync()
    world.provider.put_note(_note(body="Spy body.", updated="2026-09-23T09:00:00Z"))
    world.sync()
    world.provider.put_note(_note(body="Spy body two.", updated="2026-09-23T10:00:00Z"))
    with pytest.raises(_Injected):
        world.sync(fault_hook=_raise_at("before_publish"))
    # Review m13: M20 counts only the runtime's own calls, so this row makes none of its own
    # (M9's test makes one `collect_generation` call on purpose, which is not the runtime's).
    assert forbidden == []


def _m21(world):
    world.sync()
    before = world.store.authorization_epoch()
    session = world.open_session()
    world.provider.push_changes([{"operation": "upsert", "external_id": "n1"}])
    second = world.sync()
    assert second.outcome in ("no_changes", "already_current")
    assert world.store.authorization_epoch() == before
    session.validate()


def _m22(world):
    """Review m16: between first capture and first publication the Source serves nothing."""
    with pytest.raises(_Injected):
        world.sync(fault_hook=_raise_at("after_checkpoint"))
    assert [row for row in world.rows("Artifact") if row.connector_id == world.row.id]
    assert world.active() is None
    session = world.open_session()
    session.validate()
    assert not [row for row in world.store._native_rows("Passage") if row.get("source_id") == world.source]


_MATRIX = {
    "M1": _m1,
    "M2": _m2,
    "M3": _m3,
    "M4": _m4,
    "M5": _m5,
    "M6": _m6,
    "M7": _m7,
    "M8": _m8,
    "M8b": _m8b,
    "M9": _m9,
    "M10": _m10,
    "M10b": _m10b,
    "M11": _m11,
    "M11b": _m11b,
    "M12": _m12,
    "M13": _m13,
    "M14": _m14,
    "M15": _m15,
    "M16": _m16,
    "M17": _m17,
    "M18": _m18,
    "M19": _m19,
    "M20": _m20,
    "M21": _m21,
    "M22": _m22,
}


@pytest.mark.parametrize("row", list(_MATRIX))
def test_the_failure_matrix(world, monkeypatch, row):
    case = _MATRIX[row]
    if case.__code__.co_argcount == 2:
        case(world, monkeypatch)
    else:
        case(world)


# ------------------------------------------------------------------ LadybugDB reopen


@pytest.mark.skipif(
    os.environ.get("HIPPO_TEST_STORE", "").lower() != "ladybug", reason="LadybugDB reopen proof"
)
def test_the_last_published_generation_survives_ladybug_close_and_reopen_after_a_failed_sync(world, tmp_path):
    first = world.sync()
    before = world.fingerprint(first.generation_id)
    world.provider.put_note(_note(body="Reopen body.", updated="2026-09-24T09:00:00Z"))
    with pytest.raises(_Injected):
        world.sync(fault_hook=_raise_at("before_publish"))
    path = world.store.path
    world.store.close()
    from hippo.store.ladybug import LadybugStore

    reopened = LadybugStore(path)
    try:
        assert reopened.get_source(world.source).get("active_generation_id") == first.generation_id
        assert reopened.generation_checksums(first.generation_id) == before[0]
    finally:
        reopened.close()


# ------------------------------------------------------------------ helpers


class _Injected(RuntimeError):
    """The exception a test's `fault_hook` raises."""


def _raise_at(label: str):
    def hook(fired: str) -> None:
        if fired == label:
            raise _Injected(label)

    return hook


def _unit_texts(world, generation_id) -> list[str]:
    return sorted(unit.text for unit in world.rows("Unit", generation_id=generation_id))


def _revision_of(world, external_id: str) -> str:
    artifact = world.artifact_of(external_id)
    revisions = [row for row in world.rows("ArtifactRevision") if row.artifact_id == artifact.id]
    assert len(revisions) == 1, revisions
    return revisions[0].id


def _note(*, body: str, updated: str, note_id: str = "n1", links=("n2",)) -> dict:
    """A replacement note. The link is kept, so the child generation still holds an assertion."""
    return {
        "id": note_id,
        "title": "First note" if note_id == "n1" else "Second note",
        "body": body,
        "updated": updated,
        "links": list(links),
        "same_as": [],
    }


def _revision_span_policy(world, external_id: str) -> str:
    """The policy the newest stored revision of a note was first captured under (ruling R48)."""
    artifact = world.artifact_of(external_id)
    revisions = world.store._knowledge_rows("ArtifactRevision", where={"artifact_id": artifact.id})
    newest = max(revisions, key=lambda row: (row.observed_at, row.id))
    return json.loads(newest.metadata_json)["span_policy_id"]


def _cursor(world) -> dict:
    """The parts of `SyncState.cursor_json` a failed page must leave untouched."""
    stored = json.loads(world.sync_state().cursor_json)
    return {"cursor": stored.get("cursor"), "pending": stored.get("pending")}


def _capture_rows(world):
    return tuple(
        sorted(
            _bytes(row)
            for kind in ("Artifact", "ArtifactRevision", "AccessPolicy")
            for row in world.rows(kind)
        )
    )


def _span_policies(world, generation_id):
    return {
        world.store._knowledge_get("EvidenceSpan", row.record_id).policy_id
        for row in world.rows("GenerationEvidenceMember", generation_id=generation_id)
        if row.record_kind == "EvidenceSpan"
    }


def _advance_fence(world):
    run = world.sync_run()
    world.store.update_knowledge(
        run.replace(
            lease_owner="another-holder",
            lease_expires_at=world.store._now() + timedelta(seconds=300),
            fencing_token=run.fencing_token + 1,
            status="running",
        )
    )


def _bumped_extension():
    kind = FIXTURE_EXTENSION.object_kinds[0]
    template = kind.fact_templates[0]
    bumped = kind.model_copy(update={"fact_templates": (template.model_copy(update={"version": "2"}),)})
    return FIXTURE_EXTENSION.model_copy(update={"object_kinds": (bumped,)})


class _Delegating:
    """A connector that forwards every call to the fixture connector it wraps."""

    def __init__(self, inner):
        self._inner = inner
        self.descriptor = inner.descriptor

    def probe(self, config, clock):
        return self._inner.probe(config, clock)

    def list_changes(self, config, cursor):
        return self._inner.list_changes(config, cursor)

    def fetch(self, config, ref):
        return self._inner.fetch(config, ref)

    def fetch_policy(self, config, ref):
        return self._inner.fetch_policy(config, ref)

    def emit(self, revision, mapping):
        return self._inner.emit(revision, mapping)


class _SpyConnector(_Delegating):
    def __init__(self, inner, seen):
        super().__init__(inner)
        self._seen = seen

    def emit(self, revision, mapping):
        self._seen.append((revision.artifact.external_id, mapping))
        return self._inner.emit(revision, mapping)


class _LaneConnector(_Delegating):
    def __init__(self, inner):
        super().__init__(inner)
        self.descriptor = inner.descriptor.model_copy(
            update={
                "capabilities": inner.descriptor.capabilities.model_copy(
                    update={"derivation": "coordinator_lane"}
                )
            }
        )


class _DriftedConnector(_Delegating):
    def __init__(self, inner):
        super().__init__(inner)
        drifted = _bumped_extension()
        self.descriptor = inner.descriptor.model_copy(update={"extension": drifted})


class _TwoFamilyFailingConnector(_Delegating):
    """CK7 F15: two declared families, the partition classified as the *second* of them.

    The count of a revision-level emit failure used to land on `descriptor.families[0]`, which on
    this connector is the family the failing revision has nothing to do with.
    """

    def __init__(self, inner, external_id):
        super().__init__(inner)
        self.descriptor = inner.descriptor.model_copy(update={"families": ("service", FIXTURE_FAMILY)})
        self._external_id = external_id

    def emit(self, revision, mapping):
        if revision.artifact.external_id == self._external_id:
            raise ValueError("this revision cannot be parsed")
        return self._inner.emit(revision, mapping)


class _FailingEmitConnector(_Delegating):
    def __init__(self, inner, external_id):
        super().__init__(inner)
        self._external_id = external_id

    def emit(self, revision, mapping):
        if revision.artifact.external_id == self._external_id:
            raise ValueError("this revision cannot be parsed")
        return self._inner.emit(revision, mapping)


_IDLE_TRANSPORT = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
_IDLE_OLLAMA = Ollama(
    "http://guard.invalid",
    "chat:latest",
    "embed:latest",
    client=httpx.Client(base_url="http://guard.invalid", transport=_IDLE_TRANSPORT),
)


def _violate_socket():
    import socket

    sock = socket.socket()
    try:
        sock.connect_ex(("127.0.0.1", 9))
    finally:
        sock.close()


def _violate_httpx():
    with httpx.Client(transport=_IDLE_TRANSPORT) as client:
        client.get("http://guard.invalid/")


def _violate_ollama():
    _IDLE_OLLAMA.embed_one("text")


def _violate_subprocess():
    subprocess.run([sys.executable, "-c", "pass"], check=False)


def _violate_thread():
    threading.Thread(target=lambda: None).start()


def _violate_time():
    time.time()


def _violate_datetime():
    datetime.now(UTC)


_GUARD_VIOLATIONS = (
    _violate_socket,
    _violate_httpx,
    _violate_ollama,
    _violate_subprocess,
    _violate_thread,
    _violate_time,
    _violate_datetime,
)


class _ViolatingConnector(_Delegating):
    def __init__(self, inner, violation):
        super().__init__(inner)
        self._violation = violation

    def emit(self, revision, mapping):
        self._violation()
        return self._inner.emit(revision, mapping)


class _SwallowingConnector(_Delegating):
    """CK7 F1: an `emit` carrying the ordinary broad `except` a third-party connector may well have.

    It makes a second forbidden call after the first was refused, which CPython leaves unguarded
    because it unset the profiler when the hook raised.
    """

    def __init__(self, inner, catching):
        super().__init__(inner)
        self._catching = catching
        self.reached_the_second_call = False

    def emit(self, revision, mapping):
        try:
            _IDLE_OLLAMA.embed_one("text")
        except self._catching:  # the connector's own retry
            pass
        self.reached_the_second_call = True
        time.time()
        return self._inner.emit(revision, mapping)


def test_the_record_bundle_stages_alias_candidates(store):
    """Ruling R68(1): alias candidates are part of an emission batch, so the writer stages them.

    S2b's binder turns an `AliasEmission` into a `SAME_OBJECT_AS` assertion and writes no `Alias`
    row, so nothing in S3c fills the field; the bundle carries it so that a connector that does
    needs no change to the writer. The hand-built connector generation is S3b's fixture, imported
    rather than copied so one such world exists in the tree.
    """
    from tests.unit import test_staged_records as fixtures

    built = fixtures.world(store)
    bundle = fixtures.bundle_of(built)
    target, span = bundle.objects[0], bundle.spans[0]

    def with_alias(**overrides):
        fields = {
            "workspace_id": target.workspace_id,
            "namespace": "fixture",
            "alias_key": "alpha",
            "target_object_id": target.id,
            "authority": "connector",
            "support_span_ids": (span.id,),
            "status": "candidate",
        }
        alias = k.Alias(**(fields | overrides))
        member = k.GenerationEvidenceMember(
            generation_id=bundle.generation.id, record_kind="Alias", record_id=alias.id
        )
        return replace(bundle, aliases=(alias,), evidence_members=(*bundle.evidence_members, member))

    staged = with_alias()
    assert staged.scoped[-1] == staged.aliases[0]
    groups = list(staged_records._groups(staged))
    assert groups[-1].records[0] == staged.aliases[0]
    with pytest.raises(ValueError, match="references a missing KnowledgeObject"):
        with_alias(target_object_id="object-" + "0" * 64)
    with pytest.raises(ValueError, match="references a missing EvidenceSpan"):
        with_alias(support_span_ids=("span-" + "0" * 64,))


def test_sqlite_is_not_used_by_the_runtime():
    """A guard against an accidental second persistence path; the store is the store."""
    assert sqlite3 is not None
    assert "sqlite3" not in Path(sync.__file__).read_text(encoding="utf-8")


def test_the_runtime_never_deletes_the_active_generation():
    source = Path(sync.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "discard_generation",
        "collect_generation",
        "_clear_passages",
        "delete_passages_for_source",
        "delete_code_nodes_for_source",
    ):
        assert forbidden not in source


def test_the_documented_dangling_unit_note_is_present():
    """Ruling R66(ii): `sync.py` documents that a tombstoned version's unit may dangle."""
    source = Path(sync.__file__).read_text(encoding="utf-8")
    assert "unit_id" in source and "collect" in source


# ------------------------------------------------------------------ F5: ensure_connector's enabled


def test_re_ensuring_a_connector_leaves_its_enabled_flag_alone_unless_asked(world):
    """CK7 F5: `enabled=False` as the default wrote a disable into every configuration change.

    R51 is unchanged - a new instance is created disabled - but `None` now means "do not decide",
    so re-ensuring an instance to change its configuration no longer silently turns it off. `True`
    and `False` stay explicit.
    """
    fields = {
        "workspace_id": world.row.workspace_id,
        "kind": "fixture",
        "instance_url": world.instance,
    }
    assert world.store._knowledge_get("Connector", world.row.id).enabled is True

    # A configuration change with no opinion about enablement keeps the row enabled.
    changed = FixtureConfig(instance_url=world.instance, partition="a-different-partition")
    reensured = sync.ensure_connector(world.store, config=changed, **fields)
    assert reensured.enabled is True
    assert reensured.config_json == changed.model_dump_json()

    # `False` is still a way to say it, and `None` then leaves the row disabled.
    assert sync.ensure_connector(world.store, config=changed, enabled=False, **fields).enabled is False
    assert sync.ensure_connector(world.store, config=changed, **fields).enabled is False
    assert sync.ensure_connector(world.store, config=changed, enabled=True, **fields).enabled is True


def test_a_new_connector_instance_is_created_disabled_whether_or_not_enabled_is_passed(world):
    """R51/M5 unchanged: the default creates a disabled row, it just no longer disables an old one."""
    fields = {"workspace_id": world.row.workspace_id, "kind": "fixture"}
    config = FixtureConfig(instance_url="https://second.invalid", partition=world.partition)

    defaulted = sync.ensure_connector(
        world.store, instance_url="https://second.invalid", config=config, **fields
    )
    assert defaulted.enabled is False

    third = FixtureConfig(instance_url="https://third.invalid", partition=world.partition)
    explicit = sync.ensure_connector(
        world.store, instance_url="https://third.invalid", config=third, enabled=False, **fields
    )
    assert explicit.enabled is False


def test_a_failure_counted_without_a_classified_family_is_counted_as_unknown():
    """CK7 F15's fallback: `unknown` rather than a family that did not fail.

    Every target built by `sync_connector` carries a validated `TypeMapping`, so this is the answer
    for a target that reached the counter without one - which is why it is a named string and not
    `descriptor.families[0]`.
    """
    assert sync._failure_family(SimpleNamespace(mapping=None)) == "unknown"
    assert sync._failure_family(SimpleNamespace(mapping=SimpleNamespace(family=""))) == "unknown"
    assert sync._failure_family(SimpleNamespace(mapping=SimpleNamespace(family="db"))) == "db"
