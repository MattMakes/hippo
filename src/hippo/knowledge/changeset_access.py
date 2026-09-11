"""Owner-scoped graph edits with current evidence checks on every operation."""

import json
from copy import deepcopy

from hippo.analysis import changesets
from hippo.store.authorization import lock_authorization

from .eval_access import EvalAccess
from .query_access import current_access, query_access


class ChangesetUnavailable(ValueError):
    pass


class ChangesetAccess:
    def __init__(self, ctx, access):
        self.ctx, self.store, self.access = ctx, ctx.store, access
        self.graph, _, self.validate = query_access(ctx, access)
        self.current = current_access(self.store, access)

    def _owner(self):
        if self.current is None or self.current.audience_kind == "internal":
            return {"version": 1, "audience": "internal", "owner_id": None}
        if self.current.audience_kind == "reader" and self.current.user_id:
            return {"version": 1, "audience": "reader", "owner_id": self.current.user_id}
        if self.current.audience_kind == "open" and not self.store.get_meta("has_had_users"):
            return {"version": 1, "audience": "open", "owner_id": None}
        raise ChangesetUnavailable("Changeset ownership is unavailable")

    def _visible_ops(self, ops):
        return all(
            value in self.graph.idx_of
            for op in ops
            for key, value in op.items()
            if key in {"a", "b", "entity_id"}
        )

    def get(self, identity):
        self.validate()
        raw_owner = self.store.get_meta("changeset_owner:" + identity)
        try:
            owner = json.loads(raw_owner) if isinstance(raw_owner, str) else None
        except (TypeError, ValueError):
            owner = None
        expected = self._owner()
        internal = expected["audience"] == "internal"
        if not internal and owner != expected:
            if raw_owner is not None or expected["audience"] != "open":
                return None
        record = self.store.get_changeset(identity)
        if record is None or not self._visible_ops(record["ops"]):
            return None
        if record.get("from_result_id"):
            result = EvalAccess(self.ctx, self.access).get_result(record["from_result_id"])
            if result is None:
                return None
        self.validate()
        return deepcopy(record)

    def list(self):
        self.validate()
        identities = (
            list(self.store.changesets)
            if self.store.knowledge_backend == "fake"
            else [
                row["id"]
                for row in self.store.run("MATCH (c:Changeset) RETURN c.id AS id ORDER BY c.created_at DESC")
            ]
        )
        result = [row for identity in identities if (row := self.get(identity)) is not None]
        self.validate()
        return result

    def save(self, name, ops, from_result_id=None, note=""):
        changesets.validate(ops)
        with self.store.transaction():
            lock_authorization(self.store)
            self.validate()
            if not self._visible_ops(ops):
                raise ChangesetUnavailable("Changeset evidence is unavailable")
            if from_result_id:
                result = EvalAccess(self.ctx, self.access).get_result(from_result_id)
                if result is None:
                    raise ChangesetUnavailable("Changeset evidence is unavailable")
            identity = changesets.save(self.ctx, name, ops, from_result_id, note)
            self.store.set_meta("changeset_owner:" + identity, json.dumps(self._owner(), sort_keys=True))
            self.store._bump_authorization_epoch()
            return identity

    def delete(self, identity):
        with self.store.transaction():
            lock_authorization(self.store)
            if self.get(identity) is None:
                raise ChangesetUnavailable("No such changeset")
            self.store.delete_changeset(identity)
            self.store.set_meta("changeset_owner:" + identity, None)
            self.store._bump_authorization_epoch()

    def apply(self, identity):
        with self.store.transaction():
            lock_authorization(self.store)
            record = self.get(identity)
            if record is None:
                raise ChangesetUnavailable("No such changeset")
            # Managed object IDs are evidence identities, not writable legacy nodes.
            native_ids = set(self.ctx.graph().node_ids)
            if any(
                value not in native_ids
                for op in record["ops"]
                for key, value in op.items()
                if key in {"a", "b", "entity_id"}
            ):
                raise ValueError("Managed evidence requires typed changes, not legacy graph edits")
            descriptions = changesets.describe(self.ctx, record["ops"], index=self.graph)
            self.validate()
            result = changesets.apply(self.ctx, identity)
            result.pop("graph_version", None)
            result["descriptions"] = descriptions
            self.validate()
            self.store._bump_authorization_epoch()
            return result
