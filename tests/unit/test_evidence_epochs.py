"""Authorization changes and their cache invalidation counter commit together."""

from datetime import UTC, datetime, timedelta

import pytest

from hippo.knowledge import model as k


def policy_fixture(store):
    store.ensure_schema()
    workspace = k.Workspace(name="default")
    policy = k.AccessPolicy(
        workspace_id=workspace.id, mode="workspace", verified_at=datetime(2026, 9, 11, tzinfo=UTC)
    )
    return policy


def test_managed_policy_writes_increment_epoch_only_when_changed(store):
    policy = policy_fixture(store)
    initial = store.authorization_epoch()
    store.put_knowledge(policy)
    assert store.authorization_epoch() == initial + 1
    store.put_knowledge(policy)
    assert store.authorization_epoch() == initial + 1
    store.update_knowledge(policy.replace(verified_at=policy.verified_at + timedelta(seconds=1)))
    assert store.authorization_epoch() == initial + 2


def test_failed_policy_change_rolls_back_record_and_epoch(store):
    policy = policy_fixture(store)
    before = store.authorization_epoch()
    with pytest.raises(RuntimeError, match="injected"):
        with store.transaction():
            store.put_knowledge(policy)
            assert store.authorization_epoch() == before + 1
            raise RuntimeError("injected transaction failure")
    assert store.authorization_epoch() == before
    assert store._knowledge_get("AccessPolicy", policy.id) is None


@pytest.mark.parametrize(
    "operation", ["new_user", "disable_user", "remove_user", "edit_role", "source_access"]
)
def test_legacy_permission_mutations_invalidate_managed_readers(store, operation):
    store.ensure_schema()
    store.ensure_roles()
    user = store.create_user("epoch-reader", "secret1", "individual")
    source = store.create_source("file", "epoch.sql")
    before = store.authorization_epoch()
    if operation == "new_user":
        store.create_user("epoch-second", "secret1", "individual")
    elif operation == "disable_user":
        store.update_user(user, disabled=True)
    elif operation == "remove_user":
        store.delete_user(user)
    elif operation == "edit_role":
        store.update_role("individual", rank=1)
    else:
        store.set_source_access(source, "arch-admin")
    assert store.authorization_epoch() > before


def test_failed_legacy_permission_change_rolls_back_epoch(store):
    store.ensure_schema()
    store.ensure_roles()
    user = store.create_user("rollback-reader", "secret1", "individual")
    before = store.authorization_epoch()
    with pytest.raises(RuntimeError, match="injected"):
        with store.transaction():
            store.update_user(user, disabled=True)
            raise RuntimeError("injected transaction failure")
    assert store.authorization_epoch() == before
    assert store.get_user(user)["disabled"] is False


def test_first_user_history_rolls_back_with_failed_creation(store):
    store.ensure_schema()
    store.ensure_roles()
    with pytest.raises(RuntimeError, match="injected"):
        with store.transaction():
            store.create_user("rolled-back-first", "secret1", "individual")
            assert store.get_meta("has_had_users") is True
            raise RuntimeError("injected transaction failure")
    assert store.count_users() == 0
    assert store.get_meta("has_had_users") is not True


def test_removing_last_pre_marker_user_preserves_authentication_history(store):
    store.ensure_schema()
    store.ensure_roles()
    user = store.create_user("pre-marker-reader", "secret1", "individual")
    # Existing installations can contain users created before this marker existed.
    store.set_meta("has_had_users", None)
    store.delete_user(user)
    assert store.count_users() == 0
    assert store.get_meta("has_had_users") is True


