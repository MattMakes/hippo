# E1F-c — Two UI gaps the territory-updater run showed

Read `impl/00-impl-context.md` first (rules, worktree + venv, three-store matrix, exit-code capture).
Worktree `.worktrees/e1fc`, branch `wp/e1fc`, from the CURRENT tip of `code-graph`. Neo4j test
container: name `hippo-neo4j-e1fc`, port **17707**. Small task: templates and one route, under an hour.
Spec: `research/E1-territory-updater.md` §Surprises, the two bullets "The Ask page's summary line
undercounts anchoring" and "The Status page's code card is populated server-side but never rendered".

1. **Status page renders the Code card.** `GET /api/status` already returns `code` (`symbols`,
   `data_objects`, `code_edges`, `commits`, `languages`, `unresolved_calls`, `history_skipped`, built by
   `status.py::_code_card`), but `web/templates/partials/status.html` never shows it. Add a "Code" card
   in the same style as the existing cards (one line per non-zero field; languages joined with ", ";
   hidden entirely when `symbols == 0`). Test in `test_web_base.py`: over `code_index` the partial shows
   the symbol count and the languages; over the prose `indexed` fixture no Code card renders.
2. **The Ask page's summary line counts symbol seeds.** "Found through the graph: N fact(s) kept, M seed
   entities…" reads as if nothing anchored on a stack-trace question where five symbol seeds drove the
   answer. Extend the line (find it in `partials/answer.html` or the Ask route) to add "K symbol seed(s)"
   when `trace.seed_symbols` has lexical (non-dense) entries, leaving the prose wording byte-identical
   when K is 0 (a test pins both).

Touch only `web/templates/partials/{status,answer}.html`, `web/routes/pages.py` if the line is built
there, and the two test files. Three stores + lint green, no pinned assertion changed beyond the two you
add, ledger summary, `horch tell orchestrator "[<role>] DONE: wp/e1fc ..."`, close pane.
