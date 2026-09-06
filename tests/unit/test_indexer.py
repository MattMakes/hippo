"""
hipporag/indexer.py: chunks in, graph nodes and edges out.

Uses the sample corpus through the store and Ollama fixtures, so the same
tests run against FakeStore locally and a real Neo4j in CI.
"""

from __future__ import annotations

import numpy as np
import pytest

from hippo.hipporag.indexer import Chunk, find_synonyms, index_source, passage_id
from hippo.hipporag.text import entity_id
from tests.fakes.fake_ollama import DIM, embed_text


def sample_chunks(sample_text: str) -> list[Chunk]:
    chunks = []
    for ordinal, section in enumerate(sample_text.split("## ")[1:]):
        title, _, body = section.partition("\n")
        chunks.append(Chunk(ordinal, title.strip(), body.strip()))
    return chunks


@pytest.fixture
def chunks(sample_text: str) -> list[Chunk]:
    return sample_chunks(sample_text)


@pytest.fixture
def source_id(store) -> str:
    return store.create_source("sample", "Acme Robotics")


# ------------------------------------------------------------------ counts


def test_the_sample_is_split_into_eight_sections(chunks: list[Chunk]) -> None:
    assert [c.title for c in chunks] == [
        "The company",
        "Where things are",
        "The Orion arm",
        "The Lyra gripper",
        "People",
        "Software",
        "Customers",
        "Suppliers",
    ]
    assert [c.ordinal for c in chunks] == list(range(8))


def test_indexing_the_sample_returns_the_counts(store, ollama, source_id: str, chunks: list[Chunk]) -> None:
    counts = index_source(store, ollama, source_id, chunks)
    assert counts == {"passages": 8, "entities": 31, "facts": 34, "synonyms": 0}

    stats = store.stats()
    assert (stats["passages"], stats["entities"], stats["facts"]) == (8, 31, 34)
    assert stats["mention_edges"] == 45  # each passage mentions the unique entities of its own facts
    source = store.get_source(source_id)
    assert source["passages"] == 8
    assert source["fact_links"] == 34


def test_passages_are_stored_with_titles_text_and_extractions(store, ollama, source_id: str, chunks) -> None:
    index_source(store, ollama, source_id, chunks)
    rows = store.passages_for_source(source_id)
    assert [r["title"] for r in rows] == [c.title for c in chunks]
    assert rows[0]["text"] == chunks[0].text
    assert rows[0]["entities"][:2] == ["Acme Robotics", "Priya Natarajan"]
    assert ["Acme Robotics", "is headquartered in", "Boulder"] in rows[0]["triples"]
    assert rows[0]["extraction_error"] is None
    assert store.passage_ids_for_source(source_id) == [passage_id(source_id, c) for c in chunks]


def test_facts_link_the_right_entities_and_passages(store, ollama, source_id: str, chunks) -> None:
    index_source(store, ollama, source_id, chunks)
    facts = {(f["subject"], f["predicate"], f["object"]): f for f in store.load_facts()}
    hq = facts[("acme robotics", "is headquartered in", "boulder")]
    assert hq["subject_id"] == entity_id("acme robotics")
    assert hq["object_id"] == entity_id("boulder")
    assert hq["passage_ids"] == [passage_id(source_id, chunks[0])]
    assert len(hq["embedding"]) == DIM
    (boulder,) = store.get_entities([entity_id("boulder")])
    assert boulder["name"] == "boulder"
    assert boulder["passage_count"] == 2  # "The company" and "Where things are"


# ------------------------------------------------------------ idempotence


def test_reindexing_the_same_chunks_adds_no_duplicates(store, ollama, source_id: str, chunks) -> None:
    index_source(store, ollama, source_id, chunks)
    before = store.stats()

    counts = index_source(store, ollama, source_id, chunks)

    assert counts == {"passages": 8, "entities": 0, "facts": 0, "synonyms": 0}
    assert store.stats() == before
    assert len(store.load_fact_edges()) == len({(e["a"], e["b"]) for e in store.load_fact_edges()})


def test_passage_ids_are_stable_for_the_same_source_and_text(source_id: str, chunks) -> None:
    assert passage_id(source_id, chunks[0]) == passage_id(source_id, chunks[0])
    assert passage_id(source_id, chunks[0]) != passage_id("other-source", chunks[0])
    assert passage_id(source_id, chunks[0]).startswith("passage-")
    moved = Chunk(9, chunks[0].title, chunks[0].text)
    assert passage_id(source_id, moved) != passage_id(source_id, chunks[0])


# --------------------------------------------------------------- synonyms


