"""Managed model identity against real HTTP client code and disposable vector cache."""

import importlib
import importlib.util
import json
from dataclasses import FrozenInstanceError

import httpx
import numpy as np
import pytest

from hippo.knowledge.embedding_cache import EmbeddingCache, cache_key
from hippo.ollama import Ollama, OllamaError


def api():
    assert importlib.util.find_spec("hippo.knowledge.embedding_profile") is not None, (
        "profile resolver missing"
    )
    return importlib.import_module("hippo.knowledge.embedding_profile")


class Server:
    def __init__(self):
        self.digest = "a" * 64
        self.name = "nomic-embed-text:latest"
        self.calls = []
        self.hook = None
        self.rows = None
        self.models = None
        self.show = {"capabilities": ["embedding"], "model_info": {"general.architecture": "bert"}}
        self.dimension = 3

    def handle(self, request):
        path = request.url.path
        body = json.loads(request.content or "{}")
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
                    else [{"name": self.name, "model": self.name, "digest": self.digest}]
                },
            )
        if path == "/api/show":
            return httpx.Response(200, json=self.show)
        if path == "/api/embed":
            rows = self.rows
            if rows is None:
                rows = [[len(text) + 1] + [2] * (self.dimension - 1) for text in body["input"]]
            return httpx.Response(200, json={"model": self.name, "embeddings": rows})
        raise AssertionError(f"unexpected HTTP request {path}")

    def client(self, name="nomic-embed-text"):
        return Ollama(
            "http://test-ollama",
            "chat",
            name,
            client=httpx.Client(base_url="http://test-ollama", transport=httpx.MockTransport(self.handle)),
        )

    def embeds(self):
        return [body for path, body in self.calls if path == "/api/embed"]


def resolved(server=None, **spec_kwargs):
    module = api()
    server = server or Server()
    client = server.client()
    spec = module.EmbeddingSpec(query_prefix="Q: ", document_prefix="D: ", **spec_kwargs)
    profile = module.resolve_embedding_profile(client, spec=spec)
    return module, server, client, profile


def test_resolver_captures_actual_dimension_and_explicit_probe_request():
    module = api()
    server = Server()
    client = server.client()
    client._embedding_dim = 999
    profile = module.resolve_embedding_profile(
        client,
        spec=module.EmbeddingSpec(
            query_prefix="Q: ", document_prefix="D: ", options_json='{"num_ctx":256}', dimensions=3
        ),
    )
    assert profile.profile.model_digest == "a" * 64
    assert profile.profile.dimension == 3
    assert profile.profile.model == "nomic-embed-text"
    assert profile.wire_model == "nomic-embed-text:latest"
    assert len(profile.fingerprint) == 64
    assert server.embeds() == [
        {
            "model": server.name,
            "input": ["D: hippo embedding profile probe v1"],
            "options": {"num_ctx": 256},
            "dimensions": 3,
            "truncate": False,
            "keep_alive": "15m",
        }
    ]
    assert client._embedding_dim == 999


@pytest.mark.parametrize("digest", [None, "latest", "f" * 63, True, "G" * 64])
def test_unknown_digest_never_probes(digest):
    module = api()
    server = Server()
    server.digest = digest
    with pytest.raises(module.EmbeddingProfileUnavailable):
        module.resolve_embedding_profile(server.client(), spec=module.EmbeddingSpec())
    assert not server.embeds()


@pytest.mark.parametrize("name", ["other/nomic-embed-text:latest", "nomic-embed-text:v2"])
def test_related_model_name_is_not_a_match(name):
    module = api()
    server = Server()
    server.name = name
    with pytest.raises(module.EmbeddingProfileUnavailable):
        module.resolve_embedding_profile(server.client(), spec=module.EmbeddingSpec())


def test_registry_port_does_not_count_as_model_tag():
    module = api()
    server = Server()
    server.name = "localhost:5000/team/model:latest"
    profile = module.resolve_embedding_profile(
        server.client("localhost:5000/team/model"), spec=module.EmbeddingSpec()
    )
    assert profile.wire_model == server.name


def test_conflicting_duplicate_model_entries_are_rejected():
    module = api()
    server = Server()
    server.models = [{"name": server.name, "digest": value * 64} for value in ("a", "b")]
    with pytest.raises(module.EmbeddingProfileUnavailable):
        module.resolve_embedding_profile(server.client(), spec=module.EmbeddingSpec())


