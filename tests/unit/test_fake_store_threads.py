"""The Fake store serializes knowledge reads and writes across threads, as a real store does.

A held query renews its snapshot lease on a heartbeat thread while a build writes on the caller's
thread (`query_session`, `LeaseHeartbeat`). On LadybugDB and Neo4j the database serializes the two.
On the Fake double both walk and fill the same per-kind dicts, so an unserialized read iterating a
kind while the other thread puts into it raises `dictionary changed size during iteration`. CC11's
CD9 scenario hit exactly that at its full size, as a failed lease renewal.

The test makes the interleaving deterministic rather than hoping a thread scheduler produces it: a
row-like object inside the kind hands control to a writer thread in the middle of the read and
waits briefly for the write to land.
"""

from __future__ import annotations

import threading

from hippo.knowledge import model as k
from tests.fakes.fake_store import FakeStore

GENERATION = "generation-threads"


def member(record_id):
    return k.GenerationEvidenceMember(
        generation_id=GENERATION, record_kind="EvidenceSpan", record_id=record_id
    )


class Interleave:
    """A stored row whose `generation_id` read lets another thread write before it answers."""

    def __init__(self, store, written):
        self.store, self.written = store, written

    @property
    def generation_id(self):
        writer = threading.Thread(
            target=lambda: (self.store._write_knowledge(member("late")), self.written.set())
        )
        writer.start()
        # An unserialized store lets the write land in the very dict this read is walking. A
        # serialized one walks a copy taken under the store lock, so the write lands beside it.
        self.written.wait(0.5)
        self.writer = writer
        return "another-generation"


def test_a_knowledge_read_and_a_write_from_another_thread_never_interleave():
    store = FakeStore()
    written = threading.Event()
    interleave = Interleave(store, written)
    rows = store._knowledge_data.setdefault("GenerationEvidenceMember", {})
    rows["interleave"] = interleave
    for index in range(3):
        record = member(f"span-{index}")
        rows[record.id] = record

    found = store._knowledge_rows("GenerationEvidenceMember", generation_id=GENERATION)

    interleave.writer.join(5)
    assert written.is_set(), "the writer completes once the read releases the store"
    assert {row.record_id for row in found} == {"span-0", "span-1", "span-2"}
    assert member("late").id in store._knowledge_data["GenerationEvidenceMember"]
