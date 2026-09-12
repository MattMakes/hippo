"""One held evidence graph chooses a faithful dense model without granting new access."""

import importlib
from dataclasses import replace
from datetime import UTC, datetime

import numpy as np
import pytest

from hippo.access import EVERYTHING
from hippo.hipporag.retriever import Retriever
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.embedding_profile import EmbeddingProfileChanged, EmbeddingProfileMismatch
from hippo.knowledge.query_access import AuthorizedModel, query_session
from hippo.knowledge.replay import view_fingerprint
from tests.unit.test_embedding_profile import Server
from tests.unit.test_staged_prose_writer import publish, setup, write
from tests.unit.test_structural_loading import published, unembedded_code


def api():
    try:
        return importlib.import_module("hippo.knowledge.dense_session")
    except ModuleNotFoundError:
        pytest.fail("Dense session dispatcher is missing")


def verified(ctx, tmp_path):
    old, job, prepared, credentials = setup(ctx.store, tmp_path)
    write(ctx.store, prepared, credentials)
    publish(ctx.store, prepared.inputs.generation, job)
    ctx.store._generation_clock = lambda: datetime.now(UTC)
    server = Server()
    server.name = "embed:latest"
    server.dimension = 2
    server.show["model_info"]["bert.embedding_length"] = 2
    ctx.ollama = server.client("embed:latest")
    return prepared, server


def refs_closed(ctx):
    assert all(row.released_at is not None for row in ctx.store._knowledge_rows("SnapshotReference"))


def observe(ctx, monkeypatch):
    held, closed = [], []
    original = ctx.graph_for

    def graph_for(*args, **kwargs):
        graph = original(*args, **kwargs)
        held.append(graph)
        close = getattr(graph, "close_snapshot", lambda: None)

        def release():
            closed.append(graph)
            close()

        graph.close_snapshot = release
        return graph

    monkeypatch.setattr(ctx, "graph_for", graph_for)
    return held, closed


def test_verified_session_pins_once_and_preserves_vectors_provenance_settings(ctx, tmp_path, monkeypatch):
    prepared, server = verified(ctx, tmp_path)
    held, closed = observe(ctx, monkeypatch)

    def outside(path, body):
        assert not getattr(ctx.store, "_transaction_depth", 0)
        assert getattr(ctx.store, "_transaction", None) is None

    server.hook = outside
    with api().dense_session(ctx, EVERYTHING, settings={"qa_top_k": 2}) as session:
        assert len(held) == 1 and not closed
        assert session.graph is not held[0]
        assert session.settings["qa_top_k"] == 2
        assert session.graph.snapshot_ids == held[0].snapshot_ids
        assert held[0].passage_embeddings.shape[1] == 0
        assert session.graph.passage_embeddings.shape[1] == 2
        assert session.graph.dense_capability.mode == "verified"
        assert session.model.profile_fingerprint == prepared.inputs.embedding_profile.fingerprint
        assert view_fingerprint(session.graph) == view_fingerprint(held[0])
        assert session.graph.original_citations == held[0].original_citations
        vector = session.model.embed_one("who builds?", kind="query")
        assert vector.shape == (2,)
        assert server.embeds()[-1]["input"] == ["query:who builds?"]
        assert server.embeds()[-1]["dimensions"] == 2
        with pytest.raises(AttributeError):
            session.model.profile_fingerprint = "other"
    assert closed == held
    refs_closed(ctx)


def test_tag_session_keeps_snapshot_through_publication(ctx, monkeypatch):
    first, original = published(ctx.store, "G1", profile=ctx.ollama.embed_model)
    held, closed = observe(ctx, monkeypatch)
    with api().retrieval_session(ctx, EVERYTHING) as session:
        assert session.graph.dense_capability.mode == "tag_compatible"
        assert session.model.profile_fingerprint is None
        _, newer = published(ctx.store, "G2", parent=first, profile=ctx.ollama.embed_model)
        session.validate()
        assert [p.id for p in session.graph.passages] == [original.id]
        assert session.graph.passage_by_id(newer.id) is None
        assert view_fingerprint(session.graph) == view_fingerprint(held[0])
    assert closed == held
    refs_closed(ctx)


