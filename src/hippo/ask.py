"""
Search and ask: the two things every entry point (web, MCP, CLI) does with the memory.

    search(ctx, question)  -> Trace              (which passages, and why)
    ask(ctx, question)     -> (Trace, Answer)    (the LLM's answer from the top passages)

Both take an optional `access` (hippo/access.py): the search then runs on the
part of the graph that user may see, so hidden passages can neither be ranked
nor read by the model. None means unrestricted (open mode, the CLI, tests).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import prompts
from .access import Access
from .context import AppContext
from .hipporag import paths
from .hipporag.answerer import Answer, answer_question
from .hipporag.retriever import Retriever, Trace
from .knowledge.query_access import AuthorizedModel, query_access
from .knowledge.replay import can_reuse_answer, reconstruct_trace, view_fingerprint
from .store.base import validate_settings


def search(
    ctx: AppContext,
    question: str,
    settings: dict[str, Any] | None = None,
    access: Access | None = None,
    *,
    authorization_check: Callable[[], None] | None = None,
) -> Trace:
    """Rank visible passages, retaining any saved-input guard at every model boundary."""
    graph, model, validate = _query_access(ctx, access, authorization_check)
    trace = _search(ctx, graph, model, question, settings)
    validate()
    return trace


def _query_access(ctx, access, authorization_check):
    if authorization_check is not None:
        authorization_check()
    graph, model, query_check = query_access(ctx, access)
    if authorization_check is None:
        return graph, model, query_check

    def validate():
        authorization_check()
        query_check()

    validate()
    return graph, AuthorizedModel(model, validate), validate


def _search(ctx, graph, model, question, settings):
    merged = ctx.store.get_settings()
    merged.update(validate_settings(settings or {}))  # raises ValueError on junk, before any model call
    retriever = Retriever(graph, model)
    # The LLM keep/drop/expand pass is installed here rather than inside `retrieve`, so a unit test
    # or a replayed simulation that calls `retrieve` directly never makes a second model call. It
    # still only runs when the question named code (`code_select` and `used_code_seeds`).
    trace = retriever.retrieve(question, merged, select_fn=retriever.llm_select)
    trace.evidence_fingerprint = view_fingerprint(graph)
    return trace


def ask(
    ctx: AppContext, question: str, settings: dict[str, Any] | None = None, access: Access | None = None
) -> tuple[Trace, Answer]:
    """Retrieve, then let the LLM read the top `qa_top_k` passages and answer."""
    graph, model, validate = query_access(ctx, access)
    trace = _search(ctx, graph, model, question, settings)
    validate()
    answer = _answer_from_trace(graph, model, trace)
    validate()
    return trace, answer


def answer_from_trace(
    ctx: AppContext,
    trace: Trace,
    access: Access | None = None,
    *,
    authorization_check: Callable[[], None] | None = None,
) -> Answer:
    """Answer from ranked passages while preserving the caller's saved-input authorization."""
    graph, model, validate = _query_access(ctx, access, authorization_check)
    if not can_reuse_answer(graph, trace.evidence_fingerprint):
        trace = reconstruct_trace(graph, trace, question=trace.question)
    answer = _answer_from_trace(graph, model, trace)
    validate()
    return answer


def _answer_from_trace(graph, model, trace):
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
    return answer_question(model, trace.question, passages, context_block=code_block(graph, trace))


def code_fields(trace: Trace, block: str) -> dict[str, Any]:
    """
    What the question found in the code graph, as every surface reports it.

    The MCP tools (`search_tool`, `ask_tool`) and the HTTP `/api/search` and `/api/ask` all spread
    this dict into their answer, so the two cannot drift: a client that moves between them sees the
    same five keys. They are always present, so nothing has to branch on whether the memory holds
    code; on a prose question `paths`, `tests`, `history` and `code_graph` are all empty, which is
    the same gate the answer block itself uses (`used_code_seeds`, Ruling 1a). `seed_symbols` is the
    one that can still be non-empty there: a dense seed is recorded even though it never opens the
    gate, which is exactly what makes "this named no code" readable in the trace.

    The rows are the trace's own, so they match `/api/search`'s trace field for field.
    """
    return {
        "seed_symbols": [vars(seed) for seed in trace.seed_symbols],
        "paths": list(trace.paths),
        "tests": list(trace.tests),
        "history": list(trace.history),
        "code_graph": block,
    }


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
