"""
Tests for hippo.codegraph.git_history: reading a repository's first-parent history.

Backend-free, like `test_codegraph.py`: every test builds a *real* git repository in
`tmp_path` and calls `read_history` directly. No store, no pipeline, no LLM. That is the
point -- history reading is pure subprocess plumbing plus tree-sitter, and it is far easier
to argue with three commits you can see than with a graph three layers down.

The repository is `tests/conftest.make_code_checkout`, which replays the checked-in fixture
tree as three commits with a pinned identity and pinned dates, so the SHAs are the same on
every machine and HEAD is the fixture byte for byte.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from hippo.codegraph import extract_code, git_history
from hippo.codegraph.git_history import HistoryError, read_history
from hippo.ingest import repos
from tests.conftest import (
    CODE_CHECKOUT_DATES,
    CODE_CHECKOUT_SUBJECTS,
    CODE_SAMPLE_PATH,
    git_env,
    make_code_checkout,
)

SOURCE_ID = "fixture"

# A module-level function inserted above `OrderService` by the S2.9 drift test. Long enough
# that the lines the middle commit changed (19-22) end up inside *it* at HEAD.
AUDIT = '''\
def audit(order):
    """Audit an order before it is placed."""
    seen = 0
    seen += 1
    seen += 2
    seen += 3
    seen += 4
    seen += 5
    seen += 6
    seen += 7
    seen += 8
    seen += 9
    seen += 10
    return seen


'''

# `save` as it stands at HEAD, for the test that deletes it.
SAVE_AT_HEAD = """\
    def save(self, order):
        self.run("INSERT INTO orders (id, total) VALUES (?, ?)")
        raise OrderError("nope")

"""


# ------------------------------------------------------------ the checkout


def git_out(checkout: Path, *args: str) -> str:
    """One read-only git command against the checkout, as text."""
    result = subprocess.run(
        ["git", "-C", str(checkout), *args],
        capture_output=True,
        text=True,
        env=git_env(),
        check=True,
    )
    return result.stdout


def add_commit(checkout: Path, subject: str) -> None:
    """One more commit on top of `make_code_checkout`'s three, with the same pinned identity."""
    env = _identity("2024-02-01T09:00:00+00:00")
    subprocess.run(["git", "-C", str(checkout), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(checkout), "commit", "-q", "-m", subject], check=True, env=env)


def _merge(checkout: Path, subject: str) -> None:
    """Merge `side` into the current branch with a real merge commit."""
    env = _identity("2024-02-02T09:00:00+00:00")
    subprocess.run(
        ["git", "-C", str(checkout), "merge", "--no-ff", "-q", "-m", subject, "side"],
        check=True,
        env=env,
    )


def _identity(date: str) -> dict[str, str]:
    return git_env(
        GIT_AUTHOR_NAME="Hippo Fixture", GIT_AUTHOR_EMAIL="fixture@hippo.test", GIT_AUTHOR_DATE=date,
        GIT_COMMITTER_NAME="Hippo Fixture", GIT_COMMITTER_EMAIL="fixture@hippo.test",
        GIT_COMMITTER_DATE=date,
    )  # fmt: skip


def test_make_code_checkout_replays_the_fixture_as_three_commits(tmp_path: Path) -> None:
    checkout = make_code_checkout(tmp_path)
    subjects = git_out(checkout, "log", "--first-parent", "--format=%s").split("\n")[:3]
    assert subjects == list(reversed(CODE_CHECKOUT_SUBJECTS))  # git logs newest first

    # HEAD must be the fixture byte for byte, or expected.json's pinned line numbers drift.
    for path in sorted(CODE_SAMPLE_PATH.rglob("*")):
        if path.is_file() and path.name != "expected.json":
            assert (checkout / path.relative_to(CODE_SAMPLE_PATH)).read_bytes() == path.read_bytes()
    assert not (checkout / "expected.json").exists()  # the spec is beside the tree, not in it


