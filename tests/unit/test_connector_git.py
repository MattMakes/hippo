"""The git connector, the local connector's code half, and the code path's byte-identity proof.

Gate CK5, plan `ai_docs/plans/cdk-s5-port.md` sections 3, 4.1, 4.2, 5, 6 and 8 (S5b), with
rulings R1 (the coordinator lane), R2 (`code_generation.py` is S5b's), R4 (runtime parity at
N=2), R5 (no `Connector` or `SyncState` row), R54 (the one `ingest` to `connectors` import
edge), R65 (no configuration field named `credential...`), R67 / M12 (`check_capture` on both
ported connectors), R69 (`git` stays a built-in loader entry), R72 (falsify the fingerprint
branch on the code lane) and m9.

The proof is two worlds on two fresh stores, run one after the other: world A is the pre-kit
`_run_code_build` as it stood at `2710262`, world B is the runtime path. Their published
generations must agree everywhere `tests/fakes/connector_parity.py` compares them, with
`Generation.registry_fingerprint` the single allowed difference.
"""

from __future__ import annotations

import importlib
import inspect
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from hippo.ingest import managed_activation, pipeline, repos
from hippo.ingest.repo_capture import CaptureRefused
from hippo.knowledge.registry import Registry, TypeExtension, current_registry
from tests.fakes import connector_parity as parity

TOKEN = "ghp_s3cr3tT0ken"  # noqa: S105 - a fixture credential that must never reach a clone
CREDENTIALED_URL = f"https://robot:{TOKEN}@git.example.com/acme/private.git"


def lanes():
    return importlib.import_module("hippo.connectors.lanes")


def git():
    try:
        return importlib.import_module("hippo.connectors.git.connector")
    except ModuleNotFoundError:
        pytest.fail("The git connector module hippo.connectors.git.connector is missing")


def local():
    return importlib.import_module("hippo.connectors.local.connector")


def connector():
    return git().GitConnector()


def config(**fields):
    defaults = {
        "source_id": "s1",
        "url": parity.CLONE_URL,
        "depth": 1,
        "git_timeout_seconds": 20,
    }
    return git().GitSourceConfig(**{**defaults, **fields})


def local_config(**fields):
    return local().LocalSourceConfig(**fields)


# ------------------------------------------------------------------ the worlds


def _stage_repo(world) -> str:
    return pipeline.add_repo(world.ctx, parity.CLONE_URL, owner_id=world.user, build_actor=world.actor)


def _stage_archive(world) -> str:
    return pipeline.add_upload(
        world.ctx,
        parity.ARCHIVE_FILENAME,
        parity.archive_bytes(),
        owner_id=world.user,
        build_actor=world.actor,
    )


def _stage_code_file(world) -> str:
    return pipeline.add_upload(
        world.ctx,
        parity.CODE_FILENAME,
        parity.code_file_bytes(),
        owner_id=world.user,
        build_actor=world.actor,
    )


STAGE = {"repo": _stage_repo, "archive": _stage_archive, "file": _stage_code_file}


def _drive(world, source_id: str, *, runtime: bool, operation_id: str | None = None):
    """One managed code build, through the world's own path and one operation identity.

    World A calls the pre-kit `_run_code_build` copied into the parity helper; world B calls
    `run_managed_build`. The runtime assertions are what separate the two worlds before the
    switch lands: a parity comparison must never be able to pass by comparing world A with
    itself.
    """
    if runtime:
        assert managed_activation.run_coordinator_lane is lanes().run_coordinator_lane, (
            "world B is not the runtime path: the dispatch does not hold the coordinator lane"
        )
    operation_id = operation_id or managed_activation.new_operation_id()
    call = parity.runtime_code_build if runtime else parity.pre_kit_code_build
    kwargs = {} if runtime else {"job_key": pipeline.job_key(source_id)}
    receipt = call(world.ctx, source_id=source_id, actor=world.actor, operation_id=operation_id, **kwargs)
    if runtime and receipt.outcome == "published":
        row = world.ctx.store._knowledge_get("Generation", receipt.generation_id)
        assert row.registry_fingerprint == current_registry().fingerprint(), (
            "the runtime path published without the registry fingerprint"
        )
    return receipt


def _first(world, source_id: str, *, runtime: bool):
    """The first build, on the identity `add_repo`/`add_upload`'s own dispatch minted."""
    return _drive(world, source_id, runtime=runtime, operation_id=world.operations[0])


