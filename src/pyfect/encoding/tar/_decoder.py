"""Tar archive bytes to entries, pulled."""

from __future__ import annotations

from pyfect.encoding._archive import NEED_INPUT, ByteQueue, NeedInput
from pyfect.encoding.tar._header import (
    BLOCK,
    PERMISSION_BITS,
    RawHeader,
    apply_pax,
    entry_type,
    invalid_header,
    is_header_only,
    padding,
    parse_header,
    parse_pax,
    read_string,
    to_mtime,
    unsupported,
)
from pyfect.encoding.tar._model import Header, TarError

_MAX_META_SIZE = 1024 * 1024  # PAX and GNU long name data
_ZERO_BLOCK = bytes(BLOCK)


class Decoder:
    """``next`` skips unread body bytes; ``read`` consumes the current body. Both
    keep their progress across ``NEED_INPUT``."""

    def __init__(self) -> None:
        self._queue = ByteQueue()
        self._ended = False
        self._finished = False
        self._closed = False
        # Incremented whenever the current body is invalidated
        self.generation = 0
        self._remaining = 0
        self._pad = 0
        # Bytes to discard before the next header
        self._skip = 0
        self._zero_block = False
        # Archive offset of the last header block read, for error messages
        self._at = 0
        # An extended header whose data is still to be read
        self._meta: RawHeader | None = None
        self._pax: dict[str, str] | None = None
        # Records of the PAX global headers read so far
        self._global: dict[str, str] | None = None
        self._long_name = ""
        self._long_link = ""

    def push(self, chunk: bytes) -> None:
        if not self._finished:
            self._queue.push(chunk)

    def end(self) -> None:
        self._ended = True

    def close(self) -> None:
        self._closed = True
        self.generation += 1
        self._queue.clear()

    def next(self) -> Header | NeedInput | None:
        """The next entry header, or ``None`` once the archive and the input have
        ended. Input after the end of the archive is discarded."""
        try:
            return self._advance()
        except TarError as error:
            # Header errors are raised where the archive offset is not known
            if error.kind in ("InvalidHeader", "Unsupported"):
                raise TarError(error.kind, f"{error.message} (header at byte {self._at})") from None
            raise

    def _advance(self) -> Header | NeedInput | None:  # noqa: PLR0911, PLR0912
        self.generation += 1
        self._skip += self._remaining + self._pad
        self._remaining = 0
        self._pad = 0
        queue = self._queue
        while True:
            if self._finished:
                return self._finish()
            while self._skip > 0:
                if queue.length == 0:
                    return self._need_input()
                self._skip -= len(queue.take_some(self._skip))
            if self._meta is not None:
                size = self._meta.size
                typeflag = self._meta.typeflag
                total = size + padding(size)
                if queue.length < total:
                    return self._need_input()
                data = queue.take(total)[:size]
                self._meta = None
                if typeflag == "x":
                    self._pax = parse_pax(data)
                elif typeflag == "g":
                    self._add_global(parse_pax(data))
                elif typeflag == "L":
                    self._long_name = read_string(data, 0, size)
                else:
                    self._long_link = read_string(data, 0, size)
                continue
            if queue.length < BLOCK:
                if queue.length == 0 and self._ended:
                    return self._finish()
                return self._need_input()
            self._at = queue.consumed
            block = queue.take(BLOCK)
            if block == _ZERO_BLOCK:
                if self._zero_block:
                    return self._finish()
                self._zero_block = True
                continue
            if self._zero_block:
                raise invalid_header("non-zero block after an end-of-archive block")
            raw = parse_header(block)
            if raw.typeflag in ("x", "g", "L", "K"):
                if raw.size > _MAX_META_SIZE:
                    raise invalid_header(f"extended header of {raw.size} bytes exceeds the limit")
                self._meta = raw
                continue
            if raw.typeflag == "S":
                raise unsupported("GNU sparse files are not supported")
            header = self._to_header(raw)
            self._remaining = header.size
            self._pad = padding(header.size)
            return header

    def read(self, generation: int) -> tuple[bytes, ...] | NeedInput | None:
        """The buffered body bytes of the entry from ``generation``, or ``None``
        once the whole body has been read."""
        if generation != self.generation:
            raise TarError(
                "BodyConsumed",
                "tar entry body read after the archive stream ended"
                if self._closed
                else "tar entry body read after moving to the next entry",
            )
        if self._remaining == 0:
            return None
        if self._queue.length == 0:
            return self._need_input()
        chunks: list[bytes] = []
        while self._remaining > 0 and self._queue.length > 0:
            chunk = self._queue.take_some(self._remaining)
            self._remaining -= len(chunk)
            chunks.append(chunk)
        return tuple(chunks)

    def _need_input(self) -> NeedInput:
        if self._ended:
            raise _truncated(self._queue.consumed + self._queue.length)
        return NEED_INPUT

    def _finish(self) -> NeedInput | None:
        # An extended header must be followed by the entry it describes
        if not self._finished and (
            self._pax is not None or self._long_name != "" or self._long_link != ""
        ):
            raise _truncated(self._queue.consumed)
        self._finished = True
        self._queue.clear()
        return None if self._ended else NEED_INPUT

    def _add_global(self, records: dict[str, str]) -> None:
        """Global records apply to every entry that follows, except the ones that
        only describe a single entry, and an empty value removes a record."""
        for key, value in records.items():
            if key in ("path", "linkpath", "size"):
                continue
            if value != "":
                if self._global is None:
                    self._global = {}
                self._global[key] = value
            elif self._global is not None:
                self._global.pop(key, None)
        if not self._global:
            self._global = None

    def _to_header(self, raw: RawHeader) -> Header:
        # The records of the entry's own extended header override global ones
        if self._global is None:
            records = self._pax
        else:
            records = self._global if self._pax is None else {**self._global, **self._pax}
        rest = {} if records is None else apply_pax(raw, records)
        # Empty GNU long names are ignored, as in Go
        if self._long_name != "":
            raw.path = self._long_name
        if self._long_link != "":
            raw.link_target = self._long_link
        self._pax = None
        self._long_name = ""
        self._long_link = ""
        mtime = to_mtime(raw.mtime_millis)
        kind = entry_type(raw.typeflag, raw.path)
        device = kind in ("CharDevice", "BlockDevice")
        return Header(
            path=raw.path,
            type=kind,
            typeflag=raw.typeflag,
            size=0 if is_header_only(kind) else raw.size,
            mode=raw.mode & PERMISSION_BITS,
            uid=raw.uid,
            gid=raw.gid,
            uname=raw.uname,
            gname=raw.gname,
            mtime=mtime,
            link_target=None if raw.link_target == "" else raw.link_target,
            dev_major=raw.dev_major if device else None,
            dev_minor=raw.dev_minor if device else None,
            pax=rest,
        )


def _truncated(at: int) -> TarError:
    return TarError("Truncated", f"unexpected end of tar archive at byte {at}")
