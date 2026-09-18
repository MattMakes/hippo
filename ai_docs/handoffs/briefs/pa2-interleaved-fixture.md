# Brief: PA2 finding 5, the interleaved two-generation relation-support fixture

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `pa2f5` (branch `wp/pa2f5`, base = the `rag-it-all-tibs` HEAD named in the spawn message).

GOAL: One new test module proves the multi-contributor branch of `src/hippo/status.py` (`pair in row.source_generations`, `:~124`) and the corresponding projection path in `src/hippo/knowledge/access.py` (`:~445-447`, support grouped across all authorized rows) with a relation supported by TWO generations of TWO sources that stage CONCURRENTLY, both enriching the same `(assertion_version_id, derivation_group)` proof group, and are then sealed and published. This closes the last OPEN row of `ai_docs/reports/2026-09-12-pa8-signoff.md` (PA2 finding 5; `ai_docs/plans/rag-it-all-task-5-production-activation.md:~254` names the case). Committed on `wp/pa2f5`.

CONTEXT: opus-17's `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa8close.md` (row "PA2 f5") has the repro of why the SEQUENTIAL shape is refused by design (`generations.py:~601` "Sealed assertion proof group cannot gain support") and a ~60-line design for the interleaved variant of `tests/unit/test_structural_loading.py::published()` with the exact assertions; follow it. The coordinator only serialises builds per source, so two sources staging into one proof group is a legal production shape.

REQUIRED BEHAVIOR:
1. NEW `tests/unit/test_multi_generation_support.py`: build two sources, open both generations in staging, enrich both into the same proof group, seal and publish both; assert (a) the relation is projected once with BOTH `(source, generation)` pairs in `source_generations`, (b) status counts it once per source lane, (c) revoking one source's audience removes only that pair and the relation survives on the other's proof, (d) tombstoning one source leaves the relation supported by the other, (e) an unpublished third contributor never appears. Run on Fake and Ladybug.
2. No production change. If the branch turns out unreachable or a test exposes a defect, stop and report with the exact line.
3. If the fixture needs a helper from `tests/unit/test_structural_loading.py`, import it; do not edit that file.

FILES:
  - own: NEW `tests/unit/test_multi_generation_support.py`, NEW `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa2f5.md`.
  - do NOT touch: anything else (CC8 is live on `src/hippo/knowledge/*`; opus-19 on `src/hippo/store/*`, `context.py`, `status.py`).

STEPS: worktree + venv (`mcp==2.1.1` pin); RED is not applicable for a coverage test — instead prove the test discriminates by temporarily breaking the multi-contributor branch locally (e.g. make `status.py`'s branch take the single-pair path) and showing the failure, then restore byte for byte and say so; GREEN Fake and Ladybug with `-W error`; Ruff; evidence with the two commands and the discrimination proof; one commit.

DONE WHEN: green on both backends; evidence written; `horch done` lists the test names, counts and logs.

REPORT: `horch note` per step; `horch tell orchestrator "[<role>] BLOCKED: ..."` if the shape is unreachable.
