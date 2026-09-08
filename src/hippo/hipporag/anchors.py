"""
Finding the symbols a question actually names. Pure, deterministic, no model call.

A question that contains code names things exactly: an identifier, a traceback, a pasted snippet, a
diff. `find_anchors` turns those into seed nodes for Personalized PageRank, which is what lets a
bare stack trace retrieve the right functions even when no *fact* survives the recognition-memory
filter. `split_question` separates the two halves of such a question, so a forty-line traceback
cannot swallow the one sentence that says what is being asked.

**The bare-word rule is the load-bearing part, and it is not the one PLAN.md first wrote.** Spike 1
(`research/S0-spikes.md`) measured the planned rule - a word of three characters or more, not in a
stoplist, matching a symbol `name` exactly - against 118 ordinary prose questions and four symbol
sets. It fired on 16% of prose questions against Django's 12 317 symbols and 4% against hippo's own,
because `country`, `library`, `city`, `status` and `run` are both English words and symbol names, and
a stoplist big enough to cover them is an English dictionary that also kills the real questions. So a
bare word anchors here only when **its surface form is code-shaped**: qualified (`a.b`), backticked,
PascalCase, camelCase, snake_case or ALL_CAPS. That measured zero false anchors on all four repos.

Two corrections travel with it and the zero depends on the first:

* the three-character minimum applies to the **segment matched against `Symbol.name`**, not to the
  raw token - otherwise the prose abbreviation `S.O.B.` falls through to `b` and anchors on Django's
  one-character `DateFormat.b`;
* a dotted token counts as qualified only when **every dot-separated part is at least two
  characters** - otherwise `e.g.` and `U.S.A.` enter through the qualified branch, which is exempt
  from every bare-word defence.

The cost is real and is documented rather than hidden: "what does run do" names a single-token
lowercase symbol and produces no anchor, so `used_code_seeds` stays False and the select pass, the
path block and `timing["paths"]` do not run. Dense seeding can still surface the passage; typing
``what does `run` do`` or `GraphIndex.load` restores all of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .graph_index import DATA, SYMBOL, CodeNode, GraphIndex
from .paths import display_of

MAX_ANCHORS = 20  # how many seeds one question may contribute at all
MAX_MATCHES_PER_TOKEN = 8  # how many symbols one ambiguous token may seed
AMBIGUOUS_ABOVE = 10  # more matches than this and the token seeds nothing (S2.13)
MIN_NAME_CHARS = 3  # applied to the matched name segment, not the raw token (spike 1, finding 2)
MIN_QUALIFIED_PART = 2  # `e.g.` is not a qualified name (spike 1, finding 3)
FRAME_DECAY = 0.8  # a stack frame's weight, 0.8 ** k outward from the innermost
EXCEPTION_WEIGHT = 0.8

IDENTIFIER = "identifier"
STACK_TRACE = "stack_trace"
EXCEPTION = "exception"
FENCED_CODE = "fenced_code"
DIFF = "diff"

# Inert on prose once the surface-form rule above is in (spike 1), and `test_anchors.py` empties it
# to prove that. It is kept for the branches that rule exempts: a backticked or qualified `self.get`
# should not seed every `get` in the repo.
STOPLIST = frozenset(
    {
        "and",
        "are",
        "but",
        "can",
        "does",
        "for",
        "from",
        "get",
        "has",
        "how",
        "not",
        "set",
        "the",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "you",
    }
)

CODE_SUFFIXES = ("py", "pyi", "ts", "tsx", "js", "jsx", "mjs", "cjs", "sql", "go", "rb", "java")

_FENCE_MARKER = re.compile(r"^\s*```")
_FENCE = re.compile(r"```[^\n]*\n(.*?)(?:\n\s*```|\Z)", re.DOTALL)
_BACKTICK = re.compile(r"`([^`\n]+)`")
_QUALIFIED = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b")
_BARE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_PASCAL = re.compile(r"^[A-Z][a-z0-9]*(?:[A-Z][a-z0-9]*)+$")
_CAMEL = re.compile(r"^[a-z][a-z0-9]*(?:[A-Z][a-z0-9]*)+$")
_SNAKE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+$")
_ALLCAPS = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")

_SUFFIX_GROUP = "|".join(CODE_SUFFIXES)
_PY_FRAME = re.compile(r'File "([^"\n]+)", line (\d+), in (\S+)')
_JS_FRAME = re.compile(r"\bat\s+([\w.$<>]+)\s*\(([^()\s:]+):(\d+):(\d+)\)")
_PATH_LINE = re.compile(rf"\b([\w./\\-]+\.(?:{_SUFFIX_GROUP}))[:(](\d+)")
_EXCEPTION_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception))\s*:", re.MULTILINE)

_DIFF_FILE = re.compile(r"^\+\+\+ (?:[ab]/)?(\S+)")
_DIFF_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

# What makes a *line* code, used only when the question has more than one line (S2.12). A one-line
# question always splits to `(text, "")`, which is what keeps every prose question on the path it
# takes today.
_STACK_ISH = re.compile(
    r'File "[^"\n]+", line \d+'
    r"|^\s*at \S+ \("
    rf"|\b[\w./\\-]+\.(?:{_SUFFIX_GROUP}):\d+"
    r"|^Traceback \(most recent call last\)"
)
_DIFF_ISH = re.compile(r"^(?:@@ |diff --git |--- |\+\+\+ |[+-][^\s+-])")
_STATEMENT = re.compile(
    r"^\s*(?:def |class |return\b|import |from \s*[\w.]+ import |raise |await |yield "
    r"|const |let |var |function |export |public |private |#include|//|/\*|\*/|[{}])"
)
_ENDS_LIKE_CODE = re.compile(r"[)\]}\"']\s*[;{]\s*$|^\s*\S.*[;{]\s*$")
_ARROW = re.compile(r"=>|->")
_INDENTED_CALL = re.compile(r"^\s+[A-Za-z_][\w.\[\]]*\s*(?:=[^=]|\()")


@dataclass
class Anchor:
    """
    One symbol (or data object) a question named, and how it named it.

    `weight` is the share of `code_seed_weight` this anchor claims, already divided by the token's
    fan-out: a name matching three symbols gives each of them a third, so an ambiguous mention
    cannot outweigh an exact one (S2.13). `ambiguous` rows are the tokens that matched *too many*
    symbols to be worth seeding at all - they carry no node and no weight, and exist so the trace
    (and the Analyze page) can say why nothing was seeded.
    """

    node_id: str
    vertex: int
    token: str
    how: str  # identifier | stack_trace | exception | fenced_code | diff
    kind: str  # "symbol" or "data"
    weight: float
    n_matches: int = 1  # the pre-cap count of everything this token matched
    ambiguous: bool = False


# ------------------------------------------------------- splitting a question


def split_question(text: str) -> tuple[str, str]:
    """
    Separate the prose of a question from the code pasted into it (S2.12).

    The prose half is what gets embedded and what the fact filter reads; the whole question still
    reaches the QA prompt, and `find_anchors` reads both halves. Without this a forty-line traceback
    dominates the single query vector and the question sentence stops mattering.

    **A one-line question always returns `(text, "")`**, so every prose question takes exactly the
    path it takes today. That is this adaptation's inert condition, and it is a test.
    """
    if not text or not text.strip():
        return text or "", ""
    if "```" not in text and len(text.strip().splitlines()) == 1:
        return text, ""

    prose: list[str] = []
    code: list[str] = []
    fenced = False
    for line in text.splitlines():
        if _FENCE_MARKER.match(line):
            fenced = not fenced
            continue  # the ``` marker itself belongs to neither half
        (code if fenced or _is_code_line(line) else prose).append(line)
    return "\n".join(prose).strip(), "\n".join(code).strip()


def _is_code_line(line: str) -> bool:
    if not line.strip():
        return False
    if _STACK_ISH.search(line) or _DIFF_ISH.match(line) or _EXCEPTION_LINE.match(line):
        return True
    if _STATEMENT.match(line):
        return True
    if _ENDS_LIKE_CODE.search(line):
        return True
    if _ARROW.search(line) and re.search(r"[()\[\]{}]", line):
        return True
    return bool(_INDENTED_CALL.match(line))


# --------------------------------------------------------------- the anchors


def find_anchors(question: str, index: GraphIndex) -> list[Anchor]:
    """
    Every code node this question names, strongest first.

    Reads both halves of `split_question`: a symbol named in the prose ("what does `GraphIndex.load`
    do") anchors just as one named in a pasted frame does. Every hit is looked up through *this*
    index's `idx_of` and kept only when its vertex is a symbol or data object, so a scoped index can
    never surface a node the caller may not see.
    """
    prose, code = split_question(question)
    fenced = "\n".join(_FENCE.findall(question))

    found: list[Anchor] = []
    found += _diff_anchors(question, index)
    found += _frame_anchors(question, index)
    found += _exception_anchors(question, index)
    found += _token_anchors(_plain(fenced), index, how=FENCED_CODE, strict=False)
    # The code half minus the fenced blocks: pasted lines the fence did not mark.
    found += _token_anchors(_plain(_without(code, fenced)), index, how=IDENTIFIER, strict=False)
    # The prose half is where spike 1's surface-form rule bites.
    found += _token_anchors(prose, index, how=IDENTIFIER, strict=True)

    return _best(found)


def _without(text: str, fenced: str) -> str:
    """The code half with the fenced lines removed, so a token inside a fence is not counted twice."""
    if not fenced:
        return text
    drop = {line.strip() for line in fenced.splitlines() if line.strip()}
    return "\n".join(line for line in text.splitlines() if line.strip() not in drop)


def _plain(text: str) -> str:
    """
    Pasted code with the lines that already have their own rule taken out.

    A frame line, a hunk header and the trailing `SomeError:` are read by `_frame_anchors`,
    `_diff_anchors` and `_exception_anchors`, which is where the `0.8 ** k` decay and the 0.8
    exception weight come from. Letting the plain tokenizer see them again would re-seed the same
    symbols at a flat 1.0 and the decay would mean nothing.
    """
    keep = []
    for line in text.splitlines():
        handled = (
            _PY_FRAME.search(line)
            or _JS_FRAME.search(line)
            or _PATH_LINE.search(line)
            or _DIFF_ISH.match(line)
            or _EXCEPTION_LINE.match(line)
            or line.startswith("Traceback")
        )
        if not handled:
            keep.append(line)
    return "\n".join(keep)


def _best(found: list[Anchor]) -> list[Anchor]:
    """One row per node (the strongest wins), ambiguity rows kept, capped at `MAX_ANCHORS`."""
    strongest: dict[str, Anchor] = {}
    ambiguous: list[Anchor] = []
    for anchor in found:
        if anchor.ambiguous:
            if not any(a.token == anchor.token for a in ambiguous):
                ambiguous.append(anchor)
            continue
        current = strongest.get(anchor.node_id)
        if current is None or anchor.weight > current.weight:
            strongest[anchor.node_id] = anchor
    ranked = sorted(strongest.values(), key=lambda a: (-a.weight, a.node_id))[:MAX_ANCHORS]
    return ranked + ambiguous


# ----------------------------------------------------------------- matching


def _anchor(index: GraphIndex, node_id: str, token: str, how: str, weight: float, n: int) -> Anchor | None:
    vertex = index.idx_of.get(node_id)
    if vertex is None or index.node_kind[vertex] not in (SYMBOL, DATA):
        return None
    return Anchor(node_id, vertex, token, how, index.node_kind[vertex], weight, n_matches=n)


def _code_shaped(token: str) -> bool:
    """Spike 1's fallback (b): a bare word anchors only when the user typed it as code."""
    return bool(_PASCAL.match(token) or _CAMEL.match(token) or _SNAKE.match(token) or _ALLCAPS.match(token))


def _ordered(index: GraphIndex, node_ids: list[str]) -> list[str]:
    """A stable order for a token's matches: by what a person reads, then by id."""
    unique = list(dict.fromkeys(node_ids))
    return sorted(unique, key=lambda nid: (display_of(index.code_node_by_id(nid)), nid))


def _visible(index: GraphIndex, node_id: str) -> CodeNode | None:
    vertex = index.idx_of.get(node_id)
    if vertex is None or index.node_kind[vertex] not in (SYMBOL, DATA):
        return None
    return index.code_node_at(vertex)


def _name_hits(index: GraphIndex, segment: str) -> list[str]:
    """Nodes whose `name` *is* this segment. The name index also holds split tokens, so `order`
    reaches `OrderService` there - which is right for synonyms and wrong for an exact anchor."""
    low = segment.lower()
    hits = []
    for node_id in index.name_index.get(low, ()):
        node = _visible(index, node_id)
        if node is not None and (node.name or "").lower() == low:
            hits.append(node_id)
    return _ordered(index, hits)


def _qualified_hits(index: GraphIndex, token: str) -> tuple[list[str], str]:
    """
    The longest dotted suffix of a qualified token that names something: `a.b.C.d` -> `C.d`.

    `name_index` holds the *module-relative* qualname (`OrderService.place`), never the
    fully-qualified display name, so the candidates come from the last segment and are then
    filtered on the display name. That is what makes `pkg.mod1.handle_it` pick one of three
    same-named functions instead of splitting between them (S2.13: a qualified match is never
    split, because the dots already say which one it is).
    """
    low = token.lower()
    parts = low.split(".")
    pool = list(dict.fromkeys([*index.name_index.get(parts[-1], ()), *index.name_index.get(low, ())]))
    for start in range(len(parts) - 1):
        key = ".".join(parts[start:])
        hits = []
        for node_id in pool:
            node = _visible(index, node_id)
            if node is None:
                continue
            for form in (display_of(node).lower(), (node.qualname or "").lower()):
                if form == key or form.endswith("." + key):
                    hits.append(node_id)
                    break
        if hits:
            return _ordered(index, hits), key
    return [], ""


def _token_anchors(text: str, index: GraphIndex, *, how: str, strict: bool) -> list[Anchor]:
    out: list[Anchor] = []
    for token, surface in _tokens(text):
        out += _match(index, token, surface, how=how, strict=strict, weight=1.0)
    return out


def _tokens(text: str) -> list[tuple[str, str]]:
    """(token, surface) pairs. Backticked and dotted spans stay whole: a path-qualified match names
    one symbol by construction and is never split (S2.13)."""
    if not text:
        return []
    out: list[tuple[str, str]] = []
    for match in _BACKTICK.finditer(text):
        out.append((match.group(1).strip(), "backtick"))
    rest = _BACKTICK.sub(" ", text)
    masked = list(rest)
    for match in _QUALIFIED.finditer(rest):
        out.append((match.group(0), "qualified"))
        for i in range(*match.span()):
            masked[i] = " "
    for match in _BARE.finditer("".join(masked)):
        out.append((match.group(0), "bare"))
    return out


def _match(
    index: GraphIndex, token: str, surface: str, *, how: str, strict: bool, weight: float
) -> list[Anchor]:
    cleaned = token.strip().strip("`").strip()
    if cleaned.endswith("()"):
        cleaned = cleaned[:-2]
    if not cleaned:
        return []
    parts = cleaned.split(".")
    qualified = len(parts) > 1 and all(len(part) >= MIN_QUALIFIED_PART for part in parts)

    if qualified:
        hits, _key = _qualified_hits(index, cleaned)
        if hits:
            # Never split: the dots already say which one it is.
            found = [_anchor(index, nid, cleaned, how, weight, len(hits)) for nid in hits]
            return [a for a in found if a is not None]

    segment = parts[-1]
    if len(segment) < MIN_NAME_CHARS or segment.lower() in STOPLIST:
        return []
    if strict and surface == "bare" and not _code_shaped(cleaned):
        return []

    hits = _name_hits(index, segment)
    n_matches = len(hits)  # pre-cap: the ambiguity rule is decided before the per-token cap (S2.13)
    if n_matches == 0:
        return []
    if n_matches > AMBIGUOUS_ABOVE:
        return [Anchor("", -1, cleaned, how, "", 0.0, n_matches=n_matches, ambiguous=True)]
    share = weight / n_matches
    found = [_anchor(index, nid, cleaned, how, share, n_matches) for nid in hits[:MAX_MATCHES_PER_TOKEN]]
    return [a for a in found if a is not None]


# ------------------------------------------------------------- stack frames


def _frames(text: str) -> list[tuple[str, int, str]]:
    """(path, line, function) innermost first. Python lists frames outermost first; V8 does not."""
    python = [(m.group(1), int(m.group(2)), m.group(3)) for m in _PY_FRAME.finditer(text)]
    if python:
        return list(reversed(python))
    v8 = [(m.group(2), int(m.group(3)), m.group(1)) for m in _JS_FRAME.finditer(text)]
    if v8:
        return v8
    return [(m.group(1), int(m.group(2)), "") for m in _PATH_LINE.finditer(text)]


def _same_path(a: str, b: str) -> bool:
    a, b = a.replace("\\", "/").lstrip("./"), b.replace("\\", "/").lstrip("./")
    return bool(a) and bool(b) and (a == b or a.endswith("/" + b) or b.endswith("/" + a))


def _frame_anchors(text: str, index: GraphIndex) -> list[Anchor]:
    out: list[Anchor] = []
    for depth, (path, line, name) in enumerate(_frames(text)):
        weight = FRAME_DECAY**depth
        token = f"{path}:{line}"
        in_file = [
            node
            for node in index.code_nodes
            if node.kind == SYMBOL and _visible(index, node.id) is not None and _same_path(node.path, path)
        ]
        containing = [n for n in in_file if n.line_start <= line <= n.line_end]
        if containing:
            # The innermost definition wins: a method, not the class or module that spans it.
            best = min(containing, key=lambda n: (n.line_end - n.line_start, n.qualname, n.id))
            anchor = _anchor(index, best.id, token, STACK_TRACE, weight, 1)
            if anchor is not None:
                out.append(anchor)
                continue
        if name:
            # The line drifted (the file was edited since the traceback was captured): fall back to
            # the function the frame names, in this file if we can, anywhere if we cannot.
            named = [n.id for n in in_file if (n.name or "").lower() == name.split(".")[-1].lower()]
            hits = _ordered(index, named) or _name_hits(index, name.split(".")[-1])
            if len(hits) > AMBIGUOUS_ABOVE:
                out.append(Anchor("", -1, name, STACK_TRACE, "", 0.0, n_matches=len(hits), ambiguous=True))
                continue
            share = weight / len(hits) if hits else weight
            for node_id in hits[:MAX_MATCHES_PER_TOKEN]:
                anchor = _anchor(index, node_id, name, STACK_TRACE, share, len(hits))
                if anchor is not None:
                    out.append(anchor)
    return out


def _exception_anchors(text: str, index: GraphIndex) -> list[Anchor]:
    """The `SomeError: message` line a traceback ends with names a class; seed it at 0.8."""
    matches = _EXCEPTION_LINE.findall(text)
    if not matches:
        return []
    return _match(
        index,
        matches[-1],
        "qualified" if "." in matches[-1] else "bare",
        how=EXCEPTION,
        strict=False,
        weight=EXCEPTION_WEIGHT,
    )


# -------------------------------------------------------------------- diffs


def _diff_anchors(text: str, index: GraphIndex) -> list[Anchor]:
    """
    A pasted patch names its symbols by line: the new-side hunk ranges, intersected.

    Only the *innermost* symbol over each hunk, the same rule a stack frame follows. A class spans
    every method it contains, so without this a one-line change inside one method would seed the
    class, the method, and on a nested class everything in between - and "what did this patch
    touch" would answer "most of the file".
    """
    out: list[Anchor] = []
    path = ""
    for line in text.splitlines():
        file_match = _DIFF_FILE.match(line)
        if file_match:
            path = file_match.group(1)
            continue
        hunk = _DIFF_HUNK.match(line)
        if not hunk or not path:
            continue
        start = int(hunk.group(1))
        end = start + max(1, int(hunk.group(2) or 1)) - 1
        touched = [
            node
            for node in index.code_nodes
            if node.kind == SYMBOL
            and node.code_kind != "module"
            and _same_path(node.path, path)
            and node.line_start <= end
            and start <= node.line_end
        ]
        for node in touched:
            if any(_contains(node, other) for other in touched):
                continue  # something more specific inside this one also matched
            anchor = _anchor(index, node.id, f"{path}:{start}", DIFF, 1.0, 1)
            if anchor is not None:
                out.append(anchor)
    return out


def _contains(outer: CodeNode, inner: CodeNode) -> bool:
    return outer.id != inner.id and outer.line_start <= inner.line_start and inner.line_end <= outer.line_end


__all__ = [
    "AMBIGUOUS_ABOVE",
    "Anchor",
    "DIFF",
    "EXCEPTION",
    "FENCED_CODE",
    "IDENTIFIER",
    "MAX_ANCHORS",
    "MAX_MATCHES_PER_TOKEN",
    "STACK_TRACE",
    "STOPLIST",
    "find_anchors",
    "split_question",
]
