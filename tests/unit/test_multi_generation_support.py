"""A proof group belongs to exactly one generation, so a relation has exactly one contributor.

PA2 finding 5 asked for the multi-contributor fixture: a relation supported by two
generations of two sources, both enriching one `(assertion_version_id, derivation_group)`
proof group, so that `status.py`'s `pair in row.source_generations` and
`knowledge/access.py`'s grouping across all authorized rows would see a second pair. No such
shape exists. The sequential order is refused while the group is frozen
(`store/generations.py:690`), and the interleaved order -- both generations in staging, one
joining the other's group before either seals -- is refused at seal time, because sealing a
generation that carries an `AssertionVersion` requires *every* `AssertionSupport` row for that
version to be in that same generation's exact interpretation (`store/generations.py:1001`).
Neither side can borrow the other's support to complete the group, and no generation can hold
a second source's revisions at all (`store/knowledge.py:690`), so the group's spans always
resolve to one source.

Each refusal is pinned below, with the invariant that follows from them: every relation a
sealed exact view can project carries exactly one `(source_id, generation_id)` pair. Each pin
guards its own rule: relaxing the seal-time clause alone fails the two seal tests and leaves
the rest green, and it is that relaxation which would make the multi-contributor coverage
writable for the first time.
"""

from datetime import UTC, datetime

import pytest

from hippo.access import EVERYTHING
from hippo.knowledge import model as k
from hippo.knowledge.identity import text_hash
from hippo.knowledge.query_access import query_session
from hippo.status import source_view
from tests.unit.test_derived_generation_store import member
from tests.unit.test_managed_source_inventory import row_of
from tests.unit.test_structural_loading import Offline, published, shared_pair


def authority_for(store, gen):
    """The running build lease `published()` claimed for this generation."""
    job = next(row for row in store._knowledge_rows("MaintenanceJob") if row.input_fingerprint == gen.id)
    return dict(job_id=job.id, lease_owner=job.lease_owner, fencing_token=job.fencing_token)


def seal_and_publish(store, gen, *, profile="p"):
    """Finish a generation `published(publish=False)` left staging, under its own lease."""
    authority = authority_for(store, gen)
    manifest = k.IndexManifest(
        generation_id=gen.id,
        profile_fingerprint=profile,
        config_fingerprint="c",
        required_representations=("evidence", "dense", "native"),
        checksums=store.generation_checksums(gen.id),
        ready=True,
    )
    store.seal_generation(gen.id, manifest, **authority)
    store.publish_staged_generation(
        gen.id,
        expected_parent_id=gen.parent_id,
        expected_suppression_epoch=store.suppression_epoch(),
        published_at=datetime.now(UTC),
        **authority,
    )


def support_span(span):
    """The relation's own support span, as `shared_pair` writes it."""
    return span.replace(
        text="f is bound to g",
        text_hash=text_hash("f is bound to g"),
        locator_json='{"kind":"file_lines","path":"a.txt","start":3,"end":3}',
    )


def join_proof_group(store, gen, revision, span, now, *, version_id, member_version=True):
    """This generation's own endpoints, plus a second support in an existing proof group."""
    shared_pair(store, gen, revision, span, now)
    support = support_span(span)
    member(store, gen, support)
    if member_version:
        # Without this the support's own closure is incomplete; with it the seal demands the
        # whole group. Both halves are pinned below.
        store.put_knowledge(
            k.GenerationEvidenceMember(
                generation_id=gen.id, record_kind="AssertionVersion", record_id=version_id
            )
        )
    member(
        store,
        gen,
        k.AssertionSupport(assertion_version_id=version_id, span_id=support.id, derivation_group="declared"),
    )


def staged_support(store, key="first support"):
    """One staging generation holding a relation and its first support, and that version."""
    gen, span = published(
        store, key, publish=False, enrich=lambda *args: shared_pair(*args, relationship=True)
    )
    version = next(iter(store._knowledge_rows("AssertionVersion")))
    return gen, span, version


def staged_join(store, version, *, member_version=True):
    """A second source staging into `version`'s proof group while the first is still open."""
    gen, span = published(
        store,
        "second support",
        profile="q",
        dimension=3,
        publish=False,
        enrich=lambda *args: join_proof_group(*args, version_id=version.id, member_version=member_version),
    )
    return gen, span


# --------------------------------------------------- the group cannot span two generations


