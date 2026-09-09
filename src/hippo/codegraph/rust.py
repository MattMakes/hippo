"""
Pass 1 for Rust: one file's CST becomes `FileFacts`.

The same contract as `python.py` -- report what is written, resolve nothing -- with the
four things Rust does that neither Python nor TypeScript does:

* **A type's methods live outside the type.** `struct OrderService` is one item and
  `impl OrderService { ... }` is another, possibly in another file. The methods are still
  `OrderService.place`, so `SourceIndex.members` finds them; which *files* may hold them is
  `member_paths`, and every symbol keeps its own truthful line range (the struct's range is
  the struct, not the struct plus its impls -- see "line ranges" below).
* **A module is a file, a directory with a `mod.rs`, or an inline `mod x { }`.** The inline
  one is an ordinary container symbol of kind `module`, so `#[cfg(test)] mod tests` reads
  like the little test file it is.
* **Paths, not dots.** `crate::billing::total`, `super::OrderService`, `self::helper` --
  resolved against the crate root (`lib.rs`/`main.rs`, found once per source by
  `source_setup`) rather than against a dotted module name. Inside an inline `mod`, one
  `super::` per nesting level names *this* file, so the walker collapses those before the
  resolver ever sees them.
* **No exceptions.** `-> Result<_, E>` is the only thing that says what a function fails
  with (2.2b's RAISES row); `?`, `Err(...)` and `match ... Err(e)` say nothing, so they
  produce nothing. Rust has values, not exceptions, and there is no CATCHES edge at all.

**Line ranges.** Every symbol claims the lines it is actually written on, attributes
included (`#[test]` sits inside the test's passage, the way a Python decorator does) and doc
comments excluded (the way TypeScript leaves a JSDoc block to the container). A type whose
`impl` blocks are elsewhere in the file therefore has a *short* range and its methods have
ranges outside it; the chunker's container rule is lexical, so those impl bodies also appear
in the module's header passage. That is the honest reading -- stretching a struct over its
impls would make two types with interleaved impls claim each other's lines.
"""

from __future__ import annotations

import inspect
import posixpath
from typing import TYPE_CHECKING

from tree_sitter import Node

from .model import (
    SELF_NAMES,
    AssignFact,
    BaseFact,
    CallFact,
    FileFacts,
    ImportFact,
    LanguageRules,
    LiteralFact,
    RaiseFact,
    Symbol,
    module_qualname,
    symbol_id,
)
from .model import (
    is_test_path as shared_is_test_path,
)
from .treesitter import end_line_of, line_of, text_of

if TYPE_CHECKING:  # `resolve` imports the registry, which imports this module
    from .resolve import Resolution, SourceIndex

# A call under one of these is conditional. `match` counts: an arm is a branch, and the
# arm that calls `rollback` is exactly what WP3's path tools want to tell apart.
BRANCH_TYPES = {
    "if_expression",
    "else_clause",
    "match_expression",
    "match_arm",
    "for_expression",
    "while_expression",
    "loop_expression",
}

# Items a container's own walk stops at: what is inside belongs to another symbol.
ITEMS = {
    "function_item",
    "function_signature_item",
    "struct_item",
    "enum_item",
    "union_item",
    "trait_item",
    "impl_item",
    "mod_item",
}
# The items that become a `class`: everything a method or a trait bound can hang off.
TYPE_ITEMS = {"struct_item", "enum_item", "union_item", "trait_item"}
# `type X = ...`, `const`, `static` and `macro_rules!` stay in their container's header (2.2a).

# Associated functions that name their own type, so `OrderService::new().place()` knows what
# `place` is on. Deliberately short: `Config::load().validate()` must stay unresolved, the
# way Python's `Config.load().validate()` does.
CONSTRUCTORS = frozenset({"new", "default", "from", "with_capacity"})

