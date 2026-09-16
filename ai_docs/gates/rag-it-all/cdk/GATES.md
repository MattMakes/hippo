# Connector Developer Kit gates

**Status:** OPEN. Design of record `docs/spec/connector-developer-kit.md` (2026-09-15); implementation
plans `ai_docs/plans/cdk-*.md`. No gate has run. CHECK lines name the test files each slice's plan
must create; a plan may replace a CHECK line by naming the replacement in its "ledger lines" section,
and the orchestrator applies it. The checker's EVIDENCE lines carry no git revision, so this Status
line is the revision of record once gates pass.

**Scope:** the kit of `docs/spec/connector-developer-kit.md` sections 1–10: the ontology registry and
the widened model (S1a, S1b), the connector contract with classification, keys, rendering and emission
(S2), the sync runtime with the generic staged writer (S3), the test kit, scaffold and commands (S4),
the port of the local prose and git code paths onto the runtime (S5), one exemplar connector for an
uncovered family with the probe and validate surfaces (S6), and the independent review (CK7). Outside
this ledger: the seven connectors of the specification's section 5 beyond the two ported paths and
the exemplar, the linker's synonym queue (Task 12), the maintenance worker (Task 9A), and every
retrieval change (the stack decision, kit section 14). Fake is the first backend for every gate;
LadybugDB is the acceptance backend where persistence is touched; Neo4j parity is root-owned evidence
recorded in `neo4j-parity.md` beside this file.

Every CHECK line runs from /Users/mascott/projects/hippo. Runnable checkboxes are set by the
orchestrator's gate checker, never by an implementer.

- [ ] CK1: Kinds, predicates, locators, families, connector kinds and evidence sources are registry-driven, refused at registration, and recorded by fingerprint in every managed generation.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_registry.py tests/unit/test_registry_model.py tests/unit/test_knowledge_contracts.py tests/unit/test_store_migrations.py tests/unit/test_generation_store.py -q -o addopts='' -W error && HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_registry_model.py tests/unit/test_store_migrations.py tests/unit/test_generation_store.py tests/unit/test_policy_migration.py -q -o addopts='' -W error
  CRITERIA: every value that is a `Literal` or frozenset member today is a built-in registration and every existing model test passes unchanged, except the schema-version pins in the store tests that move to 8 as at every earlier schema version and the predicate construction check at `tests/unit/test_knowledge_contracts.py:205-208`, which moves to `Registry.check_record` because vocabulary is never validated on read (review M1, ruling R39); each refusal reason in the design's section 3 has a test that triggers it at `Registry.register` and a test proving the same input cannot reach `emit`; `Registry.fingerprint()` is stored on every generation built by the kit runtime or a coordinator lane (`Generation.registry_fingerprint`, schema v8, outside `identity_fields`; the pre-kit lanes store none), never in `configuration_json`, and changes when a fact template changes, while the configuration of a generation built by a connector that declares that template changes with it; `SAME_OBJECT_AS` is a built-in identity predicate over any registered kind pair, exempt from ownership and never traversed, and `ALIAS_OF` keeps its `alias` subject rule; schema v8 adds `Unit`, `Generation.registry_fingerprint`, `Connector.classification_json` and the `AssertionVersion` columns `family`, `source`, `rule`, `weight`, `statement`, `unit_id` on Fake, LadybugDB and Neo4j with the frozen v1–v7 history intact and existing row identities unchanged; `EvidenceClass` gains `rule_derived` and `similarity_inferred`.
  EXPECT: passed

- [ ] CK2: An emission batch maps totally onto the knowledge records, with identities from the builders, evidence classes from the table, and direction enforced.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_contract.py tests/unit/test_connector_emit.py tests/unit/test_connector_render.py tests/unit/test_connector_keys.py tests/unit/test_connector_classify.py -q -o addopts='' -W error
  CRITERIA: a table-driven test proves every field of the specification's section 3 records lands in the record and column the design's section 4 names; `KnowledgeObject` identities come only from `connectors/keys.py`; `evidence_class` follows the design's derivation table and a connector cannot set it; an edge emitted by a non-owner family or in the reverse direction is refused with the developer-facing message; every span is verified against the revision bytes at its locator; every rendered unit is one template output; `probe` is a pure function of descriptor, config and sampled bytes (asserted by the kit's `probe_deterministic` assertion, gate CK4, review M13), and classification order is declaration, content, name, with `custom/unclassified` counted.
  EXPECT: passed

- [ ] CK3: The runtime syncs any connector durably, publishes through the build authority, keeps the last generation queryable on every failure, and is idempotent under replay.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_sync.py tests/unit/test_connector_http.py tests/unit/test_staged_records.py tests/unit/test_connector_credentials.py tests/unit/test_connector_guard.py tests/unit/test_generation_profiles.py tests/unit/test_build_authority.py tests/unit/test_build_run.py -q -o addopts='' -W error && HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_connector_sync.py tests/unit/test_staged_records.py tests/unit/test_generation_profiles.py -q -o addopts='' -W error
  CRITERIA: a fixture connector runs every step of the design's section 7 with failure injection at each durable boundary (crash after fetch before checkpoint, replayed page, failed inventory, policy change mid-page, delete of an artifact with a live query session); no deletion follows a failed inventory; a replayed page changes nothing; publication uses the existing `BuildAuthority` compare; the active generation is never deleted; `IndexEvent` rows are written for the append lane; the runtime forbids network, model and clock use inside `emit`; the same suite passes on LadybugDB with reopen proven, and Neo4j parity is recorded; after a policy-only change two more syncs publish, every stored span keeps its `policy_id`, a reader removed by narrowing loses the passage at the checkpoint and a reader added by widening sees it only after a new revision (M8b); two syncs of unchanged content inside the policy TTL window leave `authorization_epoch()` unchanged and an open session still validates (M21); between first capture and first publication a partition source contributes nothing to a query session (M22); a template version bump rebuilds an unchanged partition (M4); a disabled connector instance is refused at entry (M5).
  EXPECT: passed

