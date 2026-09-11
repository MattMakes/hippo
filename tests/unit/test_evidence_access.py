"""Managed evidence authorization is independent of ranking and source prose."""

import importlib
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from hippo.access import EVERYTHING, Access, Principal
from hippo.knowledge import model as k

NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)


def api():
    try:
        return importlib.import_module("hippo.knowledge.access")
    except ModuleNotFoundError:
        pytest.fail("Task 4 evidence authorization core is missing")


class EvidenceStore:
    """A deterministic read-contract fixture; persistence is tested separately."""

    def __init__(self):
        self.records = defaultdict(dict)
        self.users = {name: {"id": name, "role_id": "reader", "disabled": False} for name in ("alice", "bob")}
        self.roles = {"reader": {"id": "reader", "rank": 0}}
        self.sources = {}
        self.native = {}
        self.epoch = 1

    def add(self, record):
        self.records[type(record).__name__][record.id] = record
        self.epoch += 1
        return record

    def _knowledge_rows(self, kind):
        return list(self.records[kind].values())

    def _knowledge_get(self, kind, identity):
        return (
            self.native.get((kind, identity))
            if kind in {"Symbol", "DataObject", "Commit"}
            else self.records[kind].get(identity)
        )

    def get_user(self, identity):
        return self.users.get(identity)

    def get_role(self, identity):
        return self.roles.get(identity)

    def get_source(self, identity):
        return self.sources.get(identity)

    def authorization_epoch(self):
        return self.epoch


def world():
    store = EvidenceStore()
    workspace = store.add(k.Workspace(name="test"))
    source = {"id": "s", "workspace_id": workspace.id, "min_rank": 0, "owner_id": None}
    store.sources[source["id"]] = source
    for name in ("alice", "bob"):
        store.add(
            k.WorkspaceMembership(
                workspace_id=workspace.id,
                principal_id=name,
                enabled=True,
                mapping_authority="reviewed",
                policy_epoch=1,
            )
        )
    parent = store.add(
        k.AccessPolicy(
            workspace_id=workspace.id,
            origin="local_curated",
            scope_key="source:s",
            mode="workspace",
            verified_at=NOW,
        )
    )
    artifact = store.add(
        k.Artifact(
            workspace_id=workspace.id,
            source_id="s",
            kind="file",
            external_id="notes.md",
            canonical_uri="source:s/notes.md",
            policy_id=parent.id,
        )
    )
    revision = store.add(
        k.ArtifactRevision(
            artifact_id=artifact.id, content_hash="h", raw_uri="blob:r", observed_at=NOW, lifecycle="active"
        )
    )
    return SimpleNamespace(
        store=store, workspace=workspace, source=source, parent=parent, artifact=artifact, revision=revision
    )


def policy(w, **changes):
    fields = dict(
        workspace_id=w.workspace.id,
        origin="local_curated",
        scope_key="source:s/private",
        mode="restricted",
        allow_users=("bob",),
        verified_at=NOW,
    )
    return w.store.add(k.AccessPolicy(**(fields | changes)))


def span(w, name, grant=None):
    return w.store.add(
        k.EvidenceSpan(
            revision_id=w.revision.id,
            locator_kind="field",
            locator_json='{"kind":"field","field_path":"' + name + '"}',
            text=name,
            policy_id=(grant or w.parent).id,
        )
    )


def observation(w, name, kind="service", grant=None):
    evidence = span(w, name, grant)
    obj = w.store.add(
        k.KnowledgeObject(workspace_id=w.workspace.id, kind=kind, canonical_key='["' + name + '"]')
    )
    obs = w.store.add(
        k.ObjectObservation(
            object_id=obj.id,
            revision_id=w.revision.id,
            span_id=evidence.id,
            evidence_class="declared",
            recorded_from=NOW,
            attributes_json='{"name":"' + name + '"}',
        )
    )
    return obj, obs, evidence


def engine(w, access=None, **kwargs):
    return api().EvidenceAccess(
        w.store,
        w.workspace.id,
        access or Access(user_id="alice"),
        mapping_authorities=frozenset({"reviewed"}),
        clock=lambda: NOW,
        **kwargs,
    )


