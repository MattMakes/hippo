"""A managed delete is an atomic current-view tombstone and builder fence, not erasure."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from hippo.access import EVERYTHING, Principal
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.build_authority import BuildActor
from hippo.knowledge.query_access import query_session
from tests.unit.test_generation_store import authority, claim, generation
from tests.unit.test_query_snapshots import build

OPERATION = "delete-0001"
RETAINED_KINDS = (
    "AccessPolicy",
    "Artifact",
    "ArtifactRevision",
    "EvidenceSpan",
    "Generation",
    "GenerationMember",
    "GenerationEvidenceMember",
    "IndexManifest",
    "IndexEvent",
)


def api():
    try:
        return importlib.import_module("hippo.knowledge.source_lifecycle")
    except ModuleNotFoundError:
        pytest.fail("Managed source lifecycle service is missing")


def tombstone(w, *, actor=None, operation_id=OPERATION, source_id=None):
    return api().tombstone_managed_source(
        w.ctx,
        source_id=w.source if source_id is None else source_id,
        actor=w.actor if actor is None else actor,
        operation_id=operation_id,
    )


@pytest.fixture
def managed(ctx):
    """One managed source with a published G1, owned by a real local reader."""
    store = ctx.store
    store.ensure_roles()
    gen, span = build(ctx)
    other, other_span = build(ctx, text="unrelated source")
    user = store.create_user("deleter", "password", "individual")
    store.set_source_access(gen.source_id, None, owner_id=user)
    actor = BuildActor.reader(Principal.for_user(store.get_user(user), store.get_role("individual")))
    return SimpleNamespace(
        ctx=ctx,
        store=store,
        source=gen.source_id,
        gen=gen,
        span=span,
        other=other,
        other_span=other_span,
        user=user,
        actor=actor,
    )


def suppressions(store, source_id):
    return [
        row
        for row in store._knowledge_rows("Suppression")
        if row.target_kind == "source" and row.target_id == source_id
    ]


def inventory(store):
    rows = {kind: store._knowledge_rows(kind) for kind in RETAINED_KINDS}
    rows["Passage"] = sorted(store.load_passages(), key=lambda row: row["id"])
    return rows


def epochs(store):
    return store.authorization_epoch(), store.content_epoch(), store.suppression_epoch()


# ------------------------------------------------------ the committed transition


def test_tombstone_commits_suppression_fence_and_presentation_together(managed):
    store = managed.store
    before = store.get_source(managed.source)
    auth, content, suppression = epochs(store)

    receipt = tombstone(managed)

    assert receipt.source_id == managed.source
    assert receipt.operation_id == OPERATION
    assert receipt.outcome == "tombstoned"
    assert receipt.suppression_epoch == suppression + 1
    assert receipt.fencing_token == int(before.get("build_fencing_token") or 0) + 1
    assert receipt.cancelled_generation_id is None and receipt.cancelled_job_id is None

    row = suppressions(store, managed.source)
    assert len(row) == 1
    row = row[0]
    assert row.all_principals is True and row.principal_ids == ()
    assert row.view_applicability == "current_only"
    assert row.reason == "tombstone"
    assert row.scope_key == f"source:{managed.source}:delete"
    assert row.epoch == suppression + 1
    assert row.restoration_barrier == OPERATION

    source = store.get_source(managed.source)
    assert source["status"] == "deleted" and source["stage"] == "tombstoned"
    assert source["progress_done"] == 0 and source["progress_total"] == 0
    assert not source.get("error")
    assert source["active_generation_id"] == before["active_generation_id"]
    assert source["active_build_id"] is None
    assert source["build_fencing_token"] == receipt.fencing_token
    assert epochs(store) == (auth + 1, content + 1, suppression + 1)


def test_retained_history_raw_references_and_other_sources_are_untouched(managed):
    store = managed.store
    before = inventory(store)
    other_before = store.get_source(managed.other.source_id)

    tombstone(managed)

    assert inventory(store) == before
    assert store.get_source(managed.other.source_id) == other_before
    assert store._generation(managed.gen.id).status == "active"


def test_tombstone_never_runs_a_destructive_cleanup(managed, monkeypatch):
    import shutil

    from hippo.ingest import pipeline

    store = managed.store

    def refuse(*args, **kwargs):
        raise AssertionError("managed delete must not run destructive cleanup")

    for name in (
        "delete_source",
        "delete_passages_for_source",
        "delete_code_nodes_for_source",
        "remove_orphans",
        "collect_generation",
        "discard_generation",
    ):
        monkeypatch.setattr(store, name, refuse)
    monkeypatch.setattr(pipeline, "_clear_passages", refuse)
    monkeypatch.setattr(shutil, "rmtree", refuse)
    monkeypatch.setattr("pathlib.Path.unlink", refuse)
    monkeypatch.setattr("os.remove", refuse)

    assert tombstone(managed).outcome == "tombstoned"
    assert suppressions(store, managed.source)


# --------------------------------------------------------------- current views


def test_held_current_session_fails_and_a_new_session_excludes_the_source(managed):
    ctx = managed.ctx
    with pytest.raises(AuthorizationChanged):
        with query_session(ctx, EVERYTHING, structural=True) as session:
            assert session.graph.passage_by_id(managed.span.id) is not None
            tombstone(managed)
            session.validate()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        assert session.graph.passage_by_id(managed.span.id) is None
        assert session.graph.passage_by_id(managed.other_span.id) is not None


# ------------------------------------------------------------------- refusals


def test_unmanaged_source_is_refused_before_any_mutation(managed):
    store = managed.store
    # Owned by the same reader: standing is established first, so the refusal this
    # asserts is the unmanaged one rather than the generic denial below.
    legacy = store.create_source("text", "legacy", owner_id=managed.user)
    before = epochs(store), store.get_source(legacy)
    with pytest.raises(api().UnmanagedSource):
        tombstone(managed, source_id=legacy)
    assert (epochs(store), store.get_source(legacy)) == before


def test_an_unauthorized_reader_learns_nothing_about_the_source(managed):
    """Managed, unmanaged and absent are one generic denial for an actor with no standing.

    Standing is established before the managed recheck, so `UnmanagedSource` is no
    longer an oracle; `_source_control` raises the same text as `_actor_access`, so
    an absent source is not one either. One type, one message, all three cases.
    """
    store = managed.store
    stranger = store.create_user("stranger", "password", "individual")
    actor = BuildActor.reader(Principal.for_user(store.get_user(stranger), store.get_role("individual")))
    unmanaged = store.create_source("text", "legacy", owner_id=managed.user)
    before = epochs(store), inventory(store)

    denials = []
    for source_id in (managed.source, unmanaged, "source-that-never-existed"):
        with pytest.raises(AuthorizationChanged) as raised:
            tombstone(managed, actor=actor, source_id=source_id)
        denials.append((type(raised.value), str(raised.value)))

    assert [kind for kind, _ in denials] == [AuthorizationChanged] * 3
    assert not any(issubclass(kind, api().SourceLifecycleError) for kind, _ in denials)
    assert len({message for _, message in denials}) == 1, denials
    assert (epochs(store), inventory(store)) == before


def test_denied_actor_gets_the_generic_denial_and_changes_nothing(managed):
    store = managed.store
    stranger = store.create_user("stranger", "password", "individual")
    actor = BuildActor.reader(Principal.for_user(store.get_user(stranger), store.get_role("individual")))
    before = epochs(store), store.get_source(managed.source)
    with pytest.raises(AuthorizationChanged):
        tombstone(managed, actor=actor)
    assert (epochs(store), store.get_source(managed.source)) == before
    assert suppressions(store, managed.source) == []


@pytest.mark.parametrize("operation_id", ["", " ", "a" * 129, "bad id", "bad/id", "../escape", 7, None])
def test_operation_id_is_bounded_and_closed(managed, operation_id):
    store = managed.store
    before = epochs(store), store.get_source(managed.source)
    with pytest.raises((TypeError, ValueError)):
        tombstone(managed, operation_id=operation_id)
    assert (epochs(store), store.get_source(managed.source)) == before


# --------------------------------------------------------------------- replay


def test_reader_replay_reveals_nothing_about_a_tombstoned_source(managed):
    store = managed.store
    tombstone(managed)
    before = epochs(store)
    with pytest.raises(AuthorizationChanged):
        tombstone(managed)
    assert epochs(store) == before
    assert len(suppressions(store, managed.source)) == 1


@pytest.mark.parametrize("staging", [False, True])
def test_internal_replay_of_the_same_operation_returns_the_prior_receipt(managed, staging):
    store = managed.store
    if staging:
        claim(store, generation(store, "refresh", managed.gen))
    first = tombstone(managed)
    before = epochs(store), inventory(store)

    replay = tombstone(managed, actor=BuildActor.trusted_local())

    assert replay.outcome == "already_tombstoned"
    assert replay.suppression_epoch == first.suppression_epoch
    assert replay.fencing_token == first.fencing_token
    assert replay.cancelled_generation_id == first.cancelled_generation_id
    assert replay.cancelled_job_id == first.cancelled_job_id
    assert replay.source_id == first.source_id and replay.operation_id == first.operation_id
    assert (epochs(store), inventory(store)) == before
    assert len(suppressions(store, managed.source)) == 1


def test_internal_replay_with_another_operation_id_is_denied(managed):
    store = managed.store
    tombstone(managed)
    before = epochs(store)
    with pytest.raises(AuthorizationChanged):
        tombstone(managed, actor=BuildActor.trusted_local(), operation_id="delete-0002")
    assert epochs(store) == before
    assert len(suppressions(store, managed.source)) == 1


# ------------------------------------------------------------ builder fencing


def test_only_the_active_unpublished_build_is_failed_and_cancelled(managed):
    store = managed.store
    staging = generation(store, "refresh", managed.gen)
    job = claim(store, staging)

    receipt = tombstone(managed)

    assert receipt.cancelled_generation_id == staging.id
    assert receipt.cancelled_job_id == job.id
    assert store._generation(staging.id).status == "failed"
    cancelled = store._knowledge_get("MaintenanceJob", job.id)
    assert cancelled.status == "cancelled" and cancelled.error_code == "source_tombstoned"
    assert store._generation(managed.gen.id).status == "active"
    assert store.get_source(managed.source)["active_generation_id"] == managed.gen.id


def test_a_tombstoned_source_cannot_reclaim_its_failed_generation(managed, monkeypatch):
    """The committed tombstone is a store barrier, not a dispatcher courtesy."""
    store = managed.store
    staging = generation(store, "refresh", managed.gen)
    job = claim(store, staging)
    receipt = tombstone(managed)
    before = epochs(store), inventory(store), store.get_source(managed.source)

    def refuse(*args, **kwargs):
        raise AssertionError("a tombstoned source must not collect its retained attempt")

    monkeypatch.setattr(store, "_collect_generation", refuse)
    with pytest.raises(ValueError, match="Stale build lease, fence, or generation state"):
        claim(store, staging, key="retry")

    source = store.get_source(managed.source)
    assert source["build_fencing_token"] == receipt.fencing_token, "the fence must not advance"
    assert source["active_build_id"] is None, "a tombstoned source must hold no build"
    assert store._generation(staging.id).status == "failed"
    cancelled = store._knowledge_get("MaintenanceJob", job.id)
    assert cancelled.status == "cancelled" and cancelled.error_code == "source_tombstoned"
    assert (epochs(store), inventory(store), store.get_source(managed.source)) == before


def test_a_refused_reclaim_leaves_the_replayed_fencing_token_pinned(managed):
    """Nothing after the tombstone can move the fence the receipt reported."""
    store = managed.store
    staging = generation(store, "refresh", managed.gen)
    claim(store, staging)
    receipt = tombstone(managed)

    with pytest.raises(ValueError, match="Stale build lease, fence, or generation state"):
        claim(store, staging, key="retry")

    replay = tombstone(managed, actor=BuildActor.trusted_local())
    assert replay.outcome == "already_tombstoned"
    assert replay.fencing_token == receipt.fencing_token
    assert replay.suppression_epoch == receipt.suppression_epoch
    assert replay.cancelled_generation_id == receipt.cancelled_generation_id
    assert replay.cancelled_job_id == receipt.cancelled_job_id


def test_cancellation_is_requested_before_the_transaction(managed, monkeypatch):
    store, ctx = managed.store, managed.ctx
    calls = []

    def spy(key):
        calls.append((key, store.in_ambient_transaction(), len(suppressions(store, managed.source))))

    monkeypatch.setattr(ctx.jobs, "cancel", spy)

    assert tombstone(managed).outcome == "tombstoned"

    # No transaction open and no suppression written yet: requested, never awaited.
    assert calls == [(f"index:{managed.source}", False, 0)]
    assert len(suppressions(store, managed.source)) == 1


def test_another_threads_transaction_is_not_the_tombstone_callers_transaction(managed):
    """The store primitive's guard must answer for the calling thread, not the process."""
    store = managed.store
    before = epochs(store), store.get_source(managed.source)
    outcome = []

    def attempt():
        try:
            store.apply_source_tombstone(managed.source, operation_id=OPERATION, created_at=datetime.now(UTC))
        except BaseException as exc:  # noqa: BLE001 - asserted on the calling thread below
            outcome.append(exc)
        else:
            outcome.append(None)

    thread = Thread(target=attempt, name="unowned-tombstone", daemon=True)
    with store.transaction():
        thread.start()
        thread.join(10)
        assert not thread.is_alive(), "the unowned caller was admitted instead of refused"
    assert len(outcome) == 1
    assert isinstance(outcome[0], RuntimeError) and "requires the caller" in str(outcome[0])
    assert (epochs(store), store.get_source(managed.source)) == before
    assert suppressions(store, managed.source) == []


