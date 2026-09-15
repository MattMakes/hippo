# Brief: CDK S4c — the connector registry loader and its install at serve startup

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `s4c` (branch
`wp/s4c`, base = the `rag-it-all-tibs` HEAD named in the spawn message, after S1a and S2a merged).
You implement the S4c task of `ai_docs/plans/cdk-s4-kit.md` (section 3.5 as the contract; section 4
"S4c" steps; section 5's `test_connector_loader.py` tests; section 6's S4c lines), amended by the
rulings and review findings below.

GOAL: `src/hippo/connectors/loader.py` with `discover_connectors`, `load_registry(*, enabled_kinds,
allowlist) -> LoadResult` (built-ins, then enabled in-repo packages, then allowlisted entry points,
then `freeze()`; a failing entry point is listed with its error and loading continues; a frozen
registry registers nothing, so enabling takes effect at restart), `enabled_connector_kinds(store)`,
`configured_allowlist()` (the `HIPPO_CONNECTOR_ALLOWLIST` environment variable, v1) and
`load_connectors(ctx)`; the `hippo serve` lifespan installs a frozen registry and records the
`LoadResult` on `app.state.connector_load`; the S4c tests green and the regression line unchanged.

CONTEXT: the plan's changelog, sections 3.5, 4 (S4c), 5 (S4c), 6, 7, 9, 10, 11; the S4 re-review
`ai_docs/reports/2026-09-15-cdk-s4-replan-review.md` (N1, N2, N3 and the "for the next worker"
notes); the landed S1a code (`src/hippo/knowledge/registry.py`: `Registry.with_builtins()`,
`register(..., declared_families=...)`, `freeze()`, `use_registry()`, `current_registry()`,
`extension_scope()`) and S2a code (`src/hippo/connectors/base.py`: `ConnectorDescriptor.extension`,
the registry re-exports), with their evidence files under `ai_docs/gates/rag-it-all/cdk/`. Rulings
that bind S4c (`ai_docs/plans/cdk-rulings.md`): R50, R57 (the allowlist lives in `loader.py`, read
from the environment), R58 (the CLI call is S4b's; the lifespan call is yours), R63 with the
re-review's N1 (your tests register extensions only inside `extension_scope()` or under
`use_registry(Registry.with_builtins())`, never into the process default), N2 (the lifespan calls
`startup(ctx)` BEFORE `load_connectors(ctx)`, which overrides the plan's "placed before
`startup(ctx)`"; an unreachable store must never freeze an empty registry: on a store failure the
loader records the error in `LoadResult` and leaves the registry unfrozen; run the lifespan once
against a v7-era store file and record the result), N3 (hash definitions through the registry's
canonical schema, never `model_dump` of `attrs_model`, wherever S4c hashes a definition).

FILES:
  - own: `src/hippo/connectors/loader.py`, `tests/unit/test_connector_loader.py`,
    `src/hippo/web/app.py` lifespan lines only (the plan's anchor), one appended line in
    `tests/unit/test_import_order.py` (`"hippo.connectors.loader"`); new
    `ai_docs/gates/rag-it-all/cdk/evidence-s4c.md`.
  - do NOT touch: every other `connectors` module, `src/hippo/knowledge/**`, `src/hippo/ingest/**`,
    `src/hippo/store/**`, `cli.py`, `remote.py`, the routes package, `tests/fakes/**`,
    `tests/unit/test_layering.py`, `docs/spec/*`, the ledgers, the checkpoint, `data/`,
    `.rag-dev-data/`.

STEPS: worktree + venv (the rulebook recipe, with the `mcp==2.1.1` pin). RED first (the plan's S4c
tests plus the N2 store-failure test), failures recorded; the plan's steps 2–4 with N2's order;
GREEN and the regression line of section 6 (its anyio filter is form (b): record it); Ruff on your
files; the commit with the plan's message. Evidence file: RED and GREEN log paths, counts, the v7
store lifespan result, and every override.

CONSTRAINTS: the S2a brief's constraints hold (pytest form with `-W error` and logs, never Neo4j,
never `pkill -f`, stage only owned files, never push, rebase or merge). `knowledge` never imports
`connectors`; `hippo --help` must not import the loader (`test_import_order.py`'s
`HELP_MUST_NOT_IMPORT`). No duration language.

DONE WHEN: RED recorded, then the S4c GREEN and regression lines and Ruff exit 0; the three M2 tests
pass by name; `horch done` names the commit, counts, log paths, the v7-store result, overrides and
open questions.

REPORT: `horch note` after each step; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a
question the plan, the rulings and the reviews do not answer.