def test_internal_open_and_preview_access_are_distinct():
    module = api()
    assert EVERYTHING.audience_kind == "internal"
    assert Principal.open().access.audience_kind == "open"
    principal = Principal.for_user({"id": "alice"}, {"id": "reader", "rank": 0})
    assert principal.as_role({"id": "reader", "rank": 0}).access.audience_kind == "preview"
    w = world()
    evidence = span(w, "public")
    for access in (
        Principal.open().access,
        Access(unrestricted=True),
        principal.as_role({"id": "reader", "rank": 0}).access,
    ):
        assert not engine(w, access).build().span_ids
    assert (
        evidence.id
        in module.EvidenceAccess(w.store, w.workspace.id, EVERYTHING, clock=lambda: NOW).build().span_ids
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing_user",
        "disabled",
        "missing_role",
        "missing_membership",
        "disabled_membership",
        "unreviewed_membership",
    ],
)
def test_managed_reader_requires_live_identity_and_reviewed_membership(change):
    api()
    w = world()
    span(w, "public")
    membership = next(m for m in w.store._knowledge_rows("WorkspaceMembership") if m.principal_id == "alice")
    if change == "missing_user":
        w.store.users.pop("alice")
    elif change == "disabled":
        w.store.users["alice"]["disabled"] = True
    elif change == "missing_role":
        w.store.roles.clear()
    elif change == "missing_membership":
        w.store.records["WorkspaceMembership"].pop(membership.id)
    elif change == "disabled_membership":
        w.store.add(membership.replace(enabled=False))
    else:
        w.store.add(membership.replace(mapping_authority="model_generated"))
    assert not engine(w, Access(rank=100, user_id="alice", unrestricted=True)).build().span_ids


def test_source_owner_and_rank_cannot_override_item_denial():
    api()
    w = world()
    w.source["owner_id"] = "alice"
    denied = span(w, "private", policy(w, allow_users=("alice",), deny_users=("alice",)))
    assert denied.id not in engine(w, Access(rank=100, user_id="alice")).build().span_ids
    w.source["owner_id"] = None
    w.source["min_rank"] = 40
    public = span(w, "public")
    assert public.id not in engine(w, Access(rank=100, user_id="alice")).build().span_ids


def test_reviewed_group_ids_grant_and_deny_without_name_merging():
    api()
    w = world()
    groups = [
        w.store.add(
            k.KnowledgeObject(
                workspace_id=w.workspace.id, kind="group", canonical_key='["' + host + '","engineering"]'
            )
        )
        for host in ("jira", "gitlab")
    ]
    w.store.add(
        k.GroupMembership(
            workspace_id=w.workspace.id,
            group_id=groups[0].id,
            principal_id="alice",
            enabled=True,
            mapping_authority="reviewed",
            policy_epoch=1,
        )
    )
    allowed = span(
        w,
        "group_allowed",
        policy(w, allow_users=(), allow_groups=(groups[0].id,), deny_groups=(groups[1].id,)),
    )
    denied = span(
        w, "group_denied", policy(w, allow_users=("alice",), deny_groups=(groups[0].id,), scope_key="denied")
    )
    other = span(
        w, "same_name_other_host", policy(w, allow_users=(), allow_groups=(groups[1].id,), scope_key="other")
    )
    view = engine(w).build()
    assert allowed.id in view.span_ids
    assert denied.id not in view.span_ids and other.id not in view.span_ids


@pytest.mark.parametrize(
    "changes",
    [
        dict(origin="legacy_unknown", scope_key=None),
        dict(mode="unknown"),
        dict(verified_at=NOW + timedelta(seconds=1)),
        dict(verified_at=NOW - timedelta(days=1), expires_at=NOW),
    ],
)
def test_unknown_and_expired_policy_grants_fail_closed(changes):
    api()
    w = world()
    evidence = span(w, "untrusted", policy(w, allow_users=("alice",), **changes))
    assert evidence.id not in engine(w).build().span_ids


def test_expiration_invalidates_without_an_epoch_change():
    module = api()
    w = world()
    deadline = NOW + timedelta(seconds=1)
    evidence = span(w, "expiring", policy(w, allow_users=("alice",), expires_at=deadline))
    clock = [NOW]
    access = module.EvidenceAccess(
        w.store,
        w.workspace.id,
        Access(user_id="alice"),
        mapping_authorities=frozenset({"reviewed"}),
        clock=lambda: clock[0],
    )
    view = access.build()
    assert evidence.id in view.span_ids and view.valid_until == deadline
    access.validate_current(view)
    clock[0] = deadline
    with pytest.raises(module.AuthorizationChanged):
        access.validate_current(view)
    assert evidence.id not in access.build().span_ids


