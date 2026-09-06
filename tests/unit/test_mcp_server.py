"""The MCP server: tools are listed, callable through the server, and the HTTP app mounts into FastAPI."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError

from hippo import mcp_server
from hippo.context import AppContext
from hippo.hipporag.indexer import Chunk, index_source

TOOL_NAMES = {"hippo_search", "hippo_ask", "hippo_remember", "hippo_sources"}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def sample_chunks(sample_text: str) -> list[Chunk]:
    sections = sample_text.split("## ")[1:]
    return [
        Chunk(i, s.splitlines()[0].strip(), "\n".join(s.splitlines()[1:]).strip())
        for i, s in enumerate(sections)
    ]


@pytest.fixture
def indexed_ctx(ctx: AppContext, sample_text: str) -> AppContext:
    source_id = ctx.store.create_source("sample", "Acme guide")
    index_source(ctx.store, ctx.ollama, source_id, sample_chunks(sample_text))
    return ctx


@pytest.fixture
def server(indexed_ctx: AppContext):
    return mcp_server.build_server(indexed_ctx)


def call(server, tool_name: str, **arguments):
    """Go through the server's own call_tool path (validation + result conversion), synchronously."""
    return asyncio.run(server.call_tool(tool_name, arguments))


def structured(result) -> dict | list:
    """The JSON the client sees. The mcp library wraps a non-object return as {"result": ...}; unwrap it."""
    data = result.structured_content
    if data is None:
        return json.loads(result.content[0].text)
    if isinstance(data, dict) and set(data) == {"result"}:
        return data["result"]
    return data


# --------------------------------------------------------------- tools


def test_lists_the_four_tools_with_descriptions(server):
    tools = asyncio.run(server.list_tools())
    assert {t.name for t in tools} == TOOL_NAMES
    for tool in tools:
        assert tool.description and len(tool.description) > 20
    search = next(t for t in tools if t.name == "hippo_search")
    assert set(search.input_schema["properties"]) == {"question", "top_k"}


def test_search_returns_the_company_passage(server):
    result = call(server, "hippo_search", question="Where is Acme Robotics headquartered?", top_k=3)
    assert not result.is_error
    data = structured(result)
    assert len(data["passages"]) <= 3
    top = data["passages"][0]
    assert set(top) >= {"title", "source", "text", "score", "rank"}
    assert top["rank"] == 1
    assert "Boulder" in top["text"]
    assert top["source"] == "Acme guide"
    # The fake filter keeps facts that share words with the question; all are about Acme Robotics.
    assert data["kept_facts"]
    assert all(len(fact) == 3 for fact in data["kept_facts"])
    assert any("acme robotics" in " ".join(fact).lower() for fact in data["kept_facts"])


def test_search_top_k_is_clamped(server):
    data = structured(call(server, "hippo_search", question="Who designed the Orion arm?", top_k=999))
    assert len(data["passages"]) <= mcp_server.MAX_TOP_K


def test_ask_answers_from_memory_with_sources(server):
    result = call(server, "hippo_ask", question="Where is Acme Robotics headquartered?")
    assert not result.is_error
    data = structured(result)
    assert "Boulder" in data["answer"]
    assert data["sources"], "the answer should say which passages it read"
    assert any(s["title"] == "The company" for s in data["sources"])
    assert set(data["sources"][0]) >= {"title", "source", "rank", "score", "passage_id"}


def test_empty_question_is_a_tool_error(server):
    # Through call_tool the error is raised; over the wire the library turns it into is_error=True.
    with pytest.raises(ToolError, match="question is empty"):
        call(server, "hippo_ask", question="   ")


def test_remember_empty_text_is_a_tool_error(server):
    with pytest.raises(ToolError, match="empty"):
        call(server, "hippo_remember", name="x", text="  ")


def test_sources_lists_the_indexed_source(server):
    data = structured(call(server, "hippo_sources"))
    assert len(data) == 1
    row = data[0]
    assert row["name"] == "Acme guide"
    assert row["kind"] == "sample"
    assert row["passages"] == 8
    assert {"id", "status", "stage", "error"} <= set(row)


def test_remember_adds_a_text_source_and_indexes_it(server, indexed_ctx: AppContext):
    data = structured(
        call(
            server,
            "hippo_remember",
            name="Note",
            text="Zed Labs is located in Lisbon. Zed Labs builds drones.",
        )
    )
    assert data["source_id"]
    indexed_ctx.jobs.wait_all(60)
    source = indexed_ctx.store.get_source(data["source_id"])
    assert source["status"] == "ready"
    assert source["passages"] >= 1

    answer = structured(call(server, "hippo_ask", question="Where is Zed Labs located?"))
    assert "Lisbon" in answer["answer"]


# ------------------------------------------------------------- serving


def test_streamable_http_app_builds(server):
    app = server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True)
    assert any(getattr(route, "path", "") == "/mcp" for route in app.routes)
    assert server.session_manager is not None


def test_mount_serves_mcp_inside_fastapi(indexed_ctx: AppContext):
    app = FastAPI()

    @app.get("/hello")
    def hello():
        return {"ok": True}

    mcp_server.mount(app, indexed_ctx)

    with TestClient(app) as client:
        # Existing routes still win over the catch-all mount.
        assert client.get("/hello").json() == {"ok": True}

        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        response = client.post("/mcp", json=body, headers=MCP_HEADERS)
        assert response.status_code == 200, response.text
        names = {t["name"] for t in _first_json_rpc_result(response.text)["tools"]}
        assert names == TOOL_NAMES


def _first_json_rpc_result(text: str) -> dict:
    """The HTTP transport may answer as plain JSON or as one SSE 'data:' line; accept both."""
    if text.lstrip().startswith("{"):
        return json.loads(text)["result"]
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:") :])["result"]
    raise AssertionError(f"no JSON-RPC result in: {text!r}")
