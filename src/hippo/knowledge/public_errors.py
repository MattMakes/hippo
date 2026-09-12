"""The only thing a transport may learn from an exception it did not raise.

`public_failure` maps a known activation or retrieval exception to a stable
`PublicFailure`. FastAPI, the MCP tools, the remote client and the CLI all read
the same table, so a client that moves between them sees the same code for the
same condition.

The mapping is CLOSED and PURE. Closed: four codes, five sentences, five HTTP
statuses, all written here as constants. Pure: no logging, no I/O, and never
`str(exc)` or `exc.args` in a returned field. That is the whole point. Several
of the exceptions in the table carry private material by construction --
`Ollama._request` puts 300 characters of the model's reply body into its
message, `TooLarge` names the file it was reading, and a build failure can
quote source text -- so the returned message can only ever be one of the
constants below.

Caller rule for the managed paths
---------------------------------
`None` means "not one of these"; the caller falls through to the handling it
already had. That keeps legacy validation routes on their current messages and
leaves `AuthorizationChanged` to the existing permission response, which is
409/403 and already generic.

A managed build or query path must not let an unknown exception reach the
client, but a pure function cannot tell where an exception was raised. So a
managed path spells that out itself:

    failure = public_failure(exc) or OPERATION_FAILED

Everywhere else, `None` means "not mine" and nothing is substituted. This is
also how the bare `ValueError` raised by `GraphIndex.canonical_selected_generations`
becomes `operation_failed` without this module having to claim every `ValueError`
in the process.

A failure the managed lane already classified
---------------------------------------------
`managed_activation.map_build_failure` classifies a build failure once, where it
happens, and stores `ManagedFailure.code` on the Source row. A route rendering
that row hours later has no exception to re-derive from, and re-deriving would
be a second opinion about the same event. `public_failure_for_code` takes the
stored code instead:

    failure = public_failure_for_code(row.code) or OPERATION_FAILED

It takes a plain string on purpose, so nothing in the query lane has to import
the build lane to render a Source row. The two functions agree by construction
for every family the managed table maps, and `test_public_errors.py` pins that
pairing.

A stored code is a message, never a status
------------------------------------------
The two entry points do not return the same *kind* of answer, and the difference
matters at exactly one place.

`public_failure(exc)` sees the exception. It can tell a file that was too big
from a file of the wrong type, so its `http_status` is real information: 413
against 400. That is the only point at which a status is meaningful, because it
is the only point at which anything knows which of the two happened.

`public_failure_for_code(code)` sees a string a different process wrote, possibly
hours ago. What a caller may take from it is the **code and the message** -- the
rendering, `f"{code}: {message}"`, which is what every surface prints. It must
not take an HTTP status from it. Two failures deliberately share the code
`invalid_source` (the 400 type error and the 413 size error), so a code alone
cannot say which, and asking this function for a status would silently answer
400 for a source that was too large.

That is why the vocabulary is not split: `invalid_source` says the one true thing
about both, the message carries the rest, and a status is re-derived where the
exception still exists rather than reconstructed from a string where it does not.
The consequence is pinned by name in `test_the_code_mapping_is_idempotent`, which
asserts the mapping is a no-op on its own output for every code and spells out the
413 -> 400 collision rather than skipping it, so that nobody builds on the
assumption that a stored code remembers a status.
"""

from dataclasses import dataclass

import httpx

from ..ingest.accepted_inputs import CaptureTooLarge, InputCaptureError
from ..ingest.prose_generation import BuildBusy, BuildCancelled
from ..ingest.readers import ReadError, TooLarge
from ..ollama import OllamaError
from .dense import DenseUnavailable
from .dense_session import DenseSessionUnavailable
from .embedding_profile import EmbeddingProfileChanged, EmbeddingProfileMismatch
from .projection import ProjectionError
from .raw_artifacts import RawArtifactTooLarge


@dataclass(frozen=True)
class PublicFailure:
    """One stable public code, one bounded generic sentence, one HTTP status."""

    code: str
    message: str
    http_status: int


