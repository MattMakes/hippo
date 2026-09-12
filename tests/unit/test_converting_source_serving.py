"""A converting source serves its legacy graph until its first publication.

Blocker A of `ai_docs/plans/rag-it-all-task-5-managed-code-capture.md` section 7: a
repository bootstrap stages over many transactions, and the Artifact-presence
classification in `context.py` and `status.py` made the legacy graph disappear from
every read path the moment the first staging row committed.

The lane is `store.source_serves_legacy` -- no active pointer and no published
`IndexEvent` -- so what changes it is a publication, which sets the pointer, the counts
and the presentation together. The `managed` flag keeps its own meaning and its own
timing: it is set from the first staged row, because it is what the cleanup and dispatch
guards read, and a source mid-conversion must stay protected by them.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from hippo.access import EVERYTHING, Access
from hippo.ask import ask, search
from hippo.knowledge import model as k
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.lifecycle import generation_passage_id
from hippo.knowledge.query_access import query_session
from hippo.status import source_view, system_status
from tests.fakes.fake_ollama import embed_text

CODE_QUESTION = "What does pyapp.orders.OrderService.place do?"
MANAGED_TEXT = "A managed generation is served only once it is published."


# ------------------------------------------------------------------ staging


def stage(store, source_id, *, key="converting", profile="p", text=MANAGED_TEXT, vector=(1.0, 0.0)):
    """One complete unpublished generation on an existing source, under a claimed fenced build.

    The rows a repository bootstrap commits batch by batch, written directly rather than
    through a coordinator: an accepted input, its revision and span, the generation's
    membership and one generation-tagged passage.
    """
    now = datetime.now(UTC)
    workspace = store.get_source(source_id)["workspace_id"]
    policy = k.AccessPolicy(
        workspace_id=workspace, origin="local_curated", scope_key=key, mode="workspace", verified_at=now
    )
    artifact = k.Artifact(
        workspace_id=workspace,
        source_id=source_id,
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
        text=text,
        policy_id=policy.id,
    )
    gen = k.Generation(
        source_id=source_id,
        parent_id=None,
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
        gen.id, job_key=key, lease_owner="cc1", lease_expires_at=now + timedelta(minutes=5)
    )
    authority = dict(job_id=job.id, lease_owner=job.lease_owner, fencing_token=job.fencing_token)
    passage_id = generation_passage_id(gen.id, revision.id, span.id, 0)
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
                    id=passage_id,
                    source_id=source_id,
                    generation_id=gen.id,
                    artifact_revision_id=revision.id,
                    span_id=span.id,
                    embedding_profile=profile,
                    text=text,
                    title=key,
                    ordinal=0,
                    embedding=list(vector),
                )
            ]
        )
    return SimpleNamespace(
        generation=gen, authority=authority, profile=profile, passage_id=passage_id, source_id=source_id
    )


def publish(store, staged):
    """Seal and publish the staged generation, exactly as a coordinator's last step does."""
    manifest = k.IndexManifest(
        generation_id=staged.generation.id,
        profile_fingerprint=staged.profile,
        config_fingerprint="c",
        required_representations=("evidence", "dense", "native"),
        checksums=store.generation_checksums(staged.generation.id),
        ready=True,
    )
    store.seal_generation(staged.generation.id, manifest, **staged.authority)
    return store.publish_staged_generation(
        staged.generation.id,
        expected_parent_id=None,
        expected_suppression_epoch=store.suppression_epoch(),
        published_at=datetime.now(UTC),
        **staged.authority,
    )


def legacy_source(store, key="converting source"):
    """A plain legacy source with one untagged passage: the graph a conversion must keep."""
    source = store.create_source("text", key)
    store.add_passages(
        [
            dict(
                id=f"{source}:0",
                source_id=source,
                text="The legacy passage stays selected until the conversion publishes.",
                title="Legacy",
                ordinal=0,
                embedding=[0.0, 1.0],
            )
        ]
    )
    store.update_source(source, status="ready")
    return source


def row_of(view, source_id):
    return next((row for row in view.sources if row["id"] == source_id), None)


def rows_for(view, source_id):
    return [row for row in view.sources if row["id"] == source_id]


def presentation(row):
    """One inventory row without the controls a claimed staging build writes.

    `claim_generation_build` records the holder and its fence on the Source row, the first
    staged record sets `managed`, which says the managed lane owns this source's cleanup
    and dispatch, and `_lock_source` bumps `generation_lock` on every backend but the fake
    one. None of those is presentation: everything a reader is shown must be exactly what
    it was before the conversion started. `generation_lock` is excluded by
    `test_managed_pipeline_activation.row_of` and by `_bootstrap_envelope` for the same
    reason.
    """
    return {key: value for key, value in row.items() if key not in BUILD_CONTROLS}


