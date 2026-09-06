"""
Search and ask: the two things every entry point (web, MCP, CLI) does with the memory.

    search(ctx, question)  -> Trace              (which passages, and why)
    ask(ctx, question)     -> (Trace, Answer)    (the LLM's answer from the top passages)
"""

from __future__ import annotations

from typing import Any

from .context import AppContext
from .hipporag.answerer import Answer, answer_question
from .hipporag.retriever import Retriever, Trace


def search(ctx: AppContext, question: str, settings: dict[str, Any] | None = None) -> Trace:
    """Rank passages for a question using the current graph and settings."""
    merged = ctx.store.get_settings()
    merged.update(settings or {})
    return Retriever(ctx.graph(), ctx.ollama).retrieve(question, merged)


def ask(ctx: AppContext, question: str, settings: dict[str, Any] | None = None) -> tuple[Trace, Answer]:
    """Retrieve, then let the LLM read the top `qa_top_k` passages and answer."""
    trace = search(ctx, question, settings)
    return trace, answer_from_trace(ctx, trace)


def answer_from_trace(ctx: AppContext, trace: Trace) -> Answer:
    """Answer using the passages a trace already ranked (used by simulations to re-answer)."""
    graph = ctx.graph()
    qa_top_k = int(trace.settings.get("qa_top_k", 5))
    passages = []
    for ranked in trace.passages[:qa_top_k]:
        passage = graph.passage_by_id(ranked.passage_id)
        if passage is not None:
            passages.append((passage.id, passage.title, passage.text))
    if not passages:
        return Answer(
            answer="I have nothing in memory to answer that yet.", thought="", raw="", passage_ids=[]
        )
    return answer_question(ctx.ollama, trace.question, passages)