# A file whose stem is one of these names the *directory* it is in, not a module beside it.
MODULE_FILES = ("mod", "lib", "main")
CRATE_ROOT_FILES = ("lib.rs", "main.rs")
# Directories whose files are test code. `tests/` and `benches/` are Cargo's own layout.
TEST_DIRS = ("benches",)


def walk(path: str, root: Node, source_id: str) -> FileFacts:
    """Turn one parsed Rust file into the facts resolve.py needs."""
    module = module_qualname(path)
    is_test = is_test_path(path)
    facts = FileFacts(path=path, lang="rust", module=module)

    module_symbol = Symbol(
        id=symbol_id(source_id, path, module),
        source_id=source_id,
        name=module.rpartition(".")[2] or module,
        qualname=module,
        kind="module",
        lang="rust",
        path=path,
        line_start=1,
        line_end=end_line_of(root),
        doc=_module_doc(root),
        is_test=is_test,
        module=module,
        display=module,
        statement_lines=_statement_lines(root),
    )
    facts.symbols.append(module_symbol)

    bodies: list[tuple[Symbol, Node, int]] = []
    _items(facts, root, "", source_id, is_test, bodies, 0)
    module_symbol.header_end = _header_end(module_symbol, facts.symbols, top_level=True)

    _imports(facts, root, 0)
    _walk_body(facts, module_symbol, root, 0)
    for symbol, body, depth in bodies:
        _walk_body(facts, symbol, body, depth)
    return facts


# ------------------------------------------------------------ the symbols


def _items(
    facts: FileFacts,
    block: Node,
    prefix: str,
    source_id: str,
    is_test: bool,
    bodies: list[tuple[Symbol, Node, int]],
    depth: int,
    kind: str = "function",
) -> None:
    """
    Every item directly inside `block` that becomes a symbol, in source order.

    `kind` is what a bare function in this block is: a `function` at module level, a
    `method` inside an `impl` or a `trait`. `depth` is how many inline `mod`s we are in,
    which is how many leading `super::`s still name this file.
    """
    for node in block.children:
        if node.type == "impl_item":
            _impl(facts, node, prefix, source_id, is_test, bodies, depth)
        elif node.type == "mod_item":
            _inline_module(facts, node, prefix, source_id, is_test, bodies, depth)
        elif node.type in TYPE_ITEMS:
            _type_item(facts, node, prefix, source_id, is_test, bodies, depth)
        elif node.type in ("function_item", "function_signature_item"):
            symbol = _symbol(facts, node, prefix, source_id, is_test, kind)
            _raises(facts, symbol, node)
            body = node.child_by_field_name("body")
            if body is not None:
                bodies.append((symbol, body, depth))


def _type_item(
    facts: FileFacts,
    node: Node,
    prefix: str,
    source_id: str,
    is_test: bool,
    bodies: list[tuple[Symbol, Node, int]],
    depth: int,
) -> None:
    """`struct`, `enum`, `union` and `trait` are all a `class`; only a trait holds members."""
    symbol = _symbol(facts, node, prefix, source_id, is_test, "class")
    if node.type != "trait_item":
        return  # a struct's members are its impls, and those are items of their own
    body = node.child_by_field_name("body")
    if body is None:
        return
    _items(facts, body, f"{symbol.qualname}.", source_id, symbol.is_test, bodies, depth, "method")
    symbol.header_end = _header_end(symbol, facts.symbols)


def _impl(
    facts: FileFacts,
    node: Node,
    prefix: str,
    source_id: str,
    is_test: bool,
    bodies: list[tuple[Symbol, Node, int]],
    depth: int,
) -> None:
    """
    `impl OrderService { ... }` is not a symbol -- its functions are methods of the type.

    `impl Base for OrderService` also says OrderService is a Base, which is 2.2b's INHERITS
    row: an interface implementation counts, and the trait's own method then becomes what
    the impl's method OVERRIDES.
    """
    type_name = _type_name(node.child_by_field_name("type"))
    if not type_name:
        return
    trait = node.child_by_field_name("trait")
    qualname = f"{prefix}{type_name}"
    if trait is not None:
        facts.bases.append(BaseFact(cls=qualname, base=_type_name(trait), line=line_of(node)))
    body = node.child_by_field_name("body")
    if body is not None:
        _items(facts, body, f"{qualname}.", source_id, is_test, bodies, depth, "method")


