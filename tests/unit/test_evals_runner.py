"""Running a question set end to end with the fakes, plus the pure summary."""

from __future__ import annotations

import logging

import pytest

from hippo.evals import runner
from hippo.evals.question_maker import generate_questions
from hippo.evals.runner import run_question, start_run, summarize
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
def set_id(ctx, sample_text) -> str:
    source_id = index_sample(ctx, sample_text)
    # per_passage=3 so the company passage also yields "Acme Robotics is headquartered in what?"
    return generate_questions(ctx, source_id, per_passage=3, max_single=10, max_multihop=3)


def test_run_answers_every_question_and_summarizes(ctx, set_id):
    run_id = start_run(ctx, set_id, name="first run", settings={"damping": 0.6})
    assert ctx.jobs.is_running(f"run:{run_id}") or ctx.store.get_run(run_id)["status"] in ("running", "done")
    ctx.jobs.wait_all()

    run = ctx.store.get_run(run_id)
    questions = ctx.store.list_questions(set_id)
    assert run["status"] == "done"
    assert run["name"] == "first run"
    assert run["finished_at"]
    assert run["progress_done"] == run["progress_total"] == len(questions)
    assert run["settings"]["damping"] == 0.6
    assert run["settings"]["linking_top_k"] == ctx.store.get_settings()["linking_top_k"]

    results = ctx.store.list_results(run_id)
    assert len(results) == len(questions)
    assert all(r["error"] is None for r in results)
    assert all(r["answer"] for r in results)
    assert all(r["latency_ms"] is not None and r["latency_ms"] >= 0 for r in results)
    assert all(r["verdict"] in ("correct", "partially_correct", "incorrect") for r in results)
    assert all(r["recall"] for r in results)  # every generated question has gold passages

    summary = run["summary"]
    assert 0.0 <= summary["accuracy"] <= 1.0
    assert summary["questions"] == len(questions)
    assert summary["correct"] + summary["partial"] + summary["incorrect"] == len(questions)
    assert "recall@5" in summary and summary["gold_in_top5"] is not None

    # A plain single-hop question like "Acme Robotics is headquartered in what?" must come out correct.
    correct_singles = [r for r in results if r["kind"] == "single" and r["verdict"] == "correct"]
    assert correct_singles
    assert any("Acme Robotics" in r["question"] for r in correct_singles)
    headquartered = [r for r in results if r["kind"] == "single" and "headquartered" in r["question"]]
    assert headquartered and headquartered[0]["question"] == "Acme Robotics is headquartered in what?"
    assert headquartered[0]["verdict"] == "correct"
    assert headquartered[0]["gold_rank"] == 1

    # The stored result carries the full trace for the Analyze page.
    full = ctx.store.get_result(results[0]["id"])
    assert full["trace"]["question"] == results[0]["question"]
    assert full["trace"]["passages"]


def test_run_question_returns_every_field_add_result_wants(ctx, set_id):
    question = ctx.store.list_questions(set_id)[0]
    result = run_question(ctx, question, ctx.store.get_settings())
    expected_keys = {
        "answer",
        "thought",
        "verdict",
        "judge_score",
        "judge_reason",
        "exact_match",
        "f1",
        "recall",
        "gold_rank",
        "latency_ms",
        "trace",
        "used_dpr_fallback",
        "error",
    }
    assert expected_keys <= set(result)
    assert result["error"] is None
    assert result["used_dpr_fallback"] is False  # the graph search found seeds
    assert result["trace"]["settings"]["qa_top_k"] == 5
    assert result["judge_score"] in (0.0, 0.5, 1.0)


