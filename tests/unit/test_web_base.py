"""The web foundation: app factory, Ask page, Settings page, status and graph endpoints, and the request guard."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hippo import mcp_server, prompts
from hippo import status as status_module
from hippo.config import Config
from hippo.context import AppContext
from hippo.hipporag.indexer import Chunk, index_source
from hippo.hipporag.text import make_id
from hippo.web.app import create_app
from hippo.web.routes import pages
from hippo.web.routes.pages import parse_settings_form
from tests.fakes.code_fixture import write_commit_history

MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
MCP_LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
PLACE = "What does pyapp.orders.OrderService.place do?"


def sample_chunks(sample_text: str) -> list[Chunk]:
    sections = sample_text.split("## ")[1:]
    return [
        Chunk(i, s.splitlines()[0].strip(), "\n".join(s.splitlines()[1:]).strip())
        for i, s in enumerate(sections)
    ]


@pytest.fixture
def client(ctx, sample_text):
    source_id = ctx.store.create_source("sample", "Acme guide")
    index_source(ctx.store, ctx.ollama, source_id, sample_chunks(sample_text))
    # The default base_url would send "Host: testserver", which the guard refuses like any foreign name.
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        yield client


def test_ask_page_renders_with_the_question_prefilled(client):
    response = client.get("/ask?q=Who+designed+the+Orion+arm%3F")
    assert response.status_code == 200
    assert "Who designed the Orion arm?" in response.text
    # The auto-submit is an htmx "load" trigger, not an inline script: htmx is loaded with defer and
    # would not exist yet when an inline script runs (the page used to throw a ReferenceError).
    assert 'hx-trigger="submit, load"' in response.text
    assert "htmx.trigger(document.querySelector" not in response.text
    assert 'hx-trigger="submit"' in client.get("/ask").text


def test_asking_keeps_the_trace_so_analyze_does_not_ask_the_model_again(client, fake_ollama):
    response = client.post("/ask", data={"question": "Where is Acme Robotics headquartered?"})
    href = response.text.split('href="/analyze?key=')[1].split('"')[0]
    key, _, rest = href.partition("&")
    assert rest.startswith("question=Where")
    calls_before = len(fake_ollama.calls)
    page = client.get(f"/analyze?key={key}&{rest}")
    assert page.status_code == 200 and "What the search did" in page.text
    assert "Boulder" in page.text  # the answer the user just saw, not a fresh one
    assert len(fake_ollama.calls) == calls_before


def test_unexpected_error_while_asking_is_shown_not_swallowed(client, monkeypatch):
    def broken(ctx, question, **kwargs):
        raise RuntimeError("Neo4j went away")

    monkeypatch.setattr(pages.ask_service, "ask", broken)
    # htmx ignores a 500 body, so the error must come back as a normal page fragment.
    response = client.post("/ask", data={"question": "anything"}, headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert "callout bad" in response.text and "RuntimeError: Neo4j went away" in response.text


def test_asking_returns_an_answer_with_facts_and_passages(client):
    response = client.post("/ask", data={"question": "Where is Acme Robotics headquartered?"})
    assert response.status_code == 200
    assert "Boulder" in response.text
    assert "Facts the model kept" in response.text
    assert "Analyze this question" in response.text


def test_empty_question_shows_a_friendly_error(client):
    response = client.post("/ask", data={"question": "   "})
    assert "Type a question first" in response.text


def test_settings_page_lists_every_setting_with_help(client):
    response = client.get("/settings")
    assert response.status_code == 200
    for key in ("linking_top_k", "passage_node_weight", "damping", "node_specificity"):
        assert key in response.text


def test_number_inputs_take_their_bounds_from_setting_rules(client):
    # The template used to hard-code min="0" max="1" on every non-integer input, which made every
    # setting with a wider range unsaveable from the browser - passage_node_weight included.
    page = client.get("/settings").text
    for key, low, high, step in [
        ("code_seed_weight", 0.0, 10.0, 0.01),
        ("passage_node_weight", 0.0, 10.0, 0.01),
        ("code_structural_scale", 0.0, 3.0, 0.01),
        ("linking_top_k", 0, 100, 1),
        ("code_history_depth", 0, 2000, 1),
    ]:
        field = page.split(f'id="s-{key}"', 1)[1].split(">", 1)[0]
        assert f'min="{low}"' in field and f'max="{high}"' in field, (key, field)
        assert f'step="{step}"' in field, (key, field)


def test_a_float_above_one_saves_from_the_browser(client, ctx):
    response = client.post("/settings", data={"code_seed_weight": "2"}, follow_redirects=False)
    assert response.status_code == 303
    assert ctx.store.get_settings()["code_seed_weight"] == 2.0


def test_an_out_of_range_setting_is_still_refused(client):
    response = client.post("/settings", data={"code_structural_scale": "9"}, follow_redirects=False)
    assert response.status_code == 400
    assert "between 0.0 and 3.0" in response.text


def test_saving_settings_changes_what_search_uses(client, ctx):
    response = client.post(
        "/settings",
        data={"damping": "0.7", "linking_top_k": "6", "node_specificity": "on"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    settings = ctx.store.get_settings()
    assert settings["damping"] == 0.7
    assert settings["linking_top_k"] == 6
    assert settings["node_specificity"] is True


def test_unchecked_checkbox_means_false():
    assert parse_settings_form({"damping": "0.5"})["node_specificity"] is False
    assert parse_settings_form({"node_specificity": "on"})["node_specificity"] is True
    assert "damping" not in parse_settings_form({"damping": ""})


def test_status_endpoint_reports_everything_ready(client):
    status = client.get("/api/status").json()
    assert status["neo4j"] is True
    assert status["ollama"] is True
    assert status["models_ready"] is True
    assert status["stats"]["passages"] == 8


def test_the_code_card_is_all_zeros_when_no_code_is_indexed(client):
    """Purely additive: a prose memory reports the card, empty, rather than not reporting it."""
    assert client.get("/api/status").json()["code"] == {
        "symbols": 0,
        "data_objects": 0,
        "code_edges": 0,
        "commits": 0,
        "languages": [],
        "unresolved_calls": 0,
        "history_skipped": 0,
    }


def test_the_code_card_counts_an_indexed_repository(code_index):
    ctx, _source_id = code_index
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        card = client.get("/api/status").json()["code"]
    assert card["symbols"] == 30 and card["data_objects"] == 12
    assert card["code_edges"] > 0
    # Both come from Source.meta["code"], which the indexer wrote; nothing here loads the graph.
    assert card["languages"] == ["python", "typescript"]
    assert card["unresolved_calls"] >= 2  # os.path.join and print in pyapp/orders.py
    # No repo source, so no history: WP2b's commits and skips stay at zero.
    assert card["commits"] == 0 and card["history_skipped"] == 0


def test_settings_api_rejects_unknown_keys(client):
    assert client.put("/api/settings", json={"damping": 0.6}).json()["damping"] == 0.6
    assert client.put("/api/settings", json={"nonsense": 1}).status_code == 400


def test_ask_api_returns_answer_and_trace(client):
    data = client.post("/api/ask", json={"question": "Who designed the Orion arm?"}).json()
    assert data["answer"] == "Marcus Lee"
    assert "The Orion arm" in [p["title"] for p in data["trace"]["passages"][:3]]
    assert any(c["kept"] for c in data["trace"]["fact_candidates"])


def test_search_api_returns_a_trace_and_the_code_fields(client):
    data = client.post("/api/search", json={"question": "Who designed the Orion arm?"}).json()
    assert "answer" not in data
    assert data["trace"]["question"] == "Who designed the Orion arm?"
    # A memory with no code at all: the keys are there anyway, so a client never branches on it.
    assert {k: data[k] for k in CODE_FIELDS} == EMPTY_CODE_FIELDS


# ------------------------------------------------------ the code fields (QA1 surprise 3)
# The JSON routes used to return the trace and nothing else, so `answer.context_block` - the
# rendered `Title: Code graph` block the model actually read - reached the Ask page and the MCP
# tools but no HTTP client. All five keys now come from `ask.code_fields`, which the MCP tools
# spread into their own answers, so the two shapes cannot drift.

CODE_FIELDS = ("seed_symbols", "paths", "tests", "history", "code_graph")
EMPTY_CODE_FIELDS = {"seed_symbols": [], "paths": [], "tests": [], "history": [], "code_graph": ""}


def test_ask_api_returns_the_code_fields_the_mcp_tools_return(code_index):
    ctx, source_id = code_index
    write_commit_history(ctx, source_id)
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        data = client.post("/api/ask", json={"question": PLACE}).json()
        # The same question through MCP, before the client's exit closes the store.
        expected = mcp_server.ask_tool(ctx, PLACE)

    assert data["code_graph"].startswith(prompts.CODE_GRAPH_HEADER)
    assert [s["name"] for s in data["seed_symbols"] if s["how"] == "identifier"] == ["OrderService.place"]
    assert any(row["kind"] == "INVOKES" for row in data["paths"])
    assert [t["name"] for t in data["tests"]] == ["tests.test_orders.test_place"]
    assert [h["sha"] for h in data["history"]] == ["b2b2b2b"]
    # One helper, one shape: the HTTP payload and the MCP tool's agree field for field.
    assert {k: data[k] for k in CODE_FIELDS} == {k: expected[k] for k in CODE_FIELDS}


def test_ask_api_code_fields_are_empty_on_a_prose_question_over_a_code_memory(code_index):
    """Ruling 1a's gate, seen from HTTP: the memory holds code, the question named none."""
    ctx, _source_id = code_index
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        data = client.post("/api/ask", json={"question": "Where is Acme Robotics headquartered?"}).json()

    assert data["trace"]["used_code_seeds"] is False
    assert {k: data[k] for k in CODE_FIELDS if k != "seed_symbols"} == {
        k: v for k, v in EMPTY_CODE_FIELDS.items() if k != "seed_symbols"
    }
    # `seed_symbols` is the one that is *not* empty here: this question pulls ten dense seeds out
    # of the code memory, and not one of them opens the gate. Hiding them would make the payload
    # disagree with the trace it is taken from.
    assert data["seed_symbols"] and all(seed["how"] == "dense" for seed in data["seed_symbols"])


