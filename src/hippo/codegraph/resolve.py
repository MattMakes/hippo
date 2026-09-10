"""
Pass 2: what the names in one source point at.

The walkers report `invoice(order)`; this file decides that `invoice` is
`pyapp.billing.send_invoice`, that the edge is INVOKES, that ω is 0.90 because it came
through an import, and that the provenance is `via_import`. Every ω and provenance in
here is from the plan's table (D24); none is invented, and the numbers are the whole
point -- a 0.50 `fuzzy_name` edge and a 1.00 `same_file` edge look identical in a graph
picture and mean very different things.

The two rules worth stating out loud:

* **A call that does not resolve inside this source produces no edge** (D24). Not a
  low-confidence edge, not an edge to a placeholder: nothing. `print`, `console.log` and
  `os.path.join` are simply absent, and each one is counted into
  `CodeGraph.stats()["unresolved_calls"]` so phase 2 has a baseline (D15).
* **A bare-name guess needs to be unique.** `obj.m()` with an unknown receiver only becomes
  an edge when exactly one symbol in the source is called `m`, in the same language, and
  `m` is not in `FUZZY_STOPLIST`. `x.get()` must never link to somebody's `get`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .data_access import Hit, collect, mongo_hit, mongoose_hit, read_sql_file
from .languages import RULES
from .model import (
    ARG_BINDING_MAX_CHARS,
    CodeEdge,
    DataObject,
    FileFacts,
    ImportFact,
    Symbol,
    data_id,
    package_of,
    symbol_key,
)

# Method names too common to guess from. A `fuzzy_name` edge on any of these would be
# noise at best and wrong at worst; 2.2b's "ambiguous or stoplisted -> no edge" row is
# what this list implements. Written in lower case and matched in lower case, so Go's and
# C#'s `Close`/`Get`/`Write` are the same names as Python's.
FUZZY_STOPLIST = frozenset(
    {
        "add", "all", "any", "append", "apply", "build", "call", "check", "clear", "close",
        "copy", "count", "debug", "decode", "each", "emit", "encode", "end", "error", "extend",
        "fetch", "filter", "first", "format", "get", "handle", "index", "info", "init", "insert",
        "items", "join", "keys", "len", "list", "load", "log", "main", "map", "max", "min",
        "next", "open", "parse", "pop", "print", "process", "push", "put", "read", "remove",
        "render", "replace", "reset", "result", "send", "set", "setup", "size", "sort", "sorted",
        "split", "start", "stop", "str", "strip", "sum", "then", "update", "validate", "value",
        "values", "warn", "warning", "write",
    }
)  # fmt: skip

# What a name has to look like before an unresolved `raise X` lands in `Symbol.raises`.
EXCEPTION_SUFFIXES = ("Error", "Exception", "Warning")
BUILTIN_EXCEPTIONS = frozenset(
    {
        "BaseException", "Exception", "ArithmeticError", "AssertionError", "AttributeError",
        "BufferError", "EOFError", "ImportError", "IndexError", "KeyError", "KeyboardInterrupt",
        "LookupError", "MemoryError", "NameError", "NotImplementedError", "OSError",
        "OverflowError", "RecursionError", "ReferenceError", "RuntimeError", "StopIteration",
        "SyntaxError", "SystemError", "SystemExit", "TypeError", "UnboundLocalError",
        "UnicodeDecodeError", "ValueError", "ZeroDivisionError", "Error",
    }
)  # fmt: skip

MAX_MRO_DEPTH = 5  # breadth-first, so this is five *levels* of bases, not five classes
MAX_REEXPORT_DEPTH = 5

# `super().m()` parses as two calls; the bare `super()` is syntax, not a reference, and
# counting it as unresolved would put language machinery in a graph-health number.
LANGUAGE_CALLS = {"super"}


@dataclass
class Resolution:
    """A resolved name: what it is, how sure we are, and which rule said so."""

    symbol: Symbol
    omega: float
    provenance: str
    is_module: bool = False
    # The names a *scope* holds, when this resolution is a Go package or a C# namespace
    # rather than a file or a class. `Ns.Member` goes through here; a language whose
    # imports only ever name files (Python, TypeScript) never sets it.
    scope: dict[str, Symbol] | None = None


@dataclass
class SourceIndex:
    """Everything pass 2 needs to look a name up, built once for the whole source."""

    files: dict[str, FileFacts] = field(default_factory=dict)  # path -> facts
    modules: dict[str, FileFacts] = field(default_factory=dict)  # module qualname -> facts
    symbols: dict[str, Symbol] = field(default_factory=dict)  # model.symbol_key -> symbol
    defines: dict[str, dict[str, Symbol]] = field(default_factory=dict)  # module -> top-level name
    members: dict[tuple[str, str], dict[str, Symbol]] = field(default_factory=dict)  # (path, class)
    by_name: dict[tuple[str, str], list[Symbol]] = field(default_factory=dict)  # (lang, name) -> symbols
    models: dict[str, dict[str, str]] = field(default_factory=dict)  # module -> binding -> collection
    bindings: dict[str, dict[str, Resolution]] = field(default_factory=dict)  # module -> alias
    bases: dict[tuple[str, str], list[Symbol]] = field(default_factory=dict)  # (path, class) -> bases
    by_suffix: dict[str, list[FileFacts]] = field(default_factory=dict)  # dotted tail -> modules
    # A Go package or a C# namespace: every top-level name its files declare, merged. Keyed
    # by (lang, scope) because two languages may spell the same scope name.
    scopes: dict[tuple[str, str], dict[str, Symbol]] = field(default_factory=dict)
    # Whatever `LanguageRules.source_setup` returned for a language, once per source: Go's
    # `go.mod` module path, Rust's crate root directory.
    lang_state: dict[str, Any] = field(default_factory=dict)

    def module(self, name: str) -> FileFacts | None:
        """
        A module by qualname; a package name also finds its `__init__` (2.2a keeps both).

        The suffix fallback is for zips. `read_zip` titles members with the archive's own
        root folder, so a downloaded repo's `pyapp/store.py` arrives as
        `myrepo-main/pyapp/store.py` and every absolute `from pyapp.store import Base` would
        otherwise miss. A suffix is accepted only when exactly one module matches it, so an
        ambiguous name still resolves to nothing.
        """
        if not name:
            return None
        found = self.modules.get(name) or self.modules.get(f"{name}.__init__")
        if found is not None:
            return found
        candidates = self.by_suffix.get(name, [])
        return candidates[0] if len(candidates) == 1 else None

    def module_symbol(self, facts: FileFacts) -> Symbol:
        return facts.symbols[0]

    def symbol(self, path: str, qualname: str, kind: str = "") -> Symbol | None:
        """
        One symbol of one file, by the same key its id is hashed from (`model.symbol_key`).

        Keyed that way and not by `(path, qualname)` for the reason the id is: in a root
        `foo.py` with a `def foo`, or a `main.go` with a `func main`, the module and the
        member are one pair and the later one would overwrite the earlier -- so a fact at
        module level would be attributed to the member, and the module symbol would be
        missing from this index entirely (E2F-b).

        `kind` matters only when it is `"module"`, so the default `""` asks for the member,
        which is what every caller that knows it is not looking at a file's own module wants.
        """
        return self.symbols.get(symbol_key(path, qualname, kind))


def build_index(files: list[FileFacts], lang_state: dict[str, Any] | None = None) -> SourceIndex:
    """One pass over every parsed file, so the second pass can look anything up by name."""
    index = SourceIndex(lang_state=dict(lang_state or {}))
    for facts in files:
        index.files[facts.path] = facts
        index.modules[facts.module] = facts
        index.defines.setdefault(facts.module, {})
        module_symbol = facts.symbols[0] if facts.symbols else None
        for symbol in facts.symbols:
            index.symbols[symbol_key(facts.path, symbol.qualname, symbol.kind)] = symbol
            index.by_name.setdefault((symbol.lang, symbol.name), []).append(symbol)
            # The file's *own* module symbol owns nothing above it, and its dotted qualname
            # is a path, not an owner. An inline module -- Rust's `mod tests { }` -- is an
            # ordinary container and takes the same route as a class.
            if symbol is module_symbol:
                continue
            owner, _, leaf = symbol.qualname.rpartition(".")
            if owner:
                index.members.setdefault((facts.path, owner), {})[leaf] = symbol
            else:
                index.defines[facts.module][symbol.qualname] = symbol
        if facts.scope:
            # A Go package / C# namespace is the union of its files' top-level names; the file
            # with the smallest path keeps a name two of them declare, so a partial class
            # resolves to one place whatever order the documents arrived in.
            scope = index.scopes.setdefault((facts.lang, facts.scope), {})
            for name, symbol in index.defines[facts.module].items():
                held = scope.get(name)
                if held is None or facts.path < held.path:
                    scope[name] = symbol
        if facts.models:
            index.models[facts.module] = {binding: name for binding, name, _ in facts.models}
        parts = (package_of(facts.module) or facts.module).split(".")
        for start in range(1, len(parts)):  # every proper dotted tail; the whole name is exact
            index.by_suffix.setdefault(".".join(parts[start:]), []).append(facts)
    return index


# ---------------------------------------------------------------- modules


def import_target(index: SourceIndex, facts: FileFacts, spec: ImportFact) -> FileFacts | Resolution | None:
    """
    What an import spec names, by the rule of the file's own language.

    Usually a file. For a language whose imports name a *scope* rather than a file -- a C#
    `using`, a Rust `use` of a module path -- it is a `Resolution` carrying that scope's
    names in `Resolution.scope`; only `resolve_imports` needs to tell the two apart.
    """
    return RULES[facts.lang].resolve_module(index, facts, spec)


def target_module(index: SourceIndex, facts: FileFacts, spec) -> FileFacts | None:
    """The *file* an import spec names, or None -- including when it names a scope."""
    found = import_target(index, facts, spec)
    return found if isinstance(found, FileFacts) else None


# ---------------------------------------------------------------- members


def resolve_member(index: SourceIndex, facts: FileFacts, name: str, depth: int = 0) -> Resolution | None:
    """
    What `name` means inside module `facts`: something it defines, one of its submodules,
    or -- following at most `MAX_REEXPORT_DEPTH` hops -- something it re-exports.

    ω follows the import row of the table: 0.95 when the named module really holds it,
    0.90 once a re-export was followed, 0.60 through a wildcard.
    """
    if depth > MAX_REEXPORT_DEPTH:
        return None
    reexport = depth > 0
    defined = index.defines.get(facts.module, {}).get(name)
    if defined is not None:
        return _member(defined, reexport)
    submodule = index.module(f"{package_of(facts.module)}.{name}")
    if submodule is not None:
        return _member(index.module_symbol(submodule), reexport, is_module=True)
    for spec in [*facts.imports, *facts.reexports]:
        if spec.is_wildcard or spec.alias != name:
            continue
        source = target_module(index, facts, spec)
        if source is None:
            continue
        if not spec.name or spec.name == "default":
            found = _default_export(index, source) if spec.is_default else None
            if found is None:
                return _member(index.module_symbol(source), True, is_module=True)
            return _member(found, True)
        deeper = resolve_member(index, source, spec.name, depth + 1)
        if deeper is not None:
            return Resolution(deeper.symbol, min(deeper.omega, 0.90), "reexport", deeper.is_module)
    for spec in [*facts.imports, *facts.reexports]:
        if not spec.is_wildcard:
            continue
        source = target_module(index, facts, spec)
        if source is None:
            continue
        deeper = resolve_member(index, source, name, depth + 1)
        if deeper is not None:
            return Resolution(deeper.symbol, 0.60, "wildcard", deeper.is_module)
    return None


def _member(symbol: Symbol, reexport: bool, *, is_module: bool = False) -> Resolution:
    return Resolution(
        symbol, 0.90 if reexport else 0.95, "reexport" if reexport else "import_path", is_module
    )


def _default_export(index: SourceIndex, facts: FileFacts) -> Symbol | None:
    """
    What `import x from "./b"` binds: the module's `export default`, or -- when the module
    declares no default -- its only symbol, which is the shape a one-thing module has.
    """
    if facts.default_export:
        found = index.defines.get(facts.module, {}).get(facts.default_export)
        if found is not None:
            return found
    exported = [s for s in facts.symbols if s.kind != "module"]
    return exported[0] if len(exported) == 1 else None


# ---------------------------------------------------------------- imports


def resolve_imports(index: SourceIndex) -> list[CodeEdge]:
    """IMPORTS edges, and the alias table every later lookup in that file goes through."""
    edges: list[CodeEdge] = []
    for facts in index.files.values():
        bindings: dict[str, Resolution] = {}
        rules = RULES[facts.lang]
        module_symbol = index.module_symbol(facts)
        # `export {x} from "./b"` is an import as far as the graph is concerned: this module
        # depends on that one, and anybody importing this name goes through here.
        for spec in [*facts.imports, *facts.reexports]:
            found_scope = import_target(index, facts, spec)
            if isinstance(found_scope, Resolution):
                # The spec names a scope, not a file: a C# `using`, a Rust `use` of a module
                # path. Every name the scope holds becomes visible, and the IMPORTS edge goes
                # to whatever symbol the language chose to stand for it.
                for name, symbol in (found_scope.scope or {}).items():
                    bindings.setdefault(name, Resolution(symbol, found_scope.omega, found_scope.provenance))
                if spec.alias:
                    bindings.setdefault(spec.alias, found_scope)
                edges.append(
                    _edge(
                        module_symbol,
                        found_scope.symbol,
                        "IMPORTS",
                        found_scope.omega,
                        found_scope.provenance,
                    )
                )
                continue
            source = found_scope
            if source is None:
                continue  # a dependency, not part of this source: no edge (2.2b)
            if spec.is_wildcard:
                edges.append(_edge(module_symbol, index.module_symbol(source), "IMPORTS", 0.60, "wildcard"))
                for name, symbol in index.defines.get(source.module, {}).items():
                    bindings.setdefault(name, Resolution(symbol, 0.60, "wildcard"))
                continue
            if spec.is_default:
                exported = _default_export(index, source)
                found = (
                    Resolution(exported, 0.95, "import_path")
                    if exported is not None
                    else Resolution(index.module_symbol(source), 0.95, "import_path", is_module=True)
                )
            elif not spec.name:
                found = Resolution(index.module_symbol(source), 0.95, "import_path", is_module=True)
            else:
                found = resolve_member(index, source, spec.name)
                if found is None:
                    continue
            if spec.alias:
                bindings[spec.alias] = found
            edges.append(_edge(module_symbol, found.symbol, "IMPORTS", found.omega, found.provenance))
        for name, symbol in index.defines.get(facts.module, {}).items():
            bindings.setdefault(name, Resolution(symbol, 1.00, "same_file"))
        # ...then the names this file sees without importing anything: the rest of its Go
        # package, its C# namespace. Its own definitions win, so a name declared here is
        # `same_file` 1.00; a sibling's is `same_scope`, also 1.00 -- the language resolves
        # it as unambiguously as a local name, and 0.90 `via_import` would understate it.
        # Python and TypeScript have no such scope and return `{}`, so nothing moves.
        for name, symbol in rules.scope_defines(index, facts).items():
            bindings.setdefault(name, Resolution(symbol, 1.00, "same_scope"))
        index.bindings[facts.module] = bindings
    return edges


# ------------------------------------------------------------------ bases


def declared(index: SourceIndex, facts: FileFacts, qualname: str) -> Symbol | None:
    """
    The symbol a fact in this file is *about*, which is usually written in this file.

    Rust is the exception: `impl Base for OrderService` says something about a type whose
    `struct` is in another file, so "which files may hold a member of `OrderService`" -- the
    language's own `member_paths` answer, the one `_on_class` already asks -- is also where
    to look for the type itself. Every other language answers "this file", so nothing moves.

    Always asked about a *container* -- a base class, or the owner half of a member's dotted
    qualname -- so the member reading of the key is the right one to try first, and a root
    `foo.py`'s `def foo` still owns the nested function inside it rather than losing it to
    the module. The fallback is for Rust's inline `mod tests { }`, which is a container of
    kind `module`; a file's own module symbol can never be reached this way, because its
    qualname is a path form and no member's qualname is prefixed with it.
    """
    for path in RULES[facts.lang].member_paths(index, qualname, facts.path):
        found = index.symbol(path, qualname) or index.symbol(path, qualname, "module")
        if found is not None:
            return found
    return None


def resolve_bases(index: SourceIndex) -> list[CodeEdge]:
    """INHERITS edges, plus the base list OVERRIDES and `via_inheritance` calls walk."""
    edges: list[CodeEdge] = []
    for facts in index.files.values():
        for base in facts.bases:
            child = declared(index, facts, base.cls)
            if child is None:
                continue
            found = _lookup_dotted(index, facts, base.base)
            if found is None or found.symbol.kind != "class":
                found = _fuzzy(index, facts.lang, base.base.rpartition(".")[2], kinds=("class",))
            if found is None:
                continue
            omega = 0.90 if found.provenance != "fuzzy_name" else 0.50
            provenance = "fuzzy_name" if found.provenance == "fuzzy_name" else "resolved"
            # Keyed by where the *type* is, not where the `impl` was written, so `_mro_lookup`
            # -- which is always handed a class's own path -- finds the bases either way.
            index.bases.setdefault((child.path, base.cls), []).append(found.symbol)
            edges.append(_edge(child, found.symbol, "INHERITS", omega, provenance))
    return edges


def resolve_overrides(index: SourceIndex) -> list[CodeEdge]:
    """A method that shadows one on a base, found breadth-first at most `MAX_MRO_DEPTH` deep."""
    edges: list[CodeEdge] = []
    for (path, qualname), members in sorted(index.members.items()):
        # The members are in `path`; the type they belong to may be in another file, which is
        # what a Rust `impl` in its own module is, so the owner is asked for the same way
        # `resolve_bases` asks -- and its own path is what `index.bases` is keyed by.
        owner = declared(index, index.files[path], qualname)
        if owner is None or owner.kind != "class":
            continue
        for name, method in members.items():
            if method.kind != "method":
                continue
            inherited = _mro_lookup(index, owner.path, qualname, name)
            if inherited is not None:
                edges.append(_edge(method, inherited, "OVERRIDES", 0.90, "mro"))
    return edges


def _mro_lookup(index: SourceIndex, path: str, qualname: str, name: str) -> Symbol | None:
    """The first base (breadth-first, `MAX_MRO_DEPTH` levels) that defines `name`."""
    frontier = list(index.bases.get((path, qualname), []))
    seen: set[str] = set()
    for _ in range(MAX_MRO_DEPTH):
        following: list[Symbol] = []
        for base in frontier:
            if base.id in seen:
                continue
            seen.add(base.id)
            found = index.members.get((base.path, base.qualname), {}).get(name)
            if found is not None:
                return found
            following.extend(index.bases.get((base.path, base.qualname), []))
        if not following:
            return None
        frontier = following
    return None


# ------------------------------------------------------------------ calls


def resolve_calls(index: SourceIndex, facts: FileFacts) -> tuple[list[CodeEdge], list[tuple[str, Hit]], int]:
    """
    INVOKES edges, the data accesses a call chain implies, and how many calls resolved to
    nothing. A call that is really an exception constructor is left to `resolve_raises`.

    The hits come back keyed by the caller's `symbol_key`, not by its qualname, because that
    is what `resolve_data` has to look a holder up by.
    """
    edges: list[CodeEdge] = []
    hits: list[tuple[str, Hit]] = []
    raised = {
        (symbol_key(facts.path, exc.caller, exc.caller_kind), exc.line, exc.name.rpartition(".")[2])
        for exc in facts.exceptions
    }
    unresolved = 0
    for call in facts.calls:
        caller_key = symbol_key(facts.path, call.caller, call.caller_kind)
        caller = index.symbols.get(caller_key)
        if caller is None:
            continue
        if (caller_key, call.line, call.name) in raised:
            continue  # `raise OrderError(...)` is a RAISES edge, not also a call to the class
        if not call.receiver and call.name in LANGUAGE_CALLS:
            continue  # `super()` is the language's own machinery, not a reference to resolve
        hit = _data_call(index, facts, call)
        if hit is not None:
            hits.append((caller_key, hit))
            continue
        found = _call_target(index, facts, call)
        if found is None:
            unresolved += 1
            continue
        edges.append(
            _edge(
                caller,
                found.symbol,
                "INVOKES",
                found.omega,
                found.provenance,
                extra={
                    "call_line": call.line,
                    "in_branch": call.in_branch,
                    "is_await": call.is_await,
                    "arg_binding": _arg_binding(found.symbol, call),
                },
            )
        )
    return edges, hits, unresolved


def _call_target(index: SourceIndex, facts: FileFacts, call) -> Resolution | None:
    receiver, name = call.receiver, call.name
    rules = RULES[facts.lang]
    owner = call.caller.rpartition(".")[0]
    if not receiver:
        return _lookup_name(index, facts, name)
    if receiver in rules.self_names:
        return _on_class(index, facts, owner, name)
    if receiver in rules.super_names or receiver.rstrip("()") == "super":
        inherited = _mro_lookup(index, facts.path, owner, name)
        return Resolution(inherited, 0.90, "via_inheritance") if inherited is not None else None
    holder = _receiver_type(index, facts, call, receiver)
    if holder is not None:
        if holder.scope is not None:
            return _in_scope(facts, holder, name)
        if holder.is_module:
            found = resolve_member(index, index.modules[holder.symbol.qualname], name)
            return _through(facts, found) if found is not None else None
        return _on_class(index, facts, holder.symbol.qualname, name, holder.symbol.path)
    # A guess is only allowed about one unknown thing. `x.y.z()` is 2.2b's "unresolvable
    # chain -> no edge" row: we do not know what `x.y` is, so `z` is not ours to guess at.
    if not receiver.isidentifier():
        return None
    return _fuzzy(index, facts.lang, name, kinds=("function", "method"))


def _receiver_type(index: SourceIndex, facts: FileFacts, call, receiver: str) -> Resolution | None:
    """What the thing before the dot is: a module, a class, or a variable holding one."""
    if receiver.endswith(")") and "(" in receiver:  # `OrderService().place(...)`
        receiver = receiver[: receiver.index("(")]
    found = _lookup_name(index, facts, receiver)
    if found is not None and (found.is_module or found.scope is not None or found.symbol.kind == "class"):
        return found
    scope = symbol_key(facts.path, call.caller, call.caller_kind)
    for assignment in facts.assignments:
        if symbol_key(facts.path, assignment.scope, assignment.scope_kind) != scope:
            continue
        if assignment.target != receiver:
            continue
        if assignment.line > call.line:
            continue
        built = _lookup_name(index, facts, assignment.value.rpartition(".")[2])
        if built is not None and built.symbol.kind == "class":
            return built
    return None


def _on_class(
    index: SourceIndex, facts: FileFacts, qualname: str, name: str, path: str | None = None
) -> Resolution | None:
    """
    `name` on a class: its own member first (1.00), then its bases (0.90).

    A class's members usually all live in the file that declares it; Rust spreads them over
    every file with an `impl` for the type, so which files to try is the language's call.
    """
    if not qualname:
        return None
    path = path or facts.path
    for candidate in RULES[facts.lang].member_paths(index, qualname, path):
        found = index.members.get((candidate, qualname), {}).get(name)
        if found is not None:
            return Resolution(found, *_member_tier(index, facts, candidate))
    inherited = _mro_lookup(index, path, qualname, name)
    return Resolution(inherited, 0.90, "via_inheritance") if inherited is not None else None


def _member_tier(index: SourceIndex, facts: FileFacts, candidate: str) -> tuple[float, str]:
    """
    What a member found in `candidate` is worth, by how far away that file is.

    The file itself is 1.00 `same_file`. A sibling of the same Go package or C# namespace is
    1.00 `same_scope`: the language resolves it with no import at all, which is the same
    reason `resolve_imports` gives a bare same-scope name 1.00, and calling a *method* of a
    sibling file 0.90 would contradict it. Anything else came through an import, at 0.90.

    Python and TypeScript have no scope above the file, so `facts.scope` is None and the
    middle row is unreachable for them -- `None == None` is deliberately not enough.
    """
    if candidate == facts.path:
        return 1.00, "same_file"
    other = index.files.get(candidate)
    if facts.scope is not None and other is not None:
        if other.lang == facts.lang and other.scope == facts.scope:
            return 1.00, "same_scope"
    return 0.90, "via_import"


def _through(facts: FileFacts, found: Resolution) -> Resolution:
    """A member reached through another module is `via_import`; in this file it is `same_file`."""
    if found.symbol.path == facts.path:
        return Resolution(found.symbol, 1.00, "same_file", found.is_module)
    return Resolution(found.symbol, 0.90, "via_import", found.is_module)


def _in_scope(facts: FileFacts, holder: Resolution, name: str) -> Resolution | None:
    """
    `ledger.Post` where `ledger` is a Go package or a C# namespace, not a file: the name
    comes out of the scope, and `_through` puts it in the INVOKES tier its distance earns.
    """
    found = (holder.scope or {}).get(name)
    if found is None:
        return None
    return _through(facts, Resolution(found, holder.omega, holder.provenance))


def _lookup_name(index: SourceIndex, facts: FileFacts, name: str) -> Resolution | None:
    """A bare name in one file: its import bindings, then its own top-level definitions."""
    if not name:
        return None
    found = index.bindings.get(facts.module, {}).get(name)
    if found is None:
        return None
    if found.provenance in ("same_file", "same_scope"):
        return found
    # Any import-resolved call is 0.90 `via_import`: the ω table gives INVOKES three import
    # tiers (plus `same_scope`, which is not one -- the name needed no import), and a
    # wildcard import's own uncertainty is already on its 0.60 IMPORTS edge.
    return Resolution(found.symbol, 0.90, "via_import", found.is_module, found.scope)


def _lookup_dotted(index: SourceIndex, facts: FileFacts, text: str) -> Resolution | None:
    """
    `models.base.Model`: try the whole text first -- `import models.base` binds the alias
    `models.base`, dots and all -- then resolve the head and ask it for the tail.
    """
    found = _lookup_name(index, facts, text)
    if found is not None:
        return found
    if "." not in text:
        return None
    head, _, tail = text.rpartition(".")
    holder = _lookup_dotted(index, facts, head)
    if holder is None:
        return None
    if holder.scope is not None:
        return _in_scope(facts, holder, tail)
    if holder.is_module:
        found = resolve_member(index, index.modules[holder.symbol.qualname], tail)
        return _through(facts, found) if found is not None else None
    if holder.symbol.kind == "class":
        return _on_class(index, facts, holder.symbol.qualname, tail, holder.symbol.path)
    return None


def _fuzzy(index: SourceIndex, lang: str, name: str, kinds: tuple[str, ...]) -> Resolution | None:
    """
    2.2b's last resort: exactly one symbol of the right kind in this language carries the
    name, and the name is not one everybody uses. Anything else is no edge at all.

    The stoplist is matched case-insensitively: `Close`, `Get` and `Write` are as ordinary
    in Go and C# as `close`, `get` and `write` are in Python, and a list written in one case
    would refuse the guess for one language and wave it through for another.
    """
    if not name or name.lower() in FUZZY_STOPLIST:
        return None
    candidates = [s for s in index.by_name.get((lang, name), []) if s.kind in kinds]
    if len(candidates) != 1:
        return None
    return Resolution(candidates[0], 0.50, "fuzzy_name")


def _arg_binding(callee: Symbol, call) -> dict[str, str]:
    """Callee parameter names bound to the caller's argument expressions, cut at 60 chars."""
    params = list(callee.params)
    if call.receiver and params and params[0] in RULES[callee.lang].self_names:
        params = params[1:]
    # strict=False on purpose: a call may pass fewer arguments than the callee declares
    # (defaults) or more (*args), and either way we bind the pairs we are sure of.
    binding = {name: value[:ARG_BINDING_MAX_CHARS] for name, value in zip(params, call.args, strict=False)}
    for key, value in call.kwargs.items():
        if key in callee.params:
            binding[key] = value[:ARG_BINDING_MAX_CHARS]
    return binding


