"""
What a repository's git history says about its symbols.

`read_history` walks the first-parent line from HEAD backwards and returns three things the
store already knows how to write: `Commit` rows, `MODIFIES` edges from a commit to each
symbol its diff landed inside, and the `PRECEDES` chain that puts the commits in order.

**Every hunk is intersected with the symbol ranges AT THAT COMMIT** (S2.9), not at HEAD.
That costs one `git show <sha>:<path>` and one tree-sitter parse per touched file per
commit, and it is not optional: WP4's commit-localization eval uses these edges as its gold
labels, so a HEAD-range shortcut would make the eval measure its own drift on every commit
older than a few edits. A symbol is mapped back to HEAD by `model.symbol_key` -- the same
key its id is hashed from -- and one that no longer exists at HEAD produces no edge.

**Renames are followed** (E2 defect 3). Every diff is read with `-M`, so a content-preserving
rename is a `rename from` / `rename to` pair with no `@@` hunks at all rather than a whole-file
delete plus a whole-file add: the rename commit stops being attributed as MODIFIES to every
symbol in the file. The walk is newest -> oldest, so a rename seen at commit C tells us what
the *older* commits' paths are called at HEAD; `read_history` carries that map down the walk, and the
file a hunk landed in is read at its own path but *named* by its HEAD path, so the symbols
parsed out of it -- the module symbol included, whose qualname is its path -- key straight into
the HEAD index. The stored `hunk["file"]` stays as git printed it: the path the file had at that
commit, which is what S2.9's "at that commit" means everywhere else in this module.

Four things about git that this module is built around, each verified on a real repository
rather than assumed:

* **`git show -U0` on a merge commit prints nothing at all.** Not a `@@@` combined diff --
  nothing. So the diff of a commit with a parent is read as `git diff -U0 <first-parent>
  <sha>`, which is both non-empty and the right semantics for a `--first-parent` walk: the
  merge "modifies" everything it brought in. `git show` is used only for a root commit,
  which has no parent to diff against.
* **The user's git config can change the diff's shape.** `diff.noprefix` alone would turn
  `+++ b/pyapp/orders.py` into `+++ pyapp/orders.py` and quietly break every path. The
  prefixes, rename detection, colour and external diff drivers are all passed explicitly.
* **Innermost wins.** The module and the class both contain a method's lines, so a plain
  range intersection would report three symbols for one edit to one function. A hunk is
  matched against each symbol's *own* lines -- its range minus the ranges of the symbols
  nested inside it -- which is what makes "this commit changed `place`" true.
* **A shallow clone's oldest commit reports no parent**, and every repo source is a shallow
  clone. Diffed against the empty tree it looks like the commit that added the entire
  repository. `.git/shallow` is what tells the two cases apart; see `_shallow`.

Two budgets, both from settings (2.2c): `timeout_s` per commit, after which that commit is
dropped and counted in `skipped`, and `total_s` for the whole pass, after which the loop
stops and the commits already read are kept (the unread ones are counted in `skipped` too).
A third, `MAX_DIFF_BYTES`, is a module constant rather than a setting: a commit whose diff
is bigger is dropped and counted the same way, because a commit that vendors a binary tree
is not history worth parsing, and reading one would cost real Python-side decoding and
parsing time that `timeout_s` cannot bound (it only measures how long the subprocess runs).
`should_stop` is separate: cancelling a job is not a budget being exceeded, so it stops the
loop without counting anything as skipped.

Pure, like the rest of `codegraph`: stdlib, tree-sitter and this package. No store, no LLM,
no `ingest` import. Writing what it returns is the indexer's job.
"""

from __future__ import annotations

import logging
import os
import re
import select
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .extract import _walk
from .languages import PARSED_LANGS
from .model import Symbol, commit_id, lang_of, symbol_key

log = logging.getLogger(__name__)

