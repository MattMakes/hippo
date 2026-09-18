# R3 — Retriever, edge weights, explain, changesets, simulate, ask, fidelity (worker: opus-1)

Read `00-shared-context.md` first. Output file: `docs/plans/hippo-for-code/research/R3-retrieval-analysis.md`.

Files in scope: `src/hippo/hipporag/retriever.py`, `hipporag/graph_index.py` (weight rule and PPR call only;
R1 covers schema/vertex model), `src/hippo/analysis/*.py`, `src/hippo/ask.py`, `src/hippo/hipporag/answerer.py`,
`src/hippo/prompts.py`, `docs/FIDELITY.md`, `tests/unit/test_retriever.py`, `tests/unit/test_analysis_*.py`,
`tests/unit/test_ask.py`, `tests/unit/test_web_analyze.py`.

This is judgment work: A and B make different retrieval choices and you must say which fit the code and
which break fidelity. Still: evidence first, verdicts second, no redesign.

- **R3.1** `Retriever.retrieve` end to end. Quote the order of operations: question embedding → fact scores →
  `llm_fact_filter` → seed entities → node specificity → boosts → `link_top_k` (or `linking_top_k`) → PPR →
  passage scores → DPR fallback. Give line numbers for each stage. Then state precisely WHERE B's
  `seed_nodes: dict[str, float]` (anchors added to `phrase_weights` after specificity and boosts, subject to
  `link_top_k`) and A's "symbol seeds bypass the fact filter and `linking_top_k`" would each enter, and what
  each implies for `docs/FIDELITY.md`.
- **R3.2** `Trace`. Every field and where each is filled. Which fields would `anchors` / `paths` join.
- **R3.3** Edge weight rule. Quote `Edge.weight` (or the equivalent in `graph_index.py`) and how
  `graph_with_edits` applies `TUNED`. Evaluate: B's `max(fact_count, mention, synonym_score, structural × structural_scale)`
  and A's `tuned if set else max(fact_count, 1.0 if mention, synonym_score, ω_max)`. Are these the same rule?
  Does either change behaviour for a graph with no code (must be no)?
- **R3.4** Node specificity. A changes it for code nodes to `1/(incoming INVOKES/READS/WRITES + 1)`; B keeps
  `1/passage_count` and relies on `MENTIONS`/`DEFINES` counting as mentions. Against `docs/FIDELITY.md` and
  the retriever code, state which is the smaller deviation and whether either touches the prose path.
- **R3.5** `analysis/explain.py`. `Explanation` and `PassageExplanation` fields, how `why` sentences are built,
  how the subgraph and its edge `kinds` are computed (the Analyze picture "already draws `kinds`" per B), the
  shortest-path helper (≤3 hops?). Where `anchors` and `paths` would attach.
- **R3.6** `analysis/changesets.py`. `VALID_OPS` (exact list), `validate`, `describe`, `apply`, what each op
  writes (store method names), how `add_synonym` persists today, whether `apply` bumps `graph_version`,
  and whether there is any `eval_set_id` link or refusal path (B wants a 409 on regression).
- **R3.7** `analysis/simulate.py`. The `Overrides` dataclass fields; how the LLM filter is "replayed" (from
  which stored data?); how ranks are diffed; whether a whole-set replay is feasible with what is stored
  (coordinate with the R2 finding on `evals/runner.py` if you read it; otherwise state the dependency).
- **R3.8** `ask.py`. `search` and `answer_from_trace` signatures; how passages are shaped for
  `answerer.answer_question`; where a synthetic first passage would be prepended and whether the QA prompt
  in `prompts.py` would need to change (B says no).
- **R3.9** A's LLM "select pass" (keep / drop / expand-once after retrieval, on by default behind a setting).
  Is there any post-retrieval LLM rerank today? Where would it sit in `ask.py` vs `retriever.py`? What does
  `docs/FIDELITY.md` say about post-retrieval steps? Report cost in LLM calls per question.
- **R3.10** Fidelity statements. Quote the sentences in `docs/FIDELITY.md` that constrain: PPR call, damping,
  edge weights, seeding, `link_top_k`, DPR fallback. For each of B's three claimed "additive" changes
  (structural facts as extra Fact rows; anchors as extra reset mass after seed computation; `structural` as an
  extra max term) say whether the claim "with `structural_scale = 0` and no code sources the system is the
  reference" holds given the code.
- **R3.11** Web/Analyze API. In `src/hippo/web/routes/analyze.py`: list the endpoints (simulate, changeset
  save/apply, explain) with methods and request shapes, so the synthesizer knows what `/api/paths/impact`
  and `/api/simulate/replay-set` would sit beside.

Gotchas to look for: tests in `test_retriever.py` that pin seed counts or weights (would constrain anchors),
any place `phrase_weights` keys are assumed to be OpenIE phrases, and any assumption that every Fact has a
subject and object Entity that both exist (structural facts to a `commit` or a test file may not).