BUILD_CONTROLS = ("active_build_id", "build_fencing_token", "generation_lock", "updated_at", "managed")


# ------------------------------------------------------- the store predicate


def test_staging_rows_alone_keep_a_source_in_the_legacy_lane(store):
    source = legacy_source(store)
    staged = stage(store, source)

    row = store.get_source(source)
    assert store.source_serves_legacy(row) is True
    # The flag still flips at staging start, because it is what the managed lane's cleanup
    # and dispatch guards read. It is not what decides which lane answers a query.
    assert store.source_is_managed(source) is True
    assert row.get("active_generation_id") is None
    assert store._knowledge_get("Generation", staged.generation.id).status == "staging"


def test_a_failed_unpublished_generation_keeps_the_source_in_the_legacy_lane(store):
    source = legacy_source(store)
    staged = stage(store, source)
    store.fail_generation_build(staged.generation.id, **staged.authority)

    assert store._knowledge_get("Generation", staged.generation.id).status == "failed"
    assert store.source_serves_legacy(store.get_source(source)) is True


def test_publication_moves_the_source_out_of_the_legacy_lane(store):
    source = legacy_source(store)
    staged = stage(store, source)
    assert store.source_serves_legacy(store.get_source(source)) is True

    publish(store, staged)

    row = store.get_source(source)
    assert store.source_serves_legacy(row) is False
    assert row["active_generation_id"] == staged.generation.id
    assert store.source_is_managed(source) is True


def test_each_clause_of_the_predicate_leaves_the_legacy_lane_on_its_own(store):
    source = legacy_source(store)
    staged = stage(store, source)
    publish(store, staged)
    row = store.get_source(source)

    # The active pointer alone, then the published event alone.
    assert store.source_serves_legacy(row) is False
    assert store.source_serves_legacy({**row, "active_generation_id": None}) is False


def test_the_managed_flag_alone_does_not_leave_the_legacy_lane(store):
    """The flag is a cleanup and dispatch control; only a publication changes what serves."""
    source = legacy_source(store)
    store.begin_managed_source(source)

    assert store.source_is_managed(source) is True
    assert store.source_serves_legacy(store.get_source(source)) is True


def test_an_unconverted_legacy_source_serves_legacy(store):
    source = legacy_source(store)

    assert store.source_serves_legacy(store.get_source(source)) is True


def test_a_source_mid_conversion_cannot_be_wiped_by_a_source_wide_cleanup(store):
    """Serving legacy is not the same as being unmanaged for a destructive operation.

    The cleanup would delete exactly the graph the conversion is still serving and orphan
    its staged rows. `legacy_source_cleanup` reads the managed flag, which is set from the
    first staged row, so the refusal holds throughout the conversion.
    """
    source = legacy_source(store)
    stage(store, source)
    assert store.source_serves_legacy(store.get_source(source)) is True

    for operation in (
        store.delete_passages_for_source,
        store.delete_code_nodes_for_source,
        store.delete_source,
    ):
        with pytest.raises(ValueError):
            operation(source)
    assert [passage["source_id"] for passage in store.load_passages()].count(source) == 2


def test_the_predicate_is_a_pure_read_of_the_row_and_takes_no_lock(store, monkeypatch):
    source = legacy_source(store)
    stage(store, source)
    monkeypatch.setattr(
        type(store), "_lock_source", lambda *a, **kw: pytest.fail("the predicate took the source lock")
    )
    monkeypatch.setattr(store, "_now", lambda: pytest.fail("the predicate read a clock"), raising=False)

    assert store.source_serves_legacy(store.get_source(source)) is True


# ------------------------------------------------- serving through the graph


def test_a_converting_source_still_answers_search_and_ask_from_its_legacy_graph(code_index):
    ctx, source = code_index
    before = search(ctx, CODE_QUESTION)
    before_nodes = {node.id for node in ctx.graph_for(EVERYTHING).code_nodes}
    assert before.passages and before_nodes

    staged = stage(ctx.store, source, profile=ctx.ollama.embed_model, vector=embed_text(MANAGED_TEXT))

    after = search(ctx, CODE_QUESTION)
    assert [row.passage_id for row in after.passages] == [row.passage_id for row in before.passages]
    assert staged.passage_id not in {row.passage_id for row in after.passages}
    assert {node.id for node in ctx.graph_for(EVERYTHING).code_nodes} == before_nodes

    trace, answer = ask(ctx, CODE_QUESTION)
    assert [row.passage_id for row in trace.passages] == [row.passage_id for row in before.passages]
    assert staged.passage_id not in set(answer.passage_ids)