def test_make_code_checkout_pins_dates_so_shas_are_reproducible(tmp_path: Path) -> None:
    one = make_code_checkout(tmp_path / "one")
    two = make_code_checkout(tmp_path / "two")
    assert git_out(one, "log", "--format=%H") == git_out(two, "log", "--format=%H")
    # Git versions render UTC as either Z or +00:00; the pinned instants are identical.
    assert [
        datetime.fromisoformat(value) for value in git_out(one, "log", "--format=%aI").splitlines()[:3]
    ] == [datetime.fromisoformat(value) for value in reversed(CODE_CHECKOUT_DATES)]


# ------------------------------------------------------------- reading it


def head_symbols(checkout: Path, source_id: str = SOURCE_ID) -> list:
    """The symbols of the checkout at HEAD, exactly as the pipeline would extract them."""
    return extract_code(repos.walk_repo(checkout), source_id).symbols


def history_of(checkout: Path, symbols: list | None = None, **budgets) -> tuple:
    """`read_history` over a checkout at the settings' defaults, with its HEAD symbols."""
    symbols = head_symbols(checkout) if symbols is None else symbols
    options = {"depth": 200, "timeout_s": 10, "total_s": 120, **budgets}
    return read_history(checkout, symbols, SOURCE_ID, **options), symbols


def modified(history, symbols: list, key=lambda s: s.qualname) -> dict[int, set[str]]:
    """
    ordinal -> the symbol qualnames that commit's MODIFIES edges point at.

    `key` names a symbol some other way, for the cases where a qualname is not unique across the
    fixture tree: `OrderService.save` is one symbol in `pyapp/orders.py` and another in
    `rsapp/src/orders.rs`.
    """
    qualname = {s.id: key(s) for s in symbols}
    ordinal = {c["id"]: c["ordinal"] for c in history.commits}
    touched: dict[int, set[str]] = {}
    for row in history.modifies:
        touched.setdefault(ordinal[row["commit_id"]], set()).add(qualname[row["symbol_id"]])
    return touched


def test_reads_the_three_commits_newest_first(tmp_path: Path) -> None:
    checkout = make_code_checkout(tmp_path)
    history, _ = history_of(checkout)

    assert [c["ordinal"] for c in history.commits] == [0, 1, 2]
    assert history.truncated is False  # the whole first-parent line, start to finish
    assert [c["message"].strip() for c in history.commits] == list(reversed(CODE_CHECKOUT_SUBJECTS))
    assert [datetime.fromisoformat(c["date"]) for c in history.commits] == [
        datetime.fromisoformat(value) for value in reversed(CODE_CHECKOUT_DATES)
    ]
    assert {c["author"] for c in history.commits} == {"Hippo Fixture"}
    assert {c["source_id"] for c in history.commits} == {SOURCE_ID}
    assert all(len(c["sha"]) == 40 for c in history.commits)
    assert history.skipped == 0


def test_commit_ids_are_the_ones_the_store_writes(tmp_path: Path) -> None:
    from hippo.codegraph import commit_id

    checkout = make_code_checkout(tmp_path)
    history, _ = history_of(checkout)
    assert [c["id"] for c in history.commits] == [commit_id(SOURCE_ID, c["sha"]) for c in history.commits]


def test_precedes_chains_the_first_parent_line_newest_to_oldest(tmp_path: Path) -> None:
    checkout = make_code_checkout(tmp_path)
    history, _ = history_of(checkout)
    ids = [c["id"] for c in history.commits]
    assert history.precedes == [(ids[0], ids[1]), (ids[1], ids[2])]


def test_modifies_points_at_the_symbol_the_hunk_is_inside(tmp_path: Path) -> None:
    # The middle commit edits `place`'s body and nothing else. The module and the class both
    # *contain* those lines, so a plain range intersection would emit three edges; only the
    # innermost enclosing symbol per touched line is the one that changed.
    checkout = make_code_checkout(tmp_path)
    history, symbols = history_of(checkout)
    assert modified(history, symbols)[1] == {"OrderService.place"}


