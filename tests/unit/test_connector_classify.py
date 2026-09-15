"""Classification on connect: declaration, then content, then name, with `custom/unclassified` counted.

Plan `ai_docs/plans/cdk-s2-contract.md` section 5 and the design's section 2. The classifier is a pure
function of the descriptor, the configuration and the sampled bytes: no socket, no HTTP client, no
Ollama, no subprocess and no clock.
"""

import json
import socket
import subprocess
import time
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

import hippo.ollama
from hippo.connectors import base, classify
from hippo.ingest import readers
from hippo.knowledge.contract import Text
from hippo.knowledge.locators import LocatorBase
from hippo.knowledge.registry import (
    CUSTOM_FAMILY,
    LocatorKindDefinition,
    ObjectKindDefinition,
    TypeExtension,
    extension_scope,
)


class IncidentAttributes(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    title: str


class IncidentEventLocator(LocatorBase):
    kind: Literal["incident_event"] = "incident_event"
    event_id: Text


class FolderConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    root: str = "/srv/exports"


def incident_extension() -> TypeExtension:
    return TypeExtension(
        object_kinds=(
            ObjectKindDefinition(
                name="incident_fixture",
                family="incident",
                key_template=("tool", "incident_id"),
                key_prefix="incx",
                attrs_model=IncidentAttributes,
                label_template="{title}",
            ),
        ),
        artifact_kinds=("incident_export",),
        locator_kinds=(LocatorKindDefinition(name="incident_event", model=IncidentEventLocator),),
    )


@pytest.fixture
def registry():
    with extension_scope() as scoped:
        scoped.register(incident_extension())
        scoped.freeze()
        yield scoped


def descriptor(**changes) -> base.ConnectorDescriptor:
    value = base.ConnectorDescriptor(
        name="local_folder",
        version="1",
        families=("prose", "code", "db", "service"),
        kinds=(),
        predicates=(),
        artifact_kinds=("file",),
        locator_kinds=("file_lines",),
        capabilities=base.ConnectorCapabilities(inventory=True),
        config_model=FolderConfig,
        credentials=(),
        parsers=(),
        extension=TypeExtension(),
    )
    return value.replace(**changes) if changes else value


def item(path: str, text: str = "", *, partition: str = "exports", data: bytes | None = None, **changes):
    return classify.SampledItem(
        partition=partition, path=path, data=text.encode("utf-8") if data is None else data, **changes
    )


def spec(**changes) -> base.ClassifierSpec:
    return classify.classifier_spec(**changes)


def run(items, *, registry, spec_=None, kinds=(), attributes=(), descriptor_=None) -> base.Classification:
    return classify.classify(
        descriptor_ or descriptor(),
        FolderConfig(),
        items,
        registry,
        spec=spec_ or spec(),
        capabilities=base.ConnectorCapabilities(inventory=True),
        kinds=kinds,
        attributes=attributes,
    )


ADR = """# Title

## Status
Accepted

## Context
We need a store.

## Decision
LadybugDB.

## Consequences
One backend more.
"""
PRD = "# P\n\n## Problem\nx\n\n## Goals\nx\n\n## Requirements\nx\n\n## Non-goals\nx\n"
RUNBOOK = "# R\n\n## Prerequisites\nx\n\n## Steps\nx\n\n## Verification\nx\n\n## Rollback\nx\n"
POSTMORTEM = (
    "# P\n\n## Summary\nx\n\n## Impact\nx\n\n## Timeline\nx\n\n## Root cause\nx\n\n## Action items\nx\n"
)
DDL = "CREATE TABLE orders (id int);\nALTER TABLE orders ADD COLUMN total numeric;\n"
NDJSON = '{"id": 1, "title": "a"}\n{"id": 2, "title": "b"}\n'


# ------------------------------------------------------------------ the order of the rules


def test_declaration_wins_over_content_and_name() -> None:
    declared = spec(
        declarations=(
            base.PathDeclaration(pattern="docs/adr/*", family="prose", template="adr"),
            base.PathDeclaration(pattern="migrations/*.sql", family="db", dialect="postgres"),
        ),
        sql_dialects=("postgres",),
    )
    decision = classify.classify_item(item("docs/adr/0001-store.md", DDL), declared)
    assert (decision.family, decision.template) == ("prose", "adr")
    assert decision.evidence.rule == "declaration"
    assert decision.evidence.detector == "declaration"
    assert not decision.unclassified
    migration = classify.classify_item(item("migrations/001_init.sql", "-- not sql at all (("), declared)
    assert (migration.family, migration.dialect) == ("db", "postgres")
    undeclared = classify.classify_item(item("docs/adr/0001-store.md", DDL), spec())
    assert undeclared.evidence.rule == "name", "without the declaration the name rule decides"
    assert undeclared.template is None


def test_declared_tabular_shape_falls_through_when_the_bytes_are_not_tabular() -> None:
    declared = spec(
        declarations=(
            base.PathDeclaration(pattern="exports/*.md", family="db", kind="table", shape="tabular"),
        )
    )
    tabular = classify.classify_item(item("exports/rows.md", NDJSON), declared)
    assert (tabular.family, tabular.kind) == ("db", "table")
    assert tabular.evidence.rule == "declaration"
    prose = classify.classify_item(item("exports/notes.md", "Just a note.\n"), declared)
    assert prose.family == "prose"
    assert prose.evidence.rule == "name"
    assert "declared_tabular_shape_missing" in prose.warnings


def test_sql_ddl_content_wins_over_the_code_name_in_a_declared_dialect() -> None:
    decision = classify.classify_item(item("scripts/migrate.py", DDL), spec(sql_dialects=("postgres",)))
    assert decision.family == "db"
    assert decision.dialect == "postgres"
    assert decision.evidence.rule == "content"
    assert decision.evidence.detector == "sqlglot.ddl:postgres"
    assert classify.classify_item(item("scripts/migrate.py", DDL), spec()).family == "code"


def test_prose_that_parses_as_select_is_not_database_content() -> None:
    decision = classify.classify_item(
        item("docs/guide.md", "Select a source from the list.\n"), spec(sql_dialects=("postgres",))
    )
    assert decision.family == "prose"
    decision = classify.classify_item(
        item("docs/query.sql", "SELECT id FROM orders;\n"), spec(sql_dialects=("postgres",))
    )
    assert decision.family == "code", "a query without DDL is not a database schema"


def test_sqlglot_command_fallback_is_not_a_successful_parse() -> None:
    decision = classify.classify_item(
        item("scripts/vacuum.sql", "VACUUM FULL orders;\n"), spec(sql_dialects=("postgres",))
    )
    assert decision.family == "code"
    assert decision.evidence.rule == "name"


def test_openapi_and_asyncapi_headers_classify_as_service_api() -> None:
    for text in (
        "openapi: 3.0.0\npaths: {}\n",
        "# a comment\n\nasyncapi: 2.6.0\n",
        "swagger: '2.0'\n",
        json.dumps({"openapi": "3.0.0", "paths": {}}),
    ):
        decision = classify.classify_item(item("contracts/orders.yaml", text), spec())
        assert (decision.family, decision.kind) == ("service", "api"), text
        assert decision.evidence.detector == "api.header"


def test_backstage_catalog_and_kubernetes_manifests_classify_as_service() -> None:
    catalog = classify.classify_item(
        item(
            "services/checkout/catalog-info.yaml",
            "apiVersion: backstage.io/v1alpha1\nkind: Component\nmetadata:\n  name: checkout\n",
        ),
        spec(),
    )
    assert (catalog.family, catalog.kind) == ("service", "service")
    assert catalog.evidence.detector == "backstage.catalog"
    manifest = classify.classify_item(
        item("deploy/checkout.yaml", "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: checkout\n"),
        spec(),
    )
    assert manifest.family == "service"
    assert manifest.evidence.detector == "k8s.manifest"
    json_manifest = classify.classify_item(
        item("deploy/checkout.json", json.dumps({"apiVersion": "apps/v1", "kind": "Deployment"})), spec()
    )
    assert json_manifest.family == "service"


@pytest.mark.parametrize(
    ("template", "text"), [("adr", ADR), ("prd", PRD), ("runbook", RUNBOOK), ("postmortem", POSTMORTEM)]
)
def test_heading_signatures_select_adr_prd_runbook_and_postmortem(template: str, text: str) -> None:
    decision = classify.classify_item(item("docs/note.md", text), spec())
    assert decision.family == "prose"
    assert decision.template == template
    assert decision.evidence.detector == "heading.signature"
    plain = classify.classify_item(item("docs/note.md", "# Title\n\n## Notes\nx\n"), spec())
    assert plain.template is None


@pytest.mark.parametrize(
    ("path", "text", "detector"),
    [
        ("exports/rows.txt", NDJSON, "tabular.ndjson"),
        ("exports/rows.txt", json.dumps([{"id": 1}, {"id": 2}]), "tabular.json_array"),
        ("exports/rows.txt", "id,title\n1,a\n2,b\n", "tabular.csv"),
    ],
)
def test_tabular_shape_without_a_declared_kind_is_unclassified_with_a_warning(
    path: str, text: str, detector: str
) -> None:
    decision = classify.classify_item(item(path, text), spec())
    assert decision.unclassified
    assert decision.kind is None
    assert decision.evidence.detector == detector
    assert decision.evidence.outcome == base.UNCLASSIFIED
    assert "tabular_without_declared_kind" in decision.warnings


def test_name_rules_call_readers_lang_of_code_and_prose_names() -> None:
    code = classify.classify_item(item("src/hippo/cli.py", "x = 1\n"), spec())
    assert code.family == "code"
    assert code.evidence.detector == "readers.lang_of"
    assert readers.lang_of("src/hippo/cli.py") == "python"
    prose = classify.classify_item(item("docs/readme.md", "Hello.\n"), spec())
    assert prose.family == "prose"
    assert prose.evidence.detector == "readers.is_plain_prose_name"
    assert readers.is_plain_prose_name("docs/readme.md")
    named = [
        name
        for name in (
            f"x{suffix}" if suffix.startswith(".") else f"x.{suffix}" for suffix in readers.CODE_EXTENSIONS
        )
        if readers.is_code_name(name) and readers.lang_of(name) is None
    ]
    assert named, "a code extension with no language proves the second name rule"
    only_code_name = classify.classify_item(item(f"src/{named[0]}", "int main() {}\n"), spec())
    assert only_code_name.family == "code"
    assert only_code_name.evidence.detector == "readers.is_code_name"


def test_binary_bytes_are_unclassified_and_counted(registry) -> None:
    binary = item("exports/logo.bin", data=b"\x00\x01\x02binary\x00")
    decision = classify.classify_item(binary, spec())
    assert decision.unclassified
    assert decision.family == CUSTOM_FAMILY
    assert decision.evidence.detector == "readers.is_probably_binary"
    assert readers.is_probably_binary(binary.data)
    classification = run([binary, item("docs/readme.md", "Hello.\n")], registry=registry)
    partition = classification.partitions[0]
    assert partition.counts[base.UNCLASSIFIED] == 1
    assert partition.counts["prose"] == 1
    assert partition.sample_count == 2


def test_nothing_decided_is_unclassified() -> None:
    decision = classify.classify_item(item("exports/notes", "one sentence, no suffix\n"), spec())
    assert decision.unclassified
    assert decision.evidence.rule == "unclassified"
    assert decision.evidence.detector == "none"


# ------------------------------------------------------------------ provider record types


def test_unmapped_provider_type_is_custom_unclassified_and_counted(registry) -> None:
    mapped = base.KindMapping(provider_type="incident", kind="incident_fixture")
    items = [
        item("incident", "{}", provider_type="incident"),
        item("page", "{}", provider_type="page"),
    ]
    classification = run(
        items,
        registry=registry,
        kinds=(mapped,),
        descriptor_=descriptor(families=("incident",), kinds=("incident_fixture",)),
    )
    partition = classification.partitions[0]
    assert partition.family == "incident"
    assert partition.counts[base.UNCLASSIFIED] == 1
    assert partition.counts["incident"] == 1
    outcomes = {evidence.subject: evidence.outcome for evidence in partition.evidence}
    assert outcomes["page"] == base.UNCLASSIFIED
    assert outcomes["incident"] == "incident/incident_fixture"
    assert {evidence.rule for evidence in partition.evidence} == {"descriptor", "unclassified"}


def test_unregistered_mapped_kind_returns_no_classification(registry) -> None:
    with pytest.raises(base.RegistrationRequired) as error:
        run(
            [item("outage", "{}", provider_type="outage")],
            registry=registry,
            kinds=(base.KindMapping(provider_type="outage", kind="outage"),),
            descriptor_=descriptor(families=("incident",)),
        )
    assert error.value.kinds == ("outage",)
    assert "outage" in error.value.skeleton


# ------------------------------------------------------------------ the classification record


def test_every_decision_names_its_rule_and_detector(registry) -> None:
    items = [
        item("docs/adr/0001.md", ADR),
        item("src/hippo/cli.py", "x = 1\n"),
        item("exports/rows.csv", "id,title\n1,a\n"),
        item("exports/logo.bin", data=b"\x00\x00binary"),
    ]
    classification = run(items, registry=registry, spec_=spec(sql_dialects=("postgres",)))
    partition = classification.partitions[0]
    assert len(partition.evidence) == len(items)
    assert [evidence.subject for evidence in partition.evidence] == sorted(entry.path for entry in items)
    for evidence in partition.evidence:
        assert evidence.rule in {"descriptor", "declaration", "content", "name", "unclassified"}
        assert evidence.detector
        assert evidence.level in {"family", "kind", "attribute"}
        assert evidence.outcome


def test_partition_family_is_the_agreed_family_then_the_descriptors_own(registry) -> None:
    agreed = run([item("a/one.md", "x\n"), item("a/two.md", "y\n", partition="a")], registry=registry)
    assert {partition.family for partition in agreed.partitions} == {"prose"}
    mixed = run([item("docs/readme.md", "x\n"), item("src/cli.py", "x = 1\n")], registry=registry)
    assert mixed.partitions[0].family == CUSTOM_FAMILY
    single = run(
        [item("docs/readme.md", "x\n"), item("src/cli.py", "x = 1\n")],
        registry=registry,
        descriptor_=descriptor(families=("service",)),
    )
    assert single.partitions[0].family == "service"
    empty = run([item("exports/logo.bin", data=b"\x00\x00")], registry=registry)
    assert empty.partitions[0].family == CUSTOM_FAMILY


def test_classification_records_the_registry_fingerprint_and_the_classifier_spec(registry) -> None:
    used = spec(
        declarations=(base.PathDeclaration(pattern="docs/adr/*", family="prose", template="adr"),),
        sql_dialects=("postgres", "tsql"),
    )
    classification = run(
        [item("docs/adr/0001.md", ADR), item("other/two.md", "x\n", partition="other")],
        registry=registry,
        spec_=used,
    )
    assert classification.connector == "local_folder"
    assert classification.connector_version == "1"
    assert classification.registry_fingerprint == registry.fingerprint()
    assert [partition.partition for partition in classification.partitions] == ["exports", "other"]
    for partition in classification.partitions:
        assert partition.mapping.classifier == used
        assert partition.mapping.classifier.version == classify.CLASSIFIER_VERSION
        assert partition.capabilities.inventory is True
    assert used.version == "cdk-classify-v1"


def test_classification_carries_the_attribute_mappings_it_was_given(registry) -> None:
    attribute = base.AttributeMapping(
        kind="incident_fixture", attribute="title", provider_field="fields.title"
    )
    classification = run(
        [item("incident", "{}", provider_type="incident")],
        registry=registry,
        kinds=(base.KindMapping(provider_type="incident", kind="incident_fixture"),),
        attributes=(attribute,),
        descriptor_=descriptor(families=("incident",), kinds=("incident_fixture",)),
    )
    partition = classification.partitions[0]
    assert partition.mapping.attributes == (attribute,)
    assert any(evidence.level == "attribute" for evidence in partition.evidence)


# ------------------------------------------------------------------ purity


def _forbidden(*args, **kwargs):
    raise AssertionError("classification performed an effect")


PURITY_TARGETS = (
    "socket.socket.connect",
    "socket.create_connection",
    "socket.getaddrinfo",
    "subprocess.Popen.__init__",
    "time.time",
    "time.time_ns",
    "time.monotonic",
    "time.perf_counter",
    "time.sleep",
    "httpx.Client.send",
    "httpx.AsyncClient.send",
    "hippo.ollama.Ollama.*",
)


def _intercept(monkeypatch, *, clock: float | None) -> None:
    import httpx

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", _forbidden)
    monkeypatch.setattr(subprocess.Popen, "__init__", _forbidden)
    monkeypatch.setattr(httpx.Client, "send", _forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", _forbidden)
    for name, value in vars(hippo.ollama.Ollama).items():
        if callable(value) and not name.startswith("__"):
            monkeypatch.setattr(hippo.ollama.Ollama, name, _forbidden)
    for name in ("time", "monotonic", "perf_counter", "sleep"):
        monkeypatch.setattr(time, name, _forbidden if clock is None else (lambda *_, _v=clock: _v))
    monkeypatch.setattr(time, "time_ns", _forbidden if clock is None else (lambda *_: int(clock * 1e9)))


def test_classify_is_pure_under_reordering_clock_and_forbidden_io(registry, monkeypatch) -> None:
    items = [
        item("docs/adr/0001.md", ADR),
        item("src/hippo/cli.py", "x = 1\n"),
        item("migrations/001.sql", DDL),
        item("exports/rows.csv", "id,title\n1,a\n"),
        item("other/notes.md", "x\n", partition="other"),
    ]
    used = spec(
        declarations=(base.PathDeclaration(pattern="migrations/*.sql", family="db", dialect="postgres"),),
        sql_dialects=("postgres",),
    )
    with monkeypatch.context() as first:
        _intercept(first, clock=None)
        one = run(items, registry=registry, spec_=used)
    with monkeypatch.context() as second:
        _intercept(second, clock=1_700_000_000.0)
        two = run(list(reversed(items)), registry=registry, spec_=used)
    assert one == two
    assert one.model_dump_json() == two.model_dump_json()
