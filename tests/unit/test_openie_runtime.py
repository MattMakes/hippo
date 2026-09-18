"""Captured OpenIE semantics through real Ollama HTTP retry boundaries."""

import importlib
import importlib.util
import json
from dataclasses import FrozenInstanceError, replace
from threading import Event, Thread, current_thread

import httpx
import pytest

from hippo import prompts
from hippo.ollama import Ollama, OllamaError


def api():
    assert importlib.util.find_spec("hippo.knowledge.openie_runtime"), "Captured OpenIE runtime missing"
    return importlib.import_module("hippo.knowledge.openie_runtime")


class Server:
    def __init__(self):
        self.digest = "b" * 64
        self.models = None
        self.capabilities = ["completion", "thinking"]
        self.calls = []
        self.hook = None
        self.response_model = "chat:latest"
        self.response_text = None

    def handle(self, request):
        path, body = request.url.path, json.loads(request.content or "{}")
        self.calls.append((path, body))
        if self.hook:
            response = self.hook(path, body)
            if response is not None:
                return response
        if path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": self.models
                    if self.models is not None
                    else [{"name": "chat:latest", "model": "chat:latest", "digest": self.digest}]
                },
            )
        if path == "/api/show":
            return httpx.Response(200, json={"capabilities": self.capabilities})
        if path == "/api/chat":
            output = (
                {"named_entities": ["ACME", "Robot"]}
                if body["format"] == prompts.NER_SCHEMA
                else {"triples": [["ACME", "builds", "Robot"]]}
            )
            return httpx.Response(
                200,
                json={
                    "model": self.response_model,
                    "message": {
                        "content": self.response_text
                        if self.response_text is not None
                        else json.dumps(output)
                    },
                },
            )
        pytest.fail(f"Unexpected request {path}")

    def client(self):
        return Ollama(
            "http://openie-test",
            "chat",
            "embed",
            num_ctx=8192,
            client=httpx.Client(base_url="http://openie-test", transport=httpx.MockTransport(self.handle)),
        )

    @property
    def chats(self):
        return [body for path, body in self.calls if path == "/api/chat"]


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch):
    monkeypatch.setattr("hippo.ollama.time.sleep", lambda seconds: None)


def runtime(server=None, check=lambda: None):
    module, server = api(), server or Server()
    client = server.client()
    resolved = module.resolve_openie_profile(client, authorization_check=check)
    return server, client, resolved, module.GuardedOpenIE(client, resolved, authorization_check=check)


def ask(model, *, guard=lambda: None):
    return model.chat_json(
        prompts.ner_messages("ACME builds Robot."), prompts.NER_SCHEMA, max_tokens=512, request_guard=guard
    )


def test_resolve_captures_safe_profile_without_source_inference():
    server, client, resolved, model = runtime()
    assert resolved.profile == model.profile
    assert model.profile.wire_model == "chat:latest"
    assert model.profile.model_digest == "b" * 64
    assert model.profile.num_ctx == 8192
    assert not server.chats
    assert [path for path, _ in server.calls] == ["/api/tags", "/api/show", "/api/tags"]
    assert "http" not in repr(resolved)
    with pytest.raises(FrozenInstanceError):
        resolved.profile = None
    with pytest.raises(AttributeError):
        model.profile = None
    assert client._capabilities == {}


@pytest.mark.parametrize(
    "capabilities",
    [
        None,
        [],
        ["embedding"],
        "completion",
        ["completion", {}],
        ["completion", "completion"],
        ["completion", ""],
    ],
)
def test_missing_or_malformed_completion_capability_rejects(capabilities):
    module, server = api(), Server()
    server.capabilities = capabilities
    with pytest.raises(OllamaError):
        module.resolve_openie_profile(server.client(), authorization_check=lambda: None)
    assert not server.chats


@pytest.mark.parametrize(
    "models",
    [
        [],
        [{"name": "chat:latest", "digest": "bad"}],
        [{"name": "chat", "digest": "a" * 64}, {"name": "chat:latest", "digest": "b" * 64}],
    ],
)
def test_missing_ambiguous_and_invalid_installed_identity_rejects(models):
    module, server = api(), Server()
    server.models = models
    with pytest.raises(OllamaError):
        module.resolve_openie_profile(server.client(), authorization_check=lambda: None)
    assert not server.chats


def test_resolver_rejects_model_change_during_show():
    module, server = api(), Server()

    def mutate(path, body):
        if path == "/api/show":
            server.digest = "c" * 64

    server.hook = mutate
    with pytest.raises(OllamaError):
        module.resolve_openie_profile(server.client(), authorization_check=lambda: None)


@pytest.mark.parametrize("thinking", [False, True])
def test_chat_uses_captured_options_and_ignores_shared_capability_cache(thinking):
    server = Server()
    server.capabilities = ["completion"] + (["thinking"] if thinking else [])
    server, client, _, model = runtime(server)
    client._capabilities["chat"] = {"thinking"} if not thinking else set()
    assert ask(model) == {"named_entities": ["ACME", "Robot"]}
    body = server.chats[0]
    assert body["model"] == "chat:latest"
    assert body["options"] == {"temperature": 0.0, "num_ctx": 8192, "num_predict": 512}
    assert body["messages"] == prompts.ner_messages("ACME builds Robot.")
    assert body["format"] == prompts.NER_SCHEMA
    assert body["stream"] is False
    assert ("think" in body) == thinking
    if thinking:
        assert body["think"] is False


