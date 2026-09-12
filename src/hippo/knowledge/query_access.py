"""Permission checks around every model call and before releasing query output."""

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ..access import Access
from ..store.base import validate_settings
from .access import AuthorizationChanged


def current_access(store, access: Access | None) -> Access | None:
    """Refresh a caller's identity within the caller's authorization-epoch bracket.

    None retains its legacy meaning; the graph context decides whether it means
    internal local access or an open audience for managed evidence. Preview ranks
    never acquire ownership. Only installations that have never had users retain
    the synthetic reader scopes used by local previews and legacy integrations.
    """
    if access is None or access.audience_kind == "internal":
        return access
    if access.audience_kind == "preview":
        return Access(rank=access.rank, audience_kind="preview")
    users_exist = store.count_users() > 0
    if access.audience_kind == "open":
        if users_exist:
            raise AuthorizationChanged("Open access ended; authenticate again")
        return access
    if access.audience_kind != "reader":
        raise AuthorizationChanged("Unknown query audience")
    if not users_exist and not store.get_meta("has_had_users"):
        return access
    user = store.get_user(access.user_id) if access.user_id else None
    if not user or user.get("disabled") or user.get("id") != access.user_id:
        raise AuthorizationChanged("The authenticated user is no longer available")
    role = store.get_role(user.get("role_id"))
    if not role:
        raise AuthorizationChanged("The authenticated role is no longer available")
    return Access(rank=min(access.rank, int(role.get("rank") or 0)), user_id=access.user_id)


class AuthorizedModel:
    def __init__(self, model, validate):
        self.model = model
        self.validate = validate

    @property
    def profile_fingerprint(self) -> str | None:
        """Expose only the wrapped immutable profile identity, without model I/O."""
        self.validate()
        try:
            return getattr(self.model, "profile_fingerprint", None)
        finally:
            self.validate()

    def _call(self, name, *args, **kwargs):
        self.validate()
        try:
            return getattr(self.model, name)(*args, **kwargs)
        finally:
            self.validate()

    def embed_one(self, *args, **kwargs):
        return self._call("embed_one", *args, **kwargs)

    def chat_json(self, *args, **kwargs):
        return self._call("chat_json", *args, **kwargs)

    def chat_text(self, *args, **kwargs):
        return self._call("chat_text", *args, **kwargs)


def query_access(ctx, access, *, settings: dict[str, Any] | None = None, structural: bool = True):
    """Prove one audience's view of the graph. Structural generation selection is the default.

    `structural=False` is the legacy compatibility lane: it couples every selected
    managed generation to the configured embedding tag. `AppContext.graph_for` keeps
    the opposite default, because it is the low-level entry point.
    """
    epoch = ctx.store.authorization_epoch()
    access = current_access(ctx.store, access)
    if structural:
        graph = ctx.graph_for(access, settings=settings, structural=True)
    else:
        graph = ctx.graph_for(access, settings=settings) if settings is not None else ctx.graph_for(access)

    def validate():
        if ctx.store.authorization_epoch() != epoch:
            raise AuthorizationChanged("Permissions changed; repeat the query")
        graph.validate_authorization()

    try:
        validate()
    except BaseException:
        close = getattr(graph, "close_snapshot", None)
        if close is not None:
            close()
        raise
    return graph, AuthorizedModel(ctx.ollama, validate), validate


@dataclass(frozen=True)
class QuerySession:
    """The graph, guarded model and live authorization proof for one query."""

    graph: Any
    model: AuthorizedModel
    validate: Callable[[], None]
    settings: Mapping[str, Any]


@contextmanager
def query_session(
    ctx, access=None, *, settings: dict[str, Any] | None = None, structural: bool = True
) -> Iterator[QuerySession]:
    """Keep one view pinned through output construction, then release it on every exit.

    Structural generation selection by default, like `query_access`. The flag is
    forwarded verbatim: an explicit `structural=False` must reach the lower layer
    rather than fall through to its default.
    """
    effective_settings = validate_settings({**ctx.store.get_settings(), **(settings or {})})
    captured_settings = MappingProxyType(effective_settings)
    graph, model, validate = query_access(
        ctx, access, settings=dict(captured_settings), structural=structural
    )
    heartbeat = None

    def validate_live():
        if heartbeat is not None:
            heartbeat.check()
        validate()
        if heartbeat is not None:
            heartbeat.check()

    try:
        if getattr(graph, "snapshot_ids", ()):
            from .lease_heartbeat import LeaseHeartbeat

            heartbeat = LeaseHeartbeat(validate, interval=graph.snapshot_renewal_interval)
            heartbeat.start()
        yield QuerySession(graph, AuthorizedModel(model, validate_live), validate_live, captured_settings)
    finally:
        if heartbeat is not None:
            heartbeat.close()
        try:
            validate_live()
        finally:
            close = getattr(graph, "close_snapshot", None)
            if close is not None:
                close()
