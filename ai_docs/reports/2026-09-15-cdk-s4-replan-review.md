# Narrow re-review: the re-planned CDK slice S4, sections 3.1 and 3.5

**Reviewer:** architect-reviewer-2 (herdr fleet, root tree, read-only).
**Subject:** `ai_docs/plans/cdk-s4-kit.md` as re-planned at `dffe1a3`, sections 3.1
(`connectors/testing.py`) and 3.5 (slice S4c, `connectors/loader.py`), against the findings that
rejected S4 in `ai_docs/reports/2026-09-15-cdk-plan-review.md` (B3, B4, M2, M5, M12, M13, M15, M16,
m6, m17, m18, m19, m20) and against the signatures S1, S2 and S3 provide, as amended by rulings
R39-R60 of `ai_docs/plans/cdk-rulings.md`. Sections 3.2-3.4 were checked only where the re-plan
changelog says they changed (M16, m19) and where R59 now binds them.
**HEAD:** `78dd2f9` on `rag-it-all-tibs`, working tree clean.
**Method:** every signature in 3.1 and 3.5 was read against its providing plan section or against the
landed S1a code at `src/hippo/knowledge/registry.py` (merged at `d0bd052`). I wrote no code and ran no
test suite. Six assumptions that the plans state but no plan proves were checked directly against the
root venv in `/tmp`, read-only; each is marked "probed" below and its result is quoted.

## VERDICT

- **Section 3.1 (the kit, S4a): APPROVED WITH CHANGES.**
- **Section 3.5 (the loader, S4c): APPROVED WITH CHANGES.**

The re-plan answers the two blockers. `purity_guard` is now S3's `forbid_effects` itself and nothing
patches the process (B3); `run_case` drives S3's real entry with its full signature, after
`ensure_connector(..., enabled=True)`, the replay probe and `store_classification`, and the five
runtime scenarios are S3 section 9's boundaries on replay variants with S3's labels (B4). The loader
exists as its own slice with the three tests M2 named, and it merges before every caller. Twelve of
the thirteen findings are closed. No section needs re-planning again: every new finding has a
spelling-level fix inside the section it lands in.

**Counts.** Prior findings: 12 CLOSED, 1 OPEN (m18). New findings: 0 blockers, 5 majors, 14 minors.
One of the five majors (N5, ruling R59) lands in sections 3.3 and 5 and binds the S4b brief; it does
not gate either verdict here.

## New findings

