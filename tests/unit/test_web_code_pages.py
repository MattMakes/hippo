"""
Ask, Source and Analyze rendered over a memory that holds a code graph.

The Graph page's JSON is `test_web_graph_code.py`; this file is about what the three HTML pages
show once a question anchors on a symbol. Templates are compile-checked by `test_web_busy_pages.py`,
so what is worth asserting here is the content: the Code graph card, the seed-symbol chips and
table, the paths in the S2.15 grammar, the per-passage code details and the `meta["code"]` summary.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hippo.web.app import create_app
from tests.fakes.code_fixture import write_commit_history

PLACE = "What does pyapp.orders.OrderService.place do?"
PROSE = "Where is Acme Robotics headquartered?"


@pytest.fixture
def coded(code_index):
    """The fixture tree plus the three commits, as `(ctx, source_id)`."""
    ctx, source_id = code_index
    write_commit_history(ctx, source_id)
    return ctx, source_id


@pytest.fixture
def client(coded):
    ctx, _source_id = coded
    # The default base_url would send "Host: testserver", which the guard refuses like any foreign name.
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        yield client


# --------------------------------------------------------------------- ask


def test_the_answer_card_shows_the_code_graph_block_and_the_seed_chips(client):
    page = client.post("/ask", data={"question": PLACE})
    assert page.status_code == 200

    assert "Code graph" in page.text
    # The block itself, in the S2.15 grammar. Jinja escapes the arrow, so match the head of a line.
    assert "-[INVOKES 1.00 same_file]-" in page.text
    assert "Commits: b2b2b2b" in page.text
    # The chips name the symbols the question anchored on, and say how.
    assert "pyapp.orders.OrderService.place" in page.text
    assert "identifier" in page.text


def test_a_prose_question_gets_no_code_graph_card(client):
    page = client.post("/ask", data={"question": PROSE})
    assert page.status_code == 200
    assert "Code graph" not in page.text


# ------------------------------------------------------------------ source


def test_the_source_header_summarises_what_the_code_pass_found(client, coded):
    _ctx, source_id = coded
    page = client.get(f"/sources/{source_id}")
    assert page.status_code == 200
    assert "Code graph" in page.text
    for label in ("symbols", "data objects", "relations", "files parsed"):
        assert label in page.text, label
    # The raw meta dict must not also print as a blob in the Details card.
    assert "'files_parsed'" not in page.text and "&#39;files_parsed&#39;" not in page.text


def test_a_symbol_passage_carries_its_corner_of_the_code_graph(client, coded):
    ctx, source_id = coded
    passages = ctx.store.passages_for_source(source_id, limit=500)
    place = next(p for p in passages if "OrderService.place" in p["title"])
    page = client.get(f"/sources/{source_id}?page={1 + passages.index(place) // 25}")
    assert page.status_code == 200

    body = page.text.split(place["title"], 1)[1]
    assert "In the code graph" in body
    assert "-[INVOKES 1.00 same_file]-" in body  # its own out-edges
    assert "tests.test_orders.test_place" in body  # Tests:
    assert "b2b2b2b" in body  # Commits:


# ----------------------------------------------------------------- analyze


def analyze_page(client, question: str):
    redirect = client.post("/analyze", data={"question": question}, follow_redirects=False)
    assert redirect.status_code == 303, redirect.text
    page = client.get(redirect.headers["location"])
    assert page.status_code == 200, page.text
    return page.text


def test_the_analyze_page_shows_the_seed_symbols_and_the_paths(client):
    page = analyze_page(client, PLACE)

    assert "seed symbols" in page.lower()
    assert "pyapp.orders.OrderService.place" in page
    assert "identifier" in page  # the `how` column
    assert "Paths" in page
    assert "-[INVOKES 1.00 same_file]-" in page  # S2.15, rendered by paths.render_triples


def test_the_simulate_panel_offers_the_code_knobs_but_not_the_ingest_ones(client):
    page = analyze_page(client, PLACE)
    for simulatable in ("code_seed_weight", "code_structural_scale", "code_theta"):
        assert f'id="ov-{simulatable}"' in page, simulatable
    for ingest_only in ("code_history_depth", "code_git_timeout_s", "code_history_total_s"):
        assert f'id="ov-{ingest_only}"' not in page, ingest_only


def test_the_code_knobs_take_their_bounds_from_setting_rules(client):
    page = analyze_page(client, PLACE)
    for key, low, high in [("code_seed_weight", 0.0, 10.0), ("code_structural_scale", 0.0, 3.0)]:
        field = page.split(f'id="ov-{key}"', 1)[1].split(">", 1)[0]
        assert f'min="{low}"' in field and f'max="{high}"' in field, (key, field)


def test_a_prose_question_hides_the_code_sections(client):
    page = analyze_page(client, PROSE)
    assert "Seed symbols" not in page
    # The knobs stay: they are settings, and a prose question may still want the scale at 0.
    assert 'id="ov-code_structural_scale"' in page
