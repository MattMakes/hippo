# Latest handoff: response-time improvement goal

Read [2026-09-16-performance-goal.md](2026-09-16-performance-goal.md) first. It supersedes the historical task state below for the current user request. The active goal is not complete. A full fake-store suite is running in exec session 14400.

---

Historical handoff (preserved):

<original_task>
Implement the entire approved docs/rag_it_all.md on rag-it-all-tibs, preserving the isolated code-graph base. User explicitly authorized multiple agents and publishing reviewed commits to PUBLIC MattMakes/hippo on this branch. Do not ask again. User forbids prioritization/estimates based on time. Local-first Ladybug, Neo4j scale verification. Full task remains incomplete: Tasks0–4 done, Task5 OPEN, Tasks5A and6–16 remain. No goal tool was created. Continue implementation rather than treating a new status/continue message as a replacement task.
</original_task>

<work_completed>
The canonical detailed progress record is ai_docs/checkpoints/2026-09-11-execution-state.md. Published HEAD at this handoff is f7acf6e. Recent reviewed commits:
- ad7ef86: static fixture evaluator holds one query session through search/scoring/candidate DTOs (59 Fake tests).
- 1d46f00: controlled generation embedding-profile binding to exact accepted manifest and original revisions, verified seal/config/dimension checks (33 Fake,33 Ladybug,33 Neo,84 compatibility;122 profile integration).
- ffc46b6: detached plain-prose preparation and fenced staged writer, exact complete inference/dense coverage, controlled verified binding required, callback-free transaction core (147 independent Fake;19 writer Ladybug/Neo,32 pure preparation).
- a9f0b52: captured actual OpenIE runtime, immutable digest/name/context/capabilities and per-attempt live authorization; sticky concurrent failure, exact request/parser semantics (41 focused,187 regressions, independent transport/concurrency probes).
- f7acf6e: progress documentation/full-suite result.
Earlier published slices include raw capture/storage, original provenance/chunk mapping, input binding, query-session ownership across presentation/evaluations/changesets, schema4 fenced generations/snapshots, schema5 derived/prose lineage and dense capability sidecars. See checkpoint and dedicated plans/ledgers; do not redo completed slices.

Full regression of exactly a9f0b52 from isolated git archive /tmp/hippo-rag-reviewed.upWdAL passed2875,23skipped,17upstream Starlette/httpx warnings. Log /tmp/hippo-reviewed-a9f0b52-full-fake.log; session26579 completed. Explicit HIPPO_TEST_STORE=fake; local socket permission granted for HTTP tests. This run excludes subsequent uncommitted structural/build-authority changes. CI for recent published commits remains queued at last check, not claimed green.
</work_completed>

<work_remaining>
Immediate active work:
1. Root final structural gate checker4030 (/tmp/hippo-structural-final-root-gates.log) and isolated Neo session2286 (/tmp/hippo-structural-final-neo4j.log). Storage agent implementation stable:38 Fake/38 Ladybug,170 exact compatibility,269 expanded regressions,Ruff8files. Root reviewed the implementation against the contract; finalize verdict after gates, checkpoint, explicitly stage only owned files and publish. No other agent may edit its files before publication.
2. rag_generation_loader drafts exact dense_session/retrieval_session contract (no implementation yet). One structural query_session, no advisory metadata routing/duplicated eligibility. New explicit DenseCapability tag_compatible retains canonical+legacy+code+relation provenance, no verified fingerprint, uniform positive dimension; legacy zero vectors preserved. Mixed verified/tagged rejects. Truly empty legacy graph requires no model; tag-only code graph with no legitimate width denies dense retrieval. Verified session validates actual contributing generation profiles then resolves/validates HTTP outside DB and activates canonical matrices without graph reload. Structural relation source_generations map covers support-only contributors. Tiny shared dense.py/GraphIndex/projection width changes must coordinate after structural publication. Production caller activation stays separate.
3. adaptive_graph_papers implements first bounded build-authority increment after approved prose coordinator draft. Owns NEW knowledge/build_authority.py,NEW test_build_authority.py, narrow knowledge/access.py shared source helper, plan/ledger. Reuses EvidenceAccess with a read-only prospective overlay of ACTUAL accepted Artifact/Revision/span/policy records. No synthetic probe artifacts/policies. Empty pre-capture guard calls factored EvidenceAccess.require_source(source_id,query_mode=current|history), sharing identity/workspace/source/suppression rules with build. Read-only local check usable under TX; callback check rejects ambient TX and brackets callback with sticky guard. bind_inputs creates bound authority only while original controls/epochs remain identical; no generic epoch rebase. Trusted local explicit maintenance actor supported; readers need current source-management authority and reviewed workspace mapping. Existing policies cannot be overridden; provider/legacy_unknown/expired/future/tombstoned input rejected even for internal plain conversion.
4. rag_generation_store now independently reviews loader's dense-session contract while root final structural tests run. No code edits during final gates.

Coordinator full draft ai_docs/plans/rag-it-all-task-5-prose-coordinator.md is approved in architecture, not implemented. Bootstrap prepares all raw/model outputs without any persisted Artifact/Generation (those would hide legacy), no durable reservation; final bounded outer TX performs source/control/authority CAS, installs policy/generation/job/members/profile, callback-free writer/seal, publishes. Duplicate computation allowed; one commit winner. Refresh stages/claims before inference and owns job heartbeat. Capture policy/managed self-mutation epoch shifts only under lock after original baseline checks, then fresh local authority validation. Stop/join workers outside TX; no callback/model/raw I/O inside bootstrap transaction. Source meta input config CAS independently required. New controlled failure marker may be needed later; do not source-wide cleanup. No-op compares input manifest before parent-dependent generation construction. Reuse exact stored original revisions/timestamps. No raw GC without accounting for in-flight captures.

