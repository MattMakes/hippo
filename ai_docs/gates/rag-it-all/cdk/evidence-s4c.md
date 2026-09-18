# CDK S4c evidence: the connector registry loader and its install at serve startup

Worker `backend-developer-6`, branch `wp/s4c`, base `bc647ef` (the `rag-it-all-tibs` HEAD naming
S1a's merge `d0bd052` and S2a's `96eda9f`). Contract: task S4c of `ai_docs/plans/cdk-s4-kit.md`
(section 3.5, section 4 "S4c", section 5's `test_connector_loader.py`, section 6's S4c lines),
amended by the rulings the brief `ai_docs/handoffs/briefs/cdk-s4c.md` names — R50, R57 (the allowlist
in `loader.py`), R58 (the lifespan call is S4c's, the CLI call S4b's) and R63 with the re-review
`ai_docs/reports/2026-09-15-cdk-s4-replan-review.md` (N1, N2, N3, and the minors N13, N14, N15 that
land in section 3.5).

## Commits

| # | Hash | Subject | Files |
| --- | --- | --- | --- |
| 1 | `baa02eb` | Add the connector registry loader and install it at serve startup (CDK S4c) | `src/hippo/connectors/loader.py`, `tests/unit/test_connector_loader.py` (new); `src/hippo/web/app.py` (the lifespan lines only), `tests/unit/test_import_order.py` (one appended line) |
| 2 | (this commit) | Record the S4c evidence | this file (new) |

No file outside the brief's "own" list was touched. `git show --stat baa02eb` is exactly the four
files above; the `web/app.py` diff is seven lines inside `lifespan`, and the
`test_import_order.py` diff is the single line `"hippo.connectors.loader"` appended to `MODULES`.

## RED

| Stage | Log | Result |
| --- | --- | --- |
| `tests/unit/test_connector_loader.py` before any source file | `/tmp/hippo-cdk-s4c-red.log` | exit 2; one collection error, `ImportError: cannot import name 'loader' from 'hippo.connectors'` — the shape the plan's step 1 predicts |

Two test-side defects surfaced on the first implementation run and were fixed in the tests, not in
the loader. Both are findings the later slices inherit, so they are written out under "What the
store taught us" below: an enabled provider `Connector` row needs a signed-in installation, and a
duplicate name legitimately puts two entries under one name in `LoadResult.entries`.

## GREEN (final tree, `baa02eb`)

| Line | Log | Result |
| --- | --- | --- |
| Plan section 6 S4c green: Fake, `test_connector_loader.py test_import_order.py` | `/tmp/hippo-cdk-s4c-green.log` | exit 0, 32 passed (17 loader cases, 15 import-order cases) |
| Plan section 6 S4c regression: Fake, `test_connector_loader.py test_web_base.py test_managed_web_surfaces.py test_registry.py test_registry_model.py` | `/tmp/hippo-cdk-s4c-regress.log` | exit 0, 275 passed |
| The same regression set without the new file, at the `bc647ef` baseline in the root tree | `/tmp/hippo-cdk-s4c-regress-baseline.log` | exit 0, 258 passed |
| M2's three tests by name (the DONE WHEN check) | `/tmp/hippo-cdk-s4c-m2.log` | exit 0, 4 passed (the first is parametrized) |
| The same file on LadybugDB, because the `store` fixture defaults to it | `/tmp/hippo-cdk-s4c-ladybug.log` | exit 0, 17 passed |
| Ruff `check` then `format --check` over the four files | `/tmp/hippo-s4c-ruff.log` | exit 0 and exit 0; "All checks passed!", "4 files already formatted" |
| `hippo --help` under the new tree, listing the `hippo.connectors` and serving modules it loaded | `/tmp/hippo-s4c-help.log` | exit 0; `connector/serving modules after --help: []` |

