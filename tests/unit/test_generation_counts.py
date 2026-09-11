"""Generation inventory is distinct from indexer write diagnostics and serving grants."""

import importlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from threading import Event

import pytest

from hippo.knowledge import model as k
from tests.unit.test_generation_store import NOW, authority, claim, evidence, passage, publish, seal


def api():
    try:
        return importlib.import_module("hippo.store.generation_counts")
    except ModuleNotFoundError:
        pytest.fail("Standalone generation inventory API is not implemented")


def stage(store, *, source_id=None, parent=None, key="one", passages=2):
    source_id = source_id or (parent.source_id if parent else store.create_source("text", "inventory"))
    gen = k.Generation(
        source_id=source_id,
        parent_id=parent.id if parent else None,
        status="staging",
        parser_version="p",
        linker_version="l",
        embedding_profile="p",
        created_at=NOW,
        manifest_hash=key,
    )
    store.put_knowledge(gen)
    store._generation_clock = lambda: NOW
    job = claim(store, gen, key=key)
    rows = []
    if passages:
        with store.generation_write(gen.id, **authority(job)):
            revision, span = evidence(store, gen)
            for ordinal in range(passages):
                from hippo.knowledge.lifecycle import generation_passage_id

                row = passage(gen, revision, span)
                row.update(id=generation_passage_id(gen.id, revision.id, span.id, ordinal), ordinal=ordinal)
                rows.append(row)
            store.add_passages(rows)
            store.add_entities(
                [
                    dict(id="entity-a", name="a", embedding=[0.1, 0.2]),
                    dict(id="entity-b", name="b", embedding=[0.1, 0.2]),
                ]
            )
            store.add_facts(
                [
                    dict(
                        id="fact-shared",
                        subject="a",
                        predicate="knows",
                        object="b",
                        subject_id="entity-a",
                        object_id="entity-b",
                        embedding=[0.1, 0.2],
                    )
                ]
            )
            store.link_passage_facts([(row["id"], "fact-shared") for row in rows])
    return gen, job, rows


def test_generation_inventory_separates_staging_retired_and_legacy_contributions(store):
    counts = api().generation_counts
    source_id = store.create_source("text", "mixed source")
    store.add_passages(
        [
            dict(
                id="passage-legacy",
                source_id=source_id,
                ordinal=0,
                title="old",
                text="legacy",
                embedding=[0.1, 0.2],
            )
        ]
    )
    old, old_job, _ = stage(store, source_id=source_id)
    seal(store, old, old_job)
    publish(store, old, old_job)
    new, new_job, _ = stage(store, parent=old, key="two", passages=1)
    assert (counts(store, old.id).passages, counts(store, old.id).fact_links) == (2, 2)
    staged = counts(store, new.id)
    assert (staged.source_id, staged.generation_id, staged.state) == (source_id, new.id, "staging")
    assert (staged.passages, staged.fact_links) == (1, 1)
    assert store.get_source(source_id)["passages"] == 4
    seal(store, new, new_job)
    publish(store, new, new_job)
    assert counts(store, old.id).state == "retired"
    assert counts(store, old.id).fact_links == 2


def test_duplicate_contributions_do_not_inflate_counts_and_read_preserves_epochs(store):
    counts = api().generation_counts
    gen, job, rows = stage(store)
    with store.generation_write(gen.id, **authority(job)):
        store.link_passage_facts([(row["id"], "fact-shared") for row in rows] * 2)
    before = (
        store.authorization_epoch(),
        store.content_epoch(),
        store.suppression_epoch(),
        store.graph_version(),
    )
    result = counts(store, gen.id)
    assert (result.passages, result.fact_links) == (2, 2)
    assert (
        store.authorization_epoch(),
        store.content_epoch(),
        store.suppression_epoch(),
        store.graph_version(),
    ) == before
    with pytest.raises(FrozenInstanceError):
        result.passages = 99