def _inline_module(
    facts: FileFacts,
    node: Node,
    prefix: str,
    source_id: str,
    is_test: bool,
    bodies: list[tuple[Symbol, Node, int]],
    depth: int,
) -> None:
    """`mod tests { ... }` is a container symbol of kind `module`; `mod helpers;` is an import."""
    body = node.child_by_field_name("body")
    if body is None:
        return
    symbol = _symbol(facts, node, prefix, source_id, is_test, "module")
    bodies.append((symbol, body, depth + 1))
    _items(facts, body, f"{symbol.qualname}.", source_id, symbol.is_test, bodies, depth + 1)
    symbol.header_end = _header_end(symbol, facts.symbols)


def _symbol(facts: FileFacts, node: Node, prefix: str, source_id: str, is_test: bool, kind: str) -> Symbol:
    """One item as a `Symbol`, appended to `facts` in source order."""
    name = text_of(node.child_by_field_name("name"))
    qualname = f"{prefix}{name}"
    body = node.child_by_field_name("body")
    symbol = Symbol(
        id=symbol_id(source_id, facts.path, qualname),
        source_id=source_id,
        name=name,
        qualname=qualname,
        kind=kind,
        lang="rust",
        path=facts.path,
        line_start=_item_start(node),
        line_end=end_line_of(node),
        signature=_signature(node, body),
        doc=_doc_above(node),
        is_test=is_test or _is_test_item(node),
        params=_params(node),
        module=facts.module,
        display=f"{facts.module}.{qualname}",
        statement_lines=_statement_lines(body) if body is not None else [],
    )
    symbol.header_end = symbol.line_end
    facts.symbols.append(symbol)
    return symbol


def _type_name(node: Node | None) -> str:
    """The type an `impl` is for, generics stripped: `Wrapper<T>` -> `Wrapper`, `a::B` -> `B`."""
    if node is None:
        return ""
    if node.type == "generic_type":
        return _type_name(node.child_by_field_name("type"))
    return text_of(node).rpartition("::")[2]


def _params(node: Node) -> list[str]:
    """Parameter names, in order. `self` is not one: it is the receiver, not an argument."""
    params = node.child_by_field_name("parameters")
    if params is None:
        return []
    names: list[str] = []
    for child in params.children:
        if child.type != "parameter":
            continue  # `self_parameter`, and the punctuation between them
        pattern = child.child_by_field_name("pattern")
        names.append(_one_line(text_of(pattern) if pattern is not None else text_of(child)))
    return [name for name in names if name]


def _signature(node: Node, body: Node | None) -> str:
    """
    The item down to its body, whitespace collapsed: `pub fn place(&self, o: &Order) ->
    Result<i64, OrderError>`. An item with no body (`pub struct X;`, a trait's required
    method) keeps its whole text without the `;`.
    """
    if node.text is None:
        return ""
    if body is None or body.start_byte < node.start_byte:
        return " ".join(text_of(node).split()).rstrip(";").strip()
    head = node.text[: body.start_byte - node.start_byte].decode("utf-8", errors="replace")
    return " ".join(head.split()).strip()


def _statement_lines(body: Node) -> list[int]:
    """Start lines of the body's own statements -- where an oversized passage may be split."""
    return [
        line_of(child)
        for child in body.children
        if child.is_named and child.type not in ("line_comment", "block_comment")
    ]


