# Managed code capture: cross-task notes (orchestrator-owned)

Running list of contracts and open items that cross CC1–CC11 boundaries. The plan is
`ai_docs/plans/rag-it-all-task-5-managed-code-capture.md`; the design review is
`ai_docs/reports/2026-09-12-code-capture-plan-review.md`; the ledger is
`ai_docs/gates/rag-it-all/task-5-code-capture/GATES.md`.

## Merged

- CC4 at `91131e7`: `src/hippo/ingest/repo_capture.py`, `src/hippo/ingest/code_provenance.py`
  (evidence-cc4.md; M8 amendment recorded: repo identity from the whole normalized clone path).
- CC1 at `7a0c719`: `GenerationQueries.source_serves_legacy(source_row)` (shape (b), ruling 9 with
  the tombstone term); lane decision at `context.py:~222/~345`, `status.py:~61/~78`; the managed
  flag keeps its staging-start timing. `meta['managed']` is no longer a lane marker and a legacy
  row's passage count comes from the held graph (the Store's Source counter is cumulative).

- CC9a at `67e11cc`: `src/hippo/ingest/build_run.py` (`BuildRun`, `BuildReceipt`, `BuildCancelled`,
  `BuildBusy`, `BuildProgress`, `credentials`, `authority_fields`); `prose_generation.py` keeps aliases.
  For CC9b: `BuildRun(ctx, actor, source_id, options, should_stop, on_progress, *, cancelled_message=,
  renewal_failed_message=, capture=)`; options need only `lease_duration_seconds` and
  `renewal_interval_seconds`; `BuildReceipt(..., resumed_from_batches=0, rebaselines=0)`.

- REGRESSION from CC1 (found by opus-17 at `c893a95`): a staging-only managed source satisfies
  `source_serves_legacy`, lands in `legacy_ids`, and the legacy loader (no generation filter) emits its
  unpublished native rows on graph surfaces and its name in eval labels (PA6 line: 6 failed). Ruling 14:
  the legacy lane serves ONLY untagged rows, and a `managed` source is presented in the legacy lane only
  when it has at least one untagged row; `source_serves_legacy` keeps its three terms. Refined by opus-18
  (approved): (a) a source with NO Generation row follows `13efa40`'s rule verbatim (legacy iff in no
  managed record set: Artifact/Generation/managed flag), because test fixtures and the eval SECRET source
  write untagged rows plus an Artifact; (b) a source WITH a Generation row is converting: legacy iff
  `source_serves_legacy()` AND it has >= 1 untagged Passage/Symbol/DataObject/Commit. Flicker-free because
  `prose_generation` writes the Generation before the first Artifact. Corner case (a) hides: a managed
  source with no Generation row is invisible, as before CC1. Fix worker:
  `fix-cc1-legacy-lane.md` (`wp/cc1fix`). CC1's tests that asserted presentation of a rows-less
  generation-only source are re-adapted; the six PA6 tests are the contract. The CD2 CRITERIA line gains
  "only untagged rows serve the legacy lane; a managed source with no untagged row is absent from every
  surface until publication" when the fix merges.

- CC6 at `e02bb08`: `src/hippo/knowledge/code_binding.py` with two entry points,
  `code_generation(capture, *, workspace_id, source_id, generation_identity_inputs, observed_at) -> Generation`
  (identity never depends on the graph; CC9b's order is capture -> code_generation -> extract_code(...,
  node_namespace=generation_namespace(gen)) -> resolve -> read_history -> prepare_code_chunks ->
  materialize_code_evidence) and `materialize_code_evidence(...) -> CodeEvidenceBundle`; rule versions under
  the reserved configuration key `code_derivation`; `EXPECTED_CODE_CHUNK_RULE_VERSION` pinned. The bundle
  does NOT seal until CC8's `code` profile lands (one manifest, one repository member whose revision carries
  the accepted manifest hash/uri and the head SHA, one file per input, N history_event). Findings that bind
  later slices (evidence-cc6.md): (10) CC8 subtracts `{row.native_id for row in bundle.native_rows}` from the
  graph's node IDs before writing CODE_EDGE (a whitespace-only symbol gets no passage and no native row);
  (11) `chunker.code_windows` takes no overlap, so `overlap_chars` is inert for code yet sits in identity;
  (4) plan section 4's `community` label has no key in `Symbol.row()`: CC8/CC9b merge it or CC11 drops the
  claim from the plan; two C# overloads share one codegraph native ID (two objects/bindings over one row,
  first in canonical order kept) recorded as a defect for CC11/CD10, not repaired.