def test_empty_ready_active_and_retired_counts_are_distinct_from_missing_or_collected(store):
    module = api()
    gen, job, _ = stage(store, passages=0)
    assert module.generation_counts(store, gen.id).passages == 0
    seal(store, gen, job)
    assert module.generation_counts(store, gen.id).state == "ready"
    publish(store, gen, job)
    assert module.generation_counts(store, gen.id).state == "active"
    new, new_job, _ = stage(store, parent=gen, key="new", passages=0)
    seal(store, new, new_job)
    publish(store, new, new_job)
    assert module.generation_counts(store, gen.id).state == "retired"
    store.collect_generation(gen.id)
    for identity in (gen.id, "missing"):
        with pytest.raises(module.GenerationCountsUnavailable):
            module.generation_counts(store, identity)
    for identity in (None, "", "   "):
        with pytest.raises(ValueError):
            module.generation_counts(store, identity)


def corrupt_passage(store, row, *, source_id=None, text=None):
    if store.knowledge_backend == "fake":
        store.passages[row["id"]].update({"source_id": source_id} if source_id else {"text": text})
    elif source_id:
        store.run("MATCH (p:Passage {id:$id})-[r:FROM]->(:Source) DELETE r", id=row["id"])
        store.run(
            "MATCH (p:Passage {id:$id}), (s:Source {id:$source}) MERGE (p)-[:FROM]->(s)",
            id=row["id"],
            source=source_id,
        )
    else:
        store.run("MATCH (p:Passage {id:$id}) SET p.text=$text", id=row["id"], text=text)


def test_staging_inventory_refuses_a_passage_owned_by_another_source(store):
    module = api()
    gen, _, rows = stage(store)
    other = store.create_source("text", "other")
    corrupt_passage(store, rows[0], source_id=other)
    with pytest.raises(module.GenerationCountsUnavailable):
        module.generation_counts(store, gen.id)


def test_sealed_inventory_revalidates_actual_persisted_content(store):
    module = api()
    gen, job, rows = stage(store)
    seal(store, gen, job)
    corrupt_passage(store, rows[0], text="corrupt")
    with pytest.raises(module.GenerationCountsUnavailable):
        module.generation_counts(store, gen.id)


def test_orphaned_generation_has_the_same_unavailable_error(store):
    module = api()
    gen, _, _ = stage(store, passages=0)
    if store.knowledge_backend == "fake":
        store.sources.pop(gen.source_id)
    else:
        store.run("MATCH (s:Source {id:$id}) DETACH DELETE s", id=gen.source_id)
    with pytest.raises(module.GenerationCountsUnavailable):
        module.generation_counts(store, gen.id)


def test_collection_waits_for_one_coherent_inventory_read(store, monkeypatch):
    counts = api().generation_counts
    old, old_job, _ = stage(store)
    seal(store, old, old_job)
    publish(store, old, old_job)
    new, new_job, _ = stage(store, parent=old, key="new", passages=0)
    seal(store, new, new_job)
    publish(store, new, new_job)
    original = store._native_rows
    rows_read, release_reader, collector_attempted = Event(), Event(), Event()
    paused = False

    def pause_reader(kind):
        nonlocal paused
        rows = original(kind)
        if kind == "Passage" and not paused:
            paused = True
            rows_read.set()
            assert release_reader.wait(10)
        return rows

    monkeypatch.setattr(store, "_native_rows", pause_reader)

    def collect():
        collector_attempted.set()
        return store.collect_generation(old.id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        reader = pool.submit(counts, store, old.id)
        try:
            assert rows_read.wait(10)
            collector = pool.submit(collect)
            assert collector_attempted.wait(10)
        finally:
            release_reader.set()
        result = reader.result(timeout=20)
        collected = collector.result(timeout=20)
    assert (result.passages, result.fact_links) == (2, 2)
    assert collected.blocked_reason is None
