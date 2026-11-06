"""Tar's header blocks and PAX records, read and written."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from pyfect._digits import is_digits, parse_digits
from pyfect._js import js_sort_key, text_encode
from pyfect._json_text import quote as quoted
from pyfect.encoding.tar._model import EntryType, Header, TarError

BLOCK: Final = 512
PERMISSION_BITS: Final = 0o7777
MAX_SAFE_INTEGER: Final = 2**53 - 1
EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)

_USTAR_MAGIC = b"ustar\0"
_GNU_MAGIC = b"ustar  \0"
_STAR_TRAILER = b"tar\0"
_USTAR_MAGIC_VERSION = b"ustar\x0000"
_MAX_OCTAL_7 = 0o7777777  # 8-byte numeric fields
_MAX_OCTAL_11 = 0o77777777777  # 12-byte numeric fields
_MAX_DATE_MILLIS = 8_640_000_000_000_000  # the range of JavaScript's ``Date``
_MIN_MILLIS = (datetime(1, 1, 1, tzinfo=UTC) - EPOCH) // timedelta(milliseconds=1)
_MAX_MILLIS = (datetime(9999, 12, 31, 23, 59, 59, 999000, tzinfo=UTC) - EPOCH) // timedelta(
    milliseconds=1
)
_MAX_SAFE_DIGITS = 16
"""More digits than a safe integer has: ``int`` raises past 4300 digits."""

TYPEFLAGS: Final[Mapping[EntryType, str]] = {
    "File": "0",
    "Hardlink": "1",
    "Symlink": "2",
    "CharDevice": "3",
    "BlockDevice": "4",
    "Directory": "5",
    "Fifo": "6",
}
_TYPES: Mapping[str, EntryType] = {
    **{flag: kind for kind, flag in TYPEFLAGS.items()},
    "7": "File",  # contiguous files
}
_PAX_STRING_KEYS = frozenset(("path", "linkpath", "uname", "gname"))
_PAX_HEADER_KEYS = frozenset(("path", "linkpath", "size", "uid", "gid", "uname", "gname", "mtime"))

_TIME = re.compile(r"(-?)([0-9]+)(?:\.([0-9]+))?")
_NONZERO = re.compile(r"[1-9]")


def invalid_header(message: str) -> TarError:
    return TarError("InvalidHeader", message)


def unsupported(message: str) -> TarError:
    return TarError("Unsupported", message)


def padding(size: int) -> int:
    return (BLOCK - size % BLOCK) % BLOCK


def is_header_only(kind: EntryType) -> bool:
    """Entries of these types never carry body bytes, whatever their size says."""
    return kind not in ("File", "Other")


def millis_of(mtime: datetime) -> int | None:
    """``Date.getTime()``, or ``None`` for a naive ``datetime``, which names no
    instant (JavaScript's invalid date)."""
    if mtime.utcoffset() is None:
        return None
    return (mtime - EPOCH) // timedelta(milliseconds=1)


def read_string(block: bytes, offset: int, length: int) -> str:
    """The NUL-terminated text of a field; invalid UTF-8 becomes U+FFFD, and a
    leading byte order mark stays."""
    end = block.find(0, offset, offset + length)
    return block[offset : offset + length if end == -1 else end].decode("utf-8", "replace")


def _read_octal(block: bytes, offset: int, length: int) -> int:
    start = offset
    end = offset + length
    while start < end and block[start] in (0, 0x20):
        start += 1
    while end > start and block[end - 1] in (0, 0x20):
        end -= 1
    value = 0
    for i in range(start, end):
        c = block[i]
        if c < 0x30 or c > 0x37:
            raise invalid_header(f"invalid octal number in the header field at offset {offset}")
        value = value * 8 + (c - 0x30)
    return value


def _read_number(block: bytes, offset: int, length: int) -> int:
    """GNU base-256: the high bit of the first byte is set, and the next bit is
    the sign of a two's complement big-endian number."""
    if block[offset] & 0x80 == 0:
        return _read_octal(block, offset, length)
    negative = block[offset] & 0x40 != 0
    # Negative numbers are read as the bitwise inverse of their magnitude minus one
    value = 0
    for i in range(length):
        c = block[offset + i]
        if negative:
            c ^= 0xFF
        if i == 0:
            c &= 0x7F
        value = value * 256 + c
        if value > MAX_SAFE_INTEGER:
            raise invalid_header(
                f"base-256 number in the header field at offset {offset} is out of range"
            )
    return -value - 1 if negative else value


def _read_unsigned(block: bytes, offset: int, length: int, field: str) -> int:
    value = _read_number(block, offset, length)
    if value < 0:
        raise invalid_header(f"negative {field}")
    return value


def _verify_checksum(block: bytes) -> bool:
    """The checksum is the sum of the block bytes with the checksum field counted
    as spaces. Some old tar writers summed signed bytes, which is accepted too."""
    stored = _read_octal(block, 148, 8)
    rest = block[:148] + block[156:]
    unsigned = sum(rest) + 8 * 0x20
    if stored == unsigned:
        return True
    high = sum(1 for byte in rest if byte > 0x7F)
    return stored == unsigned - 0x100 * high


@dataclass(slots=True)
class RawHeader:
    typeflag: str
    path: str
    link_target: str
    size: int
    mode: int
    uid: int
    gid: int
    uname: str
    gname: str
    mtime_millis: int
    dev_major: int
    dev_minor: int


def parse_header(block: bytes) -> RawHeader:
    if not _verify_checksum(block):
        raise invalid_header("header checksum mismatch")
    is_ustar = block.startswith(_USTAR_MAGIC, 257)
    is_gnu = not is_ustar and block.startswith(_GNU_MAGIC, 257)
    header = RawHeader(
        typeflag=chr(block[156]),
        path=read_string(block, 0, 100),
        link_target=read_string(block, 157, 100),
        size=_read_unsigned(block, 124, 12, "size"),
        mode=_read_unsigned(block, 100, 8, "mode"),
        uid=_read_unsigned(block, 108, 8, "uid"),
        gid=_read_unsigned(block, 116, 8, "gid"),
        mtime_millis=_read_number(block, 136, 12) * 1000,
        uname="",
        gname="",
        dev_major=0,
        dev_minor=0,
    )
    if not is_ustar and not is_gnu:
        return header
    header.uname = read_string(block, 265, 32)
    header.gname = read_string(block, 297, 32)
    header.dev_major = _read_unsigned(block, 329, 8, "devMajor")
    header.dev_minor = _read_unsigned(block, 337, 8, "devMinor")
    if is_ustar:
        # star archives end the block with "tar\0" and keep times after a shorter prefix
        prefix = read_string(block, 345, 131 if block.startswith(_STAR_TRAILER, 508) else 155)
        if prefix:
            header.path = f"{prefix}/{header.path}"
    return header


def parse_pax(data: bytes) -> dict[str, str]:
    """Parses records of the form ``<length> <key>=<value>\\n``, where the length
    counts the bytes of the whole record."""
    records: dict[str, str] = {}
    offset = 0
    size = len(data)
    while offset < size:
        space = offset
        while space < size and space - offset < 16 and data[space] != 0x20:
            space += 1
        field = data[offset:space]
        length = parse_digits(field.decode("latin-1"))
        end = offset + (length or 0)
        if (
            length is None
            or length < 5
            or end > size
            or space >= size
            or data[space] != 0x20
            or space + 1 >= end
            or data[end - 1] != 0x0A
        ):
            raise invalid_header("malformed PAX record")
        record = data[space + 1 : end - 1]
        equals = record.find(0x3D)
        if equals <= 0:
            raise invalid_header("malformed PAX record")
        key = record[:equals].decode("utf-8", "replace")
        value = record[equals + 1 :].decode("utf-8", "replace")
        if "\0" in key or (key in _PAX_STRING_KEYS and "\0" in value):
            raise invalid_header(f"invalid PAX record {key}")
        records[key] = value
        offset = end
    return records


def _pax_integer(key: str, value: str) -> int:
    significant = value.lstrip("0")
    if (
        not is_digits(value)
        or len(significant) > _MAX_SAFE_DIGITS
        or int(significant or "0") > MAX_SAFE_INTEGER
    ):
        raise invalid_header(f"invalid PAX {key} {quoted(value)}")
    return int(significant or "0")


def _pax_millis(value: str) -> int:
    """A PAX time of decimal seconds as milliseconds, rounded down."""
    match = _TIME.fullmatch(value)
    if match is None:
        raise invalid_header(f"invalid PAX mtime {quoted(value)}")
    sign, seconds, fraction = match[1], match[2], match[3] or ""
    significant = seconds.lstrip("0")
    if len(significant) > _MAX_SAFE_DIGITS:
        # Past every date, which ``to_header`` reports; ``int`` raises past 4300 digits
        return _MAX_DATE_MILLIS + 1
    millis = int(significant or "0") * 1000 + int(fraction[:3].ljust(3, "0"))
    if sign == "":
        return millis
    # A negative time with digits below a millisecond rounds down past them
    return -millis - (1 if _NONZERO.search(fraction[3:]) else 0)


def apply_pax(header: RawHeader, records: Mapping[str, str]) -> dict[str, str]:
    """Applies the records that override header fields and returns the rest. An
    empty value keeps the field from the header block."""
    rest: dict[str, str] = {}
    for key, value in records.items():
        if key.startswith("GNU.sparse."):
            raise unsupported("GNU sparse files are not supported")
        if key not in _PAX_HEADER_KEYS:
            rest[key] = value
        elif value == "":
            continue
        elif key == "path":
            header.path = value
        elif key == "linkpath":
            header.link_target = value
        elif key == "uname":
            header.uname = value
        elif key == "gname":
            header.gname = value
        elif key == "uid":
            header.uid = _pax_integer(key, value)
        elif key == "gid":
            header.gid = _pax_integer(key, value)
        elif key == "size":
            header.size = _pax_integer(key, value)
        else:
            header.mtime_millis = _pax_millis(value)
    return rest


def to_mtime(millis: int) -> datetime:
    """``new Date(millis)``. Past JavaScript's range or years 1 to 9999, which
    ``datetime`` holds, the archive fails."""
    if abs(millis) > _MAX_DATE_MILLIS or not _MIN_MILLIS <= millis <= _MAX_MILLIS:
        raise invalid_header("mtime is out of range")
    return EPOCH + timedelta(milliseconds=millis)


def entry_type(typeflag: str, path: str) -> EntryType:
    # Legacy archives mark directories with a trailing slash only
    if typeflag == "\0":
        return "Directory" if path.endswith("/") else "File"
    return _TYPES.get(typeflag, "Other")


def _pax_record(key: str, value: str) -> bytes:
    rest = text_encode(f" {key}={value}\n")
    # The length counts its own digits
    length = len(rest) + len(str(len(rest) + len(str(len(rest)))))
    return text_encode(str(length)) + rest


def _pax_header_name(path: str) -> str:
    trimmed = path.rstrip("/")
    i = trimmed.rfind("/")
    name = (
        f"PaxHeaders.0/{trimmed}" if i == -1 else f"{trimmed[:i]}/PaxHeaders.0/{trimmed[i + 1 :]}"
    )
    return _to_ascii(name)[:100]


def _is_ascii(text: str) -> bool:
    return text.isascii() and "\0" not in text


def _to_ascii(text: str) -> str:
    """The ASCII characters of a value that is also stored in a PAX record."""
    return "".join(char for char in text if "\0" < char < "\x80")


def _fits(value: str, length: int) -> bool:
    return len(value) <= length and _is_ascii(value)


def _split_path(path: str) -> tuple[str, str] | None:
    """Split at the last slash that fits the 155-byte USTAR prefix."""
    if len(path) <= 100 or not _is_ascii(path):
        return None
    length = len(path)
    if length > 156:
        length = 156
    elif path[length - 1] == "/":
        length -= 1
    i = path.rfind("/", 0, length)
    if i <= 0 or len(path) - i - 1 > 100:
        return None
    return path[:i], path[i + 1 :]


def _octal(value: int, length: int) -> bytes:
    """``length - 1`` zero-padded octal digits; the value must fit."""
    return text_encode(f"{value:0{length - 1}o}")


def _ustar_block(
    *,
    name: str,
    prefix: str = "",
    typeflag: str,
    size: int = 0,
    mode: int = 0o644,
    uid: int = 0,
    gid: int = 0,
    mtime: int = 0,
    linkname: str = "",
    uname: str = "",
    gname: str = "",
    dev_major: int = 0,
    dev_minor: int = 0,
) -> bytes:
    block = bytearray(BLOCK)
    block[0 : len(name)] = text_encode(name)
    block[100:107] = _octal(mode, 8)
    block[108:115] = _octal(uid, 8)
    block[116:123] = _octal(gid, 8)
    block[124:135] = _octal(size, 12)
    block[136:147] = _octal(mtime, 12)
    block[156] = ord(typeflag)
    block[157 : 157 + len(linkname)] = text_encode(linkname)
    block[257:265] = _USTAR_MAGIC_VERSION
    block[265 : 265 + len(uname)] = text_encode(uname)
    block[297 : 297 + len(gname)] = text_encode(gname)
    block[329:336] = _octal(dev_major, 8)
    block[337:344] = _octal(dev_minor, 8)
    block[345 : 345 + len(prefix)] = text_encode(prefix)
    block[148:156] = b" " * 8
    # Six digits, a NUL and the space left from the fill
    block[148:154] = _octal(sum(block), 7)
    block[154] = 0
    return bytes(block)


def _check_number(field: str, value: object, largest: int) -> int:
    if not isinstance(value, int) or value < 0 or value > largest:
        raise invalid_header(f"invalid {field} {value}")
    return value


def _check_no_nul(field: str, value: str) -> str:
    if "\0" in value:
        raise invalid_header(f"{field} must not contain NUL characters")
    return value


def encode_header(header: Header) -> bytes:  # noqa: PLR0912, PLR0915
    """The header blocks of an entry, with a PAX header first when needed."""
    path = _check_no_nul("path", header.path)
    if path == "":
        raise invalid_header("path must not be empty")
    # GNU tar and node-tar read such an entry as a directory
    if header.type == "File" and path.endswith("/"):
        raise invalid_header(f'File entry {quoted(path)} must not end with "/"')
    typeflag = header.typeflag if header.type == "Other" else TYPEFLAGS[header.type]
    if len(typeflag) != 1 or ord(typeflag) >= 0x80 or typeflag in "xgLKS":
        raise invalid_header(f"invalid typeflag {quoted(typeflag)}")
    size = _check_number("size", header.size, MAX_SAFE_INTEGER)
    if size > 0 and is_header_only(header.type):
        raise invalid_header(f"{header.type} entry {quoted(path)} must have size 0")
    mode = _check_number("mode", header.mode, MAX_SAFE_INTEGER) & PERMISSION_BITS
    uid = _check_number("uid", header.uid, MAX_SAFE_INTEGER)
    gid = _check_number("gid", header.gid, MAX_SAFE_INTEGER)
    dev_major = _check_number("devMajor", header.dev_major or 0, _MAX_OCTAL_7)
    dev_minor = _check_number("devMinor", header.dev_minor or 0, _MAX_OCTAL_7)
    millis = millis_of(header.mtime)
    if millis is None:
        raise invalid_header("mtime must be a valid date")
    mtime = millis // 1000

    # Records of the PAX header. Their keys are unique, as custom records cannot
    # use the keys of header fields.
    pax: list[tuple[str, str]] = []
    for key, value in header.pax.items():
        if key.startswith("GNU.sparse."):
            raise invalid_header(f"PAX record {quoted(key)} is not supported")
        if key in _PAX_HEADER_KEYS:
            raise invalid_header(f"PAX record {quoted(key)} must be set through its header field")
        if key == "" or "=" in key or "\0" in key:
            raise invalid_header(f"invalid PAX record {quoted(key)}")
        pax.append((key, value))

    # PAX holds overflow values; USTAR keeps truncated ASCII strings or zero.
    split = _split_path(path)
    link_target = _check_no_nul("linkTarget", header.link_target or "")
    uname = _check_no_nul("uname", header.uname)
    gname = _check_no_nul("gname", header.gname)
    path_fits = split is not None or _fits(path, 100)
    link_target_fits = _fits(link_target, 100)
    uname_fits = _fits(uname, 32)
    gname_fits = _fits(gname, 32)
    if not path_fits:
        pax.append(("path", path))
    if not link_target_fits:
        pax.append(("linkpath", link_target))
    if not uname_fits:
        pax.append(("uname", uname))
    if not gname_fits:
        pax.append(("gname", gname))
    if size > _MAX_OCTAL_11:
        pax.append(("size", str(size)))
    if uid > _MAX_OCTAL_7:
        pax.append(("uid", str(uid)))
    if gid > _MAX_OCTAL_7:
        pax.append(("gid", str(gid)))
    if mtime < 0 or mtime > _MAX_OCTAL_11:
        pax.append(("mtime", str(mtime)))

    fitting = path if path_fits else _to_ascii(path)[:100]
    name = fitting if split is None else split[1]
    ustar = _ustar_block(
        name=name,
        prefix=split[0] if split is not None else "",
        typeflag=typeflag,
        size=0 if size > _MAX_OCTAL_11 else size,
        mode=mode,
        uid=0 if uid > _MAX_OCTAL_7 else uid,
        gid=0 if gid > _MAX_OCTAL_7 else gid,
        mtime=0 if mtime < 0 or mtime > _MAX_OCTAL_11 else mtime,
        linkname=link_target if link_target_fits else _to_ascii(link_target)[:100],
        uname=uname if uname_fits else _to_ascii(uname)[:32],
        gname=gname if gname_fits else _to_ascii(gname)[:32],
        dev_major=dev_major,
        dev_minor=dev_minor,
    )
    if not pax:
        return ustar
    pax.sort(key=lambda record: js_sort_key(record[0]))
    data = b"".join(_pax_record(key, value) for key, value in pax)
    data_blocks = math.ceil(len(data) / BLOCK)
    return (
        _ustar_block(name=_pax_header_name(path), typeflag="x", size=len(data))
        + data.ljust(data_blocks * BLOCK, b"\0")
        + ustar
    )
