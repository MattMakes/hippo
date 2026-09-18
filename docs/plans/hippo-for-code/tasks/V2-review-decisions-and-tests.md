# V2 — Judgment review of PLAN.md: decisions, fidelity, sequencing, testability (worker: fresh Opus)

You are a herdr WORKER. Read `00-shared-context.md` (rules only). Review `docs/plans/hippo-for-code/PLAN.md`.
You are the "is this the right plan and can it be built as written" reviewer. Output:
`docs/plans/hippo-for-code/research/V2-decision-review.md`. Do not edit PLAN.md or any source file.

Read first: `inputs/A-existing-plan-phase1.md` "Context" section (user decisions), `research/R5-reconciliation.md`
(conflict list), `research/R3-retrieval-analysis.md` (fidelity), `research/R2-ingest-evals-tests.md` §R2.8
(test conventions). Then PLAN.md in full.

- **V2.1 User decisions.** For each bullet in A's "User decisions" and "Deferred with reasons": is it kept,
  moved, or reversed in PLAN.md, and if reversed, is it listed under "Confirm with user" with a reason?
  Any silent drop is a `blocker`.
- **V2.2 Conflict coverage.** Every row of R5's matrix has a Decision Log entry with a cited research id.
  List missing or uncited ones.
- **V2.3 Fidelity.** The plan's edge-weight rule, specificity rule, seeding and `link_top_k` treatment: do they
  leave a no-code graph byte-identical to today (per R3.10)? Is the FIDELITY.md sentence the plan proposes true?
- **V2.4 Sequencing.** WPs in dependency order? Can each WP land as its own green PR (tests pass on all three
  stores) without the later WPs? Identify any WP that cannot be tested until a later one exists.
- **V2.5 Testability.** For each WP's tests: runnable on fake / LadybugDB / Neo4j per R2.8 conventions? Does the
  fixture plan build a real git repo in `tmp_path`? Do any tests need an LLM (they must not, except where the
  plan says so and uses FakeOllama rules)?
- **V2.6 Phase calls.** For each phase-2 deferral: is the cost line credible and is the phase-1 design leaving
  the hook for it (e.g. columns/tables that phase 2 needs, so no migration later)?
- **V2.7 Risk.** The three riskiest assumptions in the plan, each with the cheapest experiment that would
  de-risk it before WP1 starts.
- **V2.8 Scope.** Anything in PLAN.md that neither A nor B asked for (scope creep), and anything both asked
  for that is absent (scope loss).

Output: summary table first, then bullets `PLAN.md:LINE — finding — recommendation` tagged `blocker` / `fix` / `nit`.
Be specific enough that the plan's author can apply each item without re-deriving it.
Finish with `horch tell orchestrator "[<role>] DONE: V2 <n> blockers, <m> fixes, <k> nits -> <path>"` and close your pane.
