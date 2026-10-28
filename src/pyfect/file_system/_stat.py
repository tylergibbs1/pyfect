"""``os.stat_result`` as ``FileInfo``."""

from __future__ import annotations

import os
import stat as st
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pyfect.byte_size import ByteSize
from pyfect.file_system._model import FileInfo, FileType

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_UINT64 = 2**64 - 1


_TYPES: tuple[tuple[Callable[[int], bool], FileType], ...] = (
    (st.S_ISREG, "File"),
    (st.S_ISDIR, "Directory"),
    (st.S_ISLNK, "SymbolicLink"),
    (st.S_ISBLK, "BlockDevice"),
    (st.S_ISCHR, "CharacterDevice"),
    (st.S_ISFIFO, "FIFO"),
    (st.S_ISSOCK, "Socket"),
)


def _type(mode: int) -> FileType:
    for test, name in _TYPES:
        if test(mode):
            return name
    return "Unknown"


def from_nanos(nanos: int) -> datetime:
    """An aware UTC datetime, the nanoseconds cut to microseconds."""
    return EPOCH + timedelta(microseconds=nanos // 1000)


def _birthtime(result: os.stat_result) -> datetime | None:
    nanos: int | None = getattr(result, "st_birthtime_ns", None)
    if nanos is not None:
        return from_nanos(nanos)
    seconds: float | None = getattr(result, "st_birthtime", None)
    return None if seconds is None else from_nanos(round(seconds * 1e9))


def file_info(result: os.stat_result) -> FileInfo:
    """Device and inode numbers read as unsigned 64-bit integers, as Effect
    reads Node's."""
    rdev: int | None = getattr(result, "st_rdev", None)
    blksize: int | None = getattr(result, "st_blksize", None)
    blocks: int | None = getattr(result, "st_blocks", None)
    return FileInfo(
        type=_type(result.st_mode),
        mtime=from_nanos(result.st_mtime_ns),
        atime=from_nanos(result.st_atime_ns),
        birthtime=_birthtime(result),
        dev=result.st_dev & _UINT64,
        ino=result.st_ino & _UINT64,
        mode=result.st_mode,
        nlink=result.st_nlink,
        uid=result.st_uid,
        gid=result.st_gid,
        rdev=None if rdev is None else rdev & _UINT64,
        size=ByteSize(result.st_size),
        blksize=None if blksize is None else ByteSize(blksize),
        blocks=blocks,
    )
