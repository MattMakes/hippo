# Using hippo from an AI client (MCP)

hippo exposes its memory as MCP tools. MCP ("Model Context Protocol") is a
small standard that lets a client such as Claude Code, Claude Desktop or
Cursor call tools. Once connected, you can say "remember this" or "what do we
know about X?" and the client calls hippo.

Two ways to connect:

* **HTTP (recommended).** The web app serves MCP at `http://localhost:8000/mcp`
  (streamable HTTP, stateless). Nothing to install: `hippo serve` (or
  `./hippo up`) is enough.
* **stdio.** The client starts `hippo mcp` itself, with hippo installed on
  your machine (`pip install -e .`) and Ollama reachable. Mind the database:
  the embedded LadybugDB file can be open in one process at a time, so `hippo
  mcp` only works while `hippo serve` is *not* running on the same file (it
  fails with a clear "already open in another hippo process" message
  otherwise). If you keep the server running, use the HTTP form. With
  `HIPPO_STORE=neo4j` there is no such limit; compose publishes 7687 on
  `127.0.0.1`, and the password is the `NEO4J_PASSWORD` line of `.env`.

Both ways only work from the machine that runs hippo; port 8000 is bound to
`127.0.0.1`.

## Who is calling

Until the first user is created hippo is open and every tool sees the whole
memory. Once users exist (Users page, or `./hippo user add`), every MCP call
must identify its user, and each tool then works on the part of the memory
that user may see (see "Users and roles" in the README):

* **HTTP:** send `Authorization: Bearer <token>`. Your token is on your
  Account page (`/account`).
* **stdio (`hippo mcp`):** set the `HIPPO_TOKEN` environment variable.

Without a valid token the HTTP endpoint answers 401 and the tools return the
error "sign in required". `hippo_whoami` tells you who hippo thinks you are.

hippo only answers requests whose `Host` header is `localhost`, `127.0.0.1` or `[::1]`.
To reach `/mcp` by another name or IP (a LAN address, a Tailscale name), add it to
`HIPPO_ALLOWED_HOSTS` in `.env` and publish the port with `HIPPO_BIND=0.0.0.0`; hippo has
no login, so do that only on a network you trust.

## Claude Code

```bash
claude mcp add --transport http hippo http://localhost:8000/mcp
# once users exist:
claude mcp add --transport http hippo http://localhost:8000/mcp --header "Authorization: Bearer <your token>"
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
        "HIPPO_DATA_DIR": "/Users/you/hippo/data",
        "OLLAMA_URL": "http://localhost:11434",
        "HIPPO_TOKEN": "<your token from /account, once users exist>"
      }
    }
  }
}
```

If `hippo` is not on the PATH Claude Desktop uses, put the full path to the
executable in `command` (for example `/Users/you/hippo/.venv/bin/hippo`).
`HIPPO_DATA_DIR` must point at the folder that holds your `hippo.lbug` (or set
`HIPPO_DB_PATH` to the file itself); with Neo4j, pass `HIPPO_STORE=neo4j` and
the `NEO4J_*` variables instead.

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
      "url": "http://localhost:8000/mcp",
      "headers": {"Authorization": "Bearer <your token, once users exist>"}
    }
  }
}
```

Cursor lists the nine tools under Settings, MCP.

## stdio alternative: `hippo mcp`

`hippo mcp` runs the same server over stdin/stdout. It reads the usual
environment variables (see `.env.example`), so any client that can spawn a
command works:

```bash
HIPPO_DATA_DIR=./data OLLAMA_URL=http://localhost:11434 hippo mcp
```

Remember that this opens the database file itself, so stop `hippo serve` first
(or use the HTTP endpoint of the running server instead).

Nothing may be printed to stdout in this mode (it is the protocol channel);
hippo sends its logs to stderr.

## The nine tools

Five are about the memory as a whole. The other four answer structural questions about indexed
source code, and only return anything once a repository has been indexed (see "Code" in the
README). All nine work on the part of the memory the caller may see.

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
  "used_dpr_fallback": false,
  "seed_symbols": [], "paths": [], "tests": [], "history": [], "code_graph": ""
}
```

