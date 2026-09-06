"""
hippo/ollama.py: the small HTTP client for Ollama, tested against FakeOllama.

Every request goes through an httpx MockTransport, so we can also wrap the fake
to record what was sent (prefixes, schema, options) and to inject failures.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import numpy as np
import pytest

from hippo import prompts
from hippo.ollama import EMBED_PREFIXES, Ollama, OllamaError, parse_json_object
from tests.fakes.fake_ollama import DIM, FakeOllama

LLM = "qwen3:8b"
EMBED = "nomic-embed-text"


class Recorder:
    """Wraps FakeOllama.handle and keeps every (path, body) it saw."""

    def __init__(self, fake: FakeOllama):
        self.fake = fake
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}") if request.method == "POST" else {}
        self.requests.append((request.url.path, body))
        return self.fake.handle(request)

    def bodies(self, path: str) -> list[dict[str, Any]]:
        return [body for seen_path, body in self.requests if seen_path == path]


def client_for(handler) -> httpx.Client:
    return httpx.Client(base_url="http://fake-ollama", transport=httpx.MockTransport(handler))


@pytest.fixture
def recorder(fake_ollama: FakeOllama) -> Recorder:
    return Recorder(fake_ollama)


@pytest.fixture
def recorded(recorder: Recorder) -> Ollama:
    return Ollama("http://fake-ollama", LLM, EMBED, client=client_for(recorder))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """The retry loop sleeps between attempts; tests should not."""
    monkeypatch.setattr("hippo.ollama.time.sleep", lambda seconds: None)


# ------------------------------------------------------------------ embeddings


def test_embed_returns_unit_length_float32_rows(ollama: Ollama) -> None:
    matrix = ollama.embed(["Acme Robotics", "Boulder", "a longer sentence about robots"])
    assert matrix.shape == (3, DIM)
    assert matrix.dtype == np.float32
    assert np.allclose(np.linalg.norm(matrix, axis=1), 1.0, atol=1e-5)


def test_embed_one_returns_a_single_vector(ollama: Ollama) -> None:
    vector = ollama.embed_one("Where is Boulder?")
    assert vector.shape == (DIM,)


def test_embed_empty_list_returns_zero_rows_with_the_right_width(ollama: Ollama) -> None:
    assert ollama.embed([]).shape == (0, DIM)


def test_embedding_dim_is_discovered_by_probing_once(recorded: Ollama, recorder: Recorder) -> None:
    assert recorded.embedding_dim() == DIM
    assert recorded.embedding_dim() == DIM
    assert len(recorder.bodies("/api/embed")) == 1


def test_embed_adds_the_query_and_document_prefixes_for_nomic(recorded: Ollama, recorder: Recorder) -> None:
    query_prefix, doc_prefix = EMBED_PREFIXES["nomic-embed-text"]
    recorded.embed(["hello"], kind="query")
    recorded.embed(["hello"], kind="document")
    sent = [body["input"] for body in recorder.bodies("/api/embed")]
    assert sent == [[query_prefix + "hello"], [doc_prefix + "hello"]]


def test_embed_prefix_lookup_ignores_the_model_tag(recorder: Recorder) -> None:
    client = Ollama("http://fake-ollama", LLM, "nomic-embed-text:latest", client=client_for(recorder))
    client.embed(["hello"], kind="query")
    assert recorder.bodies("/api/embed")[0]["input"] == ["search_query: hello"]


def test_embed_sends_no_prefix_for_models_that_do_not_want_one() -> None:
    fake = FakeOllama(installed=[LLM, "bge-m3:latest"])
    recorder = Recorder(fake)
    client = Ollama("http://fake-ollama", LLM, "bge-m3", client=client_for(recorder))
    client.embed(["hello"], kind="query")
    assert recorder.bodies("/api/embed")[0]["input"] == ["hello"]


def test_embed_splits_long_lists_into_batches(recorded: Ollama, recorder: Recorder) -> None:
    matrix = recorded.embed([f"text {i}" for i in range(5)], batch_size=2)
    assert matrix.shape == (5, DIM)
    assert [len(body["input"]) for body in recorder.bodies("/api/embed")] == [2, 2, 1]


def test_embed_with_a_missing_embedding_model_raises(fake_ollama: FakeOllama) -> None:
    client = Ollama("http://fake-ollama", LLM, "no-such-embedder", client=fake_ollama.client())
    with pytest.raises(OllamaError, match="is the model installed"):
        client.embed(["hello"])


# ------------------------------------------------------------------------ chat


def test_chat_json_parses_the_reply_into_a_dict(ollama: Ollama) -> None:
    reply = ollama.chat_json(prompts.ner_messages("Acme Robotics is located in Boulder."), prompts.NER_SCHEMA)
    assert reply == {"named_entities": ["Acme Robotics", "Boulder"]}


def test_chat_json_sends_the_schema_and_generation_options(recorded: Ollama, recorder: Recorder) -> None:
    recorded.chat_json(prompts.ner_messages("Boulder."), prompts.NER_SCHEMA, max_tokens=99, temperature=0.3)
    (body,) = recorder.bodies("/api/chat")
    assert body["model"] == LLM
    assert body["format"] == prompts.NER_SCHEMA
    assert body["stream"] is False
    assert body["options"] == {"temperature": 0.3, "num_ctx": 8192, "num_predict": 99}
    # qwen3 reports the "thinking" capability, so we ask Ollama to skip the monologue.
    assert body["think"] is False


def test_chat_text_returns_plain_text_without_a_format(recorded: Ollama, recorder: Recorder) -> None:
    text = recorded.chat_text([{"role": "user", "content": "hi"}])
    assert "fake model" in text
    (body,) = recorder.bodies("/api/chat")
    assert "format" not in body
    assert "num_predict" not in body["options"]


def test_chat_strips_a_think_block_from_the_reply() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion"]})
        content = '<think>let me think...\nmore</think>\n{"answer": 42}'
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})

    client = Ollama("http://fake-ollama", LLM, EMBED, client=client_for(handler))
    assert client.chat_text([{"role": "user", "content": "?"}]) == '{"answer": 42}'
    assert client.chat_json([{"role": "user", "content": "?"}], {}) == {"answer": 42}


def test_chat_with_a_missing_llm_raises_a_friendly_error(fake_ollama: FakeOllama) -> None:
    client = Ollama("http://fake-ollama", "missing:1b", EMBED, client=fake_ollama.client())
    with pytest.raises(OllamaError, match="is the model installed"):
        client.chat_text([{"role": "user", "content": "hi"}])


def test_model_capabilities_are_looked_up_once(recorded: Ollama, recorder: Recorder) -> None:
    recorded.chat_text([{"role": "user", "content": "one"}])
    recorded.chat_text([{"role": "user", "content": "two"}])
    assert len(recorder.bodies("/api/show")) == 1


# ------------------------------------------------------------ parse_json_object


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ('  {"a": 1}\n', {"a": 1}),
        ('Sure! Here you go: {"a": 1} Hope that helps.', {"a": 1}),
        ('<think>hmm, tricky</think>{"a": 1}', {"a": 1}),
        ('<think>\nmulti\nline\n</think>\nAnswer: {"fact": [["s", "p", "o"]]}', {"fact": [["s", "p", "o"]]}),
        ('[1, 2] then {"b": [1, {"c": 2}]}', {"b": [1, {"c": 2}]}),
        ('{not json} but {"ok": true}', {"ok": True}),
    ],
)
def test_parse_json_object_rescues_the_first_object(text: str, expected: dict) -> None:
    assert parse_json_object(text) == expected


@pytest.mark.parametrize("text", ["", "no json here", "[1, 2, 3]", "<think>only thoughts</think>", "{"])
def test_parse_json_object_raises_when_there_is_no_object(text: str) -> None:
    with pytest.raises(OllamaError, match="did not return a JSON object"):
        parse_json_object(text)


# ---------------------------------------------------------------------- models


def test_installed_and_missing_models(ollama: Ollama) -> None:
    assert ollama.installed_models() == [LLM, "nomic-embed-text:latest"]
    assert ollama.required_models() == [LLM, EMBED]
    assert ollama.missing_models() == []


def test_missing_models_lists_what_is_not_installed() -> None:
    fake = FakeOllama(installed=[LLM])
    client = Ollama("http://fake-ollama", LLM, EMBED, client=fake.client())
    assert client.missing_models() == [EMBED]


def test_has_model_treats_latest_as_the_default_tag() -> None:
    fake = FakeOllama(installed=["qwen3:8b", "nomic-embed-text:latest"])
    client = Ollama("http://fake-ollama", LLM, EMBED, client=fake.client())
    assert client.has_model("nomic-embed-text")
    assert client.has_model("nomic-embed-text:latest")
    assert client.has_model("qwen3:8b")
    assert not client.has_model("qwen3")  # "qwen3" means "qwen3:latest", which is not installed
    assert not client.has_model("llama3")


def test_ensure_model_pulls_a_missing_model_and_reports_progress() -> None:
    fake = FakeOllama(installed=[LLM])
    client = Ollama("http://fake-ollama", LLM, EMBED, client=fake.client())
    events: list[dict] = []

    client.ensure_model(EMBED, on_progress=events.append)

    assert fake.installed == [LLM, "nomic-embed-text:latest"]
    assert [e["status"] for e in events] == ["pulling manifest", "downloading", "downloading", "success"]
    assert events[1] == {"status": "downloading", "completed": 50, "total": 100}
    assert client.missing_models() == []


def test_ensure_model_does_nothing_when_already_installed(recorded: Ollama, recorder: Recorder) -> None:
    recorded.ensure_model(LLM)
    assert recorder.bodies("/api/pull") == []
    assert recorder.fake.installed == [LLM, "nomic-embed-text:latest"]


def test_ensure_model_raises_when_the_pull_reports_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        lines = [{"status": "pulling manifest"}, {"error": "pull model manifest: file does not exist"}]
        return httpx.Response(200, content="\n".join(json.dumps(line) for line in lines).encode())

    client = Ollama("http://fake-ollama", LLM, EMBED, client=client_for(handler))
    with pytest.raises(OllamaError, match="could not pull"):
        client.ensure_model("nope:1b")


def test_pull_raises_on_a_non_200_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = Ollama("http://fake-ollama", LLM, EMBED, client=client_for(handler))
    with pytest.raises(OllamaError, match="could not pull"):
        list(client.pull("nope:1b"))


# ---------------------------------------------------------------------- retries


class Flaky:
    """Fails the first `failures` requests (with a 5xx or an exception), then hands over to FakeOllama."""

    def __init__(self, fake: FakeOllama, failures: int, error: Exception | None = None):
        self.fake = fake
        self.failures = failures
        self.error = error
        self.attempts = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.attempts += 1
        if self.attempts <= self.failures:
            if self.error is not None:
                raise self.error
            return httpx.Response(503, text="server overloaded")
        return self.fake.handle(request)


def test_a_request_is_retried_after_two_5xx_replies(fake_ollama: FakeOllama) -> None:
    flaky = Flaky(fake_ollama, failures=2)
    client = Ollama("http://fake-ollama", LLM, EMBED, client=client_for(flaky))
    assert client.installed_models() == [LLM, "nomic-embed-text:latest"]
    assert flaky.attempts == 3


def test_three_5xx_replies_in_a_row_give_up_with_a_clear_error(fake_ollama: FakeOllama) -> None:
    flaky = Flaky(fake_ollama, failures=3)
    client = Ollama("http://fake-ollama", LLM, EMBED, client=client_for(flaky))
    with pytest.raises(OllamaError, match="is not answering"):
        client.installed_models()
    assert flaky.attempts == 3


def test_network_errors_are_retried_too(fake_ollama: FakeOllama) -> None:
    flaky = Flaky(fake_ollama, failures=1, error=httpx.ConnectError("connection refused"))
    client = Ollama("http://fake-ollama", LLM, EMBED, client=client_for(flaky))
    assert client.embed(["hello"]).shape == (1, DIM)
    assert flaky.attempts == 2


def test_4xx_replies_other_than_404_are_not_retried() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, text="bad request")

    client = Ollama("http://fake-ollama", LLM, EMBED, client=client_for(handler))
    with pytest.raises(OllamaError, match="HTTP 400"):
        client.installed_models()
    assert attempts == 1


# ---------------------------------------------------------------------- status


def test_is_up_is_true_for_the_fake(ollama: Ollama) -> None:
    assert ollama.is_up()


def test_is_up_is_false_when_the_server_cannot_be_reached() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = Ollama("http://fake-ollama", LLM, EMBED, client=client_for(handler))
    assert not client.is_up()


def test_base_url_loses_its_trailing_slash(fake_ollama: FakeOllama) -> None:
    client = Ollama("http://fake-ollama/", LLM, EMBED, client=fake_ollama.client())
    assert client.base_url == "http://fake-ollama"


# --------------------------------------------------------------- timeouts


def test_a_read_timeout_is_not_retried_and_names_the_knob_to_raise() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        raise httpx.ReadTimeout("the model is still thinking", request=request)

    client = Ollama("http://fake-ollama", LLM, EMBED, client=client_for(handler), timeout_seconds=42)
    with pytest.raises(OllamaError, match="HIPPO_LLM_TIMEOUT") as info:
        client.chat_text([{"role": "user", "content": "hi"}])

    assert "42s" in str(info.value) and "/api/chat" in str(info.value)
    # One capability lookup (which swallows its own timeout), one chat: no retries of either.
    assert paths == ["/api/show", "/api/chat"]


def test_a_connect_timeout_is_still_retried(fake_ollama: FakeOllama) -> None:
    flaky = Flaky(fake_ollama, failures=1, error=httpx.ConnectTimeout("slow to connect"))
    client = Ollama("http://fake-ollama", LLM, EMBED, client=client_for(flaky))
    assert client.embed(["hello"]).shape == (1, DIM)
    assert flaky.attempts == 2


def test_the_default_client_waits_long_for_replies_but_not_to_connect() -> None:
    client = Ollama("http://fake-ollama", LLM, EMBED, timeout_seconds=123)
    assert client.client.timeout.read == 123
    assert client.client.timeout.connect == 10.0
    assert client.timeout_seconds == 123


def test_a_stalled_pull_raises_instead_of_hanging_forever() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no bytes for a long time", request=request)

    client = Ollama("http://fake-ollama", LLM, EMBED, client=client_for(handler))
    with pytest.raises(OllamaError, match="stopped sending data"):
        list(client.pull("nope:1b"))


def test_a_pull_that_cannot_connect_raises_an_ollama_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = Ollama("http://fake-ollama", LLM, EMBED, client=client_for(handler))
    with pytest.raises(OllamaError, match="could not pull"):
        list(client.pull("nope:1b"))
