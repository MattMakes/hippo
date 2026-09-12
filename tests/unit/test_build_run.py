"""The coordinator run state both build lanes share, proved without either lane.

`BuildRun` is the failure latch, the cooperative cancellation checkpoint and the
lease heartbeat that `prose_generation.py` owned privately as `_Run`. The prose
lane still proves itself end to end in `test_prose_generation.py`; this module
proves the shared piece in isolation, with a real store and a real
`BuildAuthority` but no model, no raw objects and no published generation, so
that the code coordinator inherits a contract rather than a copy.

The options object is duck-typed on purpose: `BuildRun` reads exactly two
attributes from it, and `PlainBuildOptions` is not importable here without
dragging the prose lane back in.
"""

import subprocess
import sys
import threading
from dataclasses import FrozenInstanceError, dataclass
from types import SimpleNamespace

import pytest

from hippo.access import Principal
from hippo.ingest import build_run
from hippo.ingest.build_run import (
    BuildCancelled,
    BuildProgress,
    BuildReceipt,
    BuildRun,
    authority_fields,
    credentials,
)
from hippo.knowledge import model as k
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.build_authority import BuildActor, BuildAuthority, capture_build_authority
from hippo.knowledge.lease_heartbeat import LeaseHeartbeat

RENEWAL_THREAD = "hippo-lease-renewal"


@dataclass(frozen=True)
class Options:
    """Everything `BuildRun` asks of a lane's options object."""

    lease_duration_seconds: float = 300.0
    renewal_interval_seconds: float = 30.0


@pytest.fixture
def world(ctx):
    store = ctx.store
    store.ensure_schema()
    store.ensure_roles()
    user = store.create_user("builder", "password", "individual")
    source = store.create_source("text", "Notes", {"file": "notes.md"}, owner_id=user)
    workspace = store.get_source(source)["workspace_id"]
    store.put_knowledge(
        k.WorkspaceMembership(
            workspace_id=workspace, principal_id=user, mapping_authority="local", enabled=True, policy_epoch=1
        )
    )
    store.set_meta("reviewed_mapping_authorities", ["local"])
    actor = BuildActor.reader(Principal.for_user(store.get_user(user), store.get_role("individual")))
    return SimpleNamespace(ctx=ctx, store=store, source=source, actor=actor)


def make_run(w, *, should_stop=None, on_progress=None, options=None, **kwargs):
    return BuildRun(
        w.ctx,
        w.actor,
        w.source,
        options if options is not None else Options(),
        should_stop if should_stop is not None else (lambda: False),
        on_progress,
        **kwargs,
    )


def live_renewal_workers():
    return [t for t in threading.enumerate() if t.name == RENEWAL_THREAD and t.is_alive()]


# ------------------------------------------------------------- the failure latch


def test_the_first_failure_is_the_one_every_later_checkpoint_reports(world):
    """Latched once: the run never reports a second, downstream failure instead."""
    raised = [RuntimeError("first"), RuntimeError("second")]
    run = make_run(world, on_progress=lambda update: (_ for _ in ()).throw(raised.pop(0)))
    try:
        with pytest.raises(RuntimeError, match="first"):
            run.progress("capture")
        with pytest.raises(RuntimeError, match="first"):
            run.check()
        # The callback is never reached again, so "second" cannot replace the latch.
        with pytest.raises(RuntimeError, match="first"):
            run.progress("extract", 1, 2)
        assert len(raised) == 1
    finally:
        run.close()


def test_a_healthy_run_checkpoints_without_raising(world):
    run = make_run(world)
    try:
        run.check()
        run.check()
    finally:
        run.close()


# --------------------------------------------------------------- cancellation


def test_cancellation_reaches_the_next_checkpoint_and_not_before(world):
    stopping = []
    run = make_run(world, should_stop=lambda: bool(stopping))
    try:
        run.check()
        stopping.append(True)
        with pytest.raises(BuildCancelled, match="Plain source build cancelled"):
            run.check()
    finally:
        run.close()


