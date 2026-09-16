"""The scaffold behind `hippo connector new` (CDK S4b, plan `ai_docs/plans/cdk-s4-kit.md` §3.2).

`render_package` writes a working connector package — descriptor, `TypeExtension`, fact templates,
one fixture case and one passing test — and then runs the whole kit over it with
`validate_package(..., update_golden=True)`, so the package arrives with its registry lock and its
seven goldens already computed and `hippo connector validate` passes on a tree nobody has edited.

Three rules shape what the templates emit:

* **The descriptor name is three things at once** (ruling R64): the discovered entry name, the
  connector kind the extension registers, and the `Connector.kind` an operator's row carries. The
  loader refuses any disagreement with `NameMismatch`, so `__init__.py`'s `from .connector import
  <Class> as Connector` re-export and `types.py`'s `connector_kinds=(...)` are load-bearing, not
  decoration. The generated class also publishes `descriptor` as a **class** attribute, because
  `loader._imported` reads it off the class before anything is constructed.
* **`emit` writes no instance key part** (ruling M16). The kind declares `key_template=("instance",
  ...)` and the kit fills `instance` from the connector row (S2 §6 step 2), so a `NodeRef` carries
  only the parts this revision can see.
* **A generated module imports only the public surface** (R-S2-8, R-S2-10): `hippo.connectors`,
  `hippo.connectors.base`, `hippo.connectors.classify`, `hippo.knowledge.registry` for the
  definition models, `pydantic` and the standard library. `current_registry` comes from
  `hippo.connectors.base`, which re-exports it (ruling R60).

The templates are `string.Template` files under `templates/`, shipped as package data (non-Python
files under `src/hippo` go into the wheel, `pyproject.toml:53-54`) and read through
`importlib.resources`, so an installed hippo scaffolds as well as a checkout does.
"""

from __future__ import annotations

import importlib.resources
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Final

FAMILIES_REQUIRE_REGISTRY: Final = True
NAME: Final = re.compile(r"^[a-z][a-z0-9_]{1,62}$")

# Template file -> where it lands inside the new package. The order is the order they are written.
TEMPLATES: Final = (
    ("__init__.py.tmpl", "__init__.py"),
    ("types.py.tmpl", "types.py"),
    ("templates.py.tmpl", "templates.py"),
    ("connector.py.tmpl", "connector.py"),
    ("test_connector.py.tmpl", "tests/test_connector.py"),
    ("config.json.tmpl", "fixtures/basic/config.json"),
    ("changes.json.tmpl", "fixtures/basic/changes.json"),
    ("policies.json.tmpl", "fixtures/basic/policies.json"),
    ("record-1.tmpl", "fixtures/basic/inputs/record-1"),
    ("record-2.tmpl", "fixtures/basic/inputs/record-2"),
)


class ScaffoldError(ValueError):
    """A request the scaffold refuses by name, so `hippo connector new` exits 2 with a sentence."""


@dataclass(frozen=True)
class ScaffoldRequest:
    """What `hippo connector new` was asked for. `kinds` defaults to one kind named for the package."""

    name: str
    family: str
    kinds: tuple[str, ...] = ()

    @property
    def object_kinds(self) -> tuple[str, ...]:
        return self.kinds or (self.name,)

    @property
    def class_name(self) -> str:
        return "".join(part.title() for part in self.name.split("_")) + "Connector"

    @property
    def key_prefix(self) -> str:
        """The readable prefix of specification §4.1: the primary kind's first four characters."""
        return self.object_kinds[0][:4]


