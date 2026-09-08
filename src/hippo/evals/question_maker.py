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

A source with a code graph gets two more kinds, and unlike the first two they
cost **no model call at all**: `code_questions` and `commit_questions` are pure
functions of the graph, so their questions and their expected answers are short
deterministic strings assembled from symbols, calls and commits (D17). That is
the point - an eval question about code must be reproducible run to run, and an
LLM asked to invent one would drift.

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
from ..access import Access
from ..context import AppContext
from ..hipporag.graph_index import COMMIT, ENTITY, SYMBOL, GraphIndex, Passage
from ..hipporag.paths import display_at, display_of
from ..ollama import OllamaError

log = logging.getLogger(__name__)

QuestionRow = dict[str, Any]
PassagePair = tuple[Passage, Passage]

MIN_SHARED = 2  # an entity must appear in at least two passages to make a link
PREFERRED_SHARED = 3  # 2-3 passages: a specific link; tried first
MAX_SHARED = 5  # more than this and the entity is too generic ("Colorado" in every passage)
GEN_MAX_TOKENS = 512

CALLABLE_KINDS = frozenset({"function", "method"})  # "what does a class call" is not a question
MIN_CALL_OMEGA = 0.5  # a guessed call is not something to grade retrieval against
MIN_DOC_CHARS = 80  # the same bar OpenIE uses for a docstring: enough to be worth asking about
MIN_COMMIT_SYMBOLS = 2  # one symbol is a rename, not a localization question


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
    max_code: int = 5,
    max_commits: int = 5,
    name: str | None = None,
    set_id: str | None = None,
    access: Access | None = None,
) -> str:
    """
    Fill a question set about `source_id` (creating it unless `set_id` is given). Returns the set id.
    `access` keeps the passages (and the entity pairs for multi-hop questions) inside the caller's slice.

    `max_code` and `max_commits` bound the two graph-built kinds; a source with no code graph
    simply produces none of them.
    """
    set_id = set_id or _create_set(ctx, source_id, name)
    store = ctx.store
    try:
        index = ctx.graph_for(access)
        passages = _passages_of(index, source_id)
        if not passages:
            raise ValueError("this source has no indexed passages yet; index it first")

        singles = _spread(passages, max_single)
        pairs = shared_entity_pairs(index, passages)
        # Built up front because they are pure: no model call, so they cannot fail halfway and they
        # only need counting into `total`. Without them a set of nothing but code questions would
        # report progress 0 of 0.
        graph_rows = code_questions(index, source_id, max_code)
        graph_rows += commit_questions(index, source_id, max_commits)
        # Every pair may cost up to two LLM calls (both orders), but we stop at max_multihop questions.
        total = len(singles) + min(max_multihop, len(pairs)) + len(graph_rows)
        store.update_question_set(
            set_id, stage="writing single-hop questions", progress_done=0, progress_total=total
        )

        rows = _single_hop_questions(ctx, set_id, singles, per_passage, total)
        store.add_questions(set_id, rows)

        store.update_question_set(set_id, stage="writing multi-hop questions", progress_done=len(singles))
        rows = _multihop_questions(ctx, set_id, pairs, max_multihop, done=len(singles), total=total)
        store.add_questions(set_id, rows)

        store.update_question_set(set_id, stage="writing code questions")
        store.add_questions(set_id, graph_rows)

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


# ---------------------------------------------------------- code and commits
# Both generators are pure functions of the loaded graph: no store, no model, no clock. Given the
# same index they write the same questions, the same expected answers and the same gold ids, which
# is what makes an eval run comparable to the one before it.


