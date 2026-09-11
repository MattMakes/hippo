"""Status inventory follows the caller's graph, independently of cached health."""

from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from hippo.access import Access
from hippo.status import system_status


def status_context():
    graph = NS(
        passages=[NS(source_id="public", title="Public")],
        entity_names={"entity": "visible"},
        facts=[NS(id="fact")],
        code_nodes=[NS(id="public-node", kind="symbol", lang="python", source_id="public")],
        code_out={0: [NS(kind="INVOKES", src=0), NS(kind="DEFINED_IN", src=0)]},
        node_ids=["public-node"],
        edges={(0, 1): NS(mention=True, synonym_score=0.0, code_kinds=[])},
        validate_authorization=Mock(),
    )
    public = {"id": "public", "meta": {"code": {"languages": ["python"], "unresolved_calls_total": 2}}}
    store = NS(
        ping=Mock(return_value=True),
        stats=Mock(return_value={"passages": 99, "sources": 9, "symbols": 99}),
        get_meta=Mock(return_value="hidden-profile"),
        list_sources=Mock(return_value=[public]),
        _knowledge_rows=Mock(return_value=[]),
        authorization_epoch=Mock(return_value=1),
        count_users=Mock(return_value=1),
        get_user=Mock(return_value={"id": "reader", "role_id": "individual", "disabled": False}),
        get_role=Mock(return_value={"id": "individual", "rank": 0}),
    )
    return NS(
        store=store,
        ollama=NS(
            is_up=Mock(return_value=True),
            installed_models=Mock(return_value=["model"]),
            required_models=Mock(return_value=["model"]),
            embed_model="model",
        ),
        config=NS(store_backend="fake", store_location="first", ollama_url="http://first"),
        jobs=NS(running_keys=Mock(return_value=["index:public"])),
        models=None,
        graph_for=Mock(return_value=graph),
    )


def test_private_corpus_cannot_change_reader_counts_cards_or_jobs():
    ctx = status_context()
    access = Access(user_id="reader")
    before = system_status(ctx, access=access)
    ctx.store.stats.return_value = {"passages": 999, "sources": 90, "symbols": 999}
    ctx.store.get_meta.return_value = "new-secret-model"
    ctx.store.list_sources.return_value.append(
        {"id": "managed", "meta": {"code": {"languages": ["secret-language"], "history_skipped": 100}}}
    )
    ctx.store._knowledge_rows.return_value = [NS(source_id="managed")]
    ctx.jobs.running_keys.return_value.extend(
        ["index:managed", "index:private", "run:secret", "generate:secret"]
    )
    after = system_status(ctx, access=access)
    assert before == after
    assert after["stats"]["passages"] == 1
    assert after["stats"]["sources"] == 1
    assert after["stats"]["code_edges"] == 1
    assert after["jobs"] == ["index:public"]
    assert after["embed_model_built"] is None
    assert after["embed_model_mismatch"] is False
    ctx.store.stats.assert_not_called()
    ctx.graph_for.assert_called_with(access)


def test_generation_only_source_is_hidden_until_authorized_evidence_is_projected():
    ctx = status_context()
    ctx.store.list_sources.return_value.append({"id": "staging", "meta": {"secret": "unpublished"}})
    ctx.store._knowledge_rows.side_effect = lambda kind: (
        [NS(source_id="staging")] if kind == "Generation" else []
    )
    ctx.jobs.running_keys.return_value.append("index:staging")
    value = system_status(ctx, access=Access(user_id="reader"))
    assert value["stats"]["sources"] == 1
    assert value["jobs"] == ["index:public"]


def test_managed_metadata_is_withheld_even_with_visible_managed_evidence():
    ctx = status_context()
    ctx.graph_for.return_value.passages.append(NS(source_id="managed", title="Managed"))
    ctx.graph_for.return_value.code_nodes.append(
        NS(id="managed-node", kind="data", lang="sql", source_id="managed")
    )
    ctx.store._knowledge_rows.return_value = [NS(source_id="managed")]
    ctx.store.list_sources.return_value.append(
        {"id": "managed", "meta": {"code": {"languages": ["private"], "unresolved_calls_total": 90}}}
    )
    ctx.jobs.running_keys.return_value.append("index:managed")
    value = system_status(ctx, access=Access(user_id="reader"))
    assert value["stats"]["sources"] == 2
    assert value["code"]["languages"] == ["python", "sql"]
    assert value["code"]["data_objects"] == 1
    assert value["code"]["unresolved_calls"] == 2
    assert value["jobs"] == ["index:public"]


def test_synonym_inventory_includes_authorized_cross_kind_links():
    ctx = status_context()
    ctx.graph_for.return_value.edges[(1, 2)] = NS(mention=False, synonym_score=0.0, code_kinds=["synonym"])
    value = system_status(ctx, access=Access(user_id="reader"))
    assert value["stats"]["synonym_edges"] == 1


