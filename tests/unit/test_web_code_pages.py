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

from hippo import ask as ask_service
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
    # The summary line counts the one lexical (identifier) seed that anchored this question, not
    # just entity seeds - a stack-trace question that names no entity used to read as "0 seed
    # entities" even though symbol seeds drove the whole answer (E1 territory-updater surprise).
    assert (
        "Found through the graph: 0 fact(s) kept, 0 seed entities, 1 symbol seed(s), PPR damping" in page.text
    )


def test_a_prose_question_gets_no_code_graph_card(client):
    page = client.post("/ask", data={"question": PROSE})
    assert page.status_code == 200
    assert "Code graph" not in page.text
    # No lexical symbol seed fired (dense seeds don't count), so the summary line's wording is
    # byte-identical to the pre-existing prose-only phrasing: no "symbol seed(s)" clause at all.
    assert "Found through the graph: 1 fact(s) kept, 2 seed entities, PPR damping" in page.text
    assert "symbol seed" not in page.text


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
    assert "<h2>Paths" in page
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


def test_a_prose_question_says_no_lexical_anchor_and_has_no_paths(client):
    """
    A prose question still collects *dense* seed symbols once a repository is indexed alongside,
    so the table is not empty - and hiding it would be the wrong lie on the page whose whole job
    is explaining what the search did. What must be unambiguous is that nothing lexical fired:
    the footer says so, and there is no Paths section, because paths are gated on that (Ruling 1a).
    """
    page = analyze_page(client, PROSE)
    assert "A lexical anchor was found: <b>no</b>" in page
    assert "<h2>Paths" not in page
    # The knobs stay: they are settings, and a prose question may still want the scale at 0.
    assert 'id="ov-code_structural_scale"' in page


def test_a_code_question_says_a_lexical_anchor_was_found(client):
    assert "A lexical anchor was found: <b>yes</b>" in analyze_page(client, PLACE)


def test_a_dense_seed_names_the_passage_it_came_from(client, coded):
    """
    A dense seed's `matched_by` is the passage id it was pulled from, not a token. Printing the
    raw `passage-<hash>` in the table's "From" column tells a reader nothing; the title does.
    """
    ctx, _source_id = coded
    page = analyze_page(client, PLACE)
    # The ids do belong in the <script id="analyze-data"> block the graph picture reads; this is
    # about the table a person looks at, so scope the assertion to it.
    table = page.split("seed symbols", 1)[1].split("</table>", 1)[0]
    dense = [s for s in ask_service.search(ctx, PLACE).seed_symbols if s.how == "dense" and s.kept]
    assert dense, "the fixture's code passages score high enough to seed densely"
    for seed in dense:
        title = ctx.graph().passage_by_id(seed.matched_by).title
        assert seed.matched_by not in table, f"raw id {seed.matched_by} leaked into the table"
        assert title.split(" :: ")[0] in table, title
