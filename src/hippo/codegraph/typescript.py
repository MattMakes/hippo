"""
Pass 1 for TypeScript and JavaScript: one file's CST becomes `FileFacts`.

The same contract as python.py -- report what is written, resolve nothing -- with the
differences the language forces:

* `export` wraps a declaration rather than being part of it, so every lookup unwraps an
  `export_statement` first, while line numbers come from the outer node (a passage should
  start at `export class Order`, not at `class Order`).
* An arrow function bound to a `const` at module or class scope is a symbol, named by its
  binding (`export const compute = (o) => ...` is the function `compute`). An anonymous
  callback is not, and neither are interfaces, type aliases, enums or overload signatures
  (2.2a) -- none of them has a body a passage could usefully hold.
* `new X()` is a call to `X`, and `mongoose.model("Order", ...)` binds a name to a
  collection, which is how `OrderModel.find({})` in another file becomes a READS edge.
"""

from __future__ import annotations

from tree_sitter import Node

from .model import (
    AssignFact,
    BaseFact,
    CallFact,
    FileFacts,
    ImportFact,
    LiteralFact,
    RaiseFact,
    Symbol,
    symbol_id,
)
from .python import is_test_path, module_qualname
from .treesitter import end_line_of, line_of, text_of

BRANCH_TYPES = {
    "if_statement",
    "else_clause",
    "for_statement",
    "for_in_statement",
    "while_statement",
    "do_statement",
    "try_statement",
    "catch_clause",
    "finally_clause",
    "switch_statement",
    "switch_case",
    "switch_default",
    "ternary_expression",
}

DECLARATIONS = {
    "class_declaration",
    "abstract_class_declaration",
    "function_declaration",
    "generator_function_declaration",
    "method_definition",
    "lexical_declaration",
    "variable_declaration",
}
ARROWS = {"arrow_function", "function_expression"}


def walk(path: str, root: Node, source_id: str) -> FileFacts:
    """Turn one parsed TypeScript/JavaScript file into the facts resolve.py needs."""
    module = module_qualname(path)
    is_test = is_test_path(path)
    facts = FileFacts(path=path, lang="typescript", module=module)

    module_symbol = Symbol(
        id=symbol_id(source_id, path, module),
        source_id=source_id,
        name=module.rpartition(".")[2] or module,
        qualname=module,
        kind="module",
        lang="typescript",
        path=path,
        line_start=1,
        line_end=end_line_of(root),
        doc=_doc_before(root.children[0]) if root.children else "",
        is_test=is_test,
        module=module,
        display=module,
        statement_lines=_statement_lines(root),
    )
    facts.symbols.append(module_symbol)

    bodies: list[tuple[Symbol, Node]] = []
    _declarations(facts, root, module_symbol, "", source_id, is_test, bodies)
    module_symbol.header_end = _header_end(module_symbol, facts.symbols, root)

    _imports(facts, root)
    _walk_body(facts, module_symbol, root, is_test)
    for symbol, body in bodies:
        _walk_body(facts, symbol, body, is_test)
    return facts


# ------------------------------------------------------------ the symbols


def _declarations(
    facts: FileFacts,
    block: Node,
    parent: Symbol,
    prefix: str,
    source_id: str,
    is_test: bool,
    bodies: list[tuple[Symbol, Node]],
) -> None:
    """Every class, function, method and named arrow directly inside `block`, in source order."""
    for outer in block.children:
        node = _unwrap(outer)
        if node is None:
            continue
        for name, definition, body in _named_definitions(node):
            if not name or body is None:
                continue
            qualname = f"{prefix}{name}"
            is_class = definition.type in ("class_declaration", "abstract_class_declaration")
            symbol = Symbol(
                id=symbol_id(source_id, facts.path, qualname),
                source_id=source_id,
                name=name,
                qualname=qualname,
                kind="class" if is_class else ("method" if prefix else "function"),
                lang="typescript",
                path=facts.path,
                line_start=line_of(outer),
                line_end=end_line_of(outer),
                signature=_signature(definition, body),
                doc=_doc_before(outer),
                is_test=is_test,
                params=_params(definition),
                module=facts.module,
                display=f"{facts.module}.{qualname}",
                statement_lines=_statement_lines(body),
            )
            symbol.header_end = symbol.line_end
            facts.symbols.append(symbol)
            bodies.append((symbol, body))
            if is_class:
                for base in _base_names(definition):
                    facts.bases.append(BaseFact(cls=qualname, base=base, line=line_of(definition)))
                _declarations(facts, body, symbol, f"{qualname}.", source_id, is_test, bodies)
                symbol.header_end = _header_end(symbol, facts.symbols, body)


