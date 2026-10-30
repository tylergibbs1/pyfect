"""``from_dir``: one file per key, as Kubernetes and Docker mount secrets."""

from __future__ import annotations

import os
from collections.abc import Generator
from typing import Any, Never

from pyfect import _js
from pyfect._core import Effect
from pyfect.config_provider._node import Keys, Node, Path, Record, SourceError, Value
from pyfect.config_provider._provider import ConfigProvider, make
from pyfect.effect import fail, gen, succeed
from pyfect.file_system import FileSystem, FileSystemService
from pyfect.path import Path as PathTag
from pyfect.path import PathService
from pyfect.platform_error import NotFound, PlatformError


def from_dir(
    root_path: str | os.PathLike[str] = "/", *, preserve_empty_strings: bool = False
) -> Effect[ConfigProvider, Never, PathTag | FileSystem]:
    """A provider over the files under ``root_path``, read through the
    ``FileSystem`` and ``Path`` services: the path ``("db", "password")``
    reads the file ``<root_path>/db/password`` (trimmed) as a value, and a
    directory is a record of its entry names. A path missing both as a file
    and as a directory is absent; any other failure is a ``SourceError``
    holding the ``PlatformError``. A path leading above ``root_path`` (``..``)
    is absent. An empty file is absent unless
    ``preserve_empty_strings``. Files are read at each lookup."""

    root = os.fspath(root_path)

    def build() -> Generator[Effect[Any, Never, PathTag | FileSystem], Any, ConfigProvider]:
        paths = yield from PathTag()
        fs = yield from FileSystem()
        return make(lambda path: _load(paths, fs, root, path, preserve_empty_strings))

    return gen(build)


def _load(
    paths: PathService,
    fs: FileSystemService,
    root: str,
    path: Path,
    preserve_empty_strings: bool,
) -> Effect[Node | None, SourceError]:
    # Like Node's path.join, a segment is joined below the root even when
    # it starts with a separator.
    segments = [str(segment).lstrip("/" + paths.sep) for segment in path]
    full = paths.normalize(paths.join(root, *segments))
    # Unlike Effect, a path whose ``..`` segments lead above the root is
    # absent rather than read.
    if segments and paths.resolve_within(root, paths.join(*segments)) is None:
        return succeed(None)

    def as_file(content: str) -> Node | None:
        value = _js.trim(content)
        return None if value == "" and not preserve_empty_strings else Value(value)

    def as_directory(entries: list[str]) -> Node | None:
        return Record(Keys(paths.basename(entry) for entry in entries))

    def after_file(file_error: PlatformError) -> Effect[Node | None, PlatformError]:
        return (
            fs.read_directory(full)
            .map(as_directory)
            .catch_all(lambda dir_error: _absent_or(file_error, dir_error))
        )

    return (
        fs.read_file_string(full)
        .map(as_file)
        .catch_all(after_file)
        .map_error(lambda cause: SourceError(f"Failed to read file at {full}", cause))
    )


def _absent_or(file_error: PlatformError, dir_error: PlatformError) -> Effect[None, PlatformError]:
    file_missing = isinstance(file_error.reason, NotFound)
    if file_missing and isinstance(dir_error.reason, NotFound):
        return succeed(None)
    return fail(dir_error if file_missing else file_error)
