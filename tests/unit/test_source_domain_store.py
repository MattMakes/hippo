"""The Source domain columns of schema v9: read defaults, the one write path, and the publish bump.

Design D3 and D6, plan section 3.1. A domain decision lives on the Source alone. Writing it never
moves `updated_at`; publishing a generation moves it to the publication instant.
"""

from datetime import datetime

import pytest

from hippo.store import migrations
from tests.unit.test_generation_store import NOW, authority, claim, generation, publish, seal

DOMAIN_COLUMNS = ("domain_override", "domain_confirmed_at", "domain_confirmed_by")
FIRST = "2026-09-18T12:00:00.000000+00:00"
SECOND = "2026-09-18T13:30:00.250000+00:00"


def domain(source):
    return {column: source[column] for column in DOMAIN_COLUMNS}


def listed(store, source_id):
    return next(row for row in store.list_sources() if row["id"] == source_id)


def test_the_domain_columns_are_the_v9_additions():
    assert migrations.V9_ADDED_SOURCE_COLUMNS == DOMAIN_COLUMNS


def test_a_new_source_reads_back_null_domain_columns(store):
    source = store.create_source("text", "fresh")
    assert domain(store.get_source(source)) == dict.fromkeys(DOMAIN_COLUMNS)
    assert domain(listed(store, source)) == dict.fromkeys(DOMAIN_COLUMNS)


def test_set_source_domain_writes_the_three_columns_and_nothing_else(store):
    source = store.create_source("text", "confirmed")
    before = store.get_source(source)
    store.set_source_domain(source, override="code", confirmed_at=FIRST, confirmed_by="user-1")
    after = store.get_source(source)
    assert domain(after) == {
        "domain_override": "code",
        "domain_confirmed_at": FIRST,
        "domain_confirmed_by": "user-1",
    }
    # Invariant P2: the write never bumps `updated_at`, and no other field moves either.
    assert after["updated_at"] == before["updated_at"]
    assert {key: value for key, value in after.items() if key not in DOMAIN_COLUMNS} == {
        key: value for key, value in before.items() if key not in DOMAIN_COLUMNS
    }
    assert domain(listed(store, source)) == domain(after)


def test_a_second_write_without_an_override_clears_it(store):
    source = store.create_source("text", "corrected back")
    store.set_source_domain(source, override="code", confirmed_at=FIRST, confirmed_by="user-1")
    updated_at = store.get_source(source)["updated_at"]
    store.set_source_domain(source, override=None, confirmed_at=SECOND, confirmed_by=None)
    after = store.get_source(source)
    assert domain(after) == {
        "domain_override": None,
        "domain_confirmed_at": SECOND,
        "domain_confirmed_by": None,
    }
    assert after["updated_at"] == updated_at


def test_set_source_domain_refuses_an_unknown_source_on_every_backend(store):
    with pytest.raises(ValueError, match="Unknown source"):
        store.set_source_domain("missing", override=None, confirmed_at=FIRST, confirmed_by=None)


def test_publishing_moves_updated_at_to_the_publication_instant_and_keeps_the_domain(store):
    gen = generation(store)
    job = claim(store, gen)
    seal(store, gen, job)
    store.set_source_domain(gen.source_id, override="code", confirmed_at=FIRST, confirmed_by="user-1")
    before = store.get_source(gen.source_id)
    publish(store, gen, job)
    after = store.get_source(gen.source_id)
    published_at = store._knowledge_get("Generation", gen.id).published_at
    assert published_at == NOW
    # Design D6: the managed proxy (`published_at`) and the legacy one (`updated_at`) agree, in the
    # `now_iso()` format that `created_at` and `updated_at` already use.
    assert after["updated_at"] == NOW.isoformat(timespec="microseconds")
    assert datetime.fromisoformat(after["updated_at"]) >= published_at
    assert after["updated_at"] > before["updated_at"]
    # Invariant I2: publication leaves the domain decision where it was.
    assert domain(after) == domain(before)


def test_a_failed_publication_leaves_updated_at_where_it_was(store):
    gen = generation(store)
    job = claim(store, gen)
    seal(store, gen, job)
    before = store.get_source(gen.source_id)["updated_at"]

    def fail(at):
        if at == "pointer":
            raise RuntimeError("injected")

    with pytest.raises(RuntimeError, match="injected"):
        publish(store, gen, job, fault_hook=fail)
    assert store.get_source(gen.source_id)["updated_at"] == before


def test_a_naive_publication_instant_is_refused_before_updated_at_moves(store):
    gen = generation(store)
    job = claim(store, gen)
    seal(store, gen, job)
    before = store.get_source(gen.source_id)["updated_at"]
    with pytest.raises(ValueError, match="timezone"):
        store.publish_staged_generation(
            gen.id,
            expected_parent_id=None,
            expected_suppression_epoch=store.suppression_epoch(),
            published_at=NOW.replace(tzinfo=None),
            **authority(job),
        )
    assert store.get_source(gen.source_id)["updated_at"] == before
