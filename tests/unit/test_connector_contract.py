"""The connector contract: every emission and protocol record, its validators and its messages.

Plan `ai_docs/plans/cdk-s2-contract.md` sections 4.1, 4.6 and 14, as amended by the rulings this
slice's brief names (R24/R42 the passage bound, R26 the one counter, R46 `extension`, R48
`span_policy_id`, R53 `NodeRef.instance`) and by the orchestrator's R-S2-10 message (the registry
accessors are re-exported here, so a connector never imports `hippo.knowledge.registry`).
"""

import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

import hippo.knowledge
from hippo.connectors import base
from hippo.knowledge import model as k
from hippo.knowledge.contract import Contract, Text
from hippo.knowledge.identity import canonical_json
from hippo.knowledge.locators import LocatorBase
from hippo.knowledge.registry import (
    EvidenceSourceDefinition,
    FactTemplate,
    LocatorKindDefinition,
    ObjectKindDefinition,
    PredicateDefinition,
    Registry,
    TypeExtension,
    connector_configuration,
    current_registry,
    extension_scope,
)

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)
LATER = datetime(2026, 9, 15, 13, tzinfo=UTC)


class IncidentAttributes(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    title: str
    severity: str | None = None


class IncidentEventLocator(LocatorBase):
    kind: Literal["incident_event"] = "incident_event"
    event_id: Text


class IncidentConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    export_path: str = "incidents.ndjson"


class OpenConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    export_path: str = "incidents.ndjson"


SEVERITY = FactTemplate(
    name="severity", version="1", consumes=("severity",), text="{label} has severity {severity}"
)


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
                fact_templates=(SEVERITY,),
            ),
        ),
        artifact_kinds=("incident_export",),
        locator_kinds=(LocatorKindDefinition(name="incident_event", model=IncidentEventLocator),),
        connector_kinds=("incident_ndjson",),
        evidence_sources=(
            EvidenceSourceDefinition(
                name="pager_feed", family="deterministic", evidence_class="catalog_observed"
            ),
        ),
        predicates=(
            PredicateDefinition(
                name="AFFECTS_FIXTURE",
                subject_kinds=frozenset({"incident_fixture"}),
                object_kinds=frozenset({"service"}),
                owner_families=frozenset({"incident"}),
                canonical_direction="subject_to_object",
                family_default="deterministic",
                sources_allowed=frozenset({"pager_feed", "metadata"}),
                verb_phrase="affects",
            ),
        ),
    )


@pytest.fixture
def registry():
    """The current registry, extended with the incident fixture and frozen for the test."""
    with extension_scope() as scoped:
        scoped.register(incident_extension())
        scoped.freeze()
        yield scoped


def descriptor(**changes) -> base.ConnectorDescriptor:
    value = base.ConnectorDescriptor(
        name="incidents_ndjson",
        version="1",
        families=("incident",),
        kinds=("incident_fixture", "service"),
        predicates=("AFFECTS_FIXTURE",),
        artifact_kinds=("incident_export",),
        locator_kinds=("file_lines",),
        capabilities=base.ConnectorCapabilities(acls=True),
        config_model=IncidentConfig,
        credentials=(base.CredentialRequirement(name="incidents_token", scopes=("read",)),),
        parsers=(base.ParserVersion(name="json", version="1"),),
        extension=incident_extension(),
    )
    return value.replace(**changes) if changes else value


def external_ref(**changes) -> base.ExternalRef:
    value = base.ExternalRef(partition="export", artifact_kind="incident_export", external_id="INC-2210")
    return value.replace(**changes) if changes else value


def policy_id() -> str:
    return k.AccessPolicy(
        workspace_id="workspace",
        origin="provider",
        scope_key="connector:c:incident_export:INC-2210",
        mode="workspace",
        verified_at=NOW,
        expires_at=LATER,
    ).id


