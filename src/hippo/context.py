"""
The one object every part of the app shares: config, the store, Ollama, jobs,
and the in-memory graph (rebuilt when Neo4j's graph version changes).

Web routes, the MCP server and the CLI all get an `AppContext` and call the
same functions, so behaviour is identical no matter where a request comes from.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from .config import Config, load_config
from .hipporag.graph_index import GraphIndex
from .jobs import Jobs
from .model_manager import ModelManager
from .ollama import Ollama
from .store import Store

log = logging.getLogger(__name__)


@dataclass
class AppContext:
    config: Config
    store: Store
    ollama: Ollama
    jobs: Jobs = field(default_factory=Jobs)
    models: ModelManager | None = None  # created on first use (needs ollama + jobs)
    _graph: GraphIndex | None = None
    _graph_lock: threading.Lock = field(default_factory=threading.Lock)  # guards `_graph` itself
    _reload_lock: threading.Lock = field(default_factory=threading.Lock)  # only one thread loads at a time

    @classmethod
    def from_env(cls, ollama: Ollama | None = None) -> AppContext:
        config = load_config()
        store = Store(config.neo4j_uri, config.neo4j_user, config.neo4j_password)
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
        The current in-memory graph. Reloads from Neo4j if the graph version moved on.

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

    def invalidate_graph(self) -> None:
        with self._graph_lock:
            self._graph = None

    def close(self) -> None:
        self.store.close()
