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
from dataclasses import dataclass, field, replace

from .access import Access, Principal
from .config import Config, load_config
from .hipporag.graph_index import GraphIndex
from .jobs import Jobs
from .model_manager import ModelManager
from .ollama import Ollama
from .store import AnyStore, open_store

log = logging.getLogger(__name__)


def _release_snapshot(bundle):
    try:
        bundle.close()
    except Exception:
        # Process/store shutdown may beat finalization. The durable lease still
        # expires, so collection never depends on Python object destruction.
        log.warning("Snapshot reference release deferred to lease expiry", exc_info=True)


NATIVE_KINDS = ("Passage", "Symbol", "DataObject", "Commit")


def _owns_untagged_rows(store, source_id: str) -> bool:
    """Whether this source still owns one native row no generation claims.

    CC2's `source_id` + `untagged=True` key (`store/generations.py::_native_rows`, ruling
    14) is one bounded query per kind on every backend, and the loop stops at the first
    kind that answers, so a converting source with passages costs a single query. Only a
    source that has a generation and has not published is ever asked.
    """
    return any(store._native_rows(kind, source_id=source_id, untagged=True) for kind in NATIVE_KINDS)


def legacy_lane(store, sources, managed_records) -> tuple[frozenset[str], frozenset[str]]:
    """`(the sources the legacy lane serves, the converting subset of them)`.

    Two rules, because a conversion is a `Generation` being built and nothing else is.

    A source with no generation keeps `13efa40`'s classification byte for byte: any
    managed record at all -- an `Artifact`, the `managed` flag -- takes it out of the
    legacy lane, and a source with no managed record stays in it whether or not it has
    a row to show. Nothing about such a source is mid-conversion, so nothing about it
    changes.

    A source that has a generation is converting, and `source_serves_legacy` keeps it in
    the legacy lane until its first publication. It is *presented* there only while it
    still owns an untagged row to serve: a bootstrap through managed ingress stages every
    row it has under a generation, so it has none, and it stays invisible on every surface
    until it publishes -- exactly as it was before CC1 (plan invariant 5, PA2, PA6). A
    legacy source converting in place has its old untagged rows, and keeps serving exactly
    those.

    The production coordinator writes the `Generation` before the first `Artifact`
    (`ingest/prose_generation.py`), so a converting source never falls into the first rule
    for a transaction and its legacy graph never blinks out: Blocker A stays fixed.
    """
    generation_sources = {record.source_id for record in store._knowledge_rows("Generation")}
    legacy, converting = set(), set()
    for row in sources:
        identity = row["id"]
        if identity not in generation_sources:
            if identity not in managed_records:
                legacy.add(identity)
            continue
        if store.source_serves_legacy(row) and _owns_untagged_rows(store, identity):
            legacy.add(identity)
            converting.add(identity)
    return frozenset(legacy), frozenset(converting)


