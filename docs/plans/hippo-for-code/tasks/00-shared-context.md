# Shared context for every worker on the "hippo for code" planning effort

You are a research worker in a herdr fleet. The orchestrator is building a NEW implementation plan
for adding code-as-a-first-class-data-type to hippo. Your job is to ground that plan in the real code.

## The two inputs (read both before anything else)

- `docs/plans/hippo-for-code/inputs/A-existing-plan-phase1.md`  "Code as a first-class data type in hippo (phase 1)".
  An implementation-level plan with 4 work packages. Its "Context" section records EXPLICIT USER DECISIONS
  dated 2026-09-07 and a "Verified on this machine" block of toolchain facts. Treat those as facts.
- `docs/plans/hippo-for-code/inputs/B-design-against-built.md`  "hippo for code: the design, against what is already built".
  A research-shaped architecture (15 sections). Its section 1 is a Built/Missing checklist that cites files
  and line numbers. Those citations are CLAIMS to verify, not facts.

A and B disagree on core shape (A: new `Symbol`/`DataObject`/`Commit` tables + `CODE_EDGE`; B: symbols are
`Entity` rows with a `kind` column, structure is `Fact` rows + a `STRUCT` rel). The synthesizer will decide.
You do NOT decide architecture. You report what the code does, precisely, so the decision is grounded.

## Repo and rules

- Repo root: `/Users/mascott/projects/hippo`. Source in `src/hippo/`, tests in `tests/`, docs in `docs/`.
- Research workers are READ-ONLY on `src/`, `tests/`, `docs/*.md`, `data/`, `.venv/`. Do not edit code.
  Write only to your own output file under `docs/plans/hippo-for-code/research/`.
- Do not start Neo4j, docker, or the app. Do not touch `data/`. If you must run something to confirm a
  behaviour, use `.venv/bin/python` and only the fast fake-store tests (`just test-fake` or a single
  `.venv/bin/pytest tests/unit/<file> -q`). Prefer reading over running.
- Existing conventions to respect when you describe things: `docs/CONTRACTS.md` lists module contracts;
  `docs/FIDELITY.md` describes what must stay byte-identical to the HippoRAG reference.

## Output format (mandatory)

Write your file as:

1. A **Verdict table** at the very top: one row per claim id: `| id | claim (short) | verdict | key file:line |`.
   Verdicts: `Built` | `Partial` | `Missing` | `Contradicted` | `Unclear`.
2. Then one section per claim:
   ```
   ### <id>: <claim in one line>
   **Source:** A §x.y / B §n
   **Evidence:** `path/to/file.py:LINE` — quoted snippet, max 5 lines, verbatim
   **Verdict:** Built | Partial | Missing | Contradicted | Unclear
   **Implication for the plan:** one or two sentences, factual, no architecture proposals
   ```
3. A closing section **"Surprises and gotchas for the synthesizer"**: anything you found that neither A nor B
   mentions and that would break or reshape the plan (naming collisions, hidden coupling, tests that pin
   behaviour, TODOs, quirks).
4. Keep the whole file under ~400 lines. Precision beats coverage. Every file path must be real and every
   line number must be checked with `grep -n` or `sed -n`.

## Worker protocol

- Record short progress notes in the ledger as you go (the herdr-worker skill tells you how).
- If blocked or if a claim needs a decision only the orchestrator can make, send
  `horch tell orchestrator "[<your-role>] <question>"` and wait.
- When finished: make sure the file is written, then send
  `horch tell orchestrator "[<your-role>] DONE: <one-line summary> -> <output path>"`, record the summary in
  the ledger, and close your pane.
