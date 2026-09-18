# Notes to fold into the activation Task 4 briefs (orchestrator scratch)

## Task 5A integration brief inputs (sections 4–6)

- Re-review minors deferred to integration (`ai_docs/reports/2026-09-11-temporal-pure-rereview.md`): N1 `temporal.py:98-109` accepts `known_at_source='latest'` when `known_at != latest_known_at` and `'inherited'` without a compare parent (label-only, identity unaffected; one-line validation fix); N2 `conflicts.py:156,161` can repeat a version ID in `superseded_version_ids` when one source contributes it under two support groups (`tuple(sorted(set(...)))`), to be done with the per-series supersession keying recorded in plan section 3.
- `ConflictSet` has no source field; "every contributing source represented" holds only through merged support spans. Reword the plan sentence when the integration slice defines persistence.
- `ResolvedTemporalSelector` constructor is now `(selector, known_at, known_at_source, latest_known_at)` with `selector_json` derived; `KnownAtSource` includes `inherited`. Any sections 4–6 code must use this shape.
- Coarse effective precision on any group member makes the whole group `possible` with null bounds (documented consequence, intended).
- Part 1 review (`ai_docs/reports/2026-09-11-t5a-int1-review.md`) decisions now being applied on `wp/t5a1fix`: caller-audience proof in `acquire_history_snapshot`; `select_history` atomic in one transaction with manifest-subset-of-proof before the put; `CurrentSelector`/`AtemporalSelector` gain optional `known_at`; `HistoryManifest` and `ConflictSet` reclassified as bookkeeping in `store/authorization.py`; `purged_history_evidence` takes workspace and access. Part 2 must build on these signatures (report section 5) and still owes: `TemporalPublicationPlan` + `publish_staged_generation` closure with failpoint rollback and idempotent retry (`recorded_correction` tests), chronological fixture loading, N2, and the inherited "revalidate on release" gap in `QuerySnapshotBundle.close()` (untested, decide whether to close it).
- Publication rule: push `158ebf2` (coordinator + probe switch, fully reviewed) as soon as opus-5's final pass lands; hold `043ca51`+ until the part 1 fixes are merged and re-checked.

## Task 4 cross-part contracts (decided during execution)

- `public_failure_for_code` is closed over the WHOLE public vocabulary (managed codes, `build_interrupted`, `retrieval_rebuild_required`, `retrieval_unavailable`) and idempotent on any `PublicFailure.code`; the 4c follow-up (opus-12) owns `public_errors.py` for that. Task 4f codes against it and merges after.
- Public codes round-trip to a message, not to an HTTP status: `invalid_source` is shared by the 400 (type) and 413 (size) failures, so `public_failure_for_code` resolves it to the 400 row. Decision: keep the vocabulary; a status is only meaningful where the exception is mapped (`public_failure(exc)`), and stored codes are rendered as messages only. The collision is pinned by name in `test_public_errors.py`.
- Evaluation failures carry their public code as the first segment of the existing stored `error` string (as `record_build_failure` does); `EvalAccess` splits it into a closed `failure_code` on the returned dict while still nulling `error`, and exposes the prefix only when it is a public code.

- JSON public failure shape on every route: body `{"error": failure.message, "code": failure.code}` with HTTP status `failure.http_status`; the fixed 502 on light-up and simulate is gone. 4b-ii adds `public_failure_response(failure)` in `web/render.py`; 4b-i implements the same shape locally in `web/app.py` and the orchestrator dedupes after both merge. MCP `ToolError` and CLI stderr carry the same `code` and message (4c).
- Test ownership resolved: `test_dense_session.py:596` (structural=False) to 4b-ii; `test_analysis_changesets.py` to 4d; `test_web_code_pages*.py` to 4b-ii; `test_query_session.py` rows `test_model_failure_releases_graph_and_revocation_wins[False-http_ask|http_search]` to 4b-i (they now assert the mapped 500 `operation_failed` body instead of a propagated `RuntimeError`, release assertions unchanged). Unknown query exceptions on `/api/ask` and `/api/search` no longer propagate; `AuthorizationChanged` still outranks and propagates to the existing 409 handler. The four MCP rows of the same test are also 4b-i's (after 4c merged, MCP tools raise `ToolError` with the closed code, `DENIED` for `AuthorizationChanged`).
- 4b-i finishes without the `delete_source`/`reindex_all` actor wiring if Task 3b has not merged by then; that wiring becomes a small follow-up brief (web/routes/sources.py plus the two skipped tests in `test_managed_web_ingress.py`).

