"""A never-published attempt is reclaimed by a new holder without losing its staged rows.

`claim_generation_build` collects a `failed` generation before returning it to `staging`, which
is the reviewed prose retry contract and stays exactly as it is. A crashed repository build needs
the opposite: the same generation, the same rows, a fresh fence and a fresh holder. These tests
pin `reclaim_generation_build` to every admission guarantee `claim_generation_build` gives -- the
tombstone barrier, the future lease, the full never-published triple, live-holder exclusion, the
fence advance and the `attempt_count` carry-over -- with collection the single difference.
"""

from datetime import UTC, datetime, timedelta

import pytest

from hippo.knowledge import model as k
from tests.unit.test_generation_store import (
    NOW,
    authority,
    claim,
    generation,
    manifest,
    native_fixture,
    publish,
    seal,
)

LATER = NOW + timedelta(minutes=6)
LEASE = NOW + timedelta(minutes=12)
MEMBER_KINDS = ("GenerationMember", "GenerationEvidenceMember", "NativeBinding", "IndexManifest")
NATIVE_KINDS = ("Passage", "Symbol", "DataObject", "Commit")


def reclaim(store, gen, *, key="resume", owner="resume-worker", expires=LEASE, manifest_hash=None):
    assert hasattr(store, "reclaim_generation_build"), "Resumable staging reclaim is missing"
    return store.reclaim_generation_build(
        gen.id,
        job_key=key,
        lease_owner=owner,
        lease_expires_at=expires,
        expected_manifest_hash=gen.manifest_hash if manifest_hash is None else manifest_hash,
    )


def staged(store, gen):
    """Every row the generation owns, read through the scoped readers only."""
    rows = {
        kind: sorted(store._knowledge_rows(kind, generation_id=gen.id), key=lambda row: row.id)
        for kind in MEMBER_KINDS
    }
    for kind in NATIVE_KINDS:
        rows[kind] = sorted(
            (dict(row) for row in store._native_rows(kind, generation_id=gen.id)),
            key=lambda row: row["id"],
        )
    rows["relations"] = store._native_relationships(generation_id=gen.id)
    rows["checksums"] = store.generation_checksums(gen.id)
    return rows


def admission(store, gen):
    """The three rows a refusal must leave untouched: source, generation and its build jobs.

    `generation_lock` is excluded because it is the durable source lock itself: on the real
    backends `_lock_source` increments it on every acquisition, and an admission that returns
    the live holder idempotently commits that increment. It records that the lock was taken,
    which is the guarantee, not a mutation of the build state. Every other field stays.
    """
    return (
        {key: value for key, value in store.get_source(gen.source_id).items() if key != "generation_lock"},
        store._generation(gen.id),
        sorted(
            store._knowledge_rows("MaintenanceJob", where={"input_fingerprint": gen.id}),
            key=lambda row: row.id,
        ),
    )


def crashed(store, key="one", parent=None):
    """A generation whose holder's lease has expired, with one full batch of staged rows."""
    gen = generation(store, key, parent)
    job = claim(store, gen)
    native_fixture(store, gen, job)
    store._generation_clock = lambda: LATER
    return gen, job


def test_reclaim_of_an_expired_staging_holder_keeps_every_staged_row(store):
    gen, job = crashed(store)
    before = staged(store, gen)
    resumed = reclaim(store, gen)
    assert resumed.fencing_token > job.fencing_token
    assert resumed.id != job.id and resumed.status == "running"
    assert store._generation(gen.id).status == "staging"
    assert staged(store, gen) == before
    source = store.get_source(gen.source_id)
    assert source["active_build_id"] == resumed.id
    assert source["build_fencing_token"] == resumed.fencing_token
    # The reclaimed job is a build credential exactly as a claimed one is.
    with store.generation_write(gen.id, **authority(resumed)):
        pass
    with pytest.raises(ValueError):
        store.check_generation_write(gen.id, **authority(job))


