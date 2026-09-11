"""Managed graph reads never fall through to legacy source-level authorization."""

import pytest

from hippo.access import Access, Principal
from hippo.hipporag.indexer import Chunk, index_source
from tests.unit.test_store_knowledge import foundation


@pytest.mark.parametrize("surface", ["reader_graph", "/api/entities?q=SECRET", "/api/graph/full"])
def test_orphan_native_nodes_are_hidden_even_when_all_passages_are_visible(ctx, surface):
    from fastapi.testclient import TestClient

    from hippo.web.app import create_app

    ctx.store.ensure_roles()
    user_id = ctx.store.create_user("reader", "password123", "individual")
    public = ctx.store.create_source("text", "Public")
    index_source(ctx.store, ctx.ollama, public, [Chunk(0, "Public", "Public prose.")])
    hidden = ctx.store.create_source("code", "SECRET source")
    ctx.store.set_source_access(hidden, "local-admin")
    ctx.store.add_symbols(
        [
            dict(
                id="SECRET-symbol",
                source_id=hidden,
                name="SECRET symbol",
                kind="function",
                embedding=[1.0, 0.0],
            )
        ]
    )
    ctx.store.add_entities([dict(id="SECRET-entity", name="SECRET entity", embedding=[1.0, 0.0])])
    ctx.store.bump_graph_version()
    # Staged/orphan native nodes exist but have no defining/mention passage proving reader access.
    assert {"SECRET-symbol", "SECRET-entity"} <= set(ctx.graph().node_ids)
    if surface == "reader_graph":
        graph = ctx.graph_for(Access(rank=0, user_id=user_id))
        assert "SECRET" not in repr(graph.node_ids)
        assert "SECRET" not in repr(graph.entity_names)
        assert "SECRET" not in repr(graph.code_nodes)
    else:
        with TestClient(create_app(ctx), base_url="http://localhost") as client:
            assert (
                client.post("/login", data={"username": "reader", "password": "password123"}).status_code
                == 200
            )
            response = client.get(surface)
            assert response.status_code == 200, response.text
            assert "SECRET" not in response.text


def test_unstated_fact_is_not_reader_evidence_even_when_its_entities_are_public(ctx):
    ctx.store.ensure_roles()
    source = ctx.store.create_source("text", "Public")
    index_source(ctx.store, ctx.ollama, source, [Chunk(0, "Public", "Public prose.")])
    passage = ctx.store.load_passages()[0]["id"]
    ctx.store.add_entities(
        [dict(id=identity, name=identity, embedding=[1.0, 0.0]) for identity in ("entity-a", "entity-b")]
    )
    ctx.store.link_passage_entities([(passage, "entity-a"), (passage, "entity-b")])
    ctx.store.add_facts(
        [
            dict(
                id="fact-SECRET",
                subject="entity-a",
                predicate="SECRET relationship",
                object="entity-b",
                subject_id="entity-a",
                object_id="entity-b",
                embedding=[1.0, 0.0],
            )
        ]
    )
    ctx.store.bump_graph_version()
    assert ctx.graph().facts
    graph = ctx.graph_for(Access(rank=0, user_id="reader"))
    assert graph.facts == []


def test_reader_graph_version_does_not_expose_private_indexing_counter(ctx):
    ctx.store.ensure_roles()
    source = ctx.store.create_source("text", "public")
    index_source(ctx.store, ctx.ollama, source, [Chunk(0, "Title", "Mira designed Orion.")])
    access = Access(rank=0, user_id="reader")
    before = ctx.graph_for(access)
    ctx.store.bump_graph_version()  # A private-only publication also advances this counter.
    ctx.invalidate_graph()
    after = ctx.graph_for(access)
    assert before.version == after.version
    assert ctx.graph().version == ctx.store.graph_version()


