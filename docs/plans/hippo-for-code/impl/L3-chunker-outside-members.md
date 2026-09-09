# L3 — Chunker: types whose methods live outside the type, and inline modules as containers

Read `impl/00-impl-context.md` first (rules, worktree + venv, three-store matrix, exit-code capture).
Worktree `.worktrees/l3`, branch `wp/l3`, from the CURRENT tip of `code-graph` (the Rust walker is
merged; Go and C# walkers are in flight and do not touch the chunker). Neo4j test container: name
`hippo-neo4j-l3`, port **17709**. One file plus its tests: `src/hippo/ingest/chunker.py`,
`tests/unit/test_ingest_chunker.py`. Nothing in `codegraph/`.

Two facts the Go and Rust walker workers reported (their ledger notes: `opus-9` "Go phase A",
`opus-11` "RUST PHASE A LEDGER"), both about `ingest/chunker.py` assuming Python/TS layout:

1. **A type's methods can lie outside the type's own range** (Go `func (s *Service) Place`, Rust
   `impl OrderService { fn place }`, and `impl Base for OrderService { fn log }`). Today
   `_header_rows` walks from the class's `line_start` to its first member's `line_start`, so the class
   header passage swallows every line between the struct and its first method (other declarations
   included) and its title claims that whole span, while the same lines also sit in the module header's
   placeholder run; and the impl bodies appear both in their own method passages AND verbatim in the
   module header rows, because `_members(module)` lists only kinds `class`/`function` and the module's
   placeholder run therefore never covers a method whose owner's range does not contain it. Rule to
   implement: a class header passage is exactly the class's own lines (`line_start..header_end` where
   `header_end == line_end` for such types) plus one placeholder line per member in the existing
   `sig { ... }  // lines a-b` style, wherever that member lives; and the MODULE header's placeholder
   run covers every symbol range in the file, whatever its kind and owner, so no line is rendered twice.
   Python/TS output must be byte-identical (the existing chunker tests and `expected.json`'s
   `definitions` prove it — `scripts/update_expected.py --check` must stay clean).
2. **An inline module is a container.** Rust's `mod tests { #[test] fn place_totals() {} }` is a symbol
   of kind `module` with members (L0's `build_index` owns it), but `_members()` does not treat kind
   `module` as a container, so its body stays verbatim inside the file's module header and its
   functions get no passage. Make `module`-kind symbols containers exactly like classes (header passage
   of their own lines + placeholders; members get their own passages), for any language.

Tests (inline `Document`s through `extract_code` + `chunk_documents`, the way `test_ingest_chunker.py`
already builds cases): a Rust file with a struct, two impl blocks and an inline `mod tests` → exact
titles in order, every line rendered exactly once across all passages of the file, the struct header
titled with its own range, `mod tests`' function getting its own passage; a Go-shaped case is not
possible until the Go walker merges, so add the Go case as a follow-up note in the ledger for phase B
(the rule is language-agnostic — assert it on the Rust tree with a comment naming Go). Keep every
existing chunker test green unchanged.

Done when three stores + lint green, `expected.json --check` clean, no pinned assertion changed,
ledger summary (the exact new title rule in one sentence, for the phase-B briefings and L4),
`horch tell orchestrator "[<role>] DONE: wp/l3 ..."`, close pane.
