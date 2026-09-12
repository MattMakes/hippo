"""Prospective build permissions use live evidence policies without publishing rows."""

import importlib
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from hippo.access import Principal
from hippo.knowledge import model as k
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.identity import text_hash

NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)


def api():
    try:
        return importlib.import_module("hippo.knowledge.build_authority")
    except ModuleNotFoundError:
        pytest.fail("Prospective build authority is missing")


def world(store, *, existing=False):
    module = api()
    store.ensure_schema()
    store.ensure_roles()
    user = store.create_user("builder", "password", "individual")
    source = store.create_source("file", "Notes", {"file": "notes.md"}, owner_id=user)
    workspace = store.get_source(source)["workspace_id"]
    membership = k.WorkspaceMembership(
        workspace_id=workspace, principal_id=user, mapping_authority="local", enabled=True, policy_epoch=1
    )
    store.put_knowledge(membership)
    store.set_meta("reviewed_mapping_authorities", ["local"])
    policy = k.AccessPolicy(
        workspace_id=workspace,
        origin="local_curated",
        scope_key=f"source:{source}:plain-prose-v1",
        mode="workspace",
        verified_at=NOW,
    )
    artifact = k.Artifact(
        workspace_id=workspace,
        source_id=source,
        kind="file",
        external_id="notes.md",
        canonical_uri=f"source:{source}/notes.md",
        policy_id=policy.id,
    )
    revision = k.ArtifactRevision(
        artifact_id=artifact.id,
        content_hash="a" * 64,
        raw_uri="hippo-raw:sha256:" + "a" * 64,
        observed_at=NOW,
        lifecycle="active",
    )
    span = k.EvidenceSpan(
        revision_id=revision.id,
        locator_kind="field",
        locator_json='{"kind":"field","field_path":"body"}',
        text="Private original",
        policy_id=policy.id,
    )
    if existing:
        for record in (policy, artifact, revision, span):
            store.put_knowledge(record)
    actor = module.BuildActor.reader(Principal.for_user(store.get_user(user), store.get_role("individual")))
    inputs = module.AcceptedBuildInputs(
        pairs=((artifact, revision),), spans=(span,), planned_policies=() if existing else (policy,)
    )
    return SimpleNamespace(**locals())


def guard(w, accepted=None, **kwargs):
    return w.module.capture_build_authority(
        w.store,
        source_id=w.source,
        actor=w.actor,
        accepted=w.inputs if accepted is None else accepted,
        clock=kwargs.pop("clock", lambda: NOW),
        **kwargs,
    )


def suppress(w, kind, identity):
    w.store.put_knowledge(
        k.Suppression(
            workspace_id=w.workspace,
            target_kind=kind,
            target_id=identity,
            scope_key="test",
            view_applicability="all_history",
            reason="access_loss",
            epoch=1,
            created_at=NOW,
            restoration_barrier="restore",
        )
    )


def test_prospective_originals_authorized_without_staging_or_epoch_mutation(store):
    w = world(store)
    before = (
        store.authorization_epoch(),
        store.suppression_epoch(),
        store.content_epoch(),
        store.get_source(w.source),
    )
    value = guard(w)
    assert value.check_local() is None
    assert value.check() is None
    assert (
        store.authorization_epoch(),
        store.suppression_epoch(),
        store.content_epoch(),
        store.get_source(w.source),
    ) == before
    for kind in ("Artifact", "ArtifactRevision", "EvidenceSpan", "Generation", "AccessPolicy"):
        assert store._knowledge_rows(kind) == []
    with pytest.raises(FrozenInstanceError):
        value.source_control.owner_id = "other"
    with pytest.raises(FrozenInstanceError):
        w.inputs.pairs = ()


@pytest.mark.parametrize("fault", ["membership", "disabled", "deleted", "manager", "rank"])
def test_live_identity_and_source_management_required(store, fault):
    w = world(store)
    if fault == "membership":
        store.update_knowledge(w.membership.replace(enabled=False, policy_epoch=2))
    elif fault == "disabled":
        store.update_user(w.user, disabled=True)
    elif fault == "deleted":
        store.delete_user(w.user)
    elif fault == "manager":
        store.set_source_access(w.source, None, owner_id=None)
    else:
        store.set_source_access(w.source, "arch-admin", owner_id=None)
        store.update_role("individual", capabilities=["manage_sources"])
    with pytest.raises(AuthorizationChanged):
        guard(w)


@pytest.mark.parametrize("target", ["source", "artifact", "revision", "span", "policy"])
def test_existing_and_prospective_suppressions_are_honored(store, target):
    w = world(store, existing=target != "source")
    identity = w.source if target == "source" else getattr(w, target).id
    suppress(w, target, identity)
    with pytest.raises(AuthorizationChanged):
        guard(w)


def test_empty_precapture_guard_still_enforces_membership_and_source_suppression(store):
    w = world(store)
    value = guard(w, w.module.AcceptedBuildInputs())
    assert value.check_local() is None
    suppress(w, "source", w.source)
    with pytest.raises(AuthorizationChanged):
        guard(w, w.module.AcceptedBuildInputs())