@pytest.mark.parametrize("show", [[], {"capabilities": ["completion"]}, {"model_info": []}])
def test_bad_show_or_nonembedding_capability_is_not_ignored(show):
    module = api()
    server = Server()
    server.show = show
    with pytest.raises(module.EmbeddingProfileUnavailable):
        module.resolve_embedding_profile(server.client(), spec=module.EmbeddingSpec())
    assert not server.embeds()


def test_show_hidden_width_is_not_output_dimension_override():
    server = Server()
    server.show = {"model_info": {"general.architecture": "bert", "bert.embedding_length": 1024}}
    _, _, _, profile = resolved(server, dimensions=3)
    assert profile.profile.dimension == 3


@pytest.mark.parametrize("rows", [[], [[1, 2]], [[1, True, 3]], [["1", 2, 3]], [[0, 0, 0]], [[1e100, 2, 3]]])
def test_invalid_probe_output_rejects(rows):
    module = api()
    server = Server()
    server.rows = rows
    with pytest.raises(module.EmbeddingProfileUnavailable):
        module.resolve_embedding_profile(server.client(), spec=module.EmbeddingSpec(dimensions=3))


@pytest.mark.parametrize("phase", ["/api/show", "/api/embed"])
def test_same_tag_digest_drift_during_resolution_rejects(phase):
    module = api()
    server = Server()
    server.hook = lambda path, body: setattr(server, "digest", "b" * 64) if path == phase else None
    with pytest.raises(module.EmbeddingProfileChanged):
        module.resolve_embedding_profile(server.client(), spec=module.EmbeddingSpec())


def test_spec_identity_tracks_both_prefixes_options_and_dimension():
    module, server, client, first = resolved(options_json='{"num_ctx":256,"seed":1}')
    same = module.resolve_embedding_profile(
        client,
        spec=module.EmbeddingSpec(
            query_prefix="Q: ", document_prefix="D: ", options_json='{"seed":1,"num_ctx":256}'
        ),
    )
    assert same.fingerprint == first.fingerprint
    specs = [
        module.EmbeddingSpec(query_prefix="changed", document_prefix="D: "),
        module.EmbeddingSpec(query_prefix="Q: ", document_prefix="changed"),
        module.EmbeddingSpec(query_prefix="Q: ", document_prefix="D: ", dimensions=3),
    ]
    assert all(
        module.resolve_embedding_profile(client, spec=s).fingerprint != first.fingerprint for s in specs
    )
    server.digest = "b" * 64
    assert module.resolve_embedding_profile(client, spec=same.spec).fingerprint != first.fingerprint


@pytest.mark.parametrize(
    "kwargs",
    [
        {"dimensions": True},
        {"dimensions": 0},
        {"options_json": '{"x":NaN}'},
        {"options_json": '{"x":1,"x":2}'},
        {"options_json": "[]"},
        {"normalization": "unknown"},
        {"truncate": True},
    ],
)
def test_spec_rejects_unsupported_or_ambiguous_semantics(kwargs):
    with pytest.raises(ValueError):
        api().EmbeddingSpec(**kwargs)


def test_cached_adapter_uses_exact_kind_prefixes_batches_and_return_order(tmp_path):
    module, server, client, profile = resolved()
    adapter = module.ProfiledEmbeddings(client, profile, cache=EmbeddingCache(tmp_path))
    server.calls.clear()
    first = adapter.embed(["longer", "a", "longer"], batch_size=1)
    assert first.dtype == np.float32 and first.shape == (3, 3)
    assert np.allclose(first[0], first[2]) and not np.allclose(first[0], first[1])
    assert np.allclose(np.linalg.norm(first, axis=1), 1)
    assert [r["input"] for r in server.embeds()] == [["D: longer"], ["D: a"]]
    server.calls.clear()
    assert np.array_equal(adapter.embed(["longer", "a", "longer"]), first)
    assert not server.embeds()
    assert len(server.calls) >= 2  # Full hits still verify remote identity.
    adapter.embed_one("a")
    assert server.embeds()[0]["input"] == ["Q: a"]
    assert adapter.embedding_dim() == 3
    assert adapter.embed([]).shape == (0, 3)


@pytest.mark.parametrize("error", [False, True])
def test_digest_change_during_http_success_or_failure_never_caches(tmp_path, error):
    module, server, client, profile = resolved()

    def change(path, body):
        if path == "/api/embed":
            server.digest = "b" * 64
            if error:
                return httpx.Response(400, json={"error": "failed"})

    server.hook = change
    adapter = module.ProfiledEmbeddings(client, profile, cache=EmbeddingCache(tmp_path))
    with pytest.raises(module.EmbeddingProfileChanged):
        adapter.embed(["secret"])
    assert not list(tmp_path.iterdir())


