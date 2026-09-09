"""hippo/ask.py: search() and ask() glue the graph, the retriever and the answerer together."""

from __future__ import annotations

import pytest

from hippo import prompts
from hippo.ask import answer_from_trace, ask, search
from hippo.context import AppContext
from hippo.hipporag.answerer import Answer
from hippo.hipporag.indexer import Chunk, index_source
from hippo.hipporag.retriever import Trace
from tests.fakes.code_fixture import write_commit_history

DIRECT = "Where is Acme Robotics headquartered?"


def index_sample(ctx: AppContext, sample_text: str) -> str:
    source_id = ctx.store.create_source("sample", "Acme Robotics")
    chunks = []
    for ordinal, section in enumerate(sample_text.split("## ")[1:]):
        title, _, body = section.partition("\n")
        chunks.append(Chunk(ordinal, title.strip(), body.strip()))
    index_source(ctx.store, ctx.ollama, source_id, chunks)
    return source_id


@pytest.fixture
def indexed(ctx: AppContext, sample_text: str) -> AppContext:
    index_sample(ctx, sample_text)
    return ctx


def test_search_returns_a_trace_using_the_stored_settings(indexed: AppContext) -> None:
    trace = search(indexed, DIRECT)
    assert isinstance(trace, Trace)
    assert trace.settings == indexed.store.get_settings()
    assert trace.graph_version == indexed.store.graph_version()
    assert trace.passages[0].title == "The company"
    assert not trace.used_dpr_fallback


def test_search_merges_overrides_on_top_of_the_stored_settings(indexed: AppContext) -> None:
    indexed.store.update_settings({"damping": 0.7})
    trace = search(indexed, DIRECT, {"linking_top_k": 0})
    assert trace.settings["damping"] == 0.7
    assert trace.settings["linking_top_k"] == 0
    assert trace.used_dpr_fallback


def test_ask_returns_the_trace_and_an_answer_read_from_the_top_passages(indexed: AppContext) -> None:
    trace, answer = ask(indexed, DIRECT)
    assert isinstance(trace, Trace) and isinstance(answer, Answer)
    assert answer.answer == "Boulder"
    assert "Acme Robotics is headquartered in Boulder." in answer.thought
    assert answer.raw.endswith("Answer: Boulder")
    assert answer.passage_ids == trace.passage_ids()[:5]


def test_ask_reads_only_qa_top_k_passages(indexed: AppContext) -> None:
    trace, answer = ask(indexed, DIRECT, {"qa_top_k": 2})
    assert len(answer.passage_ids) == 2
    assert answer.passage_ids == trace.passage_ids()[:2]


def test_answer_from_trace_with_an_empty_trace_gives_the_friendly_message(ctx: AppContext) -> None:
    answer = answer_from_trace(ctx, Trace(question="Anything?", settings={}, graph_version=0))
    assert answer == Answer(
        answer="I have nothing in memory to answer that yet.", thought="", raw="", passage_ids=[]
    )


def test_answer_from_trace_skips_passages_that_no_longer_exist(indexed: AppContext) -> None:
    trace = search(indexed, DIRECT)
    trace.passages[0].passage_id = "passage-gone"
    answer = answer_from_trace(indexed, trace)
    assert "passage-gone" not in answer.passage_ids
    assert len(answer.passage_ids) == 4


def test_search_on_an_empty_memory_falls_back(ctx: AppContext) -> None:
    trace = search(ctx, DIRECT)
    assert trace.used_dpr_fallback
    assert trace.fallback_reason == "the memory is empty"
    _, answer = ask(ctx, DIRECT)
    assert answer.answer.startswith("I have nothing in memory")


def test_the_graph_reloads_after_new_text_is_indexed(indexed: AppContext) -> None:
    first = indexed.graph()
    other = indexed.store.create_source("text", "More")
    index_source(
        indexed.store, indexed.ollama, other, [Chunk(0, "Extra", "Skyline Software is located in Portland.")]
    )
    assert indexed.graph() is not first
    assert search(indexed, DIRECT).graph_version == indexed.store.graph_version()