# Field separators inside one `git log` record, and between records. A commit message is
# multi-line and may contain anything a user typed, so the separators have to be bytes no
# message can hold: git's own `%x1f` (unit) and `%x1e` (record).
_UNIT, _RECORD = "\x1f", "\x1e"
LOG_FORMAT = f"%H{_UNIT}%P{_UNIT}%an{_UNIT}%aI{_UNIT}%B{_RECORD}"

# `@@ -18,0 +19,4 @@ class OrderService(Base):` -- a missing count means exactly one line.
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

# Passed to every diff so that nothing in the user's config can change what we parse.
DIFF_OPTIONS = (
    "-U0",
    "-M",  # rename detection ON: a rename is a rename, not a delete plus an add (E2 defect 3)
    "--no-color",
    "--no-ext-diff",
    "--no-textconv",
    "--src-prefix=a/",
    "--dst-prefix=b/",
)

MODIFIES_OMEGA = 1.0

# A commit whose diff is bigger than this is skipped like a timeout: a commit that vendors a
# binary tree (a real one has been seen at ~1 GB) is not history worth parsing, and reading it
# would cost seconds of Python-side decoding and regex work that `timeout_s` cannot bound --
# that budget only covers how long the *subprocess* runs, not what we do with its output after.
MAX_DIFF_BYTES = 20 * 1024 * 1024


class HistoryError(RuntimeError):
    """The history could not be read at all -- no git, no repository, no commits."""


class _DiffTooLarge(OSError):
    """
    A commit's diff exceeded MAX_DIFF_BYTES before it finished.

    Subclasses OSError so `read_history`'s defence-in-depth catch (which must already handle
    a bare OSError from git plumbing) catches this too if it is ever reached that way -- from
    the caller's point of view a diff too large to read is exactly like one it could not read.
    """

    def __init__(self, size: int) -> None:
        super().__init__(f"diff exceeded {MAX_DIFF_BYTES:,} bytes (read at least {size:,})")
        self.size = size


@dataclass
class History:
    """
    One source's history, in the shapes the store takes.

    `commits` are `add_commits` rows newest first (`ordinal` 0 is HEAD), `modifies` are
    `add_modifies` rows and `precedes` are `add_precedes` pairs, each going from the newer
    commit to the older one. `skipped` is how many commits a budget cost us; it becomes
    `Source.meta["code"]["history_skipped"]`, which is the number that tells a user their
    history is incomplete rather than their repository being small.
    """

    commits: list[dict] = field(default_factory=list)
    modifies: list[dict] = field(default_factory=list)
    precedes: list[tuple[str, str]] = field(default_factory=list)
    skipped: int = 0
    # Whether the walk stopped before the end of the first-parent line, for any reason -- a
    # budget or a cancellation. `skipped` alone cannot say: cancelling is not a budget, so it
    # counts nothing, and a caller reading `skipped == 0` off a cancelled run would take a
    # partial history for a complete one. Named like `CodeGraph.truncated`, which exists for
    # exactly this reason.
    truncated: bool = False


@dataclass
class _Hunk:
    """One `@@` header: where it landed on the new side, and how many lines it moved."""

    file: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int

    @property
    def touched(self) -> tuple[int, int]:
        """
        The new-side lines this hunk is about, as an inclusive range.

        A pure deletion (`+c,0`) has no new-side lines of its own: git reports the line it
        happened *after*, and that line is the one to attribute the deletion to -- otherwise
        deleting the middle of a function produces no edge at all.
        """
        start = max(self.new_start, 1)
        return (start, start + self.new_count - 1) if self.new_count else (start, start)

    def as_json(self, churn: int) -> dict:
        """The `hunk` payload stored on the MODIFIES edge: the `@@` header, as it was printed."""
        return {
            "file": self.file,
            "old_range": [self.old_start, self.old_count],
            "new_range": [self.new_start, self.new_count],
            "churn": churn,
        }


@dataclass
class _Diff:
    """
    One commit's diff: where it landed, and which files it renamed.

    A rename-only commit has `renames` and no `hunks` at all -- which is exactly the point of
    `-M`, and why such a commit now modifies nothing instead of every symbol in the file.
    """

    hunks: list[_Hunk] = field(default_factory=list)
    renames: list[tuple[str, str]] = field(default_factory=list)  # (path before, path after)


