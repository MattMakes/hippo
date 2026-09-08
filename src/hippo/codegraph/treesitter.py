"""
The tree-sitter plumbing: grammars, parsers and the handful of node helpers the two
walkers share.

Three facts about tree-sitter 0.26 that cost an afternoon to find (R4 T9), so they are
written down rather than rediscovered:

* `tree_sitter.Query` has no `.captures()`; it moved to `QueryCursor(query).captures(node)`.
  The walkers here do not use queries at all -- they walk the CST with `child_by_field_name`,
  because a call site is only useful together with the symbol that encloses it and the
  branch depth it sits at, and a capture list throws both away.
* `language_tsx()` parses plain JS and JSX cleanly, so `.js/.jsx/.mjs/.cjs` need no third
  wheel. `.ts` uses `language_typescript()`, which JSX would confuse.
* Fragments parse tolerantly: a bare conditional assignment yields no error node and keeps
  every identifier. That is what will let WP3 pull anchors out of a pasted snippet.

`Language` objects are immutable and shared; a `Parser` is not thread-safe, so
`new_parser` builds a fresh one per `extract_code` call (two index jobs can run at once).
"""

from __future__ import annotations

from functools import cache

from tree_sitter import Language, Node, Parser

# The three grammars. `lang_of` in ingest/readers.py maps a file name to "python",
# "typescript" or "sql"; only the first two are parsed here, and "typescript" picks
# between the two TS dialects by suffix.
GRAMMARS = ("python", "typescript", "tsx")

# Suffixes that JSX would confuse the plain TypeScript grammar with.
TSX_SUFFIXES = (".tsx", ".js", ".jsx", ".mjs", ".cjs")


@cache
def get_language(grammar: str) -> Language:
    """Build (once) one of the three `Language`s. Raises on an unknown grammar name."""
    if grammar == "python":
        import tree_sitter_python

        return Language(tree_sitter_python.language())
    if grammar in ("typescript", "tsx"):
        import tree_sitter_typescript

        source = (
            tree_sitter_typescript.language_tsx()
            if grammar == "tsx"
            else tree_sitter_typescript.language_typescript()
        )
        return Language(source)
    raise ValueError(f"unknown grammar: {grammar!r}")


def grammar_for(path: str, lang: str) -> str:
    """Which grammar parses this file: TSX for JS/JSX/TSX, plain TypeScript for `.ts`."""
    if lang == "python":
        return "python"
    return "tsx" if path.lower().endswith(TSX_SUFFIXES) else "typescript"


def new_parser(grammar: str) -> Parser:
    """A fresh parser for one grammar. One per `extract_code` call: parsers are not thread-safe."""
    return Parser(get_language(grammar))


# ------------------------------------------------------------ node helpers


def text_of(node: Node | None) -> str:
    """A node's source text. `None` (a missing optional field) reads as the empty string."""
    if node is None or node.text is None:
        return ""
    return node.text.decode("utf-8", errors="replace")


def line_of(node: Node) -> int:
    """1-based start line, the way every other line number in hippo is counted."""
    return node.start_point[0] + 1


def end_line_of(node: Node) -> int:
    """
    1-based end line. tree-sitter's end point sits *after* the last character, so a node
    ending at the very start of a line does not own that line.
    """
    row, column = node.end_point
    return row if column == 0 and row > node.start_point[0] else row + 1


def named_children(node: Node) -> list[Node]:
    return [child for child in node.children if child.is_named]


def field_child(node: Node, name: str) -> Node | None:
    return node.child_by_field_name(name)


def walk_tree(node: Node):
    """Every node in the subtree, parents before children, left to right."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))