def _unwrap(node: Node) -> Node | None:
    """`export class X {}` -> the `class_declaration`. Anything else is returned as it is."""
    if node.type != "export_statement":
        return node if node.is_named else None
    declaration = node.child_by_field_name("declaration")
    return declaration if declaration is not None else None


def _named_definitions(node: Node) -> list[tuple[str, Node, Node | None]]:
    """`(name, definition node, body)` for everything in `node` that becomes a symbol."""
    if node.type in ("class_declaration", "abstract_class_declaration"):
        return [(text_of(node.child_by_field_name("name")), node, node.child_by_field_name("body"))]
    if node.type in ("function_declaration", "generator_function_declaration", "method_definition"):
        return [(text_of(node.child_by_field_name("name")), node, node.child_by_field_name("body"))]
    if node.type in ("lexical_declaration", "variable_declaration"):
        found = []
        for child in node.children:
            if child.type != "variable_declarator":
                continue
            value = child.child_by_field_name("value")
            if value is None or value.type not in ARROWS:
                continue  # only a function binding is a symbol; a plain const is not
            found.append(
                (text_of(child.child_by_field_name("name")), child, value.child_by_field_name("body"))
            )
        return found
    return []


def _base_names(node: Node) -> list[str]:
    heritage = next((c for c in node.children if c.type == "class_heritage"), None)
    if heritage is None:
        return []
    names: list[str] = []
    for clause in heritage.children:
        if clause.type != "extends_clause":
            continue
        names.extend(text_of(c) for c in clause.children if c.is_named and c.type != "type_arguments")
    return [name for name in names if name]


def _params(node: Node) -> list[str]:
    params = node.child_by_field_name("parameters")
    if params is None:
        value = node.child_by_field_name("value")
        params = value.child_by_field_name("parameters") if value is not None else None
    if params is None:
        return []
    names: list[str] = []
    for child in params.children:
        if not child.is_named:
            continue
        pattern = child.child_by_field_name("pattern") or child
        names.append(text_of(pattern).split(":")[0].strip())
    return [name for name in names if name]


def _signature(node: Node, body: Node) -> str:
    """The declaration down to the body, whitespace collapsed, trailing `=>` dropped."""
    if node.text is None or body.start_byte < node.start_byte:
        return " ".join(text_of(node).splitlines()[0].split())
    head = node.text[: body.start_byte - node.start_byte].decode("utf-8", errors="replace")
    return " ".join(head.split()).removesuffix("=>").strip()


def _doc_before(node: Node) -> str:
    """The `/** ... */` block immediately above a declaration, stripped of its comment marks."""
    previous = node.prev_sibling
    if previous is None or previous.type != "comment":
        return ""
    raw = text_of(previous)
    if not raw.startswith("/**"):
        return ""
    lines = raw.removeprefix("/**").removesuffix("*/").splitlines()
    return "\n".join(line.strip().removeprefix("*").strip() for line in lines).strip()


def _statement_lines(body: Node) -> list[int]:
    return [line_of(child) for child in body.children if child.is_named and child.type != "comment"]


def _header_end(symbol: Symbol, symbols: list[Symbol], body: Node) -> int:
    members = [s for s in symbols if s is not symbol and _is_member(symbol, s)]
    if not members:
        return symbol.line_end
    return min(m.line_start for m in members) - 1


def _is_member(parent: Symbol, child: Symbol) -> bool:
    if parent.kind == "module":
        return child.kind in ("class", "function") and "." not in child.qualname
    prefix = f"{parent.qualname}."
    return child.qualname.startswith(prefix) and "." not in child.qualname[len(prefix) :]


# ---------------------------------------------------------- what bodies do