def _header_end(symbol: Symbol, symbols: list[Symbol], *, top_level: bool = False) -> int:
    """
    Last line of a container's header: everything before its first *lexical* member.

    A type whose `impl` blocks are written further down the file has no lexical member at
    all and keeps its own last line, which is the truth: its methods are elsewhere.
    """
    members = [s for s in symbols if s is not symbol and _is_member(symbol, s, top_level)]
    if not members:
        return symbol.line_end
    return min(m.line_start for m in members) - 1


def _is_member(parent: Symbol, child: Symbol, top_level: bool) -> bool:
    """
    Direct members only. The file's own module owns every undotted name -- an inline `mod`
    included, which is why `module` is in that list -- and every other container owns the
    names one dot below its own.
    """
    if top_level:
        return child.kind in ("class", "function", "module") and "." not in child.qualname
    prefix = f"{parent.qualname}."
    return child.qualname.startswith(prefix) and "." not in child.qualname[len(prefix) :]


# ------------------------------------------------------- attributes and docs


def _preceding(node: Node):
    """The attributes and comments written above an item, nearest first."""
    previous = node.prev_sibling
    while previous is not None and previous.type in ("attribute_item", "line_comment", "block_comment"):
        yield previous
        previous = previous.prev_sibling


def _item_start(node: Node) -> int:
    """
    The first line of a symbol's passage: its attributes, if it has any.

    `#[test]` belongs to the function the way `@pytest.mark.slow` belongs to a Python one.
    A doc comment does not extend the range -- it stays with the container, as a TypeScript
    JSDoc block does -- so `/// doc` above `#[derive(Debug)]` above `struct B` starts at the
    `#[derive]`.
    """
    line = line_of(node)
    for previous in _preceding(node):
        if previous.type == "attribute_item":
            line = line_of(previous)
    return line


def _attributes(node: Node) -> list[str]:
    """The text of each attribute above an item: `test`, `cfg(test)`, `derive(Debug)`."""
    found = [
        " ".join(text_of(c).split())
        for previous in _preceding(node)
        if previous.type == "attribute_item"
        for c in previous.children
        if c.type == "attribute"
    ]
    return list(reversed(found))


def _is_test_item(node: Node) -> bool:
    """`#[test]`, `#[tokio::test]` or `#[cfg(test)]` makes an item -- and its contents -- test code."""
    return any(
        attribute == "test"
        or attribute.endswith("::test")
        or attribute.replace(" ", "").startswith("cfg(test")
        for attribute in _attributes(node)
    )


def _doc_text(node: Node, marker: str) -> str | None:
    """
    A comment's doc text, or None when it is an ordinary comment (which ends a doc block).

    A `///` line carries its own newline, and the parts are joined with one, so it comes
    off here; a `/** */` block's ` * ` decoration comes off the way TypeScript strips a
    JSDoc's, and only for a block, because `* item` in a `///` line is a markdown bullet.
    """
    if not any(child.type == marker for child in node.children):
        return None
    text = "".join(text_of(child) for child in node.children if child.type == "doc_comment")
    if node.type != "block_comment":
        return text.rstrip("\n")
    lines = [line.strip().removeprefix("*").strip() for line in text.splitlines()]
    return "\n".join(lines).strip("\n")


def _doc_above(node: Node) -> str:
    """The `///` (or `/** */`) block written above an item, cleaned like a Python docstring."""
    parts: list[str] = []
    for previous in _preceding(node):
        if previous.type == "attribute_item":
            continue  # `#[derive]` may sit between the doc and the item
        text = _doc_text(previous, "outer_doc_comment_marker")
        if text is None:
            break
        parts.append(text)
    return inspect.cleandoc("\n".join(reversed(parts))).strip()


def _module_doc(root: Node) -> str:
    """`//!` at the top of the file is the module's own doc."""
    parts: list[str] = []
    for child in root.children:
        if child.type not in ("line_comment", "block_comment"):
            break
        text = _doc_text(child, "inner_doc_comment_marker")
        if text is not None:
            parts.append(text)
    return inspect.cleandoc("\n".join(parts)).strip()


