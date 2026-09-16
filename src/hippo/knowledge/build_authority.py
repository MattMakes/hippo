"""Read-only authority for prospective local inputs, never a query evidence grant.

The coordinator owns leases, transactions, heartbeat threads and publication.
This boundary reuses EvidenceAccess policy decisions on an unpersisted overlay.
"""

import json
from dataclasses import dataclass
from threading import Lock
from typing import Literal

from ..access import Access, Principal
from . import model as k
from .access import AuthorizationChanged, EvidenceAccess, EvidenceSelection, utc_now
from .identity import canonical_json
from .registry import current_registry

# Every source kind a managed build can be captured for. `repo` and `archive` joined the
# set with CC8 (design review B3): `capture_build_authority` calls `_source_control`
# first, so before that a repository build could not take its first step. `connector` joined
# with the kit (plan section 7.3); its inputs are remote, so it takes the branches below.
BUILD_SOURCE_KINDS = frozenset({"text", "file", "repo", "archive", "connector"})

# The accepted-artifact kinds a *local* build may present. `repository` is the captured tree
# and `history_event` is one commit; both are generation members that carry evidence. A
# connector's kinds are open instead, and validated against the registry (S1 D8): the whole
# point of a connector is that it brings artifact kinds this table never enumerated.
ACCEPTED_ARTIFACT_KINDS = frozenset({"file", "manifest", "repository", "history_event"})