def _walk_body(facts: FileFacts, symbol: Symbol, body: Node, is_test: bool) -> None:
    """Calls, throws, catches, bindings and literals inside one symbol, attributed to it."""
    container = symbol.kind in ("module", "class")
    for child in body.children:
        if container and _unwrap(child) is not None and _named_definitions(_unwrap(child)):
            continue
        stack = [child]
        while stack:
            node = stack.pop()
            _record(facts, symbol, node, is_test)
            stack.extend(reversed(node.children))


def _record(facts: FileFacts, symbol: Symbol, node: Node, is_test: bool) -> None:
    if node.type == "call_expression":
        facts.calls.append(_call(symbol.qualname, node))
    elif node.type == "new_expression":
        facts.calls.append(_new(symbol.qualname, node))
    elif node.type == "throw_statement":
        name = _thrown_name(node)
        if name:
            facts.exceptions.append(RaiseFact(caller=symbol.qualname, name=name, line=line_of(node)))
    elif node.type == "catch_clause":
        for name in _caught_names(node):
            facts.exceptions.append(
                RaiseFact(caller=symbol.qualname, name=name, line=line_of(node), kind="catch")
            )
    elif node.type == "variable_declarator":
        _binding(facts, symbol, node)
    elif node.type == "string":
        content = "".join(text_of(c) for c in node.children if c.type == "string_fragment")
        if content:
            facts.literals.append(LiteralFact(caller=symbol.qualname, text=content, line=line_of(node)))
    elif node.type in ("identifier", "property_identifier") and is_test:
        if symbol.kind in ("function", "method"):
            facts.names.setdefault(text_of(node), []).append(line_of(node))


def _call(caller: str, node: Node) -> CallFact:
    target = node.child_by_field_name("function")
    receiver, name = "", ""
    if target is not None and target.type == "member_expression":
        receiver = _one_line(text_of(target.child_by_field_name("object")))
        name = text_of(target.child_by_field_name("property"))
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


def _new(caller: str, node: Node) -> CallFact:
    """`new Order()` is a call to the class -- 2.2b's "INVOKES the constructor-bearing class"."""
    target = node.child_by_field_name("constructor")
    receiver, name = "", _one_line(text_of(target))
    if "." in name:
        receiver, _, name = name.rpartition(".")
    args, kwargs = _arguments(node)
    return CallFact(
        caller=caller,
        receiver=receiver,
        name=name,
        line=line_of(node),
        in_branch=_in_branch(node),
        is_await=_is_await(node),
        is_new=True,
        args=args,
        kwargs=kwargs,
    )


def _arguments(node: Node) -> tuple[list[str], dict[str, str]]:
    args: list[str] = []
    arg_list = node.child_by_field_name("arguments")
    if arg_list is None:
        return args, {}
    args.extend(_one_line(text_of(c)) for c in arg_list.children if c.is_named)
    return args, {}


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _in_branch(node: Node) -> bool:
    parent = node.parent
    while parent is not None and parent.type not in DECLARATIONS and parent.type != "program":
        if parent.type in BRANCH_TYPES:
            return True
        parent = parent.parent
    return False


def _is_await(node: Node) -> bool:
    return node.parent is not None and node.parent.type == "await_expression"


def _thrown_name(node: Node) -> str:
    for child in node.children:
        if child.type == "new_expression":
            return _one_line(text_of(child.child_by_field_name("constructor")))
        if child.type in ("identifier", "member_expression"):
            return _one_line(text_of(child))
    return ""


def _caught_names(node: Node) -> list[str]:
    """
    A `catch` only names what it catches through an `instanceof` test (2.2b): a bare
    `catch (e)` says nothing about the type and gets no edge.
    """
    names: list[str] = []
    stack = list(node.children)
    while stack:
        current = stack.pop()
        if current.type == "binary_expression":
            operator = next((c for c in current.children if not c.is_named), None)
            if operator is not None and text_of(operator) == "instanceof":
                right = current.child_by_field_name("right")
                if right is not None:
                    names.append(_one_line(text_of(right)))
        stack.extend(current.children)
    return [name for name in names if name]


