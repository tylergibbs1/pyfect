"""The inputs ``test_archive_node.py`` runs through this port and
``archive_oracle.ts`` through Effect. Deflate data here is hand-built or from the
fixtures, as bytes from the local zlib could change the recorded results."""

from __future__ import annotations

import base64
import gzip
import json
import zlib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def split(data: bytes, size: int) -> list[str]:
    return [b64(data[i : i + size]) for i in range(0, len(data), size)]


# Tar blocks


def octal(value: int, length: int) -> bytes:
    return f"{value:0{length - 1}o}".encode() + b"\0"


def tar_block(
    name: bytes = b"f",
    *,
    typeflag: bytes = b"0",
    size: bytes | int = 0,
    mode: bytes | int = 0o644,
    uid: bytes | int = 0,
    gid: bytes | int = 0,
    mtime: bytes | int = 0,
    link: bytes = b"",
    magic: bytes = b"ustar\x0000",
    prefix: bytes = b"",
    dev_major: bytes | int = 0,
    dev_minor: bytes | int = 0,
    checksum: bytes | None = None,
) -> bytes:
    def number(value: bytes | int, length: int) -> bytes:
        return value.ljust(length, b"\0") if isinstance(value, bytes) else octal(value, length)

    block = bytearray(512)
    block[0 : len(name)] = name
    block[100:108] = number(mode, 8)
    block[108:116] = number(uid, 8)
    block[116:124] = number(gid, 8)
    block[124:136] = number(size, 12)
    block[136:148] = number(mtime, 12)
    block[156:157] = typeflag
    block[157 : 157 + len(link)] = link
    block[257 : 257 + len(magic)] = magic
    block[329:337] = number(dev_major, 8)
    block[337:345] = number(dev_minor, 8)
    block[345 : 345 + len(prefix)] = prefix
    block[148:156] = b" " * 8
    block[148:156] = checksum if checksum is not None else f"{sum(block):06o}\0 ".encode()
    return bytes(block)


def pad(data: bytes) -> bytes:
    return data + bytes(-len(data) % 512)


END_OF_TAR = bytes(1024)


def tar_file(name: bytes, body: bytes = b"", **fields: Any) -> bytes:
    return tar_block(name, size=len(body), **fields) + pad(body)


def pax_record(key: str, value: str) -> bytes:
    rest = f" {key}={value}\n".encode()
    size = len(rest)
    while len(str(size)) + len(rest) != size:
        size = len(str(size)) + len(rest)
    return str(size).encode() + rest


def pax(data: bytes, *, typeflag: bytes = b"x") -> bytes:
    return tar_block(b"PaxHeaders/f", typeflag=typeflag, size=len(data)) + pad(data)


def pax_entry(records: dict[str, str], *, typeflag: bytes = b"x") -> bytes:
    data = b"".join(pax_record(k, v) for k, v in records.items())
    return pax(data, typeflag=typeflag)


