"""
hipporag/anchors.py: which symbols a question names, and how a question splits.

Two things are being defended here. The first is that a question containing an identifier, a
traceback, a snippet or a diff finds the right code nodes. The second matters more: that an
*ordinary prose question finds nothing*. Spike 1 (`research/S0-spikes.md`) measured the rule
PLAN.md first wrote and found it firing on 16% of 118 prose questions against Django's symbol set,
because `country`, `library`, `status` and `run` are English words as well as symbol names. The
corpus below is that spike's, and it runs with the stoplist emptied - which is the stronger test,
because it proves the surface-form rule carries the weight on its own.
"""

from __future__ import annotations

import pytest

from hippo.codegraph.model import symbol_id
from hippo.hipporag import anchors
from hippo.hipporag.anchors import (
    AMBIGUOUS_ABOVE,
    MAX_MATCHES_PER_TOKEN,
    Anchor,
    find_anchors,
    split_question,
)
from hippo.hipporag.graph_index import GraphIndex
from hippo.hipporag.paths import display_of
from tests.fakes.code_fixture import many_symbols, polyglot_symbols

TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "pyapp/cli.py", line 5, in main\n'
    "    service.place(order)\n"
    '  File "pyapp/orders.py", line 18, in place\n'
    "    amount = billing.total(order)\n"
    "OrderError: nope"
)

# The other four runtimes, captured from real programs rather than written from the regexes: `go
# run` on an out-of-range slice, `dotnet run` on an out-of-range list, `RUST_BACKTRACE=1 cargo run`
# on the same. Only the paths and line numbers were moved onto the fixture symbols; every other
# character - the `+0x34` offsets, the rustc hash, the `(677470444)` thread id, ``List`1``, the
# `<usize as …>` frame, the trailing `exit status 2` - is what the toolchain printed.
GO_PANIC = (
    "panic: runtime error: index out of range [5] with length 0\n"
    "\n"
    "goroutine 1 [running]:\n"
    "example.com/goapp/orders.(*Service).Place(0x14000112000, {0x0?})\n"
    "\t/Users/me/src/goapp/orders/service.go:18 +0x34\n"
    "main.main()\n"
    "\tgoapp/cmd/main.go:7 +0x24\n"
    "runtime.main()\n"
    "\t/opt/homebrew/Cellar/go/1.19.5/libexec/src/runtime/proc.go:250 +0x24c\n"
    "exit status 2"
)

NET_TRACE = (
    "Unhandled exception. CsApp.Store.InvalidOrderException: order 5 is not open\n"
    "   at CsApp.Orders.OrderService.Place(Order o)"
    " in /Users/me/src/csapp/Orders/OrderService.cs:line 18\n"
    "   at CsApp.Orders.OrderService.Save(Order o) in csapp/Orders/OrderService.cs:line 28\n"
    "   at System.Collections.Generic.List`1.ForEach(Action`1 action)\n"
    "   at Program.<Main>$(String[] args) in csapp/Program.cs:line 4"
)

RUST_PANIC = (
    "thread 'main' (677470444) panicked at rsapp/src/orders.rs:20:19:\n"
    "index out of bounds: the len is 0 but the index is 5\n"
    "stack backtrace:\n"
    "   0: __rustc::rust_begin_unwind\n"
    "             at /rustc/ac68faa20c58cbccd/library/std/src/panicking.rs:689:5\n"
    "   1: core::panicking::panic_fmt\n"
    "             at /rustc/ac68faa20c58cbccd/library/core/src/panicking.rs:80:14\n"
    "   2: <usize as core::slice::index::SliceIndex<[T]>>::index\n"
    "             at /rustc/ac68faa20c58cbccd/library/core/src/slice/index.rs:272:10\n"
    "   3: rsapp::orders::OrderService::place\n"
    "             at ./rsapp/src/orders.rs:20:19\n"
    "   4: rsapp::main\n"
    "             at ./rsapp/src/main.rs:5:22\n"
    "   5: core::ops::function::FnOnce::call_once\n"
    "             at /rustc/ac68faa20c58cbccd/library/core/src/ops/function.rs:250:5\n"
    "note: Some details are omitted, run with `RUST_BACKTRACE=full` for a verbose backtrace."
)

