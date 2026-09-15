# Brief: CDK S1b-fix — the three items S1b handed off

Read `ai_docs/handoffs/fleet-worker-rules.md` first, then `ai_docs/handoffs/briefs/cdk-s1b.md` (both
amendment sections) and the "Handed off" section of `ai_docs/gates/rag-it-all/cdk/evidence-s1b.md`,
which specifies each item. Use the worktree recipe with name `s1b-fix` (branch `wp/s1b-fix`, base =
the `rag-it-all-tibs` HEAD named in the spawn message, which includes S1b merged at `9e5b93c`).

GOAL: three small, separately committed changes, each green:
1. **B1 / R47 (CK5 blocker).** `src/hippo/knowledge/prose_preparation.py` lines 164–174 pass
   `registry_fingerprint=gen.registry_fingerprint` to `generation_for_inputs`;
   `src/hippo/knowledge/staged_code.py` line 310 normalizes `registry_fingerprint` on both sides of
   the compare. Two tests, one per file, each building a generation with a fingerprint and proving
   the compare accepts it (and still refuses a generation that differs in any identity field).
2. **`Registry.evidence_source_definition(name) -> EvidenceSourceDefinition`** in
   `src/hippo/knowledge/registry.py`, returning the registered definition unchanged (built-ins:
   `family=None, evidence_class=None`, callers read `EVIDENCE_CLASS_DERIVATION`; extension sources
   carry both; unknown name raises the registry's "Unknown evidence source"), with tests in
   `tests/unit/test_registry.py` (ruling R62).
3. **The projection exclusions one-liner** in `src/hippo/knowledge/projection.py`: a caller's
   `exclusions` counter gains no `locator_kinds: 0` entry when nothing was left out
   (`excluded.get(...)`), with a test in `tests/unit/test_registry_model.py`.

CONTEXT: rulings R39, R40, R47, R62 in `ai_docs/plans/cdk-rulings.md`; the review's B1 section in
`ai_docs/reports/2026-09-15-cdk-plan-review.md`; S1a-fix's "Review amendments" evidence section.

FILES:
  - own: the five source files named above at those lines only; `tests/unit/test_registry.py`,
    `tests/unit/test_registry_model.py`, and one new test file per B1 file if the existing suites
    (`tests/unit/test_prose_generation.py`, `tests/unit/test_code_generation.py`) are not the right
    home (say which); new `ai_docs/gates/rag-it-all/cdk/evidence-s1b-fix.md`.
  - do NOT touch: anything else; especially `store/*`, `ingest/*`, `connectors/*`, `tests/fakes/*`.

STEPS: worktree + venv (the rulebook recipe, with the `mcp==2.1.1` pin). Per item: RED, GREEN,
commit. Then the CK1 Fake and LadybugDB CHECK lines of `ai_docs/gates/rag-it-all/cdk/GATES.md`
verbatim, `tests/unit/test_prose_generation.py tests/unit/test_code_generation.py` on Fake, and the
CK7 Ruff lines over your files. Evidence file: RED and GREEN log paths and counts per line.

CONSTRAINTS: the S1b brief's constraints hold (pytest form with `-W error` and logs, never Neo4j,
never `pkill -f`, stage only owned files, never push, rebase or merge). No identity field changes;
existing checksums unchanged. No duration language.

DONE WHEN: three commits green; the CK1 lines, the two ingest suites and Ruff exit 0; `horch done`
names the commits, counts, log paths and open questions.

REPORT: `horch note` per item; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a question
the brief, the evidence and the rulings do not answer.