# A planned policy is an explicit local source grant for one lane and nothing else, so
# the suffix set is closed rather than free text.
PLAIN_PROSE_SCOPE = "plain-prose-v1"
MANAGED_CODE_SCOPE = "managed-code-v1"
CONNECTOR_SCOPE = "connector-v1"
PLANNED_POLICY_SCOPES = (PLAIN_PROSE_SCOPE, MANAGED_CODE_SCOPE, CONNECTOR_SCOPE)


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
    if not source or source.get("kind") not in BUILD_SOURCE_KINDS or not source.get("workspace_id"):
        # Deliberately the same text as the denial in `_actor_access`: a caller with no
        # standing must not be able to tell an absent source from one it may not touch.
        raise AuthorizationChanged("Build actor cannot manage source")
    meta = source.get("meta") or {}
    # The Source row alone. The Artifact/Generation presence scan this used to run was a
    # third copy of the classification CC1 retired, and `check_local` re-ran it on every
    # batch -- a whole-table read per write. `meta["managed"]` went with it: nothing
    # writes it, and CC1 proved it is no longer a lane marker.
    managed = bool(source.get("managed") or source.get("active_generation_id"))
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
    """No persistence methods and no unselected interpretation inventory.

    It answers the store's scoped read contract. A live kind forwards the key it was asked with, so a
    proof that looks a group up by ID reads that group rather than the table (R21-M2); an
    accepted-input kind is filtered here, as the Fake store filters.
    """

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

    def _knowledge_rows(self, kind, *, generation_id=None, where=None, ids=None):
        if kind in self._LIVE:
            scope = {"generation_id": generation_id, "where": where, "ids": ids}
            return self.store._knowledge_rows(
                kind, **{key: value for key, value in scope.items() if value is not None}
            )
        rows = self.rows.get(kind, [])
        if ids is not None:
            if generation_id is not None or where:
                raise ValueError(f"{kind} is scoped by ids alone")
            if isinstance(ids, (str, bytes)):
                raise TypeError("Knowledge ids must be a collection of record ids, not one string")
            by_id = {row.id: row for row in rows}
            return [by_id[identity] for identity in dict.fromkeys(ids) if identity in by_id]
        selection = dict(where or {}) | ({} if generation_id is None else {"generation_id": generation_id})
        return [
            row for row in rows if all(getattr(row, field) == value for field, value in selection.items())
        ]

    def _knowledge_get(self, kind, identity):
        return next(iter(self._knowledge_rows(kind, ids=[identity])), None)

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
        # `(audience, valid_until)` once the accepted inputs are proven; see `check_local`.
        self._proven = None

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

    def _connector_id(self):
        """The connector a `connector` Source names, from the meta `_source_control` froze.

        Read from `input_config_json` rather than from a widened `SourceControl`, so the
        connector and the partition are compared as part of the whole control record a
        rebaseline refuses to adopt (`_source_control`, plan section 7.3).
        """
        if self.source_control.kind != "connector":
            return None
        identity = json.loads(self.source_control.input_config_json).get("connector_id")
        if type(identity) is not str or not identity:
            raise AuthorizationChanged("Connector source names no connector")
        return identity

    def _connector_input(self, artifact, revision, connector_id):
        """One accepted input of a connector build: a remote original, or the local manifest."""
        registry = current_registry()
        if artifact.kind not in registry.artifact_kinds() or revision.lifecycle != "active":
            raise AuthorizationChanged("Accepted original is not an active input of this connector")
        if artifact.kind == "manifest":
            # The inventory manifest is written here, not fetched, so it stays a local artifact.
            if artifact.connector_id is not None or artifact.deleted_at is not None:
                raise AuthorizationChanged("Connector inventory manifest must be a local artifact")
            return
        if (
            artifact.connector_id != connector_id
            or not artifact.provider_instance
            or artifact.deleted_at is not None
        ):
            raise AuthorizationChanged("Accepted original is not an active input of this connector")

    def _provider_grant(self, policy, connector_id, now):
        """Whether this policy is the connector's own provider grant, which the build admits.

        `mode="unknown"` is admitted and `expires_at` is not read. The build is not a read
        grant: it writes evidence whose spans carry this policy, and the internal audience
        ignores deadlines anyway (`access.py:458-459`). A reader still needs an unexpired,
        non-unknown policy to see any of it, which `EvidenceAccess` enforces on its own.

        Expiry is the only check this branch drops. The workspace is still compared here, so a
        cross-workspace provider policy whose scope happens to name this connector is refused by
        the inventory rather than two lines later by `EvidenceAccess.grant`.
        """
        return (
            connector_id is not None
            and policy.origin == "provider"
            and policy.workspace_id == self.source_control.workspace_id
            and type(policy.scope_key) is str
            and policy.scope_key.startswith(f"connector:{connector_id}:")
            and policy.verified_at <= now
        )

    def _inventory(self, now):
        accepted, control, store = self._accepted, self.source_control, self._store
        connector_id = self._connector_id()
        policies = {p.id: p for p in store._knowledge_rows("AccessPolicy")}
        used_policies = {a.policy_id for a, _ in accepted.pairs} | {s.policy_id for s in accepted.spans}
        for policy in accepted.planned_policies:
            expected = [
                k.AccessPolicy(
                    workspace_id=control.workspace_id,
                    origin="local_curated",
                    scope_key=f"source:{control.source_id}:{scope}",
                    mode="workspace",
                    verified_at=policy.verified_at,
                )
                for scope in PLANNED_POLICY_SCOPES
            ]
            if policy not in expected or policy.id not in used_policies:
                raise AuthorizationChanged("Planned policy is not an explicit local source grant")
            if policy.id in policies and policies[policy.id] != policy:
                raise AuthorizationChanged("Planned policy cannot replace existing policy")
            policies.setdefault(policy.id, policy)
        for artifact, revision in accepted.pairs:
            if artifact.source_id != control.source_id or artifact.workspace_id != control.workspace_id:
                raise AuthorizationChanged("Accepted original is not an active local input")
            if connector_id is not None:
                self._connector_input(artifact, revision, connector_id)
            elif (
                artifact.kind not in ACCEPTED_ARTIFACT_KINDS
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
            if policy is not None and self._provider_grant(policy, connector_id, now):
                continue
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
        """Only local/store reads; caller owns any enclosing transaction/lock.

        The live checks run on every call: both captured epochs, the Source row, the actor's
        standing, the reviewed mappings and the source requirement. The accepted inputs are proven
        once per authority -- their stored identities and every artifact, revision and span grant
        -- and again only if the audience differs or the earliest policy deadline has passed
        (R21-M1); before, every call re-read and re-proved all of them, so a build's authority
        work grew with members x batches. A child authority proves afresh, so no proof crosses a
        rebaseline or `bind_inputs`.

        Keeping the proof is sound because everything else it read is fenced by an epoch this
        authority never adopts. A policy, membership, connector, mapping or permission write moves
        the authorization epoch, and so does an accepted `Artifact`'s `policy_id` or `deleted_at`; a
        suppression moves the suppression epoch; `ArtifactRevision` and `EvidenceSpan` rows are
        immutable; and a reader's groups change only through a membership, because a membership
        cannot name a missing group object and none is ever deleted. Not re-read: an accepted
        `Artifact`'s `canonical_uri`, the one mutable field that moves no epoch and grants nothing,
        and a record another writer first stores with different contents after the proof, which the
        store refuses when this build writes its own.
        """
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
            audience = (access, frozenset(mappings))
            proven = self._proven
            if proven is not None and proven[0] == audience:
                core._check_current_boundary(self._epochs[0], proven[1])
            else:
                self._inventory(core._now())
                proof = core.build(
                    EvidenceSelection(revision_ids=frozenset(r.id for _, r in self._accepted.pairs))
                )
                if proof.revision_ids != frozenset(
                    r.id for _, r in self._accepted.pairs
                ) or proof.span_ids != frozenset(s.id for s in self._accepted.spans):
                    raise AuthorizationChanged("Not every accepted original is authorized")
                core.validate_current(proof)
                self._proven = (audience, proof.valid_until)
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

    def rebaseline(self):
        """Re-prove the actor in full and adopt only a new *authorization* epoch.

        A repository build outlives many unrelated permission mutations, and a frozen
        epoch equality would abort it whenever any operator logs a role change. So the
        guard may, between batches, ask for a child authority carrying the store's
        current authorization epoch -- but only after `check_local()` re-proves the actor
        and every accepted input's policy in full, under the authorization and source
        locks, exactly as `bind_inputs` does.

        This is the `check_local()` proof, not a reset. Three things are frozen at
        capture and never adopted (design review M6/M7, ruling 2):

        * the suppression epoch. Any change refuses. `publish_staged_generation` checks
          the same epoch against the generation's whole reachable closure and would
          refuse at the end anyway, so continuing is wasted work -- which is why this
          needs no closure computation of its own.
        * `source_control`, compared whole: kind, workspace, `owner_id`, `access_role_id`,
          `min_rank`, the managed flag, the active generation and the input configuration.
          Adopting a changed one would let an operator re-target the finished generation's
          audience or inputs mid-build even though the actor kept every capability.
        * the actor and the accepted inputs, which are the child's by construction.

        Refused inside an ambient transaction, after any sticky failure, and once
        closed. `check_local()` itself is unchanged: it refuses on an epoch mismatch as
        its first act, which is the very condition this exists to clear, so the parent's
        own `check_local()` is never called here.
        """
        if self._store.in_ambient_transaction():
            raise RuntimeError("A rebaseline requires no ambient transaction")
        self._latched()
        try:
            with self._store.transaction():
                self._store._lock_authorization()
                self._store._lock_source(self.source_control.source_id)
                if self._store.suppression_epoch() != self.expected_suppression_epoch:
                    raise AuthorizationChanged("Build suppression changed during rebaseline")
                if _source_control(self._store, self.source_control.source_id) != self.source_control:
                    raise AuthorizationChanged("Source controls changed during build")
                child = BuildAuthority(
                    self._store,
                    self._actor,
                    self._accepted,
                    self.source_control,
                    (self._store.authorization_epoch(), self.expected_suppression_epoch),
                    self._clock,
                )
                try:
                    child.check_local()
                except BaseException:
                    child.close()
                    raise
                return child
        except BaseException as exc:
            self._fail(exc)
            raise

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