def test_a_new_file_modifies_every_symbol_it_brought_in(tmp_path: Path) -> None:
    checkout = make_code_checkout(tmp_path)
    history, symbols = history_of(checkout)
    # HEAD's commit edits `save` and adds tsapp/index.ts whole.
    assert modified(history, symbols)[0] == {"OrderService.save", "tsapp.index", "main"}


def test_the_hunk_is_the_at_at_line_as_json(tmp_path: Path) -> None:
    checkout = make_code_checkout(tmp_path)
    history, symbols = history_of(checkout)
    ordinal = {c["id"]: c["ordinal"] for c in history.commits}
    (place,) = [r for r in history.modifies if ordinal[r["commit_id"]] == 1]
    # `@@ -18,0 +19,4 @@` -- start and count, exactly the numbers git printed.
    assert place["hunk"] == {
        "file": "pyapp/orders.py",
        "old_range": [18, 0],
        "new_range": [19, 4],
        "churn": 4,
    }
    assert place["omega"] == 1.0


def test_a_directory_with_no_git_in_it_says_so(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    with pytest.raises(HistoryError, match="git"):
        read_history(tmp_path / "plain", [], SOURCE_ID, depth=200, timeout_s=10, total_s=120)


def test_depth_caps_how_far_back_the_walk_goes(tmp_path: Path) -> None:
    checkout = make_code_checkout(tmp_path)
    history, symbols = history_of(checkout, depth=1)
    assert [c["ordinal"] for c in history.commits] == [0]
    assert history.precedes == []
    assert set(modified(history, symbols)) == {0}


def test_depth_zero_reads_no_history_at_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # `code_history_depth = 0` disables history: git must not even be run for it.
    monkeypatch.setattr(
        git_history.subprocess, "run", lambda *a, **k: pytest.fail("git ran with history disabled")
    )
    history = read_history(tmp_path, [], SOURCE_ID, depth=0, timeout_s=10, total_s=120)
    assert (history.commits, history.modifies, history.precedes, history.skipped) == ([], [], [], 0)


def test_the_same_checkout_twice_gives_the_same_history(tmp_path: Path) -> None:
    checkout = make_code_checkout(tmp_path)
    first, symbols = history_of(checkout)
    second, _ = history_of(checkout, symbols)
    assert first == second


def test_binary_and_unsupported_files_are_ignored(tmp_path: Path) -> None:
    checkout = make_code_checkout(tmp_path)
    (checkout / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)))
    # Ruby has no grammar here and no walker, so it stands for "code we cannot read" now
    # that Go parses; `PARSED_LANGS` is derived from the walkers, and this is what it gates.
    (checkout / "tools" / "extra.rb").write_text("module Extra\n  def self.run; end\nend\n")
    add_commit(checkout, "Add a logo and a ruby helper")
    history, symbols = history_of(checkout)
    assert modified(history, symbols).get(0, set()) == set()  # neither file has a grammar
    assert [c["ordinal"] for c in history.commits] == [0, 1, 2, 3]  # the commit is still a commit


# ------------------------------------------------------------------ S2.9


def test_the_hunk_is_read_against_the_file_at_that_commit_not_at_head(tmp_path: Path) -> None:
    # The whole point of S2.9. A later commit inserts a function *above* `OrderService`, so
    # `place` is no longer where it was: the lines the middle commit changed (19-22) now sit
    # inside `audit`. Reading the hunk against HEAD would report `audit`; reading it against
    # the file as it was at that commit still reports `place`.
    checkout = make_code_checkout(tmp_path)
    orders = checkout / "pyapp" / "orders.py"
    orders.write_text(
        orders.read_text().replace("class OrderService(Base):", AUDIT + "class OrderService(Base):")
    )
    add_commit(checkout, "Add an audit helper above the service")

    history, symbols = history_of(checkout)
    # Keyed by (path, qualname): `rsapp/src/orders.rs` has an `OrderService.place` of its own.
    at_head = {(s.path, s.qualname): (s.line_start, s.line_end) for s in symbols}
    orders = "pyapp/orders.py"
    assert at_head[(orders, "audit")][0] <= 19 and at_head[(orders, "audit")][1] >= 19  # drift is real
    assert at_head[(orders, "OrderService.place")][0] > 22
    assert modified(history, symbols)[2] == {"OrderService.place"}


