"""The LLM judge: verdict -> score, and what happens when the model is unavailable."""

from __future__ import annotations

from hippo.evals.judge import Verdict, judge, verdict_from_reply
from hippo.ollama import Ollama
from tests.fakes.fake_ollama import FakeOllama


def test_correct_when_expected_answer_appears(ollama, fake_ollama):
    verdict = judge(ollama, "Where is Acme Robotics headquartered?", "Boulder", "It is in Boulder, Colorado.")
    assert verdict == Verdict("correct", 1.0, verdict.reason)
    assert verdict.reason
    # The judge prompt was the one from prompts.py, sent as one chat call.
    assert len(fake_ollama.calls) == 1
    assert fake_ollama.calls[0]["messages"][0]["content"].startswith("You grade answers")
    assert "Expected answer: Boulder" in fake_ollama.calls[0]["messages"][-1]["content"]


def test_partially_correct_scores_half(ollama):
    verdict = judge(ollama, "Who founded Acme?", "Priya Natarajan", "Someone called Priya")
    assert verdict.verdict == "partially_correct"
    assert verdict.score == 0.5


def test_incorrect_scores_zero(ollama):
    verdict = judge(ollama, "Who founded Acme?", "Priya Natarajan", "Marcus Lee")
    assert verdict.verdict == "incorrect"
    assert verdict.score == 0.0


def test_ollama_error_becomes_incorrect_with_a_reason():
    # No models installed -> Ollama answers 404 -> OllamaError inside chat_json.
    broken = Ollama(
        "http://fake-ollama", "qwen3:8b", "nomic-embed-text", client=FakeOllama(installed=[]).client()
    )
    verdict = judge(broken, "q", "expected", "actual")
    assert verdict.verdict == "incorrect"
    assert verdict.score == 0.0
    assert "judge could not run" in verdict.reason


def test_unknown_verdict_words_are_not_trusted():
    assert verdict_from_reply({"verdict": "Partially Correct", "reason": "half"}) == Verdict(
        "partially_correct", 0.5, "half"
    )
    odd = verdict_from_reply({"verdict": "maybe", "reason": "unsure"})
    assert odd.verdict == "incorrect"
    assert odd.score == 0.0
    assert "unknown verdict" in odd.reason
    assert verdict_from_reply({}).verdict == "incorrect"
