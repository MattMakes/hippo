# CDK S4b evidence: the scaffold, the `hippo connector` commands and the developer guide

Worker `backend-developer-15`, branch `wp/s4b`, base `2710262` (the `rag-it-all-tibs` HEAD named in
the spawn message, after S4a and S4c merged). Contract: task S4b of `ai_docs/plans/cdk-s4-kit.md`
(sections 3.2, 3.3 and 3.4, section 4 "S4b", section 5's `test_connector_scaffold.py` and
`test_cli_connector.py`, section 6's S4b line), amended by the brief
`ai_docs/handoffs/briefs/cdk-s4b.md` and its R73 amendment. Read first: `evidence-s4a.md`
(especially its gotcha 7 about the committed goldens) and `evidence-s4c.md`.

Where a ruling and the plan differ, the ruling wins; every such case, and every case where the
landed code overrode the plan, is under "Overrides".

## Commits

| # | Hash | Subject | Files |
| --- | --- | --- | --- |
| 1 | `434733a` | Add the connector scaffold, the hippo connector commands and the developer guide (CDK S4b) | `src/hippo/connectors/scaffold/__init__.py` and `scaffold/templates/*.tmpl` (new, 10 templates); `src/hippo/cli.py` (the `connector` group, the handler entry and `cmd_connector` with its helpers); `src/hippo/remote.py` (`connectors()`); `docs/spec/cdk-guide.md` (new); `tests/unit/test_connector_scaffold.py`, `tests/unit/test_cli_connector.py` (new); `tests/fakes/fixture_connector/{connector,types}.py` (the `cdk-guide` marker comments only) |
| 2 | (this commit) | Record the S4b evidence | this file (new) |

### The one grant beyond the brief's "own" list

The brief lists `tests/fakes/**` under "do NOT touch" with no exception, while plan section 4 step 6
and section 7 both grant S4b "marker comments in S3's fixture connector" and section 3.4 makes them
load-bearing. Asked before any edit; the orchestrator answered:

> YES: add the four `# cdk-guide: begin/end <name>` marker comment pairs (comments only, zero code
> change) to `tests/fakes/fixture_connector/connector.py` and `types.py`, as plan section 7 grants;
> the brief's do-not-touch yields for those lines. Rerun the CK3 Fake line and the kit's
> fixture-golden test after adding them and name the grant in the evidence.

Both reruns are under GREEN. The whole diff to that package is ten lines:

```text
+# cdk-guide: begin descriptor
+# cdk-guide: end descriptor
+    # cdk-guide: begin sync_half
+    # cdk-guide: end sync_half
+
+    # cdk-guide: begin emit
+
+    # cdk-guide: end emit
+# cdk-guide: begin types
+# cdk-guide: end types
```

Four comment pairs and the two blank lines `ruff format` requires before a trailing comment. No
statement, no signature and no byte of `emit` changed, which is why the committed goldens still
reproduce. Nothing else outside the brief's list was touched: no other `docs/spec` file, no gate
ledger checkbox, no checkpoint, no `data/`, no `.rag-dev-data/`, no other `connectors` module, no
`knowledge/`, `ingest/`, `store/`, web package or `mcp_server.py`.

## RED

| Stage | Log | Result |
| --- | --- | --- |
| Both S4b test files against the base tree, before any source edit | `/tmp/hippo-cdk-s4b-red.log` | exit 2; one collection error, `ImportError: cannot import name 'scaffold' from 'hippo.connectors'` — the shape the plan's step 1 predicts |
| The same two files against a stub-only `scaffold/__init__.py` (every public name present, `render_package` raising `NotImplementedError`) with `cli.py` and `remote.py` reverted to `2710262` | `/tmp/hippo-cdk-s4b-red2.log` | exit 1; **47 failed, 8 passed, 5 errors** |

The plan's RED is a collection failure, which proves the module is absent but not that each
assertion bites. The second RED exists for that, as S4a's did. The eight that passed against the
stub are the ones that do not depend on this slice's code:

| Passed against the stub | Why it legitimately does |
| --- | --- |
| `test_the_guide_exists_and_every_python_example_is_the_fixture_connector`, `test_the_guide_documents_every_assertion`, `test_the_guide_carries_no_credential_and_no_user_data`, `test_the_fixture_connector_markers_are_comments_only` | The guide and the markers were already committed when the second RED ran, so these four measure files on disk rather than the reverted modules. They were RED in the first run, where `docs/spec/cdk-guide.md` did not exist |
| `test_the_connector_group_requires_a_subcommand`, `test_connector_help_imports_no_serving_machinery` | Both assert an absence: an unknown subcommand exits 2, and nothing heavy is imported. A CLI with no `connector` group satisfies both |
| `test_the_connector_command_is_not_an_evidence_command`, `test_a_type_extension_is_importable_for_the_scaffold_test` | Constants: `EVIDENCE_COMMANDS` and `TypeExtension()` |

The tree was restored from `HEAD` afterwards and `git status` is clean; the 60 cases are green
again on the restored tree.

**What going green found** is under its own heading below: five defects, four of them in the plan's
text rather than in the tests, and all five bit as assertions rather than as tracebacks.

## GREEN

| Line | Log | Result |
| --- | --- | --- |
| Section 6's S4b line, Fake: `test_connector_scaffold.py test_cli_connector.py test_cli.py test_import_order.py` | `/tmp/hippo-cdk-s4b-green.log` | exit 0, **136 passed** |
| The CK4 CHECK line of `ai_docs/gates/rag-it-all/cdk/GATES.md`, verbatim | `/tmp/hippo-cdk-s4b-ck4.log` | exit 0, **163 passed** |
| The same two S4b files on LadybugDB | `/tmp/hippo-cdk-s4b-ladybug.log` | exit 0, **60 passed** |
| Regression, the marker grant: the CK3 Fake CHECK line | `/tmp/hippo-cdk-s4b-ck3-fake.log` | exit 0, **296 passed, 2 skipped** |
| Regression, the marker grant: `test_the_fixture_connector_passes_every_assertion` (the one test that reads the committed goldens) | `/tmp/hippo-cdk-s4b-goldens.log` | exit 0, **1 passed** |
| `hippo connector new` then `hippo connector validate`, end to end, at the shipped default scratch store | `/tmp/hippo-cdk-s4b-e2e.log` | see "The goal sentence, end to end" |
| Ruff `check` then `format --check` over the eight changed `.py` files and the guide | `/tmp/hippo-s4b-ruff.log` | exit 0 and exit 0; "All checks passed!", "8 files already formatted" |
| `hippo --help` under this tree, listing the connector, ingest and serving modules it loaded | `/tmp/hippo-s4b-help.log` | exit 0; `connector/serving modules after --help: []` |

Counts per backend for the two S4b files: **Fake 60**, **LadybugDB 60**, the same cases on both.
The Fake S4b line reads 136 because it also runs `test_cli.py` (55) and `test_import_order.py` (21),
both unchanged.

**Warning filters.** Every line above ran with `-W error` alone — **form (a)** of rulebook line 19,
and in fact no marker was needed either. No file in any of these lines imports `fastapi.testclient`
or `starlette.testclient` at module level: `test_cli.py`'s fourteen server tests import
`starlette.testclient` inside `behind_server` and carry their existing per-test markers, which this
slice did not touch, and the two new files prove forwarding against `httpx.MockTransport` and never
build a test client at all. This confirms plan section 6's claim for the CK4 CHECK line: **the
four-file CK4 line needs no form (b) filter**. No warning was suppressed and no ini-wide
`filterwarnings` was added.

**No Neo4j run.** The rulebook forbids one without a written grant, which this worker did not hold.

Nothing here reads `.rag-dev-data/`, a real credential, a real token, the server on 8011 or the
user's Ollama. The kit's model is `offline_ollama()` over `httpx.MockTransport`, every store is a
temporary one, and the guide contains no credential and no instance of the user's data
(`test_the_guide_carries_no_credential_and_no_user_data` pins the absence).

## The goal sentence, end to end

The brief's GOAL is one sentence: `hippo connector new` writes a package whose
`hippo connector validate` passes. Run as a developer runs it — the installed console script, no
`HIPPO_TEST_STORE`, so the scratch store is the **shipped default**, a temporary LadybugDB with a
256 MiB buffer pool (R7, S4a finding N9) rather than the Fake the tests substitute:

```text
hippo connector new incidents_ndjson --family incident --kinds incident --dest /tmp/s4b-e2e
hippo connector validate /tmp/s4b-e2e/incidents_ndjson
```

`/tmp/hippo-cdk-s4b-e2e.log` holds both. `new` exits 0 and writes eighteen files; `validate` exits 0
and prints:

```text
+ connector kind incidents_ndjson
+ kind incident
+ template incident/summary@1
incidents_ndjson 1: passed (full)
```

`full` scope means the run included the registry lock, the capture assertions, the twelve contract
assertions, `run_case` against the committed goldens and all five runtime scenarios.

## The scaffolded package

`render_package(ScaffoldRequest(name="incidents_ndjson", family="incident", kinds=("incident",)))`
writes eighteen files: the ten from templates, the registry lock, and the seven goldens.

| Path | Written by |
| --- | --- |
| `__init__.py`, `connector.py`, `types.py`, `templates.py`, `tests/test_connector.py` | templates |
| `fixtures/basic/{config,changes,policies}.json`, `fixtures/basic/inputs/record-{1,2}` | templates |
| `fixtures/registry.lock.json` | `render_package`, from `testing.extension_lock` (see override 2) |
| `fixtures/basic/expected/*.json` (seven) | `validate_package(update_golden=True)` |

`test_scaffold_output_for_a_fixed_request_is_pinned` pins all eighteen by SHA-256 and the six short
ones (`__init__.py` and the whole fixture case) byte for byte, so a kit change that alters scaffold
output fails in this repository rather than silently in a developer's package. The pins were filled
from the first GREEN rendering, the way S4a filled its digest pin; the test names its own
regeneration command. **The digests are identical on Fake and on LadybugDB** — the LadybugDB line
above runs the same pinned test — which is the same cross-backend property S4a established for the
fixture connector's goldens.

`test_a_scaffolded_package_is_ruff_clean` runs `ruff check` and `ruff format --check` over the
generated `.py` files as a subprocess. It resolves this repository's configuration (line length 110,
`E,F,I,B,UP`), because ruff reads the configuration of the working directory when a file has no
ancestor `pyproject.toml`; a developer whose own repository declares `hippo` as a third-party import
will see `ruff check --fix` swap the `pydantic` and `hippo` import blocks, and nothing else.

