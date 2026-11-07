"""Client bodies Effect's multipart parser mishandles (PARITY section 4):
a part whose headers never end fails with a typed parse error (Effect
dies, or emits the previous field twice), and an epilogue after the final
boundary is ignored however it is written (Effect fails when it comes in
a later write)."""

from __future__ import annotations

from typing import Any

import pyfect as fx
from pyfect import stream
from pyfect.exit import Exit, Failure, Success
from pyfect.http import multipart
from pyfect.http import multipart_parser as mp

_HEADERS = {"content-type": "multipart/form-data; boundary=b"}
_FIELD_A = b'--b\r\nContent-Disposition: form-data; name="a"\r\n\r\nv\r\n'


def _parse(*pieces: bytes) -> tuple[list[str], Exit[Any, Any]]:
    seen: list[str] = []

    def keep(part: multipart.Part) -> None:
        assert isinstance(part, multipart.Field)
        seen.append(f"{part.key}={part.value}")

    parts = stream.from_iterable(pieces).pipe_through_channel(multipart.make_channel(_HEADERS))
    exit = fx.run_blocking_exit(parts.run_for_each(lambda part: fx.sync(lambda: keep(part))))
    return seen, exit


def _parse_error(exit: Exit[Any, Any]) -> str:
    assert isinstance(exit, Failure)
    error = exit.cause.squash()
    assert isinstance(error, multipart.MultipartError)
    return error.reason.tag


def test_a_first_part_whose_headers_never_end_is_a_parse_error() -> None:
    seen, exit = _parse(b'--b\r\nContent-Disposition: form-data; name="a"\r\n--b--')
    assert seen == []
    assert _parse_error(exit) == "Parse"


def test_a_later_part_whose_headers_never_end_is_a_parse_error() -> None:
    seen, exit = _parse(_FIELD_A + b'--b\r\nContent-Disposition: form-data; name="c"\r\n--b--')
    # The earlier field once, never again with the broken part's empty value.
    assert seen == ["a=v"]
    assert _parse_error(exit) == "Parse"


def test_a_part_without_headers_is_a_parse_error() -> None:
    seen, exit = _parse(b"--b\r\n\r\n--b--")
    assert seen == []
    assert _parse_error(exit) == "Parse"


def test_an_epilogue_is_ignored_in_the_same_write_or_a_later_one() -> None:
    epilogue = b"\r\nthis is the epilogue\r\n"
    assert _parse(_FIELD_A + b"--b--" + epilogue) == (["a=v"], Success(None))
    assert _parse(_FIELD_A + b"--b--", epilogue) == (["a=v"], Success(None))
    assert _parse(_FIELD_A + b"--b--", b"\r\n", b"--b\r\nnot: a part\r\n") == (
        ["a=v"],
        Success(None),
    )


def test_the_parser_reports_nothing_after_it_is_done() -> None:
    events: list[str] = []
    parser = mp.make(
        headers=_HEADERS,
        on_file=lambda _info: lambda _chunk: None,
        on_field=lambda info, value: events.append(f"field {info.name}={value.decode()}"),
        on_error=lambda error: events.append(f"error {error.tag}"),
        on_done=lambda: events.append("done"),
        max_total_size=len(_FIELD_A) + 5,
    )
    parser.write(_FIELD_A + b"--b--")
    parser.write(b"\r\nan epilogue past every limit\r\n")
    parser.end()
    assert events == ["field a=v", "done"]
