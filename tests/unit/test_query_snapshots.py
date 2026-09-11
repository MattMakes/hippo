"""Real-store pins survive publication, but never current authorization loss."""

from datetime import UTC, datetime, timedelta

import pytest

from hippo.access import EVERYTHING
from hippo.knowledge import model as k
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.lifecycle import generation_passage_id


def build(ctx, *, parent=None, text="first revision"):
    store, now = ctx.store, datetime.now(UTC)
    store.ensure_schema()
    if parent is None:
        source = store.create_source("text", "managed")
        workspace = store.get_source(source)["workspace_id"]
        policy = k.AccessPolicy(
            workspace_id=workspace,
            origin="local_curated",
            scope_key=source,
            mode="workspace",
            verified_at=now,
        )
        artifact = k.Artifact(
            workspace_id=workspace,
            source_id=source,
            kind="file",
            external_id="notes.md",
            canonical_uri="notes.md",
            policy_id=policy.id,
        )
        store.put_knowledge(policy)
        store.put_knowledge(artifact)
    else:
        source = parent.source_id
        artifact = next(a for a in store._knowledge_rows("Artifact") if a.source_id == source)
    revision = k.ArtifactRevision(
        artifact_id=artifact.id,
        content_hash=text,
        raw_uri="blob:" + text,
        observed_at=now,
        lifecycle="active",
    )
    span = k.EvidenceSpan(
        revision_id=revision.id,
        locator_kind="file_lines",
        locator_json='{"kind":"file_lines","path":"notes.md","start":1,"end":1}',
        text=text,
        policy_id=artifact.policy_id,
    )
    gen = k.Generation(
        source_id=source,
        parent_id=parent.id if parent else None,
        status="staging",
        parser_version="p",
        linker_version="l",
        embedding_profile=ctx.ollama.embed_model,
        created_at=now,
        manifest_hash=text,
    )
    store.put_knowledge(gen)
    job = store.claim_generation_build(
        gen.id, job_key=text, lease_owner="snapshot-test", lease_expires_at=now + timedelta(minutes=5)
    )
    authority = dict(job_id=job.id, lease_owner=job.lease_owner, fencing_token=job.fencing_token)
    with store.generation_write(gen.id, **authority):
        for row in (
            revision,
            span,
            k.GenerationMember(generation_id=gen.id, artifact_revision_id=revision.id),
            k.GenerationEvidenceMember(generation_id=gen.id, record_kind="EvidenceSpan", record_id=span.id),
        ):
            store.put_knowledge(row)
        store.add_passages(
            [
                dict(
                    id=generation_passage_id(gen.id, revision.id, span.id, 0),
                    source_id=source,
                    generation_id=gen.id,
                    artifact_revision_id=revision.id,
                    span_id=span.id,
                    embedding_profile=gen.embedding_profile,
                    text=text,
                    title="notes",
                    ordinal=0,
                    embedding=[1.0, 0.0],
                )
            ]
        )
    manifest = k.IndexManifest(
        generation_id=gen.id,
        profile_fingerprint=gen.embedding_profile,
        config_fingerprint="test",
        required_representations=("evidence", "dense", "native"),
        checksums=store.generation_checksums(gen.id),
        ready=True,
    )
    store.seal_generation(gen.id, manifest, **authority)
    store.publish_staged_generation(
        gen.id,
        expected_parent_id=gen.parent_id,
        expected_suppression_epoch=store.suppression_epoch(),
        published_at=now,
        **authority,
    )
    return gen, span


def test_context_holds_old_generation_until_query_reference_released(ctx):
    gen, span = build(ctx)
    old = ctx.graph_for(EVERYTHING)
    assert old.passage_by_id(span.id).text == "first revision"
    assert len(old.snapshot_ids) == 1
    epoch = ctx.store.authorization_epoch()
    newer, new_span = build(ctx, parent=gen, text="second revision")
    assert ctx.store.authorization_epoch() == epoch
    old.validate_authorization()
    assert old.passage_by_id(span.id).text == "first revision"
    assert old.passage_by_id(new_span.id) is None
    current = ctx.graph_for(EVERYTHING)
    try:
        assert current.passage_by_id(new_span.id).text == "second revision"
        assert current.passage_by_id(span.id) is None
        assert current.snapshot_ids != old.snapshot_ids
        assert ctx.store.collect_generation(gen.id).blocked_reason == "snapshot_reference"
    finally:
        current.close_snapshot()
        old.close_snapshot()
    assert ctx.store.collect_generation(gen.id).blocked_reason is None
    assert ctx.store.get_source(gen.source_id)["active_generation_id"] == newer.id


def test_held_snapshot_rechecks_suppression_before_releasing_any_output(ctx):
    gen, span = build(ctx)
    graph = ctx.graph_for(EVERYTHING)
    workspace = ctx.store.get_source(gen.source_id)["workspace_id"]
    ctx.store.put_knowledge(
        k.Suppression(
            workspace_id=workspace,
            target_kind="span",
            target_id=span.id,
            scope_key="test",
            view_applicability="all_history",
            reason="access_loss",
            epoch=1,
            created_at=datetime.now(UTC),
            restoration_barrier="reverify",
        )
    )
    try:
        with pytest.raises(AuthorizationChanged):
            graph.validate_authorization()
        current = ctx.graph_for(EVERYTHING)
        try:
            assert current.passages == []
        finally:
            current.close_snapshot()
    finally:
        graph.close_snapshot()


def test_ask_keeps_pinned_passages_when_generation_publishes_during_embedding(ctx, monkeypatch):
    from hippo import ask

    gen, span = build(ctx)
    published = []

    def embedding(text, **kwargs):
        if not published:
            published.append(build(ctx, parent=gen, text="published during query"))
        return [1.0, 0.0]

    monkeypatch.setattr(ctx.ollama, "embed_one", embedding)
    trace, answer = ask.ask(ctx, "What was the first revision?", access=EVERYTHING)
    assert answer.passage_ids == [span.id]
    assert all(p.passage_id == span.id for p in trace.passages)
    assert published[0][1].id not in answer.passage_ids
    references = ctx.store._knowledge_rows("SnapshotReference")
    assert references and all(reference.released_at is not None for reference in references)


def test_snapshot_settings_fingerprint_matches_request_and_remains_pinned(ctx, monkeypatch):
    from hippo import ask
    from hippo.knowledge.identity import canonical_json, text_hash

    build(ctx)
    monkeypatch.setattr(ctx.ollama, "embed_one", lambda *args, **kwargs: [1.0, 0.0])
    trace = ask.search(ctx, "revision", settings={"qa_top_k": 1}, access=EVERYTHING)
    snapshot = ctx.store._knowledge_rows("QuerySnapshot")[0]
    assert trace.settings["qa_top_k"] == 1
    assert snapshot.settings_fingerprint == text_hash(canonical_json(trace.settings))


def test_graph_acquisition_failure_closes_reference_before_propagating(ctx, monkeypatch):
    from hippo import ask

    build(ctx)
    original = ctx._managed_graph_for
    held = []

    def changing(*args, **kwargs):
        graph = original(*args, **kwargs)
        held.append(graph)
        ctx.store._bump_authorization_epoch()
        return graph

    monkeypatch.setattr(ctx, "_managed_graph_for", changing)
    with pytest.raises(AuthorizationChanged):
        ask.search(ctx, "revision", access=EVERYTHING)
    assert held
    assert all(ref.released_at is not None for ref in ctx.store._knowledge_rows("SnapshotReference"))
