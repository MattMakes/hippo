"""Read-only authority for prospective local inputs, never a query evidence grant.

The coordinator owns leases, transactions, heartbeat threads and publication.
This boundary reuses EvidenceAccess policy decisions on an unpersisted overlay.
"""

from dataclasses import dataclass
from threading import Lock
from typing import Literal

from ..access import Access, Principal
from . import model as k
from .access import AuthorizationChanged, EvidenceAccess, EvidenceSelection, utc_now
from .identity import canonical_json


@dataclass(frozen=True, slots=True)
class BuildActor:
    kind: Literal["reader", "trusted_local"]
    user_id: str | None = None
    max_rank: int = 0

    def __post_init__(self):
        if self.kind not in {"reader", "trusted_local"} or type(self.max_rank) is not int:
            raise ValueError("Explicit build actor required")
        if self.kind == "reader":
            if type(self.user_id) is not str or not self.user_id:
                raise ValueError("Build reader requires authenticated user")
        elif self.user_id is not None or self.max_rank != 0:
            raise ValueError("Trusted local actor cannot impersonate a reader")

    @classmethod
    def reader(cls, principal):
        if (
            type(principal) is not Principal
            or principal.access.audience_kind != "reader"
            or not principal.user_id
            or principal.access.user_id != principal.user_id
            or principal.access.unrestricted
        ):
            raise ValueError("Open and preview identities cannot build managed evidence")
        return cls("reader", principal.user_id, min(principal.rank, principal.access.rank))

    @classmethod
    def trusted_local(cls):
        return cls("trusted_local")


@dataclass(frozen=True, slots=True)
class SourceControl:
    source_id: str
    workspace_id: str
    kind: str
    owner_id: str | None
    access_role_id: str | None
    min_rank: int
    managed: bool
    active_generation_id: str | None
    input_config_json: str


def _source_control(store, source_id):
    source = store.get_source(source_id)
    if not source or source.get("kind") not in {"text", "file"} or not source.get("workspace_id"):
        raise AuthorizationChanged("Plain build source is unavailable")
    meta = source.get("meta") or {}
    managed = bool(
        source.get("managed")
        or source.get("active_generation_id")
        or meta.get("managed")
        or any(
            r.source_id == source_id
            for kind in ("Artifact", "Generation")
            for r in store._knowledge_rows(kind)
        )
    )
    return SourceControl(
        source_id,
        source["workspace_id"],
        source["kind"],
        source.get("owner_id"),
        source.get("access_role_id"),
        int(source.get("min_rank") or 0),
        managed,
        source.get("active_generation_id"),
        canonical_json(
            {
                key: value
                for key, value in meta.items()
                if key not in {"chunks", "documents", "counts", "code", "progress"}
            }
        ),
    )


@dataclass(frozen=True, slots=True)
class AcceptedBuildInputs:
    pairs: tuple[tuple[k.Artifact, k.ArtifactRevision], ...] = ()
    spans: tuple[k.EvidenceSpan, ...] = ()
    planned_policies: tuple[k.AccessPolicy, ...] = ()

    def __post_init__(self):
        if type(self.pairs) is not tuple or any(
            type(pair) is not tuple
            or len(pair) != 2
            or type(pair[0]) is not k.Artifact
            or type(pair[1]) is not k.ArtifactRevision
            or pair[1].artifact_id != pair[0].id
            for pair in self.pairs
        ):
            raise ValueError("Accepted artifact/revision pairs must be immutable and bound")
        for values, kind in ((self.spans, k.EvidenceSpan), (self.planned_policies, k.AccessPolicy)):
            if (
                type(values) is not tuple
                or any(type(v) is not kind for v in values)
                or len({v.id for v in values}) != len(values)
            ):
                raise ValueError("Accepted records must be immutable and unique")
        if len({a.id for a, _ in self.pairs}) != len(self.pairs):
            raise ValueError("One accepted revision per artifact is required")
        revisions = {r.id for _, r in self.pairs}
        if any(span.revision_id not in revisions for span in self.spans):
            raise ValueError("Requested spans must belong to accepted revisions")


