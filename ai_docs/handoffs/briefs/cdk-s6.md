# Brief: CDK S6 — the incidents exemplar connector and the probe and validate surfaces

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `s6` (branch
`wp/s6`, base = the `rag-it-all-tibs` HEAD named in the spawn message, after S4b and S5b merged).
You implement `ai_docs/plans/cdk-s6-exemplar.md` sections 3–7 exactly as written, amended by the
rulings and review findings below.

GOAL: `src/hippo/connectors/examples/incidents_ndjson/` written only with the public kit (scaffolded
by `hippo connector new`, then edited): at least one new object kind with a fact template and one
new windowed predicate with owner families, `ts` from the data, an ACL from the data through the
principal map, `hippo connector validate` passing, a fixture syncing into a scratch workspace, a
query through the existing query path returning its rendered facts with citations that resolve to
its spans; the connector routes (`src/hippo/web/routes/connectors.py`) and the `hippo_connectors`
MCP tool exposing probe and validate results; the CK6 CHECK line green.

CONTEXT: design `docs/spec/connector-developer-kit.md` sections 8, 9, 10; the plan whole; the
landed code and evidence of every earlier slice, especially S4a (`validate_package(name,
runtime=False)`), S4b (`hippo connector new`, `enable`), S4c (`LoadResult`, `error="frozen"`), S3c
(`sync_connector`, the fixture connector) and S2b (`evidence_class(registry, ...)`). Rulings and
findings that bind S6 (`ai_docs/plans/cdk-rulings.md`, both review reports): R6 (rendered facts get
a `Unit` and a derived `Passage`), R8 (the probe route runs on the stored instance config; the
validate route and the tool return the contract-scope report), R13 (the kind stays `incident`),
R14 (tool name `hippo_connectors`), R49 / B3 (the validate surfaces run under S3a's per-thread
guard; add `test_post_validate_does_not_disturb_a_concurrent_request`), R53 / M6 (the config
carries `catalog_instance`; the `service` endpoint is an identity-only foreign node keyed by it),
R60 (the import allowlist admits `hippo.connectors.classify` and `hippo.connectors.http` for
`ProviderNotFoundError`), M15 (`ConnectorCapabilities(acls=True, inventory=True)`; `fetch` raises
`ProviderNotFoundError` for an id absent from the export), R61 (`principal_map` in the config),
R64 (`GET /api/connectors` keys entries on `(origin, name)` and renders `LoadResult.error` and
`error="frozen"`), R59 (enabling an instance is `hippo connector enable`, S4b's), m8
(`FactTemplate.consumes`, `ParserVersion.parse("json@1")`, `metadata_origin="catalog"` on
metadata-sourced nodes and edges, an HTTP(S) `instance_url`), m11 (the routes map `CredentialError`,
`Provider*Error`, `RegistrationRequired` and `ConnectorSyncRefused` to coded responses with
redacted messages, with tests). Where a ruling and the plan differ, the ruling wins; say so in your
evidence.

FILES:
  - own: `src/hippo/connectors/examples/**`, `src/hippo/web/routes/connectors.py`,
    `src/hippo/web/app.py` (the route mount only), `src/hippo/mcp_server.py`,
    `tests/unit/test_connector_exemplar.py`, `tests/unit/test_connector_surfaces.py`,
    `tests/unit/test_mcp_server.py` (the `TOOL_NAMES` set only), `docs/MCP.md`, `docs/CONTRACTS.md`
    (connector entries), `README.md` (the tool count); new `ai_docs/gates/rag-it-all/cdk/evidence-s6.md`.
  - do NOT touch: everything the plan's section 9 forbids (`cli.py`, `remote.py`, every other
    `connectors` module, `src/hippo/knowledge/**`, `src/hippo/store/**`, `src/hippo/ingest/**`,
    `docs/spec/*`, the ledgers, the checkpoint, `data/`, `.rag-dev-data/`).

STEPS: worktree + venv (the rulebook recipe, with the `mcp==2.1.1` pin). The plan's steps 1–7 in
order: scaffold and commit the unedited output first; RED; edit; regenerate goldens and review the
diff; routes and tool; docs; GREEN (the section 8 lines, form (b) filter where the plan says);
Ruff; commit. Evidence file: RED and GREEN log paths, counts per backend, the query used for the
retrieval check and its citations, and every override.

CONSTRAINTS: the S4b brief's constraints hold. The exemplar imports nothing outside
`hippo.connectors` public modules and `hippo.knowledge.model` (plus the R60 admissions); `ts` never
comes from the clock; unknown policy is deny; nothing calls the user's Ollama or reads
`.rag-dev-data/`. No duration language.

DONE WHEN: RED recorded, then the section 8 lines and the CK6 CHECK line exit 0 on Fake and the
exemplar lines on LadybugDB; `horch done` names the commit, counts per backend, log paths, the
retrieval check, overrides and open questions.

REPORT: `horch note` after each step; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a
question the plan, the rulings and the reviews do not answer.

## Amendments (rulings R70, R71)

- The `service` endpoint of `AFFECTS` is an identity-only foreign `NodeEmission` whose ref carries
  `instance=<catalog_instance>` and `label="checkout"`; the binder stores the label and the edge
  statement reads "… affects service checkout". A label anywhere else is ignored (R71).
- Base your worktree on the HEAD named in the spawn message, which includes S2b-fix.