## Wrap-up items from Task 3b (`evidence-pa3b.md`, merged `640d20b`)

- `reindex_all` with a failed managed preflight returns 0 and the route still answers `{"accepted": true}`; only a local log line reveals the refusal. The plan forbids a per-source breakdown, not a bounded signal; decide in the wrap-up whether the route should return a closed refusal code (`bulk_refused`) when nothing was started.
- A bulk with no actor over a managed inventory RAISES `ManagedActorRequired`; 4b-i's route must map it to the generic permission response (verify after 4b-i merges).
- The legacy lane still stores `f"{type(err).__name__}: {err}"` in the Source row (`pipeline.py:~309`); the CLI now prints only the closed `code: message` shape (4c follow-up) and the web status renderer maps only managed codes, so legacy text stays on the row but no longer reaches clients through those paths. Bounding the stored form itself is a small pipeline change for the wrap-up.
- The restart sweep constants (`REFRESHING_PREFIX`, `INTERRUPTED_REFRESH_STAGE`, `INTERRUPTED_REFRESH_ERROR`) live in `store/memory.py` and are imported by `ladybug.py` and the Fake; the Neo4j `base.py` sweep needs the same treatment before Neo4j parity is claimed for interrupted refreshes.

## From the 4b-i review (`ai_docs/reports/2026-09-11-pa4b1-review.md`, SPEC/QUALITY PASS, three medium routed to 4e)