def test_a_symbol_deleted_after_the_commit_that_touched_it_gets_no_edge(tmp_path: Path) -> None:
    checkout = make_code_checkout(tmp_path)
    orders = checkout / "pyapp" / "orders.py"
    orders.write_text(orders.read_text().replace(SAVE_AT_HEAD, ""))
    add_commit(checkout, "Drop save")

    history, symbols = history_of(checkout)
    # By path: the Rust tree tells the same story and still has a `save` of its own.
    by_path = lambda s: f"{s.path}::{s.qualname}"  # noqa: E731
    save = "pyapp/orders.py::OrderService.save"
    assert save not in {by_path(s) for s in symbols}
    touched = modified(history, symbols, key=by_path)
    assert all(save not in names for names in touched.values())
    # the rest of that commit's edges survive
    assert touched[1] == {"tsapp/index.ts::tsapp.index", "tsapp/index.ts::main"}


def test_a_commit_whose_diff_times_out_is_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # `_hunks` reads its diff through `_git_capped` (a Popen, not `subprocess.run`), so the
    # timeout is simulated at that seam instead of at `subprocess.run` -- test plumbing only,
    # the assertions below are unchanged.
    checkout = make_code_checkout(tmp_path)
    symbols = head_symbols(checkout)
    slow = git_out(checkout, "rev-parse", "HEAD~1").strip()  # the middle commit
    real_capped = git_history._git_capped

    def sometimes_slow(checkout, args, timeout_s, max_bytes):
        # Only that commit's own diff. Its sha also appears as the *parent* of HEAD's diff,
        # which is a perfectly healthy command and must still run.
        if args[-1] == slow:
            raise subprocess.TimeoutExpired(["git", *args], timeout_s)
        return real_capped(checkout, args, timeout_s, max_bytes)

    monkeypatch.setattr(git_history, "_git_capped", sometimes_slow)
    history, _ = history_of(checkout, symbols)

    assert history.skipped == 1
    assert [c["ordinal"] for c in history.commits] == [0, 2]  # the ordinal gap is the skip
    ids = [c["id"] for c in history.commits]
    assert history.precedes == [(ids[0], ids[1])]  # chained over what survived
    assert set(modified(history, _)) == {0, 2}


def test_the_whole_pass_budget_stops_the_walk_and_keeps_what_it_read(tmp_path: Path) -> None:
    checkout = make_code_checkout(tmp_path)
    history, symbols = history_of(checkout, total_s=0)
    # The budget is checked before each commit, so a zero budget reads none of them -- and
    # says so, rather than quietly reporting a repository with no history.
    assert history.commits == []
    assert history.skipped == 3
    assert history.truncated is True


def test_should_stop_ends_the_walk_without_counting_a_skip(tmp_path: Path) -> None:
    # Cancelling a job is not a budget being exceeded: the user asked us to stop.
    checkout = make_code_checkout(tmp_path)
    seen = {"calls": 0}

    def should_stop() -> bool:
        seen["calls"] += 1
        return seen["calls"] > 2

    history = read_history(
        checkout, head_symbols(checkout), SOURCE_ID,
        depth=200, timeout_s=10, total_s=120, should_stop=should_stop,
    )  # fmt: skip
    assert [c["ordinal"] for c in history.commits] == [0, 1]
    assert history.skipped == 0
    # `skipped` is a budget count, and no budget was exceeded -- but the walk *did* stop early,
    # and a caller that only looked at `skipped` could not tell this from a complete history.
    assert history.truncated is True


