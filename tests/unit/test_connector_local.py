"""The local connector, the coordinator lane, and the prose path's byte-identity proof.

Gate CK5, plan `ai_docs/plans/cdk-s5-port.md` sections 3, 4.1, 5, 6 and 8 (S5a), with rulings
R1 (the coordinator lane), R2 (`prose_generation.py` is S5a's), R5 (no `Connector` or
`SyncState` row), R43 (`kind="connector"` is refused by dispatch), R54 (the one `ingest` to
`connectors` import edge) and m9 (`SyncConnector`, `capabilities.derivation`,
`current_registry()`, a `mode="workspace"` policy observation).

The proof is two worlds on two fresh stores, run one after the other: world A is the pre-kit
coordinator call `run_managed_build` made at `2a9913a`, world B is the runtime path. Their
published generations must agree everywhere `tests/fakes/connector_parity.py` compares them,
with `Generation.registry_fingerprint` the single allowed difference.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import httpx
import pytest

from hippo.ingest import managed_activation, pipeline
from hippo.knowledge.registry import Registry, TypeExtension, current_registry
from tests.fakes import connector_parity as parity
from tests.unit.test_connector_git import published_vocabulary


def lanes():
    try:
        return importlib.import_module("hippo.connectors.lanes")
    except ModuleNotFoundError:
        pytest.fail("The coordinator lane module hippo.connectors.lanes is missing")


def local():
    try:
        return importlib.import_module("hippo.connectors.local.connector")
    except ModuleNotFoundError:
        pytest.fail("The local connector module hippo.connectors.local.connector is missing")


def connector():
    return local().LocalConnector()


def config(**fields):
    return local().LocalSourceConfig(**fields)


# ------------------------------------------------------------------ the worlds


def _stage_text(world, text: str) -> str:
    return pipeline.add_text(world.ctx, "Notes", text, owner_id=world.user, build_actor=world.actor)


def _stage_upload(world, filename: str, data: bytes) -> str:
    return pipeline.add_upload(world.ctx, filename, data, owner_id=world.user, build_actor=world.actor)


def _pre_kit(world, source_id: str):
    """Which pre-kit branch world A is: the saved Source row decides, as the dispatch does.

    S5b's archive and code-file worlds reach the code coordinator, so the descriptor pin can
    cover every kind the local connector declares (ruling R72).
    """
    source = world.ctx.store.get_source(source_id)
    if managed_activation.is_code_source(source):
        return parity.pre_kit_code_build
    return parity.pre_kit_prose_build


def _drive(world, source_id: str, *, runtime: bool, operation_id: str | None = None):
    """One managed build of `source_id`, through the world's own path and one operation identity.

    World A calls the coordinator with the arguments `run_managed_build` built at `2a9913a`;
    world B calls `run_managed_build`, which is the call `pipeline._run_managed_indexing` makes.
    A published runtime build must carry the process registry's fingerprint, and that assertion
    is what separates the two worlds before the switch lands.
    """
    if runtime:
        assert managed_activation.run_coordinator_lane is lanes().run_coordinator_lane, (
            "world B is not the runtime path: the dispatch does not hold the coordinator lane"
        )
    operation_id = operation_id or managed_activation.new_operation_id()
    call = parity.runtime_prose_build if runtime else _pre_kit(world, source_id)
    kwargs = {} if runtime else {"job_key": pipeline.job_key(source_id)}
    receipt = call(world.ctx, source_id=source_id, actor=world.actor, operation_id=operation_id, **kwargs)
    if runtime and receipt.outcome == "published":
        row = world.ctx.store._knowledge_get("Generation", receipt.generation_id)
        assert row.registry_fingerprint == current_registry().fingerprint(), (
            "the runtime path published without the registry fingerprint"
        )
    return receipt


def _first(world, source_id: str, *, runtime: bool):
    """The first build, on the identity `add_text`/`add_upload`'s own dispatch minted."""
    return _drive(world, source_id, runtime=runtime, operation_id=world.operations[0])


def _snapshot(world, receipt):
    return parity.published_snapshot(world.ctx, receipt.generation_id, receipt)


