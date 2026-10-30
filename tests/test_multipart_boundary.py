"""A multipart boundary is 1 to 70 characters (RFC 2046 §5.1.1): a longer
one would make every small body write scan the whole boundary."""

from __future__ import annotations

import time

import pytest

from pyfect.http import multipart_parser as mp


def _parse(boundary: str, body: list[bytes]) -> tuple[list[str], list[bytes]]:
    errors: list[str] = []
    fields: list[bytes] = []
    parser = mp.make(
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
        on_file=lambda _info: lambda _chunk: None,
        on_field=lambda _info, value: fields.append(value),
        on_error=lambda error: errors.append(error.tag),
        on_done=lambda: None,
    )
    for chunk in body:
        parser.write(chunk)
    parser.end()
    return errors, fields


def _form(boundary: str) -> list[bytes]:
    return [
        f"--{boundary}\r\ncontent-disposition: form-data; name=a\r\n\r\nvalue\r\n"
        f"--{boundary}--\r\n".encode()
    ]


@pytest.mark.parametrize("boundary", ["b", "a" * 70, "'()+_,-./:=? x"])
def test_a_boundary_of_up_to_70_characters_is_read(boundary: str) -> None:
    quoted = f'"{boundary}"'
    assert _parse(quoted, _form(boundary)) == ([], [b"value"])


@pytest.mark.parametrize("boundary", ["a" * 71, "a" * 16000, '"a "', '"a@b"'])
def test_a_boundary_outside_rfc_2046_is_invalid(boundary: str) -> None:
    assert _parse(boundary, [])[0] == ["InvalidBoundary"]


def test_small_writes_with_the_longest_boundary_stay_cheap() -> None:
    """2-byte writes of the boundary's own byte: each scans at most the
    boundary, so 20k of them take well under a second."""
    errors: list[str] = []
    parser = mp.make(
        headers={"content-type": "multipart/form-data; boundary=" + "a" * 70},
        on_file=lambda _info: lambda _chunk: None,
        on_field=lambda _info, _value: None,
        on_error=lambda error: errors.append(error.tag),
        on_done=lambda: None,
    )
    started = time.monotonic()
    for _ in range(20_000):
        parser.write(b"aa")
    assert time.monotonic() - started < 1.0
    assert errors == []
