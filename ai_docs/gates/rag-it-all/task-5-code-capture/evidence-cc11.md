# CC11 evidence: acceptance runs, the CD9 fixture and ledger amendments

Worker `backend-developer-24`, 2026-09-13. Branch `wp/cc11`, worktree `.worktrees/cc11`, base
`9a474e4` (CC1–CC10, cc1fix, lbfix and pa8close/2 merged). Root `rag-it-all-tibs` is at `492cb4c`,
which changes only CD2's CRITERIA line in `GATES.md`. Every ledger line quoted below is root's
text. Contract:

- brief `ai_docs/handoffs/briefs/cc11-acceptance.md`, including its prior-work addendum;
- plan sections 8.3, 12 and 13;
- design review m1, m2, question 10 and the CRITERIA amendments it lists;
- gates CD9 and CD10.

No gate checkbox is set here, and no `EVIDENCE:` line is written.

## Orchestrator rulings taken during this slice (2026-09-13)

| Question | Ruling |
| --- | --- |
| Whole-table knowledge reads make a code build quadratic (finding 1) | (a): a store fix slice scopes the reads. CD9 runs at the full fixture size after it merges, and the scale probe is its RED. |
| A published code generation projects no arrows (finding 2) | (i) now: the acceptance test asserts the native `DEFINED_IN` contract. (ii) a projection fix slice projects `DEFINED_IN` and `CODE_EDGE` from the selected generation's native rows. After it merges, CD9 asserts projected arrows equal the native rows. CODEPROJ merged at `955cc11`, serving `MODIFIES` and `PRECEDES` too. |
| How `wp/cc11` picks up the fixes | (b): once the orchestrator reports that both kscope and codeproj have merged, run `git merge rag-it-all-tibs` into `wp/cc11` (a merge commit, no rebase), add the post-fix assertions, and run CD9 on LadybugDB |
| `status._with_code_edges`' docstring still says the projection serves no native `CODE_EDGE` arrow | Fix it in the first commit after that merge, with no separate branch. `status.py` is released to this slice for that change. |
| The two parity differences CODEPROJ pinned | Recorded in the plan appendix's §4 projection paragraph |
| Both fixes merged (`rag-it-all-tibs` at `df05bac`) | The merge ran as authorized: merge commit `4edce57`, docstring fix `cd358d4`, post-fix assertions `baf2d8c` |
| Neo4j parity run 6 failed `test_code_generation.py::test_no_log_record_source_row_or_receipt_carries_a_path_url_or_source_text`: the driver logs Cypher parameters at DEBUG | The test now checks only records from hippo's own loggers (`f31090c`). Capping the `neo4j` logger at INFO is recorded as a finding for Task 16 or a follow-up |

## Gate runs

All runs are from `.worktrees/cc11` with `.venv/bin/python` (3.12.11, `mcp==2.1.1` pinned). Each
command is the ledger's CHECK line verbatim, output captured to the log with `echo EXIT $?`. No
line needed the AnyIO filter (form (b)). CD5 already names `tests/unit/test_managed_input_binding.py`
(m1 applied), so the line ran as written.

| Gate | Backend | Command | Result line | EXIT | Log |
| --- | --- | --- | --- | --- | --- |
| CD1 | Fake | `GATES.md:18` verbatim | `93 passed in 12.32s` | 0 | `/tmp/hippo-cc11-cd1.log` |
| CD2 | Fake | `GATES.md:23` verbatim | `113 passed, 2 skipped in 7.60s` | 0 | `/tmp/hippo-cc11-cd2.log` |
| CD3 | Fake | `GATES.md:28` verbatim | `152 passed in 1.37s` | 0 | `/tmp/hippo-cc11-cd3.log` |
| CD4 | Fake | `GATES.md:33` verbatim | `95 passed in 1.55s` | 0 | `/tmp/hippo-cc11-cd4.log` |
| CD5 | Fake | `GATES.md:38` verbatim | `89 passed in 0.71s` | 0 | `/tmp/hippo-cc11-cd5.log` |
| CD6 | Fake | `GATES.md:43` verbatim | `91 passed in 8.30s` | 0 | `/tmp/hippo-cc11-cd6.log` |
| CD7 | Fake | `GATES.md:48` verbatim | `83 passed in 10.79s` | 0 | `/tmp/hippo-cc11-cd7.log` |
| CD8 | Fake | `GATES.md:53` verbatim | `306 passed, 3 skipped in 53.58s` | 0 | `/tmp/hippo-cc11-cd8.log` |
| CD9 | LadybugDB | `GATES.md:58` plus `tests/unit/test_code_capture_acceptance.py` | PENDING: waits for the store fix slice (finding 1) | — | `/tmp/hippo-cc11-cd9.log` |
| CD10 | — | `GATES.md:63` verbatim | `All checks passed!` / `10 files already formatted` | 0 | `/tmp/hippo-cc11-cd10.log` |
| Full Fake suite | Fake | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"` | PENDING | — | `/tmp/hippo-cc11-full-fake.log` |

CD10 counts ten files: the eight Python modules (`build_run.py` among them) plus the plan and the
ledger. So `EXPECT: 10 files already formatted` is right, not 11. It stays right after this slice's
plan appendix: `ruff format --check` on the plan prints `1 file already formatted`.

## The CD9 fixture and acceptance test

### Files

- NEW `tests/fakes/code_capture_repo.py`: `build_code_capture_repository(parent, *,
  files_per_language=48) -> CodeCaptureRepository`, the checkout plus its expected capture
  (`files`, `languages`, `accepted`, `excluded` by reason, `prose`, `unparsed`, `commits`, `head`,
  and `refresh()` for a fifth commit). It sits beside `tests/fakes/code_fixture.py`, because
  `tests/fixtures/` holds static data and is not a package.
