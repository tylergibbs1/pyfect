"""``Logger.to_file``: a logger appending lines to a file through the
``FileSystem`` service."""

from __future__ import annotations

from collections.abc import Generator, Sequence
from typing import Any

from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect.duration import Duration
from pyfect.effect import gen
from pyfect.file_system import FileSystem, OpenFlag
from pyfect.logger._model import Logger
from pyfect.platform_error import PlatformError
from pyfect.scope import Scope


def to_file(
    logger: Logger[str], path: str, *, flag: OpenFlag, mode: int, batch_window: Duration
) -> Effect[Logger[None], PlatformError, Scope | FileSystem]:
    def build() -> Generator[Effect[Any, PlatformError, Scope | FileSystem], Any, Logger[None]]:
        fs = yield from FileSystem()
        file = yield from fs.open(path, flag=flag, mode=mode)

        def flush(lines: Sequence[str]) -> Effect[object]:
            return file.write_all(text_encode("\n".join(lines) + "\n")).ignore()

        return (yield from logger.batched(window=batch_window, flush=flush))

    return gen(build)
