"""Zip's records, times, names and validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

from pyfect._json_text import quote as quoted
from pyfect.encoding.zip._model import Header, ZipError

LOCAL: Final = 0x04034B50
CENTRAL: Final = 0x02014B50
DESCRIPTOR: Final = 0x08074B50
END: Final = 0x06054B50
END64: Final = 0x06064B50
LOCATOR64: Final = 0x07064B50

FLAG_ENCRYPTED: Final = 0x0001
FLAG_DESCRIPTOR: Final = 0x0008
FLAG_STRONG_ENCRYPTION: Final = 0x0040
FLAG_UTF8: Final = 0x0800

EXTRA_ZIP64: Final = 0x0001
EXTRA_TIMESTAMP: Final = 0x5455
EXTRA_UNICODE_PATH: Final = 0x7075

MAX16: Final = 0xFFFF
MAX32: Final = 0xFFFFFFFF
MAX_SAFE_INTEGER: Final = 2**53 - 1

EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
MIN_MTIME: Final = datetime(1980, 1, 1, tzinfo=UTC)

_PAST_DOS_TIMES = datetime(2108, 1, 1, tzinfo=UTC)


def invalid_header(message: str) -> ZipError:
    return ZipError("InvalidHeader", message)


def size_mismatch(path: str, actual: int, expected: int) -> ZipError:
    return ZipError(
        "SizeMismatch",
        f"body of {quoted(path)} has {'at least' if actual > expected else 'only'} {actual} "
        f"bytes, but its size is {expected}",
    )


def to_dos(mtime: datetime) -> tuple[int, int]:
    """``(time, date)``: DOS times have two-second resolution and cover 1980 to 2107."""
    if mtime < MIN_MTIME:
        return 0, (1 << 5) | 1
    if mtime >= _PAST_DOS_TIMES:
        return (23 << 11) | (59 << 5) | 29, (127 << 9) | (12 << 5) | 31
    utc = mtime.astimezone(UTC)
    return (
        (utc.hour << 11) | (utc.minute << 5) | (utc.second >> 1),
        ((utc.year - 1980) << 9) | (utc.month << 5) | utc.day,
    )


def from_dos(time: int, date: int) -> datetime:
    """``Date.UTC`` of DOS fields, whose out-of-range values carry over: month 0 is
    the previous December, and day 0 the last day of the previous month."""
    month = ((date >> 5) & 0xF) - 1
    first = datetime((date >> 9) + 1980 + month // 12, month % 12 + 1, 1, tzinfo=UTC)
    return first + timedelta(
        days=(date & 0x1F) - 1,
        hours=time >> 11,
        minutes=(time >> 5) & 0x3F,
        seconds=(time & 0x1F) * 2,
    )


def decode_name(data: bytes, utf8: bool) -> str:
    """Paths keep a leading byte order mark, as other zip tools do."""
    if utf8:
        return data.decode("utf-8", "replace")
    try:
        return data.decode()
    except UnicodeDecodeError:
        return data.decode("cp437")


_DRIVE_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")


def validate(header: Header) -> None:  # noqa: PLR0912
    path = header.path
    if path == "":
        raise invalid_header("path is empty")
    name = quoted(path)
    if path.startswith("/"):
        raise invalid_header(f"path {name} is absolute")
    # The zip format forbids these, and libarchive reads them as separators and roots
    if "\\" in path:
        raise invalid_header(f"path {name} contains a backslash")
    if path[:1] in _DRIVE_LETTERS and path[1:2] == ":":
        raise invalid_header(f"path {name} starts with a drive letter")
    if "\0" in path:
        raise invalid_header(f"path {name} contains a NUL character")
    if header.type == "File":
        if path.endswith("/"):
            raise invalid_header(f'file path {name} ends with "/"')
        if header.method not in ("Store", "Deflate"):
            raise invalid_header(f"unknown method for {name}")
    elif header.type == "Directory":
        if not path.endswith("/"):
            raise invalid_header(f'directory path {name} does not end with "/"')
        if header.size not in (None, 0):
            raise invalid_header(f"directory {name} has a size")
    else:
        raise invalid_header(f"unknown entry type for {name}")
    size = header.size
    if size is not None and not (isinstance(size, int) and 0 <= size <= MAX_SAFE_INTEGER):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise invalid_header(f"size of {name} is not a non-negative safe integer")
    mode = header.mode
    if mode is not None and not (isinstance(mode, int) and 0 <= mode <= 0o7777):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise invalid_header(f"mode of {name} is not a permission mode")
    # A naive ``datetime`` names no instant: JavaScript's invalid date
    if header.mtime.utcoffset() is None:
        raise invalid_header(f"mtime of {name} is not a valid date")
