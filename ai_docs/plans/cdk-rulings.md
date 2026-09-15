# Orchestrator rulings on the CDK plans

Rulings on the deviations and open questions the slice plans raise. A ruling binds the implementer
briefs and the plan review; a plan section that contradicts a ruling is superseded by it. Numbered
R1 onward; later rulings are appended, never renumbered.

## S4, S5, S6 (plans committed at `937fbb8`)

- **R1 — S5 coordinator lanes (S5 deviation 1–4): ratified.** The local and git connectors implement
  `probe`, `list_changes`, `fetch` and `fetch_policy`; their derivation half stays the reviewed prose
  and code coordinators through `connectors/lanes.py`. The design's §11 already disposes of these
  paths as wrapped without changing their output, and S5 §3.1 gives five anchored reasons a
  per-revision `emit` cannot be byte-identical. Conditions: the descriptors declare the lane in their
  capabilities so kit assertions that need `emit` are skipped by declaration, never by exception; the
  kit's capture-side assertions run on both connectors, so S5b merges after S4a. CK5 CRITERIA reworded
  as S5 §9 proposes.
- **R2 — S5 ownership (S5 open question 1): ratified.** S5a owns `ingest/prose_generation.py`, S5b
  owns `ingest/code_generation.py`, each for one keyword argument. The S1 plan states the pre-kit
  lanes are not changed (`cdk-s1-registry.md` §2), so S1 does not edit either file.
- **R3 — `connectors/sync.py` re-export (S5 open question 2): ratified as proposed.** S5b makes the
  one-line dispatch or re-export in `connectors/sync.py` after S3 merges; S3 leaves no seam for it.
- **R4 — LadybugDB at the recorded size (S5 open question 3): recommendation accepted.** Runtime-path
  parity at N=2 plus the CD9 line at N=8 through the coordinator is CK5's LadybugDB evidence. The CD9
  run is scheduled by the orchestrator, one acceptance process at a time.
- **R5 — `Connector` rows for local and git (S5 open question 4): out of scope.** Task 15 creates
  them, once, outside any build window. No slice writes them.
- **R6 — S6 requirements on S2/S3 (R-S3-2, R-S2-6, R-S3-5): ratified.** Rendered facts are a `Unit`
  and a derived `Passage` over the record span, because the existing query path retrieves passages
  and the retrieval change is outside this ledger (design §14). A connector may emit an endpoint node
  of a kind another family owns as an identity-only node (`KnowledgeObject` plus the minimal
  observation), which is how cross-domain edges get endpoints; ownership is checked on edges, not on
  endpoint nodes. Deletion only from a completed inventory is the design's own rule (§7 step 9, CK3),
  not a deviation.
- **R7 — S4 deviations 1–4: ratified.** The shipped kit uses a temporary LadybugDB store because the
  Fake store is test code; tests and the CK4 CHECK line substitute the Fake; S4a records validate wall
  time and RSS at the 256 MiB buffer pool as CK4 evidence. `assert_contract` takes `context`; `sync`
  gains `--config`, `new` gains `--dest`; only `list` forwards through `remote.py`.
- **R8 — S6 narrowings 1–2: ratified.** The probe route runs on the stored instance config; the
  validate route and the MCP tool return the contract-scope report; the CLI keeps the full golden run.
- **R9 — Grants.** `docs/spec/cdk-guide.md` to S4b (rulebook line 17 now allows the single `docs/spec`
  file a brief grants by name). `tests/unit/test_import_order.py` appends by S4a, S5a and S5b are
  serialized by merge order.
- **R10 — Fixture connector location (S4 open question 2, S3 decision 11).** `tests/fakes/fixture_connector/`:
  never shipped, never auto-registered, importable by tests and by the guide's executed examples. It
  must not collide with `connectors/testing.py`, which S4a owns.
- **R11 — The 1,500-token bound (S4 open question 4, R-S2-5).** S2 names one counter in
  `connectors/contract.py`, reusing whatever `ingest/chunker.py` uses for its own budget; the kit and
  the S6 exemplar use that function and no other.
- **R12 — `Connector.classification_json` (S4 open question 3, S6 open question 2).** S1b adds the
  column (design §3 store impact, CK1 CRITERIA, commit `ef143b1`); S3 writes it (R-S3-3); `list`,
  the probe route and the classification route read it.
- **R13 — Kind collision (S6 open question 1).** `incident` is not a built-in kind (`predicates.py`
  has none); the design §5 prefix list reserves prefixes for the connectors that register those
  kinds. S1 registers only today's `OBJECT_KINDS` as built-ins. The exemplar keeps `incident`.
- **R14 — MCP tool name (S6 open question 3).** `hippo_connectors`, matching the `hippo_` prefix of
  the existing tools.
