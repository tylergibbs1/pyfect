"""The live ``Terminal``: standard input read as lines or key presses,
standard output for display (the counterpart of Effect's Node terminal).

Input is read from the file descriptor in short waits on a worker thread,
straight into a buffer the terminal keeps, so an interrupted read loses
nothing and later reads see every byte. Key input puts a TTY in raw mode
while a ``read_input`` scope is open; ``read_line`` leaves it as it is."""

from __future__ import annotations

import codecs
import os
import select
import sys
import threading
from collections.abc import Callable, Generator
from typing import Any, Never, TextIO

from pyfect._core import Effect
from pyfect.effect import blocking, gen, sync, try_blocking
from pyfect.errors import Done
from pyfect.platform_error import PlatformError, bad_argument
from pyfect.queue import Dequeue, Queue
from pyfect.scope import Scope, acquire_release
from pyfect.terminal._keys import decode
from pyfect.terminal._service import QuitError, TerminalService, UserInput, default_should_quit

_WAIT = 0.05
"""Seconds one read waits for input before giving the fiber back."""


class _Input:
    """Bytes read from standard input that no reader has taken yet."""

    __slots__ = ("_fd", "_filling", "_lock", "buffer", "ended")

    def __init__(self, fd: Callable[[], int]) -> None:
        self._fd = fd
        self._lock = threading.Lock()
        # One reader of the descriptor at a time, so bytes reach the buffer
        # in the order they were read.
        self._filling = threading.Lock()
        self.buffer = bytearray()
        self.ended = False

    def fill(self) -> None:
        """Wait a moment for input and keep what arrives (on a worker
        thread)."""
        with self._filling:
            if self.ended:
                return
            try:
                fd = self._fd()
                if os.name != "nt" and not select.select([fd], [], [], _WAIT)[0]:
                    return
                data = os.read(fd, 4096)
            except (OSError, ValueError):
                data = b""
            with self._lock:
                if data:
                    self.buffer += data
                else:
                    self.ended = True

    def take_line(self) -> str | None:
        """The next line without its line break; at the end of input, what
        is left (an unterminated last line)."""
        with self._lock:
            end = self.buffer.find(b"\n")
            if end >= 0:
                line = bytes(self.buffer[:end])
                del self.buffer[: end + 1]
            elif self.ended and self.buffer:
                line = bytes(self.buffer)
                self.buffer.clear()
            else:
                return None
        return line.decode(errors="replace").removesuffix("\r")

    def take_all(self) -> bytes:
        with self._lock:
            data = bytes(self.buffer)
            self.buffer.clear()
            return data


class _RawMode:
    """A TTY's raw mode, held while any key reader needs it (libuv's raw
    mode: no echo, no line editing, no signals)."""

    __slots__ = ("_fd", "_saved", "_users")

    def __init__(self, fd: Callable[[], int]) -> None:
        self._fd = fd
        self._users = 0
        self._saved: list[Any] | None = None

    def acquire(self) -> None:
        self._users += 1
        if self._users > 1:
            return
        try:
            import termios

            fd = self._fd()
            if not os.isatty(fd):
                return
            saved = termios.tcgetattr(fd)
            raw = termios.tcgetattr(fd)
            raw[0] &= ~(termios.BRKINT | termios.ICRNL | termios.INPCK | termios.ISTRIP)
            raw[0] &= ~termios.IXON
            raw[1] |= termios.ONLCR
            raw[2] |= termios.CS8
            raw[3] &= ~(termios.ECHO | termios.ICANON | termios.IEXTEN | termios.ISIG)
            termios.tcsetattr(fd, termios.TCSADRAIN, raw)
            self._saved = saved
        except (ImportError, OSError, ValueError):
            return

    def release(self) -> None:
        self._users -= 1
        if self._users > 0 or self._saved is None:
            return
        import termios

        saved, self._saved = self._saved, None
        try:
            termios.tcsetattr(self._fd(), termios.TCSADRAIN, saved)
        except (OSError, ValueError):
            return


def _size(output: TextIO) -> os.terminal_size | None:
    try:
        return os.get_terminal_size(output.fileno())
    except (OSError, ValueError, AttributeError):
        return None


def live(
    *,
    should_quit: Callable[[UserInput], bool] = default_should_quit,
    input: int | None = None,
    output: TextIO | None = None,
) -> TerminalService:
    """A terminal over the file descriptor ``input`` and the text stream
    ``output`` (standard input and output, looked up when used). A key
    press for which ``should_quit`` is true ends ``read_input``'s queue
    after it is delivered."""

    def input_fd() -> int:
        return sys.stdin.fileno() if input is None else input

    def out() -> TextIO:
        return sys.stdout if output is None else output

    source = _Input(input_fd)
    raw_mode = _RawMode(input_fd)
    fill = blocking(source.fill)

    def read_line() -> Generator[Effect[Any, QuitError], Any, str]:
        while True:
            line = source.take_line()
            if line is not None:
                return line
            if source.ended:
                return (yield from QuitError())
            yield from fill

    def read_input() -> Generator[Effect[Any, Never, Scope], Any, Dequeue[UserInput, Done]]:
        queue = yield from Queue[UserInput, Done].unbounded()
        yield from acquire_release(sync(raw_mode.acquire), lambda _a, _e: sync(raw_mode.release))
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

        def pump() -> Generator[Effect[Any], Any]:
            while True:
                data = source.take_all()
                if data:
                    for event in decode(decoder.decode(data)):
                        yield from queue.offer(event)
                        if should_quit(event):
                            yield from queue.end()
                            return
                elif source.ended:
                    yield from queue.end()
                    return
                else:
                    yield from fill

        yield from gen(pump).fork_scoped()
        return queue

    def write(text: str) -> None:
        target = out()
        target.write(text)
        target.flush()

    def display(text: str) -> Effect[None, PlatformError]:
        return try_blocking(
            lambda: write(text),
            lambda cause: bad_argument(
                module="Terminal",
                method="display",
                description="Failed to write prompt to stdout",
                cause=cause,
            ),
        ).uninterruptible()

    def columns() -> int:
        size = _size(out())
        return 0 if size is None else size.columns

    def rows() -> int:
        size = _size(out())
        return 0 if size is None else size.lines

    return TerminalService(
        columns=sync(columns),
        rows=sync(rows),
        read_input=gen(read_input),
        read_line=gen(read_line),
        display=display,
    )
