"""``FileSystem.watch`` on the operating system's change notification (the
``watch`` extra, watchfiles) and the polling it falls back to without it.

The events follow Effect's Node file system, checked against Node 24's
``fs.watch`` on macOS and on Linux: an add or a delete (Node's ``rename``)
is ``Create`` if the path exists afterwards and ``Remove`` if not, paths are
relative to the watched directory (the file's name for a file), and only a
recursive watch sees inside subdirectories. The watcher runs on a thread of
its own, which closing the stream stops and waits for."""

from __future__ import annotations

import importlib.abc
import os
import sys
import threading
import time
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import file_system
from pyfect.file_system import Create, FileSystem, Remove, Update, WatchEvent, _native_watch
from pyfect.platform_error import PlatformError

_TIMEOUT = "10 seconds"


def _watcher_threads() -> list[threading.Thread]:
    return [thread for thread in threading.enumerate() if thread.name == "pyfect-watch"]


def _watch(
    target: Path,
    act: Callable[[], object],
    until: Callable[[WatchEvent], bool],
    *,
    recursive: bool = False,
) -> list[WatchEvent]:
    """The events of watching ``target`` while ``act`` runs (once the
    watcher is installed), up to the first that satisfies ``until``."""

    @fx.fn
    def program() -> Generator[fx.Effect[Any, Any, Any], Any, list[WatchEvent]]:
        fs = yield from FileSystem()
        ready = yield from fx.Latch.make()
        fiber = yield from (
            fs.watch(str(target), recursive=recursive, on_ready=_opener(ready))
            .take_until(until)
            .run_collect()
            .fork()
        )
        yield from ready.wait().race_first(fiber.join().as_(None))
        yield from fx.blocking(act)
        return (yield from fiber.join().timeout(_TIMEOUT))

    return fx.run_blocking(program().pipe(fx.provide(file_system.layer)).or_die())


def _opener(latch: fx.Latch) -> Callable[[], None]:
    def open_latch() -> None:
        latch.open_unsafe()

    return open_latch


def _write(path: Path, text: str = "x") -> Callable[[], object]:
    return lambda: path.write_text(text)


def test_a_new_file_is_a_create_relative_to_the_directory(tmp_path: Path):
    events = _watch(tmp_path, _write(tmp_path / "a.txt"), lambda event: event.path == "a.txt")
    assert events[-1] == Create("a.txt")


def test_a_rename_removes_the_old_name_and_creates_the_new_one(tmp_path: Path):
    (tmp_path / "a.txt").write_text("x")
    time.sleep(0.2)
    events = _watch(
        tmp_path,
        lambda: os.rename(tmp_path / "a.txt", tmp_path / "b.txt"),
        lambda event: event == Create("b.txt"),
    )
    assert events == [Remove("a.txt"), Create("b.txt")]


def test_a_removed_directory_is_a_remove(tmp_path: Path):
    (tmp_path / "d").mkdir()
    time.sleep(0.2)
    events = _watch(tmp_path, (tmp_path / "d").rmdir, lambda event: event.path == "d")
    assert events == [Remove("d")]


def test_a_file_created_and_removed_at_once_is_still_reported(tmp_path: Path):
    # Polling every 50 ms misses it: the file is gone by the next listing.
    def create_and_remove() -> None:
        (tmp_path / "a.txt").write_text("x")
        (tmp_path / "a.txt").unlink()

    events = _watch(tmp_path, create_and_remove, lambda event: event == Remove("a.txt"))
    assert events[-1] == Remove("a.txt")


def test_watching_a_file_reports_its_name(tmp_path: Path):
    target = tmp_path / "f.txt"
    target.write_text("x")
    time.sleep(0.2)
    events = _watch(target, _write(target, "y"), lambda _: True)
    assert [event.path for event in events] == ["f.txt"]


def test_a_recursive_watch_reports_a_file_made_with_its_new_directory(tmp_path: Path):
    # inotify watches the new directory only once told of it; Node lists it
    # and reports what is already inside, so pyfect does too.
    def make() -> None:
        (tmp_path / "m").mkdir()
        (tmp_path / "m" / "y.txt").write_text("x")

    events = _watch(
        tmp_path, make, lambda event: event.path == os.path.join("m", "y.txt"), recursive=True
    )
    assert Create("m") in events
    assert events[-1] == Create(os.path.join("m", "y.txt"))


