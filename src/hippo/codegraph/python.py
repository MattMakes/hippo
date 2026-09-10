"""
Pass 1 for Python: one file's CST becomes `FileFacts`.

A walker's job is to say what is *written*, never what it means. `invoice(order)` is
recorded as "a call named `invoice` with no receiver, on line 19, inside a branch"; whether
that is `pyapp.billing.send_invoice` is resolve.py's problem, and it cannot be answered
without the rest of the source.

What becomes a symbol (2.2a): the module, every class, every module-level function and
every method, however deeply classes nest (`Outer.Inner.method`). A function nested inside
a function, a lambda and a comprehension do not -- they stay inside the enclosing symbol's
passage, which is what keeps a passage readable.
"""

from __future__ import annotations

import inspect

from tree_sitter import Node

from .model import (
    AssignFact,
    BaseFact,
    CallFact,
    FileFacts,
    ImportFact,
    LanguageRules,
    LiteralFact,
    RaiseFact,
    Symbol,
    is_test_path,
    module_qualname,
    package_of,
    symbol_id,
)
from .treesitter import end_line_of, line_of, text_of

# A call under one of these is conditional: `extra["in_branch"]` says so, and WP3's path
# tools read it to tell "always calls" from "calls only when something went wrong".
BRANCH_TYPES = {
    "if_statement",
    "elif_clause",
    "else_clause",
    "for_statement",
    "while_statement",
    "try_statement",
    "except_clause",
    "finally_clause",
    "with_statement",
    "match_statement",
    "case_clause",
    "conditional_expression",
}

# Nodes that define something. A walk of one symbol's body stops at these: what is inside
# belongs to another symbol (a method), or to nobody (a nested function).
DEFINITIONS = {"class_definition", "function_definition", "decorated_definition"}


def resolve_module(index, facts: FileFacts, spec: ImportFact) -> FileFacts | None:
    """
    `from ..b import c` in `a/x/y.py`: walk `spec.level` packages up, then down `spec.module`.

    One dot means "the package this module is in", and for `pyapp/__init__.py` that package
    is `pyapp` itself, not its parent -- `from .orders import X` inside `pyapp/__init__.py`
    must reach `pyapp.orders`, which dropping a component would miss.
    """
    origin, text, level = facts.module, spec.module, spec.level
    if not level:
        return index.module(text)
    base = package_of(origin) if origin.endswith(".__init__") else origin.rpartition(".")[0]
    for _ in range(level - 1):
        base = base.rpartition(".")[0]
    target = f"{base}.{text}" if base and text else (base or text)
    return index.module(target)


def walk(path: str, root: Node, source_id: str) -> FileFacts:
    """Turn one parsed Python file into the facts resolve.py needs."""
    module = module_qualname(path)
    is_test = is_test_path(path)
    facts = FileFacts(path=path, lang="python", module=module)

    module_symbol = Symbol(
        id=symbol_id(source_id, path, module, "module"),
        source_id=source_id,
        name=module.rpartition(".")[2] or module,
        qualname=module,
        kind="module",
        lang="python",
        path=path,
        line_start=1,
        line_end=end_line_of(root),
        doc=_docstring(root),
        is_test=is_test,
        module=module,
        display=module,
        statement_lines=_statement_lines(root),
    )
    facts.symbols.append(module_symbol)

    bodies: list[tuple[Symbol, Node]] = []
    _definitions(facts, root, module_symbol, "", source_id, is_test, bodies)
    module_symbol.header_end = _header_end(module_symbol, facts.symbols)

    _imports(facts, root)
    _walk_body(facts, module_symbol, root, is_test)
    for symbol, body in bodies:
        _walk_body(facts, symbol, body, is_test)
    return facts


# ------------------------------------------------------------ the symbols