- F1 page routes answer JSON to browsers on a mapped failure (Accept negotiation missing in `app.py`'s handler); F2 `pages.py::failure_text` logs at DEBUG and promises an operation ID nothing logs; F3 seven `sources.py` JSON failure bodies carry no code. All three are 4e addenda (backend-developer-12).
- Confirmed closed by 4b-i: pa4c F1 and F6, both bullets of pa4b2 finding 10; the actorless bulk maps to the generic 409 with code; the fixed 502 is gone.
- Also routed to 4e: F4 (two `public_failure_page` definitions, rename before dedupe), F5 (`sources.py` broad `except ValueError`), promotion of the review's probes 5 and 6 into the suite, and the caution that the bulk test must fail if the bulk silently starts nothing. F6 (delete maps every `AuthorizationChanged` to 404, including a mid-request revocation) is an accepted non-disclosure deviation. The stale line numbers in `evidence-pa4b1.md:388` (real sites `graph_index.py:297,300`) can be corrected in the wrap-up.

## From 4b-i's done summary (merged `0bc378c`)

- A bare `ValueError` from `GraphIndex.canonical_selected_generations` still escapes graph-only routes as a code-less 500 (module constants only, nothing private); fixed at the source in Task 4e decision 8 (raise `ProjectionError`).
- HTTP denial carries `code=authorization_changed` while MCP and CLI carried a sentence with no code; the 4c follow-up (opus-12) unifies all three on the web sentence plus that code.

## From the 4c re-review (`ai_docs/reports/2026-09-11-pa4c-rereview.md`, PASS, four LOW)

- N1: `public_errors.py:179-184` comment misnames "the last two rows"; the test mirror at `test_public_errors.py:208` says eleven against a twelve-entry dict. Documentation only.
- N2: `cli.py:635` `_index_remotely`'s stored-error print has no test (correct by probe); N3: the git-URL branch of `cmd_index`'s identity rule has no test; N4: nothing pins the `hippo --help` import footprint (assert absences of `hippo.ingest.pipeline`, `public_errors`, `managed_activation`, fastapi, starlette). Three small tests for the wrap-up.
- Phrasing: an already-mapped `ToolError` from the MCP code tools is never lost to a raw exception or a masked crash, but it CAN be superseded by a denial from the trailing validate (intended); fix the sentence in `evidence-pa4cfix.md`.
- Three copies of the `authorization_changed` literal exist (`mcp_server.py`, `cli.py`, `web/app.py`) because the CLI keeps knowledge imports out of its top level; consolidate only if it can be done without dragging imports into `hippo --help`.

## From the 4c follow-up's done summary (merged `c9404ed`)

- `evidence-pa4c.md` deviation 5 still says the stored-error print was "already closed"; only the managed lane had been checked. The follow-up's `_stored_error` (both CLI print sites) now prints only closed codes; amend that evidence line in the wrap-up review.
- `pipeline.py:146/:216-221`: the 4c review's F5 "better option" (raise a dedicated closed validator type instead of a bare `ValueError` so MCP and CLI agree by type) remains open; 4e owns `pipeline.py` and may take it if cheap, otherwise the Task 4 wrap-up review carries it.
- `build_interrupted` maps to `operation_failed`/500, not 409: an interrupted refresh leaves the published generation serving, so a rebuild-required claim would be false.

## Remote-client rule (decided 2026-09-12 during the 4c follow-up)

- The remote client prints a 4xx body's `detail` (bounded validator/lookup text such as a symbol name) and prints the fixed `operation_failed` sentence plus the HTTP status for every 5xx and every unparseable or code-less non-4xx body; it never falls back to a raw `error` string. Residual: the `except ValueError -> HTTPException(400, str(exc))` sites at `web/routes/code.py:217` and `web/routes/api.py:50/94/117` use an isinstance catch, so a `ReadError`/`TooLarge`/`ProjectionError` subclass message (bounded per the 4c review's enumeration, but not the closed validator set) can reach a 4xx `detail`. Tighten those catches to exact types in the Task 4 wrap-up (4b-i owns `api.py`, the 4b-ii follow-up owns `code.py`).

## Wrap-up items from Task 4c (`evidence-pa4c.md`)

- Gated `hippo index` passes a reader actor but sets no `owner_id`/`access_role_id`, while `hippo_remember` sets both; decide whether CLI-created sources should be owned by the token's principal (likely yes) in the wrap-up.
- `add_repo` takes no `build_actor` (repositories are legacy by plan), so a gated `hippo index <git-url>` stays legacy; the identity rule still applies.
- Activating the reader actor moves accepted plain inputs to the managed lane, which resolves an embedding profile the legacy lane never asked for: on a deployment without `/api/show` metadata, a gated `hippo index note.md` or `hippo_remember` now reports `model_unavailable` where legacy used to succeed. Intended; document it in the release notes / README (Task 16) and in the plan's rollout section.
- `mcp_server._code_answer` (~:420-439) calls `validate()` again in a `finally` AFTER the `try/except` that maps into `tool_failure`, so an `AuthorizationChanged` raised only by that second validate (revoked during a successful build) reaches the caller raw instead of as `ToolError(DENIED)`; `test_lookup_snapshot_lifetime[revoke-mcp_path]` and the MCP rows of `test_code_path_surfaces_validate_error_output` currently pin the raw form. The 4c reviewer decides whether the contract requires mapping the finally path too (one small change plus two test updates).
- `tool_failure` passes exact-type `ValueError` text through (for `AmbiguousSymbol`/`UnknownSymbol` candidates); the 4c reviewer enumerates what else can reach a client verbatim.
- `remote.py` no longer passes `timeout=` to an injected client (the cause of the fourteen `test_cli.py` failures); a real client still gets the bounded probe.

