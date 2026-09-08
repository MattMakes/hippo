"""
The other half of the code pages: the branches that fire when the answer is *not* about code.

`test_web_code_pages.py` pins what a code question shows on Ask, Source and Analyze. What breaks
quietly is the negative and the legacy side of the same rendering, so this file covers those: a
trace stored before the code graph existed, a question whose only code seeds are dense ones
(Ruling 1a - they must not grow a Code graph card), a prose passage sitting inside a code source,
a commit passage, and a caller who may not see the source at all.

The two `code_details_for` assertions are made against the function rather than against the page
text: the dict is keyed by passage id, so "this passage has details and that one does not" is
exact, where slicing HTML at a title is not.
"""

from __future__ import annotations

from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient

from hippo import ask as ask_service
from hippo.access import Access, Principal
from hippo.hipporag.answerer import Answer
from hippo.hipporag.retriever import trace_from_dict
from hippo.web.app import create_app
from hippo.web.render import templates
from hippo.web.routes import sources as sources_routes
from tests.fakes.code_fixture import write_commit_history

PLACE = "What does pyapp.orders.OrderService.place do?"
PROSE = "Where is Acme Robotics headquartered?"
PLACE_TITLE = "pyapp/orders.py :: pyapp.orders.OrderService.place (lines 16-23)"
README_TITLE = "Code sample"  # README.md's only section: prose, inside a source full of code

# Everything WP3 added to the Trace and the Answer. A row stored before it carries none of them,
# and `trace_from_dict` / `Answer(**row)` default them all - the template must survive that.
WP3_TRACE_KEYS = (
    "seed_symbols",
    "used_code_seeds",
    "question_prose",
    "question_code",
    "paths",
    "tests",
    "history",
    "select",
    "expansions",
)


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


def render_answer(**context) -> str:
    """`partials/answer.html` on its own - it extends no layout, so it needs no Request."""
    return templates.get_template("partials/answer.html").render(**context)


def article_containing(html: str, title: str) -> str:
    """The one `<article>` of the passage list whose header carries `title`."""
    blocks = [block for block in html.split("<article") if title in block]
    assert blocks, f"no article for {title!r}"
    return blocks[0]


# --------------------------------------------------------------------- ask


def test_an_answer_stored_before_the_code_graph_still_renders(coded):
    """A trace written before WP3 has no `used_code_seeds` and no `seed_symbols` at all."""
    ctx, _source_id = coded
    trace, answer = ask_service.ask(ctx, PLACE)

    old_trace = trace_from_dict({k: v for k, v in trace.to_dict().items() if k not in WP3_TRACE_KEYS})
    old_answer = Answer(**{k: v for k, v in asdict(answer).items() if k != "context_block"})
    html = render_answer(question=PLACE, trace=old_trace, answer=old_answer, passages=[], trace_key="k")

    assert "Answer" in html and old_answer.answer in html
    assert "Code graph" not in html, "an old answer has no block and named no symbols"


def test_dense_only_code_seeds_do_not_grow_a_code_graph_card(client, coded):
    """Ruling 1a: a dense seed is admitted on any question and flips nothing, card included."""
    ctx, _source_id = coded
    trace = ask_service.search(ctx, PROSE)
    # The precondition the gate exists for: a prose question over a code memory *does* reach
    # symbols, so gating the card on "there are seed symbols" would put one on every answer.
    assert [s for s in trace.seed_symbols if s.kept], "expected dense code seeds on a prose question"
    assert {s.how for s in trace.seed_symbols} == {"dense"}
    assert trace.used_code_seeds is False

    page = client.post("/ask", data={"question": PROSE})
    assert page.status_code == 200
    assert "Code graph" not in page.text


# ------------------------------------------------------------------ source


def test_only_the_passages_that_define_code_carry_code_details(coded):
    ctx, source_id = coded
    passages = ctx.store.passages_for_source(source_id, limit=500)
    details = sources_routes.code_details_for(ctx, Principal.open(), passages)
    by_title = {p["title"]: p["id"] for p in passages}

    assert by_title[PLACE_TITLE] in details, "a symbol passage has its corner of the graph"
    assert by_title[README_TITLE] not in details, "prose inside a code source has none"
    assert set(details) <= {p["id"] for p in passages}


def test_a_prose_passage_shows_no_code_graph_details(client, coded):
    ctx, source_id = coded
    passages = ctx.store.passages_for_source(source_id, limit=500)
    readme = next(p for p in passages if p["title"] == README_TITLE)
    page = client.get(f"/sources/{source_id}?page={1 + passages.index(readme) // 25}")
    assert page.status_code == 200

    assert "In the code graph" not in article_containing(page.text, README_TITLE)


def test_a_commit_passage_shows_what_the_commit_modified(client, coded):
    """A commit is DEFINED_IN its own passage, so that passage carries its MODIFIES edges."""
    ctx, source_id = coded
    passages = ctx.store.passages_for_source(source_id, limit=500)
    commit = next(p for p in passages if p["title"].startswith("commit b2b2b2b"))
    page = client.get(f"/sources/{source_id}?page={1 + passages.index(commit) // 25}")
    assert page.status_code == 200

    block = article_containing(page.text, commit["title"])
    assert "In the code graph" in block
    assert "-[MODIFIES 1.00" in block
    assert "OrderService.place" in block


def test_the_source_header_names_the_files_the_code_pass_could_not_read(client, coded):
    """`tools/build.go` is checked in unparsed on purpose, so one file is always skipped."""
    _ctx, source_id = coded
    page = client.get(f"/sources/{source_id}")
    assert page.status_code == 200
    assert "unsupported 1" in page.text
    # The per-kind badges are the other half of the summary, and INVOKES is always there.
    assert "INVOKES" in page.text


def test_a_hidden_source_leaks_no_symbol_details(coded):
    ctx, source_id = coded
    ctx.store.ping()  # seeds the default roles
    ctx.store.set_source_access(source_id, "arch-admin")
    ctx.invalidate_graph()
    passages = ctx.store.passages_for_source(source_id, limit=500)

    ivy = Principal(
        user={"id": "ivy"},
        role=ctx.store.get_role("individual"),
        access=Access(rank=0, user_id="ivy"),
    )
    assert sources_routes.code_details_for(ctx, ivy, passages) == {}

    # And the page an individual would have to reach to see them is not theirs to open.
    ctx.store.create_user("root", "secret1", "arch-admin")  # the first user must take the top role
    ctx.store.create_user("ivy", "secret1", "individual")
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        signed_in = client.post(
            "/login", data={"username": "ivy", "password": "secret1"}, follow_redirects=False
        )
        assert signed_in.status_code == 303, signed_in.text
        assert client.get(f"/sources/{source_id}").status_code == 404