# ==================================================================== the code graph
# WP3, over `tests/fixtures/code_sample/` indexed through the real pipeline. The block is a fixed
# grammar, not free text (S2.15): the point of pinning it exactly is that a rendering change has to
# be argued for rather than absorbed.

PLACE = "What does pyapp.orders.OrderService.place do?"

# The six kept seeds, in weight order, are `OrderService.place` (the identifier anchor, 0.33) and
# the dense `tests.test_orders`, `pyapp.__init__`, `goapp.cmd.main.main`, `rsapp.tests.orders`,
# `csapp.Program` (0.05 down to 0.0379); `pyapp.cli` fell off the end when the Go tree arrived and
# `rsapp.src.orders.tests.place_totals` when the C# one did -- by 7.5e-7 of dense score, the two
# entry-point-shaped passages being near-twins under `FakeOllama`'s feature hashing.
# Lines 1-5 are the pairwise paths between the strongest five (each new edge once) and they are all
# the Python tree's: the only route from `goapp`/`rsapp`/`csapp` to it is the shared `orders` table,
# whose `bare_identifier` READS is 0.60 and below theta. The rest is `code_paths_for`'s round-robin
# over the six seeds' own relations, each seed's strongest first (QA1F) -- a seed whose turn lands on
# an edge already printed above spends the turn, which is why the first round shows only the three
# seeds the paths did not already cover. Four of the six seeds belong to the other three trees: the
# fixture tells the same story in Go, Rust and C#, and under `FakeOllama`'s feature-hashed vectors
# their passages are as dense-similar as the Python ones. That is why the whole block no longer fits
# the default `code_triples_chars` of 1500 -- the cut is the next test's subject, so this one asks
# for a budget wide enough to see all of it.
CODE_BLOCK_BODY = [
    # place <-> tests.test_orders, then place <-> pyapp.__init__: the Python tree's own routes.
    "pyapp.orders.OrderService.place -[TESTED_BY 0.85 test_import]-> tests.test_orders.test_place",
    "tests.test_orders -[CONTAINS 1.00 syntax]-> tests.test_orders.test_place",
    "pyapp.orders.OrderService -[CONTAINS 1.00 syntax]-> pyapp.orders.OrderService.place",
    "pyapp.__init__ -[IMPORTS 0.95 import_path]-> pyapp.orders.OrderService",
    "tests.test_orders -[IMPORTS 0.95 import_path]-> pyapp.orders.OrderService",
    # Turn 1: the seeds' strongest edges that are not above yet -- one per tree that the paths missed.
    "goapp.cmd.main -[CONTAINS 1.00 syntax]-> goapp.cmd.main.main",
    "rsapp.tests.orders -[CONTAINS 1.00 syntax]-> rsapp.tests.orders.test_place",
    "csapp.Program -[IMPORTS 0.95 import_path]-> csapp.Orders.OrderService",
    # Turn 2: place's second-strongest (the other omega=1.00 relation, this one outgoing), then the
    # other seeds' strongest route into their own tree's service.
    "pyapp.orders.OrderService.place -[INVOKES 1.00 same_file]-> pyapp.orders.OrderService.log",
    "goapp.cmd.main.main -[INVOKES 0.90 via_import]-> goapp.orders.service.Service.Place",
    "rsapp.tests.orders -[IMPORTS 0.95 import_path]-> rsapp.src.orders.OrderService",
    "csapp.Program -[INVOKES 0.90 via_import]-> csapp.Orders.OrderService.OrderService",
    # Turn 3: at omega=0.90 an *incoming* call now comes before place's own outgoing ones - this is
    # the line that answers "who calls place", and out-then-in used to bury it (QA1 defect 1).
    "pyapp.cli.main -[INVOKES 0.90 via_import]-> pyapp.orders.OrderService.place",
    "pyapp.orders -[TESTED_BY 0.75 test_filename]-> tests.test_orders",
    "rsapp.src.orders -[TESTED_BY 0.75 test_filename]-> rsapp.tests.orders",
    "csapp.Program -[INVOKES 0.90 via_import]-> csapp.Orders.OrderService.OrderService.Place",
    # Turns 4-7: place's remaining omega=0.90 edges, in-then-out inside the tier.
    "pyapp.orders.OrderService.place -[CATCHES 0.90 resolved]-> pyapp.store.OrderError",
    "tests.test_orders.test_place -[INVOKES 0.90 via_import]-> pyapp.orders.OrderService.place",
    "pyapp.orders.OrderService.place -[INVOKES 0.90 via_import in_branch]-> pyapp.billing.send_invoice",
    "pyapp.orders.OrderService.place -[INVOKES 0.90 via_import]-> pyapp.billing.total",
    "Tests: tests.test_orders.test_place",
    "Commits: b2b2b2b 2026-01-02 Total the order in place",
    # One subsystem line per community the seeds reach: each tree is its own.
    "Subsystems: csapp.Billing.Billing: csapp.Orders.OrderService, "
    "csapp.Orders.OrderService.OrderService, csapp.Orders.OrderService.OrderService.Place, "
    "csapp.Program",
    "Subsystems: goapp.billing.billing: goapp.cmd.main, goapp.cmd.main.main, "
    "goapp.orders.service.Service.Place",
    "Subsystems: pyapp.__init__: pyapp.__init__, pyapp.billing.send_invoice, pyapp.billing.total, "
    "pyapp.cli.main, pyapp.orders, pyapp.orders.OrderService, "
    "pyapp.orders.OrderService.log, pyapp.orders.OrderService.place, pyapp.store.OrderError, "
    "tests.test_orders, tests.test_orders.test_place",
    "Subsystems: rsapp.src.billing: rsapp.src.orders, rsapp.src.orders.OrderService, "
    "rsapp.tests.orders, rsapp.tests.orders.test_place",
]


