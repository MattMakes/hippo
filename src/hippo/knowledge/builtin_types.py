"""The built-in vocabulary: every value the closed `Literal`s and frozensets held before the registry.

The registry installs `BUILTIN_EXTENSION` on its first use, through the same checks an extension
meets, less the three that only make sense for an extension (plan D6). No module-level statement
here may look up the registry: it would re-enter that install.
"""

from types import MappingProxyType

from pydantic import BaseModel, ConfigDict

from .locators import (
    CommentLocator,
    DiffHunkLocator,
    FieldLocator,
    FileLinesLocator,
    PageLocator,
    SectionLocator,
    TableCellLocator,
)
from .predicates import BUILTIN_PREDICATES, OBJECT_KINDS
from .registry import (
    CUSTOM_FAMILY,
    SPEC_FAMILIES,
    EvidenceSourceDefinition,
    LocatorKindDefinition,
    ObjectKindDefinition,
    TypeExtension,
)


class BuiltinAttributes(BaseModel):
    """Open on purpose: the pre-kit lanes write freeform attribute dicts (plan D6)."""

    model_config = ConfigDict(frozen=True, extra="allow")
    name: str | None = None


def _kind(name, family, prefix, *key_template, scope=False) -> ObjectKindDefinition:
    return ObjectKindDefinition(
        name=name,
        family=family,
        key_template=key_template,
        key_prefix=prefix,
        attrs_model=BuiltinAttributes,
        label_template="{name}",
        scope_kind=scope,
    )


# Each key template names the positions of the canonical key today's identity helper, or today's
# only writer, builds; the workspace is never a part (plan D13).
EXTERNAL = ("provider_instance", "external_id")
CATALOG_ENTITY = ("catalog_instance", "reference")
DATABASE_OBJECT = ("instance", "environment", "catalog", "schema", "parts")
API = ("service", "protocol", "api_identity", "api_version")
BUILTIN_OBJECT_KINDS = (
    _kind("service", "service", "svc", *CATALOG_ENTITY, scope=True),
    _kind("api", "service", "api", *API),
    _kind("endpoint", "service", "ep", *API, "method", "path_template"),
    _kind("owner", "service", "owner", *EXTERNAL),
    _kind("team", "service", "team", "name", scope=True),
    _kind("person", "service", "eng", "email"),
    _kind("group", "service", "group", *EXTERNAL),
    _kind("user", "service", "user", *EXTERNAL),
    _kind("system", "service", "sys", *CATALOG_ENTITY, scope=True),
    _kind("domain", "service", "domain", *CATALOG_ENTITY, scope=True),
    _kind("resource", "service", "res", "repository", "dialect", "data_kind", "qualname"),
    _kind("repository", "code", "repo", "provider_instance", "repository_id"),
    _kind("file", "code", "file", "repository", "path"),
    _kind(
        "symbol", "code", "fn", "repository", "language", "path", "qualified_name", "symbol_kind", "signature"
    ),
    _kind("commit", "change", "commit", "repository", "sha"),
    _kind("database", "db", "db", "instance", "environment", "catalog"),
    _kind("schema", "db", "schema", "instance", "environment", "catalog", "schema"),
    _kind("table", "db", "tbl", *DATABASE_OBJECT),
    _kind("column", "db", "col", *DATABASE_OBJECT),
    _kind("view", "db", "view", *DATABASE_OBJECT),
    _kind("constraint", "db", "constraint", *DATABASE_OBJECT),
    _kind("index", "db", "index", *DATABASE_OBJECT),
    _kind("routine", "db", "proc", *DATABASE_OBJECT),
    _kind("requirement", "prose", "req", *EXTERNAL),
    _kind("criterion", "work", "criterion", *EXTERNAL),
    _kind("ticket", "work", "wi", "provider_instance", "issue_id"),
    _kind("review", "change", "pr", "provider_instance", "repository_id", "review_id"),
    _kind("decision", "prose", "decision", *EXTERNAL),
    _kind("document", "prose", "doc", "provider_instance", "document_id"),
    _kind("alias", "custom", "alias", "namespace", "alias_key"),
)
assert {kind.name for kind in BUILTIN_OBJECT_KINDS} == OBJECT_KINDS

# Design §4: the evidence class of a kit record from the specification's `family` and `source`. The
# third key part says where a `metadata` fact came from ("catalog": a catalog or tracker API;
# "declaration": a document, manifest or declaration in a file) and is None for every other source.
# The design's "any" family row is spelled once per family. Ruling R29 as amended by R40: a built-in
# source needs a row here and takes its class from it; an extension source registers its own family
# and class with its `EvidenceSourceDefinition`.
EVIDENCE_CLASS_DERIVATION = MappingProxyType(
    {
        ("deterministic", "parser", None): "syntax_observed",
        ("deterministic", "metadata", "catalog"): "catalog_observed",
        ("deterministic", "metadata", "declaration"): "declared",
        ("deterministic", "rule", None): "rule_derived",
        ("deterministic", "access_history", None): "catalog_observed",
        ("deterministic", "apm", None): "catalog_observed",
        ("deterministic", "postmortem", None): "discussion_claim",
        ("deterministic", "slack", None): "discussion_claim",
        ("probabilistic", "similarity", None): "similarity_inferred",
        ("probabilistic", "cooccurrence", None): "similarity_inferred",
        ("deterministic", "reviewed", None): "human_verified",
        ("probabilistic", "reviewed", None): "human_verified",
    }
)

BUILTIN_EXTENSION = TypeExtension(
    families=(*SPEC_FAMILIES, CUSTOM_FAMILY),
    evidence_sources=tuple(
        EvidenceSourceDefinition(name=name)
        for name in (
            "parser",
            "metadata",
            "rule",
            "similarity",
            "cooccurrence",
            "access_history",
            "apm",
            "postmortem",
            "slack",
            "reviewed",
        )
    ),
    artifact_kinds=(
        "file",
        "repository",
        "ticket",
        "comment",
        "attachment",
        "review",
        "schema_snapshot",
        "catalog_entity",
        "document",
        "manifest",
        "openapi",
        "history_event",
    ),
    connector_kinds=(
        "local",
        "git",
        "github",
        "gitlab",
        "jira_cloud",
        "jira_data_center",
        "tuleap",
        "backstage",
    ),
    locator_kinds=tuple(
        LocatorKindDefinition(name=model.model_fields["kind"].default, model=model)
        for model in (
            FileLinesLocator,
            SectionLocator,
            FieldLocator,
            CommentLocator,
            PageLocator,
            TableCellLocator,
            DiffHunkLocator,
        )
    ),
    object_kinds=BUILTIN_OBJECT_KINDS,
    predicates=BUILTIN_PREDICATES,
)