def revision_input(data: bytes = b"{}", *, hashed: bytes | None = None, **changes) -> base.RevisionInput:
    """A revision input over `data`; `hashed` is the bytes the revision's content hash covers."""
    artifact = k.Artifact(
        workspace_id="workspace",
        source_id="source",
        connector_id="connector",
        provider_instance="https://incidents.example",
        kind="incident_export",
        external_id="INC-2210",
        canonical_uri="https://incidents.example/incidents/INC-2210",
        policy_id=policy_id(),
    )
    revision = k.ArtifactRevision(
        artifact_id=artifact.id,
        provider_revision="2026-09-15T12:00:00Z",
        content_hash=_sha256(data if hashed is None else hashed),
        raw_uri="raw://incidents/INC-2210",
        observed_at=NOW,
        lifecycle="active",
    )
    fields = {
        "partition": "export",
        "artifact": artifact,
        "revision": revision,
        "data": data,
        "config": IncidentConfig(),
        "mapping": base.TypeMapping(family="incident"),
        "registry": current_registry(),
        "span_policy_id": artifact.policy_id,
    }
    return base.RevisionInput(**(fields | changes))


def _sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------ the contract records


def _contracts() -> list[type[Contract]]:
    return sorted(
        (
            value
            for value in vars(base).values()
            if isinstance(value, type) and issubclass(value, Contract) and value.__module__ == base.__name__
        ),
        key=lambda contract: contract.__name__,
    )


def test_every_contract_is_frozen_strict_and_forbids_extra_fields() -> None:
    contracts = _contracts()
    assert {contract.__name__ for contract in contracts} >= {
        "ConnectorCapabilities",
        "ConnectorDescriptor",
        "EmissionBatch",
        "NodeEmission",
        "NodeRef",
        "RawFetch",
        "RevisionInput",
        "TypeMapping",
    }
    for contract in contracts:
        config = contract.model_config
        assert config["frozen"] is True, contract
        assert config["extra"] == "forbid", contract
        assert config["strict"] is True, contract
        assert config["revalidate_instances"] == "always", contract


def test_sync_connector_and_connector_protocols_are_runtime_checkable() -> None:
    class Sync:
        descriptor = descriptor()

        def probe(self, config, clock):  # pragma: no cover - protocol shape only
            raise NotImplementedError

        def list_changes(self, config, cursor):  # pragma: no cover - protocol shape only
            raise NotImplementedError

        def fetch(self, config, ref):  # pragma: no cover - protocol shape only
            raise NotImplementedError

        def fetch_policy(self, config, ref):  # pragma: no cover - protocol shape only
            raise NotImplementedError

    class Full(Sync):
        def emit(self, revision, mapping):  # pragma: no cover - protocol shape only
            raise NotImplementedError

    assert isinstance(Sync(), base.SyncConnector)
    assert not isinstance(Sync(), base.Connector)
    assert isinstance(Full(), base.SyncConnector)
    assert isinstance(Full(), base.Connector)


def test_capabilities_declare_emit_or_coordinator_lane_derivation() -> None:
    assert base.ConnectorCapabilities().derivation == "emit"
    assert base.ConnectorCapabilities(derivation="coordinator_lane").derivation == "coordinator_lane"
    with pytest.raises(ValueError):
        base.ConnectorCapabilities(derivation="lane")
    assert base.ConnectorCapabilities().inventory is False


def test_base_reexports_the_registry_definition_classes() -> None:
    import hippo.knowledge.registry as registry_module

    for name in ("TypeExtension", "ObjectKindDefinition", "PredicateDefinition", "FactTemplate", "Registry"):
        assert getattr(base, name) is getattr(registry_module, name), name


def test_base_reexports_the_registry_accessors_so_a_connector_never_imports_the_registry() -> None:
    """The orchestrator's R-S2-10 addition: `probe` and the kit reach the registry through `base`."""
    import hippo.knowledge.registry as registry_module

    for name in ("current_registry", "use_registry", "extension_scope"):
        assert getattr(base, name) is getattr(registry_module, name), name


def test_the_passage_bound_is_the_approximated_token_bound_and_one_counter_measures_it() -> None:
    """R24 and R42: 6,000 characters approximate the specification's 1,500 tokens (R26's counter)."""
    from hippo.ingest import chunker

    assert base.PASSAGE_CHAR_BOUND == 6000
    assert base.token_count("abc") == 3
    assert base.token_count("") == 0
    assert base.token_count("é") == 1
    source = Path(chunker.__file__).read_text()
    assert "size_chars" in source, "the chunker still budgets in characters"


def test_unclassified_is_the_counted_outcome_and_never_an_object_kind() -> None:
    assert base.UNCLASSIFIED == "custom/unclassified"
    assert base.UNCLASSIFIED not in current_registry().object_kinds()


# ------------------------------------------------------------------ the descriptor


