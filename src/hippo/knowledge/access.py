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

from .derivations import GenerationViews, derived_capability
from .identity import canonical_json

_DERIVED_KINDS = ("DerivedRecord", "DerivedDependency", "RetrievalView", "ProseExtraction")

# Looked up by ID in every proof, bounded or not. No proof reads `KnowledgeObject` whole: each lookup
# names its records -- a reader's groups, an observation's object -- while the table grows with every
# symbol, file and commit, so walking it for a handful of groups made every build check corpus-sized
# (R21-M2).
_KEYED_KINDS = frozenset({"KnowledgeObject"})


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


class _ProofReads:
    """The knowledge rows one proof reads, each fetched once and only as widely as the proof needs.

    A proof over explicit generations (`bounded`) reads a generation-sized kind by generation, by
    revision or by record ID, so its cost follows the evidence it serves rather than the corpus.
    Every caller still applies the filters it applied to a whole-table read, and each narrowed read
    returns a superset of the rows those filters keep, so the proof is the same.

    A proof with no generation selection -- a legacy reader, the history lane proving every retained
    row before time narrows it, or the build authority's overlay -- answers over the whole inventory
    and reads it whole, exactly as before, except for `_KEYED_KINDS`, which it only ever looks up
    by ID. The authorization tables (`AccessPolicy`, `Connector`, `Workspace`, `GroupMembership`)
    are read whole either way: they grow with principals and policies, not with evidence.
    """

    def __init__(self, store, *, bounded: bool):
        self.store = store
        self.bounded = bounded
        self._whole = {}
        self._keyed = defaultdict(dict)
        self._scoped = {}

    def whole(self, kind):
        if kind not in self._whole:
            self._whole[kind] = {record.id: record for record in self.store._knowledge_rows(kind)}
        return self._whole[kind]

    def by_id(self, kind, identities):
        """The named records that exist, as `{id: record}`: one read for the IDs not fetched yet."""
        wanted = frozenset(identities)
        if not wanted:  # nothing to look up reads nothing, as a lookup per row never ran for no rows
            return {}
        if not self.bounded and kind not in _KEYED_KINDS:
            return {identity: record for identity, record in self.whole(kind).items() if identity in wanted}
        known = self._keyed[kind]
        missing = sorted(wanted - known.keys())
        if missing:
            found = {record.id: record for record in self.store._knowledge_rows(kind, ids=missing)}
            known.update((identity, found.get(identity)) for identity in missing)
        return {identity: known[identity] for identity in sorted(wanted) if known[identity] is not None}

    def scoped(self, kind, field, values):
        """`kind`'s records whose `field` is one of `values`: one scoped read per value."""
        values = frozenset(values)
        if not self.bounded:
            return {
                identity: record
                for identity, record in self.whole(kind).items()
                if getattr(record, field) in values
            }
        rows = {}
        for value in sorted(values):
            key = (kind, field, value)
            if key not in self._scoped:
                self._scoped[key] = {
                    record.id: record for record in self.store._knowledge_rows(kind, where={field: value})
                }
            rows.update(self._scoped[key])
        return rows


def _exact_generations(reads, selection):
    required = {"evidence", "dense", "native"}
    if selection.generation_ids is None:
        return set()
    return {
        manifest.generation_id
        for manifest in reads.scoped("IndexManifest", "generation_id", selection.generation_ids).values()
        if manifest.ready
        and required <= set(manifest.required_representations)
        and required <= {item.kind for item in manifest.checksums if item.ready}
    }


def _derived_generations(reads, exact):
    generations = reads.by_id("Generation", exact)
    return {
        identity
        for identity in exact
        if (generation := generations.get(identity)) is not None and derived_capability(generation)
    }


