"""
Talking to a running `hippo serve` over its JSON API.

The embedded LadybugDB file belongs to one process at a time. When a CLI command
finds the file already open, that process is almost always the web server, so
the CLI asks the server instead of giving up. `hippo mcp` over stdio has no such
fallback (point MCP clients at http://localhost:8000/mcp while the server runs;
see docs/MCP.md).

Once users exist the server wants a token: the CLI sends the HIPPO_TOKEN
environment variable as `Authorization: Bearer`, the same variable stdio MCP
uses. Without it, a 401 is turned into a message that says where to get one.

A refusal is printed, so what this client raises has to be fit to print. When the
server sends a public failure (`code` plus `error`, the shape every JSON route
uses) the error carries exactly that code and that bounded sentence, so the same
condition reads the same whether the caller reached hippo through the CLI, the API
or MCP.

Without a `code`, only one thing travels: a `detail` on a **4xx**, which is
FastAPI's own shape for a legacy validator and for a lookup that found nothing.
Its text is the caller's own input said back to them - the symbol they named, the
argument they left out - and it is the single actionable fact in the response, so
dropping it would make `hippo blast no_such_thing` read differently behind a
server than it does in this process. A code-less `error` never travels, whatever
the status: that is the shape of a route the activation has not reached yet, and
its content is an exception string, which by construction can hold a model's reply
body, an absolute path or a sentence of a stored source. Neither does an
unparseable body. Both become the same closed `operation_failed` sentence, with
the HTTP status, which is the one detail a user can quote when asking for help.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from .config import Config

TOKEN_ENV = "HIPPO_TOKEN"
PROBE_SECONDS = 3.0  # "is a hippo listening there?" must answer fast or not at all
# A 409 that carries `candidates` but names none of them: the list is still the answer, so
# it needs a line to sit under. `/api/code` always sends `detail` today, so this is latent.
AMBIGUOUS = "that name could mean several things"


def _body(response: httpx.Response) -> dict[str, Any]:
    """The response's JSON object, or `{}` for anything else. Never the raw text."""
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


class RemoteError(RuntimeError):
    """The server refused or could not do what was asked; the message is fit to print."""


class RemoteAmbiguous(RemoteError):
    """
    A name the caller gave means several things in the code graph (the server's 409).

    Its message and `candidates` are exactly what `hipporag.paths.AmbiguousSymbol` carries, so the
    CLI prints the same thing whether it answered from this process or from a running server. The
    name is not resolvable here - only the server has the graph - which is why the candidates have
    to travel in the response body.
    """

    def __init__(self, message: str, candidates: list[str]):
        super().__init__(message)
        self.candidates = candidates


