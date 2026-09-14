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


def world(store, *, existing=False, kind="file"):
    module = api()
    store.ensure_schema()
    store.ensure_roles()
    user = store.create_user("builder", "password", "individual")
    source = store.create_source(kind, "Notes", {"file": "notes.md"}, owner_id=user)
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


def join_group(w, name="builders"):
    """An enabled group membership for the builder, written before capture: it bumps the epoch."""
    group = k.KnowledgeObject(workspace_id=w.workspace, kind="group", canonical_key=f'["{name}"]')
    w.store.put_knowledge(group)
    w.store.put_knowledge(
        k.GroupMembership(
            workspace_id=w.workspace,
            group_id=group.id,
            principal_id=w.user,
            enabled=True,
            mapping_authority="local",
            policy_epoch=1,
        )
    )
    return group


def test_a_group_member_builder_looks_its_groups_up_by_id_on_every_check(store):
    """R21-M2: every `check_local` of a group member read the whole `KnowledgeObject` table.

    Capture proves the accepted inputs, which is where the groups are resolved; the checks after it
    must not read the table whole either.
    """
    w = world(store, existing=True)
    group = join_group(w)
    store.put_knowledge(k.KnowledgeObject(workspace_id=w.workspace, kind="symbol", canonical_key='["a","f"]'))
    reads = []
    original = store._knowledge_rows

    def rows(kind, **scope):
        reads.append((kind, {key: item for key, item in scope.items() if item is not None}))
        return original(kind, **scope)

    store._knowledge_rows = rows
    try:
        value = guard(w)
        value.check_local()
        value.check()
    finally:
        del store._knowledge_rows
    objects = [scope for kind, scope in reads if kind == "KnowledgeObject"]
    assert objects and all(scope == {"ids": [group.id]} for scope in objects), objects


def test_the_overlay_answers_the_scoped_read_contract(store):
    """A live kind forwards its key to the store; an accepted-input kind is filtered in place."""
    w = world(store, existing=True)
    group = join_group(w)
    overlay = w.module._Overlay(store, w.inputs)
    assert overlay._knowledge_rows("KnowledgeObject", ids=[group.id, "absent", group.id]) == [group]
    assert overlay._knowledge_get("KnowledgeObject", group.id) == group
    assert overlay._knowledge_rows("EvidenceSpan", ids=["absent", w.span.id, w.span.id]) == [w.span]
    assert overlay._knowledge_rows("EvidenceSpan", where={"revision_id": w.revision.id}) == [w.span]
    assert overlay._knowledge_rows("EvidenceSpan", where={"revision_id": "other"}) == []
    assert overlay._knowledge_get("Artifact", w.artifact.id) == w.artifact
    assert overlay._knowledge_rows("GenerationMember", generation_id="any") == []
    with pytest.raises(ValueError, match="scoped by ids alone"):
        overlay._knowledge_rows("EvidenceSpan", ids=[w.span.id], where={"revision_id": w.revision.id})


def test_the_accepted_inputs_are_proven_once_per_authority_and_afresh_after_a_rebaseline(store):
    """R21-M1: every `check_local` re-read and re-proved every accepted pair and span."""
    w = world(store, existing=True)
    value = guard(w)
    reads = []
    original = store._knowledge_rows

    def rows(kind, **scope):
        reads.append(kind)
        return original(kind, **scope)

    accepted = {"Artifact", "ArtifactRevision", "EvidenceSpan"}
    store._knowledge_rows = rows
    try:
        value.check_local()
        value.check()
        assert accepted.isdisjoint(reads), reads
        bump(store, "authorization_epoch")
        child = value.rebaseline()
        assert accepted <= set(reads), "the child proves every accepted input again"
        reads.clear()
        child.check_local()
        assert accepted.isdisjoint(reads), reads
    finally:
        del store._knowledge_rows


def test_a_builders_groups_change_only_with_a_membership_which_moves_the_epoch(store):
    """The premise of proving once: a knowledge object write moves only the content epoch, so a
    reader's groups must not be able to change through one. A membership cannot name a group object
    that does not exist yet, and a membership write moves the authorization epoch."""
    w = world(store, existing=True)
    value = guard(w)
    absent = k.KnowledgeObject(workspace_id=w.workspace, kind="group", canonical_key='["later"]')
    membership = k.GroupMembership(
        workspace_id=w.workspace,
        group_id=absent.id,
        principal_id=w.user,
        enabled=True,
        mapping_authority="local",
        policy_epoch=1,
    )
    with pytest.raises(ValueError, match="Missing KnowledgeObject reference"):
        store.put_knowledge(membership)
    epoch = store.authorization_epoch()
    store.put_knowledge(absent)
    assert store.authorization_epoch() == epoch
    value.check_local()
    store.put_knowledge(membership)
    assert store.authorization_epoch() != epoch
    with pytest.raises(AuthorizationChanged, match="authorization or suppression changed"):
        value.check_local()


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


