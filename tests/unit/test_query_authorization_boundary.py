"""Known revocations invalidate in-flight model work before its next use."""

import pytest

from hippo import ask
from hippo.access import Access
from hippo.hipporag.indexer import Chunk, index_source
from hippo.knowledge.access import AuthorizationChanged


@pytest.mark.parametrize("boundary", ["embed_one", "chat_json", "chat_text"])
def test_permission_change_during_model_call_discards_dependent_output(ctx, monkeypatch, boundary):
    ctx.store.ensure_roles()
    source = ctx.store.create_source("text", "public")
    index_source(
        ctx.store,
        ctx.ollama,
        source,
        [Chunk(0, "Orion arm", "The Orion arm was designed by Mira Chen at Aster Labs.")],
    )
    original = getattr(ctx.ollama, boundary)
    called = []

    def revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        called.append(boundary)
        ctx.store.set_source_access(source, "local-admin")
        return result

    monkeypatch.setattr(ctx.ollama, boundary, revoke)
    with pytest.raises(AuthorizationChanged):
        ask.ask(ctx, "Who designed the Orion arm?", access=Access(rank=0, user_id="reader"))
    assert called == [boundary]


def test_http_query_returns_retryable_error_after_revocation(ctx, monkeypatch):
    from fastapi.testclient import TestClient

    from hippo.web.app import create_app

    def revoked(*args, **kwargs):
        raise AuthorizationChanged("internal proof details must not be returned")

    monkeypatch.setattr(ask, "ask", revoked)
    with TestClient(create_app(ctx), base_url="http://localhost", raise_server_exceptions=False) as client:
        response = client.post("/api/ask", json={"question": "anything"})
    assert response.status_code == 409
    assert response.json() == {
        "error": "Permissions changed; repeat the query",
        "code": "authorization_changed",
    }


@pytest.mark.parametrize("method", ["embed_one", "chat_json", "chat_text"])
def test_model_error_cannot_skip_post_call_revocation_check(ctx, monkeypatch, method):
    from hippo.knowledge.query_access import query_access
    from hippo.ollama import OllamaError

    def failed(*args, **kwargs):
        ctx.store._bump_authorization_epoch()
        raise OllamaError("private provider error payload")

    monkeypatch.setattr(ctx.ollama, method, failed)
    _, model, _ = query_access(ctx, None)
    with pytest.raises(AuthorizationChanged):
        getattr(model, method)("query")


def restricted_query_fixture(ctx):
    ctx.store.ensure_roles()
    user = ctx.store.create_user("query-reader", "password1", "arch-admin")
    source = ctx.store.create_source("text", "restricted")
    ctx.store.set_source_access(source, "arch-admin")
    index_source(
        ctx.store,
        ctx.ollama,
        source,
        [Chunk(0, "Orion arm", "The Orion arm was designed by Mira Chen at Aster Labs.")],
    )
    return user, source


def test_role_downgrade_before_query_cannot_reuse_authenticated_rank(ctx):
    from hippo.knowledge.query_access import query_access

    user, _ = restricted_query_fixture(ctx)
    authenticated = Access(rank=40, user_id=user, unrestricted=True)
    ctx.store.update_user(user, role_id="individual")
    graph, _, validate = query_access(ctx, authenticated)
    assert graph.passages == []
    validate()


@pytest.mark.parametrize("change", ["disabled", "deleted", "deleted_last", "missing"])
def test_reader_identity_lost_before_query_cannot_use_old_access(ctx, change):
    from hippo.knowledge.query_access import query_access

    user, _ = restricted_query_fixture(ctx)
    if change != "deleted_last":
        ctx.store.create_user("remaining-admin", "password1", "arch-admin")
    if change == "disabled":
        ctx.store.update_user(user, disabled=True)
    elif change in {"deleted", "deleted_last"}:
        ctx.store.delete_user(user)
    else:
        user = "not-a-user"
    with pytest.raises(AuthorizationChanged):
        query_access(ctx, Access(rank=40, user_id=user))


def test_open_principal_cannot_survive_first_user_creation(ctx):
    from hippo.access import Principal
    from hippo.knowledge.query_access import query_access

    authenticated = Principal.open().access
    restricted_query_fixture(ctx)
    with pytest.raises(AuthorizationChanged):
        query_access(ctx, authenticated)


def test_reader_revalidation_preserves_owner_access_and_explicit_lower_rank(ctx):
    from hippo.knowledge.query_access import current_access, query_access

    user, source = restricted_query_fixture(ctx)
    ctx.store.set_source_access(source, "arch-admin", owner_id=user)
    current = current_access(ctx.store, Access(rank=0, user_id=user, unrestricted=True))
    assert current.rank == 0
    assert current.user_id == user
    assert current.unrestricted is False
    graph, _, validate = query_access(ctx, current)
    assert len(graph.passages) == 1
    validate()


