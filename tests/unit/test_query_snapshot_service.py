"""Query-level snapshot orchestration over the durable store API."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from importlib import import_module

import pytest

from hippo.access import Access
from hippo.knowledge import model as k
from hippo.knowledge.access import AuthorizationChanged
from tests.unit.test_evidence_access import NOW, engine, observation, world
from tests.unit.test_generation_evidence_selection import generation


def setup():
    w = world()
    _, obs, evidence = observation(w, "billing")
    gen = generation(w, [obs, evidence])
    w.source["active_generation_id"] = gen.id
    w.clock = [NOW]
    store = w.store
    store.references = {}
    store.lease_clock = w.clock
    store.count_users = lambda: len(store.users)
    store.get_meta = lambda key: None
    store.list_sources = lambda access: [s for s in store.sources.values() if access.can_see_source(s)]
    store.suppression_epoch = lambda: 0

    @contextmanager
    def transaction():
        before = deepcopy((store.records, store.references))
        try:
            yield
        except Exception:
            store.records, store.references = before
            raise

    store.transaction = transaction

    def proof(workspace_id, access, **kwargs):
        resolver = engine(w, access)
        return resolver, resolver.build(kwargs["selection"])

    store._reader_proof = proof

    def acquire(snapshot, *, reference_key, lease_owner, lease_expires_at, require_current=True):
        for selected in snapshot.sources:
            assert store.sources[selected.source_id]["active_generation_id"] == selected.generation_id
        store.records["QuerySnapshot"][snapshot.id] = snapshot
        ref = k.SnapshotReference(
            workspace_id=snapshot.workspace_id,
            snapshot_id=snapshot.id,
            kind="active_query",
            reference_key=reference_key,
            created_at=w.clock[0],
            lease_owner=lease_owner,
            lease_expires_at=lease_expires_at,
        )
        store.references[ref.id] = ref
        return ref

    store.acquire_snapshot_reference = acquire

    def renew(identity, *, lease_owner, lease_expires_at):
        ref = store.references[identity]
        if ref.released_at or ref.lease_expires_at <= w.clock[0] or ref.lease_owner != lease_owner:
            raise ValueError("snapshot lease unavailable")
        result = ref.replace(lease_expires_at=lease_expires_at)
        store.references[identity] = result
        return result

    store.renew_snapshot_reference = renew

    def release(identity, *, lease_owner=None):
        ref = store.references[identity]
        if ref.lease_owner != lease_owner:
            raise ValueError("wrong owner")
        store.references[identity] = ref.replace(released_at=w.clock[0])

    store.release_snapshot_reference = release
    w.gen = gen
    return w


def acquire(w, **kwargs):
    api = import_module("hippo.knowledge.snapshots")
    return api.acquire_query_snapshots(
        w.store,
        Access(user_id="alice"),
        source_ids=frozenset({"s"}),
        profile_fingerprint="e",
        settings_fingerprint="settings",
        clock=lambda: w.clock[0],
        **kwargs,
    )


def test_snapshot_acquires_proof_and_generation_then_releases_deterministically():
    w = setup()
    with acquire(w) as bundle:
        assert bundle.generation_ids == frozenset({w.gen.id})
        assert len(bundle.snapshots) == 1
        assert bundle.snapshots[0].sources[0].source_id == "s"
        assert bundle.proofs[0][1].selection.require_exact_membership
        bundle.validate()
        assert not next(iter(w.store.references.values())).released_at
    assert all(ref.released_at for ref in w.store.references.values())
    with pytest.raises(AuthorizationChanged, match="closed"):
        bundle.validate()
    bundle.close()


def test_content_publication_does_not_replace_held_generation():
    w = setup()
    with acquire(w) as bundle:
        w.source["active_generation_id"] = "new-generation"
        bundle.validate()
        assert bundle.generation_ids == frozenset({w.gen.id})


def test_current_revocation_still_invalidates_held_snapshot():
    w = setup()
    with acquire(w) as bundle:
        w.store.epoch += 1
        with pytest.raises(AuthorizationChanged):
            bundle.validate()


def test_expired_reference_cannot_be_renewed_by_query():
    w = setup()
    with acquire(w, lease_duration=timedelta(seconds=30)) as bundle:
        w.clock[0] += timedelta(seconds=31)
        with pytest.raises(AuthorizationChanged, match="lease"):
            bundle.validate()


def test_requested_private_or_missing_source_fails_before_reference_creation():
    w = setup()
    w.source["min_rank"] = 50
    with pytest.raises(ValueError, match="source"):
        acquire(w)
    assert not w.store.references


def test_wrong_profile_and_unsealed_generation_are_not_silently_skipped():
    w = setup()
    w.store.records["Generation"][w.gen.id] = w.gen.replace(embedding_profile="another")
    with pytest.raises(ValueError, match="profile|compatible"):
        acquire(w)
    assert not w.store.references


def test_failure_after_reference_creation_rolls_back_all_references():
    w = setup()
    original = w.store.acquire_snapshot_reference

    def failing(*args, **kwargs):
        original(*args, **kwargs)
        w.store.epoch += 1

    w.store.acquire_snapshot_reference = failing
    with pytest.raises(AuthorizationChanged):
        acquire(w)
    assert not w.store.references


def test_lease_duration_must_be_positive():
    w = setup()
    with pytest.raises(ValueError, match="positive"):
        acquire(w, lease_duration=timedelta(0))


def test_context_entry_failure_releases_the_acquired_reference():
    w = setup()
    bundle = acquire(w)
    w.store.epoch += 1
    with pytest.raises(AuthorizationChanged):
        with bundle:
            pytest.fail("revoked snapshot entered")
    assert all(ref.released_at is not None for ref in w.store.references.values())
