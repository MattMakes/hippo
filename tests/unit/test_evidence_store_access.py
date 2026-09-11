"""Public typed reads use managed policies rather than legacy unrestricted/rank shortcuts."""

from datetime import UTC, datetime

import pytest

from hippo.access import EVERYTHING, Access, Principal
from hippo.knowledge import model as k


def managed_fixture(store):
    store.ensure_schema()
    store.ensure_roles()
    workspace = k.Workspace(name="default")
    user = store.create_user("managed-reader", "secret1", "individual")
    source = store.create_source("file", "managed.md")
    policy = k.AccessPolicy(
        workspace_id=workspace.id,
        origin="local_curated",
        scope_key="source:" + source,
        mode="workspace",
        verified_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    store.put_knowledge(policy)
    artifact = k.Artifact(
        workspace_id=workspace.id,
        source_id=source,
        kind="file",
        external_id="managed.md",
        canonical_uri="source:managed.md",
        policy_id=policy.id,
    )
    store.put_knowledge(artifact)
    revision = k.ArtifactRevision(
        artifact_id=artifact.id,
        content_hash="h",
        raw_uri="blob:r",
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        lifecycle="active",
    )
    store.put_knowledge(revision)
    span = k.EvidenceSpan(
        revision_id=revision.id,
        locator_kind="field",
        locator_json='{"kind":"field","field_path":"body"}',
        text="managed evidence",
        policy_id=policy.id,
    )
    store.put_knowledge(span)
    return workspace, user, span


def test_store_read_requires_explicit_reviewed_workspace_membership(store):
    workspace, user, span = managed_fixture(store)
    access = Access(user_id=user)
    assert store.get_knowledge("EvidenceSpan", span.id, workspace_id=workspace.id, access=access) is None
    membership = k.WorkspaceMembership(
        workspace_id=workspace.id,
        principal_id=user,
        enabled=True,
        mapping_authority="reviewed",
        policy_epoch=1,
    )
    store.put_knowledge(membership)
    assert store.list_knowledge("EvidenceSpan", workspace_id=workspace.id, access=access) == []
    store.set_meta("reviewed_mapping_authorities", ["reviewed"])
    assert store.get_knowledge("EvidenceSpan", span.id, workspace_id=workspace.id, access=access) == span
    store.update_knowledge(membership.replace(enabled=False, policy_epoch=2))
    assert store.list_knowledge("EvidenceSpan", workspace_id=workspace.id, access=access) == []


@pytest.mark.parametrize("access", [Access(unrestricted=True), Principal.open().access])
def test_open_or_unrestricted_flag_cannot_bypass_managed_store_policy(store, access):
    workspace, _, span = managed_fixture(store)
    assert store.get_knowledge("EvidenceSpan", span.id, workspace_id=workspace.id, access=access) is None
    assert store.get_knowledge("EvidenceSpan", span.id, workspace_id=workspace.id, access=EVERYTHING) == span


def test_revoking_a_mapping_authority_invalidates_an_existing_proof(store):
    from hippo.knowledge.access import AuthorizationChanged

    workspace, user, _ = managed_fixture(store)
    store.put_knowledge(
        k.WorkspaceMembership(
            workspace_id=workspace.id,
            principal_id=user,
            enabled=True,
            mapping_authority="reviewed",
            policy_epoch=1,
        )
    )
    store.set_meta("reviewed_mapping_authorities", ["reviewed"])
    engine, proof = store._reader_proof(workspace.id, Access(user_id=user))
    assert proof.span_ids
    store.set_meta("reviewed_mapping_authorities", [])
    with pytest.raises(AuthorizationChanged):
        engine.validate_current(proof)


def test_mapping_revocation_during_configuration_read_cannot_build_stale_proof(store, monkeypatch):
    from hippo.knowledge.access import AuthorizationChanged

    workspace, user, _ = managed_fixture(store)
    store.put_knowledge(
        k.WorkspaceMembership(
            workspace_id=workspace.id,
            principal_id=user,
            enabled=True,
            mapping_authority="reviewed",
            policy_epoch=1,
        )
    )
    store.set_meta("reviewed_mapping_authorities", ["reviewed"])
    original = store.get_meta
    revoked = False

    def read(key):
        nonlocal revoked
        value = original(key)
        if key == "reviewed_mapping_authorities" and not revoked:
            revoked = True
            store.set_meta(key, [])
        return value

    monkeypatch.setattr(store, "get_meta", read)
    with pytest.raises(AuthorizationChanged):
        store.list_knowledge("EvidenceSpan", workspace_id=workspace.id, access=Access(user_id=user))


@pytest.mark.parametrize("state", ["active", "disabled", "deleted"])
def test_membership_control_records_are_not_public_evidence(store, state):
    workspace, user, _ = managed_fixture(store)
    membership = k.WorkspaceMembership(
        workspace_id=workspace.id,
        principal_id=user,
        enabled=True,
        mapping_authority="reviewed",
        policy_epoch=1,
    )
    store.put_knowledge(membership)
    store.set_meta("reviewed_mapping_authorities", ["reviewed"])
    if state == "disabled":
        store.update_user(user, disabled=True)
    elif state == "deleted":
        store.delete_user(user)
    access = Access(user_id=user)
    assert (
        store.get_knowledge("WorkspaceMembership", membership.id, workspace_id=workspace.id, access=access)
        is None
    )
    assert store.list_knowledge("WorkspaceMembership", workspace_id=workspace.id, access=access) == []
    assert (
        store.get_knowledge(
            "WorkspaceMembership", membership.id, workspace_id=workspace.id, access=EVERYTHING
        )
        == membership
    )
