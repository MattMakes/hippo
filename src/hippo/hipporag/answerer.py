"""
Step 5 of HippoRAG: read the top passages and answer.

The reference's `rag_qa` prompt asks the model to think out loud after
"Thought:" and finish with a short line after "Answer:". We keep both parts.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import prompts
from ..ollama import Ollama

QA_MAX_TOKENS = 1024


@dataclass
class Answer:
    answer: str
    thought: str
    raw: str
    passage_ids: list[str]


def answer_question(ollama: Ollama, question: str, passages: list[tuple[str, str, str]]) -> Answer:
    """`passages` is a list of (passage_id, title, text), best first, already cut to qa_top_k."""
    raw = ollama.chat_text(
        prompts.qa_messages(question, [(title, text) for _, title, text in passages]),
        max_tokens=QA_MAX_TOKENS,
    )
    thought, answer = prompts.split_answer(raw)
    return Answer(answer=answer, thought=thought, raw=raw, passage_ids=[pid for pid, _, _ in passages])