REBUILD_REQUIRED = PublicFailure(
    "retrieval_rebuild_required", "Rebuild compatible sources before retrieval", 409
)
RETRIEVAL_UNAVAILABLE = PublicFailure("retrieval_unavailable", "Retrieval service is unavailable", 503)
INVALID_SOURCE_TYPE = PublicFailure("invalid_source", "The source is not an accepted input type", 400)
INVALID_SOURCE_SIZE = PublicFailure("invalid_source", "The source exceeds the accepted input size limit", 413)
OPERATION_FAILED = PublicFailure(
    "operation_failed", "Operation failed; inspect local logs by operation ID", 500
)

# A borrowed session the caller assembled wrongly is our bug, not stale evidence:
# telling the user to rebuild their sources would be a lie.
_CALLER_ERROR_REASONS = frozenset({"invalid_borrow"})

# Ordered most specific first. Inheritance is not the order: EmbeddingProfileMismatch
# and EmbeddingProfileChanged are OllamaError subclasses, but a stale profile asks for
# a rebuild while an unreachable model asks for a retry.
_ROWS: tuple[tuple[type[BaseException], PublicFailure], ...] = (
    (EmbeddingProfileMismatch, REBUILD_REQUIRED),
    (EmbeddingProfileChanged, REBUILD_REQUIRED),
    # DenseSessionUnavailable is handled ahead of this table; DenseUnavailable is its base.
    (DenseUnavailable, REBUILD_REQUIRED),
    (OllamaError, RETRIEVAL_UNAVAILABLE),
    # The model client is httpx; a connection or timeout error that escapes unwrapped
    # is still "the model is not answering".
    (httpx.TransportError, RETRIEVAL_UNAVAILABLE),
    # Closed input validators only -- the readers, the accepted-input capture and the
    # raw object store. Size before type, because each size error is a subclass of its
    # module's base validation error. Nothing else in these modules is listed: a corrupt
    # raw object or an unsafe storage location is not client input, so it falls through
    # to whatever handling the caller already had.
    (TooLarge, INVALID_SOURCE_SIZE),
    (CaptureTooLarge, INVALID_SOURCE_SIZE),
    (RawArtifactTooLarge, INVALID_SOURCE_SIZE),
    (ReadError, INVALID_SOURCE_TYPE),
    (InputCaptureError, INVALID_SOURCE_TYPE),
    (BuildBusy, OPERATION_FAILED),
    (BuildCancelled, OPERATION_FAILED),
    (ProjectionError, OPERATION_FAILED),
)