# ---------------------------------------------------------- what bodies do


def _walk_body(facts: FileFacts, symbol: Symbol, body: Node, depth: int) -> None:
    """
    Calls, bindings and literals inside one symbol, attributed to it.

    A container's walk stops at each item, because that item is a symbol of its own. A
    function's does not: a closure and a nested `fn` are deliberately not symbols (2.2a), so
    what they call is attributed to the function they are written in.
    """
    container = symbol.kind in ("module", "class")
    for child in body.children:
        if container and child.type in ITEMS:
            continue
        stack = [child]
        while stack:
            node = stack.pop()
            _record(facts, symbol, node, depth)
            stack.extend(reversed(node.children))


def _record(facts: FileFacts, symbol: Symbol, node: Node, depth: int) -> None:
    if node.type == "call_expression":
        call = _call(symbol.qualname, node, depth)
        if call is not None:
            facts.calls.append(call)
    elif node.type in ("string_literal", "raw_string_literal"):
        content = "".join(text_of(c) for c in node.children if c.type == "string_content")
        if content:
            facts.literals.append(LiteralFact(caller=symbol.qualname, text=content, line=line_of(node)))
    elif node.type == "let_declaration":
        _binding(facts, symbol, node)
    elif node.type in ("identifier", "type_identifier") and symbol.is_test:
        if symbol.kind in ("function", "method"):
            facts.names.setdefault(text_of(node), []).append(line_of(node))


def _call(caller: str, node: Node, depth: int) -> CallFact | None:
    """
    One call site. `println!(...)` is not one: a macro invocation is not a call node at all,
    and 2.2b's "no edge for what we cannot resolve" would drop it anyway.
    """
    target = node.child_by_field_name("function")
    if target is not None and target.type == "generic_function":
        target = target.child_by_field_name("function")  # `collection::<Order>("x")`
    if target is None:
        return None
    receiver, name = "", ""
    if target.type == "field_expression":
        receiver = _receiver(target.child_by_field_name("value"), depth)
        name = text_of(target.child_by_field_name("field"))
    elif target.type == "scoped_identifier":
        receiver = _path(text_of(target.child_by_field_name("path")), depth)
        receiver = "" if receiver == "self" else receiver  # `self::helper()` is a bare name
        name = text_of(target.child_by_field_name("name"))
    elif target.type == "identifier":
        name = text_of(target)
    else:
        return None  # a call on an expression: `(f)(x)`, `handlers[0]()`
    return CallFact(
        caller=caller,
        receiver=receiver,
        name=name,
        line=line_of(node),
        in_branch=_in_branch(node),
        is_await=_is_await(node),
        args=_arguments(node),
    )


def _receiver(node: Node | None, depth: int) -> str:
    """
    What is written before the dot. `OrderService::new()` is the type -- the only guess this
    walker makes, and only for the associated functions that name their own type; anything
    else keeps its text, so `Config::load().validate()` stays unresolvable and
    `db.collection::<Order>("orders")` still reads as a Mongo chain.
    """
    if node is None:
        return ""
    if node.type == "call_expression":
        called = node.child_by_field_name("function")
        if called is not None and called.type == "scoped_identifier":
            if text_of(called.child_by_field_name("name")) in CONSTRUCTORS:
                return _path(text_of(called.child_by_field_name("path")), depth)
    text = _one_line(text_of(node))
    return _path(text, depth) if "::" in text and "(" not in text else text


def _path(text: str, depth: int) -> str:
    """
    A `::` path as the resolver should see it. One `super::` per inline `mod` we are inside
    names *this* file, so those come off: `super::OrderService` in `mod tests` is the local
    `OrderService`, and `use super::*` becomes a `self` import the resolver drops.
    """
    segments = [segment for segment in text.split("::") if segment]
    while depth > 0 and segments and segments[0] == "super":
        segments = segments[1:]
        depth -= 1
    return "::".join(segments) if segments else "self"


