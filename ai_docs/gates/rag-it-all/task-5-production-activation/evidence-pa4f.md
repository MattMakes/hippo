# Evidence: activation Task 4f — evaluation wrap-up (public failure reason, dispatch promotion, bounded logging)

Branch `wp/pa4f`, worktree `.worktrees/pa4f`. Base `rag-it-all-tibs` `b2fa6f0` (the HEAD named in
the spawn message, not the `26f9a55` in the rulebook). One authorized merge of `rag-it-all-tibs`
at `feed275`, taken mid-slice on the orchestrator's instruction once `public_failure_for_code`
landed (see decision 1(iv) and deviation 1).
Python `.venv/bin/python` 3.12.11, pytest 9.1.1, Ruff 0.16.6, `mcp` pinned to 2.1.1 per the rulebook.

Commits:

| Hash | Subject |
|---|---|
| `59796b7` | Promote the dense dispatch rule out of ask into retrieval_session |
| `f23970d` | Bound the per-question log line and restore a fact-bearing generator corpus |
| `feed275` | Merge branch 'rag-it-all-tibs' into wp/pa4f |
| `221acf2` | Give an evaluation failure a public reason a reader can see |
| *(this file)* | Record the wrap-up's evidence — hash reported in the `horch done` summary |

Files created: this file.
Files modified: `src/hippo/knowledge/dense_session.py`, `src/hippo/ask.py`,
`src/hippo/analysis/simulate.py`, `src/hippo/evals/runner.py`, `src/hippo/evals/question_maker.py`,
`src/hippo/knowledge/eval_access.py`, `src/hippo/web/routes/evals.py`,
`src/hippo/web/templates/partials/run_body.html`, `src/hippo/web/templates/eval_set.html`,
`tests/unit/test_managed_route_activation.py`, `tests/unit/test_managed_eval_activation.py`,
`tests/unit/test_evals_runner.py`, `tests/unit/test_eval_access.py`,
`tests/unit/test_web_library_evals.py`, `tests/unit/test_answer_original_citations.py` (one line),
`tests/unit/test_managed_web_surfaces.py` (one comment), `tests/unit/test_web_busy_pages.py` (one
assertion, see run 3).

Not touched: `src/hippo/knowledge/public_errors.py` and `tests/unit/test_public_errors.py`
(orchestrator assigned them to opus-12 — see deviation 1), `src/hippo/web/routes/analyze.py`
(the audit it was listed for produced no change — see decision 2(d)).

---

## Decision 1 — a public failure reason on three readers

**The gap.** `errors` was in `summarize`'s output but not in `SUMMARY_CARDS`, so the run page never
rendered it. `run_body.html:42`'s per-question error pill tested `res.error`, which
`eval_access.get_result` had already nulled, so it was dead on every read. `eval_set.html:18`'s
"Generating questions failed" callout was dead the same way through `get_question_set`. A run whose
every question failed to route rendered identically to a run of unanswerable questions.

**(i) The writers store the closed code in front of the private string.**
`runner.run_question` and `runner._run_all` store `f"{code}: {type(exc).__name__}: {exc}"`, where
`code` is `(public_failure(exc) or OPERATION_FAILED).code`; `question_maker` does the same for a
failed question set. This is the shape `managed_activation.record_build_failure:415` already stores
on a Source row, and it is a *deliberate substitute* for the brief's "closed field beside the
private `error`": `store.add_result`, `update_run` and `update_question_set` write fixed property
lists, and `store/*` is on this brief's do-NOT-touch list, so a separate stored column was not
available. The orchestrator confirmed this reading (Q3).

**(ii) `EvalAccess` reads only the code back out.** `failure_code_of` (new, in `eval_access.py`, pure)
splits the first segment and returns it **only** when it is one of the codes `public_failure` can
return, derived from the `PublicFailure` constants rather than from the code table opus-12 owns. A
row written before this convention holds `f"{type(exc).__name__}: {exc}"`, so the naive split would
have published an exception class name — or whatever else a caller once put there. Such a row is
still presenting a failure, so it takes the documented `operation_failed` fallback instead of
falling silent. The three readers (`get_question_set`, `get_result`, `get_run`) set
`result["failure_code"]` and leave the `error` nulling exactly as it was.

