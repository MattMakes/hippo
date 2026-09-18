# R2 — Ingest pipeline, indexer, OpenIE cost, evals, test conventions

Worker: sonnet-2. Scope: `src/hippo/ingest/*.py`, `src/hippo/hipporag/indexer.py`, `hipporag/openie.py`,
`src/hippo/jobs.py`, `src/hippo/evals/*.py`, `src/hippo/cli.py`, `src/hippo/remote.py`, `tests/conftest.py`,
`tests/fakes/fake_ollama.py`, ingest/indexer/evals/cli tests, `justfile`, `pyproject.toml`, `docs/CONTRACTS.md`.

## Verdict table

| id | claim (short) | verdict | key file:line |
|---|---|---|---|
| R2-1 | `readers.lang_of(path)` exists and routes docs to a code path | Contradicted | src/hippo/ingest/readers.py (no such function anywhere in repo) |
| R2-2 | Repos ingest today: shallow clone → `_chunk_code` line windows → OpenIE on every chunk | Built | src/hippo/ingest/pipeline.py:250-274 |
| R2-3 | A 1500-char code chunk costs two LLM calls in `openie.extract` | Built | src/hippo/hipporag/openie.py:52-71 |
| R2-4 | Extraction is concurrent (`deque`/`in_flight`) | Built | src/hippo/hipporag/openie.py:91-110 |
| R2-5 | `FakeOllama` counts calls (so tests can assert "no NER call on code") | Partial | tests/fakes/fake_ollama.py:169,207 |
| R2-6 | Some passage can be marked to skip OpenIE today | Missing | src/hippo/hipporag/indexer.py:51-57 |
| R2-7 | `repos.clone_repo` has a configurable depth (needed for git-history WPs) | Missing | src/hippo/ingest/repos.py:58-69 |
| R2-8 | `walk_repo`/readers filters and size limits as described | Built | src/hippo/ingest/readers.py:36-75 |
| R2-9 | Reindex has per-file bookkeeping (path/hash/commit) to build incrementality on | Missing | src/hippo/ingest/pipeline.py:328-397 |
| R2-10 | Indexing runs in a thread with cooperative cancellation, not asyncio | Built | src/hippo/jobs.py:19-47 |
| R2-11 | Golden-set no-LLM replay (B §7 `replay_set`) has no plumbing yet | Contradicted (plumbing exists) | src/hippo/analysis/simulate.py:125-134 |
| R2-12 | Eval question rows have `origin`, `gold_passage_ids`, `kind`, `notes` | Partial | src/hippo/store/evals.py:14-52 |
| R2-13 | `runner.run_question` stores the full `Trace` per result | Built | src/hippo/evals/runner.py:99-101 |
| R2-14 | Evals metric names: `recall@k`, `gold_rank`, EM, F1 | Built | src/hippo/evals/metrics.py:34,63,83,106 |
| R2-15 | Judge always runs, even for code questions | Built | src/hippo/evals/judge.py:37-47; runner.py:113-116 |
| R2-16 | Default test store is the fake store | Contradicted | tests/conftest.py:32-37 |
| R2-17 | `tests/fixtures/` exists today | Missing | tests/ (directory listing) |
| R2-18 | Throwaway Neo4j test container is on 7688 / `testpassword` | Contradicted | justfile:132-140 |
| R2-19 | `tree-sitter`/`sqlglot` already present somewhere in the project | Missing | pyproject.toml:1-22 |
| R2-20 | `cli.py` is argparse-based; `RemoteHippo` has no path/blast/history methods | Built (argparse) / Missing (remote methods) | src/hippo/cli.py:52-93; src/hippo/remote.py:32-136 |
| R2-21 | Answer prompt needs no change to prepend a synthetic "Code graph" passage | Built | src/hippo/prompts.py:353-361; src/hippo/ask.py:40-53 |

---

### R2-1: `readers.lang_of(path)` exists and routes documents to a code path (B §5)
**Source:** B §5 ("`pipeline.start_indexing` routes a document to it when `readers.lang_of(path)` is a supported language")
**Evidence:** `grep -rn "lang_of" src/ tests/` returns nothing. Language/kind detection today is done entirely by extension-set membership in `src/hippo/ingest/readers.py:58-71` (`PROSE_EXTENSIONS`, `RICH_EXTENSIONS`, `CODE_EXTENSIONS`) and a single boolean `Document.is_code` (readers.py:79-85), not a per-language classifier.
**Verdict:** Contradicted
**Implication for the plan:** Any "is this a supported code language" branch (Python/TS/JS vs. everything else) must be written from scratch — most naturally as a new function next to `is_code_name`/`is_supported_name` in `readers.py`, or as a small lookup in the new code package, keyed on the same suffix sets hippo already has (`.py .pyi` / `.ts .tsx` / `.js .jsx .mjs .cjs`).