def _arguments(node: Node) -> list[str]:
    arguments = node.child_by_field_name("arguments")
    if arguments is None:
        return []
    return [_one_line(text_of(c)) for c in arguments.children if c.is_named]


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _in_branch(node: Node) -> bool:
    parent = node.parent
    while parent is not None and parent.type not in ITEMS and parent.type != "source_file":
        if parent.type in BRANCH_TYPES:
            return True
        parent = parent.parent
    return False


def _is_await(node: Node) -> bool:
    return node.parent is not None and node.parent.type == "await_expression"


def _binding(facts: FileFacts, symbol: Symbol, node: Node) -> None:
    """
    `let s = OrderService::new();` and `let s = OrderService { .. };` -- what a later
    `s.place()` has to go through. The value recorded is the *type*, not the call.
    """
    pattern = node.child_by_field_name("pattern")
    value = node.child_by_field_name("value")
    if pattern is None or value is None or pattern.type != "identifier":
        return
    built = ""
    if value.type == "struct_expression":
        built = _type_name(value.child_by_field_name("name"))
    elif value.type == "call_expression":
        called = value.child_by_field_name("function")
        if called is not None and called.type == "scoped_identifier":
            if text_of(called.child_by_field_name("name")) in CONSTRUCTORS:
                built = text_of(called.child_by_field_name("path")).rpartition("::")[2]
    if built:
        facts.assignments.append(
            AssignFact(scope=symbol.qualname, target=text_of(pattern), value=built, line=line_of(node))
        )


def _raises(facts: FileFacts, symbol: Symbol, node: Node) -> None:
    """
    What a function fails with: the error half of its `-> Result<_, E>` and nothing else.

    `?`, `Err(...)` and `match ... Err(e)` are values being moved around, not a raise and
    not a catch, so they say nothing. The line is the signature's: there is no throw site.
    """
    returns = node.child_by_field_name("return_type")
    if returns is None or returns.type != "generic_type":
        return
    if _type_name(returns.child_by_field_name("type")) != "Result":
        return
    arguments = returns.child_by_field_name("type_arguments")
    named = [c for c in arguments.children if c.is_named] if arguments is not None else []
    if len(named) != 2 or named[1].type not in ("type_identifier", "scoped_type_identifier"):
        return
    name = text_of(named[1]).rpartition("::")[2]
    if name:
        facts.exceptions.append(RaiseFact(caller=symbol.qualname, name=name, line=line_of(node)))


# ------------------------------------------------------------- the imports


def _imports(facts: FileFacts, node: Node, depth: int) -> None:
    """
    Every `use` and every `mod x;`, as written -- turning `crate::billing` into a file needs
    the crate root, which is `resolve_module`'s business.
    """
    for child in node.children:
        if child.type == "use_declaration":
            _use(facts, child, depth)
            continue
        if child.type == "mod_item":
            body = child.child_by_field_name("body")
            if body is None and depth == 0:
                # `mod store;` is "the file beside me": an import of `self::store`. Inside an
                # inline mod it would name a file under a directory no module of ours is in,
                # so there is nothing to point at and we say nothing.
                name = text_of(child.child_by_field_name("name"))
                facts.imports.append(ImportFact(module=f"self::{name}", alias=name, line=line_of(child)))
            if body is not None:
                _imports(facts, body, depth + 1)
            continue
        _imports(facts, child, depth)


def _use(facts: FileFacts, node: Node, depth: int) -> None:
    _use_tree(facts, node.child_by_field_name("argument"), "", line_of(node), depth)


