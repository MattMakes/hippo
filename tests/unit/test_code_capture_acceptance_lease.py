"""Finite query-retention budget used only by the slow CD9 acceptance refresh."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from hippo.knowledge.access import AuthorizationChanged
from tests.unit.test_code_capture_acceptance import acceptance_query_lease
from tests.unit.test_query_snapshot_service import acquire, setup


def acceptance_world(seconds=3600.0):
    return SimpleNamespace(options=SimpleNamespace(lease_duration_seconds=seconds))


def reference(w):
    return next(iter(w.store.references.values()))


def test_acceptance_budget_keeps_real_snapshot_live_past_production_default(monkeypatch):
    snapshot_world = setup()
    with acceptance_query_lease(acceptance_world(), monkeypatch):
        with acquire(snapshot_world) as bundle:
            owner = bundle.lease_owner
            snapshot_world.clock[0] += timedelta(seconds=301)
            bundle.validate()
            live = reference(snapshot_world)
            assert live.lease_owner == owner
            assert live.released_at is None
    assert reference(snapshot_world).released_at is not None


def test_acceptance_budget_remains_finite_and_expires_without_renewal(monkeypatch):
    snapshot_world = setup()
    with acceptance_query_lease(acceptance_world(), monkeypatch):
        with acquire(snapshot_world) as bundle:
            snapshot_world.clock[0] += timedelta(seconds=3601)
            with pytest.raises(AuthorizationChanged, match="lease"):
                bundle.validate()
    assert reference(snapshot_world).released_at is not None


def test_explicit_shorter_lease_overrides_acceptance_budget(monkeypatch):
    snapshot_world = setup()
    with acceptance_query_lease(acceptance_world(), monkeypatch):
        with acquire(snapshot_world, lease_duration=timedelta(seconds=10)) as bundle:
            snapshot_world.clock[0] += timedelta(seconds=11)
            with pytest.raises(AuthorizationChanged, match="lease"):
                bundle.validate()
    assert reference(snapshot_world).released_at is not None


def test_production_default_is_restored_after_exceptional_scope_exit(monkeypatch):
    with pytest.raises(RuntimeError, match="leave scope"):
        with acceptance_query_lease(acceptance_world(), monkeypatch):
            raise RuntimeError("leave scope")

    snapshot_world = setup()
    with acquire(snapshot_world) as bundle:
        snapshot_world.clock[0] += timedelta(seconds=301)
        with pytest.raises(AuthorizationChanged, match="lease"):
            bundle.validate()
    assert reference(snapshot_world).released_at is not None
