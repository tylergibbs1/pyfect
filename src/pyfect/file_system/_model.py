"""The data ``FileSystem`` works with: open flags, file metadata and watch
events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pyfect.byte_size import ByteSize

type OpenFlag = Literal["r", "r+", "w", "wx", "w+", "wx+", "a", "ax", "a+", "ax+"]
"""Node's open flags: ``r`` read, ``w`` truncate or create, ``a`` append or
create, ``x`` fail if the file exists, ``+`` read and write."""

type SeekMode = Literal["start", "current"]

type FileType = Literal[
    "File",
    "Directory",
    "SymbolicLink",
    "BlockDevice",
    "CharacterDevice",
    "FIFO",
    "Socket",
    "Unknown",
]


@dataclass(frozen=True, slots=True)
class DirectoryEntry:
    """A name in a directory listing and the type of the entry itself, not
    of a symbolic link's target. ``"Unknown"`` when the listing could not
    tell."""

    name: str
    type: FileType


@dataclass(frozen=True, slots=True)
class FileInfo:
    """What ``stat`` reports about a file. Times are aware UTC datetimes;
    a field the platform does not report is ``None``."""

    type: FileType
    mtime: datetime | None
    atime: datetime | None
    birthtime: datetime | None
    dev: int
    ino: int | None
    mode: int
    nlink: int | None
    uid: int | None
    gid: int | None
    rdev: int | None
    size: ByteSize
    blksize: ByteSize | None
    blocks: int | None


@dataclass(frozen=True, slots=True)
class Create:
    """A file appeared. ``path`` is relative to the watched directory."""

    path: str


@dataclass(frozen=True, slots=True)
class Update:
    """A file's contents or metadata changed."""

    path: str


@dataclass(frozen=True, slots=True)
class Remove:
    """A file went away."""

    path: str


type WatchEvent = Create | Update | Remove
