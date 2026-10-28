"""Errors of platform services (Effect's ``PlatformError``).

``FileSystem``, ``Stdio``, ``Terminal`` and the other platform services fail
with one error class, ``PlatformError``, whose ``reason`` says what went
wrong: a ``BadArgument`` the service rejected before doing anything, or a
``SystemError`` the operating system reported. Each of Effect's system error
tags (``"NotFound"``, ``"PermissionDenied"``, ...) is a subclass of
``SystemError``, so ``catch_reason`` matches them by class::

    fs.read_file_string(path).pipe(
        fx.catch_reason(PlatformError, platform_error.NotFound, lambda _r, _e: fx.succeed(""))
    )

``reason.tag`` is Effect's ``_tag`` string. An ``OSError`` maps to a tag by
its ``errno``, as Node's ``code`` does in Effect's Node file system.
"""

from __future__ import annotations

import errno
from dataclasses import dataclass, field
from typing import ClassVar, Literal

from pyfect.errors import TaggedError

type SystemErrorTag = Literal[
    "AlreadyExists",
    "BadResource",
    "Busy",
    "InvalidData",
    "NotFound",
    "PermissionDenied",
    "TimedOut",
    "UnexpectedEof",
    "Unknown",
    "WouldBlock",
    "WriteZero",
]


@dataclass(eq=False)
class BadArgument(TaggedError):
    """A platform service rejected its input before running."""

    module: str
    method: str
    description: str | None = None
    cause: object = None

    tag: ClassVar[Literal["BadArgument"]] = "BadArgument"

    @property
    def message(self) -> str:
        suffix = f": {self.description}" if self.description else ""
        return f"{self.module}.{self.method}{suffix}"


@dataclass(eq=False)
class SystemError(TaggedError):
    """The operating system reported a failure. Not instantiated itself:
    each tag is a subclass (``NotFound``, ``PermissionDenied``, ...)."""

    module: str
    method: str
    description: str | None = None
    syscall: str | None = None
    path_or_descriptor: str | int | None = None
    cause: object = None

    tag: ClassVar[SystemErrorTag]

    @property
    def message(self) -> str:
        where = "" if self.path_or_descriptor is None else f" ({self.path_or_descriptor})"
        suffix = f": {self.description}" if self.description else ""
        return f"{self.tag}: {self.module}.{self.method}{where}{suffix}"


@dataclass(eq=False)
class AlreadyExists(SystemError):
    tag: ClassVar[SystemErrorTag] = "AlreadyExists"


@dataclass(eq=False)
class BadResource(SystemError):
    tag: ClassVar[SystemErrorTag] = "BadResource"


@dataclass(eq=False)
class Busy(SystemError):
    tag: ClassVar[SystemErrorTag] = "Busy"


@dataclass(eq=False)
class InvalidData(SystemError):
    tag: ClassVar[SystemErrorTag] = "InvalidData"


@dataclass(eq=False)
class NotFound(SystemError):
    tag: ClassVar[SystemErrorTag] = "NotFound"


@dataclass(eq=False)
class PermissionDenied(SystemError):
    tag: ClassVar[SystemErrorTag] = "PermissionDenied"


@dataclass(eq=False)
class TimedOut(SystemError):
    tag: ClassVar[SystemErrorTag] = "TimedOut"


@dataclass(eq=False)
class UnexpectedEof(SystemError):
    tag: ClassVar[SystemErrorTag] = "UnexpectedEof"


@dataclass(eq=False)
class Unknown(SystemError):
    tag: ClassVar[SystemErrorTag] = "Unknown"


@dataclass(eq=False)
class WouldBlock(SystemError):
    tag: ClassVar[SystemErrorTag] = "WouldBlock"


@dataclass(eq=False)
class WriteZero(SystemError):
    tag: ClassVar[SystemErrorTag] = "WriteZero"


_BY_TAG: dict[SystemErrorTag, type[SystemError]] = {
    cls.tag: cls
    for cls in (
        AlreadyExists,
        BadResource,
        Busy,
        InvalidData,
        NotFound,
        PermissionDenied,
        TimedOut,
        UnexpectedEof,
        Unknown,
        WouldBlock,
        WriteZero,
    )
}


@dataclass(eq=False)
class PlatformError(TaggedError):
    """A platform service failed; ``reason`` says how. The reason's
    ``cause`` is this error's ``cause`` too (Python's ``__cause__``)."""

    reason: BadArgument | SystemError
    cause: object = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.cause = self.reason.cause

    @property
    def message(self) -> str:
        return self.reason.message


def system_error(
    tag: SystemErrorTag,
    *,
    module: str,
    method: str,
    description: str | None = None,
    syscall: str | None = None,
    path_or_descriptor: str | int | None = None,
    cause: object = None,
) -> PlatformError:
    """A ``PlatformError`` whose reason is the ``SystemError`` subclass
    named by ``tag``."""
    reason = _BY_TAG[tag](
        module=module,
        method=method,
        description=description,
        syscall=syscall,
        path_or_descriptor=path_or_descriptor,
        cause=cause,
    )
    return PlatformError(reason)


def bad_argument(
    *, module: str, method: str, description: str | None = None, cause: object = None
) -> PlatformError:
    """A ``PlatformError`` whose reason is a ``BadArgument``."""
    return PlatformError(
        BadArgument(module=module, method=method, description=description, cause=cause)
    )


_TAGS_BY_ERRNO: dict[int, SystemErrorTag] = {
    errno.ENOENT: "NotFound",
    errno.EACCES: "PermissionDenied",
    errno.EPERM: "PermissionDenied",
    errno.EEXIST: "AlreadyExists",
    errno.EISDIR: "BadResource",
    errno.ENOTDIR: "BadResource",
    errno.EBUSY: "Busy",
    errno.ELOOP: "BadResource",
}


def tag_of(error: OSError) -> SystemErrorTag:
    """The tag Effect's Node platform gives the same ``errno`` (``Unknown``
    for any other)."""
    return "Unknown" if error.errno is None else _TAGS_BY_ERRNO.get(error.errno, "Unknown")


def from_exception(
    error: Exception, *, module: str, method: str, path_or_descriptor: str | int | None = None
) -> PlatformError:
    """An ``OSError`` as a ``SystemError`` tagged by its ``errno``; any other
    exception (a ``ValueError`` for a path with a NUL byte, say) as a
    ``BadArgument``, as Effect's Node platform reports invalid arguments."""
    if isinstance(error, OSError):
        return system_error(
            tag_of(error),
            module=module,
            method=method,
            path_or_descriptor=path_or_descriptor,
            description=error.strerror,
            cause=error,
        )
    return bad_argument(module=module, method=method, description=str(error), cause=error)


__all__ = [
    "AlreadyExists",
    "BadArgument",
    "BadResource",
    "Busy",
    "InvalidData",
    "NotFound",
    "PermissionDenied",
    "PlatformError",
    "SystemError",
    "SystemErrorTag",
    "TimedOut",
    "UnexpectedEof",
    "Unknown",
    "WouldBlock",
    "WriteZero",
    "bad_argument",
    "from_exception",
    "system_error",
    "tag_of",
]