# ------------------------------------------------------- raises and catches


def resolve_raises(index: SourceIndex, facts: FileFacts) -> list[CodeEdge]:
    """
    RAISES/CATCHES to an in-repo exception class. A builtin -- or anything that merely looks
    like an exception and is not in this source -- goes on `Symbol.raises` with no edge.
    """
    edges: list[CodeEdge] = []
    for exception in facts.exceptions:
        caller = index.symbol(facts.path, exception.caller, exception.caller_kind)
        if caller is None:
            continue
        name = exception.name.rpartition(".")[2]
        found = _lookup_dotted(index, facts, exception.name) or _lookup_name(index, facts, name)
        if found is not None and found.symbol.kind == "class":
            kind = "RAISES" if exception.kind == "raise" else "CATCHES"
            edges.append(_edge(caller, found.symbol, kind, 0.90, "resolved"))
            continue
        if exception.kind != "raise":
            continue
        if name in BUILTIN_EXCEPTIONS or name.endswith(EXCEPTION_SUFFIXES):
            if name not in caller.raises:
                caller.raises.append(name)
    return edges


# ------------------------------------------------------------- data access


def resolve_data(
    index: SourceIndex, facts: FileFacts, hits: list[tuple[str, Hit]]
) -> tuple[list[DataObject], list[CodeEdge]]:
    """
    Turn the literals and call chains of one file into data objects and READS/WRITES edges.
    `__tablename__ = "orders"` names a table without parsing anything, so it is the
    `bare_identifier` row: it links the class to the table at 0.60.

    Every hit arrives paired with the `symbol_key` of the symbol that holds it -- `collect`
    builds one, `resolve_calls` already did, and `table_names` is always a class's.
    """
    objects: list[DataObject] = []
    edges: list[CodeEdge] = []
    source_id = facts.symbols[0].source_id
    found = collect(facts.path, facts.literals) + list(hits)
    for cls, name, line in facts.table_names:
        key = symbol_key(facts.path, cls, "class")
        found.append((key, Hit("table", name, "sql", "READS", "bare_identifier", line)))
    # `mongoose.model("Order", ...)` declares the collection without touching it. No edge --
    # but the node and this mention site must exist, or S2.5 would let the collection vanish
    # the moment the file that reads it is hidden.
    for _binding, collection, line in facts.models:
        objects.append(
            DataObject(
                id=data_id(source_id, "collection", collection),
                source_id=source_id,
                name=collection,
                qualname=collection,
                kind="collection",
                dialect="mongo",
                mentions=[(facts.path, line)],
            )
        )
    for caller_key, hit in found:
        target = DataObject(
            id=data_id(source_id, hit.kind, hit.qualname),
            source_id=source_id,
            name=hit.qualname.rpartition(".")[2],
            qualname=hit.qualname,
            kind=hit.kind,
            dialect=hit.dialect,
            mentions=[(facts.path, hit.line)],
        )
        objects.append(target)
        holder = index.symbols.get(caller_key)
        if holder is None:
            continue
        omega = 0.60 if hit.provenance == "bare_identifier" else 0.85
        edges.append(_edge(holder, target, hit.access, omega, hit.provenance))
    return objects, edges


