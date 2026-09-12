"""Explicit structural sessions retain evidence without consulting a model."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from hippo.access import EVERYTHING, Access
from hippo.knowledge import dense
from hippo.knowledge import model as k
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.lifecycle import generation_passage_id
from hippo.knowledge.projection import compose_graphs
from hippo.knowledge.query_access import query_session
from hippo.knowledge.replay import view_fingerprint
from hippo.knowledge.snapshots import acquire_query_snapshots
from tests.unit.test_dense_capability import base_graph, capable


class Offline:
    def __getattribute__(self, name):
        pytest.fail(f"Structural selection inspected model attribute {name}")


def published(
    store, key, *, profile="p", dimension=2, parent=None, publish=True, enrich=None, original_passage=True
):
    now = datetime.now(UTC)
    source = parent.source_id if parent else store.create_source("text", key)
    workspace = store.get_source(source)["workspace_id"]
    policy = k.AccessPolicy(
        workspace_id=workspace, origin="local_curated", scope_key=key, mode="workspace", verified_at=now
    )
    if parent:
        prior = next(row for row in store._knowledge_rows("Artifact") if row.source_id == source)
        policy = store._knowledge_get("AccessPolicy", prior.policy_id)
    artifact = k.Artifact(
        workspace_id=workspace,
        source_id=source,
        kind="file",
        external_id=key,
        canonical_uri=key,
        policy_id=policy.id,
    )
    revision = k.ArtifactRevision(
        artifact_id=artifact.id, content_hash=key, raw_uri="blob:" + key, observed_at=now, lifecycle="active"
    )
    span = k.EvidenceSpan(
        revision_id=revision.id,
        locator_kind="file_lines",
        locator_json='{"kind":"file_lines","path":"a.txt","start":1,"end":1}',
        text=key,
        policy_id=policy.id,
    )
    gen = k.Generation(
        source_id=source,
        parent_id=parent.id if parent else None,
        status="staging",
        parser_version="p",
        linker_version="l",
        embedding_profile=profile,
        created_at=now,
        manifest_hash=key,
    )
    for row in (policy, artifact, gen):
        store.put_knowledge(row)
    job = store.claim_generation_build(
        gen.id, job_key=key, lease_owner="structural", lease_expires_at=now + timedelta(minutes=5)
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
        if original_passage:
            store.add_passages(
                [
                    dict(
                        id=generation_passage_id(gen.id, revision.id, span.id, 0),
                        source_id=source,
                        generation_id=gen.id,
                        artifact_revision_id=revision.id,
                        span_id=span.id,
                        embedding_profile=profile,
                        text=key,
                        title=key,
                        ordinal=0,
                        embedding=[1.0] + [0.0] * (dimension - 1),
                    )
                ]
            )
        if enrich:
            enrich(store, gen, revision, span, now)
    if publish:
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
            published_at=now,
            **authority,
        )
    return gen, span


def legacy_graph():
    graph = base_graph("legacy", dimension=3)
    return replace(
        graph,
        managed_passage_ids=frozenset(),
        retrieval_evidence=(),
        original_citations=(),
        prose_provenance=(),
    )


def test_legacy_adapter_preserves_fingerprint_and_distinct_immutable_bindings():
    original = legacy_graph()
    assert hasattr(dense, "structural_legacy_graph"), "Legacy structural vector adapter missing"
    graph = dense.structural_legacy_graph(original)
    assert view_fingerprint(graph) == view_fingerprint(original)
    assert graph.dense_vectors == ()
    assert graph.passage_embeddings.shape == (1, 0)
    assert {row.lane for row in graph.legacy_dense_vectors} == {"passage", "fact"}
    for row in graph.legacy_dense_vectors:
        assert not hasattr(row, "generation_id") and not hasattr(row, "profile")
        with pytest.raises(FrozenInstanceError):
            row.values = ()
    managed = capable(base_graph("managed"), "unavailable")
    combined = compose_graphs(managed, graph)
    assert len(combined.passages) == len(combined.facts) == 2
    assert view_fingerprint(combined.scoped({"legacy"})) == view_fingerprint(graph)
    assert view_fingerprint(combined.scoped({"managed"})) == view_fingerprint(managed)
    assert not combined.scoped(set()).legacy_dense_vectors


def test_legacy_binding_rejects_invented_support_or_managed_relabeling():
    assert hasattr(dense, "structural_legacy_graph"), "Legacy structural vector adapter missing"
    with pytest.raises(ValueError):
        dense.structural_legacy_graph(base_graph())
    graph = dense.structural_legacy_graph(legacy_graph())
    rows = tuple(
        replace(row, support_passage_ids=("missing",)) if row.lane == "fact" else row
        for row in graph.legacy_dense_vectors
    )
    with pytest.raises(ValueError):
        replace(graph, legacy_dense_vectors=rows)


def test_legacy_adapter_keeps_existing_fact_labels_and_zero_vector_eligibility():
    original = legacy_graph()
    original.entity_names[original.facts[0].subject_id] = "Legacy display alias"
    original.passage_embeddings[:] = 0
    graph = dense.structural_legacy_graph(original)
    assert view_fingerprint(graph) == view_fingerprint(original)
    assert graph.facts[0].subject == original.facts[0].subject


@pytest.mark.parametrize("values", [(True, 1.0), (float("nan"), 1.0), (0.1, 1.0), [1.0, 2.0]])
def test_legacy_sidecar_rejects_mutable_or_noncanonical_values(values):
    with pytest.raises(ValueError):
        dense.LegacyDenseVector("passage", "p", 2, values)


def test_structural_context_keeps_different_managed_profiles_offline(ctx):
    first, a = published(ctx.store, "first")
    second, b = published(ctx.store, "second", profile="q", dimension=3)
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        assert {p.id for p in graph.passages} == {a.id, b.id}
        assert graph.passage_embeddings.shape == (2, 0)
        assert {(row.profile, row.dimension) for row in graph.dense_vectors} == {("p", 2), ("q", 3)}
        assert len(graph.snapshot_ids) == 2
        assert {row.generation_id for row in graph.dense_vectors} == {first.id, second.id}
        session.validate()
    assert all(r.released_at is not None for r in ctx.store._knowledge_rows("SnapshotReference"))


def test_structural_selection_records_its_authorized_pairs_without_model_access(ctx):
    first, _ = published(ctx.store, "first")
    second, _ = published(ctx.store, "second", profile="q", dimension=3)
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        assert graph.selected_managed_generations == tuple(
            sorted(((first.source_id, first.id), (second.source_id, second.id)))
        )
        assert graph.scoped({first.source_id}).selected_managed_generations == ((first.source_id, first.id),)
        session.validate()
    # The legacy lane selects no generation, so it can never claim one.
    assert not dense.structural_legacy_graph(legacy_graph()).selected_managed_generations


def test_managed_and_hidden_dimensions_do_not_choose_legacy_majority(ctx):
    store = ctx.store
    store.ensure_roles()
    source = store.create_source("text", "legacy")
    hidden = store.create_source("text", "hidden")
    store.set_source_access(hidden, "local-admin")
    store.add_passages(
        [
            dict(
                id="legacy",
                source_id=source,
                text="legacy",
                title="legacy",
                ordinal=0,
                embedding=[1.0, 0.0, 0.0, 0.0],
            )
        ]
    )
    for i in range(3):
        published(store, f"managed-{i}", dimension=2)
        store.add_passages(
            [
                dict(
                    id=f"hidden-{i}",
                    source_id=hidden,
                    text="hidden",
                    title="hidden",
                    ordinal=i,
                    embedding=[1.0] * 7,
                )
            ]
        )
    ctx.ollama = Offline()
    from tests.unit.test_store_knowledge import reader

    user = reader(store, store.get_source(source)["workspace_id"], "reader")
    with query_session(ctx, Access(rank=0, user_id=user), structural=True) as session:
        assert len(session.graph.passages) == 4
        assert {row.projected_id for row in session.graph.legacy_dense_vectors} == {"legacy"}
        assert "hidden" not in repr(session.graph.node_ids)


def test_source_profile_mapping_groups_atomically_and_does_not_alias(store):
    a, _ = published(store, "a")
    b, _ = published(store, "b", profile="q", dimension=3)
    profiles = {a.source_id: "p", b.source_id: "q"}
    bundle = acquire_query_snapshots(
        store,
        EVERYTHING,
        source_ids=frozenset(profiles),
        source_profiles=profiles,
        settings_fingerprint="settings",
    )
    try:
        profiles[a.source_id] = "changed"
        assert {s.profile_fingerprint for s in bundle.snapshots} == {"p", "q"}
        assert bundle.generation_ids == {a.id, b.id}
        bundle.validate()
    finally:
        bundle.close()


@pytest.mark.parametrize("selector", [{}, {"missing": "p"}, None])
def test_source_profile_mapping_requires_exact_selector(store, selector):
    a, _ = published(store, "a")
    with pytest.raises(ValueError):
        acquire_query_snapshots(
            store,
            EVERYTHING,
            source_ids=frozenset({a.source_id}),
            source_profiles=selector,
            settings_fingerprint="settings",
        )


def test_later_profile_group_failure_rolls_back_all_references(store, monkeypatch):
    a, _ = published(store, "a")
    b, _ = published(store, "b", profile="q", dimension=3)
    original = store.acquire_snapshot_reference
    calls = []

    def fail_second(snapshot, **kwargs):
        calls.append(snapshot)
        if len(calls) == 2:
            raise RuntimeError("second group failed")
        return original(snapshot, **kwargs)

    monkeypatch.setattr(store, "acquire_snapshot_reference", fail_second)
    with pytest.raises(RuntimeError, match="second group"):
        acquire_query_snapshots(
            store,
            EVERYTHING,
            source_ids=frozenset({a.source_id, b.source_id}),
            source_profiles={a.source_id: "p", b.source_id: "q"},
            settings_fingerprint="settings",
        )
    assert len(calls) == 2
    assert not store._knowledge_rows("SnapshotReference")


def test_structural_pin_survives_publication_and_closes_on_body_failure(ctx):
    old, span = published(ctx.store, "old")
    ctx.ollama = Offline()
    with pytest.raises(RuntimeError, match="body failure"):
        with query_session(ctx, EVERYTHING, structural=True) as session:
            published(ctx.store, "new", parent=old, profile="q", dimension=3)
            session.validate()
            assert [p.id for p in session.graph.passages] == [span.id]
            assert ctx.store.collect_generation(old.id).blocked_reason == "snapshot_reference"
            raise RuntimeError("body failure")
    assert ctx.store.collect_generation(old.id).blocked_reason is None


def test_structural_graph_rechecks_suppression_and_releases_refs(ctx):
    gen, span = published(ctx.store, "private")
    ctx.ollama = Offline()
    with pytest.raises(AuthorizationChanged):
        with query_session(ctx, EVERYTHING, structural=True) as session:
            ctx.store.put_knowledge(
                k.Suppression(
                    workspace_id=ctx.store.get_source(gen.source_id)["workspace_id"],
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
            session.validate()
    assert all(r.released_at is not None for r in ctx.store._knowledge_rows("SnapshotReference"))


def enrich(store, gen, revision, span, now, *, canonical_key='["a.py","f"]'):
    from hippo.codegraph.model import symbol_id
    from hippo.knowledge.lifecycle import generation_namespace
    from tests.unit.test_derived_generation_store import extraction, member, rendered

    view, _, _ = rendered(store, gen, span)
    row = dict(
        id=generation_passage_id(gen.id, revision.id, span.id, 1, retrieval_view_id=view.id),
        source_id=gen.source_id,
        generation_id=gen.id,
        artifact_revision_id=revision.id,
        span_id=span.id,
        retrieval_view_id=view.id,
        ordinal=1,
        embedding_profile=gen.embedding_profile,
        text=view.text,
        title="rendered",
        embedding=[0.0, 1.0],
    )
    store.add_passages([row])
    member(store, gen, extraction(store, gen, span, row))
    obj = k.KnowledgeObject(
        workspace_id=store.get_source(gen.source_id)["workspace_id"],
        kind="symbol",
        canonical_key=canonical_key,
    )
    store.put_knowledge(obj)
    member(
        store,
        gen,
        k.ObjectObservation(
            object_id=obj.id,
            revision_id=revision.id,
            span_id=span.id,
            evidence_class="declared",
            recorded_from=now,
            attributes_json='{"name":"f","path":"a.py","kind":"function"}',
        ),
    )
    identity = symbol_id(gen.source_id, "a.py", "f", "function", node_namespace=generation_namespace(gen))
    store.add_symbols(
        [
            dict(
                id=identity,
                source_id=gen.source_id,
                generation_id=gen.id,
                name="f",
                qualname="f",
                kind="function",
                path="a.py",
                embedding=[1.0, 0.0],
            )
        ]
    )
    store.put_knowledge(
        k.NativeBinding(
            generation_id=gen.id, object_id=obj.id, native_kind="Symbol", native_id=identity, span_id=span.id
        ),
    )


def test_heterogeneous_structural_keeps_rendered_prose_code_and_original_citations(ctx):
    from hippo.knowledge.citations import resolve_citations

    first, original = published(ctx.store, "rich", enrich=enrich)
    published(ctx.store, "other", profile="q", dimension=3)
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        assert len(graph.passages) == 3 and len(graph.facts) == 1 and len(graph.code_nodes) == 1
        assert graph.fact_embeddings.shape == (1, 0)
        assert {r.generation_id for r in graph.dense_vectors if r.lane == "fact"} == {first.id}
        rendered = next(p for p in graph.passages if p.text == "rendered card")
        citations = resolve_citations(graph, (rendered.id,))
        assert [c.id for c in citations.citations] == [original.id]
        assert citations.citations[0].text == "rich"
        assert graph.code_nodes[0].name == "f"
        assert graph.code_out


def test_staged_hidden_and_suppressed_rows_do_not_change_visible_structural_hash(ctx):
    gen, _ = published(ctx.store, "visible")
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        before = view_fingerprint(session.graph)
    published(
        ctx.store, "staged", parent=gen, profile="other", dimension=7, publish=False, enrich=unembedded_code
    )
    with query_session(ctx, EVERYTHING, structural=True) as session:
        assert view_fingerprint(session.graph) == before


def test_structural_projection_failure_closes_all_acquired_profiles(ctx, monkeypatch):
    import hippo.knowledge.projection as projection

    published(ctx.store, "a")
    published(ctx.store, "b", profile="q", dimension=3)
    ctx.ollama = Offline()

    def failed(*args, **kwargs):
        raise RuntimeError("projection failed")

    monkeypatch.setattr(projection, "project_managed_graph", failed)
    with pytest.raises(RuntimeError, match="projection failed"):
        ctx.graph_for(EVERYTHING, structural=True)
    assert not [r for r in ctx.store._knowledge_rows("SnapshotReference") if r.released_at is None]


def test_structural_expired_reference_denies_cached_graph_without_model_access(ctx):
    published(ctx.store, "a")
    ctx.ollama = Offline()
    graph = ctx.graph_for(EVERYTHING, structural=True)
    refs = ctx.store._knowledge_rows("SnapshotReference")
    ctx.store._generation_clock = lambda: max(r.lease_expires_at for r in refs) + timedelta(seconds=1)
    try:
        with pytest.raises(AuthorizationChanged):
            graph.validate_authorization()
    finally:
        graph.close_snapshot()


def test_structural_legacy_only_retains_baseline_eligibility_and_fingerprint(ctx):
    from hippo.knowledge.graph_loader import load_generation_graph

    source = ctx.store.create_source("text", "legacy")
    ctx.store.add_passages(
        [
            dict(
                id=f"p-{i}", source_id=source, text=f"p-{i}", title="legacy", ordinal=i, embedding=[1.0] * dim
            )
            for i, dim in enumerate((2, 2, 3))
        ]
    )
    expected = load_generation_graph(
        ctx.store, generations={}, legacy_source_ids=frozenset({source}), version=1
    )
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        assert view_fingerprint(session.graph) == view_fingerprint(expected)
        assert {p.id for p in session.graph.passages} == {"p-0", "p-1"}


def test_structural_reader_does_not_gain_orphan_legacy_code(ctx):
    from tests.unit.test_store_knowledge import reader

    gen, _ = published(ctx.store, "managed")
    source = ctx.store.create_source("code", "legacy")
    ctx.store.add_symbols(
        [dict(id="orphan", source_id=source, name="orphan", kind="function", embedding=[1.0, 0.0])]
    )
    user = reader(ctx.store, ctx.store.get_source(gen.source_id)["workspace_id"], "reader")
    ctx.ollama = Offline()
    with query_session(ctx, Access(rank=0, user_id=user), structural=True) as session:
        assert "orphan" not in session.graph.node_ids


def test_snapshot_selection_race_is_denied_before_projection(ctx, monkeypatch):
    import hippo.knowledge.projection as projection
    import hippo.knowledge.snapshots as snapshots

    gen, _ = published(ctx.store, "old")
    acquire = snapshots.acquire_query_snapshots

    def switched(*args, **kwargs):
        published(ctx.store, "new", parent=gen)
        return acquire(*args, **kwargs)

    monkeypatch.setattr(snapshots, "acquire_query_snapshots", switched)
    monkeypatch.setattr(
        projection,
        "project_managed_graph",
        lambda *args, **kwargs: pytest.fail("mismatched pin reached projection"),
    )
    ctx.ollama = Offline()
    with pytest.raises(AuthorizationChanged):
        ctx.graph_for(EVERYTHING, structural=True)
    assert all(r.released_at is not None for r in ctx.store._knowledge_rows("SnapshotReference"))


def unembedded_code(store, gen, revision, original, now):
    from hippo.codegraph.model import symbol_id
    from hippo.knowledge.identity import text_hash
    from hippo.knowledge.lifecycle import generation_namespace
    from tests.unit.test_derived_generation_store import member

    span = original.replace(
        text="def detached(): pass",
        text_hash=text_hash("def detached(): pass"),
        locator_json='{"kind":"file_lines","path":"a.txt","start":2,"end":2}',
    )
    member(store, gen, span)
    obj = k.KnowledgeObject(
        workspace_id=store.get_source(gen.source_id)["workspace_id"],
        kind="symbol",
        canonical_key='["a.py","detached"]',
    )
    store.put_knowledge(obj)
    member(
        store,
        gen,
        k.ObjectObservation(
            object_id=obj.id,
            revision_id=revision.id,
            span_id=span.id,
            evidence_class="declared",
            recorded_from=now,
            attributes_json='{"name":"detached","path":"a.py","kind":"function"}',
        ),
    )
    native = symbol_id(
        gen.source_id, "a.py", "detached", "function", node_namespace=generation_namespace(gen)
    )
    store.add_symbols(
        [
            dict(
                id=native,
                source_id=gen.source_id,
                generation_id=gen.id,
                name="detached",
                qualname="detached",
                kind="function",
                path="a.py",
                embedding=[1.0, 0.0],
            )
        ]
    )
    store.put_knowledge(
        k.NativeBinding(
            generation_id=gen.id, object_id=obj.id, native_kind="Symbol", native_id=native, span_id=span.id
        )
    )
    return obj, span


def connected_unembedded(store, gen, revision, original, now):
    from tests.unit.test_derived_generation_store import member

    enrich(store, gen, revision, original, now)
    detached, span = unembedded_code(store, gen, revision, original, now)
    sibling = next(obj for obj in store._knowledge_rows("KnowledgeObject") if obj.id != detached.id)
    relation = k.checked_assertion(sibling, "BOUND_TO", detached, scope_key=gen.source_id)
    store.put_knowledge(relation)
    version = k.AssertionVersion(
        assertion_id=relation.id,
        evidence_class="declared",
        rule_version="r",
        confidence=1.0,
        status="active",
        recorded_from=now,
    )
    member(store, gen, version)
    member(
        store,
        gen,
        k.AssertionSupport(assertion_version_id=version.id, span_id=span.id, derivation_group="declaration"),
    )


def test_unembedded_code_retains_authorized_assertion_edges_under_scope(ctx):
    gen, _ = published(ctx.store, "bound", enrich=connected_unembedded)
    published(ctx.store, "other", profile="q", dimension=3)
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph.scoped({gen.source_id})
        assert len(graph.code_nodes) == 2
        arrows = [arrow for rows in graph.code_out.values() for arrow in rows if arrow.kind == "BOUND_TO"]
        assert len(arrows) == 1
        assert {graph.node_ids[arrows[0].src], graph.node_ids[arrows[0].dst]} == {
            node.id for node in graph.code_nodes
        }


def test_structural_unembedded_code_has_original_scope_and_suppression_closure(ctx):
    gen, original = published(ctx.store, "dense sibling", enrich=unembedded_code)
    other, _ = published(ctx.store, "another source", profile="q", dimension=3)
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        assert len(graph.code_nodes) == 1
        scoped = graph.scoped({gen.source_id})
        assert len(scoped.code_nodes) == 1
        assert len(scoped.structural_code_evidence) == 1
        assert len(scoped.original_citations) == 2
        code_original = next(c for c in scoped.original_citations if c.id != original.id)
        assert scoped.structural_code_evidence[0].original_span_ids == (code_original.id,)
        assert not graph.scoped({other.source_id}).structural_code_evidence
        assert not graph.scoped(set()).code_nodes
        with pytest.raises(ValueError):
            replace(
                graph,
                structural_code_evidence=(
                    replace(graph.structural_code_evidence[0], generation_id="another-generation"),
                ),
            )
        from hippo.knowledge.identity import text_hash

        changed = replace(
            graph,
            original_citations=tuple(
                replace(c, text="changed original", text_hash=text_hash("changed original"))
                if c.id == code_original.id
                else c
                for c in graph.original_citations
            ),
        )
        assert view_fingerprint(changed) != view_fingerprint(graph)
    ctx.store.put_knowledge(
        k.Suppression(
            workspace_id=ctx.store.get_source(gen.source_id)["workspace_id"],
            target_kind="span",
            target_id=code_original.id,
            scope_key="test",
            view_applicability="all_history",
            reason="access_loss",
            epoch=1,
            created_at=datetime.now(UTC),
            restoration_barrier="reverify",
        )
    )
    with query_session(ctx, EVERYTHING, structural=True) as session:
        assert not session.graph.code_nodes
        assert code_original.id not in {c.id for c in session.graph.original_citations}


def test_rendered_only_code_without_view_binding_keeps_explicit_structural_scope(ctx):
    gen, _ = published(ctx.store, "rendered only", enrich=enrich, original_passage=False)
    published(ctx.store, "other", profile="q", dimension=3)
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph.scoped({gen.source_id})
        assert len(graph.code_nodes) == 1
        assert len(graph.structural_code_evidence) == 1
        assert len(graph.passages) == 1
        assert not any(arrow.kind == "DEFINED_IN" for rows in graph.code_out.values() for arrow in rows)


def shared_code(store, gen, revision, span, now, *, name="f", doc="shared body"):
    from hippo.codegraph.model import symbol_id
    from hippo.knowledge.identity import canonical_json, repository_identity, symbol_key
    from hippo.knowledge.lifecycle import generation_namespace
    from tests.unit.test_derived_generation_store import member

    workspace = store.get_source(gen.source_id)["workspace_id"]
    repository = repository_identity(workspace, "https://git.example", "team/project")
    obj = k.KnowledgeObject(
        workspace_id=workspace,
        kind="symbol",
        canonical_key=canonical_json(symbol_key(repository, "python", "a.py", name, kind="function")),
    )
    store.put_knowledge(obj)
    member(
        store,
        gen,
        k.ObjectObservation(
            object_id=obj.id,
            revision_id=revision.id,
            span_id=span.id,
            evidence_class="declared",
            recorded_from=now,
            attributes_json=canonical_json(dict(name=name, path="a.py", kind="function", doc=doc)),
        ),
    )
    identity = symbol_id(gen.source_id, "a.py", name, "function", node_namespace=generation_namespace(gen))
    vector = next(row["embedding"] for row in store.load_passages() if row.get("generation_id") == gen.id)
    store.add_symbols(
        [
            dict(
                id=identity,
                source_id=gen.source_id,
                generation_id=gen.id,
                name=name,
                qualname=name,
                kind="function",
                path="a.py",
                embedding=vector,
            )
        ]
    )
    store.put_knowledge(
        k.NativeBinding(
            generation_id=gen.id, object_id=obj.id, native_kind="Symbol", native_id=identity, span_id=span.id
        )
    )
    return obj


@pytest.mark.parametrize("profile,dimension", [("p", 2), ("q", 3)])
def test_structural_shared_canonical_code_object_does_not_collide_across_sources(ctx, profile, dimension):
    a, a_span = published(ctx.store, "first observation", enrich=shared_code)
    b, b_span = published(
        ctx.store, "second observation", profile=profile, dimension=dimension, enrich=shared_code
    )
    if profile == "p":
        ctx.ollama.embed_model = "p"
        baseline = ctx.graph_for(EVERYTHING)
        try:
            assert len(baseline.code_nodes) == 1
            # The non-structural managed lane proves the same pairs, so source inventory agrees
            # whichever view a reader holds.
            assert baseline.selected_managed_generations == tuple(
                sorted(((a.source_id, a.id), (b.source_id, b.id)))
            )
        finally:
            baseline.close_snapshot()
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        assert len(graph.code_nodes) == 1 and len(graph.passages) == 2
        for gen, span in ((a, a_span), (b, b_span)):
            scoped = graph.scoped({gen.source_id})
            assert len(scoped.code_nodes) == 1
            assert scoped.code_nodes[0].source_id == gen.source_id
            assert {c.id for c in scoped.original_citations} == {span.id}


def test_shared_code_conflicting_source_attributes_fail_and_release_pins(ctx):
    from hippo.knowledge.projection import ProjectionError

    published(ctx.store, "a", enrich=shared_code)
    published(ctx.store, "b", enrich=lambda *args: shared_code(*args, doc="private other body"))
    ctx.ollama = Offline()
    with pytest.raises(ProjectionError, match="conflicting"):
        ctx.graph_for(EVERYTHING, structural=True)
    assert not [r for r in ctx.store._knowledge_rows("SnapshotReference") if r.released_at is None]


def shared_pair(store, gen, revision, span, now, *, relationship=False):
    from hippo.knowledge.identity import text_hash
    from tests.unit.test_derived_generation_store import member

    a = shared_code(store, gen, revision, span, now, name="f")
    b = shared_code(store, gen, revision, span, now, name="g")
    if relationship:
        support = span.replace(
            text="f is bound to g",
            text_hash=text_hash("f is bound to g"),
            locator_json='{"kind":"file_lines","path":"a.txt","start":3,"end":3}',
        )
        member(store, gen, support)
        assertion = k.checked_assertion(a, "BOUND_TO", b, scope_key=gen.source_id)
        store.put_knowledge(assertion)
        version = k.AssertionVersion(
            assertion_id=assertion.id,
            evidence_class="declared",
            rule_version="r",
            confidence=0.7,
            status="active",
            recorded_from=now,
        )
        member(store, gen, version)
        member(
            store,
            gen,
            k.AssertionSupport(
                assertion_version_id=version.id, span_id=support.id, derivation_group="declared"
            ),
        )


def test_scope_removes_assertion_supported_only_by_removed_source_not_surviving_endpoints(ctx):
    a, _ = published(
        ctx.store, "supporting source", enrich=lambda *args: shared_pair(*args, relationship=True)
    )
    b, b_span = published(ctx.store, "other observations", profile="q", dimension=3, enrich=shared_pair)
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        assert len(graph.code_nodes) == 2
        assert any(arrow.kind == "BOUND_TO" for rows in graph.code_out.values() for arrow in rows)
        assert any(c.text == "f is bound to g" for c in graph.original_citations)
        assert graph.structural_relations[0].source_generations == ((a.source_id, a.id),)
        with pytest.raises(ValueError):
            replace(
                graph,
                structural_relations=(
                    replace(graph.structural_relations[0], source_generations=((a.source_id, b.id),)),
                ),
            )
        only_b = graph.scoped({b.source_id})
        assert len(only_b.code_nodes) == 2
        assert not any(arrow.kind == "BOUND_TO" for rows in only_b.code_out.values() for arrow in rows)
        assert not any("bound_to" in edge.code_kinds for edge in only_b.edges.values())
        x, y = (only_b.idx_of[node.id] for node in only_b.code_nodes)
        assert (min(x, y), max(x, y)) not in only_b.edges
        assert only_b.graph.get_eid(x, y, directed=False, error=False) == -1
        assert {c.id for c in only_b.original_citations} == {b_span.id}
        assert any(
            arrow.kind == "BOUND_TO"
            for rows in graph.scoped({a.source_id}).code_out.values()
            for arrow in rows
        )


def test_relation_only_generation_contribution_is_retained_without_a_dense_or_code_row(ctx):
    a, span = published(
        ctx.store, "support source", enrich=lambda *args: shared_pair(*args, relationship=True)
    )
    b, _ = published(ctx.store, "endpoint source", profile="q", dimension=3, enrich=shared_pair)
    ctx.store.put_knowledge(
        k.Suppression(
            workspace_id=ctx.store.get_source(a.source_id)["workspace_id"],
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
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        assert {row.generation_id for row in graph.dense_vectors} == {b.id}
        assert all(row.generation_id != a.id for row in graph.structural_code_evidence)
        assert graph.structural_relations[0].source_generations == ((a.source_id, a.id),)
        assert not graph.scoped({b.source_id}).structural_relations


def projection_inputs(store):
    from hippo.knowledge.access import EvidenceSelection

    gen, _ = published(store, "project")
    _, proof = store._reader_proof(
        store.get_source(gen.source_id)["workspace_id"],
        EVERYTHING,
        expected_epoch=store.authorization_epoch(),
        selection=EvidenceSelection(generation_ids=frozenset({gen.id}), require_exact_membership=True),
    )
    return gen, proof


def test_nonstructural_projection_requires_cached_full_graph(store):
    from hippo.knowledge.projection import ProjectionError, project_managed_graph

    _, proof = projection_inputs(store)
    with pytest.raises(ProjectionError, match="full graph"):
        project_managed_graph(None, store, proof, embedding_profile="p")


@pytest.mark.parametrize("fault", ["none", "missing", "extra", "wrong", "mutable_value", "both"])
def test_structural_projection_requires_exact_valid_source_profiles(store, fault):
    from hippo.knowledge.projection import ProjectionError, project_managed_graph

    gen, proof = projection_inputs(store)
    profiles = {gen.source_id: "p"}
    if fault == "none":
        profiles = None
    elif fault == "missing":
        profiles = {}
    elif fault == "extra":
        profiles["extra"] = "p"
    elif fault == "wrong":
        profiles[gen.source_id] = "q"
    elif fault == "mutable_value":
        profiles[gen.source_id] = ["p"]
    with pytest.raises(ProjectionError):
        project_managed_graph(
            None,
            store,
            proof,
            source_profiles=profiles,
            structural=True,
            embedding_profile="p" if fault == "both" else None,
        )


def typed_pair(store, gen, revision, span, now, *, relationship=True):
    from hippo.knowledge.identity import text_hash
    from tests.unit.test_derived_generation_store import member

    original = span.replace(
        text="declared services",
        text_hash=text_hash("declared services"),
        locator_json='{"kind":"file_lines","path":"a.txt","start":2,"end":2}',
    )
    member(store, gen, original)
    workspace = store.get_source(gen.source_id)["workspace_id"]
    objects = []
    for name in ("billing", "payment"):
        obj = k.KnowledgeObject(workspace_id=workspace, kind="service", canonical_key='["' + name + '"]')
        store.put_knowledge(obj)
        member(
            store,
            gen,
            k.ObjectObservation(
                object_id=obj.id,
                revision_id=revision.id,
                span_id=original.id,
                evidence_class="declared",
                recorded_from=now,
                attributes_json='{"name":"' + name + '"}',
            ),
        )
        objects.append(obj)
    if relationship:
        support = original.replace(
            text="service dependency",
            text_hash=text_hash("service dependency"),
            locator_json='{"kind":"file_lines","path":"a.txt","start":3,"end":3}',
        )
        member(store, gen, support)
        assertion = k.checked_assertion(objects[0], "DEPENDS_ON", objects[1], scope_key=gen.source_id)
        store.put_knowledge(assertion)
        version = k.AssertionVersion(
            assertion_id=assertion.id,
            evidence_class="declared",
            rule_version="r",
            confidence=0.7,
            status="active",
            recorded_from=now,
        )
        member(store, gen, version)
        member(
            store,
            gen,
            k.AssertionSupport(
                assertion_version_id=version.id, span_id=support.id, derivation_group="declared"
            ),
        )


@pytest.mark.parametrize("relationship", [False, True])
def test_original_only_typed_objects_survive_same_source_scope(ctx, relationship):
    gen, _ = published(
        ctx.store, "typed catalog", enrich=lambda *a: typed_pair(*a, relationship=relationship)
    )
    published(ctx.store, "other", profile="q", dimension=3)
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        assert set(graph.entity_names.values()) == {"billing", "payment"}
        scoped = graph.scoped({gen.source_id})
        assert scoped.entity_names == graph.entity_names
        assert len(scoped.structural_relations) == int(relationship)
        assert {r.generation_id for r in scoped.structural_object_evidence} == {gen.id}
        assert any(c.text == "declared services" for c in scoped.original_citations)
        observations = {r.id for r in ctx.store._knowledge_rows("ObjectObservation")}
        assert {i for r in scoped.structural_object_evidence for i in r.observation_ids} == observations
        assert not graph.scoped(set()).entity_names
        assert not graph.scoped(set()).structural_object_evidence


def test_shared_typed_objects_scope_drops_removed_support_not_observations(ctx):
    a, _ = published(ctx.store, "typed support", enrich=typed_pair)
    b, _ = published(
        ctx.store,
        "typed other",
        profile="q",
        dimension=3,
        enrich=lambda *args: typed_pair(*args, relationship=False),
    )
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        scoped = graph.scoped({b.source_id})
        assert set(scoped.entity_names.values()) == {"billing", "payment"}
        assert {row.source_id for row in scoped.structural_object_evidence} == {b.source_id}
        assert not scoped.structural_relations
        x, y = [scoped.idx_of[i] for i in scoped.entity_names]
        assert scoped.graph.get_eid(x, y, directed=False, error=False) == -1
        assert all(c.source_id == b.source_id for c in scoped.original_citations)
        assert graph.scoped({a.source_id}).structural_relations


def test_structural_typed_observations_validate_and_fingerprint_originals(ctx):
    gen, _ = published(ctx.store, "typed integrity", enrich=typed_pair)
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        row = graph.structural_object_evidence[0]
        with pytest.raises(FrozenInstanceError):
            row.source_id = "wrong"
        for mutation in ({"source_id": "wrong"}, {"generation_id": "wrong"}, {"node_id": "wrong"}):
            with pytest.raises(ValueError):
                replace(
                    graph,
                    structural_object_evidence=(replace(row, **mutation),)
                    + graph.structural_object_evidence[1:],
                )
        with pytest.raises(ValueError):
            replace(row, observation_ids=["mutable"])
        changed = replace(
            graph,
            original_citations=tuple(
                replace(c, title="changed title") if c.id in row.original_span_ids else c
                for c in graph.original_citations
            ),
        )
        assert view_fingerprint(changed) != view_fingerprint(graph)
        assert gen.id == row.generation_id


def test_suppressed_typed_observation_cannot_be_invented_from_relation_support(ctx):
    gen, _ = published(ctx.store, "typed suppression", enrich=typed_pair)
    ctx.ollama = Offline()
    with pytest.raises(AuthorizationChanged), query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        span_id = graph.structural_object_evidence[0].original_span_ids[0]
        assert span_id not in graph.structural_relations[0].original_span_ids
        ctx.store.put_knowledge(
            k.Suppression(
                workspace_id=ctx.store.get_source(gen.source_id)["workspace_id"],
                target_kind="span",
                target_id=span_id,
                scope_key="test",
                view_applicability="all_history",
                reason="access_loss",
                epoch=1,
                created_at=datetime.now(UTC),
                restoration_barrier="reverify",
            )
        )
        with pytest.raises(AuthorizationChanged):
            session.validate()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        assert not session.graph.entity_names
        assert not session.graph.structural_object_evidence
        assert not session.graph.structural_relations
        assert session.graph.passages
