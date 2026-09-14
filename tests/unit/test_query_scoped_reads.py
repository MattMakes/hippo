"""Query-time knowledge reads: scoped by the selected generations, never whole-table.

KSCOPE scoped the knowledge reads a managed *build* makes (`evidence-kscope.md`). A *query* still
read the generation-sized kinds whole, and CC11 measured the cost (`evidence-cc11.md`): 30+
whole-table reads during one lease renewal, and on LadybugDB at about 50 files a projection of
427 s and a dense dispatch of more than seven minutes. The reads behind it:

* `EvidenceAccess.build` read every knowledge kind whole for every proof. A structural session
  builds one proof per workspace at open and one for its snapshot bundle, and every renewal
  rebuilds both.
* The proof and the projection validated each rendered view against a fresh `_Inventory`, two
  member-table reads per view.
* `project_managed_graph` fetched the proof's records by walking each kind for the authorized IDs.
* The session's strict-manifest test and the snapshot's publication receipt read `IndexManifest`
  and `IndexEvent` whole, and collecting a generation walked its kinds.

Three kinds of assertion, as in `test_knowledge_scoped_reads`: equal results against the unscoped
form, no whole-table read of a generation-sized kind across a query's whole life, and membership
read a constant number of times per generation rather than once per view.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from threading import Event, current_thread
from typing import NamedTuple

import pytest

from hippo.access import EVERYTHING, Access
from hippo.knowledge import model as k
from hippo.knowledge.access import EvidenceSelection
from hippo.knowledge.dense_session import dense_session, retrieval_session
from hippo.knowledge.projection import project_managed_graph
from hippo.knowledge.query_access import query_session
from hippo.knowledge.temporal import _RETAINED_GENERATIONS, _retention_gaps
from tests.unit.test_build_authority import join_group
from tests.unit.test_code_generation import build, refreshed, world  # noqa: F401
from tests.unit.test_dense_session import verified
from tests.unit.test_generation_store import (
    NOW,
    authority,
    claim,
    evidence,
    generation,
    passage,
    publish,
    seal,
)
from tests.unit.test_knowledge_scoped_reads import GENERATION_SIZED, rendered_rows
from tests.unit.test_structural_loading import published

MEMBER_KINDS = ("GenerationEvidenceMember", "GenerationMember")


class Read(NamedTuple):
    kind: str
    scoped: bool
    caller: str  # `module.py:function` of the direct caller


# R21-m4, left named by the CD10 review and owned by no fix slice: `AppContext._graph_for` decides which
# loader can answer from the whole `Artifact` table on every graph it builds (`context.py:243`). It is
# the one whole read of a generation-sized kind a query still makes, pinned by its caller so that any
# other whole `Artifact` read -- a proof's included -- still fails these tests.
KNOWN_WHOLE_READS = frozenset({("Artifact", "context.py:_graph_for")})


@contextmanager
def knowledge_reads(store):
    """Every `_knowledge_rows` call on every thread, the lease heartbeat's included, as a `Read`.

    A plain function as the instance attribute, removed again on exit rather than replaced by the
    bound method: the Fake store deep-copies its attributes at every transaction, and a bound
    method stored there would copy the store inside itself (`evidence-cc11.md`, finding 20).
    """
    reads = []
    original = store._knowledge_rows

    def knowledge_rows(name, **scope):
        code = sys._getframe(1).f_code
        caller = f"{Path(code.co_filename).name}:{code.co_name}"
        reads.append(Read(name, any(value is not None for value in scope.values()), caller))
        return original(name, **scope)

    store._knowledge_rows = knowledge_rows
    try:
        yield reads
    finally:
        del store._knowledge_rows


def whole_generation_sized(reads):
    return sorted(
        {
            read.kind
            for read in reads
            if read.kind in GENERATION_SIZED
            and not read.scoped
            and (read.kind, read.caller) not in KNOWN_WHOLE_READS
        }
    )


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


def test_retention_gaps_answer_as_the_whole_membership_walk_did(store):
    retired = generation(store, "retained")
    job = claim(store, retired)
    with store.generation_write(retired.id, **authority(job)):
        kept, span = evidence(store, retired)
        store.add_passages([passage(retired, kept, span)])
    seal(store, retired, job)
    publish(store, retired, job)
    staged = generation(store, "staged")
    with store.generation_write(staged.id, **authority(claim(store, staged))):
        orphan, _ = evidence(store, staged)
    asked = {kept.id, orphan.id, "no-such-revision"}

    def reference(revisions):  # the reviewed body, verbatim, as the oracle
        retained = set()
        for member in store._knowledge_rows("GenerationMember"):
            gen = store._knowledge_get("Generation", member.generation_id)
            if gen is not None and gen.status in _RETAINED_GENERATIONS:
                retained.add(member.artifact_revision_id)
        return sorted(revisions - retained)

    expected = reference(asked)
    assert expected == sorted({orphan.id, "no-such-revision"})
    with knowledge_reads(store) as reads:
        assert _retention_gaps(store, asked) == expected
    assert whole_generation_sized(reads) == []


# --------------------------------------------------------------- bounded work


def query_life(ctx, monkeypatch, access=EVERYTHING):
    """A query's whole life, recording every knowledge read on every thread.

    One structural session opens, its lease renews on the heartbeat thread and once more in place,
    it closes, and then a `retrieval_session` and a `dense_session` each route verified evidence.
    Only the held session's heartbeat is quickened; the dispatched sessions keep the default.
    """
    renewed, quickened = Event(), []
    graph_for, renew = ctx.graph_for, ctx.store.renew_snapshot_reference

    def quick_graph_for(*args, **kwargs):
        graph = graph_for(*args, **kwargs)
        if not quickened:
            quickened.append(graph)
            graph.snapshot_renewal_interval = 0.01
        return graph

    def observed_renew(*args, **kwargs):
        result = renew(*args, **kwargs)
        if current_thread().name == "hippo-lease-renewal":
            renewed.set()
        return result

    monkeypatch.setattr(ctx, "graph_for", quick_graph_for)
    monkeypatch.setattr(ctx.store, "renew_snapshot_reference", observed_renew)
    with knowledge_reads(ctx.store) as reads:
        with query_session(ctx, access, structural=True) as session:
            assert renewed.wait(30), "the heartbeat renewed the held snapshot"
            session.validate()
            selected = session.graph.selected_managed_generations
        with retrieval_session(ctx, access) as routed:
            assert routed.graph.dense_capability.mode == "verified"
        with dense_session(ctx, access) as dense:
            assert dense.graph.dense_capability.mode == "verified"
    return selected, reads


def test_a_code_query_reads_no_generation_sized_table_whole(world, monkeypatch):  # noqa: F811
    w = world
    first, tree = refreshed(w)
    second = build(w, tree=tree, operation="refresh")
    assert w.store._knowledge_get("Generation", first.generation_id).status == "retired"
    selected, reads = query_life(w.ctx, monkeypatch)
    assert selected == ((w.source, second.generation_id),)
    assert whole_generation_sized(reads) == []
    # The pinned exception is still made; fixing R21-m4 removes it from `KNOWN_WHOLE_READS` too.
    assert {(read.kind, read.caller) for read in reads if not read.scoped} >= KNOWN_WHOLE_READS


def test_a_group_member_readers_code_query_reads_no_generation_sized_table_whole(world, monkeypatch):  # noqa: F811
    """R21-M2 on the query side: the builder queries as a reader who belongs to a group."""
    w = world
    build(w)
    group = join_group(w)
    selected, reads = query_life(w.ctx, monkeypatch, access=Access(rank=0, user_id=w.user))
    assert selected and selected[0][0] == w.source
    assert whole_generation_sized(reads) == []
    assert any(read.kind == "KnowledgeObject" and read.scoped for read in reads), group.id


def test_a_prose_query_reads_no_generation_sized_table_whole(ctx, tmp_path, monkeypatch):
    prepared, _ = verified(ctx, tmp_path)
    gen = prepared.inputs.generation
    assert ctx.store._knowledge_get("Generation", gen.parent_id).status == "retired"
    selected, reads = query_life(ctx, monkeypatch)
    assert selected == ((gen.source_id, gen.id),)
    assert whole_generation_sized(reads) == []


def rendered_generation(store, size):
    """A published generation of `size` rendered passages, each over its own span and view."""
    gen = generation(store, f"rendered-{size}")
    job = claim(store, gen)
    with store.generation_write(gen.id, **authority(job)):
        store.add_passages(rendered_rows(store, gen, size))
    seal(store, gen, job)
    publish(store, gen, job)
    selection = EvidenceSelection(generation_ids=frozenset({gen.id}), require_exact_membership=True)
    _, proof = store._reader_proof(
        store.get_source(gen.source_id)["workspace_id"], EVERYTHING, selection=selection
    )
    return gen, proof


def test_a_proof_reads_membership_a_constant_number_of_times_whatever_its_views(store):
    """`_authorized_derivations` validated each selected view against a fresh `_Inventory`."""
    counts = {}
    for size in (4, 16):
        gen, proof = rendered_generation(store, size)
        assert len(proof.retrieval_view_ids) == size
        with knowledge_reads(store) as reads:
            _, again = store._reader_proof(
                store.get_source(gen.source_id)["workspace_id"], EVERYTHING, selection=proof.selection
            )
        assert again == proof
        counts[size] = len([read for read in reads if read.kind in MEMBER_KINDS])
    assert counts[16] == counts[4], f"member reads per proof: {counts[4]} for 4 views, {counts[16]} for 16"


def test_a_projection_reads_membership_a_constant_number_of_times_whatever_its_passages(store):
    """`_safe_vectors` validated each rendered passage's view against a fresh `_Inventory`."""
    counts = {}
    for size in (4, 16):
        gen, proof = rendered_generation(store, size)
        with knowledge_reads(store) as reads:
            graph = project_managed_graph(
                None,
                store,
                proof,
                source_profiles={gen.source_id: gen.embedding_profile},
                selected_generations={gen.source_id: gen.id},
                structural=True,
            )
        assert len(graph.passages) == size
        assert whole_generation_sized(reads) == []
        counts[size] = len([read for read in reads if read.kind in MEMBER_KINDS])
    assert counts[16] == counts[4], f"member reads per projection: {counts[4]} for 4, {counts[16]} for 16"


