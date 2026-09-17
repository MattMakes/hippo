"""Bounded full-text evidence selected for code answers."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from hippo.ask import _answer_from_trace
from hippo.hipporag.answer_context import select_answer_passage_ids
from hippo.hipporag.graph_index import CodeNode, DirectedEdge, GraphIndex, Passage, build_igraph
from hippo.hipporag.retriever import DENSE, RankedPassage, SeedSymbol, Trace
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.citations import OriginalCitation, RetrievalEvidence
from hippo.knowledge.identity import text_hash
from hippo.knowledge.query_access import AuthorizedModel


def _ranked(passage_id: str, rank: int, *, via_expand: bool = False) -> RankedPassage:
    return RankedPassage(
        passage_id=passage_id,
        rank=rank,
        score=1.0 / rank,
        dpr_rank=rank,
        dpr_score=1.0 / rank,
        title=passage_id,
        source_id="source",
        source_name="source",
        preview=passage_id,
        via_expand=via_expand,
    )


def _trace(
    passages: list[str],
    seeds: list[SeedSymbol] | None = None,
    *,
    qa_top_k: int = 1,
    code_expand_max: int = 10,
    code_theta: float = 0.5,
) -> Trace:
    trace = Trace(
        question="How does Service.run work?",
        settings={
            "qa_top_k": qa_top_k,
            "code_expand_max": code_expand_max,
            "code_theta": code_theta,
        },
        graph_version=1,
    )
    trace.passages = [_ranked(identity, rank + 1) for rank, identity in enumerate(passages)]
    trace.seed_symbols = seeds or []
    trace.used_code_seeds = any(
        seed.kept and not seed.ambiguous and seed.how != DENSE for seed in trace.seed_symbols
    )
    return trace


def _seed(node_id: str, vertex: int, **changes) -> SeedSymbol:
    fields = dict(
        node_id=node_id,
        name=node_id,
        vertex=vertex,
        weight=1.0,
        how="identifier",
        token=node_id,
        kind="symbol",
        matched_by=node_id,
        kept=True,
    )
    fields.update(changes)
    return SeedSymbol(**fields)


def _graph(
    nodes: list[CodeNode],
    passages: list[Passage],
    relations: list[tuple[str, str, str, float]] | None = None,
) -> GraphIndex:
    node_ids = [node.id for node in nodes] + [passage.id for passage in passages]
    idx_of = {identity: vertex for vertex, identity in enumerate(node_ids)}
    code_out: dict[int, list[DirectedEdge]] = {}
    code_in: dict[int, list[DirectedEdge]] = {}

    def edge(source: str, target: str, kind: str, omega: float) -> None:
        directed = DirectedEdge(idx_of[source], idx_of[target], kind, omega, "synthetic")
        code_out.setdefault(directed.src, []).append(directed)
        code_in.setdefault(directed.dst, []).append(directed)

    for source, target, kind, omega in relations or []:
        edge(source, target, kind, omega)
    passage_by_symbol = {passage.title: passage.id for passage in passages if passage.title in idx_of}
    for symbol_id, passage_id in passage_by_symbol.items():
        edge(symbol_id, passage_id, "DEFINED_IN", 1.0)

    return GraphIndex(
        version=1,
        node_ids=node_ids,
        node_kind=[node.kind for node in nodes] + ["passage"] * len(passages),
        idx_of=idx_of,
        entity_names={},
        entity_boost=np.ones(len(node_ids)),
        specificity=np.ones(len(node_ids)),
        passages=passages,
        passage_vertices=np.arange(len(nodes), len(node_ids), dtype=np.int64),
        passage_embeddings=np.ones((len(passages), 1), dtype=np.float32),
        facts=[],
        fact_embeddings=np.zeros((0, 0), dtype=np.float32),
        fact_index_of={},
        graph=build_igraph(len(node_ids), {}),
        code_nodes=nodes,
        code_vertices=np.arange(len(nodes), dtype=np.int64),
        code_out=code_out,
        code_in=code_in,
    )


def _node(identity: str, *, name: str | None = None, code_kind: str = "method") -> CodeNode:
    return CodeNode(
        id=identity,
        kind="symbol",
        name=name or identity.rsplit(".", 1)[-1],
        qualname=identity,
        code_kind=code_kind,
        path="public.py",
        source_id="source",
    )


def _passage(identity: str, text: str | None = None) -> Passage:
    return Passage(f"passage-{identity}", identity, text or f"source for {identity}", "source", "", 0)


def _with_lineage(
    graph: GraphIndex,
    lineage: list[tuple[str, list[tuple[str, str]]]],
) -> GraphIndex:
    graph.managed_passage_ids = frozenset(passage_id for passage_id, _originals in lineage)
    graph.retrieval_evidence = tuple(
        RetrievalEvidence(
            passage_id,
            "generation",
            f"view-{index}",
            tuple(identity for identity, _text in originals),
        )
        for index, (passage_id, originals) in enumerate(lineage)
    )
    unique_originals = {
        identity: text for _passage_id, originals in lineage for identity, text in originals
    }
    graph.original_citations = tuple(
        OriginalCitation(
            id=identity,
            span_id=identity,
            revision_id="revision",
            artifact_id="artifact",
            text=text,
            title="public.py",
            source_id="source",
            text_hash=text_hash(text),
        )
        for identity, text in unique_originals.items()
    )
    return graph


def test_base_slice_is_unchanged_and_code_extras_require_lexical_seeds() -> None:
    passages = [
        Passage("base-a", "A", "alpha", "source", "", 0),
        Passage("expanded", "Expanded", "not base evidence", "source", "", 1),
        Passage("base-b", "B", "bravo", "source", "", 2),
    ]
    graph = _graph([], passages)
    trace = _trace(["base-a", "expanded", "missing", "base-b"], qa_top_k=2)
    trace.passages[1].via_expand = True

    assert select_answer_passage_ids(graph, trace) == ["base-a"]

    trace.seed_symbols = [_seed("not-present", -1, how=DENSE)]
    trace.used_code_seeds = False
    assert select_answer_passage_ids(graph, trace) == ["base-a"]


def test_two_hop_callees_and_containing_type_initializer_are_selected_without_broadening() -> None:
    identities = [
        "module",
        "Service",
        "Service.run",
        "Service.__init__",
        "Service.sibling",
        "module.new",
        "first",
        "second",
        "third",
        "caller",
        "uncertain",
    ]
    nodes = [
        _node(identity, code_kind="module" if identity == "module" else "class" if identity == "Service" else "method")
        for identity in identities
    ]
    passages = [Passage("base", "Base", "ranked", "source", "", 0)] + [
        _passage(identity) for identity in identities
    ]
    relations = [
        ("module", "Service", "CONTAINS", 1.0),
        ("module", "module.new", "CONTAINS", 1.0),
        ("Service", "Service.run", "CONTAINS", 1.0),
        ("Service", "Service.__init__", "CONTAINS", 1.0),
        ("Service", "Service.sibling", "CONTAINS", 1.0),
        ("Service.run", "first", "INVOKES", 0.9),
        ("first", "second", "INVOKES", 0.5),
        ("second", "Service.run", "INVOKES", 1.0),
        ("second", "third", "INVOKES", 1.0),
        ("caller", "Service.run", "INVOKES", 1.0),
        ("Service.run", "uncertain", "INVOKES", 0.49),
    ]
    graph = _graph(nodes, passages, relations)
    trace = _trace(["base"], [_seed("Service.run", graph.idx_of["Service.run"])])

    assert select_answer_passage_ids(graph, trace) == [
        "base",
        "passage-Service.run",
        "passage-Service.__init__",
        "passage-first",
        "passage-second",
    ]


def test_only_kept_unambiguous_lexical_symbol_seeds_add_context() -> None:
    nodes = [_node(name) for name in ("kept", "dense", "ambiguous", "dropped", "data")]
    nodes[-1] = replace(nodes[-1], kind="data", code_kind="table")
    passages = [Passage("base", "Base", "ranked", "source", "", 0)] + [
        _passage(node.id) for node in nodes
    ]
    graph = _graph(nodes, passages)
    seeds = [
        _seed("kept", graph.idx_of["kept"]),
        _seed("dense", graph.idx_of["dense"], how=DENSE),
        _seed("ambiguous", graph.idx_of["ambiguous"], ambiguous=True),
        _seed("dropped", graph.idx_of["dropped"], kept=False),
        _seed("data", graph.idx_of["data"], kind="data"),
        _seed("hidden", 999),
        _seed("wrong-node", graph.idx_of["kept"]),
    ]

    assert select_answer_passage_ids(graph, _trace(["base"], seeds)) == ["base", "passage-kept"]


def test_extra_entry_and_character_limits_skip_whole_passages() -> None:
    nodes = [_node(f"seed{index}") for index in range(12)]
    passages = [Passage("base", "Base", "ranked", "source", "", 0)] + [
        _passage(node.id, "x" * (6001 if index == 0 else 6000 if index == 1 else 1))
        for index, node in enumerate(nodes)
    ]
    graph = _graph(nodes, passages)
    seeds = [_seed(node.id, graph.idx_of[node.id]) for node in nodes]

    assert select_answer_passage_ids(graph, _trace(["base"], seeds, code_expand_max=0)) == ["base"]
    selected = select_answer_passage_ids(graph, _trace(["base"], seeds, code_expand_max=20))
    assert selected == ["base", "passage-seed1"]

    compact = [replace(passage, text="x") if passage.id != "base" else passage for passage in passages]
    compact_graph = _graph(nodes, compact)
    selected = select_answer_passage_ids(compact_graph, _trace(["base"], seeds, code_expand_max=20))
    assert selected[1:] == [f"passage-seed{index}" for index in range(10)]


def test_symbol_visit_bound_and_passage_deduplication() -> None:
    nodes = [_node(f"n{index:02}") for index in range(70)]
    shared = Passage("shared", "n00", "same source", "source", "", 0)
    passages = [
        Passage("base", "Base", "ranked", "source", "", 0),
        shared,
        _passage("n63"),
        _passage("n64"),
    ]
    relations = [(f"n{index:02}", f"n{index + 1:02}", "INVOKES", 1.0) for index in range(69)]
    relations += [("n02", "n00", "INVOKES", 1.0), ("n00", "n01", "INVOKES", 1.0)]
    graph = _graph(nodes, passages, relations)
    trace = _trace(
        ["base", "shared"],
        [_seed(node.id, graph.idx_of[node.id]) for node in nodes],
        qa_top_k=2,
        code_expand_max=10,
    )

    first = select_answer_passage_ids(graph, trace)
    second = select_answer_passage_ids(graph, trace)
    assert first == second
    assert first[:2] == ["base", "shared"]
    assert first[2:] == ["passage-n63"]
    assert "passage-n64" not in first
    assert len(first) == len(set(first))


def test_one_seed_cycle_terminates_and_sorts_outgoing_edges() -> None:
    nodes = [_node(identity) for identity in ("seed", "a-target", "b-target")]
    passages = [Passage("base", "Base", "ranked", "source", "", 0)] + [
        _passage(node.id) for node in nodes
    ]
    graph = _graph(
        nodes,
        passages,
        [
            ("seed", "b-target", "INVOKES", 1.0),
            ("seed", "a-target", "INVOKES", 1.0),
            ("a-target", "seed", "INVOKES", 1.0),
            ("b-target", "seed", "INVOKES", 1.0),
        ],
    )
    trace = _trace(["base"], [_seed("seed", graph.idx_of["seed"])])

    expected = ["base", "passage-seed", "passage-a-target", "passage-b-target"]
    assert select_answer_passage_ids(graph, trace) == expected
    assert select_answer_passage_ids(graph, trace) == expected
    assert len(expected) == len(set(expected))


def test_answer_resolves_base_and_supplemental_retrieval_ids_to_original_citations() -> None:
    nodes = [_node("Service.run"), _node("helper")]
    passages = [_passage("Service.run", "rendered run"), _passage("helper", "rendered helper")]
    graph = _graph(nodes, passages, [("Service.run", "helper", "INVOKES", 1.0)])
    graph.managed_passage_ids = frozenset(passage.id for passage in passages)
    graph.retrieval_evidence = tuple(
        RetrievalEvidence(passage.id, "generation", f"view-{index}", (f"span-{index}",))
        for index, passage in enumerate(passages)
    )
    graph.original_citations = tuple(
        OriginalCitation(
            id=f"span-{index}",
            span_id=f"span-{index}",
            revision_id="revision",
            artifact_id="artifact",
            text=f"original source {index}",
            title="public.py",
            source_id="source",
            text_hash=text_hash(f"original source {index}"),
        )
        for index in range(2)
    )
    trace = _trace(
        ["passage-Service.run"],
        [_seed("Service.run", graph.idx_of["Service.run"])],
    )
    seen: list[dict[str, str]] = []

    def chat(messages, **_kwargs):
        seen.extend(messages)
        return "Answer: grounded"

    answer = _answer_from_trace(graph, SimpleNamespace(chat_text=chat), trace)
    assert answer.passage_ids == ["span-0", "span-1"]
    assert answer.retrieval_passage_ids == ["passage-Service.run", "passage-helper"]
    assert "original source 0" in str(seen) and "original source 1" in str(seen)
    assert "rendered" not in str(seen)


@pytest.mark.parametrize(
    "supplemental_texts",
    [
        ["x" * 6001],
        [f"original {index}" for index in range(11)],
    ],
    ids=["over-character-limit", "over-citation-limit"],
)
def test_answer_skips_supplemental_groups_that_exceed_resolved_original_limits(
    supplemental_texts: list[str],
) -> None:
    nodes = [_node("Service.run"), _node("helper")]
    passages = [_passage("Service.run", "rendered run"), _passage("helper", "x")]
    graph = _graph(nodes, passages, [("Service.run", "helper", "INVOKES", 1.0)])
    graph.managed_passage_ids = frozenset(passage.id for passage in passages)
    supplemental_ids = tuple(f"supplemental-{index}" for index in range(len(supplemental_texts)))
    graph.retrieval_evidence = (
        RetrievalEvidence("passage-Service.run", "generation", "base-view", ("base-original",)),
        RetrievalEvidence("passage-helper", "generation", "helper-view", supplemental_ids),
    )
    originals = [("base-original", "base source"), *zip(supplemental_ids, supplemental_texts, strict=True)]
    graph.original_citations = tuple(
        OriginalCitation(
            id=identity,
            span_id=identity,
            revision_id="revision",
            artifact_id="artifact",
            text=text,
            title="public.py",
            source_id="source",
            text_hash=text_hash(text),
        )
        for identity, text in originals
    )
    trace = _trace(
        ["passage-Service.run"],
        [_seed("Service.run", graph.idx_of["Service.run"])],
    )
    seen: list[dict[str, str]] = []

    def chat(messages, **_kwargs):
        seen.extend(messages)
        return "Answer: grounded"

    answer = _answer_from_trace(graph, SimpleNamespace(chat_text=chat), trace)

    assert answer.retrieval_passage_ids == ["passage-Service.run"]
    assert answer.passage_ids == ["base-original"]
    assert "base source" in str(seen)
    assert not any(text in str(seen) for text in supplemental_texts)


def test_resolved_original_limits_include_exact_boundary_and_leave_large_base_intact() -> None:
    nodes = [_node("Service.run"), _node("helper")]
    passages = [_passage("Service.run", "rendered run"), _passage("helper", "x")]
    graph = _graph(nodes, passages, [("Service.run", "helper", "INVOKES", 1.0)])
    supplemental = [(f"supplemental-{index}", "x" * 600) for index in range(10)]
    _with_lineage(
        graph,
        [
            ("passage-Service.run", [("base-original", "b" * 6001)]),
            ("passage-helper", supplemental),
        ],
    )
    trace = _trace(
        ["passage-Service.run"],
        [_seed("Service.run", graph.idx_of["Service.run"])],
        code_expand_max=10,
    )

    answer = _answer_from_trace(
        graph, SimpleNamespace(chat_text=lambda *_args, **_kwargs: "Answer: grounded"), trace
    )

    assert answer.retrieval_passage_ids == ["passage-Service.run", "passage-helper"]
    assert answer.passage_ids == ["base-original", *[identity for identity, _text in supplemental]]

    trace.settings["code_expand_max"] = 0
    base_only = _answer_from_trace(
        graph, SimpleNamespace(chat_text=lambda *_args, **_kwargs: "Answer: grounded"), trace
    )
    assert base_only.retrieval_passage_ids == ["passage-Service.run"]
    assert base_only.passage_ids == ["base-original"]


def test_skipped_group_does_not_block_later_groups_or_control_citation_order() -> None:
    nodes = [_node(identity) for identity in ("seed", "a-large", "b-small", "c-reuse")]
    passages = [_passage(node.id, "x") for node in nodes]
    graph = _graph(
        nodes,
        passages,
        [
            ("seed", "a-large", "INVOKES", 1.0),
            ("seed", "b-small", "INVOKES", 1.0),
            ("seed", "c-reuse", "INVOKES", 1.0),
        ],
    )
    _with_lineage(
        graph,
        [
            ("passage-seed", [("base-original", "base")]),
            ("passage-a-large", [("reused-later", "r"), ("too-large", "x" * 6001)]),
            ("passage-b-small", [("small-original", "s")]),
            ("passage-c-reuse", [("reused-later", "r")]),
        ],
    )
    trace = _trace(["passage-seed"], [_seed("seed", graph.idx_of["seed"])])
    seen: list[dict[str, str]] = []

    def chat(messages, **_kwargs):
        seen.extend(messages)
        return "Answer: grounded"

    answer = _answer_from_trace(graph, SimpleNamespace(chat_text=chat), trace)

    assert answer.retrieval_passage_ids == ["passage-seed", "passage-b-small", "passage-c-reuse"]
    assert answer.passage_ids == ["base-original", "small-original", "reused-later"]
    qa_content = seen[-1]["content"]
    assert "Title: public.py\nbase\n\nTitle: public.py\ns\n\nTitle: public.py\nr" in qa_content
    assert "x" * 6001 not in qa_content


def test_original_shared_with_base_costs_zero_supplemental_entries() -> None:
    nodes = [_node("Service.run"), _node("helper")]
    passages = [_passage("Service.run", "rendered run"), _passage("helper", "x")]
    graph = _graph(nodes, passages, [("Service.run", "helper", "INVOKES", 1.0)])
    novel = [(f"novel-{index}", "x") for index in range(10)]
    _with_lineage(
        graph,
        [
            ("passage-Service.run", [("shared", "shared")]),
            ("passage-helper", [("shared", "shared"), *novel]),
        ],
    )
    trace = _trace(
        ["passage-Service.run"],
        [_seed("Service.run", graph.idx_of["Service.run"])],
        code_expand_max=10,
    )

    answer = _answer_from_trace(
        graph, SimpleNamespace(chat_text=lambda *_args, **_kwargs: "Answer: grounded"), trace
    )

    assert answer.retrieval_passage_ids == ["passage-Service.run", "passage-helper"]
    assert answer.passage_ids == ["shared", *[identity for identity, _text in novel]]


def test_revocation_after_answer_model_call_prevents_result_release() -> None:
    passages = [Passage("base", "Base", "public evidence", "source", "", 0)]
    graph = _graph([], passages)
    trace = _trace(["base"])
    revoked = False

    def validate() -> None:
        if revoked:
            raise AuthorizationChanged("evidence was revoked")

    def chat(*_args, **_kwargs):
        nonlocal revoked
        revoked = True
        return "Answer: stale"

    with pytest.raises(AuthorizationChanged):
        _answer_from_trace(graph, AuthorizedModel(SimpleNamespace(chat_text=chat), validate), trace)
