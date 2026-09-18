"""One resolver for a source's effective domain (family), and the one rule for what it may become.

Plan `ai_docs/plans/2026-09-18-knowledge-inventory-domain-plan.md` section 3.2, design D2, D4 and
D5. The resolver is pure: the caller supplies the batch-read records, so the Library's poll reads
the store once per record kind, never once per row (invariant I1).

Two layers meet here and neither may be imported. `hippo.knowledge` never imports `hippo.ingest`
(`tests/unit/test_layering.py`), so the coordinator's lane facts arrive as a `SourceShape` value
that `ingest.managed_activation.source_shape` computes. It never imports `hippo.connectors` either
(`tests/unit/test_connector_contract.py::test_knowledge_package_never_imports_connectors`, which
reads the text, so a `TYPE_CHECKING` import fails it too), so a partition classification is read
by its shape.

`buildable_families` is the only rule the UI, the routes, the CLI and MCP read for what a source may
be corrected to. A correction is offered only where a rebuild builds it in every lane the source
can still reach (plan table 2.4); with `COORDINATOR_TRANSITIONS` empty (OD1), every coordinator
source shows its domain as fixed, with a one-sentence reason.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, Self

from .model import Generation, SyncState
from .registry import CUSTOM_FAMILY

Family = str
Origin = Literal["lane", "declared", "content", "name", "fallback", "user"]
State = Literal["auto", "confirmed", "corrected", "pending_rebuild"]
Lane = Literal["legacy", "managed"]

# `hippo.connectors.base.UNCLASSIFIED`, which this package may not import; a test pins the two equal.
UNCLASSIFIED_OUTCOME = f"{CUSTOM_FAMILY}/unclassified"
# The classification rules that choose a family, strongest first (`connectors/classify.py`).
_RULE_ORIGINS: tuple[tuple[str, Origin], ...] = (
    ("descriptor", "declared"),
    ("declaration", "declared"),
    ("content", "content"),
    ("name", "name"),
)
# The family each managed coordinator's `parser_version` builds (`code_generation.py:81`,
# `prose_generation.py:228`); a test pins them to the lanes' own values.
MANAGED_PARSER_FAMILIES: Mapping[str, Family] = {"managed-code-v1": "code", "mapped-prose-v1": "prose"}


class PartitionClassification(Protocol):
    """The shape of `hippo.connectors.base.PartitionClassification` the resolver reads."""

    @property
    def family(self) -> str: ...

    @property
    def evidence(self) -> tuple[Any, ...]: ...

    @property
    def mapping(self) -> Any: ...

    def replace(self, **changes: Any) -> Self: ...


@dataclass(frozen=True)
class SourceShape:
    """The coordinator facts `managed_activation.source_shape` reads off a row."""

    kind: str  # text | file | archive | repo | sample | connector
    lane_family: Family  # "code" if the lane rule says code, else "prose"
    name_class: Literal["prose_name", "code_name", "other"]
    lanes: frozenset[Lane]  # lanes a rebuild of this row can still take


@dataclass(frozen=True)
class DomainDecision:
    family: Family
    natural: Family  # what automatic classification chose, ignoring the override
    origin: Origin
    state: State
    confirmed_at: str | None
    confirmed_by: str | None
    allowed: tuple[Family, ...]
    fixed_reason: str | None  # one sentence when len(allowed) == 1
    pending_rebuild: bool


# `(row_class, target)` rows, `row_class` in {"text", "file:prose_name", "unsupported"} and target
# "code". Empty by default (OD1): table 2.4 shows no coordinator transition changes the domain in
# substance. Enabling a row also needs plan tasks T1-C and T3-C.
COORDINATOR_TRANSITIONS: frozenset[tuple[str, Family]] = frozenset()

# Table 2.4: the lanes in which a rebuild of a row class under the target family builds.
# `("text", "code")` builds in the managed lane only through T1-C's text-to-file kind map
# (`managed_activation.py:743,758`), so enable that row together with the map.
_TRANSITION_LANES: Mapping[tuple[str, Family], frozenset[Lane]] = {
    ("text", "code"): frozenset({"legacy", "managed"}),
    ("file:prose_name", "code"): frozenset({"legacy", "managed"}),
    ("unsupported", "code"): frozenset({"legacy"}),
}


def buildable_families(
    shape: SourceShape,
    *,
    classification: PartitionClassification | None = None,
    descriptor_families: tuple[Family, ...] | None = None,
) -> tuple[Family, ...]:
    """The families a rebuild of this source can build; the first entry is the natural one."""
    natural = _natural(shape, classification)
    if shape.kind == "connector":
        if descriptor_families is not None and len(descriptor_families) > 1:
            return tuple(descriptor_families)
        return (natural,)
    if not shape.lanes:  # tombstoned: nothing rebuilds it
        return (natural,)
    row_class = _row_class(shape)
    targets = tuple(
        target
        for candidate, target in sorted(COORDINATOR_TRANSITIONS)
        if candidate == row_class
        and target != natural
        and shape.lanes <= _TRANSITION_LANES.get((candidate, target), frozenset())
    )
    return (natural, *targets)


def resolve_domain(
    source: Mapping[str, Any],
    shape: SourceShape,
    *,
    classification: PartitionClassification | None = None,
    descriptor_families: tuple[Family, ...] | None = None,
    active_generation: Generation | None = None,
    sync_state: SyncState | None = None,
    connector_kind: str | None = None,
) -> DomainDecision:
    """The effective domain of one source row: the override, then classification, then the lane.

    Never raises on a stored value: an override a coordinator row cannot build is ignored (the
    lane family stands), and an unreadable confirmation time leaves a correction pending.
    """
    natural = _natural(shape, classification)
    allowed = buildable_families(
        shape, classification=classification, descriptor_families=descriptor_families
    )
    override = source.get("domain_override")
    confirmed_at = source.get("domain_confirmed_at")
    if shape.kind == "connector":
        origin = _connector_origin(classification)
        honoured = override is not None
    else:
        origin = "lane"
        honoured = override is not None and override != natural and override in allowed
    if honoured:
        family, origin = override, "user"
        state: State = (
            "corrected"
            if _built(source, shape, override, confirmed_at, active_generation, sync_state)
            else "pending_rebuild"
        )
    else:
        family = natural
        state = "auto" if confirmed_at is None else "confirmed"
    return DomainDecision(
        family=family,
        natural=natural,
        origin=origin,
        state=state,
        confirmed_at=confirmed_at,
        confirmed_by=source.get("domain_confirmed_by"),
        allowed=allowed,
        fixed_reason=(
            _fixed_reason(shape, descriptor_families, connector_kind) if len(allowed) == 1 else None
        ),
        pending_rebuild=state == "pending_rebuild",
    )


def overridden_classification(
    entry: PartitionClassification, override: Family | None
) -> PartitionClassification:
    """The stored partition classification, with the user's family as its family and mapping family.

    `Contract.replace` re-validates through `model_validate`, so the strict contract checks the copy.
    """
    if override is None:
        return entry
    return entry.replace(family=override, mapping=entry.mapping.replace(family=override))


def _natural(shape: SourceShape, classification: PartitionClassification | None) -> Family:
    if shape.kind != "connector":
        return shape.lane_family
    return CUSTOM_FAMILY if classification is None else classification.family


def _connector_origin(classification: PartitionClassification | None) -> Origin:
    """The strongest rule among the evidence that chose the partition's family.

    Orchestrator decision (a deviation from plan 3.2's "family-level" wording): kind-level rows
    count too, when the family part of the outcome (`family` or `family/kind`) is the family,
    because the `descriptor` rule and a declaration with a kind are recorded only at kind level.
    """
    if classification is None:
        return "fallback"
    family = classification.family
    rules = {
        row.rule
        for row in classification.evidence
        if row.level in ("family", "kind")
        and row.outcome != UNCLASSIFIED_OUTCOME
        and row.outcome.split("/", 1)[0] == family
    }
    for rule, origin in _RULE_ORIGINS:
        if rule in rules:
            return origin
    return "fallback"


def _row_class(shape: SourceShape) -> str | None:
    if shape.kind == "text":
        return "text"
    if shape.kind == "file" and shape.name_class == "prose_name":
        return "file:prose_name"
    if shape.lanes == {"legacy"}:
        return "unsupported"
    return None


def _built(
    source: Mapping[str, Any],
    shape: SourceShape,
    override: Family,
    confirmed_at: str | None,
    active_generation: Generation | None,
    sync_state: SyncState | None,
) -> bool:
    """Whether the build that serves the source was made under the override (design D5)."""
    if shape.kind == "connector":
        confirmed = _instant(confirmed_at)
        synced = sync_state.last_success_at if sync_state is not None else None
        return confirmed is not None and synced is not None and synced >= confirmed
    if shape.lanes == {"managed"}:
        parser = active_generation.parser_version if active_generation is not None else None
        return MANAGED_PARSER_FAMILIES.get(parser) == override
    meta = source.get("meta") or {}
    return isinstance(meta, Mapping) and meta.get("domain") == override and source.get("status") == "ready"


def _instant(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _fixed_reason(
    shape: SourceShape, descriptor_families: tuple[Family, ...] | None, connector_kind: str | None
) -> str:
    if shape.kind == "connector":
        if not descriptor_families:
            return "This process does not know the connector's declared domains."
        subject = f"The {connector_kind} connector" if connector_kind else "This connector"
        return f"{subject} declares only the {descriptor_families[0]} domain."
    if shape.kind == "repo":
        return "Repositories are always built as code."
    if shape.kind == "archive":
        return "Zip archives are always built as code."
    if shape.kind == "text":
        return "Pasted text is always built as prose."
    if shape.kind == "file" and shape.name_class == "code_name":
        return "Files with a code extension are always built as code."
    if shape.kind == "file" and shape.name_class == "prose_name":
        return "Plain-text files are always built as prose."
    return "Documents are always read as prose."
