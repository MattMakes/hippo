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

## After the plan review (`ai_docs/reports/2026-09-15-cdk-plan-review.md`, committed at `9c5fc8e`)

The review's fix column binds the owning slice's brief for every finding not listed here; these
rulings record the decisions and the amendments to earlier rulings. Earlier rulings are not rewritten.

- **R39 — Vocabulary is never validated on read (review M1; design §3 amended).** Registration, bind
  and store write check vocabulary; model fields stay plain codes; reads accept any code; projection
  and citations exclude and count rows of unregistered vocabulary. S1a exposes
  `Registry.check_record`; S2b's binder and S1b's write path (`store/knowledge.py`) call it.
- **R40 — amends R29 (review M8).** An extension evidence source registers with its class:
  `EvidenceSourceDefinition(name, family, evidence_class)`, never `model_inferred` or
  `human_verified`. Registration refuses a source with no class or an excluded class, not a source
  absent from the built-in table. S2's refusal of invalid (family, source) pairs at bind stays.
- **R41 — amends R17 (review m2).** The `Unit` indexes are Neo4j only; LadybugDB 0.15.3 has no
  secondary-index DDL.
- **R42 — amends R24 (review m6).** The 6,000-character bound stands as an approximation of the
  specification's 1,500 tokens, recorded as such; S2's message interpolates `PASSAGE_CHAR_BOUND` and
  S4 sets `TOKEN_BOUND = base.PASSAGE_CHAR_BOUND`.
- **R43 — amends R25 (review M14).** Until Task 15, `run_managed_build` refuses `kind="connector"`
  with `ManagedDispatchError`; S5a adds the branch and its test. No route from the reader actor to
  `sync_connector` exists.
- **R44 — amends R30 (review M9).** The principal map is applied in S2's `policy_record`: an
  unmapped principal in a deny list makes the observation `unknown` (deny); an allow list the mapping
  empties becomes `unknown`; unmapped allow entries are dropped and counted.
- **R45 — amends R31 (review M10).** Only extension locator kinds set `verifier`. Built-in verifiers
  are S2b's table in `connectors/emit.py`, consulted first. A kind with neither is refused at bind and
  by `validate`. There is no byte-range built-in kind.
- **R46 — amends R32 (review m7).** `ConnectorDescriptor` gains `extension: TypeExtension`; S3 checks
  that each registered definition equals it.
- **R47 — B1 (CK5): S1b owns the fingerprint-tolerant comparisons.** S1b edits
  `knowledge/prose_preparation.py:164-174` (pass `registry_fingerprint=gen.registry_fingerprint` to
  `generation_for_inputs`) and `knowledge/staged_code.py:310` (normalize the fingerprint on both
  sides) with the review's two tests; the S1b brief's do-not-touch list yields for those lines.
- **R48 — B2 (CK3): span policy is the first capture's.** `RevisionInput.span_policy_id` (S2a,
  `base.py`), used by `bind_batch` for every span; S3 records it in
  `ArtifactRevision.metadata_json["span_policy_id"]` at first capture and passes it. Matrix row M8b.
- **R49 — B3 and B4 (CK4): one guard, one runtime entry.** `testing.purity_guard` is S3's
  `guard.forbid_effects`; S3's forbidden set gains m20's names; `run_case` calls `sync_connector`
  with S3's full signature after `ensure_connector(..., enabled=True)`, `connector_source`, the replay
  probe and `store_classification`; `sync_connector` gains `connector_id: str`; `RUNTIME_FAILPOINTS`
  are S3 §9's five scenarios on `_ReplayConnector`; `testing` re-exports S3's transports.
- **R50 — M2: slice S4c, the loader.** `connectors/loader.py` with
  `load_registry(*, enabled_kinds, allowlist) -> LoadResult` (built-ins, enabled in-repo packages,
  allowlisted entry points, then `freeze()`); `cli.cmd_connector` and the `web/app.py` lifespan call
  it (those lines granted to S4c); enabling a kind takes effect at restart. R38's order gains "S4c
  before any caller of `load_registry`", and S5's `default_registry()` and S6's R-S1-3 use it.
- **R51 — M5: only enabled instances run.** `ensure_connector` defaults to `enabled=False`;
  `sync_connector` refuses a disabled instance at entry. This answers design §14.3 for v1: an
  installed connector package runs only when an operator enables its kind and its instance.
- **R52 — M3 and M4 (CK3).** A stored policy is refreshed only when `expires_at - now <
  policy_ttl_seconds / 2` (row M21); `no_changes` is decided after computing the candidate
  generation, by `manifest_hash` equality and no policy change.