def test_reclaim_after_recovery_failed_the_generation_keeps_every_staged_row(store):
    gen, job = crashed(store)
    before = staged(store, gen)
    store.recover_generation_builds()
    assert store._generation(gen.id).status == "failed"
    resumed = reclaim(store, gen)
    assert resumed.fencing_token > job.fencing_token
    assert store._generation(gen.id).status == "staging"
    assert staged(store, gen) == before
    with store.generation_write(gen.id, **authority(resumed)):
        pass


def test_reclaim_of_a_recovered_ready_generation_reseals_the_identical_manifest(store):
    """A crash after the seal and before publication resumes and seals again, byte for byte."""
    gen = generation(store)
    job = claim(store, gen)
    native_fixture(store, gen, job)
    sealed = seal(store, gen, job)
    assert store._generation(gen.id).status == "ready"
    before = staged(store, gen)
    store._generation_clock = lambda: LATER
    store.recover_generation_builds()
    assert store._generation(gen.id).status == "failed"
    resumed = reclaim(store, gen)
    assert store._generation(gen.id).status == "staging"
    assert staged(store, gen) == before
    assert store.seal_generation(gen.id, manifest(store, gen), **authority(resumed)) == sealed
    assert store._generation(gen.id).status == "ready"
    publish(store, gen, resumed)
    assert store.get_source(gen.source_id)["active_generation_id"] == gen.id


def test_reclaim_of_a_ready_generation_holding_a_live_job_is_refused(store):
    gen = generation(store)
    job = claim(store, gen)
    native_fixture(store, gen, job)
    seal(store, gen, job)
    before = admission(store, gen)
    with pytest.raises(ValueError):
        reclaim(store, gen)
    assert admission(store, gen) == before


@pytest.mark.parametrize(
    "fault", ["tombstoned", "live_holder", "expired_lease", "published_at", "active_pointer", "event"]
)
def test_reclaim_refuses_without_advancing_the_fence_or_installing_a_holder(store, fault):
    """Each of B5's preconditions refuses before the fence moves and before a holder exists."""
    gen, _ = crashed(store)
    expires = LEASE
    if fault == "tombstoned":
        store._generation_clock = lambda: NOW
        store.begin_managed_source(gen.source_id)
        with store.transaction():
            store.apply_source_tombstone(gen.source_id, operation_id="op", created_at=NOW)
        store._generation_clock = lambda: LATER
    elif fault == "live_holder":
        store.claim_generation_build(
            gen.id, job_key="other", lease_owner="other-worker", lease_expires_at=LEASE
        )
    elif fault == "expired_lease":
        expires = LATER
    elif fault == "published_at":
        store._write_knowledge(store._generation(gen.id).replace(published_at=NOW))
    elif fault == "active_pointer":
        store._source_fields(gen.source_id, active_generation_id=gen.id)
    elif fault == "event":
        source = store.get_source(gen.source_id)
        store._write_knowledge(
            k.IndexEvent(
                workspace_id=source["workspace_id"],
                generation_id=gen.id,
                kind="published",
                aggregate_id=gen.source_id,
                sequence=1,
                dedupe_key=gen.id,
                created_at=NOW,
            )
        )
    before = admission(store, gen)
    rows = staged(store, gen)
    with pytest.raises(ValueError):
        reclaim(store, gen, expires=expires)
    assert admission(store, gen) == before
    assert staged(store, gen) == rows


def test_reclaim_refuses_a_manifest_hash_the_stored_generation_does_not_carry(store):
    gen, _ = crashed(store)
    before = admission(store, gen)
    with pytest.raises(ValueError, match="manifest"):
        reclaim(store, gen, manifest_hash="not-the-stored-hash")
    assert admission(store, gen) == before


