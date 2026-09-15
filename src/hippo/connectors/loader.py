"""Which connector packages exist, and which of them an operator has enabled.

Design §3's order is built-ins, then in-repo packages, then installed entry points, and design §9
admits an entry point only when the configuration's allowlist names it. `load_registry` walks that
order once and freezes the registry it loaded, so a process serves one vocabulary from its first
request to its last: enabling a kind takes effect when the process next starts (ruling R50).

Nothing here raises at startup. A package that does not import, a class that does not answer to its
own name and an extension the registry refuses are each *listed* with their error, and loading
continues — one broken connector never costs the others their registration, and never costs the
server its startup. `load_connectors` is the whole-process call: `hippo serve`'s lifespan stores its
`LoadResult` on `app.state.connector_load`, which is what `GET /api/connectors` reads back.

Readers need none of this. Ruling R39 makes every read accept any code, so `hippo ask`, the MCP
tools and startup recovery read rows whose extension no process ever loaded.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.resources
import logging
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, Literal

from ..knowledge.registry import Registry, TypeExtension, current_registry

if TYPE_CHECKING:  # pragma: no cover - the annotation must not cost an import at startup
    from ..context import AppContext

log = logging.getLogger(__name__)

ENTRY_POINT_GROUP: Final = "hippo.connectors"
ALLOWLIST_ENV: Final = "HIPPO_CONNECTOR_ALLOWLIST"
IN_REPO_PACKAGES: Final = ("hippo.connectors", "hippo.connectors.examples")
# What makes a directory a connector package rather than a helper directory. `scaffold/` is not one:
# its files are `.tmpl`, so it holds neither.
PACKAGE_FILES: Final = ("__init__.py", "connector.py")


class ConnectorLoadError(ValueError):
    """A connector asked for by name that this load did not register."""


@dataclass(frozen=True)
class ConnectorEntry:
    """One connector the process can see, registered or not, with the reason when it is not."""

    name: str
    origin: Literal["built-in", "in-repo", "entry point"]
    target: str | None  # "package.module:Connector"; None for a built-in connector kind
    trusted: bool
    enabled: bool = False
    registered: bool = False
    connector_class: type | None = None
    # An exception class name, or one of "not allowlisted", "NameMismatch", "DuplicateName" and
    # "frozen" (enabled, but the registry was already frozen when this load began).
    error: str | None = None


@dataclass(frozen=True)
class LoadResult:
    """The registry this load left behind, and what it found on the way.

    `error` carries the one failure that leaves `entries` empty: the store could not say which kinds
    are enabled, or the walk itself failed. The registry is then left unfrozen, because freezing an
    empty vocabulary would outlast the outage it came from (re-review N2, N14).
    """

    registry: Registry
    entries: tuple[ConnectorEntry, ...]
    error: str | None = None

    def connector_class(self, name: str) -> type:
        """The class of a registered entry. A built-in kind has none, which is its own refusal."""
        for entry in self.entries:
            if entry.name != name:
                continue
            if entry.registered and entry.connector_class is not None:
                return entry.connector_class
            raise ConnectorLoadError(
                f"Connector '{name}' is not loaded: {entry.error or 'it has no installed package'}"
            )
        raise ConnectorLoadError(f"No connector named '{name}' was discovered")


def discover_connectors(*, allowlist: frozenset[str]) -> tuple[ConnectorEntry, ...]:
    """Every connector package this process can see, imported but not registered.

    In-repo packages come first and in name order, then entry points in name order, which is the
    order `load_registry` registers them in. An entry point repeating an in-repo name, or missing
    from `allowlist`, is decided before anything is imported: untrusted code does not run its module
    body just to be discarded (design §10, re-review N15).
    """
    candidates = _in_repo_candidates()
    seen = {entry.name for entry, _ in candidates}
    for entry, load in _entry_point_candidates(allowlist=allowlist):
        if entry.name in seen:
            entry = replace(entry, error="DuplicateName")
        seen.add(entry.name)
        candidates.append((entry, load))
    return tuple(_imported(entry, load) for entry, load in candidates)


def load_registry(*, enabled_kinds: frozenset[str], allowlist: frozenset[str]) -> LoadResult:
    """Register the enabled connectors' extensions into the current registry, then freeze it.

    The registry is `current_registry()`, which in a server process is the module-level `REGISTRY`: a
    `ContextVar` set inside the lifespan task would not reach the request tasks, so the vocabulary is
    installed where every thread reads it. A test installs its own with `use_registry` first.

    A registry that is already frozen registers nothing. An enabled connector whose extension is
    already present and equal is still reported as registered, so a second lifespan in one process
    reads the same way as the first; anything else waits for the next process (ruling R50).
    """
    registry = current_registry()
    frozen = registry.frozen
    discovered = discover_connectors(allowlist=allowlist)
    entries = [
        _installed(registry, entry, enabled_kinds=enabled_kinds, frozen=frozen) for entry in discovered
    ]
    packaged = {entry.name for entry in discovered}
    built_in = tuple(
        ConnectorEntry(
            name=name,
            origin="built-in",
            target=None,
            trusted=True,
            enabled=name in enabled_kinds,
            registered=True,
        )
        for name in sorted(Registry.with_builtins().connector_kinds() - packaged)
    )
    registry.freeze()
    return LoadResult(registry=registry, entries=built_in + tuple(entries))


def configured_allowlist(environ: Mapping[str, str] | None = None) -> frozenset[str]:
    """The entry point names this configuration trusts; empty by default (design §9).

    Deviation 5 of the plan: the list is read from `HIPPO_CONNECTOR_ALLOWLIST` here rather than from
    `Config`, for v1. Task 15's `POST /api/connectors` is where it moves when a stored setting exists.
    """
    source = os.environ if environ is None else environ
    return frozenset(
        name for name in (part.strip() for part in source.get(ALLOWLIST_ENV, "").split(",")) if name
    )


def enabled_connector_kinds(store) -> frozenset[str]:
    """The kinds an operator has enabled, which is one enabled `Connector` instance of that kind.

    Ruling R51 gates each instance again at sync entry: this answers "may this code load at all",
    not "may this instance run".
    """
    return frozenset(row.kind for row in store._knowledge_rows("Connector") if row.enabled)


def load_connectors(ctx: AppContext) -> LoadResult:
    """Load the process registry from the configured store's enabled kinds. Never raises.

    `startup` (`web/app.py`) is designed to tolerate a store that comes up minutes later, and this
    call runs after it for the same reason. When the rows cannot be read, or the walk fails, the
    failure is logged and returned in the result, and the registry is left unfrozen: a frozen empty
    vocabulary would outlive the outage and silence every extension until the next restart (N2, N14).
    """
    try:
        enabled_kinds = enabled_connector_kinds(ctx.store)
    except Exception as error:
        log.warning("connector kinds could not be read from the store; loaded none", exc_info=True)
        return LoadResult(registry=current_registry(), entries=(), error=type(error).__name__)
    try:
        return load_registry(enabled_kinds=enabled_kinds, allowlist=configured_allowlist())
    except Exception as error:
        log.warning("the connector registry could not be loaded; loaded none", exc_info=True)
        return LoadResult(registry=current_registry(), entries=(), error=type(error).__name__)


def _entry_points() -> Iterable:
    """The installed `hippo.connectors` entry points. Tests replace this with stand-ins."""
    return importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)


def _in_repo_candidates() -> list[tuple[ConnectorEntry, Callable[[], type]]]:
    candidates: list[tuple[ConnectorEntry, Callable[[], type]]] = []
    for package in IN_REPO_PACKAGES:
        try:
            children = sorted(importlib.resources.files(package).iterdir(), key=lambda entry: entry.name)
        except (ImportError, TypeError):
            continue  # `hippo.connectors.examples` need not exist
        for child in children:
            if not child.is_dir() or not all((child / name).is_file() for name in PACKAGE_FILES):
                continue
            module = f"{package}.{child.name}"
            entry = ConnectorEntry(
                name=child.name, origin="in-repo", target=f"{module}:Connector", trusted=True
            )
            candidates.append((entry, _package_export(module)))
    return candidates


def _package_export(module: str) -> Callable[[], type]:
    def load() -> type:
        return importlib.import_module(module).Connector

    return load


def _entry_point_candidates(*, allowlist: frozenset[str]) -> list[tuple[ConnectorEntry, Callable[[], type]]]:
    candidates: list[tuple[ConnectorEntry, Callable[[], type]]] = []
    for point in sorted(_entry_points(), key=lambda point: point.name):
        trusted = point.name in allowlist
        entry = ConnectorEntry(
            name=point.name,
            origin="entry point",
            target=point.value,
            trusted=trusted,
            error=None if trusted else "not allowlisted",
        )
        candidates.append((entry, point.load))
    return candidates


def _imported(entry: ConnectorEntry, load: Callable[[], type]) -> ConnectorEntry:
    if not entry.trusted or entry.error is not None:
        return entry
    try:
        connector = load()
        name = connector.descriptor.name
    except Exception as error:  # a connector's own import is not the server's problem
        log.warning("connector '%s' (%s) did not import", entry.name, entry.target, exc_info=True)
        return replace(entry, error=type(error).__name__)
    if name != entry.name:
        log.warning("connector '%s' (%s) calls itself '%s'", entry.name, entry.target, name)
        return replace(entry, error="NameMismatch")
    return replace(entry, connector_class=connector)


def _installed(
    registry: Registry, entry: ConnectorEntry, *, enabled_kinds: frozenset[str], frozen: bool
) -> ConnectorEntry:
    if entry.connector_class is None or entry.name not in enabled_kinds:
        return entry
    entry = replace(entry, enabled=True)
    descriptor = entry.connector_class.descriptor
    if frozen:
        if _already_registered(registry, descriptor.extension):
            return replace(entry, registered=True)
        return replace(entry, error="frozen")
    try:
        registry.register(descriptor.extension, declared_families=descriptor.families)
    except Exception as error:
        # `register` swaps state only when every check passes, so a refusal registers nothing.
        log.warning("connector '%s' was not registered", entry.name, exc_info=True)
        return replace(entry, error=type(error).__name__)
    return replace(entry, registered=True)


def _already_registered(registry: Registry, extension: TypeExtension) -> bool:
    """Whether every name this extension declares is present in `registry`, and equal where it can be.

    The definition sections are compared whole, so a package that changed under a running process is
    not reported as the vocabulary the process actually serves. Families, evidence sources and the
    two name-only sections are compared by membership: `evidence_source` returns a name, and the
    definition accessor ruling R62 gives S1b does not exist yet (re-review N13).
    """
    definitions = (
        (registry.object_kind, extension.object_kinds),
        (registry.predicate, extension.predicates),
        (registry.locator_kind, extension.locator_kinds),
    )
    for accessor, declared in definitions:
        for definition in declared:
            try:
                if accessor(definition.name) != definition:
                    return False
            except KeyError:
                return False
    memberships = (
        (registry.families(), extension.families),
        (registry.evidence_sources(), tuple(source.name for source in extension.evidence_sources)),
        (registry.artifact_kinds(), extension.artifact_kinds),
        (registry.connector_kinds(), extension.connector_kinds),
    )
    return all(set(names) <= registered for registered, names in memberships)