_EMPTY_INPUTS = AcceptedBuildInputs()


class _Overlay:
    """No persistence methods and no unselected interpretation inventory."""

    _LIVE = frozenset(
        {"Workspace", "WorkspaceMembership", "GroupMembership", "KnowledgeObject", "Suppression", "Connector"}
    )

    def __init__(self, store, accepted):
        self.store = store
        self.rows = {
            "Artifact": [a for a, _ in accepted.pairs],
            "ArtifactRevision": [r for _, r in accepted.pairs],
            "EvidenceSpan": list(accepted.spans),
        }
        policies = {p.id: p for p in store._knowledge_rows("AccessPolicy")}
        for policy in accepted.planned_policies:
            policies.setdefault(policy.id, policy)
        self.rows["AccessPolicy"] = list(policies.values())

    def _knowledge_rows(self, kind):
        return self.store._knowledge_rows(kind) if kind in self._LIVE else self.rows.get(kind, [])

    def _knowledge_get(self, kind, identity):
        return next((r for r in self._knowledge_rows(kind) if r.id == identity), None)

    def get_source(self, identity):
        return self.store.get_source(identity)

    def get_user(self, identity):
        return self.store.get_user(identity)

    def get_role(self, identity):
        return self.store.get_role(identity)

    def authorization_epoch(self):
        return self.store.authorization_epoch()


