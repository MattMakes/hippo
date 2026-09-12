"""Shared evidence validation and backend persistence, never an unscoped public read.

Managed reads apply principal/group/evidence authorization; source rank is an
additional intersection. Internal
write validation uses private lookups and does not expose a bypass transport.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import get_args, get_origin

from ..access import Access
from ..knowledge import model as k
from ..knowledge.identity import canonical_json

LOCAL_MAPPING_AUTHORITY = "local"
"""The one identity mapping this application reviews itself: its own local User records."""

# Typed scalar references, validated on write and materialized where traversal needs them.
REFERENCES = {
    "WorkspaceMembership": {"workspace_id": "Workspace", "principal_id": "User"},
    "GroupMembership": {"workspace_id": "Workspace", "principal_id": "User", "group_id": "KnowledgeObject"},
    "Connector": {"workspace_id": "Workspace"},
    "Artifact": {
        "workspace_id": "Workspace",
        "source_id": "Source",
        "connector_id": "Connector",
        "policy_id": "AccessPolicy",
    },
    "ArtifactRevision": {"artifact_id": "Artifact"},
    "Generation": {"source_id": "Source", "parent_id": "Generation"},
    "GenerationEvidenceMember": {"generation_id": "Generation"},
    "SnapshotReference": {"snapshot_id": "QuerySnapshot", "workspace_id": "Workspace"},
    "GenerationMember": {"generation_id": "Generation", "artifact_revision_id": "ArtifactRevision"},
    "EvidenceSpan": {"revision_id": "ArtifactRevision", "policy_id": "AccessPolicy"},
    "KnowledgeObject": {"workspace_id": "Workspace"},
    "ObjectObservation": {
        "object_id": "KnowledgeObject",
        "revision_id": "ArtifactRevision",
        "span_id": "EvidenceSpan",
    },
    "Assertion": {
        "workspace_id": "Workspace",
        "subject_id": "KnowledgeObject",
        "object_id": "KnowledgeObject",
    },
    "AssertionVersion": {"assertion_id": "Assertion"},
    "AssertionSupport": {"assertion_version_id": "AssertionVersion", "span_id": "EvidenceSpan"},
    "NativeBinding": {
        "generation_id": "Generation",
        "object_id": "KnowledgeObject",
        "span_id": "EvidenceSpan",
    },
    "AccessPolicy": {"workspace_id": "Workspace"},
    "SyncState": {"connector_id": "Connector"},
    "SyncRun": {"connector_id": "Connector", "source_id": "Source", "expected_parent_id": "Generation"},
    "MaintenanceJob": {"source_id": "Source", "expected_parent_id": "Generation"},
    "SourceEvent": {"connector_id": "Connector", "artifact_id": "Artifact"},
    "IndexManifest": {"generation_id": "Generation"},
    "DerivedDependency": {"derived_record_id": "DerivedRecord"},
    "Suppression": {"workspace_id": "Workspace"},
    "PurgeJob": {"workspace_id": "Workspace"},
    "IndexEvent": {"workspace_id": "Workspace", "generation_id": "Generation"},
    "LinkGeneration": {"workspace_id": "Workspace"},
    "HistoryManifest": {"workspace_id": "Workspace"},
    "DerivedRecord": {"workspace_id": "Workspace"},
    "ConsumerAck": {"event_id": "IndexEvent"},
    "ProseExtraction": {"generation_id": "Generation", "derived_record_id": "DerivedRecord"},
    "RetrievalView": {
        "object_id": "KnowledgeObject",
        "span_id": "EvidenceSpan",
        "source_revision_id": "ArtifactRevision",
        "derived_record_id": "DerivedRecord",
    },
    "Section": {"source_revision_id": "ArtifactRevision", "parent_section_id": "Section"},
    "SectionMember": {"section_id": "Section"},
    "ConflictSet": {"workspace_id": "Workspace"},
    "Alias": {"workspace_id": "Workspace", "target_object_id": "KnowledgeObject"},
    "QuerySnapshot": {"workspace_id": "Workspace", "link_generation_id": "LinkGeneration"},
}
LIST_REFERENCES = {
    "ProseExtraction": {"support_passage_ids": "Passage"},
    "LinkGeneration": {"assertion_version_ids": "AssertionVersion"},
    "HistoryManifest": {
        "revision_ids": "ArtifactRevision",
        "assertion_version_ids": "AssertionVersion",
        "link_generation_ids": "LinkGeneration",
    },
    "DerivedRecord": {"input_revision_ids": "ArtifactRevision", "input_binding_ids": "NativeBinding"},
    "Section": {"original_span_ids": "EvidenceSpan"},
    "ConflictSet": {"assertion_version_ids": "AssertionVersion", "support_span_ids": "EvidenceSpan"},
    "Alias": {"support_span_ids": "EvidenceSpan"},
    "QuerySnapshot": {"history_manifest_ids": "HistoryManifest"},
}
REL_FIELDS = {
    "Assertion": [
        ("SUBJECT_OBJECT", "KnowledgeObject", "subject_id"),
        ("TARGET_OBJECT", "KnowledgeObject", "object_id"),
    ],
    "AssertionVersion": [("VERSION_OF", "Assertion", "assertion_id")],
    "AssertionSupport": [
        ("SUPPORT_VERSION", "AssertionVersion", "assertion_version_id"),
        ("SUPPORT_SPAN", "EvidenceSpan", "span_id"),
    ],
    "ArtifactRevision": [("REVISION_OF", "Artifact", "artifact_id")],
    "EvidenceSpan": [("SPAN_REVISION", "ArtifactRevision", "revision_id")],
    "ObjectObservation": [
        ("OBSERVED_OBJECT", "KnowledgeObject", "object_id"),
        ("OBSERVATION_SPAN", "EvidenceSpan", "span_id"),
    ],
    "GenerationMember": [
        ("MEMBER_GENERATION", "Generation", "generation_id"),
        ("MEMBER_REVISION", "ArtifactRevision", "artifact_revision_id"),
    ],
    "NativeBinding": [
        ("BINDING_OBJECT", "KnowledgeObject", "object_id"),
        ("BINDING_SPAN", "EvidenceSpan", "span_id"),
    ],
    "SectionMember": [("SECTION_PARENT", "Section", "section_id")],
    "GenerationEvidenceMember": [("EVIDENCE_GENERATION", "Generation", "generation_id")],
    "SnapshotReference": [("REFERENCE_SNAPSHOT", "QuerySnapshot", "snapshot_id")],
}
# Only these lifecycle fields may change under the same record identity.
MUTABLE_FIELDS = {
    "WorkspaceMembership": {"enabled", "mapping_authority", "policy_epoch"},
    "GroupMembership": {"enabled", "mapping_authority", "policy_epoch"},
    "Connector": {"enabled", "config_json", "credential_ref", "capabilities_json"},
    "Artifact": {"deleted_at", "policy_id", "canonical_uri"},
    "Generation": {"status", "published_at", "coverage_json"},
    "AccessPolicy": {"verified_at", "expires_at"},
    "SyncState": {"cursor_json", "watermark", "last_success_at", "last_reconciled_at", "error_code"},
    "SyncRun": {
        "phase",
        "cursor_json",
        "lease_owner",
        "lease_expires_at",
        "fencing_token",
        "attempt_count",
        "retry_at",
        "error_code",
        "status",
    },
    "MaintenanceJob": {
        "phase",
        "cursor_json",
        "lease_owner",
        "lease_expires_at",
        "fencing_token",
        "attempt_count",
        "retry_at",
        "error_code",
        "status",
    },
    "SourceEvent": {"acceptance_state"},
    "DerivedRecord": {"state"},
    "PurgeJob": {
        "phase",
        "removal_manifest_ids",
        "raw_status",
        "derived_status",
        "saved_output_status",
        "backup_disposition",
        "completed_at",
    },
    "IndexEvent": {"state"},
    "ConsumerAck": {
        "state",
        "attempt_count",
        "lease_owner",
        "lease_expires_at",
        "fencing_token",
        "retry_at",
        "acknowledged_at",
    },
}


def _selected_principals(principal_ids):
    """The explicit selection, sorted and unique; None means every live local User."""
    if principal_ids is None:
        return None
    if isinstance(principal_ids, (str, bytes)) or not isinstance(principal_ids, Iterable):
        raise TypeError("Selected principals must be an iterable of identities")
    selected = list(principal_ids)
    if any(type(value) is not str or not value for value in selected):
        raise ValueError("Selected principals must be nonempty identity strings")
    return sorted(set(selected))


def _json_field(model, field):
    from pydantic import BaseModel

    from .migrations import plain_annotation

    annotation = plain_annotation(model.model_fields[field].annotation)
    origin = get_origin(annotation)
    if origin is tuple:
        return plain_annotation(get_args(annotation)[0]) is not str
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return True
    return origin is not None and origin is not __import__("typing").Literal


class KnowledgeQueries:
    def authorization_epoch(self) -> int:
        from .authorization import authorization_epoch

        return authorization_epoch(self)

    def _bump_authorization_epoch(self) -> int:
        from .authorization import bump_authorization_epoch

        return bump_authorization_epoch(self)

    def _lock_authorization(self) -> None:
        from .authorization import lock_authorization

        lock_authorization(self)

    # ------------------------------------------- the local workspace mapping

    def ensure_local_workspace_memberships(self, principal_ids: Iterable[str] | None = None) -> int:
        """Map this installation's live local Users into its one default workspace.

        Idempotent, and deliberately additive-only: it adds or repairs memberships
        and adds the local authority, so the only proof it can stale is a *denial*,
        which fails safe. It therefore never bumps the authorization epoch - the
        lazy first `ping()` runs this while a request may already hold a query
        session, and invalidating that reader would be the only harm it could do.
        Every reduction goes through `permission_mutation`, which owns its bump.
        """
        with self.transaction():
            self._lock_authorization()
            return self._ensure_local_workspace_memberships_locked(principal_ids)

    def _ensure_local_workspace_memberships_locked(self, principal_ids: Iterable[str] | None = None) -> int:
        """The mapping repair itself; the caller owns the transaction, lock and epoch bump."""
        from .migrations import DEFAULT_WORKSPACE_ID

        selected = _selected_principals(principal_ids)
        if not self._local_mapping_available():
            return 0
        changes = 0
        authorities = self._reviewed_mapping_authorities()
        reviewed = sorted(set(authorities) | {LOCAL_MAPPING_AUTHORITY})
        if reviewed != authorities:
            self._set_meta_locked("reviewed_mapping_authorities", reviewed)
            changes += 1
        live = {row["id"] for row in self.list_users()}
        if selected is None:
            selected = sorted(live)
        elif not set(selected) <= live:
            raise ValueError("Unknown local principal cannot be mapped into the workspace")
        for principal_id in selected:
            changes += self._apply_local_membership(DEFAULT_WORKSPACE_ID, principal_id, enabled=True)
        return changes

    def _disable_local_workspace_memberships_locked(self, principal_ids: Iterable[str]) -> int:
        """Retire a principal's mapping as audit state, keeping the record and its history.

        Called while the User still exists, so the retained membership reference
        stays valid. The caller owns the transaction, lock and epoch bump.
        """
        from .migrations import DEFAULT_WORKSPACE_ID

        selected = _selected_principals(principal_ids)
        if selected is None:
            raise ValueError("Retiring a local mapping requires explicit principals")
        if not self._local_mapping_available():
            return 0
        return sum(
            self._apply_local_membership(DEFAULT_WORKSPACE_ID, principal_id, enabled=False)
            for principal_id in selected
        )

    def _apply_local_membership(self, workspace_id: str, principal_id: str, *, enabled: bool) -> int:
        """One reviewed local membership per principal; repair moves `policy_epoch` forward."""
        record = k.WorkspaceMembership(
            workspace_id=workspace_id,
            principal_id=principal_id,
            enabled=enabled,
            mapping_authority=LOCAL_MAPPING_AUTHORITY,
            policy_epoch=1,
        )
        existing = self._knowledge_get("WorkspaceMembership", record.id)
        if existing is None:
            if not enabled:
                return 0  # Nothing was ever mapped here; do not invent audit state.
            self._validate_knowledge(record)
            self._check_knowledge_write(record)
            self._write_knowledge(record, create_only=True)
            return 1
        # Retiring keeps the authority that granted the mapping: the disabled record is
        # audit state, so a provider- or group-granted row is never rewritten as local.
        authority = LOCAL_MAPPING_AUTHORITY if enabled else existing.mapping_authority
        if (existing.enabled, existing.mapping_authority) == (enabled, authority):
            return 0
        repaired = existing.replace(
            enabled=enabled,
            mapping_authority=authority,
            policy_epoch=existing.policy_epoch + 1,
        )
        self._validate_knowledge(repaired)
        self._check_knowledge_write(repaired, existing)
        self._write_knowledge(repaired)
        return 1

    def _local_mapping_available(self) -> bool:
        """A store still on an older physical schema has no mapping to maintain yet.

        Migration creates the membership records and then the application maps its
        users; a permission mutation against a pre-schema-5 file must not fail.
        A user created while this is false is therefore left unmapped and stays
        unmapped - fail-closed, no managed evidence - until the next
        `on_first_connection` runs the all-user form and repairs it.
        """
        from .migrations import CURRENT_SCHEMA_VERSION

        row = self.schema_version()
        return bool(row and row.get("version") == CURRENT_SCHEMA_VERSION and row.get("state") == "complete")

    def _reviewed_mapping_authorities(self) -> list[str]:
        authorities = self.get_meta("reviewed_mapping_authorities") or []
        if not isinstance(authorities, list) or any(
            not isinstance(item, str) or not item for item in authorities
        ):
            raise RuntimeError("Invalid reviewed membership authority configuration")
        return authorities

    def _set_meta_locked(self, key: str, value) -> None:
        """Write metadata without `metadata_mutation`'s own bump; the caller owns exactly one.

        The value is built from an already validated list, so skipping that
        decorator skips no check that this caller has not already made.
        """
        writer = getattr(type(self).set_meta, "__wrapped__", None)
        if writer is None:
            raise RuntimeError("Metadata writer is not a reviewed authorization mutation")
        writer(self, key, value)

    def _ensure_knowledge_ready(self):
        if not getattr(self, "_schema_checked", False) and not self._migrating:
            self.ensure_schema()
        if self._migration_blocked and not self._migrating:
            raise RuntimeError("Store migration is incomplete; application access is disabled")

    def schema_version(self):
        from .migrations import schema_version

        return schema_version(self)

    def schema_history(self):
        from .migrations import schema_history

        return schema_history(self)

    def _knowledge_rows(self, name: str) -> list[k.Record]:
        model = k.RECORD_TYPES.get(name)
        if model is None:
            raise ValueError("Unknown knowledge record type")
        if self.knowledge_backend == "fake":
            return list(self._knowledge_data.get(name, {}).values())
        columns = model.model_fields
        rows = self.run(f"MATCH (n:{name}) RETURN " + ", ".join(f"n.{field} AS {field}" for field in columns))
        records = []
        for row in rows:
            for field, value in row.items():
                if isinstance(value, datetime):
                    row[field] = (
                        value.replace(tzinfo=UTC).isoformat() if value.tzinfo is None else value.isoformat()
                    )
                elif hasattr(value, "to_native"):
                    row[field] = value.to_native().isoformat()
                elif value is not None and _json_field(model, field):
                    row[field] = json.loads(value)
            records.append(model.model_validate_json(canonical_json(row)))
        return records

    def _knowledge_get(self, name: str, record_id: str):
        # Internal-only reference lookups; public access never defaults to unrestricted.
        if name == "Source":
            return self.get_source(record_id)
        if name == "Passage":
            return next((row for row in self._native_rows("Passage") if row["id"] == record_id), None)
        if name == "User":
            return self.get_user(record_id)
        if name in {"Symbol", "DataObject", "Commit"}:
            if self.knowledge_backend == "fake":
                return getattr(
                    self, {"Symbol": "symbols", "DataObject": "data_objects", "Commit": "commits"}[name]
                ).get(record_id)
            return self.run_one(
                f"MATCH (n:{name} {{id:$id}}) RETURN n.source_id AS source_id, n.generation_id AS generation_id",
                id=record_id,
            )
        return next((record for record in self._knowledge_rows(name) if record.id == record_id), None)

    def _write_knowledge(self, record: k.Record, *, create_only: bool = False) -> None:
        from .migrations import KNOWLEDGE_COLUMNS

        name = type(record).__name__
        if self.knowledge_backend == "fake":
            self._knowledge_data.setdefault(name, {})[record.id] = record
            return
        values = record.model_dump(mode="json")
        for field, value in list(values.items()):
            if value is not None and _json_field(type(record), field):
                values[field] = canonical_json(value)
            if KNOWLEDGE_COLUMNS[name][field] == "TIMESTAMP" and value is not None:
                values[field] = datetime.fromisoformat(value)
                if self.knowledge_backend == "ladybug":
                    values[field] = values[field].replace(tzinfo=None)
        if self.knowledge_backend == "neo4j":
            assignment = "ON CREATE SET" if create_only else "SET"
            self.run(f"MERGE (n:{name} {{id:$id}}) {assignment} n += $values", id=record.id, values=values)
            if create_only and self._knowledge_get(name, record.id) != record:
                raise ValueError("Immutable record already exists with different contents")
        else:
            assignments = []
            values.pop("id")
            for field, value in list(values.items()):
                kind = KNOWLEDGE_COLUMNS[name][field]
                if kind == "STRING":
                    values[field] = value.encode("utf-8") if value is not None else None
                    expression = f"decode(CAST(${field} AS BLOB))"
                elif kind == "STRING[]":
                    values[field] = [item.encode("utf-8") for item in value] if value is not None else None
                    expression = f"list_transform(CAST(${field} AS BLOB[]), x -> decode(x))"
                else:
                    expression = f"${field}"
                assignments.append(f"n.{field}={expression}")
            self.run(
                f"MERGE (n:{name} {{id:$knowledge_record_pk}}) SET " + ", ".join(assignments),
                knowledge_record_pk=record.id,
                **values,
            )
        for relation, target, field in REL_FIELDS.get(name, []):
            self.run(
                f"MATCH (n:{name} {{id:$id}}), (t:{target} {{id:$target}}) MERGE (n)-[:{relation}]->(t)",
                id=record.id,
                target=getattr(record, field),
            )

    def _references(self, record):
        refs = [
            (target, getattr(record, field))
            for field, target in REFERENCES.get(type(record).__name__, {}).items()
            if getattr(record, field) is not None
        ]
        refs += [
            (target, value)
            for field, target in LIST_REFERENCES.get(type(record).__name__, {}).items()
            for value in getattr(record, field)
        ]
        if isinstance(record, k.ProseExtraction):
            refs.append(("EvidenceSpan" if record.input_kind == "span" else "RetrievalView", record.input_id))
        if isinstance(record, k.GenerationEvidenceMember):
            refs.append((record.record_kind, record.record_id))
        if isinstance(record, k.NativeBinding):
            refs.append((record.native_kind, record.native_id))
        if isinstance(record, k.SectionMember):
            refs.append(("Section" if record.child_kind == "section" else "EvidenceSpan", record.child_id))
        if isinstance(record, k.DerivedDependency):
            refs.append(
                (
                    {
                        "revision": "ArtifactRevision",
                        "span": "EvidenceSpan",
                        "binding": "NativeBinding",
                        "assertion_version": "AssertionVersion",
                        "policy": "AccessPolicy",
                        "generation": "Generation",
                        "link_generation": "LinkGeneration",
                        "derived_record": "DerivedRecord",
                    }[record.input_kind],
                    record.input_id,
                )
            )
        if isinstance(record, k.Suppression):
            refs.append(
                (
                    {
                        "source": "Source",
                        "artifact": "Artifact",
                        "revision": "ArtifactRevision",
                        "span": "EvidenceSpan",
                        "assertion_version": "AssertionVersion",
                        "derived_record": "DerivedRecord",
                        "policy": "AccessPolicy",
                    }[record.target_kind],
                    record.target_id,
                )
            )
        if isinstance(record, k.QuerySnapshot):
            refs += [("Generation", source.generation_id) for source in record.sources]
            refs += [("Source", source.source_id) for source in record.sources]
        return refs

    def _workspaces(self, record, seen=None) -> set[str]:
        if isinstance(record, dict):
            return (
                {
                    record.get("workspace_id")
                    or __import__(
                        "hippo.store.migrations", fromlist=["DEFAULT_WORKSPACE_ID"]
                    ).DEFAULT_WORKSPACE_ID
                }
                if "source_id" not in record
                else self._workspaces(self.get_source(record["source_id"]))
            )
        if isinstance(record, k.Workspace):
            return {record.id}
        if hasattr(record, "workspace_id"):
            return {record.workspace_id}
        seen = set() if seen is None else seen
        if record.id in seen:
            return set()
        seen.add(record.id)
        result = set()
        for name, rid in self._references(record):
            reference = self._knowledge_get(name, rid)
            if reference is not None:
                result |= self._workspaces(reference, seen)
        return result

    def _validate_knowledge(self, record):
        from .authorization import configured_provider, safer_connector

        if isinstance(record, k.Connector) and configured_provider(record) and self.count_users() == 0:
            existing = self._knowledge_get("Connector", record.id)
            if not safer_connector(existing, record):
                raise ValueError(
                    "Provider connectors require a signed-in installation; open mode cannot configure or enable them"
                )
        refs = []
        for name, rid in self._references(record):
            reference = self._knowledge_get(name, rid)
            if reference is None:
                raise ValueError(f"Missing {name} reference")
            refs.append(reference)
        workspaces = self._workspaces(record)
        for reference in refs:
            if not isinstance(reference, dict) or "username" not in reference:
                workspaces |= self._workspaces(reference)
        if len(workspaces) > 1:
            raise ValueError("Knowledge references cross workspace boundaries")
        if isinstance(record, k.Artifact) and record.connector_id is not None:
            connector = self._knowledge_get("Connector", record.connector_id)
            if connector.instance_url != record.provider_instance:
                raise ValueError("Artifact provider differs from its connector provider")
        if isinstance(record, k.SourceEvent):
            connector = self._knowledge_get("Connector", record.connector_id)
            if connector.instance_url != record.provider_instance:
                raise ValueError("Source event provider differs from its connector")
            if record.artifact_id is not None:
                artifact = self._knowledge_get("Artifact", record.artifact_id)
                if (
                    artifact.connector_id != record.connector_id
                    or artifact.provider_instance != record.provider_instance
                    or artifact.external_id != record.provider_artifact_id
                ):
                    raise ValueError("Source event provider identity differs from its artifact")
        if isinstance(record, k.SectionMember):
            parent = self._knowledge_get("Section", record.section_id)
            if record.child_kind == "section":
                child_revision = self._knowledge_get("Section", record.child_id).source_revision_id
            else:
                child_revision = self._knowledge_get("EvidenceSpan", record.child_id).revision_id
            if parent.source_revision_id != child_revision:
                raise ValueError("Section member belongs to another revision")
        if isinstance(record, k.Generation) and record.parent_id is not None:
            if self._knowledge_get("Generation", record.parent_id).source_id != record.source_id:
                raise ValueError("Generation parent belongs to another source")
        if isinstance(record, k.QuerySnapshot):
            for member in record.sources:
                if self._knowledge_get("Generation", member.generation_id).source_id != member.source_id:
                    raise ValueError("Snapshot generation belongs to another source")
        if isinstance(record, k.Section):
            revisions = {
                self._knowledge_get("EvidenceSpan", span).revision_id for span in record.original_span_ids
            }
            if record.parent_section_id is not None:
                revisions.add(self._knowledge_get("Section", record.parent_section_id).source_revision_id)
            if revisions != {record.source_revision_id}:
                raise ValueError("Section evidence belongs to another revision")
        if isinstance(record, k.Assertion):
            record.validate_endpoints(
                self._knowledge_get("KnowledgeObject", record.subject_id),
                self._knowledge_get("KnowledgeObject", record.object_id),
            )
        if (
            isinstance(record, k.ObjectObservation)
            and self._knowledge_get("EvidenceSpan", record.span_id).revision_id != record.revision_id
        ):
            raise ValueError("Observation span belongs to another revision")
        if isinstance(record, k.GenerationMember):
            revision = self._knowledge_get("ArtifactRevision", record.artifact_revision_id)
            artifact = self._knowledge_get("Artifact", revision.artifact_id)
            if artifact.source_id != self._knowledge_get("Generation", record.generation_id).source_id:
                raise ValueError("Generation member belongs to another source")
        if (
            isinstance(record, k.RetrievalView)
            and self._knowledge_get("EvidenceSpan", record.span_id).revision_id != record.source_revision_id
        ):
            raise ValueError("Retrieval view source revision differs from its span")
        if isinstance(record, k.NativeBinding):
            span = self._knowledge_get("EvidenceSpan", record.span_id)
            revision = self._knowledge_get("ArtifactRevision", span.revision_id)
            source_id = self._knowledge_get("Artifact", revision.artifact_id).source_id
            native = self._knowledge_get(record.native_kind, record.native_id)
            if (
                source_id != self._knowledge_get("Generation", record.generation_id).source_id
                or native["source_id"] != source_id
            ):
                raise ValueError("Native binding crosses source boundaries")

    def put_knowledge(self, record: k.Record) -> str:
        if (
            type(record).__name__ not in k.RECORD_TYPES
            or type(record) is not k.RECORD_TYPES[type(record).__name__]
        ):
            raise TypeError("Expected a registered immutable knowledge record")
        record = type(record).model_validate(record)
        with self.transaction():
            self._lock_authorization()
            self._validate_knowledge(record)
            existing = self._knowledge_get(type(record).__name__, record.id)
            if existing is not None and existing != record:
                raise ValueError("Immutable record already exists with different contents")
            if existing is None:
                self._check_knowledge_write(record)
                self._write_knowledge(record, create_only=True)
                from .authorization import record_mutation

                record_mutation(self, record)
        return record.id

    def update_knowledge(self, record: k.Record) -> str:
        if (
            type(record).__name__ not in k.RECORD_TYPES
            or type(record) is not k.RECORD_TYPES[type(record).__name__]
        ):
            raise TypeError("Expected a registered immutable knowledge record")
        record = type(record).model_validate(record)
        with self.transaction():
            self._lock_authorization()
            if self.knowledge_backend == "neo4j":
                # Lock before reading lifecycle state; two processes must not both
                # close the same historical interpretation from an old open view.
                self.run(
                    f"MATCH (n:{type(record).__name__} {{id:$id}}) SET n._knowledge_lock=coalesce(n._knowledge_lock,0)+1 RETURN n.id AS id",
                    id=record.id,
                )
            existing = self._knowledge_get(type(record).__name__, record.id)
            if existing is None:
                raise ValueError("Cannot update a missing record")
            self._validate_knowledge(record)
            changed = {
                key for key, value in record.model_dump().items() if value != existing.model_dump()[key]
            }
            allowed = MUTABLE_FIELDS.get(type(record).__name__, set())
            if isinstance(record, (k.ObjectObservation, k.AssertionVersion)):
                allowed = {"recorded_to"}
                if changed and (existing.recorded_to is not None or record.recorded_to is None):
                    raise ValueError("Recorded interval may only close once monotonically")
            if not changed <= allowed:
                raise ValueError("Update changes immutable evidence fields")
            for field in ("fencing_token", "attempt_count", "policy_epoch"):
                if field in changed and getattr(record, field) < getattr(existing, field):
                    raise ValueError("Lifecycle counters cannot decrease")
            if changed:
                self._check_knowledge_write(record, existing)
                self._write_knowledge(record)
                from .authorization import record_mutation

                record_mutation(self, record, existing)
        return record.id

    def _reader_proof(self, workspace_id: str, access: Access, *, expected_epoch=None, selection=None):
        from ..knowledge.access import AuthorizationChanged, EvidenceAccess

        expected_epoch = self.authorization_epoch() if expected_epoch is None else expected_epoch

        authorities = self.get_meta("reviewed_mapping_authorities") or []
        if not isinstance(authorities, list) or any(
            not isinstance(item, str) or not item for item in authorities
        ):
            raise RuntimeError("Invalid reviewed membership authority configuration")
        engine = EvidenceAccess(self, workspace_id, access, mapping_authorities=frozenset(authorities))
        proof = engine.build(selection)
        if proof.authorization_epoch != expected_epoch:
            raise AuthorizationChanged("Authorization changed during the evidence read")
        return engine, proof

    @staticmethod
    def _record_visible(record, access, proof):
        field = {
            "Artifact": "artifact_ids",
            "ArtifactRevision": "revision_ids",
            "EvidenceSpan": "span_ids",
            "ObjectObservation": "observation_ids",
            "KnowledgeObject": "object_ids",
            "Assertion": "assertion_ids",
            "AssertionVersion": "assertion_version_ids",
            "AssertionSupport": "support_ids",
            "NativeBinding": "native_binding_ids",
        }.get(type(record).__name__)
        if field is not None:
            return record.id in getattr(proof, field)
        # Control records contain credentials, complete inventory counts or derived
        # text. Their user-facing DTOs must be rendered by the owning service.
        return False

    def get_knowledge(self, name: str, record_id: str, *, workspace_id: str, access: Access):
        self._ensure_knowledge_ready()
        if name not in k.RECORD_TYPES:
            raise ValueError("Unknown knowledge record type")
        if not isinstance(access, Access) or not workspace_id:
            raise TypeError("Knowledge reads require explicit workspace and Access")
        epoch = self.authorization_epoch()
        record = self._knowledge_get(name, record_id)
        if record is None or self._workspaces(record) != {workspace_id}:
            return None
        if access.audience_kind == "internal":
            return record
        engine, proof = self._reader_proof(workspace_id, access, expected_epoch=epoch)
        visible = self._record_visible(record, access, proof)
        engine.validate_current(proof)
        return record if visible else None

    def list_knowledge(self, name: str, *, workspace_id: str, access: Access):
        self._ensure_knowledge_ready()
        if not isinstance(access, Access) or not workspace_id:
            raise TypeError("Knowledge reads require explicit workspace and Access")
        epoch = self.authorization_epoch()
        records = [
            record for record in self._knowledge_rows(name) if self._workspaces(record) == {workspace_id}
        ]
        if access.audience_kind == "internal":
            return records
        engine, proof = self._reader_proof(workspace_id, access, expected_epoch=epoch)
        visible = [record for record in records if self._record_visible(record, access, proof)]
        engine.validate_current(proof)
        return visible
