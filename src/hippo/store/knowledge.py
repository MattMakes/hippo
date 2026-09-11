"""Shared evidence validation and backend persistence, never an unscoped public read.

Task 4 supplies the full principal/group/snapshot authorization engine. Until then
provider policies fail closed; source rank is an additional intersection. Internal
write validation uses private lookups and does not expose a bypass transport.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import get_args, get_origin

from ..access import Access
from ..knowledge import model as k
from ..knowledge.identity import canonical_json

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
        if name == "User":
            return self.get_user(record_id)
        if name in {"Symbol", "DataObject", "Commit"}:
            if self.knowledge_backend == "fake":
                return getattr(
                    self, {"Symbol": "symbols", "DataObject": "data_objects", "Commit": "commits"}[name]
                ).get(record_id)
            return self.run_one(f"MATCH (n:{name} {{id:$id}}) RETURN n.source_id AS source_id", id=record_id)
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
                f"MERGE (n:{name} {{id:$record_id}}) SET " + ", ".join(assignments),
                record_id=record.id,
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
            self._validate_knowledge(record)
            existing = self._knowledge_get(type(record).__name__, record.id)
            if existing is not None and existing != record:
                raise ValueError("Immutable record already exists with different contents")
            if existing is None:
                self._write_knowledge(record, create_only=True)
        return record.id

    def update_knowledge(self, record: k.Record) -> str:
        if (
            type(record).__name__ not in k.RECORD_TYPES
            or type(record) is not k.RECORD_TYPES[type(record).__name__]
        ):
            raise TypeError("Expected a registered immutable knowledge record")
        record = type(record).model_validate(record)
        with self.transaction():
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
            self._write_knowledge(record)
        return record.id

    def _policy_visible(self, policy, access):
        if access.unrestricted:
            return True
        if policy.mode == "unknown" or (policy.expires_at and policy.expires_at <= datetime.now(UTC)):
            return False
        if access.user_id in policy.deny_users or policy.deny_groups:
            return False
        return policy.mode == "workspace" or (
            access.user_id is not None and access.user_id in policy.allow_users
        )

    def _record_visible(self, record, access, seen=None):
        if access.unrestricted:
            return True
        if isinstance(record, (k.WorkspaceMembership, k.GroupMembership)):
            return access.user_id is not None and record.principal_id == access.user_id
        if record is None or isinstance(record, dict):
            return False
        seen = set() if seen is None else seen
        if record.id in seen:
            return False
        seen = seen | {record.id}
        if isinstance(record, k.AccessPolicy):
            return self._policy_visible(record, access)
        if isinstance(record, k.EvidenceSpan):
            policy = self._knowledge_get("AccessPolicy", record.policy_id)
            revision = self._knowledge_get("ArtifactRevision", record.revision_id)
            return self._policy_visible(policy, access) and self._record_visible(revision, access, seen)
        if isinstance(record, k.ObjectObservation):
            return self._record_visible(self._knowledge_get("EvidenceSpan", record.span_id), access, seen)
        if isinstance(record, k.Artifact):
            return access.can_see_source(self.get_source(record.source_id)) and self._policy_visible(
                self._knowledge_get("AccessPolicy", record.policy_id), access
            )
        if isinstance(record, k.AssertionVersion):
            groups = {}
            for support in self._knowledge_rows("AssertionSupport"):
                if support.assertion_version_id == record.id:
                    groups.setdefault(support.derivation_group, []).append(support.span_id)
            return any(
                all(
                    self._record_visible(self._knowledge_get("EvidenceSpan", span), access, seen)
                    for span in spans
                )
                for spans in groups.values()
            )
        if isinstance(record, k.Assertion):
            return any(
                version.assertion_id == record.id and self._record_visible(version, access, seen)
                for version in self._knowledge_rows("AssertionVersion")
            )
        if isinstance(record, k.KnowledgeObject):
            return any(
                obs.object_id == record.id and self._record_visible(obs, access, seen)
                for obs in self._knowledge_rows("ObjectObservation")
            )
        refs = self._references(record)
        if not refs:
            return isinstance(record, k.Workspace)
        return all(
            access.can_see_source(reference)
            if isinstance(reference, dict) and "kind" in reference
            else self._record_visible(reference, access, seen)
            for name, rid in refs
            if (reference := self._knowledge_get(name, rid)) is not None
        )

    def get_knowledge(self, name: str, record_id: str, *, workspace_id: str, access: Access):
        self._ensure_knowledge_ready()
        if name not in k.RECORD_TYPES:
            raise ValueError("Unknown knowledge record type")
        if not isinstance(access, Access) or not workspace_id:
            raise TypeError("Knowledge reads require explicit workspace and Access")
        record = self._knowledge_get(name, record_id)
        if record is None or self._workspaces(record) != {workspace_id}:
            return None
        return record if self._record_visible(record, access) else None

    def list_knowledge(self, name: str, *, workspace_id: str, access: Access):
        self._ensure_knowledge_ready()
        if not isinstance(access, Access) or not workspace_id:
            raise TypeError("Knowledge reads require explicit workspace and Access")
        return [
            record
            for record in self._knowledge_rows(name)
            if self._workspaces(record) == {workspace_id} and self._record_visible(record, access)
        ]
