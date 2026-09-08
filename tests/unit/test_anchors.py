"""
hipporag/anchors.py: which symbols a question names, and how a question splits.

Two things are being defended here. The first is that a question containing an identifier, a
traceback, a snippet or a diff finds the right code nodes. The second matters more: that an
*ordinary prose question finds nothing*. Spike 1 (`research/S0-spikes.md`) measured the rule
PLAN.md first wrote and found it firing on 16% of 118 prose questions against Django's symbol set,
because `country`, `library`, `status` and `run` are English words as well as symbol names. The
corpus below is that spike's, and it runs with the stoplist emptied - which is the stronger test,
because it proves the surface-form rule carries the weight on its own.
"""

from __future__ import annotations

import pytest

from hippo.codegraph.model import symbol_id
from hippo.hipporag import anchors
from hippo.hipporag.anchors import (
    AMBIGUOUS_ABOVE,
    MAX_MATCHES_PER_TOKEN,
    Anchor,
    find_anchors,
    split_question,
)
from hippo.hipporag.graph_index import GraphIndex
from tests.fakes.code_fixture import many_symbols

TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "pyapp/cli.py", line 5, in main\n'
    "    service.place(order)\n"
    '  File "pyapp/orders.py", line 18, in place\n'
    "    amount = billing.total(order)\n"
    "OrderError: nope"
)

# Spike 1's corpus, cut to the questions that actually fired under the planned rule plus the
# abbreviations findings 2 and 3 are about. Every one of these must produce nothing.
PROSE = [
    "Where is Acme Robotics headquartered?",
    "Who maintains the Halo library?",
    "Can you check the sources for the status of the main index?",
    "What country is the city in, and what language do they run?",
    "Describe the source of the connection difference.",
    "What is the date of the site's quality review?",
    "Tell me about the total for that order.",
    "How do I get started with the store?",
    "What does the company build?",
    "Is there a log of everything that was saved?",
    "Who serves the customers list?",
    "The graph shows how the main run works.",
    "S.O.B. is a film, e.g. one from the U.S.A.",
    "In which state is the company founded by Priya Natarajan headquartered?",
]


@pytest.fixture
def index(code_index) -> GraphIndex:
    """`tests/fixtures/code_sample/` indexed through the real pipeline, extractor and all."""
    ctx, _source_id = code_index
    return ctx.graph()


def names(index: GraphIndex, found: list[Anchor]) -> list[str]:
    return [index.name_of(a.vertex) for a in found if not a.ambiguous]


# ------------------------------------------------------------- identifiers


def test_a_dotted_qualname_names_exactly_one_symbol(index: GraphIndex) -> None:
    found = find_anchors("What does pyapp.orders.OrderService.place do?", index)
    assert names(index, found) == ["OrderService.place"]
    assert found[0].how == "identifier"
    assert found[0].kind == "symbol"
    assert found[0].weight == 1.0
    assert found[0].n_matches == 1


def test_a_module_relative_qualname_resolves_too(index: GraphIndex) -> None:
    assert names(index, find_anchors("Explain OrderService.place", index)) == ["OrderService.place"]


def test_snake_case_pascal_case_and_all_caps_anchor_bare(index: GraphIndex) -> None:
    assert names(index, find_anchors("what does list_open return?", index)) == ["OrderService.list_open"]
    assert names(index, find_anchors("what is OrderService for?", index)) == ["OrderService"]
    assert names(index, find_anchors("where is send_invoice called?", index)) == ["send_invoice"]


def test_backticks_rescue_a_single_token_lowercase_name(index: GraphIndex) -> None:
    # The cost spike 1 asks us to accept and document: bare `place` in prose does not anchor,
    # because a lowercase single token is indistinguishable from English. Backticks say "code".
    assert find_anchors("what does place do?", index) == []
    assert names(index, find_anchors("what does `place` do?", index)) == ["OrderService.place"]