def test_tombstone_does_not_wait_for_a_blocked_model_callback(managed):
    store = managed.store
    staging = generation(store, "refresh", managed.gen)
    job = claim(store, staging)
    blocked, released, fenced = Event(), Event(), []

    def worker():
        blocked.set()
        released.wait(20)
        try:
            store.check_generation_write(staging.id, **authority(job))
        except ValueError:
            fenced.append("fenced")

    thread = Thread(target=worker, name="blocked-build", daemon=True)
    thread.start()
    try:
        assert blocked.wait(10)
        assert tombstone(managed).outcome == "tombstoned"
    finally:
        released.set()
        thread.join(20)
    assert fenced == ["fenced"]


def test_legacy_delete_still_removes_an_unmanaged_source(managed):
    store = managed.store
    legacy = store.create_source("text", "legacy")
    store.add_passages(
        [dict(id="legacy-passage", source_id=legacy, title="t", text="legacy", ordinal=0, embedding=[1.0])]
    )
    store.delete_source(legacy)
    assert store.get_source(legacy) is None
    assert not any(row["id"] == "legacy-passage" for row in store.load_passages())


def test_saved_ingress_and_query_snapshots_survive_the_tombstone(managed):
    from hippo.ingest import pipeline

    store, ctx = managed.store, managed.ctx
    directory = pipeline.source_dir(ctx, managed.source)
    directory.mkdir(parents=True, exist_ok=True)
    saved = directory / "text.md"
    saved.write_text("the original bytes")
    snapshots = store._knowledge_rows("QuerySnapshot"), store._knowledge_rows("SnapshotReference")

    tombstone(managed)

    assert saved.read_text() == "the original bytes"
    assert (store._knowledge_rows("QuerySnapshot"), store._knowledge_rows("SnapshotReference")) == snapshots


