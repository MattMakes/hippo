# R6 — Web surfaces, MCP server, CLI, status, docs conventions

Worker: sonnet-3. Scope: `src/hippo/web/**`, `mcp_server.py`, `status.py`, `model_manager.py`,
`context.py`, `config.py`, `docs/CONTRACTS.md`, `docs/FIDELITY.md`, `docs/MCP.md`, `README.md`,
`tests/unit/test_web_*.py`, `tests/unit/test_mcp_*.py`.

## Verdict table

| id | claim (short) | verdict | key file:line |
|---|---|---|---|
| C1 | A: new `code.py` router "included after `analyze.api`" for a functional reason | Contradicted | `web/app.py:49-61` |
| C2 | Only two node kinds exist today (`entity`, `passage`); no symbol/data/commit | Built (gap) | `hipporag/graph_index.py:31-32,102` |
| C3 | Graph page (routes + JS) hard-codes a binary passage/entity switch, not a kind lookup | Built (gap) | `web/routes/graph.py:81,134,336-358`; `static/graph.js:81,102,134` |
| C4 | Analyze's Cytoscape picture special-cases only `kind="passage"`, everything else = entity style | Built (gap) | `static/analyze.js:29-40` |
| C5 | A: settings.html hard-codes `max="1"` on every float input | Confirmed | `templates/settings.html:73-77` |
| C6 | A: `SETTING_RULES` (per-key min/max) must be added for the template to use | Partial | `store/base.py:24-32` |
| C7 | R6.4: what a new POST JSON endpoint must do to pass the CSRF/host guard | Built | `web/security.py:86-103`; `static/app.js:8-21` |
| C8 | R6.4: how the principal/access is resolved and threaded to search/MCP | Built | `web/auth.py:134-180` |
| C9 | R6.5: MCP has 5 tools today, plain-function pattern, HTTP+stdio transport | Built | `mcp_server.py:111-168,326-377` |
| C10 | R6.6: CLI reaches the store via `AppContext.from_env()`, falls back to `RemoteHippo` when the file is locked; no `path`/`blast`/`raises`/`history` commands yet | Built (gap) | `cli.py:261-276,52-93` |
| C11 | R6.7: status/model_manager expose no grammar/resolver/edge-provenance fields | Missing | `status.py:29-57` |
| C12 | R6.8: CONTRACTS.md format — one path per row inside a fenced block, wrapped continuations | Confirmed | `docs/CONTRACTS.md:338-343` |
| C13 | R6.8: FIDELITY.md has 14 numbered adaptations; a 15th slot is free | Confirmed | `docs/FIDELITY.md:88-162` |
| C14 | R6.2: Ask page has one form field (`question`); no second "paste code/stack trace" textarea | Missing | `templates/ask.html:11-13` |
| C15 | R6.3: Passage dataclass carries no `kind`/`path`/`lines`, only title/text/source/ordinal | Missing | `hipporag/graph_index.py:36-42` |
| C16 | R6.3/R6.5: `Answer` has no `context_block`; nothing prepends a pseudo-passage today | Missing | `hipporag/answerer.py:19` |
| C17 | R6.2: the reindex button lives on the Source page, not the Library row | Confirmed | `templates/source.html:16`; `templates/partials/source_rows.html:30-35` |
| C18 | R6.3: Source page passages are paged with plain `?page=` links, not an HTMX partial swap | Confirmed | `templates/source.html:78-80` |
| C19 | R6.9: `client` fixtures must pass `base_url="http://localhost"` or the host guard 400s every test | Confirmed | `tests/unit/test_web_base.py:27-31` |
| C20 | R6.9: a template-compile test iterates every file under `templates/`, catching Jinja syntax errors only | Confirmed | `tests/unit/test_web_busy_pages.py:25-27` |

## Claims

