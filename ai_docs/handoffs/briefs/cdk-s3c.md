# Brief: CDK S3c — the sync runtime and the fixture connector

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `s3c` (branch
`wp/s3c`, base = the `rag-it-all-tibs` HEAD named in the spawn message, after S2b, S3a and S3b
merged). You implement Task S3c of `ai_docs/plans/cdk-s3-runtime.md` section 12 (its steps) exactly
as written, with sections 4.7, 5, 6, 9 and 11 as the contract, amended by the rulings and review
findings below.

GOAL: `connectors/sync.py` (`sync_connector` and the nine steps of the design's section 7 as named
functions with S3's fault points), `tests/fakes/fixture_connector/` (ruling R10), the failure matrix
of the plan's section 9 with the review's added rows, and the CK3 CHECK lines of
`ai_docs/gates/rag-it-all/cdk/GATES.md` green on Fake and LadybugDB.

CONTEXT: design `docs/spec/connector-developer-kit.md` sections 7 and 8; the plan's sections 4.7, 5,
6, 9, 11, 12 (Task S3c), 13–18; the evidence files of S1b, S2a, S2b, S3a and S3b under
`ai_docs/gates/rag-it-all/cdk/`; the re-planned S4 plan's section 3.1 (what the kit calls:
`sync_connector`'s full signature, `store_classification`, `ensure_connector`, `connector_source`,
the five boundary scenarios by label). Rulings and findings that bind S3c
(`ai_docs/plans/cdk-rulings.md`, `ai_docs/reports/2026-09-15-cdk-plan-review.md`): R48 / B2 (record
the first capture's policy in `ArtifactRevision.metadata_json["span_policy_id"]` and pass it as
`RevisionInput.span_policy_id`; matrix row M8b), R49 / B4 (`sync_connector` gains `connector_id:
str`; the stored-classification refusal; `FAULT_POINTS` and the five boundary scenarios with the
labels the S4 plan cites; `contextvars.copy_context().run(...)` per worker, m20), R51 / M5
(`ensure_connector` defaults to `enabled=False`; a disabled instance is refused at entry, with its
test), R52 / M3 and M4 (a stored policy is refreshed only when `expires_at - now <
policy_ttl_seconds / 2`, row M21; `no_changes` is decided after computing the candidate generation
by `manifest_hash` equality and no policy change, with `test_a_template_version_bump_rebuilds_an_unchanged_partition`),
M15 (`fetch` of an id absent from the export raises `ProviderNotFoundError`; the fixture declares
`ConnectorCapabilities(acls=True, inventory=True)`), R46 / m7 (sync checks each registered
definition equals `descriptor.extension`), R60 (R-S3-7: a no-argument `FixtureConnector`,
`fixtures/basic` with two or more upserts, `inventory=True`, probe sampling through its own
`list_changes` and `fetch`), R21 (classification written only on change), R63 (`evidence_class(registry,
...)`), m12 (append `hippo.connectors.sync`, `hippo.connectors.emit` and
`hippo.knowledge.staged_records` to `test_import_order.py`'s `MODULES`), m13 (M20's spy accounts for
M9's `collect_generation(G1)` call), m15 (the pending log lives in the raw store; `canonical_uri`
updates when it changes), m16 (row M22: between first capture and first publication a partition
source contributes nothing to a query session), and the S1a-fix finding that the projection's
`exclusions` counter surfaces in `Generation.coverage_json` under `excluded_vocabulary` (your
decision where exactly; say it). Where a ruling and the plan differ, the ruling wins; say so in
your evidence.

FILES:
  - own: the files Task S3c's commit step stages (`connectors/sync.py`, the fixture connector
    package under `tests/fakes/fixture_connector/`, `tests/unit/test_connector_sync.py`), the three
    appended lines in `tests/unit/test_import_order.py`; new `ai_docs/gates/rag-it-all/cdk/evidence-s3c.md`.
  - do NOT touch: every other `connectors` module (a defect there is `BLOCKED`, not a patch),
    `src/hippo/knowledge/**`, `src/hippo/ingest/**`, `src/hippo/store/**`, `tests/fakes/fake_store.py`,
    `tests/unit/test_layering.py`, `docs/spec/*`, the ledgers, the checkpoint, `data/`, `.rag-dev-data/`.

STEPS: worktree + venv (the rulebook recipe, with the `mcp==2.1.1` pin). RED first (the plan's S3c
tests plus rows M8b, M21, M22 and the M4/M5 tests), failures recorded; GREEN; the CK3 CHECK lines
verbatim (Fake, then LadybugDB with reopen proven); lint; the commit with the plan's message.
Evidence file: RED and GREEN log paths, counts per backend, the matrix with every row's test name,
and every override. Neo4j is root-owned: write nothing for it, run nothing on it.

CONSTRAINTS: the S3a brief's constraints hold. The runtime never deletes the active generation,
never deletes after a failed inventory, publishes only through `BuildAuthority`, and forbids
network, model and clock use inside `emit` through S3a's guard. Unknown policy is deny. No duration
language.

DONE WHEN: RED recorded, then both CK3 CHECK lines and the Ruff lines exit 0; every "requires from
S3" item of the S4, S5 and S6 plans that names `sync` is satisfied verbatim and listed in the
evidence; `horch done` names the commit, counts per backend, log paths, the matrix, overrides and
open questions.

REPORT: `horch note` after each step; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a
question the plan, the rulings and the reviews do not answer.

## Amendments from S3a and S3b (rulings R65 and later; read `evidence-s3a.md` and `evidence-s3b.md` first)

- Widen `guard.FORBIDDEN_CALLS` by `time.process_time_ns`, `time.thread_time` and
  `time.thread_time_ns` and update its pin test (R65; the one S3a file you may edit).
- The guard is thread-local: each emit worker enters `forbid_effects()` inside its own thread, under
  `contextvars.copy_context().run(...)` for the context, and the runtime expects at most one reported
  violation per `emit` call.
- Add `guard`, `http`, `credentials`, `sync` and the S2b modules to `connectors/__init__.py`'s
  module list if S2b has not.
- Base your worktree on the HEAD named in the spawn message, which includes S1b-fix, S2b, S3a and S3b.
- R66: the registry is loaded before any lifecycle write (pin it with the two tests R66 names), and
  a tombstoned version's `unit_id` may dangle after collection (document it in `sync.py`).