Production ingestion remains LEGACY. Before enabling managed writes, finish structural/dense caller routing, lifecycle coordinator/bootstrap/update/delete/reindex/bulk dispatch, runtime errors, code/rich/history provenance and parser predicate/projection parity. No INVOKES/IMPORTS/CONTAINS/MODIFIES/PRECEDES assertion registry implementation yet. Later temporal/conflict/connectors/schema/hybrid/evaluation tasks remain required; don't mark Task5 complete from primitive tests.
</work_remaining>

<attempted_approaches>
- Per-source structural projection collided on legitimate shared canonical repository symbol IDs. Final approved design uses one workspace projection, validates vectors per selected generation/source, merges only equal shared code display attributes (source label/degree excluded), and explicitly rejects conflicting attributes. Source-local code contributions determine source scope; relationships survive only complete retained support, with arrows/omega/code_kinds/igraph rebuilt. No endpoint-only support retention.
- Old cached majority-vector matrices could discard managed heterogeneous profiles or let hidden/managed rows choose legacy eligibility. Structural path reads exact managed raw rows and loads visible legacy inventory separately. It preserves existing legacy eligibility, not rows already dropped by that legacy algorithm.
- Code with unembedded or rendered-only original support could disappear during scope. Frozen StructuralCodeEvidence and original citations now retain it without invented passages/vectors.
- Preparation guard snapshotted closed/failure before an external callback; concurrent closure during blocking callback could dispatch afterward. Recheck sticky state after callbacks; event tests prove correction.
- Captured OpenIE capabilities initially accepted mutable lists in a frozen record. One RED test led to strict canonical tuple validation. Runtime initial lint gate failed only import ordering; final gates all MET.
- Do not classify profile mode from a digest-shaped string: explicit controlled verified_v1 binding only; absent mode is supported legacy_tag_v1. No HTTP inside local metadata validation.
- Bootstrap cannot claim the existing generation job before preparation without prematurely marking legacy managed. Detached preparation plus final atomic CAS avoids a new reservation schema.
</attempted_approaches>

<critical_context>
Repo /Users/mascott/projects/hippo, zsh. NEVER touch application data/. All tests use disposable fixtures. .venv Python3.12.11; real_ladybug0.15.3; pytest9.1.1; Ruff0.16.6. Store fixture defaults to LADYBUG; set HIPPO_TEST_STORE=fake explicitly for Fake claims. Pure tests backend-independent.

Git base code-graph unchanged at3ac02f30054fff3827ec25aa799147be99967692; no standalone open code-graph PR existed to close, historical merged PR1 left untouched. Never git add all; shared tree has concurrent edits. .git/network/local sockets require require_escalated; publication authorization persists and auto review has allowed it. No credentials printing. No automatic data cleanup.

Disposable Neo container hippo-rag-test-b780ab5 (Neo5.26.30), bolt127.0.0.1:32774, no host bind mounts. Existing test-only credentials are in prior command context; never use application Neo. ONE Neo pytest process at a time. Current reservation root2286; after completion database free. Prefix HIPPO_TEST_STORE=neo4j for Neo checks. Root owns reservations.

Old isolated dev runtime still7a6b5e2 on .rag-dev-data/hippo.lbug port8011, no reload, session36640/log /tmp/hippo-rag-dev-server-task5.log. Backup .rag-dev-data/pre-task5-7a6b5e2. Do not pretend it runs new HEAD. Credentials are0600 .rag-dev-data/smoke-credentials.json; NEVER print. User Ollama is not ours to stop.

Skills previously read/announced: dev-prime/dev-execute/preflight/dev-tdd/dev-debug/dev-gates/dev-whats-next. No applicable AGENTS/CLAUDE found. User continuation overrides skill pauses; don't ask for reapproval of implementation/publication. Required frequent meaningful commentary (~minute). Avoid waits >60seconds. No new goal unless user requests.

Gate checker: UNLAZY_APPROVAL_DIR=/tmp/hippo-rag-gate-approvals node /Users/mascott/.agents/skills/dev-gates/scripts/gate-check.mjs --approve --reverify --timeout 600 LEDGER --root . --cwd . . --approve alone skips previous MET; --reverify actually runs. APPROVAL REQUIRED is local oracle bookkeeping, not user approval. Inspect every result; don't edit active ledger. EXPECT must match pytest/Ruff output; criteria belong separate. No app warnings suppressed; exact known upstream AnyIO warning filter used only where required.
</critical_context>

<current_state>
At handoff creation: HEADf7acf6e published. Uncommitted structural owned files: context.py,hipporag/graph_index.py,knowledge/dense.py,projection.py,query_access.py,replay.py,snapshots.py;NEWtest_structural_loading.py and plan/ledger. These are being final-verified, not yet committed. Uncommitted build-authority tests/ledger/coordinator plan under adaptive ownership, implementation may arrive asynchronously. Loader dense contract draft may arrive asynchronously; read live agent messages before continuing. No root implementation changes pending. This handoff itself is local work, not a completion claim. Continue original plan.
</current_state>