| ID | Sev | Plan section, or `file:line` | Violates | Exact fix |
| --- | --- | --- | --- | --- |
| N1 | MAJOR | S4 section 3.5 "The process registry in tests"; section 5 S4b; `tests/unit/test_connector_sync.py` (S3 section 11) | Test-order independence of `pytest tests/unit` | The hazard is population, not the frozen flag. Rewrite the rule as: any test that reaches `load_registry`, through a lifespan, `cmd_connector list|sync`, or S5's `default_registry()`, runs under `use_registry(Registry.with_builtins())`, so nothing it registers survives into `REGISTRY`. Bind it in section 5 for S4b's CLI tests, and add one process-level proof to S4b's GREEN: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_cli_connector.py tests/unit/test_connector_sync.py tests/unit/test_registry.py -q -o addopts='' -W error` |
| N2 | MAJOR | S4 section 3.5 "Wiring (R50)"; `src/hippo/web/app.py:63-68`, `:163-180` | `startup` "Never raises"; design section 9 enablement | Call `load_connectors(ctx)` **after** `startup(ctx)`, not before: `startup`'s `ping()` is what bootstraps the schema, and it is designed to tolerate a store that comes up minutes later. Loading first means an unreachable store yields `enabled_kinds=frozenset()` and a frozen registry for the life of the process, with only a warning. Add `test_serve_startup_with_an_unreachable_store_loads_no_kinds_and_says_so` |
| N3 | MAJOR | S4 section 3.1 "Registry assertion" (`extension_lock`) | CK4 "every registry assertion has a negative and a positive fixture" | `extension_lock` cannot hash "the canonical JSON body of every ... object kind": `ObjectKindDefinition.model_dump(mode="json")` raises `PydanticSerializationError` because `attrs_model` is a class (probed). Spell the body as the registry's own document shape, `{**definition.model_dump(exclude={"attrs_model"}), "attrs": definition.attrs_model.model_json_schema(mode="validation")}`, or have S1b expose the per-definition accessor and name it. Add extension locator kinds to the lock, or record why R45's verifiers are outside it |
| N4 | MAJOR | S4 section 3.1 `run_case` step 8; `src/hippo/store/knowledge.py:435-437` | CK4 "`new` writes a package whose `validate` passes" | `_knowledge_rows("Passage", ...)` raises `ValueError("Unknown knowledge record type")`: `Passage` is a native row, not a knowledge record (probed: `"Passage" in k.RECORD_TYPES` is `False`). Name the reader that already exists: `store._native_rows("Passage", generation_id=receipt.generation_id)` (`generations.py:708`), which `staged_prose.py:169` uses for exactly this question and which returns the golden's own fields, `span_id` and `retrieval_view_id` included. The two public passage readers are the wrong ones: `get_passages(ids, access=None)` and `passages_for_source(source_id, limit=50, ...)` return neither field, are access-filtered through `ACCESS_WHERE`, and the latter is source-scoped and caps at 50. `units.json` is fine once S1b adds `Unit` to `RECORD_TYPES` (S1 section 2); say so |
| N5 | MAJOR | Ruling R59; S4 sections 3.3, 5 S4b, 11 question 3 | R59 | The re-plan predates R59, so `hippo connector enable <kind> <instance_url> [--config <file>]` is in no parser table, no exit-code row, no test list, and section 11 still calls instance creation Task 15's. Add it, and record the ordering it needs: `ensure_connector` writes a `Connector` row whose `kind` the write path checks through `Registry.check_record` (R39; `registry.py:275`, `_RECORD_VOCABULARY["Connector"]`), and the loader cannot have registered that kind yet, because no enabled instance exists. `enable` therefore runs under the connector's own scratch registry (N6), not the loaded one. The check is not live yet: `check_record` has no caller in `src/hippo` today, so this binds S1b's write path and S4b together |
| N6 | MINOR | S4 section 3.1 public API; section 3.3 "Resolving a connector" | API completeness | `_kit_registry(descriptor)` is private, yet sections 3.3 and S6's routes both need "a scratch registry holding the built-ins and that connector's extension". Promote it to `kit_registry(descriptor) -> Registry` in the section 3.1 listing and add it to section 9 "Provides" |
| N7 | MINOR | S4 section 3.1 "The replay connector" step 3 | Implementability | `copy.copy(connector)` then setting `__class__` raises `FrozenInstanceError` for a frozen-dataclass connector, and `TypeError` for an incompatible slotted layout. Use `object.__setattr__(copy, "__class__", subclass)`, and state the one shape requirement connectors must meet |
| N8 | MINOR | S4 section 3.1 "Purity"; S3 section 5.6 | Kit and runtime disagree | `assert_emit_pure` maps only `EmitSideEffect`. An `emit` that succeeds inside the runtime and raises on the kit's re-run (the state-dependent case the assertion exists to catch) leaves `run_case` as an untyped traceback. Wrap both calls: any other exception becomes `ContractViolation("emit_deterministic", ...)` |
| N9 | MINOR | S4 section 3.1 "Scratch runs" (`scratch_store`); section 4 S4a step 5 | R7 evidence | `LadybugStore(path)` takes the production buffer pool (a quarter of RAM, up to 4 GiB), while the measurement R7 asks for runs under the tests' autouse 256 MiB cap (`tests/conftest.py:229`). Pass `buffer_pool_bytes=256 * 2**20` in `scratch_store` so the measured configuration is the shipped one |
| N10 | MINOR | S4 section 3.1 "Fixture layout" (`load_case` refusals) | S2 section 4.6 | A `fetches` entry may set `source_updated_at` without `source_timestamp_original`, which `RawFetch` refuses ("A source timestamp needs its original spelling, and only with a timestamp"). The refusal then reaches the developer as an unnamed `pydantic.ValidationError` mid-replay. Add the pair rule to `load_case`'s refusal list |
| N11 | MINOR | S4 section 3.1 runtime scenario `replayed_page` | Test honesty | With the store clock pinned to one instant, a re-stamped `deleted_at` and a re-verified policy are equal by construction, so the scenario cannot see the two defects (M3, R52) it stands for. Run 3 under `FIXED_INSTANT + timedelta(seconds=1)`, which stays inside R52's half-TTL window, and keep the equality checks |
| N12 | MINOR | S4 section 3.1 runtime scenario `policy_change_mid_page` | Test honesty | "flips between unknown and `known`/`workspace`" does not say which way, and the scaffold's own case starts from `unknown`, which can only widen, while the row cites narrowing. Name the observation sequence in the table and cite the matching half of S3 section 6.3 |
| N13 | MINOR | S4 section 3.5 "Loading" (the restart rule); section 9 R-S1-1 | Completeness | The "already present and equal" comparison covers object kinds, predicates, locator kinds and the two membership sections, but not `families` or `evidence_sources`, so a second load in one process can report `registered=True` for an extension whose families are absent. Name `Registry.locator_kind(name)` (landed, `registry.py:231`) as the locator accessor, since `locator()` returns only the model, and add it to R-S1-1 |
| N14 | MINOR | S4 section 3.5 "Inputs" (`load_connectors`) | "It never raises" | Only the row read is guarded. `load_registry` can still raise (a broken in-repo tree, the built-in install's `RuntimeError`). Wrap the whole call and extend `test_load_connectors_never_raises_when_connector_rows_cannot_be_read` to a second case |
| N15 | MINOR | S4 section 3.5 "Discovery" steps 3-4 | Design section 10 trust | Duplicates are decided in step 4, after step 3 has imported them, so an allowlisted entry point that shadows an in-repo name runs its module code before being discarded. Decide duplicates before import |
| N16 | MINOR | S4 section 3.1 `_kit_registry`; `run_case` step 4 | Named rules | Nothing checks that `descriptor.name` is a registered connector kind, so a connector whose extension omits `connector_kinds` fails at `ensure_connector` with `Unknown connector kind` (R39) instead of a named rule. Check it in `_kit_registry` and report it as the report's `error` |
| N17 | MINOR | S4 section 3.3 non-dry-run `sync` steps 4-7 (m19's list) | Wiring completeness | The steps never obtain the connector object. Spell `connector = load.connector_class(row.kind)()`, and map `ConnectorLoadError` (a built-in kind carries `connector_class=None`, which is every `local`/`git` row under R5) to exit 2 with its own message |
| N18 | MINOR | S4 section 5 `test_sync_of_a_disabled_instance_exits_2` | Test honesty | A kind whose only instance is disabled is not in `enabled_kinds`, so step 4's "kind is not enabled" fires first and the test proves the loader, not R51. Enable a second instance of the same kind, then sync the disabled one and assert S3's refusal message |
| N19 | MINOR | S4 section 9 R-S2-1 code block | m6 | The copied block still reads `PASSAGE_CHAR_BOUND = 1500` with the correction in a comment. Write `6000` (R24, R42), so the quoted contract is the contract |

## Closure of the findings that rejected S4

| Finding | Verdict | Evidence, and what remains |
| --- | --- | --- |
| **B3** the purity guard patches the whole process | **CLOSED** | Section 3.1 "Purity": `purity_guard` is `from .guard import forbid_effects as purity_guard`, S3's per-thread `sys.setprofile` hook (S3 sections 4.1, 10.1). No process-wide patch, no lock, no `*modules`, no `PurityViolation`. `assert_emit_pure` runs both `emit` calls inside `forbid_effects()` on the calling thread, so S6's route and MCP tool are safe under `hippo serve`, which is what B3 asked for. The forbidden set is S3's, widened by m20, so kit and runtime cannot disagree: they are one function. `test_the_purity_guard_is_the_runtime_guard` and `test_assert_emit_pure_leaves_other_threads_alone` cover both halves. N8 is a gap in the surrounding error handling, not in the guard |
| **B4** `run_case` calls a runtime entry S3 does not provide | **CLOSED** | Section 3.1 `run_case` and "Scratch runs" call `sync.sync_connector` with S3 section 4.7's full signature plus R49's `connector_id`, after `ensure_connector(..., enabled=True)`, the replay `probe` and `store_classification`, and read `receipt.generation_id`. `RUNTIME_FAILPOINTS` is gone; `RUNTIME_SCENARIOS` is S3 section 9's five boundary rows on `_ReplayConnector` with S3's labels (`after_fetch`, `after_checkpoint`) and its provider scenarios. `testing` re-exports S3's `record_transport`, `replay_transport` and `ERROR_CLASSES`, and `ContractViolation("provider_recording")` is gone. The order deviation is analysed below and is harmless. N4 is a separate defect in step 8's read-back |
| **M2** the loader is in no plan | **CLOSED** | Section 3.5 is `connectors/loader.py` with `load_registry(*, enabled_kinds, allowlist) -> LoadResult` exactly as R50 words it, built-ins then enabled in-repo packages then allowlisted entry points then `freeze()`, the `web/app.py` lifespan call, and M2's three tests, one of them parametrized over import failure and registration refusal. Merge order puts S4c before every caller (section 7), and R58's split of the `cmd_connector` call to S4b matches section 3.5's own note. Enablement at restart is stated. N1, N2, N13, N14 and N15 are defects inside it |
| **M5** connectors run that no operator enabled | **CLOSED** | Every scratch instance is created with an explicit `enabled=True` because R51 flips the default (section 3.1 `prepare_instance` step 1); a non-dry-run `sync` of a disabled instance exits 2 through S3's entry refusal, and `list` shows kind enablement and instance enablement separately (section 3.3). The landed record already defaults to `enabled=False` (probed: `k.Connector.model_fields["enabled"].default is False`), so R51 changes only `ensure_connector`. N18 is a test-honesty nit on the proof |
| **M12** the capture-side assertions are defined nowhere | **CLOSED** | Section 3.1 "Capture assertions" defines `check_capture(connector, config, *, sample)` with the five rules M12 named, each with a negative fixture in the `VIOLATIONS` table, bounded by `sample`, opening no store and making no HTTP call of its own. The argument is a `SyncConnector`, so S5's lane connectors qualify (R1), and section 9 "Provides" hands it to S5a and S5b. The three quoted S2 validator messages match S2 section 4.6 character for character |
| **M13** nothing tests that `probe` is pure | **CLOSED** | `probe_deterministic` is one of the five capture assertions: `probe` under `FIXED_INSTANT` and `SECOND_INSTANT` must return `Classification`s with equal canonical JSON, with a negative fixture (a `probe` that stamps `clock()` into a warning). The comparison is sound because S2 section 4.1 states that the clock "never enters a `Classification`", and the only other varying field, `registry_fingerprint`, is fixed by the one kit registry both calls run under. CK2's CRITERIA already cite it (`GATES.md:31`) |
| **M15** the replay cannot confirm a deletion | **CLOSED** | `_ReplayConnector.fetch` raises `ProviderNotFoundError(url=..., status=404, attempts=1)` for an id with no `inputs/` file, which is the confirmation S3 section 6.4 condition 4 needs, and `load_case` refuses a missing input only for an `upsert`, so a `delete` or `policy_change` case is legal. The constructor keywords match S3 section 4.3's `ProviderError.__init__` |
| **M16** the scaffold emits an instance key part | **CLOSED** | `connector.py.tmpl` emits `NodeRef(kind="$primary_kind", key={"id": record["id"]})` and `types.py.tmpl` keeps `key_template=("instance", "id")`, which is exactly S2 section 6 step 2's rule: `set(ref.key)` must equal the template's parts minus `INSTANCE_PARTS`, and the kit fills `instance` from the Connector row's `instance_url`. The pinned scaffold output is regenerated and `test_the_scaffold_emits_node_refs_without_an_instance_key_part` pins it. The same templates also carry R46's `extension`, register the connector kind (which `ensure_connector` needs under R39) and sample `probe` through the replayable methods |
| **m6** `TOKEN_BOUND = 1500` | **CLOSED** | Section 3.1 sets `TOKEN_BOUND: Final = base.PASSAGE_CHAR_BOUND` and `test_token_bound_is_the_passage_character_bound` pins it; `passages_within_token_bound` measures with `base.token_count`, the one counter of R11/R26. N19 is a stale literal in section 9's copied block |
| **m17** the offline model copies the fake's algorithm | **CLOSED** | `hashed_embedding` moves into `testing.py` with `EMBEDDING_DIM = 128`, and `tests/fakes/fake_ollama.py`'s `embed_text` becomes a function-local import plus the call, with `DIM` and every other line unchanged, so conftest loads no kit module at collection. The signature matches the source: `embed_text(text) -> np.ndarray` over `DIM = 128` (`fake_ollama.py:23`, `:146-160`). The edit is granted to S4a and the pinned digest is computed on the base tree first |
| **m18** the kit and the binder disagree on edge sources | **OPEN** | `edges_fully_attributed` calls `emit.evidence_class(edge.family, edge.source, edge.metadata_origin)`, which is S2 section 4.5's signature exactly, so the built-in half is closed. The extension half is not: under R40 an extension evidence source carries its class on its `EvidenceSourceDefinition`, which only the registry holds, and `evidence_class` takes no registry, so the kit fires on an edge the binder accepts. Section 9 leaves this conditional ("R40 may give `evidence_class` a registry argument. If so, the kit passes `context.registry`"). **Fix:** make it unconditional. R-S2-9 records `evidence_class(registry, family, source, metadata_origin=None)`, the assertion passes `context.registry`, and S1b exposes the definition accessor that the S1a evidence's open question 1 asks for (`Registry.evidence_source` returns only the name, `registry.py:241`) |
| **m19** the non-dry-run `sync` is under-specified | **CLOSED** | Section 3.3 spells the steps: open the context, `_require(_principal(ctx), "manage_sources")` (`cli.py:236-272`), load the registry, read the row and check its kind, validate the config, exit 2 with a named message when there is no stored classification, then sync as `BuildActor.trusted_local()`. Section 5 carries `test_sync_checks_manage_sources_then_runs_as_the_trusted_local_actor` and `test_sync_without_a_stored_classification_exits_2`. One cosmetic drift: the changelog says "then `BuildActor.trusted_local()`, then exit 2", while section 3.3 builds the actor at step 7, after step 6's exit. Constructing the actor has no effect, so the order is unobservable; make the changelog match the section. N17 is the wiring gap in the same list |
| **m20** guard coverage and pool context | **CLOSED** | Inherited from S3 and correctly relied on: the kit uses S3's forbidden set with m20's five names, and `run_case`'s `use_registry` reaches S3's emit workers only because they run in `contextvars.copy_context()` (section 9 R-S3-4). That dependency is stated where it is used, which is what closes it here; S3 owns the implementation |

## The three questions the brief asks by name

### 1. R49's order against `prepare_instance`'s order: harmless

R49 and B4 list `ensure_connector` and `connector_source`, then the replay `probe` and
`store_classification`, then `sync_connector`. The plan runs `connector_source` last, after
`store_classification`, and says so in the changelog and in section 3.1. The difference is harmless,
for three reasons I checked in S3's text:

- **Neither call reads the other's row.** `connector_source(store, *, connector, partition, name, ...)`
  creates or finds one `Source` of kind `connector` per (connector instance, partition), whose meta is
  `{"connector_id", "partition", ...}` (S3 sections 4.7, 7.3, 13). `store_classification(store, *,
  connector, classification)` writes `Connector.classification_json` and nothing else, and only when
  the canonical JSON differs (R12, R21). No field of either write is an input to the other.
- **The row identity does not move.** `Connector.identity_fields` is `("workspace_id", "kind",
  "instance_url")` (`model.py:204-212`), so the row `store_classification` returns has the same id as
  the row `ensure_connector` created; passing the post-classification row to `connector_source` names
  the same connector.
- **The reordering is load-bearing for the dry run.** `dry_run_sync` takes its partitions from
  `classification.partitions` when `--partition` is absent, so the probe has to precede
  `connector_source`. Under R49's literal order a dry run would have to invent the partition list
  before probing.

Both orders leave the same rows; the plan's order is the one that also serves `sync --dry-run`. R57
already ratifies this deviation, and this re-review confirms it costs nothing. One consequence worth
recording in the plan: `ensure_connector` and `store_classification` are `Connector` writes and each
bumps the authorization epoch (S3 section 13, `authorization.py:113-114`), so `prepare_instance` must
stay outside any build window, which in the kit it is.

### 2. The freeze-once rule, against pytest and against `hippo serve` restarts

**Against `hippo serve` restarts: sound.** `load_registry` freezes `current_registry()`, which in a
server process is the module-level `REGISTRY`, and the plan's reason is right: a `ContextVar` set
inside the lifespan task would not reach request tasks, because each request runs in its own task with
its own context. A fresh process starts from an unfrozen `REGISTRY`, so a restart re-reads the enabled
kinds and re-registers; "enabling a kind takes effect when the process next starts" holds. A second
lifespan in one process is harmless through the restart rule, subject to N13's missing sections. The
operator story is consistent too: with LadybugDB the store lock means `hippo connector enable` (R59,
N5) runs while the server is stopped, so the restart that applies it happens anyway.

**Against pytest: understated, and it bites a sibling slice.** The plan's rule is "a test that
registers into the process registry must do so under `extension_scope()` or
`use_registry(Registry.with_builtins())`". Freezing alone is indeed harmless, and I probed both halves:

```text
REGISTRY frozen: True | has probe_kind: True
second register under extension_scope RAISES: duplicate_name |
  connector kind 'probe_conn' repeats the registered name 'probe_conn'
```

`extension_scope()` clears and restores the frozen flag, so a frozen `REGISTRY` does not break S1a's
own tests, and CK1's built-in equality tests build a fresh `Registry.with_builtins()` and are immune
(`test_registry.py:406-418`). What is not harmless is **population**: once any test leaves an
extension registered in `REGISTRY`, a later test that registers the same extension under
`extension_scope()` fails with `duplicate_name`. That is exactly S3's pattern, which registers
`FIXTURE_EXTENSION` "by tests through `extension_scope()`" (S3 section 11), and exactly what S4b's CLI
tests will do, because `cmd_connector list` and a non-dry-run `sync` call `load_connectors(ctx)` on the
process registry with the fixture connector enabled. In CI's one-process `pytest tests/unit`,
`test_cli_connector.py` sorts before `test_connector_sync.py`, so CK3's suite would fail on test order
alone. The CK4 CHECK line itself is safe: of its four files, the loader's tests install
`use_registry(Registry.with_builtins())` and the kit's and the scaffold's work inside `_kit_registry`.
N1 carries the fix, and the plan's own S4c regression line (web plus registry suites in one process)
proves only the frozen-flag half, because a web lifespan with no enabled rows registers nothing.

### 3. The CK4 CHECK line replacement

The proposed replacement is correct and I recommend applying it as written:

```text
CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_testing_kit.py tests/unit/test_connector_scaffold.py tests/unit/test_cli_connector.py tests/unit/test_connector_loader.py -q -o addopts='' -W error
```

It adds S4c's file to the ledger's three and keeps the fleet's standard invocation. The claim that no
form (b) anyio filter is needed holds, and it is the one claim in the line that could not be settled by
reading: the loader's startup test is the only new test that touches serving machinery, and it reaches
it through `hippo.web.app` and `app.router.lifespan_context`, never a test client. Probed on the root
venv with warnings as errors, including the MCP mount:

```text
starlette 1.6.0 Router has lifespan_context: True
StreamableHTTP session manager started
inside lifespan: ok
lifespan ran with warnings-as-errors: OK
```

The test's other mechanism holds too: `asyncio.run` copies the calling thread's context, so a
`use_registry(...)` installed by the test is visible inside the lifespan (probed: `asyncio.run sees
use_registry: True`). Two notes for the orchestrator: CK4's CRITERIA already carry S4c,
`check_capture`, `probe_deterministic` and the one guard at `a9cbfcb`, so only the CHECK line changes;
and the standing wording proposal for the `remote.py` row is still worth applying, since only `list`
forwards (R7, deviation 4).

## Signature check

Every call sections 3.1 and 3.5 make, against the plan section that provides it or against the landed
S1a code. "Matches" means character for character, allowing for the ruling that amends it.

### From S1a, read in `src/hippo/knowledge/registry.py` at `d0bd052`

| Call in 3.1 or 3.5 | Provider | Verdict |
| --- | --- | --- |
| `Registry.with_builtins()` | `registry.py:268-273`, classmethod, fresh and unfrozen | Matches |
| `register(descriptor.extension, declared_families=descriptor.families)` | `:197`, `declared_families: Iterable[str] \| None`, keyword-only; a bare `str` raises `TypeError` | Matches; a descriptor's `families` is a tuple, so the guard is not tripped |
| `freeze()`, `frozen` | `:209`, `:245-248`; `freeze` is idempotent, `frozen` is a property | Matches, and the loader's "idempotent" claim is the landed behaviour |
| `object_kind`, `predicate`, `locator`, `evidence_source` (`registered_vocabulary`) | `:222`, `:225`, `:228`, `:241`; misses raise `UnregisteredName` | Matches |
| `connector_kinds()` (loader step 4) | `:259`, returns `frozenset[str]`; the built-ins are the eight kinds `backstage, git, github, gitlab, jira_cloud, jira_data_center, local, tuleap` (probed) | Matches |
| `current_registry()`, `use_registry(registry)`, `extension_scope()` | `:617`, `:622`, `:638`; `use_registry` refuses a non-`Registry`; `extension_scope` extends in place and restores the state whole | Matches, and section 3.5's "clears and restores the frozen flag" is exactly `:649` and `:654` |
| `RegistrationError` from `_kit_registry` and the loader | `:32`, a `ValueError` with a `reason` | Matches |
| `extension_lock` over "the canonical JSON body of every fact template, object kind and predicate" | no public serializer exists: `_document`/`_schema` are private (`:543`, `:564`), and `model_dump(mode="json")` raises on `attrs_model` (probed) | **Mismatch, N3** |
| the restart rule's `registry.object_kind(name) == definition`, "likewise for ... locator kinds" | `locator()` returns the model, not the definition; `locator_kind()` (`:231`) returns the definition | **Mismatch, N13** |
| `Registry.check_record` | `:275`, defined and unused in `src/hippo` today | Not called by 3.1 or 3.5; it is the write-path check N5 depends on |

### From S2 (`cdk-s2-contract.md` sections 4.1-4.6, 5, 6), with R46, R48, R53, R60

| Call in 3.1 | Provider | Verdict |
| --- | --- | --- |
| `base.PASSAGE_CHAR_BOUND`, `base.token_count(text)` | section 4.1 (`token_count` is the one counter, R11/R26; the value is 6000 by R24) | Matches; N19 is the stale copy in section 9 |
| `ContractError`, `RegistrationRequired`, `BindRefused` (run_case step 6) | sections 4.1, 4.5: `BindRefused(ContractError)`, `RegistrationRequired(ContractError)` | Matches |
| `ConnectorDescriptor` fields, `.extension`, `.capabilities.derivation`, `.capabilities.inventory`, `.config_model`, `.version`, `.families`, `.kinds` | section 4.1 plus R46 for `extension`; `derivation: Literal["emit", "coordinator_lane"]`, `inventory: bool` | Matches |
| `RevisionInput(partition, artifact, revision, data, config, mapping, registry, span_policy_id)` | section 4.1 plus R48; validators require `registry.frozen` and the content hash | Matches; the kit passes the frozen kit registry, so the R2 validator is satisfied |
| `NodeRef(kind, key)`, `NodeRef.instance` | section 4.1 plus R53 | Matches |
| `SyncConnector`, `Connector` protocols, `Clock` | section 4.1, both `runtime_checkable` | Matches; `check_capture`'s `SyncConnector` argument is the lane-safe one (R1) |
| `ChangePage(partition, changes, next_cursor, complete)`, `SyncCursor(partition, value, scan)`, `Change(ref, operation)`, `ExternalRef(partition, artifact_kind, external_id, provider_revision)` | section 4.1 | Matches, including `scan: Literal["changes", "inventory"]`, which the replay's cursor rule depends on |
| `RawFetch` fields the `fetches` map may set | section 4.1: `content_type`, `canonical_uri`, `provider_revision`, `source_updated_at`, `source_timestamp_original`, `source_timezone`, `source_precision`, `parser` | Matches the eight names; N10 is the missing pair rule |
| `PolicyObservation(ref, state, mode, ...)`, `PolicyObservation(ref=ref, state="unknown")` | section 4.1 | Matches |
| `Classification.partitions`, `PartitionClassification.mapping`, `.warnings` | section 4.1 | Matches; `Classification` carries `registry_fingerprint` and no clock field (section 4.1: the clock "never enters a `Classification`"), which is what makes `probe_deterministic` sound |
| the three quoted validator messages in `check_capture` | section 4.6 | Match character for character: `A change page cannot mix partitions`; `An unknown policy carries no principals; the runtime stores it as deny`; `RawFetch.external_id must equal the requested ref` |
| `keys.check_key_parts(definition, ref)`, `keys.canonical_key(registry, ref, instance=...)` | section 4.2 | Matches |
| `render.render_label`, `render.render_facts(definition, attrs, *, label, key)`, `render.unit_text`, `RenderedText.template` | sections 4.4 | Matches |
| `emit.verify_span(data, span, *, artifact)`, `emit.check_direction_and_ownership(registry, descriptor, predicate, subject_kind, object_kind)`, `emit.policy_record(policy, *, connector, workspace_id, observed_at, expires_at)`, `emit.capture_records(...) -> CapturedRevision(artifact, revision, policy)` | section 4.5 | Match |
| `emit.evidence_class(family, source, metadata_origin)` | section 4.5 | Matches the letter; wrong after R40 (**m18 OPEN**) |
| instance key parts (M16) | section 6 step 2: `set(ref.key)` equals the template minus `INSTANCE_PARTS`, and the kit fills `instance` from `connector.instance_url` | Matches |
| module-level import of `current_registry`/`use_registry` through `hippo.connectors.base` | R60 (S2a re-exports them) | Matches, and it is load-bearing: section 3.1's import rules exclude `hippo.knowledge.registry` at module level, so **S2a must land R60 before S4a** |

### From S3 (`cdk-s3-runtime.md` sections 4.1-4.3, 4.7, 5, 6, 9, 10), with R49 and R51

| Call in 3.1 | Provider | Verdict |
| --- | --- | --- |
| `guard.forbid_effects`, `EmitSideEffect` | section 4.1 | Matches |
| `http.ERROR_CLASSES`, `record_transport(case_dir, inner)`, `replay_transport(case_dir)` | sections 4.3, 10.2; replay raises `ProviderMalformedError` on an unexpected request | Matches; the six canned `error_transport` responses are the six classes S3 section 10.2 classifies |
| `ProviderTransientError(url=..., status=503, attempts=1)`, `ProviderNotFoundError(url=..., status=404, attempts=1)` | section 4.3 `ProviderError.__init__(*, url, status, attempts, retry_after=None)` | Matches |
| `sync.ensure_connector(store, *, workspace_id, kind, instance_url, config, enabled=True)` | section 4.7 with R51's flipped default | Matches; `KIT_INSTANCE_URL` survives `normalize_provider_url` and builds a valid `Connector` (probed) |
| `sync.connector_source(store, *, connector, partition, name)` | section 4.7 | Matches |
| `sync.store_classification(store, *, connector, classification) -> k.Connector` | section 4.7 | Matches |
| `sync.sync_connector(ctx, connector, *, connector_id, config, partition, actor, registry, options, raw_store, embedding_spec, operation_id, should_stop, on_batch, fault_hook)` | section 4.7 plus R49's `connector_id` | Matches, keyword for keyword |
| the five entry refusals the kit must satisfy | section 5: the frozen current registry, `derivation == "emit"`, `type(config) is config_model`, a trusted-local actor, no ambient transaction, and a stored classification | All satisfied: `use_registry(_kit_registry(...))` is frozen and current, `config` comes from `descriptor.config_model.model_validate`, the actor is `BuildActor.trusted_local()`, and `prepare_instance` stores the classification first |
| `SyncOptions(emit_workers=1)`, `SyncOptions().max_fetch_bytes`, `SyncOptions(emit_workers=1, reconcile=True)` | section 4.7 (`max_fetch_bytes = 8_000_000`) | Matches |
| `SyncReceipt.outcome`, `.generation_id`, `.coverage` | section 4.7 | Matches |
| `ConnectorSyncRefused`, `ConnectorContractViolation` | section 4.7 | Matches; S3 section 5.6 maps `EmitSideEffect` and `ContractError` to `ConnectorContractViolation`, which is why run_case step 6 catches it |
| fault labels `after_fetch`, `after_checkpoint` | section 4.7 `FAULT_POINTS`, section 9's boundary table | Matches |
| `on_batch(revision, batch)` in the main thread, outside the guard | section 5.6 | Matches, and it is why the plan's observer only records |
| emit workers under `contextvars.copy_context()` | section 5.6 with m20 | Matches (the dependency `run_case`'s `use_registry` rests on) |

### From existing code, and from S4c's own seams

| Call | Anchor | Verdict |
| --- | --- | --- |
| `embedding_spec(ollama)`, `raw_root(ctx)`, `new_operation_id()` | `managed_activation.py:238`, `:228`, `:163` | Match |
| `RawArtifactStore(root, *, max_object_bytes)`, `put_bytes(value) -> RawArtifact` with `.uri` | `raw_artifacts.py:85`, `:198`, `:43-48` | Match; the resolved-root rule the plan cites is real (`:74-90`) |
| `BuildActor.trusted_local()`, `query_session(ctx, EVERYTHING)`, `AuthorizationChanged`, `EVERYTHING` | `build_authority.py:60`, `query_access.py:126`, `access.py:32`, `src/hippo/access.py:120` | Match |
| `DEFAULT_WORKSPACE_ID`, `OPERATION_ID` | `migrations.py:72`, `source_lifecycle.py:21` | Match; `validate.<case>` with `CASE_NAME`-bounded names stays inside the pattern |
| `store._generation_clock`, `store.ensure_schema()`, `generation_checksums(id)`, `authorization_epoch()` | `generations.py:63-64`, `ladybug.py:535`, `generations.py:966`, `knowledge.py:265`; `FakeStore` has both (probed) | Match |
| `AppContext(config=Config(data_dir=...), store=..., ollama=...)` and `ctx.close()` | `context.py:106-112`, `:516` | Match (the `tests/conftest.py:257-260` shape) |
| `Ollama(base_url, llm_model, embed_model, *, num_ctx=8192, client=...)` | `ollama.py:46-56` | Matches `offline_ollama()`'s call exactly |
| `LadybugStore(path, *, buffer_pool_bytes=None, ...)` | `ladybug.py:337` | Matches; N9 is the shipped default |
| `_knowledge_rows(name, *, generation_id=...)`, `_knowledge_get(name, id)` | `store/knowledge.py:417`, `:519` | Match for the five knowledge-record goldens; **raise for `Passage` (N4)**, and `Unit` needs S1b |
| `store._knowledge_rows("Connector")` unscoped (`enabled_connector_kinds`) | `store/knowledge.py:417`, "Passing no key at all still reads the kind whole" | Allowed |
| `importlib.metadata.entry_points(group=...)`, `importlib.resources.files` | stdlib | Match the plan's stand-in shape (`name`, `value`, `load()`) |
| `app.router.lifespan_context(app)` | Starlette 1.6.0 (probed) | Matches |

## Verdicts

**Section 3.1 (`connectors/testing.py`, S4a): APPROVED WITH CHANGES.** B3, B4, M12, M13, M15, m6, m17
and m20 are closed inside it. Before S4a spawns, apply: N3 (the lock's serialization), N4 (the passage
read), m18 (the registry-taking `evidence_class`), and the nine minors N6, N7, N8, N9, N10, N11, N12,
N16 and N19. None changes the section's structure.

**Section 3.5 (`connectors/loader.py`, S4c): APPROVED WITH CHANGES.** M2 is closed. Before S4c spawns,
apply: N1 (the process-registry rule and S4b's proof line), N2 (load after `startup`), and the minors
N13, N14 and N15.

**Carried to the S4b brief, not gating either section:** N5 (ruling R59's `enable` command), N17 and
N18, and the m19 changelog wording.

**Still owed by siblings, and worth naming in their briefs:** S2a must land R60's `base` re-exports
before S4a (the kit's module-level import rules depend on them); S2b owes m18's signature; S1b owes
`Unit` in `RECORD_TYPES`, the write-path `check_record` call and an evidence-source definition
accessor; S3c owes R-S3-7's four fixture-connector properties.

## What I probed, and what I read

Six assumptions the plans state but no plan proves, checked against the root venv, read-only, in
`/tmp`; each result is quoted where it is used above.

1. `ObjectKindDefinition.model_dump(mode="json")` raises `PydanticSerializationError` (N3).
2. `Passage` and `Unit` are absent from `k.RECORD_TYPES`, so the golden read must go through
   `_native_rows`, not `_knowledge_rows` (N4).
3. A populated, frozen `REGISTRY` makes a later `extension_scope()` registration of the same
   extension raise `duplicate_name`; `Registry.with_builtins()` comparisons are immune (N1).
4. `asyncio.run` carries a `use_registry(...)` installed by the caller into the lifespan.
5. `create_app(ctx).router.lifespan_context(app)` runs to completion with warnings as errors,
   including the MCP mount, on Starlette 1.6.0 (the CK4 CHECK line's filter claim).
6. A fresh LadybugDB answers `_knowledge_rows("Connector")` with `[]` before `ensure_schema`, so N2's
   failure mode is an unreachable store, not a new file. The v7-to-v8 case is inferred, not tested:
   the S4c worker should run the lifespan once against a v7 file.

Read in full: the re-planned `cdk-s4-kit.md`; `cdk-rulings.md` R1-R60; the first review;
`cdk-s1-registry.md` section 5.2; `cdk-s2-contract.md` sections 4-6; `cdk-s3-runtime.md` sections
4, 5, 6, 9, 10, 11, 13; `evidence-s1a.md`; `GATES.md`; `src/hippo/knowledge/registry.py`; design
sections 3, 8, 9. Anchors opened and confirmed: `web/app.py:60-112`, `:163-180`; `cli.py:150-192`,
`:236-272`, `:815`; `store/knowledge.py:417-445`, `:519`; `store/generations.py:55-70`, `:966`;
`store/ladybug.py:337-360`, `:505-560`, `:960`; `store/base.py:244-330`; `store/memory.py:278`;
`knowledge/model.py:204-212`, `:558-570`; `knowledge/raw_artifacts.py:43-95`, `:196-206`;
`knowledge/build_authority.py:55-62`; `knowledge/query_access.py:80-130`;
`ingest/managed_activation.py:160-170`, `:224-245`, `:650-662`; `context.py:104-122`, `:514-526`;
`ollama.py:44-62`; `tests/conftest.py:179-262`; `tests/fakes/fake_ollama.py:23`, `:146-160`;
`tests/unit/test_registry.py:406-418`, `:628-702`; `tests/unit/test_import_order.py:14-30`.
