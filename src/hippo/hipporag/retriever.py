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

**One addition the reference has no counterpart for: code.** When the question
*names* something in the code graph - an identifier, a stack frame, a pasted
snippet, a diff - those symbols seed PPR too, between step 2 and the fallback
decision, so a bare traceback still retrieves even though no fact survived the
filter. Symbol seeds have their own budget rather than competing for
`linking_top_k`'s entity slots, and only a *lexical* anchor counts as "the
question named code": that flag (`Trace.used_code_seeds`) is the single gate on
everything else code adds - the optional keep/drop/expand pass, the path block
the answerer reads, and the `paths` timing key. On a memory with no code
indexed, and on a prose question over one that has, none of it runs.

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
from . import paths
from .anchors import find_anchors, split_question
from .graph_index import DATA, ENTITY, PASSAGE, SYMBOL, GraphIndex
from .text import min_max_normalize

log = logging.getLogger(__name__)

TRACE_CANDIDATES = 20  # the trace records at least this many top facts (more when linking_top_k is larger)
TRACE_TOP_NODES = 40  # how many top PPR nodes we record
TRACE_SEED_PASSAGES = 10  # how many of the strongest embedding-similarity passages we record as seed passages

# Symbol seeds get their own budget instead of competing for `linking_top_k`'s entity slots: that cut
# (`retriever.py`'s `top_entities`) iterates the entities a *fact* pointed at, which anchors are not
# in, so sharing it would let an anchor evict a fact seed on every question that has both (D18).
MAX_CODE_SEEDS = 20
HISTORY_LIMIT = 3  # commits per answer block
DENSE = "dense"  # SeedSymbol.how for a seed that came from a passage's similarity, not from a word

# A fact filter takes (question, candidate triples) and returns (kept triples in order, raw model text).
FactFilter = Callable[[str, list[list[str]]], tuple[list[list[str]], str]]
# A select pass takes (question, the passages about to be read) and says what to keep, drop or
# expand. It is injected, so a unit test hands in a plain function and no model is involved.
SelectFn = Callable[[str, list["RankedPassage"]], "SelectResult"]


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
class SeedSymbol:
    """
    A symbol or data object the question reached, and how.

    `how` is `identifier`, `stack_trace`, `exception`, `fenced_code`, `diff` - the five *lexical*
    anchors - or `dense`, meaning the seed came from a code passage that scored highly against the
    question rather than from anything the question said. Only a lexical anchor flips
    `Trace.used_code_seeds`; a dense seed adds reset mass and nothing else (Ruling 1a).

    An `ambiguous` row is a token that matched more symbols than it is worth seeding (S2.13). It has
    no node and no weight, and exists so the trace can say why a name the user typed did nothing.
    """

    node_id: str = ""
    name: str = ""
    vertex: int = -1
    weight: float = 0.0
    how: str = ""
    token: str = ""
    kind: str = ""  # "symbol" or "data"
    n_matches: int = 1  # the pre-cap count of everything the token matched
    matched_by: str = ""  # the token, or the passage id a dense seed came from
    ambiguous: bool = False
    specificity: float = 0.0  # what the weight was divided by (in-degree + 1)
    boost: float = 1.0
    kept: bool = False  # False when it fell outside MAX_CODE_SEEDS or weighed nothing


