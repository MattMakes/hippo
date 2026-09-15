"""Records validate kinds, locators and predicates through the current ontology registry."""

import inspect
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import get_args

import pytest
from pydantic import ValidationError

from hippo.knowledge import answer_evidence, contract, locators, projection
from hippo.knowledge import model as k
from hippo.knowledge.builtin_types import EVIDENCE_CLASS_DERIVATION
from hippo.knowledge.identity import canonical_json, normalize_json
from hippo.knowledge.predicates import OBJECT_KINDS, PREDICATES, predicate_definition
from hippo.knowledge.registry import RegistrationError, Registry, extension_scope
from hippo.store import migrations
from tests.unit.test_registry import (  # noqa: F401
    REFUSALS,
    IncidentEventLocator,
    incident_extension,
    scoped,
)

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)
INCIDENT = {"workspace_id": "w", "kind": "incident_fixture", "canonical_key": '["pagerduty","P1"]'}
ARTIFACT = {
    "workspace_id": "w",
    "source_id": "source-incidents",
    "connector_id": "connector-pager",
    "provider_instance": "https://pager.example",
    "kind": "incident_export",
    "external_id": "P1",
    "canonical_uri": "https://pager.example/incidents/P1",
    "policy_id": "policy-x",
}
CONNECTOR = {"workspace_id": "w", "kind": "incident_ndjson", "instance_url": "https://pager.example"}
INCIDENT_SPAN = {
    "revision_id": "revision-x",
    "locator_kind": "incident_event",
    "locator_json": '{"kind":"incident_event","event_id":"E1"}',
    "text": "Checkout failed",
    "policy_id": "policy-x",
}
AFFECTS = {
    "workspace_id": "w",
    "subject_id": "object-a",
    "predicate": "AFFECTS_FIXTURE",
    "object_id": "object-b",
    "scope_key": "source:source-incidents:all",
}


def _object(kind: str, key: list) -> k.KnowledgeObject:
    return k.KnowledgeObject(workspace_id="w", kind=kind, canonical_key=canonical_json(key))


def test_the_vocabulary_slice_changes_no_persisted_column():
    assert migrations.CURRENT_SCHEMA_VERSION == 7
    assert migrations.MIGRATION_CHECKSUM == "73720e1eaeed7c148033c269de3a7e3af0d0c167fd87e580622f5c57537787f3"


def test_moved_contract_names_resolve_through_the_model():
    for name in (
        "Text",
        "Json",
        "Code",
        "Nonnegative",
        "Positive",
        "VersionOne",
        "_utc",
        "Instant",
        "RelativePath",
        "ProviderURL",
        "Contract",
    ):
        assert getattr(k, name) is getattr(contract, name), name
    builtins = (
        "FileLinesLocator",
        "SectionLocator",
        "FieldLocator",
        "CommentLocator",
        "PageLocator",
        "TableCellLocator",
        "DiffHunkLocator",
    )
    for name in (*builtins, "SourceLocator", "LOCATOR_ADAPTER"):
        assert getattr(k, name) is getattr(locators, name), name
    assert all(issubclass(getattr(locators, name), locators.LocatorBase) for name in builtins)


def test_object_kind_literal_names_exactly_the_builtin_kinds():
    assert set(get_args(k.ObjectKind)) == OBJECT_KINDS == Registry.with_builtins().object_kinds()
    assert k.OBJECT_KINDS is OBJECT_KINDS


def test_a_registered_kind_validates_knowledge_objects_and_query_kinds():
    with extension_scope() as registry:
        registry.register(incident_extension())
        assert k.KnowledgeObject(**INCIDENT).kind == "incident_fixture"
        request = k.QueryRequest(question="What broke checkout?", kinds=("incident_fixture", "service"))
        assert request.kinds == ("incident_fixture", "service")
    with pytest.raises(ValidationError, match="Unknown object kind"):
        k.KnowledgeObject(**INCIDENT)
    with pytest.raises(ValidationError, match="Unknown object kind"):
        k.QueryRequest(question="What broke checkout?", kinds=("incident_fixture",))


def test_registered_artifact_and_connector_kinds_validate_their_records():
    with extension_scope() as registry:
        registry.register(incident_extension())
        assert k.Artifact(**ARTIFACT).kind == "incident_export"
        assert k.Connector(**CONNECTOR).kind == "incident_ndjson"
    with pytest.raises(ValidationError, match="Unknown artifact kind"):
        k.Artifact(**ARTIFACT)
    with pytest.raises(ValidationError, match="Unknown connector kind"):
        k.Connector(**CONNECTOR)


