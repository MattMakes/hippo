"""Exact raw-content decoding reuse never substitutes for a current storage read."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from hippo.knowledge import model as k
from hippo.knowledge.identity import canonical_json


def prose(label="span", *, width=2):
    return k.ProseExtraction(
        generation_id="generation",
        derived_record_id="derived",
        input_kind="span",
        input_id=label,
        input_text_hash="hash",
        support_passage_ids=("passage",),
        extractor_profile="extractor",
        embedding_profile="embedding",
        payload=k.ProseExtractionPayload(
            entities=(k.ProseEntity(name="alice", embedding=(0.1,) * width),),
        ),
    )


def raw(record):
    row = record.model_dump(mode="json")
    row["payload"] = canonical_json(row["payload"])
    return row


def decode(store, row):
    return store._knowledge_records(k.ProseExtraction, [row])[0]


def test_identical_raw_rows_reuse_expensive_decode(store, monkeypatch):
    calls = []
    original = k.ProseExtraction.model_validate_json

    def observe(data, **kwargs):
        calls.append(data)
        return original(data, **kwargs)

    monkeypatch.setattr(k.ProseExtraction, "model_validate_json", observe)
    record = prose()
    first = decode(store, raw(record))
    second = decode(store, raw(record))
    assert first == record
    assert second is first
    assert len(calls) == 1


def test_decoder_does_not_mutate_incoming_row(store):
    row = raw(prose())
    before = row.copy()
    decode(store, row)
    assert row == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "corrupt"),
        ("payload_hash", "corrupt"),
        ("input_id", "another"),
        ("payload", '{"entities": []}'),
        ("payload", "not JSON"),
        ("support_passage_ids", ["another"]),
        ("input_id", True),
    ],
)
def test_changed_raw_content_cannot_hit_valid_cached_row(store, field, value):
    row = raw(prose())
    decode(store, row.copy())
    with pytest.raises((ValueError, TypeError)):
        decode(store, row | {field: value})
    assert decode(store, row.copy()) == prose()


def test_cached_records_are_deeply_immutable(store):
    result = decode(store, raw(prose()))
    with pytest.raises(ValidationError):
        result.input_id = "changed"
    with pytest.raises(ValidationError):
        result.payload.entities[0].name = "changed"
    with pytest.raises(TypeError):
        result.payload.entities[0].embedding[0] = 4.0
    assert decode(store, raw(prose())) == prose()


def test_cache_evicts_after_32_distinct_rows(store):
    first = decode(store, raw(prose()))
    for index in range(32):
        decode(store, raw(prose(str(index))))
    assert decode(store, raw(prose())) is not first


def test_oversized_row_bypasses_cache(store):
    record = prose("x" * (1024 * 1024))
    assert decode(store, raw(record)) is not decode(store, raw(record))


def test_serialized_utf8_size_not_character_count_bounds_cache(store):
    record = prose("猫" * (200 * 1024))
    assert len(canonical_json(raw(record))) < 1024 * 1024
    assert len(canonical_json(raw(record)).encode("utf-8")) > 1024 * 1024
    assert decode(store, raw(record)) is not decode(store, raw(record))


def test_serialized_byte_budget_evicts_before_entry_limit(store, monkeypatch):
    from hippo.store import knowledge

    row = raw(prose("one"))
    budget = len(canonical_json(row).encode("utf-8")) * 2
    monkeypatch.setattr(knowledge, "_PROSE_DECODE_TOTAL_BYTES", budget)
    first = decode(store, row)
    second = decode(store, raw(prose("two")))
    decode(store, raw(prose("six")))
    assert len(store._prose_decode_cache) == 2
    assert store._prose_decode_cache_bytes <= budget
    assert decode(store, raw(prose("two"))) is second
    assert decode(store, row) is not first


def test_unsupported_raw_tuple_uses_uncached_validation(store):
    row = raw(prose())
    first = decode(store, row.copy())
    row["support_passage_ids"] = tuple(row["support_passage_ids"])
    assert decode(store, row.copy()) == first
    assert decode(store, row.copy()) is not first


def test_other_record_kinds_are_not_cached(store):
    record = k.ProseEntity(name="alice", embedding=(0.1, 0.2))
    row = record.model_dump(mode="json")
    row["embedding"] = canonical_json(row["embedding"])
    first = store._knowledge_records(k.ProseEntity, [row])[0]
    second = store._knowledge_records(k.ProseEntity, [row])[0]
    assert first == second
    assert first is not second


def test_stores_do_not_share_decoded_records(store, tmp_path):
    from hippo.store.ladybug import LadybugStore

    other = LadybugStore(tmp_path / "other.lbug", buffer_pool_bytes=64 * 1024 * 1024)
    try:
        first = decode(store, raw(prose()))
        second = decode(other, raw(prose()))
        assert first == second
        assert first is not second
    finally:
        other.close()


def test_concurrent_decoders_share_one_immutable_result(store):
    record = prose()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: decode(store, raw(record)), range(24)))
    assert all(result is results[0] for result in results)


def test_persisted_reads_stay_fresh_and_deletion_stays_absent(store, monkeypatch):
    if store.knowledge_backend == "fake":
        pytest.skip("Physical row decoding requires a database backend")
    record = prose()
    store._write_knowledge(record)
    statements = []
    original = store.run

    def observe(query, **params):
        statements.append(query)
        return original(query, **params)

    monkeypatch.setattr(store, "run", observe)
    first = store._knowledge_get("ProseExtraction", record.id)
    assert store._knowledge_get("ProseExtraction", record.id) is first
    assert len(statements) == 2
    store.run("MATCH (n:ProseExtraction {id:$id}) SET n.payload_hash = $value", id=record.id, value="bad")
    with pytest.raises(ValueError, match="hash differs"):
        store._knowledge_get("ProseExtraction", record.id)
    store.run("MATCH (n:ProseExtraction {id:$id}) DETACH DELETE n", id=record.id)
    assert store._knowledge_get("ProseExtraction", record.id) is None
