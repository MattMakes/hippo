"""
hipporag/indexer.py: chunks in, graph nodes and edges out.

Uses the sample corpus through the store and Ollama fixtures, so the same
tests run against FakeStore locally and a real Neo4j in CI.
"""

from __future__ import annotations

import random
import threading
import time

import numpy as np
import pytest

from hippo.hipporag.indexer import Chunk, find_synonyms, index_source, passage_id
from hippo.hipporag.text import entity_id
from tests.fakes.fake_ollama import DIM, embed_text

COUNT_KEYS = (
    "passages",
    "entities",
    "facts",
    "synonyms",
    "symbols",
    "data_objects",
    "code_edges",
    "commits",
    "refers_to",
)


def counts(**written: int) -> dict[str, int]:
    """The nine keys `index_source` always returns, zero unless this run wrote some."""
    return {**dict.fromkeys(COUNT_KEYS, 0), **written}


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
    written = index_source(store, ollama, source_id, chunks)
    assert written == counts(passages=8, entities=31, facts=34)

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

    written = index_source(store, ollama, source_id, chunks)

    assert written == counts(passages=8)
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
    written = index_source(
        store,
        ollama,
        other,
        [Chunk(0, "Press", "Acme Robotics Inc is located in Boulder.")],
        synonymy_threshold=0.7,
    )

    assert written["synonyms"] == 1
    (row,) = store.load_synonyms()
    assert {row["a"], row["b"]} == {entity_id("acme robotics"), entity_id("acme robotics inc")}
    assert row["score"] == pytest.approx(similarity, abs=1e-5)
    assert row["manual"] is False


def test_a_strict_threshold_links_nothing(store, ollama, source_id: str, chunks) -> None:
    index_source(store, ollama, source_id, chunks, synonymy_threshold=0.99)
    other = store.create_source("text", "Press release")
    written = index_source(
        store, ollama, other, [Chunk(0, "Press", "Acme Robotics Inc is located in Boulder.")]
    )
    assert written["synonyms"] == 0
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
    assert index_source(store, ollama, source_id, []) == counts()
    assert index_source(store, ollama, source_id, [Chunk(0, "Blank", "   \n")]) == counts()
    assert store.graph_version() == before
    assert store.stats()["passages"] == 0

    written = index_source(
        store,
        ollama,
        source_id,
        [Chunk(0, "Blank", " "), Chunk(1, "Real", "Boulder is located in Colorado.")],
    )
    assert written["passages"] == 1 and written["entities"] == 2 and written["facts"] == 1


def test_a_chunk_with_no_facts_still_becomes_a_passage(store, ollama, source_id: str) -> None:
    written = index_source(
        store, ollama, source_id, [Chunk(0, "Chatter", "Nothing here matches a relation.")]
    )
    assert written == counts(passages=1)
    assert store.get_source(source_id)["passages"] == 1


# ------------------------------------------------- store round-trips & the lock


class CountingStore:
    """Wraps a store and counts the two 'which of these ids exist?' queries."""

    def __init__(self, store) -> None:
        self._store = store
        self.calls = {"existing_entity_ids": 0, "existing_fact_ids": 0}

    def __getattr__(self, name: str):
        target = getattr(self._store, name)
        if name not in self.calls:
            return target

        def counted(ids):
            self.calls[name] += 1
            return target(ids)

        return counted


def test_the_existence_queries_run_once_per_index_run_not_once_per_id(
    store, ollama, source_id, chunks
) -> None:
    """31 entities used to mean 31 UNWIND queries each carrying all 31 ids (a comprehension called the store per element)."""
    counting = CountingStore(store)
    written = index_source(counting, ollama, source_id, chunks)
    assert written["entities"] == 31 and written["facts"] == 34
    assert counting.calls == {"existing_entity_ids": 1, "existing_fact_ids": 1}


def test_re_indexing_re_checks_the_known_ids_under_the_lock_with_one_more_query(
    store, ollama, source_id, chunks
) -> None:
    index_source(store, ollama, source_id, chunks)
    counting = CountingStore(store)
    index_source(counting, ollama, source_id, chunks)
    # One query before embedding, one under the lock to see whether a delete pruned any of the known ids.
    assert counting.calls == {"existing_entity_ids": 2, "existing_fact_ids": 2}


