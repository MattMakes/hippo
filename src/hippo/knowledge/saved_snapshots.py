"""Retention owned by saved results; snapshot IDs are never an access grant.

Callers authorize the question/run and keep its query session open until this
transaction commits. Saved reads still pass through current audience checks.
Legacy-only results have no durable snapshot and retain current-only semantics.
"""

from .replay import view_fingerprint


def save_evaluation_result(store, run_id, question_id, result, *, session):
    """Persist a result and its live generation references in one transaction."""
    with store.transaction():
        store._lock_authorization()
        session.validate()
        run = store.get_run(run_id)
        question = store.get_question(question_id)
        if run is None or question is None or run["set_id"] != question["set_id"]:
            raise ValueError("Evaluation run and question must belong to the same existing set")
        trace = result.get("trace") or {}
        snapshot_ids = tuple(trace.get("snapshot_ids", ()))
        if trace:
            if snapshot_ids != tuple(getattr(session.graph, "snapshot_ids", ())):
                raise ValueError("Saved trace snapshots differ from the live query")
            if trace.get("evidence_fingerprint") != view_fingerprint(session.graph):
                raise ValueError("Saved trace evidence differs from the live query")
        result_id = store.add_result(run_id, question_id, result)
        for snapshot_id in snapshot_ids:
            store.retain_snapshot(snapshot_id, kind="saved", reference_key="eval_result:" + result_id)
        session.validate()
        return result_id


def release_saved_evaluations(store, result_ids):
    """Release only these results' references inside their authorized deletion."""
    keys = {"eval_result:" + identity for identity in result_ids}
    with store.transaction():
        store._lock_authorization()
        for reference in store._knowledge_rows("SnapshotReference"):
            if (
                reference.kind == "saved"
                and reference.reference_key in keys
                and reference.released_at is None
            ):
                store.release_snapshot_reference(reference.id)
