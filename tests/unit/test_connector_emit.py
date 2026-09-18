"""Binding an emission batch to knowledge records: the totality table and every refusal.

Plan `ai_docs/plans/cdk-s2-contract.md` sections 4.5, 8 and 9. Rulings: R6 (a rendered fact is a
`Unit` and a derived `Passage`; identity-only foreign endpoints), R16 and R39 (the binder checks the
frozen `current_registry()` and calls `Registry.check_record` on every record it builds), R40 and R62
(an extension evidence source carries its class, read through `Registry.evidence_source_definition`),
R42 (the bound message interpolates `PASSAGE_CHAR_BOUND`), R45 (built-in locator verifiers are this
module's table, consulted before an extension kind's `verifier`), R48/B2 (every span's `policy_id` is
`RevisionInput.span_policy_id`), R53/M6 (an identity-only foreign endpoint is keyed by its declared
`NodeRef.instance`), R61 (`policy_record` applies the instance `principal_map`), R63 (`evidence_class`
takes the registry), M7 (`Provenance.observed_at` is `ArtifactRevision.source_updated_at`), m4 (the
refusal cases are S1's), m21.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict
from test_registry import REFUSALS  # m4: the binder is checked against S1's refusal cases

from hippo.connectors import base, emit, keys, render
from hippo.knowledge import model as k
from hippo.knowledge.builtin_types import EVIDENCE_CLASS_DERIVATION
from hippo.knowledge.identity import canonical_json, text_hash
from hippo.knowledge.lifecycle import generation_passage_id
from hippo.knowledge.locators import LocatorBase
from hippo.knowledge.registry import (
    EvidenceSourceDefinition,
    FactTemplate,
    LocatorKindDefinition,
    ObjectKindDefinition,
    PredicateDefinition,
    RegistrationError,
    Registry,
    TypeExtension,
    UnregisteredName,
    extension_scope,
    use_registry,
)

WORKSPACE = "workspace"
SOURCE = "source-1"
PARTITION = "incidents"
INSTANCE = "https://incidents.example"
CATALOG = "https://backstage.example"
CREATED_AT = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 9, 15, 11, 0, tzinfo=UTC)
SOURCE_UPDATED_AT = datetime(2026, 9, 14, 8, 30, tzinfo=UTC)
DATA = b"first line\nsecond line\nthird line\n"


class IncidentAttributes(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    severity: str
    resolution: str | None = None


class IncidentEventLocator(LocatorBase):
    kind: Literal["incident_event"] = "incident_event"
    event_id: str


class FixtureConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instance: str = INSTANCE


def incident_event_verifier(data: bytes, locator: dict, *, artifact: k.Artifact) -> str:
    """The call shape S2b defines for `LocatorKindDefinition.verifier` (ruling R45)."""
    return data.decode("utf-8").splitlines(keepends=True)[0]


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
                text="Incident {label} is severity {severity}.",
            ),
        ),
    }
    return ObjectKindDefinition(**(fields | overrides))


def fixture_predicate(**overrides) -> PredicateDefinition:
    fields = {
        "name": "AFFECTS_FIXTURE",
        "subject_kinds": frozenset({"incident_fixture"}),
        "object_kinds": frozenset({"service"}),
        "owner_families": frozenset({"incident"}),
        "canonical_direction": "subject_to_object",
        "family_default": "deterministic",
        "sources_allowed": frozenset({"metadata", "rule", "pager_pull"}),
        "verb_phrase": "affects",
    }
    return PredicateDefinition(**(fields | overrides))


def fixture_extension() -> TypeExtension:
    return TypeExtension(
        object_kinds=(incident_kind(),),
        artifact_kinds=("incident_export",),
        locator_kinds=(
            LocatorKindDefinition(
                name="incident_event", model=IncidentEventLocator, verifier=incident_event_verifier
            ),
        ),
        evidence_sources=(
            EvidenceSourceDefinition(
                name="pager_pull", family="deterministic", evidence_class="catalog_observed"
            ),
        ),
        predicates=(
            fixture_predicate(),
            fixture_predicate(name="WINDOWED_FIXTURE", windowed=True),
        ),
    )


@pytest.fixture
def registry():
    with extension_scope() as scoped:
        scoped.register(fixture_extension(), declared_families=("incident",))
        scoped.freeze()
        yield scoped


def descriptor(**overrides) -> base.ConnectorDescriptor:
    fields = {
        "name": "pager",
        "version": "1.0.0",
        "families": ("incident",),
        "kinds": ("incident_fixture", "service", "api"),
        "predicates": ("AFFECTS_FIXTURE", "WINDOWED_FIXTURE", "PROVIDES_API"),
        "artifact_kinds": ("incident_export", "file"),
        "locator_kinds": ("file_lines", "field", "table_cell", "incident_event", "section"),
        "capabilities": base.ConnectorCapabilities(acls=True),
        "config_model": FixtureConfig,
        "credentials": (),
        "parsers": (base.ParserVersion(name="pager/json", version="1"),),
        "extension": fixture_extension(),
    }
    return base.ConnectorDescriptor(**(fields | overrides))


def connector_row() -> k.Connector:
    return k.Connector(
        workspace_id=WORKSPACE,
        kind="pager",
        instance_url=INSTANCE,
        config_json=canonical_json({"principal_map": {"users": {"u1": "local-u1"}, "groups": {}}}),
        enabled=True,
    )


def generation_row() -> k.Generation:
    return k.Generation(
        source_id=SOURCE,
        status="staging",
        parser_version="p1",
        linker_version="l1",
        embedding_profile="profile-1",
        created_at=CREATED_AT,
        manifest_hash="m" * 64,
    )


def policy_row() -> k.AccessPolicy:
    return k.AccessPolicy(
        workspace_id=WORKSPACE,
        origin="provider",
        scope_key="connector:c:incident_export:INC-1",
        mode="workspace",
        verified_at=OBSERVED_AT,
        expires_at=OBSERVED_AT + timedelta(days=1),
    )


class World:
    """One frozen registry, one connector, one generation and one revision under bind."""

    def __init__(self, registry, *, data: bytes = DATA, artifact_kind: str = "file", **overrides):
        self.registry = registry
        self.descriptor = overrides.pop("descriptor", None) or descriptor()
        self.connector = connector_row()
        self.generation = generation_row()
        self.policy = policy_row()
        self.other_policy = policy_row().replace(mode="restricted", allow_users=("local-u1",))
        self.data = data
        self.artifact = k.Artifact(
            workspace_id=WORKSPACE,
            source_id=SOURCE,
            connector_id=self.connector.id,
            provider_instance=INSTANCE,
            kind=artifact_kind,
            external_id="incidents/INC-1.txt",
            canonical_uri=f"{INSTANCE}/incidents/INC-1",
            # The artifact's *current* policy differs from the span policy on purpose (R48/B2).
            policy_id=self.other_policy.id,
        )
        self.revision = k.ArtifactRevision(
            artifact_id=self.artifact.id,
            provider_revision="rev-7",
            content_hash=hashlib.sha256(data).hexdigest(),
            raw_uri="raw://incidents/INC-1",
            source_updated_at=SOURCE_UPDATED_AT,
            source_timestamp_original="2026-09-14T08:30:00Z",
            observed_at=OBSERVED_AT,
            lifecycle="active",
        )
        self.context = emit.BindContext(
            registry=registry,
            descriptor=self.descriptor,
            connector=self.connector,
            generation=self.generation,
            workspace_id=WORKSPACE,
            source_id=SOURCE,
            partition=PARTITION,
        )

    def revision_input(self, **overrides) -> base.RevisionInput:
        fields = {
            "partition": PARTITION,
            "artifact": self.artifact,
            "revision": self.revision,
            "data": self.data,
            "config": FixtureConfig(),
            "mapping": base.TypeMapping(family="incident"),
            "registry": self.registry,
            "span_policy_id": self.policy.id,
        }
        return base.RevisionInput(**(fields | overrides))

    def bind(self, batch: base.EmissionBatch, **overrides) -> emit.BoundBatch:
        return emit.bind_batch(self.context, self.revision_input(**overrides), batch)


@pytest.fixture
def world(registry) -> World:
    return World(registry)


@pytest.fixture
def builtin_world(registry) -> World:
    """A connector of the `service` family, so a built-in predicate of that family binds."""
    return World(
        registry,
        descriptor=descriptor(families=("service",), kinds=("service",), predicates=("DEPENDS_ON",)),
    )


@pytest.fixture
def reviewing_world() -> World:
    """An extension that declares `reviewed` in its own `sources_allowed`, which it may."""
    extension = fixture_extension()
    widened = fixture_predicate(sources_allowed=frozenset({"metadata", "rule", "reviewed"}))
    with extension_scope() as scoped:
        scoped.register(
            extension.model_copy(update={"predicates": (widened, extension.predicates[1])}),
            declared_families=("incident",),
        )
        scoped.freeze()
        yield World(scoped)


# ------------------------------------------------------------------ emission helpers


def lines_span(start: int = 1, end: int = 1, *, text: str | None = None) -> base.SpanRef:
    return base.SpanRef(
        locator_kind="file_lines",
        locator={"kind": "file_lines", "path": "incidents/INC-1.txt", "start": start, "end": end},
        text=text,
    )


def incident_ref(incident_id: str = "INC-1") -> base.NodeRef:
    return base.NodeRef(kind="incident_fixture", key={"tool": "pager", "incident_id": incident_id})


def service_ref(reference: str = "checkout") -> base.NodeRef:
    return base.NodeRef(kind="service", key={"reference": reference}, instance=CATALOG)


def node_emission(**overrides) -> base.NodeEmission:
    fields = {
        "ref": incident_ref(),
        "attrs": {"title": "Checkout is down", "severity": "sev1"},
        "span": lines_span(),
        "source": "metadata",
        "metadata_origin": "catalog",
    }
    return base.NodeEmission(**(fields | overrides))


def service_emission(**overrides) -> base.NodeEmission:
    fields = {
        "ref": service_ref(),
        "attrs": {"name": "checkout"},
        "span": lines_span(2, 2),
        "source": "metadata",
        "metadata_origin": "catalog",
    }
    return base.NodeEmission(**(fields | overrides))


def edge_emission(**overrides) -> base.EdgeEmission:
    fields = {
        "subject": incident_ref(),
        "predicate": "AFFECTS_FIXTURE",
        "object": service_ref(),
        "family": "deterministic",
        "source": "metadata",
        "metadata_origin": "catalog",
        "weight": 1.0,
        "support": (base.SupportEmission(spans=(lines_span(3, 3),)),),
    }
    return base.EdgeEmission(**(fields | overrides))


def node_batch(**overrides) -> base.EmissionBatch:
    return base.EmissionBatch(nodes=(node_emission(**overrides),))


def edge_batch() -> base.EmissionBatch:
    return base.EmissionBatch(nodes=(node_emission(), service_emission()), edges=(edge_emission(),))


def _is_docstring(node) -> bool:
    import ast

    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)


def one(bound: emit.BoundBatch, record_kind: str):
    """The single record of `record_kind` in a bound batch; each totality row builds exactly one."""
    field = {
        "EvidenceSpan": "spans",
        "KnowledgeObject": "objects",
        "ObjectObservation": "observations",
        "Assertion": "assertions",
        "AssertionVersion": "versions",
        "AssertionSupport": "supports",
        "Passage": "passages",
        "Unit": "units",
        "RetrievalView": "views",
    }[record_kind]
    records = getattr(bound, field)
    assert len(records) == 1, f"{record_kind}: expected one record, got {len(records)}"
    return records[0]


def readable(registry, ref: base.NodeRef) -> str:
    """An identity-only endpoint has no stored label, so a statement names it by its canonical key."""
    return keys.canonical_key(registry, ref, instance=INSTANCE).readable


def object_id(registry, ref: base.NodeRef) -> str:
    """Identity comes from `keys.py` and nowhere else (CK2)."""
    return keys.knowledge_object(registry, ref, workspace_id=WORKSPACE, instance=INSTANCE).id


def column(record, name: str):
    """`attr.attr` walks records; `json_column:key` reads one key of a canonical-JSON column."""
    name, separator, json_key = name.partition(":")
    for part in name.split("."):
        record = getattr(record, part)
    if separator:
        return json.loads(record)[json_key]
    return record


# ------------------------------------------------------------------ the totality table (section 8.2)

SPEC_FIELDS = frozenset(
    {
        # Node
        "Node.id",
        "Node.type",
        "Node.domain",
        "Node.label",
        "Node.attrs",
        "Node.ts",
        "Node.provenance",
        "Node.acl",
        # Edge
        "Edge.src",
        "Edge.dst",
        "Edge.type",
        "Edge.family",
        "Edge.source",
        "Edge.rule",
        "Edge.weight",
        "Edge.statement",
        "Edge.unit_ref",
        "Edge.valid_from",
        "Edge.valid_to",
        "Edge.provenance",
        # Passage
        "Passage.id",
        "Passage.node_ref",
        "Passage.title",
        "Passage.text",
        "Passage.ts",
        "Passage.provenance",
        "Passage.acl",
        # Unit
        "Unit.id",
        "Unit.passage_id",
        "Unit.ordinal",
        "Unit.text",
        "Unit.embed_text",
        "Unit.mentions",
        "Unit.kind",
        "Unit.content_hash",
        # AliasCandidate
        "AliasCandidate.a",
        "AliasCandidate.b",
        "AliasCandidate.rule",
        "AliasCandidate.weight",
        "AliasCandidate.provenance",
        # Provenance
        "Provenance.source_system",
        "Provenance.uri",
        "Provenance.path",
        "Provenance.span",
        "Provenance.version",
        "Provenance.observed_at",
        "Provenance.parser",
    }
)


def node_records(world: World) -> dict:
    bound = world.bind(node_batch())
    return {"bound": bound}


def timed_node_records(world: World) -> dict:
    batch = base.EmissionBatch(
        nodes=(
            node_emission(
                ts=datetime(2026, 9, 13, 7, 0, tzinfo=UTC),
                ts_original="2026-09-13T07:00:00Z",
                ts_timezone="UTC",
                ts_precision="second",
            ),
        )
    )
    return {"bound": world.bind(batch)}


def edge_records(world: World) -> dict:
    return {"bound": world.bind(edge_batch())}


def windowed_edge_records(world: World) -> dict:
    batch = base.EmissionBatch(
        nodes=(node_emission(), service_emission()),
        edges=(
            edge_emission(
                predicate="WINDOWED_FIXTURE",
                valid_from=datetime(2026, 9, 10, tzinfo=UTC),
                valid_to=datetime(2026, 9, 11, tzinfo=UTC),
                window_precision="day",
            ),
        ),
    )
    return {"bound": world.bind(batch)}


def rule_edge_records(world: World) -> dict:
    batch = base.EmissionBatch(
        nodes=(node_emission(), service_emission()),
        edges=(
            edge_emission(
                source="rule",
                metadata_origin=None,
                rule="temporal_window",
                rule_evidence="within 5 minutes",
            ),
        ),
    )
    return {"bound": world.bind(batch)}


def passage_records(world: World) -> dict:
    batch = base.EmissionBatch(
        passages=(
            base.PassageEmission(
                key="p1", span=lines_span(1, 2), title="Incident report", ts=SOURCE_UPDATED_AT
            ),
        ),
        units=(base.UnitEmission(key="u1", passage="p1", ordinal=0, kind="sentence", span=lines_span(1, 2)),),
    )
    return {"bound": world.bind(batch)}


def alias_records(world: World) -> dict:
    batch = base.EmissionBatch(
        nodes=(node_emission(), node_emission(ref=incident_ref("INC-2"))),
        aliases=(
            base.AliasEmission(
                a=incident_ref(),
                b=incident_ref("INC-2"),
                rule="same_incident_key",
                support=(base.SupportEmission(spans=(lines_span(3, 3),)),),
            ),
        ),
    )
    return {"bound": world.bind(batch)}


def capture(world: World) -> dict:
    fetch = base.RawFetch(
        ref=base.ExternalRef(
            partition=PARTITION,
            artifact_kind="incident_export",
            external_id="INC-1",
            provider_revision="rev-7",
        ),
        data=DATA,
        content_type="text/plain",
        external_id="INC-1",
        canonical_uri=f"{INSTANCE}/incidents/INC-1",
        provider_revision="rev-7",
        source_updated_at=SOURCE_UPDATED_AT,
        source_timestamp_original="2026-09-14T08:30:00Z",
        source_timezone="UTC",
        source_precision="second",
        parser=base.ParserVersion(name="pager/json", version="1"),
    )
    observation = base.PolicyObservation(ref=fetch.ref, state="known", mode="restricted", allow_users=("u1",))
    captured = emit.capture_records(
        fetch,
        observation,
        connector=world.connector,
        workspace_id=WORKSPACE,
        source_id=SOURCE,
        raw_uri="raw://incidents/INC-1",
        observed_at=OBSERVED_AT,
        policy_expires_at=OBSERVED_AT + timedelta(days=1),
    )
    return {"captured": captured}


def node_of(records: dict, record_kind: str):
    return one(records["bound"], record_kind)


# (spec_field, build_records, record_kind, column, expected)
TOTALITY = [
    (
        "Node.id",
        node_records,
        "KnowledgeObject",
        "id",
        lambda w, r: node_of(r, "ObjectObservation").object_id,
    ),
    ("Node.type", node_records, "KnowledgeObject", "kind", lambda w, r: "incident_fixture"),
    (
        "Node.domain",
        node_records,
        "coverage",
        "nodes_by_family",
        lambda w, r: {"incident": 1},
    ),
    (
        "Node.label",
        node_records,
        "ObjectObservation",
        "attributes_json:label",
        lambda w, r: "Checkout is down",
    ),
    (
        "Node.attrs",
        node_records,
        "ObjectObservation",
        "attributes_json:attrs",
        lambda w, r: {"title": "Checkout is down", "severity": "sev1", "resolution": None},
    ),
    (
        "Node.ts",
        timed_node_records,
        "ObjectObservation",
        "valid_from",
        lambda w, r: datetime(2026, 9, 13, 7, 0, tzinfo=UTC),
    ),
    (
        "Node.provenance",
        node_records,
        "ObjectObservation",
        "span_id",
        lambda w, r: node_of(r, "EvidenceSpan").id,
    ),
    ("Node.acl", node_records, "EvidenceSpan", "policy_id", lambda w, r: w.policy.id),
    (
        "Edge.src",
        edge_records,
        "Assertion",
        "subject_id",
        lambda w, r: object_id(w.registry, incident_ref()),
    ),
    (
        "Edge.dst",
        edge_records,
        "Assertion",
        "object_id",
        lambda w, r: object_id(w.registry, service_ref()),
    ),
    ("Edge.type", edge_records, "Assertion", "predicate", lambda w, r: "AFFECTS_FIXTURE"),
    ("Edge.family", edge_records, "AssertionVersion", "family", lambda w, r: "deterministic"),
    ("Edge.source", edge_records, "AssertionVersion", "source", lambda w, r: "metadata"),
    ("Edge.rule", rule_edge_records, "AssertionVersion", "rule", lambda w, r: "temporal_window"),
    ("Edge.weight", edge_records, "AssertionVersion", "weight", lambda w, r: 1.0),
    (
        "Edge.statement",
        edge_records,
        "AssertionVersion",
        "statement",
        lambda w, r: (
            "incident fixture Checkout is down affects service " + readable(w.registry, service_ref())
        ),
    ),
    (
        "Edge.unit_ref",
        edge_records,
        "AssertionVersion",
        "unit_id",
        lambda w, r: next(unit.id for unit in r["bound"].units if unit.kind == "rendered_edge"),
    ),
    (
        "Edge.valid_from",
        windowed_edge_records,
        "AssertionVersion",
        "valid_from",
        lambda w, r: datetime(2026, 9, 10, tzinfo=UTC),
    ),
    (
        "Edge.valid_to",
        windowed_edge_records,
        "AssertionVersion",
        "valid_to",
        lambda w, r: datetime(2026, 9, 11, tzinfo=UTC),
    ),
    (
        "Edge.provenance",
        edge_records,
        "AssertionSupport",
        "span_id",
        lambda w, r: next(span.id for span in r["bound"].spans if span.locator_json.count('"start":3')),
    ),
    (
        "Passage.id",
        passage_records,
        "Passage",
        "id",
        lambda w, r: generation_passage_id(
            w.generation.id,
            w.revision.id,
            one(r["bound"], "EvidenceSpan").id,
            0,
            retrieval_view_id=None,
        ),
    ),
    ("Passage.node_ref", passage_records, "Passage", "view", lambda w, r: None),
    ("Passage.title", passage_records, "Passage", "title", lambda w, r: "Incident report"),
    (
        "Passage.text",
        passage_records,
        "Passage",
        "text",
        lambda w, r: "first line\nsecond line\n",
    ),
    ("Passage.ts", passage_records, "Passage", "span.revision_id", lambda w, r: w.revision.id),
    (
        "Passage.provenance",
        passage_records,
        "Passage",
        "span.id",
        lambda w, r: one(r["bound"], "EvidenceSpan").id,
    ),
    ("Passage.acl", passage_records, "Passage", "span.policy_id", lambda w, r: w.policy.id),
    (
        "Unit.id",
        passage_records,
        "Unit",
        "id",
        lambda w, r: one(r["bound"], "Unit").id,
    ),
    (
        "Unit.passage_id",
        passage_records,
        "Unit",
        "passage_id",
        lambda w, r: one(r["bound"], "Passage").id,
    ),
    ("Unit.ordinal", passage_records, "Unit", "ordinal", lambda w, r: 0),
    (
        "Unit.text",
        passage_records,
        "Unit",
        "text",
        lambda w, r: "first line\nsecond line\n",
    ),
    (
        "Unit.embed_text",
        passage_records,
        "Unit",
        "embed_text",
        lambda w, r: "first line\nsecond line\n",
    ),
    ("Unit.mentions", passage_records, "Unit", "mentions_json", lambda w, r: []),
    ("Unit.kind", passage_records, "Unit", "kind", lambda w, r: "sentence"),
    (
        "Unit.content_hash",
        passage_records,
        "Unit",
        "content_hash",
        lambda w, r: text_hash("first line\nsecond line\n"),
    ),
    (
        "AliasCandidate.a",
        alias_records,
        "Assertion",
        "predicate",
        lambda w, r: "SAME_OBJECT_AS",
    ),
    (
        "AliasCandidate.b",
        alias_records,
        "Assertion",
        "object_id",
        lambda w, r: max((obj.canonical_key, obj.kind, obj.id) for obj in r["bound"].objects)[2],
    ),
    (
        "AliasCandidate.rule",
        alias_records,
        "AssertionVersion",
        "rule",
        lambda w, r: "same_incident_key",
    ),
    ("AliasCandidate.weight", alias_records, "AssertionVersion", "weight", lambda w, r: 1.0),
    (
        "AliasCandidate.provenance",
        alias_records,
        "AssertionSupport",
        "span_id",
        lambda w, r: next(span.id for span in r["bound"].spans if span.locator_json.count('"start":3')),
    ),
    (
        "Provenance.source_system",
        capture,
        "Artifact",
        "connector_id",
        lambda w, r: w.connector.id,
    ),
    (
        "Provenance.uri",
        capture,
        "Artifact",
        "canonical_uri",
        lambda w, r: f"{INSTANCE}/incidents/INC-1",
    ),
    ("Provenance.path", capture, "Artifact", "external_id", lambda w, r: "INC-1"),
    (
        "Provenance.span",
        node_records,
        "EvidenceSpan",
        "locator_kind",
        lambda w, r: "file_lines",
    ),
    (
        "Provenance.version",
        capture,
        "ArtifactRevision",
        "content_hash",
        lambda w, r: hashlib.sha256(DATA).hexdigest(),
    ),
    # Review M7: the provider's instant, not the kit's receipt clock.
    (
        "Provenance.observed_at",
        capture,
        "ArtifactRevision",
        "source_updated_at",
        lambda w, r: SOURCE_UPDATED_AT,
    ),
    (
        "Provenance.parser",
        capture,
        "ArtifactRevision",
        "metadata_json:parser",
        lambda w, r: "pager/json@1",
    ),
]


def totality_record(records: dict, record_kind: str):
    if "captured" in records:
        return getattr(
            records["captured"], {"Artifact": "artifact", "ArtifactRevision": "revision"}[record_kind]
        )
    if record_kind == "coverage":
        return records["bound"].coverage
    return one(records["bound"], record_kind)


@pytest.mark.parametrize(
    ("spec_field", "build", "record_kind", "name", "expected"),
    TOTALITY,
    ids=[row[0] for row in TOTALITY],
)
def test_every_spec_section_3_field_lands_in_its_design_section_4_column(
    world, spec_field, build, record_kind, name, expected
) -> None:
    records = build(world)
    record = totality_record(records, record_kind)
    value = column(record, name)
    wanted = expected(world, records)
    if isinstance(value, str) and not isinstance(wanted, str):
        value = json.loads(value)
    assert value == wanted, spec_field


def test_the_totality_table_names_every_spec_section_3_field() -> None:
    assert {row[0] for row in TOTALITY} == SPEC_FIELDS
    assert len(TOTALITY) == len(SPEC_FIELDS) == 47


# ------------------------------------------------------------------ evidence classes (section 8.3)

DERIVATION_ROWS = [
    ("deterministic", "parser", None, "syntax_observed"),
    ("deterministic", "metadata", "catalog", "catalog_observed"),
    ("deterministic", "metadata", "declaration", "declared"),
    ("deterministic", "rule", None, "rule_derived"),
    ("deterministic", "access_history", None, "catalog_observed"),
    ("deterministic", "apm", None, "catalog_observed"),
    ("deterministic", "postmortem", None, "discussion_claim"),
    ("deterministic", "slack", None, "discussion_claim"),
    ("probabilistic", "similarity", None, "similarity_inferred"),
    ("probabilistic", "cooccurrence", None, "similarity_inferred"),
    ("deterministic", "reviewed", None, "human_verified"),
    ("probabilistic", "reviewed", None, "human_verified"),
]


@pytest.mark.parametrize(("family", "source", "origin", "expected"), DERIVATION_ROWS)
def test_evidence_class_follows_the_derivation_table(registry, family, source, origin, expected) -> None:
    assert emit.evidence_class(registry, family, source, origin) == expected
    assert EVIDENCE_CLASS_DERIVATION[(family, source, origin)] == expected


def test_evidence_class_reads_an_extension_source_class_from_the_registry(registry) -> None:
    """Ruling R40/R62/R63: the class travels with the registered source, not a built-in row."""
    assert (registry.evidence_source_definition("pager_pull").evidence_class) == "catalog_observed"
    assert emit.evidence_class(registry, "deterministic", "pager_pull", None) == "catalog_observed"
    with pytest.raises(emit.BindRefused) as refused:
        emit.evidence_class(registry, "probabilistic", "pager_pull", None)
    assert str(refused.value) == (
        "No evidence class for family=probabilistic source=pager_pull; "
        "the derivation table in the kit design section 4 is fixed"
    )


@pytest.mark.parametrize(
    ("family", "source"),
    [
        ("deterministic", "similarity"),
        ("probabilistic", "parser"),
        ("deterministic", "cooccurrence"),
        ("probabilistic", "metadata"),
    ],
)
def test_family_source_pairs_outside_the_table_are_refused(registry, family, source) -> None:
    with pytest.raises(emit.BindRefused) as refused:
        emit.evidence_class(registry, family, source, "catalog" if source == "metadata" else None)
    assert str(refused.value).startswith(f"No evidence class for family={family} source={source}")


def test_no_emission_yields_model_inferred(registry) -> None:
    assert "model_inferred" not in set(EVIDENCE_CLASS_DERIVATION.values())
    classes = {
        emit.evidence_class(registry, family, source, origin) for family, source, origin, _ in DERIVATION_ROWS
    }
    assert "model_inferred" not in classes


def test_a_connector_cannot_set_evidence_class(world) -> None:
    for record in (base.NodeEmission, base.EdgeEmission):
        assert "evidence_class" not in record.model_fields
    with pytest.raises(ValueError):
        base.NodeEmission(
            ref=incident_ref(),
            attrs={},
            span=lines_span(),
            source="parser",
            evidence_class="human_verified",
        )
    assert one(world.bind(node_batch()), "ObjectObservation").evidence_class == "catalog_observed"


# ------------------------------------------------------------------ the registry (R16, R39, m4)


def test_bind_refuses_a_registry_other_than_the_frozen_current_registry(world) -> None:
    other = Registry.with_builtins()
    other.freeze()
    context = emit.BindContext(
        registry=other,
        descriptor=world.descriptor,
        connector=world.connector,
        generation=world.generation,
        workspace_id=WORKSPACE,
        source_id=SOURCE,
        partition=PARTITION,
    )
    with pytest.raises(emit.BindRefused) as refused:
        emit.bind_batch(context, world.revision_input(registry=other), node_batch())
    assert str(refused.value) == (
        "Bind requires the frozen current registry that the knowledge model validates against"
    )


# The vocabulary every `REFUSALS` extension carries, and where the binder would read each name.
S1_FIXTURE_VOCABULARY = (
    ("object_kinds", "incident_fixture"),
    ("predicates", "AFFECTS_FIXTURE"),
    ("evidence_sources", "pager_feed"),
)


def s1_fixture_batch() -> base.EmissionBatch:
    """A batch naming every name of S1's `incident_extension`, so any absence refuses at bind."""
    subject = base.NodeRef(kind="incident_fixture", key={"tool": "pager", "incident_id": "INC-1"})
    return base.EmissionBatch(
        nodes=(
            base.NodeEmission(
                ref=subject,
                attrs={"title": "Checkout is down", "severity": "sev1"},
                span=lines_span(),
                source="pager_feed",
            ),
            service_emission(source="pager_feed", metadata_origin=None),
        ),
        edges=(
            base.EdgeEmission(
                subject=subject,
                predicate="AFFECTS_FIXTURE",
                object=service_ref(),
                family="deterministic",
                source="pager_feed",
                weight=1.0,
                support=(base.SupportEmission(spans=(lines_span(3, 3),)),),
            ),
        ),
    )


