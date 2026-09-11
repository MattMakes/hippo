"""Graph and code transports release only current authorized evidence."""

import pytest
from fastapi.testclient import TestClient

from hippo import ask, mcp_server
from hippo.access import Principal
from hippo.hipporag.indexer import Chunk, index_source
from hippo.knowledge.access import AuthorizationChanged
from hippo.web.app import create_app
from hippo.web.routes import code, graph
from tests.unit.test_store_knowledge import foundation


@pytest.fixture
def public_source(ctx):
    ctx.store.ensure_roles()
    source = ctx.store.create_source("text", "Public guide")
    index_source(
        ctx.store,
        ctx.ollama,
        source,
        [Chunk(0, "Orion", "The Orion arm was designed by Mira Chen at Aster Labs.")],
    )
    return source


@pytest.fixture
def client(ctx):
    with TestClient(create_app(ctx), base_url="http://localhost", raise_server_exceptions=False) as client:
        yield client


@pytest.mark.parametrize("url", ["/api/entities?q=orion", "/api/graph/full", "/graph"])
def test_unpublished_managed_native_rows_never_escape_graph_surfaces(ctx, client, url):
    _, source, *_ = foundation(ctx.store)
    index_source(
        ctx.store,
        ctx.ollama,
        source,
        [Chunk(0, "Hidden native title", "The Orion arm was designed by Mira Chen at Aster Labs.")],
    )
    response = client.get(url)
    assert response.status_code == 200, response.text
    if url.startswith("/api/entities"):
        assert response.json() == []
    else:
        assert source not in response.text
        assert "schema.sql" not in response.text
        assert "Hidden native title" not in response.text


@pytest.mark.parametrize("surface", ["full", "node", "neighborhood"])
def test_graph_revocation_after_label_read_discards_payload(ctx, client, public_source, monkeypatch, surface):
    index = ctx.graph_for(Principal.open().access)
    node_id = index.passages[0].id
    if surface == "neighborhood":
        target, name = type(index), "name_of"
    else:
        target, name = graph, "label_at"
    original = getattr(target, name)
    changed = False

    def label(*args, **kwargs):
        nonlocal changed
        result = original(*args, **kwargs)
        if not changed:
            changed = True
            ctx.store.set_source_access(public_source, "arch-admin")
        return result

    monkeypatch.setattr(target, name, label)
    url = {
        "full": "/api/graph/full",
        "node": "/api/graph/node/" + node_id,
        "neighborhood": "/api/graph/neighborhood?node_id=" + node_id,
    }[surface]
    response = client.get(url)
    assert changed
    assert response.status_code == 409
    assert response.json() == {"error": "Permissions changed; repeat the query"}


def test_graph_page_revocation_during_template_render_discards_html(ctx, client, public_source, monkeypatch):
    from hippo.web.render import templates

    original = templates.TemplateResponse

    def render(*args, **kwargs):
        response = original(*args, **kwargs)
        ctx.store.set_source_access(public_source, "arch-admin")
        return response

    monkeypatch.setattr(templates, "TemplateResponse", render)
    assert client.get("/graph").status_code == 409


@pytest.mark.parametrize("surface", ["ask", "search", "light-up"])
def test_query_transport_rechecks_after_building_output(ctx, client, public_source, monkeypatch, surface):
    target, name = (graph, "explain") if surface == "light-up" else (ask, "code_fields")
    original = getattr(target, name)

    def build(*args, **kwargs):
        result = original(*args, **kwargs)
        ctx.store.set_source_access(public_source, "arch-admin")
        return result

    monkeypatch.setattr(target, name, build)
    url = "/api/graph/light-up" if surface == "light-up" else "/api/" + surface
    response = client.post(url, json={"question": "Who designed Orion?"})
    assert response.status_code == 409
    assert "Mira" not in response.text


@pytest.mark.parametrize("surface", ["ask", "search"])
def test_mcp_query_rechecks_after_building_output(ctx, public_source, monkeypatch, surface):
    original = mcp_server.code_fields

    def build(*args, **kwargs):
        result = original(*args, **kwargs)
        ctx.store.set_source_access(public_source, "arch-admin")
        return result

    monkeypatch.setattr(mcp_server, "code_fields", build)
    with pytest.raises(AuthorizationChanged):
        getattr(mcp_server, surface + "_tool")(ctx, "Who designed Orion?", principal=Principal.open())


