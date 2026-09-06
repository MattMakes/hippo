"""
Digging into one question: why did the search rank things the way it did,
what would change if we tweaked something, and how do we keep a tweak?

    explain.py     explain(index, trace)                 -> Explanation (why each passage, subgraph, facts)
    simulate.py    simulate(ctx, question, overrides)    -> Simulation (new trace, optional answer, diff)
    changesets.py  save / describe / apply saved edits   (the only part that writes to Neo4j)

The Analyze page in the web UI is built on these three.
"""

from .changesets import VALID_OPS, apply, describe, save, validate
from .explain import Explanation, PassageExplanation, explain
from .simulate import Overrides, Simulation, diff_traces, replay_filter, simulate, trace_from_dict

__all__ = [
    "Explanation",
    "PassageExplanation",
    "explain",
    "Overrides",
    "Simulation",
    "simulate",
    "diff_traces",
    "replay_filter",
    "trace_from_dict",
    "VALID_OPS",
    "validate",
    "save",
    "describe",
    "apply",
]
