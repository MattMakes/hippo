# E2F-b — The resolver's own index must not let a member overwrite its file's module

Read `impl/00-impl-context.md` first (rules, worktree + venv, three-store matrix, exit-code capture).
Worktree `.worktrees/e2fb`, branch `wp/e2fb`, from the CURRENT tip of `code-graph`. Neo4j test
container: name `hippo-neo4j-e2fb`, port **17714**. Small, contained task.

Context: E2F (merged as aac9559) fixed the STORE side of the module-vs-member id collision with
`model.symbol_key(path, qualname, kind)`. The `opus-18` ledger names the residual: `resolve.SourceIndex.
symbols` is still keyed `(path, qualname)` (`resolve.py` ~144), so in a collision file (`main.go` with
`func main`, root `foo.py` with `def foo`) the member overwrites the module in the RESOLVER's index — a
module-level call in that file is attributed to the member (lookups ~420/636/696), and
`resolve_tested_by`'s `by_id` (~788) lacks the module symbol. `CallFact.caller == facts.module` is
exactly ambiguous there, so the fact must say which it is.

## Do this

1. Key `SourceIndex.symbols` (and every lookup that builds a key from `(path, qualname)`) by
   `model.symbol_key(path, qualname, kind)` — one helper, used everywhere; grep for every
   `(facts.path, ...)` / `(path, qualname)` tuple key in `resolve.py`, `extract.py`, `git_history.py`
   and the walkers.
2. Give `CallFact` (and any other fact that names its caller by qualname — `RaiseFact`, `LiteralFact`,
   `AssignFact.scope`) a `caller_kind` (or a `caller_key`) so a module-level call in a collision file
   is attributed to the module, not the member. All five walkers emit it; default it for backward
   compatibility so inline tests that build facts by hand keep working.
3. Tests: in `test_codegraph.py`, a root `foo.py` with `def foo()` and a module-level `foo()` call →
   INVOKES from the MODULE `foo` to the function `foo` (not a self-loop dropped silently), and a Go
   `main.go` whose `func main` calls `run()` → INVOKES from `main.main`; `resolve_tested_by` over a test
   module whose name collides with a function still emits its TESTED_BY. `expected.json --check` clean
   (the fixture has no collision file; assert that in the test the way E2F asserted no renames).

Done when three stores + lint green, no pinned assertion weakened, ledger summary,
`horch tell orchestrator "[<role>] DONE: wp/e2fb ..."`, close pane.
