"""Ports of Effect's ``NodeTerminal.test.ts``.

Each test's docstring is the Effect test title. Effect runs a fixture
process over piped stdin; here the live terminal reads a pipe (or a
pseudo-terminal) passed as ``input`` in the same process, and prompts write
to an in-memory stream instead of the fixture's stdout.

Omitted, with the reason:

- ``disposes readline after its idle TTL``: pyfect installs no readline
  interface; each read takes from the terminal's own buffer, so there is
  nothing to dispose.
"""

import io
import os
import sys
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

import pytest

import pyfect as fx
from pyfect import file_system, layer, path, terminal, testing
from pyfect.cli import prompt
from pyfect.cli.prompt import Choice
from pyfect.terminal import QuitError, Terminal, TerminalService, UserInput


@contextmanager
def _pipe(data: bytes, *, close: bool = True) -> Generator[int]:
    """A pipe holding ``data`` (its writer closed unless ``close`` is
    false); yields the read end."""
    read, write = os.pipe()
    os.write(write, data)
    if close:
        os.close(write)
    try:
        yield read
    finally:
        os.close(read)
        if not close:
            os.close(write)


def _terminal(fd: int) -> TerminalService:
    return terminal.live(input=fd, output=io.StringIO())


def test_does_not_install_a_readline_interface_until_the_terminal_is_used():
    """does not install a readline interface until the terminal is used"""
    with _pipe(b"untouched") as fd:
        _terminal(fd)
        assert os.read(fd, 100) == b"untouched"


@testing.live
def test_delivers_buffered_keypresses_before_ending_the_input_queue():
    """delivers buffered keypresses before ending the input queue"""
    with _pipe(b"yn") as fd:
        queue = yield from _terminal(fd).read_input
        first = yield from queue.take()
        second = yield from queue.take()
        ended = yield from queue.take().flip()
    assert (first.input, second.input) == ("y", "n")
    assert isinstance(ended, fx.Done)


@testing.live
def test_flushes_an_unterminated_line_before_failing_read_line_with_quit_error_at_eof():
    """flushes an unterminated line before failing readLine with QuitError at EOF"""
    with _pipe(b"last line") as fd:
        service = _terminal(fd)
        first = yield from service.read_line
        second = yield from service.read_line.flip()
    assert first == "last line"
    assert isinstance(second, QuitError)


@testing.live
def test_preserves_lines_buffered_between_sequential_read_line_calls():
    """preserves lines buffered between sequential readLine calls"""
    with _pipe(b"first\nsecond\n") as fd:
        service = _terminal(fd)
        first = yield from service.read_line
        second = yield from service.read_line
    assert (first, second) == ("first", "second")


@testing.live
def test_fails_read_line_with_quit_error_when_stdin_ended_before_initialization():
    """fails readLine with QuitError when stdin ended before initialization"""
    with _pipe(b"") as fd:
        error = yield from _terminal(fd).read_line.flip()
    assert isinstance(error, QuitError)


_posix_only = pytest.mark.skipif(sys.platform == "win32", reason="needs a POSIX pseudo-terminal")


@contextmanager
def _pty(data: bytes) -> Generator[int]:
    """A pseudo-terminal with ``data`` typed into it; yields its terminal
    end. Echo is off, so no output waits for a reader (raw mode's
    ``TCSADRAIN`` would wait for it)."""
    import pty
    import termios

    controller, tty = pty.openpty()
    attributes = termios.tcgetattr(tty)
    attributes[3] &= ~termios.ECHO
    termios.tcsetattr(tty, termios.TCSANOW, attributes)
    os.write(controller, data)
    try:
        yield tty
    finally:
        os.close(tty)
        os.close(controller)


def _canonical(fd: int) -> bool:
    import termios

    return bool(termios.tcgetattr(fd)[3] & termios.ICANON)


@_posix_only
@testing.live
def test_leaves_a_tty_in_cooked_mode_for_read_line():
    """leaves a TTY in cooked mode for readLine"""
    with _pty(b"line\n") as fd:
        line = yield from _terminal(fd).read_line
        assert _canonical(fd)
    assert line == "line"