- NEW `tests/unit/test_code_capture_acceptance.py`: a determinism test for the fixture and one CD9
  scenario. `HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE` overrides the size for scratch runs only;
  the ledger's line runs the default.

### The fixture at its default size (48 files per language)

| What | Count |
| --- | --- |
| Accepted files | 270, 55,478 bytes |
| Python, TypeScript, Go, C#, Rust | 48 each |
| SQL schemas | 12 |
| YAML config files | 12 |
| Plain prose (`README.md`, `docs/architecture.md`) | 2: captured, `openie_reasons = prose_extraction_deferred` |
| Extensionless and known-name text (`NOTES`, `LICENSE`, `Makefile`, `go.mod`) | 4: captured, `unparsed` (ruling 11) |
| `ignored_path` | `.git`, untracked `web/node_modules/` |
| `too_large` | untracked `data/huge.json`, 2,100,015 bytes > `readers.MAX_FILE_BYTES` |
| `binary` | `data/blob.json` |
| `unsupported_language` | `assets/logo.png` |
| `symlink` | `fleet_link.py`, committed |
| Commits | 4, with pinned identities and dates (HEAD `4c3d2aa22ffb5f4c16d2adf084a75552e6185640`); `refresh()` adds a fifth |
| Build time | 0.38 s |

The fixture does NOT reach the 50,000-symbol ceiling. At 2 and 8 files per language the coverage
records 41 and 173 symbols. The CD1 linearity proof at the ceiling is CC2's synthetic Fake test
(`test_generation_scoped_reads.py::test_sealing_at_the_symbol_ceiling_completes` and
`::test_sealing_is_linear_in_the_generation`; design review M5). The index-backed half of the CD1
bound is proven on Neo4j (parity run 2), not on LadybugDB, which has no secondary-index DDL (M4,
`evidence-cc2.md`).

### What the scenario asserts, in order

1. **Crash.** A bootstrap crashes after three write batches. The generation is `failed`, there is
   no active pointer, and the staged members are retained.
2. **Reopen during staging.** The store is closed and reopened: a new `LadybugStore` on the same
   path, or a new `Store` on the same Neo4j database. The Fake store has no second life, so on Fake
   this step is skipped. What must survive is compared as one record: source pointers, the managed
   flag, `build_fencing_token`, `active_build_id`, the `Generation` record and its coverage, revision
   and evidence membership, native bindings, manifests, the build jobs, every native row, the
   relationship representation and the raw URIs. The source still serves the legacy lane.
3. **Resume.** The same operation resumes the same generation and publishes it, with
   `resumed_from_batches >= 1`. It adopts the stored `created_at`, and every staged observation
   member is still a member.
4. **Reopen after publication.** The published state is identical; the seal validates and the
   checksums equal the manifest's. Every accepted file's raw object reads back byte-identical.
5. **Exact membership.** The accepted file artifacts equal the fixture's accepted set, and each
   exclusion reason is counted. The OpenIE reason of every prose, unparsed and walker-language file
   is as expected. The walk is first-parent and the commit count is exact.
6. **Projection.**
   - The selected pair is the published generation, and symbol, commit and data nodes are present.
   - Every code node carries structural support, either a `DEFINED_IN` arrow or a sidecar.
   - Every `StructuralCodeEvidence` row names the generation and source, and its
     `original_span_ids` equal exactly the spans of that object's selected observations.
   - Every `file_lines` citation's `start` and `end` are inside the fixture file, and its text equals
     those lines.
   - Every symbol's spans are `file_lines`.
7. **Native `DEFINED_IN` support.** Every native `DEFINED_IN` row joins a bound native node of the
   generation to a passage of the generation whose original spans include the node's binding span,
   and every bound symbol has at least one. This is the ruling (i) contract.
8. **Verified dense dispatch.** `retrieval_session` and `dense_session` both route `verified`.
   `require_dense` passes, the dense vectors belong to the published generation, and `/api/chat` is
   never called.
9. **Retire under a live snapshot.** With `query_session` held on G1, a refresh (one edited Python
   file) publishes G2. `held.validate()` passes, G1 is `retired`, and the held graph still selects
   G1 with its exact code-node and passage sets. A new session selects G2.
10. **Reopen after the refresh.**
    - G1's seal validates, and its checksums, membership, bindings, manifests, native rows,
      relations and raw objects equal the published snapshot.
    - Every unchanged file's revision is one record shared by G1 and G2, with its first
      `observed_at` kept.
    - The prior commits are reused as well.
11. **Ceilings (plan section 8.3).**
    - The options keep the reviewed defaults: `CODE_MAX_FILES`, `CODE_MAX_SYMBOLS_PER_SOURCE`,
      `MAX_CHUNKS`, and the 64 MiB batch payload.
    - Each generation's coverage is within them, with symbols far below the ceiling, and
      `code_truncated` is false.
    - Only the lease is lengthened (3,600 s). It is operational, and a slow LadybugDB seal must not
      become a lost fence.
12. **The CD1 bound, as CC2 proves it.** Across all three builds:
    - there is no whole-table native read;
    - every relationship read is scoped;
    - no write batch does more than 32 native reads. The measurement on this fixture was at most
      20 per batch at 2 files per language and at most 12 at 8
      (`/tmp/hippo-cc11-accept-probe-2.log`, `-8.log`).

The HTTP runtime is `test_code_generation.Runtime`, which fails the test on any HTTP call made
inside a store transaction and on any chat request.

### RED and GREEN

