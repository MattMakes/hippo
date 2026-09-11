"""Owned evaluation DTOs, checked against current source and evidence permissions.

Low-level store evaluation methods remain internal. Ownership is immutable,
versioned JSON at a unique Settings key, committed with set creation. ID-only
joins establish the owner before a question or saved answer is loaded.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
from functools import wraps

from hippo.access import EVERYTHING, Access, Principal
from hippo.hipporag.retriever import Trace, trace_from_dict
from hippo.store.authorization import lock_authorization
from hippo.store.migrations import DEFAULT_WORKSPACE_ID

from .access import AuthorizationChanged
from .identity import canonical_json
from .query_access import current_access
from .replay import reconstruct_trace, view_fingerprint


class EvalAccessDenied(ValueError):
    """The evaluation is missing or unavailable to this audience."""


def _guarded_collection(function):
    """Earlier authorized rows cannot outlive the proof for the whole response."""

    @wraps(function)
    def guarded(self, *args, **kwargs):
        with self.read_scope():
            return function(self, *args, **kwargs)

    return guarded


class EvalAccess:
    def __init__(self, ctx, access: Access | None):
        self.ctx, self.store, self.access = ctx, ctx.store, access

    def _open(self):
        return self.store.count_users() == 0 and not self.store.get_meta("has_had_users")

    def _current(self):
        access = self.access
        if access is None:
            return Principal.open().access if self._open() else EVERYTHING
        access = current_access(self.store, access)
        if access.audience_kind == "open" and not self._open():
            raise AuthorizationChanged("Open evaluation access is no longer available")
        return access

    def graph(self):
        graph = self.ctx.graph_for(self._current())
        graph.validate_authorization()
        return graph

    def get_source(self, source_id):
        """Resolve source presentation exclusively from the current audience view."""
        from hippo.status import source_view

        view = source_view(self.ctx, self._current())
        row = next((row for row in view.sources if row["id"] == source_id), None)
        view.validate()
        return deepcopy(row)

    @contextmanager
    def read_scope(self):
        """Bracket complete response assembly across several authorized reads."""
        epoch = self.store.authorization_epoch()
        graph = self.graph()
        yield self
        graph.validate_authorization()
        self._boundary(epoch)

    def _boundary(self, epoch):
        self._current()
        if self.store.authorization_epoch() != epoch:
            raise AuthorizationChanged("Evaluation permissions changed during the operation")

    def _metadata(self, set_id):
        raw = self.store.get_meta("eval_owner:" + set_id)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return False
        required = {
            "version",
            "workspace_id",
            "owner_id",
            "audience",
            "source_id",
            "origin",
            "evidence_fingerprint",
        }
        if (
            not isinstance(data, dict)
            or set(data) != required
            or type(data["version"]) is not int
            or data["version"] != 1
            or not isinstance(data["workspace_id"], str)
            or not data["workspace_id"]
        ):
            return False
        if (
            not isinstance(data["audience"], str)
            or data["audience"] not in {"owner", "open", "internal"}
            or not isinstance(data["origin"], str)
            or data["origin"] not in {"manual", "generated"}
        ):
            return False
        if data["audience"] == "owner":
            if not isinstance(data["owner_id"], str) or not data["owner_id"]:
                return False
        elif data["owner_id"] is not None:
            return False
        if data["source_id"] is not None and (
            not isinstance(data["source_id"], str) or not data["source_id"]
        ):
            return False
        if not isinstance(data["evidence_fingerprint"], str):
            return False
        return data

    def _authorized(self, set_id):
        try:
            epoch = self.store.authorization_epoch()
            access = self._current()
            metadata = self._metadata(set_id)
            if metadata is False:
                return None
            if metadata is None:
                if access.audience_kind != "internal" and not (
                    access.audience_kind == "open" and self._open()
                ):
                    return None
            elif access.audience_kind != "internal":
                owner = (
                    metadata["audience"] == "owner"
                    and access.audience_kind == "reader"
                    and metadata["owner_id"] == access.user_id
                )
                open_audience = (
                    metadata["audience"] == "open" and access.audience_kind == "open" and self._open()
                )
                if not (owner or open_audience):
                    return None
            row = self.store.get_question_set(set_id)
            if row is None:
                return None
            source_id = metadata["source_id"] if metadata else row.get("source_id")
            if source_id:
                source = self.store.get_source(source_id, access)
                if source is None or (metadata and source.get("workspace_id") != metadata["workspace_id"]):
                    return None
                if self.get_source(source_id) is None:
                    return None
            if metadata and metadata["origin"] == "generated":
                if not metadata["evidence_fingerprint"] or metadata[
                    "evidence_fingerprint"
                ] != view_fingerprint(self.graph()):
                    return None
            self._boundary(epoch)
            return metadata or {}, row, epoch
        except AuthorizationChanged:
            return None

    def require_set(self, set_id):
        authorized = self._authorized(set_id)
        if authorized is None:
            raise EvalAccessDenied("unknown question set or access denied")
        return authorized[1]

    def require_generation_target(self, set_id, source_id):
        authorized = self._authorized(set_id)
        if (
            authorized is None
            or authorized[0].get("origin") != "generated"
            or authorized[0].get("source_id") != source_id
        ):
            raise EvalAccessDenied("Question generation requires its verified source and input view")
        return authorized[1]

    def _ids(self, kind, *, parent=None):
        if self.store.knowledge_backend == "fake":
            if kind == "sets":
                return list(self.store.question_sets)
            if kind == "runs":
                return [
                    key for key, row in self.store.runs.items() if parent is None or row["set_id"] == parent
                ]
            if kind == "results":
                return [key for key, row in self.store.results.items() if row["run_id"] == parent]
            if kind == "question_results":
                return [key for key, row in self.store.results.items() if row["question_id"] == parent]
        queries = {
            "sets": "MATCH (qs:QuestionSet) RETURN qs.id AS id ORDER BY qs.created_at DESC",
            "runs": "MATCH (r:EvalRun)-[:OF]->(qs:QuestionSet) WHERE $parent IS NULL OR qs.id=$parent RETURN r.id AS id ORDER BY r.started_at DESC",
            "results": "MATCH (:EvalRun {id:$parent})-[:RESULT]->(r:EvalResult) RETURN r.id AS id ORDER BY r.created_at",
            "question_results": "MATCH (r:EvalResult)-[:FOR]->(:Question {id:$parent}) RETURN r.id AS id ORDER BY r.created_at DESC",
        }
        return [
            row["id"]
            for row in self.store.run(queries[kind], **({} if kind == "sets" else {"parent": parent}))
        ]

    def _refs(self, kind, identity):
        if self.store.knowledge_backend == "fake":
            rows = {"question": self.store.questions, "run": self.store.runs, "result": self.store.results}
            row = rows[kind].get(identity)
            if row is None:
                return None
            return {key: row[key] for key in (("run_id", "question_id") if kind == "result" else ("set_id",))}
        query = {
            "question": "MATCH (qs:QuestionSet)-[:HAS]->(:Question {id:$id}) RETURN qs.id AS set_id",
            "run": "MATCH (:EvalRun {id:$id})-[:OF]->(qs:QuestionSet) RETURN qs.id AS set_id",
            "result": "MATCH (run:EvalRun)-[:RESULT]->(:EvalResult {id:$id})-[:FOR]->(q:Question) RETURN run.id AS run_id,q.id AS question_id",
        }[kind]
        return self.store.run_one(query, id=identity)

    def get_question_set(self, set_id):
        authorized = self._authorized(set_id)
        if authorized is None:
            return None
        _, row, epoch = authorized
        graph = self.graph()
        result = deepcopy(row)
        if row.get("source_id"):
            source = self.get_source(row["source_id"])
            if source is None:
                return None
            result["source_name"] = source["name"]
        result["question_count"] = len(self.list_questions(set_id))
        result["run_count"] = len(self._ids("runs", parent=set_id))
        if authorized[0]:
            result["error"] = None  # exception strings may embed model/provider input
        graph.validate_authorization()
        self._boundary(epoch)
        return result

    @_guarded_collection
    def list_question_sets(self):
        return [row for identity in self._ids("sets") if (row := self.get_question_set(identity)) is not None]

    def _question_visible(self, row, graph):
        return set(row.get("gold_passage_ids") or []) <= {passage.id for passage in graph.passages}

    @_guarded_collection
    def list_questions(self, set_id):
        authorized = self._authorized(set_id)
        if authorized is None:
            return []
        graph = self.graph()
        rows = [
            deepcopy(row) for row in self.store.list_questions(set_id) if self._question_visible(row, graph)
        ]
        graph.validate_authorization()
        self._boundary(authorized[2])
        return rows

    def get_question(self, question_id):
        refs = self._refs("question", question_id)
        authorized = self._authorized(refs["set_id"]) if refs else None
        if authorized is None:
            return None
        row = self.store.get_question(question_id)
        graph = self.graph()
        if row is None or not self._question_visible(row, graph):
            return None
        graph.validate_authorization()
        self._boundary(authorized[2])
        return deepcopy(row)

    def get_result(self, result_id):
        refs = self._refs("result", result_id)
        run_refs = self._refs("run", refs["run_id"]) if refs else None
        authorized = self._authorized(run_refs["set_id"]) if run_refs else None
        if authorized is None:
            return None
        question = self.get_question(refs["question_id"])
        if question is None or question["set_id"] != run_refs["set_id"]:
            return None
        row = self.store.get_result(result_id)
        if row is None:
            return None
        graph = self.graph()
        result = deepcopy(row)
        raw_trace = row.get("trace") or {}
        reusable = (
            isinstance(raw_trace, dict)
            and bool(raw_trace.get("evidence_fingerprint"))
            and raw_trace["evidence_fingerprint"] == view_fingerprint(graph)
        )
        try:
            original = trace_from_dict(raw_trace)
            trace = reconstruct_trace(graph, original, question=question["text"])
        except (ValueError, TypeError, KeyError, AttributeError):
            trace = Trace(question=question["text"], settings={}, graph_version=graph.version)
            reusable = False
        result["trace"] = trace.to_dict()
        result.update(
            question=question["text"],
            expected_answer=question.get("expected_answer", ""),
            gold_passage_ids=list(question.get("gold_passage_ids") or []),
            answer_withheld=not reusable,
        )
        result["error"] = None
        if not reusable:
            for key in ("answer", "thought", "verdict", "judge_reason"):
                result[key] = ""
            for key in ("judge_score", "exact_match", "f1", "gold_rank", "latency_ms"):
                result[key] = None
            result["recall"] = {}
            result["used_dpr_fallback"] = False
        graph.validate_authorization()
        self._boundary(authorized[2])
        return result

    @_guarded_collection
    def list_results(self, run_id):
        refs = self._refs("run", run_id)
        if not refs or self._authorized(refs["set_id"]) is None:
            return []
        return [
            row
            for identity in self._ids("results", parent=run_id)
            if (row := self.get_result(identity)) is not None
        ]

    @_guarded_collection
    def results_for_question(self, question_id):
        if self.get_question(question_id) is None:
            return []
        return [
            row
            for identity in self._ids("question_results", parent=question_id)
            if (row := self.get_result(identity)) is not None
        ]

    def get_run(self, run_id):
        refs = self._refs("run", run_id)
        authorized = self._authorized(refs["set_id"]) if refs else None
        if authorized is None:
            return None
        graph = self.graph()
        row = self.store.get_run(run_id)
        if row is None:
            return None
        results = self.list_results(run_id)
        result = deepcopy(row)
        if authorized[0]:
            result["error"] = None
        visible_questions = len(self.list_questions(refs["set_id"]))
        # Progress counts owned questions, independently of whether their saved
        # answers can still be shown. Hide progress if some inputs are hidden.
        result["progress_total"] = visible_questions
        result["progress_done"] = (
            min(row.get("progress_done") or 0, visible_questions)
            if visible_questions == authorized[1].get("question_count")
            else len(results)
        )
        if any(item["answer_withheld"] for item in results) or len(results) != len(
            self._ids("results", parent=run_id)
        ):
            result["summary"] = {}
        else:
            from hippo.evals.runner import summarize

            result["summary"] = summarize(results) if results else {}
        graph.validate_authorization()
        self._boundary(authorized[2])
        return result

    @_guarded_collection
    def list_runs(self, set_id=None):
        if set_id is not None and self._authorized(set_id) is None:
            return []
        return [
            row
            for identity in self._ids("runs", parent=set_id)
            if (row := self.get_run(identity)) is not None
        ]

    def create_question_set(self, name, source_id=None, origin="manual"):
        if origin not in {"manual", "generated"}:
            raise ValueError("Unknown evaluation origin")
        with self.store.transaction():
            lock_authorization(self.store)
            access = self._current()
            if access.audience_kind not in {"reader", "open", "internal"} or (
                access.audience_kind == "reader" and not access.user_id
            ):
                raise EvalAccessDenied("An evaluation owner is required")
            source = self.store.get_source(source_id, access) if source_id else None
            source_dto = self.get_source(source_id) if source_id else None
            if source_id and (source is None or source_dto is None):
                raise EvalAccessDenied("unknown source or access denied")
            if not name and origin == "generated" and source_dto:
                name = f"Sample questions: {source_dto['name']}"
            if not isinstance(name, str) or not name:
                raise ValueError("An evaluation name is required")
            fingerprint = view_fingerprint(self.graph()) if origin == "generated" else ""
            metadata = dict(
                version=1,
                workspace_id=source.get("workspace_id") if source else DEFAULT_WORKSPACE_ID,
                owner_id=access.user_id if access.audience_kind == "reader" else None,
                audience="owner" if access.audience_kind == "reader" else access.audience_kind,
                source_id=source_id,
                origin=origin,
                evidence_fingerprint=fingerprint,
            )
            identity = self.store.create_question_set(name, source_id, origin)
            self.store.set_meta("eval_owner:" + identity, canonical_json(metadata))
            self.store._bump_authorization_epoch()
            return identity

    def add_questions(self, set_id, questions):
        with self.store.transaction():
            lock_authorization(self.store)
            self.require_set(set_id)
            graph = self.graph()
            if any(not self._question_visible(row, graph) for row in questions):
                raise EvalAccessDenied("Question evidence is not available")
            graph.validate_authorization()
            return self.store.add_questions(set_id, questions)

    def delete_question_set(self, set_id):
        with self.store.transaction():
            lock_authorization(self.store)
            self.require_set(set_id)
            self.store.delete_question_set(set_id)
            self.store.set_meta("eval_owner:" + set_id, None)
            self.store._bump_authorization_epoch()

    def delete_question(self, question_id):
        with self.store.transaction():
            lock_authorization(self.store)
            if self.get_question(question_id) is None:
                raise EvalAccessDenied("unknown question or access denied")
            self.store.delete_question(question_id)

    def delete_run(self, run_id):
        with self.store.transaction():
            lock_authorization(self.store)
            refs = self._refs("run", run_id)
            if refs is None:
                raise EvalAccessDenied("unknown run or access denied")
            self.require_set(refs["set_id"])
            self.store.delete_run(run_id)

    def create_run(self, set_id, name, settings):
        with self.store.transaction():
            lock_authorization(self.store)
            self.require_set(set_id)
            return self.store.create_run(set_id, name, settings)