258 baseline plus this slice's 17 new cases is the 275 of the regression line: the four existing
files pass unchanged. The regression line carries form (b) of the fleet rules,
`-W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`, because
`test_web_base.py:6` and `test_managed_web_surfaces.py:33` import `fastapi.testclient` at module
level, so the warning fires at collection where no marker can catch it. The green line carries
`-W error` alone and needs no filter: neither `test_connector_loader.py` nor `test_import_order.py`
imports a test client, and the startup tests reach the lifespan through
`app.router.lifespan_context(app)`. This confirms the re-review's claim for the proposed CK4 CHECK
line. No warning was suppressed, and no ini-wide filter was added.

Counts per backend: Fake 17 new plus 258 regression equal to the baseline, LadybugDB 17. The
LadybugDB line is not a gate line — S4c persists nothing and adds no store path, its one store call
being the existing `_knowledge_rows("Connector")` — but the `store` fixture defaults to LadybugDB,
so the file is proved on the backend an invocation without `HIPPO_TEST_STORE` would pick: the two
lifespan tests close the store inside the lifespan and again in the fixture, and a real file takes
it. The store is exercised on LadybugDB outside pytest too, in the v7 lifespan run below, which the
brief asks for by name. No Neo4j run; the rulebook forbids one without a written grant.

## The tests

17 cases in `tests/unit/test_connector_loader.py`. The plan's eight names are all present (two of
them parametrized), plus the re-review's N2 test and six that cover section 3.5 rules the plan
states without naming a test.

| Test | Covers |
| --- | --- |
| `test_loader_registers_enabled_in_repo_packages_before_allowlisted_entry_points_then_freezes` | The order of section 3.5 "Loading", proved by a spy on `registry.register`: `[("acme",), ("beta",), ("gamma",)]`, then `frozen` |
| `test_a_discovered_kind_that_is_not_enabled_is_listed_and_not_registered` | Discovery without enablement (design section 9) |
| `test_loading_a_frozen_registry_registers_nothing_until_restart` | The restart rule of R50, in three loads: first registers, second reports the same extension as registered, a kind enabled after the freeze is `error="frozen"` |
| `test_loader_lists_a_failing_entry_point_and_continues[import_error]` and `[registration_refused]` | M2's first test. `ImportError` and `RegistrationError` are listed by class name; the second entry point still registers |
| `test_loader_skips_an_entry_point_missing_from_the_allowlist` | M2's second test, with `loads == 0`: an untrusted entry point is never imported |
| `test_an_entry_point_that_repeats_an_in_repo_name_is_a_duplicate_and_is_never_imported` | N15: the duplicate is decided before the import, again with `loads == 0` |
| `test_a_connector_whose_descriptor_name_differs_is_a_name_mismatch` | `error="NameMismatch"` (section 3.5 discovery step 3) |
| `test_an_in_repo_package_that_cannot_be_imported_is_listed_with_its_error` | The in-repo half of "any exception is caught and discovery continues" |
| `test_built_in_connector_kinds_are_listed_with_their_enablement` | Section 3.5 discovery step 4: the eight built-in kinds, `target=None`, `registered=True`, `enabled` from `enabled_kinds` |
| `test_connector_class_answers_for_a_registered_entry_and_refuses_otherwise` | `LoadResult.connector_class`, including the built-in kind that carries no class (N17's case, which S4b maps to exit 2) |
| `test_enabled_kinds_come_from_enabled_instances_and_the_allowlist_from_the_environment` | `enabled_connector_kinds` over enabled and disabled rows; `configured_allowlist` over an unset, empty, padded and environment-read list |
| `test_load_connectors_reads_the_enabled_kinds_and_the_allowlist` | `load_connectors(ctx)` as the composition of the two inputs |
| `test_load_connectors_never_raises_when_connector_rows_cannot_be_read[rows]` and `[load_registry]` | N14: the row read and the walk itself are both guarded; the registry is left unfrozen either way |
| `test_serve_startup_installs_a_frozen_registry` | M2's third test: `create_app(ctx)`, `asyncio.run` over `app.router.lifespan_context(app)`, `current_registry().frozen` and the enabled stand-in listed as registered on `app.state.connector_load` |
| `test_serve_startup_with_an_unreachable_store_loads_no_kinds_and_says_so` | N2: the error is recorded, `entries == ()`, and the registry is **not** frozen |

Ruling N1 holds for every one of them: each test that reaches `load_registry` runs under a
`use_registry(Registry.with_builtins())` fixture, so nothing this file registers survives into
`REGISTRY`, and the regression line puts the loader, the web and the registry suites in one process
to show it.

The tests do not write fixture packages into `src/hippo/connectors/`, which no brief grants. They
point `loader.IN_REPO_PACKAGES` at a temporary package root on `sys.path`, write the same connector
source there that the entry point stand-ins execute, and drop the root's modules from `sys.modules`
afterwards so a later test of the same package name gets its own code. Entry points are the plan's
stand-ins with `name`, `value` and `load()`, installed by replacing `loader._entry_points`.

## The v7 store lifespan run (N2, ruled by R63)

`/tmp/hippo-s4c-v7-lifespan.log`, from `/tmp/hippo-s4c-v7-lifespan.py` run under
`.venv/bin/python -W error`, exit 0. A real LadybugDB file at this tree's
`CURRENT_SCHEMA_VERSION = 7`, a 256 MiB buffer pool, and an `httpx.MockTransport` model client so
the user's Ollama is never called (`startup` logged "Ollama … is not reachable yet" in all three
phases). Each phase runs under its own `use_registry(Registry.with_builtins())`, which is what a
fresh process gives the loader.