def run_worlds(tmp_path: Path, scenario, **config_fields):
    """Run `scenario` in the pre-kit world, then in the runtime world, and return both results.

    Sequential by design: a backend may serve one database per process, so world A's snapshot
    is taken and its store closed before world B opens. Jobs are held in both worlds, so each
    build is one explicit call and the two worlds mint the same operation identities.
    """
    results = []
    for name, runtime in (("pre_kit", False), ("runtime", True)):
        with pytest.MonkeyPatch.context() as stack:
            with parity.world(stack, tmp_path, name, **config_fields) as world:
                parity.hold_jobs(stack, world.ctx)
                results.append(scenario(world, runtime))
    return results


# ------------------------------------------------------------- descriptor and methods


def test_local_descriptor_declares_no_templates_parsers_predicates_or_emit():
    descriptor = connector().descriptor
    assert descriptor.name == "local" and descriptor.version == "local-v1"
    assert descriptor.predicates == () and descriptor.parsers == () and descriptor.credentials == ()
    assert descriptor.capabilities.derivation == "coordinator_lane"
    assert not hasattr(connector(), "emit")
    assert not Path(local().__file__).with_name("templates.py").exists()
    from hippo.connectors import base

    assert isinstance(connector(), base.SyncConnector)
    assert not isinstance(connector(), base.Connector)


@pytest.mark.parametrize("kind", ["text", "archive", "file"])
def test_local_descriptor_covers_every_record_the_lanes_write(tmp_path, kind):
    """Every object, artifact and locator kind the two lanes publish is declared, and registered.

    Ruling R72: S5a could only pin the prose subset, so the archive and code-file worlds are
    pinned here. The declaration is the superset of both lanes, so each world is required to be
    covered by it rather than equal to it, and the measured sets are recorded in the evidence.
    """
    descriptor = connector().descriptor
    descriptor.validate_against(current_registry())

    def scenario(world, runtime):
        if kind == "text":
            source = _stage_text(world, parity.FIRST_TEXT)
        elif kind == "archive":
            source = _stage_upload(world, parity.ARCHIVE_FILENAME, parity.archive_bytes())
        else:
            source = _stage_upload(world, parity.CODE_FILENAME, parity.code_file_bytes())
        receipt = _first(world, source, runtime=runtime)
        assert receipt.outcome == "published"
        return published_vocabulary(world.ctx.store, receipt.generation_id)

    (objects, artifacts, locators), _ = run_worlds(tmp_path, scenario)
    assert artifacts and artifacts <= set(descriptor.artifact_kinds), (artifacts, descriptor.artifact_kinds)
    assert locators and locators <= set(descriptor.locator_kinds), (locators, descriptor.locator_kinds)
    assert objects <= set(descriptor.kinds), (objects, descriptor.kinds)
    if kind == "text":
        assert objects == set(), "the prose lane writes no knowledge object"
    else:
        assert objects, "the code lane writes knowledge objects"
    # Ruling R72's narrowing, pinned: a saved local source is never a repository tree, so
    # `code_generation._history:397` walks nothing and no commit or history event is published.
    assert "commit" not in objects and "history_event" not in artifacts
    assert "commit" not in descriptor.kinds and "history_event" not in descriptor.artifact_kinds


def test_the_local_connector_passes_check_capture(tmp_path):
    """Ruling R67 / review M12: the kit's capture-side assertions run on the ported connector.

    The kit ships one negative fixture per capture assertion
    (`tests/unit/test_connector_testing_kit.py` `VIOLATIONS`), so none is added here; the last
    case proves the rules are read against *this* connector rather than passing vacuously.
    """
    from hippo.connectors import testing

    text = tmp_path / "text.md"
    text.write_bytes(parity.FIRST_TEXT.encode())
    archive = tmp_path / parity.ARCHIVE_FILENAME
    archive.write_bytes(parity.archive_bytes())
    code = tmp_path / parity.CODE_FILENAME
    code.write_bytes(parity.code_file_bytes())

    for source_id, kind, root in (
        ("c1", "text", text),
        ("c2", "file", tmp_path / parity.PROSE_FILENAME),
        ("c3", "archive", archive),
        ("c4", "file", code),
    ):
        if not root.exists():
            root.write_bytes(parity.PROSE_FILE)
        cfg = config(source_id=source_id, kind=kind, root=str(root))
        assert testing.check_capture(connector(), cfg, sample=8) == (), (source_id, kind)

    class WrongFetch(local().LocalConnector):
        def fetch(self, config, ref):
            # `model_copy` does not re-run the validator, which is how a real connector would
            # answer the wrong record: nothing refuses it before the kit does.
            return super().fetch(config, ref).model_copy(update={"external_id": "never/seen.md"})

    broken = config(source_id="c5", kind="archive", root=str(archive))
    assert {v.assertion for v in testing.check_capture(WrongFetch(), broken, sample=2)} == {
        "fetch_matches_ref"
    }