def test_question_without_expected_answer_is_not_judged(ctx, set_id):
    row = {
        "id": "x",
        "text": "Acme Robotics is headquartered in what?",
        "expected_answer": "",
        "gold_passage_ids": [],
    }
    result = run_question(ctx, row, ctx.store.get_settings())
    assert result["answer"]
    assert result["verdict"] == ""
    assert result["judge_score"] is None
    assert result["exact_match"] is None
    # `code_seeded` describes the trace, not the gold set, so it is written even here. What must
    # stay absent is every gold-derived key: no `recall@k`, no rank, and no place in `summarize`'s
    # gold means (test_evals_code.py::test_summarize_means_the_new_keys pins that half).
    assert result["recall"] == {"code_seeded": 0.0}
    assert result["gold_rank"] is None


def test_one_broken_question_does_not_kill_the_run(ctx, set_id, monkeypatch):
    real_search = runner.search
    questions = ctx.store.list_questions(set_id)
    poison = questions[0]["text"]

    def flaky_search(ctx_, text, settings, access=None, **kwargs):
        if text == poison:
            raise RuntimeError("boom")
        return real_search(ctx_, text, settings, access, **kwargs)

    monkeypatch.setattr(runner, "search", flaky_search)
    run_id = start_run(ctx, set_id)
    ctx.jobs.wait_all()

    run = ctx.store.get_run(run_id)
    assert run["status"] == "done"
    results = ctx.store.list_results(run_id)
    assert len(results) == len(questions)
    broken = [r for r in results if r["error"]]
    assert len(broken) == 1
    assert "boom" in broken[0]["error"]
    assert broken[0]["question"] == poison
    assert run["summary"]["errors"] == 1
    assert run["summary"]["questions"] == len(questions)


def test_a_failed_question_stores_its_closed_code_in_front_of_the_private_text(ctx, set_id, monkeypatch):
    """The code is the half a reader may see, so it is stored where a reader can find it.

    `store.add_result` writes a fixed property list, so the closed code rides in the first
    segment of `error`, exactly as `managed_activation.record_build_failure` stores it on a
    Source row. The rest of the string stays what it was: the operator's whole story.
    """
    poison = "sk-live-DEADBEEF"

    def exploding_search(*args, **kwargs):
        raise EmbeddingProfileMismatch(poison)

    monkeypatch.setattr(runner, "search", exploding_search)
    run_id = start_run(ctx, set_id)
    ctx.jobs.wait_all()

    results = ctx.store.list_results(run_id)
    assert results and all(row["error"] for row in results)
    assert all(row["error"].startswith("retrieval_rebuild_required: ") for row in results)
    assert all(poison in row["error"] for row in results), "the private record is unchanged"
    summary = ctx.store.get_run(run_id)["summary"]
    assert summary["errors"] == len(results)
    assert summary["error_codes"] == ["retrieval_rebuild_required"]


def test_summarize_lists_each_closed_code_once():
    results = [
        {"error": "retrieval_unavailable: OllamaError: boom"},
        {"error": "retrieval_rebuild_required: EmbeddingProfileMismatch: boom"},
        {"error": "retrieval_unavailable: OllamaError: again"},
        {"error": "EmbeddingProfileMismatch: a row written before the code existed"},
        {"error": None},
        # The shape `EvalAccess.get_run` summarizes: the private half is already gone.
        {"error": None, "failure_code": "retrieval_unavailable"},
    ]
    summary = summarize(results)
    assert summary["errors"] == 5
    assert summary["error_codes"] == [
        "operation_failed",
        "retrieval_rebuild_required",
        "retrieval_unavailable",
    ]


