"""
The Store interface, part 1: settings, sources, passages, entities, facts,
links, synonyms, the load_* rows the graph is built from, and the graph edits.

Locally this runs against FakeStore; in CI (NEO4J_URI set) the very same tests
run against a real Neo4j, which keeps the fake honest. Every test only touches
rows it created itself.
"""

from __future__ import annotations

import pytest

from hippo.store.base import DEFAULT_SETTINGS

VEC = [1.0, 0.0, 0.0]
VEC2 = [0.0, 1.0, 0.0]


def add_passage(
    store, source_id: str, pid: str, ordinal: int = 0, title: str = "T", text: str = "some text"
) -> str:
    store.add_passages(
        [
            {
                "id": pid,
                "source_id": source_id,
                "ordinal": ordinal,
                "title": title,
                "text": text,
                "embedding": VEC,
            }
        ]
    )
    return pid


def add_entity(store, eid: str, name: str | None = None, embedding: list[float] | None = None) -> str:
    store.add_entities([{"id": eid, "name": name or eid, "embedding": embedding or VEC}])
    return eid


def add_fact(store, fid: str, subject_id: str, object_id: str, predicate: str = "rel") -> str:
    store.add_facts(
        [
            {
                "id": fid,
                "subject": subject_id,
                "predicate": predicate,
                "object": object_id,
                "subject_id": subject_id,
                "object_id": object_id,
                "embedding": VEC,
            }
        ]
    )
    return fid


# ------------------------------------------------------------- settings & meta


def test_settings_start_at_the_defaults(store) -> None:
    assert store.get_settings() == DEFAULT_SETTINGS


def test_update_settings_changes_known_keys_and_rejects_unknown_ones(store) -> None:
    after = store.update_settings({"damping": 0.7, "linking_top_k": 3})
    assert after["damping"] == 0.7
    assert after["linking_top_k"] == 3
    assert set(after) == set(DEFAULT_SETTINGS)
    assert store.get_settings() == after
    with pytest.raises(ValueError):
        store.update_settings({"damping": 0.9, "bogus": 1})
    assert store.get_settings()["damping"] == 0.7  # nothing from a rejected request is applied


def test_meta_is_none_until_set(store) -> None:
    assert store.get_meta("embed_model") is None
    store.set_meta("embed_model", "nomic-embed-text")
    store.set_meta("embedding_dim", 128)
    assert store.get_meta("embed_model") == "nomic-embed-text"
    assert store.get_meta("embedding_dim") == 128


def test_graph_version_counts_up(store) -> None:
    start = store.graph_version()
    assert store.bump_graph_version() == start + 1
    assert store.bump_graph_version() == start + 2
    assert store.graph_version() == start + 2


def test_stats_has_every_key_and_counts_what_we_create(store) -> None:
    keys = {
        "sources",
        "passages",
        "entities",
        "facts",
        "symbols",
        "data_objects",
        "code_edges",
        "commits",
        "synonym_edges",
        "mention_edges",
        "question_sets",
        "eval_runs",
        "changesets",
        "users",
        "roles",
    }
    assert set(store.stats()) == keys
    source_id = store.create_source("text", "S")
    add_passage(store, source_id, "passage-1")
    add_entity(store, "entity-1")
    add_entity(store, "entity-2")
    store.link_passage_entities([("passage-1", "entity-1")])
    store.add_synonyms([("entity-1", "entity-2", 0.9)])
    stats = store.stats()
    assert (stats["sources"], stats["passages"], stats["entities"]) == (1, 1, 2)
    assert (stats["mention_edges"], stats["synonym_edges"]) == (1, 1)


def test_ping_and_ensure_schema_are_safe_to_call(store) -> None:
    assert store.ping() is True
    store.ensure_schema()
    assert store.get_settings() == DEFAULT_SETTINGS


# --------------------------------------------------------------------- sources


def test_create_and_get_source(store) -> None:
    source_id = store.create_source("file", "notes.md", meta={"bytes": 12})
    row = store.get_source(source_id)
    assert row["id"] == source_id
    assert (row["kind"], row["name"], row["status"], row["stage"]) == ("file", "notes.md", "queued", "queued")
    assert (row["progress_done"], row["progress_total"], row["error"]) == (0, 0, None)
    assert row["meta"] == {"bytes": 12}
    assert row["passages"] == 0 and row["fact_links"] == 0
    assert row["created_at"] and row["updated_at"]


