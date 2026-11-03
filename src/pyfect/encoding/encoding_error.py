"""The error of the binary encodings (Effect's ``encoding/EncodingError``)."""

from __future__ import annotations

from typing import TypeIs

from pyfect._binary_codecs import EncodingError
from pyfect._public import publish


def is_encoding_error(value: object) -> TypeIs[EncodingError]:
    return isinstance(value, EncodingError)


__all__ = ["EncodingError", "is_encoding_error"]

publish(globals())