@pytest.mark.parametrize(("reason", "message", "action"), REFUSALS, ids=[row.id for row in REFUSALS])
def test_unregistered_or_undeclared_type_at_bind_is_refused(reason, message, action) -> None:
    """m4: for each of S1's registration refusals, the same input cannot reach emit (CK1).

    A refused registration adds nothing, so the names its extension carried stay unregistered and
    the binder refuses an emission that uses them. The one case that registers before it refuses
    (`duplicate_name`, whose first call succeeds) is carried by the other half of the same
    assertion: with the vocabulary present, the very same batch binds.
    """
    with use_registry(Registry.with_builtins()) as fresh:
        before = {section: _names(fresh, section) for section, _ in S1_FIXTURE_VOCABULARY}
        with pytest.raises(RegistrationError) as refused_registration:
            action(fresh)
        assert refused_registration.value.reason == reason
        absent = [name for section, name in S1_FIXTURE_VOCABULARY if name not in _names(fresh, section)]
        if not fresh.frozen:
            fresh.freeze()
        world = World(fresh)
        outcome = _bind_outcome(world, s1_fixture_batch())
        assert (outcome is not None) == bool(absent), (reason, absent, outcome)
        if absent:
            assert outcome == (
                f"{_LABEL[absent[0]]} {absent[0]!r} is not registered; "
                "register it with a TypeExtension before emitting"
            )
        else:
            # `duplicate_name`: the first registration stands and the refusal added nothing to it.
            assert {section: _names(fresh, section) for section, _ in S1_FIXTURE_VOCABULARY} != before