@pytest.mark.parametrize("empty", [False, True])
def test_tag_change_rejects_supplied_vectors_and_empty_before_scoring(ctx, empty):
    published(ctx.store, "original", profile=ctx.ollama.embed_model)
    old_tag = ctx.ollama.embed_model
    with api().retrieval_session(ctx, EVERYTHING) as session:
        graph = session.graph.scoped(set()) if empty else session.graph
        ctx.ollama.embed_model = "other"
        try:
            with pytest.raises(EmbeddingProfileChanged):
                session.validate()
            with pytest.raises(EmbeddingProfileChanged):
                _ = session.model.profile_fingerprint
            with pytest.raises(EmbeddingProfileChanged):
                Retriever(graph, session.model).retrieve(
                    "q",
                    dict(session.settings),
                    question_embedding=np.array([1.0, 0.0]),
                    fact_filter=lambda *_: [],
                )
        finally:
            ctx.ollama.embed_model = old_tag
    refs_closed(ctx)


def test_mixed_verified_and_tagged_denies_without_metadata_or_model_text(ctx, tmp_path):
    _, server = verified(ctx, tmp_path)
    published(ctx.store, "legacy managed", profile=ctx.ollama.embed_model)
    with pytest.raises(api().DenseSessionUnavailable, match="mixed"):
        with api().retrieval_session(ctx, EVERYTHING):
            pytest.fail("mixed modes must reject")
    assert not server.calls
    refs_closed(ctx)


@pytest.mark.parametrize("width", [2, 3])
def test_tag_legacy_vectors_are_retained_or_explicitly_rejected_without_pruning(ctx, width):
    _, original = published(ctx.store, "managed", profile=ctx.ollama.embed_model)
    source = ctx.store.create_source("text", "legacy")
    ctx.store.add_passages(
        [dict(id="old", source_id=source, title="old", text="old", ordinal=0, embedding=[0.0] * width)]
    )
    if width != 2:
        with pytest.raises(api().DenseSessionUnavailable, match="dimension"):
            with api().retrieval_session(ctx, EVERYTHING):
                pytest.fail("incompatible widths must reject")
    else:
        with api().retrieval_session(ctx, EVERYTHING) as session:
            assert {p.id for p in session.graph.passages} == {original.id, "old"}
            index = next(i for i, p in enumerate(session.graph.passages) if p.id == "old")
            assert session.graph.passage_embeddings[index].tolist() == [0.0, 0.0]
            assert session.graph.legacy_dense_vectors[0].values == (0.0, 0.0)
    refs_closed(ctx)


def test_truly_empty_compatibility_uses_no_model_attributes(ctx):
    class Offline:
        def __getattribute__(self, name):
            pytest.fail(f"empty graph touched model {name}")

    ctx.ollama = Offline()
    with api().retrieval_session(ctx, EVERYTHING) as session:
        assert session.graph.is_empty()
        assert session.graph.dense_capability.mode == "legacy"


def test_tag_provenance_without_dense_width_cannot_invent_a_dimension(ctx):
    from hippo.knowledge import model as k

    gen, span = published(ctx.store, "code only", profile=ctx.ollama.embed_model, enrich=unembedded_code)
    ctx.store.put_knowledge(
        k.Suppression(
            workspace_id=ctx.store.get_source(gen.source_id)["workspace_id"],
            target_kind="span",
            target_id=span.id,
            scope_key="hide dense",
            created_at=datetime.now(UTC),
            reason="access_loss",
            view_applicability="all_history",
            epoch=1,
            restoration_barrier="review",
        )
    )
    with pytest.raises(api().DenseSessionUnavailable, match="dimension"):
        with api().retrieval_session(ctx, EVERYTHING):
            pytest.fail("code-only graph must reject a missing dense dimension")


@pytest.mark.parametrize("revoke", [False, True])
def test_remote_failure_releases_and_current_denial_takes_precedence(ctx, tmp_path, revoke):
    _, server = verified(ctx, tmp_path)

    def fail(path, body):
        if revoke:
            ctx.store._bump_authorization_epoch()
        raise RuntimeError("remote unavailable")

    server.hook = fail
    with pytest.raises(AuthorizationChanged if revoke else RuntimeError):
        with api().dense_session(ctx, EVERYTHING):
            pytest.fail("resolution must fail")
    refs_closed(ctx)


def test_same_dimension_live_digest_mismatch_cannot_dispatch_private_text(ctx, tmp_path):
    _, server = verified(ctx, tmp_path)
    server.digest = "c" * 64
    with pytest.raises(EmbeddingProfileMismatch):
        with api().dense_session(ctx, EVERYTHING):
            pytest.fail("wrong live digest must reject")
    assert all("hippo embedding profile probe" in text for call in server.embeds() for text in call["input"])
    refs_closed(ctx)


