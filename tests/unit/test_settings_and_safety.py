"""
Settings validation at every door, boost 0 surviving a reload, and the embedding-model guard.
These came out of the review: each one used to be a way to quietly break every later search.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hippo import ask
from hippo.hipporag.indexer import Chunk, EmbeddingMismatch, index_source
from hippo.store.base import validate_settings
from hippo.web.app import create_app


def sample_chunks(sample_text: str) -> list[Chunk]:
    sections = sample_text.split("## ")[1:]
    return [
        Chunk(i, s.splitlines()[0].strip(), "\n".join(s.splitlines()[1:]).strip())
        for i, s in enumerate(sections)
    ]


# ---------------------------------------------------------------- validation


def test_validate_settings_coerces_and_checks_ranges():
    assert validate_settings({"damping": "0.7", "linking_top_k": "6", "node_specificity": "off"}) == {
        "damping": 0.7,
        "linking_top_k": 6,
        "node_specificity": False,
    }
    for bad in (
        {"linking_top_k": "five"},
        {"damping": 1.5},
        {"damping": -0.1},
        {"qa_top_k": 0},
        {"nonsense": 1},
        {"linking_top_k": 2.5},
        {"damping": True},
    ):
        with pytest.raises(ValueError):
            validate_settings(bad)


def test_stores_refuse_bad_settings_and_keep_the_old_value(store):
    with pytest.raises(ValueError):
        store.update_settings({"damping": "lots"})
    assert store.get_settings()["damping"] == 0.5


def test_api_and_form_reject_bad_settings_with_a_message(ctx):
    with TestClient(create_app(ctx)) as client:
        response = client.put("/api/settings", json={"damping": 7})
        assert response.status_code == 400 and "damping" in response.text
        response = client.post("/settings", data={"damping": "7"})
        assert response.status_code == 400 and "Not saved" in response.text
        assert ctx.store.get_settings()["damping"] == 0.5
        assert (
            client.post("/api/search", json={"question": "x", "settings": {"damping": 9}}).status_code == 400
        )


def test_search_refuses_bad_overrides_before_calling_the_model(ctx, fake_ollama):
    with pytest.raises(ValueError):
        ask.search(ctx, "anything", {"linking_top_k": "many"})
    assert fake_ollama.calls == []


# ------------------------------------------------------------------- boost 0


def test_a_boost_of_zero_survives_a_reload_and_mutes_the_entity(ctx, sample_text):
    source_id = ctx.store.create_source("sample", "Acme")
    index_source(ctx.store, ctx.ollama, source_id, sample_chunks(sample_text))
    index = ctx.graph()
    boulder = next(eid for eid, name in index.entity_names.items() if name == "boulder")
    ctx.store.set_node_boost(boulder, 0.0)
    ctx.store.bump_graph_version()
    index = ctx.graph()
    assert index.entity_boost[index.idx_of[boulder]] == 0.0
    assert ctx.store.get_entities([boulder])[0]["boost"] == 0.0
    trace = ask.search(ctx, "Where is Acme Robotics headquartered?")
    assert all(s.weight == 0.0 for s in trace.seed_entities if s.entity_id == boulder)


# ------------------------------------------------------ embedding model guard


def test_indexing_with_another_embedding_model_is_refused(ctx, sample_text, store, fake_ollama):
    source_id = ctx.store.create_source("sample", "Acme")
    index_source(ctx.store, ctx.ollama, source_id, sample_chunks(sample_text))
    assert store.get_meta("embed_model") == "nomic-embed-text"
    fake_ollama.installed.append("some-other-model:latest")
    ctx.ollama.embed_model = "some-other-model"
    other = ctx.store.create_source("text", "note")
    with pytest.raises(EmbeddingMismatch) as excinfo:
        index_source(ctx.store, ctx.ollama, other, [Chunk(0, "note", "Zed Corp is located in Austin.")])
    assert "Re-index everything" in str(excinfo.value)


def test_loading_skips_vectors_of_the_wrong_length_instead_of_crashing(ctx, sample_text, store):
    source_id = ctx.store.create_source("sample", "Acme")
    index_source(ctx.store, ctx.ollama, source_id, sample_chunks(sample_text))
    odd = ctx.store.create_source("text", "odd")
    store.add_passages(
        [
            {
                "id": "passage-odd",
                "source_id": odd,
                "ordinal": 0,
                "title": "odd",
                "text": "x",
                "embedding": [1.0, 0.0, 0.0],
            }
        ]
    )
    store.bump_graph_version()
    index = ctx.graph()
    assert index.passage_by_id("passage-odd") is None
    assert index.passage_embeddings.shape[0] == len(index.passages) == 8


def test_reindex_everything_endpoint_reindexes_each_source(ctx):
    from hippo.ingest import pipeline

    pipeline.add_sample(ctx)
    pipeline.add_text(ctx, "note", "Zed Corp is located in Austin.")
    ctx.jobs.wait_all()
    with TestClient(create_app(ctx)) as client:
        assert client.post("/api/sources/reindex-all").json()["started"] == 2
        ctx.jobs.wait_all()
    assert all(s["status"] == "ready" for s in ctx.store.list_sources())
