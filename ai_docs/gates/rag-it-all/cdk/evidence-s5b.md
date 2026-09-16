# CDK S5b evidence: the git connector, the code half of the local connector, and the code parity proof

Worker `backend-developer-16`, branch `wp/s5b`, base `2710262` (the `rag-it-all-tibs` HEAD carrying
S5a, S3b and S4a). Contract: the S5b steps of `ai_docs/plans/cdk-s5-port.md` section 7, with
sections 3, 4.2, 5, 6 and 8 as the contract, amended by the rulings the brief
`ai_docs/handoffs/briefs/cdk-s5b.md` names — R1, R2, R4, R43, R47, R54, R65, R67/M12, R69, R72 and
m9 — and by `ai_docs/gates/rag-it-all/cdk/evidence-s5a.md`. Gate: CK5.

## Commits

| # | Hash | Subject | Files |
| --- | --- | --- | --- |
| 1 | `17d2d64` | Dispatch the managed code build through the local and git connectors and the coordinator lane (CDK S5b) | `src/hippo/connectors/git/{__init__,connector,types}.py`, `tests/unit/test_connector_git.py` (new); `src/hippo/connectors/local/connector.py`, `src/hippo/ingest/code_generation.py`, `src/hippo/ingest/managed_activation.py`, `tests/fakes/connector_parity.py`, `tests/unit/test_connector_local.py`, `tests/unit/test_import_order.py`, `tests/unit/test_connector_loader.py`, `tests/unit/test_layering.py` (modified) |
| 2 | (this commit) | Record the S5b evidence | this file (new) |

`tests/unit/test_layering.py` is outside the brief's "own" list; the orchestrator granted the
one-line `PORTED` append during implementation (see Override 2). Every other file is on the brief's
list, or is the appended line `test_import_order.py` and `test_connector_loader.py` carry by R9 and
the brief's amendment.

## RED

| Stage | Log | Result |
| --- | --- | --- |
| The plan's section 9 S5b Fake line minus the file that does not exist yet, on the unmodified tree | `/tmp/hippo-cdk-s5b-baseline.log` | exit 0, 298 passed, 3 skipped |
| Section 8's S5b tests, the `check_capture` tests, the extended descriptor pin and the three appended lines, before any source change | `/tmp/hippo-cdk-s5b-red.log` | exit 1, 27 failed, 89 passed |

The 27 RED failures are 22 of the 24 cases of `tests/unit/test_connector_git.py`, three of
`tests/unit/test_connector_local.py` (`check_capture` and the two new descriptor-coverage
parameters), the appended `test_import_order.MODULES` entry and the appended `test_layering.PORTED`
entry. The two git cases that pass at RED are regression pins rather than new behaviour:
`test_the_git_connector_kind_stays_a_built_in_of_the_frozen_registry` (R69 already holds, because
S1a registers `git` as a built-in connector kind and S5a's loader rule already skips a directory
named after one) and the loader case, which is `test_connector_loader.py`'s.

**The parity cases fail RED on a stated property, not on a missing module.** Before the switch both
worlds call the same coordinator and would be trivially equal, so `_drive` asserts that a published
runtime build carries `current_registry().fingerprint()`. That is false at `2710262` and true after
the switch, so a parity comparison can never pass by comparing world A with itself. The recorded RED
failure for `test_repository_bootstrap_through_the_runtime_is_byte_identical_to_the_pre_kit_path` is
exactly `the runtime path published without the registry fingerprint`.

## GREEN

Every figure below was measured on the committed tree, after the Ruff formatting pass and after the
descriptor narrowing of Override 3, so no figure is from an earlier working tree.

