"""Exact selected generations make an empty managed source visible without leaking denied ones.

`GraphIndex.selected_managed_generations` is evidence-selection metadata: the
sorted, unique `(source_id, active_generation_id)` pairs this audience proved.
A pair exists only when the Source current pointer, the Generation, its raw
manifest `GenerationMember` revision and that revision's authorization all
agree, so an authorized generation that produced no evidence at all is still
representable while a policy-denied or tombstoned one is not.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from hippo.access import EVERYTHING, Access
from hippo.knowledge import model as k
from hippo.knowledge.access import AuthorizationChanged, EvidenceSelection
from hippo.knowledge.projection import ProjectionError, _assemble, compose_graphs, project_managed_graph
from hippo.knowledge.query_access import query_session
from hippo.knowledge.replay import view_fingerprint
from hippo.status import source_view
from tests.unit.test_store_knowledge import reader
from tests.unit.test_structural_loading import Offline, published, shared_code, shared_pair

# ----------------------------------------------------------------- fixtures


def empty_published(
    store,
    key,
    *,
    profile="p",
    parent=None,
    artifact_key=None,
    policy_mode="workspace",
    publish=True,
    owner=None,
    access_role_id=None,
):
    """One exact generation whose raw manifest carries no interpreted evidence.

    This is the shape a published empty plain-prose build leaves behind: an
    immutable Artifact/ArtifactRevision captured under a `GenerationMember`, a
    sealed ready manifest, and zero `EvidenceSpan` records. `published()` cannot
    express it because its dangling span makes `generation_checksums` demand
    dense passage coverage.
    """
    now = datetime.now(UTC)
    source = (
        parent.source_id
        if parent
        else store.create_source("text", key, owner_id=owner, access_role_id=access_role_id)
    )
    workspace = store.get_source(source)["workspace_id"]
    policy = k.AccessPolicy(
        workspace_id=workspace, origin="local_curated", scope_key=key, mode=policy_mode, verified_at=now
    )
    if parent:
        prior = next(row for row in store._knowledge_rows("Artifact") if row.source_id == source)
        policy = store._knowledge_get("AccessPolicy", prior.policy_id)
    external = artifact_key or key
    artifact = k.Artifact(
        workspace_id=workspace,
        source_id=source,
        kind="file",
        external_id=external,
        canonical_uri=external,
        policy_id=policy.id,
    )
    revision = k.ArtifactRevision(
        artifact_id=artifact.id, content_hash=key, raw_uri="blob:" + key, observed_at=now, lifecycle="active"
    )
    generation = k.Generation(
        source_id=source,
        parent_id=parent.id if parent else None,
        status="staging",
        parser_version="p",
        linker_version="l",
        embedding_profile=profile,
        created_at=now,
        manifest_hash=key,
    )
    for row in (policy, artifact, generation):
        store.put_knowledge(row)
    job = store.claim_generation_build(
        generation.id, job_key=key, lease_owner="inventory", lease_expires_at=now + timedelta(minutes=5)
    )
    authority = dict(job_id=job.id, lease_owner=job.lease_owner, fencing_token=job.fencing_token)
    with store.generation_write(generation.id, **authority):
        store.put_knowledge(revision)
        store.put_knowledge(k.GenerationMember(generation_id=generation.id, artifact_revision_id=revision.id))
    if publish:
        manifest = k.IndexManifest(
            generation_id=generation.id,
            profile_fingerprint=profile,
            config_fingerprint="c",
            required_representations=("evidence", "dense", "native"),
            checksums=store.generation_checksums(generation.id),
            ready=True,
        )
        store.seal_generation(generation.id, manifest, **authority)
        store.publish_staged_generation(
            generation.id,
            expected_parent_id=generation.parent_id,
            expected_suppression_epoch=store.suppression_epoch(),
            published_at=now,
            **authority,
        )
    return SimpleNamespace(
        generation=generation,
        revision=revision,
        artifact=artifact,
        policy=policy,
        authority=authority,
        source_id=source,
        pair=(source, generation.id),
    )


def row_of(view, source_id):
    return next((row for row in view.sources if row["id"] == source_id), None)


def tombstone(store, source_id):
    """The current-only all-principals Source suppression Task 1 commits on delete."""
    store.put_knowledge(
        k.Suppression(
            workspace_id=store.get_source(source_id)["workspace_id"],
            target_kind="source",
            target_id=source_id,
            scope_key=f"source:{source_id}:delete",
            view_applicability="current_only",
            reason="tombstone",
            epoch=store.suppression_epoch() + 1,
            created_at=datetime.now(UTC),
            restoration_barrier="operation-1",
        )
    )


def proof_for(store, source_id, generations, access=EVERYTHING):
    identities = frozenset(generations)
    return store._reader_proof(
        store.get_source(source_id)["workspace_id"],
        access,
        expected_epoch=store.authorization_epoch(),
        selection=EvidenceSelection(generation_ids=identities, require_exact_membership=True),
    )


# ------------------------------------------------- visibility of empty sources


def test_exact_empty_generation_is_visible_with_control_presentation_and_zero_counts(ctx):
    ctx.store.ensure_roles()
    owner = ctx.store.create_user("empty-owner", "secret1", "individual")
    built = empty_published(ctx.store, "Quarterly notes", owner=owner)
    ctx.store.update_source(built.source_id, status="ready", stage="", progress_done=3, progress_total=3)
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        assert session.graph.selected_managed_generations == (built.pair,)
        assert session.graph.num_nodes == 0
        view = source_view(ctx, EVERYTHING, session=session)
        row = row_of(view, built.source_id)
        assert row is not None, "an authorized empty generation must appear in the inventory"
        assert row["name"] == "Quarterly notes"
        assert row["managed"] is True
        assert row["status"] == "ready"
        assert row["progress_total"] == 3
        assert row["created_at"] == ctx.store.get_source(built.source_id)["created_at"]
        assert row["owner_id"] == owner
        assert row["passages"] == row["fact_links"] == 0
        assert row["meta"] == {}
        assert row["error"] == ""


def test_allowed_reader_sees_the_empty_source_and_a_denied_reader_does_not(ctx):
    ctx.store.ensure_roles()
    built = empty_published(ctx.store, "shared empty")
    private = empty_published(ctx.store, "restricted empty", access_role_id="arch-admin")
    workspace = ctx.store.get_source(built.source_id)["workspace_id"]
    allowed = reader(ctx.store, workspace, "allowed-reader")
    access = Access(rank=0, user_id=allowed)
    ctx.ollama = Offline()
    with query_session(ctx, access, structural=True) as session:
        assert session.graph.selected_managed_generations == (built.pair,)
        view = source_view(ctx, access, session=session)
        assert row_of(view, built.source_id) is not None
        assert row_of(view, private.source_id) is None
        assert private.source_id not in repr(view.sources)


def test_unauthorized_manifest_revision_produces_no_pair_when_only_the_acl_allows(ctx):
    allowed = empty_published(ctx.store, "policy allowed")
    denied = empty_published(ctx.store, "policy denied", policy_mode="restricted")
    workspace = ctx.store.get_source(allowed.source_id)["workspace_id"]
    access = Access(rank=0, user_id=reader(ctx.store, workspace, "policy-reader"))
    # The Source ACL alone permits both; only the artifact policy separates them.
    assert {row["id"] for row in ctx.store.list_sources(access)} >= {
        allowed.source_id,
        denied.source_id,
    }
    _, proof = proof_for(ctx.store, allowed.source_id, [allowed.generation.id], access=access)
    assert denied.revision.id not in proof.revision_ids
    ctx.ollama = Offline()
    with query_session(ctx, access, structural=True) as session:
        assert session.graph.selected_managed_generations == (allowed.pair,)
        view = source_view(ctx, access, session=session)
        assert row_of(view, allowed.source_id) is not None
        assert row_of(view, denied.source_id) is None


def test_current_only_source_suppression_removes_the_pair_and_the_row(ctx):
    built = empty_published(ctx.store, "tombstoned empty")
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        assert session.graph.selected_managed_generations == (built.pair,)
    tombstone(ctx.store, built.source_id)
    # The retained Source row is still administratively listed; only the missing
    # proven pair may remove it from the audience's inventory.
    assert built.source_id in {row["id"] for row in ctx.store.list_sources(EVERYTHING)}
    with query_session(ctx, EVERYTHING, structural=True) as session:
        assert session.graph.selected_managed_generations == ()
        assert row_of(source_view(ctx, EVERYTHING, session=session), built.source_id) is None


@pytest.mark.parametrize("outcome", ["staging", "failed"])
def test_unpublished_generations_never_produce_a_pair(ctx, outcome):
    built = empty_published(ctx.store, "unpublished", publish=False)
    if outcome == "failed":
        ctx.store.fail_generation_build(built.generation.id, **built.authority)
        assert ctx.store._knowledge_get("Generation", built.generation.id).status == "failed"
    assert ctx.store.get_source(built.source_id).get("active_generation_id") is None
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        assert session.graph.selected_managed_generations == ()
        assert row_of(source_view(ctx, EVERYTHING, session=session), built.source_id) is None


def test_retired_generation_is_replaced_by_its_successor_pair(ctx):
    first = empty_published(ctx.store, "revision one")
    second = empty_published(ctx.store, "revision two", parent=first.generation, artifact_key="revision one")
    assert ctx.store._knowledge_get("Generation", first.generation.id).status == "retired"
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        assert session.graph.selected_managed_generations == (second.pair,)
        assert first.generation.id not in repr(session.graph.selected_managed_generations)


def test_empty_publication_changes_the_audience_view_fingerprint(ctx):
    first = empty_published(ctx.store, "fingerprint one")
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        before = view_fingerprint(session.graph)
        assert session.graph.num_nodes == 0
    empty_published(ctx.store, "fingerprint two", parent=first.generation, artifact_key="fingerprint one")
    with query_session(ctx, EVERYTHING, structural=True) as session:
        assert session.graph.num_nodes == 0
        assert view_fingerprint(session.graph) != before, (
            "an empty G1 to empty G2 publication must change the view fingerprint"
        )


def test_empty_selection_resolves_no_profile_and_performs_no_model_request(ctx):
    from hippo.knowledge.dense_session import retrieval_session
    from tests.unit.test_embedding_profile import Server

    built = empty_published(ctx.store, "offline empty")
    server = Server()
    server.dimension = 2
    server.show["model_info"]["bert.embedding_length"] = 2
    ctx.ollama = server.client()
    with retrieval_session(ctx, EVERYTHING) as session:
        assert session.graph.selected_managed_generations == (built.pair,)
        assert session.graph.num_nodes == 0
    assert server.calls == [], "an empty selected pair must not trigger profile resolution or model I/O"


# --------------------------------------------- preservation through the lanes


def test_pair_survives_scope_and_is_dropped_with_its_source(ctx):
    first = empty_published(ctx.store, "kept empty")
    second = empty_published(ctx.store, "dropped empty")
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        assert graph.selected_managed_generations == tuple(sorted((first.pair, second.pair)))
        assert graph.scoped({first.source_id}).selected_managed_generations == (first.pair,)
        assert graph.scoped({second.source_id}).selected_managed_generations == (second.pair,)
        assert graph.scoped(set()).selected_managed_generations == ()


def test_scope_cannot_keep_a_pair_through_the_unchanged_graph_fast_path(ctx):
    """A source with no evidence must not ride `scoped`'s identity shortcut."""
    populated, _ = published(ctx.store, "populated")
    empty = empty_published(ctx.store, "invisible empty")
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        assert empty.pair in graph.selected_managed_generations
        scoped = graph.scoped({populated.source_id})
        assert scoped.selected_managed_generations == ((populated.source_id, populated.id),), (
            "scoping away an empty source must drop its pair"
        )
        assert len(scoped.passages) == len(graph.passages)