class RemoteHippo:
    """A thin client for /api on a running hippo."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 600.0,
        client: httpx.Client | None = None,
        token: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        # `client` lets tests hand in Starlette's TestClient (an httpx.Client aimed at the app in-process).
        self._client = client or httpx.Client(base_url=self.base_url, timeout=timeout)
        # A client we were given owns its own transport settings, so the liveness probe below
        # bounds only the one we built. Starlette's TestClient refuses a per-request `timeout`
        # outright, and overriding a caller's deadline would be presumptuous in any case.
        self._probe_timeout = None if client is not None else PROBE_SECONDS
        token = token if token is not None else os.environ.get(TOKEN_ENV, "")
        if token:
            self._client.headers["Authorization"] = f"Bearer {token}"

    @classmethod
    def for_config(cls, config: Config) -> RemoteHippo:
        # The server binds HIPPO_HOST; 0.0.0.0 means "every interface", which we reach through loopback.
        host = "127.0.0.1" if config.host in ("0.0.0.0", "::", "") else config.host
        return cls(f"http://{host}:{config.port}", timeout=config.llm_timeout_seconds)

    def is_up(self) -> bool:
        """Does a hippo answer there? A 401 counts: the server is up, it just wants a token (see _json)."""
        bound = {} if self._probe_timeout is None else {"timeout": self._probe_timeout}
        try:
            return self._client.get("/api/status", **bound).status_code in (200, 401)
        except httpx.HTTPError:
            return False

    def _json(self, response: httpx.Response) -> Any:
        if response.status_code == 401:
            raise RemoteError(
                f"the server at {self.base_url} has users now and wants to know who you are: set {TOKEN_ENV} "
                "to your token (Account page, /account) and run the command again"
            )
        if response.status_code >= 400:
            body = _body(response)
            # A 409 from /api/code carries what the name could have meant; that list is the whole
            # point of the status code, so it is raised as itself rather than flattened into text.
            candidates = body.get("candidates")
            if candidates:
                raise RemoteAmbiguous(
                    str(body.get("detail") or body.get("error") or AMBIGUOUS), list(candidates)
                )
            raise RemoteError(self._refusal(response, body))
        return response.json()

    def _refusal(self, response: httpx.Response, body: dict[str, Any]) -> str:
        """What the caller may be told about a refusal, in order of how much the server said.

        A `code` means the server classified this itself, and that classification is the
        whole message: the same two strings a ToolError and the local CLI would print, with
        no URL and no status, because the condition is the answer and the plumbing is not.

        Without one, a `detail` on a 4xx is a legacy validator or a lookup that found
        nothing, and its bounded text is the caller's own input. Anything else - a
        code-less `error`, a 5xx, a body this client could not parse - is an exception
        string that was never meant for a client, and only the closed sentence and the
        status go out. See this module's docstring for why that asymmetry is the rule.
        """
        # Imported per call, not at module scope: `cli.py` imports this module eagerly, and
        # `public_errors` reaches the whole ingest stack. `hippo ask` should not pay for it.
        from .knowledge.public_errors import OPERATION_FAILED

        code, message = body.get("code"), body.get("error")
        if type(code) is str and type(message) is str:
            return f"{code}: {message}"
        detail = body.get("detail")
        if response.status_code < 500 and type(detail) is str and detail:
            return detail
        return f"{OPERATION_FAILED.code}: {OPERATION_FAILED.message} (HTTP {response.status_code})"

    def ask(self, question: str) -> dict[str, Any]:
        return self._json(self._client.post("/api/ask", json={"question": question}))

    def sources(self) -> list[dict[str, Any]]:
        return self._json(self._client.get("/api/sources"))

    def source(self, source_id: str) -> dict[str, Any]:
        return self._json(self._client.get(f"/api/sources/{source_id}"))

    def settings(self) -> dict[str, Any]:
        return self._json(self._client.get("/api/settings"))

    def add_upload(self, filename: str, data: bytes) -> str:
        response = self._client.post("/api/sources/upload", files={"file": (filename, data)})
        return self._json(response)["source_id"]

    def add_repo(self, url: str) -> str:
        return self._json(self._client.post("/api/sources/repo", json={"url": url}))["source_id"]

    # ---- the code graph (see web/routes/code.py for the shapes; these are the same dicts)

    def code_path(self, a: str, b: str) -> dict[str, Any]:
        return self._json(self._client.get("/api/code/path", params={"a": a, "b": b}))

    def code_blast_radius(self, symbol: str, depth: int) -> dict[str, Any]:
        return self._json(
            self._client.get("/api/code/blast-radius", params={"symbol": symbol, "depth": depth})
        )

    def code_exception_path(self, symbol: str, exception: str) -> dict[str, Any]:
        return self._json(
            self._client.get("/api/code/exception-path", params={"symbol": symbol, "exception": exception})
        )

    def code_history(self, symbol: str, limit: int) -> dict[str, Any]:
        return self._json(self._client.get("/api/code/history", params={"symbol": symbol, "limit": limit}))

    # ---- users and roles (see web/routes/users.py for who may do what)

    def roles(self) -> list[dict[str, Any]]:
        return self._json(self._client.get("/api/roles"))

    def users(self) -> list[dict[str, Any]]:
        return self._json(self._client.get("/api/users"))

    def user_by_username(self, username: str) -> dict[str, Any] | None:
        name = (username or "").strip().lower()
        return next((u for u in self.users() if u.get("username") == name), None)

    def create_user(
        self, username: str, password: str, role_id: str, display_name: str = ""
    ) -> dict[str, Any]:
        """The server's reply: {user, signed_in, token}. `role_id` may be "" for the server's default."""
        body = {"username": username, "password": password, "role_id": role_id, "display_name": display_name}
        return self._json(self._client.post("/api/users", json=body))

    def set_user_role(self, user_id: str, role_id: str) -> dict[str, Any]:
        return self._json(self._client.patch(f"/api/users/{user_id}", json={"role_id": role_id}))

    def rotate_token(self, user_id: str) -> str:
        return self._json(self._client.post(f"/api/users/{user_id}/token"))["token"]

    def delete_user(self, user_id: str) -> None:
        self._json(self._client.delete(f"/api/users/{user_id}"))

    def wait_for_source(self, source_id: str, timeout: float, poll: float = 2.0) -> dict[str, Any]:
        """Poll until the source is no longer queued/reading/indexing (or the timeout passes)."""
        deadline = time.time() + timeout
        while True:
            source = self.source(source_id)
            if source.get("status") not in ("queued", "reading", "indexing") or time.time() >= deadline:
                return source
            time.sleep(poll)

    def close(self) -> None:
        self._client.close()
