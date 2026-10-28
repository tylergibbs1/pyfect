"""Ports of platform-node's ``MultipartParser.test.ts`` (Effect's
``MultipartParser``).

Each test's docstring is the Effect test title. The case table is
``fixtures/multipart_parser_cases.json``, dumped from the Effect test (an
``isFile`` predicate becomes the part name it tests; the 10 MiB file of
"Fields and large file" is written as ``{"repeat", "count"}`` pieces).

Omitted, with the reason:

- ``node api`` and ``node async-iterable api`` (``$name`` for every case,
  ``exposes missing filenames as undefined``, ``stops sending file chunks
  after an error``): ``NodeMultipartParser`` wraps the parser in Node
  streams, which have no Python counterpart; the two named cases are
  ported against the parser itself.
- ``smoke test`` writes 100 random files of up to 100 MiB; the port writes
  20 of up to 1 MiB with the same generator, as pure Python parsing is
  slower than Node's.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pyfect.http import multipart_parser as mp

_CASES: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "fixtures" / "multipart_parser_cases.json").read_text()
)


def _source(piece: str | dict[str, Any]) -> bytes:
    if isinstance(piece, str):
        return piece.encode()
    return (piece["repeat"] * piece["count"]).encode()


def _is_file(spec: str) -> Callable[[mp.PartInfo], bool]:
    if spec.startswith("not "):
        name = spec.removeprefix("not ")
        return lambda info: info.name != name
    return lambda info: info.name == spec


def _run(case: dict[str, Any]) -> tuple[list[list[object]], list[str]]:
    parts: list[list[object]] = []
    errors: list[str] = []
    config = case.get("config", {})
    options: dict[str, Any] = {}
    if "maxParts" in config:
        options["max_parts"] = config["maxParts"]
    if "maxPartSize" in config:
        options["max_part_size"] = config["maxPartSize"]
    if "maxFieldSize" in config:
        options["max_field_size"] = config["maxFieldSize"]
    if "isFile" in config:
        options["is_file"] = _is_file(config["isFile"])

    def on_file(info: mp.PartInfo) -> mp.OnChunk:
        size = 0

        def on_chunk(chunk: bytes | None) -> None:
            nonlocal size
            if chunk is not None:
                size += len(chunk)
            else:
                parts.append(["file", info.name, size, info.filename, info.content_type])

        return on_chunk

    def on_field(info: mp.PartInfo, value: bytes) -> None:
        parts.append(["field", info.name, mp.decode_field(info, value), info.content_type])

    parser = mp.make(
        headers={"content-type": "multipart/form-data; boundary=" + case["boundary"]},
        on_file=on_file,
        on_field=on_field,
        on_error=lambda error: errors.append(error.tag),
        on_done=lambda: None,
        **options,
    )
    for piece in case["source"]:
        parser.write(_source(piece))
    parser.end()
    return parts, errors


@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_multipart(case: dict[str, Any]) -> None:
    """$name"""
    parts, errors = _run(case)
    assert parts == case["expected"]
    if "errors" in case:
        assert errors == case["errors"]


def _ignore_chunk(_chunk: bytes | None) -> None:
    return None


def test_exposes_missing_filenames_as_none() -> None:
    """exposes missing filenames as undefined"""
    files: list[str | None] = []
    parser = mp.make(
        headers={"content-type": "multipart/form-data; boundary=boundary"},
        on_file=lambda info: (files.append(info.filename), _ignore_chunk)[1],
        on_field=lambda _info, _value: None,
        on_error=lambda _error: None,
        on_done=lambda: None,
    )
    parser.write(
        b'--boundary\r\nContent-Disposition: form-data; name="file"\r\n'
        b"Content-Type: application/octet-stream\r\n\r\ncontent\r\n--boundary--"
    )
    parser.end()
    assert files == [None]


def test_stops_sending_file_chunks_after_an_error() -> None:
    """stops sending file chunks after an error"""
    chunks: list[bytes | None] = []
    parser = mp.make(
        headers={"content-type": "multipart/form-data; boundary=boundary"},
        on_file=lambda _info: chunks.append,
        on_field=lambda _info, _value: None,
        on_error=lambda _error: None,
        on_done=lambda: None,
        max_part_size=100,
    )
    parser.write(
        b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="a.txt"\r\n\r\nA'
    )
    parser.write(b"B" * 128)
    assert chunks == [b"A", None]


def test_smoke() -> None:
    """smoke test"""
    boundary = "------WebKitFormBoundaryTB2MiQ36fnSJlrhY--"
    seed = 0x9E3779B9

    def random() -> float:
        nonlocal seed
        seed ^= (seed << 13) & 0xFFFFFFFF
        seed ^= seed >> 17
        seed ^= (seed << 5) & 0xFFFFFFFF
        return seed / 0x1_0000_0000

    for i in range(20):
        size = round(random() * 1024 * 1024)
        success = False

        def done() -> None:
            nonlocal success
            success = True

        parser = mp.make(
            headers={"content-type": f"multipart/form-data; boundary={boundary}"},
            on_done=done,
            on_file=lambda _info: lambda _chunk: None,
            on_field=lambda _info, _value: None,
            on_error=lambda _error: None,
        )
        buffer = (
            f"--{boundary}\r\n".encode()
            + b'Content-Disposition: form-data; name="file"; filename="blob"\r\n'
            + b"Content-Type: application/octet-stream\r\n\r\n"
            + bytes([i]) * size
            + f"\r\n--{boundary}--".encode()
        )
        cursor = 0
        while cursor < len(buffer):
            chunk_size = max(1, min(round(random() * 128 * 1024), len(buffer) - cursor))
            parser.write(buffer[cursor : cursor + chunk_size])
            cursor += chunk_size
        parser.end()
        assert success
