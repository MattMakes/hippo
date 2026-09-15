# Brief: CC4 — repository capture and code provenance (managed code capture, task 4)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `cc4` (branch `wp/cc4`, base = the `rag-it-all-tibs` HEAD named in the spawn message).

GOAL: An ordered, normalized, bounded inventory of a repository tree (or archive or single code file) is captured as immutable accepted inputs with explicit exclusion reasons and refusals, and each accepted code or config file decodes to text with exact complete-line locators, so that reordering the walk never changes the accepted identity. Gate CD3 of `ai_docs/gates/rag-it-all/task-5-code-capture/GATES.md`; plan sections 3, 5, 6 and 10 of `ai_docs/plans/rag-it-all-task-5-managed-code-capture.md`. Committed on `wp/cc4`. Pure preparation: no store, no model, no clock (the capture instant is a parameter).

CONTEXT: the plain-prose capture and provenance you mirror: `src/hippo/ingest/accepted_inputs.py` (`capture_raw_inputs`, `CaptureLimits`, the canonical manifest), `src/hippo/knowledge/inputs.py` (the moved contracts), `src/hippo/ingest/provenance.py` (`read_plain_provenance`, complete-line locators, Unicode parser-byte mappings), `src/hippo/knowledge/raw_artifacts.py`; the legacy walk you must reproduce faithfully: `src/hippo/ingest/repos.py` (`walk_repo`, exclusions), `src/hippo/ingest/readers.py` (`is_supported`, `read_zip`, code/config detection, `CODE_MAX_FILE_BYTES` and the other rails), `src/hippo/codegraph/extract.py` (which files the walkers accept). Tests to model on: `tests/unit/test_accepted_inputs.py`, `test_managed_reader_provenance.py` (or the provenance test the checkpoint names), `test_ingest_readers.py`.

REQUIRED BEHAVIOR (plan §3/§6):
1. `src/hippo/ingest/repo_capture.py`: `capture_repository_inputs(root, *, limits, exclusions, observed_at, provider_revision) -> RepositoryCapture` producing the sorted (normalized logical path) tuple of `FileInput`/`ExcludedInput` descriptors, each exclusion carrying a closed reason (`ignored_path`, `binary`, `too_large`, `unsupported_language`, `symlink`, `submodule`, `not_regular`), a bounded refusal when the tree exceeds `CODE_MAX_FILES` or the total byte rails, and then the same immutable raw capture the prose lane performs (`capture_raw_inputs`) so the manifest is canonical and reordering the walk or the directory listing does not change `manifest.sha256`. Archive (`.zip`) and single-file inputs go through the same function.
2. `src/hippo/ingest/code_provenance.py`: `read_code_provenance(raw, *, budget) -> CodeProvenance` decoding text with the same explicit/binary/empty outcomes as the plain reader, exact complete-line locators (1-based line, byte offsets, both ends inclusive-exclusive as the plain reader defines), Unicode-safe parser-byte mappings for tree-sitter, language detection by the walker's rule (not by content sniffing), and a frozen `CodeUnit` per file the chunker and walkers can consume without re-reading disk.
3. Tests: 20,000-case seeded decoder parity against the plain reader where they overlap; walk-order independence; every exclusion reason; every refusal; symlink and submodule handling; `.zip` and single file; identity stability across two captures of the same tree; a tree that exceeds the file rail refuses before any raw write.

FILES:
  - own: NEW `src/hippo/ingest/repo_capture.py`, NEW `src/hippo/ingest/code_provenance.py`, NEW `tests/unit/test_repo_capture.py`, NEW `tests/unit/test_code_provenance.py`, NEW `ai_docs/gates/rag-it-all/task-5-code-capture/evidence-cc4.md`.
  - do NOT touch: anything existing (if a helper in `accepted_inputs.py`/`provenance.py` must become shared, stop and ask with the exact function name; the reviewer may also redirect you).

STEPS: worktree + venv (with the `mcp==2.1.1` pin); baseline `tests/unit/test_accepted_inputs.py tests/unit/test_ingest_readers.py` green; RED; implement; GREEN Fake (the two new files plus the baseline set); no Ladybug needed (pure), say so; Ruff; evidence with the CD3 command result; commit in one or two commits.

DONE WHEN: green with `-W error`; evidence written; `horch done` lists the two public signatures verbatim, the closed exclusion-reason set, counts and logs.

REPORT: `horch note` per step; `horch tell orchestrator "[<role>] BLOCKED: ..."` for contract questions.
