# CDK slice S6: an incidents exemplar connector, and the probe and validate surfaces

**Status:** proposed implementation contract for root review. Nothing here is implemented. Written
at HEAD `f7b14ee`, which carries the design amendments of `d1b7bb2` and `f7b14ee`. Design of record:
`docs/spec/connector-developer-kit.md` ("design"). Specification: `docs/spec/enterprise-graph-rag-v1.md`
("spec"). Gate: CK6 of `ai_docs/gates/rag-it-all/cdk/GATES.md`. Form follows
`ai_docs/plans/rag-it-all-task-5-managed-code-capture.md`.

## 1. Goal and scope

**Goal.** Prove the kit with a connector the repository has never had, written only against the
public kit and started from `hippo connector new`:

- it registers a new object kind with fact templates and a new windowed predicate;
- `hippo connector validate` passes on it;
- it syncs a fixture into a scratch workspace;
- a question through the existing query path returns its rendered facts, with citations that
  resolve to its record spans.

Operators see the probe and validate results through the smallest set of Task 15 connector routes
and one MCP tool.

**In scope.**

- `src/hippo/connectors/examples/incidents_ndjson/`: the connector, its types, its templates and its
  fixtures.
- `src/hippo/web/routes/connectors.py`, with its inclusion in `web/app.py`.
- One MCP tool in `mcp_server.py`.
- Tool-count text in `docs/MCP.md` and `README.md`, and short entries in `docs/CONTRACTS.md`.
- `tests/unit/test_connector_exemplar.py` and `tests/unit/test_connector_surfaces.py`.

**Out of scope.** Everything Task 15 keeps (§6.3), retrieval changes (design §14), the linker, and
the other spec §5 connectors.

**Sizing (decision 12).** One worker. The exemplar is smaller than the scaffold it starts from plus
one parser, and the surfaces are four thin routes and one tool over shared payload builders, the
pattern `web/routes/code.py` already uses for the MCP code tools.

## 2. Existing seams

| Seam | Use or required boundary |
| --- | --- |
| `src/hippo/knowledge/model.py:56-87` `ObjectKind`; `src/hippo/knowledge/predicates.py:66-105` `PREDICATES` | Neither has an incident kind or an `AFFECTS` predicate. The work family is partly present: `ticket` (`model.py`), `TRACKS` and `BLOCKS` (`predicates.py:87-88`). |
| `model.py:289-312` `Artifact.kind` | `file`, `repository`, `ticket`, `comment`, `attachment`, `review`, `schema_snapshot`, `catalog_entity`, `document`, `manifest`, `openapi`, `history_event`. None fits one incident record, so the exemplar registers an artifact kind. |
| `model.py:414` `EvidenceSpan.locator_kind` | `file_lines` is built in. One NDJSON line is one line, so no locator kind is registered. |
| `src/hippo/knowledge/identity.py:187` `service_identity` | The built-in `service` key the `AFFECTS` object uses, through S2's builder. |
| `src/hippo/knowledge/input_binding.py:294-346` `_view` | Rendered text reaches retrieval as a `RetrievalView` + `DerivedRecord` + `DerivedDependency` over original spans. |
| `src/hippo/knowledge/projection.py:184-252` | Projection serves a rendered passage with `RetrievalEvidence(passage_id, generation_id, retrieval_view_id, original_span_ids)`. |
| `src/hippo/knowledge/citations.py:97-146` `resolve_citations` | Refuses a managed passage with no original lineage (`:112-113`) or no originals (`:123-124`), and checks each original's `span_id`, `source_id` and `text_hash` (`:127-133`). |
| `src/hippo/ask.py:39-52` `search`; `src/hippo/knowledge/query_access.py:126-164` `query_session` | The existing query path. A caller holding a session passes `session=`, and the citations resolve on that same graph (`tests/unit/test_managed_route_activation.py:363`). |
| `tests/unit/test_prose_generation.py:102-113` | A reader that can prove managed evidence: a user, a `WorkspaceMembership`, and `reviewed_mapping_authorities`. |
| `src/hippo/web/app.py:86-99` include order; `:100-102` `_mount_mcp` | Every router is included before the MCP catch-all. |
| `src/hippo/web/auth.py:210-219` `require` | Answers 403 with the missing capability named. |
| `src/hippo/access.py:45` `manage_sources` | Gates every connector surface. |
| `src/hippo/web/render.py:117` `coded_response`, `:129` `public_failure_response` | Coded JSON errors. |
| `src/hippo/web/routes/code.py:60` `api`; `src/hippo/mcp_server.py:90-97` | Payload builders live in the route module, and the MCP server imports them, so the HTTP and MCP shapes cannot drift. |
| `mcp_server.py:179-197` `tool_failure`; `:229-331` `build_server` | Tool registration and public failure rendering. The docstrings say "nine" at `:6` and `:230`. |
| `tests/unit/test_mcp_server.py:20-30` `TOOL_NAMES`, asserted at `:74` and `:279`; `:54-66` `call`, `structured` | This file imports `fastapi.testclient` at module level (`:10`), so S6's tests copy the two helpers instead of importing them. |
| `docs/MCP.md:116`, `:134`, `:138`; `README.md:294`, `:405` | The "nine tools" text. |
| `tests/unit/test_cli.py:310` | The per-test marker form (a) for a function-level `TestClient` import. |