def test_a_second_source_cannot_join_a_published_proof_group(store):
    """The sequential shape: the first generation seals its group before the second arrives."""
    first, _, version = staged_support(store)
    seal_and_publish(store, first)
    with pytest.raises(ValueError, match="Sealed assertion proof group cannot gain support"):
        staged_join(store, version)


def test_the_interleaved_group_cannot_seal_the_versions_own_generation(store):
    """Both staging, the second joins, and now the *first* can never seal its own version."""
    first, _, version = staged_support(store)
    staged_join(store, version)
    with pytest.raises(ValueError, match="Incomplete assertion proof group"):
        seal_and_publish(store, first)


def test_the_interleaved_group_cannot_seal_the_joining_generation(store):
    """The same refusal from the other side: the joining generation carries the version too."""
    _, _, version = staged_support(store)
    second, _ = staged_join(store, version)
    with pytest.raises(ValueError, match="Incomplete assertion proof group"):
        seal_and_publish(store, second, profile="q")


def test_a_join_that_leaves_out_the_version_has_an_incomplete_closure(store):
    """Not membering the version does not dodge the rule; the support's closure is then open."""
    _, _, version = staged_support(store)
    second, _ = staged_join(store, version, member_version=False)
    with pytest.raises(ValueError, match="Incomplete exact interpretation closure"):
        seal_and_publish(store, second, profile="q")


def test_the_other_generations_support_cannot_be_borrowed_while_its_build_runs(store):
    """Completing the group by membering the first source's support needs *its* lease."""
    _, _, version = staged_support(store)
    foreign = next(iter(store._knowledge_rows("AssertionSupport")))
    second, _ = staged_join(store, version)
    with pytest.raises(ValueError, match="Managed evidence write requires build authority"):
        with store.generation_write(second.id, **authority_for(store, second)):
            store.put_knowledge(
                k.GenerationEvidenceMember(
                    generation_id=second.id, record_kind="AssertionSupport", record_id=foreign.id
                )
            )


def test_the_other_generations_support_cannot_be_borrowed_after_it_publishes(store):
    """And with the first build finished, the borrow is outside the second's own revisions."""
    first, _, version = staged_support(store)
    foreign = next(iter(store._knowledge_rows("AssertionSupport")))
    seal_and_publish(store, first)
    second, _ = published(store, "second support", profile="q", dimension=3, publish=False)
    with pytest.raises(ValueError, match="Evidence member is outside generation revisions"):
        with store.generation_write(second.id, **authority_for(store, second)):
            store.put_knowledge(
                k.GenerationEvidenceMember(
                    generation_id=second.id, record_kind="AssertionSupport", record_id=foreign.id
                )
            )


def test_no_generation_can_hold_a_second_sources_revision(store):
    """The last door: one generation cannot carry both sources' evidence in its raw manifest."""
    first, _, _ = staged_support(store)
    foreign = next(row for row in store._knowledge_rows("GenerationMember") if row.generation_id == first.id)
    second, _ = published(store, "second support", profile="q", dimension=3, publish=False)
    with pytest.raises(ValueError, match="Generation member belongs to another source"):
        with store.generation_write(second.id, **authority_for(store, second)):
            store.put_knowledge(
                k.GenerationMember(generation_id=second.id, artifact_revision_id=foreign.artifact_revision_id)
            )


# ------------------------------------------------------- the invariant that follows from them


def test_every_projected_relation_carries_exactly_one_contributing_pair(ctx):
    """The reachable shape, and the tripwire: one relation, one pair, one counted lane.

    Two published sources share the relation's endpoints and only one of them supports the
    relation, which is the most contributors a sealed proof group can have. A third source
    staging its own support is never selected, so it inflates no count either.
    """
    supporting, _, _ = staged_support(ctx.store, "relation support")
    seal_and_publish(ctx.store, supporting)
    endpoints, _ = published(ctx.store, "relation endpoints", profile="q", dimension=3, enrich=shared_pair)
    staging, _, _ = staged_support(ctx.store, "staged support")
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        assert [row.source_generations for row in graph.structural_relations] == [
            ((supporting.source_id, supporting.id),)
        ]
        assert {source for source, _ in graph.selected_managed_generations} == {
            supporting.source_id,
            endpoints.source_id,
        }
        view = source_view(ctx, EVERYTHING, session=session)
        assert row_of(view, supporting.source_id)["meta"]["code"]["edges_by_kind"]["BOUND_TO"] == 1
        assert row_of(view, endpoints.source_id)["meta"]["code"]["edges_by_kind"].get("BOUND_TO") is None
        assert row_of(view, staging.source_id) is None
        session.validate()