| Run | Result | Log |
| --- | --- | --- |
| RED, Fake, 2 files per language | `2 failed`: `The multi-hundred-file code capture fixture builder is missing` | `/tmp/hippo-cc11-red.log` |
| GREEN, Fake, 2 files per language (before the per-batch bound was added) | `2 passed in 14.82s` | `/tmp/hippo-cc11-green-small.log` |
| GREEN, Fake, 2 files per language (final file at `ae24a54`) | `2 passed in 12.44s` | `/tmp/hippo-cc11-green.log` |
| Fake, default size | PENDING (inside the full Fake suite) | `/tmp/hippo-cc11-full-fake.log` |
| LadybugDB, CD9 line | PENDING: after the store fix slice | `/tmp/hippo-cc11-cd9.log` |

## Measurements behind findings 1 and 2

The probes are uncommitted scratch files, moved out of `tests/` so the full suite runs the brief's
exact line. They live in `/tmp/hippo-cc11-probes/`. To run one, copy it into a worktree's
`tests/unit/`.

| Probe | What it shows | Log |
| --- | --- | --- |
| `test_zz_cc11_scale_scratch.py` (the store fix's RED) | `build_code_source` on `test_code_generation`'s world plus N generated Python files, `batch_size=128`, counting unscoped `GenerationEvidenceMember`/`GenerationMember`/`DerivedDependency` reads | `/tmp/hippo-cc11-scale-fake.log`, `/tmp/hippo-cc11-scale-ladybug.log` |
| `test_zz_cc11_scratch.py` | the published 7-file generation's structural graph: 14 code nodes, 14 sidecar rows, no arrow of any kind; the call sites of the unscoped reads | `/tmp/hippo-cc11-scratch.log` |
| `test_zz_cc11_accept_probe.py` | native reads per write batch, native relation kinds, coverage, graph counts at 2 and 8 files per language | `/tmp/hippo-cc11-accept-probe-2.log`, `/tmp/hippo-cc11-accept-probe-8.log` |

| Files | Backend | One build | Evidence members | Unscoped reads (GEM / GM / DerivedDependency) |
| --- | --- | --- | --- | --- |
| 10 | Fake | 1.1 s | 600 | 1,809 / 999 / 858 |
| 40 | Fake | 8.4 s | 2,040 | 6,009 / 3,339 / 2,808 |
| 160 | Fake | 109.5 s | 7,800 | 22,809 / 12,699 / 10,608 |
| 10 | LadybugDB | 444.6 s | 600 | 1,809 / 999 / 858 |
| 40 | LadybugDB | not measured: the OS killed the run for low system memory | | |

The same memory kill stopped the first full Fake suite run at about 10%, while the LadybugDB timing
run was still going. `LadybugStore` opens `lb.Database(str(self.path))` and passes no buffer-pool
limit (`src/hippo/store/ladybug.py:270`). CD9's LadybugDB line should therefore run with no other
heavy process on the machine.

At 2 files per language the native representation holds `DEFINED_IN` 49, `MODIFIES` 42,
`CODE_EDGE` 40 (`CONTAINS` 31, `INVOKES` 8, `IMPORTS` 1) and `PRECEDES` 3. The structural graph
projects 49 code nodes, 49 sidecar rows and no arrows. At 8 files per language: `DEFINED_IN` 175,
`CODE_EDGE` 166, 175 nodes, 175 sidecar rows, no arrows.

## Neo4j parity file list (root-owned, one process, serial)

Every file CD9's CHECK names, after the amendment below:

- `tests/unit/test_code_generation.py`
- `tests/unit/test_staged_code_writer.py`
- `tests/unit/test_generation_resume.py`
- `tests/unit/test_generation_scoped_reads.py`
- `tests/unit/test_converting_source_serving.py`
- `tests/unit/test_managed_code_activation.py`
- `tests/unit/test_code_history.py`
- `tests/unit/test_structural_loading.py`
- `tests/unit/test_dense_session.py`
- `tests/unit/test_code_capture_acceptance.py`

The brief's three additions (`test_generation_resume.py`, `test_staged_code_writer.py`,
`test_managed_code_activation.py`) are already in CD9's line. No parity run so far covers
`test_code_generation.py`, `test_managed_code_activation.py`, `test_code_history.py`,
`test_structural_loading.py` or `test_dense_session.py` (`neo4j-parity.md` runs 1–5).

Two things to know before running the new file on Neo4j:

- The scenario reopens by constructing a second `Store` from `NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD`
  on the same database, with no reset. Run it only after the store fix merges: at 270 files the
  quadratic knowledge reads make it impractical on any backend.
- The pre-fix 10-file LadybugDB build took 444.6 s, and CC9b's LadybugDB run of
  `test_code_generation.py` took 1,920 s. Size the gate checker's `--timeout` for CD9 in hours, not
  minutes.

## Ledger replacement lines

Each gate below is a complete CHECK/CRITERIA/EXPECT set, ready to paste over the current lines. A
gate marked "unchanged" repeats root's text verbatim. The pending lines in `code-capture-notes.md`
were checked against root `GATES.md`:

- CD1's Q3 clause, CD2's replacement (with ruling 14 and the CC10 spies), CD5's m1 CHECK, CD6's m4/m5
  clause, CD7's B4/B5/M2/Q4, ruling 13 and revision-reuse clauses, CD8's rebaseline clause and CD10's
  m2 EXPECT are all already applied, and each matches what shipped.
- CD9's CHECK and CRITERIA were the only lines still pending. Both are below, with the
  prior-work addendum's clauses added.
- Every other change is a correction against the evidence, named after its gate.

**CD1** (CRITERIA amended: the knowledge-table half of the per-batch bound, which KSCOPE made true at
`df05bac`; finding 1).