def test_get_source_of_unknown_id_is_none(store) -> None:
    assert store.get_source("nope") is None


def test_update_source_progress_fields(store) -> None:
    source_id = store.create_source("text", "S")
    store.update_source(
        source_id,
        status="indexing",
        stage="extracting facts",
        progress_done=3,
        progress_total=8,
        name="Renamed",
    )
    row = store.get_source(source_id)
    assert (row["status"], row["stage"], row["progress_done"], row["progress_total"]) == (
        "indexing",
        "extracting facts",
        3,
        8,
    )
    assert row["name"] == "Renamed"
    store.update_source(source_id, status="failed", error="boom", meta_json='{"chunks": 2}')
    row = store.get_source(source_id)
    assert (row["status"], row["error"], row["meta"]) == ("failed", "boom", {"chunks": 2})


def test_update_source_rejects_unknown_fields(store) -> None:
    source_id = store.create_source("text", "S")
    with pytest.raises(ValueError, match="unknown source fields"):
        store.update_source(source_id, colour="blue")


def test_list_sources_newest_first_with_counts(store) -> None:
    first = store.create_source("text", "First")
    second = store.create_source("text", "Second")
    add_passage(store, second, "p1")
    rows = store.list_sources()
    assert [r["id"] for r in rows] in ([second, first], [first, second])  # same-second ties are unordered
    by_id = {r["id"]: r for r in rows}
    assert by_id[second]["passages"] == 1 and by_id[first]["passages"] == 0


def test_delete_source_removes_its_passages_and_orphaned_entities_and_facts(store) -> None:
    keep, drop = store.create_source("text", "Keep"), store.create_source("text", "Drop")
    add_passage(store, keep, "p-keep")
    add_passage(store, drop, "p-drop")
    add_entity(store, "entity-shared")
    add_entity(store, "entity-only-drop")
    add_fact(store, "f-shared", "entity-shared", "entity-shared", "self")
    add_fact(store, "f-drop", "entity-shared", "entity-only-drop")
    store.link_passage_entities(
        [("p-keep", "entity-shared"), ("p-drop", "entity-shared"), ("p-drop", "entity-only-drop")]
    )
    store.link_passage_facts([("p-keep", "f-shared"), ("p-drop", "f-drop")])
    store.add_synonyms([("entity-shared", "entity-only-drop", 0.9)])
    store.set_edge_weight("entity-shared", "entity-only-drop", 2.0)

    store.delete_source(drop)

    assert store.get_source(drop) is None
    assert store.get_passages(["p-drop"]) == []
    assert store.existing_entity_ids(["entity-shared", "entity-only-drop"]) == {"entity-shared"}
    assert store.existing_fact_ids(["f-shared", "f-drop"]) == {"f-shared"}
    assert store.load_synonyms() == []
    assert store.load_tuned_edges() == []
    assert store.get_source(keep)["passages"] == 1


# -------------------------------------------------------------------- passages


def test_add_and_get_passages(store) -> None:
    source_id = store.create_source("text", "Src")
    add_passage(store, source_id, "p1", ordinal=0, title="One", text="first text")
    add_passage(store, source_id, "p2", ordinal=1, title="Two", text="second text")

    rows = store.get_passages(["p2", "p1", "missing"])

    assert [r["id"] for r in rows] == ["p2", "p1"]
    row = rows[1]
    assert (row["title"], row["text"], row["ordinal"]) == ("One", "first text", 0)
    assert (row["source_id"], row["source_name"]) == (source_id, "Src")
    assert (row["entities"], row["triples"], row["extraction_error"]) == ([], [], None)


def test_re_adding_a_passage_updates_it_in_place(store) -> None:
    source_id = store.create_source("text", "Src")
    add_passage(store, source_id, "p1", title="Old")
    add_passage(store, source_id, "p1", title="New")
    (row,) = store.get_passages(["p1"])
    assert row["title"] == "New"
    assert store.stats()["passages"] == 1


def test_save_extraction_is_visible_on_the_passage(store) -> None:
    source_id = store.create_source("text", "Src")
    add_passage(store, source_id, "p1")
    store.save_extraction("p1", ["Boulder"], [["Boulder", "is located in", "Colorado"]], None)
    (row,) = store.get_passages(["p1"])
    assert row["entities"] == ["Boulder"]
    assert row["triples"] == [["Boulder", "is located in", "Colorado"]]
    store.save_extraction("p1", [], [], "model missing")
    assert store.get_passages(["p1"])[0]["extraction_error"] == "model missing"