def tar_cases() -> Iterable[tuple[str, bytes]]:  # noqa: PLR0915
    for name in ("gnu", "pax", "ustar", "v7", "sparse-gnu", "sparse-pax"):
        data = gzip.decompress((FIXTURES / "tar" / f"{name}.tar.gz").read_bytes())
        yield f"fixture/{name}", data
    small = gzip.decompress((FIXTURES / "tar" / "ustar.tar.gz").read_bytes())
    for at in (*range(0, 1600, 113), 511, 512, 513, 1023, 1024, len(small) - 512):
        yield f"truncated/ustar/{at}", small[:at]
    paxed = gzip.decompress((FIXTURES / "tar" / "pax.tar.gz").read_bytes())
    for at in range(0, 3000, 257):
        yield f"truncated/pax/{at}", paxed[:at]
    gnu = gzip.decompress((FIXTURES / "tar" / "gnu.tar.gz").read_bytes())
    for at in range(0, 3000, 257):
        yield f"truncated/gnu/{at}", gnu[:at]
    for at in (0, 100, 108, 124, 136, 148, 156, 157, 257, 263, 265, 329, 345, 511):
        corrupt = bytearray(small)
        corrupt[at] ^= 0x41
        yield f"corrupt/{at}", bytes(corrupt)

    body = tar_file(b"ok", b"body")
    yield "traversal/dotdot", tar_file(b"../../etc/passwd", b"x") + END_OF_TAR
    yield "traversal/absolute", tar_file(b"/etc/passwd", b"x") + END_OF_TAR
    yield (
        "traversal/symlink-then-write",
        tar_block(b"out", typeflag=b"2", link=b"/etc") + tar_file(b"out/passwd", b"x") + END_OF_TAR,
    )
    yield "traversal/hardlink", tar_block(b"h", typeflag=b"1", link=b"../../x") + END_OF_TAR
    yield "traversal/backslash", tar_file(b"..\\..\\x", b"x") + END_OF_TAR
    yield "traversal/drive", tar_file(b"C:\\x", b"x") + END_OF_TAR
    yield "traversal/control", tar_file(b"a\x01\x1b[2Kb\n", b"x") + END_OF_TAR
    yield "traversal/pax-path", pax_entry({"path": "../../pax"}) + tar_file(b"safe") + END_OF_TAR
    yield (
        "traversal/pax-global-size",
        pax_entry({"path": "g", "size": "9", "comment": "c"}, typeflag=b"g") + body + END_OF_TAR,
    )
    gnu_long = tar_block(b"././@LongLink", typeflag=b"L", size=11, magic=b"ustar  \0") + pad(
        b"../../long\0"
    )
    yield "traversal/gnu-long-name", gnu_long + tar_file(b"short") + END_OF_TAR
    yield "duplicate-paths", tar_file(b"a", b"1") + tar_file(b"a", b"2") + END_OF_TAR

    yield "empty", b""
    yield "only-end", END_OF_TAR
    yield "one-zero-block", bytes(512)
    yield "no-end-marker", body
    yield "single-zero-then-entry", bytes(512) + body + END_OF_TAR
    yield "trailing-garbage", body + END_OF_TAR + b"garbage" * 100
    yield "short-block", b"x" * 100
    yield "bad-checksum", tar_block(checksum=b"0000000\0")
    yield "bad-octal-size", tar_block(size=b"9" * 11)
    yield "bad-octal-mode", tar_block(mode=b"abc")
    yield "spaces-octal", tar_block(size=b"  1  \0") + pad(b"x") + END_OF_TAR
    yield "base256-size", tar_block(size=b"\x80" + bytes(10) + b"\x04") + pad(b"body") + END_OF_TAR
    yield "base256-negative-size", tar_block(size=b"\xff" * 12)
    yield "base256-huge", tar_block(size=b"\xff" + b"\x7f" * 11)
    yield "base256-negative-mtime", tar_block(mtime=b"\xff" * 12) + END_OF_TAR
    yield (
        "base256-out-of-date-range",
        tar_block(mtime=b"\x80" + bytes(5) + b"\x7f" * 6) + END_OF_TAR,
    )
    yield "base256-uid", tar_block(uid=b"\x80" + bytes(6) + b"\x10") + END_OF_TAR
    yield "bit-high-magic", tar_block(magic=b"bogus\0") + END_OF_TAR
    yield "v7-no-magic", tar_block(b"old", magic=b"") + END_OF_TAR
    star_long = bytearray(tar_block(b"name", prefix=b"p" * 140))
    star_long[508:512] = b"tar\0"
    star_long[148:156] = b" " * 8
    star_long[148:156] = f"{sum(star_long):06o}\0 ".encode()
    yield "star-prefix-past-131", bytes(star_long) + END_OF_TAR
    yield "gnu-magic-uname", tar_block(magic=b"ustar  \0", prefix=b"not-a-prefix") + END_OF_TAR
    yield "ustar-prefix", tar_block(b"name", prefix=b"pre/fix") + END_OF_TAR
    star = bytearray(tar_block(b"name", prefix=b"star"))
    star[508:512] = b"tar\0"
    star[148:156] = b" " * 8
    star[148:156] = f"{sum(star):06o}\0 ".encode()
    yield "star-trailer", bytes(star) + END_OF_TAR
    yield "signed-checksum", _signed_checksum() + END_OF_TAR
    for flag in b"01234567":
        kind = bytes((flag,))
        yield (
            f"typeflag/{kind.decode()}",
            tar_block(b"t", typeflag=kind, size=4, dev_major=7, dev_minor=9)
            + pad(b"body")
            + END_OF_TAR,
        )
    yield "typeflag/nul-file", tar_block(b"t", typeflag=b"\0", magic=b"") + END_OF_TAR
    yield "typeflag/nul-dir", tar_block(b"t/", typeflag=b"\0", magic=b"") + END_OF_TAR
    yield "typeflag/volume", tar_block(b"t", typeflag=b"V", size=4) + pad(b"body") + END_OF_TAR
    yield "typeflag/high", tar_block(b"t", typeflag=b"\xe9") + END_OF_TAR
    yield "typeflag/sparse", tar_block(b"t", typeflag=b"S") + END_OF_TAR
    yield (
        "typeflag/longlink",
        tar_block(b"t", typeflag=b"K", size=2) + pad(b"l\0") + tar_file(b"s") + END_OF_TAR,
    )
    yield "invalid-utf8-name", tar_file(b"\xff\xfe\x80name", b"") + END_OF_TAR
    yield "extended-too-large", tar_block(b"p", typeflag=b"x", size=1024 * 1024 + 1)
    yield "extended-at-end", pax_entry({"path": "x"}) + END_OF_TAR
    yield "extended-at-eof", pax_entry({"path": "x"})
    yield "long-at-end", tar_block(b"l", typeflag=b"L", size=2) + pad(b"x\0") + END_OF_TAR
    yield (
        "long-empty",
        tar_block(b"l", typeflag=b"L", size=1) + pad(b"\0") + tar_file(b"kept") + END_OF_TAR,
    )

    for name, data in {
        "no-space": b"10abcdefgh\n",
        "no-digits": b" a=b\n",
        "bad-digits": b"1x a=b\n",
        "zero-length": b"0 a=b\n",
        "too-short": b"4 a\n",
        "past-end": b"99 a=b\n",
        "no-newline": b"7 a=bcd",
        "no-equals": b"7 abcd\n",
        "empty-key": b"6 =bc\n",
        "long-length": b"00000000000000000000000000000006 a=b\n",
        "nul-in-key": b"8 a\0b=c\n",
        "nul-in-path": b"12 path=a\0b\n",
        "nul-in-comment": b"11 com=a\0b\n",
        "invalid-utf8": b"9 a=\xff\xfe\xfd\n",
        "bom-key": "12 \ufeffkey=v\n".encode(),
    }.items():
        yield f"pax/{name}", pax(data) + tar_file(b"f") + END_OF_TAR

    for key, values in {
        "size": (
            "4",
            "",
            "x",
            "-1",
            "1.5",
            "9007199254740991",
            "9007199254740992",
            "0" * 5000,
            "1" * 5000,
        ),
        "uid": ("12", "", "x", "9007199254740992"),
        "gid": ("13", "x"),
        "mtime": (
            "1.5",
            "-1.5",
            "1.0009",
            "-1.0009",
            "-0.0001",
            "0",
            "",
            "x",
            "1e3",
            "1.",
            ".5",
            "+1",
            "253402300799",
            "253402300800",
            "-62135596800",
            "-62135596801",
            "8640000000000",
            "8640000000001",
            "9" * 5000,
            "1" * 20,
        ),
        "path": ("p", ""),
        "linkpath": ("l", ""),
        "uname": ("u", ""),
        "gname": ("g", ""),
        "custom": ("value", ""),
        "GNU.sparse.major": ("1",),
        "GNU.sparse.name": ("x",),
    }.items():
        for i, value in enumerate(values):
            for prefix, flag in (("pax", b"x"), ("global", b"g")):
                yield (
                    f"{prefix}-field/{key}/{i}",
                    pax_entry({key: value}, typeflag=flag) + tar_file(b"f", b"body") + END_OF_TAR,
                )
    yield (
        "global/override-and-remove",
        pax_entry({"comment": "g", "uname": "gu"}, typeflag=b"g")
        + tar_file(b"a")
        + pax_entry({"comment": "own"})
        + tar_file(b"b")
        + pax_entry({"comment": ""}, typeflag=b"g")
        + tar_file(b"c")
        + END_OF_TAR,
    )