| Line | Log | Result |
| --- | --- | --- |
| Section 9's S5b CK5 Fake line, verbatim | `/tmp/hippo-cdk-s5b-ck5.log` | exit 0, 325 passed, 3 skipped |
| The same line plus the three files that gained an appended entry (`test_import_order.py`, `test_layering.py`, `test_connector_loader.py`) | `/tmp/hippo-cdk-s5b-green.log` | exit 0, 387 passed, 3 skipped |
| The CD1 line verbatim (`task-5-code-capture/GATES.md:18`) | `/tmp/hippo-cdk-s5b-cd1.log` | exit 0, 133 passed |
| The CD2 line verbatim (`GATES.md:24`) | `/tmp/hippo-cdk-s5b-cd2.log` | exit 0, 169 passed, 2 skipped |
| The CD8 line verbatim (`GATES.md:60`) | `/tmp/hippo-cdk-s5b-cd8.log` | exit 0, 399 passed, 3 skipped |
| Section 9's S5b LadybugDB line: `test_connector_local.py test_connector_git.py` | `/tmp/hippo-cdk-s5b-ladybug-parity.log` | exit 0, 54 passed |
| Ruff `check` then `format --check` over every file this branch touches | `/tmp/hippo-s5b-ruff.log` | exit 0 and exit 0 |

Counts per backend: **Fake** 325 passed / 3 skipped on the CK5 line (298 baseline + 27 new), 133 on
CD1, 169 / 2 on CD2 and 399 / 3 on CD8; **LadybugDB** 54 passed on the two connector files (30 local, 24 git).
**No Neo4j run** — the rulebook forbids one without a written grant, and the plan's section 9 makes
the Neo4j parity of the connector files root-owned. **The CD9 line was not run**: ruling R4 and the
brief make it the orchestrator's to schedule, one acceptance process at a time.

Every command carries `-W error` alone, with no filter appended: no file on any of these lines
imports `fastapi.testclient` at module level, so form (b) of the fleet rules is not needed and no
warning was suppressed. No ini-wide `filterwarnings` was added.

`tests/unit/test_prose_generation.py`, `tests/unit/test_code_generation.py`,
`tests/unit/test_managed_pipeline_activation.py`, `tests/unit/test_managed_code_activation.py` and
`tests/unit/test_code_capture_acceptance.py` pass **unchanged** — none is modified in this branch,
and `git show --stat` proves it.

`HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE` was never set by this worker on any line. The runtime
parity of the acceptance fixture's shape is pinned at N=2 inside
`test_the_capture_fixture_repository_through_the_runtime_is_byte_identical`, which builds
`build_code_capture_repository(files_per_language=2)` itself (ruling R4).

## The parity comparison, extended to the code worlds

`tests/fakes/connector_parity.py` keeps S5a's shape — two worlds, each on its own data directory and
its own store of the selected backend, run one after the other, with the store clock, `new_id` in
every module that binds it and the operation identity pinned. S5b adds:

- `pre_kit_code_build` and `_pre_kit_build_code`: `managed_activation._run_code_build:710-746` and
  `_build_code:749-779` copied verbatim from `2710262`, including the clone, the head read and the
  `finally` that discards the checkout. `repos.clone_repo` is reached through the module attribute,
  so one `clone_from` patch serves both worlds;
- `make_origin` / `commit_refresh` / `head_revision`: **each world builds its own origin
  repository**, so world A's refresh commit can never be present when world B bootstraps. The
  commit dates are pinned by `test_code_generation._commit`, so two origins built from the same
  files carry the same commit ids — measured directly before any code was written:
  `make_checkout` twice gives `b029412b013ba8c82e9d1c71b88d2597363b28a7` both times, and
  `build_code_capture_repository(files_per_language=2)` twice gives
  `85c341fdacc7f5c197113ac4939eb3ac9a79f336` both times. Without that the two worlds could not
  agree on `head_revision`, which enters generation identity;
- `archive_bytes()` / `code_file_bytes()`: the `ARCHIVE` and single-code-file fixtures of
  `test_managed_code_activation.py:59-80`;
- `runtime_code_build`, which is `runtime_prose_build`: `run_managed_build` routes a code source to
  `_run_code_build` itself, so world B has one call for both families.

`published_snapshot` is unchanged and the nine comparisons of plan section 6 stand as S5a recorded
them. The code worlds exercise the parts of it S5a could not: `native` and `relationships` now carry
`Symbol`, `DataObject` and `Commit` rows, and the closure carries the history bindings.