@pytest.mark.parametrize("tuned_zero", [False, True])
def test_hidden_only_fact_does_not_change_public_fingerprint_through_an_empty_edge(ctx, tuned_zero):
    from hippo.knowledge.replay import view_fingerprint

    ctx.store.ensure_roles()
    public = ctx.store.create_source("text", "Public")
    hidden = ctx.store.create_source("text", "Hidden")
    ctx.store.set_source_access(hidden, "local-admin")
    ctx.store.add_passages(
        [
            dict(
                id="passage-public",
                source_id=public,
                title="Public",
                text="Public",
                ordinal=0,
                embedding=[1.0, 0.0],
            )
        ]
    )
    ctx.store.add_entities(
        [dict(id=identity, name=identity, embedding=[1.0, 0.0]) for identity in ("entity-a", "entity-b")]
    )
    ctx.store.link_passage_entities([("passage-public", "entity-a"), ("passage-public", "entity-b")])
    if tuned_zero:
        ctx.store.set_edge_weight("entity-a", "entity-b", 0.0)
    ctx.store.bump_graph_version()
    access = Access(rank=0, user_id="reader")
    before = ctx.graph_for(access)
    fingerprint = view_fingerprint(before)
    ctx.store.add_passages(
        [
            dict(
                id="passage-hidden",
                source_id=hidden,
                title="Hidden",
                text="Hidden",
                ordinal=0,
                embedding=[1.0, 0.0],
            )
        ]
    )
    ctx.store.add_facts(
        [
            dict(
                id="fact-hidden",
                subject="entity-a",
                predicate="secret",
                object="entity-b",
                subject_id="entity-a",
                object_id="entity-b",
                embedding=[1.0, 0.0],
            )
        ]
    )
    ctx.store.link_passage_facts([("passage-hidden", "fact-hidden")])
    ctx.store.bump_graph_version()
    after = ctx.graph_for(access)
    assert before.facts == after.facts == []
    assert before.graph.get_edgelist() == after.graph.get_edgelist()
    assert fingerprint == view_fingerprint(after)
    assert before.version == after.version
    edge = after.edge_between(after.idx_of["entity-a"], after.idx_of["entity-b"])
    if tuned_zero:
        assert edge is not None and edge.tuned == 0.0
    else:
        assert edge is None


@pytest.mark.parametrize("access", [None, Principal.open().access, Access(unrestricted=True)])
def test_managed_source_cannot_enter_legacy_graph_without_published_evidence(ctx, access):
    _, source, *_ = foundation(ctx.store)
    index_source(ctx.store, ctx.ollama, source, [Chunk(0, "private title", "private managed content")])
    legacy = ctx.store.create_source("text", "legacy")
    index_source(ctx.store, ctx.ollama, legacy, [Chunk(0, "public title", "public legacy content")])
    graph = ctx.graph_for(access)
    assert {passage.source_id for passage in graph.passages} == {legacy}
    assert "private" not in str(graph.entity_names)


def test_adding_managed_evidence_invalidates_previously_cached_legacy_scope(ctx):
    _, source, *_ = foundation(ctx.store)
    index_source(ctx.store, ctx.ollama, source, [Chunk(0, "private title", "private managed content")])
    # The in-memory full graph remains useful to indexing, but never authorizes a reader.
    full = ctx.graph()
    assert full.passages
    assert ctx.graph_for(Access(user_id="unknown")).passages == []


def test_permission_change_during_source_scope_load_cannot_release_a_stale_graph(ctx, monkeypatch):
    from hippo.knowledge.access import AuthorizationChanged

    ctx.store.ensure_roles()
    source = ctx.store.create_source("text", "public")
    index_source(ctx.store, ctx.ollama, source, [Chunk(0, "title", "visible before revocation")])
    original = ctx.store.list_sources
    changed = False

    def read(*args, **kwargs):
        nonlocal changed
        rows = original(*args, **kwargs)
        if not changed:
            changed = True
            ctx.store.set_source_access(source, "local-admin")
        return rows

    monkeypatch.setattr(ctx.store, "list_sources", read)
    with pytest.raises(AuthorizationChanged):
        ctx.graph_for(Access(rank=0, user_id="reader"))


