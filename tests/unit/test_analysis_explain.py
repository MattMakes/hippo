"""explain(): the why-sentences, paths and subgraph for a real search over the sample corpus."""

from __future__ import annotations

import json

import pytest

from hippo.analysis.explain import MAX_PATH_HOPS, Explanation, explain
from hippo.ask import search
from hippo.hipporag.indexer import Chunk, index_source
from hippo.hipporag.retriever import Retriever, Trace

QUESTION = "In which state is the company founded by Priya Natarajan headquartered?"


def index_sample(ctx, sample_text: str) -> str:
    """Index samples/acme_robotics.md as one passage per '## ' section. Returns the source id."""
    source_id = ctx.store.create_source("sample", "Acme Robotics")
    chunks = []
    for ordinal, section in enumerate(sample_text.split("## ")[1:]):
        title, _, body = section.partition("\n")
        chunks.append(Chunk(ordinal, title.strip(), body.strip()))
    index_source(ctx.store, ctx.ollama, source_id, chunks, workers=2)
    ctx.store.update_source(source_id, status="ready")
    return source_id


@pytest.fixture
def trace(ctx, sample_text) -> Trace:
    index_sample(ctx, sample_text)
    return search(ctx, QUESTION)


def test_every_top_passage_gets_a_why_sentence(ctx, trace):
    assert not trace.used_dpr_fallback  # the fake filter keeps facts for this question
    explanation = explain(ctx.graph(), trace)
    assert isinstance(explanation, Explanation)
    assert len(explanation.passages) == min(10, len(trace.passages))

    for ranked, explained in zip(trace.passages, explanation.passages, strict=False):
        assert explained.passage_id == ranked.passage_id
        assert explained.rank == ranked.rank
        assert explained.title == ranked.title
        assert explained.why.endswith(".")
        # Either the passage mentions a seed, or we found a short path, or we say why not.
        if explained.linked_seeds:
            assert explained.why.startswith("Directly mentions seed")
            assert not explained.path
        elif explained.path:
            assert explained.why.startswith("Reached in")
            assert 2 <= len(explained.path) <= MAX_PATH_HOPS + 1
            assert explained.path[-1] == ranked.title
        else:
            assert "No seed reaches" in explained.why


def test_top_passage_directly_mentions_the_strongest_seed(ctx, trace):
    explanation = explain(ctx.graph(), trace)
    first = explanation.passages[0]
    assert first.title == "The company"
    seed_names = {s["name"] for s in first.linked_seeds}
    assert {"acme robotics", "priya natarajan"} <= seed_names
    strongest = max(trace.seed_entities, key=lambda s: s.weight)
    assert f"'{first.linked_seeds[0]['name']}'" in first.why
    assert first.linked_seeds[0]["seed_weight"] == pytest.approx(strongest.weight)
    assert all(s["edge_weight"] > 0 for s in first.linked_seeds)


def test_path_is_used_when_no_seed_is_mentioned(ctx, trace):
    # "The Lyra gripper" mentions no seed. The strongest seed is 'denver'; passages are graph
    # nodes too, so the shortest path runs through the "Where things are" passage and Hana Sato.
    explanation = explain(ctx.graph(), trace)
    lyra = next(p for p in explanation.passages if p.title == "The Lyra gripper")
    assert lyra.linked_seeds == []
    assert lyra.path == ["denver", "Where things are", "hana sato", "The Lyra gripper"]
    assert lyra.why == "Reached in 3 hops from seed 'denver' via 'Where things are' -> 'hana sato'."

    customers = next(p for p in explanation.passages if p.title == "Customers")
    assert customers.path == ["denver", "colorado", "Customers"]
    assert customers.why == "Reached in 2 hops from seed 'denver' via 'colorado'."

    # "Suppliers" is further away than 3 hops from every seed.
    suppliers = next(p for p in explanation.passages if p.title == "Suppliers")
    assert suppliers.linked_seeds == [] and suppliers.path == []
    assert suppliers.why.startswith("No seed reaches this passage within 3 hops")
    assert f"embedding rank {suppliers.dpr_rank}" in suppliers.why


def test_subgraph_has_seeds_top_nodes_passages_and_only_real_edges(ctx, trace):
    index = ctx.graph()
    explanation = explain(index, trace, top_passages=5)
    nodes = {n["id"]: n for n in explanation.subgraph["nodes"]}
    edges = explanation.subgraph["edges"]

    for seed in trace.seed_entities:
        assert nodes[seed.entity_id]["is_seed"] == seed.kept
        assert nodes[seed.entity_id]["seed_weight"] == pytest.approx(seed.weight)
        assert nodes[seed.entity_id]["kind"] == "entity"
    for top in trace.top_nodes:
        assert top.node_id in nodes
        assert nodes[top.node_id]["score"] >= top.score - 1e-12
    for ranked in trace.passages[:5]:
        assert nodes[ranked.passage_id]["rank"] == ranked.rank
        assert nodes[ranked.passage_id]["kind"] == "passage"
    assert all(n["rank"] is None for n in nodes.values() if n["kind"] == "entity")

    assert edges, "seeds and the passages that mention them must be connected"
    seen = set()
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        real = index.edge_between(index.idx_of[edge["source"]], index.idx_of[edge["target"]])
        assert real is not None and real.weight == pytest.approx(edge["weight"])
        assert edge["kinds"] == real.kinds
        key = frozenset((edge["source"], edge["target"]))
        assert key not in seen, "each undirected edge is listed once"
        seen.add(key)