```text
CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_generation_scoped_reads.py tests/unit/test_generation_store.py tests/unit/test_generation_counts.py tests/unit/test_staged_prose_writer.py -q -o addopts='' -W error
CRITERIA: parameterised `_native_rows`, `_native_relationships` and `_knowledge_rows` return exactly what the unscoped forms returned for the same selection; `native_write`, `native_mutation` and `generation_checksums` use them; a recorded query counter proves per-batch work is bounded by the batch rather than by corpus size; every existing representation checksum, seal and publication result is unchanged; the reviewed prose writer and counts suites stay green. (Amended 2026-09-12 by the design review: native_write and native_mutation scope by ids and native_mutation still raises 'Native relationship crosses generations' for an edge across two generations and still admits an edge to an untagged legacy row; the scoped read is index-backed on the backends that support one, evidenced by the schema statement and not only by the query counter; sealing a generation at the symbol ceiling is linear in the generation in CPU as well as in queries; the scoped edge enumeration still returns every edge with exactly one endpoint in the selection so the 'Native relationship crosses generations' and 'Missing shared graph endpoint' refusals survive, and the two-hop MENTIONS/STATES -> SUBJECT/OBJECT closure is computed by a second scoped pass, never a whole-table read.) (Amended 2026-09-13 by CC11: the per-batch bound covers the knowledge tables as well as the native ones — `_check_knowledge_write`'s membership and binding checks, `derivations._Inventory` and `validate_view` read the generation's own `GenerationMember`, `GenerationEvidenceMember` and `DerivedDependency` rows, never a whole table per record written, so a managed code build is linear in its corpus, `evidence-cc11.md` finding 1.)
EXPECT: passed
```

**CD2** (CHECK amended: the CRITERIA cite CC10's pipeline-level spies, which live in
`test_managed_code_activation.py`, a file this CHECK did not run; CRITERIA unchanged). The amended
line on Fake, plain `-W error`: `169 passed, 2 skipped in 15.92s`, EXIT 0,
`/tmp/hippo-cc11-cd2-amended.log`.

```text
CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_converting_source_serving.py tests/unit/test_managed_source_inventory.py tests/unit/test_status_access.py tests/unit/test_structural_loading.py tests/unit/test_managed_code_activation.py -q -o addopts='' -W error
CRITERIA: `source_serves_legacy` is true for a source holding only staging Artifact/Generation rows and false once a generation is published or an all-principals suppression targets the source, independent of the managed flag, which flips at staging start (ruling 9); such a source keeps its complete legacy passages, code nodes and edges in every query and appears exactly once in source inventory with its legacy counts; with the converting source as the only managed source on the instance, no staged passage, symbol, data object or commit appears in any query result; publication flips lane, active pointer, counts and presentation in one transaction; an authorized empty published generation still appears with zero counts; a denied or tombstoned source appears in neither lane; only UNTAGGED rows ever serve the legacy lane, and a source holding a Generation row is presented in the legacy lane only while it owns at least one untagged passage, symbol, data object or commit, so a bootstrap-only managed source is absent from every graph surface, dropdown, eval label and count until publication (ruling 14, `evidence-cc1fix.md`); an actorless delete, reindex or bulk reindex of a converting source refuses rather than clearing it (`delete_source`, `delete_passages_for_source`, `delete_code_nodes_for_source`, `remove_orphans`, `_collect_generation`, `_prepare_reindex`, `_clear_passages`, `read_source` and `shutil.rmtree` outside the named per-operation checkout are never reached) and the source can still be tombstoned (store-level refusals CC1, pipeline-level spies CC10, `evidence-cc10.md`).
EXPECT: passed
```

**CD3** (CRITERIA corrected: ruling 7 made symlinks, submodules and non-regular files recorded
exclusions, and only an escaping path or a file changed during capture refuses. See `evidence-cc4.md`
and plan ruling 7.)

```text
CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_repo_capture.py tests/unit/test_code_provenance.py tests/unit/test_accepted_inputs.py -q -o addopts='' -W error
CRITERIA: the tree inventory is normalized, sorted and identical under a reordered walk; ignored directories, oversized files, unsupported names, binary content, symlinks, submodules, non-regular files and explicit exclusions each carry a distinct recorded reason (ruling 7); a path escaping the root and a file changed during capture are refused rather than skipped; code and config decode with exact complete-line locators, Unicode byte mappings and the legacy trim behaviour; rich, archive-inside-archive and binary outcomes refuse in this seam; the accepted manifest excludes itself and contains no absolute path; every later read is from the captured raw object.
EXPECT: passed
```

**CD4** (CRITERIA corrected: the committed chunker synthesizes no data-object mention text, so there
is no mention passage to map; `evidence-cc5.md` finding 1).

```text
CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_prepared_code_chunks.py tests/unit/test_ingest_chunker.py -q -o addopts='' -W error
CRITERIA: for seeded trees the prepared chunk text, order and `defines` equal the committed `chunk_documents(..., code=code)` output; every chunk maps to exact original line ranges plus explicitly marked generated segments for the context header and commit passages (the committed chunker synthesizes no data-object mention text, so none is mapped); oversized bodies split at statement boundaries as today; a chunk whose text is byte-identical to one original region carries no generated segment; remapped, rich and already-derived inputs reject.
EXPECT: passed
```

**CD5** (unchanged).

