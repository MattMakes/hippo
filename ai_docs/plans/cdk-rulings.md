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

## S1 (plan committed at `5bae615`)

- **R15 — Discovery (S1 deviation 9, open question 7; S4 R-S1-1): S4 owns it.** `Registry.load()`
  of design §9 becomes a loader in `hippo.connectors` (S4), composed from S1's primitives
  (`Registry.with_builtins()`, `register(..., declared_families=...)`, `freeze()`, `use_registry()`),
  because `knowledge/registry.py` may not import `hippo.connectors`. S3's `sync` takes an already
  frozen registry as an argument and plans no loader; the `hippo connector` commands and `hippo
  serve` startup call the loader.
- **R16 — One current registry (S1 deviation 10; S2 Q3; S4 `run_case`).** The process default is
  `REGISTRY`; `use_registry()` may install another for a bounded run, and `extension_scope()` extends
  the current one in place. Every identity check, including S2's binder, is against the current
  registry (`current_registry()`), never against the module constant by identity. S4's `run_case`
  registers the connector's `TypeExtension` inside `extension_scope()` or under `use_registry()`;
  either satisfies the binder.
- **R17 — Unit indexes (open question 1).** v8 indexes `Unit.generation_id`, `Unit.passage_id` and
  `Unit.content_hash` on LadybugDB and Neo4j now, so the boilerplate weight of spec §7.2 needs no v9.
- **R18 — Two identities for one table (open question 2): accepted for v1.** The code lane's keys are
  not re-keyed (CK5 byte-identity). A table seen in code and in a catalog is joined by the database
  object alias rule of spec §4.2, emitted as `SAME_OBJECT_AS` by the connector that sees both, in
  Task 12's scope.
- **R19 — Multi-owner built-ins (open question 3): sets confirmed as planned.** The refusal is
  `family not in owner_families`; the reviewer checks the table against spec §6.
- **R20 — Unversioned render text (open question 4): no version fields.** The fingerprint hashes the
  full canonical definition, so `verb_phrase` and `label_template` changes change it. A kit connector
  covers its own render text through its connector version: S4's kit asserts that changed
  `label_template`, `verb_phrase` or fact template text without a connector version bump fails the
  golden run.
- **R21 — Classification and the authorization epoch (open question 5): accepted.** Probe is an
  operator action; S3 writes `classification_json` only when the value changes, so a re-probe with
  the same result bumps nothing.
- **R22 — `SAME_OBJECT_AS` ordering (open question 6): code-point order, confirmed.** No collation.
- **R23 — S1 deviations 1–8: ratified.** `Unit` lands in S1b with the v8 bump (the live v7 checksum
  forbids otherwise); the three leaf modules and the widened CK7 lint line; the file ownership of
  §9.3; additive registry API; `LocatorBase` as the refusal rule's `SourceLocator`; `PREDICATES`
  excludes identity predicates; built-in kinds keep an open attribute model while extensions forbid
  extras; the schema-version pins move to 8 (CK1 CRITERIA amended). CK1's CHECK lines and the
  Neo4j parity file are applied as S1 §8 proposes.

