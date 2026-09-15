# Brief: CDK S5a — the coordinator lane and the local prose connector

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `s5a` (branch
`wp/s5a`, base = the `rag-it-all-tibs` HEAD named in the spawn message). You implement the S5a
steps of `ai_docs/plans/cdk-s5-port.md` section 7 exactly as written, with sections 3, 4.1, 5, 6
and 8 as the contract, amended by the rulings and review findings below.

GOAL: `connectors/lanes.py` (the coordinator lane, ruling R1), `connectors/local/` (the local
connector's `probe`, `list_changes`, `fetch` and `fetch_policy` over the existing capture, text and
prose-file branches), the `registry_fingerprint` seam in `ingest/prose_generation.py`, the switch
in `ingest/managed_activation.py` with the legacy lane and the CD2 rule untouched, and the
byte-identity proof for the prose path (`tests/unit/test_connector_local.py` with
`tests/fakes/connector_parity.py`): `add_text` and `add_upload` (prose files) dispatch through the
connector interface and the lane and publish generations whose `generation_checksums`, spans,
passages, receipts and `coverage_json` equal the pre-kit path's, with `Generation.registry_fingerprint`
the single allowed difference.

CONTEXT: design `docs/spec/connector-developer-kit.md` sections 7, 11 and 13; the plan's sections
1–6, 7 (S5a), 8, 9, 10–14; the landed code and evidence of S1a, S1b, S1b-fix, S2a and S4c under
`ai_docs/gates/rag-it-all/cdk/` (`SyncConnector`, `ConnectorCapabilities`, `current_registry`,
`load_registry`, `Generation.registry_fingerprint`); the task-5 ledger
`ai_docs/gates/rag-it-all/task-5-code-capture/GATES.md` (CD2). Rulings and findings that bind S5a
(`ai_docs/plans/cdk-rulings.md`, `ai_docs/reports/2026-09-15-cdk-plan-review.md`): R1 (the lane;
descriptors declare `capabilities.derivation="coordinator_lane"`, m9), R2 (`prose_generation.py`
is yours), R3, R43 / M14 (`run_managed_build` refuses `kind="connector"` with
`ManagedDispatchError`; add the branch and `test_a_connector_source_reindex_is_refused_by_dispatch`),
R47 (S1b-fix already made `prose_preparation.py` fingerprint-tolerant; do not redo it), R54 / M11
(the one `ingest` to `connectors` import edge: `managed_activation` only; `connectors.{lanes,local}`
never import `managed_activation` or `pipeline`; pin it in `tests/unit/test_layering.py`, granted;
`lanes.py` raises its own `LaneRefused`), R67 (the `check_capture` test is S5b's, not yours), m9
(type the lane's argument as `SyncConnector`, call `current_registry()`, and the fetch-policy test
compares a `mode="workspace"` observation), R65 (config models never name a field containing
`credential`). The ported connector's `configuration_json` and `coverage_json` stay byte for byte
what the prose path writes today (design §3; CK5 CRITERIA). Where a ruling and the plan differ, the
ruling wins; say so in your evidence.

FILES:
  - own: `src/hippo/connectors/lanes.py`, `src/hippo/connectors/local/**`,
    `src/hippo/ingest/prose_generation.py`, `src/hippo/ingest/managed_activation.py`,
    `tests/fakes/connector_parity.py`, `tests/unit/test_connector_local.py`, the appended lines in
    `tests/unit/test_import_order.py`, the R54 pin in `tests/unit/test_layering.py`; new
    `ai_docs/gates/rag-it-all/cdk/evidence-s5a.md`.
  - do NOT touch: everything the plan's section 10 forbids (`pipeline.py`, `readers.py`,
    `chunker.py`, `repo_capture.py`, `accepted_inputs.py`, `repos.py`, `src/hippo/knowledge/**`,
    `src/hippo/store/**`, `context.py`, `status.py`, `codegraph/**`, every other `connectors`
    module, the web package, `mcp_server.py`, `cli.py`, `remote.py`, every existing test named on
    the CK5, CD1, CD2, CD8 or CD9 lines, `docs/spec/*`, the ledgers, the checkpoint, `data/`,
    `.rag-dev-data/`); `ingest/code_generation.py` (S3b's, then S5b's).

STEPS: worktree + venv (the rulebook recipe, with the `mcp==2.1.1` pin). Baseline the plan's
section 9 S5a Fake line on the unmodified tree and record counts. RED first (section 8's S5a tests
plus the R43 and R54 tests), failures recorded; the plan's steps 2–6; GREEN on Fake and the
LadybugDB S5a line; Ruff on your files; the commit with the plan's message. Evidence file: RED and
GREEN log paths, counts per backend, the parity comparison (what was compared, the one allowed
difference), and every override.

CONSTRAINTS: the rulebook (pytest form with `-W error` and logs, never Neo4j, never `pkill -f`,
stage only owned files, never push, rebase or merge). The legacy lane and the CD2 converting-source
rule are untouched; no `Connector` or `SyncState` row is written by the lane (R5); nothing calls
the user's Ollama. No duration language.

DONE WHEN: RED recorded, then the S5a Fake and LadybugDB lines and Ruff exit 0, and
`tests/unit/test_prose_generation.py tests/unit/test_managed_pipeline_activation.py` pass
unchanged; `horch done` names the commit, counts per backend, log paths, the parity result,
overrides and open questions.

REPORT: `horch note` after each step; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a
question the plan, the rulings and the review do not answer.
