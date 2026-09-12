"""
The `hippo` command line.

    hippo serve                 start the web app (and the MCP server at /mcp)
    hippo mcp                   run the MCP server over stdio, for clients that spawn it
    hippo pull-models           download the Ollama models hippo needs, showing progress
    hippo index <path-or-url>   remember a file, a folder, or a public git repo, and wait for it
    hippo ask "<question>"      ask the memory a question
    hippo path A B              how one symbol reaches another in an indexed repository
    hippo blast SYMBOL          who would feel a change to it, level by level
    hippo raises SYMBOL EXC     how a function reaches an exception class
    hippo history SYMBOL        the commits that touched a symbol, newest first
    hippo sources               list what is in the memory
    hippo settings              show the retrieval settings and where things are
    hippo users                 list users and roles (the access ladder)
    hippo user add <name>       create a user (prompts for a password; --role picks the tier)
    hippo user token <name>     print a user's API/MCP token (or --new to issue another)
    hippo user role <name> <r>  move a user to another role
    hippo user remove <name>    delete a user

Who the CLI is. Administration is not gated by users: creating the first admin
from `docker exec` is exactly what it is for (see hippo/access.py). Everything
that reads or writes *evidence* is, and by the same rule the MCP server uses:
once users exist, HIPPO_TOKEN names the reader, and `index`, `ask`, `sources`
and the four code commands act as them - building as their `BuildActor.reader`,
and seeing the slice of the memory they may see. A missing or unknown token
refuses before anything is created. While no user exists the memory is open, so
those commands use the open audience, which reads legacy evidence unrestricted
but proves no managed generation. `hippo mcp` identifies its caller the same
way, over stdio.

Every command builds its `AppContext` from environment variables (see
config.py and .env.example), exactly like the web app does, so the CLI and the
UI always see the same memory.

The embedded database file can be open in one process at a time. When `hippo
serve` has it, `index`, `ask`, `sources` and `settings` talk to that server over
its JSON API instead (remote.py), so they work either way.
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .config import load_config
from .context import AppContext
from .remote import TOKEN_ENV, RemoteAmbiguous, RemoteError, RemoteHippo
from .store import StoreLockedError

WAIT_SECONDS = 3600.0  # a big repo on a slow CPU model really can take an hour

# Commands that read or write evidence. They resolve a principal, and a failure inside
# one is answered with the closed public code rather than whatever was raised - see
# `_public_failure`. The rest are administration and keep their own messages.
EVIDENCE_COMMANDS = frozenset({"index", "ask", "sources", "path", "blast", "raises", "history"})

NO_TOKEN = (
    f"this hippo has users, so it needs to know who you are: set {TOKEN_ENV} to your token "
    "(Account page, /account) and run the command again"
)
STORE_DOWN = "hippo cannot reach its database, so nobody can be signed in right now"
# The same two strings `mcp_server.DENIED` and `mcp_server.DENIED_CODE` hold, and the same
# two the web app answers 409 with: one permission change, one wording, whichever surface
# the caller reached hippo through. `public_errors` maps an authorization change to no
# *public* code (it keeps the response it already had rather than becoming a fifth one),
# but the managed lane has its own stable name for the event and this is it.
DENIED = "Permissions changed; repeat the query"
DENIED_CODE = "authorization_changed"

# What a failed Source row may be printed as when its stored `error` is not already a
# rendering. The row is not re-derivable from an exception hours later, so the id is all
# a reader gets; the local log holds the rest.
INDEXING_FAILED = "indexing failed; inspect local logs for source {source_id}"


class Denied(RuntimeError):
    """This command may not run as whoever is holding the terminal. The message is fit to print."""


# ------------------------------------------------------------ arguments


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hippo", description="A portable HippoRAG memory.")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="start the web app and the MCP endpoint")
    serve.add_argument(
        "--host",
        default=None,
        help="bind address (default: HIPPO_HOST or 127.0.0.1; open it up only with users created and a proxy in front)",
    )
    serve.add_argument("--port", type=int, default=None, help="port (default: HIPPO_PORT or 8000)")

    sub.add_parser("mcp", help="run the MCP server over stdio")
    sub.add_parser("pull-models", help="download the Ollama models hippo needs")

    index = sub.add_parser("index", help="remember a file, folder, or git URL and wait for indexing")
    index.add_argument("target", help="a file path, a folder path, or a public git URL")
    index.add_argument("--name", default=None, help="what to call this source in the library")

    ask = sub.add_parser("ask", help="ask the memory a question")
    ask.add_argument("question")

    # The code graph. A name may be fully qualified (pkg.module.Class.method), module-relative
    # (Class.method) or bare when only one symbol answers to it; the defaults repeat
    # web/routes/code.py's so that argparse stays free of a web import.
    path = sub.add_parser("path", help="how one symbol reaches another")
    path.add_argument("a", help="the symbol the route starts at")
    path.add_argument("b", help="the symbol it should reach")
    blast = sub.add_parser("blast", help="what a change to a symbol could break")
    blast.add_argument("symbol")
    blast.add_argument("--depth", type=int, default=2, help="levels of callers to walk (1-4, default 2)")
    raises = sub.add_parser("raises", help="how a function reaches an exception class")
    raises.add_argument("symbol")
    raises.add_argument("exception", help="the exception class, e.g. OrderError")
    history = sub.add_parser("history", help="the commits that touched a symbol")
    history.add_argument("symbol")
    history.add_argument("--limit", type=int, default=3, help="how many commits to show (default 3)")

    sub.add_parser("sources", help="list the sources in the memory")
    sub.add_parser("settings", help="show the retrieval settings")
    sub.add_parser("users", help="list users and roles")

    user = sub.add_parser("user", help="manage one user: add, token, role, remove")
    user_sub = user.add_subparsers(dest="user_command", required=True)
    add = user_sub.add_parser("add", help="create a user")
    add.add_argument("username")
    add.add_argument("--role", default=None, help="role id (default: the top role; see `hippo users`)")
    add.add_argument("--password", default=None, help="password (prompted for when omitted)")
    add.add_argument("--name", default="", help="display name")
    token = user_sub.add_parser("token", help="print a user's token")
    token.add_argument("username")
    token.add_argument("--new", action="store_true", help="issue a new token (the old one stops working)")
    role = user_sub.add_parser("role", help="move a user to another role")
    role.add_argument("username")
    role.add_argument("role_id")
    remove = user_sub.add_parser("remove", help="delete a user (their sources stay, without an owner)")
    remove.add_argument("username")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # stdio MCP owns stdout, so all logging goes to stderr for every command (simplest rule).
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per Ollama/API call is noise here
    handlers = {
        "serve": cmd_serve,
        "mcp": cmd_mcp,
        "pull-models": cmd_pull_models,
        "index": cmd_index,
        "ask": cmd_ask,
        "path": cmd_path,
        "blast": cmd_blast,
        "raises": cmd_raises,
        "history": cmd_history,
        "sources": cmd_sources,
        "settings": cmd_settings,
        "users": cmd_users,
        "user": cmd_user,
    }
    try:
        return handlers[args.command](args)
    except CodeNameError as exc:
        # A name hippo cannot act on: unknown, blank, or meaning several things. When it means
        # several, listing them is the whole answer, so they go out under the message.
        print(f"error: {exc}", file=sys.stderr)
        for candidate in exc.candidates:
            print(f"  {candidate}", file=sys.stderr)
        return 2
    except (StoreLockedError, RemoteError, Denied) as exc:
        # The embedded database belongs to one process at a time; usually `hippo serve` has it, and then
        # the command went to the server instead, which may have refused (no token, no permission).
        # A remote refusal already carries the server's own stable code (remote.py).
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        # KeyboardInterrupt and SystemExit are not Exceptions and so pass straight
        # through: Ctrl-C is the operator stopping the command, not hippo failing at it.
        message = _refusal(exc, command=args.command)
        if message is None:
            raise
        print(f"error: {message}", file=sys.stderr)
        return 2


def _refusal(exc: Exception, *, command: str) -> str | None:
    """What this failure may be printed as, or `None` to let the exception through.

    Same table as the HTTP routes and the MCP tools, so one condition reads the same
    everywhere. An evidence command adds `or OPERATION_FAILED`, which is the caller rule
    `knowledge/public_errors.py` documents: a pure mapper cannot tell where an exception
    was raised, so the path that could have touched stored text says so itself. An
    administrative command touches no managed evidence and keeps its own errors -- with
    one deliberate exception, below.

    The two modules order the same table differently: `mcp_server.tool_failure` asks
    `public_failure` first, this asks about a permission change first. They agree only
    because `AuthorizationChanged` is a bare `RuntimeError` and appears in no row of the
    public table; if it ever gains one, these two have to be re-read together.
    """
    from .knowledge.access import AuthorizationChanged
    from .knowledge.public_errors import OPERATION_FAILED, public_failure

    if isinstance(exc, AuthorizationChanged):
        # Mapped for *every* command, administrative ones included, and deliberately so:
        # a permission change is the one condition that is about the caller rather than
        # about the work, and no command should answer it with a traceback. Nothing
        # administrative raises it today; `cmd_settings` growing a capability check is
        # exactly the case this ordering is here for.
        return f"{DENIED_CODE}: {DENIED}"
    if command not in EVIDENCE_COMMANDS:
        return None
    failure = public_failure(exc)
    if failure is not None:
        return f"{failure.code}: {failure.message}"
    # Closed input validation the caller can act on, raised before any managed work and
    # never interpolating stored text: the same exact-type rule, for the same reason, as
    # `mcp_server.tool_failure`. Every managed exception is a *subclass* of ValueError
    # (ReadError, ManagedDispatchError, ProjectionError), so `isinstance` would let those
    # out as `str(exc)`; the two surfaces have to agree on this or the same upload limit
    # reads as its own sentence over MCP and as `operation_failed` here.
    if type(exc) is ValueError:
        return str(exc)
    return f"{OPERATION_FAILED.code}: {OPERATION_FAILED.message}"


def _principal(ctx: AppContext):
    """Who is running this command: the HIPPO_TOKEN reader, or the open audience.

    `principal_from_bearer` is the same resolver the stdio MCP server uses, so a token
    that works for one works for the other. `require_online=True` matters: without it a
    database hiccup on a process that has never seen a user answers `Principal.open()`,
    which would hand the top role to a request that proved nothing.
    """
    import os

    from .web.auth import StoreDown, principal_from_bearer

    try:
        principal = principal_from_bearer(ctx, os.environ.get(TOKEN_ENV) or None, require_online=True)
    except StoreDown as exc:
        raise Denied(STORE_DOWN) from exc
    if principal is None:
        raise Denied(NO_TOKEN)
    return principal


def _build_actor(principal):
    """The actor this identity may build as, or `None` for legacy-only open mode.

    `mcp_server.reader_actor` is the same three lines: this module stays out of the web
    and MCP import graphs on purpose, so that `hippo ask` never pays for FastAPI.
    """
    from .knowledge.build_authority import BuildActor

    if principal.is_open or principal.access.unrestricted:
        return None
    return BuildActor.reader(principal)


def _require(principal, capability: str) -> None:
    if not principal.can(capability):
        raise Denied(f"your role ({principal.role_name}) may not {capability.replace('_', ' ')}")


# ------------------------------------------------------------- commands


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn  # heavy import; only the server needs it

    config = load_config()
    host = args.host or config.host
    port = args.port or config.port
    print(f"hippo is starting at http://{host}:{port}  (MCP at http://{host}:{port}/mcp)")
    # The web app is imported lazily by uvicorn so `hippo ask` does not pay for FastAPI + Jinja.
    uvicorn.run("hippo.web.app:create_app", factory=True, host=host, port=port)
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import run_stdio

    run_stdio(AppContext.from_env())
    return 0


def cmd_pull_models(args: argparse.Namespace) -> int:
    ctx = AppContext.from_env()
    if not ctx.ollama.is_up():
        print(f"Ollama at {ctx.config.ollama_url} is not reachable.", file=sys.stderr)
        return 1
    missing = ctx.ollama.missing_models()
    if not missing:
        print("All models are installed: " + ", ".join(ctx.ollama.required_models()))
        return 0
    for model in missing:
        print(f"Pulling {model} ...")
        ctx.ollama.ensure_model(model, on_progress=_print_pull_event)
        print(f"{model} is ready")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    from .ingest import pipeline, repos

    ctx, remote = _context_or_running_server()
    if remote is not None:
        return _index_remotely(remote, args)
    # Before a Source row or a saved byte exists: an identity that may not add sources
    # must not leave one behind.
    principal = _principal(ctx)
    _require(principal, "add_sources")
    actor = _build_actor(principal)
    # The identity this command just resolved decides who may see the result and who may
    # manage it, exactly as it does for `hippo_remember` (`mcp_server.remember_tool`).
    # Leaving these to their `None` defaults published a low tier's own file to every role
    # and left its creator unable to rename or delete what they had made.
    owner_id = principal.user_id
    role_id = None if principal.is_open else principal.role_id
    target: str = args.target
    if repos.is_git_url(target):
        # A repository is not an accepted managed input, so it has no actor to take.
        source_id = pipeline.add_repo(ctx, target, owner_id=owner_id, access_role_id=role_id)
    else:
        path = Path(target)
        if not path.exists():
            print(f"{target} does not exist and is not a git URL", file=sys.stderr)
            return 1
        source_id = pipeline.add_upload(
            ctx,
            *_upload_for_path(path),
            owner_id=owner_id,
            access_role_id=role_id,
            build_actor=actor,
        )
    if args.name:
        ctx.store.update_source(source_id, name=args.name)

    print(f"Indexing {target} as source {source_id} ...")
    ctx.jobs.wait_all(WAIT_SECONDS)
    source = ctx.store.get_source(source_id) or {}
    print(f"status: {source.get('status')} ({source.get('stage')}), passages: {source.get('passages', 0)}")
    if source.get("error"):
        print(f"error: {_stored_error(source_id, source)}", file=sys.stderr)
        return 1
    return 0


def _stored_error(source_id: str, source: dict[str, Any]) -> str:
    """What a Source row's stored `error` may be printed as.

    The managed lane classifies a build failure once, where it happens, and stores its own
    closed `code: message` on the row (`ingest/managed_activation.record_build_failure`).
    That string *is* the public rendering, so it is printed unchanged - re-deriving it here
    would be a second opinion about an event this process did not see.

    The legacy lane stores `f"{type(err).__name__}: {err}"` instead, which is not a
    rendering at all: an `OllamaError` carries 300 characters of the model's reply body by
    construction, and a read error names the file it was reading. Open-mode `hippo index`
    and `hippo index <git-url>` both still take that lane, so anything whose leading token
    is not one of the closed codes is replaced rather than printed.
    """
    from .knowledge.public_errors import public_failure_for_code

    stored = str(source.get("error") or "")
    code, separator, message = stored.partition(": ")
    closed = public_failure_for_code(code) is not None or code == DENIED_CODE
    if separator and message and closed:
        return stored
    return INDEXING_FAILED.format(source_id=source_id)


def cmd_ask(args: argparse.Namespace) -> int:
    from .ask import ask
    from .knowledge.query_access import query_session

    ctx, remote = _context_or_running_server()
    if remote is not None:
        reply = remote.ask(args.question)
        if reply.get("error"):
            print(f"error: {reply['error']}", file=sys.stderr)
            return 1
        answer, thought, trace = reply["answer"], reply.get("thought"), reply["trace"]
        passages = trace.get("passages", [])
        fallback = trace.get("used_dpr_fallback"), trace.get("fallback_reason")
        print(_format_answer(answer, thought, passages, fallback))
    else:
        access = _principal(ctx).access
        with query_session(ctx, access) as session:
            trace_obj, answer_obj = ask(ctx, args.question, access=access, session=session)
            output = _format_answer(
                answer_obj.answer,
                answer_obj.thought,
                [vars(p) for p in trace_obj.passages],
                (trace_obj.used_dpr_fallback, trace_obj.fallback_reason),
            )
            session.validate()
            print(output)
    return 0


def _format_answer(answer, thought, passages, fallback) -> str:
    lines = [answer]
    if thought:
        lines.append(f"\nThought: {thought}")
    lines.append("\nTop passages:")
    for p in passages[:5]:
        lines.append(f"  {p['rank']:>2}. {p['score']:.4f}  {p['title']}  [{p['source_name']}]")
    if fallback[0]:
        lines.append(f"\n(no facts matched, fell back to embedding search: {fallback[1]})")
    return "\n".join(lines)


# ----------------------------------------------------------- the code graph
# Four commands, two ways to answer each. Locally they run web/routes/code.py's builders on this
# process's graph; behind a running server they call the same builders over /api/code. Both sides
# return the same dict and raise the same two errors, so only the plumbing below differs - which is
# what keeps `hippo path` printing one thing rather than two.


class CodeNameError(RuntimeError):
    """A name hippo cannot act on. `candidates` is non-empty when the name meant several things."""

    def __init__(self, message: str, candidates: list[str] | None = None):
        super().__init__(message)
        self.candidates = candidates or []


def _code_locally(ctx: AppContext, build) -> dict[str, Any]:
    """`build(code, index, theta)` over one held view, with the path tools' errors normalised.

    The view is this caller's, not the whole graph: a walk that crossed into code they
    may not see would be presentation of evidence they never proved. It is held through
    the build and validated on the way out, so a permission change mid-answer denies
    rather than prints.
    """
    from .hipporag.paths import AmbiguousSymbol, UnknownSymbol
    from .knowledge.query_access import query_session
    from .web.routes import code

    with query_session(ctx, _principal(ctx).access) as session:
        theta = float(session.settings["code_theta"])
        try:
            return build(code, session.graph, theta)
        except AmbiguousSymbol as exc:
            raise CodeNameError(str(exc), exc.candidates) from exc
        except (UnknownSymbol, ValueError) as exc:
            raise CodeNameError(str(exc)) from exc
        finally:
            session.validate()


def _code_remotely(call) -> dict[str, Any]:
    """The same answer from the running server; its 409 already carries the candidates."""
    try:
        return call()
    except RemoteAmbiguous as exc:
        raise CodeNameError(str(exc), exc.candidates) from exc


def cmd_path(args: argparse.Namespace) -> int:
    ctx, remote = _context_or_running_server()
    data = (
        _code_remotely(lambda: remote.code_path(args.a, args.b))
        if remote is not None
        else _code_locally(ctx, lambda c, i, t: c.path_payload(i, args.a, args.b, theta=t))
    )
    if not data["found"]:
        print(f"No relations connect {data['a']} and {data['b']} (above the code_theta setting).")
        return 0
    print(f"How {data['a']} reaches {data['b']}:")
    print("\n".join(data["lines"]))
    return 0


def cmd_blast(args: argparse.Namespace) -> int:
    ctx, remote = _context_or_running_server()
    data = (
        _code_remotely(lambda: remote.code_blast_radius(args.symbol, args.depth))
        if remote is not None
        else _code_locally(ctx, lambda c, i, t: c.blast_payload(i, args.symbol, theta=t, depth=args.depth))
    )
    print(f"What depends on {data['symbol']} (depth {data['depth']}):")
    print("\n".join(data["lines"]) if data["lines"] else "  nothing: no other symbol reaches it.")
    return 0


def cmd_raises(args: argparse.Namespace) -> int:
    ctx, remote = _context_or_running_server()
    data = (
        _code_remotely(lambda: remote.code_exception_path(args.symbol, args.exception))
        if remote is not None
        else _code_locally(ctx, lambda c, i, t: c.exception_payload(i, args.symbol, args.exception, theta=t))
    )
    if not data["found"]:
        print(f"{data['symbol']} does not reach {data['exception']}.")
        return 0
    print(f"How {data['symbol']} reaches {data['exception']}:")
    print("\n".join(data["lines"]))
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    ctx, remote = _context_or_running_server()
    data = (
        _code_remotely(lambda: remote.code_history(args.symbol, args.limit))
        if remote is not None
        else _code_locally(ctx, lambda c, i, _t: c.history_payload(i, args.symbol, limit=args.limit))
    )
    if not data["lines"]:
        print(
            f"No commits touched {data['symbol']}. "
            "History comes from a repo source; `hippo index <git-url>` reads it."
        )
        return 0
    print(f"Commits that touched {data['symbol']}, newest first:")
    print("\n".join(data["lines"]))
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    ctx, remote = _context_or_running_server()
    rows = remote.sources() if remote is not None else _sources_locally(ctx)
    if not rows:
        print("The memory is empty. Try: hippo index <file>")
        return 0
    print_table(
        ["id", "name", "kind", "status", "stage", "passages", "facts", "created"],
        [
            [
                r["id"],
                r["name"],
                r["kind"],
                r["status"],
                r.get("stage") or "",
                r.get("passages", 0),
                r.get("fact_links", 0),
                (r.get("created_at") or "")[:19],
            ]
            for r in rows
        ],
    )
    return 0


def _sources_locally(ctx: AppContext) -> list[dict[str, Any]]:
    """The caller's own library, from the same view the web app and MCP list.

    `store.list_sources()` unrestricted would be a different answer to the same question
    depending on which surface asked it, and would count a refreshed managed source's
    passages twice over. `status.source_view` counts from the held graph's provenance.
    """
    from .knowledge.query_access import query_session
    from .status import source_view

    access = _principal(ctx).access
    with query_session(ctx, access) as session:
        view = source_view(ctx, access, session=session)
        rows = list(view.sources)
        view.validate()
        return rows


def cmd_settings(args: argparse.Namespace) -> int:
    ctx, remote = _context_or_running_server()
    config = load_config()
    print("Where things are:")
    print(f"  store        = {config.store_backend} ({config.store_location})")
    if remote is not None:
        print(f"  server       = {remote.base_url} (running; the settings below come from it)")
    print(f"  ollama_url   = {config.ollama_url}")
    print(f"  llm_model    = {config.llm_model}")
    print(f"  embed_model  = {config.embed_model}")
    print(f"  data_dir     = {config.data_dir}")
    print("\nRetrieval settings (change them on the Settings page):")
    settings = remote.settings() if remote is not None else ctx.store.get_settings()
    for key, value in sorted(settings.items()):
        print(f"  {key} = {value}")
    return 0


# ------------------------------------------------- the running server, if any


def _context_or_running_server() -> tuple[AppContext | None, RemoteHippo | None]:
    """
    An AppContext when this process can open the store, else a client for the server that has it.
    Exactly one of the two is returned; StoreLockedError propagates if the file is locked and no
    server answers (some other hippo process has it).
    """
    try:
        return AppContext.from_env(), None
    except StoreLockedError:
        remote = RemoteHippo.for_config(load_config())
        if not remote.is_up():
            raise
        print(
            f"(the database is open in hippo serve; asking the server at {remote.base_url})", file=sys.stderr
        )
        return None, remote


def _index_remotely(remote: RemoteHippo, args: argparse.Namespace) -> int:
    from .ingest import repos

    target: str = args.target
    if repos.is_git_url(target):
        source_id = remote.add_repo(target)
    else:
        path = Path(target)
        if not path.exists():
            print(f"{target} does not exist and is not a git URL", file=sys.stderr)
            return 1
        source_id = remote.add_upload(*_upload_for_path(path))
    if args.name:
        print(
            "(--name is ignored when indexing through the server; rename it on the Library page)",
            file=sys.stderr,
        )
    print(f"Indexing {target} as source {source_id} ...")
    source = remote.wait_for_source(source_id, WAIT_SECONDS)
    print(f"status: {source.get('status')} ({source.get('stage')}), passages: {source.get('passages', 0)}")
    if source.get("error"):
        # The server's Source row is the same row with the same two lanes in it.
        print(f"error: {_stored_error(source_id, source)}", file=sys.stderr)
        return 1
    return 0


def cmd_users(args: argparse.Namespace) -> int:
    ctx, remote = _context_or_running_server()
    if remote is not None:
        roles, users = remote.roles(), remote.users()
    else:
        ctx.store.ping()  # seeds the roles on a fresh database
        roles, users = ctx.store.list_roles(), ctx.store.list_users()
    print("Roles, top of the ladder first (a tier sees itself and every tier below):")
    print_table(
        ["id", "name", "rank", "users", "sources", "may"],
        [
            [r["id"], r["name"], r["rank"], r["users"], r["sources"], ", ".join(r["capabilities"])]
            for r in roles
        ],
    )
    if not users:
        print(
            "\nNo users yet: hippo is open (everyone acts as the top role). Create one: hippo user add <name>"
        )
        return 0
    print()
    print_table(
        ["username", "name", "role", "rank", "sources", "status"],
        [
            [
                u["username"],
                u.get("display_name", ""),
                u["role_name"],
                u["rank"],
                u["sources"],
                "disabled" if u.get("disabled") else "active",
            ]
            for u in users
        ],
    )
    return 0


def _ask_password(args: argparse.Namespace) -> str | None:
    from getpass import getpass

    if args.password is not None:
        return args.password
    password = getpass("Password: ")
    if password != getpass("Again: "):
        print("The two passwords differ.", file=sys.stderr)
        return None
    return password


def cmd_user(args: argparse.Namespace) -> int:
    from .access import top_role

    ctx, remote = _context_or_running_server()
    if remote is not None:
        return _user_remotely(remote, args)
    ctx.store.ping()
    store = ctx.store
    if args.user_command == "add":
        role_id = args.role or top_role(store.list_roles())["id"]
        password = _ask_password(args)
        if password is None:
            return 2
        try:
            user_id = store.create_user(args.username, password, role_id, args.name)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        user = store.get_user(user_id) or {}
        print(f"Created {user['username']} as {user['role_name']}. Their token (for MCP and the API):")
        print(f"  {user['token']}")
        if store.count_users() == 1:
            print("That was the first user: hippo is no longer open. Sign in at /login.")
        return 0
    user = store.get_user_by_username(args.username)
    if user is None:
        print(f"error: no user '{args.username}'", file=sys.stderr)
        return 2
    if args.user_command == "token":
        print(store.rotate_token(user["id"]) if args.new else user["token"])
        return 0
    if args.user_command == "role":
        try:
            updated = store.update_user(user["id"], role_id=args.role_id)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"{updated['username']} is now {updated['role_name']} (rank {updated['rank']}).")
        return 0
    if args.user_command == "remove":
        store.delete_user(user["id"])
        print(f"Removed {user['username']}. Their sources stay, without an owner.")
        return 0
    return 2


def _user_remotely(remote: RemoteHippo, args: argparse.Namespace) -> int:
    """The same four sub-commands through the server's /api/users (which checks who may manage whom)."""
    if args.user_command == "add":
        password = _ask_password(args)
        if password is None:
            return 2
        reply = remote.create_user(args.username, password, args.role or "", args.name)
        user = reply.get("user") or {}
        print(
            f"Created {user.get('username')} as {user.get('role_name')}. Their token (for MCP and the API):"
        )
        print(f"  {reply.get('token')}")
        if reply.get("signed_in"):
            print("That was the first user: hippo is no longer open. Sign in at /login.")
        return 0
    user = remote.user_by_username(args.username)
    if user is None:
        print(f"error: no user '{args.username}'", file=sys.stderr)
        return 2
    if args.user_command == "token":
        if not args.new:
            print(
                "The server never hands out an existing token; read it on that user's Account page, "
                "or issue a new one with --new.",
                file=sys.stderr,
            )
            return 2
        print(remote.rotate_token(user["id"]))
        return 0
    if args.user_command == "role":
        updated = remote.set_user_role(user["id"], args.role_id)
        print(f"{updated['username']} is now {updated['role_name']} (rank {updated['rank']}).")
        return 0
    if args.user_command == "remove":
        remote.delete_user(user["id"])
        print(f"Removed {user['username']}. Their sources stay, without an owner.")
        return 0
    return 2


