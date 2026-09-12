"""Audience-safe evidence proofs, separate from retrieval and temporal selection.

Only internal readers may bypass policy checks. A caller selecting current or
historical evidence must supply its resolved selection; an omitted selection
authorizes retained records without claiming that they are currently applicable.
The store owns epoch mutation and callers must validate before releasing results.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Literal

from hippo.access import Access

from .derivations import derived_capability, validate_prose, validate_view
from .identity import canonical_json

_DERIVED_KINDS = ("DerivedRecord", "DerivedDependency", "RetrievalView", "ProseExtraction")


class AuthorizationChanged(RuntimeError):
    """An authorization proof expired or changed; discard dependent output."""


@dataclass(frozen=True)
class EvidenceSelection:
    generation_ids: frozenset[str] | None = None
    revision_ids: frozenset[str] | None = None
    assertion_version_ids: frozenset[str] | None = None
    query_mode: Literal["current", "history"] = "current"
    require_exact_membership: bool = False

    def __post_init__(self):
        if type(self.require_exact_membership) is not bool:
            raise ValueError("Exact membership requirement must be boolean")
        if self.require_exact_membership and self.generation_ids is None:
            raise ValueError("Exact membership requires explicit generation selection")
        if self.query_mode not in {"current", "history"}:
            raise ValueError("Unknown evidence query mode")
        for name in ("generation_ids", "revision_ids", "assertion_version_ids"):
            values = getattr(self, name)
            if values is not None and (
                not isinstance(values, frozenset)
                or any(not isinstance(item, str) or not item for item in values)
            ):
                raise ValueError("Evidence selection IDs must be immutable nonempty strings")


@dataclass(frozen=True)
class AuthorizedSupportGroup:
    assertion_version_id: str
    derivation_group: str
    span_ids: frozenset[str]
    support_ids: frozenset[str]


@dataclass(frozen=True)
class AuthorizedEvidence:
    workspace_id: str
    selection: EvidenceSelection
    artifact_ids: frozenset[str] = frozenset()
    revision_ids: frozenset[str] = frozenset()
    span_ids: frozenset[str] = frozenset()
    observation_ids: frozenset[str] = frozenset()
    object_ids: frozenset[str] = frozenset()
    assertion_version_ids: frozenset[str] = frozenset()
    assertion_ids: frozenset[str] = frozenset()
    support_ids: frozenset[str] = frozenset()
    native_binding_ids: frozenset[str] = frozenset()
    derived_record_ids: frozenset[str] = frozenset()
    derived_dependency_ids: frozenset[str] = frozenset()
    retrieval_view_ids: frozenset[str] = frozenset()
    prose_extraction_ids: frozenset[str] = frozenset()
    support_groups: tuple[AuthorizedSupportGroup, ...] = ()
    policy_fingerprint: str = ""
    authorization_epoch: int = field(default=0, repr=False)
    valid_until: datetime | None = None


def utc_now() -> datetime:
    return datetime.now(UTC)


def _exact_generations(rows, selection):
    required = {"evidence", "dense", "native"}
    return {
        manifest.generation_id
        for manifest in rows("IndexManifest").values()
        if selection.generation_ids is not None
        and manifest.generation_id in selection.generation_ids
        and manifest.ready
        and required <= set(manifest.required_representations)
        and required <= {item.kind for item in manifest.checksums if item.ready}
    }


def _derived_generations(rows, exact):
    return {
        identity
        for identity in exact
        if (generation := rows("Generation").get(identity)) is not None and derived_capability(generation)
    }


def _interpretation_inventory(rows, selection):
    """Select sealed interpretation membership before evaluating any ACL.

    Older trusted generations have only revision manifests and retain that read
    contract until rebuilt. Durable snapshot callers explicitly reject them.
    Crucially, an empty exact manifest means no interpretation, not a fallback.
    """
    if selection.generation_ids is None:
        return lambda kind: {} if kind in _DERIVED_KINDS else rows(kind)
    exact = _exact_generations(rows, selection)
    compatibility = selection.generation_ids - exact
    if selection.require_exact_membership and compatibility:
        raise ValueError("Selected generation needs a sealed exact manifest; rebuild required")
    if not exact:
        return lambda kind: {} if kind in _DERIVED_KINDS else rows(kind)
    derived_exact = _derived_generations(rows, exact)
    selected = defaultdict(set)
    for member in rows("GenerationEvidenceMember").values():
        if member.generation_id in exact and (
            member.record_kind not in _DERIVED_KINDS or member.generation_id in derived_exact
        ):
            selected[member.record_kind].add(member.record_id)
    compatibility_revisions = {
        member.artifact_revision_id
        for member in rows("GenerationMember").values()
        if member.generation_id in compatibility
    }
    # Compatibility supports retain their full AND groups, including spans from
    # outside the selected revision set; ordinary revision checks will deny them.
    compatibility_versions = {
        support.assertion_version_id
        for support in rows("AssertionSupport").values()
        if (span := rows("EvidenceSpan").get(support.span_id)) is not None
        and span.revision_id in compatibility_revisions
    }
    inventories = {}
    for kind in (
        "EvidenceSpan",
        "ObjectObservation",
        "AssertionVersion",
        "AssertionSupport",
        *_DERIVED_KINDS,
    ):
        inventories[kind] = {
            identity: record
            for identity, record in rows(kind).items()
            if identity in selected[kind]
            or (
                kind in {"EvidenceSpan", "ObjectObservation"}
                and record.revision_id in compatibility_revisions
            )
            or (kind == "AssertionVersion" and identity in compatibility_versions)
            or (kind == "AssertionSupport" and record.assertion_version_id in compatibility_versions)
        }
    return lambda kind: inventories.get(kind, rows(kind))


def _authorized_derivations(store, rows, interpretation, selection, spans, revisions, bindings, suppressed):
    """Validate full trusted closures before applying all-input audience grants."""
    exact = _derived_generations(rows, _exact_generations(rows, selection))
    views = interpretation("RetrievalView")
    prose = interpretation("ProseExtraction")
    derived = interpretation("DerivedRecord")
    dependencies = interpretation("DerivedDependency")
    selected_outputs = defaultdict(set)
    for member in rows("GenerationEvidenceMember").values():
        if member.generation_id in exact and member.record_kind in {"RetrievalView", "ProseExtraction"}:
            selected_outputs[member.record_kind].add((member.generation_id, member.record_id))
    visible_derived, visible_dependencies, visible_views, visible_prose = set(), set(), set(), set()

    def include(closure):
        if (
            not closure.span_ids <= spans.keys()
            or not closure.revision_ids <= revisions.keys()
            or not closure.binding_ids <= bindings
            or not closure.derived_record_ids <= derived.keys()
            or not closure.dependency_ids <= dependencies.keys()
            or not closure.view_ids <= views.keys()
            or any(("derived_record", identity) in suppressed for identity in closure.derived_record_ids)
        ):
            return False
        visible_derived.update(closure.derived_record_ids)
        visible_dependencies.update(closure.dependency_ids)
        visible_views.update(closure.view_ids)
        return True

    for generation_id, identity in sorted(selected_outputs["RetrievalView"]):
        view = views.get(identity)
        if view is None:
            raise ValueError("Selected derived retrieval view is missing")
        include(validate_view(store, generation_id, view))
    for generation_id, identity in sorted(selected_outputs["ProseExtraction"]):
        extraction = prose.get(identity)
        if extraction is None:
            raise ValueError("Selected prose extraction is missing")
        if include(validate_prose(store, generation_id, extraction)):
            visible_prose.add(identity)
    return dict(
        derived_record_ids=frozenset(visible_derived),
        derived_dependency_ids=frozenset(visible_dependencies),
        retrieval_view_ids=frozenset(visible_views),
        prose_extraction_ids=frozenset(visible_prose),
    )


class EvidenceAccess:
    """Build proofs from full trusted storage inventories, never filtered groups.

    Mapping authorities are explicit administrator configuration. Provider scopes
    are opaque IDs whose connector-to-policy binding must be verified by ingestion;
    this layer additionally checks origin, connector namespace, and freshness.
    """

    def __init__(
        self,
        store,
        workspace_id: str,
        access: Access,
        *,
        mapping_authorities: frozenset[str] = frozenset(),
        clock: Callable[[], datetime] = utc_now,
        policy_max_age: timedelta | None = None,
        epoch_reader: Callable[[], int] | None = None,
    ):
        if policy_max_age is not None and policy_max_age <= timedelta(0):
            raise ValueError("Policy maximum age must be positive")
        self.store = store
        self.workspace_id = workspace_id
        self.access = access
        self.mapping_authorities = frozenset(mapping_authorities)
        self.clock = clock
        self.policy_max_age = policy_max_age
        self.epoch_reader = epoch_reader or store.authorization_epoch

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Authorization clock must be timezone aware")
        return now.astimezone(UTC)

    def _identity(self):
        if self.access.audience_kind == "internal":
            return self.access
        if self.access.audience_kind != "reader" or not self.access.user_id:
            return None
        user = self.store.get_user(self.access.user_id)
        if not user or user.get("disabled") or user.get("id") != self.access.user_id:
            return None
        role = self.store.get_role(user.get("role_id"))
        if not role:
            return None
        memberships = self.store._knowledge_rows("WorkspaceMembership")
        if not any(self._membership(member) for member in memberships):
            return None
        return Access(rank=min(self.access.rank, int(role.get("rank") or 0)), user_id=self.access.user_id)

    def _membership(self, member) -> bool:
        return (
            member.workspace_id == self.workspace_id
            and member.principal_id == self.access.user_id
            and member.enabled
            and member.mapping_authority in self.mapping_authorities
        )

    def _suppressed(self, query_mode):
        if query_mode not in {"current", "history"}:
            raise ValueError("Unknown evidence query mode")
        return {
            (item.target_kind, item.target_id)
            for item in self.store._knowledge_rows("Suppression")
            if item.workspace_id == self.workspace_id
            and (item.all_principals or self.access.user_id in item.principal_ids)
            and (query_mode == "current" or item.view_applicability == "all_history")
        }

    def _source_allowed(self, identity, source_id, suppressed):
        source = self.store.get_source(source_id)
        return bool(
            identity is not None
            and source
            and source.get("workspace_id") == self.workspace_id
            and ("source", source_id) not in suppressed
            and identity.can_see_source(source)
        )

    def require_source(self, source_id: str, *, query_mode="current") -> None:
        """Authorize source administration input without fabricating evidence.

        This checks the existing reader/workspace/source boundary only; callers
        still enforce management capability and every original's policy.
        """
        epoch = self.epoch_reader()
        suppressed = self._suppressed(query_mode)
        identity = self._identity()
        if not any(
            row.id == self.workspace_id for row in self.store._knowledge_rows("Workspace")
        ) or not self._source_allowed(identity, source_id, suppressed):
            raise AuthorizationChanged("Source is not available to this audience")
        self._check_current_boundary(epoch, None)

    def build(self, selection: EvidenceSelection | None = None) -> AuthorizedEvidence:
        selection = selection or EvidenceSelection()
        epoch, now = self.epoch_reader(), self._now()
        identity = self._identity()
        internal = self.access.audience_kind == "internal"
        records = {}

        def rows(kind):
            if kind not in records:
                records[kind] = {record.id: record for record in self.store._knowledge_rows(kind)}
            return records[kind]

        interpretation = _interpretation_inventory(rows, selection)
        generation_members = {
            (member.generation_id, member.artifact_revision_id)
            for member in rows("GenerationMember").values()
        }
        selected_revisions = selection.revision_ids
        if selection.generation_ids is not None:
            generation_revisions = {
                revision_id
                for generation_id, revision_id in generation_members
                if generation_id in selection.generation_ids
            }
            selected_revisions = (
                generation_revisions
                if selected_revisions is None
                else generation_revisions.intersection(selected_revisions)
            )
        selected_artifacts = (
            None
            if selected_revisions is None
            else {
                revision.artifact_id
                for revision in rows("ArtifactRevision").values()
                if revision.id in selected_revisions
            }
        )

        suppressed = self._suppressed(selection.query_mode)
        groups = {
            member.group_id
            for member in rows("GroupMembership").values()
            if self._membership(member)
            and (group := rows("KnowledgeObject").get(member.group_id)) is not None
            and group.workspace_id == self.workspace_id
            and group.kind in {"group", "team"}
        }
        proofs = {}

        def grant(policy_id, artifact):
            policy = rows("AccessPolicy").get(policy_id)
            if (
                policy is None
                or policy.workspace_id != self.workspace_id
                or ("policy", policy_id) in suppressed
            ):
                return False
            if internal:
                return True
            if policy.origin == "legacy_unknown" or policy.mode == "unknown" or policy.verified_at > now:
                return False
            if artifact.connector_id:
                connector = rows("Connector").get(artifact.connector_id)
                if (
                    connector is None
                    or not connector.enabled
                    or connector.workspace_id != self.workspace_id
                    or connector.instance_url != artifact.provider_instance
                ):
                    return False
                if connector.kind != "local" and policy.origin != "provider":
                    return False
            elif policy.origin != "local_curated":
                return False
            deadline = policy.expires_at
            if policy.origin == "provider" and self.policy_max_age is not None:
                maximum = policy.verified_at + self.policy_max_age
                deadline = min(deadline, maximum) if deadline else maximum
            if policy.origin == "provider" and deadline is None:
                return False
            if deadline is not None and now >= deadline:
                return False
            if self.access.user_id in policy.deny_users or groups.intersection(policy.deny_groups):
                return False
            if (
                policy.mode != "workspace"
                and self.access.user_id not in policy.allow_users
                and not groups.intersection(policy.allow_groups)
            ):
                return False
            return (policy.id, deadline)

        def remember(proof):
            if isinstance(proof, tuple):
                proofs[proof[0]] = proof[1]

        artifacts = {}
        if identity is not None and self.workspace_id in rows("Workspace"):
            for artifact in rows("Artifact").values():
                if (
                    artifact.workspace_id != self.workspace_id
                    or (selected_artifacts is not None and artifact.id not in selected_artifacts)
                    or ("artifact", artifact.id) in suppressed
                    or ("source", artifact.source_id) in suppressed
                ):
                    continue
                if not self._source_allowed(identity, artifact.source_id, suppressed):
                    continue
                if proof := grant(artifact.policy_id, artifact):
                    artifacts[artifact.id] = artifact
                    remember(proof)
        revisions = {
            record.id: record
            for record in rows("ArtifactRevision").values()
            if record.artifact_id in artifacts
            and ("revision", record.id) not in suppressed
            and (selected_revisions is None or record.id in selected_revisions)
        }
        spans = {}
        for span in interpretation("EvidenceSpan").values():
            if span.revision_id not in revisions or ("span", span.id) in suppressed:
                continue
            if proof := grant(span.policy_id, artifacts[revisions[span.revision_id].artifact_id]):
                spans[span.id] = span
                remember(proof)
        observations = {
            record.id: record
            for record in interpretation("ObjectObservation").values()
            if record.span_id in spans
            and record.revision_id == spans[record.span_id].revision_id
            and (obj := rows("KnowledgeObject").get(record.object_id)) is not None
            and obj.workspace_id == self.workspace_id
        }
        objects = frozenset(record.object_id for record in observations.values())
        all_groups = defaultdict(list)
        for support in interpretation("AssertionSupport").values():
            all_groups[(support.assertion_version_id, support.derivation_group)].append(support)
        versions, assertions, supports, complete_groups = set(), set(), set(), []
        for (version_id, group_name), members in sorted(all_groups.items()):
            version = interpretation("AssertionVersion").get(version_id)
            if (
                version is None
                or ("assertion_version", version_id) in suppressed
                or (
                    selection.assertion_version_ids is not None
                    and version_id not in selection.assertion_version_ids
                )
            ):
                continue
            assertion = rows("Assertion").get(version.assertion_id)
            if (
                assertion is None
                or assertion.workspace_id != self.workspace_id
                or assertion.subject_id not in objects
                or assertion.object_id not in objects
                or not all(member.span_id in spans for member in members)
            ):
                continue
            versions.add(version_id)
            assertions.add(assertion.id)
            supports.update(member.id for member in members)
            complete_groups.append(
                AuthorizedSupportGroup(
                    version_id,
                    group_name,
                    frozenset(member.span_id for member in members),
                    frozenset(member.id for member in members),
                )
            )
        bindings = set()
        for binding in rows("NativeBinding").values():
            if (
                binding.span_id not in spans
                or binding.object_id not in objects
                or (
                    selection.generation_ids is not None
                    and binding.generation_id not in selection.generation_ids
                )
            ):
                continue
            generation = rows("Generation").get(binding.generation_id)
            artifact = artifacts[revisions[spans[binding.span_id].revision_id].artifact_id]
            native = self.store._knowledge_get(binding.native_kind, binding.native_id)
            if (
                generation
                and generation.source_id == artifact.source_id
                and (generation.id, spans[binding.span_id].revision_id) in generation_members
                and native
                and native.get("source_id") == artifact.source_id
            ):
                bindings.add(binding.id)
        derived_visible = _authorized_derivations(
            self.store, rows, interpretation, selection, spans, revisions, bindings, suppressed
        )
        visible = dict(
            artifact_ids=frozenset(artifacts),
            revision_ids=frozenset(revisions),
            span_ids=frozenset(spans),
            observation_ids=frozenset(observations),
            object_ids=objects,
            assertion_version_ids=frozenset(versions),
            assertion_ids=frozenset(assertions),
            support_ids=frozenset(supports),
            native_binding_ids=frozenset(bindings),
        )
        # An additive schema must not invalidate original-only schema 4 proofs
        # or expose the existence of denied/unselected derived payloads.
        if any(derived_visible.values()):
            visible.update(derived_visible)
        fingerprint = hashlib.sha256(
            canonical_json(
                [
                    self.workspace_id,
                    self.access.audience_kind,
                    self.access.user_id,
                    {key: sorted(value) for key, value in visible.items()},
                    sorted((key, value.isoformat() if value else None) for key, value in proofs.items()),
                ]
            ).encode()
        ).hexdigest()
        deadlines = [deadline for deadline in proofs.values() if deadline is not None]
        valid_until = min(deadlines) if deadlines else None
        self._check_current_boundary(epoch, valid_until)
        return AuthorizedEvidence(
            workspace_id=self.workspace_id,
            selection=selection,
            **visible,
            support_groups=tuple(complete_groups),
            policy_fingerprint=fingerprint,
            authorization_epoch=epoch,
            valid_until=valid_until,
        )

    def build_history(self, selection: EvidenceSelection | None = None) -> AuthorizedEvidence:
        """Prove retained evidence for a historical request without forking policy.

        This is `build` with the history query mode pinned, so live identity,
        workspace membership, artifact policy, complete AND support groups and
        `all_history` suppression all still decide the proof before any caller
        filters it by time. Only an ordinary `current_only` tombstone stops
        hiding rows, which is exactly the distinction `query_mode` already draws.
        """
        selection = selection or EvidenceSelection()
        if selection.query_mode != "history":
            selection = replace(selection, query_mode="history")
        return self.build(selection)

    def _check_current_boundary(self, epoch: int, valid_until: datetime | None) -> None:
        if (valid_until is not None and self._now() >= valid_until) or self.epoch_reader() != epoch:
            raise AuthorizationChanged("Authorization proof expired or changed")

    def validate_current(self, view: AuthorizedEvidence) -> None:
        """Recheck current grants, including expiry even without an epoch write."""
        if view.workspace_id != self.workspace_id:
            raise AuthorizationChanged("Authorization proof belongs to another workspace")
        self._check_current_boundary(view.authorization_epoch, view.valid_until)
        current = self.build(view.selection)
        if (
            current.authorization_epoch != view.authorization_epoch
            or current.policy_fingerprint != view.policy_fingerprint
        ):
            raise AuthorizationChanged("Audience evidence permissions changed")
        self._check_current_boundary(view.authorization_epoch, view.valid_until)
