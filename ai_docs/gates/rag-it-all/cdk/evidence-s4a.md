# CDK S4a evidence: the contract test kit

Worker `backend-developer-14`, branch `wp/s4a`, base `655ffb3` (the `rag-it-all-tibs` HEAD named in
the spawn message, after S1a, S2a, S1b, S1b-fix, S3a, S4c, S4c-fix, S3b, S2b, S2b-fix, S5a and S3c
merged). Contract: task S4a of `ai_docs/plans/cdk-s4-kit.md` (section 3.1, section 4 "S4a",
section 5's `test_connector_testing_kit.py`, section 6's S4a lines), amended by the brief
`ai_docs/handoffs/briefs/cdk-s4a.md` and its R73 amendment. Read first: `evidence-s3c.md`,
`evidence-s3a.md` and `evidence-s2b.md`.

Where a ruling and the plan differ, the ruling wins; every such case is under "Overrides".

## Commits

| # | Hash | Subject | Files |
| --- | --- | --- | --- |
| 1 | `c707974` | Add the connector test kit: contract, purity, capture, runtime and registry assertions (CDK S4a) | `connectors/testing.py` (new), `connectors/loader.py` (the R64 lines), `tests/unit/test_connector_testing_kit.py` (new), `tests/unit/test_connector_loader.py` (one test), `tests/unit/test_import_order.py` (one line), `tests/unit/test_connector_sync.py` (two granted edits), `tests/fakes/fake_ollama.py` (the `embed_text` body), `tests/fakes/fixture_connector/__init__.py`, `tests/fakes/fixture_connector/fixtures/registry.lock.json` (new), `tests/fakes/fixture_connector/fixtures/basic/changes.json`, `tests/fakes/fixture_connector/fixtures/basic/expected/*.json` (new), this file |
| 2 | `d35c9af` | Record the S4a commit hash in its evidence | this file |
| 3 | `0d25665` | Check the fixture connector's committed goldens in the positive fixture (CDK S4a) | `tests/unit/test_connector_testing_kit.py`, this file |

### Grants beyond the brief's "own" list

Four edits to `tests/fakes/fixture_connector/**` and two to `tests/unit/test_connector_sync.py` are
outside the brief. Both were asked for and granted by name; nothing else outside the brief's list
was touched.

| Grant | What it is | Why |
| --- | --- | --- |
| Orchestrator, option (a) | `fixtures/basic/changes.json` rewritten as one `ChangePage` JSON object per page | S3c landed the case with bare change lists (`{"operation","external_id"}`). Section 3.1's layout is `ChangePage` JSON, and `load_case(case_dir)` takes no descriptor, so it can synthesize neither `ExternalRef.artifact_kind` nor `FixtureCase.partition` |
| Orchestrator, option (a) | `Connector = FixtureConnector` in `fixtures_connector/__init__.py` | `load_connector_package` resolves a package through the `Connector` name design section 9 names; R64 keeps the descriptor name, the connector kind and `Connector.kind` equal |
| Orchestrator, option (a) | `fixtures/registry.lock.json` and `fixtures/basic/expected/*.json` generated and committed | The positive fixture is the real package; only `--update-golden` can write them. The grant's condition was met: both reproduce **byte-identically on Fake and on LadybugDB** (`diff -r` over the two `expected/` trees: identical; the LadybugDB `--update-golden` rerun returned an empty diff) |
| Orchestrator, option (a) | `test_connector_sync.py:548-558` | `test_the_fixture_connector_constructs_with_no_arguments` iterated `provider.case_pages()` as bare dicts. It now reads the pages from `CASE/changes.json` |
| Orchestrator, second grant | `test_connector_sync.py:536` | `test_no_production_module_passes_fault_hook_to_sync_connector` refuses any `src/hippo` module but `sync.py` that names both `fault_hook` and `sync_connector`. `connectors/testing.py` names both by design: section 3.1 gives `scratch_sync` a `fault_hook` and the five `RUNTIME_SCENARIOS` inject through it (R49 / B4). The exclusion now lists `connectors/sync.py` and `connectors/testing.py`, with that reason in a comment |
| Brief (R64) | `connectors/loader.py` `_already_registered` and its test | See "Overrides" |

