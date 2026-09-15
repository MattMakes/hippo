"""The connector registry loader: discovery, the enablement gate, the freeze and the serve lifespan.

Slice S4c of `ai_docs/plans/cdk-s4-kit.md` §3.5, with the findings ruling R63 binds from
`ai_docs/reports/2026-09-15-cdk-s4-replan-review.md`: N1 (no test registers into the process
registry), N2 (the lifespan loads after `startup`, and an unreachable store never freezes an empty
registry), N13 (the restart rule covers every section), N14 (`load_connectors` never raises) and
N15 (a duplicate name is decided before the module is imported).

Every test that reaches `load_registry` runs under `use_registry(Registry.with_builtins())`. Freezing
alone is harmless, but *population* is not: an extension left in `REGISTRY` makes a later
`extension_scope()` registration of the same extension fail with `duplicate_name`, and pytest runs
this file in one process with `test_connector_sync.py` and `test_registry.py` (N1). Every test that
seeds `Connector` rows takes the same fixture, because `seed_connectors` registers the kinds it
writes (see its docstring) and that registration must not reach `REGISTRY` either.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Mapping
from string import Template

import pytest

from hippo.connectors import loader
from hippo.knowledge import model as k
from hippo.knowledge.registry import (
    Registry,
    TypeExtension,
    current_registry,
    extension_scope,
    use_registry,
)

# The package root the loader scans in these tests, in place of `hippo/connectors/`. A temporary
# root keeps the source tree free of fixture packages, which no brief grants.
IN_REPO_ROOT = "loader_fixture_packages"

# One shape for both discovery paths: an in-repo package writes it to `connector.py`, and an entry
# point stand-in returns the class this source defines. The extension is the smallest one the
# registry admits: a family, an object kind, an artifact kind, a locator kind and the connector kind
# that `ensure_connector(kind=descriptor.name)` stores.
CONNECTOR_SOURCE = Template('''"""A stand-in connector package for the loader tests."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from hippo.connectors.base import ConnectorCapabilities, ConnectorDescriptor
from hippo.knowledge.contract import Text
from hippo.knowledge.locators import LocatorBase
from hippo.knowledge.registry import LocatorKindDefinition, ObjectKindDefinition, TypeExtension


