"""Declared assertion endpoints and traversal rules; support is always required.

`both` permits inverse lookup, while the stored and rendered predicate retains its
subject/object orientation. This registry never infers evidence or grants access.
`PREDICATES` reads the ontology registry, so a registered extension predicate appears in it;
an identity predicate declares no endpoint kinds and is read with `predicate_definition`.
"""

from collections.abc import Iterator, Mapping

from .registry import CUSTOM_FAMILY, SPEC_FAMILIES, PredicateDefinition, UnregisteredName, current_registry

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


ALL = " ".join(sorted(OBJECT_KINDS))
CATALOG = "service api system domain resource repository"
SCHEMA = "database schema table column view constraint index routine"
DECLARED = "metadata rule reviewed"
PARSED = "parser metadata rule reviewed"
DISCUSSED = "metadata reviewed"
MENTIONED = "parser metadata reviewed"
EVERY_FAMILY = " ".join((*SPEC_FAMILIES, CUSTOM_FAMILY))


def _rule(name, subjects, objects, owners, sources, verb, *, windowed=False, traversal=True, identity=False):
    return PredicateDefinition(
        name=name,
        subject_kinds=frozenset(subjects.split()),
        object_kinds=frozenset(objects.split()),
        owner_families=frozenset(owners.split()),
        identity=identity,
        canonical_direction="subject_to_object",
        family_default="deterministic",
        sources_allowed=frozenset(sources.split()),
        verb_phrase=verb,
        windowed=windowed,
        traversal_permitted=traversal,
    )


# Owner families follow spec §6's "across (owner)" column (ruling R19); endpoint sets and traversal
# flags are the pre-registry table's, unchanged. Verb phrases name no endpoint kind.
BUILTIN_PREDICATES = (
    _rule(
        "PART_OF",
        CATALOG,
        "system domain service repository",
        "service",
        DECLARED,
        "is part of",
        windowed=True,
    ),
    _rule(
        "OWNED_BY",
        CATALOG + " endpoint",
        "owner group user team person",
        "service code",
        DECLARED,
        "is owned by",
        windowed=True,
    ),
    _rule("PROVIDES_API", "service", "api", "service", DECLARED, "provides", windowed=True),
    _rule("CONSUMES_API", "service", "api", "service", DECLARED, "consumes", windowed=True),
    _rule("DEPENDS_ON", CATALOG, CATALOG, "service", DECLARED, "depends on", windowed=True),
    _rule("EXPOSES_ENDPOINT", "service api", "endpoint", "service code", PARSED, "exposes", windowed=True),
    _rule(
        "IMPLEMENTED_BY",
        "service api endpoint requirement criterion",
        "symbol file repository",
        "code",
        PARSED,
        "is implemented by",
    ),
    _rule("READS_TABLE", "symbol routine", "table view", "code db", PARSED, "reads"),
    _rule("WRITES_TABLE", "symbol routine", "table view", "code db", PARSED, "writes"),
    _rule("READS_COLUMN", "symbol routine", "column", "code db", PARSED, "reads"),
    _rule("WRITES_COLUMN", "symbol routine", "column", "code db", PARSED, "writes"),
    _rule("REFERENCES_OBJECT", "symbol file routine", SCHEMA, "code db", PARSED, "references"),
    _rule("HAS_COLUMN", "table view", "column", "db", PARSED, "has"),
    _rule("HAS_CONSTRAINT", "table column", "constraint", "db", PARSED, "has"),
    _rule("FK_REFERENCES", "constraint", "table", "db", PARSED, "references"),
    _rule("VIEW_READS", "view", "table view column", "db", PARSED, "reads"),
    _rule("DERIVES_FROM", "column view", "column table view", "db", PARSED, "derives from"),
    _rule("RENAMED_TO", ALL, ALL, "code change db", PARSED, "was renamed to"),
    _rule("HAS_CRITERION", "requirement ticket", "criterion", "work prose", DECLARED, "has"),
    _rule("TRACKS", "ticket", "requirement criterion decision", "work", DECLARED, "tracks", windowed=True),
    _rule(
        "BLOCKS",
        "ticket requirement criterion",
        "ticket requirement criterion",
        "work",
        DECLARED,
        "blocks",
        windowed=True,
    ),
    _rule("DUPLICATE_OF", "ticket requirement", "ticket requirement", "work", DECLARED, "duplicates"),
    _rule(
        "MENTIONS",
        "document ticket review decision requirement criterion",
        ALL,
        "prose work change",
        MENTIONED,
        "mentions",
        traversal=False,
    ),
    _rule("ADDRESSES", "review commit", "ticket requirement criterion", "change", DECLARED, "addresses"),
    _rule("CHANGES", "review commit", "file symbol endpoint " + SCHEMA, "change", PARSED, "changes"),
    _rule("MERGED_AS", "review", "commit", "change", DECLARED, "was merged as"),
    _rule(
        "SUPERSEDES",
        "decision requirement criterion document",
        "decision requirement criterion document",
        "prose",
        DISCUSSED,
        "supersedes",
    ),
    _rule("CONTRADICTS", ALL, ALL, "prose", DISCUSSED, "contradicts", traversal=False),
    _rule("SUPPORTS", ALL, ALL, "prose", DISCUSSED, "supports"),
    _rule(
        "DECIDED_IN",
        "decision requirement criterion",
        "ticket review document",
        "prose work change",
        DISCUSSED,
        "was decided in",
    ),
    _rule("ALIAS_OF", "alias", ALL, " ".join(SPEC_FAMILIES), DECLARED, "is an alias of"),
    _rule(
        "BOUND_TO",
        "symbol resource service endpoint " + SCHEMA,
        "symbol resource service endpoint " + SCHEMA,
        "code service db",
        PARSED,
        "is bound to",
    ),
    _rule(
        "SAME_OBJECT_AS",
        "",
        "",
        EVERY_FAMILY,
        "rule reviewed",
        "is the same object as",
        traversal=False,
        identity=True,
    ),
)


