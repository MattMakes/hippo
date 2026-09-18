# E2F — Fix two things the Go real-repository run found; document the third

Read `impl/00-impl-context.md` first (rules, worktree + venv, three-store matrix, exit-code capture).
Worktree `.worktrees/e2f`, branch `wp/e2f`, from the CURRENT tip of `code-graph`. Neo4j test
container: name `hippo-neo4j-e2f`, port **17713**. Spec: `research/E2-go-mgodatagen.md` §Defects
(exact reproductions and evidence there).

1. **Symbol id collision (Defect 1, major, not Go-specific).** `symbol_id(source_id, path, qualname)`
   gives a file's module symbol and a same-named top-level member the SAME id (`main.go`'s module
   `main` and `func main`; `foo.py`'s module `foo` and `def foo` at the repo root), so one is silently
   destroyed at the store write (the extractor counted 230 symbols, the store held 229, and a node
   carried two DEFINED_IN edges and no CONTAINS). Fix in `codegraph/model.py`: the id must
   distinguish the module symbol from members — include the kind for modules (e.g.
   `make_id("symbol-", f"{source_id}:{path}:module:{qualname}")` for kind `module`, unchanged for
   others) or an equivalent that keeps D4's path-namespacing. Check every place that recomputes a
   symbol id from `(source_id, path, qualname)` (`scripts/update_expected.py`, `git_history.py`'s
   HEAD mapping, `paths.resolve_symbol`, the indexer's REFERS_TO linker, tests) and route them through
   one function. Tests: a Go `main.go` with `func main` and a Python `foo.py` with `def foo` through
   `extract_code` → the indexer → both symbols present with distinct ids, CONTAINS module→function,
   one DEFINED_IN each; the golden test and `expected.json --check` stay clean (ids are not in the
   file; if `mentions`/`definitions` rows moved, say why).
2. **Git history follows renames (Defect 3, moderate).** `git_history.py` diffs with `--no-renames`,
   so a content-preserving rename is a full delete+add: the rename commit is attributed as MODIFIES to
   every symbol in the file, and a symbol's real authorship commit before the rename is invisible.
   Turn rename detection on (`-M`, drop `--no-renames`), parse the `rename from` / `rename to`
   headers, and keep an alias map while walking newest → oldest so that a hunk in the OLD path at an
   older commit maps to the HEAD symbol at the NEW path by `(head_path, qualname)`. Tests in
   `test_git_history.py` (real git in `tmp_path`): a commit that renames a file with no content change
   yields NO MODIFIES; a commit that renames AND edits one function yields MODIFIES for that function
   only; a commit that edited a function BEFORE the file was renamed still yields MODIFIES to the HEAD
   symbol; `expected.json`'s `modifies` section is unchanged (the fixture history has no renames —
   verify). Update the README "History stops at renames" limitation and the CONTRACTS row.
3. **Variable collection names (Defect 2) — document, do not build.** A `Collection(coll.Name)` call
   with a non-literal argument yields no data object by design (D9: literals only). Add one Known
   limitations line to `README.md` naming the shape (config-driven data tools; EF DbSets are the C#
   analogue) and a row to `ai_docs/add_langs.md`'s deviations table.

Done when three stores + lint green, `scripts/update_expected.py --check` clean, no pinned assertion
weakened, ledger summary (the id scheme, the alias-map rule, the counts you verified unchanged),
`horch tell orchestrator "[<role>] DONE: wp/e2f ..."`, close pane.