# Spike 1's corpus, cut to the questions that actually fired under the planned rule plus the
# abbreviations findings 2 and 3 are about. Every one of these must produce nothing.
PROSE = [
    "Where is Acme Robotics headquartered?",
    "Who maintains the Halo library?",
    "Can you check the sources for the status of the main index?",
    "What country is the city in, and what language do they run?",
    "Describe the source of the connection difference.",
    "What is the date of the site's quality review?",
    "Tell me about the total for that order.",
    "How do I get started with the store?",
    "What does the company build?",
    "Is there a log of everything that was saved?",
    "Who serves the customers list?",
    "The graph shows how the main run works.",
    "S.O.B. is a film, e.g. one from the U.S.A.",
    "In which state is the company founded by Priya Natarajan headquartered?",
]


@pytest.fixture
def index(code_index) -> GraphIndex:
    """`tests/fixtures/code_sample/` indexed through the real pipeline, extractor and all."""
    ctx, _source_id = code_index
    return ctx.graph()


@pytest.fixture
def poly_index(code_index) -> GraphIndex:
    """The fixture tree plus the Go, C# and Rust symbols `ai_docs/add_langs.md` adds to it.

    A separate fixture, not an extension of `index`: `pyapp.store.OrderError` and `Base.log` are
    the only symbols of their name in the tree today and two tests pin the weights that follow
    from that, so the polyglot symbols must not reach them."""
    ctx, source_id = code_index
    polyglot_symbols(ctx, source_id)
    return ctx.graph()


def names(index: GraphIndex, found: list[Anchor]) -> list[str]:
    return [index.name_of(a.vertex) for a in found if not a.ambiguous]


def seeds(index: GraphIndex, found: list[Anchor]) -> dict[str, float]:
    """{display name: weight}, which is what `names` cannot say once four files hold a `main`."""
    return {display_of(index.code_node_at(a.vertex)): a.weight for a in found if not a.ambiguous}


# ------------------------------------------------------------- identifiers


def test_a_dotted_qualname_names_exactly_one_symbol(index: GraphIndex) -> None:
    found = find_anchors("What does pyapp.orders.OrderService.place do?", index)
    assert names(index, found) == ["OrderService.place"]
    assert found[0].how == "identifier"
    assert found[0].kind == "symbol"
    assert found[0].weight == 1.0
    assert found[0].n_matches == 1


def test_a_module_relative_qualname_resolves_too(index: GraphIndex) -> None:
    # The fixture tells one story in two languages, so `OrderService.place` is a qualname in
    # `pyapp/orders.py` and in `rsapp/src/orders.rs`. A dotted name is never split (S2.13): the
    # dots already say "this is code", so both keep the whole share.
    assert seeds(index, find_anchors("Explain OrderService.place", index)) == {
        "pyapp.orders.OrderService.place": 1.0,
        "rsapp.src.orders.OrderService.place": 1.0,
    }


def test_snake_case_pascal_case_and_all_caps_anchor_bare(index: GraphIndex) -> None:
    # A *bare* name is split across everything it matches, and each of these names one symbol per
    # tree: the surface form is what admits the token, the split is what keeps it honest.
    assert seeds(index, find_anchors("what does list_open return?", index)) == {
        "pyapp.orders.OrderService.list_open": 0.5,
        "rsapp.src.orders.OrderService.list_open": 0.5,
    }
    assert seeds(index, find_anchors("what is OrderService for?", index)) == {
        "pyapp.orders.OrderService": 0.5,
        "rsapp.src.orders.OrderService": 0.5,
    }
    assert seeds(index, find_anchors("where is send_invoice called?", index)) == {
        "pyapp.billing.send_invoice": 0.5,
        "rsapp.src.billing.send_invoice": 0.5,
    }


def test_backticks_rescue_a_single_token_lowercase_name(index: GraphIndex) -> None:
    # The cost spike 1 asks us to accept and document: bare `place` in prose does not anchor,
    # because a lowercase single token is indistinguishable from English. Backticks say "code".
    assert find_anchors("what does place do?", index) == []
    assert seeds(index, find_anchors("what does `place` do?", index)) == {
        "pyapp.orders.OrderService.place": 0.5,
        "rsapp.src.orders.OrderService.place": 0.5,
    }


def test_a_data_object_anchors_by_its_name(index: GraphIndex) -> None:
    # `orders` is the table and three modules -- `pyapp/orders.py`, `rsapp/src/orders.rs` and
    # `rsapp/tests/orders.rs` -- so the four share the weight.
    found = find_anchors("who writes to the `orders` table?", index)
    assert seeds(index, found) == {
        "table orders": 0.25,
        "pyapp.orders": 0.25,
        "rsapp.src.orders": 0.25,
        "rsapp.tests.orders": 0.25,
    }
    assert {a.kind for a in found} == {"data", "symbol"}
    assert all(a.n_matches == 4 for a in found)