**Result: the only difference the comparison finds anywhere is `Generation.registry_fingerprint`.**
`test_registry_fingerprint_is_the_only_generation_field_that_differs_on_the_code_lane` states it as
an assertion over the whole row dump, and the seven byte-identity cases (repository bootstrap,
repository refresh, archive, code file, the capture fixture at N=2, the crash-and-resume pair, and
the dispatch case) compare the full snapshot.

## The registry-fingerprint seam on the code lane

`build_code_source` gains `registry_fingerprint: str | None = None`, validated as an explicit
nonempty string or omitted, exactly as `build_plain_source` validates it. It is passed to
`_install`, which is **the one place the code lane writes a `Generation` row**
(`code_generation.py:654`, the only `put_knowledge(gen…)` in the lane — verified by grep over
`code_generation.py`, `build_run.py` and `staged_code.py`).

Plan section 3.2 says the coordinator "sets the fingerprint on a generation it creates and adopts
the stored value on a reclaim". Both halves land at that single write:

- **set**: the `existing is None` branch writes `gen.replace(coverage_json=…,
  registry_fingerprint=registry_fingerprint)`;
- **adopt**: the reclaim branch writes nothing at all, so the stored row keeps what it was published
  with.

The merged bundle's own generation is left without the field, which is precisely the shape ruling
R47 already landed for: `staged_code._local:310-316` normalizes `registry_fingerprint` away on both
sides of its "persisted generation differs from accepted preparation" comparison, because "the
merged bundle's generation is re-settled from the inputs, so it carries no `registry_fingerprint`
while the persisted row does". No `knowledge/` file changed.

### Ruling R72: the adoption branch **is** falsifiable on the code lane

S5a found the same branch unfalsifiable on the prose path and asked S5b to check the code lane,
where a reclaim may rewrite the row. It does not rewrite it — and that is now *proved* rather than
assumed, by three mutations, each run over `tests/unit/test_connector_git.py` on Fake and then
reverted:

| Mutation | Log | Result |
| --- | --- | --- |
| Drop `registry_fingerprint=registry_fingerprint` from `_install`'s write (the **set** half) | `/tmp/hippo-cdk-s5b-mutation-set.log` | exit 1, **10 failed**, 14 passed |
| Add a reclaim branch that re-puts the bundle's generation with the incoming fingerprint (the **adopt** half, coarse) | `/tmp/hippo-cdk-s5b-mutation-adopt.log` | exit 1, **2 failed**, 22 passed — `ValueError: Immutable record already exists with different contents` |
| Add a reclaim branch that re-puts **the stored row with only the fingerprint replaced** (the **adopt** half, isolated) | `/tmp/hippo-cdk-s5b-mutation-adopt2.log` | exit 1, **exactly 1 failed**, 23 passed — the same `ValueError` |

The third mutation is the answer R72 asked for. It changes nothing but the fingerprint, so the
same-registry resume (`test_a_resumed_code_build_through_the_runtime_equals_the_pre_kit_resume`)
still passes, and exactly one case fails:
`test_a_reclaimed_code_generation_keeps_its_stored_registry_fingerprint`, with
`store/knowledge.py:795`'s "Immutable record already exists with different contents". **On the code
lane, adopting the incoming fingerprint instead of the stored one is a store-level refusal, not a
silent difference.** That is the opposite of S5a's prose finding, and it is why the adoption is
implemented as "never re-put a stored generation" rather than as a `replace`.

The test that pins the property registers a probe artifact kind on its other registry first, because
a bare `Registry.with_builtins()` fingerprints identically to the process registry (R72), and
asserts the difference as a precondition before it asserts anything about the stored row.

## The two connectors

### `connectors/git/` (new)