## 3. The exemplar (decision 9)

### 3.1 Choice: an incidents NDJSON export

Four reasons:

- **Uncovered family.** The incident family has nothing in the repository: no kind, no predicate, no
  artifact kind (`model.py:56-87`, `predicates.py:66-105`). The work family is already partly present
  through `ticket`, `TRACKS` and `BLOCKS`, so incidents are the cleaner test of "a family the
  repository does not cover".
- **Flat format.** NDJSON is what PagerDuty, incident.io and FireHydrant exports and webhooks are.
  One object per line gives a one-line `file_lines` span with no flattening convention for nested
  fields, which a CSV would need.
- **A windowed predicate straight from the spec.** Spec §5.7 names `AFFECTS` "to Service (dated)":
  windowed by the incident's own start and resolution times, owned by the incident family.
- **Its own ACL.** Spec §5.7 says incidents are organization-visible "unless the tool scopes them",
  so the record's visibility field is the ACL.

### 3.2 Export format (the fixture)

One JSON object per line:

```json
{"id": "P7Q2X1", "number": 2210, "title": "Settlement batch stalled", "severity": "SEV2", "status": "resolved", "service": "settlement-batch-processor", "started_at": "2026-09-14T03:12:00Z", "detected_at": "2026-09-14T03:17:00Z", "mitigated_at": "2026-09-14T03:43:00Z", "resolved_at": "2026-09-14T03:59:00Z", "updated_at": "2026-09-14T04:10:00Z", "visibility": {"mode": "workspace"}}
```

`visibility` is `{"mode": "workspace"}`, or `{"mode": "restricted", "allow_users": [...],
"allow_groups": [...]}`. Anything else, or a missing field, is unknown, which is deny.

### 3.3 Package

The package is created by the scaffold and then edited:

```bash
hippo connector new incidents_ndjson --family incident --kinds incident --dest src/hippo/connectors/examples
```

The unedited scaffold output is committed first, as its own commit, so the review shows the diff from
scaffold to exemplar.

`types.py`:

```python
class IncidentAttributes(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    number: int
    title: str
    severity: str
    status: str
    service: str
    started_at: str
    resolved_at: str | None = None
    mttd_minutes: int | None = None
    mttm_minutes: int | None = None
    mttr_minutes: int | None = None


EXTENSION = TypeExtension(
    object_kinds=(
        ObjectKindDefinition(
            name="incident",
            family="incident",
            key_template=("tool_instance", "incident_id"),
            key_prefix="inc",
            attrs_model=IncidentAttributes,
            label_template="INC-{number}",
            fact_templates=(INCIDENT_SUMMARY, INCIDENT_RESOLUTION),
        ),
    ),
    artifact_kinds=("incident_record",),
    predicates=(
        PredicateDefinition(
            name="AFFECTS",
            subject_kinds=frozenset({"incident"}),
            object_kinds=frozenset({"service"}),
            owner_families=frozenset({"incident"}),
            canonical_direction="subject_to_object",
            family_default="deterministic",
            sources_allowed=frozenset({"metadata"}),
            verb_phrase="affected",
            windowed=True,
        ),
    ),
)
```