def relationship(w, private_endpoint=False):
    subject, _, _ = observation(w, "billing")
    target, _, _ = observation(w, "orders", grant=policy(w) if private_endpoint else None)
    assertion = w.store.add(k.checked_assertion(subject, "DEPENDS_ON", target, scope_key="prod"))
    version = w.store.add(
        k.AssertionVersion(
            assertion_id=assertion.id,
            evidence_class="declared",
            rule_version="r",
            confidence=1.0,
            status="active",
            recorded_from=NOW,
        )
    )
    public, private = span(w, "mapping_code"), span(w, "private_mapping", policy(w))
    for item in (public, private):
        w.store.add(
            k.AssertionSupport(assertion_version_id=version.id, span_id=item.id, derivation_group="joint")
        )
    return assertion, version


def test_support_groups_are_complete_before_filtering_and_endpoints_are_independent():
    api()
    for private_endpoint in (False, True):
        w = world()
        assertion, version = relationship(w, private_endpoint)
        assert version.id not in engine(w).build().assertion_version_ids
        direct = span(w, "public_direct")
        support = w.store.add(
            k.AssertionSupport(
                assertion_version_id=version.id, span_id=direct.id, derivation_group="independent"
            )
        )
        view = engine(w).build()
        assert (version.id in view.assertion_version_ids) is (not private_endpoint)
        assert (assertion.id in view.assertion_ids) is (not private_endpoint)
        if not private_endpoint:
            assert support.id in view.support_ids
            assert all(group.derivation_group != "joint" for group in view.support_groups)


def test_observations_never_borrow_private_attributes_from_public_object_identity():
    api()
    w = world()
    obj, visible, _ = observation(w, "billing")
    hidden = span(w, "private_owner", policy(w))
    private = w.store.add(
        k.ObjectObservation(
            object_id=obj.id,
            revision_id=w.revision.id,
            span_id=hidden.id,
            evidence_class="declared",
            recorded_from=NOW,
            attributes_json='{"owner":"private-team"}',
        )
    )
    view = engine(w).build()
    assert obj.id in view.object_ids and visible.id in view.observation_ids
    assert private.id not in view.observation_ids


def test_current_suppressions_override_retained_evidence_and_history_rules():
    module = api()
    w = world()
    evidence = span(w, "retained")
    w.store.add(
        k.Suppression(
            workspace_id=w.workspace.id,
            target_kind="span",
            target_id=evidence.id,
            scope_key="source:s",
            view_applicability="current_only",
            reason="tombstone",
            epoch=1,
            created_at=NOW,
            restoration_barrier="refetch",
        )
    )
    assert evidence.id not in engine(w).build().span_ids
    assert evidence.id in engine(w).build(module.EvidenceSelection(query_mode="history")).span_ids
    w.store.add(
        k.Suppression(
            workspace_id=w.workspace.id,
            target_kind="artifact",
            target_id=w.artifact.id,
            scope_key="source:s",
            view_applicability="all_history",
            reason="access_loss",
            epoch=2,
            created_at=NOW,
            restoration_barrier="reverify",
        )
    )
    assert evidence.id not in engine(w).build(module.EvidenceSelection(query_mode="history")).span_ids


def test_policy_fingerprint_does_not_include_unreadable_evidence():
    module = api()
    w = world()
    span(w, "public")
    access = engine(w)
    before = access.build()
    span(w, "private-only", policy(w))
    after = access.build()
    assert before.policy_fingerprint == after.policy_fingerprint
    assert before.span_ids == after.span_ids
    with pytest.raises(module.AuthorizationChanged):
        access.validate_current(before)


def test_native_binding_requires_visible_span_object_and_selected_generation():
    module = api()
    w = world()
    obj, _, evidence = observation(w, "function", kind="symbol")
    gen = w.store.add(
        k.Generation(
            source_id="s",
            status="ready",
            parser_version="p",
            linker_version="l",
            embedding_profile="e",
            created_at=NOW,
            manifest_hash="h",
        )
    )
    w.store.add(k.GenerationMember(generation_id=gen.id, artifact_revision_id=w.revision.id))
    w.store.native[("Symbol", "symbol-native")] = {
        "id": "symbol-native",
        "source_id": "s",
        "doc": "Do not return this unchecked native body",
    }
    binding = w.store.add(
        k.NativeBinding(
            generation_id=gen.id,
            object_id=obj.id,
            native_kind="Symbol",
            native_id="symbol-native",
            span_id=evidence.id,
        )
    )
    view = engine(w).build(module.EvidenceSelection(generation_ids=frozenset({gen.id})))
    assert binding.id in view.native_binding_ids
    assert (
        binding.id
        not in engine(w).build(module.EvidenceSelection(generation_ids=frozenset())).native_binding_ids
    )
    assert not hasattr(view, "native_nodes")