```text
CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_code_binding.py tests/unit/test_managed_input_binding.py -q -o addopts='' -W error
CRITERIA: spans, rendered views, derived records and dependencies, knowledge objects, observations, native rows, bindings, revision members and evidence members form one closed inventory with no duplicate and no orphan *binding* — a `repository` or `file` knowledge object legitimately has observations and no native row, and must not be treated as an orphan; native IDs equal `symbol_id`/`data_id`/`commit_id` under the generation namespace; `symbol_key` carries the signature discriminator so overloads do not merge; a shared canonical symbol observed by two sources keeps distinct per-source observations; no `Assertion`, `AssertionVersion`, `AssertionSupport` or `SYNONYM` row is produced; the materialiser holds no store handle, model client or clock.
EXPECT: passed
```

**CD6** (unchanged).

```text
CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_code_history.py tests/unit/test_git_history.py -q -o addopts='' -W error
CRITERIA: one `history_event` artifact and revision per commit carrying the author date in `source_updated_at`, the raw `%aI` text in `source_timestamp_original`, its offset in `source_timezone` and `source_precision="second"`; commit observations use `valid_from` = author date, `validity_kind="explicit_interval"`, `temporal_basis="commit"`, `recorded_from` = the one injected capture instant, `recorded_to` null; no record calls a wall clock and no default instant appears anywhere; `MODIFIES` hunks and `PRECEDES` pairs bind only to symbols of the same generation; `skipped`, `truncated`, the shallow boundary, renames and disabled history are recorded in coverage and never presented as a complete history; the first-parent restriction of the history walk is recorded in coverage beside `skipped`, `truncated` and the shallow boundary, so a first-parent history is never presented as the repository's complete history; every commit observation carries an explicit `evidence_class` (`declared`), its span is a `field` locator over the commit message on the history_event revision, and the history rule version enters generation identity through a top-level configuration key the merge refuses to do without (ruling 10, option 3).
EXPECT: passed
```

**CD7** (unchanged).

```text
CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_staged_code_writer.py tests/unit/test_generation_resume.py tests/unit/test_generation_failure.py -q -o addopts='' -W error
CRITERIA: batches are complete dependency groups, so no batch leaves a dangling endpoint or an unbound native row; every batch revalidates lease, fence, authorization and suppression inside its own short transaction; no callback, model call or filesystem access occurs inside a transaction; missing, extra or conflicting rows refuse the seal; the seal writes an `IndexManifest` with the evidence, dense and native representations and matching checksums; `reclaim_generation_build` resumes a never-published attempt with an equal `manifest_hash` without collecting, a different manifest still collects, a published generation never reopens, and identical replay is idempotent while a conflicting persisted payload fails closed; a lost fence or expired lease prevents every write and the seal; a reclaim on a tombstoned source, on a source with a live holder, with an expired lease, or on a generation with any of the three publication proofs refuses without advancing the fence or installing a holder; a resumed build adopts the persisted capture instant, reproduces every `ObjectObservation` ID byte-identically and reports a nonzero `resumed_from_batches`; a staged generation holding a record the current derivation would not produce fails the resume rather than sealing; the resume probe checks every row of a group against its canonical payload, never a sample and never `native_write`'s tolerant equality, and a relation group binds only to endpoints this attempt would produce; a sealed code generation validates under the `code` generation profile (one manifest, one repository, one file per accepted input, zero or more history_event members, the history_event pairs excluded from identity) at seal, checksum and query time, and the plain-prose profile's member set and every existing checksum are byte-identical (ruling 13); a refresh over an unchanged file reuses its immutable revision, so one revision record is a member of both generations and its `observed_at` stays the instant it was first observed.
EXPECT: passed
```

**CD8** (CRITERIA corrected in one phrase: `resumed_from_batches` counts skipped dependency groups, not
batch transactions; `evidence-cc8.md` finding 7, `evidence-cc9b.md`).

```text
CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_code_generation.py tests/unit/test_managed_code_activation.py tests/unit/test_ingest_pipeline.py tests/unit/test_ingest_concurrency.py tests/unit/test_managed_pipeline_activation.py tests/unit/test_prose_generation.py -q -o addopts='' -W error
CRITERIA: an authenticated actor converts an eligible `repo`, `archive` or code `file` and the legacy graph serves unchanged until publication; refresh keeps G1 selected through capture, extraction, every write batch and the seal, and after failure or cancellation; a crashed build resumes the same generation and reports the skipped dependency-group count (`resumed_from_batches`, excluding the revision-member groups every install writes); `already_current` returns without inference; the head SHA, walker rules version and per-grammar parser profile participate in generation identity while worker count, clone depth and progress do not; `BuildAuthority.rebaseline` accepts an unrelated authorization-epoch change and refuses after any capability loss, after any suppression-epoch change, when the Source row's `access_role_id`, `min_rank` or `owner_id` changed even though the actor kept every capability, after a sticky failure and inside a transaction, and never adopts a suppression epoch or a changed `SourceControl`; a bootstrap publication expects no authorization-epoch change in its window because the managed flip happened at staging start, and a genuine unrelated authorization change in the same window still refuses; open, preview and actorless callers and unsupported source kinds stay legacy; spies on `_clear_passages`, `delete_passages_for_source`, `delete_code_nodes_for_source`, `remove_orphans`, `store.delete_source`, `shutil.rmtree`, generation collection and raw unlink are never called for a managed attempt; the reviewed prose coordinator suite is unchanged by the `_Run` extraction.
EXPECT: passed
```