`templates.py` (the `FactTemplate` field names follow S1, R-S1-2):

```python
INCIDENT_SUMMARY = FactTemplate(
    name="incident_summary",
    version="1",
    text="INC-{number} ({severity}) {title}: {status}; affected {service} from {started_at}",
)
INCIDENT_RESOLUTION = FactTemplate(
    name="incident_resolution",
    version="1",
    text="INC-{number} was detected in {mttd_minutes} minutes, mitigated in {mttm_minutes} and resolved in {mttr_minutes}, at {resolved_at}",
)
```

`connector.py`:

```python
class IncidentsExportConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    export_path: str
    tool_instance: str


class IncidentsConnector:
    descriptor = ConnectorDescriptor(
        name="incidents_ndjson",
        version="1",
        families=("incident",),
        kinds=("incident", "service"),
        predicates=("AFFECTS",),
        artifact_kinds=("incident_record",),
        locator_kinds=("file_lines",),
        capabilities=ConnectorCapabilities(acls=True),
        config_model=IncidentsExportConfig,
        credentials=(),
        parsers=(ParserVersion("json@1"),),
    )

    def probe(self, config: IncidentsExportConfig, clock: Clock) -> Classification: ...
    def list_changes(self, config: IncidentsExportConfig, cursor: SyncCursor | None) -> ChangePage: ...
    def fetch(self, config: IncidentsExportConfig, ref: ExternalRef) -> RawFetch: ...
    def fetch_policy(self, config: IncidentsExportConfig, ref: ExternalRef) -> PolicyObservation: ...
    def emit(self, revision: RevisionInput, mapping: TypeMapping) -> EmissionBatch: ...
```

**Behaviour.** `ts` always comes from the data. The clock passed to `probe` is used for nothing but
the design's signature, and `emit` never reads a clock.

- **`list_changes`** reads the export file read-only. Each non-empty line is one `upsert` change:
  the external id is the record's `id` (or `line-sha256:<hash>` for a line that is not a JSON object,
  so `emit` can count it), and `provider_revision` is `updated_at`. The page carries completed scan
  true and the cursor `sha256` of the file bytes, so a replayed export is a no-op (design §7 step 4).
  An id missing from a complete scan is the runtime's deletion to infer (design §7 step 9).
- **`fetch`** returns a `RawFetch` with:
  - `bytes`: the exact line, without its newline;
  - `provider_revision`: `updated_at`;
  - `source_updated_at`: `updated_at` parsed, keeping its original string, its timezone and second
    precision;
  - `canonical_uri`: `f"{tool_instance}/incidents/{id}"`;
  - `external_id`: `id`;
  - `content_type`: `application/x-ndjson`.
- **`fetch_policy`** maps `visibility` as §3.2 states. Unknown is the design's deny.
- **`probe`** returns one partition, the export file, with family `incident` and mapping
  `{"incident": "incident", "service": "service"}`. Its sample count is the line count, and an
  unparseable line is a warning.
- **`emit`** is pure. It runs `json.loads` on the revision bytes. A decode error or a missing required
  field (`id`, `number`, `title`, `severity`, `status`, `service`, `started_at`) becomes
  `ParseFailure(family="incident", parser="json@1", reason=...)`. Otherwise it returns:
  - a node of kind `incident` with key parts `(tool_instance, id)`, attributes with the minutes
    computed from the record's own timestamps (`None` when a timestamp is missing), `ts=started_at`,
    and locator `file_lines` 1–1;
  - a node of kind `service` keyed by S2's built-in `service` builder from `(tool_instance, service)`,
    with the same locator;
  - one `AFFECTS` edge with `family="deterministic"`, `source="metadata"`, `valid_from=started_at`,
    `valid_to=resolved_at` (open when unresolved), and the same locator.

  The kit renders the edge statement and both fact templates (design §6). `emit` writes no statement
  text and no rendered unit itself. A template whose attribute is `None` is not invoked (R-S2-5), so
  an unresolved incident has a summary fact and no resolution fact. It never gets "resolved in None
  minutes". This is spec §5.7's "does not compute an MTTR when the tool has no resolved time".

