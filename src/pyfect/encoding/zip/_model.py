"""The entries and error of ``pyfect.encoding.zip``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, Literal, Never, TypeVar

from pyfect.errors import TaggedError
from pyfect.stream import Stream

type ZipErrorKind = Literal[
    "InvalidHeader",
    "InvalidData",
    "Truncated",
    "Checksum",
    "SizeMismatch",
    "Unsupported",
    "BodyConsumed",
]
type EntryType = Literal["File", "Directory"]
type Method = Literal["Store", "Deflate"]


E_co = TypeVar("E_co", covariant=True, default=Never)
R_co = TypeVar("R_co", covariant=True, default=Never)


@dataclass(eq=False)
class ZipError(TaggedError):
    """A zip archive could not be encoded or decoded.

    - ``"InvalidHeader"``: a header has an unknown signature or a malformed field,
      or an entry has a value that cannot be written.
    - ``"InvalidData"``: the compressed data of an entry is corrupt.
    - ``"Truncated"``: the input ended inside an entry or before the central
      directory.
    - ``"Checksum"``: the data of an entry does not match its CRC-32.
    - ``"SizeMismatch"``: a body produced a byte count other than its ``size``, or
      the data of an entry does not match the sizes in the archive.
    - ``"Unsupported"``: the archive uses a feature this module does not read, such
      as encryption or a compression method other than store and deflate.
    - ``"BodyConsumed"``: a body was read after the decoder had moved past it."""

    kind: ZipErrorKind
    message: str


@dataclass(frozen=True, slots=True)
class Header:
    """The metadata of an entry.

    ``path`` is the archive path, as written, with ``/`` separators; directory paths
    end with ``/``. ``size`` is the uncompressed byte length when it is known before
    the body: decoded entries whose sizes follow their data have none. ``mode`` holds
    Unix permission bits, written to the central directory, which ``decode`` does not
    read. ``mtime`` has a resolution of one second with an extended timestamp and two
    seconds otherwise."""

    path: str
    type: EntryType
    method: Method
    mtime: datetime
    size: int | None = None
    mode: int | None = None


@dataclass(frozen=True, slots=True)
class Entry(Generic[E_co, R_co]):
    """A header and a stream of the uncompressed body bytes. ``decode`` writes these
    and ``file_stream`` builds them; ``encode`` writes the sizes and CRC-32 of a
    streamed body in a data descriptor after the data."""

    header: Header
    body: Stream[bytes, E_co, R_co]


@dataclass(frozen=True, slots=True)
class ContentEntry:
    """An entry whose uncompressed content is in memory. ``file`` and ``directory``
    build these; since the content is known first, ``encode`` puts its sizes and
    CRC-32 in the local header and writes no data descriptor, which every zip reader
    accepts."""

    header: Header
    content: bytes
