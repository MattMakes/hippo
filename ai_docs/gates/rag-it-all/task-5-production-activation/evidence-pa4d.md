# Evidence: activation Task 4d — evaluation, analysis, changeset and eval-access owners

Branch `wp/pa4d`, worktree `.worktrees/pa4d`. Base `rag-it-all-tibs` `da51784` (see deviation 1:
the brief named `1acf069`, the orchestrator reassigned `957fc35`, and `wp/pa4d` was then
**fast-forwarded** to `da51784` for the import-cycle fix — a fast-forward, so there is no merge
commit to quote).
Python `.venv/bin/python` 3.12.11, pytest 9.1.1, Ruff 0.16.6, `mcp` pinned to 2.1.1 per the rulebook.

Commits:

| Hash | Subject |
|---|---|
| `3f36d1c` | Run the simulation over the dense route it owns |
| `267f3af` | Give every evaluation question one dispatched owner |
| `d9d3d24` | Pin the evaluation half of the production activation |
| `929862b` | Generate questions over evidence whose fingerprint holds still |
| *(this file)* | Record the evaluation slice's evidence — hash reported in the `horch done` summary, since a commit cannot name itself |

Five commits rather than the brief's two or three: the fourth is the Ladybug finding below, and the
fifth is this file, which had to follow the Ladybug run.

Files created: `tests/unit/test_managed_eval_activation.py`, this file.
Files modified: `src/hippo/analysis/simulate.py`, `src/hippo/evals/runner.py`,
`src/hippo/evals/rag_all.py`, `tests/unit/test_analysis_simulate.py`,
`tests/unit/test_analysis_changesets.py`, `tests/unit/test_rag_replay_access.py`.
Unchanged, and confirmed rather than converted: `src/hippo/knowledge/eval_access.py`,
`src/hippo/knowledge/changeset_access.py`, `src/hippo/evals/question_maker.py` (see "Audit rows").
Nothing under `src/hippo/web`, `mcp_server.py`, `cli.py`, `remote.py`, `ask.py`, `query_access.py`,
`dense_session.py`, `projection.py`, `replay.py`, `ingest/`, `store/`, `context.py`, `status.py`,
`docs/`, the shared `GATES.md` or the checkpoint was touched.

## What the slice does

1. **`analysis/simulate.py`** reaches its graph through `ask._dispatch`, the same three-branch rule
   `ask.search` uses: own the session through `retrieval_session`, wrap a borrowed structural one in
   place, or pass an already dispatched one straight through. The retriever below never sees an
   unactivated structural graph, and a caller that already paid for a profile does not pay again.
2. **`evals/runner.py`**: `run_question` dispatches once through the same helper and hands the
   dispatched session to `search`, `answer_from_trace` and the judge, so one question is one
   acquisition, one activation and one release. `_run_all` still acquires the structural owner per
   question — that is what `save_evaluation_result` retains the result's snapshots against, and
   keeping the dispatch inside `run_question` keeps an unroutable corpus a per-question error
   instead of the end of the run (decision 4).
3. **`evals/rag_all.py`**: the static evaluator owns `retrieval_session` for its per-question view,
   so the candidate rows it reports are read from the same activated graph that ranked them.
4. **`EvalAccess`, `ChangesetAccess`, question-maker passage reads** are graph-only owners that were
   already structural once Task 4a flipped the `query_session`/`query_access` defaults. They are
   confirmed by test, not rewritten: `test_managed_eval_activation.py` loads a generation built under
   a *foreign* embedding tag through each of them — the corpus the explicit legacy lane refuses —
   and reads DTOs with the model replaced by an object that fails on any attribute access.
5. `ChangesetAccess` mutations keep their acquire-before-transaction / close-after shape, now pinned
   by a recorded event order (`acquire`, …, `transaction`, …, `close`) rather than by inspection.

## Commands and results

All runs used the standard invocation with the log captured, never piped to `tail`.