def test_a_data_object_anchors_by_its_name(index: GraphIndex) -> None:
    # `orders` is both the table and the module `pyapp/orders.py`, so the two share the weight.
    found = find_anchors("who writes to the `orders` table?", index)
    assert sorted(names(index, found)) == ["orders", "pyapp.orders"]
    assert {a.kind for a in found} == {"data", "symbol"}
    assert all(a.weight == pytest.approx(0.5) and a.n_matches == 2 for a in found)


def test_an_unknown_identifier_anchors_nothing(index: GraphIndex) -> None:
    assert find_anchors("what does `no_such_function` do?", index) == []


# -------------------------------------------------------------- prose is inert


@pytest.mark.parametrize("question", PROSE)
def test_ordinary_prose_anchors_nothing(index: GraphIndex, question: str, monkeypatch) -> None:
    monkeypatch.setattr(anchors, "STOPLIST", frozenset())
    assert find_anchors(question, index) == [], question


@pytest.mark.parametrize("question", PROSE)
def test_a_one_line_prose_question_is_all_prose(question: str) -> None:
    # S2.12's inert condition: the embedding and the fact filter see exactly what they see today.
    assert split_question(question) == (question, "")


def test_prose_is_inert_even_with_the_stoplist_emptied(index: GraphIndex, monkeypatch) -> None:
    monkeypatch.setattr(anchors, "STOPLIST", frozenset())
    assert [q for q in PROSE if find_anchors(q, index)] == []


# ------------------------------------------------------------- stack traces


def test_a_frame_resolves_to_the_innermost_symbol_containing_the_line(index: GraphIndex) -> None:
    found = find_anchors('File "pyapp/orders.py", line 18, in place', index)
    assert names(index, found) == ["OrderService.place"]
    assert found[0].how == "stack_trace"
    assert found[0].weight == 1.0


def test_an_absolute_frame_path_still_finds_the_repo_relative_symbol(index: GraphIndex) -> None:
    # A real traceback names the checkout's absolute path; the index holds the repo-relative one.
    # `_same_path` matches a suffix either way round, which is why AR1 fix 5's `path_index` is
    # keyed by the basename rather than by the whole path.
    found = find_anchors('File "/Users/me/proj/pyapp/orders.py", line 18, in place', index)
    assert names(index, found) == ["OrderService.place"]
    assert found[0].how == "stack_trace" and found[0].weight == 1.0
    # A file that shares a basename with nothing indexed still anchors on nothing.
    assert find_anchors('File "/elsewhere/nothing_here.py", line 18, in nope', index) == []


def test_a_drifted_line_falls_back_to_the_named_function(index: GraphIndex) -> None:
    found = find_anchors('File "pyapp/orders.py", line 999, in place', index)
    assert names(index, found) == ["OrderService.place"]
    assert found[0].how == "stack_trace"


def test_a_path_and_line_with_no_frame_wrapper_still_resolves(index: GraphIndex) -> None:
    assert names(index, find_anchors("it blew up at pyapp/orders.py:31", index)) == ["OrderService.save"]


def test_frames_decay_outwards_and_the_exception_line_anchors_at_08(index: GraphIndex) -> None:
    found = {index.name_of(a.vertex): a for a in find_anchors(TRACEBACK, index) if not a.ambiguous}
    assert found["OrderService.place"].weight == pytest.approx(1.0)
    assert found["OrderService.place"].how == "stack_trace"
    assert found["main"].weight == pytest.approx(0.8)  # one frame further out
    assert found["OrderError"].how == "exception"
    assert found["OrderError"].weight == pytest.approx(0.8)


def test_a_traceback_is_all_code_and_the_sentence_beside_it_is_all_prose(index: GraphIndex) -> None:
    prose, code = split_question("Why does this fail?\n" + TRACEBACK)
    assert prose == "Why does this fail?"
    assert code.startswith("Traceback") and 'File "pyapp/orders.py"' in code
    # find_anchors reads both halves, so the sentence never hides the frames.
    assert "OrderService.place" in names(index, find_anchors("Why does this fail?\n" + TRACEBACK, index))


# ------------------------------------------------------- fenced code and diffs


