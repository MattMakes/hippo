"""The connector routes and the `hippo_connectors` MCP tool.

Plan `ai_docs/plans/cdk-s6-exemplar.md` section 6, gate CK6. Rulings and review findings that bind
this file: R8 (the probe route runs on the stored instance configuration; the validate route and the
tool return the contract-scope report), R14 (the tool is `hippo_connectors`), R49/B3 (the validate
surfaces run under S3a's per-thread guard, so a concurrent request is undisturbed), R64 (the list is
keyed on `(origin, name)` and renders `LoadResult.error`, including `error="frozen"`), R73 (every
`ensure_connector` call passes `enabled=` deliberately), R77 (open mode refuses a provider
`Connector` row, so every row-seeding test signs an operator in; a test that seeds an extension kind
registers it in an `extension_scope()` that closes before the app is built), m11 (`CredentialError`,
`Provider*Error`, `RegistrationRequired` and `ConnectorSyncRefused` become coded responses with
redacted messages).

Every test that needs a test client imports it inside the function and carries the per-test marker
of rulebook line 19 form (a), so this module imports no test client at collection time.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hippo.connectors import base, loader, sync, testing
from hippo.connectors.examples import incidents_ndjson as exemplar
from hippo.knowledge import model as k
from hippo.knowledge.registry import Registry, extension_scope, use_registry
from hippo.web.routes import connectors as routes

ANYIO = "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"
PACKAGE = Path(exemplar.__file__).resolve().parent
EXPORT = PACKAGE / "export" / "incidents.ndjson"
INSTANCE = "https://incidents.example"


# ------------------------------------------------------------------ harness


def _config(**overrides):
    payload = json.loads((PACKAGE / "fixtures" / "basic" / "config.json").read_text(encoding="utf-8"))
    payload["export_path"] = str(EXPORT)
    payload["instance_url"] = INSTANCE
    return exemplar.Connector.descriptor.config_model.model_validate(payload | overrides)


@pytest.fixture
def operator(store):
    """A signed-in installation with `manage_sources`; R77 makes it a precondition of every row."""
    store.ensure_schema()
    store.ensure_roles()
    return store.create_user("operator", "password", "local-admin")


@pytest.fixture
def reader(store):
    store.ensure_schema()
    store.ensure_roles()
    return store.create_user("reader", "password", "individual")


@pytest.fixture
def ctx(store, tmp_path):
    from hippo.config import Config
    from hippo.context import AppContext

    store.ensure_schema()
    store.ensure_roles()
    return AppContext(config=Config(data_dir=tmp_path / "data"), store=store, ollama=testing.offline_ollama())


def _seed_instance(ctx, *, enabled: bool = True, config=None):
    """One `Connector` row of the exemplar kind, with its stored classification.

    The extension is registered in an `extension_scope()` that closes before the caller builds the
    app (S4b gotcha 5, R64): the store's write path is vocabulary-checked, and leaving the kind
    registered would make the lifespan's own `register` fail with `duplicate_name`.
    """
    connector = exemplar.Connector()
    configured = config or _config()
    with extension_scope() as scoped:
        scoped.register(exemplar.types.EXTENSION, declared_families=("incident",))
        probe = scoped
        source = ctx.store.create_source("text", "workspace probe", {})
        row = sync.ensure_connector(
            ctx.store,
            workspace_id=ctx.store.get_source(source)["workspace_id"],
            kind="incidents_ndjson",
            instance_url=INSTANCE,
            config=configured,
            enabled=enabled,  # R73: deliberate on every call
        )
        with use_registry(probe):
            classification = connector.probe(configured, ctx.store._now)
        row = sync.store_classification(ctx.store, connector=row, classification=classification)
    return row


def _headers(ctx, user_id: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + ctx.store.get_user(user_id)["token"]}


def _client(ctx):
    """One test client over the whole app.

    Leaving its context runs the FastAPI lifespan's shutdown, which calls `ctx.close()` and closes
    the store. On LadybugDB that is a real close: a store read after the `with` block answers
    `RuntimeError: Connection is closed`, where the Fake store answers as if nothing happened. Any
    assertion that reads the store back therefore stays inside the block, and a test that makes
    several requests builds one client for all of them.
    """
    from fastapi.testclient import TestClient

    from hippo.web.app import create_app

    return TestClient(create_app(ctx), base_url="http://localhost")


# ------------------------------------------------------------------ the routes


@pytest.mark.filterwarnings(ANYIO)
def test_get_connectors_lists_the_exemplar_with_its_instance_and_classification(ctx, operator):
    row = _seed_instance(ctx)
    with use_registry(Registry.with_builtins()), _client(ctx) as client:
        body = client.get("/api/connectors", headers=_headers(ctx, operator))
    assert body.status_code == 200
    entry = next(item for item in body.json() if item["name"] == "incidents_ndjson")
    assert entry["origin"] == "in-repo"
    assert entry["version"] == "1"
    assert entry["families"] == ["incident"]
    assert entry["enabled"] is True
    assert entry["error"] is None
    assert [instance["id"] for instance in entry["instances"]] == [row.id]
    assert entry["instances"][0]["partitions"] == [
        {"partition": exemplar.connector.PARTITION, "family": "incident"}
    ]
    # R64: rows are keyed on `(origin, name)`, so a built-in kind and a package never merge.
    keyed = [(item["origin"], item["name"]) for item in body.json()]
    assert len(keyed) == len(set(keyed))


def test_the_list_payload_is_the_one_the_cli_prints(ctx, operator):
    """`cli.py` is not this slice's to edit, so the two builders are pinned against each other."""
    from hippo import cli

    _seed_instance(ctx)
    with use_registry(Registry.with_builtins()):
        assert routes.connectors_payload(ctx) == cli._connector_summaries(ctx)


