"""Records name kinds, locators and predicates as plain codes; the registry checks them at bind and write.

Reads never consult the registry for membership (ruling R39): a row written under an extension reads
back where the extension is not registered, and projection leaves such rows out and counts them.
"""

import inspect
from collections import Counter
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import get_args

import pytest
from pydantic import ValidationError

from hippo.access import EVERYTHING
from hippo.knowledge import answer_evidence, contract, locators, projection
from hippo.knowledge import model as k
from hippo.knowledge.access import EvidenceAccess, EvidenceSelection
from hippo.knowledge.builtin_types import EVIDENCE_CLASS_DERIVATION
from hippo.knowledge.graph_loader import load_generation_graph
from hippo.knowledge.identity import canonical_json, normalize_json
from hippo.knowledge.lifecycle import generation_passage_id
from hippo.knowledge.predicates import OBJECT_KINDS, PREDICATES, predicate_definition
from hippo.knowledge.registry import (
    RegistrationError,
    Registry,
    TypeExtension,
    extension_scope,
)
from hippo.store import migrations
from tests.unit.test_derived_generation_store import extraction, member, rendered
from tests.unit.test_evidence_access import NOW as ACCESS_NOW
from tests.unit.test_evidence_access import engine
from tests.unit.test_evidence_projection import assertion as supported_assertion
from tests.unit.test_evidence_projection import fixture as projection_world
from tests.unit.test_generation_store import NOW as STORE_NOW
from tests.unit.test_generation_store import authority, claim, evidence, generation, passage, publish, seal
from tests.unit.test_registry import (  # noqa: F401
    REFUSALS,
    IncidentEventLocator,
    affects_predicate,
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


def _extension_rows() -> list[tuple[k.Record, str]]:
    """One record per vocabulary field, each naming the extension, with the refusal `check_record` raises."""
    return [
        (k.KnowledgeObject(**INCIDENT), "Unknown object kind"),
        (k.Artifact(**ARTIFACT), "Unknown artifact kind"),
        (k.Connector(**CONNECTOR), "Unknown connector kind"),
        (k.EvidenceSpan(**INCIDENT_SPAN), "Unknown locator kind"),
        (k.Assertion(**AFFECTS), "Unknown assertion predicate"),
    ]


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
        "EvidenceClass",
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


def test_vocabulary_fields_accept_any_code_without_a_registration():
    rows = _extension_rows()
    assert [row.kind for row, _ in rows[:3]] == ["incident_fixture", "incident_export", "incident_ndjson"]
    assert rows[3][0].locator_json == '{"event_id":"E1","kind":"incident_event"}'
    assert rows[4][0].predicate == "AFFECTS_FIXTURE"
    request = k.QueryRequest(question="What broke checkout?", kinds=("incident_fixture", "service"))
    assert request.kinds == ("incident_fixture", "service")
    with pytest.raises(ValidationError):
        k.KnowledgeObject(**INCIDENT | {"kind": "not a code"})
    with pytest.raises(ValidationError, match="Locator kind disagrees with its payload"):
        k.EvidenceSpan(**INCIDENT_SPAN | {"locator_kind": "pager_event"})
    with pytest.raises(ValidationError, match="Locator payload requires a kind"):
        k.EvidenceSpan(**INCIDENT_SPAN | {"locator_json": '{"event_id":"E1"}'})


def test_a_row_of_an_unregistered_kind_reads_back_outside_its_registry(store):
    workspace = k.Workspace(name="incidents")
    with extension_scope() as registry:
        registry.register(incident_extension())
        rows = [row for row, _ in _extension_rows()]
        incident = k.KnowledgeObject(**INCIDENT | {"workspace_id": workspace.id})
        service = k.KnowledgeObject(workspace_id=workspace.id, kind="service", canonical_key='["checkout"]')
        affects = k.checked_assertion(incident, "AFFECTS_FIXTURE", service, scope_key="source:s:all")
        for record in (workspace, incident, service, affects):
            store.put_knowledge(record)
    # What the store does on every read (`store/knowledge.py` `_knowledge_records`).
    for row in rows:
        assert type(row).model_validate_json(row.model_dump_json()) == row
    assert store._knowledge_rows("KnowledgeObject", ids=[incident.id]) == [incident]
    assert store._knowledge_rows("Assertion", ids=[affects.id]) == [affects]


def test_check_record_refuses_an_unregistered_kind(scoped):  # noqa: F811
    rows = _extension_rows()
    for row, refusal in rows:
        with pytest.raises(ValueError, match=refusal):
            scoped.check_record(row)
    builtins = (_object("service", ["checkout"]), k.Assertion(**AFFECTS | {"predicate": "BOUND_TO"}))
    for row in builtins:
        assert scoped.check_record(row) is None
    scoped.register(incident_extension())
    for row, _ in rows:
        assert scoped.check_record(row) is None
    assert scoped.check_record(k.Workspace(name="incidents")) is None
    with pytest.raises(TypeError, match="Registry.check_record takes a knowledge record"):
        scoped.check_record("KnowledgeObject")


def test_check_record_validates_a_span_payload_with_its_registered_model(scoped):  # noqa: F811
    unchecked = k.EvidenceSpan(**INCIDENT_SPAN | {"locator_json": '{"kind":"incident_event","page":1}'})
    scoped.register(incident_extension())
    with pytest.raises(ValidationError):
        scoped.check_record(unchecked)
    assert scoped.check_record(k.EvidenceSpan(**INCIDENT_SPAN)) is None


@pytest.mark.parametrize(("reason", "message", "action"), REFUSALS)
def test_a_refused_extension_leaves_no_name_check_record_accepts(scoped, reason, message, action):  # noqa: F811
    with pytest.raises(RegistrationError):
        action(scoped)
    if reason != "duplicate_name":  # the first of the two registrations holds these names
        for row, refusal in _extension_rows():
            with pytest.raises(ValueError, match=refusal):
                scoped.check_record(row)
    if reason in {"shadows_builtin", "duplicate_name"}:
        assert scoped.object_kind("file") == Registry.with_builtins().object_kind("file")
        with pytest.raises(ValueError, match="Unknown object kind"):
            scoped.check_record(k.KnowledgeObject(**INCIDENT | {"kind": "File"}))


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


def test_answer_location_is_empty_for_an_unregistered_locator():
    citation = SimpleNamespace(locator_json='{"kind":"incident_event","event_id":"E1"}')
    assert answer_evidence._location(citation) == ""


def _calls_fixture() -> TypeExtension:
    calls = affects_predicate(
        name="CALLS_FIXTURE",
        subject_kinds=frozenset({"symbol"}),
        object_kinds=frozenset({"symbol"}),
        owner_families=frozenset({"code"}),
        sources_allowed=frozenset({"parser"}),
        verb_phrase="calls",
    )
    return TypeExtension(predicates=(calls,))


def _register_extensions(registry: Registry) -> None:
    registry.register(incident_extension())
    registry.register(_calls_fixture(), declared_families=("code",))


def _extension_projection() -> SimpleNamespace:
    """The evidence projection world plus one row per extension vocabulary, written under the extension."""
    w = projection_world()
    with extension_scope() as registry:
        _register_extensions(registry)
        w.incident = w.store.add(
            k.KnowledgeObject(workspace_id=w.workspace.id, kind="incident_fixture", canonical_key='["P1"]')
        )
        w.store.add(
            k.ObjectObservation(
                object_id=w.incident.id,
                revision_id=w.revision.id,
                span_id=w.spans[0].id,
                evidence_class="declared",
                recorded_from=ACCESS_NOW,
                attributes_json='{"name":"checkout outage"}',
            )
        )
        w.event = w.store.add(
            k.EvidenceSpan(**INCIDENT_SPAN | {"revision_id": w.revision.id, "policy_id": w.parent.id})
        )
        w.calls = supported_assertion(w, predicate="CALLS_FIXTURE")
    return w


def _project(w: SimpleNamespace, exclusions: Counter | None) -> object:
    return projection.project_managed_graph(
        w.full, w.store, engine(w).build(w.selection), embedding_profile="embed-v1", exclusions=exclusions
    )


def test_projection_leaves_out_and_counts_rows_of_unregistered_vocabulary():
    w = _extension_projection()
    exclusions = Counter()
    graph = _project(w, exclusions)
    first = graph.idx_of[w.objects[0].id]
    assert w.incident.id not in graph.idx_of
    assert not any(arrow.kind == "CALLS_FIXTURE" for arrow in graph.out_edges(first))
    assert w.event.id not in {citation.id for citation in graph.original_citations}
    assert exclusions == Counter(object_kinds=1, locator_kinds=1, predicates=1)


def test_projection_keeps_those_rows_where_their_extension_is_registered():
    w = _extension_projection()
    exclusions = Counter()
    with extension_scope() as registry:
        _register_extensions(registry)
        graph = _project(w, exclusions)
    first, second = (graph.idx_of[obj.id] for obj in w.objects)
    assert w.incident.id in graph.idx_of
    assert any(arrow.kind == "CALLS_FIXTURE" and arrow.dst == second for arrow in graph.out_edges(first))
    assert exclusions == Counter()
    assert _project(w, None).idx_of.keys() <= graph.idx_of.keys()


def test_projection_leaves_out_views_and_prose_anchored_on_an_unregistered_locator(store):
    gen = generation(store, "incidents")
    job = claim(store, gen, key="incidents")
    with extension_scope() as registry:
        registry.register(incident_extension())
        with store.generation_write(gen.id, **authority(job)):
            revision, span = evidence(store, gen)
            store.add_passages([passage(gen, revision, span)])
            event = k.EvidenceSpan(
                **INCIDENT_SPAN | {"revision_id": revision.id, "policy_id": span.policy_id}
            )
            member(store, gen, event)
            view, _, _ = rendered(store, gen, event, text="rendered incident")
            row = passage(gen, revision, event) | {
                "id": generation_passage_id(gen.id, revision.id, event.id, 1, retrieval_view_id=view.id),
                "retrieval_view_id": view.id,
                "text": view.text,
                "ordinal": 1,
            }
            store.add_passages([row])
            member(store, gen, extraction(store, gen, event, row))
        seal(store, gen, job)
        publish(store, gen, job)
    selection = EvidenceSelection(generation_ids=frozenset({gen.id}), require_exact_membership=True)
    access = EvidenceAccess(
        store, store.get_source(gen.source_id)["workspace_id"], EVERYTHING, clock=lambda: STORE_NOW
    )
    full = load_generation_graph(
        store, generations={gen.source_id: gen.id}, legacy_source_ids=frozenset(), version=1
    )
    exclusions = Counter()
    graph = projection.project_managed_graph(
        full, store, access.build(selection), embedding_profile="p", exclusions=exclusions
    )
    assert [p.id for p in graph.passages] == [span.id]  # an unrendered passage keeps its span id
    assert [citation.id for citation in graph.original_citations] == [span.id]
    assert not graph.facts
    assert exclusions == Counter(locator_kinds=1)


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
