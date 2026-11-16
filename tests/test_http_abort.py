"""``AbortController`` / ``AbortSignal`` listeners as a WHATWG ``AbortSignal``
runs them (Effect's clients use one): every listener runs once, a raising one
is reported without stopping the rest, a removed one or one added late never
runs. And the client's abort paths keep that when a backend's listener raises."""

import ast
import gc
import logging
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect.http import client, response
from pyfect.http.abort import AbortController, AbortSignal
from pyfect.http.request import HttpClientRequest


def _raise() -> None:
    raise RuntimeError("listener failed")


def test_a_raising_listener_is_logged_and_the_others_still_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    controller = AbortController()
    runs: list[str] = []
    controller.signal.add_listener(lambda: runs.append("first"))
    controller.signal.add_listener(_raise)
    controller.signal.add_listener(lambda: runs.append("third"))
    with caplog.at_level(logging.ERROR, "pyfect.http.abort"):
        controller.abort()
    assert runs == ["first", "third"]
    [record] = caplog.records
    assert record.exc_info is not None
    assert str(record.exc_info[1]) == "listener failed"


def test_a_listener_added_after_the_abort_never_runs() -> None:
    controller = AbortController()
    controller.abort()
    runs: list[str] = []
    remove = controller.signal.add_listener(lambda: runs.append("late"))
    remove()
    assert runs == []


def test_on_abort_runs_a_listener_added_after_the_abort_at_once() -> None:
    controller = AbortController()
    runs: list[str] = []
    controller.signal.on_abort(lambda: runs.append("before"))
    controller.abort()
    controller.signal.on_abort(lambda: runs.append("late"))
    assert runs == ["before", "late"]


def test_a_listener_removed_or_added_during_the_abort_does_not_run() -> None:
    controller = AbortController()
    runs: list[str] = []
    removers: list[Any] = []

    def first() -> None:
        runs.append("first")
        removers[0]()
        controller.signal.add_listener(lambda: runs.append("added during"))

    controller.signal.add_listener(first)
    removers.append(controller.signal.add_listener(lambda: runs.append("removed")))
    controller.abort()
    controller.abort()
    assert runs == ["first"]


def test_a_listener_added_twice_runs_once_and_removing_either_removes_it() -> None:
    controller = AbortController()
    runs: list[str] = []

    def listener() -> None:
        runs.append("ran")

    controller.signal.add_listener(listener)
    controller.signal.add_listener(listener)
    controller.abort()
    assert runs == ["ran"]

    other = AbortController()
    other.signal.add_listener(listener)
    other.signal.add_listener(listener)()
    other.abort()
    assert runs == ["ran"]


def _backend(seen: list[str], answer: str = "body") -> client.HttpClientService[Any]:
    def send(request: HttpClientRequest, url: Any, signal: AbortSignal, fiber: Any) -> Any:
        signal.add_listener(_raise)
        signal.add_listener(lambda: seen.append("cleaned"))
        return fx.never if answer == "hang" else fx.succeed(response.make(request, answer))

    return client.make(send)


def test_a_scoped_request_succeeds_and_cleans_up_when_a_listener_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: list[str] = []
    program = fx.scoped(_backend(seen).with_scope().get("http://x/").map(lambda r: r.status))
    with caplog.at_level(logging.ERROR, "pyfect.http.abort"):
        assert fx.run_blocking(program) == 200
    assert seen == ["cleaned"]
    assert len(caplog.records) == 1


def test_a_timed_out_or_dropped_request_cleans_up_when_a_listener_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    timed_out: list[str] = []
    dropped: list[str] = []
    with caplog.at_level(logging.ERROR, "pyfect.http.abort"):
        fx.run_blocking_exit(_backend(timed_out, "hang").get("http://x/").timeout("20 millis"))
        fx.run_blocking(_backend(dropped).get("http://x/").as_void())
        gc.collect()
    assert (timed_out, dropped) == (["cleaned"], ["cleaned"])
    assert len(caplog.records) == 2


_SRC = Path(__file__).resolve().parents[1] / "src" / "pyfect"


def test_pyfect_listens_on_signals_with_on_abort() -> None:
    """``add_listener`` never runs for a signal that already fired, so a backend
    handed an aborted signal (``with_scope`` after its scope closed, an interrupt
    racing a response) would keep running: pyfect's own code uses ``on_abort``."""
    calls = [
        f"{path.relative_to(_SRC)}:{node.lineno}"
        for path in _SRC.rglob("*.py")
        if path.name != "abort.py"
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute) and node.attr == "add_listener"
    ]
    assert calls == []
