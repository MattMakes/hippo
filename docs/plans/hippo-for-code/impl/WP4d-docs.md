# WP4d — Docs: CONTRACTS, FIDELITY adaptation 15, MCP.md, README, docs/design

Read `impl/00-impl-context.md` first. Worktree `.worktrees/wp4d`, branch `wp/wp4d`. No Neo4j leg: you
change no code. `just lint` must still pass (it does not lint markdown outside `docs/plans`, but run it).

`code-graph` now contains WP1-WP3, and WP4a/b/c (API+MCP+CLI, web pages, evals) are being built in
parallel by three other workers. **You edit only `docs/CONTRACTS.md`, `docs/FIDELITY.md`, `docs/MCP.md`,
`README.md` and the new `docs/design/` directory.** Where a name you must document is owned by a parallel
worker (endpoint query parameters, MCP response fields, CLI flags, eval metric names), take it from the
plan; the orchestrator will hand you their ledger summaries when they land so you can correct the few
that differ, before your branch merges.

Your spec is PLAN.md **§Docs to update (lines 528-568)** in full — it prescribes the exact format of each
file — plus the FIDELITY paragraph and the three sentence edits in §Retrieval rule (lines 121-125),
§Known limitations (lines 515-522), §Out of scope (line 526), the Settings table (lines 129-141), and
Confirm #5 (line 513). Evidence: `research/R6-web-mcp-cli-docs.md` C12 (CONTRACTS.md's fenced plain-text
block format, not a table; its "## To write" heading is stale — append there), C13 (FIDELITY.md is a flat
numbered list of 14 adaptations; you write **15, "Code graph"**, not a section), C9/`MCP.md:136-227` (one
request/response JSON pair per tool), gotcha 2 (`README.md:228` says "four MCP tools"; it becomes nine).
Also `research/S0-spikes.md` spike 3 for two limitations to state: a pandas-sized repo (~34k symbols) now
exceeds `MAX_CHUNKS = 20_000` where its line windows fit before, and vector reload cost at the ceiling
(~117 MiB) on every graph-version bump.

## What the previous workers built (read their code — the code is the truth, the plan is the intent)

<!-- ORCHESTRATOR FILLS FROM THE WP1-WP3 LEDGER SUMMARIES; WP4a/b/c arrive as they land -->

## Scope

1. **`docs/CONTRACTS.md`** — a new `### code graph` heading with the block quoted at PLAN lines 532-560,
   corrected to the signatures actually in the code (`grep -n "^def \|^    def \|^class " ` the modules),
   plus rows appended to the existing `src/hippo/web/`, `mcp_server.py` and `cli.py` blocks.
2. **`docs/FIDELITY.md`** — adaptation 15 in the file's exact `N. **Title.** ... Reason: ...` shape,
   covering every item in the list at line 562; the inertness paragraph from line 123 verbatim; and the
   **three** sentence edits at `:67-72`, `:120-121`, `:153-155` as §Retrieval rule specifies (the line
   numbers are from before this work — find the sentences by text). Every claim you write must be
   literally true of the code on `code-graph`: check `build_igraph`'s weight expression, the retriever's
   gate, and `split_question` before you write the sentence that describes them.
3. **`docs/MCP.md`** — "## The five tools" → nine; a `###` per new tool with one request/response JSON
   pair in the existing shape, the `AmbiguousSymbol` → `ToolError` example, and the new fields on
   `hippo_search`/`hippo_ask`. Field names come from WP4a's code; until it lands use the plan's and mark
   each with `<!-- verify against WP4a -->`, then remove the markers when the orchestrator sends the summary.
4. **`README.md`** — the new **"Code"** section after "How it works" (line 568 lists its content); the
   eleven `code_*` rows in the configuration table; "Where the code lives" gains the five new modules;
   `README.md:228` "four MCP tools" → nine. No new env var anywhere.
5. **`docs/design/`** — `README.md` mapping each principle of the code-only design to where it lives in
   hippo and what phase 1 defers (D12 CCG, D13 incremental, D14 overrides, D15 unresolved, D16 replay
   gate, D23 LSP, typed restart, `Field` nodes). The two verbatim documents `code-hipporag-design.md` and
   `code-only-design.md` are the USER's originals and are not in the repo: write `docs/design/README.md`
   so it links to both by those names, and put a one-line placeholder file at each path saying the
   document is supplied by the user (the orchestrator has asked for them). `inputs/B-design-against-built.md`
   is NOT one of them unless the orchestrator tells you so. Do not invent content.
6. **Known limitations** — every bullet of PLAN lines 517-522 plus the two spike-3 facts, in whichever
   file the existing "limitations" content lives (check README and FIDELITY; follow the precedent).

## Done when

Every file reads as if the feature had always been there, every path/function/setting/tool name you
wrote exists on `code-graph` (write a tiny `grep` loop over your own doc and run it — paste it in the
ledger), lint green. Commit, ledger summary (files; the list of names you marked `verify against`),
`horch tell orchestrator "[<role>] DONE: wp/wp4d ..."`, and **keep your pane open**: the orchestrator
will send you the WP4a/b/c summaries for a final correction pass before merge.
