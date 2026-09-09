"""
Pass 1 for C#: one file's CST becomes `FileFacts`.

The same contract as `python.py` and `typescript.py` -- report what is written, resolve
nothing -- with the four things C# does that neither of them does:

* **A namespace is a scope above the file.** `namespace CsApp.Orders;` (or the block form)
  becomes `FileFacts.scope`, `build_index` merges every file of that namespace, and a
  sibling's type is then visible with no `using` at all: ω 1.00 `same_scope`, the tier the
  plan gives a name the language resolves as surely as a local one.
* **A `using` names a scope, not a file**, so `resolve_module` hands back a `Resolution`
  carrying the namespace's types rather than a `FileFacts`. `using Alias = X.Y.Type;` binds
  one name and `using static X.Y.Type;` binds the type's members.
* **Fields carry declared types**, which is the whole of ASP.NET dependency injection:
  `_repo.Save()` on a `private readonly IOrderRepo _repo` resolves through the field's type.
  The declaration becomes an `AssignFact` per method of the class -- "inside `Place`, `_repo`
  holds an `IOrderRepo`" is the statement `resolve._receiver_type` reads, and it only ever
  reads assignments scoped to the *calling method*.
* **Attributes mark tests.** `[Fact]` / `[Test]` / `[TestMethod]` / `[Theory]` / `[TestCase]`
  on a method sets `is_test`, and `Orders.Tests/OrderServiceTests.cs` is a test file by both
  its directory and its name -- neither of which the shared default recognises.

Interfaces and abstract members get symbols even though they have no body: a DI call lands
on the declared *interface* method, and without a symbol there it would be no edge at all.
"""

from __future__ import annotations

import re

from tree_sitter import Node