def test_a_merge_commit_reports_what_it_brought_in(tmp_path: Path) -> None:
    # `git show -U0` prints *nothing* for a merge, so a `git show` implementation gives a
    # merge zero MODIFIES. Diffing against the first parent is what a --first-parent walk
    # means: the merge changed everything the branch carried.
    checkout = make_code_checkout(tmp_path)
    git_out(checkout, "checkout", "-q", "-b", "side", "HEAD~1")
    # The docstring line is the module's own -- a symbol is only modified when the hunk lands
    # on lines that belong to it rather than to something nested inside it.
    (checkout / "pyapp" / "shipping.py").write_text(
        '"""Shipping."""\n\n\ndef ship(order):\n    return order["id"]\n'
    )
    add_commit(checkout, "Add shipping")
    git_out(checkout, "checkout", "-q", "main")
    _merge(checkout, "Merge side")

    history, symbols = history_of(checkout)
    assert history.commits[0]["message"].startswith("Merge side")
    assert modified(history, symbols)[0] == {"pyapp.shipping", "ship"}


@pytest.mark.parametrize(
    ("header", "touched"),
    [
        ((0, 0, 1, 8), (1, 8)),  # @@ -0,0 +1,8 @@   a new file
        ((18, 0, 19, 4), (19, 22)),  # @@ -18,0 +19,4 @@ four lines inserted
        ((31, 0, 32, 1), (32, 32)),  # @@ -31,0 +32 @@   one line inserted
        ((22, 1, 21, 0), (21, 21)),  # @@ -22 +21,0 @@   a line deleted, after new line 21
        ((1, 6, 0, 0), (1, 1)),  # @@ -1,6 +0,0 @@   a whole file emptied
    ],
)
def test_the_lines_a_hunk_is_about(header: tuple, touched: tuple) -> None:
    # A deletion has no new-side lines of its own, so git reports the line it happened
    # *after*. Reading that literally gives the empty range (21, 20) and the deletion is
    # attributed to nothing -- so a deleted line inside a function would look like a commit
    # that touched no symbol at all.
    assert git_history._Hunk("x.py", *header).touched == touched


def test_a_deletion_is_attributed_to_the_symbol_it_was_deleted_from(tmp_path: Path) -> None:
    # A pure deletion has no new-side lines of its own: git prints `@@ -22 +21,0 @@`, meaning
    # "after new line 21". Reading that range literally gives an empty one (21..20) and the
    # edge disappears -- deleting the middle of a function would look like touching nothing.
    # The same commit deletes a whole file, whose hunk has `+++ /dev/null` and no new side
    # at all: that one really is nothing to point at.
    checkout = make_code_checkout(tmp_path)
    orders = checkout / "pyapp" / "orders.py"
    orders.write_text(orders.read_text().replace("        print(amount)\n", ""))
    (checkout / "pyapp" / "cli.py").unlink()
    add_commit(checkout, "Drop a print and the cli")

    history, symbols = history_of(checkout)
    assert ("pyapp/cli.py", "main") not in {(s.path, s.qualname) for s in symbols}  # gone at HEAD
    assert modified(history, symbols)[0] == {"OrderService.place"}


def test_a_shallow_clones_oldest_commit_does_not_claim_the_whole_tree(tmp_path: Path) -> None:
    # Every repo source is a shallow clone, and the oldest commit in one reports *no parent*
    # even though it has one. `git show` then diffs it against the empty tree and it looks
    # like the commit that added all eleven files. `.git/shallow` is what says the parent was
    # merely not fetched, and a commit whose diff we cannot know gets no edges rather than
    # every edge.
    checkout = make_code_checkout(tmp_path)
    clone = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "2", "--single-branch", "--", f"file://{checkout}", str(clone)],
        check=True,
        env=git_env(),
    )
    assert (clone / ".git" / "shallow").exists()

    history, symbols = history_of(clone)
    assert [c["ordinal"] for c in history.commits] == [0, 1]  # both commits are still commits
    touched = modified(history, symbols)
    assert touched[0] == {"OrderService.save", "tsapp.index", "main"}  # the real tip diff
    assert 1 not in touched  # the boundary claims nothing, rather than claiming everything


# ------------------------------------------------------------- E2F: renames


