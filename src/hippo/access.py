"""
Who may see what: roles, users and the scope they put on the graph.

hippo's memory is one graph shared by everyone, so access is decided per
*source* (a file, a pasted text, a repo). Every source names the lowest role
that may see it, and roles form a ladder ordered by `rank`:

    Arch admin (40) > Regional admin (30) > Local admin (20) > Local assistant (10) > Individual (0)

A user sees a source when their role's rank is at least the source's, or when
they own it. Passages follow their source; an entity or fact is visible when
at least one visible passage mentions or states it. That rule is applied in two
places, and both must agree:

* **In Cypher.** Every store read that returns sources, passages, entities or
  facts takes an `Access` and adds the `ACCESS_WHERE` predicate, so a query can
  never return a node the caller may not see (see store/memory.py).
* **In memory.** Search runs Personalized PageRank over an in-memory igraph,
  not over Cypher, so `scope_index` cuts the full graph down to the visible
  nodes before a search. Activation cannot flow through a node that is not in
  the graph, which is how "crawl until the nodes become restricted" is enforced.

Roles are editable (name, rank, what they may do). The five above are seeded
on first start and can be changed like any other; only their ids are fixed.

Until the first user is created hippo is *open*: everyone is treated as the
top role, as it was before there were users. Creating the first user closes it.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field, replace
from typing import Any

# ------------------------------------------------------------ capabilities
# What a role may *do* (as opposed to *see*, which is the rank). Each is a boolean on the Role.

CAPABILITIES: dict[str, str] = {
    "manage_users": "Create, edit and remove users whose role ranks below their own.",
    "manage_roles": "Add roles, rename them, move them up or down the ladder, change what they may do.",
    "add_sources": "Add files, text and repositories to the memory (visible to their own tier or below).",
    "manage_sources": "Change who may see any visible source, re-index it or delete it (owners can always do this to their own).",
    "edit_graph": "Change retrieval settings and apply changesets: edits that affect everyone's answers.",
    "run_evals": "Create question sets, generate questions and run evaluations.",
}

ALL_CAPABILITIES = frozenset(CAPABILITIES)

# The ladder the user asked for, top first. Ranks are spaced so a new role can go between two.
DEFAULT_ROLES: list[dict[str, Any]] = [
    {
        "id": "arch-admin",
        "name": "Arch admin",
        "rank": 40,
        "description": "Sees everything and can change anything, including roles and other admins.",
        "capabilities": sorted(ALL_CAPABILITIES),
    },
    {
        "id": "regional-admin",
        "name": "Regional admin",
        "rank": 30,
        "description": "Manages the users and sources of a region; tunes the graph.",
        "capabilities": ["manage_users", "add_sources", "manage_sources", "edit_graph", "run_evals"],
    },
    {
        "id": "local-admin",
        "name": "Local admin",
        "rank": 20,
        "description": "Manages a site's users and sources and checks answer quality.",
        "capabilities": ["manage_users", "add_sources", "manage_sources", "run_evals"],
    },
    {
        "id": "local-assistant",
        "name": "Local assistant",
        "rank": 10,
        "description": "Adds material and asks questions; cannot change other people's sources.",
        "capabilities": ["add_sources"],
    },
    {
        "id": "individual",
        "name": "Individual",
        "rank": 0,
        "description": "Asks questions and keeps their own notes; sees only what is open to everyone.",
        "capabilities": ["add_sources"],
    },
]

EVERYONE_RANK = 0  # a source with this min_rank (or none at all) is visible to every user


# ------------------------------------------------------------------ Access
# The small, hashable thing the store and the graph filter by.


@dataclass(frozen=True)
class Access:
    """Who is asking, reduced to what a query needs: their rank, their id, and whether they see it all."""

    rank: int = 0
    user_id: str | None = None
    unrestricted: bool = False  # open mode or the store's own internal reads

    def params(self) -> dict[str, Any]:
        """Parameters for ACCESS_WHERE. Always all three, so every query binds the same names."""
        return {"acc_all": bool(self.unrestricted), "acc_rank": int(self.rank), "acc_uid": self.user_id or ""}

    def can_see_source(self, source: dict[str, Any]) -> bool:
        """The same rule as ACCESS_WHERE, for rows already in hand (and the in-memory FakeStore)."""
        if self.unrestricted:
            return True
        if self.user_id and source.get("owner_id") == self.user_id:
            return True
        return int(source.get("min_rank") or EVERYONE_RANK) <= self.rank


EVERYTHING = Access(rank=0, user_id=None, unrestricted=True)

# The Cypher predicate, with `s` bound to a Source. Sources written before there were roles have no
# min_rank; coalesce makes them "open to everyone", which is what they were.
ACCESS_WHERE = "($acc_all OR s.owner_id = $acc_uid OR coalesce(s.min_rank, 0) <= $acc_rank)"


def access_params(access: Access | None) -> dict[str, Any]:
    return (access or EVERYTHING).params()


# --------------------------------------------------------------- Principal
# A signed-in user (or the open-mode stand-in) as the web app, MCP and CLI see them.


@dataclass(frozen=True)
class Principal:
    user: dict[str, Any] | None  # None in open mode
    role: dict[str, Any]
    access: Access = field(default_factory=Access)

    @classmethod
    def for_user(cls, user: dict[str, Any], role: dict[str, Any]) -> Principal:
        return cls(user=user, role=role, access=Access(rank=int(role.get("rank") or 0), user_id=user["id"]))

    @classmethod
    def open(cls, top_role: dict[str, Any] | None = None) -> Principal:
        """Open mode: no users exist yet, so whoever is here acts as the top role and sees everything."""
        role = dict(top_role or DEFAULT_ROLES[0])
        role["capabilities"] = sorted(ALL_CAPABILITIES)
        return cls(user=None, role=role, access=Access(rank=int(role.get("rank") or 0), unrestricted=True))

    @property
    def is_open(self) -> bool:
        return self.user is None

    @property
    def user_id(self) -> str | None:
        return self.user["id"] if self.user else None

    @property
    def name(self) -> str:
        if self.user is None:
            return "everyone (open mode)"
        return self.user.get("display_name") or self.user.get("username") or self.user["id"]

    @property
    def role_id(self) -> str:
        return self.role["id"]

    @property
    def role_name(self) -> str:
        return self.role.get("name", self.role["id"])

    @property
    def rank(self) -> int:
        return int(self.role.get("rank") or 0)

    def can(self, capability: str) -> bool:
        if capability not in CAPABILITIES:
            raise ValueError(f"unknown capability {capability!r}")
        return capability in set(self.role.get("capabilities") or [])

    def outranks(self, rank: int) -> bool:
        """Strictly above: what a user may manage (users, roles) is everything below their own rank."""
        return self.is_open or self.rank > int(rank)

    def may_assign_role(self, role: dict[str, Any]) -> bool:
        """A user may set a source's visibility to any tier up to their own: never above what they see."""
        return self.is_open or int(role.get("rank") or 0) <= self.rank

    def may_manage_source(self, source: dict[str, Any]) -> bool:
        if self.is_open:
            return True
        if self.user_id and source.get("owner_id") == self.user_id:
            return True
        return self.can("manage_sources") and self.access.can_see_source(source)

    def as_role(self, role: dict[str, Any]) -> Principal:
        """A preview principal: 'what would someone with this role (and no sources of their own) see?'"""
        return replace(self, role=dict(role), access=Access(rank=int(role.get("rank") or 0), user_id=None))


