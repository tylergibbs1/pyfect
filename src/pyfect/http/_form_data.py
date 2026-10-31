"""``multipart/form-data`` encoding of a ``FormData`` body, as ``fetch``
writes one."""

from __future__ import annotations

import secrets

from pyfect._js import text_encode
from pyfect.http import body as _body


def _quote(text: str) -> str:
    return text.replace("\r", "%0D").replace("\n", "%0A").replace('"', "%22")


def encode(form: _body.FormData) -> tuple[bytes, str]:
    """The encoded form and its content type (with the boundary)."""
    boundary = f"----formdata-pyfect-{secrets.token_hex(12)}"
    out = bytearray()
    for name, value in form.entries:
        out += text_encode(f"--{boundary}\r\n")
        if isinstance(value, str):
            out += text_encode(f'Content-Disposition: form-data; name="{_quote(name)}"\r\n\r\n')
            out += text_encode(value) + b"\r\n"
        else:
            disposition = (
                f'Content-Disposition: form-data; name="{_quote(name)}"; '
                f'filename="{_quote(value.name)}"\r\n'
            )
            out += text_encode(disposition)
            out += text_encode(f"Content-Type: {value.content_type}\r\n\r\n")
            out += value.content + b"\r\n"
    out += text_encode(f"--{boundary}--\r\n")
    return bytes(out), f"multipart/form-data; boundary={boundary}"