def sql_file_objects(source_id: str, path: str, text: str) -> tuple[list[DataObject], list[CodeEdge]]:
    """An in-repo `.sql` file: its tables, their columns, and CONTAINS between them."""
    objects: list[DataObject] = []
    edges: list[CodeEdge] = []
    tables: dict[str, DataObject] = {}
    for hit in read_sql_file(text):
        target = DataObject(
            id=data_id(source_id, hit.kind, hit.qualname),
            source_id=source_id,
            name=hit.qualname.rpartition(".")[2],
            qualname=hit.qualname,
            kind=hit.kind,
            dialect=hit.dialect,
            mentions=[(path, hit.line)],
        )
        objects.append(target)
        if hit.kind == "table":
            tables[hit.qualname] = target
        elif hit.kind == "column":
            owner = tables.get(hit.qualname.rpartition(".")[0])
            if owner is not None:
                edges.append(_edge(owner, target, "CONTAINS", 1.00, "syntax"))
    return objects, edges


def _data_call(index: SourceIndex, facts: FileFacts, call) -> Hit | None:
    """
    A Mongo chain (`db.orders.find`), a call on a `mongoose.model` binding, or a call on a
    variable bound earlier in the same scope to a Mongo chain (`const col =
    db.collection("orders"); col.find(...)`).
    """
    if not call.receiver:
        return None
    binding = _model_binding(index, facts, call.receiver)
    if binding:
        return mongoose_hit(binding, call.name, call.line)
    hit = mongo_hit(call.receiver, call.name, call.line)
    if hit is not None:
        return hit
    return _bound_mongo_hit(facts, call)


