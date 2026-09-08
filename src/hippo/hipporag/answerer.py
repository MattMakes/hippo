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


CODE_GRAPH_TITLE = "Code graph"


@dataclass
class Answer:
    answer: str
    thought: str
    raw: str
    passage_ids: list[str]
    context_block: str = ""  # the Code graph pseudo-passage, when the question named code


def answer_question(
    ollama: Ollama, question: str, passages: list[tuple[str, str, str]], context_block: str = ""
) -> Answer:
    """
    `passages` is a list of (passage_id, title, text), best first, already cut to qa_top_k.

    `context_block` is the typed relations behind a code question. It is prepended *here*, inside
    the prompt, rather than by the caller pushing a synthetic passage onto the list: the list is
    also what `Answer.passage_ids` is built from, so a fake id in it would end up cited as a source
    the reader cannot open (D19).
    """
    pairs = [(title, text) for _, title, text in passages]
    if context_block:
        pairs.insert(0, (CODE_GRAPH_TITLE, context_block))
    raw = ollama.chat_text(prompts.qa_messages(question, pairs), max_tokens=QA_MAX_TOKENS)
    thought, answer = prompts.split_answer(raw)
    return Answer(
        answer=answer,
        thought=thought,
        raw=raw,
        passage_ids=[pid for pid, _, _ in passages],
        context_block=context_block,
    )
