"""
The MCP server over real HTTP, the way Claude Code or Cursor would use it.

The synchronous test client cannot read the streaming responses MCP uses, so
this test starts uvicorn in a background thread on a free port and talks to
it with the official MCP client.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver.exceptions import ToolError

from hippo import mcp_server
from hippo.ingest import pipeline
from hippo.web import auth
from hippo.web.app import create_app
from tests.fakes.code_fixture import write_commit_history


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def serve(ctx, *, standalone=False):
    """Run the real app on a free port in a background thread; yields the /mcp URL."""
    port = free_port()
    app = FastAPI() if standalone else create_app(ctx)
    if standalone:
        mcp_server.mount(app, ctx)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn did not start"
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture
def server_url(ctx):
    pipeline.add_sample(ctx)
    ctx.jobs.wait_all()
    yield from serve(ctx)


@pytest.fixture
def code_server_url(code_index):
    """The same server over a memory that holds a code graph, so the path tools have something to walk."""
    ctx, source_id = code_index
    write_commit_history(ctx, source_id)
    yield from serve(ctx)


def tool_payload(result):
    return result.structured_content or json.loads(result.content[0].text)


def test_a_real_mcp_client_can_list_and_call_the_tools(server_url):
    async def scenario():
        async with streamable_http_client(server_url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                init = await session.initialize()
                assert init.server_info.name == "hippo"

                tools = await session.list_tools()
                assert [t.name for t in tools.tools] == [
                    "hippo_search",
                    "hippo_ask",
                    "hippo_remember",
                    "hippo_sources",
                    "hippo_whoami",
                    "hippo_explain_path",
                    "hippo_blast_radius",
                    "hippo_exception_path",
                    "hippo_history",
                ]

                sources = tool_payload(await session.call_tool("hippo_sources", {}))
                rows = sources["result"] if isinstance(sources, dict) else sources
                assert rows[0]["status"] == "ready"

                found = tool_payload(
                    await session.call_tool(
                        "hippo_search", {"question": "Where is Acme Robotics headquartered?", "top_k": 2}
                    )
                )
                assert found["passages"][0]["title"].endswith("The company")
                assert ["acme robotics", "is headquartered in", "boulder"] in found["kept_facts"]

                answered = tool_payload(
                    await session.call_tool("hippo_ask", {"question": "Who designed the Orion arm?"})
                )
                assert answered["answer"] == "Marcus Lee"
                assert answered["sources"]

                remembered = tool_payload(
                    await session.call_tool(
                        "hippo_remember", {"name": "note", "text": "Zed Corp is located in Austin."}
                    )
                )
                assert remembered["status"] == "queued"

                empty = await session.call_tool("hippo_search", {"question": "  "})
                assert empty.is_error and "empty" in empty.content[0].text

    asyncio.run(scenario())


def test_a_real_mcp_client_can_walk_the_code_graph(code_server_url):
    """The four code tools over the wire, including how an ambiguous name comes back."""

    async def scenario():
        async with streamable_http_client(code_server_url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()

                walked = tool_payload(
                    await session.call_tool(
                        "hippo_explain_path",
                        {"a": "pyapp.cli.main", "b": "pyapp.billing.total"},
                    )
                )
                assert walked["lines"] == [
                    "pyapp.cli.main -[INVOKES 0.90 via_import]-> pyapp.orders.OrderService.place",
                    "pyapp.orders.OrderService.place -[INVOKES 0.90 via_import]-> pyapp.billing.total",
                ]

                blast = tool_payload(
                    await session.call_tool(
                        "hippo_blast_radius", {"symbol": "pyapp.billing.total", "depth": 1}
                    )
                )
                assert blast["levels"] == [["pyapp.billing", "pyapp.orders.OrderService.place"]]

                raised = tool_payload(
                    await session.call_tool(
                        "hippo_exception_path",
                        {
                            "symbol": "pyapp.orders.OrderService.save",
                            "exception": "pyapp.store.OrderError",
                        },
                    )
                )
                assert raised["found"] is True

                past = tool_payload(
                    await session.call_tool("hippo_history", {"symbol": "pyapp.orders.OrderService.place"})
                )
                assert [c["sha"] for c in past["commits"]] == ["b2b2b2b"]

                # A name meaning three things is an error the client can act on: it lists them.
                unclear = await session.call_tool("hippo_history", {"symbol": "log"})
                assert unclear.is_error
                assert "pyapp.store.Base.log" in unclear.content[0].text

    asyncio.run(scenario())


def credentials(ctx):
    ctx.store.ping()
    admin = ctx.store.create_user("transport-admin", "secret1", "arch-admin")
    reader = ctx.store.create_user("transport-reader", "secret1", "individual")
    return ctx.store.get_user(admin), ctx.store.get_user(reader)


@pytest.mark.parametrize(
    "headers", [{}, {"authorization": "Basic invalid"}, {"authorization": "Bearer invalid"}]
)
def test_http_caller_never_falls_back_to_process_token(ctx, monkeypatch, headers):
    admin, _ = credentials(ctx)
    monkeypatch.setenv(mcp_server.TOKEN_ENV, admin["token"])
    with pytest.raises(ToolError, match="sign in required"):
        mcp_server.caller(ctx, SimpleNamespace(headers=headers))


def test_http_cookie_caller_keeps_own_identity(ctx, monkeypatch):
    admin, reader = credentials(ctx)
    monkeypatch.setenv(mcp_server.TOKEN_ENV, admin["token"])
    cookie = auth.sign_session(auth.session_secret(ctx), reader["id"])
    principal = mcp_server.caller(ctx, SimpleNamespace(headers={"cookie": f"{auth.SESSION_COOKIE}={cookie}"}))
    assert principal.user_id == reader["id"]


def test_http_direct_tool_call_cannot_inherit_process_identity(ctx, monkeypatch):
    admin, _ = credentials(ctx)
    monkeypatch.setenv(mcp_server.TOKEN_ENV, admin["token"])
    with pytest.raises(ToolError, match="sign in required"):
        asyncio.run(mcp_server.build_server(ctx).call_tool("hippo_whoami", {}))


def test_real_http_cookie_and_bearer_ignore_ambient_admin(ctx, monkeypatch):
    admin, reader = credentials(ctx)
    monkeypatch.setenv(mcp_server.TOKEN_ENV, admin["token"])
    cookie = auth.sign_session(auth.session_secret(ctx), reader["id"])

    async def scenario(url):
        for headers in (
            {"Cookie": f"{auth.SESSION_COOKIE}={cookie}"},
            {"Authorization": f"Bearer {reader['token']}"},
        ):
            async with httpx.AsyncClient(headers=headers) as client:
                async with streamable_http_client(url, http_client=client) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        who = tool_payload(await session.call_tool("hippo_whoami", {}))
                        assert who["user"]["id"] == reader["id"]

    for url in serve(ctx):
        asyncio.run(scenario(url))


def test_real_http_without_credentials_refuses_ambient_admin(ctx, monkeypatch):
    admin, _ = credentials(ctx)
    monkeypatch.setenv(mcp_server.TOKEN_ENV, admin["token"])

    async def scenario(url):
        statuses = []

        async def record_response(response):
            statuses.append(response.status_code)

        async with httpx.AsyncClient(event_hooks={"response": [record_response]}) as client:
            with pytest.raises(BaseExceptionGroup):
                async with streamable_http_client(url, http_client=client) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
        # The MCP SDK wraps HTTP errors as MCPError, so inspect the actual wire response.
        assert statuses and set(statuses) == {401}

    for url in serve(ctx):
        asyncio.run(scenario(url))


@pytest.mark.parametrize("mount_name", ["streamable_http_app", "sse_app"])
def test_stdio_identity_server_cannot_be_mounted_over_http(ctx, mount_name):
    server = mcp_server.build_server(ctx, transport="stdio")
    with pytest.raises(ValueError, match="credential transport"):
        getattr(server, mount_name)()


def test_http_identity_server_cannot_run_stdio(ctx):
    server = mcp_server.build_server(ctx)
    with pytest.raises(ValueError, match="credential transport"):
        asyncio.run(server.run_stdio_async())


def test_mcp_outage_fails_closed_even_before_first_user(ctx, monkeypatch):
    monkeypatch.setattr(ctx.store, "ping", lambda: False)
    with pytest.raises(ToolError, match="cannot reach"):
        mcp_server.caller(ctx, None)


@pytest.mark.parametrize("transport", ["http", "stdio"])
def test_mcp_outage_during_authentication_never_becomes_open(ctx, monkeypatch, transport):
    credentials(ctx)
    auth._users_seen.discard(id(ctx))
    replies = iter([True, False])
    monkeypatch.setattr(ctx.store, "ping", lambda: next(replies, False))
    with pytest.raises(ToolError, match="cannot reach"):
        mcp_server.caller(ctx, None, transport=transport)


@pytest.mark.parametrize("credential", ["missing", "malformed", "invalid", "disabled"])
def test_standalone_http_tool_denies_invalid_caller_with_ambient_admin(ctx, monkeypatch, credential):
    admin, reader = credentials(ctx)
    monkeypatch.setenv(mcp_server.TOKEN_ENV, admin["token"])
    ctx.store.update_user(reader["id"], disabled=True)
    headers = {
        "missing": {},
        "malformed": {"Authorization": "Basic invalid"},
        "invalid": {"Authorization": "Bearer invalid"},
        "disabled": {"Authorization": f"Bearer {reader['token']}"},
    }[credential]

    async def scenario(url):
        async with httpx.AsyncClient(headers=headers) as client:
            async with streamable_http_client(url, http_client=client) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    result = await session.call_tool("hippo_whoami", {})
                    assert result.is_error
                    assert "sign in required" in result.content[0].text
                    assert not result.structured_content

    for url in serve(ctx, standalone=True):
        asyncio.run(scenario(url))