def test_digest_change_on_full_cache_hit_is_rejected(tmp_path):
    module, server, client, profile = resolved()
    cache = EmbeddingCache(tmp_path)
    adapter = module.ProfiledEmbeddings(client, profile, cache=cache)
    adapter.embed(["cached"])
    original = cache.get

    def change(key):
        row = original(key)
        server.digest = "b" * 64
        return row

    cache.get = change
    server.calls.clear()
    with pytest.raises(module.EmbeddingProfileChanged):
        adapter.embed(["cached"])
    assert not server.embeds()


@pytest.mark.parametrize("attribute,value", [("embed_model", "other"), ("base_url", "http://other")])
def test_local_client_identity_change_rejects_before_dispatch(attribute, value):
    module, server, client, profile = resolved()
    adapter = module.ProfiledEmbeddings(client, profile)
    setattr(client, attribute, value)
    server.calls.clear()
    with pytest.raises(module.EmbeddingProfileChanged):
        adapter.embed(["secret"])
    assert not server.calls


def test_authorization_revocation_during_http_error_wins(tmp_path):
    module, server, client, profile = resolved()
    revoked = False

    def authorize():
        if revoked:
            raise PermissionError("revoked")

    def revoke(path, body):
        nonlocal revoked
        if path == "/api/embed":
            revoked = True
            return httpx.Response(400, json={"error": "failed"})

    server.hook = revoke
    adapter = module.ProfiledEmbeddings(
        client, profile, cache=EmbeddingCache(tmp_path), authorization_check=authorize
    )
    with pytest.raises(PermissionError, match="revoked"):
        adapter.embed(["secret"])
    assert not list(tmp_path.iterdir())


def test_model_error_with_stable_identity_remains_model_error():
    module, server, client, profile = resolved()
    server.hook = lambda path, body: (
        httpx.Response(400, json={"error": "failed"}) if path == "/api/embed" else None
    )
    with pytest.raises(OllamaError):
        module.ProfiledEmbeddings(client, profile).embed(["input"])


def test_cache_nonunit_row_is_normalized_without_rewriting(tmp_path):
    module, server, client, profile = resolved()
    cache = EmbeddingCache(tmp_path)
    key = cache_key(profile.profile, "cached")
    cache.put(key, np.array([3, 4, 0], dtype=np.float32))
    server.calls.clear()
    result = module.ProfiledEmbeddings(client, profile, cache=cache).embed(["cached"])
    assert np.allclose(result, [[0.6, 0.8, 0]])
    assert np.array_equal(cache.get(key), [3, 4, 0])
    assert not server.embeds()


def test_normalization_uses_original_precision_before_final_float32_cast():
    module, server, client, profile = resolved()
    values = [0.8515680698511308, 0.8369613232370445, 0.05143876747525933]
    server.rows = [values]
    result = module.ProfiledEmbeddings(client, profile).embed_one("precision")
    raw = np.array(values, dtype=np.float64)
    expected = (raw / np.linalg.norm(raw)).astype(np.float32)
    assert np.array_equal(result, expected)


@pytest.mark.parametrize("phase", ["get", "put"])
def test_cache_error_cannot_swallow_model_identity_drift(tmp_path, phase):
    module, server, client, profile = resolved()
    cache = EmbeddingCache(tmp_path)

    def fail(*args):
        server.digest = "b" * 64
        raise OSError("disk failed")

    setattr(cache, phase, fail)
    with pytest.raises(module.EmbeddingProfileChanged):
        module.ProfiledEmbeddings(client, profile, cache=cache).embed(["value"])


def test_cache_write_omission_retains_verified_vector(tmp_path, monkeypatch):
    module, _, client, profile = resolved()
    monkeypatch.setattr(
        "hippo.knowledge.embedding_cache.os.replace", lambda *args: (_ for _ in ()).throw(OSError())
    )
    result = module.ProfiledEmbeddings(client, profile, cache=EmbeddingCache(tmp_path)).embed(["input"])
    assert result.shape == (1, 3) and np.isfinite(result).all()


def test_second_http_batch_drift_rejects_all_uncached_rows(tmp_path):
    module, server, client, profile = resolved()
    embeds = 0

    def change(path, body):
        nonlocal embeds
        if path == "/api/embed":
            embeds += 1
            if embeds == 2:
                server.digest = "b" * 64

    server.hook = change
    with pytest.raises(module.EmbeddingProfileChanged):
        module.ProfiledEmbeddings(client, profile, cache=EmbeddingCache(tmp_path)).embed(
            ["one", "two"], batch_size=1
        )
    assert embeds == 2 and not list(tmp_path.iterdir())


