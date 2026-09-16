"""The emit guard: one per-thread `sys.setprofile` hook that refuses effects inside `emit`.

Plan `ai_docs/plans/cdk-s3-runtime.md` sections 4.1 and 10.1, with ruling B3/R49 (this is the ONE
guard; `testing.purity_guard` is this function and nothing patches the process) and review minor m20
(the forbidden set also names `time.clock_gettime`, `time.clock_gettime_ns`, the process and thread
clocks in both spellings (ruling R65),
`time.sleep`, thread start, `os.fork`, `os.posix_spawn`, `time.localtime`, `sys.setprofile` and
`threading.setprofile`).

Every case builds its effect *outside* the guard, so what the guard refuses is the call itself and
not the setup around it. The fork and spawn cases are written so that a broken guard fails cleanly
rather than forking the test session.
"""

import _thread
import contextlib
import datetime
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
from time import time as _imported_time

import httpx
import pytest

from hippo.connectors import guard
from hippo.connectors.guard import EmitSideEffect, forbid_effects
from hippo.ollama import Ollama

_INSTANCE = "http://provider.invalid"
_REFUSAL = "emit must not touch the network, a model, a subprocess, a thread or the clock"

# The whole contract, in one table. Plan section 10.1's set plus m20's names, and nothing else.
# Ruling R65 closed the S3a evidence's question 1 by reading m20 as "the process and thread
# clocks", so `time.process_time_ns`, `time.thread_time` and `time.thread_time_ns` are named too.
EXPECTED_FORBIDDEN_CALLS = (
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


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True})


def _refuses(effect) -> bool:
    """Run `effect` inside an already-entered guard and report whether it was refused."""
    try:
        effect()
    except EmitSideEffect:
        return True
    return False


def _ollama(stack: contextlib.ExitStack) -> Ollama:
    client = stack.enter_context(httpx.Client(transport=httpx.MockTransport(_ok), base_url=_INSTANCE))
    return Ollama(_INSTANCE, "llm", "embed", client=client)


def _socket_connect(stack):
    sock = stack.enter_context(socket.socket())
    return lambda: sock.connect(("127.0.0.1", 9))


def _socket_connect_ex(stack):
    sock = stack.enter_context(socket.socket())
    return lambda: sock.connect_ex(("127.0.0.1", 9))


def _getaddrinfo(stack):
    return lambda: socket.getaddrinfo("localhost", 80)


def _httpx_client(stack):
    client = stack.enter_context(httpx.Client(transport=httpx.MockTransport(_ok), base_url=_INSTANCE))
    return lambda: client.get("/notes/1")


def _httpx_async_client(stack):
    client = httpx.AsyncClient(transport=httpx.MockTransport(_ok), base_url=_INSTANCE)
    request = client.build_request("GET", "/notes/1")

    def effect():
        coro = client.send(request)
        try:
            coro.send(None)
        finally:
            coro.close()

    return effect


def _ollama_chat_json(stack):
    ollama = _ollama(stack)
    return lambda: ollama.chat_json([{"role": "user", "content": "hi"}], {"type": "object"})


def _ollama_embed(stack):
    ollama = _ollama(stack)
    return lambda: ollama.embed(["a passage"])


def _subprocess_run(stack):
    return lambda: subprocess.run(["/bin/echo", "hi"], capture_output=True, check=False)


def _os_system(stack):
    return lambda: os.system("true")


def _os_fork(stack):
    def effect():
        pid = os.fork()
        if pid == 0:  # pragma: no cover - only reached when the guard is broken
            os._exit(0)
        os.waitpid(pid, 0)

    return effect


def _os_posix_spawn(stack):
    return lambda: os.posix_spawn("/nonexistent", ["/nonexistent"], {})


def _thread_start(stack):
    return threading.Thread(target=lambda: None).start


def _thread_start_new_thread(stack):
    return lambda: _thread.start_new_thread(lambda: None, ())


def _sys_setprofile(stack):
    return lambda: sys.setprofile(None)


def _threading_setprofile(stack):
    stack.callback(threading.setprofile, None)
    return lambda: threading.setprofile(None)


def _date_subclass_today(stack):
    class Yesterday(datetime.date):
        pass

    return Yesterday.today


