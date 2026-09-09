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

import pytest
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from hippo.ingest import pipeline
from hippo.web.app import create_app
from tests.fakes.code_fixture import write_commit_history


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def serve(ctx):
    """Run the real app on a free port in a background thread; yields the /mcp URL."""
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(ctx), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn did not start"
    yield f"http://127.0.0.1:{port}/mcp"
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
