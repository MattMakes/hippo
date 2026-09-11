"""Managed projections reconstruct evidence instead of filtering native secrets."""

import importlib
import json
from copy import deepcopy
from dataclasses import asdict

import numpy as np
import pytest

from hippo.hipporag.graph_index import CodeNode, DirectedEdge, Edge, GraphIndex, Passage, build_igraph
from hippo.knowledge import model as k
from hippo.knowledge.access import EvidenceSelection
from tests.unit.test_evidence_access import NOW, engine, observation, policy, span, world


def api():
    try:
        return importlib.import_module("hippo.knowledge.projection")
    except ModuleNotFoundError:
        pytest.fail("Managed evidence projection is missing")


def fixture():
    w = world()
    w.store.knowledge_backend = "fake"
    w.store.passages = {}
    w.generation = w.store.add(
        k.Generation(
            source_id="s",
            status="active",
            parser_version="p",
            linker_version="l",
            embedding_profile="embed-v1",
            created_at=NOW,
            published_at=NOW,
            manifest_hash="h",
        )
    )
    w.source["active_generation_id"] = w.generation.id
    w.store.add(k.GenerationMember(generation_id=w.generation.id, artifact_revision_id=w.revision.id))
    w.objects, w.spans, w.nodes, w.passages = [], [], [], []
    for name in ("first", "second"):
        obj, observed, evidence = observation(w, name, kind="symbol")
        w.store.records["ObjectObservation"].pop(observed.id)
        w.store.add(
            observed.replace(
                attributes_json=json.dumps(
                    {
                        "name": name,
                        "qualname": name,
                        "path": "public.py",
                        "signature": name + "()",
                        "doc": "Public documentation",
                    }
                )
            )
        )
        native = "native-" + name
        w.store.native[("Symbol", native)] = {"source_id": "s"}
        w.store.add(
            k.NativeBinding(
                generation_id=w.generation.id,
                object_id=obj.id,
                native_kind="Symbol",
                native_id=native,
                span_id=evidence.id,
            )
        )
        w.objects.append(obj)
        w.spans.append(evidence)
        w.nodes.append(
            CodeNode(
                native,
                "symbol",
                "SECRET-" + name,
                path="secret.py",
                doc="SECRET native body",
                community=42,
                in_degree=999,
                source_id="s",
            )
        )
        passage = Passage("passage-" + name, "SECRET title", evidence.text, "s", "SECRET source label", 999)
        w.passages.append(passage)
        w.store.passages[passage.id] = dict(
            id=passage.id,
            source_id="s",
            text=evidence.text,
            span_id=evidence.id,
            artifact_revision_id=w.revision.id,
            generation_id=w.generation.id,
            embedding_profile="embed-v1",
            embedding=[1.0, 0.0],
        )
    w.selection = EvidenceSelection(generation_ids=frozenset({w.generation.id}))
    w.full = graph(w.nodes, w.passages)
    return w


def graph(nodes, passages):
    ids = [n.id for n in nodes] + [p.id for p in passages]
    edges = (
        {(0, 1): Edge(omega=99, synonym_score=99, tuned=99, code_kinds=["SECRET"])} if len(nodes) > 1 else {}
    )
    return GraphIndex(
        version=999,
        node_ids=ids,
        node_kind=[n.kind for n in nodes] + ["passage"] * len(passages),
        idx_of={identity: i for i, identity in enumerate(ids)},
        entity_names={},
        entity_boost=np.full(len(ids), 99.0),
        specificity=np.full(len(ids), 999.0),
        passages=passages,
        passage_vertices=np.arange(len(nodes), len(ids)),
        passage_embeddings=np.array([[1.0, 0.0]] * len(passages), dtype=np.float32).reshape((-1, 2)),
        facts=[],
        fact_embeddings=np.zeros((0, 0), dtype=np.float32),
        fact_index_of={},
        graph=build_igraph(len(ids), edges),
        edges=edges,
        code_nodes=nodes,
        code_vertices=np.arange(len(nodes)),
        code_out={0: [DirectedEdge(0, 1, "BOUND_TO", 99, "SECRET", {"secret": "value"})]}
        if len(nodes) > 1
        else {},
        name_index={"SECRET": [n.id for n in nodes]},
        path_index={"secret.py": [n.id for n in nodes]},
        communities={42: "SECRET"},
        display_cache={0: "SECRET"},
    )


def projected(w):
    return api().project_managed_graph(
        w.full, w.store, engine(w).build(w.selection), embedding_profile="embed-v1"
    )


