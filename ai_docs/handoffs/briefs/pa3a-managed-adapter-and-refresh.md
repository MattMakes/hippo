# Brief: production activation Task 3a — managed adapter, eligibility, add/bootstrap/refresh dispatch

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `pa3a` (branch `wp/pa3a`, base = the `rag-it-all-tibs` HEAD the orchestrator names in the spawn message; it includes the committed coordinator and the store transaction-ownership change).

GOAL: An authenticated actor adding pasted text or an eligible plain-prose file, or reindexing such a source, goes through the reviewed coordinator via a new `managed_activation.py` adapter; everything else keeps legacy behavior byte-for-byte; failures are private and generation-aware. Delete, `reindex_all` and mixed bulk dispatch are NOT in this brief (Task 3b follows on the same files).

CONTEXT:
- Plan: `ai_docs/plans/rag-it-all-task-5-production-activation.md`. Binding sections: "Managed eligibility and dispatch" (the signature block and the table), "Managed build resources and coordinator adapter" (steps 1–7), "Failure and progress presentation", "Reindex and mixed bulk behavior" ONLY the single-source `reindex` bullets, invariants 1, 3, 5, 8, the Task 3 row of the ownership table, and the adversarial cases about authenticated pasted text / `.md` upload / `.pdf` / `.py` / zip / repo / sample and about refresh failing at every coordinator boundary. Gates PA1 (pipeline half), PA3, PA5 (single-source half), PA7 (pipeline half) in `ai_docs/gates/rag-it-all/task-5-production-activation/GATES.md`.
- Existing pipeline: `src/hippo/ingest/pipeline.py` (`add_text`, `add_upload`, `start_indexing` ~:203, `run_indexing` ~:212, `_read_chunk_index` ~:248, `reindex` ~:443, `_prepare_reindex`, `delete_source` ~:408, `reindex_all` ~:429). `src/hippo/ingest/readers.py` has `PROSE_EXTENSIONS`. `src/hippo/jobs.py` has `Jobs.is_cancelled(job_key)`; the index job key is `index:<source_id>`. Read `tests/unit/test_ingest_pipeline.py` and `tests/unit/test_ingest_concurrency.py` for fixture patterns (how sources, jobs and the Ollama MockTransport are set up).
- Coordinator (committed): `src/hippo/ingest/prose_generation.py`. Verbatim contract from the independent review (`ai_docs/reports/2026-09-11-prose-coordinator-review.md` section 4):
  ```python
  build_plain_source(ctx, *, source_id, actor, inputs, options, raw_store, embedding_spec,
                     operation_id, should_stop, on_progress=None,
                     embedding_cache: EmbeddingCache | None = None) -> BuildReceipt
  # actor: exactly BuildActor; options: exactly PlainBuildOptions; embedding_spec: exactly EmbeddingSpec;
  # inputs: exactly tuple; operation_id: non-empty str <= 256 chars; raises ValueError (BuildBusy subclass),
  # AuthorizationChanged, BuildCancelled, plus OllamaError / TooLarge / UnsupportedProvenanceFormat.
  PlainBuildOptions(chunk_size_chars=1500, chunk_overlap_chars=200, synonymy_threshold=0.8, allow_empty=False,
                    capture_limits=CaptureLimits(...), max_decoded_chars=2_000_000, max_chunks=1000,
                    max_bootstrap_rows=50_000, max_bootstrap_bytes=64 MiB, batch_size=128, workers=2,
                    lease_duration_seconds=300.0, renewal_interval_seconds=30.0)   # frozen, strict types
  BuildProgress(phase: str, completed: int = 0, total: int = 0)   # phases "capture", "reading", "extract"
  BuildReceipt(source_id, generation_id, event_id, accepted_input_hash, outcome)  # "published" | "already_current" | "already_published"
  ```
  `ByteInput`, `FileInput(logical_path, path: Path (absolute, no ..), media_type="text/plain", provider_revision=None)`, `ExcludedInput`, `CaptureLimits(max_input_bytes, max_total_bytes, max_inputs, max_manifest_bytes)` are imported from `hippo.ingest.accepted_inputs`, NOT from `prose_generation`.
  `BuildActor(kind: "reader"|"trusted_local", user_id, max_rank)` with `BuildActor.reader(principal)` / `BuildActor.trusted_local()` from `hippo.knowledge.build_authority`.
