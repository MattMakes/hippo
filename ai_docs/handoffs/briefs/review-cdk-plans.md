# Brief: design and plan review of the Connector Developer Kit

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree
(`/Users/mascott/projects/hippo`) at the HEAD named in the spawn message. You read and run; you do not
edit source, tests, the design, the plans or the ledger. Your one output is
`ai_docs/reports/<today>-cdk-plan-review.md`.

GOAL: rule whether the six implementation plans `ai_docs/plans/cdk-s1-registry.md`,
`cdk-s2-contract.md`, `cdk-s3-runtime.md`, `cdk-s4-kit.md`, `cdk-s5-port.md`, `cdk-s6-exemplar.md`
can be executed as written to meet gates CK1–CK6 of `ai_docs/gates/rag-it-all/cdk/GATES.md` and the
design `docs/spec/connector-developer-kit.md`, and whether the design itself honours the
specification's section 3 contract and the repository's invariants.

CONTEXT: `ai_docs/plans/cdk-rulings.md` (the orchestrator's rulings R1 onward; a ruling supersedes the
plan section it names, so review the plans as amended by the rulings),
`docs/spec/enterprise-graph-rag-v1.md` (sections 3, 4, 6, 13.1), the design (all sections),
`docs/rag_it_all.md` sections 4.2 (invariants I1–I14), 5, 7, the earlier design review
`ai_docs/reports/2026-09-12-code-capture-plan-review.md` (your form: BLOCKER/MAJOR/MINOR with the
per-task table, and a verdict APPROVED / APPROVED WITH CHANGES / REJECTED). Read the code every plan
cites at its `file:line` anchors and confirm each anchor is what the plan says it is.

REQUIRED:
1. SPEC: for each of CK1–CK6, does the plan's test list assert every clause of the gate's CRITERIA?
   Name any clause with no test. Does every field of the specification's section 3 records reach the
   record and column the design's section 4 names, as the S2 plan claims?
2. INVARIANTS you verify by reading the plans against the code: existing row identities stay stable
   (S1); every value that is a `Literal` today remains valid (S1); the registry refuses at
   registration and cannot be reached at emit (S1, S2); no connector path can call a model or the
   network inside `emit` (S2, S3, S4); the runtime never deletes the active generation, never deletes
   from a failed inventory, and keeps the CD2 legacy-lane rule (S3, S5); `BuildAuthority` and the
   publication compare are reused, not re-implemented (S3); the byte-identity proof in S5 compares
   what the store actually checksums; unknown policy is deny everywhere.
3. QUALITY: layering (`knowledge` must not import `connectors` or `ingest`; `connectors` may import
   `knowledge` and `ingest`; check `tests/unit/test_import_order.py` and its allowlist), duplication
   against `staged_prose.py`/`staged_code.py`/`input_binding.py`, error surfaces through
   `public_errors.py`, determinism, test honesty, and whether each slice is sized for one worker.
4. Cross-plan consistency: S2/S3's "requires from S1" and S4–S6's "requires from S2/S3" sections are
   satisfied by the other plans' contracts, with signatures that agree character for character.
5. The design's section 14 open decisions: state for each whether any plan silently assumed an
   answer.
6. The rulings: state for each ruling whether it contradicts the design, the specification's section 3
   or an invariant; a ruling you find wrong is a finding against the ruling, not against the plan.

FILES:
  - own: `ai_docs/reports/<today>-cdk-plan-review.md`.
  - do NOT touch: anything else.

DONE WHEN: the report exists with a findings table (id, severity, plan and section or `file:line`,
the gate or invariant it violates, the exact fix), a per-gate SPEC verdict, a QUALITY verdict, the
cross-plan consistency table, and a one-line verdict per plan; `ruff format --check` clean on the
report; `horch done` with the verdicts, the counts per severity, and the report path.

REPORT: `horch note` per plan reviewed; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a
missing input, never to ask whether a finding matters.