def test_local_list_changes_for_pasted_text_and_a_prose_file_is_one_complete_upsert(tmp_path):
    saved = tmp_path / "text.md"
    saved.write_bytes(parity.FIRST_TEXT.encode())
    page = connector().list_changes(config(source_id="s1", kind="text", root=str(saved)), None)
    assert page.partition == "source:s1" and page.complete is True and page.next_cursor is None
    assert page.warnings == ()
    assert [(c.operation, c.ref.external_id, c.ref.artifact_kind) for c in page.changes] == [
        ("upsert", "text.md", "file")
    ]
    assert page.changes[0].ref.provider_revision is None

    upload = tmp_path / parity.PROSE_FILENAME
    upload.write_bytes(parity.PROSE_FILE)
    file_page = connector().list_changes(config(source_id="s2", kind="file", root=str(upload)), None)
    assert [c.ref.external_id for c in file_page.changes] == [parity.PROSE_FILENAME]
    assert file_page.complete is True


def test_local_fetch_returns_the_saved_bytes(tmp_path):
    saved = tmp_path / parity.PROSE_FILENAME
    saved.write_bytes(parity.PROSE_FILE)
    cfg = config(source_id="s3", kind="file", root=str(saved))
    ref = connector().list_changes(cfg, None).changes[0].ref
    fetched = connector().fetch(cfg, ref)
    assert fetched.data == parity.PROSE_FILE
    assert fetched.external_id == parity.PROSE_FILENAME
    assert fetched.canonical_uri == f"source:s3/{parity.PROSE_FILENAME}"
    assert fetched.provider_revision is None


def test_local_fetch_policy_equals_the_policy_the_prose_lane_mints(tmp_path):
    """m9: `PolicyObservation` has no origin, so the comparison is the workspace grant itself."""
    saved = tmp_path / "text.md"
    saved.write_bytes(parity.FIRST_TEXT.encode())
    cfg = config(source_id="s4", kind="text", root=str(saved))
    ref = connector().list_changes(cfg, None).changes[0].ref
    observed = connector().fetch_policy(cfg, ref)
    assert observed.ref == ref
    assert (observed.state, observed.mode) == ("known", "workspace")
    assert not (observed.allow_users or observed.allow_groups)
    assert not (observed.deny_users or observed.deny_groups)

    from hippo.knowledge import model as k

    minted = k.AccessPolicy(
        workspace_id="w",
        origin="local_curated",
        scope_key="source:s4:plain-prose-v1",
        mode="workspace",
        verified_at=parity.INSTANT,
    )
    assert minted.mode == observed.mode


@pytest.mark.parametrize(
    ("kind", "name"),
    [
        ("text", "text.md"),
        ("file", "notes.md"),
        ("file", "module.py"),
        ("archive", "tree.zip"),
    ],
)
def test_local_probe_family_agrees_with_the_dispatch_for_every_eligible_kind(tmp_path, kind, name):
    saved = tmp_path / name
    saved.write_bytes(parity.PROSE_FILE)
    cfg = config(source_id="s5", kind=kind, root=str(saved))
    classification = connector().probe(cfg, lambda: parity.INSTANT)
    assert classification.connector == "local"
    assert [partition.partition for partition in classification.partitions] == ["source:s5"]
    family = classification.partitions[0].family
    row = {"kind": kind, "meta": {"file": name}}
    assert (family == "code") is managed_activation.is_code_source(row), (family, kind, name)


def test_the_sample_and_an_actorless_source_never_reach_a_lane(tmp_path, monkeypatch):
    """The sample stays legacy (plan deviation 6), and no actor means no managed dispatch."""
    calls = []
    with pytest.MonkeyPatch.context() as stack:
        with parity.world(stack, tmp_path, "sample") as world:
            parity.inline_jobs(stack, world.ctx)
            stack.setattr(
                lanes(),
                "run_coordinator_lane",
                lambda *a, **kw: calls.append(a) or pytest.fail("a lane ran"),
            )
            pipeline.add_sample(world.ctx, owner_id=world.user)
            pipeline.add_text(world.ctx, "Notes", parity.FIRST_TEXT, owner_id=world.user)
    assert calls == []