class PrunedMeanwhileStore(CountingStore):
    """
    Plays the race: the first existence check says `entity`/`fact` exist (so they are not embedded),
    then a delete prunes them before the writes. Later checks tell the truth.
    """

    def __init__(self, store, entity: str, fact: str) -> None:
        super().__init__(store)
        self.pretend = {"existing_entity_ids": entity, "existing_fact_ids": fact}

    def __getattr__(self, name: str):
        target = super().__getattr__(name)
        if name not in self.calls:
            return target

        def lying_once(ids):
            found = target(ids)
            return found | {self.pretend[name]} if self.calls[name] == 1 else found

        return lying_once


def test_ids_pruned_between_the_check_and_the_write_are_written_again(
    store, ollama, source_id, chunks
) -> None:
    boulder = entity_id("boulder")
    from hippo.hipporag.text import fact_id

    hq = fact_id("acme robotics", "is headquartered in", "boulder")
    lying = PrunedMeanwhileStore(store, boulder, hq)

    written = index_source(lying, ollama, source_id, chunks)

    assert written == counts(passages=8, entities=31, facts=34)  # nothing lost
    assert store.existing_entity_ids([boulder]) == {boulder}
    assert store.existing_fact_ids([hq]) == {hq}
    (row,) = store.get_entities([boulder])
    assert row["passage_count"] == 2
    ids, vectors = store.load_entity_embeddings()
    assert len(vectors[ids.index(boulder)]) == DIM  # embedded under the lock, like the others
    assert store.get_facts([hq])[0]["passage_ids"] == [passage_id(source_id, chunks[0])]


def test_the_write_phase_holds_the_graph_write_lock_and_releases_it_after(
    store, ollama, source_id, chunks
) -> None:
    import threading

    from hippo.hipporag.indexer import GRAPH_WRITE_LOCK

    def other_thread_can_take_the_lock() -> bool:
        result: list[bool] = []

        def try_it() -> None:
            got = GRAPH_WRITE_LOCK.acquire(blocking=False)
            result.append(got)
            if got:
                GRAPH_WRITE_LOCK.release()

        thread = threading.Thread(target=try_it)
        thread.start()
        thread.join(5)
        return result[0]

    seen: dict[str, bool] = {}
    for method in ("add_entities", "add_facts", "link_passage_entities", "link_passage_facts"):
        original = getattr(store, method)

        def spy(rows, method=method, original=original):
            seen[method] = other_thread_can_take_the_lock()
            return original(rows)

        setattr(store, method, spy)

    index_source(store, ollama, source_id, chunks)

    assert seen == {
        m: False for m in ("add_entities", "add_facts", "link_passage_entities", "link_passage_facts")
    }
    assert other_thread_can_take_the_lock() is True


# ------------------------------------------------------------- the code graph
#
# `index_source(..., code=)` writes the symbols, data objects and edges `extract_code` found,
# links each passage to what it defines, and -- the point of the whole work package -- keeps
# OpenIE off function bodies and DDL (S2.7).

from hippo.codegraph import extract_code  # noqa: E402
from hippo.codegraph.model import CodeGraph, Symbol, name_text, symbol_id  # noqa: E402
from hippo.hipporag import openie  # noqa: E402
from hippo.ingest.chunker import chunk_documents  # noqa: E402
from tests.conftest import code_sample_docs  # noqa: E402

NER_PREFIX = "Your task is to extract named entities"
TRIPLES_PREFIX = "Your task is to construct an RDF"


@pytest.fixture
def code_source(store) -> str:
    return store.create_source("archive", "code_sample")


@pytest.fixture
def code_chunks(code_source: str):
    """The fixture tree through the real extractor and the real chunker, ready to index."""
    docs = code_sample_docs()
    graph = extract_code(docs, code_source)
    return graph, chunk_documents(docs, 1500, 150, code=graph)


def ner_texts(fake_ollama) -> list[str]:
    """The paragraph of every NER call. Filtering by system prompt is the only way to tell
    an OpenIE call from the fact filter or the answerer (R2-5)."""
    return [
        call["messages"][-1]["content"]
        for call in fake_ollama.calls
        if call["messages"][0]["content"].startswith(NER_PREFIX)
    ]


