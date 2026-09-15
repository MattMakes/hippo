# Independent SPEC and QUALITY review: managed code capture (gate CD10)

**Reviewer:** architect-reviewer-21 (herdr fleet, root tree, read-only except this report).
**Subject:** HEAD `cbed8ca` on `rag-it-all-tibs` (source identical at `79d171d`, which changed ledger
docs only) (CC1-CC11, cc11b and the fix slices cc1fix,
lbfix, kscope, codeproj, pa2f4, lbpool, qscope and lbconn merged), against
`ai_docs/plans/rag-it-all-task-5-managed-code-capture.md` (rulings 1-14 and the post-implementation
amendments), the design review `ai_docs/reports/2026-09-12-code-capture-plan-review.md`, the notes
`ai_docs/handoffs/briefs/code-capture-notes.md` and the ledger
`ai_docs/gates/rag-it-all/task-5-code-capture/GATES.md`.

**Method.** I read the code at HEAD, not the evidence. Six read-only helper passes, split by gate,
produced candidate findings. I opened every BLOCKER and MAJOR citation myself, and I confirmed four
BLOCKERs by running throwaway reproductions on the Fake store, from a copy of `tests/` under
`/tmp/h21scratch` so that nothing in the repository changed. I re-ran every CD CHECK line on Fake
with `-W error`, and the CD9 line plus the LadybugDB lines the evidence files claim, one LadybugDB
line at a time. I ran nothing on Neo4j; parity runs 1-9 are cited from `neo4j-parity.md`.

**Severity rule used here.** BLOCKER: a CRITERIA clause, ruling or brief invariant is false at HEAD
with a reachable functional, data-integrity or privacy consequence. MAJOR: a CRITERIA clause is false
as worded without such a consequence, a defect sits on a production path, or an authorization,
privacy or engine-persistence clause has no real test (a vacuous or tautological assertion counts as
none). MINOR: test depth where the code is verified true by reading, CRITERIA or plan drift,
duplication. The **Verified** column says how I checked each finding: `repro` (a Fake reproduction
failed as described), `read` (I opened the cited lines), or `helper` (reported by a helper pass and
not re-opened by me; MINOR only).

## Ledger conflict to resolve first

