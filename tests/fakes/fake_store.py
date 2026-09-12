"""
An in-memory stand-in for `hippo.store.Store`.

It implements the same methods with the same row shapes, using dicts and
sets instead of Cypher. Tests run against this locally; in CI the same tests
also run against a real Neo4j (see tests/conftest.py), which keeps the two in
step. If you add a query to the real store, add it here too.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from copy import deepcopy
from typing import Any

from hippo.access import (
    DEFAULT_ROLES,
    EVERYONE_RANK,
    EVERYTHING,
    Access,
    hash_password,
    new_token,
    verify_password,
)
from hippo.store.authorization import metadata_mutation, permission_mutation
from hippo.store.base import DEFAULT_SETTINGS, new_id, now_iso, validate_settings
from hippo.store.code import (
    BOOSTABLE_LABELS,
    SPECIFICITY_KINDS,
    SYNONYM_LABELS,
    TUNED_LABELS,
    _commit_row,
    _data_object_row,
    _json_field,
    _symbol_row,
    code_edge_write_rows,
    commit_write_row,
    data_object_write_row,
    modifies_write_rows,
    node_label,
    refers_to_write_rows,
    symbol_write_row,
)
from hippo.store.generations import (
    INTERRUPTED_REFRESH_ERROR,
    INTERRUPTED_REFRESH_STAGE,
    REFRESHING_PREFIX,
    GenerationQueries,
    legacy_source_cleanup,
    native_mutation,
    native_write,
)
from hippo.store.knowledge import KnowledgeQueries
from hippo.store.migrations import DEFAULT_WORKSPACE_ID
from hippo.store.snapshots import SnapshotQueries
from hippo.store.users import clean_capabilities, clean_rank, clean_username, slug


def _boost(entity: dict[str, Any]) -> float:
    """Same as Neo4j's coalesce(e.boost, 1.0): unset means 1.0, but a stored 0 stays 0."""
    return 1.0 if entity.get("boost") is None else float(entity["boost"])


