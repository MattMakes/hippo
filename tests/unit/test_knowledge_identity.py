"""Canonical identities must survive adversarial names and namespace boundaries."""

import importlib
from pathlib import Path

import pytest


def identity():
    try:
        return importlib.import_module("hippo.knowledge.identity")
    except ModuleNotFoundError:
        pytest.fail("Task 2 canonical identity module has not been implemented")


def test_canonical_hash_uses_unambiguous_arrays_and_nested_key_order():
    m = identity()
    assert m.make_identity("artifact", ["a:b", "c"]) != m.make_identity("artifact", ["a", "b:c"])
    assert m.make_identity("artifact", [{"b": 2, "a": [1, None]}]) == m.make_identity(
        "artifact", [{"a": [1, None], "b": 2}]
    )
    assert m.make_identity("artifact", ["é"]).startswith("artifact-")
    assert len(m.make_identity("artifact", ["é"]).split("-")[1]) == 64
    assert m.canonical_json(["é", {"b": 2, "a": 1}]) == '["é",{"a":1,"b":2}]'


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), {1: "ambiguous"}, {"set"}, b"bytes", Path("x")]
)
def test_identity_rejects_non_json_values(value):
    with pytest.raises((TypeError, ValueError)):
        identity().make_identity("artifact", [value])


