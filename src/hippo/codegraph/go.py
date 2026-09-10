"""
Pass 1 for Go: one file's CST becomes `FileFacts`.

The same contract as python.py -- report what is written, resolve nothing -- with the
three things Go does differently:

* **A package is a directory, not a file.** `billing/orders.go` and `billing/invoice.go`
  see each other's top-level names with no import at all, so the file's `scope` is its
  directory and an import resolves to a *scope* (`Resolution.scope`) rather than to one
  file. That is what makes `bill.Total` reachable when `Total` is in a sibling file.
* **A type's methods live outside it.** `func (s *Service) Place(...)` is a top-level
  declaration whose qualname is `Service.Place`, so the resolver's member table finds it
  exactly as it finds a Python method -- but a Go type declaration has no members *inside*
  it, so `header_end` is `line_end`: there is nothing in the declaration to stop before. The
  chunker groups by owner rather than by position, so the type's header passage is those lines
  plus one placeholder per method, wherever below the type that method is written.
* **There are no exceptions.** `panic("x")` is an ordinary unresolved call and `error` is a
  return value, so a Go file records no `RaiseFact` at all and gets no RAISES/CATCHES edge
  (add_langs.md "Decisions taken here").

What becomes a symbol: the module, every `func`, every method, and every `type X struct`
or `type X interface`. A type alias, a defined type over a builtin (`type ID int`) and a
func literal do not -- they stay in the passage of whatever holds them, which is what keeps
a passage readable.
"""

from __future__ import annotations

import posixpath

from tree_sitter import Node

from .model import (
    AssignFact,
    BaseFact,
    CallFact,
    FileFacts,
    ImportFact,
    LanguageRules,
    LiteralFact,
    Symbol,
    is_test_path,
    module_qualname,
    symbol_id,
)
from .treesitter import end_line_of, line_of, text_of

# A call under one of these is conditional. Go's `else` is a block hanging off the
# `if_statement`, and every `switch`/`select` arm is its own node, so walking up from the
# call reaches one of these whenever the call is not unconditional.
BRANCH_TYPES = {
    "if_statement",
    "for_statement",
    "expression_switch_statement",
    "type_switch_statement",
    "select_statement",
    "expression_case",
    "default_case",
    "type_case",
    "communication_case",
}

# Nodes that define something. A container's walk stops at these: what is inside belongs to
# another symbol (a method), or to nobody (a func literal).
DEFINITIONS = {"function_declaration", "method_declaration", "type_declaration", "func_literal"}

# The two string forms, and the two node types their content arrives in.
STRING_TYPES = ("interpreted_string_literal", "raw_string_literal")
STRING_CONTENT = ("interpreted_string_literal_content", "raw_string_literal_content", "escape_sequence")

# What a test function is called (`go test` runs exactly these). Go's convention is the
# reason `LanguageRules.is_test_function` exists: the shared rule is `test_*`, lowercase.
TEST_PREFIXES = ("Test", "Benchmark", "Example")


def walk(path: str, root: Node, source_id: str) -> FileFacts:
    """Turn one parsed Go file into the facts resolve.py needs."""
    module = module_qualname(path)
    is_test = is_test_path(path)
    facts = FileFacts(path=path, lang="go", module=module, scope=package_dir(path))

    package = next((c for c in root.children if c.type == "package_clause"), None)
    module_symbol = Symbol(
        id=symbol_id(source_id, path, module, "module"),
        source_id=source_id,
        name=module.rpartition(".")[2] or module,
        qualname=module,
        kind="module",
        lang="go",
        path=path,
        line_start=1,
        line_end=end_line_of(root),
        doc=_doc(package) if package is not None else "",
        is_test=is_test,
        module=module,
        display=module,
        statement_lines=_statement_lines(root),
    )
    facts.symbols.append(module_symbol)

    bodies: list[tuple[Symbol, Node]] = []
    owned: set[int] = set()
    _declarations(facts, root, source_id, is_test, bodies, owned)
    module_symbol.header_end = _header_end(module_symbol, facts.symbols)

    _imports(facts, root)
    _walk_body(facts, module_symbol, root, is_test, owned)
    for symbol, body in bodies:
        _walk_body(facts, symbol, body, is_test, owned)
    return facts