def test_a_failing_question_logs_its_id_and_code_but_neither_its_text_nor_the_exception(
    ctx, set_id, monkeypatch, caplog
):
    """The per-question log line is bounded, like every other managed failure record.

    A generated question is written out of source passages and `Ollama._request` puts
    300 characters of the model's reply body into its message, so the question text and
    `str(exc)` are both private material. What an operator needs to find the run in the
    local logs is the question's id and the closed code; the exception's type names the
    family without quoting it.
    """
    question = ctx.store.list_questions(set_id)[0]
    poison = "sk-live-DEADBEEF 'Acme Robotics is headquartered in Boulder.'"

    def exploding_search(*args, **kwargs):
        raise EmbeddingProfileMismatch(poison)

    monkeypatch.setattr(runner, "search", exploding_search)
    with caplog.at_level(logging.DEBUG, logger="hippo.evals.runner"):
        result = run_question(ctx, question, ctx.store.get_settings())

    assert result["error"], "the private record still keeps the whole story"
    assert caplog.records, "a failed question must not fail silently either"
    assert question["id"] in caplog.text
    assert "retrieval_rebuild_required" in caplog.text
    assert "EmbeddingProfileMismatch" in caplog.text
    assert question["text"] not in caplog.text
    assert poison not in caplog.text
    assert not [record for record in caplog.records if record.exc_info]


def test_a_failing_run_logs_its_id_and_code_but_not_the_exception(ctx, set_id, monkeypatch, caplog):
    """The whole-run log line is bounded the same way as the per-question one.

    Landing in `_run_all`'s own `except` means the store itself failed, not one question, so
    there is no single question id to log -- but the exception is still private material and
    must not reach the logger any more than a per-question failure would. Calls `_run_all`
    directly rather than through `ctx.jobs`: the background job runner has its own crash
    logger that reports the full traceback, which is `hippo.jobs`'s concern, not this line's.
    """
    from hippo.evals.runner import _run_all

    run_id = ctx.store.create_run(set_id, "run", ctx.store.get_settings())
    poison = "sk-live-DEADBEEF 'Acme Robotics is headquartered in Boulder.'"

    def exploding_save(*args, **kwargs):
        raise EmbeddingProfileMismatch(poison)

    monkeypatch.setattr(runner, "save_evaluation_result", exploding_save)
    with caplog.at_level(logging.DEBUG, logger="hippo.evals.runner"):
        with pytest.raises(EmbeddingProfileMismatch):
            _run_all(ctx, run_id, set_id, ctx.store.get_settings())

    run = ctx.store.get_run(run_id)
    assert run["status"] == "failed"
    assert caplog.records, "a failed run must not fail silently either"
    assert run_id in caplog.text
    assert "retrieval_rebuild_required" in caplog.text
    assert "EmbeddingProfileMismatch" in caplog.text
    assert poison not in caplog.text
    assert not [record for record in caplog.records if record.exc_info]


def test_start_run_rejects_unknown_set(ctx):
    with pytest.raises(ValueError):
        start_run(ctx, "nope")


def test_summarize_is_pure_and_skips_missing_numbers():
    results = [
        {
            "verdict": "correct",
            "judge_score": 1.0,
            "exact_match": 1.0,
            "f1": 1.0,
            "recall": {"recall@1": 1.0, "recall@5": 1.0},
            "gold_rank": 1,
            "latency_ms": 100.0,
            "trace": {"used_dpr_fallback": False},
            "used_dpr_fallback": False,
            "error": None,
        },
        {
            "verdict": "incorrect",
            "judge_score": 0.0,
            "exact_match": 0.0,
            "f1": 0.5,
            "recall": {"recall@1": 0.0, "recall@5": 0.0},
            "gold_rank": None,
            "latency_ms": 300.0,
            "trace": None,  # store.list_results rows have no trace; the flag stands on its own
            "used_dpr_fallback": True,
            "error": None,
        },
        {  # no expected answer, no gold passages, and it errored: contributes only to counts
            "verdict": "",
            "judge_score": None,
            "exact_match": None,
            "f1": None,
            "recall": {},
            "gold_rank": None,
            "latency_ms": None,
            "trace": None,
            "error": "boom",
        },
    ]
    before = [dict(r) for r in results]
    summary = summarize(results)
    assert results == before  # nothing was mutated
    assert summary["questions"] == 3
    assert summary["errors"] == 1
    assert summary["accuracy"] == 0.5
    assert (summary["correct"], summary["partial"], summary["incorrect"]) == (1, 0, 1)
    assert summary["exact_match"] == 0.5
    assert summary["f1"] == 0.75
    assert summary["recall@1"] == 0.5
    assert summary["recall@5"] == 0.5
    assert summary["recall@20"] is None
    assert summary["mean_gold_rank"] == 1
    assert summary["gold_in_top5"] == 0.5
    assert summary["dpr_fallbacks"] == 1
    assert summary["mean_latency_ms"] == 200.0