def test_the_cancellation_message_belongs_to_the_lane_not_the_shared_run(world):
    run = make_run(world, should_stop=lambda: True, cancelled_message="Code source build cancelled")
    try:
        with pytest.raises(BuildCancelled) as raised:
            run.check()
        assert str(raised.value) == "Code source build cancelled"
    finally:
        run.close()


def test_a_closed_run_is_cancelled_for_every_later_caller(world):
    run = make_run(world)
    run.close()
    with pytest.raises(BuildCancelled, match="Plain source build cancelled"):
        run.check()


def test_check_nests_its_own_transaction_rather_than_refusing_an_ambient_one(world):
    """The no-ambient-transaction rule is the coordinator's entry probe, not this.

    `BuildAuthority.check` refuses an ambient transaction because it brackets
    arbitrary external work; `BuildRun.check` holds only local reads and opens
    its own transaction around them, which is what lets the renewal worker
    checkpoint while another thread owns one. Pinned because the run is now
    shared and a refusal added here would break both lanes silently.
    """
    run = make_run(world)
    try:
        with world.store.transaction():
            run.check()
    finally:
        run.close()


# --------------------------------------------------------------- lease renewal


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "Plain build lease renewal failed"),
        ({"renewal_failed_message": "Code build lease renewal failed"}, "Code build lease renewal failed"),
    ],
)
def test_renew_reports_any_lost_lease_as_a_single_authorization_change(world, kwargs, message):
    run = make_run(world, **kwargs)
    try:
        run.guard.close()  # the guard a renewal re-proves is gone
        with pytest.raises(AuthorizationChanged) as raised:
            run.renew()
        assert str(raised.value) == message
        assert isinstance(raised.value.__cause__, AuthorizationChanged)
        assert str(raised.value.__cause__) != message
    finally:
        run.close()


def test_renew_lets_cancellation_through_unwrapped(world):
    """Cancellation is the caller's own decision, not a lost lease."""
    run = make_run(world, should_stop=lambda: True)
    try:
        with pytest.raises(BuildCancelled, match="Plain source build cancelled"):
            run.renew()
    finally:
        run.close()


def test_start_runs_a_renewal_worker_that_pause_joins_without_faulting_the_run(world):
    run = make_run(world, options=Options(lease_duration_seconds=2, renewal_interval_seconds=0.01))
    try:
        assert not live_renewal_workers()
        run.start()
        assert live_renewal_workers()
        run.pause()
        assert run.heartbeat is None and not live_renewal_workers()
        run.check()
    finally:
        run.close()


# --------------------------------------------------------------- guard handover


def test_adopt_closes_the_guard_it_replaces(world):
    run = make_run(world)
    try:
        previous = run.guard
        fresh = capture_build_authority(
            world.store, source_id=world.source, actor=world.actor, clock=world.store._now
        )
        run.adopt(fresh)
        assert run.guard is fresh
        fresh.check_local()
        with pytest.raises(AuthorizationChanged, match="Build authority is closed"):
            previous.check_local()
    finally:
        run.close()


def test_close_stops_the_renewal_worker_before_it_closes_the_guard(world, monkeypatch):
    order = []
    worker_close, guard_close = LeaseHeartbeat.close, BuildAuthority.close
    monkeypatch.setattr(LeaseHeartbeat, "close", lambda w: (order.append("heartbeat"), worker_close(w))[1])
    monkeypatch.setattr(BuildAuthority, "close", lambda g: (order.append("guard"), guard_close(g))[1])
    run = make_run(world, options=Options(lease_duration_seconds=2, renewal_interval_seconds=0.01))
    run.start()
    run.close()
    assert order == ["heartbeat", "guard"]
    assert run.heartbeat is None and not live_renewal_workers()
    with pytest.raises(AuthorizationChanged, match="Build authority is closed"):
        run.guard.check_local()