def read_history(
    checkout: Path,
    symbols: list[Symbol],
    source_id: str,
    *,
    depth: int,
    timeout_s: int,
    total_s: int,
    should_stop: Callable[[], bool] | None = None,
) -> History:
    """
    The last `depth` first-parent commits of `checkout`, as commits, MODIFIES and PRECEDES.

    `symbols` are the source's symbols at HEAD -- what `extract_code` just produced -- and
    are the only symbols an edge may point at. `source_id` is passed rather than read off
    `symbols[0]`: a repository whose files hippo cannot parse still has a history worth
    reading, and it has no symbols to read an id from.

    Raises `HistoryError` if the history cannot be read at all. Budgets, by contrast, are
    not errors: they return what was read, with `skipped` saying how much was not.
    """
    if depth <= 0:
        return History()  # `code_history_depth = 0` disables history; do not even run git

    started = time.monotonic()
    entries = _log(checkout, depth, timeout_s)
    head = _head_index(symbols)
    boundary = _shallow(checkout)
    parsers: dict[str, object] = {}

    history = History()
    kept: list[str] = []
    alias: dict[str, str] = {}  # a path as it was at this point in the walk -> its path at HEAD
    for position, entry in enumerate(entries):
        if should_stop is not None and should_stop():
            history.truncated = True  # cancellation, not a budget: nothing to report as skipped
            break
        if time.monotonic() - started >= total_s:
            history.skipped += len(entries) - position
            history.truncated = True
            break
        node_id = commit_id(source_id, entry["sha"])
        try:
            diff = (
                _Diff()
                if entry["sha"] in boundary
                else _hunks(checkout, entry["sha"], entry["parent"], timeout_s)
            )
            rows = _modifies(
                checkout, entry["sha"], node_id, diff.hunks, head, alias, source_id, parsers, timeout_s
            )
        except _DiffTooLarge as err:
            log.debug("commit %s diff too large, skipping (%s)", entry["sha"], err)
            history.skipped += 1
            continue
        except (subprocess.TimeoutExpired, UnicodeDecodeError, OSError):
            # Defence in depth beyond the specific cases above: a slow or otherwise unreadable
            # commit must not cost the rest of the history.
            history.skipped += 1
            continue
        history.commits.append(
            {
                "id": node_id,
                "source_id": source_id,
                "sha": entry["sha"],
                "author": entry["author"],
                "date": entry["date"],
                "message": entry["message"],
                "ordinal": position,  # the position in the git log, so a skip leaves a gap
            }
        )
        history.modifies.extend(rows)
        kept.append(node_id)
        # This commit's own hunks were read under the map as it stood *above* the rename; every
        # commit from here down sees the old path instead. Every target is resolved against that
        # same map and the results applied together, so no rename in one commit can be read
        # through another rename of the same commit.
        alias.update({old: alias.get(new, new) for old, new in diff.renames})

    history.precedes = list(zip(kept, kept[1:], strict=False))  # newer -> older, over what we kept
    return history


# --------------------------------------------------------------- the log


def _shallow(checkout: Path) -> set[str]:
    """
    The shas whose parents were never fetched, from `.git/shallow`.

    This matters because every repo source hippo indexes *is* a shallow clone. The oldest
    commit in one reports no parent at all, so its diff would be taken against the empty
    tree and it would look like the commit that added every file in the repository -- one
    commit modifying every symbol, which is worse than useless as a history and is exactly
    what WP4's commit eval would score against. A commit whose diff we cannot know gets no
    MODIFIES rather than all of them. It is still a commit, and still in the PRECEDES chain.

    (The complementary half is the pipeline's: clone `code_history_depth + 1` commits and
    read `code_history_depth`, so the boundary falls outside the walk and no history is
    lost. This is the half that is true whatever the clone did.)
    """
    marker = checkout / ".git" / "shallow"
    try:
        return {line.strip() for line in marker.read_text().splitlines() if line.strip()}
    except OSError:
        return set()  # a full clone, a worktree, or no repository at all: nothing is truncated