## Final cleanup batch (opus-16, `wp/cleanup4`) decisions

- The `str(exc)` grep test is an allow-list: the two leak sites (`sources.py:~508` RepoError, `evals.py:~373`) and wrap-up finding 10 (`graph.py:~386`) get exact-type guards; every other remaining site is pinned by name with the wrap-up review's classification (protected legacy validator, or deferred to "when users.py is next owned"), so any new `str(exc)` under `src/hippo/web` fails the test. `users.py`/`auth.py` (finding 18) stay deferred per the review.
- Ownership extensions granted: `evals/question_maker.py` + its test (item 1b), the one assertion in `test_ingest_pipeline.py:167` (item 2), and `ingest/repos.py:88-113` for bounding `_explain_git_failure`.
- Wrap-up finding 1's premise was wrong at the route: `pipeline.add_repo` raises `RepoError` only for the not-a-git-URL case (the caller's own input plus a fixed hint, a protected legacy validator); the path and git stderr strings reach the Source row via `_legacy_failure`, never that 400. Decision: bound `_explain_git_failure` at its source (reason clause only; full text at `log.warning`), keep the hint at the 400, guard the route so only that shape survives.

## From the 4e web wrap-up (`evidence-pa4e.md`, merged `65fbcab`)

- Logging decision (F2 of the 4b-i review): local logs at INFO/WARNING carry the operation id and the exception CLASS only; the traceback stays at DEBUG tagged with the same id. The plan forbids unknown exception strings in logs, and 4b-i's redaction test enforces it at INFO. Do not "fix" this by adding `exc_info=True` at WARNING.
- The MCP code tools' session acquisition is already inside the mapper since the 4c follow-up (`c9404ed`); 4e's base predated it, so its open item 2 is closed by the merge.
- Open: `pipeline.py:~392` raises a bare `ValueError` where a `ReadError` would restore the "no readable text" sentence under the closed-validator rule (one line); 18 `str(exc)` sites remain in unowned web files (`users.py`, `analyze.py`, `evals.py`, `auth.py`, `pages.py`, `graph.py`), to be classified by the wrap-up review as protected legacy validators or leaks; `web/routes/analyze.py` and `graph.py` still bind `retrieval_session` at import. These form the final cleanup batch after the wrap-up review.
- Neo4j: the `mark_interrupted_jobs`/`release_interrupted_build` lane on Neo4j is being run by the orchestrator (`neo4j-parity.md` run 3).

## From the 4f evaluation wrap-up (`evidence-pa4f.md`, merged `b5a5086`)

- Done in 4f: public failure reason on results, runs and sets (code as the first segment of the stored error; `EvalAccess` exposes `failure_code`, nulls `error`); `ask._dispatch` folded into `dense_session.retrieval_session` with the access-versus-session precedence explicit; bounded per-question log line; fact-bearing question-maker corpus; `errors` card on the run page. Decision 5 (late-bound `rag_all.py` dispatch plus the dispatch-mode test) and two cheap open findings (the `run_status`/`set_status` partial titles; the two remaining `log.exception` calls) are sonnet-4's.
- Still open: `web/routes/analyze.py` and `graph.py` bind `retrieval_session` at import, so `test_managed_web_surfaces.watch` needs its own patch point; late-bind both after 4e merges (small task, or the layering worker). `answer_withheld` still conflates a withheld answer with a failure that saved a trace (contract question for Task 16). `summarize`'s gold means skip failed questions, so `accuracy: None` can sit beside `errors: N` (pre-existing, correct; document in Task 16's release notes).

## Wrap-up items from Task 4d (`evidence-pa4d.md`)