@dataclass
class SelectResult:
    """What the optional keep/drop/expand pass decided (S2.14). Every field is optional."""

    keep: list[str] = field(default_factory=list)
    drop: list[str] = field(default_factory=list)
    expand: list[str] = field(default_factory=list)
    raw: str = ""


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
    community_boosted: bool = False  # code_community_boost lifted this one
    via_expand: bool = False  # fetched by the select pass's "expand", never part of the qa_top_k slice


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
    # The code graph. Every one of these has a default and none may ever be removed: evals store
    # traces permanently and `trace_from_dict` rebuilds each row with `Cls(**row)` (R3 gotcha 8).
    seed_symbols: list[SeedSymbol] = field(default_factory=list)
    used_code_seeds: bool = False  # a *lexical* anchor was kept: the gate for select, paths and the block
    question_prose: str = ""  # what was embedded and shown to the fact filter (S2.12)
    question_code: str = ""  # the pasted half: frames, fenced blocks, diff hunks
    paths: list[dict[str, Any]] = field(default_factory=list)  # rendered triples, one dict per relation
    tests: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    select: dict[str, Any] = field(default_factory=dict)  # {"keep", "drop", "expand", "raw", "error"}
    expansions: list[dict[str, Any]] = field(default_factory=list)
    evidence_fingerprint: str = ""  # exact authorized input view; empty on older saved traces

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

    def llm_select(self, question: str, ranked: list[RankedPassage]) -> SelectResult:
        """
        Show the top passages to the LLM and let it keep, drop or expand them (S2.14, D10).

        This is the *default* the entry points install, not something `retrieve()` reaches for on
        its own: a caller that passes no `select_fn` never makes this call, which is what keeps a
        unit test (and a replayed simulation) free of the model. Anything that goes wrong here -
        a transport error, unparsable output - reaches `_select`, which keeps every passage.
        """
        if not ranked:
            return SelectResult()
        reply = self.ollama.chat_json(
            prompts.code_select_messages(question, [(p.passage_id, p.title, p.preview) for p in ranked]),
            prompts.CODE_SELECT_SCHEMA,
            max_tokens=512,
        )
        pick = lambda key: [str(x) for x in reply.get(key, []) if isinstance(x, str)]  # noqa: E731
        return SelectResult(keep=pick("keep"), drop=pick("drop"), expand=pick("expand"), raw=str(reply))

    # ------------------------------------------------------------- retrieve

    def retrieve(
        self,
        question: str,
        settings: dict[str, Any],
        *,
        fact_filter: FactFilter | None = None,
        select_fn: SelectFn | None = None,
        force_include: set[str] | frozenset[str] = frozenset(),
        force_exclude: set[str] | frozenset[str] = frozenset(),
        node_boosts: dict[str, float] | None = None,
        graph: ig.Graph | None = None,
        question_embedding: np.ndarray | None = None,
    ) -> Trace:
        """
        Rank passages for `question`. The keyword arguments exist for simulations:
        replay a recorded filter or select pass, force facts in/out, boost entities, or use an
        edited graph. `select_fn` is injected rather than hard-wired, so a test (or a replay) can
        hand in a plain function and the second LLM pass never happens.
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
        code_theta = float(settings.get("code_theta", 0.5))
        code_community_boost = float(settings.get("code_community_boost", 0.0))
        if not 0.0 <= damping <= 1.0:
            raise ValueError(f"damping must be between 0 and 1, got {damping}")

        # 1. Split the question, then embed the prose half once and score every fact and passage.
        # A pure-prose question splits to `(text, "")`, so this is the unchanged path (S2.12); it is
        # a pasted traceback that would otherwise swallow the one sentence saying what is asked.
        trace.question_prose, trace.question_code = split_question(question)
        asked = trace.question_prose or question
        t = time.time()
        q = (
            question_embedding
            if question_embedding is not None
            else self.ollama.embed_one(asked, kind="query")
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
        kept_triples, raw = filter_fn(asked, candidate_triples) if sent else ([], "")
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

        # 3. The code graph seeds too, before the fallback decision is taken: a pasted stack trace
        # keeps no facts at all, and B's placement (after the seed computation) sits behind the
        # `return` below, so its own headline case would never reach it (R3.1-A/B, D18).
        n = index.num_nodes
        boosts = index.entity_boost.copy()
        for node_id, boost in (node_boosts or {}).items():
            v = index.idx_of.get(node_id)
            if v is not None:
                boosts[v] = float(boost)
        code_weights = self._code_seeds(
            trace, question, dpr_scores, dpr_order, boosts, settings, node_specificity=node_specificity
        )

        # No facts and nothing the question *named*? Plain embedding search, like the reference.
        # Dense code seeds deliberately do not count here: they exist on any memory containing code
        # whatever was asked, so letting them disable the fallback would change every prose question
        # on a mixed corpus (Ruling 1a).
        if not kept_fact_indices and not trace.used_code_seeds:
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

        # 4. Seed weights for entities (node specificity + averaging, as in the reference).
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

        reset = phrase_weights + code_weights + passage_weights
        if reset.sum() <= 0:  # only possible when every seed was boosted to zero
            trace.used_dpr_fallback = True
            trace.fallback_reason = "every seed weight is zero"
            trace.passages = self._ranked(dpr_scores, dpr_scores, dpr_order, dpr_rank_of, retrieval_top_k)
            trace.top_nodes = []
            timing["total"] = (time.time() - started) * 1000
            trace.timing_ms = timing
            return trace

        # 5. Spread activation.
        t = time.time()
        if graph is None:
            # `Edge.weight` is a property with no access to settings and `build_igraph` runs once
            # inside `load()`, so another `code_structural_scale` is a real rebuild, memoised per
            # scale on the index. A simulation that also edits an edge passes its own graph, which
            # already composes the scale in (`graph_with_edits(edits, scale)`).
            graph = index.graph_for_scale(float(settings.get("code_structural_scale", 1.0)))
        ppr_scores = index.ppr(reset, damping, graph=graph)
        timing["ppr"] = (time.time() - t) * 1000

        # 6. Rank passages; remember the most activated nodes of any kind for the Analyze page.
        passage_ppr = ppr_scores[index.passage_vertices]
        boosted = self._community_boost(trace, passage_ppr, code_community_boost)
        ppr_order = np.argsort(-passage_ppr, kind="stable")
        trace.passages = self._ranked(
            passage_ppr, dpr_scores, ppr_order, dpr_rank_of, retrieval_top_k, boosted=boosted
        )
        seed_vertices = top_set | {int(v) for v in index.passage_vertices[dpr_order[:TRACE_SEED_PASSAGES]]}
        seed_vertices |= {s.vertex for s in trace.seed_symbols if s.kept and s.vertex >= 0}
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

        # 7. The two things that only happen when the question named code (R3 gotchas 1 and 2 keep
        # the prose fixture's pinned assertions green: neither key is written otherwise).
        if trace.used_code_seeds:
            if select_fn is not None and bool(settings.get("code_select", True)):
                self._select(trace, select_fn, asked, settings)
            t = time.time()
            self._explain_code(trace, theta=code_theta)
            timing["paths"] = (time.time() - t) * 1000

        timing["total"] = (time.time() - started) * 1000
        trace.timing_ms = timing
        return trace

    # ------------------------------------------------------------ code seeds

    def _code_seeds(
        self,
        trace: Trace,
        question: str,
        dpr_scores: np.ndarray,
        dpr_order: np.ndarray,
        boosts: np.ndarray,
        settings: dict[str, Any],
        *,
        node_specificity: bool,
    ) -> np.ndarray:
        """
        Reset mass for the symbols the question reached, and the `used_code_seeds` gate.

        `phrase_weights` is a per-vertex array, so any vertex kind can carry reset mass - nothing
        here assumes an OpenIE phrase (R3 gotcha 5). Two rules decide what a seed is worth: the
        anchor's own share of `code_seed_weight` (already divided by its token's fan-out), and the
        same node-specificity division the reference applies to entities, over an array that holds
        `in_degree + 1` for a code vertex (S2.4).
        """
        index = self.index
        weights = np.zeros(index.num_nodes)
        seed_weight = float(settings.get("code_seed_weight", 1.0))
        dense_seeds = int(settings.get("code_dense_seeds", 5))
        if not index.code_nodes or seed_weight <= 0:
            return weights

        def seed(vertex: int, weight: float, **fields: Any) -> SeedSymbol:
            specificity = float(index.specificity[vertex])
            if node_specificity and specificity > 0:
                weight /= specificity
            return SeedSymbol(
                node_id=index.node_ids[vertex],
                name=index.name_of(vertex),
                vertex=vertex,
                weight=weight * float(boosts[vertex]),
                kind=index.node_kind[vertex],
                specificity=specificity,
                boost=float(boosts[vertex]),
                **fields,
            )

        candidates: list[SeedSymbol] = []
        for anchor in find_anchors(question, index):
            if anchor.ambiguous:
                candidates.append(
                    SeedSymbol(
                        name=anchor.token,
                        how=anchor.how,
                        token=anchor.token,
                        matched_by=anchor.token,
                        n_matches=anchor.n_matches,
                        ambiguous=True,
                    )
                )
                continue
            candidates.append(
                seed(
                    anchor.vertex,
                    seed_weight * anchor.weight,
                    how=anchor.how,
                    token=anchor.token,
                    matched_by=anchor.token,
                    n_matches=anchor.n_matches,
                )
            )

        # Dense seeds: a code passage that scored highly *overall* also seeds the symbols it
        # defines. "Overall", not "top-N among code passages": `dpr_scores` is min-max normalised,
        # so five code passages always lead the code passages whatever was asked (Ruling 1b).
        #
        # A dense seed is worth what the passage it came from is worth as a seed - its similarity
        # times `passage_node_weight`, the existing "a passage seeds PPR lightly" weight - times
        # `code_seed_weight`. PLAN.md leaves this number open, and the obvious reading (the full
        # `code_seed_weight`) is wrong: `dpr_scores` is min-max normalised, so the top passage's
        # dense seed would land at exactly 1.0 and out-weigh an *exact identifier match*, on every
        # question, five times over. What the user typed has to beat what merely looked similar.
        if dense_seeds > 0:
            dense_scale = float(settings.get("passage_node_weight", 0.05))
            already = {c.vertex for c in candidates}
            for position in dpr_order[:dense_seeds]:
                position = int(position)
                passage = index.passages[position]
                for vertex in sorted(index.symbols_defined_in(int(index.passage_vertices[position]))):
                    if index.node_kind[vertex] not in (SYMBOL, DATA) or vertex in already:
                        continue
                    already.add(vertex)
                    candidates.append(
                        seed(
                            vertex,
                            seed_weight * dense_scale * float(dpr_scores[position]),
                            how=DENSE,
                            matched_by=passage.id,
                        )
                    )

        budget = [c for c in candidates if not c.ambiguous and c.weight > 0]
        for chosen in sorted(budget, key=lambda s: (-s.weight, s.node_id))[:MAX_CODE_SEEDS]:
            chosen.kept = True
            weights[chosen.vertex] += chosen.weight
        trace.seed_symbols = sorted(candidates, key=lambda s: (-s.weight, s.name, s.node_id))
        # Only a *lexical* anchor opens the gate (Ruling 1a).
        trace.used_code_seeds = any(s.kept and s.how != DENSE for s in trace.seed_symbols)
        return weights

    def _community_boost(self, trace: Trace, passage_ppr: np.ndarray, boost: float) -> set[int]:
        """Lift passages whose symbols share a subsystem with a kept seed. Default 0.0: a no-op."""
        index = self.index
        communities = {index.community_of(s.vertex) for s in trace.seed_symbols if s.kept and s.vertex >= 0}
        communities.discard(None)
        if boost <= 0 or not communities:
            return set()
        boosted: set[int] = set()
        for position, passage_vertex in enumerate(index.passage_vertices):
            defined = index.symbols_defined_in(int(passage_vertex))
            if any(index.community_of(v) in communities for v in defined):
                passage_ppr[position] *= 1.0 + boost
                boosted.add(position)
        return boosted

    def _explain_code(self, trace: Trace, *, theta: float) -> None:
        """The triples, tests and commits behind a code-seeded answer (rendered by `ask.py`)."""
        index = self.index
        seeds = [s.vertex for s in trace.seed_symbols if s.kept and s.vertex >= 0]
        trace.paths = paths.triple_rows(index, paths.code_paths_for(index, seeds, theta=theta))
        trace.tests = paths.test_rows(index, paths.tests_for(index, seeds, theta=theta))
        commits: list[Any] = []
        for vertex in seeds:
            for commit in paths.history(index, vertex, limit=HISTORY_LIMIT):
                if commit.id not in {c.id for c in commits}:
                    commits.append(commit)
        commits.sort(key=lambda c: (c.ordinal, c.sha))
        trace.history = paths.history_rows(commits[:HISTORY_LIMIT])

    # ----------------------------------------------------------- select pass

    def _select(self, trace: Trace, select_fn: SelectFn, question: str, settings: dict[str, Any]) -> None:
        """
        Keep / drop / expand over the passages around the ones the model is about to read (S2.14).

        The window is deliberately *wider* than the `qa_top_k` slice `ask.py` answers from. Judging
        exactly that slice would make a "drop" inert: there would be nothing outside the window to
        take the dropped passage's place, so the prompt and the citation list would be the same
        list in a different order (AR1 fix 1).

        Dropped passages are ranked *below* the kept ones, never removed - a wrong "drop" should
        cost a position, not erase evidence. Expanded neighbours are appended at score 0.0 with
        `via_expand=True` and are excluded from the `qa_top_k` slice outright: the slice *is* the
        citation list, so "counted only if cited" would be circular.
        """
        qa_top_k = int(settings.get("qa_top_k", 5))
        window_size = max(qa_top_k * 2, qa_top_k + 5)
        window, rest = trace.passages[:window_size], trace.passages[window_size:]
        known = {p.passage_id for p in window}
        decided: dict[str, Any] = {"keep": [], "drop": [], "expand": [], "raw": "", "error": ""}
        try:
            result = select_fn(question, list(window))
            picked = lambda key: [pid for pid in getattr(result, key, []) or [] if pid in known]  # noqa: E731
            decided.update(keep=picked("keep"), drop=picked("drop"), expand=picked("expand"), raw=result.raw)
        except Exception as exc:  # a bad reply must cost a rerank, not an answer
            log.warning("The code select pass failed; keeping every passage: %s", exc)
            decided["error"] = str(exc)
            trace.select = decided
            return

        dropped = set(decided["drop"])
        kept = [p for p in window if p.passage_id not in dropped]
        demoted = [p for p in window if p.passage_id in dropped]
        expanded = self._expand(trace, decided["expand"], limit=int(settings.get("code_expand_max", 10)))
        # `rest` before `demoted`: a passage the model judged irrelevant sinks below the passages
        # it never saw, which is what lets one of them into the `qa_top_k` slice in its place.
        trace.passages = kept + rest + demoted + expanded
        for rank, passage in enumerate(trace.passages, start=1):
            passage.rank = rank
        trace.select = decided

    def _expand(self, trace: Trace, passage_ids: list[str], *, limit: int) -> list[RankedPassage]:
        index = self.index
        if not passage_ids or limit <= 0:
            return []
        vertices: list[int] = []
        for passage_id in passage_ids:
            vertex = index.idx_of.get(passage_id)
            if vertex is not None:
                # Vertex numbers are assigned at load in a backend-independent order, so sorting
                # here is what keeps "which neighbours did `expand` reach first" the same on all
                # three stores - `code_out` itself is in whatever order the store returned rows.
                vertices.extend(sorted(index.symbols_defined_in(vertex)))
        seen = {p.passage_id for p in trace.passages}
        out: list[RankedPassage] = []
        for edge in paths.expand_from(index, vertices, limit=limit):
            for passage_vertex in sorted(index.defining_passages(edge.dst)):
                passage = index.passages[index.passage_position(passage_vertex)]
                if passage.id in seen:
                    continue
                seen.add(passage.id)
                out.append(
                    RankedPassage(
                        passage_id=passage.id,
                        rank=0,
                        score=0.0,
                        dpr_rank=0,
                        dpr_score=0.0,
                        title=passage.title,
                        source_id=passage.source_id,
                        source_name=passage.source_name,
                        preview=passage.text[:240],
                        via_expand=True,
                    )
                )
                trace.expansions.append(
                    {
                        "passage_id": passage.id,
                        "node_id": index.node_ids[edge.dst],
                        "name": paths.display_at(index, edge.dst),
                        "kind": edge.kind,
                        "from": index.node_ids[edge.src],
                    }
                )
        return out

    def _ranked(
        self, scores, dpr_scores, order, dpr_rank_of, top_k, boosted: set[int] | None = None
    ) -> list[RankedPassage]:
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
                    community_boosted=bool(boosted and pos in boosted),
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
    "DATA",
    "ENTITY",
    "PASSAGE",
    "SYMBOL",
    "FactCandidate",
    "FactFilter",
    "RankedPassage",
    "Retriever",
    "SeedEntity",
    "SeedPassage",
    "SeedSymbol",
    "SelectFn",
    "SelectResult",
    "TopNode",
    "Trace",
    "trace_from_dict",
]


def trace_from_dict(data: dict[str, Any]) -> Trace:
    """
    Rebuild a Trace from the JSON we stored with an evaluation result.

    Every row is built with `Cls(**row)`, so a stored trace loads only while every field has a
    default and no field is ever removed. Evals keep traces forever; a trace written before the
    code graph existed must still load after it.
    """
    trace = Trace(
        question=data.get("question", ""),
        settings=dict(data.get("settings", {})),
        graph_version=int(data.get("graph_version", 0)),
        used_dpr_fallback=bool(data.get("used_dpr_fallback", False)),
        fallback_reason=data.get("fallback_reason", ""),
        filter=dict(data.get("filter", {})),
        timing_ms=dict(data.get("timing_ms", {})),
        used_code_seeds=bool(data.get("used_code_seeds", False)),
        question_prose=data.get("question_prose", ""),
        question_code=data.get("question_code", ""),
        paths=list(data.get("paths", [])),
        tests=list(data.get("tests", [])),
        history=list(data.get("history", [])),
        select=dict(data.get("select", {})),
        expansions=list(data.get("expansions", [])),
        evidence_fingerprint=data.get("evidence_fingerprint", ""),
    )
    trace.fact_candidates = [FactCandidate(**c) for c in data.get("fact_candidates", [])]
    trace.seed_entities = [SeedEntity(**s) for s in data.get("seed_entities", [])]
    trace.seed_passages = [SeedPassage(**s) for s in data.get("seed_passages", [])]
    trace.seed_symbols = [SeedSymbol(**s) for s in data.get("seed_symbols", [])]
    trace.top_nodes = [TopNode(**n) for n in data.get("top_nodes", [])]
    trace.passages = [RankedPassage(**p) for p in data.get("passages", [])]
    return trace