| Method | What it does |
| --- | --- |
| `list_changes` | `repository_descriptor(config.url)` first, so a URL carrying a token refuses before any clone exists; `repos.clone_repo(url, checkout, depth=…)` through the module attribute when the checkout is absent; `repos.head_revision(checkout, timeout=…)`; then `walk_tree` with the dispatch's rails. One `upsert` per walked input in walk order, `provider_revision=head` on every ref, one coverage warning per exclusion reason, `complete=True`, no cursor |
| `fetch` | the walked file's bytes from the checkout, echoing `ref.provider_revision`, under `source:<id>/<logical path>` |
| `fetch_policy` | the `mode="workspace"` observation the code lane mints (`code_generation._policy:588-599`) |
| `probe` | one partition `source:<id>`, family `code`, and the history capability **observed from the checkout** — see Override 4 |

`descriptor`: `name="git"`, `version="git-v1"`, `families=("code",)`, `predicates=()`,
`credentials=()`, `parsers=()`, `capabilities.derivation="coordinator_lane"`, `history=True`,
`inventory=True`. `descriptor.validate_against(current_registry())` passes: every declared name is a
built-in. `GitSourceConfig` has no field whose name contains `credential` (ruling R65).

### `connectors/local/` (the code half)

`list_changes` and `_member` no longer raise `NotImplementedError`. For an archive or a code file
they answer `repo_capture.walk_tree` with the same rails `code_generation._capture:313-319` uses, so
the inventory the connector reports and the inventory the lane derives from are the same walk of the
same saved bytes. `_member` now returns `bytes` rather than a `Path`, because an archive member's
bytes come out of the walk (`ByteInput`) while a file's are read from disk (`FileInput`).

**Re-walking is also the traversal guard.** Both connectors answer a reference only when the walk
itself produced that logical path, so a `..` or an absolute external id reaches nothing and raises
`base.ContractError` instead.

### What a build actually publishes, measured

Read from the published generation of each world (objects are the distinct `KnowledgeObject` kinds
the generation's member `ObjectObservation`s name, per S4a override 6):

| World | Object kinds | Artifact kinds | Locator kinds |
| --- | --- | --- | --- |
| `repo` (`make_checkout`) | `column`, `commit`, `file`, `repository`, `symbol`, `table` | `file`, `history_event`, `manifest`, `repository` | `field`, `file_lines` |
| capture fixture at N=2 | `column`, `commit`, `file`, `repository`, `symbol`, `table` | `file`, `history_event`, `manifest`, `repository` | `field`, `file_lines` |
| `archive` | `file`, `repository`, `symbol` | `file`, `manifest`, `repository` | `field`, `file_lines` |
| code `file` | `file`, `repository`, `symbol` | `file`, `manifest`, `repository` | `field`, `file_lines` |
| `text` (prose) | none | `file`, `manifest` | `file_lines` |

## Overrides and deviations

**Override 1 — no re-export in `connectors/sync.py`.** Ruling R3 ratified "S5b makes the one-line
dispatch or re-export in `connectors/sync.py` after S3 merges", but the brief's own-list does not
name the file and does not cite R3. Asked before implementing; the orchestrator's answer: **dropped,
R3 is superseded** — lane connectors have no `Connector` row in v1 (R5), so `hippo connector sync`
never targets them and `managed_activation` is their only dispatcher. `connectors/sync.py` is
untouched. Plan open question 2 is closed by that answer.

**Override 2 — `tests/unit/test_layering.py`'s `PORTED` gained `connectors/git/connector.py`.** S5a
owns the file and the brief does not grant it. Asked at the same time; **granted** by the
orchestrator as a one-line append, named here as the answer required. Without it the R54 pin would
not cover the new connector at all, and a `from ...ingest import managed_activation` inside
`connectors/git/connector.py` would go unnoticed.

**Override 3 — the local descriptor is narrowed: `commit` and `history_event` are dropped.** Plan
section 4.1 makes the local declaration the superset both lanes write, and section 4.2 records that
it carries `history_event` "as for local". Ruling R72 says S5b extends the pin to the archive and
code worlds **and may narrow the declaration**, and the ruling wins. Both are structurally
unreachable for a local source: a commit and a history event come from `read_history`, which
`code_generation._history:397` runs only when `tree.is_repository`, and a `LocalSourceConfig` is
never a repository (`kind` is `text`, `file` or `archive`, and `_run_code_build` builds
`CodeTreeInput(root=saved, kind=source["kind"])` with no `repository`). The measurement table above
confirms it for both code worlds. `test_local_descriptor_covers_every_record_the_lanes_write` now
pins both halves: the published sets are covered by the declaration, and neither `commit` nor
`history_event` appears in either.

`resource` **stays** in both declarations although no fixture publishes it, including the capture
fixture at N=2 with its YAML config files. It is reachable rather than dead:
`code_binding.DATA_OBJECT_KINDS:88-93` maps a Mongo collection and the two Cypher kinds onto
`resource`, and an archive may hold either. Narrowing it would be a fixture artifact, not a fact
about the lane. The same reasoning keeps `table` and `column` on the local descriptor: an archive
holding `.sql` publishes them, and the fixture archive simply does not.

**Override 4 — `GitConnector.probe` observes that the checkout is a clone, and nothing else.** Plan
section 4.2 says probe reports "the history capability, observed from the checkout". It reads
`(checkout / ".git").exists()` and reports `capabilities.history` from it; it does not clone, and it
does not walk the tree. Two reasons, both binding: the kit's `probe_deterministic` (review M13, run
by `check_capture`) calls `probe` twice an instant apart and requires identical dumps, and walking
could raise `CaptureRefused` from a method whose contract is a classification. A probe on an absent
checkout reports `history=False` and the `checkout_absent` page warning rather than refusing, which
`test_git_probe_reports_the_code_family_and_the_history_capability` pins on both sides of a
`list_changes` call.

