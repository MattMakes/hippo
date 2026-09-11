"""
"What if?" for one question: rerun the search with tweaks and show what moved.

The Analyze page lets you change settings, force facts in or out, boost
entities and edit edge weights, then press "Simulate". Nothing is written
to the store; we run the retriever again in memory with the overrides and diff
the two traces.

To keep simulations cheap and repeatable, the LLM fact filter is *replayed*
from the baseline trace (the same facts are kept) unless you ask to rerun
it. Re-generating the answer is also opt-in, because it costs an LLM call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..access import Access
from ..ask import _answer_from_trace
from ..context import AppContext
from ..hipporag.answerer import Answer
from ..hipporag.graph_index import EdgeEdit
from ..hipporag.retriever import (
    FactFilter,
    RankedPassage,
    Retriever,
    SelectFn,
    SelectResult,
    Trace,
    trace_from_dict,
)
from ..knowledge.query_access import AuthorizedModel, query_access
from ..knowledge.replay import can_reuse_answer, reconstruct_trace, view_fingerprint
from ..store.base import validate_settings
from .explain import TOP_PASSAGES

DIFF_TOP = TOP_PASSAGES  # the diff covers the same passages the Analyze page explains

# Which settings a simulation may change. An explicit allow-list rather than "everything in
# SETTING_RULES", because a few settings only take effect while *indexing*: as sliders on the
# Analyze page they would render as knobs that cannot move any ranking, on the page whose whole
# purpose is explaining one. A new setting is not simulatable until it is named here.
SIMULATABLE_SETTINGS = frozenset(
    {
        "linking_top_k",
        "passage_node_weight",
        "damping",
        "node_specificity",
        "synonymy_threshold",
        "retrieval_top_k",
        "qa_top_k",
        "code_seed_weight",
        "code_structural_scale",
        "code_theta",
        "code_dense_seeds",
        "code_triples_chars",
        "code_community_boost",
        "code_select",
        "code_expand_max",
    }
)

# The rest: read once, while indexing, and never looked at again by a search.
INGEST_SETTINGS = frozenset({"code_history_depth", "code_git_timeout_s", "code_history_total_s"})


def validate_simulation_settings(changes: dict[str, Any]) -> dict[str, Any]:
    """`validate_settings`, but refusing the settings a simulation cannot act on."""
    not_simulatable = sorted(set(changes) & INGEST_SETTINGS)
    if not_simulatable:
        raise ValueError(
            f"{', '.join(not_simulatable)} only applies while indexing, so a simulation cannot change it"
        )
    return validate_settings(changes)


@dataclass
class Overrides:
    """Everything the simulate panel can change. All fields are optional."""

    settings: dict[str, Any] = field(default_factory=dict)
    force_include: list[str] = field(default_factory=list)  # fact ids
    force_exclude: list[str] = field(default_factory=list)  # fact ids
    node_boosts: dict[str, float] = field(default_factory=dict)  # entity id -> boost
    edge_edits: list[dict[str, Any]] = field(default_factory=list)  # {a, b, weight}
    rerun_filter: bool = False
    reanswer: bool = False

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Overrides:
        d = d or {}
        return cls(
            settings=validate_simulation_settings(dict(d.get("settings") or {})),
            force_include=[str(x) for x in d.get("force_include") or []],
            force_exclude=[str(x) for x in d.get("force_exclude") or []],
            node_boosts={str(k): float(v) for k, v in (d.get("node_boosts") or {}).items()},
            edge_edits=[
                {"a": str(e["a"]), "b": str(e["b"]), "weight": float(e["weight"])}
                for e in d.get("edge_edits") or []
            ],
            rerun_filter=bool(d.get("rerun_filter", False)),
            reanswer=bool(d.get("reanswer", False)),
        )

    def to_ops(self) -> list[dict[str, Any]]:
        """
        The changeset ops that would make these tweaks permanent.
        force_include/force_exclude are about one question only, so they never become ops.
        """
        ops: list[dict[str, Any]] = []
        for name, value in self.settings.items():
            ops.append({"op": "set_setting", "name": name, "value": value})
        for entity_id, boost in self.node_boosts.items():
            ops.append({"op": "set_node_boost", "entity_id": entity_id, "boost": float(boost)})
        for edit in self.edge_edits:
            ops.append(
                {"op": "set_edge_weight", "a": edit["a"], "b": edit["b"], "weight": float(edit["weight"])}
            )
        return ops

    def edge_edit_objects(self) -> list[EdgeEdit]:
        return [EdgeEdit(e["a"], e["b"], float(e["weight"])) for e in self.edge_edits]


@dataclass
class Simulation:
    trace: Trace
    answer: Answer | None
    diff: dict[str, Any]
    baseline: Trace | None = None  # the trace we compared against (created here for ad-hoc questions)


def simulate(
    ctx: AppContext,
    question: str,
    overrides: Overrides,
    baseline: Trace | None = None,
    access: Access | None = None,
    *,
    authorization_check=None,
) -> Simulation:
    """
    Run the search again with `overrides` and diff it against `baseline` (or a fresh plain search).
    `access` keeps the simulation inside the caller's slice of the graph (hippo/access.py).
    """
    index, model, validate_query = query_access(ctx, access)

    def validate():
        if authorization_check is not None:
            authorization_check()
        validate_query()

    validate()
    model = AuthorizedModel(model, validate)
    if baseline is not None and not can_reuse_answer(index, baseline.evidence_fingerprint):
        baseline = reconstruct_trace(index, baseline, question=question)
    retriever = Retriever(index, model)

    base_settings = dict(baseline.settings) if baseline is not None else ctx.store.get_settings()
    settings = {**base_settings, **overrides.settings}

    # No baseline (ad-hoc question)? Run the real filter once so we have something to replay and diff.
    # With rerun_filter the simulated search runs the LLM itself, so we skip the extra call.
    if baseline is None and not overrides.rerun_filter:
        baseline = retriever.retrieve(question, base_settings, select_fn=retriever.llm_select)

    replaying = not overrides.rerun_filter and baseline is not None
    fact_filter = replay_filter(baseline) if replaying else None
    # The select pass is replayed exactly as the fact filter is. `simulate()` re-runs the whole
    # retrieval on every slider move, so without this a code question would cost one LLM call per
    # move - which is what putting the pass in the retriever was supposed to make replayable.
    select_fn = replay_select(baseline) if replaying else retriever.llm_select
    # The scale composes with the edits inside one rebuild. Applying it anywhere else would be
    # silently discarded the moment a simulation also edited an edge, because `retrieve(graph=)`
    # then runs on *this* igraph.
    scale = float(settings.get("code_structural_scale", 1.0))
    graph = index.graph_with_edits(overrides.edge_edit_objects(), scale) if overrides.edge_edits else None

    trace = retriever.retrieve(
        question,
        settings,
        fact_filter=fact_filter,
        select_fn=select_fn,
        force_include=set(overrides.force_include),
        force_exclude=set(overrides.force_exclude),
        node_boosts=dict(overrides.node_boosts) or None,
        graph=graph,
    )
    trace.evidence_fingerprint = view_fingerprint(index)
    validate()
    answer = _answer_from_trace(index, model, trace) if overrides.reanswer else None
    outcome = Simulation(trace=trace, answer=answer, diff=diff_traces(baseline, trace), baseline=baseline)
    validate()
    return outcome


def replay_filter(baseline: Trace) -> FactFilter:
    """A fact filter that answers with the triples the baseline's LLM kept, without calling the LLM."""
    kept: list[list[str]] = [list(t) for t in baseline.filter.get("kept_triples") or []]

    def replay(question: str, candidates: list[list[str]]) -> tuple[list[list[str]], str]:
        # Only triples that are candidates again. The retriever fuzzy-matches unknown triples to the
        # closest candidate (meant for sloppy LLM output), which would keep a random fact here.
        return [t for t in kept if t in candidates], "replayed"

    return replay


