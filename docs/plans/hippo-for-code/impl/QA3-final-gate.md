# QA3 — The final gate: full matrix, manual verification with real git history, two loose ends

Read `impl/00-impl-context.md` first. Worktree `.worktrees/qa3`, branch `wp/qa3`, from the CURRENT tip
of `code-graph` (everything is merged: WP0-WP4, the review fixes, the smoke fixes, the Neo4j teardown
fix; the docs branch may merge while you work — merge `code-graph` into your branch again before your
final legs). Neo4j test container: name `hippo-neo4j-qa3`, port **17687** (the justfile default is fine
now — you are the only Neo4j leg left; you may simply run `just test-neo4j`). Capture every pytest exit
code to a file (`> /tmp/qa3-<leg>.log 2>&1; echo EXIT $?`) and read the summary line; never `| tail`.
Scratch server: `HIPPO_DATA_DIR=/tmp/hippo-qa3 HIPPO_STORE=ladybug .venv/bin/hippo serve --port 8013`
(never 8000, never `data/`). Ollama on the host is the real model; LLM steps take tens of seconds.

## Part A — two small loose ends (code, with tests)

1. **Commit questions over real git history.** `tests/unit/test_evals_code.py` tests `commit_questions`
   on `write_commit_history` plus a local fixture; WP2b's `git_index` fixture (yields `(ctx, source_id,
   depths)`) landed after WP4c branched. Add one case that runs `commit_questions` and `run_question`'s
   `path_fidelity` over `git_index` and asserts the same shape (the newest commit that touches ≥ 2
   symbols qualifies; a module whose only content is one class is never in the gold set). No `src/`
   change expected.
2. **Eval summary cards.** `web/routes/evals.py::SUMMARY_CARDS` has no card for `code_seeded` and
   `path_fidelity`; add both (label + one-line help) so the Evals page shows them; one test in
   `test_web_library_evals.py` that the labels render for a summary containing the keys.

## Part B — the three-store matrix, properly

`just test` (LadybugDB), `just test-fake`, `just test-neo4j`, each with the exit code captured, plus
`just lint`. Record the three summary lines verbatim. Any failure: stop, characterise (which test,
which store, reproducible?), `horch tell orchestrator` immediately with the traceback — do not fix a
failure in someone else's module without asking; a flaky-looking one must be run five times before you
call it flaky.

## Part C — PLAN.md §Verification step 4, with real history

Build a repo source that HAS git history: call `tests/conftest.py::make_code_checkout` into
`/tmp/hippo-qa3/checkout` (it is the fixture tree with three real commits), then add it as a **repo**
source over the local path (as `git_index` does: create the source with the path as `meta["url"]` and
run the pipeline, or through the UI if the Sources page accepts a local path). Also add
`samples/acme_robotics.md` as a prose source so the memory is mixed. Then walk every check in step 4
(line 489) against it, adapting the traceback to the fixture:
`File "pyapp/orders.py", line 18, in place` → a seed chip `place`, a Code graph card with
`pyapp.orders.OrderService.place -[INVOKES 1.00 same_file]-> ...`, a `Tests:` line naming
`tests.test_orders.test_place`, a `Commits:` line with a 7-char sha and the subject "Total the order in
place" (or whatever `CODE_CHECKOUT_SUBJECTS` says), and a `Subsystems:` block. Graph page: filter kind
`symbol`, open `place`, confirm signature, callers/callees, a commit in its panel, and the `subsystem`
colour mode. Analyze: seed-symbols table, Paths section, move `code_structural_scale` to 0 and confirm no
LLM call (timing in ms, no Ollama request in the log). Source page: the `In the code graph` details
under `place` with a Commits line; the header shows commits > 0 and `history_skipped` 0. Settings:
save `code_seed_weight = 2`, toggle `code_select`. CLI against the running server: `hippo path
pyapp.cli.main pyapp.billing.total`, `hippo blast pyapp.orders.OrderService.place --depth 2`,
`hippo raises pyapp.orders.OrderService.save OrderError`, `hippo history pyapp.orders.OrderService.place`
(set `HIPPO_URL`/token the way `test_cli.py`'s behind-server fixture does). MCP over stdio: call
`hippo_explain_path`, `hippo_blast_radius`, `hippo_exception_path`, `hippo_history` and one ambiguous
name to see the `ToolError` candidates (follow `docs/MCP.md`'s examples). A prose question ("Where is
Acme Robotics headquartered?") must show no card, no chips under "the question named", and
`used_code_seeds false` in its trace. Screenshot every page into `/tmp/hippo-qa3/shots/`.

## Part D — migration, once more on the final tree

Repeat WP1's check quickly: with a scratch worktree of `main` (`git worktree add /tmp/hippo-main main`,
its own venv), index `samples/acme_robotics.md` into `/tmp/hippo-qa3-old.lbug` with `FakeOllama` through
`index_source`, add one manual synonym and one TUNED edge; then open a COPY of that file with the final
`LadybugStore`, assert `CALL show_connection('SYNONYM')` lists the widened pairs, the old rows load,
and a code source can then be indexed into the same file. Remove the scratch worktree after.

## Output

`docs/plans/hippo-for-code/research/QA3-final-gate.md`: a verdict table (matrix ×3, lint, each step-4
surface, migration), the three summary lines, the screenshot paths, and a **Defects** list with
reproductions. Commit Part A's code and the report on `wp/qa3`. Stop the server, remove the scratch
worktree and `/tmp/hippo-qa3` data (keep shots). `horch tell orchestrator "[<role>] DONE: wp/qa3 — <verdict line>"`,
ledger summary, close pane.