def test_facts_carry_passage_titles_and_everything_is_json_safe(ctx, trace):
    explanation = explain(ctx.graph(), trace)
    assert len(explanation.facts) == len(trace.fact_candidates)
    for fact in explanation.facts:
        assert fact["triple"] and fact["reason"]
        assert [p["passage_id"] for p in fact["passages"]] == fact["passage_ids"]
        assert all(p["title"] for p in fact["passages"])
    json.dumps(explanation.to_dict())  # must not raise


def test_explain_a_fallback_trace(ctx, trace):
    # Force the DPR fallback by keeping no facts at all.
    fallback = Retriever(ctx.graph(), ctx.ollama).retrieve(
        QUESTION, trace.settings, fact_filter=lambda q, c: ([], "nothing")
    )
    assert fallback.used_dpr_fallback
    explanation = explain(ctx.graph(), fallback)
    assert explanation.passages
    for p in explanation.passages:
        assert p.linked_seeds == [] and p.path == []
        assert "similarity" in p.why and fallback.fallback_reason in p.why
    assert explanation.subgraph["nodes"]  # the passages themselves are still drawn
    assert not any(n["is_seed"] for n in explanation.subgraph["nodes"])


def test_explain_uses_an_edited_graph_when_given(ctx, trace):
    from hippo.hipporag.graph_index import EdgeEdit

    index = ctx.graph()
    first = explain(index, trace).passages[0]
    seed_id = first.linked_seeds[0]["entity_id"]
    edited = index.graph_with_edits([EdgeEdit(seed_id, first.passage_id, 0.0)])
    after = explain(index, trace, graph=edited).passages[0]
    assert seed_id not in {s["entity_id"] for s in after.linked_seeds}


# ------------------------------------------ the graph changed since the trace


def test_explain_ignores_the_vertex_numbers_recorded_in_the_trace(ctx, trace):
    # Vertex numbers are positions in the graph *as it was*; only ids are stable. A trace whose
    # numbers are all nonsense must explain exactly like the original.
    from hippo.hipporag.retriever import trace_from_dict

    index = ctx.graph()
    scrambled = trace_from_dict(trace.to_dict())
    for seed in scrambled.seed_entities:
        seed.vertex = 999_999
    for top in scrambled.top_nodes:
        top.vertex = 999_999
    for seed_passage in scrambled.seed_passages:
        seed_passage.vertex = 999_999

    assert explain(index, scrambled).to_dict() == explain(index, trace).to_dict()


def test_explain_after_a_source_was_deleted_skips_the_missing_seed_and_says_so(store, ollama, sample_text):
    from hippo.hipporag.graph_index import GraphIndex
    from hippo.hipporag.retriever import Retriever
    from hippo.store.base import DEFAULT_SETTINGS

    # Index the extra source *first* so its entities get the low vertex numbers: once it is
    # deleted, every sample vertex number in the old trace points past the end of the graph.
    extra = store.create_source("text", "Extra")
    index_source(store, ollama, extra, [Chunk(0, "Priya's studies", "Priya Natarajan studied at Stanford.")])
    index_sample_into(store, ollama, sample_text)
    old_index = GraphIndex.load(store)
    keep_all = lambda question, candidates: (candidates, "kept all")  # noqa: E731
    old_trace = Retriever(old_index, ollama).retrieve(
        QUESTION, {**DEFAULT_SETTINGS, "linking_top_k": 50}, fact_filter=keep_all
    )
    seeds = {s.name: s for s in old_trace.seed_entities if s.kept and s.weight > 0}
    assert {"stanford", "priya natarajan", "acme robotics"} <= set(seeds)  # only 'stanford' will vanish

    store.delete_source(extra)
    new_index = GraphIndex.load(store)
    assert new_index.num_nodes < old_index.num_nodes
    # Some recorded vertex numbers now point past the end of the graph, others at different nodes.
    assert any(top.vertex >= new_index.num_nodes for top in old_trace.top_nodes)
    assert seeds["acme robotics"].vertex != new_index.idx_of[seeds["acme robotics"].entity_id]

    explanation = explain(new_index, old_trace)  # must not raise

    node_ids = {n["id"] for n in explanation.subgraph["nodes"]}
    assert seeds["stanford"].entity_id not in node_ids
    assert seeds["priya natarajan"].entity_id in node_ids
    assert all(node_id in new_index.idx_of for node_id in node_ids)
    for edge in explanation.subgraph["edges"]:
        assert new_index.edge_between(new_index.idx_of[edge["source"]], new_index.idx_of[edge["target"]])
    company = next(p for p in explanation.passages if p.title == "The company")
    assert "priya natarajan" in {s["name"] for s in company.linked_seeds}
    assert "stanford" not in {s["name"] for s in company.linked_seeds}
    for p in explanation.passages:
        assert p.why.endswith(".")
        if p.title == "Priya's studies":  # the deleted source's own passage
            assert p.why == "This passage is no longer in the graph."
        else:
            assert "Seed 'stanford' is no longer in the graph and was ignored." in p.why
    json.dumps(explanation.to_dict())


def index_sample_into(store, ollama, sample_text: str) -> str:
    source_id = store.create_source("sample", "Acme Robotics")
    chunks = []
    for ordinal, section in enumerate(sample_text.split("## ")[1:]):
        title, _, body = section.partition("\n")
        chunks.append(Chunk(ordinal, title.strip(), body.strip()))
    index_source(store, ollama, source_id, chunks, workers=2)
    return source_id
