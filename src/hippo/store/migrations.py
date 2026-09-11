"""Versioned additive evidence schema; reject incompatible stores before mutation.

Ladybug schema/data changes share a transaction. Neo4j journals idempotent schema
steps separately, then atomically commits data transforms and the completion row.
An incomplete Neo4j migration is never declared ready and must resume before use.
"""

from __future__ import annotations

import types
from datetime import datetime
from typing import Annotated, Literal, Union, get_args, get_origin

from ..knowledge.identity import canonical_json, text_hash
from ..knowledge.model import RECORD_TYPES, Workspace

CURRENT_SCHEMA_VERSION = 2
DEFAULT_WORKSPACE = Workspace(name="default")
DEFAULT_WORKSPACE_ID = DEFAULT_WORKSPACE.id


def plain_annotation(annotation):
    if get_origin(annotation) is Annotated:
        return plain_annotation(get_args(annotation)[0])
    if get_origin(annotation) in (Union, types.UnionType):
        members = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(members) == 1:
            return plain_annotation(members[0])
    return annotation


def _type(annotation) -> str:
    annotation = plain_annotation(annotation)
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        members = [arg for arg in get_args(annotation) if arg is not type(None)]
        return _type(members[0]) if len(members) == 1 else "STRING"
    if origin is Literal:
        return _type(type(get_args(annotation)[0]))
    if annotation is bool:
        return "BOOLEAN"
    if annotation is int:
        return "INT64"
    if annotation is float:
        return "DOUBLE"
    if annotation is datetime:
        return "TIMESTAMP"
    if origin is tuple and plain_annotation(get_args(annotation)[0]) is str:
        return "STRING[]"
    return "STRING"


KNOWLEDGE_COLUMNS = {
    name: {field: _type(info.annotation) for field, info in model.model_fields.items()}
    for name, model in RECORD_TYPES.items()
}
# Explicit graph endpoints mirror scalar references. Membership paths remain typed.
KNOWLEDGE_RELATIONS = [
    ("SUBJECT_OBJECT", "Assertion", "KnowledgeObject"),
    ("TARGET_OBJECT", "Assertion", "KnowledgeObject"),
    ("VERSION_OF", "AssertionVersion", "Assertion"),
    ("SUPPORT_VERSION", "AssertionSupport", "AssertionVersion"),
    ("SUPPORT_SPAN", "AssertionSupport", "EvidenceSpan"),
    ("REVISION_OF", "ArtifactRevision", "Artifact"),
    ("SPAN_REVISION", "EvidenceSpan", "ArtifactRevision"),
    ("OBSERVED_OBJECT", "ObjectObservation", "KnowledgeObject"),
    ("OBSERVATION_SPAN", "ObjectObservation", "EvidenceSpan"),
    ("MEMBER_GENERATION", "GenerationMember", "Generation"),
    ("MEMBER_REVISION", "GenerationMember", "ArtifactRevision"),
    ("BINDING_OBJECT", "NativeBinding", "KnowledgeObject"),
    ("BINDING_SPAN", "NativeBinding", "EvidenceSpan"),
    ("SECTION_PARENT", "SectionMember", "Section"),
]
SOURCE_COLUMNS = {
    "workspace_id": "STRING",
    "active_generation_id": "STRING",
    "generation_version": "INT64",
    "generation_lock": "INT64",
}
PASSAGE_COLUMNS = {
    "generation_id": "STRING",
    "artifact_revision_id": "STRING",
    "span_id": "STRING",
    "parent_passage_id": "STRING",
    "content_kind": "STRING",
    "embedding_profile": "STRING",
}
V1_CHECKSUM = text_hash("hippo-legacy-schema-v1")
MIGRATION_CHECKSUM = text_hash(
    canonical_json(
        [CURRENT_SCHEMA_VERSION, KNOWLEDGE_COLUMNS, KNOWLEDGE_RELATIONS, SOURCE_COLUMNS, PASSAGE_COLUMNS]
    )
)


class SchemaCompatibilityError(RuntimeError):
    pass


def schema_version(store) -> dict | None:
    if store.knowledge_backend == "fake":
        return getattr(store, "_schema_row", None)
    if store.knowledge_backend == "ladybug":
        if not store.run("CALL show_tables() WHERE name = 'SchemaVersion' RETURN name, type"):
            return None
    rows = store.run(
        "MATCH (v:SchemaVersion) RETURN v.version AS version, v.checksum AS checksum, v.state AS state, v.step AS step ORDER BY v.version DESC"
    )
    return rows[0] if rows else None


def check_compatibility(store) -> dict | None:
    row = schema_version(store)
    if row and (
        type(row["version"]) is not int
        or row["version"] not in {1, CURRENT_SCHEMA_VERSION}
        or row["checksum"] != {1: V1_CHECKSUM, CURRENT_SCHEMA_VERSION: MIGRATION_CHECKSUM}.get(row["version"])
    ):
        raise SchemaCompatibilityError(
            "Unsupported schema version or migration checksum; store was not modified"
        )
    return row