### C1: A §4.1 — new code router must be "included after `analyze.api`"
**Source:** A §4.1
**Evidence:** `src/hippo/web/app.py:49-61` includes 13 routers in a fixed order, ending
`analyze.router, analyze.api, api.router` then `_mount_mcp(app, ctx)`. No router declares a
catch-all (`{path:path}`) or a path overlapping `/api/code/*` (`grep -n "@router\.\|@api\.\|
APIRouter(" src/hippo/web/routes/*.py`, checked against all 7 route files). `HostAndOriginGuard`
and `AuthGate` are app-level middleware (`app.py:45-46`), not per-router, so include order changes
neither auth nor CSRF behaviour. `docs/CONTRACTS.md:201-205` documents this same order and gives
the real reason files share the `/api` prefix (each builds its own `APIRouter(prefix=...)`), not a
functional dependency between them.
**Verdict:** Contradicted — no mechanism in the current code makes `analyze.api` vs `api.router`
ordering observable; FastAPI only cares about order when two routers can match the same path, and
`/api/code/*` matches nothing else.
**Implication for the plan:** a new `code.py` router can be included anywhere in the
`app.include_router(...)` block, as long as it's before `_mount_mcp(app, ctx)` — the MCP mount is
a catch-all at `/` (`mcp_server.py:336-338`) and must stay last.

### C2: node kinds today are only `entity` and `passage`
**Source:** B §4.1 (Nodes) / B §9 (Graph page "Kind filter gains 'symbol'")
**Evidence:** `src/hippo/hipporag/graph_index.py:31-32,102,134`
```
ENTITY = "entity"
PASSAGE = "passage"
...
    node_kind: list[str]  # vertex index -> "entity" | "passage"
...
        node_kind = [ENTITY] * len(entity_rows) + [PASSAGE] * len(passage_rows)
```
**Verdict:** Built (as a gap) — confirms both A and B are additive here; there is no existing
generic "kind" dispatch to extend, only two literals threaded through 5 files (`grep -rln
"ENTITY\b\|PASSAGE\b" src/hippo`: `evals/question_maker.py`, `analysis/explain.py`,
`web/routes/graph.py`, `hipporag/retriever.py`, `hipporag/graph_index.py`).
**Implication for the plan:** every one of those 5 files, plus the two JS files below (C3, C4),
touches node-kind literals directly (`==`/`!=` comparisons or a ternary), not a lookup table.
Adding `symbol`/`data`/`commit` kinds is a mechanical but wide edit, not a single extension point.

