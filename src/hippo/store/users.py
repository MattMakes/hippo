"""
Queries for roles, users and who may see which source.

    (User {id, username, display_name, password_hash, token, role_id, disabled, created_at})-[:HAS_ROLE]->(Role)
    (Role {id, name, rank, description, capabilities: [..], builtin})
    (Source {access_role_id, min_rank, owner_id})   min_rank is copied from the role's rank so that
                                                    the ACCESS_WHERE predicate is one comparison

The rank on a Source is a copy: when a role moves up or down the ladder,
`update_role` rewrites min_rank on every source that names it, so sources
follow their role and the predicate stays a single integer compare.
"""

from __future__ import annotations

import re
from typing import Any

from ..access import ALL_CAPABILITIES, DEFAULT_ROLES, EVERYONE_RANK, hash_password, new_token, verify_password
from .base import Neo4jBase, new_id, now_iso, with_defaults

ROLE_DEFAULTS: dict[str, Any] = {
    "description": "",
    "rank": EVERYONE_RANK,
    "capabilities": [],
    "builtin": False,
}
USER_DEFAULTS: dict[str, Any] = {"display_name": "", "disabled": False, "created_at": "", "role_id": None}


def slug(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return text or "role"


def clean_capabilities(capabilities: Any) -> list[str]:
    """Only known capability names, sorted; anything else is a loud error (a typo would silently grant nothing)."""
    names = [str(c) for c in (capabilities or [])]
    unknown = set(names) - ALL_CAPABILITIES
    if unknown:
        raise ValueError(f"unknown capabilities: {sorted(unknown)}")
    return sorted(set(names))


def clean_rank(rank: Any) -> int:
    try:
        value = int(rank)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"rank must be a whole number, got {rank!r}") from exc
    if value < 0 or value > 1000:
        raise ValueError("rank must be between 0 and 1000")
    return value


def clean_username(username: str) -> str:
    name = (username or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,63}", name):
        raise ValueError("a username is 2-64 characters: letters, digits, dots, dashes or underscores")
    return name