class _PredicateView(Mapping[str, PredicateDefinition]):
    """Every registered predicate that declares endpoint kinds: the built-ins, then extensions."""

    def __getitem__(self, name: str) -> PredicateDefinition:
        definition = current_registry().predicate(name)  # UnregisteredName is a KeyError
        if definition.identity:
            raise KeyError(name)
        return definition

    def __iter__(self) -> Iterator[str]:
        registry = current_registry()
        return iter(sorted(name for name in registry.predicates() if not registry.predicate(name).identity))

    def __contains__(self, name: object) -> bool:  # no KeyError path in per-arrow loops
        registry = current_registry()
        return (
            isinstance(name, str) and name in registry.predicates() and not registry.predicate(name).identity
        )

    def __len__(self) -> int:
        return sum(1 for _ in self)


PREDICATES: Mapping[str, PredicateDefinition] = _PredicateView()


def predicate_definition(name: str) -> PredicateDefinition:
    """Any registered predicate, identity predicates included."""
    try:
        return current_registry().predicate(name)
    except UnregisteredName:
        raise ValueError("Unknown assertion predicate") from None


def validate_endpoints(predicate: str, subject_kind: str, object_kind: str) -> None:
    definition = predicate_definition(predicate)
    if definition.identity:
        kinds = current_registry().object_kinds()
        if subject_kind not in kinds or object_kind not in kinds:
            raise ValueError(f"Invalid endpoint kinds for {predicate}")
        return
    if subject_kind not in definition.subject_kinds or object_kind not in definition.object_kinds:
        raise ValueError(f"Invalid endpoint kinds for {predicate}")
    if predicate in {"RENAMED_TO", "DUPLICATE_OF"} and subject_kind != object_kind:
        raise ValueError(f"{predicate} requires matching endpoint kinds")
