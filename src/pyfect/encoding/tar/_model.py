"""The entries and error of ``pyfect.encoding.tar``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Generic, Literal, Never, TypeVar

from pyfect.errors import TaggedError
from pyfect.stream import Stream

type TarErrorKind = Literal[
    "InvalidHeader", "Truncated", "SizeMismatch", "Unsupported", "BodyConsumed"
]
type EntryType = Literal[
    "File", "Directory", "Symlink", "Hardlink", "CharDevice", "BlockDevice", "Fifo", "Other"
]
"""``"Other"`` covers every typeflag without a kind of its own, such as GNU volume
labels; the raw flag is in ``Header.typeflag``."""


E_co = TypeVar("E_co", covariant=True, default=Never)
R_co = TypeVar("R_co", covariant=True, default=Never)


@dataclass(frozen=True, slots=True)
class FarDate:
    """An instant ``datetime`` cannot hold, past years 1 to 9999 but within
    JavaScript's ``Date``: milliseconds since the Unix epoch."""

    epoch_millis: int


@dataclass(eq=False)
class TarError(TaggedError):
    """A tar archive could not be encoded or decoded.

    - ``"InvalidHeader"``: a header has a bad checksum, a malformed field, or a
      value that cannot be written.
    - ``"Truncated"``: the input ended inside a header or an entry body.
    - ``"SizeMismatch"``: a body produced a byte count other than its ``size``.
    - ``"Unsupported"``: the archive uses a feature this module does not read,
      such as GNU sparse files.
    - ``"BodyConsumed"``: a body was read after the decoder had moved past it."""

    kind: TarErrorKind
    message: str


@dataclass(frozen=True, slots=True)
class Header:
    """The metadata of an entry.

    ``path`` and ``link_target`` are archive paths, as written; a hard link's
    target names another entry of the archive. ``mode`` holds the permission bits,
    with setuid, setgid and sticky; file type bits are dropped both ways. ``pax``
    holds the PAX records no other field reflects, global ones included.
    ``dev_major`` and ``dev_minor`` are set for device entries only."""

    path: str
    type: EntryType
    typeflag: str
    size: int
    mode: int
    uid: int
    gid: int
    uname: str
    gname: str
    mtime: datetime | FarDate
    link_target: str | None = None
    dev_major: int | None = None
    dev_minor: int | None = None
    pax: Mapping[str, str] = field(default_factory=dict[str, str], hash=False)


@dataclass(frozen=True, slots=True)
class Entry(Generic[E_co, R_co]):
    """A header and a stream of exactly ``header.size`` body bytes."""

    header: Header
    body: Stream[bytes, E_co, R_co]
