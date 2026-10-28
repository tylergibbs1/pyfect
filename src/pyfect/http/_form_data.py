"""``multipart/form-data`` encoding of a ``FormData`` body, as ``fetch``
writes one."""

from __future__ import annotations

import secrets

from pyfect.http import body as _body


def _quote(text: str) -> str:
    return text.replace("\r", "%0D").replace("\n", "%0A").replace('"', "%22")


def encode(form: _body.FormData) -> tuple[bytes, str]:
    """The encoded form and its content type (with the boundary)."""
    boundary = f"----formdata-pyfect-{secrets.token_hex(12)}"
    out = bytearray()
    for name, value in form.entries:
        out += f"--{boundary}\r\n".encode()
        if isinstance(value, str):
            out += f'Content-Disposition: form-data; name="{_quote(name)}"\r\n\r\n'.encode()
            out += value.encode() + b"\r\n"
        else:
            disposition = (
                f'Content-Disposition: form-data; name="{_quote(name)}"; '
                f'filename="{_quote(value.name)}"\r\n'
            )
            out += disposition.encode()
            out += f"Content-Type: {value.content_type}\r\n\r\n".encode()
            out += value.content + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"