def test_compose_unions_pairs_and_refuses_two_generations_for_one_source():
    def lane(pairs):
        return _assemble({}, [], [], {}, [], {}, {}, [], selected_managed_generations=pairs)

    composed = compose_graphs(lane((("source-b", "gen-2"),)), lane((("source-a", "gen-1"),)))
    assert composed.selected_managed_generations == (("source-a", "gen-1"), ("source-b", "gen-2"))
    assert compose_graphs(lane(()), lane((("source-a", "gen-1"),))).selected_managed_generations == (
        ("source-a", "gen-1"),
    )
    with pytest.raises(ValueError):
        compose_graphs(lane((("source-a", "gen-1"),)), lane((("source-a", "gen-2"),)))


def test_structural_to_dense_activation_retains_the_selected_pairs(ctx, tmp_path, monkeypatch):
    from hippo.knowledge.dense_session import dense_session
    from tests.unit.test_dense_session import observe, verified

    prepared, _server = verified(ctx, tmp_path)
    empty = empty_published(ctx.store, "empty beside verified")
    held, _closed = observe(ctx, monkeypatch)
    with dense_session(ctx, EVERYTHING) as session:
        assert session.graph.dense_capability.mode == "verified"
        assert empty.pair in session.graph.selected_managed_generations
        assert session.graph.selected_managed_generations == held[0].selected_managed_generations
        assert prepared.inputs.generation.source_id in {
            source for source, _ in session.graph.selected_managed_generations
        }