| # | Command | Result | Log |
|---|---|---|---|
| 0 | Baseline on clean `da51784`: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_analysis_simulate.py tests/unit/test_analysis_snapshot_lifetime.py tests/unit/test_analysis_changesets.py tests/unit/test_evals_runner.py tests/unit/test_eval_access.py tests/unit/test_evals_question_maker.py tests/unit/test_rag_replay_access.py tests/unit/test_rag_eval.py tests/unit/test_rag_eval_session.py tests/unit/test_eval_access_lifetime.py tests/unit/test_eval_snapshot_lifetime.py -q -o addopts='' -p no:cacheprovider -W error` | **22 failed, 187 passed** — exactly the 4d rows of the pa4a breakage table and nothing else | `/tmp/hippo-pa4d-baseline.log` |
| 0b | Baseline attempt at `957fc35`, before the import-cycle fix | 7 collection errors (`ImportError: cannot import name 'MANIFEST_EXTERNAL_ID' …`), reported and fixed by the orchestrator at `da51784` | `/tmp/hippo-pa4d-baseline.log` (overwritten by run 0; the failure is quoted in deviation 2) |
| 1 | RED: the final `test_managed_eval_activation.py` against the three source files restored to `da51784` (`git restore --source=da51784 -- src/hippo/analysis/simulate.py src/hippo/evals/runner.py src/hippo/evals/rag_all.py`), then `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_eval_activation.py -q -o addopts='' -p no:cacheprovider -W error`, then `git restore` back | **10 failed, 7 passed.** Six simulation cases fail with `DenseUnavailable: This structural graph is unavailable for dense retrieval`; the four runner/routing cases fail on the dispatch count (`['tag_compatible', 'tag_compatible'] != ['tag_compatible']`), i.e. search and answer each dispatching their own. The 7 that already pass are the four confirmations (three graph-only owners, one borrowed-and-already-dispatched session) and the three failure paths this slice preserves rather than changes: mixed-profile containment, revocation during a question, and the empty corpus (whose re-wrapped `legacy` dispatches are asserted as a set, decision 6). | `/tmp/hippo-pa4d-red.log` |
| 1b | RED for the AnyIO marker: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_rag_replay_access.py -q -o addopts='' -p no:cacheprovider -W error` (the file alone, so no earlier module has imported the transport) | 4 failed, 6 passed — `DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated` | `/tmp/hippo-pa4d-anyio-red.log` |
| 2 | GREEN Fake, owned + adjacent: run 0's files plus `test_managed_eval_activation.py`, `test_evals_code.py`, `test_evals_judge.py`, `test_evals_metrics.py`, `test_store_evals.py`, `test_managed_route_activation.py`, `test_query_snapshots.py`, same flags | **308 passed**, exit 0, 22.43s | `/tmp/hippo-pa4d-fake-green.log` |
| 3 | The new file alone after `ruff format`: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_eval_activation.py …` | 17 passed | — |
| 4 | Collateral not owned by this slice: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_web_analyze.py -q -o addopts='' -p no:cacheprovider -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"` | **9 passed** — the four Group A rows in that file are green without `web/routes/analyze.py` being touched (deviation 6) | `/tmp/hippo-pa4d-web-analyze.log` |
| 5 | GREEN Ladybug: `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_managed_eval_activation.py tests/unit/test_analysis_snapshot_lifetime.py tests/unit/test_eval_access.py -q -o addopts='' -p no:cacheprovider -W error` | **62 passed** in 287.99s, exit 0 | `/tmp/hippo-pa4d-ladybug-green.log` |
| 5a | The same three files, first attempt, before the question-maker test moved to a fact-free corpus | 1 failed, 61 passed — `EvalAccessDenied: Question generation requires its verified source and input view`, the symptom of the ordering defect in "Open finding" | superseded by run 5 |
| 5b | Throwaway probe for that finding, run on both backends and then deleted (`tests/unit/test_pa4d_probe.py`) | Fake: fingerprints stable. Ladybug: two loads of one unchanged corpus differ, component comparison `['facts', 'fact_vectors']`; a fact-free managed corpus is stable on both | — |
| 6 | `.venv/bin/ruff check src/hippo <the four test files> && .venv/bin/ruff format --check src/hippo <the four test files>` | All checks passed; 124 files already formatted | — |

AnyIO warning handling: **form (a)**, the exact per-test marker, on the three tests in
`tests/unit/test_rag_replay_access.py` that import `fastapi.testclient` inside the function body
(`:136`, `:165`, `:192`). No file this slice owns imports a transport at module level, so every run
above except the one over `test_web_analyze.py` (not ours) passed under a bare `-W error`. No
ini-wide `filterwarnings` exists.

## Audit rows

Row ids are `file:line` as recorded in `session-audit.md` (produced at `043ca51`).