**Fixtures.**

- `fixtures/basic/` holds four lines:
  - INC-2210, resolved, workspace visibility;
  - INC-2211, restricted to one user;
  - INC-2212, open, with no `resolved_at`;
  - one malformed line.
- `fixtures/update/` has two pages: INC-2212 gains `resolved_at` and a new `updated_at`, and INC-2211
  is absent from the second, complete page.
- `fixtures/export/incidents.ndjson` is a real file for the non-replay `list_changes` tests and for
  the probe route.

**Imports.** The package may import only:

- the standard library;
- `pydantic`;
- `hippo.connectors`, `hippo.connectors.base`, `hippo.connectors.keys` and `hippo.connectors.render`;
- `hippo.knowledge.model`;
- `hippo.connectors.testing`, inside its own `tests/` directory only.

The registry definitions (`TypeExtension`, `ObjectKindDefinition`, `PredicateDefinition`,
`FactTemplate`) are therefore imported from `hippo.connectors.base`, which must re-export them
(R-S2-1).

**Registration.** `connectors/examples/` is discovered for `list` and `validate` but not registered
into the process registry until enabled (design §9: "A discovered kind is not enabled until an
operator … enables it"). Adding the exemplar to the repository therefore changes no production
generation's `registry_fingerprint` (R-S1-3).

## 4. The retrieval check (decision 10)

**How the facts reach the query path.** The exemplar is synced by S3's runtime into a scratch
workspace: a fresh `AppContext` on a temporary data directory and the test store (the `ctx` fixture,
`tests/conftest.py:257-260`), in its default workspace. The runtime does four things (R-S3-1, R-S3-2):

1. It creates the partition's `Source` row.
2. It binds each rendered fact unit as a managed `Passage` over a `RetrievalView` + `DerivedRecord` +
   `DerivedDependency` whose dependency is the record's `EvidenceSpan` (the `input_binding._view`
   pattern, `:294-346`).
3. It embeds that passage through `ctx.ollama` with S4's `offline_ollama()` hashed vectors, so
   ranking is lexical and deterministic.
4. It publishes through `BuildAuthority`, which sets the Source's `active_generation_id`.

`projection.py:184-252` then serves the passage with `RetrievalEvidence(original_span_ids=(record
span,))`, and the existing `search` reaches it. Units themselves are not read by retrieval: that is
the stack decision in design §14.

**What "citations resolve to its spans" asserts.** Within `query_session(ctx, reader.access)`, the
test runs `trace = search(ctx, "Which incident affected settlement-batch-processor?", session=session)`.
For the passage whose text is INC-2210's summary fact:

1. It is among `trace.passages`.
2. `bundle = resolve_citations(session.graph, (passage_id,))` returns without raising
   (`citations.py:97-146`).
3. `bundle.items[0].is_derived` is true.
4. Every citation's `span_id` is an `EvidenceSpan` that is a `GenerationEvidenceMember` of the
   exemplar's published generation.
5. `citation.text` equals INC-2210's exact line bytes from `fixtures/basic`, decoded.
6. `text_hash(citation.text) == span.text_hash`.
7. `citation.locator_kind == "file_lines"`, and its locator is line 1–1 of that record's revision.

Two more assertions:

- The same question asked by a reader outside INC-2211's allow list never returns INC-2211's fact.
- An incident with unknown visibility is returned to nobody.

## 5. RED tests

### `tests/unit/test_connector_exemplar.py`