def _snapshot(world, receipt):
    return parity.published_snapshot(world.ctx, receipt.generation_id, receipt)


# The crashed attempt has to complete more staged groups than the install's own revision
# members, or `_resumed_batches` reports nothing resumed (`code_generation.py:783-792`). At the
# reviewed batch size the whole fixture is one batch, so the worlds are driven at `batch_size=1`,
# which is an operational option the generation never hashes (`CodeBuildOptions`, plan section 8.3).
CRASH_AFTER_BATCHES = 20


def small_batches(world) -> None:
    """Both worlds read their options from `managed_activation.code_build_options`, so one patch
    gives world A and world B the same write plan: 127 one-record batches for this fixture."""
    real = managed_activation.code_build_options
    world.stack.setattr(
        managed_activation, "code_build_options", lambda ctx: replace(real(ctx), batch_size=1)
    )


def crash_mid_staging(world, source_id: str, *, runtime: bool) -> None:
    """Fail the build inside a staged write, leaving a resumable generation.

    The shape `test_code_generation.crashed` uses (`:689-705`), driven through whichever path the
    world is, so the crash lands at the same batch in both worlds.
    """
    from hippo.knowledge import staged_code

    original = staged_code._write_batch
    written = 0

    def crash(store, prepared, batch, **authority):
        nonlocal written
        if written == CRASH_AFTER_BATCHES:
            raise RuntimeError("injected crash")
        written += 1
        return original(store, prepared, batch, **authority)

    world.stack.setattr(staged_code, "_write_batch", crash)
    try:
        with pytest.raises(RuntimeError):
            _first(world, source_id, runtime=runtime)
    finally:
        world.stack.setattr(staged_code, "_write_batch", original)
    assert written == CRASH_AFTER_BATCHES, "the crash never reached the chosen staged write"


@contextmanager
def one_world(tmp_path: Path, name: str, **config_fields):
    """One world, for the rules that do not need a comparison. A repo build is not cheap."""
    with pytest.MonkeyPatch.context() as stack:
        with parity.world(stack, tmp_path, name, **config_fields) as world:
            parity.hold_jobs(stack, world.ctx)
            world.origin = parity.make_origin(tmp_path / name / "git")
            world.clones = parity.clone_from(stack, world.origin)
            world.stack = stack
            yield world


def run_worlds(tmp_path: Path, scenario, **config_fields):
    """Run `scenario` in the pre-kit world, then in the runtime world, and return both results.

    Each world gets its own origin repository, built from the same files at the same pinned
    commit dates, so world A's refresh commit can never be present when world B bootstraps and
    the two still agree on every commit id and every head revision.
    """
    results = []
    for name, runtime in (("pre_kit", False), ("runtime", True)):
        with pytest.MonkeyPatch.context() as stack:
            with parity.world(stack, tmp_path, name, **config_fields) as world:
                parity.hold_jobs(stack, world.ctx)
                world.origin = parity.make_origin(tmp_path / name / "git")
                world.clones = parity.clone_from(stack, world.origin)
                world.stack = stack
                results.append(scenario(world, runtime))
    return results


# ------------------------------------------------------------- descriptor and methods


def test_git_descriptor_declares_no_templates_parsers_predicates_or_emit():
    descriptor = connector().descriptor
    assert descriptor.name == "git" and descriptor.version == "git-v1"
    assert descriptor.families == ("code",)
    assert descriptor.predicates == () and descriptor.parsers == () and descriptor.credentials == ()
    assert descriptor.capabilities.derivation == "coordinator_lane"
    assert descriptor.capabilities.history is True
    assert not hasattr(connector(), "emit")
    assert not Path(git().__file__).with_name("templates.py").exists()
    from hippo.connectors import base

    assert isinstance(connector(), base.SyncConnector)
    assert not isinstance(connector(), base.Connector)
    descriptor.validate_against(current_registry())
    # Ruling R65: a configuration model never names a field after a credential.
    assert not [name for name in git().GitSourceConfig.model_fields if "credential" in name]


def test_the_git_connector_kind_stays_a_built_in_of_the_frozen_registry():
    """Ruling R69: `connectors/git/` is an in-repo package by shape and a built-in kind."""
    assert "git" in Registry.with_builtins().connector_kinds()
    assert "git" in current_registry().connector_kinds()


