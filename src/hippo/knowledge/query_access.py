"""Permission checks around every model call and before releasing query output."""

from ..access import Access
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


def query_access(ctx, access):
    epoch = ctx.store.authorization_epoch()
    access = current_access(ctx.store, access)
    graph = ctx.graph_for(access)

    def validate():
        if ctx.store.authorization_epoch() != epoch:
            raise AuthorizationChanged("Permissions changed; repeat the query")
        graph.validate_authorization()

    validate()
    return graph, AuthorizedModel(ctx.ollama, validate), validate
