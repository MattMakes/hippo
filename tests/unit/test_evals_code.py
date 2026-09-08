"""
Code and commit questions: the two generators, the new recall keys and the baseline comparison.

Everything here runs over `code_index` - the checked-in `code_sample` tree indexed through the real
pipeline - so the questions are built from the extractor's own graph, not a hand-written guess.

One rule holds throughout: **the judge's verdict is never asserted on a code or commit question**.
`_grade` runs whenever `expected_answer` is non-empty and `FakeOllama.judge` scores content-word
overlap with no code awareness, so a qualname-heavy expected answer scores at random (R2-15).

The commit half needs commits that touch **two** symbols, and `write_commit_history` writes three
that touch one each. `code_history` below keeps those three and adds a second `MODIFIES` to the two
newest, which is also what makes "the one-symbol commit is skipped" checkable. When WP2b lands, the
same assertions should hold over the real `git_index`.
"""

from __future__ import annotations

import pytest

from hippo.codegraph.model import commit_id, symbol_id
from hippo.evals.question_maker import code_questions, commit_questions, generate_questions
from hippo.evals.runner import BASELINE_SETTINGS, compare_with_baseline, run_question, summarize
from tests.fakes.code_fixture import write_commit_history

# A dotted qualname is code-shaped, so `find_anchors` seeds from it and `used_code_seeds` opens.
# This is the shape `code_questions` writes; if it stopped anchoring, every code metric would read 0.
PLACE_QUESTION = "What does pyapp.orders.OrderService.place call?"

PLACE_TITLE = "pyapp/orders.py :: pyapp.orders.OrderService.place (lines 16-23)"
LOG_TITLE = "pyapp/orders.py :: pyapp.orders.OrderService.log (lines 25-25)"
SAVE_TITLE = "pyapp/orders.py :: pyapp.orders.OrderService.save (lines 30-32)"
RUN_TITLE = "pyapp/orders.py :: pyapp.orders.OrderService.run (lines 40-40)"
TOTAL_TITLE = "pyapp/billing.py :: pyapp.billing.total (lines 4-5)"


def titles(ctx, passage_ids: list[str]) -> list[str]:
    """Gold passage ids -> their titles, in the order the question stored them."""
    index = ctx.graph()
    return [index.passage_by_id(pid).title for pid in passage_ids]


@pytest.fixture
def code_history(code_index):
    """
    `code_index` plus three commits, the two newest touching two symbols each.

    `write_commit_history` gives one `MODIFIES` per commit; the extra rows here are what makes
    commits 0 and 1 qualify for a commit question and commit 2 (one symbol) stay out.
    """
    ctx, source_id = code_index
    write_commit_history(ctx, source_id)
    ctx.store.add_modifies(
        [
            {
                "commit_id": commit_id(source_id, sha),
                "symbol_id": symbol_id(source_id, "pyapp/orders.py", qualname)
                if qualname.startswith("OrderService")
                else symbol_id(source_id, "pyapp/billing.py", qualname),
                "omega": 1.0,
                "hunk": {"file": "pyapp/orders.py", "old_range": [1, 0], "new_range": [1, 1], "churn": 1},
            }
            for sha, qualname in (("c3c3c3c", "OrderService.run"), ("b2b2b2b", "total"))
        ]
    )
    ctx.invalidate_graph()
    yield ctx, source_id


# ------------------------------------------------------------------- the metrics


def test_a_question_naming_a_qualname_is_code_seeded(code_index):
    ctx, _source_id = code_index
    row = {"id": "x", "text": PLACE_QUESTION, "expected_answer": "", "gold_passage_ids": []}

    result = run_question(ctx, row, ctx.store.get_settings())

    assert result["error"] is None
    assert result["trace"]["used_code_seeds"] is True
    assert result["recall"]["code_seeded"] == 1.0
    # A code question carries no gold-passage metrics of its own here, and `code_seeded` must not
    # pretend it does: it is a property of the trace, not of the gold set.
    assert "recall@5" not in result["recall"]
    assert result["gold_rank"] is None


def test_a_prose_question_is_not_code_seeded(ctx, sample_text):
    from tests.conftest import index_prose_sample

    index_prose_sample(ctx)
    row = {
        "id": "x",
        "text": "Where is Acme Robotics headquartered?",
        "expected_answer": "",
        "gold_passage_ids": [],
    }

    result = run_question(ctx, row, ctx.store.get_settings())

    assert result["recall"] == {"code_seeded": 0.0}