def test_an_unknown_identifier_anchors_nothing(index: GraphIndex) -> None:
    assert find_anchors("what does `no_such_function` do?", index) == []


# -------------------------------------------------------------- prose is inert


@pytest.mark.parametrize("question", PROSE)
def test_ordinary_prose_anchors_nothing(index: GraphIndex, question: str, monkeypatch) -> None:
    monkeypatch.setattr(anchors, "STOPLIST", frozenset())
    assert find_anchors(question, index) == [], question


@pytest.mark.parametrize("question", PROSE)
def test_a_one_line_prose_question_is_all_prose(question: str) -> None:
    # S2.12's inert condition: the embedding and the fact filter see exactly what they see today.
    assert split_question(question) == (question, "")


def test_prose_is_inert_even_with_the_stoplist_emptied(index: GraphIndex, monkeypatch) -> None:
    monkeypatch.setattr(anchors, "STOPLIST", frozenset())
    assert [q for q in PROSE if find_anchors(q, index)] == []


# ------------------------------------------------------------- stack traces


def test_a_frame_resolves_to_the_innermost_symbol_containing_the_line(index: GraphIndex) -> None:
    found = find_anchors('File "pyapp/orders.py", line 18, in place', index)
    assert names(index, found) == ["OrderService.place"]
    assert found[0].how == "stack_trace"
    assert found[0].weight == 1.0


def test_an_absolute_frame_path_still_finds_the_repo_relative_symbol(index: GraphIndex) -> None:
    # A real traceback names the checkout's absolute path; the index holds the repo-relative one.
    # `_same_path` matches a suffix either way round, which is why AR1 fix 5's `path_index` is
    # keyed by the basename rather than by the whole path.
    found = find_anchors('File "/Users/me/proj/pyapp/orders.py", line 18, in place', index)
    assert names(index, found) == ["OrderService.place"]
    assert found[0].how == "stack_trace" and found[0].weight == 1.0
    # A file that shares a basename with nothing indexed still anchors on nothing.
    assert find_anchors('File "/elsewhere/nothing_here.py", line 18, in nope', index) == []


def test_a_drifted_line_falls_back_to_the_named_function(index: GraphIndex) -> None:
    found = find_anchors('File "pyapp/orders.py", line 999, in place', index)
    assert names(index, found) == ["OrderService.place"]
    assert found[0].how == "stack_trace"


def test_a_path_and_line_with_no_frame_wrapper_still_resolves(index: GraphIndex) -> None:
    assert names(index, find_anchors("it blew up at pyapp/orders.py:31", index)) == ["OrderService.save"]


def test_frames_decay_outwards_and_the_exception_line_anchors_at_08(index: GraphIndex) -> None:
    # Keyed by *display* name: `OrderService.place`, `main` and `OrderError` are each a qualname in
    # more than one tree now, and a frame is placed by its path and line, not by its name.
    anchors_found = [a for a in find_anchors(TRACEBACK, index) if not a.ambiguous]
    found = {display_of(index.code_node_at(a.vertex)): a for a in anchors_found}
    assert found["pyapp.orders.OrderService.place"].weight == pytest.approx(1.0)
    assert found["pyapp.orders.OrderService.place"].how == "stack_trace"
    assert found["pyapp.cli.main"].weight == pytest.approx(0.8)  # one frame further out
    assert found["pyapp.store.OrderError"].how == "exception"
    # The exception line is still one 0.8 share; it is a bare name, so the two `OrderError`
    # symbols split it (S2.13) rather than each seeding a whole one.
    errors = [a for a in anchors_found if a.how == "exception"]
    assert sum(a.weight for a in errors) == pytest.approx(0.8)


def test_a_traceback_is_all_code_and_the_sentence_beside_it_is_all_prose(index: GraphIndex) -> None:
    prose, code = split_question("Why does this fail?\n" + TRACEBACK)
    assert prose == "Why does this fail?"
    assert code.startswith("Traceback") and 'File "pyapp/orders.py"' in code
    # find_anchors reads both halves, so the sentence never hides the frames.
    assert "OrderService.place" in names(index, find_anchors("Why does this fail?\n" + TRACEBACK, index))


