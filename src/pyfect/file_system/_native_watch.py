"""Watching through the operating system's change notification (inotify,
FSEvents, ReadDirectoryChangesW) with watchfiles, the ``watch`` extra, as
Effect's Node file system watches with ``fs.watch``.

watchfiles' watcher blocks, so each watch has a thread of its own that
installs it, waits for changes and turns them into events; fibers wait for
them in ``os_wait``. Closing the stream stops the thread (it checks every
``_STEP_MS``) and waits until it has closed the watcher and exited."""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Callable, Generator, Iterable
from typing import TYPE_CHECKING, Any, Never

from pyfect import stream as stream_
from pyfect._core import Effect
from pyfect._extras import is_absent, missing_extra
from pyfect._os_wait import Resume, os_wait
from pyfect.effect import fail, gen, succeed, sync, void
from pyfect.file_system._model import Create, FileInfo, Remove, Update, WatchEvent
from pyfect.platform_error import PlatformError, from_exception, system_error
from pyfect.scope import acquire_release
from pyfect.stream import Stream

if TYPE_CHECKING:
    from watchfiles._rust_notify import RustNotify

_STEP_MS = 10
"""How long the watcher waits for more changes before reporting a batch,
and how often it checks whether to stop."""

_DEBOUNCE_MS = 50
"""The longest a batch of changes collects before it is reported."""

_ADDED, _MODIFIED, _DELETED = 1, 2, 3
"""watchfiles' ``Change`` values."""

_SCANS_NEW_DIRECTORIES = sys.platform == "linux"
"""inotify watches a new directory only once told of it, so what is
created in it first goes unseen; Node's recursive watcher on Linux lists a
new directory and reports what it finds (FSEvents and Windows watch whole
trees natively)."""


def _rust_notify() -> type[RustNotify] | None:
    try:
        from watchfiles._rust_notify import RustNotify
    except ImportError as error:
        if not is_absent(error, "watch"):
            raise missing_extra("FileSystem.watch", "watch", error) from error
        return None
    return RustNotify


def _born(path: str) -> float | None:
    """When ``path`` was created where the system records it (macOS,
    Windows, BSD), ``0`` where it doesn't (Linux), ``None`` if it is gone."""
    try:
        info = os.stat(path)
    except OSError:
        return None
    return getattr(info, "st_birthtime", 0.0)


def _descendants(directory: str) -> Iterable[str]:
    """The paths under ``directory``, relative to it."""
    for parent, names, files in os.walk(directory):
        relative = os.path.relpath(parent, directory)
        for name in (*names, *files):
            yield name if relative == "." else os.path.join(relative, name)


class _Translation:
    """watchfiles' changes as Effect's events. Effect reads Node's
    ``rename`` (an add or a delete) by whether the path exists now:
    ``Create`` if it does, ``Remove`` if not; ``change`` is ``Update``.
    Paths are relative to the watched directory (to the file's directory
    for a file), as Node reports them."""

    __slots__ = ("_bases", "_directory", "_recursive")

    def __init__(self, directory: str, *, recursive: bool) -> None:
        self._directory = directory
        self._recursive = recursive
        self._bases = (os.path.abspath(directory), os.path.realpath(directory))

    def _relative(self, path: str) -> str:
        for base in self._bases:
            if path == base:
                return os.path.basename(base)
            relative = os.path.relpath(path, base)
            if relative != os.pardir and not relative.startswith(os.pardir + os.sep):
                return relative
        return path

    def events(self, changes: set[tuple[int, str]]) -> list[WatchEvent]:
        kinds: dict[str, set[int]] = {}
        for kind, path in changes:
            kinds.setdefault(self._relative(path), set()).add(kind)
        if self._recursive and _SCANS_NEW_DIRECTORIES:
            # What is inside a new directory is new, even when inotify, watching it late,
            # saw only a write to it.
            for name, found in list(kinds.items()):
                full = os.path.join(self._directory, name)
                if (_ADDED in found or _DELETED in found) and os.path.isdir(full):
                    for child in _descendants(full):
                        kinds.setdefault(os.path.join(name, child), set()).add(_ADDED)
        gone: list[tuple[str, list[WatchEvent]]] = []
        present: list[tuple[float, str, list[WatchEvent]]] = []
        for name, found in kinds.items():
            renamed = _ADDED in found or _DELETED in found
            updated = [Update(name)] if _MODIFIED in found else []
            born = _born(os.path.join(self._directory, name))
            if born is None:
                gone.append((name, [*updated, *([Remove(name)] if renamed else [])]))
                continue
            present.append((born, name, [*([Create(name)] if renamed else []), *updated]))
        # A batch is unordered. Removals come first, children before their
        # directories; then what exists, oldest first where creation times
        # are recorded (FSEvents can report a change made just before the
        # watch started, which Node reports first), directories before
        # their children.
        gone.sort(key=lambda item: item[0], reverse=True)
        present.sort(key=lambda item: item[:2])
        return [
            *(event for _, events in gone for event in events),
            *(event for _, _, events in present for event in events),
        ]