@pytest.mark.parametrize("drift", ["model", "context", "endpoint", "client", "digest"])
def test_runtime_identity_drift_prevents_source_dispatch(drift):
    server, client, _, model = runtime()
    if drift == "model":
        client.llm_model = "other"
    elif drift == "context":
        client.num_ctx += 1
    elif drift == "endpoint":
        client.base_url = "http://other"
    elif drift == "client":
        client.client = httpx.Client(
            base_url="http://openie-test", transport=httpx.MockTransport(server.handle)
        )
    else:
        server.digest = "c" * 64
    with pytest.raises(OllamaError):
        ask(model)
    assert not server.chats


@pytest.mark.parametrize("fault", ["digest", "authorization", "request_guard"])
def test_retry_revalidates_before_resending_source_text(fault):
    authorized = True

    def check():
        if not authorized:
            raise PermissionError("revoked")

    server, _, _, model = runtime(check=check if fault == "authorization" else lambda: None)

    def fail(path, body):
        nonlocal authorized
        if path == "/api/chat":
            if fault == "digest":
                server.digest = "c" * 64
            else:
                authorized = False
            return httpx.Response(503, json={"error": "retry"})

    server.hook = fail
    with pytest.raises((OllamaError, PermissionError)):
        ask(model, guard=check if fault == "request_guard" else lambda: None)
    assert len(server.chats) == 1
    server.digest, authorized, server.hook = "b" * 64, True, None
    with pytest.raises((OllamaError, PermissionError)):
        ask(model)
    assert len(server.chats) == 1


@pytest.mark.parametrize("transport", [False, True])
def test_successful_retry_preserves_captured_body(transport):
    server, _, _, model = runtime()

    def fail_once(path, body):
        if path == "/api/chat" and len(server.chats) == 1:
            if transport:
                raise httpx.ConnectError("retry")
            return httpx.Response(503)

    server.hook = fail_once
    assert ask(model)["named_entities"] == ["ACME", "Robot"]
    assert server.chats[0] == server.chats[1]


@pytest.mark.parametrize("text", ['<think>private</think>{"ok":true}', '```json\n{"ok":true}\n```'])
def test_existing_json_and_think_block_parsing_is_preserved(text):
    server, _, _, model = runtime()
    server.response_text = text
    assert ask(model) == {"ok": True}


@pytest.mark.parametrize("fault", ["model", "invalid_json"])
def test_response_failure_latches_and_denies_future_calls(fault):
    server, _, _, model = runtime()
    if fault == "model":
        server.response_model = "other"
    else:
        server.response_text = "not json"
    with pytest.raises(OllamaError):
        ask(model)
    with pytest.raises(OllamaError):
        ask(model)
    assert len(server.chats) == 1


def test_real_plain_preparation_runs_both_phases_through_guarded_http():
    from tests.unit.test_managed_prose_preparation import Embeddings, inputs
    from tests.unit.test_managed_prose_preparation import api as prep_api

    value = inputs()
    server, _, _, model = runtime()
    assert value.extractor_profile == model.profile
    prepared = prep_api().prepare_plain_prose(
        value, embeddings=Embeddings(value.embedding_profile), chat=model, check=lambda: None, workers=1
    )
    assert [body["options"]["num_predict"] for body in server.chats] == [512, 2048]
    assert prepared.extractions[0].payload.triples[0].predicate == "builds"


@pytest.mark.parametrize("limit", [True, 0, 10, 512.0, None])
def test_uncaptured_token_limits_reject_before_dispatch(limit):
    server, _, _, model = runtime()
    with pytest.raises(ValueError):
        model.chat_json([], prompts.NER_SCHEMA, max_tokens=limit, request_guard=lambda: None)
    assert not server.chats


def test_constructor_rejects_other_transport_without_http():
    server, _, resolved, _ = runtime()
    other = server.client()
    before = len(server.calls)
    with pytest.raises(OllamaError):
        api().GuardedOpenIE(other, resolved, authorization_check=lambda: None)
    assert len(server.calls) == before


@pytest.mark.parametrize(
    "payload", [[], {"model": "chat", "message": []}, {"model": "chat", "message": {"content": 1}}]
)
def test_malformed_response_fails_with_controlled_error(payload):
    server, _, _, model = runtime()
    server.hook = lambda path, body: httpx.Response(200, json=payload) if path == "/api/chat" else None
    with pytest.raises(OllamaError):
        ask(model)


def test_resolved_identity_cannot_retain_mutable_capabilities():
    _, _, resolved, _ = runtime()
    with pytest.raises(ValueError):
        replace(resolved, capabilities=list(resolved.capabilities))


@pytest.mark.parametrize("callback", ["authorization", "request"])
def test_concurrent_failure_during_callback_prevents_late_dispatch(callback):
    entered, release = Event(), Event()
    should_block = False

    def checkpoint():
        if should_block and current_thread().name == "late-openie":
            entered.set()
            assert release.wait(5)

    server, _, _, model = runtime(check=checkpoint if callback == "authorization" else lambda: None)
    failures = []

    def late():
        try:
            ask(model, guard=checkpoint if callback == "request" else lambda: None)
        except BaseException as exc:
            failures.append(exc)

    should_block = True
    thread = Thread(target=late, name="late-openie")
    thread.start()
    try:
        assert entered.wait(5)
        server.response_text = "invalid JSON"
        with pytest.raises(OllamaError):
            ask(model)
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert len(server.chats) == 1
    assert len(failures) == 1 and isinstance(failures[0], OllamaError)