- `test_the_exemplar_keeps_the_scaffold_file_set_and_its_generated_test`
- `test_the_exemplar_imports_only_the_public_kit_and_the_knowledge_model`
- `test_the_extension_registers_a_new_kind_with_fact_templates_and_a_windowed_predicate_owned_by_incident`
- `test_validate_passes_the_exemplar_and_reports_its_registry_diff`
- `test_list_changes_reads_one_change_per_line_with_the_updated_at_revision_and_a_file_cursor`
- `test_fetch_returns_the_exact_line_bytes_and_the_provider_timestamp`
- `test_fetch_policy_maps_visibility_and_unknown_is_deny[workspace|restricted|missing|garbage]`
- `test_emit_takes_ts_and_the_affects_window_from_the_record_never_the_clock`
- `test_emit_computes_minutes_from_timestamps_and_an_open_incident_gets_no_resolution_fact`
- `test_a_malformed_line_is_a_counted_parse_failure`
- `test_emit_is_pure_under_the_guard`
- `test_a_fixture_syncs_into_a_scratch_workspace_and_publishes_one_generation`
- `test_search_returns_the_rendered_fact_of_the_incident`
- `test_every_citation_of_the_rendered_fact_resolves_to_the_record_span`
- `test_a_restricted_incident_is_never_returned_to_a_reader_outside_its_allow_list`
- `test_an_incident_with_unknown_visibility_is_returned_to_nobody`
- `test_an_update_page_republishes_and_a_complete_scan_withdraws_the_missing_incident` (needs R-S3-5)

### `tests/unit/test_connector_surfaces.py`

Every test importing `TestClient` does so inside the function, with the per-test marker
`@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")`.

- `test_get_connectors_lists_the_exemplar_with_its_instance_and_classification`
- `test_every_connector_route_requires_manage_sources`
- `test_post_probe_runs_the_stored_instance_config_and_stores_the_classification`
- `test_post_probe_accepts_no_caller_supplied_config`
- `test_get_classification_returns_the_stored_probe_result`
- `test_get_classification_of_an_unknown_instance_is_404_not_found`
- `test_post_validate_returns_the_validation_report_of_the_exemplar`
- `test_post_validate_runs_no_scratch_build_and_reports_scope_contract`
- `test_post_validate_of_an_undiscovered_kind_is_404_not_found`
- `test_the_mcp_tool_lists_connectors`
- `test_the_mcp_tool_returns_a_stored_classification`
- `test_the_mcp_tool_runs_validation`
- `test_the_mcp_tool_refuses_without_manage_sources`
- `test_the_mcp_tool_refuses_two_modes_at_once`
- `test_route_and_tool_payloads_are_the_same_builders`

**Modified existing test:** `tests/unit/test_mcp_server.py:20-30` gains `"hippo_connectors"` in
`TOOL_NAMES`. No assertion changes.

## 6. The surfaces (decision 11)

### 6.1 Routes: `src/hippo/web/routes/connectors.py`

```python
api = APIRouter(prefix="/api/connectors")


def connectors_payload(ctx) -> list[dict[str, Any]]: ...
def classification_payload(ctx, connector_id: str) -> dict[str, Any]: ...
def probe_payload(ctx, connector_id: str) -> dict[str, Any]: ...
def validation_payload(name: str) -> dict[str, Any]: ...


@api.get("")
def list_connectors(request: Request) -> list[dict[str, Any]]: ...


@api.get("/{connector_id}/classification")
def connector_classification(request: Request, connector_id: str) -> dict[str, Any]: ...


@api.post("/{connector_id}/probe")
def probe_connector(request: Request, connector_id: str) -> dict[str, Any]: ...


@api.post("/kinds/{name}/validate")
def validate_connector(request: Request, name: str) -> dict[str, Any]: ...
```

- **Capability.** Every route first calls `require(request, "manage_sources")` (`web/auth.py:210-219`).
- **`GET /api/connectors`** returns the `ConnectorSummary` list that S4 defines for
  `RemoteHippo.connectors()`, character for character (`cdk-s4-kit.md` §3.3).
- **`POST /{connector_id}/probe`** runs `probe` against the instance's **stored**
  `Connector.config_json`, validated by the descriptor's `config_model`, with S3's credential
  resolution. It stores the result through S3 (R-S3-3) and returns the classification as JSON.
  It takes no request body: a caller-supplied config would let an HTTP caller make the server read an
  arbitrary local path, which the exemplar's `export_path` is.
- **`GET /{connector_id}/classification`** returns the stored result, or 404 with `coded_response`
  code `not_found`.
- **`POST /kinds/{name}/validate`** runs `testing.validate_package(name, runtime=False)` on the
  discovered package's own fixtures and returns `ValidationReport.to_json()` with `scope` `contract`
  (S4 §3.1): registration, the registry lock, and `check_contract` plus `assert_emit_pure` over every
  case.
  - It runs no scratch build. A scratch LadybugDB build costs minutes and gigabytes
    (`ai_docs/gates/rag-it-all/task-5-code-capture/evidence-cc11b.md`) and does not belong inside a
    request. The full golden run stays `hippo connector validate`.
  - An undiscovered name is 404 `not_found`.
