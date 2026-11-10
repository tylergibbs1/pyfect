"""Loads migrations by reading a directory (Effect's
``effect/sql/MigratorFileSystem``): ``from_file_system(directory)``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import importlib.util
import re
from collections.abc import Sequence
from typing import Any

from pyfect._core import Effect, _Suspend
from pyfect.effect import succeed
from pyfect.file_system import FileSystem
from pyfect.path import Path
from pyfect.sql.migrator import Loader, MigrationError, ResolvedMigration, _sorted

_FILE_NAME = re.compile(r"^(?:.*/)?([0-9]+)_([^.]+)\.py$")


def _import(path: str, module_name: str) -> object:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def from_file_system(directory: str) -> Loader[FileSystem | Path]:
    """The ``<id>_<name>.py`` modules of ``directory``; each migration is
    the module's ``default``."""

    def read(fs: Any, path: Any) -> Loader:
        def failed(cause: object) -> MigrationError:
            return MigrationError(
                kind="Failed", cause=cause, message="Failed to read migrations directory"
            )

        def resolve(files: Sequence[str]) -> list[ResolvedMigration]:
            found: list[ResolvedMigration] = []
            for file in files:
                match = _FILE_NAME.match(file)
                if match is None:
                    continue
                basename = match[0].rsplit("/", 1)[-1]
                full = path.join(directory, basename)
                module_name = f"pyfect_migration_{match[1]}_{match[2]}"
                load: Effect[object] = _Suspend(
                    lambda full=full, module_name=module_name: succeed(_import(full, module_name))
                )
                found.append((int(match[1]), match[2], load))
            return _sorted(found)

        listed: Effect[Sequence[str], Any] = fs.read_directory(directory)
        return listed.map_error(failed).map(resolve)

    return FileSystem().flat_map(lambda fs: Path().flat_map(lambda path: read(fs, path)))


__all__ = ["from_file_system"]
