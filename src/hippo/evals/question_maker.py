"""
Making sample questions about one source, so you can test the memory without
writing questions by hand.

Two kinds come out:

* single-hop: the LLM reads one passage and writes a question that passage
  answers. We spread the chosen passages evenly across the source so the
  set is not all about the first page.
* multi-hop: we look in the graph for two passages of this source that
  MENTION the same entity (say "Boulder"), show both to the LLM and ask for a
  question that needs both ("Acme is headquartered in a city that lies in
  which state?"). Entities shared by exactly 2-3 passages make the most
  specific links, so we try those first; entities mentioned by more than
  5 passages are too generic and skipped.

Every question row stores its gold passage id(s), so a run can later check
whether retrieval found the right passage(s).

Progress (stage, done, total) is written on the QuestionSet node so the
Source page can show it while the job runs.
"""

from __future__ import annotations

import logging
from itertools import combinations
from typing import Any

from .. import prompts
from ..context import AppContext
from ..hipporag.graph_index import ENTITY, GraphIndex, Passage
from ..ollama import OllamaError

log = logging.getLogger(__name__)

QuestionRow = dict[str, Any]
PassagePair = tuple[Passage, Passage]

MIN_SHARED = 2  # an entity must appear in at least two passages to make a link
PREFERRED_SHARED = 3  # 2-3 passages: a specific link; tried first
MAX_SHARED = 5  # more than this and the entity is too generic ("Colorado" in every passage)
GEN_MAX_TOKENS = 512


# ------------------------------------------------------------------ entry points


def start_generation_job(ctx: AppContext, source_id: str, **kw: Any) -> str:
    """Create the QuestionSet now, fill it in the background. Returns the set id straight away."""
    set_id = _create_set(ctx, source_id, kw.pop("name", None))
    ctx.jobs.start(f"generate:{set_id}", lambda: generate_questions(ctx, source_id, set_id=set_id, **kw))
    return set_id


def generate_questions(
    ctx: AppContext,
    source_id: str,
    *,
    per_passage: int = 1,
    max_single: int = 10,
    max_multihop: int = 5,
    name: str | None = None,
    set_id: str | None = None,
) -> str:
    """Fill a question set about `source_id` (creating it unless `set_id` is given). Returns the set id."""
    set_id = set_id or _create_set(ctx, source_id, name)
    store = ctx.store
    try:
        index = ctx.graph()
        passages = _passages_of(index, source_id)
        if not passages:
            raise ValueError("this source has no indexed passages yet; index it first")

        singles = _spread(passages, max_single)
        pairs = shared_entity_pairs(index, passages)
        # Every pair may cost up to two LLM calls (both orders), but we stop at max_multihop questions.
        total = len(singles) + min(max_multihop, len(pairs))
        store.update_question_set(
            set_id, stage="writing single-hop questions", progress_done=0, progress_total=total
        )

        rows = _single_hop_questions(ctx, set_id, singles, per_passage, total)
        store.add_questions(set_id, rows)

        store.update_question_set(set_id, stage="writing multi-hop questions", progress_done=len(singles))
        rows = _multihop_questions(ctx, set_id, pairs, max_multihop, done=len(singles), total=total)
        store.add_questions(set_id, rows)

        store.update_question_set(
            set_id, status="ready", stage="done", progress_done=total, progress_total=total
        )
    except Exception as exc:
        log.exception("Question generation for source %s failed", source_id)
        store.update_question_set(set_id, status="failed", stage="failed", error=str(exc))
        raise
    return set_id


# ---------------------------------------------------------------- single-hop


def _single_hop_questions(
    ctx: AppContext, set_id: str, passages: list[Passage], per_passage: int, total: int
) -> list[QuestionRow]:
    rows: list[QuestionRow] = []
    for done, passage in enumerate(passages, start=1):
        try:
            reply = ctx.ollama.chat_json(
                prompts.question_gen_messages(passage.title, passage.text, per_passage),
                prompts.QUESTION_GEN_SCHEMA,
                max_tokens=GEN_MAX_TOKENS,
            )
        except OllamaError as exc:
            # One bad passage should not stop the whole set; the log keeps the reason.
            log.warning("Question generation skipped passage %s: %s", passage.id, exc)
            reply = {}
        for item in reply.get("questions", [])[:per_passage]:
            question, answer = str(item.get("question", "")).strip(), str(item.get("answer", "")).strip()
            if question and answer:
                rows.append(
                    {
                        "text": question,
                        "expected_answer": answer,
                        "gold_passage_ids": [passage.id],
                        "kind": "single",
                        "notes": f"from passage '{passage.title}'",
                    }
                )
        ctx.store.update_question_set(set_id, progress_done=done, progress_total=total)
    return rows


