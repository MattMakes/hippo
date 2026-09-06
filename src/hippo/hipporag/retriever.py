"""
Step 4 of HippoRAG: turning a question into ranked passages.

The reference calls this `HippoRAG.retrieve()`. In plain words:

1. **Find candidate facts.** Embed the question and compare it with every
   fact's embedding. Keep the `linking_top_k` (5) most similar facts.
2. **Recognition memory.** Show those facts to the LLM and ask which ones
   really matter for the question. (Embeddings are fuzzy; the LLM is picky.)
3. **Seed the graph.** The entities in the surviving facts become seed nodes.
   Each gets the fact's similarity score as weight, divided by how many
   passages mention that entity ("node specificity": a name that appears
   everywhere is a weak clue). The passages themselves also get a tiny seed
   weight from their own similarity to the question (`passage_node_weight`).
4. **Spread activation.** Run Personalized PageRank from those seeds.
5. **Rank passages** by their PageRank score.

If the LLM keeps no facts at all, we fall back to plain embedding search
("dense passage retrieval"), exactly like the reference.

Every step is recorded in a `Trace`, which is what the Analyze page shows
and what simulations replay.
"""

from __future__ import annotations

import difflib
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import igraph as ig
import numpy as np

from .. import prompts
from ..ollama import Ollama, OllamaError
from .graph_index import ENTITY, PASSAGE, GraphIndex
from .text import min_max_normalize

log = logging.getLogger(__name__)

TRACE_CANDIDATES = 20  # the trace records at least this many top facts (more when linking_top_k is larger)
TRACE_TOP_NODES = 40  # how many top PPR nodes we record
TRACE_SEED_PASSAGES = 10  # how many of the strongest embedding-similarity passages we record as seed passages

# A fact filter takes (question, candidate triples) and returns (kept triples in order, raw model text).
FactFilter = Callable[[str, list[list[str]]], tuple[list[list[str]], str]]


@dataclass
class FactCandidate:
    fact_id: str
    triple: list[str]
    score: float  # similarity to the question, min-max normalised over all facts
    rank: int  # 1 = most similar
    sent_to_filter: bool  # only the top linking_top_k are shown to the LLM
    kept: bool  # survived the filter (or was forced in)
    reason: str  # "kept by filter" | "dropped by filter" | "not sent to filter" | "forced in" | "forced out"
    passage_ids: list[str]


@dataclass
class SeedEntity:
    entity_id: str
    name: str
    vertex: int
    weight: float  # what PPR starts with (after specificity, averaging, boost, and top-k cut)
    fact_score_sum: float  # the fact scores that pointed at this entity, before dividing
    occurrences: int  # how many kept facts mention this entity
    passage_count: int  # how many passages mention it (node specificity divides by this)
    boost: float
    from_fact_ids: list[str]
    kept: bool  # False if it fell outside the top linking_top_k entities


@dataclass
class SeedPassage:
    passage_id: str
    title: str
    vertex: int
    dpr_score: float  # similarity to the question, min-max normalised
    weight: float  # dpr_score * passage_node_weight


@dataclass
class RankedPassage:
    passage_id: str
    rank: int
    score: float  # PPR score (or DPR score in fallback mode)
    dpr_rank: int
    dpr_score: float
    title: str
    source_id: str
    source_name: str
    preview: str


@dataclass
class TopNode:
    node_id: str
    kind: str
    name: str
    vertex: int
    score: float
    is_seed: bool


@dataclass
class Trace:
    question: str
    settings: dict[str, Any]
    graph_version: int
    used_dpr_fallback: bool = False
    fallback_reason: str = ""
    fact_candidates: list[FactCandidate] = field(default_factory=list)
    filter: dict[str, Any] = field(
        default_factory=dict
    )  # {"raw_response", "kept_triples", "error", "replayed"}
    seed_entities: list[SeedEntity] = field(default_factory=list)
    seed_passages: list[SeedPassage] = field(default_factory=list)
    top_nodes: list[TopNode] = field(default_factory=list)
    passages: list[RankedPassage] = field(default_factory=list)
    timing_ms: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def kept_fact_ids(self) -> list[str]:
        return [c.fact_id for c in self.fact_candidates if c.kept]

    def passage_ids(self) -> list[str]:
        return [p.passage_id for p in self.passages]


