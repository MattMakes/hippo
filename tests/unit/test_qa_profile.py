"""The opt-in final-answer profile, from environment through the guarded Ollama wire."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from hippo import cli, prompts
from hippo.ask import answer_from_trace, ask
from hippo.config import Config, load_config
from hippo.context import AppContext
from hippo.hipporag.answerer import QA_MAX_TOKENS, answer_question
from hippo.hipporag.retriever import Trace
from hippo.knowledge.embedding_profile import (
    EmbeddingProfileChanged,
    EmbeddingSpec,
    ProfiledEmbeddings,
    resolve_embedding_profile,
)
from hippo.knowledge.public_errors import public_failure
from hippo.knowledge.query_access import AuthorizedModel
from hippo.ollama import Ollama, OllamaError
from hippo.web.app import create_app
from tests.fakes.fake_ollama import FakeOllama

BASE = "qwen3:8b"
EMBED = "nomic-embed-text"
QA = "qwen3.8:latest"


class Recorder:
    def __init__(self, handler):
        self.handler = handler
        self.requests: list[tuple[str, dict]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}") if request.method == "POST" else {}
        self.requests.append((request.url.path, body))
        return self.handler(request)

    def bodies(self, path: str) -> list[dict]:
        return [body for seen, body in self.requests if seen == path]


def client_for(handler) -> httpx.Client:
    return httpx.Client(base_url="http://fake-ollama", transport=httpx.MockTransport(handler))


def recorded_ollama(*, qa_model: str | None = QA, installed: list[str] | None = None):
    fake = FakeOllama(installed=installed or [BASE, EMBED + ":latest", QA])
    recorder = Recorder(fake.handle)
    client = Ollama(
        "http://fake-ollama",
        BASE,
        EMBED,
        qa_model=qa_model,
        client=client_for(recorder),
    )
    return client, recorder, fake


def test_config_qa_model_defaults_inherits_and_strips_nonempty_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HIPPO_QA_MODEL", raising=False)
    assert load_config().qa_model is None
    monkeypatch.setenv("HIPPO_QA_MODEL", "  ")
    assert load_config().qa_model is None
    monkeypatch.setenv("HIPPO_QA_MODEL", f"  {QA}  ")
    assert load_config().qa_model == QA


def test_required_models_adds_only_a_distinct_qa_alias() -> None:
    client, _, _ = recorded_ollama(qa_model=QA)
    assert client.required_models() == [BASE, EMBED, QA]
    same, _, _ = recorded_ollama(qa_model="qwen3:8b")
    assert same.required_models() == [BASE, EMBED]
    alias, _, _ = recorded_ollama(qa_model="nomic-embed-text:latest")
    assert alias.required_models() == [BASE, EMBED]


def test_missing_and_pull_results_include_the_configured_qa_model() -> None:
    client, _, fake = recorded_ollama(installed=[BASE, EMBED + ":latest"])
    assert client.missing_models() == [QA]
    client.ensure_model(QA)
    assert fake.installed[-1] == QA
    assert client.missing_models() == []


def test_default_answer_protocol_stays_four_messages_and_1024_tokens() -> None:
    client, recorder, _ = recorded_ollama(qa_model=None)
    answer_question(client, "Where?", [("p1", "Source", "A place is here.")])
    (body,) = recorder.bodies("/api/chat")
    assert body["model"] == BASE
    assert len(body["messages"]) == 4
    assert [message["role"] for message in body["messages"]] == ["system", "user", "assistant", "user"]
    assert [hashlib.sha256(message["content"].encode()).hexdigest() for message in body["messages"]] == [
        "99c1a269c82621a4e6ec0d7b97e11b1860876fa971e14dd402f5c164fac17fbb",
        "86f369d207257f921e70bf5b808d7ce68aa678ab264dbffa8d514deb56b7eeb6",
        "b6949ba71d7fcd88fd9695114664d9483dc6f8f9ec784ae5fe970cbf457d95d0",
        "8979626dd864f774bc16eb5c7f7394eddf93021a6c31ef270a0cea4f2d09436d",
    ]
    assert body["options"]["num_predict"] == QA_MAX_TOKENS == 1024
    assert body["messages"][-1]["content"].endswith("Question: Where?\nThought: ")


def test_default_system_prompt_is_the_committed_reference_text() -> None:
    assert prompts.QA_SYSTEM == (
        "As an advanced reading comprehension assistant, your task is to analyze text passages and corresponding "
        'questions meticulously. Your response start after "Thought: ", where you will methodically break down the '
        'reasoning process, illustrating how you arrive at conclusions. Conclude with "Answer: " to present a concise, '
        "definitive response, devoid of additional elaborations."
    )


def test_profile_answer_uses_exact_two_message_wire_controls_and_one_chat() -> None:
    client, recorder, _ = recorded_ollama()
    answer = answer_question(
        client,
        "List the steps.",
        [("p1", "First", "Step one."), ("p2", "Second", "Step two.")],
        qa_model=QA,
    )
    expected_messages = [
        {"role": "system", "content": prompts.GROUNDED_QA_SYSTEM},
        {
            "role": "user",
            "content": "Title: First\nStep one.\n\nTitle: Second\nStep two.\n\nQuestion: List the steps.",
        },
    ]
    assert recorder.bodies("/api/chat") == [
        {
            "model": QA,
            "messages": expected_messages,
            "stream": False,
            "keep_alive": "15m",
            "options": {
                "temperature": 0.0,
                "num_ctx": 8192,
                "num_predict": 4096,
                "top_p": 0.95,
                "top_k": 20,
                "min_p": 0.0,
                "seed": 0,
            },
            "think": False,
        }
    ]
    assert answer.answer
    assert answer.thought == ""
    assert answer.raw == answer.answer
    options = recorder.bodies("/api/chat")[0]["options"]
    assert type(options["min_p"]) is float
    assert type(options["seed"]) is int


def test_per_call_model_uses_its_own_capability_cache_without_mutating_base() -> None:
    client, recorder, _ = recorded_ollama()
    client.chat_text([{"role": "user", "content": "profile"}], model=QA)
    client.chat_json([{"role": "user", "content": "base"}], {})
    assert [body["model"] for body in recorder.bodies("/api/show")] == [QA, BASE]
    assert [body["model"] for body in recorder.bodies("/api/chat")] == [QA, BASE]
    assert client.llm_model == BASE


def test_nonthinking_override_omits_think_false() -> None:
    model = "plain:latest"
    client, recorder, _ = recorded_ollama(qa_model=model, installed=[BASE, EMBED + ":latest", model])
    client.chat_text([{"role": "user", "content": "hello"}], model=model)
    assert "think" not in recorder.bodies("/api/chat")[0]


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"message": {"content": "final"}, "done": False, "done_reason": "stop"}, "incomplete"),
        ({"message": {"content": "final"}, "done": True, "done_reason": "length"}, "incomplete"),
        ({"message": {"content": "   "}, "done": True, "done_reason": "stop"}, "empty"),
        ({"message": {"content": 7}, "done": True, "done_reason": "stop"}, "invalid"),
    ],
)
def test_require_complete_rejects_incomplete_or_malformed_output_without_leaking(
    payload: dict, match: str
) -> None:
    secret = "private-source-sentinel"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": []})
        payload["provider_secret"] = secret
        return httpx.Response(200, json=payload)

    client = Ollama("http://fake-ollama", BASE, EMBED, client=client_for(handler))
    with pytest.raises(OllamaError, match=match) as info:
        client.chat_text([{"role": "user", "content": secret}], require_complete=True)
    assert secret not in str(info.value)


def test_require_complete_returns_only_clean_final_content_not_native_thinking() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["thinking"]})
        return httpx.Response(
            200,
            json={
                "message": {"content": "  visible final  ", "thinking": "private thought"},
                "done": True,
                "done_reason": "stop",
            },
        )

    client = Ollama("http://fake-ollama", BASE, EMBED, client=client_for(handler))
    assert client.chat_text([{"role": "user", "content": "?"}], require_complete=True) == "visible final"


def test_require_complete_rejects_non_json_provider_output() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": []})
        return httpx.Response(200, content=b"not-json")

    client = Ollama("http://fake-ollama", BASE, EMBED, client=client_for(handler))
    with pytest.raises(OllamaError, match="invalid complete-answer response"):
        client.chat_text([{"role": "user", "content": "?"}], require_complete=True)


def test_require_complete_bounds_http_errors_without_provider_content() -> None:
    secret = "private-provider-error-sentinel"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": []})
        return httpx.Response(400, text=secret)

    client = Ollama("http://fake-ollama", BASE, EMBED, client=client_for(handler))
    with pytest.raises(OllamaError) as info:
        client.chat_text([{"role": "user", "content": "?"}], require_complete=True)
    assert str(info.value) == "Ollama could not complete the answer"
    assert secret not in str(info.value)


@pytest.mark.parametrize("guarded", [False, True], ids=["direct", "guarded"])
def test_require_complete_bounds_fresh_capability_http_error_at_its_origin(guarded: bool) -> None:
    secret = "private-show-error-sentinel"
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/show":
            return httpx.Response(400, text=secret)
        raise AssertionError("complete QA must stop after capability lookup fails")

    client = Ollama("http://fake-ollama", BASE, EMBED, client=client_for(handler))
    guard = (lambda: None) if guarded else None
    with pytest.raises(OllamaError) as info:
        client.chat_text(
            [{"role": "user", "content": "?"}],
            model=QA,
            require_complete=True,
            request_guard=guard,
        )
    assert str(info.value) == "Ollama could not complete the answer"
    assert secret not in str(info.value)
    assert paths == ["/api/show"]


def test_require_complete_bounds_invalid_capability_json_without_chat() -> None:
    secret = "private-invalid-show-json-sentinel"
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/show":
            return httpx.Response(200, text=secret)
        raise AssertionError("complete QA must stop after invalid capability metadata")

    client = Ollama("http://fake-ollama", BASE, EMBED, client=client_for(handler))
    with pytest.raises(OllamaError) as info:
        client.chat_text([{"role": "user", "content": "?"}], model=QA, require_complete=True)
    assert str(info.value) == "Ollama returned an invalid complete-answer response"
    assert secret not in str(info.value)
    assert paths == ["/api/show"]


class ExactGuardError(OllamaError):
    pass


@pytest.mark.parametrize(
    "guard_error",
    [
        OllamaError("exact ollama guard failure"),
        ExactGuardError("typed ollama guard failure"),
        PermissionError("permission guard failure"),
        ValueError("value guard failure"),
    ],
    ids=["ollama", "ollama-subclass", "permission", "value"],
)
def test_require_complete_preserves_exact_guard_exception_and_makes_no_request(
    guard_error: BaseException,
) -> None:
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        raise AssertionError("a failed guard must prevent provider requests")

    def guard() -> None:
        raise guard_error

    client = Ollama("http://fake-ollama", BASE, EMBED, client=client_for(handler))
    client._capabilities[QA] = set()
    with pytest.raises(type(guard_error)) as info:
        client.chat_text(
            [{"role": "user", "content": "?"}],
            model=QA,
            require_complete=True,
            request_guard=guard,
        )
    assert info.value is guard_error
    assert requests == 0


def test_profile_rejects_nonempty_provider_final_that_parses_to_an_empty_public_answer() -> None:
    secret = "private-reasoning-sentinel"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": []})
        return httpx.Response(
            200,
            json={
                "message": {"content": f"{secret}\nAnswer:"},
                "done": True,
                "done_reason": "stop",
            },
        )

    client = Ollama("http://fake-ollama", BASE, EMBED, client=client_for(handler))

    def call_profile():
        try:
            return answer_question(client, "Question?", [("p1", "Source", "Evidence.")], qa_model=QA)
        except TypeError as exc:
            if "qa_model" not in str(exc):
                raise
            return answer_question(client, "Question?", [("p1", "Source", "Evidence.")])

    with pytest.raises(OllamaError, match="empty answer") as info:
        call_profile()
    assert secret not in str(info.value)
    assert prompts.split_answer(f"{secret}\nAnswer:") == (secret, "")


def test_request_guard_covers_selected_model_show_chat_retry_and_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("hippo.ollama.time.sleep", lambda _seconds: None)
    events: list[str] = []
    chats = 0

    def guard() -> None:
        events.append("guard")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal chats
        events.append(request.url.path)
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["thinking"]})
        chats += 1
        if chats == 1:
            return httpx.Response(503, text="retry")
        return httpx.Response(
            200, json={"message": {"content": "final"}, "done": True, "done_reason": "stop"}
        )

    client = Ollama("http://fake-ollama", BASE, EMBED, client=client_for(handler))
    assert (
        client.chat_text(
            [{"role": "user", "content": "?"}], model=QA, require_complete=True, request_guard=guard
        )
        == "final"
    )
    assert events == [
        "guard",
        "/api/show",
        "guard",
        "guard",
        "/api/chat",
        "guard",
        "guard",
        "/api/chat",
        "guard",
    ]


class ProfileServer:
    def __init__(self) -> None:
        self.digest = "a" * 64
        self.calls: list[tuple[str, dict]] = []
        self.phase = ""
        self.revoked = False
        self.outer_revoked = False
        self.chat_attempts = 0
        self.tag_checks = 0

    def authorize(self) -> None:
        if self.revoked:
            raise PermissionError("revoked")

    def outer_authorize(self) -> None:
        if self.outer_revoked:
            raise PermissionError("output revoked")

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}") if request.method == "POST" else {}
        path = request.url.path
        self.calls.append((path, body))
        if path == "/api/tags":
            self.tag_checks += 1
            transient_change = (self.phase, self.tag_checks) in {
                ("profile-chat", 5),
                ("profile-retry", 6),
            }
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": EMBED + ":latest",
                            "model": EMBED + ":latest",
                            "digest": "c" * 64 if transient_change else self.digest,
                        },
                        {"name": QA, "model": QA, "digest": "b" * 64},
                    ]
                },
            )
        if path == "/api/show":
            if body["model"] == QA:
                if self.phase == "show":
                    self.revoked = True
                return httpx.Response(200, json={"capabilities": ["completion", "thinking"]})
            return httpx.Response(
                200,
                json={
                    "capabilities": ["embedding"],
                    "model_info": {"general.architecture": "bert"},
                },
            )
        if path == "/api/embed":
            return httpx.Response(200, json={"model": EMBED + ":latest", "embeddings": [[1, 2, 3]]})
        if path == "/api/chat":
            self.chat_attempts += 1
            if self.phase == "chat":
                self.revoked = True
            if self.phase == "release":
                self.outer_revoked = True
            if self.phase in {"retry", "profile-retry"} and self.chat_attempts == 1:
                return httpx.Response(503, text="retry")
            return httpx.Response(
                200,
                json={"message": {"content": "final"}, "done": True, "done_reason": "stop"},
            )
        raise AssertionError(path)


@pytest.mark.parametrize(
    ("phase", "expected_chats"),
    [("before", 0), ("show", 0), ("chat", 1), ("retry", 1), ("release", 1)],
)
def test_configured_profile_is_not_released_after_wrapper_denial_or_revocation(
    phase: str, expected_chats: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = ProfileServer()
    client = Ollama(
        "http://fake-ollama",
        BASE,
        EMBED,
        qa_model=QA,
        client=client_for(server.handle),
    )
    resolved = resolve_embedding_profile(
        client,
        spec=EmbeddingSpec(query_prefix="Q: ", document_prefix="D: ", dimensions=3),
    )
    profiled = ProfiledEmbeddings(client, resolved, authorization_check=server.authorize)
    guarded = AuthorizedModel(profiled, server.outer_authorize)
    server.calls.clear()
    server.phase = phase
    if phase == "before":
        server.revoked = True
    if phase == "retry":
        monkeypatch.setattr("hippo.ollama.time.sleep", lambda _seconds: setattr(server, "revoked", True))
    with pytest.raises(PermissionError, match="revoked"):
        answer_question(guarded, "Question?", [("p1", "Source", "Evidence.")], qa_model=QA)
    assert server.chat_attempts == expected_chats


@pytest.mark.parametrize("phase", ["profile-chat", "profile-retry"])
def test_complete_qa_preserves_profile_change_and_public_rebuild_classification(
    phase: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = ProfileServer()
    client = Ollama(
        "http://fake-ollama",
        BASE,
        EMBED,
        qa_model=QA,
        client=client_for(server.handle),
    )
    resolved = resolve_embedding_profile(
        client,
        spec=EmbeddingSpec(query_prefix="Q: ", document_prefix="D: ", dimensions=3),
    )
    profiled = ProfiledEmbeddings(client, resolved, authorization_check=server.authorize)
    guarded = AuthorizedModel(profiled, server.outer_authorize)
    server.calls.clear()
    server.tag_checks = 0
    server.phase = phase
    monkeypatch.setattr("hippo.ollama.time.sleep", lambda _seconds: None)

    with pytest.raises(EmbeddingProfileChanged) as info:
        answer_question(guarded, "Question?", [("p1", "Source", "Evidence.")], qa_model=QA)

    failure = public_failure(info.value)
    assert failure is not None
    assert (failure.code, failure.http_status) == ("retrieval_rebuild_required", 409)
    assert server.chat_attempts == 1


def test_answer_from_trace_and_ask_use_configured_profile_but_empty_evidence_calls_nothing(
    ctx: AppContext, sample_text: str, fake_ollama: FakeOllama
) -> None:
    from hippo.hipporag.indexer import Chunk, index_source

    ctx.config = replace(ctx.config, qa_model=BASE)
    source_id = ctx.store.create_source("sample", "Acme Robotics")
    sections = sample_text.split("## ")[1:]
    index_source(
        ctx.store,
        ctx.ollama,
        source_id,
        [
            Chunk(i, section.partition("\n")[0], section.partition("\n")[2])
            for i, section in enumerate(sections)
        ],
    )
    trace, answer = ask(ctx, "Where is Acme Robotics headquartered?")
    assert answer.answer == "Boulder"
    assert len(fake_ollama.calls[-1]["messages"]) == 2
    calls = len(fake_ollama.calls)
    replay = answer_from_trace(ctx, trace)
    assert replay.answer == "Boulder"
    assert len(fake_ollama.calls) == calls + 1
    assert len(fake_ollama.calls[-1]["messages"]) == 2
    calls = len(fake_ollama.calls)
    empty = answer_from_trace(ctx, Trace(question="Anything?", settings={}, graph_version=0))
    assert empty.answer.startswith("I have nothing")
    assert len(fake_ollama.calls) == calls


def test_from_env_constructs_matching_qa_client_and_rejects_mismatched_injection(
    monkeypatch: pytest.MonkeyPatch, tmp_path, store
) -> None:
    monkeypatch.setenv("HIPPO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HIPPO_QA_MODEL", QA)
    monkeypatch.setattr("hippo.context.open_store", lambda _config: store)
    ctx = AppContext.from_env()
    assert ctx.ollama.qa_model == QA
    supplied, _, _ = recorded_ollama(qa_model=None)
    with pytest.raises(ValueError, match="QA model"):
        AppContext.from_env(supplied)
    assert supplied.qa_model is None


def test_explicit_same_base_profile_is_not_reported_as_inherited() -> None:
    configured = Config(llm_model=BASE, qa_model=BASE)
    inherited = Config(llm_model=BASE)
    assert configured.qa_model == BASE
    assert inherited.qa_model is None


def test_cli_settings_distinguishes_inherited_and_configured_qa(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(cli, "_context_or_running_server", lambda: (ctx, None))
    monkeypatch.setattr(cli, "load_config", lambda: replace(ctx.config, qa_model=None))
    assert cli.cmd_settings(SimpleNamespace()) == 0
    assert f"qa_model     = inherited ({BASE}; default reference protocol)" in capsys.readouterr().out
    monkeypatch.setattr(cli, "load_config", lambda: replace(ctx.config, qa_model=QA))
    assert cli.cmd_settings(SimpleNamespace()) == 0
    assert f"qa_model     = {QA} (grounded final-answer profile)" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("llm_model", "qa_model", "embed_model", "expected"),
    [
        (
            "alias-model",
            "alias-model:latest",
            EMBED,
            ("extracting facts", "grounded final answers"),
        ),
        (
            "alias-model:latest",
            "alias-model",
            EMBED,
            ("extracting facts", "grounded final answers"),
        ),
        (BASE, EMBED + ":latest", EMBED, ("grounded final answers", "embeddings")),
    ],
)
def test_settings_page_normalizes_aliases_and_includes_each_shared_role(
    ctx: AppContext,
    llm_model: str,
    qa_model: str,
    embed_model: str,
    expected: tuple[str, ...],
) -> None:
    ctx.config = replace(ctx.config, llm_model=llm_model, qa_model=qa_model, embed_model=embed_model)
    ctx.ollama.llm_model = llm_model
    ctx.ollama.qa_model = qa_model
    ctx.ollama.embed_model = embed_model
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        page = client.get("/settings")
    assert page.status_code == 200
    normalize = lambda name: name.removesuffix(":latest")  # noqa: E731
    qa_row_name = next(
        name for name in ctx.ollama.required_models() if normalize(name) == normalize(qa_model)
    )
    row = page.text.split(f"<code>{qa_row_name}</code>", 1)[1].split("</tr>", 1)[0]
    for label in expected:
        assert label in row


def test_grounded_system_text_has_the_accepted_hash() -> None:
    assert hashlib.sha256(prompts.GROUNDED_QA_SYSTEM.encode()).hexdigest() == (
        "623fc4c74b8e56ffbccd3dc1f8b077021b4377db875bf20618aa099f8e199df7"
    )