@pytest.mark.parametrize("error", [False, True])
def test_code_symbol_response_and_ambiguity_cannot_outlive_permissions(
    ctx, client, public_source, monkeypatch, error
):
    from hippo.hipporag.paths import AmbiguousSymbol

    def rows(*args, **kwargs):
        ctx.store.set_source_access(public_source, "arch-admin")
        if error:
            raise AmbiguousSymbol("private", ["PRIVATE CANDIDATE"])
        return [{"name": "PRIVATE CANDIDATE"}]

    monkeypatch.setattr(code, "symbol_rows", rows)
    response = client.get("/api/code/symbols?q=private")
    assert response.status_code == 409
    assert "PRIVATE CANDIDATE" not in response.text


@pytest.mark.parametrize("transport", ["http", "mcp"])
@pytest.mark.parametrize("operation", ["path", "blast", "exception", "history"])
def test_code_path_surfaces_validate_error_output(
    ctx, client, public_source, monkeypatch, transport, operation
):
    from hippo.hipporag.paths import UnknownSymbol

    builder = {
        "path": "path_payload",
        "blast": "blast_payload",
        "exception": "exception_payload",
        "history": "history_payload",
    }[operation]

    def revoked(*args, **kwargs):
        ctx.store.set_source_access(public_source, "arch-admin")
        raise UnknownSymbol("PRIVATE SYMBOL")

    monkeypatch.setattr(code if transport == "http" else mcp_server, builder, revoked)
    if transport == "http":
        url = {
            "path": "/path?a=x&b=y",
            "blast": "/blast-radius?symbol=x",
            "exception": "/exception-path?symbol=x&exception=y",
            "history": "/history?symbol=x",
        }[operation]
        response = client.get("/api/code" + url)
        assert response.status_code == 409
        assert "PRIVATE SYMBOL" not in response.text
    else:
        name, args = {
            "path": ("explain_path_tool", ("x", "y")),
            "blast": ("blast_radius_tool", ("x",)),
            "exception": ("exception_path_tool", ("x", "y")),
            "history": ("history_tool", ("x",)),
        }[operation]
        with pytest.raises(AuthorizationChanged):
            getattr(mcp_server, name)(ctx, *args, principal=Principal.open())


def test_staged_generation_without_artifacts_is_not_a_source_dropdown_entry(ctx, client):
    from hippo.knowledge import model as k
    from tests.unit.test_store_knowledge import NOW

    source = ctx.store.create_source("text", "PRIVATE STAGING")
    ctx.store.put_knowledge(
        k.Generation(
            source_id=source,
            status="staging",
            manifest_hash="staged",
            parser_version="p1",
            linker_version="l1",
            embedding_profile=ctx.ollama.embed_model,
            created_at=NOW,
        )
    )
    for url in ("/graph", "/api/graph/full"):
        response = client.get(url)
        assert response.status_code == 200
        assert source not in response.text
        assert "PRIVATE STAGING" not in response.text


def test_unpublished_managed_code_never_appears_in_symbol_lookup(code_index, client):
    from hippo.knowledge import model as k
    from tests.unit.test_store_knowledge import NOW

    ctx, source = code_index
    policy = k.AccessPolicy(
        workspace_id=ctx.store.get_source(source)["workspace_id"],
        origin="local_curated",
        scope_key="source:" + source,
        mode="workspace",
        verified_at=NOW,
    )
    ctx.store.put_knowledge(policy)
    ctx.store.put_knowledge(
        k.Artifact(
            workspace_id=policy.workspace_id,
            source_id=source,
            kind="file",
            external_id="private.py",
            canonical_uri="private.py",
            policy_id=policy.id,
        )
    )
    response = client.get("/api/code/symbols?q=place")
    assert response.status_code == 200
    assert response.json() == []


def test_entity_lookup_revalidates_after_reading_matches(ctx, client, public_source, monkeypatch):
    index = ctx.graph_for(Principal.open().access)
    changed = False

    class Names(dict):
        def items(self):
            nonlocal changed
            rows = list(super().items())
            if not changed:
                changed = True
                ctx.store.set_source_access(public_source, "arch-admin")
            return rows

    index.entity_names = Names(index.entity_names)
    monkeypatch.setattr(ctx, "graph_for", lambda access: index)
    response = client.get("/api/entities?q=orion")
    assert changed
    assert response.status_code == 409