- Task 1 (committed, `5564d73`): `hippo.knowledge.source_lifecycle.tombstone_managed_source(ctx, *, source_id, actor, operation_id) -> TombstoneReceipt`; `store.source_is_managed(source_id)`; a tombstoned Source has `status="deleted", stage="tombstoned"` plus a current-only suppression with `scope_key="source:<id>:delete"`. In THIS brief you only need to recognize a tombstoned source and refuse/skip it; you do not call the tombstone.
- Other reviewed primitives: `hippo.knowledge.raw_artifacts.RawArtifactStore(root, max_object_bytes=...)`, `hippo.knowledge.embedding_cache.EmbeddingCache`, `hippo.knowledge.embedding_profile.EmbeddingSpec` and the dense-session base-model prefix mapping in `hippo.knowledge.dense_session` (factor one pure helper so ingestion and empty-corpus resolution cannot drift; if that helper must live in `dense_session.py`, stop and ask, because that file is not yours).
- The concurrency fix `store.in_ambient_transaction()` is in HEAD; the coordinator must be called with no ambient transaction on the calling thread.

FROZEN CONTRACT:
```python
# src/hippo/ingest/pipeline.py (keyword-only additions; omitted actor == legacy for unmanaged sources)
add_text(..., build_actor: BuildActor | None = None) -> str
add_upload(..., build_actor: BuildActor | None = None) -> str
start_indexing(ctx, source_id, *, build_actor=None, operation_id=None) -> bool
run_indexing(ctx, source_id, *, build_actor=None, operation_id=None) -> None
reindex(ctx, source_id, *, build_actor=None) -> bool

# src/hippo/ingest/managed_activation.py
def managed_eligibility(source: Source) -> Literal["managed", "eligible_legacy", "unsupported", "tombstoned"]
def new_operation_id() -> str                      # bounded, unique, matches ^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$
def run_managed_build(ctx, *, source_id: str, actor: BuildActor, operation_id: str, job_key: str) -> BuildReceipt
def map_build_failure(exc: BaseException, *, has_active_generation: bool) -> ManagedFailure   # closed mapping
@dataclass(frozen=True) class ManagedFailure: status: str; stage: str; code: str; message: str   # generic bounded text only
```
Eligibility rules are exactly the plan table: saved Source kind `text`, or kind `file` whose sanitized stored filename ends in one of `readers.PROSE_EXTENSIONS` (`.txt .md .markdown .rst .text`), checked on the saved Source, never on an HTTP content-type; a managed Source (`store.source_is_managed`) is `"managed"` regardless of kind; a tombstoned Source is `"tombstoned"`; everything else (archive, repo, sample, rich, code/config, extensionless, binary) is `"unsupported"`.

Dispatch matrix (must be tested cell by cell): new `text`/eligible `file` + actor → managed bootstrap; same without actor → legacy; existing eligible legacy + actor `reindex` → atomic managed bootstrap with legacy evidence serving until publish; existing managed + actor → managed refresh only; existing managed WITHOUT actor (or open/preview actor) → refuse before any mutation, never legacy; unsupported → legacy with or without actor; tombstoned → refuse/skip, no mutation, no resurrection.

Adapter obligations (plan steps 1–7): exactly one saved ingress file under the source directory; refuse missing / symlinked / non-regular / changed-during-capture / oversized / filename-escaping; `FileInput` with absolute path, sanitized logical name (`text.md` for pasted text), `text/plain`; lazy `RawArtifactStore` at `Path(config.data_dir).resolve()/"knowledge"/"raw-v1"` with `max_object_bytes=config.max_upload_bytes` and `EmbeddingCache` at the sibling `cache/embeddings-v1`, created ONLY by a managed build (add a test that query/status/legacy ingest never create them); `PlainBuildOptions` from effective config (chunk size/overlap, synonym threshold, `openie_workers`, one input, `max_upload_bytes`, `max_text_chars`), rejecting out-of-contract values without truncation; `EmbeddingSpec` via the shared helper; progress mapped ONLY to Source `status/stage/progress_done/progress_total`, never into `meta_json`; `build_plain_source` called outside every ambient transaction with `should_stop=lambda: ctx.jobs.is_cancelled(job_key)`; no model/file callback under a store lock; the immutable actor and operation ID captured in the job closure, never a token/Request/cookie/ambient principal.