@pytest.fixture
def coded(code_index) -> AppContext:
    """The fixture tree, plus the three commits WP2b will build from a real checkout."""
    ctx, source_id = code_index
    write_commit_history(ctx, source_id)
    return ctx


def test_a_code_question_carries_the_block_exactly(coded: AppContext) -> None:
    # A budget wide enough for the whole block: what is pinned here is the grammar and the order,
    # and `code_triples_chars` (1500 by default, 2359 needed for four trees) is the next test.
    _, answer = ask(coded, PLACE, {"code_triples_chars": 8000})
    assert answer.context_block == "\n".join([prompts.CODE_GRAPH_HEADER, *CODE_BLOCK_BODY])


def test_the_block_rides_in_as_a_pseudo_passage_and_is_never_cited(coded: AppContext, fake_ollama) -> None:
    trace, answer = ask(coded, PLACE)
    last = fake_ollama.calls[-1]["messages"][-1]["content"]
    assert last.startswith("Title: Code graph\n" + prompts.CODE_GRAPH_HEADER)
    # The block is not a passage: it has no id, so it cannot end up in the citation list.
    assert answer.passage_ids == [p.passage_id for p in trace.passages][:5]
    assert all(pid.startswith("passage-") for pid in answer.passage_ids)


def test_there_is_no_block_when_the_question_named_no_code(coded: AppContext) -> None:
    trace, answer = ask(coded, "Where is Acme Robotics headquartered?")
    assert trace.used_code_seeds is False
    assert answer.context_block == ""
    assert "Title: Code graph" not in answer.raw


def test_code_triples_chars_cuts_on_a_line_boundary(coded: AppContext) -> None:
    _, answer = ask(coded, PLACE, {"code_triples_chars": 60})
    body = answer.context_block.splitlines()
    assert body[0] == prompts.CODE_GRAPH_HEADER  # the legend is outside the budget
    assert body[-1] == f"… (+{len(CODE_BLOCK_BODY)} more)"

    _, wider = ask(coded, PLACE, {"code_triples_chars": 300})
    kept = wider.context_block.splitlines()[1:-1]
    assert kept == CODE_BLOCK_BODY[: len(kept)], "whole lines only, in order"
    assert sum(len(line) for line in kept) + len(kept) - 1 <= 300
    assert wider.context_block.splitlines()[-1] == f"… (+{len(CODE_BLOCK_BODY) - len(kept)} more)"


def test_an_answer_stored_before_the_block_existed_still_loads() -> None:
    old = {"answer": "Boulder", "thought": "", "raw": "Answer: Boulder", "passage_ids": ["passage-1"]}
    assert Answer(**old).context_block == ""
