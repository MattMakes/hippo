"""The coordinator lane: the kit's sync half in front of a reviewed coordinator's derivation half.

Design `docs/spec/connector-developer-kit.md` section 11, plan `ai_docs/plans/cdk-s5-port.md`
section 3, ruling R1. The local and git connectors answer `probe`, `list_changes`, `fetch` and
`fetch_policy`; the prose and code coordinators keep emission, binding, staging and publication,
because a per-revision `emit` cannot reproduce their output byte for byte (plan section 3.1 gives
the five anchored reasons). A connector that declares
`capabilities.derivation == "coordinator_lane"` says so in its descriptor, so a kit assertion that
needs `emit` is skipped by declaration and never by exception.

This module imports nothing from `hippo.ingest.managed_activation` or `hippo.ingest.pipeline`
(ruling R54): the build is a closure the dispatch supplies, and the lane's own refusal is
`LaneRefused`, so the one `ingest` to `connectors` edge cannot close into a cycle.
`tests/unit/test_layering.py` pins both halves of that rule.

The lane writes no `Connector` and no `SyncState` row (ruling R5). Its lease is the coordinator's
fenced build claim and its checkpoint is the coordinator's accepted manifest, which returns the
prior receipt for an unchanged replay.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from .base import ChangePage, ContractError, Registry, SyncConnector


class LaneRefused(ValueError):
    """The lane refused before any coordinator ran: a descriptor or an inventory it cannot accept.

    Its own class, not the dispatch's `ManagedDispatchError`, because `connectors` sits above
    `ingest` (review M11, ruling R54). It is outside `managed_activation.FAILURES`, so a refusal
    reaches a caller as the unknown code - which is what a kit mistake should look like, and what
    the ported connectors can never produce: their descriptors are static and their inventories
    are always complete.
    """


@dataclass(frozen=True)
class CoordinatorLane:
    """One reviewed coordinator, named by the family it derives and called with the fingerprint."""

    family: Literal["prose", "code"]
    build: Callable[[ChangePage, str], Any]


def run_coordinator_lane(
    connector: SyncConnector,
    config: BaseModel,
    lane: CoordinatorLane,
    *,
    registry: Registry,
) -> Any:
    """Take the connector's complete inventory, then let the coordinator derive and publish it.

    Three steps, in order (plan section 3.2):

    1. Refuse a descriptor that does not declare this lane, that names vocabulary `registry` does
       not hold, or that declares predicates or parsers - a lane connector emits neither.
    2. Take `connector.list_changes(config, None)`: a complete local inventory, with no provider
       cursor to resume from. An incomplete scan is refused rather than published as a whole.
    3. Return `lane.build(page, registry.fingerprint())`.

    Step 3 lets every exception through with its type unchanged, so
    `managed_activation.map_build_failure` maps the coordinator's failures to exactly the public
    codes it mapped before the port.
    """
    if not isinstance(lane, CoordinatorLane):
        raise LaneRefused("A coordinator lane is required")
    if not isinstance(registry, Registry):
        raise LaneRefused("A registry is required to fingerprint the build")
    descriptor = getattr(connector, "descriptor", None)
    if descriptor is None:
        raise LaneRefused("A connector declares a descriptor")
    if descriptor.capabilities.derivation != "coordinator_lane":
        raise LaneRefused(
            f"Connector {descriptor.name} does not declare a coordinator lane; it emits its own records"
        )
    if lane.family not in descriptor.families:
        raise LaneRefused(f"Connector {descriptor.name} does not declare the {lane.family} family")
    if descriptor.predicates or descriptor.parsers:
        raise LaneRefused(
            f"Connector {descriptor.name} declares predicates or parsers, which a lane never emits"
        )
    try:
        descriptor.validate_against(registry)
    except ContractError as error:
        raise LaneRefused(f"Connector {descriptor.name} names vocabulary this registry lacks") from error
    page = connector.list_changes(config, None)
    if not isinstance(page, ChangePage):
        raise LaneRefused(f"Connector {descriptor.name} returned something that is not a change page")
    if not page.complete:
        raise LaneRefused(
            f"Connector {descriptor.name} returned an incomplete inventory; a lane publishes a whole source"
        )
    return lane.build(page, registry.fingerprint())
