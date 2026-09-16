"""The incidents exemplar: a connector written only with the public kit, proved end to end.

Plan `ai_docs/plans/cdk-s6-exemplar.md` sections 3, 4 and 5, gate CK6. Rulings and review findings
that bind this file: R6 and R-S2-6 (a rendered fact is a `Unit` and a derived `Passage`; a foreign
endpoint is identity only), R13 (the kind stays `incident`), R53/M6 and R70/R71 (the `service`
endpoint is an identity-only foreign node keyed by the configured `catalog_instance` and named by
the label its `NodeEmission` carries), R60 and M15 (the import allowlist admits
`hippo.connectors.classify` and `hippo.connectors.http`; the descriptor declares `acls` and
`inventory`, and `fetch` raises `ProviderNotFoundError` for an id absent from the export), R61 (the
`principal_map` lives in the configuration and `emit.policy_record` applies it), m8
(`FactTemplate.consumes`, `ParserVersion.parse("json@1")`, `metadata_origin="catalog"`, an HTTP(S)
`instance_url`), R75 and R79 (one malformed record, so `failures.json` fills with `{family, parser,
count}`), R77 (`descriptor` is a class attribute; a provider `Connector` row needs a signed-in
installation), R78 (never build a negative fixture with `model_copy(update=...)`: kit records
re-validate, so a mangled copy passes for the wrong reason - answer another record instead).

The three plan overrides this slice took, approved by the orchestrator before any edit, are in
`ai_docs/gates/rag-it-all/cdk/evidence-s6.md`: the key template is `("instance", "incident_id")`
rather than the plan's `("tool_instance", ...)`, the raw export file lives under `<package>/export/`
rather than under `fixtures/`, and the predicate's verb phrase is `affects`.

No test here imports a test client, so the section 8 line for this file needs no anyio filter.
"""

from __future__ import annotations

import ast
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hippo.access import Principal
from hippo.ask import search
from hippo.connectors import base, sync, testing
from hippo.connectors.examples import incidents_ndjson as exemplar
from hippo.connectors.http import ProviderNotFoundError
from hippo.knowledge import model as k
from hippo.knowledge.build_authority import BuildActor
from hippo.knowledge.citations import resolve_citations
from hippo.knowledge.identity import text_hash
from hippo.knowledge.query_access import query_session
from hippo.knowledge.raw_artifacts import RawArtifactStore
from hippo.knowledge.registry import Registry, extension_scope, use_registry

PACKAGE = Path(exemplar.__file__).resolve().parent
EXPORT = PACKAGE / "export" / "incidents.ndjson"
BASIC = PACKAGE / "fixtures" / "basic"
UPDATE = PACKAGE / "fixtures" / "update"

# Plan section 3.3: the exemplar imports the public kit and the knowledge model, plus the two
# modules ruling R60 and finding M15 admit. `hippo.connectors.testing` is allowed inside `tests/`.
ALLOWED_IMPORTS = frozenset(
    {
        "hippo.connectors",
        "hippo.connectors.base",
        "hippo.connectors.keys",
        "hippo.connectors.render",
        "hippo.connectors.classify",
        "hippo.connectors.http",
        "hippo.knowledge.model",
    }
)
TEST_ONLY_IMPORTS = frozenset({"hippo.connectors.testing"})
# The scaffold's own file set, which the exemplar keeps. The two `inputs/record-*` files are the
# only scaffolded paths it replaces: a fixture record is named by its external id, and the
# exemplar's ids are the incident ids of its export.
SCAFFOLD_FILES = (
    "__init__.py",
    "connector.py",
    "fixtures/basic/changes.json",
    "fixtures/basic/config.json",
    "fixtures/basic/expected/aliases.json",
    "fixtures/basic/expected/coverage.json",
    "fixtures/basic/expected/edges.json",
    "fixtures/basic/expected/failures.json",
    "fixtures/basic/expected/nodes.json",
    "fixtures/basic/expected/passages.json",
    "fixtures/basic/expected/units.json",
    "fixtures/basic/policies.json",
    "fixtures/registry.lock.json",
    "templates.py",
    "tests/test_connector.py",
    "types.py",
)
# The export's own records, by the external id the connector reads off each line.
RESOLVED = "P7Q2X1"  # INC-2210, workspace visible, resolved
RESTRICTED = "P7Q2X2"  # INC-2211, restricted to one provider user
OPEN_INCIDENT = "P7Q2X3"  # INC-2212, unresolved, so no resolution fact
QUESTION = "Which incident affected settlement-batch-processor?"
# `RevisionInput` refuses anything but a real `AccessPolicy` id, so the hand-built
# revisions of the `emit` tests name one of the right shape.
POLICY_ID = "accesspolicy-" + "0" * 64


