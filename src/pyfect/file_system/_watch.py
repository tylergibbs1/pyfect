"""Watching by polling: the standard library has no portable change
notification, so the live file system compares listings of the watched
path at an interval. A directory's own timestamps are left out, so a
change inside a subdirectory is reported only by a recursive watch, as
Node's watcher reports it."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Generator
from typing import Any

from pyfect import stream as stream_
from pyfect._core import Effect
from pyfect.clock import LiveClock
from pyfect.duration import Seconds
from pyfect.effect import gen, sync
from pyfect.file_system._errors import run
from pyfect.file_system._model import Create, Remove, Update, WatchEvent
from pyfect.platform_error import PlatformError
from pyfect.stream import Stream

type _Signature = tuple[object, ...]
type _Listing = dict[str, _Signature]


def _signature(entry: os.stat_result) -> _Signature:
    if stat.S_ISDIR(entry.st_mode):
        return ("directory", entry.st_ino)
    return ("file", entry.st_ino, entry.st_mtime_ns, entry.st_size, entry.st_mode)


def _list_directory(root: str, recursive: bool) -> _Listing:
    listing: _Listing = {}
    pending = [""]
    while pending:
        relative = pending.pop()
        try:
            entries = list(os.scandir(os.path.join(root, relative) if relative else root))
        except (FileNotFoundError, NotADirectoryError):
            continue
        for entry in entries:
            name = os.path.join(relative, entry.name) if relative else entry.name
            try:
                info = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            listing[name] = _signature(info)
            if recursive and entry.is_dir(follow_symlinks=False):
                pending.append(name)
    return listing


def _list_file(path: str) -> _Listing:
    try:
        return {os.path.basename(path): _signature(os.stat(path))}
    except FileNotFoundError:
        return {}


def _changes(before: _Listing, after: _Listing) -> tuple[WatchEvent, ...]:
    events: list[WatchEvent] = []
    for name in sorted(before.keys() | after.keys()):
        old = before.get(name)
        new = after.get(name)
        if old is None:
            events.append(Create(name))
        elif new is None:
            events.append(Remove(name))
        elif old != new:
            events.append(Update(name))
    return tuple(events)


def poll(
    path: str,
    *,
    directory: bool,
    recursive: bool,
    on_ready: Callable[[], None] | None,
    interval: Seconds,
) -> Stream[WatchEvent, PlatformError]:
    """The changes under ``path``, found by listing it every ``interval``
    of real time (whatever ``Clock`` is provided)."""

    def scan() -> _Listing:
        return _list_directory(path, recursive) if directory else _list_file(path)

    def make() -> Generator[Effect[Any, PlatformError], Any, Effect[Any, Any]]:
        listing = yield from run("watch", path, scan)
        if on_ready is not None:
            yield from sync(on_ready)
        latest = [listing]

        def next_changes() -> Generator[Effect[Any, PlatformError], Any, tuple[WatchEvent, ...]]:
            while True:
                yield from LiveClock().sleep(interval)
                current = yield from run("watch", path, scan)
                events = _changes(latest[0], current)
                latest[0] = current
                if events:
                    return events

        return gen(next_changes)

    return stream_.from_pull(gen(make))