def remote_world():
    w = world()
    connector = w.store.add(
        k.Connector(
            workspace_id=w.workspace.id, kind="jira_cloud", instance_url="https://jira.example", enabled=True
        )
    )
    parent = policy(w, origin="provider", mode="workspace", expires_at=NOW + timedelta(minutes=10))
    artifact = w.store.add(
        k.Artifact(
            workspace_id=w.workspace.id,
            source_id="s",
            connector_id=connector.id,
            provider_instance=connector.instance_url,
            kind="ticket",
            external_id="T-1",
            canonical_uri="https://jira.example/T-1",
            policy_id=parent.id,
        )
    )
    revision = w.store.add(
        k.ArtifactRevision(
            artifact_id=artifact.id,
            content_hash="remote",
            raw_uri="blob:remote",
            observed_at=NOW,
            lifecycle="active",
        )
    )
    w.connector, w.parent, w.artifact, w.revision = connector, parent, artifact, revision
    return w


@pytest.mark.parametrize(
    "change",
    [
        "curated_parent",
        "curated_child",
        "unknown_connector",
        "wrong_instance",
        "disabled_connector",
        "no_deadline",
    ],
)
def test_provider_origin_and_connector_boundary_fail_closed(change):
    w = remote_world()
    child = w.parent
    if change == "curated_parent":
        parent = policy(w, mode="workspace")
        w.store.add(w.artifact.replace(policy_id=parent.id))
    elif change == "curated_child":
        child = policy(w, mode="workspace")
    elif change == "unknown_connector":
        w.store.records["Connector"].clear()
    elif change == "wrong_instance":
        w.store.records["Connector"][w.connector.id] = w.connector.replace(
            instance_url="https://other.example"
        )
    elif change == "disabled_connector":
        w.store.add(w.connector.replace(enabled=False))
    else:
        child = policy(w, origin="provider", mode="workspace", scope_key="no-deadline")
    evidence = span(w, "remote-secret", child)
    assert evidence.id not in engine(w).build().span_ids


def test_provider_freshness_deadline_uses_the_earliest_configured_bound():
    w = remote_world()
    evidence = span(w, "remote-allowed")
    view = engine(w, policy_max_age=timedelta(minutes=2)).build()
    assert evidence.id in view.span_ids
    assert view.valid_until == NOW + timedelta(minutes=2)
    child = policy(w, origin="provider", mode="workspace", scope_key="age-only")
    second = span(w, "age-only", child)
    assert second.id in engine(w, policy_max_age=timedelta(minutes=2)).build().span_ids


def test_child_workspace_policy_cannot_broaden_a_restricted_parent():
    w = world()
    w.store.add(w.artifact.replace(policy_id=policy(w).id))
    evidence = span(w, "child-public")
    assert evidence.id not in engine(w).build().span_ids


def test_revocation_during_inventory_rejects_the_entire_proof():
    module = api()
    w = world()
    span(w, "public")
    original = w.store._knowledge_rows

    def changing_rows(kind):
        if kind == "AssertionSupport":
            w.store.epoch += 1
        return original(kind)

    w.store._knowledge_rows = changing_rows
    with pytest.raises(module.AuthorizationChanged):
        engine(w).build()


def test_revalidation_detects_live_user_disabling_even_without_fixture_epoch_bump():
    module = api()
    w = world()
    span(w, "public")
    access = engine(w)
    before = access.build()
    w.store.users["alice"]["disabled"] = True
    with pytest.raises(module.AuthorizationChanged):
        access.validate_current(before)


def test_native_binding_requires_its_own_generation_membership():
    w = world()
    obj, _, evidence = observation(w, "function", kind="symbol")
    generation = w.store.add(
        k.Generation(
            source_id="s",
            status="ready",
            parser_version="p",
            linker_version="l",
            embedding_profile="e",
            created_at=NOW,
            manifest_hash="h",
        )
    )
    w.store.native[("Symbol", "native")] = {"source_id": "s"}
    binding = w.store.add(
        k.NativeBinding(
            generation_id=generation.id,
            object_id=obj.id,
            native_kind="Symbol",
            native_id="native",
            span_id=evidence.id,
        )
    )
    assert binding.id not in engine(w).build().native_binding_ids


def test_selection_and_authorized_proofs_are_immutable():
    from dataclasses import FrozenInstanceError

    module = api()
    w = world()
    span(w, "public")
    view = engine(w).build()
    with pytest.raises(FrozenInstanceError):
        view.span_ids = frozenset()
    with pytest.raises(ValueError):
        module.EvidenceSelection(revision_ids={w.revision.id})
    with pytest.raises(ValueError):
        module.EvidenceSelection(query_mode="anything")