- **Failures.** Anything else goes through `public_failure_response`.

`web/app.py` includes `connectors.api` after `code.api` (`:99`) and before `_mount_mcp`
(`:100-102`).

### 6.2 MCP tool

```python
@server.tool(
    description=(
        "hippo's connectors: with no argument, the list; with connector_id, that instance's stored "
        "classification (the probe result); with validate, the contract validation of that "
        "installed connector kind. Needs the manage_sources capability."
    )
)
def hippo_connectors(
    connector_id: str | None = None, validate: str | None = None, mcp_ctx: Context | None = None
) -> dict[str, Any]: ...
```

- The tool returns `{"connectors": [...]}`, `{"classification": {...}}` or `{"validation": {...}}`,
  built by the route module's builders, as the code tools do (`mcp_server.py:90-97`). `validation` is
  the same `scope` `contract` report the route returns.
- Passing both arguments raises `ValueError("Choose connector_id or validate, not both")`, which
  `tool_failure` renders (`:195-196`). The missing capability raises `ToolError` with the denied
  wording (`:189-190`).
- The tool never runs `probe`, because an MCP client triggering provider reads is Task 15's call.
- The "nine" text becomes "ten" at `mcp_server.py:6` and `:230`, `docs/MCP.md:116`, `:134` and
  `:138`, and `README.md:294` and `:405`. `docs/MCP.md` gains a `hippo_connectors` section.
  `docs/CONTRACTS.md` gains the four routes under the web section (`:557-719`) and the tool under the
  MCP section (`:720-746`).

### 6.3 What Task 15 keeps for later

`POST /api/connectors` (create or enable an instance, and the third-party allowlist), `POST
/api/connectors/{id}/sync`, `GET /api/connectors/{id}/status` (coverage, last fetch and publication,
sanitized error), `web/templates/connectors.html` and every UI change, the `/api/knowledge/*`
routes, the CLI's `hippo search`, `hippo sync` and `hippo ask --mode`, MCP `probe` execution, the MCP
tools `search_knowledge`, `get_evidence`, `trace_requirement`, `schema_context` and
`service_dependencies`, and `docs/FIDELITY.md`.

## 7. File-by-file steps (worktree `s6`)

1. Run the scaffold command of §3.3 and commit its unedited output.
2. **Create** `tests/unit/test_connector_exemplar.py` and `tests/unit/test_connector_surfaces.py`, and
   **modify** `tests/unit/test_mcp_server.py:20-30`. Save `/tmp/hippo-cdk-s6-red.log`.
3. **Edit** the scaffolded `src/hippo/connectors/examples/incidents_ndjson/{connector,types,templates}.py`
   and its fixtures as in §3, then regenerate the goldens with `hippo connector validate
   src/hippo/connectors/examples/incidents_ndjson --update-golden` and review the printed diff.
4. **Create** `src/hippo/web/routes/connectors.py`, and **modify** `src/hippo/web/app.py:99`.
5. **Modify** `src/hippo/mcp_server.py`: register the tool beside the code tools, import the builders,
   and update the docstrings.
6. **Modify** `docs/MCP.md`, `README.md` and `docs/CONTRACTS.md` (§6.2).
7. Run GREEN (§8), run Ruff, commit.

## 8. GREEN commands and the CK6 CHECK line

```bash
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_exemplar.py tests/unit/test_connector_surfaces.py -q -o addopts='' -W error > /tmp/hippo-cdk-s6-green.log 2>&1; echo EXIT $?
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_mcp_server.py tests/unit/test_mcp_http.py tests/unit/test_cli.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning" > /tmp/hippo-cdk-s6-mcp.log 2>&1; echo EXIT $?
HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_connector_exemplar.py tests/unit/test_connector_surfaces.py -q -o addopts='' -W error > /tmp/hippo-cdk-s6-ladybug.log 2>&1; echo EXIT $?
.venv/bin/ruff check src/hippo/connectors/examples src/hippo/web/routes/connectors.py src/hippo/web/app.py src/hippo/mcp_server.py tests/unit/test_connector_exemplar.py tests/unit/test_connector_surfaces.py tests/unit/test_mcp_server.py && .venv/bin/ruff format --check src/hippo/connectors/examples src/hippo/web/routes/connectors.py src/hippo/web/app.py src/hippo/mcp_server.py tests/unit/test_connector_exemplar.py tests/unit/test_connector_surfaces.py tests/unit/test_mcp_server.py docs/MCP.md docs/CONTRACTS.md README.md
```