- [ ] CK4: The test kit fires on every seeded violation, the scaffold produces a package that validates, and the commands work against the fixture connector.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_testing_kit.py tests/unit/test_connector_scaffold.py tests/unit/test_cli_connector.py tests/unit/test_connector_loader.py -q -o addopts='' -W error
  CRITERIA: every contract, purity, runtime and registry assertion of the design's section 8 has a negative fixture that fires it and a positive fixture that passes; `hippo connector new` writes a package whose `hippo connector validate` passes; `probe`, `list` and `sync --dry-run` run against the fixture connector; `remote.py` forwards the commands; the developer guide `docs/spec/cdk-guide.md` exists and its examples are the fixture connector; the loader (`connectors/loader.py`, slice S4c) lists a failing entry point with its error and continues, skips an entry point missing from the allowlist, and `hippo serve` startup installs a frozen registry; the kit's `check_capture` and `probe_deterministic` assertions exist with negative fixtures (M12, M13); one purity guard, S3's per-thread `forbid_effects`, serves the kit and the runtime (B3).
  EXPECT: passed

- [ ] CK5: The local prose and git code paths run through the runtime as connectors with byte-identical published output.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_local.py tests/unit/test_connector_git.py tests/unit/test_prose_generation.py tests/unit/test_code_generation.py tests/unit/test_managed_pipeline_activation.py tests/unit/test_managed_code_activation.py tests/unit/test_code_capture_acceptance.py -q -o addopts='' -W error
  CRITERIA: `add_text`, `add_upload` (including ZIP) and `add_repo` dispatch through the kit's connector interface (`LocalConnector`, `GitConnector`) and the coordinator lane (`connectors/lanes.py`), whose derivation half is the reviewed coordinator (S5 plan deviation 1, ruling R1 of `ai_docs/plans/cdk-rulings.md`), and the kit's capture-side contract assertions (probe, list_changes, fetch, fetch_policy) pass on both connectors; for every existing fixture the published generation's checksums (`generation_checksums`), spans, passages, native rows, receipts and coverage equal the pre-kit path's, proven by a test that runs both paths on the same fixture, with the ported connectors writing `configuration_json` unchanged so no generation id, and no id namespaced by one, is normalized in the comparison, and the one allowed difference is `Generation.registry_fingerprint` (None on the pre-kit path), which `generation_checksums` does not hash because it skips the `Generation` row; the CD1 and CD2 CHECK lines of `../task-5-code-capture/GATES.md` pass verbatim; LadybugDB acceptance at the recorded size passes.
  EXPECT: passed

- [ ] CK6: An exemplar connector for an uncovered family is written only with the public kit, registers new types, validates, syncs and is retrievable with resolving citations.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_exemplar.py tests/unit/test_connector_surfaces.py -q -o addopts='' -W error
  CRITERIA: the exemplar imports nothing outside `hippo.connectors` public modules and the knowledge model; it registers at least one new object kind with a fact template and one new predicate with an owner family; `hippo connector validate` passes; a fixture syncs into a scratch workspace; a query through the existing query path returns its rendered facts with citations that resolve to its spans; the probe and validate results are visible through the Task 15 connector routes and MCP tool.
  EXPECT: passed

- [ ] CK7: Lint, formatting and independent review.
  CHECK: .venv/bin/ruff check src/hippo/connectors src/hippo/knowledge/registry.py src/hippo/knowledge/contract.py src/hippo/knowledge/locators.py src/hippo/knowledge/builtin_types.py src/hippo/knowledge/predicates.py src/hippo/knowledge/staged_records.py tests/unit/test_connector_*.py tests/unit/test_registry*.py tests/unit/test_staged_records.py && .venv/bin/ruff format --check src/hippo/connectors src/hippo/knowledge/registry.py src/hippo/knowledge/contract.py src/hippo/knowledge/locators.py src/hippo/knowledge/builtin_types.py src/hippo/knowledge/predicates.py src/hippo/knowledge/staged_records.py tests/unit/test_connector_*.py tests/unit/test_registry*.py tests/unit/test_staged_records.py
  CRITERIA: independent SPEC and QUALITY reviews of the kit against the design and the specification's section 3 pass with every finding closed or assigned by name; the review confirms the two standing rules (no model call, no unearned relation label) are enforced by tests, not stated.
  EXPECT: All checks passed

When a gate passes, replace its checkbox and append an `EVIDENCE:` line containing exit code, shell,
working directory, source revision, test count, and concise output. Record initial RED failures for
each new behavior and the final GREEN result. Any change made after review reruns the affected gate.