def test_selected_pairs_are_canonical_immutable_and_single_valued():
    graph = _assemble({}, [], [], {}, [], {}, {}, [], selected_managed_generations=(("b", "2"), ("a", "1")))
    assert graph.selected_managed_generations == (("a", "1"), ("b", "2"))
    for bad in ([("a", "1")], (("a",),), (("a", "1", "x"),), (("a", ""),), ((1, "1"),), (("a", None),)):
        with pytest.raises(ValueError):
            replace(graph, selected_managed_generations=bad)
    with pytest.raises(ValueError):
        replace(graph, selected_managed_generations=(("a", "1"), ("a", "2")))
    with pytest.raises(TypeError):
        graph.selected_managed_generations[0][0] = "other"


# ------------------------------------------------------ the population rule


def test_projection_rejects_a_mapping_that_differs_from_the_authorized_selection(ctx):
    built = empty_published(ctx.store, "explicit mapping")
    _, proof = proof_for(ctx.store, built.source_id, [built.generation.id])
    profiles = {built.source_id: "p"}
    for mapping in (
        {},
        {"other-source": built.generation.id},
        {built.source_id: "other-generation"},
        {built.source_id: built.generation.id, "extra": built.generation.id},
    ):
        with pytest.raises(ProjectionError):
            project_managed_graph(
                None,
                ctx.store,
                proof,
                source_profiles=profiles,
                structural=True,
                selected_generations=mapping,
            )
    graph = project_managed_graph(
        None,
        ctx.store,
        proof,
        source_profiles=profiles,
        structural=True,
        selected_generations={built.source_id: built.generation.id},
    )
    assert graph.selected_managed_generations == (built.pair,)