def test_borrowed_session_preserves_owner_settings_and_never_acquires_or_closes_again(ctx, monkeypatch):
    published(ctx.store, "original", profile=ctx.ollama.embed_model)
    held, closed = observe(ctx, monkeypatch)
    with query_session(ctx, EVERYTHING, structural=True) as owner:
        with api().retrieval_session(ctx, session=owner) as borrowed:
            assert borrowed.settings is owner.settings
            assert borrowed.graph.snapshot_ids == owner.graph.snapshot_ids
            borrowed.validate()
        assert len(held) == 1 and not closed
        with pytest.raises(api().DenseSessionUnavailable, match="settings"):
            with api().retrieval_session(ctx, session=owner, settings={"qa_top_k": 1}):
                pytest.fail("conflicting settings")
        assert not closed
    assert held == closed


def test_verified_profile_property_is_local_readonly_and_forwards_through_nested_guards():
    from hippo.knowledge.embedding_profile import ProfiledEmbeddings
    from tests.unit.test_embedding_profile import resolved

    _, server, client, profile = resolved()
    adapter = ProfiledEmbeddings(client, profile)
    before = list(server.calls)
    guarded = AuthorizedModel(AuthorizedModel(adapter, lambda: None), lambda: None)
    assert getattr(guarded, "profile_fingerprint", None) == profile.fingerprint
    assert server.calls == before
    with pytest.raises(AttributeError):
        adapter.profile_fingerprint = "other"


def test_selected_descriptor_dimension_mismatch_denies_before_resolution(ctx, tmp_path):
    _, server = verified(ctx, tmp_path)
    with query_session(ctx, EVERYTHING, structural=True) as owner:
        rows = tuple(replace(row, dimension=3, values=(1.0, 0.0, 0.0)) for row in owner.graph.dense_vectors)
        borrowed = replace(owner, graph=replace(owner.graph, dense_vectors=rows))
        with pytest.raises(api().DenseSessionUnavailable, match="dimension"):
            with api().dense_session(ctx, session=borrowed):
                pytest.fail("wrong dimensions must reject")
    assert not server.calls


def test_supplied_resolution_is_revalidated_and_cache_hits_detect_digest_drift(ctx, tmp_path):
    from hippo.knowledge.embedding_cache import EmbeddingCache
    from hippo.knowledge.embedding_profile import resolve_embedding_profile

    prepared, server = verified(ctx, tmp_path)
    resolved = resolve_embedding_profile(ctx.ollama, spec=prepared.inputs.embedding_profile.spec)
    cache = EmbeddingCache(tmp_path / "cache.sqlite")
    with api().dense_session(ctx, EVERYTHING, resolved_profile=resolved, cache=cache) as session:
        first = session.model.embed_one("private query")
        count = len(server.embeds())
        assert np.array_equal(session.model.embed_one("private query"), first)
        assert len(server.embeds()) == count
        server.digest = "d" * 64
        try:
            with pytest.raises(EmbeddingProfileChanged):
                session.model.embed_one("private query")
            assert len(server.embeds()) == count
        finally:
            server.digest = "a" * 64
    refs_closed(ctx)


def test_verified_graph_retains_snapshot_trace_ids(ctx, tmp_path, monkeypatch):
    from hippo import ask

    verified(ctx, tmp_path)
    monkeypatch.setattr(ctx.ollama, "chat_json", lambda *args, **kwargs: {"triples": []})
    with api().dense_session(ctx, EVERYTHING) as session:
        trace = ask.search(ctx, "who builds?", session=session)
        assert trace.snapshot_ids == session.graph.snapshot_ids
        assert trace.snapshot_ids


def test_hidden_only_verified_generation_cannot_change_tag_dispatch_or_trigger_http(ctx, tmp_path):
    from hippo.knowledge import model as k

    prepared, server = verified(ctx, tmp_path)
    for span in prepared.inputs.evidence.spans:
        ctx.store.put_knowledge(
            k.Suppression(
                workspace_id=prepared.inputs.evidence.workspace_id,
                target_kind="span",
                target_id=span.id,
                scope_key="hidden original",
                created_at=datetime.now(UTC),
                reason="access_loss",
                view_applicability="all_history",
                epoch=1,
                restoration_barrier="review",
            )
        )
    _, visible = published(ctx.store, "tag visible", profile=ctx.ollama.embed_model)
    with api().retrieval_session(ctx, EVERYTHING) as session:
        assert [p.id for p in session.graph.passages] == [visible.id]
        assert session.graph.dense_capability.mode == "tag_compatible"
    assert not server.calls
    refs_closed(ctx)