@pytest.mark.filterwarnings(ANYIO)
def test_every_connector_route_requires_manage_sources(ctx, operator, reader):
    row = _seed_instance(ctx)
    calls = (
        ("get", "/api/connectors"),
        ("get", f"/api/connectors/{row.id}/classification"),
        ("post", f"/api/connectors/{row.id}/probe"),
        ("post", "/api/connectors/kinds/incidents_ndjson/validate"),
    )
    with use_registry(Registry.with_builtins()), _client(ctx) as client:
        for method, path in calls:
            denied = getattr(client, method)(path, headers=_headers(ctx, reader))
            assert denied.status_code == 403, f"{method} {path} is not behind manage_sources"
            assert "manage_sources" in denied.json()["detail"]


@pytest.mark.filterwarnings(ANYIO)
def test_post_probe_runs_the_stored_instance_config_and_stores_the_classification(ctx, operator):
    row = _seed_instance(ctx)
    # A stale stored value, so the assertion below measures this probe and not the seeder's.
    stale = json.dumps({"connector": "incidents_ndjson", "partitions": []}, sort_keys=True)
    with extension_scope() as scoped:
        scoped.register(exemplar.types.EXTENSION, declared_families=("incident",))
        ctx.store.update_knowledge(
            ctx.store._knowledge_get("Connector", row.id).replace(classification_json=stale)
        )
    with use_registry(Registry.with_builtins()), _client(ctx) as client:
        answered = client.post(f"/api/connectors/{row.id}/probe", headers=_headers(ctx, operator))
        assert answered.status_code == 200
        payload = answered.json()
        assert payload["connector"] == "incidents_ndjson"
        assert [entry["partition"] for entry in payload["partitions"]] == [exemplar.connector.PARTITION]
        assert payload["partitions"][0]["family"] == "incident"
        # Read back inside the block: the lifespan's shutdown closes the store (see `_client`).
        stored = ctx.store._knowledge_get("Connector", row.id)
        assert stored.classification_json != stale, "R-S3-3: the probe route stores what it read"
        assert json.loads(stored.classification_json) == payload


@pytest.mark.filterwarnings(ANYIO)
def test_post_probe_accepts_no_caller_supplied_config(ctx, operator):
    row = _seed_instance(ctx)
    with use_registry(Registry.with_builtins()), _client(ctx) as client:
        supplied = client.post(
            f"/api/connectors/{row.id}/probe",
            headers=_headers(ctx, operator),
            json={"export_path": "/etc", "instance_url": INSTANCE},
        )
    # The body is ignored, not honoured: a caller-supplied path would make the server read an
    # arbitrary local directory (plan section 6.1).
    assert supplied.status_code == 200
    assert supplied.json()["partitions"][0]["sample_count"] > 0


@pytest.mark.filterwarnings(ANYIO)
def test_get_classification_returns_the_stored_probe_result(ctx, operator):
    row = _seed_instance(ctx)
    with use_registry(Registry.with_builtins()), _client(ctx) as client:
        answered = client.get(f"/api/connectors/{row.id}/classification", headers=_headers(ctx, operator))
        assert answered.status_code == 200
        stored = ctx.store._knowledge_get("Connector", row.id).classification_json
    assert answered.json() == json.loads(stored)