def _bound_mongo_hit(facts: FileFacts, call) -> Hit | None:
    """`col` in `const col = db.collection("orders"); col.updateOne(...)` -- read the
    collection off the assignment's own call chain, the same way `mongo_hit` reads it off a
    direct `db.collection("orders").updateOne(...)` chain."""
    scope = symbol_key(facts.path, call.caller, call.caller_kind)
    for assignment in facts.assignments:
        if symbol_key(facts.path, assignment.scope, assignment.scope_kind) != scope:
            continue
        if assignment.target != call.receiver:
            continue
        if assignment.line > call.line or not assignment.chain:
            continue
        hit = mongo_hit(assignment.chain, call.name, call.line)
        if hit is not None:
            return hit
    return None


def _model_binding(index: SourceIndex, facts: FileFacts, receiver: str) -> str:
    """`OrderModel` -> `Order`, whether the model was declared here or imported."""
    local = index.models.get(facts.module, {}).get(receiver)
    if local:
        return local
    for spec in facts.imports:
        if spec.alias != receiver or spec.is_wildcard:
            continue
        source = target_module(index, facts, spec)
        if source is None:
            continue
        found = index.models.get(source.module, {}).get(spec.name or receiver)
        if found:
            return found
    return ""


# --------------------------------------------------------------- tested by


