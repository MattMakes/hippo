"""The vocabulary the `incidents_ndjson` connector registers.

Nothing here registers itself. `hippo connector validate` registers this extension into a scratch
registry, and `hippo serve` registers it once an operator has enabled an instance of this kind
with `hippo connector enable incidents_ndjson <instance_url>`.

`connector_kinds` is load-bearing: it is the kind an operator's `Connector` row carries, and it
must equal this package's name and the descriptor's.

The incident family is the one specification family the repository had no kind for, so this is the
whole shape of "a family the kit covers and the code does not": one object kind with two fact
templates, one artifact kind for a record, and one windowed predicate the incident family owns,
pointing at the built-in `service` kind another family owns.

Everything imported here comes from `hippo.connectors.base`, which re-exports the registry's
definition models (ruling R-S2-1). A connector package never imports `hippo.knowledge.registry`
directly; the scaffold's own template does, and that is the one line of it this exemplar changed.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from hippo.connectors.base import ObjectKindDefinition, PredicateDefinition, TypeExtension

from .templates import INCIDENT_RESOLUTION, INCIDENT_SUMMARY

CONNECTOR_KIND = "incidents_ndjson"
FAMILY = "incident"
INCIDENT_KIND = "incident"
INCIDENT_RECORD = "incident_record"
SERVICE_KIND = "service"
AFFECTS = "AFFECTS"


class IncidentAttributes(BaseModel):
    """One incident's typed attributes.

    `extra="forbid"` is required of every extension kind: an attribute nobody declared is a mapping
    mistake, not a free-form field. Every field but the first six is optional, because a tool that
    has not resolved an incident has no resolution to report, and a template whose consumed
    attribute is `None` is not invoked (R-S2-5). That is what keeps an open incident from being
    described as "resolved in None minutes".
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    number: int
    title: str
    severity: str
    status: str
    service: str
    started_at: str
    resolved_at: str | None = None
    mttd_minutes: int | None = None
    mttm_minutes: int | None = None
    mttr_minutes: int | None = None


def incident_kind(**overrides) -> ObjectKindDefinition:
    fields = {
        "name": INCIDENT_KIND,
        "family": FAMILY,
        # `instance` is filled by the kit from the `Connector` row and is never emitted (M16), so
        # one tool's incident id cannot collide with another instance's.
        "key_template": ("instance", "incident_id"),
        "key_prefix": "inc",
        "attrs_model": IncidentAttributes,
        "label_template": "INC-{number}",
        "fact_templates": (INCIDENT_SUMMARY, INCIDENT_RESOLUTION),
    }
    return ObjectKindDefinition(**(fields | overrides))


def affects_predicate(**overrides) -> PredicateDefinition:
    """`AFFECTS`: incident to service, dated by the incident's own start and resolution.

    `windowed=True` is what makes the edge carry `valid_from` and `valid_to` from the record rather
    than from the run. The object kind is the built-in `service`, whose family this connector does
    not own: ownership is checked on the edge, never on its endpoints (ruling R6 / R-S2-6).
    """
    fields = {
        "name": AFFECTS,
        "subject_kinds": frozenset({INCIDENT_KIND}),
        "object_kinds": frozenset({SERVICE_KIND}),
        "owner_families": frozenset({FAMILY}),
        "canonical_direction": "subject_to_object",
        "family_default": "deterministic",
        "sources_allowed": frozenset({"metadata"}),
        # Ruling R71 fixes the statement as "... affects service checkout", so the verb phrase is
        # the present tense the ruling quotes, not the plan's "affected".
        "verb_phrase": "affects",
        "windowed": True,
    }
    return PredicateDefinition(**(fields | overrides))


EXTENSION = TypeExtension(
    object_kinds=(incident_kind(),),
    artifact_kinds=(INCIDENT_RECORD,),
    predicates=(affects_predicate(),),
    connector_kinds=(CONNECTOR_KIND,),
)
