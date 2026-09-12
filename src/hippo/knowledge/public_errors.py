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


def public_failure(exc: BaseException) -> PublicFailure | None:
    """The public failure for a known activation or retrieval exception, else `None`."""
    if isinstance(exc, DenseSessionUnavailable):
        reason = getattr(exc, "reason", None)
        return OPERATION_FAILED if reason in _CALLER_ERROR_REASONS else REBUILD_REQUIRED
    for kind, failure in _ROWS:
        if isinstance(exc, kind):
            return failure
    return None