def test_passages_for_source_are_paged_in_ordinal_order(store) -> None:
    source_id = store.create_source("text", "Src")
    other = store.create_source("text", "Other")
    for i in (2, 0, 1):
        add_passage(store, source_id, f"p{i}", ordinal=i)
    add_passage(store, other, "px", ordinal=0)

    assert [r["id"] for r in store.passages_for_source(source_id)] == ["p0", "p1", "p2"]
    assert [r["id"] for r in store.passages_for_source(source_id, limit=2)] == ["p0", "p1"]
    assert [r["id"] for r in store.passages_for_source(source_id, limit=2, offset=2)] == ["p2"]
    assert store.passage_ids_for_source(source_id) == ["p0", "p1", "p2"]
    assert store.passage_ids_for_source("nope") == []


# ------------------------------------------------------------ entities & facts


def test_existing_entity_ids_and_add_entities(store) -> None:
    assert store.existing_entity_ids(["e1"]) == set()
    add_entity(store, "e1", "boulder")
    add_entity(store, "e2", "denver", VEC2)
    assert store.existing_entity_ids(["e1", "e2", "e3"]) == {"e1", "e2"}
    rows = {r["id"]: r for r in store.get_entities(["e1", "e2", "e3"])}
    assert set(rows) == {"e1", "e2"}
    assert rows["e1"] == {"id": "e1", "name": "boulder", "boost": 1.0, "passage_count": 0}


def test_re_adding_an_entity_keeps_its_name(store) -> None:
    add_entity(store, "e1", "boulder")
    add_entity(store, "e1", "somewhere else")
    assert store.get_entities(["e1"])[0]["name"] == "boulder"
    assert store.stats()["entities"] == 1


def test_search_entities_by_substring_ordered_by_mentions(store) -> None:
    source_id = store.create_source("text", "Src")
    add_passage(store, source_id, "p1")
    add_passage(store, source_id, "p2", ordinal=1)
    add_entity(store, "e1", "boulder")
    add_entity(store, "e2", "boulder workshop")
    add_entity(store, "e3", "denver")
    store.link_passage_entities([("p1", "e2"), ("p2", "e2"), ("p1", "e1")])
    rows = store.search_entities("Boulder")
    assert [(r["id"], r["passage_count"]) for r in rows] == [("e2", 2), ("e1", 1)]
    assert [r["id"] for r in store.search_entities("boulder", limit=1)] == ["e2"]
    assert store.search_entities("zzz") == []


def test_load_entity_embeddings_returns_aligned_lists(store) -> None:
    add_entity(store, "e1", "a", VEC)
    add_entity(store, "e2", "b", VEC2)
    ids, vectors = store.load_entity_embeddings()
    assert set(ids) == {"e1", "e2"}
    assert [list(v) for v in vectors][ids.index("e2")] == VEC2


def test_existing_fact_ids_add_facts_and_get_facts(store) -> None:
    add_entity(store, "a")
    add_entity(store, "b")
    assert store.existing_fact_ids(["f1"]) == set()
    add_fact(store, "f1", "a", "b", "likes")
    assert store.existing_fact_ids(["f1", "f2"]) == {"f1"}
    (row,) = store.get_facts(["f1", "nope"])
    assert row == {
        "id": "f1",
        "subject": "a",
        "predicate": "likes",
        "object": "b",
        "subject_id": "a",
        "object_id": "b",
        "passage_ids": [],
    }


# ------------------------------------------------------------------- links


def test_links_connect_passages_to_entities_and_facts(store) -> None:
    source_id = store.create_source("text", "Src")
    add_passage(store, source_id, "p1")
    add_entity(store, "a")
    add_entity(store, "b")
    add_fact(store, "f1", "a", "b")
    store.link_passage_entities([("p1", "a"), ("p1", "a"), ("p1", "ghost")])
    store.link_passage_facts([("p1", "f1"), ("p1", "f1")])

    assert store.load_mentions() == [{"passage_id": "p1", "entity_id": "a"}]
    assert store.get_facts(["f1"])[0]["passage_ids"] == ["p1"]
    assert store.get_entities(["a"])[0]["passage_count"] == 1
    assert store.get_source(source_id)["fact_links"] == 1