_LABEL = {
    "incident_fixture": "object kind",
    "AFFECTS_FIXTURE": "predicate",
    "pager_feed": "evidence source",
}


def _names(registry, section: str) -> frozenset[str]:
    return getattr(registry, section)()


def _bind_outcome(world: World, batch: base.EmissionBatch) -> str | None:
    """The refusal message, or `None` when the batch binds."""
    try:
        world.bind(batch)
    except emit.BindRefused as refused:
        return str(refused)
    return None


def test_a_kind_nothing_registered_is_refused_before_any_record_is_built(world) -> None:
    unregistered = base.NodeRef(kind="never_registered_kind", key={"tool": "p", "incident_id": "1"})
    with pytest.raises(UnregisteredName):
        world.registry.object_kind("never_registered_kind")
    with pytest.raises(emit.BindRefused) as refused:
        world.bind(base.EmissionBatch(nodes=(node_emission(ref=unregistered),)))
    assert str(refused.value) == (
        "object kind 'never_registered_kind' is not registered; "
        "register it with a TypeExtension before emitting"
    )


def test_an_undeclared_but_registered_type_is_refused(world) -> None:
    narrowed = World(world.registry, descriptor=descriptor(kinds=("service",)))
    with pytest.raises(emit.BindRefused) as refused:
        narrowed.bind(node_batch())
    assert str(refused.value) == ("Connector pager emits object kind 'incident_fixture' it does not declare")


