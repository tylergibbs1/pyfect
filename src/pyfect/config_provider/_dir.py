"""``from_dir``: one file per key, as Kubernetes and Docker mount secrets."""

from __future__ import annotations

import os
from pathlib import Path as FilePath

from pyfect._core import Effect
from pyfect.config_provider._node import Node, Path, Record, SourceError, Value
from pyfect.config_provider._provider import ConfigProvider, make
from pyfect.effect import try_blocking


def from_dir(
    root_path: str | os.PathLike[str] = "/", *, preserve_empty_strings: bool = False
) -> ConfigProvider:
    """A provider over the files under ``root_path``: the path ``("db",
    "password")`` reads the file ``<root_path>/db/password`` (trimmed) as a
    value, and a directory is a record of its entry names. A missing path is
    absent; any other read error (a permission error, say) fails with a
    ``SourceError``. An empty file is absent unless ``preserve_empty_strings``.
    Files are read on a worker thread at each lookup."""
    root = os.fspath(root_path)
    return make(lambda path: _load(root, path, preserve_empty_strings))


def _load(root: str, path: Path, preserve_empty_strings: bool) -> Effect[Node | None, SourceError]:
    # Like Node's path.join: a segment is joined below the root even when it
    # starts with a separator.
    full = os.path.normpath(os.path.join(root, *(str(seg).lstrip("/\\") for seg in path)))
    return try_blocking(
        lambda: _read(full, preserve_empty_strings),
        lambda error: SourceError(f"Failed to read file at {full}", error),
    )


def _read(full: str, preserve_empty_strings: bool) -> Node | None:
    try:
        content = FilePath(full).read_text(encoding="utf-8").strip()
    except OSError as file_error:
        try:
            return _directory(full)
        except OSError as dir_error:
            if not isinstance(file_error, FileNotFoundError):
                raise file_error from None
            if not isinstance(dir_error, FileNotFoundError):
                raise
            return None
    return None if content == "" and not preserve_empty_strings else Value(content)


def _directory(full: str) -> Record:
    return Record(frozenset(os.listdir(full)))