| Phase | Store | Result inside the lifespan |
| --- | --- | --- |
| A: a new file, first lifespan | `schema_version` 7, state `complete`; `_knowledge_rows("Connector")` returns `[]` | `error: None`; 8 entries, all `built-in` (`backstage, git, github, gitlab, jira_cloud, jira_data_center, local, tuleap`); none enabled; `frozen: True` |
| B: the same file reopened, second lifespan | unchanged at 7 / `complete` | identical to A — the restart reads the same way |
| C: the same file with the migration marked incomplete after `startup` | `run()` raises `RuntimeError("Store migration is incomplete; application access is disabled")` | `error: 'RuntimeError'`; `entries: 0`; `frozen: False`, and the lifespan still completed |

Phase C is the finding the brief asks for. `startup(ctx)`'s `ping()` *completes* a migration that
can complete — with the flag set before the lifespan it was cleared by the time the loader read, and
the load succeeded — so the honest v7-era failure is a migration that does not finish, and the flag
is set in C between `startup` and `load_connectors`. The loader then behaves as N2 requires: it
records the error, registers nothing, and leaves the registry unfrozen, so the next process can load
the vocabulary rather than serving an empty one until someone restarts twice. Nothing in phases A–C
raised out of the lifespan.

## What the store taught us (for S4b, S5 and S6)

- **An enabled provider `Connector` row needs a signed-in installation.**
  `store/authorization.py:44` (`configured_provider`) plus `store/knowledge.py:675` refuse
  `enabled=True` for any kind other than `local` while `count_users() == 0`: *"Provider connectors
  require a signed-in installation; open mode cannot configure or enable them"*. So
  `enabled_connector_kinds` is empty by construction on an open-mode installation, and R59's
  `hippo connector enable` (S4b) must either run on an installation with users or surface that
  refusal as its own exit 2. The loader's tests create a user before seeding rows.
- **A duplicate name legitimately yields two entries with one name.** The in-repo package and the
  shadowed entry point are both listed, the second with `error="DuplicateName"`. S6's
  `GET /api/connectors` should key its rows on `(origin, name)`, not on `name`.
- **The descriptor name is three things at once**: the discovered entry name, the connector kind the
  extension registers, and the `Connector.kind` an operator's row carries. The loader refuses any
  disagreement with `NameMismatch`, and the scaffold (S4b) must keep them equal.

## Overrides and deviations, each with its reason

1. **`LoadResult` gains `error: str | None = None`.** Section 3.5's dataclass lists only `registry`
   and `entries`, but N2 and N14 require the failure to be recorded *in* `LoadResult`. A third
   optional field is the smallest shape that carries it, and `entries == ()` beside it is what says
   nothing was loaded.