def test_bind_inputs_keeps_original_epoch_and_denies_stale_guard(store):
    w = world(store)
    value = guard(w, w.module.AcceptedBuildInputs())
    child = value.bind_inputs(w.inputs)
    child.check_local()
    store.update_user(w.user, display_name="new")
    with pytest.raises(AuthorizationChanged):
        value.bind_inputs(w.inputs)
    with pytest.raises(AuthorizationChanged):
        child.check_local()


@pytest.mark.parametrize("fault", ["missing", "existing_replacement", "planned_grants", "foreign_scope"])
def test_planned_policy_is_explicit_exact_source_local_grant(store, fault):
    w = world(store, existing=fault == "existing_replacement")
    if fault == "missing":
        accepted = replace(w.inputs, planned_policies=())
    else:
        policy = w.policy.replace(
            **({"deny_users": (w.user,)} if fault != "foreign_scope" else {"scope_key": "other"})
        )
        if fault == "existing_replacement":
            policy = w.policy.replace(verified_at=NOW + timedelta(seconds=1))
        accepted = replace(w.inputs, planned_policies=(policy,))
    with pytest.raises((ValueError, AuthorizationChanged)):
        guard(w, accepted)


@pytest.mark.parametrize("internal", [False, True])
@pytest.mark.parametrize("fault", ["legacy", "provider", "future", "expired", "tombstone", "retired"])
def test_incompatible_input_rejected_even_for_trusted_local(store, internal, fault):
    w = world(store)
    policy, artifact, revision = w.policy, w.artifact, w.revision
    if fault == "legacy":
        policy = policy.replace(origin="legacy_unknown", scope_key=None)
    elif fault == "provider":
        policy = policy.replace(origin="provider")
    elif fault == "future":
        policy = policy.replace(verified_at=NOW + timedelta(seconds=1))
    elif fault == "expired":
        policy = policy.replace(verified_at=NOW - timedelta(days=1), expires_at=NOW)
    elif fault == "tombstone":
        artifact = artifact.replace(deleted_at=NOW)
    else:
        revision = revision.replace(lifecycle="deleted")
    store.put_knowledge(policy)
    artifact = artifact.replace(policy_id=policy.id)
    accepted = w.module.AcceptedBuildInputs(pairs=((artifact, revision),))
    if internal:
        w.actor = w.module.BuildActor.trusted_local()
    with pytest.raises((ValueError, AuthorizationChanged)):
        guard(w, accepted)


def test_hidden_secondary_span_denies_whole_input_without_overriding_existing_policy(store):
    w = world(store, existing=True)
    deny = w.policy.replace(scope_key="private", mode="restricted", allow_users=("other",))
    store.put_knowledge(deny)
    hidden = w.span.replace(
        text="Hidden secondary", text_hash=text_hash("Hidden secondary"), policy_id=deny.id
    )
    accepted = replace(w.inputs, spans=(w.span, hidden))
    with pytest.raises(AuthorizationChanged):
        guard(w, accepted)


def test_policy_expiry_rechecked_without_epoch_mutation(store):
    w = world(store)
    policy = w.policy.replace(expires_at=NOW + timedelta(seconds=1))
    store.put_knowledge(policy)
    accepted = replace(w.inputs, planned_policies=())
    now = [NOW]
    value = guard(w, accepted, clock=lambda: now[0])
    now[0] += timedelta(seconds=1)
    with pytest.raises(AuthorizationChanged):
        value.check_local()


def test_source_input_change_without_epoch_invalidates_but_progress_does_not(store):
    w = world(store)
    value = guard(w)
    store.update_source(w.source, progress_done=1, stage="reading")
    value.check_local()
    before = store.authorization_epoch()
    store.update_source(w.source, meta_json='{"file":"changed.md"}')
    assert store.authorization_epoch() == before
    with pytest.raises(AuthorizationChanged):
        value.check_local()


def test_existing_revision_cannot_be_represented_with_new_observation_metadata(store):
    w = world(store, existing=True)
    accepted = replace(
        w.inputs, pairs=((w.artifact, w.revision.replace(observed_at=NOW + timedelta(seconds=1))),)
    )
    with pytest.raises(AuthorizationChanged):
        guard(w, accepted)


def test_transaction_local_check_and_external_callback_boundary(store):
    w = world(store)
    value = guard(w)
    calls = []
    with store.transaction():
        value.check_local()
        with pytest.raises(RuntimeError):
            value.check(checkpoint=lambda: calls.append("called"))
    assert calls == []