def _definitions(
    facts: FileFacts,
    block: Node,
    parent: Symbol,
    prefix: str,
    source_id: str,
    is_test: bool,
    bodies: list[tuple[Symbol, Node]],
) -> None:
    """Every class/function directly inside `block`, in source order. Recurses into classes only."""
    for child in block.children:
        node = child.child_by_field_name("definition") if child.type == "decorated_definition" else child
        if node is None or node.type not in ("class_definition", "function_definition"):
            continue
        name = text_of(node.child_by_field_name("name"))
        if not name:
            continue
        qualname = f"{prefix}{name}"
        body = node.child_by_field_name("body")
        is_class = node.type == "class_definition"
        kind = "class" if is_class else ("method" if prefix else "function")
        symbol = Symbol(
            id=symbol_id(source_id, facts.path, qualname, kind),
            source_id=source_id,
            name=name,
            qualname=qualname,
            kind=kind,
            lang="python",
            path=facts.path,
            # The *decorated* node, so `@app.route(...)` sits inside the symbol's passage
            # and no line of the file belongs to nobody.
            line_start=line_of(child),
            line_end=end_line_of(child),
            signature=_signature(node, body),
            doc=_docstring(body) if body is not None else "",
            is_test=is_test,
            params=_params(node),
            module=facts.module,
            display=f"{facts.module}.{qualname}",
            statement_lines=_statement_lines(body) if body is not None else [],
        )
        symbol.header_end = symbol.line_end
        facts.symbols.append(symbol)
        _decorators(facts, symbol, child)
        if body is None:
            continue
        bodies.append((symbol, body))
        if is_class:
            for base in _base_names(node):
                facts.bases.append(BaseFact(cls=qualname, base=base, line=line_of(node)))
            _definitions(facts, body, symbol, f"{qualname}.", source_id, is_test, bodies)
            symbol.header_end = _header_end(symbol, facts.symbols)


def _decorators(facts: FileFacts, symbol: Symbol, node: Node) -> None:
    """
    `@app.route("/x")` is a call the decorated symbol makes (2.2b), so it is recorded
    against that symbol. `@plain` is a call with no arguments; either resolves or, like any
    other unresolvable call, produces no edge.
    """
    if node.type != "decorated_definition":
        return
    for child in node.children:
        if child.type != "decorator":
            continue
        expression = next((c for c in child.children if c.is_named), None)
        if expression is None:
            continue
        if expression.type == "call":
            facts.calls.append(_call(symbol.qualname, expression))
        elif expression.type in ("identifier", "attribute"):
            receiver, name = "", text_of(expression)
            if expression.type == "attribute":
                receiver = _one_line(text_of(expression.child_by_field_name("object")))
                name = text_of(expression.child_by_field_name("attribute"))
            facts.calls.append(
                CallFact(caller=symbol.qualname, receiver=receiver, name=name, line=line_of(child))
            )


def _base_names(node: Node) -> list[str]:
    args = node.child_by_field_name("superclasses")
    if args is None:
        return []
    return [text_of(c) for c in args.children if c.is_named and c.type != "keyword_argument"]


def _params(node: Node) -> list[str]:
    """Parameter names, in order, annotations and defaults dropped (`arg_binding` needs names)."""
    params = node.child_by_field_name("parameters")
    if params is None:
        return []
    names: list[str] = []
    for child in params.children:
        if not child.is_named:
            continue
        if child.type == "identifier":
            names.append(text_of(child))
        elif child.type in ("list_splat_pattern", "dictionary_splat_pattern"):
            names.append(text_of(child).lstrip("*"))
        else:
            inner = child.child_by_field_name("name")
            names.append(text_of(inner) if inner is not None else text_of(child).split(":")[0].strip())
    return [name for name in names if name]


def _signature(node: Node, body: Node | None) -> str:
    """The definition line down to the body, whitespace collapsed, trailing `:` dropped."""
    if body is None or node.text is None:
        return " ".join(text_of(node).splitlines()[0].split())
    head = node.text[: body.start_byte - node.start_byte].decode("utf-8", errors="replace")
    return " ".join(head.split()).rstrip(":").strip()


def _docstring(body: Node) -> str:
    """The first string statement of a body, cleaned the way `inspect.getdoc` cleans one."""
    node = _doc_node(body)
    if node is None:
        return ""
    content = "".join(text_of(c) for c in node.children if c.type == "string_content")
    return inspect.cleandoc(content).strip()


