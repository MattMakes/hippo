"""Disposable embedding reuse, independent of stores and a live model server."""

import hashlib
import json
from dataclasses import FrozenInstanceError, replace

import numpy as np
import pytest


@pytest.fixture
def ec():
    from hippo.knowledge import embedding_cache

    return embedding_cache


@pytest.fixture
def profile(ec):
    return ec.EmbeddingProfile(
        model="nomic-embed-text:latest",
        model_digest="sha256:" + "a" * 64,
        dimension=3,
        preprocessing_version="ollama-prefix-rules-v1",
        normalization_options_fingerprint="float32-l2;options={}",
    )


class Model:
    embed_model = "nomic-embed-text:latest"

    def __init__(self):
        self.calls = []

    def embed(self, texts, kind="document", batch_size=32):
        self.calls.append((list(texts), kind, batch_size))
        vectors = np.array([[len(t) + 1, sum(t.encode()) % 19 + 1, 1] for t in texts], dtype=np.float32)
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def test_hit_skips_model_preserves_order_and_isolates_arrays(ec, profile, tmp_path):
    model = Model()
    cache = ec.EmbeddingCache(tmp_path)
    expected = ec.cached_embed(model, ["a", "bbb", "a"], profile=profile, cache=cache)
    assert model.calls == [(["a", "bbb"], "document", 32)]
    np.testing.assert_array_equal(expected[0], expected[2])
    first = ec.cached_embed(model, ["a", "bbb", "a"], profile=profile, cache=cache)
    first[0, 0] = 99
    assert first[2, 0] != 99
    actual = ec.cached_embed(model, ["a", "ccc", "bbb", "ccc"], profile=profile, cache=cache, batch_size=8)
    assert model.calls[-1] == (["ccc"], "document", 8)
    assert len(model.calls) == 2
    np.testing.assert_array_equal(actual[[0, 2]], expected[[0, 1]])
    np.testing.assert_array_equal(actual[1], actual[3])
    key = ec.cache_key(profile, "a")
    cache.get(key)[0] = 77
    np.testing.assert_array_equal(cache.get(key), expected[0])


@pytest.mark.parametrize(
    "change", ["text", "kind", "model", "digest", "dimension", "preprocessing", "options"]
)
def test_changed_inputs_miss(ec, profile, tmp_path, change):
    model = Model()
    cache = ec.EmbeddingCache(tmp_path)
    ec.cached_embed(model, ["a"], profile=profile, cache=cache)
    original = ec.cache_key(profile, "a")
    text, kind = "a", "document"
    if change == "text":
        text = "a "
    elif change == "kind":
        kind = "query"
    elif change == "model":
        profile = replace(profile, model="other:latest")
    elif change == "digest":
        profile = replace(profile, model_digest="sha256:" + "b" * 64)
    elif change == "dimension":
        profile = replace(profile, dimension=4)
    elif change == "preprocessing":
        profile = replace(profile, preprocessing_version="v2")
    else:
        profile = replace(profile, normalization_options_fingerprint="float32-l2;options={truncate:false}")
    key = ec.cache_key(profile, text, kind=kind)
    assert key != original
    assert cache.get(key) is None


def test_utf8_identity_and_no_plaintext_payload(ec, profile, tmp_path):
    text = "private passage é\r\n"
    key = ec.cache_key(profile, text)
    assert key.input_hash == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert key != ec.cache_key(profile, "private passage e\u0301\r\n")
    ec.cached_embed(Model(), [text], profile=profile, cache=ec.EmbeddingCache(tmp_path))
    envelope = json.loads((tmp_path / f"{key.digest}.json").read_bytes())
    assert isinstance(envelope["payload"], list)
    assert "private passage" not in json.dumps(envelope)


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", ""),
        ("model_digest", ""),
        ("model_digest", "latest"),
        ("dimension", 0),
        ("dimension", True),
        ("dimension", 1.5),
        ("preprocessing_version", ""),
        ("normalization_options_fingerprint", ""),
    ],
)
def test_invalid_profiles_rejected(profile, field, value):
    with pytest.raises(ValueError):
        replace(profile, **{field: value})