## Overrides: where a ruling, a review finding or the landed code overrode the plan

1. **`fixtures/basic/policies.json` declares a known workspace policy for both records; section 3.2
   says `{}`.** With no policies, the replay answers `state="unknown"` for every record, and
   `policy_change_mid_page` narrows a policy that is already the narrowest: the stored policy does
   not move at the checkpoint and the scenario fires
   (`policy_change_mid_page: narrowing takes effect at the checkpoint, so A's artifact names the new
   policy`). A scaffolded package must pass `validate` in full scope, so the case records what a
   provider that *does* answer would say. The generated `fetch_policy` is unchanged from section
   3.2 — it returns `state="unknown"` with the comment that unknown is deny — and its docstring now
   says why the two differ. The kit never calls the real `fetch_policy`; the replay overrides it.
2. **`render_package` writes `fixtures/registry.lock.json` itself.** Section 3.2 says
   `validate_package(update_golden=True)` "computes the goldens **and the registry lock**". As
   landed it computes only the goldens: `assert_registry_lock` reads a lock that already exists and
   compares, and writes nothing (`testing.py`). A package shipped without a lock would satisfy
   `registry_version_bump` vacuously forever. `render_package` therefore writes it from the public
   `testing.extension_lock(descriptor.extension, version=descriptor.version)` in canonical JSON —
   the same bytes S4a committed for the fixture connector — before it calls `validate_package`, so
   the validate run confirms the lock it just wrote. See finding 2.
