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

import posixpath
from dataclasses import dataclass, field

from .data_access import Hit, collect, mongo_hit, mongoose_hit, read_sql_file
from .model import (
    ARG_BINDING_MAX_CHARS,
    CodeEdge,
    DataObject,
    FileFacts,
    Symbol,
    data_id,
)

# Method names too common to guess from. A `fuzzy_name` edge on any of these would be
# noise at best and wrong at worst; 2.2b's "ambiguous or stoplisted -> no edge" row is
# what this list implements.
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

# Where a TypeScript relative import may land, in the order the resolver tries them.
TS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
JS_EXTENSIONS = (".js", ".jsx", ".mjs", ".cjs")

MAX_MRO_DEPTH = 5  # breadth-first, so this is five *levels* of bases, not five classes
MAX_REEXPORT_DEPTH = 5

SELF_NAMES = {"self", "cls", "this"}
SUPER_NAMES = {"super", "super()"}
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


@dataclass
class SourceIndex:
    """Everything pass 2 needs to look a name up, built once for the whole source."""

    files: dict[str, FileFacts] = field(default_factory=dict)  # path -> facts
    modules: dict[str, FileFacts] = field(default_factory=dict)  # module qualname -> facts
    symbols: dict[tuple[str, str], Symbol] = field(default_factory=dict)  # (path, qualname) -> symbol
    defines: dict[str, dict[str, Symbol]] = field(default_factory=dict)  # module -> top-level name
    members: dict[tuple[str, str], dict[str, Symbol]] = field(default_factory=dict)  # (path, class)
    by_name: dict[tuple[str, str], list[Symbol]] = field(default_factory=dict)  # (lang, name) -> symbols
    models: dict[str, dict[str, str]] = field(default_factory=dict)  # module -> binding -> collection
    bindings: dict[str, dict[str, Resolution]] = field(default_factory=dict)  # module -> alias
    bases: dict[tuple[str, str], list[Symbol]] = field(default_factory=dict)  # (path, class) -> bases
    by_suffix: dict[str, list[FileFacts]] = field(default_factory=dict)  # dotted tail -> modules

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


def build_index(files: list[FileFacts]) -> SourceIndex:
    """One pass over every parsed file, so the second pass can look anything up by name."""
    index = SourceIndex()
    for facts in files:
        index.files[facts.path] = facts
        index.modules[facts.module] = facts
        index.defines.setdefault(facts.module, {})
        for symbol in facts.symbols:
            index.symbols[(facts.path, symbol.qualname)] = symbol
            index.by_name.setdefault((symbol.lang, symbol.name), []).append(symbol)
            if symbol.kind == "module":
                continue
            owner, _, leaf = symbol.qualname.rpartition(".")
            if owner:
                index.members.setdefault((facts.path, owner), {})[leaf] = symbol
            else:
                index.defines[facts.module][symbol.qualname] = symbol
        if facts.models:
            index.models[facts.module] = {binding: name for binding, name, _ in facts.models}
        parts = (package_of(facts.module) or facts.module).split(".")
        for start in range(1, len(parts)):  # every proper dotted tail; the whole name is exact
            index.by_suffix.setdefault(".".join(parts[start:]), []).append(facts)
    return index


# ---------------------------------------------------------------- modules


def package_of(module: str) -> str:
    """`pyapp.__init__` names the package `pyapp`; every other module names only itself."""
    if module == "__init__":
        return ""
    return module.removesuffix(".__init__") if module.endswith(".__init__") else module


def resolve_module_python(index: SourceIndex, origin: str, text: str, level: int) -> FileFacts | None:
    """
    `from ..b import c` in `a/x/y.py`: walk `level` packages up, then down `text`.

    One dot means "the package this module is in", and for `pyapp/__init__.py` that package
    is `pyapp` itself, not its parent -- `from .orders import X` inside `pyapp/__init__.py`
    must reach `pyapp.orders`, which dropping a component would miss.
    """
    if not level:
        return index.module(text)
    base = package_of(origin) if origin.endswith(".__init__") else origin.rpartition(".")[0]
    for _ in range(level - 1):
        base = base.rpartition(".")[0]
    target = f"{base}.{text}" if base and text else (base or text)
    return index.module(target)


