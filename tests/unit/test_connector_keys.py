"""Canonical keys: one builder per registered kind, generated from its `key_template`.

Plan `ai_docs/plans/cdk-s2-contract.md` section 6, with ruling R28 (the public `file_key`,
`commit_key` and `resource_key` helpers), R53 (an identity-only foreign endpoint carries its own
instance) and review minor m21 (the static constructor check also flags `model_validate`,
`model_construct` and `replace`). Every built-in row is pinned against the helper, or the only
writer, that builds that key today.
"""

import ast
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

import hippo.connectors
from hippo.connectors import base, keys
from hippo.knowledge import code_binding, code_history, identity
from hippo.knowledge import model as k
from hippo.knowledge.contract import Text
from hippo.knowledge.identity import (
    canonical_json,
    database_object_key,
    endpoint_key,
    knowledge_object_identity,
    repository_key,
    review_key,
    service_key,
    sql_identifier,
    symbol_key,
)
from hippo.knowledge.locators import LocatorBase
from hippo.knowledge.registry import (
    LocatorKindDefinition,
    ObjectKindDefinition,
    TypeExtension,
    extension_scope,
)

WORKSPACE = "workspace"
INSTANCE = "https://incidents.example"
CATALOG = "https://backstage.example"


class IncidentAttributes(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    title: str


class IncidentEventLocator(LocatorBase):
    kind: Literal["incident_event"] = "incident_event"
    event_id: Text


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
            ),
            ObjectKindDefinition(
                name="pager_rotation",
                family="incident",
                key_template=("provider_instance", "team", "rotation_id"),
                key_prefix="rot",
                attrs_model=IncidentAttributes,
                label_template="{title}",
            ),
        ),
        artifact_kinds=("incident_export",),
        locator_kinds=(LocatorKindDefinition(name="incident_event", model=IncidentEventLocator),),
    )


@pytest.fixture
def registry():
    with extension_scope() as scoped:
        scoped.register(incident_extension())
        scoped.freeze()
        yield scoped


def key_of(registry, kind: str, key: dict, *, instance: str = INSTANCE, node_instance: str | None = None):
    ref = base.NodeRef(kind=kind, key=key, instance=node_instance)
    return keys.canonical_key(registry, ref, instance=instance)


def object_of(registry, kind: str, key: dict, *, instance: str = INSTANCE) -> k.KnowledgeObject:
    return keys.knowledge_object(
        registry, base.NodeRef(kind=kind, key=key), workspace_id=WORKSPACE, instance=instance
    )


# ------------------------------------------------------------------ the rule


def test_key_rule_version_is_pinned() -> None:
    assert keys.KEY_RULE_VERSION == "cdk-keys-v1"
    assert keys.INSTANCE_PARTS == frozenset({"instance", "provider_instance", "catalog_instance"})
    assert issubclass(keys.KeyPartsRefused, base.ContractError)


def test_check_key_parts_requires_exactly_the_non_instance_template_parts(registry) -> None:
    definition = registry.object_kind("pager_rotation")
    keys.check_key_parts(
        definition, base.NodeRef(kind="pager_rotation", key={"team": "checkout", "rotation_id": "R-1"})
    )
    for key in (
        {"team": "checkout"},
        {"team": "checkout", "rotation_id": "R-1", "extra": "x"},
    ):
        with pytest.raises(keys.KeyPartsRefused) as error:
            keys.check_key_parts(definition, base.NodeRef(kind="pager_rotation", key=key))
        message = str(error.value)
        assert message.startswith("NodeRef for pager_rotation needs key parts")
        assert "team" in message and "rotation_id" in message


def test_instance_parts_are_filled_from_the_connector_instance_and_refused_in_a_node_ref(registry) -> None:
    built = key_of(registry, "pager_rotation", {"team": "checkout", "rotation_id": "R-1"})
    assert built.parts == (INSTANCE, "checkout", "R-1")
    with pytest.raises(keys.KeyPartsRefused) as error:
        key_of(
            registry,
            "pager_rotation",
            {"provider_instance": INSTANCE, "team": "checkout", "rotation_id": "R-1"},
        )
    assert (
        "The kit fills provider_instance of pager_rotation from the connector's instance; do not emit it"
        in str(error.value)
    )