def test_a_converting_source_appears_once_in_inventory_with_its_legacy_counts(code_index):
    ctx, source = code_index
    # An audience inventory, not the internal one: `EVERYTHING` reports the Store's own
    # counters, which legitimately count every row ever written, staged rows included.
    audience = Access(rank=0, unrestricted=True, audience_kind="open")
    before_status = system_status(ctx, access=audience)
    before_row = row_of(source_view(ctx, EVERYTHING), source)
    assert before_row is not None and before_row["kind"] != "managed"

    stage(ctx.store, source, profile=ctx.ollama.embed_model, vector=embed_text(MANAGED_TEXT))

    view = source_view(ctx, EVERYTHING)
    assert [presentation(row) for row in rows_for(view, source)] == [presentation(before_row)]
    assert source in view.legacy_ids
    # The one row field the conversion does change, and it is a control, not a count.
    assert not before_row.get("managed") and row_of(view, source)["managed"] is True
    assert system_status(ctx, access=audience)["stats"] == before_status["stats"]
    assert system_status(ctx, access=audience)["stats"]["sources"] == 1


def test_publication_flips_the_lane_the_pointer_and_the_presentation_together(code_index):
    ctx, source = code_index
    legacy_passages = {row.id for row in ctx.graph_for(EVERYTHING).passages if row.source_id == source}
    staged = stage(ctx.store, source, profile=ctx.ollama.embed_model, vector=embed_text(MANAGED_TEXT))

    publish(ctx.store, staged)

    with query_session(ctx, EVERYTHING, structural=True) as session:
        assert session.graph.selected_managed_generations == ((source, staged.generation.id),)
        # The managed lane presents its evidence under projected identities, so what proves
        # the swap is that exactly one passage is served and no legacy row is among them.
        selected = [row for row in session.graph.passages if row.source_id == source]
        assert [row.text for row in selected] == [MANAGED_TEXT]
        assert not {row.id for row in selected} & legacy_passages
        assert not [node for node in session.graph.code_nodes if node.source_id == source]
        row = row_of(source_view(ctx, EVERYTHING, session=session), source)
    assert row["kind"] == "managed" and row["managed"] is True
    assert row["passages"] == 1
    assert source not in source_view(ctx, EVERYTHING).legacy_ids


def test_a_held_legacy_session_is_invalidated_when_the_conversion_starts(code_index):
    """The staging-start flip is an authorization change, and a held view must repeat.

    The source's authorization model changes there: the source ACL authorized the legacy
    graph, and from that moment the managed lane owns the source. Serving does not change
    until publication, but the view a caller is holding is no longer the one it proved.
    """
    ctx, source = code_index

    refused = []
    with pytest.raises(AuthorizationChanged):
        with query_session(ctx, EVERYTHING, structural=True) as session:
            session.validate()
            assert {row.source_id for row in session.graph.passages} == {source}
            stage(ctx.store, source, profile=ctx.ollama.embed_model, vector=embed_text(MANAGED_TEXT))
            try:
                session.validate()
            except AuthorizationChanged:
                refused.append("held legacy session")
                raise
    assert refused == ["held legacy session"]


# -------------------------------------------------------- Ladybug durability


def test_a_ladybug_reopen_during_staging_still_serves_legacy(tmp_path):
    """Staging state is durable, and reopening mid-conversion must not move the lane."""
    if os.environ.get("HIPPO_TEST_STORE", "").strip().lower() != "ladybug":
        pytest.skip("reopen is a LadybugDB persistence assertion")
    from hippo.store.ladybug import LadybugStore

    path = tmp_path / "converting.lbug"
    store = LadybugStore(path)
    try:
        source = legacy_source(store)
        staged = stage(store, source)
        assert store.source_serves_legacy(store.get_source(source)) is True
    finally:
        store.close()

    reopened = LadybugStore(path)
    try:
        row = reopened.get_source(source)
        assert reopened.source_serves_legacy(row) is True
        assert reopened._knowledge_get("Generation", staged.generation.id).status == "staging"
        assert [passage["id"] for passage in reopened.load_passages()] == [
            f"{source}:0",
            staged.passage_id,
        ]
    finally:
        reopened.close()
