"""The file-system ``KeyValueStore`` gives keys that differ only in ASCII
letter case, or by a trailing ``.``, files whose names differ however the
file system folds case (macOS and Windows do) or trims a trailing ``.``
(Windows): ``user:Alice`` and ``user:alice`` were one file there. A store
written by 0.6.5 reads back as it did, on either kind of file system."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import file_system, path
from pyfect.file_system import FileInfo, NoopFileSystem, layer_noop
from pyfect.persistence import key_value_store as kvs
from pyfect.persistence.key_value_store import _layers
from pyfect.persistence.key_value_store._layers import (
    _decode_file_key,  # pyright: ignore[reportPrivateUsage]
    _file_name,  # pyright: ignore[reportPrivateUsage]
    _legacy_file_name,  # pyright: ignore[reportPrivateUsage]
)
from pyfect.platform_error import PlatformError, system_error

_PLATFORM = fx.layer.merge(file_system.layer, path.layer)


def _folded(name: str) -> str:
    return name.casefold().rstrip(".")


def test_file_names_stay_apart_when_case_is_folded_and_round_trip() -> None:
    alphabet = ["a", "A", "z", "Z", ".", "%", "é", "É", "4", "1", ":"]
    keys = [
        "".join(chars)
        for size in range(1, 4)
        for chars in itertools.product(alphabet, repeat=size)
        if "".join(chars) not in (".", "..")
    ]
    names = {key: _file_name(key) for key in keys}
    assert all(name is not None for name in names.values())
    folded = {_folded(name) for name in names.values() if name is not None}
    assert len(folded) == len(keys)
    assert all(_decode_file_key(name) == key for key, name in names.items() if name is not None)


def test_lower_case_keys_keep_effects_file_names() -> None:
    assert _file_name("user:alice") == "user%3Aalice"
    assert _file_name("a b") == "a%20b"


class _MemoryFiles(NoopFileSystem):
    """One flat directory in memory. With ``fold``, names match ignoring
    case and a trailing ``.``, and a file keeps the name it was made with
    (as APFS and NTFS do)."""

    def __init__(self, *, fold: bool) -> None:
        self.fold = fold
        self.files: dict[str, tuple[str, bytes, datetime]] = {}
        self.clock = datetime(2026, 1, 1, tzinfo=UTC)

    def _id(self, p: str) -> str:
        name = p.rsplit("/", 1)[-1]
        return _folded(name) if self.fold else name

    def _missing(self, p: str) -> PlatformError:
        return system_error("NotFound", module="FileSystem", method="test", path_or_descriptor=p)

    def exists(self, path: str):
        return fx.succeed(path == "kv" or self._id(path) in self.files)

    def make_directory(self, path: str, *, recursive: bool = False, mode: int = 0o777):
        return fx.void

    def read_directory(self, path: str, *, recursive: bool = False):
        return fx.succeed([name for name, _, _ in self.files.values()])

    def read_file(self, path: str):
        found = self.files.get(self._id(path))
        return fx.fail(self._missing(path)) if found is None else fx.succeed(found[1])

    def read_file_string(self, path: str, encoding: str = "utf-8"):
        return self.read_file(path).map(lambda data: data.decode(encoding))

    def write_file(self, path: str, data: bytes, *, flag: Any = "w", mode: int = 0o666):
        def write() -> None:
            self.clock += timedelta(seconds=1)
            old = self.files.get(self._id(path))
            name = old[0] if old is not None else path.rsplit("/", 1)[-1]
            self.files[self._id(path)] = (name, bytes(data), self.clock)

        return fx.sync(write)

    def write_file_string(self, path: str, data: str, *, flag: Any = "w", mode: int = 0o666):
        return self.write_file(path, data.encode())

    def remove(self, path: str, *, recursive: bool = False, force: bool = False):
        def remove() -> None:
            if path == "kv":
                self.files.clear()
            else:
                self.files.pop(self._id(path), None)

        return fx.sync(remove)

    def rename(self, old_path: str, new_path: str):
        def rename() -> fx.Effect[None, PlatformError]:
            found = self.files.pop(self._id(old_path), None)
            if found is None:
                return fx.fail(self._missing(old_path))
            _, data, mtime = found
            self.files[self._id(new_path)] = (new_path.rsplit("/", 1)[-1], data, mtime)
            return fx.void

        return fx.suspend(rename)

    def stat(self, path: str) -> fx.Effect[FileInfo, PlatformError]:
        found = self.files.get(self._id(path))
        if found is None:
            return fx.fail(self._missing(path))
        info: Any = type("Info", (), {"mtime": found[2]})()
        typed: FileInfo = info
        return fx.succeed(typed)


def _open(files: _MemoryFiles) -> fx.Layer[kvs.KeyValueStore, Any, Any]:
    return (
        kvs.layer_file_system("kv").pipe(fx.provide(layer_noop(files))).pipe(fx.provide(path.layer))
    )


def _run(files: _MemoryFiles, body: Any) -> Any:
    return fx.run_blocking(fx.gen(body).pipe(fx.provide(_open(files))).or_die())


def _keep_names(*_: object) -> fx.Effect[None]:
    return fx.void


def _write_as_0_6_5(
    files: _MemoryFiles, monkeypatch: pytest.MonkeyPatch, entries: dict[str, str]
) -> None:
    with monkeypatch.context() as patched:
        patched.setattr(_layers, "_file_name", _legacy_file_name)
        patched.setattr(_layers, "_rename_legacy_files", _keep_names)

        def body():
            store = yield from kvs.KeyValueStore()
            for key, value in entries.items():
                yield from store.set(key, value)

        _run(files, body)


def _snapshot(keys: list[str]):
    def body():
        store = yield from kvs.KeyValueStore()
        values: dict[str, str | None] = {}
        present: dict[str, bool] = {}
        for key in keys:
            values[key] = yield from store.get(key)
            present[key] = yield from store.has(key)
        return (sorted((yield from store.keys)), (yield from store.size), values, present)

    return body


@pytest.mark.parametrize("fold", [False, True], ids=["case-sensitive", "case-insensitive"])
def test_a_0_6_5_store_reads_back_as_it_did(monkeypatch: pytest.MonkeyPatch, fold: bool) -> None:
    files = _MemoryFiles(fold=fold)
    entries = {"user:Alice": "a", "Report.": "r", "plain": "p", "MiXeD/Key": "m"}
    _write_as_0_6_5(files, monkeypatch, entries)
    before = (sorted(entries), len(entries), entries, dict.fromkeys(entries, True))
    keys = list(entries)
    assert _run(files, _snapshot(keys)) == before
    # Once more, after the names were moved, and through each operation.
    assert _run(files, _snapshot(keys)) == before

    def remove_and_set():
        store = yield from kvs.KeyValueStore()
        yield from store.remove("user:Alice")
        yield from store.set("user:alice", "lower")
        yield from store.set("Report.", "r2")

    _run(files, remove_and_set)
    assert _run(files, _snapshot(["user:Alice", "user:alice", "Report."])) == (
        sorted(["user:alice", "Report.", "plain", "MiXeD/Key"]),
        4,
        {"user:Alice": None, "user:alice": "lower", "Report.": "r2"},
        {"user:Alice": False, "user:alice": True, "Report.": True},
    )


def test_of_a_legacy_file_and_a_current_one_the_newer_stays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = _MemoryFiles(fold=False)

    def set_new():
        store = yield from kvs.KeyValueStore()
        yield from store.set("Key", "current")

    _run(files, set_new)
    _write_as_0_6_5(files, monkeypatch, {"Key": "legacy, written later"})
    assert _run(files, _snapshot(["Key"])) == (
        ["Key"],
        1,
        {"Key": "legacy, written later"},
        {"Key": True},
    )


def test_keys_differing_in_case_are_separate_entries(tmp_path: Path) -> None:
    def body():
        store = yield from kvs.KeyValueStore()
        yield from store.set("user:Alice", "alice's secret")
        yield from store.set("user:alice.", "dot")
        return (
            (yield from store.get("user:alice")),
            (yield from store.get("user:alice.")),
            sorted((yield from store.keys)),
        )

    layer = kvs.layer_file_system(str(tmp_path / "kv")).pipe(fx.provide(_PLATFORM))
    assert fx.run_blocking(fx.gen(body).pipe(fx.provide(layer)).or_die()) == (
        None,
        "dot",
        ["user:Alice", "user:alice."],
    )


def test_a_0_6_5_store_on_this_machines_file_system_reads_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layer = kvs.layer_file_system(str(tmp_path / "kv")).pipe(fx.provide(_PLATFORM))
    entries = {"user:Alice": "a", "Report.": "r", "plain": "p"}

    def write():
        store = yield from kvs.KeyValueStore()
        for key, value in entries.items():
            yield from store.set(key, value)

    with monkeypatch.context() as patched:
        patched.setattr(_layers, "_file_name", _legacy_file_name)
        fx.run_blocking(fx.gen(write).pipe(fx.provide(layer)).or_die())
    snapshot = fx.run_blocking(fx.gen(_snapshot(list(entries))).pipe(fx.provide(layer)).or_die())
    assert snapshot == (sorted(entries), 3, entries, dict.fromkeys(entries, True))


class _Interleaved(_MemoryFiles):
    """The files of ``shared``, where another process opens the store
    (``other``) just before this one's ``at``-th file system call."""

    def __init__(self, shared: _MemoryFiles, at: int, other: fx.Effect[object, Any]) -> None:
        super().__init__(fold=shared.fold)
        self.files = shared.files
        self.clock = shared.clock
        self.at = at
        self.other = other
        self.calls = 0

    def _call[A, E](self, effect: fx.Effect[A, E]) -> fx.Effect[A, E]:
        def call() -> fx.Effect[A, E]:
            self.calls += 1
            if self.calls - 1 == self.at:
                return self.other.or_die().and_then(effect)
            return effect

        return fx.suspend(call)

    def exists(self, path: str):
        return self._call(super().exists(path))

    def read_directory(self, path: str, *, recursive: bool = False):
        return self._call(super().read_directory(path))

    def remove(self, path: str, *, recursive: bool = False, force: bool = False):
        return self._call(super().remove(path, recursive=recursive, force=force))

    def rename(self, old_path: str, new_path: str):
        return self._call(super().rename(old_path, new_path))

    def stat(self, path: str):
        return self._call(super().stat(path))


