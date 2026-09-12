# Low-level graph/session call-site audit (activation Task 4)

Produced for activation Task 4a on `wp/pa4a`, base `rag-it-all-tibs` `043ca51`. It answers the
plan's requirement that "the low-level graph/session call-site audit has no unclassified production
caller" and the PA8 criterion that the `rg` sweep is attached to review with every production call
classified.

> **Refreshed 2026-09-12 at HEAD `c893a95`** (branch `rag-it-all-tibs`, worktree `wp/pa8close`),
> closing PA8 sign-off finding **S1**. The three sweep commands below were re-run at that commit and
> every row re-resolved to its enclosing symbol; the result is
> ["The sweep re-run at `c893a95`"](#the-sweep-re-run-at-c893a95), which is the **current** table and
> carries current line numbers. Sections 1–8 below it are the `043ca51` record and are kept
> unchanged: they are organised by *which slice would convert a caller*, which only means something
> at the commit they were written for. Their `file:line` values are historical and the refresh
> section maps each surviving row to its line at `c893a95`.

## How the list was produced

```
rg -n 'query_session\(|query_access\(|graph_for\(|ctx\.graph\(' src/hippo          # 68 rows, the PA8 pattern
rg -n --no-heading -g '*.py' '\bctx\.graph\(\)|self\.ctx\.graph\(\)' src/hippo     # 2 rows
rg -n --no-heading -g '*.py' 'retrieval_session\(|dense_session\(' src/hippo       # 2 rows, both definitions
```

The tables below are the union, deduplicated, with the definition sites of the primitives kept so
that no `rg` row looks unaccounted for. Two rows are prose in a module docstring, not calls; they
are listed under "Not calls" rather than dropped.

**Baseline fact:** at `043ca51` there is no production caller of `retrieval_session` or
`dense_session` anywhere under `src/hippo` — the dispatcher reviewed in Task 2 is reachable only
from tests. `ask.py` becomes its first production caller in this slice (4a); every other
model/dense owner in the table below is still on a raw `query_session` and is converted by 4b/4c/4d.

**`ctx.graph_for(..., structural=False)` stays the explicit low-level legacy default** (plan,
"Production query-session activation"). Only `query_access`/`query_session` flip. Therefore the
`context.py` rows are infrastructure, not owners.

## Class legend

| Class | Meaning |
|---|---|
| `4a-converted` | Changed in this slice. |
| `model/dense` | Embeds a query or scores dense candidates; must dispatch through `retrieval_session` over its one held owner. Named part converts it. |
| `graph-only` | Graph/source/citation/status/code/user-view evidence only; holds one structural `query_session` through DTO/render/save. Named part converts (or confirms) it. |
| `compat/test` | Documented compatibility path that may keep `structural=False`. |
| `admin` | Administrative store operation, not query evidence. |
| `infrastructure` | The primitive's own definition or internal plumbing, not a caller. |
| `not-a-call` | Prose in a docstring matched by the pattern. |

## The sweep re-run at `c893a95`

2026-09-12, worktree `.worktrees/pa8close` at `c893a95`, all three commands above run verbatim:

```
rg -n 'query_session\(|query_access\(|graph_for\(|ctx\.graph\(' src/hippo          # 58 rows
rg -n --no-heading -g '*.py' '\bctx\.graph\(\)|self\.ctx\.graph\(\)' src/hippo     # 1 row
rg -n --no-heading -g '*.py' 'retrieval_session\(|dense_session\(' src/hippo       # 8 rows (2 defs, 6 callers)
```

Raw output: `/tmp/hippo-pa8close-sweep1.log`, `/tmp/hippo-pa8close-sweep2.log`,
`/tmp/hippo-pa8close-sweep3.log`. Every row was resolved to its enclosing `def`/`class` rather than
read off the old table, so the line numbers here are the ones at `c893a95`.

**Unclassified production callers: 0.** The classes are the ones the PA8 criterion needs — who owns
a session, who borrows one, and what is not a call at all — not the 4a-era "which slice converts
this" classes of section 1 below.

| Class | Rows |
|---|---|
| Not a call, or the primitives' own definitions and plumbing | 11 |
| The dispatcher's own acquisition | 1 |
| Borrow-or-acquire (uses the caller's session, acquires only when none is passed) | 3 |
| Production `query_session` owner, one session per operation | 42 |
| Raw unrestricted `ctx.graph()` on a request path | 1 |
| **Total / unclassified** | **58 / 0** |

### Not a call, or the primitives' own definitions and plumbing (11)

| File:line | Symbol | Note |
|---|---|---|
| `src/hippo/context.py:8` | module docstring | "`graph()` is the whole graph; `graph_for(access)` is the part a user may see". Prose. |
| `src/hippo/context.py:117` | `AppContext.graph_for` def | Keeps `structural: bool = False`, the explicit low-level legacy default the plan requires. |
| `src/hippo/context.py:129` | `AppContext.graph_for` | Forwards to `_graph_for`. |
| `src/hippo/context.py:170` | `AppContext._graph_for` def | Same default. |
| `src/hippo/context.py:184` | `AppContext._graph_for` | Dispatch to the generation-aware loader. Was `:180` at `1e2f112`; the code-capture slice added the comment above it. |
| `src/hippo/context.py:205` | `AppContext._managed_graph_for` def | Was `:201` at `1e2f112`, same cause. |
| `src/hippo/knowledge/query_access.py:75` | `query_access` def | `structural: bool = True`. |
| `src/hippo/knowledge/query_access.py:85` | `query_access` | The structural branch. |
| `src/hippo/knowledge/query_access.py:87` | `query_access` | The legacy branch, reached only by an explicit `structural=False`. |
| `src/hippo/knowledge/query_access.py:126` | `query_session` def | `structural: bool = True`. |
| `src/hippo/knowledge/query_access.py:136` | `query_session` | Forwards `structural=structural` verbatim. |

### The dispatcher's own acquisition (1)

| File:line | Symbol | Note |
|---|---|---|
| `src/hippo/knowledge/dense_session.py:201` | `_session` | The one place a dense/model path may acquire an owner; every `retrieval_session`/`dense_session` caller goes through it. |

### Borrow-or-acquire (3)

| File:line | Symbol | Note |
|---|---|---|
| `src/hippo/status.py:47` | `source_view` | Uses `session.graph` when the caller holds one, and acquires `ctx.graph_for(access, structural=True)` only when it does not. |
| `src/hippo/status.py:271` | `_audience_inventory` | Acquires its own structural `query_session`. Was `:263` at `1e2f112`. |
| `src/hippo/web/render.py:185` | `render` | Acquires an owner only when the caller did not supply one. |

### Production `query_session` owners, one session per operation (42)

| File:line | Symbol | Surface |
|---|---|---|
| `src/hippo/mcp_server.py:362` | `search_tool` | MCP, inside `_answering()` |
| `src/hippo/mcp_server.py:400` | `ask_tool` | MCP, inside `_answering()` |
| `src/hippo/mcp_server.py:423` | `_code_graph` | MCP, the four code tools' single owner |
| `src/hippo/mcp_server.py:539` | `sources_tool` | MCP source listing |
| `src/hippo/knowledge/eval_access.py:137` | `read_scope` | Evaluation reads |
| `src/hippo/knowledge/eval_access.py:163` | `_creation_scope` | Evaluation creation; the lower `query_access` on purpose (a mutation bumps the epoch, so no heartbeat may join while the lock is held) |
| `src/hippo/knowledge/changeset_access.py:49` | `read_scope` | Changeset listing |
| `src/hippo/knowledge/changeset_access.py:70` | `_mutation_scope` | Same `query_access` reason as the evaluation creation scope |
| `src/hippo/cli.py:399` | `cmd_ask` | Local CLI `hippo ask`; dispatches through `retrieval_session` |
| `src/hippo/cli.py:451` | `_code_locally` | Local CLI code listing. Converted from the raw `ctx.graph()` section 4 recorded |
| **`src/hippo/cli.py:567`** | **`_sources_locally`** | **Local CLI source listing — finding S1's row.** Converted from a raw unrestricted `store.list_sources()`, which is why it matched no pattern at `043ca51` and so had no row. It holds one structural `query_session`, reads `status.source_view` from it and calls `view.validate()` before returning: exactly the plan's "Local CLI code and source listing" bullet |
| `src/hippo/evals/question_maker.py:95` | `generate_questions` | Question-maker passage reads; graph evidence only, no query embedding |
| `src/hippo/evals/runner.py:106` | `_run_all` | The runner's outer owner for a whole question set |
| `src/hippo/web/routes/analyze.py:64` | `analyze_adhoc` | HTTP |
| `src/hippo/web/routes/analyze.py:135` | `analyze_result` | HTTP |
| `src/hippo/web/routes/analyze.py:263` | `changesets_page` | HTTP page |
| `src/hippo/web/routes/graph.py:184` | `graph_page` | HTTP page, guarded by `ctx.store.ping()` |
| `src/hippo/web/routes/graph.py:239` | `full_graph` | HTTP |
| `src/hippo/web/routes/graph.py:496` | `node_details` | HTTP |
| `src/hippo/web/routes/code.py:189` | `_graph` | Every code endpoint's single owner |
| `src/hippo/web/routes/users.py:88` | `ladder` | HTTP |
| `src/hippo/web/routes/users.py:119` | `users_page` | HTTP page |
| `src/hippo/web/routes/users.py:289` | `list_users` | HTTP |
| `src/hippo/web/routes/users.py:300` | `list_roles` | HTTP |
| `src/hippo/web/routes/users.py:364` | `patch_user` | Mutation; the session exists for the user/source view it returns |
| `src/hippo/web/routes/users.py:435` | `patch_role` | Same |
| `src/hippo/web/auth.py:348` | `account_page` | HTTP page |
| `src/hippo/web/auth.py:401` | `me` | HTTP |
| `src/hippo/web/routes/sources.py:93` | `library` | HTTP page, guarded by `ctx.store.ping()` |
| `src/hippo/web/routes/sources.py:118` | `sources_partial` | HTTP partial |
| `src/hippo/web/routes/sources.py:149` | `visible_source` | HTTP |
| `src/hippo/web/routes/sources.py:172` | `source_page` | HTTP page |
| `src/hippo/web/routes/sources.py:260` | `code_details_for` | HTTP |
| `src/hippo/web/routes/sources.py:314` | `source_status_partial` | HTTP partial |
| `src/hippo/web/routes/sources.py:478` | `list_sources` | HTTP |
| `src/hippo/web/routes/sources.py:547` | `reindex_all` | The bulk route. Section 3's bold "no session today" row: it now holds one owner across the inventory, the pipeline call and the post-operation `validate()` (PA2 finding 3) |
| `src/hippo/web/routes/api.py:119` | `ask` | HTTP; the inner `ask_service.ask` re-wraps with `retrieval_session` |
| `src/hippo/web/routes/api.py:150` | `search` | HTTP, same shape |
| `src/hippo/web/routes/api.py:177` | `entities` | HTTP |
| `src/hippo/web/routes/api.py:198` | `neighborhood` | HTTP |
| `src/hippo/web/routes/pages.py:91` | `ask_page` | HTTP page, guarded by `ctx.store.ping()` |
| `src/hippo/web/routes/pages.py:148` | `ask_submit` | HTML Ask form |

### Raw unrestricted `ctx.graph()` on a request path (1)

| File:line | Symbol | Note |
|---|---|---|
| `src/hippo/knowledge/changeset_access.py:170` | `apply` | `set(self.ctx.graph().node_ids)` inside `_mutation_scope`, used only to refuse a managed evidence identity as a legacy edit target. The single remaining `ctx.graph()` under `src/hippo`; classified here as a deliberate non-evidence read, and the subject of PA4d finding 2. |

### What moved between `043ca51` and `c893a95`

- **`ask.py`, `analysis/simulate.py` and `evals/rag_all.py` no longer match the pattern**: they
  dispatch through `dense_session.retrieval_session`. The audit's baseline fact ("no production
  caller of `retrieval_session` or `dense_session` anywhere under `src/hippo`") is now false by
  design — sweep 3 returns the two definitions plus six production callers: `ask.py:68`,
  `evals/runner.py:164`, `analysis/simulate.py:160`, `evals/rag_all.py:388`,
  `web/routes/analyze.py:312`, `web/routes/graph.py:406`.
- **`cli.py:567 _sources_locally` gained a row** (finding S1); `cli.py:451 _code_locally` replaced
  section 4's raw `ctx.graph()`, so sweep 2 falls from 2 rows to 1.
- **`sources.py:547 reindex_all` gained a session**, which is what section 3's bold row asked for.
- **`code.py` and `graph.py`'s module docstrings no longer match**, so section 6's two "stale after
  4b converts the route" rows resolved themselves; section 6 keeps only the `context.py` docstring.
- **`context.py:184`/`:205` and `status.py:271` moved by a few lines** at `c893a95` relative to
  `1e2f112`, from the code-capture slice's comments in `_graph_for`. No row changed class.

## 1. Converted in 4a — the `043ca51` record

| File:line | Symbol | Class | Note |
|---|---|---|---|
| `src/hippo/knowledge/query_access.py:75` | `query_access` def | `4a-converted` | Signature default becomes `structural=True`. |
| `src/hippo/knowledge/query_access.py:79` | `query_access` | `infrastructure` | Structural branch: `ctx.graph_for(..., structural=True)`. |
| `src/hippo/knowledge/query_access.py:81` | `query_access` | `compat/test` | Legacy branch, reached only by an explicit `structural=False`. |
| `src/hippo/knowledge/query_access.py:109` | `query_session` def | `4a-converted` | Signature default becomes `structural=True`. |
| `src/hippo/knowledge/query_access.py:115` | `query_session` | `infrastructure` | Now forwards `structural=structural` verbatim, so an explicit `False` survives (it did not before: the old `**({"structural": True} if structural else {})` dropped the keyword and let `query_access`'s own default decide, which would have silently forced structural on every opt-out once the default flipped). |
| `src/hippo/ask.py:41` | `search` | `4a-converted` / `model/dense` | Now `_retrieval_scope`. |
| `src/hippo/ask.py:48` | `_query_session` | `4a-converted` / `model/dense` | Replaced by `_retrieval_scope`, which owns or borrows through `retrieval_session`. |
| `src/hippo/ask.py:55` | `_query_session` | `4a-converted` / `model/dense` | The bare `query_session(...)` acquisition is gone. |
| `src/hippo/ask.py:96` | `ask` | `4a-converted` / `model/dense` | |
| `src/hippo/ask.py:113` | `answer_from_trace` | `4a-converted` / `model/dense` | Answer-only, but it re-reads the trace's graph and may reconstruct it, so it takes the same dispatched owner. |

## 2. Model/dense owners still to convert

| File:line | Symbol | Owner | Note |
|---|---|---|---|
| `src/hippo/web/routes/api.py:78` | `ask` | 4b web | HTTP `/api/ask`. Passes its session to `ask_service.ask`; once 4a lands, the inner call re-wraps with `retrieval_session`, so 4b only has to hold a structural owner and map failures. |
| `src/hippo/web/routes/api.py:104` | `search` | 4b web | HTTP `/api/search`, same shape. |
| `src/hippo/web/routes/pages.py:111` | `ask_submit` | 4b web | HTML Ask form; currently renders `str(exc)` for `OllamaError` (`pages.py:114`), which the 4a mapper replaces with `retrieval_unavailable`. |
| `src/hippo/web/routes/graph.py:328` | `light_up` | 4b web | Graph light-up runs a real search over the held session. |
| `src/hippo/web/routes/analyze.py:55` | `analyze_adhoc` | 4b web | Recalls a cached ad-hoc analysis; no model call on the cached path, but the same route re-runs the retriever on the miss branch, so it takes the dense owner. |
| `src/hippo/web/routes/analyze.py:108` | `analyze_result` | 4b web | Replays a stored result; `reconstruct_trace`/`can_reuse_answer` run against the held graph and the render path can re-score. |
| `src/hippo/web/routes/analyze.py:270` | `simulate` | 4b web | Calls `analysis.simulate.simulate(session=...)`, which embeds and re-ranks. |
| `src/hippo/analysis/simulate.py:149` | `simulate` | 4d analysis | Owns a session only when none is borrowed; both branches feed `Retriever`. |
| `src/hippo/mcp_server.py:278` | `search_tool` | 4c MCP | |
| `src/hippo/mcp_server.py:316` | `ask_tool` | 4c MCP | |
| `src/hippo/cli.py:233` | `cmd_ask` | 4c CLI | Local `hippo ask`; unrestricted access (`query_session(ctx)`), still a dense dispatch. |
| `src/hippo/evals/runner.py:95` | `_run_all` | 4d evals | The evaluation runner's outer owner for a whole question set. |
| `src/hippo/evals/runner.py:141` | `run_question` | 4d evals | Borrows the runner's owner or acquires its own. |
| `src/hippo/evals/rag_all.py:386` | `evaluate` | 4d evals | The static RAG-all evaluator. |

## 3. Graph / source / citation / status / code-only owners

| File:line | Symbol | Owner | Note |
|---|---|---|---|
| `src/hippo/status.py:46` | `source_view` | 4b (released by Task 2) | Already `ctx.graph_for(access, structural=True)` when no session is borrowed. Remains an explicit structural acquisition rather than a `query_session`, so 4b decides whether the fallback acquisition survives at all. |
| `src/hippo/status.py:242` | `_audience_inventory` | 4b (released by Task 2) | Already `query_session(..., structural=True)`; the explicit keyword becomes redundant after 4a but is left in place (not this slice's file). |
| `src/hippo/web/routes/sources.py:69` | `library` | 4b web | Guarded by `ctx.store.ping()`; graph-only. |
| `src/hippo/web/routes/sources.py:94` | `sources_partial` | 4b web | |
| `src/hippo/web/routes/sources.py:125` | `visible_source` | 4b web | |
| `src/hippo/web/routes/sources.py:148` | `source_page` | 4b web | |
| `src/hippo/web/routes/sources.py:236` | `code_details_for` | 4b web | |
| `src/hippo/web/routes/sources.py:290` | `source_status_partial` | 4b web | |
| `src/hippo/web/routes/sources.py:438` | `list_sources` | 4b web | |
| **`src/hippo/web/routes/sources.py` `reindex_all`** | (no session today) | **4b web** | Carried from `task4-notes.md`: `reindex_all` calls `source_view(ctx, access)` and then `view.validate()` *after* `pipeline.reindex_all`, i.e. it validates a view it does not hold. It has no row in the `rg` sweep precisely because it holds no session; 4b must give it one held owner across the pipeline call. Listed here so the audit is not silent about it. |
| `src/hippo/web/routes/graph.py:145` | `graph_page` | 4b web | |
| `src/hippo/web/routes/graph.py:190` | `full_graph` | 4b web | |
| `src/hippo/web/routes/graph.py:418` | `node_details` | 4b web | |
| `src/hippo/web/routes/api.py:129` | `entities` | 4b web | |
| `src/hippo/web/routes/api.py:150` | `neighborhood` | 4b web | |
| `src/hippo/web/routes/pages.py:90` | `ask_page` | 4b web | Renders the form and the scope note; no model call. |
| `src/hippo/web/routes/analyze.py:233` | `changesets_page` | 4b web | Lists changesets and describes their ops. |
| `src/hippo/web/routes/code.py:182` | `_graph` | 4b web | Every code endpoint's single owner. |
| `src/hippo/web/routes/users.py:88` | `ladder` | 4b web | |
| `src/hippo/web/routes/users.py:119` | `users_page` | 4b web | |
| `src/hippo/web/routes/users.py:289` | `list_users` | 4b web | |
| `src/hippo/web/routes/users.py:300` | `list_roles` | 4b web | |
| `src/hippo/web/routes/users.py:364` | `patch_user` | 4b web | Mutation, but the session exists for the source/user view it returns. |
| `src/hippo/web/routes/users.py:435` | `patch_role` | 4b web | Same. |
| `src/hippo/web/auth.py:331` | `account_page` | 4b web | Account source view. |
| `src/hippo/web/auth.py:384` | `me` | 4b web | |
| `src/hippo/web/render.py:89` | `render` | 4b web | Render helper: acquires an owner only when the caller did not supply one. |
| `src/hippo/mcp_server.py:339` | `_code_graph` | 4c MCP | Code tools. |
| `src/hippo/mcp_server.py:428` | `sources_tool` | 4c MCP | Source listing. |
| `src/hippo/knowledge/changeset_access.py:49` | `read_scope` | 4b web | Only consumer is `web/routes/analyze.py`. Graph-only: lists and describes ops. |
| `src/hippo/knowledge/changeset_access.py:70` | `_mutation_scope` | 4b web | Uses the lower `query_access` on purpose: mutations bump the authorization epoch, so no heartbeat may join while the DB lock is held. Still graph-only evidence; it must become structural with the rest of 4b. |
| `src/hippo/knowledge/eval_access.py:97` | `read_scope` | 4d evals | |
| `src/hippo/knowledge/eval_access.py:123` | `_creation_scope` | 4d evals | Same `query_access` reason as the changeset mutation scope. |
| `src/hippo/evals/question_maker.py:94` | `generate_questions` | 4d evals | The plan classifies "question-maker passage reads" as a graph owner. It calls the LLM to write questions, but it never embeds a query and never scores dense candidates: seeds come from `_passages_of` and `shared_entity_pairs`. It therefore holds a structural `query_session` and does **not** need `retrieval_session`. |

## 4. Local-CLI presentation to replace with a structural session

| File:line | Symbol | Owner | Note |
|---|---|---|---|
| `src/hippo/cli.py:278` | `_code_locally` | 4c CLI | `index = ctx.graph()` — the whole unrestricted graph as presentation evidence. The plan requires replacing this with one structural session and the shared payload/source-view functions. |
| `src/hippo/knowledge/changeset_access.py:170` | `apply` | 4b web | `set(self.ctx.graph().node_ids)` inside `_mutation_scope`, used only to reject managed evidence identities as legacy edit targets. This is a deliberate *unrestricted* read of the native legacy graph, not query evidence, so it may stay a raw `ctx.graph()`; 4b must confirm it stays inside the mutation scope and never reaches a response body. |

## 5. Infrastructure (definitions and internal plumbing, not owners)

| File:line | Symbol | Note |
|---|---|---|
| `src/hippo/context.py:117` | `AppContext.graph_for` def | Keeps `structural: bool = False`. Unchanged by 4a. |
| `src/hippo/context.py:129` | `graph_for` | Forwards to `_graph_for`. |
| `src/hippo/context.py:170` | `_graph_for` def | Keeps `structural=False`. |
| `src/hippo/context.py:180` | `_graph_for` | Legacy managed compatibility branch. |
| `src/hippo/context.py:201` | `_managed_graph_for` def | Same. |
| `src/hippo/knowledge/dense_session.py:188` | `_session` | The dispatcher's own owner acquisition, already `structural=True`. |
| `src/hippo/knowledge/dense_session.py:271` | `dense_session` def | Verified-only entry point. |
| `src/hippo/knowledge/dense_session.py:289` | `retrieval_session` def | Verified-or-tag-compatible entry point. |

## 6. Not calls

| File:line | Note |
|---|---|
| `src/hippo/context.py:8` | Module docstring: "`graph()` is the whole graph; `graph_for(access)` is the part a user may see". |
| `src/hippo/web/routes/code.py:10` | Module docstring: "Every endpoint reads `ctx.graph_for(access)`". Stale after 4b converts the route; 4b owns the wording. |
| `src/hippo/web/routes/graph.py:6` | Module docstring: "come from `ctx.graph_for(access)`". Same. |

## 7. Excluded by inspection

`rg '\.graph\(\)'` also matches `EvalAccess.graph()` (`src/hippo/knowledge/eval_access.py:106, 220,
295, 322, 337, 357, 417, 479, 500`). That is a method on the access object returning the held
session's graph, not `AppContext.graph()`, so it acquires nothing and is not an audit row.

## 8. Counts by class (at `043ca51`; the current counts are in the refresh section above)

| Class | Rows |
|---|---|
| `4a-converted` (incl. the two infrastructure lines inside the converted primitives) | 10 |
| `model/dense`, still to convert | 14 (4b 7, 4c 3, 4d 4) |
| `graph-only`, still to convert or confirm | 33 (4b 28 incl. the sessionless `reindex_all`, 4c 2, 4d 3) |
| local-CLI / administrative presentation | 2 (4c 1, 4b 1) |
| `infrastructure` (definitions outside the converted primitives) | 8 |
| `not-a-call` | 3 |
| **Unclassified** | **0** |