def test_near_identical_names_get_a_synonym_edge(store, ollama, source_id: str, chunks) -> None:
    # The fake embedder scores "acme robotics" ~ "acme robotics inc" at about 0.71,
    # so a threshold of 0.7 links them while unrelated names stay apart.
    similarity = float(embed_text("acme robotics") @ embed_text("acme robotics inc"))
    assert similarity > 0.7
    index_source(store, ollama, source_id, chunks, synonymy_threshold=0.7)

    other = store.create_source("text", "Press release")
    counts = index_source(
        store,
        ollama,
        other,
        [Chunk(0, "Press", "Acme Robotics Inc is located in Boulder.")],
        synonymy_threshold=0.7,
    )

    assert counts["synonyms"] == 1
    (row,) = store.load_synonyms()
    assert {row["a"], row["b"]} == {entity_id("acme robotics"), entity_id("acme robotics inc")}
    assert row["score"] == pytest.approx(similarity, abs=1e-5)
    assert row["manual"] is False


def test_a_strict_threshold_links_nothing(store, ollama, source_id: str, chunks) -> None:
    index_source(store, ollama, source_id, chunks, synonymy_threshold=0.99)
    other = store.create_source("text", "Press release")
    counts = index_source(
        store, ollama, other, [Chunk(0, "Press", "Acme Robotics Inc is located in Boulder.")]
    )
    assert counts["synonyms"] == 0
    assert store.load_synonyms() == []


def test_find_synonyms_skips_tiny_phrases_and_itself(store) -> None:
    ids = [entity_id("us"), entity_id("usa")]
    vectors = np.asarray([embed_text("us"), embed_text("usa")], dtype=np.float32)
    store.add_entities(
        [
            {"id": ids[0], "name": "us", "embedding": vectors[0].tolist()},
            {"id": ids[1], "name": "usa", "embedding": vectors[1].tolist()},
        ]
    )
    names = {ids[0]: "us", ids[1]: "usa"}
    pairs = find_synonyms(store, ids, vectors, names, threshold=0.0)
    # "us" is too short to be linked; "usa" links to "us" (never to itself).
    assert [(a, b) for a, b, _ in pairs] == [(ids[1], ids[0])]


def test_find_synonyms_with_nothing_new_or_nothing_stored(store) -> None:
    assert find_synonyms(store, [], np.zeros((0, DIM), dtype=np.float32), {}, threshold=0.5) == []
    vectors = np.asarray([embed_text("boulder")], dtype=np.float32)
    assert (
        find_synonyms(
            store, [entity_id("boulder")], vectors, {entity_id("boulder"): "boulder"}, threshold=0.5
        )
        == []
    )


# --------------------------------------------------------- bookkeeping


def test_indexing_bumps_the_graph_version_and_records_the_embed_model(
    store, ollama, source_id, chunks
) -> None:
    before = store.graph_version()
    index_source(store, ollama, source_id, chunks)
    assert store.graph_version() == before + 1
    assert store.get_meta("embed_model") == ollama.embed_model == "nomic-embed-text"
    assert store.get_meta("embedding_dim") == DIM


def test_progress_is_reported_stage_by_stage(store, ollama, source_id: str, chunks) -> None:
    seen: list[tuple[str, int, int]] = []
    index_source(
        store,
        ollama,
        source_id,
        chunks,
        on_progress=lambda stage, done, total: seen.append((stage, done, total)),
    )
    stages = [s for s, _, _ in seen]
    assert stages[0] == "embedding passages"
    assert stages[-1] == "linking synonyms"
    assert ("embedding passages", 8, 8) in seen
    assert ("extracting facts", 8, 8) in seen
    assert ("saving entities and facts", 1, 1) in seen
    assert ("linking synonyms", 1, 1) in seen
    assert [s for s in dict.fromkeys(stages)] == [
        "embedding passages",
        "extracting facts",
        "saving entities and facts",
        "linking synonyms",
    ]


def test_blank_chunks_are_skipped_and_an_empty_source_changes_nothing(store, ollama, source_id: str) -> None:
    before = store.graph_version()
    assert index_source(store, ollama, source_id, []) == {
        "passages": 0,
        "entities": 0,
        "facts": 0,
        "synonyms": 0,
    }
    assert index_source(store, ollama, source_id, [Chunk(0, "Blank", "   \n")]) == {
        "passages": 0,
        "entities": 0,
        "facts": 0,
        "synonyms": 0,
    }
    assert store.graph_version() == before
    assert store.stats()["passages"] == 0

    counts = index_source(
        store,
        ollama,
        source_id,
        [Chunk(0, "Blank", " "), Chunk(1, "Real", "Boulder is located in Colorado.")],
    )
    assert counts["passages"] == 1 and counts["entities"] == 2 and counts["facts"] == 1


def test_a_chunk_with_no_facts_still_becomes_a_passage(store, ollama, source_id: str) -> None:
    counts = index_source(store, ollama, source_id, [Chunk(0, "Chatter", "Nothing here matches a relation.")])
    assert counts == {"passages": 1, "entities": 0, "facts": 0, "synonyms": 0}
    assert store.get_source(source_id)["passages"] == 1