| Audit row | Class | Disposition |
|---|---|---|
| `src/hippo/analysis/simulate.py:149` `simulate` | model/dense | **Converted.** `ask._dispatch(ctx, access, session, None)`. |
| `src/hippo/evals/runner.py:141` `run_question` | model/dense | **Converted.** Same helper; the dispatched session is what `search`, `answer_from_trace` and `_grade` receive. |
| `src/hippo/evals/runner.py:95` `_run_all` | model/dense in the audit | **Reclassified, not converted: it is the graph-only holder of the owner the model layer dispatches.** It still acquires one structural `query_session` per question — what `save_evaluation_result` retains that result's snapshots against — and `run_question` (`:141`) wraps that same session in place, which is the plan's second option for a model owner ("wrap its one borrowed structural `QuerySession`"). No graph is reacquired anywhere in the chain. Rationale in decision 4. |
| `src/hippo/evals/rag_all.py:386` `evaluate` | model/dense | **Converted.** `retrieval_session(ctx, Access(...), settings={"retrieval_top_k": 20})`. |
| `src/hippo/knowledge/eval_access.py:97` `read_scope` | graph-only | **Confirmed structural, no code change.** `query_session` defaults to structural since 4a; pinned by `test_eval_access_reads_hold_a_structural_session_with_the_model_offline`. |
| `src/hippo/knowledge/eval_access.py:123` `_creation_scope` | graph-only | **Confirmed structural, no code change.** `query_access` default; the acquire-outside-transaction shape is unchanged. |
| `src/hippo/evals/question_maker.py:94` `generate_questions` | graph-only | **Confirmed structural, no code change.** Pinned by `test_question_generation_reads_originals_without_a_dense_dispatch`: one acquisition, zero dispatches, and the prompt carries the graph's own resolved original citation text. |
| `src/hippo/knowledge/changeset_access.py:49` `read_scope` | graph-only (audit says 4b) | **Confirmed structural, no code change.** Assigned to this slice by the brief; see decision 10. |
| `src/hippo/knowledge/changeset_access.py:70` `_mutation_scope` | graph-only (audit says 4b) | **Confirmed structural, no code change.** The recorded event order proves acquire-before-transaction and close-after. |
| `src/hippo/knowledge/changeset_access.py:170` `apply` | unrestricted legacy read (audit says 4b) | **Confirmed as the audit describes.** `set(self.ctx.graph().node_ids)` stays a raw unrestricted read inside `_mutation_scope`; it is used only to refuse managed evidence identities as legacy edit targets and never reaches a response body — `apply`'s returned dict carries the changeset's own ops, counts and descriptions rebuilt under the postcommit read scope. |

## Breakage rows fixed

Every row below comes from `evidence-pa4a.md`, "Breakage for 4b/4c/4d". All are green in run 2.

| Group | File | Rows | How |
|---|---|---|---|
| A | `tests/unit/test_analysis_simulate.py` | 13 | The `simulate.py` conversion. One of them, `test_a_structural_scale_override_is_passed_to_the_graph_the_search_runs_on`, also needed its recorder moved from the instance `ctx.graph_for(None)` returned to `GraphIndex` itself, because the simulation builds its own view (decision 9). |
| A | `tests/unit/test_analysis_snapshot_lifetime.py` | 6 | The same conversion, including `test_analysis_routes_use_one_graph_through_dto_and_render[simulate]`, whose table row named `analyze.py:270` as a second owner. It is green with `analyze.py` untouched: the route borrows its structural session to `simulate`, which dispatches it in place, so the route still acquires exactly one graph. |
| A | `tests/unit/test_rag_replay_access.py` | 1 (`test_simulation_diff_does_not_reveal_old_hidden_titles`) | The same conversion. |
| B | `tests/unit/test_analysis_snapshot_lifetime.py` | 1 (`test_deleted_saved_result_is_withheld_during_analysis[dto]`) | Falls out of the Group A fix, as the table predicted. |
| D | `tests/unit/test_analysis_changesets.py` | 1 (`test_overrides_to_ops_are_valid_and_apply_reaches_the_graph`) | Compares two traces (`after.graph_version != before.graph_version`) instead of the store counter. The store-counter assertions earlier in the same test are about the store and still hold unchanged. |
| — | `tests/unit/test_rag_replay_access.py` | 3 tests | The per-test AnyIO marker the Task 2 review asked for (form (a)). |

Not this slice's rows, reported for their owners: the four Group A rows in
`tests/unit/test_web_analyze.py` (4b) are **also green now** (run 4), for the reason given in the
Group A row above. 4b still owns `analyze_adhoc` and `analyze_result`, which are dense owners in
their own right; this changes only the `simulate` route's symptom.

## Deviations and decisions