def test_reclaim_by_the_live_holder_returns_its_own_job_without_a_second_fence(store):
    gen = generation(store)
    job = store.claim_generation_build(
        gen.id, job_key="resume", lease_owner="resume-worker", lease_expires_at=NOW + timedelta(minutes=5)
    )
    before = admission(store, gen)
    assert reclaim(store, gen, expires=NOW + timedelta(minutes=5)) == job
    assert admission(store, gen) == before


def test_reclaim_carries_over_the_attempt_count_of_the_holder_it_replaces(store):
    gen = generation(store)
    first = store.claim_generation_build(
        gen.id, job_key="resume", lease_owner="resume-worker", lease_expires_at=NOW + timedelta(minutes=5)
    )
    assert first.attempt_count == 1
    store._generation_clock = lambda: LATER
    store.recover_generation_builds()
    second = reclaim(store, gen)
    assert second.attempt_count == 2 and second.id == first.id
    store._generation_clock = lambda: NOW + timedelta(minutes=20)
    store.recover_generation_builds()
    third = reclaim(store, gen, expires=NOW + timedelta(minutes=30))
    assert third.attempt_count == 3


def test_claim_still_collects_the_failed_generation_that_reclaim_would_have_resumed(store):
    """The contrast: the reviewed prose retry contract is untouched by this slice."""
    gen, _ = crashed(store)
    store.recover_generation_builds()
    assert any(store._native_rows("Symbol", generation_id=gen.id))
    retry = store.claim_generation_build(
        gen.id, job_key="retry", lease_owner="retry-worker", lease_expires_at=LEASE
    )
    assert store._generation(gen.id).status == "staging"
    assert retry.status == "running"
    for kind in NATIVE_KINDS:
        assert not store._native_rows(kind, generation_id=gen.id)
    for kind in ("GenerationMember", "GenerationEvidenceMember", "NativeBinding"):
        assert not store._knowledge_rows(kind, generation_id=gen.id)


def test_a_reclaimed_build_replays_its_batch_and_still_seals_and_publishes(store):
    """Replay is idempotent by construction: the same rows are written over themselves."""
    gen, _ = crashed(store)
    store.recover_generation_builds()
    resumed = reclaim(store, gen)
    before = staged(store, gen)
    native_fixture(store, gen, resumed)
    assert staged(store, gen) == before
    seal(store, gen, resumed)
    publish(store, gen, resumed)
    assert store._generation(gen.id).status == "active"


def test_reclaim_survives_a_ladybug_close_and_reopen(tmp_path):
    """The crash is a process boundary: the staged rows and the reclaim both cross it."""
    from hippo.store.ladybug import LadybugStore

    path = tmp_path / "resume.lbug"
    store = LadybugStore(path)
    try:
        gen = generation(store)
        job = claim(store, gen)
        native_fixture(store, gen, job)
        before = staged(store, gen)
    finally:
        store.close()
    reopened = LadybugStore(path)
    try:
        reopened._generation_clock = lambda: LATER
        reopened.recover_generation_builds()
        assert reopened._generation(gen.id).status == "failed"
        resumed = reclaim(reopened, gen)
        assert resumed.fencing_token > job.fencing_token
        assert reopened._generation(gen.id).status == "staging"
        assert staged(reopened, gen) == before
        with reopened.generation_write(gen.id, **authority(resumed)):
            pass
        reopened.seal_generation(gen.id, manifest(reopened, gen), **authority(resumed))
        assert reopened._generation(gen.id).status == "ready"
    finally:
        reopened.close()


def test_a_reclaim_does_not_re_take_the_stored_capture_instant(store):
    """`created_at` is not in `Generation.identity_fields`, and reclaim must not re-take it."""
    gen, _ = crashed(store)
    store.recover_generation_builds()
    store._generation_clock = lambda: datetime(2031, 6, 1, tzinfo=UTC)
    reclaim(store, gen, expires=datetime(2031, 6, 2, tzinfo=UTC))
    assert store._generation(gen.id).created_at == NOW
