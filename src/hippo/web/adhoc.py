"""
A small in-memory cache of ad-hoc analyses.

When you ask a question on the Ask page and click "Analyze this question",
the Analyze page should explain the answer you just saw, not run the search
and the model again (they are slow and not deterministic). So the Ask page
stores the trace under a random key and the link carries that key.

Only the last ADHOC_LIMIT traces are kept, in memory, so a key can expire
(or vanish on restart); the Analyze page then offers to run it again.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

from ..hipporag.retriever import Trace
from ..store.base import new_id

ADHOC_LIMIT = 50

_ADHOC: OrderedDict[str, dict[str, Any]] = OrderedDict()  # trace_key -> {"trace": dict, "answer": dict}
_ADHOC_LOCK = threading.Lock()


def remember_adhoc(trace: Trace, answer: dict[str, Any] | None) -> str:
    """Keep a trace (and the answer given) and return the key to fetch it with."""
    key = new_id()
    with _ADHOC_LOCK:
        _ADHOC[key] = {"trace": trace.to_dict(), "answer": answer}
        while len(_ADHOC) > ADHOC_LIMIT:
            _ADHOC.popitem(last=False)
    return key


def recall_adhoc(key: str) -> dict[str, Any] | None:
    with _ADHOC_LOCK:
        return _ADHOC.get(key)
