# WP0 — `split_identifier` and `label_of` in `hipporag/text.py`

Read `impl/00-impl-context.md` first. Worktree: `.worktrees/wp0`, branch `wp/wp0`. No Neo4j leg needed
(pure functions), but `just test` and `just test-fake` and `just lint` must be green.

This is a 30-minute task that lands BEFORE WP1 and WP2 so both can fork from it without touching the same
file. Read PLAN.md §Design summary "Node ids" (line ~81) and WP1.1 (line ~176) for the spec; nothing else
in the plan is yours.

## Deliverable: two pure functions in `src/hippo/hipporag/text.py`, beside `make_id`

1. `label_of(node_id: str) -> str` — maps the id prefix to the node label:
   `entity-` → `Entity`, `passage-` → `Passage`, `symbol-` → `Symbol`, `data-` → `DataObject`,
   `commit-` → `Commit`; `fact-` → `Fact` (facts are ids too — include it). Raises `ValueError` on any other
   prefix or on a non-string. Pure string work on the prefix; no lookup, no store. Check how `make_id`
   builds ids (`text.py:27-39`) so the prefixes match exactly.
2. `split_identifier(name: str) -> list[str]` — lowercase tokens of a code identifier:
   `OrderService → ["order", "service"]`, `get_user2 → ["get", "user", "2"]`,
   `pkg.HTTPServer → ["pkg", "http", "server"]`, `XMLHttpRequest → ["xml", "http", "request"]`,
   `__init__ → ["init"]`, `snake_case_name → ["snake", "case", "name"]`, `a.b.c → ["a", "b", "c"]`,
   `"" → []`. Split on `.`, `_`, `-`, `/`, `::`, whitespace, digit/letter boundaries and camelCase
   boundaries (an uppercase run followed by a capitalised word splits before the last capital, as in
   `HTTPServer`). Drop empty tokens. Deterministic, no regex compilation per call (compile at module level).

## Tests

Grow `tests/unit/test_text.py` (exists): one `label_of` case per prefix, the `raises` case, and a
parametrized table for `split_identifier` covering every example above plus one unicode name
(`café_name → ["café", "name"]`). Keep the file's existing style.

## Done

`just test-fake`, `just test`, `just lint` green in the worktree; committed on `wp/wp0`; ledger summary;
`horch tell orchestrator "[<role>] DONE: wp/wp0 ..."`; close your pane.