def test_preview_never_inherits_owner_or_unrestricted_access(ctx):
    from hippo.knowledge.query_access import query_access

    user, source = restricted_query_fixture(ctx)
    ctx.store.set_source_access(source, "arch-admin", owner_id=user)
    graph, _, validate = query_access(
        ctx, Access(rank=0, user_id=user, unrestricted=True, audience_kind="preview")
    )
    assert graph.passages == []
    validate()


def test_revocation_during_live_identity_read_is_detected(ctx, monkeypatch):
    from hippo.knowledge.query_access import query_access

    user, _ = restricted_query_fixture(ctx)
    original = ctx.store.get_user
    changed = False

    def read(user_id):
        nonlocal changed
        value = original(user_id)
        if user_id == user and not changed:
            changed = True
            ctx.store.update_user(user, disabled=True)
        return value

    monkeypatch.setattr(ctx.store, "get_user", read)
    with pytest.raises(AuthorizationChanged):
        query_access(ctx, Access(rank=40, user_id=user))
    assert changed


def test_explicit_internal_and_legacy_none_remain_supported(ctx):
    from hippo.access import EVERYTHING
    from hippo.knowledge.query_access import current_access, query_access

    restricted_query_fixture(ctx)
    assert current_access(ctx.store, None) is None
    assert current_access(ctx.store, EVERYTHING) is EVERYTHING
    for access in (None, EVERYTHING):
        graph, _, validate = query_access(ctx, access)
        assert len(graph.passages) == 1
        validate()


def test_fresh_zero_user_synthetic_reader_keeps_legacy_scoping(ctx):
    from hippo.knowledge.query_access import current_access

    access = Access(rank=10, user_id="synthetic-reader")
    assert current_access(ctx.store, access) == access


def test_deliberate_return_to_open_mode_remains_available(ctx):
    from hippo.access import Principal
    from hippo.knowledge.query_access import current_access

    user, _ = restricted_query_fixture(ctx)
    ctx.store.delete_user(user)
    access = Principal.open().access
    assert current_access(ctx.store, access) == access


def test_model_failure_without_revocation_preserves_original_error(ctx, monkeypatch):
    from hippo.knowledge.query_access import query_access
    from hippo.ollama import OllamaError

    error = OllamaError("ordinary provider failure")

    def failed(*args, **kwargs):
        raise error

    monkeypatch.setattr(ctx.ollama, "chat_text", failed)
    _, model, _ = query_access(ctx, None)
    with pytest.raises(OllamaError) as caught:
        model.chat_text("query")
    assert caught.value is error


def test_graph_expiry_callback_blocks_model_output_without_epoch_write(ctx, monkeypatch):
    restricted_query_fixture(ctx)
    expired = False

    def check_expiry():
        if expired:
            raise AuthorizationChanged("The evidence proof expired")

    # The callback has to sit on the graph the query will actually run on. A structural
    # selection builds a fresh view per query, so stamping a separately acquired object
    # would install the check on a graph nothing ever reads.
    build = ctx._build_structural_graph

    def stamping(*args, **kwargs):
        graph = build(*args, **kwargs)
        graph.authorization_check = check_expiry
        return graph

    monkeypatch.setattr(ctx, "_build_structural_graph", stamping)
    original = ctx.ollama.chat_text
    epoch = ctx.store.authorization_epoch()

    def expire(*args, **kwargs):
        nonlocal expired
        result = original(*args, **kwargs)
        expired = True
        return result

    monkeypatch.setattr(ctx.ollama, "chat_text", expire)
    with pytest.raises(AuthorizationChanged):
        ask.ask(ctx, "Who designed the Orion arm?")
    assert expired
    assert ctx.store.authorization_epoch() == epoch


@pytest.mark.parametrize("entrypoint, stage", [("search", "_search"), ("ask", "_answer_from_trace")])
def test_final_release_guard_catches_revocation_after_last_model_call(ctx, monkeypatch, entrypoint, stage):
    restricted_query_fixture(ctx)
    original = getattr(ask, stage)

    def revoke_after(*args, **kwargs):
        result = original(*args, **kwargs)
        ctx.store._bump_authorization_epoch()
        return result

    monkeypatch.setattr(ask, stage, revoke_after)
    with pytest.raises(AuthorizationChanged):
        getattr(ask, entrypoint)(ctx, "Who designed the Orion arm?")
