"""Ports of Effect's ``effect/test/Migrator.test.ts`` (the loaders).

Each test's docstring is the Effect test title.

Adapted: ``migrator_file_system.from_file_system`` loads ``<id>_<name>.py`` modules, where
Effect loads ``.js`` / ``.ts`` / ``.mjs`` / ``.mts`` ones. Python imports a
module from its path, so there is no file URL step: the two file URL tests
check that the module is imported from the path the platform's ``Path``
joins, and that a module that cannot be imported is a defect of the load
effect (which ``make`` reports as an ``ImportError``), never a typed
failure.

Omitted: "fromGlob accepts js, ts, mjs, and mts files" and "fromBabelGlob
accepts Js, Ts, Mjs, and Mts suffixes": they read a bundler's import map,
which Python has no equivalent of.
"""

from pathlib import Path as FsPath
from typing import cast

import pyfect as fx
from pyfect import _path_win32, testing
from pyfect import path as fx_path
from pyfect.file_system import FileSystem, NoopFileSystem
from pyfect.path import Path, PathService
from pyfect.sql import migrator, migrator_file_system
from pyfect.sql.migrator import ResolvedMigration

_FIXTURE = FsPath(__file__).parent / "fixtures" / "migrator" / "0001_first.py"


class _Listing(NoopFileSystem):
    def __init__(self, *names: str) -> None:
        self.names = list(names)

    def read_directory(self, path: str, *, recursive: bool = False):
        return fx.succeed(self.names)


class _RecordingPath(PathService):
    """Windows-like joins that resolve to the fixture module, recording what
    was joined (Effect's test overrides ``join`` and ``toFileUrl``)."""

    def __init__(self) -> None:
        super().__init__(_path_win32, windows=True)
        self.joined: list[str] = []

    def join(self, *paths: str) -> str:
        self.joined.append("\\".join(paths))
        return str(_FIXTURE)


def _loaded(migration: ResolvedMigration) -> fx.Effect[object, object]:
    # ``ResolvedMigration`` declares a ``SqlClient`` requirement that this
    # loader's load effect never uses (Effect's test casts it away too).
    return cast("fx.Effect[object, object]", migration[2])


def _names(migrations: list[ResolvedMigration]) -> list[tuple[int, str]]:
    return [(id_, name) for id_, name, _ in migrations]


def _load(directory: str, fs: NoopFileSystem, path: PathService):
    return (
        migrator_file_system.from_file_system(directory)
        .map(list)
        .pipe(fx.provide_service(FileSystem, fs))
        .pipe(fx.provide_service(Path, path))
    )


@testing.effect
def test_from_record_loads_migrations_without_filesystem_services():
    """fromRecord loads migrations without filesystem services"""
    migrations = yield from migrator.from_record({"0002_second": fx.void, "0001_first": fx.void})
    assert _names(list(migrations)) == [(1, "first"), (2, "second")]


@testing.effect
def test_from_file_system_accepts_python_modules():
    """fromFileSystem accepts js, ts, mjs, and mts files"""
    listing = _Listing(
        "0004_fourth.py",
        "0002_second.py",
        "0003_third.py",
        "0001_first.py",
        "0005_ignored.js",
        "0006_ignored.pyc",
        "notes.txt",
    )

    migrations = yield from _load("/migrations", listing, fx_path.posix)

    assert _names(migrations) == [(1, "first"), (2, "second"), (3, "third"), (4, "fourth")]


@testing.effect
def test_from_file_system_imports_through_the_platform_path():
    """fromFileSystem imports migrations through the file URL the platform resolves"""
    windows_like = _RecordingPath()

    migrations = yield from _load("C:\\migrations", _Listing("0001_first.py"), windows_like)
    imported = yield from _loaded(migrations[0])

    assert windows_like.joined == ["C:\\migrations\\0001_first.py"]
    assert getattr(imported, "marker", None) == "loaded"


@testing.effect
def test_from_file_system_import_failures_are_defects(tmp_path: FsPath):
    """fromFileSystem surfaces file URL failures as import errors"""
    migrations = yield from _load(str(tmp_path), _Listing("0001_first.py"), fx_path.posix)

    outcome = yield from (
        _loaded(migrations[0])
        .map(lambda _: "no defect")
        .catch_defect(lambda defect: fx.succeed(f"defect: {defect!r}"))
        .or_else_succeed(lambda _: "typed failure")
    )

    assert outcome.startswith("defect: FileNotFoundError")
