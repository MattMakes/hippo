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

from . import prompts
from .access import Access
from .context import AppContext
from .hipporag import paths
from .hipporag.answerer import Answer, answer_question
from .hipporag.retriever import Retriever, Trace
from .store.base import validate_settings


def search(
    ctx: AppContext, question: str, settings: dict[str, Any] | None = None, access: Access | None = None
) -> Trace:
    """Rank passages for a question using the graph `access` may see, and the current settings."""
    merged = ctx.store.get_settings()
    merged.update(validate_settings(settings or {}))  # raises ValueError on junk, before any model call
    retriever = Retriever(ctx.graph_for(access), ctx.ollama)
    # The LLM keep/drop/expand pass is installed here rather than inside `retrieve`, so a unit test
    # or a replayed simulation that calls `retrieve` directly never makes a second model call. It
    # still only runs when the question named code (`code_select` and `used_code_seeds`).
    return retriever.retrieve(question, merged, select_fn=retriever.llm_select)


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
    # Passages the select pass fetched by "expand" are summarised inside the code block instead;
    # this slice *is* the citation list, so letting them in would cite a neighbour as a source.
    for ranked in [p for p in trace.passages if not p.via_expand][:qa_top_k]:
        passage = graph.passage_by_id(ranked.passage_id)
        if passage is not None:
            passages.append((passage.id, passage.title, passage.text))
    if not passages:
        return Answer(
            answer="I have nothing in memory to answer that yet.", thought="", raw="", passage_ids=[]
        )
    return answer_question(ctx.ollama, trace.question, passages, context_block=code_block(graph, trace))


def code_block(graph, trace: Trace) -> str:
    """
    The `Title: Code graph` pseudo-passage, or "" - gated on a *lexical* anchor having fired.

    That gate is what keeps a prose question over a memory containing code identical to today's:
    no block, no extra passage in the prompt, and no competition for `FakeOllama.answer`'s
    word-overlap scoring in the tests.
    """
    if not trace.used_code_seeds:
        return ""
    return paths.render_block(
        graph,
        trace,
        header=prompts.CODE_GRAPH_HEADER,
        max_chars=int(trace.settings.get("code_triples_chars", 1500)),
    )
