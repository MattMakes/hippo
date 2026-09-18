# Gates: RAG Task 1

OWNS: tests/fixtures/rag_all/**, tests/unit/test_rag_eval.py, src/hippo/evals/rag_all.py, src/hippo/evals/metrics.py, scripts/rag_eval.py, tests/conftest.py

- [x] G1: The cross-source fixture validates stable labels and corpus separation, hand-ranked metrics handle sufficient alternatives, and the deterministic legacy evaluation reports actual retrieval and coverage gaps.
  CHECK: .venv/bin/python -m pytest tests/unit/test_rag_eval.py -q
  EXPECT: [100%]
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=........................................................                 [100%]

- [x] G1R: The CLI produces a reproducible nonempty development baseline and rejects unimplemented modes rather than reporting empty success.
  EVIDENCE: Root ran two real CLI invocations against isolated fake stores with byte-identical development reports (7/12 evaluated, 5 capability gaps); all four unimplemented modes returned nonzero without output. Full diagnostic report: ai_docs/reports/2026-09-11-rag-legacy-dev.json. No held-out quality tuning or live quality claim.