def test_profile_immutable_model_guard_and_explicit_kind(ec, profile, tmp_path):
    with pytest.raises(FrozenInstanceError):
        profile.model = "other"
    model = Model()
    with pytest.raises(ValueError, match="model"):
        ec.cached_embed(
            model, ["a"], profile=replace(profile, model="other"), cache=ec.EmbeddingCache(tmp_path)
        )
    with pytest.raises(ValueError, match="kind"):
        ec.cached_embed(model, ["a"], profile=profile, kind="typo")
    assert model.calls == []


def test_no_cache_and_empty_are_well_defined(ec, profile):
    model = Model()
    assert ec.cached_embed(model, [], profile=profile).shape == (0, 3)
    assert model.calls == []
    actual = ec.cached_embed(model, ["a", "bbb"], profile=profile)
    assert actual.dtype == np.float32
    assert actual.shape == (2, 3)


@pytest.mark.parametrize(
    "mutation",
    [
        "checksum",
        "shape",
        "nan",
        "infinity",
        "zero",
        "bool",
        "string",
        "extra",
        "key",
        "duplicate",
        "garbage",
        "nested",
        "oversize",
    ],
)
def test_malformed_entries_are_safe_misses(ec, profile, tmp_path, mutation):
    cache = ec.EmbeddingCache(tmp_path, max_entry_bytes=2048)
    key = ec.cache_key(profile, "a")
    cache.put(key, np.array([1, 0, 0], dtype=np.float32))
    path = tmp_path / f"{key.digest}.json"
    envelope = json.loads(path.read_bytes())
    if mutation == "checksum":
        envelope["payload_hash"] = "wrong"
    elif mutation == "shape":
        envelope["payload"] = [[1, 0, 0]]
    elif mutation in {"nan", "infinity", "zero", "bool", "string"}:
        envelope["payload"] = {
            "nan": [float("nan"), 0, 0],
            "infinity": [float("inf"), 0, 0],
            "zero": [0, 0, 0],
            "bool": [True, 0, 0],
            "string": ["1", 0, 0],
        }[mutation]
    elif mutation == "extra":
        envelope["unexpected"] = 1
    elif mutation == "key":
        envelope["key"]["profile"]["dimension"] = True
    if mutation != "checksum":
        envelope["payload_hash"] = hashlib.sha256(
            json.dumps(envelope["payload"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    raw = json.dumps(envelope).encode()
    raw = {
        "duplicate": b'{"key":{},"key":{}}',
        "garbage": b"not json",
        "nested": b"[" * 1500,
        "oversize": b" " * 2049,
    }.get(mutation, raw)
    path.write_bytes(raw)
    assert cache.get(key) is None


@pytest.mark.parametrize(
    "output",
    [
        [[1, 0, 0]],
        [[1, 0], [1, 0]],
        [[1, 0, 0], [0, 0, 0]],
        [[1, 0, 0], [float("nan"), 0, 0]],
        [[1, 0, 0], [float("inf"), 0, 0]],
        [[1, 0, 0], [True, 0, 0]],
        [[1, 0, 0], ["1", 0, 0]],
        [1, 0, 0],
        [[1, 0, 0], [1]],
    ],
)
def test_bad_model_response_rejected_before_any_writes(ec, profile, tmp_path, output):
    model = Model()
    model.embed = lambda *args, **kwargs: output
    with pytest.raises(ValueError):
        ec.cached_embed(model, ["a", "b"], profile=profile, cache=ec.EmbeddingCache(tmp_path))
    assert not list(tmp_path.iterdir())


def test_disk_unavailable_and_atomic_write_failure_return_embeddings(ec, profile, tmp_path, monkeypatch):
    model = Model()
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    cache = ec.EmbeddingCache(blocker / "cache")
    actual = ec.cached_embed(model, ["a"], profile=profile, cache=cache)
    assert actual.shape == (1, 3)
    cache = ec.EmbeddingCache(tmp_path / "working")
    key = ec.cache_key(profile, "a")
    cache.put(key, actual[0])
    original = cache.get(key)

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(ec.os, "replace", fail)
    cache.put(key, [0, 1, 0])
    np.testing.assert_array_equal(cache.get(key), original)
    assert len(list(cache.root.iterdir())) == 1
    assert ec.cached_embed(model, ["b"], profile=profile, cache=cache).shape == (1, 3)


def test_oversized_write_skipped_and_model_errors_propagate(ec, profile, tmp_path):
    cache = ec.EmbeddingCache(tmp_path / "tiny", max_entry_bytes=10)
    model = Model()
    assert ec.cached_embed(model, ["a"], profile=profile, cache=cache).shape == (1, 3)
    assert not cache.root.exists()

    def fail(*args, **kwargs):
        raise RuntimeError("model unavailable")

    model.embed = fail
    with pytest.raises(RuntimeError, match="model unavailable"):
        ec.cached_embed(model, ["a"], profile=profile, cache=cache)


def test_real_ollama_prefixes_and_normalization_are_reused(ec, profile, tmp_path):
    import httpx

    from hippo.ollama import Ollama

    calls = []

    def handler(request):
        assert request.url.path == "/api/embed"
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(200, json={"embeddings": [[3, 4, 0] for _ in body["input"]]})

    cache = ec.EmbeddingCache(tmp_path)
    with httpx.Client(base_url="http://local-test", transport=httpx.MockTransport(handler)) as client:
        model = Ollama("http://local-test", "unused", profile.model, client=client)
        for kind in ("document", "query"):
            first = ec.cached_embed(model, ["exact é"], profile=profile, kind=kind, cache=cache)
            second = ec.cached_embed(model, ["exact é"], profile=profile, kind=kind, cache=cache)
            np.testing.assert_array_equal(first, second)
            np.testing.assert_allclose(second, [[0.6, 0.8, 0]])
    assert [body["input"] for body in calls] == [["search_document: exact é"], ["search_query: exact é"]]
    assert all(
        body == {"model": profile.model, "input": body["input"], "keep_alive": "15m"} for body in calls
    )


@pytest.mark.parametrize("fail", [False, True])
def test_model_change_during_embed_rejected_without_cache_writes(ec, profile, tmp_path, fail):
    model = Model()
    embed = model.embed

    def change_model(*args, **kwargs):
        model.embed_model = "other:latest"
        if fail:
            raise RuntimeError("changed model failed")
        return embed(*args, **kwargs)

    model.embed = change_model
    with pytest.raises(ValueError, match="model"):
        ec.cached_embed(model, ["a"], profile=profile, cache=ec.EmbeddingCache(tmp_path))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("hit", [False, True])
def test_model_change_during_cache_lookup_rejected_before_dispatch(ec, profile, tmp_path, monkeypatch, hit):
    model = Model()
    cache = ec.EmbeddingCache(tmp_path)
    if hit:
        cache.put(ec.cache_key(profile, "a"), [1, 0, 0])
    get = cache.get

    def change_model(key):
        model.embed_model = "other:latest"
        return get(key)

    monkeypatch.setattr(cache, "get", change_model)
    with pytest.raises(ValueError, match="model"):
        ec.cached_embed(model, ["a"], profile=profile, cache=cache)
    assert not model.calls


def test_model_change_during_cache_write_stops_remaining_writes_and_return(
    ec, profile, tmp_path, monkeypatch
):
    model = Model()
    cache = ec.EmbeddingCache(tmp_path)
    written = []
    put = cache.put

    def change_model(key, row):
        put(key, row)
        written.append(key)
        model.embed_model = "other:latest"

    monkeypatch.setattr(cache, "put", change_model)
    with pytest.raises(ValueError, match="model"):
        ec.cached_embed(model, ["a", "b"], profile=profile, cache=cache)
    assert written == [ec.cache_key(profile, "a")]
    np.testing.assert_array_equal(cache.get(written[0]), Model().embed(["a"])[0])
    assert cache.get(ec.cache_key(replace(profile, model="other:latest"), "a")) is None


def test_model_change_on_last_cache_write_rejected_before_return(ec, profile, tmp_path, monkeypatch):
    model = Model()
    cache = ec.EmbeddingCache(tmp_path)

    def change_model(key, row):
        model.embed_model = "other:latest"

    monkeypatch.setattr(cache, "put", change_model)
    with pytest.raises(ValueError, match="model"):
        ec.cached_embed(model, ["a"], profile=profile, cache=cache)
