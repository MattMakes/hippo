"""The pure domain resolver and the coordinator's lane facts (plan section 3.2).

Plan `ai_docs/plans/2026-09-18-knowledge-inventory-domain-plan.md` sections 2.4, 3.2 and task T1.
Two orchestrator decisions bind this file: the origin reads every family- or kind-level evidence row
whose outcome names the family (not only family-level rows), and a single-family connector's fixed
reason names the connector kind only when the caller passes it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from hippo.connectors import base
from hippo.ingest import managed_activation
from hippo.knowledge import domain
from hippo.knowledge import model as k
from hippo.knowledge.domain import (
    COORDINATOR_TRANSITIONS,
    DomainDecision,
    SourceShape,
    buildable_families,
    overridden_classification,
    resolve_domain,
)
from hippo.knowledge.registry import CUSTOM_FAMILY

CONFIRMED = "2026-09-18T10:00:00.000000+00:00"
CONFIRMED_AT = datetime.fromisoformat(CONFIRMED)
TWO_FAMILIES = ("service", "custom")


# ------------------------------------------------------------------ builders


def row(kind="text", *, file="", status="ready", stage=None, managed=False, **fields):
    meta = {"file": file} if file else {}
    return {"id": "s1", "kind": kind, "name": "a source", "meta": meta, "status": status, "stage": stage,
            "managed": managed} | fields  # fmt: skip


def connector_row(**fields):
    return row("connector", meta={"connector_id": "connector-1", "partition": "notes"}) | fields


def shape_of(source) -> SourceShape:
    return managed_activation.source_shape(source)


def evidence(rule, outcome, *, level="family", subject="notes/a.md"):
    return base.ClassificationEvidence(
        level=level, rule=rule, detector="test", subject=subject, outcome=outcome
    )


def partition(family, *rows):
    return base.PartitionClassification(
        partition="notes",
        family=family,
        mapping=base.TypeMapping(family=family),
        capabilities=base.ConnectorCapabilities(inventory=True),
        sample_count=len(rows),
        counts={},
        evidence=tuple(rows),
    )


def state(last_success_at):
    return k.SyncState(connector_id="connector-1", partition_key="notes", last_success_at=last_success_at)


def resolve_connector(source=None, **kwargs) -> DomainDecision:
    source = connector_row() if source is None else source
    kwargs.setdefault("classification", partition("custom", evidence("name", "custom")))
    return resolve_domain(source, shape_of(source), **kwargs)


# ------------------------------------------------------------------ source_shape


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (row("text", file="text.md"), ("text", "prose", "prose_name", {"legacy", "managed"})),
        (row("file", file="notes.md"), ("file", "prose", "prose_name", {"legacy", "managed"})),
        (row("file", file="main.py"), ("file", "code", "code_name", {"legacy", "managed"})),
        (row("file", file="report.pdf"), ("file", "prose", "other", {"legacy"})),
        (row("archive", file="bundle.zip"), ("archive", "code", "other", {"legacy", "managed"})),
        (row("repo"), ("repo", "code", "other", {"legacy", "managed"})),
        (row("sample"), ("sample", "prose", "other", {"legacy"})),
        (row("file", file="main.py", managed=True), ("file", "code", "code_name", {"managed"})),
        (connector_row(), ("connector", "prose", "other", set())),
        (connector_row(managed=True), ("connector", "prose", "other", set())),
        (
            row("file", file="notes.md", status="deleted", stage="tombstoned"),
            ("file", "prose", "prose_name", set()),
        ),
    ],
    ids=[
        "text",
        "prose-named-file",
        "code-named-file",
        "rich-file",
        "archive",
        "repo",
        "sample",
        "managed-file",
        "connector",
        "managed-connector",
        "tombstoned",
    ],
)
def test_source_shape_reads_the_lane_facts_off_the_row(source, expected):
    shape = shape_of(source)
    kind, lane_family, name_class, lanes = expected
    assert shape == SourceShape(
        kind=kind, lane_family=lane_family, name_class=name_class, lanes=frozenset(lanes)
    )
    assert (shape.lane_family == "code") is managed_activation.is_code_source(source)


# ------------------------------------------------------------------ origin


def test_a_coordinator_row_takes_the_lane_family_with_origin_lane():
    decision = resolve_domain(row("file", file="main.py"), shape_of(row("file", file="main.py")))
    assert (decision.family, decision.natural, decision.origin) == ("code", "code", "lane")
    decision = resolve_domain(row("text"), shape_of(row("text")))
    assert (decision.family, decision.natural, decision.origin) == ("prose", "prose", "lane")


@pytest.mark.parametrize(
    ("rows", "origin"),
    [
        ((evidence("declaration", "service"),), "declared"),
        ((evidence("descriptor", "service"),), "declared"),
        ((evidence("content", "service"),), "content"),
        ((evidence("name", "service"),), "name"),
        # Orchestrator decision 1: a kind-level row counts when the part before "/" is the family.
        ((evidence("declaration", "service/api", level="kind"),), "declared"),
        ((evidence("descriptor", "service/api", level="kind"),), "declared"),
        ((evidence("content", "service/api", level="kind"),), "content"),
        # The strongest rule wins, whatever the order of the rows.
        ((evidence("name", "service"), evidence("content", "service"), evidence("declaration", "service")), "declared"),
        ((evidence("name", "service"), evidence("content", "service")), "content"),
        # A row for another family, an attribute row and a similar family name do not count.
        ((evidence("declaration", "code"), evidence("name", "service")), "name"),
        ((evidence("descriptor", "service_ext", level="kind"),), "fallback"),
        ((evidence("descriptor", "api.title", level="attribute"),), "fallback"),
        ((), "fallback"),
    ],
)  # fmt: skip
def test_a_connector_origin_is_the_strongest_rule_that_chose_the_family(rows, origin):
    decision = resolve_connector(classification=partition("service", *rows))
    assert (decision.family, decision.natural, decision.origin) == ("service", "service", origin)


def test_an_unclassified_row_is_never_evidence_for_the_custom_family():
    rows = (
        evidence("unclassified", base.UNCLASSIFIED),
        evidence("content", base.UNCLASSIFIED),  # tabular content without a declared kind
        evidence("name", base.UNCLASSIFIED),  # binary bytes
    )
    decision = resolve_connector(classification=partition(CUSTOM_FAMILY, *rows))
    assert (decision.family, decision.origin) == (CUSTOM_FAMILY, "fallback")
    assert domain.UNCLASSIFIED_OUTCOME == base.UNCLASSIFIED


def test_the_origin_of_a_real_classification_matches_its_decisions():
    """Duck typing reads the connector records the classifier really builds."""
    from pydantic import BaseModel, ConfigDict

    from hippo.connectors import classify
    from hippo.knowledge.registry import Registry

    class Config(BaseModel):
        model_config = ConfigDict(frozen=True, extra="forbid")

    registry = Registry.with_builtins()
    registry.freeze()
    descriptor = base.ConnectorDescriptor(
        name="folder",
        version="1",
        families=("prose", "code"),
        kinds=(),
        predicates=(),
        artifact_kinds=("file",),
        locator_kinds=("file_lines",),
        capabilities=base.ConnectorCapabilities(inventory=True),
        config_model=Config,
        credentials=(),
        parsers=(),
        extension=base.TypeExtension(),
    )
    items = [
        classify.SampledItem(partition="by-name", path="src/a.py", data=b"x = 1\n"),
        classify.SampledItem(partition="declared", path="docs/a.txt", data=b"plain words\n"),
    ]
    spec = classify.classifier_spec(declarations=(base.PathDeclaration(pattern="docs/*", family="prose"),))
    result = classify.classify(
        descriptor,
        Config(),
        items,
        registry,
        spec=spec,
        capabilities=base.ConnectorCapabilities(inventory=True),
    )
    found = {entry.partition: resolve_connector(classification=entry) for entry in result.partitions}
    assert (found["by-name"].family, found["by-name"].origin) == ("code", "name")
    assert (found["declared"].family, found["declared"].origin) == ("prose", "declared")


def test_no_classification_gives_the_custom_family_by_fallback():
    decision = resolve_connector(classification=None)
    assert (decision.family, decision.natural, decision.origin) == (CUSTOM_FAMILY, CUSTOM_FAMILY, "fallback")


def test_an_override_on_a_connector_row_is_the_family_with_origin_user():
    source = connector_row(domain_override="service", domain_confirmed_at=CONFIRMED)
    decision = resolve_connector(source, descriptor_families=TWO_FAMILIES)
    assert (decision.family, decision.natural, decision.origin) == ("service", "custom", "user")


def test_a_stale_connector_override_is_still_shown_outside_allowed():
    """OD7: sync refuses it loudly, and the source page shows it so a Confirm can clear it."""
    source = connector_row(domain_override="db", domain_confirmed_at=CONFIRMED)
    decision = resolve_connector(source, descriptor_families=TWO_FAMILIES)
    assert (decision.family, decision.origin, decision.state) == ("db", "user", "pending_rebuild")
    assert decision.allowed == TWO_FAMILIES


# ------------------------------------------------------------------ state


def test_the_state_without_an_override_is_auto_or_confirmed():
    auto = resolve_connector()
    assert (auto.state, auto.confirmed_at, auto.confirmed_by) == ("auto", None, None)
    assert auto.pending_rebuild is False
    confirmed = resolve_connector(connector_row(domain_confirmed_at=CONFIRMED, domain_confirmed_by="user-1"))
    assert (confirmed.state, confirmed.confirmed_at, confirmed.confirmed_by) == (
        "confirmed",
        CONFIRMED,
        "user-1",
    )
    assert confirmed.pending_rebuild is False


def test_the_state_of_a_row_without_the_v9_columns_is_auto():
    """Invariant I5: a row read before (or without) schema v9 carries none of the three keys."""
    source = connector_row()
    assert "domain_override" not in source
    decision = resolve_connector(source)
    assert (decision.state, decision.origin) == ("auto", "name")


def test_pending_rebuild_states():
    source = connector_row(domain_override="service", domain_confirmed_at=CONFIRMED)

    def decide(sync_state):
        return resolve_connector(source, descriptor_families=TWO_FAMILIES, sync_state=sync_state)

    for pending in (None, state(None), state(CONFIRMED_AT - timedelta(seconds=1))):
        decision = decide(pending)
        assert (decision.state, decision.pending_rebuild) == ("pending_rebuild", True)
    for synced in (state(CONFIRMED_AT), state(CONFIRMED_AT + timedelta(minutes=5))):
        decision = decide(synced)
        assert (decision.state, decision.pending_rebuild) == ("corrected", False)
        assert decision.family == "service"


def test_an_override_without_a_readable_confirmation_time_stays_pending_and_never_raises():
    after = state(datetime(2030, 1, 1, tzinfo=UTC))
    for confirmed_at in (None, "not a time"):
        source = connector_row(domain_override="service", domain_confirmed_at=confirmed_at)
        decision = resolve_connector(source, descriptor_families=TWO_FAMILIES, sync_state=after)
        assert decision.state == "pending_rebuild"
    naive = connector_row(domain_override="service", domain_confirmed_at="2026-09-18T10:00:00")
    decision = resolve_connector(naive, descriptor_families=TWO_FAMILIES, sync_state=after)
    assert decision.state == "corrected"


# ------------------------------------------------------------------ allowed and fixed reasons


@pytest.mark.parametrize(
    ("source", "family", "reason"),
    [
        (row("repo"), "code", "Repositories are always built as code."),
        (row("archive", file="bundle.zip"), "code", "Zip archives are always built as code."),
        (row("file", file="main.py"), "code", "Files with a code extension are always built as code."),
        (row("file", file="main.py", managed=True), "code", "Files with a code extension are always built as code."),
        (row("file", file="notes.md"), "prose", "Plain-text files are always built as prose."),
        (row("text", file="text.md"), "prose", "Pasted text is always built as prose."),
        (row("text", managed=True), "prose", "Pasted text is always built as prose."),
        (row("file", file="report.pdf"), "prose", "Documents are always read as prose."),
        (row("file", file="notes"), "prose", "Documents are always read as prose."),
        (row("sample"), "prose", "Documents are always read as prose."),
    ],
    ids=["repo", "archive", "code-file", "managed-code-file", "prose-file", "text", "managed-text",
         "rich-file", "no-suffix-file", "sample"],
)  # fmt: skip
def test_every_coordinator_row_class_has_one_allowed_family_and_its_reason(source, family, reason):
    shape = shape_of(source)
    assert buildable_families(shape) == (family,)
    decision = resolve_domain(source, shape)
    assert decision.allowed == (family,)
    assert decision.fixed_reason == reason


def test_a_single_family_connector_is_fixed_and_names_the_connector_kind_when_given():
    decision = resolve_connector(descriptor_families=("custom",), connector_kind="fixture")
    assert decision.allowed == ("custom",)
    assert decision.fixed_reason == "The fixture connector declares only the custom domain."
    decision = resolve_connector(descriptor_families=("custom",))
    assert decision.fixed_reason == "This connector declares only the custom domain."


def test_a_multi_family_connector_allows_exactly_its_declared_families():
    decision = resolve_connector(descriptor_families=TWO_FAMILIES, connector_kind="fixture")
    assert decision.allowed == TWO_FAMILIES
    assert decision.fixed_reason is None
    shape = shape_of(connector_row())
    allowed = buildable_families(shape, classification=partition("custom"), descriptor_families=TWO_FAMILIES)
    assert allowed == TWO_FAMILIES


def test_a_connector_without_known_families_is_fixed():
    """CLI and MCP pass no descriptor families (plan section 2.5)."""
    decision = resolve_connector(descriptor_families=None)
    assert decision.allowed == ("custom",)
    assert decision.fixed_reason == "This process does not know the connector's declared domains."
    assert buildable_families(shape_of(connector_row()), classification=None) == (CUSTOM_FAMILY,)


def test_a_tombstoned_row_allows_only_its_natural_family():
    source = row("file", file="notes.md", status="deleted", stage="tombstoned")
    shape = shape_of(source)
    assert shape.lanes == frozenset()
    decision = resolve_domain(source, shape)
    assert decision.allowed == (decision.natural,) == ("prose",)
    assert decision.fixed_reason == "Plain-text files are always built as prose."


def test_no_coordinator_transition_is_enabled():
    """OD1: the plan's default offers no coordinator correction."""
    assert COORDINATOR_TRANSITIONS == frozenset()
    assert isinstance(COORDINATOR_TRANSITIONS, frozenset)


