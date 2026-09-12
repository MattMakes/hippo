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


# ------------------------------- the managed lane's own code, not its exception

# `ManagedFailure.code` from `src/hippo/ingest/managed_activation.py` (Task 3a).
# The managed lane maps an exception once, at the point of failure, and stores the
# code on the Source row; a route reading that row hours later has no exception to
# re-derive from. These eleven are the stable set: the nine recorded in the Task 3a
# review, plus the two Task 3b added -- `retrieval_rebuild_required`, when the managed
# table learned to read a stale embedding profile ahead of the wider `OllamaError`, and
# `build_interrupted`, which the store's restart sweep writes without any exception to
# classify (see `test_a_code_the_store_writes_without_an_exception_still_has_an_answer`).
MANAGED_CODES = {
    "build_cancelled": FAILED,
    "build_interrupted": FAILED,
    "build_busy": FAILED,
    "authorization_changed": None,
    "model_unavailable": UNAVAILABLE,
    "retrieval_rebuild_required": REBUILD,
    "source_too_large": SIZE,
    "unsupported_source": TYPE,
    "invalid_configuration": FAILED,
    "invalid_source": TYPE,
    "operation_failed": FAILED,
}


@pytest.mark.parametrize("code,expected", sorted(MANAGED_CODES.items()))
def test_every_managed_failure_code_has_one_public_answer(code, expected):
    failure = api().public_failure_for_code(code)
    if expected is None:
        assert failure is None
        return
    assert (failure.code, failure.message, failure.http_status) == expected


def test_a_stored_code_and_its_own_exception_agree():
    """The two entry points must not disagree about the same failure.

    `map_build_failure` lives in the ingest lane and is not importable from here,
    so the pairing is spelled out: each row is the exception family the managed
    table maps to that code.
    """
    module = api()
    for code, exc in (
        ("build_cancelled", BuildCancelled(POISON)),
        ("build_busy", BuildBusy(POISON)),
        ("authorization_changed", AuthorizationChanged(POISON)),
        ("model_unavailable", OllamaError(POISON)),
        # The one code whose two vocabularies now agree exactly: the managed table reads
        # a stale or mismatched profile ahead of the wider `OllamaError` row, so a stored
        # `retrieval_rebuild_required` round-trips to the failure the same exception maps
        # to in a query. Before Task 3b it was stored as `model_unavailable` and read back
        # as a 503 retry for evidence that will never be compatible again.
        ("retrieval_rebuild_required", EmbeddingProfileMismatch(POISON)),
        ("retrieval_rebuild_required", EmbeddingProfileChanged(POISON)),
        ("source_too_large", TooLarge(POISON)),
        ("unsupported_source", UnsupportedProvenanceFormat(POISON)),
        ("invalid_source", InputCaptureError(POISON)),
    ):
        assert module.public_failure_for_code(code) == module.public_failure(exc), code


def test_a_code_the_store_writes_without_an_exception_still_has_an_answer():
    """`build_interrupted` has no exception family, so its round trip is the stored string.

    A process that has just restarted has no exception to classify: the sweep in
    `store/memory.py` writes `INTERRUPTED_REFRESH_ERROR` onto the row directly, and must
    not import the pipeline to do it. The literal is spelled out here for the same reason
    the pairing above is -- importing the store into this test would pull a driver -- so
    what this pins is the shape contract between the two modules: whatever the sweep
    writes has to split on `": "` into a code this table knows and a bounded sentence.
    """
    module = api()
    stored = "build_interrupted: The build was interrupted by a restart. Reindex to run it again."
    code, separator, message = stored.partition(": ")
    assert separator and message
    failure = module.public_failure_for_code(code)
    assert failure is not None, "a stored code with no public answer renders as the wrong status"
    assert (failure.code, failure.message, failure.http_status) == FAILED
    # Not 409: that sentence claims the corpus cannot serve a query until it is rebuilt,
    # and an interrupted refresh leaves the published generation serving throughout.
    assert failure.http_status == 500
    assert failure != module.public_failure_for_code("retrieval_rebuild_required")


def test_an_unknown_or_malformed_code_falls_through_like_an_unknown_exception():
    module = api()
    for value in ("", "no_such_code", "OPERATION_FAILED", None, 7, ("operation_failed",)):
        assert module.public_failure_for_code(value) is None


def test_a_stored_code_cannot_widen_the_public_vocabulary():
    module = api()
    answers = [module.public_failure_for_code(code) for code in MANAGED_CODES]
    mapped = [failure for failure in answers if failure is not None]
    assert {failure.code for failure in mapped} <= {
        "retrieval_rebuild_required",
        "retrieval_unavailable",
        "invalid_source",
        "operation_failed",
    }
    assert all(
        failure.message in {row[1] for row in (REBUILD, UNAVAILABLE, TYPE, SIZE, FAILED)}
        for failure in mapped
    )


def test_code_mapping_logs_nothing_and_touches_no_store_or_socket(caplog, monkeypatch):
    module = api()

    def forbidden(*args, **kwargs):
        pytest.fail("public_failure_for_code performed I/O")

    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    with caplog.at_level(logging.DEBUG):
        for code in MANAGED_CODES:
            module.public_failure_for_code(code)
        module.public_failure_for_code("no_such_code")
    assert caplog.records == []