1. **Base.** The brief says `1acf069`; the orchestrator's task line reassigned `957fc35`; after the
   import cycle in deviation 2 the orchestrator authorized one `git merge rag-it-all-tibs`, which
   resolved as a **fast-forward to `da51784`**. There is therefore no merge commit — `wp/pa4d`'s
   first own commit is `3f36d1c`, whose parent is `da51784`.
2. **A branch-wide import cycle was found here and fixed by the orchestrator.** At `957fc35`,
   `python -c "import hippo.ask"` failed with
   `ImportError: cannot import name 'MANIFEST_EXTERNAL_ID' from partially initialized module
   hippo.knowledge.generation_profiles`: `ask.py` → `knowledge/dense_session.py` →
   `knowledge/generation_profiles.py:14` → `hippo/ingest/__init__.py` → `pipeline.py` →
   `managed_activation.py` → `ingest/prose_generation.py:25` → back into the half-initialized module.
   The cycle predates Task 4 (`d4a916f`, `c3333ca`); pa4a's merge made it *reachable* by adding the
   `dense_session` import to `ask.py`, and a full-suite run masks it because an alphabetically
   earlier test module imports `hippo.ingest` first. Seven of this slice's eleven files could not be
   collected. Fixed at `da51784` (lazy managed-lane accessor in `pipeline.py`, plus
   `tests/unit/test_import_order.py`). No file of this slice's was changed for it.
3. **`tests/unit/test_rag_all*.py` does not exist.** `ls` gives no such file; the RAG-all evaluator's
   tests are `tests/unit/test_rag_eval.py` and `tests/unit/test_rag_eval_session.py`, and no other
   brief claims them. Both are in run 0 and run 2 and pass unchanged.
4. **`_run_all` keeps `query_session` and `run_question` owns the dispatch.** Dispatching in
   `_run_all` would move an unroutable corpus (mixed verified/tag-compatible evidence, say) *outside*
   `run_question`'s handler, so the first question would mark the whole run `failed` and re-raise,
   contradicting the runner's documented contract that one broken question is recorded and the run
   carries on (`test_evals_runner.py::test_one_broken_question_does_not_kill_the_run`). The chosen
   shape is the plan's own second option for a model owner, costs no extra acquisition, and is pinned
   by `test_a_mixed_profile_corpus_fails_its_questions_without_ending_the_run`: the run reaches
   `done` with `summary["errors"] == 1`, the stored row carries the dispatcher's constant message,
   and the metadata server records no call at all.
5. **This slice imports `ask._dispatch`, a private helper.** `simulate.py` already imported
   `ask._answer_from_trace`, and the alternative was copying the three-branch rule (own / wrap /
   pass through) into three modules, where it would drift. The coupling is deliberate and worth
   promoting to a public name in `ask.py` when whoever owns that file next touches it; it is not this
   slice's file to change. A convenient side effect: `test_managed_route_activation.watch()` patches
   `ask.retrieval_session`, so the same recorder observes analysis and evaluation dispatches.
6. **Empty corpora dispatch more than once, by design.** `retrieval_session` over an empty view
   yields `dense_capability.mode == "legacy"`, which `ask._dispatch` re-wraps rather than passes
   through — the documented no-op that makes no model call. The empty-corpus tests therefore assert
   the dispatch *set* (`{"legacy"}`) plus one acquisition and an `Offline` model, not a count.
7. **The runner stores raw exception text privately, and this slice did not widen that.**
   `result["error"] = f"{type(exc).__name__}: {exc}"` and `update_run(error=str(exc))` are
   pre-existing; `EvalAccess.get_result`/`get_run` null both on every public read, which is what PA6's
   "no arbitrary exception strings" applies to. The failures this slice adds to that field are
   `DenseSessionUnavailable`'s own constant sentences, which carry no input, path or model body.
8. **`compare_with_baseline` keeps its nested owners.** Its outer `EvalAccess.read_scope()` is
   graph-only, and each `run_question` acquires its own dispatched owner because
   `BASELINE_SETTINGS` differ from the outer session's captured settings — borrowing it would fail
   the settings check that exists precisely to stop that.
9. **Two owned assertions changed meaning with the behaviour and were adapted, not re-pinned.**
   (a) the scale-override recorder moved from the instance to `GraphIndex`, because the simulation
   builds its own structural view and an instance patch would not be on the graph the search runs on;
   (b) the applied-changeset assertion compares two traces, as `test_ask.py` now does.