def test_descriptor_refuses_duplicates_and_missing_families_artifact_or_locator_kinds() -> None:
    for field in ("families", "artifact_kinds", "locator_kinds"):
        with pytest.raises(ValueError) as error:
            descriptor(**{field: ()})
        assert "A connector declares at least one family, artifact kind and locator kind" in str(error.value)
    with pytest.raises(ValueError) as error:
        descriptor(kinds=("incident_fixture", "incident_fixture"))
    assert "Connector descriptor lists kinds 'incident_fixture' twice" in str(error.value)
    with pytest.raises(ValueError) as error:
        descriptor(
            parsers=(
                base.ParserVersion(name="json", version="1"),
                base.ParserVersion(name="json", version="1"),
            )
        )
    assert "Connector descriptor lists parsers 'json@1' twice" in str(error.value)
    with pytest.raises(ValueError) as error:
        descriptor(version="a version with spaces")
    assert "Connector version must be a short token such as 1.2.0" in str(error.value)


def test_descriptor_config_model_must_forbid_extra_fields() -> None:
    with pytest.raises(ValueError) as error:
        descriptor(config_model=OpenConfig)
    assert 'Connector configuration model OpenConfig must set extra="forbid"' in str(error.value)


def test_descriptor_carries_the_extension_that_registers_its_vocabulary() -> None:
    """Ruling R46: the descriptor names its own `TypeExtension`, which S3 compares with the registry."""
    assert descriptor().extension == incident_extension()
    with pytest.raises(ValueError):
        descriptor(extension=None)


def test_descriptor_validate_against_names_every_unregistered_type_in_a_skeleton(registry) -> None:
    descriptor().validate_against(registry)
    unregistered = descriptor(
        kinds=("incident_fixture", "outage"),
        predicates=("AFFECTS_FIXTURE", "PAGES"),
        artifact_kinds=("incident_export", "pager_dump"),
        locator_kinds=("file_lines", "pager_event"),
        families=("incident", "operations"),
    )
    with pytest.raises(base.RegistrationRequired) as error:
        unregistered.validate_against(registry)
    raised = error.value
    assert raised.kinds == ("outage",)
    assert raised.predicates == ("PAGES",)
    message = str(raised)
    for name in ("outage", "PAGES", "pager_dump", "pager_event", "operations"):
        assert name in message, name
        assert name in raised.skeleton, name
    assert "TypeExtension(" in raised.skeleton
    assert isinstance(raised, base.ContractError)


def test_descriptor_predicate_it_does_not_own_is_accepted_as_a_view(registry) -> None:
    """A connector declares a predicate another family owns; ownership is checked on edges (R6)."""
    descriptor(families=("prose",), kinds=("incident_fixture", "service")).validate_against(registry)


def test_descriptor_configuration_is_the_registry_connector_configuration_without_a_fingerprint(
    registry,
) -> None:
    value = base.descriptor_configuration(descriptor(), registry)
    assert value == connector_configuration(
        name="incidents_ndjson",
        version="1",
        templates=registry.declared_template_versions(("incident_fixture", "service")),
        parsers=["json@1"],
    )
    assert value["connector"]["templates"] == {"incident_fixture.severity": "1"}
    assert registry.fingerprint() not in canonical_json(value)


def test_parser_version_spelling_round_trips_and_refuses_free_text() -> None:
    parser = base.ParserVersion(name="tree-sitter/python", version="0.23")
    assert parser.spelling == "tree-sitter/python@0.23"
    assert base.ParserVersion.parse("tree-sitter/python@0.23") == parser
    assert base.ParserVersion.parse("json@1").spelling == "json@1"
    for spelling in ("tree-sitter/python", "Tree Sitter@0.23", "@1", "json@"):
        with pytest.raises(ValueError) as error:
            base.ParserVersion.parse(spelling)
        assert "Parser version must be spelled name@version, e.g. tree-sitter/python@0.23" in str(error.value)


# ------------------------------------------------------------------ the provider records