**Override 5 — `repository_descriptor(url)` is called twice on a repository build.** Once in
`_run_code_build`, before `present`, because a credentialed URL must refuse at exactly the point it
refused before the port and because the dispatch needs the descriptor for `CodeTreeInput`; and once
inside `GitConnector.list_changes`, because plan section 4.2 step 1 makes it the connector's own
first act and a connector used outside this dispatch must still refuse. It is a pure function of the
URL, so the second call cannot disagree with the first.

**Override 6 — `coverage_warnings` is eight duplicated lines, not a shared helper.** Both connector
packages define it identically, with a comment in each naming the other. A connector package is
self-contained by design (design section 9); a third-party connector could not import
`connectors.local` either, and `connectors/base.py` is S2's file, which this brief does not grant.
The warning spelling `excluded.<reason>:<count>` is pinned by the two `list_changes` tests.

**Override 7 — the resume parity worlds run at `batch_size=1`.** At the reviewed batch size the
whole `make_checkout` fixture is one staged write (measured: 1 `_write_batch` call, 11 revision
members), so no crash can leave a resumable attempt that reports a nonzero `resumed_from_batches`.
`small_batches` patches `managed_activation.code_build_options`, which **both** worlds read their
options from, to `replace(real(ctx), batch_size=1)` — 127 one-record batches for this fixture, with
the crash at batch 20. `batch_size` is an operational option `CodeBuildOptions` never hashes into
generation identity (plan section 8.3), so the comparison is unaffected and both worlds get the same
write plan.

**Override 8 — `GitSourceConfig.git_timeout_seconds` is a `float`, as plan section 4.2 declares it,
while `CodeBuildOptions.git_timeout_seconds` is an `int`.** The dispatch passes the int and pydantic
widens it; `repos.head_revision` uses it as a `subprocess` timeout, which accepts either.

**Deviation carried from S5a, not introduced here — `ConnectorCapabilities.inventory` is `True`.**
S5a's Override 2 flagged that its `check_capture` test would be the first thing to read it. It is
read now, and it is right: `check_capture` is green on both connectors with `inventory=True`, and
`run_coordinator_lane` refuses a page that is not `complete`, which is exactly what the field
declares.

## The rulings, checked

