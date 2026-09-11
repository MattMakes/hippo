"""Rendered retrieval candidates lead to exact original evidence in answers."""

import pytest

from hippo.ask import _answer_from_trace
from hippo.hipporag.graph_index import Passage
from hippo.hipporag.retriever import RankedPassage, Trace
from hippo.knowledge.citations import OriginalCitation, RetrievalEvidence
from hippo.knowledge.identity import text_hash
from tests.unit.test_evidence_projection import graph


@pytest.fixture
def derived_graph():
    index = graph(
        [],
        [
            Passage("view-a", "Rendered A", "GENERATED PLACEHOLDER A", "source", "", 0),
            Passage("view-b", "Rendered B", "GENERATED PLACEHOLDER B", "source", "", 1),
        ],
    )
    index.managed_passage_ids = frozenset({"view-a", "view-b"})
    index.retrieval_evidence = (
        RetrievalEvidence("view-a", "generation", "rv-a", ("span-a", "span-b")),
        RetrievalEvidence("view-b", "generation", "rv-b", ("span-a",)),
    )
    index.original_citations = tuple(
        OriginalCitation(
            id=identity,
            span_id=identity,
            revision_id="revision",
            artifact_id="artifact",
            text=text,
            title="original.py",
            source_id="source",
            text_hash=text_hash(text),
            locator_kind="file_lines",
            locator_json='{"kind":"file_lines","path":"original.py","start":1,"end":1}',
        )
        for identity, text in (("span-a", "def original(): pass"), ("span-b", "# Original requirement"))
    )
    trace = Trace(question="How does original work?", settings={"qa_top_k": 2}, graph_version=0)
    trace.passages = [
        RankedPassage(
            passage_id=p.id,
            title=p.title,
            source_id=p.source_id,
            source_name="source",
            rank=i + 1,
            score=1.0,
            dpr_score=1.0,
            dpr_rank=i + 1,
            preview=p.text,
        )
        for i, p in enumerate(index.passages)
    ]
    return index, trace


def test_answer_reads_all_original_inputs_and_deduplicates_shared_citations(derived_graph):
    from types import SimpleNamespace

    index, trace = derived_graph
    prompts = []

    def chat(messages, **kwargs):
        prompts.extend(messages)
        return "Answer: original evidence"

    answer = _answer_from_trace(index, SimpleNamespace(chat_text=chat), trace)
    assert answer.passage_ids == ["span-a", "span-b"]
    assert answer.retrieval_passage_ids == ["view-a", "view-b"]
    content = str(prompts)
    assert "def original(): pass" in content and "# Original requirement" in content
    assert "GENERATED PLACEHOLDER" not in content
    assert content.count("def original(): pass") == 1


def test_top_k_and_expansion_selection_happen_before_original_closure(derived_graph):
    from types import SimpleNamespace

    index, trace = derived_graph
    trace.settings["qa_top_k"] = 1
    trace.passages[1].via_expand = True
    answer = _answer_from_trace(index, SimpleNamespace(chat_text=lambda *a, **kw: "Answer: yes"), trace)
    assert answer.passage_ids == ["span-a", "span-b"]
    assert answer.retrieval_passage_ids == ["view-a"]


def test_missing_managed_lineage_fails_before_model(derived_graph):
    from types import SimpleNamespace

    index, trace = derived_graph
    index.retrieval_evidence = ()
    with pytest.raises(ValueError, match="lineage"):
        _answer_from_trace(
            index, SimpleNamespace(chat_text=lambda *a, **kw: pytest.fail("model called")), trace
        )


@pytest.mark.parametrize("surface", ["http", "mcp", "html"])
def test_answer_surfaces_present_originals_separately_from_ranked_views(
    ctx, derived_graph, monkeypatch, surface
):
    from types import SimpleNamespace

    from hippo import ask, mcp_server
    from hippo.access import Principal
    from hippo.web import render
    from hippo.web.routes import api, pages

    index, trace = derived_graph
    monkeypatch.setattr(ctx, "graph_for", lambda *a, **kw: index)
    monkeypatch.setattr(ask, "_search", lambda *a, **kw: trace)
    monkeypatch.setattr(ctx.ollama, "chat_text", lambda *a, **kw: "Answer: original evidence")
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(ctx=ctx)), state=SimpleNamespace(principal=Principal.open())
    )
    if surface == "mcp":
        result = mcp_server.ask_tool(ctx, trace.question)
        originals = result["sources"]
    elif surface == "http":
        result = api.ask(request, api.QuestionBody(question=trace.question))
        originals = result["sources"]
        assert result["passage_ids"] == ["span-a", "span-b"]
        assert result["retrieval_passage_ids"] == ["view-a", "view-b"]
    else:
        monkeypatch.setattr(
            render.templates, "TemplateResponse", lambda request, template, context, **kw: context
        )
        result = pages.ask_submit(request, trace.question)
        originals = result["passages"]
    assert [row["passage_id"] for row in originals] == ["span-a", "span-b"]
    assert originals[0]["retrieval_passage_ids"] == ["view-a", "view-b"]
    assert all(row["title"] == "original.py" for row in originals)
    assert all(row["locator_kind"] == "file_lines" for row in originals)
    assert "GENERATED PLACEHOLDER" not in str(originals)


