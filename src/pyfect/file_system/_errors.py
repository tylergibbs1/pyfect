"""Running a blocking file system call and reporting its failure as a
``PlatformError``."""

from __future__ import annotations

from collections.abc import Callable

from pyfect._core import Effect
from pyfect.effect import try_blocking
from pyfect.platform_error import PlatformError, from_exception, system_error


def run[A](method: str, path: str | int | None, thunk: Callable[[], A]) -> Effect[A, PlatformError]:
    """``thunk`` on a worker thread; what it raises is a ``PlatformError``
    for ``FileSystem.<method>`` on ``path`` (Effect's Node file system
    reports the first path argument)."""
    return try_blocking(
        thunk,
        lambda error: from_exception(
            error, module="FileSystem", method=method, path_or_descriptor=path
        ),
    )


def not_found(method: str, path: str) -> PlatformError:
    return system_error(
        "NotFound",
        module="FileSystem",
        method=method,
        description="No such file or directory",
        path_or_descriptor=path,
    )
