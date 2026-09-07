"""
Search and ask: the two things every entry point (web, MCP, CLI) does with the memory.

    search(ctx, question)  -> Trace              (which passages, and why)
    ask(ctx, question)     -> (Trace, Answer)    (the LLM's answer from the top passages)

Both take an optional `access` (hippo/access.py): the search then runs on the
part of the graph that user may see, so hidden passages can neither be ranked
nor read by the model. None means unrestricted (open mode, the CLI, tests).
"""

from __future__ import annotations

from typing import Any

from .access import Access
from .context import AppContext
from .hipporag.answerer import Answer, answer_question
from .hipporag.retriever import Retriever, Trace
from .store.base import validate_settings


def search(
    ctx: AppContext, question: str, settings: dict[str, Any] | None = None, access: Access | None = None
) -> Trace:
    """Rank passages for a question using the graph `access` may see, and the current settings."""
    merged = ctx.store.get_settings()
    merged.update(validate_settings(settings or {}))  # raises ValueError on junk, before any model call
    return Retriever(ctx.graph_for(access), ctx.ollama).retrieve(question, merged)


def ask(
    ctx: AppContext, question: str, settings: dict[str, Any] | None = None, access: Access | None = None
) -> tuple[Trace, Answer]:
    """Retrieve, then let the LLM read the top `qa_top_k` passages and answer."""
    trace = search(ctx, question, settings, access)
    return trace, answer_from_trace(ctx, trace, access)


def answer_from_trace(ctx: AppContext, trace: Trace, access: Access | None = None) -> Answer:
    """Answer using the passages a trace already ranked (used by simulations to re-answer)."""
    graph = ctx.graph_for(access)
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