@pytest.mark.parametrize("value", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', "not-json"])
def test_json_payloads_reject_duplicate_keys_and_nonfinite(value):
    with pytest.raises(ValueError):
        identity().normalize_json(value)


def test_provider_normalization_keeps_instance_base_path():
    m = identity()
    assert m.normalize_provider_url("HTTPS://GIT.Example:443/team/") == "https://git.example/team"
    assert m.normalize_provider_url("http://EXAMPLE:80") == "http://example"
    assert m.normalize_provider_url("http://[::1]:8011/") == "http://[::1]:8011"
    assert m.normalize_provider_url("https://example/a") != m.normalize_provider_url("https://example/b")


@pytest.mark.parametrize(
    "url",
    [
        "https://u:p@example",
        "https://example?q=a",
        "https://example#x",
        "file:///x",
        "https://example/../a",
        "https://example/%2e%2e/a",
        "https://example\\evil",
        "https://example\n",
        "https://example:99999",
    ],
)
def test_provider_rejects_ambiguous_or_secret_urls(url):
    with pytest.raises(ValueError):
        identity().normalize_provider_url(url)


def test_paths_are_root_relative_and_resolved_against_symlink_escape(tmp_path):
    m = identity()
    root = tmp_path / "root"
    root.mkdir()
    (root / "folder").mkdir()
    (root / "folder" / "a.py").write_text("pass")
    assert m.source_relative_path(root, "folder/./a.py") == "folder/a.py"
    (root / "escape").symlink_to(tmp_path, target_is_directory=True)
    for path in ["../private", "/etc/passwd", "escape/secret", "C:\\Users\\secret", "..\\private"]:
        with pytest.raises(ValueError):
            m.source_relative_path(root, path)


def test_provider_artifacts_and_catalog_references_do_not_collide():
    m = identity()
    args = ("commerce", "https://one.example", "ticket", "42")
    first = m.artifact_identity(*args)
    assert first != m.artifact_identity("commerce", "https://two.example", "ticket", "42")
    assert first == m.artifact_identity("commerce", "https://ONE.example:443/", "ticket", "42")
    assert m.catalog_reference("payments", default_kind="Component") == "component:default/payments"
    assert m.service_identity("commerce", "https://catalog", "component:a/payments") != m.service_identity(
        "commerce", "https://catalog", "component:b/payments"
    )


def test_sql_identifier_preserves_quoting_and_collation():
    m = identity()
    unquoted = m.sql_identifier("Orders", dialect="postgres", quoted=False)
    quoted = m.sql_identifier("Orders", dialect="postgres", quoted=True)
    assert unquoted.lookup == "orders"
    assert quoted.lookup == "Orders"
    assert quoted.original == "Orders" and quoted.quoted
    cs = m.sql_identifier("Orders", dialect="tsql", collation="Latin1_General_CS_AS")
    ci = m.sql_identifier("Orders", dialect="tsql", collation="Latin1_General_CI_AS")
    assert cs.lookup == "Orders"
    assert ci.lookup == "Orders"  # Collation must be resolved by a capable adapter, not Python casefold.
    assert ci.collation != cs.collation
    with pytest.raises(ValueError):
        m.sql_identifier("Orders", dialect="prose")
    assert m.database_object_identity(
        "w", "db-a", "prod", "cat", "public", [quoted], "table"
    ) != m.database_object_identity("w", "db-b", "prod", "cat", "public", [quoted], "table")


def test_revision_span_endpoint_and_overloaded_symbols_have_separate_keys():
    m = identity()
    assert m.revision_identity("a", "r1", "hash") != m.revision_identity("a", "r2", "hash")
    assert m.span_identity(
        "r", {"kind": "file_lines", "path": "a.py", "start": 1, "end": 2}, "hash"
    ) != m.span_identity("r", {"kind": "file_lines", "path": "a.py", "start": 2, "end": 3}, "hash")
    assert m.symbol_identity("repo", "python", "x.py", "f", "(int)") != m.symbol_identity(
        "repo", "python", "x.py", "f", "(str)"
    )
    assert m.endpoint_identity("svc", "http", "api-v1", "get", "/Foo") == m.endpoint_identity(
        "svc", "http", "api-v1", "GET", "/Foo"
    )
    assert m.endpoint_identity("svc", "http", "api-v1", "GET", "/Foo") != m.endpoint_identity(
        "svc", "http", "api-v1", "GET", "/foo"
    )


def test_sql_identity_hashes_semantics_and_preserves_qualified_boundaries():
    m = identity()

    def object_id(parts):
        return m.database_object_identity("w", "db", "prod", "catalog", "public", parts, "table")

    plain = m.sql_identifier("Orders", dialect="postgres")
    lower = m.sql_identifier("orders", dialect="postgres", quoted=True)
    upper = m.sql_identifier("Orders", dialect="postgres", quoted=True)
    assert object_id([plain]) == object_id([lower])
    assert object_id([plain]) != object_id([upper])
    assert object_id([m.sql_identifier("a.b", dialect="postgres", quoted=True), lower]) != object_id(
        [
            m.sql_identifier("a", dialect="postgres"),
            m.sql_identifier("b.orders", dialect="postgres", quoted=True),
        ]
    )
    assert m.sql_identifier("ÄOrders", dialect="postgres").lookup == "Äorders"


def test_symbol_kind_and_api_identity_are_part_of_keys():
    m = identity()
    assert m.symbol_identity("repo", "python", "a.py", "a", kind="module") != m.symbol_identity(
        "repo", "python", "a.py", "a", kind="function"
    )
    assert m.endpoint_identity(
        "svc", "http", "v1", "GET", "/health", api_identity="public"
    ) != m.endpoint_identity("svc", "http", "v1", "GET", "/health", api_identity="admin")


@pytest.mark.parametrize("url", ["https://example/a%", "https://example/a%2", "https://example/a%ZZ"])
def test_provider_rejects_malformed_percent_encoding(url):
    with pytest.raises(ValueError):
        identity().normalize_provider_url(url)


def test_provider_encoded_delimiters_and_case_remain_distinct():
    m = identity()
    assert m.normalize_provider_url("https://example/a%2Fb") != m.normalize_provider_url(
        "https://example/a/b"
    )
    assert m.normalize_provider_url("https://example/Tenant") != m.normalize_provider_url(
        "https://example/tenant"
    )
    assert m.catalog_reference("api/refunds", default_namespace="commerce") == "component:api/refunds"
    assert m.catalog_reference("api:refunds", default_namespace="commerce") == "api:commerce/refunds"


def test_local_repository_review_helpers_preserve_namespace(tmp_path):
    m = identity()
    assert m.local_artifact_identity("w", "source-a", tmp_path, "a.sql") != m.local_artifact_identity(
        "w", "source-b", tmp_path, "a.sql"
    )
    assert m.repository_identity("w", "https://git", "a") != m.repository_identity("w2", "https://git", "a")
    assert m.review_identity("w", "https://git", "repo-a", "42") != m.review_identity(
        "w", "https://git", "repo-b", "42"
    )


def test_database_qualifiers_are_dialect_aware_too():
    m = identity()
    table = m.sql_identifier("orders", dialect="postgres")

    def object_id(schema):
        return m.database_object_identity("w", "db", "prod", "catalog", schema, [table], "table")

    assert object_id("Public") == object_id(m.sql_identifier("public", dialect="postgres", quoted=True))
    assert object_id("Public") != object_id(m.sql_identifier("Public", dialect="postgres", quoted=True))


def test_provider_unicode_host_cannot_alias_a_distinct_ascii_host():
    m = identity()
    # Python's legacy IDNA codec maps ß to ss, unlike HTTPX's modern transport.
    # Unsupported Unicode host spelling is rejected; explicit punycode is stable.
    with pytest.raises(ValueError):
        m.normalize_provider_url("https://faß.de")
    assert m.normalize_provider_url("https://xn--fa-hia.de") != m.normalize_provider_url("https://fass.de")


def test_span_identity_canonicalizes_typed_locator_paths_and_defaults():
    m = identity()
    assert m.span_identity(
        "r", {"kind": "file_lines", "path": "a/./b.py", "start": 1, "end": 2}, "h"
    ) == m.span_identity("r", {"kind": "file_lines", "path": "a/b.py", "start": 1, "end": 2}, "h")
    assert m.span_identity("r", {"kind": "page", "page": 1}, "h") == m.span_identity(
        "r", {"kind": "page", "page": 1, "offset_start": 0, "offset_end": None}, "h"
    )


@pytest.mark.parametrize("url", ["https://K.example", "https://İ.example"])
def test_unicode_hosts_are_rejected_before_url_parser_case_normalization(url):
    with pytest.raises(ValueError):
        identity().normalize_provider_url(url)