def _interpretation_inventory(reads, selection, selected_revisions):
    """Select sealed interpretation membership before evaluating any ACL.

    Older trusted generations have only revision manifests and retain that read
    contract until rebuilt. Durable snapshot callers explicitly reject them.
    Crucially, an empty exact manifest means no interpretation, not a fallback.

    With explicit generations only what they can serve is read: exact members by ID, and spans
    and observations of the selected revisions, the only revisions `build` keeps a span of.
    """
    if selection.generation_ids is None:
        return lambda kind: {} if kind in _DERIVED_KINDS else reads.whole(kind)
    exact = _exact_generations(reads, selection)
    compatibility = selection.generation_ids - exact
    if selection.require_exact_membership and compatibility:
        raise ValueError("Selected generation needs a sealed exact manifest; rebuild required")

    def retained(kind):
        if kind in {"EvidenceSpan", "ObjectObservation"}:
            return reads.scoped(kind, "revision_id", selected_revisions)
        return reads.whole(kind)

    if not exact:
        return lambda kind: {} if kind in _DERIVED_KINDS else retained(kind)
    derived_exact = _derived_generations(reads, exact)
    selected = defaultdict(set)
    for member in reads.scoped("GenerationEvidenceMember", "generation_id", exact).values():
        if member.record_kind not in _DERIVED_KINDS or member.generation_id in derived_exact:
            selected[member.record_kind].add(member.record_id)
    compatibility_revisions = {
        member.artifact_revision_id
        for member in reads.scoped("GenerationMember", "generation_id", compatibility).values()
    }
    # Compatibility supports retain their full AND groups, including spans from
    # outside the selected revision set; ordinary revision checks will deny them.
    compatibility_versions = set()
    if compatibility_revisions:
        supports = reads.whole("AssertionSupport")
        support_spans = reads.by_id("EvidenceSpan", {support.span_id for support in supports.values()})
        compatibility_versions = {
            support.assertion_version_id
            for support in supports.values()
            if (span := support_spans.get(support.span_id)) is not None
            and span.revision_id in compatibility_revisions
        }
    inventories = {kind: reads.by_id(kind, selected[kind]) for kind in _DERIVED_KINDS}
    for kind in ("EvidenceSpan", "ObjectObservation"):
        inventories[kind] = {
            **reads.by_id(kind, selected[kind]),
            **reads.scoped(kind, "revision_id", compatibility_revisions),
        }
    inventories["AssertionVersion"] = reads.by_id(
        "AssertionVersion", selected["AssertionVersion"] | compatibility_versions
    )
    inventories["AssertionSupport"] = reads.by_id("AssertionSupport", selected["AssertionSupport"])
    if compatibility_versions:
        inventories["AssertionSupport"].update(
            (identity, support)
            for identity, support in reads.whole("AssertionSupport").items()
            if support.assertion_version_id in compatibility_versions
        )
    return lambda kind: inventories[kind] if kind in inventories else retained(kind)