def _log(checkout: Path, depth: int, timeout_s: int) -> list[dict]:
    """The first-parent commit list, newest first. One subprocess for the whole walk."""
    try:
        result = _git(
            checkout,
            ["log", "--first-parent", "-n", str(depth), f"--format={LOG_FORMAT}"],
            timeout_s,
        )
    except subprocess.TimeoutExpired as err:
        raise HistoryError(f"reading the git history of {checkout} took longer than {timeout_s}s") from err
    except FileNotFoundError as err:
        raise HistoryError("git is not installed on this machine, so history cannot be read") from err
    if result.returncode != 0:
        last = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ""
        raise HistoryError(f"could not read the git history of {checkout}. git said: {last}")

    entries: list[dict] = []
    for record in result.stdout.split(_RECORD):
        fields = record.lstrip("\n").split(_UNIT)
        if len(fields) != 5 or not fields[0]:
            continue
        sha, parents, author, date, message = fields
        entries.append(
            {
                "sha": sha,
                "parent": parents.split()[0] if parents.split() else "",
                "author": author,
                "date": date,
                "message": message.strip(),
            }
        )
    return entries


# -------------------------------------------------------------- the diff


def _hunks(checkout: Path, sha: str, parent: str, timeout_s: int) -> _Diff:
    """
    Every `@@` header in this commit's diff, with the file it belongs to, and every rename.

    Against the first parent when there is one, so a merge reports what it brought in
    instead of the empty combined diff `git show` prints for it. Read as bytes and decoded
    with `errors="replace"` -- the pattern `_symbols_at` already uses below -- because a
    diff is not source code and a byte outside valid UTF-8 (seen for real, inside a vendored
    binary tree) must not crash the whole index job over one unparseable commit. Raises
    `_DiffTooLarge` rather than reading past `MAX_DIFF_BYTES`; the caller treats that like a
    timeout.
    """
    command = ["diff", *DIFF_OPTIONS, parent, sha] if parent else ["show", *DIFF_OPTIONS, "--format=", sha]
    raw = _git_capped(checkout, command, timeout_s, MAX_DIFF_BYTES)
    if raw is None:
        return _Diff()  # an unreadable commit is a commit with no edges, not a broken index run
    text = raw.decode("utf-8", errors="replace")

    hunks: list[_Hunk] = []
    renames: list[tuple[str, str]] = []
    moved_from = ""
    path = ""
    for line in text.splitlines():
        # `rename from`/`rename to` carry the bare paths -- git prints no `a/`/`b/` prefix on
        # them whatever `--src-prefix` says -- and always in that order, one pair per file. A
        # `+`/`-` body line could never be mistaken for one: it would start with its own sign.
        if line.startswith("rename from "):
            moved_from = line[len("rename from ") :]
            continue
        if line.startswith("rename to ") and moved_from:
            renames.append((moved_from, line[len("rename to ") :]))
            moved_from = ""
            continue
        if line.startswith("+++ "):
            target = line[4:]
            # `/dev/null` is a deletion: no new side, so nothing to intersect against.
            path = target[2:] if target.startswith("b/") else "" if target == "/dev/null" else target
            continue
        if not path or not line.startswith("@@"):
            continue
        found = HUNK_RE.match(line)
        if found is None:
            continue
        old_start, old_count, new_start, new_count = found.groups()
        hunks.append(
            _Hunk(
                file=path,
                old_start=int(old_start),
                old_count=1 if old_count is None else int(old_count),
                new_start=int(new_start),
                new_count=1 if new_count is None else int(new_count),
            )
        )
    return _Diff(hunks=hunks, renames=renames)


# ------------------------------------------------------- hunks to symbols