def assertion(w, *, private=False, predicate="BOUND_TO"):
    relation = w.store.add(k.checked_assertion(w.objects[0], predicate, w.objects[1], scope_key="prod"))
    version = w.store.add(
        k.AssertionVersion(
            assertion_id=relation.id,
            evidence_class="declared",
            rule_version="rule",
            confidence=0.8,
            status="active",
            recorded_from=NOW,
        )
    )
    evidence = span(w, "private-map", policy(w)) if private else w.spans[0]
    w.store.add(
        k.AssertionSupport(
            assertion_version_id=version.id, span_id=evidence.id, derivation_group="declaration"
        )
    )
    return version


def test_private_relationship_between_public_endpoints_is_not_projected():
    api()
    w = fixture()
    assertion(w, private=True)
    result = projected(w)
    a, b = (result.idx_of[obj.id] for obj in w.objects)
    assert result.edge_between(a, b) is None
    assert not any(edge.dst == b for edge in result.out_edges(a))


def test_labels_bodies_and_indexes_are_rebuilt_from_allowed_observations():
    api()
    w = fixture()
    hidden = span(w, "private-attributes", policy(w))
    w.store.add(
        k.ObjectObservation(
            object_id=w.objects[0].id,
            revision_id=w.revision.id,
            span_id=hidden.id,
            attributes_json='{"name":"PRIVATE OWNER","doc":"SECRET private body"}',
            evidence_class="declared",
            recorded_from=NOW,
        )
    )
    result = projected(w)
    node = result.code_node_by_id(w.objects[0].id)
    assert node.name == "first" and node.path == "public.py"
    assert node.doc == "Public documentation"
    assert result.passage_by_id(w.spans[0].id).text == "first"
    assert "SECRET" not in repr(result)
    assert "PRIVATE OWNER" not in repr(result)
    assert set(result.path_index) == {"public.py"}
    assert result.entity_boost.tolist() == [1.0] * len(result.node_ids)
    assert not result.display_cache and not result._scaled
    assert all(node.in_degree == 0 for node in result.code_nodes)


def test_supported_registered_relationship_is_recreated_with_its_proof():
    api()
    w = fixture()
    version = assertion(w)
    result = projected(w)
    a, b = (result.idx_of[obj.id] for obj in w.objects)
    edge = result.edge_between(a, b)
    assert edge.weight == 0.8 and edge.tuned is None and edge.synonym_score == 0
    arrow = next(edge for edge in result.out_edges(a) if edge.dst == b)
    assert arrow.kind == "BOUND_TO" and arrow.extra["assertion_version_id"] == version.id
    assert arrow.extra["support_span_ids"] == [w.spans[0].id]


@pytest.mark.parametrize(
    "change",
    [
        "no_selection",
        "retired_generation",
        "changed_pointer",
        "unselected_binding",
        "unbound_passage",
        "wrong_text",
        "wrong_profile",
        "stale_vector",
    ],
)
def test_current_generation_and_embedding_bindings_fail_closed(change):
    module = api()
    w = fixture()
    if change == "no_selection":
        with pytest.raises(module.ProjectionError):
            module.project_managed_graph(w.full, w.store, engine(w).build(), embedding_profile="embed-v1")
        return
    if change == "retired_generation":
        w.store.add(w.generation.replace(status="retired"))
    elif change == "changed_pointer":
        w.source["active_generation_id"] = "other"
    elif change == "unselected_binding":
        w.store.records["NativeBinding"].clear()
    elif change == "unbound_passage":
        for row in w.store.passages.values():
            row["span_id"] = None
    elif change == "wrong_text":
        for passage in w.full.passages:
            passage.text += " SECRET appended"
    elif change == "wrong_profile":
        for row in w.store.passages.values():
            row["embedding_profile"] = "old-profile"
    else:
        w.full.passage_embeddings[:] = [0, 1]
    if change in {"retired_generation", "changed_pointer"}:
        with pytest.raises(module.ProjectionError):
            projected(w)
    elif change == "unselected_binding":
        assert not projected(w).code_nodes
    else:
        assert not projected(w).passages


def test_adding_private_native_corpus_does_not_change_projected_content_or_weights():
    api()
    w = fixture()
    before = projected(w)
    w.full.version += 1
    w.full.name_index["PRIVATE-ADDITION"] = ["private"]
    w.full.communities[99] = "PRIVATE-ADDITION"
    assertion(w, private=True)
    after = projected(w)
    assert before.version == after.version
    assert before.node_ids == after.node_ids
    assert before.name_index == after.name_index
    assert before.communities == after.communities
    np.testing.assert_array_equal(before.specificity, after.specificity)
    np.testing.assert_array_equal(before.passage_embeddings, after.passage_embeddings)