def code_questions(index: GraphIndex, source_id: str, limit: int = 5) -> list[QuestionRow]:
    """
    "What does <qualname> call?", for the functions worth asking about.

    A function qualifies when it has a doc of at least `MIN_DOC_CHARS` (so there is something to
    answer with) and at least one INVOKES out-edge at omega >= `MIN_CALL_OMEGA` (so the call is
    resolved, not guessed). The gold passages are the function's own and those of the **strongest**
    call it makes - highest omega, ties broken by display name - and `notes` lists every callee, so
    a person reading the set can see what the one gold call was chosen out of.

    The question names the fully-qualified display name on purpose: a dotted name is code-shaped,
    so `find_anchors` seeds from it and the run's `recall["code_seeded"]` reads 1.0. Written any
    other way the question would measure dense retrieval instead of the code graph.
    """
    candidates: list[tuple[str, QuestionRow]] = []
    for node in index.code_nodes:
        if node.kind != SYMBOL or node.source_id != source_id:
            continue
        if node.code_kind not in CALLABLE_KINDS or len(node.doc) < MIN_DOC_CHARS:
            continue
        vertex = index.idx_of[node.id]
        calls = [e for e in index.out_edges(vertex) if e.kind == "INVOKES" and e.omega >= MIN_CALL_OMEGA]
        gold = _defining_passage_ids(index, vertex)
        if not calls or not gold:
            continue
        best = min(calls, key=lambda e: (-e.omega, display_at(index, e.dst)))
        callee_gold = _defining_passage_ids(index, best.dst)
        if not callee_gold:
            continue  # a callee we cannot point at is not a gold passage
        caller, callee = display_of(node), display_at(index, best.dst)
        callees = ", ".join(sorted(display_at(index, e.dst) for e in calls))
        candidates.append(
            (
                caller,
                {
                    "text": f"What does {caller} call?",
                    "expected_answer": f"{caller} calls {callee}.",
                    "gold_passage_ids": _gold(gold, callee_gold),
                    "kind": "code",
                    "notes": (
                        f"INVOKES {callee} ({best.provenance}, omega {best.omega:.2f}); callees: {callees}"
                    ),
                },
            )
        )
    candidates.sort(key=lambda item: item[0])
    return [row for _display, row in candidates[: max(limit, 0)]]


def commit_questions(index: GraphIndex, source_id: str, limit: int = 5) -> list[QuestionRow]:
    """
    "What changed in the commit <subject>?", newest commit first.

    A commit qualifies when it MODIFIES at least `MIN_COMMIT_SYMBOLS` symbols: one symbol makes the
    answer a restatement of the subject line, two or more make it a localization question, which is
    the eval the user asked for (D8).

    **The gold order is a contract with `runner.run_question`:** the commit's own message passage
    first, then one entry per modified symbol in display-name order. `recall["path_fidelity"]`
    scores that tail alone - "of the functions this commit touched, how many did we retrieve" -
    which the plain `recall@k` cannot separate out from the message passage.
    """
    candidates: list[tuple[int, str, QuestionRow]] = []
    for node in index.code_nodes:
        if node.kind != COMMIT or node.source_id != source_id:
            continue
        vertex = index.idx_of[node.id]
        touched = sorted(
            {
                (display_at(index, e.dst), e.dst)
                for e in index.out_edges(vertex)
                if e.kind == "MODIFIES" and index.node_kind[e.dst] == SYMBOL
            }
        )
        # Only the first: the tail of `gold_passage_ids` must be symbols and nothing else, or
        # `path_fidelity` would silently score a message passage as a touched function.
        commit_gold = _defining_passage_ids(index, vertex)[:1]
        if len(touched) < MIN_COMMIT_SYMBOLS or not commit_gold:
            continue
        symbol_gold: list[str] = []
        for _name, symbol_vertex in touched:
            symbol_gold.extend(_defining_passage_ids(index, symbol_vertex))
        if not symbol_gold:
            continue
        subject = (node.message or "").splitlines()[0].strip() or display_of(node)
        names = ", ".join(name for name, _vertex in touched)
        candidates.append(
            (
                node.ordinal,
                node.sha,
                {
                    "text": f'What changed in the commit "{subject}"?',
                    "expected_answer": f'The commit "{subject}" changed {names}.',
                    "gold_passage_ids": _gold(commit_gold, symbol_gold),
                    "kind": "commit",
                    "notes": f"touched: {names}",
                },
            )
        )
    # `Commit.ordinal` is 0 for the newest, so ascending order is newest first; the sha only ever
    # breaks a tie, and never reaches a question (a sha is not reproducible across machines, S2.17).
    candidates.sort(key=lambda item: (item[0], item[1]))
    return [row for _ordinal, _sha, row in candidates[: max(limit, 0)]]


def _defining_passage_ids(index: GraphIndex, vertex: int) -> list[str]:
    """The passage ids a code node is written down in, in vertex order (so: passage ordinal order)."""
    return [index.node_ids[p] for p in sorted(index.defining_passages(vertex))]


def _gold(*groups: list[str]) -> list[str]:
    """Several nodes' passage ids as one gold list: order kept, each id once. Two symbols sharing a
    passage would otherwise store it twice and read as two hits to anyone counting the raw list."""
    out: list[str] = []
    for group in groups:
        for passage_id in group:
            if passage_id not in out:
                out.append(passage_id)
    return out


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
