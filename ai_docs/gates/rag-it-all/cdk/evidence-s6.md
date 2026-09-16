# CDK S6 evidence: the incidents exemplar and the probe and validate surfaces

Worker `backend-developer-18`, branch `wp/s6`, base `e7b9370` (the `rag-it-all-tibs` HEAD named in
the spawn message, after S4a-fix, S4b and S5b merged). Contract: `ai_docs/plans/cdk-s6-exemplar.md`
sections 3–7, amended by the brief `ai_docs/handoffs/briefs/cdk-s6.md` and its R70/R71 and R73–R79
amendments. Read first: `evidence-s4b.md`, `evidence-s4a-fix.md`, `evidence-s3c.md` and
`evidence-s2b-fix.md`.

Where a ruling and the plan differ, the ruling wins; every such case, and every case where the
landed code overrode the plan, is under "Overrides".

## Commits

| # | Hash | Subject | Files |
| --- | --- | --- | --- |
| 1 | `e7e47ce` | Scaffold the incidents_ndjson example connector, unedited (CDK S6) | `src/hippo/connectors/examples/__init__.py` (new, hand written); `src/hippo/connectors/examples/incidents_ndjson/**` (18 files, the scaffold's own output) |
| 2 | `03359a6` | Edit the scaffold into the incidents exemplar and add the connector surfaces (CDK S6) | `examples/incidents_ndjson/{connector,types,templates}.py`, its `export/` and `fixtures/`; `src/hippo/web/routes/connectors.py` (new); `src/hippo/web/app.py` (the import and the one `include_router`); `src/hippo/mcp_server.py`; `src/hippo/cli.py` (one line, R79); `tests/unit/test_connector_exemplar.py`, `tests/unit/test_connector_surfaces.py` (new); `tests/unit/test_mcp_server.py` (`TOOL_NAMES`); `tests/unit/test_mcp_http.py` (one string, granted); `docs/MCP.md`, `docs/CONTRACTS.md`, `README.md`, `docs/spec/cdk-guide.md` (one paragraph, R79) |
| 3 | `7afbe55` | Answer a missing connector with the module's own sentence (CDK S6) | `src/hippo/web/routes/connectors.py`, `src/hippo/mcp_server.py` |
| 4 | (this commit) | Record the S6 evidence | this file (new) |

Commit 1 is the unedited scaffold, committed before a byte of it was edited, so the review reads the
diff from scaffold to exemplar (plan section 7 step 1).

Nothing outside the brief's list was touched except the three granted lines below: no other
`connectors` module, no `knowledge/`, `store/` or `ingest/`, no other `docs/spec` file, no gate
ledger checkbox, no checkpoint, no `data/`, no `.rag-dev-data/`.

### The three edits outside the brief's "own" list

1. **`src/hippo/cli.py`, one line (R79).** `hippo connector validate --update-golden` now prints
   `<connector> <version>: goldens and the registry lock written`. Granted by name in R79.
2. **`docs/spec/cdk-guide.md` section 7, one paragraph (R79).** `--update-golden` "rewrites the
   goldens **and `fixtures/registry.lock.json`**", with the reason the lock is rewritten rather than
   compared on that run. Granted by name in R79. The guide's four fenced examples are untouched and
   still equal their marked regions (`test_the_guide_exists_and_every_python_example_is_the_fixture_connector`
   is green on the CK4 line).
3. **`tests/unit/test_mcp_http.py`, one string.** The plan's section 8 second GREEN line includes
   that file, and `test_a_real_mcp_client_can_list_and_call_the_tools` asserts the tool-name list
   **inline** (`:86-96`) rather than through `TOOL_NAMES`, so `hippo_connectors` had to be added
   there too. Asked before editing; the orchestrator answered:

   > Approved: add the single string 'hippo_connectors' to the inline tool-name list at
   > tests/unit/test_mcp_http.py:86-96, nothing else in that file; name it in the evidence beside
   > the TOOL_NAMES grant.

   The whole diff to that file is one line.

## RED

| Stage | Log | Result |
| --- | --- | --- |
| Both S6 test files against the tree at commit 1 (the unedited scaffold, no routes module) | `/tmp/hippo-cdk-s6-red.log` | exit 2; one collection error, `ImportError: cannot import name 'connectors' from 'hippo.web.routes'` — the surfaces module is absent |
| `test_connector_exemplar.py` alone, against the unedited scaffold | `/tmp/hippo-cdk-s6-red-exemplar.log` | exit 1; **15 failed, 2 passed, 4 errors** |

The second stage exists because a collection error proves a module is absent but not that each
assertion bites (the gap S4b and S3c both recorded). Against the scaffolded package every exemplar
assertion bit on its own subject: no `AFFECTS` predicate, no second fact template, no `export/`
file, a `fetch` that reads `<id>.json` rather than a line, no `service` endpoint, no window, no
counted `ParseFailure`.

The two that passed against the scaffold are pins on what must **not** change, not TDD steps:

| Passed at RED | Why it legitimately does |
| --- | --- |
| `test_the_exemplar_keeps_the_scaffold_file_set_and_its_generated_test` | It measures the scaffold's own output, which commit 1 had just written. It is the pin that the exemplar does not quietly drop a scaffolded file |
| `test_the_exemplar_never_reaches_the_network_or_the_user_data` | It asserts an absence: no `http/` recording, no `ProviderClient`, no `httpx`. The scaffold satisfies it and so must the exemplar |

## GREEN

| Line | Log | Result |
| --- | --- | --- |
| The CK6 CHECK line of `GATES.md`, verbatim, Fake | `/tmp/hippo-cdk-s6-ck6.log` (= `/tmp/hippo-cdk-s6-green.log`) | exit 0, **42 passed** |
| Section 8 line 2 (mcp, mcp_http, cli), Fake, form (b) | `/tmp/hippo-cdk-s6-mcp.log` | exit 0, **96 passed** |
| Section 8 line 3, the two S6 files on LadybugDB | `/tmp/hippo-cdk-s6-ladybug.log` | exit 0, **42 passed** |
| The CK7 Ruff lines of `GATES.md`, verbatim | `/tmp/hippo-cdk-s6-ck7.log` | exit 0 and exit 0; "All checks passed!", **"51 files already formatted"** |
| Ruff `check` then `format --check` over every file this slice changed, plus the four Markdown files | `/tmp/hippo-cdk-s6-ruff.log` | exit 0 and exit 0; "All checks passed!", "18 files already formatted" |
| `hippo connector validate src/hippo/connectors/examples/incidents_ndjson`, the installed console script at the shipped default scratch store | `/tmp/hippo-cdk-s6-validate.log` | exit 0; `incidents_ndjson 1: passed (full)` |
| `hippo connector new ... --dest src/hippo/connectors/examples` (commit 1) | `/tmp/hippo-cdk-s6-scaffold.log` | exit 0; 18 files |
| `hippo connector validate ... --update-golden` (plan step 3) | `/tmp/hippo-cdk-s6-golden.log` | exit 0; the diff reviewed below |
| Regression: loader, cli_connector, testing kit, scaffold, import order, layering, Fake | `/tmp/hippo-cdk-s6-regress.log` | exit 0, **209 passed** |
| Regression: the web layer this slice adds a router to, Fake | `/tmp/hippo-cdk-s6-web.log` | exit 0, **170 passed** |

**Counts per backend** for the two S6 files: **Fake 42**, **LadybugDB 42**, the same cases on both.

**Warning filters.** The CK6 line and the LadybugDB line ran with `-W error` alone — **form (a)** of
rulebook line 19, and no marker was needed at module level, because neither S6 file imports
`fastapi.testclient` at collection time: `test_connector_surfaces.py` imports it inside `_client()`
and every test that builds a client carries the exact per-test marker. The mcp/cli line carries the
**form (b)** command-line filter the plan's section 8 prescribes, because `tests/unit/test_mcp_server.py`
imports `fastapi.testclient` at module level (`:10`). No warning was suppressed and no ini-wide
`filterwarnings` was added. **Plan section 8's claim is confirmed as written.**

**No Neo4j run.** The rulebook forbids one without a written grant, which this worker did not hold.
Nothing here reads `.rag-dev-data/`, a real credential, a real token, the server on 8011 or the
user's Ollama: every store is a temporary one, the model is `offline_ollama()` over
`httpx.MockTransport`, and the exemplar reads one file the test wrote.

## The goal sentence, end to end

The retrieval check of plan section 4 runs inside
`test_every_citation_of_the_rendered_fact_resolves_to_the_record_span`. The question is

```text
Which incident affected settlement-batch-processor?
```

asked through `search(ctx, question, session=session)` inside `query_session(ctx, reader.access)`.
The passage it resolves is INC-2210's summary fact,

```text
INC-2210 (SEV2) Settlement batch stalled: resolved; affected settlement-batch-processor from 2026-09-14T03:12:00Z
```

and `resolve_citations(session.graph, (passage_id,))` returns without raising, with
`item.is_derived` true. Every citation's `span_id` is an `EvidenceSpan` that is a
`GenerationEvidenceMember` of the exemplar's published generation; `citation.text` is INC-2210's
exact export line, `text_hash(citation.text) == citation.text_hash`, `citation.locator_kind` is
`file_lines`, and the locator is lines 1–1 of that record's revision. The two negatives hold as
well: a reader outside INC-2211's allow list never sees it, and an incident whose `visibility` mode
this connector does not recognise is returned to nobody.

## The golden diff (plan step 3), read

`--update-golden` rewrote the seven goldens and the registry lock. What moved, and why:

| Golden | Before (scaffold) | After (exemplar) |
| --- | --- | --- |
| `nodes.json` | one `incident` node for `record-1` | six: three `incident` objects keyed `["https://incidents.example","P7Q2X…"]`, three identity-only `service` objects keyed `["https://catalog.example","component:default/…"]` whose `attributes_json` is `{"key": …, "label": …}` and nothing else (R6, R71) |
| `edges.json` | `[]` | three `AFFECTS` assertions, each `valid_from` the incident's `started_at`; INC-2210 and INC-2211 closed at their `resolved_at`, INC-2212 open. Statements: "incident INC-2210 affects service settlement-batch-processor", "… INC-2211 affects service payments-api", **"incident INC-2212 affects service checkout"** — R71's sentence, produced by the label on the endpoint's `NodeEmission` |
| `passages.json` / `units.json` | one rendered fact | eight passages / eight units: five `rendered_fact` and three `rendered_edge`. INC-2210 and INC-2211 render both templates; INC-2212 renders only `incident_summary@1` |
| `failures.json` | `[{"count":1,"family":"incident","parser":null}]` | `[{"count":1,"family":"incident","parser":"json@1"}]` — R75(4) and R79 satisfied by a real fixture, with the parser named because `ParseFailure` carries `ParserVersion.parse("json@1")` (m8) |
| `coverage.json` | 1 node, 1 passage, 2 fetched, partition `export` | 6 nodes (`{"incident":3,"service":3}`), 3 edges, 8 passages, 4 fetched, partition `incidents`, `inventory: "complete"`, and **`facts_skipped: {"incident_resolution@1": 1}`** — the open incident's omitted resolution, counted rather than guessed (R-S2-5) |
| `aliases.json` | `[]` | `[]`: the exemplar proposes no alias |
| `registry.lock.json` | two keys | four: `kind:incident@1`, `predicate:AFFECTS@1`, `template:incident/incident_resolution@1`, `template:incident/incident_summary@1` |

Nothing in the diff is unexplained. `facts_skipped` and the `parser` in `failures.json` are the two
lines worth keeping: they are the specification's "no MTTR when the tool has no resolved time" and
R79's failure row, both visible in a committed file rather than in prose.

## Overrides: where a ruling, a grant or the code overrode the plan

1. **`key_template=("instance", "incident_id")`, not the plan's `("tool_instance", "incident_id")`;
   `tool_instance` dropped from the configuration.** `keys.INSTANCE_PARTS` is the closed set
   `{instance, provider_instance, catalog_instance}` and `connectors/keys.py` is S2's, so
   `tool_instance` would not be kit-filled: `emit` would have to write it from the configuration,
   while m8 separately requires an HTTP(S) `instance_url` for `ensure_connector` — two near-duplicate
   fields, and a kind whose instance discrimination bypasses the rule M16 states. Asked before any
   edit; the orchestrator answered:

   > (A) approved: key_template=('instance','incident_id') kit-filled from Connector.instance_url;
   > config = export_path, instance_url, catalog_instance, principal_map; tool_instance dropped;
   > canonical_uri f'{instance_url}/incidents/{id}'.

   The configuration is therefore `export_path`, `instance_url` (m8), `catalog_instance` (R53/M6)
   and `principal_map` (R61).
2. **The raw export lives at `<package>/export/incidents.ndjson`, not `fixtures/export/`.** The
   plan's placement is impossible as written: `testing.discover_cases` treats **every** directory
   under `fixtures/` as a fixture case, and `load_case` refuses an unexpected entry because
   `CASE_FILES + CASE_DIRS` is a closed layout. A `fixtures/export/` holding a `.ndjson` file would
   fail `validate` on the case loader, not on anything about the connector. Approved with override 1.
3. **`AFFECTS` declares `verb_phrase="affects"`, not the plan's `"affected"`.** R71 fixes the
   statement as "… affects service checkout", and the ruling wins. Approved with override 1.
4. **There is no `fixtures/update/` case.** The plan gives it two pages so a complete scan withdraws
   INC-2211, but `validate_package` runs every case **standalone** and a first sync has no parent
   generation, so a deletion is unreachable in it (S3c gotcha 7) and the case would prove the
   opposite of what it is for. `test_an_update_page_republishes_and_a_complete_scan_withdraws_the_missing_incident`
   therefore drives the update through the **real** connector over a rewritten export: sync, rewrite
   the file (INC-2212 gains `resolved_at` and a new `updated_at`, INC-2211 is removed), sync again
   with `SyncOptions(reconcile=True)`. It asserts `receipt.deleted == 1`, `inventory == "complete"`,
   INC-2211's artifact carrying `deleted_at`, and that the reader no longer sees INC-2211 while
   INC-2212 is still there. That exercises `list_changes`' own completeness rather than a replay's.
   Reported to the orchestrator in a `horch note`; no objection was raised.
5. **The package imports the registry definition models from `hippo.connectors.base`, not from
   `hippo.knowledge.registry`.** The scaffold template imports the latter (its own documented rule),
   but the plan's section 3 import allowlist admits only the public kit plus `hippo.knowledge.model`,
   and says the definitions "are therefore imported from `hippo.connectors.base`, which must
   re-export them (R-S2-1)". `base.py:40-49` does. This is the one scaffold line the exemplar changed
   for a reason other than behaviour, and `test_the_exemplar_imports_only_the_public_kit_and_the_knowledge_model`
   is what holds it.
6. **The partition is the constant `incidents`, not a configured name.** The plan's configuration
   model has no partition field and says `probe` "returns one partition, the export file". One export
   is one partition, so the name is a module constant rather than a fifth configuration field.
7. **An unparseable line is *counted*, not warned.** The plan says "an unparseable line is a
   warning". `classify.classify` computes a partition's `warnings` from its own decisions and takes
   none from the caller, so the exemplar maps a truncated line to `provider_type="unparsed"` with
   `KindMapping(provider_type="unparsed", kind=None)` — `custom/unclassified`, counted and never
   dropped, and visible in the classification the probe route returns. Warning the operator instead
   would need a `classify` change, which is S2's file.
8. **`ConnectorNotFound` carries `message` and the surfaces answer with that attribute** (commit 3).
   Printing the exception's own words would have added an unclassified site to the closed table
   `tests/unit/test_managed_web_surfaces.py:1110-1167` keeps over the whole web layer, and that file
   is not this slice's. The sentence is this module's own either way; the attribute is what makes
   that checkable.
9. **The MCP capability refusal follows `remember_tool`'s shape**, `ToolError("your role (…) may
   not do this: it needs 'manage_sources'")`, not the `DENIED` authorization-epoch sentence at
   `mcp_server.py:189-190` that plan section 6.2 points at. That branch is for a permission change
   *mid-answer*; a caller who simply lacks the capability is the `remember_tool` case.
10. **`GET /api/connectors` reads `app.state.connector_load`** when the lifespan set it, and loads
    afresh otherwise. The loader's own docstring names that attribute as what this route reads back;
    re-freezing the registry on every request would be the alternative.

## What going green found (the assertions that bit)

1. **A `TestClient` context manager closes the store.** Leaving it runs the FastAPI lifespan's
   shutdown, which calls `ctx.close()`. On LadybugDB a store read after the `with` block raises
   `RuntimeError: Connection is closed`; the Fake answers as if nothing happened, so three surface
   tests were green on Fake and red on LadybugDB. Every read-back now stays inside the block, and
   the failure-mapping test builds one client for its whole loop. This is the single most useful
   thing this slice learned, and it is in `_client`'s docstring.
2. **`RevisionInput` refuses anything but a real `AccessPolicy` id** (`base._POLICY_ID`), so a
   hand-built revision in a test needs `accesspolicy-<64 hex>`, not a readable placeholder. Likewise
   `Artifact` needs `source_id`, `connector_id` and `canonical_uri` (not `uri`), and
   `ArtifactRevision` needs `raw_uri` and a `lifecycle` from its own `Literal`.
3. **`store_classification` is vocabulary-checked**, so a test that rewrites a `Connector` row's
   `classification_json` must do it inside an `extension_scope()` that registers the kind — the same
   rule S4c-fix wrote for seeding the row in the first place.
4. **A docstring counts.** `test_every_str_exc_in_the_web_layer_is_one_the_review_classified` greps
   every non-comment line under `hippo/web`, docstrings included, so even *describing* the rule in
   prose that quotes the pattern adds an unlisted site.

## Requirements this slice consumed, satisfied by name

| Requirement | Where it landed |
| --- | --- |
| R-S1-1, R13 | `incident` is a built-in **family** and not a built-in kind; the exemplar registers the kind and keeps the `inc` prefix |
| R-S1-3, R50 | `hippo.connectors.examples` is already in `loader.IN_REPO_PACKAGES`; the package is discovered and registered only when an instance of its kind is enabled, so no production generation's `registry_fingerprint` moves |
| R-S2-1 | `base.py` re-exports `TypeExtension`, `ObjectKindDefinition`, `PredicateDefinition` and `FactTemplate`; the exemplar imports all four from there (override 5) |
| R-S2-3 | the built-in `service` key builder, reached through `NodeRef(kind="service", key={"reference": …}, instance=catalog_instance)` |
| R-S2-4 | `file_lines` as the emission locator, verified by `emit.BUILTIN_VERIFIERS` against the line bytes |
| R-S2-5 | `render.render_facts` skips `incident_resolution@1` for an open incident; `coverage.json` counts it under `facts_skipped` |
| R-S2-6, R6 | the `service` endpoint is identity only, because its family is not in `descriptor.families`; ownership is checked on the edge |
| R53/M6, R70/R71 | `NodeRef.instance` is the configured `catalog_instance`; `NodeRef.label` is the record's own `service` value, and the fixture's INC-2212 affects `checkout`, so the stored statement reads "incident INC-2212 affects service checkout" |
| R-S3-1, R-S3-2 | `sync_connector` publishes the partition and binds each rendered fact as a derived `Passage` over a `RetrievalView`; both pinned by `test_a_fixture_syncs_into_a_scratch_workspace_and_publishes_one_generation` |
| R-S3-3, R12 | `store_classification` / the stored `classification_json`, written by the probe route and read by the classification route |
| R-S3-5 | override 4's two-sync test: `receipt.deleted == 1` only from a completed inventory scan |
| R-S4-1 | `hippo connector new --dest`, `validate_package(runtime=False)`, `ValidationReport.to_json()`, `offline_ollama()`, `assert_emit_pure`, and `cli._connector_summaries` as the `ConnectorSummary` shape |
| R44/R61 | the configuration's `principal_map`; `emit.policy_record` maps `pd-user-7` to the local reader, and the reader outside the list is denied |
| R49/B3 | `test_post_validate_does_not_disturb_a_concurrent_request`: a second thread reads both clocks while a validate runs, and answers |
| R64 | the list is keyed on `(origin, name)` and renders `LoadResult.error`; `test_the_list_renders_a_load_error_and_the_frozen_spelling` covers `error="frozen"` |
| R73 | every `ensure_connector` call in this slice's code and tests passes `enabled=` |
| R75, R79 | one malformed line in the committed fixture; `failures.json` holds `{family, parser, count}` |
| R77 | `descriptor` is a class attribute; every row-seeding test signs an operator in first |
| R78 | the negative visibility fixtures are new records written as plain dicts into a scratch export, never `model_copy(update=...)` of a kit record |
| M15 | `ConnectorCapabilities(acls=True, inventory=True)`; `fetch` raises `ProviderNotFoundError` for an id absent from the export |
| m8 | `FactTemplate.consumes`, `ParserVersion.parse("json@1")`, `metadata_origin="catalog"` on every node and edge, an HTTP(S) `instance_url` |
| m11 | `CONNECTOR_FAILURES` maps `CredentialError`, `ProviderError` (and its subclasses), `RegistrationRequired` and `ConnectorSyncRefused` to coded responses whose message is this module's own; `test_a_connector_failure_is_a_coded_response_with_a_redacted_message` asserts a credentialed URL never reaches the body |

## Ledger lines

None. The CK6 CHECK line and its CRITERIA stand as written and are green; plan section 8's
"confirmed as written" holds, including that the CK6 line needs no form (b) filter. No gate checkbox
was touched.

## Gotchas for the next worker

1. **Leaving a `TestClient` context closes the store** (finding 1). On the Fake nothing happens; on
   LadybugDB the next store read raises. Keep read-backs inside the block.
2. **`testing.discover_cases` owns every directory under `fixtures/`.** Anything that is not a case
   goes somewhere else in the package; the exemplar's raw export is at `<package>/export/`.
3. **`fixtures/basic/config.json` carries `export_path: "export/incidents.ndjson"`, which nothing
   opens.** The replay connector overrides `list_changes`, `fetch` and `fetch_policy`, so the case
   never reads the file; the tests that exercise the real reader point the configuration at the
   committed export by absolute path. The value is the honest relative one a developer would write.
4. **The fixture's input file names are `quote(external_id, safe="")`.** The malformed line's id is
   its own SHA-256, so its input file is `line-sha256%3A<hash>`. Regenerate the whole case together
   if the export changes: the id, the change, the fetch entry, the policy entry and the file name
   all move at once.
5. **Re-goldening the exemplar also rewrites `fixtures/registry.lock.json`** (R79). A change to
   S2b's binder, S3c's runtime, the templates or the descriptor version moves the goldens; run
   `hippo connector validate src/hippo/connectors/examples/incidents_ndjson --update-golden`, read
   the diff, then run the plain `validate` and both backends.
6. **The exemplar's `probe` is what fills `TypeMapping.kinds`,** and the mapping is stored on the
   `Connector` row. A new provider type must be added to `KINDS` in `connector.py` or it classifies
   as `custom/unclassified`.

## Open questions for the orchestrator

1. **Neo4j parity for `test_connector_exemplar.py` and `test_connector_surfaces.py` is not run.**
   The rulebook forbids it without a written grant. Both files are Fake- and LadybugDB-green; the
   exemplar persists through `sync_connector`, so the parity run is worth scheduling on the
   disposable container with the S5 parity files.
2. **The plan's `fixtures/update/` case is not shipped** (override 4). If the reviewer wants a
   second committed case for its own sake — two pages, its own goldens, no deletion — it is a small
   addition, but it cannot demonstrate withdrawal and the current test does.
3. **`PROBE_SAMPLE` bounds the probe at 10 records**, so "the sample count is the line count" (plan
   section 3.3) holds only for exports at or under the bound, which every fixture here is. Removing
   the bound would make a probe read a whole export; the scaffold ships the bound and the exemplar
   kept it.
4. **`validation_payload` treats an unloadable package as "no such kind" (404)** when the report
   carries no connector name. A package that is installed but whose module raises on import is
   therefore reported as missing rather than as broken. `GET /api/connectors` does show it with its
   error, so the information is available; whether the validate route should distinguish the two is
   Task 15's call.