3. **The `update_golden=True` run's diff is not a failure.** `ValidationReport.passed` is false on
   that run by construction: `--update-golden` writes the seven goldens and reports the diff from
   the empty tree it found. `render_package` therefore checks `report.error`, `report.violations`
   and each case's error and violations, and leaves the diff to the plain `validate` the developer
   runs next — which `test_a_new_package_passes_validate` proves is clean.
4. **The generated class publishes `descriptor` as a class attribute.** `loader._imported` reads
   `connector.descriptor` off the *class*, before anything is constructed. See finding 3.
5. **`--family` defaults to `custom`; `--kinds` defaults to the connector name.** Section 3.3 shows
   both as optional and fixes neither default. `custom` is the built-in family that exists for
   exactly this, and a single kind named after the package is the shortest honest starting point;
   both are stated in the `--help` text and in the guide.
6. **`key_prefix` is the primary kind's first four characters.** Section 3.2 makes `$key_prefix` a
   placeholder and names no rule. One rule that always yields a valid `Code` beats a guess per
   request, and the placeholder is there for a developer who wants another.
7. **Two refusals beyond section 3.3's four.** A kind name that does not match `NAME`, and a kind a
   built-in already registers, are refused by name. `Registry.register` would otherwise refuse the
   second with `duplicate_name` after the files were written, and the first would only break when
   the generated module was imported. A refused request leaves no directory behind, which
   `test_new_refuses_...` asserts for every case.