def test_authority_configuration_is_required_and_cannot_be_inferred_from_names():
    module = api()
    w = world()
    span(w, "public")
    assert (
        not module.EvidenceAccess(w.store, w.workspace.id, Access(user_id="alice"), clock=lambda: NOW)
        .build()
        .span_ids
    )


@pytest.mark.parametrize("operation", ["build", "validate"])
def test_expiry_crossing_during_inventory_rejects_the_proof(operation):
    module = api()
    w = world()
    deadline = NOW + timedelta(seconds=1)
    span(w, "expires-during-read", policy(w, allow_users=("alice",), expires_at=deadline))
    clock = [NOW]
    access = module.EvidenceAccess(
        w.store,
        w.workspace.id,
        Access(user_id="alice"),
        mapping_authorities=frozenset({"reviewed"}),
        clock=lambda: clock[0],
    )
    view = access.build()
    original = w.store._knowledge_rows

    def crossing_rows(kind):
        if kind == "NativeBinding":
            clock[0] = deadline
        return original(kind)

    w.store._knowledge_rows = crossing_rows
    with pytest.raises(module.AuthorizationChanged):
        if operation == "build":
            access.build()
        else:
            access.validate_current(view)


@pytest.mark.parametrize("change", ["epoch", "expiry"])
def test_validate_checks_the_boundary_after_rebuilding(change):
    module = api()
    w = world()
    deadline = NOW + timedelta(seconds=1)
    span(w, "final-boundary", policy(w, allow_users=("alice",), expires_at=deadline))
    clock = [NOW]
    access = module.EvidenceAccess(
        w.store,
        w.workspace.id,
        Access(user_id="alice"),
        mapping_authorities=frozenset({"reviewed"}),
        clock=lambda: clock[0],
    )
    view = access.build()
    original = access.build

    def change_after_build(selection=None):
        current = original(selection)
        if change == "epoch":
            w.store.epoch += 1
        else:
            clock[0] = deadline
        return current

    access.build = change_after_build
    with pytest.raises(module.AuthorizationChanged):
        access.validate_current(view)


def test_selected_support_cannot_borrow_an_unselected_revision():
    module = api()
    w = world()
    _, version = relationship(w)
    first = w.revision.id
    w.revision = w.store.add(
        k.ArtifactRevision(
            artifact_id=w.artifact.id,
            content_hash="other",
            raw_uri="blob:other",
            observed_at=NOW,
            lifecycle="active",
        )
    )
    independent = span(w, "other-revision-support")
    w.store.add(
        k.AssertionSupport(
            assertion_version_id=version.id, span_id=independent.id, derivation_group="other-revision"
        )
    )
    assert version.id in engine(w).build().assertion_version_ids
    selection = module.EvidenceSelection(revision_ids=frozenset({first}))
    assert version.id not in engine(w).build(selection).assertion_version_ids


def test_principal_specific_suppression_does_not_revoke_other_users():
    w = world()
    evidence = span(w, "shared")
    w.store.add(
        k.Suppression(
            workspace_id=w.workspace.id,
            target_kind="span",
            target_id=evidence.id,
            scope_key="s",
            all_principals=False,
            principal_ids=("alice",),
            view_applicability="all_history",
            reason="access_loss",
            epoch=1,
            created_at=NOW,
            restoration_barrier="reverify",
        )
    )
    assert evidence.id not in engine(w).build().span_ids
    assert evidence.id in engine(w, Access(user_id="bob")).build().span_ids


def test_foreign_workspace_group_membership_does_not_grant_access():
    w = world()
    other = w.store.add(k.Workspace(name="other"))
    group = w.store.add(
        k.KnowledgeObject(workspace_id=other.id, kind="group", canonical_key='["engineering"]')
    )
    w.store.add(
        k.GroupMembership(
            workspace_id=w.workspace.id,
            group_id=group.id,
            principal_id="alice",
            enabled=True,
            mapping_authority="reviewed",
            policy_epoch=1,
        )
    )
    evidence = span(w, "foreign-group", policy(w, allow_users=(), allow_groups=(group.id,)))
    assert evidence.id not in engine(w).build().span_ids


def test_policy_and_source_workspaces_are_independent_authorization_boundaries():
    w = world()
    other = w.store.add(k.Workspace(name="other"))
    foreign = policy(w, workspace_id=other.id, allow_users=("alice",))
    evidence = span(w, "wrong-policy-workspace", foreign)
    assert evidence.id not in engine(w).build().span_ids
    public = span(w, "wrong-source-workspace")
    w.source["workspace_id"] = other.id
    assert public.id not in engine(w).build().span_ids
