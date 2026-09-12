from datetime import timedelta

import pytest

from hippo.knowledge import model as k
from tests.unit.test_generation_store import NOW, claim, generation, publish, seal


def snapshot(store, gen):
    return k.QuerySnapshot(
        workspace_id=store.get_source(gen.source_id)["workspace_id"],
        sources=(k.SnapshotSource(source_id=gen.source_id, generation_id=gen.id),),
        knowledge_cutoff=NOW,
        temporal=k.CurrentSelector(),
        profile_fingerprint="p",
        settings_fingerprint="s",
        policy_fingerprint="policy",
        suppression_epoch=store.suppression_epoch(),
        created_at=NOW,
    )


def test_live_saved_and_expired_references_control_collection(store):
    assert hasattr(store, "acquire_snapshot_reference")
    old = generation(store)
    job = claim(store, old)
    seal(store, old, job)
    publish(store, old, job)
    snap = snapshot(store, old)
    ref = store.acquire_snapshot_reference(
        snap, reference_key="request", lease_owner="reader", lease_expires_at=NOW + timedelta(minutes=2)
    )
    saved = store.retain_snapshot(snap.id, kind="saved", reference_key="result")
    assert store.retain_snapshot(snap.id, kind="saved", reference_key="result") == saved
    new = generation(store, "new", old)
    newjob = claim(store, new)
    seal(store, new, newjob)
    publish(store, new, newjob)
    assert store.collect_generation(old.id).blocked_reason == "snapshot_reference"
    store.release_snapshot_reference(ref.id, lease_owner="reader")
    assert store.collect_generation(old.id).blocked_reason == "snapshot_reference"
    store.release_snapshot_reference(saved.id)
    assert store.collect_generation(old.id).blocked_reason is None
    with pytest.raises(ValueError):
        store.renew_snapshot_reference(
            ref.id, lease_owner="reader", lease_expires_at=NOW + timedelta(minutes=3)
        )


def test_expired_reference_cannot_be_reacquired_or_renewed(store):
    assert hasattr(store, "acquire_snapshot_reference")
    gen = generation(store)
    job = claim(store, gen)
    seal(store, gen, job)
    publish(store, gen, job)
    snap = snapshot(store, gen)
    ref = store.acquire_snapshot_reference(
        snap, reference_key="request", lease_owner="reader", lease_expires_at=NOW + timedelta(minutes=2)
    )
    store._generation_clock = lambda: NOW + timedelta(minutes=3)
    with pytest.raises(ValueError):
        store.renew_snapshot_reference(
            ref.id, lease_owner="reader", lease_expires_at=NOW + timedelta(minutes=5)
        )
    with pytest.raises(ValueError):
        store.acquire_snapshot_reference(
            snap, reference_key="request", lease_owner="reader", lease_expires_at=NOW + timedelta(minutes=5)
        )


def test_recovery_preserves_active_source(store):
    assert hasattr(store, "recover_generation_builds")
    old = generation(store)
    job = claim(store, old)
    seal(store, old, job)
    publish(store, old, job)
    store.update_source(old.source_id, status="ready")
    new = generation(store, "new", old)
    claim(store, new)
    store._generation_clock = lambda: NOW + timedelta(minutes=6)
    result = store.recover_generation_builds()
    assert result.failed_builds == 1
    assert store.get_source(old.source_id)["active_generation_id"] == old.id
    assert store.get_source(old.source_id)["status"] == "ready"
    assert store._knowledge_get("Generation", new.id).status == "failed"


def test_reference_acquisition_rollback_and_current_pointer_compare(store):
    gen = generation(store)
    job = claim(store, gen)
    seal(store, gen, job)
    publish(store, gen, job)
    snap = snapshot(store, gen)

    def fail(point):
        if point == "reference":
            raise RuntimeError("injected reference")

    with pytest.raises(RuntimeError, match="injected"):
        store.acquire_snapshot_reference(
            snap,
            reference_key="rollback",
            lease_owner="reader",
            lease_expires_at=NOW + timedelta(minutes=2),
            fault_hook=fail,
        )
    assert store._knowledge_get("QuerySnapshot", snap.id) is None
    assert store._knowledge_rows("SnapshotReference") == []
    new = generation(store, "new", gen)
    newjob = claim(store, new)
    seal(store, new, newjob)
    publish(store, new, newjob)
    with pytest.raises(ValueError):
        store.acquire_snapshot_reference(
            snap, reference_key="late", lease_owner="reader", lease_expires_at=NOW + timedelta(minutes=2)
        )