def _modifies(
    checkout: Path,
    sha: str,
    node_id: str,
    hunks: list[_Hunk],
    head: dict[str, str],
    alias: dict[str, str],
    source_id: str,
    parsers: dict,
    timeout_s: int,
) -> list[dict]:
    """
    One `add_modifies` row per symbol this commit's hunks landed inside.

    Grouped by file so each file is fetched and parsed once per commit, however many hunks
    touched it. Rows come back sorted by `(path, qualname, kind)` -- `expected.json`'s
    `(path, qualname)` key (S2.17) with the module/member tie broken -- so two runs, and two
    machines, agree on the order.

    `alias` says what a path at this commit is called at HEAD (see the module docstring): the
    blob is read at the path it had here, the symbols are *named* by the HEAD path, and the
    lookup is then the ordinary one. A file whose HEAD name has no grammar is skipped, because
    HEAD is where the symbol this could point at would have to live.
    """
    by_file: dict[str, list[_Hunk]] = {}
    for hunk in hunks:
        if lang_of(alias.get(hunk.file, hunk.file)) in PARSED_LANGS:
            by_file.setdefault(hunk.file, []).append(hunk)

    rows: dict[str, dict] = {}
    keys: dict[str, tuple[str, str, str]] = {}
    for path, file_hunks in sorted(by_file.items()):
        head_path = alias.get(path, path)
        ranges = _own_ranges(_symbols_at(checkout, sha, path, head_path, source_id, parsers, timeout_s))
        for hunk in file_hunks:
            for symbol, own in ranges:
                if not _overlaps(hunk.touched, own):
                    continue
                symbol_id = head.get(symbol_key(symbol.path, symbol.qualname, symbol.kind))
                if symbol_id is None:
                    continue  # gone at HEAD: S2.9 says no edge rather than a dangling one
                seen = rows.get(symbol_id)
                if seen is None:
                    keys[symbol_id] = (symbol.path, symbol.qualname, symbol.kind)
                    rows[symbol_id] = {
                        "commit_id": node_id,
                        "symbol_id": symbol_id,
                        "omega": MODIFIES_OMEGA,
                        "hunk": hunk.as_json(hunk.old_count + hunk.new_count),
                    }
                else:
                    # A second hunk in the same symbol: the store keeps one row per
                    # (commit, symbol), so keep the first hunk's position and add its churn.
                    seen["hunk"]["churn"] += hunk.old_count + hunk.new_count
    return [rows[key] for key in sorted(rows, key=keys.__getitem__)]


def _symbols_at(
    checkout: Path, sha: str, path: str, head_path: str, source_id: str, parsers: dict, timeout_s: int
) -> list[Symbol]:
    """
    The symbols of one file as it was at one commit. An unreadable blob yields none.

    The blob is fetched at `path` -- what the file was called at that commit -- and walked
    under `head_path`, what it is called now. Only the *naming* moves: line ranges are still
    the ranges at that commit, which is what S2.9 asks for. Naming by the HEAD path is what
    lets a symbol be found again across a rename, and it is the only thing that works for the
    module symbol, whose qualname *is* its path (`datagen.mgodatagen` before the rename,
    `datagen.generate` after) and which `(path, qualname)` alone could never match.
    """
    result = _git(checkout, ["show", f"{sha}:{path}"], timeout_s, text=False)
    if result.returncode != 0:
        return []
    text = result.stdout.decode("utf-8", errors="replace")
    facts = _walk(head_path, text, lang_of(head_path), source_id, parsers)
    return [] if facts is None else facts.symbols


