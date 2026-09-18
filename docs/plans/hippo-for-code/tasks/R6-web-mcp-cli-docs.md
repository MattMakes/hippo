# R6 — Web surfaces, MCP server, CLI, status, docs conventions (worker: sonnet-3)

Read `00-shared-context.md` first. Output file: `docs/plans/hippo-for-code/research/R6-web-mcp-cli-docs.md`.

Files in scope: `src/hippo/web/**` (app.py, auth.py, security.py, render.py, adhoc.py, routes/*.py, templates/**,
static/** if present), `src/hippo/mcp_server.py`, `src/hippo/status.py`, `src/hippo/model_manager.py`,
`src/hippo/context.py`, `src/hippo/config.py`, `tests/unit/test_web_*.py`, `tests/unit/test_mcp_*.py`,
`docs/CONTRACTS.md`, `docs/FIDELITY.md`, `docs/MCP.md`, `README.md`.

- **R6.1** App wiring. `web/app.py`: how routers are included and in what order (A §4.1 says a new
  `web/routes/code.py` with `APIRouter(prefix="/api/code")` must be "included after `analyze.api`" — why would
  order matter? find the reason: catch-all routes, auth dependencies, CSRF middleware?). List every router
  and its prefix.
- **R6.2** Routes inventory. For each of `routes/pages.py`, `sources.py`, `analyze.py`, `graph.py`, `api.py`,
  `evals.py`, `users.py`: list endpoints (method, path, handler name, template or JSON). Mark which are HTMX
  partials. Note the source page's reindex button endpoint and the Ask page's form fields.
- **R6.3** Templates. List the templates directory tree. For `settings.html`: quote one setting input and
  confirm/refute A's claim that `max="1"` is hard-coded. For the Analyze template: how the subgraph picture
  is drawn (Cytoscape? which JSON shape? how `kinds` map to styles), how the Tweak panel posts simulations.
  For the Graph page (`/graph`): 3d-force-graph? how node kinds are filtered, how edge types are styled.
  For the Source page: how passages are listed (pagination? partial?). For the Library page: repo row fields.
- **R6.4** Security. `web/security.py` (CSRF/Host guard from commit f65afe2): what a new POST JSON endpoint
  must do to pass (headers? token?), and how the existing `/api/simulate` calls satisfy it (quote the JS or
  form attribute). `web/auth.py`: how the current user and `access` are resolved per request and passed to
  `ask.search` / `GraphIndex.scoped()`.
- **R6.5** MCP. `mcp_server.py`: the five tools (names, argument schemas, how `access`/scoping is derived),
  the pattern for adding a tool, the transport (`test_mcp_http.py` implies HTTP). `docs/MCP.md`: what it
  documents and its format, so new tools can be added in the same style.
- **R6.6** CLI. `cli.py`: framework and command list; how a command reaches the store/pipeline (via
  `context.py`?). `remote.py`: what it is (A §4.3 "CLI + remote").
- **R6.7** Status. `status.py` and `model_manager.py`: what the Settings/status card shows today (models
  pulled? store health?) and where "installed grammars / resolver found" would be computed.
- **R6.8** Docs conventions. `docs/CONTRACTS.md`: quote 3 consecutive rows to capture the exact format
  (path, signature, one-line contract). `docs/FIDELITY.md`: section structure and the "Adaptations" style.
  README: which sections ("A tour", "How it works", "Where the code lives", "Configuration") would need a
  code-sources paragraph, with line numbers.
- **R6.9** Web tests. `test_web_*.py`: how they build the app client (TestClient? fixtures?), how they log in,
  how they hit HTMX partials; `test_web_busy_pages.py` (what "busy" means for pages during indexing).

Gotchas to look for: templates that switch on `Source.kind` or `Passage` fields (would need `kind`/`path`/`lines`),
JS that hard-codes edge type lists or colours, and any route that enumerates entity "kinds".
