"""The ontology registry: built-in registrations, refusals at `register`, scopes and the fingerprint."""

import ast
import inspect
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, get_args

import pytest
from pydantic import BaseModel, ConfigDict

from hippo.knowledge import model as k
from hippo.knowledge.builtin_types import BUILTIN_EXTENSION, EVIDENCE_CLASS_DERIVATION, BuiltinAttributes
from hippo.knowledge.contract import Text
from hippo.knowledge.identity import (
    canonical_json,
    database_object_key,
    endpoint_key,
    repository_key,
    review_key,
    service_key,
    sql_identifier,
    symbol_key,
    text_hash,
)
from hippo.knowledge.lifecycle import generation_for_inputs
from hippo.knowledge.locators import LocatorBase
from hippo.knowledge.predicates import OBJECT_KINDS, PREDICATES
from hippo.knowledge.registry import (
    REGISTRY,
    EvidenceSourceDefinition,
    FactTemplate,
    LocatorKindDefinition,
    ObjectKindDefinition,
    PredicateDefinition,
    RegistrationError,
    Registry,
    TypeExtension,
    UnregisteredName,
    connector_configuration,
    current_registry,
    extension_scope,
    use_registry,
)

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


@pytest.fixture
def scoped():
    with extension_scope() as registry:
        yield registry