def test_git_descriptor_covers_every_record_the_code_lane_writes(tmp_path):
    """Every object, artifact and locator kind a repository build publishes is declared."""
    descriptor = connector().descriptor
    with one_world(tmp_path, "git_vocabulary") as world:
        source = _stage_repo(world)
        receipt = _first(world, source, runtime=True)
        assert receipt.outcome == "published"
        objects, artifacts, locators = published_vocabulary(world.ctx.store, receipt.generation_id)
    assert objects and objects <= set(descriptor.kinds), (objects, descriptor.kinds)
    assert artifacts and artifacts <= set(descriptor.artifact_kinds), (artifacts, descriptor.artifact_kinds)
    assert locators and locators <= set(descriptor.locator_kinds), (locators, descriptor.locator_kinds)
    # The code lane is the one that writes a repository's history, so the declaration is not
    # a superset here: the artifact kinds a repository build publishes include `history_event`.
    assert "history_event" in artifacts and "repository" in artifacts


def published_vocabulary(store, generation_id: str) -> tuple[set[str], set[str], set[str]]:
    """The object, artifact and locator kinds one published generation actually wrote.

    A `KnowledgeObject` is never a generation member (S4a override 6), so the generation's
    objects are the distinct ones its member observations name.
    """
    artifacts = {
        store._knowledge_get(
            "Artifact",
            store._knowledge_get("ArtifactRevision", member.artifact_revision_id).artifact_id,
        ).kind
        for member in store._knowledge_rows("GenerationMember", generation_id=generation_id)
    }
    evidence = list(store._knowledge_rows("GenerationEvidenceMember", generation_id=generation_id))
    locators = {
        store._knowledge_get("EvidenceSpan", member.record_id).locator_kind
        for member in evidence
        if member.record_kind == "EvidenceSpan"
    }
    objects = {
        store._knowledge_get(
            "KnowledgeObject", store._knowledge_get("ObjectObservation", member.record_id).object_id
        ).kind
        for member in evidence
        if member.record_kind == "ObjectObservation"
    }
    return objects, artifacts, locators


def test_git_list_changes_clones_through_repos_clone_repo_with_the_dispatch_depth(tmp_path):
    """The `clone_locally` monkeypatch of `test_managed_code_activation.py:129-140` still applies."""
    with pytest.MonkeyPatch.context() as stack:
        origin = parity.make_origin(tmp_path / "origin_tree")
        clones = parity.clone_from(stack, origin)
        checkout = tmp_path / "checkout"
        page = connector().list_changes(config(checkout=str(checkout), depth=4), None)

    assert [(url, dest, depth) for url, dest, depth in clones] == [(parity.CLONE_URL, checkout, 4)]
    assert checkout.is_dir() and page.complete is True


def test_git_list_changes_refuses_a_credentialed_url_before_cloning(tmp_path):
    """`repository_descriptor` refuses first, so a token never reaches a clone (plan 4.2 step 1)."""
    reached = []
    with pytest.MonkeyPatch.context() as stack:
        stack.setattr(repos, "clone_repo", lambda *a, **kw: reached.append(a) or pytest.fail("cloned"))
        with pytest.raises(CaptureRefused) as raised:
            connector().list_changes(config(url=CREDENTIALED_URL, checkout=str(tmp_path / "never")), None)
    assert reached == []
    assert TOKEN not in str(raised.value)
    assert not (tmp_path / "never").exists()


def test_git_list_changes_lists_the_walk_with_the_head_revision(tmp_path):
    from hippo.ingest.repo_capture import walk_tree

    with pytest.MonkeyPatch.context() as stack:
        origin = parity.make_origin(tmp_path / "origin_tree")
        parity.clone_from(stack, origin)
        checkout = tmp_path / "checkout"
        page = connector().list_changes(config(source_id="s9", checkout=str(checkout)), None)

    head = parity.head_revision(checkout)
    inventory = walk_tree(checkout)
    assert page.partition == "source:s9" and page.complete is True and page.next_cursor is None
    assert [change.ref.external_id for change in page.changes] == [
        item.logical_path for item in inventory.inputs
    ]
    assert {change.operation for change in page.changes} == {"upsert"}
    assert {change.ref.provider_revision for change in page.changes} == {head}
    assert {change.ref.artifact_kind for change in page.changes} == {"file"}
    # One coverage warning per exclusion reason, with its count.
    reasons = {item.reason for item in inventory.exclusions}
    assert {warning.split(".")[1].split(":")[0] for warning in page.warnings} == reasons

    fetched = connector().fetch(config(source_id="s9", checkout=str(checkout)), page.changes[0].ref)
    member = checkout / page.changes[0].ref.external_id
    assert fetched.data == member.read_bytes()
    assert fetched.provider_revision == head
    assert fetched.canonical_uri == f"source:s9/{page.changes[0].ref.external_id}"