class Retriever:
    def __init__(self, index: GraphIndex, ollama: Ollama):
        self.index = index
        self.ollama = ollama

    # ----------------------------------------------------------- the LLM filter

    def llm_fact_filter(self, question: str, candidates: list[list[str]]) -> tuple[list[list[str]], str]:
        """Ask the LLM which candidate facts matter (the reference's DSPy "recognition memory" filter)."""
        if not candidates:
            return [], ""
        try:
            reply = self.ollama.chat_json(
                prompts.fact_filter_messages(question, candidates), prompts.FACT_FILTER_SCHEMA, max_tokens=512
            )
        except OllamaError as exc:
            log.warning("Fact filter failed, keeping no facts: %s", exc)
            return [], f"error: {exc}"
        kept = [list(t) for t in reply.get("fact", []) if isinstance(t, list | tuple) and len(t) == 3]
        return kept, str(reply)

    # ------------------------------------------------------------- retrieve

    def retrieve(
        self,
        question: str,
        settings: dict[str, Any],
        *,
        fact_filter: FactFilter | None = None,
        force_include: set[str] | frozenset[str] = frozenset(),
        force_exclude: set[str] | frozenset[str] = frozenset(),
        node_boosts: dict[str, float] | None = None,
        graph: ig.Graph | None = None,
        question_embedding: np.ndarray | None = None,
    ) -> Trace:
        """
        Rank passages for `question`. The keyword arguments exist for simulations:
        replay a recorded filter, force facts in/out, boost entities, or use an edited graph.
        """
        started = time.time()
        index = self.index
        timing: dict[str, float] = {}
        trace = Trace(question=question, settings=dict(settings), graph_version=index.version)
        if index.is_empty():
            trace.used_dpr_fallback = True
            trace.fallback_reason = "the memory is empty"
            return trace

        link_top_k = int(settings.get("linking_top_k", 5))
        damping = float(settings.get("damping", 0.5))
        passage_node_weight = float(settings.get("passage_node_weight", 0.05))
        node_specificity = bool(settings.get("node_specificity", True))
        retrieval_top_k = int(settings.get("retrieval_top_k", 200))
        if not 0.0 <= damping <= 1.0:
            raise ValueError(f"damping must be between 0 and 1, got {damping}")

        # 1. Embed the question once; score every fact and every passage against it.
        t = time.time()
        q = (
            question_embedding
            if question_embedding is not None
            else self.ollama.embed_one(question, kind="query")
        )
        timing["embed"] = (time.time() - t) * 1000
        dpr_scores = min_max_normalize(index.passage_embeddings @ q) if len(index.passages) else np.zeros(0)
        dpr_order = np.argsort(-dpr_scores, kind="stable")
        dpr_rank_of = {int(p): r + 1 for r, p in enumerate(dpr_order)}

        fact_scores = min_max_normalize(index.fact_embeddings @ q) if len(index.facts) else np.zeros(0)
        full_order = np.argsort(-fact_scores, kind="stable")
        # Exactly linking_top_k facts go to the filter, like the reference's `rerank_facts`. The trace
        # keeps a few more (at least TRACE_CANDIDATES) so the Analyze page can show the near misses,
        # and always every fact that was sent.
        sent = [int(i) for i in full_order[:link_top_k]] if link_top_k > 0 else []
        fact_order = full_order[: max(TRACE_CANDIDATES, link_top_k)]

        # 2. Recognition memory: the LLM (or a replay) picks the facts that matter.
        t = time.time()
        candidate_triples = [index.facts[i].triple for i in sent]
        filter_fn = fact_filter or self.llm_fact_filter
        kept_triples, raw = filter_fn(question, candidate_triples) if sent else ([], "")
        kept_positions = match_triples(kept_triples, candidate_triples)[:link_top_k]
        kept_fact_indices = [sent[pos] for pos in kept_positions]
        timing["filter"] = (time.time() - t) * 1000
        trace.filter = {
            "raw_response": raw,
            "kept_triples": kept_triples,
            "replayed": fact_filter is not None,
        }

        # Simulation knobs: force facts in or out.
        forced_in = [index.fact_index_of[fid] for fid in force_include if fid in index.fact_index_of]
        for i in forced_in:
            if i not in kept_fact_indices:
                kept_fact_indices.append(i)
        kept_fact_indices = [i for i in kept_fact_indices if index.facts[i].id not in force_exclude]

        shown = list(dict.fromkeys([int(i) for i in fact_order] + forced_in))
        for rank, i in enumerate(shown, start=1):
            fact = index.facts[i]
            was_sent = i in sent
            kept = i in kept_fact_indices
            if fact.id in force_exclude:
                reason = "forced out"
            elif i in forced_in and i not in [sent[p] for p in kept_positions]:
                reason = "forced in"
            elif not was_sent:
                reason = "not sent to filter"
            else:
                reason = "kept by filter" if kept else "dropped by filter"
            trace.fact_candidates.append(
                FactCandidate(
                    fact.id,
                    fact.triple,
                    float(fact_scores[i]),
                    rank,
                    was_sent,
                    kept,
                    reason,
                    list(fact.passage_ids),
                )
            )

        # No facts? Plain embedding search, like the reference.
        if not kept_fact_indices:
            trace.used_dpr_fallback = True
            trace.fallback_reason = (
                "no facts survived the filter"
                if sent
                else "no facts to link (empty graph or linking_top_k = 0)"
            )
            trace.passages = self._ranked(dpr_scores, dpr_scores, dpr_order, dpr_rank_of, retrieval_top_k)
            trace.top_nodes = []
            timing["total"] = (time.time() - started) * 1000
            trace.timing_ms = timing
            return trace

        # 3. Seed weights for entities (node specificity + averaging, as in the reference).
        n = index.num_nodes
        weight_sum = np.zeros(n)
        occurs = np.zeros(n)
        from_facts: dict[int, list[str]] = {}
        for i in kept_fact_indices:
            fact = index.facts[i]
            for entity_id in (fact.subject_id, fact.object_id):
                v = index.idx_of.get(entity_id)
                if v is None:
                    continue
                w = float(fact_scores[i])
                if node_specificity and index.entity_passage_count[v] > 0:
                    w /= index.entity_passage_count[v]
                weight_sum[v] += w
                occurs[v] += 1
                from_facts.setdefault(v, []).append(fact.id)
        phrase_weights = np.divide(weight_sum, occurs, out=np.zeros(n), where=occurs != 0)

        boosts = index.entity_boost.copy()
        for entity_id, boost in (node_boosts or {}).items():
            v = index.idx_of.get(entity_id)
            if v is not None:
                boosts[v] = float(boost)
        phrase_weights *= boosts

        seeded = [v for v in np.flatnonzero(occurs > 0)]
        top_entities = sorted(seeded, key=lambda v: -phrase_weights[v])[:link_top_k] if link_top_k else seeded
        top_set = set(top_entities)
        for v in seeded:
            trace.seed_entities.append(
                SeedEntity(
                    entity_id=index.node_ids[v],
                    name=index.name_of(v),
                    vertex=int(v),
                    weight=float(phrase_weights[v]) if v in top_set else 0.0,
                    fact_score_sum=float(weight_sum[v]),
                    occurrences=int(occurs[v]),
                    passage_count=int(index.entity_passage_count[v]),
                    boost=float(boosts[v]),
                    from_fact_ids=from_facts.get(v, []),
                    kept=v in top_set,
                )
            )
        trace.seed_entities.sort(key=lambda s: (-s.weight, -s.fact_score_sum))
        for v in seeded:
            if v not in top_set:
                phrase_weights[v] = 0.0

        # Passages seed PPR too, lightly, by their own similarity to the question.
        passage_weights = np.zeros(n)
        passage_weights[index.passage_vertices] = dpr_scores * passage_node_weight
        for pos in dpr_order[:TRACE_SEED_PASSAGES]:
            p = index.passages[int(pos)]
            trace.seed_passages.append(
                SeedPassage(
                    p.id,
                    p.title,
                    int(index.passage_vertices[pos]),
                    float(dpr_scores[pos]),
                    float(dpr_scores[pos] * passage_node_weight),
                )
            )

        reset = phrase_weights + passage_weights
        if reset.sum() <= 0:  # only possible when every seed was boosted to zero
            trace.used_dpr_fallback = True
            trace.fallback_reason = "every seed weight is zero"
            trace.passages = self._ranked(dpr_scores, dpr_scores, dpr_order, dpr_rank_of, retrieval_top_k)
            trace.top_nodes = []
            timing["total"] = (time.time() - started) * 1000
            trace.timing_ms = timing
            return trace

        # 4. Spread activation.
        t = time.time()
        ppr_scores = index.ppr(reset, damping, graph=graph)
        timing["ppr"] = (time.time() - t) * 1000

        # 5. Rank passages; remember the most activated nodes of either kind for the Analyze page.
        passage_ppr = ppr_scores[index.passage_vertices]
        ppr_order = np.argsort(-passage_ppr, kind="stable")
        trace.passages = self._ranked(passage_ppr, dpr_scores, ppr_order, dpr_rank_of, retrieval_top_k)
        seed_vertices = top_set | {int(v) for v in index.passage_vertices[dpr_order[:TRACE_SEED_PASSAGES]]}
        for v in np.argsort(-ppr_scores, kind="stable")[:TRACE_TOP_NODES]:
            v = int(v)
            trace.top_nodes.append(
                TopNode(
                    index.node_ids[v],
                    index.node_kind[v],
                    index.name_of(v),
                    v,
                    float(ppr_scores[v]),
                    v in seed_vertices,
                )
            )
        timing["total"] = (time.time() - started) * 1000
        trace.timing_ms = timing
        return trace

    def _ranked(self, scores, dpr_scores, order, dpr_rank_of, top_k) -> list[RankedPassage]:
        out = []
        for rank, pos in enumerate(order[:top_k], start=1):
            pos = int(pos)
            p = self.index.passages[pos]
            out.append(
                RankedPassage(
                    passage_id=p.id,
                    rank=rank,
                    score=float(scores[pos]),
                    dpr_rank=dpr_rank_of.get(pos, 0),
                    dpr_score=float(dpr_scores[pos]),
                    title=p.title,
                    source_id=p.source_id,
                    source_name=p.source_name,
                    preview=p.text[:240],
                )
            )
        return out


