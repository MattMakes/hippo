# Brief: narrow re-review of the re-planned CDK slice S4 (sections 3.1 and 3.5 only)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree
(`/Users/mascott/projects/hippo`) at the HEAD named in the spawn message. Read-only except your one
output: `ai_docs/reports/2026-09-15-cdk-s4-replan-review.md`.

GOAL: rule whether the re-planned `ai_docs/plans/cdk-s4-kit.md` (changelog at its top) now meets the
findings that rejected it in `ai_docs/reports/2026-09-15-cdk-plan-review.md`: B3, B4, M2, M5, M12,
M13, M15, M16, m6, m17, m18, m19, m20, and whether its section 3.1 (`connectors/testing.py`) and
section 3.5 (slice S4c, `connectors/loader.py`) call only signatures the S1, S2 and S3 plans provide,
as amended by rulings R39–R60 in `ai_docs/plans/cdk-rulings.md`. Sections 3.2–3.4 stand from the
first review; check them only where the changelog says they changed (M16, m19, R59).

CONTEXT: the first review's form (BLOCKER/MAJOR/MINOR table with exact fixes, per-finding verdict);
S3's plan sections 4.7, 5, 9, 10, 11; S2's plan sections 4, 5; S1's plan section 5.2; S1a's landed
code at `src/hippo/knowledge/registry.py` (merged at `d0bd052`; `Registry.check_record`,
`current_registry`, `use_registry`, `extension_scope`, `with_builtins`, `freeze`,
`evidence_source_definition` pending in S1b) and its evidence `ai_docs/gates/rag-it-all/cdk/evidence-s1a.md`.

REQUIRED: for each finding above, CLOSED or OPEN with the exact remaining fix; every signature in
3.1 and 3.5 checked against the providing plan or the landed S1a code, character for character; the
R49 order versus the plan's `prepare_instance` order (is the difference harmless?); the freeze-once
rule against pytest (the plan's gotcha) and against `hippo serve` restarts; the CK4 CHECK line
replacement; a verdict APPROVED / APPROVED WITH CHANGES / REJECTED for 3.1 and for 3.5 separately.

FILES:
  - own: `ai_docs/reports/2026-09-15-cdk-s4-replan-review.md`.
  - do NOT touch: anything else.

DONE WHEN: the report exists with the findings table, the per-finding closure table, the signature
table, and the two verdicts; `ruff format --check` clean; `horch done` with the verdicts and counts.

REPORT: `horch note` per section; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a
missing input.
