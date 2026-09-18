# Brief: CDK S3a — the emit guard, the bounded HTTP client and credentials

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `s3a` (branch
`wp/s3a`, base = the `rag-it-all-tibs` HEAD named in the spawn message, after S2a merged). You
implement Task S3a of `ai_docs/plans/cdk-s3-runtime.md` section 12 (its steps) exactly as written,
with sections 4.1–4.3 and 10 as the contract, amended by the rulings and review findings below.

GOAL: `connectors/guard.py` (the per-thread `forbid_effects` that is the ONE purity guard for the
runtime and the kit), `connectors/http.py` (the bounded client: timeout, size, retry with jitter,
`Retry-After`, attempt and duration caps, the six error classes, `record_transport` and
`replay_transport`, URL redaction) and `connectors/credentials.py` (environment and file references
first), with their three test files green.

CONTEXT: design `docs/spec/connector-developer-kit.md` sections 7 (step 5) and 8; the plan's sections
4.1–4.3, 10, 12 (Task S3a), 15–18; the S2a evidence; the re-planned S4 plan's section 3.1 (the kit
re-exports your guard and transports: their names and errors must be what it cites). Rulings and
findings that bind S3a: B3 / R49 (yours is the only guard; S4 sets `testing.purity_guard =
guard.forbid_effects`; no process-wide patching anywhere), m20 (the forbidden set also names
`time.clock_gettime`, `time.clock_gettime_ns`, `time.process_time`, `time.sleep`, thread start,
`os.fork`, `os.posix_spawn`, `time.localtime`, `sys.setprofile`, `threading.setprofile`), B4 (the
transports are specified once, here; `replay_transport` raises `ProviderMalformedError` on an
unexpected request), R27 (the store clock is the one clock the guard intercepts). Where a ruling and
the plan differ, the ruling wins; say so in your evidence.

FILES:
  - own: the files Task S3a's commit step stages (the three modules and their three tests); new
    `ai_docs/gates/rag-it-all/cdk/evidence-s3a.md`.
  - do NOT touch: `src/hippo/knowledge/**`, `src/hippo/ingest/**`, `src/hippo/store/**`, every other
    `connectors` module, `tests/fakes/**`, `tests/unit/test_layering.py`, `test_import_order.py`,
    `docs/spec/*`, the ledgers, the checkpoint, `data/`, `.rag-dev-data/`.

STEPS: worktree + venv (the rulebook recipe, with the `mcp==2.1.1` pin). RED first (the plan's S3a
test list plus m20's names), failures recorded; then the plan's GREEN step; then the commit with the
plan's message. Run the plan's S3a line and the CK7 Ruff lines over your files. Evidence file: RED and
GREEN log paths, counts, the full forbidden set, and every override.

CONSTRAINTS: the S2a brief's constraints hold. The guard is per thread and re-entrant safe; it never
patches module attributes. Nothing here reads `.rag-dev-data/` or any real credential; tests use
environment variables and temporary files they create. No duration language.

DONE WHEN: RED recorded, then the S3a line and the Ruff lines exit 0; the names the S4 plan's section
3.1 re-exports exist exactly; `horch done` names the commit, counts, log paths, overrides and open
questions.

REPORT: `horch note` after each step; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a
question the plan, the rulings and the review do not answer.
