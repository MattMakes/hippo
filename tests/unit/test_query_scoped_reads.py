"""Knowledge records read by primary key: one bounded read for a list of IDs.

A proof or a projection that already knows which records it serves fetches exactly those, through
`_knowledge_rows(kind, ids=...)`: one read driven by the key (`store.base.by_ids`, never a list
predicate), each record once, in the order asked. The consumers that read this way are covered in
the same module once they use it.
"""

from __future__ import annotations

import pytest

from hippo.knowledge import model as k
from tests.unit.test_generation_store import NOW
from tests.unit.test_structural_loading import published

# --------------------------------------------------------------- equal results


def test_records_read_by_id_are_the_unscoped_records_with_those_ids(store):
    _, first = published(store, "first")
    _, second = published(store, "second")
    whole = {row.id: row for row in store._knowledge_rows("EvidenceSpan")}
    asked = [second.id, first.id, second.id, "no-such-span"]
    assert store._knowledge_rows("EvidenceSpan", ids=asked) == [whole[second.id], whole[first.id]]
    assert store._knowledge_rows("EvidenceSpan", ids=[]) == []


def test_records_read_by_id_after_a_delete_in_the_open_transaction_are_the_asked_rows(store):
    """LadybugDB's `IN <list>` answered from another row in exactly this state (`evidence-lbfix.md`)."""
    workspace = store.get_source(store.create_source("text", "policies"))["workspace_id"]
    policies = [
        k.AccessPolicy(
            workspace_id=workspace,
            origin="local_curated",
            scope_key=f"scope-{index}",
            mode="workspace",
            verified_at=NOW,
        )
        for index in range(3)
    ]
    store.put_knowledge(policies[0])
    with store.transaction():
        store.put_knowledge(policies[1])
        store._delete_knowledge_record("AccessPolicy", policies[0].id)
        store.put_knowledge(policies[2])
        read = store._knowledge_rows("AccessPolicy", ids=[policies[2].id, policies[1].id, policies[0].id])
    assert read == [policies[2], policies[1]]


def test_an_id_read_is_not_combined_with_another_scope(store):
    with pytest.raises(ValueError, match="scoped by ids alone"):
        store._knowledge_rows("GenerationMember", ids=["a"], generation_id="g")
    with pytest.raises(ValueError, match="scoped by ids alone"):
        store._knowledge_rows("GenerationMember", ids=["a"], where={"generation_id": "g"})