- CC7 rulings (2026-09-12): `CODE_HISTORY_RULE_VERSION` enters identity via CC7's exported
  `HISTORY_CONFIGURATION_KEY`, set by CC9b OUTSIDE `code_derivation` before `code_generation`;
  `merge_code_bundles` refuses a generation whose accepted configuration lacks it. `merge_code_bundles`
  returns a new `MergedCodeBundle` (CC6's field names plus history fields, revalidated) because
  `NativeCodeRow` refuses `Commit` and `_check_membership` refuses extra revision members. CC8's `code`
  profile excludes `history_event` pairs from the `generation_for_inputs` re-derivation (members, not
  identity inputs).

- CC2 at `c461c9c` (CD1 line 90 passed in the root tree): `_native_rows(kind, *, ids=None,
  generation_id=None, source_id=None, untagged=False)`, `_native_relationships(*, ids=None,
  generation_id=None)` (exactly one), `_knowledge_rows(name, *, generation_id=None, where=None)` over a
  per-kind field allow-list, `_edges_touching(ids, *, both=False, rels=None)`, `_selected_revisions(gid)`,
  `_validate_managed_native(kind, row, gen, *, selected=None)`; `native_write`/`native_mutation` by ids,
  checksums/counts/`_inventory` by generation; `_knowledge_get` by `where={id}` (the real quadratic).
  Schema v6 = journaled indexes (M4's four plus IndexEvent.aggregate_id, Suppression.target_kind/target_id,
  MaintenanceJob.input_fingerprint; v5 frozen with its checksum); LADYBUG HAS NO SECONDARY-INDEX DDL
  (real_ladybug 0.15.3), so its v6 step list is empty and scoped reads are bounded by the predicate only:
  CD9 must state the index-backed half is proven on Neo4j (orchestrator parity run 2), not on the
  acceptance backend. Sealing at 50,000 symbols: 3.51s. Ruling 14's untagged read exists.

- CC7 at `20c4dea` (CD6 line 89 passed in the root tree): `src/hippo/knowledge/code_history.py` with
  `bind_history(history, *, code_bundle, repository, workspace_id, source_id, generation_id,
  generation_namespace, observed_at, history_depth, shallow_boundary) -> CodeHistoryBundle` and
  `merge_code_bundles(code_bundle, history_bundle) -> MergedCodeBundle` (`.accepted_pairs` = the hashed
  identity set, `.history_pairs` = the complement); `HISTORY_CONFIGURATION_KEY='code_history_derivation'`
  (top-level, set by CC9b BEFORE `code_generation`; refused if absent); commit spans are `FieldLocator
  ('commit.message')` on the history_event revision, `declared`; `BoundCommitPassage` for commit chunks;
  `bind_history` refuses `observed_at != code_bundle.generation.created_at` (one instant). Routed: CC8 never
  dereferences a history_event revision's `raw_uri` (`hippo-commit:<sha>`); CC9b passes the FOLDED
  configuration to `capture_repository_inputs`, subtracts CC6 finding 10's unbound-symbol complement from
  `History.modifies` and records it in coverage (bind_history REFUSES a MODIFIES edge whose symbol has no
  native row), unions its coverage into the merged `coverage_json`, and must obtain the shallow boundary
  itself: nothing produces it today (`git_history._shallow` is private; renames are internal too) — CC9b
  is granted `src/hippo/ingest/git_history.py` additions only, to surface `shallow` and `renames` on
  `History`.

- CC3 at `8f32ec4` (resume+failure+scoped+claim-callers 328 passed in the root tree):
  `GenerationQueries.reclaim_generation_build(generation_id, *, job_key, lease_owner, lease_expires_at,
  expected_manifest_hash) -> MaintenanceJob` sharing `_admit_build(...) -> BuildAdmission(job, generation,
  reused)` with `claim_generation_build` (claim collects a failed generation first; reclaim restages
  without collecting). Claim tightened: the never-published triple gained `source.active_generation_id ==
  gen.id` and now applies to staging generations too. Gotcha for CC8/store tests: on Ladybug/Neo4j
  `_lock_source` commits a `generation_lock` increment even on an idempotent same-holder admission, so
  whole-row before/after snapshots must exclude that field. Store side of B4 asserted
  (`test_a_reclaim_does_not_re_take_the_stored_capture_instant`); the coordinator side (adopt
  `Generation.created_at`) is CC9b's. Still whole-table: `fail_generation_build`, `_collect_generation`,
  `apply_source_tombstone` IndexEvent/Suppression reads (named for CC8/CC11). Neo4j parity run 3 (CC3) is
  queued behind run 2.

- CC8 ruling (2026-09-12): `build_authority.py` widens two more refusals beside B3's kind allow-list:
  `BuildAuthority._inventory` admits `repository` and `history_event` accepted artifacts (beside
  `file`/`manifest`), and the planned-policy scope key accepts `source:<id>:managed-code-v1` beside
  `plain-prose-v1`, closed to exactly those two. Prose byte-identical; CC8 exports the scope-key
  constant for CC9b.

- CC8 at `d1910c8` (CD7 line + authority/profile/prose-consumer suites 308 passed in the root tree):
  `knowledge/staged_code.py` (fenced dependency groups, `probe_staged_rows` with the absence assertion,
  seal), `BuildAuthority.rebaseline()`, `build_authority` admits repo/archive + repository/history_event
  members + `source:<id>:managed-code-v1`, `generation_profiles` gains the `code` profile (history_event
  pairs excluded from identity). generations.py untouched (the "Evidence outside raw manifest" check
  never refused the repository span). Findings: plan section 4's `community` label CANNOT be written
  (`symbol_write_row` closed dict, `add_symbols` has no SET) -> CC11 drops the claim or opens a
  `store/code.py` slice; `content_kind` unset on code passages; `validate_generation_profile` does
  O(members) bounded `_knowledge_get` pairs at query time (CC11 notes it); no writer rule version in
  identity (batch grouping affects no record identity; M2 closed by the absence assertion).
- LADYBUG ENGINE DEFECT (opus-19, 2026-09-12): real_ladybug 0.15.3 answers `WHERE n.id IN $ids` from the
  WRONG row when the table holds a deleted row and the wanted row was written in the open transaction
  (string columns from another row -> UnicodeDecodeError / ValueError). Introduced into the pipeline by
  CC2's `_knowledge_get` -> `_native_rows(ids=[id])`. Ruling: every `id IN $ids` shape in `store/*` goes
  through ONE helper emitting `UNWIND $ids AS rid MATCH (n:Kind {id: rid})`; a Ladybug repro test and a
  static tripwire are added; `wp/lbfix`. GENERALISED (opus-19): the defect is ANY `IN <list>` predicate
  on a STRING column of a NODE table (`p.generation_id IN $generations` at `knowledge/projection.py:~111`
  too, granted to opus-19); the tripwire covers node-property `IN $` in `store/*` and `knowledge/*`;
  relationship-property sites (`store/code.py:~596`, `ladybug.py:~1280`) are converted only on a clean
  repro, else allowlisted with the probe named; `migrations.py:~307` label comprehension left alone.
  Every future Ladybug query builder must use the UNWIND form for list membership on node string columns.
  `wp/lbfix` merged at `9770c00` (bisect: first red at `c461c9c`; Ladybug lane 138 passed; evidence
  `evidence-lbfix.md`). CC9b told to merge the tip before its Ladybug lines.

- CC9b rulings (2026-09-12): the git history reader is `src/hippo/codegraph/git_history.py` (the CC7
  brief's `ingest/git_history.py` path was wrong); CC9b is granted ADDITIONS ONLY there for a public
  `shallow_boundary(checkout)` wrapper (renames only if a trivial promotion), `test_git_history.py`
  green. RULING 5 DEFERRED (named): no slice in this wave carries prose extractions through
  `CodeEvidenceBundle`/`MergedCodeBundle`/`staged_code` (which refuses them), so a `PROSE_EXTENSIONS`
  file inside a tree is captured as ordinary passages via `prepare_code_chunks`' prose branch and
  coverage records `openie='skipped'`, reason `prose_extraction_deferred`, per file. The OpenIE widening
  of CC6/CC7/CC8 is a follow-up slice CC11 records in the plan's post-implementation amendments; the
  user is told at close-out.

- CC9b grant (2026-09-12): a code REFRESH over an unchanged file was impossible (`ArtifactRevision`
  identity excludes `observed_at`, so generation 2 mints the same id with a new instant and
  `put_knowledge`/`build_authority._inventory` refuse). CC9b owns the amendment in
  `knowledge/code_binding.py` and `knowledge/code_history.py` (additions only): optional
  `stored_revisions` mapping on `materialize_code_evidence`/`code_generation`/`bind_history`, reusing
  the stored record when `(artifact_id, content_hash, provider_revision, raw_uri)` match, as
  `prose_generation._pair` does; `observed_at` means first observed. Pending ledger clause for CD7 and
  CD9: "a refresh over an unchanged file or commit reuses its immutable revision rather than refusing".

- CC9b at `bc7ea22` (coordinator + binding + writer + layering suites 344 passed in the root tree):
  `src/hippo/ingest/code_generation.py::build_code_source(ctx, *, source_id, actor, tree: CodeTreeInput,
  options: CodeBuildOptions, raw_store, embedding_spec, operation_id, should_stop, on_progress=None,
  embedding_cache=None) -> BuildReceipt` (status created | already_current | resumed), refusals
  `CodeBuildRefused(ValueError)`; `CodeTreeInput(root, paths=None, kind="repo", repository=None,
  head_revision=None)` — the coordinator is HANDED A CHECKOUT (cloning and the per-operation directory
  are CC10's `repos.py`); `CodeBuildOptions` input-affecting vs operational fields are asserted by a test
  (operational fields never enter identity). `codegraph.git_history.shallow_boundary()` added; the
  stored_revisions reuse landed in CC6/CC7's modules. Ladybug: one managed code build ~55s vs ~0.6s Fake
  (CD9 context, not a scale claim). Findings for CC10/CC11 (evidence-cc9b.md, six): the lease heartbeat
  can latch before a between-batch rebaseline (needs a hook in `build_run.py`, CC9a's file -> CC10 may
  take it, additions only); a crash between seal and publication is not resumable (store contract, CC3 ->
  CC11 records); `CodeTreeInput.paths` is an exclusion complement (capture has no only-these-paths);
  renames stay `not_reported`; "what a reviewer must not read as proven" has seven items (no scale claim,
  ceilings proved by lowering the option).

- CC10 rulings (2026-09-13): eligibility flip adapts the named rows in `test_managed_pipeline_activation.py`
  and `test_managed_web_ingress.py` (unsupported examples become `paper.pdf`/`LICENSE`); the repo routes
  (`sources.py` repo_form and `/api/sources/repo`) and `cli.py`'s git-URL branch pass the actor through
  exactly as `add_file` does (this IS the reviewed activation increment for code ingress); a credentialed
  clone URL with an actor is refused by `repository_descriptor` BEFORE any Source row exists (legacy keeps
  storing the URL verbatim: out-of-scope finding for Task 16); archives are captured straight from the saved
  `.zip` as `CodeTreeInput(kind='archive')`; the managed clone lives at `sources/<id>/checkouts/<operation_id>`
  and only a named function may remove it; an actorless bulk over a managed row raises
  `ManagedActorRequired` (not `ManagedPreflightRefused`); the `build_run.py` heartbeat hook stays named
  for CC11.

- CC10 at `9a474e4` (CD8 line 306 passed; ingress/transport/cli 327 passed in the root tree): eligibility
  admits code files (`readers.is_code_name`), `.zip` archives and repos as `eligible_legacy`;
  `run_managed_build` -> `_run_code_build` -> `build_code_source`; managed clone at
  `data/sources/<id>/checkouts/<operation-id>/`, removed only by `managed_activation.discard_checkout`;
  `add_repo(build_actor, operation_id)` refuses a credentialed URL before any row; repo routes and the CLI
  git-URL branch pass the actor; failure mapping `CaptureRefused`/`CodeBuildRefused` -> `invalid_source`,
  `RepoError` -> `operation_failed`; m6 redaction proven (no URL/path/stderr in messages, tracebacks, logs,
  rows). PA3a-6/PA3a-9/W15 closed here. Findings: PA2-4 now REACHABLE (`status.source_view` attributes
  CODE_EDGE by node membership) -> `fix-pa2-4-code-edges.md`; legacy still stores credentialed `meta.url`
  (Task 16); crashed repo build leaves `checkouts/<op>/` until retry (restart sweep could reclaim; CC11
  notes); `invalid_source` also covers code ceilings/unreadable history (frozen vocabulary); `build_run.py`
  heartbeat hook still open (CC11). CD2's destructive-operation clause applied.

- CD1 SECOND HALF (CC11 finding, 2026-09-13): the managed write path still does whole-table KNOWLEDGE
  reads per record (`_check_knowledge_write`'s frozen set, GM/GEM reads per GEM/NativeBinding put,
  `derivations._Inventory` per rendered passage, `DerivedDependency` via `validate_view`), so a code build is
  quadratic (Fake: 10 files 1.1 s, 40 files 8.4 s, 160 files 109.5 s). Fix slice
  `fix-knowledge-reads-scope.md` (`wp/kscope`); CC11 runs CD9 at ~300 files after it merges. CD1's evidence
  must then show `knowledge_whole_table(kinds=CORPUS) == []` across a full `build_code_source`, where
  CORPUS = the generation-sized kinds (GenerationEvidenceMember, GenerationMember, NativeBinding,
  DerivedDependency, DerivedRecord, RetrievalView, EvidenceSpan, ObjectObservation, IndexManifest,
  IndexEvent). Authorization/control-table reads (AccessPolicy/WorkspaceMembership/GroupMembership/
  Suppression/Workspace via `build_authority` -> `access.py`, ~880 per 10-file build; `code_generation`'s
  MaintenanceJob; `snapshots` Generation) are bounded by principals, not the corpus: recorded as a finding
  for CD10/Task 16 (a per-build cache). Schema v7 (two indexes: `GenerationEvidenceMember.record_id`,
  `DerivedDependency.derived_record_id`) journaled with v6 frozen; journal-pin edits granted in the four
  migration/store test files.

- SERVING-PARITY DEFECT (CC11 finding, 2026-09-13): a published managed code generation projects ZERO
  arrows (no DEFINED_IN, no CODE_EDGE) although the native representation holds them:
  `code_binding.py:~459-463` refuses `input_binding_ids` on code derived records (so
  `projection.py:~538-545` skips DEFINED_IN for every rendered symbol chunk) and `projection.py` never reads
  native CODE_EDGE. Fix slice `fix-code-projection.md` (`wp/codeproj`): project DEFINED_IN and the selected
  generation's native relations with exact evidence, legacy-vs-managed parity test. CC11 asserts the native
  contract now and, after the merge, projected arrows == native rows of the selected generation (CD9).

- PA2-4 fix (opus-22) merged at `63aae1e`: `status._with_code_edges(row, store, generation_id)` counts
  CODE_EDGE_KINDS rows from `_native_relationships(generation_id=...)` for the held view's proven pair
  (not the live pointer); node-membership counting removed. Open: `_audience_inventory.stats.code_edges`
  and the code card still count held-graph `code_out` (0 for managed until codeproj projects the native
  arrows) -> codeproj adds the agreement test; one three-pass relation read per managed source per
  `source_view` (Task 16: `_edges_touching(rels=('CODE_EDGE',))` or a sealed count); the count is exact to
  the generation, not narrowed by a suppression inside it (named for the PA8 reviewer). PA2 CHECK line
  gains `tests/unit/test_status_code_edges.py`.

- codeproj (opus-23) merged at `955cc11` (projection/status/coordinator/surface suites 243 passed):
  `projection._native_code_relations` reads each selected generation's sealed DEFINED_IN + NativeBinding
  rows and one `_edges_touching(ids, both=True, rels=staged_code.RELATION_KINDS)` per generation (ids =
  authorized bound native ids + projected passage ids, so crossing/unbound endpoints never appear);
  DEFINED_IN only when the binding span is inside the passage's exact original closure; PRECEDES is
  arrow-only. On the 7-file world: 0 -> 33 arrows (DEFINED_IN 14, MODIFIES 10, CONTAINS 7, PRECEDES 2);
  card/inventory count == source row count (7). Identity unchanged (pinned-id proof). Legacy-vs-managed
  parity 52 vs 46 with exactly two documented differences: the managed lane writes no REFERS_TO, and
  declaration-only modules stay unbound (`code_binding` binds `chunk.symbol_id` only -> missing node/
  CONTAINS/MODIFIES/DEFINED_IN; a follow-up slice flips the pinned parity test). Overloads sharing a native
  id project a cross product (recorded). Cost: one `_edges_touching` (8 statements) per selected generation
  with bound code. Neo4j parity run 7 (test_code_projection + test_derived_projection) queued behind run 6.

- kscope (backend-developer-25) merged: `_sealed_member`/`_revision_member`/`_evidence_member` PK and
  `where={record_id}` / `where={derived_record_id}` reads replace the per-write whole-table GEM/GM/DD reads;
  `derivations.GenerationViews(store, gen).validate(view)` hoists the inventory to one per native_write
  call / checksum pass (threaded as `views=` beside `selected=`); IndexManifest/IndexEvent/GM/GEM reads at
  seal/publish/tombstone/fail by `generation_id=`. Schema v7 (two indexes) with v6 frozen; `V7_INDEXES` is
  DERIVED from `KIND_SCOPED_FIELDS` -> freeze it as a literal before any v8. FakeStore snapshot shares
  frozen knowledge records (guard test). Numbers: per-member CPU 2.69/6.05/20.26 ms -> 1.62/1.70/3.06 ms at
  10/40/160 files; zero whole-table reads of generation-sized kinds. Full Fake suite 4435 passed.
  Findings for CC11/CD10/Task 16: authorization-table reads per BuildRun check (~880 per kind at 10 files;
  `access.build` 7140x at 160 files) -> per-build cache; `build_run._check` opens one outer transaction per
  check; AssertionSupport by `assertion_version_id` unscoped/unindexed (next index step); `validate_prose`
  once per extraction; query-time `validate_view` builds one inventory per view; Ladybug v7 keys are engine
  scans (measure the Ladybug ceiling on the acceptance fixture).

- Neo4j parity run 6 (CC9b + CC10 suites, run on `9a474e4`): 195 passed, 1 FAILED:
  `test_no_log_record_source_row_or_receipt_carries_a_path_url_or_source_text` — the neo4j DRIVER logs
  Cypher parameters at DEBUG (`C: RUN 'MERGE (n:Artifact ...)' {values}`), so caplog saw `raw_uri`/paths
  from the driver, not from hippo. Ruling: the test scopes to hippo's own loggers (CC11); FINDING for
  CD10/Task 16: hippo's logging setup must cap the `neo4j` logger at INFO unless explicitly overridden,
  because at DEBUG the driver prints every parameter (source text, paths, URLs) for legacy rows too.

- Fake-double race (CC11 at 48 files/lang): the held query session's `LeaseHeartbeat` renews on its own
  thread and reads GenerationEvidenceMember through kscope's Fake single-key fast path, a comprehension
  over the LIVE per-kind dict (`store/knowledge.py:~450`), while Fake knowledge writes put straight into
  `_knowledge_data` outside `_lock` -> "dictionary changed size during iteration" surfaced as
  `AuthorizationChanged`. Not a Ladybug/Neo4j finding. Ruling: CC11 serializes Fake knowledge reads/writes
  under `_lock` (fake_store.py + the Fake branch of knowledge.py) and snapshots `list(rows.values())`.

- LADYBUG MEMORY DEFECT (CC11, 2026-09-13): `store/ladybug.py:~270` opens `lb.Database(path)` with no
  `buffer_pool_size`; real_ladybug 0.15.3 treats 0 as ~80% of system memory PER embedded store (~100 GB
  here), so the acceptance run's RSS climbed ~1 GB/min and an earlier 40-file timing run was OS-killed.
  Production and every Ladybug test inherit it. Fix slice `fix-ladybug-buffer-pool.md` (`wp/lbpool`):
  configured `HIPPO_LADYBUG_BUFFER_POOL_BYTES`, default min(25% RAM, 4 GiB), 256 MiB cap under pytest,
  zero refused.

- QUERY-TIME WHOLE-TABLE READS (CC11, 2026-09-13): `context.py:~282/:~402` (IndexManifest),
  `projection.py:~426` (GenerationMember), `temporal.py:~495` (GenerationMember), `snapshots.py:~47/:~248/
  :~297` (IndexEvent/GenerationMember/IndexEvent), `generations.py:~1765` (IndexManifest), plus
  EvidenceSpan/ObjectObservation on the renewal and projection paths: O(corpus) per query session or lease
  renewal. On LadybugDB at ~50 files: projection+arrows phase 427 s, dense dispatch > 7 min, ~300k
  knowledge reads in a resume bootstrap; RSS flat ~11 GB outside builds. Fix slice
  `fix-query-reads-scope.md` (`wp/qscope` from `2577add`). CC11's CD1 recorder is thread-local meanwhile
  (the renewal thread's reads were the false positive at 48 files/lang).

- lbpool (backend-developer-26) merged at `c4ba26e`: `HIPPO_LADYBUG_BUFFER_POOL_BYTES` ->
  `Config.ladybug_buffer_pool_bytes`; `LadybugStore(path, *, buffer_pool_bytes=None)`; default
  `min(physical // 4, 4 GiB)` at each open; pytest autouse cap 256 MiB (explicit kwarg/Config wins). GATE
  RISK: the pool does not grow, it FAILS ("Buffer manager exception: Unable to allocate memory") — a
  1-passage prose build needs >= 96 MiB; CC11's full-size acceptance must pass an explicit size (start at 4
  GiB) and record what it needed. Outside scope: `tests/unit/test_store_migrations.py:~225` opens
  `lb.Database` bare; docker-compose does not forward the setting (nor HIPPO_DB_PATH); on Linux the
  default reads host memory, not the cgroup limit (Task 16 / ops note).

- CC11 (backend-developer-24) merged at `f9537ae` (acceptance + threads + coordinator + status + scoped
  suites 57 passed at N=2 on Fake): `tests/fakes/code_capture_repo.py::build_code_capture_repository(parent,
  *, files_per_language=48)` (270 accepted files, 2 prose, 4 unparsed, 5 exclusion reasons, 4 pinned
  commits); `tests/unit/test_code_capture_acceptance.py` (9 phases: crash+reopen, resume+reopen, seal,
  projection == native rows, dense dispatch, refresh under a held session, retired reconstruct, revision
  reuse + ceilings, CD1 bound on the build thread); knobs `HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE`,
  `HIPPO_CODE_ACCEPTANCE_BUFFER_POOL_BYTES` (4 GiB default), `HIPPO_CODE_ACCEPTANCE_TIMINGS`. Ladybug at
  N=2 with the 4 GiB pool: 455 s, peak RSS 10.2 GiB (~6 GiB outside the pool). CD2 CHECK gains
  `test_managed_code_activation.py`, CD9 CHECK gains the acceptance file (committed). CRITERIA replacement
  lines for CD1/CD3/CD4/CD8/CD9 and the header wait for cc11b's verification on the final tree.
  25 findings in evidence-cc11.md (1, 2, 23, 24 closed; 25 = qscope; 3 = cc11b).

- qscope (backend-developer-27) merged at `14d0a37` (query/projection/temporal/acceptance suites 289
  passed): `_knowledge_rows(kind, ids=[...])` via `base.by_ids` (UNWIND primary-key, never IN);
  `access._ProofReads(bounded=)` reads per selected generation and by ids; projection `allowed()` and
  `_safe_vectors` by ids with `GenerationViews`; `context._strict_generations` per active generation;
  snapshots/collection/retention by `generation_id=`; empty-lookup guard. Counter proof: no whole read of a
  generation-sized kind across open + renewal + validate + retrieval + dense, code and prose. Ladybug N=8:
  projection 334 s -> 70 s, dense dispatch 1,310 s -> 244 s (contention disfavoured the after run). Reads
  left whole, by name: authorization tables, unbounded proofs (legacy list/get, history lane,
  build_authority), compatibility AssertionSupport, `legacy_lane`/`_graph_for` Generation+Artifact,
  `native_mutation` IndexManifest. Findings for CD10/Task 16: keyed `_Inventory` per-view reads dominate
  (128k keyed reads at Fake N=2 dense dispatch); 198 proof builds per query life; AssertionSupport whole per
  AssertionVersion in `generation_checksums:~1025` at every session open; `_graph_for` Artifact whole (needs
  an `Artifact.source_id` index); `_collect_generation` walks native kinds whole.

- MEMORY GROWTH (cc11b, 2026-09-13): the CD9 scenario on LadybugDB with the 4 GiB pool uses ~0.51 GiB of
  RSS per accepted file (N=2: 10.2 GiB / 20 files; N=8: 25.6 GiB / 50 files; DB dir 96 MB), growing in
  every build and in dense dispatch; linear projection puts N=48 at ~138 GiB. Ruling: N=48 is NOT launched;
  cc11b attributes the growth first (recorder/timings off vs on; tracemalloc per phase). If production
  code retains per-file data, a fix slice follows and the ledger-size CD9 run waits for it; N=16 is the
  largest completed size meanwhile.

- NATIVE PER-STATEMENT RETENTION (cc11b, 2026-09-13, driver-level reproduction): real_ladybug 0.15.3
  `Connection.execute(query, parameters)` retains ~4.7 KB of native MALLOC_SMALL per call for the life of
  the connection (0 for literal queries; `gc.collect()` frees nothing; `Connection.close()` frees most).
  `LadybugStore` holds one connection for its lifetime and parameterises nearly everything -> production
  grows until restart (~2 GB/min of live footprint during a managed code build; peak footprint 15.8 GiB at
  N=8). Payload matrix: retention ~2.6 KB base + ~1.1x parameter bytes per statement, writes included
  (100 KB string param 115 KB; 1,000-id UNWIND 126 KB); connection close alone frees most for small
  params but NOTHING for the 100 KB-string case, while a full store close (connection + database)
  returned 16.0 -> 0.8 GiB. Fix slice `fix-ladybug-connection-recycle.md` (`wp/lbconn`): recycle the
  connection at safe boundaries, budget by statement count and parameter bytes (lbconn's 8-cycle probe:
  connection-only stays flat in every shape incl. 100 KB strings; database+connection is no better and
  costs 51-81 ms per recycle vs 0.6-36 ms). Deferred follow-up: a per-connection prepared-statement cache
  (a prepared statement retains 11 B/execute vs 1.8-68 KB; three checks unverified: DDL survival, failed
  execute reuse, cache bound). Upstream issue draft: prepare-per-execute leak, plan-complexity numbers, and a
  SIGSEGV on `WHERE n.v IN $vs` with `vs=None` (never inside a transaction or with an open QueryResult, under the lock) past a configured
  statement budget; upstream issue text drafted in evidence. The ledger-size CD9 run waits for it; N=16 is
  the largest completed size on record.

- cc11b (backend-developer-28) merged at `cbe809f` (evidence-cc11b.md only): Fake CD1-CD8/CD10 lines
  EXIT 0 on the final tree (CD1 93, CD2 169/2s, CD3 152, CD4 95, CD5 89, CD6 91, CD7 83, CD8 306/3s, CD10
  clean); full Fake 4484 passed / 30 skipped; proposed CD1 CHECK (+knowledge/query scoped reads) 118
  passed. Ladybug: N=8 completed (2 passed, 1615.56 s, peak footprint 15.8 GiB, RSS 25.6 GiB); N=16
  guard-stopped in the refresh build; N=48 not run. Reproducer `/tmp/hippo-cc11b-probes/
  ladybug_retention_case.py`. Attribution: harness not it (recorder-off run within 0.3 GiB); traced Python
  32 MB vs 5.6 GiB native footprint at N=2.

- lbconn (backend-developer-29) merged at `cbed8ca` (recycle + pool + store + activation suites 162 passed
  on Fake): `HIPPO_LADYBUG_CONNECTION_RECYCLE_STATEMENTS` -> `Config.ladybug_connection_recycle_statements`
  (default 4096 = 256 MiB / 64 KiB per statement plan; parameters charged 128 B per value, strings +25%);
  recycle only under `_lock`, after the QueryResult closes, never at transaction depth > 0 (re-checked in
  the outermost `transaction()` finally), fresh connection opened before the stale one closes, logs name no
  path or driver text. N=8: peak footprint 15.8 GiB -> 1.35 GiB, RSS 25.6 -> 2.88 GiB, 1616 s -> 1177 s,
  225 recycles over 2.13M statements, same 628,151 knowledge reads. Deferred: prepared-statement cache (11
  B/execute; DDL survival, failed-execute reuse and cache bound unverified); statements inside ONE
  transaction are bounded by that transaction, not the budget; hippo must never pass None to a
  parameterised `IN $vs` (driver SIGSEGV); upstream real_ladybug issue drafted in evidence-lbconn.md, not
  filed. The ledger-size (270-file) CD9 run is now feasible on this machine and is the first follow-up.

## Open items routed to later slices

1. Review B3 (`build_authority._source_control` refuses every source kind except `text`/`file`
   and holds a third Artifact/Generation presence test): UNTOUCHED by CC1. Owner: CC8/CC9
   (the brief must lift the allow-list to repo/archive and collapse the presence test onto
   `source_serves_legacy` or the loader-selection set). Under shape (b) only the kind allow-list
   still bites.
2. `source_serves_legacy` reads all `IndexEvent` and all `Suppression` rows per legacy source at
   three sites: handed to CC2 via its brief's PRIOR WORK (bound under CD1).
3. CD2 CRITERIA should gain the review's destructive-operation line. CC1 proves the three
   store-level refusals (`delete_passages_for_source`, `delete_code_nodes_for_source`,
   `delete_source` refuse mid-conversion); the pipeline-level ones (`_prepare_reindex`,
   `shutil.rmtree`) belong to CC10's spies. Amend CD2's CRITERIA when CC10 lands.
4. CC5's brief named `tests/unit/test_prepared_chunks.py`; the prose parity suite is actually
   `tests/unit/test_managed_chunk_provenance.py` (worker corrected it with `ls`).
5. CC2 grants (2026-09-12): `src/hippo/store/knowledge.py` query methods only (`_knowledge_rows`,
   `_knowledge_get`); `_knowledge_rows(kind, *, generation_id=None, where=None)` where `where` is an
   exact-match dict over a closed per-kind field allow-list, one bounded query per backend (this is how
   `source_serves_legacy`'s IndexEvent `aggregate_id` / Suppression target reads get bounded);
   `knowledge/staged_prose.py::_inventory` read calls only. Later slices touching `store/knowledge.py`
   (CC3, CC8) build on that signature.

5b. CC5 merged at `b516232` (CD4 line 95 passed in the root tree). Ratified CC5's three signature
   defaults: `units: Iterable[CapturedCode]`, `max_chunks` as a required keyword (no import of
   `pipeline.MAX_CHUNKS`), and the extra kinds `window`/`prose`. Rulings taken on its questions:
   - Ruling 11 (extensionless prose inside a repository): `readers.PROSE_EXTENSIONS` is the SOLE prose
     test in the managed lane; an extensionless README/LICENSE/etc. is an unparsed file, chunked as
     `window`s, recorded in coverage as `openie=skipped` with reason `unparsed`. No basename allow-list.
     The legacy lane is untouched. Binds CC9b (coverage) and CC11 (acceptance fixture must contain one).
   - The parity latch (chunking runs twice per build, pure string work) STAYS; CC9b may not disable it.
   - Commit views: CC7 owns them (CC6 passes `commit` chunks through unbound). The parked CC6/CC7
     question is closed.
   - The pinned fixture digest is bumped only with `CODE_CHUNK_RULE_VERSION`, never quietly.
5c. CC9a grant (2026-09-12): `tests/unit/test_prose_generation.py:~173` (the receipt field-set
   assertion) may be amended to the 7-name set once `BuildReceipt` gains `resumed_from_batches` and
   `rebaselines`; no other line of that file. `BuildRun` takes keyword-only `cancelled_message` and
   `renewal_failed_message` with the exact prose strings as defaults (byte-identical for prose); CC9b
   passes its own code strings.
5d. CC6 rulings (2026-09-12, code-proven questions from backend-developer-18):
   - Ruling 12 (layering): `knowledge/code_binding.py` imports NOTHING from `hippo.ingest`; it validates
     `PreparedCodeChunks`/`RepositoryCapture` structurally and pins `EXPECTED_CODE_CHUNK_RULE_VERSION`
     equal to CC5's constant, refusing a mismatch (a CC5 bump requires a CC6 bump). The
     `tests/unit/test_layering.py` allowlist stays at `{input_binding.py, public_errors.py}`. A later
     slice (CC9b or CC11) may relocate the shared chunk/capture dataclasses into `knowledge/inputs.py`
     following the layering precedent; record it as deferred if not done.
   - Ruling 13 (generation profile): `knowledge/generation_profiles.py::validate_generation_profile`
     (called from `generations.py::generation_checksums` and `dense_session.py:~115`) admits only the
     plain-prose member set (one manifest + one file per accepted input) and `generation_checksums`
     refuses "Evidence outside raw manifest". The plan holds: the repository revision (head SHA as
     `provider_revision`) and CC7's `history_event` revisions ARE generation members and carry spans.
     CC8 owns the amendment: a `code` profile selected by the accepted configuration (manifest + one
     repository + one file per accepted input + zero or more history_event), plain prose byte-identical,
     both call sites covered, CD7/CD9 CRITERIA lines gain it. CC9b sets the profile in configuration.
   - Evidence classes: symbol/data_object `syntax_observed`; file objects one observation per span,
     `catalog_observed`; repository object exactly one `declared` observation on the repository
     revision with a `FieldLocator` over the normalized clone path text; commit observations are
     CC7's (`declared` for the commit message field, per section 9).
5e. CC6 narrowing accepted: `model.ObjectKind` has `table`/`column` but not the codegraph's
   `collection`/`label`/`rel_type`; CC6 maps the latter three to `resource` (map exported as
   `code_binding.DATA_OBJECT_KINDS`), keeping dialect and data kind inside `canonical_key` and in
   `attributes_json`. Deferred question for the CD10 review / CC11: whether `ObjectKind` should grow
   the three names instead (a `model.py` change, out of CC6's scope).
6. Ownership decisions taken while drafting CC3/CC7–CC11 (fork, 2026-09-12):
   - `src/hippo/knowledge/build_authority.py` + `tests/unit/test_build_authority.py` stay with CC8
     (the plan's owner). CC8 does B3's first half: admit `repo`/`archive`, and replace the
     `managed` computation with the row's `managed` flag or `active_generation_id` (drop
     `meta["managed"]` and the whole-table Artifact/Generation scan `check_local` re-ran per batch).
   - `src/hippo/ingest/prose_generation.py` goes to CC9a (the `_Run`/`BuildReceipt` extraction into
     NEW `build_run.py`, `BuildReceipt` gains `resumed_from_batches=0` and `rebaselines=0`);
     `tests/unit/test_prose_generation.py` is regression-only for CC9a. CC9a can spawn NOW from
     `7a0c719` in parallel with CC2–CC8: nothing else in the wave touches that file.
   - `src/hippo/store/base.py`/`migrations.py` stay with CC2; CC8/CC9a/CC9b/CC10 never touch them.
   - CC9 split per M11: CC9a (`build_run.py`) and CC9b (`code_generation.py`; base = after CC3, CC8,
     CC9a). CC10 owns `repos.py` (m6) and the managed lane's clone/extract seam; CC9b's tests build
     their own checkout and `CodeTreeInput`.
   - Rebaseline (CC8): the suppression epoch is frozen at capture and ANY change refuses, which
     subsumes M7's reachable-closure question (publication would refuse anyway); `source_control`
     frozen; child-authority shape copied from `bind_inputs`.
   - B4 landing: CC9b computes the manifest and generation ID first (instant-independent), then
     adopts `Generation.created_at` from a reclaimable generation or takes one `store._now()`, and
     threads it through CC6/CC7; CC8's `probe_staged_rows` compares canonical payloads and asserts
     absence of unexpected generation-scoped rows.
   - CC6/CC7 boundary: CC7 owns every commit-side record (`history_event` artifacts/revisions,
     commit objects/observations, commit-message spans with a `field` locator, commit views unless
     CC6's evidence says it produced them, `MODIFIES`/`PRECEDES` rows) and exports the bundle
     merge with validation. CONTRACT QUESTION for the orchestrator when CC6 reports: if CC6
     rendered commit views without `history_event` revisions to bind them to, CC7's brief item 1
     needs a one-line ruling on which side owns the commit view.
   - CC11 does not edit `GATES.md`; it verifies the pending lines below, writes the final set in
     its evidence, and appends a "Post-implementation amendments" section to the plan (append
     only). The independent SPEC/QUALITY review is a separate reviewer brief the orchestrator
     still has to write (`review-code-capture.md`).

## Ledger amendments pending (orchestrator applies)

Exact replacement lines. Text before the "(Amended ...)" clauses is the current ledger text verbatim.

- CD1 CRITERIA (append after the existing amended clause; Q3's two enumeration constraints; apply now, CC2 is live):
  `... in CPU as well as in queries; the scoped edge enumeration still returns every edge with exactly one endpoint in the selection so the 'Native relationship crosses generations' and 'Missing shared graph endpoint' refusals survive, and the two-hop MENTIONS/STATES -> SUBJECT/OBJECT closure is computed by a second scoped pass, never a whole-table read.)`
- CD2 CRITERIA (replace the whole line; B1 now, the destructive-operation clause when CC10 lands):
  `CRITERIA: \`source_serves_legacy\` is true for a source holding only staging Artifact/Generation rows and false once a generation is published or an all-principals suppression targets the source, independent of the managed flag, which flips at staging start; such a source keeps its complete legacy passages, code nodes and edges in every query and appears exactly once in source inventory with its legacy counts; with the converting source as the only managed source on the instance, no staged passage, symbol, data object or commit appears in any query result; publication flips lane, active pointer, counts and presentation in one transaction; an authorized empty published generation still appears with zero counts; a denied or tombstoned source appears in neither lane; an actorless delete, reindex or bulk reindex of a converting source refuses rather than clearing it (\`delete_source\`, \`delete_passages_for_source\`, \`delete_code_nodes_for_source\`, \`_prepare_reindex\` and \`shutil.rmtree\` are never reached) and the source can still be tombstoned.`
  Note: the current line says "false once ... the managed flag is set", which ruling 9 reversed; CC1's tests assert the opposite, so this replacement is needed before the checker's CRITERIA are read against CC1.
- CD5 CHECK (m1; apply now, before CC6 spawns or runs the line):
  `CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_code_binding.py tests/unit/test_managed_input_binding.py -q -o addopts='' -W error`
- CD6 CRITERIA (append; m4 and m5; apply when CC7 lands):
  `...; the first-parent restriction of the history walk is recorded in coverage beside \`skipped\`, \`truncated\` and the shallow boundary, so a first-parent history is never presented as the repository's complete history; every commit observation carries an explicit \`evidence_class\`.`
- CD7 CRITERIA (append; B4, B5, M2/ruling 10, question 4; apply when CC3 and CC8 land):
  `...; a reclaim on a tombstoned source, on a source with a live holder, with an expired lease, or on a generation with any of the three publication proofs refuses without advancing the fence or installing a holder; a resumed build adopts the persisted capture instant, reproduces every \`ObjectObservation\` ID byte-identically and reports a nonzero \`resumed_from_batches\`; a staged generation holding a record the current derivation would not produce fails the resume rather than sealing; the resume probe checks every row of a group against its canonical payload, never a sample and never \`native_write\`'s tolerant equality, and a relation group binds only to endpoints this attempt would produce.`
- CD8 CRITERIA (replace the `BuildAuthority.rebaseline` clause and add B6-as-dissolved; apply when CC8/CC9b land):
  `... \`BuildAuthority.rebaseline\` accepts an unrelated authorization-epoch change and refuses after any capability loss, after any suppression-epoch change, when the Source row's \`access_role_id\`, \`min_rank\` or \`owner_id\` changed even though the actor kept every capability, after a sticky failure and inside a transaction, and never adopts a suppression epoch or a changed \`SourceControl\`; a bootstrap publication expects no authorization-epoch change in its window because the managed flip happened at staging start, and a genuine unrelated authorization change in the same window still refuses; ...` (the rest of the line unchanged).
- CD7 CRITERIA (append; ruling 13; apply when CC8 lands):
  `...; a sealed code generation validates under the \`code\` generation profile (one manifest, one repository, one file per accepted input, zero or more history_event members) at seal, checksum and query time, and the plain-prose profile's member set and every existing checksum are byte-identical.`
- CD9 CHECK (CC11 adds its acceptance file; apply when CC11 lands):
  append ` tests/unit/test_code_capture_acceptance.py` before `-q`.
- CD9 CRITERIA (append; M4/M5; apply when CC11 lands):
  `...; the CD1 linearity bound is proven on Fake with CC2's synthetic ceiling-sized fixture and this gate records which backend the query bound is proven on (Ladybug creates no secondary index); the multi-hundred-file fixture does not exercise the symbol ceiling and is not presented as doing so.`
- CD10 EXPECT (m2; apply now):
  `EXPECT: 10 files already formatted`
  (8 Python files plus the plan and the ledger in the `ruff format --check` list; recount if the CHECK line changes.)

## Merge checklist for each slice

- Worktree clean, commits listed in the done report, `git merge --no-ff wp/<name>`.
- Run the slice's CD gate line on Fake in the root tree after the merge.
- Ladybug lines as the brief says; Neo4j parity is root-owned, one process, batched.
- Record the merge hash here and in the fleet memory.

## CD10 review round 1 (2026-09-14)

`ai_docs/reports/2026-09-13-code-capture-review.md` (architect-reviewer-21 at `cbed8ca`/`79d171d`): CD10
NOT SIGNABLE, 5 BLOCKER / 12 MAJOR / 49 MINOR. Four parallel fix slices with disjoint file ownership:

| Finding | Brief | Owned files |
| --- | --- | --- |
| R21-B1 one NativeBinding per native row refuses ordinary trees | `fix-r21-writer.md` (`wp/r21w`) | `knowledge/staged_code.py`, `tests/fakes/code_capture_repo.py` (shapes added), `test_staged_code_writer.py`, `test_code_generation.py` |
| R21-B2 any failure after the seal strands the source | `fix-r21-writer.md` | `store/generations.py` (`bind_generation_embedding_profile`), `ingest/code_generation.py` (`_install` only) |
| R21-B3 resume probe drops a second CODE_EDGE kind / never compares relation payloads | `fix-r21-writer.md` | `knowledge/staged_code.py` |
| R21-B5 non-Fake `_edges_touching` de-duplicates on (a,b) | `fix-r21-writer.md` | `store/generations.py`, `test_generation_scoped_reads.py` (LadybugDB oracle) |
| R21-B4 legacy synonym pass mutates managed rows | `fix-r21-legacy-indexer.md` (`wp/r21i`) | `hipporag/indexer.py`, `store/code.py` (code-embedding read), NEW `test_legacy_index_beside_managed.py` |
| R21-M7 converting source page drops triples/entities | `fix-r21-capture-web.md` (`wp/r21c`) | `web/routes/sources.py`, `test_managed_web_surfaces.py` |
| R21-M8 extensionless zip members bypass the budget | `fix-r21-capture-web.md` | `ingest/repo_capture.py`, `test_repo_capture.py` |
| R21-M9 zip symlink/non-regular members unclassified | `fix-r21-capture-web.md` | `ingest/repo_capture.py` |
| R21-M10 credentialed URL echoed (body, Location, access log) | `fix-r21-capture-web.md` | `ingest/repos.py`, `ingest/pipeline.py` (message lines), `web/routes/sources.py`, `cli.py` (only if needed) |
| R21-M11 CI runs the acceptance scenario at the ledger size | `fix-r21-capture-web.md` | `.github/workflows/ci.yml`, `test_code_capture_acceptance.py` (default-size line only) |
| R21-M2 whole KnowledgeObject read per check_local with a group membership | `fix-r21-authority-tests.md` (`wp/r21a`) | `knowledge/access.py`, `knowledge/build_authority.py`, `test_knowledge_scoped_reads.py`, `test_query_scoped_reads.py` |
| R21-M4 capability-loss tests non-discriminating | `fix-r21-authority-tests.md` | `test_build_authority.py` (the `test_code_generation.py` twin is proposed to r21w in evidence) |
| R21-M6 no denial test for native relation projection | `fix-r21-authority-tests.md` | `test_code_projection.py` |
| R21-M12 overload observations cross-attributed | `fix-r21-authority-tests.md` | `knowledge/code_binding.py` (if fixed), `test_code_binding.py`; plan sentence + CD5 wording proposed in evidence |
| R21-M1 CD1 "linear" claim false as worded | `fix-r21-authority-tests.md` (authority half + measurement + wording); the cross-batch inventory in `staged_code`/`generations.py` is NOT taken (r21w is full) | `knowledge/build_authority.py`; corrected CD1 CRITERIA proposed in evidence |
| R21-M3 CD9 StructuralCodeEvidence clause vacuous | `fix-r21-authority-tests.md` (wording + assertion shape proposed) | evidence only |
| R21-M5 `test_build_authority.py` missing from CD8 CHECK | `fix-r21-authority-tests.md` (line proposed) | evidence only; orchestrator applies |

Minors taken "if a one-liner in a file already touched": r21w m2, m3, m6, m10, m14, m31; r21c m15, m16, m20,
m21; r21a m35 (+ m24, m26 only with the M12 code change). Minors owned by NO brief (a later cleanup slice):

- m1 (`test_generation_scoped_reads.py` ceiling/ratio test floors), m4 (`code_generation.py:639`,
  `prose_generation.py:233`, `context.py:243` whole IndexEvent/Artifact reads), m5 (`generations.py:1022-1029`
  AssertionSupport whole; `derivations.py:178-180`), m7/m9 (`test_converting_source_serving.py` staged
  natives in `stage()`, publication atomicity fault), m8 (`test_status_access.py` real-store denial), m11
  (`status.py:250/:346`, `cli.py:353-354` counts include staged rows; CD2 wording), m12
  (`changeset_access.py:170` unfiltered `ctx.graph()`), m13 (`context.py:43-51` limit-one read), m17
  (`test_prepared_code_chunks.py` ASCII-only corpus), m18 (`managed_activation.py:559-570` code-lane refusal
  sentences), m19 (`code_generation.py:477` truncation at exactly 50,000 symbols), m22
  (`prepared_code_chunks.py` private chunker imports), m23 (`test_git_history.py` real shallow boundary), m24/m26
  (`code_binding.py` refusal branches, `_reuse` four-field compare) unless r21a takes M12's code change, m25
  (`GATES.md:44` CD6 "symbols" -> "commits"; orchestrator), m27/m28 (`code_history.py` offset re-derivation,
  merge guard), m29 (`test_layering.py` regex, `test_import_order.py` MODULES), m30/m38 (duplication of
  `_view`, `_install`/`_publish` vs prose), m32/m33/m34/m40/m41 (`code_generation.py` refresh cancellation,
  payload ceiling after install, `already_current` after one probe, failure-path catch, rebaseline outside
  the write loop), m36 (CD8 `rmtree` wording; orchestrator), m37 (`test_generation_profiles.py` digest pin),
  m39 (`managed_activation.py:599-605` remediation never reaches a log), m42/m43/m45/m46/m47
  (`test_code_capture_acceptance.py` oracle tautologies, `>=` counts, recorder scope), m44/m48 (`GATES.md`
  CD9 wording and CHECK omissions; orchestrator), m49 (`test_store_ladybug.py:48` bare `lb.Database`).

- r21i (backend-developer-31) merged at `2570f16` (indexer/pipeline/store-code/legacy-beside-managed
  suites 119 passed on Fake): `load_code_embeddings` returns only untagged rows on Fake, Ladybug and Neo4j;
  legacy add_text/index_source beside a published or staging code generation succeeds and touches no
  tagged id; managed rows/relations/checksums byte-identical. Out of scope, named: `native_mutation` on
  entity/fact ids checksums every ready generation, so a legacy SYNONYM between entities a sealed
  generation's passages MENTION would be refused (unreachable today; the first managed lane writing native
  MENTIONS/STATES hits it). Neo4j parity run 10 started for the Cypher shape.
- r21c (backend-developer-32) merged at `4004fbd` (capture/ingress/surface/activation/acceptance suites
  368 passed on Fake): M7 converting source page cut from the held graph + `get_passages` (also moves plain
  legacy pages off `passages_for_source` SKIP/LIMIT; count still from the Source row); M8 every read
  archive member classified then budgeted (configured_exclusion members no longer count); M9 symlink /
  not_regular from `S_IFMT(external_attr >> 16)`; M10 `repos.NOT_A_GIT_URL` closed sentence, `repo_form`
  redirects the quoted closed text (`upload_form`'s unquoted `{exc}` redirect remains, outside M10);
  M11 acceptance default 8 files/lang, 48 opt-in via the env var; m15/m20/m21 closed. Not measured:
  hosted-runner wall time and memory for the Ladybug scenario at 8. CD9 CRITERIA: "one of the node's
  binding spans" (r21w's B1 oracle change in the acceptance test, granted).
- r21w (backend-developer-30) merged at `1fc6233` (writer/resume/coordinator/acceptance/layering suites 385
  passed on Fake): B1 `staged_code._groups` writes and probes EVERY NativeBinding of a native row; B3
  relations keyed `(rel, a, b, kind-or-None)`, each probe carries its row, payloads compared through
  `store.code` write-row shapes at probe and seal; B5 `_edges_touching` (non-Fake) drops the (a,b) seen set
  (b-pass skips rows whose a is in ids); B2 `bind_generation_embedding_profile` returns for a verified_v1
  generation before the IndexManifest refusal (unreachable for prose: claim collects the manifest). Fixture
  gains report.py, orders_cli.py, Robot.cs, schema.sql: accepted = 5N + 2·max(2, N//4) + 10 (274 at 48, 54
  at 8, 24 at 2). `BuildReceipt` has no `resumed` outcome (brief error); the retry test asserts same
  generation id + outcome published + exact skipped count. Left named: m2 (SUBJECT/OBJECT hop needs an
  Entity/Fact fixture), m14, m1, m5, m19, m32-34, m38, m40, m41. Gotcha: patch the Fake store CLASS, not a
  bound method on the instance (transaction snapshot cannot pickle an RLock).
- r21a (backend-developer-33) merged at `881cc83` (authority/binding/projection/scoped/acceptance/layering
  suites 403 passed on Fake): M2 `access._KEYED_KINDS` + `EvidenceAccess._groups` (group-member actors no
  longer read KnowledgeObject/Artifact/ArtifactRevision whole; `_Overlay._knowledge_rows` scoped); M1
  authority half: `check_local` proves accepted inputs once per authority (1,392/4,092 -> 42/42 rows per
  heaviest batch at 10/40 files; CPU per member 1.93x -> 1.21x over 10..160), the per-batch
  `GenerationViews` membership read stays generation-sized (writer follow-up); M4 discriminating
  capability-loss tests in both suites; M6 denial tests for relation projection; M12 overloads bound and
  observed only from passages whose original lines OVERLAP the node's lines, `CODE_BINDING_RULE_VERSION`
  = `code-binding-v2` (paired pin in code_history.py); m24/m26/m35 closed; m4 pinned as the single named
  whole-read exception. Acceptance oracle's DEFINED_IN rule matches the projection's. Ladybug acceptance
  at 8 files/lang 2 passed in 694 s. Proven-once cache does not re-read a record another writer stores
  later (docstring). Neo4j parity run 13 started (keyed KnowledgeObject reads on the proof path).
- r21i grant (2026-09-14): `store/ladybug.py::load_code_embeddings` only, adding `WHERE n.generation_id IS
  NULL` to its one query (LadybugStore does not inherit `CodeQueries`, so the Neo4j-side filter in
  `store/code.py` cannot reach it); the same untagged filter lands in the Neo4j read and the Fake so the
  legacy synonym pass never sees a managed row on any backend.

- Cleanup-slice item (2026-09-14, from r21a): `context.py:~243 _graph_for` reads Artifact whole on every
  graph build (review m4, qscope finding 6); r21a pins it as the single named exception in
  `test_query_scoped_reads.py` once Artifact joins GENERATION_SIZED. Fix shape: `Artifact.source_id` on the
  per-kind allow-list plus a journaled v8 index step (freeze `V7_INDEXES`/`V7_DESCRIPTOR` as literals
  first). Not taken by r21a.

- Ruling (2026-09-14, r21a M12): `CODE_BINDING_RULE_VERSION` bumps to `code-binding-v2` because the
  binder's derivation changed (an overload symbol is bound only from passages whose original lines
  overlap that node's lines). Strict ruling 10; no sealed generation exists anywhere real on this branch,
  so the bump costs nothing now. Every code generation id moves; tests re-pin.
