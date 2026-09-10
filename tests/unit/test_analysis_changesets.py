"""changesets: validate, save, describe and apply graph edits through the store."""

from __future__ import annotations

import pytest

from hippo.analysis import changesets
from hippo.analysis.changesets import VALID_OPS, apply, describe, save, validate
from hippo.analysis.simulate import Overrides
from hippo.ask import search
from hippo.codegraph.model import commit_id, data_id, symbol_id
from hippo.hipporag.indexer import Chunk, index_source
from hippo.hipporag.text import entity_id
from tests.fakes.code_fixture import write_commit_history

QUESTION = "In which state is the company founded by Priya Natarajan headquartered?"


def index_sample(ctx, sample_text: str) -> str:
    """Index samples/acme_robotics.md as one passage per '## ' section. Returns the source id."""
    source_id = ctx.store.create_source("sample", "Acme Robotics")
    chunks = []
    for ordinal, section in enumerate(sample_text.split("## ")[1:]):
        title, _, body = section.partition("\n")
        chunks.append(Chunk(ordinal, title.strip(), body.strip()))
    index_source(ctx.store, ctx.ollama, source_id, chunks, workers=2)
    ctx.store.update_source(source_id, status="ready")
    return source_id


@pytest.fixture
def indexed(ctx, sample_text) -> str:
    return index_sample(ctx, sample_text)


# ---------------------------------------------------------------- validate


def test_valid_ops_pass():
    validate(
        [
            {"op": "set_setting", "name": "damping", "value": 0.7},
            {"op": "set_setting", "name": "node_specificity", "value": False},
            {"op": "set_edge_weight", "a": "entity-a", "b": "passage-b", "weight": 0},
            {"op": "add_synonym", "a": "entity-a", "b": "entity-b", "score": 0.9},
            {"op": "set_node_boost", "entity_id": "entity-a", "boost": 1.5},
        ]
    )
    assert VALID_OPS == {"set_setting", "set_edge_weight", "add_synonym", "set_node_boost"}


@pytest.mark.parametrize(
    "ops, message",
    [
        ("not a list", "must be a list"),
        ([], "at least one op"),
        (["junk"], "must be an object"),
        ([{"op": "explode"}], "unknown op"),
        ([{"op": "set_setting", "name": "damping"}], "exactly the keys"),
        ([{"op": "set_setting", "name": "damping", "value": 0.7, "extra": 1}], "exactly the keys"),
        ([{"op": "set_setting", "name": "nope", "value": 1}], "unknown setting"),
        ([{"op": "set_setting", "name": "damping", "value": "0.7"}], "must be a number"),
        ([{"op": "set_setting", "name": "damping", "value": True}], "must be a number"),
        ([{"op": "set_setting", "name": "node_specificity", "value": 1}], "true or false"),
        ([{"op": "set_edge_weight", "a": "x", "b": "x", "weight": 1}], "two different nodes"),
        ([{"op": "set_edge_weight", "a": "", "b": "y", "weight": 1}], "non-empty node id"),
        ([{"op": "set_edge_weight", "a": "x", "b": "y", "weight": -1}], "at least 0"),
        ([{"op": "add_synonym", "a": "x", "b": "y", "score": 1.5}], "at most 1"),
        ([{"op": "add_synonym", "a": "x", "b": "y", "score": 0}], "above 0"),
        ([{"op": "set_node_boost", "entity_id": 42, "boost": 1}], "non-empty node id"),
        ([{"op": "set_node_boost", "entity_id": "x", "boost": None}], "must be a number"),
    ],
)
def test_junk_ops_are_refused(ops, message):
    with pytest.raises(ValueError, match=message):
        validate(ops)


def test_error_names_the_offending_op():
    good = {"op": "set_setting", "name": "damping", "value": 0.7}
    with pytest.raises(ValueError, match="op 2:"):
        validate([good, {"op": "nope"}])


# ------------------------------------------------------------ save/describe


def test_save_stores_a_draft_and_refuses_junk(ctx):
    ops = [{"op": "set_setting", "name": "damping", "value": 0.7}]
    changeset_id = save(ctx, "  lower damping ", ops, from_result_id="res-1", note="try it")
    row = ctx.store.get_changeset(changeset_id)
    assert row["name"] == "lower damping"
    assert row["status"] == "draft" and row["applied_at"] is None
    assert row["ops"] == ops and row["note"] == "try it" and row["from_result_id"] == "res-1"

    with pytest.raises(ValueError):
        save(ctx, "", ops)
    with pytest.raises(ValueError):
        save(ctx, "bad", [{"op": "nope"}])
    assert len(ctx.store.list_changesets()) == 1


def test_describe_resolves_names(ctx, indexed):
    boulder, colorado = entity_id("boulder"), entity_id("colorado")
    company = next(p for p in ctx.store.passages_for_source(indexed) if p["title"] == "The company")
    lines = describe(
        ctx,
        [
            {"op": "set_setting", "name": "damping", "value": 0.7},
            {"op": "set_node_boost", "entity_id": boulder, "boost": 1.5},
            {"op": "add_synonym", "a": boulder, "b": colorado, "score": 0.9},
            {"op": "set_edge_weight", "a": boulder, "b": company["id"], "weight": 2.0},
            {"op": "set_edge_weight", "a": boulder, "b": company["id"], "weight": 0},
            {"op": "set_node_boost", "entity_id": "entity-unknown", "boost": 1},
        ],
    )
    assert lines == [
        "Set damping to 0.7",
        "Boost 'boulder' x1.5",
        "Link 'boulder' ~ 'colorado' (0.9)",
        "Set edge 'boulder' - 'The company' weight to 2",
        "Remove the edge 'boulder' - 'The company'",
        "Boost 'entity-unknown' x1",
    ]