def test_the_fixture_history_renames_nothing(tmp_path: Path) -> None:
    # The premise of every `expected.json` `modifies` row: turning rename detection on cannot
    # move a single one of them, because there is no rename in this history to detect. Asserted
    # rather than assumed -- it is the reason the golden file did not change with `-M`.
    checkout = make_code_checkout(tmp_path)
    summary = git_out(checkout, "log", "--first-parent", "-M", "--summary", "--format=")
    assert "rename " not in summary


def test_a_rename_with_no_content_change_modifies_nothing(tmp_path: Path) -> None:
    # E2 defect 3, half one. With `--no-renames` a content-preserving rename diffs as a delete
    # of the whole old path plus an add of the whole new one, which is indistinguishable from a
    # whole-file rewrite: the rename commit was credited with modifying EVERY symbol in the file,
    # so `hippo history` returned it for `run` and `connectToDB` exactly as for `Generate`.
    checkout = make_code_checkout(tmp_path)
    git_out(checkout, "mv", "pyapp/orders.py", "pyapp/svc.py")
    add_commit(checkout, "Rename orders.py to svc.py")

    history, symbols = history_of(checkout)
    assert history.commits[0]["message"].startswith("Rename orders.py")
    assert modified(history, symbols).get(0, set()) == set()


def test_a_rename_that_also_edits_a_function_modifies_only_that_function(tmp_path: Path) -> None:
    # Rename detection is a similarity match, not an exact one: a rename carrying one small edit
    # is still a rename, and only the edited function is modified by it.
    checkout = make_code_checkout(tmp_path)
    git_out(checkout, "mv", "pyapp/orders.py", "pyapp/svc.py")
    svc = checkout / "pyapp" / "svc.py"
    svc.write_text(svc.read_text().replace("        print(amount)\n", "        print(amount + 1)\n"))
    add_commit(checkout, "Rename orders.py and tweak place")

    history, symbols = history_of(checkout)
    assert modified(history, symbols)[0] == {"OrderService.place"}


def test_a_commit_before_a_rename_still_modifies_the_symbol_at_its_head_path(tmp_path: Path) -> None:
    # E2 defect 3, half two, and the reason `Generate`'s real authorship commit was invisible:
    # the commit that wrote a function diffs against the path the file had THEN, which no HEAD
    # symbol lives at. Walking newest -> oldest, the rename says what the older path is called
    # now, and the file is read at its old path but named by its HEAD one -- which is also the
    # only way the module symbol can be found, its qualname being its path.
    checkout = make_code_checkout(tmp_path)
    git_out(checkout, "mv", "pyapp/orders.py", "pyapp/svc.py")
    add_commit(checkout, "Rename orders.py to svc.py")

    history, symbols = history_of(checkout)
    by_path = lambda s: f"{s.path}::{s.qualname}"  # noqa: E731
    touched = modified(history, symbols, key=by_path)
    assert touched.get(0, set()) == set()  # the rename commit itself
    # Ordinal 1 edited `save` and ordinal 2 edited `place`, both in `pyapp/orders.py`; those
    # symbols are `pyapp/svc.py`'s now, and both commits are still theirs.
    assert "pyapp/svc.py::OrderService.save" in touched[1]
    assert touched[2] == {"pyapp/svc.py::OrderService.place"}
    # The module symbol was `pyapp.orders` at the root commit and is `pyapp.svc` at HEAD, so
    # keying on the qualname the old file computed could never have matched it.
    assert "pyapp/svc.py::pyapp.svc" in touched[3]

    # The stored hunk still names the path the file had at that commit: S2.9 reads everything
    # about a commit as it was at that commit, and the `file` field is part of that.
    ordinal = {c["id"]: c["ordinal"] for c in history.commits}
    assert {r["hunk"]["file"] for r in history.modifies if ordinal[r["commit_id"]] == 2} == {
        "pyapp/orders.py"
    }