@pytest.mark.parametrize("revoke", [False, True])
def test_remote_final_validation_failure_releases_even_after_body_error(ctx, tmp_path, revoke):
    _, server = verified(ctx, tmp_path)
    with pytest.raises(AuthorizationChanged if revoke else EmbeddingProfileChanged):
        with api().dense_session(ctx, EVERYTHING):
            server.digest = "f" * 64
            if revoke:
                ctx.store._bump_authorization_epoch()
            raise RuntimeError("body failed")
    refs_closed(ctx)


def test_supplied_resolution_wrong_spec_denies_without_http(ctx, tmp_path):
    from hippo.knowledge.embedding_profile import EmbeddingSpec, resolve_embedding_profile

    prepared, server = verified(ctx, tmp_path)
    resolved = resolve_embedding_profile(ctx.ollama, spec=prepared.inputs.embedding_profile.spec)
    server.calls.clear()
    with pytest.raises(EmbeddingProfileMismatch):
        with api().dense_session(ctx, EVERYTHING, resolved_profile=resolved, spec=EmbeddingSpec()):
            pytest.fail("requested prefixes must match stored descriptor")
    assert not server.calls
    refs_closed(ctx)


def test_verified_owner_stays_on_g1_when_g2_publishes_during_model_resolution(ctx, tmp_path, monkeypatch):
    prepared, server = verified(ctx, tmp_path)
    held, closed = observe(ctx, monkeypatch)
    new = None

    def publish_next(path, body):
        nonlocal new
        if new is None:
            assert len(held) == 1 and not closed
            new, _ = published(
                ctx.store, "G2", parent=prepared.inputs.generation, profile="other", dimension=7
            )

    server.hook = publish_next
    with api().dense_session(ctx, EVERYTHING) as session:
        assert new is not None
        session.validate()
        assert {row.generation_id for row in session.graph.dense_vectors} == {prepared.inputs.generation.id}
        assert all(p.text != "G2" for p in session.graph.passages)
        assert session.model.embed_one("q").shape == (2,)
    assert held == closed
    refs_closed(ctx)


def test_local_heartbeat_renews_while_metadata_http_blocks(ctx, tmp_path, monkeypatch):
    from threading import Event

    _, server = verified(ctx, tmp_path)
    inside, renewed = Event(), Event()
    original_graph, original_renew = ctx.graph_for, ctx.store.renew_snapshot_reference

    def graph_for(*args, **kwargs):
        graph = original_graph(*args, **kwargs)
        graph.snapshot_renewal_interval = 0.01
        return graph

    def renew(*args, **kwargs):
        result = original_renew(*args, **kwargs)
        if inside.is_set():
            renewed.set()
        return result

    def blocked(path, body):
        if not renewed.is_set():
            inside.set()
            assert renewed.wait(3), "heartbeat could not renew during metadata HTTP"
            inside.clear()

    monkeypatch.setattr(ctx, "graph_for", graph_for)
    monkeypatch.setattr(ctx.store, "renew_snapshot_reference", renew)
    server.hook = blocked
    with api().dense_session(ctx, EVERYTHING) as session:
        assert renewed.is_set()
        session.validate()
    refs_closed(ctx)


def test_managed_mention_entities_without_inferred_fact_are_not_legacy(ctx, tmp_path):
    verified(ctx, tmp_path)
    with query_session(ctx, EVERYTHING, structural=True) as owner:
        graph = replace(
            owner.graph,
            facts=[],
            fact_index_of={},
            fact_embeddings=np.zeros((0, 0), dtype=np.float32),
            prose_provenance=(),
            dense_vectors=tuple(row for row in owner.graph.dense_vectors if row.lane == "passage"),
        )
        with api().dense_session(ctx, session=replace(owner, graph=graph)) as session:
            assert session.graph.entity_names == graph.entity_names
            assert session.graph.dense_capability.mode == "verified"


