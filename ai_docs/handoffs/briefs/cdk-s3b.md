# Brief: CDK S3b — the generic staged writer, the connector generation profile, authority admission and the build-run helpers

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `s3b` (branch
`wp/s3b`, base = the `rag-it-all-tibs` HEAD named in the spawn message, after S1b merged). You
implement Task S3b of `ai_docs/plans/cdk-s3-runtime.md` section 12 (its steps) exactly as written,
with sections 4.4–4.6, 7 and 8 as the contract, amended by the rulings and review findings below.

GOAL: `knowledge/staged_records.py` (the generic staged writer that shares fencing, seal and resume
with `staged_prose.py` and `staged_code.py`, writes spans, passages, units, observations, assertions,
versions, support and alias candidates, and for code native bindings), the connector generation
profile, `BuildAuthority` admission for connector generations, and the helper extraction from
`build_run.py` with the `code_generation.py` re-bindings the plan's section 8 names, with the four
test files green and the regression line unchanged.

CONTEXT: design `docs/spec/connector-developer-kit.md` section 7 (steps 7 and 8); the plan's sections
4.4–4.6, 7, 8, 12 (Task S3b), 15–18; the S1b evidence (the `Unit` row, the widened columns, the write
path's `check_record`); `docs/rag_it_all.md` sections 7.1–7.3 (the transaction and fencing rules).
Rulings and findings that bind S3b: R38 (`ingest/code_generation.py` is yours for the section 8
re-bindings only, then S5b's), R39 (the writer relies on the store write path's `check_record`; it
does not re-validate on read), m10 (private names you reuse from `staged_code.py` and
`ingest/provenance.py` are promoted to public names under this grant, or re-exported from their
owning module, and pinned with an import test), R47 / B1 (S1b already made the two generation
comparisons fingerprint-tolerant; do not redo them). Where a ruling and the plan differ, the ruling
wins; say so in your evidence.

FILES:
  - own: the files Task S3b's commit step stages (`knowledge/staged_records.py`, the generation
    profile and authority edits at the plan's anchors, `ingest/build_run.py` and
    `ingest/code_generation.py` at the section 8 anchors, the four tests); new
    `ai_docs/gates/rag-it-all/cdk/evidence-s3b.md`.
  - do NOT touch: `src/hippo/connectors/**`, `src/hippo/store/**`, `ingest/prose_generation.py`,
    `ingest/managed_activation.py`, `ingest/pipeline.py`, `tests/fakes/**`, every existing test file
    the plan does not name, `docs/spec/*`, the ledgers, the checkpoint, `data/`, `.rag-dev-data/`.

STEPS: worktree + venv (the rulebook recipe, with the `mcp==2.1.1` pin). Baseline the plan's step 3
regression line and record counts. RED first (the plan's S3b test list), failures recorded; GREEN;
the regression line equal to baseline; lint; the commit with the plan's message. Evidence file: RED
and GREEN log paths, counts, the regression comparison, the promoted names, and every override.

CONSTRAINTS: the S1b brief's constraints hold (pytest form with `-W error` and logs, Fake first then
the LadybugDB line the plan names, never Neo4j, never `pkill -f`, stage only owned files, never push,
rebase or merge). `BuildAuthority` and the publication compare are reused, never re-implemented; the
active generation is never deleted; the code lane's native rows and checksums are unchanged (CK5).
No duration language.

DONE WHEN: RED recorded, then the S3b lines, the regression line and the Ruff lines exit 0 on Fake
and the LadybugDB line exit 0; `horch done` names the commit, counts per backend, log paths, the
promoted names, overrides and open questions.

REPORT: `horch note` after each step; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a
question the plan, the rulings and the review do not answer.
