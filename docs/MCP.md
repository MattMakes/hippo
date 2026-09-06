# Using hippo from an AI client (MCP)

hippo exposes its memory as MCP tools. MCP ("Model Context Protocol") is a
small standard that lets a client such as Claude Code, Claude Desktop or
Cursor call tools. Once connected, you can say "remember this" or "what do we
know about X?" and the client calls hippo.

Two ways to connect:

* **HTTP (recommended).** The web app serves MCP at `http://localhost:8000/mcp`
  (streamable HTTP, stateless). Nothing to install: `./hippo up` is enough.
* **stdio.** The client starts `hippo mcp` itself. This needs hippo installed
  on your machine (`pip install -e .`) and the Neo4j / Ollama ports reachable,
  which they are when the containers are running: compose publishes 7687 and
  11434 on `127.0.0.1`, so they can be reached from this machine only. The
  Neo4j password is the `NEO4J_PASSWORD` line of `.env` (written by `./hippo up`).

Both ways only work from the machine that runs the containers; port 8000 is
also bound to `127.0.0.1`, and hippo has no login of its own.

hippo only answers requests whose `Host` header is `localhost`, `127.0.0.1` or `[::1]`.
To reach `/mcp` by another name or IP (a LAN address, a Tailscale name), add it to
`HIPPO_ALLOWED_HOSTS` in `.env` and publish the port with `HIPPO_BIND=0.0.0.0`; hippo has
no login, so do that only on a network you trust.

## Claude Code

```bash
claude mcp add --transport http hippo http://localhost:8000/mcp
```

Check with `claude mcp list`. Then, in a session: *use hippo to remember that
our staging database lives on host db-2*, or *ask hippo who designed the Orion arm*.

## Claude Desktop

Claude Desktop reads `claude_desktop_config.json`
(macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`).

The stdio form, with hippo installed on your machine:

```json
{
  "mcpServers": {
    "hippo": {
      "command": "hippo",
      "args": ["mcp"],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "<the NEO4J_PASSWORD from your .env>",
        "OLLAMA_URL": "http://localhost:11434"
      }
    }
  }
}
```

If `hippo` is not on the PATH Claude Desktop uses, put the full path to the
executable in `command` (for example `/Users/you/hippo/.venv/bin/hippo`).

To use the HTTP endpoint instead, add it as a custom connector in Claude
Desktop's settings (Settings, Connectors, Add custom connector) with the URL
`http://localhost:8000/mcp`, or bridge it with `mcp-remote`:

```json
{
  "mcpServers": {
    "hippo": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8000/mcp"]
    }
  }
}
```

Restart Claude Desktop after editing the file.

## Cursor

Create `.cursor/mcp.json` in your project (or `~/.cursor/mcp.json` for all projects):

```json
{
  "mcpServers": {
    "hippo": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

Cursor lists the four tools under Settings, MCP.

## stdio alternative: `hippo mcp`

`hippo mcp` runs the same server over stdin/stdout. It reads the usual
environment variables (see `.env.example`), so any client that can spawn a
command works:

```bash
NEO4J_URI=bolt://localhost:7687 NEO4J_PASSWORD="$(sed -n 's/^NEO4J_PASSWORD=//p' .env)" OLLAMA_URL=http://localhost:11434 hippo mcp
```

Nothing may be printed to stdout in this mode (it is the protocol channel);
hippo sends its logs to stderr.

## The four tools

### `hippo_search(question, top_k=5)`

Rank passages for a question without writing an answer. Returns the top
passages with their full text and the facts the retriever kept. Use it when
the client wants the raw material and will reason over it itself.

```json
{"name": "hippo_search", "arguments": {"question": "Who manages the Boulder workshop?", "top_k": 3}}
```

```json
{
  "question": "Who manages the Boulder workshop?",
  "passages": [
    {"passage_id": "passage-...", "title": "Where things are", "source": "Acme guide",
     "text": "Boulder is located in Colorado. ... The Boulder workshop is managed by Tomas Reyes. ...",
     "score": 0.183, "rank": 1}
  ],
  "kept_facts": [["boulder workshop", "is managed by", "tomas reyes"]],
  "used_dpr_fallback": false
}
```

### `hippo_ask(question)`

Search, then let the local LLM read the top passages and answer.

```json
{"name": "hippo_ask", "arguments": {"question": "Who designed the Orion arm?"}}
```

```json
{
  "answer": "Marcus Lee",
  "thought": "The Orion arm was designed by Marcus Lee.",
  "sources": [{"passage_id": "passage-...", "title": "The Orion arm", "source": "Acme guide", "rank": 1, "score": 0.21}]
}
```

### `hippo_remember(name, text)`

Store a piece of text under a name. Indexing runs in the background (the LLM
has to read the text), so the result comes back at once with `status: queued`.
Texts bigger than `HIPPO_MAX_UPLOAD_BYTES` (50 MB) are refused with a tool error.

```json
{"name": "hippo_remember", "arguments": {"name": "Deploy notes", "text": "The staging database runs on db-2. Releases go out on Tuesdays."}}
```

```json
{"source_id": "...", "status": "queued", "name": "Deploy notes"}
```

### `hippo_sources()`

List what is in the memory and whether it is indexed yet.

```json
{"name": "hippo_sources", "arguments": {}}
```

```json
[
  {"id": "...", "name": "Acme guide", "kind": "sample", "status": "ready", "stage": "linking synonyms",
   "progress_done": 1, "progress_total": 1, "passages": 8, "error": null, "created_at": "2026-09-06T17:20:00"}
]
```

Empty questions and empty texts come back as tool errors with a plain
message; the client shows it verbatim.
