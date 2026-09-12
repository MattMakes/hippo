"""
Search and ask: the two things every entry point (web, MCP, CLI) does with the memory.

    search(ctx, question)  -> Trace              (which passages, and why)
    ask(ctx, question)     -> (Trace, Answer)    (the LLM's answer from the top passages)

Both take an optional `access` (hippo/access.py): the search then runs on the
part of the graph that user may see, so hidden passages can neither be ranked
nor read by the model. None means the open audience (open mode, the CLI,
tests), which reads legacy sources unrestricted but cannot prove managed
evidence, so a managed corpus needs a real reader.

Every model path here runs over one held structural session dispatched by
`retrieval_session`, which is what turns the view's provenance sidecars back
into a scorable matrix. A caller may hand its own session in; it is dispatched
in place, and never reacquired below this layer.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from typing import Any

from . import prompts
from .access import Access
from .context import AppContext
from .hipporag import paths
from .hipporag.answerer import Answer, answer_question
from .hipporag.retriever import Retriever, Trace
from .knowledge.citations import resolve_citations
from .knowledge.dense_session import retrieval_session
from .knowledge.query_access import AuthorizedModel, QuerySession
from .knowledge.replay import can_reuse_answer, reconstruct_trace, view_fingerprint
from .store.base import validate_settings

# The two modes `retrieval_session` yields once it has chosen a route. Anything else
# is an owner that has not been dispatched yet (a structural graph reports
# "unavailable"; an activated empty one reports "legacy" and re-wrapping it is a
# no-op that makes no model call).
_DISPATCHED = frozenset({"verified", "tag_compatible"})


def search(
    ctx: AppContext,
    question: str,
    settings: dict[str, Any] | None = None,
    access: Access | None = None,
    *,
    authorization_check: Callable[[], None] | None = None,
    session: QuerySession | None = None,
) -> Trace:
    """Rank visible passages, retaining any saved-input guard at every model boundary."""
    with _retrieval_scope(ctx, access, authorization_check, session, settings) as query:
        trace = _search(ctx, query.graph, query.model, question, settings, effective_settings=query.settings)
        query.validate()
        return trace


def _dispatch(ctx, access, session, settings):
    """One structural owner, routed to the dense evidence this audience actually proved.

    Owned: `retrieval_session` acquires the structural session itself, so no graph is
    reacquired below it. Borrowed: the caller's own session is dispatched in place -- or
    passed straight through when the caller already dispatched it, because re-resolving
    would cost a second `/api/show` and probe embedding for the same profile.
    """
    if session is None:
        return retrieval_session(ctx, access, settings=settings)
    if type(session) is QuerySession and session.graph.dense_capability.mode in _DISPATCHED:
        return nullcontext(session)
    # Settings were already compared against the held session; passing them again would
    # only replace that message with the dispatcher's own.
    return retrieval_session(ctx, session=session)


@contextmanager
def _retrieval_scope(ctx, access, authorization_check, session, settings):
    if authorization_check is not None:
        authorization_check()
    if session is not None:
        overrides = validate_settings(settings or {})
        if any(session.settings.get(key) != value for key, value in overrides.items()):
            raise ValueError("Query settings do not match the active session")
    with _dispatch(ctx, access, session, settings) as query:

        def validate():
            if authorization_check is not None:
                authorization_check()
            query.validate()

        validate()
        try:
            yield QuerySession(query.graph, AuthorizedModel(query.model, validate), validate, query.settings)
        finally:
            validate()


def _search(ctx, graph, model, question, settings, *, effective_settings=None):
    if effective_settings is None:
        merged = ctx.store.get_settings()
        merged.update(validate_settings(settings or {}))
    else:
        merged = dict(effective_settings)
    retriever = Retriever(graph, model)
    # The LLM keep/drop/expand pass is installed here rather than inside `retrieve`, so a unit test
    # or a replayed simulation that calls `retrieve` directly never makes a second model call. It
    # still only runs when the question named code (`code_select` and `used_code_seeds`).
    trace = retriever.retrieve(question, merged, select_fn=retriever.llm_select)
    trace.evidence_fingerprint = view_fingerprint(graph)
    trace.snapshot_ids = tuple(getattr(graph, "snapshot_ids", ()))
    return trace


def ask(
    ctx: AppContext,
    question: str,
    settings: dict[str, Any] | None = None,
    access: Access | None = None,
    *,
    authorization_check: Callable[[], None] | None = None,
    session: QuerySession | None = None,
) -> tuple[Trace, Answer]:
    """Retrieve, then let the LLM read the top `qa_top_k` passages and answer."""
    with _retrieval_scope(ctx, access, authorization_check, session, settings) as query:
        trace = _search(ctx, query.graph, query.model, question, settings, effective_settings=query.settings)
        query.validate()
        answer = _answer_from_trace(query.graph, query.model, trace)
        query.validate()
        return trace, answer


def answer_from_trace(
    ctx: AppContext,
    trace: Trace,
    access: Access | None = None,
    *,
    authorization_check: Callable[[], None] | None = None,
    session: QuerySession | None = None,
) -> Answer:
    """Answer from ranked passages while preserving the caller's saved-input authorization."""
    with _retrieval_scope(ctx, access, authorization_check, session, trace.settings) as query:
        if not can_reuse_answer(query.graph, trace.evidence_fingerprint):
            trace = reconstruct_trace(query.graph, trace, question=trace.question)
        trace = replace(trace, settings=dict(query.settings))
        answer = _answer_from_trace(query.graph, query.model, trace)
        query.validate()
        return answer


def _answer_from_trace(graph, model, trace):
    qa_top_k = int(trace.settings.get("qa_top_k", 5))
    retrieval_ids = []
    # Passages the select pass fetched by "expand" are summarised inside the code block instead;
    # this slice *is* the citation list, so letting them in would cite a neighbour as a source.
    for ranked in [p for p in trace.passages if not p.via_expand][:qa_top_k]:
        passage = graph.passage_by_id(ranked.passage_id)
        if passage is not None:
            retrieval_ids.append(passage.id)
    if not retrieval_ids:
        return Answer(
            answer="I have nothing in memory to answer that yet.", thought="", raw="", passage_ids=[]
        )
    bundle = resolve_citations(graph, tuple(retrieval_ids))
    passages = [(citation.id, citation.title, citation.text) for citation in bundle.citations]
    answer = answer_question(model, trace.question, passages, context_block=code_block(graph, trace))
    answer.retrieval_passage_ids = list(bundle.retrieval_passage_ids)
    return answer


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