def test_entity_search_and_neighborhood(client):
    entities = client.get("/api/entities?q=acme").json()
    assert entities and entities[0]["name"] == "acme robotics"
    graph = client.get(f"/api/graph/neighborhood?node_id={entities[0]['id']}").json()
    assert any(n["kind"] == "passage" for n in graph["nodes"])
    assert all("kinds" in e for e in graph["edges"])
    assert client.get("/api/graph/neighborhood?node_id=nope").status_code == 404


def test_the_graph_endpoints_survive_an_index_that_contains_code(ctx, client):
    """Nothing may 500 over a code-bearing index, and every count must still be about the kind it
    names. The per-kind panels themselves are `test_web_graph_code.py`."""
    source_id = ctx.store.create_source("repo", "pyapp")
    symbol_id = make_id("symbol-", "place")
    ctx.store.add_passages(
        [
            {
                "id": "passage-code",
                "source_id": source_id,
                "ordinal": 0,
                "title": "pyapp/orders.py :: place",
                "text": "def place(self, order): ...",
                "embedding": [1.0] + [0.0] * 127,
            }
        ]
    )
    ctx.store.add_symbols(
        [
            {
                "id": symbol_id,
                "source_id": source_id,
                "name": "place",
                "qualname": "pyapp.orders.OrderService.place",
                "kind": "method",
                "path": "pyapp/orders.py",
                "line_start": 16,
                "line_end": 23,
            }
        ]
    )
    ctx.store.link_definitions([(symbol_id, "passage-code")])
    ctx.store.bump_graph_version()
    ctx.invalidate_graph()

    full = client.get("/api/graph/full?limit=500").json()
    index = ctx.graph_for(None)
    assert full["entities"] == index.num_entities  # entities only: the symbol is not counted as one
    assert full["passages"] == len(index.passages)
    by_id = {n["id"]: n for n in full["nodes"]}
    assert by_id[symbol_id]["kind"] == "symbol"
    assert by_id[symbol_id]["label"] == "pyapp.orders.OrderService.place"
    assert "passage_count" not in by_id[symbol_id]  # a symbol is not an entity
    # Every passage node still resolves to its own passage, which is what passages-last protects.
    for node in full["nodes"]:
        if node["kind"] == "passage":
            assert node["source_id"] and node["source_name"]

    assert client.get(f"/api/graph/node/{symbol_id}").status_code == 200
    assert client.get(f"/api/graph/neighborhood?node_id={symbol_id}").status_code == 200
    assert client.get("/api/graph/full?kind=symbol").json()["nodes"][0]["id"] == symbol_id