def test_synonyms_are_stored_once_per_pair_with_the_best_score(store) -> None:
    add_entity(store, "entity-b")
    add_entity(store, "entity-a")
    store.add_synonyms([("entity-b", "entity-a", 0.8)])
    store.add_synonyms([("entity-a", "entity-b", 0.95)])
    store.add_synonyms([("entity-b", "entity-a", 0.5)])
    store.add_synonyms([("entity-a", "entity-a", 1.0)])  # self pairs are ignored

    (row,) = store.load_synonyms()
    assert (row["a"], row["b"]) == ("entity-a", "entity-b")  # canonical: smaller id first
    assert row["score"] == pytest.approx(0.95)
    assert row["manual"] is False


def test_manual_synonyms_keep_their_flag(store) -> None:
    add_entity(store, "entity-1")
    add_entity(store, "entity-2")
    store.add_synonyms([("entity-1", "entity-2", 0.6)], manual=True)
    store.add_synonyms([("entity-1", "entity-2", 0.7)])
    (row,) = store.load_synonyms()
    assert row["manual"] is True
    assert row["score"] == pytest.approx(0.7)


def test_deleting_a_sources_passages_keeps_the_source_for_reindexing(store):
    source_id = store.create_source("text", "notes")
    store.add_passages(
        [
            {
                "id": "passage-x",
                "source_id": source_id,
                "ordinal": 0,
                "title": "t",
                "text": "x",
                "embedding": [1.0, 0.0],
            }
        ]
    )
    store.add_entities([{"id": "entity-only", "name": "only", "embedding": [1.0, 0.0]}])
    store.link_passage_entities([("passage-x", "entity-only")])
    store.delete_passages_for_source(source_id)
    assert store.get_source(source_id)["passages"] == 0
    assert store.get_source(source_id)["status"] == "queued"
    assert store.load_entities() == []  # the orphaned entity went with the passage


def test_jobs_left_running_by_a_restart_are_marked_failed(store):
    indexing = store.create_source("text", "a")
    store.update_source(indexing, status="indexing", stage="extracting facts")
    ready = store.create_source("text", "b")
    store.update_source(ready, status="ready")
    set_id = store.create_question_set("s")
    store.update_question_set(set_id, status="generating")
    run_id = store.create_run(set_id, "r", {})
    assert store.mark_interrupted_jobs() == 3
    assert (
        store.get_source(indexing)["status"] == "failed" and "restart" in store.get_source(indexing)["error"]
    )
    assert store.get_source(ready)["status"] == "ready"
    assert store.get_question_set(set_id)["status"] == "failed"
    assert store.get_run(run_id)["status"] == "failed" and store.get_run(run_id)["finished_at"]
    assert store.mark_interrupted_jobs() == 0


def test_text_that_looks_like_json_or_a_list_is_stored_verbatim(store) -> None:
    """Code and JSON files are indexed too: text starting with { or [ must come back byte for byte."""
    source_id = store.create_source("file", "{not a struct}.json", meta={"path": "[weird]/{name}"})
    passage_text = '{"a": [1, 2, {"b": null}]}\n[1, 2, 3]'
    add_passage(store, source_id, "pj", title="[section]", text=passage_text)
    add_entity(store, "ej", name="{config}")
    store.add_facts(
        [
            {
                "id": "fj",
                "subject": "{config}",
                "predicate": "[contains]",
                "object": "{config}",
                "subject_id": "ej",
                "object_id": "ej",
                "embedding": VEC,
            }
        ]
    )
    store.save_extraction("pj", ["{config}"], [["{config}", "[contains]", "{config}"]], error="[boom]")
    store.set_meta("note", "{x}")

    source = store.get_source(source_id)
    assert source["name"] == "{not a struct}.json" and source["meta"] == {"path": "[weird]/{name}"}
    passage = store.get_passages(["pj"])[0]
    assert passage["text"] == passage_text and passage["title"] == "[section]"
    assert passage["entities"] == ["{config}"] and passage["extraction_error"] == "[boom]"
    assert store.get_entities(["ej"])[0]["name"] == "{config}"
    fact = store.get_facts(["fj"])[0]
    assert (fact["subject"], fact["predicate"]) == ("{config}", "[contains]")
    assert store.search_entities("{conf")[0]["id"] == "ej"
    assert store.get_meta("note") == "{x}"
    store.update_source(source_id, error="{}")
    assert store.get_source(source_id)["error"] == "{}"