def test_a_whole_inventory_proof_reads_no_kind_it_has_nothing_to_look_up_in(store):
    """A proof reads `KnowledgeObject` to look up a group membership's or an observation's object, and
    `Assertion` to look up a version's assertion. With nothing to look up it reads neither: CC11's
    build counts at N=8 found 6,602 whole `KnowledgeObject` reads from proofs that asked for no ID."""
    _, span = published(store, "nothing-to-look-up")
    for kind in ("GroupMembership", "ObjectObservation", "AssertionSupport"):
        assert store._knowledge_rows(kind) == []
    workspace = store._knowledge_get("AccessPolicy", span.policy_id).workspace_id
    with knowledge_reads(store) as reads:
        _, proof = store._reader_proof(workspace, EVERYTHING)
    assert span.id in proof.span_ids
    assert {"KnowledgeObject", "Assertion"} & {read.kind for read in reads} == set()


def test_a_group_member_reader_proof_looks_its_groups_up_by_id(store):
    """R21-M2: a whole-inventory proof -- a legacy reader's, the build authority's -- read the whole
    `KnowledgeObject` table to resolve a reader's groups, whatever else the table held."""
    _, span = published(store, "grouped")
    workspace = store._knowledge_get("AccessPolicy", span.policy_id).workspace_id
    store.ensure_roles()
    user = store.create_user("reader", "password", "individual")
    store.set_meta("reviewed_mapping_authorities", ["local"])
    group = k.KnowledgeObject(workspace_id=workspace, kind="group", canonical_key='["readers"]')
    for record in (
        k.WorkspaceMembership(
            workspace_id=workspace, principal_id=user, mapping_authority="local", enabled=True, policy_epoch=1
        ),
        group,
        k.KnowledgeObject(workspace_id=workspace, kind="symbol", canonical_key='["unrelated","f"]'),
        k.GroupMembership(
            workspace_id=workspace,
            group_id=group.id,
            principal_id=user,
            enabled=True,
            mapping_authority="local",
            policy_epoch=1,
        ),
    ):
        store.put_knowledge(record)
    with knowledge_reads(store) as reads:
        _, proof = store._reader_proof(workspace, Access(rank=0, user_id=user))
    assert span.id in proof.span_ids
    assert [read.scoped for read in reads if read.kind == "KnowledgeObject"] == [True]


def test_collecting_a_retired_generation_reads_no_generation_sized_table_whole(store):
    first = generation(store, "collected")
    job = claim(store, first)
    with store.generation_write(first.id, **authority(job)):
        revision, span = evidence(store, first)
        store.add_passages([passage(first, revision, span)])
    seal(store, first, job)
    publish(store, first, job)
    second = generation(store, "collected", parent=first)
    job = claim(store, second, key="second")
    with store.generation_write(second.id, **authority(job)):
        revision, span = evidence(store, second)
        store.add_passages([passage(second, revision, span)])
    seal(store, second, job)
    publish(store, second, job)
    assert store._knowledge_get("Generation", first.id).status == "retired"
    with knowledge_reads(store) as reads:
        result = store.collect_generation(first.id)
    assert result.blocked_reason is None and result.removed_records
    assert store._knowledge_rows("GenerationMember", generation_id=first.id) == []
    assert whole_generation_sized(reads) == []
