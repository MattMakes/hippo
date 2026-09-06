"""hippo/ask.py: search() and ask() glue the graph, the retriever and the answerer together."""

from __future__ import annotations

import pytest

from hippo.ask import answer_from_trace, ask, search
from hippo.context import AppContext
from hippo.hipporag.answerer import Answer
from hippo.hipporag.indexer import Chunk, index_source
from hippo.hipporag.retriever import Trace

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
