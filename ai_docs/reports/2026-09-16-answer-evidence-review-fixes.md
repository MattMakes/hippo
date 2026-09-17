# Answer-evidence review fixes

## Outcome

The two important review findings are corrected.

- Supplemental answer evidence is now budgeted against the deduplicated original citations and
  original text actually supplied to QA, rather than only against projected retrieval passages.
- The two migrated fixture tests now derive an explicit fixed set of fixture symbol passages and
  no longer call the production selection helper as their expected-value oracle.

The related minor findings are also addressed: a real one-seed cycle regression exercises the
walk, the 70-seed test is named for its actual visit-cap coverage, stale answer-slice docstrings
are corrected, and the directly affected README/FIDELITY behavior descriptions are aligned.

## RED evidence

Before production changes, this command exercised a tiny supplemental retrieval passage whose
lineage expanded once to 6,001 original characters and once to 11 original citations:

```text
HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_answer_context.py -q -o addopts='' -k 'skips_supplemental_groups'
```

Result: `2 failed, 7 deselected`. Both failures showed the same defect: expected only
`passage-Service.run`, but the answer also retained `passage-helper` in
`retrieval_passage_ids`.

## Implementation

`select_answer_citations` resolves the unchanged base plus bounded lexical candidates through
`resolve_citations` once. It initializes the seen-original set from the complete base bundle,
then accepts each supplemental item only as a whole when its previously unseen originals keep
both incremental limits: `min(max(code_expand_max, 0), 10)` citations and 6,000 text characters.
An oversized group is skipped without blocking later candidates. Shared originals cost zero,
base evidence is never subjected to supplemental limits, and accepted citations are rebuilt in
first accepted-item/within-item order from validated resolver output.

`ask._answer_from_trace` consumes that `CitationBundle` directly. There are no raw-store reads,
new model calls, changes to citation resolution, or changes to authorization behavior.

Coverage includes exact-bound admission, 6,001-character and 11-citation rejection, later-small
admission after an oversized group, shared-original accounting, an oversized unchanged base,
`code_expand_max=0`, exact retrieval/citation ordering, model-message inclusion/exclusion,
one-seed cycles, noncanonical edge insertion order, and the existing final-revocation path.

## Verification completed

```text
HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_answer_context.py -q -o addopts=''
```

Result: `13 passed`.

```text
HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_answer_context.py tests/unit/test_ask.py::test_the_block_rides_in_as_a_pseudo_passage_and_is_never_cited tests/unit/test_retriever.py::test_via_expand_passage_selected_as_full_text_evidence_is_cited -q -o addopts=''
```

Result: `15 passed`.

```text
HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_ask.py tests/unit/test_retriever.py tests/unit/test_answer_original_citations.py tests/unit/test_query_authorization_boundary.py tests/unit/test_query_session.py tests/unit/test_dense_session.py -q -o addopts=''
```

Result: `184 passed, 1 warning`. The warning is Starlette's existing deprecation warning for the
`anyio.abc.BlockingPortal` alias.

```text
HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_answer_context.py tests/unit/test_answer_original_citations.py -q -o addopts=''
```

Result: `24 passed, 1 warning`, the same Starlette dependency warning.

```text
.venv/bin/ruff check src/hippo/hipporag/answer_context.py src/hippo/ask.py src/hippo/hipporag/answerer.py tests/unit/test_answer_context.py tests/unit/test_ask.py tests/unit/test_retriever.py
.venv/bin/python -m compileall -q src/hippo
git diff --check
```

Result: all checks passed.

After those runs, two assertions were tightened without changing production behavior: the
skip/continue synthetic case now also pins model-message inclusion/exclusion, and the migrated
retriever test checks full prompt text for every exact expected passage. Per the orchestrator's
stop instruction, those assertion-only edits were not rerun by this worker. The parent reported
fresh final answer gates of 13 and 184 passing and no remaining test processes.

## Remaining boundary

G3 real-model answer quality and the isolated proof measurement remain parent-owned. This worker
made no model calls, corpus runs, timing claims, commits, historical-plan edits, or changes outside
the authorized answer-context, migrated-test, docstring, documentation, and report scope.
