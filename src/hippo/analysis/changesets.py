"""
Changesets: graph edits you decided on while analysing, saved first and applied later.

A changeset is a named list of small "ops" (see hippo/store/changesets.py for
the JSON shapes). This module checks them, describes them in words for the
UI, and applies them: every op goes through a store method, then the graph
version is bumped so the in-memory graph reloads with the new weights.

    save(ctx, name, ops)        -> changeset id (still a draft)
    describe(ctx, ops)          -> ["Set damping to 0.7", "Boost 'boulder' x1.5", ...]
    apply(ctx, changeset_id)    -> what changed
"""

from __future__ import annotations

from typing import Any

from ..context import AppContext
from ..hipporag.graph_index import COMMIT, DATA, SYMBOL, CodeNode
from ..hipporag.paths import display_of
from ..store.base import DEFAULT_SETTINGS

VALID_OPS = {"set_setting", "set_edge_weight", "add_synonym", "set_node_boost"}

# The exact keys each op must carry. Anything else is a typo and gets refused.
REQUIRED_KEYS: dict[str, set[str]] = {
    "set_setting": {"op", "name", "value"},
    "set_edge_weight": {"op", "a", "b", "weight"},
    "add_synonym": {"op", "a", "b", "score"},
    "set_node_boost": {"op", "entity_id", "boost"},
}


# ---------------------------------------------------------------- validate


def validate(ops: Any) -> None:
    """Raise ValueError with a clear message if `ops` is not a list of well-formed op dicts."""
    if not isinstance(ops, list):
        raise ValueError("ops must be a list")
    if not ops:
        raise ValueError("a changeset needs at least one op")
    for position, op in enumerate(ops):
        try:
            _validate_op(op)
        except ValueError as exc:
            raise ValueError(f"op {position + 1}: {exc}") from None


def _validate_op(op: Any) -> None:
    if not isinstance(op, dict):
        raise ValueError("each op must be an object")
    kind = op.get("op")
    if kind not in VALID_OPS:
        raise ValueError(f"unknown op {kind!r}; expected one of {sorted(VALID_OPS)}")
    keys = set(op)
    if keys != REQUIRED_KEYS[kind]:
        raise ValueError(f"{kind} needs exactly the keys {sorted(REQUIRED_KEYS[kind])}, got {sorted(keys)}")

    if kind == "set_setting":
        _validate_setting(op["name"], op["value"])
    elif kind == "set_edge_weight":
        _validate_pair(op["a"], op["b"])
        _validate_number(op["weight"], "weight", minimum=0.0)
    elif kind == "add_synonym":
        _validate_pair(op["a"], op["b"])
        _validate_number(op["score"], "score", minimum=0.0, maximum=1.0)
        if float(op["score"]) <= 0:
            raise ValueError("score must be above 0 (a zero-score synonym is no link at all)")
    elif kind == "set_node_boost":
        _validate_id(op["entity_id"], "entity_id")
        _validate_number(op["boost"], "boost", minimum=0.0)


def _validate_setting(name: Any, value: Any) -> None:
    if name not in DEFAULT_SETTINGS:
        raise ValueError(f"unknown setting {name!r}; expected one of {sorted(DEFAULT_SETTINGS)}")
    default = DEFAULT_SETTINGS[name]
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be true or false")
    else:
        _validate_number(value, name, minimum=0.0)