# id -> (builder, the qualified names any one of which the refusal may name)
EFFECTS = {
    "socket_connect": (_socket_connect, ("socket.connect",)),
    "socket_connect_ex": (_socket_connect_ex, ("socket.connect_ex",)),
    "getaddrinfo": (_getaddrinfo, ("getaddrinfo",)),
    "httpx_client": (_httpx_client, ("Client.send",)),
    "httpx_async_client": (_httpx_async_client, ("AsyncClient.send",)),
    "ollama_chat_json": (_ollama_chat_json, ("Ollama.chat_json",)),
    "ollama_embed": (_ollama_embed, ("Ollama.embed",)),
    "subprocess_run": (_subprocess_run, ("fork_exec", "posix_spawn")),
    "os_system": (_os_system, ("os.system",)),
    "os_fork": (_os_fork, ("os.fork",)),
    "os_posix_spawn": (_os_posix_spawn, ("os.posix_spawn",)),
    "thread_start": (_thread_start, ("Thread.start",)),
    "thread_start_new_thread": (_thread_start_new_thread, ("start_new_thread",)),
    "sys_setprofile": (_sys_setprofile, ("sys.setprofile",)),
    "threading_setprofile": (_threading_setprofile, ("setprofile",)),
    "time_time": (lambda stack: time.time, ("time.time",)),
    "time_monotonic": (lambda stack: time.monotonic, ("time.monotonic",)),
    "perf_counter": (lambda stack: time.perf_counter, ("time.perf_counter",)),
    "from_time_import_time": (lambda stack: _imported_time, ("time.time",)),
    "time_sleep": (lambda stack: lambda: time.sleep(0), ("time.sleep",)),
    "clock_gettime": (
        lambda stack: lambda: time.clock_gettime(time.CLOCK_MONOTONIC),
        ("time.clock_gettime",),
    ),
    "clock_gettime_ns": (
        lambda stack: lambda: time.clock_gettime_ns(time.CLOCK_MONOTONIC),
        ("time.clock_gettime_ns",),
    ),
    "process_time": (lambda stack: time.process_time, ("time.process_time",)),
    # Ruling R65: the process and thread clocks in both spellings.
    "process_time_ns": (lambda stack: time.process_time_ns, ("time.process_time_ns",)),
    "thread_time": (lambda stack: time.thread_time, ("time.thread_time",)),
    "thread_time_ns": (lambda stack: time.thread_time_ns, ("time.thread_time_ns",)),
    "localtime": (lambda stack: time.localtime, ("time.localtime",)),
    "datetime_now": (lambda stack: datetime.datetime.now, ("datetime.now",)),
    "datetime_utcnow": (lambda stack: datetime.datetime.utcnow, ("datetime.utcnow",)),
    "date_today": (lambda stack: datetime.date.today, ("date.today",)),
    "date_subclass_today": (_date_subclass_today, ("today",)),
}


@pytest.fixture
def resources():
    with contextlib.ExitStack() as stack:
        yield stack


@pytest.mark.parametrize("case", sorted(EFFECTS))
def test_the_guard_refuses(case, resources) -> None:
    builder, expected_names = EFFECTS[case]
    effect = builder(resources)

    with pytest.raises(EmitSideEffect) as caught:
        with forbid_effects():
            effect()

    message = str(caught.value)
    assert message.startswith("emit called ")
    assert _REFUSAL in message
    assert any(name in message for name in expected_names), message
    assert sys.getprofile() is None