The last five keys are the code graph's, and they are **always present** so a client never has to
branch on whether the memory holds code. On a memory with no code in it they are all empty, as
above. One caveat if your memory mixes prose and code: `paths`, `tests`, `history` and `code_graph`
stay empty unless the question actually *named* code, but `seed_symbols` can still carry entries —
a code passage that merely scored well on similarity is recorded there even though it changes
nothing else. Check `how` to tell them apart. When the question does name code, all five fill in:

```json
{
  "seed_symbols": [
    {"node_id": "symbol-...", "name": "OrderService.place", "vertex": 11, "weight": 0.333,
     "how": "identifier", "token": "OrderService.place", "kind": "symbol", "n_matches": 1,
     "matched_by": "OrderService.place", "ambiguous": false, "specificity": 3.0, "boost": 1.0,
     "kept": true}
  ],
  "paths": [
    {"a": "symbol-...", "b": "symbol-...", "a_name": "pyapp.orders.OrderService.place",
     "b_name": "pyapp.billing.total", "kind": "INVOKES", "omega": 0.9, "provenance": "via_import",
     "in_branch": false, "is_await": false, "call_line": 18}
  ],
  "tests": [{"id": "symbol-...", "name": "tests.test_orders.test_place", "path": "tests/test_orders.py"}],
  "history": [],
  "code_graph": "Relations read from the code graph, not from prose. INVOKES = calls, ...\npyapp.orders.OrderService.place -[INVOKES 0.90 via_import]-> pyapp.billing.total\nTests: tests.test_orders.test_place"
}
```

Two things to know about those rows. `how` says *why* a symbol was seeded — `identifier`,
`stack_trace`, `exception`, `fenced_code` or `diff` when the question said so, or `dense` when the
symbol came from a passage that merely scored well. **Only the first five mean the question named
code**, and only they cause the other four keys to fill in; a `dense` row on its own is a note in
the trace and nothing more. And `seed_symbols[].name` is the **module-relative** qualname (`OrderService.place`),
while `paths[].a_name` and everything in `code_graph` use the fully-qualified display name
(`pyapp.orders.OrderService.place`). The path tools below accept either form.

### `hippo_ask(question)`

Search, then let the local LLM read the top passages and answer.

```json
{"name": "hippo_ask", "arguments": {"question": "Who designed the Orion arm?"}}
```

```json
{
  "answer": "Marcus Lee",
  "thought": "The Orion arm was designed by Marcus Lee.",
  "sources": [{"passage_id": "passage-...", "title": "The Orion arm", "source": "Acme guide", "rank": 1, "score": 0.21}],
  "seed_symbols": [], "paths": [], "tests": [], "history": [], "code_graph": ""
}
```

It carries the same five code-graph keys as `hippo_search`, in the same shapes and under the same
rule, `seed_symbols` included: always present, and empty unless the question named something in
indexed code — except for the dense-seed rows noted above. Here `code_graph`
is exactly the block the model was shown before it answered, so it is the evidence behind the
answer rather than a separate lookup. `sources` lists only the passages the model actually read;
the code block is never one of them.

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

### `hippo_whoami()`

Who hippo thinks you are: your user and role, your rank on the ladder, what
your role may do, how many of the sources you can see, and the role ids you
may pass as `visibility` to `hippo_remember`.

```json
{
  "open_mode": false,
  "user": {"id": "3f2a...", "username": "ivy", "display_name": ""},
  "role": {"id": "individual", "name": "Individual", "rank": 0},
  "can": ["add_sources"],
  "sources_visible": 3, "sources_total": 9,
  "ladder": [{"id": "arch-admin", "name": "Arch admin", "rank": 40}, "..."],
  "visibility_you_may_use": ["everyone", "individual"]
}
```

`hippo_remember(name, text, visibility=None)` records you as the owner and,
by default, makes the text visible to your own tier and above; pass
`"everyone"` or a role id at or below yours to choose otherwise.

## The four code tools

These answer structural questions about indexed source code — the kind a call graph can answer
exactly and an embedding can only guess at. They read the code graph directly and never call the
language model, so they are fast and their answers are the same every time.

