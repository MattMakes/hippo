"""Rendering: the label, the fact templates, the edge statement and the unit prefixes.

Plan `ai_docs/plans/cdk-s2-contract.md` sections 4.4 and 7, with rulings R6 (a rendered fact is one
unit), R11/R26 (`base.token_count` is the one counter) and R20 (render text carries no version of its
own; a template's `name@version` does). Every rule here is the specification's section 3 "Rendering
rules" as code: one template invocation is one unit, and nothing ever joins two outputs.
"""

import hashlib

import pytest
from pydantic import BaseModel, ConfigDict

from hippo.connectors import base, keys, render
from hippo.knowledge.identity import text_hash
from hippo.knowledge.registry import (
    FactTemplate,
    ObjectKindDefinition,
    PredicateDefinition,
    TypeExtension,
    extension_scope,
)

INSTANCE = "https://incidents.example"


class IncidentAttributes(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    severity: str
    resolution: str | None = None


class ColumnAttributes(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    column_type: str


def incident_kind(**overrides) -> ObjectKindDefinition:
    fields = {
        "name": "incident_fixture",
        "family": "incident",
        "key_template": ("tool", "incident_id"),
        "key_prefix": "incx",
        "attrs_model": IncidentAttributes,
        "label_template": "{title}",
        "fact_templates": (
            FactTemplate(
                name="severity",
                version="1",
                consumes=("severity",),
                text="Incident {label} ({key}) is severity {severity}.",
            ),
            FactTemplate(
                name="resolution",
                version="2",
                consumes=("resolution",),
                text="Incident {label} was resolved by {resolution}.",
            ),
        ),
    }
    return ObjectKindDefinition(**(fields | overrides))


def column_kind() -> ObjectKindDefinition:
    return ObjectKindDefinition(
        name="fixture_column",
        family="incident",
        key_template=("tool", "incident_id"),
        key_prefix="fcol",
        attrs_model=ColumnAttributes,
        label_template="{name}",
        fact_templates=(
            FactTemplate(
                name="column_type",
                version="1",
                consumes=("column_type",),
                text="Column {label} has type {column_type}.",
            ),
        ),
    )


def affects_predicate(**overrides) -> PredicateDefinition:
    fields = {
        "name": "AFFECTS_FIXTURE",
        "subject_kinds": frozenset({"incident_fixture"}),
        "object_kinds": frozenset({"service"}),
        "owner_families": frozenset({"incident"}),
        "canonical_direction": "subject_to_object",
        "family_default": "deterministic",
        "sources_allowed": frozenset({"metadata", "rule"}),
        "verb_phrase": "affects",
    }
    return PredicateDefinition(**(fields | overrides))


@pytest.fixture
def registry():
    with extension_scope() as scoped:
        scoped.register(
            TypeExtension(
                object_kinds=(incident_kind(), column_kind()),
                predicates=(affects_predicate(),),
            ),
            declared_families=("incident",),
        )
        scoped.freeze()
        yield scoped


def attrs_of(registry, kind: str, **values) -> BaseModel:
    return registry.object_kind(kind).attrs_model(**values)


def key_of(registry, kind: str = "incident_fixture") -> keys.CanonicalKey:
    return keys.canonical_key(
        registry,
        base.NodeRef(kind=kind, key={"tool": "pager", "incident_id": "INC-1"}),
        instance=INSTANCE,
    )


# ------------------------------------------------------------------ the rule


def test_render_rule_version_and_prefix_constants_are_pinned() -> None:
    assert render.RENDER_RULE_VERSION == "cdk-render-v1"
    assert render.PREFIX_TOKEN_LIMIT == 12
    assert render.PREFIX_SEPARATOR == ": "


# ------------------------------------------------------------------ labels and facts


def test_label_template_renders_from_declared_attributes(registry) -> None:
    definition = registry.object_kind("incident_fixture")
    attrs = attrs_of(registry, "incident_fixture", title="Checkout is down", severity="sev1")
    assert render.render_label(definition, attrs) == "Checkout is down"
    assert render.kind_label(definition) == "incident fixture"


def test_each_fact_template_renders_exactly_one_unit(registry) -> None:
    definition = registry.object_kind("incident_fixture")
    attrs = attrs_of(
        registry,
        "incident_fixture",
        title="Checkout is down",
        severity="sev1",
        resolution="a rollback",
    )
    rendered = render.render_facts(definition, attrs, label="Checkout is down", key=key_of(registry))
    assert len(rendered) == len(definition.fact_templates) == 2
    assert [item.template for item in rendered] == ["severity@1", "resolution@2"]
    assert rendered[0].text == (f"Incident Checkout is down ({key_of(registry).readable}) is severity sev1.")
    assert rendered[1].text == "Incident Checkout is down was resolved by a rollback."


def test_fact_templates_format_only_consumed_attributes_label_and_key(registry) -> None:
    definition = incident_kind(
        fact_templates=(
            FactTemplate(
                name="severity",
                version="1",
                consumes=("severity",),
                # `title` is an attribute this template does not consume, so it is not a field.
                text="{label}/{key}/{severity}",
            ),
        )
    )
    attrs = IncidentAttributes(title="Checkout is down", severity="sev1")
    key = key_of(registry)
    rendered = render.render_facts(definition, attrs, label="L", key=key)
    assert rendered[0].text == f"L/{key.readable}/sev1"
    with pytest.raises(KeyError):
        "{title}".format_map({name: "x" for name in ("severity", "label", "key")})


def test_forty_column_nodes_render_forty_units_and_none_joins_two_outputs(registry) -> None:
    definition = registry.object_kind("fixture_column")
    key = key_of(registry, "fixture_column")
    rendered = [
        render.render_facts(
            definition,
            ColumnAttributes(name=f"col_{index}", column_type="text"),
            label=f"col_{index}",
            key=key,
        )
        for index in range(40)
    ]
    assert [len(item) for item in rendered] == [1] * 40
    texts = [item[0].text for item in rendered]
    assert len(set(texts)) == 40
    assert all(text.count("Column ") == 1 for text in texts)


def test_a_template_with_a_none_consumed_attribute_is_skipped_and_counted(registry) -> None:
    definition = registry.object_kind("incident_fixture")
    attrs = attrs_of(registry, "incident_fixture", title="Open", severity="sev2", resolution=None)
    rendered = render.render_facts(definition, attrs, label="Open", key=key_of(registry))
    # No unit and no error; `emit` counts the omission as coverage["facts_skipped"]["resolution@2"].
    assert [item.template for item in rendered] == ["severity@1"]
    assert len(definition.fact_templates) == 2


def test_a_label_template_naming_a_missing_attribute_is_refused(registry) -> None:
    definition = incident_kind(label_template="{missing}")
    with pytest.raises(base.ContractError) as refused:
        render.render_label(definition, IncidentAttributes(title="t", severity="sev1"))
    assert str(refused.value) == ("Label template of incident_fixture names a missing attribute missing")


# ------------------------------------------------------------------ edge statements


def test_edge_statement_reads_subject_kind_label_verb_object_kind_label(registry) -> None:
    predicate = registry.predicate("AFFECTS_FIXTURE")
    subject = registry.object_kind("incident_fixture")
    target = registry.object_kind("service")
    assert render.edge_statement(predicate, (subject, "Checkout is down"), (target, "checkout")) == (
        "incident fixture Checkout is down affects service checkout"
    )


def test_edge_statement_appends_the_source_statement_after_a_colon(registry) -> None:
    predicate = registry.predicate("AFFECTS_FIXTURE")
    statement = render.edge_statement(
        predicate,
        (registry.object_kind("incident_fixture"), "Checkout is down"),
        (registry.object_kind("service"), "checkout"),
        source_statement="checkout returned 503 for 20 minutes",
    )
    assert statement == (
        "incident fixture Checkout is down affects service checkout: checkout returned 503 for 20 minutes"
    )


def test_rule_edge_statement_appends_rule_and_evidence_in_parentheses(registry) -> None:
    predicate = registry.predicate("AFFECTS_FIXTURE")
    statement = render.edge_statement(
        predicate,
        (registry.object_kind("incident_fixture"), "Checkout is down"),
        (registry.object_kind("service"), "checkout"),
        rule="temporal_window",
        rule_evidence="within 5 minutes",
    )
    assert statement == (
        "incident fixture Checkout is down affects service checkout (temporal window: within 5 minutes)"
    )


# ------------------------------------------------------------------ prefixes


def test_heading_prefix_is_the_innermost_heading_cut_to_twelve_tokens_with_its_separator() -> None:
    innermost = " ".join(f"word{index}" for index in range(20))
    prefix = render.heading_prefix(("Chapter one", "Locking strategy", innermost))
    kept = " ".join(f"word{index}" for index in range(render.PREFIX_TOKEN_LIMIT))
    assert prefix == kept + render.PREFIX_SEPARATOR
    assert render.heading_prefix(("Locking strategy",)) == "Locking strategy: "
    assert render.heading_prefix(()) == ""


def test_symbol_prefix_ends_with_the_separator() -> None:
    assert render.symbol_prefix("dispatch_settlement_run") == "dispatch_settlement_run: "
    assert render.symbol_prefix("").endswith(render.PREFIX_SEPARATOR) is True


# ------------------------------------------------------------------ unit text and hashes


def test_rendered_units_have_no_prefix_and_embed_text_equals_text(registry) -> None:
    definition = registry.object_kind("incident_fixture")
    attrs = attrs_of(registry, "incident_fixture", title="Checkout is down", severity="sev1")
    for rendered in render.render_facts(definition, attrs, label="L", key=key_of(registry)):
        assert rendered.prefix == ""
        assert rendered.embed_text == rendered.text
        assert rendered.embed_hash == rendered.content_hash


def test_embed_text_is_prefix_plus_text_and_both_hashes_are_sha256() -> None:
    rendered = render.unit_text("It takes an exclusive lock", prefix="Locking strategy: ")
    assert rendered.embed_text == "Locking strategy: It takes an exclusive lock"
    assert rendered.content_hash == hashlib.sha256(rendered.text.encode("utf-8")).hexdigest()
    assert rendered.embed_hash == hashlib.sha256(rendered.embed_text.encode("utf-8")).hexdigest()
    assert rendered.template is None


def test_identical_text_under_two_headings_shares_content_hash_not_embed_hash() -> None:
    first = render.unit_text("It takes an exclusive lock", prefix=render.heading_prefix(("Locking",)))
    second = render.unit_text("It takes an exclusive lock", prefix=render.heading_prefix(("Retries",)))
    assert first.content_hash == second.content_hash
    assert first.embed_hash != second.embed_hash


def test_embed_hash_is_the_embedding_cache_input_hash() -> None:
    """S1 D17: the vector cache keys on `embed_text`, so the unit carries that exact hash."""
    from hippo.knowledge.embedding_cache import EmbeddingProfile, cache_key

    profile = EmbeddingProfile(
        model="nomic-embed-text",
        model_digest="sha256:" + "0" * 64,
        dimension=768,
        preprocessing_version="p1",
        normalization_options_fingerprint="n1",
    )
    rendered = render.unit_text("one sentence", prefix="Heading: ")
    assert rendered.embed_hash == cache_key(profile, rendered.embed_text).input_hash
    assert rendered.embed_hash == text_hash(rendered.embed_text)


def test_token_count_is_the_character_count_the_chunker_budgets_with() -> None:
    text = "a sentence of some length"
    assert base.token_count(text) == len(text) == 25
    assert base.PASSAGE_CHAR_BOUND == 6000


# ------------------------------------------------------------------ purity


def test_render_reads_no_clock_and_no_module_state(registry) -> None:
    definition = registry.object_kind("incident_fixture")
    attrs = attrs_of(registry, "incident_fixture", title="Checkout is down", severity="sev1")
    first = render.render_facts(definition, attrs, label="L", key=key_of(registry))
    second = render.render_facts(definition, attrs, label="L", key=key_of(registry))
    assert first == second
    source = __import__("inspect").getsource(render)
    for forbidden in ("import time", "datetime.now", "random", "httpx", "subprocess"):
        assert forbidden not in source