8. **`render_package` returns every file under the new package, sorted**, not only the ones the
   templates wrote, because the lock and the goldens are part of what `new` produced. It removes
   the `__pycache__` that `validate_package`'s import leaves, so a developer's new package holds
   only what they are meant to read and commit.
9. **A guide fence for a region inside a class carries the `class FixtureConnector:` header line.**
   Section 3.4 requires each fenced block to equal its marked region byte for byte, and the plan
   also requires the guide's fenced Python to pass `ruff format --check`. Those two cannot both hold
   for an indented method region: measured on this tree, `ruff format` **dedents and reflows** a
   fenced block whose content is indented (for the `emit` region it joins
   `return base.EmissionBatch(failures=...)` onto one line once the dedent frees the width), so a
   verbatim method body fails the check, and the dedented, reflowed text is no longer the region.
   A fence that is `class FixtureConnector:\n` plus the indented region is valid top-level Python
   and is already formatted — verified directly on all four regions before the guide was written.
   The `descriptor` and `types` regions are top-level and their fences are the region alone.
10. **A marked region is normalized to exactly one trailing newline.** `ruff format` requires a
    blank line before a trailing comment inside a class body, and refuses a trailing blank line
    inside a fenced block. The two rules meet in the extraction rather than in the guide:
    `_marked_regions()` strips trailing newlines and restores one. Nothing inside the region is
    touched.
11. **`hippo connector enable` refuses a configuration whose `instance_url` disagrees with the
    argument.** S3's sync entry refuses such a row later
    (`sync.py`: `row.instance_url != getattr(config, "instance_url", row.instance_url)`), so the
    disagreement is named where the operator can still fix it rather than at the first sync.
12. **`enable` does not construct `BuildActor.trusted_local()`.** R59 names it, but none of
    `ensure_connector`, `probe` or `store_classification` accepts an actor, so a constructed value
    would be read by nothing. The actor appears where S3 requires one, in the non-dry-run `sync`
    (`test_sync_checks_manage_sources_then_runs_as_the_trusted_local_actor` asserts
    `actor.kind == "trusted_local"` and `actor.user_id is None`). R59's "outside any build window"
    is satisfied structurally: `enable` is a shell invocation and `ensure_connector` is never called
    from inside a sync. Both are in `_connector_enable`'s docstring, and this is open question 1.