def openie_calls(fake_ollama) -> int:
    return len(
        [
            call
            for call in fake_ollama.calls
            if call["messages"][0]["content"].startswith((NER_PREFIX, TRIPLES_PREFIX))
        ]
    )


def test_indexing_a_code_source_returns_all_nine_counts(store, ollama, code_source, code_chunks):
    graph, chunks = code_chunks
    written = index_source(store, ollama, code_source, chunks, code=graph)
    assert written == counts(
        passages=len(chunks),
        entities=written["entities"],
        facts=written["facts"],
        synonyms=written["synonyms"],
        symbols=30,
        data_objects=12,
        code_edges=64,
        refers_to=2,  # the README names `OrderService.place` and "the order service"
    )
    assert (store.stats()["symbols"], store.stats()["data_objects"]) == (30, 12)
    assert len(store.load_code_edges()) == 64


def test_every_passage_is_linked_to_what_it_defines(store, ollama, code_source, code_chunks):
    graph, chunks = code_chunks
    index_source(store, ollama, code_source, chunks, code=graph)
    defined = {(row["node_id"], row["passage_id"]) for row in store.load_definitions()}
    place = symbol_id(code_source, "pyapp/orders.py", "OrderService.place")
    (place_chunk,) = [c for c in chunks if place in c.defines]
    assert (place, passage_id(code_source, place_chunk)) in defined
    # Every DEFINED_IN pair the chunker asked for was written, and nothing else.
    assert defined == {(node, passage_id(code_source, c)) for c in chunks for node in c.defines}


def test_re_indexing_a_code_source_changes_nothing(store, ollama, code_source, code_chunks):
    graph, chunks = code_chunks
    first = index_source(store, ollama, code_source, chunks, code=graph)
    before = store.stats()

    again = index_source(store, ollama, code_source, chunks, code=graph)

    assert store.stats() == before
    # The code counts say what this run wrote, not what was new to the store, so they repeat.
    # Entities and facts count only the new ones, exactly as they do for a prose source.
    assert again == {**first, "entities": 0, "facts": 0}


def test_openie_never_reads_a_function_body_or_ddl(store, ollama, fake_ollama, code_source, code_chunks):
    graph, chunks = code_chunks
    index_source(store, ollama, code_source, chunks, code=graph)
    texts = ner_texts(fake_ollama)
    assert not any("billing.total(order)" in t for t in texts)
    assert not any("CREATE TABLE" in t for t in texts)
    assert len([t for t in texts if "Keeps orders. Acme Robotics is headquartered" in t]) == 1
    assert [t for t in texts if "package main" in t] == ["package main\n\nfunc main() {}"]


def test_the_openie_bill_is_two_calls_per_extracted_passage(
    store, ollama, fake_ollama, code_source, code_chunks
):
    """S2.7's gate, counted: NER + triples for every prose chunk and every code passage whose
    doc-comment was long enough, and nothing for the rest."""
    graph, chunks = code_chunks
    extracted = [c for c in chunks if c.extract_text is None or c.extract_text != ""]
    index_source(store, ollama, code_source, chunks, code=graph)
    assert openie_calls(fake_ollama) == 2 * len(extracted)
    assert len(extracted) == 5  # README, build.go, and three docstrings of 80+ characters


def test_a_skipped_passage_still_stores_an_empty_extraction_without_an_error(
    store, ollama, code_source, code_chunks
):
    graph, chunks = code_chunks
    index_source(store, ollama, code_source, chunks, code=graph)
    skipped = next(c for c in chunks if c.extract_text == "")
    (row,) = [p for p in store.passages_for_source(code_source) if p["title"] == skipped.title]
    assert row["entities"] == [] and row["triples"] == [] and row["extraction_error"] is None


def test_prose_passages_refer_to_the_symbols_they_name(store, ollama, code_source, code_chunks):
    graph, chunks = code_chunks
    index_source(store, ollama, code_source, chunks, code=graph)
    readme = next(c for c in chunks if c.title.startswith("Code sample"))
    rows = {row["node_id"]: row for row in store.load_refers_to()}
    place = symbol_id(code_source, "pyapp/orders.py", "OrderService.place")
    service = symbol_id(code_source, "pyapp/orders.py", "OrderService")
    assert rows[place]["omega"] == 0.85 and rows[place]["token"] == "OrderService.place"
    assert rows[service]["omega"] == 0.60 and rows[service]["token"] == "order service"
    assert {row["passage_id"] for row in rows.values()} == {passage_id(code_source, readme)}


