# Brief: CDK S5b — the git code connector, the archive and code-file branches, and the code parity proof

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `s5b` (branch
`wp/s5b`, base = the `rag-it-all-tibs` HEAD named in the spawn message, after S5a, S3b and S4a
merged). You implement the S5b steps of `ai_docs/plans/cdk-s5-port.md` section 7 exactly as
written, with sections 3, 4.2, 5, 6 and 8 as the contract, amended by the rulings and review
findings below.

GOAL: `connectors/git/` (the git connector over the existing clone and checkout), the archive and
code-file branches of the local connector, the `registry_fingerprint` seam in
`ingest/code_generation.py`, the code half of the switch in `ingest/managed_activation.py`, the
code parity worlds in `tests/fakes/connector_parity.py` and `tests/unit/test_connector_git.py`;
`add_upload` (ZIP and code files) and `add_repo` dispatch through the connector interface and the
lane with native rows, checksums, spans, passages, receipts and `coverage_json` byte-identical to
the pre-kit path's; the CD1, CD2 and CD8 lines of the task-5 ledger pass verbatim; both connectors
pass the kit's `check_capture` (R67).

CONTEXT: the plan's sections 1–6, 7 (S5b), 8, 9, 10–14; S5a's evidence and code; S3b's evidence
(the `code_generation.py` re-bindings you inherit; R38); S4a's evidence (`check_capture`,
`probe_deterministic`); the task-5 ledger and `evidence-cc11.md`/`evidence-cc11b.md` (how
byte-identity was proven before). Rulings and findings that bind S5b: R1, R2 (`code_generation.py`
is yours after S3b), R4 (runtime-path parity at N=2 on the acceptance fixture's shape; the CD9 line
at N=8 is scheduled by the orchestrator, one acceptance process at a time; do not run it), R43,
R47 (`staged_code.py` is already fingerprint-tolerant), R54, R65 (`record_transport` and config
field names), R67 / M12 (the `check_capture` tests for both connectors, with a negative fixture
each if the kit does not already ship them), m9. Where a ruling and the plan differ, the ruling
wins; say so in your evidence.

FILES:
  - own: `src/hippo/connectors/git/**`, `src/hippo/connectors/local/connector.py`,
    `src/hippo/ingest/code_generation.py`, `src/hippo/ingest/managed_activation.py`,
    `tests/fakes/connector_parity.py`, `tests/unit/test_connector_git.py`, the `check_capture`
    tests (in `test_connector_local.py` and `test_connector_git.py`), the appended line in
    `tests/unit/test_import_order.py`; new `ai_docs/gates/rag-it-all/cdk/evidence-s5b.md`.
  - do NOT touch: everything the S5a brief forbids; `connectors/lanes.py` (a defect there is
    `BLOCKED`, not a patch); `prose_generation.py`.

STEPS: worktree + venv (the rulebook recipe, with the `mcp==2.1.1` pin). Baseline the plan's
section 9 S5b Fake line and record counts. RED first, failures recorded; the plan's steps 2–6;
GREEN on Fake; the CD1, CD2 and CD8 lines verbatim from
`ai_docs/gates/rag-it-all/task-5-code-capture/GATES.md`; the LadybugDB parity run of section 9;
Ruff; the commit with the plan's message. Evidence file: RED and GREEN log paths, counts per line
and backend, the parity comparison, and every override.

CONSTRAINTS: the S5a brief's constraints hold. `HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE` is never
raised above the plan's N=2 by you. No duration language.

DONE WHEN: RED recorded, then every line above exits 0; `horch done` names the commit, counts per
line, log paths, the parity result, overrides and open questions.

REPORT: `horch note` after each step; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a
question the plan, the rulings and the review do not answer.

## Amendments (rulings R69, R72; read `evidence-s5a.md` whole first)

- Follow R72: falsify the fingerprint-adoption branch on the code lane (or record that it stays
  unfalsifiable and why); register a probe kind before any "different registry" assertion; extend
  the descriptor coverage pin to the archive and code worlds; extend `connector_parity.py` rather
  than duplicating it; `LocalConnector.list_changes` and `_member` raise `NotImplementedError`
  naming you for archives and code files, which you replace.
- The loader keeps `git` as a built-in entry by the same rule as `local` (R69); add the git case
  to that loader test (one granted line in `tests/unit/test_connector_loader.py`).
- Base your worktree on the HEAD named in the spawn message, which includes S5a, S3b and S4a.

