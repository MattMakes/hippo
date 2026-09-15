# Brief: CDK S4b — the scaffold, the `hippo connector` commands and the developer guide

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `s4b` (branch
`wp/s4b`, base = the `rag-it-all-tibs` HEAD named in the spawn message, after S4a and S4c merged).
You implement the S4b task of `ai_docs/plans/cdk-s4-kit.md` (sections 3.2, 3.3 and 3.4 as the
contract; section 4 "S4b" steps; section 5's scaffold and CLI tests; section 6's S4b line), amended
by the rulings and review findings below.

GOAL: `hippo connector new|list|validate|probe|sync|enable` in `cli.py` with `list` forwarded
through `remote.py`; `hippo connector new` writes a package (descriptor, `TypeExtension`,
templates, one fixture case, one passing test) whose `hippo connector validate` passes; the
developer guide `docs/spec/cdk-guide.md` whose examples are the fixture connector and are executed
by tests; the CK4 CHECK line green.

CONTEXT: the plan's sections 3.2–3.4, 4 (S4b), 5, 6, 7, 9, 10, 11 and its changelog; the reviews'
M16, m19 and the re-review's N5; the landed S4a and S4c code and evidence. Rulings that bind S4b
(`ai_docs/plans/cdk-rulings.md`): R7, R9 (`docs/spec/cdk-guide.md` is granted to you by name; the
rulebook's `docs/spec` rule yields for it), R58 (`cli.cmd_connector` calls `load_registry`; the
lifespan call already exists from S4c), R59 (`hippo connector enable <kind> <instance_url>
[--config <file>]`: `manage_sources`, `BuildActor.trusted_local()`, outside any build window,
`ensure_connector(..., enabled=True)` under the connector's own scratch registry (R63 N5), then the
probe and `store_classification`), R64 (in open mode the store refuses `enabled=True` for any kind
but `local`; `enable` exits 2 with that message and the test proves it; the descriptor name equals
the registered connector kind and `Connector.kind`, and `__init__.py.tmpl`'s re-export of
`Connector` is load-bearing), M16 (the template emits `NodeRef(kind=..., key={"id": ...})` and the
kit fills `instance`; regenerate the pinned scaffold output), m19 (non-dry-run `sync`:
`manage_sources`, the loader, an enabled kind, a stored classification or exit 2, then
`BuildActor.trusted_local()`), R14 (no MCP work here). Where a ruling and the plan differ, the
ruling wins; say so in your evidence.

FILES:
  - own: the files the plan's S4b step stages (the scaffold templates and their module, the
    `cli.py` connector subcommands, the `remote.py` forwarding for `list`,
    `tests/unit/test_connector_scaffold.py`, `tests/unit/test_cli_connector.py`), plus
    `docs/spec/cdk-guide.md`; new `ai_docs/gates/rag-it-all/cdk/evidence-s4b.md`.
  - do NOT touch: any S4a or S4c file, every other `connectors` module, `src/hippo/knowledge/**`,
    `src/hippo/ingest/**`, `src/hippo/store/**`, the web package, `mcp_server.py`, `tests/fakes/**`,
    `tests/unit/test_layering.py`, `test_import_order.py`, every other `docs/spec` file, the
    ledgers, the checkpoint, `data/`, `.rag-dev-data/`.

STEPS: worktree + venv (the rulebook recipe, with the `mcp==2.1.1` pin). RED first (the plan's S4b
tests plus the `enable` tests), failures recorded; GREEN; the S4b line of section 6 and the CK4
CHECK line of `ai_docs/gates/rag-it-all/cdk/GATES.md` verbatim; Ruff on your files (and `ruff
format --check` on the guide, whose fenced Python must be ruff-formatted); the commit with the
plan's message. Evidence file: RED and GREEN log paths, counts, the scaffolded package's validate
output, and every override.

CONSTRAINTS: the S4a brief's constraints hold. `hippo --help` must not import the loader or the
serving modules; `probe` keeps config and credential references on the caller's machine; the guide
contains no credential and no instance of the user's data. No duration language.

DONE WHEN: RED recorded, then the S4b line, the CK4 CHECK line and Ruff exit 0; `horch done` names
the commit, counts, log paths, overrides and open questions.

REPORT: `horch note` after each step; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a
question the plan, the rulings and the reviews do not answer.