def test_relation_only_support_generation_participates_in_tag_compatibility(ctx):
    from hippo.knowledge import model as k
    from tests.unit.test_structural_loading import shared_pair

    first, span = published(
        ctx.store,
        "relation support",
        profile="wrong-tag",
        enrich=lambda *a: shared_pair(*a, relationship=True),
    )
    published(ctx.store, "endpoints", profile=ctx.ollama.embed_model, enrich=shared_pair)
    ctx.store.put_knowledge(
        k.Suppression(
            workspace_id=ctx.store.get_source(first.source_id)["workspace_id"],
            target_kind="span",
            target_id=span.id,
            scope_key="only relation",
            created_at=datetime.now(UTC),
            reason="access_loss",
            view_applicability="all_history",
            epoch=1,
            restoration_barrier="review",
        )
    )
    with query_session(ctx, EVERYTHING, structural=True) as owner:
        assert all(row.generation_id != first.id for row in owner.graph.dense_vectors)
        assert all(row.generation_id != first.id for row in owner.graph.structural_code_evidence)
        assert owner.graph.structural_relations[0].source_generations == ((first.source_id, first.id),)
        with pytest.raises(EmbeddingProfileMismatch):
            with api().retrieval_session(ctx, session=owner):
                pytest.fail("relation support cannot escape profile checks")


def test_normal_dense_bound_managed_code_without_structural_sidecar_is_verified(ctx, tmp_path):
    from hippo.hipporag.graph_index import CodeNode
    from hippo.knowledge.projection import _assemble

    prepared, _ = verified(ctx, tmp_path)
    with query_session(ctx, EVERYTHING, structural=True) as owner:
        original = owner.graph
        node = CodeNode("fixture-code", "symbol", "f", source_id=prepared.inputs.generation.source_id)
        graph = _assemble(
            original.entity_names,
            [node],
            original.passages,
            {},
            original.facts,
            {},
            {(original.node_ids[a], original.node_ids[b]): edge for (a, b), edge in original.edges.items()},
            [(node.id, original.passages[0].id, "DEFINED_IN", 1.0, "authorized_evidence", {})],
            retrieval_evidence=original.retrieval_evidence,
            original_citations=original.original_citations,
            prose_provenance=original.prose_provenance,
            managed_passage_ids=original.managed_passage_ids,
            dense_capability=original.dense_capability,
            dense_vectors=original.dense_vectors,
        )
        assert not graph.structural_code_evidence
        with api().dense_session(ctx, session=replace(owner, graph=graph)) as session:
            assert session.graph.dense_capability.mode == "verified"
            assert [n.id for n in session.graph.code_nodes] == [node.id]


def test_tag_capability_preserves_zero_legacy_rows_scopes_and_fingerprints():
    from hippo.knowledge.dense import DenseCapability, structural_legacy_graph
    from hippo.knowledge.projection import compose_graphs
    from tests.unit.test_dense_capability import base_graph, capable
    from tests.unit.test_structural_loading import legacy_graph

    legacy = legacy_graph()
    legacy.passage_embeddings[:] = 0
    structural = compose_graphs(
        capable(base_graph("managed", dimension=3), "unavailable", profile="tag"),
        structural_legacy_graph(legacy),
    )
    rows = {
        (row.lane, row.projected_id): row.values
        for row in (*structural.dense_vectors, *structural.legacy_dense_vectors)
    }
    activated = replace(
        structural,
        dense_capability=DenseCapability("tag_compatible", dimension=3),
        passage_embeddings=np.asarray([rows["passage", p.id] for p in structural.passages], dtype=np.float32),
        fact_embeddings=np.asarray([rows["fact", f.id] for f in structural.facts], dtype=np.float32),
    )
    assert view_fingerprint(activated) == view_fingerprint(structural)
    assert activated.scoped(set()).passage_embeddings.shape == (0, 3)
    assert activated.scoped(set()).fact_embeddings.shape == (0, 3)
    combined = compose_graphs(activated.scoped({"managed"}), activated.scoped({"legacy"}))
    assert view_fingerprint(combined) == view_fingerprint(activated)
    with pytest.raises(ValueError):
        replace(activated, passage_embeddings=activated.passage_embeddings + 1)
    with pytest.raises(ValueError):
        DenseCapability("tag_compatible", fingerprint="a" * 64, dimension=3)


