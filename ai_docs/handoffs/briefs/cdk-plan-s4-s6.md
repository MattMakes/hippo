# Brief: implementation plans for CDK slices S4 (test kit and commands), S5 (port) and S6 (exemplar and surfaces)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree
(`/Users/mascott/projects/hippo`) at the HEAD named in the spawn message. You write THREE files and
nothing else: `ai_docs/plans/cdk-s4-kit.md`, `ai_docs/plans/cdk-s5-port.md`,
`ai_docs/plans/cdk-s6-exemplar.md`. No code, no tests, no commits (the orchestrator commits). Two
other planners are writing `cdk-s1-registry.md` and `cdk-s2-contract.md`/`cdk-s3-runtime.md` in
parallel; do not write those. Program against the design's normative API (sections 1 and 3); list
anything you need that S2 or S3 must expose under "requires from S2/S3" rather than inventing it.

GOAL: three step-by-step implementation plans, executable by workers who have never seen the
repository, for gates CK4, CK5 and CK6 of `ai_docs/gates/rag-it-all/cdk/GATES.md`: the contract test
kit with the scaffold and the `hippo connector` commands (S4), the port of the local prose path and
the git code path onto the runtime with byte-identical published output (S5), and one exemplar
connector for a family the repository does not cover plus the probe and validate surfaces (S6).

CONTEXT (read completely, in this order): `docs/spec/connector-developer-kit.md` (all; sections 8,
9, 10, 12, 13 are your contract), `docs/spec/enterprise-graph-rag-v1.md` sections 3, 5.5, 5.7 and
13.1, `docs/rag_it_all_remaining_tasks.md` Task 6 and Task 15, `docs/CONTRACTS.md` (the ingest, CLI
and MCP sections), the code-capture plan `ai_docs/plans/rag-it-all-task-5-managed-code-capture.md`
(the FORM your plans must take) and `ai_docs/reports/2026-09-12-code-capture-plan-review.md` (what
gets a plan rejected), the code-capture acceptance evidence `ai_docs/gates/rag-it-all/task-5-code-capture/evidence-cc11.md`
and `evidence-cc11b.md` (how byte-identity and acceptance were proven and measured). Then the code:
`src/hippo/cli.py`, `src/hippo/remote.py`, `src/hippo/mcp_server.py`, `src/hippo/web/app.py` and the
routes package, `src/hippo/ingest/pipeline.py` (`add_text`, `add_upload`, `add_repo`, `start_indexing`,
`run_indexing`, `_run_managed_indexing`), `src/hippo/ingest/managed_activation.py`,
`src/hippo/ingest/prose_generation.py`, `src/hippo/ingest/code_generation.py`,
`src/hippo/store/generations.py` (`generation_checksums`), `tests/fakes/fake_store.py`,
`tests/fakes/code_capture_repo.py`, `tests/fakes/code_fixture.py`, `tests/fakes/fake_ollama.py`,
`tests/unit/test_prose_generation.py`, `tests/unit/test_code_generation.py`,
`tests/unit/test_managed_pipeline_activation.py`, `tests/unit/test_code_capture_acceptance.py`,
`tests/unit/test_cli.py`, `tests/unit/test_mcp_server.py`, `tests/unit/test_mcp_http.py`, and
`tests/unit/test_rag_surfaces.py` if it exists. Cite `file:line` at HEAD for every claim.

DECISIONS THE S4 PLAN MUST MAKE AND STATE:
1. `connectors/testing.py`: the fixture layout on disk, `run_case`, `assert_contract` with each
   assertion of the design's section 8 as a named function, the purity guard (how socket, `httpx`,
   Ollama, subprocess and clock are intercepted), `MockTransport` record/replay helpers, the
   negative-fixture convention (one per assertion, in the kit's own tests), the golden update path.
2. The scaffold: the templates `hippo connector new` writes (descriptor, `TypeExtension`, templates,
   one fixture case, one passing test), where templates live, and the test that the scaffolded
   package validates.
3. The commands in `cli.py` (`connector new|list|validate|probe|sync`), their forwarding in
   `remote.py`, argument shapes, exit codes, what is read-only, and the tests.
4. The developer guide `docs/spec/cdk-guide.md`: its outline; its examples must be the fixture
   connector so they are executed by tests.

DECISIONS THE S5 PLAN MUST MAKE AND STATE:
5. The local connector (`connectors/local/`): how `add_text`, `add_upload` (files and ZIP) and the
   sample become `list_changes`/`fetch` over the existing capture (`repo_capture.walk_tree`,
   `accepted_inputs.capture_raw_inputs`) and how its `emit` reuses `readers.py` and `chunker.py`
   unchanged.
6. The git connector (`connectors/git/`): how `add_repo` and refresh become `list_changes`/`fetch`
   over the existing clone and checkout (`managed_activation.checkout_directory`, `_clone_url`), and
   how its `emit` reuses the code walkers, `code_binding.py`, `code_history.py` and `staged_code.py`
   so native rows are unchanged.
7. The switch: exactly where `pipeline.py` and `managed_activation.py` dispatch to the runtime, with
   the legacy lane and the CD2 converting-source rule untouched; the flag or absence of a flag.
8. The byte-identity proof: a test that runs the pre-kit path and the runtime path on the same fixture
   and compares `generation_checksums`, spans, passages, native rows, receipts and coverage; what is
   allowed to differ (nothing, or an enumerated list with reasons); the LadybugDB acceptance
   invocation reusing `HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE=8`.

DECISIONS THE S6 PLAN MUST MAKE AND STATE:
9. The exemplar's family and shape. Criteria: a family the repository does not cover (work items or
   incidents), a flat export format anyone can produce (CSV or NDJSON), at least one new object kind
   with a fact template and at least one new windowed predicate with an owner family, `ts` from the
   data never from the clock, an ACL from the data, and nothing imported outside `hippo.connectors`
   public modules and `hippo.knowledge.model`. Choose one and say why.
10. The retrieval check: how a query through the existing query path (`ask.py`/`query_access.py`)
    reaches the exemplar's rendered facts, and what "citations resolve to its spans" asserts.
11. The Task 15 surfaces: the connector routes and the MCP tool that expose probe and validate
    results (create the minimum; name what Task 15 keeps for later).
12. Sizing: S4, S5 and S6 are each one worker; if any exceeds that, split and say where.

FILES:
  - own: `ai_docs/plans/cdk-s4-kit.md`, `ai_docs/plans/cdk-s5-port.md`, `ai_docs/plans/cdk-s6-exemplar.md` (all new).
  - do NOT touch: anything else.

DONE WHEN: the three plans exist with the code-capture plan's form (goal, contract with exact
signatures, file-by-file steps with `file:line` anchors, RED test list with names, GREEN commands,
the CK4/CK5/CK6 CHECK lines confirmed or replacements proposed, worktree names `s4`/`s5`/`s6`, merge
order, do-not-touch lists, "requires from S2/S3", "decisions taken", "design deviations" if any, open
questions); `ruff format --check` clean on all three; `horch done` names the paths, the counts of
decisions taken, and open questions.

REPORT: `horch note` per section written; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for
a contract question the design does not answer and you cannot decide safely.