def package_dir(path: str) -> str:
    """
    The package a file belongs to: its directory, not the name in its `package` clause.

    Two directories may both say `package main` -- `cmd/main.go` and `tools/build.go` do --
    and they are two packages, so merging their names would invent edges between programs
    that share nothing. `.` is the root directory, kept truthy so `build_index` records it.
    """
    head, _, _ = path.replace("\\", "/").rpartition("/")
    return head or "."


# ------------------------------------------------------------ the symbols


def _declarations(
    facts: FileFacts,
    root: Node,
    source_id: str,
    is_test: bool,
    bodies: list[tuple[Symbol, Node]],
    owned: set[int],
) -> None:
    """Every func, method and struct/interface type at the top level, in source order."""
    for child in root.children:
        if child.type == "function_declaration":
            _function(facts, child, "", source_id, is_test, bodies, owned)
        elif child.type == "method_declaration":
            _function(facts, child, _receiver_type(child), source_id, is_test, bodies, owned)
        elif child.type == "type_declaration":
            _types(facts, child, source_id, is_test, owned)


def _function(
    facts: FileFacts,
    node: Node,
    receiver: str,
    source_id: str,
    is_test: bool,
    bodies: list[tuple[Symbol, Node]],
    owned: set[int],
) -> None:
    """One `func`. With a receiver type it is the method `Receiver.Name`, else a function."""
    name = text_of(node.child_by_field_name("name"))
    body = node.child_by_field_name("body")
    if not name:
        return
    qualname = f"{receiver}.{name}" if receiver else name
    kind = "method" if receiver else "function"
    symbol = Symbol(
        id=symbol_id(source_id, facts.path, qualname, kind),
        source_id=source_id,
        name=name,
        qualname=qualname,
        kind=kind,
        lang="go",
        path=facts.path,
        line_start=line_of(node),
        line_end=end_line_of(node),
        signature=_signature(node, body),
        doc=_doc(node),
        is_test=is_test,
        params=_params(node),
        module=facts.module,
        display=f"{facts.module}.{qualname}",
        statement_lines=_statement_lines(body) if body is not None else [],
    )
    symbol.header_end = symbol.line_end
    facts.symbols.append(symbol)
    owned.add(node.id)
    if body is not None:
        bodies.append((symbol, body))


def _types(facts: FileFacts, node: Node, source_id: str, is_test: bool, owned: set[int]) -> None:
    """
    `type X struct {...}` / `type X interface {...}` -- a class either way.

    An interface is a class with no methods of its own: its method signatures have no
    bodies, so they stay in the type's header passage rather than becoming symbols nothing
    could show. A type alias and a defined type over a builtin become no symbol at all.
    """
    specs = [child for child in node.children if child.type == "type_spec"]
    for spec in specs:
        inner = spec.child_by_field_name("type")
        name = text_of(spec.child_by_field_name("name"))
        if inner is None or not name or inner.type not in ("struct_type", "interface_type"):
            continue
        # A lone `type X struct` starts its passage at the `type` keyword; inside a grouped
        # `type ( ... )` the spec is the only honest start line.
        outer = node if len(specs) == 1 else spec
        fields = _field_list(inner)
        members = fields if fields is not None else inner
        symbol = Symbol(
            id=symbol_id(source_id, facts.path, name, "class"),
            source_id=source_id,
            name=name,
            qualname=name,
            kind="class",
            lang="go",
            path=facts.path,
            line_start=line_of(outer),
            line_end=end_line_of(outer),
            signature=_signature(outer, _brace(members)),
            doc=_doc(outer),
            is_test=is_test,
            module=facts.module,
            display=f"{facts.module}.{name}",
            statement_lines=_statement_lines(members),
        )
        # A Go type has no members inside it -- `func (s *Service) Place` is a top-level
        # declaration -- so the whole declaration is its header.
        symbol.header_end = symbol.line_end
        facts.symbols.append(symbol)
        owned.add(node.id)
        if inner.type == "struct_type":
            _embedded(facts, name, fields)


def _field_list(inner: Node) -> Node | None:
    """A struct's `field_declaration_list`, or None -- an interface holds its `method_elem`s
    directly, with no list node around them."""
    found = inner.child_by_field_name("body")
    if found is not None:
        return found
    return next((c for c in inner.children if c.type == "field_declaration_list"), None)