def resolve_tested_by(index: SourceIndex, invokes: list[CodeEdge]) -> list[CodeEdge]:
    """
    TESTED_BY, all three provenances (the ω table): a resolved call from a test function
    (`test_import`, 0.85), a test file named after a module (`test_filename`, 0.75), and a
    test function naming a symbol it never calls (`test_mention`, 0.60).

    `by_id` is every symbol of the source because `index.symbols` is: a collision file used
    to drop its module symbol out of that index, and an INVOKES edge with an end nobody could
    name was skipped here rather than becoming the TESTED_BY it had earned (E2F-b).
    """
    edges: list[CodeEdge] = []
    by_id = {symbol.id: symbol for symbol in index.symbols.values()}
    for edge in invokes:
        caller, callee = by_id.get(edge.a), by_id.get(edge.b)
        if caller is None or callee is None or not _is_test_function(caller) or callee.is_test:
            continue
        if edge.provenance == "fuzzy_name":
            edges.append(_edge(callee, caller, "TESTED_BY", 0.60, "test_mention"))
        else:
            edges.append(_edge(callee, caller, "TESTED_BY", 0.85, "test_import"))
    edges.extend(_tested_by_filename(index))
    edges.extend(_tested_by_mention(index))
    return edges


def _is_test_function(symbol: Symbol) -> bool:
    """In a test file, and one of its cases by that language's naming convention."""
    return symbol.is_test and RULES[symbol.lang].is_test_function(symbol)


