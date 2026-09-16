"""Canonical keys: one builder per registered kind, generated from its `key_template`.

Design `docs/spec/connector-developer-kit.md` section 5, plan `ai_docs/plans/cdk-s2-contract.md`
section 6. Identity is the kit's, not the connector's: a connector names key parts, and this module
assembles them in the registered template's order, fills the instance parts from the connector's
instance, and normalizes each built-in shape through the identity helper that already builds it
(`knowledge/identity.py`). Those helpers are called, never copied.

This is the only module in `hippo.connectors` that constructs a `KnowledgeObject`
(`tests/unit/test_connector_keys.py::test_keys_is_the_only_knowledge_object_constructor_in_connectors`).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..knowledge import model as k
from ..knowledge.identity import (
    canonical_json,
    commit_key,
    database_object_key,
    endpoint_key,
    file_key,
    knowledge_object_identity,
    normalize_provider_url,
    repository_key,
    resource_key,
    review_key,
    service_key,
    sql_identifier,
    symbol_key,
)
from ..knowledge.registry import ObjectKindDefinition, Registry, UnregisteredName
from . import base
from .emit import BindRefused

KEY_RULE_VERSION = "cdk-keys-v1"
INSTANCE_PARTS = frozenset({"instance", "provider_instance", "catalog_instance"})
# The kinds whose key parts are dialect-aware SQL identifiers; every other kind has plain parts.
_DATABASE_KINDS = {
    "database": 3,
    "schema": 4,
    "table": None,
    "column": None,
    "view": None,
    "constraint": None,
    "index": None,
    "routine": None,
}
_INSTANCE_REFUSAL = "The connector instance must be a normalized ASCII HTTP(S) provider URL"


class KeyPartsRefused(BindRefused):
    """A node reference the kit cannot key; the message names the fix.

    It is a `BindRefused` (plan section 10, Task S2b) so one `except` in a connector's tests, and in
    `hippo connector validate`, catches every refusal `bind_batch` can raise.
    """


@dataclass(frozen=True, slots=True)
class CanonicalKey:
    kind: str
    parts: tuple  # the canonical JSON array `knowledge_object_identity` hashes
    readable: str  # "wi:https://jira.example/10042"; display only, never hashed

    @property
    def canonical_json(self) -> str:
        return canonical_json(list(self.parts))


def check_key_parts(definition: ObjectKindDefinition, ref: base.NodeRef) -> None:
    """Refuse a `NodeRef` whose key is not exactly the kind's non-instance template parts."""
    expected = tuple(part for part in definition.key_template if part not in INSTANCE_PARTS)
    for part in ref.key:
        if part in INSTANCE_PARTS:
            raise KeyPartsRefused(
                f"The kit fills {part} of {definition.name} from the connector's instance; do not emit it"
            )
    if set(ref.key) != set(expected):
        raise KeyPartsRefused(
            f"NodeRef for {definition.name} needs key parts {list(expected)}, got {sorted(ref.key)}"
        )
    if ref.instance is not None and not (set(definition.key_template) & INSTANCE_PARTS):
        raise KeyPartsRefused(f"Kind {definition.name} has no instance key part; drop the declared instance")


def canonical_key(registry: Registry, ref: base.NodeRef, *, instance: str) -> CanonicalKey:
    """The canonical key array of `ref`, in its kind's template order.

    `instance` is the Connector row's `instance_url`. A foreign endpoint that declares its own
    instance (ruling R53) is keyed by that one, so both sources mint the same object.
    """
    definition = _definition(registry, ref.kind)
    check_key_parts(definition, ref)
    instance_value = ref.instance if ref.instance is not None else _checked_instance(instance)
    values = {
        part: instance_value if part in INSTANCE_PARTS else ref.key[part] for part in definition.key_template
    }
    if ref.kind in _DATABASE_KINDS:
        parts = _database_parts(ref.kind, values, _DATABASE_KINDS[ref.kind])
    else:
        _check_plain(ref.kind, values)
        parts = _BUILDERS.get(ref.kind, _plain)(values)
    return CanonicalKey(kind=ref.kind, parts=tuple(parts), readable=_readable(definition, parts))


def knowledge_object(
    registry: Registry, ref: base.NodeRef, *, workspace_id: str, instance: str
) -> k.KnowledgeObject:
    """The `KnowledgeObject` of `ref`, whose id is `knowledge_object_identity`'s and nothing else."""
    key = canonical_key(registry, ref, instance=instance)
    parts = list(key.parts)
    obj = k.KnowledgeObject(workspace_id=workspace_id, kind=ref.kind, canonical_key=key.canonical_json)
    expected = knowledge_object_identity(workspace_id, ref.kind, parts)
    if obj.id != expected:
        raise KeyPartsRefused(f"Object identity for {ref.kind} does not match the canonical key")
    return obj


def _definition(registry: Registry, kind: str) -> ObjectKindDefinition:
    try:
        return registry.object_kind(kind)
    except UnregisteredName as error:
        raise KeyPartsRefused(
            f"object kind {kind!r} is not registered; register it with a TypeExtension before emitting"
        ) from error