def _brace(members: Node) -> Node | None:
    """
    The `{` that opens a type's body, which is where its signature stops: `type Service
    struct`, `type Lister interface`. A struct's brace sits on its field list and an
    interface's on the type itself, so the node to look at is whichever holds the members.
    """
    return next((c for c in members.children if not c.is_named and text_of(c) == "{"), None)


def _embedded(facts: FileFacts, cls: str, fields: Node | None) -> None:
    """
    Struct embedding is Go's inheritance: a `field_declaration` with a type and no name.

    `struct { store.Base }` promotes `Base`'s methods onto `Service`, which is exactly what
    INHERITS means here. Interface satisfaction is implicit and gets no edge (D: Go).
    """
    if fields is None:
        return
    for field in fields.children:
        if field.type != "field_declaration" or field.child_by_field_name("name") is not None:
            continue
        base = _type_name(field.child_by_field_name("type"))
        if base:
            facts.bases.append(BaseFact(cls=cls, base=base, line=line_of(field)))


def _receiver_type(node: Node) -> str:
    """`func (s *Service[T]) Place(...)` -> `Service`: the type the method hangs off."""
    receiver = node.child_by_field_name("receiver")
    if receiver is None:
        return ""
    declaration = next((c for c in receiver.children if c.type == "parameter_declaration"), None)
    if declaration is None:
        return ""
    return _type_name(declaration.child_by_field_name("type"))


def _receiver_name(node: Node) -> str:
    """The receiver *variable* (`s`), which the bodies below rewrite to `self`."""
    receiver = node.child_by_field_name("receiver")
    if receiver is None:
        return ""
    declaration = next((c for c in receiver.children if c.type == "parameter_declaration"), None)
    return text_of(declaration.child_by_field_name("name")) if declaration is not None else ""


def _type_name(node: Node | None) -> str:
    """A type expression as a name: pointers and type arguments dropped, package kept."""
    text = _one_line(text_of(node)).lstrip("*&")
    return text.split("[")[0].strip()


def _params(node: Node) -> list[str]:
    """
    Parameter names, in order, for the INVOKES `arg_binding`.

    A method's receiver is recorded as `self` rather than by its own letter: `_arg_binding`
    drops a first parameter only when it is one of the language's `self_names`, and a Go
    receiver is spelled differently in every method (`s`, `b`, `svc`). The bodies rewrite
    the receiver variable to `self` too, so the two halves agree.
    """
    names = ["self"] if node.type == "method_declaration" else []
    params = node.child_by_field_name("parameters")
    if params is None:
        return names
    for child in params.children:
        if child.type not in ("parameter_declaration", "variadic_parameter_declaration"):
            continue
        # `func f(a, b int)` is one declaration with two names; an unnamed parameter
        # (`func f(int)`) has none, and contributes nothing to bind against.
        names.extend(text_of(c) for c in child.children if c.type == "identifier")
    return [name for name in names if name]


def _signature(node: Node, body: Node | None) -> str:
    """The declaration down to its body, whitespace collapsed: `func (s *Service) Place(o Order) int`."""
    if body is None or node.text is None or body.start_byte < node.start_byte:
        return " ".join(text_of(node).splitlines()[0].split())
    head = node.text[: body.start_byte - node.start_byte].decode("utf-8", errors="replace")
    return " ".join(head.split()).strip()


def _doc(node: Node) -> str:
    """
    The Go doc comment: the run of `//` lines immediately above a declaration, first
    paragraph only. A blank line ends the run, and a blank comment line (`//`) ends the
    paragraph -- Go's convention is a summary sentence, then the details.
    """
    lines: list[str] = []
    previous, expected = node.prev_sibling, line_of(node) - 1
    while previous is not None and previous.type == "comment" and end_line_of(previous) == expected:
        lines.append(text_of(previous))
        expected = line_of(previous) - 1
        previous = previous.prev_sibling
    paragraph: list[str] = []
    for raw in reversed(lines):
        text = _comment_text(raw)
        if not text.strip():  # a bare `//` ends the summary and starts the details
            break
        for line in text.splitlines():
            if not line.strip():
                return "\n".join(paragraph).strip()
            paragraph.append(line.strip())
    return "\n".join(paragraph).strip()


def _comment_text(raw: str) -> str:
    """One comment node's text, without its marks. Both `// x` and `/* x */` are doc comments."""
    if raw.startswith("//"):
        return raw[2:].strip()
    if raw.startswith("/*"):
        return raw.removeprefix("/*").removesuffix("*/").strip()
    return raw.strip()


