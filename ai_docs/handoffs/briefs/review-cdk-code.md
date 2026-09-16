# Brief: independent SPEC and QUALITY review of the Connector Developer Kit (gate CK7)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree
(`/Users/mascott/projects/hippo`) at the HEAD named in the spawn message. Read-only except your one
output: `ai_docs/reports/<today>-cdk-code-review.md`. You may run tests on Fake and on LadybugDB
(never Neo4j, never `pkill -f`), one pytest process at a time, logs under `/tmp/hippo-review-*.log`.

GOAL: rule whether the kit as merged meets `docs/spec/connector-developer-kit.md` (as amended by the
rulings) and the specification's section 3 contract (`docs/spec/enterprise-graph-rag-v1.md`), and
whether CK1–CK6 of `ai_docs/gates/rag-it-all/cdk/GATES.md` are MET on their CRITERIA, not only on
their CHECK lines; and confirm that the two standing rules (no model call inside `emit`; no
unearned relation label) are enforced by tests, not stated.

CONTEXT: the two plan reviews (`ai_docs/reports/2026-09-15-cdk-plan-review.md`,
`2026-09-15-cdk-s4-replan-review.md`) and the rulings `ai_docs/plans/cdk-rulings.md` (R1 onward;
a ruling supersedes the plan section it names); the evidence files
`ai_docs/gates/rag-it-all/cdk/evidence-*.md` (every slice's counts, overrides and open questions)
and `neo4j-parity.md`; the code: `src/hippo/connectors/**`, `src/hippo/knowledge/{registry,
contract,locators,builtin_types,predicates,staged_records}.py`, the v8 parts of
`src/hippo/store/migrations.py`, `store/knowledge.py`, `store/generations.py`, the lane edits in
`src/hippo/ingest/{managed_activation,prose_generation,code_generation}.py`, `src/hippo/cli.py`'s
connector commands, `src/hippo/web/routes/connectors.py`, `src/hippo/mcp_server.py`'s
`hippo_connectors` tool, `docs/spec/cdk-guide.md`, and every `tests/unit/test_connector_*.py`,
`test_registry*.py`, `test_staged_records.py`.

REQUIRED:
1. SPEC per gate CK1–CK6: for each CRITERIA clause, the test (file and name) that proves it, or
   "no test"; the verdict MET / NOT MET per gate.
2. The two standing rules: the tests that enforce them and how a violation would fail.
3. Invariants, verified by reading and by running a probe where cheap: reads never validate
   vocabulary (R39); existing row identities and the v7 checksum unchanged; the pre-kit prose and
   code outputs byte-identical through the lanes (the parity suites, and what they compare);
   refusal at registration never at emit; unknown policy is deny everywhere including the principal
   map; the active generation is never deleted; publication only through `BuildAuthority`; the
   guard is the one guard.
4. QUALITY: layering (`tests/unit/test_layering.py`, `test_import_order.py`), duplication against
   `staged_prose.py`/`staged_code.py`/`input_binding.py`, error surfaces through
   `public_errors.py` and the routes, determinism, test honesty (mutation-style spot checks where
   the evidence claims a test bites), and the open questions each evidence file left.
5. Findings as a table (id, severity BLOCKER/MAJOR/MINOR, file:line, the gate or invariant, the
   exact fix), a verdict per gate, a QUALITY verdict, and an overall verdict for CK7: PASS / PASS
   WITH CHANGES / FAIL.

FILES:
  - own: `ai_docs/reports/<today>-cdk-code-review.md`.
  - do NOT touch: anything else.

DONE WHEN: the report exists with the tables and verdicts above; `ruff format --check` clean on it;
`horch done` with the verdicts and the counts per severity.

REPORT: `horch note` per gate reviewed; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for
a missing input.