def test_close_releases_the_guard_even_when_joining_the_worker_fails(world, monkeypatch):
    worker_close = LeaseHeartbeat.close

    def close(worker):
        worker_close(worker)
        raise RuntimeError("join reported a fault")

    monkeypatch.setattr(LeaseHeartbeat, "close", close)
    run = make_run(world, options=Options(lease_duration_seconds=2, renewal_interval_seconds=0.01))
    run.start()
    with pytest.raises(RuntimeError, match="join reported a fault"):
        run.close()
    assert not live_renewal_workers()
    with pytest.raises(AuthorizationChanged, match="Build authority is closed"):
        run.guard.check_local()


# ------------------------------------------------------------------- progress


def test_progress_hands_the_callback_one_frozen_update(world):
    seen = []
    run = make_run(world, on_progress=seen.append)
    try:
        run.progress("capture")
        run.progress("extract", 3, 7)
        assert seen == [BuildProgress("capture", 0, 0), BuildProgress("extract", 3, 7)]
        with pytest.raises(FrozenInstanceError):
            seen[0].completed = 1
    finally:
        run.close()


def test_progress_without_a_callback_is_still_a_cancellation_checkpoint(world):
    run = make_run(world, should_stop=lambda: True, on_progress=None)
    try:
        with pytest.raises(BuildCancelled):
            run.progress("capture")
    finally:
        run.close()


# -------------------------------------------------------------------- receipt


def test_a_receipt_counts_no_resumed_batches_and_no_rebaselines_until_a_lane_says_so(world):
    receipt = BuildReceipt("s1", "g1", "e1", "h1", "published")
    assert (receipt.resumed_from_batches, receipt.rebaselines) == (0, 0)
    assert receipt == BuildReceipt("s1", "g1", "e1", "h1", "published", 0, 0)
    assert BuildReceipt("s1", "g1", "e1", "h1", "published", 2, 1).resumed_from_batches == 2


def test_a_receipt_is_frozen_and_names_no_path_no_text_and_no_exception_body(world):
    receipt = BuildReceipt("s1", "g1", "e1", "h1", "published")
    with pytest.raises(FrozenInstanceError):
        receipt.outcome = "failed"
    assert set(vars(receipt)) == {
        "source_id",
        "generation_id",
        "event_id",
        "accepted_input_hash",
        "outcome",
        "resumed_from_batches",
        "rebaselines",
    }


# ------------------------------------------------------- the write credentials


def test_credentials_name_the_fence_every_staged_write_carries():
    job = SimpleNamespace(id="job-1", lease_owner="owner-1", fencing_token=4)
    assert credentials(job) == {"job_id": "job-1", "lease_owner": "owner-1", "fencing_token": 4}


def test_authority_fields_name_the_epochs_frozen_at_capture(world):
    run = make_run(world)
    try:
        assert authority_fields(run.guard) == {
            "expected_authorization_epoch": run.guard.expected_authorization_epoch,
            "expected_suppression_epoch": run.guard.expected_suppression_epoch,
        }
    finally:
        run.close()


# ------------------------------------------------------------------- the seams


def test_the_prose_coordinator_still_answers_to_every_name_the_extraction_moved():
    """No caller changes its imports, and `_Run` is the moved class itself."""
    from hippo.ingest import prose_generation

    for name in ("BuildCancelled", "BuildBusy", "BuildProgress", "BuildReceipt"):
        assert getattr(prose_generation, name) is getattr(build_run, name)
    assert prose_generation._Run is BuildRun
    assert prose_generation._credentials is credentials
    assert prose_generation._authority_fields is authority_fields


def test_the_shared_run_loads_without_either_coordinator():
    """The point of the extraction: the code lane must not import the prose lane."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, hippo.ingest.build_run\n"
            "print('\\n'.join(sorted(n for n in sys.modules if n.startswith('hippo.ingest'))))\n",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.split() == ["hippo.ingest", "hippo.ingest.build_run"], result.stdout