def _statement_lines(body: Node | None) -> list[int]:
    """Start lines of a body's own statements -- where an oversized passage may be split."""
    if body is None:
        return []
    block = next((c for c in body.children if c.type == "statement_list"), body)
    return [line_of(child) for child in block.children if child.is_named and child.type != "comment"]


def _header_end(symbol: Symbol, symbols: list[Symbol]) -> int:
    """A module's header: everything before its first top-level declaration."""
    members = [s for s in symbols if s is not symbol and "." not in s.qualname and s.kind != "module"]
    if not members:
        return symbol.line_end
    return min(m.line_start for m in members) - 1


# ---------------------------------------------------------- what bodies do


def _walk_body(facts: FileFacts, symbol: Symbol, body: Node, is_test: bool, owned: set[int]) -> None:
    """
    Calls, bindings and literals inside one symbol, attributed to it.

    A module's walk stops at the declarations that became symbols of their own, and at the
    `package` and `import` clauses -- an import path is a string, and letting it through
    would offer every dependency's path to the literal classifier. A function's walk does
    not stop: a func literal is deliberately not a symbol, so what it calls belongs to the
    function it is written in, which is also the passage it lands in.
    """
    container = symbol.kind in ("module", "class")
    receiver = _receiver_name(body.parent) if body.parent is not None else ""
    collections: dict[str, str] = {}
    for child in body.children:
        if container and (child.id in owned or child.type in ("package_clause", "import_declaration")):
            continue
        stack = [child]
        while stack:
            node = stack.pop()
            _record(facts, symbol, node, is_test, receiver, collections)
            stack.extend(reversed(node.children))


def _record(
    facts: FileFacts,
    symbol: Symbol,
    node: Node,
    is_test: bool,
    receiver: str,
    collections: dict[str, str],
) -> None:
    if node.type == "call_expression":
        facts.calls.append(_call(symbol.qualname, node, receiver, collections))
    elif node.type in ("short_var_declaration", "var_spec"):
        _binding(facts, symbol, node, collections)
    elif node.type in STRING_TYPES:
        content = "".join(text_of(c) for c in node.children if c.type in STRING_CONTENT)
        if content:
            facts.literals.append(LiteralFact(caller=symbol.qualname, text=content, line=line_of(node)))
    elif node.type in ("identifier", "type_identifier", "field_identifier") and is_test:
        if symbol.kind in ("function", "method"):
            facts.names.setdefault(text_of(node), []).append(line_of(node))


def _call(caller: str, node: Node, receiver: str, collections: dict[str, str]) -> CallFact:
    """
    One call site. `go f()` and `defer f()` are calls like any other -- neither is an await,
    and both are as much a dependency of the caller as a plain call is.
    """
    target = node.child_by_field_name("function")
    holder, name = "", ""
    if target is not None and target.type == "selector_expression":
        holder = _one_line(text_of(target.child_by_field_name("operand")))
        name = text_of(target.child_by_field_name("field"))
    elif target is not None:
        name = _one_line(text_of(target))
    args = _arguments(node)
    return CallFact(
        caller=caller,
        receiver=_normalise(holder, receiver, collections),
        name=name,
        line=line_of(node),
        in_branch=_in_branch(node),
        args=args,
    )


def _normalise(holder: str, receiver: str, collections: dict[str, str]) -> str:
    """
    What the thing before the dot really is.

    Three rewrites, all of them saying the same thing the reader of the file says: a
    composite literal is its type (`(&Service{}).Place` is a call on `Service`), the
    enclosing method's receiver variable is `self` (so `s.db.Query` is `self.db.Query`, an
    unresolvable chain, and `s.Log` is `self.Log`, the class's own method), and a local
    bound to a collection chain stands for that chain, so `coll.InsertOne` is still the
    Mongo access `client.Database("app").Collection("orders").InsertOne` is.
    """
    text = holder.strip()
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    text = text.lstrip("*&")
    if text.endswith("}") and "{" in text:  # `Service{}` / `orders.Order{Total: 1}`
        text = text[: text.index("{")].strip()
    head, dot, tail = text.partition(".")
    if receiver and head == receiver:
        return f"self{dot}{tail}"
    return collections.get(text, text)