# ------------------------------------------------------------------ helpers


def _connector():
    return exemplar.Connector()


def _descriptor():
    return exemplar.Connector.descriptor


def _config(**overrides):
    """The configuration of the committed `basic` case, with `export_path` pointed at the export."""
    payload = json.loads((BASIC / "config.json").read_text(encoding="utf-8"))
    payload["export_path"] = str(EXPORT)
    return _descriptor().config_model.model_validate(payload | overrides)


def _lines() -> list[str]:
    return [line for line in EXPORT.read_text(encoding="utf-8").split("\n") if line.strip()]


def _record(external_id: str) -> dict:
    for line in _lines():
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and parsed.get("id") == external_id:
            return parsed
    raise AssertionError(f"{external_id} is not in {EXPORT}")


def _id_of(line: str) -> dict | None:
    """The line's record, or None when the exporter truncated it."""
    try:
        parsed = json.loads(line)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _line_of(external_id: str) -> str:
    for line in _lines():
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and parsed.get("id") == external_id:
            return line
    raise AssertionError(f"{external_id} is not in {EXPORT}")


def _revision(connector, config, external_id: str, mapping):
    """One `RevisionInput` over the real export line, with no store and no clock."""
    fetched = connector.fetch(config, _ref(config, external_id))
    artifact = k.Artifact(
        workspace_id="w-exemplar",
        source_id="src-exemplar",
        connector_id="connector-exemplar",
        kind=_descriptor().artifact_kinds[0],
        external_id=external_id,
        provider_instance=config.instance_url,
        canonical_uri=fetched.canonical_uri,
        policy_id=POLICY_ID,
    )
    revision = k.ArtifactRevision(
        artifact_id=artifact.id,
        content_hash=hashlib.sha256(fetched.data).hexdigest(),
        provider_revision=fetched.provider_revision,
        source_updated_at=fetched.source_updated_at,
        observed_at=datetime(2026, 9, 14, 12, tzinfo=UTC),
        raw_uri=f"raw://exemplar/{external_id}",
        lifecycle="active",
    )
    return base.RevisionInput(
        partition=exemplar.connector.PARTITION,
        artifact=artifact,
        revision=revision,
        data=fetched.data,
        config=config,
        mapping=mapping,
        registry=_registry(),
        span_policy_id=POLICY_ID,
    )


def _ref(config, external_id: str) -> base.ExternalRef:
    return base.ExternalRef(
        partition=exemplar.connector.PARTITION,
        artifact_kind=_descriptor().artifact_kinds[0],
        external_id=external_id,
    )


def _registry() -> Registry:
    return testing.kit_registry(_descriptor())


def _mapping(connector, config):
    classification = connector.probe(config, lambda: datetime(2026, 1, 1, tzinfo=UTC))
    return classification.partitions[0].mapping


@pytest.fixture
def kit_registry():
    """The built-ins plus the exemplar's extension, installed for the duration of one test."""
    registry = _registry()
    with use_registry(registry):
        yield registry


# ------------------------------------------------------------------ the package


def test_the_exemplar_keeps_the_scaffold_file_set_and_its_generated_test():
    missing = [name for name in SCAFFOLD_FILES if not (PACKAGE / name).is_file()]
    assert not missing, f"the exemplar dropped scaffolded files: {missing}"
    inputs = sorted(path.name for path in (BASIC / "inputs").iterdir())
    assert len(inputs) == len(_lines()), "one input file per exported line, named by its external id"
    generated = (PACKAGE / "tests" / "test_connector.py").read_text(encoding="utf-8")
    assert "validate_package(PACKAGE)" in generated
    assert "assert report.passed" in generated


