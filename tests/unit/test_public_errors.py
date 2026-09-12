"""Known activation and retrieval failures become a closed, private public vocabulary.

`public_failure` is the only thing a transport is allowed to learn from an
exception it did not raise itself. Everything here is about two properties:
the mapping is closed (four codes, four messages, five statuses) and it is
pure (no logging, no I/O, and never one character of the exception's own text).
"""

import importlib
import logging

import httpx
import pytest

from hippo.ingest.accepted_inputs import CaptureTooLarge, InputCaptureError, UnsupportedCaptureInput
from hippo.ingest.prose_generation import BuildBusy, BuildCancelled
from hippo.ingest.provenance import UnsupportedProvenanceFormat
from hippo.ingest.readers import ReadError, TooLarge
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.dense import DenseUnavailable
from hippo.knowledge.dense_session import DenseSessionUnavailable
from hippo.knowledge.embedding_profile import (
    EmbeddingProfileChanged,
    EmbeddingProfileMismatch,
    EmbeddingProfileUnavailable,
)
from hippo.knowledge.projection import ProjectionError
from hippo.knowledge.raw_artifacts import RawArtifactCorrupt, RawArtifactTooLarge
from hippo.ollama import OllamaError


def api():
    try:
        return importlib.import_module("hippo.knowledge.public_errors")
    except ModuleNotFoundError:
        pytest.fail("Public failure mapping is missing")


# A single string carrying every kind of private material the plan names: a
# credential, an absolute path, verbatim source text and a model reply body.
POISON = (
    "token=sk-live-DEADBEEF /Users/someone/data/private/notes.md "
    "'Acme Robotics is headquartered in Boulder.' "
    '{"model":"nomic-embed-text","embeddings":[[0.1,0.2]]}'
)
SECRETS = (
    "sk-live-DEADBEEF",
    "/Users/someone/data/private/notes.md",
    "Acme Robotics",
    "nomic-embed-text",
    "embeddings",
    POISON,
)

REBUILD = ("retrieval_rebuild_required", "Rebuild compatible sources before retrieval", 409)
UNAVAILABLE = ("retrieval_unavailable", "Retrieval service is unavailable", 503)
TYPE = ("invalid_source", "The source is not an accepted input type", 400)
SIZE = ("invalid_source", "The source exceeds the accepted input size limit", 413)
FAILED = ("operation_failed", "Operation failed; inspect local logs by operation ID", 500)


def dense_unavailable(reason):
    return DenseSessionUnavailable(reason, POISON)


MAPPED = [
    # mixed / unverified / invalid dense evidence and stored profile mismatch or change
    (lambda: dense_unavailable("mixed_modes"), REBUILD),
    (lambda: dense_unavailable("mixed_profiles"), REBUILD),
    (lambda: dense_unavailable("dimension_mismatch"), REBUILD),
    (lambda: dense_unavailable("unverified"), REBUILD),
    (lambda: dense_unavailable("invalid_binding"), REBUILD),
    (lambda: dense_unavailable("no_dense_dimension"), REBUILD),
    (lambda: DenseUnavailable(POISON), REBUILD),
    (lambda: EmbeddingProfileMismatch(POISON), REBUILD),
    (lambda: EmbeddingProfileChanged(POISON), REBUILD),
    # model metadata / embed / chat unavailable or timeout
    (lambda: EmbeddingProfileUnavailable(POISON), UNAVAILABLE),
    (lambda: OllamaError(POISON), UNAVAILABLE),
    (lambda: httpx.ConnectError(POISON), UNAVAILABLE),
    (lambda: httpx.ReadTimeout(POISON), UNAVAILABLE),
    (lambda: httpx.ConnectTimeout(POISON), UNAVAILABLE),
    # invalid client input, unsupported type, size
    (lambda: TooLarge(POISON), SIZE),
    (lambda: CaptureTooLarge(POISON), SIZE),
    (lambda: RawArtifactTooLarge(POISON), SIZE),
    (lambda: UnsupportedProvenanceFormat(POISON), TYPE),
    (lambda: UnsupportedCaptureInput(POISON), TYPE),
    (lambda: ReadError(POISON), TYPE),
    (lambda: InputCaptureError(POISON), TYPE),
    # unknown managed build or query exception
    (lambda: BuildBusy(POISON), FAILED),
    (lambda: BuildCancelled(POISON), FAILED),
    (lambda: ProjectionError(POISON), FAILED),
    # a borrowed session the caller assembled wrongly is our bug, not stale evidence
    (lambda: dense_unavailable("invalid_borrow"), FAILED),
]


