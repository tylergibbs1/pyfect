"""Brotli through the ``brotli`` extra (brotlicffi, which keeps the GIL off on a
free-threaded CPython); ``http.platform`` offers ``br`` when it is installed."""

from typing import Any

from pyfect._extras import missing_extra

try:
    import brotlicffi as _library  # pyright: ignore[reportMissingTypeStubs]
except ImportError as error:
    raise missing_extra("Brotli compression", "brotli", error) from error

_NODE_DEFAULT_QUALITY = 11


class Brotli:
    __slots__ = ("_compressor",)

    def __init__(self, level: int | None) -> None:
        quality = _NODE_DEFAULT_QUALITY if level is None else level
        library: Any = _library
        self._compressor: Any = library.Compressor(quality=quality)

    def chunk(self, data: bytes) -> bytes:
        return self._compressor.process(data) + self._compressor.flush()

    def finish(self) -> bytes:
        return self._compressor.finish()