### R2-2: Repos ingest today: shallow clone → `_chunk_code` line windows → OpenIE on every chunk (B §1, "Built, but code is treated as prose")
**Source:** B §1 checklist row "Git repos as a source"
**Evidence:**
```python
# src/hippo/ingest/pipeline.py:316-321
if kind == "repo":
    ctx.store.update_source(source["id"], stage="cloning")
    checkout = folder / REPO_DIR
    shutil.rmtree(checkout, ignore_errors=True)
    repos.clone_repo(meta["url"], checkout)
    return repos.walk_repo(checkout, budget)
```
Then `_read_chunk_index` (pipeline.py:247-274) calls `chunk_documents(docs, config.chunk_size_chars, config.chunk_overlap_chars)` unconditionally for every document, and `index_source` (indexer.py:64-199) runs every non-blank chunk through `openie.extract_many` with no branch on `Document.is_code`.
**Verdict:** Built
**Implication for the plan:** The single insertion point for a code path is between `read_source` and `chunk_documents` in `_read_chunk_index` (pipeline.py:251-253) — exactly where A's `extract_code(docs, source_id)` call and B's `extract_repo` call are meant to sit. No other call site duplicates this chunk→index flow.

### R2-3: A 1500-char code chunk costs two LLM calls in `openie.extract` (B §1)
**Source:** B §1 ("a 1500-character code chunk costs two LLM calls in `openie.extract`")
**Evidence:**
```python
# src/hippo/hipporag/openie.py:55-63
ner = ollama.chat_json(prompts.ner_messages(text), prompts.NER_SCHEMA, max_tokens=NER_MAX_TOKENS)
result.entities = _unique_strings(ner.get("named_entities", []))
triples = ollama.chat_json(
    prompts.triples_messages(text, result.entities),
    prompts.TRIPLES_SCHEMA,
    max_tokens=TRIPLES_MAX_TOKENS,
)
```
`extract()` takes exactly `(passage_id, text)` — there is no length check, no code/prose branch, no way to shortcut either call. Every chunk, code or prose, costs exactly 2 `chat_json` calls.
**Verdict:** Built
**Implication for the plan:** Confirmed as literally true today, with no existing knob to reduce it — any "prose-only OpenIE" gate (A's `MIN_OPENIE_DOC_CHARS`, B's `extract_text`/passage `kind`) is new code, not a config flip.

### R2-4: Extraction is concurrent via `deque`/`in_flight` (task asked to confirm openie.py:91-103)
**Source:** shared-context / task text
**Evidence:**
```python
# src/hippo/hipporag/openie.py:91-104,109-110
todo = deque(passages)
in_flight: set[Future[Extraction]] = set()
...
while todo and len(in_flight) < workers * 2:
    pid, text = todo.popleft()
    in_flight.add(pool.submit(extract_unless_stopped, pid, text))
...
while in_flight:
    finished, in_flight = wait(in_flight, return_when=FIRST_COMPLETED)
```
`workers` defaults to `config.openie_workers = 2` (config.py:58), so up to 4 in-flight futures at once (`workers * 2`), via a `ThreadPoolExecutor(max_workers=workers)`.
**Verdict:** Built
**Implication for the plan:** A code extractor that emits zero LLM calls doesn't need to touch this machinery at all; it only matters for whatever residual OpenIE still runs (docstrings/README/commit messages per A, `doc` passages per B).

### R2-5: `FakeOllama` counts calls (B §12, "FakeOllama counts calls")
**Source:** B §12
**Evidence:** `tests/fakes/fake_ollama.py:169` (`self.calls: list[dict[str, Any]] = []`) is appended to once per `/api/chat` request (fake_ollama.py:207, inside `handle`). Each entry is the full request body (`{"model", "messages", ...}`), not a per-method counter — there is no `self.calls["ner"]` style breakdown.
**Verdict:** Partial
**Implication for the plan:** Tests that must assert "no NER call touches a function body" (A §Verification step 6, B §12) will filter `fake_ollama.calls` by inspecting each call's `messages[0]["content"]` system-prompt prefix (`"Your task is to extract named entities"` for NER, `"Your task is to construct an RDF"` for triples — see `fake_ollama.py:223-227`) and then check the user content, exactly as `FakeOllama.chat()` itself dispatches (fake_ollama.py:220-238). This is a few lines of test helper, not something already provided.