**CD9** (CHECK amended: the acceptance file is added. CRITERIA amended: M4, M5, the reopen case of
revision reuse, the LadybugDB engine defect, and the two fix slices' clauses. Apply after both fix
slices merge and CC11's LadybugDB rerun records GREEN.)

```text
CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_code_generation.py tests/unit/test_staged_code_writer.py tests/unit/test_generation_resume.py tests/unit/test_generation_scoped_reads.py tests/unit/test_converting_source_serving.py tests/unit/test_managed_code_activation.py tests/unit/test_code_history.py tests/unit/test_structural_loading.py tests/unit/test_dense_session.py tests/unit/test_code_capture_acceptance.py -q -o addopts='' -W error
CRITERIA: close and reopen preserves generation pointers, fences, exact membership, native code rows and relations, bindings, manifests, raw references, resumable staging state and coverage; a published code generation projects `StructuralCodeEvidence` with exact original spans and original citations with real line locators, its sealed native `DEFINED_IN` rows each join a bound node to a passage of the same generation whose original spans include the node's binding span, the structural graph's projected `DEFINED_IN`, `CODE_EDGE`, `MODIFIES` and `PRECEDES` arrows equal the selected generation's sealed native rows and `status.source_view`'s `edges_by_kind` equals its native `CODE_EDGE` rows (the managed lane writes no `REFERS_TO` and a declaration-only module stays unbound, as `evidence-codeproj.md` pins), and it routes through verified dense dispatch; a retired generation stays reconstructable under a live snapshot; a refresh over an unchanged file or commit reuses its immutable revision, and the shared record survives reopen unchanged; a representative multi-hundred-file fixture (`tests/fakes/code_capture_repo.py`, 270 accepted files at its default size) completes within the ceilings of the plan's §8.3 with the CD1 query bound holding for native and knowledge reads alike. (Amended 2026-09-13 by CC11: the CD1 linearity bound at the 50,000-symbol ceiling is proven on Fake by CC2's synthetic fixture, and the index-backed half of the bound is proven on Neo4j (parity run 2), not on LadybugDB, which creates no secondary index; the multi-hundred-file fixture does not exercise the symbol ceiling and is not presented as doing so; the LadybugDB `IN <list>` engine defect on node string columns is guarded by `store.base.by_ids` and the static tripwire `test_no_query_builder_selects_node_rows_with_a_list_predicate`, `evidence-lbfix.md`.) Root records disposable-Neo4j parity for the same files here as an evidence note, run serially against the reserved container, never as a second concurrent pytest process.
EXPECT: passed
```

**CD10** (unchanged; ten files, not eleven).

```text
CHECK: .venv/bin/ruff check src/hippo/ingest/repo_capture.py src/hippo/ingest/code_provenance.py src/hippo/ingest/prepared_code_chunks.py src/hippo/ingest/code_generation.py src/hippo/ingest/build_run.py src/hippo/knowledge/code_binding.py src/hippo/knowledge/code_history.py src/hippo/knowledge/staged_code.py && .venv/bin/ruff format --check src/hippo/ingest/repo_capture.py src/hippo/ingest/code_provenance.py src/hippo/ingest/prepared_code_chunks.py src/hippo/ingest/code_generation.py src/hippo/ingest/build_run.py src/hippo/knowledge/code_binding.py src/hippo/knowledge/code_history.py src/hippo/knowledge/staged_code.py ai_docs/plans/rag-it-all-task-5-managed-code-capture.md ai_docs/gates/rag-it-all/task-5-code-capture/GATES.md
CRITERIA: no lint findings; the formatter also checks the fenced Python in the plan and this ledger, which the CI Ruff job runs; independent SPEC and QUALITY reviews pass with every finding closed and each affected gate rerun afterwards.
EXPECT: 10 files already formatted
```

**Ledger header** (not a gate line). `GATES.md:3` still says "no implementation evidence has been
recorded", and `GATES.md:14-15` say "Test files named below do not exist yet". Every file now exists,
and CD1–CD8 and CD10 have recorded runs. Proposed replacements:
`**Status:** implemented through CC10; CC11 acceptance recorded in evidence-cc11.md; gates unticked until the checker runs.`
and `Every CHECK line runs from /Users/mascott/projects/hippo. Runnable checkboxes are set by the
orchestrator's gate checker, never by an implementer.`

## Open findings for the reviewer

Findings 1 and 2 are new in this slice. The rest are carried from slice evidence that no later slice
closed.

1. **Whole-table knowledge reads per record make a code build quadratic.**
   - `store/generations.py:675`: `_check_knowledge_write`'s `frozen` list reads every
     `GenerationEvidenceMember` and resolves each one's generation, on every put.
   - `:641`: every `GenerationMember`, on each evidence-member put.
   - `:658` and `:663`: `GenerationMember` and `GenerationEvidenceMember`, on each `NativeBinding`
     put.
   - `knowledge/derivations.py:115-123`: `_Inventory.__init__` reads both membership tables. It is
     reached per rendered passage through `store/generations.py:1477` (`_validate_managed_native` →
     `validate_view`).
   - `DerivedDependency` is read unscoped through `validate_view` and
     `validate_generation_derivations` (`generations.py:971`).

   Callers are `knowledge/staged_code.py:467` and `:482`, and the install at
   `ingest/code_generation.py:708-738`. See the measurement table: 109.5 s for 160 files on Fake and
   444.6 s for one 10-file build on LadybugDB. `native_whole_table()` is empty, so CD1's test as
   written holds while its CRITERIA's "bounded by the batch rather than by corpus size" does not.
   Closed by KSCOPE, merged at `df05bac` (`evidence-kscope.md`). Every one of those sites now reads
   by `generation_id`, by a primary key or by a v7 key: `GenerationEvidenceMember.record_id` and
   `DerivedDependency.derived_record_id`. On LadybugDB the v7 keys are predicate scans inside the
   engine. After merging it, the CD9 scenario asserts that no generation-sized knowledge kind is
   read whole during a managed build.
2. **A published code generation projects no arrows.**
   - `knowledge/code_binding.py:459-463` refuses `input_binding_ids` on code derived records.
   - `knowledge/projection.py:541-544` therefore skips `DEFINED_IN` for every rendered code passage,
     and every symbol chunk is rendered, because of its context header.
   - `projection.py` reads no native `CODE_EDGE`.

   The legacy lane serves `code_out` arrows, so this is a code-path retrieval regression. It also
   makes `status.source_view`'s `CODE_EDGE` counts (PA2-4, `evidence-cc10.md` finding 1) read zero.
   Closed by CODEPROJ, merged at `955cc11`. The projection now serves `DEFINED_IN`, `CODE_EDGE`,
   `MODIFIES` and `PRECEDES` from each selected generation's sealed native rows. Two parity
   differences are pinned: the managed lane writes no `REFERS_TO`, and declaration-only modules
   stay unbound (`evidence-codeproj.md`, recorded in the plan appendix). Since pa2f4 (`63aae1e`),
   `status.source_view` counts the generation's native `CODE_EDGE` rows. CD9's acceptance test
   asserts both after the merge into `wp/cc11`.
3. **CD9 has not run at the multi-hundred-file size on LadybugDB.** It is blocked by finding 1 and
   PENDING above.
4. **The heartbeat can latch before a between-batch rebaseline.** `evidence-cc9b.md:405-411`; the
   `build_run.py` hook was not taken (`evidence-cc10.md:272`).
5. **A crash between the seal and the publication is not resumable by an immediate retry.**
   `evidence-cc9b.md:412-415`. It becomes resumable once recovery marks the generation `failed`
   (`evidence-cc3.md:158-160`). No coordinator test exercises the recovery path.
6. **The community label is not written for managed code.** `store/code.py:107`'s `symbol_write_row`
   (`evidence-cc8.md:426-433`). The plan withdraws the claim in its CC11 appendix.
7. **Two C# overloads in one file share one native ID.** `codegraph.model.symbol_id` carries no
   signature (`evidence-cc6.md:267-276`).
8. **`ObjectKind` lacks `collection`, `label` and `rel_type`.** They map to `resource`
   (`knowledge/model.py:56-87`, `evidence-cc6.md:136-149`).
9. **`chunk_overlap_chars` is hashed but inert for code.** `ingest/code_generation.py:185`
   (`evidence-cc6.md:349-357`).
10. **`content_kind` is unset on code passages.** `evidence-cc8.md:434-438`.
11. **`validate_generation_profile` does a bounded `_knowledge_get` pair per member on every query.**
    `evidence-cc8.md:445-451`.
12. **A `ResumePlan` is not bound to the prepared index it was probed against.**
    `evidence-cc8.md:456-462`.
13. **No writer rule version is hashed, against plan ruling 10's list.** `evidence-cc8.md:439-444`.
14. **Ruling 5 is deferred.** A converted source's README facts are not extracted
    (`evidence-cc9b.md:275-280`).
15. **`walk_tree` is not cancellable.** `evidence-cc9b.md:416-417`, CC4 finding 11.
16. **A crashed repository build leaves `checkouts/<operation-id>/` behind.**
    `evidence-cc10.md:284-288`.
17. **The legacy lane stores a credentialed `meta.url`.** Routed to Task 16
    (`evidence-cc10.md:282-283`).
18. **CD10's lint list covers only the eight new modules.** It omits the reviewed files the slices
    changed:
    - `knowledge/generation_profiles.py`, `knowledge/build_authority.py`, `knowledge/projection.py`
    - `codegraph/git_history.py`
    - `ingest/managed_activation.py`, `ingest/pipeline.py`, `ingest/repos.py`
    - `store/generations.py`, `store/knowledge.py`, `store/migrations.py`, `store/base.py`,
      `store/ladybug.py`
    - `context.py`, `status.py`, `web/routes/sources.py`, `cli.py`

    The CI Ruff job covers them. The ledger does not.
19. **`test_import_order.py::MODULES` does not list `hippo.ingest.build_run`.**
    `evidence-cc9a.md:183-187`.
20. **Test harness gotcha.** `test_generation_scoped_reads.ReadLog.__exit__` restores `_native_rows`,
    `_knowledge_rows` and `_native_relationships` as bound-method instance attributes
    (`tests/unit/test_generation_scoped_reads.py:78-81`). A later Fake transaction on the same store
    then deep-copies the store through them and fails. The acceptance test instruments with plain
    functions for that reason. The existing tests are unaffected because none of them opens a
    transaction afterwards.
21. **The Neo4j driver logs Cypher parameters at DEBUG.** Root's Neo4j parity run 6
    (`/tmp/hippo-orch-neo4j-parity-cc10.log`) failed
    `test_code_generation.py::test_no_log_record_source_row_or_receipt_carries_a_path_url_or_source_text`:
    the driver's `[#…] C: RUN MERGE (n:Artifact …) {…}` records carried raw URIs and paths. The test
    now checks hippo's own loggers only (`f31090c`). Hippo's logging setup must cap the `neo4j` logger
    at INFO (Task 16 or a follow-up). The same limit is recorded in the plan appendix's §10
    paragraph.
22. **LadybugDB build cost is query count.** On the merged tree, the CD9 scenario at 2 files per
    language (three builds) made 183,041 knowledge reads and no whole-table read of a
    generation-sized kind. The top kinds:

    | Read | Count |
    | --- | --- |
    | `EvidenceSpan` by key | 47,367 |
    | `ArtifactRevision` by key | 32,596 |
    | `Artifact` by key | 17,799 |
    | `Generation` by key | 15,875 |
    | `AccessPolicy` by key | 9,068 |
    | `DerivedRecord` by key | 7,273 |
    | `DerivedDependency` by key | 6,423 |
    | `MaintenanceJob` by key | 5,735 |

    Whole reads of the small authorization tables add about 4,600 each for `Suppression`,
    `WorkspaceMembership` and `Workspace`, and about 3,100 each for `AccessPolicy` and
    `GroupMembership` (`evidence-kscope.md` finding 1). A write batch made up to 21,404 knowledge
    reads, against at most 20 native reads (`/tmp/hippo-cc11-timings-fake-2b.json`). Each is one
    query on LadybugDB, so a per-build cache of the authorization reads and batched keyed
    `_knowledge_get` reads are where a LadybugDB build's time can be recovered.
23. **The Fake store races a query's lease heartbeat against a long build.** The CD9 scenario on
    Fake at the default size failed after 20 min 24 s in `refresh_under_a_live_snapshot`
    (`/tmp/hippo-cc11-fake-48.log`). The failure was `RuntimeError: dictionary changed size during
    iteration` at `src/hippo/store/knowledge.py:450`, which surfaced as
    `AuthorizationChanged("Snapshot lease renewal failed; repeat the query")`
    (`knowledge/lease_heartbeat.py:54`).

    The sequence:

    1. The held `query_session` renews its snapshot every lease/3 (100 s) on a heartbeat thread
       (`query_access.py:152`, `context.py:377`).
    2. The renewal revalidates the reader proof, which reads `GenerationEvidenceMember` by
       `generation_id` through KSCOPE's Fake single-key path. That path is a comprehension over the
       live per-kind dict.
    3. Meanwhile the refresh build writes knowledge records. A Fake knowledge write puts straight
       into `_knowledge_data` (`knowledge.py:503`), and `FakeStore` holds `_lock` only inside
       `transaction()` (`tests/fakes/fake_store.py:136`), so that read and write are not serialized.

    At 2 files per language the refresh finishes before the first renewal.

    This is a race in the test double, not a LadybugDB or Neo4j result. KSCOPE's single-key fast
    path (`knowledge.py:450`, a comprehension over the live dict) widened its window. The
    pre-KSCOPE path, `list(rows.values())`, only narrowed it; nothing serialized a read against
    another thread's write.

    Fixed in this slice under the orchestrator's ruling (a) plus (b), with the Fake branches only
    and real backends untouched:

    - `KnowledgeQueries._knowledge_rows` takes the store lock while it copies the kind's rows and
      walks the copy.
    - `_write_knowledge` takes the same lock for its put.
    - The live-snapshot renewal on Fake is unchanged.

    New `tests/unit/test_fake_store_threads.py` makes the interleaving deterministic. A row-like
    object inside the kind hands control to a writer thread in the middle of the read.

    | Run | Result | Log |
    | --- | --- | --- |
    | RED | `1 failed`: `RuntimeError: dictionary changed size during iteration` | `/tmp/hippo-cc11-fakelock-red.log` |
    | GREEN | `1 passed` | `/tmp/hippo-cc11-fakelock-green.log` |
    | Thread and heartbeat regression, Fake: `test_fake_store_threads`, `test_knowledge_scoped_reads`, `test_generation_scoped_reads`, `test_generation_store`, `test_staged_code_writer`, `test_generation_resume`, `test_prose_generation`, `test_ingest_concurrency`, `test_dense_session`, `test_code_generation`, `test_code_projection`, `test_build_run` | `319 passed, 1 skipped in 90.46s` | `/tmp/hippo-cc11-fakelock-regress.log` |

    Not serialized: `store/snapshots.py:259` `_delete_knowledge_record` pops a Fake record. Its
    caller is generation collection, and the file was outside this grant.
24. **An embedded LadybugDB store may take about 80% of system memory.** `store/ladybug.py:270` opens
    `lb.Database(str(self.path))` without `buffer_pool_size`. real_ladybug 0.15.3's own signature is
    `Database(..., buffer_pool_size: int = 0, ...)`, and its docstring says the default is "~80% of
    system memory".

    The full-size LadybugDB acceptance run grew by about 1 GB a minute: 1.3 GB, then 3.9 GB, then
    8.0 GB between 13:46 and 13:50. The earlier OS kill of the 40-file LadybugDB timing run fits the
    same cause. Production servers and every LadybugDB test inherit this default.

    The orchestrator ruled it a production defect and routed it to the follow-up slice `lbpool`,
    which covers `store/ladybug.py`, the settings and a test cap in `tests/conftest.py`. The
    full-size CD9 run waits for `lbpool` to merge. This slice
    touches none of those files. For this run a guard stops only this slice's LadybugDB pytest if
    system free memory drops below 4 GB (`/tmp/hippo-cc11-ladybug-guard.log`).

    The guard tripped on the full-size run (48 files per language) at 13:58:50, after about 13
    minutes (EXIT 143, `/tmp/hippo-cc11-ladybug-acceptance.log`). The process RSS grew steadily
    until then:

    | Time | RSS | System free |
    | --- | --- | --- |
    | 13:46 | 1.3 GB | 31 GB |
    | 13:48 | 3.9 GB | 32 GB |
    | 13:50 | 8.0 GB | 28 GB |
    | 13:51 | 10.7 GB | 26 GB |
    | 13:54 | 20.2 GB | 15 GB |
    | 13:56 | 26.4 GB | 9 GB |
    | 13:58 | 33.1 GB | 3 GB (guard) |

    Only the fixture determinism test had passed. The run had written no progress log, so the
    scenario phase it reached is unknown. The same scenario on Fake held about 270 MB, so the
    growth is the engine's under the uncapped default buffer pool, not the test's own bookkeeping.

## Commits

PENDING.
