# Brief: CC5 — mapped code chunks (managed code capture, task 5)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `cc5` (branch `wp/cc5`, base = the `rag-it-all-tibs` HEAD named in the spawn message; CC4 is merged).

GOAL: `prepare_code_chunks` turns CC4's `CodeUnit`s into the exact passages the legacy indexer produces for code (symbol passages, data-object mention passages, the chunker's generated context header, and commit passages), each carrying its exact original file-line ranges and explicitly marked generated segments, with seeded parity against the committed legacy chunker. Plan sections 4 and 6 of `ai_docs/plans/rag-it-all-task-5-managed-code-capture.md`; gate CD4 of `ai_docs/gates/rag-it-all/task-5-code-capture/GATES.md`. Pure: no store, model or clock. Committed on `wp/cc5`.

CONTEXT: the prose precedent `src/hippo/ingest/prepared_chunks.py` (`prepare_prose_chunks`, `PreparedChunk` with ordered original ranges, generated separator and title dependencies, honest complete-line closure) and its 2,000-case parity test; the legacy code chunking you must reproduce: `src/hippo/ingest/chunker.py` (the context header at `~:92` and the commit passage shape), `src/hippo/hipporag/indexer.py` (how symbol, data-object and commit passages are assembled and which text is synthesized), `src/hippo/codegraph/extract.py` and the walkers for symbol spans; CC4's `CodeUnit`/`CodeProvenance` (`src/hippo/ingest/code_provenance.py`, read its evidence `evidence-cc4.md`). The design review (`ai_docs/reports/2026-09-12-code-capture-plan-review.md`) may bind details; read it if present.

REQUIRED BEHAVIOR:
1. `src/hippo/ingest/prepared_code_chunks.py`: `prepare_code_chunks(units, *, facts, settings) -> PreparedCodeChunks` where each `PreparedCodeChunk` names its kind (`symbol`, `data_object`, `header`, `commit`), the exact original ranges (file logical path plus complete-line ranges from CC4's locators), and the generated segments as dependencies (header text, mention wording, commit rendering) so the binding task can create `RetrievalView`+`DerivedRecord` over original spans exactly as `input_binding._view` does for prose. The public `Chunk` output stays byte-identical to the legacy chunker for the same inputs.
2. Seeded parity: 2,000 random units (mixed languages the walkers support) produce the same `Chunk` texts and order as the committed legacy path; every generated segment is marked and every original byte is covered by exactly one original range or one generated segment.
3. Refusals: a unit whose provenance is binary/empty/oversized produces no chunk and an explicit reason; nothing truncates silently.
4. Rule version (plan ruling 10, design review M2): the module exports a frozen `CODE_CHUNK_RULE_VERSION` constant (bump it whenever the chunk texts, kinds, ranges or generated segments could change) and every `PreparedCodeChunks` carries it, so CC6/CC9 can fold it into the generation configuration that `generation_for_inputs` hashes; a test pins the current value and the parity fixture's digest against it.

FILES:
  - own: NEW `src/hippo/ingest/prepared_code_chunks.py`, NEW `tests/unit/test_prepared_code_chunks.py`, NEW `ai_docs/gates/rag-it-all/task-5-code-capture/evidence-cc5.md`.
  - do NOT touch: anything existing; if the legacy chunker needs a seam to be called without side effects, stop and ask with the exact function.

STEPS: worktree + venv; baseline `tests/unit/test_ingest_chunker.py tests/unit/test_prepared_chunks.py tests/unit/test_code_provenance.py` green (correct names with `ls`); RED; implement; GREEN Fake; Ruff; evidence with the CD4 command result; commit in one or two commits.

DONE WHEN: green with `-W error`; parity proven; evidence written; `horch done` lists the public signature, the chunk kinds, counts and logs.

REPORT: `horch note` per step; `horch tell orchestrator "[<role>] BLOCKED: ..."` for contract questions.