@pytest.mark.parametrize("failure", ["close", "revocation"])
def test_blocked_callback_cannot_resume_after_close_or_concurrent_failure(store, failure):
    w = world(store)
    value = guard(w)
    entered, release = Event(), Event()
    errors = []

    def checkpoint():
        entered.set()
        assert release.wait(5)

    def run():
        try:
            value.check(checkpoint=checkpoint)
        except BaseException as exc:
            errors.append(exc)

    thread = Thread(target=run)
    thread.start()
    try:
        assert entered.wait(5)
        if failure == "close":
            value.close()
        else:
            store.update_user(w.user, disabled=True)
            with pytest.raises(AuthorizationChanged):
                value.check_local()
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive() and len(errors) == 1
    with pytest.raises(AuthorizationChanged):
        value.check_local()


def test_open_preview_and_mutable_inputs_cannot_become_build_authority(store):
    w = world(store)
    for principal in (Principal.open(), Principal.open().as_role(store.get_role("individual"))):
        with pytest.raises(ValueError):
            w.module.BuildActor.reader(principal)
    with pytest.raises(ValueError):
        w.module.AcceptedBuildInputs(pairs=list(w.inputs.pairs))


def test_core_source_requirement_reuses_current_and_history_suppression(store):
    from hippo.access import Access
    from hippo.knowledge.access import EvidenceAccess

    w = world(store)
    access = EvidenceAccess(
        store,
        w.workspace,
        Access(user_id=w.user),
        mapping_authorities=frozenset({"local"}),
        clock=lambda: NOW,
    )
    store.put_knowledge(
        k.Suppression(
            workspace_id=w.workspace,
            target_kind="source",
            target_id=w.source,
            scope_key="test",
            view_applicability="current_only",
            reason="tombstone",
            epoch=1,
            created_at=NOW,
            restoration_barrier="restore",
        )
    )
    with pytest.raises(AuthorizationChanged):
        access.require_source(w.source)
    assert access.require_source(w.source, query_mode="history") is None
    with pytest.raises(ValueError):
        access.require_source(w.source, query_mode="invalid")
    access.workspace_id = "missing-workspace"
    with pytest.raises(ValueError):
        access.require_source(w.source, query_mode="invalid")


def test_unknown_source_input_metadata_cannot_evade_control_cas(store):
    w = world(store)
    value = guard(w)
    store.update_source(w.source, meta_json='{"file":"notes.md","decoder":"different"}')
    with pytest.raises(AuthorizationChanged):
        value.check_local()


def test_local_maintenance_remains_explicit_and_respects_source_suppression(store):
    w = world(store)
    w.actor = w.module.BuildActor.trusted_local()
    store.update_knowledge(w.membership.replace(enabled=False, policy_epoch=2))
    value = guard(w)
    value.check_local()
    suppress(w, "source", w.source)
    with pytest.raises(AuthorizationChanged):
        guard(w)


def test_revocation_during_binding_does_not_rebase_to_new_epoch(store, monkeypatch):
    w = world(store)
    value = guard(w, w.module.AcceptedBuildInputs())
    original = w.module.EvidenceAccess.build
    changed = False

    def revoke(core, selection=None):
        nonlocal changed
        result = original(core, selection)
        if not changed:
            changed = True
            store.update_user(w.user, disabled=True)
        return result

    monkeypatch.setattr(w.module.EvidenceAccess, "build", revoke)
    with pytest.raises(AuthorizationChanged):
        value.bind_inputs(w.inputs)


def test_live_reader_role_is_reloaded_before_management_decision(store):
    w = world(store)
    store.update_user(w.user, role_id="arch-admin")
    w.actor = w.module.BuildActor.reader(
        Principal.for_user(store.get_user(w.user), store.get_role("arch-admin"))
    )
    store.set_source_access(w.source, None, owner_id=None)
    store.update_user(w.user, role_id="individual")
    with pytest.raises(AuthorizationChanged):
        guard(w)


def test_binding_checks_hold_source_lock_and_do_not_reset_authority(store, monkeypatch):
    w = world(store)
    value = guard(w, w.module.AcceptedBuildInputs())
    original_lock = store._lock_source
    original_require = w.module.EvidenceAccess.require_source
    locked = []

    def lock(identity):
        original_lock(identity)
        locked.append(identity)

    def require(core, *args, **kwargs):
        assert locked == [w.source], "Prospective binding must hold source/authorization lock"
        assert getattr(store, "_transaction_depth", 0) or getattr(store, "_transaction", None) is not None
        return original_require(core, *args, **kwargs)

    monkeypatch.setattr(store, "_lock_source", lock)
    monkeypatch.setattr(w.module.EvidenceAccess, "require_source", require)
    value.bind_inputs(w.inputs)


def test_captured_epochs_are_readonly_and_do_not_follow_store_changes(store):
    w = world(store)
    value = guard(w)
    initial = store.authorization_epoch(), store.suppression_epoch()
    assert (value.expected_authorization_epoch, value.expected_suppression_epoch) == initial
    with pytest.raises(AttributeError):
        value.expected_authorization_epoch = 0
    store.update_user(w.user, display_name="changed")
    assert (value.expected_authorization_epoch, value.expected_suppression_epoch) == initial
    with pytest.raises(AuthorizationChanged):
        value.check_local()
