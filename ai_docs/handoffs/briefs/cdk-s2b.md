# Brief: CDK S2b — rendering and the batch-to-records binder

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `s2b` (branch
`wp/s2b`, base = the `rag-it-all-tibs` HEAD named in the spawn message, after S2a and S1b merged).
You implement Task S2b of `ai_docs/plans/cdk-s2-contract.md` section 10 (its five steps) exactly as
written, with sections 7, 8 and 9 as the contract, amended by the rulings and review findings below.

GOAL: `connectors/render.py` and `connectors/emit.py` (plus the two test files the plan names) exist:
every emission batch binds totally onto the knowledge records with identities from `keys.py`,
evidence classes from the derivation table, every span verified against the revision bytes, direction
and ownership enforced with the developer-facing messages, one `Unit` per template output, a derived
`Passage` per rendered fact and rendered edge, and the CK2 CHECK line green.

CONTEXT: design `docs/spec/connector-developer-kit.md` sections 4, 5, 6; the plan's sections 7, 8, 9,
10 (Task S2b), 12–16; the S2a and S1b evidence files under `ai_docs/gates/rag-it-all/cdk/`; the S3,
S4 and S6 plans' "requires from S2" items that name `emit` or `render`. Rulings
(`ai_docs/plans/cdk-rulings.md`) and review findings (`ai_docs/reports/2026-09-15-cdk-plan-review.md`)
that bind S2b: R6 (rendered facts get a `Unit` and a derived `Passage` over the record span;
identity-only foreign endpoints), R16 and R39 (the binder checks against `current_registry()` and
calls `Registry.check_record` on every record it builds), R40 (extension evidence sources carry
their class: read it through `Registry.evidence_source_definition`; keep the plan's refusal of
invalid (family, source) pairs), R42 (the bound message), R45 (built-in locator verifiers are YOUR
table in `emit.py`, consulted before an extension kind's `verifier`; a kind with neither is refused),
R48 / B2 (every span's `policy_id` is `RevisionInput.span_policy_id`, never the artifact's current
policy), R53 / M6 (an identity-only foreign endpoint is keyed by its declared `NodeRef.instance`),
M7 (`Provenance.observed_at` lands in `ArtifactRevision.source_updated_at`; the totality row asserts
the fetch's value), m4 (parametrize `test_unregistered_or_undeclared_type_at_bind_is_refused` over
S1's `test_register_refuses` cases), m18, m21. Where a ruling and the plan differ, the ruling wins;
say so in your evidence.

FILES:
  - own: the four new files Task S2b creates and their two tests as the plan names them; in
    `keys.py` only the base class of `KeyPartsRefused`; new `ai_docs/gates/rag-it-all/cdk/evidence-s2b.md`.
  - do NOT touch: every other S2a file (a defect there is `BLOCKED`, not a patch); everything the S2a
    brief forbids.

STEPS: worktree + venv (the rulebook recipe, with the `mcp==2.1.1` pin). RED first (the plan's Task
S2b test list, with the amendments), failures recorded; then the plan's steps; then the commit with
the plan's message. Run the CK2 CHECK line of `ai_docs/gates/rag-it-all/cdk/GATES.md` verbatim and the
CK7 Ruff lines over `src/hippo/connectors`. Write the evidence file: RED and GREEN log paths, counts,
the totality table's row count against `SPEC_FIELDS`, and every ruling-over-plan override.

CONSTRAINTS: the S2a brief's constraints hold. `bind_batch` is pure and deterministic: no store, no
socket, `httpx`, Ollama, subprocess or clock; `recorded_from` is the generation instant passed in.
No `KnowledgeObject(` outside `keys.py`. No duration language.

DONE WHEN: RED recorded, then the CK2 CHECK line and the Ruff lines exit 0; every "requires from
S2" item of S3, S4 and S6 that names `emit` or `render` is satisfied verbatim and listed in the
evidence; `horch done` names the commit, counts, log paths, overrides and open questions.

REPORT: `horch note` after each plan step; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for
a question the plan, the rulings and the review do not answer.