- Ladybug returns extracted facts in arbitrary order, so `view_fingerprint` of an unchanged corpus differed between loads on the primary backend. FIXED at `e709aad` (canonical fact order by `Fact.id` at the three `GraphIndex` construction sites; `evidence-factorder.md`). Consequences: every `evidence_fingerprint` persisted before the fix is stale (nothing to migrate; generated eval sets created earlier deny until recreated); cross-backend fingerprint equality is not meaningful because passage IDs derive from the store-assigned source ID, but each backend is now self-consistent across loads. The sibling defect (arrows within a code vertex in store order) is being fixed on `fix-code-arrow-order.md` (sonnet-3).
- No public surface names an evaluation run's retrieval failure, and a reader sees no count either (4d review finding 3): `errors` is not in `SUMMARY_CARDS` (`web/routes/evals.py:53-64`), `run_body.html:42`'s error pill is dead because `eval_access.py:378` nulls `error` unconditionally, and `get_question_set` does the same at `:305` so `eval_set.html:18` is dead too. A gap, not a leak. Three-part fix for the wrap-up: the runner stores `public_failure(exc).code` in a closed field beside `error`; `EvalAccess` passes that code through instead of nulling; the templates render it and `errors` joins the cards.
- `ask._dispatch` is imported privately by `analysis/simulate.py` and `evals/runner.py` (two importers; `evals/rag_all.py` imports `retrieval_session` directly). Promote it by folding the pass-through into `retrieval_session` in `dense_session.py`, not by an alias in `ask.py`; the promotion must audit `runner.py:106`, `rag_all.py:392-397` and `web/routes/analyze.py:319-327`, which pass access plus session, because `_dispatch` silently drops the access where `dense_session._session:178` raises `invalid_borrow`.
- 4d review finding 4: restore a fact-bearing corpus in the question-maker activation test now that the fact-order fix (`e709aad`) has landed. Finding 7 (pre-existing): `runner.py:209` logs the question text and full exception; bound it in the wrap-up.

## Wrap-up items from the 4b-ii review (`ai_docs/reports/2026-09-11-pa4b2-review.md`)

- Finding 8 (latent, becomes live with managed ingestion): `knowledge/access.py:253` returns no identity for a preview audience, so `/graph?as_role=` previews a managed corpus as EMPTY whatever the tier can see. Decide in the wrap-up whether preview audiences get a synthetic membership-free proof over managed evidence or an explicit "preview shows legacy evidence only" notice.
- Finding 4: `graph.py:337` duplicates `query_access.py:124`'s settings merge; factor a shared `effective_settings` helper when `query_access.py` is next owned.
- Finding 7: `retrieval_failure`'s total fallback would turn `EvalAccessDenied` (a `ValueError`) into `operation_failed` if `_simulate` ever called an unguarded `EvalAccess` method; unreachable today; keep in mind for 4d follow-ups.
- Finding 9: `test_query_authorization_boundary.py:219` monkeypatches the private `ctx._build_structural_graph`; add a public seam in `context.py` when it is next owned.
- Decision 6 sharpened: verified dense over HTTP by a reader audience AND revocation on the verified lane are both untested (fixture-blocked by the `legacy_unknown` policy); the `local_curated` verified fixture item now carries the revocation half too.
- Finding 1 (five unmapped routes) and the cheap findings 2, 3, 5, 6 plus the simulate empty-corpus seam are being fixed on `fix-pa4b2.md` (opus-11).

## Wrap-up items from Task 4b-ii (`evidence-pa4b2.md`)