@pytest.mark.parametrize(
    "source",
    [row("text"), row("file", file="notes.md"), row("file", file="main.py"), row("repo"), row("sample")],
    ids=["text", "prose-file", "code-file", "repo", "sample"],
)
@pytest.mark.parametrize("override", ["code", "prose", "db", "Not A Family"])
def test_an_unknown_override_on_a_coordinator_row_resolves_to_the_lane_family(source, override):
    confirmed = source | {"domain_override": override, "domain_confirmed_at": CONFIRMED}
    shape = shape_of(confirmed)
    decision = resolve_domain(confirmed, shape)
    assert (decision.family, decision.origin) == (shape.lane_family, "lane")
    assert decision.state == "confirmed"
    assert decision.pending_rebuild is False


# ------------------------------------------------------------------ enabled transitions (T1-C)


def test_an_enabled_transition_is_offered_only_where_every_reachable_lane_builds_it(monkeypatch):
    monkeypatch.setattr(
        domain,
        "COORDINATOR_TRANSITIONS",
        frozenset({("text", "code"), ("file:prose_name", "code"), ("unsupported", "code")}),
    )
    assert buildable_families(shape_of(row("text"))) == ("prose", "code")
    assert buildable_families(shape_of(row("file", file="notes.md"))) == ("prose", "code")
    assert buildable_families(shape_of(row("file", file="notes.md", managed=True))) == ("prose", "code")
    assert buildable_families(shape_of(row("file", file="report.pdf"))) == ("prose", "code")
    # A code-named file matches no enabled row class, and a tombstoned row reaches no lane.
    assert buildable_families(shape_of(row("file", file="main.py"))) == ("code",)
    tombstoned = row("file", file="notes.md", status="deleted", stage="tombstoned")
    assert buildable_families(shape_of(tombstoned)) == ("prose",)