@pytest.mark.parametrize("build,expected", MAPPED, ids=[str(i) for i in range(len(MAPPED))])
def test_every_closed_row_returns_its_stable_code_message_and_status(build, expected):
    failure = api().public_failure(build())
    assert (failure.code, failure.message, failure.http_status) == expected


@pytest.mark.parametrize("build,expected", MAPPED, ids=[str(i) for i in range(len(MAPPED))])
def test_no_injected_private_text_reaches_any_field(build, expected):
    failure = api().public_failure(build())
    rendered = "␟".join((failure.code, failure.message, str(failure.http_status)))
    for secret in SECRETS:
        assert secret not in rendered
    assert str(build()) not in rendered


@pytest.mark.parametrize(
    "exc",
    [
        AuthorizationChanged("Permissions changed; repeat the query"),
        ValueError("Managed compatibility projection requires explicit current generations"),
        RuntimeError(POISON),
        KeyError("passage-1"),
        LookupError(POISON),
        # Corrupt stored bytes are not client input; the existing handler owns them.
        RawArtifactCorrupt(POISON),
        Exception(POISON),
        BaseException(POISON),
    ],
)
def test_unrelated_exceptions_fall_through_to_existing_handling(exc):
    assert api().public_failure(exc) is None


def test_the_returned_vocabulary_is_closed():
    module = api()
    codes, messages, statuses = set(), set(), set()
    for build, _ in MAPPED:
        failure = module.public_failure(build())
        codes.add(failure.code)
        messages.add(failure.message)
        statuses.add(failure.http_status)
    assert codes == {
        "retrieval_rebuild_required",
        "retrieval_unavailable",
        "invalid_source",
        "operation_failed",
    }
    assert len(messages) == 5  # one per code, plus the two bounded invalid-source sentences
    assert statuses == {409, 503, 400, 413, 500}


def test_a_subclass_of_ollama_error_that_names_a_profile_asks_for_a_rebuild_not_a_retry():
    # EmbeddingProfileMismatch/Changed are OllamaError subclasses. Row order, not
    # inheritance, decides: a stale profile is 409, an unreachable model is 503.
    module = api()
    assert issubclass(EmbeddingProfileMismatch, OllamaError)
    assert module.public_failure(EmbeddingProfileMismatch("x")).http_status == 409
    assert module.public_failure(EmbeddingProfileChanged("x")).http_status == 409
    assert module.public_failure(EmbeddingProfileUnavailable("x")).http_status == 503


def test_the_public_failure_is_frozen_and_repeatable():
    module = api()
    first = module.public_failure(OllamaError(POISON))
    second = module.public_failure(OllamaError("something else entirely"))
    assert first == second
    with pytest.raises(AttributeError):
        first.code = "other"


def test_operation_failed_is_exported_for_managed_path_callers():
    module = api()
    assert (
        module.OPERATION_FAILED.code,
        module.OPERATION_FAILED.message,
        module.OPERATION_FAILED.http_status,
    ) == FAILED
    assert module.public_failure(ProjectionError(POISON)) == module.OPERATION_FAILED


def test_mapping_logs_nothing_and_touches_no_store_or_socket(caplog, monkeypatch):
    module = api()

    def forbidden(*args, **kwargs):
        pytest.fail("public_failure performed I/O")

    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    with caplog.at_level(logging.DEBUG):
        for build, _ in MAPPED:
            module.public_failure(build())
        module.public_failure(RuntimeError(POISON))
    assert caplog.records == []


def test_an_exception_whose_str_raises_is_still_mapped():
    class Hostile(OllamaError):
        def __str__(self):
            raise AssertionError("public_failure read the exception text")

    assert api().public_failure(Hostile()).code == "retrieval_unavailable"