def test_raw_fetch_refuses_a_different_external_id_and_a_credentialed_uri() -> None:
    def fetch(**changes) -> base.RawFetch:
        fields = {
            "ref": external_ref(),
            "data": b"{}",
            "content_type": "application/json",
            "external_id": "INC-2210",
            "canonical_uri": "https://incidents.example/incidents/INC-2210",
        }
        return base.RawFetch(**(fields | changes))

    assert fetch().external_id == "INC-2210"
    with pytest.raises(ValueError) as error:
        fetch(external_id="INC-9999")
    assert "RawFetch.external_id must equal the requested ref" in str(error.value)
    with pytest.raises(ValueError) as error:
        fetch(canonical_uri="https://user:s3cret@incidents.example/incidents/INC-2210")
    assert "Canonical URIs cannot carry credentials" in str(error.value)
    assert "s3cret" not in str(error.value), "a refusal never echoes the credential"


def test_raw_fetch_source_time_requires_its_original_spelling() -> None:
    fields = {
        "ref": external_ref(),
        "data": b"{}",
        "content_type": "application/json",
        "external_id": "INC-2210",
        "canonical_uri": "https://incidents.example/incidents/INC-2210",
    }
    complete = base.RawFetch(
        **fields,
        source_updated_at=NOW,
        source_timestamp_original="2026-09-15T12:00:00Z",
        source_timezone="UTC",
        source_precision="second",
    )
    assert complete.source_precision == "second"
    assert base.RawFetch(**fields).source_precision == "unknown"
    for changes in ({"source_updated_at": NOW}, {"source_timestamp_original": "2026-09-15T12:00:00Z"}):
        with pytest.raises(ValueError) as error:
            base.RawFetch(**fields, **changes)
        assert "A source timestamp needs its original spelling, and only with a timestamp" in str(error.value)


def test_external_id_has_no_control_characters() -> None:
    with pytest.raises(ValueError) as error:
        external_ref(external_id="INC\n2210")
    assert "External ids cannot contain control characters" in str(error.value)


def test_unknown_policy_observation_carries_no_principals() -> None:
    unknown = base.PolicyObservation(ref=external_ref(), state="unknown")
    assert unknown.mode is None and unknown.allow_users == ()
    for changes in (
        {"mode": "workspace"},
        {"allow_users": ("alice",)},
        {"deny_groups": ("oncall",)},
    ):
        with pytest.raises(ValueError) as error:
            base.PolicyObservation(ref=external_ref(), state="unknown", **changes)
        assert "An unknown policy carries no principals; the runtime stores it as deny" in str(error.value)


def test_known_restricted_policy_without_an_allowed_principal_is_refused() -> None:
    assert base.PolicyObservation(ref=external_ref(), state="known", mode="workspace").allow_users == ()
    restricted = base.PolicyObservation(
        ref=external_ref(), state="known", mode="restricted", allow_groups=("oncall",)
    )
    assert restricted.allow_groups == ("oncall",)
    with pytest.raises(ValueError) as error:
        base.PolicyObservation(ref=external_ref(), state="known", mode="restricted")
    assert (
        'A known restricted policy needs at least one allowed principal; report state="unknown" instead'
        in str(error.value)
    )
    with pytest.raises(ValueError) as error:
        base.PolicyObservation(ref=external_ref(), state="known")
    assert "A known policy needs a mode" in str(error.value)


# ------------------------------------------------------------------ the principal map (M9, R44)


def observation(**changes) -> base.PolicyObservation:
    fields = {
        "ref": external_ref(),
        "state": "known",
        "mode": "restricted",
        "allow_users": ("provider-alice",),
        "allow_groups": ("provider-oncall",),
    }
    return base.PolicyObservation(**(fields | changes))


MAP = base.PrincipalMap(
    users={"provider-alice": "alice"}, groups={"provider-oncall": "oncall", "provider-sre": "sre"}
)


def test_the_principal_map_translates_provider_principals_to_local_ids() -> None:
    mapped, dropped = base.map_principals(observation(), MAP)
    assert mapped.allow_users == ("alice",)
    assert mapped.allow_groups == ("oncall",)
    assert mapped.state == "known" and mapped.mode == "restricted"
    assert dropped == 0
    assert base.PrincipalMap().users == {}


def test_an_unmapped_deny_principal_makes_the_observation_unknown() -> None:
    """R44 rule 1: dropping an unmapped deny entry would grant the workspace to its members."""
    for changes in ({"deny_users": ("provider-mallory",)}, {"deny_groups": ("provider-contractors",)}):
        mapped, _ = base.map_principals(
            observation(mode="workspace", allow_users=(), allow_groups=(), **changes), MAP
        )
        assert mapped.state == "unknown"
        assert mapped.mode is None
        assert (mapped.allow_users, mapped.allow_groups, mapped.deny_users, mapped.deny_groups) == (
            (),
            (),
            (),
            (),
        )
    mapped, _ = base.map_principals(
        observation(mode="workspace", allow_users=(), allow_groups=(), deny_groups=("provider-sre",)), MAP
    )
    assert mapped.state == "known" and mapped.deny_groups == ("sre",)