def test_a_transition_the_lanes_cannot_build_is_never_offered(monkeypatch):
    """Rows 3-5 of table 2.4: code to prose is refused by the managed lane."""
    monkeypatch.setattr(domain, "COORDINATOR_TRANSITIONS", frozenset({("file:code_name", "prose")}))
    assert buildable_families(shape_of(row("file", file="main.py"))) == ("code",)
    assert buildable_families(shape_of(row("file", file="main.py", managed=True))) == ("code",)


def _generation(parser_version):
    now = datetime(2026, 9, 18, 11, tzinfo=UTC)
    return k.Generation(
        source_id="s1",
        status="active",
        parser_version=parser_version,
        linker_version="linker-v1",
        embedding_profile="profile",
        created_at=now,
        published_at=now,
        manifest_hash="hash",
    )


def test_an_enabled_coordinator_correction_is_pending_until_its_lane_builds_it(monkeypatch):
    monkeypatch.setattr(domain, "COORDINATOR_TRANSITIONS", frozenset({("file:prose_name", "code")}))
    corrected = {"domain_override": "code", "domain_confirmed_at": CONFIRMED}

    managed = row("file", file="notes.md", managed=True) | corrected
    for generation in (None, _generation("mapped-prose-v1")):
        decision = resolve_domain(managed, shape_of(managed), active_generation=generation)
        assert (decision.family, decision.origin, decision.state) == ("code", "user", "pending_rebuild")
    decision = resolve_domain(managed, shape_of(managed), active_generation=_generation("managed-code-v1"))
    assert (decision.family, decision.state, decision.pending_rebuild) == ("code", "corrected", False)

    legacy = row("file", file="notes.md") | corrected
    decision = resolve_domain(legacy, shape_of(legacy))
    assert decision.state == "pending_rebuild"
    built = legacy | {"meta": {"file": "notes.md", "domain": "code"}}
    assert resolve_domain(built, shape_of(built)).state == "corrected"
    indexing = built | {"status": "indexing"}
    assert resolve_domain(indexing, shape_of(indexing)).state == "pending_rebuild"