def schema_history(store) -> list[dict]:
    if store.knowledge_backend == "fake":
        return [dict(row) for _, row in sorted(store._schema_history.items())]
    return store.run(
        "MATCH (v:SchemaVersion) RETURN v.version AS version, v.checksum AS checksum, v.state AS state, v.step AS step ORDER BY v.version"
    )


def _record_legacy_version(store) -> None:
    row = {"version": 1, "checksum": V1_CHECKSUM, "state": "complete", "step": 0}
    if store.knowledge_backend == "fake":
        store._schema_history.setdefault(1, row)
    elif not store.run("MATCH (v:SchemaVersion {version:1}) RETURN v.id AS id"):
        store.run(
            "CREATE (:SchemaVersion {id:'knowledge-v1',version:1,checksum:$checksum,state:'complete',step:0})",
            checksum=V1_CHECKSUM,
        )


def validate_existing_legacy_shape(store) -> None:
    """Missing old tables can be added, but existing incompatible columns cannot."""
    if store.knowledge_backend != "ladybug":
        return
    from .ladybug import NODE_TABLES

    existing = {row["name"] for row in store.run("CALL show_tables() RETURN name")}
    for name, declaration in NODE_TABLES.items():
        if name not in existing:
            continue
        actual = {row["name"]: row for row in store.run(f"CALL table_info('{name}') RETURN *")}
        for column in declaration.split(","):
            field, kind, *_ = column.split()
            if field not in actual or actual[field]["type"] != {"BOOLEAN": "BOOL"}.get(kind, kind):
                raise SchemaCompatibilityError("Legacy schema shape has an absent or incompatible column")
            if "PRIMARY KEY" in column and not actual[field]["primary key"]:
                raise SchemaCompatibilityError("Legacy schema shape lacks its declared primary key")


def validate_physical_schema(store) -> None:
    """A completion record cannot substitute for the actual schema declarations."""
    if store.knowledge_backend == "fake":
        return
    if store.knowledge_backend == "ladybug":
        tables = {row["name"]: row["type"] for row in store.run("CALL show_tables() RETURN name,type")}
        for name, columns in {
            **KNOWLEDGE_COLUMNS,
            "Source": SOURCE_COLUMNS,
            "Passage": PASSAGE_COLUMNS,
        }.items():
            if tables.get(name) != "NODE":
                raise SchemaCompatibilityError("Evidence schema shape is missing a node table")
            actual = {row["name"]: row for row in store.run(f"CALL table_info('{name}') RETURN *")}
            for field, kind in columns.items():
                if field not in actual or actual[field]["type"] != {"BOOLEAN": "BOOL"}.get(kind, kind):
                    raise SchemaCompatibilityError(
                        "Evidence schema shape has an absent or incompatible column"
                    )
            if name in KNOWLEDGE_COLUMNS and not actual["id"]["primary key"]:
                raise SchemaCompatibilityError("Evidence schema shape lacks its primary key")
        for name, source, target in KNOWLEDGE_RELATIONS:
            if tables.get(name) != "REL" or store.connection_pairs(name) != {(source, target)}:
                raise SchemaCompatibilityError(
                    "Evidence schema shape has incompatible relationship endpoints"
                )
        return
    constraints = {
        row["name"]: row
        for row in store.run(
            "SHOW CONSTRAINTS YIELD name,labelsOrTypes,properties,type RETURN name,labelsOrTypes,properties,type"
        )
    }
    for name in KNOWLEDGE_COLUMNS:
        found = constraints.get(f"knowledge_{name.lower()}_id")
        if (
            found is None
            or found["labelsOrTypes"] != [name]
            or found["properties"] != ["id"]
            or found["type"] != "UNIQUENESS"
        ):
            raise SchemaCompatibilityError(
                "Evidence schema shape has an absent or incompatible uniqueness constraint"
            )
    indexes = {
        row["name"]: row
        for row in store.run(
            "SHOW INDEXES YIELD name,labelsOrTypes,properties,type RETURN name,labelsOrTypes,properties,type"
        )
    }
    for name, columns in KNOWLEDGE_COLUMNS.items():
        for field in columns.keys() & {
            "workspace_id",
            "artifact_id",
            "revision_id",
            "generation_id",
            "predicate",
            "subject_id",
            "object_id",
            "recorded_from",
            "valid_from",
        }:
            found = indexes.get(f"knowledge_{name.lower()}_{field}")
            if (
                found is None
                or found["labelsOrTypes"] != [name]
                or found["properties"] != [field]
                or found["type"] != "RANGE"
            ):
                raise SchemaCompatibilityError(
                    "Evidence schema shape has an absent or incompatible lookup index"
                )