| Ruling | Where it is satisfied | Pinned by |
| --- | --- | --- |
| R1 — coordinator lanes; `capabilities.derivation="coordinator_lane"` | `git/connector.py` `DESCRIPTOR`; the code branch of `_run_code_build` | `test_git_descriptor_declares_no_templates_parsers_predicates_or_emit` |
| R2 — S5b owns `code_generation.py` | one keyword argument, one `_install` argument, one write | `test_build_code_source_defaults_registry_fingerprint_to_none` |
| R4 — runtime parity at N=2; CD9 is the orchestrator's | `build_code_capture_repository(files_per_language=2)`; no CD9 run, no `HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE` set | `test_the_capture_fixture_repository_through_the_runtime_is_byte_identical` |
| R5 — no `Connector` or `SyncState` row | the code lane writes neither | `test_the_runtime_code_path_writes_no_connector_or_sync_state_row_and_no_connector_id` |
| R43 — `kind="connector"` refused by dispatch | unchanged from S5a, on the line before the code branch | S5a's `test_a_connector_source_reindex_is_refused_by_dispatch` |
| R47 — S1b-fix owns the fingerprint-tolerant comparisons | `staged_code.py` untouched; the seam writes where its comment already expects the difference | the resume and reclaim cases pass |
| R54 / M11 — one `ingest` → `connectors` edge | `managed_activation` alone imports the kit; `git/connector.py` imports `ingest.readers`, `ingest.repos` and `ingest.repo_capture`, never the dispatch or the pipeline | `test_the_ported_connectors_never_import_the_dispatch_or_the_pipeline[connectors/git/connector.py]` |
| R65 — no config field named `credential…` | `GitSourceConfig` has none; a credential cannot reach it, because `repository_descriptor` refuses a credentialed URL | `test_git_descriptor_declares_no_templates_parsers_predicates_or_emit`, `test_git_list_changes_refuses_a_credentialed_url_before_cloning` |
| R67 / M12 — `check_capture` on both connectors | `testing.check_capture(…, sample=8) == ()` for `git` and for the local `text`, prose `file`, `archive` and code `file` configurations | `test_the_git_connector_passes_check_capture`, `test_the_local_connector_passes_check_capture` |
| R69 — `git` stays a built-in loader entry | no loader change was needed: S5a's rule already skips an in-repo directory named after a built-in kind | `test_a_package_named_after_a_built_in_kind_keeps_its_built_in_entry` (extended to `git`), `test_the_git_connector_kind_stays_a_built_in_of_the_frozen_registry` |
| R72 — falsify the fingerprint branch; extend the descriptor pin; extend rather than duplicate `connector_parity.py`; replace the `NotImplementedError` branches | the three mutations above; the parametrized descriptor pin; `connector_parity.py` extended in place; both branches replaced | the whole `test_connector_git.py` suite |
| m9 — `SyncConnector`, `current_registry()`, a `mode="workspace"` observation | `GitConnector` is a `SyncConnector` and not a `Connector`; `registry=current_registry()` in both code branches; `fetch_policy` | `test_git_fetch_policy_equals_the_policy_the_code_lane_mints`, `test_add_repo_and_code_uploads_dispatch_through_the_code_lane` |

**Negative fixtures for the capture assertions (R67 / M12).** The kit already ships exactly one per
assertion — S4a's `VIOLATIONS` table in `tests/unit/test_connector_testing_kit.py` has 25 entries
for 25 names, including all five capture names, and
`test_every_assertion_has_exactly_one_negative_fixture` pins the count. So none was added. Each
`check_capture` test instead ends with a one-method subclass of the real connector whose `fetch`
answers the wrong `external_id`, and requires the fired set to be exactly `{"fetch_matches_ref"}`,
which proves the rules run against *these* connectors rather than passing vacuously.

## What landed