def _doc_node(body: Node) -> Node | None:
    for child in body.children:
        if not child.is_named:
            continue
        if child.type == "expression_statement" and child.children and child.children[0].type == "string":
            return child.children[0]
        return None
    return None


def _statement_lines(body: Node) -> list[int]:
    """Start lines of the body's own statements -- where an oversized passage may be split."""
    return [line_of(child) for child in body.children if child.is_named]


def _header_end(symbol: Symbol, symbols: list[Symbol]) -> int:
    """
    Last line of a module's or class's header passage: everything before its first member.
    A member's `line_start` is its decorated node, so a header always stops before the
    decorators, never between them and the `def`.

    `header_end < line_start` means there is no header at all -- a file that opens with
    `class Base:` on line 1 -- and the chunker writes no header passage for it.
    """
    members = [s for s in symbols if s is not symbol and _is_member(symbol, s)]
    if not members:
        return symbol.line_end
    return min(m.line_start for m in members) - 1


def _is_member(parent: Symbol, child: Symbol) -> bool:
    """Direct members only: `OrderService.place` is a member of `OrderService`, `X.Y.z` is not."""
    if parent.kind == "module":
        return child.kind in ("class", "function") and "." not in child.qualname
    prefix = f"{parent.qualname}."
    return child.qualname.startswith(prefix) and "." not in child.qualname[len(prefix) :]


# ---------------------------------------------------------- what bodies do


def _walk_body(facts: FileFacts, symbol: Symbol, body: Node, is_test: bool) -> None:
    """
    Calls, raises, assignments and literals inside one symbol, attributed to it.

    A module's or class's walk stops at each definition, because that definition is a symbol
    of its own and owns what is inside it. A *function's* walk does not: a nested function,
    a lambda and a comprehension are deliberately not symbols (2.2a), so what they call is
    attributed to the function they are written in, which is also the passage they land in.
    """
    container = symbol.kind in ("module", "class")
    doc = _doc_node(body)
    for child in body.children:
        if container and child.type in DEFINITIONS:
            continue
        stack = [child]
        while stack:
            node = stack.pop()
            _record(facts, symbol, node, doc, is_test)
            stack.extend(reversed(node.children))


def _record(facts: FileFacts, symbol: Symbol, node: Node, doc: Node | None, is_test: bool) -> None:
    if node.type == "call":
        facts.calls.append(_call(symbol.qualname, node))
    elif node.type == "raise_statement":
        name = _exception_name(node)
        if name:
            facts.exceptions.append(RaiseFact(caller=symbol.qualname, name=name, line=line_of(node)))
    elif node.type == "except_clause":
        for name in _caught_names(node):
            facts.exceptions.append(
                RaiseFact(caller=symbol.qualname, name=name, line=line_of(node), kind="catch")
            )
    elif node.type == "assignment":
        _assignment(facts, symbol, node)
    elif node.type == "string" and node is not doc:
        content = "".join(text_of(c) for c in node.children if c.type == "string_content")
        if content:
            facts.literals.append(LiteralFact(caller=symbol.qualname, text=content, line=line_of(node)))
    elif node.type == "identifier" and is_test and symbol.kind in ("function", "method"):
        facts.names.setdefault(text_of(node), []).append(line_of(node))


def _call(caller: str, node: Node) -> CallFact:
    target = node.child_by_field_name("function")
    receiver, name = "", ""
    if target is not None and target.type == "attribute":
        receiver = _one_line(text_of(target.child_by_field_name("object")))
        name = text_of(target.child_by_field_name("attribute"))
    elif target is not None:
        name = text_of(target)
    args, kwargs = _arguments(node)
    return CallFact(
        caller=caller,
        receiver=receiver,
        name=name,
        line=line_of(node),
        in_branch=_in_branch(node),
        is_await=_is_await(node),
        args=args,
        kwargs=kwargs,
    )


