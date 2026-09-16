# CK7: independent SPEC and QUALITY review of the Connector Developer Kit

**Reviewer:** `architect-reviewer-3` (herdr fleet). **Revision:** `0d50887` on `rag-it-all-tibs`,
root tree, read-only apart from this file. **Date:** 2026-09-15.

**Overall verdict: PASS WITH CHANGES.** Fifteen findings: 0 BLOCKER, 2 MAJOR, 13 MINOR (table in
section 9, counts in section 10). Every gate CK1-CK6 is MET on its CRITERIA. The second standing
rule (no unearned relation label) is enforced by tests. The first (no model call inside `emit`) is
enforced for a connector that lets the refusal propagate and is **defeatable by an ordinary broad
`except` inside `emit`** (F1). F1 and F2 are the two changes this review asks for before CK7 is
closed; F3-F15 are recorded and assigned.

## 1 What was read and what was run

Design of record `docs/spec/connector-developer-kit.md`; the contract of
`docs/spec/enterprise-graph-rag-v1.md` sections 3, 4.1-4.4 and 6; the rulings
`ai_docs/plans/cdk-rulings.md` R1-R80; the ledger `ai_docs/gates/rag-it-all/cdk/GATES.md` with
`root-evidence.md`, `neo4j-parity.md` and all seventeen `evidence-*.md`; the two plan reviews; the
code and the test files the brief names.

Every Fake CHECK line of CK1-CK6 and the CK7 lint line were run verbatim at `0d50887`, one pytest
process at a time, `-W error`, from `/Users/mascott/projects/hippo`:

| Line | Exit | Result | Log |
| --- | --- | --- | --- |
| CK1 Fake | 0 | 305 passed, 9 skipped | `/tmp/hippo-review-ck1-fake.log` |
| CK2 Fake | 0 | 289 passed | `/tmp/hippo-review-ck2-fake.log` |
| CK3 Fake | 0 | 296 passed, 2 skipped | `/tmp/hippo-review-ck3-fake.log` |
| CK4 Fake | 0 | 166 passed | `/tmp/hippo-review-ck4-fake.log` |
| CK5 Fake | 0 | 325 passed, 3 skipped | `/tmp/hippo-review-ck5-fake.log` |
| CK6 Fake | 0 | 42 passed | `/tmp/hippo-review-ck6-fake.log` |
| CK7 lint | 0 | all checks passed; 51 files already formatted | `/tmp/hippo-review-ck7-ruff.log` |
| CD1 verbatim (CK5 CRITERIA) | 0 | 133 passed | `/tmp/hippo-review-cd1.log` |
| CD2 verbatim (CK5 CRITERIA) | 0 | 169 passed, 2 skipped | `/tmp/hippo-review-cd2.log` |
| `test_layering.py` + `test_import_order.py` | 0 | 43 passed | `/tmp/hippo-review-layering.log` |

The LadybugDB lines of CK1, CK3 and CK5 and every Neo4j parity line are root-owned; they are
recorded in `root-evidence.md` and `neo4j-parity.md` and were not re-run here. Section 8.9 records
the one gap in that record.

Beyond the suites, five read-only probes were run against the installed package
(`/tmp/hippo-review-probe1.py` through `probe4.py`) and five source mutations were applied
in-process through a pytest plugin at `/tmp/hippo_mutation_plugin.py`, to test whether the suites
bite rather than whether they pass. Nothing in the repository was edited by either.

## 2 Gate CK1 - registry, model and schema v8

**Verdict: MET.**

| CRITERIA clause | Proof | Verdict |
| --- | --- | --- |
| Every value that is a `Literal` or frozenset today is a built-in registration | `test_registry.py::test_builtins_register_every_value_the_closed_vocabularies_held`; `::test_builtin_object_kinds_carry_the_planned_family_prefix_and_key_template` (30 kinds, family, prefix, key template, scope); `::test_builtin_endpoint_rules_are_the_legacy_table`; `builtin_types.py:91` asserts the kind set equals `predicates.OBJECT_KINDS` at import | MET |
| Every existing model test passes unchanged | Verified by diff, not only by green: `git diff 5039b46..0d50887` (the parent of `dc10058`, the first commit to touch `knowledge/registry.py`) over the ten pre-existing suites shows `test_prose_generation.py`, `test_code_generation.py`, `test_managed_pipeline_activation.py`, `test_managed_code_activation.py` and `test_code_capture_acceptance.py` untouched, and in the other five the only **removed** lines are the schema-version pins moving 7 -> 8 and the `test_knowledge_contracts.py:205-208` predicate-construction check, with one widening (`test_recovery_after_each_declared_schema_step` parametrized `[2,3,4,5]` -> `[2,3,4,5,8]`); everything else is addition. Those are exactly the CRITERIA's two named exceptions. Plus `test_registry_model.py::test_moved_contract_names_resolve_through_the_model`, `::test_object_kind_literal_names_exactly_the_builtin_kinds` | MET |
| The schema-version pins move to 8 | `test_store_migrations.py:20-21`; the four pins R62 names (`test_generation_scoped_reads.py:838,845`, `test_policy_migration.py:173,243`) are green inside CD1 and the CK1 LadybugDB line | MET |
| `test_knowledge_contracts.py:205-208` moves to `Registry.check_record` because vocabulary is never validated on read (M1, R39) | `test_registry_model.py::test_vocabulary_fields_accept_any_code_without_a_registration`, `::test_a_row_of_an_unregistered_kind_reads_back_outside_its_registry`, `::test_check_record_refuses_an_unregistered_kind`, `::test_check_record_validates_a_span_payload_with_its_registered_model`; confirmed independently by probe 1 (section 8.1) | MET |
| Each refusal reason of design section 3 has a test that triggers it at `Registry.register` | `test_registry.py::test_register_refuses[...]`, 31 parametrized rows over `REFUSALS` (`test_registry.py:165-347`), asserting the reason code **and** the exact message. Every design-section-3 reason is present: `duplicate_name`, `shadows_builtin`, `unknown_family` (kind and owner), `empty_key_template`, `repeated_key_part`, `extra_attributes_allowed`, `undeclared_template_field` (label, consumes, text, positional), `unregistered_endpoint_kind`, `undeclared_owner_family` (extension and declared), `missing_locator_model`, `not_a_source_locator`; plus `frozen`, `reserved_attribute`, `malformed_template`, `repeated_template_attribute`, `duplicate_template` (and its case variant), `identity_predicate`, `empty_endpoint_kinds` (subject and object), `empty_owner_families`, `unregistered_evidence_source`, and R40's `missing_evidence_family`, `missing_evidence_class`, `excluded_evidence_class` (both excluded classes) | MET |
| ... and a test proving the same input cannot reach `emit` | `test_connector_emit.py::test_unregistered_or_undeclared_type_at_bind_is_refused[...]`, the same 31 rows: each refused registration is followed by a bind of a batch naming that extension's vocabulary, and the binder's refusal message is asserted. `duplicate_name`, the one row whose first registration succeeds, is carried by the converse half of the same assertion. Reinforced by `test_registry_model.py::test_a_refused_extension_leaves_no_name_check_record_accepts[...]` | MET |
| `Registry.fingerprint()` is on every generation the kit runtime or a lane builds, `Generation.registry_fingerprint`, schema v8, outside `identity_fields`, never in `configuration_json`; the pre-kit lanes store none | `test_registry_model.py::test_generation_registry_fingerprint_is_a_sha256_outside_identity_and_the_manifest`; `test_connector_sync.py::test_the_generation_records_the_registry_fingerprint_outside_its_configuration`; `test_connector_local.py::test_run_coordinator_lane_passes_the_frozen_registry_fingerprint`, `::test_build_plain_source_defaults_registry_fingerprint_to_none`; `test_connector_git.py::test_build_code_source_defaults_registry_fingerprint_to_none` | MET |
| The fingerprint changes when a fact template changes, and the declaring connector's configuration changes with it | `test_registry.py::test_a_changed_fact_template_changes_the_fingerprint_and_the_declaring_configuration`, `::test_a_template_text_change_without_a_version_bump_changes_only_the_fingerprint` (R20), `::test_fingerprint_covers_label_templates_and_verb_phrases`, `::test_fingerprint_is_independent_of_registration_order`, `::test_connector_configuration_is_canonical_and_reads_declared_template_versions` | MET |
| `SAME_OBJECT_AS` is a built-in identity predicate over any registered kind pair, exempt from ownership, never traversed | `test_registry_model.py::test_same_object_as_accepts_any_registered_kind_pair_without_ownership_or_traversal`, `::test_same_object_as_stores_the_lexically_smaller_canonical_key_as_subject` (R22, code-point order), `::test_a_stored_same_object_as_is_absent_from_projection_and_structural_relations`. Probe 1 confirms `identity=True`, `traversal_permitted=False`, owner families = all eight | MET |
| `ALIAS_OF` keeps its `alias` subject rule | `test_registry_model.py::test_alias_of_keeps_its_alias_subject_rule`; probe 1 confirms `subject_kinds == {"alias"}` | MET |
| Schema v8 adds `Unit`, `Generation.registry_fingerprint`, `Connector.classification_json` and the six `AssertionVersion` columns on all three backends, v1-v7 frozen, existing row identities unchanged | `test_store_migrations.py::test_v7_descriptor_and_indexes_are_frozen_at_their_published_values` (the seven published checksums are pinned by literal, `V7_CHECKSUM` recomputed, and `Unit`/`family`/`registry_fingerprint`/`classification_json` asserted absent from v7); `::test_v8_descriptor_adds_unit_and_the_widened_columns_only` (`canonical_json(v8[2:]) == canonical_json(v7[2:])`); `::test_v8_schema_steps_are_exact_per_backend`; `test_registry_model.py::test_v8_fields_leave_existing_identities_unchanged`, `::test_unit_identity_is_generation_passage_ordinal_and_content_hash`; Neo4j recorded in `neo4j-parity.md` (114 passed at `9e5b93c`) | MET |
| `EvidenceClass` gains `rule_derived` and `similarity_inferred` | `test_registry_model.py::test_the_two_new_evidence_classes_validate_and_change_no_column`; `contract.py:28` | MET |