Each takes a symbol by name. A **fully-qualified** name (`pyapp.orders.OrderService.place`), a
module-relative one (`OrderService.place`) or a bare one (`place`) all work, as long as the name
picks out one symbol. If it does not, the tool fails with the candidates in the message rather than
guessing:

```json
{"name": "hippo_blast_radius", "arguments": {"symbol": "log"}}
```

```
ToolError: 'log' could mean any of: csapp.Orders.OrderService.OrderService.Log, csapp.Store.Base.Base.Log, goapp.orders.service.Service.Log, goapp.store.base.Base.Log, pyapp.orders.OrderService.log, pyapp.store.Base.log, rsapp.src.orders.OrderService.log, rsapp.src.store.Base.log, tsapp.models.base.Base.log
```

The match is **case-blind**, which is why C#'s `Log` and Go's `Log` are in that list beside Python's
`log`. In a repository written in more than one language the fully-qualified form is the one to
reach for.

A name nothing matches fails the same way — `no symbol or data object called 'nope'` — and so does a
blank one. `ToolError` is the one error an MCP client is shown verbatim, so everything you could act
on is inside the message. Every tool also returns `lines`: the same answer already rendered for a
person to read, so a client can show it without walking the JSON.

An edge's `omega` is how sure the resolver is (1.00 = read straight from the syntax, 0.50 = matched
on a unique name) and `provenance` names the rule that produced it. Edges below `code_theta` (0.5 by
default) are not walked at all.

### `hippo_explain_path(a, b)`

How one symbol reaches another: the shortest chain of calls, imports and inheritance between them.
Answers "how does this end up calling that?".

```json
{"name": "hippo_explain_path",
 "arguments": {"a": "pyapp.orders.OrderService.place", "b": "pyapp.billing.total"}}
```

```json
{
  "a": "pyapp.orders.OrderService.place",
  "b": "pyapp.billing.total",
  "a_id": "symbol-f32134b3...", "b_id": "symbol-1127d1fb...",
  "found": true,
  "edges": [
    {"a": "symbol-f32134b3...", "b": "symbol-1127d1fb...",
     "a_name": "pyapp.orders.OrderService.place", "b_name": "pyapp.billing.total",
     "kind": "INVOKES", "omega": 0.9, "provenance": "via_import",
     "in_branch": false, "is_await": false, "call_line": 18}
  ],
  "lines": ["pyapp.orders.OrderService.place -[INVOKES 0.90 via_import]-> pyapp.billing.total"]
}
```

`found` is `false` with an empty `edges` when the two are not connected — that is an answer, not an
error. `in_branch` says the call sits inside an `if` or a `try`, and `is_await` that it is awaited.

The same tool over a Go repository, and the one provenance a Python or TypeScript answer can never
carry — `same_scope`, a call the language resolves with no import at all, because both files are in
the same package:

```json
{"name": "hippo_explain_path",
 "arguments": {"a": "goapp.orders.service_test.TestPlace", "b": "goapp.orders.service.Service.Place"}}
```

```json
{
  "a": "goapp.orders.service_test.TestPlace",
  "b": "goapp.orders.service.Service.Place",
  "a_id": "symbol-73548d06...", "b_id": "symbol-a986308e...",
  "found": true,
  "edges": [
    {"a": "symbol-73548d06...", "b": "symbol-a986308e...",
     "a_name": "goapp.orders.service_test.TestPlace", "b_name": "goapp.orders.service.Service.Place",
     "kind": "INVOKES", "omega": 1.0, "provenance": "same_scope",
     "in_branch": false, "is_await": false, "call_line": 6}
  ],
  "lines": ["goapp.orders.service_test.TestPlace -[INVOKES 1.00 same_scope]-> goapp.orders.service.Service.Place"]
}
```

A C# namespace earns the same 1.00. Rust has no scope above the file, so a resolved Rust call across
files is always 0.90 `via_import` — `rsapp.src.orders.OrderService.place -[INVOKES 0.90 via_import]->
rsapp.src.billing.total`.