def _strict_generations(store, generation_ids) -> frozenset[str]:
    """Which of `generation_ids` carry a ready manifest requiring every representation.

    One manifest read per generation asked about, never the manifest table: a session only asks
    about the generations its sources select, while the table holds one row per sealed generation.
    """
    return frozenset(
        manifest.generation_id
        for generation_id in sorted(set(generation_ids))
        for manifest in store._knowledge_rows("IndexManifest", generation_id=generation_id)
        if manifest.ready and {"evidence", "dense", "native"} <= set(manifest.required_representations)
    )


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
    _managed_scoped: OrderedDict[tuple, GraphIndex] = field(default_factory=OrderedDict)
    _legacy_authorized: OrderedDict[tuple, tuple[GraphIndex, GraphIndex]] = field(default_factory=OrderedDict)

    @classmethod
    def from_env(cls, ollama: Ollama | None = None) -> AppContext:
        config = load_config()
        if ollama is not None and ollama.qa_model != config.qa_model:
            raise ValueError("Injected Ollama client QA model does not match HIPPO_QA_MODEL")
        store = open_store(config)
        ollama = ollama or Ollama(
            config.ollama_url,
            config.llm_model,
            config.embed_model,
            qa_model=config.qa_model,
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

    def graph_for(
        self, access: Access | None, *, settings: dict | None = None, structural: bool = False
    ) -> GraphIndex:
        """
        The graph as `access` may see it. Unrestricted access (None, open mode, internal work)
        gets the full graph; anyone else gets an induced subgraph over their visible sources,
        so a search can neither rank a hidden passage nor spread activation through one.
        """
        epoch = self.store.authorization_epoch()
        from .knowledge.query_access import current_access

        access = current_access(self.store, access)
        graph = self._graph_for(access, epoch, settings=settings, structural=structural)
        from .knowledge.access import AuthorizationChanged

        try:
            if self.store.authorization_epoch() != epoch:
                raise AuthorizationChanged("Authorization changed while loading graph scope")
            if (
                access is not None
                and access.audience_kind != "internal"
                and graph.authorization_check is None
            ):
                graph = self._authorize_legacy(graph, epoch)
            graph.validate_authorization()
            return graph
        except BaseException:
            close = getattr(graph, "close_snapshot", None)
            if close is not None:
                close()
            raise

    def _authorize_legacy(self, graph: GraphIndex, epoch: int) -> GraphIndex:
        from .knowledge.access import AuthorizationChanged
        from .knowledge.replay import view_fingerprint

        def validate():
            if self.store.authorization_epoch() != epoch:
                raise AuthorizationChanged("Authorization changed during graph use")

        key = (id(graph), epoch)
        with self._scoped_lock:
            cached = self._legacy_authorized.get(key)
            if cached is not None:
                self._legacy_authorized.move_to_end(key)
                return cached[1]
            view = replace(graph, version=int(view_fingerprint(graph)[:12], 16), authorization_check=validate)
            # Retain the original too, so its Python id cannot be reused as a cache key.
            self._legacy_authorized[key] = (graph, view)
            while len(self._legacy_authorized) > self.SCOPED_CACHE_SIZE:
                self._legacy_authorized.popitem(last=False)
            return view

    def _graph_for(self, access: Access | None, epoch: int, *, settings=None, structural=False) -> GraphIndex:
        # Which loader can answer at all, not which lane serves a source: `self.graph()`
        # below is `GraphIndex.load`, which reads every native row with no generation
        # filter, so one managed row anywhere means the generation-aware loader must run.
        # A generation-tagged row names a `Generation`, which puts its source in this set,
        # so the unfiltered loader is unreachable while any tagged row exists and never has
        # tagged rows to drop. The serving lane is decided per source inside the
        # generation-aware builders, by `legacy_lane`.
        managed_sources = {record.source_id for record in self.store._knowledge_rows("Artifact")}
        managed_sources.update(record.source_id for record in self.store._knowledge_rows("Generation"))
        managed_sources.update(row["id"] for row in self.store.list_sources() if row.get("managed"))
        if structural:
            with self.store.transaction():
                return self._build_structural_graph(
                    access or Principal.open().access, managed_sources, epoch, settings=settings
                )
        if managed_sources:
            return self._managed_graph_for(
                access or Principal.open().access, managed_sources, epoch, settings=settings
            )
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

    def _managed_graph_for(self, access, managed_sources, epoch, *, settings=None):
        # Pointer selection and reference acquisition share collection's durable
        # transaction boundary. No model calls run in this transaction.
        with self.store.transaction():
            return self._build_managed_graph(access, managed_sources, epoch, settings=settings)

    def _build_managed_graph(self, access, managed_sources, epoch, *, settings=None):
        from .knowledge.access import AuthorizationChanged, EvidenceSelection
        from .knowledge.graph_loader import load_generation_graph
        from .knowledge.projection import compose_graphs, project_managed_graph

        profile = self.ollama.embed_model
        sources = self.store.list_sources(access)
        # The serving lane, one level below the loader choice: a source converting to
        # managed generations is in `managed_sources` from its first staged row, but until
        # it publishes it has no generation to serve and belongs here, where the loader
        # takes exactly its untagged rows. Selection is the active pointer and nothing else.
        legacy_ids, _ = legacy_lane(self.store, sources, managed_sources)
        selected = {
            row["id"]: row["active_generation_id"] for row in sources if row.get("active_generation_id")
        }
        strict = _strict_generations(self.store, selected.values())
        bundle = None
        if any(identity in strict for identity in selected.values()):
            from .knowledge.identity import canonical_json, text_hash
            from .knowledge.snapshots import acquire_query_snapshots

            bundle = acquire_query_snapshots(
                self.store,
                access,
                source_ids=frozenset(
                    source for source, generation in selected.items() if generation in strict
                ),
                profile_fingerprint=profile,
                settings_fingerprint=text_hash(
                    canonical_json(self.store.get_settings() if settings is None else settings)
                ),
            )
        full = load_generation_graph(
            self.store,
            generations=selected,
            legacy_source_ids=legacy_ids,
            version=self.store.graph_version(),
            trusted_untagged_generations={
                source: gen for source, gen in selected.items() if gen not in strict
            },
        )
        proofs = []
        for workspace_id in sorted({row["workspace_id"] for row in sources if row["id"] in managed_sources}):
            # Keep the source-to-generation mapping, not just the generation set: projection must be
            # told which source each selected generation belongs to rather than infer it from rows.
            local = {
                row["id"]: row["active_generation_id"]
                for row in sources
                if row["workspace_id"] == workspace_id and row.get("active_generation_id")
            }
            engine, proof = self.store._reader_proof(
                workspace_id,
                access,
                expected_epoch=epoch,
                selection=EvidenceSelection(generation_ids=frozenset(local.values())),
            )
            proofs.append((engine, proof, local))

        def validate():
            if bundle is not None:
                bundle.validate()
            if self.ollama.embed_model != profile:
                raise AuthorizationChanged("Retrieval profile changed during graph use")
            if self.store.authorization_epoch() != epoch:
                raise AuthorizationChanged("Authorization changed during graph use")
            for engine, proof, _ in proofs:
                engine.validate_current(proof)
            if self.ollama.embed_model != profile:
                raise AuthorizationChanged("Retrieval profile changed during graph use")
            if self.store.authorization_epoch() != epoch:
                raise AuthorizationChanged("Authorization changed during graph use")

        validate()
        key = (
            full.version,
            legacy_ids,
            tuple(proof.policy_fingerprint for _, proof, _ in proofs),
            epoch,
            profile,
        )
        with self._scoped_lock:
            cached = self._managed_scoped.get(key)
            if cached is not None and bundle is None:
                cached.validate_authorization()
                self._managed_scoped.move_to_end(key)
                return cached
        projections = [
            project_managed_graph(
                full,
                self.store,
                proof,
                embedding_profile=profile,
                selected_generations=local,
                snapshot_bundle=bundle,
            )
            for _, proof, local in proofs
        ]
        scoped = compose_graphs(full.scoped(legacy_ids), *projections)
        scoped.authorization_check = validate
        if access.audience_kind != "internal":
            from .knowledge.replay import view_fingerprint

            scoped.version = int(view_fingerprint(scoped)[:12], 16)
        validate()
        if bundle is not None:
            import weakref

            scoped.snapshot_ids = tuple(snapshot.id for snapshot in bundle.snapshots)
            scoped.snapshot_renewal_interval = bundle.lease_duration.total_seconds() / 3
            scoped.close_snapshot = weakref.finalize(scoped, _release_snapshot, bundle)
            return scoped
        with self._scoped_lock:
            self._managed_scoped[key] = scoped
            while len(self._managed_scoped) > self.SCOPED_CACHE_SIZE:
                self._managed_scoped.popitem(last=False)
        return scoped

    def _build_structural_graph(self, access, managed_sources, epoch, *, settings=None):
        """Opt-in local evidence loading; never inspect a model or joint matrix."""
        from .knowledge.access import AuthorizationChanged, EvidenceSelection
        from .knowledge.dense import structural_legacy_graph
        from .knowledge.graph_loader import load_generation_graph
        from .knowledge.identity import canonical_json, text_hash
        from .knowledge.projection import compose_graphs, project_managed_graph
        from .knowledge.replay import view_fingerprint
        from .knowledge.snapshots import acquire_query_snapshots

        sources = self.store.list_sources(access)
        # The same split as `_build_managed_graph`: `managed_sources` chose this loader,
        # `legacy_lane` chooses the lane, and the active pointer chooses evidence.
        legacy_ids, _ = legacy_lane(self.store, sources, managed_sources)
        strict = _strict_generations(
            self.store, (row["active_generation_id"] for row in sources if row.get("active_generation_id"))
        )
        selected, proofs, by_workspace = {}, [], {}
        for source in sorted(sources, key=lambda row: row["id"]):
            if source.get("active_generation_id"):
                by_workspace.setdefault(source["workspace_id"], []).append(source)
        for workspace, rows in sorted(by_workspace.items()):
            identities = frozenset(source["active_generation_id"] for source in rows)
            engine, proof = self.store._reader_proof(
                workspace,
                access,
                expected_epoch=epoch,
                selection=EvidenceSelection(
                    generation_ids=identities, require_exact_membership=identities <= strict
                ),
            )
            local = {}
            # Establish exact authorized evidence before inspecting profiles.
            for source in rows:
                generation = self.store._knowledge_get("Generation", source["active_generation_id"])
                if generation is None or generation.source_id != source["id"]:
                    raise AuthorizationChanged("Selected generation is unavailable")
                selected[source["id"]] = local[source["id"]] = generation
            proofs.append((engine, proof, local))

        bundle = None
        try:
            profiles = {source: gen.embedding_profile for source, gen in selected.items() if gen.id in strict}
            if profiles:
                bundle = acquire_query_snapshots(
                    self.store,
                    access,
                    source_ids=frozenset(profiles),
                    source_profiles=profiles,
                    settings_fingerprint=text_hash(
                        canonical_json(self.store.get_settings() if settings is None else settings)
                    ),
                )
                if bundle.generation_ids != frozenset(
                    gen.id for gen in selected.values() if gen.id in strict
                ):
                    raise AuthorizationChanged("Selected generations changed while acquiring snapshots")

            def validate():
                if self.store.authorization_epoch() != epoch:
                    raise AuthorizationChanged("Authorization changed during graph use")
                if bundle is not None:
                    bundle.validate()
                for engine, proof, _ in proofs:
                    engine.validate_current(proof)
                if self.store.authorization_epoch() != epoch:
                    raise AuthorizationChanged("Authorization changed during graph use")

            validate()
            legacy = load_generation_graph(
                self.store,
                generations={},
                legacy_source_ids=legacy_ids,
                version=self.store.graph_version(),
            )
            if managed_sources or not access.unrestricted:
                legacy = legacy.scoped(legacy_ids)
            legacy = structural_legacy_graph(legacy)
            projected = [
                project_managed_graph(
                    None,
                    self.store,
                    proof,
                    source_profiles={
                        source: generation.embedding_profile for source, generation in local.items()
                    },
                    selected_generations={source: generation.id for source, generation in local.items()},
                    snapshot_bundle=bundle,
                    structural=True,
                )
                for _, proof, local in proofs
            ]
            graph = compose_graphs(legacy, *projected)
            graph.authorization_check = validate
            graph.version = int(view_fingerprint(graph)[:12], 16)
            validate()
            if bundle is not None:
                import weakref

                graph.snapshot_ids = tuple(snapshot.id for snapshot in bundle.snapshots)
                graph.snapshot_renewal_interval = bundle.lease_duration.total_seconds() / 3
                graph.close_snapshot = weakref.finalize(graph, _release_snapshot, bundle)
            return graph
        except BaseException:
            if bundle is not None:
                bundle.close()
            raise

    def invalidate_graph(self) -> None:
        with self._graph_lock:
            self._graph = None
        self.invalidate_scoped()

    def invalidate_scoped(self) -> None:
        """Forget the per-viewer graphs (after a source's visibility changed; the full graph is unchanged)."""
        with self._scoped_lock:
            self._scoped.clear()
            self._managed_scoped.clear()
            self._legacy_authorized.clear()

    def close(self) -> None:
        """
        Stop background jobs before closing the store: none may still be using it once this
        returns. A job (an index, a model pull) runs in its own thread against `self.store`, and
        the neo4j driver's own `close()` warns that closing it while another thread is still using
        it "results in unspecified behaviour" -- observed as an intermittent BufferError.
        """
        for key in self.jobs.running_keys():
            self.jobs.cancel(key)
        self.jobs.wait_all()
        self.store.close()