def test_a_held_legacy_graph_stops_authorizing_saved_outputs_after_revocation(ctx):
    from hippo import ask
    from hippo.knowledge.access import AuthorizationChanged
    from hippo.web.adhoc import recall_adhoc, remember_adhoc

    ctx.store.ensure_roles()
    source = ctx.store.create_source("text", "Public")
    index_source(ctx.store, ctx.ollama, source, [Chunk(0, "Title", "Mira designed Orion.")])
    access = Access(rank=0, user_id="reader")
    trace = ask.search(ctx, "Who designed Orion?", access=access)
    held = ctx.graph_for(access)
    key = remember_adhoc(trace, {"answer": "PRIVATE OLD ANSWER"}, owner="reader")
    ctx.store.set_source_access(source, "local-admin")
    with pytest.raises(AuthorizationChanged):
        recall_adhoc(key, "reader", graph=held)


@pytest.mark.parametrize("profile_change", [False, True])
def test_published_managed_span_reaches_query_and_revocation_evicts_cached_graph(ctx, profile_change):
    from hippo import ask
    from hippo.knowledge import model as k
    from hippo.knowledge.access import AuthorizationChanged
    from tests.unit.test_store_knowledge import NOW, reader

    workspace, source, policy, _, revision, span = foundation(ctx.store)
    user = reader(ctx.store, workspace.id, "managed-query-reader")
    access = Access(rank=0, user_id=user)
    index_source(ctx.store, ctx.ollama, source, [Chunk(0, "SECRET NATIVE TITLE", span.text)])
    passage = ctx.store.load_passages()[0]
    gen = k.Generation(
        source_id=source,
        status="ready",
        parser_version="p1",
        linker_version="l1",
        embedding_profile=ctx.ollama.embed_model,
        created_at=NOW,
        manifest_hash="complete",
    )
    ctx.store.put_knowledge(gen)
    ctx.store.put_knowledge(k.GenerationMember(generation_id=gen.id, artifact_revision_id=revision.id))
    ctx.store.put_knowledge(
        k.IndexManifest(
            generation_id=gen.id,
            profile_fingerprint=ctx.ollama.embed_model,
            config_fingerprint="config",
            required_representations=("dense",),
            checksums=(
                k.RepresentationChecksum(kind="dense", checksum="test-bound-vector", row_count=1, ready=True),
            ),
            ready=True,
        )
    )
    metadata = dict(
        generation_id=gen.id,
        artifact_revision_id=revision.id,
        span_id=span.id,
        embedding_profile=ctx.ollama.embed_model,
    )
    if ctx.store.knowledge_backend == "fake":
        ctx.store.passages[passage["id"]].update(metadata)
    else:
        ctx.store.run(
            "MATCH (p:Passage {id:$id}) SET p.generation_id=$generation_id, "
            "p.artifact_revision_id=$artifact_revision_id, p.span_id=$span_id, "
            "p.embedding_profile=$embedding_profile",
            id=passage["id"],
            **metadata,
        )
    assert ctx.graph_for(access).passages == []
    ctx.store.publish_generation(gen.id, expected_parent_id=None, published_at=NOW)
    graph = ctx.graph_for(access)
    assert [p.id for p in graph.passages] == [span.id]
    assert graph.passages[0].text == span.text
    assert "SECRET" not in graph.passages[0].title
    assert ctx.graph_for(access) is graph
    trace, answer = ask.ask(ctx, "What is the DDL?", access=access)
    assert answer.passage_ids == [span.id]
    assert trace.evidence_fingerprint
    if profile_change:
        from hippo.knowledge.projection import ProjectionError

        ctx.ollama.embed_model = "a-different-profile"
        with pytest.raises((ProjectionError, AuthorizationChanged)):
            ctx.graph_for(access)
        with pytest.raises(AuthorizationChanged):
            graph.validate_authorization()
        return
    denied = k.AccessPolicy(
        workspace_id=workspace.id,
        origin="local_curated",
        scope_key=policy.scope_key,
        mode="restricted",
        deny_users=(user,),
        verified_at=policy.verified_at,
    )
    ctx.store.put_knowledge(denied)
    artifact = ctx.store._knowledge_get("Artifact", revision.artifact_id)
    ctx.store.update_knowledge(artifact.replace(policy_id=denied.id))
    with pytest.raises(AuthorizationChanged):
        graph.validate_authorization()
    assert ctx.graph_for(access).passages == []