def test_the_managed_parser_versions_the_resolver_reads_are_the_lanes_own():
    from hippo.ingest import code_generation

    expected = {code_generation.CODE_PARSER_VERSION: "code", "mapped-prose-v1": "prose"}
    assert domain.MANAGED_PARSER_FAMILIES == expected


# ------------------------------------------------------------------ overridden_classification


def test_no_override_returns_the_entry_itself():
    entry = partition("custom", evidence("name", "custom"))
    assert overridden_classification(entry, None) is entry


def test_an_override_returns_a_revalidated_copy_with_both_families_replaced():
    entry = partition("custom", evidence("name", "custom"))
    copied = overridden_classification(entry, "service")
    assert copied is not entry
    assert type(copied) is base.PartitionClassification
    assert (copied.family, copied.mapping.family) == ("service", "service")
    unchanged = copied.model_dump(exclude={"family", "mapping"})
    assert unchanged == entry.model_dump(exclude={"family", "mapping"})
    assert copied.mapping.model_dump(exclude={"family"}) == entry.mapping.model_dump(exclude={"family"})
    assert (entry.family, entry.mapping.family) == ("custom", "custom")


def test_an_override_that_is_not_a_family_name_fails_validation():
    with pytest.raises(ValidationError):
        overridden_classification(partition("custom"), "Not A Family")
