"""A legacy index beside managed code generations never reads or writes a generation-tagged row.

R21-B4 of `ai_docs/reports/2026-09-13-code-capture-review.md`. The legacy synonym pass takes
every code name vector as its key matrix (`store.load_code_embeddings`). Ruling 14 says only
untagged rows serve the legacy lane, so a staging or published generation's Symbol and
DataObject must stay out of that matrix. Otherwise a never-managed source whose entity names
resemble a managed symbol fails to index: `add_synonyms` is refused by the staging generation's
write guard or by the sealed generation's checksum.

Every generation here holds a Symbol and a DataObject whose name vector is exactly the legacy
entity's, and one untagged twin pair on a legacy code source holds the same vector. The twin is
what makes each test discriminate: the legacy pass must still link to it, so the read filters
rather than returning nothing.
"""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import numpy as np
import pytest

from hippo.codegraph.model import CodeGraph, Symbol, data_id, name_text, symbol_id
from hippo.context import AppContext
from hippo.hipporag.indexer import Chunk, find_synonyms, index_source
from hippo.hipporag.text import entity_id
from hippo.ingest import pipeline
from hippo.knowledge import model as k
from hippo.knowledge.lifecycle import generation_namespace
from tests.fakes.fake_ollama import DIM, embed_text
from tests.unit.test_derived_generation_store import member
from tests.unit.test_structural_loading import published

PRESS = "The order service is located in Boulder."
ORDER_SERVICE = entity_id("order service")
VECTOR = embed_text(name_text("OrderService")).tolist()
NATIVE_KINDS = ("Passage", "Symbol", "DataObject", "Commit")
SETTLE_SECONDS = 60


def code_rows(source_id, *, namespace=None, generation_id=None):
    """A Symbol and a DataObject named like the legacy entity, tagged when a generation is given."""
    tag = {} if generation_id is None else {"generation_id": generation_id}
    symbol = dict(
        id=symbol_id(source_id, "orders.py", "OrderService", "class", node_namespace=namespace),
        source_id=source_id,
        name="OrderService",
        qualname="OrderService",
        kind="class",
        path="orders.py",
        embedding=VECTOR,
        **tag,
    )
    table = dict(
        id=data_id(source_id, "table", "order_service", node_namespace=namespace),
        source_id=source_id,
        name="order_service",
        qualname="order_service",
        kind="table",
        dialect="sql",
        embedding=VECTOR,
        **tag,
    )
    return symbol, table


def managed_code(store, gen, revision, span, now):
    """`published`'s enrich hook: the generation's own code rows, each bound to its one span.

    A seal refuses a native row without an evidence binding, and a binding whose object has no
    selected observation, so each row gets both.
    """
    symbol, table = code_rows(gen.source_id, namespace=generation_namespace(gen), generation_id=gen.id)
    store.add_symbols([symbol])
    store.add_data_objects([table])
    workspace = store.get_source(gen.source_id)["workspace_id"]
    for kind, object_kind, row in (("Symbol", "symbol", symbol), ("DataObject", "table", table)):
        obj = k.KnowledgeObject(
            workspace_id=workspace, kind=object_kind, canonical_key=json.dumps([gen.id, row["qualname"]])
        )
        store.put_knowledge(obj)
        member(
            store,
            gen,
            k.ObjectObservation(
                object_id=obj.id,
                revision_id=revision.id,
                span_id=span.id,
                evidence_class="declared",
                recorded_from=now,
                attributes_json=json.dumps({"name": row["name"], "kind": row["kind"]}),
            ),
        )
        store.put_knowledge(
            k.NativeBinding(
                generation_id=gen.id, object_id=obj.id, native_kind=kind, native_id=row["id"], span_id=span.id
            )
        )


@pytest.fixture
def managed(store):
    """A published and a staging code generation, and the untagged twin a legacy index may use."""
    active, _ = published(store, "published code", dimension=DIM, enrich=managed_code)
    staging, _ = published(store, "staging code", dimension=DIM, enrich=managed_code, publish=False)
    assert store._generation(active.id).status == "active"
    assert store._generation(staging.id).status == "staging"
    generations = (active.id, staging.id)
    tagged = {
        row["id"]
        for generation_id in generations
        for kind in ("Symbol", "DataObject")
        for row in store._native_rows(kind, generation_id=generation_id)
    }
    assert len(tagged) == 4, "each generation must hold its own Symbol and DataObject"
    legacy = store.create_source("archive", "legacy code")
    symbol, table = code_rows(legacy)
    store.add_symbols([symbol])
    store.add_data_objects([table])
    return SimpleNamespace(generations=generations, tagged=tagged, twins=(symbol["id"], table["id"]))


