# Brief: CDK S4a — the contract test kit (`connectors/testing.py`)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `s4a` (branch
`wp/s4a`, base = the `rag-it-all-tibs` HEAD named in the spawn message, after S3c merged). You
implement the S4a task of `ai_docs/plans/cdk-s4-kit.md` (section 3.1 as the contract; section 4
"S4a" steps; section 5's `test_connector_testing_kit.py`; section 6's S4a lines), amended by the
rulings and review findings below. The plan's changelog maps each review finding to its section;
read it first.

GOAL: `src/hippo/connectors/testing.py` gives a connector developer `run_case`, `check_contract`,
`check_capture` (five named capture-side rules), `assert_emit_pure` on S3a's `forbid_effects`,
`probe_deterministic`, `assert_runtime_resilience` over S3's five boundary scenarios on the replay
connector, the golden update path, `registry_diff`, `scratch_workspace`, `hashed_embedding` and the
re-exported S3a transports, with a negative fixture per assertion; the S4a tests green on Fake and
LadybugDB; the fake Ollama's `embed_text` imports the hashed-vector algorithm from the kit.

CONTEXT: the plan's sections 3.1, 4 (S4a), 5 (S4a), 6, 7, 9, 10, 11; both reviews
(`ai_docs/reports/2026-09-15-cdk-plan-review.md` B3, B4, M12, M13, m6, m17, m18, m20;
`ai_docs/reports/2026-09-15-cdk-s4-replan-review.md` N1, N3, N4 and its signature table); the
landed code and evidence of S2a, S2b, S3a, S3b, S3c and S4c under `ai_docs/gates/rag-it-all/cdk/`
(the exact names of `sync_connector`, `store_classification`, `ensure_connector`,
`connector_source`, `FAULT_POINTS`, `forbid_effects`, `record_transport`, `replay_transport`,
`evidence_class(registry, ...)`, the fixture connector). Rulings that bind S4a
(`ai_docs/plans/cdk-rulings.md`): R42 (`TOKEN_BOUND = base.PASSAGE_CHAR_BOUND`), R49 (one guard, one
runtime entry, `ensure_connector(..., enabled=True)`, the five scenarios by S3's labels, transports
re-exported), R57, R63 (N1: register only inside `extension_scope()` or under
`use_registry(Registry.with_builtins())`; N3: hash definitions through the registry's canonical
schema; N4: read passages with `store._native_rows("Passage", generation_id=...)`; m18:
`edges_fully_attributed` calls `emit.evidence_class(current_registry(), ...)`), R64 (tighten
`loader._already_registered` to compare evidence-source definitions through
`Registry.evidence_source_definition`, the one `loader.py` edit granted to you, with a test), R65
(clear `http/` before re-recording; the guard reports one violation per `emit` call). Where a
ruling and the plan differ, the ruling wins; say so in your evidence.

FILES:
  - own: `src/hippo/connectors/testing.py`, `tests/unit/test_connector_testing_kit.py`, the body of
    `embed_text` in `tests/fakes/fake_ollama.py` (m17), one appended line in
    `tests/unit/test_import_order.py`, the R64 lines of `src/hippo/connectors/loader.py` and their
    test; new `ai_docs/gates/rag-it-all/cdk/evidence-s4a.md`.
  - do NOT touch: every other `connectors` module (a defect there is `BLOCKED`, not a patch),
    `src/hippo/knowledge/**`, `src/hippo/ingest/**`, `src/hippo/store/**`, `cli.py`, `remote.py`,
    the web package, `tests/fakes/fixture_connector/**`, `tests/unit/test_layering.py`,
    `docs/spec/*`, the ledgers, the checkpoint, `data/`, `.rag-dev-data/`.

STEPS: worktree + venv (the rulebook recipe, with the `mcp==2.1.1` pin). RED first (the plan's S4a
tests), failures recorded; GREEN; the three S4a lines of section 6 (Fake, LadybugDB, the fake-Ollama
consumers with the plan's anyio filter recorded as form (b)); Ruff on your files; the commit with the
plan's message; the fallback split S4a-1/S4a-2 the plan names if the budget runs short. Evidence
file: RED and GREEN log paths, counts per line, every negative fixture by assertion name, and every
override.

CONSTRAINTS: the S3a brief's constraints hold. The kit never patches module attributes; every
assertion has a negative fixture that fires it and a positive fixture that passes; `run_case` writes
only into a scratch workspace; nothing calls the user's Ollama. No duration language.

DONE WHEN: RED recorded, then the S4a lines and Ruff exit 0; `horch done` names the commit, counts,
log paths, the negative-fixture table, overrides and open questions.

REPORT: `horch note` after each step; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a
question the plan, the rulings and the reviews do not answer.