def _checked_instance(instance: str) -> str:
    """The connector instance, already normalized. The refusal never echoes it: it may carry a secret."""
    try:
        if normalize_provider_url(instance) != instance:
            raise ValueError(_INSTANCE_REFUSAL)
    except ValueError as error:
        raise KeyPartsRefused(_INSTANCE_REFUSAL) from error
    return instance


def _check_plain(kind: str, values: dict) -> None:
    for name, value in values.items():
        if not isinstance(value, str):
            raise KeyPartsRefused(f"Kind {kind} has plain key parts; SqlPart values belong to database kinds")
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise KeyPartsRefused(f"Key part {name} of {kind} contains control characters")


def _refusing(build, kind: str):
    """Run an identity helper, turning its refusal into the developer-facing one."""
    try:
        return build()
    except ValueError as error:
        raise KeyPartsRefused(f"Key parts of {kind} are invalid: {error}") from error


def _plain(values: dict) -> list:
    return list(values.values())


def _service(values: dict) -> list:
    return _refusing(lambda: service_key(values["catalog_instance"], values["reference"]), "service")


def _repository(values: dict) -> list:
    return _refusing(
        lambda: repository_key(values["provider_instance"], values["repository_id"]), "repository"
    )


def _review(values: dict) -> list:
    return _refusing(
        lambda: review_key(values["provider_instance"], values["repository_id"], values["review_id"]),
        "review",
    )


def _endpoint(values: dict) -> list:
    return _refusing(
        lambda: endpoint_key(
            values["service"],
            values["protocol"],
            values["api_version"],
            values["method"],
            values["path_template"],
            api_identity=values["api_identity"],
        ),
        "endpoint",
    )


def _api(values: dict) -> list:
    # The first four parts of an endpoint key, so an api and its endpoints share the helper's
    # protocol casing. The method and path are placeholders the slice drops.
    return _refusing(
        lambda: endpoint_key(
            values["service"],
            values["protocol"],
            values["api_version"],
            "GET",
            "/",
            api_identity=values["api_identity"],
        )[:4],
        "api",
    )


def _symbol(values: dict) -> list:
    return _refusing(
        lambda: symbol_key(
            values["repository"],
            values["language"],
            values["path"],
            values["qualified_name"],
            values["signature"],
            kind=values["symbol_kind"],
        ),
        "symbol",
    )


def _file(values: dict) -> list:
    return _refusing(lambda: file_key(values["repository"], values["path"]), "file")


def _commit(values: dict) -> list:
    return _refusing(lambda: commit_key(values["repository"], values["sha"]), "commit")


def _resource(values: dict) -> list:
    return _refusing(
        lambda: resource_key(
            values["repository"], values["dialect"], values["data_kind"], values["qualname"]
        ),
        "resource",
    )


_BUILDERS = {
    "service": _service,
    "system": _service,
    "domain": _service,
    "repository": _repository,
    "review": _review,
    "endpoint": _endpoint,
    "api": _api,
    "symbol": _symbol,
    "file": _file,
    "commit": _commit,
    "resource": _resource,
}


def _database_parts(kind: str, values: dict, count: int | None) -> list:
    """`database_object_key`, or its leading parts for `database` and `schema`.

    The dialect comes from the first `SqlPart` among catalog, schema and the object parts: the helper
    keeps dialect-aware identifiers, and a plain string alone cannot say which dialect folds it.
    """
    emitted = values.get("parts")
    parts = list(emitted) if isinstance(emitted, tuple) else ([emitted] if emitted is not None else [])
    candidates = [values.get("catalog"), values.get("schema"), *parts]
    dialect = next((value.dialect for value in candidates if isinstance(value, base.SqlPart)), None)
    if dialect is None:
        raise KeyPartsRefused(f"Kind {kind} needs a SqlPart key part to fix its dialect")
    for name in ("environment",):
        if not isinstance(values.get(name), str):
            raise KeyPartsRefused(f"Key part {name} of {kind} is a plain value")
    catalog = _identifier(values["catalog"], dialect)
    schema = _identifier(values.get("schema", values["catalog"]), dialect)
    if not parts:
        parts = [values.get("schema", values["catalog"])]
    identifiers = [_identifier(part, dialect) for part in parts]
    key = _refusing(
        lambda: database_object_key(values["instance"], values["environment"], catalog, schema, identifiers),
        kind,
    )
    return key[:count] if count is not None else key


def _identifier(value, dialect: str):
    if isinstance(value, base.SqlPart):
        return sql_identifier(
            value.original, dialect=value.dialect, quoted=value.quoted, collation=value.collation
        )
    return sql_identifier(value, dialect=dialect)


def _readable(definition: ObjectKindDefinition, parts) -> str:
    rendered = "/".join(part if isinstance(part, str) else canonical_json(part) for part in parts)
    return f"{definition.key_prefix}:{rendered}"