2. **`error="frozen"`** is the spelling for an enabled entry whose extension is absent from an
   already-frozen registry. Section 3.5's comment lists four spellings and names no fifth for the
   restart rule; the entry has no exception to name, and S6's route wants a reason to show.
3. **The restart rule compares what it can compare.** Object kinds, predicates and locator kinds are
   compared whole with `==` through `object_kind`, `predicate` and `locator_kind` (N13 names
   `locator_kind`, because `locator()` returns only the model). Families, evidence sources, artifact
   kinds and connector kinds are compared by membership: `Registry.evidence_source` returns a name,
   and the definition accessor ruling R62 gives S1b (`evidence_source_definition`) does not exist at
   this base. N13's gap — families and evidence sources missing from the comparison — is closed;
   tightening evidence sources to equality is S1b's to enable.
4. **Entry order in `LoadResult.entries`** is the built-in kinds first in name order, then in-repo
   packages, then entry points, which is design section 3's order and the order registration walks.
   The plan states the registration order and lists built-ins in step 4 without fixing the tuple's
   order; this one is stable and reads the way the design does.
5. **N3 is moot in S4c, and is recorded rather than applied.** The restart rule compares definitions
   by equality, so the loader hashes no definition and never calls `model_dump` on one. N3 binds
   S4a's `extension_lock`, not this slice.
6. **An in-repo package is imported through the package, not through `connector.py`.** Section 3.5's
   target is `hippo.connectors[.examples].<name>:Connector`, and the scaffold's `__init__.py.tmpl`
   is `from .connector import $class_name as Connector` (section 3.2), so `Connector` is read off
   the package. The `connector.py` file is part of what makes a directory a candidate, nothing more.
   S4b's scaffold must keep that re-export, and the loader's tests write one.
7. **A missing `hippo.connectors.examples` is normal.** `importlib.resources.files` is called inside
   a `try` that skips an `ImportError` or `TypeError`, because no `examples` package exists at this
   base and one need never exist.
8. **`HELP_MUST_NOT_IMPORT` was not extended.** The brief grants one appended line in
   `test_import_order.py`, which is `"hippo.connectors.loader"` in `MODULES`. The `--help` constraint
   is met and measured: `cli.py` imports no connectors module at all today (S4b's calls are
   function-local by its own plan), and the run logged above prints an empty list. If a later slice
   wants the absence pinned, the line is one string in that tuple.
9. **Two test names beyond the plan's list carry re-review findings** rather than inventing scope:
   the duplicate test proves N15's "decide before import", and the parametrized
   `[load_registry]` case is N14's second case, added to the plan's own test name rather than to a
   new one.
10. **Ruff is 0.16.7 in this worktree venv**, where the rulebook says 0.16.6. `uv` resolved it; both
    lint lines pass and the formatter made no change the rulebook's version would not have made.
    Worth a one-line note in the rulebook if the fleet wants the version pinned.

## Open questions for the orchestrator

1. **`LoadResult.error` and `error="frozen"`** are the two shapes S6's `GET /api/connectors` will
   render. If the ledger wants different spellings, now is the cheap moment: no caller exists yet.
2. **Evidence sources in the restart rule** stay a membership check until S1b lands R62's
   `evidence_source_definition`. Should S1b's brief carry "tighten `loader._already_registered` to
   compare evidence source definitions", or is membership the final answer?
3. **R59's `enable` command meets the open-mode refusal** described above. S4b's brief should say
   which it is: require a signed-in installation, or let `hippo connector enable` fail with the
   store's own sentence.
4. **The CK4 CHECK line replacement** proposed in plan section 6 is safe as written for this slice:
   `test_connector_loader.py` needs no anyio filter, which the green line above demonstrates. The
   ledger change is the orchestrator's to apply.

## S4c-fix: the seeded connector kinds are registered before they are written