def test_identity_only_endpoint_is_keyed_by_its_declared_instance(registry) -> None:
    """Ruling R53: a foreign endpoint keeps the instance that minted its name, not the emitter's."""
    reference = "component:default/checkout"
    foreign = key_of(
        registry, "service", {"reference": reference}, node_instance="HTTPS://Backstage.Example/"
    )
    assert foreign.parts == tuple(service_key(CATALOG, reference))
    assert foreign.parts != key_of(registry, "service", {"reference": reference}).parts
    foreign_object = keys.knowledge_object(
        registry,
        base.NodeRef(kind="service", key={"reference": reference}, instance=CATALOG),
        workspace_id=WORKSPACE,
        instance=INSTANCE,
    )
    assert foreign_object.id == knowledge_object_identity(
        WORKSPACE, "service", service_key(CATALOG, reference)
    )
    with pytest.raises(keys.KeyPartsRefused) as error:
        key_of(
            registry, "incident_fixture", {"tool": "pagerduty", "incident_id": "INC-1"}, node_instance=CATALOG
        )
    assert "Kind incident_fixture has no instance key part; drop the declared instance" in str(error.value)


def test_extension_kind_key_follows_its_template_order(registry) -> None:
    built = key_of(registry, "incident_fixture", {"incident_id": "INC-2210", "tool": "pagerduty"})
    assert built.kind == "incident_fixture"
    assert built.parts == ("pagerduty", "INC-2210")
    assert built.canonical_json == canonical_json(["pagerduty", "INC-2210"])


def test_an_unregistered_kind_is_refused_with_its_registration_instruction(registry) -> None:
    with pytest.raises(keys.KeyPartsRefused) as error:
        key_of(registry, "outage", {"id": "INC-1"})
    assert "object kind 'outage' is not registered; register it with a TypeExtension before emitting" in str(
        error.value
    )


def test_plain_kinds_refuse_sql_parts_and_control_characters(registry) -> None:
    with pytest.raises(keys.KeyPartsRefused) as error:
        key_of(
            registry,
            "incident_fixture",
            {"tool": base.SqlPart(original="pagerduty", dialect="postgres"), "incident_id": "INC-1"},
        )
    assert "Kind incident_fixture has plain key parts; SqlPart values belong to database kinds" in str(
        error.value
    )
    with pytest.raises(keys.KeyPartsRefused) as error:
        key_of(registry, "incident_fixture", {"tool": "pager\tduty", "incident_id": "INC-1"})
    assert "Key part tool of incident_fixture contains control characters" in str(error.value)


def test_readable_key_uses_the_kind_prefix_and_is_never_hashed(registry) -> None:
    built = key_of(registry, "incident_fixture", {"tool": "pagerduty", "incident_id": "INC-2210"})
    assert built.readable == "incx:pagerduty/INC-2210"
    assert built.readable not in built.canonical_json
    obj = object_of(registry, "incident_fixture", {"tool": "pagerduty", "incident_id": "INC-2210"})
    assert built.readable not in obj.canonical_key
    assert obj.id == knowledge_object_identity(WORKSPACE, "incident_fixture", ["pagerduty", "INC-2210"])
    table = key_of(
        registry,
        "table",
        {
            "environment": "prod",
            "catalog": base.SqlPart(original="shop", dialect="postgres"),
            "schema": base.SqlPart(original="public", dialect="postgres"),
            "parts": (base.SqlPart(original="Orders", dialect="postgres"),),
        },
    )
    assert table.readable.startswith("tbl:")
    # `sql_identifier` folds an unquoted postgres identifier, and the readable key shows what the
    # helper stored, not what the connector typed.
    assert "orders" in table.readable
    quoted = key_of(
        registry,
        "table",
        {
            "environment": "prod",
            "catalog": base.SqlPart(original="shop", dialect="postgres"),
            "schema": base.SqlPart(original="public", dialect="postgres"),
            "parts": (base.SqlPart(original="Orders", dialect="postgres", quoted=True),),
        },
    )
    assert "Orders" in quoted.readable


def test_instance_must_be_a_normalized_ascii_provider_url(registry) -> None:
    for instance in ("https://INCIDENTS.example", "https://incidents.example/", "not a url", "ftp://x"):
        with pytest.raises(keys.KeyPartsRefused) as error:
            key_of(registry, "incident_fixture", {"tool": "t", "incident_id": "i"}, instance=instance)
        assert "The connector instance must be a normalized ASCII HTTP(S) provider URL" in str(error.value)
    with pytest.raises(keys.KeyPartsRefused) as error:
        key_of(registry, "incident_fixture", {"tool": "t", "incident_id": "i"}, instance="https://u:s3cret@x")
    assert "s3cret" not in str(error.value), "a refusal never echoes the credential"