class UserQueries(Neo4jBase):
    # ================================================================ roles

    def ensure_roles(self) -> None:
        """Seed the default ladder. Existing roles are left exactly as the user edited them."""
        self.run(
            """
            UNWIND $roles AS role
            MERGE (r:Role {id: role.id})
            ON CREATE SET r.name = role.name, r.rank = role.rank, r.description = role.description,
                          r.capabilities = role.capabilities, r.builtin = true
            """,
            roles=DEFAULT_ROLES,
        )

    def list_roles(self) -> list[dict[str, Any]]:
        """Every role, top of the ladder first, with how many users and sources sit at it."""
        rows = self.run(
            """
            MATCH (r:Role)
            RETURN r AS r, count { (:User)-[:HAS_ROLE]->(r) } AS users,
                   count { (s:Source) WHERE s.access_role_id = r.id } AS sources
            ORDER BY r.rank DESC, r.name
            """
        )
        return [_role_row(row) for row in rows]

    def get_role(self, role_id: str | None) -> dict[str, Any] | None:
        if not role_id:
            return None
        row = self.run_one(
            """
            MATCH (r:Role {id: $id})
            RETURN r AS r, count { (:User)-[:HAS_ROLE]->(r) } AS users,
                   count { (s:Source) WHERE s.access_role_id = r.id } AS sources
            """,
            id=role_id,
        )
        return _role_row(row) if row else None

    def create_role(
        self, name: str, rank: int, description: str = "", capabilities: list[str] | None = None
    ) -> str:
        name = (name or "").strip()
        if not name:
            raise ValueError("the role needs a name")
        role_id = slug(name)
        if self.get_role(role_id) is not None:
            role_id = f"{role_id}-{new_id()[:4]}"
        self.run(
            """
            CREATE (r:Role {id: $id, name: $name, rank: $rank, description: $description,
                            capabilities: $capabilities, builtin: false})
            """,
            id=role_id,
            name=name,
            rank=clean_rank(rank),
            description=(description or "").strip(),
            capabilities=clean_capabilities(capabilities),
        )
        return role_id

    def update_role(self, role_id: str, **fields: Any) -> dict[str, Any]:
        """Edit name/rank/description/capabilities. A rank change is copied onto the role's sources."""
        allowed = {"name", "rank", "description", "capabilities"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown role fields: {sorted(bad)}")
        if self.get_role(role_id) is None:
            raise ValueError("no such role")
        changes: dict[str, Any] = {}
        if "name" in fields:
            changes["name"] = str(fields["name"]).strip()
            if not changes["name"]:
                raise ValueError("the role needs a name")
        if "rank" in fields:
            changes["rank"] = clean_rank(fields["rank"])
        if "description" in fields:
            changes["description"] = str(fields["description"] or "").strip()
        if "capabilities" in fields:
            changes["capabilities"] = clean_capabilities(fields["capabilities"])
        if changes:
            self.run("MATCH (r:Role {id: $id}) SET r += $changes", id=role_id, changes=changes)
        if "rank" in changes:
            self.run(
                "MATCH (s:Source {access_role_id: $id}) SET s.min_rank = $rank",
                id=role_id,
                rank=changes["rank"],
            )
        return self.get_role(role_id)  # type: ignore[return-value]

    def delete_role(self, role_id: str) -> None:
        """Remove a role nobody uses. Refused while a user or a source still names it."""
        role = self.get_role(role_id)
        if role is None:
            raise ValueError("no such role")
        if role["users"] or role["sources"]:
            raise ValueError(
                f"'{role['name']}' is still used by {role['users']} user(s) and {role['sources']} source(s); "
                "move them to another role first"
            )
        if len(self.list_roles()) <= 1:
            raise ValueError("cannot delete the last role")
        self.run("MATCH (r:Role {id: $id}) DETACH DELETE r", id=role_id)

    # ================================================================ users

    def count_users(self) -> int:
        row = self.run_one("MATCH (u:User) RETURN count(u) AS n")
        return int(row["n"]) if row else 0

    def list_users(self) -> list[dict[str, Any]]:
        rows = self.run(
            """
            MATCH (u:User)
            OPTIONAL MATCH (u)-[:HAS_ROLE]->(r:Role)
            RETURN u AS u, r.name AS role_name, coalesce(r.rank, 0) AS rank,
                   count { (s:Source) WHERE s.owner_id = u.id } AS sources
            ORDER BY coalesce(r.rank, 0) DESC, u.username
            """
        )
        return [_user_row(row) for row in rows]

    def get_user(self, user_id: str | None) -> dict[str, Any] | None:
        if not user_id:
            return None
        return self._one_user("MATCH (u:User {id: $value})", user_id)

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        return self._one_user("MATCH (u:User {username: $value})", (username or "").strip().lower())

    def get_user_by_token(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        return self._one_user("MATCH (u:User {token: $value})", token)

    def _one_user(self, match: str, value: str) -> dict[str, Any] | None:
        row = self.run_one(
            match
            + """
            OPTIONAL MATCH (u)-[:HAS_ROLE]->(r:Role)
            RETURN u AS u, r.name AS role_name, coalesce(r.rank, 0) AS rank,
                   count { (s:Source) WHERE s.owner_id = u.id } AS sources
            """,
            value=value,
        )
        return _user_row(row) if row else None

    def create_user(self, username: str, password: str, role_id: str, display_name: str = "") -> str:
        username = clean_username(username)
        if self.get_user_by_username(username) is not None:
            raise ValueError(f"the username '{username}' is taken")
        if self.get_role(role_id) is None:
            raise ValueError("no such role")
        user_id = new_id()
        self.run(
            """
            MATCH (r:Role {id: $role_id})
            CREATE (u:User {id: $id, username: $username, display_name: $display_name,
                            password_hash: $password_hash, token: $token, role_id: $role_id,
                            disabled: false, created_at: $now})
            CREATE (u)-[:HAS_ROLE]->(r)
            """,
            id=user_id,
            username=username,
            display_name=(display_name or "").strip(),
            password_hash=hash_password(password),
            token=new_token(),
            role_id=role_id,
            now=now_iso(),
        )
        return user_id

    def update_user(self, user_id: str, **fields: Any) -> dict[str, Any]:
        """Edit display_name, role_id, disabled or password. Unknown keys are refused."""
        allowed = {"display_name", "role_id", "disabled", "password"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown user fields: {sorted(bad)}")
        if self.get_user(user_id) is None:
            raise ValueError("no such user")
        changes: dict[str, Any] = {}
        if "display_name" in fields:
            changes["display_name"] = str(fields["display_name"] or "").strip()
        if "disabled" in fields:
            changes["disabled"] = bool(fields["disabled"])
        if "password" in fields:
            changes["password_hash"] = hash_password(str(fields["password"]))
        if "role_id" in fields:
            if self.get_role(fields["role_id"]) is None:
                raise ValueError("no such role")
            changes["role_id"] = fields["role_id"]
            self.run(
                """
                MATCH (u:User {id: $id})
                OPTIONAL MATCH (u)-[old:HAS_ROLE]->() DELETE old
                WITH u MATCH (r:Role {id: $role_id}) MERGE (u)-[:HAS_ROLE]->(r)
                """,
                id=user_id,
                role_id=fields["role_id"],
            )
        if changes:
            self.run("MATCH (u:User {id: $id}) SET u += $changes", id=user_id, changes=changes)
        return self.get_user(user_id)  # type: ignore[return-value]

    def rotate_token(self, user_id: str) -> str:
        token = new_token()
        self.run("MATCH (u:User {id: $id}) SET u.token = $token", id=user_id, token=token)
        return token

    def delete_user(self, user_id: str) -> None:
        """Remove a user. Their sources stay, ownerless (visible by their tier alone)."""
        self.run("MATCH (s:Source {owner_id: $id}) REMOVE s.owner_id", id=user_id)
        self.run("MATCH (u:User {id: $id}) DETACH DELETE u", id=user_id)

    def check_password(self, username: str, password: str) -> dict[str, Any] | None:
        """The user row when the username/password pair is right and the user is not disabled, else None."""
        user = self.get_user_by_username(username)
        if user is None or user.get("disabled"):
            return None
        return user if verify_password(password, user.get("password_hash")) else None

    # ======================================================= source access

    def set_source_access(self, source_id: str, role_id: str | None, owner_id: str | None = ...) -> None:
        """
        Who may see a source: the lowest role (None = everyone) and, optionally, a new owner.
        Pass owner_id to change it (None removes it); leave it out to keep the current owner.
        """
        if role_id:
            role = self.get_role(role_id)
            if role is None:
                raise ValueError("no such role")
            min_rank = int(role["rank"])
        else:
            min_rank = EVERYONE_RANK
        changes: dict[str, Any] = {"access_role_id": role_id, "min_rank": min_rank, "updated_at": now_iso()}
        if owner_id is not ...:
            changes["owner_id"] = owner_id
        self.run("MATCH (s:Source {id: $id}) SET s += $changes", id=source_id, changes=changes)


# ------------------------------------------------------------- row shaping


def _role_row(row: dict[str, Any]) -> dict[str, Any]:
    role = with_defaults(dict(row["r"]), ROLE_DEFAULTS)
    role["rank"] = int(role.get("rank") or 0)
    role["capabilities"] = sorted(role.get("capabilities") or [])
    role["users"] = int(row.get("users", 0))
    role["sources"] = int(row.get("sources", 0))
    return role


def _user_row(row: dict[str, Any]) -> dict[str, Any]:
    user = with_defaults(dict(row["u"]), USER_DEFAULTS)
    user["role_name"] = row.get("role_name") or user.get("role_id") or ""
    user["rank"] = int(row.get("rank") or 0)
    user["sources"] = int(row.get("sources", 0))
    return user