def _open_layer(files: NoopFileSystem) -> fx.Layer[kvs.KeyValueStore, Any, Any]:
    return (
        kvs.layer_file_system("kv").pipe(fx.provide(layer_noop(files))).pipe(fx.provide(path.layer))
    )


@pytest.mark.parametrize(
    "current",
    [None, "current, written earlier", "current, written later"],
    ids=["legacy-only", "legacy-newer", "current-newer"],
)
def test_processes_opening_a_0_6_5_store_together_all_open_and_keep_the_newer_value(
    monkeypatch: pytest.MonkeyPatch, current: str | None
) -> None:
    """Another process may open the store at any point of this one's
    renames: both open, and the key keeps its newer value."""
    template = _MemoryFiles(fold=False)

    def set_current():
        assert current is not None
        store = yield from kvs.KeyValueStore()
        yield from store.set("Key", current)

    if current == "current, written earlier":
        _run(template, set_current)
    _write_as_0_6_5(template, monkeypatch, {"Key": "legacy"})
    if current == "current, written later":
        _run(template, set_current)
    expected = "current, written later" if current == "current, written later" else "legacy"

    def get_key():
        return (yield from (yield from kvs.KeyValueStore()).get("Key"))

    def open_alone(files: _MemoryFiles) -> fx.Effect[object, Any]:
        return fx.gen(get_key).pipe(fx.provide(_open_layer(files)))

    counted = _Interleaved(_copy(template), -1, fx.void)
    fx.run_blocking(open_alone(counted).or_die())
    assert counted.calls > 0
    for at in range(counted.calls):
        files = _copy(template)
        other = open_alone(files)
        racing = _Interleaved(files, at, other)
        read = fx.run_blocking(fx.gen(get_key).pipe(fx.provide(_open_layer(racing))).exit())
        assert read == fx.exit.succeed(expected), (at, read)


def _copy(files: _MemoryFiles) -> _MemoryFiles:
    copied = _MemoryFiles(fold=files.fold)
    copied.files = dict(files.files)
    copied.clock = files.clock
    return copied