def _validate_id(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty node id")


def _validate_pair(a: Any, b: Any) -> None:
    _validate_id(a, "a")
    _validate_id(b, "b")
    if a == b:
        raise ValueError("a and b must be two different nodes")


def _validate_number(value: Any, label: str, *, minimum: float, maximum: float | None = None) -> None:
    # bool is an int in Python, so it would sneak past isinstance(value, int | float).
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{label} must be a number")
    if value < minimum or (maximum is not None and value > maximum):
        top = f" and at most {maximum}" if maximum is not None else ""
        raise ValueError(f"{label} must be at least {minimum}{top}")


# --------------------------------------------------------------- save/apply


def save(
    ctx: AppContext, name: str, ops: list[dict[str, Any]], from_result_id: str | None = None, note: str = ""
) -> str:
    """Store a validated changeset as a draft and return its id."""
    if not name or not name.strip():
        raise ValueError("a changeset needs a name")
    validate(ops)
    return ctx.store.create_changeset(name.strip(), ops, from_result_id=from_result_id, note=note or "")


def apply(ctx: AppContext, changeset_id: str) -> dict[str, Any]:
    """
    Write every op of the changeset to the store, reload the graph, and mark it applied.
    Applying twice is harmless (every op sets a value rather than adding to one).
    """
    changeset = ctx.store.get_changeset(changeset_id)
    if changeset is None:
        raise ValueError(f"no changeset with id {changeset_id!r}")
    ops = changeset["ops"]
    validate(ops)

    store = ctx.store
    changed: dict[str, Any] = {"settings": {}, "boosts": [], "edges": [], "synonyms": []}
    for op in ops:
        kind = op["op"]
        if kind == "set_setting":
            store.update_settings({op["name"]: op["value"]})
            changed["settings"][op["name"]] = op["value"]
        elif kind == "set_edge_weight":
            store.set_edge_weight(op["a"], op["b"], float(op["weight"]))
            changed["edges"].append({"a": op["a"], "b": op["b"], "weight": float(op["weight"])})
        elif kind == "add_synonym":
            store.add_synonyms([(op["a"], op["b"], float(op["score"]))], manual=True)
            changed["synonyms"].append({"a": op["a"], "b": op["b"], "score": float(op["score"])})
        elif kind == "set_node_boost":
            store.set_node_boost(op["entity_id"], float(op["boost"]))
            changed["boosts"].append({"entity_id": op["entity_id"], "boost": float(op["boost"])})

    # Settings are read fresh on every search, but boosts/edges/synonyms live in the loaded graph.
    changed["graph_version"] = store.bump_graph_version()
    ctx.invalidate_graph()
    store.mark_applied(changeset_id)
    changed["changeset_id"] = changeset_id
    changed["applied"] = len(ops)
    changed["descriptions"] = describe(ctx, ops)
    return changed


# ---------------------------------------------------------------- describe


def describe(ctx: AppContext, ops: list[dict[str, Any]]) -> list[str]:
    """One readable line per op, with node ids replaced by names where the store knows them."""
    names = _node_names(ctx, ops)
    lines = []
    for op in ops:
        kind = op.get("op")
        if kind == "set_setting":
            lines.append(f"Set {op.get('name')} to {op.get('value')}")
        elif kind == "set_node_boost":
            lines.append(f"Boost '{names(op.get('entity_id'))}' x{_num(op.get('boost'))}")
        elif kind == "add_synonym":
            lines.append(f"Link '{names(op.get('a'))}' ~ '{names(op.get('b'))}' ({_num(op.get('score'))})")
        elif kind == "set_edge_weight":
            a, b = names(op.get("a")), names(op.get("b"))
            if float(op.get("weight") or 0) == 0:
                lines.append(f"Remove the edge '{a}' - '{b}'")
            else:
                lines.append(f"Set edge '{a}' - '{b}' weight to {_num(op.get('weight'))}")
        else:
            lines.append(f"Unknown op {kind!r}")
    return lines


def _node_names(ctx: AppContext, ops: list[dict[str, Any]]):
    """
    A lookup from node id to display name, falling back to the id.

    Synonyms, tuned edges and boosts reach symbols and data objects too (WP1 widened every writer),
    so the four code readers are asked as well - otherwise the Changesets page, which is where an
    edit is read before it is applied to everyone's graph, prints a raw `symbol-<hash>`.
    """
    ids = []
    for op in ops:
        for key in ("a", "b", "entity_id"):
            value = op.get(key)
            if isinstance(value, str) and value not in ids:
                ids.append(value)
    found: dict[str, str] = {}

    def missing() -> list[str]:
        return [i for i in ids if i not in found]

    if ids:
        for row in ctx.store.get_entities(ids):
            found[row["id"]] = row["name"]
        for row in ctx.store.get_passages(missing()):
            found[row["id"]] = row["title"] or row["id"]
        for kind, read in (
            (SYMBOL, ctx.store.get_symbols),
            (DATA, ctx.store.get_data_objects),
            (COMMIT, ctx.store.get_commits),
        ):
            for row in read(missing()):
                found[row["id"]] = _code_display(kind, row) or row["id"]

    def lookup(node_id: Any) -> str:
        return found.get(node_id, str(node_id))

    return lookup


def _code_display(kind: str, row: dict[str, Any]) -> str:
    """A stored code row's display name, through the one function that owns the S2.6 grammar."""
    return display_of(
        CodeNode(
            id=row["id"],
            kind=kind,
            name=row.get("name") or "",
            qualname=row.get("qualname") or "",
            code_kind=row.get("kind") or "",
            path=row.get("path") or "",
            sha=row.get("sha") or "",
        )
    )


def _num(value: Any) -> str:
    """1.0 -> '1', 1.5 -> '1.5', 0.9 -> '0.9'."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(number)) if number.is_integer() else f"{number:g}"


__all__ = ["VALID_OPS", "validate", "save", "apply", "describe"]