def test_the_binder_checks_every_record_it_builds_against_the_registry(world, monkeypatch) -> None:
    """Ruling R39: `Registry.check_record` is the one vocabulary check, and bind calls it."""
    checked: list[str] = []
    real = type(world.registry).check_record

    def spy(self, record):
        checked.append(type(record).__name__)
        return real(self, record)

    monkeypatch.setattr(type(world.registry), "check_record", spy)
    bound = world.bind(edge_batch())
    # Every record kind `check_record` has a vocabulary rule for is passed to it as it is built.
    assert {"KnowledgeObject", "EvidenceSpan", "Assertion"} <= set(checked)
    assert checked.count("KnowledgeObject") == len(bound.objects)
    assert checked.count("EvidenceSpan") == len(bound.spans)
    for record in (*bound.objects, *bound.spans, *bound.assertions):
        real(world.registry, record)


# ------------------------------------------------------------------ direction and ownership (8.5)


def test_check_direction_and_ownership_is_the_check_the_binder_applies(world) -> None:
    """The kit (S4) and the binder call one function, so their messages cannot drift apart."""
    definition = emit.check_direction_and_ownership(
        world.registry, world.descriptor, "AFFECTS_FIXTURE", "incident_fixture", "service"
    )
    assert definition == world.registry.predicate("AFFECTS_FIXTURE")
    with pytest.raises(emit.BindRefused) as direct:
        emit.check_direction_and_ownership(
            world.registry, world.descriptor, "AFFECTS_FIXTURE", "service", "incident_fixture"
        )
    reversed_batch = base.EmissionBatch(
        nodes=(node_emission(), service_emission()),
        edges=(edge_emission(subject=service_ref(), object=incident_ref()),),
    )
    with pytest.raises(emit.BindRefused) as through_bind:
        world.bind(reversed_batch)
    assert str(through_bind.value) == str(direct.value)


def test_non_owner_family_edge_is_refused_with_the_developer_message(world) -> None:
    with pytest.raises(emit.BindRefused) as refused:
        emit.check_direction_and_ownership(world.registry, world.descriptor, "PROVIDES_API", "service", "api")
    assert str(refused.value) == (
        "pager (incident) cannot store PROVIDES_API: its owner families are service. "
        "Emit a ReverseViewHint for the view you observed, or an AliasEmission for an identity "
        "you can back with a rule."
    )


def test_reverse_direction_edge_is_refused_with_the_developer_message(world) -> None:
    with pytest.raises(emit.BindRefused) as refused:
        emit.check_direction_and_ownership(
            world.registry, world.descriptor, "AFFECTS_FIXTURE", "service", "incident_fixture"
        )
    assert str(refused.value) == (
        "AFFECTS_FIXTURE runs ['incident_fixture'] -> ['service']; this edge runs "
        "service -> incident_fixture, the reverse of its canonical direction. "
        "Swap subject and object if you own the fact, or emit a ReverseViewHint."
    )


def test_direction_is_checked_before_ownership(world) -> None:
    """Both fail for this edge; the more specific message wins (section 8.5)."""
    with pytest.raises(emit.BindRefused) as refused:
        emit.check_direction_and_ownership(world.registry, world.descriptor, "PROVIDES_API", "api", "service")
    assert "the reverse of its canonical direction" in str(refused.value)


def test_identity_predicate_is_refused_as_an_edge(world) -> None:
    with pytest.raises(emit.BindRefused) as refused:
        emit.check_direction_and_ownership(
            world.registry, world.descriptor, "SAME_OBJECT_AS", "incident_fixture", "incident_fixture"
        )
    assert str(refused.value) == (
        "SAME_OBJECT_AS is an identity predicate; emit an AliasEmission with its rule"
    )


def test_source_outside_sources_allowed_is_refused(world) -> None:
    with pytest.raises(emit.BindRefused) as refused:
        world.bind(
            base.EmissionBatch(
                nodes=(node_emission(), service_emission()),
                edges=(edge_emission(source="apm", metadata_origin=None),),
            )
        )
    assert str(refused.value) == (
        "AFFECTS_FIXTURE does not accept source apm; allowed: ['metadata', 'pager_pull', 'rule']"
    )