# ------------------------------------------------------------------- apply


def test_overrides_to_ops_are_valid_and_apply_reaches_the_graph(ctx, indexed):
    before = search(ctx, QUESTION)
    boulder = entity_id("boulder")
    company_id = next(p.passage_id for p in before.passages if p.title == "The company")
    overrides = Overrides(
        settings={"damping": 0.7},
        node_boosts={boulder: 2.5},
        edge_edits=[{"a": boulder, "b": company_id, "weight": 3.0}],
        force_exclude=["fact-whatever"],  # per-question: must not become an op
    )
    ops = overrides.to_ops()
    validate(ops)
    assert len(ops) == 3

    version_before = ctx.store.graph_version()
    graph_before = ctx.graph()
    changeset_id = save(ctx, "boost boulder", ops)
    result = apply(ctx, changeset_id)

    # The store has the edits.
    assert ctx.store.get_settings()["damping"] == 0.7
    assert ctx.store.get_entities([boulder])[0]["boost"] == 2.5
    assert {"a": min(boulder, company_id), "b": max(boulder, company_id), "weight": 3.0} in (
        ctx.store.load_tuned_edges()
    )
    assert ctx.store.get_changeset(changeset_id)["status"] == "applied"
    assert ctx.store.get_changeset(changeset_id)["applied_at"]

    # The graph version moved on, so ctx.graph() reloads and sees the boost and the tuned edge.
    assert ctx.store.graph_version() == version_before + 1
    assert result["graph_version"] == version_before + 1
    graph_after = ctx.graph()
    assert graph_after is not graph_before
    assert graph_after.version == version_before + 1
    assert graph_after.entity_boost[graph_after.idx_of[boulder]] == 2.5
    edge = graph_after.edge_between(graph_after.idx_of[boulder], graph_after.idx_of[company_id])
    assert edge.tuned == 3.0 and edge.weight == 3.0 and "tuned" in edge.kinds

    # What apply reports.
    assert result["changeset_id"] == changeset_id and result["applied"] == 3
    assert result["settings"] == {"damping": 0.7}
    assert result["boosts"] == [{"entity_id": boulder, "boost": 2.5}]
    assert result["edges"] == [{"a": boulder, "b": company_id, "weight": 3.0}]
    assert result["synonyms"] == []
    assert result["descriptions"][0] == "Set damping to 0.7"
    assert result["descriptions"][1] == "Boost 'boulder' x2.5"

    # And a search afterwards uses the new settings.
    after = search(ctx, QUESTION)
    assert after.settings["damping"] == 0.7
    assert after.graph_version == version_before + 1


def test_apply_writes_a_manual_synonym(ctx, indexed):
    boulder, colorado = entity_id("boulder"), entity_id("colorado")
    changeset_id = save(ctx, "link", [{"op": "add_synonym", "a": boulder, "b": colorado, "score": 0.9}])
    result = apply(ctx, changeset_id)
    assert result["synonyms"] == [{"a": boulder, "b": colorado, "score": 0.9}]
    rows = [r for r in ctx.store.load_synonyms() if {r["a"], r["b"]} == {boulder, colorado}]
    assert rows and rows[0]["score"] == 0.9 and rows[0]["manual"] is True
    graph = ctx.graph()
    edge = graph.edge_between(graph.idx_of[boulder], graph.idx_of[colorado])
    assert "synonym" in edge.kinds


def test_apply_unknown_changeset_fails_loudly(ctx):
    with pytest.raises(ValueError, match="no changeset"):
        apply(ctx, "missing")


def test_apply_refuses_junk_that_got_into_the_store(ctx):
    changeset_id = ctx.store.create_changeset("junk", [{"op": "nope"}])
    with pytest.raises(ValueError):
        changesets.apply(ctx, changeset_id)
    assert ctx.store.get_changeset(changeset_id)["status"] == "draft"


def test_describe_resolves_symbol_data_and_commit_ids(code_index):
    """
    `_node_names` looked in `get_entities` and `get_passages` only, so an op on a symbol printed
    its raw id - and the Changesets page is where a boost or a synonym on a symbol is reviewed
    before it is applied to everyone's graph.
    """
    ctx, source_id = code_index
    write_commit_history(ctx, source_id)
    place = symbol_id(source_id, "pyapp/orders.py", "OrderService.place", "method")
    orders = data_id(source_id, "table", "orders")
    commit = commit_id(source_id, "b2b2b2b")

    assert describe(
        ctx,
        [
            {"op": "set_node_boost", "entity_id": place, "boost": 2.0},
            {"op": "add_synonym", "a": place, "b": orders, "score": 0.9},
            {"op": "set_edge_weight", "a": commit, "b": place, "weight": 0},
            {"op": "set_node_boost", "entity_id": "symbol-unknown", "boost": 1},
        ],
    ) == [
        "Boost 'pyapp.orders.OrderService.place' x2",
        "Link 'pyapp.orders.OrderService.place' ~ 'table orders' (0.9)",
        "Remove the edge 'b2b2b2b' - 'pyapp.orders.OrderService.place'",
        "Boost 'symbol-unknown' x1",
    ]