@pytest.mark.parametrize("surface", ["ask", "search", "light-up"])
def test_model_errors_cannot_skip_transport_revocation_checks(
    ctx, client, public_source, monkeypatch, surface
):
    from hippo.ollama import OllamaError

    def failed(*args, **kwargs):
        ctx.store.set_source_access(public_source, "arch-admin")
        raise OllamaError("PRIVATE PROVIDER ERROR")

    method = {"ask": "ask", "search": "search", "light-up": "_search"}[surface]
    monkeypatch.setattr(ask, method, failed)
    url = "/api/graph/light-up" if surface == "light-up" else "/api/" + surface
    response = client.post(url, json={"question": "Who designed Orion?"})
    assert response.status_code == 409
    assert "PRIVATE PROVIDER ERROR" not in response.text


@pytest.mark.parametrize("surface", ["ask", "search"])
def test_mcp_model_errors_cannot_skip_transport_revocation_checks(ctx, public_source, monkeypatch, surface):
    from hippo.ollama import OllamaError

    def failed(*args, **kwargs):
        ctx.store.set_source_access(public_source, "arch-admin")
        raise OllamaError("PRIVATE PROVIDER ERROR")

    monkeypatch.setattr(mcp_server, surface, failed)
    with pytest.raises(AuthorizationChanged):
        getattr(mcp_server, surface + "_tool")(ctx, "Who designed Orion?", principal=Principal.open())


@pytest.mark.parametrize("when", ["before_selection", "after_selection"])
def test_role_preview_cannot_outlive_original_reader_permissions(
    ctx, client, public_source, monkeypatch, when
):
    user = ctx.store.create_user("preview-admin", "secret1", "arch-admin")
    client.headers["Authorization"] = "Bearer " + ctx.store.get_user(user)["token"]
    ctx.store.set_source_access(public_source, "arch-admin")
    target = "principal_of" if when == "before_selection" else "viewer"
    original = getattr(graph, target)

    def downgrade(*args, **kwargs):
        result = original(*args, **kwargs)
        ctx.store.update_user(user, role_id="individual")
        return result

    monkeypatch.setattr(graph, target, downgrade)
    response = client.get("/api/graph/full?as_role=arch-admin")
    assert response.status_code in {403, 409}
    assert public_source not in response.text


def test_revoked_preview_never_dispatches_its_graph_to_a_model(ctx, client, public_source, monkeypatch):
    user = ctx.store.create_user("preview-model-admin", "secret1", "arch-admin")
    client.headers["Authorization"] = "Bearer " + ctx.store.get_user(user)["token"]
    ctx.store.set_source_access(public_source, "arch-admin")
    original = graph.viewer
    dispatched = []

    def downgrade(*args, **kwargs):
        result = original(*args, **kwargs)
        ctx.store.update_user(user, role_id="individual")
        return result

    def model(*args, **kwargs):
        dispatched.append(args)
        raise AssertionError("Revoked preview reached the model")

    monkeypatch.setattr(graph, "viewer", downgrade)
    for method in ("embed_one", "chat_json", "chat_text"):
        monkeypatch.setattr(ctx.ollama, method, model)
    response = client.post(
        "/api/graph/light-up", json={"question": "Who designed Orion?", "as_role": "arch-admin"}
    )
    assert response.status_code == 409
    assert dispatched == []


def test_graph_preview_menu_uses_the_live_actor_after_a_pre_entry_downgrade(ctx, client, monkeypatch):
    user = ctx.store.create_user("menu-admin", "secret1", "arch-admin")
    client.headers["Authorization"] = "Bearer " + ctx.store.get_user(user)["token"]
    original = graph.viewer

    def downgrade_before_viewer(*args, **kwargs):
        ctx.store.update_user(user, role_id="individual")
        return original(*args, **kwargs)

    captured = {}
    original_render = graph.render

    def render(request, template, **kwargs):
        captured.update(kwargs)
        return original_render(request, template, **kwargs)

    monkeypatch.setattr(graph, "viewer", downgrade_before_viewer)
    monkeypatch.setattr(graph, "render", render)
    response = client.get("/graph")
    assert response.status_code == 200
    assert captured["principal"].role_id == "individual"
    assert captured["previewable"] == []


def test_light_up_holds_one_graph_through_source_inventory_and_releases(
    ctx, client, public_source, monkeypatch
):
    acquired, released = [], []
    original = ctx.graph_for

    def graph_for(*args, **kwargs):
        result = original(*args, **kwargs)
        acquired.append(result)
        result.close_snapshot = lambda: released.append(result)
        return result

    monkeypatch.setattr(ctx, "graph_for", graph_for)
    response = client.post(
        "/api/graph/light-up", json={"question": "Who designed Orion?", "settings": {"qa_top_k": 1}}
    )
    assert response.status_code == 200, response.text
    assert len(acquired) == 1
    assert released == acquired
    assert response.json()["settings"]["qa_top_k"] == 1