def test_symbols_and_prose_entities_become_synonyms_in_both_directions(
    store, ollama, code_source, code_chunks, sample_text
):
    graph, chunks = code_chunks
    service = symbol_id(code_source, "pyapp/orders.py", "OrderService")
    order_service = entity_id("order service")
    # The symbol arrives first and the entity second: the symbol is a key, the entity a query.
    index_source(store, ollama, code_source, chunks, code=graph)
    later = store.create_source("text", "Press release")
    index_source(store, ollama, later, [Chunk(0, "Press", "The order service is located in Boulder.")])
    assert {order_service, service} in [{row["a"], row["b"]} for row in store.load_synonyms()]


def test_a_one_token_symbol_is_kept_out_of_the_cross_kind_synonym_search(store, ollama):
    """
    S0 spike 2: under the real embedder 40% of the symbol-entity pairs above 0.80 are nonsense,
    and raising the threshold makes it worse because generic one-word names score highest. The
    rule that works is on the symbol side -- two split tokens or no cross-kind link at all.
    """
    source = store.create_source("archive", "tiny")
    one = Symbol(
        id=symbol_id(source, "a.py", "boulder"),
        source_id=source,
        name="boulder",
        qualname="boulder",
        kind="function",
        path="a.py",
        display="a.boulder",
        line_start=1,
        line_end=1,
    )
    two = Symbol(
        id=symbol_id(source, "a.py", "BoulderOffice"),
        source_id=source,
        name="BoulderOffice",
        qualname="BoulderOffice",
        kind="class",
        path="a.py",
        display="a.BoulderOffice",
        line_start=3,
        line_end=3,
    )
    # An entity whose name is exactly the text each symbol embeds: the vectors are identical,
    # so only the two-token rule can keep them apart.
    store.add_entities(
        [
            {
                "id": entity_id(name_text(s.name)),
                "name": name_text(s.name),
                "embedding": embed_text(name_text(s.name)).tolist(),
            }
            for s in (one, two)
        ]
    )
    graph = CodeGraph(source_id=source, symbols=[one, two])
    index_source(
        store,
        ollama,
        source,
        [Chunk(0, "a.py :: a.boulder (lines 1-1)", "def boulder(): ...", defines=[one.id], extract_text="")],
        code=graph,
    )

    linked = [{row["a"], row["b"]} for row in store.load_synonyms()]
    assert {two.id, entity_id(name_text(two.name))} in linked
    assert not any(one.id in pair for pair in linked)
    # It is absent from the key matrix too, so a later prose source cannot link to it either.
    assert one.id not in store.load_code_embeddings()[0]
    later = store.create_source("text", "Notes")
    index_source(store, ollama, later, [Chunk(0, "Notes", "Boulder is located in Colorado.")])
    assert not any(one.id in {row["a"], row["b"]} for row in store.load_synonyms())


def test_symbols_carry_a_community_from_the_module_projection(store, ollama, code_source, code_chunks):
    graph, chunks = code_chunks
    index_source(store, ollama, code_source, chunks, code=graph)
    by_qualname = {row["qualname"]: row for row in store.load_symbols()}
    # Every symbol of one module shares that module's community.
    assert by_qualname["OrderService.place"]["community"] == by_qualname["pyapp.orders"]["community"]
    # `pyapp` and `tsapp` share no edge, so Leiden must not put them together.
    assert by_qualname["pyapp.orders"]["community"] != by_qualname["tsapp.index"]["community"]
    assert all(row["community"] is not None for row in store.load_symbols())