def test_no_builtin_predicate_admits_the_reviewed_source() -> None:
    """CK7 F2: `reviewed` is the reconciliation queue's source (spec 4.3), never a connector's.

    `evidence_class(registry, family, "reviewed", None)` is `human_verified` for both families, so
    any predicate that admitted the source let a connector store a human-verified edge that no
    human verified. None of the thirty-three built-ins admits it now, the identity one included.
    """
    builtins = Registry.with_builtins()
    names = sorted(builtins.predicates())
    assert len(names) == 33
    assert [name for name in names if "reviewed" in builtins.predicate(name).sources_allowed] == []
    # The source stays registered and keeps both derivation rows: spec 4.3's acceptance path writes
    # `human_verified` through `update_knowledge`, not through the binder (Task 12).
    assert "reviewed" in builtins.evidence_sources()
    assert EVIDENCE_CLASS_DERIVATION[("deterministic", "reviewed", None)] == "human_verified"
    assert EVIDENCE_CLASS_DERIVATION[("probabilistic", "reviewed", None)] == "human_verified"
    assert emit.evidence_class(builtins, "deterministic", "reviewed", None) == "human_verified"


def test_a_builtin_edge_with_source_reviewed_is_refused_at_bind(builtin_world) -> None:
    """The bind path, not only the table: a built-in predicate no longer accepts the source."""
    other = service_emission(ref=service_ref("payments"), attrs={"name": "payments"})
    depends_on = base.EdgeEmission(
        subject=service_ref(),
        predicate="DEPENDS_ON",
        object=service_ref("payments"),
        family="deterministic",
        source="reviewed",
        weight=1.0,
        support=(base.SupportEmission(spans=(lines_span(3, 3),)),),
    )
    with pytest.raises(emit.BindRefused) as refused:
        builtin_world.bind(
            base.EmissionBatch(nodes=(service_emission(), other), edges=(depends_on,)),
            mapping=base.TypeMapping(family="service"),
        )
    assert str(refused.value) == ("DEPENDS_ON does not accept source reviewed; allowed: ['metadata', 'rule']")


def test_an_extension_predicate_that_declares_reviewed_is_refused_anyway(reviewing_world) -> None:
    """CK7 F2's backstop: `sources_allowed` is the extension's to write, `reviewed` is not.

    Dropping the source from the built-ins is not enough on its own - an extension predicate may
    list any registered evidence source, and `reviewed` is registered so that the acceptance path
    can write it. This refusal is what keeps the class out of the binder for good.
    """
    with pytest.raises(emit.BindRefused) as refused:
        reviewing_world.bind(
            base.EmissionBatch(
                nodes=(node_emission(), service_emission()),
                edges=(edge_emission(source="reviewed", metadata_origin=None),),
            )
        )
    assert str(refused.value) == (
        "AFFECTS_FIXTURE: reviewed is the reconciliation queue's source (spec 4.3); "
        "emit the rule you derived the fact from"
    )


def test_windowed_predicate_without_a_window_is_unknown_and_an_unwindowed_window_is_refused(
    world,
) -> None:
    batch = base.EmissionBatch(
        nodes=(node_emission(), service_emission()),
        edges=(edge_emission(predicate="WINDOWED_FIXTURE"),),
    )
    version = one(world.bind(batch), "AssertionVersion")
    assert version.validity_kind == "unknown" and version.valid_from is None
    with pytest.raises(emit.BindRefused) as refused:
        world.bind(
            base.EmissionBatch(
                nodes=(node_emission(), service_emission()),
                edges=(edge_emission(valid_from=datetime(2026, 9, 10, tzinfo=UTC)),),
            )
        )
    assert str(refused.value) == "AFFECTS_FIXTURE is not windowed; drop valid_from/valid_to"


# ------------------------------------------------------------------ hints (section 9)


def hint_batch(predicate: str = "PROVIDES_API") -> base.EmissionBatch:
    return base.EmissionBatch(
        hints=(
            base.ReverseViewHint(
                predicate=predicate,
                subject=service_ref(),
                object=base.NodeRef(
                    kind="api",
                    key={
                        "service": "checkout",
                        "protocol": "http",
                        "api_version": "1",
                        "api_identity": "checkout-api",
                    },
                ),
                support=(base.SupportEmission(spans=(lines_span(3, 3),)),),
            ),
        )
    )


def test_reverse_view_hint_is_counted_and_writes_no_assertion(world) -> None:
    bound = world.bind(hint_batch())
    assert bound.coverage.hints == {"PROVIDES_API": 1}
    assert bound.assertions == () and bound.versions == () and bound.supports == ()
    assert len(bound.spans) == 1, "the hint's support spans are still verified (section 9 step 4)"


def test_hint_for_an_owned_predicate_is_told_to_emit_the_edge(world) -> None:
    with pytest.raises(emit.BindRefused) as refused:
        world.bind(
            base.EmissionBatch(
                hints=(
                    base.ReverseViewHint(
                        predicate="AFFECTS_FIXTURE",
                        subject=incident_ref(),
                        object=service_ref(),
                        support=(base.SupportEmission(spans=(lines_span(3, 3),)),),
                    ),
                )
            )
        )
    assert str(refused.value) == ("pager owns AFFECTS_FIXTURE; emit the edge instead of a reverse-view hint")


# ------------------------------------------------------------------ aliases (section 8.8)


def test_alias_endpoints_are_ordered_by_canonical_key_then_kind(world) -> None:
    bound = alias_records(world)["bound"]
    assertion = one(bound, "Assertion")
    objects = {obj.id: obj for obj in bound.objects}
    subject, target = objects[assertion.subject_id], objects[assertion.object_id]
    assert (subject.canonical_key, subject.kind) < (target.canonical_key, target.kind)
    assert assertion.predicate == "SAME_OBJECT_AS"


def test_guarded_alias_kind_pairs_stay_candidate(world) -> None:
    batch = base.EmissionBatch(
        nodes=(service_emission(), service_emission(ref=service_ref("payments"), span=lines_span(3, 3))),
        aliases=(
            base.AliasEmission(
                a=service_ref(),
                b=service_ref("payments"),
                rule="same_service",
                support=(base.SupportEmission(spans=(lines_span(3, 3),)),),
            ),
        ),
    )
    assert one(world.bind(batch), "AssertionVersion").status == "candidate"
    assert one(alias_records(world)["bound"], "AssertionVersion").status == "active"


def test_the_guarded_pairs_are_the_schema_kinds_with_resource(world) -> None:
    """Section 8.8 reads "any of `predicates.SCHEMA` with `resource`", not one hand-picked pair."""
    from hippo.knowledge.predicates import SCHEMA

    for kind in SCHEMA.split():
        assert frozenset({kind, "resource"}) in emit.GUARDED_ALIAS_PAIRS, kind
    assert frozenset({"service"}) in emit.GUARDED_ALIAS_PAIRS
    assert frozenset({"service", "repository"}) in emit.GUARDED_ALIAS_PAIRS
    assert frozenset({"incident_fixture"}) not in emit.GUARDED_ALIAS_PAIRS


def test_alias_version_is_rule_derived_with_rule_name_and_version(world) -> None:
    version = one(alias_records(world)["bound"], "AssertionVersion")
    assert version.evidence_class == "rule_derived"
    assert version.source == "rule" and version.rule == "same_incident_key"
    assert version.rule_version == "same_incident_key@1.0.0"
    assert version.weight == version.confidence == 1.0
    assert version.validity_kind == "observed_snapshot"


def test_an_alias_of_one_object_is_refused(world) -> None:
    with pytest.raises(emit.BindRefused) as refused:
        world.bind(
            base.EmissionBatch(
                nodes=(node_emission(),),
                aliases=(
                    base.AliasEmission(
                        a=incident_ref(),
                        b=incident_ref(),
                        rule="same_incident_key",
                        support=(base.SupportEmission(spans=(lines_span(3, 3),)),),
                    ),
                ),
            )
        )
    assert str(refused.value) == "An alias needs two distinct objects"


# ------------------------------------------------------------------ spans (section 8.4)


def test_file_lines_span_text_is_sliced_from_revision_bytes_with_terminators(world) -> None:
    span = one(world.bind(node_batch(span=lines_span(1, 2))), "EvidenceSpan")
    assert span.text == "first line\nsecond line\n"
    assert emit.verify_span(DATA, lines_span(3, 3), artifact=world.artifact) == "third line\n"


def test_a_line_past_the_last_line_is_refused(world) -> None:
    with pytest.raises(emit.BindRefused) as refused:
        emit.verify_span(DATA, lines_span(1, 9), artifact=world.artifact)
    assert str(refused.value) == (
        'Locator {"end":9,"kind":"file_lines","path":"incidents/INC-1.txt","start":1} '
        "is outside the revision's 3 lines"
    )


def test_a_file_lines_locator_naming_another_file_is_refused(world) -> None:
    other = base.SpanRef(
        locator_kind="file_lines",
        locator={"kind": "file_lines", "path": "other.txt", "start": 1, "end": 1},
    )
    with pytest.raises(emit.BindRefused) as refused:
        emit.verify_span(DATA, other, artifact=world.artifact)
    assert str(refused.value) == "A file_lines locator names a different file than its revision"


def test_span_text_that_differs_from_the_bytes_is_refused_without_quoting_it(world) -> None:
    with pytest.raises(emit.BindRefused) as refused:
        emit.verify_span(
            DATA, lines_span(1, 1, text="a secret the span does not hold"), artifact=world.artifact
        )
    message = str(refused.value)
    assert message == (
        "Span text differs from the revision bytes at file_lines "
        '{"end":1,"kind":"file_lines","path":"incidents/INC-1.txt","start":1}'
    )
    assert "secret" not in message and "first line" not in message


