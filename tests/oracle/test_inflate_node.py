"""What Effect's inflater (``internal/inflate.ts``) and ``Zip.decode`` did under Node on
the mutated deflate streams of ``_inflate_corpus.py`` (``inflate_oracle.ts`` says how to
record them). Not Effect test titles: found by comparing with Effect.

``zip._inflate_port`` must match Effect's inflater exactly: output chunks, the input it
pulls, its error message and the byte it fails at. ``Zip.decode``, which inflates with
``zlib`` and replays through the port, must match Effect's errors exactly, and its body
chunks and input pulls too, but for one case: a code length code without codes, which
``zlib`` takes and rejects up to 40 bytes later (``docs/PARITY.md`` section 4)."""
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import stream
from pyfect.encoding import zip as Zip
from pyfect.encoding._archive import NEED_INPUT, ByteQueue
from pyfect.encoding.zip._inflate_port import InflateError, Inflater
from pyfect.result import Ok

from ._inflate_corpus import zip_archive

CASES: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "fixtures" / "inflate_oracle.json").read_text()
)

ZLIB_LATER = "invalid code length code"
"""Effect's error where ``zlib`` reads more input before it fails."""


def digest(data: bytes) -> str:
    return f"{len(data)}:{hashlib.sha256(data).hexdigest()[:12]}"


def sequence(hashes: list[str]) -> str:
    return f"{len(hashes)}:{hashlib.sha256(','.join(hashes).encode()).hexdigest()[:12]}"


def inflate(data: bytes, splits: list[int]) -> dict[str, Any]:
    """The port, given one split per ``NEED_INPUT``."""
    queue = ByteQueue()
    inflater = Inflater(queue)
    at = pushes = 0
    outs: list[str] = []
    while True:
        try:
            out = inflater.pull()
        except InflateError as error:
            return {"outs": sequence(outs), "pushes": pushes, "error": str(error)}
        if out is NEED_INPUT:
            if pushes == len(splits):
                return {"outs": sequence(outs), "pushes": pushes, "end": "truncated"}
            queue.push(data[at : at + splits[pushes]])
            at += splits[pushes]
            pushes += 1
            continue
        if out is None:
            left = queue.length + len(data) - at
            return {"outs": sequence(outs), "pushes": pushes, "end": "done", "left": left}
        outs.append(digest(out))


def decode(data: bytes, splits: list[int]) -> dict[str, Any]:
    chunks: list[bytes] = []
    at = 0
    for size in splits:
        chunks.append(data[at : at + size])
        at += size
    items: list[dict[str, Any]] = []
    pulls = 0

    def pulled(_: bytes) -> fx.Effect[None]:
        nonlocal pulls
        pulls += 1
        return fx.void

    def read(entry: Any) -> Any:
        record: dict[str, Any] = {"path": entry.header.path, "chunks": []}
        items.append(record)

        def keep(chunk: bytes) -> fx.Effect[None]:
            return fx.sync(lambda: record["chunks"].append(digest(chunk)))

        return entry.body.run_for_each(keep)

    effect = (
        stream.from_iterable(chunks, chunk_size=1)
        .tap(pulled)
        .pipe_through_channel(Zip.decode())
        .map_effect(read)
        .run_drain()
    )
    result = fx.run_blocking_exit(effect)
    for item in items:
        item["chunks"] = sequence(item["chunks"])
    error = None
    if isinstance(result, fx.Failure):
        found = result.cause.find_error()
        assert isinstance(found, Ok)
        error = {"kind": found.value.kind, "message": found.value.message}
    return {"items": items, "error": error, "pulls": pulls}


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_port_matches_effect(case: dict[str, Any]) -> None:
    data = base64.b64decode(case["data"])
    assert inflate(data, case["splits"]) == case["raw"]
    if case["bytewise"] is not None:
        assert inflate(data, [1] * len(data)) == case["bytewise"]


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_decode_matches_effect(case: dict[str, Any]) -> None:
    data = base64.b64decode(case["data"])[: case["compressed"]]
    result = decode(zip_archive(data, case["crc"], case["size"]), case["zipSplits"])
    expected = case["zip"]
    if (expected["error"] or {}).get("message") == ZLIB_LATER:
        assert result["error"] == expected["error"]
    else:
        assert result == expected


def test_zlib_reads_on_past_a_code_length_code_without_codes() -> None:
    """The one difference: pulled a byte at a time, Effect fails on the 4th byte of the
    entry's data, and this port after 36 bytes, past the data to the end of the archive,
    with Effect's error."""
    case = next(case for case in CASES if case["id"] == "message/4")
    assert case["zip"]["error"] == {"kind": "InvalidData", "message": ZLIB_LATER}
    data = base64.b64decode(case["data"])
    archive = zip_archive(data, case["crc"], case["size"])
    one_by_one = [31] + [1] * (len(archive) - 31)
    result = decode(archive, one_by_one)
    assert result["error"] == case["zip"]["error"]
    assert (case["bytewise"]["pushes"], result["pulls"] - 1) == (4, 36)