# ------------------------------------------ Go, .NET and Rust stack frames (L1)


def test_a_go_panic_seeds_its_frames_and_nothing_from_the_runtime(poly_index: GraphIndex) -> None:
    # The innermost frame names an absolute checkout path and the index holds the repo-relative
    # one, so this is the basename rule of `test_an_absolute_frame_path_...` on a `.go` file too.
    assert seeds(poly_index, find_anchors(GO_PANIC, poly_index)) == {
        "goapp.orders.service.Service.Place": pytest.approx(1.0),
        "goapp.cmd.main.main": pytest.approx(0.8),
    }
    # `runtime.main()` at `runtime/proc.go:250` is a frame like any other and resolves to nothing:
    # no file of that basename, and `runtime.main` names no symbol. And the `panic:` header is not
    # an exception anchor -- Go has no RAISES for one to reach.
    assert [a.how for a in find_anchors(GO_PANIC, poly_index)] == ["stack_trace", "stack_trace"]


def test_a_go_frame_still_resolves_with_its_registers_attached(poly_index: GraphIndex) -> None:
    # `GOTRACEBACK=system` puts `fp=… sp=… pc=…` after the `+0x74` offset, which the plan's
    # `(?: \+0x[0-9a-f]+)?$` tail cannot match -- and an unmatched second line is not a frame.
    trace = (
        "goroutine 1 [running]:\n"
        "example.com/goapp/orders.(*Service).Place(0x60?, {0x0?})\n"
        "\t/Users/me/src/goapp/orders/service.go:18 +0x74"
        " fp=0x14000078f30 sp=0x14000078ef0 pc=0x1009a6274\n"
        "main.main()\n"
        "\tgoapp/cmd/main.go:7 +0x34 fp=0x14000078f70 sp=0x14000078f30 pc=0x1009a62e4"
    )
    assert seeds(poly_index, find_anchors(trace, poly_index)) == {
        "goapp.orders.service.Service.Place": pytest.approx(1.0),
        "goapp.cmd.main.main": pytest.approx(0.8),
    }


def test_a_windows_frame_path_still_finds_the_repo_relative_symbol(poly_index: GraphIndex) -> None:
    # .NET's home platform names `C:\src\…`, and the plan's `[^:]+\.cs` stops at the drive letter.
    # The ` in <file>:line N` half is optional, so the frame does not half-match -- it resolves by
    # name instead, silently losing the line that says which method.
    frame = r"   at CsApp.Orders.OrderService.ListOpen() in C:\src\csapp\Orders\OrderService.cs:line 38"
    found = find_anchors(frame, poly_index)
    assert seeds(poly_index, found) == {"csapp.Orders.OrderService.OrderService.ListOpen": pytest.approx(1.0)}
    assert found[0].how == "stack_trace"
    assert found[0].token == r"C:\src\csapp\Orders\OrderService.cs:38"


def test_a_dotnet_trace_seeds_its_frames_and_its_exception_header(poly_index: GraphIndex) -> None:
    found = find_anchors(NET_TRACE, poly_index)
    assert seeds(poly_index, found) == {
        "csapp.Orders.OrderService.OrderService.Place": pytest.approx(1.0),
        "csapp.Orders.OrderService.OrderService.Save": pytest.approx(0.8),
        "csapp.Store.Base.InvalidOrderException": pytest.approx(0.8),
    }
    how = {display_of(poly_index.code_node_at(a.vertex)): a.how for a in found}
    assert how["csapp.Store.Base.InvalidOrderException"] == "exception"
    assert how["csapp.Orders.OrderService.OrderService.Place"] == "stack_trace"
    # ``System.Collections.Generic.List`1.ForEach`` has no ` in file:line`, so it resolves by name
    # alone -- and `List`1.ForEach` names nothing. `Program.<Main>$` has a file the index does not.
    assert "OrderService.ForEach" not in names(poly_index, found)


def test_a_dotnet_frame_with_no_file_resolves_by_its_qualified_method(poly_index: GraphIndex) -> None:
    found = find_anchors("   at CsApp.Orders.OrderService.ListOpen()", poly_index)
    assert seeds(poly_index, found) == {"csapp.Orders.OrderService.OrderService.ListOpen": pytest.approx(1.0)}
    assert found[0].how == "stack_trace" and found[0].token == "OrderService.ListOpen"