def test_an_allow_list_the_map_empties_becomes_unknown() -> None:
    """R44 rule 2, read per list (orchestrator, 2026-09-15): either emptied allow list denies."""
    for changes in (
        {"allow_users": ("provider-nobody",)},
        {"allow_groups": ("provider-nobody",)},
    ):
        mapped, dropped = base.map_principals(observation(**changes), MAP)
        assert mapped.state == "unknown", changes
        assert mapped.mode is None and mapped.allow_users == () and mapped.allow_groups == ()
        assert dropped == 1


def test_unmapped_allow_entries_are_dropped_and_counted() -> None:
    """R44 rule 3: the list keeps its mapped principals, and the drop is counted, never silent."""
    mapped, dropped = base.map_principals(
        observation(allow_users=("provider-alice", "provider-nobody"), allow_groups=("provider-oncall",)), MAP
    )
    assert mapped.allow_users == ("alice",)
    assert mapped.allow_groups == ("oncall",)
    assert mapped.state == "known"
    assert dropped == 1
    unknown, dropped = base.map_principals(base.PolicyObservation(ref=external_ref(), state="unknown"), MAP)
    assert unknown.state == "unknown" and dropped == 0


def test_change_page_cannot_mix_partitions_and_keeps_change_order() -> None:
    changes = tuple(
        base.Change(ref=external_ref(external_id=f"INC-{index}"), operation="upsert") for index in range(3)
    )
    page = base.ChangePage(
        partition="export",
        changes=changes,
        next_cursor=base.SyncCursor(partition="export"),
        complete=True,
    )
    assert tuple(change.ref.external_id for change in page.changes) == ("INC-0", "INC-1", "INC-2")
    assert page.warnings == ()
    with pytest.raises(ValueError) as error:
        base.ChangePage(
            partition="export",
            changes=(base.Change(ref=external_ref(partition="other"), operation="delete"),),
            next_cursor=None,
        )
    assert "A change page cannot mix partitions" in str(error.value)
    with pytest.raises(ValueError) as error:
        base.ChangePage(partition="export", changes=(), next_cursor=base.SyncCursor(partition="other"))
    assert "A change page cannot mix partitions" in str(error.value)


# ------------------------------------------------------------------ the mapping records


def test_type_mapping_to_an_unregistered_kind_raises_registration_required(registry) -> None:
    mapping = base.TypeMapping(
        family="incident",
        kinds=(base.KindMapping(provider_type="incident", kind="incident_fixture"),),
        predicates=("AFFECTS_FIXTURE",),
    )
    mapping.validate_against(registry)
    unmapped = base.TypeMapping(family="incident", kinds=(base.KindMapping(provider_type="page", kind=None),))
    unmapped.validate_against(registry)
    with pytest.raises(base.RegistrationRequired) as error:
        base.TypeMapping(
            family="incident", kinds=(base.KindMapping(provider_type="outage", kind="outage"),)
        ).validate_against(registry)
    assert error.value.kinds == ("outage",)
    assert "outage" in error.value.skeleton
    with pytest.raises(ValueError) as error:
        base.TypeMapping(
            family="incident",
            kinds=(
                base.KindMapping(provider_type="incident", kind="incident_fixture"),
                base.KindMapping(provider_type="incident", kind=None),
            ),
        )
    assert "Provider type 'incident' is mapped twice" in str(error.value)


def test_type_mapping_attribute_must_be_declared_by_the_kind(registry) -> None:
    base.TypeMapping(
        family="incident",
        kinds=(base.KindMapping(provider_type="incident", kind="incident_fixture"),),
        attributes=(
            base.AttributeMapping(kind="incident_fixture", attribute="severity", provider_field="fields.sev"),
        ),
    ).validate_against(registry)
    with pytest.raises(base.ContractError) as error:
        base.TypeMapping(
            family="incident",
            attributes=(
                base.AttributeMapping(
                    kind="incident_fixture", attribute="impact", provider_field="fields.imp"
                ),
            ),
        ).validate_against(registry)
    assert "Kind incident_fixture declares no attribute impact" in str(error.value)