10. **`changeset_access.py` is tagged `4b web` in the audit but assigned to this slice by the brief**
    (file list and the Group D row). Nothing in it changed, so the two readings do not conflict; 4b
    should treat its three rows as confirmed rather than open.
11. **No public surface can name an evaluation run's retrieval failure — an open item for 4b.**
    With the containment in decision 4, a run over an unroutable corpus finishes `done` with
    `summary["errors"] == N`, and `EvalAccess.get_run`/`get_result` null `error` on every public
    read (correctly: it may hold arbitrary exception text). So requirement 3's
    `retrieval_rebuild_required` is satisfied at the exception level for the runner, but a reader on
    the Evals page sees a count and no reason. If a public reason is wanted, the runner would have
    to store `public_failure(exc).code` in its own closed field beside `error`; that is a change to
    the eval presentation contract and to `web/routes/evals.py`, which this slice does not own.
12. **The question-generation test uses a managed corpus, not the legacy sample.** A `generated`
    question set re-proves its stored evidence fingerprint on every read, and that fingerprint is
    unstable on Ladybug for any corpus with facts — see "Open finding" above. The test therefore
    generates over a published managed source, which is fact-free and stable on both backends, and
    the finding is recorded rather than worked around silently.
13. **`EvalAccess`/`ChangesetAccess`/`question_maker` were not given a redundant explicit
    `structural=True`.** The audit's own note on `status.py:242` sets the precedent: after 4a the
    keyword is redundant, and adding it would suggest the default cannot be relied on. The behaviour
    is pinned by test instead.

## Open finding: LadybugDB returns extracted facts in an arbitrary order

Found while running this slice's Ladybug gate; **pre-existing, not caused by anything here**, and in
files this slice does not own. Two consecutive loads of the same unchanged corpus produce two
different `view_fingerprint` values on `HIPPO_TEST_STORE=ladybug`, because `graph.facts` comes back
in a different order each time (`fingerprint_vectors`' `fact_vectors` moves with it). The payload's
other components — node ids, kinds, entity names, passages, code nodes, boosts, specificity, edges —
are stable.

Reproducer (throwaway file, not committed):

```python
def test_legacy_only_fingerprint_is_stable(ctx, sample_text):
    legacy_sample(ctx, sample_text)  # the samples/acme_robotics.md corpus
    prints = []
    for _ in range(2):
        with query_session(ctx, EVERYTHING) as session:
            prints.append(view_fingerprint(session.graph))
    assert len(set(prints)) == 1
```

`HIPPO_TEST_STORE=fake` passes; `HIPPO_TEST_STORE=ladybug` fails, and a component-by-component
comparison reports `['facts', 'fact_vectors']`. A corpus with no extracted facts (a published
managed generation, say) is stable on both backends, which is how this slice's question-generation
test stays green on Ladybug.

What it breaks today, all on the primary acceptance backend:

* `EvalAccess._authorized` re-proves a `generated` set's stored `evidence_fingerprint` against a
  fresh view, so **question generation and every generated-set read deny on Ladybug** as soon as the
  corpus has facts (`EvalAccessDenied: Question generation requires its verified source and input
  view`). That is what the first Ladybug run of this slice hit.
* `can_reuse_answer` compares the same value, so a saved evaluation answer or ad-hoc analysis reloads
  as withheld/reconstructed on Ladybug even when nothing changed.

The fix belongs wherever facts are loaded into `GraphIndex` (a deterministic order — sorting by fact
id would do), i.e. `store/` or `hipporag/graph_index.py`, neither of which this slice owns. Raised
with the orchestrator rather than fixed here. PA7 should treat it as a blocking parity item: it is
invisible to the Fake backend.

## Ladybug result

`HIPPO_TEST_STORE=ladybug` over `test_managed_eval_activation.py`,
`test_analysis_snapshot_lifetime.py` and `test_eval_access.py` with a bare `-W error`:
**62 passed** in 287.99s, exit 0 (`/tmp/hippo-pa4d-ladybug-green.log`). None of the three imports a
transport at module level, so no AnyIO ignore was needed. The six snapshot-lifetime tests that the
Group A breakage covered hold their single generation through answer and release it on Ladybug as
well as on Fake, and the exact acquisition/heartbeat/dispatch counts in the new file are the same on
both backends — so nothing in this slice's dispatch or ownership is Fake-only.

The first attempt at this run (run 5a) failed one test and is what surfaced the fact-ordering
defect; the file was adjusted to a fact-free corpus (commit `929862b`) and the defect written up
rather than worked around silently.