def test_projection_without_an_explicit_mapping_claims_no_pair(ctx):
    built = empty_published(ctx.store, "no mapping")
    _, proof = proof_for(ctx.store, built.source_id, [built.generation.id])
    graph = project_managed_graph(
        None, ctx.store, proof, source_profiles={built.source_id: "p"}, structural=True
    )
    assert graph.selected_managed_generations == ()


# ------------------------------------------------------- provenance counting


def test_shared_code_object_counts_for_every_contributing_selected_source(ctx):
    first, _ = published(ctx.store, "first shared", enrich=shared_code)
    second, _ = published(ctx.store, "second shared", profile="q", dimension=3, enrich=shared_code)
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        assert len(graph.code_nodes) == 1, "the shared object stays one global vertex"
        view = source_view(ctx, EVERYTHING, session=session)
        for generation in (first, second):
            row = row_of(view, generation.source_id)
            assert row is not None
            assert row["meta"]["code"]["symbols"] == 1, generation.source_id
            assert row["meta"]["code"]["languages"] == []
            assert row["passages"] == 1


def test_relation_support_counts_only_for_the_contributing_generation(ctx):
    support, _ = published(
        ctx.store, "relation support", enrich=lambda *args: shared_pair(*args, relationship=True)
    )
    endpoints, _ = published(ctx.store, "relation endpoints", profile="q", dimension=3, enrich=shared_pair)
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        assert graph.structural_relations[0].source_generations == ((support.source_id, support.id),)
        view = source_view(ctx, EVERYTHING, session=session)
        supporting = row_of(view, support.source_id)
        other = row_of(view, endpoints.source_id)
        assert supporting["meta"]["code"]["edges_by_kind"].get("BOUND_TO") == 1
        assert other["meta"]["code"]["edges_by_kind"].get("BOUND_TO") is None
        assert supporting["meta"]["code"]["symbols"] == other["meta"]["code"]["symbols"] == 2


