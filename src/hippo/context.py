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
from .ollama import Ollama
from .store import Store

log = logging.getLogger(__name__)


@dataclass
class AppContext:
    config: Config
    store: Store
    ollama: Ollama
    jobs: Jobs = field(default_factory=Jobs)
    _graph: GraphIndex | None = None
    _graph_lock: threading.Lock = field(default_factory=threading.Lock)

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

    def graph(self) -> GraphIndex:
        """The current in-memory graph. Reloads from Neo4j if the graph version moved on."""
        version = self.store.graph_version()
        with self._graph_lock:
            if self._graph is None or self._graph.version != version:
                self._graph = GraphIndex.load(self.store, version=version)
            return self._graph

    def invalidate_graph(self) -> None:
        with self._graph_lock:
            self._graph = None

    def close(self) -> None:
        self.store.close()
