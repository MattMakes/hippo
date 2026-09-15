# CDK S2a evidence: the connector contract, canonical keys and classification

Worker `backend-developer-4`, branch `wp/s2a`, base `95867be` (the `rag-it-all-tibs` HEAD naming
S1a's merge `d0bd052`). Contract: Task S2a of `ai_docs/plans/cdk-s2-contract.md` section 10, with
sections 4.1–4.3, 4.6, 5 and 6, amended by the rulings the brief
`ai_docs/handoffs/briefs/cdk-s2a.md` names and by its review-amendment section (B2, M6, M9, M10, m6,
m7, m21 of `ai_docs/reports/2026-09-15-cdk-plan-review.md`). S1a's surface is read from
`ai_docs/gates/rag-it-all/cdk/evidence-s1a.md`, including its review amendments.

## Commits

| # | Hash | Subject | Files |
| --- | --- | --- | --- |
| 1 | `7da6494` | Add the connector contract, canonical keys and classification (CDK S2a) | `connectors/__init__.py`, `connectors/base.py`, `connectors/keys.py`, `connectors/classify.py` (new); `knowledge/identity.py` (the R28 grant); `tests/unit/test_connector_contract.py`, `test_connector_keys.py`, `test_connector_classify.py` (new) |

This evidence file is a second, documentation-only commit. No file outside the brief's "own" list was
touched: `git show --stat 7da6494` is exactly the eight files above.

## RED

| Stage | Log | Result |
| --- | --- | --- |
| The three test files before any implementation | `/tmp/hippo-s2a-red.log` | exit 2; three collection errors, each `ModuleNotFoundError: No module named 'hippo.connectors'` — the shape the plan's step 1 predicts |

Two test-side defects surfaced on the first GREEN run and were fixed in the tests, not the code: a
helper that took `data` both positionally and by keyword, so the content-hash mismatch case could not
be built, and an assertion that expected `Orders` where `sql_identifier` folds an unquoted postgres
identifier to `orders` (the test now pins both the folded and the quoted spelling).

## GREEN (final tree, `7da6494`)

| Line | Log | Result |
| --- | --- | --- |
| Plan step 2 / the CK2 CHECK line's S2a subset: Fake, `test_connector_contract.py test_connector_keys.py test_connector_classify.py` | `/tmp/hippo-s2a-green.log` | exit 0, 100 passed |
| Plan step 3 regression: Fake, `test_layering.py test_import_order.py test_ingest_readers.py test_knowledge_identity.py test_knowledge_contracts.py` | `/tmp/hippo-s2a-regress.log` | exit 0, 193 passed |
| The same regression set at the `95867be` baseline, in the root tree before any change | `/tmp/hippo-s2a-regress-baseline.log` | exit 0, 193 passed |
| Plan step 4 lint: Ruff `check` then `format --check` over `src/hippo/connectors`, `knowledge/identity.py` and the three test files | `/tmp/hippo-s2a-ruff.log` | exit 0 and exit 0; "All checks passed!", "8 files already formatted" |

Counts per backend: Fake 100 new plus 193 regression, equal to the baseline. No LadybugDB line: S2a
adds no persisted column and touches no store path (CK2 needs no LadybugDB line, plan section 11). No
Neo4j run; the rulebook forbids one without a written grant.

Every line ran with `-W error` alone. No anyio filter was needed: none of the five files imports
`fastapi.testclient` (plan section 11). No warning was suppressed.

`test_layering.py` and `test_import_order.py` pass unchanged, so neither needed the brief's BLOCKED
path: `hippo.connectors` is a new top layer, and those two files pin `knowledge` → `ingest` only. The
`knowledge` → `connectors` rule lives in S2's own file, as plan decision 35 says, and the fresh
interpreter import test covers `hippo.connectors`, `.base`, `.keys` and `.classify`.

## Where a ruling or the review overrode the plan

1. **R24 and R42 over plan DV6 and question Q7.** `PASSAGE_CHAR_BOUND = 6000`, recorded in the code
   as the specification's 1,500 tokens at four characters per token. The plan's text says 1,500.
2. **R26 over R11's module name.** The one counter is `connectors/base.py:token_count`, not
   `connectors/contract.py`, which no plan and no design creates. It is `len(text)`, the character
   measure `ingest/chunker.py` budgets with (`size_chars`), pinned by a test that also reads the
   chunker's source.
3. **R28 over plan section 12's do-not-touch entry for `identity.py`.** `file_key`, `commit_key` and
   `resource_key` are public helpers there; `keys.py` calls them instead of re-spelling the arrays
   the code lane writes. That is the only edit to the file, and the parity tests compare against
   `code_binding._file_object`, `code_binding._data_object` and the `code_history` commit object.
4. **R45 and review M10 over the brief's R31 line.** S2a supplies **no** byte verifiers. The brief's
   sentence ("you supply byte verifiers for the built-in line and byte-range locator kinds") is
   deleted by its own amendment section: built-in verifiers are S2b's table in `connectors/emit.py`,
   only extension locator kinds set `LocatorKindDefinition.verifier`, and there is no byte-range
   built-in kind. `Registry.locator_kind(name)` (S1a-fix) is what `validate_against` uses to resolve
   a declared locator kind.
5. **R46 (review m7).** `ConnectorDescriptor` gains `extension: TypeExtension`, appended after
   `parsers`; S3 compares each registered definition with it.
6. **R48 (review B2).** `RevisionInput.span_policy_id: str`, with a validator, so every span keeps the
   policy of the revision's first capture.
7. **R53 (review M6).** `NodeRef.instance`, admitted on identity-only foreign endpoints and
   normalized; `keys.canonical_key` fills the instance parts from it when it is set.
8. **R44 (review M9), as the orchestrator ruled on 2026-09-15.** The amendment names
   `policy_record`, which plan sections 4.5 and 10 place in `emit.py` (S2b's file). Asked and
   answered: option (a). S2a owns the `PrincipalMap` contract and the pure
   `map_principals(policy, principal_map) -> (PolicyObservation, dropped)` in `base.py`, with one
   test per rule; S2b's `emit.policy_record` reads `connector.config_json["principal_map"]` and calls
   it. "An allow list the mapping empties" is read **per list** (the orchestrator's answer): either
   emptied allow list makes the observation `unknown`. R30's "instance configuration contract" is
   that `PrincipalMap` shape, not a base class every `config_model` must subclass, which would break
   the S5 and S6 configuration models.
9. **Review m6.** The bound message is raised at bind and is therefore S2b's; S2a ships only
   `PASSAGE_CHAR_BOUND`. Confirmed by the orchestrator in the same reply.
10. **Review m21.** `test_keys_is_the_only_knowledge_object_constructor_in_connectors` also flags
    `KnowledgeObject.model_validate`, `.model_validate_json`, `.model_construct` and `.replace`
    outside `keys.py`, and any `replace`/`model_copy`/`model_construct` call carrying a
    `canonical_key` keyword. Because the check is near-vacuous over three modules today, a
    parametrized companion test runs the detector over seven synthetic sources, one per forbidden
    spelling, so the check is proved to flag before S2b relies on it.
11. **The orchestrator's R-S2-10 addition (2026-09-15, by `horch tell`).** "connectors/base.py
    re-exports `current_registry` (and `extension_scope`, `use_registry`) from `knowledge.registry`,
    so a connector's probe and the kit never import `hippo.knowledge.registry` directly. Add it to
    your S2a public API with a one-line test." Added, with
    `test_base_reexports_the_registry_accessors_so_a_connector_never_imports_the_registry`. It comes
    from S4's re-plan, which is uncommitted in the root tree.
12. **R16** binds S2b's binder, not S2a: the only registry check S2a makes is
    `RevisionInput`'s `registry.frozen` ("emit requires a frozen registry"). Nothing here compares a
    registry with `current_registry()` by identity.

## Decisions this slice took where the plan is silent

- **`NodeRef.instance` is `ProviderURL | None = None`, not `Text = None`.** `Contract` sets
  `validate_default=True`, so a `Text` field defaulting to `None` refuses its own default at class
  definition. `ProviderURL` is the existing `knowledge/contract.py` alias whose validator is
  `normalize_provider_url`, which is exactly what R53 asks for.
- **`span_policy_id` is validated against the `AccessPolicy` identity shape** (`accesspolicy-` and 64
  hex characters, derived from `k.AccessPolicy.identity_prefix`, never a literal), with the message
  `A revision input names the AccessPolicy its spans keep`. The plan gives no message for it.
- **`RawFetch` and `NodeRef` set `hide_input_in_errors=True`.** Both carry a URL that may hold
  credentials in a mistaken configuration, and Pydantic otherwise prints the refused input. Two tests
  assert the secret does not appear in the refusal. The same reason keeps the connector instance out
  of `keys.py`'s refusals.
- **One message the plan does not list:** `A canonical URI must be a parseable URI`, for a
  `canonical_uri` that `urllib.parse.urlsplit` cannot parse at all. Without it the credential
  refusal would have to claim something it has not checked.
- **Database keys take their dialect from a `SqlPart`.** `database_object_key` needs dialect-aware
  parts, and `database` and `schema` (the leading-three and leading-four prefixes) have no `parts`
  entry to take one from, so the dialect comes from the first `SqlPart` among catalog, schema and
  parts. A `database` whose catalog is a plain string is refused with `Kind database needs a SqlPart
  key part to fix its dialect`.
- **`keys.canonical_key` validates its `instance` argument even for a kind with no instance part**, so
  a connector configured with a non-normalized instance fails on its first node rather than on its
  first instance-keyed one.
- **`ItemDecision` gains a trailing `warnings: tuple[str, ...] = ()`.** The plan's dataclass has no
  field for `declared_tabular_shape_missing` or `tabular_without_declared_kind`, and the partition's
  `warnings` must carry both. Additive and defaulted; no sibling plan pins the field list.
- **A declaration whose `shape="tabular"` does not match tabular bytes falls through to content and
  name**, not to the next matching declaration, and carries its warning onto whatever decides.
- **`tabular.ndjson` needs at least two non-empty lines.** One line of JSON object is also a JSON
  document, and the design's tabular rule is about streams of homogeneous rows; the csv rule already
  requires a second row.
- **`k8s.manifest` reads the first YAML document**, skipping a leading `---` separator, since a
  manifest that starts with one would otherwise have an empty head.
- **Unclassified items do not vote for the partition family**, and a partition with no classified item
  takes the descriptor's family when it declares exactly one, else `custom`.
- **An unmapped provider record type is counted in the partition's fallback family** with
  `rule="unclassified"`, `detector="kind_mapping"`; a mapped one is `rule="descriptor"`, level
  `kind`, outcome `<family>/<kind>`.
- **`EmissionBatch` key uniqueness is per kind** (passage keys among passages, unit keys among units),
  because `unit.passage` and `edge.unit` are separate namespaces.
- **The commit-key parity test is a source pin.** `code_history` builds its commit object inline
  inside a function that needs store rows, so the test asserts `commit_key`'s array and the literal
  spelling at the writer's anchor, rather than calling it.

## The purity test's interception list

`test_classify_is_pure_under_reordering_clock_and_forbidden_io` runs `classify` twice inside
`monkeypatch.context()` blocks — first with every target raising, then with the clock returning a
fixed different instant and the items reversed — and asserts the two `Classification`s are equal,
including their JSON. The "two clocks" of the plan is that pair, because `classify` takes no clock
argument at all. Intercepted:

`socket.socket.connect`, `socket.create_connection`, `socket.getaddrinfo`,
`subprocess.Popen.__init__`, `httpx.Client.send`, `httpx.AsyncClient.send`, every public method of
`hippo.ollama.Ollama` (read off the class, so a new method is covered), `time.time`, `time.time_ns`,
`time.monotonic`, `time.perf_counter`, `time.sleep`.

The patches are scoped to a context manager rather than the bare `monkeypatch` fixture, so pytest's
own call-phase timing is never running against a patched clock.

## The "requires from S2" lists that name an S2a module

Verified by importing the built modules and comparing names and signatures
(`inspect.signature`), at `7da6494`.

| Requirement | Where it is defined | Satisfied |
| --- | --- | --- |
| S3 "From S2": `descriptor_configuration`, `ContractError`, and the `base.py` records `Connector`, `ConnectorDescriptor`, `ChangePage`, `Change`, `ExternalRef`, `SyncCursor`, `RawFetch`, `PolicyObservation`, `TypeMapping`, `PartitionClassification`, `Classification`, `RevisionInput`, `EmissionBatch`, `ParseFailure` | `base.py:287` (`descriptor_configuration`), `:75`, `:767`, `:232`, `:321`, `:316`, `:297`, `:310`, `:338`, `:370`, `:468`, `:520`, `:531`, `:726`, `:697`, `:687` | yes |
| S3 `KEY_RULE_VERSION`, `CLASSIFIER_VERSION` | `keys.py:36`, `classify.py:35` | yes (`BINDER_VERSION` and `RENDER_RULE_VERSION` are S2b's) |
| S3 `RevisionInput(partition, artifact, revision, data, config, mapping, registry)` | `base.py:726`, plus `span_policy_id` (R48) | yes, with the ruling's field |
| S4 R-S2-1: every section 4.1 record importable from `hippo.connectors.base`, with `Family`, `Clock`, `ContractError`, `RegistrationRequired`, `PASSAGE_CHAR_BOUND`, `token_count` | `base.py:51` (`Clock`), `:41` (`Family`), `:54`, `:65`, `:75`, `:79`; every record class | yes; none missing |
| S4 R-S2-2: `check_key_parts(definition, ref)`, `canonical_key(registry, ref, *, instance)` | `keys.py:67`, `keys.py:83` | yes, character for character |
| S4 R-S2-5: `base.token_count` behind the passage bound; `TOKEN_BOUND = base.PASSAGE_CHAR_BOUND` | `base.py:65`, `base.py:54` | yes |
| S4 R-S2-8: `base.py` re-exports `TypeExtension`, `ObjectKindDefinition`, `PredicateDefinition`, `FactTemplate` | `base.py:40-45` | yes |
| S4 R-S2-10 (the re-plan, uncommitted): `classify(descriptor, config, items, registry, *, spec, capabilities, kinds=(), attributes=())`, `classifier_spec(*, declarations=(), sql_dialects=())`, and `current_registry` re-exported from `base` | `classify.py:127`, `classify.py:87`, `base.py:47-49` | yes, signatures equal |
| S4's scaffold shape `NodeRef(kind=..., key={"id": ...})` with the kit filling `instance` (M16) | `base.py:554`, `keys.py:83` | yes: an instance part inside `key` is refused, and the builder fills it |
| S5 R-S2-1: empty `predicates`, `parsers`, `credentials`; an emit-less connector declared by `capabilities.derivation="coordinator_lane"` | `base.py:232` (only families, artifact kinds and locator kinds must be non-empty), `:179`, `:754` (`SyncConnector` has no `emit`) | yes |
| S5 R-S2-2: `ChangePage`, `Change`, `ExternalRef`, `RawFetch`, `PolicyObservation`, `Classification`, `ConnectorCapabilities`, `SyncCursor`, `Clock` from `hippo.connectors.base` | `base.py:321`, `:316`, `:297`, `:338`, `:370`, `:531`, `:179`, `:310`, `:51` | yes |
| S5 R-S2-3: the name-level classifier over `readers.is_code_name` and `is_plain_prose_name` | `classify.py:361` (`_name`, reached by `classify_item`, `classify.py:96`) | yes |
| S5 R-S2-4: `connectors/__init__.py` imports nothing | `connectors/__init__.py` (docstring only), pinned by `test_the_connectors_package_marker_imports_nothing` | yes |
| S6 R-S2-1: the registry definition classes re-exported | `base.py:40-45` | yes |
| S6 R-S2-2: the records, `RawFetch`'s timestamp fields, `PolicyObservation` workspace/restricted/unknown | `base.py:338`, `:370` | yes; `ParserVersion` is structured, so the exemplar uses `ParserVersion.parse("json@1")` (review m8) |
| S6 R-S2-3: the built-in `service` key builder | `keys.py:155` (`_service`, through `canonical_key`) | yes, and R53 lets the exemplar key it by its declared `catalog_instance` |
| S6 R-S2-6 / R6: a node of a foreign family | contract side only here; the identity-only binding is S2b's | deferred to S2b by the plan |

## Open questions and what S2b inherits

1. **`KeyPartsRefused` re-parenting.** `keys.KeyPartsRefused` subclasses `base.ContractError`; plan
   section 10 has S2b change only that base class to `BindRefused`, without renaming it. Nothing else
   in `keys.py` is S2b's to edit.
2. **`policy_record` must apply the map.** Under the ruling above it reads
   `connector.config_json["principal_map"]`, validates it with `base.PrincipalMap`, and calls
   `base.map_principals`, counting the returned drops in `EmissionCoverage` (R30's "counted"). S2a
   counts nothing: it has no coverage record.
3. **A `symbol` key cannot carry a null signature.** `symbol_key`'s last part is `str | None`, but
   `NodeRef.key` values are `Text | SqlPart | tuple[SqlPart, ...]`, so a symbol with no signature
   cannot be emitted through the kit. The code lane, which is the only writer of symbols today, is
   unaffected (S5 keeps its lane binder). If a kit connector ever emits symbols, `KeyValue` needs a
   null member and the plan's section 4.1 line changes.
4. **S4's plan is uncommitted.** Its R-S2 list, which this file verifies against, lives in the root
   tree's working copy of `ai_docs/plans/cdk-s4-kit.md` (the re-plan R56 orders); the committed copy
   at `95867be` has the older list, whose `TOKEN_BOUND = 1500` review minor m6 supersedes.
5. **Nothing outside the brief was edited.** Two things noticed and left alone: the classifier logs
   through `sqlglot`'s own logger when a statement falls back to `Command` (a logging call, not a
   warning, so `-W error` is unaffected), and `tests/fakes/` holds no connector fixture yet — R10
   gives that to S4.