def test_git_fetch_policy_equals_the_policy_the_code_lane_mints(tmp_path):
    """m9: `PolicyObservation` has no origin, so the comparison is the workspace grant itself."""
    with pytest.MonkeyPatch.context() as stack:
        origin = parity.make_origin(tmp_path / "origin_tree")
        parity.clone_from(stack, origin)
        cfg = config(source_id="s10", checkout=str(tmp_path / "checkout"))
        ref = connector().list_changes(cfg, None).changes[0].ref
        observed = connector().fetch_policy(cfg, ref)
    assert observed.ref == ref
    assert (observed.state, observed.mode) == ("known", "workspace")
    assert not (observed.allow_users or observed.allow_groups)
    assert not (observed.deny_users or observed.deny_groups)


def test_git_probe_reports_the_code_family_and_the_history_capability(tmp_path):
    with pytest.MonkeyPatch.context() as stack:
        origin = parity.make_origin(tmp_path / "origin_tree")
        parity.clone_from(stack, origin)
        checkout = tmp_path / "checkout"
        cfg = config(source_id="s11", checkout=str(checkout))
        before = connector().probe(cfg, lambda: parity.INSTANT)
        connector().list_changes(cfg, None)
        after = connector().probe(cfg, lambda: parity.INSTANT)

    assert before.connector == "git" and before.partitions[0].family == "code"
    assert before.partitions[0].capabilities.history is False, "no checkout, no observed history"
    assert after.partitions[0].capabilities.history is True
    assert [partition.partition for partition in after.partitions] == ["source:s11"]


def test_local_list_changes_for_an_archive_and_a_code_file_lists_their_walk(tmp_path):
    from hippo.ingest.repo_capture import walk_tree

    archive = tmp_path / parity.ARCHIVE_FILENAME
    archive.write_bytes(parity.archive_bytes())
    cfg = local_config(source_id="a1", kind="archive", root=str(archive))
    page = local().LocalConnector().list_changes(cfg, None)
    inventory = walk_tree(archive)
    assert page.partition == "source:a1" and page.complete is True and page.next_cursor is None
    assert [change.ref.external_id for change in page.changes] == [
        item.logical_path for item in inventory.inputs
    ]
    assert {change.ref.provider_revision for change in page.changes} == {None}
    member = local().LocalConnector().fetch(cfg, page.changes[0].ref)
    assert member.data and member.canonical_uri == f"source:a1/{page.changes[0].ref.external_id}"

    saved = tmp_path / parity.CODE_FILENAME
    saved.write_bytes(parity.code_file_bytes())
    file_cfg = local_config(source_id="a2", kind="file", root=str(saved))
    file_page = local().LocalConnector().list_changes(file_cfg, None)
    assert [change.ref.external_id for change in file_page.changes] == [parity.CODE_FILENAME]
    assert file_page.complete is True
    assert local().LocalConnector().fetch(file_cfg, file_page.changes[0].ref).data == saved.read_bytes()


# ---------------------------------------------------------- the kit's capture assertions


def test_the_git_connector_passes_check_capture(tmp_path):
    """Ruling R67 / review M12: the kit's capture-side assertions run on the ported connector."""
    from hippo.connectors import testing

    with pytest.MonkeyPatch.context() as stack:
        origin = parity.make_origin(tmp_path / "origin_tree")
        parity.clone_from(stack, origin)
        cfg = config(source_id="s12", checkout=str(tmp_path / "checkout"))
        assert testing.check_capture(connector(), cfg, sample=8) == ()

        # The kit ships one negative fixture per capture assertion
        # (`tests/unit/test_connector_testing_kit.py` `VIOLATIONS`), so none is added here. This
        # one proves the rules are read against *this* connector rather than passing vacuously.
        class WrongFetch(git().GitConnector):
            """S4a's `_fetch_that_answers_another_ref` shape, over the real connector.

            A perfectly valid `RawFetch` for the *next* walked member. Nothing refuses it before
            the kit does: `RawFetch` revalidates on copy (`Contract.model_config` sets
            `revalidate_instances="always"`), so a mangled copy would raise inside `fetch` and be
            recorded under the same name for the wrong reason.
            """

            def fetch(self, config, ref):
                refs = [change.ref for change in self.list_changes(config, None).changes]
                other = next(candidate for candidate in refs if candidate != ref)
                return super().fetch(config, other)

        fired = {violation.assertion for violation in testing.check_capture(WrongFetch(), cfg, sample=2)}
        assert fired == {"fetch_matches_ref"}, fired