def test_object_id_equals_knowledge_object_identity(registry) -> None:
    obj = object_of(registry, "incident_fixture", {"tool": "pagerduty", "incident_id": "INC-2210"})
    assert obj.kind == "incident_fixture"
    assert obj.workspace_id == WORKSPACE
    assert json.loads(obj.canonical_key) == ["pagerduty", "INC-2210"]
    assert obj.id == knowledge_object_identity(WORKSPACE, "incident_fixture", ["pagerduty", "INC-2210"])


# ------------------------------------------------------------------ parity with the built-in shapes


@pytest.mark.parametrize("kind", ["service", "system", "domain"])
def test_service_system_and_domain_keys_equal_service_key(registry, kind: str) -> None:
    reference = "Component:Default/Checkout"
    built = key_of(registry, kind, {"reference": reference}, instance=CATALOG)
    assert list(built.parts) == service_key(CATALOG, reference)
    assert object_of(
        registry, kind, {"reference": reference}, instance=CATALOG
    ).id == knowledge_object_identity(WORKSPACE, kind, service_key(CATALOG, reference))


def test_repository_and_review_keys_equal_their_identity_helpers(registry) -> None:
    repository = key_of(registry, "repository", {"repository_id": "42"})
    assert list(repository.parts) == repository_key(INSTANCE, "42")
    review = key_of(registry, "review", {"repository_id": "42", "review_id": "7"})
    assert list(review.parts) == review_key(INSTANCE, "42", "7")


def test_endpoint_and_api_keys_equal_endpoint_key_and_its_prefix(registry) -> None:
    service_object_id = object_of(registry, "service", {"reference": "component:default/checkout"}).id
    endpoint = key_of(
        registry,
        "endpoint",
        {
            "service": service_object_id,
            "protocol": "HTTP",
            "api_identity": "public",
            "api_version": "v1",
            "method": "get",
            "path_template": "/orders/{id}",
        },
    )
    assert list(endpoint.parts) == endpoint_key(
        service_object_id, "HTTP", "v1", "get", "/orders/{id}", api_identity="public"
    )
    api = key_of(
        registry,
        "api",
        {
            "service": service_object_id,
            "protocol": "HTTP",
            "api_identity": "public",
            "api_version": "v1",
        },
    )
    assert (
        list(api.parts)
        == endpoint_key(service_object_id, "HTTP", "v1", "GET", "/", api_identity="public")[:4]
    )
    assert api.parts[1] == "http", "the helper lowercases the protocol"


def test_symbol_key_equals_symbol_key(registry) -> None:
    built = key_of(
        registry,
        "symbol",
        {
            "repository": "object-repo",
            "language": "python",
            "path": "src/hippo/cli.py",
            "qualified_name": "hippo.cli.main",
            "symbol_kind": "function",
            "signature": "(argv: list[str]) -> int",
        },
    )
    assert list(built.parts) == symbol_key(
        "object-repo",
        "python",
        "src/hippo/cli.py",
        "hippo.cli.main",
        "(argv: list[str]) -> int",
        kind="function",
    )


def test_database_kind_keys_equal_database_object_key_and_its_prefixes(registry) -> None:
    catalog = base.SqlPart(original="Shop", dialect="postgres")
    schema = base.SqlPart(original="Public", dialect="postgres")
    column = base.SqlPart(original="Orders", dialect="postgres", quoted=True, collation="C")
    expected = database_object_key(
        INSTANCE,
        "prod",
        sql_identifier("Shop", dialect="postgres"),
        sql_identifier("Public", dialect="postgres"),
        [sql_identifier("Orders", dialect="postgres", quoted=True, collation="C")],
    )
    table = key_of(
        registry,
        "table",
        {"environment": "prod", "catalog": catalog, "schema": schema, "parts": (column,)},
    )
    assert list(table.parts) == expected
    database = key_of(registry, "database", {"environment": "prod", "catalog": catalog})
    assert list(database.parts) == expected[:3]
    schema_key = key_of(registry, "schema", {"environment": "prod", "catalog": catalog, "schema": schema})
    assert list(schema_key.parts) == expected[:4]
    with pytest.raises(keys.KeyPartsRefused) as error:
        key_of(registry, "database", {"environment": "prod", "catalog": "shop"})
    assert "Kind database needs a SqlPart key part to fix its dialect" in str(error.value)


def test_file_key_matches_code_binding_file_object(registry) -> None:
    """Ruling R28: the public helper wraps the only writer's spelling (`code_binding._file_object`)."""
    repository = "object-repo"
    assert identity.file_key(repository, "./src/hippo/cli.py") == [repository, "src/hippo/cli.py"]
    written = code_binding._file_object(WORKSPACE, repository, "src/hippo/cli.py")
    built = object_of(registry, "file", {"repository": repository, "path": "src/hippo/cli.py"})
    assert built.id == written.id
    assert json.loads(built.canonical_key) == identity.file_key(repository, "src/hippo/cli.py")