def resolve_module_ts(index: SourceIndex, origin_path: str, spec: str) -> FileFacts | None:
    """
    `./base` from `tsapp/models/order.ts`. A bare specifier (`react`, `mongoose`) is a
    dependency, not part of this source, and resolves to nothing (2.2b: no edge).
    """
    if not spec.startswith("."):
        return None
    base = posixpath.normpath(posixpath.join(posixpath.dirname(origin_path), spec))
    candidates: list[str] = []
    if base.endswith(JS_EXTENSIONS):  # `./b.js` is written for the runtime; `./b.ts` is the source
        stem = base.rsplit(".", 1)[0]
        candidates += [f"{stem}.ts", f"{stem}.tsx", base]
    elif base.endswith((".ts", ".tsx")):
        candidates.append(base)
    else:
        candidates += [f"{base}{ext}" for ext in TS_EXTENSIONS]
        candidates += [f"{base}/index{ext}" for ext in TS_EXTENSIONS]
    for candidate in candidates:
        facts = index.files.get(candidate)
        if facts is not None:
            return facts
    return None


def target_module(index: SourceIndex, facts: FileFacts, spec, ts: bool) -> FileFacts | None:
    if ts:
        return resolve_module_ts(index, facts.path, spec.module)
    return resolve_module_python(index, facts.module, spec.module, spec.level)


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
    ts = facts.lang == "typescript"
    for spec in [*facts.imports, *facts.reexports]:
        if spec.is_wildcard or spec.alias != name:
            continue
        source = target_module(index, facts, spec, ts)
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
        source = target_module(index, facts, spec, ts)
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
        module_symbol = index.module_symbol(facts)
        ts = facts.lang == "typescript"
        # `export {x} from "./b"` is an import as far as the graph is concerned: this module
        # depends on that one, and anybody importing this name goes through here.
        for spec in [*facts.imports, *facts.reexports]:
            source = target_module(index, facts, spec, ts)
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
        index.bindings[facts.module] = bindings
    return edges


# ------------------------------------------------------------------ bases


def resolve_bases(index: SourceIndex) -> list[CodeEdge]:
    """INHERITS edges, plus the base list OVERRIDES and `via_inheritance` calls walk."""
    edges: list[CodeEdge] = []
    for facts in index.files.values():
        for base in facts.bases:
            child = index.symbols.get((facts.path, base.cls))
            if child is None:
                continue
            found = _lookup_dotted(index, facts, base.base)
            if found is None or found.symbol.kind != "class":
                found = _fuzzy(index, facts.lang, base.base.rpartition(".")[2], kinds=("class",))
            if found is None:
                continue
            omega = 0.90 if found.provenance != "fuzzy_name" else 0.50
            provenance = "fuzzy_name" if found.provenance == "fuzzy_name" else "resolved"
            index.bases.setdefault((facts.path, base.cls), []).append(found.symbol)
            edges.append(_edge(child, found.symbol, "INHERITS", omega, provenance))
    return edges