def _authorized_derivations(store, reads, interpretation, selection, spans, revisions, bindings, suppressed):
    """Validate full trusted closures before applying all-input audience grants.

    Every selected view and prose extraction validates against its generation's one inventory,
    scoped to this proof build so later validation always reads current records.
    """
    exact = _derived_generations(reads, _exact_generations(reads, selection))
    views = interpretation("RetrievalView")
    prose = interpretation("ProseExtraction")
    derived = interpretation("DerivedRecord")
    dependencies = interpretation("DerivedDependency")
    selected_outputs = defaultdict(set)
    for member in reads.scoped("GenerationEvidenceMember", "generation_id", exact).values():
        if member.record_kind in {"RetrievalView", "ProseExtraction"}:
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

    inventories = {}
    for generation_id, identity in sorted(selected_outputs["RetrievalView"]):
        view = views.get(identity)
        if view is None:
            raise ValueError("Selected derived retrieval view is missing")
        if generation_id not in inventories:
            inventories[generation_id] = GenerationViews(store, generation_id)
        include(inventories[generation_id].validate(view))
    for generation_id, identity in sorted(selected_outputs["ProseExtraction"]):
        extraction = prose.get(identity)
        if extraction is None:
            raise ValueError("Selected prose extraction is missing")
        if generation_id not in inventories:
            inventories[generation_id] = GenerationViews(store, generation_id)
        if include(inventories[generation_id].validate_prose(extraction)):
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

    def _groups(self, reads=None) -> frozenset[str]:
        """The enabled groups and teams this reader holds in this workspace, each looked up by ID."""
        reads = _ProofReads(self.store, bounded=False) if reads is None else reads
        memberships = [
            member for member in reads.whole("GroupMembership").values() if self._membership(member)
        ]
        group_objects = reads.by_id("KnowledgeObject", {member.group_id for member in memberships})
        return frozenset(
            member.group_id
            for member in memberships
            if (group := group_objects.get(member.group_id)) is not None
            and group.workspace_id == self.workspace_id
            and group.kind in {"group", "team"}
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
        # A proof over explicit generations reads only what they can serve (`_ProofReads`); the
        # authorization tables below stay whole reads through `rows`.
        reads = _ProofReads(self.store, bounded=selection.generation_ids is not None)
        rows = reads.whole
        member_rows = (
            rows("GenerationMember")
            if selection.generation_ids is None
            else reads.scoped("GenerationMember", "generation_id", selection.generation_ids)
        )
        generation_members = {
            (member.generation_id, member.artifact_revision_id) for member in member_rows.values()
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
        interpretation = _interpretation_inventory(reads, selection, selected_revisions)
        selected_revision_rows = (
            None if selected_revisions is None else reads.by_id("ArtifactRevision", selected_revisions)
        )
        selected_artifacts = (
            None
            if selected_revision_rows is None
            else {revision.artifact_id for revision in selected_revision_rows.values()}
        )

        suppressed = self._suppressed(selection.query_mode)
        groups = self._groups(reads)
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
            candidates = (
                rows("Artifact")
                if selected_artifacts is None
                else reads.by_id("Artifact", selected_artifacts)
            )
            for artifact in candidates.values():
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
        revision_rows = rows("ArtifactRevision") if selected_revision_rows is None else selected_revision_rows
        revisions = {
            record.id: record
            for record in revision_rows.values()
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
        observed = [
            record
            for record in interpretation("ObjectObservation").values()
            if record.span_id in spans and record.revision_id == spans[record.span_id].revision_id
        ]
        observed_objects = reads.by_id("KnowledgeObject", {record.object_id for record in observed})
        observations = {
            record.id: record
            for record in observed
            if (obj := observed_objects.get(record.object_id)) is not None
            and obj.workspace_id == self.workspace_id
        }
        objects = frozenset(record.object_id for record in observations.values())
        all_groups = defaultdict(list)
        for support in interpretation("AssertionSupport").values():
            all_groups[(support.assertion_version_id, support.derivation_group)].append(support)
        assertion_versions = interpretation("AssertionVersion")
        assertion_rows = reads.by_id(
            "Assertion",
            {
                version.assertion_id
                for version_id, _ in all_groups
                if (version := assertion_versions.get(version_id)) is not None
            },
        )
        versions, assertions, supports, complete_groups = set(), set(), set(), []
        for (version_id, group_name), members in sorted(all_groups.items()):
            version = assertion_versions.get(version_id)
            if (
                version is None
                or ("assertion_version", version_id) in suppressed
                or (
                    selection.assertion_version_ids is not None
                    and version_id not in selection.assertion_version_ids
                )
            ):
                continue
            assertion = assertion_rows.get(version.assertion_id)
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
        binding_rows = (
            rows("NativeBinding")
            if selection.generation_ids is None
            else reads.scoped("NativeBinding", "generation_id", selection.generation_ids)
        )
        binding_generations = reads.by_id(
            "Generation", {binding.generation_id for binding in binding_rows.values()}
        )
        for binding in binding_rows.values():
            if (
                binding.span_id not in spans
                or binding.object_id not in objects
                or (
                    selection.generation_ids is not None
                    and binding.generation_id not in selection.generation_ids
                )
            ):
                continue
            generation = binding_generations.get(binding.generation_id)
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
            self.store, reads, interpretation, selection, spans, revisions, bindings, suppressed
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