def test_a_question_on_an_empty_memory_is_marked_as_a_fallback(ctx):
    row = {"id": "x", "text": "Where is Acme?", "expected_answer": "", "gold_passage_ids": []}
    result = run_question(ctx, row, ctx.store.get_settings())
    assert result["used_dpr_fallback"] is True
    assert result["trace"]["fallback_reason"] == "the memory is empty"
    assert summarize([result])["dpr_fallbacks"] == 1


def test_summarize_of_nothing():
    summary = summarize([])
    assert summary["questions"] == 0
    assert summary["accuracy"] is None
    assert summary["correct"] == 0


# ------------------- wrap-up finding 13: the borrow pair the dispatcher refuses to split


def test_run_question_hands_the_dispatcher_a_session_or_an_audience_but_never_both(ctx, monkeypatch):
    """The invariant `runner.py:159-167` states in a comment, as a test.

    A borrowed `QuerySession` already carries the audience it was proved for, so handing
    `retrieval_session` an `access` beside it would be a second, unproven opinion about who
    is asking. The dispatcher refuses that pair outright (`invalid_borrow`); the runner is
    what keeps the refusal from ever firing, by passing `access=None` whenever it borrows.

    The comment was half the review's fix and the code is correct, but nothing pinned it: a
    later edit that "restores" the dropped `access` would turn every borrowed question into
    a runtime `invalid_borrow` and only show up as an error field on a stored result. The
    second half below proves the pair is what the dispatcher actually objects to, so this
    test fails for the right reason rather than because a keyword was renamed.
    """
    from hippo.access import EVERYTHING
    from hippo.knowledge import dense_session
    from hippo.knowledge.dense_session import DenseSessionUnavailable
    from hippo.knowledge.query_access import query_session

    row = {"id": "x", "text": "Where is Acme?", "expected_answer": "", "gold_passage_ids": []}
    # The internal audience: `access` is not `None`, so the pair below is a real pair, and
    # `EvalAccess` does not re-read the row this test never saved.
    audience = EVERYTHING
    handed: list[tuple[object, object]] = []
    real = dense_session.retrieval_session

    def watched(ctx_, access=None, **kwargs):
        handed.append((access, kwargs.get("session")))
        return real(ctx_, access, **kwargs)

    monkeypatch.setattr(dense_session, "retrieval_session", watched)

    with query_session(ctx, audience) as borrowed:
        result = run_question(ctx, row, ctx.store.get_settings(), audience, session=borrowed)
    assert result["error"] is None, result["error"]
    # `run_question` enters the dispatcher once and the stages below it re-enter with the
    # session it routed, so only the first entry is the runner's own hand-over. Compared by
    # identity: a `QuerySession` holds numpy arrays, so `==` is not a question one can ask.
    assert handed, "the dispatcher was never reached"
    assert handed[0][0] is None and handed[0][1] is borrowed, "a borrow arrives without an audience"
    assert all(access is None for access, _ in handed), "no re-entry may add one either"

    # Acquiring its own owner is the other half of the same rule: an audience, no session.
    handed.clear()
    assert run_question(ctx, row, ctx.store.get_settings(), audience)["error"] is None
    assert handed and (handed[0][0] is audience and handed[0][1] is None)

    # And the pair the runner never forms is the pair the dispatcher refuses.
    with query_session(ctx, audience) as borrowed:
        with pytest.raises(DenseSessionUnavailable) as caught:
            with real(ctx, audience, session=borrowed):
                pass
    assert caught.value.reason == "invalid_borrow"