- The only verified-evidence fixture in the tree (`tests/unit/test_staged_prose_writer.setup`) stamps `AccessPolicy(origin='legacy_unknown')`, which `knowledge/access.py:370` refuses for every audience except internal, so verified-lane web cases are direct route calls with an internal principal rather than HTTP. A `local_curated` verified fixture (built with the coordinator or `input_binding`) would let them run over HTTP; schedule with the Task 4 wrap-up review.
- A managed row whose build failed on `AuthorizationChanged` renders `operation_failed`; narrowing belongs in `managed_activation._MANAGED_CODES` (Task 3b's file), not the renderer.
- `graph_page`'s preview branch deliberately renders two audiences (previewed tier body, actor header); the 4b-ii reviewer checks it for cross-audience leakage.

## Layering follow-up (in flight on `wp/layering`)

- Decided 2026-09-12: the layering guard passes with a two-entry allowlist, each with a reason: `knowledge/input_binding.py` imports `PreparedChunk` from `ingest/prepared_chunks.py` (its value types are hard-bound to ingest readers: `UnsupportedProvenanceFormat` subclasses `readers.ReadError`, `ProvenanceDocument.to_document()` returns `readers.Document`), and `knowledge/public_errors.py` imports ingest exception classes for its closed table. Both are proven non-cyclic by the import-order test once `hippo/ingest/__init__.py` is lazy and `pipeline._managed()` is gone. Moving those types is a later refactor, not a correctness item.

- `hippo.knowledge.generation_profiles` (and `input_binding`) import `hippo.ingest.accepted_inputs` / `hippo.ingest.provenance`, so `hippo.knowledge` depends on `hippo.ingest` while `hippo.ingest` (coordinator, managed lane) depends on `hippo.knowledge`. The cycle surfaced at `c668688` when `pipeline.py` imported `managed_activation` eagerly; fixed at `da51784` with a lazy accessor plus `tests/unit/test_import_order.py`. The proper fix is to move the shared input contracts (`ByteInput`, `FileInput`, `ExcludedInput`, `CaptureLimits`, `AcceptedInputs`, `InputDisposition`, `RawInput`, `MANIFEST_EXTERNAL_ID`) into `hippo.knowledge` (or a leaf module neither package's `__init__` imports) so knowledge never imports ingest, and to stop `hippo/ingest/__init__.py` importing `pipeline` eagerly. One small worker, after Task 4, with the import-order test as the gate.

## 5A part 2 fix notes (opus-13, in flight)

- Review F2's premise was wrong: `validate_generation_seal` (`generations.py:703-710`) already refuses any member `AssertionVersion` whose complete `AssertionSupport` group is not also a member, and publish calls it before `_validate_publication_plan`; the `:914` check is defense-in-depth. Fix records this with an end-to-end refusal test, a white-box `_validate_publication_plan` test that fails if `:914` is removed, and an evidence/plan note. F1 (capability boundary), F3–F6 proceed as decided.

## Pre-Task-3 store increment (schedule after wp/pa1 merges)

- "Per-thread transaction ownership": coordinator review finding 3. The ambient-transaction probes at `prose_generation.py:~652` and `build_authority.py:167-168` read the process-global `_transaction_depth/_transaction`, which is nonzero for every thread while any thread holds a transaction (all three stores lock the whole transaction body, e.g. `ladybug.py:378-384`). Fix: stores record the owning thread when a transaction opens and expose `in_ambient_transaction()` (true only for the calling thread); both probes use it; the skipped test the coordinator fixer adds becomes RED then GREEN. Files: `store/base.py`, `store/ladybug.py`, `tests/fakes/fake_store.py`, `knowledge/build_authority.py`, `ingest/prose_generation.py` (probe line only), plus tests. Must land before activation Task 3 dispatches concurrent builds.
- Also carry from that review: minor 9 (authority checks full-scan Artifact and Generation tables in `build_authority.py:70-75`, run 2-3x per progress tick; the 148x Fake-vs-Ladybug gap) is a performance item for the same increment or Task 3; minor 7 (PlainBuildOptions lacks the plan's pipeline/parser/materializer version fields) was not recorded by the fixer; its two sentences are written into the coordinator plan's "Coordinator implementation notes" by PA8 closure batch 2 (`wp/pa8close2`, 2026-09-13).

## Merge checklist (orchestrator)

- When merging `wp/pa1` into `rag-it-all-tibs` (after the coordinator commit): run `tests/unit/test_prose_generation.py` and `test_build_authority.py` on Fake. Local memberships now auto-exist for every user (enabled, policy_epoch=1, authority `local`), so root-tree tests that create a local membership by hand or rely on a missing membership to deny may change. backend-developer-1 lists the expected blast radius in `evidence-pa1.md`; the coordinator fixer (not Task 1) adapts `test_prose_generation.py`.
- Both `wp/pa1` and `wp/pa2` edit `tests/unit/test_status_access.py`: pa1 removes hand-written `reviewed` membership + `set_meta` fixture lines (112 "Immutable record already exists" collisions across seven test files once `create_user` auto-creates a `local` membership); pa2 changes assertions and adds AnyIO markers. Expect a clean auto-merge; if not, keep both sets of hunks.
- Tombstone replay contract: reader replay gets the generic `AuthorizationChanged`; trusted-local replay re-checks via `require_source(query_mode='history')` and matches the tombstone suppression by reason/applicability/scope_key/restoration_barrier==operation_id, returning `already_tombstoned` with the original epoch and no write.
- From pa2's done summary: `test_cli.py` has a SECOND pre-existing `-W error` failure class (14 tests): `StarletteDeprecationWarning: You should not use the timeout argument with the TestClient`. Task 4c (CLI/remote) must fix the test usage (drop the `timeout` argument) rather than filter it. Proven pre-existing at clean 26f9a55.
- From pa2: the non-structural managed lane still requires every selected generation's embedding profile to equal `ctx.ollama.embed_model` (`_current_generations` raises `ProjectionError` otherwise); Task 4a's structural default flip removes that coupling. Adding pairs to `view_fingerprint` invalidates saved trace/eval fingerprints once for managed corpora (intended); legacy payloads are byte-identical.
- Reusable fixture: `empty_published()` in `tests/unit/test_managed_source_inventory.py` builds a real empty generation (Artifact + ArtifactRevision + GenerationMember, zero EvidenceSpans) that seals and publishes; `published(original_passage=False)` in `test_structural_loading.py` cannot. `retrieval_session` on an empty corpus makes zero HTTP calls; `dense_session` alone makes six, so "no Ollama call" assertions belong on `retrieval_session`.
- From the Task 2 review (`ai_docs/reports/2026-09-11-pa2-review.md`): `tests/unit/test_rag_replay_access.py` needs the per-test AnyIO marker (function-level imports, form (a)); `canonical_selected_generations` raises bare `ValueError` while `_assemble`/`compose_graphs` raise `ProjectionError`, so Task 4a's public error mapper must catch both or the field validator must raise `ProjectionError`; `status.py:104-109` attributes inherited code-edge kinds by node membership rather than exact pair (latent until managed code generations exist); `_audience_inventory`/`visible_source_count` now do structural loading on every status and MCP-identity call, worth measuring in Task 4; `dense_session` resolves the profile unconditionally (`strict=True` at `dense_session.py:199`) so Task 4 must route empty corpora through `retrieval_session`, which makes no model call.
- From the Task 3a review (`ai_docs/reports/2026-09-11-pa3a-review.md`): two definitions of "managed" coexist (`managed_eligibility`/`legacy_source_cleanup` use `source['managed']`; `build_authority._source_control` uses a broader disjunction), safe today because `begin_managed_source` commits with the first Artifact/Generation write; make it one definition when a future slice touches both. `plan_dispatch` RAISES for a managed source without an actor but RETURNS `Dispatch('skip','tombstoned')` for a tombstone; routes must map the former to the generic denial. Task 3b absorbs the review's test fixes, `synonymy_threshold` validation and the restart sweep for interrupted refreshes.
- Decision 8 (Task 1 follow-up): the public `ensure_local_workspace_memberships` never bumps the authorization epoch; plan amended.
- Sanctioned single-workspace policy worth revisiting when provider/group mappings land (Task 9+): startup re-adds `local` to `reviewed_mapping_authorities` and repairs a non-local enabled mapping back to `local`, so there is no durable way to un-map a local User; disabled Users still receive an enabled membership (fail-closed at `BuildAuthority._actor_access`).
- `test_status_access.py` and `test_web_base.py` need the AnyIO filter marker before any `-W error` gate line that includes them can pass; Task 2 covers the first, Task 4a the second.

- `web/routes/sources.py` `reindex_all` calls `source_view(ctx, access)` and then `view.validate()` AFTER `pipeline.reindex_all`. Task 2 keeps `source_view`'s session=None acquisition mechanism (now structural) so this still works, but the route must become a single-owner session in Task 4 (PA5). Task 2's evidence file records it.
- Task 2 deliberately keeps `error` withheld on managed rows. Task 3 adds the closed exception-to-status mapper in `managed_activation.py`; Task 4 (or 3) renders the mapped generic error on managed rows and updates the status test.
- Task 2 flips `status._audience_inventory` to `structural=True` locally. The global `query_access(..., structural=True)` / `query_session(..., structural=True)` default flip remains Task 4a.
- Task 1 put the membership hook inside `store/authorization.py::permission_mutation` (create_user after the wrapped call, delete_user before). Task 4's `web/routes/users.py` changes must not add a second epoch-owning wrapper around those.
- `tests/fakes/fake_store.py` gained one startup-hook line in `ping()` (Task 1). FakeStore has no `on_first_connection`.

## Queued after the PA8 closure batch (2026-09-12)

- PA2 finding 5 (a relation supported by two generations) needs an INTERLEAVED fixture: two sources
  staging concurrently, both enriching the same `(assertion_version_id, derivation_group)` proof group,
  then both sealed and published. Sequential publication is refused by design (`generations.py:~601`
  "Sealed assertion proof group cannot gain support"). opus-17's `evidence-pa8close.md` has the repro and
  a ~60-line fixture design based on `test_structural_loading.published()`. Owner: a dedicated small task
  after `wp/pa8close` merges (orchestrator to write the brief).
- RULED 2026-09-12 (opus-20's probe, `/tmp/hippo-pa2f5-probe.log`): PA2 finding 5 is UNREACHABLE BY
  DESIGN. A proof group spanning two sources cannot be sealed: seal requires every AssertionSupport row of
  a membered AssertionVersion to be in that generation's exact set ("Incomplete assertion proof group",
  `generations.py:~1001`), a joiner without membering fails "Incomplete exact interpretation closure"
  (`:~993`), sequential joining fails "Sealed assertion proof group cannot gain support" (`:~690`), and no
  generation may hold another source's revisions (`store/knowledge.py:~690`). So
  `len(source_generations) > 1` never holds for a sealed exact generation and `status.py:~142`'s
  multi-pair branch is dead code (simplify in a later slice; not touched now). `wp/pa2f5` pins the four
  refusals and the one-pair invariant. Also noted: `graph_index.py:~878` keeps a relation only if ALL its
  support spans are visible, so a shared proof would be fail-closed anyway.
- `wp/pa2f5` merged at `be1cfc0` (8 tests pin the refusals + the one-pair invariant, Fake and Ladybug).
  DECISION (orchestrator, 2026-09-12): the seal clause at `generations.py:~1001` STAYS. A relation's proof
  must lie wholly inside one generation's exact interpretation; a proof shared across two sources would
  make publication, tombstone and audience semantics cross-source, and `graph_index.py:~878` /
  `access.py:~466` are already fail-closed on a half-visible group. The dead multi-pair branch at
  `status.py:~142` (and `access.py:~445-447`'s cross-row grouping) is simplified in a later cleanup slice,
  not now. The PA2 CHECK line gains `tests/unit/test_multi_generation_support.py` at the next ledger edit
  (after checker run 2 finishes writing the file).