13. **`cmd_connector` has six branches, not five.** R59's `enable` is the sixth, and the brief's
    GOAL names it.
14. **`hippo connector list` builds the `ConnectorSummary` list locally and prints the same table
    for the local and the forwarded answer.** Section 3.3 defines the shape and assigns the route to
    S6; `cli._connector_summaries` is that shape, so the two paths cannot drift while S6 is
    unwritten. Rows are keyed on `(origin, name)` as R64 requires.

## What going green found (the assertions that bit)

1. **`validate_package(update_golden=True)` never writes a registry lock** — override 2 and
   finding 2. The first rendering produced seventeen files and `test_new_writes_the_documented_
   package_files` named the missing one.
2. **A case whose policies are all unknown cannot pass `policy_change_mid_page`** — override 1. The
   scenario named itself; nothing else in the run did.
3. **`loader._imported` reads `descriptor` off the class**, and S3c's `FixtureConnector` does not
   have one — finding 3. The CLI tests' entry point stand-in is a one-line subclass that publishes
   it.
4. **Open mode refuses a provider `Connector` row whatever its `enabled` value** — finding 4. Every
   `list`, `sync` and `enable` test that seeds a row needed a signed-in installation first, which
   is what the `operator` fixture is.
5. **A malformed record exercises a `ParseFailure` and `failures.json` is still `[]`** — finding 1.

## Findings for the orchestrator (each one binds a later slice)

1. **`failures.json` cannot fill, and R75(4) expects it to.** `testing._parse_failures(coverage)`
   reads `coverage["failures"]` (falling back to `coverage["parse_failures"]`), but S3c writes the
   counts at `coverage["emission"]["failures"]` — measured on the scaffolded package, whose
   `record-2` is malformed by design: the coverage golden holds
   `"emission": {..., "failures": {"incident|-|-": 1}}` and `failures.json` is `[]`. This closes
   S4a's open question 3 the wrong way, and it **contradicts R75(4)**, which says `failures.json`
   "stays empty until a fixture exercises `ParseFailure` (S6's exemplar adds one malformed
   record)". S6's exemplar will add the record and still get `[]`. The fix is one line in
   `testing._parse_failures`, which S4a owns and this worker did not touch.
2. **`validate --update-golden` does not write a registry lock for any package but a scaffolded
   one.** Override 2 fixes it inside `render_package`. A developer who adds a kind to an existing
   package and reruns `--update-golden` gets updated goldens and a stale lock. The kit needs either
   a lock write in `validate_package(update_golden=True)` or a documented "regenerate the lock by
   hand" step; S6's validate route inherits whichever is chosen.
3. **A connector class must publish `descriptor` as a class attribute.** `loader._imported` reads it
   before construction, so `tests/fakes/fixture_connector/FixtureConnector` as committed is **not
   loadable through an entry point**: it sets `self.descriptor` in `__init__` only. S4b's scaffold
   emits a class attribute and `test_cli_connector.py` wraps the fixture connector in a one-line
   subclass. S5's ported connectors and S6's exemplar must carry one, and the S5/S6 briefs should
   say so; making the fixture connector itself carry one is a one-line S3c change nobody has been
   granted.
4. **Open mode cannot create a provider `Connector` row at all**, not merely an enabled one:
   `store/authorization.py`'s `safer_connector(None, candidate)` is `False`, so `enabled=False` is
   refused too. S4c's evidence recorded the enabled half; this is the rest of it. S6's route tests
   will need a signed-in installation for every connector row they seed.

## What S5, S6 and Task 15 get from S4b