def test_fact_links_come_from_retained_support_of_the_sources_own_passages(ctx):
    from tests.unit.test_structural_loading import enrich

    built, _ = published(ctx.store, "prose facts", enrich=enrich)
    other = empty_published(ctx.store, "no facts")
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        assert len(graph.facts) == 1
        expected = sum(
            1
            for fact in graph.facts
            for passage in fact.passage_ids
            if passage in {row.id for row in graph.passages if row.source_id == built.source_id}
        )
        assert expected == 1
        view = source_view(ctx, EVERYTHING, session=session)
        assert row_of(view, built.source_id)["fact_links"] == 1
        assert row_of(view, other.source_id)["fact_links"] == 0


def test_staging_contributions_do_not_inflate_current_counts(ctx):
    first, _ = published(ctx.store, "current code", enrich=shared_code)
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        before = row_of(source_view(ctx, EVERYTHING, session=session), first.source_id)
        assert before["meta"]["code"]["symbols"] == 1
    published(ctx.store, "staged code", parent=first, publish=False, enrich=shared_code)
    with query_session(ctx, EVERYTHING, structural=True) as session:
        assert row_of(source_view(ctx, EVERYTHING, session=session), first.source_id) == before


def test_retired_contributions_do_not_inflate_current_counts_or_raw_store_counts(ctx):
    first, _ = published(ctx.store, "current code", enrich=shared_code)
    second, _ = published(ctx.store, "next code", parent=first, enrich=shared_code)
    assert ctx.store._knowledge_get("Generation", first.id).status == "retired"
    # Both generations' native passages are retained, so the raw Source count
    # spans history and can never be a managed public row's count.
    assert ctx.store.get_source(first.source_id)["passages"] == 2
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        assert graph.selected_managed_generations == ((first.source_id, second.id),)
        row = row_of(source_view(ctx, EVERYTHING, session=session), first.source_id)
        assert row["passages"] == 1, "managed counts come from held-graph provenance only"
        assert row["meta"]["code"]["symbols"] == 1
        assert all(item.generation_id == second.id for item in graph.structural_code_evidence)


# --------------------------------------------------- validation after output


def test_held_session_is_validated_after_dto_construction(ctx, monkeypatch):
    import hippo.status as status

    ctx.store.ensure_roles()
    built = empty_published(ctx.store, "revoked during render")
    ctx.ollama = Offline()
    original, denied = status._managed_source, []

    def revoke(source, graph):
        row = original(source, graph)
        ctx.store.set_source_access(built.source_id, "arch-admin")
        return row

    # The session's own release also denies, so record where the denial happened rather than
    # letting the context manager's exit stand in for the check under test.
    with pytest.raises(AuthorizationChanged):
        with query_session(ctx, EVERYTHING, structural=True) as session:
            monkeypatch.setattr(status, "_managed_source", revoke)
            try:
                source_view(ctx, EVERYTHING, session=session)
            except AuthorizationChanged:
                denied.append("after DTO construction")
                raise
    assert denied == ["after DTO construction"], "a row built under revoked authority must not be released"