def test_a_fenced_block_is_tokenised_as_code(index: GraphIndex) -> None:
    question = "why is this slow?\n```python\namount = billing.total(order)\n```"
    found = find_anchors(question, index)
    assert "total" in names(index, found)
    assert {a.how for a in found} == {"fenced_code"}
    prose, code = split_question(question)
    assert prose == "why is this slow?"
    assert code == "amount = billing.total(order)"


def test_a_unified_diff_seeds_the_symbols_its_hunks_touch(index: GraphIndex) -> None:
    diff = (
        "--- a/pyapp/orders.py\n"
        "+++ b/pyapp/orders.py\n"
        "@@ -16,3 +16,4 @@\n"
        "-        amount = billing.total(order)\n"
        "+        amount = billing.total(order) or 0\n"
    )
    found = [a for a in find_anchors(diff, index) if a.how == "diff"]
    assert names(index, found) == ["OrderService.place"]
    assert found[0].weight == 1.0


# ------------------------------------------------------------- fan-out (S2.13)


def index_with(code_index, name: str, how_many: int) -> GraphIndex:
    """The fixture tree plus `how_many` functions all called `name` - a shape ten files cannot make."""
    ctx, source_id = code_index
    many_symbols(ctx, source_id, name, how_many)
    return ctx.graph()


def test_an_ambiguous_name_splits_its_weight_and_is_capped(code_index) -> None:
    index = index_with(code_index, "handle_it", MAX_MATCHES_PER_TOKEN + 1)
    found = [a for a in find_anchors("what does handle_it do?", index) if not a.ambiguous]
    assert len(found) == MAX_MATCHES_PER_TOKEN
    assert all(a.n_matches == MAX_MATCHES_PER_TOKEN + 1 for a in found)
    assert all(a.weight == pytest.approx(1.0 / (MAX_MATCHES_PER_TOKEN + 1)) for a in found)


def test_a_three_way_split_sums_to_one_share_of_the_seed_weight(index: GraphIndex) -> None:
    # `log` is a method on OrderService, on pyapp's Base and on tsapp's Base: three real symbols.
    found = find_anchors("what does `log` do?", index)
    assert sorted(names(index, found)) == ["Base.log", "Base.log", "OrderService.log"]
    assert sum(a.weight for a in found) == pytest.approx(1.0)
    assert {a.n_matches for a in found} == {3}


def test_a_name_matching_more_than_ten_symbols_seeds_nothing_and_says_so(code_index) -> None:
    index = index_with(code_index, "handle_it", AMBIGUOUS_ABOVE + 1)
    found = find_anchors("what does handle_it do?", index)
    assert [a.ambiguous for a in found] == [True]
    assert found[0].node_id == "" and found[0].vertex == -1 and found[0].weight == 0.0
    assert found[0].n_matches == AMBIGUOUS_ABOVE + 1


def test_a_path_qualified_match_is_never_split(index: GraphIndex) -> None:
    # Three symbols are called `log`; naming one of them by its module picks that one, whole.
    found = find_anchors("what does pyapp.store.Base.log do?", index)
    assert names(index, found) == ["Base.log"]
    assert found[0].weight == 1.0 and found[0].n_matches == 1


# ------------------------------------------------------------------ scoping


def test_a_scoped_index_never_surfaces_a_hidden_symbol(mixed_index) -> None:
    ctx, prose_source_id, code_source_id = mixed_index
    full = ctx.graph()
    assert find_anchors("what does `place` do?", full)

    scoped = full.scoped({prose_source_id})
    assert symbol_id(code_source_id, "pyapp/orders.py", "OrderService.place") not in scoped.idx_of
    assert find_anchors("what does `place` do?", scoped) == []


# ------------------------------------------------------------ determinism


def test_the_same_question_always_gives_the_same_anchors(index: GraphIndex) -> None:
    first = find_anchors(TRACEBACK, index)
    second = find_anchors(TRACEBACK, index)
    assert first == second
    assert [a.node_id for a in first] == sorted(
        [a.node_id for a in first], key=lambda nid: (-next(a.weight for a in first if a.node_id == nid), nid)
    )


def test_an_empty_question_splits_and_anchors_to_nothing(index: GraphIndex) -> None:
    assert split_question("") == ("", "")
    assert find_anchors("", index) == []