# -------------------------------------------------------------- helpers


def _print_pull_event(event: dict[str, Any]) -> None:
    status = event.get("status", "")
    if "completed" in event and "total" in event and event["total"]:
        percent = 100 * int(event["completed"]) // int(event["total"])
        print(f"  {status} {percent}%", end="\r", flush=True)
    else:
        print(f"  {status}")


def _upload_for_path(path: Path) -> tuple[str, bytes]:
    """What to hand to pipeline.add_upload: a file as-is, a folder zipped in memory."""
    if path.is_file():
        return path.name, path.read_bytes()
    return path.name + ".zip", _zip_folder(path)


def _zip_folder(folder: Path) -> bytes:
    """Zip a folder so it can go through the same 'archive' path as an uploaded .zip."""
    from .ingest.readers import IGNORED_DIRS, MAX_FILE_BYTES

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(folder.rglob("*")):
            relative = file.relative_to(folder)
            # Skip .git, node_modules, hidden folders and huge files: the readers would ignore them anyway,
            # and leaving them out keeps the zip small.
            parts = relative.parts[:-1]
            if any(p in IGNORED_DIRS or p.startswith(".") for p in parts):
                continue
            if file.is_file() and file.stat().st_size <= MAX_FILE_BYTES:
                zf.write(file, str(relative))
    return buffer.getvalue()


def print_table(headers: list[str], rows: Iterable[list[Any]]) -> None:
    """A plain aligned text table; no dependency needed."""
    rows = [[str(cell) for cell in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(cell)) for w, cell in zip(widths, row, strict=True)]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True))
    print(line)
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)))


if __name__ == "__main__":
    sys.exit(main())
