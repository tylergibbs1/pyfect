"""``multipart/form-data`` encoding of a ``FormData`` body, as ``fetch``
writes one."""

from __future__ import annotations

import secrets

from pyfect._js import text_encode
from pyfect.http import body as _body
from pyfect.http.body import FileSourceError
from pyfect.stream import Stream, from_iterable, succeed


def _quote(text: str) -> str:
    return text.replace("\r", "%0D").replace("\n", "%0A").replace('"', "%22")


def encode(form: _body.FormData) -> tuple[bytes | Stream[bytes, FileSourceError], str]:
    """The encoded form and its content type (with the boundary): bytes
    when every file is bytes, else a stream reading each file source as it
    is pulled."""
    boundary = f"----formdata-pyfect-{secrets.token_hex(12)}"
    pieces: list[bytes | _body.File] = []
    head = bytearray()
    for name, value in form.entries:
        head += text_encode(f"--{boundary}\r\n")
        if isinstance(value, str):
            head += text_encode(f'Content-Disposition: form-data; name="{_quote(name)}"\r\n\r\n')
            head += text_encode(value) + b"\r\n"
            continue
        head += text_encode(
            f'Content-Disposition: form-data; name="{_quote(name)}"; '
            f'filename="{_quote(value.name)}"\r\n'
        )
        head += text_encode(f"Content-Type: {value.content_type}\r\n\r\n")
        if isinstance(value.content, bytes):
            head += value.content
        else:
            pieces.append(bytes(head))
            pieces.append(value)
            head = bytearray()
        head += b"\r\n"
    head += text_encode(f"--{boundary}--\r\n")
    content_type = f"multipart/form-data; boundary={boundary}"
    if not pieces:
        return bytes(head), content_type
    pieces.append(bytes(head))
    return from_iterable(pieces).flat_map(_piece), content_type


def _piece(piece: bytes | _body.File) -> Stream[bytes, FileSourceError]:
    return succeed(piece) if isinstance(piece, bytes) else piece.stream()


def has_file_source(form: _body.FormData) -> bool:
    """Whether a file of ``form`` is a stream source, not bytes."""
    return any(
        not isinstance(value, str) and not isinstance(value.content, bytes)
        for _name, value in form.entries
    )