### R2-6: Some passage can be marked to skip OpenIE today (task R2.2)
**Source:** task R2.2 ("Is there any place a passage could be marked to SKIP OpenIE today?")
**Evidence:**
```python
# src/hippo/hipporag/indexer.py:51-57
@dataclass
class Chunk:
    """What the indexer needs to know about one passage of a source."""
    ordinal: int
    title: str
    text: str
```
`Chunk` has exactly three fields. `index_source` (indexer.py:85, 112-118) filters only blank chunks (`c.text.strip()`) before handing everything else to `openie.extract_many`. There is no `extract_text`, no `skip`, no per-chunk flag anywhere in `ingest/` or `hipporag/indexer.py`.
**Verdict:** Missing
**Implication for the plan:** A's `Chunk.defines`/`Chunk.extract_text` and B's `Passage.kind` are both new fields that don't exist yet; whichever shape wins, `index_source`'s OpenIE step (indexer.py:109-120) is the one place that needs the new branch (`extract_text is None` vs. a threshold vs. a `kind` check).

### R2-7: `repos.clone_repo` has a configurable depth
**Source:** A §2.2 `git_history.py` ("`repos.clone_repo` uses `--depth {depth + 1}`"), B §5 ("`repos.clone_repo` gains `depth`")
**Evidence:**
```python
# src/hippo/ingest/repos.py:58,69
def clone_repo(url: str, dest: Path, timeout: int = 300) -> Path:
    ...
    command = ["git", "clone", "--depth", "1", "--single-branch", "--", url, str(dest)]
```
`--depth 1` is a hardcoded literal in the command list, not a parameter. `clone_repo`'s signature has no `depth` argument at all.
**Verdict:** Missing
**Implication for the plan:** Both A and B correctly describe this as a change to make, not something already there; the change is a one-line signature addition plus threading a `depth` value from `Config`/env down through `read_source`'s `kind == "repo"` branch (pipeline.py:316-321) into this call.

### R2-8: `walk_repo`/readers filters and size limits (task R2.4)
**Source:** task R2.4
**Evidence:**
```python
# src/hippo/ingest/readers.py:36-54
IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "target",
                ".idea", ".vscode", "vendor"}
MAX_FILE_BYTES = 2_000_000
MAX_TEXT_CHARS = 20_000_000
MAX_ZIP_MEMBERS = 5_000
MAX_ZIP_TOTAL_BYTES = 50_000_000
```
`repos._walk_files` (repos.py:125-138) skips `IGNORED_DIRS`, dotfiles/dirs, symlinks, and anything over `MAX_FILE_BYTES`; `readers.is_supported` (readers.py:145-155) gates by `CODE_EXTENSIONS`/`PROSE_EXTENSIONS`/`RICH_EXTENSIONS`/`KNOWN_TEXT_NAMES` or a UTF-8 sniff for extensionless files. `pipeline.py:60-62` adds a hard `MAX_CHUNKS = 20_000` passages-per-source cap on top, independent of file count. `test_ingest_limits.py` exercises the upload-byte cap (50 MB, `DEFAULT_MAX_UPLOAD_BYTES`), the text-char budget (20 M, shared across every file of one source via `TextBudget`), zip member/byte budgets, and the chunk ceiling — a 50k-line repo would most plausibly hit `MAX_CHUNKS` (20,000 chunks at 1500 chars ≈ 30 M chars of code) or the 20 M char `TextBudget`, whichever comes first.
**Verdict:** Built
**Implication for the plan:** These limits are shared by every source kind (`MAX_CHUNKS` is source-agnostic); a code path that produces one passage per symbol instead of one per 1500-char window will produce *more* documents for the same repo size, so `MAX_CHUNKS` becomes the binding constraint sooner, not later — worth a settings review, not a code change to discover.