def _tested_by_filename(index: SourceIndex) -> list[CodeEdge]:
    """`tests/test_orders.py` tests the one module whose file is called `orders`."""
    by_stem: dict[tuple[str, str], list[FileFacts]] = {}
    for facts in index.files.values():
        stem = facts.module.rpartition(".")[2]
        if not index.module_symbol(facts).is_test:
            by_stem.setdefault((facts.lang, stem), []).append(facts)
    edges: list[CodeEdge] = []
    for facts in index.files.values():
        module_symbol = index.module_symbol(facts)
        if not module_symbol.is_test:
            continue
        subject = RULES[facts.lang].test_stem(facts.path)
        if subject is None:
            continue
        candidates = by_stem.get((facts.lang, subject), [])
        if len(candidates) != 1:
            continue
        edges.append(
            _edge(index.module_symbol(candidates[0]), module_symbol, "TESTED_BY", 0.75, "test_filename")
        )
    return edges


def _tested_by_mention(index: SourceIndex) -> list[CodeEdge]:
    """A bare identifier in a test function that uniquely names an in-repo symbol."""
    edges: list[CodeEdge] = []
    for facts in index.files.values():
        if not index.module_symbol(facts).is_test:
            continue
        functions = [s for s in facts.symbols if _is_test_function(s)]
        for name, lines in facts.names.items():
            found = _fuzzy(index, facts.lang, name, kinds=("class", "function", "method"))
            if found is None or found.symbol.is_test:
                continue
            for line in lines:
                holder = next((f for f in functions if f.line_start <= line <= f.line_end), None)
                if holder is not None:
                    edges.append(_edge(found.symbol, holder, "TESTED_BY", 0.60, "test_mention"))
    return edges


# ------------------------------------------------------------------ shared


def _edge(
    a: Symbol | DataObject,
    b: Symbol | DataObject,
    kind: str,
    omega: float,
    provenance: str,
    extra: dict | None = None,
) -> CodeEdge:
    return CodeEdge(a=a.id, b=b.id, kind=kind, omega=omega, provenance=provenance, extra=extra or {})