While this review ran, commit `79d171d` ("Record CD1-CD10 MET at cbed8ca and Neo4j parity run 9
for the acceptance scenario") ticked every box in the ledger, CD10 included. It changes only
`GATES.md` and `neo4j-parity.md`, so every finding below applies unchanged at `79d171d`. The ticks
record that the CHECK lines exit 0, which this review confirms. CD10's CRITERIA, though, is "independent
SPEC and QUALITY reviews pass with every finding closed", and this is that review: it does not pass.
By SPEC, CD1, CD2, CD3, CD5, CD7, CD8 and CD9 are NOT MET (table below), because their CRITERIA are false
at HEAD or their clauses are not asserted. Recommended: untick CD10, and untick or annotate the SPEC-failed
gates, until the blocking findings are closed and the affected lines are rerun.

## CD10 verdict

**NOT SIGNABLE.** Blocking findings: R21-B1 to R21-B5 (all five reproduced: four on Fake, R21-B5 on
LadybugDB) and R21-M1 to R21-M12. CD10's own text requires every finding
closed, so the 49 MINORs also need a fix or an explicit orchestrator deferral.

Counts: **5 BLOCKER** (all reproduced), **12 MAJOR**, **49 MINOR**.

## Findings: BLOCKER

| ID | Verified | Where | Gate / ruling | Failure | Exact fix |
| --- | --- | --- | --- | --- | --- |
| R21-B1 | repro | `knowledge/staged_code.py:353-362` (`bindings = {(native_kind, native_id): binding ...}`), `:611-620` (`_inventory`); `knowledge/model.py:614` (`NativeBinding` identity includes `span_id`) | CD7 "sealable"; CD8 "an authenticated actor converts an eligible repo, archive or code file"; CD9 | `_groups` writes one `NativeBinding` per native row, while the bundle carries one per observing `(object, span)`. `build_code_source` therefore fails at the seal with `Exact NativeBinding inventory differs from prepared coverage` for ordinary trees. Reproduced shapes: a Python function longer than `chunk_size_chars=1500` (24 bindings over 13 native rows), a C# file with overloads (18 over 15), a SQL table defined in `db/schema.sql` and referenced from Python (22 over 21). The CD9 fixture (`tests/fakes/code_capture_repo.py`) contains none of these shapes: every language template is under about 300 characters, the C# template (`Ledger{i}`: `Place`, `Scale`) has no overload, and each SQL template defines and selects its own table inside one file. | Write every binding of a native row: key `bindings` by `(native_kind, native_id)` to a tuple, put all of them in the row's group, probe each. Add the three shapes to `test_staged_code_writer.py`, `test_code_generation.py` and the CD9 fixture. |
| R21-B2 | repro | `ingest/code_generation.py:739` (`_install` always calls `bind_generation_embedding_profile`); `store/generations.py:493-494` | CD8 "a crashed build resumes the same generation"; plan amendment "§10, failure, crash and costs" (seal-to-publication crash "publishes") | Any failure after `_seal` (a crash, cancellation, heartbeat failure or the publication window's epoch refusal) leaves a `failed` generation holding its `IndexManifest`. `_instant` adopts it, reclaim admits it, and every retry raises `A sealed profile cannot be rebound` inside `_install`. The generation ID is input-derived, so the source stays stuck until its tree changes. | Smallest fix: in `bind_generation_embedding_profile`, move the `IndexManifest` refusal (`:493-494`) after the `verified_v1` early return (`:496-497`), keeping `validate_generation_profile`, so rebinding an identical sealed profile is a no-op. Alternatively skip the bind in `_install` for a `verified_v1` generation with the same pointer. Add a coordinator test that faults between `_seal` and `_publish` and asserts the retry publishes the same generation ID. |
| R21-B3 | repro | `knowledge/staged_code.py:217-226` (`relations` keys `CODE_EDGE` by endpoints only), `:363-364` (relation probe record `None`), `:531-535` and `:640-646` (probe and inventory compare `(rel, a, b)` sets) | CD7 "the resume probe checks every row of a group against its canonical payload"; "missing ... rows refuse the seal" | Two `CODE_EDGE` kinds on one pair are ordinary: `CONTAINS` and `INVOKES` for a module-level `main()` call, `READS` and `WRITES` for a function that selects and updates one table. A crash between their two groups makes the probe skip both, and the generation seals and publishes without `INVOKES` (reproduced, `resumed_from_batches` 92) or `WRITES` (88). A staged relation with a different `omega`, `provenance`, `extra` or hunk is also skipped. | Key `CODE_EDGE` by `(a, b, kind)` in `relations`, `_groups`, `_persisted` and `_inventory`; carry each relation's canonical payload in its probe and compare it in the probe and at the seal. Add the two-kinds crash test. |
| R21-B4 | repro at function level (`find_synonyms` then `add_synonyms`, the two calls `index_source` makes in sequence), not end to end through `pipeline.add_text` | `hipporag/indexer.py:250-258` and `:390-391`; `store/code.py:673-682` (`load_code_embeddings`, no generation filter); `store/generations.py:1766-1776` | Brief invariant "the legacy lane's behaviour for non-managed sources is byte-identical" (CD1, CD2); ruling 14 "only untagged rows serve the legacy lane" | The legacy indexer's synonym pass reads every Symbol and DataObject name vector, including managed code rows, and writes the pairs through `add_synonyms`. Reproduced: `find_synonyms` returned 3 pairs touching a published managed symbol, and `add_synonyms` raised `Sealed native payload or relationship is immutable`; against a staging generation `_assert_generation_writable` refuses instead. After any repository converts, a never-managed source whose entity names match a managed symbol fails to index. | Restrict the legacy synonym key matrix to untagged rows (`generation_id IS NULL`) on every backend. Test: index a legacy source while a staging and a published code generation hold a matching symbol; it succeeds and writes no `SYNONYM` touching a tagged row. |
| R21-B5 | repro on LadybugDB (Fake control keeps both kinds); Neo4j by the same non-Fake branch at `:857-863`, not run (root-owned) | `store/generations.py:857-863` (non-Fake `_edges_touching` de-duplicates on `(a, b)`); `store/code.py:436-447` and `tests/fakes/fake_store.py:607` keep one `CODE_EDGE` per `(a, b, kind)` | CD1 "`_native_relationships` ... return exactly what the unscoped forms returned"; CD9 "projected arrows equal the selected generation's sealed native rows" | On LadybugDB and Neo4j the second `CODE_EDGE` kind between one pair is dropped from `_native_relationships`, the sealed native checksum, the projection and `status._with_code_edges`; Fake keeps both, so no Fake CHECK line can see it, and CD9's oracle reads through the same function. Reproduced on LadybugDB with a plain bootstrap (no crash): the published generation's relations lack `INVOKES` for a module-level `main()` call and `WRITES` for a function that selects and updates one table; the seal passes because `_inventory` compares through the same read. | Remove the `seen` set; in the `b`-driven pass skip rows whose `a` is already in `ids`. Add a two-kinds oracle case to `test_generation_scoped_reads.py` and run it on LadybugDB. |

## Findings: MAJOR

| ID | Verified | Where | Gate / ruling | Failure | Exact fix |
| --- | --- | --- | --- | --- | --- |
| R21-M1 | read | `store/generations.py:1612` (a `GenerationViews` per `native_write` call); `knowledge/derivations.py:115-122` (reads the generation's whole `GenerationEvidenceMember`/`GenerationMember` set); `knowledge/build_authority.py:245-258`, `:293-301` (every `check_local` re-reads each accepted pair and span and proves them); `ingest/code_generation.py:790-806`; `tests/unit/test_knowledge_scoped_reads.py:349`, `:400` | CD1 is internally inconsistent: its amendment discloses one inventory "built once per generation for a `native_write` call", i.e. per batch, and then claims "a managed code build is linear in its corpus"; the original clause says per-batch work is "bounded by the batch rather than by corpus size" | A per-batch read of the whole generation's membership, plus every `check_local` re-proving every accepted input, makes total work members x batches. KSCOPE's own numbers grow 1.9x per member from 10 to 160 files; `LINEAR_FACTOR = 3.0` admits it. | Carry one inventory across the batches of a build and extend it with each batch's writes; verify the immutable accepted records once per `BuildAuthority`. Rewrite the counter test as one batch at two corpus sizes counting rows returned, then tighten the factor. Or amend CD1 to state the per-batch generation-sized reads. |
| R21-M2 | read | `knowledge/access.py:393` (unbounded proof reads for a `revision_ids` selection), `:121-122` (`by_id` falls back to `whole`), `:427` (`by_id("KnowledgeObject", group ids)`); `knowledge/build_authority.py:144-146`, `:160-161` (`_Overlay` passes `KnowledgeObject` through whole) | CD1 "no generation-sized knowledge table is read whole" | When the build actor holds any enabled `GroupMembership`, every `check_local` (several per batch and per lease renewal) reads the whole `KnowledgeObject` table, which grows with every symbol, file and commit. No fixture has a group membership, the CD1 counter list omits `KnowledgeObject`, and neither kscope nor qscope names this read. | Pass `ids=` through `_Overlay._knowledge_rows` for live kinds and make `_ProofReads.by_id` keyed for `KnowledgeObject`; add `KnowledgeObject`, `Artifact` and `ArtifactRevision` to the counters' generation-sized list; give the counter tests an actor with a group membership. |
| R21-M3 | read | `knowledge/projection.py:710-723`; `tests/unit/test_code_capture_acceptance.py:491-501`; plan amendment "§4, the projection" | CD9 "projects `StructuralCodeEvidence` with exact original spans" | The projection emits no `StructuralCodeEvidence` for a node with a `DEFINED_IN` arrow into a projected passage, which is every bound node in the CD9 scenario; the exact-span loop runs over an empty mapping and asserts nothing. | Reword CD9 to "every code node carries structural support: a `DEFINED_IN` arrow whose `support_span_ids` hold its binding span, or a `StructuralCodeEvidence` row with exact original spans", and assert that shape (pin `sidecar == {}` for the scenario, or add a shared-node shape that produces a row and assert it). |
| R21-M4 | read | `tests/unit/test_build_authority.py:574-582`; `tests/unit/test_code_generation.py:819-843`; `knowledge/build_authority.py:384` | Ruling 2 "the between-batch test proves a removed capability still aborts"; CD8 "refuses after any capability loss" | Both tests also set `owner_id=None`, so the refusal fires at the `SourceControl` comparison before the child's capability proof runs. Deleting `child.check_local()` from `rebaseline` would leave both green. | Use a non-owner builder that manages the source through its role, change only the role's capabilities, match `cannot manage source`, and assert `rebaselines == 0`. |
| R21-M5 | read | `GATES.md:53` (CD8 CHECK) | CD8 rebaseline clauses (capability loss, suppression epoch, `access_role_id`/`min_rank`/`owner_id`, sticky failure, inside a transaction, never adopts) and "open, preview ... stay legacy" | Those clauses are asserted in `tests/unit/test_build_authority.py:542-658` and `:310`, which no CD CHECK line runs. | Add `tests/unit/test_build_authority.py` to CD8's CHECK. |
| R21-M6 | read | `knowledge/projection.py:338-362`, `:495-509`; no restricted-access case in `tests/unit/test_code_projection.py` or `tests/unit/test_status_code_edges.py` | Access boundary for the CODEPROJ read (plan invariant: one structural owner per query under exact evidence) | The code filters native relations through authorized bindings, but every test of that read uses an unrestricted principal; building `bound` from all of a generation's bindings would leak arrows to a suppressed symbol and nothing would fail. | Suppress (`target_kind="span"`) the binding span of a symbol with `CONTAINS`/`INVOKES` edges and assert no arrow or `support_span_ids` touches it; add a policy-denied file variant. |
| R21-M7 | read | `web/routes/sources.py:178-192` | CD2 "keeps its complete legacy passages, code nodes and edges in every query" | The source page branches on the `managed` flag, which is true from staging start, so a converting source's page renders its legacy passages with `triples: []`, `entities: []` and no extraction error. No test requests the page for a converting source. | Branch on membership of the view's legacy lane and read the untagged passages with their triples for a converting source; test the page before publication. |
| R21-M8 | read | `ingest/repo_capture.py:508-510` (budget set built by `_wanted_member`, `:540-547`, which needs a supported name), `:525-533` (`_member_reason`/`_name_reason`, `:429-437` and `:550-562`, admit extensionless names, which are then read into memory), `:364` (file count checked after the walk) | CD3 "bounded" | An uploaded `.zip` of many extensionless members, each under the per-file cap, is read whole into memory outside `check_zip_budgets`, before any count or total check. | Build the budget set from the same acceptance rule as `_member_reason`, or check running count and bytes before each `package.read`; add a test that lowers the budget. |
| R21-M9 | read | `ingest/repo_capture.py:514-533` | CD3 "symlinks, submodules and non-regular files each carry a distinct recorded reason"; ruling 7 | Archive members are never classified by `external_attr`: a symlink member is captured as a text file holding its target path. No escape (nothing is followed), but the clause is false for archives. | Record `symlink` for `S_ISLNK(member.external_attr >> 16)` and `not_regular` for other non-regular types; test with a `ZipInfo` carrying `(S_IFLNK \| 0o777) << 16`. |
| R21-M10 | read | `ingest/pipeline.py:179-183`, `ingest/repos.py:75-79` (URL in the `RepoError` message when `is_git_url` fails); `web/routes/sources.py:427-428` (`RedirectResponse(f"/?error={exc}")`, unquoted); `cli.py:286` (default uvicorn access log) | Plan §10 privacy; amendment "§10, privacy" lists three remaining limits and not this one | A credentialed URL that fails `is_git_url` (a host without a dot, `git+https://`) lands in the 400 body, the redirect `Location` and the access log line. Pre-existing (`e8c68836`, 2026-09-06), not introduced by the slices. | Drop the URL from both messages, `quote()` the redirect, and test both spellings against the body, the header and `caplog`; or record it beside the legacy `meta.url` limit for Task 16. |
| R21-M11 | read | `.github/workflows/ci.yml:25-40` (`pytest tests/unit -q` with `store: ["ladybug", "fake"]`); `tests/unit/test_code_capture_acceptance.py:74` (default 48 files per language) | CI health; CD9 note that the ledger size is unevidenced | CI runs the acceptance scenario at the ledger size on LadybugDB, a size that has not completed anywhere. | Set `HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE=8` in the CI job, or make the ledger size opt-in. |
| R21-M12 | read | `knowledge/code_binding.py:889-903` (`_by_native_id`), `:1077-1085`; plan amendment "§4, data objects, mentions and overloads"; `tests/unit/test_code_binding.py:672-697` | CD5 "overloads do not merge"; exact-evidence contract | Every passage naming a shared overload ID observes every overload behind it: `Move(string)` is observed on `Move(int)`'s span. The amendment says "two knowledge objects and two bindings"; there are four bindings and two wrong observations (recorded honestly only in `evidence-cc6.md`). Once R21-B1 is fixed, those wrong observations will seal. | Bind a node only from the passage whose original lines contain the node's lines, or rule a deferral and correct the amendment and CD5; pin the binding and observation counts in the test. |

## Findings: MINOR

| ID | Verified | Where | Gate | Finding and fix |
| --- | --- | --- | --- | --- |
| R21-m1 | helper | `tests/unit/test_generation_scoped_reads.py:664-689`, `:720-741` | CD1 | Ceiling test is an absolute bound; the ratio test's 0.01 s floor admits O(n^2) at n=400. Use larger sizes and no floor; add rendered views to the ceiling fixture. |
| R21-m2 | read | `store/generations.py:914-940` | CD1 | No test exercises the SUBJECT/OBJECT second hop or `Missing shared graph endpoint`. Add oracle cases. |
| R21-m3 | helper | `tests/unit/test_generation_scoped_reads.py:382-401` | CD1 | Tripwire regex is case- and whitespace-sensitive and top-level only. Match `(?i)\bIN\s+\$` over whole sources. |
| R21-m4 | helper | `ingest/code_generation.py:639`, `ingest/prose_generation.py:233`, `context.py:243` | CD1 | Whole `IndexEvent` reads on the already-published path and whole `Artifact` per graph build; "generation-sized" is defined only by a test list. Scope by generation and name the list in CD1. |
| R21-m5 | helper | `store/generations.py:1022-1029`; `knowledge/derivations.py:178-180` | CD1 | `AssertionSupport` whole per `AssertionVersion` member; observation re-read per binding dependency (unreachable from today's lanes). |
| R21-m6 | helper | `store/generations.py:831-837` | CD1 | Fake `_edges_touching` iterates live dicts outside `_lock`; no concurrent reader found today. |
| R21-m7 | helper | `tests/unit/test_converting_source_serving.py:39-112` | CD2 | Staged `Symbol`/`DataObject`/`Commit` absence is asserted only through a two-snapshot hook. Stage them in `stage()`. |
| R21-m8 | helper | `tests/unit/test_status_access.py:41-136` | CD2 | Denied reader on a converting source is tested on a mocked store only. Add a real-store case. |
| R21-m9 | helper | `tests/unit/test_converting_source_serving.py` publication test | CD2 | "One transaction" asserted by end state only. Fault inside the code lane's `_publish` transaction. |
| R21-m10 | helper | `store/generations.py:111-116` | CD2 | The all-principals suppression term has no direct predicate test. |
| R21-m11 | helper | `status.py:250`, `:346`; `cli.py:353-354` | CD2 | `store.stats()`, `visible_source_count` and the CLI count staged rows; CD2 says "any query result". Qualify CD2 or count from the held graph. |
| R21-m12 | helper | `changeset_access.py:170` | CD2 | Last unfiltered `ctx.graph()` caller; gated by `_visible_ops`. Use the filtered graph. |
| R21-m13 | read | `context.py:43-51` | CD2 | `_owns_untagged_rows` fetches every untagged row of a kind to test existence. Add a limit-one read. |
| R21-m14 | read | `ingest/code_generation.py:378` | CD3 | "Every later read is from the captured raw object" is true by reading but untested. Rewrite the checkout after capture and assert identical passages. |
| R21-m15 | read | `ingest/repo_capture.py:106` | CD3 | `_SCP_LIKE` accepts `user:pass@host:path` (unreachable: `is_git_url` rejects it). Refuse and parametrize the credential test over five spellings. |
| R21-m16 | helper | `ingest/repo_capture.py:494-496`; `ingest/code_generation.py:314` | CD3 | Walk-time binary and size decisions go stale before the copy; `tree.paths` walks twice. |
| R21-m17 | helper | `tests/unit/test_prepared_code_chunks.py` | CD4 | Seeded corpus is ASCII-only with overlap 0; digest/version tie is one-way; rich-input rejection untested. |
| R21-m18 | helper | `ingest/managed_activation.py:559-570` | CD3 | Code-lane capture refusals map to plain-prose sentences. Add code-lane rows. |
| R21-m19 | helper | `ingest/code_generation.py:477` | CD3 | At exactly 50,000 symbols `extract_code` truncates without tripping `> max_symbols`. Refuse on `facts.truncated`. |
| R21-m20 | helper | `ingest/pipeline.py:504` | privacy (legacy) | Legacy history warning logs `HistoryError` text with the checkout path and git stderr. |
| R21-m21 | read | `ingest/repo_capture.py:512` | CD3 | `archive_budget` refusal message is `str(TooLarge)`, which names the archive. Use a closed sentence. |
| R21-m22 | helper | `ingest/prepared_code_chunks.py:43-72` | QUALITY | Imports 18 private chunker helpers; fragile coupling contained by the parity latch. |
| R21-m23 | read | `ingest/code_generation.py:414`; `tests/unit/test_code_generation.py:950` | CD6 | The shallow boundary is never checked on a real shallow clone, although managed clones are always shallow. Assert `shallow_boundary(clone)` in `test_git_history.py` and a non-empty coverage value in one coordinator build. |
| R21-m24 | read | `knowledge/code_binding.py:464-501`, `:961-962` | CD5 | Refusal branches untested: binding without an observation, observation/view/dependency outside the bundle, extra evidence member, Symbol/DataObject namespace mismatch; merged-bundle refusals mostly untested. |
| R21-m25 | read | `GATES.md:44` | CD6 | "`PRECEDES` pairs bind only to symbols" should read "commits". |
| R21-m26 | read | `knowledge/code_binding.py:134-146` | CD5/CD7 | `_reuse` compares four fields; a changed history rule would silently keep a stored revision's old spelling. Compare the whole record except `observed_at`. |
| R21-m27 | read | `knowledge/code_history.py:148-153` | CD6 | `_offset_text` re-derives the offset (`Z` becomes `+00:00`) contrary to "unparsed"; add `-08:00` and `-03:30` cases. |
| R21-m28 | read | `knowledge/code_history.py:615-625` | CD6 | The merge's configuration guard reads a copy not tied to `manifest_hash`, and the merge refusal is untested. |
| R21-m29 | helper | `tests/unit/test_layering.py:28-33`; `tests/unit/test_import_order.py` | QUALITY | Layering regex misses `from hippo import ingest` and `import_module` strings; import-order `MODULES` omit the two code modules. Clean today. |
| R21-m30 | helper | `knowledge/input_binding.py:294`, `knowledge/code_binding.py:561`, `knowledge/code_history.py:826` | QUALITY | `_view` exists three times; merged-bundle validators have drifted from the code bundle's. Move one helper into `knowledge/derivations.py`. |
| R21-m31 | read | `tests/unit/test_code_generation.py` | CD8 | No code-lane test changes the authorization epoch in the publication window (only prose, `test_prose_generation.py:804`). Add one; with R21-B2 fixed, assert the retry publishes. |
| R21-m32 | read | `tests/unit/test_code_generation.py:596-606`, `:748` | CD8 | Refresh test samples the pointer in the write phase only; no refresh cancellation test. |
| R21-m33 | read | `ingest/code_generation.py:794-795`; `tests/unit/test_code_generation.py:893-906` | CD8, plan §8.3 amendment | The batch payload ceiling refuses after `_install`, while the amendment says every ceiling refuses before install; the test asserts only "not active" and its `max_chunks` row accepts any `Exception`. |
| R21-m34 | read | `ingest/code_generation.py:931`, `:948`, `:974` | CD8 | `already_current` is reached after one embedding probe and raw capture; CD8 and §10 say "without inference or writes". Qualify the text or reorder (prose has the same order). |
| R21-m35 | read | `knowledge/build_authority.py:279`, `:384` | CD8 | `SourceControl` is compared whole (safe); docstring, amendment and tests name three fields. |
| R21-m36 | helper | `ingest/managed_activation.py:418`, `:702`, `:713` | CD8 | CD8's "`shutil.rmtree` ... never called" overclaims: the adapter removes its own checkout. Qualify as "outside the named checkout", as CD2 does. |
| R21-m37 | helper | `tests/unit/test_generation_profiles.py:343`, `:443` | CD7 | Plain-prose byte identity is proven relatively; pin a digest. |
| R21-m38 | helper | `ingest/code_generation.py:685-756`, `:820-856`; `knowledge/staged_code.py` vs `knowledge/staged_prose.py:15-48` | QUALITY | `_install`/`_publish` and the writer's epoch/local helpers are near-copies of the prose lane; R21-B2's fix is needed in both. |
| R21-m39 | helper | `ingest/managed_activation.py:599-605` | CD7 | The M2 remediation ("explicit failed-generation cleanup") never reaches an operator or log. |
| R21-m40 | read | `ingest/code_generation.py:1033` | QUALITY | The failure path catches only `ValueError`/`AuthorizationChanged` from `fail_generation_build`; any other exception replaces the original. |
| R21-m41 | read | `ingest/code_generation.py:790-806` | ruling 2 | Rebaseline guards only the write loop; an unrelated epoch change during capture, extraction or embedding aborts. |
| R21-m42 | read | `tests/unit/test_code_capture_acceptance.py:518-524`; `status.py:192-196` | CD9 | `edges_by_kind` is checked against the same computation `status` performs. Use an independent oracle. |
| R21-m43 | read | `tests/unit/test_code_capture_acceptance.py:581-586`, `:336-338` | CD9 | "The shared record survives reopen unchanged" compares two reads taken after the reopen, and durable state carries only `raw_uri`. Snapshot full revision dumps before the reopen. |
| R21-m44 | helper | `GATES.md:59`; test name and docstring | CD9 | "The largest size that completes on the 128 GiB dev machine" is stale after lbconn; the test says "multi-hundred" while passing at 50 files. |
| R21-m45 | helper | `tests/unit/test_code_capture_acceptance.py:79-81` | CD9 | The 4 GiB production pool is never asserted and is env-overridable. |
| R21-m46 | read | `tests/unit/test_code_capture_acceptance.py:700` | CD9 | `resumed_from_batches >= 1` where the crash point fixes the count; similar `>=` at `:392`, `:404` (helper). |
| R21-m47 | helper | `tests/unit/test_code_capture_acceptance.py:140-152` | CD9 | The CD1 recorder does not wrap `_edges_touching` and counts build-thread reads only; reword CD9 or wrap it. |
| R21-m48 | read | `GATES.md:58` | CD9 | CHECK omits `test_code_projection.py`, `test_status_code_edges.py`, `test_ladybug_connection_recycle.py` and `test_ladybug_buffer_pool.py`, which assert CD9's `REFERS_TO`/unbound-module clause and the two fixes CD9 depends on. |
| R21-m49 | helper | `tests/unit/test_store_ladybug.py:48` | lbpool | Opens `lb.Database` with no pool (notes name only `test_store_migrations.py`). |

Recorded, still open and not counted above: the `LeaseHeartbeat` rebaseline race (fails closed),
the neo4j driver's DEBUG parameter logging (Task 16), the legacy credentialed `meta.url` (Task 16),
LadybugDB's missing secondary-index DDL, ruling 5's prose-extraction deferral, the unrepaired shared
overload native row, and the CD9 multi-hundred-file clause, which the ledger honestly marks as not
evidenced (no ledger-size run exists after lbconn).

## Design-review closure (B1-B6, M1-M11, m1-m7)

| Item | Disposition | Closing commit or evidence |
| --- | --- | --- |
| B1 legacy loader fall-through | CLOSED | CC1 `74ebaa5` (merge `7a0c719`) split loader selection from the serving lane; cc1fix `fe457f0` (merge `d56b618`) serves only untagged rows (`context.py:54-88`); CD2 CRITERIA; `evidence-cc1.md`, `evidence-cc1fix.md` |
| B2 deferred flag disarms cleanup guards | CLOSED by shape (b), ruling 9 | Flag flips at staging start; store refusals CC1; pipeline spies CC10 `e954eb7` (merge `9a474e4`); CD2 amended `492cb4c` |
| B3 `_source_control` refuses repositories | CLOSED | CC8 (merge `d1910c8`): `build_authority.py:79`, `:88`; `evidence-cc8.md` |
| B4 capture instant in observation identity | CLOSED for resume before the seal | CC9b `5f45611` (merge `bc7ea22`): `_instant` (`code_generation.py:602-614`); `evidence-cc8.md:390`. After the seal the adopted instant meets R21-B2 |
| B5 reclaim drops claim's guarantees | CLOSED | CC3 (merge `8f32ec4`): `_admit_build` (`generations.py:248-380`); CD7 amended `2753cab` |
| B6 publication bumps the epoch | DISSOLVED by ruling 9 | `evidence-cc9b.md:213`; `code_generation.py:704`, `:716` |
| M1 manifest equality is a tautology | CLOSED | `c5b2e42`; `generations.py:356-362` |
| M2 stale derivation rows on resume | CLOSED for evidence, members, bindings and native rows; OPEN for relations (R21-B3) | Ruling 10; absence probe `staged_code.py:562-570`; rule versions under `code_derivation` and `code_history_derivation` |
| M3 decorators scope by ids | CLOSED | CC2 (merge `c461c9c`); `evidence-cc2.md:42` |
| M4 no `generation_id` index | CLOSED with a recorded backend limit | Schema v6, v7 (`5194214`); index-backed half proven on Neo4j parity run 2 |
| M5 quadratic checksum loops | CLOSED | CC2 `6bcbd02`; `evidence-cc2.md:167` (the build-time per-batch reads are R21-M1, a different loop) |
| M6 rebaseline shape and freezes | CLOSED in code; test gap R21-M4 | `build_authority.py:348-402` |
| M7 "applies to this source" | CLOSED (subsumed) | Suppression epoch frozen, `build_authority.py:382`; `evidence-cc8.md:292` |
| M8 `repo_name` truncation | CLOSED | CC4 `8a92f50` (merge `91131e7`); `evidence-cc4.md:75` |
| M9 unowned files | CLOSED with an accepted deviation | `prose_generation.py` to CC9a (merge `67e11cc`); `base.py`/`migrations.py` to CC2; `build_authority.py` stayed with CC8 (notes, item 6) |
| M10 guard re-pointing across tasks | DISSOLVED by shape (b) | Ruling 9 |
| M11 over-budget tasks | PARTLY ADOPTED | CC9 split (`67e11cc`, `bc7ea22`); CC2a/CC2b not adopted, CC2 shipped whole |
| m1 CD5 CHECK file name | CLOSED | `GATES.md:38` |
| m2 CD10 EXPECT | CLOSED | `GATES.md:65`; rerun printed `10 files already formatted` |
| m3 CHECK lines runnable | NO CHANGE NEEDED | Every CHECK line ran under bare `-W error` |
| m4 first-parent walk | CLOSED | `e6cfc3f`; `history_walk: "first_parent"`; `evidence-cc7.md:257` |
| m5 `evidence_class` unset | CLOSED | `evidence-cc7.md:91`; `code_history.py:86`, `:960` |
| m6 clone URL and stderr in logs | CLOSED for `repos.py` logging | `a07e325`: `repos.py:122-159`; the adjacent message echo is R21-M10 |
| m7 walker drift | CLOSED (documented) | Plan amendment "§5, walker drift" |

## Invariants the brief names

| Invariant | Result |
| --- | --- |
| No staged row reachable from a query, status or export surface before publication (CD2, ruling 9) | HOLDS for every query and status surface (no export route exists), with two exceptions: the legacy indexer's synonym search reads staged and published code rows (R21-B4), and internal counts include staged rows (R21-m11). |
| Every managed native ID is namespaced and `_validate_managed_native` re-derives it | HOLDS: `store/generations.py:1508-1547` re-derives Passage, Symbol, DataObject and Commit IDs; every native writer goes through `native_write`. |
| `BuildAuthority.rebaseline` adopts only the authorization epoch and refuses on suppression, capability or `SourceControl` change (ruling 2, M6) | HOLDS in code (`build_authority.py:375-402`, the whole `SourceControl` compared); the capability-loss refusal is not discriminated by any test (R21-M4) and its tests are off the CD8 CHECK (R21-M5). |
| Capture instant on `Generation.created_at`, never in an identity field (B4) | HOLDS (`model.py:368-375` excludes it; `code_generation.py:602-614`, `:969-973`). |
| Reclaim keeps all four claim guarantees (B5) | HOLDS (`generations.py:263-318`), each refusal tested with the fence and holder unchanged. |
| Rule versions in configuration; resume probe asserts absence (ruling 10, M2) | HOLDS except relations, which are keyed without kind and compared without payload (R21-B3). |
| `repos.py` never logs a credentialed URL or raw git stderr (m6) | HOLDS for `repos.py` logging (`repos.py:146`, `:181`); the invalid-URL message echo is R21-M10. |
| Legacy lane byte-identical for non-managed sources (CD1, CD2) | BROKEN by R21-B4 once any code source converts; otherwise the loaders and presentation are unchanged. |

## Per-gate SPEC verdicts

| Gate | Verdict | Blocking findings | Clauses with no test in the CHECK line's suites |
| --- | --- | --- | --- |
| CD1 | NOT MET | R21-B5, R21-M1, R21-M2 | SUBJECT/OBJECT second hop and `Missing shared graph endpoint` (R21-m2) |
| CD2 | NOT MET | R21-B4, R21-M7 | Converting-source page; real-store denial (R21-m8); publication atomicity beyond end state (R21-m9) |
| CD3 | NOT MET | R21-M8, R21-M9 | Every later read from the raw object (R21-m14); archive symlink and non-regular reasons |
| CD4 | MET with minors | none | Rich-input rejection (R21-m17) |
| CD5 | NOT MET | R21-M12 | Several closure refusal branches (R21-m24) |
| CD6 | MET with minors | none | Real shallow boundary (R21-m23); merge-path configuration refusal (R21-m28) |
| CD7 | NOT MET | R21-B1, R21-B3 | Relation payload comparison on resume (R21-B3) |
| CD8 | NOT MET | R21-B1, R21-B2, R21-M4, R21-M5 | Rebaseline refusals and open/preview (R21-M5); publication-window refusal (R21-m31); refresh cancellation (R21-m32) |
| CD9 | NOT MET | R21-B5, R21-M3, R21-M6, R21-M11 | `REFERS_TO`/unbound module off the CHECK line (R21-m48); the LadybugDB line result is below |

## QUALITY verdict

**NOT PASSED.** What holds: layering (`knowledge` imports `ingest` only in the two allowlisted
modules, exact-set asserted by `tests/unit/test_layering.py`; `code_binding.py` and `code_history.py`
import nothing from `hippo.ingest` at any level); no wall clock in `code_binding`, `code_history`,
`staged_code`, `prepared_code_chunks`, `repo_capture` or `code_provenance`; managed-lane failures
reach rows, logs and responses only through the closed mapper and `public_errors.py`; canonical
ordering for identities and checksums; lbconn recycles only under the store lock, outside a
transaction and after the result is closed. What fails: test honesty (R21-M3 vacuous loop, R21-M4
non-discriminating tests, R21-M1's `LINEAR_FACTOR = 3.0`, R21-m42 and R21-m43 tautologies, R21-m33's
`pytest.raises(Exception)`); CHECK lines that omit the suites asserting their own CRITERIA
(R21-M5, R21-m48); the acceptance fixture avoids every shape that breaks the writer (R21-B1, R21-B3);
duplication against the prose precedents (R21-m30, R21-m38).

## Commands run

Fake, root tree at `cbed8ca`, `HIPPO_TEST_STORE=fake`, `-q -o addopts='' -W error`, each CHECK line
verbatim from the ledger, run serially (logs `/tmp/hippo-review21-cd<N>.log`). The orchestrator's
checker was running its own Fake, LadybugDB and Neo4j processes on the same machine.

```text
CD1  EXIT 0  118 passed in 40.12s
CD2  EXIT 0  169 passed, 2 skipped in 11.43s
CD3  EXIT 0  152 passed in 1.71s
CD4  EXIT 0  95 passed in 1.90s
CD5  EXIT 0  89 passed in 0.95s
CD6  EXIT 0  91 passed in 9.68s
CD7  EXIT 0  83 passed in 10.77s
CD8  EXIT 0  306 passed, 3 skipped in 57.51s
CD10 EXIT 0  All checks passed! / 10 files already formatted
```

The counts equal cc11b's recorded final-tree counts. Skip reasons (`-rs`,
`/tmp/hippo-review21-cd2-rs.log`, `/tmp/hippo-review21-cd8-rs.log`):

```text
CD2: test_converting_source_serving.py:366    reopen is a LadybugDB persistence assertion
CD2: test_managed_source_inventory.py:597     reopen is a LadybugDB persistence assertion
CD8: test_managed_pipeline_activation.py:1155 real Ladybug close/reopen contract
CD8: test_managed_pipeline_activation.py:1584 real Ladybug close/reopen contract
CD8: test_prose_generation.py:1028            real Ladybug close/reopen contract
```

Whole-tree Ruff: `.venv/bin/ruff check src tests` (All checks passed), `.venv/bin/ruff format
--check src tests` (295 files already formatted), and the 23 gate documents plus the plan (already
formatted).

Reproductions (Fake). The scratch module is
`/tmp/h21scratch/tests/unit/test_zz_review21_scratch.py`, beside a copy of `tests/` and
`pyproject.toml`, run as
`HIPPO_TEST_STORE=fake .venv/bin/pytest /tmp/h21scratch/tests/unit/test_zz_review21_scratch.py -k <t> -q -o addopts='' -p no:cacheprovider -s -W error --rootdir=/tmp/h21scratch`.
It reuses the `world`, `build` and `make_checkout` helpers of `tests/unit/test_code_generation.py`
and can seed the regression tests the fixes need.

```text
t1 (R21-B2)  /tmp/hippo-review21-scratch-fake.log
  T1 after fault: [('generation-8a14f', 'failed')] manifests: 1
  T1 retry raised: ValueError A sealed profile cannot be rebound
t2 (R21-B4)  /tmp/hippo-review21-scratch-fake.log
  T2 legacy find_synonyms pairs touching managed symbols: 3 of 5
  T2 legacy add_synonyms raised: ValueError Sealed native payload or relationship is immutable
t5 (R21-B1)  /tmp/hippo-review21-scratch-fake-t5.log
  multi         ValueError: Exact NativeBinding inventory differs from prepared coverage; bindings 22 over 21 native rows (DataObject orders: app/main.py and db/schema.sql)
  sql_rw        ValueError: Exact NativeBinding inventory differs ...; bindings 17 over 16 native rows
  cs_overloads  ValueError: Exact NativeBinding inventory differs ...; bindings 18 over 15 native rows
  big_function  ValueError: Exact NativeBinding inventory differs ...; bindings 24 over 13 native rows
  main_guard, class_call: published
t6 (R21-B5 Fake control; the same test fails on LadybugDB, below)  /tmp/hippo-review21-scratch-fake-t67.log
  main_guard {CONTAINS, INVOKES} on one pair: missing [] extra []
  sql_rw_no_schema {READS, WRITES} on one pair: missing [] extra []
t7 (R21-B3)  /tmp/hippo-review21-scratch-fake-t67.log
  main_guard: resumed_from_batches 92; sealed+published generation missing (..., 'INVOKES')
  sql_rw_no_schema: resumed_from_batches 88; sealed+published generation missing (..., 'WRITES')
```

LadybugDB, one line at a time, each under `/usr/bin/time -l`. The CD9 CHECK line verbatim from the
ledger (`HIPPO_TEST_STORE=ladybug HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE=8`, ten suites, `-q -o
addopts='' -W error`), log `/tmp/hippo-review21-cd9-ladybug.log`, run beside the checker's own
LadybugDB CD9 run and a Neo4j run:

```text
CD9  EXIT 0  335 passed, 2 skipped in 3775.45s (1:02:55)
     maximum resident set size 3,144,204,288 B (2.9 GiB); peak memory footprint 1,481,656,696 B (1.4 GiB)
```

The two skips are the only skip sites in those ten suites that apply on LadybugDB,
`test_generation_scoped_reads.py:673` and `:695` (synthetic ceiling and scale fixtures built through
the Fake store's tables); `test_converting_source_serving.py:366` skips only off LadybugDB. That
means CD1's CPU-linearity proof never runs on the acceptance backend, as the CD9 amendment already
states. This proves what the ledger says a tick proves: the 50-file scenario and the nine LadybugDB suites
at HEAD, not the multi-hundred-file clause. The footprint (1.4 GiB, against cc11b's 15.8 GiB at the
same size before lbconn) is consistent with lbconn's recycle. It does not reach R21-B1, R21-B3 or
R21-B5, because the fixture has none of their shapes.

The R21-B5 probe (scratch `-k t6`, `HIPPO_TEST_STORE=ladybug`, log
`/tmp/hippo-review21-lb-p-dedupe.log`):

```text
p-dedupe  EXIT 1  2 failed, 12 deselected in 55.59s (expected failure: the assertion is the defect)
  main_guard       {CONTAINS, INVOKES} on one pair: missing (..., 'INVOKES')
  sql_rw_no_schema {READS, WRITES} on one pair: missing (..., 'WRITES')
```

The LadybugDB lines the evidence files claim, deduplicated against the CD9 line (every file CD9
already ran whole is left out), `HIPPO_TEST_STORE=ladybug`, `-q -o addopts='' -W error -rs`, run
serially after the probe (logs `/tmp/hippo-review21-lb-<name>.log`):

```text
a-store       EXIT 0  255 passed, 2 skipped in 455.12s   max RSS 2.1 GiB
  test_managed_source_inventory test_generation_store test_store_migrations test_policy_migration
  test_generation_counts test_staged_prose_writer test_build_authority test_build_run
  test_knowledge_scoped_reads test_query_scoped_reads   (cc1fix, cc2, cc3, cc8, cc9a, kscope, qscope)
  SKIPPED test_knowledge_scoped_reads.py:385 the timed scale builds run on the Fake store
  SKIPPED test_knowledge_scoped_reads.py:412 the snapshot under test is the Fake store's rollback
b-prose       EXIT 0  9 passed, 58 deselected in 175.30s   max RSS 0.7 GiB
  test_prose_generation -k "reopen or publish"   (cc1, cc2, cc9a)
c-lifecycle   EXIT 0  195 passed in 1154.12s   max RSS 1.0 GiB
  test_managed_source_lifecycle test_managed_pipeline_activation test_store_ladybug
  test_ladybug_buffer_pool test_ladybug_connection_recycle   (lbfix, lbpool, lbconn, cc10)
d-query       EXIT 0  8 passed, 114 deselected in 149.21s   max RSS 0.9 GiB
  test_query_session test_structural_loading test_code_projection test_temporal_conflicts
  -k "publish or select or reopen", with the form (b) AnyIO filter   (qscope)
e-projection  EXIT 0  8 passed in 441.31s   max RSS 1.2 GiB
  test_code_projection   (codeproj)
f-derived     EXIT 0  2 passed, 49 deselected in 141.77s   max RSS 0.9 GiB
  test_derived_projection test_code_generation -k publish   (codeproj, lbconn)
```

Every claimed LadybugDB line is green at HEAD. None of them contains the shapes behind R21-B1,
R21-B3 or R21-B5, which is why they pass beside those defects.

## Appendix: the reproduction module

Verbatim copy of `/tmp/h21scratch/tests/unit/test_zz_review21_scratch.py`, kept here because `/tmp`
may not outlive the session. It seeds regression tests for R21-B1 to R21-B5: `t5` the seal shapes,
`t1` the post-seal retry, `t7` the resume across two kinds, `t2` the legacy synonym pass, and `t6`
the two kinds on one pair (passes on Fake, fails on LadybugDB).

```text
"""Throwaway reproductions for the CD10 review (architect-reviewer-21). Not part of the repo."""

from dataclasses import replace

import numpy as np
import pytest

from hippo.knowledge import staged_code
from tests.unit.test_code_generation import build, head_of, make_checkout, options, world  # noqa: F401

MULTI = {
    "app/main.py": (
        "import sqlite3\n\n\n"
        "def helper():\n    return 1\n\n\n"
        "def main():\n    return helper()\n\n\n"
        "def touch(cursor):\n"
        '    cursor.execute("SELECT id FROM orders")\n'
        '    cursor.execute("UPDATE orders SET total = 1")\n'
        "    return cursor\n\n\n"
        "class Robot:\n"
        "    def move(self):\n        return 1\n\n"
        "    speed = move(None)\n\n\n"
        'if __name__ == "__main__":\n    main()\n'
    ),
    "db/schema.sql": "CREATE TABLE orders (id INT, total INT);\n",
    "src/orders.py": "def total():\n    return 1\n",
    "README.md": "# Multi\n\nA small tree.\n",
}


def multi_tree(w):
    checkout = make_checkout(w.tmp_path, files=MULTI, name="multi")
    return replace(w.tree, root=checkout.resolve(), head_revision=head_of(checkout))


def capture_prepared(monkeypatch, seen):
    original = staged_code.probe_staged_rows

    def spy(store, prepared):
        seen.setdefault("prepared", prepared)
        return original(store, prepared)

    monkeypatch.setattr(staged_code, "probe_staged_rows", spy)


def multi_kind_pairs(prepared):
    by_pair = {}
    for edge in prepared.edges:
        by_pair.setdefault(tuple(edge.endpoints), set()).add(edge.row["kind"])
    return {pair: kinds for pair, kinds in by_pair.items() if len(kinds) > 1}


def stored_code_edges(store, generation_id):
    return {
        (row[1], row[2], row[3]["kind"])
        for row in store._native_relationships(generation_id=generation_id)
        if row[0] == "CODE_EDGE"
    }


def test_zz_t1_a_failure_after_the_seal_resumes_through_the_coordinator(world, monkeypatch):
    w = world
    original = w.module._publish

    def fault(*args, **kwargs):
        raise RuntimeError("injected fault after the seal")

    monkeypatch.setattr(w.module, "_publish", fault)
    with pytest.raises(RuntimeError):
        build(w, operation="first")
    monkeypatch.setattr(w.module, "_publish", original)
    rows = w.store._knowledge_rows("Generation")
    manifests = sum(len(w.store._knowledge_rows("IndexManifest", generation_id=g.id)) for g in rows)
    print("T1 after fault:", [(g.id[:16], g.status) for g in rows], "manifests:", manifests)
    try:
        receipt = build(w, operation="second")
    except BaseException as error:  # noqa: BLE001 - print the outcome, then fail
        print("T1 retry raised:", type(error).__name__, str(error))
        raise
    print("T1 retry:", receipt.status, receipt.generation_id[:16])


def test_zz_t2_legacy_synonym_search_reaches_a_managed_symbol(world):
    w = world
    receipt = build(w, operation="first")
    symbols = [r for r in w.store._native_rows("Symbol", generation_id=receipt.generation_id) if r.get("embedding")]
    ids = {row["id"] for row in symbols}
    print("T2 published generation", receipt.generation_id[:16], "managed symbols with a name vector:", len(symbols))
    from hippo.hipporag.indexer import find_synonyms

    vector = np.asarray([symbols[0]["embedding"]], dtype=np.float32)
    pairs = find_synonyms(w.store, ["entity-probe"], vector, {"entity-probe": "order service"}, threshold=0.8)
    touching = [pair for pair in pairs if pair[0] in ids or pair[1] in ids]
    print("T2 legacy find_synonyms pairs touching managed symbols:", len(touching), "of", len(pairs))
    w.store.add_entities([{"id": "entity-probe", "name": "order service", "embedding": list(map(float, vector[0]))}])
    try:
        w.store.add_synonyms(touching[:1])
    except BaseException as error:  # noqa: BLE001
        print("T2 legacy add_synonyms raised:", type(error).__name__, str(error))
        raise
    print("T2 legacy add_synonyms succeeded")


def test_zz_t3_detect_multi_kind_pairs_and_sealed_parity(world, monkeypatch):
    w = world
    seen = {}
    capture_prepared(monkeypatch, seen)
    receipt = build(w, operation="first", tree=multi_tree(w))
    prepared = seen["prepared"]
    multi = multi_kind_pairs(prepared)
    wanted = {(*edge.endpoints, edge.row["kind"]) for edge in prepared.edges}
    stored = stored_code_edges(w.store, receipt.generation_id)
    print("T3 edges:", len(prepared.edges), "relations keys:", len(prepared.relations), "multi-kind pairs:", multi)
    print("T3 prepared-not-stored:", sorted(wanted - stored), "stored-not-prepared:", sorted(stored - wanted))
    assert multi, "the tree produced no pair with two CODE_EDGE kinds"
    assert wanted == stored


def test_zz_t4_resume_between_two_kinds_of_one_pair(world, monkeypatch):
    w = world
    tree = multi_tree(w)
    seen = {}
    capture_prepared(monkeypatch, seen)
    original = staged_code._write_batch
    state = {"crashed": False, "first": set()}

    def write(store, prepared, batch, **authority):
        multi = multi_kind_pairs(prepared)
        for record in batch:
            if type(record) is staged_code._CodeEdge and tuple(record.endpoints) in multi and not state["crashed"]:
                pair = tuple(record.endpoints)
                if pair in state["first"]:
                    state["crashed"] = True
                    raise RuntimeError("injected crash between two kinds of one pair")
                state["first"].add(pair)
        return original(store, prepared, batch, **authority)

    monkeypatch.setattr(staged_code, "_write_batch", write)
    with pytest.raises(RuntimeError):
        build(w, operation="first", tree=tree, options=options(w, batch_size=1))
    assert state["crashed"]
    monkeypatch.setattr(staged_code, "_write_batch", original)
    receipt = build(w, operation="second", tree=tree, options=options(w, batch_size=1))
    prepared = seen["prepared"]
    wanted = {(*edge.endpoints, edge.row["kind"]) for edge in prepared.edges}
    stored = stored_code_edges(w.store, receipt.generation_id)
    print(
        "T4 status:", receipt.status, "resumed_from_batches:", receipt.resumed_from_batches,
        "sealed generation missing:", sorted(wanted - stored),
    )  # fmt: skip
    assert wanted == stored


def _bindings_report(prepared):
    bundle = prepared.bundle
    spans = {span.id: span for span in bundle.spans}
    objects = {item.id: item for item in bundle.objects}
    grouped = {}
    for binding in bundle.bindings:
        grouped.setdefault((binding.native_kind, binding.native_id), []).append(binding)
    report = []
    for key, rows in grouped.items():
        if len(rows) > 1:
            report.append(
                (
                    key[0],
                    key[1][-24:],
                    [
                        (objects[row.object_id].canonical_key[-60:], spans[row.span_id].locator_json[-60:])
                        for row in rows
                    ],
                )
            )
    return len(bundle.bindings), len(grouped), report


@pytest.mark.parametrize("shape", ["multi", "main_guard", "class_call", "sql_rw", "cs_overloads", "big_function"])
def test_zz_t5_which_trees_seal(world, monkeypatch, shape):
    from tests.unit.test_code_binding import OVERLOADS

    w = world
    files = {
        "multi": MULTI,
        "main_guard": {
            "app/main.py": 'def main():\n    return 1\n\n\nif __name__ == "__main__":\n    main()\n',
            "src/orders.py": "def total():\n    return 1\n",
        },
        "class_call": {
            "app/robot.py": "class Robot:\n    def move(self):\n        return 1\n\n    speed = move(None)\n",
            "src/orders.py": "def total():\n    return 1\n",
        },
        "sql_rw": {
            "app/touch.py": (
                "def touch(cursor):\n"
                '    cursor.execute("SELECT id FROM orders")\n'
                '    cursor.execute("UPDATE orders SET total = 1")\n'
                "    return cursor\n"
            ),
            "db/schema.sql": "CREATE TABLE orders (id INT, total INT);\n",
            "src/orders.py": "def total():\n    return 1\n",
        },
        "cs_overloads": {"src/Robot.cs": OVERLOADS, "src/orders.py": "def total():\n    return 1\n"},
        "big_function": {
            "app/big.py": "def big():\n" + "".join(f"    value_{i} = {i} * 2 + 1  # padding text\n" for i in range(400)) + "    return 1\n",
            "src/orders.py": "def total():\n    return 1\n",
        },
    }[shape]
    checkout = make_checkout(w.tmp_path, files=files, name=shape)
    tree = replace(w.tree, root=checkout.resolve(), head_revision=head_of(checkout))
    seen = {}
    capture_prepared(monkeypatch, seen)
    try:
        receipt = build(w, operation=f"op-{shape}", tree=tree)
        outcome = f"published {receipt.status}"
    except BaseException as error:  # noqa: BLE001
        outcome = f"{type(error).__name__}: {error}"
    prepared = seen.get("prepared")
    if prepared is None:
        print(f"T5 {shape}: {outcome} (no prepared index)")
        return
    total, natives, report = _bindings_report(prepared)
    print(f"T5 {shape}: {outcome}; bindings {total} over {natives} native rows; multi-bound: {report}")
    print(f"T5 {shape}: multi-kind CODE_EDGE pairs: {multi_kind_pairs(prepared)}")


SHAPES = {
    "main_guard": {
        "app/main.py": 'def main():\n    return 1\n\n\nif __name__ == "__main__":\n    main()\n',
        "src/orders.py": "def total():\n    return 1\n",
    },
    "sql_rw_no_schema": {
        "app/touch.py": (
            "def touch(cursor):\n"
            '    cursor.execute("SELECT id FROM orders")\n'
            '    cursor.execute("UPDATE orders SET total = 1")\n'
            "    return cursor\n"
        ),
        "src/orders.py": "def total():\n    return 1\n",
    },
}


def shape_tree(w, shape):
    checkout = make_checkout(w.tmp_path, files=SHAPES[shape], name=shape)
    return replace(w.tree, root=checkout.resolve(), head_revision=head_of(checkout))


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_zz_t6_sealed_code_edges_equal_prepared(world, monkeypatch, shape):
    w = world
    seen = {}
    capture_prepared(monkeypatch, seen)
    receipt = build(w, operation="first", tree=shape_tree(w, shape))
    prepared = seen["prepared"]
    wanted = {(*edge.endpoints, edge.row["kind"]) for edge in prepared.edges}
    stored = stored_code_edges(w.store, receipt.generation_id)
    print(f"\nT6 {shape}: multi-kind {multi_kind_pairs(prepared)}; missing {sorted(wanted - stored)}; extra {sorted(stored - wanted)}")
    assert multi_kind_pairs(prepared)
    assert wanted == stored


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_zz_t7_resume_between_two_kinds_of_one_pair(world, monkeypatch, shape):
    w = world
    tree = shape_tree(w, shape)
    seen = {}
    capture_prepared(monkeypatch, seen)
    original = staged_code._write_batch
    state = {"crashed": False, "first": set()}

    def write(store, prepared, batch, **authority):
        multi = multi_kind_pairs(prepared)
        for record in batch:
            if type(record) is staged_code._CodeEdge and tuple(record.endpoints) in multi and not state["crashed"]:
                pair = tuple(record.endpoints)
                if pair in state["first"]:
                    state["crashed"] = True
                    raise RuntimeError("injected crash between two kinds of one pair")
                state["first"].add(pair)
        return original(store, prepared, batch, **authority)

    monkeypatch.setattr(staged_code, "_write_batch", write)
    with pytest.raises(RuntimeError):
        build(w, operation="first", tree=tree, options=options(w, batch_size=1))
    assert state["crashed"]
    monkeypatch.setattr(staged_code, "_write_batch", original)
    try:
        receipt = build(w, operation="second", tree=tree, options=options(w, batch_size=1))
    except BaseException as error:  # noqa: BLE001
        print(f"\nT7 {shape}: retry raised {type(error).__name__}: {error}")
        raise
    prepared = seen["prepared"]
    wanted = {(*edge.endpoints, edge.row["kind"]) for edge in prepared.edges}
    stored = stored_code_edges(w.store, receipt.generation_id)
    print(f"\nT7 {shape}: resumed_from_batches {receipt.resumed_from_batches}; sealed+published generation missing {sorted(wanted - stored)}")
    assert wanted == stored
```