### R2-9: Reindex has per-file bookkeeping (path/hash/commit) to build incrementality on (task R2.5)
**Source:** task R2.5; B §5 ("Incremental. `pipeline.reindex(source_id)` gains `changed_only=True`")
**Evidence:**
```python
# src/hippo/ingest/pipeline.py:376-380
def _prepare_reindex(ctx: AppContext, source_id: str) -> None:
    _clear_passages(ctx, source_id)
    ctx.store.update_source(
        source_id, status="queued", stage="queued", progress_done=0, progress_total=0, error=None
    )
```
`reindex`/`reindex_all` (pipeline.py:349-373) always call `_clear_passages` (→ `store.delete_passages_for_source`, pipeline.py:393-397) then re-run `start_indexing` from scratch. Passage rows written by `index_source` carry only `{id, source_id, ordinal, title, text, embedding}` (indexer.py:96-105) — no file path, hash, or commit sha field anywhere in the store schema for passages. `Source.meta` (set in `_read_chunk_index`, pipeline.py:275-276) holds only `{"chunks", "documents", "counts"}`.
**Verdict:** Missing
**Implication for the plan:** Both A ("sources are still re-indexed wholesale... not that the graph is patched") and B ("Incremental" as new work) are right that nothing today supports a changed-files diff; the `Busy` rule (pipeline.py:67-68, 383-390: any *other* running index job blocks delete/reindex) is the only concurrency safety net that any incremental path would also need to respect.

### R2-10: Indexing runs in a thread with cooperative cancellation, not asyncio (task R2.6)
**Source:** task R2.6; commit f65afe2 ("cancellable indexing")
**Evidence:**
```python
# src/hippo/jobs.py:27-47
def start(self, key: str, work: Callable[[], None]) -> bool:
    ...
    thread = threading.Thread(target=runner, name=f"job-{key}", daemon=True)
    self._running[key] = thread
    self._cancelled[key] = threading.Event()
    thread.start()
```
Cancellation is a `threading.Event` per job key, checked cooperatively: `index_source`'s `checkpoint()` closure (indexer.py:81-83) and `extract_many`'s `extract_unless_stopped` (openie.py:94-97) both call `should_stop()` and raise `openie.Stopped`. Progress flows through `on_progress(stage, done, total)` callbacks that write directly to the `Source` row (`ctx.store.update_source(..., stage=..., progress_done=..., progress_total=...)`, pipeline.py:270-273), polled by the UI — there is no separate progress bus.
**Verdict:** Built
**Implication for the plan:** A long git-history pass (A's WP2b `read_history`) has an obvious progress seam: it's a synchronous, single `git log` subprocess call with no natural sub-steps, so progress reporting for it would most likely be a single `on_progress("reading history", 0, 1)` / `(..., 1, 1)` pair around the whole call, matching how `pipeline.py`'s existing stages (`"parsing code"` in A's plan) already report only start/end, not fine-grained percentages.

