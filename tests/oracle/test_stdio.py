"""Ports of Effect's ``Stdio.test.ts`` and ``NodeStdio.test.ts``.

Each test's docstring is the Effect test title. ``Stdio.make`` is the
``StdioService`` constructor; Node's ``isTTY`` property is ``isatty()`` on
the ``sys`` streams, replaced here with ``monkeypatch``.
"""

import io

import pytest

import pyfect as fx
from pyfect import sink, stdio, stream, testing
from pyfect.stdio import Stdio, StdioService


def _drain(*, end_on_done: bool = False) -> stdio.Output:
    return sink.drain


@testing.effect
def test_make_defaults_stderr_terminal_state_to_false():
    """make defaults stderr terminal state to false"""
    service = StdioService(
        args=fx.succeed(()),
        stdin=stream.empty,
        stdout=_drain,
        stderr=_drain,
        stdout_is_terminal=fx.succeed(True),
    )
    assert not (yield from service.stderr_is_terminal)


@testing.effect
def test_layer_test_defaults_terminal_state_to_false():
    """layerTest defaults terminal state to false"""
    service = yield from Stdio().pipe(fx.provide(stdio.layer_test()))
    assert not (yield from service.stdin_is_terminal)
    assert not (yield from service.stdout_is_terminal)
    assert not (yield from service.stderr_is_terminal)


@testing.effect
def test_layer_test_allows_terminal_state_overrides():
    """layerTest allows terminal state overrides"""
    test_layer = stdio.layer_test(
        stdin_is_terminal=fx.succeed(True),
        stdout_is_terminal=fx.succeed(True),
        stderr_is_terminal=fx.succeed(True),
    )
    service = yield from Stdio().pipe(fx.provide(test_layer))
    assert (yield from service.stdin_is_terminal)
    assert (yield from service.stdout_is_terminal)
    assert (yield from service.stderr_is_terminal)


class _Tty(io.StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


def test_reads_terminal_state_when_the_effects_run(monkeypatch: pytest.MonkeyPatch):
    """NodeStdio / reads terminal state when the effects run"""
    service = fx.run_blocking(Stdio().pipe(fx.provide(stdio.layer)))
    checks = fx.all(
        service.stdin_is_terminal, service.stdout_is_terminal, service.stderr_is_terminal
    )

    def set_tty(stdin: bool, stdout: bool, stderr: bool | None) -> None:
        monkeypatch.setattr("sys.stdin", _Tty(stdin))
        monkeypatch.setattr("sys.stdout", _Tty(stdout))
        monkeypatch.setattr("sys.stderr", None if stderr is None else _Tty(stderr))

    set_tty(False, False, True)
    assert fx.run_blocking(checks) == (False, False, True)
    set_tty(True, True, False)
    assert fx.run_blocking(checks) == (True, True, False)
    set_tty(False, True, None)
    assert not fx.run_blocking(service.stderr_is_terminal)