class Config(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = "https://$name.invalid"


class Attributes(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str


class RowLocator(LocatorBase):
    kind: Literal["${name}_row"] = "${name}_row"
    row_id: Text


EXTENSION = TypeExtension(
    families=$families,
    object_kinds=(
        ObjectKindDefinition(
            name="${name}_record",
            family="$name",
            key_template=("instance", "row_id"),
            key_prefix="$name",
            attrs_model=Attributes,
            label_template="{title}",
        ),
    ),
    artifact_kinds=("${name}_export",),
    locator_kinds=(LocatorKindDefinition(name="${name}_row", model=RowLocator),),
    connector_kinds=("$name",),
)


class Connector:
    """What the loader reads from `<package>:Connector`: a descriptor carrying its extension."""

    descriptor = ConnectorDescriptor(
        name="$descriptor_name",
        version="1",
        families=("$name",),
        kinds=("${name}_record",),
        predicates=(),
        artifact_kinds=("${name}_export",),
        locator_kinds=("${name}_row",),
        capabilities=ConnectorCapabilities(),
        config_model=Config,
        credentials=(),
        parsers=(),
        extension=EXTENSION,
    )
''')

# A package whose module raises on import, for the in-repo half of "a failing entry is listed".
BROKEN_SOURCE = '''"""A connector package that cannot be imported."""

raise ImportError("the acme client library is not installed")
'''


def connector_source(name: str, *, descriptor_name: str | None = None, declares_family: bool = True) -> str:
    return CONNECTOR_SOURCE.substitute(
        name=name,
        descriptor_name=descriptor_name or name,
        families=f'("{name}",)' if declares_family else "()",
    )


def connector_class(name: str, *, descriptor_name: str | None = None, declares_family: bool = True) -> type:
    """The same connector shape as an object, for an entry point stand-in to return."""
    namespace: dict[str, object] = {"__name__": f"loader_fixture_installed_{name}"}
    source = connector_source(name, descriptor_name=descriptor_name, declares_family=declares_family)
    exec(compile(source, f"<{name} connector>", "exec"), namespace)
    return namespace["Connector"]


class StandInEntryPoint:
    """The three attributes the loader reads from an `importlib.metadata` entry point (§3.5 step 2).

    `loads` counts the imports, so a test can prove that an untrusted or duplicate name is never
    imported at all (design §10 trust, N15).
    """

    def __init__(self, name: str, value: str, result: object) -> None:
        self.name = name
        self.value = value
        self._result = result
        self.loads = 0

    def load(self) -> object:
        self.loads += 1
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


def entry_point(name: str, result: object) -> StandInEntryPoint:
    return StandInEntryPoint(name, f"{name}_connector:Connector", result)


def install_entry_points(monkeypatch: pytest.MonkeyPatch, *points: StandInEntryPoint) -> None:
    monkeypatch.setattr(loader, "_entry_points", lambda: points)


@pytest.fixture
def packages(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """A temporary package root the loader scans instead of `hippo.connectors`.

    Every module the root holds is dropped from `sys.modules` afterwards, so a later test that
    writes a package of the same name gets its own code rather than this test's cached class.
    """
    root = tmp_path / IN_REPO_ROOT
    root.mkdir()
    (root / "__init__.py").write_text('"""In-repo connector packages, for the loader tests."""\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(loader, "IN_REPO_PACKAGES", (IN_REPO_ROOT, f"{IN_REPO_ROOT}.examples"))

    def write(name: str, *, descriptor_name: str | None = None, declares_family: bool = True, source=None):
        package = root / name
        package.mkdir()
        (package / "__init__.py").write_text("from .connector import Connector as Connector\n")
        body = (
            source
            if source is not None
            else connector_source(name, descriptor_name=descriptor_name, declares_family=declares_family)
        )
        (package / "connector.py").write_text(body)
        return package

    yield write
    for module in [n for n in sys.modules if n == IN_REPO_ROOT or n.startswith(f"{IN_REPO_ROOT}.")]:
        del sys.modules[module]


@pytest.fixture
def registry():
    """A fresh registry, current for the body: nothing a test registers reaches `REGISTRY` (N1)."""
    with use_registry(Registry.with_builtins()) as fresh:
        yield fresh


def seed_connectors(store, kinds: Mapping[str, bool]) -> None:
    """One `Connector` row per kind, enabled or not, which is where `enabled_kinds` comes from.

    The user comes first on purpose: `store/authorization.py:44` refuses an enabled provider
    connector while the installation has no users, so enabling a kind is a signed-in operator's act
    (which is the installation R59's `hippo connector enable` runs in).

    The kinds are registered before they are written, because the write path calls
    `Registry.check_record` (ruling R39, `store/knowledge.py:772`), which refuses a `Connector` row
    whose kind no registry knows. Production writes such a row under the connector's own extension,
    already registered by the time `hippo connector enable` runs (R63 N5); here a throwaway
    `TypeExtension` stands in for it inside `extension_scope()`, which restores the registry whole
    and so never leaves these names behind (N1). The scope closes before this function returns on
    purpose: a caller that goes on to load registers the discovered connector's real extension under
    these same names, which a throwaway still in place would refuse as a `duplicate_name`.
    """
    store.ensure_schema()
    store.ensure_roles()
    store.create_user("loader-operator", "secret1", "individual")
    workspace = k.Workspace(name="default")
    store.put_knowledge(workspace)
    with extension_scope() as scoped:
        scoped.register(TypeExtension(families=tuple(kinds), connector_kinds=tuple(kinds)))
        for kind, enabled in kinds.items():
            store.put_knowledge(
                k.Connector(
                    workspace_id=workspace.id,
                    kind=kind,
                    instance_url=f"https://{kind}.invalid",
                    enabled=enabled,
                )
            )


def named(result: loader.LoadResult, name: str) -> loader.ConnectorEntry:
    matches = [entry for entry in result.entries if entry.name == name]
    assert len(matches) == 1, [entry.name for entry in result.entries]
    return matches[0]


def discovered(result: loader.LoadResult) -> list[str]:
    return [entry.name for entry in result.entries if entry.origin != "built-in"]


def run_lifespan(app, inside) -> None:
    """Run the app's lifespan to completion, calling `inside()` while it is open."""

    async def main() -> None:
        async with app.router.lifespan_context(app):
            inside()

    asyncio.run(main())


def test_loader_registers_enabled_in_repo_packages_before_allowlisted_entry_points_then_freezes(
    packages, registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    packages("beta")
    packages("acme")
    gamma = entry_point("gamma", connector_class("gamma"))
    install_entry_points(monkeypatch, gamma)
    order: list[tuple[str, ...]] = []
    register = registry.register

    def spy(extension, **kwargs):
        order.append(tuple(extension.connector_kinds))
        return register(extension, **kwargs)

    registry.register = spy

    result = loader.load_registry(
        enabled_kinds=frozenset({"acme", "beta", "gamma"}), allowlist=frozenset({"gamma"})
    )

    assert order == [("acme",), ("beta",), ("gamma",)]
    assert discovered(result) == ["acme", "beta", "gamma"]
    assert [named(result, name).origin for name in ("acme", "beta", "gamma")] == [
        "in-repo",
        "in-repo",
        "entry point",
    ]
    assert named(result, "acme").target == f"{IN_REPO_ROOT}.acme:Connector"
    assert named(result, "gamma").target == "gamma_connector:Connector"
    assert all(named(result, name).registered for name in ("acme", "beta", "gamma"))
    assert all(named(result, name).enabled for name in ("acme", "beta", "gamma"))
    assert {"acme", "beta", "gamma"} <= registry.connector_kinds()
    assert registry.object_kind("acme_record").family == "acme"
    assert registry.frozen
    assert result.registry is registry is current_registry()


def test_a_discovered_kind_that_is_not_enabled_is_listed_and_not_registered(packages, registry) -> None:
    packages("acme")

    result = loader.load_registry(enabled_kinds=frozenset(), allowlist=frozenset())

    entry = named(result, "acme")
    assert entry.origin == "in-repo" and entry.trusted
    assert entry.connector_class is not None and entry.connector_class.descriptor.name == "acme"
    assert not entry.enabled and not entry.registered and entry.error is None
    assert "acme" not in registry.connector_kinds()
    assert registry.frozen


def test_loading_a_frozen_registry_registers_nothing_until_restart(packages, registry) -> None:
    packages("acme")
    enabled = {"kinds": frozenset({"acme"})}

    first = loader.load_registry(enabled_kinds=enabled["kinds"], allowlist=frozenset())
    assert named(first, "acme").registered and registry.frozen

    # A second lifespan in one process: the extension is already present and equal, so the entry is
    # registered and nothing is written again.
    second = loader.load_registry(enabled_kinds=enabled["kinds"], allowlist=frozenset())
    assert named(second, "acme").registered and named(second, "acme").error is None

    # A kind enabled only after the freeze waits for the next process (the restart rule of R50).
    packages("beta")
    third = loader.load_registry(enabled_kinds=frozenset({"acme", "beta"}), allowlist=frozenset())
    beta = named(third, "beta")
    assert beta.enabled and not beta.registered and beta.error == "frozen"
    assert "beta" not in registry.connector_kinds()


@pytest.mark.parametrize("failure", ["import_error", "registration_refused"])
def test_loader_lists_a_failing_entry_point_and_continues(
    registry, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    if failure == "import_error":
        acme = entry_point("acme", ImportError("the acme client library is not installed"))
        expected = "ImportError"
    else:
        # The extension declares no family, so the registry refuses its object kind whole.
        acme = entry_point("acme", connector_class("acme", declares_family=False))
        expected = "RegistrationError"
    beta = entry_point("beta", connector_class("beta"))
    install_entry_points(monkeypatch, acme, beta)

    result = loader.load_registry(
        enabled_kinds=frozenset({"acme", "beta"}), allowlist=frozenset({"acme", "beta"})
    )

    assert named(result, "acme").error == expected
    assert not named(result, "acme").registered
    assert named(result, "beta").registered and named(result, "beta").error is None
    assert "beta" in registry.connector_kinds() and "acme" not in registry.connector_kinds()
    assert registry.frozen


def test_loader_skips_an_entry_point_missing_from_the_allowlist(
    registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    acme = entry_point("acme", connector_class("acme"))
    install_entry_points(monkeypatch, acme)

    result = loader.load_registry(enabled_kinds=frozenset({"acme"}), allowlist=frozenset())

    entry = named(result, "acme")
    assert entry.error == "not allowlisted"
    assert not entry.trusted and not entry.registered and entry.connector_class is None
    assert acme.loads == 0, "an entry point outside the allowlist is never imported"
    assert "acme" not in registry.connector_kinds()


def test_an_entry_point_that_repeats_an_in_repo_name_is_a_duplicate_and_is_never_imported(
    packages, registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    packages("acme")
    shadow = entry_point("acme", connector_class("acme"))
    install_entry_points(monkeypatch, shadow)

    result = loader.load_registry(enabled_kinds=frozenset({"acme"}), allowlist=frozenset({"acme"}))

    # Both are listed under the one name; only the in-repo package is loaded.
    by_origin = {entry.origin: entry for entry in result.entries if entry.name == "acme"}
    assert by_origin["entry point"].error == "DuplicateName"
    assert not by_origin["entry point"].registered
    assert shadow.loads == 0, "a duplicate name is decided before the module is imported (N15)"
    assert by_origin["in-repo"].registered


def test_a_connector_whose_descriptor_name_differs_is_a_name_mismatch(packages, registry) -> None:
    packages("acme", descriptor_name="acme_cloud")

    result = loader.load_registry(enabled_kinds=frozenset({"acme"}), allowlist=frozenset())

    entry = named(result, "acme")
    assert entry.error == "NameMismatch"
    assert not entry.registered and entry.connector_class is None
    assert "acme" not in registry.connector_kinds()


def test_an_in_repo_package_that_cannot_be_imported_is_listed_with_its_error(packages, registry) -> None:
    packages("acme", source=BROKEN_SOURCE)

    result = loader.load_registry(enabled_kinds=frozenset({"acme"}), allowlist=frozenset())

    assert named(result, "acme").error == "ImportError"
    assert not named(result, "acme").registered
    assert registry.frozen


def test_built_in_connector_kinds_are_listed_with_their_enablement(registry) -> None:
    result = loader.load_registry(enabled_kinds=frozenset({"git"}), allowlist=frozenset())

    built_in = {entry.name: entry for entry in result.entries if entry.origin == "built-in"}
    assert set(built_in) == Registry.with_builtins().connector_kinds()
    assert all(entry.target is None and entry.trusted and entry.registered for entry in built_in.values())
    assert built_in["git"].enabled
    assert not built_in["github"].enabled


def test_connector_class_answers_for_a_registered_entry_and_refuses_otherwise(packages, registry) -> None:
    packages("acme")
    result = loader.load_registry(enabled_kinds=frozenset({"acme"}), allowlist=frozenset())

    assert result.connector_class("acme").descriptor.name == "acme"
    with pytest.raises(loader.ConnectorLoadError):
        result.connector_class("git")  # a built-in kind carries no class
    with pytest.raises(loader.ConnectorLoadError):
        result.connector_class("nothing_like_it")


def test_enabled_kinds_come_from_enabled_instances_and_the_allowlist_from_the_environment(
    store, registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_connectors(store, {"acme": True, "beta": False})

    assert loader.enabled_connector_kinds(store) == frozenset({"acme"})

    assert loader.configured_allowlist({}) == frozenset()
    assert loader.configured_allowlist({loader.ALLOWLIST_ENV: ""}) == frozenset()
    assert loader.configured_allowlist({loader.ALLOWLIST_ENV: " acme , beta ,,"}) == frozenset(
        {"acme", "beta"}
    )
    monkeypatch.setenv(loader.ALLOWLIST_ENV, "gamma")
    assert loader.configured_allowlist() == frozenset({"gamma"})
    monkeypatch.delenv(loader.ALLOWLIST_ENV)
    assert loader.configured_allowlist() == frozenset()


def test_load_connectors_reads_the_enabled_kinds_and_the_allowlist(
    ctx, registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_connectors(ctx.store, {"acme": True, "beta": True})
    acme = entry_point("acme", connector_class("acme"))
    beta = entry_point("beta", connector_class("beta"))
    install_entry_points(monkeypatch, acme, beta)
    monkeypatch.setenv(loader.ALLOWLIST_ENV, "acme")

    result = loader.load_connectors(ctx)

    assert result.error is None
    assert named(result, "acme").registered
    assert named(result, "beta").error == "not allowlisted"
    assert registry.frozen


@pytest.mark.parametrize("failure", ["rows", "load_registry"])
def test_load_connectors_never_raises_when_connector_rows_cannot_be_read(
    ctx, registry, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    if failure == "rows":

        def unreachable(*args, **kwargs):
            raise RuntimeError("the graph store is not reachable")

        monkeypatch.setattr(ctx.store, "_knowledge_rows", unreachable)
        expected = "RuntimeError"
    else:
        # N14: the row read is not the only thing that can fail; a broken in-repo tree raises here.
        def refuses(**kwargs):
            raise ValueError("a package under hippo/connectors is not readable")

        monkeypatch.setattr(loader, "load_registry", refuses)
        expected = "ValueError"

    result = loader.load_connectors(ctx)

    assert result.error == expected
    assert result.entries == ()
    assert not registry.frozen, "an unreachable store never freezes an empty registry (N2)"


def test_serve_startup_installs_a_frozen_registry(ctx, registry, monkeypatch: pytest.MonkeyPatch) -> None:
    from hippo.web.app import create_app

    seed_connectors(ctx.store, {"acme": True})
    install_entry_points(monkeypatch, entry_point("acme", connector_class("acme")))
    monkeypatch.setenv(loader.ALLOWLIST_ENV, "acme")
    app = create_app(ctx)

    def inside() -> None:
        assert current_registry().frozen
        load = app.state.connector_load
        assert named(load, "acme").registered and named(load, "acme").enabled
        assert load.registry is registry

    run_lifespan(app, inside)


def test_serve_startup_with_an_unreachable_store_loads_no_kinds_and_says_so(
    ctx, registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N2: `startup` runs first and tolerates a store that comes up later; the loader must too."""
    from hippo.web.app import create_app

    def unreachable(*args, **kwargs):
        raise RuntimeError("the graph store is not reachable")

    monkeypatch.setattr(ctx.store, "ping", lambda: False)
    monkeypatch.setattr(ctx.store, "_knowledge_rows", unreachable)
    app = create_app(ctx)

    def inside() -> None:
        load = app.state.connector_load
        assert load.error == "RuntimeError"
        assert load.entries == ()
        assert not current_registry().frozen, "a store that is late must not freeze an empty registry"

    run_lifespan(app, inside)