### `hippo_blast_radius(symbol, depth=2)`

What a change here could break: everything that depends on this symbol, level by level outwards.
`depth` is clamped to 1–4.

```json
{"name": "hippo_blast_radius", "arguments": {"symbol": "pyapp.orders.OrderService.log", "depth": 2}}
```

```json
{
  "symbol": "pyapp.orders.OrderService.log",
  "symbol_id": "symbol-ac1f20eb...",
  "depth": 2,
  "levels": [
    ["pyapp.orders.OrderService", "pyapp.orders.OrderService.place"],
    ["pyapp.__init__", "pyapp.cli", "pyapp.cli.main", "pyapp.orders", "tests.test_orders", "tests.test_orders.test_place"]
  ],
  "truncated": false,
  "lines": [
    "Level 1: pyapp.orders.OrderService, pyapp.orders.OrderService.place",
    "Level 2: pyapp.__init__, pyapp.cli, pyapp.cli.main, pyapp.orders, tests.test_orders, tests.test_orders.test_place",
    "Subsystems: pyapp.__init__: pyapp.__init__, pyapp.cli, ..."
  ]
}
```

This walks dependencies *inwards* — who calls this — not what this calls. `truncated: true` means the
200-node cap stopped the walk, which for a hub symbol is itself the answer.

### `hippo_exception_path(symbol, exception)`

How a function reaches an exception class: the chain of calls ending in whatever raises it. Answers
"where can this error actually come from?".

```json
{"name": "hippo_exception_path",
 "arguments": {"symbol": "pyapp.orders.OrderService.save", "exception": "pyapp.store.OrderError"}}
```

```json
{
  "symbol": "pyapp.orders.OrderService.save",
  "symbol_id": "symbol-bb1109bc...",
  "exception": "pyapp.store.OrderError",
  "found": true,
  "edges": [
    {"a": "symbol-bb1109bc...", "b": "symbol-57da82b6...",
     "a_name": "pyapp.orders.OrderService.save", "b_name": "pyapp.store.OrderError",
     "kind": "RAISES", "omega": 0.9, "provenance": "resolved",
     "in_branch": false, "is_await": false, "call_line": 0}
  ],
  "lines": ["pyapp.orders.OrderService.save -[RAISES 0.90 resolved]-> pyapp.store.OrderError"]
}
```

Only exception classes defined *in the repository* are nodes. A `raise ValueError` is recorded on the
function itself and has no path, because there is nothing in the repository to point at.

### `hippo_history(symbol, limit=3)`

The commits that touched this symbol, newest first. Needs a source added as a **git repository** — a
zip or a folder has no history to read — and returns an empty `commits` list otherwise.

```json
{"name": "hippo_history", "arguments": {"symbol": "pyapp.orders.OrderService.place", "limit": 3}}
```

```json
{
  "symbol": "pyapp.orders.OrderService.place",
  "symbol_id": "symbol-1cdd45af...",
  "commits": [
    {"id": "commit-2bd173ee...", "sha": "c9be063124adf79f45bba65782c07aad68f3678f",
     "date": "2024-01-02", "subject": "Total, invoice and log in place"},
    {"id": "commit-ef638094...", "sha": "dea088d7cd0c7a44ffb0d8c55a6fbcdcc9b84612",
     "date": "2024-01-01", "subject": "Add the order service"}
  ],
  "lines": [
    "c9be063 2024-01-02 Total, invoice and log in place",
    "dea088d 2024-01-01 Add the order service"
  ]
}
```

`sha` is the full hash and `date` the day it was authored; `lines` abbreviates both for reading.
`subject` is the first line of the commit message.

How far back this goes is the `code_history_depth` setting (200 first-parent commits by default; 0
turns history off), and it is fixed at **clone** time — hippo clones `code_history_depth + 1`
commits, because a shallow clone's oldest commit has no parent to diff against. Raising the setting
therefore only takes effect on the next index of that source. A commit is attributed to a symbol
when its diff touched the symbol's lines *as they were at that commit*, so a function that has since
moved is still credited correctly. Renames are the exception: history before a rename is not carried
across.