Nothing else was touched: no `docs/spec`, no gate ledger checkbox, no checkpoint, no `data/`, no
`.rag-dev-data/`, no other `connectors` module, no `knowledge/`, `ingest/`, `store/`, `cli.py`,
`remote.py` or web package.

## RED

| Stage | Log | Result |
| --- | --- | --- |
| The whole S4a test file against the base tree, before any source edit | `/tmp/hippo-cdk-s4a-red.log` | exit 2; one collection error, `ImportError: cannot import name 'testing' from 'hippo.connectors'` — the shape the plan's step 1 predicts |
| The same file against a stub-only `testing.py` (every public name present, every body `NotImplementedError`) | `/tmp/hippo-cdk-s4a-red2.log` | exit 1; **23 failed, 4 passed, 57 errors** |

The plan's RED is a collection failure, which proves the module is absent but not that each
assertion bites. The second RED exists for that: with the skeleton in place every test fails for
its own reason. The four that passed against the skeleton are the ones that only read constants
and re-exported names (`test_every_assertion_has_exactly_one_negative_fixture`,
`test_token_bound_is_the_passage_character_bound`, `test_the_purity_guard_is_the_runtime_guard`,
`test_the_kit_re_exports_the_runtime_transports`), which the skeleton legitimately satisfies.

Seven assertions bit while going green, each on a real defect in the kit rather than in the test;
they are under "What going green found".

## GREEN

| Line | Log | Result |
| --- | --- | --- |
| Section 6 S4a line 1, Fake: `test_connector_testing_kit.py` + `test_import_order.py` | `/tmp/hippo-cdk-s4a-green.log` | exit 0, **105 passed** |
| Section 6 S4a line 2, LadybugDB: `test_connector_testing_kit.py` | `/tmp/hippo-cdk-s4a-ladybug.log` | exit 0, **84 passed** |
| Section 6 S4a line 3, the fake-Ollama consumers | `/tmp/hippo-cdk-s4a-fake-ollama.log` | exit 0, **1181 passed, 12 skipped** |
| Regression: the CK3 Fake CHECK line plus `test_connector_loader.py` | `/tmp/hippo-cdk-s4a-ck3-fake.log` | exit 0, **315 passed, 2 skipped** |
| Regression: the CK3 LadybugDB CHECK line | `/tmp/hippo-cdk-s4a-ck3-ladybug.log` | exit 0, **110 passed** |
| Ruff `check` then `format --check` over the eight changed `.py` files | run inline | exit 0; "All checks passed!", "8 files already formatted" |

Counts per backend for the kit itself: **Fake 84**, **LadybugDB 84**, the same cases on both.
The Fake line reads 105 because it also runs `test_import_order.py` (21).

**Warning filters.** The two S4a lines and the two CK3 lines ran with `-W error` alone: form (a) of
rulebook line 19, because no file in them imports `fastapi.testclient` at module level. The
fake-Ollama consumer line carries the sanctioned filter, **form (b)**, because that set includes
`test_web_base.py`, `test_managed_web_surfaces.py`, `test_managed_route_activation.py` and
`test_cli.py`, which do import a test client at module level:
`-W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`.
No warning was suppressed and no ini-wide filter was added. One unraisable did surface while going
green (`PytestUnraisableExceptionWarning` from an abandoned `query_session` generator in the
`delete_with_live_session` scenario) and was fixed by closing the generator in a `finally`, never
by a filter.

**No Neo4j run.** The rulebook forbids one without a written grant, which this worker did not hold.

Nothing here reads `.rag-dev-data/`, a real credential, a real token, the server on 8011 or the
user's Ollama: the kit's model is `offline_ollama()` over `httpx.MockTransport`, and every store is
a temporary one under `tempfile`.

## The R7 measurement (plan section 4 S4a step 5)

`validate_package(tests/fakes/fixture_connector)` with the **default** `scratch_store`, i.e. a
temporary LadybugDB with `buffer_pool_bytes=256 * 2**20` (finding N9, so the measured configuration
is the shipped one):