Two notes that do not change the verdict. The `Unit` indexes are Neo4j-only (R41) because
LadybugDB 0.15.3 has no secondary-index DDL, which `test_v8_schema_steps_are_exact_per_backend`
pins per backend. And the built-in prefix set is today's `OBJECT_KINDS` only (R13), so design
section 5's sentence "the readable prefixes of spec section 4.1 ... **are** the built-in kinds'
prefixes" is now false for `coll`, `sprint`, `inc`, `alert`, `sec` and `term`: finding F6.

## 3 Gate CK2 - the contract and emit

**Verdict: MET.**

| CRITERIA clause | Proof | Verdict |
| --- | --- | --- |
| A table-driven test proves every field of spec section 3 lands in the record and column design section 4 names | `test_connector_emit.py::test_every_spec_section_3_field_lands_in_its_design_section_4_column[...]`, 47 parametrized rows over `TOTALITY`, each naming the spec field, the knowledge record, the column and the expected value; `::test_the_totality_table_names_every_spec_section_3_field` asserts the row set equals `SPEC_FIELDS` and that both are 47. The 47 are Node's 8, Edge's 12, Passage's 7, Unit's 8, AliasCandidate's 5 and Provenance's 7 - the whole of spec section 3 | MET |
| `KnowledgeObject` identities come only from `connectors/keys.py` | `test_connector_keys.py::test_keys_is_the_only_knowledge_object_constructor_in_connectors` (AST scan of the package); `test_connector_emit.py::test_the_binder_never_constructs_a_knowledge_object_itself` | MET |
| `evidence_class` follows the derivation table and a connector cannot set it | `test_connector_emit.py::test_evidence_class_follows_the_derivation_table[...]` (12 rows, the whole of design section 4's table, asserted against `EVIDENCE_CLASS_DERIVATION` as well as against `emit.evidence_class`); `::test_family_source_pairs_outside_the_table_are_refused[...]`; `::test_evidence_class_reads_an_extension_source_class_from_the_registry` (R40/R62/R63); `::test_a_connector_cannot_set_evidence_class` (the field is absent from `NodeEmission` and `EdgeEmission` and setting it is a `ValidationError`); `::test_no_emission_yields_model_inferred`; `test_registry.py::test_evidence_class_derivation_table_is_the_design_table`. The table in `builtin_types.py:99-114` is row-for-row design section 4 | MET |
| An edge emitted by a non-owner family or in the reverse direction is refused with the developer-facing message | `test_connector_emit.py::test_non_owner_family_edge_is_refused_with_the_developer_message`, `::test_reverse_direction_edge_is_refused_with_the_developer_message`, `::test_direction_is_checked_before_ownership`, `::test_identity_predicate_is_refused_as_an_edge`, `::test_check_direction_and_ownership_is_the_check_the_binder_applies`, `::test_source_outside_sources_allowed_is_refused`. One function, `emit.check_direction_and_ownership` (`emit.py:401-433`), serves the binder and `hippo connector validate`, so the message a developer reads is the message the binder raises. Mutation `direction` (section 9.3) confirms these bite | MET |
| Every span is verified against the revision bytes at its locator | `test_connector_emit.py::test_file_lines_span_text_is_sliced_from_revision_bytes_with_terminators`, `::test_span_text_that_differs_from_the_bytes_is_refused_without_quoting_it`, `::test_a_line_past_the_last_line_is_refused`, `::test_a_file_lines_locator_naming_another_file_is_refused`, `::test_field_span_is_resolved_in_the_json_document`, `::test_table_cell_span_is_resolved_in_the_csv_table`, `::test_locator_kind_without_a_verifier_is_refused` (R45), `::test_a_built_in_verifier_is_consulted_before_an_extension_verifier`, `::test_verify_span_returns_the_text_the_binder_hashes`. Mutation `span_bytes` (section 9.3) confirms they bite | MET |
| Every rendered unit is one template output | `test_connector_render.py` (the whole file); `test_connector_emit.py::test_one_fact_with_two_statements_in_one_batch_is_refused`, `::test_unit_offsets_are_verified_within_the_unit_span`, `::test_each_rendered_fact_and_rendered_edge_gets_its_own_derived_passage` (R6); `testing.assert_one_fact_per_unit` with its negative fixture | MET |
| `probe` is a pure function of descriptor, config and sampled bytes, asserted by `probe_deterministic` | `testing.CAPTURE_ASSERTIONS` contains `probe_deterministic`; `test_connector_testing_kit.py::test_a_negative_fixture_fires_its_own_assertion[probe_deterministic]` and `::test_a_negative_fixture_fires_no_other_assertion_of_its_group[probe_deterministic]`; `test_connector_git.py::test_git_probe_reports_the_code_family_and_the_history_capability` with R78's note that `GitConnector.probe` observes only whether the checkout is a clone; `test_connector_exemplar.py` probes through the fixture export | MET |
| Classification order is declaration, content, name, with `custom/unclassified` counted | `classify.classify_item` (`classify.py:96-124`) decides in exactly that order and falls through to `_unclassified`; `test_connector_classify.py` covers each rule and the count; `classify._partition` keys an undecided item under `base.UNCLASSIFIED` | MET |

## 4 Gate CK3 - the runtime

**Verdict: MET.**

| CRITERIA clause | Proof | Verdict |
| --- | --- | --- |
| A fixture connector runs every step of design section 7 | `test_connector_sync.py::test_a_fixture_partition_syncs_through_every_step_and_publishes`; `::test_every_fault_point_label_is_reachable` proves the fault points the matrix uses are the real boundaries | MET |
| Failure injection at each durable boundary: crash after fetch before checkpoint | `::test_the_failure_matrix[M1]` (`after_fetch`) and `[M2]` (`before_checkpoint`): no capture row is written and the cursor does not move | MET |
| ... replayed page | `[M3]` (crash after checkpoint, replay is byte-identical and moves no authorization epoch) and `[M4]` (`repeat_first_page`: artifact ids stay unique) | MET |
| ... failed inventory | `[M5]`: a 503 mid-scan leaves `scan.complete` false and deletes nothing; `[M6]`: a page-bounded run reports `inventory="partial"` and deletes nothing; `[M7]`: a complete scan withdraws the missing artifact | MET |
| ... policy change mid-page | `[M8]`, `[M8b]` | MET |
| ... delete of an artifact with a live query session | `[M9]`: the open session sees `AuthorizationChanged`, a new session opens, and collection of the first generation is blocked or clean | MET |
| No deletion follows a failed inventory | `[M5]`, `[M6]` | MET |
| A replayed page changes nothing | `[M3]`, `[M4]` | MET |
| Publication uses the existing `BuildAuthority` compare | `::test_publication_uses_the_build_authority_and_writes_one_published_index_event`; `[M15]` (a stolen active pointer fails the compare-and-swap); `sync.py` calls `capture_build_authority` at 1171, 1273, 1497 and 1635 and `store.publish_staged_generation` at 1226, and has no other publication path | MET |
| The active generation is never deleted | `::test_the_runtime_never_deletes_the_active_generation`; `[M20]` spies `discard_generation`, `collect_generation`, `_clear_passages`, `delete_passages_for_source` and `delete_code_nodes_for_source` on the store class across three syncs including one that fails before publish, and asserts the runtime calls none of them; `[M19]` (a tombstone mid-build leaves the first generation's rows in place); `[M13]`, `[M14]` | MET |
| `IndexEvent` rows are written for the append lane | `::test_publication_uses_the_build_authority_and_writes_one_published_index_event`; `[M13]` asserts no `published` event exists before publication | MET |
| The runtime forbids network, model and clock use inside `emit` | `sync._emit_one` (`sync.py:967-970`) enters `guard.forbid_effects()` **inside** the worker body submitted to the pool (R65), and `sync._emit` maps `guard.EmitSideEffect` to `ConnectorContractViolation`; `[M10]` drives a violating connector for each of `_GUARD_VIOLATIONS` and asserts the sync raises and writes no `Generation`. See section 6.1 for the one hole | MET with F1 |
| The same suite passes on LadybugDB with reopen proven; Neo4j parity recorded | `::test_the_last_published_generation_survives_ladybug_close_and_reopen_after_a_failed_sync` (skipped unless `HIPPO_TEST_STORE=ladybug`); the CK3 LadybugDB line is root-owned; `neo4j-parity.md` records CK3 at `94c891f`, exit 0, 108 passed | MET (root evidence) |
| After a policy-only change two more syncs publish; every stored span keeps its `policy_id`; narrowing loses the passage at the checkpoint; widening is visible only after a new revision (M8b) | `[M8b]`, in full: the artifact's policy moves, `_span_policies` of the first generation is unchanged, the revision's `span_policy_id` is still the first capture's (R48), the narrowed policy is absent from the second generation's spans, and widening reaches the spans only on the third sync after a new revision | MET |
| Two syncs of unchanged content inside the policy TTL leave `authorization_epoch()` unchanged and an open session still validates (M21) | `[M21]` | MET |
| Between first capture and first publication a partition source contributes nothing to a query session (M22) | `[M22]`: capture rows exist, no active generation, a session validates, and no `Passage` native row names the source | MET |
| A template version bump rebuilds an unchanged partition (M4 of the review) | `::test_a_template_version_bump_rebuilds_an_unchanged_partition` (R52: `no_changes` is decided after the candidate generation) | MET |
| A disabled connector instance is refused at entry (M5 of the review) | `::test_a_disabled_connector_instance_is_refused` (R51) | MET |

One clause of design section 7 step 5 is not what the code does. The design says parse failures
"are `ParseFailure` rows in the batch and become `Generation.coverage_json` counts per family and
parser; **the previous revision's records stay**". R37 ratified S3 DV1 - every member revision is
re-emitted and carrying records forward is a later optimisation - so a revision whose `emit` raises
this run contributes nothing to the new generation even though it published last run, and the
previous *generation* (not the previous revision's records) is what stays queryable. `[M11]` runs
one sync and asserts publication plus the `emit_failed` count, so nothing pins the second-sync
behaviour either way. Finding F14. Separately, `sync.py:1013-1017` attributes every raised
exception to `target.descriptor.families[0]` regardless of which family the revision classified as,
so a multi-family connector's failure counts land in the wrong bucket; spec section 3 requires
failures counted per language and dialect. Finding F15.

`test_staged_records.py`, `test_connector_http.py`, `test_connector_credentials.py`,
`test_connector_guard.py`, `test_generation_profiles.py`, `test_build_authority.py` and
`test_build_run.py` are green inside the same line and carry the writer, transport, credential,
guard and authority halves.

## 5 Gates CK4, CK5, CK6

### 5.1 CK4 - the test kit, the scaffold and the commands. Verdict: MET.

| CRITERIA clause | Proof | Verdict |
| --- | --- | --- |
| Every contract, purity, runtime and registry assertion of design section 8 has a negative fixture that fires it and a positive fixture that passes | `testing.ASSERTIONS` is 25 names in five groups. `test_connector_testing_kit.py::test_every_assertion_has_exactly_one_negative_fixture` asserts `set(VIOLATIONS) == set(kit.ASSERTIONS)`; `::test_a_negative_fixture_fires_its_own_assertion[...]` is parametrized over all 25; `::test_a_negative_fixture_fires_no_other_assertion_of_its_group[...]` over the 17 contract and capture rules; `::test_the_fixture_connector_passes_every_assertion` is the positive fixture and ends with a `run_case` against the committed goldens. The twelve `CONTRACT_ASSERTIONS` are design section 8's twelve rules one for one, including m18's wording in `assert_edges_fully_attributed` | MET |
| `hippo connector new` writes a package whose `hippo connector validate` passes | `test_connector_scaffold.py::test_a_new_package_passes_validate`, `::test_a_new_packages_own_test_passes`, `::test_new_writes_the_documented_package_files`, `::test_a_scaffolded_package_is_ruff_clean`, `::test_scaffold_output_for_a_fixed_request_is_pinned`; `test_cli_connector.py::test_new_writes_a_package_and_exits_0` | MET |
| `probe`, `list` and `sync --dry-run` run against the fixture connector | `test_cli_connector.py::test_probe_prints_family_and_mapping_per_partition`, `::test_list_shows_built_in_in_repo_and_entry_point_connectors`, `::test_sync_dry_run_prints_coverage_and_writes_nothing_to_the_configured_store` | MET |
| `remote.py` forwards the commands | `test_cli_connector.py::test_list_forwards_to_the_running_server_when_the_store_is_locked`, `::test_remote_connectors_maps_a_401_and_a_coded_refusal`. R7 narrowed this to `list` alone; the CRITERIA sentence is stale and is finding F7 | MET as amended by R7 |
| The developer guide exists and its examples are the fixture connector | `test_connector_scaffold.py::test_the_guide_exists_and_every_python_example_is_the_fixture_connector`, `::test_the_guide_documents_every_assertion`, `::test_the_guide_carries_no_credential_and_no_user_data` | MET |
| The loader lists a failing entry point with its error and continues, skips one missing from the allowlist, and `hippo serve` startup installs a frozen registry | `test_connector_loader.py::test_loader_lists_a_failing_entry_point_and_continues[import_error]` and `[registration_refused]`, `::test_loader_skips_an_entry_point_missing_from_the_allowlist`, `::test_serve_startup_installs_a_frozen_registry`, `::test_serve_startup_with_an_unreachable_store_loads_no_kinds_and_says_so` (re-review N2), `::test_loading_a_frozen_registry_registers_nothing_until_restart`, `::test_a_package_named_after_a_built_in_kind_keeps_its_built_in_entry` (R69), `::test_a_connector_whose_descriptor_name_differs_is_a_name_mismatch` (R64) | MET |
| `check_capture` and `probe_deterministic` exist with negative fixtures (M12, M13) | `testing.CAPTURE_ASSERTIONS`; the two parametrized negative-fixture tests above; `::test_check_capture_bounds_its_reads_by_sample`, `::test_check_capture_accepts_a_sync_connector_without_emit` (R1's declaration route) | MET |
| One purity guard, S3's per-thread `forbid_effects`, serves the kit and the runtime (B3) | `test_connector_testing_kit.py::test_the_purity_guard_is_the_runtime_guard` asserts `kit.purity_guard is guard.forbid_effects`; `testing.py:48` is the import; probe 3 confirms the identity at run time | MET |

### 5.2 CK5 - the port. Verdict: MET.

| CRITERIA clause | Proof | Verdict |
| --- | --- | --- |
| `add_text`, `add_upload` (including ZIP) and `add_repo` dispatch through `LocalConnector`, `GitConnector` and `connectors/lanes.py` | `test_connector_local.py::test_add_text_and_a_prose_upload_dispatch_through_the_prose_lane`; `test_connector_git.py::test_add_repo_and_code_uploads_dispatch_through_the_code_lane[repo|archive|file]`; `test_connector_local.py::test_a_connector_source_reindex_is_refused_by_dispatch` (R43) | MET |
| The kit's capture-side contract assertions pass on both connectors (R1's condition) | `test_connector_local.py::test_the_local_connector_passes_check_capture`; `test_connector_git.py::test_the_git_connector_passes_check_capture`; both descriptors declare the lane rather than raising, pinned by `::test_local_descriptor_declares_no_templates_parsers_predicates_or_emit` and its git twin | MET |
| For every existing fixture the published generation's checksums, spans, passages, native rows, receipts and coverage equal the pre-kit path's, proven by a test that runs both paths on the same fixture | `tests/fakes/connector_parity.py::published_snapshot` builds ten comparisons - `generation_checksums`, the reference closure walked the way `generation_checksums` walks it, native rows, native relationships, the `Generation` row, the accepted manifest, index manifests, index events, the receipt and the raw object inventory - and the parity tests compare the two worlds whole: `test_connector_local.py::test_pasted_text_through_the_runtime_is_byte_identical_to_the_pre_kit_path[first_text|long_text]`, `::test_a_prose_upload_...`, `::test_a_text_refresh_...`, `::test_an_unchanged_rebuild_...`; `test_connector_git.py::test_repository_bootstrap_...`, `::test_repository_refresh_...`, `::test_archive_and_code_file_...[archive|file]`, `::test_the_capture_fixture_repository_...`, `::test_a_resumed_code_build_through_the_runtime_equals_the_pre_kit_resume` | MET |
| The ported connectors write `configuration_json` unchanged, so no generation id and no id namespaced by one is normalized in the comparison | `test_connector_local.py::test_the_accepted_configuration_is_byte_for_byte_the_pre_kit_configuration`; `connector_parity.world` pins ids with a counter (`_Counter`) shared by both worlds and pins the generation clock, so the comparison is byte identity rather than a normalization. The only field removed is `registry_fingerprint` (`connector_parity.py:533`), and `CLOSURE_SKIPPED` names `Generation` for that reason alone | MET |
| The one allowed difference is `Generation.registry_fingerprint`, which `generation_checksums` does not hash | `test_connector_local.py::test_registry_fingerprint_is_the_only_generation_field_that_differs`; `test_connector_git.py::test_registry_fingerprint_is_the_only_generation_field_that_differs_on_the_code_lane`; B1/R47's two adoption tests `::test_a_retried_prose_generation_keeps_its_stored_registry_fingerprint` and `::test_a_reclaimed_code_generation_keeps_its_stored_registry_fingerprint` | MET |
| The CD1 and CD2 CHECK lines pass verbatim | Re-run here: CD1 exit 0, 133 passed; CD2 exit 0, 169 passed, 2 skipped | MET |
| LadybugDB acceptance at the recorded size passes | `root-evidence.md`: CD9 at `HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE=8`, run by the orchestrator at `cb00f04`, exit 0, 354 passed, 2 skipped (R4) | MET (root evidence) |

`test_connector_local.py::test_the_runtime_path_writes_no_connector_or_sync_state_row_and_no_connector_id`
and its git twin pin R5. `test_layering.py::test_only_managed_activation_imports_the_connector_kit`
pins R54 and carries a positive control that the guard regex matches a real import.

### 5.3 CK6 - the exemplar. Verdict: MET.

| CRITERIA clause | Proof | Verdict |
| --- | --- | --- |
| The exemplar imports nothing outside `hippo.connectors` public modules and the knowledge model | `test_connector_exemplar.py::test_the_exemplar_imports_only_the_public_kit_and_the_knowledge_model` walks every `.py` under the package with `ast` and compares against an allowlist of `hippo.connectors`, `.base`, `.keys`, `.render`, `.classify` (R60), `.http` and `hippo.knowledge.model`, with `hippo.connectors.testing` admitted in the package's own tests only | MET |
| It registers at least one new object kind with a fact template and one new predicate with an owner family | `::test_the_extension_registers_a_new_kind_with_fact_templates_and_a_windowed_predicate_owned_by_incident`: `incident` (family `incident`, key template `("instance", "incident_id")`, `incident_summary@1` and `incident_resolution@1`) and `AFFECTS` (windowed, incident -> service, owner `incident`, sources `metadata`), and it first asserts that neither is a built-in (R13) | MET |
| `hippo connector validate` passes | `::test_validate_passes_the_exemplar_and_reports_its_registry_diff`, asserting `scope == "full"` and the six-line registry diff | MET |
| A fixture syncs into a scratch workspace | `::test_a_fixture_syncs_into_a_scratch_workspace_and_publishes_one_generation` | MET |
| A query through the existing query path returns its rendered facts with citations that resolve to its spans | `::test_search_returns_the_rendered_fact_of_the_incident`; `::test_every_citation_of_the_rendered_fact_resolves_to_the_record_span`; plus the two access tests `::test_a_restricted_incident_is_never_returned_to_a_reader_outside_its_allow_list` and `::test_an_incident_with_unknown_visibility_is_returned_to_nobody` | MET |
| The probe and validate results are visible through the Task 15 connector routes and the MCP tool | `test_connector_surfaces.py::test_get_connectors_lists_the_exemplar_with_its_instance_and_classification`, `::test_post_probe_runs_the_stored_instance_config_and_stores_the_classification`, `::test_get_classification_returns_the_stored_probe_result`, `::test_post_validate_returns_the_validation_report_of_the_exemplar`, `::test_post_validate_runs_no_scratch_build_and_reports_scope_contract` (R8), the four `test_the_mcp_tool_*` tests, and `::test_route_and_tool_payloads_are_the_same_builders` | MET |

`::test_a_malformed_line_is_a_counted_parse_failure` closes R75(4)/R79 by exercising
`failures.json` for the first time, and `::test_an_update_page_republishes_and_a_complete_scan_withdraws_the_missing_incident`
is R80's substitute for the absent `fixtures/update/` case.

## 6 The two standing rules

Design section 0: "Two standing rules the kit enforces, not merely states." CK7's CRITERIA asks
whether tests enforce them. The second is enforced; the first is enforced except along one
reachable path. Section 6.3 carries R19's owner-family comparison, which belongs to the second
rule's vocabulary and which no slice owned.

### 6.1 No connector calls a language model

**Enforced by tests, with one reachable hole (finding F1).**

The chain, end to end:

1. `connectors/guard.py:34-82` is one sorted table of 47 forbidden calls, covering the sockets
   (`socket.socket.connect`, `connect_ex`, `socket.getaddrinfo`), the HTTP clients
   (`httpx.Client.send`, `httpx.AsyncClient.send`), every `hippo.ollama.Ollama` entry point
   (`_chat`, `chat_json`, `chat_text`, `embed`, `embed_explicit`, `embed_one`, `pull`), the
   subprocess and exec family (`_posixsubprocess.fork_exec`, `os.fork`, `os.system`, the eight
   `os.exec*`, `os.posix_spawn`, `posix_spawnp`), the threads
   (`threading.Thread.start`, `_thread.start_new_thread`), the profiler
   (`sys.setprofile`, `threading.setprofile`, so leaving the guard cannot trip it), and every clock
   spelling including R65's `process_time_ns`, `thread_time`, `thread_time_ns`.
2. `forbid_effects` installs a `sys.setprofile` hook for the calling thread only. CPython reports a
   `c_call` before running it, so a refused call never happens.
3. `sync._emit_one` (`sync.py:967-970`) enters the guard **inside** the pool worker (R65), and
   `sync._emit` (`sync.py:1008`) turns `guard.EmitSideEffect` into `ConnectorContractViolation`,
   which fails the sync.
4. `testing.purity_guard` **is** `guard.forbid_effects` (`testing.py:48`), so the kit and the
   runtime cannot drift; `test_connector_testing_kit.py::test_the_purity_guard_is_the_runtime_guard`
   asserts the identity.

How a violation fails, by test. `test_connector_guard.py::test_the_guard_refuses[...]` has 31
executed cases, each asserting an `EmitSideEffect` whose message starts `emit called `, names the
entry, and leaves `sys.getprofile() is None` afterwards.
`::test_the_forbidden_set_is_the_plans_names_plus_m20s` pins all 47 names byte for byte, and
`guard._partition()` resolves every one at import or raises `LookupError`.
`::test_the_guard_never_patches_a_module_attribute` proves nothing is monkeypatched, and
`::test_the_guard_affects_only_the_entering_thread`,
`::test_the_guard_nests_and_restores_a_previous_profiler` and
`::test_the_guard_is_removed_after_a_violation_and_after_a_normal_exit` cover the lifecycle. At the
runtime level, `test_connector_sync.py::test_the_failure_matrix[M10]` drives a violating connector
for each seeded effect and asserts the sync raises `ConnectorContractViolation` and writes no
`Generation` row.

The 16 names with no executed case of their own were checked by probe 6
(`/tmp/hippo-review-probe6.py`): the five other `Ollama` methods, five `os.exec*` and
`posix_spawnp` spellings, and `time.gmtime`, `time_ns`, `monotonic_ns` and `perf_counter_ns`. Every
one was refused. `Ollama.pull` is a generator function, so it is caught on its first `next()`
rather than on the call that builds the generator; a connector that built one inside the guard and
iterated it outside would escape, which no shape of `emit` has, since `emit` returns a batch.

Probe 2 (`/tmp/hippo-review-probe2.py`) confirms this independently: `time.time`, `time.monotonic`,
`socket.getaddrinfo`, `socket.connect`, `httpx.get`, `subprocess.run`, `os.system`,
`datetime.datetime.now`, `threading.Thread.start` and a `datetime.date` subclass's `now` are all
refused with the documented message. Mutation `guard_model`, which drops the Ollama entries from
the guard's two matcher tables, fails exactly
`test_the_guard_refuses[ollama_chat_json]` and `[ollama_embed]` and nothing else, so those rows
bite.

**The hole.** CPython unsets the profiler for a thread when a profile hook raises, so an `emit`
that catches the refusal is unguarded for the rest of that call. `EmitSideEffect` subclasses
`RuntimeError`, so an ordinary `except Exception` catches it. Probe 3
(`/tmp/hippo-review-probe3.py`) reproduces the consequence: an `emit` body with a two-attempt
`try/except Exception: continue` around `Ollama.embed` has its **second** call delivered to the
provider (the recorded transport logs `http://ollama.test/api/embed`) and returns a batch.
`assert_emit_pure` (`testing.py:785-807`) only sees a propagating `EmitSideEffect`, so
`hippo connector validate` does not catch it either. The reproduction, run against the installed
package:

```text
client = httpx.Client(transport=httpx.MockTransport(transport), base_url="http://ollama.test")
ollama = Ollama("http://ollama.test", "llm", "embed", client=client)


def emit_that_swallows():
    "An emit body with an ordinary broad except, as a third-party connector may well have."
    for _ in range(2):
        try:
            return ollama.embed(["a passage"])
        except Exception:      # the connector's own retry
            continue
    return None


with forbid_effects():
    result = emit_that_swallows()

# {"model_calls_that_reached_the_provider": ["http://ollama.test/api/embed"],
#  "embed_returned": true,
#  "kit_purity_guard_is_the_runtime_guard": true}
```

This is `evidence-s3a.md` question Q2, which R65 answered with the parenthetical "(the sync fails on
the first)" - a premise nothing enforces. Finding F1.

### 6.2 No connector writes a relation label it did not derive from syntax, metadata or a named rule

**Enforced by tests.** Five independent gates, each with a test that bites:

| Gate | Where | Test | How a violation fails |
| --- | --- | --- | --- |
| The predicate must be registered | `emit._registered` | `test_connector_emit.py::test_a_kind_nothing_registered_is_refused_before_any_record_is_built`, `::test_unregistered_or_undeclared_type_at_bind_is_refused[...]` | `BindRefused("predicate 'X' is not registered; register it with a TypeExtension before emitting")` |
| The connector's family must own it, and the edge must run in the canonical direction | `emit.check_direction_and_ownership` (`emit.py:401-433`) | `::test_non_owner_family_edge_is_refused_with_the_developer_message`, `::test_reverse_direction_edge_is_refused_with_the_developer_message`, `::test_direction_is_checked_before_ownership`, `::test_identity_predicate_is_refused_as_an_edge`, `::test_an_undeclared_but_registered_type_is_refused` | `BindRefused` naming the owner families and telling the developer to emit a `ReverseViewHint` or an `AliasEmission`. Mutation `direction` fails exactly these five plus the surface pin |
| The source must be one the predicate allows | `emit._bind_edges` (`emit.py:842-846`) | `::test_source_outside_sources_allowed_is_refused` | `BindRefused("X does not accept source Y; allowed: [...]")` |
| The `(family, source)` pair must have a row in the design's table, and the connector cannot choose the class | `emit.evidence_class`, `builtin_types.EVIDENCE_CLASS_DERIVATION` | `::test_family_source_pairs_outside_the_table_are_refused[...]` (four off-table pairs), `::test_a_connector_cannot_set_evidence_class`, `::test_no_emission_yields_model_inferred`, `::test_evidence_class_follows_the_derivation_table[...]` | `BindRefused("No evidence class for family=... source=...")`; `evidence_class` is not a field of `NodeEmission` or `EdgeEmission` at all, so setting it is a pydantic `ValidationError` |
| Every edge carries family, source and statement, and every alias names its rule | `testing.assert_edges_fully_attributed`, `assert_aliases_name_a_rule` | `test_connector_testing_kit.py::test_a_negative_fixture_fires_its_own_assertion[edges_fully_attributed]` and `[aliases_name_a_rule]`, and their no-other-assertion twins | `ContractViolation("edges_fully_attributed: (...) has no evidence class")`, `ContractViolation("aliases_name_a_rule: ...")` |

An alias cannot smuggle a class either: `emit._bind_aliases` (`emit.py:952-974`) hardcodes
`evidence_class="rule_derived"`, `source="rule"`, `weight=1.0`, and takes `status` from
`GUARDED_ALIAS_PAIRS` rather than from the connector
(`::test_guarded_alias_kind_pairs_stay_candidate`, `::test_the_guarded_pairs_are_the_schema_kinds_with_resource`,
`::test_alias_version_is_rule_derived_with_rule_name_and_version`).

One class of unearned claim is still reachable, on the edge path only: `source="reviewed"` is in
all four built-in source strings (`predicates.py:54-57`), so probe 5 shows all 33 built-in
predicates admit it, and `emit.evidence_class(registry, family, "reviewed", None)` is
`human_verified` for both families. `_bind_edges` checks only `sources_allowed`, and
`assert_edges_fully_attributed` accepts any row that exists in the table. R40 forbids an extension
evidence source from declaring `human_verified` for exactly this reason. Finding F2.

### 6.3 R19: the built-in owner families against spec section 6

R19 leaves this check to the reviewer. The 33 built-in predicates were dumped with their owner
families (probe: `Registry.with_builtins()`) and compared with spec section 6's "Deterministic,
across (owner)" and "Deterministic, within" columns. Design section 3 is explicit that the two
vocabularies are mostly disjoint - the built-ins keep their repository names, and spec section 6's
wider vocabulary "is registered by the connectors that own each predicate as they are written with
the kit ... Nothing is renamed" - so most built-in names (`BOUND_TO`, `CHANGES`, `ADDRESSES`,
`MERGED_AS`, `DECIDED_IN`, `CONTRADICTS`, `SUPPORTS`, `IMPLEMENTED_BY`, `REFERENCES_OBJECT`,
`READS_TABLE`, `WRITES_TABLE`, `READS_COLUMN`, `WRITES_COLUMN`, `VIEW_READS`, `HAS_CONSTRAINT`,
`FK_REFERENCES`, `HAS_CRITERION`, `DUPLICATE_OF`, `RENAMED_TO`, `MENTIONS`, `ALIAS_OF`) have no
counterpart in spec section 6 and nothing to check.

Where the names do coincide, the owner families agree in eleven cases - `PART_OF`, `DEPENDS_ON`,
`PROVIDES_API`, `CONSUMES_API` and `EXPOSES_ENDPOINT` are `service`; `DERIVES_FROM`, `HAS_COLUMN`
and `FK_REFERENCES` are `db`; `BLOCKS` is `work`; `SAME_OBJECT_AS` is the identity predicate every
family may emit (design section 4); `ALIAS_OF` is owned by every family including `custom`.

Three coincide and disagree, and an extension cannot repair any of them, because registering the
same name is `shadows_builtin` and a built-in's `subject_kinds`, `object_kinds` and `owner_families`
cannot be widened:

| Name | Built-in as landed | Spec section 6 | Consequence |
| --- | --- | --- | --- |
| `OWNED_BY` | owners `{code, service}`, catalog entities and `endpoint` -> `group, owner, person, team, user` | Work row, `OWNED_BY -> Team (work)` | A work connector can neither register `OWNED_BY` nor store the built-in one (`work` is not an owner). It must emit a differently named predicate or a `ReverseViewHint` |
| `TRACKS` | owner `{work}`, `ticket -> criterion, decision, requirement` | Work row, `TRACKS -> Incident (work)` | The owner agrees, the endpoints do not: `incident` is not a built-in kind (R13), so `TRACKS -> Incident` is `BindRefused("Invalid endpoint kinds for TRACKS")` and the endpoint set cannot be widened |
| `SUPERSEDES` | owner `{prose}`, decision and document kinds | listed in both the Prose **and** the Change sets "within" columns | A change connector emitting `SUPERSEDES` is refused: `change` is not an owner |

None of these blocks CK1-CK6: the exemplar's `AFFECTS` is a fresh name, and the seven connectors of
spec section 5 are outside this ledger's scope. They are written down here because R19 asks for the
comparison and because the first slice to write a work, change or incident connector meets all
three. Finding F13.

## 7 Invariants

| Invariant | How it was verified | Holds |
| --- | --- | --- |
| Reads never validate vocabulary (R39) | Probe 1: a `KnowledgeObject` of kind `zzz_never_registered` and an `Artifact` of an unregistered kind both validate and round-trip through `model_validate_json`, while `REGISTRY.check_record` refuses each with "Unknown object kind" / "Unknown artifact kind". Tests: `test_registry_model.py::test_vocabulary_fields_accept_any_code_without_a_registration`, `::test_a_row_of_an_unregistered_kind_reads_back_outside_its_registry`, `::test_an_unregistered_kind_is_refused_at_write_and_reads_back_afterwards`, `::test_projection_leaves_out_and_counts_rows_of_unregistered_vocabulary`, `::test_answer_location_is_empty_for_an_unregistered_locator`. Mutation `check_record` (making it a no-op) fails 36 tests including `::test_an_unregistered_kind_is_refused_at_write_and_reads_back_afterwards` | Yes |
| Existing row identities and the v7 checksum unchanged | `test_store_migrations.py::test_v7_descriptor_and_indexes_are_frozen_at_their_published_values` pins all seven published checksums by literal and recomputes `V7_CHECKSUM` from `_descriptor(7)`; `::test_v8_descriptor_adds_unit_and_the_widened_columns_only` proves v8 is v7 plus `Unit` and `V8_ADDED_COLUMNS` and nothing else; `test_registry_model.py::test_v8_fields_leave_existing_identities_unchanged` | Yes |
| Pre-kit prose and code outputs byte-identical through the lanes | `connector_parity.published_snapshot`'s ten comparisons, over two worlds that share a pinned id counter and a pinned generation clock, so nothing is normalized except `Generation.registry_fingerprint`. Nine parity tests across `test_connector_local.py` and `test_connector_git.py`, plus CD1 and CD2 verbatim and CD9 at N=8 in `root-evidence.md` | Yes |
| Refusal at registration, never at emit | Section 2's two 31-row parametrized suites, one at `Registry.register` and one at `bind_batch`; `registry.py` raises `RegistrationError` only from `_checked`, which only `register` and `_ensure_builtins` call | Yes |
| Unknown policy is deny everywhere, including the principal map | Probe 4 over `base.map_principals`: an unknown observation stays unknown; an allow list the mapping empties becomes unknown; an unmapped **deny** entry makes the whole observation unknown; unmapped allow entries are dropped and counted; and with no `principal_map` configured at all a restricted policy becomes unknown rather than open. `emit.policy_record` then writes `mode="unknown"`. `PolicyObservation` itself refuses a known restricted policy with no allowed principal. Tests: `test_connector_emit.py::test_unknown_policy_observation_is_stored_as_mode_unknown`, `::test_provider_policy_always_carries_its_expiry`; kit assertions `unknown_policy_is_deny` and `unknown_policy_carries_no_principals` with negative fixtures; `test_connector_exemplar.py::test_an_incident_with_unknown_visibility_is_returned_to_nobody`. R73: `ProviderForbiddenError` and `ProviderNotFoundError` on `fetch_policy` also become unknown | Yes |
| The active generation is never deleted | `test_connector_sync.py::test_the_runtime_never_deletes_the_active_generation`; matrix `[M20]` spies the five deletion entry points across three syncs, one of them failing before publish, and asserts the runtime calls none; `[M13]`, `[M14]`, `[M19]`, `[M22]` cover the failure paths | Yes |
| Publication only through `BuildAuthority` | `sync.py` reaches publication only at `_publish` (line 1220), which calls `store.publish_staged_generation` once and re-captures authority; `capture_build_authority` is called at 1171, 1273, 1497 and 1635; `::test_publication_uses_the_build_authority_and_writes_one_published_index_event` and `[M15]` (a stolen pointer fails the compare-and-swap) | Yes |
| The guard is the one guard | `testing.py:48` aliases `guard.forbid_effects` as `purity_guard`; `::test_the_purity_guard_is_the_runtime_guard` asserts identity; probe 3 confirms it at run time; the repository has no second guard (`grep` for `forbid_effects` finds `sync.py`, `testing.py` and the tests only) | Yes, subject to F1 |

## 8 QUALITY

### 8.1 Layering and imports

`test_layering.py` and `test_import_order.py` are green (43 passed). R54's single `ingest` ->
`connectors` edge is pinned by
`test_layering.py::test_only_managed_activation_imports_the_connector_kit`, which scans every
`ingest` module and, importantly, carries a positive control
(`assert CONNECTORS_IMPORT.search("from ..connectors import lanes")`) so a regex that stopped
matching would fail rather than pass vacuously. R76's reverse edge is pinned per file by
`::test_the_ported_connectors_never_import_the_dispatch_or_the_pipeline[connectors/lanes.py|local/connector.py|git/connector.py]`.
`test_registry.py::test_registry_modules_import_nothing_outside_the_knowledge_leaf_modules` and
the six `::test_each_knowledge_module_imports_first_in_a_fresh_interpreter[...]` rows keep
`knowledge/registry.py` a leaf, which is what lets `knowledge` stay ignorant of `hippo.connectors`
(R15).

### 8.2 Duplication

`knowledge/staged_records.py` (575 lines) reproduces the helper shape of `knowledge/staged_code.py`
(788 lines): `_vector`, `_accepted`, `_groups`, `_payload`, `_write_batches`, `_check_ceiling`,
`_write_batch`, `_persisted`, `probe_*`, `_inventory`, `_seal`, `write_staged_*`. `_vector` is
byte-identical between the two; `_check_ceiling` differs only in the word "record"/"code" in its
message; `_seal` differs only in how it reaches the bundle and which fencing helper it opens. This
is a consequence of R1 and CK5: the reviewed prose and code writers cannot be touched while
byte-identity is the gate, so the kit grew a third writer beside them rather than absorbing them.
Recorded as F9, with the two trivially shareable helpers named.

The kit does **not** duplicate `input_binding.py`: `connectors/lanes.py` is 100 lines and delegates
the derivation half to the reviewed coordinators, which is exactly R1's shape.

### 8.3 Error surfaces

`web/routes/connectors.py` maps four connector vocabularies to coded responses
(`credential_unavailable` 409, `provider_unavailable` 502, `registration_required` 409,
`connector_refused` 409) and discards the raised text, because a provider error names the URL it
called and a mistaken configuration can put a token in it (m6's lesson). `ConnectorNotFound`
answers 404 with a sentence written in the module that names only the caller's own input. The route
and MCP payloads are the same builder functions, pinned by
`test_connector_surfaces.py::test_route_and_tool_payloads_are_the_same_builders`, so the two
surfaces cannot drift; `::test_a_connector_failure_is_a_coded_response_with_a_redacted_message`
pins the redaction and `::test_every_connector_route_requires_manage_sources` the capability. The
CLI's exit codes are pinned per condition across twenty `test_cli_connector.py` tests. This is
good, consistent error design.

Two API-design observations. `POST .../probe` correctly uses POST for a side-effecting read-only
provider call, and `POST .../kinds/{name}/validate` correctly avoids GET for an expensive
computation; neither is a REST problem. What is missing is a bound: `probe_payload`
(`routes/connectors.py:136-157`) calls a third-party connector's `probe` synchronously in the
request with no timeout, which design section 10's "bounded by the runtime rather than by the
connector's good behaviour" does not allow (F4). And `GET /api/connectors` enumerates every
`Connector` row with no pagination and no workspace filter (F12).

### 8.4 Determinism

`bind_batch` is deterministic by test (`test_connector_emit.py::test_bind_batch_is_deterministic`);
`emit` is called twice and diffed by `assert_emit_pure`; the registry fingerprint is independent of
registration order (`test_registry.py::test_fingerprint_is_independent_of_registration_order`) and
ignores model titles and descriptions but not field names; goldens are canonical JSON sorted by id
with run-local ids normalized to stable tokens (R75(2)) and content-hash ids written whole;
`connector_parity` pins both the id counter and the generation clock. `render.py` is a pure module
by construction. `_support_group` derives its group id from the sorted span ids, so support grouping
is order-independent.

### 8.5 Test honesty

Five source mutations were applied in-process (`/tmp/hippo_mutation_plugin.py`) against the suites
the evidence files claim cover them. Every one was caught, and each failed a precisely targeted set:

| Mutation | What it breaks | Result |
| --- | --- | --- |
| `direction` | `emit.check_direction_and_ownership` never refuses | 6 failed / 170 passed: the five ownership and direction tests plus the S2 surface pin |
| `check_record` | `Registry.check_record` is a no-op | 36 failed / 110 passed, including `test_an_unregistered_kind_is_refused_at_write_and_reads_back_afterwards` |
| `guard_model` | the guard stops matching the Ollama client | 2 failed / 35 passed: exactly `test_the_guard_refuses[ollama_chat_json]` and `[ollama_embed]` |
| `span_bytes` | `emit.verify_span` returns the emitted text | 87 failed / 89 passed |
| `render_prefix` | `render.unit_text` drops the prefix from `embed_text` | 2 failed / 174 passed: exactly the two hash tests |

No suite passed under a mutation it claims to cover. Two smaller honesty notes: the 47-row totality
table's `Unit.embed_text` row expects the same string as `Unit.text` because that fixture has no
prefix, so the prefix half of `embed_text` is carried elsewhere
(`test_registry_model.py::test_unit_embed_text_is_its_prefix_followed_by_its_text` and the
`render_prefix` mutation above); and `test_connector_sync.py::test_the_guard_reports_one_violation_per_emit_call`
does not test what its name says (F3).

### 8.6 The exemplar and the kit's public surface

`test_connector_exemplar.py::test_the_exemplar_imports_only_the_public_kit_and_the_knowledge_model`
is the strongest evidence in the kit that the public API is sufficient: an AST scan over every
module of a working connector, against a seven-module allowlist. It found nothing, which means the
exemplar needed no private import to register a kind, build keys, render facts, classify, replay a
transport and publish. `test_connector_emit.py::test_the_surface_s3_s4_and_s6_require_from_s2_is_present_by_name`
pins the same surface from the other direction.

### 8.7 Open questions each evidence file left

The seventeen evidence files raise open questions and findings in every slice. All but four are
closed by a ruling
(R39/R40 close s1a's four; R66 closes s1b's two; R70/R71 close s2a's 1-3; R68 closes s3b's four;
R73 closes s3c's 1-6; R75/R79 close s4a's four; R77 closes s4b's 1-4; R64 closes s4c's 1-3; R72/R78
close s5a's 1-6 and s5b's findings; R80 closes s6's 1-4, sending the probe bound and the validate
404 to Task 15). Four were left for this review, and all four are ruled here:

1. **s3a Q2, "a caught violation leaves the rest of that `emit` call unguarded."** Not closed by
   R65, whose "(the sync fails on the first)" is the premise that fails. **Ruling: F1, fix before
   CK7 closes.**
2. **s2a Q5, "a `symbol` key cannot carry a null signature."** Unruled. **Ruling: F10, assign by
   name to the first slice that writes a code connector with the kit; nothing breaks before then,
   because the code lane keeps its own binder (CK5).**
3. **s4b Q5, "`--family` defaults to `custom`."** Unruled. **Ruling: F11, make it required, as
   design section 9 already writes the command.**
4. **s5b finding 3 and s5a Q1, `resource` declared by both ported descriptors and published by no
   fixture.** R78 keeps it. **Ruling: acceptable. `test_local_descriptor_covers_every_record_the_lanes_write`
   is a subset check by design (a declaration may be a superset); the cost is that a declared kind
   nothing publishes is unpinned, which is a documentation cost, not a correctness one. No finding.**

Three findings in this review come from the design comparison rather than from an evidence file:
F13 is R19's owner-family check against spec section 6, which no slice owned and no evidence file
raised; F14 is design section 7 step 5's stale "the previous revision's records stay"; F15 is the
family attribution of an emit failure.

Two further observations that are not findings. `evidence-s5b.md` finding 2 records that a
repository build clones once and walks twice (the connector for the inventory, the coordinator for
capture); this is what plan sections 4.1 and 4.2 specify and what keeps the bytes identical, and it
is the one cost the port adds. And R1's shape means the two ported connectors implement no `emit`
at all, so the kit's emit contract is exercised in production code only by the S6 exemplar (the
fixture connector is test code); that is the ratified design, but it is worth the orchestrator
knowing that the emit half has one shipping user today.

### 8.8 Security and trust (design section 10)

Connectors are read-only to providers by contract and by test
(`check_capture`'s five rules, `test_connector_git.py::test_git_list_changes_refuses_a_credentialed_url_before_cloning`,
`credentials.refuse_inline_secrets` refusing any config field whose name contains `credential`,
R65). Only enabled kinds and enabled instances run (R50, R51,
`test_connector_loader.py::test_a_discovered_kind_that_is_not_enabled_is_listed_and_not_registered`,
`test_connector_sync.py::test_a_disabled_connector_instance_is_refused`). Third-party entry points
are allowlisted from `HIPPO_CONNECTOR_ALLOWLIST` (R57) and a missing one is skipped
(`::test_loader_skips_an_entry_point_missing_from_the_allowlist`). `hippo connector enable` refuses
in open mode for any kind but `local` (R64,
`test_cli_connector.py::test_enable_in_open_mode_exits_2_with_the_stores_message`). Runs are
bounded by `SyncOptions` (`max_pages`, `batch_size`, `emit_workers`, `emit_timeout_seconds`,
`max_batch_records`), and `test_connector_emit.py` and `[M10]` pin the emit budget. The one place
the bound is missing is the probe route (F4).

### 8.9 One record-keeping gap

CK6 persists - the exemplar syncs a fixture into a scratch workspace and is queried back - but its
CHECK line is Fake only, there is no CK6 LadybugDB line, and `neo4j-parity.md` has no CK6 entry
although R80 says the S6 parity is root-owned and run beside the S5 files. `evidence-s6.md` records
both files as LadybugDB-green, so the run exists and the ledger does not name it. Finding F8. The
ledger is the orchestrator's; nothing here changes it.

## 9 Findings

Severity: BLOCKER = CK7 cannot pass; MAJOR = fix or assign by name before CK7 closes;
MINOR = record and assign.

| id | Sev | file:line | Gate or invariant | The exact fix |
| --- | --- | --- | --- | --- |
| F1 | MAJOR | `src/hippo/connectors/guard.py:171-203` | CK7 standing rule 1; CK3 "the runtime forbids network, model and clock use inside `emit`" | The refusal is swallowed by any `except Exception` in `emit`, and CPython has already unset the profiler, so the rest of that call is unguarded and a second model call reaches the provider (reproduced: `/tmp/hippo-review-probe3.py`). In `_hook`, set `_state.violation = refused` before raising; in `forbid_effects`'s `finally`, raise `EmitSideEffect(_state.violation)` when a violation was recorded and no exception is propagating, then clear it - so a swallowed violation still fails the sync. Additionally change `class EmitSideEffect(RuntimeError)` to `class EmitSideEffect(BaseException)` so an ordinary broad `except` cannot catch it (`sync.py:1008` and `testing.py:794` name the class explicitly and both precede their broad handlers, so neither call site changes). Add `test_connector_guard.py::test_a_swallowed_violation_still_leaves_the_guard` and a `[M10]`-style row driving a connector whose `emit` catches and retries. Owner proposed: a S3-fix on `connectors/guard.py` and its tests. Reruns CK3 and CK4 |
| F2 | MAJOR | `src/hippo/connectors/emit.py:842-846`; `src/hippo/knowledge/predicates.py:54-57` | CK7 standing rule 2; CK2 "`evidence_class` follows the design's derivation table and a connector cannot set it" | `reviewed` is in `DECLARED`, `PARSED`, `DISCUSSED` and `MENTIONED`, so all 33 built-in predicates admit it (probe 5), and `emit.evidence_class(registry, family, "reviewed", None)` is `human_verified` for both families. `_bind_edges` checks only `sources_allowed`, so a connector emitting `EdgeEmission(source="reviewed")` stores a `human_verified` edge with no reviewer - the claim R40 forbids an extension evidence source from making, and the class design section 4 reserves for the reconciliation queue's acceptance path. Refuse it at bind: in `_bind_edges`, after the `sources_allowed` check, `if emission.source == "reviewed": raise BindRefused(f"{emission.predicate}: reviewed is the reconciliation queue's source (spec 4.3); emit the rule you derived the fact from")`, and drop `reviewed` from the four source strings in `predicates.py`, keeping the two `reviewed` rows in `EVIDENCE_CLASS_DERIVATION` for Task 12's acceptance writer. Add one negative test beside `::test_source_outside_sources_allowed_is_refused`. Reruns CK1 (the fingerprint moves and `::test_builtin_predicates_carry_owner_families_sources_and_verb_phrases` pins the source sets) and CK2, and nothing else: no committed golden or `registry.lock.json` contains `registry_fingerprint`, and `extension_lock` hashes only the extension's own definitions (re-review N3). Owner proposed: a S2-fix (`emit.py`, `predicates.py` and their tests) |
| F3 | MINOR | `tests/unit/test_connector_sync.py:1228-1234` | CK3 test honesty | `test_the_guard_reports_one_violation_per_emit_call` names R65's one-violation-per-call behaviour and its body asserts only `issubclass(EmitSideEffect, RuntimeError)` and three `FORBIDDEN_CALLS` memberships. Rename it to `test_the_guard_pins_the_process_and_thread_clock_names`, or fold the three membership assertions into `test_connector_guard.py::test_the_forbidden_set_is_the_plans_names_plus_m20s`, which already pins the whole tuple; then add the real test as part of F1. Owner proposed: the same S3-fix as F1 |
| F4 | MINOR | `src/hippo/web/routes/connectors.py:136-157` | Design section 10, "bounded by the runtime rather than by the connector's good behaviour" | `probe_payload` calls a third-party `probe` synchronously in a request with no timeout, so a connector that blocks holds a FastAPI threadpool worker indefinitely. Run it through a `ThreadPoolExecutor` with `future.result(timeout=...)` as `sync._emit` does, and answer `provider_unavailable` (502) on `TimeoutError`. Assign to Task 15 beside the probe sample bound R80 already sends there |
| F5 | MINOR | `src/hippo/connectors/sync.py:202-211` | CK3; `evidence-s3c.md` open question 5 | `ensure_connector(..., enabled: bool = False)` is written to an existing row, so re-ensuring an instance to change its configuration silently disables it. R73 answered "pass `enabled=` deliberately", which makes every future caller carry the trap. Make it `enabled: bool | None = None`: `None` creates a row disabled (R51 unchanged) and leaves an existing row's value alone; `True`/`False` are explicit. Update the callers that pass it (`cli.cmd_connector`'s `enable`, `testing.prepare_instance`, S6's routes) and add one test. Owner proposed: a S3-fix. Reruns CK3 and CK4 |
| F6 | MINOR | `docs/spec/connector-developer-kit.md:347-349` | CK1 (R13) | Design section 5 says the spec section 4.1 prefixes "are the built-in kinds' prefixes"; R13 registered only today's `OBJECT_KINDS`, so `coll`, `sprint`, `inc`, `alert`, `sec` and `term` are reserved and not registered. Reword to "are reserved for the connectors that register those kinds; the built-ins are the thirty kinds of `knowledge/builtin_types.py`". Orchestrator owns `docs/spec` |
| F7 | MINOR | `ai_docs/gates/rag-it-all/cdk/GATES.md:42` | CK4 CRITERIA wording | "`remote.py` forwards the commands" is stale: R7 narrowed it to `list`, which is what ships and what `test_list_forwards_to_the_running_server_when_the_store_is_locked` covers. Reword to "`remote.py` forwards `list` (R7)" |
| F8 | MINOR | `ai_docs/gates/rag-it-all/cdk/GATES.md:51`; `ai_docs/gates/rag-it-all/cdk/neo4j-parity.md` | CK6 evidence | CK6 persists but has a Fake CHECK line only; there is no LadybugDB line and no CK6 entry in `neo4j-parity.md`, although the ledger's Scope makes LadybugDB the acceptance backend where persistence is touched, `evidence-s6.md` records both files as LadybugDB-green, and R80 says the S6 Neo4j parity is root-owned. Add `CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_connector_exemplar.py tests/unit/test_connector_surfaces.py -q -o addopts='' -W error` to CK6 and record the Neo4j run in `neo4j-parity.md`, or state in the Scope why CK6 is Fake-only |
| F9 | MINOR | `src/hippo/knowledge/staged_records.py:52,375,523` against `src/hippo/knowledge/staged_code.py:48,483,723` | QUALITY, duplication | The generic writer repeats the code writer's eleven-helper shape; `_vector` is byte-identical, `_check_ceiling` differs only in one word of its message, `_seal` only in how it reaches the bundle. CK5's byte-identity is what blocks unifying the three writers, so record it as a follow-up for the slice that retires the two pre-kit writers (design section 11 puts that after spec section 5's connectors are written), and move `_vector` and `_check_ceiling` into a shared leaf now, which changes no output but reruns CK3 and CK5. Owner proposed: the writer-retirement slice for the unification, any S3-fix for the two shared helpers |
| F10 | MINOR | `src/hippo/connectors/base.py:551,559`; `src/hippo/knowledge/identity.py:283-292` | `evidence-s2a.md` open question 5, unruled until now | `KeyValue = Text \| SqlPart \| tuple[SqlPart, ...]` has no null member, but `symbol_key`'s `signature` is `str \| None`, so a kit connector cannot emit a `symbol` node with no signature, and `""` would mint a different identity from the code lane's `None`. Nothing breaks today (the code lane keeps its own binder, CK5). Assign by name to the first slice that writes a code connector with the kit, or add `None` to `KeyValue` now with one key test |
| F11 | MINOR | `src/hippo/cli.py` `connector new`; `evidence-s4b.md` override 5 | Design section 9's command signature | `--family` defaults to `custom`, and a `custom`-family connector owns no predicate in spec section 6's table, so the first real edge it emits is refused by `check_direction_and_ownership` rather than at `new`. Design section 9 writes the command as `new <name> --family <f> [--kinds ...]`, family required. Make it `required=True` (one argparse keyword, one row in `test_connector_arguments_parse`). Owner proposed: a S4b-fix. Reruns CK4 |
| F12 | MINOR | `src/hippo/web/routes/connectors.py:97`; `src/hippo/cli.py:909`; `src/hippo/connectors/loader.py:159`; `src/hippo/store/authorization.py:86` | QUALITY, API design | `Connector` carries `workspace_id` in `identity_fields`, but all four readers enumerate `_knowledge_rows("Connector")` unfiltered, so connectors are installation-scoped in practice and workspace-scoped in the model. Latent only: `migrations.py:71` installs the one workspace and nothing creates a second. `GET /api/connectors` is also unpaginated. Assign to Task 15: filter by workspace at all four readers when it adds workspaces, and page the route |
| F13 | MINOR | `src/hippo/knowledge/predicates.py:90,122,146` | R19, "the reviewer checks the table against spec section 6" | Three built-in names coincide with spec section 6 and disagree with it, and an extension can repair none of them (`shadows_builtin` on the name; a built-in's endpoint kinds and owner families cannot be widened): `OWNED_BY` is `{code, service}` against spec's Work row `OWNED_BY -> Team (work)`; `TRACKS` agrees on owner `work` but its object kinds cannot admit `incident`, which R13 leaves unregistered, so spec's `TRACKS -> Incident` is `BindRefused("Invalid endpoint kinds for TRACKS")`; `SUPERSEDES` is `{prose}` while spec lists it in the Change sets "within" column too. Nothing in CK1-CK6 is affected. Record all three in design section 3's "Naming" paragraph, with what a connector does instead (a distinct name, or a `ReverseViewHint`), and assign by name to the first slice that writes a work, change or incident connector. Owner proposed: the orchestrator for the design paragraph; the connector slice for the code |
| F14 | MINOR | `docs/spec/connector-developer-kit.md` section 7 step 5; `tests/unit/test_connector_sync.py` `_m11` | CK3; design section 7 step 5 | The design says "the previous revision's records stay" after an `emit` failure; R37's DV1 (every member revision re-emitted, no carry-forward) means they do not - the revision drops out of the new generation and it is the previous *generation* that stays queryable. `[M11]` runs one sync only, so neither reading is pinned. Amend the design sentence to R37's shape, and extend `_m11` to a second sync asserting that the failed revision's records are absent from the new generation and that the previous generation is still readable. Owner proposed: the orchestrator for `docs/spec`, a S3-fix for the test. Reruns CK3 |
| F15 | MINOR | `src/hippo/connectors/sync.py:1013-1017` | CK3; spec section 3 "parse failures are counted per language and dialect" | Every exception raised by `emit` is counted against `target.descriptor.families[0]`, so on a connector that declares more than one family the count lands in the wrong family. Take the family from the revision's classification (`target.mapping`) and fall back to `"unknown"` rather than to the first declared family, and pin it with a two-family fixture. Owner proposed: a S3-fix. Reruns CK3 |

## 10 Verdicts

| Gate | Verdict | Note |
| --- | --- | --- |
| CK1 | **MET** | Every CRITERIA clause has a named test; the two 31-row refusal suites are the strongest part of the kit |
| CK2 | **MET** | The 47-row totality table is complete against spec section 3; F2 is a gap in a neighbouring rule, not in a CK2 clause |
| CK3 | **MET** | M1-M22 and M8b are real behavioural tests, not shape assertions; F1 qualifies the emit-guard clause without unmeeting it, because every violation that propagates does fail the sync |
| CK4 | **MET** | All 25 assertions have a negative fixture that fires only its own rule and a positive fixture that passes; CRITERIA wording stale per F7 |
| CK5 | **MET** | Byte-identity is real byte-identity: both worlds share a pinned id counter and clock, and only `registry_fingerprint` is removed. CD1, CD2 re-run verbatim here; CD9 at N=8 in `root-evidence.md` |
| CK6 | **MET** | The AST import allowlist is the proof that the public kit is sufficient; evidence record gap per F8 |
| Standing rule 1 (no model call in `emit`) | **Enforced with a reachable hole** | F1 |
| Standing rule 2 (no unearned relation label) | **Enforced by tests** | Five independent gates, all mutation-tested; F2 is an adjacent evidence-class hole on the edge path |
| QUALITY | **PASS WITH CHANGES** | Layering, error surfaces, determinism and test honesty are strong. F9 (duplication) is ratified debt; F4, F5, F11, F12 and F15 are ordinary API and correctness fixes; F6, F7, F8, F13 and the design half of F14 are record-keeping |
| **CK7 overall** | **PASS WITH CHANGES** | F1 and F2 fixed or assigned by name; F3-F15 recorded and assigned. No BLOCKER |

**Counts: 0 BLOCKER, 2 MAJOR, 13 MINOR.** Every finding names an owner or an owning slice, which
is what CK7's "every finding closed or assigned by name" asks for.

Reruns the fixes imply: F1 -> CK3, CK4; F2 -> CK1 (the fingerprint moves when `sources_allowed`
changes, and the built-in source sets are pinned) and CK2, and nothing else, because no committed
golden or lock carries the fingerprint; F3 -> CK3; F5 -> CK3, CK4; F9 -> CK3, CK5; F11 -> CK4;
F14 -> CK3; F15 -> CK3. F4, F6, F7, F8, F10, F12 and the design half of F13 and F14 are
documentation, ledger or Task 15 work and rerun nothing.
