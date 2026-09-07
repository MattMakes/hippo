"""
The one object every part of the app shares: config, the store, Ollama, jobs,
and the in-memory graph (rebuilt when the store's graph version changes).

Web routes, the MCP server and the CLI all get an `AppContext` and call the
same functions, so behaviour is identical no matter where a request comes from.

`graph()` is the whole graph; `graph_for(access)` is the part a user may see
(hippo/access.py). Scoped graphs are cut from the full one in memory and cached
by the set of visible sources, so two users who see the same sources share one.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass, field

from .access import Access
from .config import Config, load_config
from .hipporag.graph_index import GraphIndex
from .jobs import Jobs
from .model_manager import ModelManager
from .ollama import Ollama
from .store import AnyStore, open_store

log = logging.getLogger(__name__)


@dataclass
class AppContext:
    config: Config
    store: AnyStore
    ollama: Ollama
    jobs: Jobs = field(default_factory=Jobs)
    models: ModelManager | None = None  # created on first use (needs ollama + jobs)
    _graph: GraphIndex | None = None
    _graph_lock: threading.Lock = field(default_factory=threading.Lock)  # guards `_graph` itself
    _reload_lock: threading.Lock = field(default_factory=threading.Lock)  # only one thread loads at a time
    # (graph version, visible source ids) -> scoped GraphIndex; small, because cutting one is cheap
    _scoped: OrderedDict[tuple[int, frozenset[str]], GraphIndex] = field(default_factory=OrderedDict)
    _scoped_lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def from_env(cls, ollama: Ollama | None = None) -> AppContext:
        config = load_config()
        store = open_store(config)
        ollama = ollama or Ollama(
            config.ollama_url,
            config.llm_model,
            config.embed_model,
            num_ctx=config.num_ctx,
            timeout_seconds=config.llm_timeout_seconds,
        )
        return cls(config=config, store=store, ollama=ollama)

    def __post_init__(self) -> None:
        if self.models is None:
            self.models = ModelManager(self.ollama, self.jobs)

    def graph(self) -> GraphIndex:
        """
        The current in-memory graph. Reloads from the store if the graph version moved on.

        Loading a big graph takes a while, so it happens outside `_graph_lock`: other callers keep
        using the previous graph until the new one is swapped in. Only one thread loads at a time
        (`_reload_lock`); a caller that finds a reload already under way gets the previous graph
        rather than waiting (the trace records `graph_version`, so that is visible).
        """
        fresh = self._graph_if_fresh()
        if fresh is not None:
            return fresh
        with self._graph_lock:
            previous = self._graph
        if previous is None:
            self._reload_lock.acquire()  # nothing to fall back on: wait for whoever is loading
        elif not self._reload_lock.acquire(blocking=False):
            return previous  # a reload is under way; keep using the old graph meanwhile
        try:
            return self._graph_if_fresh() or self._reload()  # the other thread may have just finished
        finally:
            self._reload_lock.release()

    def _graph_if_fresh(self) -> GraphIndex | None:
        """The cached graph if it is up to date with the store, else None."""
        with self._graph_lock:
            # Read the version and the cached graph together, so the comparison is of one moment.
            version = self.store.graph_version()
            current = self._graph
        return current if current is not None and current.version == version else None

    def _reload(self) -> GraphIndex:
        """Load the graph for the store's current version and make it the cached one. Call with `_reload_lock` held."""
        with self._graph_lock:
            version = self.store.graph_version()
        # Labelled with the version read *before* loading: if a bump lands mid-load the new graph
        # looks stale and the next call reloads it, which is the safe way round.
        loaded = GraphIndex.load(self.store, version=version)
        with self._graph_lock:
            self._graph = loaded
        return loaded

    SCOPED_CACHE_SIZE = 16

    def graph_for(self, access: Access | None) -> GraphIndex:
        """
        The graph as `access` may see it. Unrestricted access (None, open mode, internal work)
        gets the full graph; anyone else gets an induced subgraph over their visible sources,
        so a search can neither rank a hidden passage nor spread activation through one.
        """
        full = self.graph()
        if access is None or access.unrestricted:
            return full
        # The store applies the access predicate itself, so this is the Cypher-checked list.
        visible = frozenset(row["id"] for row in self.store.list_sources(access))
        key = (full.version, visible)
        with self._scoped_lock:
            cached = self._scoped.get(key)
            if cached is not None:
                self._scoped.move_to_end(key)
                return cached
        scoped = full.scoped(visible)
        with self._scoped_lock:
            self._scoped[key] = scoped
            while len(self._scoped) > self.SCOPED_CACHE_SIZE:
                self._scoped.popitem(last=False)
        return scoped

    def invalidate_graph(self) -> None:
        with self._graph_lock:
            self._graph = None
        self.invalidate_scoped()

    def invalidate_scoped(self) -> None:
        """Forget the per-viewer graphs (after a source's visibility changed; the full graph is unchanged)."""
        with self._scoped_lock:
            self._scoped.clear()

    def close(self) -> None:
        self.store.close()