def test_the_store_primitive_is_unreachable_without_the_callers_transaction(managed):
    store = managed.store
    before = epochs(store), store.get_source(managed.source)
    with pytest.raises(RuntimeError, match="requires the caller"):
        store.apply_source_tombstone(managed.source, operation_id=OPERATION, created_at=datetime.now(UTC))
    assert (epochs(store), store.get_source(managed.source)) == before
    assert suppressions(store, managed.source) == []


def test_tombstone_fence_and_epochs_survive_a_ladybug_reopen(tmp_path, ollama):
    """The whole transition is durable, including on the primary acceptance backend."""
    from hippo.config import Config
    from hippo.context import AppContext
    from hippo.store.ladybug import LadybugStore

    path, data = tmp_path / "hippo.lbug", tmp_path / "data"
    store = LadybugStore(path)
    try:
        store.ping()
        ctx = AppContext(config=Config(data_dir=data, openie_workers=2), store=store, ollama=ollama)
        gen, span = build(ctx)
        user = store.create_user("deleter", "password", "individual")
        store.set_source_access(gen.source_id, None, owner_id=user)
        actor = BuildActor.reader(Principal.for_user(store.get_user(user), store.get_role("individual")))
        staging = generation(store, "refresh", gen)
        job = claim(store, staging)
        w = SimpleNamespace(ctx=ctx, source=gen.source_id, actor=actor)
        receipt = tombstone(w)
        expected = store.get_source(gen.source_id)
    finally:
        store.close()

    store = LadybugStore(path)
    try:
        store.ping()
        ctx = AppContext(config=Config(data_dir=data, openie_workers=2), store=store, ollama=ollama)
        assert store.get_source(gen.source_id) == expected
        # Reopening must not bump anything: the mapping is already in place.
        assert store.suppression_epoch() == receipt.suppression_epoch
        row = suppressions(store, gen.source_id)
        assert len(row) == 1 and row[0].epoch == receipt.suppression_epoch
        assert row[0].restoration_barrier == OPERATION
        assert row[0].view_applicability == "current_only" and row[0].all_principals is True
        assert store._generation(staging.id).status == "failed"
        cancelled = store._knowledge_get("MaintenanceJob", job.id)
        assert cancelled.status == "cancelled" and cancelled.error_code == "source_tombstoned"
        assert store._generation(gen.id).status == "active"
        with query_session(ctx, EVERYTHING, structural=True) as session:
            assert session.graph.passage_by_id(span.id) is None
        # The barrier is durable too: a reopened file still refuses to reclaim.
        with pytest.raises(ValueError, match="Stale build lease, fence, or generation state"):
            claim(store, staging, key="retry")
        assert store.get_source(gen.source_id) == expected
        replay = tombstone(SimpleNamespace(ctx=ctx, source=gen.source_id, actor=BuildActor.trusted_local()))
        assert replay.outcome == "already_tombstoned"
        assert replay.suppression_epoch == receipt.suppression_epoch
        assert replay.fencing_token == receipt.fencing_token
        assert replay.cancelled_generation_id == staging.id and replay.cancelled_job_id == job.id
    finally:
        store.close()


def test_creation_time_of_the_suppression_is_recorded(managed):
    before = datetime.now(UTC)
    tombstone(managed)
    row = suppressions(managed.store, managed.source)[0]
    assert before <= row.created_at <= datetime.now(UTC)