def test_status_partial_renders_pills(client, monkeypatch):
    monkeypatch.setattr(status_module, "CACHE_SECONDS", 0.0)  # a neighbouring test's ctx must not leak in
    text = client.get("/partials/status").text
    assert (
        "Graph" in text and "Ollama" in text
    )  # "Graph" is the embedded store; it reads "Neo4j" with that backend
    assert "Neo4j" not in text
    assert "symbol" not in text  # no code indexed in this memory: the Code card stays hidden


def test_status_partial_shows_the_code_card_when_code_is_indexed(code_index, monkeypatch):
    monkeypatch.setattr(status_module, "CACHE_SECONDS", 0.0)  # a neighbouring test's ctx must not leak in
    ctx, _source_id = code_index
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        text = client.get("/partials/status").text
    assert "Code 30 symbols" in text
    assert "python, typescript" in text


def test_startup_marks_jobs_interrupted_by_a_restart_as_failed(ctx):
    stuck = ctx.store.create_source("text", "stuck")
    ctx.store.update_source(stuck, status="indexing", stage="extracting facts")
    with TestClient(create_app(ctx)):
        source = ctx.store.get_source(stuck)
    assert source["status"] == "failed" and "restart" in source["error"]


# ---------------------------------------------------------------- the request guard


def test_cross_site_posts_are_refused_and_plant_nothing(client, ctx):
    before = len(ctx.store.list_sources())
    for headers in (
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Referer": "https://evil.example/page.html"},
        {"Sec-Fetch-Site": "cross-site"},
    ):
        response = client.post("/sources/text", data={"name": "planted", "text": "x"}, headers=headers)
        assert response.status_code == 403, headers
    assert client.post("/api/sources/sample", headers={"Origin": "https://evil.example"}).status_code == 403
    assert len(ctx.store.list_sources()) == before