def test_private_connector_cannot_be_configured_or_enabled_in_open_mode(store):
    policy = policy_fixture(store)
    connector = k.Connector(
        workspace_id=policy.workspace_id, kind="github", instance_url="https://git.example"
    )
    # Inert identity records carry no credentials or provider configuration.
    store.put_knowledge(connector)
    for change in (
        {"enabled": True},
        {"credential_ref": "env:HIPPO_PROVIDER_TOKEN"},
        {"config_json": '{"repository":"private"}'},
    ):
        before = store.authorization_epoch()
        with pytest.raises(ValueError, match="open mode"):
            store.update_knowledge(connector.replace(**change))
        assert store.authorization_epoch() == before
    with pytest.raises(ValueError, match="open mode"):
        store.put_knowledge(connector.replace(instance_url="https://another.example", enabled=True))
    store.ensure_roles()
    store.create_user("connector-admin", "secret1", "arch-admin")
    store.update_knowledge(connector.replace(enabled=True))


def test_caller_cannot_treat_corrupt_epoch_as_fresh_cache(store):
    store.ensure_schema()
    store.set_meta("authorization_epoch", -1)
    with pytest.raises(RuntimeError, match="authorization epoch"):
        store.authorization_epoch()


def test_corrupt_epoch_cannot_be_reset_by_a_permission_mutation(store):
    store.ensure_schema()
    store.ensure_roles()
    user = store.create_user("corrupt-epoch-reader", "secret1", "individual")
    store.set_meta("authorization_epoch", -1)
    with pytest.raises(RuntimeError, match="authorization epoch"):
        store.update_user(user, disabled=True)
    assert store.get_meta("authorization_epoch") == -1
    assert store.get_user(user)["disabled"] is False


def configured_connector(store):
    policy = policy_fixture(store)
    store.ensure_roles()
    user = store.create_user("provider-owner", "secret1", "arch-admin")
    connector = k.Connector(
        workspace_id=policy.workspace_id,
        kind="github",
        instance_url="https://git.example",
        enabled=True,
        credential_ref="env:PROVIDER_TOKEN",
        config_json='{"repo":"private"}',
    )
    store.put_knowledge(connector)
    return user, connector


def test_last_user_cannot_be_removed_with_configured_provider_connectors(store):
    user, connector = configured_connector(store)
    before = store.authorization_epoch()
    with pytest.raises(ValueError, match="connector"):
        store.delete_user(user)
    assert store.count_users() == 1
    assert store.authorization_epoch() == before
    store.update_knowledge(connector.replace(enabled=False, credential_ref=None, config_json="{}"))
    store.delete_user(user)
    assert store.count_users() == 0


def test_safe_connector_deactivation_can_recover_existing_open_installation(store):
    user, connector = configured_connector(store)
    # Simulate a pre-guard store, without using the new guarded deletion API.
    if store.knowledge_backend == "fake":
        store.users.pop(user)
    else:
        store.run("MATCH (u:User {id:$id}) DETACH DELETE u", id=user)
    disabled = connector.replace(enabled=False)
    store.update_knowledge(disabled)
    assert store._knowledge_get("Connector", connector.id).enabled is False
    with pytest.raises(ValueError, match="open mode"):
        store.update_knowledge(connector)
    store.update_knowledge(disabled.replace(credential_ref=None, config_json="{}"))


def test_connector_enable_and_last_user_removal_have_one_safe_winner(store):
    import os
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from hippo.store import Store

    policy = policy_fixture(store)
    store.ensure_roles()
    user = store.create_user("racing-owner", "secret1", "arch-admin")
    connector = k.Connector(
        workspace_id=policy.workspace_id, kind="github", instance_url="https://git.example"
    )
    store.put_knowledge(connector)
    other = store
    if store.knowledge_backend == "neo4j":
        other = Store(
            os.environ["NEO4J_URI"], os.environ.get("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"]
        )
        other.ensure_schema()
    barrier = Barrier(2)

    def attempt(operation):
        barrier.wait(timeout=15)
        try:
            operation()
            return True
        except ValueError:
            return False

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(attempt, lambda: store.update_knowledge(connector.replace(enabled=True))),
                executor.submit(attempt, lambda: other.delete_user(user)),
            ]
            assert sum(future.result() for future in futures) == 1
        configured = store._knowledge_get("Connector", connector.id).enabled
        assert store.count_users() > 0 or not configured
    finally:
        if other is not store:
            other.close()