def _arguments(node: Node) -> list[str]:
    """The argument expressions, in order. Go has no keyword arguments."""
    arguments = node.child_by_field_name("arguments")
    if arguments is None:
        return []
    return [_one_line(text_of(c)) for c in arguments.children if c.is_named]


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _in_branch(node: Node) -> bool:
    parent = node.parent
    while parent is not None and parent.type not in DEFINITIONS and parent.type != "source_file":
        if parent.type in BRANCH_TYPES:
            return True
        parent = parent.parent
    return False


def _binding(facts: FileFacts, symbol: Symbol, node: Node, collections: dict[str, str]) -> None:
    """
    `s := &Service{}`, `var s Service = Service{}`, `s := NewService()` -- what a later
    `s.Place()` has to go through -- and `coll := ...Collection("orders")`, which is not a
    construction at all but the name of a Mongo collection.
    """
    for target, value in _bindings(node):
        if _collection_chain(value):
            collections.setdefault(target, value)
            continue
        constructed = _constructed(value)
        if constructed:
            facts.assignments.append(
                AssignFact(scope=symbol.qualname, target=target, value=constructed, line=line_of(node))
            )


def _bindings(node: Node) -> list[tuple[str, str]]:
    """`(name, value text)` pairs of one `:=` or `var` declaration, paired left to right."""
    if node.type == "short_var_declaration":
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        names = [text_of(c) for c in left.children if c.type == "identifier"] if left is not None else []
        values = [_one_line(text_of(c)) for c in right.children if c.is_named] if right is not None else []
    else:
        names = [text_of(c) for c in node.children if c.type == "identifier"]
        value = node.child_by_field_name("value")
        values = [_one_line(text_of(c)) for c in value.children if c.is_named] if value is not None else []
    return [(name, value) for name, value in zip(names, values, strict=False) if name and value]


def _collection_chain(value: str) -> bool:
    """True for `client.Database("app").Collection("orders")` and its siblings."""
    from .data_access import collection_of

    return bool(collection_of(value))


def _constructed(value: str) -> str:
    """
    The type a value expression constructs: `&Service{}` and `Service{}` are a `Service`,
    and so is `NewService()` -- Go has no constructors, and `NewT` returning a `T` is the
    convention every Go program follows in their place.
    """
    text = value.lstrip("*&").strip()
    if text.endswith("}") and "{" in text:
        return text[: text.index("{")].strip()
    if not text.endswith(")") or "(" not in text:
        return ""
    called = text[: text.index("(")].strip()
    head, dot, tail = called.rpartition(".")
    if not tail.startswith("New") or len(tail) <= 3 or not tail[3].isupper():
        return ""
    return f"{head}{dot}{tail[3:]}"


# ------------------------------------------------------------- the imports


def _imports(facts: FileFacts, root: Node) -> None:
    """
    Every import, as written. `bill "example.com/goapp/billing"` binds `bill`; a plain
    import binds the path's last segment, which is what Go itself does when the package
    name and the directory agree (and they do, by convention).
    """
    for node in root.children:
        if node.type != "import_declaration":
            continue
        for spec in _specs(node):
            path = spec.child_by_field_name("path")
            module = "".join(text_of(c) for c in path.children if c.type in STRING_CONTENT) if path else ""
            if not module:
                continue
            alias = text_of(spec.child_by_field_name("name")) or module.rsplit("/", 1)[-1]
            facts.imports.append(ImportFact(module=module, alias=alias, line=line_of(spec)))


def _specs(node: Node) -> list[Node]:
    """The specs of `import "x"` and of a parenthesised `import ( ... )` block alike."""
    found = [c for c in node.children if c.type == "import_spec"]
    for child in node.children:
        if child.type == "import_spec_list":
            found.extend(c for c in child.children if c.type == "import_spec")
    return found


# ---------------------------------------------------------- the resolution


def source_setup(docs: list) -> dict[str, str]:
    """
    Every `go.mod` in the source: `{module path: the directory it governs}`.

    Read once per `extract_code`, from the raw documents -- `go.mod` is not a file any
    walker parses -- and consulted by `resolve_module` to turn `example.com/goapp/billing`
    into the directory `goapp/billing`. A source with no `go.mod` in it simply gets `{}`
    and the directory-suffix rule below does the work.
    """
    roots: dict[str, str] = {}
    for doc in docs:
        path = (getattr(doc, "title", "") or getattr(doc, "path", "") or "").replace("\\", "/")
        if path.rpartition("/")[2] != "go.mod":
            continue
        for line in (getattr(doc, "text", "") or "").splitlines():
            head, _, rest = line.strip().partition(" ")
            if head == "module" and rest.strip():
                roots.setdefault(rest.strip(), posixpath.dirname(path))
                break
    return roots


