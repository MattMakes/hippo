"""The single local workspace maps its own live Users, idempotently and at every boundary.

This file parametrizes its own backends because it is about store startup: the
shared `store` fixture hands out an already bootstrapped object, and the Ladybug
case has to close and reopen the same database file between steps.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from hippo.access import EVERYTHING, Principal
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.build_authority import BuildActor, capture_build_authority
from hippo.store.migrations import DEFAULT_WORKSPACE_ID
from tests.fakes.fake_store import FakeStore

NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)


class Backend:
    """One store of the parametrized kind, restartable so startup wiring can be replayed."""

    def __init__(self, kind: str, path) -> None:
        self.kind, self.path, self.store = kind, path, None

    def start(self):
        if self.store is None:
            if self.kind == "fake":
                self.store = FakeStore()
            else:
                from hippo.store.ladybug import LadybugStore

                self.store = LadybugStore(self.path)
        self.store.ping()
        return self.store

    def restart(self):
        """Ladybug reopens the same file; the in-memory fake replays its one bootstrap."""
        if self.kind == "ladybug":
            self.store.close()
            self.store = None
        else:
            self.store._bootstrapped = False
        return self.start()

    def close(self) -> None:
        if self.store is not None:
            self.store.close()


@pytest.fixture(params=["fake", "ladybug"])
def backend(request, tmp_path):
    value = Backend(request.param, tmp_path / "hippo.lbug")
    try:
        yield value
    finally:
        value.close()


def memberships(store, principal_id=None):
    rows = store._knowledge_rows("WorkspaceMembership")
    return sorted(
        (row for row in rows if principal_id is None or row.principal_id == principal_id),
        key=lambda row: row.id,
    )


def one(rows):
    assert len(rows) == 1, rows
    return rows[0]


def authorities(store):
    return store.get_meta("reviewed_mapping_authorities")


def forget_local_mapping(store) -> None:
    """Reproduce a store written before this mapping policy existed."""
    if store.knowledge_backend == "fake":
        store._knowledge_data.pop("WorkspaceMembership", None)
    else:
        store.run("MATCH (m:WorkspaceMembership) DETACH DELETE m")
    store.set_meta("reviewed_mapping_authorities", [])


def world(store, username="builder"):
    """A managed-source build authority captured through the mapping this task creates."""
    user = store.create_user(username, "password", "individual")
    source = store.create_source("file", "Notes", {"file": "notes.md"}, owner_id=user)
    actor = BuildActor.reader(Principal.for_user(store.get_user(user), store.get_role("individual")))
    guard = capture_build_authority(store, source_id=source, actor=actor, clock=lambda: NOW)
    return SimpleNamespace(store=store, user=user, source=source, actor=actor, guard=guard)


# ------------------------------------------------------------------ startup


def test_startup_maps_existing_users_into_the_reviewed_local_workspace(backend):
    store = backend.start()
    user = store.create_user("existing", "secret1", "individual")
    forget_local_mapping(store)
    assert memberships(store) == []
    assert authorities(store) == []

    store = backend.restart()

    assert authorities(store) == ["local"]
    row = one(memberships(store, user))
    assert row.workspace_id == DEFAULT_WORKSPACE_ID
    assert (row.enabled, row.mapping_authority, row.policy_epoch) == (True, "local", 1)


def test_repeated_startup_changes_nothing_and_bumps_no_epoch(backend):
    store = backend.start()
    store.create_user("stable", "secret1", "individual")
    before = (store.authorization_epoch(), memberships(store), authorities(store))

    store = backend.restart()
    assert (store.authorization_epoch(), memberships(store), authorities(store)) == before

    assert store.ensure_local_workspace_memberships() == 0
    assert (store.authorization_epoch(), memberships(store), authorities(store)) == before


def test_startup_keeps_the_reviewed_authorities_an_administrator_already_chose(backend):
    store = backend.start()
    store.set_meta("reviewed_mapping_authorities", ["reviewed"])
    store.create_user("kept", "secret1", "individual")

    store = backend.restart()

    assert authorities(store) == ["local", "reviewed"]


# --------------------------------------------------------- user lifecycle


def test_create_user_maps_the_new_principal_in_one_authorization_bump(backend):
    store = backend.start()
    before = store.authorization_epoch()

    user = store.create_user("mapped", "secret1", "individual")

    assert store.authorization_epoch() == before + 1
    row = one(memberships(store, user))
    assert (row.enabled, row.mapping_authority, row.policy_epoch) == (True, "local", 1)
    assert row.workspace_id == DEFAULT_WORKSPACE_ID


def test_delete_user_disables_and_retains_its_membership_in_one_bump(backend):
    store = backend.start()
    user = store.create_user("leaver", "secret1", "individual")
    before = store.authorization_epoch()

    store.delete_user(user)

    assert store.authorization_epoch() == before + 1
    assert store.get_user(user) is None
    row = one(memberships(store, user))
    assert row.enabled is False
    assert row.mapping_authority == "local"
    assert row.policy_epoch == 2


def test_disabling_a_mapping_keeps_the_authority_that_granted_it(backend):
    """Retiring is audit state: a non-local authority is retained, never rewritten local."""
    store = backend.start()
    user = store.create_user("granted", "secret1", "individual")
    row = one(memberships(store, user))
    store.update_knowledge(row.replace(mapping_authority="reviewed", policy_epoch=row.policy_epoch + 1))
    before = store.authorization_epoch()

    store.delete_user(user)

    assert store.authorization_epoch() == before + 1
    retired = one(memberships(store, user))
    assert (retired.enabled, retired.mapping_authority, retired.policy_epoch) == (False, "reviewed", 3)


def test_delete_user_on_a_pre_schema_store_has_no_mapping_to_retire(tmp_path, monkeypatch):
    """A permission mutation against a pre-schema-5 file must not fail on either path."""
    from hippo.store.ladybug import LadybugStore

    with monkeypatch.context() as patch:
        patch.setattr(LadybugStore, "ensure_schema", LadybugStore._ensure_legacy_schema)
        store = LadybugStore(tmp_path / "legacy.lbug")
        try:
            store.ensure_roles()
            assert not store.run("CALL show_tables() WHERE name='WorkspaceMembership' RETURN name")
            user = store.create_user("legacy", "secret1", "individual")
            # A second principal keeps this off the last-user removal branch, whose own
            # `Connector` read is a separate pre-schema gap outside this mapping.
            store.create_user("remaining", "secret1", "individual")

            store.delete_user(user)

            assert store.get_user(user) is None
        finally:
            store.close()


def test_startup_never_resurrects_a_removed_principal(backend):
    store = backend.start()
    kept = store.create_user("kept", "secret1", "individual")
    gone = store.create_user("gone", "secret1", "individual")
    store.delete_user(gone)

    store = backend.restart()

    assert one(memberships(store, kept)).enabled is True
    assert one(memberships(store, gone)).enabled is False


def test_mapping_survives_close_and_reopen(backend):
    store = backend.start()
    user = store.create_user("durable", "secret1", "individual")
    before = (memberships(store), authorities(store), store.authorization_epoch())

    store = backend.restart()

    assert (memberships(store), authorities(store), store.authorization_epoch()) == before
    assert one(memberships(store, user)).enabled is True


# ------------------------------------------------------------------ repair


@pytest.mark.parametrize("damage", ["disabled", "foreign_authority", "both"])
def test_damaged_local_mapping_is_repaired_with_a_higher_policy_epoch(backend, damage):
    store = backend.start()
    user = store.create_user("repairable", "secret1", "individual")
    current = one(memberships(store, user))
    changes = {
        "disabled": {"enabled": False},
        "foreign_authority": {"mapping_authority": "imported"},
        "both": {"enabled": False, "mapping_authority": "imported"},
    }[damage]
    broken = current.replace(policy_epoch=current.policy_epoch + 1, **changes)
    store.update_knowledge(broken)
    before = store.authorization_epoch()

    assert store.ensure_local_workspace_memberships() == 1

    repaired = one(memberships(store, user))
    assert (repaired.enabled, repaired.mapping_authority) == (True, "local")
    assert repaired.policy_epoch > broken.policy_epoch
    assert store.authorization_epoch() == before, "repair is additive; it invalidates no reader"


def test_many_repairs_count_every_change_and_invalidate_no_reader(backend):
    """The locked helper counts every change; the additive wrapper bumps no epoch at all."""
    store = backend.start()
    users = [store.create_user(f"repairable{index}", "secret1", "individual") for index in range(3)]
    for user in users:
        row = one(memberships(store, user))
        store.update_knowledge(row.replace(enabled=False, policy_epoch=row.policy_epoch + 1))
    store.set_meta("reviewed_mapping_authorities", [])
    before = store.authorization_epoch()

    assert store.ensure_local_workspace_memberships() == 4

    assert store.authorization_epoch() == before
    assert authorities(store) == ["local"]
    assert [one(memberships(store, user)).enabled for user in users] == [True, True, True]


def test_a_held_query_session_survives_the_first_ping_bootstrap(ctx):
    """The lazy bootstrap is additive, so a reader already in flight stays valid.

    `render()` pings the store while it holds the session it is rendering from, so a
    bump here would fail the first HTML request against any store that still needs
    mapping - the exact shape observed in the Task 2 review.
    """
    from hippo.knowledge.query_access import query_session

    store = ctx.store
    store.ensure_roles()
    store.create_user("inflight", "secret1", "individual")
    forget_local_mapping(store)
    store._bootstrapped = False
    before = store.authorization_epoch()

    with query_session(ctx, EVERYTHING, structural=True) as session:
        assert store.ping() is True
        session.validate()

    assert store.authorization_epoch() == before
    assert authorities(store) == ["local"]
    assert memberships(store) != []


def test_selected_principals_leave_every_other_mapping_untouched(backend):
    store = backend.start()
    first = store.create_user("first", "secret1", "individual")
    second = store.create_user("second", "secret1", "individual")
    for user in (first, second):
        row = one(memberships(store, user))
        store.update_knowledge(row.replace(enabled=False, policy_epoch=row.policy_epoch + 1))
    untouched = one(memberships(store, second))

    assert store.ensure_local_workspace_memberships([first]) == 1

    assert one(memberships(store, first)).enabled is True
    assert one(memberships(store, second)) == untouched


@pytest.mark.parametrize("principal_ids", ["", "user", [""], [1], [None], 7])
def test_selected_principals_must_be_explicit_nonempty_identities(backend, principal_ids):
    store = backend.start()
    before = (store.authorization_epoch(), memberships(store))
    with pytest.raises((TypeError, ValueError)):
        store.ensure_local_workspace_memberships(principal_ids)
    assert (store.authorization_epoch(), memberships(store)) == before


def test_unknown_principals_are_refused_rather_than_mapped(backend):
    store = backend.start()
    before = (store.authorization_epoch(), memberships(store))
    with pytest.raises(ValueError):
        store.ensure_local_workspace_memberships(["no-such-user"])
    assert (store.authorization_epoch(), memberships(store)) == before


# --------------------------------------------------- live build authority


def test_a_mapped_reader_can_capture_build_authority_without_manual_setup(backend):
    store = backend.start()
    w = world(store)
    assert w.guard.check_local() is None


def test_removing_the_reviewed_local_authority_invalidates_a_live_build(backend):
    store = backend.start()
    w = world(store)
    assert w.guard.check_local() is None

    store.set_meta("reviewed_mapping_authorities", ["imported"])

    with pytest.raises(AuthorizationChanged):
        w.guard.check_local()
    with pytest.raises(AuthorizationChanged):
        capture_build_authority(store, source_id=w.source, actor=w.actor, clock=lambda: NOW)


@pytest.mark.parametrize("change", ["membership", "role", "source_acl", "disabled", "deleted"])
def test_identity_and_source_changes_invalidate_a_captured_authority(backend, change):
    store = backend.start()
    w = world(store)
    assert w.guard.check_local() is None
    if change == "membership":
        row = one(memberships(store, w.user))
        store.update_knowledge(row.replace(enabled=False, policy_epoch=row.policy_epoch + 1))
    elif change == "role":
        store.update_role("individual", rank=0)
    elif change == "source_acl":
        store.set_source_access(w.source, None, owner_id=None)
    elif change == "disabled":
        store.update_user(w.user, disabled=True)
    else:
        store.delete_user(w.user)

    with pytest.raises(AuthorizationChanged):
        w.guard.check_local()
    if change == "role":
        # Moving the ladder invalidates the captured proof. The owner may still
        # recapture, which is exactly what losing standing below does not allow.
        capture_build_authority(store, source_id=w.source, actor=w.actor, clock=lambda: NOW)
        return
    with pytest.raises(AuthorizationChanged):
        capture_build_authority(store, source_id=w.source, actor=w.actor, clock=lambda: NOW)
