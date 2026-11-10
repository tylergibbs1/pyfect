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
from pyfect._os_wait import os_wait
from pyfect.effect import blocking, gen, sync, try_blocking, void
from pyfect.errors import Done
from pyfect.platform_error import PlatformError, bad_argument
from pyfect.queue import Dequeue, Queue
from pyfect.scope import Scope, acquire_release
from pyfect.terminal._keys import ESCAPE_CODE_TIMEOUT, KeyDecoder
from pyfect.terminal._resize import resizes
from pyfect.terminal._service import (
    QuitError,
    Size,
    TerminalService,
    UserInput,
    default_should_quit,
)

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

    def fill(self, wait: float = _WAIT) -> None:
        """Wait up to ``wait`` seconds for input and keep what arrives (on a
        worker thread)."""
        with self._filling:
            if self.ended:
                return
            try:
                fd = self._fd()
                if os.name != "nt" and not select.select([fd], [], [], wait)[0]:
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

    def waiting(self) -> bool:
        """Bytes are waiting or the input has ended."""
        with self._lock:
            return bool(self.buffer) or self.ended

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


class _Wake:
    """Wakes one waiting fiber from any thread; a wake with nobody waiting
    is kept for the next wait."""

    __slots__ = ("_lock", "_pending", "_resume")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._resume: Callable[[Effect[None]], None] | None = None
        self._pending = False

    def notify(self) -> None:
        with self._lock:
            resume, self._resume = self._resume, None
            if resume is None:
                self._pending = True
        if resume is not None:
            resume(void)

    def wait(self) -> Effect[None]:
        def register(resume: Callable[[Effect[None]], None]) -> Callable[[], None] | None:
            with self._lock:
                if not self._pending:
                    self._resume = resume
                    return self._cancel
                self._pending = False
            resume(void)
            return None

        return os_wait(register, waits_for="event")

    def _cancel(self) -> None:
        with self._lock:
            self._resume = None


def _size(output: TextIO) -> os.terminal_size | None:
    try:
        return os.get_terminal_size(output.fileno())
    except (OSError, ValueError, AttributeError):
        return None


def _sizes(current: Callable[[], Size]) -> Effect[Dequeue[Size, Done], Never, Scope]:
    """A queue of the current size, then the latest after each resize
    until the scope closes (Node's ``resize`` listener)."""

    def size() -> Generator[Effect[Any, Never, Scope], Any, Dequeue[Size, Done]]:
        queue = yield from Queue[Size, Done].sliding(1)
        wake = _Wake()

        def pump() -> Generator[Effect[Any], Any]:
            while True:
                yield from wake.wait()
                queue.offer_unsafe(current())

        def subscribe() -> Callable[[], None]:
            queue.offer_unsafe(current())
            return resizes.subscribe(wake.notify, current)

        def unsubscribe(stop: Callable[[], None], _exit: object) -> Effect[None]:
            def run() -> None:
                stop()
                queue.end_unsafe()

            return sync(run)

        yield from acquire_release(sync(subscribe), unsubscribe)
        yield from gen(pump).fork_scoped()
        return queue

    return gen(size)


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
    fill_within_escape_timeout = blocking(lambda: source.fill(ESCAPE_CODE_TIMEOUT))

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
        text = codecs.getincrementaldecoder("utf-8")(errors="replace")
        keys = KeyDecoder()

        def pump() -> Generator[Effect[Any], Any]:
            while True:
                data = source.take_all()
                if data:
                    events = keys.feed(text.decode(data))
                elif source.ended:
                    # As Effect's reader, the end of input ends the queue
                    # before a trailing ESC's timeout could name it.
                    yield from queue.end()
                    return
                elif keys.escape_pending:
                    yield from fill_within_escape_timeout
                    if source.waiting():
                        continue
                    events = keys.timeout()
                else:
                    yield from fill
                    continue
                for event in events:
                    yield from queue.offer(event)
                    if should_quit(event):
                        yield from queue.end()
                        return

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

    def current() -> Size:
        size = _size(out())
        return Size(0, 0) if size is None else Size(size.columns, size.lines)

    return TerminalService(
        columns=sync(columns),
        rows=sync(rows),
        size=_sizes(current),
        read_input=gen(read_input),
        read_line=gen(read_line),
        display=display,
    )