def test_field_span_is_resolved_in_the_json_document(registry) -> None:
    document = json.dumps({"incident": {"title": "Checkout is down", "tags": ["sev1", "paging"]}})
    data = document.encode("utf-8")
    world = World(registry, data=data, artifact_kind="incident_export")
    text = emit.verify_span(
        data,
        base.SpanRef(locator_kind="field", locator={"kind": "field", "field_path": "incident.title"}),
        artifact=world.artifact,
    )
    assert text == "Checkout is down"
    assert (
        emit.verify_span(
            data,
            base.SpanRef(locator_kind="field", locator={"kind": "field", "field_path": "incident.tags.1"}),
            artifact=world.artifact,
        )
        == "paging"
    )
    assert emit.verify_span(
        data,
        base.SpanRef(locator_kind="field", locator={"kind": "field", "field_path": "incident.tags"}),
        artifact=world.artifact,
    ) == canonical_json(["sev1", "paging"])
    with pytest.raises(emit.BindRefused) as refused:
        emit.verify_span(
            data,
            base.SpanRef(locator_kind="field", locator={"kind": "field", "field_path": "incident.gone"}),
            artifact=world.artifact,
        )
    assert str(refused.value) == "Field incident.gone is absent from the revision document"


def test_table_cell_span_is_resolved_in_the_csv_table(registry) -> None:
    data = b"id,title\nINC-1,Checkout is down\n"
    world = World(registry, data=data, artifact_kind="incident_export")
    cell = base.SpanRef(
        locator_kind="table_cell",
        locator={"kind": "table_cell", "table": 0, "row": 1, "column": 1, "heading_path": []},
    )
    assert emit.verify_span(data, cell, artifact=world.artifact) == "Checkout is down"
    with pytest.raises(emit.BindRefused) as refused:
        emit.verify_span(
            data,
            base.SpanRef(
                locator_kind="table_cell",
                locator={"kind": "table_cell", "table": 0, "row": 9, "column": 0, "heading_path": []},
            ),
            artifact=world.artifact,
        )
    assert str(refused.value) == "Cell (9, 0) is outside the revision table"


def test_locator_kind_without_a_verifier_is_refused(world) -> None:
    """Ruling R45: no built-in row, no extension `verifier`, no span."""
    section = base.SpanRef(
        locator_kind="section",
        locator={"kind": "section", "heading_path": ["Chapter"], "block_start": 0, "block_end": 1},
    )
    with pytest.raises(emit.BindRefused) as refused:
        emit.verify_span(DATA, section, artifact=world.artifact)
    assert str(refused.value) == (
        "Locator kind section has no byte verifier in the kit; spans of this kind cannot be emitted"
    )


def test_a_built_in_verifier_is_consulted_before_an_extension_verifier(world) -> None:
    assert set(emit.BUILTIN_VERIFIERS) == {"file_lines", "field", "table_cell"}
    event = base.SpanRef(locator_kind="incident_event", locator={"kind": "incident_event", "event_id": "E-1"})
    assert emit.verify_span(DATA, event, artifact=world.artifact) == "first line\n"


def test_verify_span_returns_the_text_the_binder_hashes(world) -> None:
    bound = world.bind(node_batch(span=lines_span(2, 2)))
    span = one(bound, "EvidenceSpan")
    assert span.text == emit.verify_span(DATA, lines_span(2, 2), artifact=world.artifact)
    assert span.text_hash == text_hash(span.text)


def test_span_and_artifact_share_the_revision_policy(world) -> None:
    """Ruling R48/B2: the span keeps the policy of the revision's first capture."""
    assert world.artifact.policy_id != world.policy.id
    span = one(world.bind(node_batch()), "EvidenceSpan")
    assert span.policy_id == world.policy.id


def test_identical_spans_collapse(world) -> None:
    batch = base.EmissionBatch(
        nodes=(node_emission(), node_emission(ref=incident_ref("INC-2"), span=lines_span()))
    )
    bound = world.bind(batch)
    assert len(bound.spans) == 1 and len(bound.observations) == 2


# ------------------------------------------------------------------ nodes (8.1 step 4)


def test_node_attrs_are_validated_by_the_kind_attribute_model(world) -> None:
    with pytest.raises(emit.BindRefused) as refused:
        world.bind(node_batch(attrs={"title": "t", "severity": "sev1", "unknown": "x"}))
    assert "incident_fixture" in str(refused.value)
    assert "unknown" in str(refused.value)


def test_node_ts_is_an_explicit_valid_from_and_a_missing_ts_is_a_snapshot(world) -> None:
    observation = one(timed_node_records(world)["bound"], "ObjectObservation")
    assert observation.validity_kind == "explicit_interval"
    assert observation.temporal_basis == "source_explicit"
    assert observation.temporal_precision == "second"
    assert observation.source_timestamp_original == "2026-09-13T07:00:00Z"
    plain = one(world.bind(node_batch()), "ObjectObservation")
    assert plain.validity_kind == "observed_snapshot"
    assert plain.temporal_basis == "observed" and plain.temporal_precision == "instant"
    assert plain.valid_from is None


def test_recorded_from_is_the_generation_instant_and_no_clock_is_read(world) -> None:
    observation = one(world.bind(node_batch()), "ObjectObservation")
    assert observation.recorded_from == world.generation.created_at == CREATED_AT
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(emit))
    tree.body = [node for node in tree.body if not _is_docstring(node)]
    code = ast.unparse(tree)
    for forbidden in ("datetime.now", "time.time", "utcnow", "httpx", "subprocess", "socket", "random"):
        assert forbidden not in code


def test_identity_only_endpoint_of_a_foreign_family_binds_its_object_and_a_minimal_observation(
    world,
) -> None:
    """Ruling R6 with R53/M6: the foreign endpoint is keyed by its own declared instance."""
    bound = world.bind(base.EmissionBatch(nodes=(service_emission(),)))
    observation = one(bound, "ObjectObservation")
    assert json.loads(observation.attributes_json) == {
        "key": keys.canonical_key(world.registry, service_ref(), instance=INSTANCE).readable
    }
    assert bound.units == () and bound.passages == ()
    assert one(bound, "KnowledgeObject").id == object_id(world.registry, service_ref())
    elsewhere = World(world.registry)
    other = elsewhere.bind(
        base.EmissionBatch(
            nodes=(
                service_emission(
                    ref=base.NodeRef(kind="service", key={"reference": "checkout"}, instance=CATALOG)
                ),
            )
        )
    )
    assert one(other, "KnowledgeObject").id == one(bound, "KnowledgeObject").id


def test_an_emitted_label_on_an_identity_only_endpoint_is_stored_and_read_by_the_statement(
    world,
) -> None:
    """Ruling R70: the label the connector emits is stored, so the statement stays re-derivable."""
    labelled = service_ref().replace(label="checkout")
    bound = world.bind(
        base.EmissionBatch(
            nodes=(node_emission(), service_emission(ref=labelled)),
            edges=(edge_emission(object=labelled),),
        )
    )
    endpoint = object_id(world.registry, labelled)
    observation = next(record for record in bound.observations if record.object_id == endpoint)
    assert json.loads(observation.attributes_json) == {
        "key": readable(world.registry, labelled),
        "label": "checkout",
    }
    rendered = [unit for unit in bound.units if unit.kind == "rendered_edge"]
    assert len(rendered) == 1
    assert rendered[0].text == "incident fixture Checkout is down affects service checkout"
    assert one(bound, "AssertionVersion").statement == rendered[0].text


def test_an_identity_only_endpoint_without_a_label_is_still_named_by_its_readable_key(world) -> None:
    """The behaviour R70 leaves alone: no emitted label, so the canonical key names the endpoint."""
    bound = world.bind(edge_batch())
    endpoint = object_id(world.registry, service_ref())
    observation = next(record for record in bound.observations if record.object_id == endpoint)
    assert json.loads(observation.attributes_json) == {"key": readable(world.registry, service_ref())}
    rendered = [unit for unit in bound.units if unit.kind == "rendered_edge"]
    assert len(rendered) == 1
    assert rendered[0].text == (
        "incident fixture Checkout is down affects service " + readable(world.registry, service_ref())
    )
    assert one(bound, "AssertionVersion").statement == rendered[0].text


# ------------------------------------------------------------------ units and passages (8.7)


def test_statement_unit_edge_reuses_its_unit_and_a_bare_edge_gets_a_rendered_edge_unit(world) -> None:
    bare = world.bind(edge_batch())
    rendered = [unit for unit in bare.units if unit.kind == "rendered_edge"]
    assert len(rendered) == 1
    assert rendered[0].text == (
        "incident fixture Checkout is down affects service " + readable(world.registry, service_ref())
    )
    assert rendered[0].template == f"edge_statement@{render.RENDER_RULE_VERSION}"
    reused = base.EmissionBatch(
        nodes=(node_emission(), service_emission()),
        passages=(base.PassageEmission(key="p1", span=lines_span(3, 3), title="Report"),),
        units=(
            base.UnitEmission(key="u1", passage="p1", ordinal=0, kind="statement", span=lines_span(3, 3)),
        ),
        edges=(edge_emission(unit="u1"),),
    )
    bound = world.bind(reused)
    statement_unit = next(unit for unit in bound.units if unit.kind == "statement")
    version = one(bound, "AssertionVersion")
    assert version.unit_id == statement_unit.id
    assert [unit.kind for unit in bound.units].count("rendered_edge") == 0


def test_each_rendered_fact_and_rendered_edge_gets_its_own_derived_passage(world) -> None:
    bound = world.bind(edge_batch())
    rendered = [unit for unit in bound.units if unit.kind in {"rendered_fact", "rendered_edge"}]
    assert len(rendered) == 2
    for unit in rendered:
        row = next(row for row in bound.passages if row.id == unit.passage_id)
        assert row.view is not None and row.view.view_kind == "projection"
        assert row.text == unit.text and unit.ordinal == 0
    assert len(bound.views) == len(bound.derived_records) == 2
    assert len(bound.derived_dependencies) >= 2