def test_mapping_hash_covers_the_mapping_and_its_classifier() -> None:
    mapping = base.TypeMapping(family="incident")
    assert mapping.mapping_hash == mapping.replace(family="incident").mapping_hash
    assert mapping.mapping_hash != mapping.replace(predicates=("AFFECTS_FIXTURE",)).mapping_hash
    assert len(mapping.mapping_hash) == 64


# ------------------------------------------------------------------ the revision input


def test_revision_input_refuses_bytes_that_differ_from_the_content_hash(registry) -> None:
    revision_input(b'{"id": "INC-2210"}', registry=registry)
    with pytest.raises(ValueError) as error:
        # The revision's hash covers other bytes than the ones `emit` would read.
        revision_input(b'{"id": "INC-2210"}', hashed=b"other bytes", registry=registry)
    assert "Revision bytes differ from the revision's content hash" in str(error.value)


def test_revision_input_refuses_a_revision_of_another_artifact(registry) -> None:
    other = k.ArtifactRevision(
        artifact_id="artifact-other",
        content_hash=_sha256(b"{}"),
        raw_uri="raw://other",
        observed_at=NOW,
        lifecycle="active",
    )
    with pytest.raises(ValueError) as error:
        revision_input(registry=registry, revision=other)
    assert "Revision does not belong to its artifact" in str(error.value)


def test_revision_input_refuses_an_unfrozen_registry() -> None:
    with extension_scope() as scoped:
        scoped.register(incident_extension())
        with pytest.raises(ValueError) as error:
            revision_input(registry=scoped)
        assert "emit requires a frozen registry" in str(error.value)
        scoped.freeze()
        assert revision_input(registry=scoped).registry is scoped


def test_revision_input_carries_the_span_policy_of_the_first_capture(registry) -> None:
    """Ruling R48: every span keeps the policy the revision was first captured under."""
    value = revision_input(registry=registry)
    assert value.span_policy_id == value.artifact.policy_id
    stored = policy_id()
    assert revision_input(registry=registry, span_policy_id=stored).span_policy_id == stored
    for wrong in ("", "policy-1", "accesspolicy-not-a-digest"):
        with pytest.raises(ValueError) as error:
            revision_input(registry=registry, span_policy_id=wrong)
        assert "A revision input names the AccessPolicy its spans keep" in str(error.value)


# ------------------------------------------------------------------ the emission records


def node_ref(**changes) -> base.NodeRef:
    value = base.NodeRef(kind="incident_fixture", key={"tool": "pagerduty", "incident_id": "INC-2210"})
    return value.replace(**changes) if changes else value


def span_ref() -> base.SpanRef:
    return base.SpanRef(locator_kind="file_lines", locator={"path": "incidents.ndjson", "start": 1, "end": 1})


def support() -> tuple[base.SupportEmission, ...]:
    return (base.SupportEmission(spans=(span_ref(),)),)


def node_emission(**changes) -> base.NodeEmission:
    fields = {
        "ref": node_ref(),
        "attrs": {"title": "Checkout is down"},
        "span": span_ref(),
        "source": "metadata",
        "metadata_origin": "catalog",
    }
    return base.NodeEmission(**(fields | changes))


def edge_emission(**changes) -> base.EdgeEmission:
    fields = {
        "subject": node_ref(),
        "predicate": "AFFECTS_FIXTURE",
        "object": base.NodeRef(kind="service", key={"reference": "component:default/checkout"}),
        "family": "deterministic",
        "source": "metadata",
        "metadata_origin": "catalog",
        "weight": 1.0,
        "support": support(),
    }
    return base.EdgeEmission(**(fields | changes))


def test_node_reference_needs_its_key_parts_and_may_declare_a_foreign_instance() -> None:
    """Ruling R53: an identity-only foreign endpoint carries the instance that minted its name."""
    assert node_ref().instance is None
    foreign = base.NodeRef(
        kind="service",
        key={"reference": "component:default/checkout"},
        instance="HTTPS://Backstage.Example:443/",
    )
    assert foreign.instance == "https://backstage.example"
    for key in ({}, {"tool": ""}):
        with pytest.raises(ValueError) as error:
            base.NodeRef(kind="incident_fixture", key=key)
        assert "A node reference needs its key parts" in str(error.value)
    with pytest.raises(ValueError) as error:
        base.NodeRef(kind="service", key={"reference": "r"}, instance="https://u:s3cret@backstage.example")
    assert "s3cret" not in str(error.value), "a refusal never echoes the credential"