# --------------------------------------------- CC8: code sources and long builds


@pytest.mark.parametrize("kind", ["text", "file", "repo", "archive"])
def test_every_managed_capture_kind_can_hold_build_authority(store, kind):
    """Design review B3: `repo` and `archive` were refused outright before CC8."""
    w = world(store, kind=kind)
    assert guard(w).source_control.kind == kind


@pytest.mark.parametrize("kind", ["url", "unknown"])
def test_an_unsupported_source_kind_keeps_the_identical_denial(store, kind):
    w = world(store, kind=kind)
    with pytest.raises(AuthorizationChanged, match="^Build actor cannot manage source$"):
        guard(w)


def test_the_managed_term_is_the_row_alone_and_reads_no_record_table(store, monkeypatch):
    """B3's second half: the Artifact/Generation presence scan ran on every batch."""
    w = world(store, existing=True)
    seen = []
    original = store._knowledge_rows

    def rows(kind, **kwargs):
        seen.append(kind)
        return original(kind, **kwargs)

    monkeypatch.setattr(store, "_knowledge_rows", rows)
    assert w.module._source_control(store, w.source).managed is True
    assert "Artifact" not in seen and "Generation" not in seen, "no record table is scanned"
    # Ruling 9 keeps the store's own flag flipping at staging start, so the answer is the
    # same; what changed is that it is read from the Source row instead of rediscovered.
    store._source_fields(w.source, managed=False)
    assert w.module._source_control(store, w.source).managed is False


def test_the_managed_term_follows_the_row_flag_and_the_active_pointer(store):
    w = world(store)
    module = w.module
    assert module._source_control(store, w.source).managed is False
    store._source_fields(w.source, managed=True)
    assert module._source_control(store, w.source).managed is True
    store._source_fields(w.source, managed=False, active_generation_id="generation-1")
    assert module._source_control(store, w.source).managed is True


def test_a_stale_meta_managed_marker_no_longer_classifies_a_source(store):
    """CC1 retired `meta['managed']` as a lane marker; nothing writes it."""
    w = world(store)
    store.update_source(w.source, meta_json='{"file":"notes.md","managed":true}')
    assert w.module._source_control(store, w.source).managed is False


def _pair(w, **changes):
    artifact = w.artifact.replace(**changes)
    return artifact, w.revision.replace(artifact_id=artifact.id)


@pytest.mark.parametrize("kind", ["repository", "history_event"])
def test_a_code_accepted_artifact_kind_is_an_active_local_input(store, kind):
    """A captured tree and a commit are accepted inputs as much as a file is."""
    w = world(store)
    accepted = w.module.AcceptedBuildInputs(pairs=(_pair(w, kind=kind),), planned_policies=(w.policy,))
    guard(w, accepted)


def test_an_artifact_kind_outside_the_code_and_prose_set_still_refuses(store):
    w = world(store)
    accepted = w.module.AcceptedBuildInputs(pairs=(_pair(w, kind="ticket"),), planned_policies=(w.policy,))
    with pytest.raises(AuthorizationChanged, match="not an active local input"):
        guard(w, accepted)


def test_a_planned_policy_may_carry_the_code_scope_key(store):
    w = world(store)
    module = w.module
    policy = w.policy.replace(scope_key=f"source:{w.source}:{module.MANAGED_CODE_SCOPE}")
    artifact, revision = _pair(w, policy_id=policy.id)
    span = w.span.replace(revision_id=revision.id, policy_id=policy.id)
    accepted = module.AcceptedBuildInputs(
        pairs=((artifact, revision),), spans=(span,), planned_policies=(policy,)
    )
    guard(w, accepted)
    assert module.PLANNED_POLICY_SCOPES == (module.PLAIN_PROSE_SCOPE, module.MANAGED_CODE_SCOPE)


def test_a_planned_policy_scope_key_outside_the_closed_set_refuses(store):
    w = world(store)
    policy = w.policy.replace(scope_key=f"source:{w.source}:invented-v1")
    artifact, revision = _pair(w, policy_id=policy.id)
    span = w.span.replace(revision_id=revision.id, policy_id=policy.id)
    accepted = w.module.AcceptedBuildInputs(
        pairs=((artifact, revision),), spans=(span,), planned_policies=(policy,)
    )
    with pytest.raises(AuthorizationChanged, match="explicit local source grant"):
        guard(w, accepted)


def bump(store, name):
    from hippo.store.authorization import bump_epoch

    bump_epoch(store, name)


def test_rebaseline_adopts_an_unrelated_authorization_epoch_and_freezes_the_rest(store):
    w = world(store, existing=True)
    value = guard(w)
    frozen = value.expected_suppression_epoch
    bump(store, "authorization_epoch")
    child = value.rebaseline()
    assert child is not value
    assert child.expected_authorization_epoch == store.authorization_epoch()
    assert child.expected_suppression_epoch == frozen
    assert child.source_control == value.source_control
    assert child.check_local() is None
    assert value.expected_authorization_epoch != child.expected_authorization_epoch