def test_path_fidelity_scores_the_symbols_a_commit_touched(code_history):
    ctx, source_id = code_history
    question = commit_questions(ctx.graph(), source_id, 1)[0]

    result = run_question(ctx, question, ctx.store.get_settings())

    assert result["error"] is None
    # Two gold symbol passages behind the commit passage: the share of them in the top 5.
    assert result["recall"]["path_fidelity"] in (0.0, 0.5, 1.0)
    assert result["recall"]["code_seeded"] in (0.0, 1.0)
    assert "recall@5" in result["recall"]


def test_only_commit_questions_get_path_fidelity(code_index):
    ctx, source_id = code_index
    question = code_questions(ctx.graph(), source_id, 1)[0]

    result = run_question(ctx, question, ctx.store.get_settings())

    assert "path_fidelity" not in result["recall"]
    assert result["recall"]["code_seeded"] == 1.0


def test_summarize_means_the_new_keys():
    results = [
        {"recall": {"recall@5": 1.0, "code_seeded": 1.0, "path_fidelity": 1.0}, "gold_rank": 1},
        {"recall": {"recall@5": 0.0, "code_seeded": 0.0, "path_fidelity": 0.0}, "gold_rank": None},
        {"recall": {"code_seeded": 1.0}, "gold_rank": None},  # no gold: counts for the flag only
    ]

    summary = summarize(results)

    assert summary["code_seeded"] == round(2 / 3, 4)
    assert summary["path_fidelity"] == 0.5
    # A question with no gold passages must not join the gold means, which `code_seeded` alone
    # would otherwise drag it into: `recall@5` and `gold_in_top5` still average two questions.
    assert summary["recall@5"] == 0.5
    assert summary["gold_in_top5"] == 0.5
    assert summary["mean_gold_rank"] == 1


def test_summarize_reports_no_path_fidelity_without_commit_questions():
    summary = summarize([{"recall": {"recall@1": 1.0, "code_seeded": 0.0}, "gold_rank": 1}])
    assert summary["path_fidelity"] is None
    assert summary["code_seeded"] == 0.0


# ---------------------------------------------------------------- the generators


def test_code_questions_are_the_documented_functions_that_call(code_index):
    ctx, source_id = code_index
    index = ctx.graph()

    questions = code_questions(index, source_id, 5)

    # `place` is the only function in the tree with both a doc >= 80 chars and an INVOKES out-edge:
    # `cli.main`, `test_place`, `save`, `list_open`, `graph` and `Order.total` all call but carry no
    # doc, and `OrderService` and `Order` carry a doc but call nothing.
    assert [q["text"] for q in questions] == [PLACE_QUESTION]
    question = questions[0]
    assert question["kind"] == "code"
    assert question["expected_answer"] == (
        "pyapp.orders.OrderService.place calls pyapp.orders.OrderService.log."
    )
    # The strongest call wins the gold slot: `log` is same_file at 1.00, the other two via_import
    # at 0.90. All three are in the notes so a person reading the set sees the whole call site.
    assert question["notes"] == (
        "INVOKES pyapp.orders.OrderService.log (same_file, omega 1.00); callees: "
        "pyapp.billing.send_invoice, pyapp.billing.total, pyapp.orders.OrderService.log"
    )
    assert titles(ctx, question["gold_passage_ids"]) == [PLACE_TITLE, LOG_TITLE]


def test_commit_questions_need_two_touched_symbols(code_history):
    ctx, source_id = code_history
    index = ctx.graph()

    questions = commit_questions(index, source_id, 5)

    # Newest first, and "Add the order service" (one symbol) is not a localization question at all.
    assert [q["text"] for q in questions] == [
        'What changed in the commit "Raise OrderError from save"?',
        'What changed in the commit "Total the order in place"?',
    ]
    assert [q["kind"] for q in questions] == ["commit", "commit"]
    assert questions[0]["expected_answer"] == (
        'The commit "Raise OrderError from save" changed '
        "pyapp.orders.OrderService.run, pyapp.orders.OrderService.save."
    )
    assert questions[0]["notes"] == ("touched: pyapp.orders.OrderService.run, pyapp.orders.OrderService.save")
    # The commit's own passage comes first and the symbols' follow: `path_fidelity` reads that order.
    assert titles(ctx, questions[0]["gold_passage_ids"]) == [
        "commit c3c3c3c: Raise OrderError from save",
        RUN_TITLE,
        SAVE_TITLE,
    ]
    # Display order, not the order the MODIFIES rows were written: `pyapp.billing.total` sorts first.
    assert titles(ctx, questions[1]["gold_passage_ids"]) == [
        "commit b2b2b2b: Total the order in place",
        TOTAL_TITLE,
        PLACE_TITLE,
    ]
    assert questions[1]["expected_answer"] == (
        'The commit "Total the order in place" changed pyapp.billing.total, pyapp.orders.OrderService.place.'
    )