The second command uses form (b) of the fleet rules, because `tests/unit/test_mcp_server.py` imports
`fastapi.testclient` at module level (`:10`).

**CK6 CHECK line: confirmed as written.** Neither new file imports a test client at module level. The
LadybugDB line is evidence for the ledger, because the runtime persists the sync. Neo4j parity is
root-owned.

**Ledger lines.** None: the CK6 CHECK line and CRITERIA stand as written.

## 9. Worktree, merge order, do-not-touch

- **Worktree:** `s6`.
- **Merge order:** after S4b (it needs `hippo connector new`, `validate_package`, `offline_ollama` and
  the `ConnectorSummary` contract) and after S5b, keeping design §13's order. S6 shares no file with
  S5, so the orchestrator may run it beside S5 once S4b has merged.
- **Owns:**
  - `src/hippo/connectors/examples/**`;
  - `src/hippo/web/routes/connectors.py`, `src/hippo/web/app.py`, `src/hippo/mcp_server.py`;
  - `tests/unit/test_connector_exemplar.py`, `tests/unit/test_connector_surfaces.py`,
    `tests/unit/test_mcp_server.py` (the `TOOL_NAMES` set only);
  - `docs/MCP.md`, `docs/CONTRACTS.md` (connector entries), `README.md` (tool count).
- **Do not touch:**
  - `src/hippo/cli.py`, `src/hippo/remote.py`, `src/hippo/connectors/testing.py`,
    `connectors/scaffold/**` (S4);
  - `connectors/{base,classify,keys,render,emit}.py` (S2);
  - `connectors/{sync,http,credentials}.py`, `knowledge/staged_records.py` (S3);
  - `connectors/lanes.py`, `connectors/local/**`, `connectors/git/**` and the ingest coordinators (S5);
  - `src/hippo/knowledge/**`, `src/hippo/store/**`, `src/hippo/ingest/**`;
  - `docs/spec/*`, the ledgers, the checkpoint.

## 10. Decisions taken

9. **Exemplar.**
   - An incidents NDJSON export connector, `incidents_ndjson`.
   - It registers the kind `incident` (two fact templates), the artifact kind `incident_record` and
     the windowed predicate `AFFECTS` (incident → service), owned by `incident`.
   - `ts` and the window come from the record's timestamps. The ACL comes from its `visibility`, and
     unknown is deny.
   - It imports only the public kit and `knowledge.model`, and is started from the scaffold.
10. **Retrieval.**
    - Rendered facts reach the existing `search` as managed derived passages over the record span.
    - The check asserts the fact's presence and a derived item whose citations are the exemplar
      generation's record spans, with the exact line text, the matching text hash and a `file_lines`
      locator.
    - It also asserts the ACL and unknown-deny negatives.
11. **Surfaces.**
    - Four routes under `/api/connectors`, all behind `manage_sources`: list, stored classification,
      probe against the stored config only, and validate of a discovered kind.
    - One MCP tool, `hippo_connectors`, read-only apart from validation.
    - Payload builders shared between route and tool.
    - Task 15 keeps the rest (§6.3).
12. **Sizing.** One worker.
13. **Examples are discovered but not registered until enabled**, so the repository's production
    fingerprint does not move when an example is added.

## 11. Requires from S1, S2, S3 and S4

- **R-S1-1.** `incident` is a built-in family (design §1 lists it), and `incident` is **not** a
  built-in object kind. CK1 defines built-ins as today's `Literal` and frozenset members, and
  `model.py:56-87` has no incident.
