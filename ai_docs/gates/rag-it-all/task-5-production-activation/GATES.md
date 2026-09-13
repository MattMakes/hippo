# Task 5 production-activation gates

**Status:** PA1–PA7 MET by the gate checker's full `--reverify` pass (started 2026-09-12 06:33 -0700, finished 07:44; PA7's Ladybug line 1:08:31) at source revision `9770c00` (`rag-it-all-tibs`; log `/tmp/hippo-orch-pa-gates-3.log`; the checker's EVIDENCE lines carry no git revision, so this line is the revision of record). PA8's EXPECT is a prose clause and is signed only by the independent sign-off review: the first review (`ai_docs/reports/2026-09-12-pa8-signoff.md`) found it NOT SIGNABLE with 30 LOW/INFO rows; the closure batch (`evidence-pa8close.md`) and the PA2 finding 5 ruling (`evidence-pa2f5.md`) followed; the re-sign-off report is named beside PA8 when it lands. Neo4j parity for the store lanes is recorded in `neo4j-parity.md` here and in `../task-5-code-capture/neo4j-parity.md` (runs 1–5).

**Scope:** authenticated local text/plain managed dispatch, mixed lifecycle operations, current-view tombstones, generation-aware source inventory, structural production reads, dense retrieval dispatch, and safe failures. LadybugDB is the primary acceptance backend. Physical purge/retention, restore, connectors, and autonomous maintenance remain outside this ledger; repository, archive and code-file managed capture is the sibling ledger `../task-5-code-capture/GATES.md` (its CC10 slice widened this ledger's PA1 opt-in set).

- [x] PA1: BuildActor propagation and managed eligibility are closed and backward compatible.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_local_workspace_membership.py tests/unit/test_managed_pipeline_activation.py tests/unit/test_managed_route_activation.py -q -o addopts='' -W error
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=b6bf9549d64b/37 entries; output=..............s...............................                           [100%] | 188 passed, 2 skipped in 29.49s
  CRITERIA: authenticated web page/API, HTTP/stdio MCP, remote CLI, and gated local CLI propagate the current real reader; explicit internal calls may use trusted-local; open/preview/missing-token callers cannot build managed evidence; old actorless library calls remain legacy; only pasted text, the closed plain-prose extension set and (since CC10 of the managed code-capture ledger, `../task-5-code-capture/evidence-cc10.md`) code files named by `readers.is_code_name`, `.zip` archives and repositories opt in; unsupported inputs preserve legacy behavior; existing managed sources never fall back to legacy.
  EXPECT: passed

- [x] PA2: Exact selected-generation metadata makes empty managed sources visible without leaking denied sources.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_source_inventory.py tests/unit/test_status_access.py tests/unit/test_structural_loading.py tests/unit/test_multi_generation_support.py -q -o addopts='' -W error
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=b6bf9549d64b/37 entries; output=..................................                                       [100%] | 105 passed, 1 skipped in 2.35s
  CRITERIA: canonical selected `(source,generation)` pairs require an authorized exact manifest revision and survive scope/compose/dense replacement/fingerprint; empty active generations appear with Source control presentation and zero counts; denied/suppressed/staging/retired generations do not appear; empty selection performs no Ollama call; shared code/object/relation and Fact support counts use exact current provenance.
  EXPECT: passed

- [x] PA3: Managed add/bootstrap/refresh uses the coordinator and preserves G1 on every non-publication exit.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_pipeline_activation.py tests/unit/test_prose_generation.py tests/unit/test_generation_failure.py -q -o addopts='' -W error
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=b6bf9549d64b/37 entries; output=..........................s.......................                       [100%] | 191 passed, 3 skipped in 26.91s
  CRITERIA: saved plain input is bounded and captured under the configured absolute raw root; profile/options/operation identity are immutable; bootstrap swaps legacy only at publish; refresh serves G1 through cancellation/failure/races; failure state is generation aware; no managed attempt clears source-wide evidence, collects a generation, or deletes raw/source files.
  EXPECT: passed

- [x] PA4: Managed delete is an atomic current-view tombstone and fence, not physical deletion.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_source_lifecycle.py tests/unit/test_ingest_concurrency.py tests/unit/test_generation_store.py tests/unit/test_evidence_access.py -q -o addopts='' -W error
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=b6bf9549d64b/37 entries; output=.............................................                            [100%] | 117 passed in 6.84s
  CRITERIA: current-only all-principals Source suppression, next epoch, restoration barrier, Source tombstone presentation, active-builder fencing and exact unpublished-job cancellation commit together; delete does not wait on model I/O; in-flight/current reads deny after commit; active/retired generations, history, saved ingress, raw blobs, snapshots, independent support and unrelated sources remain; legacy delete behavior is unchanged; repeated inaccessible delete reveals nothing.
  EXPECT: passed

- [x] PA5: Reindex and mixed bulk dispatch by source mode without managed cleanup or resurrection.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_pipeline_activation.py tests/unit/test_ingest_pipeline.py tests/unit/test_ingest_concurrency.py tests/unit/test_status_access.py tests/unit/test_ingest_limits.py -q -o addopts='' -W error
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=b6bf9549d64b/37 entries; output=..............................................                           [100%] | 188 passed, 2 skipped in 30.26s
  CRITERIA: managed refresh and eligible conversion never call legacy preparation; unsupported/actorless unmanaged sources preserve legacy preparation; bulk preflights every managed authority before any clear, clears all and only legacy lanes before job submission, skips tombstones, retains the public accepted response, isolates asynchronous failures, and rechecks races without fallback. Destructive managed-operation spies remain untouched.
  EXPECT: passed

- [x] PA6: Production readers hold one structural owner and model routes use dense dispatch with private failure mapping.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_route_activation.py tests/unit/test_dense_session.py tests/unit/test_query_session.py tests/unit/test_web_base.py tests/unit/test_web_auth.py tests/unit/test_mcp_http.py tests/unit/test_mcp_server.py tests/unit/test_cli.py tests/unit/test_web_analyze.py tests/unit/test_web_code.py tests/unit/test_eval_access.py tests/unit/test_evals_runner.py tests/unit/test_managed_web_surfaces.py tests/unit/test_managed_web_ingress.py tests/unit/test_graph_surface_access.py tests/unit/test_web_library_evals.py tests/unit/test_managed_eval_activation.py tests/unit/test_evals_question_maker.py tests/unit/test_managed_transport_activation.py tests/unit/test_public_errors.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=b6bf9549d64b/37 entries; output=........                                                                 [100%] | 728 passed in 95.34s (0:01:35)
  CRITERIA: ask/search/analyze/light-up/evaluation activate verified or explicit tag-compatible dense execution from one held structural session; graph/source/status/code/citation routes remain Ollama-offline; hidden or empty sources do not affect routing; authorization/profile changes deny output; HTTP/MCP/CLI stable codes contain no injected secrets, raw text, paths, tokens, prompts, model bodies, or arbitrary exception strings.
  EXPECT: passed

- [x] PA7: Ladybug persistence and full Task 5 regression pass as the primary backend.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_local_workspace_membership.py tests/unit/test_managed_source_lifecycle.py tests/unit/test_managed_source_inventory.py tests/unit/test_managed_pipeline_activation.py tests/unit/test_managed_route_activation.py tests/unit/test_prose_generation.py tests/unit/test_dense_session.py tests/unit/test_query_session.py tests/unit/test_generation_store.py tests/unit/test_structural_loading.py tests/unit/test_status_access.py tests/unit/test_managed_web_surfaces.py tests/unit/test_managed_web_ingress.py tests/unit/test_managed_eval_activation.py tests/unit/test_managed_transport_activation.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=b6bf9549d64b/37 entries; output=......................                                                   [100%] | 742 passed in 4111.53s (1:08:31)
  CRITERIA: close/reopen preserves local membership, active pointers, exact manifests, raw references, failed refresh state, tombstone/fence/epochs, empty source visibility and current/history behavior. Existing legacy ingestion/query/source tests remain green. No real model credentials or network are required.
  EXPECT: passed

- [ ] PA8: Static checks, call-site audit, Neo4j parity, and independent review pass.
  CHECK: .venv/bin/ruff check src/hippo tests/unit/test_local_workspace_membership.py tests/unit/test_managed_source_lifecycle.py tests/unit/test_managed_source_inventory.py tests/unit/test_managed_pipeline_activation.py tests/unit/test_managed_route_activation.py && .venv/bin/ruff format --check src/hippo tests/unit/test_local_workspace_membership.py tests/unit/test_managed_source_lifecycle.py tests/unit/test_managed_source_inventory.py tests/unit/test_managed_pipeline_activation.py tests/unit/test_managed_route_activation.py ai_docs/plans/rag-it-all-task-5-production-activation.md
  CRITERIA: lint/format pass; `rg -n 'query_session\(|query_access\(|graph_for\(|ctx\.graph\(' src/hippo` is attached to review with every production call classified; independent SPEC and QUALITY reviews have no unresolved findings; the PA1–PA6 behavioral set also passes against a reserved isolated Neo4j database before Neo4j scale compatibility is claimed.
  EXPECT: all checks pass; all call sites classified; independent review pass; Neo4j parity recorded

## Mandatory negative evidence

The PA3–PA5 test fixtures must monkeypatch each of these to fail if called for a managed source: `Store.delete_source`, `delete_passages_for_source`, code-source deletion, `remove_orphans`, pipeline `_clear_passages`, `shutil.rmtree`, generation discard/collection, raw unlink/removal, and source-root removal. Passing only by checking final counts is insufficient.

The PA2/PA6 fixtures must include an authorized empty generation, a policy-denied empty generation, a current-tombstoned generation, hidden wrong-profile evidence, relation-only support, code-only support, shared multi-source objects, a profile change during use, and an authorization change during output construction.

The PA7 Ladybug fixture must use a temporary absolute `HIPPO_DATA_DIR`, close the first Store/context cleanly, reopen the same database/raw tree, and re-run current/history/source-view assertions. Tests must never write to the repository's `data/` directory.

## Evidence recording format

When a gate passes, replace its checkbox and append an `EVIDENCE:` line containing exit code, shell, working directory, source revision, test count, and concise output. Record initial RED failures for each new behavior and the final GREEN result. Any change made after review reruns the affected focused gate and PA7/PA8 when persistence or shared routing changed.