def test_derived_passage_is_a_projection_view_over_the_record_span(world) -> None:
    bound = world.bind(node_batch())
    row = one(bound, "Passage")
    view = one(bound, "RetrievalView")
    span = one(bound, "EvidenceSpan")
    assert view.span_id == span.id and view.source_revision_id == world.revision.id
    assert view.object_id == one(bound, "KnowledgeObject").id
    assert view.derivation_version == emit.BINDER_VERSION
    assert view.vector_profile == world.generation.embedding_profile
    assert row.view is view and row.title == "Checkout is down"
    derived = one(bound, "RetrievalView")
    assert derived is view
    record = bound.derived_records[0]
    assert record.view_kind == "projection" and record.rule_version == emit.BINDER_VERSION
    assert record.input_revision_ids == (world.revision.id,)


def test_verbatim_passage_text_is_its_span_text(world) -> None:
    bound = passage_records(world)["bound"]
    row = one(bound, "Passage")
    assert row.view is None
    assert row.text == one(bound, "EvidenceSpan").text == "first line\nsecond line\n"


def test_unit_mentions_are_sorted_unique_object_ids(world) -> None:
    batch = base.EmissionBatch(
        nodes=(node_emission(), service_emission()),
        passages=(base.PassageEmission(key="p1", span=lines_span(1, 2), title="Report"),),
        units=(
            base.UnitEmission(
                key="u1",
                passage="p1",
                ordinal=0,
                kind="sentence",
                span=lines_span(1, 2),
                mentions=(service_ref(), incident_ref(), incident_ref()),
            ),
        ),
    )
    bound = world.bind(batch)
    unit = next(unit for unit in bound.units if unit.kind == "sentence")
    mentions = json.loads(unit.mentions_json)
    assert mentions == sorted(set(mentions)) and len(mentions) == 2
    edge_unit = next(unit for unit in world.bind(edge_batch()).units if unit.kind == "rendered_edge")
    assert json.loads(edge_unit.mentions_json) == sorted(json.loads(edge_unit.mentions_json))
    fact_unit = next(unit for unit in world.bind(node_batch()).units if unit.kind == "rendered_fact")
    assert len(json.loads(fact_unit.mentions_json)) == 1


def test_unit_offsets_are_verified_within_the_unit_span(world) -> None:
    batch = base.EmissionBatch(
        passages=(base.PassageEmission(key="p1", span=lines_span(1, 2), title="Report"),),
        units=(
            base.UnitEmission(
                key="u1", passage="p1", ordinal=0, kind="sentence", span=lines_span(1, 2), start=0, end=10
            ),
        ),
    )
    unit = one(world.bind(batch), "Unit")
    assert unit.text == "first line"
    over = base.EmissionBatch(
        passages=(base.PassageEmission(key="p1", span=lines_span(1, 1), title="Report"),),
        units=(
            base.UnitEmission(
                key="u1", passage="p1", ordinal=0, kind="sentence", span=lines_span(1, 1), start=0, end=99
            ),
        ),
    )
    with pytest.raises(emit.BindRefused) as refused:
        world.bind(over)
    assert str(refused.value) == "Unit u1 offsets fall outside its span"


def test_passage_over_the_token_bound_is_refused(registry) -> None:
    data = ("x" * (base.PASSAGE_CHAR_BOUND + 10)).encode("utf-8") + b"\n"
    world = World(registry, data=data)
    batch = base.EmissionBatch(
        passages=(base.PassageEmission(key="p1", span=lines_span(1, 1), title="Long"),)
    )
    with pytest.raises(emit.BindRefused) as refused:
        world.bind(batch)
    # Review m6 / ruling R42 over the plan's literal "1500": the message interpolates the constant.
    assert str(refused.value) == (
        f"Passage p1 has {base.PASSAGE_CHAR_BOUND + 11} characters; "
        f"split it at {base.PASSAGE_CHAR_BOUND} before emitting"
    )


def test_passage_node_must_be_observed_on_the_passage_span(world) -> None:
    batch = base.EmissionBatch(
        nodes=(node_emission(span=lines_span(1, 1)),),
        passages=(
            base.PassageEmission(key="p1", span=lines_span(2, 2), title="Report", node=incident_ref()),
        ),
    )
    with pytest.raises(emit.BindRefused) as refused:
        world.bind(batch)
    assert str(refused.value) == (
        "Passage p1 names node incident_fixture, but that node is observed on a different span; "
        "emit the node on the passage's span"
    )


def test_passage_ts_other_than_node_or_source_time_is_refused(world) -> None:
    ok = base.EmissionBatch(
        passages=(base.PassageEmission(key="p1", span=lines_span(1, 1), title="R", ts=SOURCE_UPDATED_AT),)
    )
    assert len(world.bind(ok).passages) == 1
    bad = base.EmissionBatch(
        passages=(
            base.PassageEmission(
                key="p1",
                span=lines_span(1, 1),
                title="R",
                ts=datetime(2001, 1, 1, tzinfo=UTC),
            ),
        )
    )
    with pytest.raises(emit.BindRefused) as refused:
        world.bind(bad)
    assert "Passage p1" in str(refused.value) and "ts" in str(refused.value)


def test_passage_rows_satisfy_the_managed_passage_identity_and_text_rules(world) -> None:
    """`store/generations.py:1479-1545` without a store: id, binding and text."""
    bound = world.bind(edge_batch())
    for row in bound.passages:
        native = row.native_row()
        assert set(native) == {
            "id",
            "source_id",
            "generation_id",
            "artifact_revision_id",
            "span_id",
            "retrieval_view_id",
            "embedding_profile",
            "ordinal",
            "title",
            "text",
        }
        assert native["id"] == generation_passage_id(
            world.generation.id,
            native["artifact_revision_id"],
            native["span_id"],
            native["ordinal"],
            retrieval_view_id=native["retrieval_view_id"],
        )
        assert native["source_id"] == SOURCE
        assert native["generation_id"] == world.generation.id
        assert native["embedding_profile"] == world.generation.embedding_profile
        view = row.view
        assert native["text"] == (view.text if view else row.span.text)
        if view is not None:
            assert view.span_id == native["span_id"]
            assert view.source_revision_id == native["artifact_revision_id"]
            assert view.vector_profile == world.generation.embedding_profile
    ordinals = [row.native_row()["ordinal"] for row in bound.passages]
    assert ordinals == sorted(ordinals)


# ------------------------------------------------------------------ versions and merging (8.6)


def test_each_support_emission_is_one_derivation_group(world) -> None:
    batch = base.EmissionBatch(
        nodes=(node_emission(), service_emission()),
        edges=(
            edge_emission(
                support=(
                    base.SupportEmission(spans=(lines_span(1, 1), lines_span(2, 2))),
                    base.SupportEmission(spans=(lines_span(3, 3),)),
                )
            ),
        ),
    )
    bound = world.bind(batch)
    groups = {support.derivation_group for support in bound.supports}
    assert len(groups) == 2 and len(bound.supports) == 3
    first = sorted(
        support.span_id for support in bound.supports if support.derivation_group == sorted(groups)[0]
    )
    expected = text_hash(canonical_json(sorted(first)))[:32]
    assert expected in groups


def test_one_fact_with_two_statements_in_one_batch_is_refused(world) -> None:
    batch = base.EmissionBatch(
        nodes=(node_emission(), service_emission()),
        edges=(
            edge_emission(source_statement="first statement"),
            edge_emission(
                source_statement="second statement",
                support=(base.SupportEmission(spans=(lines_span(2, 2),)),),
            ),
        ),
    )
    with pytest.raises(emit.BindRefused) as refused:
        world.bind(batch)
    message = str(refused.value)
    assert message.startswith("Edge AFFECTS_FIXTURE ")
    assert message.endswith(
        "is emitted twice with different statements; emit one EdgeEmission with two support groups"
    )


def test_two_edges_with_the_same_statement_collapse_into_one_version(world) -> None:
    batch = base.EmissionBatch(
        nodes=(node_emission(), service_emission()),
        edges=(
            edge_emission(),
            edge_emission(support=(base.SupportEmission(spans=(lines_span(2, 2),)),)),
        ),
    )
    bound = world.bind(batch)
    assert len(bound.versions) == 1
    assert len({support.derivation_group for support in bound.supports}) == 2


def statement_batch(text: str) -> base.EmissionBatch:
    return base.EmissionBatch(
        nodes=(node_emission(), service_emission()),
        edges=(edge_emission(source_statement=text),),
    )


def test_merge_bound_collapses_equal_records_and_keeps_the_first_statement(registry) -> None:
    """Section 8.6: one version id, two statements; the lexically smallest revision wins."""
    first = World(registry, data=DATA).bind(statement_batch("alpha statement"))
    second = World(registry, data=DATA + b"more\n").bind(statement_batch("beta statement"))
    versions = {version.id for version in first.versions}
    assert versions == {version.id for version in second.versions}
    merged = emit.merge_bound([first, second])
    assert len(merged.versions) == 1
    kept = merged.versions[0]
    ordering = sorted(
        (bound.revision_ids[0], min(s.derivation_group for s in bound.supports), bound)
        for bound in (first, second)
    )
    assert kept.statement == ordering[0][2].versions[0].statement
    assert {(s.span_id, s.derivation_group) for s in merged.supports} == {
        (s.span_id, s.derivation_group) for s in (*first.supports, *second.supports)
    }
    assert merged.coverage.edges == 2