def test_empty_scope_is_a_fresh_empty_graph_and_never_returns_full_input():
    api()
    w = fixture()
    w.selection = EvidenceSelection(generation_ids=frozenset())
    result = projected(w)
    assert result is not w.full and result.num_nodes == 0 and result.is_empty()
    assert not result.name_index and not result.path_index and not result.communities


def test_composition_keeps_vertex_order_and_rebuilds_lookups_without_mutating_inputs():
    module = api()
    w = fixture()
    managed = projected(w)
    legacy = graph(
        [CodeNode("legacy-symbol", "symbol", "legacy", path="legacy.py")],
        [Passage("legacy-p", "legacy", "legacy text", "legacy-source", "legacy", 0)],
    )
    old = deepcopy(legacy)
    combined = module.compose_graphs(legacy, managed)
    assert combined.node_ids[-len(combined.passages) :] == [p.id for p in combined.passages]
    assert "SECRET" not in combined.name_index and "secret.py" not in combined.path_index
    assert combined.passage_by_id("legacy-p").text == "legacy text"
    assert combined.code_node_by_id(w.objects[0].id).name == "first"
    combined.code_nodes[0].doc = "mutated copy"
    assert [asdict(node) for node in legacy.code_nodes] == [asdict(node) for node in old.code_nodes]
    assert legacy.name_index == old.name_index
    with pytest.raises(module.ProjectionError):
        module.compose_graphs(managed, managed)


def test_composing_an_empty_lane_preserves_legacy_retrieval_semantics():
    module = api()
    legacy = graph(
        [CodeNode("legacy", "symbol", "legacy", community=7, in_degree=4)],
        [Passage("p", "title", "text", "source", "source", 0)],
    )
    legacy.communities = {7: "legacy"}
    before = deepcopy(legacy)
    result = module.compose_graphs(legacy, module.compose_graphs())
    assert result.node_ids == before.node_ids
    np.testing.assert_array_equal(result.entity_boost, before.entity_boost)
    np.testing.assert_array_equal(result.specificity, before.specificity)
    np.testing.assert_array_equal(result.passage_embeddings, before.passage_embeddings)
    assert result.communities == before.communities
    assert [asdict(node) for node in result.code_nodes] == [asdict(node) for node in before.code_nodes]
    assert result.edges == before.edges


def test_conflicting_observations_do_not_create_a_synthetic_latest_object():
    api()
    w = fixture()
    w.store.add(
        k.ObjectObservation(
            object_id=w.objects[0].id,
            revision_id=w.revision.id,
            span_id=w.spans[0].id,
            attributes_json='{"name":"conflicting-name","doc":"other-doc"}',
            evidence_class="declared",
            recorded_from=NOW,
        )
    )
    node = projected(w).code_node_by_id(w.objects[0].id)
    assert node.name == "symbol" and node.doc == "" and node.path == ""


def test_closed_observations_do_not_override_current_code_attributes():
    from datetime import timedelta

    api()
    w = fixture()
    w.store.add(
        k.ObjectObservation(
            object_id=w.objects[0].id,
            revision_id=w.revision.id,
            span_id=w.spans[0].id,
            attributes_json='{"name":"closed-name"}',
            evidence_class="declared",
            recorded_from=NOW - timedelta(days=2),
            recorded_to=NOW - timedelta(days=1),
        )
    )
    assert projected(w).code_node_by_id(w.objects[0].id).name == "first"
    for observed in w.store._knowledge_rows("ObjectObservation"):
        if observed.object_id == w.objects[1].id:
            w.store.add(observed.replace(recorded_to=NOW + timedelta(seconds=1)))
    assert projected(w).code_node_by_id(w.objects[1].id) is None


def test_vector_binding_requires_the_exact_generation_revision_pair():
    api()
    w = fixture()
    # The raw passage matches selected G1, but its revision belongs only to G2.
    # An invalid/corrupt membership must not be laundered through a union of revisions.
    other = w.store.add(
        k.Generation(
            source_id="other-source",
            status="active",
            parser_version="p",
            linker_version="l",
            embedding_profile="embed-v1",
            created_at=NOW,
            published_at=NOW,
            manifest_hash="other",
        )
    )
    w.store.sources["other-source"] = {
        "id": "other-source",
        "workspace_id": w.workspace.id,
        "active_generation_id": other.id,
    }
    w.store.records["GenerationMember"].clear()
    w.store.add(k.GenerationMember(generation_id=other.id, artifact_revision_id=w.revision.id))
    w.selection = EvidenceSelection(generation_ids=frozenset({w.generation.id, other.id}))
    assert not projected(w).passages


def test_nontraversable_assertions_do_not_become_graph_edges():
    api()
    w = fixture()
    assertion(w, predicate="CONTRADICTS")
    result = projected(w)
    a, b = (result.idx_of[obj.id] for obj in w.objects)
    assert result.edge_between(a, b) is None


