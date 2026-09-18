# V3 — Final mechanical re-check of the finished PLAN.md (worker: fresh Codex Sol)

You are a herdr WORKER. Read `00-shared-context.md` (rules only). `docs/plans/hippo-for-code/PLAN.md` has been
through two reviews and three rounds of edits since the last mechanical check. Re-run every check in
`V1-review-paths-and-ddl.md` (V1.1–V1.8) on the CURRENT file, and add the consistency checks below.
Output: `docs/plans/hippo-for-code/research/V3-final-check.md`. Do not edit PLAN.md or source.

Additional checks (all mechanical):

- **V3.1 One spelling per setting.** `grep -o 'code_[a-z_]*' PLAN.md | sort | uniq -c`; every name must appear
  in the Settings table with default, `SETTING_RULES` bounds and a help-text mention. Flag any name used in a WP
  but absent from the table, or in the table but never used.
- **V3.2 The relation table vs the prose.** The "which relations enter igraph" table, the edge-weight formula, the
  FIDELITY.md sentence, Ruling 2 in `tasks/S3-v2-rulings.md`, and every WP that mentions `DEFINED_IN`, `REFERS_TO`,
  `MODIFIES`, `SYNONYM` or `code_structural_scale` must agree. Quote any two places that disagree.
- **V3.3 Decision Log vs later sections.** For each D1–D25 row, find the section that implements it and confirm
  the same choice (e.g. D20 module paths vs the package layout block vs WP file lists; D22 settings vs the
  Settings table; D8 history vs WP2b vs Ruling 6 spelling `code_history_depth`).
- **V3.4 S2/S3 rulings landed.** For each of the 18 items in `tasks/S2-staff-decisions.md` and the 7 rulings in
  `tasks/S3-v2-rulings.md`, cite the PLAN.md line where it is implemented, or flag it missing. Rulings 3, 4, 5
  override S2.7, S2.15, S2.17 respectively; confirm the overridden text is gone.
- **V3.5 Pinned tests.** Every test file:line in the pinned-test list exists at that line with the assertion
  described (`sed -n`). Flag drift.
- **V3.6 Fixture and expected.json.** The fixture tree, the `expected.json` key scheme (ordinal + subject, never
  SHA), and the fixture builder's fixed git identity are each stated exactly once and agree.
- **V3.7 Appendix.** Every "Review responses" entry refers to a real V1/V2 finding and the response matches what
  the body now says.

Output format as V1: summary table, then `PLAN.md:LINE — says — should be (evidence)` bullets tagged
`blocker` / `fix` / `nit`. Finish with `horch tell orchestrator "[<role>] DONE: V3 <n> blockers, <m> fixes, <k> nits -> <path>"`
and close your pane.