| File | Change |
| --- | --- |
| `src/hippo/connectors/git/connector.py` (new) | `GitSourceConfig`, the `git` descriptor, and `probe` / `list_changes` / `fetch` / `fetch_policy` over one managed checkout |
| `src/hippo/connectors/git/types.py` (new) | `EXTENSION = TypeExtension()` — the connector registers no vocabulary (ruling R46) |
| `src/hippo/connectors/git/__init__.py` (new) | the package marker, exporting `Connector` for the kit's package convention |
| `src/hippo/connectors/local/connector.py` | the archive and code-file branches of `list_changes` and `_member`; `_inventory`, `coverage_warnings`, `_ref`; the descriptor narrowing of Override 3 |
| `src/hippo/ingest/code_generation.py` | `build_code_source(..., registry_fingerprint: str | None = None)`; `_install` records it on the one generation write and the reclaim branch adopts by writing nothing |
| `src/hippo/ingest/managed_activation.py` | both code branches of `_run_code_build` are now lanes; `_build_code` gains `registry_fingerprint`; the `hippo.connectors.git.connector` import; the module docstring records the code hand-off |
| `tests/fakes/connector_parity.py` | the code worlds: `pre_kit_code_build`, `_pre_kit_build_code`, `runtime_code_build`, `clone_from`, `make_origin`, `commit_refresh`, `head_revision`, `archive_bytes`, `code_file_bytes` and the code fixture constants |
| `tests/unit/test_connector_git.py` (new, 24 cases) | section 8's fifteen S5b names, the `check_capture` case, and eight that state rules section 8 leaves unnamed (fetch policy, probe, the built-in registry entry, the no-rows case, and the fingerprint-difference case) |
| `tests/unit/test_connector_local.py` | `_pre_kit` picks world A's branch by the saved Source kind; the descriptor pin is parametrized over `text`, `archive` and `file`; the local `check_capture` case |
| `tests/unit/test_import_order.py` | `"hippo.connectors.git.connector"` appended to `MODULES` |
| `tests/unit/test_layering.py` | `"connectors/git/connector.py"` appended to `PORTED` (Override 2) |
| `tests/unit/test_connector_loader.py` | the granted `git` case beside S5a's `local` case (R69) |

## Findings for the merger and for S6

1. **The fingerprint-adoption branch is observable on the code lane**, which answers S5a's open
   question 5 and R72's instruction. See the mutation table above. Nothing needs to change; the
   finding is that the implementation shape (never re-put a stored generation) is load-bearing and
   not merely tidy, because `put_knowledge` refuses the alternative.
2. **Both connectors walk the tree that the coordinator's capture then walks again.** A repository
   build clones once and walks twice: once in `GitConnector.list_changes` for the inventory and once
   in `capture_repository_inputs`. An archive is read twice for the same reason. This is what plan
   sections 4.1 and 4.2 specify — the connector owns the inventory, the coordinator owns capture —
   and it is what keeps the published bytes identical. It is recorded here because it is the one
   cost the port adds that a reader will notice, and because a later slice that moves capture behind
   `fetch` would remove it.
3. **`resource` is declared by both connectors and published by no fixture** (Override 3). A case
   with a Mongo or Cypher schema file would exercise it; none exists in the repository today.
4. **The Neo4j branch of `connector_parity._store` is still written and unexercised.** S5a recorded
   it; nothing here changed it, and the rulebook forbade running it.
5. **`test_connector_local.py` now imports `published_vocabulary` from `test_connector_git.py`.** The
   helper reads a published generation's object, artifact and locator kinds and both descriptor pins
   need it. A merger splitting the two files again should move it rather than copy it.

## Open questions for the orchestrator

1. **CD9 at N=8 and the Neo4j parity of the two connector files are unrun here**, by ruling R4 and by
   the rulebook. The CK5 EVIDENCE line needs both before the gate is complete.
2. **Plan section 9's proposed CK5 CRITERIA rewording** ("dispatch through the kit's connector
   interface … and the coordinator lane, whose derivation half is the reviewed coordinator") is not
   applied here: the ledger is the orchestrator's.
3. **Override 3's narrowing is a declaration change a SPEC reviewer may want to see**, since plan
   section 4.2 states the opposite in passing. The code and the measurement both support the
   narrowing; the ruling grants it; the plan sentence is now stale.