def test_two_leiden_runs_in_two_threads_do_not_interleave(code_chunks, monkeypatch) -> None:
    """
    AR1 fix 3. igraph's RNG is process-global and `_leiden` seeds it, runs and restores it, while
    `jobs.py` runs each index job in its own thread. Without a lock two jobs interleave as
    seed(A) -> seed(B) -> run(A) -> restore(A) -> run(B) and job B partitions unseeded: community
    integers a re-index would not reproduce, on a single-threaded CI gate that stays green.
    """
    import igraph as ig

    from hippo.hipporag.indexer import module_communities

    graph, _chunks = code_chunks
    events: list[str] = []
    real = ig.set_random_number_generator

    def spy(generator):
        events.append("seed" if isinstance(generator, random.Random) else "restore")
        time.sleep(0.01)  # wide enough that an unlocked interleave is a certainty, not a race
        return real(generator)

    monkeypatch.setattr(ig, "set_random_number_generator", spy)

    results: list[dict[str, int]] = []
    threads = [threading.Thread(target=lambda: results.append(module_communities(graph))) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert events == ["seed", "restore"] * 4, "seed/run/restore is one atomic triple"
    assert len(results) == 4 and all(r == results[0] for r in results)


def test_stopping_before_the_code_graph_stage_writes_no_code(store, ollama, code_source, code_chunks):
    graph, chunks = code_chunks
    with pytest.raises(openie.Stopped, match="writing code graph"):
        index_source(store, ollama, code_source, chunks, code=graph, should_stop=lambda: True)
    assert store.load_symbols() == [] and store.load_data_objects() == []
    assert store.load_code_edges() == [] and store.load_definitions() == []


def test_the_code_stages_are_reported_and_only_run_for_a_code_source(store, ollama, code_source, code_chunks):
    graph, chunks = code_chunks
    seen: list[str] = []
    index_source(
        store,
        ollama,
        code_source,
        chunks,
        code=graph,
        on_progress=lambda stage, done, total: seen.append(stage),
    )
    assert list(dict.fromkeys(seen)) == [
        "embedding passages",
        "writing code graph",
        "extracting facts",
        "saving entities and facts",
        "linking synonyms",
        "linking mentions",
        "communities",
    ]


def test_indexing_the_same_tree_twice_gives_the_same_graph(store, ollama, code_chunks, code_source):
    """
    CI gate 1. The fields compared are named here on purpose: ids, kinds, qualnames, paths, line
    ranges, edges with kind/omega/provenance, DEFINED_IN and REFERS_TO. `community` is excluded --
    Leiden is randomised, and S2.10 seeds and relabels it rather than pinning the integers.
    """
    graph, chunks = code_chunks
    index_source(store, ollama, code_source, chunks, code=graph)

    other = store.create_source("archive", "code_sample again")
    docs = code_sample_docs()
    second = extract_code(docs, other)
    index_source(store, ollama, other, chunks_for(docs, second), code=second)

    assert comparable(store, code_source) == comparable(store, other)


def chunks_for(docs, graph):
    return chunk_documents(docs, 1500, 150, code=graph)


def comparable(store, source_id: str):
    """One source's code graph with every source-dependent value replaced by a stable key."""
    symbols = {
        r["id"]: (r["path"], r["qualname"]) for r in store.load_symbols() if r["source_id"] == source_id
    }
    data = {
        r["id"]: (r["kind"], r["qualname"]) for r in store.load_data_objects() if r["source_id"] == source_id
    }
    keys = {**symbols, **data}
    passages = {p["id"]: p["title"] for p in store.passages_for_source(source_id)}
    nodes = sorted(
        (keys[r["id"]], r["kind"], r["lang"], r["line_start"], r["line_end"], r["signature"], r["doc"])
        for r in store.load_symbols()
        if r["source_id"] == source_id
    )
    edges = sorted(
        (keys[e["a"]], keys[e["b"]], e["kind"], e["omega"], e["provenance"])
        for e in store.load_code_edges()
        if e["a"] in keys and e["b"] in keys
    )
    defined = sorted(
        (keys[d["node_id"]], passages[d["passage_id"]])
        for d in store.load_definitions()
        if d["node_id"] in keys and d["passage_id"] in passages
    )
    refers = sorted(
        (passages[r["passage_id"]], keys[r["node_id"]], r["omega"], r["token"])
        for r in store.load_refers_to()
        if r["node_id"] in keys and r["passage_id"] in passages
    )
    return nodes, sorted(data.values()), edges, defined, refers


# ---------------------------------------------------- the checked-in spec (S2.17)


def test_the_indexed_fixture_matches_the_checked_in_spec(code_index, request) -> None:
    """
    `tests/fixtures/code_sample/expected.json` is the spec for the code graph, not a snapshot of
    it: a diff there is a change to what hippo promises about a repository, and is read like a
    source change. Compared order-independently; `community` is excluded because S2.10 seeds and
    relabels Leiden rather than pinning its integers, and the `commits`/`modifies` sections are
    ignored while WP2b has not filled them in.

    `--update-expected` rewrites the file instead of comparing against it. Read the diff.
    """
    if request.config.getoption("--update-expected"):
        pytest.skip(rewrite_expected())
    ctx, source_id = code_index
    assert indexed_spec(ctx.store, source_id) == checked_in_spec()


def rewrite_expected() -> str:
    """Regenerate the spec by running the script that owns it, so there is one generator."""
    import subprocess
    import sys

    from tests.conftest import ROOT

    script = ROOT / "scripts" / "update_expected.py"
    done = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=True)
    return done.stdout.strip()


