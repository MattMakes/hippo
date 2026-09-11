"""Declared assertion endpoints and traversal rules; support is always required.

`both` permits inverse lookup, while the stored and rendered predicate retains its
subject/object orientation. This registry never infers evidence or grants access.
"""

from dataclasses import dataclass
from types import MappingProxyType

# Commit is a merge target, index/routine are schema objects, and system/domain/
# resource represent real catalog kinds. They must not be squeezed into prose entities.
OBJECT_KINDS = frozenset(
    {
        "service",
        "api",
        "endpoint",
        "owner",
        "team",
        "person",
        "group",
        "user",
        "system",
        "domain",
        "resource",
        "repository",
        "file",
        "symbol",
        "commit",
        "database",
        "schema",
        "table",
        "column",
        "view",
        "constraint",
        "index",
        "routine",
        "requirement",
        "criterion",
        "ticket",
        "review",
        "decision",
        "document",
        "alias",
    }
)


@dataclass(frozen=True)
class PredicateDefinition:
    subject_kinds: frozenset[str]
    object_kinds: frozenset[str]
    direction: str = "both"
    support_required: bool = True
    traversal_permitted: bool = True


def _rule(subjects: str, objects: str, *, traversal: bool = True) -> PredicateDefinition:
    return PredicateDefinition(
        frozenset(subjects.split()), frozenset(objects.split()), traversal_permitted=traversal
    )


ALL = " ".join(sorted(OBJECT_KINDS))
CATALOG = "service api system domain resource repository"
SCHEMA = "database schema table column view constraint index routine"
PREDICATES = MappingProxyType(
    {
        "PART_OF": _rule(CATALOG, "system domain service repository"),
        "OWNED_BY": _rule(CATALOG + " endpoint", "owner group user team person"),
        "PROVIDES_API": _rule("service", "api"),
        "CONSUMES_API": _rule("service", "api"),
        "DEPENDS_ON": _rule(CATALOG, CATALOG),
        "EXPOSES_ENDPOINT": _rule("service api", "endpoint"),
        "IMPLEMENTED_BY": _rule("service api endpoint requirement criterion", "symbol file repository"),
        "READS_TABLE": _rule("symbol routine", "table view"),
        "WRITES_TABLE": _rule("symbol routine", "table view"),
        "READS_COLUMN": _rule("symbol routine", "column"),
        "WRITES_COLUMN": _rule("symbol routine", "column"),
        "REFERENCES_OBJECT": _rule("symbol file routine", SCHEMA),
        "HAS_COLUMN": _rule("table view", "column"),
        "HAS_CONSTRAINT": _rule("table column", "constraint"),
        "FK_REFERENCES": _rule("constraint", "table"),
        "VIEW_READS": _rule("view", "table view column"),
        "DERIVES_FROM": _rule("column view", "column table view"),
        "RENAMED_TO": _rule(ALL, ALL),
        "HAS_CRITERION": _rule("requirement ticket", "criterion"),
        "TRACKS": _rule("ticket", "requirement criterion decision"),
        "BLOCKS": _rule("ticket requirement criterion", "ticket requirement criterion"),
        "DUPLICATE_OF": _rule("ticket requirement", "ticket requirement"),
        "MENTIONS": _rule("document ticket review decision requirement criterion", ALL, traversal=False),
        "ADDRESSES": _rule("review commit", "ticket requirement criterion"),
        "CHANGES": _rule("review commit", "file symbol endpoint " + SCHEMA),
        "MERGED_AS": _rule("review", "commit"),
        "SUPERSEDES": _rule(
            "decision requirement criterion document", "decision requirement criterion document"
        ),
        "CONTRADICTS": _rule(ALL, ALL, traversal=False),
        "SUPPORTS": _rule(ALL, ALL),
        "DECIDED_IN": _rule("decision requirement criterion", "ticket review document"),
        "ALIAS_OF": _rule("alias", ALL),
        "BOUND_TO": _rule(
            "symbol resource service endpoint " + SCHEMA, "symbol resource service endpoint " + SCHEMA
        ),
    }
)


def validate_endpoints(predicate: str, subject_kind: str, object_kind: str) -> None:
    definition = PREDICATES.get(predicate)
    if definition is None:
        raise ValueError("Unknown assertion predicate")
    if subject_kind not in definition.subject_kinds or object_kind not in definition.object_kinds:
        raise ValueError(f"Invalid endpoint kinds for {predicate}")
    if predicate in {"RENAMED_TO", "DUPLICATE_OF"} and subject_kind != object_kind:
        raise ValueError(f"{predicate} requires matching endpoint kinds")
