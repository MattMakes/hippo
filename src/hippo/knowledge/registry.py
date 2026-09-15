"""One registry for every kind, predicate, locator, family, connector kind and evidence source.

Validated at load, refused at registration, frozen before the first emit. Imports nothing from
`hippo.connectors` or `hippo.store`; built-ins install from `builtin_types` on first use.
"""

from __future__ import annotations

import string
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from .contract import Code, Contract, Text
from .identity import canonical_json, text_hash
from .locators import LocatorBase

Family = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
Version = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")]  # "1", "2.0", "v3"
SPEC_FAMILIES = ("prose", "code", "change", "db", "work", "service", "incident")
CUSTOM_FAMILY = "custom"
RESERVED_TEMPLATE_FIELDS = frozenset({"label", "key"})  # decided by S1 plan
FINGERPRINT_VERSION = 1


class RegistrationError(ValueError):
    """A refused extension. `reason` is a code from the refusal table; the message names the input."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class UnregisteredName(KeyError):
    """A lookup of a name nothing registered; a KeyError so `Mapping.__contains__` works."""

    def __str__(self) -> str:
        return str(self.args[0])


class FactTemplate(Contract):  # fields decided by S1 plan
    name: Code
    version: Version  # a leading digit is allowed; Code is not
    consumes: tuple[Code, ...]  # the attributes it reads
    text: Text  # str.format fields drawn from `consumes` and RESERVED_TEMPLATE_FIELDS


class ObjectKindDefinition(Contract):
    name: Code
    family: Family
    key_template: tuple[Code, ...]  # ordered key parts, e.g. ("tracker", "key") for wi:{tracker}/{key}
    key_prefix: Code  # the readable prefix of spec §4.1: "wi", "tbl", "svc", ...
    attrs_model: type[BaseModel]  # typed attributes; extra="forbid" (extensions)
    label_template: Text  # display label from attrs
    fact_templates: tuple[FactTemplate, ...] = ()  # one rendered unit each (§6)
    scope_kind: bool = False  # Domain, System, Service, Team, Sprint, Epic, Initiative


class PredicateDefinition(Contract):
    name: Code
    subject_kinds: frozenset[Code]
    object_kinds: frozenset[Code]
    owner_families: frozenset[Family]  # non-empty
    identity: bool = False  # SAME_OBJECT_AS only
    canonical_direction: Literal["subject_to_object"]
    inverse_lookup: bool = True
    family_default: Literal["deterministic", "probabilistic"]
    sources_allowed: frozenset[Code]
    verb_phrase: Text
    windowed: bool = False
    support_required: bool = True
    traversal_permitted: bool = True

    @property
    def direction(self) -> Literal["both", "forward"]:  # decided by S1 plan (predicates.py:52)
        return "both" if self.inverse_lookup else "forward"


class LocatorKindDefinition(Contract):
    name: Code
    model: type[BaseModel] | None = None  # optional so "has no model" is refused at register
    # Ruling R31: checks a span's text against the revision bytes. S2 defines the call; the built-ins
    # register none. A callable is not vocabulary, so the fingerprint does not read it.
    verifier: Callable[..., object] | None = None


class TypeExtension(Contract):
    families: tuple[Family, ...] = ()
    object_kinds: tuple[ObjectKindDefinition, ...] = ()
    artifact_kinds: tuple[Code, ...] = ()
    locator_kinds: tuple[LocatorKindDefinition, ...] = ()
    connector_kinds: tuple[Code, ...] = ()
    evidence_sources: tuple[Code, ...] = ()
    predicates: tuple[PredicateDefinition, ...] = ()


SECTIONS = (
    "families",
    "evidence_sources",
    "artifact_kinds",
    "connector_kinds",
    "locator_kinds",
    "object_kinds",
    "predicates",
)
_LABELS = MappingProxyType(
    {
        "families": "family",
        "evidence_sources": "evidence source",
        "artifact_kinds": "artifact kind",
        "connector_kinds": "connector kind",
        "locator_kinds": "locator kind",
        "object_kinds": "object kind",
        "predicates": "predicate",
    }
)


@dataclass(frozen=True)
class _State:
    entries: Mapping[str, Mapping[str, object]]  # section -> name -> definition or name
    builtin: Mapping[str, frozenset[str]]  # section -> names installed as built-ins
    names: Mapping[str, frozenset[str]]  # section -> registered names, built once per registration
    frozen: bool = False


_EMPTY = _State(
    entries=MappingProxyType({section: MappingProxyType({}) for section in SECTIONS}),
    builtin=MappingProxyType({section: frozenset() for section in SECTIONS}),
    names=MappingProxyType({section: frozenset() for section in SECTIONS}),
)


class Registry:
    """The vocabulary records validate against.

    `_state` is replaced whole under `_lock` and never mutated, so readers take no lock. Built-ins
    install on the first public call, through the same checks an extension meets.
    """

    def __init__(self, *, builtins: Callable[[], TypeExtension] | None = None) -> None:
        self._builtins = builtins
        self._installed = builtins is None
        self._installing = False
        self._lock = threading.RLock()
        self._state = _EMPTY

    def _ensure_builtins(self) -> None:
        if self._installed:
            return
        with self._lock:
            if self._installed:
                return
            if self._installing:
                # An RLock lets the installing thread get here instead of deadlocking.
                raise RuntimeError(
                    "The built-in vocabulary looked up the registry while it was being installed"
                )
            self._installing = True
            try:
                self._state = _checked(self._state, self._builtins(), declared=None, builtin=True)
                self._installed = True
            finally:
                self._installing = False

    # normative (design §3)
    def register(self, extension: TypeExtension, *, declared_families: Iterable[str] | None = None) -> None:
        if not isinstance(extension, TypeExtension):
            raise TypeError("Registry.register takes a TypeExtension")
        if isinstance(declared_families, str):
            raise TypeError("declared_families is a collection of family names, not one string")
        self._ensure_builtins()
        declared = None if declared_families is None else frozenset(declared_families)
        with self._lock:
            if self._state.frozen:
                raise RegistrationError("frozen", "Registry is frozen; register extensions before freeze()")
            self._state = _checked(self._state, extension, declared=declared, builtin=False)

    def freeze(self) -> None:
        self._ensure_builtins()
        with self._lock:
            if not self._state.frozen:
                self._state = replace(self._state, frozen=True)

    def fingerprint(self) -> str:
        self._ensure_builtins()
        return text_hash(canonical_json(_document(self._state)))

    def families(self) -> frozenset[str]:
        return self._names("families")

    def object_kind(self, name: str) -> ObjectKindDefinition:
        return self._lookup("object_kinds", name)

    def predicate(self, name: str) -> PredicateDefinition:
        return self._lookup("predicates", name)

    def locator(self, kind: str) -> type[LocatorBase]:
        return self._lookup("locator_kinds", kind).model

    def artifact_kind(self, name: str) -> str:
        return self._lookup("artifact_kinds", name)

    def connector_kind(self, name: str) -> str:
        return self._lookup("connector_kinds", name)

    def evidence_source(self, name: str) -> str:
        return self._lookup("evidence_sources", name)

    # decided by S1 plan
    @property
    def frozen(self) -> bool:
        self._ensure_builtins()
        return self._state.frozen

    def object_kinds(self) -> frozenset[str]:
        return self._names("object_kinds")

    def predicates(self) -> frozenset[str]:
        return self._names("predicates")

    def artifact_kinds(self) -> frozenset[str]:
        return self._names("artifact_kinds")

    def connector_kinds(self) -> frozenset[str]:
        return self._names("connector_kinds")

    def locator_kinds(self) -> frozenset[str]:
        return self._names("locator_kinds")

    def evidence_sources(self) -> frozenset[str]:
        return self._names("evidence_sources")

    @classmethod
    def with_builtins(cls) -> Registry:
        """A fresh, unfrozen registry holding only the built-ins; it shares no state with `REGISTRY`."""
        registry = cls(builtins=_builtin_extension)
        registry._ensure_builtins()
        return registry

    def declared_template_versions(self, kinds: Iterable[str]) -> dict[str, str]:
        """`{"<kind>.<template>": version}` over the fact templates of the named kinds (D25)."""
        if isinstance(kinds, str):
            raise TypeError("declared_template_versions takes a collection of kind names, not one string")
        versions = {}
        for kind in kinds:
            for template in self.object_kind(kind).fact_templates:
                versions[f"{kind}.{template.name}"] = template.version
        return dict(sorted(versions.items()))

    def _names(self, section: str) -> frozenset[str]:
        self._ensure_builtins()
        return self._state.names[section]

    def _lookup(self, section: str, name: str):
        self._ensure_builtins()
        try:
            return self._state.entries[section][name]
        except (KeyError, TypeError):
            raise UnregisteredName(f"Unknown {_LABELS[section]}: '{name}'") from None


_FORMATTER = string.Formatter()


def _template_fields(text: str, where: str, kind: str) -> list[str]:
    """Every replacement field name in a `str.format` template, including fields nested in format specs."""
    try:
        parsed = list(_FORMATTER.parse(text))
    except ValueError:
        raise RegistrationError(
            "malformed_template", f"{where} of object kind '{kind}' is not a valid format string"
        ) from None
    fields = []
    for _, field, spec, _ in parsed:
        if field is not None:
            fields.append(field)
        if spec:
            fields.extend(_template_fields(spec, where, kind))
    return fields


def _derivable_evidence_sources() -> frozenset[str]:
    from .builtin_types import EVIDENCE_CLASS_DERIVATION

    return frozenset(source for _, source, _ in EVIDENCE_CLASS_DERIVATION)


def _checked(
    state: _State, extension: TypeExtension, *, declared: frozenset[str] | None, builtin: bool
) -> _State:
    """The state with `extension` appended, or a `RegistrationError` naming the first failing rule."""
    entries = {section: dict(state.entries[section]) for section in SECTIONS}
    registered = {section: {name.casefold(): name for name in entries[section]} for section in SECTIONS}
    builtins = {section: {name.casefold(): name for name in state.builtin[section]} for section in SECTIONS}
    added = {section: [] for section in SECTIONS}
    if declared is None:
        declared = frozenset(extension.families) | {kind.family for kind in extension.object_kinds}

    def admit(section: str, name: str, value: object) -> None:
        label, folded = _LABELS[section], name.casefold()
        if folded in builtins[section]:
            raise RegistrationError(
                "shadows_builtin", f"{label} '{name}' shadows the built-in '{builtins[section][folded]}'"
            )
        if folded in registered[section]:
            raise RegistrationError(
                "duplicate_name",
                f"{label} '{name}' repeats the registered name '{registered[section][folded]}'",
            )
        check = _SECTION_RULES.get(section)
        if check is not None:
            check(value, entries=entries, declared=declared, builtin=builtin)
        entries[section][name] = value
        registered[section][folded] = name
        added[section].append(name)

    for name in extension.families:
        admit("families", name, name)
    for name in extension.evidence_sources:
        admit("evidence_sources", name, name)
    for name in extension.artifact_kinds:
        admit("artifact_kinds", name, name)
    for name in extension.connector_kinds:
        admit("connector_kinds", name, name)
    for definition in extension.locator_kinds:
        admit("locator_kinds", definition.name, definition)
    for definition in extension.object_kinds:
        admit("object_kinds", definition.name, definition)
    for definition in extension.predicates:
        admit("predicates", definition.name, definition)

    return _State(
        entries=MappingProxyType({section: MappingProxyType(entries[section]) for section in SECTIONS}),
        builtin=MappingProxyType(
            {
                section: state.builtin[section] | frozenset(added[section] if builtin else ())
                for section in SECTIONS
            }
        ),
        names=MappingProxyType({section: frozenset(entries[section]) for section in SECTIONS}),
        frozen=state.frozen,
    )


def _check_evidence_source(name: str, **_) -> None:
    # Ruling R29: the evidence class of every edge is derived from the design §4 table, so a source
    # with no row in it could never be emitted.
    if name not in _derivable_evidence_sources():
        raise RegistrationError(
            "underivable_evidence_source",
            f"evidence source '{name}' has no row in the evidence class derivation table",
        )


def _check_locator_kind(definition: LocatorKindDefinition, **_) -> None:
    name, model = definition.name, definition.model
    if model is None:
        raise RegistrationError("missing_locator_model", f"locator kind '{name}' has no model")
    kind = model.model_fields.get("kind") if issubclass(model, LocatorBase) else None
    if kind is None or kind.default != name:
        raise RegistrationError(
            "not_a_source_locator",
            f"locator kind '{name}' model is not a SourceLocator whose kind defaults to '{name}'",
        )


def _check_object_kind(definition: ObjectKindDefinition, *, entries, builtin: bool, **_) -> None:
    name = definition.name
    subject = f"object kind '{name}'"
    if definition.family not in entries["families"]:
        raise RegistrationError("unknown_family", f"{subject} names unknown family '{definition.family}'")
    if not definition.key_template:
        raise RegistrationError("empty_key_template", f"{subject} has an empty key template")
    seen = set()
    for part in definition.key_template:
        if part in seen:
            raise RegistrationError("repeated_key_part", f"{subject} repeats key part '{part}'")
        seen.add(part)
    model = definition.attrs_model
    if not builtin and model.model_config.get("extra") != "forbid":
        raise RegistrationError(
            "extra_attributes_allowed", f"{subject} attribute model {model.__name__} must forbid extra fields"
        )
    attributes = model.model_fields
    for reserved in sorted(RESERVED_TEMPLATE_FIELDS):
        if reserved in attributes:
            raise RegistrationError(
                "reserved_attribute",
                f"{subject} attribute model declares the reserved template field '{reserved}'",
            )

    def undeclared(where: str, field: str) -> RegistrationError:
        return RegistrationError(
            "undeclared_template_field", f"{where} of {subject} references undeclared attribute '{field}'"
        )

    for field in _template_fields(definition.label_template, "label template", name):
        if field not in attributes:
            raise undeclared("label template", field)
    for template in definition.fact_templates:
        where = f"fact template '{template.name}'"
        for attribute in template.consumes:
            if attribute not in attributes:
                raise undeclared(where, attribute)
        allowed = set(template.consumes) | RESERVED_TEMPLATE_FIELDS
        for field in _template_fields(template.text, where, name):
            if field not in allowed:
                raise undeclared(where, field)
    for template in definition.fact_templates:
        seen = set()
        for attribute in template.consumes:
            if attribute in seen:
                raise RegistrationError(
                    "repeated_template_attribute",
                    f"fact template '{template.name}' of {subject} repeats attribute '{attribute}'",
                )
            seen.add(attribute)


def _check_predicate(
    definition: PredicateDefinition, *, entries, declared: frozenset[str], builtin: bool, **_
) -> None:
    subject = f"predicate '{definition.name}'"
    if definition.identity and not builtin:
        raise RegistrationError(
            "identity_predicate", f"{subject} is an identity predicate; identity predicates are built-in"
        )
    endpoints = (("subject", definition.subject_kinds), ("object", definition.object_kinds))
    if not definition.identity:
        for role, kinds in endpoints:
            if not kinds:
                raise RegistrationError("empty_endpoint_kinds", f"{subject} declares no {role} kinds")
    for role, kinds in endpoints:
        for kind in sorted(kinds):
            if kind not in entries["object_kinds"]:
                raise RegistrationError(
                    "unregistered_endpoint_kind", f"{subject} names unregistered {role} kind '{kind}'"
                )
    if not definition.owner_families:
        raise RegistrationError("empty_owner_families", f"{subject} declares no owner families")
    for family in sorted(definition.owner_families):
        if family not in entries["families"]:
            raise RegistrationError("unknown_family", f"{subject} names unknown owner family '{family}'")
    if not builtin and not definition.identity and not definition.owner_families & declared:
        raise RegistrationError(
            "undeclared_owner_family",
            f"{subject}: none of its owner families {sorted(definition.owner_families)} "
            f"is declared by the registering connector {sorted(declared)}",
        )
    for source in sorted(definition.sources_allowed):
        if source not in entries["evidence_sources"]:
            raise RegistrationError(
                "unregistered_evidence_source", f"{subject} allows unregistered evidence source '{source}'"
            )


_SECTION_RULES = MappingProxyType(
    {
        "evidence_sources": _check_evidence_source,
        "locator_kinds": _check_locator_kind,
        "object_kinds": _check_object_kind,
        "predicates": _check_predicate,
    }
)


def _schema(model: type[BaseModel]) -> object:
    """A model's validation schema without schema-level `title`/`description` (field names stay)."""

    def node(value):
        if isinstance(value, list):
            return [node(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key in ("title", "description"):
                continue
            if key in ("properties", "$defs", "patternProperties") and isinstance(item, dict):
                result[key] = {name: node(child) for name, child in item.items()}
            else:
                result[key] = node(item)
        return result

    return node(model.model_json_schema(mode="validation"))


def _document(state: _State) -> dict:
    entries = state.entries

    def kind(definition: ObjectKindDefinition) -> dict:
        return {
            "name": definition.name,
            "family": definition.family,
            "key_template": list(definition.key_template),
            "key_prefix": definition.key_prefix,
            "attrs": _schema(definition.attrs_model),
            "label_template": definition.label_template,
            "fact_templates": sorted(
                (
                    {"name": t.name, "version": t.version, "consumes": list(t.consumes), "text": t.text}
                    for t in definition.fact_templates
                ),
                key=canonical_json,
            ),
            "scope_kind": definition.scope_kind,
        }

    def predicate(definition: PredicateDefinition) -> dict:
        return {
            field: sorted(value) if isinstance(value, frozenset) else value
            for field, value in definition.model_dump().items()
        }

    return {
        "version": FINGERPRINT_VERSION,
        "families": sorted(entries["families"]),
        "evidence_sources": sorted(entries["evidence_sources"]),
        "artifact_kinds": sorted(entries["artifact_kinds"]),
        "connector_kinds": sorted(entries["connector_kinds"]),
        "locator_kinds": [
            [name, _schema(entries["locator_kinds"][name].model)] for name in sorted(entries["locator_kinds"])
        ],
        "object_kinds": [kind(entries["object_kinds"][name]) for name in sorted(entries["object_kinds"])],
        "predicates": [predicate(entries["predicates"][name]) for name in sorted(entries["predicates"])],
    }


def _builtin_extension() -> TypeExtension:
    from .builtin_types import BUILTIN_EXTENSION

    return BUILTIN_EXTENSION


REGISTRY = Registry(builtins=_builtin_extension)
_CURRENT: ContextVar[Registry] = ContextVar("hippo_registry", default=REGISTRY)


def current_registry() -> Registry:
    """The registry every model validator and `predicates` consults."""
    return _CURRENT.get()


@contextmanager
def use_registry(registry: Registry) -> Iterator[Registry]:
    """Install `registry` as the current one for the body, and restore the previous one afterwards.

    A thread-pool worker starts in a fresh context and sees `REGISTRY`, unless the caller runs the
    work in `contextvars.copy_context()`.
    """
    if not isinstance(registry, Registry):
        raise TypeError("use_registry takes a Registry")
    token = _CURRENT.set(registry)
    try:
        yield registry
    finally:
        _CURRENT.reset(token)


@contextmanager
def extension_scope() -> Iterator[Registry]:
    """Extend the current registry in place for the body, unfrozen, then restore its state whole.

    Under the default the yielded registry is `REGISTRY` itself (ruling R16). For tests; not safe
    across threads.
    """
    registry = current_registry()
    registry._ensure_builtins()
    with registry._lock:
        saved = registry._state
        registry._state = replace(saved, frozen=False)
    try:
        yield registry
    finally:
        with registry._lock:
            registry._state = saved


def connector_configuration(
    *, name: str, version: str, templates: Mapping[str, str], parsers: Iterable[str]
) -> dict:
    """`{"connector": {...}}` with sorted parsers and templates; never the fingerprint (D25)."""
    return {
        "connector": {
            "name": name,
            "version": version,
            "parsers": sorted(parsers),
            "templates": dict(sorted(templates.items())),
        }
    }