@pytest.mark.parametrize(("reason", "message", "action"), REFUSALS)
def test_a_refused_extension_leaves_no_name_a_record_accepts(scoped, reason, message, action):  # noqa: F811
    with pytest.raises(RegistrationError):
        action(scoped)
    if reason != "duplicate_name":  # the first of the two registrations holds these names
        records = (
            lambda: k.KnowledgeObject(**INCIDENT),
            lambda: k.Assertion(**AFFECTS),
            lambda: k.EvidenceSpan(**INCIDENT_SPAN),
            lambda: k.Artifact(**ARTIFACT),
            lambda: k.Connector(**CONNECTOR),
        )
        for record in records:
            with pytest.raises(ValidationError):
                record()
    if reason in {"shadows_builtin", "duplicate_name"}:
        assert scoped.object_kind("file") == Registry.with_builtins().object_kind("file")
        with pytest.raises(ValidationError, match="Unknown object kind"):
            k.KnowledgeObject(**INCIDENT | {"kind": "File"})


LOCATOR_SAMPLES = [
    '{"kind":"file_lines","path":"./src/a.py","start":1,"end":2}',
    '{"kind":"section","heading_path":["Guide","Install"],"block_start":0,"block_end":3}',
    '{"kind":"field","field_path":"description"}',
    '{"kind":"comment","comment_id":"c1"}',
    '{"kind":"page","page":2}',
    '{"kind":"table_cell","table":0,"row":1,"column":2}',
    '{"kind":"diff_hunk","path":"a.py","start":1,"end":2,"base_revision":"a","head_revision":"b","side":"head"}',
]


@pytest.mark.parametrize("value", LOCATOR_SAMPLES)
def test_builtin_locator_canonical_json_is_byte_identical_to_the_union_adapter(value):
    expected = canonical_json(k.LOCATOR_ADAPTER.validate_json(normalize_json(value)).model_dump(mode="json"))
    assert k.canonical_locator_json(value) == expected


def test_builtin_span_identity_is_unchanged():
    span = k.EvidenceSpan(
        revision_id="revision-x",
        locator_kind="file_lines",
        locator_json='{"kind":"file_lines","path":"a.py","start":1,"end":2}',
        text="hello",
        policy_id="policy-x",
    )
    assert span.id == "span-3f9d480f360a65f44ffbf25b1bb72b282ead62e65bad0f9723a614e9170cb15a"


def test_a_registered_locator_validates_and_canonicalizes_an_evidence_span(scoped):  # noqa: F811
    scoped.register(incident_extension())
    span = k.EvidenceSpan(**INCIDENT_SPAN)
    assert span.locator_json == '{"event_id":"E1","kind":"incident_event"}'
    assert k.parse_locator_json(span.locator_json) == IncidentEventLocator(event_id="E1")
    with pytest.raises(ValidationError, match="Locator kind disagrees with its payload"):
        k.EvidenceSpan(**INCIDENT_SPAN | {"locator_kind": "field"})
    with pytest.raises(ValidationError):
        k.EvidenceSpan(
            **INCIDENT_SPAN | {"locator_json": '{"kind":"incident_event","event_id":"E1","page":1}'}
        )


def test_parse_locator_json_names_a_missing_or_unknown_kind():
    with pytest.raises(ValueError, match="Locator payload requires a kind"):
        k.parse_locator_json('{"path":"a.py"}')
    with pytest.raises(ValueError, match="Locator payload requires a kind"):
        k.parse_locator_json("[1]")
    with pytest.raises(ValueError, match="Unknown locator kind"):
        k.parse_locator_json('{"kind":"incident_event","event_id":"E1"}')


def test_answer_location_is_empty_for_an_extension_locator(scoped):  # noqa: F811
    scoped.register(incident_extension())
    location = answer_evidence._location
    assert location(SimpleNamespace(locator_json='{"kind":"incident_event","event_id":"E1"}')) == ""
    assert location(
        SimpleNamespace(locator_json='{"kind":"file_lines","path":"a.py","start":1,"end":2}')
    ) == ("a.py, lines 1–2")
    assert location(SimpleNamespace(locator_json='{"kind":"table_cell","table":0,"row":1,"column":2}')) == (
        "Table 1, row 2, column 3"
    )


def test_predicates_view_holds_the_non_identity_predicates_and_follows_extensions():
    assert len(PREDICATES) == 32
    assert "SAME_OBJECT_AS" not in PREDICATES
    assert 7 not in PREDICATES
    with pytest.raises(KeyError):
        PREDICATES["SAME_OBJECT_AS"]
    with extension_scope() as registry:
        registry.register(incident_extension())
        assert len(PREDICATES) == 33
        assert "AFFECTS_FIXTURE" in PREDICATES
        assert PREDICATES["AFFECTS_FIXTURE"].traversal_permitted
        assert list(PREDICATES) == sorted(PREDICATES)
    assert len(PREDICATES) == 32
    assert "AFFECTS_FIXTURE" not in PREDICATES