def managed_state(store, generation_ids):
    """Every native row and relation of each generation, read through the generation's own key."""
    return copy.deepcopy(
        {
            generation_id: (
                {
                    kind: sorted(
                        store._native_rows(kind, generation_id=generation_id), key=lambda row: row["id"]
                    )
                    for kind in NATIVE_KINDS
                },
                store._native_relationships(generation_id=generation_id),
                store.generation_checksums(generation_id),
            )
            for generation_id in generation_ids
        }
    )


def synonym_pairs(store):
    return [{row["a"], row["b"]} for row in store.load_synonyms()]


def assert_no_synonym_touches(store, tagged):
    touching = [pair for pair in synonym_pairs(store) if pair & tagged]
    assert touching == []


# ------------------------------------------------------------- the store read


def test_the_legacy_key_matrix_holds_only_untagged_code_vectors(store, managed):
    ids, vectors = store.load_code_embeddings()

    # Symbols first, then data objects, as the unfiltered read always returned them.
    assert ids == list(managed.twins)
    assert [list(vector) for vector in vectors] == [pytest.approx(VECTOR), pytest.approx(VECTOR)]
    # The tagged rows are still there and still carry their vectors; the read just never sees them.
    for generation_id in managed.generations:
        for kind in ("Symbol", "DataObject"):
            (row,) = store._native_rows(kind, generation_id=generation_id)
            assert row["embedding"]


def test_find_synonyms_pairs_a_new_entity_only_with_untagged_code(store, managed):
    pairs = find_synonyms(
        store,
        [ORDER_SERVICE],
        np.asarray([embed_text("order service")], dtype=np.float32),
        {ORDER_SERVICE: "order service"},
        threshold=0.8,
    )

    assert {b for _, b, _ in pairs} == set(managed.twins)


# ------------------------------------------------------------- the indexer


def test_index_source_beside_managed_code_links_only_the_untagged_twin(store, ollama, managed):
    before = managed_state(store, managed.generations)
    source = store.create_source("text", "Press release")

    written = index_source(store, ollama, source, [Chunk(0, "Press", PRESS)])

    assert written["synonyms"] > 0
    assert {ORDER_SERVICE, managed.twins[0]} in synonym_pairs(store)
    assert_no_synonym_touches(store, managed.tagged)
    assert managed_state(store, managed.generations) == before


def test_a_legacy_code_graph_beside_managed_code_never_pairs_with_a_tagged_node(store, ollama, managed):
    """The unmanaged repository lane: new legacy code nodes join the same key matrix as queries."""
    before = managed_state(store, managed.generations)
    source = store.create_source("archive", "another legacy tree")
    service = Symbol(
        id=symbol_id(source, "orders.py", "OrderService", "class"),
        source_id=source,
        name="OrderService",
        qualname="OrderService",
        kind="class",
        path="orders.py",
        display="orders.OrderService",
        line_start=1,
        line_end=1,
    )
    graph = CodeGraph(source_id=source, symbols=[service])
    chunk = Chunk(
        0,
        "orders.py :: OrderService (lines 1-1)",
        "class OrderService: ...",
        defines=[service.id],
        extract_text="",
    )

    written = index_source(store, ollama, source, [chunk], code=graph)

    assert written["symbols"] == 1 and written["synonyms"] > 0
    assert {service.id, managed.twins[0]} in synonym_pairs(store)
    assert_no_synonym_touches(store, managed.tagged)
    assert managed_state(store, managed.generations) == before


# ------------------------------------------------------------- the pipeline


def test_add_text_beside_managed_code_indexes_and_leaves_every_managed_row_unchanged(
    ctx: AppContext, managed
):
    store = ctx.store
    before = managed_state(store, managed.generations)

    source_id = pipeline.add_text(ctx, "Press release", PRESS)
    ctx.jobs.wait_all(SETTLE_SECONDS)
    assert ctx.jobs.running_keys() == []

    source = store.get_source(source_id)
    assert (source["status"], source["error"]) == ("ready", None)
    assert source["meta"]["counts"]["synonyms"] > 0
    assert {ORDER_SERVICE, managed.twins[0]} in synonym_pairs(store)
    assert_no_synonym_touches(store, managed.tagged)
    assert managed_state(store, managed.generations) == before