# ------------------------------------------------------------- passwords
# scrypt from the standard library: no new dependency, slow on purpose.

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    if not password or len(password) < 4:
        raise ValueError("the password must be at least 4 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not password:
        return False
    try:
        scheme, salt_hex, digest_hex = stored.split("$", 2)
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt_hex), n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def new_token() -> str:
    """A bearer token for the API and MCP. Shown to the user; they paste it into their client's config."""
    return "hippo_" + secrets.token_urlsafe(32)


# ------------------------------------------------------------ the ladder
# Helpers the Users page and the CLI use to describe the ladder in words.


def role_by_id(roles: list[dict[str, Any]], role_id: str | None) -> dict[str, Any] | None:
    for role in roles:
        if role["id"] == role_id:
            return role
    return None


def top_role(roles: list[dict[str, Any]]) -> dict[str, Any]:
    """The highest-ranked role: the first user gets it, and open mode acts as it."""
    if not roles:
        return dict(DEFAULT_ROLES[0])
    return max(roles, key=lambda r: int(r.get("rank") or 0))


def roles_at_or_below(roles: list[dict[str, Any]], rank: int) -> list[dict[str, Any]]:
    """Roles a user of `rank` may give a source (their tier and every tier below), top first."""
    return sorted((r for r in roles if int(r.get("rank") or 0) <= rank), key=lambda r: -int(r["rank"]))


def visible_source_ids(sources: list[dict[str, Any]], access: Access) -> frozenset[str]:
    return frozenset(s["id"] for s in sources if access.can_see_source(s))


__all__ = [
    "ACCESS_WHERE",
    "ALL_CAPABILITIES",
    "Access",
    "CAPABILITIES",
    "DEFAULT_ROLES",
    "EVERYONE_RANK",
    "EVERYTHING",
    "Principal",
    "access_params",
    "hash_password",
    "new_token",
    "role_by_id",
    "roles_at_or_below",
    "top_role",
    "verify_password",
    "visible_source_ids",
]
