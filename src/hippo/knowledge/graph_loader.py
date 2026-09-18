"""Select native generations before GraphIndex allocates vectors and statistics.

This is a persistence adapter, not an authorization boundary. The caller supplies
logical source IDs and their selected generation, and must separately authorize
the resulting graph. Canonical managed evidence is projected by projection.py.
"""

from __future__ import annotations

from collections import Counter

from hippo.hipporag.graph_index import GraphIndex, _rows_with_good_vectors
from hippo.store.code import SPECIFICITY_KINDS


class _GraphRows:
    """Expose only the materialized, selected loading methods to GraphIndex."""

    def __init__(self, rows: dict[str, list[dict]]):
        self.rows = rows

    def __getattr__(self, name):
        if name in self.rows:
            return lambda: self.rows[name]
        raise AttributeError(name)


def load_generation_graph(
    store,
    *,
    generations: dict[str, str],
    legacy_source_ids: frozenset[str],
    version: int,
    trusted_untagged_generations: dict[str, str] | None = None,
) -> GraphIndex:
    """Load one selected generation per logical source, plus untagged legacy rows.

    A managed source never gains untagged rows implicitly. Compatibility callers
    may explicitly vouch for those rows using a source-to-generation mapping;
    that trust expires when the selected generation changes. IDs and file paths
    are not interpreted as source or generation identity.
    """
    trusted = trusted_untagged_generations or {}

    def selected(row):
        source_id = row.get("source_id")
        generation_id = row.get("generation_id")
        if source_id in generations:
            expected = generations[source_id]
            return generation_id == expected or (generation_id is None and trusted.get(source_id) == expected)
        return source_id in legacy_source_ids and generation_id is None

    rows = {}
    for name in ("passages", "symbols", "data_objects", "commits"):
        rows[f"load_{name}"] = [dict(row) for row in getattr(store, f"load_{name}")() if selected(row)]
    for row in rows["load_passages"]:
        # View-aware native IDs remain independent candidates even when their
        # original span is shared. Only authorized projection resolves lineage.
        row.setdefault("retrieval_view_id", None)

    # GraphIndex uses the majority dimension. Run its vector eligibility rule on
    # the selected passages before determining support, so rejected passages
    # cannot leave behind mentions, entities, facts or aggregate counts either.
    rows["load_passages"] = _rows_with_good_vectors(rows["load_passages"], "passage")
    passage_ids = {row["id"] for row in rows["load_passages"]}
    entities = {row["id"]: dict(row) for row in store.load_entities()}
    facts = []
    for row in store.load_facts():
        support = list(dict.fromkeys(pid for pid in row.get("passage_ids") or [] if pid in passage_ids))
        if support and row["subject_id"] in entities and row["object_id"] in entities:
            facts.append({**row, "passage_ids": support})
    rows["load_facts"] = _rows_with_good_vectors(facts, "fact")
    rows["load_mentions"] = [
        dict(row)
        for row in store.load_mentions()
        if row["passage_id"] in passage_ids and row["entity_id"] in entities
    ]

    supported_entities = {row["entity_id"] for row in rows["load_mentions"]}
    fact_weights = Counter()
    for row in rows["load_facts"]:
        a, b = row["subject_id"], row["object_id"]
        supported_entities.update((a, b))
        if a != b:
            fact_weights[tuple(sorted((a, b)))] += len(row["passage_ids"])
    rows["load_fact_edges"] = [
        {"a": a, "b": b, "weight": count} for (a, b), count in sorted(fact_weights.items())
    ]
    mention_counts = Counter()
    for entity_id, _passage_id in {(row["entity_id"], row["passage_id"]) for row in rows["load_mentions"]}:
        mention_counts[entity_id] += 1
    rows["load_entities"] = [
        {**row, "passage_count": mention_counts[identity]}
        for identity, row in entities.items()
        if identity in supported_entities
    ]

    node_ids = (
        passage_ids
        | supported_entities
        | {row["id"] for name in ("symbols", "data_objects", "commits") for row in rows[f"load_{name}"]}
    )
    for name, a, b in (
        ("code_edges", "a", "b"),
        ("synonyms", "a", "b"),
        ("tuned_edges", "a", "b"),
        ("definitions", "node_id", "passage_id"),
        ("refers_to", "passage_id", "node_id"),
        ("modifies", "commit_id", "symbol_id"),
        ("precedes", "a", "b"),
    ):
        rows[f"load_{name}"] = [
            dict(row) for row in getattr(store, f"load_{name}")() if row[a] in node_ids and row[b] in node_ids
        ]

    degrees = Counter(
        row["b"]
        for row in rows["load_code_edges"]
        if row["kind"] in SPECIFICITY_KINDS and row["a"] != row["b"]
    )
    for name in ("symbols", "data_objects", "commits"):
        for row in rows[f"load_{name}"]:
            row["in_degree"] = degrees[row["id"]]

    return GraphIndex.load(_GraphRows(rows), version=version)