def _signed_checksum() -> bytes:
    block = bytearray(tar_block(b"\xc3\xa9"))
    block[148:156] = b" " * 8
    total = sum(b - 256 if b > 127 else b for b in block)
    block[148:156] = f"{total:06o}\0 ".encode()
    return bytes(block)


# Zip records


def le(value: int, length: int) -> bytes:
    return value.to_bytes(length, "little")


ZIP_END = le(0x06054B50, 4) + bytes(18)


def zip_local(
    name: bytes,
    *,
    flags: int = 0,
    method: int = 0,
    time: int = 0,
    date: int = 0x21,
    crc: int = 0,
    compressed: int = 0,
    size: int = 0,
    extra: bytes = b"",
    signature: int = 0x04034B50,
) -> bytes:
    return (
        le(signature, 4)
        + le(20, 2)
        + le(flags, 2)
        + le(method, 2)
        + le(time, 2)
        + le(date, 2)
        + le(crc, 4)
        + le(compressed, 4)
        + le(size, 4)
        + le(len(name), 2)
        + le(len(extra), 2)
        + name
        + extra
    )


def stored(name: bytes, body: bytes = b"", **fields: Any) -> bytes:
    options: dict[str, Any] = {
        "crc": zlib.crc32(body),
        "compressed": len(body),
        "size": len(body),
        **fields,
    }
    return zip_local(name, **options) + body


def deflate_stored(body: bytes) -> bytes:
    """Deflate data of one stored block."""
    return b"\x01" + le(len(body), 2) + le(len(body) ^ 0xFFFF, 2) + body


def deflated(name: bytes, body: bytes, data: bytes | None = None, **fields: Any) -> bytes:
    raw = deflate_stored(body) if data is None else data
    options: dict[str, Any] = {
        "method": 8,
        "crc": zlib.crc32(body),
        "compressed": len(raw),
        "size": len(body),
        **fields,
    }
    return zip_local(name, **options) + raw


def extra_field(field_id: int, data: bytes) -> bytes:
    return le(field_id, 2) + le(len(data), 2) + data