def _binding(facts: FileFacts, symbol: Symbol, node: Node) -> None:
    """`const o = new Order()` and `const M = mongoose.model("Order", ...)`."""
    name = node.child_by_field_name("name")
    value = node.child_by_field_name("value")
    if name is None or value is None or name.type != "identifier":
        return
    if value.type == "new_expression":
        facts.assignments.append(
            AssignFact(
                scope=symbol.qualname,
                target=text_of(name),
                value=_one_line(text_of(value.child_by_field_name("constructor"))),
                line=line_of(node),
            )
        )
        return
    if value.type != "call_expression":
        return
    called = value.child_by_field_name("function")
    if called is None:
        return
    collection = _model_collection(called, value)
    if collection:
        facts.models.append((text_of(name), collection, line_of(node)))
        return
    facts.assignments.append(
        AssignFact(
            scope=symbol.qualname,
            target=text_of(name),
            value=_one_line(text_of(called)),
            line=line_of(node),
        )
    )


def _model_collection(called: Node, call: Node) -> str:
    """`mongoose.model("Order", ...)` -> `Order`; anything else -> ""."""
    if called.type != "member_expression":
        return ""
    if text_of(called.child_by_field_name("property")) != "model":
        return ""
    arguments = call.child_by_field_name("arguments")
    first = next((c for c in arguments.children if c.is_named), None) if arguments is not None else None
    if first is None or first.type != "string":
        return ""
    return "".join(text_of(c) for c in first.children if c.type == "string_fragment")


# ------------------------------------------------------------- the imports


def _imports(facts: FileFacts, root: Node) -> None:
    """
    `import`, `require` and `export ... from`. The module text is kept as written -- turning
    `./base` into `tsapp.models.base` needs the file list, which is resolve.py's business.
    """
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "import_statement":
            _import_statement(facts, node)
        elif node.type == "export_statement" and node.child_by_field_name("source") is not None:
            _reexport(facts, node)
        else:
            if node.type == "call_expression":
                _require(facts, node)
            stack.extend(reversed(node.children))


def _import_statement(facts: FileFacts, node: Node) -> None:
    source = _source_text(node)
    if not source:
        return
    line = line_of(node)
    clause = next((c for c in node.children if c.type == "import_clause"), None)
    if clause is None:  # `import "./side-effect"`
        facts.imports.append(ImportFact(module=source, line=line))
        return
    for child in clause.children:
        if child.type == "identifier":  # default import
            facts.imports.append(
                ImportFact(module=source, name="default", alias=text_of(child), line=line, is_default=True)
            )
        elif child.type == "namespace_import":
            alias = next((c for c in child.children if c.type == "identifier"), None)
            facts.imports.append(ImportFact(module=source, alias=text_of(alias), line=line))
        elif child.type == "named_imports":
            for specifier in child.children:
                if specifier.type != "import_specifier":
                    continue
                name, alias = _specifier(specifier)
                facts.imports.append(ImportFact(module=source, name=name, alias=alias, line=line))


def _reexport(facts: FileFacts, node: Node) -> None:
    """`export {x} from "./b"` and `export * from "./b"`."""
    source = _source_text(node)
    if not source:
        return
    line = line_of(node)
    clause = next((c for c in node.children if c.type == "export_clause"), None)
    if clause is None:
        facts.reexports.append(ImportFact(module=source, line=line, is_wildcard=True))
        return
    for specifier in clause.children:
        if specifier.type != "export_specifier":
            continue
        name, alias = _specifier(specifier)
        facts.reexports.append(ImportFact(module=source, name=name, alias=alias, line=line))


def _require(facts: FileFacts, node: Node) -> None:
    """`const x = require("./y")` -- the module edge only; the binding is a plain const."""
    called = node.child_by_field_name("function")
    if called is None or text_of(called) != "require":
        return
    arguments = node.child_by_field_name("arguments")
    first = next((c for c in arguments.children if c.is_named), None) if arguments is not None else None
    if first is None or first.type != "string":
        return
    module = "".join(text_of(c) for c in first.children if c.type == "string_fragment")
    if module:
        facts.imports.append(ImportFact(module=module, line=line_of(node)))


def _specifier(node: Node) -> tuple[str, str]:
    name = text_of(node.child_by_field_name("name"))
    alias = node.child_by_field_name("alias")
    return name, text_of(alias) if alias is not None else name


def _source_text(node: Node) -> str:
    source = node.child_by_field_name("source")
    if source is None:
        return ""
    return "".join(text_of(c) for c in source.children if c.type == "string_fragment")
