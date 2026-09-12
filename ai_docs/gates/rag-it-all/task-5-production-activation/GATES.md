# Task 5 production-activation gates

**Status:** proposed; no implementation evidence has been recorded.

**Scope:** authenticated local text/plain managed dispatch, mixed lifecycle operations, current-view tombstones, generation-aware source inventory, structural production reads, dense retrieval dispatch, and safe failures. LadybugDB is the primary acceptance backend. Physical purge/retention, restore, repository/rich managed extraction, connectors, and autonomous maintenance remain outside this ledger.

- [ ] PA1: BuildActor propagation and managed eligibility are closed and backward compatible.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_local_workspace_membership.py tests/unit/test_managed_pipeline_activation.py tests/unit/test_managed_route_activation.py -q -o addopts='' -W error
  CRITERIA: authenticated web page/API, HTTP/stdio MCP, remote CLI, and gated local CLI propagate the current real reader; explicit internal calls may use trusted-local; open/preview/missing-token callers cannot build managed evidence; old actorless library calls remain legacy; only pasted text and the closed plain-prose extension set opt in; unsupported inputs preserve legacy behavior; existing managed sources never fall back to legacy.
  EXPECT: passed

- [ ] PA2: Exact selected-generation metadata makes empty managed sources visible without leaking denied sources.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_source_inventory.py tests/unit/test_status_access.py tests/unit/test_structural_loading.py -q -o addopts='' -W error
  CRITERIA: canonical selected `(source,generation)` pairs require an authorized exact manifest revision and survive scope/compose/dense replacement/fingerprint; empty active generations appear with Source control presentation and zero counts; denied/suppressed/staging/retired generations do not appear; empty selection performs no Ollama call; shared code/object/relation and Fact support counts use exact current provenance.
  EXPECT: passed

- [ ] PA3: Managed add/bootstrap/refresh uses the coordinator and preserves G1 on every non-publication exit.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_pipeline_activation.py tests/unit/test_prose_generation.py tests/unit/test_generation_failure.py -q -o addopts='' -W error
  CRITERIA: saved plain input is bounded and captured under the configured absolute raw root; profile/options/operation identity are immutable; bootstrap swaps legacy only at publish; refresh serves G1 through cancellation/failure/races; failure state is generation aware; no managed attempt clears source-wide evidence, collects a generation, or deletes raw/source files.
  EXPECT: passed

- [ ] PA4: Managed delete is an atomic current-view tombstone and fence, not physical deletion.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_source_lifecycle.py tests/unit/test_ingest_concurrency.py tests/unit/test_generation_store.py tests/unit/test_evidence_access.py -q -o addopts='' -W error
  CRITERIA: current-only all-principals Source suppression, next epoch, restoration barrier, Source tombstone presentation, active-builder fencing and exact unpublished-job cancellation commit together; delete does not wait on model I/O; in-flight/current reads deny after commit; active/retired generations, history, saved ingress, raw blobs, snapshots, independent support and unrelated sources remain; legacy delete behavior is unchanged; repeated inaccessible delete reveals nothing.
  EXPECT: passed

- [ ] PA5: Reindex and mixed bulk dispatch by source mode without managed cleanup or resurrection.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_pipeline_activation.py tests/unit/test_ingest_pipeline.py tests/unit/test_ingest_concurrency.py tests/unit/test_status_access.py -q -o addopts='' -W error
  CRITERIA: managed refresh and eligible conversion never call legacy preparation; unsupported/actorless unmanaged sources preserve legacy preparation; bulk preflights every managed authority before any clear, clears all and only legacy lanes before job submission, skips tombstones, retains the public accepted response, isolates asynchronous failures, and rechecks races without fallback. Destructive managed-operation spies remain untouched.
  EXPECT: passed

- [ ] PA6: Production readers hold one structural owner and model routes use dense dispatch with private failure mapping.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_route_activation.py tests/unit/test_dense_session.py tests/unit/test_query_session.py tests/unit/test_web_base.py tests/unit/test_web_auth.py tests/unit/test_mcp_http.py tests/unit/test_mcp_server.py tests/unit/test_cli.py tests/unit/test_web_analyze.py tests/unit/test_web_code.py tests/unit/test_eval_access.py tests/unit/test_evals_runner.py -q -o addopts='' -W error
  CRITERIA: ask/search/analyze/light-up/evaluation activate verified or explicit tag-compatible dense execution from one held structural session; graph/source/status/code/citation routes remain Ollama-offline; hidden or empty sources do not affect routing; authorization/profile changes deny output; HTTP/MCP/CLI stable codes contain no injected secrets, raw text, paths, tokens, prompts, model bodies, or arbitrary exception strings.
  EXPECT: passed

- [ ] PA7: Ladybug persistence and full Task 5 regression pass as the primary backend.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_local_workspace_membership.py tests/unit/test_managed_source_lifecycle.py tests/unit/test_managed_source_inventory.py tests/unit/test_managed_pipeline_activation.py tests/unit/test_managed_route_activation.py tests/unit/test_prose_generation.py tests/unit/test_dense_session.py tests/unit/test_query_session.py tests/unit/test_generation_store.py tests/unit/test_structural_loading.py tests/unit/test_status_access.py -q -o addopts='' -W error
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