def test_final_metadata_failure_rejects_computed_vectors(tmp_path):
    module, server, client, profile = resolved()
    computed = False

    def fail(path, body):
        nonlocal computed
        if path == "/api/embed":
            computed = True
        if path == "/api/tags" and computed:
            return httpx.Response(400, json={"error": "metadata offline"})

    server.hook = fail
    with pytest.raises(OllamaError):
        module.ProfiledEmbeddings(client, profile, cache=EmbeddingCache(tmp_path)).embed(["one"])
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("path", ["/api/tags", "/api/show", "/api/embed"])
def test_resolution_rejects_nonfinite_or_duplicate_wire_json(path):
    module = api()
    server = Server()
    server.hook = lambda seen, body: httpx.Response(200, content=b'{"x":1,"x":2}') if seen == path else None
    with pytest.raises(module.EmbeddingProfileUnavailable):
        module.resolve_embedding_profile(server.client(), spec=module.EmbeddingSpec())


def test_specs_and_resolved_profiles_are_frozen():
    _, _, _, profile = resolved()
    with pytest.raises(FrozenInstanceError):
        profile.spec.document_prefix = "changed"
    with pytest.raises(FrozenInstanceError):
        profile.fingerprint = "changed"


def test_replacing_http_client_is_detected_even_with_same_endpoint():
    module, server, client, profile = resolved()
    adapter = module.ProfiledEmbeddings(client, profile)
    client.client = server.client().client
    server.calls.clear()
    with pytest.raises(module.EmbeddingProfileChanged):
        adapter.embed_one("input")
    assert not server.calls


@pytest.mark.parametrize("method", ["chat_text", "chat_json"])
def test_explicit_chat_forwarding_rechecks_identity_on_success_and_error(method, monkeypatch):
    module, server, client, profile = resolved()
    adapter = module.ProfiledEmbeddings(client, profile)
    calls = []

    def chat(*args, **kwargs):
        calls.append((args, kwargs))
        return {"answer": "ok"} if method == "chat_json" else "ok"

    monkeypatch.setattr(client, method, chat)
    assert getattr(adapter, method)(["messages"], temperature=0) == (
        {"answer": "ok"} if method == "chat_json" else "ok"
    )
    assert len(calls) == 1 and calls[0][0] == (["messages"],)
    assert calls[0][1]["temperature"] == 0
    assert calls[0][1]["request_guard"] == adapter.validate

    def change(*args, **kwargs):
        server.digest = "b" * 64
        raise OllamaError("chat failed")

    monkeypatch.setattr(client, method, change)
    with pytest.raises(module.EmbeddingProfileChanged):
        getattr(adapter, method)(["messages"])


def test_preexisting_revocation_prevents_even_metadata_dispatch():
    module, server, client, profile = resolved()
    server.calls.clear()

    def deny():
        raise PermissionError("denied")

    with pytest.raises(PermissionError):
        module.resolve_embedding_profile(client, spec=profile.spec, authorization_check=deny)
    assert not server.calls


@pytest.mark.parametrize("attribute", ["resolved", "embed_model", "ollama"])
def test_adapter_captured_identity_is_read_only(attribute):
    module, server, client, profile = resolved()
    adapter = module.ProfiledEmbeddings(client, profile)
    server.digest = "b" * 64
    other = module.resolve_embedding_profile(client, spec=profile.spec)
    replacement = {"resolved": other, "embed_model": "other", "ollama": server.client()}[attribute]
    with pytest.raises(AttributeError):
        setattr(adapter, attribute, replacement)
    with pytest.raises(module.EmbeddingProfileChanged):
        adapter.embed(["input"])


def test_persistable_descriptor_omits_client_and_endpoint_and_returns_copies():
    _, _, _, profile = resolved(options_json='{"num_ctx":256}')
    descriptor = profile.descriptor()
    assert set(descriptor) == {"profile_schema", "profile", "spec", "fingerprint"}
    assert descriptor["profile"]["model_digest"] == "a" * 64
    encoded = json.dumps(descriptor, allow_nan=False)
    assert "test-ollama" not in encoded and "_client" not in encoded and "endpoint" not in encoded
    descriptor["profile"]["model_digest"] = "changed"
    descriptor["spec"]["query_prefix"] = "changed"
    assert profile.descriptor()["profile"]["model_digest"] == "a" * 64
    assert profile.descriptor()["spec"]["query_prefix"] == "Q: "