### C3: Graph page hard-codes a binary kind switch (route + JS)
**Source:** B §9 (Graph: "Kind filter gains 'symbol'... node panel for a symbol shows...")
**Evidence:** `src/hippo/web/routes/graph.py:336-358` — `node_details` does
`if index.node_kind[vertex] == PASSAGE: ... else: facts = [f for f in index.facts if node_id in
(f.subject_id, f.object_id)]; out.update(passage_count=..., boost=..., facts=...)`.
`src/hippo/web/static/graph.js:81,134` mirrors it: `n.kind === 'passage' ? COLORS.passage :
COLORS.entity` and the tooltip's `n.kind === 'passage' ? 'passage · ...' : 'entity · in N
passages'`.
**Verdict:** Built (as a gap) — `node_details`'s `else` branch unconditionally treats every
non-passage node as an entity (reads `facts`, `passage_count`, `boost`, none of which a symbol/
data/commit row would have); `graph.js`'s `g-kind` dropdown (`templates/graph.html:44`) offers
only `entity`/`passage`; `nodeColor`/`nodeSize`/`tooltip` all branch on `=== 'passage'` else
entity-shaped text.
**Implication for the plan:** a symbol/data/commit node reaching `/api/graph/node/{id}` today
would be mis-rendered as an entity (wrong tooltip, `passage_count`/`boost` computed from facts
that don't apply). This needs a real kind dispatch in `node_details`, `full_graph`'s node dict
builder (`graph.py:169-186`, same passage/else split), and `graph.js`'s color/size/tooltip/legend
functions and the `g-kind`/`g-color` `<select>` options in `graph.html:44,49`.

### C4: Analyze's Cytoscape picture special-cases only `kind="passage"`
**Source:** B §9 ("Section 3's picture draws STRUCT edges as dashed lines labelled by kind")
**Evidence:** `src/hippo/web/static/analyze.js:29-40`
```
        { selector: 'node', style: { ..., 'background-color': '#c7cbe8', ... } },
        { selector: 'node[kind = "passage"]', style: { shape: 'round-rectangle', ... } },
        ...
        { selector: 'edge[kinds *= "synonym"]', style: { 'line-color': '#9ad0b5', 'line-style': 'dashed' } },
        { selector: 'edge[kinds *= "tuned"]', style: { 'line-color': '#e0a83a' } },
```
**Verdict:** Built (as a gap) — a symbol/data/commit node gets the plain circular default style
(entity-shaped); edges only special-case `synonym` and `tuned` kinds strings, so any new edge kind
(`INVOKES`, `WRITES`, `MODIFIES`, ...) falls through to the plain grey `line-color: '#d4d2cb'` with
no dashing — B's "drawn dashed" claim needs new Cytoscape selectors, none exist for structural
edges today.
**Implication for the plan:** new selectors are additive (Cytoscape ignores unmatched attribute
selectors), so this is low-risk, but the "labelled by kind" behaviour already exists generically
(`label: (e.kinds || []).join('+')`, line 23) — only the colour/dash needs new rules.

### C5: A §3.1 — settings.html hard-codes `max="1"` on float settings
**Source:** A §3.1
**Evidence:** `src/hippo/web/templates/settings.html:73-77`
```
      {% elif value is integer %}
        <input type="number" id="s-{{ key }}" name="{{ key }}" value="{{ value }}" min="0" step="1">
      {% else %}
        <input type="number" id="s-{{ key }}" name="{{ key }}" value="{{ value }}" min="0" max="1" step="0.01">
      {% endif %}
```
**Verdict:** Confirmed — the loop (`pages.py` renders `settings.items()`) branches purely on
Python type (bool / int / else-float), so *every* float setting gets `max="1"` regardless of its
real range.
**Implication for the plan:** A's claim is accurate and the fix generalizes past `code_seed_weight`
— see C6, this is already a live bug for `passage_node_weight` (see gotchas below).

### C6: A §3.1 — settings must take min/max from `SETTING_RULES`
**Source:** A §3.1
**Evidence:** `src/hippo/store/base.py:24-32`
```
SETTING_RULES: dict[str, tuple[type, float | None, float | None]] = {
    "linking_top_k": (int, 0, 100),
    "passage_node_weight": (float, 0.0, 10.0),
    "damping": (float, 0.0, 1.0),
    ...
}
```
**Verdict:** Partial — `SETTING_RULES` **already exists** and is already used server-side by
`validate_settings` (`store/base.py:35-60`, called from the POST `/settings` form, `PUT
/api/settings`, and every simulation path). What's missing is only the template wiring: `settings.
html` never reads `SETTING_RULES`, it infers bounds from the Python value's type instead.
**Implication for the plan:** this is a smaller change than A implies — no new rules registry to
invent, just make `templates/settings.html` (and `pages.py`'s render call) pass `SETTING_RULES[key]`
into the `min`/`max`/`step` attributes instead of switching on `value is integer`.

### C7: R6.4 — what a new POST JSON endpoint must do to satisfy the CSRF/host guard
**Source:** R6.4 (task)
**Evidence:** `src/hippo/web/security.py:86-103`
```
        if method.upper() in SAFE_METHODS:
            return None
        if headers.get("sec-fetch-site", "").lower() == "cross-site":
            return 403, "Refused: this request was sent by another website."
        origin = headers.get("origin") or headers.get("referer")
        if origin and not host_allowed(origin, self.allowed_hosts):
            return 403, f"Refused: {host_name(origin) or origin!r} is not allowed to change this memory."
        return None
```
and `static/app.js:9-12` (`/api/simulate`'s actual call, `static/analyze.js:185`):
```
  async function api(method, url, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    const resp = await fetch(url, opts);
```
**Verdict:** Built — there is **no CSRF token**. The guard is purely header-based: a request with
no `Origin`/`Referer` at all (curl, MCP, `httpx`) passes; a same-origin browser `fetch()` (no
special headers set) passes because the browser's own `Origin`/`Sec-Fetch-Site` match this host.
Confirmed by `tests/unit/test_web_security.py:38-56`, e.g. `guard.reject_reason(method,
headers(host="localhost"))` (no Origin at all) `is None` for every state-changing method.
**Implication for the plan:** a new `POST /api/code/...`-style endpoint needs nothing beyond a
plain `fetch`/`httpx.post`/curl call from an allowed host — no CSRF token to mint or thread through
templates.

### C8: R6.4 — how the principal/access is resolved and passed to search/MCP
**Source:** R6.4 (task)
**Evidence:** `src/hippo/web/auth.py:192-198,161-170`
```
def principal_of(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    ...
def principal_from_bearer(ctx: AppContext, token: str | None) -> Principal | None:
    """The Principal behind a bearer token (MCP, scripts)."""
```
`AuthGate` (ASGI middleware, `auth.py:225-255`) resolves once per request and stores it on
`request.state.principal`; routes call `principal_of(request).access` and pass it straight into
`ask.search`/`ask.ask`/`ctx.graph_for(access)`. `mcp_server.py:78-105`'s `caller()` calls
`principal_from_bearer` with a token read from the MCP `Context.headers` (HTTP) or `HIPPO_TOKEN`
(stdio) — same `Principal`/`Access` object, same `ctx.graph_for(principal.access)` call.
**Verdict:** Built.
**Implication for the plan:** any new code-graph tool (route handler or MCP tool) should follow
the identical pattern — take `principal_of(request).access` / `caller(ctx, mcp_ctx).access` and
hand it to `ctx.graph_for(access)` — no new access machinery needed.

### C9: R6.5 — MCP tool set, schema derivation, and the pattern for adding a tool
**Source:** A §4.2 / B §10
**Evidence:** `src/hippo/mcp_server.py:111-168` (five `@server.tool` closures, each one line:
`return xxx_tool(ctx, ..., principal=caller(ctx, mcp_ctx))`) and `mcp_server.py:326-339` (`mount`)
and `:374-377` (`run_stdio`). `tests/unit/test_mcp_server.py:17` sets
`TOOL_NAMES = {"hippo_search", "hippo_ask", "hippo_remember", "hippo_sources", "hippo_whoami"}`.
`tests/unit/test_mcp_http.py:53-97` drives it over real HTTP with the official MCP client
(`streamable_http_client`), confirming the transport R6.5 asked about.
**Verdict:** Built.
**Implication for the plan:** the pattern for a new tool is: (1) a plain, synchronously-testable
module function `foo_tool(ctx, ..., principal=None)` near the other `*_tool` functions; (2) a
`@server.tool(description=...)` closure inside `build_server` whose body is one line calling it
with `principal=caller(ctx, mcp_ctx)`; ambiguity/refusal is raised as `ToolError` (the one exception
type the MCP client sees verbatim, `mcp_server.py:305-307`). `docs/MCP.md` documents each tool with
one request/response JSON pair per `###` heading (`docs/MCP.md:136-227`) — new tools should follow
that exact shape.

### C10: R6.6 — CLI framework, command list, and how a command reaches the store
**Source:** A §4.3
**Evidence:** `src/hippo/cli.py:261-276`'s `_context_or_running_server()` returns
`(AppContext.from_env(), None)` normally, or `(None, RemoteHippo.for_config(...))` when
`StoreLockedError` is raised and a running server answers. `argparse` with subparsers
(`build_parser`, `cli.py:52-93`); current commands: `serve, mcp, pull-models, index, ask, sources,
settings, users, user {add,token,role,remove}` (`cli.py:101-111`). No `path`/`blast`/`raises`/
`history` subcommands exist yet.
**Verdict:** Built (existing infra) / Missing (the four code commands A proposes).
**Implication for the plan:** new commands follow the existing dual-mode pattern exactly: get
`(ctx, remote) = _context_or_running_server()`, then either call the store/pipeline directly or
call a new `RemoteHippo` method that hits the corresponding `/api/code/...` endpoint. `remote.py`
(135 lines) is a thin `httpx`-based client with one method per server endpoint (`remote.py:78-123`)
— a new `RemoteHippo.path(...)`, `.blast_radius(...)` etc. would be added the same way, each one
calling `self._json(self._client.get/post(...))`.

### C11: R6.7 — what status.py/model_manager.py show today
**Source:** B §9 (Settings: "a 'Code' status card: installed grammars, resolver availability...")
**Evidence:** `src/hippo/status.py:29-57`'s `_compute()` returns only `store`, `store_backend`,
`store_location`, `ollama`, `models`, `models_ready`, `pulling`, `jobs`, `stats`,
`embed_model_built`, `embed_model_mismatch`, `ready`.
**Verdict:** Missing — nothing about tree-sitter grammars, a resolver (pyright/tsserver), or a
per-language edge-provenance mix exists; `_compute()` only knows about the graph store and Ollama.
**Implication for the plan:** a "Code" status card is purely additive: new keys in `_compute()`'s
returned dict (e.g. `"code_grammars": {...}`, `"code_resolvers": {...}`), consumed by a new section
in `settings.html` alongside the existing Ollama/Neo4j cards (`settings.html:8-61`). No existing
key needs to change shape.

### C12: R6.8 — docs/CONTRACTS.md format
**Source:** A §4.6
**Evidence:** `docs/CONTRACTS.md:338-343`, three consecutive rows:
```
Dockerfile               python:3.12-slim, git installed (for repo cloning), pip install ., runs `hippo serve`
docker-compose.yml       services: neo4j (neo4j:5.26-community, ports 127.0.0.1:7474/7687, ...),
                         app (build ., port ${HIPPO_BIND:-127.0.0.1}:8000, depends_on neo4j healthy, ...)
hippo (bash launcher)    ./hippo up | down | logs | pull-models | test ; ...
```
**Verdict:** Confirmed — it is a fenced plain-text block, one left-aligned path/name per row,
continuation lines indented to align under the first column's text (not a markdown table), grouped
under `### <area>` headings (`mcp_server.py`/`cli.py` share one heading at line 313, `web/` gets
its own at line 184). `mcp_server.py`'s own entry (`CONTRACTS.md:316-329`) already documents the
5-tool contract with the same one-line-per-tool sub-indent style.
**Implication for the plan:** new contract entries (store methods, `GraphIndex` fields, routes,
MCP tools, CLI commands) should be appended inside the existing fenced blocks for
`src/hippo/web/`, `mcp_server.py`/`cli.py`, and a new one for `codegraph/`/`anchors.py`/`paths.py`
if those become their own `###` section, matching this exact indentation convention.

### C13: R6.8 — docs/FIDELITY.md section structure and numbering
**Source:** A §4.6
**Evidence:** `docs/FIDELITY.md:88-98,159-162` — 14 numbered items under `## Adaptations`, each
`N. **Title.** <reference behaviour> hippo <adaptation>. Reason: ...` (see item 1, lines 90-98,
and the most recent item 14, lines 159-162, "Synonym gate counts Unicode letters").
**Verdict:** Confirmed — A's plan to add "adaptation 15, Code graph" is exactly the next free
number; the file has no per-feature subsection today, only this flat numbered list plus the
"Exact matches" section above it (`FIDELITY.md:9-86`, itself organized as `### <area> (<hippo
file> vs <reference file>)`).
**Implication for the plan:** a "Code graph" fidelity entry fits as item 15 in the existing flat
list (following the same `**Bold title.** reference / hippo / Reason:` shape), not as a new
`##`-level section — there is no precedent for that in the file.

### C14: R6.2 — Ask page form fields
**Source:** B §9 ("Ask: a second textarea 'Paste code / stack trace / diff (optional)'")
**Evidence:** `src/hippo/web/templates/ask.html:11-13`
```
<form class="ask-form card" hx-post="/ask" hx-target="#answer" hx-swap="innerHTML" ...>
  <textarea id="question" name="question" rows="2" ...>{{ question }}</textarea>
```
**Verdict:** Missing — exactly one form field (`question`) exists today; B's second textarea is
not built.
**Implication for the plan:** `pages.py`'s `ask_submit` (`pages.py:71-102`) would need a second
`Form(...)` parameter and a way to fold it into the anchors search (A's `find_anchors` takes
`question` alone today).

### C15: R6.3 — Passage's fields (kind/path/lines)
**Source:** Task gotcha list ("templates that switch on Source.kind or Passage fields")
**Evidence:** `src/hippo/hipporag/graph_index.py:36-42`
```
class Passage:
    id: str
    title: str
    text: str
    source_id: str
    source_name: str
    ordinal: int
```
**Verdict:** Missing — no `kind`, `path`, or `lines` field. A's design bakes this into the `title`
string (`"path :: qualname (lines a-b)"`); B's Source-page "Symbols" tab wants them as structured
columns (kind, path, degree, specificity), which the `Passage` dataclass cannot supply today.
**Implication for the plan:** this is the concrete place A and B diverge in a way that affects the
UI directly — if code passages only carry a formatted title (A), the Source page's passage list
(`source.html:83-96`) needs string-parsing or a template filter to show kind/path/lines as
separate cells; if `Passage` gains real fields (implied by B), every `Passage(...)` construction
site and `trace_from_dict`/`RankedPassage` round-trip needs the new fields defaulted for old traces
to keep loading (same rule the code already follows for `RankedPassage.community_boosted` in A
§3.4).

### C16: R6.5 — Answer's context_block / pseudo-passage
**Source:** A §3.5
**Evidence:** `src/hippo/hipporag/answerer.py:19` (`class Answer:` — fields checked; no
`context_block` present) and `templates/partials/answer.html` (no code-graph card block).
**Verdict:** Missing — confirms A's plan is additive here with nothing to reconcile against.
**Implication for the plan:** `Answer` needs the new field defaulted (`context_block: str = ""`)
so `Answer(**old_dict)` still loads for stored eval results (same defaulting pattern discussed in
C15).

### C17: R6.2 — where the reindex button lives
**Source:** Task R6.2 ("Note the source page's reindex button endpoint")
**Evidence:** `src/hippo/web/templates/source.html:16`
```
<button class="btn" data-post="/api/sources/{{ source.id }}/reindex" data-message="Re-indexing" data-refresh="800" {% if busy %}disabled{% endif %}>Reindex</button>
```
The Library's per-row table (`partials/source_rows.html:30-35`) only offers "Ask" and "Delete" —
no Reindex button there.
**Verdict:** Confirmed.
**Implication for the plan:** a "Reindex changed files" button (B §9) would sit next to this one
button on the Source page, not on the Library rows; it should reuse the `data-post`/`data-message`/
`data-refresh` convention already there (a plain `hippo.js` `data-*` attribute handler, see
`static/app.js`'s comment block at the top, lines 1-6).

### C18: R6.3 — Source page passage pagination
**Source:** Task R6.3 ("For the Source page: how passages are listed (pagination? partial?)")
**Evidence:** `src/hippo/web/templates/source.html:78-80`
```
    {% if pages > 1 %}<span class="row muted">page {{ page }} of {{ pages }}
      {% if page > 1 %}<a class="btn small" href="?page={{ page - 1 }}">←</a>{% endif %}
      {% if page < pages %}<a class="btn small" href="?page={{ page + 1 }}">→</a>{% endif %}</span>{% endif %}
```
**Verdict:** Confirmed — plain full-page navigation via `?page=N` query params
(`routes/sources.py:119-147`, `PASSAGES_PER_PAGE = 25`), not an HTMX partial swap. Only the status
card on that page polls via HTMX (`hx-get="/partials/sources/{{ source.id }}/status" hx-trigger=
"every 2s"`, line 51).
**Implication for the plan:** a Symbols/Unresolved tab (B §9) on the same page can follow either
convention already on the page — full-page links like the passage pager, or an HTMX-polled partial
like the status card — there is no single house convention to match, both exist side by side.

### C19: R6.9 — building the test client, and a host-guard trap
**Source:** Task R6.9
**Evidence:** `tests/unit/test_web_base.py:27-31`'s `client` fixture wraps
`TestClient(create_app(ctx), base_url="http://localhost")`; every `client` fixture across
`test_web_*.py`/`test_web_busy_pages.py` repeats this exact `base_url` (e.g.
`test_web_busy_pages.py:19-21`). Logins use `client.post("/login", data={"username": ...,
"password": ...})`; HTMX partials are hit by GETting the partial path directly, and the
"strangers redirected" case adds `headers={"HX-Request": "true"}` (`test_web_auth.py:111`) to
assert an `HX-Redirect` header instead of a 303.
**Verdict:** Confirmed.
**Implication for the plan:** any new test file for code routes must copy the
`base_url="http://localhost"` fixture verbatim — the default `TestClient` sends `Host: testserver`,
which `HostAndOriginGuard` refuses with a 400 exactly like a foreign site (`security.py:88-93`).
This is not documented anywhere except by convention in every existing test file.

### C20: R6.9 — test_web_busy_pages.py and the template-compile test
**Source:** Task R6.9 ("what 'busy' means for pages during indexing")
**Evidence:** `tests/unit/test_web_busy_pages.py:25-27`'s `test_every_template_compiles()` loads
every file under `TEMPLATES_DIR` through Jinja. "Busy" means a source `status in ("queued",
"reading", "indexing")`, a model pull in progress (`ctx.models.progress[...]` with `done=False`),
or a running eval — the assertion is that pages still return 200 and render placeholder data
(`pct`/`fmt` filters over `None`/`Undefined`) without crashing, per the module docstring's own war
story about `run.summary.accuracy` on an empty summary (lines 1-7).
**Verdict:** Confirmed.
**Implication for the plan:** `test_every_template_compiles` automatically catches a Jinja syntax
error in any new template but says nothing about content correctness; new code-page tests should
add their own busy-state case to this file's pattern rather than a new one.

## Surprises and gotchas for the synthesizer

1. **`settings.html`'s `max="1"` bug already bites today**, not just in the future: the settings
   loop (`settings.html:73-77`) gives `passage_node_weight` — whose `SETTING_RULES` range is
   `(float, 0.0, 10.0)` (`store/base.py:26`) — a browser-enforced `max="1"` right now. Fixing the
   template to use `SETTING_RULES` (needed for `code_seed_weight` per A §3.1) will also fix a
   latent bug unrelated to code. Worth calling out explicitly since it's not something A or B
   attributes to the code work.

2. **README.md already has a stale tool count.** `README.md:228` says "`mcp_server.py` the four
   MCP tools", but there are five (`hippo_search`, `hippo_ask`, `hippo_remember`, `hippo_sources`,
   `hippo_whoami` — confirmed by `README.md:156-157`, `docs/MCP.md`'s own "## The five tools"
   heading, and `TOOL_NAMES` in `test_mcp_server.py:17`). Whoever writes the "nine tools" language
   for phase 1 (A §4.6) should fix this existing drift in the same edit, or the doc will say "four"
   in one place and list nine tools two paragraphs later.

3. **Adding new node kinds touches a small, enumerable set of files** (5 Python files via
   `ENTITY`/`PASSAGE` imports: `evals/question_maker.py`, `analysis/explain.py`,
   `web/routes/graph.py`, `hipporag/retriever.py`, `hipporag/graph_index.py`, plus 2 JS files that
   spell `'passage'`/`'entity'` as string literals: `static/graph.js`, `static/analyze.js`). None
   dispatch through a registry — every check is a literal `==`/`!=`/ternary. This is mechanical but
   genuinely wide; a symbol/data/commit kind that skips any of the 7 files renders as a
   mis-labelled entity rather than failing loudly. In particular, `node_details`'s else-branch
   (`graph.py:346-358`) silently assumes "not passage" means "entity" and reads
   `facts`/`passage_count`/`boost` unconditionally — a symbol node hitting this endpoint today
   would not error, it would return an entity-shaped response with wrong/empty fields (see C3, C4).

4. **The CSRF/host guard has no notion of "JSON API" vs "form post"** — it is pure header
   inspection independent of content type, so nothing about a new `/api/code/*` endpoint needs
   special handling versus the existing form-posting routes. The one thing to get right is that
   *tests* must supply `base_url="http://localhost"` (C19) — this has bitten every existing test
   file and would bite a fresh `test_web_code.py` the same way if copied from a template missing it.

5. **`docs/CONTRACTS.md`'s house style note (lines 15-16)** requires tests "on LadybugDB, the fake
   and real Neo4j in CI via the `store` fixture" for any store-touching package — applies to a new
   `store/code.py` (out of this worker's scope), not to `test_web_code.py`/`test_mcp_server.py`
   additions, which exercise the web/MCP layer only.

6. **`web/app.py`'s own docstring states the one ordering rule that does matter**: the MCP mount
   must be last because it's a catch-all at `/` (`app.py:62`, `mcp_server.py:336-338`) — in
   contrast to C1's not-actually-order-dependent claim about `analyze.api`.