def test_cache_is_per_context_and_never_caches_audience_inventory():
    first, second = status_context(), status_context()
    second.config.store_location = "second"
    second.ollama.is_up.return_value = False
    access = Access(user_id="reader")
    one = system_status(first, access=access)
    two = system_status(second, access=access)
    assert one["store_location"] == "first"
    assert two["store_location"] == "second"
    assert two["ollama"] is False
    first.graph_for.return_value.passages.append(NS(source_id="public"))
    assert system_status(first, access=access)["stats"]["passages"] == 2
    first.ollama.is_up.assert_called_once()
    first.graph_for.assert_called_with(access)


def test_cache_cannot_be_poisoned_by_mutating_a_previous_response():
    ctx = status_context()
    access = Access(user_id="reader")
    system_status(ctx, access=access)["models"]["model"] = False
    assert system_status(ctx, access=access)["models"] == {"model": True}


def test_internal_diagnostics_still_include_full_inventory():
    ctx = status_context()
    value = system_status(ctx)
    assert value["stats"]["passages"] == 99
    assert value["embed_model_built"] == "hidden-profile"
    ctx.graph_for.assert_not_called()


def test_preview_without_identity_has_no_inventory():
    ctx = status_context()
    value = system_status(ctx, access=Access(audience_kind="preview"))
    assert all(count == 0 for count in value["stats"].values())
    assert value["code"]["languages"] == []
    assert value["jobs"] == []
    ctx.graph_for.assert_not_called()


def test_aggregate_revalidates_authorization_after_reading_inventory():
    from hippo.knowledge.access import AuthorizationChanged

    ctx = status_context()
    ctx.store.authorization_epoch.side_effect = [1, 2]
    with pytest.raises(AuthorizationChanged):
        system_status(ctx, access=Access(user_id="reader"))


def test_cached_health_does_not_bypass_expiring_graph_proof():
    from hippo.knowledge.access import AuthorizationChanged

    ctx = status_context()
    access = Access(user_id="reader")
    system_status(ctx, access=access)
    ctx.graph_for.return_value.validate_authorization.side_effect = AuthorizationChanged("expired")
    with pytest.raises(AuthorizationChanged):
        system_status(ctx, access=access)


def test_status_route_and_page_header_pass_the_request_audience(monkeypatch):
    from hippo.web import render
    from hippo.web.routes import api

    ctx = status_context()
    access = Access(user_id="reader")
    request = NS(app=NS(state=NS(ctx=ctx)), state=NS(principal=NS(access=access)))
    assert api.status(request)["stats"]["passages"] == 1
    monkeypatch.setattr(
        render.templates, "TemplateResponse", lambda request, template, context, **kw: context
    )
    page = render.render(request, "unused.html")
    assert page["status"]["stats"]["passages"] == 1
    ctx.graph_for.assert_called_with(access)
    request.state.principal = None
    assert render.render(request, "unused.html")["status"]["stats"]["passages"] == 0


def test_render_revalidates_after_materialization_and_keeps_callback_out_of_context(monkeypatch):
    from hippo.knowledge.access import AuthorizationChanged
    from hippo.web import render

    ctx = status_context()
    request = NS(app=NS(state=NS(ctx=ctx)), state=NS(principal=NS(access=Access(user_id="reader"))))
    revoked = False

    def validate():
        if revoked:
            raise AuthorizationChanged("revoked during rendering")

    def materialize(request, template, context, **kwargs):
        nonlocal revoked
        assert "authorization_check" not in context
        revoked = True
        return context

    monkeypatch.setattr(render.templates, "TemplateResponse", materialize)
    with pytest.raises(AuthorizationChanged):
        render.render(request, "unused.html", authorization_check=validate)


def test_mcp_identity_never_exposes_total_hidden_source_inventory():
    from hippo.access import Principal
    from hippo.mcp_server import whoami_tool

    ctx = status_context()
    ctx.store.list_roles = Mock(return_value=[])
    ctx.store._knowledge_rows.return_value = [NS(source_id="managed")]
    ctx.store.list_sources.return_value.append({"id": "managed"})
    principal = Principal.for_user({"id": "reader"}, {"id": "individual", "rank": 0})
    value = whoami_tool(ctx, principal)
    assert value["sources_visible"] == value["sources_total"] == 1
    ctx.store.list_sources.assert_called_with(principal.access)