def check(request: ScaffoldRequest) -> None:
    """Every refusal of the plan's §3.3 `new` row, raised as a sentence rather than a traceback.

    The kind checks are this module's own: `Registry.register` would refuse a kind a built-in
    already owns with `duplicate_name` long after the files were written, and a kind that is not a
    valid identifier would only break when the generated module is imported. Naming both here keeps
    a refused request from leaving a directory behind.
    """
    from ...knowledge.registry import Registry

    builtins = Registry.with_builtins()
    if not NAME.fullmatch(request.name):
        raise ScaffoldError(
            f"'{request.name}' is not a connector name: {NAME.pattern} (lower case, 2-63 characters)"
        )
    if request.name in builtins.connector_kinds():
        raise ScaffoldError(f"'{request.name}' is already a registered connector kind")
    if FAMILIES_REQUIRE_REGISTRY and request.family not in builtins.families():
        raise ScaffoldError(
            f"'{request.family}' is not a registered family; one of {', '.join(sorted(builtins.families()))}"
        )
    for kind in request.object_kinds:
        if not NAME.fullmatch(kind):
            raise ScaffoldError(f"'{kind}' is not an object kind name: {NAME.pattern}")
        if kind in builtins.object_kinds():
            raise ScaffoldError(f"'{kind}' is already a registered object kind")


def render_package(request: ScaffoldRequest, dest: Path) -> tuple[Path, ...]:
    """Write the package under `dest`, compute its lock and goldens, and return every file written.

    The whole tree is removed if the kit refuses it, because a half-validated package on disk is
    worse than none: the developer would run `validate` on something `new` never stood behind.
    """
    from ..testing import validate_package

    check(request)
    package = Path(dest) / request.name
    if package.exists():
        raise ScaffoldError(f"{package} exists; pass --dest, or remove it")

    substitutions = {
        "name": request.name,
        "class_name": request.class_name,
        "family": request.family,
        "kinds": _tuple_literal(request.object_kinds),
        "primary_kind": request.object_kinds[0],
        "key_prefix": request.key_prefix,
    }
    try:
        for source, relative in TEMPLATES:
            target = package / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_template(source).substitute(substitutions), encoding="utf-8")
        _write_lock(package)
        report = validate_package(package, update_golden=True)
    except BaseException:
        shutil.rmtree(package, ignore_errors=True)
        raise
    # `ValidationReport.passed` is false on this run by construction: `--update-golden` writes the
    # seven goldens and reports the diff from the empty tree it found. Everything else must hold,
    # and the plain `validate` the developer runs next is the one that must be clean.
    if report.error or report.violations or any(_broke(case) for case in report.cases):
        shutil.rmtree(package, ignore_errors=True)
        raise ScaffoldError(_why(report))
    # `validate_package` imported the package to read its `Connector`, which leaves bytecode
    # behind. A developer's new package should hold only what they are meant to read and commit.
    for cache in package.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    return tuple(sorted(path for path in package.rglob("*") if path.is_file()))


def _write_lock(package: Path) -> None:
    """Commit the registry lock the new package is measured against from now on.

    `validate_package(update_golden=True)` writes the seven goldens but not the lock:
    `assert_registry_lock` only compares against a file that already exists, so a package that
    ships without one would never fire `registry_version_bump` and a template whose text changed
    under an unmoved version would pass. The lock is computed from the package's own descriptor,
    which is the state `new` is standing behind.
    """
    from ...knowledge.identity import canonical_json
    from ..testing import extension_lock, load_connector_package

    connector, _ = load_connector_package(package)
    descriptor = connector.descriptor
    lock = extension_lock(descriptor.extension, version=descriptor.version)
    (package / "fixtures" / "registry.lock.json").write_text(canonical_json(lock), encoding="utf-8")


def _broke(case) -> bool:
    return case.error is not None or bool(case.violations)


def _tuple_literal(names: tuple[str, ...]) -> str:
    """A tuple literal ruff would format the same way: double quotes and a trailing comma."""
    return "(" + "".join(f'"{name}", ' for name in names).rstrip() + ")"


def _template(name: str) -> Template:
    source = importlib.resources.files(__name__) / "templates" / name
    return Template(source.read_text(encoding="utf-8"))


def _why(report) -> str:
    """Why a freshly scaffolded package did not validate. Only a kit or template bug reaches this."""
    reasons = [report.error] if report.error else []
    reasons += [f"{violation.assertion}: {violation.message}" for violation in report.violations]
    reasons += [case.diff for case in report.cases if case.diff]
    return "the scaffolded package did not validate: " + json.dumps(reasons)