def test_a_connector_source_reindex_is_refused_by_dispatch(tmp_path):
    """R43: until Task 15 there is no route from a reader actor to `sync_connector`."""
    reached = []
    with pytest.MonkeyPatch.context() as stack:
        with parity.world(stack, tmp_path, "connector_source") as world:
            source = world.ctx.store.create_source("connector", "Tickets", {"file": "none"})
            world.ctx.store.begin_managed_source(source)  # the flag a staged build would set
            stack.setattr(
                managed_activation,
                "ingress_file",
                lambda *a, **kw: reached.append(a) or pytest.fail("ingress ran"),
            )
            with pytest.raises(managed_activation.ManagedDispatchError):
                managed_activation.run_managed_build(
                    world.ctx,
                    source_id=source,
                    actor=world.actor,
                    operation_id="index.0",
                    job_key=pipeline.job_key(source),
                )
    assert reached == []


# ------------------------------------------------------------------- the lane


def test_add_text_and_a_prose_upload_dispatch_through_the_prose_lane(tmp_path):
    """Both prose families reach `run_coordinator_lane` with the local connector and a prose lane."""
    seen = []
    with pytest.MonkeyPatch.context() as stack:
        with parity.world(stack, tmp_path, "dispatch") as world:
            parity.inline_jobs(stack, world.ctx)
            original = lanes().run_coordinator_lane

            def spy(conn, cfg, lane, *, registry):
                seen.append((type(conn).__name__, cfg.kind, lane.family, registry.fingerprint()))
                return original(conn, cfg, lane, registry=registry)

            stack.setattr(managed_activation, "run_coordinator_lane", spy)
            _stage_text(world, parity.FIRST_TEXT)
            _stage_upload(world, parity.PROSE_FILENAME, parity.PROSE_FILE)
    assert [(name, kind, family) for name, kind, family, _ in seen] == [
        ("LocalConnector", "text", "prose"),
        ("LocalConnector", "file", "prose"),
    ]
    assert {fingerprint for *_, fingerprint in seen} == {current_registry().fingerprint()}


def test_run_coordinator_lane_passes_the_frozen_registry_fingerprint(tmp_path):
    saved = tmp_path / "text.md"
    saved.write_bytes(parity.FIRST_TEXT.encode())
    module = lanes()
    registry = Registry.with_builtins()
    registry.freeze()
    seen = []

    def build(page, fingerprint):
        seen.append((page, fingerprint))
        return "receipt"

    cfg = config(source_id="s6", kind="text", root=str(saved))
    result = module.run_coordinator_lane(
        connector(), cfg, module.CoordinatorLane("prose", build), registry=registry
    )
    assert result == "receipt"
    ((page, fingerprint),) = seen
    assert fingerprint == registry.fingerprint()
    assert page.complete is True and len(page.changes) == 1


def test_run_coordinator_lane_refuses_an_incomplete_inventory_or_an_unregistered_descriptor(tmp_path):
    saved = tmp_path / "text.md"
    saved.write_bytes(parity.FIRST_TEXT.encode())
    module = lanes()
    cfg = config(source_id="s7", kind="text", root=str(saved))
    lane = module.CoordinatorLane("prose", lambda page, fingerprint: pytest.fail("build ran"))

    class Incomplete:
        descriptor = connector().descriptor

        def probe(self, config, clock):
            raise AssertionError

        def list_changes(self, config, cursor):
            page = connector().list_changes(config, cursor)
            return page.replace(complete=False)

        def fetch(self, config, ref):
            raise AssertionError

        def fetch_policy(self, config, ref):
            raise AssertionError

    with pytest.raises(module.LaneRefused):
        module.run_coordinator_lane(Incomplete(), cfg, lane, registry=current_registry())

    unregistered = connector()
    unregistered.descriptor = unregistered.descriptor.replace(families=("prose", "pager_feed"))
    with pytest.raises(module.LaneRefused):
        module.run_coordinator_lane(unregistered, cfg, lane, registry=current_registry())

    wrong_family = module.CoordinatorLane("code", lambda page, fingerprint: pytest.fail("build ran"))
    prose_only = connector()
    prose_only.descriptor = prose_only.descriptor.replace(families=("prose",))
    with pytest.raises(module.LaneRefused):
        module.run_coordinator_lane(prose_only, cfg, wrong_family, registry=current_registry())