# The eleven stable values a Source row's `error` can carry. Ten are `ManagedFailure.code`
# from `managed_activation.FAILURES` and `UNKNOWN_CODE`; the eleventh, `build_interrupted`,
# comes from somewhere else entirely -- the store's own restart sweep writes it directly
# (`store/memory.py`, `INTERRUPTED_REFRESH_ERROR`), because a process that has just come up
# has no exception to classify and must not import the pipeline to recover from a crash.
# So this table is keyed by string rather than by exception for two reasons now: a stored
# row can be rendered without the build lane, and not every code in it has an exception
# behind it at all.
#
# `invalid_configuration` is the one row where the two vocabularies part company.
# It means the operator's stored indexing settings cannot build a source -- their
# problem to fix, not the reader's input -- so publicly it is `operation_failed`
# rather than `invalid_source`; blaming the request for a stored setting would send
# the reader looking in the wrong place.
#
# `retrieval_rebuild_required` is the one code the two vocabularies name identically.
# The managed table used to stop at its widest model row, `OllamaError`, so a build that
# failed on `EmbeddingProfileMismatch` or `EmbeddingProfileChanged` was stored as
# `model_unavailable` and read back as a 503 retry -- for evidence that will never be
# compatible again. `managed_activation.FAILURES` now reads those two ahead of
# `OllamaError` and stores the rebuild code, so the row below makes the round trip an
# identity: the same exception maps to the same public failure whether a caller met it in
# a query or is reading a Source row hours later. Without the row a stored rebuild code
# falls through to `None` and its caller's `or OPERATION_FAILED` turns a 409 "reindex
# this" into a 500 "look in the logs", which is the wrong instruction as well as the
# wrong status.
#
# `build_interrupted` is `operation_failed` (500), not `retrieval_rebuild_required` (409),
# and the choice is worth spelling out because 409 is tempting: both sentences end up
# telling the reader to reindex. But 409 says "Rebuild compatible sources before
# retrieval", which is a claim about the *corpus* -- that what is published cannot serve a
# query until it is rebuilt. An interrupted refresh makes no such claim: the published
# generation kept serving throughout, which is exactly why the sweep leaves the source
# `ready` and retires only the stage. Nothing is stale and nothing is incompatible; an
# operation simply did not finish. Its nearest row is `build_cancelled`, the same event
# with a different trigger and the same "Reindex to run it again", and that is 500.
# The last two rows are not build-lane codes at all: they are this module's *own* public
# codes, here so that `public_failure_for_code` is closed over the whole public vocabulary
# and every `PublicFailure.code` round-trips to a failure carrying that same code. A caller
# that has already rendered a failure once -- an eval replaying a stored result, a route
# re-reading its own answer -- must not fall off the table and be told `operation_failed`
# for something already classified as unavailable.
#
# `INVALID_SOURCE_TYPE` (400) and `INVALID_SOURCE_SIZE` (413) deliberately share the code
# `invalid_source`, so a code alone cannot say which, and `invalid_source` resolves to the
# 400. That is not a gap to close: a stored code is rendered as `code: message` and never
# as a status (see this module's docstring). `source_too_large` keeps its own size sentence
# here, which is what a reader is shown; the 413 belongs to `public_failure(exc)`, where
# something still knows which exception it was.
_MANAGED_CODES: dict[str, PublicFailure | None] = {
    "build_cancelled": OPERATION_FAILED,
    "build_interrupted": OPERATION_FAILED,
    "build_busy": OPERATION_FAILED,
    "authorization_changed": None,
    "model_unavailable": RETRIEVAL_UNAVAILABLE,
    "retrieval_rebuild_required": REBUILD_REQUIRED,
    "retrieval_unavailable": RETRIEVAL_UNAVAILABLE,
    "source_too_large": INVALID_SOURCE_SIZE,
    "unsupported_source": INVALID_SOURCE_TYPE,
    "invalid_configuration": OPERATION_FAILED,
    "invalid_source": INVALID_SOURCE_TYPE,
    "operation_failed": OPERATION_FAILED,
}


def public_failure(exc: BaseException) -> PublicFailure | None:
    """The public failure for a known activation or retrieval exception, else `None`."""
    if isinstance(exc, DenseSessionUnavailable):
        reason = getattr(exc, "reason", None)
        return OPERATION_FAILED if reason in _CALLER_ERROR_REASONS else REBUILD_REQUIRED
    for kind, failure in _ROWS:
        if isinstance(exc, kind):
            return failure
    return None


def public_failure_for_code(code: str) -> PublicFailure | None:
    """The public failure for a `ManagedFailure.code` the managed lane already stored.

    `None` for `authorization_changed`, which keeps the existing permission
    response, and for any code this table does not know; a managed caller adds
    `or OPERATION_FAILED`, exactly as it does for `public_failure`.

    Closed over its own output: every code a returned `PublicFailure` carries is
    itself a key here, so rendering an already-rendered failure is a no-op rather
    than a fall-through to `operation_failed`.

    Take the code and the message from this; do not take `http_status`. A stored
    code is a rendering, not a classification, and `invalid_source` covers both
    the 400 and the 413. See "A stored code is a message, never a status" above.
    """
    if type(code) is not str:
        return None
    return _MANAGED_CODES.get(code)