def test_a_rebaseline_must_precede_the_failing_check_not_follow_it(store):
    """`check_local` latches its own refusal, so the coordinator rebaselines first.

    An epoch mismatch seen through `check_local()` is a sticky failure by design, and
    ruling 2 forbids a rebaseline after one. The coordinator therefore compares the
    store's authorization epoch with `expected_authorization_epoch` between batches and
    rebaselines *before* its next external check.
    """
    w = world(store, existing=True)
    value = guard(w)
    bump(store, "authorization_epoch")
    assert store.authorization_epoch() != value.expected_authorization_epoch
    with pytest.raises(AuthorizationChanged):
        value.check_local()
    with pytest.raises(AuthorizationChanged):
        value.rebaseline()


def test_rebaseline_refuses_after_a_capability_loss_and_latches(store):
    """Ruling 2 (R21-M4): the child's capability proof refuses, not the `SourceControl` comparison.

    The builder is not the owner and manages the source only through its role, so losing that one
    capability leaves the Source row, and with it `SourceControl`, exactly as captured. Only
    `child.check_local()` inside `rebaseline` can see the loss.
    """
    w = world(store, existing=True)
    store.update_role("individual", capabilities=["add_sources", "manage_sources"])
    store.set_source_access(w.source, None, owner_id=None)
    value = guard(w)
    store.update_role("individual", capabilities=["add_sources"])
    assert w.module._source_control(store, w.source) == value.source_control
    assert store.suppression_epoch() == value.expected_suppression_epoch
    with pytest.raises(AuthorizationChanged, match="cannot manage source"):
        value.rebaseline()
    with pytest.raises(AuthorizationChanged, match="cannot manage source"):
        value.rebaseline()


def test_rebaseline_refuses_any_suppression_epoch_change(store):
    w = world(store, existing=True)
    value = guard(w)
    bump(store, "suppression_epoch")
    with pytest.raises(AuthorizationChanged, match="suppression"):
        value.rebaseline()


@pytest.mark.parametrize("field", ["access_role_id", "min_rank", "owner_id"])
def test_rebaseline_refuses_a_changed_source_control_even_with_every_capability(store, field):
    """Design review M6: `source_control` is frozen at capture and never adopted."""
    w = world(store, existing=True)
    value = guard(w)
    store.update_role("individual", capabilities=["manage_sources"])
    if field == "owner_id":
        store._source_fields(w.source, owner_id=None)
    elif field == "min_rank":
        store._source_fields(w.source, min_rank=1)
    else:
        store._source_fields(w.source, access_role_id="individual")
    with pytest.raises(AuthorizationChanged, match="Source controls changed"):
        value.rebaseline()


def test_rebaseline_refuses_after_a_sticky_failure(store):
    w = world(store, existing=True)
    value = guard(w)
    store.update_user(w.user, disabled=True)
    with pytest.raises(AuthorizationChanged):
        value.check_local()
    store.update_user(w.user, disabled=False)
    with pytest.raises(AuthorizationChanged):
        value.rebaseline()


def test_rebaseline_refuses_inside_an_ambient_transaction(store):
    w = world(store, existing=True)
    value = guard(w)
    with store.transaction():
        with pytest.raises(RuntimeError, match="no ambient transaction"):
            value.rebaseline()
    assert value.rebaseline() is not value


def test_rebaseline_refuses_on_a_closed_authority(store):
    w = world(store, existing=True)
    value = guard(w)
    value.close()
    with pytest.raises(AuthorizationChanged, match="closed"):
        value.rebaseline()


def test_rebaseline_holds_the_authorization_and_source_locks(store, monkeypatch):
    w = world(store, existing=True)
    value = guard(w)
    order = []
    original_source, original_auth = store._lock_source, store._lock_authorization

    def lock_source(identity):
        order.append("source")
        return original_source(identity)

    def lock_auth():
        order.append("authorization")
        return original_auth()

    monkeypatch.setattr(store, "_lock_source", lock_source)
    monkeypatch.setattr(store, "_lock_authorization", lock_auth)
    bump(store, "authorization_epoch")
    value.rebaseline()
    assert order[:2] == ["authorization", "source"]


def test_a_failed_rebaseline_closes_the_child_it_built(store, monkeypatch):
    w = world(store, existing=True)
    value = guard(w)
    module = w.module
    built = []
    original = module.BuildAuthority.check_local

    def failing(self):
        built.append(self)
        if self is not value:
            raise AuthorizationChanged("child refused")
        return original(self)

    monkeypatch.setattr(module.BuildAuthority, "check_local", failing)
    bump(store, "authorization_epoch")
    with pytest.raises(AuthorizationChanged, match="child refused"):
        value.rebaseline()
    monkeypatch.undo()
    child = next(item for item in built if item is not value)
    with pytest.raises(AuthorizationChanged, match="closed"):
        child.check_local()