def _arguments(node: Node) -> tuple[list[str], dict[str, str]]:
    args: list[str] = []
    kwargs: dict[str, str] = {}
    arg_list = node.child_by_field_name("arguments")
    if arg_list is None:
        return args, kwargs
    for child in arg_list.children:
        if not child.is_named:
            continue
        if child.type == "keyword_argument":
            kwargs[text_of(child.child_by_field_name("name"))] = _one_line(
                text_of(child.child_by_field_name("value"))
            )
        else:
            args.append(_one_line(text_of(child)))
    return args, kwargs


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _in_branch(node: Node) -> bool:
    parent = node.parent
    while parent is not None and parent.type not in DEFINITIONS and parent.type != "module":
        if parent.type in BRANCH_TYPES:
            return True
        parent = parent.parent
    return False


def _is_await(node: Node) -> bool:
    return node.parent is not None and node.parent.type == "await"


def _exception_name(node: Node) -> str:
    for child in node.children:
        if child.type == "call":
            return text_of(child.child_by_field_name("function"))
        if child.type in ("identifier", "attribute"):
            return text_of(child)
    return ""


def _caught_names(node: Node) -> list[str]:
    names: list[str] = []
    for child in node.children:
        if child.type == "block":
            break
        if child.type in ("identifier", "attribute"):
            names.append(text_of(child))
        elif child.type in ("tuple", "parenthesized_expression"):
            names.extend(text_of(c) for c in child.children if c.type in ("identifier", "attribute"))
    return [name for name in names if name]


def _assignment(facts: FileFacts, symbol: Symbol, node: Node) -> None:
    left = node.child_by_field_name("left")
    right = node.child_by_field_name("right")
    if left is None or right is None or left.type != "identifier":
        return
    if symbol.kind == "class" and text_of(left) == "__tablename__" and right.type == "string":
        name = "".join(text_of(c) for c in right.children if c.type == "string_content")
        if name:
            facts.table_names.append((symbol.qualname, name, line_of(node)))
        return
    if right.type == "call":
        called = right.child_by_field_name("function")
        if called is not None and called.type in ("identifier", "attribute"):
            facts.assignments.append(
                AssignFact(
                    scope=symbol.qualname,
                    target=text_of(left),
                    value=_one_line(text_of(called)),
                    line=line_of(node),
                )
            )


# ------------------------------------------------------------- the imports


def _imports(facts: FileFacts, root: Node) -> None:
    """
    Every import in the file, as written. `from . import billing` keeps its level so
    resolve.py can turn it into `pyapp.billing` without re-reading the tree.
    """
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "import_statement":
            for child in node.children_by_field_name("name"):
                name, alias = _aliased(child)
                facts.imports.append(ImportFact(module=name, alias=alias, line=line_of(node)))
        elif node.type == "import_from_statement":
            _from_import(facts, node)
        else:
            stack.extend(reversed(node.children))


def _aliased(node: Node) -> tuple[str, str]:
    """`(name, local binding)` for a `dotted_name` or an `aliased_import`."""
    if node.type != "aliased_import":
        text = text_of(node)
        return text, text
    return text_of(node.child_by_field_name("name")), text_of(node.child_by_field_name("alias"))


def _from_import(facts: FileFacts, node: Node) -> None:
    source = node.child_by_field_name("module_name")
    level, module = 0, ""
    if source is not None and source.type == "relative_import":
        prefix = next((c for c in source.children if c.type == "import_prefix"), None)
        level = len(text_of(prefix)) if prefix is not None else 1
        inner = next((c for c in source.children if c.type == "dotted_name"), None)
        module = text_of(inner) if inner is not None else ""
    else:
        module = text_of(source)
    line = line_of(node)
    names = node.children_by_field_name("name")
    if not names:  # `from a import *`
        facts.imports.append(ImportFact(module=module, line=line, level=level, is_wildcard=True))
        return
    for child in names:
        name, alias = _aliased(child)
        facts.imports.append(ImportFact(module=module, name=name, alias=alias, line=line, level=level))


# ------------------------------------------------------------ registration

# What `languages.RULES["python"]` is. Everything Python-shaped that the extractor, the
# resolver or the chunker needs lives behind this entry; none of them names the language.
RULES_ENTRY = LanguageRules(
    name="python",
    line_comment="#",
    walk=walk,
    resolve_module=resolve_module,
    module_qualname=module_qualname,
    is_test_path=is_test_path,
)