def _version(store, state: str, step: int) -> None:
    row = {"version": CURRENT_SCHEMA_VERSION, "checksum": MIGRATION_CHECKSUM, "state": state, "step": step}
    if store.knowledge_backend == "fake":
        store._schema_row = row
        store._schema_history[CURRENT_SCHEMA_VERSION] = dict(row)
        return
    store.run(
        "MERGE (v:SchemaVersion {id: 'knowledge-v2'}) SET v.version=$version, v.checksum=$checksum, v.state=$state, v.step=$step",
        **row,
    )


def schema_steps(store) -> list[str]:
    if store.knowledge_backend == "ladybug":
        steps = [
            f"CREATE NODE TABLE IF NOT EXISTS {name}("
            + ", ".join(
                f"{field} {kind}" + (" PRIMARY KEY" if field == "id" else "")
                for field, kind in columns.items()
            )
            + ")"
            for name, columns in KNOWLEDGE_COLUMNS.items()
        ]
        steps += [
            f"CREATE REL TABLE IF NOT EXISTS {name}(FROM {source} TO {target})"
            for name, source, target in KNOWLEDGE_RELATIONS
        ]
        steps += [
            f"ALTER TABLE {table} ADD IF NOT EXISTS {field} {kind}"
            for table, columns in (("Source", SOURCE_COLUMNS), ("Passage", PASSAGE_COLUMNS))
            for field, kind in columns.items()
        ]
        return steps
    return [
        f"CREATE CONSTRAINT knowledge_{name.lower()}_id IF NOT EXISTS FOR (n:{name}) REQUIRE n.id IS UNIQUE"
        for name in KNOWLEDGE_COLUMNS
    ] + [
        f"CREATE INDEX knowledge_{name.lower()}_{field} IF NOT EXISTS FOR (n:{name}) ON (n.{field})"
        for name, columns in KNOWLEDGE_COLUMNS.items()
        for field in columns
        if field
        in {
            "workspace_id",
            "artifact_id",
            "revision_id",
            "generation_id",
            "predicate",
            "subject_id",
            "object_id",
            "recorded_from",
            "valid_from",
        }
    ]


def _data_transform(store):
    store._write_knowledge(DEFAULT_WORKSPACE)
    if store.knowledge_backend == "fake":
        for source in store.sources.values():
            source.setdefault("workspace_id", DEFAULT_WORKSPACE_ID)
            source.setdefault("active_generation_id", None)
            source.setdefault("generation_version", 0)
        return
    store.run(
        "MATCH (s:Source) SET s.workspace_id=coalesce(s.workspace_id,$workspace), s.generation_version=coalesce(s.generation_version,0), s.generation_lock=coalesce(s.generation_lock,0)",
        workspace=DEFAULT_WORKSPACE_ID,
    )


def migrate_store(store, *, fault_hook=None) -> None:
    # A readiness exception must not prevent this internal recovery path.
    with store._lock:
        store._migrating = True
        try:
            store._migration_blocked = True
            prior = check_compatibility(store)
            validate_existing_legacy_shape(store)
            if prior and prior["version"] == CURRENT_SCHEMA_VERSION and prior["state"] == "complete":
                validate_physical_schema(store)
                store._migration_blocked = False
                store._schema_checked = True
                return
            store._migration_blocked = True
            if store.knowledge_backend == "fake":
                with store.transaction():
                    _record_legacy_version(store)
                    _data_transform(store)
                    if fault_hook:
                        fault_hook("data")
                    _version(store, "complete", 0)
            elif store.knowledge_backend == "ladybug":
                with store.transaction():
                    store._ensure_legacy_schema()
                    store.run(
                        "CREATE NODE TABLE IF NOT EXISTS SchemaVersion(id STRING PRIMARY KEY, version INT64, checksum STRING, state STRING, step INT64)"
                    )
                    _record_legacy_version(store)
                    for index, statement in enumerate(schema_steps(store)):
                        store.run(statement)
                        if fault_hook:
                            fault_hook(f"schema:{index}")
                    validate_physical_schema(store)
                    _data_transform(store)
                    if fault_hook:
                        fault_hook("data")
                    _version(store, "complete", len(schema_steps(store)))
            else:
                # Neo4j does not permit schema + data updates in one transaction.
                # Journal exists before each schema step; repeat IF NOT EXISTS on recovery.
                store.run(
                    "CREATE CONSTRAINT knowledge_schema_version IF NOT EXISTS FOR (n:SchemaVersion) REQUIRE n.id IS UNIQUE"
                )
                _version(store, "pending", 0)
                store._ensure_legacy_schema()
                _record_legacy_version(store)
                for index, statement in enumerate(schema_steps(store)):
                    store.run(statement)
                    _version(store, "pending", index + 1)
                    if fault_hook:
                        fault_hook(f"schema:{index}")
                validate_physical_schema(store)
                with store.transaction():
                    _data_transform(store)
                    if fault_hook:
                        fault_hook("data")
                    _version(store, "complete", len(schema_steps(store)))
            store._migration_blocked = False
            store._schema_checked = True
        finally:
            store._migrating = False