def _use_tree(facts: FileFacts, node: Node | None, prefix: str, line: int, depth: int) -> None:
    """
    One `use` path, however many names it brings in. `{total, send_invoice as invoice}` is
    two facts; `{self, Base}` imports the module itself and one of its names; `::*` is a
    wildcard, which the resolver already prices at 0.60.
    """
    if node is None:
        return
    if node.type == "scoped_use_list":
        path = _join(prefix, text_of(node.child_by_field_name("path")))
        names = node.child_by_field_name("list")
        for child in names.children if names is not None else []:
            if child.is_named:
                _use_tree(facts, child, path, line, depth)
        return
    if node.type == "use_wildcard":
        path = _join(prefix, text_of(node).removesuffix("*").removesuffix("::"))
        facts.imports.append(ImportFact(module=_path(path, depth), line=line, is_wildcard=True))
        return
    if node.type == "use_as_clause":
        alias = text_of(node.child_by_field_name("alias"))
        _bind(facts, _join(prefix, text_of(node.child_by_field_name("path"))), alias, line, depth)
        return
    if node.type in ("scoped_identifier", "identifier", "crate", "self", "super", "metavariable"):
        _bind(facts, _join(prefix, text_of(node)), "", line, depth)


def _bind(facts: FileFacts, path: str, alias: str, line: int, depth: int) -> None:
    """One imported name: everything but the last segment is the module, the last is the name."""
    module, _, name = path.rpartition("::")
    if name == "self":  # `use crate::store::{self, Base}` imports the module itself
        module, name = module, ""
    if not module:  # `use serde;` -- a whole crate, ours or somebody else's
        module, name = name, ""
    local = alias or (name or module.rpartition("::")[2])
    facts.imports.append(ImportFact(module=_path(module, depth), name=name, alias=local, line=line))


def _join(prefix: str, text: str) -> str:
    return f"{prefix}::{text}" if prefix else text


# ------------------------------------------------------------ registration


def source_setup(docs: list) -> dict[str, str]:
    """
    The crate, read once per source: the directory holding `lib.rs`/`main.rs` (what `crate::`
    means) and the name other files spell it with (`use rsapp::orders::…`, which is how a
    binary and an integration test reach the library half of the same crate).

    The name comes from `Cargo.toml` when the source has one, and otherwise from the
    directory the crate root sits in -- `rsapp/src/lib.rs` is the crate `rsapp`, which is
    the layout `cargo new` produces.
    """
    roots: list[str] = []
    manifests: dict[str, str] = {}
    for doc in docs:
        title = (getattr(doc, "title", "") or getattr(doc, "path", "") or "").replace("\\", "/")
        head, _, tail = title.rpartition("/")
        if tail in CRATE_ROOT_FILES:
            roots.append(head)
        elif tail == "Cargo.toml":
            manifests[head] = getattr(doc, "text", "") or ""
    if not roots:
        return {"root": "", "crate": ""}
    root = min(roots, key=lambda path: (path.count("/") if path else -1, path))
    home = root.rpartition("/")[0] if root.rpartition("/")[2] == "src" else root
    return {"root": root, "crate": _package_name(manifests.get(home, "")) or _dir_name(home)}


def _package_name(manifest: str) -> str:
    """`name = "rsapp"` from a `Cargo.toml`'s `[package]` section."""
    section = ""
    for raw in manifest.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
        elif section == "package" and line.startswith("name"):
            _, _, value = line.partition("=")
            return value.strip().strip("\"'").replace("-", "_")
    return ""


def _dir_name(path: str) -> str:
    return path.rpartition("/")[2].replace("-", "_")


def _module_dir(path: str) -> str:
    """
    The directory a file's submodules live in: `src/lib.rs` owns `src/`, but `src/orders.rs`
    owns `src/orders/`. It is also what `self::` means and what `super::` walks up from.
    """
    head, _, tail = path.replace("\\", "/").rpartition("/")
    stem = tail.rsplit(".", 1)[0] if "." in tail else tail
    if stem in MODULE_FILES:
        return head
    return f"{head}/{stem}" if head else stem