from .model import (
    SUPER_NAMES,
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
from .treesitter import end_line_of, line_of, text_of

LANG = "csharp"

# Everything that becomes a symbol of kind `class`. An enum and an interface are not classes
# to a compiler, but they are to the graph: a named type with members, which is what a
# passage and a CONTAINS edge need.
TYPE_DECLARATIONS = {
    "class_declaration",
    "struct_declaration",
    "record_declaration",
    "record_struct_declaration",
    "interface_declaration",
    "enum_declaration",
}

# ...and of kind `method`. A local function and a lambda are deliberately absent: they fold
# into the method that holds them, exactly as `python.py` folds a nested `def`.
MEMBER_DECLARATIONS = {
    "method_declaration",
    "constructor_declaration",
    "destructor_declaration",
    "operator_declaration",
}

NAMESPACE_DECLARATIONS = {"namespace_declaration", "file_scoped_namespace_declaration"}

BRANCH_TYPES = {
    "if_statement",
    "for_statement",
    "foreach_statement",
    "while_statement",
    "do_statement",
    "try_statement",
    "catch_clause",
    "finally_clause",
    "switch_statement",
    "switch_section",
    "switch_expression",
    "conditional_expression",
}

# Where walking up from a call stops: the thing that holds it. `global_statement` is the
# top-level-statement wrapper in `Program.cs`, whose calls belong to the module.
STOP_TYPES = TYPE_DECLARATIONS | MEMBER_DECLARATIONS | {
    "compilation_unit",
    "local_function_statement",
    "property_declaration",
    "global_statement",
}  # fmt: skip

STRING_TYPES = {
    "string_literal",
    "verbatim_string_literal",
    "raw_string_literal",
    "interpolated_string_expression",
}

# An attribute that means "this method is a test", across xUnit, NUnit and MSTest.
TEST_ATTRIBUTES = frozenset({"Fact", "Test", "TestMethod", "Theory", "TestCase"})

XML_TAG = re.compile(r"<[^>]+>")
SUMMARY = re.compile(r"<summary>(.*?)</summary>", re.DOTALL)


def walk(path: str, root: Node, source_id: str) -> FileFacts:
    """Turn one parsed C# file into the facts resolve.py needs."""
    module = module_qualname(path)
    file_is_test = is_test_path(path)
    facts = FileFacts(path=path, lang=LANG, module=module, scope=_namespace_of(root))

    module_symbol = Symbol(
        id=symbol_id(source_id, path, module),
        source_id=source_id,
        name=module.rpartition(".")[2] or module,
        qualname=module,
        kind="module",
        lang=LANG,
        path=path,
        line_start=1,
        line_end=end_line_of(root),
        doc=_doc_before(root.children[0]) if root.children else "",
        is_test=file_is_test,
        module=module,
        display=module,
        statement_lines=_statement_lines(root),
    )
    facts.symbols.append(module_symbol)

    bodies: list[tuple[Symbol, Node]] = []
    fields: list[tuple[str, str, str]] = []  # (class qualname, field name, declared type)
    _declarations(facts, root, "", source_id, file_is_test, bodies, fields)
    module_symbol.header_end = _header_end(module_symbol, facts.symbols, root)

    _imports(facts, root)
    _walk_body(facts, module_symbol, root, file_is_test)
    for symbol, body in bodies:
        _walk_body(facts, symbol, body, file_is_test)
    _field_bindings(facts, fields)
    return facts


# ------------------------------------------------------------ the symbols


def _declarations(
    facts: FileFacts,
    block: Node,
    prefix: str,
    source_id: str,
    file_is_test: bool,
    bodies: list[tuple[Symbol, Node]],
    fields: list[tuple[str, str, str]],
) -> None:
    """Every type and member directly inside `block`, in source order, namespaces flattened."""
    for node in _scan_children(block):
        if node.type in TYPE_DECLARATIONS:
            name = text_of(node.child_by_field_name("name"))
        elif node.type in MEMBER_DECLARATIONS:
            name = _member_name(node)
        else:
            if node.type == "field_declaration" and prefix:
                fields.extend(_field_types(node, prefix.rstrip(".")))
            continue
        if not name:
            continue
        qualname = f"{prefix}{name}"
        is_type = node.type in TYPE_DECLARATIONS
        body = node.child_by_field_name("body")
        symbol = Symbol(
            id=symbol_id(source_id, facts.path, qualname),
            source_id=source_id,
            name=name,
            qualname=qualname,
            kind="class" if is_type else "method",
            lang=LANG,
            path=facts.path,
            line_start=line_of(node),
            line_end=end_line_of(node),
            signature=_signature(node, body),
            doc=_doc_before(node),
            is_test=file_is_test or (not is_type and _has_test_attribute(node)),
            params=_params(node),
            module=facts.module,
            display=f"{facts.module}.{qualname}",
            statement_lines=_statement_lines(body) if body is not None else [],
        )
        symbol.header_end = symbol.line_end
        facts.symbols.append(symbol)
        if body is not None:
            bodies.append((symbol, body))
        if not is_type:
            continue
        for base in _base_names(node):
            facts.bases.append(BaseFact(cls=qualname, base=base, line=line_of(node)))
        if body is not None:
            _declarations(facts, body, f"{qualname}.", source_id, file_is_test, bodies, fields)
            symbol.header_end = _header_end(symbol, facts.symbols, body)


def _scan_children(node: Node) -> list[Node]:
    """
    A container's children, with namespaces flattened away.

    A namespace is a scope, not a symbol (`FileFacts.scope` carries it), so the types inside
    `namespace X { }` are top-level exactly as the types after `namespace X;` are, and both
    forms produce the same graph.
    """
    found: list[Node] = []
    for child in node.children:
        if child.type in NAMESPACE_DECLARATIONS:
            body = child.child_by_field_name("body")
            if body is not None:
                found.extend(_scan_children(body))
        elif child.type == "declaration_list":
            found.extend(_scan_children(child))
        else:
            found.append(child)
    return found


def _member_name(node: Node) -> str:
    """
    What to call a member. A destructor is `~Base`, so it cannot collide with the
    constructor -- both carry the type's name in the grammar.
    """
    if node.type == "operator_declaration":
        return _operator_name(node)
    name = text_of(node.child_by_field_name("name"))
    return f"~{name}" if node.type == "destructor_declaration" and name else name


def _operator_name(node: Node) -> str:
    """`public static Base operator +(...)` -> `operator+`; the token is unnamed in the CST."""
    tokens = [child for child in node.children if not child.is_named]
    for index, child in enumerate(tokens[:-1]):
        if text_of(child) == "operator":
            return f"operator{text_of(tokens[index + 1])}"
    return ""


def _has_test_attribute(node: Node) -> bool:
    """`[Fact]`, `[Theory]`, `[Test]`, `[TestMethod]`, `[TestCase]` -- xUnit, NUnit, MSTest."""
    for attributes in (c for c in node.children if c.type == "attribute_list"):
        for attribute in (c for c in attributes.children if c.type == "attribute"):
            if _plain_name(attribute.child_by_field_name("name")).rpartition(".")[2] in TEST_ATTRIBUTES:
                return True
    return False


def _base_names(node: Node) -> list[str]:
    """
    `class OrderService : Base, IService` -> both. Implementing an interface counts as
    INHERITS (the plan's decision): C# writes the two in one list and means the same thing
    for a graph -- "look here for members I did not declare".
    """
    base_list = next((c for c in node.children if c.type == "base_list"), None)
    if base_list is None:
        return []
    return [name for name in (_plain_name(c) for c in base_list.children if c.is_named) if name]


def _params(node: Node) -> list[str]:
    """Parameter names, for the INVOKES `arg_binding`. A record's positional list counts."""
    params = node.child_by_field_name("parameters")
    if params is None:
        params = next((c for c in node.children if c.type == "parameter_list"), None)
    if params is None:
        return []
    names = [
        text_of(child.child_by_field_name("name")) for child in params.children if child.type == "parameter"
    ]
    return [name for name in names if name]


def _field_types(node: Node, cls: str) -> list[tuple[str, str, str]]:
    """`private readonly IOrderRepo _repo;` -> `(cls, "_repo", "IOrderRepo")`, one per name."""
    declaration = next((c for c in node.children if c.type == "variable_declaration"), None)
    if declaration is None:
        return []
    declared = _type_name(declaration.child_by_field_name("type"))
    if not declared:
        return []
    return [
        (cls, text_of(child.child_by_field_name("name")), declared)
        for child in declaration.children
        if child.type == "variable_declarator" and text_of(child.child_by_field_name("name"))
    ]


def _field_bindings(facts: FileFacts, fields: list[tuple[str, str, str]]) -> None:
    """
    A field is in scope in every method of its class, so it becomes one `AssignFact` per
    method rather than one for the class.

    `resolve._receiver_type` only reads assignments whose `scope` is the *calling method*,
    and a C# field is visible in a method regardless of where in the class it is written --
    hence the method's own first line, which no call in it can precede.
    """
    methods = [s for s in facts.symbols if s.kind == "method"]
    for cls, target, declared in fields:
        for method in methods:
            if method.qualname.rpartition(".")[0] == cls:
                facts.assignments.append(
                    AssignFact(scope=method.qualname, target=target, value=declared, line=method.line_start)
                )


def _signature(node: Node, body: Node | None) -> str:
    """
    The declaration from its modifiers to the body, `=>` or `;`, whitespace collapsed.

    Attributes are cut off the front: `[Fact]` is part of the passage (it is inside the
    symbol's line range) but not part of how the member reads.
    """
    start = node.start_byte
    for child in node.children:
        if child.type != "attribute_list":
            break
        start = child.end_byte
    end = body.start_byte if body is not None else node.end_byte
    if node.text is None or end <= start:
        return " ".join(text_of(node).splitlines()[0].split())
    head = node.text[start - node.start_byte : end - node.start_byte].decode("utf-8", errors="replace")
    return " ".join(head.split()).removesuffix(";").strip()


def _doc_before(node: Node) -> str:
    """The `///` block above a declaration: `<summary>` first, then the rest, tags stripped."""
    lines: list[str] = []
    previous = node.prev_sibling
    while previous is not None and previous.type == "comment":
        raw = text_of(previous)
        if not raw.startswith("///"):
            break
        lines.append(raw.removeprefix("///").strip())
        previous = previous.prev_sibling
    if not lines:
        return ""
    text = "\n".join(reversed(lines))
    summary = SUMMARY.search(text)
    if summary is not None:
        text = f"{summary.group(1)}\n{text[: summary.start()]}\n{text[summary.end() :]}"
    stripped = (line.strip() for line in XML_TAG.sub("", text).splitlines())
    return "\n".join(line for line in stripped if line).strip()


def _statement_lines(body: Node) -> list[int]:
    return [line_of(child) for child in _scan_children(body) if child.is_named and child.type != "comment"]


def _header_end(symbol: Symbol, symbols: list[Symbol], body: Node) -> int:
    members = [s for s in symbols if s is not symbol and _is_member(symbol, s)]
    if not members:
        return symbol.line_end
    return min(m.line_start for m in members) - 1


def _is_member(parent: Symbol, child: Symbol) -> bool:
    if parent.kind == "module":
        return child.kind == "class" and "." not in child.qualname
    prefix = f"{parent.qualname}."
    return child.qualname.startswith(prefix) and "." not in child.qualname[len(prefix) :]


# ---------------------------------------------------------- what bodies do


def _walk_body(facts: FileFacts, symbol: Symbol, body: Node, file_is_test: bool) -> None:
    """
    Calls, throws, catches, bindings and literals inside one symbol, attributed to it.

    A container skips the children that are symbols of their own -- but not its properties,
    fields or events, whose accessors and initialisers have nowhere else to belong.
    """
    container = symbol.kind in ("module", "class")
    for child in _scan_children(body):
        if container and child.type in TYPE_DECLARATIONS | MEMBER_DECLARATIONS:
            continue
        stack = [child]
        while stack:
            node = stack.pop()
            _record(facts, symbol, node, file_is_test)
            stack.extend(reversed(node.children))


def _record(facts: FileFacts, symbol: Symbol, node: Node, file_is_test: bool) -> None:
    if node.type == "invocation_expression":
        facts.calls.append(_call(symbol.qualname, node))
    elif node.type == "object_creation_expression":
        facts.calls.append(_new(symbol.qualname, node))
    elif node.type == "throw_statement":
        name = _thrown_name(node)
        if name:
            facts.exceptions.append(RaiseFact(caller=symbol.qualname, name=name, line=line_of(node)))
    elif node.type == "catch_declaration":
        caught = _plain_name(node.child_by_field_name("type"))
        if caught:
            facts.exceptions.append(
                RaiseFact(caller=symbol.qualname, name=caught, line=line_of(node), kind="catch")
            )
    elif node.type == "variable_declarator":
        _binding(facts, symbol, node)
    elif node.type in STRING_TYPES:
        content = _string_text(node)
        if content:
            facts.literals.append(LiteralFact(caller=symbol.qualname, text=content, line=line_of(node)))
    elif node.type == "identifier" and file_is_test and symbol.kind in ("function", "method"):
        facts.names.setdefault(text_of(node), []).append(line_of(node))


def _call(caller: str, node: Node) -> CallFact:
    """`Billing.Total(o)`, `this.Log(m)`, `coll?.InsertOne(o)`, `Total(o)`."""
    target = node.child_by_field_name("function")
    receiver, name = "", ""
    if target is not None and target.type == "member_access_expression":
        receiver = _receiver_text(target.child_by_field_name("expression"))
        name = _plain_name(target.child_by_field_name("name"))
    elif target is not None and target.type == "conditional_access_expression":
        receiver = _receiver_text(target.child_by_field_name("condition"))
        binding = next((c for c in target.children if c.type == "member_binding_expression"), None)
        name = _plain_name(binding.child_by_field_name("name")) if binding is not None else ""
    elif target is not None:
        name = _plain_name(target)
    return CallFact(
        caller=caller,
        receiver=receiver,
        name=name,
        line=line_of(node),
        in_branch=_in_branch(node),
        is_await=_is_await(node),
        args=_arguments(node),
    )


def _new(caller: str, node: Node) -> CallFact:
    """`new Order()` is a call to the class -- 2.2b's "INVOKES the constructor-bearing class"."""
    receiver, name = "", _plain_name(node.child_by_field_name("type"))
    if "." in name:
        receiver, _, name = name.rpartition(".")
    return CallFact(
        caller=caller,
        receiver=receiver,
        name=name,
        line=line_of(node),
        in_branch=_in_branch(node),
        is_await=_is_await(node),
        is_new=True,
        args=_arguments(node),
    )


def _receiver_text(node: Node | None) -> str:
    """
    The text before the dot, as written -- `db.GetCollection<Order>("archive_orders")` has to
    survive whole for `data_access` to read the collection out of it.

    One normalisation: `new OrderService().Place(o)` reports the receiver as `OrderService`,
    because what the call is on is an `OrderService` and `resolve._receiver_type` can only
    look a *name* up. (`new A.B.C().M()` still resolves to nothing; a dotted construction is
    not a name any binding holds.)
    """
    if node is None:
        return ""
    if node.type == "object_creation_expression":
        return _plain_name(node.child_by_field_name("type"))
    return _one_line(text_of(node))


def _plain_name(node: Node | None) -> str:
    """A name with its type arguments dropped: `GetCollection<Order>` -> `GetCollection`."""
    if node is None:
        return ""
    if node.type == "generic_name":
        identifier = next((c for c in node.children if c.type == "identifier"), None)
        return text_of(identifier)
    return _one_line(text_of(node))


def _type_name(node: Node | None) -> str:
    """A declared type, unwrapped to the name a lookup can use: `IRepo<Order>?` -> `IRepo`."""
    if node is None:
        return ""
    if node.type in ("nullable_type", "array_type"):
        inner = node.child_by_field_name("type")
        return _type_name(inner if inner is not None else (node.children[0] if node.children else None))
    return _plain_name(node)


def _arguments(node: Node) -> list[str]:
    arguments = node.child_by_field_name("arguments")
    if arguments is None:
        return []
    return [_one_line(text_of(child)) for child in arguments.children if child.is_named]


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _in_branch(node: Node) -> bool:
    parent = node.parent
    while parent is not None and parent.type not in STOP_TYPES:
        if parent.type in BRANCH_TYPES:
            return True
        parent = parent.parent
    return False


def _is_await(node: Node) -> bool:
    return node.parent is not None and node.parent.type == "await_expression"


def _thrown_name(node: Node) -> str:
    """
    `throw new OrderError(...)` names a type; a bare `throw;` re-raises and names nothing,
    and `throw ex;` names a variable, not a type, so neither becomes a fact.
    """
    created = next((c for c in node.children if c.type == "object_creation_expression"), None)
    return _plain_name(created.child_by_field_name("type")) if created is not None else ""


def _binding(facts: FileFacts, symbol: Symbol, node: Node) -> None:
    """`var s = new OrderService();` -- what a later `s.Place(o)` has to go through."""
    name = node.child_by_field_name("name")
    if name is None:
        return
    value = next((c for c in reversed(node.children) if c.is_named and c.id != name.id), None)
    if value is None:
        return
    if value.type == "object_creation_expression":
        held = _plain_name(value.child_by_field_name("type"))
    elif value.type == "invocation_expression":
        held = _plain_name(value.child_by_field_name("function"))
    else:
        return
    if held:
        facts.assignments.append(
            AssignFact(scope=symbol.qualname, target=text_of(name), value=held, line=line_of(node))
        )


def _string_text(node: Node) -> str:
    """
    The content of a literal in any of C#'s four spellings. An interpolation hole becomes
    `?`, so `$"SELECT * FROM {table}"` still reads as SQL to the classifier without
    pretending to know what the hole holds.
    """
    if node.type == "verbatim_string_literal":
        raw = text_of(node)
        return raw.removeprefix("@").strip('"').replace('""', '"')
    if node.type == "interpolated_string_expression":
        parts = []
        for child in node.children:
            if child.type == "string_content":
                parts.append(text_of(child))
            elif child.type == "interpolation":
                parts.append("?")
        return "".join(parts)
    return "".join(
        text_of(child)
        for child in node.children
        if child.type in ("string_literal_content", "raw_string_content")
    )


# ------------------------------------------------------------- the imports


def _namespace_of(root: Node) -> str | None:
    """
    The namespace this file's types live in -- `namespace X;`, `namespace X { }` and nested
    blocks alike, joined with dots.

    A file declaring two sibling namespaces records only the first: `FileFacts.scope` is one
    value per file, and one namespace per file is the shape every C# style guide asks for.
    """
    parts: list[str] = []
    current = root
    while True:
        found = next((c for c in current.children if c.type in NAMESPACE_DECLARATIONS), None)
        if found is None:
            break
        name = _one_line(text_of(found.child_by_field_name("name")))
        if name:
            parts.append(name)
        body = found.child_by_field_name("body")
        if body is None:  # `namespace X;` -- the rest of the file is in it, nothing nests
            break
        current = body
    return ".".join(parts) or None


def _imports(facts: FileFacts, root: Node) -> None:
    """
    Every `using`, wherever it sits -- the top of the file or inside a namespace body.

    Three forms, all keeping the target as written: plain (`using X.Y;`, the whole
    namespace), aliased (`using A = X.Y.Type;`, one name) and static (`using static
    X.Y.Type;`, the type's members -- `is_wildcard`, since it binds every name the target
    holds rather than one the spec picked out).
    """
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "using_directive":
            _using(facts, node)
            continue
        stack.extend(reversed(node.children))


def _using(facts: FileFacts, node: Node) -> None:
    named = [child for child in node.children if child.is_named]
    if not named:
        return
    aliased = any(not child.is_named and text_of(child) == "=" for child in node.children)
    is_static = any(not child.is_named and text_of(child) == "static" for child in node.children)
    target = _one_line(text_of(named[-1]))
    if not target:
        return
    alias = text_of(named[0]) if aliased and len(named) > 1 else ""
    facts.imports.append(ImportFact(module=target, alias=alias, line=line_of(node), is_wildcard=is_static))


# ------------------------------------------------------------ registration


def resolve_module(index, facts: FileFacts, spec: ImportFact):
    """
    What a `using` names: a namespace (its types), or a single type (aliased, or `using
    static`, whose members all become visible).

    Returns a `Resolution` rather than a `FileFacts` in every case -- a C# import never names
    a file. A namespace nobody in this source declares (`System.Text`) is a dependency and
    resolves to nothing, so it gets no edge, exactly as an unknown Python import does.
    """
    from .resolve import Resolution  # local: resolve.py imports the registry, which imports this

    scope = index.scopes.get((LANG, spec.module))
    if scope:
        holder = _scope_symbol(index, spec.module)
        if holder is not None:
            return Resolution(holder, 0.95, "import_path", is_module=True, scope=dict(scope))
        return None
    namespace, _, name = spec.module.rpartition(".")
    found = index.scopes.get((LANG, namespace), {}).get(name)
    if found is None:
        return None
    if not spec.is_wildcard:  # `using A = X.Y.Type;` binds the one name
        return Resolution(found, 0.95, "import_path")
    # `using static X.Y.Type;` -- every member, not only the static ones: `Symbol` carries no
    # modifiers, and an instance member reached this way would have been an error anyway.
    members = index.members.get((found.path, found.qualname), {})
    return Resolution(found, 0.95, "import_path", scope=dict(members))


def _scope_symbol(index, namespace: str) -> Symbol | None:
    """
    The symbol an IMPORTS edge to a whole namespace points at: the module of the first file
    that declares it. A namespace is not a node, and the first declaration is the same choice
    `build_index` already makes when it merges a scope's names.
    """
    for facts in index.files.values():
        if facts.lang == LANG and facts.scope == namespace and facts.symbols:
            return facts.symbols[0]
    return None


def scope_defines(index, facts: FileFacts) -> dict[str, Symbol]:
    """Every type of this file's namespace: visible with no `using`, so ω 1.00 `same_scope`."""
    if not facts.scope:
        return {}
    return dict(index.scopes.get((LANG, facts.scope), {}))


def is_test_path(path: str) -> bool:
    """
    C# names test code by project and by class: `Orders.Tests/OrderServiceTests.cs` is one
    twice over. Neither spelling matches the shared default, which looks for `tests/` exactly
    and `_test`/`.spec` suffixes.
    """
    parts = path.replace("\\", "/").split("/")
    for part in parts[:-1]:
        folded = part.lower()
        if folded in ("test", "tests") or folded.endswith((".test", ".tests")):
            return True
    stem = parts[-1].rsplit(".", 1)[0] if "." in parts[-1] else parts[-1]
    return stem.endswith(("Test", "Tests"))


def is_test_function(symbol: Symbol) -> bool:
    """
    A C# test case is an ordinary method with an attribute on it -- `[Fact] public void
    Place_totals()` -- so there is no name convention to match, the way `test_*` and
    `TestPlace` are matched. `resolve._is_test_function` has already checked `is_test`, which
    the walker sets from the attribute *and* from the file being test code; what is left to
    say is only that a type or a module is not itself a test case.
    """
    return symbol.kind == "method"


def test_stem(path: str) -> str | None:
    """`Orders.Tests/OrderServiceTests.cs` -> `OrderService`; `None` when the name is not a test's."""
    stem = module_qualname(path).rpartition(".")[2]
    for suffix in ("Tests", "Test"):
        if stem.endswith(suffix) and len(stem) > len(suffix):
            return stem[: -len(suffix)]
    return None


# What `languages.RULES["csharp"]` is. `base` is C#'s `super`, and is per language because
# `from . import base` makes it an ordinary module name in Python.
RULES_ENTRY = LanguageRules(
    name=LANG,
    line_comment="//",
    walk=walk,
    resolve_module=resolve_module,
    scope_defines=scope_defines,
    module_qualname=module_qualname,
    is_test_path=is_test_path,
    test_stem=test_stem,
    is_test_function=is_test_function,
    super_names=SUPER_NAMES | {"base"},
)
