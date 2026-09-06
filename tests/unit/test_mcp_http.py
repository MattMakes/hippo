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


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def server_url(ctx):
    pipeline.add_sample(ctx)
    ctx.jobs.wait_all()
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