# ------------------------------------------------------------------- the lane


@pytest.mark.parametrize("kind", ["repo", "archive", "file"])
def test_add_repo_and_code_uploads_dispatch_through_the_code_lane(tmp_path, kind):
    """Every code family reaches `run_coordinator_lane` with its connector and a code lane."""
    seen = []
    with pytest.MonkeyPatch.context() as stack:
        with parity.world(stack, tmp_path, f"dispatch_{kind}") as world:
            parity.inline_jobs(stack, world.ctx)
            parity.clone_from(stack, parity.make_origin(tmp_path / f"dispatch_{kind}" / "git"))
            original = lanes().run_coordinator_lane

            def spy(conn, cfg, lane, *, registry):
                seen.append((type(conn).__name__, lane.family, registry.fingerprint()))
                return original(conn, cfg, lane, registry=registry)

            stack.setattr(managed_activation, "run_coordinator_lane", spy)
            STAGE[kind](world)

    expected = "GitConnector" if kind == "repo" else "LocalConnector"
    assert [(name, family) for name, family, _ in seen] == [(expected, "code")]
    assert {fingerprint for *_, fingerprint in seen} == {current_registry().fingerprint()}


def test_the_checkout_is_discarded_however_the_build_ends(tmp_path):
    """The lifecycle stays in `_run_code_build`: discard before, and in `finally` (plan 4.2)."""
    with one_world(tmp_path, "checkout") as world:
        source = _stage_repo(world)
        operation = world.operations[0]
        receipt = _drive(world, source, runtime=True, operation_id=operation)
        assert receipt.outcome == "published"
        assert not managed_activation.checkout_directory(world.ctx, source, operation).exists()

        failing = managed_activation.new_operation_id()
        world.stack.setattr(
            managed_activation,
            "_build_code",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("injected")),
        )
        with pytest.raises(RuntimeError):
            _drive(world, source, runtime=True, operation_id=failing)
        assert not managed_activation.checkout_directory(world.ctx, source, failing).exists()


def test_the_runtime_code_path_writes_no_connector_or_sync_state_row_and_no_connector_id(tmp_path):
    """R5: the lane's lease and checkpoint are the coordinator's claim and manifest."""
    with pytest.MonkeyPatch.context() as stack:
        with parity.world(stack, tmp_path, "no_rows") as world:
            parity.inline_jobs(stack, world.ctx)
            parity.clone_from(stack, parity.make_origin(tmp_path / "no_rows" / "git"))
            receipts = parity.spy_receipts(stack)
            _stage_repo(world)
            store = world.ctx.store
            assert receipts and receipts[-1].outcome == "published"
            assert store._knowledge_rows("Connector") == []
            assert store._knowledge_rows("SyncState") == []
            assert all(artifact.connector_id is None for artifact in store._knowledge_rows("Artifact"))


# --------------------------------------------------------------- byte identity


def test_repository_bootstrap_through_the_runtime_is_byte_identical_to_the_pre_kit_path(tmp_path):
    def scenario(world, runtime):
        source = _stage_repo(world)
        receipt = _first(world, source, runtime=runtime)
        assert receipt.outcome == "published"
        return _snapshot(world, receipt)

    a, b = run_worlds(tmp_path, scenario)
    assert a == b


def test_repository_refresh_through_the_runtime_is_byte_identical_to_the_pre_kit_refresh(tmp_path):
    def scenario(world, runtime):
        source = _stage_repo(world)
        first = _first(world, source, runtime=runtime)
        parity.commit_refresh(world.origin)
        second = _drive(world, source, runtime=runtime)
        assert second.outcome == "published" and second.generation_id != first.generation_id
        return _snapshot(world, second)

    a, b = run_worlds(tmp_path, scenario)
    assert a == b


