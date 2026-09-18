"""
Step 5 of HippoRAG: read the top passages and answer.

The default reference `rag_qa` prompt asks the model to think out loud after
"Thought:" and finish with a short line after "Answer:". An explicit QA model
uses the grounded direct-answer profile instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import prompts
from ..ollama import Ollama, OllamaError

QA_MAX_TOKENS = 1024


CODE_GRAPH_TITLE = "Code graph"


@dataclass
class Answer:
    answer: str
    thought: str
    raw: str
    passage_ids: list[str]
    context_block: str = ""  # the Code graph pseudo-passage, when the question named code
    retrieval_passage_ids: list[str] = field(default_factory=list)


def answer_question(
    ollama: Ollama,
    question: str,
    passages: list[tuple[str, str, str]],
    context_block: str = "",
    *,
    qa_model: str | None = None,
) -> Answer:
    """
    `passages` is a list of (passage_id, title, text), with the ranked base first and any
    bounded supplemental code evidence after it.

    `context_block` is the typed relations behind a code question. It is prepended *here*, inside
    the prompt, rather than by the caller pushing a synthetic passage onto the list: the list is
    also what `Answer.passage_ids` is built from, so a fake id in it would end up cited as a source
    the reader cannot open (D19).
    """
    pairs = [(title, text) for _, title, text in passages]
    if context_block:
        pairs.insert(0, (CODE_GRAPH_TITLE, context_block))
    if qa_model is None:
        raw = ollama.chat_text(prompts.qa_messages(question, pairs), max_tokens=QA_MAX_TOKENS)
    else:
        raw = ollama.chat_text(
            prompts.grounded_qa_messages(question, pairs),
            model=qa_model,
            max_tokens=4096,
            temperature=0.0,
            top_p=0.95,
            top_k=20,
            min_p=0.0,
            seed=0,
            require_complete=True,
        )
    thought, answer = prompts.split_answer(raw)
    if qa_model is not None and not answer:
        raise OllamaError("Ollama returned an empty answer")
    return Answer(
        answer=answer,
        thought=thought,
        raw=raw,
        passage_ids=[pid for pid, _, _ in passages],
        context_block=context_block,
    )
