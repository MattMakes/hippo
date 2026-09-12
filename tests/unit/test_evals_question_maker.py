"""Generating sample questions about the indexed sample corpus (single-hop and multi-hop)."""

from __future__ import annotations

import logging

import pytest

from hippo.evals import question_maker
from hippo.evals.question_maker import generate_questions, shared_entity_pairs, start_generation_job
from hippo.hipporag.indexer import Chunk, index_source
from hippo.knowledge.embedding_profile import EmbeddingProfileMismatch


def index_sample(ctx, sample_text: str) -> str:
    """Index samples/acme_robotics.md as one passage per '## ' section. Returns the source id."""
    source_id = ctx.store.create_source("sample", "Acme Robotics")
    chunks = []
    for ordinal, section in enumerate(sample_text.split("## ")[1:]):
        title, _, body = section.partition("\n")
        chunks.append(Chunk(ordinal, title.strip(), body.strip()))
    index_source(ctx.store, ctx.ollama, source_id, chunks, workers=2)
    ctx.store.update_source(source_id, status="ready")
    return source_id


@pytest.fixture
def source_id(ctx, sample_text) -> str:
    return index_sample(ctx, sample_text)


def test_generates_single_and_multihop_questions(ctx, source_id):
    set_id = generate_questions(ctx, source_id, max_single=10, max_multihop=5)

    question_set = ctx.store.get_question_set(set_id)
    assert question_set["status"] == "ready"
    assert question_set["origin"] == "generated"
    assert question_set["source_id"] == source_id
    assert question_set["progress_done"] == question_set["progress_total"] > 0

    questions = ctx.store.list_questions(set_id)
    singles = [q for q in questions if q["kind"] == "single"]
    multis = [q for q in questions if q["kind"] == "multihop"]
    assert len(singles) >= 3
    assert len(multis) >= 1

    passage_ids = set(ctx.store.passage_ids_for_source(source_id))
    for q in questions:
        assert q["text"] and q["expected_answer"]
        assert set(q["gold_passage_ids"]) <= passage_ids
    assert all(len(q["gold_passage_ids"]) == 1 for q in singles)
    assert all(len(set(q["gold_passage_ids"])) == 2 for q in multis)
    # The fake writes single-hop questions straight from the sentences, e.g. "Acme Robotics was founded in what?"
    assert any("Acme Robotics" in q["text"] for q in singles)
    assert all("shared entity" in q["notes"] for q in multis)


def test_limits_are_respected_and_passages_are_spread(ctx, source_id):
    set_id = generate_questions(ctx, source_id, max_single=3, max_multihop=1)
    questions = ctx.store.list_questions(set_id)
    singles = [q for q in questions if q["kind"] == "single"]
    multis = [q for q in questions if q["kind"] == "multihop"]
    assert len(singles) == 3
    assert len(multis) == 1
    # Three picks over eight passages should not all come from the first three sections.
    ordinals = {ctx.store.get_passages(q["gold_passage_ids"])[0]["ordinal"] for q in singles}
    assert max(ordinals) >= 3


def test_shared_entity_pairs_prefer_specific_links(ctx, source_id):
    index = ctx.graph()
    passages = [p for p in index.passages if p.source_id == source_id]
    pairs = shared_entity_pairs(index, passages)
    assert pairs
    names = [name for name, _, _ in pairs]
    assert "acme robotics" in names  # mentioned by "The company" and "The Orion arm"
    # No two candidates repeat the same passage pair.
    keys = [frozenset((a.id, b.id)) for _, a, b in pairs]
    assert len(keys) == len(set(keys))
    for _, a, b in pairs:
        assert a.id != b.id


def test_background_job_fills_the_set(ctx, source_id):
    set_id = start_generation_job(ctx, source_id, max_single=2, max_multihop=1, name="My set")
    assert ctx.store.get_question_set(set_id)["name"] == "My set"
    ctx.jobs.wait_all()
    question_set = ctx.store.get_question_set(set_id)
    assert question_set["status"] == "ready"
    assert question_set["question_count"] >= 3


def test_source_without_passages_fails_cleanly(ctx):
    empty = ctx.store.create_source("text", "Nothing here")
    with pytest.raises(ValueError):
        generate_questions(ctx, empty)
    sets = ctx.store.list_question_sets()
    assert len(sets) == 1
    assert sets[0]["status"] == "failed"
    assert "no indexed passages" in sets[0]["error"]


def test_unknown_source_is_an_error(ctx):
    with pytest.raises(ValueError):
        generate_questions(ctx, "nope")


def test_a_failing_generation_logs_the_source_and_set_but_not_the_exception(
    ctx, source_id, monkeypatch, caplog
):
    """The generation-failure log line is bounded the same way as the runner's per-question one."""
    poison = "sk-live-DEADBEEF 'Acme Robotics is headquartered in Boulder.'"

    def exploding(*args, **kwargs):
        raise EmbeddingProfileMismatch(poison)

    monkeypatch.setattr(question_maker, "shared_entity_pairs", exploding)
    with caplog.at_level(logging.DEBUG, logger="hippo.evals.question_maker"):
        with pytest.raises(EmbeddingProfileMismatch):
            generate_questions(ctx, source_id)

    sets = ctx.store.list_question_sets()
    assert len(sets) == 1 and sets[0]["status"] == "failed"
    assert caplog.records, "a failed generation must not fail silently either"
    assert source_id in caplog.text
    assert sets[0]["id"] in caplog.text
    assert "retrieval_rebuild_required" in caplog.text
    assert "EmbeddingProfileMismatch" in caplog.text
    assert poison not in caplog.text
    assert not [record for record in caplog.records if record.exc_info]
