"""
The judge: does the system's answer mean the same as the expected answer?

Exact match and F1 (metrics.py) punish harmless differences in wording
("Boulder, Colorado" vs "Boulder"). So we also ask the LLM for a verdict:

    correct            -> score 1.0
    partially_correct  -> score 0.5
    incorrect          -> score 0.0

The mean of these scores over a run is what the Evals page calls "accuracy".
If Ollama is down or the reply is garbage we do not guess: the verdict is
"incorrect" with a reason that says the judge failed, so a broken judge shows
up as a bad run rather than a silently good one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import prompts
from ..ollama import Ollama, OllamaError

SCORE_OF: dict[str, float] = {"correct": 1.0, "partially_correct": 0.5, "incorrect": 0.0}

JUDGE_MAX_TOKENS = 256  # a verdict word plus one sentence; more means the model is rambling


@dataclass
class Verdict:
    verdict: str  # 'correct' | 'partially_correct' | 'incorrect'
    score: float  # 1.0 | 0.5 | 0.0
    reason: str


def judge(ollama: Ollama, question: str, expected: str, actual: str) -> Verdict:
    """Ask the LLM to grade `actual` against `expected` for `question`."""
    try:
        reply = ollama.chat_json(
            prompts.judge_messages(question, expected, actual),
            prompts.JUDGE_SCHEMA,
            max_tokens=JUDGE_MAX_TOKENS,
        )
    except OllamaError as exc:
        return Verdict("incorrect", 0.0, f"the judge could not run: {exc}")
    return verdict_from_reply(reply)


def verdict_from_reply(reply: dict[str, Any]) -> Verdict:
    """Turn the judge's JSON into a Verdict, tolerating 'Partially Correct' style spellings."""
    label = str(reply.get("verdict", "")).strip().lower().replace(" ", "_").replace("-", "_")
    reason = str(reply.get("reason", "")).strip()
    if label not in SCORE_OF:
        return Verdict("incorrect", 0.0, f"the judge gave an unknown verdict {label!r}: {reason}")
    return Verdict(label, SCORE_OF[label], reason)
