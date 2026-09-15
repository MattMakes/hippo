# Brief: PA8 closure batch (production activation sign-off)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `pa8close` (branch `wp/pa8close`, base = the `rag-it-all-tibs` HEAD named in the spawn message).

GOAL: Close every OPEN row of the PA8 sign-off review that has a named fix, so the next sign-off pass can record "independent review pass" for `ai_docs/gates/rag-it-all/task-5-production-activation/GATES.md`. The review is `ai_docs/reports/2026-09-12-pa8-signoff.md`; its section "What would make PA8 signable" (items 1–5; item 6 is the orchestrator's) is your work list, and its findings table gives each row's file:line and the exact fix. Committed on `wp/pa8close`.

CONTEXT: the activation plan `ai_docs/plans/rag-it-all-task-5-production-activation.md`; the earlier reviews the table cites (`ai_docs/reports/2026-09-11-pa*.md`, `2026-09-12-pa4-wrapup-review.md`); `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-cleanup4.md` (the previous closure batch, whose "unowned" list you inherit) and `session-audit.md` (the call-site audit produced at `043ca51`); `ai_docs/handoffs/briefs/task4-notes.md` (open items and decisions already taken; do not reopen a decided item). The code-capture fleet is live in parallel: CC2 owns `src/hippo/store/*`, CC6 owns `src/hippo/knowledge/code_binding.py`; you must not touch those.

REQUIRED BEHAVIOR (the review's numbering):
1. Item 1: the two one-word documentation fixes (wrap-up findings 7 and 16).
2. Item 2: the LOW code batch: findings 8, 9, 11, 17, 6, 13, PA4d finding 2's missing test, and findings 18 + C1 together (the `caller_error` line in `users.py`/`auth.py`/`pages.py`, shrinking the `str(exc)` allow-list rather than growing it). Each fix is the one-liner the review names; if a fix turns out to need more than that, do the rest of the batch, leave that row OPEN and say why in the evidence.
3. Item 3: the three coverage gaps (PA2 finding 5, PA3a finding 5, PA3b finding 8), plus PA3a finding 3 and PA2 finding 6, plus T3's two verified-dense-over-HTTP tests now that the fixture blocker is gone. Tests only; no production change unless a test exposes a defect, in which case stop and report it.
4. Item 4: refresh `session-audit.md` at HEAD: re-run the audit's own sweep command (recorded at the top of that file), add the `cli.py:567 _sources_locally` row with its class (finding S1), and re-check every existing row's line number; record the HEAD you audited in the file's header.
5. Item 5: the three lines in the plan's rollout section assigning the five DEFERRED items (the `model_unavailable` behaviour change, the CLI ownership question, `add_repo`'s legacy status) to Task 16, so the deferral is in the plan rather than a scratch file.
6. Do NOT "fix" the items the review lists under "Items that should not be fixed" (wrap-up finding 12, 4b-i F2 and the rest of that paragraph); do not touch `GATES.md` (the orchestrator records gates); do not edit `docs/`.

FILES:
  - own: the files the named findings point at under `src/hippo/web/*`, `src/hippo/ingest/managed_activation.py` (finding 8's `STAGES` only), `src/hippo/knowledge/public_errors.py` (docstring only), the tests the findings name plus NEW tests, `ai_docs/gates/rag-it-all/task-5-production-activation/session-audit.md`, `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa4e.md` (finding 16's one word), `ai_docs/plans/rag-it-all-task-5-production-activation.md` (rollout section, three lines), NEW `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa8close.md`.
  - do NOT touch: `src/hippo/store/*`, `tests/fakes/fake_store.py`, `src/hippo/knowledge/*` other than the one docstring, `src/hippo/ingest/*` other than `STAGES`, `GATES.md`, `docs/`, the checkpoint.

STEPS: worktree + venv (`mcp==2.1.1` pin); baseline on Fake: the PA1–PA6 CHECK lines from `GATES.md` (copy them verbatim; PA5/PA6 need AnyIO form (b) because their files import `fastapi.testclient` at module level) green; RED for each new test; fix; GREEN on the same lines plus every test file you touched; Ladybug on `tests/unit/test_managed_source_lifecycle.py tests/unit/test_managed_pipeline_activation.py` only; Ruff check + format --check on every touched file including the Markdown; evidence file with a row per finding (id, status CLOSED/OPEN, commit, test name); commit in two commits (docs+audit+plan, then code+tests).

DONE WHEN: every row of items 1–5 is CLOSED or explicitly OPEN with a reason; PA1–PA6 lines green on Fake; evidence written; `horch done` lists the commits, the closed and still-open finding ids, and the logs.

REPORT: `horch note` per item; `horch tell orchestrator "[<role>] BLOCKED: ..."` for a fix that would change behaviour beyond the review's one-liner.
