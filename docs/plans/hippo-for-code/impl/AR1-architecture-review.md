# AR1 — Architecture review of WP1-WP3 against the plan (read-only, runs while WP4 is built)

Read `impl/00-impl-context.md` for the fleet rules; you are the read-only exception: **you edit nothing**
and produce `docs/plans/hippo-for-code/research/AR1-architecture-review.md`. Work in the root tree
(`/Users/mascott/projects/hippo`, branch `code-graph`) — it is safe because you only read. Do not
commit; the orchestrator commits your report.

## What to review

The diff `git diff main...code-graph -- src tests` (WP0-WP3: `store/code.py`, the three stores,
`graph_index.py`, `codegraph/`, `chunker.py`, `indexer.py`, `pipeline.py`, `anchors.py`, `paths.py`,
`retriever.py`, `answerer.py`, `ask.py`, `prompts.py`, `simulate.py`) against `docs/plans/hippo-for-code/
PLAN.md` — its Decision Log, Design summary and the WP1-WP3 sections — and against the boundaries the
plan draws (line 164: `codegraph` → `hipporag.text` only; `ingest.chunker` → `codegraph.model`;
`hipporag.indexer` imports `CodeGraph` under `TYPE_CHECKING`; `hipporag/paths.py` in `hipporag/`
because the retriever calls it; `store/base.py` is the Neo4j base class, three stores kept in step by
convention + `test_store_code.py`'s parity guard). The ledger summaries in `horch sessions`
(`backend-developer-1`, `opus-1`, `backend-developer-2`, `opus-2`) list every decision each worker made
where the plan was silent — review those decisions too.

## Judge

1. **Boundaries and import direction** — any cycle, any `codegraph` → `ingest`/`store` import, any
   store-specific knowledge leaking into `hipporag/`, any place the three stores diverge in a contract
   the parity guard cannot see (return shapes, ordering promises, None vs "" handling).
2. **Contracts vs plan** — every Decision Log row D1-D25 that touches WP1-WP3: kept, adapted (with the
   worker's stated reason), or silently violated. The six load-bearing gotchas in the rulebook: verify
   each in the code with a file:line.
3. **Fidelity** — read `build_igraph`'s weight expression, `_code_seeds`, the `used_code_seeds` gate,
   `split_question`'s effect on the embedded text, `answer_from_trace`'s `via_expand` filter, and say
   whether `docs/FIDELITY.md`'s existing 14 adaptations are still literally true and whether the
   mixed-memory tests in `test_retriever.py` actually pin the inertness claim.
4. **Coupling and cost** — anything O(n²) over symbols or edges in `GraphIndex.load`, `scoped()`,
   `name_index`, `_code_seeds`, `community_labels`, or the REFERS_TO linker; anything that rebuilds
   igraph per query; anything that will not scale to the 20k-symbol ceiling spike 3 measured.
5. **Tests** — what is pinned by `expected.json` and `CODE_BLOCK_BODY` that will churn on every
   harmless change, and what is NOT pinned that should be (a backend-order dependency, a None passing
   through `decode()`, an access leak through `name_index`).

## Output

A findings list ranked by severity (`blocker` — wrong or unsafe; `fix` — should change before release;
`nit`), each `file:line — finding — recommendation`, with a short verdict paragraph first. Be concrete:
a finding without a file:line is not a finding. ~1.5 hours. When done:
`horch tell orchestrator "[<role>] DONE: research/AR1-architecture-review.md — N blockers / N fixes / N nits"`,
ledger summary, close pane.