def test_merge_bound_refuses_unequal_records_with_one_id(world) -> None:
    """A `Unit` id hashes its text, not its mentions, so the same id must hold the same row."""

    def mention_batch(mentions):
        return base.EmissionBatch(
            nodes=(node_emission(), service_emission()),
            passages=(base.PassageEmission(key="p1", span=lines_span(1, 1), title="Report"),),
            units=(
                base.UnitEmission(
                    key="u1",
                    passage="p1",
                    ordinal=0,
                    kind="sentence",
                    span=lines_span(1, 1),
                    mentions=mentions,
                ),
            ),
        )

    first = world.bind(mention_batch((incident_ref(),)))
    second = world.bind(mention_batch(()))
    sliced = [unit for unit in first.units if unit.kind == "sentence"]
    assert [unit.id for unit in sliced] == [unit.id for unit in second.units if unit.kind == "sentence"]
    with pytest.raises(emit.BindRefused) as refused:
        emit.merge_bound([first, second])
    assert str(refused.value).startswith("Two revisions bind Unit ")
    assert str(refused.value).endswith("with different contents")


# ------------------------------------------------------------------ coverage, failures, determinism


def test_parse_failures_are_counted_per_family_parser_and_dialect(world) -> None:
    batch = base.EmissionBatch(
        failures=(
            base.ParseFailure(
                family="incident",
                reason="unreadable_json",
                parser=base.ParserVersion(name="pager/json", version="1"),
                count=2,
            ),
            base.ParseFailure(family="incident", reason="unreadable_json", dialect="postgres"),
        )
    )
    bound = world.bind(batch)
    assert bound.coverage.failures == {
        "incident|pager/json@1|-": 2,
        "incident|-|postgres": 1,
    }
    assert bound.coverage.to_json()["failures"] == dict(sorted(bound.coverage.failures.items()))


def test_bind_batch_is_deterministic(world) -> None:
    batch = edge_batch()
    first, second = world.bind(batch), world.bind(batch)
    assert first == second
    assert [record.id for record in first.spans] == [record.id for record in second.spans]


def test_evidence_members_cover_exactly_the_generation_scoped_records(world) -> None:
    bound = world.bind(edge_batch())
    expected = (
        {("EvidenceSpan", record.id) for record in bound.spans}
        | {("ObjectObservation", record.id) for record in bound.observations}
        | {("AssertionVersion", record.id) for record in bound.versions}
        | {("AssertionSupport", record.id) for record in bound.supports}
        | {("Unit", record.id) for record in bound.units}
        | {("RetrievalView", record.id) for record in bound.views}
        | {("DerivedRecord", record.id) for record in bound.derived_records}
        | {("DerivedDependency", record.id) for record in bound.derived_dependencies}
    )
    assert {(member.record_kind, member.record_id) for member in bound.evidence_members} == expected
    kinds = {member.record_kind for member in bound.evidence_members}
    assert "KnowledgeObject" not in kinds and "Assertion" not in kinds
    assert all(member.generation_id == world.generation.id for member in bound.evidence_members)


# ------------------------------------------------------------------ capture records (8.9)


def test_capture_records_map_fetch_and_policy_onto_artifact_revision_and_policy(world) -> None:
    captured = capture(world)["captured"]
    assert captured.artifact.connector_id == world.connector.id
    assert captured.artifact.provider_instance == INSTANCE
    assert captured.artifact.kind == "incident_export"
    assert captured.artifact.policy_id == captured.policy.id
    assert captured.revision.observed_at == OBSERVED_AT
    assert captured.revision.source_updated_at == SOURCE_UPDATED_AT
    assert captured.revision.lifecycle == "active"
    metadata = json.loads(captured.revision.metadata_json)
    assert metadata == {"content_type": "text/plain", "parser": "pager/json@1"}
    assert captured.policy.origin == "provider"
    assert captured.policy.scope_key == f"connector:{world.connector.id}:incident_export:INC-1"
    assert captured.policy.expires_at == OBSERVED_AT + timedelta(days=1)
    # Ruling R44/R61: the provider principal is mapped to the local id before it is stored.
    assert captured.policy.allow_users == ("local-u1",)


def test_unknown_policy_observation_is_stored_as_mode_unknown(world) -> None:
    observation = base.PolicyObservation(
        ref=base.ExternalRef(partition=PARTITION, artifact_kind="incident_export", external_id="INC-1"),
        state="unknown",
    )
    policy = emit.policy_record(
        observation,
        connector=world.connector,
        workspace_id=WORKSPACE,
        observed_at=OBSERVED_AT,
        expires_at=OBSERVED_AT + timedelta(days=1),
    )
    assert policy.mode == "unknown"
    assert policy.allow_users == () and policy.deny_users == ()


def test_provider_policy_always_carries_its_expiry(world) -> None:
    observation = base.PolicyObservation(
        ref=base.ExternalRef(partition=PARTITION, artifact_kind="incident_export", external_id="INC-1"),
        state="known",
        mode="workspace",
    )
    policy = emit.policy_record(
        observation,
        connector=world.connector,
        workspace_id=WORKSPACE,
        observed_at=OBSERVED_AT,
        expires_at=OBSERVED_AT + timedelta(days=1),
    )
    assert policy.expires_at is not None and policy.expires_at > policy.verified_at
    assert policy.origin == "provider"


def test_a_fetch_and_policy_for_different_artifacts_are_refused(world) -> None:
    fetch_ref = base.ExternalRef(partition=PARTITION, artifact_kind="incident_export", external_id="INC-1")
    other_ref = base.ExternalRef(partition=PARTITION, artifact_kind="incident_export", external_id="INC-2")
    fetch = base.RawFetch(
        ref=fetch_ref,
        data=DATA,
        content_type="text/plain",
        external_id="INC-1",
        canonical_uri=f"{INSTANCE}/incidents/INC-1",
    )
    with pytest.raises(emit.BindRefused) as refused:
        emit.capture_records(
            fetch,
            base.PolicyObservation(ref=other_ref, state="unknown"),
            connector=world.connector,
            workspace_id=WORKSPACE,
            source_id=SOURCE,
            raw_uri="raw://x",
            observed_at=OBSERVED_AT,
            policy_expires_at=OBSERVED_AT + timedelta(days=1),
        )
    assert str(refused.value) == "Policy and fetch name different artifacts"


# ------------------------------------------------------------------ the module's own rules


def test_bind_refused_is_the_contract_error_keys_refusals_inherit(world) -> None:
    assert issubclass(emit.BindRefused, base.ContractError)
    assert issubclass(keys.KeyPartsRefused, emit.BindRefused)
    assert emit.BINDER_VERSION == "cdk-emit-v1"


def test_the_binder_never_constructs_a_knowledge_object_itself() -> None:
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(emit))
    calls = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    attribute_calls = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    assert "KnowledgeObject" not in calls and "KnowledgeObject" not in attribute_calls


# ------------------------------------------------------------------ what S3, S4 and S6 require


def signature_of(function) -> str:
    import inspect

    return f"{function.__name__}{inspect.signature(function)}"


def test_the_surface_s3_s4_and_s6_require_from_s2_is_present_by_name() -> None:
    """The "requires from S2" items of the S3, S4 and S6 plans that name `emit` or `render`.

    S3 section 3, S4 R-S2-3 and R-S2-4 to R-S2-9 (with ruling R63's registry argument), S6 R-S2-4,
    R-S2-5 and R-S2-6. A rename here breaks a sibling slice, so the names are pinned, not implied.
    """
    for name in (
        "bind_batch",
        "merge_bound",
        "capture_records",
        "policy_record",
        "verify_span",
        "check_direction_and_ownership",
        "evidence_class",
        "BindContext",
        "BoundBatch",
        "BoundPassageRow",
        "CapturedRevision",
        "EmissionCoverage",
        "BindRefused",
        "BINDER_VERSION",
    ):
        assert hasattr(emit, name), f"S3/S4 require emit.{name}"
    for name in ("render_label", "render_facts", "unit_text", "RENDER_RULE_VERSION"):
        assert hasattr(render, name), f"S4 R-S2-3 requires render.{name}"
    assert signature_of(emit.evidence_class) == (
        "evidence_class(registry: 'Registry', family: 'str', source: 'str', "
        "metadata_origin: 'str | None' = None) -> 'str'"
    )
    assert signature_of(emit.verify_span) == (
        "verify_span(data: 'bytes', span: 'SpanRef', *, artifact: 'k.Artifact') -> 'str'"
    )
    assert signature_of(emit.check_direction_and_ownership) == (
        "check_direction_and_ownership(registry: 'Registry', descriptor: 'ConnectorDescriptor', "
        "predicate: 'str', subject_kind: 'str', object_kind: 'str') -> 'PredicateDefinition'"
    )
    assert signature_of(emit.policy_record) == (
        "policy_record(policy: 'PolicyObservation', *, connector: 'k.Connector', "
        "workspace_id: 'str', observed_at: 'datetime', expires_at: 'datetime') -> 'k.AccessPolicy'"
    )
    assert signature_of(emit.capture_records) == (
        "capture_records(fetch: 'RawFetch', policy: 'PolicyObservation', *, "
        "connector: 'k.Connector', workspace_id: 'str', source_id: 'str', raw_uri: 'str', "
        "observed_at: 'datetime', policy_expires_at: 'datetime') -> 'CapturedRevision'"
    )
    assert signature_of(emit.bind_batch) == (
        "bind_batch(context: 'BindContext', revision: 'RevisionInput', batch: 'EmissionBatch') "
        "-> 'BoundBatch'"
    )
