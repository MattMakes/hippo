"""
Users at the door: open mode, the first user, sign-in, capability gating, scoped pages and
API calls, MCP tokens, the Users & roles page, and the Graph page's endpoints.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError

from hippo import mcp_server
from hippo.hipporag.indexer import Chunk, index_source
from hippo.web import auth
from hippo.web.app import create_app

MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def sections(sample_text: str) -> list[tuple[str, str]]:
    out = []
    for section in sample_text.split("## ")[1:]:
        lines = section.splitlines()
        out.append((lines[0].strip(), "\n".join(lines[1:]).strip()))
    return out


@pytest.fixture
def app_ctx(ctx, sample_text):
    """Two sources: the first half of the sample open to everyone, the second half for local admins."""
    ctx.store.ping()
    parts = sections(sample_text)
    half = len(parts) // 2
    open_id = ctx.store.create_source("text", "Open half")
    restricted_id = ctx.store.create_source("text", "Restricted half", access_role_id="local-admin")
    index_source(ctx.store, ctx.ollama, open_id, [Chunk(i, t, x) for i, (t, x) in enumerate(parts[:half])])
    index_source(
        ctx.store, ctx.ollama, restricted_id, [Chunk(i, t, x) for i, (t, x) in enumerate(parts[half:])]
    )
    ctx.open_id, ctx.restricted_id = open_id, restricted_id  # type: ignore[attr-defined]
    return ctx


@pytest.fixture
def client(app_ctx):
    with TestClient(create_app(app_ctx), base_url="http://localhost") as client:
        yield client


def sign_in(client: TestClient, username: str, password: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/login", data={"username": username, "password": password}, follow_redirects=False
    )
    assert response.status_code == 303, response.text
    assert auth.SESSION_COOKIE in response.cookies


def make_users(ctx) -> dict[str, str]:
    """An arch admin, a local admin and an individual; returns username -> token."""
    tokens = {}
    for name, role in (("root", "arch-admin"), ("lena", "local-admin"), ("ivy", "individual")):
        uid = ctx.store.create_user(name, "secret1", role)
        tokens[name] = ctx.store.get_user(uid)["token"]
    return tokens


# ------------------------------------------------------------- open mode


def test_open_mode_shows_everything_and_says_so(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "open mode" in page.text and "Open half" in page.text and "Restricted half" in page.text
    assert client.get("/login").status_code == 200 and "nothing to sign in to" in client.get("/login").text
    me = client.get("/api/me").json()
    assert me["open_mode"] and me["user"] is None and "manage_users" in me["capabilities"]


def test_first_user_must_take_the_top_role_and_signs_that_browser_in(client, app_ctx):
    refused = client.post(
        "/api/users", json={"username": "bob", "password": "secret1", "role_id": "individual"}
    )
    assert refused.status_code == 400 and "Arch admin" in refused.json()["detail"]
    created = client.post("/api/users", json={"username": "root", "password": "secret1"})
    assert created.status_code == 200
    body = created.json()
    assert (
        body["signed_in"] and body["user"]["role_id"] == "arch-admin" and body["token"].startswith("hippo_")
    )
    assert "password_hash" not in body["user"]
    assert auth.SESSION_COOKIE in created.cookies
    # Open mode is over: this browser is root, a fresh one is turned away.
    assert client.get("/api/me").json()["user"]["username"] == "root"
    client.cookies.clear()
    assert client.get("/api/me").status_code == 401


# ---------------------------------------------------------------- the gate


def test_strangers_are_redirected_401ed_or_htmx_redirected(client, app_ctx):
    make_users(app_ctx)
    page = client.get("/ask", follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"].startswith("/login?next=%2Fask")
    api = client.get("/api/sources")
    assert api.status_code == 401 and api.headers["www-authenticate"] == "Bearer"
    partial = client.get("/partials/status", headers={"HX-Request": "true"})
    assert partial.status_code == 401 and partial.headers["hx-redirect"] == "/login"
    mcp = client.post("/mcp", headers=MCP_HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert mcp.status_code == 401
    assert client.get("/static/app.css").status_code == 200, "the sign-in page's stylesheet stays public"


def test_sign_in_sign_out_and_wrong_password(client, app_ctx):
    make_users(app_ctx)
    bad = client.post("/login", data={"username": "lena", "password": "nope"})
    assert bad.status_code == 401 and "do not match" in bad.text
    sign_in(client, "lena", "secret1")
    page = client.get("/")
    assert page.status_code == 200 and "lena" in page.text and "Local admin" in page.text
    out = client.post("/logout", follow_redirects=False)
    assert out.status_code == 303
    assert client.get("/api/me").status_code == 401


def test_bearer_tokens_work_for_the_api_and_a_disabled_user_is_refused(client, app_ctx):
    tokens = make_users(app_ctx)
    headers = {"Authorization": f"Bearer {tokens['ivy']}"}
    me = client.get("/api/me", headers=headers).json()
    assert me["user"]["username"] == "ivy" and me["role"]["id"] == "individual"
    assert client.get("/api/me", headers={"Authorization": "Bearer hippo_nope"}).status_code == 401
    ivy = app_ctx.store.get_user_by_username("ivy")
    app_ctx.store.update_user(ivy["id"], disabled=True)
    assert client.get("/api/me", headers=headers).status_code == 401


def test_session_cookies_are_signed_and_expire():
    secret = b"s3cret"
    cookie = auth.sign_session(secret, "u1", now=1000.0)
    assert auth.read_session(secret, cookie, now=1500.0) == "u1"
    assert auth.read_session(b"other", cookie, now=1500.0) is None
    assert auth.read_session(secret, cookie + "x", now=1500.0) is None
    assert auth.read_session(secret, cookie, now=1000.0 + auth.SESSION_SECONDS + 1) is None
    assert auth.read_session(secret, "garbage", now=1500.0) is None


# --------------------------------------------------------- scoped pages


def test_an_individual_sees_only_open_sources_everywhere(client, app_ctx):
    tokens = make_users(app_ctx)
    headers = {"Authorization": f"Bearer {tokens['ivy']}"}
    listed = client.get("/api/sources", headers=headers).json()
    assert [s["name"] for s in listed] == ["Open half"]
    assert client.get(f"/api/sources/{app_ctx.restricted_id}", headers=headers).status_code == 404
    sign_in(client, "ivy", "secret1")
    library = client.get("/")
    assert "Open half" in library.text and "Restricted half" not in library.text
    assert "1 visible to you" in library.text and "Individual" in library.text
    assert "1 of 2" not in library.text
    assert client.get(f"/sources/{app_ctx.restricted_id}").status_code == 404
    assert client.get(f"/sources/{app_ctx.open_id}").status_code == 200
    ask = client.get("/ask")
    assert "Searching <b>1</b> of 1 sources" in ask.text


def test_search_and_ask_over_the_api_stay_inside_the_callers_slice(client, app_ctx):
    tokens = make_users(app_ctx)
    hidden = set(app_ctx.store.passage_ids_for_source(app_ctx.restricted_id))
    question = {"question": "Who designed the Orion arm?"}
    for name, expect_hidden in (("root", True), ("lena", True), ("ivy", False)):
        headers = {"Authorization": f"Bearer {tokens[name]}"}
        trace = client.post("/api/search", json=question, headers=headers).json()["trace"]
        reached = hidden & {p["passage_id"] for p in trace["passages"]}
        assert bool(reached) is expect_hidden, name
        answer = client.post("/api/ask", json=question, headers=headers).json()
        assert bool(hidden & set(answer["passage_ids"])) is expect_hidden, name


def test_entity_search_and_neighbourhood_are_scoped(client, app_ctx):
    tokens = make_users(app_ctx)
    everything = {
        e["id"]
        for e in client.get("/api/entities?q=a", headers={"Authorization": f"Bearer {tokens['root']}"}).json()
    }
    for_ivy = {
        e["id"]
        for e in client.get("/api/entities?q=a", headers={"Authorization": f"Bearer {tokens['ivy']}"}).json()
    }
    assert for_ivy < everything
    hidden_passage = app_ctx.store.passage_ids_for_source(app_ctx.restricted_id)[0]
    assert (
        client.get(
            f"/api/graph/neighborhood?node_id={hidden_passage}",
            headers={"Authorization": f"Bearer {tokens['ivy']}"},
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/graph/neighborhood?node_id={hidden_passage}",
            headers={"Authorization": f"Bearer {tokens['lena']}"},
        ).status_code
        == 200
    )


def test_adhoc_analyses_belong_to_the_person_who_asked(client, app_ctx):
    make_users(app_ctx)
    sign_in(client, "lena", "secret1")
    response = client.post("/ask", data={"question": "Where is Acme Robotics headquartered?"})
    key = response.text.split('href="/analyze?key=')[1].split("&")[0]
    assert client.get(f"/analyze?key={key}&question=x").status_code == 200
    sign_in(client, "ivy", "secret1")
    assert client.get(f"/analyze?key={key}&question=x").status_code == 404


# ------------------------------------------------------------ capabilities


def test_capabilities_gate_evals_changesets_settings_and_adding(client, app_ctx):
    tokens = make_users(app_ctx)
    ivy = {"Authorization": f"Bearer {tokens['ivy']}"}
    lena = {"Authorization": f"Bearer {tokens['lena']}"}
    assert client.get("/api/evals/sets", headers=ivy).status_code == 403
    assert client.get("/api/evals/sets", headers=lena).status_code == 200
    assert client.get("/api/changesets", headers=lena).status_code == 403, (
        "local admins cannot edit the graph"
    )
    assert client.put("/api/settings", json={"damping": 0.7}, headers=lena).status_code == 403
    assert client.get("/api/settings", headers=ivy).status_code == 200, "reading settings is fine"
    sign_in(client, "ivy", "secret1")
    forbidden = client.get("/evals", headers={"Accept": "text/html"})
    assert forbidden.status_code == 403 and "Not allowed" in forbidden.text and "run_evals" in forbidden.text
    # An individual may add sources (their tier by default) but not restrict them above their rank.
    added = client.post(
        "/api/sources/text", json={"name": "Ivy's notes", "text": "Ivy likes graphs."}, headers=ivy
    )
    assert added.status_code == 200
    source = app_ctx.store.get_source(added.json()["source_id"])
    assert source["access_role_id"] == "individual" and source["owner_name"] == "ivy"
    above = client.post(
        "/api/sources/text", json={"name": "x", "text": "y", "visibility": "arch-admin"}, headers=ivy
    )
    assert above.status_code == 403


def test_source_management_is_for_owners_and_manage_sources(client, app_ctx):
    tokens = make_users(app_ctx)
    ivy = {"Authorization": f"Bearer {tokens['ivy']}"}
    lena = {"Authorization": f"Bearer {tokens['lena']}"}
    # Ivy owns nothing: she may not reclassify or delete the open source.
    assert (
        client.put(
            f"/api/sources/{app_ctx.open_id}/access", json={"role_id": "individual"}, headers=ivy
        ).status_code
        == 403
    )
    assert client.delete(f"/api/sources/{app_ctx.open_id}", headers=ivy).status_code == 403
    # Her own source she may.
    mine = client.post(
        "/api/sources/text", json={"name": "Mine", "text": "Ivy wrote this."}, headers=ivy
    ).json()["source_id"]
    assert (
        client.put(f"/api/sources/{mine}/access", json={"role_id": "everyone"}, headers=ivy).status_code
        == 200
    )
    assert app_ctx.store.get_source(mine)["access_role_id"] is None
    # Lena (manage_sources) may restrict the open source to her own tier, not above it.
    assert (
        client.put(
            f"/api/sources/{app_ctx.open_id}/access", json={"role_id": "arch-admin"}, headers=lena
        ).status_code
        == 403
    )
    changed = client.put(
        f"/api/sources/{app_ctx.open_id}/access", json={"role_id": "local-admin"}, headers=lena
    )
    assert changed.status_code == 200 and changed.json()["min_rank"] == 20
    # ...after which Ivy no longer sees it at all.
    assert client.get(f"/api/sources/{app_ctx.open_id}", headers=ivy).status_code == 404
    assert client.get("/api/sources", headers=ivy).json()[0]["name"] == "Mine"


# ------------------------------------------------------------- users page


def test_users_page_ladder_and_management_rules(client, app_ctx):
    tokens = make_users(app_ctx)
    root = {"Authorization": f"Bearer {tokens['root']}"}
    lena = {"Authorization": f"Bearer {tokens['lena']}"}
    ivy = {"Authorization": f"Bearer {tokens['ivy']}"}
    assert client.get("/users", headers=ivy).status_code == 403
    page = client.get("/users", headers=lena)
    assert page.status_code == 200 and "The ladder" in page.text and "sees <b>1</b> of 2 sources" in page.text
    # Lena manages below her rank only: she can add an assistant, not a regional admin, not a peer.
    ok = client.post(
        "/api/users",
        json={"username": "sam", "password": "secret1", "role_id": "local-assistant"},
        headers=lena,
    )
    assert ok.status_code == 200
    assert (
        client.post(
            "/api/users",
            json={"username": "reg", "password": "secret1", "role_id": "regional-admin"},
            headers=lena,
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/users",
            json={"username": "peer", "password": "secret1", "role_id": "local-admin"},
            headers=lena,
        ).status_code
        == 403
    )
    root_user = app_ctx.store.get_user_by_username("root")
    assert (
        client.patch(f"/api/users/{root_user['id']}", json={"disabled": True}, headers=lena).status_code
        == 403
    )
    # The top of the ladder manages its peers, so root can add another arch admin.
    assert (
        client.post(
            "/api/users",
            json={"username": "root2", "password": "secret1", "role_id": "arch-admin"},
            headers=root,
        ).status_code
        == 200
    )
    # Nobody edits themselves here.
    lena_user = app_ctx.store.get_user_by_username("lena")
    assert (
        client.patch(f"/api/users/{lena_user['id']}", json={"disabled": True}, headers=lena).status_code
        == 400
    )
    # Roles: only manage_roles (root); moving a rank moves the sources at that tier.
    assert client.patch("/api/roles/local-assistant", json={"rank": 25}, headers=lena).status_code == 403
    moved = client.patch("/api/roles/local-admin", json={"rank": 35}, headers=root)
    assert moved.status_code == 200 and moved.json()["rank"] == 35
    assert app_ctx.store.get_source(app_ctx.restricted_id)["min_rank"] == 35
    assert client.delete("/api/roles/local-admin", headers=root).status_code == 400, "still in use"
    assert client.delete("/api/roles/arch-admin", headers=root).status_code == 400, "your own role"
    new_role = client.post(
        "/api/roles", json={"name": "Auditor", "rank": 5, "capabilities": ["run_evals"]}, headers=root
    )
    assert new_role.status_code == 200 and new_role.json()["id"] == "auditor"
    assert client.delete("/api/roles/auditor", headers=root).status_code == 200
    # Forms: the page's own create form, then the token is shown once.
    sign_in(client, "root", "secret1")
    created = client.post(
        "/users",
        data={"username": "form.user", "password": "secret1", "role_id": "individual"},
        follow_redirects=True,
    )
    assert created.status_code == 200 and "hippo_" in created.text and "form.user" in created.text


def test_account_page_password_and_token(client, app_ctx):
    tokens = make_users(app_ctx)
    sign_in(client, "ivy", "secret1")
    page = client.get("/account")
    assert page.status_code == 200 and tokens["ivy"] in page.text and "Individual" in page.text
    wrong = client.post(
        "/account/password",
        data={"current": "bad", "new": "secret2", "again": "secret2"},
        follow_redirects=True,
    )
    assert "current password is wrong" in wrong.text
    client.post("/account/password", data={"current": "secret1", "new": "secret2", "again": "secret2"})
    assert app_ctx.store.check_password("ivy", "secret2") is not None
    client.post("/account/token")
    assert app_ctx.store.get_user_by_token(tokens["ivy"]) is None


# -------------------------------------------------------------------- MCP


def test_mcp_tools_take_the_caller_from_the_bearer_token(client, app_ctx):
    tokens = make_users(app_ctx)
    hidden = set(app_ctx.store.passage_ids_for_source(app_ctx.restricted_id))

    def call(token: str, name: str, arguments: dict) -> dict:
        response = client.post(
            "/mcp",
            headers={**MCP_HEADERS, "Authorization": f"Bearer {token}"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
        )
        assert response.status_code == 200, response.text
        text = response.text
        payload = (
            json.loads(text.split("data: ", 1)[1].split("\n", 1)[0])
            if text.startswith("event:")
            else json.loads(text)
        )
        return payload["result"]

    who = call(tokens["ivy"], "hippo_whoami", {})
    data = who["structuredContent"]
    assert data["user"]["username"] == "ivy" and data["sources_visible"] == 1 and data["sources_total"] == 1
    assert data["visibility_you_may_use"] == ["everyone", "individual"]
    found = call(tokens["ivy"], "hippo_search", {"question": "Who designed the Orion arm?"})[
        "structuredContent"
    ]
    assert not hidden & {p["passage_id"] for p in found["passages"]}
    found = call(tokens["lena"], "hippo_search", {"question": "Who designed the Orion arm?"})[
        "structuredContent"
    ]
    assert hidden & {p["passage_id"] for p in found["passages"]}
    listed = call(tokens["ivy"], "hippo_sources", {})["structuredContent"]["result"]
    assert [s["name"] for s in listed] == ["Open half"]
    remembered = call(tokens["ivy"], "hippo_remember", {"name": "note", "text": "Ivy remembers things."})[
        "structuredContent"
    ]
    assert remembered["visible_to"] == "Individual"
    assert app_ctx.store.get_source(remembered["source_id"])["owner_name"] == "ivy"
    refused = call(tokens["ivy"], "hippo_remember", {"name": "x", "text": "y", "visibility": "arch-admin"})
    assert refused.get("isError") and "above yours" in refused["content"][0]["text"]


def test_mcp_stdio_uses_the_environment_token(app_ctx, monkeypatch):
    tokens = make_users(app_ctx)
    server = mcp_server.build_server(app_ctx, transport="stdio")
    monkeypatch.delenv(mcp_server.TOKEN_ENV, raising=False)
    with pytest.raises(ToolError, match="sign in required"):
        asyncio.run(server.call_tool("hippo_sources", {}))
    monkeypatch.setenv(mcp_server.TOKEN_ENV, tokens["ivy"])
    result = asyncio.run(server.call_tool("hippo_whoami", {}))
    assert not result.is_error and result.structured_content["user"]["username"] == "ivy"


# ------------------------------------------------------------- graph page


def test_graph_page_and_its_endpoints_are_scoped_and_previewable(client, app_ctx):
    tokens = make_users(app_ctx)
    root = {"Authorization": f"Bearer {tokens['root']}"}
    ivy = {"Authorization": f"Bearer {tokens['ivy']}"}
    hidden = set(app_ctx.store.passage_ids_for_source(app_ctx.restricted_id))

    full = client.get("/api/graph/full", headers=root).json()
    assert (
        full["passages"] == len(app_ctx.store.load_passages()) and full["shown_nodes"] == full["total_nodes"]
    )
    assert {t["name"] for t in full["tiers"]} >= {"Everyone", "Local admin"}
    assert all("tier" in n and "degree" in n for n in full["nodes"])

    scoped = client.get("/api/graph/full", headers=ivy).json()
    assert not hidden & {n["id"] for n in scoped["nodes"]}
    assert scoped["total_nodes"] < full["total_nodes"]

    # Filters: a source, a name, a kind, and the cap.
    by_source = client.get(f"/api/graph/full?source={app_ctx.open_id}", headers=root).json()
    assert all(n.get("source_id", app_ctx.open_id) == app_ctx.open_id for n in by_source["nodes"])
    named = client.get("/api/graph/full?q=orion", headers=root).json()
    assert named["matched_nodes"] < full["total_nodes"] and any(
        "orion" in n["label"].lower() for n in named["nodes"]
    )
    only_passages = client.get("/api/graph/full?kind=passage", headers=root).json()
    assert {n["kind"] for n in only_passages["nodes"]} == {"passage"}
    capped = client.get("/api/graph/full?limit=10", headers=root).json()
    assert capped["shown_nodes"] == 10 and capped["truncated"]

    # Preview as a tier: root may, ivy may not.
    preview = client.get("/api/graph/full?as_role=individual", headers=root).json()
    assert preview["viewer"]["preview"] and preview["total_nodes"] == scoped["total_nodes"]
    assert client.get("/api/graph/full?as_role=individual", headers=ivy).status_code == 403
    assert client.get("/graph?as_role=local-admin", headers=root).status_code == 200
    assert "as Local admin" in client.get("/graph?as_role=local-admin", headers=root).text

    # Light up: seeds, paths and passages, never a hidden node for ivy.
    body = {"question": "Who designed the Orion arm?"}
    lit = client.post("/api/graph/light-up", json=body, headers=root).json()
    assert lit["seeds"] and lit["passages"] and lit["subgraph"]["nodes"]
    assert lit["paths"] and all(len(p["nodes"]) >= 2 for p in lit["paths"])
    assert lit["passages"][0]["why"]
    lit_ivy = client.post("/api/graph/light-up", json=body, headers=ivy).json()
    assert not hidden & {n["id"] for n in lit_ivy["subgraph"]["nodes"]}
    assert not hidden & {p["id"] for p in lit_ivy["passages"]}

    # Node details, scoped.
    hidden_passage = next(iter(hidden))
    assert client.get(f"/api/graph/node/{hidden_passage}", headers=ivy).status_code == 404
    details = client.get(f"/api/graph/node/{hidden_passage}", headers=root).json()
    assert details["kind"] == "passage" and details["text"] and "neighbours" in details
    entity = next(n for n in full["nodes"] if n["kind"] == "entity")
    details = client.get(f"/api/graph/node/{entity['id']}", headers=root).json()
    assert details["kind"] == "entity" and "facts" in details and "passages" in details

    page = client.get("/graph", headers=ivy)
    assert page.status_code == 200 and "3d-force-graph.min.js" in page.text and "View as" not in page.text
    assert "View as" in client.get("/graph", headers=root).text


def test_eval_runs_and_generated_questions_stay_inside_the_runners_slice(client, app_ctx):
    tokens = make_users(app_ctx)
    lena = {"Authorization": f"Bearer {tokens['lena']}"}
    hidden = set(app_ctx.store.passage_ids_for_source(app_ctx.restricted_id))
    # Give Lena's tier only the open half: move the restricted source above her.
    app_ctx.store.set_source_access(app_ctx.restricted_id, "regional-admin")
    app_ctx.invalidate_scoped()
    # A hidden source cannot be turned into questions, even by someone who may run evals.
    assert (
        client.post(f"/api/sources/{app_ctx.restricted_id}/generate-questions", headers=lena).status_code
        == 404
    )
    # A run started by Lena answers from her slice only.
    created = client.post(
        "/api/evals/sets",
        json={
            "name": "orion",
            "questions": [{"text": "Who designed the Orion arm?", "expected_answer": "Marcus Lee"}],
        },
        headers=lena,
    )
    set_id = created.json()["set_id"]
    run_id = client.post(f"/api/evals/sets/{set_id}/run", json={"name": "lena's run"}, headers=lena).json()[
        "run_id"
    ]
    app_ctx.jobs.wait_all()
    results = app_ctx.store.list_results(run_id)
    assert results
    full = app_ctx.store.get_result(results[0]["id"])
    assert full["trace"]["passages"]
    assert not hidden & {p["passage_id"] for p in full["trace"]["passages"]}
    assert not hidden & {pid for c in full["trace"]["fact_candidates"] for pid in c["passage_ids"]}
    # The status header does not tell her which source is being indexed.
    assert all(":" not in job for job in client.get("/api/status", headers=lena).json()["jobs"])
    # Generating from her visible source works, and its questions come from visible passages only.
    app_ctx.store.update_source(app_ctx.open_id, status="ready")
    set_id = client.post(
        f"/api/sources/{app_ctx.open_id}/generate-questions",
        json={"max_single": 2, "max_multihop": 1},
        headers=lena,
    ).json()["set_id"]
    app_ctx.jobs.wait_all()
    for q in app_ctx.store.list_questions(set_id):
        assert not hidden & set(q.get("gold_passage_ids") or [])


def test_a_neo4j_outage_after_users_exist_fails_closed(client, app_ctx, monkeypatch):
    tokens = make_users(app_ctx)
    root = {"Authorization": f"Bearer {tokens['root']}"}
    assert client.get("/api/me", headers=root).status_code == 200  # a user has now been seen
    monkeypatch.setattr(app_ctx.store, "ping", lambda: False)
    assert client.get("/api/me", headers=root).status_code == 503
    assert client.get("/", follow_redirects=False).status_code == 503