def test_the_exemplar_imports_only_the_public_kit_and_the_knowledge_model():
    offenders: list[str] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        allowed = ALLOWED_IMPORTS | (TEST_ONLY_IMPORTS if path.parent.name == "tests" else frozenset())
        for module in _imported_modules(path):
            if not module.startswith("hippo"):
                continue
            if module not in allowed:
                offenders.append(f"{path.relative_to(PACKAGE)}: {module}")
    assert not offenders, f"the exemplar reached outside the public kit: {offenders}"


def _imported_modules(path: Path) -> list[str]:
    """Every absolute module an `import` statement names; a relative import names no package."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append(node.module)
    return modules


def test_the_extension_registers_a_new_kind_with_fact_templates_and_a_windowed_predicate_owned_by_incident():
    builtins = Registry.with_builtins()
    assert "incident" not in builtins.object_kinds(), "R13: the exemplar registers it, nothing else"
    assert "AFFECTS" not in builtins.predicates()

    registry = _registry()
    kind = registry.object_kind("incident")
    assert kind.family == "incident"
    assert kind.key_template == ("instance", "incident_id")
    assert [f"{t.name}@{t.version}" for t in kind.fact_templates] == [
        "incident_summary@1",
        "incident_resolution@1",
    ]
    predicate = registry.predicate("AFFECTS")
    assert predicate.windowed is True
    assert predicate.subject_kinds == frozenset({"incident"})
    assert predicate.object_kinds == frozenset({"service"})
    assert predicate.owner_families == frozenset({"incident"})
    assert predicate.sources_allowed == frozenset({"metadata"})
    assert "incident_record" in registry.artifact_kinds()
    assert "incidents_ndjson" in registry.connector_kinds()
    # R77: the loader reads the descriptor off the class, before anything is constructed.
    assert isinstance(exemplar.Connector.__dict__.get("descriptor"), base.ConnectorDescriptor)
    assert _descriptor().capabilities.acls is True and _descriptor().capabilities.inventory is True
    assert [parser.spelling for parser in _descriptor().parsers] == ["json@1"]


def test_validate_passes_the_exemplar_and_reports_its_registry_diff():
    report = testing.validate_package(PACKAGE)
    assert report.passed, json.dumps(report.to_json(), indent=2, sort_keys=True)
    assert report.scope == "full"
    assert report.registry_diff == (
        "+ artifact kind incident_record",
        "+ connector kind incidents_ndjson",
        "+ kind incident",
        "+ predicate AFFECTS",
        "+ template incident/incident_resolution@1",
        "+ template incident/incident_summary@1",
    )


# ------------------------------------------------------------------ the sync half


def test_list_changes_reads_one_change_per_line_with_the_updated_at_revision_and_a_file_cursor(kit_registry):
    connector, config = _connector(), _config()
    page = connector.list_changes(config, None)

    assert page.complete is True
    assert [change.operation for change in page.changes] == ["upsert"] * len(_lines())
    ids = [change.ref.external_id for change in page.changes]
    assert ids[:3] == [RESOLVED, RESTRICTED, OPEN_INCIDENT]
    assert ids[3].startswith("line-sha256:"), "a line that is not a JSON object still gets a change"
    assert [change.ref.provider_revision for change in page.changes][:3] == [
        _record(RESOLVED)["updated_at"],
        _record(RESTRICTED)["updated_at"],
        _record(OPEN_INCIDENT)["updated_at"],
    ]
    assert page.next_cursor is not None
    cursor = json.loads(page.next_cursor.value)
    assert cursor["sha256"] == hashlib.sha256(EXPORT.read_bytes()).hexdigest()

    replayed = connector.list_changes(config, page.next_cursor)
    assert replayed.changes == (), "an unchanged export is a no-op on the next run"
    assert replayed.complete is True


def test_fetch_returns_the_exact_line_bytes_and_the_provider_timestamp(kit_registry):
    connector, config = _connector(), _config()
    fetched = connector.fetch(config, _ref(config, RESOLVED))

    assert fetched.data == _line_of(RESOLVED).encode("utf-8")
    assert not fetched.data.endswith(b"\n")
    assert fetched.content_type == "application/x-ndjson"
    assert fetched.provider_revision == _record(RESOLVED)["updated_at"]
    assert fetched.source_timestamp_original == _record(RESOLVED)["updated_at"]
    assert fetched.source_updated_at == datetime(2026, 9, 14, 4, 10, tzinfo=UTC)
    assert fetched.source_timezone == "UTC" and fetched.source_precision == "second"
    assert fetched.canonical_uri == f"{config.instance_url}/incidents/{RESOLVED}"
    assert fetched.parser is not None and fetched.parser.spelling == "json@1"

    with pytest.raises(ProviderNotFoundError):
        connector.fetch(config, _ref(config, "P0NOPE"))


@pytest.mark.parametrize("case", ["workspace", "restricted", "missing", "garbage"])
def test_fetch_policy_maps_visibility_and_unknown_is_deny(kit_registry, tmp_path, case):
    records = {
        "workspace": (RESOLVED, "known", "workspace"),
        "restricted": (RESTRICTED, "known", "restricted"),
        "missing": ("P7Q2X4", "unknown", None),
        "garbage": ("P7Q2X5", "unknown", None),
    }
    external_id, state, mode = records[case]
    config = _visibility_export(tmp_path, case)
    observed = _connector().fetch_policy(config, _ref(config, external_id))

    assert observed.state == state
    assert observed.mode == mode
    if case == "restricted":
        assert observed.allow_users == (_record(RESTRICTED)["visibility"]["allow_users"][0],)
    else:
        principals = observed.allow_users + observed.allow_groups + observed.deny_users + observed.deny_groups
        assert principals == (), "an unknown observation carries no principals; unknown is deny"


def _visibility_export(tmp_path, case: str):
    """The committed export, plus the two negative records `basic` does not ship.

    R78: a negative fixture is another record, never `model_copy(update=...)` of a kit record. These
    are plain JSON dicts, written as new lines of a scratch export, so nothing re-validates.
    """
    lines = list(_lines())
    template = _record(RESOLVED)
    if case == "missing":
        record = {key: value for key, value in template.items() if key != "visibility"}
        lines.append(json.dumps(record | {"id": "P7Q2X4"}, sort_keys=True))
    if case == "garbage":
        lines.append(
            json.dumps(template | {"id": "P7Q2X5", "visibility": {"mode": "everyone"}}, sort_keys=True)
        )
    path = tmp_path / "incidents.ndjson"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return _config(export_path=str(path))


# ------------------------------------------------------------------ emit


def test_emit_takes_ts_and_the_affects_window_from_the_record_never_the_clock(kit_registry):
    connector, config = _connector(), _config()
    mapping = _mapping(connector, config)
    batch = connector.emit(_revision(connector, config, RESOLVED, mapping), mapping)
    record = _record(RESOLVED)

    incident = next(node for node in batch.nodes if node.ref.kind == "incident")
    assert incident.ts == datetime(2026, 9, 14, 3, 12, tzinfo=UTC)
    assert incident.ts_original == record["started_at"]
    assert incident.ref.key == {"incident_id": RESOLVED}, "the kit fills the instance part"
    assert incident.ref.instance is None
    assert incident.source == "metadata" and incident.metadata_origin == "catalog"
    assert incident.span.locator_kind == "file_lines"
    assert incident.span.locator["start"] == 1 and incident.span.locator["end"] == 1

    service = next(node for node in batch.nodes if node.ref.kind == "service")
    assert service.ref.key == {"reference": record["service"]}
    assert service.ref.instance == config.catalog_instance, "R53: the endpoint declares its instance"
    assert service.ref.label == record["service"], "R71: the label the statement reads"

    (edge,) = batch.edges
    assert edge.predicate == "AFFECTS"
    assert edge.family == "deterministic" and edge.source == "metadata"
    assert edge.metadata_origin == "catalog"
    assert edge.valid_from == datetime(2026, 9, 14, 3, 12, tzinfo=UTC)
    assert edge.valid_to == datetime(2026, 9, 14, 3, 59, tzinfo=UTC)


def test_emit_computes_minutes_from_timestamps_and_an_open_incident_gets_no_resolution_fact(kit_registry):
    connector, config = _connector(), _config()
    mapping = _mapping(connector, config)
    definition = kit_registry.object_kind("incident")

    resolved = connector.emit(_revision(connector, config, RESOLVED, mapping), mapping)
    attrs = next(node for node in resolved.nodes if node.ref.kind == "incident").attrs
    assert (attrs["mttd_minutes"], attrs["mttm_minutes"], attrs["mttr_minutes"]) == (5, 31, 47)
    assert _templates(definition, attrs) == ("incident_summary@1", "incident_resolution@1")

    from hippo.connectors import render

    unresolved = connector.emit(_revision(connector, config, OPEN_INCIDENT, mapping), mapping)
    node = next(entry for entry in unresolved.nodes if entry.ref.kind == "incident")
    assert node.attrs["resolved_at"] is None and node.attrs["mttr_minutes"] is None
    assert _templates(definition, node.attrs) == ("incident_summary@1",)
    assert render.skipped_fact_templates(definition, definition.attrs_model(**node.attrs)) == (
        "incident_resolution@1",
    )
    (edge,) = unresolved.edges
    assert edge.valid_to is None, "an unresolved incident's window is open"


def _templates(definition, attrs) -> tuple[str, ...]:
    from hippo.connectors import keys, render

    model = definition.attrs_model(**attrs)
    key = keys.CanonicalKey(kind="incident", parts=("i", "d"), readable="inc:i/d")
    label = render.render_label(definition, model)
    return tuple(text.template for text in render.render_facts(definition, model, label=label, key=key))


def test_a_malformed_line_is_a_counted_parse_failure(kit_registry):
    connector, config = _connector(), _config()
    mapping = _mapping(connector, config)
    malformed = [
        change.ref.external_id
        for change in connector.list_changes(config, None).changes
        if change.ref.external_id.startswith("line-sha256:")
    ]
    assert malformed, "R75: the fixture carries one malformed record so failures.json fills"

    batch = connector.emit(_revision(connector, config, malformed[0], mapping), mapping)
    assert batch.nodes == () and batch.edges == () and batch.units == ()
    (failure,) = batch.failures
    assert failure.family == "incident"
    assert failure.parser is not None and failure.parser.spelling == "json@1"

    failures = json.loads((BASIC / "expected" / "failures.json").read_text(encoding="utf-8"))
    assert failures == [{"count": 1, "family": "incident", "parser": "json@1"}]


def test_emit_is_pure_under_the_guard(kit_registry):
    connector, config = _connector(), _config()
    mapping = _mapping(connector, config)
    revision = _revision(connector, config, RESOLVED, mapping)
    batch = testing.assert_emit_pure(connector, revision, mapping)
    assert batch.nodes and batch.edges


# ------------------------------------------------------------------ the scratch workspace


class World:
    """One frozen registry, one enabled exemplar instance, one partition Source.

    The shape of `tests/unit/test_connector_sync.py`'s `World`, cut to what CK6 needs. R77: the
    store refuses a provider `Connector` row in open mode, so an operator is created first.
    """

    def __init__(self, ctx, tmp_path, registry, *, export: Path | None = None):
        self.ctx, self.store, self.registry = ctx, ctx.store, registry
        self.partition = exemplar.connector.PARTITION
        self.instance = "https://incidents.example"
        self.connector = _connector()
        self.raw = RawArtifactStore(tmp_path / "raw", max_object_bytes=8_000_000)
        self.store.ensure_schema()
        self.store.ensure_roles()
        self.user = self.store.create_user("operator", "password", "individual")
        self.reader_id = self.store.create_user("reader", "password", "individual")
        self.outsider_id = self.store.create_user("outsider", "password", "individual")
        self.config = _config(
            export_path=str(export or EXPORT),
            instance_url=self.instance,
            principal_map={"users": {_record(RESTRICTED)["visibility"]["allow_users"][0]: self.reader_id}},
        )
        self.row = sync.ensure_connector(
            self.store,
            workspace_id=self.store.get_source(self._probe_source())["workspace_id"],
            kind="incidents_ndjson",
            instance_url=self.instance,
            config=self.config,
            enabled=True,  # R73: passed deliberately, never relying on R51's default
        )
        self.workspace = self.row.workspace_id
        for principal in (self.user, self.reader_id, self.outsider_id):
            self.store.put_knowledge(
                k.WorkspaceMembership(
                    workspace_id=self.workspace,
                    principal_id=principal,
                    mapping_authority="local",
                    enabled=True,
                    policy_epoch=1,
                )
            )
        self.store.set_meta("reviewed_mapping_authorities", ["local"])
        self.row = sync.store_classification(
            self.store,
            connector=self.row,
            classification=self.connector.probe(self.config, self.store._now),
        )
        self.source = sync.connector_source(
            self.store,
            connector=self.row,
            partition=self.partition,
            name=f"incidents_ndjson {self.partition}",
            owner_id=self.user,
        )
        self.operation = 0
        self.sessions: list = []

    def _probe_source(self) -> str:
        if not hasattr(self, "_probe"):
            self._probe = self.store.create_source("text", "workspace probe", {})
        return self._probe

    def sync(self, connector=None, **overrides):
        from hippo.ingest.managed_activation import embedding_spec

        self.operation += 1
        fields = dict(
            connector_id=self.row.id,
            config=self.config,
            partition=self.partition,
            actor=BuildActor.trusted_local(),
            registry=self.registry,
            options=sync.SyncOptions(emit_workers=1),
            raw_store=self.raw,
            embedding_spec=embedding_spec(self.ctx.ollama),
            operation_id=f"op-{self.operation}",
            should_stop=lambda: False,
        )
        return sync.sync_connector(self.ctx, connector or self.connector, **(fields | overrides))

    def principal(self, user_id: str) -> Principal:
        return Principal.for_user(self.store.get_user(user_id), self.store.get_role("individual"))

    def session(self, user_id: str):
        opened = query_session(self.ctx, self.principal(user_id).access)
        session = opened.__enter__()
        self.sessions.append(opened)
        return session

    def close_sessions(self) -> None:
        for opened in self.sessions:
            opened.__exit__(None, None, None)
        self.sessions.clear()

    def rows(self, kind, **scope):
        return list(self.store._knowledge_rows(kind, **scope))


@pytest.fixture
def registry():
    with extension_scope() as scoped:
        scoped.register(exemplar.types.EXTENSION, declared_families=("incident",))
        scoped.freeze()
        yield scoped


@pytest.fixture
def ctx(store, tmp_path):
    from hippo.config import Config
    from hippo.context import AppContext

    return AppContext(config=Config(data_dir=tmp_path / "data"), store=store, ollama=testing.offline_ollama())


@pytest.fixture
def world(ctx, tmp_path, registry):
    built = World(ctx, tmp_path, registry)
    try:
        yield built
    finally:
        built.close_sessions()


def test_a_fixture_syncs_into_a_scratch_workspace_and_publishes_one_generation(world):
    receipt = world.sync()

    assert receipt.outcome == "published"
    assert world.store.get_source(world.source)["active_generation_id"] == receipt.generation_id
    generation = world.store._knowledge_get("Generation", receipt.generation_id)
    assert generation.status == "active"
    rendered = [
        row
        for row in world.store._native_rows("Passage", generation_id=receipt.generation_id)
        if row.get("retrieval_view_id")
    ]
    assert rendered, "R6: a rendered fact is a derived passage over a retrieval view"
    assert any("INC-2210" in row["text"] for row in rendered)
    statements = [
        row.statement
        for row in world.rows("AssertionVersion")
        if getattr(row, "statement", None) and "affects" in row.statement
    ]
    assert any(statement.endswith("affects service checkout") for statement in statements), (
        f"R70/R71: the endpoint label names the service; got {statements}"
    )


def test_search_returns_the_rendered_fact_of_the_incident(world):
    world.sync()
    session = world.session(world.user)
    trace = search(world.ctx, QUESTION, session=session)

    texts = [session.graph.passage_by_id(ranked.passage_id).text for ranked in trace.passages]
    assert any(text.startswith("INC-2210 (SEV2) Settlement batch stalled") for text in texts), (
        f"the exemplar's rendered fact did not reach the query path; got {texts}"
    )


def test_every_citation_of_the_rendered_fact_resolves_to_the_record_span(world):
    receipt = world.sync()
    session = world.session(world.user)
    trace = search(world.ctx, QUESTION, session=session)
    passage_id = next(
        ranked.passage_id
        for ranked in trace.passages
        if session.graph.passage_by_id(ranked.passage_id).text.startswith("INC-2210")
    )

    bundle = resolve_citations(session.graph, (passage_id,))
    (item,) = bundle.items
    assert item.is_derived, "a rendered fact is a derived passage"
    members = {
        row.record_id
        for row in world.rows("GenerationEvidenceMember", generation_id=receipt.generation_id)
        if row.record_kind == "EvidenceSpan"
    }
    assert bundle.citations
    for citation in bundle.citations:
        assert citation.span_id in members
        assert citation.text == _line_of(RESOLVED)
        assert text_hash(citation.text) == citation.text_hash
        assert citation.locator_kind == "file_lines"
        assert json.loads(citation.locator_json)["start"] == 1
        assert json.loads(citation.locator_json)["end"] == 1


def test_a_restricted_incident_is_never_returned_to_a_reader_outside_its_allow_list(world):
    world.sync()
    allowed = world.session(world.reader_id)
    outside = world.session(world.outsider_id)

    assert _sees(allowed, "INC-2211"), "the mapped principal is inside the allow list"
    assert not _sees(outside, "INC-2211")
    assert _sees(outside, "INC-2210"), "a workspace-visible incident is still readable"


def test_an_incident_with_unknown_visibility_is_returned_to_nobody(ctx, tmp_path, registry):
    unknown = tmp_path / "unknown.ndjson"
    record = _record(RESOLVED) | {"id": "P7Q2X9", "number": 2219, "visibility": {"mode": "everyone"}}
    unknown.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
    built = World(ctx, tmp_path, registry, export=unknown)
    try:
        built.sync()
        for user in (built.user, built.reader_id, built.outsider_id):
            assert not _sees(built.session(user), "INC-2219"), "unknown visibility is deny"
    finally:
        built.close_sessions()


def _sees(session, needle: str) -> bool:
    return any(needle in passage.text for passage in session.graph.passages)


def test_an_update_page_republishes_and_a_complete_scan_withdraws_the_missing_incident(
    ctx, tmp_path, registry
):
    export = tmp_path / "incidents.ndjson"
    export.write_text(EXPORT.read_text(encoding="utf-8"), encoding="utf-8")
    built = World(ctx, tmp_path, registry, export=export)
    try:
        first = built.sync()
        assert first.outcome == "published"

        resolved_open = json.dumps(
            json.loads(_line_of(OPEN_INCIDENT))
            | {"resolved_at": "2026-09-15T08:00:00Z", "updated_at": "2026-09-15T08:05:00Z"},
            sort_keys=True,
        )
        kept = []
        for line in _lines():
            identifier = (_id_of(line) or {}).get("id")
            if identifier == RESTRICTED:
                continue  # absent from the second, complete scan
            kept.append(resolved_open if identifier == OPEN_INCIDENT else line)
        export.write_text("\n".join(kept) + "\n", encoding="utf-8")

        second = built.sync(options=sync.SyncOptions(emit_workers=1, reconcile=True))
        assert second.outcome == "published"
        assert second.deleted == 1, "R-S3-5: a complete scan withdraws what it did not return"
        assert second.inventory == "complete"
        withdrawn = [
            row
            for row in built.rows("Artifact")
            if row.external_id == RESTRICTED and row.deleted_at is not None
        ]
        assert withdrawn
        session = built.session(built.user)
        assert not _sees(session, "INC-2211")
        assert _sees(session, "INC-2212"), "the reopened incident republished with its resolution"
    finally:
        built.close_sessions()


def test_the_exemplar_never_reaches_the_network_or_the_user_data(kit_registry):
    """The exemplar reads files only (R75): no `http/` recording, and no transport is built."""
    assert not (PACKAGE / "fixtures" / "basic" / "http").exists()
    assert not (PACKAGE / "fixtures" / "update" / "http").exists()
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(PACKAGE.rglob("*.py")) if path.is_file()
    )
    assert "ProviderClient" not in source
    assert "httpx" not in source