| Item | Where |
| --- | --- |
| `scaffold.render_package(ScaffoldRequest, dest) -> tuple[Path, ...]`, `ScaffoldError`, `NAME`, `FAMILIES_REQUIRE_REGISTRY` | `src/hippo/connectors/scaffold/__init__.py` |
| Ten `string.Template` files as package data | `scaffold/templates/`, read through `importlib.resources` |
| `hippo connector new|list|validate|probe|sync|enable` | `cli.cmd_connector` and its helpers |
| The `ConnectorSummary` list S6's `GET /api/connectors` must return | `cli._connector_summaries`, built from `loader.load_connectors(ctx)` and the `Connector` rows |
| `RemoteHippo.connectors()` | `remote.py`, pointed at the route S6 writes |
| `cli._resolve_connector(name)` — one trusted connector by name, with the loader's own reason on refusal | `cli.py`; S6's routes need the same resolution |
| The developer guide, with its examples executed by CI | `docs/spec/cdk-guide.md`, `test_the_guide_exists_and_every_python_example_is_the_fixture_connector` |

## Gotchas for the next worker

1. **The guide's examples are generated, not typed.** A change to the fixture connector's
   `DESCRIPTOR`, its `types.py`, its sync half or its `emit` breaks
   `test_the_guide_exists_and_every_python_example_is_the_fixture_connector`. Re-extract the four
   regions and paste them back into the fences; the fence for an in-class region carries the
   `class FixtureConnector:` header line and nothing else (overrides 9 and 10).
2. **The scaffold's pinned output is pinned by digest.** Any change to a template, to
   `extension_lock`, to S2b's binder or to S3c's runtime moves
   `test_scaffold_output_for_a_fixed_request_is_pinned`. The failure message lists the files whose
   digest moved; regenerate both maps and read the diff before pasting.
3. **`render_package` runs the whole kit**, including all five runtime scenarios. A test that
   renders must point `testing.scratch_store` at the backend, or it opens a real temporary
   LadybugDB. `test_connector_scaffold.py` renders once per module for the tests that only read.
4. **`hippo connector validate <path> --update-golden` rewrites the target in place.** A test that
   runs it against `tests/fakes/fixture_connector` would rewrite the committed goldens; copy the
   package to `tmp_path` first, as `test_validate_update_golden_prints_the_diff_and_exits_0` does
   (S4a gotcha 7).
5. **Every CLI test runs under `use_registry(Registry.with_builtins())`**, and a test that seeds a
   `Connector` row of an extension kind registers that kind in an `extension_scope()` that closes
   before `main()` runs — otherwise the real registration inside `load_connectors` fails with
   `duplicate_name` (S4c-fix).
6. **`hippo --help` is still measured, not remembered.** Every `hippo.connectors`, `hippo.ingest`
   and `hippo.knowledge.*` import inside `cmd_connector` is function-local, and
   `test_connector_help_imports_no_serving_machinery` runs `hippo connector --help` in a fresh
   interpreter and requires the loaded set to be empty.

## Open questions for the orchestrator

1. **R59 names `BuildActor.trusted_local()` for `enable`, and nothing in `enable` takes an actor**
   (override 12). The actor is named in a comment and constructed in the non-dry-run `sync`. If the
   ruling means something else — an authorization record, or a `BuildActor` argument S3 would have
   to grow — say so and it is a small change.
2. **`failures.json`** (finding 1) contradicts R75(4). Whose is the one-line fix to
   `testing._parse_failures`: a S4a follow-up, or S6's?
3. **The registry lock on `--update-golden`** (finding 2). Should `validate_package` write it, so
   every package behaves the way a scaffolded one does, or is regenerating the lock by hand the
   documented step?
4. **`FixtureConnector` has no class-level `descriptor`** (finding 3), so it cannot be loaded
   through an entry point without a subclass. One line in S3c's package fixes it for S5, S6 and
   Task 15. Is that a S3c follow-up, or does each slice keep wrapping it?
5. **`--family` defaults to `custom` and `--kinds` to the connector name** (override 5). Both are
   defensible and neither is ruled. If the reviewer wants `--family` required, it is one argparse
   keyword and one test row.
