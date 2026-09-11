"""Atomic source-generation publication. No external work belongs in this transaction."""

from datetime import datetime

from ..knowledge import model as k


class GenerationQueries:
    def publish_generation(
        self, generation_id: str, *, expected_parent_id: str | None, published_at: datetime, fault_hook=None
    ) -> str:
        with self.transaction():
            self._lock_authorization()
            generation = self._knowledge_get("Generation", generation_id)
            if generation is None:
                raise ValueError("Unknown generation")
            if generation.parent_id != expected_parent_id:
                raise ValueError("Generation parent differs from compare-and-swap parent")
            # A write lock is acquired before reading the pointer. A Python lock
            # alone cannot serialize separate Neo4j Store processes/connections.
            if self.knowledge_backend != "fake":
                self.run(
                    "MATCH (s:Source {id:$id}) SET s.generation_lock=coalesce(s.generation_lock,0)+1 RETURN s.id AS id",
                    id=generation.source_id,
                )
            source = self.get_source(generation.source_id)
            active = source.get("active_generation_id")
            if active == generation_id:
                events = [
                    event
                    for event in self._knowledge_rows("IndexEvent")
                    if event.generation_id == generation_id and event.kind == "published"
                ]
                if len(events) != 1:
                    raise ValueError("Active generation lacks a unique publication event")
                return events[0].id
            if active != expected_parent_id:
                raise ValueError("Generation publication compare-and-swap failed")
            if generation.status != "ready":
                raise ValueError("Generation is not ready")
            manifests = [
                manifest
                for manifest in self._knowledge_rows("IndexManifest")
                if manifest.generation_id == generation_id
            ]
            if len(manifests) != 1 or not manifests[0].ready:
                raise ValueError("Generation requires a complete ready index manifest")
            published = generation.replace(status="active", published_at=published_at)
            self._write_knowledge(published)
            sequence = int(source.get("generation_version") or 0) + 1
            if self.knowledge_backend == "fake":
                self.sources[generation.source_id].update(
                    active_generation_id=generation_id, generation_version=sequence
                )
            else:
                self.run(
                    "MATCH (s:Source {id:$id}) SET s.active_generation_id=$generation, s.generation_version=$sequence",
                    id=generation.source_id,
                    generation=generation_id,
                    sequence=sequence,
                )
            if fault_hook:
                fault_hook("pointer")
            self.bump_graph_version()
            self._bump_authorization_epoch()
            if fault_hook:
                fault_hook("version")
            event = k.IndexEvent(
                workspace_id=source["workspace_id"],
                generation_id=generation_id,
                kind="published",
                aggregate_id=generation.source_id,
                sequence=sequence,
                dedupe_key=generation_id,
                created_at=published_at,
            )
            self._write_knowledge(event)
            if fault_hook:
                fault_hook("event")
            return event.id