def test_node_emission_cannot_carry_an_id_or_an_evidence_class() -> None:
    for extra in ({"id": "object-1"}, {"evidence_class": "declared"}, {"object_id": "object-1"}):
        with pytest.raises(ValueError) as error:
            node_emission(**extra)
        assert "extra" in str(error.value).lower()
    with pytest.raises(ValueError) as error:
        base.NodeRef(kind="incident_fixture", key={"tool": "t", "incident_id": "i"}, id="object-1")
    assert "extra" in str(error.value).lower()


def test_node_emission_metadata_origin_and_timestamp_rules() -> None:
    assert node_emission().ts is None
    timed = node_emission(ts=NOW, ts_original="2026-09-15T12:00:00Z", ts_precision="second")
    assert timed.ts_precision == "second"
    with pytest.raises(ValueError) as error:
        node_emission(ts=NOW)
    assert "A node ts needs its original spelling, and only with a ts" in str(error.value)
    with pytest.raises(ValueError) as error:
        node_emission(source="parser")
    assert "Metadata provenance must say catalog or declaration" in str(error.value)
    assert node_emission(source="parser", metadata_origin=None).metadata_origin is None


def test_edge_emission_weight_rule_metadata_and_window_rules() -> None:
    assert edge_emission().weight == 1.0
    with pytest.raises(ValueError) as error:
        edge_emission(weight=0.5)
    assert "Deterministic edges carry weight 1.0" in str(error.value)
    assert edge_emission(family="probabilistic", source="similarity", metadata_origin=None, weight=0.5)
    rule_edge = edge_emission(
        source="rule", metadata_origin=None, rule="same_service_name", rule_evidence="checkout == checkout"
    )
    assert rule_edge.rule == "same_service_name"
    for changes in (
        {"source": "rule", "metadata_origin": None},
        {"rule": "same_service_name", "rule_evidence": "x"},
    ):
        with pytest.raises(ValueError) as error:
            edge_emission(**changes)
        assert (
            "A rule-derived edge names its rule and its evidence, and only a rule-derived edge does"
            in str(error.value)
        )
    with pytest.raises(ValueError) as error:
        edge_emission(unit="u1", source_statement="INSERT INTO incidents ...")
    assert "An edge reuses a statement unit or quotes a source statement, not both" in str(error.value)
    assert edge_emission(valid_from=NOW, valid_to=LATER).window_precision == "unknown"
    for changes in (
        {"valid_to": LATER},
        {"valid_from": LATER, "valid_to": NOW},
        {"valid_from": NOW, "valid_to": NOW},
    ):
        with pytest.raises(ValueError) as error:
            edge_emission(**changes)
        assert "An edge window needs a start before its end" in str(error.value)


def test_sql_part_refuses_nul_and_keeps_its_dialect() -> None:
    part = base.SqlPart(original="Orders", dialect="postgres")
    assert part.quoted is False and part.collation is None
    with pytest.raises(ValueError) as error:
        base.SqlPart(original="Ord\x00ers", dialect="tsql")
    assert "SQL identifiers cannot contain NUL" in str(error.value)


def test_unit_offsets_come_as_a_pair() -> None:
    unit = base.UnitEmission(
        key="u1", passage="p1", ordinal=0, kind="sentence", span=span_ref(), start=0, end=12
    )
    assert (unit.start, unit.end) == (0, 12)
    assert base.UnitEmission(key="u2", passage="p1", ordinal=1, kind="row", span=span_ref()).start is None
    for changes in ({"start": 0}, {"end": 12}, {"start": 12, "end": 12}, {"start": 13, "end": 12}):
        with pytest.raises(ValueError) as error:
            base.UnitEmission(key="u3", passage="p1", ordinal=2, kind="row", span=span_ref(), **changes)
        assert "Unit offsets come as a nonempty start/end pair" in str(error.value)


def test_parse_failure_reason_is_a_code_not_a_message() -> None:
    failure = base.ParseFailure(
        family="incident", reason="malformed_json", parser=base.ParserVersion.parse("json@1")
    )
    assert failure.count == 1 and failure.scope == "record"
    with pytest.raises(ValueError):
        base.ParseFailure(family="incident", reason="Expecting value: line 1 column 1 (char 0)")


