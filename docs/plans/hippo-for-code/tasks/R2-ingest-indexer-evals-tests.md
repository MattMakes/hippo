# R2 — Ingest pipeline, indexer, OpenIE cost, evals, test conventions (worker: sonnet-2)

Read `00-shared-context.md` first. Output file: `docs/plans/hippo-for-code/research/R2-ingest-evals-tests.md`.

Files in scope: `src/hippo/ingest/*.py`, `src/hippo/hipporag/indexer.py`, `hipporag/openie.py`, `src/hippo/jobs.py`,
`src/hippo/evals/*.py`, `src/hippo/cli.py`, `src/hippo/remote.py`, `tests/conftest.py`, `tests/fakes/fake_ollama.py`,
`tests/unit/test_ingest_*.py`, `tests/unit/test_indexer.py`, `tests/unit/test_evals_*.py`, `tests/unit/test_cli.py`,
`justfile`, `pyproject.toml`, `docs/CONTRACTS.md` (ingest/indexer/evals rows).

- **R2.1** Document flow. From `pipeline.start_indexing` to store writes: which functions are called in what
  order, what the document/chunk objects are (dataclass names and fields), where a per-file "is this a
  supported code language" branch would naturally sit. Quote the routing code. Is there a `readers.lang_of`
  (B §5 claims so)? What does `chunker._chunk_code` do exactly (window size, overlap, from which setting)?
- **R2.2** `indexer.index_source` step by step: chunk → `openie.extract` → entity/fact rows → store writes →
  `find_synonyms` → `graph_version` bump. Name the store methods called and in what order. Where would
  "re-apply overrides after linking" (B D4) and "link structural edges" go? Is there any place a passage
  could be marked to SKIP OpenIE today?
- **R2.3** OpenIE cost. Confirm or refute "a 1500-character code chunk costs two LLM calls in `openie.extract`"
  (B §1). Count the `chat`/`chat_json`/embed calls per chunk. Is extraction concurrent (the `deque`/`in_flight`
  at `openie.py:91-103`)? Where are embeddings computed (per chunk, per entity, per fact) and batched?
- **R2.4** Repos. `repos.clone_repo` (depth flag? `--depth 1`?), `walk_repo` (filters, size limits, which
  extensions), `ingest/readers.py` (which file types, how `.py`/`.ts` are read). `test_ingest_limits.py`: which
  limits exist (file count, bytes, chunk count) that a 50k-line repo would hit.
- **R2.5** Reindex. `pipeline.reindex(source_id)` and `reindex_all`: exactly what is deleted and re-created;
  the `Busy` rule (what is it, where enforced); `Source.meta` shape and where it is written. Is there any
  per-file bookkeeping (path, hash, commit) that an incremental path could build on?
- **R2.6** Jobs. `jobs.py`: how an indexing job runs (thread? asyncio task?), cancellation
  ("cancellable indexing" in commit f65afe2), progress reporting. Where would a long git-history pass report progress?
- **R2.7** Evals. `evals/question_maker.py`: existing origins (`'generated'`?), signature of the generator(s),
  what a question row contains (`gold_passage_ids`, `kind`, `notes`?). `evals/runner.py`: `run_question`
  signature, what it persists per question (does it store the `Trace`, including the filter verdicts and
  candidate facts, so a NO-LLM replay is possible? B §7 `replay_set` depends on this). `evals/metrics.py`:
  metric names. `evals/judge.py`: when the LLM judge runs.
- **R2.8** Test conventions. `tests/conftest.py`: fixtures, how the three stores are parametrised (env var?
  marker? `HIPPO_STORE`?), how tests get a `ctx`. `tests/fakes/fake_ollama.py`: does it count calls per
  method (B §12 relies on "FakeOllama counts calls")? How does it produce embeddings and OpenIE output
  deterministically (rules keyed by text?). Which tests currently create a temporary git repo or folder
  (`test_ingest_repos.py`) and how. `justfile` test recipes: `test`, `test-fake`, `test-neo4j`, `test-all` — what
  each sets. Is there a `tests/fixtures/` dir today?
- **R2.9** CLI and remote. `cli.py` commands and their structure (argparse? typer?); `remote.py` purpose
  (A §4.3 says "CLI + remote"). How would `hippo index <url> --history N` and `hippo reindex <id> --changed` be added?
- **R2.10** Dependencies. `pyproject.toml`: Python version floor, how optional extras are declared, and
  whether `tree-sitter`, `tree-sitter-python`, `tree-sitter-typescript`, `sqlglot` are already present anywhere
  (they are not expected to be). What the `venv` recipe in the justfile does.
- **R2.11** Answering. `hipporag/answerer.py` `answer_question` signature and the passage tuple shape;
  `prompts.py` `rag_qa` prompt; confirm whether prepending a synthetic passage titled `Paths` / `Code graph`
  (B §6, A design summary) needs any prompt change.

Gotchas to look for: any test that asserts the exact number of LLM calls or chunks for a repo (would pin
the new no-OpenIE-for-code behaviour), size limits that would truncate repos, and anything that treats
`Source.kind` (repo vs file vs zip) specially.