def test_normalization_handles_large_and_small_float32_representable_inputs():
    module, server, client, profile = resolved()
    adapter = module.ProfiledEmbeddings(client, profile)
    for values in ([3e38, -3e38, 1e-38], [1e-40, 2e-40, -1e-40]):
        server.rows = [values]
        row = adapter.embed_one("range")
        assert row.dtype == np.float32 and np.isfinite(row).all()
        assert np.allclose(np.linalg.norm(row), 1)


def test_transient_http_error_does_not_retry_after_authorization_revocation(monkeypatch):
    module, server, client, profile = resolved()
    monkeypatch.setattr("hippo.ollama.time.sleep", lambda _: None)
    revoked = False
    attempts = 0

    def authorize():
        if revoked:
            raise PermissionError("revoked")

    def fail(path, body):
        nonlocal revoked, attempts
        if path == "/api/embed":
            attempts += 1
            revoked = True
            return httpx.Response(500, json={"error": "temporary failure"})

    server.hook = fail
    adapter = module.ProfiledEmbeddings(client, profile, authorization_check=authorize)
    with pytest.raises(PermissionError, match="revoked"):
        adapter.embed(["private input"])
    assert attempts == 1


@pytest.mark.parametrize("method", ["chat_text", "chat_json"])
@pytest.mark.parametrize("failure", ["http", "transport", "timeout"])
def test_chat_attempt_does_not_resend_after_revocation(method, failure, monkeypatch):
    module, server, client, profile = resolved()
    monkeypatch.setattr("hippo.ollama.time.sleep", lambda _: None)
    revoked = False
    attempts = 0

    def authorize():
        if revoked:
            raise PermissionError("revoked")

    def fail(path, body):
        nonlocal revoked, attempts
        if path == "/api/chat":
            attempts += 1
            revoked = True
            if failure == "transport":
                raise httpx.ConnectError("connection failed")
            if failure == "timeout":
                raise httpx.ReadTimeout("read failed")
            return httpx.Response(500, json={"error": "temporary failure"})

    server.hook = fail
    adapter = module.ProfiledEmbeddings(client, profile, authorization_check=authorize)
    args = ([{"role": "user", "content": "private prompt"}],)
    if method == "chat_json":
        args += ({"type": "object"},)
    with pytest.raises(PermissionError, match="revoked"):
        getattr(adapter, method)(*args)
    assert attempts == 1


@pytest.mark.parametrize("method", ["chat_text", "chat_json"])
def test_chat_capability_failure_does_not_swallow_identity_change(method, monkeypatch):
    module, server, client, profile = resolved()
    monkeypatch.setattr("hippo.ollama.time.sleep", lambda _: None)

    def change(path, body):
        if path == "/api/show" and body["model"] == "chat":
            server.digest = "b" * 64
            return httpx.Response(500, json={"error": "temporary failure"})
        if path == "/api/chat":
            return httpx.Response(200, json={"message": {"content": "{}"}})

    server.hook = change
    server.calls.clear()
    adapter = module.ProfiledEmbeddings(client, profile)
    args = ([{"role": "user", "content": "private prompt"}],)
    if method == "chat_json":
        args += ({"type": "object"},)
    with pytest.raises(module.EmbeddingProfileChanged):
        getattr(adapter, method)(*args)
    assert not [path for path, body in server.calls if path == "/api/chat"]
    assert len([path for path, body in server.calls if path == "/api/show"]) == 1


def test_chat_rechecks_authorization_before_next_retry_without_shared_client_mutation(monkeypatch):
    module, server, client, profile = resolved()
    revoked = False
    attempts = 0

    def authorize():
        if revoked:
            raise PermissionError("revoked")

    def sleep(_):
        nonlocal revoked
        revoked = True

    def fail(path, body):
        nonlocal attempts
        if path == "/api/chat":
            attempts += 1
            return httpx.Response(
                500 if attempts == 1 else 200, json={"message": {"content": "legacy reply"}}
            )

    server.hook = fail
    monkeypatch.setattr("hippo.ollama.time.sleep", sleep)
    adapter = module.ProfiledEmbeddings(client, profile, authorization_check=authorize)
    with pytest.raises(PermissionError, match="revoked"):
        adapter.chat_text([{"role": "user", "content": "managed prompt"}])
    assert attempts == 1
    # The guarded request never installed authorization state on the shared client.
    assert client.chat_text([{"role": "user", "content": "independent legacy call"}]) == "legacy reply"
    assert attempts == 2