Worker `backend-developer-9`, branch `wp/s4c-fix`, base `2c15134` (the `rag-it-all-tibs` HEAD that
merges S4c on top of S1b), brief `ai_docs/handoffs/briefs/cdk-s4c-fix.md`. One commit,
`Register the loader tests' seeded connector kinds through the registry`, touching
`tests/unit/test_connector_loader.py` and this file. No source file was changed and none needed to
be: the refusal is `check_record` doing its job.

### The failure

S1b (`9e5b93c`) made `put_knowledge` call `current_registry().check_record(record)` on every
knowledge write (ruling R39, `src/hippo/store/knowledge.py:772`). `seed_connectors` writes
`Connector` rows of kinds `acme` and `beta`, which no registry knows, so all three tests that seed
rows died in the helper with `ValueError: Unknown connector kind`, raised from
`UnregisteredName: Unknown connector kind: 'acme'` at `registry.py:295`. Nothing about S4c's loader
was wrong; the tests were writing rows production writes under the connector's own extension.

| Stage | Log | Result |
| --- | --- | --- |
| `tests/unit/test_connector_loader.py` on Fake at `2c15134`, before the fix | `/tmp/hippo-s4c-fix-red.log` | exit 1; 3 failed, 14 passed — the three the brief names, each with the traceback above |

### The fix

`seed_connectors` now registers the kinds it is about to write, inside `extension_scope()`:

```python
with extension_scope() as scoped:
    scoped.register(TypeExtension(families=tuple(kinds), connector_kinds=tuple(kinds)))
```

Four things decided it:

1. **A throwaway extension, not a relaxed check.** `check_record` is untouched, nothing is skipped,
   and no test is marked. The seeded kinds become real vocabulary for the length of the write, which
   is the state production is in when `hippo connector enable` writes the same row (R63 N5).
2. **`extension_scope()`, so nothing reaches `REGISTRY` (N1).** The scope restores the registry's
   state whole — `test_registry.py::test_extension_scope_restores_the_registry_byte_for_byte` is the
   proof — including the frozen flag, so a seeded kind survives neither the test nor the process.
3. **The scope closes before the helper returns.** This is the part worth reading twice: a caller
   that goes on to `load_connectors` registers the *discovered* connector's real extension under
   these same names, and a throwaway still in place would make that registration fail with
   `duplicate_name`. Only the `Connector` writes are inside the scope; the schema, roles, user and
   workspace calls stay outside it.
4. **`test_enabled_kinds_come_from_enabled_instances_and_the_allowlist_from_the_environment` now
   takes the `registry` fixture.** It is the one seeding test that never reaches `load_registry`, so
   it had no fixture, and under the default `extension_scope()` yields `REGISTRY` itself (R16).
   Taking the fixture keeps the throwaway extension out of the process registry literally and not
   just by restoration. It changed no assertion in that test. The module docstring's N1 paragraph
   now states the seeding rule alongside the `load_registry` one.

Only the helper, that one signature, the module docstring and the registry import line changed. No
test case, assertion or name was altered, so the 17 cases and the coverage table above still read
true.

### GREEN

| Line | Log | Result |
| --- | --- | --- |
| Fake: `test_connector_loader.py test_import_order.py test_layering.py test_registry.py test_registry_model.py` (the brief's line) | `/tmp/hippo-s4c-fix-green.log` | exit 0, 191 passed |
| LadybugDB: `test_connector_loader.py` | `/tmp/hippo-s4c-fix-ladybug.log` | exit 0, 17 passed |
| Fake: `test_connector_loader.py` alone, the first run after the fix | `/tmp/hippo-s4c-fix-first-green.log` | exit 0, 17 passed |
| Ruff `check` then `format --check` over the two changed files | `/tmp/hippo-s4c-fix-ruff.log` | exit 0 and exit 0 |

Both lines carry `-W error` with no filter and no suppression: neither this file nor the four
regression files imports `fastapi.testclient` at module level, so form (b) of the fleet rules is not
needed here, and the CK4 CHECK line proposed above still holds. LadybugDB is green because a read
never calls `check_record` and `Connector.kind` is a plain `Code`, so a row written under the
throwaway extension validates on the way back out with no registry involved. No Neo4j run.