| Measure | Value |
| --- | --- |
| Scope | `full` (lock, registry diff, capture, contract, `run_case`, runtime resilience) |
| Result | `passed=True`, no violations, no golden diff |
| Registry diff | `+ connector kind fixture`, `+ kind fixture_note`, `+ predicate FIXTURE_LINKS`, `+ template fixture_note/note_summary@1` |
| Wall time | 43.3 s |
| Peak RSS | 788 MiB |

## The negative-fixture table

`VIOLATIONS` in `tests/unit/test_connector_testing_kit.py` has exactly one entry per name in
`testing.ASSERTIONS` (25), asserted by `test_every_assertion_has_exactly_one_negative_fixture`.
`test_a_negative_fixture_fires_its_own_assertion[...]` runs all 25;
`test_a_negative_fixture_fires_no_other_assertion_of_its_group[...]` runs the 17 contract and
capture names and requires the fired set to be exactly `{name}`, so no rule stands in for another.

| Assertion | Negative fixture | What it does |
| --- | --- | --- |
| `registered_vocabulary` | `_unregistered_vocabulary` | a node ref whose kind is `fixture_ghost` |
| `nodes_have_locator_and_policy` | `_node_without_span` | a node emission with `span=None` |
| `unknown_policy_is_deny` | `_unknown_policy_with_a_mode` | an `unknown` observation carrying `allow_users` |
| `edges_fully_attributed` | `_edge_without_an_evidence_row` | `(deterministic, similarity)`, a pair with no row in design section 4's table |
| `aliases_name_a_rule` | `_alias_without_a_rule` | an alias emission with `rule=""` |
| `no_ingestion_time` | `_node_stamped_with_the_clock` | a node `ts` equal to `FIXED_INSTANT` |
| `one_fact_per_unit` | `_unit_outside_its_text` | a slice unit with `start=0, end=10_000` over a short span |
| `spans_match_bytes` | `_span_that_is_not_the_bytes` | a node span quoting text the revision never held |
| `passages_within_token_bound` | `_passage_over_the_bound` | a note body of `TOKEN_BOUND` words |
| `identities_from_builders` | `_key_part_the_kind_never_declared` | `NodeRef(key={"wrong_part": ...})` |
| `direction_and_ownership` | `_edge_pointing_the_wrong_way` | `DEPENDS_ON`, a registered predicate whose declared endpoints are not `fixture_note` |
| `parse_failures_counted` | `_silent_parse_failure` | non-empty bytes, an empty batch, no `ParseFailure` |
| `emit_deterministic` | `_emit_is_not_deterministic` (`_Wobbly`) | an `emit` whose second call drops the edges |
| `emit_pure` | `_emit_reads_the_clock` (`_Impure`) | an `emit` that calls `time.time()` |
| `change_page_single_partition` | `_page_that_mixes_partitions` | a page whose change names another partition |
| `fetch_matches_ref` | `_fetch_that_answers_another_ref` | `fetch("n1")` answering `n9` |
| `canonical_uri_without_credentials` | `_canonical_uri_carrying_a_token` | a `canonical_uri` with `?token=` |
| `unknown_policy_carries_no_principals` | `_unknown_policy_with_principals` | `state="unknown"` with `allow_users` |
| `probe_deterministic` | `_probe_that_reads_the_clock` | a `probe` stamping `clock()` into a warning |
| `crash_after_fetch` | `_crash_after_fetch_commits_the_checkpoint` | a `scratch_sync` double that moves the raise from `after_fetch` to `after_checkpoint` |
| `replayed_page` | `_replay_that_moves_the_epoch` | a double that refreshes `verified_at` on every stored `AccessPolicy`, moving the epoch (the review's M3 defect) |
| `failed_inventory` | `_failed_inventory_that_deletes` | a double that sets `deleted_at` after the failure, then re-raises |
| `policy_change_mid_page` | `_policy_change_that_is_rolled_back` | a double that restores A's previous `policy_id` after the crash |
| `delete_with_live_session` | `_delete_that_is_undone` | a double that clears A's `deleted_at` after the crash |
| `registry_version_bump` | `_template_changed_without_a_bump` | a fact template whose text changed under version `1` |

The positive fixture is S3's `FixtureConnector` with its `fixtures/basic` case (R10, R-S3-7):
`test_the_fixture_connector_passes_every_assertion` runs `assert_emit_pure`, `check_contract`,
`check_capture` and `assert_registry_lock` against the committed lock, then
`assert_runtime_resilience` over all five scenarios, then `run_case` **without**
`update_golden`, against the committed `expected/` tree, and finds nothing. The last step is what
makes gotcha 7 below true: every other golden test works on a `tmp_path` copy it rewrites first, so
without it nothing in the suite would ever read the committed files. Proved by corrupting
`expected/nodes.json` to `[]` and re-running the test: it fails at the `run_case` assertion, and
the file was restored from the committed copy.

## Overrides: where a ruling, a review finding or the code overrode the plan

1. **`unknown_policy_is_deny` gains its reachable half.** Section 3.1 fires the rule when
   `emit.policy_record(...)` has `mode != "unknown"`. That half is **unfalsifiable** through S2:
   `emit.py`'s `policy_record` writes `mode="unknown" if mapped.state == "unknown" else mapped.mode`,
   and `base.map_principals` returns an unknown observation unchanged, so no input makes an unknown
   observation produce another mode. The reachable defect is next to it: `policy_record` copies the
   observation's four principal lists whatever the state, so an unknown observation carrying
   principals becomes a deny-mode policy **with allowed users**. The assertion therefore fires on
   either condition. The kit still calls S2's function and adds nothing of its own.
2. **`prepare_instance` takes the instance URL from the configuration when it declares one.**
   Section 3.1 passes `instance_url=KIT_INSTANCE_URL` unconditionally. S3's entry refuses a row
   whose `instance_url` differs from a configuration that has one
   (`sync.py`: `row.instance_url != getattr(config, "instance_url", row.instance_url)`), and every
   case declares its own. `KIT_INSTANCE_URL` remains the default. R73's "each fixture world needs
   its own instance URL" is satisfied structurally: every kit run has its own temporary store.
3. **`scratch_workspace` seeds an operator user.** Section 3.1 does not mention one. In open mode
   `store/knowledge.py:682` refuses an enabled non-`local` `Connector` row while `count_users() == 0`
   (S3c gotcha 6, R64), so `prepare_instance` step 1 would be refused on every kit run. The
   workspace calls `ensure_roles()`, `create_user("kit-operator", ...)` and
   `set_meta("reviewed_mapping_authorities", ["local"])`, the `test_connector_sync.py` `World`
   shape, and `ScratchWorkspace` carries the `user_id` so `connector_source` can own its Source.
4. **The goldens are normalized before they are diffed.** Section 3.1 assumes the published records
   read back with stable ids. They do not: `store/base.py:147` `new_id()` is `uuid4().hex[:12]`, so
   a `Source` id is run-local, a `Generation` id is derived from it, and so is every id hashed over
   one of them — `Passage`, `RetrievalView`, `Unit`, `Assertion` (whose `scope_key` names the
   Source), `AssertionVersion`, `AssertionSupport` and the coverage's
   `embedding_manifest_revision_id`. `_tokens` gives each a stable token (`<source>`, `<generation>`,
   `<passage-0>`, `<edge-0>`, `<version-0.0>`, ...) numbered from content that *does* reproduce — a
   span id, an ordinal, a canonical key — and `_normalise` substitutes structurally. Every other id
   is a content hash of the record itself and is written whole. Proof that this is enough:
   `test_run_case_diffs_published_records_against_the_goldens` runs the case twice and requires an
   empty diff, and the committed `expected/` tree is byte-identical between Fake and LadybugDB.
5. **Each runtime scenario run advances the pinned clock by one second.** Section 3.1 pins the store
   clock to `FIXED_INSTANT` for the whole scenario. A second publishing run at the *same* instant
   re-emits an edge whose `AssertionVersion` identity carries `recorded_from` but **not** `unit_id`,
   while the new generation mints new `Unit` rows, so the store refuses it with "Immutable record
   already exists with different contents". `_World.run` therefore sets
   `_generation_clock` to `FIXED_INSTANT + n seconds` for run *n*. This also implements **N11**,
   which asks `replayed_page`'s run 3 to happen an instant after run 2 so a re-stamped row would be
   visible; every offset stays far inside R52's half-TTL window (300 s of a 600 s TTL).
   `run_case` is a single run and stays pinned at `FIXED_INSTANT`, so the goldens are unaffected.
6. **`nodes.json` is built from the member observations, not from member objects.** A
   `KnowledgeObject` is shared across generations and is never a `GenerationEvidenceMember`
   (probed: a published fixture generation's members are `Unit` 6, `EvidenceSpan` 5,
   `ObjectObservation` 3, `DerivedRecord` 3, `DerivedDependency` 3, `RetrievalView` 3,
   `AssertionVersion` 1, `AssertionSupport` 1 — no `KnowledgeObject` and no `Assertion`). The
   generation's objects are the distinct `object_id`s its member observations name, and its
   assertions are the parents of its member versions.
7. **N3, as applied.** `extension_lock` hashes a kind as
   `{**definition.model_dump(mode="json", exclude={"attrs_model", "fact_templates"}), "attrs":
   attrs_model.model_json_schema(mode="validation")}`. N3 names the `attrs_model` exclusion;
   `fact_templates` is excluded on top of it, because each template is keyed and hashed under its
   own `template:<kind>/<name>@<version>` key, so bumping a template's version must not require
   bumping the descriptor's — which is exactly what
   `test_the_registry_lock_accepts_a_bumped_template_version` pins. N3's second half is answered
   rather than deferred: extension **locator kinds are in the lock**, keyed
   `locator:<name>@<descriptor version>` over `{"name", "model schema"}`. `verifier` is outside the
   hash because a callable is not vocabulary and the registry's own fingerprint does not read it
   either (`knowledge/registry.py`, `LocatorKindDefinition.verifier`).
8. **N7, as applied.** `_replay_connector` sets the copy's class with
   `object.__setattr__(replica, "__class__", subclass)`. The one shape requirement on a connector is
   that `copy.copy` of it be usable and its layout compatible with a `__slots__ = ()` subclass,
   which every ordinary class satisfies.
9. **N8, as applied.** `assert_emit_pure` wraps **both** calls: an `EmitSideEffect` becomes
   `ContractViolation("emit_pure")`, and any other exception from either call becomes
   `ContractViolation("emit_deterministic", "emit raised <type> on call <n>")`, so an `emit` that
   succeeds inside the runtime and raises on the kit's re-run is a named rule and not a traceback.
10. **N16, as applied, in `kit_registry`.** `kit_registry` refuses a descriptor whose extension does
    not register its own connector kind, with
    `RegistrationError("unregistered_connector_kind", ...)`, which `validate_package` reports as the
    report's `error` and `run_case` as the case's `error`.
    `test_validate_package_names_a_connector_whose_extension_omits_its_kind` pins it.
11. **N6, as applied.** `_kit_registry` is public as `kit_registry(descriptor) -> Registry`, for
    section 3.3's commands and S6's routes.
12. **N10, as applied.** `load_case` refuses a `fetches` entry that sets `source_updated_at` without
    `source_timestamp_original` (or the reverse), naming the file, rather than letting `RawFetch`
    refuse it unnamed mid-replay.
13. **N12, as applied.** `policy_change_mid_page` names its sequence: A's observation is read twice
    in one page, first as the case has it (`known`/`workspace`) and then as `unknown`, which the
    runtime stores as deny. That is the **narrowing** half of S3 section 6.3, which the row cites.
14. **N4 and m18, as applied.** Passages are read with
    `store._native_rows("Passage", generation_id=...)`; `units.json` uses
    `_knowledge_rows("Unit", ...)`, which works because S1b added `Unit` to `RECORD_TYPES`.
    `assert_edges_fully_attributed` calls
    `emit.evidence_class(context.registry, family, source, metadata_origin)`, R63's registry-taking
    signature as S2b landed it.
15. **R64, as applied in `loader._already_registered`.** Evidence sources move from the membership
    comparison to the definition comparison, through `Registry.evidence_source_definition`. Without
    it, a package whose source kept its name but changed its family or evidence class read as
    "already registered" under a frozen registry and the process served a class it never registered.
    `test_an_evidence_source_that_changed_under_its_name_is_not_already_registered` in
    `test_connector_loader.py` pins both halves and records that `evidence_source` alone cannot tell
    the two apart.
16. **R65, as applied.** `record_transport` is re-exported unchanged and the kit clears nothing of
    its own, because no committed case carries an `http/` recording. The rule stands for a connector
    that adds one: `http/` is numbered from `0000.json` and overwritten, so a re-recording must
    clear the directory first. It is stated here and in the module docstring rather than implemented,
    since S4a records nothing.
17. **`CaseError`, a name section 3.1 does not list.** `load_case`'s refusals raise
    `CaseError(ValueError)` rather than a bare `ValueError`, so `validate_package` can turn a
    malformed case into the report's `error` without catching every `ValueError` the read might
    raise. It is a `ValueError`, so the plan's callers are unaffected.
18. **`registry_diff` is a public function.** Section 3.1 describes it inside `validate_package`
    step 4. It is `registry_diff(extension) -> tuple[str, ...]`, so S4b's `validate --update-golden`
    and S6's route read the same list. `ValidationReport.registry_diff` is unchanged.
19. **`tests/fakes/fake_ollama.py` loses one line beyond `embed_text`'s body.** m17 says "`DIM` and
    every other line stay unchanged". `import hashlib` becomes unused once the body is a
    function-local import plus the call, and `ruff check` (and therefore CI) refuses it, so the
    import is removed. `DIM`, `re`, and every other line stand.
    `test_the_fake_ollama_embeds_with_the_kit_algorithm` pins the digest computed on the base tree
    **before** any edit: `sha256(embed_text("ACME builds Robot.").tobytes()) =
    db6b9cdc99c6fa294a2c150dea0958df2d8ce940d7d6d9f274c924c12a852290`, `DIM = 128`, `float32`.

## What going green found (the assertions that bit)

1. **The strict models never accept a dict** (S3c gotcha 1, R73). `ChangePage`, `PolicyObservation`
   and `RawFetch` are all built with `model_validate_json` in `load_case` and in the replay.
2. **`RenderedText.template` is `name@version`, not the template text.** `assert_one_fact_per_unit`
   compared against the text and fired on the fixture connector's own output.
3. **Each rule must skip what another rule owns.** The group tests forced it: `identities_from_builders`
   skips a ref whose kind is unregistered (`registered_vocabulary`'s), `one_fact_per_unit` skips a
   span that does not verify (`spans_match_bytes`'s) and a ref whose key cannot be built
   (`identities_from_builders`'s), and `passages_within_token_bound` skips an unverifiable span.
4. **`emit.policy_record` cannot produce the plan's condition** — override 1.
5. **`ensure_connector` is refused without a user, and again when the instance URL disagrees** —
   overrides 2 and 3.
6. **The goldens did not reproduce** — override 4 — and `nodes.json` was silently empty until
   override 6, because `KnowledgeObject` is not a generation member. A golden that is empty by
   mistake still diffs clean, which is why `test_goldens_are_canonical_json_sorted_by_id_...`
   checks the shape of every file and the R7 measurement runs the full `validate_package`.
7. **The offline model needs a real SHA-256 digest.** `knowledge/embedding_profile.py` refuses an
   installed model whose `digest` does not match `(?:sha256:)?[0-9a-f]{64}`, so `/api/tags` answers
   `sha256(model name)`.
8. **`load_connector_package` must drop cached submodules.** Two copied packages sharing a directory
   name resolve to one module name, and a stale `<name>.connector` answered for the wrong tree. The
   whole dotted prefix is deleted from `sys.modules` before the spec is executed.
9. **A `failed_inventory` scan needs two pages** for `fail_on_page=1` to be reachable: the replay
   hands back no cursor on its last page, so a one-page case never asks for page 1.

## What S4b, S5b and S6 get from S4a

| Item | Where |
| --- | --- |
| `validate_package(target, *, update_golden, runtime, allowlist) -> ValidationReport`, `ValidationReport.to_json()` | `testing.py`; scopes `capture`, `contract`, `full` as R57 ratifies |
| `load_connector_package(target, *, allowlist)` | `testing.py`; a directory or an installed name through `loader.discover_connectors` |
| `kit_registry(descriptor) -> Registry` (N6) | for `cmd_connector` and S6's routes: the built-ins plus one extension, frozen |
| `registry_diff(extension)` | the sorted `+ kind/predicate/locator/artifact kind/connector kind/template` list |
| `dry_run_sync(connector, config, *, partition=None)` | backs `hippo connector sync --dry-run`; opens no configured store |
| `check_capture(connector, config, *, sample)` | S5b's local and git connector tests (R67) |
| `assert_emit_pure`, `purity_guard` | S6's validate route and MCP tool; per-thread, so a concurrent request is undisturbed (B3), pinned by `test_assert_emit_pure_leaves_other_threads_alone` |
| `offline_ollama()`, `hashed_embedding(text)`, `EMBEDDING_DIM` | the shipped offline model; `tests/fakes/fake_ollama.embed_text` imports the second |
| `record_transport`, `replay_transport`, `ERROR_CLASSES`, `error_transport(error_class)` | S3's recorder re-exported, plus the six canned responses |
| `FIXED_INSTANT`, `SECOND_INSTANT`, `KIT_INSTANCE_URL`, `TOKEN_BOUND`, `GOLDEN_FILES`, `ASSERTIONS` | the constants a guide and a scaffold quote |
| A worked package in the documented layout | `tests/fakes/fixture_connector/`: `fixtures/registry.lock.json`, `fixtures/basic/{config,changes,policies}.json`, `inputs/`, `expected/` |

## Gotchas for the next worker

1. **A golden is normalized, not raw.** `<source>`, `<generation>`, `<passage-n>`, `<edge-n>` and
   friends are tokens, not stored ids (override 4). A reader that wants the real id must run the
   case and read `CaseResult.generation_id`.
2. **`run_case` pins the clock; `assert_runtime_resilience` advances it one second per run**
   (override 5). A new scenario that publishes twice must not re-pin the clock itself.
3. **`scratch_store` is the substitution seam.** Tests point it at the backend `HIPPO_TEST_STORE`
   names with `monkeypatch.setattr(testing, "scratch_store", ...)`; the shipped default is a
   temporary LadybugDB with a 256 MiB buffer pool (N9). `scratch_sync`, `scratch_workspace` and
   `sync.sync_connector` are all called by module-attribute lookup, so a spy or a double installed
   with `monkeypatch` is seen.
4. **`check_capture` never opens a store and never makes an HTTP call of its own.** It calls the
   connector's four sync methods, so a lane connector that shells out is fine and a connector that
   reaches the network will.
5. **`validate_package` re-imports a package by file location and clears the cached module tree.**
   Two packages with the same directory name in one process are safe, but a caller holding a class
   from a previous import holds a stale one.
6. **`assert_runtime_resilience` needs a case with two upserts** and skips `failed_inventory` by
   declaration when `capabilities.inventory` is false — never by exception, so `VIOLATIONS` still
   covers every name.
7. **The fixture connector's goldens are committed now.** Any change to S2b's binder, S3c's runtime
   or the fixture connector's `emit` will diff them; regenerate with
   `validate_package(package, update_golden=True)` and re-check on both backends before committing.

## Open questions for the orchestrator

1. **`unknown_policy_is_deny` as section 3.1 words it is unfalsifiable** (override 1). The rule is
   implemented with the reachable half added. If the reviewer wants the literal condition only, the
   assertion has no negative fixture and CK4's "every assertion has a negative fixture" cannot hold.
2. **Golden normalization is a plan gap, not a defect in S3c.** If a future slice wants raw ids in
   the goldens, `store/base.py:147`'s `new_id()` has to become injectable, which is a `store/`
   change no CDK brief grants.
3. **`GOLDEN_FILES`' `failures.json` is empty for every passing case.** `_parse_failures` reads
   `coverage["failures"]`, which S3c writes as a map. A case that exercises a `ParseFailure` would
   confirm the shape; `fixtures/basic` has none, and adding one is the scaffold's or S6's to do.
4. **`http/` recordings are unexercised by S4a** (override 16). No committed case has one, so
   `record_transport`/`replay_transport` are re-exported and tested only as identities. A connector's
   own recording tests are open question 5 of the plan, which is S6's.