def resolve_overrides(index: SourceIndex) -> list[CodeEdge]:
    """A method that shadows one on a base, found breadth-first at most `MAX_MRO_DEPTH` deep."""
    edges: list[CodeEdge] = []
    for (path, qualname), members in sorted(index.members.items()):
        owner = index.symbols.get((path, qualname))
        if owner is None or owner.kind != "class":
            continue
        for name, method in members.items():
            if method.kind != "method":
                continue
            inherited = _mro_lookup(index, path, qualname, name)
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
    """
    edges: list[CodeEdge] = []
    hits: list[tuple[str, Hit]] = []
    raised = {(exc.caller, exc.line, exc.name.rpartition(".")[2]) for exc in facts.exceptions}
    unresolved = 0
    for call in facts.calls:
        caller = index.symbols.get((facts.path, call.caller))
        if caller is None:
            continue
        if (call.caller, call.line, call.name) in raised:
            continue  # `raise OrderError(...)` is a RAISES edge, not also a call to the class
        if not call.receiver and call.name in LANGUAGE_CALLS:
            continue  # `super()` is the language's own machinery, not a reference to resolve
        hit = _data_call(index, facts, call)
        if hit is not None:
            hits.append((call.caller, hit))
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
    owner = call.caller.rpartition(".")[0]
    if not receiver:
        return _lookup_name(index, facts, name)
    if receiver in SELF_NAMES:
        return _on_class(index, facts, owner, name)
    if receiver in SUPER_NAMES or receiver.rstrip("()") == "super":
        inherited = _mro_lookup(index, facts.path, owner, name)
        return Resolution(inherited, 0.90, "via_inheritance") if inherited is not None else None
    holder = _receiver_type(index, facts, call, receiver)
    if holder is not None:
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
    if found is not None and (found.is_module or found.symbol.kind == "class"):
        return found
    for assignment in facts.assignments:
        if assignment.scope != call.caller or assignment.target != receiver:
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
    """`name` on a class: its own member first (1.00), then its bases (0.90)."""
    if not qualname:
        return None
    path = path or facts.path
    found = index.members.get((path, qualname), {}).get(name)
    if found is not None:
        omega, provenance = (1.00, "same_file") if path == facts.path else (0.90, "via_import")
        return Resolution(found, omega, provenance)
    inherited = _mro_lookup(index, path, qualname, name)
    return Resolution(inherited, 0.90, "via_inheritance") if inherited is not None else None


def _through(facts: FileFacts, found: Resolution) -> Resolution:
    """A member reached through another module is `via_import`; in this file it is `same_file`."""
    if found.symbol.path == facts.path:
        return Resolution(found.symbol, 1.00, "same_file", found.is_module)
    return Resolution(found.symbol, 0.90, "via_import", found.is_module)


def _lookup_name(index: SourceIndex, facts: FileFacts, name: str) -> Resolution | None:
    """A bare name in one file: its import bindings, then its own top-level definitions."""
    if not name:
        return None
    found = index.bindings.get(facts.module, {}).get(name)
    if found is None:
        return None
    if found.provenance == "same_file":
        return found
    # Any import-resolved call is 0.90 `via_import`: the ω table gives INVOKES exactly three
    # tiers, and a wildcard import's own uncertainty is already on its 0.60 IMPORTS edge.
    return Resolution(found.symbol, 0.90, "via_import", found.is_module)


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
    """
    if not name or name in FUZZY_STOPLIST:
        return None
    candidates = [s for s in index.by_name.get((lang, name), []) if s.kind in kinds]
    if len(candidates) != 1:
        return None
    return Resolution(candidates[0], 0.50, "fuzzy_name")


def _arg_binding(callee: Symbol, call) -> dict[str, str]:
    """Callee parameter names bound to the caller's argument expressions, cut at 60 chars."""
    params = list(callee.params)
    if call.receiver and params and params[0] in SELF_NAMES:
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
        caller = index.symbols.get((facts.path, exception.caller))
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
    """
    objects: list[DataObject] = []
    edges: list[CodeEdge] = []
    source_id = facts.symbols[0].source_id
    found = collect(facts.literals) + list(hits)
    for cls, name, line in facts.table_names:
        found.append((cls, Hit("table", name, "sql", "READS", "bare_identifier", line)))
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
    for caller, hit in found:
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
        holder = index.symbols.get((facts.path, caller))
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
    """A Mongo chain (`db.orders.find`) or a call on a `mongoose.model` binding."""
    if not call.receiver:
        return None
    binding = _model_binding(index, facts, call.receiver)
    if binding:
        return mongoose_hit(binding, call.name, call.line)
    return mongo_hit(call.receiver, call.name, call.line)


def _model_binding(index: SourceIndex, facts: FileFacts, receiver: str) -> str:
    """`OrderModel` -> `Order`, whether the model was declared here or imported."""
    local = index.models.get(facts.module, {}).get(receiver)
    if local:
        return local
    ts = facts.lang == "typescript"
    for spec in facts.imports:
        if spec.alias != receiver or spec.is_wildcard:
            continue
        source = target_module(index, facts, spec, ts)
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
    return symbol.is_test and symbol.kind in ("function", "method") and symbol.name.startswith("test")


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
        stem = facts.module.rpartition(".")[2]
        subject = stem.removeprefix("test_").removesuffix("_test").removesuffix(".test").removesuffix(".spec")
        if subject == stem:
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