def _own_ranges(symbols: list[Symbol]) -> list[tuple[Symbol, list[tuple[int, int]]]]:
    """
    Each symbol paired with the lines that are *its own*: its range, minus the ranges of the
    symbols nested inside it.

    This is what makes a hunk inside a method report the method rather than the method, its
    class and its module. Symbols nest properly, so "inside" is decided by sorting outermost
    first -- a later symbol contained in an earlier one is nested in it, and two symbols with
    the same span (a one-line module holding a one-line function) keep their walker order.
    """
    ordered = sorted(enumerate(symbols), key=lambda pair: (pair[1].line_start, -pair[1].line_end, pair[0]))
    ranges: list[tuple[Symbol, list[tuple[int, int]]]] = []
    for position, (_, symbol) in enumerate(ordered):
        own = [(symbol.line_start, symbol.line_end)]
        for _, inner in ordered[position + 1 :]:
            if inner.line_start >= symbol.line_start and inner.line_end <= symbol.line_end:
                own = _subtract(own, (inner.line_start, inner.line_end))
        ranges.append((symbol, own))
    return ranges


def _subtract(ranges: list[tuple[int, int]], cut: tuple[int, int]) -> list[tuple[int, int]]:
    """`ranges` with the inclusive range `cut` removed from each of them."""
    out: list[tuple[int, int]] = []
    for low, high in ranges:
        if cut[1] < low or cut[0] > high:
            out.append((low, high))
            continue
        if low < cut[0]:
            out.append((low, cut[0] - 1))
        if high > cut[1]:
            out.append((cut[1] + 1, high))
    return out


def _overlaps(touched: tuple[int, int], ranges: list[tuple[int, int]]) -> bool:
    return any(low <= touched[1] and touched[0] <= high for low, high in ranges)


def _head_index(symbols: list[Symbol]) -> dict[str, str]:
    """
    `model.symbol_key` -> the HEAD symbol's id.

    The same key the id is hashed from, so a file's module symbol and a same-named top-level
    member of it stay two entries here instead of one overwriting the other (E2 defect 1).
    That is `expected.json`'s `(path, qualname)` key (S2.17) plus the module marker.
    """
    return {symbol_key(s.path, s.qualname, s.kind): s.id for s in symbols}


# ------------------------------------------------------------------ plumbing


def _git_env() -> dict[str, str]:
    """
    The environment every git call runs under, for both `_git` and `_git_capped`.

    The user's global and system config are switched off for the same reason the tests do
    it: a `diff.noprefix` or an external diff driver on one machine would change what this
    parses, and nothing downstream would say why.
    """
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    env["GIT_TERMINAL_PROMPT"] = "0"
    for leaked in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(leaked, None)
    return env


def _git(checkout: Path, args: list[str], timeout_s: int, *, text: bool = True):
    """One git command against the checkout, never through a shell."""
    return subprocess.run(
        ["git", "-C", str(checkout), *args],
        capture_output=True,
        text=text,
        timeout=timeout_s,
        env=_git_env(),
    )


def _git_capped(checkout: Path, args: list[str], timeout_s: int, max_bytes: int) -> bytes | None:
    """
    One git command's stdout, read as it arrives and capped at `max_bytes`.

    `subprocess.run` cannot report a size until the whole output has been captured, so a
    commit with a gigabyte-sized diff would still cost real time being buffered, decoded and
    parsed before anyone could tell it was too big to bother with. Reading the pipe as it
    comes in means the process is killed, and the bytes past the cap are never even read,
    the moment that becomes clear. Raises `_DiffTooLarge` past the cap, and
    `subprocess.TimeoutExpired` past `timeout_s` -- the same exception `_git` raises, so
    callers do not need to know which path was used. `None` for a non-zero exit, matching
    `_git`'s callers.
    """
    proc = subprocess.Popen(
        ["git", "-C", str(checkout), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=_git_env(),
    )
    assert proc.stdout is not None
    deadline = time.monotonic() + timeout_s
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(proc.args, timeout_s)
            ready, _, _ = select.select([proc.stdout], [], [], remaining)
            if not ready:
                raise subprocess.TimeoutExpired(proc.args, timeout_s)
            chunk = os.read(proc.stdout.fileno(), 1 << 16)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise _DiffTooLarge(total)
            chunks.append(chunk)
        proc.wait(timeout=max(deadline - time.monotonic(), 0))
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    finally:
        proc.stdout.close()
    return None if proc.returncode != 0 else b"".join(chunks)
