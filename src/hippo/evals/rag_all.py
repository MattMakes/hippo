"""Validated cross-source fixtures and an injected, retrieval-only legacy baseline.

The runner never passes gold labels to an indexer or retriever. Evidence is scored
only after search, by source identity and complete original-quote containment.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..access import Access
from ..ask import search
from ..codegraph import extract_code
from ..context import AppContext
from ..hipporag.indexer import index_source, passage_id
from ..ingest.chunker import chunk_documents
from ..ingest.readers import read_path
from .metrics import passage_evidence_metrics

SLICES = (
    "exact_lookup",
    "schema_join",
    "code_dependency",
    "requirements_rationale",
    "cross_source_impact",
    "temporal_conflict_insufficient",
)
LEGACY_FAMILIES = frozenset({"code", "ddl", "prd"})
FAMILY_GAPS = {
    "ddl": "text/code extraction only; typed schema constraints and join validation unavailable",
    "prd": "heading chunks only; approval-state and structured decision extraction unavailable",
    "jira": "provider ingestion and comment-level ACL unavailable",
    "tuleap": "provider ingestion and tracker-field mapping unavailable",
    "github": "review ingestion and diff-side provenance unavailable",
    "gitlab": "review ingestion and diff-side provenance unavailable",
    "manifest": "typed service manifest ingestion unavailable",
    "backstage": "catalog ingestion and drift resolution unavailable",
    "openapi": "API contract ingestion and reference resolution unavailable",
}


@dataclass
class Fixture:
    root: Path
    manifest: dict[str, Any]
    sources: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    questions: list[dict[str, Any]]
    fingerprint: str


def _path(root: Path, name: str, directory: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root / directory) or not path.is_file():
        raise ValueError(f"file must be inside {directory}: {name}")
    return path


def _unique(rows: list[dict], label: str) -> dict[str, dict]:
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{label} records must be an array of objects")
    result = {}
    for row in rows:
        ident = row.get("id")
        if not isinstance(ident, str) or not ident:
            raise ValueError(f"invalid {label} ID")
        if ident in result:
            raise ValueError(f"duplicate {label}: {ident}")
        result[ident] = row
    return result


def _temporal_selector(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"valid_at", "known_at"}:
        raise ValueError("temporal selector requires valid_at and known_at")
    for timestamp in value.values():
        if not isinstance(timestamp, str):
            raise ValueError("temporal timestamps must be aware ISO strings")
        try:
            parsed = datetime.fromisoformat(timestamp)
        except ValueError as exc:
            raise ValueError("invalid temporal ISO timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("temporal timestamps require a timezone")


def _contains_gold_structure(text: str) -> bool:
    """Recognize label records even inside a JSON wrapper or Markdown code block."""
    decoder = json.JSONDecoder()
    signatures = (
        {"alternative_evidence_sets"},
        {"required_answer_facts"},
        {"forbidden_claims"},
        {"id", "source_id", "quote", "locator"},
        {"id", "kind", "artifact_group"},
        {"id", "principal", "expected"},
    )
    for offset, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text, offset)
        except ValueError:
            continue
        if isinstance(value, dict) and any(signature <= value.keys() for signature in signatures):
            return True
    return False


def _validate_permissions(cases, manifest, sources, evidence, objects) -> None:
    for case in _unique(cases, "permission case").values():
        if case.get("principal") not in manifest["principals"] or not isinstance(case.get("expected"), str):
            raise ValueError("invalid permission principal or expectation")
        audiences = manifest["principals"][case["principal"]]["audiences"]
        for field in ("allowed_evidence_ids", "forbidden_evidence_ids", "visible_sources"):
            values = case.get(field, [])
            if (
                not isinstance(values, list)
                or any(not isinstance(x, str) for x in values)
                or len(set(values)) != len(values)
            ):
                raise ValueError("invalid permission reference list")
            for ident in values:
                if field == "visible_sources":
                    if ident not in sources or sources[ident]["audience"] not in audiences:
                        raise ValueError("invalid permission visible source")
                elif ident not in evidence:
                    raise ValueError("missing permission evidence")
                elif (
                    field == "allowed_evidence_ids"
                    and sources[evidence[ident]["source_id"]]["audience"] not in audiences
                ):
                    raise ValueError("permission allows inaccessible evidence")
        paths = case.get("forbidden_paths", [])
        if not isinstance(paths, list):
            raise ValueError("invalid permission paths")
        for path in paths:
            if (
                not isinstance(path, dict)
                or set(path) != {"subject", "predicate", "object"}
                or path["subject"] not in objects
                or path["object"] not in objects
                or path["predicate"] not in {"INVOKES", "DEPENDS_ON", "READS", "WRITES"}
            ):
                raise ValueError("invalid permission path")


def load_fixture(directory: str | Path) -> Fixture:
    """Validate authored labels and the exact allow-list of original corpus files."""
    root = Path(directory).resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported fixture schema_version")
    questions_path = _path(root, manifest["gold"]["questions"], "gold")
    evidence_path = _path(root, manifest["gold"]["evidence"], "gold")
    questions = json.loads(questions_path.read_text())
    evidence = json.loads(evidence_path.read_text())
    objects_path = _path(root, manifest["gold"]["objects"], "gold")
    objects = _unique(json.loads(objects_path.read_text()), "object")
    permission_path = _path(root, manifest["gold"]["permission_cases"], "gold")
    permission_cases = json.loads(permission_path.read_text())
    for selector in manifest["snapshots"].values():
        _temporal_selector(selector)
    sources = manifest["sources"]
    source_by_id = _unique(sources, "source")
    evidence_by_id = _unique(evidence, "evidence")
    _unique(questions, "question")
    for obj in objects.values():
        if (
            not isinstance(obj.get("kind"), str)
            or not obj["kind"]
            or not isinstance(obj.get("artifact_group"), str)
            or not obj["artifact_group"]
        ):
            raise ValueError("invalid gold object kind or artifact group")
    if not questions or not sources or not evidence:
        raise ValueError("fixture must contain sources, evidence and questions")
    corpus = {}
    digest = hashlib.sha256()
    digest.update((root / "manifest.json").read_bytes())
    digest.update(questions_path.read_bytes())
    digest.update(evidence_path.read_bytes())
    digest.update(objects_path.read_bytes())
    digest.update(permission_path.read_bytes())
    for source in sources:
        path = _path(root, source["path"], "corpus")
        text = path.read_text()
        if _contains_gold_structure(text):
            raise ValueError(f"gold labels found in corpus: {source['path']}")
        if path.read_bytes() in tuple(
            p.read_bytes() for p in (questions_path, evidence_path, objects_path, permission_path)
        ):
            raise ValueError("gold file copied into corpus")
        if source["audience"] not in {a for p in manifest["principals"].values() for a in p["audiences"]}:
            raise ValueError("source has unknown audience")
        if not set(source["snapshots"]) <= manifest["snapshots"].keys():
            raise ValueError("source has unknown snapshot")
        corpus[source["id"]] = text
        digest.update(source["path"].encode())
        digest.update(text.encode())
    for item in evidence:
        if item.get("source_id") not in source_by_id:
            raise ValueError("missing evidence source")
        quote = item.get("quote")
        if not isinstance(quote, str) or not quote or corpus[item["source_id"]].count(quote) != 1:
            raise ValueError(f"evidence quote must occur exactly once: {item['id']}")
        if item.get("locator") != {"kind": "exact_text", "occurrence": 1}:
            raise ValueError("unsupported evidence locator")
    _validate_permissions(permission_cases, manifest, source_by_id, evidence_by_id, objects)
    groups = {}
    for q in questions:
        required = {
            "id",
            "question",
            "slice",
            "split",
            "artifact_group",
            "principal",
            "snapshot",
            "query_mode",
            "required_object_ids",
            "alternative_evidence_sets",
            "required_relation_paths",
            "required_answer_facts",
            "forbidden_claims",
            "expected_insufficiency",
            "requires",
        }
        if required - q.keys():
            raise ValueError(f"missing question fields: {sorted(required - q.keys())}")
        for field in ("requires", "required_object_ids", "required_answer_facts", "forbidden_claims"):
            values = q[field]
            if not isinstance(values, list) or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise ValueError(f"{field} must be a list of nonempty strings")
        if q["principal"] not in manifest["principals"]:
            raise ValueError("unknown principal")
        if q["snapshot"] not in manifest["snapshots"]:
            raise ValueError("unknown snapshot")
        if q["slice"] not in SLICES or q["split"] not in {"dev", "holdout"}:
            raise ValueError("invalid slice or split")
        group = q["artifact_group"]
        if group in groups and groups[group] != q["split"]:
            raise ValueError("artifact group crosses development/holdout split")
        groups[group] = q["split"]
        if q["query_mode"] not in {"current", "as_of", "compare"}:
            raise ValueError("invalid temporal query mode")
        if type(q["expected_insufficiency"]) is not bool:
            raise ValueError("expected_insufficiency must be a boolean")
        temporal = q.get("temporal")
        if q["query_mode"] == "as_of":
            _temporal_selector(temporal)
        elif q["query_mode"] == "compare":
            if not isinstance(temporal, dict) or set(temporal) != {"left", "right"}:
                raise ValueError("compare requires temporal left/right selectors")
            _temporal_selector(temporal["left"])
            _temporal_selector(temporal["right"])
        elif temporal is not None:
            raise ValueError("current query cannot include temporal selectors")
        object_ids = list(q["required_object_ids"])
        for relation in q["required_relation_paths"]:
            if relation["predicate"] not in {"INVOKES", "DEPENDS_ON", "READS", "WRITES"}:
                raise ValueError("invalid relation predicate")
            object_ids.extend([relation["subject"], relation["object"]])
        for ident in object_ids:
            if ident not in objects or objects[ident]["artifact_group"] != group:
                raise ValueError("unknown or cross-group object")
        alternatives = q["alternative_evidence_sets"]
        if not isinstance(alternatives, list) or (not alternatives and not q["expected_insufficiency"]):
            raise ValueError("invalid alternative evidence sets")
        seen = set()
        for alternative in alternatives:
            if (
                not isinstance(alternative, list)
                or not alternative
                or any(not isinstance(x, str) for x in alternative)
                or len(set(alternative)) != len(alternative)
            ):
                raise ValueError("invalid alternative evidence group")
            if frozenset(alternative) in seen:
                raise ValueError("duplicate alternative evidence group")
            seen.add(frozenset(alternative))
            for ident in alternative:
                if ident not in evidence_by_id:
                    raise ValueError(f"missing evidence: {ident}")
                source = source_by_id[evidence_by_id[ident]["source_id"]]
                if source["artifact_group"] != group:
                    raise ValueError("gold evidence crosses artifact group split")
                principal = manifest["principals"][q["principal"]]
                if source["audience"] not in principal["audiences"]:
                    raise ValueError("gold evidence forbidden to principal")
    if {q["split"] for q in questions} != {"dev", "holdout"}:
        raise ValueError("both development and holdout questions required")
    return Fixture(root, manifest, sources, evidence, questions, digest.hexdigest())


def _index(fixture: Fixture, ctx: AppContext, group: str) -> tuple[dict, dict]:
    """Run production readers, parser, chunker and indexer; labels stay outside."""
    mapping = {}
    counts = Counter()
    batches = defaultdict(list)
    for source in fixture.sources:
        if source["artifact_group"] != group or source["family"] not in LEGACY_FAMILIES:
            continue
        if source["audience"] != "public":
            continue  # unsupported policies never become public sources
        if "after" not in source["snapshots"]:
            continue
        batches[source.get("repository_id", source["id"])].append(source)
    for name, sources in sorted(batches.items()):
        source_id = ctx.store.create_source("file", name, {}, access_role_id="individual")
        docs = [doc for source in sources for doc in read_path(fixture.root / source["path"], source["path"])]
        code = extract_code(docs, source_id)
        chunks = chunk_documents(docs, ctx.config.chunk_size_chars, ctx.config.chunk_overlap_chars, code=code)
        counts.update(index_source(ctx.store, ctx.ollama, source_id, chunks, code=code, workers=1))
        counts["invokes_edges"] += sum(edge.kind == "INVOKES" for edge in code.edges)
        ctx.store.update_source(source_id, status="ready")
        for chunk in chunks:
            # A repository is indexed together so cross-file imports resolve. Match
            # both its original document locator and complete quoted bytes afterwards.
            source_ids = {
                source["id"]
                for source in sources
                if len(sources) == 1
                or chunk.title == source["path"]
                or chunk.title.startswith(source["path"] + " ")
            }
            mapping[passage_id(source_id, chunk)] = [
                e["id"] for e in fixture.evidence if e["source_id"] in source_ids and e["quote"] in chunk.text
            ]
    ctx.invalidate_graph()
    return mapping, dict(counts)


def evaluate(fixture: Fixture, ctx: AppContext, *, split: str, model_profile: str) -> dict[str, Any]:
    """Run actual legacy retrieval and label unsupported semantics as coverage gaps."""
    if split not in {"dev", "holdout"}:
        raise ValueError("unknown split")
    if ctx.store.list_sources():
        raise ValueError("evaluation requires an empty isolated store")
    questions = [q for q in fixture.questions if q["split"] == split]
    if not questions:
        raise ValueError("split has no questions")
    groups = {q["artifact_group"] for q in questions}
    mapping, counts = {}, Counter()
    for group in sorted(groups):
        group_map, group_counts = _index(fixture, ctx, group)
        mapping.update(group_map)
        counts.update(group_counts)
    rows = []
    by_slice = defaultdict(list)
    for q in questions:
        row = {
            "id": q["id"],
            "slice": q["slice"],
            "principal": q["principal"],
            "snapshot": q["snapshot"],
            "query_mode": q["query_mode"],
        }
        supported_sources = {
            s["id"]
            for s in fixture.sources
            if s["family"] in LEGACY_FAMILIES and s["audience"] == "public" and "after" in s["snapshots"]
        }
        available = {e["id"] for e in fixture.evidence if e["source_id"] in supported_sources}
        has_supported_set = any(set(group) <= available for group in q["alternative_evidence_sets"])
        missing = list(q["requires"])
        if q["query_mode"] != "current" or q["snapshot"] != "after" or q.get("temporal") is not None:
            missing.append("bitemporal")
        if q["expected_insufficiency"]:
            missing.append("insufficiency_evaluation")
        if not has_supported_set:
            missing.append("source_family_or_policy")
        if missing:
            row.update(status="coverage_gap", missing_capabilities=list(dict.fromkeys(missing)))
        else:
            principal = fixture.manifest["principals"][q["principal"]]
            trace = search(
                ctx, q["question"], {"retrieval_top_k": 20}, access=Access(rank=principal["legacy_rank"])
            )
            ranked = list(dict.fromkeys(e for p in trace.passages for e in mapping.get(p.passage_id, [])))
            candidate_evidence = [mapping.get(p.passage_id, []) for p in trace.passages]
            relevant = {e for group in q["alternative_evidence_sets"] for e in group}
            total_relevant = sum(bool(set(ids) & relevant) for ids in mapping.values())
            scores = passage_evidence_metrics(
                q["alternative_evidence_sets"], candidate_evidence, total_relevant_passages=total_relevant
            )
            graph = ctx.graph_for(Access(rank=principal["legacy_rank"]))
            candidates = []
            for rank, candidate in enumerate(trace.passages, 1):
                passage = graph.passage_by_id(candidate.passage_id)
                if passage is None:
                    raise ValueError("retrieved passage is absent from the evaluation graph")
                candidates.append(
                    {
                        "rank": rank,
                        "passage_id": passage.id,
                        "source_id": passage.source_id,
                        "title": passage.title,
                        "locator": {"kind": "legacy_chunk_ordinal", "ordinal": passage.ordinal},
                        "evidence_ids": mapping.get(passage.id, []),
                    }
                )
            row.update(
                status="evaluated",
                candidates=candidates,
                ranked_evidence_ids=ranked,
                scores=scores,
                retrieved_passage_count=len(trace.passages),
                used_code_seeds=trace.used_code_seeds,
                ranked_scores=[float(p.score) for p in trace.passages],
                candidate_evidence_ids=candidate_evidence,
                total_relevant_passages=total_relevant,
                used_dpr_fallback=trace.used_dpr_fallback,
                fallback_reason=trace.fallback_reason,
                route="dense_fallback"
                if trace.used_dpr_fallback
                else "code+hipporag"
                if trace.used_code_seeds
                else "hipporag",
                scope="legacy source-rank ACL; current static snapshot",
            )
            by_slice[q["slice"]].append(scores)
        rows.append(row)
    if not any(row["status"] == "evaluated" for row in rows):
        raise ValueError("no evaluable questions; required capabilities are not implemented")
    summary = {}
    for slice_ in SLICES:
        measured = by_slice[slice_]
        summary[slice_] = {
            "evaluated_count": len(measured),
            "question_count": sum(q["slice"] == slice_ for q in questions),
            "metric_sample_counts": {
                key: sum(key in scores for scores in measured)
                for key in {k for scores in measured for k in scores}
            },
            "metrics": {
                key: sum(s[key] for s in measured if key in s) / sum(key in s for s in measured)
                for key in {k for s in measured for k in s}
            },
        }
    families = {s["family"] for s in fixture.sources if s["artifact_group"] in groups}
    return {
        "schema_version": 1,
        "mode": "legacy",
        "split": split,
        "model_profile": model_profile,
        "purpose": "deterministic harness diagnostics; not product-quality or release evidence",
        "fixture_fingerprint": fixture.fingerprint,
        "gold_review_status": fixture.manifest["review_status"],
        "retrieval_settings": {**ctx.store.get_settings(), "retrieval_top_k": 20},
        "models": {"llm": ctx.config.llm_model, "embedding": ctx.config.embed_model},
        "budgets": {
            "retrieval_top_k": 20,
            "chunk_size_chars": ctx.config.chunk_size_chars,
            "chunk_overlap_chars": ctx.config.chunk_overlap_chars,
        },
        "question_count": len(rows),
        "evaluated_count": sum(r["status"] == "evaluated" for r in rows),
        "index_counts": dict(counts),
        "coverage_gaps": {
            family: FAMILY_GAPS[family] for family in sorted(families) if family in FAMILY_GAPS
        },
        "privacy_status": "provider ACL and adversarial permission suite not implemented; not a privacy pass",
        "release_targets": "unapproved",
        "questions": rows,
        "per_slice": summary,
    }