def test_closed_assertion_version_cannot_remain_a_current_relationship():
    from datetime import timedelta

    api()
    w = fixture()
    version = assertion(w)
    w.store.add(version.replace(recorded_to=NOW + timedelta(seconds=1)))
    result = projected(w)
    a, b = (result.idx_of[obj.id] for obj in w.objects)
    assert result.edge_between(a, b) is None


def test_persisted_passage_metadata_binds_a_real_backend_vector(store):
    from hippo.knowledge.access import AuthorizedEvidence
    from hippo.store.migrations import DEFAULT_WORKSPACE_ID

    module = api()
    store.ensure_schema()
    source = store.create_source("file", "managed-original")
    grant = k.AccessPolicy(
        workspace_id=DEFAULT_WORKSPACE_ID,
        origin="local_curated",
        scope_key="source:" + source,
        mode="workspace",
        verified_at=NOW,
    )
    artifact = k.Artifact(
        workspace_id=DEFAULT_WORKSPACE_ID,
        source_id=source,
        kind="file",
        external_id="test.py",
        canonical_uri="test.py",
        policy_id=grant.id,
    )
    revision = k.ArtifactRevision(
        artifact_id=artifact.id, content_hash="h", raw_uri="blob:h", observed_at=NOW, lifecycle="active"
    )
    evidence = k.EvidenceSpan(
        revision_id=revision.id,
        locator_kind="file_lines",
        locator_json='{"kind":"file_lines","path":"test.py","start":1,"end":1}',
        text="public original",
        policy_id=grant.id,
    )
    generation = k.Generation(
        source_id=source,
        status="active",
        parser_version="p",
        linker_version="l",
        embedding_profile="embed-v1",
        created_at=NOW,
        published_at=NOW,
        manifest_hash="h",
    )
    for record in (
        grant,
        artifact,
        revision,
        evidence,
        generation,
        k.GenerationMember(generation_id=generation.id, artifact_revision_id=revision.id),
    ):
        store._write_knowledge(record)
    store.add_passages(
        [
            dict(
                id="native-passage",
                source_id=source,
                title="Do not copy native title",
                text=evidence.text,
                ordinal=0,
                embedding=[1.0, 0.0],
            )
        ]
    )
    metadata = dict(
        span_id=evidence.id,
        artifact_revision_id=revision.id,
        generation_id=generation.id,
        embedding_profile="embed-v1",
    )
    if store.knowledge_backend == "fake":
        store.sources[source]["active_generation_id"] = generation.id
        store.passages["native-passage"].update(metadata)
    else:
        store.run(
            "MATCH (s:Source {id:$source}) SET s.active_generation_id=$generation",
            source=source,
            generation=generation.id,
        )
        store.run(
            "MATCH (p:Passage {id:'native-passage'}) SET p.span_id=$span_id,p.artifact_revision_id=$artifact_revision_id,p.generation_id=$generation_id,p.embedding_profile=$embedding_profile",
            **metadata,
        )
    proof = AuthorizedEvidence(
        workspace_id=DEFAULT_WORKSPACE_ID,
        selection=EvidenceSelection(generation_ids=frozenset({generation.id})),
        artifact_ids=frozenset({artifact.id}),
        revision_ids=frozenset({revision.id}),
        span_ids=frozenset({evidence.id}),
    )
    full = GraphIndex.load(store)
    projected = module.project_managed_graph(full, store, proof, embedding_profile="embed-v1")
    assert projected.passage_by_id(evidence.id).text == evidence.text
    assert projected.passage_by_id(evidence.id).title == "test.py"
    np.testing.assert_array_equal(projected.passage_embeddings, [[1.0, 0.0]])


def test_composing_real_legacy_graph_with_empty_preserves_its_retrieval_results(store):
    from tests.unit.test_graph_index import tiny

    module = api()
    tiny.__wrapped__(store)
    legacy = GraphIndex.load(store)
    composed = module.compose_graphs(legacy, module.compose_graphs())
    assert composed.node_ids == legacy.node_ids
    assert composed.edges == legacy.edges
    assert composed.facts == legacy.facts
    assert composed.code_out == legacy.code_out
    assert composed.communities == legacy.communities
    np.testing.assert_array_equal(composed.entity_boost, legacy.entity_boost)
    np.testing.assert_array_equal(composed.specificity, legacy.specificity)
    np.testing.assert_array_equal(composed.fact_embeddings, legacy.fact_embeddings)
    reset = np.zeros(legacy.num_nodes)
    reset[0] = 1
    np.testing.assert_array_equal(composed.ppr(reset, 0.85), legacy.ppr(reset, 0.85))