def test_a_rust_panic_decays_from_the_header_not_through_the_unwinder(poly_index: GraphIndex) -> None:
    # The panic line is frame 0. `rust_begin_unwind`, `panic_fmt` and the slice bounds check sit
    # between it and the backtrace's repeat of the same location; counting them would put `main`
    # five frames out at 0.8**5. See `_rust_frames`.
    assert seeds(poly_index, find_anchors(RUST_PANIC, poly_index)) == {
        "rsapp.src.orders.OrderService.place": pytest.approx(1.0),
        "rsapp.src.main.main": pytest.approx(0.8),
    }


def test_a_rust_std_frame_never_leaks_its_last_word_as_a_bare_token(poly_index: GraphIndex) -> None:
    # `2: <usize as core::slice::index::SliceIndex<[T]>>::index` is why the frame regex takes `.+`
    # and not the `\S+` the plan wrote: a trait-impl frame has spaces in its function. Unmatched,
    # the line is not a frame, so nothing pairs it away from the plain tokenizer -- and in a fenced
    # paste, where the tokenizer is not strict, bare `index` seeds `tsapp/index.ts` at a flat 1.0
    # from a frame inside the standard library.
    fenced = f"why does this fail?\n```\n{RUST_PANIC}\n```"
    assert seeds(poly_index, find_anchors(fenced, poly_index)) == {
        "rsapp.src.orders.OrderService.place": pytest.approx(1.0),
        "rsapp.src.main.main": pytest.approx(0.8),
    }


def test_a_rust_trait_impl_frame_resolves_in_its_own_file(poly_index: GraphIndex) -> None:
    # A drifted line, so the qualified fallback decides: `<T as Trait>::m` reads as `T::m`, and the
    # frame's own file wins over `pyapp.orders.OrderService.log`, which shares the qualname.
    found = find_anchors(
        "   2: <rsapp::orders::OrderService as rsapp::store::Base>::log\n"
        "             at ./rsapp/src/orders.rs:999:9",
        poly_index,
    )
    assert seeds(poly_index, found) == {"rsapp.src.orders.OrderService.log": pytest.approx(1.0)}


@pytest.mark.parametrize("trace", [GO_PANIC, NET_TRACE, RUST_PANIC], ids=["go", "dotnet", "rust"])
def test_every_trace_shape_is_all_code_and_the_sentence_beside_it_is_all_prose(trace: str) -> None:
    # S2.12 for the three new shapes: the goroutine header, the `+0x34` offsets, `Unhandled
    # exception.`, `stack backtrace:`, the `note:` footer and the Rust panic *message* all belong
    # to the code half, so the embedding sees the question and nothing else.
    prose, code = split_question("Why does this fail?\n" + trace)
    assert prose == "Why does this fail?"
    assert code.splitlines() == [line for line in trace.splitlines() if line.strip()]


@pytest.mark.parametrize("question", PROSE)
def test_prose_is_still_inert_against_the_polyglot_symbols(
    poly_index: GraphIndex, question: str, monkeypatch
) -> None:
    # Spike 1's corpus over an index that now also holds `Place`, `Save`, `ListOpen`, `Service` and
    # three more `main`s. The surface-form rule, not the symbol set, is what keeps it empty.
    monkeypatch.setattr(anchors, "STOPLIST", frozenset())
    assert find_anchors(question, poly_index) == [], question


@pytest.mark.parametrize("trace", [GO_PANIC, NET_TRACE, RUST_PANIC], ids=["go", "dotnet", "rust"])
def test_a_sentence_beside_a_trace_adds_no_anchor_of_its_own(poly_index: GraphIndex, trace: str) -> None:
    # How these traces are actually pasted. `find_anchors` reads both halves, so the frames survive
    # the split; the sentence goes to the prose half, where spike 1's surface-form rule holds and
    # `Why`, `does`, `this` and `fail` are English.
    asked = f"Why does this fail?\n{trace}"
    assert seeds(poly_index, find_anchors(asked, poly_index)) == seeds(
        poly_index, find_anchors(trace, poly_index)
    )


@pytest.mark.parametrize("trace", [GO_PANIC, NET_TRACE, RUST_PANIC], ids=["go", "dotnet", "rust"])
def test_the_new_shapes_are_deterministic(poly_index: GraphIndex, trace: str) -> None:
    assert find_anchors(trace, poly_index) == find_anchors(trace, poly_index)


# ------------------------------------------------------- fenced code and diffs


