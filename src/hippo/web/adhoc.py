"""
A small in-memory cache of ad-hoc analyses.

When you ask a question on the Ask page and click "Analyze this question",
the Analyze page should explain the answer you just saw, not run the search
and the model again (they are slow and not deterministic). So the Ask page
stores the trace under a random key and the link carries that key.

Only the last ADHOC_LIMIT traces are kept, in memory, so a key can expire
(or vanish on restart); the Analyze page then offers to run it again.

Each entry remembers who asked (`owner`, a user id or None in open mode) and
`recall_adhoc` only answers that same person: a key is a random string, but
one user must not be able to open another user's analysis by pasting it.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from copy import deepcopy
from typing import Any

from ..hipporag.retriever import Trace, trace_from_dict
from ..knowledge.replay import can_reuse_answer, reconstruct_trace
from ..store.base import new_id

ADHOC_LIMIT = 50

_ADHOC: OrderedDict[str, dict[str, Any]] = OrderedDict()  # trace_key -> {"trace": dict, "answer": dict}
_ADHOC_LOCK = threading.Lock()


def remember_adhoc(trace: Trace, answer: dict[str, Any] | None, owner: str | None = None) -> str:
    """Keep a trace (and the answer given) for `owner` and return the key to fetch it with."""
    key = new_id()
    with _ADHOC_LOCK:
        _ADHOC[key] = {"trace": trace.to_dict(), "answer": answer, "owner": owner}
        while len(_ADHOC) > ADHOC_LIMIT:
            _ADHOC.popitem(last=False)
    return key


def recall_adhoc(key: str, owner: str | None = None, *, graph) -> dict[str, Any] | None:
    """The entry under `key`, if it belongs to `owner` (None matches only open-mode entries)."""
    with _ADHOC_LOCK:
        entry = _ADHOC.get(key)
    if entry is None or entry.get("owner") != owner:
        return None
    entry = deepcopy(entry)
    trace = trace_from_dict(entry["trace"])
    if can_reuse_answer(graph, trace.evidence_fingerprint):
        return entry
    entry["trace"] = reconstruct_trace(graph, trace, question=trace.question).to_dict()
    entry["answer"] = {"answer": "Evidence access changed; ask again for a current answer.", "thought": ""}
    graph.validate_authorization()
    return entry