def _spread(passages: list[Passage], how_many: int) -> list[Passage]:
    """Up to `how_many` passages spread evenly over the source (first, last and evenly in between)."""
    if how_many <= 0 or not passages:
        return []
    if len(passages) <= how_many:
        return list(passages)
    step = len(passages) / how_many
    chosen = {passages[int(i * step)].id: passages[int(i * step)] for i in range(how_many)}
    return list(chosen.values())  # keyed by id: keeps order, drops any accidental repeat


# ----------------------------------------------------------------- multi-hop


def _multihop_questions(
    ctx: AppContext,
    set_id: str,
    pairs: list[tuple[str, Passage, Passage]],
    limit: int,
    *,
    done: int,
    total: int,
) -> list[QuestionRow]:
    rows: list[QuestionRow] = []
    seen_texts: set[str] = set()
    for entity_name, first, second in pairs:
        if len(rows) >= limit:
            break
        # The chain can run either way (A tells us about the entity, B continues from it), so
        # give the model both orders before giving up on this pair.
        for a, b in ((first, second), (second, first)):
            row = _ask_multihop(ctx, entity_name, a, b)
            if row and row["text"] not in seen_texts:
                seen_texts.add(row["text"])
                rows.append(row)
                break
        done += 1
        ctx.store.update_question_set(set_id, progress_done=min(done, total), progress_total=total)
    return rows


def _ask_multihop(ctx: AppContext, entity_name: str, a: Passage, b: Passage) -> QuestionRow | None:
    try:
        reply = ctx.ollama.chat_json(
            prompts.multihop_gen_messages(entity_name, (a.title, a.text), (b.title, b.text)),
            prompts.MULTIHOP_GEN_SCHEMA,
            max_tokens=GEN_MAX_TOKENS,
        )
    except OllamaError as exc:
        log.warning("Multi-hop generation skipped passages %s + %s: %s", a.id, b.id, exc)
        return None
    question, answer = str(reply.get("question", "")).strip(), str(reply.get("answer", "")).strip()
    if not question or not answer:
        return None  # the model found no sensible two-passage question; fine
    reasoning = str(reply.get("reasoning", "")).strip()
    return {
        "text": question,
        "expected_answer": answer,
        "gold_passage_ids": [a.id, b.id],
        "kind": "multihop",
        "notes": f"shared entity '{entity_name}'. {reasoning}".strip(),
    }


def shared_entity_pairs(index: GraphIndex, passages: list[Passage]) -> list[tuple[str, Passage, Passage]]:
    """
    (entity name, passage A, passage B) for every pair of passages that MENTION the same entity,
    best links first: entities shared by 2-3 passages, then 4-5. More than 5 is skipped.
    """
    mentioned_by = _mentions_by_entity(index, passages)
    candidates: list[tuple[str, Passage, Passage]] = []
    seen_pairs: set[frozenset[str]] = set()
    ordered = sorted(mentioned_by.items(), key=lambda item: (len(item[1]) > PREFERRED_SHARED, len(item[1])))
    for vertex, mentioning in ordered:
        if not MIN_SHARED <= len(mentioning) <= MAX_SHARED:
            continue
        for a, b in combinations(mentioning, 2):
            key = frozenset((a.id, b.id))
            if key in seen_pairs:
                continue  # the same two passages via another shared entity: one question is enough
            seen_pairs.add(key)
            candidates.append((index.name_of(vertex), a, b))
    return candidates


def _mentions_by_entity(index: GraphIndex, passages: list[Passage]) -> dict[int, list[Passage]]:
    """entity vertex -> the passages (of this source, in order) whose MENTIONS edge points at it."""
    mentioned_by: dict[int, list[Passage]] = {}
    for passage in passages:
        vertex = index.idx_of.get(passage.id)
        if vertex is None:
            continue
        for neighbour, _weight in index.neighbors(vertex):
            if index.node_kind[neighbour] != ENTITY:
                continue
            edge = index.edge_between(vertex, neighbour)
            if edge is not None and edge.mention:
                mentioned_by.setdefault(neighbour, []).append(passage)
    return mentioned_by


# ------------------------------------------------------------------- helpers


def _passages_of(index: GraphIndex, source_id: str) -> list[Passage]:
    return sorted((p for p in index.passages if p.source_id == source_id), key=lambda p: p.ordinal)


def _create_set(ctx: AppContext, source_id: str, name: str | None) -> str:
    source = ctx.store.get_source(source_id)
    if source is None:
        raise ValueError(f"unknown source {source_id}")
    set_id = ctx.store.create_question_set(
        name or f"Sample questions: {source['name']}", source_id, "generated"
    )
    ctx.store.update_question_set(set_id, status="generating", stage="starting")
    return set_id
