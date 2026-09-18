"""Graph edits release evidence pins and validate fresh output after own mutations."""

from contextlib import contextmanager

import pytest

from hippo.knowledge import changeset_access
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.changeset_access import ChangesetAccess
from hippo.web.routes import analyze
from tests.unit.test_lookup_snapshot_lifetime import live_refs, managed  # noqa: F401

OPS = [{"op": "set_setting", "name": "damping", "value": 0.7}]


@pytest.mark.parametrize("operation", ["get", "list", "save", "delete", "apply"])
def test_changeset_operations_close_all_acquired_snapshots(ctx, managed, operation):  # noqa: F811
    _, _, acquired, request = managed
    access = request.state.principal.access
    identity = ChangesetAccess(ctx, access).save("Tuning", OPS)
    # Initial creation must also close its generation reference.
    assert not live_refs(ctx)
    service = ChangesetAccess(ctx, access)
    if operation == "get":
        assert service.get(identity)["name"] == "Tuning"
    elif operation == "list":
        assert len(service.list()) == 1
    elif operation == "save":
        service.save("Another", OPS)
    elif operation == "delete":
        service.delete(identity)
        assert ctx.store.get_changeset(identity) is None
    else:
        assert service.apply(identity)["descriptions"] == ["Set damping to 0.7"]
    assert acquired
    assert not live_refs(ctx)


def test_failed_changeset_write_closes_pin_after_rollback(ctx, managed, monkeypatch):  # noqa: F811
    _, _, _, request = managed
    epoch = ctx.store.authorization_epoch()
    original = ctx.store.set_meta

    def fail(key, value):
        if key.startswith("changeset_owner:"):
            raise RuntimeError("owner write failed")
        return original(key, value)

    monkeypatch.setattr(ctx.store, "set_meta", fail)
    with pytest.raises(RuntimeError, match="owner write failed"):
        ChangesetAccess(ctx, request.state.principal.access).save("Tuning", OPS)
    assert ctx.store.authorization_epoch() == epoch
    assert not live_refs(ctx)
    assert ctx.store.list_changesets() == []


@pytest.mark.parametrize("action", ["success", "error", "revoke"])
def test_changeset_page_borrows_one_session_through_render(ctx, managed, monkeypatch, action):  # noqa: F811
    _, _, acquired, request = managed
    monkeypatch.setattr(analyze, "require", lambda *a: None)

    def render(*args, **kwargs):
        assert len(acquired) == 1
        assert live_refs(ctx)
        assert kwargs["session"].graph is acquired[0]
        if action == "revoke":
            ctx.store._bump_authorization_epoch()
        if action == "error":
            raise RuntimeError("render failed")
        return "html"

    monkeypatch.setattr(analyze, "render", render)
    if action == "success":
        assert analyze.changesets_page(request) == "html"
    else:
        with pytest.raises(AuthorizationChanged if action == "revoke" else RuntimeError):
            analyze.changesets_page(request)
    assert not live_refs(ctx)


def test_changeset_apply_revalidates_evidence_after_commit(ctx, managed, monkeypatch):  # noqa: F811
    _, _, _, request = managed
    access = request.state.principal.access
    identity = ChangesetAccess(ctx, access).save("Tuning", OPS)
    assert not live_refs(ctx)

    original = ctx.graph_for
    selected = 0

    def graph_for(*args, **kwargs):
        nonlocal selected
        graph = original(*args, **kwargs)
        selected += 1
        if selected == 2:
            # The postcommit response scope must still enforce external revocation.
            ctx.store._bump_authorization_epoch()
        return graph

    monkeypatch.setattr(ctx, "graph_for", graph_for)
    with pytest.raises(AuthorizationChanged):
        ChangesetAccess(ctx, access).apply(identity)
    assert ctx.store.get_changeset(identity)["status"] == "applied"
    assert not live_refs(ctx)


def test_external_revocation_before_mutation_lock_prevents_write(ctx, managed, monkeypatch):  # noqa: F811
    _, _, _, request = managed
    original = changeset_access.lock_authorization

    def lock(store):
        original(store)
        store._bump_authorization_epoch()

    monkeypatch.setattr(changeset_access, "lock_authorization", lock)
    with pytest.raises(AuthorizationChanged):
        ChangesetAccess(ctx, request.state.principal.access).save("Rejected", OPS)
    assert ctx.store.list_changesets() == []
    assert not live_refs(ctx)


@pytest.mark.parametrize("fail", [False, True])
def test_mutation_releases_snapshot_outside_transaction_without_heartbeat(ctx, managed, monkeypatch, fail):  # noqa: F811
    _, _, _, request = managed
    from hippo.knowledge.lease_heartbeat import LeaseHeartbeat

    transaction = ctx.store.transaction
    graph_for = ctx.graph_for
    depth = 0
    closed = []

    @contextmanager
    def tracked_transaction():
        nonlocal depth
        with transaction():
            depth += 1
            try:
                yield
            finally:
                depth -= 1

    def acquire(*args, **kwargs):
        graph = graph_for(*args, **kwargs)
        original_close = graph.close_snapshot

        def close():
            assert depth == 0
            closed.append(True)
            original_close()

        graph.close_snapshot = close
        return graph

    def no_heartbeat(*args):
        pytest.fail("A short fenced mutation must not join a heartbeat under the DB lock")

    monkeypatch.setattr(ctx.store, "transaction", tracked_transaction)
    monkeypatch.setattr(ctx, "graph_for", acquire)
    monkeypatch.setattr(LeaseHeartbeat, "start", no_heartbeat)
    if fail:

        def fail_write(*args, **kwargs):
            raise RuntimeError("write failed")

        monkeypatch.setattr(ctx.store, "create_changeset", fail_write)
        with pytest.raises(RuntimeError, match="write failed"):
            ChangesetAccess(ctx, request.state.principal.access).save("Tuning", OPS)
    else:
        ChangesetAccess(ctx, request.state.principal.access).save("Tuning", OPS)
    assert closed == [True]
    assert not live_refs(ctx)