def test_same_site_and_headerless_posts_still_work(client, ctx):
    for headers in (
        {},
        {"Origin": "http://localhost:8000", "Sec-Fetch-Site": "same-origin"},
        {"Referer": "http://localhost:8000/", "Sec-Fetch-Site": "same-site"},
        {"Origin": "http://127.0.0.1:8000"},
    ):
        response = client.post(
            "/sources/text",
            data={"name": "mine", "text": "Zed Corp is in Austin."},
            headers=headers,
            follow_redirects=False,
        )
        assert response.status_code == 303, headers
    ctx.jobs.wait_all()
    assert len([s for s in ctx.store.list_sources() if s["name"] == "mine"]) == 4


def test_foreign_host_header_is_refused_everywhere(client):
    for host in ("evil.example", "evil.example:8000", "localhost.evil.example"):
        assert client.get("/", headers={"Host": host}).status_code == 400, host
        assert client.post("/api/search", json={"question": "x"}, headers={"Host": host}).status_code == 400
        assert (
            client.post("/mcp", json=MCP_LIST_TOOLS, headers={**MCP_HEADERS, "Host": host}).status_code == 400
        )
    assert "HIPPO_ALLOWED_HOSTS" in client.get("/", headers={"Host": "evil.example"}).text


def test_local_host_headers_are_accepted_on_pages_and_mcp(client):
    for host in ("localhost", "localhost:8000", "127.0.0.1:8000", "[::1]:8000", "[::1]"):
        assert client.get("/", headers={"Host": host}).status_code == 200, host
        # The MCP library runs its own Host check, built from the same list.
        response = client.post("/mcp", json=MCP_LIST_TOOLS, headers={**MCP_HEADERS, "Host": host})
        assert response.status_code == 200, (host, response.text)


def test_allowed_hosts_can_be_extended_or_switched_off(ctx, tmp_path):
    class SharedStore:
        """The two apps below share one store; shutting the first app down must not close it for the second."""

        def __getattr__(self, name):
            return getattr(ctx.store, name)

        def close(self) -> None:
            pass

    def app_for(hosts: tuple[str, ...]):
        config = Config(data_dir=tmp_path / "data", allowed_hosts=hosts)
        return create_app(AppContext(config=config, store=SharedStore(), ollama=ctx.ollama))

    with TestClient(app_for(("localhost", "mybox")), base_url="http://mybox:8000") as client:
        assert client.get("/").status_code == 200
        assert client.get("/", headers={"Host": "otherbox"}).status_code == 400
    with TestClient(app_for(("*",)), base_url="http://anything.example") as client:
        assert client.get("/").status_code == 200
        assert client.post("/mcp", json=MCP_LIST_TOOLS, headers=MCP_HEADERS).status_code == 200


def test_get_analyze_never_runs_the_model(client, fake_ollama):
    calls_before = len(fake_ollama.calls)
    response = client.get("/analyze?question=Who+designed+the+Orion+arm%3F")
    assert response.status_code == 404
    assert "Analyze it again" in response.text and 'action="/analyze"' in response.text
    assert len(fake_ollama.calls) == calls_before
    assert client.get("/analyze?key=expired&question=x").status_code == 404
    # The same request as a POST is the one that does the work.
    response = client.post(
        "/analyze", data={"question": "Who designed the Orion arm?"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert "key=" in response.headers["location"] and "question=Who" in response.headers["location"]
    assert len(fake_ollama.calls) > calls_before
    assert client.get(response.headers["location"]).status_code == 200
