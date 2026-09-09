# L4 — Docs for five languages, and the add-langs deviations table

Read `impl/00-impl-context.md` first. Worktree `.worktrees/l4`, branch `wp/l4`, from the CURRENT tip of
`code-graph`. No Neo4j leg (docs only); `just lint` and `just test-fake` must pass. You edit only
`README.md`, `docs/CONTRACTS.md`, `docs/FIDELITY.md`, `docs/MCP.md`, `docs/design/README.md`,
`ai_docs/add_langs.md` (append a deviations section) and `docs/plans/hippo-for-code/PLAN.md`
(append rows to its "Implementation deviations" table only).

Spec: `ai_docs/add_langs.md` §"Docs" row of the touch-point table and §"Decisions taken here"; then
the truth on `code-graph`: `src/hippo/codegraph/languages.py` (the registry, `PARSED_LANGS`),
`go.py` / `csharp.py` / `rust.py` module docstrings, `ingest/chunker.py`'s new rule, and the ledger
notes (`horch sessions`) of `opus-7` (L0), `opus-9`/`opus-15` (Go A/B), `opus-10`/`opus-16` (C# A/B),
`opus-11`/`opus-14` (Rust A/B), `opus-8` (L1 anchors), `opus-13` (L3 chunker), `sonnet-3`/`sonnet-5`
(git-history hardening, Node idioms) — each ends with "limits for L4" and "decisions where the plan was
silent". Every name you write must exist in the tree (the `/tmp/wp4d-namecheck.sh` idea: grep each
backticked name; paste the loop in the ledger).

## Scope

1. **README** — "Two languages, plus the SQL beside them" becomes five (Python, TypeScript/JavaScript,
   Go, C#, Rust, plus `.sql`); the Code section's seeding sentence names the three new stack-frame
   shapes (Go panic, .NET, Rust panic/backtrace); "Where the code lives" gains `codegraph/languages.py`,
   `go.py`, `csharp.py`, `rust.py`; the indexing-cost sentence stays. Per-language limits in Known
   limitations, one line each, from the ledgers: Go has no RAISES/CATCHES (no exceptions) and
   `same_scope` is the directory; C#: EF Core DbSets, extension methods, `new A.B.C().M()`, a call
   inside a property body do not resolve; Rust: a call inside any macro is invisible (so `assert_eq!`
   tests yield 0.60 not 0.85), RAISES comes from `-> Result<_, E>` signatures only, no CATCHES, no
   `same_scope`; all: a Go/Rust doc comment sits outside its declaration's range so the symbol's own
   passage does not print it while OpenIE still reads it; `go.mod` is one prose passage; the fuzzy
   stoplist is case-blind; a namespace declared by many files imports from the smallest path.
2. **CONTRACTS.md** — rows for `codegraph/languages.py` (`LanguageRules` fields incl. `is_test_function`,
   `member_paths`, `source_setup`, per-language `self_names`/`super_names`; `RULES`, `register`,
   `PARSED_LANGS`), the three walkers (`walk(path, root_node, source_id) -> FileFacts`, `RULES_ENTRY`),
   `resolve.declared`, `resolve._member_tier`/`same_scope`, `FileFacts.scope`, `SourceIndex.scopes` /
   `lang_state`, `Resolution.scope`, `AssignFact.chain`, `readers.KNOWN_TEXT_FILENAMES`,
   `git_history.MAX_DIFF_BYTES` / `_git_capped` (check the E1F-a row is right), `anchors` new frame
   regexes and `_Frame`; and fix the chunker row L3 flagged (~line 126: "a placeholder line per member"
   → the one-sentence rule in the `opus-13` ledger: every line of a parsed file is printed in exactly
   one passage; a container's header is its own lines with one placeholder per member wherever it is
   written; the file module stands in for every symbol range).
3. **FIDELITY.md** adaptation 15 — the ω table gains `same_scope` 1.00; the languages sentence; the
   three new trace shapes under seeding; nothing else moves (verify the inertness paragraph is still
   literally true with five trees: the mixed-memory tests pin it).
4. **MCP.md** — one example naming a Go or Rust symbol (generate it by calling the tool over
   `code_index`, as WP4d did; do not transcribe).
5. **docs/design/README.md** rows 26 and 54: five languages; the deferrals table loses Go/Rust from
   its "unsupported" examples and gains Java/Kotlin/C/C++.
6. **Deviations**: append `## Implementation deviations` to `ai_docs/add_langs.md` (same three-column
   shape as PLAN.md's table) with one row per ruling: per-language `self_names`/`super_names` (not a
   shared `base`); `PARSED_LANGS` derived in `languages.py`; `LanguageRules` defined in `model.py`;
   `is_test_function` hook; `same_scope` for members of a sibling file (L0c); case-blind stoplist;
   `declared()`/`member_paths` for cross-file types (L0d); `Resolution.scope` wiring; `files_skipped`
   reason stays `unsupported`; `go.mod` as a known text name; the chunker rule (L3); doc comments use
   their own prose; C# tests in `CsApp.Orders.Tests` with `using`; C# per-(field × method)
   `AssignFact`s; C# `Program.cs` needs `using`; Rust `tests/` crate rule; Go `Save` exists; no
   `.csproj`/`Cargo.toml`; deterministic namespace target; the lift test's isolated form; the
   `passages_for_source(limit=50)` trap; `MAX_MATCHES_PER_TOKEN` capping `log` at nine matches. Add
   the cross-cutting ones (L0b-L0d, L3, lift test, prose rule) to PLAN.md's table too, as I15+.

## Done when

`just lint` and `just test-fake` green, name-check loop clean, ledger summary listing every file and
the rows added, `horch tell orchestrator "[<role>] DONE: wp/l4 ..."`, close pane.
