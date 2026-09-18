# L0 — Step 0 of `ai_docs/add_langs.md`: make a language a registration (no behaviour change)

Read `impl/00-impl-context.md` first (rules, worktree + venv recipe, test matrix; capture pytest exit
codes to a file, never `| tail`). Worktree `.worktrees/l0`, branch `wp/l0`, from the CURRENT tip of
`code-graph`. Neo4j test container: name `hippo-neo4j-l0`, port **17701**.

Your spec is **`ai_docs/add_langs.md`**: the "Where a language plugs in today" table and **Step 0** in
full, plus the pieces of Steps 1-3 and 5 that are shared registrations rather than walkers (listed
below). Three language workers (Go, C#, Rust) start the moment you merge, each adding ONLY its own
walker module, fixture tree and tests — so everything shared must land here, once, and the gate is
strict: **the whole suite green on all three stores with `tests/fixtures/code_sample/expected.json`
byte-identical** (`scripts/update_expected.py --check` clean and `git diff --stat` shows no fixture
change). The current code is the truth for names and line numbers; the plan's citations were written
against `39e46de`, so `grep` for symbols rather than trusting a line.

## Scope

1. **`src/hippo/codegraph/languages.py`** (new): the frozen `LanguageRules` dataclass exactly as the
   plan sketches (`name`, `walk`, `resolve_module`, `scope_defines`, `module_qualname`, `is_test_path`,
   `test_stem`, `line_comment`) plus whatever the resolver refactor needs (`member_paths(index,
   qualname) -> list[str]`, defaulting to the one path). `RULES: dict[str, LanguageRules]` is built by
   importing `python.py` and `typescript.py`, which each expose a module-level `RULES_ENTRY`
   (`LanguageRules`). **Walkers are optional**: a language can be registered for suffix / grammar /
   comment style without a walker yet, and `extract_code` then treats its files exactly as an unsupported
   language today (line windows + OpenIE, counted under `files_skipped` with a reason such as
   `"no walker"`). That keeps `tools/build.go` unparsed until the Go walker lands — do not change the
   `test_indexer.py` OpenIE-policy assertion that names it.
2. **The resolver refactor**: the four `facts.lang == "typescript"` branches in `resolve.py`
   (`target_module`, `resolve_member`, `resolve_imports`, `_model_binding`) become
   `RULES[lang]` lookups, the two bodies moving to `python.py` / `typescript.py` untouched;
   `resolve_imports` seeds bindings with `scope_defines(...)` after the file's own `defines`, with
   the new **`same_scope` provenance at ω 1.00** (Python and TS return `{}` so nothing changes);
   `_tested_by_filename` uses `test_stem`; `_on_class` consults `member_paths`; `Resolution` gains an
   optional `scope: dict[str, Symbol] | None` field; `SELF_NAMES` gains `Self`, `SUPER_NAMES` gains
   `base`. Add `same_scope` to the ω table wherever provenances are enumerated (`store/code.py`
   constants if any, docs are L4's). Two more hooks the walkers will need, so they never edit
   `extract.py`/`resolve.py` themselves: **`LanguageRules.source_setup: Callable[[list[Document]],
   Any] | None`**, called once per `extract_code` run and stored on `SourceIndex.lang_state[lang]`
   (Go reads `go.mod`'s `module` line, Rust finds the directory holding `lib.rs`/`main.rs`), and
   **`FileFacts.scope: str | None`** (Go package, C# namespace) with `SourceIndex.scopes[(lang, scope)]`
   merged from every file's top-level defines in `build_index`, which is what `scope_defines` reads.
   Make `build_index`/`extract._contains` accept a symbol of kind `module` as a container (Rust's inline
   `mod tests { }`), if they do not already.
3. **Shared registrations for all five languages** (so the walker workers never touch these files):
   `pyproject.toml` deps `tree-sitter-go>=0.23,<0.26`, `tree-sitter-c-sharp>=0.23,<0.24`,
   `tree-sitter-rust>=0.23,<0.25` (verify cp311 + macOS arm64 wheels, record versions); `treesitter.py`
   `GRAMMARS` six with `get_language`/`grammar_for` for `go`, `csharp`, `rust`; `test_grammars_load`
   covers six; `model.py` `LANG_BY_SUFFIX` `.go → go`, `.cs → csharp`, `.rs → rust`; `readers.py`
   `GO_EXTENSIONS` / `CSHARP_EXTENSIONS` / `RUST_EXTENSIONS` with the suffix-pin test still passing;
   `chunker.LINE_COMMENT` read from `RULES` (`//` for the three); `extract.WALKERS` read from `RULES`;
   `model.PARSED_LANGS` (every language with a walker) used by `git_history.py` instead of the literal
   tuple; `data_access.py` `MONGO_READS`/`MONGO_WRITES` gain the PascalCase driver names the plan lists
   for Go and C# (strip a trailing `Async` before lookup) and the `Collection("x")` /
   `GetCollection<T>("x")` / `collection::<T>("x")` markers. Pin each with a small test (a PascalCase
   name classifies; a `.go` path has `lang_of == "go"` on both sides of the dependency line).
4. **A registration test** in `test_codegraph.py`: every `RULES` entry has every field; every suffix in
   `LANG_BY_SUFFIX` maps to a language with a grammar; `PARSED_LANGS` equals the walker keys.

## Done when

Three stores + lint green, `expected.json` byte-identical, `scripts/update_expected.py --check` clean,
no pinned test changed (say so). Ledger summary must spell out, for the three walker workers: the exact
`LanguageRules` fields and their signatures, how a walker module registers (`RULES_ENTRY`), what
`scope_defines`/`member_paths`/`Resolution.scope` mean and where they are consulted, the `same_scope`
tier, and the `files_skipped` reason string for a registered-but-unwalked language.
`horch tell orchestrator "[<role>] DONE: wp/l0 ..."`, close pane.