def test_same_object_as_accepts_any_registered_kind_pair_without_ownership_or_traversal():
    with extension_scope() as registry:
        registry.register(incident_extension())
        service, incident = _object("service", ["a-service"]), _object("incident_fixture", ["b-incident"])
        same = k.checked_assertion(service, "SAME_OBJECT_AS", incident, scope_key="source:s:all")
        assert (same.subject_id, same.object_id) == (service.id, incident.id)
    with pytest.raises(ValueError, match="Invalid endpoint kinds for SAME_OBJECT_AS"):
        k.checked_assertion(service, "SAME_OBJECT_AS", incident, scope_key="source:s:all")
    table, view = _object("table", ["orders"]), _object("view", ["orders_v"])
    assert k.checked_assertion(table, "SAME_OBJECT_AS", view, scope_key="source:s:all").subject_id == table.id
    assert predicate_definition("SAME_OBJECT_AS").identity
    assert predicate_definition("SAME_OBJECT_AS").traversal_permitted is False


def test_same_object_as_stores_the_lexically_smaller_canonical_key_as_subject():
    first, second = _object("service", ["a"]), _object("repository", ["b"])
    with pytest.raises(
        ValueError, match="SAME_OBJECT_AS stores the lexically smaller canonical key as its subject"
    ):
        k.checked_assertion(second, "SAME_OBJECT_AS", first, scope_key="source:s:all")
    with pytest.raises(ValueError, match="SAME_OBJECT_AS requires two distinct objects"):
        k.checked_assertion(first, "SAME_OBJECT_AS", first, scope_key="source:s:all")
    table, view = _object("table", ["x"]), _object("view", ["x"])  # equal keys: the kind breaks the tie
    assert k.checked_assertion(table, "SAME_OBJECT_AS", view, scope_key="source:s:all").subject_id == table.id
    with pytest.raises(ValueError, match="lexically smaller canonical key"):
        k.checked_assertion(view, "SAME_OBJECT_AS", table, scope_key="source:s:all")


def test_alias_of_keeps_its_alias_subject_rule():
    alias, symbol = _object("alias", ["docs", "billing"]), _object("symbol", ["repo", "pkg.charge"])
    assert k.checked_assertion(alias, "ALIAS_OF", symbol, scope_key="source:s:all").subject_id == alias.id
    with pytest.raises(ValueError, match="Invalid endpoint kinds for ALIAS_OF"):
        k.checked_assertion(symbol, "ALIAS_OF", alias, scope_key="source:s:all")


def test_renamed_to_and_duplicate_of_keep_the_matching_kind_rule():
    table, view = _object("table", ["orders"]), _object("view", ["orders_v"])
    with pytest.raises(ValueError, match="RENAMED_TO requires matching endpoint kinds"):
        k.checked_assertion(table, "RENAMED_TO", view, scope_key="source:s:all")
    renamed = _object("table", ["orders_2"])
    assert k.checked_assertion(table, "RENAMED_TO", renamed, scope_key="source:s:all").object_id == renamed.id
    ticket, requirement = _object("ticket", ["jira", "1"]), _object("requirement", ["docs", "1"])
    with pytest.raises(ValueError, match="DUPLICATE_OF requires matching endpoint kinds"):
        k.checked_assertion(ticket, "DUPLICATE_OF", requirement, scope_key="source:s:all")


def test_projection_reads_predicate_definitions_through_the_registry():
    assert "PREDICATES[" not in inspect.getsource(projection)


def test_the_two_new_evidence_classes_validate_and_change_no_column():
    for evidence_class in ("rule_derived", "similarity_inferred"):
        observation = k.ObjectObservation(
            object_id="object-x",
            revision_id="revision-x",
            span_id="span-x",
            evidence_class=evidence_class,
            recorded_from=NOW,
        )
        version = k.AssertionVersion(
            assertion_id="assertion-x",
            evidence_class=evidence_class,
            rule_version="rule@1",
            confidence=1.0,
            status="active",
            recorded_from=NOW,
        )
        assert observation.evidence_class == version.evidence_class == evidence_class
    with pytest.raises(ValidationError):
        k.ObjectObservation(
            object_id="object-x",
            revision_id="revision-x",
            span_id="span-x",
            evidence_class="model_guess",
            recorded_from=NOW,
        )
    assert migrations.KNOWLEDGE_COLUMNS["ObjectObservation"]["evidence_class"] == "STRING"
    assert migrations.KNOWLEDGE_COLUMNS["AssertionVersion"]["evidence_class"] == "STRING"
    assert set(EVIDENCE_CLASS_DERIVATION.values()) <= set(get_args(k.EvidenceClass))
