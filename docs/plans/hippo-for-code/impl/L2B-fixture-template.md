# L2B — Phase B: the fixture tree and golden file for one language (Rust, then Go, then C#)

Read `impl/00-impl-context.md` first (rules, worktree + venv, three-store matrix, exit-code capture).
Your language, worktree, branch and Neo4j port are in the spawn message:

| Language | Worktree / branch | Neo4j container / port | Fixture tree | Phase-A ledger to read |
|---|---|---|---|---|
| Rust | `.worktrees/lrsb`, `wp/lrsb` | `hippo-neo4j-lrsb`, **17710** | `rsapp/` | `opus-11` ("RUST PHASE A LEDGER", two notes) |
| Go | `.worktrees/lgob`, `wp/lgob` | `hippo-neo4j-lgob`, **17711** | `goapp/` | `opus-9` ("GO PHASE A DECISIONS", "GO PHASE A KNOWN LIMITS") |
| C# | `.worktrees/lcsb`, `wp/lcsb` | `hippo-neo4j-lcsb`, **17712** | `csapp/` | `opus-10` (its DONE summary) |

**Phase B runs one language at a time**, each from the tip of `code-graph` that already contains the
previous language's fixture, so `expected.json` and the count literals are regenerated on top of the
last state rather than reconciled three ways. All five walkers, the shared resolver fixes (L0b-L0d)
and the chunker fix for members-outside-their-type / inline modules (L3) are merged. Nothing in
`src/` should need to change; if it does, `horch tell orchestrator` before editing.

## Scope

1. **`tests/fixtures/code_sample/<lang>app/**`** exactly as `ai_docs/add_langs.md` §"Fixture additions"
   draws it, mirroring the `pyapp`/`tsapp` order-service story (same `orders` table, `archive_orders`
   collection, `Order`/`Customer`/`PLACED_BY` Cypher objects, an `OrderService` with `place`/`log`/
   `list_open`/`save`/`archive`/`graph`, a `Base`, an `OrderError`, a billing module, a test, an
   entry point). Apply the phase-A worker's fixture constraints (read its ledger — the load-bearing
   ones are repeated below). Recompute the final line numbers from your files.
2. **`expected.json`**: `scripts/update_expected.py`, then read the diff row by row. Only rows under
   `<lang>app/` may appear plus new `mentions` sites on the shared data objects (the dedup test
   `test_fixture_data_objects_are_deduped_across_every_site` gains sites, not objects). A changed
   `pyapp`/`tsapp`/`schema`/`goapp`/`rsapp` row means shared behaviour moved: stop and tell me.
3. **Count literals** that move with the fixture: `test_codegraph.py` fixture totals, `test_indexer.py`
   (nine-key counts, DEFINED_IN rows, the OpenIE bill `len(extracted)`), `test_ingest_pipeline.py`
   (`meta["code"]` numbers), `test_web_base.py` / `test_web_code_pages_2.py` (status pill count,
   languages list), `test_git_history.py` if a modifies count moved. Record every old → new in the
   ledger summary.
4. **`test_ingest_chunker.py`**: the placeholder and header cases the plan's chunker bullet lists for
   your language (`func (s *Service) Place(o Order) int { ... }  // lines a-b`,
   `public int Place(Order order) { ... }  // lines a-b`,
   `pub fn place(&self, o: &Order) -> Result<i64, OrderError> { ... }  // lines a-b`), the class/impl
   header with method placeholders, and (Rust) `mod tests` chunked as a container — under the L3 rule:
   a type whose members lie outside it gets a header passage of exactly its own lines, every line of
   a file is rendered once across its passages.
5. **`test_retriever.py`** via `code_index`: naming your language's `place` (display name, e.g.
   `goapp.orders.service.Service.Place`) seeds it and lifts its passage into what the model reads;
   `hippo path`-style `paths.shortest_code_path` from `place` to the billing `total` renders
   `-[INVOKES 0.90 via_import]->` (or `1.00 same_scope` where the plan says so — Go's `main.go` and
   `service_test.go` cases are in the plan's fixture block).

## Load-bearing constraints from phase A (all languages read all three)

- **Go**: a symbol's `doc` is the FIRST PARAGRAPH only — the ≥ 80-char prose (see the doc-comment
  rule below: its own words, not the Acme/Priya/Boulder sentences) must sit in the first paragraph, or
  `extract_text` is `""` and OpenIE never sees it. `goapp/go.mod` becomes ONE prose-chunked passage (a known text name) and NO
  `files_skipped` row, so `len(extracted)` in `test_indexer.py` goes up by one. `FileFacts.scope` is
  the directory. Import resolution is `go.mod` first, then ≥ 2 shared trailing path segments.
- **C#**: `csapp/Program.cs` MUST carry `using CsApp.Orders;` or its call resolves at 0.50
  `fuzzy_name` with no edge to the class. An interpolated SQL string must quote its hole
  (`... WHERE id = '{id}'`) or sqlglot yields no data object. A bodyless interface member renders a
  `{ ... }` placeholder (cosmetic, accepted).
- **Rust**: `rsapp/tests/orders.rs` must say `use rsapp::orders::OrderService;` (`crate::` is dead from
  `tests/`); the test's call must be a statement, NOT inside `assert_eq!` (calls inside any macro are
  invisible); `OrderService::new` need not exist for `.place()` to resolve; struct and impls may live in
  different files and still get INHERITS/OVERRIDES/CONTAINS. Rust sets no `FileFacts.scope`, so
  `same_scope` never fires for it.
- **All — doc comments (ruling from Rust phase B)**: each new tree's `OrderService` and `place` docs
  must be ≥ 80 chars of their OWN prose that never names Acme Robotics, Priya Natarajan or Boulder.
  The plan's `csapp` `<summary>` text repeats `pyapp`'s sentences, but repeating them makes two more
  code passages mention the prose entities and re-weights the mixed-memory ranking, which breaks the
  exact V2.5 guard in `test_retriever.py`. Record it as a plan deviation in the ledger. Also: a second
  tree with the same short qualnames (`OrderService.place`, `Base.log`, `OrderError`, `save`) makes
  bare-name lookups ambiguous, so fully-qualify the call sites in the existing tests (`test_paths.py`,
  `test_mcp_*`, `test_web_code.py`, `test_git_history.py`) — the Rust phase-B ledger lists them; and the
  inertness test compares ids/order exactly and scores with `pytest.approx(rel=1e-9)` (PPR summation
  noise from more isolated vertices at scale 0).
- **All**: `extract.WALKERS` is an import-time snapshot (tests swapping a walker patch both); the
  `make_code_checkout` three commits gain no files, so history tests do not move.

## Done when

Three stores + lint green, `scripts/update_expected.py --check` clean, the golden test green, no row
outside your tree changed. Ledger summary: files, final line numbers, the edge list under your tree,
every count literal old → new, and the three or four limits L4 should document for your language.
`horch tell orchestrator "[<role>] DONE: wp/<branch> ..."`, close pane.