def test_a_lane_failure_reaches_map_build_failure_with_its_type_unchanged(tmp_path):
    """The lane lets the coordinator's exception through, so the public code does not move."""
    saved = tmp_path / "text.md"
    saved.write_bytes(parity.FIRST_TEXT.encode())
    module = lanes()
    from hippo.ollama import OllamaError

    def build(page, fingerprint):
        raise OllamaError("offline")

    with pytest.raises(OllamaError) as raised:
        module.run_coordinator_lane(
            connector(),
            config(source_id="s8", kind="text", root=str(saved)),
            module.CoordinatorLane("prose", build),
            registry=current_registry(),
        )
    assert type(raised.value) is OllamaError
    assert (
        managed_activation.map_build_failure(raised.value, has_active_generation=False).code
        == "model_unavailable"
    )


# --------------------------------------------------------------- byte identity


@pytest.mark.parametrize("text", [parity.FIRST_TEXT, parity.LONG_TEXT], ids=["first_text", "long_text"])
def test_pasted_text_through_the_runtime_is_byte_identical_to_the_pre_kit_path(tmp_path, text):
    def scenario(world, runtime):
        source = _stage_text(world, text)
        receipt = _first(world, source, runtime=runtime)
        assert receipt.outcome == "published"
        return _snapshot(world, receipt)

    a, b = run_worlds(tmp_path, scenario)
    assert a == b


def test_a_prose_upload_through_the_runtime_is_byte_identical_to_the_pre_kit_path(tmp_path):
    def scenario(world, runtime):
        source = _stage_upload(world, parity.PROSE_FILENAME, parity.PROSE_FILE)
        receipt = _first(world, source, runtime=runtime)
        assert receipt.outcome == "published"
        return _snapshot(world, receipt)

    a, b = run_worlds(tmp_path, scenario)
    assert a == b


def test_a_text_refresh_through_the_runtime_is_byte_identical_to_the_pre_kit_refresh(tmp_path):
    def scenario(world, runtime):
        source = _stage_text(world, parity.FIRST_TEXT)
        first = _first(world, source, runtime=runtime)
        (pipeline.source_dir(world.ctx, source) / "text.md").write_text(parity.SECOND_TEXT)
        second = _drive(world, source, runtime=runtime)
        assert second.outcome == "published" and second.generation_id != first.generation_id
        return _snapshot(world, second)

    a, b = run_worlds(tmp_path, scenario)
    assert a == b


def test_an_unchanged_rebuild_through_the_runtime_returns_the_pre_kit_receipt(tmp_path):
    def scenario(world, runtime):
        source = _stage_text(world, parity.FIRST_TEXT)
        first = _first(world, source, runtime=runtime)
        again = _drive(world, source, runtime=runtime)
        assert again.outcome != "published"
        assert again.generation_id == first.generation_id
        return parity._jsonable(again)

    a, b = run_worlds(tmp_path, scenario)
    assert a == b


def test_registry_fingerprint_is_the_only_generation_field_that_differs(tmp_path):
    def scenario(world, runtime):
        source = _stage_text(world, parity.FIRST_TEXT)
        receipt = _first(world, source, runtime=runtime)
        row = world.ctx.store._knowledge_get("Generation", receipt.generation_id)
        return row.model_dump(mode="json")

    a, b = run_worlds(tmp_path, scenario)
    assert a["registry_fingerprint"] is None
    assert b["registry_fingerprint"] == current_registry().fingerprint()
    assert {key for key in a if a[key] != b.get(key)} == {"registry_fingerprint"}


@pytest.mark.parametrize("scenario_id", ["capture_too_large", "model_unavailable"])
def test_a_failed_runtime_build_presents_the_pre_kit_public_failure(tmp_path, scenario_id):
    """A refusal keeps the public code and message the pre-kit path presents, and the same row."""

    def scenario(world, runtime):
        if scenario_id == "model_unavailable":
            world.runtime.hook = lambda path, body: httpx.Response(503)
        source = _stage_text(world, parity.FIRST_TEXT)
        with pytest.raises(Exception) as raised:  # noqa: PT011 - the presentation is what is compared
            _first(world, source, runtime=runtime)
        failure = managed_activation.record_build_failure(
            world.ctx, source_id=source, operation_id=world.operations[0], error=raised.value
        )
        row = world.ctx.store.get_source(source)
        return (
            type(raised.value).__name__,
            (failure.status, failure.stage, failure.code, failure.message),
            (row["status"], row["stage"], row["error"]),
        )

    limits = {"max_text_chars": 4} if scenario_id == "capture_too_large" else {}
    a, b = run_worlds(tmp_path, scenario, **limits)
    assert a == b