class FakeStore(KnowledgeQueries, GenerationQueries, SnapshotQueries):
    knowledge_backend = "fake"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._knowledge_data = {}
        self._schema_row = None
        self._schema_history = {}
        self._migration_blocked = False
        self._migrating = False
        self._transaction_depth = 0
        self._transaction_failed = False
        self._transaction_owner = None
        self.sources: dict[str, dict[str, Any]] = {}
        self.passages: dict[str, dict[str, Any]] = {}
        self.entities: dict[str, dict[str, Any]] = {}
        self.facts: dict[str, dict[str, Any]] = {}
        self.mentions: set[tuple[str, str]] = set()  # (passage_id, entity_id)
        self.statements: set[tuple[str, str]] = set()  # (passage_id, fact_id)
        self.synonyms: dict[tuple[str, str], dict[str, Any]] = {}  # (a, b) a<b -> {score, manual}
        self.tuned: dict[tuple[str, str], float] = {}
        # The code graph. Every dict here is pruned by hand in delete_source /
        # delete_passages_for_source: Python dicts do not cascade the way DETACH DELETE does, and
        # nothing but a test would notice a dangling key (R1 gotcha 5).
        self.symbols: dict[str, dict[str, Any]] = {}
        self.data_objects: dict[str, dict[str, Any]] = {}
        self.commits: dict[str, dict[str, Any]] = {}
        self.code_edges: dict[tuple[str, str, str], dict[str, Any]] = {}  # (a, b, kind) -> row
        self.definitions: set[tuple[str, str]] = set()  # (node_id, passage_id)
        self.modifies: dict[tuple[str, str], dict[str, Any]] = {}  # (commit_id, symbol_id) -> row
        self.precedes: list[tuple[str, str]] = []
        self.refers_to: dict[tuple[str, str], dict[str, Any]] = {}  # (passage_id, node_id) -> row
        self.settings: dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.meta: dict[str, Any] = {}
        self._graph_version = 0
        self.question_sets: dict[str, dict[str, Any]] = {}
        self.questions: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.results: dict[str, dict[str, Any]] = {}
        self.changesets: dict[str, dict[str, Any]] = {}
        self.roles: dict[str, dict[str, Any]] = {}
        self.users: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------- base
    def close(self) -> None:
        pass

    def ping(self) -> bool:
        # Same as the real store: the first successful ping bootstraps (schema + interrupted jobs).
        if not getattr(self, "_bootstrapped", False):
            self._bootstrapped = True
            self.ensure_schema()
            self.ensure_roles()
            self.ensure_local_workspace_memberships()
            self.mark_interrupted_jobs()
        return True

    def ensure_schema(self) -> None:
        from hippo.store.migrations import migrate_store

        migrate_store(self)

    def in_ambient_transaction(self) -> bool:
        """True only when the calling thread has an open transaction on this store."""
        # Deliberately lock-free: the holder keeps `_lock` for its whole transaction body, so
        # taking it here would block every other thread instead of answering them.
        return self._transaction_owner == threading.get_ident()

    @contextmanager
    def transaction(self):
        with self._lock:
            if not getattr(self, "_schema_checked", False) and not self._migrating:
                self.ensure_schema()
            if self._migration_blocked and not self._migrating:
                raise RuntimeError("Store migration is incomplete; transaction refused")
            outer = self._transaction_depth == 0
            transient = {
                "_lock",
                "_transaction_depth",
                "_transaction_failed",
                "_transaction_owner",
                "_migrating",
                "_migration_blocked",
                "_schema_checked",
                "_bootstrapped",
            }
            snapshot = (
                deepcopy({name: value for name, value in vars(self).items() if name not in transient})
                if outer
                else None
            )
            if outer:
                self._transaction_failed = False
                self._transaction_owner = threading.get_ident()
            self._transaction_depth += 1
            try:
                yield self
                if outer and self._transaction_failed:
                    raise RuntimeError("Nested transaction failed; outer transaction must roll back")
            except BaseException:
                self._transaction_failed = True
                if snapshot is not None:
                    for name, value in snapshot.items():
                        setattr(self, name, value)
                raise
            finally:
                self._transaction_depth -= 1
                if outer:
                    self._transaction_failed = False
                    self._transaction_owner = None

    def get_settings(self) -> dict[str, Any]:
        self._ensure_knowledge_ready()
        return {k: self.settings.get(k, d) for k, d in DEFAULT_SETTINGS.items()}

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        self.settings.update(validate_settings(changes))
        return self.get_settings()

    def get_meta(self, key: str) -> Any:
        return self.meta.get(key)

    @metadata_mutation
    def set_meta(self, key: str, value: Any) -> None:
        self.meta[key] = value

    def graph_version(self) -> int:
        return self._graph_version

    def bump_graph_version(self) -> int:
        self._graph_version += 1
        return self._graph_version

    def stats(self) -> dict[str, int]:
        return {
            "sources": len(self.sources),
            "passages": len(self.passages),
            "entities": len(self.entities),
            "facts": len(self.facts),
            "symbols": len(self.symbols),
            "data_objects": len(self.data_objects),
            "code_edges": len(self.code_edges),
            "commits": len(self.commits),
            "synonym_edges": len(self.synonyms),
            "mention_edges": len(self.mentions),
            "question_sets": len(self.question_sets),
            "eval_runs": len(self.runs),
            "changesets": len(self.changesets),
            "users": len(self.users),
            "roles": len(self.roles),
        }

    # ---------------------------------------------------------- sources
    def create_source(
        self,
        kind: str,
        name: str,
        meta: dict[str, Any] | None = None,
        *,
        owner_id: str | None = None,
        access_role_id: str | None = None,
    ) -> str:
        sid = new_id()
        role = self.roles.get(access_role_id or "")
        self.sources[sid] = {
            "id": sid,
            "kind": kind,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "active_generation_id": None,
            "generation_version": 0,
            "managed": False,
            "active_build_id": None,
            "build_fencing_token": 0,
            "name": name,
            "status": "queued",
            "stage": "queued",
            "progress_done": 0,
            "progress_total": 0,
            "error": None,
            "meta_json": json.dumps(meta or {}),
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "owner_id": owner_id,
            "access_role_id": role["id"] if role else None,
            "min_rank": int(role["rank"]) if role else EVERYONE_RANK,
        }
        return sid

    def _visible(self, source: dict[str, Any], access: Access | None) -> bool:
        return (access or EVERYTHING).can_see_source(source)

    def update_source(self, source_id: str, **fields: Any) -> None:
        allowed = {"status", "stage", "progress_done", "progress_total", "error", "name", "meta_json"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown source fields: {sorted(bad)}")
        if source_id in self.sources:  # Neo4j: MATCH finds nothing for a deleted source, so no error
            self.sources[source_id].update(fields, updated_at=now_iso())

    def _source_row(self, source: dict[str, Any]) -> dict[str, Any]:
        row = dict(source)
        row["meta"] = json.loads(row.pop("meta_json") or "{}")
        pids = [pid for pid, p in self.passages.items() if p["source_id"] == source["id"]]
        row["passages"] = len(pids)
        row["fact_links"] = sum(1 for pid, _ in self.statements if pid in pids)
        row.setdefault("owner_id", None)
        row.setdefault("access_role_id", None)
        row["min_rank"] = int(row.get("min_rank") or 0)
        role = self.roles.get(row["access_role_id"] or "")
        row["access_role_name"] = (
            role["name"] if role else ("Everyone" if not row["access_role_id"] else row["access_role_id"])
        )
        owner = self.users.get(row["owner_id"] or "")
        row["owner_name"] = owner["username"] if owner else ""
        return row

    def get_source(self, source_id: str, access: Access | None = None) -> dict[str, Any] | None:
        s = self.sources.get(source_id)
        return self._source_row(s) if s and self._visible(s, access) else None

    def list_sources(self, access: Access | None = None) -> list[dict[str, Any]]:
        return [
            self._source_row(s)
            for s in sorted(self.sources.values(), key=lambda s: s["created_at"], reverse=True)
            if self._visible(s, access)
        ]

    def _drop_passages_and_code(self, source_id: str) -> None:
        """What DETACH DELETE does for free on a real graph, spelled out: the source's passages and
        code nodes, and every edge either end of which has just gone."""
        gone = self.delete_code_nodes_for_source(source_id)
        pids = {pid for pid, p in self.passages.items() if p["source_id"] == source_id}
        for pid in pids:
            del self.passages[pid]
        gone |= pids
        self.mentions = {m for m in self.mentions if m[0] not in pids}
        self.statements = {s for s in self.statements if s[0] not in pids}
        self.definitions = {d for d in self.definitions if d[0] not in gone and d[1] not in gone}
        self.refers_to = {k: v for k, v in self.refers_to.items() if not (set(k) & gone)}
        self.tuned = {k: v for k, v in self.tuned.items() if not (set(k) & gone)}
        self.synonyms = {k: v for k, v in self.synonyms.items() if not (set(k) & gone)}

    @permission_mutation
    @legacy_source_cleanup
    def delete_source(self, source_id: str) -> None:
        self._drop_passages_and_code(source_id)
        self.sources.pop(source_id, None)
        self.remove_orphans()

    @legacy_source_cleanup
    def delete_passages_for_source(self, source_id: str) -> None:
        self._drop_passages_and_code(source_id)
        self.remove_orphans()

    def mark_interrupted_jobs(self) -> int:
        message = "interrupted by a restart; run it again"
        total = 0
        interrupted = []
        for s in self.sources.values():
            if s["status"] in ("reading", "indexing"):
                s.update(status="failed", error=message, updated_at=now_iso())
                total += 1
            elif s["status"] == "ready" and str(s.get("stage") or "").startswith(REFRESHING_PREFIX):
                # A managed refresh never stopped serving: only its stage is retired.
                s.update(
                    stage=INTERRUPTED_REFRESH_STAGE, error=INTERRUPTED_REFRESH_ERROR, updated_at=now_iso()
                )
                interrupted.append(s["id"])
                total += 1
        for source_id in interrupted:
            # The crash's build holder goes with the stage, or the reindex the new error
            # asks for is refused until the abandoned lease expires.
            self.release_interrupted_build(source_id)
        for r in self.runs.values():
            if r["status"] == "running":
                r.update(status="failed", error=message, finished_at=now_iso())
                total += 1
        for qs in self.question_sets.values():
            if qs["status"] == "generating":
                qs.update(status="failed", error=message)
                total += 1
        return total

    def remove_orphans(self) -> None:
        stated = {fid for _, fid in self.statements}
        for fid in [f for f in self.facts if f not in stated]:
            del self.facts[fid]
        mentioned = {eid for _, eid in self.mentions}
        for eid in [e for e in self.entities if e not in mentioned]:
            del self.entities[eid]
            self.synonyms = {k: v for k, v in self.synonyms.items() if eid not in k}
            self.tuned = {k: v for k, v in self.tuned.items() if eid not in k}

    # --------------------------------------------------------- passages
    @native_write("Passage")
    def add_passages(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            if row["source_id"] not in self.sources:
                continue  # Neo4j: MATCH (s:Source) finds nothing, so the row is silently skipped
            existing = self.passages.get(row["id"], {})
            self.passages[row["id"]] = {
                **existing,
                "id": row["id"],
                "source_id": row["source_id"],
                "ordinal": row["ordinal"],
                "title": row["title"],
                "text": row["text"],
                "embedding": list(row["embedding"]),
            }

    @native_mutation
    def save_extraction(
        self, passage_id: str, entities: list[str], triples: list[list[str]], error: str | None
    ) -> None:
        if passage_id not in self.passages:
            return  # Neo4j: MATCH finds nothing (the passage was deleted meanwhile)
        self.passages[passage_id].update(
            entities_json=json.dumps(entities), triples_json=json.dumps(triples), extraction_error=error
        )

    def _passage_row(self, p: dict[str, Any]) -> dict[str, Any]:
        s = self.sources[p["source_id"]]
        return {
            "id": p["id"],
            "title": p["title"],
            "text": p["text"],
            "ordinal": p["ordinal"],
            "source_id": s["id"],
            "source_name": s["name"],
            "entities": json.loads(p.get("entities_json") or "[]"),
            "triples": json.loads(p.get("triples_json") or "[]"),
            "extraction_error": p.get("extraction_error"),
        }

    def _passage_visible(self, p: dict[str, Any], access: Access | None) -> bool:
        source = self.sources.get(p["source_id"])
        return source is not None and self._visible(source, access)

    def get_passages(self, ids: list[str], access: Access | None = None) -> list[dict[str, Any]]:
        return [
            self._passage_row(self.passages[i])
            for i in ids
            if i in self.passages and self._passage_visible(self.passages[i], access)
        ]

    def passages_for_source(
        self, source_id: str, limit: int = 50, offset: int = 0, access: Access | None = None
    ) -> list[dict[str, Any]]:
        rows = sorted(
            (
                p
                for p in self.passages.values()
                if p["source_id"] == source_id and self._passage_visible(p, access)
            ),
            key=lambda p: p["ordinal"],
        )
        return [self._passage_row(p) for p in rows[offset : offset + limit]]

    def passage_ids_for_source(self, source_id: str) -> list[str]:
        rows = sorted(
            (p for p in self.passages.values() if p["source_id"] == source_id), key=lambda p: p["ordinal"]
        )
        return [p["id"] for p in rows]

    # --------------------------------------------------------- entities
    def existing_entity_ids(self, ids: list[str]) -> set[str]:
        return {i for i in ids if i in self.entities}

    @native_mutation
    def add_entities(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            e = self.entities.setdefault(
                row["id"], {"id": row["id"], "name": row["name"], "boost": None, "created_at": now_iso()}
            )
            e["embedding"] = list(row["embedding"])

    def _passage_count(self, eid: str, access: Access | None = None) -> int:
        return sum(
            1
            for pid, e in self.mentions
            if e == eid and pid in self.passages and self._passage_visible(self.passages[pid], access)
        )

    def get_entities(self, ids: list[str], access: Access | None = None) -> list[dict[str, Any]]:
        rows = []
        for i in ids:
            if i not in self.entities:
                continue
            count = self._passage_count(i, access)
            if count == 0 and not (access or EVERYTHING).unrestricted:
                continue  # Neo4j: WHERE $acc_all OR passage_count > 0 (hidden unless a visible passage mentions it)
            rows.append(
                {
                    "id": i,
                    "name": self.entities[i]["name"],
                    "boost": _boost(self.entities[i]),
                    "passage_count": count,
                }
            )
        return rows

    def search_entities(
        self, text: str, limit: int = 20, access: Access | None = None
    ) -> list[dict[str, Any]]:
        rows = [
            {"id": e["id"], "name": e["name"], "passage_count": self._passage_count(e["id"], access)}
            for e in self.entities.values()
            if text.lower() in e["name"]
        ]
        if not (access or EVERYTHING).unrestricted:
            rows = [r for r in rows if r["passage_count"] > 0]
        rows.sort(key=lambda r: (-r["passage_count"], r["name"]))
        return rows[:limit]

    def load_entity_embeddings(self) -> tuple[list[str], list[list[float]]]:
        ids = list(self.entities)
        return ids, [self.entities[i]["embedding"] for i in ids]

    # ------------------------------------------------------------ facts
    def existing_fact_ids(self, ids: list[str]) -> set[str]:
        return {i for i in ids if i in self.facts}

    @native_mutation
    def add_facts(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            if row["subject_id"] not in self.entities or row["object_id"] not in self.entities:
                continue  # Neo4j: MATCH (a:Entity), (b:Entity) finds nothing, so the row is silently skipped
            f = self.facts.setdefault(
                row["id"],
                {
                    "id": row["id"],
                    "subject": row["subject"],
                    "predicate": row["predicate"],
                    "object": row["object"],
                    "subject_id": row["subject_id"],
                    "object_id": row["object_id"],
                },
            )
            f["embedding"] = list(row["embedding"])

    def _fact_row(self, f: dict[str, Any], with_embedding: bool) -> dict[str, Any]:
        row = {k: f[k] for k in ("id", "subject", "predicate", "object", "subject_id", "object_id")}
        row["passage_ids"] = [pid for pid, fid in self.statements if fid == f["id"]]
        if with_embedding:
            row["embedding"] = f["embedding"]
        return row

    def get_facts(self, ids: list[str], access: Access | None = None) -> list[dict[str, Any]]:
        rows = []
        for i in ids:
            if i not in self.facts:
                continue
            row = self._fact_row(self.facts[i], False)
            row["passage_ids"] = [
                pid
                for pid in row["passage_ids"]
                if pid in self.passages and self._passage_visible(self.passages[pid], access)
            ]
            if row["passage_ids"] or (access or EVERYTHING).unrestricted:
                rows.append(row)
        return rows

    # ------------------------------------------------------------ links
    @native_mutation
    def link_passage_facts(self, pairs: list[tuple[str, str]]) -> None:
        for p, f in pairs:
            if p in self.passages and f in self.facts:
                self.statements.add((p, f))

    @native_mutation
    def link_passage_entities(self, pairs: list[tuple[str, str]]) -> None:
        for p, e in pairs:
            if p in self.passages and e in self.entities:
                self.mentions.add((p, e))

    def _synonym_node(self, node_id: str) -> bool:
        """Entity, symbol or data object: the three kinds SYNONYM has endpoints for (S2.2)."""
        return node_label(node_id, SYNONYM_LABELS) is not None and node_id in (
            self.entities | self.symbols | self.data_objects
        )

    @native_mutation
    def add_synonyms(self, rows: list[tuple[str, str, float]], manual: bool = False) -> None:
        for a, b, score in rows:
            if a == b or not self._synonym_node(a) or not self._synonym_node(b):
                continue
            key = (min(a, b), max(a, b))
            current = self.synonyms.setdefault(key, {"score": None, "manual": False})
            if current["score"] is None or current["score"] < score:
                current["score"] = float(score)
            current["manual"] = current["manual"] or manual

    # ------------------------------------------------------- code graph
    # Same names and row shapes as store/code.py (Neo4j) and store/ladybug.py.

    def _add_code_nodes(self, table: dict[str, Any], rows: list[dict[str, Any]], shaper) -> None:
        for row in rows:
            shaped = shaper(row)
            if shaped["source_id"] not in self.sources:
                continue  # the real stores MATCH (s:Source) and skip the row
            existing = table.get(shaped["id"], {})
            embedding = shaped.pop("embedding", [])  # commits carry no vector
            table[shaped["id"]] = {
                **{"boost": None, "created_at": now_iso()},
                **existing,
                **shaped,
                "embedding": list(embedding) if embedding else list(existing.get("embedding") or []),
            }

    @native_write("Symbol")
    def add_symbols(self, rows: list[dict[str, Any]]) -> None:
        self._add_code_nodes(self.symbols, rows, symbol_write_row)
        for node in self.symbols.values():
            node.setdefault("community", None)

    @native_write("DataObject")
    def add_data_objects(self, rows: list[dict[str, Any]]) -> None:
        self._add_code_nodes(self.data_objects, rows, data_object_write_row)

    @native_write("Commit")
    def add_commits(self, rows: list[dict[str, Any]]) -> None:
        self._add_code_nodes(self.commits, rows, commit_write_row)

    @native_mutation
    def add_code_edges(self, rows: list[dict[str, Any]]) -> None:
        for row in code_edge_write_rows(rows):
            if not self._code_node(row["a"]) or not self._code_node(row["b"]):
                continue
            key = (row["a"], row["b"], row["kind"])
            current = self.code_edges.get(key)
            if current is None or current["omega"] < row["omega"]:
                self.code_edges[key] = {
                    "a": row["a"],
                    "b": row["b"],
                    "kind": row["kind"],
                    "omega": row["omega"],
                    "provenance": row["provenance"],
                    "extra": row["extra"],
                }

    def _code_node(self, node_id: str) -> dict[str, Any] | None:
        for table in (self.symbols, self.data_objects, self.commits):
            if node_id in table:
                return table[node_id]
        return None

    @native_mutation
    def link_definitions(self, pairs: list[tuple[str, str]]) -> None:
        for node_id, passage_id in pairs:
            if self._code_node(node_id) is not None and passage_id in self.passages:
                self.definitions.add((node_id, passage_id))

    @native_mutation
    def add_modifies(self, rows: list[dict[str, Any]]) -> None:
        for row in modifies_write_rows(rows):
            if row["commit_id"] not in self.commits or row["symbol_id"] not in self.symbols:
                continue
            key = (row["commit_id"], row["symbol_id"])
            current = self.modifies.get(key)
            if current is None or current["omega"] < row["omega"]:
                self.modifies[key] = dict(row)

    @native_mutation
    def add_precedes(self, pairs: list[tuple[str, str]]) -> None:
        for a, b in pairs:
            if a != b and a in self.commits and b in self.commits and (a, b) not in self.precedes:
                self.precedes.append((a, b))

    @native_mutation
    def add_refers_to(self, rows: list[dict[str, Any]]) -> None:
        for row in refers_to_write_rows(rows):
            target = self.symbols.get(row["node_id"]) or self.data_objects.get(row["node_id"])
            if target is None or row["passage_id"] not in self.passages:
                continue
            key = (row["passage_id"], row["node_id"])
            current = self.refers_to.get(key)
            if current is None or current["omega"] < row["omega"]:
                self.refers_to[key] = {
                    "passage_id": row["passage_id"],
                    "node_id": row["node_id"],
                    "omega": row["omega"],
                    "token": row["token"],
                }

    @native_mutation
    def set_symbol_communities(self, mapping: dict[str, int]) -> None:
        for symbol_id, community in mapping.items():
            if symbol_id in self.symbols:
                self.symbols[symbol_id]["community"] = int(community)

    # ------------------------------------------------------- reading code nodes

    def _passage_ids_of(self, node_id: str) -> list[str]:
        return [pid for nid, pid in self.definitions if nid == node_id]

    def _code_visible(self, node: dict[str, Any], access: Access | None) -> bool:
        source = self.sources.get(node.get("source_id") or "")
        return source is not None and self._visible(source, access)

    def _get_code_nodes(self, table, ids, access, shaper) -> list[dict[str, Any]]:
        rows = []
        for node_id in ids:
            node = table.get(node_id)
            if node is None or not self._code_visible(node, access):
                continue
            source = self.sources[node["source_id"]]
            rows.append(
                shaper(
                    {
                        **{k: v for k, v in node.items() if k != "embedding"},
                        "source_name": source["name"],
                        "passage_ids": self._passage_ids_of(node_id),
                    }
                )
            )
        return rows

    def get_symbols(self, ids: list[str], access: Access | None = None) -> list[dict[str, Any]]:
        return self._get_code_nodes(self.symbols, ids, access, _symbol_row)

    def get_data_objects(self, ids: list[str], access: Access | None = None) -> list[dict[str, Any]]:
        return self._get_code_nodes(self.data_objects, ids, access, _data_object_row)

    def get_commits(self, ids: list[str], access: Access | None = None) -> list[dict[str, Any]]:
        return self._get_code_nodes(self.commits, ids, access, _commit_row)

    # ------------------------------------------------- loading the code graph

    def _code_in_degrees(self) -> dict[str, int]:
        degrees: dict[str, int] = {}
        for row in self.code_edges.values():
            if row["kind"] in SPECIFICITY_KINDS:
                degrees[row["b"]] = degrees.get(row["b"], 0) + 1
        return degrees

    def _load_code_nodes(self, table, shaper) -> list[dict[str, Any]]:
        degrees = self._code_in_degrees()
        return [
            shaper(
                {
                    **{k: v for k, v in node.items() if k != "embedding"},
                    "source_name": self.sources[node["source_id"]]["name"],
                    "in_degree": degrees.get(node["id"], 0),
                }
            )
            for node in table.values()
            if node["source_id"] in self.sources
        ]

    def load_symbols(self) -> list[dict[str, Any]]:
        return self._load_code_nodes(self.symbols, _symbol_row)

    def load_data_objects(self) -> list[dict[str, Any]]:
        return self._load_code_nodes(self.data_objects, _data_object_row)

    def load_commits(self) -> list[dict[str, Any]]:
        return [
            _commit_row(
                {
                    **{k: v for k, v in node.items() if k != "embedding"},
                    "source_name": self.sources[node["source_id"]]["name"],
                }
            )
            for node in self.commits.values()
            if node["source_id"] in self.sources
        ]

    def load_code_edges(self) -> list[dict[str, Any]]:
        return [{**row, "extra": _json_field(row["extra"])} for row in self.code_edges.values()]

    def load_definitions(self) -> list[dict[str, Any]]:
        return [{"node_id": nid, "passage_id": pid} for nid, pid in self.definitions]

    def load_modifies(self) -> list[dict[str, Any]]:
        return [{**row, "hunk": _json_field(row["hunk"])} for row in self.modifies.values()]

    def load_precedes(self) -> list[dict[str, Any]]:
        ordered = sorted(
            self.precedes,
            key=lambda pair: (
                int(self.commits[pair[0]]["ordinal"] or 0),
                int(self.commits[pair[1]]["ordinal"] or 0),
            ),
        )
        return [{"a": a, "b": b} for a, b in ordered]

    def load_refers_to(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.refers_to.values()]

    def load_code_embeddings(self) -> tuple[list[str], list[list[float]]]:
        ids: list[str] = []
        vectors: list[list[float]] = []
        for table in (self.symbols, self.data_objects):
            for node in table.values():
                if node.get("embedding"):
                    ids.append(node["id"])
                    vectors.append(list(node["embedding"]))
        return ids, vectors

    @legacy_source_cleanup
    def delete_code_nodes_for_source(self, source_id: str) -> set[str]:
        """Every code node of one source, and every code edge touching one. Returns the ids dropped
        so the caller can prune the edge dicts a real graph would cascade for it."""
        gone: set[str] = set()
        for table in (self.symbols, self.data_objects, self.commits):
            for node_id in [i for i, n in table.items() if n.get("source_id") == source_id]:
                del table[node_id]
                gone.add(node_id)
        self.code_edges = {k: v for k, v in self.code_edges.items() if not ({k[0], k[1]} & gone)}
        self.modifies = {k: v for k, v in self.modifies.items() if not (set(k) & gone)}
        self.precedes = [p for p in self.precedes if not (set(p) & gone)]
        self.definitions = {d for d in self.definitions if d[0] not in gone}
        self.refers_to = {k: v for k, v in self.refers_to.items() if not (set(k) & gone)}
        self.synonyms = {k: v for k, v in self.synonyms.items() if not (set(k) & gone)}
        self.tuned = {k: v for k, v in self.tuned.items() if not (set(k) & gone)}
        return gone

    # ---------------------------------------------------------- roles
    def ensure_roles(self) -> None:
        for role in DEFAULT_ROLES:
            self.roles.setdefault(
                role["id"], {**role, "capabilities": list(role["capabilities"]), "builtin": True}
            )

    def _role_row(self, role: dict[str, Any]) -> dict[str, Any]:
        row = dict(role)
        row["rank"] = int(row.get("rank") or 0)
        row["capabilities"] = sorted(row.get("capabilities") or [])
        row["users"] = sum(1 for u in self.users.values() if u.get("role_id") == role["id"])
        row["sources"] = sum(1 for s in self.sources.values() if s.get("access_role_id") == role["id"])
        return row

    def list_roles(self) -> list[dict[str, Any]]:
        return [
            self._role_row(r) for r in sorted(self.roles.values(), key=lambda r: (-int(r["rank"]), r["name"]))
        ]

    def get_role(self, role_id: str | None) -> dict[str, Any] | None:
        r = self.roles.get(role_id or "")
        return self._role_row(r) if r else None

    def create_role(
        self, name: str, rank: int, description: str = "", capabilities: list[str] | None = None
    ) -> str:
        name = (name or "").strip()
        if not name:
            raise ValueError("the role needs a name")
        role_id = slug(name)
        if role_id in self.roles:
            role_id = f"{role_id}-{new_id()[:4]}"
        self.roles[role_id] = {
            "id": role_id,
            "name": name,
            "rank": clean_rank(rank),
            "description": (description or "").strip(),
            "capabilities": clean_capabilities(capabilities),
            "builtin": False,
        }
        return role_id

    @permission_mutation
    def update_role(self, role_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {"name", "rank", "description", "capabilities"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown role fields: {sorted(bad)}")
        role = self.roles.get(role_id)
        if role is None:
            raise ValueError("no such role")
        if "name" in fields:
            role["name"] = str(fields["name"]).strip()
            if not role["name"]:
                raise ValueError("the role needs a name")
        if "rank" in fields:
            role["rank"] = clean_rank(fields["rank"])
            for s in self.sources.values():
                if s.get("access_role_id") == role_id:
                    s["min_rank"] = role["rank"]
        if "description" in fields:
            role["description"] = str(fields["description"] or "").strip()
        if "capabilities" in fields:
            role["capabilities"] = clean_capabilities(fields["capabilities"])
        return self._role_row(role)

    @permission_mutation
    def delete_role(self, role_id: str) -> None:
        role = self.get_role(role_id)
        if role is None:
            raise ValueError("no such role")
        if role["users"] or role["sources"]:
            raise ValueError(
                f"'{role['name']}' is still used by {role['users']} user(s) and {role['sources']} source(s); "
                "move them to another role first"
            )
        if len(self.roles) <= 1:
            raise ValueError("cannot delete the last role")
        del self.roles[role_id]

    # ---------------------------------------------------------- users
    def _user_row(self, user: dict[str, Any]) -> dict[str, Any]:
        row = dict(user)
        role = self.roles.get(user.get("role_id") or "")
        row["role_name"] = role["name"] if role else (user.get("role_id") or "")
        row["rank"] = int(role["rank"]) if role else 0
        row["sources"] = sum(1 for s in self.sources.values() if s.get("owner_id") == user["id"])
        return row

    def count_users(self) -> int:
        return len(self.users)

    def list_users(self) -> list[dict[str, Any]]:
        rows = [self._user_row(u) for u in self.users.values()]
        rows.sort(key=lambda r: (-r["rank"], r["username"]))
        return rows

    def get_user(self, user_id: str | None) -> dict[str, Any] | None:
        u = self.users.get(user_id or "")
        return self._user_row(u) if u else None

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        name = (username or "").strip().lower()
        for u in self.users.values():
            if u["username"] == name:
                return self._user_row(u)
        return None

    def get_user_by_token(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        for u in self.users.values():
            if u["token"] == token:
                return self._user_row(u)
        return None

    @permission_mutation
    def create_user(self, username: str, password: str, role_id: str, display_name: str = "") -> str:
        username = clean_username(username)
        if self.get_user_by_username(username) is not None:
            raise ValueError(f"the username '{username}' is taken")
        if role_id not in self.roles:
            raise ValueError("no such role")
        user_id = new_id()
        self.users[user_id] = {
            "id": user_id,
            "username": username,
            "display_name": (display_name or "").strip(),
            "password_hash": hash_password(password),
            "token": new_token(),
            "role_id": role_id,
            "disabled": False,
            "created_at": now_iso(),
        }
        return user_id

    @permission_mutation
    def update_user(self, user_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {"display_name", "role_id", "disabled", "password"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown user fields: {sorted(bad)}")
        user = self.users.get(user_id)
        if user is None:
            raise ValueError("no such user")
        if "display_name" in fields:
            user["display_name"] = str(fields["display_name"] or "").strip()
        if "disabled" in fields:
            user["disabled"] = bool(fields["disabled"])
        if "password" in fields:
            user["password_hash"] = hash_password(str(fields["password"]))
        if "role_id" in fields:
            if fields["role_id"] not in self.roles:
                raise ValueError("no such role")
            user["role_id"] = fields["role_id"]
        return self._user_row(user)

    def rotate_token(self, user_id: str) -> str:
        token = new_token()
        if user_id in self.users:
            self.users[user_id]["token"] = token
        return token

    @permission_mutation
    def delete_user(self, user_id: str) -> None:
        for s in self.sources.values():
            if s.get("owner_id") == user_id:
                s["owner_id"] = None
        self.users.pop(user_id, None)

    def check_password(self, username: str, password: str) -> dict[str, Any] | None:
        user = self.get_user_by_username(username)
        if user is None or user.get("disabled"):
            return None
        return user if verify_password(password, user.get("password_hash")) else None

    @permission_mutation
    def set_source_access(self, source_id: str, role_id: str | None, owner_id: str | None = ...) -> None:
        if role_id:
            role = self.roles.get(role_id)
            if role is None:
                raise ValueError("no such role")
            min_rank = int(role["rank"])
        else:
            min_rank = EVERYONE_RANK
        source = self.sources.get(source_id)
        if source is None:
            return
        source.update(access_role_id=role_id, min_rank=min_rank, updated_at=now_iso())
        if owner_id is not ...:
            source["owner_id"] = owner_id

    # ------------------------------------------------------- graph loads
    def load_entities(self) -> list[dict[str, Any]]:
        return [
            {
                "id": e["id"],
                "name": e["name"],
                "boost": _boost(e),
                "passage_count": self._passage_count(e["id"]),
                "created_at": e.get("created_at", ""),
            }
            for e in self.entities.values()
        ]

    def load_passages(self) -> list[dict[str, Any]]:
        return [
            {
                "id": p["id"],
                "title": p["title"],
                "text": p["text"],
                "ordinal": p["ordinal"],
                "embedding": p["embedding"],
                "source_id": p["source_id"],
                "source_name": self.sources[p["source_id"]]["name"],
                "generation_id": p.get("generation_id"),
                "retrieval_view_id": p.get("retrieval_view_id"),
            }
            for p in self.passages.values()
        ]

    def load_facts(self) -> list[dict[str, Any]]:
        return [self._fact_row(f, True) for f in self.facts.values()]

    def load_fact_edges(self) -> list[dict[str, Any]]:
        counts: dict[tuple[str, str], int] = {}
        for _, fid in self.statements:
            f = self.facts[fid]
            if f["subject_id"] != f["object_id"]:
                key = (f["subject_id"], f["object_id"])
                counts[key] = counts.get(key, 0) + 1
        return [{"a": a, "b": b, "weight": w} for (a, b), w in counts.items()]

    def load_mentions(self) -> list[dict[str, Any]]:
        return [{"passage_id": p, "entity_id": e} for p, e in self.mentions]

    def load_synonyms(self) -> list[dict[str, Any]]:
        return [
            {"a": a, "b": b, "score": v["score"], "manual": v["manual"]}
            for (a, b), v in self.synonyms.items()
        ]

    def load_tuned_edges(self) -> list[dict[str, Any]]:
        return [{"a": a, "b": b, "weight": w} for (a, b), w in self.tuned.items()]

    # ---------------------------------------------------- question sets
    def create_question_set(self, name: str, source_id: str | None = None, origin: str = "manual") -> str:
        sid = new_id()
        self.question_sets[sid] = {
            "id": sid,
            "name": name,
            "origin": origin,
            "status": "ready",
            "stage": "",
            "progress_done": 0,
            "progress_total": 0,
            "error": None,
            "created_at": now_iso(),
            "source_id": source_id,
        }
        return sid

    def update_question_set(self, set_id: str, **fields: Any) -> None:
        allowed = {"status", "stage", "progress_done", "progress_total", "error", "name"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown question set fields: {sorted(bad)}")
        self.question_sets[set_id].update(fields)

    def add_questions(self, set_id: str, questions: list[dict[str, Any]]) -> list[str]:
        offset = sum(1 for q in self.questions.values() if q["set_id"] == set_id)
        ids = []
        for i, q in enumerate(questions):
            qid = new_id()
            self.questions[qid] = {
                "id": qid,
                "set_id": set_id,
                "text": q["text"],
                "expected_answer": q.get("expected_answer", ""),
                "gold_passage_ids": list(q.get("gold_passage_ids") or []),
                "kind": q.get("kind", "single"),
                "notes": q.get("notes", ""),
                "ordinal": offset + i,
            }
            ids.append(qid)
        return ids

    def delete_question(self, question_id: str) -> None:
        self.questions.pop(question_id, None)
        for rid in [r for r, res in self.results.items() if res["question_id"] == question_id]:
            del self.results[rid]

    def delete_question_set(self, set_id: str) -> None:
        for qid in [q for q, v in self.questions.items() if v["set_id"] == set_id]:
            self.delete_question(qid)
        for rid in [r for r, v in self.runs.items() if v["set_id"] == set_id]:
            self.delete_run(rid)
        self.question_sets.pop(set_id, None)

    def _set_row(self, qs: dict[str, Any]) -> dict[str, Any]:
        row = dict(qs)
        src = self.sources.get(qs.get("source_id") or "")
        row["source_name"] = src["name"] if src else None
        row["question_count"] = sum(1 for q in self.questions.values() if q["set_id"] == qs["id"])
        row["run_count"] = sum(1 for r in self.runs.values() if r["set_id"] == qs["id"])
        return row

    def get_question_set(self, set_id: str) -> dict[str, Any] | None:
        qs = self.question_sets.get(set_id)
        return self._set_row(qs) if qs else None

    def list_question_sets(self) -> list[dict[str, Any]]:
        return [
            self._set_row(qs)
            for qs in sorted(self.question_sets.values(), key=lambda s: s["created_at"], reverse=True)
        ]

    def _question_row(self, q: dict[str, Any]) -> dict[str, Any]:
        return {
            k: q[k] for k in ("id", "text", "expected_answer", "gold_passage_ids", "kind", "notes", "ordinal")
        }

    def list_questions(self, set_id: str) -> list[dict[str, Any]]:
        rows = sorted(
            (q for q in self.questions.values() if q["set_id"] == set_id), key=lambda q: q["ordinal"]
        )
        return [self._question_row(q) for q in rows]

    def get_question(self, question_id: str) -> dict[str, Any] | None:
        q = self.questions.get(question_id)
        if not q:
            return None
        row = self._question_row(q)
        row["set_id"] = q["set_id"]
        row["set_name"] = self.question_sets[q["set_id"]]["name"]
        return row

    # ------------------------------------------------------------- runs
    def create_run(self, set_id: str, name: str, settings: dict[str, Any]) -> str:
        rid = new_id()
        self.runs[rid] = {
            "id": rid,
            "set_id": set_id,
            "name": name,
            "status": "running",
            "started_at": now_iso(),
            "finished_at": None,
            "settings_json": json.dumps(settings),
            "summary_json": "{}",
            "progress_done": 0,
            "progress_total": sum(1 for q in self.questions.values() if q["set_id"] == set_id),
            "error": None,
        }
        return rid

    def update_run(self, run_id: str, **fields: Any) -> None:
        allowed = {"status", "finished_at", "summary_json", "progress_done", "error", "name"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown run fields: {sorted(bad)}")
        self.runs[run_id].update(fields)

    def _run_row(self, r: dict[str, Any]) -> dict[str, Any]:
        row = dict(r)
        row["settings"] = json.loads(row.pop("settings_json") or "{}")
        row["summary"] = json.loads(row.pop("summary_json") or "{}")
        row["set_name"] = self.question_sets[r["set_id"]]["name"]
        return row

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        r = self.runs.get(run_id)
        return self._run_row(r) if r else None

    def list_runs(self, set_id: str | None = None) -> list[dict[str, Any]]:
        rows = [r for r in self.runs.values() if set_id is None or r["set_id"] == set_id]
        return [self._run_row(r) for r in sorted(rows, key=lambda r: r["started_at"], reverse=True)]

    def delete_run(self, run_id: str) -> None:
        for rid in [r for r, res in self.results.items() if res["run_id"] == run_id]:
            del self.results[rid]
        self.runs.pop(run_id, None)

    # ---------------------------------------------------------- results
    def add_result(self, run_id: str, question_id: str, result: dict[str, Any]) -> str:
        rid = new_id()
        self.results[rid] = {
            "id": rid,
            "run_id": run_id,
            "question_id": question_id,
            "answer": result.get("answer", ""),
            "thought": result.get("thought", ""),
            "verdict": result.get("verdict", ""),
            "judge_score": result.get("judge_score"),
            "judge_reason": result.get("judge_reason", ""),
            "exact_match": result.get("exact_match"),
            "f1": result.get("f1"),
            "recall_json": json.dumps(result.get("recall", {})),
            "gold_rank": result.get("gold_rank"),
            "latency_ms": result.get("latency_ms"),
            "trace_json": json.dumps(result.get("trace", {})),
            "used_dpr_fallback": bool(result.get("used_dpr_fallback", False)),
            "error": result.get("error"),
            "created_at": now_iso(),
        }
        return rid

    def _result_row(self, res: dict[str, Any], with_trace: bool) -> dict[str, Any]:
        row = dict(res)
        row.setdefault("used_dpr_fallback", False)  # same fallback as RESULT_DEFAULTS in the real store
        row["recall"] = json.loads(row.pop("recall_json") or "{}")
        trace_json = row.pop("trace_json")
        row["trace"] = json.loads(trace_json or "{}") if with_trace else None
        q = self.questions[res["question_id"]]
        row.update(
            question=q["text"],
            expected_answer=q["expected_answer"],
            kind=q["kind"],
            gold_passage_ids=q["gold_passage_ids"],
            ordinal=q["ordinal"],
            run_name=self.runs[res["run_id"]]["name"],
        )
        return row

    def list_results(self, run_id: str) -> list[dict[str, Any]]:
        rows = [r for r in self.results.values() if r["run_id"] == run_id]
        rows.sort(key=lambda r: self.questions[r["question_id"]]["ordinal"])
        return [self._result_row(r, False) for r in rows]

    def get_result(self, result_id: str) -> dict[str, Any] | None:
        r = self.results.get(result_id)
        return self._result_row(r, True) if r else None

    def results_for_question(self, question_id: str) -> list[dict[str, Any]]:
        rows = [r for r in self.results.values() if r["question_id"] == question_id]
        return [self._result_row(r, False) for r in sorted(rows, key=lambda r: r["created_at"], reverse=True)]

    # ------------------------------------------------------- changesets
    def create_changeset(
        self, name: str, ops: list[dict[str, Any]], from_result_id: str | None = None, note: str = ""
    ) -> str:
        cid = new_id()
        self.changesets[cid] = {
            "id": cid,
            "name": name,
            "note": note,
            "status": "draft",
            "ops_json": json.dumps(ops),
            "created_at": now_iso(),
            "applied_at": None,
            "from_result_id": from_result_id,
        }
        return cid

    def _changeset_row(self, c: dict[str, Any]) -> dict[str, Any]:
        row = dict(c)
        row["ops"] = json.loads(row.pop("ops_json") or "[]")
        return row

    def get_changeset(self, changeset_id: str) -> dict[str, Any] | None:
        c = self.changesets.get(changeset_id)
        return self._changeset_row(c) if c else None

    def list_changesets(self) -> list[dict[str, Any]]:
        return [
            self._changeset_row(c)
            for c in sorted(self.changesets.values(), key=lambda c: c["created_at"], reverse=True)
        ]

    def delete_changeset(self, changeset_id: str) -> None:
        self.changesets.pop(changeset_id, None)

    def mark_applied(self, changeset_id: str) -> None:
        self.changesets[changeset_id].update(status="applied", applied_at=now_iso())

    @native_mutation
    def set_node_boost(self, entity_id: str, boost: float) -> None:
        label = node_label(entity_id, BOOSTABLE_LABELS)
        for table in (self.entities, self.symbols, self.data_objects):
            if label is not None and entity_id in table:
                table[entity_id]["boost"] = float(boost)

    @native_mutation
    def set_edge_weight(self, a: str, b: str, weight: float) -> None:
        known = set(self.entities) | set(self.passages) | set(self.symbols) | set(self.data_objects)
        tunable = node_label(a, TUNED_LABELS) and node_label(b, TUNED_LABELS)
        if tunable and a in known and b in known:
            self.tuned[(min(a, b), max(a, b))] = float(weight)

    @native_mutation
    def clear_edge_weight(self, a: str, b: str) -> None:
        self.tuned.pop((min(a, b), max(a, b)), None)