def resolve_module(index, facts: FileFacts, spec: ImportFact):
    """
    What `import "example.com/goapp/billing"` names: the *package* in `goapp/billing`, as a
    `Resolution` carrying every name that package declares.

    A Go import binds a package, not a file, so `bill.Total` has to come out of the whole
    directory's names rather than one file's `defines` -- which is what `Resolution.scope`
    is for. The IMPORTS edge goes to the first file of the package by path, so two runs
    name the same module symbol.

    Two ways to find the directory, in order: the `module` line of a `go.mod` (exact), then
    the longest run of trailing path segments a directory shares with the import path
    (`example.com/goapp/billing` -> `myrepo-main/goapp/billing`, the shape a downloaded zip
    arrives in). The fallback needs two segments to agree, so `database/sql` never claims a
    local `sql/` and no single-segment stdlib path (`fmt`, `errors`) resolves at all.
    """
    from .resolve import Resolution  # `resolve` imports the registry, which imports this module

    directory = _directory_of(index, spec.module)
    if directory is None:
        return None
    scope = index.scopes.get(("go", directory), {})
    files = sorted(f.path for f in index.files.values() if f.lang == "go" and f.scope == directory)
    if not files:
        return None
    module_symbol = index.module_symbol(index.files[files[0]])
    return Resolution(module_symbol, 0.95, "import_path", is_module=True, scope=dict(scope))


def _directory_of(index, import_path: str) -> str | None:
    """The directory an import path names, by `go.mod` first and by suffix second."""
    if not import_path:
        return None
    directories = {facts.scope for facts in index.files.values() if facts.lang == "go" and facts.scope}
    roots = index.lang_state.get("go") or {}
    for module_path in sorted(roots, key=len, reverse=True):
        if import_path == module_path or import_path.startswith(f"{module_path}/"):
            rest = import_path[len(module_path) :].strip("/")
            found = posixpath.join(roots[module_path], rest) if rest else roots[module_path]
            return found or "."
    wanted = import_path.split("/")
    if len(wanted) < 2:  # a single segment is the standard library, and never in the repo
        return None
    best: list[str] = []
    depth = 0
    for directory in sorted(directories):
        shared = _shared_tail(directory.split("/"), wanted)
        if shared < 2 or shared < depth:
            continue
        if shared > depth:
            best, depth = [], shared
        best.append(directory)
    return best[0] if len(best) == 1 else None


def _shared_tail(left: list[str], right: list[str]) -> int:
    """How many trailing path segments two paths agree on."""
    shared = 0
    for one, other in zip(reversed(left), reversed(right), strict=False):
        if one != other:
            break
        shared += 1
    return shared


def scope_defines(index, facts: FileFacts) -> dict[str, Symbol]:
    """
    What this file sees without importing anything: the rest of its own package.

    The file's own names are seeded first by `resolve_imports`, so returning the whole
    package here costs nothing -- an own name stays `same_file` 1.00 and a sibling file's
    becomes `same_scope` 1.00, which is what Go's package really is.
    """
    return dict(index.scopes.get(("go", facts.scope or ""), {}))


def is_test_function(symbol: Symbol) -> bool:
    """What `go test` runs: `TestPlace`, `BenchmarkPlace`, `ExamplePlace`, in a `_test.go` file."""
    return symbol.kind in ("function", "method") and symbol.name.startswith(TEST_PREFIXES)


# ------------------------------------------------------------ registration

# What `languages.RULES["go"]` is. `module_qualname`, `is_test_path` and `test_stem` are the
# shared defaults on purpose: `billing/orders.go` is the module `billing.orders`,
# `service_test.go` is test code, and its stem is `service` -- Go's conventions and hippo's
# already agree, and a copy here would be one more thing to keep in step.
RULES_ENTRY = LanguageRules(
    name="go",
    line_comment="//",
    walk=walk,
    resolve_module=resolve_module,
    scope_defines=scope_defines,
    is_test_function=is_test_function,
    source_setup=source_setup,
)
