"""
`/api/code/*`: the path tools over HTTP.

Five read-only endpoints answer on the caller's own slice of the graph, so the access case is the
one that matters most - `name_index` is *shared* with the full index (`graph_index.py` builds it
once and `scoped()` passes the same dict on), so every hit has to be filtered through the scoped
`idx_of` before it leaves the process. The last two tests are that rule, from both directions.

The error mapping is `analyze.py`'s: an unknown name is a 404, a name that means several things is
a 409 carrying the candidates, and a blank required argument is a 400.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hippo.ingest import pipeline
from hippo.web.app import create_app
from tests.conftest import code_sample_zip
from tests.fakes.code_fixture import write_commit_history

PLACE = "pyapp.orders.OrderService.place"
TOTAL = "pyapp.billing.total"


@pytest.fixture
def client(code_index):
    ctx, _source_id = code_index
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        yield client


@pytest.fixture
def client_with_history(code_index):
    ctx, source_id = code_index
    write_commit_history(ctx, source_id)
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        yield client


@pytest.fixture
def restricted_client(ctx):
    """
    The code sample indexed for local admins only, signed in as an individual (a lower tier).

    Returns the client; `ctx` holds the users. An individual may see no source at all here, so
    every code endpoint must behave as if the graph were empty.
    """
    ctx.store.ping()
    pipeline.add_upload(ctx, "code_sample.zip", code_sample_zip(), access_role_id="local-admin")
    ctx.jobs.wait_all(60)
    ivy = ctx.store.create_user("ivy", "secret1", "individual")
    token = ctx.store.get_user(ivy)["token"]
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        client.headers["Authorization"] = f"Bearer {token}"
        yield client


# ------------------------------------------------------------------ symbols


def test_symbols_finds_by_substring_with_display_names(client):
    rows = client.get("/api/code/symbols", params={"q": "place"}).json()
    # A substring, not a token: the Cypher rel type `PLACED_BY` matches "place" too, and saying so
    # is the point - this endpoint is a name search, not a resolver.
    assert [r["display"] for r in rows] == [PLACE, "rel_type PLACED_BY", "tests.test_orders.test_place"]
    place = rows[0]
    assert place["kind"] == "symbol" and place["code_kind"] == "method"
    assert place["lang"] == "python" and place["path"] == "pyapp/orders.py"
    assert place["line_start"] > 0 and place["line_end"] >= place["line_start"]
    assert place["qualname"] == "OrderService.place"


def test_symbols_finds_data_objects_too(client):
    rows = client.get("/api/code/symbols", params={"q": "orders"}).json()
    displays = [r["display"] for r in rows]
    assert "table orders" in displays
    assert next(r for r in rows if r["display"] == "table orders")["kind"] == "data"


def test_symbols_with_no_query_returns_nothing(client):
    assert client.get("/api/code/symbols").json() == []
    assert client.get("/api/code/symbols", params={"q": "  "}).json() == []


def test_symbols_limit_is_clamped_to_a_hundred(client):
    rows = client.get("/api/code/symbols", params={"q": "o", "limit": 5}).json()
    assert len(rows) == 5
    assert len(client.get("/api/code/symbols", params={"q": "o", "limit": 9999}).json()) <= 100


# --------------------------------------------------------------------- path


def test_path_renders_the_relations_between_two_symbols(client):
    data = client.get("/api/code/path", params={"a": "pyapp.cli.main", "b": TOTAL}).json()
    assert data["found"] is True
    assert data["a"] == "pyapp.cli.main" and data["b"] == TOTAL
    assert data["lines"] == [
        "pyapp.cli.main -[INVOKES 0.90 via_import]-> pyapp.orders.OrderService.place",
        "pyapp.orders.OrderService.place -[INVOKES 0.90 via_import]-> pyapp.billing.total",
    ]
    assert [e["kind"] for e in data["edges"]] == ["INVOKES", "INVOKES"]
    assert data["edges"][0]["omega"] == 0.9


def test_path_accepts_a_module_relative_name(client):
    data = client.get("/api/code/path", params={"a": "OrderService.place", "b": TOTAL}).json()
    assert data["a"] == PLACE and data["found"] is True


def test_path_between_unconnected_symbols_is_found_false(client):
    data = client.get("/api/code/path", params={"a": PLACE, "b": "table customers"}).json()
    assert data["found"] is False and data["edges"] == [] and data["lines"] == []


# ------------------------------------------------------------- blast radius


def test_blast_radius_returns_levels_and_rendered_lines(client):
    data = client.get("/api/code/blast-radius", params={"symbol": TOTAL, "depth": 1}).json()
    assert data["symbol"] == TOTAL and data["depth"] == 1
    assert data["levels"] == [["pyapp.billing", PLACE]]
    assert data["truncated"] is False
    assert data["lines"][0] == "Level 1: pyapp.billing, pyapp.orders.OrderService.place"


def test_blast_radius_depth_is_clamped_to_one_to_four(client):
    assert client.get("/api/code/blast-radius", params={"symbol": TOTAL, "depth": 0}).json()["depth"] == 1
    assert client.get("/api/code/blast-radius", params={"symbol": TOTAL, "depth": 99}).json()["depth"] == 4


# ------------------------------------------------------------ exception path


def test_exception_path_finds_the_raise(client):
    data = client.get(
        "/api/code/exception-path", params={"symbol": "OrderService.save", "exception": "OrderError"}
    ).json()
    assert data["found"] is True
    assert data["lines"] == [
        "pyapp.orders.OrderService.save -[RAISES 0.90 resolved]-> pyapp.store.OrderError"
    ]


def test_exception_path_for_an_unknown_exception_is_a_404(client):
    response = client.get(
        "/api/code/exception-path", params={"symbol": "OrderService.save", "exception": "NoSuchError"}
    )
    assert response.status_code == 404
    assert "NoSuchError" in response.json()["detail"]


# ------------------------------------------------------------------ history


def test_history_lists_the_commits_that_touched_a_symbol(client_with_history):
    data = client_with_history.get("/api/code/history", params={"symbol": PLACE}).json()
    assert [c["sha"] for c in data["commits"]] == ["b2b2b2b"]
    assert data["commits"][0]["subject"] == "Total the order in place"
    assert data["lines"] == ["b2b2b2b 2026-01-02 Total the order in place"]


def test_history_of_an_untouched_symbol_is_empty(client):
    data = client.get("/api/code/history", params={"symbol": PLACE}).json()
    assert data["commits"] == [] and data["lines"] == []


# ------------------------------------------------------------- the mapping


def test_an_unknown_symbol_is_a_404(client):
    response = client.get("/api/code/blast-radius", params={"symbol": "no_such_thing"})
    assert response.status_code == 404
    assert "no_such_thing" in response.json()["detail"]


def test_an_ambiguous_symbol_is_a_409_with_its_candidates(client):
    response = client.get("/api/code/history", params={"symbol": "log"})
    assert response.status_code == 409
    body = response.json()
    assert body["candidates"] == [
        "pyapp.orders.OrderService.log",
        "pyapp.store.Base.log",
        "tsapp.models.base.Base.log",
    ]
    assert "could mean any of" in body["detail"]


def test_a_blank_argument_is_a_400(client):
    assert client.get("/api/code/path", params={"a": "  ", "b": TOTAL}).status_code == 400
    assert client.get("/api/code/blast-radius", params={"symbol": ""}).status_code == 400
    assert (
        client.get("/api/code/exception-path", params={"symbol": PLACE, "exception": " "}).status_code == 400
    )


# --------------------------------------------------------------- who may see


def test_a_restricted_caller_cannot_reach_a_hidden_sources_symbol(restricted_client):
    """`name_index` is shared with the full index, so this is the endpoint that would leak it."""
    assert restricted_client.get("/api/code/symbols", params={"q": "place"}).json() == []
    for path, params in [
        ("/api/code/blast-radius", {"symbol": PLACE}),
        ("/api/code/history", {"symbol": PLACE}),
        ("/api/code/exception-path", {"symbol": "OrderService.save", "exception": "OrderError"}),
        ("/api/code/path", {"a": PLACE, "b": TOTAL}),
    ]:
        assert restricted_client.get(path, params=params).status_code == 404, path