def test_typed_observation_only_generation_participates_in_tag_selection(ctx):
    from hippo.knowledge import model as k
    from hippo.knowledge.identity import text_hash
    from tests.unit.test_derived_generation_store import member
    from tests.unit.test_structural_loading import typed_pair

    def typed(store, gen, revision, span, now):
        original = span.replace(
            text="typed observation",
            text_hash=text_hash("typed observation"),
            locator_json='{"kind":"file_lines","path":"a.txt","start":2,"end":2}',
        )
        member(store, gen, original)
        typed_pair(store, gen, revision, original, now, relationship=False)

    gen, span = published(ctx.store, "typed only", profile="wrong-tag", enrich=typed)
    ctx.store.put_knowledge(
        k.Suppression(
            workspace_id=ctx.store.get_source(gen.source_id)["workspace_id"],
            target_kind="span",
            target_id=span.id,
            scope_key="typed only",
            created_at=datetime.now(UTC),
            reason="access_loss",
            view_applicability="all_history",
            epoch=1,
            restoration_barrier="review",
        )
    )
    published(ctx.store, "dense", profile=ctx.ollama.embed_model)
    with query_session(ctx, EVERYTHING, structural=True) as owner:
        assert {row.generation_id for row in owner.graph.structural_object_evidence} == {gen.id}
        assert all(row.generation_id != gen.id for row in owner.graph.dense_vectors)
        with pytest.raises(EmbeddingProfileMismatch):
            with api().retrieval_session(ctx, session=owner):
                pytest.fail("typed observation profile cannot escape eligibility")


def test_verified_code_only_uses_stored_width_without_invented_vectors(ctx, tmp_path):
    from hippo.hipporag.graph_index import CodeNode
    from hippo.knowledge.dense import DenseCapability, StructuralCodeEvidence
    from hippo.knowledge.projection import _assemble

    prepared, server = verified(ctx, tmp_path)
    with query_session(ctx, EVERYTHING, structural=True) as owner:
        originals = owner.graph.original_citations
        gen = prepared.inputs.generation
        node = CodeNode("code-only", "symbol", "f", source_id=gen.source_id)
        graph = _assemble(
            {},
            [node],
            [],
            {},
            [],
            {},
            {},
            [],
            original_citations=originals,
            dense_capability=DenseCapability("unavailable"),
            structural_code_evidence=(
                StructuralCodeEvidence(
                    node.id, gen.id, gen.source_id, tuple(sorted(original.id for original in originals))
                ),
            ),
        )
        with api().dense_session(ctx, session=replace(owner, graph=graph)) as session:
            assert session.graph.passage_embeddings.shape == session.graph.fact_embeddings.shape == (0, 2)
            assert session.graph.structural_code_evidence == graph.structural_code_evidence
            assert session.graph.original_citations == originals
            session.graph.require_dense(session.model.profile_fingerprint)
    assert server.calls


def test_populated_default_legacy_borrow_rejects_without_reacquiring(ctx, monkeypatch):
    source = ctx.store.create_source("text", "legacy")
    ctx.store.add_passages(
        [dict(id="p", source_id=source, title="p", text="p", ordinal=0, embedding=[1.0, 0.0])]
    )
    held, closed = observe(ctx, monkeypatch)
    with query_session(ctx, EVERYTHING) as owner:
        assert owner.graph.dense_capability.mode == "legacy"
        with pytest.raises(api().DenseSessionUnavailable, match="structural"):
            with api().retrieval_session(ctx, session=owner):
                pytest.fail("cannot reload to upgrade a borrowed graph")
        assert len(held) == 1 and not closed
    assert held == closed


@pytest.mark.parametrize("when", ["before", "during"])
def test_profile_property_rechecks_authorization_around_a_blocked_read(when):
    from threading import Event, Thread

    entered, resume, revoked = Event(), Event(), Event()
    results = []

    class Model:
        @property
        def profile_fingerprint(self):
            entered.set()
            assert resume.wait(3)
            return "a" * 64

    def validate():
        if revoked.is_set():
            raise AuthorizationChanged("revoked")

    guarded = AuthorizedModel(AuthorizedModel(Model(), validate), validate)

    def read():
        try:
            results.append(guarded.profile_fingerprint)
        except BaseException as error:
            results.append(error)

    if when == "before":
        revoked.set()
        resume.set()
    worker = Thread(target=read)
    worker.start()
    try:
        if when == "during":
            assert entered.wait(3)
            revoked.set()
            resume.set()
        worker.join(3)
        assert not worker.is_alive()
        assert len(results) == 1 and isinstance(results[0], AuthorizationChanged)
        assert entered.is_set() == (when == "during")
    finally:
        resume.set()
        worker.join(3)
