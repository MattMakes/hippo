# V1 — Mechanical review of PLAN.md: names, paths, DDL, signatures (worker: fresh Codex Sol)

You are a herdr WORKER. Read `00-shared-context.md` (rules only). Review `docs/plans/hippo-for-code/PLAN.md`
against the repository. You are the "does this thing exist" reviewer. Output:
`docs/plans/hippo-for-code/research/V1-path-check.md`. Do not edit PLAN.md or any source file.

Checks, all mechanical, all with evidence:

- **V1.1 Paths.** Every `src/hippo/...`, `tests/...`, `docs/...` path named in PLAN.md: exists, or is marked `new`.
  Table: `| path | in plan as | exists? | verdict |`.
- **V1.2 Symbols.** Every existing function/class/method/setting/route/template the plan says it will MODIFY:
  grep it. Report the ones that do not exist or whose signature differs from what the plan states
  (e.g. the plan says `Retriever.retrieve(..., seed_nodes=None)` will be added — confirm `retrieve` exists and
  list its current parameters).
- **V1.3 Store parity.** For each store method the plan adds: is it specified for LadybugDB, Neo4j and
  FakeStore with identical names and row shapes? List any that are missing a backend.
- **V1.4 DDL.** Every DDL statement in the plan: does it match a PASS row in `research/R4-spike-results.md`?
  Flag any DDL that was not tested or that R4 marked FAIL/PARTIAL.
- **V1.5 Settings.** Every new setting: has a default, min/max for `SETTING_RULES`, and a mention of the
  settings page. Cross-check against R1.7.
- **V1.6 Tests.** Every test file the plan names: does a file with that name already exist (collision) and does
  the plan say which store matrix it runs on?
- **V1.7 Contracts.** The `docs/CONTRACTS.md` rows the plan proposes: same column format as the existing file.
- **V1.8 Internal consistency.** Settings, module paths, rel names and ω values used in one section must match
  every other section (e.g. `STRUCT` vs `CODE_EDGE`, `analysis/paths.py` vs `hipporag/paths.py`,
  `history_commits` default). List every mismatch with line numbers in PLAN.md.

Output format: the summary table first (`| id | count checked | defects |`), then one bullet per defect:
`PLAN.md:LINE — <what it says> — <what is true> (evidence file:line)`. Severity tag: `blocker` (would send an
implementer to a file that does not exist or a DDL that fails), `fix` (wrong detail), `nit`.
Finish with `horch tell orchestrator "[<role>] DONE: V1 <n> blockers, <m> fixes, <k> nits -> <path>"` and close your pane.