def test_the_runtime_path_writes_no_connector_or_sync_state_row_and_no_connector_id(tmp_path):
    """R5: the lane's lease and checkpoint are the coordinator's claim and manifest."""
    lane_calls = []
    with pytest.MonkeyPatch.context() as stack:
        with parity.world(stack, tmp_path, "no_rows") as world:
            parity.inline_jobs(stack, world.ctx)
            receipts = parity.spy_receipts(stack)
            original = lanes().run_coordinator_lane
            stack.setattr(
                managed_activation,
                "run_coordinator_lane",
                lambda *a, **kw: (lane_calls.append(a), original(*a, **kw))[1],
            )
            _stage_text(world, parity.FIRST_TEXT)
            store = world.ctx.store
            assert receipts and receipts[-1].outcome == "published"
            assert len(lane_calls) == 1, "the publication did not come through the lane"
            assert store._knowledge_rows("Connector") == []
            assert store._knowledge_rows("SyncState") == []
            assert all(artifact.connector_id is None for artifact in store._knowledge_rows("Artifact"))


# ------------------------------------------------------- the coordinator seam


def test_build_plain_source_defaults_registry_fingerprint_to_none(tmp_path):
    """The reviewed path stays reachable: the keyword defaults to `None` (plan section 5)."""
    import inspect

    from hippo.ingest.prose_generation import build_plain_source

    parameter = inspect.signature(build_plain_source).parameters["registry_fingerprint"]
    assert parameter.default is None and parameter.kind is inspect.Parameter.KEYWORD_ONLY

    with pytest.MonkeyPatch.context() as stack:
        with parity.world(stack, tmp_path, "default") as world:
            parity.hold_jobs(stack, world.ctx)
            source = _stage_text(world, parity.FIRST_TEXT)
            receipt = _first(world, source, runtime=False)
            row = world.ctx.store._knowledge_get("Generation", receipt.generation_id)
            assert row.registry_fingerprint is None


def test_a_retried_prose_generation_keeps_its_stored_registry_fingerprint(tmp_path):
    """A published generation's fingerprint is what it was published with, whatever the rebuild reads.

    `_generation` adopts a stored generation's fingerprint exactly as it adopts its `created_at`,
    so the immutable record can never be re-derived with different contents. The fingerprint is
    outside `Generation.identity_fields`, so a rebuild under a different registry lands on the same
    generation id and must leave the stored value alone.
    """
    with pytest.MonkeyPatch.context() as stack:
        with parity.world(stack, tmp_path, "retry") as world:
            parity.inline_jobs(stack, world.ctx)
            receipts = parity.spy_receipts(stack)
            source = _stage_text(world, parity.FIRST_TEXT)
            stored = world.ctx.store._knowledge_get("Generation", receipts[-1].generation_id)
            assert stored.registry_fingerprint == current_registry().fingerprint()

            # A registry that really differs. Freezing alone does not move a fingerprint, so a bare
            # `Registry.with_builtins()` would make every assertion below true by construction.
            other = Registry.with_builtins()
            other.register(TypeExtension(artifact_kinds=("parity_probe",)))
            other.freeze()
            assert other.fingerprint() != stored.registry_fingerprint

            stack.setattr(managed_activation, "current_registry", lambda: other)
            pipeline.start_indexing(world.ctx, source, build_actor=world.actor)
            replay = receipts[-1]
            assert replay.outcome == "already_current"  # the rebuild took the prior-receipt path
            assert replay.generation_id == stored.id
            again = world.ctx.store._knowledge_get("Generation", stored.id)
            assert again.registry_fingerprint == stored.registry_fingerprint
            assert again == stored


def test_the_accepted_configuration_is_byte_for_byte_the_pre_kit_configuration(tmp_path):
    """Design section 3 and the CK5 CRITERIA: the port adds nothing to the manifest."""

    def scenario(world, runtime):
        source = _stage_text(world, parity.FIRST_TEXT)
        receipt = _first(world, source, runtime=runtime)
        revisions = [
            json.loads(row.metadata_json)
            for row in world.ctx.store._knowledge_rows("ArtifactRevision")
            if row.metadata_json and "accepted_manifest_v1" in row.metadata_json
        ]
        generation = world.ctx.store._knowledge_get("Generation", receipt.generation_id)
        return revisions, generation.coverage_json, generation.manifest_hash

    a, b = run_worlds(tmp_path, scenario)
    assert a == b