def test_private_source_is_invisible_to_real_web_status_and_header(ctx, sample_text, monkeypatch):
    from fastapi.testclient import TestClient

    from hippo.access import Principal
    from hippo.hipporag.indexer import Chunk, index_source
    from hippo.mcp_server import whoami_tool
    from hippo.web.app import create_app

    ctx.store.ping()
    uid = ctx.store.create_user("status-reader", "secret1", "individual")
    user = ctx.store.get_user(uid)
    principal = Principal.for_user(user, ctx.store.get_role("individual"))
    public = ctx.store.create_source("text", "Public notes")
    index_source(ctx.store, ctx.ollama, public, [Chunk(0, "Public", sample_text)])
    keys = ["index:" + public]
    monkeypatch.setattr(ctx.jobs, "running_keys", lambda: list(keys))
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        client.headers["Authorization"] = "Bearer " + user["token"]
        before = client.get("/api/status").json()
        header_before = client.get("/partials/status").text
        ask_before = client.get("/ask").text
        library_before = client.get("/").text
        who_before = whoami_tool(ctx, principal)
        private = ctx.store.create_source(
            "text",
            "Confidential",
            access_role_id="arch-admin",
            meta={"code": {"languages": ["secret-language"], "unresolved_calls_total": 123}},
        )
        index_source(ctx.store, ctx.ollama, private, [Chunk(0, "Private", "Secret implementation details.")])
        ctx.invalidate_graph()
        keys.extend(["index:" + private, "run:secret-evaluation", "generate:secret-set"])
        after = client.get("/api/status").json()
        assert before == after
        assert header_before == client.get("/partials/status").text
        assert ask_before == client.get("/ask").text
        assert library_before == client.get("/").text
        assert who_before == whoami_tool(ctx, principal)
        assert after["stats"]["sources"] == 1
        assert after["stats"]["passages"] == 1
        assert after["jobs"] == ["index:" + public]


def test_role_downgrade_clamps_status_sources_metadata_and_jobs(ctx, monkeypatch):
    from hippo.access import Principal

    ctx.store.ping()
    uid = ctx.store.create_user("downgraded-reader", "secret1", "arch-admin")
    stale = Principal.for_user(ctx.store.get_user(uid), ctx.store.get_role("arch-admin"))
    public = ctx.store.create_source("text", "Public")
    private = ctx.store.create_source(
        "text",
        "Secret",
        access_role_id="arch-admin",
        meta={"code": {"languages": ["secret-language"], "history_skipped": 100}},
    )
    monkeypatch.setattr(ctx.jobs, "running_keys", lambda: ["index:" + public, "index:" + private])
    assert system_status(ctx, access=stale.access)["stats"]["sources"] == 2
    ctx.store.update_user(uid, role_id="individual")
    value = system_status(ctx, access=stale.access)
    assert value["stats"]["sources"] == 1
    assert value["code"]["languages"] == []
    assert value["code"]["history_skipped"] == 0
    assert value["jobs"] == ["index:" + public]


def test_user_and_role_source_counts_are_intersected_with_the_callers_inventory(ctx):
    from fastapi.testclient import TestClient

    from hippo.web.app import create_app

    ctx.store.ping()
    uid = ctx.store.create_user("local-manager", "secret1", "local-admin")
    owner = ctx.store.create_user("senior-manager", "secret1", "arch-admin")
    ctx.store.create_source("text", "Public", owner_id=uid)
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        client.headers["Authorization"] = "Bearer " + ctx.store.get_user(uid)["token"]
        before = {path: client.get(path).text for path in ("/users", "/api/users", "/api/roles")}
        ctx.store.create_source("text", "Secret", owner_id=owner, access_role_id="arch-admin")
        assert before == {path: client.get(path).text for path in before}


@pytest.mark.parametrize("role", ["individual", "local-admin"])
def test_managed_source_surfaces_render_only_projected_evidence(ctx, monkeypatch, role):
    from fastapi.testclient import TestClient

    from hippo.access import Principal
    from hippo.hipporag.graph_index import Passage
    from hippo.mcp_server import sources_tool
    from hippo.web.app import create_app
    from tests.unit.test_evidence_projection import graph

    ctx.store.ping()
    uid = ctx.store.create_user("managed-surface-reader", "secret1", role)
    user = ctx.store.get_user(uid)
    principal = Principal.for_user(user, ctx.store.get_role(role))
    sid = ctx.store.create_source("repo", "SECRET container", meta={"code": {"languages": ["SECRET"]}})
    ctx.store.update_source(sid, status="failed", error="SECRET error", progress_total=100, progress_done=99)
    projected = graph([], [Passage("allowed-span", "Allowed title", "Allowed body", sid, "", 0)])
    monkeypatch.setattr(ctx, "graph_for", lambda access, **kwargs: projected)
    original = ctx.store._knowledge_rows
    monkeypatch.setattr(
        ctx.store,
        "_knowledge_rows",
        lambda kind: [NS(source_id=sid)] if kind == "Artifact" else original(kind),
    )
    monkeypatch.setattr(ctx.jobs, "running_keys", lambda: ["index:" + sid])
    monkeypatch.setattr(ctx.jobs, "is_running", lambda key: True)
    monkeypatch.setattr(
        ctx.store, "list_question_sets", Mock(side_effect=AssertionError("raw eval inventory"))
    )
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        client.headers["Authorization"] = "Bearer " + user["token"]
        for path in (
            "/",
            "/partials/sources",
            "/api/sources",
            f"/api/sources/{sid}",
            f"/sources/{sid}",
            f"/partials/sources/{sid}/status",
        ):
            response = client.get(path)
            assert response.status_code in (200, 286)
            assert "SECRET" not in response.text, path
        detail = client.get(f"/sources/{sid}").text
        assert "Allowed body" in detail
        row = client.get(f"/api/sources/{sid}").json()
        assert row["passages"] == 1 and row["progress_total"] == 0 and row["status"] == "ready"
        assert "SECRET" not in repr(sources_tool(ctx, principal))
        monkeypatch.setattr(ctx, "graph_for", lambda access, **kwargs: graph([], []))
        assert client.get("/api/sources").json() == []
        assert client.get(f"/api/sources/{sid}").status_code == 404