def test_a_fenced_block_is_tokenised_as_code(index: GraphIndex) -> None:
    question = "why is this slow?\n```python\namount = billing.total(order)\n```"
    found = find_anchors(question, index)
    assert "total" in names(index, found)
    assert {a.how for a in found} == {"fenced_code"}
    prose, code = split_question(question)
    assert prose == "why is this slow?"
    assert code == "amount = billing.total(order)"


def test_a_unified_diff_seeds_the_symbols_its_hunks_touch(index: GraphIndex) -> None:
    diff = (
        "--- a/pyapp/orders.py\n"
        "+++ b/pyapp/orders.py\n"
        "@@ -16,3 +16,4 @@\n"
        "-        amount = billing.total(order)\n"
        "+        amount = billing.total(order) or 0\n"
    )
    found = [a for a in find_anchors(diff, index) if a.how == "diff"]
    assert names(index, found) == ["OrderService.place"]
    assert found[0].weight == 1.0


# ------------------------------------------------------------- fan-out (S2.13)


def index_with(code_index, name: str, how_many: int) -> GraphIndex:
    """The fixture tree plus `how_many` functions all called `name` - a shape ten files cannot make."""
    ctx, source_id = code_index
    many_symbols(ctx, source_id, name, how_many)
    return ctx.graph()


def test_an_ambiguous_name_splits_its_weight_and_is_capped(code_index) -> None:
    index = index_with(code_index, "handle_it", MAX_MATCHES_PER_TOKEN + 1)
    found = [a for a in find_anchors("what does handle_it do?", index) if not a.ambiguous]
    assert len(found) == MAX_MATCHES_PER_TOKEN
    assert all(a.n_matches == MAX_MATCHES_PER_TOKEN + 1 for a in found)
    assert all(a.weight == pytest.approx(1.0 / (MAX_MATCHES_PER_TOKEN + 1)) for a in found)


def test_a_split_over_every_match_sums_to_one_share_of_the_seed_weight(index: GraphIndex) -> None:
    # `log` is a method on both `OrderService`s and on all three `Base`s: five real symbols.
    found = find_anchors("what does `log` do?", index)
    assert sorted(seeds(index, found)) == [
        "pyapp.orders.OrderService.log",
        "pyapp.store.Base.log",
        "rsapp.src.orders.OrderService.log",
        "rsapp.src.store.Base.log",
        "tsapp.models.base.Base.log",
    ]
    assert sum(a.weight for a in found) == pytest.approx(1.0)
    assert {a.n_matches for a in found} == {5}


def test_a_name_matching_more_than_ten_symbols_seeds_nothing_and_says_so(code_index) -> None:
    index = index_with(code_index, "handle_it", AMBIGUOUS_ABOVE + 1)
    found = find_anchors("what does handle_it do?", index)
    assert [a.ambiguous for a in found] == [True]
    assert found[0].node_id == "" and found[0].vertex == -1 and found[0].weight == 0.0
    assert found[0].n_matches == AMBIGUOUS_ABOVE + 1


def test_a_path_qualified_match_is_never_split(index: GraphIndex) -> None:
    # Three symbols are called `log`; naming one of them by its module picks that one, whole.
    found = find_anchors("what does pyapp.store.Base.log do?", index)
    assert names(index, found) == ["Base.log"]
    assert found[0].weight == 1.0 and found[0].n_matches == 1


# ------------------------------------------------------------------ scoping


def test_a_scoped_index_never_surfaces_a_hidden_symbol(mixed_index) -> None:
    ctx, prose_source_id, code_source_id = mixed_index
    full = ctx.graph()
    assert find_anchors("what does `place` do?", full)

    scoped = full.scoped({prose_source_id})
    assert symbol_id(code_source_id, "pyapp/orders.py", "OrderService.place") not in scoped.idx_of
    assert find_anchors("what does `place` do?", scoped) == []


# ------------------------------------------------------------ determinism


def test_the_same_question_always_gives_the_same_anchors(index: GraphIndex) -> None:
    first = find_anchors(TRACEBACK, index)
    second = find_anchors(TRACEBACK, index)
    assert first == second
    assert [a.node_id for a in first] == sorted(
        [a.node_id for a in first], key=lambda nid: (-next(a.weight for a in first if a.node_id == nid), nid)
    )


def test_an_empty_question_splits_and_anchors_to_nothing(index: GraphIndex) -> None:
    assert split_question("") == ("", "")
    assert find_anchors("", index) == []