def test_a_file_in_a_new_directory_is_created_even_if_only_its_write_was_seen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Linux CI: inotify watched ``m`` after ``y.txt`` was opened but before it was
    # written, so the batch held ``m`` added and ``y.txt`` only modified, and the
    # first event for it was an Update. Anything inside a new directory is new.
    monkeypatch.setattr(_native_watch, "_SCANS_NEW_DIRECTORIES", True)
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "y.txt").write_text("x")
    translation = _native_watch._Translation(str(tmp_path), recursive=True)  # pyright: ignore[reportPrivateUsage]
    changes = {(1, str(tmp_path / "m")), (2, str(tmp_path / "m" / "y.txt"))}
    assert translation.events(changes) == [
        Create("m"),
        Create(os.path.join("m", "y.txt")),
        Update(os.path.join("m", "y.txt")),
    ]


def test_the_watcher_runs_on_its_own_thread_and_interrupting_stops_it(tmp_path: Path):
    @fx.fn
    def program() -> Generator[fx.Effect[Any, Any, Any], Any, tuple[int, float]]:
        fs = yield from FileSystem()
        ready = yield from fx.Latch.make()
        fiber = yield from fs.watch(str(tmp_path), on_ready=_opener(ready)).run_drain().fork()
        yield from ready.wait()
        watching = len(_watcher_threads())
        started = time.monotonic()
        yield from fiber.interrupt()
        return watching, time.monotonic() - started

    before = len(_watcher_threads())
    watching, took = fx.run_blocking(program().pipe(fx.provide(file_system.layer)).or_die())
    assert watching == before + 1
    assert len(_watcher_threads()) == before
    assert took < 1


def test_a_stream_that_ends_stops_its_watcher(tmp_path: Path):
    before = len(_watcher_threads())
    _watch(tmp_path, _write(tmp_path / "a.txt"), lambda _: True)
    assert len(_watcher_threads()) == before


def _without_watchfiles(monkeypatch: pytest.MonkeyPatch) -> None:
    class Absent(importlib.abc.MetaPathFinder):
        def find_spec(self, name: str, path: object = None, target: object = None) -> None:
            if name.split(".", maxsplit=1)[0] == "watchfiles":
                raise ModuleNotFoundError(f"No module named {name!r}", name="watchfiles")

    for name in [name for name in sys.modules if name.split(".")[0] == "watchfiles"]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "meta_path", [Absent(), *sys.meta_path])


def test_without_the_extra_watch_polls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _without_watchfiles(monkeypatch)
    seen: list[int] = []

    def act() -> None:
        seen.append(len(_watcher_threads()))
        (tmp_path / "a.txt").write_text("x")

    events = _watch(tmp_path, act, lambda event: event.path == "a.txt")
    assert events[-1] == Create("a.txt")
    assert seen == [0]


def test_a_polled_rename_removes_the_old_name_before_creating_the_new_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """As the native watcher (and Node) reports it, whichever name sorts first."""
    _without_watchfiles(monkeypatch)
    (tmp_path / "z.txt").write_text("x")
    events = _watch(
        tmp_path,
        lambda: os.rename(tmp_path / "z.txt", tmp_path / "a.txt"),
        lambda event: event == Create("a.txt"),
    )
    assert events == [Remove("z.txt"), Create("a.txt")]


def test_a_watcher_that_cannot_start_fails_the_stream(tmp_path: Path):
    @fx.fn
    def program() -> Generator[fx.Effect[Any, Any, Any], Any, fx.Exit[None, PlatformError]]:
        backend = file_system.WatchfilesBackend()
        info = yield from (yield from FileSystem()).stat(str(tmp_path))
        stream = backend.register(str(tmp_path / "gone"), info, recursive=False, on_ready=None)
        assert stream is not None
        return (yield from stream.run_drain().exit())

    exit = fx.run_blocking(program().pipe(fx.provide(file_system.layer)))
    assert isinstance(exit, fx.Failure)
    assert _watcher_threads() == []