def test_a_rename_of_a_rename_follows_all_the_way_back(tmp_path: Path) -> None:
    # Two renames of the same file in two commits: the alias map has to compose, or the oldest
    # commit's hunks land on a path nothing at HEAD answers to.
    checkout = make_code_checkout(tmp_path)
    git_out(checkout, "mv", "pyapp/orders.py", "pyapp/svc.py")
    add_commit(checkout, "Rename orders.py to svc.py")
    git_out(checkout, "mv", "pyapp/svc.py", "pyapp/service.py")
    add_commit(checkout, "Rename svc.py to service.py")

    history, symbols = history_of(checkout)
    touched = modified(history, symbols, key=lambda s: f"{s.path}::{s.qualname}")
    assert touched.get(0, set()) == set() and touched.get(1, set()) == set()  # neither modifies
    assert touched[3] == {"pyapp/service.py::OrderService.place"}  # two renames back


# ------------------------------------------------------------------ E1F-a


def diff_bytes(checkout: Path, *args: str) -> bytes:
    """The raw stdout of one git command, unlike `git_out` which decodes as text."""
    return subprocess.run(["git", "-C", str(checkout), *args], capture_output=True, env=git_env()).stdout


def test_a_commit_with_invalid_utf8_in_its_diff_is_read_with_replacement(tmp_path: Path) -> None:
    # A byte outside valid UTF-8 inside a diff -- seen for real inside a vendored binary tree
    # (Defect 1) -- must not crash `subprocess.run`'s strict decode and take the whole index
    # job down with it. `.h` has no grammar, so this file itself never produces a MODIFIES
    # edge either way; what matters is that the commit still lands (not skipped) and the
    # *other* file this same commit touches is still read correctly past the bad byte.
    checkout = make_code_checkout(tmp_path)
    (checkout / "tools" / "native.h").write_bytes(b"#define X 1 /* \xe4 not valid utf-8 */\n")
    orders = checkout / "pyapp" / "orders.py"
    orders.write_text(orders.read_text() + "\n\ndef audit(order):\n    return order\n")
    add_commit(checkout, "Add a native header with a bad byte")

    history, symbols = history_of(checkout)
    assert history.skipped == 0  # read with replacement, not skipped
    assert [c["ordinal"] for c in history.commits] == [0, 1, 2, 3]
    assert modified(history, symbols)[0] == {"audit", "pyapp.orders"}  # the new function and its module


def test_a_commit_whose_diff_exceeds_max_diff_bytes_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The root commit's diff (the whole initial tree, `git show` against the empty tree) is
    # the largest of the fixture's three; capping MAX_DIFF_BYTES one byte under its real size
    # skips only that one commit and leaves the other two -- much smaller, single-symbol
    # edits -- intact.
    checkout = make_code_checkout(tmp_path)
    symbols = head_symbols(checkout)
    root = git_out(checkout, "rev-parse", "HEAD~2").strip()
    size = len(diff_bytes(checkout, "show", *git_history.DIFF_OPTIONS, "--format=", root))
    monkeypatch.setattr(git_history, "MAX_DIFF_BYTES", size - 1)

    history, _ = history_of(checkout, symbols)

    assert history.skipped == 1
    assert [c["ordinal"] for c in history.commits] == [0, 1]
    ids = [c["id"] for c in history.commits]
    assert history.precedes == [(ids[0], ids[1])]
    assert set(modified(history, symbols)) == {0, 1}


def test_a_symbol_with_no_lines_of_its_own_is_never_modified(tmp_path: Path) -> None:
    # `tsapp/models/base.ts` is nothing but `export class Base { ... }`, so the module symbol
    # spans exactly the same lines as the class and owns none of them. It therefore never
    # appears in MODIFIES -- not even in the commit that created the file. That is the
    # innermost rule being consistent rather than a gap: every line of that file belongs to
    # the class, and the class is what changed. Named here because WP4's commit eval will see
    # it, and a module symbol quietly missing from every commit should be a decision.
    checkout = make_code_checkout(tmp_path)
    history, symbols = history_of(checkout)
    touched = {q for names in modified(history, symbols).values() for q in names}
    assert "Base" in touched and "Base.log" in touched
    assert "tsapp.models.base" not in touched
    assert "pyapp.store" in touched  # a module with a line of its own is modified as usual
