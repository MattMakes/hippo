"""The one purity guard for `emit`: a per-thread profile hook, never a process-wide patch.

Design `docs/spec/connector-developer-kit.md` section 8, plan `ai_docs/plans/cdk-s3-runtime.md`
sections 4.1 and 10.1, ruling B3/R49 (this module is the only guard there is; the kit's
`testing.purity_guard` is `forbid_effects` itself) and review minor m20 (the clock, profiler and
thread-start names below).

`forbid_effects()` installs a `sys.setprofile` hook for the *calling thread only* and removes it on
the way out. Per-thread profiling rather than patched module attributes, for two reasons: the
runtime's own main thread uses httpx, the store clock and Ollama while emit workers run, so a
process-wide patch would break the coordinator that installed it; and `datetime.datetime.now` is an
attribute of an immutable C type that cannot be patched at all.

CPython reports a call before it runs it, so a refused call never happens. It also unsets the
profiler for the thread when a profile hook raises, so the rest of that call is unguarded. Review
CK7 finding F1 closed the two ways a connector could live in that gap: the hook records the refusal
on the thread's state before raising and `forbid_effects` raises the record on the way out, so a
swallowed refusal still fails the sync, even when the body goes on to raise an ordinary exception
of its own (confirmation finding N1); and `EmitSideEffect` is a `BaseException`, so an ordinary
broad `except` never catches it in the first place. The refusal a guard reports is therefore the
*first* forbidden call of that region, exactly one per `emit` call.
"""

from __future__ import annotations

import datetime
import importlib
import socket
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from types import CodeType, ModuleType

REFUSAL = "emit must not touch the network, a model, a subprocess, a thread or the clock"

# The whole forbidden set, in one sorted table: plan section 10.1's names plus m20's. Nothing is
# added here without a ruling, and `tests/unit/test_connector_guard.py` pins it byte for byte.
FORBIDDEN_CALLS: tuple[str, ...] = (
    "_posixsubprocess.fork_exec",
    "_thread.start_new_thread",
    "datetime.date.today",
    "datetime.datetime.now",
    "datetime.datetime.utcnow",
    "hippo.ollama.Ollama._chat",
    "hippo.ollama.Ollama.chat_json",
    "hippo.ollama.Ollama.chat_text",
    "hippo.ollama.Ollama.embed",
    "hippo.ollama.Ollama.embed_explicit",
    "hippo.ollama.Ollama.embed_one",
    "hippo.ollama.Ollama.pull",
    "httpx.AsyncClient.send",
    "httpx.Client.send",
    "os.execl",
    "os.execle",
    "os.execlp",
    "os.execlpe",
    "os.execv",
    "os.execve",
    "os.execvp",
    "os.execvpe",
    "os.fork",
    "os.posix_spawn",
    "os.posix_spawnp",
    "os.system",
    "socket.getaddrinfo",
    "socket.socket.connect",
    "socket.socket.connect_ex",
    "sys.setprofile",
    "threading.Thread.start",
    "threading.setprofile",
    "time.clock_gettime",
    "time.clock_gettime_ns",
    "time.gmtime",
    "time.localtime",
    "time.monotonic",
    "time.monotonic_ns",
    "time.perf_counter",
    "time.perf_counter_ns",
    "time.process_time",
    "time.process_time_ns",
    "time.sleep",
    "time.thread_time",
    "time.thread_time_ns",
    "time.time",
    "time.time_ns",
)

# Three of the names above resolve to a method bound to an instance or a type rather than to a
# module-level callable, so the hook recognizes them by name and owner instead of by identity:
# `socket.connect` is a fresh object per socket, and `now`/`utcnow`/`today` must also be refused on
# a *subclass* of `datetime.date` that a connector defines to smuggle the clock in.
_SOCKET_METHODS = frozenset({"connect", "connect_ex"})
_DATE_CONSTRUCTORS = frozenset({"now", "utcnow", "today"})
_WATCHED_METHODS = _SOCKET_METHODS | _DATE_CONSTRUCTORS
_OWNER_MATCHED = frozenset(
    {
        "socket.socket.connect",
        "socket.socket.connect_ex",
        "datetime.date.today",
        "datetime.datetime.now",
        "datetime.datetime.utcnow",
    }
)


class EmitSideEffect(BaseException):
    """emit touched the network, a model, a subprocess, a thread or the clock.

    Review CK7 finding F1: a `BaseException` rather than a `RuntimeError`, so the ordinary broad
    `except Exception` a third-party `emit` may well carry cannot catch the refusal. The two call
    sites that must see it name the class (`sync._emit`, `testing.assert_emit_pure`) and both name
    it before their broad handlers.
    """