**(iii) `errors` joins the cards and the templates render the code's own sentence.**
`web/routes/evals.py` puts `("errors", "Errors", …)` first in `SUMMARY_CARDS`, adds `'errors'` to
`run_body.html`'s integer-formatting tuple (the other cards run through `fmt(2)`, which would have
rendered a count as `3.00`), and passes a `public_reason` resolver into the three render calls that
need it. `public_reason` is `(public_failure_for_code(code) or OPERATION_FAILED).message` and reads
**the message only** — `invalid_source` covers both 400 and 413, so a stored code can never be
turned back into an HTTP status (opus-12's note). The resolver is passed in context rather than
registered as a Jinja filter because `web/render.py` is Task 4e's.

**(iv) Dependency on opus-12.** Until `public_failure_for_code` was closed over the query-lane codes,
`public_failure_for_code("retrieval_rebuild_required")` was `None` and every eval failure would have
rendered the generic `operation_failed` sentence. The orchestrator refused this slice ownership of
`public_errors.py` (Q1) and authorized one merge once it landed; `feed275` carries it, and the web
test below asserts the literal REBUILD_REQUIRED sentence.

**Two findings of my own, fixed here because fixing their neighbours would otherwise have been
cosmetic:**

* `summarize` runs **twice** over the same run — once in `_run_all` over the rows `run_question`
  returned (whole string present) and once inside `EvalAccess.get_run` over DTOs whose `error` is
  already nulled. Counting `r.get("error")` meant the DTO summary reported `errors == 0` for a run
  that had just failed every question. `runner._failure_code` reads either shape.
* A question that failed **before it retrieved** saved no trace, so `get_result` reported
  `answer_withheld=True`; `get_run` blanks the whole summary when any result withholds its answer,
  which took the error count with it. `get_result` now treats a failure with no stored trace as
  withholding nothing — a failure that happened later *does* have a saved trace and is withheld like
  any other. This is a semantic narrowing of `answer_withheld` gated on `failure_code`, so nothing
  else changes.

**Tests.** `test_web_library_evals.py::test_a_run_that_could_not_route_shows_a_count_and_a_public_reason`
is the brief's required case: a run whose question raises `EmbeddingProfileMismatch(POISON)` shows
`errors == 1`, the sentence `Rebuild compatible sources before retrieval` on the page and the
partial, `failure_code == "retrieval_rebuild_required"` over JSON, and neither the secret, the
question text nor the exception class anywhere in the response.
`::test_a_question_set_that_failed_to_generate_shows_a_public_reason` covers `eval_set.html`.
`test_eval_access.py` adds five cases: the pass-through, a result that did not fail, the eight-way
parametrized prefix table (class name, embedded secret, no colon, empty, blank, `None`, code-only,
code-and-text), the question-set and run readers, and the withheld-summary finding.
`test_evals_runner.py` adds the stored-prefix case and a pure `summarize` case over both shapes.
One honest caveat about RED order: `test_a_run_of_routing_failures_still_reports_its_summary` was
written *after* the `answer_withheld` narrowing, so that assertion was never watched to fail. The
behaviour was found and driven by the web test, which was RED on exactly that path
(`'Errors' not in …`, because `get_run` had blanked the summary); the `eval_access` test pins it at
the layer it belongs to rather than proving it.
RED logs: `/tmp/hippo-pa4f-red-d1.log` (`KeyError: 'failure_code'`),
`/tmp/hippo-pa4f-red-d1b.log`, `/tmp/hippo-pa4f-red-d1c.log` (`'Errors' not in …`,
`'Retrieval service is unavailable' not in …`).

## Decision 2 — the dispatch rule promoted into `retrieval_session`

**Promoted signature (unchanged from before — the rule moved, the signature did not):**

```python
@contextmanager
def retrieval_session(ctx, access=None, *, settings=None, resolved_profile=None,
                      spec=None, cache=None, session=None) -> Iterator[QuerySession]
```

The three-branch rule now lives inside it: no `session` → acquire and route; a `session` not routed
yet → route it in place; a `session` already routed (`dense_capability.mode` in
`{"verified", "tag_compatible"}`) → yield it unchanged. `ask._dispatch` is deleted and `_DISPATCHED`
moved to `dense_session.py`.

**The two questions the 4d review said the promotion had to answer explicitly:**

* **`access` and `session` together: raise.** The pass-through branch is placed *after* the two
  borrow checks in `_session`, so a pass-through is a borrow and is checked like one. `_dispatch`
  skipped both.
* **The settings comparison still runs on a pass-through**, for the same reason.

**Audit of the three call sites the brief named.** All three pass `access` *and* `session` today,
and all three must keep tolerating it: `ask.search`/`ask.ask` are called with both from `cli.py`,
`mcp_server.py`, `web/routes/api.py` and `web/routes/pages.py` (all do-NOT-touch), `simulate` with
both from `tests/unit/test_analysis_snapshot_lifetime.py:69`, and `run_question` with both from
`tests/unit/test_eval_snapshot_lifetime.py:117` — the last two unowned files. So the public
signatures stay as they are and each caller resolves "the borrowed session's audience wins" in one
documented line, `None if session is not None else access`. `runner.run_question` still needs
`access` for `EvalAccess` regardless. **(d)** `web/routes/analyze.py:340` therefore needs no change:
`simulate` resolves it, and removing `access=` at one of three equivalent call sites would imply the
other two were wrong.

**Recorder consequence, and why `watch()` moved.** `test_managed_route_activation.watch` (shared by
`test_managed_eval_activation.py` and the unowned `test_managed_transport_activation.py`) patched
`ask_module.retrieval_session`, and it only ever saw `simulate` and `runner` because `_dispatch`
looked the name up in `ask`'s globals at call time. Importing the name directly into those modules
would have made ~11 `record.dispatched` rows read `[]`. Two changes, confirmed by the orchestrator
(Q5): `ask`, `simulate` and `runner` call `dense_session.retrieval_session` through the **module
object** at call time, so one patch point covers every promoted caller (and decision 5 becomes the
same one-line change); and `watch()` now patches `hippo.knowledge.dense_session.retrieval_session`
and **skips a yielded session identical to the borrowed one**, because a pass-through is not a
dispatch. Without that skip, the runner rows would have read three entries where
`test_managed_eval_activation.py:255` asserts exactly one ("search, answer and grading share the
runner's one dispatched owner"). **Every `record.dispatched` assertion in the tree kept its value
and its meaning; none was weakened.** `test_managed_web_surfaces.watch` patches route modules by
name and is unaffected (its now-stale comment about `ask._dispatch` was corrected).

**Tests.** `test_managed_route_activation.py::test_the_dispatch_rule_is_public_and_owns_every_borrow_decision`
(pass-through identity, no second `/api/show`, `invalid_borrow` for an audience alongside a borrow,
`invalid_borrow` for settings the held session never captured) and
`::test_no_module_reaches_dense_dispatch_through_a_private_helper`.
`tests/unit/test_answer_original_citations.py:115` retargets its monkeypatch (one line, authorized).
RED log: `/tmp/hippo-pa4f-red-d2.log`.

## Decision 3 — the per-question log line is bounded

`runner.py`'s `log.exception("Question %r failed", text)` emitted the question and the whole
exception, `str(exc)` included, at ERROR level. It is now
`log.warning("Evaluation question failed: question=%s code=%s exception=%s", identity, code, type(exc).__name__)`
with **no** `exc_info` — the traceback footer is itself `str(exc)`, and the brief's rule ("never the
question text or exception text") outranks the 4d review's nit, which had suggested keeping
`log.exception`. The question's id is captured before the `try`, because the row is re-read inside it
and a denial leaves that name holding `None`. Shape copied from
`managed_activation.record_build_failure:407-413`.

Test: `test_evals_runner.py::test_a_failing_question_logs_its_id_and_code_but_neither_its_text_nor_the_exception`
asserts the id and the code are present, the question text and a poison string are absent, and no
record carries `exc_info`. RED log: `/tmp/hippo-pa4f-red-d3.log` (the old line printed both).

## Decision 4 — a fact-bearing corpus for the question maker

`test_question_generation_reads_originals_without_a_dense_dispatch` ran over
`managed(ctx, "managed notes")`: one passage, no facts, so `shared_entity_pairs` returned nothing and
the multi-hop generator — the one that reads the *entity graph* and resolves citations through the
second call site at `question_maker.py:236` — never ran. The corpus is now the staged prose writer
over a three-section text, which is the only fixture in the tree that produces real managed evidence
spans **and** extracted facts: 3 passages, 1 fact, 3 shared-entity pairs, and 6 two-passage prompts
(3 pairs × both orders) beside the 3 single-passage ones. The test asserts the pairs exist and that a
prompt carries two passages' own original citation text, so `record.dispatched == []` and
originals-in-prompt now cover both generators. Canonical fact order (`e709aad`, confirmed an ancestor
of this base) is what makes the fact-bearing corpus usable: a generated set re-proves its stored
evidence fingerprint on every read.

**Deviation (flagged).** The brief asked for the multihop **and** code **and** commit paths in this
case. Code and commit questions are **not reachable over a managed corpus**: their fixture
(`tests/fakes/code_fixture.write_commit_history`) writes passages natively and a managed source
rejects that with `ValueError: Managed native writes require generation context`. They therefore get
their own case, `test_code_and_commit_question_generation_dispatches_nothing_either`, over the legacy
`code_index` tree plus the two-symbol commit arrangement `test_evals_code.code_history` makes (built
inline rather than importing a fixture, which Ruff flags as F811). It asserts
`{"code", "commit"} <= kinds` and `record.dispatched == []`, which is the assertion finding 4 said
was missing. The fake model accepts no multi-hop *question* from this corpus (1 single question out
of 9 prompts), so the multi-hop claim is made about the generator running and resolving citations,
not about a row it produced.

RED log: `/tmp/hippo-pa4f-red-d4.log` — the new assertion fails on the old fact-free corpus with
"the corpus must bear facts, or the multi-hop generator never runs".

## Decision 5 — `rag_all.py` late binding: HANDED OFF to opus-10

**NOT DONE, and not this slice's to do.** The spawn message ordered it last, after a "fixture loader
merged" signal that never came: opus-10 still owns `rag_all.py` and has not merged. The orchestrator
answered "hand decision 5 off … I am giving it that one-liner plus the dispatch-mode test as an
addendum" and "do not merge again", so it is recorded here for that addendum rather than attempted.

**The exact change, for whoever picks it up.** `src/hippo/evals/rag_all.py:24` currently does
`from ..knowledge.dense_session import retrieval_session`, which binds the name at import. Replace it
with `from ..knowledge import dense_session` and call `dense_session.retrieval_session(...)` at
`~:388`. That is the convention `ask.py`, `analysis/simulate.py` and `evals/runner.py` now follow, and
it is what makes the fourth model/dense owner observable: `watch()` in
`tests/unit/test_managed_route_activation.py` patches
`hippo.knowledge.dense_session.retrieval_session`, so after the one-liner the static evaluator's
dispatch shows up in `record.dispatched` with no second patch point, and the dispatch-mode test the
4d review's finding 5 said was missing can finally be written against it.

`rag_all.py:388` already **owns** its session (it passes `access`, never a `session`), so it needs no
other change: the promoted rule's borrow branches do not apply to it, and nothing about its behaviour
moves. The one-liner is purely about observability.

---

## Runs

All commands from `/Users/mascott/projects/hippo/.worktrees/pa4f`, `HIPPO_TEST_STORE` explicit on
every one, output captured to a log and never piped to `tail`.

| # | Command | Result | Log |
|---|---|---|---|
| 0 | Fake baseline at `b2fa6f0`, clean tree, the 11 files this slice would touch | **4 failed, 272 passed** — the four are `test_query_session.py::test_model_failure_releases_graph_and_revocation_wins[{True,False}-mcp_{ask,search}]`, the post-4c MCP rows `task4-notes.md:15` assigns to 4b-i. Pre-existing by construction (clean tree at the base). The merge at `feed275` brought 4b-i's fix and they now pass. | `/tmp/hippo-pa4f-baseline-fake.log` |
| 1 | Fake, 21 files: this slice's own plus the brief's `test_managed_web_surfaces.py test_analysis_simulate.py test_query_session.py`, plus `test_managed_transport_activation.py test_eval_snapshot_lifetime.py test_analysis_snapshot_lifetime.py test_dense_session.py test_import_order.py` (added by me: the first shares `watch()`, the next three call the promoted rule with both `access` and `session`, and the last is the gate for `eval_access` importing `public_errors`) | **EXIT 0 — 479 passed** | `/tmp/hippo-pa4f-green-fake.log` |
| 2 | Ladybug, the brief's two files: `test_managed_eval_activation.py test_eval_access.py` | **EXIT 0 — 62 passed in 531.61s**, and re-run at the final HEAD after run 3's fix: **EXIT 0 — 62 passed in 588.64s** | `/tmp/hippo-pa4f-green-ladybug.log`, `/tmp/hippo-pa4f-green-ladybug2.log` |
| 3 | Fake, added by me: **every** `tests/unit` file mentioning `retrieval_session`, `dense_session`, `hippo.ask`, `evals` or `simulate` — 47 files, because decision 2 changes two modules the whole suite reaches through | **EXIT 0 — 1195 passed, 2 skipped** (first attempt found one regression outside both of the brief's lists; see below) | `/tmp/hippo-pa4f-sweep-fake.log` |
| 4 | Ruff `check` + `format --check` on every file this slice changed | **EXIT 0** — all checks passed, all formatted | inline |

Command 1 verbatim:

```
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_eval_activation.py \
  tests/unit/test_evals_runner.py tests/unit/test_eval_access.py \
  tests/unit/test_web_library_evals.py tests/unit/test_ask.py \
  tests/unit/test_managed_route_activation.py tests/unit/test_rag_eval.py \
  tests/unit/test_managed_web_surfaces.py tests/unit/test_analysis_simulate.py \
  tests/unit/test_query_session.py tests/unit/test_evals_question_maker.py \
  tests/unit/test_evals_code.py tests/unit/test_eval_snapshot_lifetime.py \
  tests/unit/test_eval_access_lifetime.py tests/unit/test_web_analyze.py \
  tests/unit/test_managed_transport_activation.py \
  tests/unit/test_answer_original_citations.py tests/unit/test_import_order.py \
  tests/unit/test_rag_eval_session.py tests/unit/test_analysis_snapshot_lifetime.py \
  tests/unit/test_dense_session.py -q -o addopts='' -W error \
  -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"
```

Command 2 verbatim:

```
HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_managed_eval_activation.py \
  tests/unit/test_eval_access.py -q -o addopts='' -W error
```

Both new Ladybug-relevant cases pass there: the fact-bearing managed corpus (decision 4) and the
eight prefix rows of `failure_code_of` (decision 1). No Neo4j was used; `ladybug` is the sanctioned
local backend and the disposable container was never claimed by this session.

**AnyIO warning handling: command-line form (b)**, because two files in the list import
`fastapi.testclient` at module level — `test_web_library_evals.py:9` and
`test_managed_web_surfaces.py:32` — so the warning fires at collection where no marker can catch it.
The Ladybug run uses a **bare `-W error`**: neither of its two files imports a transport at module
level. No ini-wide filter was added, and no application warning was suppressed.

The brief's `test_web_evals*.py` does not exist; the Evals page tests live in
`tests/unit/test_web_library_evals.py`.

**The sweep (run 3) earned its keep: it found a regression neither of the brief's lists reaches.**
`tests/unit/test_web_busy_pages.py:72-76` stores `error="Ollama went away"` straight on the run row
and asserted the raw string on three pages. Only the run page changed — decision 1 is precisely the
change that stops it rendering there — so that one assertion now reads
`"The run failed: Operation failed"` and additionally asserts the raw string is **absent**. The other
two pages keep the old assertion, and the test says why: the set was created straight on the store,
so it carries no owner metadata, `EvalAccess` leaves `error` alone for an open audience, and the
string reaches the list pages through `partials/run_status.html`'s `title` attribute. One file
edited, one assertion, reported to the orchestrator rather than assumed.

---

## Deviations from the brief

1. **`public_errors.py` not touched.** Decision 1 required `public_failure_for_code` to resolve
   `retrieval_rebuild_required`, which it did not. The orchestrator assigned that file to opus-12
   (4c follow-up) and authorized one `git merge rag-it-all-tibs` (`feed275`) once it landed, so the
   fix is consumed rather than written here.
2. **The closed code rides in the first segment of `error`** rather than in a separate stored field,
   because `store/*` is do-NOT-touch and the three writers use fixed property lists. Orchestrator
   confirmed (Q3).
3. **Code and commit generation moved to a second test over the legacy code tree** (decision 4
   above): they are unreachable over a managed corpus.
4. **`web/routes/analyze.py` unchanged.** The audit decision 2 asked for concluded that the call site
   is correct as written; the reasoning is recorded under decision 2(d) so a reviewer can disagree
   with the conclusion rather than re-derive it.
5. **Two extra files edited, both authorized (Q2, Q4):** `src/hippo/evals/question_maker.py` (one
   failure-recording line, without which `eval_set.html` has no code to render) and
   `tests/unit/test_answer_original_citations.py` (one monkeypatch target). One comment corrected in
   `tests/unit/test_managed_web_surfaces.py`.
6. **Four commits, not the brief's two or three**, because the authorized merge falls between the
   third and fourth.
7. **Decision 5 not done — handed to opus-10** on the orchestrator's instruction, with the exact
   change recorded above. No second merge was taken.
8. **One assertion in `tests/unit/test_web_busy_pages.py`** (not on either list) updated for the run
   page's new rendering, found by the sweep in run 3.

## Open findings

* **Two more evaluation failure surfaces render the stored string, both outside this brief's
  templates: `partials/run_status.html:5` and `partials/set_status.html:5`** put `r.error` /
  `qs.error` in the failed pill's `title`. For an owned row `EvalAccess` has nulled that field, so
  the title is empty — the same dead-surface bug decision 1 fixed on the two templates it was given.
  For a metadata-less row read by an open or internal audience it is the raw string, which is the
  pre-existing and deliberate internal-diagnostics path. Converting them is the same one-line change
  (`public_reason(...)`), but it needs `evals_page` and `evals_tables_partial` to pass the resolver
  and it changes two assertions in `test_web_busy_pages.py`. This is the surface a reader lands on
  first, so it is worth doing next.
* **`web/routes/analyze.py`, `graph.py` bind `retrieval_session` at import.** Now that the promoted
  rule is late-bound in the four model/dense owners, the two route modules are the remaining
  import-bound callers, which is why `test_managed_web_surfaces.watch` needs its own per-module patch
  point. Converting them would let both recorders share one patch point; it is a mechanical change
  in files this slice does not own.
* **`answer_withheld` still conflates two things for a failure that *did* save a trace** (one that
  failed at the answer or grading step). That row reports a withheld answer and blanks the run
  summary, exactly as before. Narrowing it further means deciding what a partially-saved failed
  result owes a reader, which is a contract question, not a wrap-up one.
  Blast radius of the narrowing, checked rather than assumed: `rg answer_withheld src/hippo` finds
  exactly three sites, all in `eval_access.py` — the write at `:417`, the narrowing at `:429` and
  `get_run`'s summary gate at `:486`. No template and no route reads it; in particular
  `web/routes/analyze.py::_saved_result_check` gates on `get_result(...) is None`, not on this field,
  so clicking a failed row from `run_body.html:40` behaves exactly as it did before.
* **Two siblings of decision 3 are still unbounded**, both outside the brief's named line:
  `question_maker.py:140` and `runner._run_all:116` still call `log.exception(...)`, whose traceback
  footer is `str(exc)`. Both now compute a closed code one line below for storage, so bounding them
  is a two-line change for whoever owns the next logging pass.
* **`summarize`'s gold means still skip a failed question**, so a run of nothing but routing failures
  reports `accuracy: None` beside `errors: N`. That is the pre-existing and correct behaviour; it is
  recorded because the new `errors` card makes the pairing visible for the first time.
