# Brief: CC11b — the full-size CD9 LadybugDB run and the final code-capture evidence

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `cc11b` (branch `wp/cc11b`, base = the `rag-it-all-tibs` HEAD named in the spawn message; CC11 and the query-time reads fix `qscope` are merged).

GOAL: The CD9 CHECK line of `ai_docs/gates/rag-it-all/task-5-code-capture/GATES.md` (the nine ledger files plus `tests/unit/test_code_capture_acceptance.py`) passes on LadybugDB at the ledger size (48 files per language, ~270 accepted files) with the production buffer pool, its phase timings and memory recorded, and the full Fake suite passes on the final tree, so the orchestrator can run the CD1–CD10 checker and the CD10 review. Committed on `wp/cc11b`.

CONTEXT (read first): CC11's `ai_docs/gates/rag-it-all/task-5-code-capture/evidence-cc11.md` — its "Exact command lines for cc11b" section is your command list verbatim, its "Scenario knobs" (`HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE`, `HIPPO_CODE_ACCEPTANCE_BUFFER_POOL_BYTES` default 4 GiB, `HIPPO_CODE_ACCEPTANCE_TIMINGS=<path>` writes `<path>` and `<path>.progress`), its phase list and its findings 3, 22 and 25; `evidence-qscope.md` (the query-time reads fix and its before/after phase numbers at N=8); `evidence-lbpool.md` (the pool does not grow, it FAILS with "Buffer manager exception"; the process RSS is pool + Python heap + tree-sitter + query intermediates — at N=2 peak RSS was 10.2 GiB against a 4 GiB pool); `code-capture-notes.md`. Machine rules: one heavy Ladybug run at a time; keep a free-memory guard on the python PID (pattern `venv/bin/python .venv/bin/pytest`, not the zsh wrapper) that stops ONLY your pytest if system unused memory drops below 4 GB; never touch `data/`, `.rag-dev-data/`, port 8011 or Ollama; no time-based claims.

REQUIRED BEHAVIOR:
1. Step up on LadybugDB with the 4 GiB pool and the timings knob: N=8 first (compare its phases with qscope's before/after numbers), then N=16, then N=48 (the ledger line). At each step record phases, peak RSS, knowledge and native read counts from the timings file, and the pool size actually needed (if a step fails with the buffer-manager message, rerun with a larger explicit pool and record both). If N=48 cannot complete under the guard, record the largest completed size, the phase and RSS where it stopped, and say so plainly in the evidence and in the CD9 line you propose — never present a smaller run as the ledger size.
2. Run every CD CHECK line (CD1–CD8, CD10; CD9 from item 1) verbatim from `GATES.md` on the final tree, each to `/tmp/hippo-cc11b-cd<N>.log` with `echo EXIT $?`, and the full Fake suite (`HIPPO_TEST_STORE=fake .venv/bin/pytest tests -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`), which CC11 never completed on the final tree.
3. Apply nothing to `GATES.md`. Verify CC11's "Ledger replacement lines" against the final tree (they were written before qscope), correct any that drifted, and write the final set plus the CD9 EXPECT (with its counts) in NEW `evidence-cc11b.md`; the orchestrator pastes them.
4. If any CD line fails for a reason that is not a harness limit, stop and report with the failing test and traceback; do not fix production code.

FILES:
  - own: NEW `ai_docs/gates/rag-it-all/task-5-code-capture/evidence-cc11b.md`; `tests/unit/test_code_capture_acceptance.py` and `tests/fakes/code_capture_repo.py` ONLY for a harness fix the run needs (name it); nothing else.
  - do NOT touch: production code, the plan, `GATES.md`, `docs/`, other evidence files.

STEPS: worktree + venv (`mcp==2.1.1` pin); confirm the tree contains qscope and lbpool (`git log --oneline -5`); item 1 with the guard armed; item 2 (Fake lines can run while a Ladybug step runs only if memory allows; never two Ladybug runs); item 3; Ruff format --check on the evidence; one commit.

DONE WHEN: evidence written with the per-size table (size, files, phases, peak RSS, pool, read counts, result), every CD line's EXIT and counts, the full Fake result, and the final ledger lines; `horch done` lists the CD9 result at the ledger size (or the honest largest size), the numbers, and the logs.

REPORT: `horch note` after each size step and each gate line; `horch tell orchestrator "[<role>] BLOCKED: ..."` if the machine cannot host the N=48 run or a gate fails on production code.
