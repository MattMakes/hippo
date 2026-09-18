# QA1F — Fix the two things the real-model smoke found

Read `impl/00-impl-context.md` first. Worktree `.worktrees/qa1f`, branch `wp/qa1f`, from the CURRENT tip
of `code-graph`. Neo4j test container: name `hippo-neo4j-qa1f`, port **17688**. Capture pytest exit
codes to a file (`> /tmp/qa1f-<leg>.log 2>&1; echo EXIT $?`), never through `| tail`.

Spec: `docs/plans/hippo-for-code/research/QA1-real-model-smoke.md` §Defects (defect 1, with its exact
reproduction) and §Surprises (the `/api/ask` gap). Two changes, each with a test.

## 1. `paths.code_paths_for` orders edges by relevance before the character cut

Today: pairwise shortest paths between seeds, then each seed's `direct_edges` in a fixed
out-then-in order, then `render_block`/`cut_to` truncates at `code_triples_chars`. A well-connected
function's own outgoing calls always precede its callers, so "where is `find_anchors` called" lost the
one INVOKES in-edge that answers it, one line past the cut.

Do this: keep the pairwise-path edges first (they connect seeds to each other), then emit each seed's
direct edges **sorted by ω descending, interleaving in and out edges at equal ω (in first)**, and dedupe
identical `(a, b, kind)` triples across seeds and across duplicate indexed copies. Every seed's edges
are still interleaved by seed weight order, not seed-by-seed exhaustion: round-robin one edge per seed
until the budget is spent, so the top seed cannot starve the others. Document the order in the
docstring. Then: `test_paths.py` gets the smoke's shape (a symbol with 10 out-edges at 0.90-1.00 and one
in-edge INVOKES at 0.90, `code_triples_chars` sized so only ~6 lines fit → the in-edge is inside the
cut); `test_ask.py`'s `CODE_BLOCK_BODY` will change — regenerate it, READ the new block line by line and
confirm every line is a real edge of the fixture in the new order, and say in the ledger what moved.
The `Tests:`/`Commits:`/`Subsystems:` sections and the `… (+N more)` line are unchanged.

## 2. `/api/ask` (and `/api/search` if it lacks them) return the code fields the MCP tools return

WP4a's `ask_tool`/`search_tool` return `seed_symbols`, `paths`, `tests`, `history`, `code_graph`
(`answer.context_block` for ask; `ask.code_block(graph, trace)` for search). The HTTP `/api/ask`
omits `context_block`. Add the same five keys to the HTTP JSON (always present, empty on prose), built
by the same helper the MCP tools use so the two cannot drift; the Ask page already renders
`answer.context_block`, so only the JSON route changes. Extend `test_web_analyze.py` / the API test
that covers `/api/ask` with a code question over `code_index` asserting the keys, and a prose question
asserting they are empty. Update the `routes/api.py` row in `docs/CONTRACTS.md` (the packaging test
pins the route map).

## Done when

Three stores + lint green, no pinned assertion weakened except the regenerated `CODE_BLOCK_BODY`,
ledger summary, `horch tell orchestrator "[<role>] DONE: wp/qa1f ..."`, close pane.