def test_emission_batch_refuses_duplicate_and_dangling_keys() -> None:
    passage = base.PassageEmission(key="p1", span=span_ref(), title="INC-2210")
    unit = base.UnitEmission(key="u1", passage="p1", ordinal=0, kind="row", span=span_ref())
    batch = base.EmissionBatch(
        nodes=(node_emission(),), edges=(edge_emission(unit="u1"),), passages=(passage,), units=(unit,)
    )
    assert batch.hints == () and batch.failures == ()
    with pytest.raises(ValueError) as error:
        base.EmissionBatch(passages=(passage, passage))
    assert "Emission key 'p1' is duplicated" in str(error.value)
    with pytest.raises(ValueError) as error:
        base.EmissionBatch(units=(unit, unit.replace(ordinal=1)))
    assert "Emission key 'u1' is duplicated" in str(error.value)
    with pytest.raises(ValueError) as error:
        base.EmissionBatch(passages=(passage,), units=(unit.replace(passage="missing"),))
    assert "Emission names missing passage 'missing'" in str(error.value)
    with pytest.raises(ValueError) as error:
        base.EmissionBatch(edges=(edge_emission(unit="u9"),))
    assert "Emission names missing unit 'u9'" in str(error.value)


def test_support_and_alias_emissions_need_their_spans() -> None:
    alias = base.AliasEmission(
        a=node_ref(),
        b=base.NodeRef(kind="incident_fixture", key={"tool": "pagerduty", "incident_id": "INC-2211"}),
        rule="declared_in_export",
        support=support(),
    )
    assert alias.rule == "declared_in_export"
    with pytest.raises(ValueError):
        base.SupportEmission(spans=())
    with pytest.raises(ValueError):
        base.ReverseViewHint(predicate="AFFECTS_FIXTURE", subject=node_ref(), object=node_ref(), support=())


def test_family_and_clock_are_importable_from_base() -> None:
    class ModelWithFamily(Contract):
        family: base.Family

    assert ModelWithFamily(family="incident").family == "incident"
    with pytest.raises(ValueError):
        ModelWithFamily(family="Incident Family")

    def clock() -> datetime:
        return NOW

    checked: base.Clock = clock
    assert checked() == NOW


# ------------------------------------------------------------------ layering


REVERSE_IMPORT = re.compile(
    r"^[ \t]*(?:from[ \t]+(?:\.{2,}connectors|hippo\.connectors)\b"
    r"|from[ \t]+(?:\.{2,}|hippo)[ \t]+import[ \t]+connectors\b"
    r"|import[ \t]+hippo\.connectors\b)",
    re.MULTILINE,
)


def test_knowledge_package_never_imports_connectors() -> None:
    """`connectors` imports `knowledge` and `ingest`; nothing imports `connectors` back (S2 §2)."""
    knowledge = Path(hippo.knowledge.__file__).parent
    offenders = {
        path.name: [line for line in path.read_text().splitlines() if REVERSE_IMPORT.match(line)]
        for path in sorted(knowledge.rglob("*.py"))
        if REVERSE_IMPORT.search(path.read_text())
    }
    assert offenders == {}, f"knowledge -> connectors imports: {offenders}"
    assert REVERSE_IMPORT.search("from hippo.connectors import base"), "the guard matches a real import"


@pytest.mark.parametrize(
    "module",
    ["hippo.connectors", "hippo.connectors.base", "hippo.connectors.keys", "hippo.connectors.classify"],
)
def test_connectors_modules_import_first_in_a_fresh_interpreter(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"], capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0, result.stderr[-2000:]


def test_the_connectors_package_marker_imports_nothing() -> None:
    """`hippo --help` stays cheap: importing the package loads no submodule (S5 R-S2-4)."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, hippo.connectors;"
            "print(sorted(n for n in sys.modules if n.startswith('hippo.connectors')))",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "['hippo.connectors']", result.stdout


def test_registry_lookups_of_unregistered_names_reach_the_contract_as_unregistered_name() -> None:
    assert issubclass(base.RegistrationRequired, base.ContractError)
    assert issubclass(base.ContractError, ValueError)
    with pytest.raises(KeyError):
        Registry.with_builtins().object_kind("outage")