def test_question_generation_reads_originals_but_keeps_retrieval_gold_ids(ctx, derived_graph):
    from types import SimpleNamespace

    from hippo.evals.question_maker import _single_hop_questions

    index, _ = derived_graph
    prompts = []

    def chat(messages, *args, **kwargs):
        prompts.extend(messages)
        return {"questions": [{"question": "What is implemented?", "answer": "original"}]}

    set_id = ctx.store.create_question_set("test")
    rows = _single_hop_questions(
        ctx, set_id, index.passages[:1], 1, 1, model=SimpleNamespace(chat_json=chat), index=index
    )
    assert rows[0]["gold_passage_ids"] == ["view-a"]
    assert "GENERATED PLACEHOLDER" not in str(prompts)
    assert "def original(): pass" in str(prompts) and "# Original requirement" in str(prompts)


def test_multihop_skips_views_without_distinct_originals_on_both_sides(ctx, derived_graph):
    from types import SimpleNamespace

    from hippo.evals.question_maker import _ask_multihop

    index, _ = derived_graph
    model = SimpleNamespace(chat_json=lambda *a, **kw: pytest.fail("Redundant views reached model"))
    assert _ask_multihop(ctx, "original", *index.passages, model=model, index=index) is None


def test_multihop_shared_original_is_only_sent_once(ctx, derived_graph):
    from dataclasses import replace
    from types import SimpleNamespace

    from hippo.evals.question_maker import _ask_multihop

    index, _ = derived_graph
    text = "# Independent implementation detail"
    index.original_citations += (
        replace(
            index.original_citations[1], id="span-c", span_id="span-c", text=text, text_hash=text_hash(text)
        ),
    )
    index.retrieval_evidence = (
        index.retrieval_evidence[0],
        replace(index.retrieval_evidence[1], original_span_ids=("span-b", "span-c")),
    )
    messages = []

    def chat(prompt, *args, **kwargs):
        messages.extend(prompt)
        return {"question": "What relates them?", "answer": "original"}

    row = _ask_multihop(ctx, "original", *index.passages, model=SimpleNamespace(chat_json=chat), index=index)
    assert row["gold_passage_ids"] == ["view-a", "view-b"]
    assert str(messages).count("# Original requirement") == 1
    assert "def original(): pass" in str(messages) and text in str(messages)


def test_generated_question_job_pins_once_across_publication(ctx, monkeypatch):
    from hippo.access import EVERYTHING
    from hippo.evals.question_maker import _create_set, generate_questions
    from tests.unit.test_query_snapshots import build

    generation, span = build(ctx, text="first revision.")
    set_id = _create_set(ctx, generation.source_id, None, EVERYTHING)
    for reference in ctx.store._knowledge_rows("SnapshotReference"):
        if reference.released_at is None:
            ctx.store.release_snapshot_reference(reference.id, lease_owner=reference.lease_owner)
    acquired = []
    graph_for = ctx.graph_for

    def graph(*args, **kwargs):
        index = graph_for(*args, **kwargs)
        acquired.append(index)
        return index

    def chat(*args, **kwargs):
        build(ctx, parent=generation, text="second revision.")
        assert ctx.store.collect_generation(generation.id).blocked_reason == "snapshot_reference"
        return {"questions": [{"question": "What was first?", "answer": "first revision"}]}

    monkeypatch.setattr(ctx, "graph_for", graph)
    monkeypatch.setattr(ctx.ollama, "chat_json", chat)
    set_id = generate_questions(
        ctx, generation.source_id, set_id=set_id, max_single=1, max_multihop=0, access=EVERYTHING
    )
    assert len(acquired) == 1
    assert ctx.store.list_questions(set_id)[0]["gold_passage_ids"] == [span.id]
    assert all(ref.released_at for ref in ctx.store._knowledge_rows("SnapshotReference"))


def test_search_labels_derived_text_and_analysis_renders_original_evidence(ctx, derived_graph, monkeypatch):
    from fastapi.testclient import TestClient

    from hippo import ask, mcp_server
    from hippo.knowledge.replay import view_fingerprint
    from hippo.web.adhoc import remember_adhoc
    from hippo.web.app import create_app

    index, trace = derived_graph
    trace.evidence_fingerprint = view_fingerprint(index)
    monkeypatch.setattr(ctx, "graph_for", lambda *a, **kw: index)
    monkeypatch.setattr(ask, "_search", lambda *a, **kw: trace)
    result = mcp_server.search_tool(ctx, trace.question)
    assert result["passages"][0]["is_derived"] is True
    assert result["passages"][0]["citation_ids"] == ("span-a", "span-b")
    assert [row["id"] for row in result["citations"]] == ["span-a", "span-b"]
    key = remember_adhoc(trace, {"answer": "original evidence", "thought": ""})
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        response = client.get("/analyze", params={"key": key})
    assert response.status_code == 200
    assert "Derived retrieval text" in response.text
    assert "Original evidence" in response.text
    assert "def original(): pass" in response.text
    assert "original.py, lines 1" in response.text