- **R53 — M6: foreign endpoints carry their declared instance.** `NodeRef` gains
  `instance: Text = None`, admitted only on identity-only foreign endpoints, normalized by
  `normalize_provider_url`, with the value from instance configuration (S6's config gains
  `catalog_instance`).
- **R54 — M11: the one `ingest` to `connectors` import edge is ratified.** `managed_activation` is
  the only ingest module that may import `hippo.connectors`; `connectors.{lanes,local,git}` never
  import `managed_activation` or `pipeline`; S5a pins it in `tests/unit/test_layering.py` (granted).
- **R55 — Minors.** Every minor in the review's table is applied by the slice its "Plan and section"
  column names, through that slice's brief; m3 (CK1 wording), m6, m18 (design §8 reads "a source
  with a deterministic row in the §4 table") and m12/m14 are recorded here as applied.
- **R56 — S4 is re-planned.** S4 §3.1 (`run_case`, the guard, the transports, `check_capture`,
  `probe_deterministic`) and a new S4c (the loader) are re-planned by a fresh planner; the scaffold,
  the commands and the guide stand, with M16's template fix. The re-plan is reviewed on §3.1 and S4c
  only.

## After the S4 re-plan (`ai_docs/plans/cdk-s4-kit.md` re-planned, committed at `dffe1a3`)

- **R57 — The S4 re-plan is ratified with its stated deviations,** pending the narrow re-review of
  §3.1 and §3.5 (S4c): `validate_package` scopes `capture`, `contract` and `full`; `registry_diff`
  against `Registry.with_builtins()`; `prepare_instance` runs `connector_source` after
  `store_classification`; `tests/fakes/fake_ollama.py`'s `embed_text` body is S4a's (m17); the
  allowlist is read in `loader.py` from `HIPPO_CONNECTOR_ALLOWLIST` for v1 (a Config or store
  setting is Task 15's).
- **R58 — amends R50 (S4 open question 1).** The `cli.cmd_connector` call of `load_registry` is
  S4b's, because the command does not exist until S4b; the `web/app.py` lifespan call is S4c's.
- **R59 — Enabling an instance in v1 (S4 open question 3).** S4b adds `hippo connector enable <kind>
  <instance_url> [--config <file>]`: `manage_sources`, `BuildActor.trusted_local()`, outside any
  build window, `ensure_connector(..., enabled=True)` then the probe and `store_classification`,
  with one test. Task 15's route creates the same row over HTTP later. Local and git rows stay
  R5's.
- **R60 — Re-exports and allowlists (S4 open questions 4 and 6).** `connectors/base.py` re-exports
  `current_registry`, `extension_scope` and `use_registry` (S2a, R-S2-10); S6's import allowlist
  admits `hippo.connectors.classify`; R-S3-7 (a no-argument `FixtureConnector`, `fixtures/basic`
  with two or more upserts, `inventory=True`, probe sampling through its own `list_changes` and
  `fetch`) binds the S3c brief.

## During implementation (answers to workers, binding on later slices)

- **R61 — The principal map's shape (S2a question; refines R44).** `base.PrincipalMap(users:
  dict[Text, Text], groups: dict[Text, Text])`, kept separate so a provider user id cannot collide
  with a group id, and a pure `base.map_principals(policy, principal_map) -> (PolicyObservation,
  dropped_count)` applying R44's rules per list: an unmapped deny entry, or an `allow_users` or
  `allow_groups` list the mapping empties, makes the observation `unknown`; other unmapped allow
  entries are dropped and counted. S2b's `emit.policy_record` reads `config_json["principal_map"]`
  and calls it. R30's "instance configuration contract" means this shape, not a base class for
  `config_model`. `PASSAGE_CHAR_BOUND = 6000` ships in S2a; the bound message is S2b's.
- **R62 — Evidence sources at write and in the accessor (S1b questions; refines R39 and R40).**
  `Registry.check_record` also checks `AssertionVersion.source` when not `None` ("Unknown evidence
  source"), so the store write path and S2b's binder share it. `Registry.evidence_source_definition`
  returns the registered definition unchanged: built-ins carry `family=None, evidence_class=None`
  and callers read `EVIDENCE_CLASS_DERIVATION` by `(family, source, metadata_origin)`; extension
  sources carry both. The four schema-version pins the S1 plan did not name
  (`test_generation_scoped_reads.py:838`, `:845`; `test_policy_migration.py:173`, `:243`) move to 8
  with the rest.