@pytest.mark.parametrize("kind", ["archive", "file"])
def test_archive_and_code_file_through_the_runtime_are_byte_identical_to_the_pre_kit_path(tmp_path, kind):
    def scenario(world, runtime):
        source = STAGE[kind](world)
        receipt = _first(world, source, runtime=runtime)
        assert receipt.outcome == "published"
        return _snapshot(world, receipt)

    a, b = run_worlds(tmp_path, scenario)
    assert a == b


def test_the_capture_fixture_repository_through_the_runtime_is_byte_identical(tmp_path):
    """Ruling R4: the acceptance fixture's shape, at N=2, through the runtime on both backends."""

    def scenario(world, runtime):
        from tests.fakes.code_capture_repo import build_code_capture_repository

        world.origin = build_code_capture_repository(
            tmp_path / ("runtime" if runtime else "pre_kit") / "fixture" / "repo", files_per_language=2
        ).root
        world.clones = parity.clone_from(world.stack, world.origin)
        source = _stage_repo(world)
        receipt = _first(world, source, runtime=runtime)
        assert receipt.outcome == "published"
        return _snapshot(world, receipt)

    a, b = run_worlds(tmp_path, scenario)
    assert a == b


def test_a_resumed_code_build_through_the_runtime_equals_the_pre_kit_resume(tmp_path):
    """A crash after a batch, then a resume of the same operation, on both paths."""

    def scenario(world, runtime):
        small_batches(world)
        source = _stage_repo(world)
        crash_mid_staging(world, source, runtime=runtime)
        receipt = _first(world, source, runtime=runtime)
        assert receipt.outcome == "published" and receipt.resumed_from_batches >= 1
        return _snapshot(world, receipt)

    a, b = run_worlds(tmp_path, scenario)
    assert a == b


def test_registry_fingerprint_is_the_only_generation_field_that_differs_on_the_code_lane(tmp_path):
    def scenario(world, runtime):
        source = _stage_repo(world)
        receipt = _first(world, source, runtime=runtime)
        row = world.ctx.store._knowledge_get("Generation", receipt.generation_id)
        return row.model_dump(mode="json")

    a, b = run_worlds(tmp_path, scenario)
    assert a["registry_fingerprint"] is None
    assert b["registry_fingerprint"] == current_registry().fingerprint()
    assert {key for key in a if a[key] != b.get(key)} == {"registry_fingerprint"}


# ------------------------------------------------------- the coordinator seam


def test_build_code_source_defaults_registry_fingerprint_to_none(tmp_path):
    """The reviewed path stays reachable: the keyword defaults to `None` (plan section 5)."""
    from hippo.ingest.code_generation import build_code_source

    parameter = inspect.signature(build_code_source).parameters["registry_fingerprint"]
    assert parameter.default is None and parameter.kind is inspect.Parameter.KEYWORD_ONLY

    with one_world(tmp_path, "default") as world:
        source = _stage_repo(world)
        receipt = _first(world, source, runtime=False)
        row = world.ctx.store._knowledge_get("Generation", receipt.generation_id)
        assert row.registry_fingerprint is None


def test_a_reclaimed_code_generation_keeps_its_stored_registry_fingerprint(tmp_path):
    """Ruling R72: the code lane's reclaim is where the adoption branch could bite.

    A crashed attempt leaves a staging `Generation` row carrying the fingerprint of the
    registry that wrote it. The resume runs under a registry that genuinely differs - a bare
    `Registry.with_builtins()` fingerprints identically to the process registry, so the other
    registry registers a probe kind first - reclaims the same generation, and must leave the
    stored fingerprint exactly as it was published.
    """
    with one_world(tmp_path, "reclaim") as world:
        small_batches(world)
        source = _stage_repo(world)
        crash_mid_staging(world, source, runtime=True)

        staged = next(row for row in world.ctx.store._knowledge_rows("Generation") if row.source_id == source)
        assert staged.status == "failed"
        assert staged.registry_fingerprint == current_registry().fingerprint()

        other = Registry.with_builtins()
        other.register(TypeExtension(artifact_kinds=("parity_probe",)))
        other.freeze()
        assert other.fingerprint() != staged.registry_fingerprint

        world.stack.setattr(managed_activation, "current_registry", lambda: other)
        receipt = _first(world, source, runtime=True)
        assert receipt.generation_id == staged.id and receipt.resumed_from_batches >= 1
        again = world.ctx.store._knowledge_get("Generation", staged.id)
        assert again.registry_fingerprint == staged.registry_fingerprint