### R2-11: Golden-set no-LLM replay (B §7 `replay_set`) has no plumbing yet
**Source:** B §7 ("Golden-set replay. `simulate.replay_set(ctx, set_id, overrides) -> {before, after, changed_questions}` runs `runner.run_question` with the LLM filter replayed from each stored result's trace (no LLM)")
**Evidence:**
```python
# src/hippo/analysis/simulate.py:125-134
def replay_filter(baseline: Trace) -> FactFilter:
    """..."""
    def replay(question: str, candidates: list[list[str]]) -> tuple[list[list[str]], str]:
        kept = baseline.filter.get("kept_triples", [])
        return [t for t in kept if t in candidates], "replayed"
    return replay
```
and `Trace.filter` already stores `{"raw_response", "kept_triples", "replayed"}` (retriever.py:118-120, 221-225), `Trace.to_dict()` is `asdict(self)` (retriever.py:127-128) and is what `store.add_result` persists as `trace_json` (evals.py:194-230, `runner.py:99-101`). `Retriever.retrieve(..., fact_filter: FactFilter | None = None, ...)` already accepts a replacement filter function (retriever.py:160-166, 216-217) — this is exactly how per-question simulation replay works today (`analysis/simulate.simulate`, simulate.py:104-115).
**Verdict:** Contradicted (B's checklist row 17 itself already says "no golden-set replay yet" — the finding here is that the single-question replay plumbing this would be built on top of is already complete, which is *more* built than a plain reading of "Missing: git history" might suggest)
**Implication for the plan:** `replay_set` over a whole `QuestionSet` is "loop `run_question` per stored `EvalResult`, rebuild a `Trace` from its `trace_json` (there is no `trace_from_dict` in `simulate.py`'s `__all__` despite it being referenced — see gotcha below), call `replay_filter(that_trace)` as the `fact_filter` kwarg" — a genuinely small addition, not new machinery.

### R2-12: Eval question rows have `origin`, `gold_passage_ids`, `kind`, `notes` (task R2.7)
**Source:** task R2.7 ("existing origins (`'generated'`?)... what a question row contains")
**Evidence:**
```python
# src/hippo/store/evals.py:14
def create_question_set(self, name: str, source_id: str | None = None, origin: str = "manual") -> str:
```
`question_maker._create_set` (question_maker.py:247-255) calls `ctx.store.create_question_set(name, source_id, "generated")` — so `origin` is a **QuestionSet**-level field (`"manual"` default, `"generated"` for auto-made sets), not a per-question field. Each `Question` row (`add_questions`, evals.py:34-65) has `{id, text, expected_answer, gold_passage_ids, kind, notes, ordinal}`; `kind` is `"single"` or `"multihop"` (question_maker.py:127-134, 194-200) — there is no `"code"` or `"commit"` kind today.
**Verdict:** Partial
**Implication for the plan:** A/B's proposed `kind='code'`/`kind='commit'` and `origin='code'` slot cleanly next to the existing `origin`/`kind` fields with no schema change — `add_questions`/`create_question_set` already accept arbitrary strings for both (no enum/CHECK constraint enforced in `evals.py`).

### R2-13: `runner.run_question` stores the full `Trace` per result
**Source:** task R2.7
**Evidence:**
```python
# src/hippo/evals/runner.py:98-105
trace = search(ctx, text, settings, access)
result["trace"] = trace.to_dict()
result["used_dpr_fallback"] = trace.used_dpr_fallback
ranked_ids = trace.passage_ids()
result["recall"] = metrics.recall_at_k(gold_ids, ranked_ids)
result["gold_rank"] = metrics.gold_rank(gold_ids, ranked_ids)
```
`store.add_result` (evals.py:194-231) writes `trace_json=json.dumps(result.get("trace", {}))` on every `EvalResult` node, unconditionally.
**Verdict:** Built
**Implication for the plan:** Nothing needs to change to make traces available for replay — the full `fact_candidates`/`filter`/`seed_entities`/`top_nodes` shape is already on disk per historical result (see `docs/CONTRACTS.md:59-63` for the exact `Trace` field list, which matches `retriever.py:111-125` verbatim).

### R2-14: Evals metric names: `recall@k`, `gold_rank`, EM, F1
**Source:** task R2.7
**Evidence:** `metrics.py:34` (`DEFAULT_KS = (1, 2, 5, 10, 20)`), `:63` (`exact_match`), `:83` (`f1`), `:89-103` (`recall_at_k` → keys `"recall@1"`..`"recall@20"`), `:106-114` (`gold_rank`). `runner.summarize` (runner.py:158-187) additionally reports `accuracy` (mean judge score), `correct`/`partial`/`incorrect` counts, `mean_gold_rank`, `gold_in_top5` (rank ≤ `GOLD_TOP = 5`), `dpr_fallbacks`, `mean_latency_ms`.
**Verdict:** Built
**Implication for the plan:** A's proposed `recall["code_seeded"]`/`recall["path_fidelity"]` keys slot directly into the existing `recall: dict` on a result (runner.py:104, 146) and `summarize`'s `for k in metrics.DEFAULT_KS` loop pattern (runner.py:184-186) is the template for adding new derived means.

### R2-15: Judge always runs, even for code questions (B §12 gotcha: "Do not assert the fake judge's verdict for code questions")
**Source:** A §4.5 ("Do not assert the fake judge's verdict for code questions (it may echo a triple line)")
**Evidence:**
```python
# src/hippo/evals/runner.py:113-116
if expected:
    result.update(_grade(ctx, text, expected, answer.answer))
else:
    result["judge_reason"] = "no expected answer to compare with"
```
`_grade` unconditionally calls `judge.judge(ctx.ollama, question, expected, actual)` whenever `expected_answer` is non-empty — there is no `kind`-based skip. `FakeOllama.judge` (fake_ollama.py:284-292) does simple substring/content-word overlap between `expected` and `actual`, with no awareness of code syntax.
**Verdict:** Built
**Implication for the plan:** A's warning is well-founded: a `code`/`commit` question's `expected_answer` (e.g. `"Calls: billing.total . Reads: orders ."`) will go through the same fake judge as prose, and `content_words()` (fake_ollama.py:142-143) strips only `[a-z0-9]+` tokens, so punctuation-heavy expected answers may spuriously "partially_correct" on token overlap — a real risk for flaky new tests, not a hypothetical one.

### R2-16: Default test store is the fake store
**Source:** task R2.8 ("how are the three stores parametrised? env var? marker?")
**Evidence:**
```python
# tests/conftest.py:32-37
def store_backend() -> str:
    chosen = os.environ.get("HIPPO_TEST_STORE", "").strip().lower()
    if chosen:
        return chosen
    return "neo4j" if os.environ.get("NEO4J_URI") else "ladybug"
```
With no `HIPPO_TEST_STORE` and no `NEO4J_URI` set, the `store` fixture builds a real embedded `LadybugStore` in `tmp_path` (conftest.py:55-60) — **not** `FakeStore`. `FakeStore` only comes from `HIPPO_TEST_STORE=fake` explicitly (`just test-fake`, justfile:129-130).
**Verdict:** Contradicted (the shared-context/memory phrasing "throwaway Neo4j... via env var" is right, but a plain `pytest` run defaults to LadybugDB, not fake — worth stating precisely since it affects how fast an ad hoc test run is)
**Implication for the plan:** Running a single new test file with no env vars set (e.g. `pytest tests/unit/test_codegraph.py`) will use a real (if embedded/temp-file) LadybugDB, which is slower than the fake store and requires `real_ladybug` to import cleanly — `HIPPO_TEST_STORE=fake` is the fast-iteration choice mentioned in the worker rules, not the pytest default.

### R2-17: `tests/fixtures/` exists today
**Source:** A §1.5/2.7 ("One test fixture tree, `tests/fixtures/code_sample/`"), B §12 ("`tests/fixtures/code_repo/`")
**Evidence:** `ls tests/` → `__pycache__ conftest.py fakes unit`. No `fixtures/` directory anywhere under `tests/`.
**Verdict:** Missing
**Implication for the plan:** Both A's `tests/fixtures/code_sample/` and B's `tests/fixtures/code_repo/` are brand-new directories with no naming collision risk, but also no existing convention to match — today's fixtures are all inline Python (`make_checkout()` in `test_ingest_repos.py:144-160`) or the single `samples/acme_robotics.md` referenced by `tests/conftest.py:29` (`SAMPLE_PATH`). A checked-in fixture tree with literal source files would be the first of its kind in this repo.

### R2-18: Throwaway Neo4j test container is on 7688 / `testpassword`
**Source:** A §Verification step 2 ("Neo4j on the throwaway container (see memory `hippo-dev-loop`)"); shared context / user memory ("throwaway Neo4j on 7688 for tests")
**Evidence:**
```
# justfile:132-140
test-neo4j:
    @docker rm -f hippo-neo4j-test >/dev/null 2>&1 || true
    docker run -d --rm --name hippo-neo4j-test -p 127.0.0.1:17687:7687 -p 127.0.0.1:17474:7474 \
        -e NEO4J_AUTH=neo4j/hippo-password neo4j:5.26-community >/dev/null
    ...
    HIPPO_TEST_STORE=neo4j NEO4J_URI=bolt://localhost:17687 NEO4J_PASSWORD=hippo-password \
        {{venv}}/python -m pytest tests/unit || ...
```
The actual `just test-neo4j` recipe uses port **17687** and password **hippo-password**, not 7688/testpassword.
**Verdict:** Contradicted
**Implication for the plan:** This is a factual mismatch between the plan text/memory and the checked-in `justfile` — see gotcha below; whoever runs Neo4j-backed tests for this work should use `just test-neo4j` verbatim (or read the exact port/password from it) rather than the 7688/testpassword figures repeated elsewhere.

### R2-19: `tree-sitter`/`sqlglot` already present somewhere in the project
**Source:** task R2.10 ("whether `tree-sitter`, `tree-sitter-python`, `tree-sitter-typescript`, `sqlglot` are already present anywhere (they are not expected to be)")
**Evidence:** `grep -rn "tree.sitter\|sqlglot" pyproject.toml src/` → no matches. `pyproject.toml:6` (`requires-python = ">=3.11"`, not `>=3.12`); dependencies list (pyproject.toml:8-22) has no parsing libraries. `[project.optional-dependencies]` (pyproject.toml:24-32) only has `neo4j` and `dev` extras — no `code`/`treesitter` extra group exists as a place to add the new deps.
**Verdict:** Missing (as expected — this confirms the negative, not a surprise)
**Implication for the plan:** Adding `tree-sitter`/`tree-sitter-python`/`tree-sitter-typescript`/`sqlglot` is a plain addition to the top-level `dependencies` list (or a new optional-dependency group, matching the `neo4j` extra's pattern) with no existing pin to reconcile; the Python floor is 3.11, one below what A's "Verified on this machine" note (3.12) might imply is the baseline — worth confirming wheel availability for 3.11 too, not just cp311/cp312 as A states (A does say both).

### R2-20: `cli.py` is argparse-based; `RemoteHippo` has no path/blast/history methods
**Source:** A §4.3 ("CLI + remote": `hippo path A B`, `hippo blast SYMBOL`, etc., "behind a running server: `RemoteHippo` over the four endpoints")
**Evidence:** `cli.py:52-93` (`build_parser`) uses `argparse.ArgumentParser` + `add_subparsers`, one `add_parser` per command (`serve`, `mcp`, `pull-models`, `index`, `ask`, `sources`, `settings`, `users`, `user ...`) — no typer/click. `cli.py:101-111` dispatches via a plain `dict[str, Callable]`. `RemoteHippo` (`remote.py:32-136`) exposes exactly: `ask`, `sources`, `source`, `settings`, `add_upload`, `add_repo`, `roles`, `users`, `user_by_username`, `create_user`, `set_user_role`, `rotate_token`, `delete_user`, `wait_for_source`, `close` — no `path`/`blast`/`exception_path`/`history` methods, because the underlying web routes (`/api/code/...`) don't exist yet either.
**Verdict:** Built (argparse fact) / Missing (remote methods, as expected since A itself proposes them)
**Implication for the plan:** New CLI subcommands follow the exact same recipe as `index`/`ask`: an `add_parser` block in `build_parser`, an entry in the `handlers` dict, a function that calls `_context_or_running_server()` (cli.py:261-276) and branches on whether `remote` is `None`. `RemoteHippo` needs the four new thin methods added in the same style as `ask`/`sources` (one `self._json(self._client.get/post(...))` line each) — this only works once the corresponding `/api/code/*` routes exist (out of this worker's scope; tracked by whichever WP owns `web/routes/code.py`).

### R2-21: Answer prompt needs no change to prepend a synthetic "Code graph" passage
**Source:** A design summary ("Answering prepends one `Title: Code graph` pseudo-passage... to the unchanged `rag_qa` prompt"); B §6 ("`ask.answer_from_trace` prepends one synthetic passage titled `Paths`")
**Evidence:**
```python
# src/hippo/prompts.py:353-355
def qa_messages(question: str, passages: list[tuple[str, str]]) -> list[dict[str, str]]:
    """`passages` is a list of (title, text) pairs, best first."""
    context = "".join(f"Title: {title}\n{text}\n\n" for title, text in passages)
```
```python
# src/hippo/ask.py:40-53 (answer_from_trace)
passages = []
for ranked in trace.passages[:qa_top_k]:
    passage = graph.passage_by_id(ranked.passage_id)
    if passage is not None:
        passages.append((passage.id, passage.title, passage.text))
...
return answer_question(ctx.ollama, trace.question, passages)
```
`answer_question` (answerer.py:26-33) takes `(passage_id, title, text)` triples and strips the id before calling `qa_messages` with `(title, text)` pairs. Any extra tuple prepended to the `passages` list before this call renders as another `Title: ...` block with zero prompt changes.
**Verdict:** Built
**Implication for the plan:** A synthetic "Code graph" or "Paths" block is a one-line insertion (`passages.insert(0, (synthetic_id, "Code graph", rendered_text))`) into `answer_from_trace` (ask.py:44-48), gated on whether the trace has any code seeds/paths to show — no changes to `prompts.py` or `answerer.py` are needed either way, confirming both A and B's claims on this point.

---

## Surprises and gotchas for the synthesizer

1. **Neo4j test port/password mismatch.** The checked-in `justfile`'s `test-neo4j` recipe uses port **17687** and password **`hippo-password`** (justfile:135-138), not the 7688/`testpassword` figures that appear in A's plan text and in this fleet's own persisted memory. Anyone following the "7688/testpassword" instruction literally will connect to nothing. Worth fixing at the source (memory and/or A's doc) rather than re-deriving per worker.

2. **`CONTRACTS.md`'s "## To write" header is stale.** Everything under it (`src/hippo/ingest/`, `src/hippo/evals/`, `src/hippo/analysis/` — CONTRACTS.md:73-183) is already fully built and matches the current code almost line-for-line (I cross-checked every signature quoted there against the real files). Treat this section as **current, accurate documentation**, not a to-do list — the heading is just left over from before these modules existed.

3. **`replay_set` is closer to a one-function addition than new machinery.** `hipporag/retriever.py:429-445` already defines `trace_from_dict(data) -> Trace`, fully reconstructing every field (`fact_candidates`, `seed_entities`, `seed_passages`, `top_nodes`, `passages`, `filter`) from the JSON `store.add_result` persists. `analysis/simulate.py:24` imports and re-exports it. So "replay every stored result of a question set with no LLM" is: `trace_from_dict(json.loads(result["trace_json"] or stored dict)) → replay_filter(that_trace) → Retriever.retrieve(..., fact_filter=replayed)`, all three pieces already present and tested individually — B's checklist correctly flags golden-set replay itself as not built, but undersells how much of its plumbing already exists.

4. **FakeOllama's rule-based OpenIE only understands English "X `<relation>` Y." sentences** (`fake_ollama.py:67-93`, `RELATIONS` list, `_RELATION_RE`). Fed a code chunk today, `parse_entities` (fake_ollama.py:123-139) will still find CamelCase/PascalCase identifiers (any capitalized run) and register them as "entities", but `parse_triples` will almost never match a relation phrase inside code text — so existing tests that index a source containing code already get near-zero facts from code chunks, not the "noisy triples" B describes for a *real* model. A fixture that wants to demonstrate today's noisy-OpenIE-on-code problem for a before/after comparison will need deliberately relation-shaped sentences (e.g. in a docstring) or must accept that `FakeOllama` cannot reproduce the noise A/B describe — that noise is a real-Ollama-only phenomenon.

5. **No `Chunk` field carries a file path today.** Passage titles encode the path as a string (`"src/app.py (lines 1-2)"`, chunker.py:197-204) but the passage row itself has no structured `path` column (indexer.py:96-105: `{id, source_id, ordinal, title, text, embedding}`). Any code-graph work that needs to map a passage back to a file (for `defines`/`DEFINED_IN` links, or for `delete_passages_for_paths` in B §11) is starting from zero structured metadata, not extending an existing field.

6. **`test_indexer.py` pins two exact-equality count dicts** that any new indexer keys (`symbols`, `data_objects`, `code_edges`, `commits`, `refers_to`) will break by construction: `test_indexing_the_sample_returns_the_counts` (test_indexer.py:53-55, `counts == {"passages": 8, "entities": 31, "facts": 34, "synonyms": 0}`) and `test_reindexing_the_same_chunks_adds_no_duplicates` (test_indexer.py:92-98, same shape with zeros). A's plan already calls this out ("update the two exact-equality assertions"); confirmed these are the only two such assertions in the file — `test_blank_chunks_are_skipped...` (line 210-223) and `test_a_chunk_with_no_facts...` (line 236-238) have three more exact dict-equality checks each with the same 4-key shape and would need the same treatment.

7. **`test_ingest_pipeline.py` pins two exact chunk titles** that a symbol-per-passage chunker would change: `"src/tool.py (lines 1-2)"` (test_ingest_pipeline.py:138, zip fixture) and `"src/app.py (lines 1-2)"` (test_ingest_pipeline.py:205, repo fixture, via a monkeypatched `clone_repo`). Both come from a `def lift():\n    return 12\n`-style two-line fixture file — small enough that a real code extractor would likely produce exactly one module-header passage for it too, so these may not need changing in *content*, only in title format if the new scheme differs from `"path (lines a-b)"`.

8. **`repos.clone_repo` is monkeypatched, never really invoked, in every existing pipeline test** (`test_ingest_pipeline.py:189-198`, pattern: `monkeypatch.setattr(pipeline.repos, "clone_repo", fake_clone)` where `fake_clone` just writes files into `dest`). A real git checkout (with actual commit history) only appears in `test_ingest_repos.py:180-189` (`test_walk_repo_on_a_real_git_checkout`, via real `git init`/`add`/`commit` subprocess calls) and nowhere else in the current suite. Any new `git log`/`git blame` based history reader will need its own from-scratch real-git fixture pattern (matching `make_checkout`/`test_walk_repo_on_a_real_git_checkout`'s style), since nothing today fakes git history at the process level — it's either a real `git init` checkout or no git at all.
