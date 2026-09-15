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

## S2 and S3 (plans committed at `e2be4ab`)

- **R24 — The passage bound (S2 DV6, Q7): 6,000 characters.** `PASSAGE_CHAR_BOUND = 6000`, the
  specification's 1,500 tokens at four characters per token, measured by the one counter of R11/R26.
  The chunker's own default size is untouched; the bound is a maximum, not a target. Sibling plans
  read "token bound" as this constant.
- **R25 — `kind="connector"` sources (S3 Q7).** S5a's switch in `run_managed_build` routes
  `kind="connector"` to `sync_connector` (a reindex is a sync of every partition). Until S5a merges,
  `build_plain_source`'s refusal is the guard and S3c pins it with a test.
- **R26 — R11 amended on the module.** The counter is `connectors/base.py:token_count`, the design's
  contract module, reusing the chunker's character measure. Substance of R11 unchanged.
- **R27 — One clock (S4 R-S3-1 refuted by S3): the store clock.** The kit's purity guard and the
  `no_ingestion_time` rule intercept and read the store clock; no separate clock argument exists. S4's
  implementer brief carries this.
- **R28 — Public key helpers (S2 Q1).** S2a adds public `file_key`, `commit_key` and `resource_key` to
  `knowledge/identity.py`, wrapping the spellings at the anchors S2 §6 names; that is S2a's only edit
  to the file, parity tests pin them, and the code lane's private spellings are not touched (CK5).
- **R29 — Evidence class derivation is registry data (S2 Q4).** The derivation table of design §4
  lives in `knowledge/builtin_types.py` (S1a); registering an evidence source with no row in it is
  refused, and S2's binder imports the table from there, so bind has no evidence-class refusal path.
  Both the S1a and S2a briefs carry this.
- **R30 — Provider principals (S2 Q5, S3 Q2).** The connector instance configuration carries a
  `principal_map` from provider principals to local principal or group ids; unmapped principals are
  dropped from allow lists (deny by omission) and counted in coverage; reviewed mapping authorities
  are later work. The fixture and the exemplar configure identity maps.
- **R31 — Locator byte verifier (S2 DV2, Q6).** `LocatorKindDefinition` gains an optional `verifier`
  (S1a, one attribute); S2a supplies verifiers for the built-in line and byte-range kinds; a span
  whose locator kind has no verifier is refused at bind and `hippo connector validate` surfaces it
  before any sync; `section`, `page`, `comment` and `diff_hunk` are admitted when their registering
  connector supplies a verifier.
- **R32 — Extension registered (S3 Q1): yes.** `sync_connector` refuses a connector whose
  `TypeExtension` is not registered in the current registry, beyond `validate_against`.
- **R33 — Reconcile interval (S3 Q3): an option with the daily default; the scheduler is Task 9A.**
- **R34 — Policy changes (S3 Q4): accepted with one condition.** Widening waits for the next content
  revision, since spans keep their creation policy. Narrowing takes effect in the run that observes it
  through the policy epoch and suppression, never by re-minting spans; S3 §6 must say so and the
  reviewer verifies it. Unknown stays deny.
- **R35 — `ensure_connector` and the epoch (S3 Q5): accepted;** connectors are created once, outside
  build windows (R5), and written only on change (R21).
- **R36 — In-process emit (S3 Q6): v1 is in-process with the guard;** a timeout fails the sync while
  the worker thread finishes. Out-of-process isolation is the user's open decision (design §14.2).
- **R37 — Deviations ratified.** S2 DV1 (`Passage.ts` has no column; the binder requires it to equal
  the observation's `valid_from` or the revision's `source_updated_at`), DV2 (with R31), DV3 (alias
  rules 3–5 are Task 12's), DV4 (the kit renders), DV5 (`EmissionBatch.hints`). S3 DV1 (every member
  revision is emitted; carrying records forward is a later optimisation), DV2 (no new `IndexEvent`
  kinds), DV3 (the change log is `SyncState`), DV4 (the runtime embeds passages, units stay
  unembedded), DV5 (a failed page builds nothing in that run).
- **R38 — Splits and merge order.** Worktrees `s2a`, `s2b`, `s3a`, `s3b`, `s3c` as the plans propose;
  `ingest/code_generation.py` belongs to S3b for the §8 re-bindings, then to S5b (R2). Order: S1a;
  S1b; S2a after S1a; S2b after S2a and S1b; S3a after S2a; S3b after S1b; S3c after S2b, S3a and
  S3b; then S4a, S4b; S5a, S5b (S5b after S4a, R1); S6 after S4b and S5b. CK2's CHECK line stands;
  CK3's Fake line is replaced and a LadybugDB line added as S3 §14 proposes; the Neo4j line is in
  `neo4j-parity.md`.

