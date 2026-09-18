# L2 — Language walker briefing (shared by the Go, C# and Rust workers)

Read `impl/00-impl-context.md` first (rules, worktree + venv, three-store matrix, capture pytest exit
codes to a file). Your language, worktree, branch and Neo4j port are in the spawn message:

| Language | Worktree / branch | Neo4j container / port | Spec | Fixture tree | Test file |
|---|---|---|---|---|---|
| Go | `.worktrees/lgo`, `wp/lgo` | `hippo-neo4j-lgo`, **17703** | `ai_docs/add_langs.md` **Step 1** | `goapp/` | `test_codegraph_go.py` |
| C# | `.worktrees/lcs`, `wp/lcs` | `hippo-neo4j-lcs`, **17704** | **Step 2** | `csapp/` | `test_codegraph_csharp.py` |
| Rust | `.worktrees/lrs`, `wp/lrs` | `hippo-neo4j-lrs`, **17705** | **Step 3** | `rsapp/` | `test_codegraph_rust.py` |

`code-graph` now contains L0: `src/hippo/codegraph/languages.py` with the `LanguageRules` registry,
the grammar for your language already loading (`treesitter.get_language("<lang>")`), your suffixes
in `LANG_BY_SUFFIX` / `readers.lang_of`, `LINE_COMMENT` `//`, the PascalCase Mongo names and
collection markers in `data_access.py`, `same_scope` at ω 1.00, **per-language** `self_names` /
`super_names` on `LanguageRules` (C#'s already holds `base`, Rust's `Self`; `model.SELF_NAMES` /
`SUPER_NAMES` are only the defaults), `FileFacts.scope` + `SourceIndex.scopes`,
`LanguageRules.source_setup` + `SourceIndex.lang_state`, `member_paths`, `Resolution.scope`, and
`languages.PARSED_LANGS` DERIVED from the walker keys (so registering your walker is what turns on
MODIFIES for your language — nothing in `model.py`). The walker signature is
`walk(path: str, root_node: Node, source_id: str) -> FileFacts`. **The shared defaults do not cover
your test files**: C# must register its own `is_test_path` and `test_stem` (`Orders.Tests/
OrderServiceTests.cs` is a test file, stem `OrderService`), Rust its own `test_stem`
(`tests/orders.rs` → `orders`); Go's defaults already work. A registered-but-unwalked language is
counted as `unsupported` in `files_skipped` (no new reason string). **Read the two L0 ledger handoff
notes (`horch sessions`, the `opus-7` entry) and `languages.py` before writing a line** — the hooks are
how you plug in without editing shared files. Two other language workers run in parallel.

## Two spawns per language (sizing rule: finish inside your first ~400k tokens)

**Phase A — walker + pure tests.** `src/hippo/codegraph/<lang>.py`, its `RULES_ENTRY`, the ONE
registration line in `languages.py`, and `tests/unit/test_codegraph_<lang>.py` written against INLINE
`Document` lists (the way `test_codegraph.py` covers the resolver rows the shared fixture lacks). Do not
touch the shared fixture tree, `expected.json` or any count literal. Three stores green (nothing you
touch should change an existing test except `tools/build.go` moving to `files_parsed` for Go — Go's
phase A DOES move the `test_indexer.py` OpenIE-policy assertion to a new `tools/build.rb`). Ledger
summary + `PHASE A DONE` via `horch tell`, close pane.

**Phase B — fixture + golden file** (a fresh worker, briefed from phase A's ledger): the
`<lang>app/` tree, `expected.json` regeneration reviewed row by row, the count literals, the chunker
placeholder cases, and one `test_retriever.py` case via `code_index` naming a symbol of your language.

## What you own

- `src/hippo/codegraph/<lang>.py` (new): the walker (`walk(path, root_node, source_id) -> FileFacts`),
  the language's `resolve_module`, `scope_defines`, `module_qualname`, `is_test_path`, `test_stem`,
  `source_setup`, `member_paths`, `self_names`/`super_names` as your Step needs, and the module-level
  `RULES_ENTRY`. Register it with the ONE line in `languages.py` (import the module, swap the
  placeholder `register(LanguageRules(name="<lang>", ...))` for `register(<lang>_walker.RULES_ENTRY)`) —
  that single line is the only shared-file edit you may make without asking.
- `tests/fixtures/code_sample/<lang>app/**` exactly as the plan's "Fixture additions" block draws it,
  mirroring the `pyapp`/`tsapp` "order service" story so the same `orders` table, `archive_orders`
  collection and `Order`/`Customer`/`PLACED_BY` Cypher objects dedupe across trees. Recompute line
  numbers from your final files; your tests assert the final numbers.
- `tests/unit/test_codegraph_<lang>.py` (new, pure): every bullet of "Tests, per step" for your
  language — exact symbol set with kinds and line ranges, signatures and docs, every edge with ω and
  provenance, the no-edge rows (`fmt.Errorf` / `Console.WriteLine` / `println!` / `panic` / external
  packages), `in_branch`, `arg_binding`, `is_test`, the module-qualname rules, the import forms, the
  fuzzy rule and the `same_scope` tier, determinism.
- `expected.json`: regenerate with `scripts/update_expected.py` after your walker lands and **read the
  diff row by row** — only rows under `<lang>app/` may appear, plus new `mentions` sites on the shared
  data objects. Any change to a `pyapp`/`tsapp`/`schema` row means you changed shared behaviour: stop
  and `horch tell orchestrator`.
- The count literals your fixture moves: `test_indexer.py` (nine-key counts, `DEFINED_IN` rows),
  `test_ingest_pipeline.py` (`meta["code"]` numbers), `test_codegraph.py` fixture totals,
  `test_ingest_chunker.py` (add your placeholder / header cases from the plan's chunker bullet). Update
  them to YOUR branch's numbers; the orchestrator reconciles the three branches' numbers after merge,
  so put the exact new numbers in your ledger summary.
- **Go only**: `tools/build.go` becomes parsed, so add `tools/build.rb` (Ruby, unsupported) and move
  the `test_indexer.py` OpenIE-policy assertion ("an unparsed code file still gets NER") to it; the
  `go.mod` reader is `source_setup`.
- **Rust only**: inline `mod tests { }` is a symbol of kind `module` and a container; cross-file `impl`
  members go through `member_paths`.
- **C# only**: namespace scope via `FileFacts.scope`/`scopes`; `using` binds a scope through
  `Resolution.scope`; field declarations recorded as `AssignFact(scope=class, target=field, value=type)`
  so DI-injected `_service.Place()` resolves by declared type.

## Rules

- Do not edit `resolve.py`, `extract.py`, `model.py`, `data_access.py`, `chunker.py`, `python.py`,
  `typescript.py`, `anchors.py`, `git_history.py`. If a hook you need is missing or wrong, `horch tell orchestrator` with
  the exact change you need and WAIT; do not work around it in your walker.
- Decisions the plan already took (its "Decisions taken here" list) are settled. Where your Step is
  silent, choose the reading that mirrors `python.py`/`typescript.py`, and write it in the ledger.
- Every ω and provenance comes from the plan's tables; `same_scope` 1.00 for same package/namespace.

## Done when

Three stores + lint green, `scripts/update_expected.py --check` clean, the pure test file green, no
`pyapp`/`tsapp` row changed in `expected.json`. Ledger summary: files, the exact fixture line numbers
and edge list, every count literal you changed with old → new, decisions where the plan was silent, and
anything L4 (docs) should say about your language's limits.
`horch tell orchestrator "[<role>] DONE: wp/<branch> ..."`, close pane.