@_posix_only
@testing.live
def test_enables_raw_mode_on_a_tty_while_reading_key_input():
    """enables raw mode on a TTY while reading key input"""
    with _pty(b"y") as fd:
        modes: list[bool] = []

        @fx.fn
        def read() -> Generator[fx.Effect[Any, Any, Any], Any, str | None]:
            queue = yield from _terminal(fd).read_input
            modes.append(not _canonical(fd))
            return (yield from queue.take()).input

        key = yield from fx.scoped(read())
        modes.append(not _canonical(fd))
    assert key == "y"
    assert modes == [True, False]


# --- prompts on the live terminal ---------------------------------------------------


class _Output(io.StringIO):
    """The prompt's output; once it rings the bell, ``on_bell`` runs once
    (the fixture submits there)."""

    def __init__(self, on_bell: Callable[[], None] | None = None) -> None:
        super().__init__()
        self._on_bell = on_bell

    def write(self, s: str, /) -> int:
        written = super().write(s)
        if self._on_bell is not None and "\x07" in s:
            on_bell, self._on_bell = self._on_bell, None
            on_bell()
        return written


def _prompt_env(
    service: TerminalService,
) -> fx.Layer[Terminal | file_system.FileSystem | path.Path]:
    return layer.merge(layer.succeed(Terminal, service), file_system.layer_noop(), path.layer)


def _select_fruit(service: TerminalService) -> fx.Effect[str]:
    select = prompt.run(
        prompt.select([Choice("Apple", "apple"), Choice("Banana", "banana")], message="Pick fruit")
    )
    return (
        select.pipe(fx.catch_tag(QuitError, lambda _: fx.succeed("QuitError")))
        .timeout_option("2 seconds")
        .map(lambda found: found.value if isinstance(found, fx.Some) else "TimedOut")
        .pipe(fx.provide(_prompt_env(service)))
    )


@testing.live
def test_bare_esc_cancels_select_with_quit_error_and_restores_the_cursor_while_stdin_remains_open():
    """bare Esc cancels Select with QuitError and restores the cursor while stdin remains open"""
    output = _Output()
    with _pipe(b"\x1b", close=False) as fd:
        result = yield from _select_fruit(terminal.live(input=fd, output=output))
    stdout = output.getvalue()
    assert result == "QuitError", repr(stdout)
    assert "\x1b[?25l" in stdout
    assert stdout.endswith("\x1b[?25h"), stdout


@testing.live
def test_an_arrow_escape_sequence_navigates_select_and_enter_submits():
    """an arrow escape sequence navigates Select and Enter submits"""
    with _pipe(b"\x1b[B\r", close=False) as fd:
        result = yield from _select_fruit(terminal.live(input=fd, output=_Output()))
    assert result == "banana"


@testing.live
def test_an_explicit_should_quit_predicate_can_keep_esc_non_cancelling():
    """an explicit shouldQuit predicate can keep Esc non-cancelling"""
    read, write = os.pipe()
    os.write(write, b"\x1b")

    def submit() -> None:
        os.write(write, b"\r")

    output = _Output(submit)

    def never_quit(_: UserInput) -> bool:
        return False

    try:
        service = terminal.live(should_quit=never_quit, input=read, output=output)
        result = yield from _select_fruit(service)
    finally:
        os.close(read)
        os.close(write)
    assert "\x07" in output.getvalue()
    assert result == "apple"


@testing.live
def test_fails_a_prompt_with_quit_error_after_piped_input_is_exhausted():
    """fails a prompt with QuitError after piped input is exhausted"""
    with _pipe(b"y\n") as fd:
        service = terminal.live(input=fd, output=_Output())
        env = _prompt_env(service)
        first = yield from prompt.run(prompt.confirm("First")).pipe(fx.provide(env))
        second = yield from prompt.run(prompt.confirm("Second")).flip().pipe(fx.provide(env))
    assert first is True
    assert isinstance(second, QuitError)