def replay_select(baseline: Trace) -> SelectFn:
    """The keep/drop/expand the baseline's LLM chose, replayed without calling it again."""
    decided = dict(baseline.select or {})

    def replay(question: str, ranked: list[RankedPassage]) -> SelectResult:
        # Only ids that are candidates again: a slider move can push a passage out of the window,
        # and re-applying a decision about a passage nobody is reading would be a silent edit.
        known = {p.passage_id for p in ranked}
        pick = lambda key: [pid for pid in decided.get(key) or [] if pid in known]  # noqa: E731
        return SelectResult(keep=pick("keep"), drop=pick("drop"), expand=pick("expand"), raw="replayed")

    return replay


# --------------------------------------------------------------------- diff


def diff_traces(before: Trace | None, after: Trace) -> dict[str, Any]:
    """What changed between two traces, in the shape the diff table wants."""
    before_top = before.passages[:DIFF_TOP] if before is not None else []
    after_top = after.passages[:DIFF_TOP]
    before_rank = {p.passage_id: p.rank for p in before_top}
    after_rank = {p.passage_id: p.rank for p in after_top}
    titles = {p.passage_id: p.title for p in before_top + after_top}

    rows = []
    for pid in set(before_rank) | set(after_rank):
        b, a = before_rank.get(pid), after_rank.get(pid)
        rows.append(
            {
                "passage_id": pid,
                "title": titles[pid],
                "before_rank": b,
                "after_rank": a,
                "change": _change(b, a),
            }
        )
    # Sort by the new rank; passages that dropped out of the top list go last, in their old order.
    rows.sort(key=lambda r: (r["after_rank"] is None, r["after_rank"] or 0, r["before_rank"] or 0))

    return {
        "passages": rows,
        "seeds_before": _seed_rows(before),
        "seeds_after": _seed_rows(after),
        "fallback_before": before.used_dpr_fallback if before is not None else None,
        "fallback_after": after.used_dpr_fallback,
        "kept_facts_before": _kept_rows(before),
        "kept_facts_after": _kept_rows(after),
    }


def _change(before_rank: int | None, after_rank: int | None) -> str:
    if before_rank is None and after_rank is None:
        return "same"
    if before_rank is None:
        return "new"
    if after_rank is None:
        return "dropped"
    if after_rank < before_rank:
        return "up"
    if after_rank > before_rank:
        return "down"
    return "same"


def _seed_rows(trace: Trace | None) -> list[dict[str, Any]]:
    if trace is None:
        return []
    return [
        {"entity_id": s.entity_id, "name": s.name, "weight": s.weight}
        for s in trace.seed_entities
        if s.kept and s.weight > 0
    ]


def _kept_rows(trace: Trace | None) -> list[dict[str, Any]]:
    if trace is None:
        return []
    return [{"fact_id": c.fact_id, "triple": list(c.triple)} for c in trace.fact_candidates if c.kept]


__all__ = [
    "Overrides",
    "Simulation",
    "diff_traces",
    "replay_filter",
    "replay_select",
    "simulate",
    "trace_from_dict",
]
