"""
The Graph page over a memory that holds a code graph.

`test_web_base.py` proves the endpoints do not fall over when code is present; this file is about
what they *say*. Every node kind has its own shape, and the sharp one is `node_details`, whose
else-branch used to read `facts`/`passage_count`/`boost` off anything that was not a passage - so a
symbol came back as a wrong-shaped 200 that the side panel rendered as a mis-labelled entity.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hippo.web.app import create_app
from tests.fakes.code_fixture import write_commit_history


@pytest.fixture
def client(code_index):
    ctx, _source_id = code_index
    # The default base_url would send "Host: testserver", which the guard refuses like any foreign name.
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        yield client


def nodes_of(client, kind: str) -> dict[str, dict]:
    """Every node of one kind from /api/graph/full, by id."""
    out = client.get(f"/api/graph/full?kind={kind}&limit=8000")
    assert out.status_code == 200, out.text
    return {n["id"]: n for n in out.json()["nodes"]}


def node_named(client, kind: str, label: str) -> dict:
    found = [n for n in nodes_of(client, kind).values() if n["label"] == label]
    assert found, (
        f"no {kind} labelled {label!r} in {sorted(n['label'] for n in nodes_of(client, kind).values())}"
    )
    return found[0]


# ------------------------------------------------------------------- tiers


def test_a_symbol_shows_its_own_source_tier_not_everyone(client, code_index):
    """
    `tiers_of` built `node_tier` from passages and then from `e.mention` edges only. A symbol has
    no MENTIONS edge (D1), so it fell through to the "Everyone" default and the Graph page showed
    a restricted repository's symbols with a public badge. Not a leak - the index is already
    scoped - but a visibly wrong one.
    """
    ctx, source_id = code_index
    ctx.store.set_source_access(source_id, "local-admin")
    ctx.invalidate_graph()

    symbols = nodes_of(client, "symbol")
    assert symbols, "the fixture indexes symbols"
    assert {n["tier"] for n in symbols.values()} == {"Local admin"}
    assert {n["tier_rank"] for n in symbols.values()} == {20}
    # ... and the passages of the same source, which already worked, still agree.
    assert {n["tier"] for n in nodes_of(client, "passage").values()} == {"Local admin"}


# -------------------------------------------------------------- full graph


def test_the_node_list_describes_each_code_kind_instead_of_calling_it_an_entity(client, code_index):
    ctx, source_id = code_index
    write_commit_history(ctx, source_id)

    symbol = node_named(client, "symbol", "pyapp.orders.OrderService.place")
    assert symbol["code_kind"] == "method" and symbol["path"] == "pyapp/orders.py"
    assert symbol["lang"] == "python" and symbol["source_id"] == source_id
    assert "passage_count" not in symbol, "a symbol is not an entity and has no passage count"
    assert "community_label" in symbol  # the community colour mode reads this

    data = node_named(client, "data", "table orders")
    assert data["code_kind"] == "table" and "passage_count" not in data

    commit = node_named(client, "commit", "c3c3c3c")
    assert commit["code_kind"] == "commit" and "passage_count" not in commit

    entity = next(iter(nodes_of(client, "entity").values()))
    assert "passage_count" in entity, "entities keep the count they always had"


def test_filtering_by_source_keeps_that_source_own_code_nodes(client, code_index):
    ctx, source_id = code_index
    other = ctx.store.create_source("text", "Somewhere else")
    ctx.invalidate_graph()

    mine = client.get(f"/api/graph/full?kind=symbol&source={source_id}&limit=8000").json()
    assert mine["nodes"] and all(n["source_id"] == source_id for n in mine["nodes"])
    assert client.get(f"/api/graph/full?kind=symbol&source={other}").json()["nodes"] == []


# ------------------------------------------------------------- one node


def details(client, node_id: str) -> dict:
    response = client.get(f"/api/graph/node/{node_id}")
    assert response.status_code == 200, response.text
    return response.json()


def test_a_symbol_returns_a_symbol_shaped_panel(client):
    """The else-branch used to answer with `facts`/`passage_count`/`boost` for anything that was
    not a passage, so a symbol came back looking like an entity with an empty fact list."""
    place = node_named(client, "symbol", "pyapp.orders.OrderService.place")
    panel = details(client, place["id"])

    assert panel["kind"] == "symbol"
    assert panel["code_kind"] == "method" and panel["lang"] == "python"
    assert panel["path"] == "pyapp/orders.py"
    assert (panel["line_start"], panel["line_end"]) == (16, 23)
    assert panel["signature"] and "Place an order" in panel["doc"]
    for entity_shaped in ("passage_count", "boost", "fact_count"):
        assert entity_shaped not in panel, entity_shaped

    callees = {(row["kind"], row["b_name"]): row for row in panel["callees"]}
    assert callees[("INVOKES", "pyapp.billing.total")]["omega"] == 0.9
    assert callees[("INVOKES", "pyapp.orders.OrderService.log")]["omega"] == 1.0
    callers = {(row["kind"], row["a_name"]) for row in panel["callers"]}
    assert ("INVOKES", "pyapp.cli.main") in callers
    assert ("CONTAINS", "pyapp.orders.OrderService") in callers
    assert [t["name"] for t in panel["tests"]] == ["tests.test_orders.test_place"]
    # Both lists are sorted (kind, target, source): code_out/code_in are load order and Neo4j
    # promises none, so an unsorted panel would differ per backend.
    assert panel["callees"] == sorted(panel["callees"], key=lambda r: (r["kind"], r["b_name"], r["a_name"]))
    assert panel["callers"] == sorted(panel["callers"], key=lambda r: (r["kind"], r["b_name"], r["a_name"]))
    assert panel["defined_in"], "the passage the symbol is written down in"


def test_a_data_object_returns_its_readers_and_writers(client):
    orders = node_named(client, "data", "table orders")
    panel = details(client, orders["id"])

    assert panel["kind"] == "data" and panel["code_kind"] == "table"
    assert panel["dialect"]
    assert "pyapp.orders.OrderService.list_open" in {row["a_name"] for row in panel["readers"]}
    assert "pyapp.orders.OrderService.save" in {row["a_name"] for row in panel["writers"]}
    assert all(row["kind"] == "READS" for row in panel["readers"])
    assert all(row["kind"] == "WRITES" for row in panel["writers"])
    assert "passage_count" not in panel


def test_a_commit_returns_its_message_and_the_symbols_it_touched(client, code_index):
    ctx, source_id = code_index
    write_commit_history(ctx, source_id)

    commit = node_named(client, "commit", "b2b2b2b")
    panel = details(client, commit["id"])

    assert panel["kind"] == "commit"
    assert panel["sha"] == "b2b2b2b" and panel["author"] == "A Committer"
    assert panel["date"].startswith("2026-01-02") and panel["message"] == "Total the order in place"
    assert [row["b_name"] for row in panel["modifies"]] == ["pyapp.orders.OrderService.place"]
    assert "passage_count" not in panel


def test_an_entity_and_a_passage_keep_the_panels_they_always_had(client):
    entity = next(iter(nodes_of(client, "entity").values()))
    panel = details(client, entity["id"])
    assert panel["kind"] == "entity"
    assert {"passage_count", "boost", "facts", "fact_count", "passages"} <= set(panel)

    passage = next(iter(nodes_of(client, "passage").values()))
    panel = details(client, passage["id"])
    assert panel["kind"] == "passage"
    assert {"title", "source_id", "source_name", "ordinal", "text", "facts"} <= set(panel)


# ------------------------------------------------------------ the toolbar


def test_the_toolbar_can_filter_and_colour_by_the_new_kinds(client):
    page = client.get("/graph")
    assert page.status_code == 200
    kinds = page.text.split('id="g-kind"', 1)[1].split("</select>", 1)[0]
    for kind in ("entity", "passage", "symbol", "data", "commit"):
        assert f'value="{kind}"' in kinds, kind
    colours = page.text.split('id="g-color"', 1)[1].split("</select>", 1)[0]
    for mode in ("tier", "kind", "source", "community"):
        assert f'value="{mode}"' in colours, mode