class BuildAuthority:
    def __init__(self, store, actor, accepted, source_control, epochs, clock):
        self._store, self._actor, self._accepted = store, actor, accepted
        self._source_control, self._epochs, self._clock = source_control, epochs, clock
        self._lock, self._failure, self._closed = Lock(), None, False

    @property
    def source_control(self):
        return self._source_control

    @property
    def expected_authorization_epoch(self):
        return self._epochs[0]

    @property
    def expected_suppression_epoch(self):
        return self._epochs[1]

    def _latched(self):
        with self._lock:
            failure, closed = self._failure, self._closed
        if failure is not None:
            raise failure
        if closed:
            raise AuthorizationChanged("Build authority is closed")

    def _fail(self, exc):
        with self._lock:
            if self._failure is None:
                self._failure = exc

    def _actor_access(self):
        if self._actor.kind == "trusted_local":
            return Access(unrestricted=True, audience_kind="internal")
        user = self._store.get_user(self._actor.user_id)
        if not user or user.get("disabled") or user.get("id") != self._actor.user_id:
            raise AuthorizationChanged("Build actor is unavailable")
        role = self._store.get_role(user.get("role_id"))
        if not role:
            raise AuthorizationChanged("Build role is unavailable")
        access = Access(user_id=user["id"], rank=min(self._actor.max_rank, int(role.get("rank") or 0)))
        principal = Principal(user, dict(role, rank=access.rank), access)
        if not principal.may_manage_source(self._store.get_source(self.source_control.source_id)):
            raise AuthorizationChanged("Build actor cannot manage source")
        return access

    def _inventory(self, now):
        accepted, control, store = self._accepted, self.source_control, self._store
        policies = {p.id: p for p in store._knowledge_rows("AccessPolicy")}
        used_policies = {a.policy_id for a, _ in accepted.pairs} | {s.policy_id for s in accepted.spans}
        for policy in accepted.planned_policies:
            expected = k.AccessPolicy(
                workspace_id=control.workspace_id,
                origin="local_curated",
                scope_key=f"source:{control.source_id}:plain-prose-v1",
                mode="workspace",
                verified_at=policy.verified_at,
            )
            if policy != expected or policy.id not in used_policies:
                raise AuthorizationChanged("Planned policy is not an explicit local source grant")
            if policy.id in policies and policies[policy.id] != policy:
                raise AuthorizationChanged("Planned policy cannot replace existing policy")
            policies.setdefault(policy.id, policy)
        for artifact, revision in accepted.pairs:
            if (
                artifact.source_id != control.source_id
                or artifact.workspace_id != control.workspace_id
                or artifact.kind not in {"file", "manifest"}
                or artifact.connector_id is not None
                or artifact.deleted_at is not None
                or revision.lifecycle != "active"
            ):
                raise AuthorizationChanged("Accepted original is not an active local input")
        for record in (*[v for pair in accepted.pairs for v in pair], *accepted.spans):
            existing = store._knowledge_get(type(record).__name__, record.id)
            if existing is not None and existing != record:
                raise AuthorizationChanged("Accepted record differs from current stored identity")
        for identity in used_policies:
            policy = policies.get(identity)
            if (
                policy is None
                or policy.workspace_id != control.workspace_id
                or policy.origin != "local_curated"
                or policy.mode == "unknown"
                or policy.verified_at > now
                or policy.expires_at is not None
                and policy.expires_at <= now
            ):
                raise AuthorizationChanged("Accepted local policy is unavailable or expired")

    def check_local(self):
        """Only local/store reads; caller owns any enclosing transaction/lock."""
        self._latched()
        try:
            store = self._store
            if (store.authorization_epoch(), store.suppression_epoch()) != self._epochs:
                raise AuthorizationChanged("Build authorization or suppression changed")
            if _source_control(store, self.source_control.source_id) != self.source_control:
                raise AuthorizationChanged("Source controls changed during build")
            access = self._actor_access()
            mappings = store.get_meta("reviewed_mapping_authorities") or []
            if type(mappings) is not list or any(type(v) is not str or not v for v in mappings):
                raise AuthorizationChanged("Reviewed identity mapping configuration is invalid")
            overlay = _Overlay(store, self._accepted)
            core = EvidenceAccess(
                overlay,
                self.source_control.workspace_id,
                access,
                mapping_authorities=frozenset(mappings),
                clock=self._clock,
            )
            core.require_source(self.source_control.source_id)
            self._inventory(core._now())
            proof = core.build(
                EvidenceSelection(revision_ids=frozenset(r.id for _, r in self._accepted.pairs))
            )
            if proof.revision_ids != frozenset(
                r.id for _, r in self._accepted.pairs
            ) or proof.span_ids != frozenset(s.id for s in self._accepted.spans):
                raise AuthorizationChanged("Not every accepted original is authorized")
            core.validate_current(proof)
            if (store.authorization_epoch(), store.suppression_epoch()) != self._epochs or _source_control(
                store, self.source_control.source_id
            ) != self.source_control:
                raise AuthorizationChanged("Build controls changed during validation")
            self._latched()
        except BaseException as exc:
            self._fail(exc)
            raise

    def check(self, *, checkpoint=None):
        """Bracket optional external work; never invoke callbacks under a store transaction."""
        # The caller's own transaction, not any thread's: a concurrent build holding one is not
        # this caller's ambient transaction, and rejecting it would break concurrent builds.
        if self._store.in_ambient_transaction():
            raise RuntimeError("External build checks require no ambient transaction")
        self.check_local()
        try:
            if checkpoint is not None:
                if not callable(checkpoint):
                    raise ValueError("Checkpoint must be callable")
                checkpoint()
        except BaseException as exc:
            self._fail(exc)
            raise
        finally:
            self.check_local()

    def bind_inputs(self, accepted):
        """Derive under one source/auth lock without rebasing captured epochs."""
        if type(accepted) is not AcceptedBuildInputs:
            raise ValueError("Immutable accepted inputs required")
        with self._store.transaction():
            self._store._lock_source(self.source_control.source_id)
            self.check_local()
            child = BuildAuthority(
                self._store, self._actor, accepted, self.source_control, self._epochs, self._clock
            )
            try:
                child.check_local()
                self.check_local()
            except BaseException:
                child.close()
                raise
            return child

    def close(self):
        with self._lock:
            self._closed = True


def capture_build_authority(store, *, source_id, actor, accepted=_EMPTY_INPUTS, clock=utc_now):
    if type(actor) is not BuildActor or type(accepted) is not AcceptedBuildInputs or not callable(clock):
        raise ValueError("Explicit actor and immutable accepted inputs required")
    epochs = store.authorization_epoch(), store.suppression_epoch()
    control = _source_control(store, source_id)
    result = BuildAuthority(store, actor, accepted, control, epochs, clock)
    result.check_local()
    return result