def test_saved_reference_and_seal_survive_ladybug_reopen(tmp_path):
    from hippo.store.ladybug import LadybugStore

    path = tmp_path / "retained.lbug"
    store = LadybugStore(path)
    try:
        gen = generation(store)
        job = claim(store, gen)
        seal(store, gen, job)
        publish(store, gen, job)
        snap = snapshot(store, gen)
        store.acquire_snapshot_reference(
            snap, reference_key="reader", lease_owner="reader", lease_expires_at=NOW + timedelta(minutes=2)
        )
        saved = store.retain_snapshot(snap.id, kind="saved", reference_key="result")
        new = generation(store, "new", gen)
        newjob = claim(store, new)
        seal(store, new, newjob)
        publish(store, new, newjob)
    finally:
        store.close()
    reopened = LadybugStore(path)
    try:
        reopened._generation_clock = lambda: NOW + timedelta(minutes=3)
        assert reopened._knowledge_get("SnapshotReference", saved.id) == saved
        assert reopened.collect_generation(gen.id).blocked_reason == "snapshot_reference"
        reopened.release_snapshot_reference(saved.id)
        assert reopened.collect_generation(gen.id).blocked_reason is None
    finally:
        reopened.close()


def test_snapshot_acquisition_and_collection_share_exclusion_boundary(store):
    from concurrent.futures import ThreadPoolExecutor

    gen = generation(store)
    job = claim(store, gen)
    seal(store, gen, job)
    publish(store, gen, job)
    snap = snapshot(store, gen)
    new = generation(store, "new", gen)
    newjob = claim(store, new)
    seal(store, new, newjob)
    publish(store, new, newjob)

    def acquire():
        try:
            return store.acquire_snapshot_reference(
                snap,
                reference_key="race",
                lease_owner="reader",
                lease_expires_at=NOW + timedelta(minutes=2),
                require_current=False,
            )
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        reader = pool.submit(acquire)
        collector = pool.submit(store.collect_generation, gen.id)
        ref, result = reader.result(), collector.result()
    assert (ref is not None and result.blocked_reason == "snapshot_reference") or (
        ref is None and result.blocked_reason is None
    )


def test_recovery_clears_expired_pointer_after_staging_collection(store):
    gen = generation(store)
    job = claim(store, gen)
    store._generation_clock = lambda: NOW + timedelta(minutes=6)
    assert store.collect_generation(gen.id).blocked_reason is None
    store.recover_generation_builds()
    assert store.get_source(gen.source_id).get("active_build_id") is None
    assert store._knowledge_get("MaintenanceJob", job.id).status == "failed"


def test_historical_reference_cannot_pin_never_published_ready_generation(store):
    gen = generation(store)
    job = claim(store, gen)
    seal(store, gen, job)
    with pytest.raises(ValueError):
        store.acquire_snapshot_reference(
            snapshot(store, gen),
            reference_key="preview",
            lease_owner="reader",
            lease_expires_at=NOW + timedelta(minutes=2),
            require_current=False,
        )


def test_history_manifest_and_its_pin_survive_ladybug_reopen(tmp_path):
    """A durable manifest is reachability: it survives a reopen, a purge outranks it."""
    from hippo.access import EVERYTHING
    from hippo.knowledge import snapshots as snapshot_service
    from hippo.store.ladybug import LadybugStore
    from hippo.store.snapshots import PurgedEvidence
    from tests.unit.test_temporal_evidence import MAY_5, MAY_12, history_world, select

    path = tmp_path / "history.lbug"
    store = LadybugStore(path)
    try:
        world = history_world(store)
        history = select(world)
        snapshot_service.acquire_history_snapshot(
            store, EVERYTHING, history=history, settings_fingerprint="s", clock=lambda: MAY_12
        )
    finally:
        store.close()
    reopened = LadybugStore(path)
    try:
        reopened._generation_clock = lambda: MAY_12
        restored = reopened._knowledge_get("HistoryManifest", history.manifest.id)
        assert restored == history.manifest
        assert restored.knowledge_cutoff == MAY_5
        assert restored.revision_ids == (world.revision_one.id,)
        assert reopened.collect_generation(world.first.id).blocked_reason == "snapshot_reference"
        reopened.put_knowledge(
            k.Suppression(
                workspace_id=world.workspace,
                target_kind="revision",
                target_id=world.revision_one.id,
                scope_key="source:" + world.source,
                view_applicability="all_history",
                reason="purge",
                epoch=1,
                created_at=MAY_12,
                restoration_barrier="destroy",
            )
        )
        assert reopened.purged_history_evidence(history.manifest.id) == (
            PurgedEvidence("revision", world.revision_one.id),
        )
        assert reopened.collect_generation(world.first.id).blocked_reason is None
    finally:
        reopened.close()
