# Brief: canonical arrow order inside each code vertex of the view fingerprint

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`) at HEAD `e709aad` or later. Do NOT commit; the orchestrator commits.

GOAL: `view_fingerprint` of an unchanged code-bearing corpus is identical across loads on every backend: the `code_out` component sorts the arrows within each vertex canonically, not in store order.

CONTEXT:
- The fact-order fix just merged (`ai_docs/gates/rag-it-all/task-5-production-activation/evidence-factorder.md`) found this sibling defect: `src/hippo/knowledge/replay.py:35` builds `[asdict(edge) for _, arrows in sorted(graph.code_out.items()) for edge in arrows]`, sorting vertex keys but iterating `arrows` in whatever order the store returned them; Ladybug returns them in arbitrary order, so a code-bearing corpus gets a different fingerprint per load (generated evaluation sets deny, saved answers withhold). Check `replay.py:161` (`for values in graph.code_out.values()`) for the same dependence.
- Precedent and rule: the fact fix (`src/hippo/hipporag/graph_index.py::canonical_facts`) imposes order at `GraphIndex` materialisation keyed by stable identity. For arrows, prefer the same: sort each vertex's arrow list at materialisation (`GraphIndex.load`, `scoped`, `projection._assemble`, `compose_graphs`) by a stable key such as `(edge.target, edge.kind, ...)` from the edge's dataclass fields; if that is invasive, sorting inside the fingerprint payload at `replay.py:35` (and :161 if it matters) is acceptable as long as every consumer of `code_out` order that feeds identity goes through the same sort. Say which you chose and why.
- Golden test: `tests/unit/test_derived_projection.py::test_original_only_graph_ids_and_fingerprints_are_unchanged`. If its constants change because the fixture has multi-arrow vertices whose Fake insertion order was unsorted, update the constants in that test with a comment stating that arrows are now sorted within a vertex and that the previous value encoded store order, which was never stable on Ladybug. Do not weaken any other assertion.

FILES:
  - own: `src/hippo/knowledge/replay.py`, `src/hippo/hipporag/graph_index.py` (arrow ordering only, beside `canonical_facts`), `src/hippo/knowledge/projection.py` (`_assemble` only, if you sort at materialisation), `tests/unit/test_fact_order_determinism.py` (add the arrow cases there), `tests/unit/test_derived_projection.py` (golden constants only, if needed).
  - do NOT touch: anything else (another worker owns the web routes in this tree; reviewers are read-only).

STEPS:
1. Baseline: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_fact_order_determinism.py tests/unit/test_derived_projection.py tests/unit/test_graph_index.py tests/unit/test_dense_capability.py tests/unit/test_structural_loading.py -q -o addopts='' -W error > /tmp/hippo-arrows-baseline.log 2>&1; echo EXIT $?` green.
2. RED: a test that builds a code-bearing corpus with a vertex holding several arrows, loads the graph twice with the arrow lists deliberately permuted between loads (monkeypatch the loader or shuffle `code_out` before fingerprinting), and asserts identical `view_fingerprint`; on Ladybug (`HIPPO_TEST_STORE=ladybug`) load twice through the real store and assert identical fingerprints; save `/tmp/hippo-arrows-red.log` (Fake shuffle case must fail before the fix).
3. Implement; GREEN: the baseline command plus `tests/unit/test_managed_eval_activation.py tests/unit/test_eval_access.py tests/unit/test_web_code.py`, log `/tmp/hippo-arrows-fake-green.log`; Ladybug `tests/unit/test_fact_order_determinism.py tests/unit/test_structural_loading.py`, log `/tmp/hippo-arrows-ladybug-green.log`.
4. Ruff check + format on changed files.

DONE WHEN: Fake and Ladybug green; Ruff clean; `horch done` lists the sort site chosen, the key, whether the golden constants changed, tests added, counts and logs. No commits.

REPORT: `horch note` after RED and after GREEN.