class IncidentAttributes(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    title: str
    severity: str


class IncidentEventLocator(LocatorBase):
    kind: Literal["incident_event"] = "incident_event"
    event_id: Text


SEVERITY = FactTemplate(
    name="severity", version="1", consumes=("severity",), text="{label} has severity {severity}"
)


def incident_kind(**changes) -> ObjectKindDefinition:
    kind = ObjectKindDefinition(
        name="incident_fixture",
        family="incident",
        key_template=("tool", "incident_id"),
        key_prefix="incx",
        attrs_model=IncidentAttributes,
        label_template="{title}",
        fact_templates=(SEVERITY,),
    )
    return kind.replace(**changes)


def affects_predicate(**changes) -> PredicateDefinition:
    predicate = PredicateDefinition(
        name="AFFECTS_FIXTURE",
        subject_kinds=frozenset({"incident_fixture"}),
        object_kinds=frozenset({"service"}),
        owner_families=frozenset({"incident"}),
        canonical_direction="subject_to_object",
        family_default="deterministic",
        sources_allowed=frozenset({"pager_feed"}),
        verb_phrase="affects",
    )
    return predicate.replace(**changes)


# Ruling R40: an extension evidence source registers with its family and its evidence class.
PAGER_FEED = EvidenceSourceDefinition(
    name="pager_feed", family="deterministic", evidence_class="catalog_observed"
)


def incident_extension(**changes) -> TypeExtension:
    return TypeExtension(
        object_kinds=(incident_kind(),),
        artifact_kinds=("incident_export",),
        locator_kinds=(LocatorKindDefinition(name="incident_event", model=IncidentEventLocator),),
        connector_kinds=("incident_ndjson",),
        evidence_sources=(PAGER_FEED,),
        predicates=(affects_predicate(),),
    ).replace(**changes)


class OpenIncidentAttributes(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")
    title: str
    severity: str


class LabelledIncidentAttributes(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    title: str
    severity: str
    label: str


def _register(**changes):
    def action(registry):
        registry.register(incident_extension(**changes))

    return action


def _kind(**changes):
    return _register(object_kinds=(incident_kind(**changes),))


def _predicate(**changes):
    return _register(predicates=(affects_predicate(**changes),))


def _frozen(registry):
    registry.freeze()
    registry.register(incident_extension())


def _twice(registry):
    registry.register(incident_extension())
    registry.register(incident_extension())


def _declared(*families):
    def action(registry):
        registry.register(incident_extension(), declared_families=families)

    return action


FIXTURE = "object kind 'incident_fixture'"
AFFECTS = "predicate 'AFFECTS_FIXTURE'"
PAGER = "evidence source 'pager_feed'"
REFUSALS = [
    pytest.param("frozen", "Registry is frozen; register extensions before freeze()", _frozen, id="frozen"),
    pytest.param(
        "shadows_builtin",
        "object kind 'File' shadows the built-in 'file'",
        _kind(name="File"),
        id="shadows_builtin",
    ),
    pytest.param(
        "duplicate_name",
        f"{PAGER} repeats the registered name 'pager_feed'",
        _twice,
        id="duplicate_name",
    ),
    pytest.param(
        "missing_locator_model",
        "locator kind 'incident_event' has no model",
        _register(locator_kinds=(LocatorKindDefinition(name="incident_event"),)),
        id="missing_locator_model",
    ),
    pytest.param(
        "not_a_source_locator",
        "locator kind 'incident_event' model is not a SourceLocator whose kind defaults to 'incident_event'",
        _register(locator_kinds=(LocatorKindDefinition(name="incident_event", model=IncidentAttributes),)),
        id="not_a_source_locator",
    ),
    pytest.param(
        "unknown_family",
        f"{FIXTURE} names unknown family 'pager'",
        _kind(family="pager"),
        id="unknown_family-kind",
    ),
    pytest.param(
        "unknown_family",
        f"{AFFECTS} names unknown owner family 'pager'",
        _predicate(owner_families=frozenset({"pager"})),
        id="unknown_family-owner",
    ),
    pytest.param(
        "empty_key_template",
        f"{FIXTURE} has an empty key template",
        _kind(key_template=()),
        id="empty_key_template",
    ),
    pytest.param(
        "repeated_key_part",
        f"{FIXTURE} repeats key part 'tool'",
        _kind(key_template=("tool", "incident_id", "tool")),
        id="repeated_key_part",
    ),
    pytest.param(
        "extra_attributes_allowed",
        f"{FIXTURE} attribute model OpenIncidentAttributes must forbid extra fields",
        _kind(attrs_model=OpenIncidentAttributes),
        id="extra_attributes_allowed",
    ),
    pytest.param(
        "reserved_attribute",
        f"{FIXTURE} attribute model declares the reserved template field 'label'",
        _kind(attrs_model=LabelledIncidentAttributes),
        id="reserved_attribute",
    ),
    pytest.param(
        "undeclared_template_field",
        f"label template of {FIXTURE} references undeclared attribute 'name'",
        _kind(label_template="{name}"),
        id="undeclared_template_field-label",
    ),
    pytest.param(
        "undeclared_template_field",
        f"fact template 'severity' of {FIXTURE} references undeclared attribute 'impact'",
        _kind(fact_templates=(SEVERITY.replace(consumes=("impact",)),)),
        id="undeclared_template_field-consumes",
    ),
    pytest.param(
        "undeclared_template_field",
        f"fact template 'severity' of {FIXTURE} references undeclared attribute 'impact'",
        _kind(fact_templates=(SEVERITY.replace(text="{label} has impact {impact}"),)),
        id="undeclared_template_field-text",
    ),
    pytest.param(
        "undeclared_template_field",
        f"label template of {FIXTURE} references undeclared attribute ''",
        _kind(label_template="{} {title}"),
        id="undeclared_template_field-positional",
    ),
    pytest.param(
        "malformed_template",
        f"label template of {FIXTURE} is not a valid format string",
        _kind(label_template="{title"),
        id="malformed_template",
    ),
    pytest.param(
        "repeated_template_attribute",
        f"fact template 'severity' of {FIXTURE} repeats attribute 'severity'",
        _kind(fact_templates=(SEVERITY.replace(consumes=("severity", "severity")),)),
        id="repeated_template_attribute",
    ),
    pytest.param(
        "duplicate_template",
        f"fact template 'severity' of {FIXTURE} repeats the template name 'severity'",
        _kind(fact_templates=(SEVERITY, SEVERITY.replace(version="2"))),
        id="duplicate_template",
    ),
    pytest.param(
        "duplicate_template",
        f"fact template 'Severity' of {FIXTURE} repeats the template name 'severity'",
        _kind(fact_templates=(SEVERITY, SEVERITY.replace(name="Severity"))),
        id="duplicate_template-case",
    ),
    pytest.param(
        "identity_predicate",
        f"{AFFECTS} is an identity predicate; identity predicates are built-in",
        _predicate(identity=True),
        id="identity_predicate",
    ),
    pytest.param(
        "empty_endpoint_kinds",
        f"{AFFECTS} declares no subject kinds",
        _predicate(subject_kinds=frozenset()),
        id="empty_endpoint_kinds-subject",
    ),
    pytest.param(
        "empty_endpoint_kinds",
        f"{AFFECTS} declares no object kinds",
        _predicate(object_kinds=frozenset()),
        id="empty_endpoint_kinds-object",
    ),
    pytest.param(
        "unregistered_endpoint_kind",
        f"{AFFECTS} names unregistered object kind 'pager_duty'",
        _predicate(object_kinds=frozenset({"pager_duty"})),
        id="unregistered_endpoint_kind",
    ),
    pytest.param(
        "empty_owner_families",
        f"{AFFECTS} declares no owner families",
        _predicate(owner_families=frozenset()),
        id="empty_owner_families",
    ),
    pytest.param(
        "undeclared_owner_family",
        f"{AFFECTS}: none of its owner families ['work'] is declared by the registering connector ['incident']",
        _predicate(owner_families=frozenset({"work"})),
        id="undeclared_owner_family-extension",
    ),
    pytest.param(
        "undeclared_owner_family",
        f"{AFFECTS}: none of its owner families ['incident'] is declared by the registering connector ['prose']",
        _declared("prose"),
        id="undeclared_owner_family-declared",
    ),
    pytest.param(
        "unregistered_evidence_source",
        f"{AFFECTS} allows unregistered evidence source 'pager_pull'",
        _predicate(sources_allowed=frozenset({"pager_pull"})),
        id="unregistered_evidence_source",
    ),
    pytest.param(
        "missing_evidence_family",
        f"{PAGER} declares no family",
        _register(evidence_sources=(PAGER_FEED.replace(family=None),)),
        id="missing_evidence_family",
    ),
    pytest.param(
        "missing_evidence_class",
        f"{PAGER} declares no evidence class",
        _register(evidence_sources=(PAGER_FEED.replace(evidence_class=None),)),
        id="missing_evidence_class",
    ),
    pytest.param(
        "excluded_evidence_class",
        f"{PAGER} declares evidence class 'model_inferred', which no extension evidence source may declare",
        _register(evidence_sources=(PAGER_FEED.replace(evidence_class="model_inferred"),)),
        id="excluded_evidence_class-model_inferred",
    ),
    pytest.param(
        "excluded_evidence_class",
        f"{PAGER} declares evidence class 'human_verified', which no extension evidence source may declare",
        _register(evidence_sources=(PAGER_FEED.replace(evidence_class="human_verified"),)),
        id="excluded_evidence_class-human_verified",
    ),
]

ARTIFACT_KINDS = {
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
}
CONNECTOR_KINDS = {
    "local",
    "git",
    "github",
    "gitlab",
    "jira_cloud",
    "jira_data_center",
    "tuleap",
    "backstage",
}
FAMILIES = {"prose", "code", "change", "db", "work", "service", "incident", "custom"}
EVIDENCE_SOURCES = {
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
}


def _sections(registry: Registry) -> dict:
    return {
        "families": registry.families(),
        "evidence_sources": registry.evidence_sources(),
        "artifact_kinds": registry.artifact_kinds(),
        "connector_kinds": registry.connector_kinds(),
        "locator_kinds": registry.locator_kinds(),
        "object_kinds": registry.object_kinds(),
        "predicates": registry.predicates(),
    }


def _fingerprint_with(**changes) -> str:
    with extension_scope() as registry:
        registry.register(incident_extension(**changes))
        return registry.fingerprint()


def test_builtins_register_every_value_the_closed_vocabularies_held():
    registry = Registry.with_builtins()
    assert registry.object_kinds() == set(get_args(k.ObjectKind)) == OBJECT_KINDS
    assert registry.artifact_kinds() == ARTIFACT_KINDS
    assert registry.connector_kinds() == CONNECTOR_KINDS
    locators = get_args(get_args(k.SourceLocator)[0])
    assert len(locators) == 7
    assert registry.locator_kinds() == {model.model_fields["kind"].default for model in locators}
    assert all(registry.locator(model.model_fields["kind"].default) is model for model in locators)
    assert registry.families() == FAMILIES
    assert registry.evidence_sources() == EVIDENCE_SOURCES
    assert registry.predicates() == set(PREDICATES) | {"SAME_OBJECT_AS"}
    assert len(registry.predicates()) == 33


def test_builtin_endpoint_rules_are_the_legacy_table():
    rules = {
        name: [
            sorted(definition.subject_kinds),
            sorted(definition.object_kinds),
            definition.direction,
            definition.support_required,
            definition.traversal_permitted,
        ]
        for name, definition in PREDICATES.items()
    }
    assert (
        text_hash(canonical_json(rules)) == "050f71a4c3ef7af8e0107067d8e601cc08832f4daaea01c97f885f2bf148803e"
    )


def test_builtin_predicates_carry_owner_families_sources_and_verb_phrases():
    registry = Registry.with_builtins()
    for name in registry.predicates():
        definition = registry.predicate(name)
        assert definition.name == name
        assert definition.owner_families and definition.owner_families <= registry.families()
        assert definition.sources_allowed and definition.sources_allowed <= registry.evidence_sources()
        assert definition.verb_phrase.strip()
        assert definition.canonical_direction == "subject_to_object"
        assert definition.family_default == "deterministic"
        assert definition.support_required and definition.inverse_lookup
    assert not registry.predicate("MENTIONS").traversal_permitted
    assert not registry.predicate("CONTRADICTS").traversal_permitted
    same = registry.predicate("SAME_OBJECT_AS")
    assert same.identity and not same.traversal_permitted
    assert same.subject_kinds == same.object_kinds == frozenset()
    assert same.owner_families == FAMILIES
    assert same.sources_allowed == {"rule"}  # F2: reviewed left every built-in


def test_alias_of_is_owned_by_every_family_including_custom():
    registry = Registry.with_builtins()
    assert registry.predicate("ALIAS_OF").owner_families == FAMILIES
    assert registry.predicate("ALIAS_OF").subject_kinds == {"alias"}


def _key_positions(helper, *args, **kwargs) -> tuple[str | None, ...]:
    """The parameter of `helper` whose argument each position of the key it builds carries."""
    arguments = inspect.signature(helper).bind(*args, **kwargs).arguments

    def spelled(value):  # the text a normalized key part keeps of its argument
        if isinstance(value, list | tuple):
            value = value[0]
        return getattr(value, "lookup", value)

    return tuple(
        next((name for name, value in arguments.items() if spelled(value) in canonical_json(part)), None)
        for part in helper(*args, **kwargs)
    )


def test_builtin_key_templates_match_the_identity_helpers():
    registry = Registry.with_builtins()
    # Two parts are named for the kit rather than for the helper parameter they carry (plan D13).
    parameter = {("repository", "repository_id"): "provider_repository_id", ("symbol", "symbol_kind"): "kind"}
    instance = "https://instance.example"
    positions = {
        "repository": _key_positions(repository_key, instance, "repository-id"),
        "review": _key_positions(review_key, instance, "repository-id", "review-id"),
        "service": _key_positions(service_key, instance, "component:default/billing"),
        "endpoint": _key_positions(
            endpoint_key, "service-x", "protocol-x", "version-x", "GET", "/path-x", api_identity="identity-x"
        ),
        "symbol": _key_positions(
            symbol_key, "repository-x", "language-x", "path-x.py", "qualified-x", "signature-x", kind="kind-x"
        ),
        "table": _key_positions(
            database_object_key,
            "instance-x",
            "environment-x",
            "catalog-x",
            "schema-x",
            [sql_identifier("parts-x", dialect="postgres")],
        ),
    }
    for kind, carried in positions.items():
        template = registry.object_kind(kind).key_template
        assert tuple(parameter.get((kind, part), part) for part in template) == carried, kind


BUILTIN_KINDS = {
    "service": ("service", "svc", ("catalog_instance", "reference"), True),
    "api": ("service", "api", ("service", "protocol", "api_identity", "api_version"), False),
    "endpoint": (
        "service",
        "ep",
        ("service", "protocol", "api_identity", "api_version", "method", "path_template"),
        False,
    ),
    "owner": ("service", "owner", ("provider_instance", "external_id"), False),
    "team": ("service", "team", ("name",), True),
    "person": ("service", "eng", ("email",), False),
    "group": ("service", "group", ("provider_instance", "external_id"), False),
    "user": ("service", "user", ("provider_instance", "external_id"), False),
    "system": ("service", "sys", ("catalog_instance", "reference"), True),
    "domain": ("service", "domain", ("catalog_instance", "reference"), True),
    "resource": ("service", "res", ("repository", "dialect", "data_kind", "qualname"), False),
    "repository": ("code", "repo", ("provider_instance", "repository_id"), False),
    "file": ("code", "file", ("repository", "path"), False),
    "symbol": (
        "code",
        "fn",
        ("repository", "language", "path", "qualified_name", "symbol_kind", "signature"),
        False,
    ),
    "commit": ("change", "commit", ("repository", "sha"), False),
    "database": ("db", "db", ("instance", "environment", "catalog"), False),
    "schema": ("db", "schema", ("instance", "environment", "catalog", "schema"), False),
    "table": ("db", "tbl", ("instance", "environment", "catalog", "schema", "parts"), False),
    "column": ("db", "col", ("instance", "environment", "catalog", "schema", "parts"), False),
    "view": ("db", "view", ("instance", "environment", "catalog", "schema", "parts"), False),
    "constraint": ("db", "constraint", ("instance", "environment", "catalog", "schema", "parts"), False),
    "index": ("db", "index", ("instance", "environment", "catalog", "schema", "parts"), False),
    "routine": ("db", "proc", ("instance", "environment", "catalog", "schema", "parts"), False),
    "requirement": ("prose", "req", ("provider_instance", "external_id"), False),
    "criterion": ("work", "criterion", ("provider_instance", "external_id"), False),
    "ticket": ("work", "wi", ("provider_instance", "issue_id"), False),
    "review": ("change", "pr", ("provider_instance", "repository_id", "review_id"), False),
    "decision": ("prose", "decision", ("provider_instance", "external_id"), False),
    "document": ("prose", "doc", ("provider_instance", "document_id"), False),
    "alias": ("custom", "alias", ("namespace", "alias_key"), False),
}


def test_builtin_object_kinds_carry_the_planned_family_prefix_and_key_template():
    registry = Registry.with_builtins()
    assert set(BUILTIN_KINDS) == registry.object_kinds()
    for name, (family, prefix, template, scope) in BUILTIN_KINDS.items():
        definition = registry.object_kind(name)
        assert (definition.family, definition.key_prefix, definition.key_template, definition.scope_kind) == (
            family,
            prefix,
            template,
            scope,
        ), name
        assert definition.attrs_model is BuiltinAttributes
        assert definition.label_template == "{name}" and definition.fact_templates == ()


def test_builtins_are_exempt_from_exactly_three_extension_rules(scoped):
    open_kind = incident_kind(
        name="story_fixture",
        family="work",
        attrs_model=BuiltinAttributes,
        label_template="{name}",
        fact_templates=(),
    )
    with pytest.raises(RegistrationError) as refused:
        scoped.register(TypeExtension(object_kinds=(open_kind,)))
    assert refused.value.reason == "extra_attributes_allowed"
    same = scoped.predicate("SAME_OBJECT_AS")
    with pytest.raises(RegistrationError) as refused:
        scoped.register(TypeExtension(predicates=(same.replace(name="ALSO_SAME_OBJECT_AS"),)))
    assert refused.value.reason == "identity_predicate"
    # PROVIDES_API is owned by the service family, which this extension never declares.
    provides = scoped.predicate("PROVIDES_API")
    with pytest.raises(RegistrationError) as refused:
        scoped.register(TypeExtension(predicates=(provides.replace(name="ALSO_PROVIDES_API"),)))
    assert refused.value.reason == "undeclared_owner_family"
    fresh = Registry.with_builtins()
    assert fresh.object_kind("file").attrs_model is BuiltinAttributes
    assert fresh.predicate("SAME_OBJECT_AS").identity
    assert fresh.predicate("PROVIDES_API").owner_families == {"service"}


@pytest.mark.parametrize(("reason", "message", "action"), REFUSALS)
def test_register_refuses(scoped, reason, message, action):
    with pytest.raises(RegistrationError) as refused:
        action(scoped)
    assert isinstance(refused.value, ValueError)
    assert refused.value.reason == reason
    assert str(refused.value) == message


def test_a_refused_extension_registers_nothing(scoped):
    before = (scoped.fingerprint(), _sections(scoped))
    late = affects_predicate(name="ALSO_AFFECTS_FIXTURE", sources_allowed=frozenset({"pager_pull"}))
    with pytest.raises(RegistrationError) as refused:
        scoped.register(incident_extension(predicates=(affects_predicate(), late)))
    assert refused.value.reason == "unregistered_evidence_source"
    assert (scoped.fingerprint(), _sections(scoped)) == before
    assert "incident_fixture" not in scoped.object_kinds()


def test_a_case_variant_of_a_registered_name_is_refused(scoped):
    def story(name):
        return incident_kind(name=name, family="work", fact_templates=())

    scoped.register(TypeExtension(object_kinds=(story("story"),)))
    with pytest.raises(RegistrationError) as refused:
        scoped.register(TypeExtension(object_kinds=(story("STORY"),)))
    assert (refused.value.reason, str(refused.value)) == (
        "duplicate_name",
        "object kind 'STORY' repeats the registered name 'story'",
    )
    with pytest.raises(RegistrationError) as refused:
        scoped.register(TypeExtension(object_kinds=(story("epic"), story("Epic"))))
    assert (refused.value.reason, str(refused.value)) == (
        "duplicate_name",
        "object kind 'Epic' repeats the registered name 'epic'",
    )
    with pytest.raises(RegistrationError) as refused:
        scoped.register(TypeExtension(object_kinds=(story("Table"),)))
    assert (refused.value.reason, str(refused.value)) == (
        "shadows_builtin",
        "object kind 'Table' shadows the built-in 'table'",
    )
    with pytest.raises(UnregisteredName):
        scoped.object_kind("STORY")


def test_owner_families_are_checked_against_the_extension_or_the_declared_families():
    with extension_scope() as registry:
        registry.register(incident_extension())
        assert "AFFECTS_FIXTURE" in registry.predicates()
    with extension_scope() as registry:
        with pytest.raises(RegistrationError) as refused:
            registry.register(incident_extension(), declared_families=("work",))
        assert refused.value.reason == "undeclared_owner_family"
        registry.register(incident_extension(), declared_families=("work", "incident"))
        assert "AFFECTS_FIXTURE" in registry.predicates()


def test_freeze_refuses_registration_and_the_scope_restores_the_frozen_flag():
    fresh = Registry.with_builtins()
    with use_registry(fresh):
        assert not fresh.frozen
        fresh.freeze()
        fresh.freeze()
        assert fresh.frozen
        with pytest.raises(RegistrationError) as refused:
            fresh.register(incident_extension())
        assert refused.value.reason == "frozen"
        with extension_scope() as registry:
            assert registry is fresh and not fresh.frozen
            fresh.register(incident_extension())
            assert "incident_fixture" in fresh.object_kinds()
        assert fresh.frozen
        assert "incident_fixture" not in fresh.object_kinds()


def test_extension_scope_restores_the_registry_byte_for_byte():
    before = (REGISTRY.fingerprint(), REGISTRY.frozen, _sections(REGISTRY))
    with extension_scope() as registry:
        assert registry is REGISTRY and current_registry() is REGISTRY
        REGISTRY.register(incident_extension())
        assert REGISTRY.object_kind("incident_fixture").family == "incident"
    assert (REGISTRY.fingerprint(), REGISTRY.frozen, _sections(REGISTRY)) == before
    with pytest.raises(RuntimeError, match="body failed"):
        with extension_scope():
            REGISTRY.register(incident_extension())
            raise RuntimeError("body failed")
    assert (REGISTRY.fingerprint(), REGISTRY.frozen, _sections(REGISTRY)) == before


@pytest.mark.parametrize(
    ("lookup", "label"),
    [
        (lambda registry: registry.object_kind("pager"), "object kind"),
        (lambda registry: registry.predicate("pager"), "predicate"),
        (lambda registry: registry.locator("pager"), "locator kind"),
        (lambda registry: registry.locator_kind("pager"), "locator kind"),
        (lambda registry: registry.artifact_kind("pager"), "artifact kind"),
        (lambda registry: registry.connector_kind("pager"), "connector kind"),
        (lambda registry: registry.evidence_source("pager"), "evidence source"),
        (lambda registry: registry.evidence_source_definition("pager"), "evidence source"),
        (lambda registry: registry.declared_template_versions(["pager"]), "object kind"),
    ],
    ids=[
        "object_kind",
        "predicate",
        "locator",
        "locator_kind",
        "artifact_kind",
        "connector_kind",
        "evidence_source",
        "evidence_source_definition",
        "declared_template_versions",
    ],
)
def test_lookups_of_unregistered_names_raise_unregistered_name(lookup, label):
    with pytest.raises(UnregisteredName) as missing:
        lookup(REGISTRY)
    assert isinstance(missing.value, KeyError)
    assert str(missing.value) == f"Unknown {label}: 'pager'"


def test_lookups_match_names_exactly():
    assert REGISTRY.object_kind("file").name == "file"
    for lookup in (REGISTRY.object_kind, REGISTRY.artifact_kind, REGISTRY.connector_kind):
        with pytest.raises(UnregisteredName):
            lookup("File")


def test_fingerprint_is_independent_of_registration_order():
    def work_kind(name):
        return incident_kind(name=name, family="work", key_prefix=name[:5], fact_templates=())

    story, epic = work_kind("story_fixture"), work_kind("epic_fixture")
    with extension_scope() as registry:
        registry.register(TypeExtension(object_kinds=(story, epic)))
        together = registry.fingerprint()
    with extension_scope() as registry:
        registry.register(TypeExtension(object_kinds=(epic,)))
        registry.register(TypeExtension(object_kinds=(story,)))
        apart = registry.fingerprint()
    assert together == apart
    assert together != REGISTRY.fingerprint()
    assert len(together) == 64 and int(together, 16) >= 0


class DocumentedIncidentAttributes(BaseModel):
    """The incident's attributes, described for developers; the description is not vocabulary."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    title: str
    severity: str


class RenamedIncidentAttributes(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    severity: str


def test_fingerprint_ignores_model_titles_and_descriptions_but_not_field_names():
    def with_attributes(model):
        return _fingerprint_with(
            object_kinds=(incident_kind(attrs_model=model, label_template="{severity}"),)
        )

    base = with_attributes(IncidentAttributes)
    assert with_attributes(DocumentedIncidentAttributes) == base
    assert with_attributes(RenamedIncidentAttributes) != base


def test_fingerprint_covers_label_templates_and_verb_phrases():
    base = _fingerprint_with()
    assert _fingerprint_with() == base
    assert _fingerprint_with(object_kinds=(incident_kind(label_template="{title} ({severity})"),)) != base
    assert _fingerprint_with(predicates=(affects_predicate(verb_phrase="disrupts"),)) != base


def test_fingerprint_covers_evidence_source_families_and_classes():
    base = _fingerprint_with()
    assert _fingerprint_with(evidence_sources=(PAGER_FEED.replace(evidence_class="declared"),)) != base
    probabilistic = PAGER_FEED.replace(family="probabilistic", evidence_class="similarity_inferred")
    assert _fingerprint_with(evidence_sources=(probabilistic,)) != base


def _declared_configuration(template: FactTemplate) -> tuple[str, dict]:
    with extension_scope() as registry:
        registry.register(incident_extension(object_kinds=(incident_kind(fact_templates=(template,)),)))
        configuration = connector_configuration(
            name="incident_ndjson",
            version="1",
            templates=current_registry().declared_template_versions(["incident_fixture"]),
            parsers=[],
        )
        return registry.fingerprint(), configuration


def _generation(configuration: dict) -> k.Generation:
    return generation_for_inputs(
        (),
        workspace_id="w",
        source_id="source-incidents",
        parent_id=None,
        parser_version="parser-1",
        linker_version="linker-1",
        embedding_profile="profile-1",
        configuration=configuration,
        created_at=NOW,
    )


def test_a_changed_fact_template_changes_the_fingerprint_and_the_declaring_configuration():
    first_fingerprint, first_configuration = _declared_configuration(SEVERITY)
    second_fingerprint, second_configuration = _declared_configuration(
        SEVERITY.replace(version="2", text="{label} is a {severity} incident")
    )
    assert first_fingerprint != second_fingerprint
    assert first_configuration != second_configuration
    first, second = _generation(first_configuration), _generation(second_configuration)
    assert first.id != second.id
    assert first.manifest_hash != second.manifest_hash


def test_a_template_text_change_without_a_version_bump_changes_only_the_fingerprint():
    first_fingerprint, first_configuration = _declared_configuration(SEVERITY)
    second_fingerprint, second_configuration = _declared_configuration(
        SEVERITY.replace(text="{label} is a {severity} incident")
    )
    assert first_fingerprint != second_fingerprint
    assert first_configuration == second_configuration
    assert _generation(first_configuration) == _generation(second_configuration)


def test_use_registry_checks_records_against_the_installed_registry_only():
    before = REGISTRY.fingerprint()
    fresh = Registry.with_builtins()
    fresh.register(incident_extension())
    fresh.freeze()
    incident = k.KnowledgeObject(
        workspace_id="w", kind="incident_fixture", canonical_key='["pagerduty","P1"]'
    )
    with use_registry(fresh) as installed:
        assert installed is fresh and current_registry() is fresh
        assert current_registry().check_record(incident) is None
    assert current_registry() is REGISTRY
    with pytest.raises(ValueError, match="Unknown object kind"):
        current_registry().check_record(incident)
    with pytest.raises(RuntimeError, match="body failed"):
        with use_registry(fresh):
            raise RuntimeError("body failed")
    assert current_registry() is REGISTRY
    assert REGISTRY.fingerprint() == before
    assert Registry.with_builtins().fingerprint() == REGISTRY.fingerprint()


KNOWLEDGE = Path(k.__file__).parent
ALLOWED_KNOWLEDGE_IMPORTS = {
    f"hippo.knowledge.{name}" for name in ("contract", "identity", "locators", "registry", "predicates")
}


def _imports(module: str) -> list[tuple[str, bool]]:
    """Every imported module of `hippo.knowledge.<module>`, with whether it is imported inside a function."""
    found = []

    def visit(node, in_function):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Import):
                found.extend((alias.name, in_function) for alias in child.names)
            elif isinstance(child, ast.ImportFrom):
                if child.level == 0:
                    found.append((child.module, in_function))
                elif child.module is None:
                    found.extend((f"hippo.knowledge.{alias.name}", in_function) for alias in child.names)
                else:
                    assert child.level == 1, f"{module} imports above hippo.knowledge"
                    found.append((f"hippo.knowledge.{child.module}", in_function))
            visit(child, in_function or isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef))

    visit(ast.parse((KNOWLEDGE / f"{module}.py").read_text(encoding="utf-8")), False)
    return found


def test_registry_modules_import_nothing_outside_the_knowledge_leaf_modules():
    for module in ("contract", "locators", "registry", "builtin_types", "predicates"):
        for name, in_function in _imports(module):
            root = name.split(".")[0]
            if root in sys.stdlib_module_names or root in {"__future__", "pydantic"}:
                continue
            if module == "registry" and name == "hippo.knowledge.builtin_types":
                assert in_function, "registry imports builtin_types only inside a function"
                continue
            assert name in ALLOWED_KNOWLEDGE_IMPORTS, f"{module} imports {name}"


@pytest.mark.parametrize(
    "module", ["registry", "predicates", "builtin_types", "contract", "locators", "model"]
)
def test_each_knowledge_module_imports_first_in_a_fresh_interpreter(module):
    program = (
        f"import hippo.knowledge.{module}; from hippo.knowledge.registry import REGISTRY; "
        "assert 'file' in REGISTRY.object_kinds()"
    )
    result = subprocess.run(
        [sys.executable, "-W", "error", "-c", program],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]


def test_connector_configuration_is_canonical_and_reads_declared_template_versions(scoped):
    title = FactTemplate(name="title", version="v3", consumes=("title",), text="{label} is titled {title}")
    scoped.register(incident_extension(object_kinds=(incident_kind(fact_templates=(title, SEVERITY)),)))
    versions = scoped.declared_template_versions(["incident_fixture"])
    assert versions == {"incident_fixture.severity": "1", "incident_fixture.title": "v3"}
    assert list(versions) == sorted(versions)
    with pytest.raises(UnregisteredName):
        scoped.declared_template_versions(["pager"])
    first = connector_configuration(
        name="incident_ndjson", version="1", templates={"b.t": "1", "a.t": "2"}, parsers=["zeta@1", "alpha@2"]
    )
    second = connector_configuration(
        name="incident_ndjson", version="1", templates={"a.t": "2", "b.t": "1"}, parsers=("alpha@2", "zeta@1")
    )
    assert canonical_json(first) == canonical_json(second)
    assert first == {
        "connector": {
            "name": "incident_ndjson",
            "version": "1",
            "parsers": ["alpha@2", "zeta@1"],
            "templates": {"a.t": "2", "b.t": "1"},
        }
    }
    assert list(first) == ["connector"]
    assert "fingerprint" not in canonical_json(first)
    assert scoped.fingerprint() not in canonical_json(first)


def test_evidence_class_derivation_table_is_the_design_table():
    assert dict(EVIDENCE_CLASS_DERIVATION) == {
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
    assert {
        source for _, source, _ in EVIDENCE_CLASS_DERIVATION
    } == Registry.with_builtins().evidence_sources()
    assert "model_inferred" not in EVIDENCE_CLASS_DERIVATION.values()


def test_an_extension_evidence_source_registers_with_its_family_and_class(scoped):
    scoped.register(incident_extension())
    assert scoped.evidence_source("pager_feed") == "pager_feed"
    assert "pager_feed" in scoped.evidence_sources()
    assert scoped.predicate("AFFECTS_FIXTURE").sources_allowed == {"pager_feed"}
    assert "pager_feed" not in {source for _, source, _ in EVIDENCE_CLASS_DERIVATION}


# Ruling R62: S2b's binder checks emitted (family, source) pairs against the registered definition,
# so the accessor returns it whole rather than deriving a class the built-ins do not carry.
def test_the_definition_of_an_extension_evidence_source_carries_its_family_and_class(scoped):
    scoped.register(incident_extension())
    assert scoped.evidence_source_definition("pager_feed") == PAGER_FEED
    assert (PAGER_FEED.family, PAGER_FEED.evidence_class) == ("deterministic", "catalog_observed")


def test_the_definition_of_a_builtin_evidence_source_carries_neither(scoped):
    for name in scoped.evidence_sources():
        definition = scoped.evidence_source_definition(name)
        assert definition == EvidenceSourceDefinition(name=name)
        assert (definition.family, definition.evidence_class) == (None, None), name
    # Which is why callers read the derivation table by `(family, source, metadata_origin)`: one
    # class cannot answer for `metadata`, which derives two, or for `reviewed`, which spans families.
    derived = {klass for (_, source, _), klass in EVIDENCE_CLASS_DERIVATION.items() if source == "metadata"}
    assert derived == {"catalog_observed", "declared"}
    assert {family for family, source, _ in EVIDENCE_CLASS_DERIVATION if source == "reviewed"} == {
        "deterministic",
        "probabilistic",
    }


def test_builtin_evidence_sources_take_their_class_from_the_derivation_table():
    assert BUILTIN_EXTENSION.evidence_sources
    for definition in BUILTIN_EXTENSION.evidence_sources:
        assert (definition.family, definition.evidence_class) == (None, None), definition.name
    without_row = Registry(
        builtins=lambda: TypeExtension(evidence_sources=(EvidenceSourceDefinition(name="pager_feed"),))
    )
    with pytest.raises(RegistrationError) as refused:
        without_row.evidence_sources()
    assert (refused.value.reason, str(refused.value)) == (
        "underivable_evidence_source",
        "evidence source 'pager_feed' has no row in the evidence class derivation table",
    )


def test_a_locator_kind_may_carry_a_verifier_and_builtins_register_none(scoped):
    def verify(data: bytes, locator: IncidentEventLocator) -> str:
        return data.decode("utf-8")

    definition = LocatorKindDefinition(name="incident_event", model=IncidentEventLocator, verifier=verify)
    scoped.register(incident_extension(locator_kinds=(definition,)))
    assert scoped.locator("incident_event") is IncidentEventLocator
    registered = scoped.locator_kind("incident_event")
    assert registered == definition
    assert registered.model is IncidentEventLocator and registered.verifier is verify
    assert BUILTIN_EXTENSION.locator_kinds
    assert all(builtin.verifier is None for builtin in BUILTIN_EXTENSION.locator_kinds)
    assert scoped.locator_kind("file_lines") == LocatorKindDefinition(
        name="file_lines", model=k.FileLinesLocator
    )