def _resolve(dotted: str) -> object:
    """Find the callable a dotted name in `FORBIDDEN_CALLS` denotes, wherever the module boundary is."""
    parts = dotted.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        try:
            found: object = importlib.import_module(".".join(parts[:cut]))
        except ImportError:
            continue
        for name in parts[cut:]:
            found = getattr(found, name)
        return found
    raise LookupError(f"The forbidden call {dotted} names no importable module")


def _partition() -> tuple[dict[object, str], dict[CodeType, str]]:
    """Split the table into the two things a profile event can be compared against.

    Each half maps the matchable object back to its `FORBIDDEN_CALLS` spelling, so a refusal names
    the entry an operator can look up rather than the module the callable happens to live in
    (`os.fork` reports `__module__ == "posix"`).
    """
    functions: dict[object, str] = {}
    codes: dict[CodeType, str] = {}
    for dotted in FORBIDDEN_CALLS:
        found = _resolve(dotted)
        code = getattr(found, "__code__", None)
        if code is not None:
            codes[code] = dotted  # a Python function: matched by its code object
        elif dotted not in _OWNER_MATCHED:
            functions[found] = dotted  # a module-level C callable: matched by identity
    return functions, codes


_FORBIDDEN_FUNCTIONS, _FORBIDDEN_CODE = _partition()

# Per thread, because `sys.setprofile` is per thread. A ContextVar would follow a `copy_context()`
# onto a thread that never entered the guard.
_state = threading.local()


def _qualified(call: object) -> str:
    module = getattr(call, "__module__", None)
    qualname = getattr(call, "__qualname__", None) or getattr(call, "__name__", None) or repr(call)
    return f"{module}.{qualname}" if module else qualname


def _refused_c_call(call: object) -> str | None:
    owner = getattr(call, "__self__", None)
    if isinstance(owner, ModuleType):
        # Every identity-matched entry is bound to its module (`os.fork.__self__` is `posix`), and
        # only those are hashable for sure: `[].append.__hash__` raises, and this runs on every C
        # call the guarded thread makes.
        return _FORBIDDEN_FUNCTIONS.get(call)
    if getattr(call, "__name__", "") not in _WATCHED_METHODS:
        return None
    name = call.__name__
    # These two families are matched by owner, so the refusal names the object actually called: the
    # socket, or the `datetime.date` subclass a connector defined to smuggle the clock in.
    if name in _SOCKET_METHODS and isinstance(owner, socket.socket):
        return _qualified(call)
    if name in _DATE_CONSTRUCTORS and isinstance(owner, type) and issubclass(owner, datetime.date):
        return _qualified(call)
    return None


def _hook(frame, event, arg):
    if not getattr(_state, "armed", False):
        return None
    if event == "c_call":
        refused = _refused_c_call(arg)
    elif event == "call":
        refused = _FORBIDDEN_CODE.get(frame.f_code)
    else:
        return None
    if refused is not None:
        # F1: recorded before it is raised, because CPython unsets the profiler for this thread as
        # soon as this hook raises. Whatever the connector does with the exception, `forbid_effects`
        # finds the record on the way out.
        _state.violation = f"emit called {refused}; {REFUSAL}"
        raise EmitSideEffect(_state.violation)
    return None


@contextmanager
def forbid_effects() -> Iterator[None]:
    """Refuse every forbidden call made by this thread until the block ends.

    Re-entrant: a nested guard restores and re-arms the enclosing one, and any profiler that was
    installed before the outermost guard is put back untouched. `armed` brackets the two
    `sys.setprofile` calls because `sys.setprofile` is itself forbidden (m20): without it, leaving
    the guard would trip the guard.

    Review CK7 finding F1: a refusal the body swallowed is raised here instead, so a guarded region
    that made a forbidden call fails however the body treated the exception. An enclosing guard's
    record is saved and put back, so a nested guard cannot clear it.

    Confirmation finding N1: the swallowed refusal also outranks an ordinary exception the body
    raises afterwards, which becomes its `__cause__`; otherwise `sync._emit` would count that
    exception as a parse failure and publish. Only the refusal itself and `KeyboardInterrupt` or
    `SystemExit` propagate unchanged.
    """
    previous = sys.getprofile()
    enclosing = getattr(_state, "violation", None)
    _state.violation = None
    _state.armed = False
    sys.setprofile(_hook)
    _state.armed = True
    in_flight: BaseException | None = None
    try:
        yield
    except BaseException as error:
        in_flight = error
        raise
    finally:
        _state.armed = False
        sys.setprofile(previous)
        _state.armed = previous is _hook
        swallowed = _state.violation
        _state.violation = enclosing
        if swallowed is not None and not isinstance(
            in_flight, (EmitSideEffect, KeyboardInterrupt, SystemExit)
        ):
            raise EmitSideEffect(swallowed) from in_flight