- **R-S1-2.** `FactTemplate(name, version, text)`, or S1's spelling of those three. The kit rejects a
  template referencing an attribute its kind does not declare (design §3).
- **R-S1-3.** Discovery that lists `hippo.connectors.examples.*` packages without registering them
  into the process registry until an instance is enabled.
- **R-S2-1.** `hippo.connectors.base` re-exports `TypeExtension`, `ObjectKindDefinition`,
  `PredicateDefinition` and `FactTemplate` (S1's `knowledge/registry.py` classes), so a connector
  imports only the public kit and `knowledge.model`.
- **R-S2-2.** `ConnectorDescriptor`, `ConnectorCapabilities` (with `acls`), `ParserVersion`,
  `ChangePage`, `Change`, `ExternalRef`, `RawFetch` (with `source_timestamp_original`, timezone and
  precision), `PolicyObservation` (workspace, restricted with principals, unknown), `EmissionBatch`,
  `NodeEmission`, `EdgeEmission`, `ParseFailure`, `RevisionInput`, `TypeMapping`, `Classification`,
  `SyncCursor` and `Clock`.
- **R-S2-3.** The built-in `service` key builder in `connectors/keys.py`.
- **R-S2-4.** The `file_lines` locator as an emission locator value.
- **R-S2-5.** Fact template rendering skips a template with a `None` consumed attribute, emitting no
  unit and no error. Otherwise an open incident's resolution fact cannot be omitted honestly.
- **R-S2-6.** A connector may emit a node of a kind whose family it does not declare when that node
  is an endpoint of an edge the connector owns: an observation, not ownership. The exemplar's
  `service` node is the object of `AFFECTS`. If S2's binder refuses foreign-family nodes, `AFFECTS`
  has no object and the exemplar cannot pass `validate`.
- **R-S3-1.** A sync of one connector partition that:
  - creates the partition's `Source` row;
  - is admitted by `build_authority._source_control` for that source kind;
  - publishes through `BuildAuthority`;
  - embeds passages through `ctx.ollama`.
- **R-S3-2.** Rendered fact units become managed `Passage` rows bound to a `RetrievalView`,
  `DerivedRecord` and `DerivedDependency` over the node's span, the `input_binding._view` pattern.
  Without this, CK6's retrieval clause is unreachable through the existing query path.
- **R-S3-3.** Storing and reading a probe classification on the instance (design §2
  `classification_json`).
- **R-S3-4.** Instance creation with a stored `config_json` for a test or operator, and credential
  resolution for `probe`.
- **R-S3-5.** Deletion inferred only from a completed inventory (design §7 step 9): an incident
  missing from a complete scan is withdrawn, and one missing from an incomplete page is not.
- **R-S4-1.** `hippo connector new ... --dest`, `testing.validate_package` with `runtime=False`,
  `ValidationReport.to_json()`, `testing.offline_ollama()`, `testing.assert_emit_pure`, and the
  `ConnectorSummary` JSON of `cdk-s4-kit.md` §3.3.

## 12. Design deviations

None in the design's contract. Two narrowings:

1. Design §9 does not say whether probe runs on a caller-supplied config over HTTP. S6's probe route
   runs only on the stored instance config, for the reason given in §6.1.
2. The validate route and the MCP tool return the `scope` `contract` report
   (`validate_package(name, runtime=False)`), not the scratch-store golden run. The reason is the
   LadybugDB cost given in §6.1. `hippo connector validate` keeps the full run.

## 13. Open questions

1. **Kind collision.** Design §5 lists `inc` among "the built-in kinds' prefixes". If S1 registers a
   built-in `incident` kind from that list, the exemplar's registration is refused as a shadow, and
   the exemplar must rename its kind (for example `incident_record`) and its prefix. Recommendation:
   §5's list names key prefixes for kinds when their connectors register them, not built-ins; S1
   confirms.
2. **`Connector.classification_json`** (design §2) is in no slice's file list at this HEAD. S1b adds
   the column and S3 writes it (R-S3-3). Without it, the probe route cannot store results and the
   classification route has nothing to return.
3. **The tool name `hippo_connectors`** follows the `hippo_` prefix of the nine existing tools, not
   Task 15's unprefixed `search_knowledge` style. The orchestrator may prefer a different
   convention.