@pytest.mark.filterwarnings(ANYIO)
def test_get_classification_of_an_unknown_instance_is_404_not_found(ctx, operator):
    with use_registry(Registry.with_builtins()), _client(ctx) as client:
        missing = client.get("/api/connectors/c-nope/classification", headers=_headers(ctx, operator))
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"


@pytest.mark.filterwarnings(ANYIO)
def test_post_validate_returns_the_validation_report_of_the_exemplar(ctx, operator):
    with use_registry(Registry.with_builtins()), _client(ctx) as client:
        answered = client.post(
            "/api/connectors/kinds/incidents_ndjson/validate", headers=_headers(ctx, operator)
        )
    assert answered.status_code == 200
    report = answered.json()
    assert report["connector"] == "incidents_ndjson" and report["version"] == "1"
    assert report["passed"] is True
    assert report["violations"] == []
    assert "+ predicate AFFECTS" in report["registry_diff"]


@pytest.mark.filterwarnings(ANYIO)
def test_post_validate_runs_no_scratch_build_and_reports_scope_contract(ctx, operator, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("the validate route must not open a scratch store")

    monkeypatch.setattr(testing, "scratch_workspace", refuse)
    with use_registry(Registry.with_builtins()), _client(ctx) as client:
        answered = client.post(
            "/api/connectors/kinds/incidents_ndjson/validate", headers=_headers(ctx, operator)
        )
    assert answered.status_code == 200
    assert answered.json()["scope"] == "contract"
    assert answered.json()["cases"] == [], "a contract-scope report runs no case"


@pytest.mark.filterwarnings(ANYIO)
def test_post_validate_of_an_undiscovered_kind_is_404_not_found(ctx, operator):
    with use_registry(Registry.with_builtins()), _client(ctx) as client:
        missing = client.post("/api/connectors/kinds/nope_ndjson/validate", headers=_headers(ctx, operator))
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"


@pytest.mark.filterwarnings(ANYIO)
def test_post_validate_does_not_disturb_a_concurrent_request(ctx, operator):
    """R49/B3: the guard is per-thread, so a validate never blinds another request's clock."""
    import threading

    observed: list[object] = []
    started, release = threading.Event(), threading.Event()

    def other() -> None:
        started.set()
        release.wait(30)
        from datetime import UTC, datetime

        # The clock the guard forbids inside `emit`. This thread is not guarded, so it answers.
        observed.append(datetime.now(UTC))
        observed.append(ctx.store._now())

    worker = threading.Thread(target=other)
    worker.start()
    started.wait(30)
    with use_registry(Registry.with_builtins()), _client(ctx) as client:
        answered = client.post(
            "/api/connectors/kinds/incidents_ndjson/validate", headers=_headers(ctx, operator)
        )
        release.set()
        worker.join(30)
    assert answered.status_code == 200 and answered.json()["passed"] is True
    assert len(observed) == 2 and all(value is not None for value in observed)


@pytest.mark.filterwarnings(ANYIO)
def test_a_connector_failure_is_a_coded_response_with_a_redacted_message(ctx, operator, monkeypatch):
    """m11: the four connector error vocabularies reach the caller as codes, never as text."""
    from hippo.connectors.credentials import CredentialError
    from hippo.connectors.http import ProviderForbiddenError

    row = _seed_instance(ctx)
    secret = "https://user:t0ken@incidents.example/incidents"
    failures = {
        "credential": CredentialError(f"no credential for {secret}"),
        "provider": ProviderForbiddenError(url=secret, status=403, attempts=1),
        "registration": base.RegistrationRequired(
            f"Connector at {secret} names unregistered types",
            kinds=("incident",),
            predicates=("AFFECTS",),
            skeleton="TypeExtension(...)",
        ),
        "refused": sync.ConnectorSyncRefused(f"instance {row.id} is not enabled: {secret}"),
    }
    # One client for the whole loop: leaving its context would close the store (see `_client`).
    with use_registry(Registry.with_builtins()), _client(ctx) as client:
        for name, error in failures.items():

            def raising(*_args, _error=error, **_kwargs):
                raise _error

            monkeypatch.setattr(routes, "_probe_classification", raising, raising=False)
            answered = client.post(f"/api/connectors/{row.id}/probe", headers=_headers(ctx, operator))
            assert answered.status_code >= 400, name
            body = answered.json()
            assert body["code"] and "t0ken" not in json.dumps(body), f"{name} leaked a credential"


@pytest.mark.filterwarnings(ANYIO)
def test_the_list_renders_a_load_error_and_the_frozen_spelling(ctx, operator, monkeypatch):
    """R64: `LoadResult.error` and `error="frozen"` are the two shapes the list renders."""
    broken = loader.LoadResult(
        registry=Registry.with_builtins(),
        entries=(
            loader.ConnectorEntry(
                name="incidents_ndjson",
                origin="in-repo",
                target="hippo.connectors.examples.incidents_ndjson:Connector",
                trusted=True,
                enabled=True,
                error="frozen",
            ),
        ),
        error="ReadError",
    )
    monkeypatch.setattr(loader, "load_connectors", lambda _ctx: broken)
    with use_registry(Registry.with_builtins()):
        payload = routes.connectors_payload(ctx)
    assert [entry["error"] for entry in payload] == ["frozen"]


# ------------------------------------------------------------------ the MCP tool


def test_the_mcp_tool_lists_connectors(ctx, operator):
    from hippo.access import Principal
    from hippo.mcp_server import connectors_tool

    _seed_instance(ctx)
    with use_registry(Registry.with_builtins()):
        answered = connectors_tool(ctx, principal=_principal(ctx, operator))
    assert set(answered) == {"connectors"}
    assert any(entry["name"] == "incidents_ndjson" for entry in answered["connectors"])
    assert isinstance(Principal.open(), Principal)


def test_the_mcp_tool_returns_a_stored_classification(ctx, operator):
    from hippo.mcp_server import connectors_tool

    row = _seed_instance(ctx)
    with use_registry(Registry.with_builtins()):
        answered = connectors_tool(ctx, connector_id=row.id, principal=_principal(ctx, operator))
    assert set(answered) == {"classification"}
    assert answered["classification"]["connector"] == "incidents_ndjson"


def test_the_mcp_tool_runs_validation(ctx, operator):
    from hippo.mcp_server import connectors_tool

    with use_registry(Registry.with_builtins()):
        answered = connectors_tool(ctx, validate="incidents_ndjson", principal=_principal(ctx, operator))
    assert set(answered) == {"validation"}
    assert answered["validation"]["scope"] == "contract"
    assert answered["validation"]["passed"] is True


def test_the_mcp_tool_refuses_without_manage_sources(ctx, reader):
    from mcp.server.mcpserver.exceptions import ToolError

    from hippo.mcp_server import connectors_tool

    with use_registry(Registry.with_builtins()), pytest.raises(ToolError) as refused:
        connectors_tool(ctx, principal=_principal(ctx, reader))
    assert "manage_sources" in str(refused.value)


def test_the_mcp_tool_refuses_two_modes_at_once(ctx, operator):
    from mcp.server.mcpserver.exceptions import ToolError

    from hippo.mcp_server import connectors_tool

    with use_registry(Registry.with_builtins()), pytest.raises(ToolError) as refused:
        connectors_tool(
            ctx, connector_id="c-1", validate="incidents_ndjson", principal=_principal(ctx, operator)
        )
    assert "not both" in str(refused.value)


def test_route_and_tool_payloads_are_the_same_builders(ctx, operator):
    from hippo import mcp_server
    from hippo.mcp_server import connectors_tool

    row = _seed_instance(ctx)
    assert mcp_server.connectors_payload is routes.connectors_payload
    assert mcp_server.classification_payload is routes.classification_payload
    assert mcp_server.validation_payload is routes.validation_payload
    with use_registry(Registry.with_builtins()):
        principal = _principal(ctx, operator)
        assert connectors_tool(ctx, principal=principal)["connectors"] == routes.connectors_payload(ctx)
        assert connectors_tool(ctx, connector_id=row.id, principal=principal)["classification"] == (
            routes.classification_payload(ctx, row.id)
        )


def test_the_tool_is_registered_and_never_probes(ctx):
    """The tool is read-only apart from validation: an MCP client triggering provider reads is Task 15's."""
    import inspect

    from hippo import mcp_server

    source = inspect.getsource(mcp_server.build_server)
    assert "hippo_connectors" in source
    assert ".probe(" not in inspect.getsource(mcp_server.connectors_tool)


def _principal(ctx, user_id: str):
    from hippo.access import Principal

    user = ctx.store.get_user(user_id)
    return Principal.for_user(user, ctx.store.get_role(user["role_id"]))


def test_the_connector_row_seeder_leaves_no_registration_behind(ctx, operator):
    """S4b gotcha 5: the scope must close, or the lifespan's own `register` fails."""
    _seed_instance(ctx)
    with pytest.raises(KeyError):
        base.current_registry().object_kind("incident")
    assert isinstance(k.Connector, type)