def checked_in_spec() -> dict[str, list]:
    """The file, projected onto what a store round-trip can see."""
    import json

    from tests.conftest import CODE_SAMPLE_PATH

    document = json.loads((CODE_SAMPLE_PATH / "expected.json").read_text())
    return {
        "symbols": sorted(
            (
                s["path"],
                s["qualname"],
                s["kind"],
                s["lang"],
                s["line_start"],
                s["line_end"],
                s["signature"],
                s["doc"],
                s["is_test"],
                tuple(s["raises"]),
            )
            for s in document["symbols"]
        ),  # fmt: skip
        "data_objects": sorted(
            (d["kind"], d["qualname"], d["name"], d["dialect"]) for d in document["data_objects"]
        ),
        "edges": sorted(
            (e["kind"], e["omega"], e["provenance"], tuple(e["a"]), tuple(e["b"]), _json(e.get("extra")))
            for e in document["edges"]
        ),
        "definitions": sorted((tuple(d["node"]), d["passage"]) for d in document["definitions"]),
        "refers_to": sorted(
            (r["passage"], tuple(r["node"]), r["omega"], r["token"]) for r in document["refers_to"]
        ),
    }


def indexed_spec(store, source_id: str) -> dict[str, list]:
    """The same shape, read back out of whichever store this run used."""
    symbols = [r for r in store.load_symbols() if r["source_id"] == source_id]
    data = [r for r in store.load_data_objects() if r["source_id"] == source_id]
    keys = {r["id"]: ("symbol", r["path"], r["qualname"]) for r in symbols}
    keys.update({r["id"]: ("data", r["kind"], r["qualname"]) for r in data})
    titles = {p["id"]: p["title"] for p in store.passages_for_source(source_id)}
    return {
        "symbols": sorted(
            (
                s["path"],
                s["qualname"],
                s["kind"],
                s["lang"],
                s["line_start"],
                s["line_end"],
                s["signature"],
                s["doc"],
                s["is_test"],
                tuple(s["raises"]),
            )
            for s in symbols
        ),  # fmt: skip
        "data_objects": sorted((d["kind"], d["qualname"], d["name"], d["dialect"]) for d in data),
        "edges": sorted(
            (e["kind"], e["omega"], e["provenance"], keys[e["a"]], keys[e["b"]], _json(e.get("extra")))
            for e in store.load_code_edges()
            if e["a"] in keys and e["b"] in keys
        ),
        "definitions": sorted(
            (keys[d["node_id"]], titles[d["passage_id"]])
            for d in store.load_definitions()
            if d["node_id"] in keys and d["passage_id"] in titles
        ),
        "refers_to": sorted(
            (titles[r["passage_id"]], keys[r["node_id"]], r["omega"], r["token"])
            for r in store.load_refers_to()
            if r["node_id"] in keys and r["passage_id"] in titles
        ),
    }


def _json(value) -> str:
    """`extra` is free-form JSON; compare it as text so dict order never decides a test."""
    import json

    return json.dumps(value or {}, sort_keys=True)


def test_a_prose_entity_indexed_first_still_finds_the_symbol(store, ollama, code_source, code_chunks):
    """The other direction: the entity is already a key when the symbol arrives as a query."""
    graph, chunks = code_chunks
    earlier = store.create_source("text", "Press release")
    index_source(store, ollama, earlier, [Chunk(0, "Press", "The order service is located in Boulder.")])

    index_source(store, ollama, code_source, chunks, code=graph)

    service = symbol_id(code_source, "pyapp/orders.py", "OrderService")
    assert {entity_id("order service"), service} in [{r["a"], r["b"]} for r in store.load_synonyms()]