def _module_file(index: SourceIndex, facts: FileFacts, text: str) -> FileFacts | None:
    """
    The file a `::` path names, or None when nothing in this source is it.

    A head that is neither `crate`, `self`, `super` nor this crate's own name is another
    crate -- `std`, `serde`, `sqlx` -- and gets no edge at all (2.2b).
    """
    segments = [segment for segment in text.split("::") if segment]
    if not segments:
        return None
    state = index.lang_state.get("rust") or {}
    head, rest = segments[0], segments[1:]
    if head == "crate" or (state.get("crate") and head == state["crate"]):
        base = state.get("root", "")
    elif head == "self":
        base = _module_dir(facts.path)
    elif head == "super":
        base = _module_dir(facts.path)
        while segments and segments[0] == "super":
            base, segments = base.rpartition("/")[0], segments[1:]
        rest = segments
    else:
        return None
    if not rest:
        if head == "self":
            return index.files.get(facts.path)
        candidates = [posixpath.join(base, name) for name in (*CRATE_ROOT_FILES, "mod.rs")]
    else:
        stem = posixpath.join(base, *rest)
        candidates = [f"{stem}.rs", f"{stem}/mod.rs"]
    for candidate in candidates:
        found = index.files.get(posixpath.normpath(candidate))
        if found is not None:
            return found
    return None


def resolve_module(index: SourceIndex, facts: FileFacts, spec: ImportFact) -> FileFacts | Resolution | None:
    """
    `use crate::billing::{total}` from `rsapp/src/orders.rs`, and every other Rust path.

    A path names a *module* if one exists -- `use crate::store;` binds the module, not a
    name inside it -- so the whole path is tried first and the module/name split second.
    Importing your own file is not an import: it would bind this file's own names through a
    weaker rule than `same_file` and quietly cost every one of them 0.10.
    """
    from .resolve import Resolution

    if spec.name:
        whole = _module_file(index, facts, _join(spec.module, spec.name))
        if whole is facts:
            return None
        if whole is not None:
            return Resolution(index.module_symbol(whole), 0.95, "import_path", is_module=True)
    found = _module_file(index, facts, spec.module)
    return found if found is not None and found is not facts else None


def member_paths(index: SourceIndex, qualname: str, path: str) -> list[str]:
    """
    Where a type's methods may be: any file with an `impl` for it, this one first so a
    method written beside the call still counts as `same_file`.
    """
    found = sorted({p for (p, owner) in index.members if owner == qualname and p != path})
    return [path, *found]


def is_test_path(path: str) -> bool:
    """Cargo's test layout: `tests/` and `benches/` beside the shared `test`/`tests` rule."""
    parts = path.replace("\\", "/").split("/")
    return shared_is_test_path(path) or any(part in TEST_DIRS for part in parts[:-1])


def test_stem(path: str) -> str | None:
    """
    The module a crate-level test file is named after: `tests/orders.rs` -> `orders`.

    Rust does not decorate the name -- an integration test is simply `tests/<module>.rs` --
    so the directory is the whole signal, and `tests/common/mod.rs` names no module at all.
    """
    if not is_test_path(path):
        return None
    stem = module_qualname(path).rpartition(".")[2]
    return None if stem in MODULE_FILES else stem


def is_test_function(symbol: Symbol) -> bool:
    """
    Every function in Rust test code is a case: `#[test]`, not the name, is what marks one,
    and by the time we are asked the symbol is already known to be test code.
    """
    return symbol.kind in ("function", "method")


# What `languages.RULES["rust"]` is. `Self` is already on `self_names` there, from L0.
RULES_ENTRY = LanguageRules(
    name="rust",
    line_comment="//",
    walk=walk,
    resolve_module=resolve_module,
    module_qualname=module_qualname,
    is_test_path=is_test_path,
    test_stem=test_stem,
    is_test_function=is_test_function,
    member_paths=member_paths,
    self_names=SELF_NAMES | {"Self"},
    source_setup=source_setup,
)
