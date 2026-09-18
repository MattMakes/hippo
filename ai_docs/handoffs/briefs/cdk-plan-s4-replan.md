# Brief: re-plan CDK slice S4 section 3.1 and add slice S4c (the loader)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree
(`/Users/mascott/projects/hippo`) at the HEAD named in the spawn message. You edit ONE file and nothing
else: `ai_docs/plans/cdk-s4-kit.md`. No code, no tests, no commits (the orchestrator commits).

GOAL: the S4 plan is executable again. The review `ai_docs/reports/2026-09-15-cdk-plan-review.md`
REJECTED it on its section 3.1 (`connectors/testing.py`) and on the missing loader, while the scaffold
(3.2), the commands (3.3) and the guide (3.4) stand. Rewrite section 3.1 and add slice S4c so that every
finding the review assigns to S4 is applied, then adjust sections 4–11 to match.

CONTEXT (read completely, in this order): the review's B3, B4, M2, M5, M12, M13, M16, m6, m17, m18,
m19, m20 and its "Cross-plan consistency" section; `ai_docs/plans/cdk-rulings.md` R42, R49, R50,
R51, R55, R56 and R39 (vocabulary is never validated on read); the design
`docs/spec/connector-developer-kit.md` sections 8 and 9; the S3 plan `ai_docs/plans/cdk-s3-runtime.md`
sections 4.7 (`sync_connector`'s full signature, which gains `connector_id: str`), 5 (entry checks,
including the stored-classification refusal), 9 (`FAULT_POINTS` and the five boundary scenarios),
10 (`guard.forbid_effects`, `http.record_transport`/`replay_transport`) and 11 (the fixture
connector); the S2 plan sections 4 and 5 (`probe`, `Classification`, `ConnectorDescriptor.extension`);
the S1 plan section 5.2 (`Registry.with_builtins()`, `register(..., declared_families=...)`,
`freeze()`, `use_registry()`, `current_registry()`); and the current S4 plan whole.

REQUIRED:
1. Section 3.1 rewritten: `run_case` calls `ensure_connector(..., enabled=True)`,
   `connector_source(...)`, the replay connector's `probe`, `store_classification(...)`, then
   `sync_connector` with S3's full signature (R49), and reads `receipt.generation_id`;
   `purity_guard` is S3's `guard.forbid_effects` on the calling thread (no process-wide patching);
   `RUNTIME_FAILPOINTS` become S3 §9's five boundary scenarios on `_ReplayConnector` with S3's labels;
   `testing` re-exports S3's transports; `check_capture(connector, config, *, sample)` with five
   named capture-side rules and a negative fixture each (M12); `probe_deterministic` with its negative
   fixture (M13); `edges_fully_attributed` reads the §4 table through `emit.evidence_class(...)`
   (m18); `TOKEN_BOUND = base.PASSAGE_CHAR_BOUND` (m6); the hashed-vector algorithm moves into
   `testing.py` and `tests/fakes/fake_ollama.py` imports it (m17, name that edit as granted).
2. Slice S4c: `connectors/loader.py` with `load_registry(*, enabled_kinds, allowlist) -> LoadResult`
   (built-ins, enabled in-repo packages, allowlisted entry points, then `freeze()`; a failing entry
   point is listed with its error and does not stop loading; enabling takes effect at restart);
   `cli.cmd_connector` and the `web/app.py` lifespan call it (those lines granted to S4c); the three
   tests M2 names; its position in the merge order (before any caller of `load_registry`; S5's
   `default_registry()` and S6's enablement use it).
3. Section 3.3 adjusted for m19 (non-dry-run `sync`: `manage_sources`, `BuildActor.trusted_local()`,
   exit 2 without a stored classification, with a test) and M5 (`enabled`).
4. Section 3.2 adjusted for M16 (the template emits `NodeRef(kind=..., key={"id": ...})` and the kit
   fills `instance`; the pinned scaffold output regenerated).
5. Sections 4–11 updated: file-by-file steps, RED test names, GREEN commands, the CK4 CHECK line
   (confirm or propose the replacement that adds S4c's test file), worktrees `s4a`/`s4b`/`s4c`,
   requires-from-S1/S2/S3 with signatures copied character for character from those plans, decisions,
   deviations, open questions. Put a dated "Re-plan changelog" at the top listing each finding and
   where it is applied.

FILES:
  - own: `ai_docs/plans/cdk-s4-kit.md`.
  - do NOT touch: anything else.

DONE WHEN: the plan has the changelog, the rewritten 3.1, the S4c slice, the adjusted 3.2/3.3 and
sections 4–11; every signature it calls exists in the S1, S2 or S3 plan at the anchor it cites;
`ruff format --check` is clean on the file; `horch done` names the findings applied, the CK4 line
decision, the S4c tests and open questions.

REPORT: `horch note` per section rewritten; `horch tell orchestrator "[<role>] BLOCKED: ..."` only
for a contract the S1–S3 plans do not provide and you cannot decide safely.