def test_the_generators_are_pure_and_bounded(code_history):
    ctx, source_id = code_history
    index = ctx.graph()
    before = len(ctx.store.list_question_sets())

    assert code_questions(index, source_id, 0) == []
    assert commit_questions(index, source_id, 0) == []
    assert len(commit_questions(index, source_id, 1)) == 1
    assert code_questions(index, "no-such-source", 5) == []
    assert commit_questions(index, "no-such-source", 5) == []
    assert len(ctx.store.list_question_sets()) == before  # pure: nothing was written


def test_a_prose_source_yields_no_code_questions(ctx, sample_text):
    from tests.conftest import index_prose_sample

    source_id = index_prose_sample(ctx)
    index = ctx.graph()

    assert code_questions(index, source_id, 5) == []
    assert commit_questions(index, source_id, 5) == []


def test_generate_questions_stores_the_code_and_commit_questions(code_history):
    ctx, source_id = code_history

    set_id = generate_questions(ctx, source_id, max_single=2, max_multihop=0, max_code=5, max_commits=1)

    question_set = ctx.store.get_question_set(set_id)
    assert question_set["status"] == "ready"
    assert question_set["progress_done"] == question_set["progress_total"] > 0
    questions = ctx.store.list_questions(set_id)
    code = [q for q in questions if q["kind"] == "code"]
    commits = [q for q in questions if q["kind"] == "commit"]
    assert [q["text"] for q in code] == [PLACE_QUESTION]
    assert [q["text"] for q in commits] == ['What changed in the commit "Raise OrderError from save"?']
    passage_ids = set(ctx.store.passage_ids_for_source(source_id))
    for q in code + commits:
        assert set(q["gold_passage_ids"]) <= passage_ids
        assert q["expected_answer"]


def test_shared_entity_pairs_never_names_a_code_node(mixed_index):
    """
    WP1.4's checklist for this file: a non-passage vertex must not be treated as an entity.

    Run over prose *and* code in one memory, because that is the only shape where the bug could
    show: a passage in a code memory neighbours symbol vertices through DEFINED_IN, and a
    "not a passage, so it is an entity" test would pair two passages on a shared *symbol* and then
    ask `name_of` for an entity name it does not have.
    """
    from hippo.evals.question_maker import shared_entity_pairs
    from hippo.hipporag.graph_index import SYMBOL

    ctx, _prose_source_id, code_source_id = mixed_index
    index = ctx.graph()

    pairs = shared_entity_pairs(index, index.passages)

    assert pairs  # the prose corpus shares entities across sections
    entity_names = set(index.entity_names.values())
    for name, a, b in pairs:
        assert name in entity_names
        assert a.id != b.id
    # And the guard is not vacuous: a symbol passage really does neighbour symbol vertices.
    symbol_passage = next(p for p in index.passages if p.source_id == code_source_id and "::" in p.title)
    neighbours = index.neighbors(index.idx_of[symbol_passage.id])
    assert any(index.node_kind[n] == SYMBOL for n, _weight in neighbours)


# ------------------------------------------------------------------ the baseline


def test_the_baseline_run_turns_code_seeding_off(code_index):
    ctx, source_id = code_index
    set_id = generate_questions(ctx, source_id, max_single=0, max_multihop=0, max_code=5, max_commits=0)

    with_code, baseline = compare_with_baseline(ctx, set_id)

    assert BASELINE_SETTINGS == {
        "code_seed_weight": 0.0,
        "code_dense_seeds": 0,
        "code_select": False,
        "code_structural_scale": 0.0,
    }
    assert with_code["questions"] == baseline["questions"] == 1
    assert with_code["errors"] == baseline["errors"] == 0
    assert with_code["code_seeded"] == 1.0
    assert baseline["code_seeded"] == 0.0
    # No verdict assertion on either side: the fake judge has no opinion worth pinning here (R2-15).