def test_resource_key_matches_code_binding_data_object(registry) -> None:
    repository = "object-repo"
    data = SimpleNamespace(kind="collection", dialect="mongo", qualname="shop.orders", name="orders")
    written = code_binding._data_object(WORKSPACE, repository, data)
    assert written.kind == "resource"
    built = object_of(
        registry,
        "resource",
        {
            "repository": repository,
            "dialect": "mongo",
            "data_kind": "collection",
            "qualname": "shop.orders",
        },
    )
    assert built.id == written.id
    assert identity.resource_key(repository, "mongo", "collection", "shop.orders") == json.loads(
        written.canonical_key
    )


def test_commit_key_matches_the_code_history_commit_object(registry) -> None:
    repository, sha = "object-repo", "0" * 40
    assert identity.commit_key(repository, sha) == [repository, sha]
    built = object_of(registry, "commit", {"repository": repository, "sha": sha})
    assert built.id == knowledge_object_identity(WORKSPACE, "commit", [repository, sha])
    # The only writer builds the key inline, so the spelling is pinned at its source anchor.
    source = inspect.getsource(code_history)
    assert 'kind="commit",\n        canonical_key=canonical_json([repository_object_id, sha]),' in source


# ------------------------------------------------------------------ the static constructor check


FORBIDDEN_SOURCES = {
    "call": "obj = KnowledgeObject(workspace_id=w, kind=kind, canonical_key=key)\n",
    "qualified call": "obj = k.KnowledgeObject(workspace_id=w, kind=kind, canonical_key=key)\n",
    "model_validate": "obj = KnowledgeObject.model_validate(row)\n",
    "model_validate_json": "obj = k.KnowledgeObject.model_validate_json(row)\n",
    "model_construct": "obj = KnowledgeObject.model_construct(**row)\n",
    "class replace": "obj = k.KnowledgeObject.replace(other, kind=kind)\n",
    "instance replace": "obj = stored.replace(canonical_key=key)\n",
}


def _constructors(source: str) -> list[str]:
    """Every `KnowledgeObject` identity construction in one module's source (review minor m21).

    Calls only. Naming the class is not minting one: S2b's `BoundBatch.objects:
    tuple[k.KnowledgeObject, ...]` and any `isinstance` test must stay legal, and `ast.parse` keeps
    annotation nodes whether or not the module postpones evaluation.
    """
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted(node.func)
        if name is None:
            continue
        parts = name.split(".")
        if "KnowledgeObject" in parts:
            found.append(name)
        elif parts[-1] in {"replace", "model_copy", "model_construct"} and any(
            keyword.arg == "canonical_key" for keyword in node.keywords
        ):
            found.append(name)
    return sorted(set(found))


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        inner = _dotted(node.value)
        return f"{inner}.{node.attr}" if inner else node.attr
    return None


ALLOWED_SOURCES = {
    "field annotation": "objects: tuple[k.KnowledgeObject, ...] = ()\n",
    "return annotation": "def build() -> k.KnowledgeObject:\n    return keys.knowledge_object(r, ref)\n",
    "isinstance": "if isinstance(row, k.KnowledgeObject):\n    pass\n",
    "dataclass field": "@dataclass\nclass Bound:\n    objects: tuple[KnowledgeObject, ...]\n",
    "unrelated replace": "span = stored.replace(policy_id=policy)\n",
}


@pytest.mark.parametrize("case", sorted(FORBIDDEN_SOURCES))
def test_the_constructor_check_flags_every_way_to_mint_an_identity(case: str) -> None:
    assert _constructors(FORBIDDEN_SOURCES[case]), case


@pytest.mark.parametrize("case", sorted(ALLOWED_SOURCES))
def test_the_constructor_check_ignores_annotations_and_type_tests(case: str) -> None:
    """S2b's `BoundBatch` names the class in annotations; a name is not an identity."""
    assert _constructors(ALLOWED_SOURCES[case]) == [], case


def test_keys_is_the_only_knowledge_object_constructor_in_connectors() -> None:
    package = Path(hippo.connectors.__file__).parent
    modules = sorted(package.rglob("*.py"))
    assert {path.name for path in modules} >= {"__init__.py", "base.py", "classify.py", "keys.py"}
    offenders = {
        path.name: _constructors(path.read_text())
        for path in modules
        if path.name != "keys.py" and _constructors(path.read_text())
    }
    assert offenders == {}, f"KnowledgeObject identities outside keys.py: {offenders}"
    assert _constructors((package / "keys.py").read_text()), "keys.py is where identities are built"