def _outcome(
    events: tuple[WatchEvent, ...], failure: PlatformError | None
) -> Effect[tuple[WatchEvent, ...], PlatformError]:
    """What a take gets: the events found, else the watcher's failure."""
    return succeed(events) if events or failure is None else fail(failure)


class _Watcher:
    """One watch: its thread, the events it found that no pull has taken
    yet, and the fibers waiting on it. Shared with the thread under
    ``_lock``; resumes happen outside it."""

    __slots__ = (
        "_ended",
        "_events",
        "_failure",
        "_lock",
        "_on_end",
        "_path",
        "_recursive",
        "_stop",
        "_take",
        "_translation",
    )

    def __init__(self, path: str, directory: str, *, recursive: bool) -> None:
        self._path = path
        self._recursive = recursive
        self._translation = _Translation(directory, recursive=recursive)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._events: list[WatchEvent] = []
        self._failure: PlatformError | None = None
        self._take: Resume[tuple[WatchEvent, ...], PlatformError] | None = None
        self._ended = False
        self._on_end: Resume[None, Never] | None = None

    def start(self, notify: type[RustNotify]) -> Effect[_Watcher, PlatformError]:
        """Start the thread; succeeds once the watcher is installed."""

        def register(resume: Resume[_Watcher, PlatformError]) -> None:
            threading.Thread(
                target=self._run, args=(notify, resume), name="pyfect-watch", daemon=True
            ).start()

        return os_wait(register, waits_for="work")

    def take(self) -> Effect[tuple[WatchEvent, ...], PlatformError]:
        """The events found since the last take, waiting for one."""

        def register(
            resume: Resume[tuple[WatchEvent, ...], PlatformError],
        ) -> Callable[[], None] | None:
            with self._lock:
                events, self._events = tuple(self._events), []
                failure = self._failure
                if not events and failure is None:
                    self._take = resume
                    return self._cancel_take
            resume(_outcome(events, failure))
            return None

        return os_wait(register, waits_for="event")

    def _cancel_take(self) -> None:
        with self._lock:
            self._take = None

    def stop(self) -> Effect[None]:
        """Stop the thread; succeeds once it has closed the watcher."""

        def register(resume: Resume[None, Never]) -> None:
            with self._lock:
                ended = self._ended
                if not ended:
                    self._on_end = resume
            self._stop.set()
            if ended:
                resume(void)

        return os_wait(register, waits_for="work")

    def _run(self, notify: type[RustNotify], started: Resume[_Watcher, PlatformError]) -> None:
        try:
            watcher = notify([self._path], False, False, 50, self._recursive, False)
        except Exception as error:
            self._end()
            started(
                fail(
                    from_exception(
                        error, module="FileSystem", method="watch", path_or_descriptor=self._path
                    )
                )
            )
            return
        started(succeed(self))
        try:
            while not self._stop.is_set():
                changes = watcher.watch(_DEBOUNCE_MS, _STEP_MS, 0, self._stop)
                events = self._translation.events(changes) if isinstance(changes, set) else []
                if events:
                    self._deliver(events, None)
        except Exception as error:
            failure = system_error(
                "Unknown",
                module="FileSystem",
                method="watch",
                path_or_descriptor=self._path,
                cause=error,
            )
            self._deliver([], failure)
        finally:
            watcher.close()
            self._end()

    def _deliver(self, events: list[WatchEvent], failure: PlatformError | None) -> None:
        with self._lock:
            self._events.extend(events)
            if self._failure is None:
                self._failure = failure
            resume, self._take = self._take, None
            if resume is None:
                return
            taken, self._events = tuple(self._events), []
            failed = self._failure
        resume(_outcome(taken, failed))

    def _end(self) -> None:
        with self._lock:
            self._ended = True
            resume, self._on_end = self._on_end, None
        if resume is not None:
            resume(void)


class WatchfilesBackend:
    """A ``WatchBackend`` on the operating system's change notification,
    through watchfiles (the ``watch`` extra); without the extra it leaves
    every path to the file system. ``LiveFileSystem`` uses it when no
    provided backend takes the path."""

    __slots__ = ()

    def register(
        self,
        path: str,
        info: FileInfo,
        *,
        recursive: bool,
        on_ready: Callable[[], None] | None,
    ) -> Stream[WatchEvent, PlatformError] | None:
        notify = _rust_notify()
        if notify is None:
            return None
        directory = path if info.type == "Directory" else os.path.dirname(path) or os.curdir

        def make() -> Generator[
            Effect[Any, PlatformError, Any], Any, Stream[WatchEvent, PlatformError]
        ]:
            watcher = yield from acquire_release(
                _Watcher(path, directory, recursive=recursive).start(notify),
                lambda watcher, _exit: watcher.stop(),
            )
            if on_ready is not None:
                yield from sync(on_ready)
            return stream_.from_pull(succeed(watcher.take()))

        return stream_.unwrap(gen(make))