def zip_cases() -> Iterable[tuple[str, bytes]]:  # noqa: PLR0915
    for name in ("infozip", "infozip-stream", "7zip", "python-zip64"):
        data = (FIXTURES / "zip" / f"{name}.zip").read_bytes()
        yield f"fixture/{name}", data
        for at in range(0, len(data), max(1, len(data) // 40)):
            yield f"truncated/{name}/{at}", data[:at]
        for at in range(0, len(data), max(1, len(data) // 40)):
            corrupt = bytearray(data)
            corrupt[at] ^= 0x41
            yield f"corrupt/{name}/{at}", bytes(corrupt)

    yield "traversal/dotdot", stored(b"../../etc/passwd", b"x") + ZIP_END
    yield "traversal/absolute", stored(b"/etc/passwd", b"x") + ZIP_END
    yield "traversal/backslash", stored(b"..\\..\\x", b"x") + ZIP_END
    yield "traversal/drive", stored(b"C:\\x", b"x") + ZIP_END
    yield "traversal/control", stored(b"a\x01\x1b[2Kb\n", b"x") + ZIP_END
    yield "traversal/nul", stored(b"a.txt\0../b", b"x") + ZIP_END
    unicode_extra = extra_field(0x7075, b"\x01" + le(zlib.crc32(b"safe"), 4) + b"../../evil")
    yield "traversal/unicode-path", stored(b"safe", b"x", extra=unicode_extra) + ZIP_END
    yield "traversal/empty-name", stored(b"", b"x") + ZIP_END
    yield "duplicate-paths", stored(b"a", b"1") + stored(b"a", b"2") + ZIP_END
    yield "directory-with-body", stored(b"d/", b"body") + ZIP_END

    yield "empty", b""
    yield "only-end", ZIP_END
    yield "central-first", le(0x02014B50, 4) + bytes(100)
    yield "zip64-end-first", le(0x06064B50, 4) + bytes(100)
    yield "self-extracting", b"#!/bin/sh\nexit\n" + stored(b"a", b"x") + ZIP_END
    yield "short-signature", b"PK"
    yield "header-truncated", zip_local(b"name")[:20]
    yield "name-truncated", zip_local(b"name")[:32]
    yield "trailing-data", stored(b"a", b"x") + ZIP_END + b"trailing"
    yield "no-central-directory", stored(b"a", b"x")
    yield "garbage-after-entry", stored(b"a", b"x") + b"garbage!"
    yield "encrypted", stored(b"a", b"x", flags=1) + ZIP_END
    yield "strong-encrypted", stored(b"a", b"x", flags=0x40) + ZIP_END
    yield "method-bzip2", stored(b"a", b"x", method=12) + ZIP_END
    yield "stored-different-sizes", stored(b"a", b"x", size=2) + ZIP_END
    yield "stored-bad-crc", stored(b"a", b"x", crc=1) + ZIP_END
    yield "stored-descriptor-no-size", zip_local(b"a", flags=8) + b"x" + ZIP_END
    crc = zlib.crc32(b"x")
    yield (
        "stored-descriptor-with-size",
        zip_local(b"a", flags=8, compressed=1, size=1)
        + b"x"
        + le(0x08074B50, 4)
        + le(crc, 4)
        + le(1, 4)
        + le(1, 4)
        + ZIP_END,
    )

    yield "deflate/ok", deflated(b"a", b"hello") + ZIP_END
    yield "deflate/size-too-small", deflated(b"a", b"hello", size=2) + ZIP_END
    yield "deflate/size-too-large", deflated(b"a", b"hello", size=9) + ZIP_END
    yield "deflate/compressed-wrong", deflated(b"a", b"hello", compressed=3) + ZIP_END
    yield "deflate/bad-crc", deflated(b"a", b"hello", crc=1) + ZIP_END
    yield "deflate/truncated", deflated(b"a", b"hello")[:-2]
    for name, data in {
        "bad-block-type": b"\x07",
        "stored-lengths": b"\x01\x05\x00\x00\x00hello",
        "fixed-end-only": b"\x03\x00",
        "fixed-code-286": bytes((0xC3, 0x7F, 0x03, 0x00)),
        "fixed-distance-30": bytes((0x63, 0x00, 0xF8, 0x07, 0x00)),
        "too-far-back": bytes((0x63, 0x18, 0x05, 0x00)),
        "dynamic-too-many": b"\x05\xff\xff\x00",
        "dynamic-incomplete": b"\x05\x00\x00\x00\x00",
        "dynamic-over-subscribed": bytes((0x05, 0xE0, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF)),
        "dynamic-no-end-code": bytes((0xED, 0xC0, 0x01, 0x01, 0x00, 0x00, 0x00, 0x80, 0xA0, 0xFF)),
        "all-ones": b"\xff" * 64,
        "all-zeros": bytes(64),
    }.items():
        yield f"deflate/invalid/{name}", deflated(b"a", b"hello", data) + ZIP_END

    body = b"descriptor"
    raw = deflate_stored(body)
    crc = zlib.crc32(body)
    plain = le(crc, 4) + le(len(raw), 4) + le(len(body), 4)
    wide = le(crc, 4) + le(len(raw), 8) + le(len(body), 8)
    sig = le(0x08074B50, 4)
    head = zip_local(b"d", flags=8, method=8)
    yield "descriptor/plain", head + raw + plain + ZIP_END
    yield "descriptor/signed", head + raw + sig + plain + ZIP_END
    yield "descriptor/wide", head + raw + wide + ZIP_END
    yield "descriptor/signed-wide", head + raw + sig + wide + ZIP_END
    yield "descriptor/at-eof", head + raw + plain
    yield "descriptor/missing", head + raw
    yield "descriptor/partial", head + raw + plain[:5]
    yield "descriptor/bad-crc", head + raw + le(1, 4) + plain[4:] + ZIP_END
    yield "descriptor/bad-size", head + raw + le(crc, 4) + le(len(raw), 4) + le(1, 4) + ZIP_END
    yield "descriptor/next-entry", head + raw + plain + stored(b"n", b"x") + ZIP_END
    zip64 = extra_field(1, le(len(body), 8) + le(len(raw), 8))
    yield (
        "descriptor/zip64-extra",
        zip_local(b"d", flags=8, method=8, extra=zip64, compressed=0xFFFFFFFF, size=0xFFFFFFFF)
        + raw
        + sig
        + wide
        + ZIP_END,
    )
    yield (
        "zip64/local-sizes",
        zip_local(
            b"z",
            method=8,
            crc=crc,
            compressed=0xFFFFFFFF,
            size=0xFFFFFFFF,
            extra=zip64,
        )
        + raw
        + ZIP_END,
    )
    too_big = extra_field(1, le(2**53, 8) + le(2**53, 8))
    only_compressed = extra_field(1, le(1, 8))
    yield (
        "zip64/only-compressed-size-in-the-field",
        zip_local(
            b"a",
            crc=zlib.crc32(b"x"),
            compressed=0xFFFFFFFF,
            size=1,
            extra=only_compressed,
        )
        + b"x"
        + ZIP_END,
    )
    yield (
        "zip64/past-safe-integer",
        zip_local(b"z", compressed=0xFFFFFFFF, size=0xFFFFFFFF, extra=too_big) + ZIP_END,
    )
    yield (
        "zip64/short-field",
        zip_local(b"z", size=0xFFFFFFFF, compressed=0xFFFFFFFF, extra=extra_field(1, b""))
        + ZIP_END,
    )
    yield "extra/overflow", zip_local(b"a", extra=le(1, 2) + le(100, 2)) + ZIP_END
    yield "extra/short-tail", stored(b"a", extra=b"\x01") + ZIP_END

    def timed(value: int, date: int = 0x21) -> bytes:
        return stored(b"t", date=date, extra=extra_field(0x5455, b"\x01" + le(value, 4)))

    yield "time/extended", timed(1_700_000_000) + ZIP_END
    yield "time/negative", timed(0xFFFFFF00) + ZIP_END
    yield "time/after-2038", timed(0xFFFFFF00, (70 << 9) | 0x21) + ZIP_END
    yield "time/flag-unset", stored(b"t", extra=extra_field(0x5455, b"\x00" + le(5, 4))) + ZIP_END
    yield "time/short", stored(b"t", extra=extra_field(0x5455, b"\x01\x00")) + ZIP_END
    for time, date in (
        (0, 0),
        (0xFFFF, 0xFFFF),
        (0xBF7D, 0x0221),
        (0, 0x0020),
        (0, 0x0001),
        (0x001F, 0x21),
    ):
        yield f"time/dos/{time}/{date}", stored(b"t", time=time, date=date) + ZIP_END

    yield "name/cp437", stored(bytes(range(128, 160))) + ZIP_END
    yield "name/valid-utf8-unflagged", stored("é".encode()) + ZIP_END
    yield "name/flagged-invalid", stored(b"\xff\xfe", flags=0x800) + ZIP_END
    yield "name/bom", stored(b"\xef\xbb\xbfa") + ZIP_END
    for name, field in {
        "matching": b"\x01" + le(zlib.crc32(b"n"), 4) + "ü".encode(),
        "bad-crc": b"\x01" + le(0, 4) + b"x",
        "bad-version": b"\x02" + le(zlib.crc32(b"n"), 4) + b"x",
        "short": b"\x01\x00",
    }.items():
        yield f"name/unicode/{name}", stored(b"n", extra=extra_field(0x7075, field)) + ZIP_END
    first = extra_field(0x7075, b"\x01" + le(0, 4) + b"first")
    second = extra_field(0x7075, b"\x01" + le(zlib.crc32(b"n"), 4) + b"second")
    yield "name/unicode/second-ignored", stored(b"n", extra=first + second) + ZIP_END
    yield "name/unicode/flag-wins", stored(b"n", flags=0x800, extra=second) + ZIP_END

    bomb = stored(b"n") + zip_local(b"bomb", method=8, flags=8) + b"\x02"
    yield "stream-ends-in-deflate", bomb


def text(data: str | bytes) -> dict[str, str]:
    if isinstance(data, str):
        return {"text": data}
    return {"content": b64(data)}


SECONDS_2024 = 1_704_164_646_000

ENCODE_TAR: dict[str, list[dict[str, Any]]] = {
    "basic": [
        {"kind": "directory", "path": "dir"},
        {"kind": "file", "path": "dir/a.txt", "text": "hello\n"},
        {"kind": "file", "path": "bytes", "content": b64(bytes(range(256)))},
        {"kind": "stream", "path": "s", "size": 3, "chunks": [b64(b"ab"), b64(b"c")]},
        {"kind": "symlink", "path": "l", "target": "dir/a.txt"},
        {"kind": "hardlink", "path": "h", "target": "dir/a.txt"},
    ],
    "large-body": [{"kind": "file", "path": "big", "content": b64(bytes(70_000))}],
    **{
        f"pax-record-length-{length}": [
            {"kind": "file", "path": "p", "text": "", "pax": {"k": "v" * (length - 4)}},
        ]
        for length in (4, 5, 6, 7, 8, 9, 10, 93, 94, 95, 96, 97, 98, 99, 100, 993, 994, 995, 996)
    },
    "large-stream": [
        {
            "kind": "stream",
            "path": "big",
            "size": 90_000,
            "chunks": [b64(bytes(70_000)), b64(bytes(20_000))],
        }
    ],
    "fields": [
        {
            "kind": "file",
            "path": "f",
            "text": "",
            "mode": 0o755,
            "uid": 7,
            "gid": 8,
            "uname": "u",
            "gname": "g",
            "mtime": SECONDS_2024,
        },
        {"kind": "file", "path": "file-types", "text": "", "mode": 0o100644},
    ],
    "long-paths": [
        {"kind": "file", "path": "a" * 100, "text": ""},
        {"kind": "file", "path": "a" * 101, "text": ""},
        {"kind": "file", "path": f"{'p' * 155}/{'n' * 100}", "text": ""},
        {"kind": "file", "path": f"{'p' * 156}/{'n' * 100}", "text": ""},
        {"kind": "directory", "path": f"{'p' * 100}/{'d' * 99}"},
        {"kind": "directory", "path": "d" * 200},
        {"kind": "file", "path": "x/" + "y" * 101, "text": ""},
        {"kind": "file", "path": "/" + "y" * 100, "text": ""},
        {"kind": "file", "path": "é" * 60, "text": ""},
    ],
    "overflow": [
        {"kind": "file", "path": "u", "text": "", "uid": 2097152, "gid": 2097152},
        {"kind": "file", "path": "u", "text": "", "uid": 2097151, "gid": 2097151},
        {"kind": "file", "path": "n", "text": "", "uname": "n" * 33, "gname": "ñ"},
        {"kind": "symlink", "path": "l", "target": "t" * 101},
        {"kind": "file", "path": "t", "text": "", "mtime": -1000},
        {"kind": "file", "path": "t", "text": "", "mtime": -500},
        {"kind": "file", "path": "t", "text": "", "mtime": 1500},
        {"kind": "file", "path": "t", "text": "", "mtime": 8_589_934_592_000},
        {"kind": "file", "path": "t", "text": "", "mtime": 8_589_934_591_000},
    ],
    "pax": [
        {
            "kind": "file",
            "path": "p",
            "text": "",
            "pax": {"b": "2", "a": "é", "\ud83d\ude00": "x", "\uffff": "y"},
        },
        {"kind": "file", "path": "p", "text": "", "pax": {"long": "v" * 1000}},
    ],
    "traversal": [
        {"kind": "file", "path": "../../etc/passwd", "text": "x"},
        {"kind": "file", "path": "/etc/passwd", "text": "x"},
        {"kind": "file", "path": "..\\x", "text": "x"},
        {"kind": "symlink", "path": "out", "target": "/etc"},
        {"kind": "symlink", "path": "../out", "target": "../../etc"},
        {"kind": "hardlink", "path": "out", "target": "../../etc/passwd"},
        {"kind": "file", "path": "a\nb", "text": ""},
    ],
    "other-types": [
        {
            "kind": "raw",
            "path": "c",
            "type": "CharDevice",
            "typeflag": "3",
            "devMajor": 1,
            "devMinor": 3,
        },
        {"kind": "raw", "path": "b", "type": "BlockDevice", "typeflag": "4", "devMajor": 2097151},
        {"kind": "raw", "path": "f", "type": "Fifo", "typeflag": "6"},
        {"kind": "raw", "path": "o", "type": "Other", "typeflag": "V"},
    ],
    "empty": [],
}
_INVALID_TAR: dict[str, dict[str, Any]] = {
    "empty-path": {"kind": "file", "path": "", "text": ""},
    "empty-directory": {"kind": "directory", "path": ""},
    "nul-path": {"kind": "file", "path": "a\0b", "text": ""},
    "file-trailing-slash": {"kind": "file", "path": "a/", "text": ""},
    "negative-mode": {"kind": "file", "path": "a", "text": "", "mode": -1},
    "negative-uid": {"kind": "file", "path": "a", "text": "", "uid": -1},
    "negative-gid": {"kind": "file", "path": "a", "text": "", "gid": -1},
    "huge-uid": {"kind": "file", "path": "a", "text": "", "uid": 2**53},
    "invalid-mtime": {"kind": "file", "path": "a", "text": "", "mtime": "invalid"},
    "nul-uname": {"kind": "file", "path": "a", "text": "", "uname": "a\0"},
    "nul-gname": {"kind": "file", "path": "a", "text": "", "gname": "a\0"},
    "nul-target": {"kind": "symlink", "path": "a", "target": "a\0"},
    "body-past-size-in-a-later-chunk": {
        "kind": "stream",
        "path": "a",
        "size": 3,
        "chunks": [b64(b"abcd"), b64(b"ef")],
    },
    "pax-path": {"kind": "file", "path": "a", "text": "", "pax": {"path": "b"}},
    "pax-size": {"kind": "file", "path": "a", "text": "", "pax": {"size": "1"}},
    "pax-mtime": {"kind": "file", "path": "a", "text": "", "pax": {"mtime": "1"}},
    "pax-sparse": {"kind": "file", "path": "a", "text": "", "pax": {"GNU.sparse.major": "1"}},
    "pax-empty-key": {"kind": "file", "path": "a", "text": "", "pax": {"": "1"}},
    "pax-equals": {"kind": "file", "path": "a", "text": "", "pax": {"a=b": "1"}},
    "pax-nul-key": {"kind": "file", "path": "a", "text": "", "pax": {"a\0": "1"}},
    "pax-nul-value": {"kind": "file", "path": "a", "text": "", "pax": {"a": "\0"}},
    "dev-too-big": {
        "kind": "raw",
        "path": "c",
        "type": "CharDevice",
        "typeflag": "3",
        "devMajor": 2097152,
    },
    "dev-negative": {
        "kind": "raw",
        "path": "c",
        "type": "CharDevice",
        "typeflag": "3",
        "devMinor": -1,
    },
    "header-only-size": {"kind": "raw", "path": "c", "type": "Fifo", "typeflag": "6", "size": 1},
    "typeflag-x": {"kind": "raw", "path": "c", "type": "Other", "typeflag": "x"},
    "typeflag-empty": {"kind": "raw", "path": "c", "type": "Other", "typeflag": ""},
    "typeflag-long": {"kind": "raw", "path": "c", "type": "Other", "typeflag": "ab"},
    "typeflag-high": {"kind": "raw", "path": "c", "type": "Other", "typeflag": "é"},
    "stream-short": {"kind": "stream", "path": "s", "size": 5, "chunks": [b64(b"abc")]},
    "stream-long": {"kind": "stream", "path": "s", "size": 2, "chunks": [b64(b"abc")]},
    "stream-negative": {"kind": "stream", "path": "s", "size": -1, "chunks": []},
}
for name, entry in _INVALID_TAR.items():
    ENCODE_TAR[f"invalid/{name}"] = [entry]

STORE: dict[str, str] = {"method": "Store"}
ENCODE_ZIP: dict[str, list[dict[str, Any]]] = {
    "basic": [
        {"kind": "directory", "path": "dir"},
        {"kind": "file", "path": "dir/a.txt", "text": "hello\n", **STORE},
        {"kind": "file", "path": "bytes", "content": b64(bytes(range(256))), **STORE},
        {"kind": "stream", "path": "s", "size": 3, "chunks": [b64(b"ab"), b64(b"c")], **STORE},
        {"kind": "stream", "path": "empty", "size": 0, "chunks": [], **STORE},
        {"kind": "file", "path": "ünï/文", "text": "u", **STORE},
    ],
    "large": [
        {"kind": "file", "path": "big", "content": b64(bytes(70_000)), **STORE},
        {
            "kind": "stream",
            "path": "s",
            "size": 90_000,
            "chunks": [b64(bytes(70_000)), b64(bytes(20_000))],
            **STORE,
        },
    ],
    "times": [
        {"kind": "file", "path": str(ms), "text": "", "mtime": ms, **STORE}
        for ms in (
            0,
            5000,
            -1000,
            315532800000,
            1704164646789,
            2147483647000,
            2147483648000,
            4354819200000,
            7000000000000,
        )
    ],
    "modes": [
        {"kind": "file", "path": "x", "text": "", "mode": 0o755, **STORE},
        {"kind": "file", "path": "s", "text": "", "mode": 0o7777, **STORE},
        {"kind": "file", "path": "z", "text": "", "mode": 0, **STORE},
        {"kind": "directory", "path": "d", "mode": 0o700},
    ],
    "traversal": [
        {"kind": "file", "path": "../../etc/passwd", "text": "x", **STORE},
        {"kind": "file", "path": "a/../../b", "text": "x", **STORE},
        {"kind": "directory", "path": "../d"},
        {"kind": "file", "path": "a\nb", "text": "", **STORE},
        {"kind": "file", "path": "1:x", "text": "", **STORE},
        {"kind": "file", "path": "dup", "text": "1", **STORE},
        {"kind": "file", "path": "dup", "text": "2", **STORE},
    ],
    "empty": [],
}
_INVALID_ZIP: dict[str, dict[str, Any]] = {
    "empty-path": {"kind": "file", "path": "", "text": ""},
    "empty-directory": {"kind": "directory", "path": ""},
    "absolute": {"kind": "file", "path": "/a", "text": ""},
    "backslash": {"kind": "file", "path": "a\\b", "text": ""},
    "drive": {"kind": "file", "path": "C:a", "text": ""},
    "nul": {"kind": "file", "path": "a\0", "text": ""},
    "file-trailing-slash": {"kind": "file", "path": "a/", "text": ""},
    "long-path": {"kind": "file", "path": "a" * 65536, "text": ""},
    "mode-negative": {"kind": "file", "path": "a", "text": "", "mode": -1},
    "mode-high": {"kind": "file", "path": "a", "text": "", "mode": 0o10000},
    "invalid-mtime": {"kind": "file", "path": "a", "text": "", "mtime": "invalid"},
    "stream-short": {"kind": "stream", "path": "s", "size": 5, "chunks": [b64(b"abc")], **STORE},
    "stream-long": {"kind": "stream", "path": "s", "size": 2, "chunks": [b64(b"abc")], **STORE},
    "stream-no-size": {"kind": "stream", "path": "s", "chunks": [b64(b"abc")], **STORE},
    "deflate-short": {"kind": "stream", "path": "s", "size": 5, "chunks": [b64(b"abc")]},
    "deflate-long": {"kind": "stream", "path": "s", "size": 2, "chunks": [b64(b"abc")]},
    "deflate-negative": {"kind": "stream", "path": "s", "size": -1, "chunks": []},
    "deflate-huge": {"kind": "stream", "path": "s", "size": 2**53, "chunks": []},
}
for name, entry in _INVALID_ZIP.items():
    ENCODE_ZIP[f"invalid/{name}"] = [entry]

XML_DOCUMENTS: dict[str, str] = {
    "plain": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        "<a x=\"1\" y='2'>t<b/>&lt;&#65;&#x42;<![CDATA[c]]><!--k--><?pi d?></a>"
    ),
    "doctype": '<!DOCTYPE a PUBLIC "p" "s"><a/>',
    "doctype-system": '<!DOCTYPE a SYSTEM "s"><a/>',
    "doctype-entity": '<!DOCTYPE a [<!ENTITY e "x">]><a>&e;</a>',
    "doctype-external": '<!DOCTYPE a SYSTEM "file:///etc/passwd" [<!ENTITY e SYSTEM "file:///etc/passwd">]><a>&e;</a>',
    "billion-laughs": '<!DOCTYPE l [<!ENTITY a "x"><!ENTITY b "&a;&a;">]><l>&b;</l>',
    "undefined-entity": "<a>&e;</a>",
    "bad-reference": "<a>&#xFFFFFFFF;&#0;</a>",
    "long-reference": f"<a>&#{'9' * 5000};</a>",
    "unclosed": "<a><b></a>",
    "extra-root": "<a/><b/>",
    "text-outside": "x<a/>",
    "text-after": "<a/>x",
    "empty": "",
    "only-space": "  \n",
    "duplicate-attribute": '<a x="1" x="2"/>',
    "lt-in-attribute": '<a x="<"/>',
    "bad-name": "<1a/>",
    "cdata-end": "<a>]]></a>",
    "comment-dashes": "<a><!-- -- --></a>",
    "pi-xml": "<a><?xml version='1.0'?></a>",
    "declaration-late": " <?xml version='1.0'?><a/>",
    "bad-declaration": "<?xml version='2'?><a/>",
    "encoding-latin1": "<?xml version='1.0' encoding='ISO-8859-1'?><a/>",
    "line-endings": "<a>\r\n\r</a>",
    "lines": "<a>\n\n  <b>\n</c></a>",
    "surrogates": "<a>\U0001f600</a>",
    "control": "<a>\x01</a>",
    "ffff": "<a>\uffff</a>",
    "unterminated-comment": "<a><!-- ",
    "unterminated-attribute": '<a x="',
    "unterminated-tag": "<a",
    "bom": "\ufeff<a/>",
    "namespaces": '<x:a xmlns:x="u" x:y="1"><x:b/></x:a>',
    "whitespace-attribute": '<a x=" \t\n\r "/>',
}


def _start(name: str, **attributes: str) -> dict[str, Any]:
    return {"_tag": "StartElement", "name": name, "attributes": attributes}


def _end(name: str) -> dict[str, Any]:
    return {"_tag": "EndElement", "name": name}


def _text(text: str) -> dict[str, Any]:
    return {"_tag": "Text", "text": text}


_RECORD = [_start("feed"), _start("item", id="1"), _text("a"), _start("b"), _end("b"), _text("c")]
XML_ELEMENTS: dict[str, tuple[list[str], list[dict[str, Any]], dict[str, int]]] = {
    "records": (["f"], [*_RECORD, _end("item"), _end("feed")], {}),
    "path": (["feed", "item"], [*_RECORD, _end("item"), _end("feed")], {}),
    "wildcard": (["*", "*"], [*_RECORD, _end("item"), _end("feed")], {}),
    "limit": (["feed", "item"], [*_RECORD, _end("item"), _end("feed")], {"maxElementSize": 3}),
    "text-merged": (
        ["a"],
        [
            _start("a"),
            _text("x"),
            _text("y"),
            {"_tag": "Comment", "text": "k"},
            _text("z"),
            _end("a"),
        ],
        {},
    ),
    "unclosed": (["a"], [_start("a"), _text("x")], {}),
}
XML_ENCODE: dict[str, list[dict[str, Any]]] = {
    "plain": [
        {"_tag": "Declaration", "version": "1.0", "encoding": "UTF-8", "standalone": True},
        {"_tag": "Doctype", "name": "a", "publicId": "p", "systemId": "s"},
        {"_tag": "Comment", "text": "k"},
        _start("a", x='1<&>"', y="\t\n\r"),
        _text("<&>]]>\r"),
        {"_tag": "ProcessingInstruction", "target": "pi", "data": "d"},
        _start("b"),
        _end("b"),
        _end("a"),
    ],
    "empty": [],
    "unclosed": [_start("a")],
    "mismatched": [_start("a"), _end("b")],
    "extra-end": [_start("a"), _end("a"), _end("a")],
    "two-roots": [_start("a"), _end("a"), _start("b"), _end("b")],
    "text-outside": [_text("x"), _start("a"), _end("a")],
    "space-outside": [_text(" "), _start("a"), _end("a")],
    "bad-name": [_start("1a")],
    "bad-attribute": [_start("a", **{"1": "x"})],
    "control-text": [_start("a"), _text("\x01")],
    "late-declaration": [_start("a"), {"_tag": "Declaration", "version": "1.0"}],
    "comment-dashes": [{"_tag": "Comment", "text": "--"}],
    "pi-xml": [{"_tag": "ProcessingInstruction", "target": "xml", "data": ""}],
    "pi-end": [{"_tag": "ProcessingInstruction", "target": "a", "data": "?>"}],
    "doctype-quotes": [{"_tag": "Doctype", "name": "a", "systemId": "'\""}],
    "doctype-public-only": [{"_tag": "Doctype", "name": "a", "publicId": "p"}],
    "doctype-late": [_start("a"), {"_tag": "Doctype", "name": "a"}],
}


def corpus() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for op, source in (("tar.decode", tar_cases()), ("zip.decode", zip_cases())):
        for name, data in source:
            cases.append({"id": f"{op}/{name}", "op": op, "chunks": split(data, max(1, len(data)))})
            if len(data) < 4096:
                cases.append({"id": f"{op}/{name}#7", "op": op, "chunks": split(data, 7)})
    for op, entries in (("tar.encode", ENCODE_TAR), ("zip.encode", ENCODE_ZIP)):
        for name, items in entries.items():
            cases.append({"id": f"{op}/{name}", "op": op, "entries": items})
    for name, document in XML_DOCUMENTS.items():
        data = document.encode("utf-8", "surrogatepass")
        cases.append({"id": f"xml.decode/{name}", "op": "xml.decode", "chunks": [b64(data)]})
        cases.append({"id": f"xml.decode/{name}#1", "op": "xml.decode", "chunks": split(data, 1)})
        cases.append(
            {"id": f"xml.decodeString/{name}", "op": "xml.decodeString", "strings": [document]}
        )
    cases.append(
        {"id": "xml.decode/invalid-utf8", "op": "xml.decode", "chunks": [b64(b"<a>\xff</a>")]}
    )
    cases.append(
        {"id": "xml.decode/utf16-bom", "op": "xml.decode", "chunks": [b64(b"\xff\xfe<\0a\0/\0>\0")]}
    )
    cases.append(
        {
            "id": "xml.decode/max-depth",
            "op": "xml.decode",
            "chunks": [b64(b"<a><b><c/></b></a>")],
            "options": {"maxDepth": 2},
        }
    )
    cases.append(
        {
            "id": "xml.decode/max-token",
            "op": "xml.decode",
            "chunks": [b64(b"<a>" + b"x" * 100 + b"</a>")],
            "options": {"maxTokenSize": 16},
        }
    )
    for name, (path, events, options) in XML_ELEMENTS.items():
        cases.append(
            {
                "id": f"xml.elements/{name}",
                "op": "xml.elements",
                "path": path,
                "events": events,
                "options": options,
            }
        )
    for name, events in XML_ENCODE.items():
        cases.append({"id": f"xml.encodeString/{name}", "op": "xml.encodeString", "events": events})
    return cases


if __name__ == "__main__":
    print(json.dumps(corpus()))