def match_triples(kept: list[list[str]], candidates: list[list[str]]) -> list[int]:
    """
    Map the triples the LLM returned back to candidate positions (in the LLM's order, no repeats).
    Exact matches first; otherwise the closest candidate by string similarity, as the reference does.
    """
    positions: list[int] = []
    candidate_strings = [str(c) for c in candidates]
    for triple in kept:
        if triple in candidates:
            pos = candidates.index(triple)
        else:
            closest = difflib.get_close_matches(str(triple), candidate_strings, n=1, cutoff=0.0)
            if not closest:
                continue
            pos = candidate_strings.index(closest[0])
        if pos not in positions:
            positions.append(pos)
    return positions


__all__ = [
    "Retriever",
    "Trace",
    "trace_from_dict",
    "FactCandidate",
    "SeedEntity",
    "SeedPassage",
    "RankedPassage",
    "TopNode",
    "ENTITY",
    "PASSAGE",
]


def trace_from_dict(data: dict[str, Any]) -> Trace:
    """Rebuild a Trace from the JSON we stored with an evaluation result."""
    trace = Trace(
        question=data.get("question", ""),
        settings=dict(data.get("settings", {})),
        graph_version=int(data.get("graph_version", 0)),
        used_dpr_fallback=bool(data.get("used_dpr_fallback", False)),
        fallback_reason=data.get("fallback_reason", ""),
        filter=dict(data.get("filter", {})),
        timing_ms=dict(data.get("timing_ms", {})),
    )
    trace.fact_candidates = [FactCandidate(**c) for c in data.get("fact_candidates", [])]
    trace.seed_entities = [SeedEntity(**s) for s in data.get("seed_entities", [])]
    trace.seed_passages = [SeedPassage(**s) for s in data.get("seed_passages", [])]
    trace.top_nodes = [TopNode(**n) for n in data.get("top_nodes", [])]
    trace.passages = [RankedPassage(**p) for p in data.get("passages", [])]
    return trace
