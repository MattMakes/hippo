# RAG implementation tasks: 5A and 6–16

Extracted from [the complete implementation plan](rag_it_all.md). Includes Task 9A, the autonomous maintenance and invalidation work within this sequence. Task wording, dependencies, file ownership and checks are preserved from the source plan.

Section references and acceptance gate IDs refer to the [complete plan](rag_it_all.md), including its [acceptance gate ledger](rag_it_all.md#14-acceptance-gate-ledger). This extract is not a completion-status ledger; unfinished Task 5 work remains tracked in the main plan and execution checkpoints.

### Task 5A — Bitemporal evidence and deterministic conflict handling

**Depends on:** Tasks 2–5. **Gates:** G18.

**Create:** `src/hippo/knowledge/{temporal,conflicts}.py`, `tests/unit/test_temporal_evidence.py`, `tests/unit/test_temporal_conflicts.py`, `tests/fixtures/rag_all/temporal_events.jsonl`.

**Modify:** `knowledge/{model,snapshots,access,lifecycle}.py`, `store/{knowledge,generations,ladybug}.py`, store fakes and fixture loader.

**Steps:**

1. Implement section 5.5 selectors, UTC/precision handling, explicit unknown/open-ended states and interval overlap/throughout validation.
2. Add recorded-time version closure and append-only corrected interpretations in the publication transaction. Reject malformed/negative intervals and scope mismatches.
3. Implement parameterized effective/recorded eligibility and snapshot history selection. Current policy/suppression remains independent of historical time.
4. Add deterministic same-source replacement using adapter ordering; retain independent conflicting sources and cardinality-aware alternatives in `ConflictSet`.
5. Build the May ownership example, backdated correction, imported-old-last, unknown-date, environment collision and purged-history fixtures.
6. Expose original/effective/observed/published times in evidence serialization; no date resolution from model memory. Keep optional model conflict suggestions read-only.

**Check:** `.venv/bin/python -m pytest tests/unit/test_temporal_evidence.py tests/unit/test_temporal_conflicts.py -q`, including Ladybug reopen and fixed historical knowledge-cutoff assertions.

### Task 6 — Structured document blocks and local import adapter

**Depends on:** Tasks 5, 5A. **Gates:** G6.

**Create:** `src/hippo/knowledge/{extract,documents}.py`, `src/hippo/connectors/{__init__,base,local}.py`, `tests/unit/test_document_evidence.py`.

**Modify:** `src/hippo/ingest/{readers,chunker,pipeline}.py`, `hipporag/indexer.py`.

**Steps:**

1. Add block/locator metadata without breaking existing `Document` callers; use defaults or a compatibility adapter.
2. Implement heading/list/table/code-fence-preserving extraction and parent-child chunking, retaining PDF pages and DOCX paragraph/table coordinates. Store `Section` membership/breadcrumbs for hierarchy retrieval; repeated titles retain distinct revision/locator identities.
3. Keep original evidence separate from rendered embedding prefixes. Verify span text hashes against the original revision.
4. Route PRD criteria/IDs into observations and keep inferred criteria separate. Preserve parser/OpenIE failures as coverage metadata.
5. Adapt local file/ZIP/repo input to managed artifacts and policies. Keep an explicit legacy option during migration.

**Check:** `.venv/bin/python -m pytest tests/unit/test_document_evidence.py tests/unit/test_ingest_readers.py tests/unit/test_ingest_chunker.py -q`.

### Task 7 — Qualified schemas, constraints and migration semantics

**Depends on:** Tasks 5–6. **Gates:** G7.

**Create:** `src/hippo/schema/{__init__,model,identifiers,parse,render,migrations}.py`, `tests/unit/test_schema_parse.py`, `tests/unit/test_schema_migrations.py`.

**Modify:** `src/hippo/codegraph/{data_access,resolve}.py`, `knowledge/extract.py`.

**Steps:**

1. Write PostgreSQL and SQL Server fixtures for quoting, qualification, semicolons inside strings, dollar quotes, `GO`, composite PK/FK, checks, defaults, comments and views.
2. Parse explicit dialects and produce exact observations/constraint member order with source spans. Preserve unsupported constructs with warnings.
3. Render deterministic table/column/constraint cards; no OpenIE calls occur for DDL.
4. Implement bounded supported migration operations against a known starting schema and explicit order; unknown schema-changing operations mark completeness false.
5. Distinguish declaration from usage evidence. Add code-to-schema unresolved references without cross-database name guessing.

**Check:** `.venv/bin/python -m pytest tests/unit/test_schema_parse.py tests/unit/test_schema_migrations.py tests/unit/test_codegraph.py -q`.

### Task 8 — Service manifests, Backstage and OpenAPI imports

**Depends on:** Tasks 6–7. **Gates:** G8.

**Create:** `src/hippo/catalog/{__init__,manifest,backstage,openapi}.py`, `schemas/hippo-service.schema.json`, `tests/unit/test_catalog_parse.py`, `tests/unit/test_openapi_parse.py`.

**Modify:** `knowledge/extract.py`, `pyproject.toml`.

**Steps:**

1. Add YAML parsing as a runtime dependency, not only the current dev dependency; select/test a schema validator and pin compatible dependency ranges.
2. Validate the proposed service manifest; map catalog refs and explicit repository/database bindings.
3. Parse Backstage descriptors and recorded catalog entity responses; normalize relation directions and preserve instance-specific metadata.
4. Parse OpenAPI operations and bounded schema refs with exact JSON Pointer evidence. Keep endpoint operation and implementation bindings distinct.
5. Test reference cycles, unknown kinds, malicious remote refs, duplicate identities and conflicting descriptor/catalog observations.

**Check:** `.venv/bin/python -m pytest tests/unit/test_catalog_parse.py tests/unit/test_openapi_parse.py -q`.

### Task 9 — Connector runtime and durable polling

**Depends on:** Tasks 4–6. **Gates:** G9.

**Create:** `src/hippo/connectors/{http,registry,sync,credentials}.py`, `tests/unit/test_connector_sync.py`, `tests/unit/test_connector_http.py`.

**Modify:** `src/hippo/config.py`, `context.py`, `jobs.py`, stores/fakes.

**Steps:**

1. Implement the typed connector interface and capability flags for changes, deletion feeds, ACLs, history and attachments.
2. Validate configured origins/partitions and resolve credential references at runtime. Add CA/proxy configuration with sanitized errors.
3. Implement bounded HTTP retry, pagination, response validation, durable raw-page checkpoints and per-source sync leases.
4. Implement complete-inventory reconciliation; test that partial/failed inventory never creates deletions.
5. Keep fetch cursor, publication cursor and policy verification state distinct. Resume after failures without losing changes.

**Check:** `.venv/bin/python -m pytest tests/unit/test_connector_sync.py tests/unit/test_connector_http.py -q`.

### Task 9A — Autonomous maintenance, dependency invalidation and purge

**Depends on:** Tasks 3–6, 5A, 9. **Gates:** G19.

**Create:** `src/hippo/knowledge/{maintenance,dependencies,outbox,purge}.py`, `tests/unit/test_maintenance_worker.py`, `tests/unit/test_dependency_invalidation.py`, `tests/unit/test_evidence_purge.py`, `scripts/rag_repair.py`.

**Modify:** `jobs.py`, `context.py`, `web/app.py` lifespan, `connectors/sync.py`, `knowledge/lifecycle.py`, stores/fakes, retention/config validation.

**Steps:**

1. Implement the state machine, leases/fencing, heartbeat, retry/quarantine and durable inbox/outbox consumers from section 7.5. Keep thread tracking as execution telemetry only.
2. Add overlapping polling, scheduled complete reconciliation and policy expiry with an injected clock. Implement tombstone/version barriers and stable-scope scan checks from section 7.6.
3. Record exact reverse dependencies and membership fingerprints. Suppress stale derivatives synchronously; process invalidation in bounded idempotent batches, rebuild by input fingerprint and reject stale completion.
4. Implement support-group retraction, immediate suppressions, distinct disconnect/freeze behavior, retention GC and the complete `PurgeJob` removal manifest. Restore applies the purge ledger before traffic.
5. Add read-only diagnostics and scoped repair scheduling. Automatic repair may rebuild from originals; missing originals or ambiguous conflicts remain explicit.
6. Inject failures before/after every durable boundary, lease takeover, concurrent publication, deletion during model work, outbox replay and collection races. Verify actual Ladybug reopen and independent-support survival.
7. Compare staged delta output to a clean scoped rebuild. Keep whole-repository resolution until a narrower optimization proves equivalent; autonomous maintenance does not depend on optimizing every rebuild.

**Check:** `.venv/bin/python -m pytest tests/unit/test_maintenance_worker.py tests/unit/test_dependency_invalidation.py tests/unit/test_evidence_purge.py -q` on both real backends. The repair script accepts `--fixture`/`--dry-run` and operates on a temporary fixture by default.

### Task 10 — GitHub and GitLab review connectors

**Depends on:** Tasks 9, 9A. **Gates:** G10.

**Create:** `src/hippo/connectors/{github,gitlab}.py`, `tests/unit/test_connector_github.py`, `tests/unit/test_connector_gitlab.py`.

**Modify:** `connectors/registry.py`, `knowledge/extract.py`.

**Steps:**

1. Implement PR/MR discovery and detail fetch with ordinary comments, reviews/discussions, versions and changed-file metadata.
2. Normalize every child resource as a versioned artifact with appropriate inherited or restricted policy.
3. Preserve old/new diff sides, file renames, merge state and immutable commit links. Record truncated/binary diffs explicitly.
4. Reconcile edited/deleted comments and permission changes without relying only on parent timestamps.
5. Pin a provider API version where supported and capture deployment capabilities. Record fixtures for cloud and intended enterprise/self-hosted versions.

**Check:** `.venv/bin/python -m pytest tests/unit/test_connector_github.py tests/unit/test_connector_gitlab.py -q`.

### Task 11 — Jira, Tuleap and live Backstage connectors

**Depends on:** Tasks 8–9, 9A. **Gates:** G11.

**Create:** `src/hippo/connectors/{jira,tuleap,backstage}.py`, `tests/unit/test_connector_jira.py`, `tests/unit/test_connector_tuleap.py`, `tests/unit/test_connector_backstage.py`.

**Modify:** `connectors/registry.py`, provider fixture files.

**Steps:**

1. Implement Jira field mapping/ADF, documented search pagination, comments and state transitions. Make Cloud/Data Center profile explicit.
2. Implement Tuleap tracker-field discovery, artifact details, typed links and changesets according to the target instance schema.
3. Implement Backstage catalog entity pagination and processed relations; retain descriptors as separate observations.
4. Exercise child ACL changes, unknown permissions, renamed ticket keys, missing fields, tracker-specific status IDs and catalog name reuse.
5. Add read-only optional live integration checks for one non-production project/catalog per provider; tests skip with a stated reason when credentials are absent, and release records must distinguish skipped from passed.

**Check:** `.venv/bin/python -m pytest tests/unit/test_connector_jira.py tests/unit/test_connector_tuleap.py tests/unit/test_connector_backstage.py -q`.

### Task 12 — Cross-source linking and code/schema/API bindings

**Depends on:** Tasks 5A, 7–8, 9A for local/recorded artifacts and lifecycle-safe linking; integrate live provider enrichment after Tasks 10–11. **Gates:** G12.

**Create:** `src/hippo/knowledge/{linking,bindings}.py`, `src/hippo/codegraph/endpoints.py`, `tests/unit/test_cross_source_links.py`, `tests/unit/test_endpoint_bindings.py`.

**Modify:** `codegraph/{extract,data_access}.py`, `knowledge/lifecycle.py`.

**Steps:**

1. Resolve explicit URLs/provider IDs/catalog refs into stable objects; store unresolved reference candidates rather than guessing.
2. Bind code data uses to configured database/schema identities; support explicit SQL column reads/writes with aliases.
3. Add supported FastAPI endpoint extraction and explicit manifest bindings; preserve unresolved dynamic registrations.
4. Resolve review hunks at base/head revisions and connect requirements/tickets/reviews/code with typed, supported assertions.
5. Add a reviewed alias/mapping record that survives generation changes. Derived links retire when support revisions disappear.
6. Test same-name collisions, source deletion, conflicting claims, no-code-match, hidden support, and explicit rename lineage.
7. Publish immutable `LinkGeneration`s with exact input fingerprints and pin them in query snapshots. A source update excludes incompatible links immediately; delayed relinking cannot alter a saved link generation.

**Check:** `.venv/bin/python -m pytest tests/unit/test_cross_source_links.py tests/unit/test_endpoint_bindings.py -q`.

### Task 13 — Exact/lexical/dense fusion and typed retrieval

**Depends on:** Tasks 5–8, 5A, 12. **Gates:** G13.

**Create:** `src/hippo/retrieval/{__init__,model,exact,lexical,dense,fusion,legacy,graph,schema,hierarchy,temporal,coordinator}.py`, `tests/unit/test_hybrid_retrieval.py`, `tests/unit/test_schema_retrieval.py`, `tests/unit/test_hierarchy_retrieval.py`, `tests/unit/test_temporal_retrieval.py`.

**Modify:** `context.py`, `ask.py`, `hipporag/graph_index.py`, `store/base.py` settings validation.

**Steps:**

1. Build exact and lexical indexes from all authorized evidence, including evidence without vectors. Test punctuation-heavy identifiers and camel/snake components.
2. Adapt dense and existing HippoRAG candidates into a common evidence-ID contract; preserve the legacy route unchanged.
   Build the authorized snapshot projection before any legacy channel work, and disable its code selection callback inside hybrid mode.
3. Implement deterministic RRF, tie-breaking by stable evidence ID, per-channel deduplication and exact-hit reservation.
4. Implement relation-filtered directed expansion and schema join-path closure with complete composite constraints and bounded search.
5. Add deterministic mode routing and soft hints. Explicit filters intersect with ACLs; guessed routing cannot become a hard exclusion.
6. Extend retrieval-only eval modes and compare against Task 1. Store stage counts and limits in a versioned trace.
7. Add heading/breadcrumb search with bounded original-child expansion and metadata-type schema views. Preserve disconnected dense/exact candidates.
8. Apply temporal eligibility before every channel, including historical index/projection selection; implement optional bounded recency separately. Test historical evidence missing from unfiltered top-k and mutually incompatible path intervals.
9. Register the new mandatory provider capabilities and rebuild selected source/history manifests before enabling hybrid mode. Older generations remain usable only through the capabilities they actually provide.

**Check:** `.venv/bin/python -m pytest tests/unit/test_hybrid_retrieval.py tests/unit/test_schema_retrieval.py tests/unit/test_hierarchy_retrieval.py tests/unit/test_temporal_retrieval.py tests/unit/test_retriever.py tests/unit/test_graph_index.py -q`.

### Task 14 — Evidence packing, citations, and bounded follow-up

**Depends on:** Task 13. **Gates:** G14.

**Create:** `src/hippo/retrieval/{rerank,evidence,citations,followup,overview,planner,tools}.py`, `tests/unit/test_evidence_packer.py`, `tests/unit/test_rag_citations.py`, `tests/unit/test_rag_followup.py`.

**Modify:** `src/hippo/ask.py`, `hipporag/answerer.py`, `prompts.py`, `ollama.py` only where profile/token counting support is required.

**Steps:**

1. Implement deterministic packing before optional reranking; test full join bundles, parent expansion, duplicate spans and token exhaustion.
2. Add optional candidate-ID reranking with a no-model fallback and recorded latency. Unknown candidate IDs never enter evidence.
3. Generate citation-bearing answers and validate source IDs/locators/current ACLs. Preserve legacy response fields through an adapter.
4. Implement the provider/controller contract, evidence-needs ledger, concurrent independent coverage searches and one bounded follow-up round. Test aggregate counters, repeated subqueries, no progress, deadlines and errors.
5. Implement scoped inventory for exact overview lists/counts and grouped synthesis with contributor-aware cache invalidation.
6. Test contradictory versions, unsupported deployment claims, empty memory and questions requiring actual database rows.
7. Implement complete-set typed tools with stable snapshot pagination; test inventory completeness independently of top-k retrieval. Resolve temporal premises only from supplied evidence.

**Check:** `.venv/bin/python -m pytest tests/unit/test_evidence_packer.py tests/unit/test_rag_citations.py tests/unit/test_rag_followup.py tests/unit/test_ask.py -q`.

### Task 15 — Product surfaces and connector operations

**Depends on:** Tasks 9A, 14; expose each live adapter as it passes Tasks 10–11. **Gates:** G15.

**Create:** `src/hippo/web/routes/{knowledge,connectors}.py`, `src/hippo/web/templates/connectors.html`, `tests/unit/test_rag_surfaces.py`.

**Modify:** `web/app.py`, `web/templates/{ask,source,analyze}.html`, relevant partials, `web/static/app.js`, `cli.py`, `remote.py`, `mcp_server.py`, `docs/{CONTRACTS,MCP,FIDELITY}.md`.

**Implement proposed contracts:**

- `POST /api/knowledge/search` and `/api/knowledge/ask`: explicit mode/filter/snapshot request; versioned evidence response.
- `GET /api/knowledge/evidence/{id}`: authorized source span and citation metadata.
- `GET /api/knowledge/objects/{id}`: authorized observations and supported relations.
- `POST /api/connectors` and `POST /api/connectors/{id}/sync`: local configuration/job actions, requiring source-management capability; they do not modify provider content.
- `GET /api/connectors/{id}/status`: coverage, last fetch/publication and sanitized error state.
- CLI `hippo search`, `hippo sync`, `hippo connector list`, and `hippo ask --mode ...`; update server-forwarding behavior in `remote.py`.
- MCP tools `search_knowledge`, `get_evidence`, `trace_requirement`, `schema_context`, `service_dependencies`; each calls the same service used by HTTP. Keep existing tool names/contracts available.

Show original evidence, source version, declared/observed/inferred status and coverage in the UI. Surface ambiguous object choices and incomplete context. Do not expose extraction internals as mandatory user workflow steps.

**Check:** `.venv/bin/python -m pytest tests/unit/test_rag_surfaces.py tests/unit/test_mcp_server.py tests/unit/test_mcp_http.py tests/unit/test_cli.py -q`.

### Task 16 — Update/delete recovery, performance and release evaluation

**Depends on:** Tasks 0–15, including 5A and 9A. **Gates:** G16, G17.

**Create:** `scripts/rag_benchmark.py`, `scripts/rag_restore_check.py`, `tests/unit/test_rag_lifecycle_e2e.py`, optional credential-gated tests under `tests/integration/`.

**Modify:** `.github/workflows/ci.yml`, `src/hippo/evals/rag_all.py`, `README.md`, `.env.example`.

**Steps:**

1. Complete the 120-question reviewed set and freeze held-out labels. Run all baselines and per-slice comparisons with identical budgets.
2. Run the full temporal/event/fault replay matrix from section 12.3, including crash recovery, reindex, delete, rename, schema drift, ACL changes during generation, late events, retroactive corrections and restore under the purge ledger.
3. Benchmark 10k/100k/1m generated evidence sizes and write JSON reports with hardware/profile/version information. Record failures instead of quietly lowering the corpus.
4. Run real backend contract matrices and live-model quality checks separately from deterministic tests.
5. Run read-only non-production provider checks; confirm exact API/field/policy behavior for each intended deployment. Document unavailable integrations as unreleased, not passed.
6. Record the release configuration, remaining unsupported constructs, rollback path and operational dashboards. Promote sources gradually as described in section 15.

**Check:** G16/G17 commands below. Do not enable all connectors simply because the UI can list them.
