"""A failed build releases its own lease without collecting retained evidence."""

from datetime import timedelta

import pytest

from tests.unit.test_generation_store import NOW, authority, claim, generation, native_fixture, publish, seal


def fail(store, gen, job, **kwargs):
    assert hasattr(store, "fail_generation_build"), "Controlled non-collecting build failure is missing"
    return store.fail_generation_build(gen.id, **authority(job), **kwargs)


@pytest.mark.parametrize("ready", [False, True])
@pytest.mark.parametrize("code,status", [("build_failed", "failed"), ("build_cancelled", "cancelled")])
def test_failure_preserves_last_good_and_unpublished_inventory(store, ready, code, status):
    old = generation(store)
    old_job = claim(store, old)
    seal(store, old, old_job)
    publish(store, old, old_job)
    new = generation(store, "refresh", old)
    job = claim(store, new)
    symbol, row = native_fixture(store, new, job)
    if ready:
        seal(store, new, job)
    kinds = ("GenerationMember", "GenerationEvidenceMember", "NativeBinding", "IndexManifest")
    inventory = {kind: store._knowledge_rows(kind) for kind in kinds}
    epoch, auth_epoch = store.content_epoch(), store.authorization_epoch()
    terminal = fail(store, new, job, error_code=code)
    assert terminal.status == status and terminal.error_code == code
    assert store._knowledge_get("Generation", new.id).status == "failed"
    assert store._knowledge_get("Generation", old.id).status == "active"
    source = store.get_source(new.source_id)
    assert source["active_generation_id"] == old.id and source["active_build_id"] is None
    assert store.content_epoch() > epoch and store.authorization_epoch() == auth_epoch
    assert {kind: store._knowledge_rows(kind) for kind in kinds} == inventory
    assert any(r["id"] == row["id"] for r in store.load_passages())
    assert any(r["id"] == symbol["id"] for r in store.load_symbols())
    with pytest.raises(ValueError):
        fail(store, new, job)
    retry = claim(store, new, key="retry", owner="new-worker")
    assert retry.fencing_token > job.fencing_token
    assert not any(r["id"] == row["id"] for r in store.load_passages())
    with pytest.raises(ValueError):
        fail(store, new, job)
    assert store.get_source(new.source_id)["active_build_id"] == retry.id


@pytest.mark.parametrize("fault", ["expired", "published", "owner", "fence", "job"])
def test_failure_cannot_mutate_without_live_unpublished_build(store, fault):
    gen = generation(store)
    job = claim(store, gen)
    if fault == "expired":
        store._generation_clock = lambda: NOW + timedelta(minutes=6)
    elif fault == "published":
        seal(store, gen, job)
        publish(store, gen, job)
    else:
        job = job.replace(
            **{
                "owner": {"lease_owner": "wrong"},
                "fence": {"fencing_token": 99},
                "job": {"job_key": "wrong"},
            }[fault]
        )
    before = store.get_source(gen.source_id), store._generation(gen.id), store.content_epoch()
    with pytest.raises(ValueError):
        fail(store, gen, job)
    assert (store.get_source(gen.source_id), store._generation(gen.id), store.content_epoch()) == before


def test_failure_rejects_private_error_text_before_mutation(store):
    gen = generation(store)
    job = claim(store, gen)
    with pytest.raises(ValueError):
        fail(store, gen, job, error_code="private model text")
    assert store._generation(gen.id).status == "staging"


@pytest.mark.parametrize("point", ["generation", "job", "source"])
def test_failure_transition_rolls_back_atomically(store, monkeypatch, point):
    gen = generation(store)
    job = claim(store, gen)
    original_write, original_source = store._write_knowledge, store._source_fields

    def write(record):
        result = original_write(record)
        if (point == "generation" and type(record).__name__ == "Generation") or (
            point == "job" and type(record).__name__ == "MaintenanceJob"
        ):
            raise RuntimeError("injected")
        return result

    def source(*args, **kwargs):
        result = original_source(*args, **kwargs)
        if point == "source":
            raise RuntimeError("injected")
        return result

    before = store.get_source(gen.source_id), store.content_epoch()
    monkeypatch.setattr(store, "_write_knowledge", write)
    monkeypatch.setattr(store, "_source_fields", source)
    with pytest.raises(RuntimeError, match="injected"):
        fail(store, gen, job)
    assert store._generation(gen.id) == gen
    assert store._knowledge_get("MaintenanceJob", job.id) == job
    assert (store.get_source(gen.source_id), store.content_epoch()) == before


def test_source_recovery_leaves_unrelated_expired_build_untouched(store):
    first, second = generation(store, "first"), generation(store, "second")
    first_job, second_job = claim(store, first), claim(store, second)
    seal(store, first, first_job)
    store._generation_clock = lambda: NOW + timedelta(minutes=6)
    untouched = store.get_source(second.source_id)
    result = store.recover_generation_builds(source_id=first.source_id)
    assert result.failed_builds == 1
    assert store._generation(first.id).status == "failed"
    assert store.get_source(first.source_id)["active_build_id"] is None
    assert store._generation(second.id) == second
    assert store._knowledge_get("MaintenanceJob", second_job.id) == second_job
    assert store.get_source(second.source_id) == untouched
    retry = store.claim_generation_build(
        first.id, job_key="retry", lease_owner="new", lease_expires_at=NOW + timedelta(minutes=10)
    )
    assert retry.fencing_token > first_job.fencing_token
    store.recover_generation_builds(source_id=first.source_id)
    assert store._knowledge_get("MaintenanceJob", retry.id).status == "running"
    store.recover_generation_builds()
    assert store._generation(second.id).status == "failed"


@pytest.mark.parametrize("source_id", ["", 1, False])
def test_source_recovery_rejects_invalid_scope(store, source_id):
    with pytest.raises(ValueError):
        store.recover_generation_builds(source_id=source_id)