@pytest.mark.parametrize("path", ["/", "/partials/sources", "/sources/{id}", "/partials/sources/{id}/status"])
def test_source_html_revalidates_its_original_inventory_after_render(ctx, monkeypatch, path):
    from fastapi.testclient import TestClient

    from hippo.web.app import create_app
    from hippo.web.routes import sources

    ctx.store.ping()
    uid = ctx.store.create_user("render-reader", "secret1", "individual")
    sid = ctx.store.create_source("text", "Withdrawn source")
    original = sources.render

    def revoke_then_render(*args, **kwargs):
        ctx.store.set_source_access(sid, "arch-admin")
        return original(*args, **kwargs)

    monkeypatch.setattr(sources, "render", revoke_then_render)
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        client.headers["Authorization"] = "Bearer " + ctx.store.get_user(uid)["token"]
        response = client.get(path.format(id=sid))
        assert response.status_code == 409
        assert "Withdrawn source" not in response.text


def test_account_and_identity_count_only_owned_sources_with_visible_evidence(ctx, monkeypatch):
    from fastapi.testclient import TestClient

    from hippo.web.app import create_app
    from tests.unit.test_evidence_projection import graph

    ctx.store.ping()
    uid = ctx.store.create_user("account-reader", "secret1", "individual")
    ctx.store.create_source("text", "Visible", owner_id=uid)
    hidden = ctx.store.create_source("text", "Managed hidden", owner_id=uid)
    original = ctx.store._knowledge_rows
    monkeypatch.setattr(
        ctx.store,
        "_knowledge_rows",
        lambda kind: [NS(source_id=hidden)] if kind == "Artifact" else original(kind),
    )
    monkeypatch.setattr(ctx, "graph_for", lambda access, **kwargs: graph([], []))
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        client.headers["Authorization"] = "Bearer " + ctx.store.get_user(uid)["token"]
        assert client.get("/api/me").json()["user"]["sources"] == 1
        assert "1 of your own" in client.get("/account").text


def test_reindex_all_acknowledges_without_exposing_the_global_start_count(ctx, monkeypatch):
    from fastapi.testclient import TestClient

    from hippo.ingest import pipeline
    from hippo.web.app import create_app

    ctx.store.ping()
    uid = ctx.store.create_user("index-manager", "secret1", "local-admin")
    ctx.store.update_role("local-admin", capabilities=["edit_graph"])
    operation = Mock(return_value=79)
    monkeypatch.setattr(pipeline, "reindex_all", operation)
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        client.headers["Authorization"] = "Bearer " + ctx.store.get_user(uid)["token"]
        response = client.post("/api/sources/reindex-all")
        assert response.status_code == 200
        assert response.json() == {"accepted": True}
        operation.assert_called_once_with(ctx)


def test_source_detail_lists_only_the_callers_owned_evaluation_sets(ctx):
    from fastapi.testclient import TestClient

    from hippo.access import Principal
    from hippo.knowledge.eval_access import EvalAccess
    from hippo.web.app import create_app

    ctx.store.ping()
    owner = ctx.store.create_user("eval-owner", "secret1", "local-admin")
    reader = ctx.store.create_user("source-reader", "secret1", "local-admin")
    sid = ctx.store.create_source("text", "Shared source")
    access = Principal.for_user(ctx.store.get_user(owner), ctx.store.get_role("local-admin")).access
    EvalAccess(ctx, access).create_question_set("PRIVATE evaluation name", sid)
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        client.headers["Authorization"] = "Bearer " + ctx.store.get_user(reader)["token"]
        response = client.get(f"/sources/{sid}")
        assert response.status_code == 200
        assert "PRIVATE evaluation name" not in response.text