Failure presentation exactly as the plan: bootstrap success → coordinator owns `ready/ready`; refresh in progress → `status="ready"`, `stage="refreshing: capture|extract|write|publish"`; refresh failure/cancel with active generation → `status="ready"`, `stage="refresh_failed"|"refresh_cancelled"`, generic code/message, active pointer and counts untouched; initial failure/cancel with no active generation → `status="failed"`, safe stage, generic error, coordinator's unpublished attempt retained; tombstone observed → never overwrite `deleted/tombstoned`. Logs and Source rows never contain source text, raw bytes, absolute paths, tokens, prompts, provider bodies, model output or `str(exc)` of unknown exceptions; tests inject exception strings containing a fake secret, an absolute path, source text and a model body and assert none reaches Source rows or captured logs.

FILES:
  - own: NEW `src/hippo/ingest/managed_activation.py`, `src/hippo/ingest/pipeline.py`, `src/hippo/ingest/readers.py`, `src/hippo/config.py`, `tests/unit/test_ingest_pipeline.py`, `tests/unit/test_ingest_concurrency.py`, NEW `tests/unit/test_managed_pipeline_activation.py`, NEW `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa3a.md`.
  - do NOT touch: `src/hippo/ingest/prose_generation.py`, `src/hippo/store/*`, `src/hippo/knowledge/*`, `src/hippo/web/*`, `src/hippo/mcp_server.py`, `src/hippo/cli.py`, `src/hippo/remote.py`, `src/hippo/status.py`, `src/hippo/context.py`, `tests/unit/test_prose_generation.py`, the shared `GATES.md`, `docs/`, the checkpoint. `delete_source` and `reindex_all` bodies stay untouched in this brief except that they must not break; Task 3b changes them.
- The adapter must never call `_clear_passages`, `delete_passages_for_source`, `delete_code_for_source`, `remove_orphans`, `store.delete_source`, `shutil.rmtree`, generation collection, raw deletion or any source-wide cleanup for a managed attempt; the tests monkeypatch each to raise and prove managed add/refresh/reindex still succeed.

STEPS:
1. Worktree + venv per the rulebook (with the `mcp==2.1.1` pin). Baseline green: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_ingest_pipeline.py tests/unit/test_ingest_concurrency.py tests/unit/test_prose_generation.py -q -o addopts='' -W error`.
2. RED `tests/unit/test_managed_pipeline_activation.py`: the full dispatch matrix; eligibility on saved Source fields not content-type; ingress-file refusals; raw root / cache directory creation only on managed builds; option capture and rejection; progress mapping; every failure transition; the redaction test; managed source with no actor raises before any legacy hook; refresh while G1 is queried (hold a structural `query_session` on G1 through a refresh, assert G1 still served until publish, then G2); failure injected at each coordinator boundary leaves G1; cancellation during a blocked model call (event-controlled MockTransport as in `test_prose_generation.py`) leaves G1; the destructive-operation spies. Reuse the coordinator test fixtures where possible rather than inventing a second harness. Save `/tmp/hippo-pa3a-red.log`.
3. Implement `managed_activation.py`, then the `pipeline.py` dispatch for `add_text`, `add_upload`, `start_indexing`, `run_indexing`, `reindex`.
4. GREEN Fake: PA3's CHECK line (`test_managed_pipeline_activation.py test_prose_generation.py test_generation_failure.py`) plus `test_ingest_pipeline.py test_ingest_concurrency.py test_managed_source_lifecycle.py test_build_authority.py test_local_workspace_membership.py`. Log `/tmp/hippo-pa3a-fake-green.log`.
5. GREEN Ladybug: `test_managed_pipeline_activation.py test_ingest_pipeline.py test_ingest_concurrency.py`. Log `/tmp/hippo-pa3a-ladybug-green.log` (expect many minutes; run once at the end).
6. Ruff check + format on changed files.
7. Write `evidence-pa3a.md` (commands, results, logs, RED log, the dispatch matrix as a table with the test name per cell, the destructive-operation spy list, deviations with reasons) and commit on `wp/pa3a` in two or three commits.

DONE WHEN: steps 4–6 green with `-W error`; evidence written; commits on `wp/pa3a`; `horch done` lists commits, files, the exact `managed_activation.py` public signatures as implemented, test counts per backend with log paths, and any existing test modified. If you approach roughly 400k tokens before Ladybug is green, stop at a clean commit, write the evidence file with what is proven, and `horch done` with a partial summary naming the remaining steps.

OUT OF SCOPE: `delete_source`, `reindex_all`, mixed bulk (Task 3b); route/MCP/CLI actor propagation and public error mapping (Task 4); projection/inventory (Task 2, merging separately); Neo4j runs.

REPORT: `horch note` per step. `horch tell orchestrator "[<role>] BLOCKED: ..."` for any contract or ownership question; wait for the answer.