def test_the_guard_allows_pure_computation_json_and_hashing() -> None:
    with forbid_effects():
        payload = json.dumps({"b": [2, 3], "a": 1}, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        squares = sum(index * index for index in range(64))
        text = "note".upper().replace("O", "0")

    assert payload == '{"a":1,"b":[2,3]}'
    assert digest == hashlib.sha256(b'{"a":1,"b":[2,3]}').hexdigest()
    assert squares == 85344
    assert text == "N0TE"


def test_the_guard_affects_only_the_entering_thread() -> None:
    entered = threading.Event()
    gate = threading.Lock()
    gate.acquire()
    seen: dict[str, object] = {}

    def worker() -> None:
        try:
            with forbid_effects():
                seen["worker_profiler"] = sys.getprofile() is not None
                entered.set()
                gate.acquire()  # blocks without reading a clock
                seen["worker_refused"] = _refuses(_imported_time)
        except EmitSideEffect:
            seen["worker_reraised"] = True  # F1: `_refuses` swallowed it, the guard raises it again
        seen["worker_profiler_after"] = sys.getprofile()

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert entered.wait(10)
        # The main thread is inside no guard while the worker is inside one.
        assert sys.getprofile() is None
        assert isinstance(_imported_time(), float)
        assert isinstance(datetime.datetime.now(datetime.UTC), datetime.datetime)
    finally:
        gate.release()
        thread.join(10)

    assert seen == {
        "worker_profiler": True,
        "worker_refused": True,
        "worker_reraised": True,
        "worker_profiler_after": None,
    }


def test_the_guard_is_removed_after_a_violation_and_after_a_normal_exit() -> None:
    assert sys.getprofile() is None

    with pytest.raises(EmitSideEffect):
        with forbid_effects():
            _imported_time()
    assert sys.getprofile() is None

    with forbid_effects():
        pass
    assert sys.getprofile() is None

    assert isinstance(_imported_time(), float)


def test_the_guard_nests_and_restores_a_previous_profiler() -> None:
    events: list[str] = []

    def previous(frame, event, arg) -> None:
        events.append(event)

    sys.setprofile(previous)
    try:
        # F1: the outer guard raises the refusal `_refuses` swallowed, after restoring `previous`.
        with pytest.raises(EmitSideEffect):
            with forbid_effects():
                assert sys.getprofile() is not previous
                with forbid_effects():
                    inner_profiler = sys.getprofile()
                # Leaving the inner guard re-arms the outer one rather than clearing it.
                assert sys.getprofile() is inner_profiler
                refused = _refuses(_imported_time)
        assert sys.getprofile() is previous
        events.clear()
        len([])
        assert events, "the previous profiler stopped receiving events"
    finally:
        sys.setprofile(None)

    assert refused


def test_the_forbidden_set_is_the_plans_names_plus_m20s() -> None:
    assert guard.FORBIDDEN_CALLS == EXPECTED_FORBIDDEN_CALLS
    assert guard.FORBIDDEN_CALLS == tuple(sorted(set(guard.FORBIDDEN_CALLS)))


def test_the_guard_never_patches_a_module_attribute() -> None:
    """B3/R49: the guard is per thread; it leaves every named callable exactly where it was."""
    watched = (time.time, time.sleep, os.fork, os.system, sys.setprofile, socket.getaddrinfo)
    before = (httpx.Client.send, Ollama.embed, threading.Thread.start, datetime.datetime.now)

    with forbid_effects():
        during = (time.time, time.sleep, os.fork, os.system, sys.setprofile, socket.getaddrinfo)
        during_functions = (httpx.Client.send, Ollama.embed, threading.Thread.start, datetime.datetime.now)

    assert during == watched
    assert during_functions == before
    assert (time.time, time.sleep, os.fork, os.system, sys.setprofile, socket.getaddrinfo) == watched
    assert (httpx.Client.send, Ollama.embed, threading.Thread.start, datetime.datetime.now) == before


# ------------------------------------------------------------------ F1: a swallowed refusal


def test_the_refusal_is_not_an_ordinary_exception() -> None:
    """CK7 F1: an ordinary broad `except` in a connector's `emit` must not catch the refusal."""
    assert issubclass(EmitSideEffect, BaseException)
    assert not issubclass(EmitSideEffect, Exception)

    caught_broadly = None
    with pytest.raises(EmitSideEffect):
        with forbid_effects():
            try:
                _imported_time()
            except Exception as error:  # noqa: BLE001 - the connector's own retry, as F1 describes
                caught_broadly = error

    assert caught_broadly is None
    assert sys.getprofile() is None


def test_a_swallowed_violation_still_leaves_the_guard() -> None:
    """CK7 F1: CPython unsets the profiler when a hook raises, so the rest of the call is unguarded.

    The guard records the refusal before raising it and re-raises it on the way out, so an `emit`
    that swallows it - here with the `except BaseException` that is the only way left to swallow it
    at all - still fails.
    """
    swallowed = False

    with pytest.raises(EmitSideEffect) as caught:
        with forbid_effects():
            try:
                _imported_time()
            except BaseException:  # noqa: BLE001 - a connector determined to swallow the refusal
                swallowed = True

    assert swallowed
    assert str(caught.value).startswith("emit called ")
    assert "time.time" in str(caught.value)
    assert _REFUSAL in str(caught.value)
    assert sys.getprofile() is None


def test_the_guard_reports_one_violation_per_emit_call() -> None:
    """Ruling R65, honestly: the profiler is gone after the first refusal, so the second is unseen.

    The violation the guard reports is therefore the first forbidden call of that `emit`, and there
    is exactly one of them however many the connector goes on to make.
    """
    second_call_ran = False

    with pytest.raises(EmitSideEffect) as caught:
        with forbid_effects():
            try:
                _imported_time()
            except BaseException:  # noqa: BLE001 - a connector determined to swallow the refusal
                pass
            # Unguarded, because CPython unset the profiler when the hook raised.
            os.getpid()
            second_call_ran = True
            datetime.datetime.now(datetime.UTC)

    assert second_call_ran
    assert "time.time" in str(caught.value)
    assert "datetime" not in str(caught.value)
    assert sys.getprofile() is None


def test_a_swallowed_violation_does_not_leak_into_the_next_guard() -> None:
    with pytest.raises(EmitSideEffect):
        with forbid_effects():
            try:
                _imported_time()
            except BaseException:  # noqa: BLE001 - a connector determined to swallow the refusal
                pass

    with forbid_effects():
        assert json.dumps({"pure": True}) == '{"pure": true}'
    assert sys.getprofile() is None


def test_a_propagating_violation_is_not_raised_a_second_time_on_the_way_out() -> None:
    """The recorded refusal is cleared by the guard that raised it, whichever path raised it."""
    with pytest.raises(EmitSideEffect):
        with forbid_effects():
            _imported_time()

    with forbid_effects():
        pass
    assert sys.getprofile() is None


def test_an_unrelated_failure_inside_the_guard_still_propagates() -> None:
    """Nothing is raised on the way out when the body is already failing for its own reason."""
    with pytest.raises(ValueError, match="the connector's own bug"):
        with forbid_effects():
            raise ValueError("the connector's own bug")
    assert sys.getprofile() is None


def test_a_swallowed_refusal_outranks_a_later_ordinary_failure() -> None:
    """CK7 confirmation N1: a body that swallowed the refusal and then fails still fails with it.

    Without this, the ordinary exception reaches `sync._emit`'s broad handler as a parse failure,
    is counted as `emit_failed`, and the run publishes. The ordinary exception is kept as the cause.
    """
    with pytest.raises(EmitSideEffect) as caught:
        with forbid_effects():
            try:
                _imported_time()
            except BaseException:  # noqa: BLE001 - a connector determined to swallow the refusal
                pass
            raise ValueError("the connector's own parse failure")

    assert "time.time" in str(caught.value)
    assert isinstance(caught.value.__cause__, ValueError)
    assert str(caught.value.__cause__) == "the connector's own parse failure"
    assert sys.getprofile() is None


def test_a_swallowed_violation_fails_assert_emit_pure() -> None:
    """CK7 F1: `hippo connector validate` catches the swallowing connector too."""
    from hippo.connectors.testing import ContractViolation, assert_emit_pure

    class _Swallowing:
        def emit(self, revision, mapping):
            try:
                _imported_time()
            except BaseException:  # noqa: BLE001 - a connector determined to swallow the refusal
                pass
            return "a batch this connector never gets to return"

    with pytest.raises(ContractViolation) as caught:
        assert_emit_pure(_Swallowing(), object(), object())

    assert caught.value.assertion == "emit_pure"
    assert "time.time" in str(caught.value)
    assert sys.getprofile() is None


def test_a_nested_guard_does_not_clear_the_enclosing_guards_record() -> None:
    """F1: the record belongs to the region that made the call, not to the thread's last guard."""
    with pytest.raises(EmitSideEffect) as caught:
        with forbid_effects():
            try:
                _imported_time()
            except BaseException:  # noqa: BLE001 - a connector determined to swallow the refusal
                pass
            with forbid_effects():  # a nested region that is itself clean
                json.dumps({"pure": True})

    assert "time.time" in str(caught.value)
    assert sys.getprofile() is None
